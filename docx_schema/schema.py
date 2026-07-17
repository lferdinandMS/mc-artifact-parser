"""Parse a mapping markdown crosswalk and extract the document per column set.

``create-schema`` reads the reviewer-edited mapping plus the original source
document and, for every column set, produces a data-dictionary extract: one
markdown file whose columns are the fixed ``TARGET_COLUMNS`` and whose rows are
the source rows pulled through the ``Extracted Column -> Target Column`` mapping.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import TARGET_COLUMNS, ColumnSet, SourceTable

_COLUMN_SET_HEADING = re.compile(r"^##\s+Column Set\b.*$", re.IGNORECASE)
_TABLES_LINE = re.compile(r"^-\s*Tables:\s*(.+)$", re.IGNORECASE)


def parse_mapping_markdown(text: str) -> list[ColumnSet]:
    column_sets: list[ColumnSet] = []
    table_names: list[str] = []
    pairs: list[tuple[str, str]] = []
    in_set = False

    def flush() -> None:
        if in_set:
            column_sets.append(
                ColumnSet(table_names=table_names or ["Table"], pairs=list(pairs))
            )

    for raw in text.splitlines():
        line = raw.strip()

        if _COLUMN_SET_HEADING.match(line):
            flush()
            table_names = []
            pairs = []
            in_set = True
            continue

        if not in_set:
            continue

        names_match = _TABLES_LINE.match(line)
        if names_match:
            table_names = [n.strip() for n in names_match.group(1).split(",") if n.strip()]
            continue

        if line.startswith("|"):
            pair = _parse_pair_row(line)
            if pair is not None:
                pairs.append(pair)

    flush()
    return column_sets


def _parse_pair_row(line: str) -> tuple[str, str] | None:
    cells = _split_row(line)
    if len(cells) < 2:
        return None
    extracted, target = cells[0].strip(), cells[1].strip()

    # Skip the header row and the divider row.
    if extracted.lower() == "extracted column" and target.lower() == "target column":
        return None
    if _is_divider(extracted) and _is_divider(target):
        return None
    if not extracted and not target:
        return None
    return extracted, target


def _is_divider(value: str) -> bool:
    return bool(value) and set(value) <= {"-", ":", " "}


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    parts = re.split(r"(?<!\\)\|", stripped)
    return [part.replace("\\|", "|").strip() for part in parts]


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def extract_column_set(
    column_set: ColumnSet, source_tables: list[SourceTable]
) -> list[tuple[str, list[list[str]]]]:
    """Return ``(table_name, rows)`` for each source table in this column set.

    Each row is a list of values aligned to ``TARGET_COLUMNS``, pulled from the
    source row via the ``target -> extracted`` mapping.
    """

    target_to_extracted = column_set.target_to_extracted()
    wanted = set(column_set.table_names)
    results: list[tuple[str, list[list[str]]]] = []

    for source in source_tables:
        if source.name not in wanted:
            continue
        header_index = {header.strip().lower(): i for i, header in enumerate(source.headers)}
        out_rows: list[list[str]] = []
        for row in source.rows:
            values: list[str] = []
            for target in TARGET_COLUMNS:
                extracted = target_to_extracted.get(target)
                value = ""
                if extracted:
                    index = header_index.get(extracted.strip().lower())
                    if index is not None and index < len(row):
                        value = row[index].strip()
                values.append(value)
            out_rows.append(values)
        results.append((source.name, out_rows))

    return results


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

_EXTRACT_HEADER = "| " + " | ".join(TARGET_COLUMNS) + " |"
_EXTRACT_DIVIDER = "| " + " | ".join("---" for _ in TARGET_COLUMNS) + " |"


def render_extract_markdown(
    column_set: ColumnSet, source_tables: list[SourceTable], index: int
) -> str:
    lines: list[str] = [
        f"# Column Set {index}",
        "",
        f"- Tables: {', '.join(column_set.table_names)}",
        "",
    ]

    extracted = extract_column_set(column_set, source_tables)
    if not extracted:
        lines.append("_No source tables matched this column set._")
        return "\n".join(lines) + "\n"

    for name, rows in extracted:
        lines.append(f"## {name}")
        lines.append("")
        lines.append(_EXTRACT_HEADER)
        lines.append(_EXTRACT_DIVIDER)
        for values in rows:
            lines.append("| " + " | ".join(_escape(v) for v in values) + " |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").strip()


def extract_filename(index: int) -> str:
    return f"column-set-{index}.md"


def write_extract_files(
    column_sets: list[ColumnSet], source_tables: list[SourceTable], out_dir: Path
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, column_set in enumerate(column_sets, start=1):
        path = out_dir / extract_filename(index)
        path.write_text(
            render_extract_markdown(column_set, source_tables, index), encoding="utf-8"
        )
        written.append(path)
    return written
