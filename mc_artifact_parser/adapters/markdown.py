from __future__ import annotations

import re
from pathlib import Path

from mc_artifact_parser.adapters.base import ArtifactAdapter
from mc_artifact_parser.adapters.column_parsing import parse_column_line
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
    _SECTION_HEADINGS = {
        "columns",
        "related entities",
        "related entity",
        "open questions",
        "open question",
        "mapping",
    }
    _NON_ENTITY_TITLES = {
        "data dictionary",
        "open questions",
        "source review",
        "session mapping proposal",
    }

    def can_parse(self, path: str) -> bool:
        return Path(path).suffix.lower() == ".md"

    def parse(self, path: str) -> ArtifactParseResult:
        lines = self._extract_lines(path)
        result = ArtifactParseResult(source_path=path, artifact_type="markdown")
        current_entity: EntitySchema | None = None
        current_section: str | None = None
        h1_title: str | None = None

        for raw_line in lines:
            stripped = raw_line.strip()

            # Headings can define entities, document titles, or section labels.
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()

                if level == 1:
                    h1_title = heading_text
                    current_section = None
                    continue

                if self._is_section_heading(heading_text):
                    current_section = heading_text.strip().lower()
                    if current_entity is None and h1_title and not self._is_non_entity_title(h1_title):
                        current_entity = EntitySchema(name=h1_title, implied_tables=[h1_title])
                        result.entities.append(current_entity)
                    continue

                explicit = self._ENTITY_HEADER.match(heading_text)
                entity_name = explicit.group(1).strip() if explicit else heading_text
                current_entity = EntitySchema(name=entity_name, implied_tables=[entity_name])
                result.entities.append(current_entity)
                current_section = None
                continue

            line = self._normalize_line(stripped)
            if not line:
                continue

            if current_section in {"open questions", "open question"}:
                if current_entity:
                    current_entity.open_questions.append(line)
                else:
                    result.open_questions.append(line)
                continue

            # Non-heading "Entity: Name" / "Table: Name" lines also start an entity.
            entity_match = self._ENTITY_HEADER.match(line)
            if entity_match:
                entity_name = entity_match.group(1).strip()
                current_entity = EntitySchema(name=entity_name, implied_tables=[entity_name])
                result.entities.append(current_entity)
                current_section = None
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

            if current_section == "columns":
                row_cells = self._parse_markdown_table_row(line)
                if row_cells is not None:
                    column = self._column_from_table_row(row_cells)
                    if column is not None:
                        current_entity.columns.append(column)
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
        return parse_column_line(line)

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

    def _is_section_heading(self, heading_text: str) -> bool:
        return heading_text.strip().lower() in self._SECTION_HEADINGS

    def _is_non_entity_title(self, title: str) -> bool:
        return title.strip().lower() in self._NON_ENTITY_TITLES

    def _parse_markdown_table_row(self, line: str) -> list[str] | None:
        if not (line.startswith("|") and line.endswith("|")):
            return None

        cells = [part.strip() for part in line.strip("|").split("|")]
        return cells

    def _column_from_table_row(self, cells: list[str]) -> ColumnSchema | None:
        if not cells:
            return None

        first = cells[0].strip().lower()
        if first == "column":
            return None
        if re.fullmatch(r"-+", first):
            return None

        name = cells[0].strip()
        if not name:
            return None

        data_type = cells[1].strip() if len(cells) > 1 else ""
        nullable_raw = cells[2].strip().lower() if len(cells) > 2 else ""
        primary_key_raw = cells[3].strip().lower() if len(cells) > 3 else ""
        foreign_key = cells[4].strip() if len(cells) > 4 else ""
        details = cells[5].strip() if len(cells) > 5 else ""
        description = cells[6].strip() if len(cells) > 6 else ""

        nullable: bool | None = None
        if nullable_raw == "yes":
            nullable = True
        elif nullable_raw == "no":
            nullable = False

        primary_key = primary_key_raw == "yes"

        detail_or_description = details or description or None

        return ColumnSchema(
            name=name,
            data_type=data_type or None,
            nullable=nullable,
            primary_key=primary_key,
            foreign_key=foreign_key or None,
            description=detail_or_description,
        )
