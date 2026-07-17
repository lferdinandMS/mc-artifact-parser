"""Command-line interface for the minimal DOCX schema toolkit.

Usage examples::

    python -m docx_schema propose-mapping tables.docx
    python -m docx_schema /propose-mapping @tables.docx --out tables-mapping.md

Both slash-prefixed (``/propose-mapping``) and plain (``propose-mapping``)
command names are accepted, and file arguments may use a leading ``@``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .docx_reader import normalize_docx_path
from .mapping import (
    build_source_tables_from_docx,
    group_column_sets,
    write_mapping_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docx_schema",
        description="Extract table column sets from .docx into a reviewer-editable mapping.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser(
        "propose-mapping",
        help="Read a .docx and write a reviewer-editable proposed mapping markdown.",
    )
    propose.add_argument("docx", help="Path to the source .docx (a leading @ is allowed).")
    propose.add_argument("--out", help="Output mapping markdown path.", default=None)
    propose.set_defaults(func=_run_propose_mapping)

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
    print("A best-guess mapping was proposed; review and correct it in the mapping file.")
    return 0


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
