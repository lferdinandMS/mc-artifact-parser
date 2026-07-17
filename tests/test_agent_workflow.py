import json
import tempfile
import unittest
from pathlib import Path

from mc_artifact_parser import ArtifactParser, SchemaWorkflowAgent
from mc_artifact_parser.adapters.image import ImageAdapter
from mc_artifact_parser.workbench import SchemaWorkbench


class TestSchemaWorkflowAgent(unittest.TestCase):
    def test_full_workflow_stages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            source_path = td_path / "source.png"
            source_path.write_bytes(b"fake image bytes")

            parser = ArtifactParser(
                adapters=[
                    ImageAdapter(
                        text_extractor=lambda _: """
## Invoice
- customer_id (int) references Customer.id
- due_date (date) nullable
""".strip()
                    )
                ]
            )

            workbench = SchemaWorkbench(parser=parser)
            agent = SchemaWorkflowAgent(workbench=workbench, output_root=td_path / "review-bundle")

            source_review = agent.review_sources([str(source_path)])
            self.assertTrue(source_review.exists())

            session_mapping = agent.propose_mapping()
            self.assertTrue(session_mapping.exists())

            agent.approve_mapping()

            drafts = agent.draft_outputs()
            self.assertTrue((drafts["drafts_dir"] / "invoice.md").exists())
            self.assertTrue((drafts["mappings_dir"] / "invoice.md").exists())
            self.assertTrue(drafts["data_dictionary"].exists())

            final_outputs = agent.finalize_outputs()
            self.assertTrue(final_outputs["data_dictionary"].exists())
            self.assertTrue(final_outputs["erd"].exists())

            state_path = td_path / "review-bundle" / "session" / "session_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(state["source_review_done"])
            self.assertTrue(state["mapping_proposed"])
            self.assertTrue(state["mapping_approved"])
            self.assertTrue(state["drafts_done"])
            self.assertTrue(state["finalized"])

    def test_enforces_stage_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            agent = SchemaWorkflowAgent(output_root=Path(td) / "review-bundle")

            with self.assertRaises(RuntimeError):
                agent.propose_mapping()

            with self.assertRaises(RuntimeError):
                agent.draft_outputs()

            with self.assertRaises(RuntimeError):
                agent.finalize_outputs()

    def test_draft_outputs_clears_stale_markdown_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            source_path = td_path / "source.png"
            source_path.write_bytes(b"fake image bytes")

            parser = ArtifactParser(
                adapters=[
                    ImageAdapter(
                        text_extractor=lambda _: """
## Invoice
- invoice_id (int) pk not null
""".strip()
                    )
                ]
            )

            agent = SchemaWorkflowAgent(
                workbench=SchemaWorkbench(parser=parser),
                output_root=td_path / "review-bundle",
            )
            stale = td_path / "review-bundle" / "drafts" / "open_questions.md"
            stale.write_text("stale", encoding="utf-8")

            agent.review_sources([str(source_path)])
            agent.propose_mapping()
            agent.approve_mapping()
            drafts = agent.draft_outputs()

            self.assertFalse(stale.exists())
            self.assertTrue((drafts["drafts_dir"] / "invoice.md").exists())


if __name__ == "__main__":
    unittest.main()
