from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from mc_artifact_parser.adapters.base import ArtifactAdapter
from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema


class DocxAdapter(ArtifactAdapter):
    # Supported section markers in DOCX paragraph text:
    # - Entity/table headers: "Entity: Name" / "Table: Name"
    # - Explicit open questions: "Open Question: ..."
    # - Related entities lists: "Related Entities: A, B"
    _ENTITY_HEADER = re.compile(r"^(?:entity|table)\s*[:\-]\s*(.+)$", re.IGNORECASE)
    _OPEN_QUESTION_PREFIX = re.compile(r"^open\s*question\s*[:\-]\s*(.+)$", re.IGNORECASE)
    _RELATED_PREFIX = re.compile(r"^related\s*entities?\s*[:\-]\s*(.+)$", re.IGNORECASE)
    _COLUMN_PATTERN = re.compile(
        r"^([A-Za-z_][\w]*)\s*(?:\(([^)]+)\)|:\s*([A-Za-z_][\w()\[\],\s]*))?\s*(.*)$"
    )

    def can_parse(self, path: str) -> bool:
        return Path(path).suffix.lower() == ".docx"

    def parse(self, path: str) -> ArtifactParseResult:
        lines = self._extract_lines(path)
        result = ArtifactParseResult(source_path=path, artifact_type="docx")
        current_entity: EntitySchema | None = None

        for raw_line in lines:
            line = self._normalize_line(raw_line)
            if not line:
                continue

            entity_match = self._ENTITY_HEADER.match(line)
            if entity_match:
                entity_name = entity_match.group(1).strip()
                current_entity = EntitySchema(name=entity_name, implied_tables=[entity_name])
                result.entities.append(current_entity)
                continue

            question = self._extract_question(line)
            if question:
                if current_entity:
                    current_entity.open_questions.append(question)
                else:
                    result.open_questions.append(question)
                continue

            if current_entity is None:
                continue

            related_match = self._RELATED_PREFIX.match(line)
            if related_match:
                self._add_related_entities(current_entity, related_match.group(1))
                continue

            column = self._parse_column(line)
            if column:
                current_entity.columns.append(column)
                for ref in self._extract_reference_entities(line):
                    self._append_unique(current_entity.related_entities, ref)
                continue

            for implied in self._extract_implied_tables(line):
                self._append_unique(current_entity.implied_tables, implied)

        return result

    def _extract_lines(self, path: str) -> list[str]:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")

        root = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        lines: list[str] = []

        for paragraph in root.findall(".//w:p", ns):
            line = "".join(node.text for node in paragraph.findall(".//w:t", ns) if node.text).strip()
            if line:
                lines.append(line)

        return lines

    def _normalize_line(self, line: str) -> str:
        return re.sub(r"^[\-\*•]\s*", "", line.strip())

    def _extract_question(self, line: str) -> str | None:
        prefix_match = self._OPEN_QUESTION_PREFIX.match(line)
        if prefix_match:
            return prefix_match.group(1).strip()

        if line.endswith("?"):
            return line

        return None

    def _add_related_entities(self, entity: EntitySchema, related_text: str) -> None:
        for name in re.split(r"\s*,\s*", related_text):
            clean = name.strip()
            if clean:
                self._append_unique(entity.related_entities, clean)

    def _parse_column(self, line: str) -> ColumnSchema | None:
        # Regex capture groups: 1=column name, 2=type in parentheses, 3=type after colon, 4=trailing metadata.
        match = self._COLUMN_PATTERN.match(line)
        if not match:
            return None

        name, paren_type, colon_type, trailing = match.groups()
        lowered = line.lower()
        data_type = paren_type or colon_type
        nullable = None
        if "not null" in lowered or "required" in lowered:
            nullable = False
        elif "nullable" in lowered or "optional" in lowered or "null allowed" in lowered:
            nullable = True

        primary_key = bool(re.search(r"\b(primary\s+key|pk)\b", lowered))

        looks_like_column_definition = bool(data_type or nullable is not None or primary_key or trailing.strip())
        if not looks_like_column_definition:
            return None

        return ColumnSchema(
            name=name,
            data_type=data_type.strip() if data_type else None,
            nullable=nullable,
            primary_key=primary_key,
        )

    def _extract_reference_entities(self, line: str) -> list[str]:
        refs = []
        for pattern in (r"\breferences\s+([A-Za-z_][\w]*)", r"\bforeign\s+key\s+to\s+([A-Za-z_][\w]*)"):
            refs.extend(re.findall(pattern, line, flags=re.IGNORECASE))
        return refs

    def _extract_implied_tables(self, line: str) -> list[str]:
        return re.findall(r"\btable\s+([A-Za-z_][\w]*)", line, flags=re.IGNORECASE)

    def _append_unique(self, items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)
