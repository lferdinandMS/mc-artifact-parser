import tempfile
import unittest
import os
from pathlib import Path

from mc_artifact_parser.cli import main


class TestCli(unittest.TestCase):
    def test_runs_full_workflow_from_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            source = td_path / "schema.md"
            source.write_text(
                """
## Invoice
- invoice_id (int) pk not null
- customer_id (int) references Customer.id
""".strip() + "\n",
                encoding="utf-8",
            )

            output_root = td_path / "review-bundle"
            exit_code = main(["--sources", str(source), "--output-root", str(output_root)])
            self.assertEqual(exit_code, 0)

            self.assertTrue((output_root / "session" / "source-review.md").exists())
            self.assertTrue((output_root / "session" / "session_mapping.md").exists())
            self.assertTrue((output_root / "mappings" / "invoice.md").exists())
            self.assertTrue((output_root / "drafts" / "invoice.md").exists())
            self.assertTrue((output_root / "final" / "data-dictionary.md").exists())
            self.assertTrue((output_root / "final" / "erd.mmd").exists())

    def test_requires_sources_when_review_stage_selected(self) -> None:
        with self.assertRaises(SystemExit):
            main(["--review-sources"])

    def test_slash_mapping_then_extraction_uses_mapping_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            source = td_path / "schema.md"
            source.write_text(
                """
## Invoice
- invoice_id (int) pk not null
- customer_id (int) references Customer.id
""".strip()
                + "\n",
                encoding="utf-8",
            )

            output_root = td_path / "review-bundle"

            mapping_exit_code = main(["/mapping", "--sources", str(source), "--output-root", str(output_root)])
            self.assertEqual(mapping_exit_code, 0)

            mapping_file = output_root / "mappings" / "invoice.md"
            mapping_content = mapping_file.read_text(encoding="utf-8")
            mapping_file.write_text(mapping_content.replace("Column|Column", "Column|Field"), encoding="utf-8")

            extraction_exit_code = main(["/extraction", "--output-root", str(output_root)])
            self.assertEqual(extraction_exit_code, 0)

            data_dictionary = (output_root / "final" / "data-dictionary.md").read_text(encoding="utf-8")
            self.assertIn("| Field | Type | Nullable | Primary Key | Foreign Key | Details | Description |", data_dictionary)

            mapping_contract = (output_root / "session" / "mapping_contract.json").read_text(encoding="utf-8")
            self.assertIn('"Column": "Field"', mapping_contract)

    def test_slash_clean_removes_generated_output_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            (td_path / "review-bundle").mkdir()
            (td_path / "walkthrough-temp").mkdir()
            (td_path / "slash-workflow-demo").mkdir()
            (td_path / "keep-me").mkdir()

            original_cwd = Path.cwd()
            os.chdir(td_path)
            try:
                exit_code = main(["/clean"])
                self.assertEqual(exit_code, 0)
            finally:
                os.chdir(original_cwd)

            self.assertFalse((td_path / "review-bundle").exists())
            self.assertFalse((td_path / "walkthrough-temp").exists())
            self.assertFalse((td_path / "slash-workflow-demo").exists())
            self.assertTrue((td_path / "keep-me").exists())


if __name__ == "__main__":
    unittest.main()
