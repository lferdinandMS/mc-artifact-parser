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
    pairs: list[tuple[str, str]]
    tables: list[TableSchema] = field(default_factory=list)
