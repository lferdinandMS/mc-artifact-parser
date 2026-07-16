from __future__ import annotations

import re

from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema
from mc_artifact_parser.platforms.base import PlatformAdapter


class UnityCatalogAdapter(PlatformAdapter):
    """Convert a logical ``ArtifactParseResult`` to Databricks Unity Catalog DDL.

    Each entity becomes a ``CREATE TABLE IF NOT EXISTS`` statement using
    Delta Lake format.  Logical types are mapped to Unity Catalog SQL types;
    unmapped types default to ``STRING``.

    Example output::

        CREATE TABLE IF NOT EXISTS customer (
            customer_id INT NOT NULL,
            email STRING,
            CONSTRAINT pk_customer PRIMARY KEY (customer_id)
        ) USING DELTA;
    """

    _TYPE_MAP: dict[str, str] = {
        "int": "INT",
        "integer": "INT",
        "bigint": "BIGINT",
        "long": "BIGINT",
        "smallint": "SMALLINT",
        "tinyint": "TINYINT",
        "float": "FLOAT",
        "real": "FLOAT",
        "double": "DOUBLE",
        "decimal": "DECIMAL",
        "numeric": "DECIMAL",
        "boolean": "BOOLEAN",
        "bool": "BOOLEAN",
        "string": "STRING",
        "varchar": "STRING",
        "char": "STRING",
        "text": "STRING",
        "nvarchar": "STRING",
        "date": "DATE",
        "datetime": "TIMESTAMP",
        "timestamp": "TIMESTAMP",
        "binary": "BINARY",
        "bytes": "BINARY",
        "array": "ARRAY<STRING>",
        "map": "MAP<STRING, STRING>",
        "struct": "STRUCT<>",
    }
    _DEFAULT_TYPE = "STRING"

    def render(self, result: ArtifactParseResult) -> str:
        statements: list[str] = []
        for entity in result.entities:
            statements.append(self._render_entity(entity))
        return "\n\n".join(statements)

    def _render_entity(self, entity: EntitySchema) -> str:
        table_name = self._to_snake_case(entity.name)
        col_lines: list[str] = [self._render_column(col) for col in entity.columns]

        pk_cols = [col.name for col in entity.columns if col.primary_key]
        if pk_cols:
            pk_names = ", ".join(pk_cols)
            col_lines.append(f"    CONSTRAINT pk_{table_name} PRIMARY KEY ({pk_names})")

        body = ",\n".join(col_lines)
        return (
            f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
            f"{body}\n"
            f") USING DELTA;"
        )

    def _render_column(self, col: ColumnSchema) -> str:
        uc_type = self._map_type(col.data_type)
        not_null = " NOT NULL" if col.nullable is False else ""
        return f"    {col.name} {uc_type}{not_null}"

    def _map_type(self, data_type: str | None) -> str:
        if not data_type:
            return self._DEFAULT_TYPE
        base = re.split(r"[\s(]", data_type.strip().lower())[0]
        return self._TYPE_MAP.get(base, self._DEFAULT_TYPE)

    @staticmethod
    def _to_snake_case(name: str) -> str:
        s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
        s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
        return s.lower().replace(" ", "_")
