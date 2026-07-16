import tempfile
import unittest
import zipfile
from pathlib import Path

from mc_artifact_parser import ArtifactParser
from mc_artifact_parser.adapters.docx import DocxAdapter


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
                    "Any global concern?",
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
        self.assertEqual(result.open_questions, ["Any global concern?"])
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
        self.assertEqual(order.columns[0].name, "order_id")
        self.assertTrue(order.columns[0].primary_key)
        self.assertIn("Customer", order.related_entities)
        self.assertEqual(order.open_questions, ["Any discounts?"])

    def test_unsupported_extension_raises(self) -> None:
        with self.assertRaises(ValueError):
            unsupported = Path(tempfile.gettempdir()) / "not-supported.txt"
            ArtifactParser().parse(str(unsupported))

    def test_entity_question_captured_without_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "schema.docx"
            _write_docx(
                docx_path,
                [
                    "Entity: Supplier",
                    "Do we support international suppliers?",
                ],
            )

            result = ArtifactParser().parse(str(docx_path))

        self.assertEqual(result.open_questions, [])
        self.assertEqual(result.entities[0].open_questions, ["Do we support international suppliers?"])

    def test_rejects_oversized_document_xml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "schema.docx"
            oversized_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body><w:p><w:r><w:t>{'x' * DocxAdapter._MAX_DOCUMENT_XML_BYTES}</w:t></w:r></w:p></w:body>"
                "</w:document>"
            )
            with zipfile.ZipFile(docx_path, "w") as zf:
                zf.writestr("word/document.xml", oversized_xml)

            with self.assertRaisesRegex(ValueError, "maximum supported size"):
                ArtifactParser().parse(str(docx_path))


if __name__ == "__main__":
    unittest.main()
