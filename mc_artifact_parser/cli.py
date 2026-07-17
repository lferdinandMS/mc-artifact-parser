from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from mc_artifact_parser.agent_workflow import SchemaWorkflowAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mc_artifact_parser",
        description="Run staged schema workflow: source review, mapping, drafts, and final outputs.",
    )
    parser.add_argument(
        "workflow_command",
        nargs="?",
        choices=["/mapping", "/extraction", "/clean"],
        help="Slash workflow command. /mapping creates mapping artifacts. /extraction uses finalized mapping to generate outputs. /clean removes generated output folders.",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        help="Source artifact paths (.md, .docx, images). Required for source review stage.",
    )
    parser.add_argument(
        "--output-root",
        default="review-bundle",
        help="Workflow output root directory. Default: review-bundle",
    )

    parser.add_argument("--review-sources", action="store_true", help="Run source review stage.")
    parser.add_argument("--propose-mapping", action="store_true", help="Run session mapping proposal stage.")
    parser.add_argument("--approve-mapping", action="store_true", help="Approve mapping stage.")
    parser.add_argument("--draft-outputs", action="store_true", help="Run draft outputs stage.")
    parser.add_argument("--finalize", action="store_true", help="Run finalization stage.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.workflow_command is not None:
        selected = {
            "review_sources": False,
            "propose_mapping": False,
            "approve_mapping": False,
            "draft_outputs": False,
            "finalize": False,
        }
    else:
        selected = {
            "review_sources": args.review_sources,
            "propose_mapping": args.propose_mapping,
            "approve_mapping": args.approve_mapping,
            "draft_outputs": args.draft_outputs,
            "finalize": args.finalize,
        }

    # If no explicit stage flags are provided, run full workflow.
    if args.workflow_command is None and not any(selected.values()):
        selected = {
            "review_sources": True,
            "propose_mapping": True,
            "approve_mapping": True,
            "draft_outputs": True,
            "finalize": True,
        }

    if args.workflow_command is None and selected["review_sources"] and not args.sources:
        parser.error("--sources is required when --review-sources is selected.")

    agent = SchemaWorkflowAgent(output_root=args.output_root)

    try:
        if args.workflow_command == "/clean":
            removed = _clean_generated_outputs(args.output_root)
            if removed:
                for path in removed:
                    print(f"[clean] removed={path}")
            else:
                print("[clean] no generated output directories found")
            return 0

        if args.workflow_command == "/mapping":
            if not args.sources:
                parser.error("--sources is required when /mapping is selected.")

            report_path = agent.review_sources(args.sources)
            print(f"[review-sources] {report_path}")

            mapping_path = agent.propose_mapping()
            print(f"[propose-mapping] {mapping_path}")

            agent.approve_mapping()
            print("[approve-mapping] session mapping approved")

            outputs = agent.draft_outputs()
            print(f"[mapping] mappings={Path(outputs['mappings_dir'])}")
            print(f"[mapping] session={Path(mapping_path)}")
            return 0

        if args.workflow_command == "/extraction":
            outputs = agent.extract_with_mapping()
            print(f"[extraction] data-dictionary={Path(outputs['data_dictionary'])}")
            print(f"[extraction] erd={Path(outputs['erd'])}")
            print(f"[extraction] mapping-contract={Path(outputs['mapping_contract'])}")
            return 0

        if selected["review_sources"]:
            report_path = agent.review_sources(args.sources)
            print(f"[review-sources] {report_path}")

        if selected["propose_mapping"]:
            mapping_path = agent.propose_mapping()
            print(f"[propose-mapping] {mapping_path}")

        if selected["approve_mapping"]:
            agent.approve_mapping()
            print("[approve-mapping] session mapping approved")

        if selected["draft_outputs"]:
            outputs = agent.draft_outputs()
            print(f"[draft-outputs] drafts={Path(outputs['drafts_dir'])}")
            print(f"[draft-outputs] mappings={Path(outputs['mappings_dir'])}")
            print(f"[draft-outputs] data-dictionary={Path(outputs['data_dictionary'])}")

        if selected["finalize"]:
            outputs = agent.finalize_outputs()
            print(f"[finalize] data-dictionary={Path(outputs['data_dictionary'])}")
            print(f"[finalize] erd={Path(outputs['erd'])}")

    except RuntimeError as error:
        print(f"error: {error}")
        return 1

    return 0


def _clean_generated_outputs(output_root: str) -> list[Path]:
    cwd = Path.cwd()
    preserved = {".venv", "mc_artifact_parser", "tests", ".git"}
    generated_names = {
        "review-bundle",
        "slash-workflow-demo",
        Path(output_root).name,
    }

    removed: list[Path] = []
    for directory in cwd.iterdir():
        if not directory.is_dir() or directory.name in preserved:
            continue

        is_walkthrough = directory.name.startswith("walkthrough")
        if directory.name in generated_names or is_walkthrough:
            shutil.rmtree(directory, ignore_errors=False)
            removed.append(directory)

    return removed
if __name__ == "__main__":
    raise SystemExit(main())
