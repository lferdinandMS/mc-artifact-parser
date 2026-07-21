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
        self.assertIn("### Customer", mapping)
        self.assertIn("| " + " | ".join(TARGET_COLUMNS) + " |", mapping)

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
            written = write_schema_files(parsed, td_path / "schema")

            self.assertEqual(len(parsed), 1)
            self.assertEqual(len(written), 2)
            customer_schema = (td_path / "schema" / "customer_schema.md").read_text(encoding="utf-8")
            self.assertIn("## Custom Riders", customer_schema)
            self.assertIn("## Provenance / Audit Columns", customer_schema)
            self.assertIn("_None defined._", customer_schema)
            self.assertNotIn("source_system", customer_schema)
            self.assertNotIn("load_id", customer_schema)

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
            exit_code = main(["create-schema", f"@{mapping_path}", "--out-dir", str(out_dir)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((out_dir / "customer_schema.md").exists())
            self.assertTrue((out_dir / "order_schema.md").exists())

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
            self.assertIn("### Customer", text)
            self.assertIn("customer_id", text)

    def test_parse_mapping_errors_when_no_tables_found(self) -> None:
        with self.assertRaisesRegex(ValueError, "no tables found in mapping markdown"):
            parse_mapping_markdown("# Proposed Mapping\n")

    def test_create_schema_cli_returns_error_code_when_mapping_has_no_tables(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mapping_path = Path(td) / "empty.md"
            mapping_path.write_text("# Proposed Mapping\n", encoding="utf-8")

            exit_code = main(["create-schema", str(mapping_path), "--out-dir", str(Path(td) / "schema")])

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

            written = write_schema_files(parsed, td_path / "schema")
            self.assertEqual(len(written), 2)
            self.assertTrue((td_path / "schema" / "customer_schema.md").exists())
            self.assertTrue((td_path / "schema" / "customer_metadata_schema.md").exists())

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
            with self.assertRaisesRegex(ValueError, "duplicate table name across column sets: Customer"):
                write_schema_files(parsed, Path(td) / "schema")

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

            self.assertIn("### table_1", mapping)


if __name__ == "__main__":
    unittest.main()
