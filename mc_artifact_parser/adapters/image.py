from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from mc_artifact_parser.adapters.base import ArtifactAdapter
from mc_artifact_parser.adapters.schema_text import SchemaTextParser
from mc_artifact_parser.models import ArtifactParseResult


class ImageAdapter(ArtifactAdapter):
    _SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}

    def __init__(self, text_extractor: Callable[[str], str] | None = None) -> None:
        self._text_extractor = text_extractor or self._extract_text_with_tesseract
        self._text_parser = SchemaTextParser()

    def can_parse(self, path: str) -> bool:
        return Path(path).suffix.lower() in self._SUPPORTED_SUFFIXES

    def parse(self, path: str) -> ArtifactParseResult:
        text = self._text_extractor(path)
        lines = text.splitlines()
        if not lines:
            raise ValueError(f"No schema text could be extracted from {path}.")
        return self._text_parser.parse_lines(lines, path, "image")

    def _extract_text_with_tesseract(self, path: str) -> str:
        if shutil.which("tesseract") is None:
            raise ValueError(
                "Image parsing requires Tesseract OCR. Install Tesseract or pass a custom text_extractor."
            )

        command = ["tesseract", path, "stdout", "--psm", "6"]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise ValueError(f"Tesseract OCR failed for {path}: {stderr or 'unknown error'}")

        return completed.stdout.strip()
