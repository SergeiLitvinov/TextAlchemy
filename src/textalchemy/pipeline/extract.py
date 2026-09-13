"""Универсальный ридер: Document → Text.

Выбирает движок по ``Document.format``. Сейчас PDF идёт по цепочке
``pdfplumber → pypdf → pymupdf geometry → semantics`` (см. formats/pdf.py).
"""

from __future__ import annotations

from typing import Any

from textalchemy.core.color import ColorValue
from textalchemy.core.document_model import (
    Block as RichBlock,
)
from textalchemy.core.document_model import (
    Box,
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Length,
    PageSettings,
    Paragraph,
    Provenance,
    ProvenanceEvent,
    Resource,
    ResourceKind,
    Section,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
)
from textalchemy.core.document_model import (
    Image as RichImage,
)
from textalchemy.core.document_model import (
    Table as RichTable,
)
from textalchemy.core.registry import operation
from textalchemy.core.types import BlockType, DocFormat, Document, Text
from textalchemy.core.units import canonical_coordinate_contract


@operation(
    "extract.text",
    input_type="Document",
    output_type="Text",
    input_param="doc",
    description="Document → Text (универсальный ридер по формату).",
    tags=["extract"],
)
def extract_text(*, doc: Document) -> Text:
    if doc.format == DocFormat.PDF:
        from textalchemy.formats.pdf import read_pdf

        return read_pdf(str(doc.path))
    if doc.format == DocFormat.DOCX:
        from textalchemy.formats.docx import read_docx

        return read_docx(doc.path)
    if doc.format == DocFormat.TXT:
        from textalchemy.formats.txt import read_txt

        return read_txt(doc.path)
    if doc.format == DocFormat.DJVU:
        from textalchemy.formats.txt import read_djvu

        return read_djvu(doc.path)
    if doc.format == DocFormat.HTML:
        from textalchemy.formats.html import read_html

        return read_html(doc.path)
    if doc.format == DocFormat.EPUB:
        from textalchemy.formats.epub import read_epub

        return read_epub(doc.path)
    return Text(
        source_format=doc.format,
        engine="none",
        warnings=[f"no reader for format {doc.format.value!r}"],
    )


__all__ = ["extract_text", "extract_pdf_model", "extract_pptx_model", "extract_epub_model", "extract_html_model"]


@operation(
    "extract.html_model", input_type="Document", output_type="DocumentModel", input_param="doc",
    description="Статический HTML → DocumentModel; ограничения в metadata.html.warnings.",
    tags=["extract", "html", "document-model"],
)
def extract_html_model(*, doc: Document) -> DocumentModel:
    from textalchemy.formats.html import read_html_model

    if doc.format is not DocFormat.HTML:
        raise ValueError("extract.html_model requires an HTML document")
    return read_html_model(doc.path)


@operation(
    "extract.epub_model",
    input_type="Document",
    output_type="DocumentModel",
    input_param="doc",
    description="EPUB → DocumentModel (главы, ссылки, изображения и базовое CSS).",
    tags=["extract", "epub", "document-model"],
)
def extract_epub_model(*, doc: Document) -> DocumentModel:
    from textalchemy.formats.epub import read_epub_model

    if doc.format is not DocFormat.EPUB:
        raise ValueError("extract.epub_model requires an EPUB document")
    return read_epub_model(doc.path)


@operation(
    "extract.pdf_model",
    input_type="Document",
    output_type="DocumentModel",
    input_param="doc",
    description="PDF → DocumentModel (геометрия, таблицы, изображения, векторные рисунки).",
    tags=["extract", "pdf", "document-model"],
)
def extract_pdf_model(
    *,
    doc: Document,
    use_ocr: bool = False,
    ocr_backend: str = "",
    handwriting: bool = False,
    use_gpu: bool = False,
    mode: str | None = None,
) -> DocumentModel:
    """Извлечь PDF в богатую модель с текстом, таблицами и изображениями.

    Единый сценарий «text layer + OCR» задаётся ``mode``:
    ``fast`` — только текстовый слой; ``structure`` — text layer + OCR-слияние;
    ``scan`` — только OCR. При отсутствии ``mode`` поведение определяется
    ``use_ocr`` (backward compatibility).

    Args:
        doc: Документ PDF.
        use_ocr: Включить OCR-слияние с текстовым слоем (⇒ mode ``structure``).
        ocr_backend: Имя OCR-бэкенда (tesseract/easyocr/paddle).
        handwriting: Режим распознавания рукописного текста.
        use_gpu: Использовать GPU для OCR.
        mode: Стратегия обработки: ``fast`` / ``structure`` / ``scan``.

    Returns:
        ``DocumentModel`` с текстом, таблицами и изображениями.
    """
    from textalchemy.formats.pdf_ocr_merge import (
        PDF_SCENARIO_FAST,
        PDF_SCENARIO_MODES,
        PDF_SCENARIO_SCAN,
        PDF_SCENARIO_STRUCTURE,
    )

    scenario = mode if mode is not None else (PDF_SCENARIO_STRUCTURE if use_ocr else PDF_SCENARIO_FAST)
    if scenario not in PDF_SCENARIO_MODES:
        raise ValueError(f"unknown PDF scenario mode {scenario!r}; expected one of {PDF_SCENARIO_MODES}")

    if doc.format != DocFormat.PDF:
        return DocumentModel(
            sections=[],
            source_format=doc.format.value,
            metadata={"engine": "none", "warnings": [f"extract.pdf_model: not a PDF: {doc.format.value!r}"]},
        )

    from textalchemy.formats.pdf import read_pdf_geometry
    from textalchemy.formats.pdf_images import (
        enrich_geometry_with_images,
        extract_pdf_images,
        extract_pdf_vector_drawings,
    )

    path = str(doc.path)
    geometry = read_pdf_geometry(path)
    engine = f"pymupdf+{scenario}+document-model"
    ocr_pages = None

    # OCR-слияние для structure/scan сценариев.
    if scenario in (PDF_SCENARIO_STRUCTURE, PDF_SCENARIO_SCAN):
        from textalchemy.recognize.ocr import OcrEngine

        ocr_engine = OcrEngine(
            backend=ocr_backend if ocr_backend else "auto",
            use_gpu=use_gpu,
        )
        if ocr_engine.is_available:
            try:
                ocr_pages = ocr_engine.recognize_pdf_geometry(path, handwriting=handwriting)
            except Exception as exc:  # noqa: BLE001
                geometry.warnings.append(f"OCR failed: {exc}")
        else:
            geometry.warnings.append("OCR engine requested but none available")

    images, img_warnings = extract_pdf_images(path)
    vectors, vec_warnings = extract_pdf_vector_drawings(path)
    geometry = enrich_geometry_with_images(geometry, images, vectors)

    from textalchemy.formats.pdf_ocr_merge import merge_pdf_with_ocr

    semantic = merge_pdf_with_ocr(geometry, ocr_pages, use_text_layer=(scenario != PDF_SCENARIO_SCAN))

    all_warnings: list[str] = list(geometry.warnings) + img_warnings + vec_warnings

    sections: list[Section] = []
    resources: dict[str, Resource] = {}

    for page in geometry.pages:
        blocks: list[RichBlock] = []
        headers: list[RichBlock] = []
        footers: list[RichBlock] = []
        source_blocks = {block.number: block for block in page.text_blocks}

        def origin(object_id: str, *, detail: str, fallback_reason: str | None = None) -> Provenance:
            return Provenance(
                source_format=DocFormat.PDF.value,
                source_path=path,
                page=page.number,
                object_id=object_id,
                events=[ProvenanceEvent(f"extract.pdf.{scenario}", detail, fallback_reason)],
            )

        for semantic_block in (block for block in semantic.blocks if block.page == page.number):
            box = _pdf_box(semantic_block.meta.get("bbox"))
            properties = {
                "legacy_type": semantic_block.type.value,
                "page": page.number,
                **semantic_block.meta,
            }
            if semantic_block.type is BlockType.TABLE:
                rows = [
                    TableRow(cells=[TableCell(blocks=[Paragraph(content=[TextRun(text=str(value))])]) for value in row])
                    for row in semantic_block.meta.get("rows", [])
                ]
                blocks.append(
                    RichTable(
                        rows=rows,
                        box=box,
                        properties={"pdf": properties},
                        provenance=origin(
                            f"semantic-{semantic_block.meta.get('source_block', 'table')}",
                            detail="reconstructed semantic table",
                            fallback_reason="table inferred from PDF geometry",
                        ),
                    )
                )
                continue

            source_number = semantic_block.meta.get("source_block")
            source_block = source_blocks.get(int(source_number)) if source_number is not None else None
            runs = _pdf_text_runs(source_block, semantic_block.text, semantic_block.meta)
            if semantic_block.type is BlockType.EQUATION:
                rich_block: RichBlock = Formula(
                    value=semantic_block.text,
                    format=FormulaFormat.LATEX,
                    display=True,
                    fallback_text=semantic_block.text,
                    box=box,
                    properties=properties,
                    provenance=origin(
                        f"semantic-{source_number or 'equation'}",
                        detail="classified equation block",
                        fallback_reason="equation retained as LaTeX text without source math structure",
                    ),
                )
            else:
                merge_source = semantic_block.meta.get("source") or semantic_block.meta.get("origin") or "text-layer"
                rich_block = Paragraph(
                    content=runs,
                    box=box,
                    properties=properties,
                    provenance=origin(
                        f"semantic-{source_number or len(blocks)}",
                        detail=f"merged semantic block from {merge_source}",
                        fallback_reason="OCR supplied missing text" if "ocr" in str(merge_source).lower() else None,
                    ),
                )
            role = semantic_block.meta.get("semantic_role")
            if role == "header":
                headers.append(rich_block)
            elif role == "footer":
                footers.append(rich_block)
            else:
                blocks.append(rich_block)

        for img in page.extracted_images:
            resource_id = f"p{page.number}_img{img.xref}"
            if resource_id not in resources and img.data:
                resources[resource_id] = Resource(
                    id=resource_id,
                    kind=ResourceKind.RASTER_IMAGE,
                    media_type=img.media_type,
                    data=img.data,
                    filename=img.extension,
                    provenance=origin(f"image-xref-{img.xref}", detail="extracted embedded raster image"),
                )
            elif resource_id not in resources:
                continue
            bbox = img.bbox
            box = Box(x=bbox[0], y=bbox[1], width=bbox[2] - bbox[0], height=bbox[3] - bbox[1]) if len(bbox) == 4 else None
            image_origin = origin(f"image-xref-{img.xref}", detail="placed extracted raster image")
            blocks.append(
                Paragraph(
                    content=[RichImage(resource_id=resource_id, box=box, provenance=image_origin)],
                    provenance=image_origin,
                )
            )

        for vec in page.vector_drawings:
            resource_id = f"p{page.number}_vec{vec.number}"
            if resource_id not in resources:
                resources[resource_id] = Resource(
                    id=resource_id,
                    kind=ResourceKind.VECTOR_IMAGE,
                    media_type="application/pdf+vector",
                    data=b"",
                    properties={
                        "items": list(vec.items),
                        "fill": vec.fill.to_dict() if vec.fill else None,
                        "stroke": vec.stroke.to_dict() if vec.stroke else None,
                        "fill_opacity": vec.fill_opacity,
                        "stroke_opacity": vec.stroke_opacity,
                    },
                    provenance=origin(f"vector-{vec.number}", detail="extracted PDF drawing operators"),
                )
            bbox = vec.bbox
            box = Box(x=bbox[0], y=bbox[1], width=bbox[2] - bbox[0], height=bbox[3] - bbox[1]) if len(bbox) == 4 else None
            alt = f"Vector drawing {vec.number} on page {vec.page}"
            vector_origin = origin(f"vector-{vec.number}", detail="represented PDF drawing as editable vector resource")
            blocks.append(
                Paragraph(
                    content=[RichImage(resource_id=resource_id, box=box, alt_text=alt, provenance=vector_origin)],
                    provenance=vector_origin,
                )
            )

        sections.append(
            Section(
                blocks=blocks,
                headers=headers,
                footers=footers,
                page=PageSettings(
                    width=Length(page.width),
                    height=Length(page.height),
                ),
                provenance=origin(f"page-{page.number}", detail="created document section from PDF page"),
            )
        )

    metadata: dict[str, Any] = {
        "engine": engine,
        "pages": len(sections),
        "warnings": all_warnings,
        "coordinate_system": canonical_coordinate_contract(),
    }
    metadata.update(geometry.metadata)

    return DocumentModel(
        sections=sections,
        resources=resources,
        metadata=metadata,
        source_format="pdf",
        mode=ConversionMode.BALANCED,
    )


def _pdf_box(value: Any) -> Box | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    x0, y0, x1, y1 = (float(item) for item in value)
    return Box(x=x0, y=y0, width=max(0.0, x1 - x0), height=max(0.0, y1 - y0))


def _pdf_text_runs(source_block: Any, fallback_text: str, meta: dict[str, Any]) -> list[TextRun]:
    if source_block is not None:
        runs: list[TextRun] = []
        for line_index, line in enumerate(source_block.lines):
            if line_index:
                runs.append(TextRun(text="\n"))
            for span in line.spans:
                flags = int(span.flags)
                color = ColorValue.from_pdf_srgb(span.color)
                runs.append(
                    TextRun(
                        text=span.text,
                        style=TextStyle(
                            font_family=span.font or None,
                            font_size=Length(span.size) if span.size else None,
                            bold=bool(flags & 16),
                            italic=bool(flags & 2),
                            superscript=bool(flags & 1),
                            color=color,
                        ),
                    )
                )
        if runs:
            return runs
    font_spans = meta.get("font_spans") or []
    first = font_spans[0] if font_spans else {}
    flags = int(first.get("flags", 0))
    color = ColorValue.from_pdf_srgb(int(first.get("color", 0)))
    style = TextStyle(
        font_family=first.get("font") or None,
        font_size=Length(float(first["size"])) if first.get("size") else None,
        bold=bool(flags & 16),
        italic=bool(flags & 2),
        superscript=bool(flags & 1),
        color=color,
    )
    return [TextRun(text=fallback_text, style=style)]


@operation(
    "extract.pptx_model",
    input_type="Document",
    output_type="DocumentModel",
    input_param="doc",
    description="PPTX → DocumentModel (слайды, фигуры, таблицы, изображения, диаграммы, формулы).",
    tags=["extract", "pptx", "document-model"],
)
def extract_pptx_model(
    *,
    doc: Document,
    mode: ConversionMode = ConversionMode.BALANCED,
) -> DocumentModel:
    """Импортировать PPTX в богатую модель через ``read_pptx_model``.

    Args:
        doc: Документ PPTX.
        mode: Режим конвертации (editable/faithful/balanced).

    Returns:
        ``DocumentModel`` со слайдами в качестве секций.
    """
    if doc.format != DocFormat.PPTX:
        return DocumentModel(
            sections=[],
            source_format=doc.format.value,
            metadata={"engine": "none", "warnings": [f"extract.pptx_model: not a PPTX: {doc.format.value!r}"]},
        )

    from textalchemy.formats.pptx import read_pptx_model

    return read_pptx_model(doc.path, mode=mode)
