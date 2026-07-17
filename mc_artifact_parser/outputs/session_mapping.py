from __future__ import annotations

from mc_artifact_parser.models import ArtifactParseResult
from mc_artifact_parser.outputs.base import OutputRenderer


class SessionMappingOutput(OutputRenderer):
    """Render a session-level default mapping proposal."""

    def render(self, result: ArtifactParseResult) -> str:
        lines: list[str] = ["# Session Mapping Proposal"]
        lines.append("")
        lines.append(f"**Source:** {result.source_path}")
        lines.append(f"**Format:** {result.artifact_type}")
        lines.append(f"**Entity Count:** {len(result.entities)}")

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

        if result.open_questions:
            lines.append("")
            lines.append("## Open Questions")
            for question in result.open_questions:
                lines.append(f"- {question}")

        return "\n".join(lines)