from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from schema_parser.models import Relationship
from schema_parser.sources.base import local_name
from schema_parser.sources.svg_tables import (
    _CELL_CLASSES,
    _NAME_CLASSES,
    coord,
    load_svg_root,
    text_of,
)

# Geometry tolerances (SVG user units).
_EDGE_TOL = 6.0
_ROW_TOL = 14.0
_TOUCH_TOL = 2.5


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

    root = load_svg_root(path)
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
                x = coord(element, "x")
                y = coord(element, "y")
                width = coord(element, "width")
                height = coord(element, "height")
                if None not in (x, y, width, height):
                    table_rect = (x, y, width, height)  # type: ignore[assignment]
                continue

            if tag != "text":
                continue

            text = text_of(element)
            if not text:
                continue

            x = coord(element, "x") or 0.0
            y = coord(element, "y") or 0.0

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
        x1 = coord(element, "x1")
        y1 = coord(element, "y1")
        x2 = coord(element, "x2")
        y2 = coord(element, "y2")
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
