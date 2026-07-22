import subprocess
import sys
import tempfile
import unittest
import zipfile
from html import escape as html_escape
from pathlib import Path

from docx_schema.cli import main
from docx_schema.mapping import (
    parse_mapping_markdown,
    project_table,
    propose_mapping,
    render_mapping_markdown,
    write_schema_files,
)
from docx_schema.models import SourceTable, TARGET_COLUMNS


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
        package_dir = Path(__file__).resolve().parent.parent / "docx_schema"
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
        xml = f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>'
        path.write_text(xml, encoding="utf-8")

    def test_geometry_two_columns_extracts_column_type_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "PSP Ledger.svg"
            body = (
                '<text x="10" y="10">Column</text><text x="200" y="10">Type</text>'
                '<text x="10" y="30">amount</text><text x="200" y="30">decimal</text>'
                '<text x="10" y="50">currency</text><text x="200" y="50">string</text>'
            )
            self._write_svg(svg_path, body)

            column_sets = propose_mapping(str(svg_path))

            self.assertEqual(column_sets[0].table_names, ["PSP Ledger"])
            self.assertEqual(column_sets[0].pairs, [("Column", "Column"), ("Type", "Type")])

            mapping = render_mapping_markdown(column_sets)
            with tempfile.TemporaryDirectory() as out_dir:
                written = write_schema_files(str(svg_path), parse_mapping_markdown(mapping), out_dir)
                self.assertEqual([path.name for path in written], ["PSP Ledger_schema.md"])
                content = written[0].read_text(encoding="utf-8")

            self.assertIn("| amount | decimal |", content)
            self.assertIn("| currency | string |", content)

    def test_inline_label_value_text_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "inline.svg"
            body = (
                '<text x="0" y="0">amount: decimal</text>'
                '<text x="0" y="0">currency: string</text>'
            )
            self._write_svg(svg_path, body)

            column_sets = propose_mapping(str(svg_path))
            with tempfile.TemporaryDirectory() as out_dir:
                written = write_schema_files(
                    str(svg_path), parse_mapping_markdown(render_mapping_markdown(column_sets)), out_dir
                )
                content = written[0].read_text(encoding="utf-8")

            self.assertIn("| amount | decimal |", content)
            self.assertIn("| currency | string |", content)

    def test_rejects_doctype_in_svg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "unsafe.svg"
            svg_path.write_text(
                '<?xml version="1.0"?><!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg">'
                '<text x="0" y="0">a</text></svg>',
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


if __name__ == "__main__":
    unittest.main()
