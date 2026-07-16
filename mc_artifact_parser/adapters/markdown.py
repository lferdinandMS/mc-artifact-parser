from __future__ import annotations

import re
from pathlib import Path

from mc_artifact_parser.adapters.base import ArtifactAdapter
from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema


class MarkdownAdapter(ArtifactAdapter):
    """Parse ``.md`` files for schema intent.

    Recognised document conventions
    --------------------------------
    * ``## Entity Name`` or ``## Entity: Entity Name`` — starts a new entity
      (H2–H6 headings; a lone H1 is treated as a document title and skipped).
    * Bullet-list lines (``-``, ``*``, ``•``) — column definitions or questions.
    * ``Related Entities: A, B`` — explicit relationship list.
    * ``Open Question: …`` prefix or lines ending in ``?`` — open questions.
    """

    _ENTITY_HEADER = re.compile(r"^(?:entity|table)\s*[:\-]\s*(.+)$", re.IGNORECASE)
    _OPEN_QUESTION_PREFIX = re.compile(r"^open\s*question\s*[:\-]\s*(.+)$", re.IGNORECASE)
    _RELATED_PREFIX = re.compile(r"^related\s*entities?\s*[:\-]\s*(.+)$", re.IGNORECASE)
    _COLUMN_PATTERN = re.compile(
        r"^([A-Za-z_][\w]*)\s*(?:\(([^)]+)\)|:\s*([A-Za-z_][\w()\[\],\s]*))?\s*(.*)$"
    )
    _REFERENCE_PATTERNS = (
        re.compile(r"\breferences\s+([A-Za-z_][\w]*)", re.IGNORECASE),
        re.compile(r"\bforeign\s+key\s+to\s+([A-Za-z_][\w]*)", re.IGNORECASE),
    )
    _MAX_FILE_BYTES = 10 * 1024 * 1024

    def can_parse(self, path: str) -> bool:
        return Path(path).suffix.lower() == ".md"

    def parse(self, path: str) -> ArtifactParseResult:
        lines = self._extract_lines(path)
        result = ArtifactParseResult(source_path=path, artifact_type="markdown")
        current_entity: EntitySchema | None = None

        for raw_line in lines:
            stripped = raw_line.strip()

            # H2–H6 headings start a new entity.
            heading_match = re.match(r"^(#{2,6})\s+(.+)$", stripped)
            if heading_match:
                heading_text = heading_match.group(2).strip()
                explicit = self._ENTITY_HEADER.match(heading_text)
                entity_name = explicit.group(1).strip() if explicit else heading_text
                current_entity = EntitySchema(name=entity_name, implied_tables=[entity_name])
                result.entities.append(current_entity)
                continue

            # H1 headings are treated as document titles — skip.
            if re.match(r"^#\s+", stripped):
                continue

            line = self._normalize_line(stripped)
            if not line:
                continue

            # Non-heading "Entity: Name" / "Table: Name" lines also start an entity.
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
        file_path = Path(path)
        if file_path.stat().st_size > self._MAX_FILE_BYTES:
            raise ValueError("Markdown file exceeds the maximum supported size.")
        return file_path.read_text(encoding="utf-8").splitlines()

    def _normalize_line(self, line: str) -> str:
        line = re.sub(r"^[\-\*•]\s*", "", line.strip())
        # Strip inline bold/italic markers so "**Related Entities**:" is recognised.
        line = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", line)
        return line.strip()

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
        match = self._COLUMN_PATTERN.match(line)
        if not match:
            return None

        name, paren_type, colon_type, trailing = match.groups()
        lowered = line.lower()
        data_type = paren_type or colon_type
        nullable: bool | None = None
        if re.search(r"\b(not\s+null|required|not\s+nullable|non[-\s]?nullable)\b", lowered):
            nullable = False
        elif re.search(r"\b(nullable|optional|null\s+allowed)\b", lowered):
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
        for pattern in self._REFERENCE_PATTERNS:
            refs.extend(pattern.findall(line))
        return refs

    def _extract_implied_tables(self, line: str) -> list[str]:
        return re.findall(r"\btable\s+([A-Za-z_][\w]*)", line, flags=re.IGNORECASE)

    def _append_unique(self, items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)
