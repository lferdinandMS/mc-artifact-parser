from __future__ import annotations

import re
from pathlib import Path

from docx_schema.models import ColumnSet, Relationship, SourceTable, TableSchema, TARGET_COLUMNS
from docx_schema.sources import read_tables


def propose_mapping(path: str) -> list[ColumnSet]:
    tables = read_tables(path)
    column_sets: list[ColumnSet] = []
    by_signature: dict[tuple[str, ...], ColumnSet] = {}

    for table in tables:
        signature = tuple(_normalize_header(header) for header in table.headers)
        column_set = by_signature.get(signature)
        if column_set is None:
            pairs = [(header, _default_target_column(header)) for header in table.headers]
            column_set = ColumnSet(table_names=[table.name], pairs=pairs)
            by_signature[signature] = column_set
            column_sets.append(column_set)
        else:
            column_set.table_names.append(table.name)

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
        if column_set.table_names:
            lines.append(f"- Tables: {', '.join(column_set.table_names)}")
            lines.append("")
        lines.append("| Extracted Column | Target Column |")
        lines.append("|---|---|")
        seen_targets = {target for _, target in column_set.pairs if target}
        for source, target in column_set.pairs:
            lines.append(f"| {source} | {target} |")
        for target in TARGET_COLUMNS:
            if target not in seen_targets:
                lines.append(f"|  | {target} |")
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
            current_set = ColumnSet()
            column_sets.append(current_set)
            index += 1
            continue

        if current_set is None:
            index += 1
            continue

        if line.startswith("- Tables:"):
            table_names = line.split(":", 1)[1].strip()
            if table_names:
                current_set.table_names = [name.strip() for name in table_names.split(",") if name.strip()]
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

        index += 1

    if not any(column_set.pairs for column_set in column_sets):
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


def render_relationships_markdown(relationships: list[Relationship]) -> str:
    lines = ["# Relationships", ""]

    if not relationships:
        lines.append("_No relationships found._")
        return "\n".join(lines) + "\n"

    lines.append("| Source Table | Source Column | Target Table | Target Column |")
    lines.append("|---|---|---|---|")
    for relationship in relationships:
        lines.append(
            f"| {relationship.source_table} | {relationship.source_column or '*'} "
            f"| {relationship.target_table} | {relationship.target_column or '*'} |"
        )

    lines.append("")
    lines.append("## Mermaid ERD")
    lines.append("")
    lines.append("```mermaid")
    lines.append("erDiagram")
    for relationship in relationships:
        label = f"{relationship.source_column or '*'} -> {relationship.target_column or '*'}"
        lines.append(
            f'    {relationship.source_table} ||--o{{ {relationship.target_table} : "{label}"'
        )
    lines.append("```")

    return "\n".join(lines) + "\n"


def write_schema_files(source_docx: str | Path, column_sets: list[ColumnSet], out_dir: str | Path) -> list[Path]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    seen_names: set[str] = set()
    seen_paths: set[Path] = set()
    column_set_by_signature = {_signature_from_pairs(column_set.pairs): column_set for column_set in column_sets}

    for table in read_tables(str(source_docx)):
        signature = _signature_from_headers(table.headers)
        column_set = column_set_by_signature.get(signature)
        if column_set is None:
            raise ValueError(f"no column set found for table: {table.name}")

        if table.name in seen_names:
            raise ValueError(f"duplicate table name across column sets: {table.name}")

        seen_names.add(table.name)
        projected = project_table(table, column_set.pairs)
        path = output_dir / _schema_filename(table.name)
        if path in seen_paths:
            raise ValueError(f"duplicate output schema filename: {path.name}")

        seen_paths.add(path)
        path.write_text(render_schema_markdown(projected), encoding="utf-8")
        written.append(path)

    return written


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
        "field": "Column",
        "type": "Type",
        "data type": "Type",
        "datatype": "Type",
        "nullable": "Nullable",
        "null": "Nullable",
        "required": "Nullable",
        "required field": "Nullable",
        "optional": "Nullable",
        "primary key": "Primary Key",
        "pk": "Primary Key",
        "foreign key": "Foreign Key",
        "fk": "Foreign Key",
        "details": "Details",
        "detail": "Details",
        "notes": "Details",
        "description": "Description",
        "purpose": "Description",
        "source": "Source",
    }

    if key in aliases:
        return aliases[key]

    if key.startswith("field") or key.startswith("column"):
        return "Column"

    if key.startswith("type") or key.startswith("data type") or key.startswith("datatype"):
        return "Type"

    if key.startswith("required") or key.startswith("nullable") or key.startswith("optional"):
        return "Nullable"

    if key.startswith("purpose") or key.startswith("description"):
        return "Description"

    if key.startswith("detail") or key.startswith("note") or key.startswith("comment"):
        return "Details"

    for target in TARGET_COLUMNS:
        if key == _normalize_header(target):
            return target

    return ""


def _normalize_header(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _signature_from_headers(headers: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_header(header) for header in headers)


def _signature_from_pairs(pairs: list[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(
        _normalize_header(source)
        for source, _target in pairs
        if source and _normalize_header(source)
    )


def _schema_filename(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned[:80].strip()
    return f"{cleaned or 'table'}_schema.md"
