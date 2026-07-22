"""Generic text / markdown source reader.

Turns inconsistent, loosely structured inputs (``.txt`` notes, ``.md`` docs)
into ``SourceTable`` objects so the same ``propose-mapping`` -> ``create-schema``
workflow applies. Two input shapes are supported per entity:

* **Markdown pipe tables** -- parsed literally (first row = headers), so the
  existing header crosswalk maps them onto the target columns.
* **Free-text column lines** -- bullet or plain lines parsed heuristically by
  :func:`parse_column_line` and emitted as rows already aligned to
  ``TARGET_COLUMNS``.

Entities are delimited by markdown headings (``# Name``) or ``Entity:`` /
``Table:`` lines; input without any delimiter yields a single table named after
the file.
"""

from __future__ import annotations

import re
from pathlib import Path

from schema_parser.models import SourceTable, TARGET_COLUMNS
from schema_parser.sources.base import MAX_SOURCE_BYTES, entity_name_from_path
from schema_parser.sources.text_columns import ParsedColumn, parse_column_line

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_ENTITY_PREFIX = re.compile(r"^(?:entity|table)\s*[:\-]\s*(.+)$", re.IGNORECASE)
_BULLET = re.compile(r"^[\-\*\u2022]\s+")
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")


class TextSchemaReader:
    """Reads schema tables from ``.txt`` / ``.md`` sources."""

    def can_read(self, path: str) -> bool:
        return path.lower().endswith((".md", ".markdown", ".txt"))

    def read(self, path: str) -> list[SourceTable]:
        return _extract_text_tables(path)


def _extract_text_tables(path: str) -> list[SourceTable]:
    data = Path(path).read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("Text source exceeds the maximum supported size.")

    if re.search(br"<!\s*(doctype|entity)\b", data, flags=re.IGNORECASE):
        raise ValueError("Source contains disallowed XML declarations.")

    lines = data.decode("utf-8", errors="replace").splitlines()

    tables: list[SourceTable] = []
    current_name: str | None = None
    pipe_lines: list[str] = []
    free_rows: list[list[str]] = []

    def flush() -> None:
        nonlocal pipe_lines, free_rows
        name = current_name or entity_name_from_path(path)
        if pipe_lines:
            table = _table_from_pipe_block(pipe_lines, name)
            if table is not None:
                tables.append(table)
        elif free_rows:
            tables.append(SourceTable(name=name, headers=list(TARGET_COLUMNS), rows=free_rows))
        pipe_lines = []
        free_rows = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush()
            heading_text = heading.group(2).strip()
            prefix = _ENTITY_PREFIX.match(heading_text)
            current_name = prefix.group(1).strip() if prefix else heading_text
            continue

        prefix = _ENTITY_PREFIX.match(stripped)
        if prefix:
            flush()
            current_name = prefix.group(1).strip()
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            # A structured table takes precedence over free-text lines.
            pipe_lines.append(stripped)
            continue

        if pipe_lines:
            # Free-text after a pipe block within the same entity is ignored to
            # keep one table per entity (and stable, unique table names).
            continue

        parsed = parse_column_line(_BULLET.sub("", stripped))
        if parsed is not None and parsed.name:
            free_rows.append(_to_target_row(parsed))

    flush()

    if not tables:
        raise ValueError(f"No schema tables could be extracted from {path}.")

    return tables


def _table_from_pipe_block(pipe_lines: list[str], name: str) -> SourceTable | None:
    rows = [_split_pipe_row(line) for line in pipe_lines]
    rows = [row for row in rows if row and not _is_separator_row(row)]
    if not rows:
        return None

    headers = rows[0]
    data_rows = rows[1:]
    return SourceTable(name=name, headers=headers, rows=data_rows)


def _split_pipe_row(line: str) -> list[str]:
    trimmed = line.strip()
    if trimmed.startswith("|"):
        trimmed = trimmed[1:]
    if trimmed.endswith("|"):
        trimmed = trimmed[:-1]
    return [cell.strip() for cell in trimmed.split("|")]


def _is_separator_row(row: list[str]) -> bool:
    return all(_SEPARATOR_CELL.match(cell) is not None for cell in row if cell) and any(row)


def _to_target_row(parsed: ParsedColumn) -> list[str]:
    index = {name: position for position, name in enumerate(TARGET_COLUMNS)}
    row = [""] * len(TARGET_COLUMNS)
    row[index["Column"]] = parsed.name
    row[index["Type"]] = parsed.data_type or ""
    row[index["Nullable"]] = {True: "Yes", False: "No", None: ""}[parsed.nullable]
    row[index["Primary Key"]] = "Yes" if parsed.primary_key else ""
    row[index["Foreign Key"]] = parsed.foreign_key or ""
    row[index["Description"]] = parsed.description or ""
    return row
