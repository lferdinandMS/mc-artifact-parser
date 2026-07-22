# docx_schema DISTRIBUTION

Portable source bundle for a two-command workflow:

1. `python -m docx_schema propose-mapping <docx|svg> --out <mapping.md>`
2. `python -m docx_schema create-schema <docx|svg> <mapping.md> --out-dir <dir>`
3. `python -m docx_schema extract-relationships <svg> --out <relationships.md>` (SVG only)

Both commands accept either a DOCX (Word) file or an SVG (Scalable Vector Graphics) diagram (`.svg` or `.xml`). Extraction is handled by a small per-source subpackage (`docx_schema/sources/`): a registry tries each `SourceReader` in turn and falls back to the DOCX reader for unrecognized files. `SvgReader` claims `.svg`/`.xml`; everything else is read as DOCX.

The current implementation treats each distinct header signature as a separate column set, emits a crosswalk for it, and then uses the reviewed mapping plus the source file to generate one schema markdown file per table.

Table names are taken from the heading-styled (or short, heading-like) paragraph immediately before each DOCX table; long prose paragraphs are ignored so they never become table names, and tables without a usable heading fall back to `table_N`. For SVG sources the entity name comes from the per-table `class="thText"` label. Generated schema filenames sanitize illegal characters and are capped in length so they stay valid on Windows.

SVG extraction is class- and layout-driven: each table is a `<g>` group containing one `class="thText"` name node, `class="headText"` header nodes (ordered by `x`), and `class="cell"` data nodes (grouped into rows by `y`, ordered within a row by `x`). A group with more than one name node is treated as a wrapper and skipped so its inner per-table groups produce the tables; files without any grouped tables fall back to a single whole-document table. SVG input is guarded against oversized files and disallowed `<!DOCTYPE>`/`<!ENTITY>` declarations.

SVG diagrams can also encode directional table relationships as arrows. `extract-relationships` reads the table bounding boxes (`<rect class="tbl">`, falling back to cell extents) and the connector geometry: `class="link"` `<path>`/`<line>` segments carry the arrowhead (its last point marks the target), while `class="stub"` segments route the connector between table edges. Segments are grouped by point-on-segment adjacency (union-find), so a single source that fans out to several targets yields one relationship per target. Each endpoint touching a table's left/right edge is resolved to `(table, column)` by nearest row `y`; the non-arrowhead edge endpoint is the source and each arrowhead endpoint is a target. Output is a markdown table plus a Mermaid `erDiagram`.

Invalid input is rejected with a clear message: a non-ZIP or non-DOCX file fails with an explicit "not a valid ZIP-based DOCX file" error, and a non-SVG or malformed `.svg` fails with an explicit SVG parse/root error rather than a low-level exception.

The workflow state also records ISO timestamps with microsecond precision so successive updates remain distinct in the generated session state.

## Run it

```bash
python -m docx_schema propose-mapping ./sample.docx --out ./mapping.md
python -m docx_schema create-schema ./sample.docx @./mapping.md --out-dir ./schema

# SVG source (same two commands; .svg or .xml)
python -m docx_schema propose-mapping ./sample.svg --out ./svg-mapping.md
python -m docx_schema create-schema ./sample.svg @./svg-mapping.md --out-dir ./schema

# Extract table relationships (arrows) from an SVG diagram
python -m docx_schema extract-relationships ./sample.svg --out ./relationships.md
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


@dataclass(frozen=True)
class Relationship:
    source_table: str
    source_column: str
    target_table: str
    target_column: str
```

### `mapping.py`

```python
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
```

### `sources/__init__.py`

```python
from __future__ import annotations

from docx_schema.models import Relationship, SourceTable
from docx_schema.sources.base import SourceReader
from docx_schema.sources.docx import DocxReader
from docx_schema.sources.svg import SvgReader, extract_relationships

# Registry of source readers, tried in order. DocxReader is the default
# fallback so unrecognized files still get the clear DOCX error message.
_READERS: list[SourceReader] = [SvgReader()]

_DEFAULT_READER: SourceReader = DocxReader()

_SVG_READER = SvgReader()


def read_tables(path: str) -> list[SourceTable]:
    for reader in _READERS:
        if reader.can_read(path):
            return reader.read(path)
    return _DEFAULT_READER.read(path)


def read_relationships(path: str) -> list[Relationship]:
    """Extract table relationships from sources that encode them (SVG only)."""
    if _SVG_READER.can_read(path):
        return extract_relationships(path)
    return []


__all__ = ["read_tables", "read_relationships", "SourceReader"]
```

### `sources/base.py`

```python
from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from docx_schema.models import SourceTable

MAX_SOURCE_BYTES = 10 * 1024 * 1024


@runtime_checkable
class SourceReader(Protocol):
    """A component that turns one source file into extracted tables."""

    def can_read(self, path: str) -> bool:
        ...

    def read(self, path: str) -> list[SourceTable]:
        ...


def local_name(tag: str) -> str:
    return tag.split("}", maxsplit=1)[-1]


def reject_xml_declarations(data: bytes) -> None:
    if re.search(br"<!\s*(doctype|entity)\b", data, flags=re.IGNORECASE):
        raise ValueError("Source contains disallowed XML declarations.")


def entity_name_from_path(path: str, fallback: str = "table_1") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", Path(path).stem).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or fallback
```

### `sources/docx.py`

```python
from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

from docx_schema.models import SourceTable
from docx_schema.sources.base import MAX_SOURCE_BYTES, local_name


class DocxReader:
    """Reads tables from the Office Open XML body of a .docx file."""

    def can_read(self, path: str) -> bool:
        return path.lower().endswith(".docx")

    def read(self, path: str) -> list[SourceTable]:
        return _extract_docx_tables(path)


def _extract_docx_tables(path: str) -> list[SourceTable]:
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                document_xml = archive.getinfo("word/document.xml")
            except KeyError as exc:
                raise ValueError(f"{path} is missing word/document.xml") from exc

            if document_xml.file_size > MAX_SOURCE_BYTES:
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
        tag = local_name(child.tag)

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
```

### `sources/svg.py`

```python
from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from docx_schema.models import Relationship, SourceTable
from docx_schema.sources.base import (
    MAX_SOURCE_BYTES,
    entity_name_from_path,
    local_name,
    reject_xml_declarations,
)

_NAME_CLASSES = {"thtext"}
_HEADER_CLASSES = {"headtext"}
_CELL_CLASSES = {"cell"}

# Geometry tolerances (SVG user units).
_EDGE_TOL = 6.0
_ROW_TOL = 14.0
_TOUCH_TOL = 2.5


class SvgReader:
    """Reads schema tables from a structured SVG diagram.

    Each table is expected to be a ``<g>`` group containing:
      * one ``class="thText"`` text node giving the table name,
      * ``class="headText"`` text nodes for the column headers, and
      * ``class="cell"`` text nodes for the data, laid out in columns by
        ``x`` and in rows by ``y``.
    Files without grouped tables fall back to a single whole-document table.
    """

    def can_read(self, path: str) -> bool:
        return path.lower().endswith((".svg", ".xml"))

    def read(self, path: str) -> list[SourceTable]:
        return _extract_svg_tables(path)


def _load_svg_root(path: str) -> ET.Element:
    data = Path(path).read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("SVG file exceeds the maximum supported size.")

    reject_xml_declarations(data)

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"{path} is not a valid SVG (XML parse failed): {exc}") from exc

    if local_name(root.tag).lower() != "svg":
        raise ValueError(
            f"{path} is not an SVG file (root element is <{local_name(root.tag)}>)."
        )

    return root


def _extract_svg_tables(path: str) -> list[SourceTable]:
    root = _load_svg_root(path)

    tables: list[SourceTable] = []
    for group in root.iter():
        if local_name(group.tag).lower() != "g":
            continue
        table = _table_from_scope(group)
        if table is not None:
            tables.append(table)

    if not tables:
        fallback = _table_from_scope(root, default_name=entity_name_from_path(path))
        if fallback is not None:
            tables.append(fallback)

    if not tables:
        raise ValueError(f"No schema tables could be extracted from {path}.")

    return tables


def _table_from_scope(scope: ET.Element, default_name: str | None = None) -> SourceTable | None:
    names: list[str] = []
    header_nodes: list[tuple[float, str]] = []
    cell_nodes: list[tuple[float, float, str]] = []

    for element in scope.iter():
        if local_name(element.tag).lower() != "text":
            continue

        text = _text_of(element)
        if not text:
            continue

        classes = {token.lower() for token in (element.get("class") or "").split()}
        x = _coord(element, "x") or 0.0
        y = _coord(element, "y") or 0.0

        if classes & _NAME_CLASSES:
            names.append(text)
        elif classes & _HEADER_CLASSES:
            header_nodes.append((x, text))
        elif classes & _CELL_CLASSES:
            cell_nodes.append((x, y, text))

    # A container that wraps several tables has more than one name node; skip it
    # so the individual per-table groups are the ones that produce tables.
    if default_name is None and len(names) != 1:
        return None

    if not cell_nodes:
        return None

    headers = [text for _x, text in sorted(header_nodes)]

    rows_by_y: dict[int, list[tuple[float, str]]] = {}
    for x, y, text in cell_nodes:
        rows_by_y.setdefault(round(y), []).append((x, text))

    rows = [[text for _x, text in sorted(rows_by_y[key])] for key in sorted(rows_by_y)]

    if not headers:
        width = max(len(row) for row in rows)
        headers = [f"col{index + 1}" for index in range(width)]

    name = names[0] if names else (default_name or "table_1")
    return SourceTable(name=name, headers=headers, rows=rows)


def _text_of(element: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext()).strip())


def _coord(element: ET.Element, attribute: str) -> float | None:
    raw = element.get(attribute)
    if raw is None:
        return None
    match = re.match(r"-?\d+(?:\.\d+)?", raw.strip())
    if match is None:
        return None
    return float(match.group())


# ---------------------------------------------------------------------------
# Relationship extraction
# ---------------------------------------------------------------------------


class _TableBox:
    __slots__ = ("name", "left", "right", "top", "bottom", "rows")

    def __init__(
        self,
        name: str,
        left: float,
        right: float,
        top: float,
        bottom: float,
        rows: list[tuple[float, str]],
    ) -> None:
        self.name = name
        self.left = left
        self.right = right
        self.top = top
        self.bottom = bottom
        self.rows = rows

    def attaches(self, x: float, y: float) -> bool:
        near_edge = abs(x - self.left) <= _EDGE_TOL or abs(x - self.right) <= _EDGE_TOL
        within_span = self.top - _EDGE_TOL <= y <= self.bottom + _EDGE_TOL
        return near_edge and within_span

    def column_at(self, y: float) -> str:
        best: str = ""
        best_dist = _ROW_TOL
        for row_y, column in self.rows:
            dist = abs(row_y - y)
            if dist <= best_dist:
                best_dist = dist
                best = column
        return best


def extract_relationships(path: str) -> list[Relationship]:
    """Extract directional table relationships encoded by SVG arrows.

    Arrows are ``class="link"`` paths whose ``marker-end`` places the arrowhead
    at the target; ``class="stub"`` segments route the connector between table
    edges. Endpoints touching a table edge are resolved to ``(table, column)``
    by nearest row; connected segments are grouped so a source that fans out to
    several targets yields one relationship per target.
    """

    root = _load_svg_root(path)
    boxes = _table_boxes(root)
    if not boxes:
        return []

    segments, arrowheads = _connector_segments(root)
    if not segments:
        return []

    parent = list(range(len(segments)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            if _segments_touch(segments[i], segments[j]):
                union(i, j)

    components: dict[int, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    for index, segment in enumerate(segments):
        components.setdefault(find(index), []).append(segment)

    relationships: list[Relationship] = []
    seen: set[Relationship] = set()

    for segs in components.values():
        sources: set[tuple[str, str]] = set()
        targets: set[tuple[str, str]] = set()

        endpoints = {point for segment in segs for point in segment}
        for point in endpoints:
            attachment = _attachment(point, boxes)
            if attachment is None:
                continue
            if _rounded(point) in arrowheads:
                targets.add(attachment)
            else:
                sources.add(attachment)

        for source in sources:
            for target in targets:
                if source == target:
                    continue
                relationship = Relationship(
                    source_table=source[0],
                    source_column=source[1],
                    target_table=target[0],
                    target_column=target[1],
                )
                if relationship not in seen:
                    seen.add(relationship)
                    relationships.append(relationship)

    return relationships


def _table_boxes(root: ET.Element) -> list[_TableBox]:
    boxes: list[_TableBox] = []
    for group in root.iter():
        if local_name(group.tag).lower() != "g":
            continue

        names: list[str] = []
        cell_nodes: list[tuple[float, float, str]] = []
        table_rect: tuple[float, float, float, float] | None = None

        for element in group.iter():
            tag = local_name(element.tag).lower()
            classes = {token.lower() for token in (element.get("class") or "").split()}

            if tag == "rect" and "tbl" in classes and table_rect is None:
                x = _coord(element, "x")
                y = _coord(element, "y")
                width = _coord(element, "width")
                height = _coord(element, "height")
                if None not in (x, y, width, height):
                    table_rect = (x, y, width, height)  # type: ignore[assignment]
                continue

            if tag != "text":
                continue

            text = _text_of(element)
            if not text:
                continue

            x = _coord(element, "x") or 0.0
            y = _coord(element, "y") or 0.0

            if classes & _NAME_CLASSES:
                names.append(text)
            elif classes & _CELL_CLASSES:
                cell_nodes.append((x, y, text))

        if len(names) != 1 or not cell_nodes:
            continue

        rows = _column_rows(cell_nodes)

        if table_rect is not None:
            x, y, width, height = table_rect
            left, right, top, bottom = x, x + width, y, y + height
        else:
            xs = [x for x, _y, _t in cell_nodes]
            ys = [y for _x, y, _t in cell_nodes]
            left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)

        boxes.append(_TableBox(names[0], left, right, top, bottom, rows))

    return boxes


def _column_rows(cell_nodes: list[tuple[float, float, str]]) -> list[tuple[float, str]]:
    rows_by_y: dict[int, list[tuple[float, str]]] = {}
    for x, y, text in cell_nodes:
        rows_by_y.setdefault(round(y), []).append((x, text))

    rows: list[tuple[float, str]] = []
    for key in sorted(rows_by_y):
        cells = sorted(rows_by_y[key])
        rows.append((float(key), cells[0][1]))
    return rows


def _connector_segments(
    root: ET.Element,
) -> tuple[list[tuple[tuple[float, float], tuple[float, float]]], set[tuple[int, int]]]:
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    arrowheads: set[tuple[int, int]] = set()

    for element in root.iter():
        tag = local_name(element.tag).lower()
        classes = {token.lower() for token in (element.get("class") or "").split()}
        is_link = "link" in classes
        is_stub = "stub" in classes
        if not (is_link or is_stub):
            continue

        points = _element_points(element, tag)
        if len(points) < 2:
            continue

        for start, end in zip(points, points[1:]):
            segments.append((start, end))

        if is_link:
            arrowheads.add(_rounded(points[-1]))

    return segments, arrowheads


def _element_points(element: ET.Element, tag: str) -> list[tuple[float, float]]:
    if tag == "line":
        x1 = _coord(element, "x1")
        y1 = _coord(element, "y1")
        x2 = _coord(element, "x2")
        y2 = _coord(element, "y2")
        if None in (x1, y1, x2, y2):
            return []
        return [(x1, y1), (x2, y2)]  # type: ignore[list-item]

    if tag == "path":
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", element.get("d") or "")]
        return [(numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)]

    return []


def _segments_touch(
    a: tuple[tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    return (
        _point_on_segment(a[0], b)
        or _point_on_segment(a[1], b)
        or _point_on_segment(b[0], a)
        or _point_on_segment(b[1], a)
    )


def _point_on_segment(
    point: tuple[float, float],
    segment: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    (x1, y1), (x2, y2) = segment
    px, py = point

    if abs(x1 - x2) <= _TOUCH_TOL:  # vertical
        return abs(px - x1) <= _TOUCH_TOL and min(y1, y2) - _TOUCH_TOL <= py <= max(y1, y2) + _TOUCH_TOL

    if abs(y1 - y2) <= _TOUCH_TOL:  # horizontal
        return abs(py - y1) <= _TOUCH_TOL and min(x1, x2) - _TOUCH_TOL <= px <= max(x1, x2) + _TOUCH_TOL

    # Diagonal segment: only treat as touching at its endpoints.
    return (abs(px - x1) <= _TOUCH_TOL and abs(py - y1) <= _TOUCH_TOL) or (
        abs(px - x2) <= _TOUCH_TOL and abs(py - y2) <= _TOUCH_TOL
    )


def _attachment(point: tuple[float, float], boxes: list[_TableBox]) -> tuple[str, str] | None:
    px, py = point
    for box in boxes:
        if box.attaches(px, py):
            return (box.name, box.column_at(py))
    return None


def _rounded(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0]), round(point[1]))
```

### `cli.py`

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docx_schema.docx_reader import normalize_docx_path
from docx_schema.mapping import (
    parse_mapping_markdown,
    propose_mapping,
    render_mapping_markdown,
    render_relationships_markdown,
    write_schema_files,
)
from docx_schema.sources import read_relationships


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m docx_schema", description="Create mapping and schema markdown files from DOCX or SVG sources.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose-mapping", help="Create a self-contained mapping markdown from a DOCX or SVG file.")
    propose.add_argument("source", help="Path to source .docx or .svg/.xml")
    propose.add_argument("--out", default="./mapping.md", help="Output mapping markdown path")
    propose.set_defaults(handler=_run_propose_mapping)

    create = subparsers.add_parser("create-schema", help="Create per-table schema files from a source DOCX/SVG plus reviewed mapping markdown.")
    create.add_argument("source", help="Path to source .docx or .svg/.xml (leading @ allowed)")
    create.add_argument("mapping", help="Path to mapping markdown (leading @ allowed)")
    create.add_argument("--out-dir", default="./schema", help="Output directory for schema markdown files")
    create.set_defaults(handler=_run_create_schema)

    relationships = subparsers.add_parser("extract-relationships", help="Extract table relationships (SVG arrows) to a markdown + Mermaid ERD.")
    relationships.add_argument("source", help="Path to source .svg/.xml (leading @ allowed)")
    relationships.add_argument("--out", default="./relationships.md", help="Output relationships markdown path")
    relationships.set_defaults(handler=_run_extract_relationships)

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


def _run_extract_relationships(args: argparse.Namespace) -> int:
    source_path = normalize_docx_path(args.source)
    relationships = read_relationships(str(source_path))
    text = render_relationships_markdown(relationships)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    print(f"Wrote {len(relationships)} relationship(s)")
    print(out_path)
    return 0


def _normalize_argv(argv: list[str]) -> list[str]:
    if argv and argv[0].startswith("/"):
        return [argv[0][1:], *argv[1:]]
    return argv


if __name__ == "__main__":
    raise SystemExit(main())
```
