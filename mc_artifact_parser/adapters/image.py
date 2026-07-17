from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from mc_artifact_parser.adapters.base import ArtifactAdapter
from mc_artifact_parser.adapters.schema_text import SchemaTextParser
from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema


class ImageAdapter(ArtifactAdapter):
    _SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
    _MAX_FALLBACK_COLUMNS = 40

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
        result = self._text_parser.parse_lines(lines, path, "image")
        if result.entities:
            return result

        # OCR screenshots often contain useful table-like lines but no explicit
        # "Entity:" or markdown headings. Build a best-effort inferred entity.
        fallback_columns = self._extract_fallback_columns(lines)
        if fallback_columns:
            inferred_entity = EntitySchema(
                name=self._infer_entity_name(path),
                implied_tables=[self._infer_entity_name(path)],
                columns=fallback_columns,
            )
            result.entities.append(inferred_entity)
            result.open_questions.append(
                "Entity was inferred from OCR text because no explicit table/entity heading was detected."
            )
        return result

    def _infer_entity_name(self, path: str) -> str:
        stem = Path(path).stem
        cleaned = re.sub(r"[^A-Za-z0-9]+", " ", stem).strip()
        if not cleaned:
            return "InferredEntity"
        return " ".join(part.capitalize() for part in cleaned.split())

    def _extract_fallback_columns(self, lines: list[str]) -> list[ColumnSchema]:
        columns: list[ColumnSchema] = []
        seen_names: set[str] = set()

        for raw_line in lines:
            line = re.sub(r"\s+", " ", raw_line.strip())
            if not line:
                continue
            if len(line) > 120:
                continue
            if re.fullmatch(r"[\W_]+", line):
                continue
            if line.lower().startswith(("http://", "https://")):
                continue
            if self._is_noisy_ocr_line(line):
                continue

            candidate = self._column_from_line(line)
            if candidate is None:
                continue

            dedupe_key = candidate.name.strip().lower()
            if not dedupe_key or dedupe_key in seen_names:
                continue

            seen_names.add(dedupe_key)
            columns.append(candidate)
            if len(columns) >= self._MAX_FALLBACK_COLUMNS:
                break

        return columns

    def _is_noisy_ocr_line(self, line: str) -> bool:
        # Drop common mojibake artifacts and lines dominated by symbols.
        lowered = line.lower()
        if "â" in lowered or "ã" in lowered or "ï" in lowered:
            return True

        alpha_count = sum(1 for char in line if char.isalpha())
        if alpha_count == 0:
            return True

        symbol_count = sum(1 for char in line if not char.isalnum() and not char.isspace())
        if symbol_count / max(len(line), 1) > 0.35:
            return True

        return False

    def _column_from_line(self, line: str) -> ColumnSchema | None:
        # Common OCR pattern: "Label Can we ...?" or "Label Do we ...?"
        qa_split = re.match(
            r"^(?P<label>[A-Za-z][A-Za-z0-9_ /&\-]{1,80})\s+(?P<question>(?:Can|Do|Is|Are|Will|Should|What|When|Where|Why|How)\b.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if qa_split:
            label = qa_split.group("label").strip(" -:\t")
            question = qa_split.group("question").strip()
            if label:
                return ColumnSchema(name=label, description=question)

        # Generic fallback for short structured lines.
        tokens = line.split()
        if len(tokens) > 14:
            return None
        return ColumnSchema(name=line)

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
