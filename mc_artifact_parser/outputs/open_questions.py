from __future__ import annotations

from mc_artifact_parser.models import ArtifactParseResult
from mc_artifact_parser.outputs.base import OutputRenderer


class OpenQuestionsOutput(OutputRenderer):
    """Render all open questions from an ``ArtifactParseResult`` as a Markdown list.

    Global questions (not tied to any entity) are listed first under a
    *Global* section.  Per-entity questions follow in separate sections.
    """

    def render(self, result: ArtifactParseResult) -> str:
        lines: list[str] = ["# Open Questions"]

        has_content = False

        if result.open_questions:
            has_content = True
            lines.append("")
            lines.append("*(global)*")
            for q in result.open_questions:
                lines.append(f"- {q}")

        for entity in result.entities:
            if entity.open_questions:
                has_content = True
                lines.append("")
                lines.append(f"**{entity.name}**")
                for q in entity.open_questions:
                    lines.append(f"- {q}")

        if not has_content:
            lines.append("")
            lines.append("*No open questions.*")

        return "\n".join(lines)
