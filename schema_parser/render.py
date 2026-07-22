from __future__ import annotations

from schema_parser.models import ColumnSet, Relationship, TableSchema, TARGET_COLUMNS


def render_mapping_markdown(column_sets: list[ColumnSet]) -> str:
    lines = ["# Proposed Mapping", ""]

    for index, column_set in enumerate(column_sets, start=1):
        lines.append(f"## Column Set {index}")
        lines.append("")
        if column_set.table_names:
            lines.append(f"- Tables: {', '.join(column_set.table_names)}")
            lines.append("")
        lines.append("| Extracted Column | Target Column |")
        lines.append("|---|---|")
        seen_targets = {target for _, target in column_set.pairs if target}
        for source, target in column_set.pairs:
            lines.append(f"| {source} | {target} |")
        for target in TARGET_COLUMNS:
            if target not in seen_targets:
                lines.append(f"|  | {target} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_schema_markdown(table: TableSchema) -> str:
    lines = [f"# {table.name} Schema", ""]
    lines.extend(_render_wide_table_lines(table.columns))
    lines.extend(
        [
            "",
            "## Custom Riders",
            "",
            "_None defined._",
            "",
            "## Provenance / Audit Columns",
            "",
            "_None defined._",
            "",
            "Supplied by the target adapter for the destination platform.",
            "",
        ]
    )
    return "\n".join(lines)


def render_relationships_markdown(relationships: list[Relationship]) -> str:
    lines = ["# Relationships", ""]

    if not relationships:
        lines.append("_No relationships found._")
        return "\n".join(lines) + "\n"

    lines.append("| Source Table | Source Column | Target Table | Target Column |")
    lines.append("|---|---|---|---|")
    for relationship in relationships:
        lines.append(
            f"| {relationship.source_table} | {relationship.source_column or '*'} "
            f"| {relationship.target_table} | {relationship.target_column or '*'} |"
        )

    lines.append("")
    lines.append("## Mermaid ERD")
    lines.append("")
    lines.append("```mermaid")
    lines.append("erDiagram")
    for relationship in relationships:
        label = f"{relationship.source_column or '*'} -> {relationship.target_column or '*'}"
        lines.append(
            f'    {relationship.source_table} ||--o{{ {relationship.target_table} : "{label}"'
        )
    lines.append("```")

    return "\n".join(lines) + "\n"


def _render_wide_table_lines(rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(TARGET_COLUMNS) + " |",
        "|" + "|".join(["---"] * len(TARGET_COLUMNS)) + "|",
    ]

    for row in rows:
        padded = row + [""] * max(0, len(TARGET_COLUMNS) - len(row))
        lines.append("| " + " | ".join(padded[: len(TARGET_COLUMNS)]) + " |")

    return lines
