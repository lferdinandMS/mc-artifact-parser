"""Command-line interface for the minimal DOCX schema toolkit.

Usage examples::

    python -m docx_schema propose-mapping tables.docx
    python -m docx_schema /propose-mapping @tables.docx --out tables-mapping.md
    python -m docx_schema create-schema tables-mapping.md --out-dir schema

Both slash-prefixed (``/propose-mapping``) and plain (``propose-mapping``)
command names are accepted, and file arguments may use a leading ``@``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .docx_reader import normalize_docx_path
from .mapping import (
    build_source_tables_from_docx,
    group_column_sets,
    write_mapping_markdown,
)
from .schema import parse_mapping_markdown, write_extract_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docx_schema",
        description="Turn .docx documents into reviewed table schema markdown.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser(
        "propose-mapping",
        help="Read a .docx and write a reviewer-editable proposed mapping markdown.",
    )
    propose.add_argument("docx", help="Path to the source .docx (a leading @ is allowed).")
    propose.add_argument("--out", help="Output mapping markdown path.", default=None)
    propose.set_defaults(func=_run_propose_mapping)

    create = subparsers.add_parser(
        "create-schema",
        help="Read a mapping markdown + source .docx and write one extract per column set.",
    )
    create.add_argument("mapping", help="Path to the mapping markdown (a leading @ is allowed).")
    create.add_argument("--docx", help="Source .docx (defaults to the mapping's Source).", default=None)
    create.add_argument("--out-dir", help="Directory for schema files.", default="outputs/schemas")
    create.set_defaults(func=_run_create_schema)

    return parser


def _run_propose_mapping(args: argparse.Namespace) -> int:
    docx_path = normalize_docx_path(args.docx)
    if not docx_path.is_file():
        print(f"error: docx not found: {docx_path}", file=sys.stderr)
        return 2

    tables = build_source_tables_from_docx(str(docx_path))
    column_sets = group_column_sets(tables)
    out_path = Path(args.out) if args.out else Path.cwd() / "outputs" / "mappings" / f"{docx_path.stem}-mapping.md"
    write_mapping_markdown(column_sets, source=docx_path.name, out_path=out_path)

    print(f"Wrote proposed mapping: {out_path}")
    print(f"Detected {len(tables)} table(s) in {len(column_sets)} column set(s).")
    print("Review and edit the mapping, then run: create-schema", out_path.name)
    return 0


def _run_create_schema(args: argparse.Namespace) -> int:
    mapping_path = normalize_docx_path(args.mapping)
    if not mapping_path.is_file():
        print(f"error: mapping markdown not found: {mapping_path}", file=sys.stderr)
        return 2

    mapping_text = mapping_path.read_text(encoding="utf-8")
    column_sets = parse_mapping_markdown(mapping_text)
    if not column_sets:
        print("error: no column sets found in mapping markdown.", file=sys.stderr)
        return 1

    docx_path = _resolve_source_docx(args.docx, mapping_text, mapping_path)
    if docx_path is None:
        print(
            "error: could not locate the source .docx; pass --docx explicitly.",
            file=sys.stderr,
        )
        return 2

    source_tables = build_source_tables_from_docx(str(docx_path))
    written = write_extract_files(column_sets, source_tables, Path(args.out_dir))
    print(f"Wrote {len(written)} extract file(s) to {Path(args.out_dir)}:")
    for path in written:
        print(f"  - {path}")
    return 0


def _resolve_source_docx(
    docx_arg: str | None, mapping_text: str, mapping_path: Path
) -> Path | None:
    if docx_arg:
        candidate = normalize_docx_path(docx_arg)
        return candidate if candidate.is_file() else None

    match = re.search(r"^-\s*Source:\s*`([^`]+)`", mapping_text, re.MULTILINE)
    if not match:
        return None
    name = match.group(1).strip()
    for candidate in (mapping_path.parent / name, Path.cwd() / name, Path(name)):
        if candidate.is_file():
            return candidate
    return None


def _normalize_argv(argv: list[str]) -> list[str]:
    if argv and argv[0].startswith("/"):
        argv = [argv[0][1:], *argv[1:]]
    return argv


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = _normalize_argv(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
