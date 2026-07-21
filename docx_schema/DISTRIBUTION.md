# docx_schema DISTRIBUTION

Portable source bundle for a two-command workflow:

1. `python -m docx_schema propose-mapping <docx> --out <mapping.md>`
2. `python -m docx_schema create-schema <docx> <mapping.md> --out-dir <dir>`

The current implementation treats each distinct header signature as a separate column set, emits a crosswalk for it, and then uses the reviewed mapping plus the source DOCX to generate one schema markdown file per table.

Table names are taken from the heading-styled (or short, heading-like) paragraph immediately before each table; long prose paragraphs are ignored so they never become table names, and tables without a usable heading fall back to `table_N`. Generated schema filenames sanitize illegal characters and are capped in length so they stay valid on Windows.

Invalid input is rejected with a clear message: a non-ZIP or non-DOCX file fails with an explicit "not a valid ZIP-based DOCX file" error rather than a low-level archive exception.

The workflow state also records ISO timestamps with microsecond precision so successive updates remain distinct in the generated session state.

## Run it

```bash
python -m docx_schema propose-mapping ./sample.docx --out ./mapping.md
python -m docx_schema create-schema ./sample.docx @./mapping.md --out-dir ./schema
```

## Output format

`propose-mapping` emits one section per distinct column set with a crosswalk and table membership list:

```markdown
## Column Set 1

- Tables: Customer

| Extracted Column | Target Column |
|---|---|
| Field | Column |
| Type | Type |
| Required | Nullable |
| Purpose | Description |
|  | Primary Key |
|  | Foreign Key |
|  | Details |
|  | Source |
```

`create-schema` reads the source `.docx` plus the reviewed mapping and writes one `{table}_schema.md` per table, each ending with visible rider stubs:

```markdown
## Custom Riders

_None defined._

## Provenance / Audit Columns

_None defined._
```

## Embedded source

### `__main__.py`

```python
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from docx_schema.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

### `__init__.py`

```python
from docx_schema.cli import main
from docx_schema.mapping import (
    parse_mapping_markdown,
    project_table,
    propose_mapping,
    render_mapping_markdown,
    render_schema_markdown,
    write_schema_files,
)
from docx_schema.models import ColumnSet, SourceTable, TableSchema, TARGET_COLUMNS

__all__ = [
    "ColumnSet",
    "SourceTable",
    "TARGET_COLUMNS",
    "TableSchema",
    "main",
    "parse_mapping_markdown",
    "project_table",
    "propose_mapping",
    "render_mapping_markdown",
    "render_schema_markdown",
    "write_schema_files",
]
```

### `docx_reader.py`

```python
from __future__ import annotations

from pathlib import Path


def normalize_docx_path(path: str | Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str((Path.cwd() / candidate).resolve())
```

### `models.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field


TARGET_COLUMNS = [
    "Column",
    "Type",
    "Nullable",
    "Primary Key",
    "Foreign Key",
    "Details",
    "Description",
    "Source",
]


@dataclass
class SourceTable:
    name: str
    headers: list[str]
    rows: list[list[str]]


@dataclass
class TableSchema:
    name: str
    columns: list[list[str]]


@dataclass
class ColumnSet:
    table_names: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)
```

### `mapping.py`

```python
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

    for table in _extract_docx_tables(str(source_docx)):
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
    # Fall back for unstyled captions: accept only short, heading-like lines so
    # prose paragraphs are not mistaken for table names.
    return len(text) <= 64 and len(text.split()) <= 8


def _schema_filename(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned[:80].strip()
    return f"{cleaned or 'table'}_schema.md"


def _local_name(tag: str) -> str:
    return tag.split("}", maxsplit=1)[-1]
```

### `cli.py`

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docx_schema.docx_reader import normalize_docx_path
from docx_schema.mapping import parse_mapping_markdown, propose_mapping, render_mapping_markdown, write_schema_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m docx_schema", description="Create mapping and schema markdown files from DOCX tables.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose-mapping", help="Create a self-contained mapping markdown from a DOCX file.")
    propose.add_argument("source", help="Path to source .docx")
    propose.add_argument("--out", default="./mapping.md", help="Output mapping markdown path")
    propose.set_defaults(handler=_run_propose_mapping)

    create = subparsers.add_parser("create-schema", help="Create per-table schema files from source DOCX plus reviewed mapping markdown.")
    create.add_argument("source", help="Path to source .docx (leading @ allowed)")
    create.add_argument("mapping", help="Path to mapping markdown (leading @ allowed)")
    create.add_argument("--out-dir", default="./schema", help="Output directory for schema markdown files")
    create.set_defaults(handler=_run_create_schema)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = _normalize_argv(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except ValueError as error:
        message = str(error).strip()
        if message.startswith("error:"):
            print(message)
        else:
            print(f"error: {message}")
        return 1


def _run_propose_mapping(args: argparse.Namespace) -> int:
    column_sets = propose_mapping(str(normalize_docx_path(args.source)))
    text = render_mapping_markdown(column_sets)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    table_count = sum(len(column_set.table_names) for column_set in column_sets)
    print(f"Wrote mapping for {table_count} table(s) across {len(column_sets)} column set(s)")
    print(out_path)
    return 0


def _run_create_schema(args: argparse.Namespace) -> int:
    source_path = normalize_docx_path(args.source)
    mapping_path = args.mapping[1:] if args.mapping.startswith("@") else args.mapping
    text = Path(mapping_path).read_text(encoding="utf-8")
    column_sets = parse_mapping_markdown(text)
    written = write_schema_files(source_path, column_sets, args.out_dir)

    print(f"Wrote {len(written)} schema file(s) from {len(column_sets)} column set(s)")
    for path in written:
        print(path)
    return 0


def _normalize_argv(argv: list[str]) -> list[str]:
    if argv and argv[0].startswith("/"):
        return [argv[0][1:], *argv[1:]]
    return argv


if __name__ == "__main__":
    raise SystemExit(main())
```
