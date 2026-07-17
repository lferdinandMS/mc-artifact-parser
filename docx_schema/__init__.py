"""Minimal DOCX-to-schema toolkit.

Two operations:

* ``propose-mapping`` reads a ``.docx`` and writes a reviewer-editable
  proposed mapping markdown: a per-column-set crosswalk of extracted columns
  to target data-dictionary columns.
* ``create-schema`` reads the (reviewer-edited) mapping plus the source
  ``.docx`` and writes one data-dictionary extract per column set.

The package is intentionally self-contained and depends only on the Python
standard library.
"""

from __future__ import annotations

from .models import TARGET_COLUMNS, ColumnSet, SourceTable
from .mapping import (
    build_source_tables_from_docx,
    group_column_sets,
    render_mapping_markdown,
    write_mapping_markdown,
)
from .schema import (
    extract_column_set,
    parse_mapping_markdown,
    render_extract_markdown,
    write_extract_files,
)

__all__ = [
    "TARGET_COLUMNS",
    "SourceTable",
    "ColumnSet",
    "build_source_tables_from_docx",
    "group_column_sets",
    "render_mapping_markdown",
    "write_mapping_markdown",
    "parse_mapping_markdown",
    "extract_column_set",
    "render_extract_markdown",
    "write_extract_files",
]
