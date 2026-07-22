from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docx_schema.docx_reader import normalize_docx_path
from docx_schema.mapping import (
    parse_mapping_markdown,
    propose_mapping,
    render_mapping_markdown,
    render_relationships_markdown,
    write_schema_files,
)
from docx_schema.sources import read_relationships


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m docx_schema", description="Create mapping and schema markdown files from DOCX or SVG sources.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose-mapping", help="Create a self-contained mapping markdown from a DOCX or SVG file.")
    propose.add_argument("source", help="Path to source .docx or .svg/.xml")
    propose.add_argument("--out", default="./mapping.md", help="Output mapping markdown path")
    propose.set_defaults(handler=_run_propose_mapping)

    create = subparsers.add_parser("create-schema", help="Create per-table schema files from a source DOCX/SVG plus reviewed mapping markdown.")
    create.add_argument("source", help="Path to source .docx or .svg/.xml (leading @ allowed)")
    create.add_argument("mapping", help="Path to mapping markdown (leading @ allowed)")
    create.add_argument("--out-dir", default="./schema", help="Output directory for schema markdown files")
    create.set_defaults(handler=_run_create_schema)

    relationships = subparsers.add_parser("extract-relationships", help="Extract table relationships (SVG arrows) to a markdown + Mermaid ERD.")
    relationships.add_argument("source", help="Path to source .svg/.xml (leading @ allowed)")
    relationships.add_argument("--out", default="./relationships.md", help="Output relationships markdown path")
    relationships.set_defaults(handler=_run_extract_relationships)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = _normalize_argv(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except ValueError as error:
        message = str(error).strip()
        if message.startswith("error:"):
            print(message)
        else:
            print(f"error: {message}")
        return 1


def _run_propose_mapping(args: argparse.Namespace) -> int:
    column_sets = propose_mapping(str(normalize_docx_path(args.source)))
    text = render_mapping_markdown(column_sets)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    table_count = sum(len(column_set.table_names) for column_set in column_sets)
    print(f"Wrote mapping for {table_count} table(s) across {len(column_sets)} column set(s)")
    print(out_path)
    return 0


def _run_create_schema(args: argparse.Namespace) -> int:
    source_path = normalize_docx_path(args.source)
    mapping_path = args.mapping[1:] if args.mapping.startswith("@") else args.mapping
    text = Path(mapping_path).read_text(encoding="utf-8")
    column_sets = parse_mapping_markdown(text)
    written = write_schema_files(source_path, column_sets, args.out_dir)

    print(f"Wrote {len(written)} schema file(s) from {len(column_sets)} column set(s)")
    for path in written:
        print(path)
    return 0


def _run_extract_relationships(args: argparse.Namespace) -> int:
    source_path = normalize_docx_path(args.source)
    relationships = read_relationships(str(source_path))
    text = render_relationships_markdown(relationships)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    print(f"Wrote {len(relationships)} relationship(s)")
    print(out_path)
    return 0


def _normalize_argv(argv: list[str]) -> list[str]:
    if argv and argv[0].startswith("/"):
        return [argv[0][1:], *argv[1:]]
    return argv


if __name__ == "__main__":
    raise SystemExit(main())
