import tempfile
import unittest
from pathlib import Path

from mc_artifact_parser import ArtifactParser, SchemaWorkbench
from mc_artifact_parser.adapters.image import ImageAdapter


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


if __name__ == "__main__":
    unittest.main()