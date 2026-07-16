import unittest

from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema
from mc_artifact_parser.platforms.unity_catalog import UnityCatalogAdapter


def _result_with_entities(*entities: EntitySchema) -> ArtifactParseResult:
    return ArtifactParseResult(source_path="schema.docx", artifact_type="docx", entities=list(entities))


class TestUnityCatalogAdapter(unittest.TestCase):
    def test_basic_table_ddl(self) -> None:
        entity = EntitySchema(
            name="Customer",
            columns=[
                ColumnSchema(name="customer_id", data_type="int", nullable=False, primary_key=True),
                ColumnSchema(name="email", data_type="varchar", nullable=True),
            ],
        )
        ddl = UnityCatalogAdapter().render(_result_with_entities(entity))
        self.assertIn("CREATE TABLE IF NOT EXISTS customer", ddl)
        self.assertIn("customer_id INT NOT NULL", ddl)
        self.assertIn("email STRING", ddl)
        self.assertIn("CONSTRAINT pk_customer PRIMARY KEY (customer_id)", ddl)
        self.assertIn("USING DELTA", ddl)

    def test_type_mapping(self) -> None:
        adapter = UnityCatalogAdapter()
        self.assertEqual(adapter._map_type("varchar"), "STRING")
        self.assertEqual(adapter._map_type("text"), "STRING")
        self.assertEqual(adapter._map_type("int"), "INT")
        self.assertEqual(adapter._map_type("integer"), "INT")
        self.assertEqual(adapter._map_type("bigint"), "BIGINT")
        self.assertEqual(adapter._map_type("boolean"), "BOOLEAN")
        self.assertEqual(adapter._map_type("bool"), "BOOLEAN")
        self.assertEqual(adapter._map_type("datetime"), "TIMESTAMP")
        self.assertEqual(adapter._map_type("timestamp"), "TIMESTAMP")
        self.assertEqual(adapter._map_type("float"), "FLOAT")
        self.assertEqual(adapter._map_type("double"), "DOUBLE")
        self.assertEqual(adapter._map_type("decimal"), "DECIMAL")
        self.assertEqual(adapter._map_type("date"), "DATE")
        self.assertEqual(adapter._map_type(None), "STRING")
        self.assertEqual(adapter._map_type("unknown_type"), "STRING")

    def test_snake_case_table_names_in_ddl(self) -> None:
        entities = [
            EntitySchema(
                name="CustomerOrder",
                columns=[ColumnSchema(name="id", data_type="int", primary_key=True)],
            ),
            EntitySchema(
                name="SalesOrder",
                columns=[ColumnSchema(name="id", data_type="int", primary_key=True)],
            ),
        ]
        ddl = UnityCatalogAdapter().render(_result_with_entities(*entities))
        self.assertIn("CREATE TABLE IF NOT EXISTS customer_order", ddl)
        self.assertIn("CREATE TABLE IF NOT EXISTS sales_order", ddl)

    def test_multiple_entities_separated_by_blank_line(self) -> None:
        entities = [
            EntitySchema(
                name="Customer",
                columns=[ColumnSchema(name="customer_id", data_type="int", nullable=False, primary_key=True)],
            ),
            EntitySchema(
                name="Order",
                columns=[ColumnSchema(name="order_id", data_type="int", nullable=False, primary_key=True)],
            ),
        ]
        ddl = UnityCatalogAdapter().render(_result_with_entities(*entities))
        self.assertIn("CREATE TABLE IF NOT EXISTS customer", ddl)
        self.assertIn("CREATE TABLE IF NOT EXISTS order", ddl)
        # Separated by a blank line
        self.assertIn("\n\n", ddl)

    def test_nullable_column_has_no_not_null(self) -> None:
        entity = EntitySchema(
            name="Log",
            columns=[ColumnSchema(name="message", data_type="string", nullable=True)],
        )
        ddl = UnityCatalogAdapter().render(_result_with_entities(entity))
        self.assertIn("message STRING", ddl)
        self.assertNotIn("NOT NULL", ddl)

    def test_no_pk_constraint_when_no_primary_key_columns(self) -> None:
        entity = EntitySchema(
            name="Config",
            columns=[ColumnSchema(name="key", data_type="string")],
        )
        ddl = UnityCatalogAdapter().render(_result_with_entities(entity))
        self.assertNotIn("CONSTRAINT pk_", ddl)

    def test_empty_result_renders_empty_string(self) -> None:
        result = ArtifactParseResult(source_path="x.docx", artifact_type="docx")
        ddl = UnityCatalogAdapter().render(result)
        self.assertEqual(ddl, "")


if __name__ == "__main__":
    unittest.main()
