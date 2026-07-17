from __future__ import annotations

from mc_artifact_parser.models import ArtifactParseResult, EntitySchema
from mc_artifact_parser.outputs.base import OutputRenderer
from mc_artifact_parser.outputs.formatting import normalize_table_name


class MappingMarkdownOutput(OutputRenderer):
    """Render a human-review mapping sheet for each entity.

    The sheet provides a compact reviewer-controlled mapping from parsed output
    fields to the intended target output fields.
    """

    def render(self, result: ArtifactParseResult) -> str:
        if not result.entities:
            return ""

        lines: list[str] = []
        for entity in result.entities:
            lines.extend(self._render_entity(entity, result.source_path))

        return "\n".join(lines).rstrip()

    def _render_entity(self, entity: EntitySchema, source_path: str) -> list[str]:
        lines: list[str] = [f"# {normalize_table_name(entity.name)}"]

        if source_path:
            lines.append("")
            lines.append(f"**Source:** {source_path}")

        lines.append("")
        lines.append("## Mapping")
        lines.append("")

        lines.append("Parsed Item|Target Item")
        lines.append("|----------|-----------|")
        lines.append("|Column|Column|")
        lines.append("|Type|Type|")
        lines.append("|Nullable|Nullable|")
        lines.append("|Primary Key|Primary Key|")
        lines.append("|Foreign Key|Foreign Key|")
        lines.append("|Details|Details|")
        lines.append("||Description|")

        if entity.open_questions:
            lines.append("")
            lines.append("## Open Questions")
            for question in entity.open_questions:
                lines.append(f"- {question}")

        return lines