"""Data model shared by the propose-mapping and create-schema steps."""

from __future__ import annotations

from dataclasses import dataclass, field

# The fixed set of target columns for the data dictionary, in output order.
# A reviewer maps each extracted column from the source document onto one of
# these target columns in the proposed mapping.
TARGET_COLUMNS: list[str] = [
    "Column",
    "DataType",
    "Nullable(Y/N)",
    "Primary Key (Y/N)",
    "Foreign Key (Y/N)",
    "Related Entity",
    "Details",
    "Description",
]


@dataclass
class SourceTable:
    """A table detected in the source ``.docx``.

    ``headers`` are the raw column labels from the first row (the *extracted
    columns*) and ``rows`` are the remaining data rows, aligned to ``headers``.
    """

    name: str
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class ColumnSet:
    """A group of source tables that share the same extracted-column signature.

    ``pairs`` is the ordered crosswalk shown in the proposed mapping: each entry
    is ``(extracted_column, target_column)`` where either side may be empty.
    """

    table_names: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)

    def target_to_extracted(self) -> dict[str, str]:
        """Return a lookup of target column -> extracted column for filled pairs."""

        mapping: dict[str, str] = {}
        for extracted, target in self.pairs:
            if extracted and target and target not in mapping:
                mapping[target] = extracted
        return mapping
