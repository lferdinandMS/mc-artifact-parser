# docx_schema — Portable Source Bundle & Setup Guide

This document contains the **complete source** of the `docx_schema` package
plus step-by-step instructions to set it up in a customer environment. Everything
below is the standard library only — no third-party packages, no network access.

The workflow is two commands:

1. `propose-mapping` — read a `.docx` and write a reviewer-editable **mapping** markdown.
2. `create-schema` — read the (edited) mapping and write one `{table}_schema.md` per table.

---

## 1. Prerequisites

- **Python 3.13.x** on PATH (validated on 3.13.11 and 3.13.14; `python --version` → `Python 3.13.x`).
- No third-party packages. No internet connection required.
- A terminal (examples use Windows PowerShell).

---

## 2. Create the package

Create a folder named `docx_schema` and add the eight files below, each with the
exact contents shown. The final layout must be:

```text
docx_schema/
    __init__.py
    __main__.py
    models.py
    docx_reader.py
    mapping.py
    schema.py
    cli.py
    RUNBOOK.md   (optional operator guide; see the repo)
```

Run all commands from the **parent** folder that contains `docx_schema/`.

### 2.1 `docx_schema/__init__.py`

```python
"""Minimal DOCX-to-schema toolkit.

Two operations:

* ``propose-mapping`` reads a ``.docx`` and writes a reviewer-editable
  proposed mapping markdown file.
* ``create-schema`` reads a (reviewer-edited) mapping markdown file and
  writes one ``{table}_schema.md`` file per table.

The package is intentionally self-contained and depends only on the Python
standard library.
"""

from __future__ import annotations

from .models import Column, Table
from .mapping import build_tables_from_docx, render_mapping_markdown
from .schema import parse_mapping_markdown, render_schema_markdown, write_schema_files

__all__ = [
    "Column",
    "Table",
    "build_tables_from_docx",
    "render_mapping_markdown",
    "parse_mapping_markdown",
    "render_schema_markdown",
    "write_schema_files",
]
```

### 2.2 `docx_schema/__main__.py`

```python
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

### 2.3 `docx_schema/models.py`

```python
"""Data model shared by the propose-mapping and create-schema steps."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Column:
    """A single column definition.

    ``source_name`` records what was detected in the source document, while
    ``name`` is the target column name used in the generated schema. During
    ``propose-mapping`` the two are seeded to the same value so a reviewer can
    edit the target independently.
    """

    name: str
    source_name: str = ""
    data_type: str | None = None
    nullable: bool | None = None
    primary_key: bool = False
    foreign_key: str | None = None
    details: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.source_name:
            self.source_name = self.name


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
```

### 2.4 `docx_schema/docx_reader.py`

```python
"""Read ordered content blocks from a ``.docx`` file using only stdlib.

Security hardening mirrors the original adapter: the archive member is size
capped, and DOCTYPE/ENTITY declarations are rejected to avoid XML external
entity (XXE = XML eXternal Entity) attacks.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W_NS}
_MAX_DOCUMENT_XML_BYTES = 10 * 1024 * 1024


@dataclass
class Paragraph:
    text: str
    style: str = ""


@dataclass
class WordTable:
    rows: list[list[str]]


def read_blocks(path: str) -> list[Paragraph | WordTable]:
    """Return paragraphs and tables in document order."""

    xml = _read_document_xml(path)
    root = ET.fromstring(xml)
    body = root.find("w:body", _NS)
    if body is None:
        return []

    blocks: list[Paragraph | WordTable] = []
    for child in list(body):
        tag = _local(child.tag)
        if tag == "p":
            blocks.append(_read_paragraph(child))
        elif tag == "tbl":
            blocks.append(_read_table(child))
    return blocks


def _read_document_xml(path: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        try:
            info = archive.getinfo("word/document.xml")
        except KeyError as exc:
            raise ValueError(f"{path} is missing word/document.xml") from exc

        if info.file_size > _MAX_DOCUMENT_XML_BYTES:
            raise ValueError("DOCX word/document.xml exceeds the maximum supported size.")

        xml = archive.read(info)

    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ValueError("DOCX word/document.xml contains disallowed XML declarations.")

    return xml


def _read_paragraph(paragraph: ET.Element) -> Paragraph:
    text = "".join(node.text for node in paragraph.findall(".//w:t", _NS) if node.text).strip()
    style_el = paragraph.find("w:pPr/w:pStyle", _NS)
    style = ""
    if style_el is not None:
        style = style_el.get(f"{{{_W_NS}}}val", "") or ""
    return Paragraph(text=text, style=style)


def _read_table(table: ET.Element) -> WordTable:
    rows: list[list[str]] = []
    for row in table.findall("w:tr", _NS):
        cells: list[str] = []
        for cell in row.findall("w:tc", _NS):
            cell_text = " ".join(
                (node.text or "").strip()
                for node in cell.findall(".//w:t", _NS)
                if node.text
            ).strip()
            cells.append(cell_text)
        rows.append(cells)
    return WordTable(rows=rows)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_docx_path(raw: str) -> Path:
    """Strip a leading ``@`` (chat-style reference) and expand the path."""

    cleaned = raw.strip()
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    return Path(cleaned).expanduser()
```

### 2.5 `docx_schema/mapping.py`

```python
"""Build tables from a ``.docx`` and render a proposed mapping markdown.

The proposed mapping is a reviewer-editable document. A human confirms table
names, target column names, types, and flags before running ``create-schema``.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from .docx_reader import Paragraph, WordTable, read_blocks
from .models import Column, Table

_HEADING_MARKER = re.compile(r"^(?:entity|table)\s*[:\-]\s*(.+)$", re.IGNORECASE)
_OPEN_QUESTION = re.compile(r"^open\s*question\s*[:\-]\s*(.+)$", re.IGNORECASE)
_BULLET = re.compile(r"^[\-\*•]\s*")

# Paragraph column patterns (ordered by strength of signal).
_COL_PAREN = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*\((?P<type>[^)]+)\)\s*(?P<rest>.*)$")
_COL_COLON = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*:\s*(?P<type>[A-Za-z_][\w()\[\], ]*?)\s*(?:[—-]\s*(?P<rest>.*))?$")
_COL_UPPER = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s+(?P<type>[A-Z][A-Z0-9_]+)\b\s*(?P<rest>.*)$")

# Header synonyms for Word-table interpretation.
_HEADER_SYNONYMS = {
    "name": {"column", "column name", "field", "field name", "name", "attribute"},
    "type": {"type", "data type", "datatype"},
    "nullable": {"nullable", "null", "required", "optional"},
    "primary_key": {"primary key", "pk", "key", "primary"},
    "foreign_key": {"foreign key", "fk", "references", "reference"},
    "description": {"description", "desc", "notes", "note", "comment", "comments"},
}


def build_tables_from_docx(path: str) -> list[Table]:
    blocks = read_blocks(path)
    tables: list[Table] = []
    current: Table | None = None
    pending_heading: str | None = None

    def ensure_table(name: str) -> Table:
        for existing in tables:
            if existing.name == name:
                return existing
        created = Table(name=name)
        tables.append(created)
        return created

    for block in blocks:
        if isinstance(block, Paragraph):
            text = _BULLET.sub("", block.text).strip()
            if not text:
                continue

            heading = _HEADING_MARKER.match(text)
            if heading:
                current = ensure_table(heading.group(1).strip())
                pending_heading = None
                continue

            if _is_heading_style(block.style):
                pending_heading = text
                current = None
                continue

            question = _extract_question(text)
            if question:
                if current is not None:
                    current.open_questions.append(question)
                continue

            column = _parse_paragraph_column(text)
            if column:
                if current is None:
                    current = ensure_table(pending_heading or _fallback_name(tables))
                    pending_heading = None
                current.columns.append(column)
            continue

        # Word table block.
        columns = _parse_word_table(block)
        if not columns:
            continue
        if current is None:
            current = ensure_table(pending_heading or _fallback_name(tables))
            pending_heading = None
        current.columns.extend(columns)

    return [t for t in tables if t.columns or t.open_questions]


def _is_heading_style(style: str) -> bool:
    return style.lower().startswith("heading") or style.lower() == "title"


def _fallback_name(tables: list[Table]) -> str:
    return f"Table{len(tables) + 1}"


def _extract_question(text: str) -> str | None:
    match = _OPEN_QUESTION.match(text)
    if match:
        return match.group(1).strip()
    if text.endswith("?"):
        return text
    return None


def _parse_paragraph_column(text: str) -> Column | None:
    name: str | None = None
    data_type: str | None = None
    description: str | None = None

    paren = _COL_PAREN.match(text)
    colon = _COL_COLON.match(text)
    upper = _COL_UPPER.match(text)
    if paren:
        name = paren.group("name")
        data_type = paren.group("type").strip() or None
        description = (paren.group("rest") or "").strip() or None
    elif colon:
        name = colon.group("name")
        data_type = (colon.group("type") or "").strip() or None
        description = (colon.group("rest") or "").strip() or None
    elif upper:
        name = upper.group("name")
        data_type = upper.group("type").strip() or None
        description = (upper.group("rest") or "").strip() or None
    else:
        return None

    column = Column(name=name, data_type=data_type, description=description)
    _apply_flags_from_text(column, text)
    return column


def _parse_word_table(block: WordTable) -> list[Column]:
    rows = [r for r in block.rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    mapping = _map_header(header)
    if "name" not in mapping:
        # No recognizable header; assume first col = name, second = type.
        mapping = {"name": 0}
        if len(header) > 1:
            mapping["type"] = 1
        if len(header) > 2:
            mapping["description"] = len(header) - 1
        data_rows = rows  # treat the first row as data too
    else:
        data_rows = rows[1:]

    columns: list[Column] = []
    for row in data_rows:
        name = _cell(row, mapping.get("name"))
        if not name:
            continue
        column = Column(
            name=name,
            data_type=_cell(row, mapping.get("type")) or None,
            description=_cell(row, mapping.get("description")) or None,
        )
        nullable_cell = _cell(row, mapping.get("nullable"))
        column.nullable = _parse_nullable(nullable_cell, header_label=_label(header, mapping.get("nullable")))
        pk_cell = _cell(row, mapping.get("primary_key"))
        if _is_affirmative(pk_cell):
            column.primary_key = True
        fk_cell = _cell(row, mapping.get("foreign_key"))
        if fk_cell:
            column.foreign_key = fk_cell
        # Let free-text flags in the description reinforce detection.
        _apply_flags_from_text(column, " ".join(row))
        columns.append(column)
    return columns


def _map_header(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, label in enumerate(header):
        for key, synonyms in _HEADER_SYNONYMS.items():
            if key in mapping:
                continue
            if label in synonyms:
                mapping[key] = index
    return mapping


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _label(header: list[str], index: int | None) -> str:
    if index is None or index >= len(header):
        return ""
    return header[index]


def _parse_nullable(value: str, header_label: str = "") -> bool | None:
    if not value:
        return None
    lowered = value.strip().lower()
    affirmative = _is_affirmative(lowered)
    negative = lowered in {"no", "n", "false", "not null", "not nullable"}
    if header_label in {"required", "optional"}:
        # Invert: a "required = yes" means not nullable.
        if header_label == "required":
            if affirmative:
                return False
            if negative:
                return True
        if header_label == "optional":
            if affirmative:
                return True
            if negative:
                return False
    if affirmative:
        return True
    if negative:
        return False
    return None


def _is_affirmative(value: str) -> bool:
    return value.strip().lower() in {"yes", "y", "true", "x", "✓", "✔"}


def _apply_flags_from_text(column: Column, text: str) -> None:
    lowered = text.lower()
    if column.nullable is None:
        if re.search(r"\b(not\s+null|non[-\s]?nullable|required)\b", lowered):
            column.nullable = False
        elif re.search(r"\b(nullable|optional|null\s+allowed)\b", lowered):
            column.nullable = True
    if not column.primary_key and re.search(r"\b(primary\s+key|pk)\b", lowered):
        column.primary_key = True
    if column.foreign_key is None:
        reference = re.search(r"\b(?:references|foreign\s+key\s+to)\s+([A-Za-z_][\w.]*)", text, re.IGNORECASE)
        if reference:
            column.foreign_key = reference.group(1).split(".", 1)[0]
        elif (
            not column.primary_key
            and re.search(r"_id$|\bid$", column.name, re.IGNORECASE)
            and column.name.lower() not in {"id"}
        ):
            candidate = re.sub(r"[_\s]?id$", "", column.name, flags=re.IGNORECASE)
            if candidate:
                column.foreign_key = candidate


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

_MAPPING_HEADER = (
    "| Column | DataType | Nullable (Y/N) | Primary Key (Yes) | Foreign Key (Y/N) "
    "| Related Entity | Details | Description |"
)
_MAPPING_DIVIDER = "| --- | --- | --- | --- | --- | --- | --- | --- |"


def render_mapping_markdown(tables: list[Table], source: str) -> str:
    today = _dt.date.today().isoformat()
    lines: list[str] = [
        "# Proposed Schema Mapping",
        "",
        f"- Source: `{source}`",
        f"- Generated: {today}",
        "",
        "> Review and edit this file before running `create-schema`.",
        "> Adjust column names, types, and flags as needed.",
        "",
    ]

    if not tables:
        lines.append("_No tables were detected in the source document._")
        return "\n".join(lines) + "\n"

    groups = _group_by_columns(tables)
    single = len(groups) == 1
    for index, (table_names, columns) in enumerate(groups, start=1):
        lines.append("## Columns" if single else f"## Column Set {index}")
        lines.append("")
        lines.append(f"- Tables: {', '.join(table_names)}")
        lines.append("")
        lines.append(_MAPPING_HEADER)
        lines.append(_MAPPING_DIVIDER)
        for column in columns:
            lines.append(_render_mapping_row(column))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _group_by_columns(tables: list[Table]) -> list[tuple[list[str], list[Column]]]:
    """Group tables sharing the same set of column names into one column set."""

    groups: list[list] = []  # each entry: [key, table_names, columns]
    for table in tables:
        key = frozenset(column.name for column in table.columns)
        for group in groups:
            if group[0] == key:
                group[1].append(table.name)
                break
        else:
            groups.append([key, [table.name], table.columns])
    return [(names, columns) for _key, names, columns in groups]


def _render_mapping_row(column: Column) -> str:
    return "| {name} | {dtype} | {nullable} | {pk} | {fk} | {entity} | {details} | {desc} |".format(
        name=_escape(column.name),
        dtype=_escape(column.data_type or ""),
        nullable=_format_yn(column.nullable),
        pk="Yes" if column.primary_key else "",
        fk="Y" if column.foreign_key else "N",
        entity=_escape(column.foreign_key or ""),
        details=_escape(column.details or ""),
        desc=_escape(column.description or ""),
    )


def _format_yn(value: bool | None) -> str:
    if value is None:
        return ""
    return "Y" if value else "N"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").strip()


def write_mapping_markdown(tables: list[Table], source: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_mapping_markdown(tables, source), encoding="utf-8")
    return out_path
```

### 2.6 `docx_schema/schema.py`

```python
"""Parse a mapping markdown file and emit per-table schema markdown files."""

from __future__ import annotations

import re
from pathlib import Path

from .models import Column, Table

_COLUMN_SET_HEADING = re.compile(r"^##\s+(?:Columns|Column Set\b.*)$", re.IGNORECASE)
_TABLES_LINE = re.compile(r"^-\s*Tables:\s*(.+)$", re.IGNORECASE)


def parse_mapping_markdown(text: str) -> list[Table]:
    tables: list[Table] = []
    table_names: list[str] = []
    columns: list[Column] = []
    in_set = False

    def flush() -> None:
        if not in_set:
            return
        for name in table_names or ["Table"]:
            tables.append(Table(name=name, columns=list(columns)))

    for raw in text.splitlines():
        line = raw.strip()

        if _COLUMN_SET_HEADING.match(line):
            flush()
            table_names = []
            columns = []
            in_set = True
            continue

        if not in_set:
            continue

        names_match = _TABLES_LINE.match(line)
        if names_match:
            table_names = [n.strip() for n in names_match.group(1).split(",") if n.strip()]
            continue

        if line.startswith("|"):
            column = _parse_mapping_row(line)
            if column is not None:
                columns.append(column)

    flush()
    return tables


def _parse_mapping_row(line: str) -> Column | None:
    cells = _split_row(line)
    if len(cells) < 8:
        return None

    name, dtype, nullable, pk, _fk, entity, details, description = cells[:8]

    # Skip the header and divider rows.
    if name.strip().lower() == "column" or set(name) <= {"-", ":", " "}:
        return None
    if not name.strip():
        return None

    return Column(
        name=name.strip(),
        data_type=dtype.strip() or None,
        nullable=_parse_bool(nullable),
        primary_key=_parse_bool(pk) is True,
        foreign_key=entity.strip() or None,
        details=details.strip() or None,
        description=description.strip() or None,
    )


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    # Split on unescaped pipes.
    parts = re.split(r"(?<!\\)\|", stripped)
    return [part.replace("\\|", "|").strip() for part in parts]


def _parse_bool(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in {"yes", "y", "true"}:
        return True
    if lowered in {"no", "n", "false"}:
        return False
    return None


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

_SCHEMA_HEADER = (
    "| Column | DataType | Nullable (Y/N) | Primary Key (Yes) | Foreign Key (Y/N) "
    "| Related Entity | Details | Description |"
)
_SCHEMA_DIVIDER = "| --- | --- | --- | --- | --- | --- | --- | --- |"


def render_schema_markdown(table: Table) -> str:
    lines: list[str] = [f"# {table.name}", "", "## Columns", ""]

    if table.columns:
        lines.append(_SCHEMA_HEADER)
        lines.append(_SCHEMA_DIVIDER)
        for column in table.columns:
            lines.append(_render_schema_row(column))
    else:
        lines.append("_No columns defined._")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_schema_row(column: Column) -> str:
    return "| {name} | {dtype} | {nullable} | {pk} | {fk} | {entity} | {details} | {desc} |".format(
        name=_escape(column.name),
        dtype=_escape(column.data_type or ""),
        nullable=_format_yn(column.nullable),
        pk="Yes" if column.primary_key else "",
        fk="Y" if column.foreign_key else "N",
        entity=_escape(column.foreign_key or ""),
        details=_escape(column.details or ""),
        desc=_escape(column.description or ""),
    )


def _format_yn(value: bool | None) -> str:
    if value is None:
        return ""
    return "Y" if value else "N"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").strip()


def schema_filename(table_name: str) -> str:
    safe = re.sub(r"[^\w]+", "_", table_name.strip()).strip("_")
    if not safe:
        safe = "table"
    return f"{safe}_schema.md"


def write_schema_files(tables: list[Table], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for table in tables:
        path = out_dir / schema_filename(table.name)
        path.write_text(render_schema_markdown(table), encoding="utf-8")
        written.append(path)
    return written
```

### 2.7 `docx_schema/cli.py`

```python
"""Command-line interface for the minimal DOCX schema toolkit.

Usage examples::

    python -m docx_schema propose-mapping tables.docx
    python -m docx_schema /propose-mapping @tables.docx --out tables-mapping.md
    python -m docx_schema create-schema tables-mapping.md --out-dir schema

Both slash-prefixed (``/propose-mapping``) and plain (``propose-mapping``)
command names are accepted, and file arguments may use a leading ``@``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .docx_reader import normalize_docx_path
from .mapping import build_tables_from_docx, write_mapping_markdown
from .schema import parse_mapping_markdown, write_schema_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docx_schema",
        description="Turn .docx documents into reviewed table schema markdown.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser(
        "propose-mapping",
        help="Read a .docx and write a reviewer-editable proposed mapping markdown.",
    )
    propose.add_argument("docx", help="Path to the source .docx (a leading @ is allowed).")
    propose.add_argument("--out", help="Output mapping markdown path.", default=None)
    propose.set_defaults(func=_run_propose_mapping)

    create = subparsers.add_parser(
        "create-schema",
        help="Read a mapping markdown and write one {table}_schema.md per table.",
    )
    create.add_argument("mapping", help="Path to the mapping markdown (a leading @ is allowed).")
    create.add_argument("--out-dir", help="Directory for schema files.", default="schema")
    create.set_defaults(func=_run_create_schema)

    return parser


def _run_propose_mapping(args: argparse.Namespace) -> int:
    docx_path = normalize_docx_path(args.docx)
    if not docx_path.is_file():
        print(f"error: docx not found: {docx_path}", file=sys.stderr)
        return 2

    tables = build_tables_from_docx(str(docx_path))
    out_path = Path(args.out) if args.out else Path.cwd() / f"{docx_path.stem}-mapping.md"
    write_mapping_markdown(tables, source=docx_path.name, out_path=out_path)

    print(f"Wrote proposed mapping: {out_path}")
    print(f"Detected {len(tables)} table(s): {', '.join(t.name for t in tables) or '(none)'}")
    print("Review and edit the mapping, then run: create-schema", out_path.name)
    return 0


def _run_create_schema(args: argparse.Namespace) -> int:
    mapping_path = normalize_docx_path(args.mapping)
    if not mapping_path.is_file():
        print(f"error: mapping markdown not found: {mapping_path}", file=sys.stderr)
        return 2

    tables = parse_mapping_markdown(mapping_path.read_text(encoding="utf-8"))
    if not tables:
        print("error: no tables found in mapping markdown.", file=sys.stderr)
        return 1

    written = write_schema_files(tables, Path(args.out_dir))
    print(f"Wrote {len(written)} schema file(s) to {Path(args.out_dir)}:")
    for path in written:
        print(f"  - {path}")
    return 0


def _normalize_argv(argv: list[str]) -> list[str]:
    if argv and argv[0].startswith("/"):
        argv = [argv[0][1:], *argv[1:]]
    return argv


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = _normalize_argv(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

---

## 3. Verify the install

From the folder that contains `docx_schema/`:

```powershell
python --version           # expect Python 3.13.x
python -m docx_schema --help
python -m docx_schema propose-mapping --help
python -m docx_schema create-schema --help
```

If `--help` prints usage, the package is importable and ready.

---

## 4. Run the workflow

### Step 1 — Propose a mapping from a `.docx`

```powershell
python -m docx_schema propose-mapping .\tables.docx
```

Writes `.\tables-mapping.md`. Slash and `@` forms also work:

```powershell
python -m docx_schema /propose-mapping "@tables.docx" --out .\tables-mapping.md
```

### Step 2 — Review and edit the mapping

Open the generated `*-mapping.md`. Tables that share the same set of columns are
grouped into one column set (`## Columns` when there is only one set, or
`## Column Set N` when tables diverge). The `- Tables:` line lists which tables
the column set applies to:

```markdown
## Columns

- Tables: Customer

| Column | DataType | Nullable (Y/N) | Primary Key (Yes) | Foreign Key (Y/N) | Related Entity | Details | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| customer_id | INT | N | Yes | N |  |  | Unique id |
| name | STRING | Y |  | N |  |  | Full name |
```

Edit the `- Tables:` list (comma-separated), the column names, types, and the
`Y`/`N`/`Yes` flags. Set **Related Entity** for foreign keys. Delete unwanted
rows or whole column sets. Save.

### Step 3 — Create schema files

```powershell
python -m docx_schema create-schema .\tables-mapping.md --out-dir .\schema
```

Produces one `{table}_schema.md` per table listed in each column set's
`- Tables:` line, e.g. `schema\Customer_schema.md`.

---

## 5. Input format guidance for the `.docx`

The parser recognizes columns from any of these:

- **Word tables** with a header row containing recognizable labels
  (`Column`/`Field`/`Name`, `Type`/`Data Type`, `Nullable`/`Required`/`Optional`,
  `Primary Key`/`PK`, `Foreign Key`/`FK`/`References`, `Description`/`Notes`).
- **Headings** — a Word heading style, or a paragraph like `Table: Customer` /
  `Entity: Customer`, sets the current table name.
- **Paragraph column lines** such as `customer_id (INT) primary key`,
  `total: DECIMAL — order total`, or `order_id INT references Customer`.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `error: docx not found` | Wrong path/typo | Check the path; drag the file into the terminal to paste its full path. |
| `Detected 0 table(s)` | No recognizable tables/headers | Use a header row, or add `Table: <name>` lines above columns. |
| `error: no tables found in mapping markdown` | Mapping has no `## Columns` / `## Column Set` sections | Re-run Step 1, or restore the `## Columns` headings and `- Tables:` lines. |
| `DOCX ... contains disallowed XML declarations` | Malformed/crafted `.docx` | Use a clean, standard Word document. |
| `ModuleNotFoundError: No module named 'docx_schema'` | Running from the wrong folder | Run from the **parent** folder that contains `docx_schema/`. |

---

## 7. Security notes

- Standard library only; no network calls; nothing is written to the source `.docx`.
- The reader rejects XML DOCTYPE/ENTITY declarations and caps `word/document.xml`
  at 10 MB to defend against XXE (XML eXternal Entity) and decompression abuse.
