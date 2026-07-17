from __future__ import annotations

from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema
from mc_artifact_parser.outputs.base import OutputRenderer
from mc_artifact_parser.outputs.formatting import normalize_column_name, normalize_table_name


class DataDictionaryOutput(OutputRenderer):
    """Render an ``ArtifactParseResult`` as a Markdown data dictionary.

    Each entity is rendered as a section containing a column table and optional
    related-entities and open-questions sub-sections.
    """

    def __init__(self, header_mapping: dict[str, str] | None = None) -> None:
        self._header_mapping = {
            "Column": "Column",
            "Type": "Type",
            "Nullable": "Nullable",
            "Primary Key": "Primary Key",
            "Foreign Key": "Foreign Key",
            "Details": "Details",
            "Description": "Description",
        }
        if header_mapping:
            self._header_mapping.update({key: value for key, value in header_mapping.items() if value})

    def render(self, result: ArtifactParseResult) -> str:
        lines: list[str] = []
        lines.append("# Data Dictionary")
        lines.append("")
        lines.append(f"**Source:** {result.source_path}")
        lines.append(f"**Format:** {result.artifact_type}")

        for entity in result.entities:
            lines.append("")
            lines.append(f"## {normalize_table_name(entity.name)}")
            lines.append("")
            lines.extend(self._render_columns(entity))

            if entity.related_entities:
                lines.append("")
                lines.append(f"**Related Entities:** {', '.join(entity.related_entities)}")

            if entity.open_questions:
                lines.append("")
                lines.append("**Open Questions:**")
                for q in entity.open_questions:
                    lines.append(f"- {q}")

        return "\n".join(lines)

    def _render_columns(self, entity: EntitySchema) -> list[str]:
        if not entity.columns:
            return ["*No columns defined.*"]

        headers = [
            self._header_mapping["Column"],
            self._header_mapping["Type"],
            self._header_mapping["Nullable"],
            self._header_mapping["Primary Key"],
            self._header_mapping["Foreign Key"],
            self._header_mapping["Details"],
            self._header_mapping["Description"],
        ]

        rows: list[str] = [
            f"| {' | '.join(headers)} |",
            "|--------|------|----------|-------------|-------------|---------|-------------|",
        ]
        for col in entity.columns:
            nullable_str = {True: "Yes", False: "No", None: ""}.get(col.nullable, "")
            pk_str = "Yes" if col.primary_key else "No"
            rows.append(
                f"| {normalize_column_name(col.name)} | {col.data_type or ''} | {nullable_str} | {pk_str} | {col.foreign_key or ''} | {col.description or ''} |  |"
            )
        return rows
