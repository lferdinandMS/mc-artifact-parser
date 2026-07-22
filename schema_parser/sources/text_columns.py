"""Heuristic parsing of a single free-text column definition line.

Harvested from the larger artifact parser so ``schema_parser`` can coerce
inconsistent, unstructured inputs (bullet lists, notes, plain text) into the
same ``(name, type, nullable, primary key, foreign key, description)`` shape the
mapping pipeline expects. Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedColumn:
    name: str
    data_type: str | None = None
    nullable: bool | None = None
    primary_key: bool = False
    foreign_key: str | None = None
    description: str | None = None


_DESCRIPTION_SEPARATOR = re.compile(r"\s+[—-]\s+")
_TYPE_PAREN = re.compile(r"^(?P<name>.+?)\s*\((?P<type>[^)]+)\)\s*(?P<trailing>.*)$")
_TYPE_COLON = re.compile(r"^(?P<name>.+?)\s*:\s*(?P<type>[A-Za-z_][\w()\[\],\s]*)\s*(?P<trailing>.*)$")
_COMMON_TYPE_PREFIXES = {
    "bigint",
    "binary",
    "bool",
    "boolean",
    "bpchar",
    "char",
    "character",
    "date",
    "datetime",
    "decimal",
    "double",
    "enum",
    "float",
    "geography",
    "geometry",
    "int",
    "integer",
    "interval",
    "json",
    "jsonb",
    "map",
    "numeric",
    "real",
    "set",
    "smallint",
    "string",
    "text",
    "time",
    "timestamp",
    "tinyint",
    "uuid",
    "varchar",
    "varbinary",
}
_METADATA_PREFIX = re.compile(
    r"\b("
    r"not\s+null|required|not\s+nullable|non[-\s]?nullable|nullable|optional|null\s+allowed|"
    r"primary\s+key|pk|references\s+[A-Za-z_][\w.]*|foreign\s+key\s+to\s+[A-Za-z_][\w.]*"
    r")\b",
    re.IGNORECASE,
)


def parse_column_line(line: str) -> ParsedColumn | None:
    working = line.strip()
    if not working:
        return None

    description: str | None = None
    description_match = _DESCRIPTION_SEPARATOR.search(working)
    if description_match:
        description = working[description_match.end():].strip() or None
        working = working[:description_match.start()].strip()

    name = working
    data_type: str | None = None

    paren_match = _TYPE_PAREN.match(working)
    if paren_match:
        name = paren_match.group("name").strip()
        type_or_description = paren_match.group("type").strip()
        if _looks_like_type(type_or_description):
            data_type = type_or_description or None
        else:
            description = type_or_description or description
    else:
        colon_match = _TYPE_COLON.match(working)
        if colon_match:
            name = colon_match.group("name").strip()
            raw_type = colon_match.group("type").strip()
            # The type pattern allows spaces, so trailing metadata such as
            # "not null" can be captured with the type. Trim it back off.
            metadata_in_type = _METADATA_PREFIX.search(raw_type)
            if metadata_in_type:
                raw_type = raw_type[:metadata_in_type.start()].strip()
            data_type = raw_type or None
        else:
            metadata_match = _METADATA_PREFIX.search(working)
            if metadata_match:
                name = working[:metadata_match.start()].strip() or working

    lowered = line.lower()
    nullable: bool | None = None
    if re.search(r"\b(not\s+null|required|not\s+nullable|non[-\s]?nullable)\b", lowered):
        nullable = False
    elif re.search(r"\b(nullable|optional|null\s+allowed)\b", lowered):
        nullable = True

    primary_key = bool(re.search(r"\b(primary\s+key|pk)\b", lowered))
    foreign_key = _infer_foreign_key(name, line)
    name = name.strip() or working

    return ParsedColumn(
        name=name,
        data_type=data_type,
        nullable=nullable,
        primary_key=primary_key,
        foreign_key=foreign_key,
        description=description,
    )


def _looks_like_type(value: str) -> bool:
    if not value:
        return False

    normalized = value.strip().lower()
    if " " in normalized and not any(token in normalized.split()[:1] for token in _COMMON_TYPE_PREFIXES):
        return False

    first_token = normalized.split()[0]
    if first_token in _COMMON_TYPE_PREFIXES:
        return True

    return bool(re.fullmatch(r"[A-Za-z_][\w]*(?:\s*\([^)]*\))?", value.strip()))


def _infer_foreign_key(name: str, line: str) -> str | None:
    reference_match = re.search(r"\breferences\s+([A-Za-z_][\w.]*)", line, flags=re.IGNORECASE)
    if reference_match:
        reference_name = reference_match.group(1).split(".", 1)[0].strip()
        return reference_name or None

    normalized = name.strip()
    if normalized.lower().endswith(" id"):
        candidate = normalized[:-3].strip()
        return candidate or None
    if normalized.lower().endswith("_id"):
        candidate = normalized[:-3].strip()
        return candidate or None

    return None
