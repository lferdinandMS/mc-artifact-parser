from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx_schema.models import ColumnSet, SourceTable, TableSchema, TARGET_COLUMNS

_MAX_DOCUMENT_XML_BYTES = 10 * 1024 * 1024


def propose_mapping(path: str) -> list[ColumnSet]:
    tables = _extract_tables(path)
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


def write_schema_files(source_docx: str | Path, column_sets: list[ColumnSet], out_dir: str | Path) -> list[Path]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    seen_names: set[str] = set()
    seen_paths: set[Path] = set()
    column_set_by_signature = {_signature_from_pairs(column_set.pairs): column_set for column_set in column_sets}

    for table in _extract_tables(str(source_docx)):
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


def _extract_tables(path: str) -> list[SourceTable]:
    if Path(path).suffix.lower() == ".svg":
        return _extract_svg_tables(path)
    return _extract_docx_tables(path)


def _extract_docx_tables(path: str) -> list[SourceTable]:
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                document_xml = archive.getinfo("word/document.xml")
            except KeyError as exc:
                raise ValueError(f"{path} is missing word/document.xml") from exc

            if document_xml.file_size > _MAX_DOCUMENT_XML_BYTES:
                raise ValueError("DOCX word/document.xml exceeds the maximum supported size.")

            xml = archive.read(document_xml)
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"{path} is not a valid ZIP-based DOCX file. "
            "Please provide a real .docx generated by Microsoft Word or save the document as .docx before retrying."
        ) from exc

    if re.search(br"<!\s*(doctype|entity)\b", xml, flags=re.IGNORECASE):
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
            if text and _looks_like_table_name(child, text, ns):
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


def _looks_like_table_name(paragraph: ET.Element, text: str, ns: dict[str, str]) -> bool:
    style_el = paragraph.find("w:pPr/w:pStyle", ns)
    style = (style_el.get(f"{{{ns['w']}}}val", "") if style_el is not None else "") or ""
    if any(marker in style.lower() for marker in ("heading", "title", "caption")):
        return True
    # Fall back for unstyled captions: accept only short, heading-like lines and
    # reject prose sentences or "Label: value" lines (e.g. "Used by: ...",
    # "Routes to: Outflow Worker as a hard constraint.") so descriptive body text
    # is never mistaken for a table name.
    if len(text) > 48 or len(text.split()) > 6:
        return False
    if text[-1] in ".!?:;,":
        return False
    if ": " in text:
        return False
    return True


def _schema_filename(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned[:80].strip()
    return f"{cleaned or 'table'}_schema.md"


def _local_name(tag: str) -> str:
    return tag.split("}", maxsplit=1)[-1]


_SVG_HEADER_WORDS = {"column", "field", "name", "type", "data type", "datatype"}


def _extract_svg_tables(path: str) -> list[SourceTable]:
    data = Path(path).read_bytes()
    if len(data) > _MAX_DOCUMENT_XML_BYTES:
        raise ValueError("SVG file exceeds the maximum supported size.")

    if re.search(br"<!\s*(doctype|entity)\b", data, flags=re.IGNORECASE):
        raise ValueError("SVG contains disallowed XML declarations.")

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"{path} is not a valid SVG (XML parse failed): {exc}") from exc

    if _local_name(root.tag).lower() != "svg":
        raise ValueError(
            f"{path} is not an SVG file (root element is <{_local_name(root.tag)}>)."
        )

    nodes = _collect_svg_text_nodes(root)
    if not nodes:
        raise ValueError(f"No text could be extracted from {path}.")

    pairs = _drop_leading_header_pair(_pair_svg_texts(nodes))
    if not pairs:
        raise ValueError(f"No column/type pairs could be extracted from {path}.")

    name = _infer_svg_entity_name(path)
    rows = [[column, type_] for column, type_ in pairs]
    return [SourceTable(name=name, headers=["Column", "Type"], rows=rows)]


def _collect_svg_text_nodes(root: ET.Element) -> list[tuple[float, float, str]]:
    nodes: list[tuple[float, float, str]] = []
    for element in root.iter():
        if _local_name(element.tag).lower() != "text":
            continue

        text = re.sub(r"\s+", " ", "".join(element.itertext()).strip())
        if not text:
            continue

        x = _svg_coord(element, "x")
        y = _svg_coord(element, "y")
        if x is None or y is None:
            for child in element.iter():
                if _local_name(child.tag).lower() != "tspan":
                    continue
                if x is None:
                    x = _svg_coord(child, "x")
                if y is None:
                    y = _svg_coord(child, "y")
                break

        nodes.append((x or 0.0, y or 0.0, text))

    return nodes


def _svg_coord(element: ET.Element, attribute: str) -> float | None:
    raw = element.get(attribute)
    if raw is None:
        return None
    match = re.match(r"-?\d+(?:\.\d+)?", raw.strip())
    if match is None:
        return None
    return float(match.group())


def _pair_svg_texts(nodes: list[tuple[float, float, str]]) -> list[tuple[str, str]]:
    # 1) Inline "column: type" (or tab-separated) in a single text node.
    inline: list[tuple[str, str]] | None = []
    for _x, _y, text in nodes:
        match = re.match(r"^(.+?)[\t:]\s*(.+)$", text)
        if match is None:
            inline = None
            break
        inline.append((match.group(1).strip(), match.group(2).strip()))
    if inline:
        return _dedupe_pairs(inline)

    # 2) Two-column geometry: split on the horizontal midpoint, align by row (y).
    xs = [x for x, _y, _text in nodes]
    if xs and (max(xs) - min(xs)) > 1.0:
        midpoint = (max(xs) + min(xs)) / 2.0
        rows: dict[int, dict[str, list[tuple[float, str]]]] = {}
        for x, y, text in nodes:
            bucket = rows.setdefault(round(y), {"left": [], "right": []})
            bucket["left" if x <= midpoint else "right"].append((x, text))

        pairs: list[tuple[str, str]] = []
        for key in sorted(rows):
            left = sorted(rows[key]["left"])
            right = sorted(rows[key]["right"])
            if left and right:
                pairs.append((left[0][1], right[-1][1]))
        if pairs:
            return _dedupe_pairs(pairs)

    # 3) Fallback: pair consecutive text nodes in document order.
    texts = [text for _x, _y, text in nodes]
    fallback = [(texts[i], texts[i + 1]) for i in range(0, len(texts) - 1, 2)]
    return _dedupe_pairs(fallback)


def _dedupe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for column, type_ in pairs:
        key = _normalize_header(column)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append((column.strip(), type_.strip()))
    return deduped


def _drop_leading_header_pair(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if pairs:
        column, type_ = pairs[0]
        if _normalize_header(column) in _SVG_HEADER_WORDS and _normalize_header(type_) in _SVG_HEADER_WORDS:
            return pairs[1:]
    return pairs


def _infer_svg_entity_name(path: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", Path(path).stem).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "table_1"
