import unittest

from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema
from mc_artifact_parser.outputs.data_dictionary import DataDictionaryOutput
from mc_artifact_parser.outputs.mermaid_erd import MermaidErdOutput
from mc_artifact_parser.outputs.open_questions import OpenQuestionsOutput


def _sample_result() -> ArtifactParseResult:
    customer = EntitySchema(
        name="Customer",
        implied_tables=["Customer"],
        columns=[
            ColumnSchema(name="customer_id", data_type="int", nullable=False, primary_key=True),
            ColumnSchema(name="email", data_type="varchar", nullable=True, primary_key=False),
        ],
        related_entities=["Order"],
        open_questions=["Should guest customers be supported?"],
    )
    order = EntitySchema(
        name="Order",
        implied_tables=["Order"],
        columns=[
            ColumnSchema(name="order_id", data_type="int", nullable=False, primary_key=True),
            ColumnSchema(name="customer_id", data_type="int", nullable=False, primary_key=False),
        ],
        related_entities=[],
        open_questions=[],
    )
    return ArtifactParseResult(
        source_path="/path/to/schema.docx",
        artifact_type="docx",
        entities=[customer, order],
        open_questions=["Any global concern?"],
    )


class TestDataDictionaryOutput(unittest.TestCase):
    def test_renders_header_and_source(self) -> None:
        output = DataDictionaryOutput().render(_sample_result())
        self.assertIn("# Data Dictionary", output)
        self.assertIn("**Source:** /path/to/schema.docx", output)
        self.assertIn("**Format:** docx", output)

    def test_renders_entity_sections(self) -> None:
        output = DataDictionaryOutput().render(_sample_result())
        self.assertIn("## Customer", output)
        self.assertIn("## Order", output)

    def test_renders_column_table(self) -> None:
        output = DataDictionaryOutput().render(_sample_result())
        self.assertIn("| customer_id | int | No | Yes |", output)
        self.assertIn("| email | varchar | Yes | No |", output)

    def test_renders_related_entities(self) -> None:
        output = DataDictionaryOutput().render(_sample_result())
        self.assertIn("**Related Entities:** Order", output)

    def test_renders_open_questions(self) -> None:
        output = DataDictionaryOutput().render(_sample_result())
        self.assertIn("**Open Questions:**", output)
        self.assertIn("- Should guest customers be supported?", output)

    def test_entity_no_columns_placeholder(self) -> None:
        result = ArtifactParseResult(
            source_path="x.docx",
            artifact_type="docx",
            entities=[EntitySchema(name="Empty")],
        )
        output = DataDictionaryOutput().render(result)
        self.assertIn("*No columns defined.*", output)


class TestMermaidErdOutput(unittest.TestCase):
    def test_renders_mermaid_fences_and_er_diagram(self) -> None:
        output = MermaidErdOutput().render(_sample_result())
        self.assertTrue(output.startswith("```mermaid"))
        self.assertIn("erDiagram", output)
        self.assertTrue(output.strip().endswith("```"))

    def test_renders_entity_blocks(self) -> None:
        output = MermaidErdOutput().render(_sample_result())
        self.assertIn("Customer {", output)
        self.assertIn("Order {", output)

    def test_pk_annotation(self) -> None:
        output = MermaidErdOutput().render(_sample_result())
        self.assertIn("customer_id PK", output)

    def test_fk_annotation_for_id_suffix(self) -> None:
        output = MermaidErdOutput().render(_sample_result())
        # customer_id in Order entity is not PK, ends in _id → FK
        lines = output.splitlines()
        order_block = False
        found_fk = False
        for line in lines:
            if "Order {" in line:
                order_block = True
            if order_block and "customer_id" in line and "FK" in line:
                found_fk = True
        self.assertTrue(found_fk)

    def test_renders_relationships(self) -> None:
        output = MermaidErdOutput().render(_sample_result())
        self.assertIn("Customer ||--o{", output)

    def test_no_entities_renders_empty_diagram(self) -> None:
        result = ArtifactParseResult(source_path="x.docx", artifact_type="docx")
        output = MermaidErdOutput().render(result)
        self.assertIn("erDiagram", output)


class TestOpenQuestionsOutput(unittest.TestCase):
    def test_renders_global_and_entity_questions(self) -> None:
        output = OpenQuestionsOutput().render(_sample_result())
        self.assertIn("# Open Questions", output)
        self.assertIn("*(global)*", output)
        self.assertIn("- Any global concern?", output)
        self.assertIn("**Customer**", output)
        self.assertIn("- Should guest customers be supported?", output)

    def test_no_questions_placeholder(self) -> None:
        result = ArtifactParseResult(source_path="x.docx", artifact_type="docx")
        output = OpenQuestionsOutput().render(result)
        self.assertIn("*No open questions.*", output)

    def test_entity_without_questions_not_rendered(self) -> None:
        output = OpenQuestionsOutput().render(_sample_result())
        # Order has no questions — its heading should not appear
        self.assertNotIn("**Order**", output)


if __name__ == "__main__":
    unittest.main()
