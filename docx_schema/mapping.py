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
