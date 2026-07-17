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
from docx_schema.models import TARGET_COLUMNS, ColumnSet, SourceTable
from docx_schema.schema import (
    extract_column_set,
    parse_mapping_markdown,
    render_extract_markdown,
)

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
    def test_auto_matches_synonyms(self) -> None:
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

    def test_identical_headers_group_together(self) -> None:
        headers = ["Field", "Type"]
        tables = [
            SourceTable(name="A", headers=list(headers), rows=[]),
            SourceTable(name="B", headers=list(headers), rows=[]),
        ]
        column_sets = group_column_sets(tables)
        self.assertEqual(len(column_sets), 1)
        self.assertEqual(column_sets[0].table_names, ["A", "B"])


class ParseMappingTests(unittest.TestCase):
    def test_parses_pairs_skipping_header_and_divider(self) -> None:
        mapping_md = (
            "## Column Set 1\n\n"
            "- Tables: Customer\n\n"
            "|Extracted Column|Target Column|\n"
            "|---------------|-------------|\n"
            "|Field|Column|\n"
            "|Type|DataType|\n"
            "||Description|\n"
        )
        column_sets = parse_mapping_markdown(mapping_md)
        self.assertEqual(len(column_sets), 1)
        cs = column_sets[0]
        self.assertEqual(cs.table_names, ["Customer"])
        self.assertIn(("Field", "Column"), cs.pairs)
        self.assertIn(("Type", "DataType"), cs.pairs)
        self.assertEqual(cs.target_to_extracted(), {"Column": "Field", "DataType": "Type"})


class ExtractTests(unittest.TestCase):
    def test_extract_pulls_mapped_values(self) -> None:
        source = SourceTable(
            name="Customer",
            headers=["Field", "Type", "Required", "Purpose"],
            rows=[
                ["customer_id", "INT", "No", "Unique id"],
                ["name", "STRING", "Yes", "Full name"],
            ],
        )
        column_set = ColumnSet(
            table_names=["Customer"],
            pairs=[
                ("Field", "Column"),
                ("Type", "DataType"),
                ("Required", "Nullable(Y/N)"),
                ("Purpose", "Description"),
            ],
        )
        extracted = extract_column_set(column_set, [source])
        self.assertEqual(len(extracted), 1)
        name, rows = extracted[0]
        self.assertEqual(name, "Customer")
        column_index = TARGET_COLUMNS.index("Column")
        datatype_index = TARGET_COLUMNS.index("DataType")
        desc_index = TARGET_COLUMNS.index("Description")
        self.assertEqual(rows[0][column_index], "customer_id")
        self.assertEqual(rows[0][datatype_index], "INT")
        self.assertEqual(rows[0][desc_index], "Unique id")
        # Unmapped target columns stay empty.
        pk_index = TARGET_COLUMNS.index("Primary Key (Y/N)")
        self.assertEqual(rows[0][pk_index], "")

    def test_render_extract_markdown(self) -> None:
        source = SourceTable(
            name="Customer",
            headers=["Field", "Type"],
            rows=[["customer_id", "INT"]],
        )
        column_set = ColumnSet(
            table_names=["Customer"],
            pairs=[("Field", "Column"), ("Type", "DataType")],
        )
        md = render_extract_markdown(column_set, [source], index=1)
        self.assertIn("# Column Set 1", md)
        self.assertIn("## Customer", md)
        self.assertIn("| " + " | ".join(TARGET_COLUMNS) + " |", md)
        self.assertIn("customer_id", md)


class CliTests(unittest.TestCase):
    def test_end_to_end_cli(self) -> None:
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

            schema_dir = tmp_path / "schema"
            rc = main(
                [
                    "create-schema",
                    str(mapping_out),
                    "--docx",
                    str(docx),
                    "--out-dir",
                    str(schema_dir),
                ]
            )
            self.assertEqual(rc, 0)
            extract = schema_dir / "column-set-1.md"
            self.assertTrue(extract.is_file())
            self.assertIn("customer_id", extract.read_text(encoding="utf-8"))

    def test_create_schema_resolves_source_from_mapping(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "tables.docx"
            body = _p("Table: Customer", style="Heading1") + _table(
                [["Field", "Type"], ["customer_id", "INT"]]
            )
            _make_docx(docx, body)

            mapping_out = tmp_path / "mapping.md"
            self.assertEqual(
                main(["propose-mapping", str(docx), "--out", str(mapping_out)]), 0
            )

            schema_dir = tmp_path / "schema"
            # No --docx: the source is read from the mapping's "Source" line.
            rc = main(["create-schema", str(mapping_out), "--out-dir", str(schema_dir)])
            self.assertEqual(rc, 0)
            self.assertTrue((schema_dir / "column-set-1.md").is_file())


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
