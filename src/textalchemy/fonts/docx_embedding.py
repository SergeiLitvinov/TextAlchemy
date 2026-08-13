"""Embed deterministic obfuscated OpenType subsets into DOCX packages."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from uuid import UUID

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity
from textalchemy.core.document_model import DocumentModel
from textalchemy.fonts.embedding import FontUsage, collect_font_usages, subset_font

_FONT_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.obfuscatedFont"


def embed_docx_fonts(target: object, document: DocumentModel, report: ConversionReport) -> None:
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    try:
        font_table = target.part.part_related_by(RT.FONT_TABLE)
    except (AttributeError, KeyError):
        report.add(IssueSeverity.LOSS, "font-embedding", "DOCX font table is unavailable")
        return
    embedded = source_bytes = subset_bytes = 0
    for index, usage in enumerate(collect_font_usages(document), start=1):
        if not usage.embeddable:
            continue
        try:
            source_size = usage.path.stat().st_size
            data = subset_font(usage)
            font_key = _font_key(usage, data)
            part = _font_part(target, data, font_key, index)
            relationship_id = font_table.relate_to(part, RT.FONT)
            _register_font(font_table, usage, relationship_id, font_key)
        except (OSError, ValueError) as error:
            report.add(IssueSeverity.WARNING, "font-embedding", f"cannot embed font {usage.family!r}: {error}")
            continue
        embedded += 1
        source_bytes += source_size
        subset_bytes += len(data)
    report.metrics["font_embedding"] = {
        "embedded_faces": embedded,
        "source_bytes": source_bytes,
        "subset_bytes": subset_bytes,
        "target": "docx",
    }


def _font_key(usage: FontUsage, data: bytes) -> UUID:
    digest = hashlib.sha256(usage.family.encode("utf-8") + bytes((usage.bold, usage.italic)) + data).digest()
    return UUID(bytes=digest[:16])


def _font_part(target: object, data: bytes, font_key: UUID, index: int) -> object:
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    package = target.part.package
    partname = PackURI(f"/word/fonts/font{index}-{font_key.hex[:12]}.odttf")
    return Part(partname, _FONT_CONTENT_TYPE, _obfuscate(data, font_key), package)


def _obfuscate(data: bytes, font_key: UUID) -> bytes:
    result = bytearray(data)
    key = font_key.bytes[::-1]
    for index in range(min(32, len(result))):
        result[index] ^= key[index % 16]
    return bytes(result)


def _register_font(font_table: object, usage: FontUsage, relationship_id: str, font_key: UUID) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from lxml import etree

    root = etree.fromstring(font_table.blob)
    font = next((item for item in root.findall(qn("w:font")) if item.get(qn("w:name")) == usage.family), None)
    if font is None:
        font = OxmlElement("w:font")
        font.set(qn("w:name"), usage.family)
        root.append(font)
    if usage.bold and usage.italic:
        tag = "embedBoldItalic"
    elif usage.bold:
        tag = "embedBold"
    elif usage.italic:
        tag = "embedItalic"
    else:
        tag = "embedRegular"
    embed = font.find(qn(f"w:{tag}"))
    if embed is None:
        embed = OxmlElement(f"w:{tag}")
        font.append(embed)
    embed.set(qn("r:id"), relationship_id)
    embed.set(qn("w:fontKey"), "{" + str(font_key).upper() + "}")
    font_table._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def verify_docx_font_embedding(output: str | Path, report: ConversionReport) -> None:
    expected = int(report.metrics.get("font_embedding", {}).get("embedded_faces", 0))
    if expected == 0:
        return
    try:
        with zipfile.ZipFile(output) as package:
            font_parts = [name for name in package.namelist() if name.startswith("word/fonts/") and name.endswith(".odttf")]
            font_table = package.read("word/fontTable.xml")
            relationships = package.read("word/_rels/fontTable.xml.rels")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        report.add(IssueSeverity.LOSS, "font-embedding", f"cannot verify DOCX embedded fonts: {error}")
        return
    verified = min(len(font_parts), font_table.count(b"embed"), relationships.count(b"relationships/font"))
    report.metrics["font_embedding"]["verified_faces"] = verified
    if verified < expected:
        report.add(
            IssueSeverity.LOSS,
            "font-embedding",
            f"DOCX contains {verified} verified embedded font face(s), expected {expected}",
        )


__all__ = ["embed_docx_fonts", "verify_docx_font_embedding"]
