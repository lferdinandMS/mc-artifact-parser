import subprocess
import sys
import tempfile
import unittest
import zipfile
from html import escape as html_escape
from pathlib import Path

from schema_parser.cli import main
from schema_parser.mapping import (
    parse_mapping_markdown,
    project_table,
    propose_mapping,
    write_schema_files,
)
from schema_parser.models import Relationship, SourceTable, TARGET_COLUMNS
from schema_parser.render import render_mapping_markdown, render_relationships_markdown
from schema_parser.sources import read_relationships, read_tables
from schema_parser.sources.svg_relationships import extract_relationships
from schema_parser.sources.text_columns import parse_column_line


def _docx_xml(tables: list[tuple[str, list[str], list[list[str]]]]) -> str:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def paragraph(text: str) -> str:
        return f"<w:p><w:r><w:t>{html_escape(text)}</w:t></w:r></w:p>"

    def cell(text: str) -> str:
        return f"<w:tc><w:p><w:r><w:t>{html_escape(text)}</w:t></w:r></w:p></w:tc>"

    def row(values: list[str]) -> str:
        return "<w:tr>" + "".join(cell(value) for value in values) + "</w:tr>"

    body_parts: list[str] = []
    for table_name, headers, rows in tables:
        body_parts.append(paragraph(table_name))
        body_parts.append("<w:tbl>")
        body_parts.append(row(headers))
        for values in rows:
            body_parts.append(row(values))
        body_parts.append("</w:tbl>")

    return (
        f'<w:document xmlns:w="{ns}"><w:body>'
        + "".join(body_parts)
        + "</w:body></w:document>"
    )


def _write_docx(path: Path, tables: list[tuple[str, list[str], list[list[str]]]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", _docx_xml(tables))


class TestDocxSchema(unittest.TestCase):
    def test_render_crosswalk_shape_contains_embedded_wide_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "mapping.docx"
            _write_docx(
                docx_path,
                [
                    (
                        "Customer",
                        ["Name", "Data Type", "Nullable"],
                        [["customer_id", "int", "No"], ["email", "string", "Yes"]],
                    )
                ],
            )

            mapping = render_mapping_markdown(propose_mapping(str(docx_path)))

        self.assertIn("## Column Set 1", mapping)
        self.assertIn("| Extracted Column | Target Column |", mapping)
        self.assertIn("- Tables: Customer", mapping)
        self.assertNotIn("### Customer", mapping)
        self.assertNotIn("| " + " | ".join(TARGET_COLUMNS) + " |", mapping)

    def test_propose_mapping_makes_good_faith_header_matches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "mapping.docx"
            _write_docx(
                docx_path,
                [
                    (
                        "Customer Metadata",
                        ["Field", "Type", "Required", "Purpose"],
                        [["record_hash", "string", "No", "Unique hash" ]],
                    )
                ],
            )

            mapping = render_mapping_markdown(propose_mapping(str(docx_path)))

        self.assertIn("| Field | Column |", mapping)
        self.assertIn("| Type | Type |", mapping)
        self.assertIn("| Required | Nullable |", mapping)
        self.assertIn("| Purpose | Description |", mapping)
        self.assertIn("|  | Primary Key |", mapping)

    def test_direct_entrypoint_works_when_package_is_invoked_as_script(self) -> None:
        package_dir = Path(__file__).resolve().parent.parent / "schema_parser"
        result = subprocess.run(
            [sys.executable, str(package_dir / "__main__.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
            cwd=package_dir,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("propose-mapping", result.stdout)

    def test_project_table_places_values_using_crosswalk(self) -> None:
        table = SourceTable(
            name="Customer",
            headers=["Name", "Data Type", "Nullable"],
            rows=[["customer_id", "int", "No"]],
        )
        pairs = [("Name", "Column"), ("Data Type", "Type"), ("Nullable", "Nullable")]

        projected = project_table(table, pairs)

        self.assertEqual(projected.columns[0][0], "customer_id")
        self.assertEqual(projected.columns[0][1], "int")
        self.assertEqual(projected.columns[0][2], "No")
        self.assertEqual(len(projected.columns[0]), len(TARGET_COLUMNS))
        self.assertEqual(projected.columns[0][3], "")

    def test_round_trip_propose_parse_and_write_schema_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            docx_path = td_path / "mapping.docx"
            _write_docx(
                docx_path,
                [
                    (
                        "Customer",
                        ["Name", "Data Type", "Nullable"],
                        [["customer_id", "int", "No"], ["email", "string", "Yes"]],
                    ),
                    (
                        "Order",
                        ["Name", "Data Type", "Nullable"],
                        [["order_id", "int", "No"]],
                    ),
                ],
            )

            mapping = render_mapping_markdown(propose_mapping(str(docx_path)))
            parsed = parse_mapping_markdown(mapping)
            written = write_schema_files(docx_path, parsed, td_path / "schema")

            self.assertEqual(len(parsed), 1)
            self.assertEqual(len(written), 2)
            customer_schema = (td_path / "schema" / "Customer_schema.md").read_text(encoding="utf-8")
            self.assertIn("## Custom Riders", customer_schema)
            self.assertIn("## Provenance / Audit Columns", customer_schema)
            self.assertIn("_None defined._", customer_schema)
            self.assertNotIn("source_system", customer_schema)
            self.assertNotIn("load_id", customer_schema)

    def test_write_schema_files_uses_simple_table_name_based_filename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            docx_path = td_path / "mapping.docx"
            _write_docx(
                docx_path,
                [
                    (
                        "Customer Metadata",
                        ["Name", "Data Type"],
                        [["customer_id", "int"]],
                    )
                ],
            )

            written = write_schema_files(docx_path, parse_mapping_markdown(render_mapping_markdown(propose_mapping(str(docx_path)))), td_path / "schema")

            self.assertEqual(len(written), 1)
            self.assertTrue((td_path / "schema" / "Customer Metadata_schema.md").exists())

    def test_create_schema_cli_writes_one_file_per_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            docx_path = td_path / "mapping.docx"
            mapping_path = td_path / "mapping.md"
            out_dir = td_path / "schema"

            _write_docx(
                docx_path,
                [
                    (
                        "Customer",
                        ["Name", "Data Type"],
                        [["customer_id", "int"]],
                    ),
                    (
                        "Order",
                        ["Name", "Data Type"],
                        [["order_id", "int"]],
                    ),
                ],
            )

            mapping_path.write_text(render_mapping_markdown(propose_mapping(str(docx_path))), encoding="utf-8")
            exit_code = main(["create-schema", f"@{docx_path}", f"@{mapping_path}", "--out-dir", str(out_dir)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((out_dir / "Customer_schema.md").exists())
            self.assertTrue((out_dir / "Order_schema.md").exists())

    def test_propose_mapping_cli_accepts_slash_command_and_at_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            docx_path = td_path / "mapping.docx"
            mapping_path = td_path / "mapping.md"

            _write_docx(
                docx_path,
                [
                    (
                        "Customer",
                        ["Name", "Data Type"],
                        [["customer_id", "int"]],
                    )
                ],
            )

            exit_code = main(["/propose-mapping", f"@{docx_path}", "--out", str(mapping_path)])

            self.assertEqual(exit_code, 0)
            text = mapping_path.read_text(encoding="utf-8")
            self.assertIn("- Tables: Customer", text)
            self.assertIn("| Name | Column |", text)
            self.assertNotIn("### Customer", text)

    def test_parse_mapping_errors_when_no_tables_found(self) -> None:
        with self.assertRaisesRegex(ValueError, "no tables found in mapping markdown"):
            parse_mapping_markdown("# Proposed Mapping\n")

    def test_create_schema_cli_returns_error_code_when_mapping_has_no_tables(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            source_docx = td_path / "source.docx"
            mapping_path = td_path / "empty.md"
            _write_docx(source_docx, [(
                "Customer",
                ["Name", "Data Type"],
                [["customer_id", "int"]],
            )])
            mapping_path.write_text("# Proposed Mapping\n", encoding="utf-8")

            exit_code = main(["create-schema", str(source_docx), str(mapping_path), "--out-dir", str(td_path / "schema")])

            self.assertEqual(exit_code, 1)

    def test_multi_column_set_round_trip_and_cross_set_writes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            docx_path = td_path / "mapping.docx"
            _write_docx(
                docx_path,
                [
                    (
                        "Customer",
                        ["Name", "Data Type", "Nullable"],
                        [["customer_id", "int", "No"]],
                    ),
                    (
                        "Customer Metadata",
                        ["Field", "Rule"],
                        [["record_hash", "md5(name)"]],
                    ),
                ],
            )

            mapping = render_mapping_markdown(propose_mapping(str(docx_path)))
            self.assertIn("## Column Set 1", mapping)
            self.assertIn("## Column Set 2", mapping)

            parsed = parse_mapping_markdown(mapping)
            self.assertEqual(len(parsed), 2)

            written = write_schema_files(docx_path, parsed, td_path / "schema")
            self.assertEqual(len(written), 2)
            self.assertTrue((td_path / "schema" / "Customer_schema.md").exists())
            self.assertTrue((td_path / "schema" / "Customer Metadata_schema.md").exists())

    def test_duplicate_table_name_across_column_sets_errors(self) -> None:
        mapping = """# Proposed Mapping

## Column Set 1

| Extracted Column | Target Column |
|---|---|
| Name | Column |

### Customer

| Column | Type | Nullable | Primary Key | Foreign Key | Details | Description | Source |
|---|---|---|---|---|---|---|---|
| customer_id | int | No | Yes |  |  |  |  |

## Column Set 2

| Extracted Column | Target Column |
|---|---|
| Field | Column |

### Customer

| Column | Type | Nullable | Primary Key | Foreign Key | Details | Description | Source |
|---|---|---|---|---|---|---|---|
| record_hash | string | No | No |  |  |  |  |
"""
        parsed = parse_mapping_markdown(mapping)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            source_docx = td_path / "source.docx"
            _write_docx(
                source_docx,
                [
                    (
                        "Customer",
                        ["Name"],
                        [["customer_id"]],
                    ),
                    (
                        "Customer",
                        ["Field"],
                        [["record_hash"]],
                    ),
                ],
            )
            with self.assertRaisesRegex(ValueError, "duplicate table name across column sets: Customer"):
                write_schema_files(source_docx, parsed, td_path / "schema")

    def test_rejects_oversized_document_xml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "oversized.docx"
            oversized = "<w:document>" + ("a" * (11 * 1024 * 1024)) + "</w:document>"
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("word/document.xml", oversized)

            with self.assertRaisesRegex(ValueError, "exceeds the maximum supported size"):
                propose_mapping(str(docx_path))

    def test_rejects_doctype_and_entity_in_document_xml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "unsafe.docx"
            unsafe_xml = """<!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>id</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("word/document.xml", unsafe_xml)

            with self.assertRaisesRegex(ValueError, "contains disallowed XML declarations"):
                propose_mapping(str(docx_path))

    def test_falls_back_to_generated_table_name_without_preceding_paragraph(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "no-name.docx"
            xml = """
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Data Type</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>customer_id</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>int</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("word/document.xml", xml)

            mapping = render_mapping_markdown(propose_mapping(str(docx_path)))

            self.assertIn("- Tables: table_1", mapping)

    def test_long_prose_paragraph_is_not_used_as_table_name(self) -> None:
        prose = (
            "These sources support the normalized data model by confirming that the "
            "required financial events and signals are available across major providers "
            "so not every provider will expose every field directly."
        )
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "prose.docx"
            xml = f"""
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{html_escape(prose)}</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Data Type</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>customer_id</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>int</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("word/document.xml", xml)

            column_sets = propose_mapping(str(docx_path))
            self.assertEqual(column_sets[0].table_names, ["table_1"])

            with tempfile.TemporaryDirectory() as out_dir:
                written = write_schema_files(str(docx_path), column_sets, out_dir)

            self.assertEqual(len(written), 1)
            self.assertLessEqual(len(written[0].name), 96)

    def test_heading_styled_paragraph_is_used_as_table_name(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "heading.docx"
            xml = """
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Payment Events Table Definition Reference Guide Section One</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Data Type</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>customer_id</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>int</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("word/document.xml", xml)

            column_sets = propose_mapping(str(docx_path))
            self.assertEqual(
                column_sets[0].table_names,
                ["Payment Events Table Definition Reference Guide Section One"],
            )

    def test_label_line_before_table_is_not_used_as_table_name(self) -> None:
        # A short "Label: value" line such as "Routes to: Outflow Worker as a
        # hard constraint." previously passed the heading-like heuristic and
        # became a table name; when it preceded two tables they collided with a
        # "duplicate table name across column sets" error.
        label = "Routes to: Outflow Worker as a hard constraint."
        with tempfile.TemporaryDirectory() as td:
            docx_path = Path(td) / "labels.docx"
            block = f"""
    <w:p><w:r><w:t>{html_escape(label)}</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Field</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Type</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>amount</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>decimal</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>"""
            xml = (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>" + block + block + "</w:body></w:document>"
            )
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr("word/document.xml", xml)

            column_sets = propose_mapping(str(docx_path))
            self.assertEqual(column_sets[0].table_names, ["table_1", "table_2"])

            with tempfile.TemporaryDirectory() as out_dir:
                written = write_schema_files(str(docx_path), column_sets, out_dir)

            self.assertEqual([path.name for path in written], ["table_1_schema.md", "table_2_schema.md"])


class TestSvgExtraction(unittest.TestCase):
    def _write_svg(self, path: Path, body: str) -> None:
        xml = f'<svg xmlns="http://www.w3.org/2000/svg" width="2050" height="4532">{body}</svg>'
        path.write_text(xml, encoding="utf-8")

    def test_grouped_tables_use_thtext_names_and_class_driven_cells(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "tables_connected.xml"
            body = (
                '<g id="silver_psp_transaction">'
                '<text x="37" y="190" class="thText">silver_psp_transaction</text>'
                '<text x="37" y="207" class="headText">COLUMN</text>'
                '<text x="298" y="207" class="headText">TYPE</text>'
                '<text x="37" y="229" class="cell">transaction_id</text>'
                '<text x="298" y="229" class="cell">string</text>'
                '<text x="37" y="251" class="cell">gross_amount</text>'
                '<text x="298" y="251" class="cell">decimal</text>'
                "</g>"
                '<g id="gold_psp_ledger">'
                '<text x="557" y="190" class="thText">gold_psp_ledger</text>'
                '<text x="557" y="207" class="headText">COLUMN</text>'
                '<text x="818" y="207" class="headText">TYPE</text>'
                '<text x="557" y="229" class="cell">ledger_id</text>'
                '<text x="818" y="229" class="cell">string</text>'
                "</g>"
            )
            self._write_svg(svg_path, body)

            column_sets = propose_mapping(str(svg_path))
            self.assertEqual(
                column_sets[0].table_names,
                ["silver_psp_transaction", "gold_psp_ledger"],
            )
            self.assertEqual(
                column_sets[0].pairs,
                [("COLUMN", "Column"), ("TYPE", "Type")],
            )

            mapping = render_mapping_markdown(column_sets)
            with tempfile.TemporaryDirectory() as out_dir:
                written = write_schema_files(str(svg_path), parse_mapping_markdown(mapping), out_dir)
                names = sorted(path.name for path in written)
                self.assertEqual(
                    names,
                    ["gold_psp_ledger_schema.md", "silver_psp_transaction_schema.md"],
                )
                silver = next(p for p in written if p.name.startswith("silver")).read_text(encoding="utf-8")

            self.assertIn("| transaction_id | string |", silver)
            self.assertIn("| gross_amount | decimal |", silver)

    def test_ungrouped_svg_falls_back_to_single_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "PSP Ledger.svg"
            body = (
                '<text x="37" y="207" class="headText">COLUMN</text>'
                '<text x="298" y="207" class="headText">TYPE</text>'
                '<text x="37" y="229" class="cell">amount</text>'
                '<text x="298" y="229" class="cell">decimal</text>'
            )
            self._write_svg(svg_path, body)

            column_sets = propose_mapping(str(svg_path))
            self.assertEqual(column_sets[0].table_names, ["PSP Ledger"])

    def test_rejects_doctype_in_svg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "unsafe.svg"
            svg_path.write_text(
                '<?xml version="1.0"?><!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg">'
                '<text x="0" y="0" class="cell">a</text></svg>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "disallowed XML declarations"):
                propose_mapping(str(svg_path))

    def test_rejects_non_svg_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "notsvg.svg"
            svg_path.write_text("<root><text>a</text></root>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not an SVG file"):
                propose_mapping(str(svg_path))


class TestSvgRelationships(unittest.TestCase):
    def _write_svg(self, path: Path, body: str) -> None:
        xml = f'<svg xmlns="http://www.w3.org/2000/svg" width="2050" height="4532">{body}</svg>'
        path.write_text(xml, encoding="utf-8")

    def _fan_out_body(self) -> str:
        return (
            '<g id="silver">'
            '<rect class="tbl" x="30" y="180" width="380" height="100"/>'
            '<text x="37" y="190" class="thText">silver_psp_transaction</text>'
            '<text x="37" y="229" class="cell">settlement_batch_id</text>'
            '<text x="37" y="251" class="cell">gross_amount</text>'
            "</g>"
            '<g id="gold1">'
            '<rect class="tbl" x="560" y="180" width="380" height="60"/>'
            '<text x="567" y="190" class="thText">gold_net_revenue</text>'
            '<text x="567" y="229" class="cell">batch_ref</text>'
            "</g>"
            '<g id="gold2">'
            '<rect class="tbl" x="560" y="300" width="380" height="60"/>'
            '<text x="567" y="310" class="thText">gold_settlement_revenue</text>'
            '<text x="567" y="329" class="cell">batch_ref</text>'
            "</g>"
            '<line class="stub" x1="410" y1="229" x2="545" y2="229"/>'
            '<line class="stub" x1="545" y1="229" x2="545" y2="329"/>'
            '<path class="link" d="M545 229 L560 229"/>'
            '<path class="link" d="M545 329 L560 329"/>'
        )

    def test_fan_out_arrows_yield_one_relationship_per_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "connected.svg"
            self._write_svg(svg_path, self._fan_out_body())

            relationships = extract_relationships(str(svg_path))
            self.assertCountEqual(
                relationships,
                [
                    Relationship(
                        "silver_psp_transaction",
                        "settlement_batch_id",
                        "gold_net_revenue",
                        "batch_ref",
                    ),
                    Relationship(
                        "silver_psp_transaction",
                        "settlement_batch_id",
                        "gold_settlement_revenue",
                        "batch_ref",
                    ),
                ],
            )

    def test_read_relationships_dispatches_svg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "connected.svg"
            self._write_svg(svg_path, self._fan_out_body())
            self.assertEqual(len(read_relationships(str(svg_path))), 2)

    def test_read_relationships_returns_empty_for_non_svg(self) -> None:
        self.assertEqual(read_relationships("C:/nope/source.docx"), [])

    def test_svg_without_connectors_has_no_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "isolated.svg"
            body = (
                '<g id="silver">'
                '<rect class="tbl" x="30" y="180" width="380" height="60"/>'
                '<text x="37" y="190" class="thText">silver_only</text>'
                '<text x="37" y="229" class="cell">id</text>'
                "</g>"
            )
            self._write_svg(svg_path, body)
            self.assertEqual(extract_relationships(str(svg_path)), [])

    def test_render_relationships_markdown_includes_table_and_mermaid(self) -> None:
        relationships = [
            Relationship("a", "a_id", "b", "a_ref"),
        ]
        text = render_relationships_markdown(relationships)
        self.assertIn("| Source Table | Source Column | Target Table | Target Column |", text)
        self.assertIn("| a | a_id | b | a_ref |", text)
        self.assertIn("```mermaid", text)
        self.assertIn("erDiagram", text)
        self.assertIn('a ||--o{ b : "a_id -> a_ref"', text)

    def test_render_relationships_markdown_empty(self) -> None:
        text = render_relationships_markdown([])
        self.assertIn("_No relationships found._", text)


class TestColumnLineParsing(unittest.TestCase):
    def test_paren_type_with_primary_key_and_foreign_key(self) -> None:
        parsed = parse_column_line("customer_id (uuid) primary key")
        assert parsed is not None
        self.assertEqual(parsed.name, "customer_id")
        self.assertEqual(parsed.data_type, "uuid")
        self.assertTrue(parsed.primary_key)
        self.assertEqual(parsed.foreign_key, "customer")

    def test_colon_type_and_nullable(self) -> None:
        parsed = parse_column_line("email: string not null")
        assert parsed is not None
        self.assertEqual(parsed.name, "email")
        self.assertEqual(parsed.data_type, "string")
        self.assertFalse(parsed.nullable)

    def test_description_after_dash(self) -> None:
        parsed = parse_column_line("status (string) - current lifecycle state")
        assert parsed is not None
        self.assertEqual(parsed.name, "status")
        self.assertEqual(parsed.data_type, "string")
        self.assertEqual(parsed.description, "current lifecycle state")

    def test_references_infers_foreign_key(self) -> None:
        parsed = parse_column_line("account_ref references account")
        assert parsed is not None
        self.assertEqual(parsed.foreign_key, "account")

    def test_blank_line_returns_none(self) -> None:
        self.assertIsNone(parse_column_line("   "))


class TestTextSchemaReader(unittest.TestCase):
    def test_free_text_entity_maps_to_target_columns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "notes.txt"
            source.write_text(
                "Entity: Customer\n"
                "- customer_id (uuid) primary key\n"
                "- email: string not null\n"
                "- created_at (timestamp)\n",
                encoding="utf-8",
            )

            tables = read_tables(str(source))
            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0].name, "Customer")
            self.assertEqual(tables[0].headers, TARGET_COLUMNS)

            column_sets = propose_mapping(str(source))
            self.assertEqual(column_sets[0].table_names, ["Customer"])
            self.assertEqual(
                column_sets[0].pairs,
                [(target, target) for target in TARGET_COLUMNS],
            )

            mapping = render_mapping_markdown(column_sets)
            with tempfile.TemporaryDirectory() as out_dir:
                written = write_schema_files(str(source), parse_mapping_markdown(mapping), out_dir)
                schema = written[0].read_text(encoding="utf-8")

            self.assertIn("# Customer Schema", schema)
            self.assertIn("customer_id", schema)
            self.assertIn("uuid", schema)
            self.assertIn("| email | string | No |", schema)

    def test_markdown_headings_and_pipe_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "schema.md"
            source.write_text(
                "# Orders\n"
                "| Column | Type |\n"
                "|---|---|\n"
                "| order_id | int |\n"
                "| total | decimal |\n",
                encoding="utf-8",
            )

            tables = read_tables(str(source))
            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0].name, "Orders")
            self.assertEqual(tables[0].headers, ["Column", "Type"])
            self.assertEqual(tables[0].rows, [["order_id", "int"], ["total", "decimal"]])

            column_sets = propose_mapping(str(source))
            self.assertEqual(
                column_sets[0].pairs,
                [("Column", "Column"), ("Type", "Type")],
            )

    def test_no_heading_uses_filename_entity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "payment events.txt"
            source.write_text("transaction_id (uuid) primary key\n", encoding="utf-8")

            tables = read_tables(str(source))
            self.assertEqual(tables[0].name, "payment events")

    def test_empty_text_source_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "blank.txt"
            source.write_text("\n\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No schema tables"):
                read_tables(str(source))


if __name__ == "__main__":
    unittest.main()
