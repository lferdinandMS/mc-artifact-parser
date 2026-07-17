import tempfile
import unittest
from pathlib import Path

from mc_artifact_parser import ArtifactParser, SchemaWorkbench
from mc_artifact_parser.adapters.image import ImageAdapter
from mc_artifact_parser.models import ColumnSchema


class TestSchemaWorkbench(unittest.TestCase):
    def test_accumulates_multiple_inputs_and_generates_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            customer_path = Path(td) / "customer.png"
            order_path = Path(td) / "order.png"
            customer_path.write_bytes(b"fake image bytes")
            order_path.write_bytes(b"fake image bytes")

            parser = ArtifactParser(
                adapters=[
                    ImageAdapter(
                        text_extractor=lambda path: {
                            str(customer_path): """
## Customer
- customer_id (int) pk not null
- email (varchar) nullable
Related Entities: Order
""".strip(),
                            str(order_path): """
## Order
- order_id (int) pk not null
- customer_id (int) references Customer.id
""".strip(),
                        }[path]
                    )
                ]
            )

            workbench = SchemaWorkbench(parser=parser)
            workbench.add(str(customer_path))
            workbench.add(str(order_path))

        self.assertEqual([entity.name for entity in workbench.result.entities], ["Customer", "Order"])
        table_docs = workbench.build_table_schema_markdowns()
        self.assertIn("customer.md", table_docs)
        self.assertIn("order.md", table_docs)
        self.assertIn("# Customer", table_docs["customer.md"])
        self.assertIn("## Columns", table_docs["customer.md"])
        self.assertEqual(workbench.completeness_issues, [])
        self.assertIn("## Customer", workbench.build_data_dictionary())
        self.assertIn("erDiagram", workbench.build_erd())

    def test_generates_questions_for_missing_completeness_signals(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "invoice.png"
            path.write_bytes(b"fake image bytes")

            parser = ArtifactParser(
                adapters=[
                    ImageAdapter(
                        text_extractor=lambda _: """
## Invoice
- invoice_id
- customer_id references Customer.id
""".strip()
                    )
                ]
            )

            workbench = SchemaWorkbench(parser=parser)
            workbench.add(str(path))

        self.assertTrue(any("primary key" in issue.message.lower() for issue in workbench.completeness_issues))
        self.assertIn("What is the primary key for Invoice?", workbench.generated_open_questions)
        self.assertIn("Should Invoice reference Customer?", workbench.generated_open_questions)

    def test_human_review_can_replace_misparsed_columns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "invoice.png"
            path.write_bytes(b"fake image bytes")

            parser = ArtifactParser(
                adapters=[
                    ImageAdapter(
                        text_extractor=lambda _: """
## Invoice / AR (Before)
- Customer ID
- Invoice Amount
- Due Date
- Payment History
""".strip()
                    )
                ]
            )

            workbench = SchemaWorkbench(parser=parser)
            workbench.add(str(path))

            assessments = workbench.assess_columns()
            self.assertTrue(any(item.status != "approved" for item in assessments))

            workbench.review_entity_columns(
                "Invoice / AR (Before)",
                [
                    ColumnSchema(name="customer_id", data_type="int", nullable=False),
                    ColumnSchema(name="invoice_amount", data_type="decimal", nullable=False),
                    ColumnSchema(name="due_date", data_type="date", nullable=True),
                    ColumnSchema(name="payment_history", data_type="text", nullable=True),
                ],
            )

        reviewed = workbench.result.entities[0]
        self.assertEqual([column.name for column in reviewed.columns], ["customer_id", "invoice_amount", "due_date", "payment_history"])
        self.assertEqual([column.data_type for column in reviewed.columns], ["int", "decimal", "date", "text"])
        table_docs = workbench.build_table_schema_markdowns()
        self.assertIn("invoice_ar_before.md", table_docs)
        self.assertIn("# Invoice / AR (Before)", table_docs["invoice_ar_before.md"])
        self.assertIn("## Invoice / AR (Before)", workbench.build_data_dictionary())
        self.assertIn("erDiagram", workbench.build_erd())


if __name__ == "__main__":
    unittest.main()