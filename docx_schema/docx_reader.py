"""Read ordered content blocks from a ``.docx`` file using only stdlib.

Security hardening mirrors the original adapter: the archive member is size
capped, and DOCTYPE/ENTITY declarations are rejected to avoid XML external
entity (XXE = XML eXternal Entity) attacks.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W_NS}
_MAX_DOCUMENT_XML_BYTES = 10 * 1024 * 1024


@dataclass
class Paragraph:
    text: str
    style: str = ""


@dataclass
class WordTable:
    rows: list[list[str]]


def read_blocks(path: str) -> list[Paragraph | WordTable]:
    """Return paragraphs and tables in document order."""

    xml = _read_document_xml(path)
    root = ET.fromstring(xml)
    body = root.find("w:body", _NS)
    if body is None:
        return []

    blocks: list[Paragraph | WordTable] = []
    for child in list(body):
        tag = _local(child.tag)
        if tag == "p":
            blocks.append(_read_paragraph(child))
        elif tag == "tbl":
            blocks.append(_read_table(child))
    return blocks


def _read_document_xml(path: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        try:
            info = archive.getinfo("word/document.xml")
        except KeyError as exc:
            raise ValueError(f"{path} is missing word/document.xml") from exc

        if info.file_size > _MAX_DOCUMENT_XML_BYTES:
            raise ValueError("DOCX word/document.xml exceeds the maximum supported size.")

        xml = archive.read(info)

    if re.search(br"<!\s*(doctype|entity)\b", xml, flags=re.IGNORECASE):
        raise ValueError("DOCX word/document.xml contains disallowed XML declarations.")

    return xml


def _read_paragraph(paragraph: ET.Element) -> Paragraph:
    text = "".join(node.text for node in paragraph.findall(".//w:t", _NS) if node.text is not None).strip()
    style_el = paragraph.find("w:pPr/w:pStyle", _NS)
    style = ""
    if style_el is not None:
        style = style_el.get(f"{{{_W_NS}}}val", "") or ""
    return Paragraph(text=text, style=style)


def _read_table(table: ET.Element) -> WordTable:
    rows: list[list[str]] = []
    for row in table.findall("w:tr", _NS):
        cells: list[str] = []
        for cell in row.findall("w:tc", _NS):
            cell_text = " ".join(
                (node.text or "").strip()
                for node in cell.findall(".//w:t", _NS)
                if node.text is not None
            ).strip()
            cells.append(cell_text)
        rows.append(cells)
    return WordTable(rows=rows)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_docx_path(raw: str) -> Path:
    """Strip a leading ``@`` (chat-style reference) and expand the path."""

    cleaned = raw.strip()
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    return Path(cleaned).expanduser()
