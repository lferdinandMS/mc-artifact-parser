import tempfile
import unittest
import zipfile
from pathlib import Path

from mc_artifact_parser import ArtifactParser


def _docx_xml(paragraphs: list[str]) -> str:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", _docx_xml(paragraphs))


class TestDocxAdapter(unittest.TestCase):
    def test_parses_entities_and_schema_signals(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "schema.docx"
            _write_docx(
                docx_path,
                [
                    "Entity: Customer",
                    "- customer_id (int) not null primary key",
                    "- email (varchar) nullable",
                    "- account_manager_id (int) references Employee.id",
                    "Related Entities: Order, Invoice",
                    "Open Question: Should guest customers be supported?",
                    "Entity: Order",
                    "- order_id: int pk not null",
                    "- customer_id: int not null references Customer.id",
                    "Any discounts?",
                ],
            )

            result = ArtifactParser().parse(str(docx_path))

        self.assertEqual(result.artifact_type, "docx")
        self.assertEqual(len(result.entities), 2)

        customer = result.entities[0]
        self.assertEqual(customer.name, "Customer")
        self.assertIn("Customer", customer.implied_tables)
        self.assertEqual(customer.columns[0].name, "customer_id")
        self.assertEqual(customer.columns[0].data_type, "int")
        self.assertFalse(customer.columns[0].nullable)
        self.assertTrue(customer.columns[0].primary_key)
        self.assertTrue(customer.columns[1].nullable)
        self.assertIn("Employee", customer.related_entities)
        self.assertIn("Order", customer.related_entities)
        self.assertIn("Invoice", customer.related_entities)
        self.assertEqual(customer.open_questions, ["Should guest customers be supported?"])

        order = result.entities[1]
        self.assertEqual(order.name, "Order")
        self.assertEqual(order.columns[0].name, "order_id")
        self.assertTrue(order.columns[0].primary_key)
        self.assertIn("Customer", order.related_entities)
        self.assertEqual(order.open_questions, ["Any discounts?"])

    def test_unsupported_extension_raises(self) -> None:
        with self.assertRaises(ValueError):
            ArtifactParser().parse("/tmp/not-supported.txt")


if __name__ == "__main__":
    unittest.main()
