from __future__ import annotations

from mc_artifact_parser.models import ArtifactParseResult
from mc_artifact_parser.outputs.base import OutputRenderer


class SourceReviewOutput(OutputRenderer):
    """Render a source review summary prior to mapping and drafting."""

    def render(self, result: ArtifactParseResult) -> str:
        lines: list[str] = ["# Source Review"]
        lines.append("")
        lines.append(f"**Source:** {result.source_path}")
        lines.append(f"**Format:** {result.artifact_type}")
        lines.append("")
        lines.append(f"**Entity Count:** {len(result.entities)}")

        if not result.entities:
            lines.append("")
            lines.append("*No entities were detected.*")
            return "\n".join(lines)

        for entity in result.entities:
            lines.append("")
            lines.append(f"## {entity.name}")
            lines.append(f"- Parsed columns: {len(entity.columns)}")
            if entity.columns:
                lines.append("- Columns:")
                for column in entity.columns:
                    lines.append(f"  - {column.name}")
            if entity.related_entities:
                lines.append(f"- Related entities: {', '.join(entity.related_entities)}")
            if entity.open_questions:
                lines.append("- Open questions:")
                for question in entity.open_questions:
                    lines.append(f"  - {question}")

        if result.open_questions:
            lines.append("")
            lines.append("## Open Questions")
            for question in result.open_questions:
                lines.append(f"- {question}")

        return "\n".join(lines)