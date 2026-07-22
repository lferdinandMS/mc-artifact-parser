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
