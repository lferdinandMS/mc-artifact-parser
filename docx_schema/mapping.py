from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx_schema.models import ColumnSet, SourceTable, TableSchema, TARGET_COLUMNS

_MAX_DOCUMENT_XML_BYTES = 10 * 1024 * 1024


def propose_mapping(path: str) -> list[ColumnSet]:
    tables = _extract_docx_tables(path)
    column_sets: list[ColumnSet] = []
    by_signature: dict[tuple[str, ...], ColumnSet] = {}

    for table in tables:
        signature = tuple(_normalize_header(header) for header in table.headers)
        column_set = by_signature.get(signature)
        if column_set is None:
            pairs = [(header, _default_target_column(header)) for header in table.headers]
            column_set = ColumnSet(pairs=pairs)
            by_signature[signature] = column_set
            column_sets.append(column_set)

        column_set.tables.append(project_table(table, column_set.pairs))

    return column_sets


def project_table(table: SourceTable, pairs: list[tuple[str, str]]) -> TableSchema:
    mapping = {source: target for source, target in pairs}
    projected_rows: list[list[str]] = []

    for source_row in table.rows:
        target_row = ["" for _ in TARGET_COLUMNS]
        for index, source_header in enumerate(table.headers):
            if index >= len(source_row):
                continue

            target_header = mapping.get(source_header, "")
            if target_header not in TARGET_COLUMNS:
                continue

            target_index = TARGET_COLUMNS.index(target_header)
            value = source_row[index]
            if target_row[target_index]:
                target_row[target_index] = f"{target_row[target_index]}; {value}"
            else:
                target_row[target_index] = value

        projected_rows.append(target_row)

    return TableSchema(name=table.name, columns=projected_rows)


def render_mapping_markdown(column_sets: list[ColumnSet]) -> str:
    lines = ["# Proposed Mapping", ""]

    for index, column_set in enumerate(column_sets, start=1):
        lines.append(f"## Column Set {index}")
        lines.append("")
        lines.append("| Extracted Column | Target Column |")
        lines.append("|---|---|")
        for source, target in column_set.pairs:
            lines.append(f"| {source} | {target} |")
        lines.append("")

        for table in column_set.tables:
            lines.append(f"### {table.name}")
            lines.append("")
            lines.extend(_render_wide_table_lines(table.columns))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_mapping_markdown(text: str) -> list[ColumnSet]:
    lines = text.splitlines()
    column_sets: list[ColumnSet] = []
    current_set: ColumnSet | None = None
    index = 0

    while index < len(lines):
        line = lines[index].strip()

        if re.match(r"^##\s+Column Set\s+\d+\s*$", line):
            current_set = ColumnSet(pairs=[])
            column_sets.append(current_set)
            index += 1
            continue

        if current_set is None:
            index += 1
            continue

        if line == "| Extracted Column | Target Column |":
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = _parse_markdown_row(lines[index])
                if len(row) >= 2:
                    current_set.pairs.append((row[0], row[1]))
                index += 1
            continue

        if line.startswith("### "):
            table_name = line[4:].strip()
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1

            if index >= len(lines) or not lines[index].strip().startswith("|"):
                continue

            header = _parse_markdown_row(lines[index])
            index += 1
            if index < len(lines) and lines[index].strip().startswith("|"):
                index += 1

            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = _parse_markdown_row(lines[index])
                padded = row + [""] * max(0, len(header) - len(row))
                rows.append(padded[: len(header)])
                index += 1

            if header == TARGET_COLUMNS:
                current_set.tables.append(TableSchema(name=table_name, columns=rows))
            continue

        index += 1

    if not any(column_set.tables for column_set in column_sets):
        raise ValueError("no tables found in mapping markdown")

    return column_sets


def render_schema_markdown(table: TableSchema) -> str:
    lines = [f"# {table.name} Schema", ""]
    lines.extend(_render_wide_table_lines(table.columns))
    lines.extend(
        [
            "",
            "## Custom Riders",
            "",
            "_None defined._",
            "",
            "## Provenance / Audit Columns",
            "",
            "_None defined._",
            "",
            "Supplied by the target adapter for the destination platform.",
            "",
        ]
    )
    return "\n".join(lines)


def write_schema_files(column_sets: list[ColumnSet], out_dir: str | Path) -> list[Path]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    seen_names: set[str] = set()

    for column_set in column_sets:
        for table in column_set.tables:
            if table.name in seen_names:
                raise ValueError(f"error: duplicate table name across column sets: {table.name}")

            seen_names.add(table.name)
            path = output_dir / f"{_slugify(table.name)}_schema.md"
            path.write_text(render_schema_markdown(table), encoding="utf-8")
            written.append(path)

    return written


def _extract_docx_tables(path: str) -> list[SourceTable]:
    with zipfile.ZipFile(path) as archive:
        try:
            document_xml = archive.getinfo("word/document.xml")
        except KeyError as exc:
            raise ValueError(f"{path} is missing word/document.xml") from exc

        if document_xml.file_size > _MAX_DOCUMENT_XML_BYTES:
            raise ValueError("DOCX word/document.xml exceeds the maximum supported size.")

        xml = archive.read(document_xml)

    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ValueError("DOCX word/document.xml contains disallowed XML declarations.")

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(xml)
    body = root.find(".//w:body", ns)
    if body is None:
        return []

    tables: list[SourceTable] = []
    pending_name: str | None = None

    for child in body:
        tag = _local_name(child.tag)

        if tag == "p":
            text = "".join(node.text for node in child.findall(".//w:t", ns) if node.text).strip()
            if text:
                pending_name = text
            continue

        if tag != "tbl":
            continue

        rows: list[list[str]] = []
        for row in child.findall("./w:tr", ns):
            cells: list[str] = []
            for cell in row.findall("./w:tc", ns):
                text = "".join(node.text for node in cell.findall(".//w:t", ns) if node.text).strip()
                cells.append(text)
            if any(cells):
                rows.append(cells)

        if not rows:
            continue

        name = pending_name or f"table_{len(tables) + 1}"
        headers = rows[0]
        table_rows = rows[1:]
        tables.append(SourceTable(name=name, headers=headers, rows=table_rows))
        pending_name = None

    return tables


def _render_wide_table_lines(rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(TARGET_COLUMNS) + " |",
        "|" + "|".join(["---"] * len(TARGET_COLUMNS)) + "|",
    ]

    for row in rows:
        padded = row + [""] * max(0, len(TARGET_COLUMNS) - len(row))
        lines.append("| " + " | ".join(padded[: len(TARGET_COLUMNS)]) + " |")

    return lines


def _parse_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [part.strip() for part in stripped.split("|")]


def _default_target_column(header: str) -> str:
    key = _normalize_header(header)
    aliases = {
        "column": "Column",
        "column name": "Column",
        "name": "Column",
        "type": "Type",
        "data type": "Type",
        "datatype": "Type",
        "nullable": "Nullable",
        "null": "Nullable",
        "primary key": "Primary Key",
        "pk": "Primary Key",
        "foreign key": "Foreign Key",
        "fk": "Foreign Key",
        "details": "Details",
        "description": "Description",
        "source": "Source",
    }

    if key in aliases:
        return aliases[key]

    for target in TARGET_COLUMNS:
        if key == _normalize_header(target):
            return target

    return ""


def _normalize_header(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_")
    return cleaned.lower() or "table"


def _local_name(tag: str) -> str:
    return tag.split("}", maxsplit=1)[-1]
