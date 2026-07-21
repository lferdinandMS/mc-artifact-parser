from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re

from mc_artifact_parser.workbench import SchemaWorkbench
from mc_artifact_parser.outputs.data_dictionary import DataDictionaryOutput


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass
class WorkflowState:
    source_paths: list[str] = field(default_factory=list)
    source_review_done: bool = False
    mapping_proposed: bool = False
    mapping_approved: bool = False
    drafts_done: bool = False
    finalized: bool = False
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_paths": self.source_paths,
            "source_review_done": self.source_review_done,
            "mapping_proposed": self.mapping_proposed,
            "mapping_approved": self.mapping_approved,
            "drafts_done": self.drafts_done,
            "finalized": self.finalized,
            "updated_at": self.updated_at,
        }


class SchemaWorkflowAgent:
    """Orchestrate source review, mapping, drafts, and final outputs."""

    def __init__(self, workbench: SchemaWorkbench | None = None, output_root: str | Path = "review-bundle") -> None:
        self.workbench = SchemaWorkbench() if workbench is None else workbench
        self.output_root = Path(output_root)
        self.session_dir = self.output_root / "session"
        self.mappings_dir = self.output_root / "mappings"
        self.drafts_dir = self.output_root / "drafts"
        self.final_dir = self.output_root / "final"
        self.state_path = self.session_dir / "session_state.json"
        self.mapping_contract_path = self.session_dir / "mapping_contract.json"
        self._sources_hydrated = False

        for directory in [self.output_root, self.session_dir, self.mappings_dir, self.drafts_dir, self.final_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def review_sources(self, source_paths: list[str]) -> Path:
        self.workbench.add_many(source_paths)

        report_path = self.session_dir / "source-review.md"
        report_path.write_text(self.workbench.build_source_review_report() + "\n", encoding="utf-8")

        state = self._load_state()
        state.source_paths = list(dict.fromkeys(state.source_paths + source_paths))
        state.source_review_done = True
        state.updated_at = _utc_now_iso()
        self._save_state(state)
        self._sources_hydrated = True
        return report_path

    def propose_mapping(self) -> Path:
        state = self._load_state()
        if not state.source_review_done:
            raise RuntimeError("Source review must be completed before proposing a mapping.")
        self._hydrate_sources_from_state(state)

        mapping_path = self.session_dir / "session_mapping.md"
        mapping_path.write_text(self.workbench.build_session_mapping_proposal() + "\n", encoding="utf-8")

        state.mapping_proposed = True
        state.updated_at = _utc_now_iso()
        self._save_state(state)
        return mapping_path

    def approve_mapping(self) -> None:
        state = self._load_state()
        if not state.mapping_proposed:
            raise RuntimeError("Mapping must be proposed before approval.")

        state.mapping_approved = True
        state.updated_at = _utc_now_iso()
        self._save_state(state)

    def draft_outputs(self) -> dict[str, Path]:
        state = self._load_state()
        if not state.mapping_approved:
            raise RuntimeError("Mapping must be approved before drafting outputs.")
        self._hydrate_sources_from_state(state)

        self._clear_markdown_files(self.drafts_dir)
        self._clear_markdown_files(self.mappings_dir)

        table_docs = self.workbench.build_table_schema_markdowns()
        mapping_docs = self.workbench.build_mapping_markdowns()

        for filename, content in table_docs.items():
            (self.drafts_dir / filename).write_text(content + "\n", encoding="utf-8")

        for filename, content in mapping_docs.items():
            (self.mappings_dir / filename).write_text(content + "\n", encoding="utf-8")

        data_dictionary_path = self.drafts_dir / "data-dictionary.md"
        data_dictionary_path.write_text(self.workbench.build_data_dictionary() + "\n", encoding="utf-8")

        state.drafts_done = True
        state.updated_at = _utc_now_iso()
        self._save_state(state)

        return {
            "drafts_dir": self.drafts_dir,
            "mappings_dir": self.mappings_dir,
            "data_dictionary": data_dictionary_path,
        }

    def finalize_outputs(self) -> dict[str, Path]:
        state = self._load_state()
        if not state.drafts_done:
            raise RuntimeError("Draft outputs must be generated before finalization.")
        self._hydrate_sources_from_state(state)

        self._clear_markdown_files(self.final_dir)

        data_dictionary_path = self.final_dir / "data-dictionary.md"
        erd_path = self.final_dir / "erd.mmd"

        data_dictionary_path.write_text(self.workbench.build_data_dictionary() + "\n", encoding="utf-8")
        erd_path.write_text(self.workbench.build_erd() + "\n", encoding="utf-8")

        state.finalized = True
        state.updated_at = _utc_now_iso()
        self._save_state(state)

        return {"data_dictionary": data_dictionary_path, "erd": erd_path}

    def extract_with_mapping(self) -> dict[str, Path]:
        state = self._load_state()
        if not state.mapping_approved:
            raise RuntimeError("Mapping must be approved before extraction.")

        self._hydrate_sources_from_state(state)

        mapping_contract = self._load_mapping_contract()
        self.mapping_contract_path.write_text(json.dumps(mapping_contract, indent=2) + "\n", encoding="utf-8")

        self._clear_markdown_files(self.final_dir)

        data_dictionary_path = self.final_dir / "data-dictionary.md"
        erd_path = self.final_dir / "erd.mmd"

        data_dictionary = DataDictionaryOutput(header_mapping=mapping_contract).render(self.workbench.result)
        data_dictionary_path.write_text(data_dictionary + "\n", encoding="utf-8")
        erd_path.write_text(self.workbench.build_erd() + "\n", encoding="utf-8")

        state.finalized = True
        state.updated_at = _utc_now_iso()
        self._save_state(state)

        return {
            "data_dictionary": data_dictionary_path,
            "erd": erd_path,
            "mapping_contract": self.mapping_contract_path,
        }

    def _load_state(self) -> WorkflowState:
        if not self.state_path.exists():
            return WorkflowState()

        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        return WorkflowState(
            source_paths=list(payload.get("source_paths", [])),
            source_review_done=bool(payload.get("source_review_done", False)),
            mapping_proposed=bool(payload.get("mapping_proposed", False)),
            mapping_approved=bool(payload.get("mapping_approved", False)),
            drafts_done=bool(payload.get("drafts_done", False)),
            finalized=bool(payload.get("finalized", False)),
            updated_at=str(payload.get("updated_at", _utc_now_iso())),
        )

    def _save_state(self, state: WorkflowState) -> None:
        self.state_path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")

    def _clear_markdown_files(self, directory: Path) -> None:
        for path in directory.glob("*.md"):
            path.unlink(missing_ok=True)

    def _hydrate_sources_from_state(self, state: WorkflowState) -> None:
        if self._sources_hydrated:
            return

        if not state.source_paths:
            raise RuntimeError("No source paths were recorded. Run source review or /mapping first.")

        self.workbench.add_many(state.source_paths)
        self._sources_hydrated = True

    def _load_mapping_contract(self) -> dict[str, str]:
        mapping_files = sorted(self.mappings_dir.glob("*.md"))
        if not mapping_files:
            raise RuntimeError("No mapping files found. Run /mapping first and finalize mapping files before extraction.")

        contract: dict[str, str] = {}
        for mapping_file in mapping_files:
            for parsed_item, target_item in self._parse_mapping_file(mapping_file):
                if parsed_item:
                    contract[parsed_item] = target_item

        defaults = {
            "Column": "Column",
            "Type": "Type",
            "Nullable": "Nullable",
            "Primary Key": "Primary Key",
            "Foreign Key": "Foreign Key",
            "Details": "Details",
            "Description": "Description",
        }
        for key, default_value in defaults.items():
            contract.setdefault(key, default_value)

        return contract

    def _parse_mapping_file(self, path: Path) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        in_mapping_section = False

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.lower() == "## mapping":
                in_mapping_section = True
                continue

            if not in_mapping_section:
                continue

            if line.startswith("## "):
                break

            if not line or "|" not in line:
                continue

            lowered = line.lower()
            if lowered == "parsed item|target item":
                continue

            if re.fullmatch(r"\|?\s*[-:]+\s*\|\s*[-:]+\s*\|?", line):
                continue

            parsed_row = [cell.strip() for cell in line.strip("|").split("|")]
            if len(parsed_row) < 2:
                continue

            parsed_item = parsed_row[0]
            target_item = parsed_row[1]
            if parsed_item or target_item:
                rows.append((parsed_item, target_item))

        return rows