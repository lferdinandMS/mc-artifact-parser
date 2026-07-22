from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from schema_parser.models import SourceTable
from schema_parser.sources.base import (
    MAX_SOURCE_BYTES,
    entity_name_from_path,
    local_name,
    reject_xml_declarations,
)

_NAME_CLASSES = {"thtext"}
_HEADER_CLASSES = {"headtext"}
_CELL_CLASSES = {"cell"}


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


def load_svg_root(path: str) -> ET.Element:
    """Load and validate the root ``<svg>`` element (shared by both readers)."""

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


def text_of(element: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext()).strip())


def coord(element: ET.Element, attribute: str) -> float | None:
    raw = element.get(attribute)
    if raw is None:
        return None
    match = re.match(r"-?\d+(?:\.\d+)?", raw.strip())
    if match is None:
        return None
    return float(match.group())


def _extract_svg_tables(path: str) -> list[SourceTable]:
    root = load_svg_root(path)

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

        text = text_of(element)
        if not text:
            continue

        classes = {token.lower() for token in (element.get("class") or "").split()}
        x = coord(element, "x") or 0.0
        y = coord(element, "y") or 0.0

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
