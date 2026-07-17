"""Minimal DOCX-to-schema toolkit.

``propose-mapping`` reads a ``.docx`` and writes a reviewer-editable proposed
mapping markdown: a per-column-set crosswalk that lists the extracted columns
found in the document and the fixed target data-dictionary columns, for a human
to pair up.

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

__all__ = [
    "TARGET_COLUMNS",
    "SourceTable",
    "ColumnSet",
    "build_source_tables_from_docx",
    "group_column_sets",
    "render_mapping_markdown",
    "write_mapping_markdown",
]
