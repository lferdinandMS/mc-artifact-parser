from __future__ import annotations

from mc_artifact_parser.models import ArtifactParseResult, EntitySchema
from mc_artifact_parser.outputs.base import OutputRenderer
from mc_artifact_parser.outputs.formatting import normalize_column_name, normalize_table_name


class MermaidErdOutput(OutputRenderer):
    """Render an ``ArtifactParseResult`` as a Mermaid ``erDiagram`` block.

    Entities are rendered with their columns annotated with ``PK`` / ``FK``
    where applicable.  Relationships are inferred from ``related_entities``.
    """

    def render(self, result: ArtifactParseResult) -> str:
        lines: list[str] = ["```mermaid", "erDiagram"]

        for entity in result.entities:
            lines.extend(self._render_entity_block(entity))

        for entity in result.entities:
            for related in entity.related_entities:
                lines.append(f'    {entity.name} ||--o{{ {related} : ""')

        lines.append("```")
        return "\n".join(lines)

    def _render_entity_block(self, entity: EntitySchema) -> list[str]:
        lines = [f"    {normalize_table_name(entity.name)} {{"]
        for col in entity.columns:
            col_type = col.data_type or "string"
            annotations: list[str] = []
            if col.primary_key:
                annotations.append("PK")
            elif col.name.lower().endswith("_id"):
                annotations.append("FK")
            annotation_str = f" {', '.join(annotations)}" if annotations else ""
            lines.append(f"        {col_type} {normalize_column_name(col.name)}{annotation_str}")
        lines.append("    }")
        return lines
