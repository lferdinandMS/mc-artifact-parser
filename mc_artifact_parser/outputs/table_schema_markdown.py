from __future__ import annotations

from mc_artifact_parser.models import ArtifactParseResult, EntitySchema
from mc_artifact_parser.outputs.base import OutputRenderer


class TableSchemaMarkdownOutput(OutputRenderer):
    """Render a single entity as a table-specific schema markdown document."""

    def render(self, result: ArtifactParseResult) -> str:
        if not result.entities:
            return ""

        lines: list[str] = []
        for entity in result.entities:
            lines.extend(self._render_entity(entity, result.source_path))

        return "\n".join(lines).rstrip()

    def _render_entity(self, entity: EntitySchema, source_path: str) -> list[str]:
        lines: list[str] = [f"# {entity.name}"]

        if source_path:
            lines.append("")
            lines.append(f"**Source:** {source_path}")

        lines.append("")
        lines.append("## Columns")
        lines.append("")
        if not entity.columns:
            lines.append("*No columns defined.*")
        else:
            lines.append("| Column | Type | Nullable | Primary Key |")
            lines.append("|--------|------|----------|-------------|")
            for column in entity.columns:
                nullable_str = {True: "Yes", False: "No", None: ""}.get(column.nullable, "")
                pk_str = "Yes" if column.primary_key else "No"
                lines.append(
                    f"| {column.name} | {column.data_type or ''} | {nullable_str} | {pk_str} |"
                )

        if entity.related_entities:
            lines.append("")
            lines.append("## Related Entities")
            for related in entity.related_entities:
                lines.append(f"- {related}")

        if entity.open_questions:
            lines.append("")
            lines.append("## Open Questions")
            for question in entity.open_questions:
                lines.append(f"- {question}")

        return lines
