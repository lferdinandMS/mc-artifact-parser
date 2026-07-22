from __future__ import annotations

from schema_parser.models import Relationship, SourceTable
from schema_parser.sources.base import SourceReader
from schema_parser.sources.docx import DocxReader
from schema_parser.sources.svg_relationships import extract_relationships
from schema_parser.sources.svg_tables import SvgReader
from schema_parser.sources.text import TextSchemaReader

# Registry of source readers, tried in order. DocxReader is the default
# fallback so unrecognized files still get the clear DOCX error message.
_READERS: list[SourceReader] = [SvgReader(), TextSchemaReader()]

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
