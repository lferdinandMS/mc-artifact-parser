from schema_parser.cli import main
from schema_parser.mapping import (
    parse_mapping_markdown,
    project_table,
    propose_mapping,
    write_schema_files,
)
from schema_parser.models import ColumnSet, Relationship, SourceTable, TableSchema, TARGET_COLUMNS
from schema_parser.render import (
    render_mapping_markdown,
    render_relationships_markdown,
    render_schema_markdown,
)
from schema_parser.sources import read_relationships

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "ColumnSet",
    "Relationship",
    "SourceTable",
    "TARGET_COLUMNS",
    "TableSchema",
    "main",
    "parse_mapping_markdown",
    "propose_mapping",
    "read_relationships",
    "render_mapping_markdown",
    "render_relationships_markdown",
    "render_schema_markdown",
    "write_schema_files",
]
