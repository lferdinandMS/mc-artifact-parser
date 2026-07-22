from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from docx_schema.models import SourceTable

MAX_SOURCE_BYTES = 10 * 1024 * 1024


@runtime_checkable
class SourceReader(Protocol):
    """A component that turns one source file into extracted tables."""

    def can_read(self, path: str) -> bool:
        ...

    def read(self, path: str) -> list[SourceTable]:
        ...


def local_name(tag: str) -> str:
    return tag.split("}", maxsplit=1)[-1]


def reject_xml_declarations(data: bytes) -> None:
    if re.search(br"<!\s*(doctype|entity)\b", data, flags=re.IGNORECASE):
        raise ValueError("Source contains disallowed XML declarations.")


def entity_name_from_path(path: str, fallback: str = "table_1") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", Path(path).stem).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or fallback
