import tempfile
import unittest
from pathlib import Path

from mc_artifact_parser import ArtifactParser
from mc_artifact_parser.adapters.markdown import MarkdownAdapter


def _write_md(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class TestMarkdownAdapter(unittest.TestCase):
    def test_parses_h2_headings_as_entities(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "schema.md"
            _write_md(
                md_path,
                """\
# Schema Design

## Customer
- customer_id (int) not null primary key
- email (varchar) nullable
- account_manager_id (int) references Employee.id
Related Entities: Order, Invoice
Open Question: Should guest customers be supported?

## Order
- order_id: int pk not null
- customer_id: int not null references Customer.id
Any discounts?
""",
            )
            result = ArtifactParser().parse(str(md_path))

        self.assertEqual(result.artifact_type, "markdown")
        self.assertEqual(len(result.entities), 2)

        customer = result.entities[0]
        self.assertEqual(customer.name, "Customer")
        self.assertIn("Customer", customer.implied_tables)

        self.assertEqual(customer.columns[0].name, "customer_id")
        self.assertEqual(customer.columns[0].data_type, "int")
        self.assertIs(customer.columns[0].nullable, False)
        self.assertTrue(customer.columns[0].primary_key)

        self.assertIs(customer.columns[1].nullable, True)
        self.assertIn("Employee", customer.related_entities)
        self.assertIn("Order", customer.related_entities)
        self.assertIn("Invoice", customer.related_entities)
        self.assertEqual(customer.open_questions, ["Should guest customers be supported?"])

        order = result.entities[1]
        self.assertEqual(order.name, "Order")
        self.assertTrue(order.columns[0].primary_key)
        self.assertIn("Customer", order.related_entities)
        self.assertEqual(order.open_questions, ["Any discounts?"])

    def test_parses_explicit_entity_prefix_in_heading(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "schema.md"
            _write_md(
                md_path,
                """\
## Entity: Product
- product_id (int) pk not null
""",
            )
            result = ArtifactParser().parse(str(md_path))

        self.assertEqual(result.entities[0].name, "Product")

    def test_h1_heading_not_treated_as_entity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "schema.md"
            _write_md(
                md_path,
                """\
# Document Title
## RealEntity
- id (int) pk not null
""",
            )
            result = ArtifactParser().parse(str(md_path))

        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.entities[0].name, "RealEntity")

    def test_global_open_question_before_first_entity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "schema.md"
            _write_md(
                md_path,
                """\
Is this the final schema?

## Supplier
- id (int) pk not null
""",
            )
            result = ArtifactParser().parse(str(md_path))

        self.assertEqual(result.open_questions, ["Is this the final schema?"])
        self.assertEqual(result.entities[0].open_questions, [])

    def test_unsupported_extension_raises(self) -> None:
        with self.assertRaises(ValueError):
            ArtifactParser().parse("/tmp/not-supported.txt")

    def test_bold_related_entities_label(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "schema.md"
            _write_md(
                md_path,
                """\
## Invoice
- invoice_id (int) pk not null
**Related Entities**: Customer, Order
""",
            )
            result = ArtifactParser().parse(str(md_path))

        self.assertIn("Customer", result.entities[0].related_entities)
        self.assertIn("Order", result.entities[0].related_entities)

    def test_can_parse_returns_true_for_md(self) -> None:
        adapter = MarkdownAdapter()
        self.assertTrue(adapter.can_parse("schema.md"))
        self.assertTrue(adapter.can_parse("schema.MD"))
        self.assertFalse(adapter.can_parse("schema.docx"))

    def test_rejects_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "big.md"
            md_path.write_bytes(b"x" * (MarkdownAdapter._MAX_FILE_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "maximum supported size"):
                ArtifactParser().parse(str(md_path))


if __name__ == "__main__":
    unittest.main()
