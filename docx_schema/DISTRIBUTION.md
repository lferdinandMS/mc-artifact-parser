# docx_schema — Portable Source Bundle & Setup Guide

This document contains the **complete source** of the `docx_schema` package
plus step-by-step instructions to set it up in a customer environment. Everything
below is the standard library only — no third-party packages, no network access.

The workflow is a single command:

- `propose-mapping` — read a `.docx` and write a reviewer-editable **mapping**
  markdown. For each *column set* (a group of tables that share the same
  extracted columns) it proposes a best-guess pairing of each extracted column
  to a fixed target data-dictionary column. A human confirms or corrects the
  pairings in the generated file.

---

## 1. Prerequisites

- **Python 3.13.x** on PATH (`python --version` → `Python 3.13.x`).
- No third-party packages. No internet connection required.
- A terminal (examples use Windows PowerShell).

---

## 2. Create the package

Create a folder named `docx_schema` and add the six files below, each with the
exact contents shown. The final layout must be:

```text
docx_schema/
    __init__.py
    __main__.py
    models.py
    docx_reader.py
    mapping.py
    cli.py
    RUNBOOK.md   (optional operator guide; see the repo)
```

Run all commands from the **parent** folder that contains `docx_schema/`.

### 2.1 `docx_schema/__init__.py`

```python
"""Minimal DOCX-to-schema toolkit.

``propose-mapping`` reads a ``.docx`` and writes a reviewer-editable proposed
mapping markdown: a per-column-set crosswalk that lists the extracted columns
found in the document and the fixed target data-dictionary columns, for a human
to pair up.

The package is intentionally self-contained and depends only on the Python
standard library.
"""

from __future__ import annotations

from .models import TARGET_COLUMNS, ColumnSet, SourceTable
from .mapping import (
    build_source_tables_from_docx,
    group_column_sets,
    render_mapping_markdown,
    write_mapping_markdown,
)

__all__ = [
    "TARGET_COLUMNS",
    "SourceTable",
    "ColumnSet",
    "build_source_tables_from_docx",
    "group_column_sets",
    "render_mapping_markdown",
    "write_mapping_markdown",
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

# The fixed set of target columns for the data dictionary, in output order.
# A reviewer maps each extracted column from the source document onto one of
# these target columns in the proposed mapping.
TARGET_COLUMNS: list[str] = [
    "Column",
    "DataType",
    "Nullable(Y/N)",
    "Primary Key (Y/N)",
    "Foreign Key (Y/N)",
    "Related Entity",
    "Details",
    "Description",
]


@dataclass
class SourceTable:
    """A table detected in the source ``.docx``.

    ``headers`` are the raw column labels from the first row (the *extracted
    columns*) and ``rows`` are the remaining data rows, aligned to ``headers``.
    """

    name: str
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class ColumnSet:
    """A group of source tables that share the same extracted-column signature.

    ``pairs`` is the ordered crosswalk shown in the proposed mapping: each entry
    is ``(extracted_column, target_column)`` where either side may be empty. A
    human pairs them up by editing the two-column table.
    """

    table_names: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)
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
"""Read source tables from a ``.docx`` and render a proposed mapping markdown.

The proposed mapping is a reviewer-editable crosswalk. For each *column set*
(a group of source tables that share the same extracted columns) it proposes a
best-guess pairing of each extracted column to a target data-dictionary column,
using header synonyms. A human confirms or corrects the pairings.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from .docx_reader import Paragraph, read_blocks
from .models import TARGET_COLUMNS, ColumnSet, SourceTable

_HEADING_MARKER = re.compile(r"^(?:entity|table)\s*[:\-]\s*(.+)$", re.IGNORECASE)
_BULLET = re.compile(r"^[\-\*•]\s*")

# Synonyms that let an extracted column be auto-matched to a target column.
# Keys are the canonical target columns from ``TARGET_COLUMNS``.
_TARGET_SYNONYMS: dict[str, set[str]] = {
    "Column": {"column", "column name", "field", "field name", "name", "attribute"},
    "DataType": {"datatype", "data type", "type"},
    "Nullable(Y/N)": {"nullable", "null", "required", "optional"},
    "Primary Key (Y/N)": {"primary key", "pk", "primary"},
    "Foreign Key (Y/N)": {"foreign key", "fk"},
    "Related Entity": {"related entity", "references", "reference", "related", "entity"},
    "Details": {"details", "detail", "notes", "note"},
    "Description": {"description", "desc", "comment", "comments", "purpose"},
}


def build_source_tables_from_docx(path: str) -> list[SourceTable]:
    """Return the tables detected in the document as raw headers + rows."""

    blocks = read_blocks(path)
    tables: list[SourceTable] = []
    pending_name: str | None = None

    for block in blocks:
        if isinstance(block, Paragraph):
            text = _BULLET.sub("", block.text).strip()
            if not text:
                continue
            heading = _HEADING_MARKER.match(text)
            if heading:
                pending_name = heading.group(1).strip()
                continue
            if _is_heading_style(block.style):
                pending_name = text
                continue
            continue

        # Word table block: first non-empty row = headers, rest = data.
        rows = [r for r in block.rows if any(cell.strip() for cell in r)]
        if not rows:
            continue
        headers = [cell.strip() for cell in rows[0]]
        if not any(headers):
            continue
        data_rows = [list(r) for r in rows[1:]]
        name = pending_name or _fallback_name(tables)
        pending_name = None
        tables.append(SourceTable(name=name, headers=headers, rows=data_rows))

    return tables


def group_column_sets(tables: list[SourceTable]) -> list[ColumnSet]:
    """Group source tables by their extracted-column signature."""

    groups: list[list] = []  # each entry: [key, table_names, headers]
    for table in tables:
        key = tuple(h.lower() for h in table.headers)
        for group in groups:
            if group[0] == key:
                group[1].append(table.name)
                break
        else:
            groups.append([key, [table.name], table.headers])

    return [
        ColumnSet(table_names=names, pairs=_build_pairs(headers))
        for _key, names, headers in groups
    ]


def _build_pairs(headers: list[str]) -> list[tuple[str, str]]:
    """Build the proposed crosswalk rows for a column set.

    Each extracted column is matched to a target column by header synonym.
    Extracted columns with no confident match are listed first with an empty
    target. Every target column is then listed in canonical order, paired with
    its matched extracted column (or empty when nothing matched).
    """

    matched: dict[str, str] = {}
    unmatched: list[str] = []
    for header in headers:
        target = _match_target(header)
        if target and target not in matched:
            matched[target] = header
        else:
            unmatched.append(header)

    pairs: list[tuple[str, str]] = [(header, "") for header in unmatched]
    for target in TARGET_COLUMNS:
        pairs.append((matched.get(target, ""), target))
    return pairs


def _match_target(header: str) -> str | None:
    label = header.strip().lower()
    for target, synonyms in _TARGET_SYNONYMS.items():
        if label in synonyms:
            return target
    return None


def _is_heading_style(style: str) -> bool:
    return style.lower().startswith("heading") or style.lower() == "title"


def _fallback_name(tables: list[SourceTable]) -> str:
    return f"Table{len(tables) + 1}"


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

_CROSSWALK_HEADER = "|Extracted Column|Target Column|"
_CROSSWALK_DIVIDER = "|---------------|-------------|"


def render_mapping_markdown(column_sets: list[ColumnSet], source: str) -> str:
    today = _dt.date.today().isoformat()
    lines: list[str] = [
        "# Proposed Schema Mapping",
        "",
        f"- Source: `{source}`",
        f"- Generated: {today}",
        "",
        "> A best-guess mapping is proposed below. Review and correct the pairings.",
        "> An empty cell means no confident match was found for that column.",
        "",
    ]

    if not column_sets:
        lines.append("_No tables were detected in the source document._")
        return "\n".join(lines) + "\n"

    for index, column_set in enumerate(column_sets, start=1):
        lines.append(f"## Column Set {index}")
        lines.append("")
        lines.append(f"- Tables: {', '.join(column_set.table_names)}")
        lines.append("")
        lines.append(_CROSSWALK_HEADER)
        lines.append(_CROSSWALK_DIVIDER)
        for extracted, target in column_set.pairs:
            lines.append(f"|{_escape(extracted)}|{_escape(target)}|")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").strip()


def write_mapping_markdown(column_sets: list[ColumnSet], source: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_mapping_markdown(column_sets, source), encoding="utf-8")
    return out_path
```

### 2.6 `docx_schema/cli.py`

```python
"""Command-line interface for the minimal DOCX schema toolkit.

Usage examples::

    python -m docx_schema propose-mapping tables.docx
    python -m docx_schema /propose-mapping @tables.docx --out tables-mapping.md

Both slash-prefixed (``/propose-mapping``) and plain (``propose-mapping``)
command names are accepted, and file arguments may use a leading ``@``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .docx_reader import normalize_docx_path
from .mapping import (
    build_source_tables_from_docx,
    group_column_sets,
    write_mapping_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docx_schema",
        description="Extract table column sets from .docx into a reviewer-editable mapping.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser(
        "propose-mapping",
        help="Read a .docx and write a reviewer-editable proposed mapping markdown.",
    )
    propose.add_argument("docx", help="Path to the source .docx (a leading @ is allowed).")
    propose.add_argument("--out", help="Output mapping markdown path.", default=None)
    propose.set_defaults(func=_run_propose_mapping)

    return parser


def _run_propose_mapping(args: argparse.Namespace) -> int:
    docx_path = normalize_docx_path(args.docx)
    if not docx_path.is_file():
        print(f"error: docx not found: {docx_path}", file=sys.stderr)
        return 2

    tables = build_source_tables_from_docx(str(docx_path))
    column_sets = group_column_sets(tables)
    out_path = Path(args.out) if args.out else Path.cwd() / "outputs" / "mappings" / f"{docx_path.stem}-mapping.md"
    write_mapping_markdown(column_sets, source=docx_path.name, out_path=out_path)

    print(f"Wrote proposed mapping: {out_path}")
    print(f"Detected {len(tables)} table(s) in {len(column_sets)} column set(s).")
    print("A best-guess mapping was proposed; review and correct it in the mapping file.")
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

## 3. Run it

From the parent folder that contains `docx_schema/`:

```powershell
# Default output: .\outputs\mappings\<docx-stem>-mapping.md
python -m docx_schema propose-mapping tables.docx

# Explicit output path; chat-style @ prefixes are accepted on both the
# command name and the file argument.
python -m docx_schema /propose-mapping @tables.docx --out tables-mapping.md
```

The command prints the output path and a summary such as:

```text
Wrote proposed mapping: <path>\tables-mapping.md
Detected 1 table(s) in 1 column set(s).
A best-guess mapping was proposed; review and correct it in the mapping file.
```

---

## 4. Output format

The generated markdown has one section per **column set**. Each section lists
the tables that share the same extracted columns and a two-column crosswalk. For
a table with headers `Field, Type, Required, Purpose` the crosswalk looks like:

```markdown
# Proposed Schema Mapping

- Source: `tables.docx`
- Generated: 2026-07-17

> A best-guess mapping is proposed below. Review and correct the pairings.
> An empty cell means no confident match was found for that column.

## Column Set 1

- Tables: Customer

|Extracted Column|Target Column|
|---------------|-------------|
|Field|Column|
|Type|DataType|
|Required|Nullable(Y/N)|
||Primary Key (Y/N)|
||Foreign Key (Y/N)|
||Related Entity|
||Details|
|Purpose|Description|
```

How the crosswalk is built:

- Each extracted header is matched to a target column by synonym
  (see `_TARGET_SYNONYMS`). Matched pairs appear on the same row.
- Target columns with no match get an **empty left cell** — fill them in.
- Extracted columns with no confident match are listed **first** with an empty
  target — assign them or delete the row.

A reviewer edits this file to finalize the pairing.

---

## 5. Notes & guarantees

- **Standard library only.** No `pip install` step; no network access.
- **Security.** The DOCX reader caps `word/document.xml` at 10 MiB and rejects
  `<!DOCTYPE` / `<!ENTITY` declarations to prevent XXE (XML eXternal Entity)
  attacks.
- **Table detection.** A table is named from a preceding `Table:`/`Entity:`
  marker paragraph or a heading-styled paragraph; otherwise it falls back to
  `Table1`, `Table2`, … in document order.
