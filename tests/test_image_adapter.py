import tempfile
import unittest
from pathlib import Path

from mc_artifact_parser import ArtifactParser
from mc_artifact_parser.adapters.image import ImageAdapter


class TestImageAdapter(unittest.TestCase):
    def test_can_parse_common_image_extensions(self) -> None:
        adapter = ImageAdapter(text_extractor=lambda _: "")
        self.assertTrue(adapter.can_parse("schema.png"))
        self.assertTrue(adapter.can_parse("schema.JPG"))
        self.assertFalse(adapter.can_parse("schema.md"))

    def test_parses_extracted_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "schema.png"
            image_path.write_bytes(b"fake image bytes")

            adapter = ImageAdapter(
                text_extractor=lambda _: """
## Customer
- customer_id (int) pk not null
- email (varchar) nullable
Related Entities: Order
""".strip()
            )
            result = adapter.parse(str(image_path))

        self.assertEqual(result.artifact_type, "image")
        self.assertEqual([entity.name for entity in result.entities], ["Customer"])
        self.assertIn("Order", result.entities[0].related_entities)

    def test_parser_includes_image_adapter_by_default(self) -> None:
        adapter_names = [type(adapter).__name__ for adapter in ArtifactParser()._adapters]
        self.assertIn("ImageAdapter", adapter_names)

    def test_fallback_infers_entity_from_ocr_without_headers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            image_path = Path(td) / "confidence-framework.png"
            image_path.write_bytes(b"fake image bytes")

            adapter = ImageAdapter(
                text_extractor=lambda _: """
Balance Visibility Can we see current cash?
Inflow Visibility Can we see money coming in?
Outflow Visibility Can we see money going out?
""".strip()
            )
            result = adapter.parse(str(image_path))

        self.assertEqual(result.artifact_type, "image")
        self.assertEqual([entity.name for entity in result.entities], ["Confidence Framework"])
        self.assertGreaterEqual(len(result.entities[0].columns), 3)
        self.assertTrue(any("inferred" in question.lower() for question in result.open_questions))


if __name__ == "__main__":
    unittest.main()