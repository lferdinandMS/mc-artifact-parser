from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ColumnSchema:
    name: str
    data_type: Optional[str] = None
    nullable: Optional[bool] = None
    primary_key: bool = False


@dataclass
class EntitySchema:
    name: str
    implied_tables: list[str] = field(default_factory=list)
    columns: list[ColumnSchema] = field(default_factory=list)
    related_entities: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)


@dataclass
class ArtifactParseResult:
    source_path: str
    artifact_type: str
    entities: list[EntitySchema] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
