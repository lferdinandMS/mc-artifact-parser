from __future__ import annotations

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from docx_schema.cli import main
from docx_schema.mapping import (
    build_source_tables_from_docx,
    group_column_sets,
    render_mapping_markdown,
)
from docx_schema.models import TARGET_COLUMNS, SourceTable

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _p(text: str, style: str | None = None) -> str:
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{style_xml}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _cell(text: str) -> str:
    return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"


def _row(cells: list[str]) -> str:
    return "<w:tr>" + "".join(_cell(c) for c in cells) + "</w:tr>"


def _table(rows: list[list[str]]) -> str:
    return "<w:tbl>" + "".join(_row(r) for r in rows) + "</w:tbl>"


def _make_docx(path: Path, body: str) -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


class BuildSourceTablesTests(unittest.TestCase):
    def test_headers_and_rows_captured(self) -> None:
        with TemporaryDirectory() as tmp:
            docx = Path(tmp) / "tables.docx"
            body = _p("Table: Customer", style="Heading1") + _table(
                [
                    ["Field", "Type", "Required", "Purpose"],
                    ["customer_id", "INT", "Yes", "Unique id"],
                    ["name", "STRING", "No", "Full name"],
                ]
            )
            _make_docx(docx, body)

            tables = build_source_tables_from_docx(str(docx))

        self.assertEqual(len(tables), 1)
        table = tables[0]
        self.assertEqual(table.name, "Customer")
        self.assertEqual(table.headers, ["Field", "Type", "Required", "Purpose"])
        self.assertEqual(table.rows[0], ["customer_id", "INT", "Yes", "Unique id"])

    def test_fallback_name_when_no_heading(self) -> None:
        with TemporaryDirectory() as tmp:
            docx = Path(tmp) / "tables.docx"
            body = _table([["Field", "Type"], ["a", "INT"]])
            _make_docx(docx, body)

            tables = build_source_tables_from_docx(str(docx))

        self.assertEqual(tables[0].name, "Table1")


class CrosswalkTests(unittest.TestCase):
    def test_proposes_target_mapping(self) -> None:
        table = SourceTable(
            name="Customer",
            headers=["Field", "Type", "Required", "Purpose"],
            rows=[["a", "INT", "Yes", "note"]],
        )
        column_sets = group_column_sets([table])
        self.assertEqual(len(column_sets), 1)
        pairs = {target: extracted for extracted, target in column_sets[0].pairs}
        self.assertEqual(pairs["Column"], "Field")
        self.assertEqual(pairs["DataType"], "Type")
        self.assertEqual(pairs["Nullable(Y/N)"], "Required")
        self.assertEqual(pairs["Description"], "Purpose")
        # Targets with no match stay empty.
        self.assertEqual(pairs["Primary Key (Y/N)"], "")

    def test_unmatched_headers_listed_with_empty_target(self) -> None:
        table = SourceTable(
            name="Meta",
            headers=["Domain", "Primary Docs Referenced", "Key Objects/Endpoints"],
            rows=[],
        )
        column_sets = group_column_sets([table])
        pairs = column_sets[0].pairs
        # Unmatched extracted columns come first with empty target.
        self.assertEqual(pairs[0], ("Domain", ""))
        self.assertEqual(pairs[1], ("Primary Docs Referenced", ""))
        self.assertEqual(pairs[2], ("Key Objects/Endpoints", ""))
        # Followed by every target column with an empty extracted side.
        target_rows = pairs[3:]
        self.assertEqual([t for _e, t in target_rows], TARGET_COLUMNS)
        self.assertTrue(all(e == "" for e, _t in target_rows))

    def test_render_crosswalk_shape(self) -> None:
        table = SourceTable(
            name="Customer",
            headers=["Field", "Type", "Required", "Purpose"],
            rows=[],
        )
        column_sets = group_column_sets([table])
        md = render_mapping_markdown(column_sets, source="tables.docx")
        self.assertIn("|Extracted Column|Target Column|", md)
        self.assertIn("|Field|Column|", md)
        self.assertIn("|Type|DataType|", md)
        self.assertIn("|Required|Nullable(Y/N)|", md)
        self.assertIn("|Purpose|Description|", md)
        self.assertIn("||Primary Key (Y/N)|", md)

    def test_identical_headers_group_together(self) -> None:
        headers = ["Field", "Type"]
        tables = [
            SourceTable(name="A", headers=list(headers), rows=[]),
            SourceTable(name="B", headers=list(headers), rows=[]),
        ]
        column_sets = group_column_sets(tables)
        self.assertEqual(len(column_sets), 1)
        self.assertEqual(column_sets[0].table_names, ["A", "B"])


class CliTests(unittest.TestCase):
    def test_propose_mapping_cli(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "tables.docx"
            body = _p("Table: Customer", style="Heading1") + _table(
                [
                    ["Field", "Type", "Required", "Purpose"],
                    ["customer_id", "INT", "No", "Unique id"],
                ]
            )
            _make_docx(docx, body)

            mapping_out = tmp_path / "mapping.md"
            rc = main(["/propose-mapping", f"@{docx}", "--out", str(mapping_out)])
            self.assertEqual(rc, 0)
            self.assertTrue(mapping_out.is_file())

            text = mapping_out.read_text(encoding="utf-8")
            self.assertIn("## Column Set 1", text)
            self.assertIn("|Field|Column|", text)
            self.assertIn("|Purpose|Description|", text)


class SecurityTests(unittest.TestCase):
    def test_rejects_doctype(self) -> None:
        with TemporaryDirectory() as tmp:
            docx = Path(tmp) / "evil.docx"
            with zipfile.ZipFile(docx, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<?xml version="1.0"?><!DOCTYPE foo><w:document/>',
                )
            with self.assertRaises(ValueError):
                build_source_tables_from_docx(str(docx))


if __name__ == "__main__":
    unittest.main()
