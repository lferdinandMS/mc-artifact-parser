import unittest

from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema
from mc_artifact_parser.outputs.data_dictionary import DataDictionaryOutput
from mc_artifact_parser.outputs.mappings import MappingMarkdownOutput
from mc_artifact_parser.outputs.mermaid_erd import MermaidErdOutput
from mc_artifact_parser.outputs.open_questions import OpenQuestionsOutput
from mc_artifact_parser.outputs.session_mapping import SessionMappingOutput
from mc_artifact_parser.outputs.source_review import SourceReviewOutput


def _sample_result() -> ArtifactParseResult:
    customer = EntitySchema(
        name="Customer",
        implied_tables=["Customer"],
        columns=[
            ColumnSchema(name="customer id", data_type="int", nullable=False, primary_key=True),
            ColumnSchema(
                name="email address",
                data_type="varchar",
                nullable=True,
                primary_key=False,
                description="Primary contact email",
            ),
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

    def test_normalizes_table_heading_with_spaces(self) -> None:
        result = ArtifactParseResult(
            source_path="/path/to/schema.docx",
            artifact_type="docx",
            entities=[
                EntitySchema(
                    name="Customer Specific Invoice Payment Probability (Before)",
                    columns=[ColumnSchema(name="id", data_type="int", nullable=False, primary_key=True)],
                )
            ],
        )
        output = DataDictionaryOutput().render(result)
        self.assertIn("## Customer_Specific_Invoice_Payment_Probability_Before", output)

    def test_renders_column_table(self) -> None:
        output = DataDictionaryOutput().render(_sample_result())
        self.assertIn("| customer_id | int | No | Yes |  |  |  |", output)
        self.assertIn("| email_address | varchar | Yes | No |  | Primary contact email |  |", output)
        self.assertIn("| Column | Type | Nullable | Primary Key | Foreign Key | Details | Description |", output)

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

    def test_renders_normalized_names_in_markdown_output(self) -> None:
        output = DataDictionaryOutput().render(_sample_result())
        self.assertIn("customer_id", output)
        self.assertIn("email_address", output)


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

    def test_normalizes_mermaid_table_name_with_spaces(self) -> None:
        result = ArtifactParseResult(
            source_path="/path/to/schema.docx",
            artifact_type="docx",
            entities=[
                EntitySchema(
                    name="Customer Specific Invoice Payment Probability (Before)",
                    columns=[ColumnSchema(name="id", data_type="int", nullable=False, primary_key=True)],
                )
            ],
        )
        output = MermaidErdOutput().render(result)
        self.assertIn("Customer_Specific_Invoice_Payment_Probability_Before {", output)

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


class TestMappingMarkdownOutput(unittest.TestCase):
    def test_renders_mapping_template(self) -> None:
        result = ArtifactParseResult(
            source_path="/path/to/schema.png",
            artifact_type="image",
            entities=[
                EntitySchema(
                    name="Invoice / AR (Before)",
                    columns=[
                        ColumnSchema(name="customer id", data_type="int", nullable=False, primary_key=False),
                        ColumnSchema(name="due date", data_type="date", nullable=True, primary_key=False, description="E.g. due in 3 days"),
                    ],
                    open_questions=["Provide the types for the columns"],
                )
            ],
        )

        output = MappingMarkdownOutput().render(result)

        self.assertIn("# Invoice_AR_Before", output)
        self.assertIn("## Mapping", output)
        self.assertIn("Parsed Item|Target Item", output)
        self.assertIn("|Column|Column|", output)
        self.assertIn("|Type|Type|", output)
        self.assertIn("|Nullable|Nullable|", output)
        self.assertIn("|Primary Key|Primary Key|", output)
        self.assertIn("|Foreign Key|Foreign Key|", output)
        self.assertIn("|Details|Details|", output)
        self.assertIn("||Description|", output)
        self.assertIn("## Open Questions", output)
        self.assertIn("- Provide the types for the columns", output)


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


class TestSessionAndSourceOutputs(unittest.TestCase):
    def test_session_mapping_renders_defaults(self) -> None:
        output = SessionMappingOutput().render(_sample_result())
        self.assertIn("# Session Mapping Proposal", output)
        self.assertIn("Parsed Item|Target Item", output)
        self.assertIn("|Details|Details|", output)
        self.assertIn("||Description|", output)

    def test_source_review_renders_entities(self) -> None:
        output = SourceReviewOutput().render(_sample_result())
        self.assertIn("# Source Review", output)
        self.assertIn("## Customer", output)
        self.assertIn("- Parsed columns: 2", output)
        self.assertIn("  - customer id", output)
        self.assertIn("## Open Questions", output)
        self.assertIn("- Any global concern?", output)


if __name__ == "__main__":
    unittest.main()
