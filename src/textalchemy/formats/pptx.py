"""PPTX → Text / DocumentModel импортёры.

Импортёр ``read_pptx_model`` переводит презентацию в богатую промежуточную
модель (``DocumentModel``): каждый слайд становится секцией с абсолютно
позиционированными блоками (абзацы, изображения, таблицы, формулы OMML,
диаграммы). Группы фигур разворачиваются в плоские блоки с учётом
трансформации группы (off/ext/chOff/chExt). Цвета приводятся к ``#RRGGBB``,
размеры — в пунктах.

Обход ведётся по сырому XML дерева фигур (``p:spTree``), а не через
python-pptx, чтобы не потерять контейнеры ``mc:AlternateContent``
(например, fallback-картинки диаграмм), которые python-pptx не отдаёт.

Модель не зависит от python-pptx: после импорта она содержит только типы
``textalchemy.core.document_model`` и может быть отрендерена любым экспортёром
(см. ``textalchemy.convert.pptx_html_writer``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from lxml import etree

from textalchemy.core.document_model import (
    Box,
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Length,
    PageSettings,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
)
from textalchemy.core.document_model import (
    Table as RichTable,
)
from textalchemy.core.types import Block, BlockType, DocFormat, Table, Text

EMU_PER_PT = 12700.0

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"

_SHAPE_TAGS = frozenset({"sp", "cxnSp", "pic", "graphicFrame", "grpSp"})

# Стандартные цвета темы PowerPoint (ECMA-376, p:clrMap → theme palette).
_THEME_COLORS = {
    "bg1": "FFFFFF",
    "tx1": "000000",
    "bg2": "E7E6E6",
    "tx2": "44546A",
    "accent1": "5B9BD5",
    "accent2": "ED7D31",
    "accent3": "A5A5A5",
    "accent4": "FFC000",
    "accent5": "4472C4",
    "accent6": "70AD47",
    "hlink": "0563C1",
    "folHlink": "954F72",
}

# Соответствие индексов a:bgRef/a:schemeClr → имя цвета темы.
_BGREF_INDEX = {
    1001: "bg1",
    1002: "tx1",
    1003: "bg2",
    1004: "tx2",
    1005: "accent1",
    1006: "accent2",
    1007: "accent3",
    1008: "accent4",
    1009: "accent5",
    1010: "accent6",
    1011: "hlink",
    1012: "folHlink",
}

_ALIGN_MAP = {
    "l": "left",
    "ctr": "center",
    "r": "right",
    "just": "justify",
    "dist": "justify",
}

# Имена локальных элементов OMML, размещаемых внутри <a:p>.
_OMATH_TAGS = frozenset({"oMath", "oMathPara", "m"})


def _a(local: str) -> str:
    return f"{{{_A_NS}}}{local}"


def _p(local: str) -> str:
    return f"{{{_P_NS}}}{local}"


def _m(local: str) -> str:
    return f"{{{_M_NS}}}{local}"


def _c(local: str) -> str:
    return f"{{{_C_NS}}}{local}"


def _local_name(element) -> str:
    return element.tag.split("}")[-1]


def _emu_to_pt(value: Optional[float]) -> float:
    return (value or 0.0) / EMU_PER_PT


@dataclass(frozen=True)
class _Transform:
    """Отображение координат пространства фигуры в абсолютные EMU."""

    ox: float = 0.0
    oy: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    rotation: float = 0.0


@dataclass
class _ImporterState:
    """Состояние импорта: ресурсы и индекс слайда."""

    model: DocumentModel
    slide_index: int = 0
    layout_element: Optional[Any] = None
    master_element: Optional[Any] = None

    def add_image_resource(self, media_type: str, data: bytes, filename: str | None) -> str:
        resource_id = f"slide{self.slide_index}_img{len(self.model.resources) + 1}"
        self.model.add_resource(
            Resource(
                id=resource_id,
                kind=ResourceKind.RASTER_IMAGE,
                media_type=media_type,
                data=data,
                filename=filename,
            )
        )
        return resource_id


@dataclass
class _LevelDefaults:
    """Стиль уровня из ``p:txStyles`` (layout/master) для placeholder-текста."""

    alignment: str | None = None
    style: TextStyle | None = None


_PLACEHOLDER_CATEGORY = {
    "title": "title",
    "ctrTitle": "title",
    "subTitle": "title",
    "body": "body",
    "sldNum": "body",
    "dt": "body",
    "ftr": "body",
    "hdr": "body",
    "pic": "body",
}


def _placeholder_info(element) -> Optional[tuple[str, str]]:
    ph = element.find(f".//{_p('ph')}")
    if ph is None:
        return None
    return ph.get("type", "body"), ph.get("idx", "0")


def _placeholder_category(ph_type: str) -> str:
    return _PLACEHOLDER_CATEGORY.get(ph_type, "other")


def _walk_layout_placeholder(
    sp_tree, transform: _Transform, ph_type: str, ph_idx: str
) -> Optional[tuple[float, float, float, float, float]]:
    """Найти в spTree placeholder с подходящим типом/idx и вернуть его xfrm в EMU."""
    for child in sp_tree:
        tag = _local_name(child)
        if tag == "grpSp":
            result = _walk_layout_placeholder(child, _group_child_transform(child, transform), ph_type, ph_idx)
            if result is not None:
                return result
        elif tag == "sp":
            ph = _placeholder_info(child)
            if ph is None or ph[0] != ph_type or ph[1] != ph_idx:
                continue
            xfrm = _shape_xfrm(child)
            if xfrm is None:
                continue
            left, top, width, height = _apply_transform(transform, *xfrm[:4])
            return (left, top, width, height, transform.rotation + xfrm[4])
    return None


def _placeholder_geometry(element, state: _ImporterState) -> Optional[tuple[float, float, float, float, float]]:
    """Вернуть xfrm placeholder из slide → layout → master (в EMU)."""
    ph = _placeholder_info(element)
    if ph is None:
        return None
    for sp_tree in (state.layout_element, state.master_element):
        if sp_tree is None:
            continue
        result = _walk_layout_placeholder(sp_tree, _Transform(), ph[0], ph[1])
        if result is not None:
            return result
    return None


def _merge_tx_styles(element, context: dict[str, dict[int, _LevelDefaults]]) -> None:
    """Наложить стили уровней из ``p:txStyles`` (title/body/other) на контекст."""
    tx_styles = element.find(_p("txStyles"))
    if tx_styles is None:
        return
    for category, tag in (("title", "titleStyle"), ("body", "bodyStyle"), ("other", "otherStyle")):
        style_el = tx_styles.find(_p(tag))
        if style_el is None:
            continue
        for level in range(1, 6):
            lvl_el = style_el.find(_a(f"lvl{level}pPr"))
            if lvl_el is None:
                continue
            defaults = context.setdefault(category, {}).setdefault(level, _LevelDefaults())
            if defaults.alignment is None:
                align = lvl_el.get("algn")
                if align:
                    defaults.alignment = _ALIGN_MAP.get(align, align)
            if defaults.style is None or not _style_is_set(defaults.style):
                def_rpr = lvl_el.find(_a("defRPr"))
                if def_rpr is not None:
                    defaults.style = _run_style(def_rpr)


def _style_is_set(style: TextStyle) -> bool:
    return any(
        (
            style.font_family,
            style.font_size,
            style.bold is not None,
            style.italic is not None,
            style.underline is not None,
            style.color,
        )
    )


def _slide_style_context(slide) -> dict[str, dict[int, _LevelDefaults]]:
    """Собрать контекст стилей placeholder из layout и master (layout приоритетнее)."""
    context: dict[str, dict[int, _LevelDefaults]] = {}
    try:
        layout = slide.slide_layout
    except Exception:  # noqa: BLE001
        return context
    if layout is None:
        return context
    _merge_tx_styles(layout._element, context)
    try:
        master = layout.slide_master
    except Exception:  # noqa: BLE001
        master = None
    if master is not None:
        _merge_tx_styles(master._element, context)
    return context


def _level_defaults(style_context, category: str | None, level: int) -> Optional[_LevelDefaults]:
    if category is None:
        return None
    return (style_context.get(category) or {}).get(max(1, min(5, level + 1)))


def read_pptx(path: Union[str, Path], *, include_tables: bool = True) -> Text:
    """Достать плоский текст презентации: все текстовые кадры всех слайдов.

    Возвращает ``Text`` с блоками-параграфами и (опционально) таблицами.
    """
    from pptx import Presentation  # type: ignore[import-not-found]

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    presentation = Presentation(str(source))
    blocks: list[Block] = []
    tables: list[Table] = []
    plain: list[str] = []

    for slide_index, slide in enumerate(presentation.slides, start=1):
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    blocks.append(Block(type=BlockType.PARAGRAPH, text=text, page=slide_index))
                    plain.append(text)
            if include_tables and getattr(shape, "has_table", False) and shape.has_table:
                rows: list[list[str]] = []
                for row in shape.table.rows:
                    cells = [cell.text_frame.text for cell in row.cells]
                    rows.append(cells)
                    plain.append(" | ".join(cells))
                tables.append(Table(rows=rows, page=slide_index))

    return Text(
        blocks=blocks,
        tables=tables,
        plain="\n".join(plain),
        source_format=DocFormat.PPTX,
        engine="python-pptx",
        pages=len(presentation.slides),
    )


def read_pptx_model(
    path: Union[str, Path],
    *,
    mode: ConversionMode = ConversionMode.BALANCED,
) -> DocumentModel:
    """Импортировать PPTX в богатую модель: слайды → секции, фигуры → блоки.

    Структура модели:
      * каждая секция — слайд с ``PageSettings`` из размера слайда;
      * текстовые кадры — ``Paragraph`` с раннерами и формулами OMML;
      * картинки — ``Image`` + ресурс с байтами;
      * таблицы — ``Table``; группы фигур — плоские блоки;
      * автофигуры/коннекторы — ``Paragraph`` с ``properties["pptx"]["shape"]``;
      * диаграммы — ``Paragraph`` с данными диаграммы в ``properties``;
      * фон и заметки докладчика — в ``section.properties``.
    """
    from pptx import Presentation  # type: ignore[import-not-found]

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    presentation = Presentation(str(source))
    model = DocumentModel(
        mode=mode,
        source_format=DocFormat.PPTX.value,
        metadata=_presentation_metadata(presentation, source),
    )
    slide_width = _emu_to_pt(presentation.slide_width)
    slide_height = _emu_to_pt(presentation.slide_height)
    # PPTX geometry is expressed from the physical slide origin. Document-like
    # default margins would shift every absolutely positioned shape in HTML/PDF.
    page = PageSettings(
        width=Length(slide_width),
        height=Length(slide_height),
        margin_top=Length(0),
        margin_right=Length(0),
        margin_bottom=Length(0),
        margin_left=Length(0),
    )

    state = _ImporterState(model=model)
    for slide_index, slide in enumerate(presentation.slides, start=1):
        state.slide_index = slide_index
        state.layout_element = _layout_sp_tree(slide)
        state.master_element = _master_sp_tree(slide)
        blocks: list[Any] = []
        style_context = _slide_style_context(slide)
        sp_tree = _slide_sp_tree(slide)
        if sp_tree is not None:
            _collect_sp_tree(sp_tree, slide.part, state, blocks, _Transform(), style_context)
        section = Section(blocks=blocks, page=page)
        background = _background_fill(slide)
        if background is not None:
            section.properties["background_fill"] = background
        notes = _slide_notes(slide)
        if notes:
            section.properties["notes"] = notes
        section.properties["slide_number"] = slide_index
        model.sections.append(section)

    return model


def _slide_sp_tree(slide):
    c_sld = slide._element.find(_p("cSld"))
    if c_sld is None:
        return None
    return c_sld.find(_p("spTree"))


def _layout_sp_tree(slide):
    try:
        layout = slide.slide_layout
    except Exception:  # noqa: BLE001
        return None
    if layout is None:
        return None
    return layout._element.find(f".//{_p('spTree')}")


def _master_sp_tree(slide):
    try:
        layout = slide.slide_layout
        master = layout.slide_master
    except Exception:  # noqa: BLE001
        return None
    if master is None:
        return None
    return master._element.find(f".//{_p('spTree')}")


def _collect_sp_tree(sp_tree, slide_part, state: _ImporterState, blocks: list[Any], transform: _Transform, style_context) -> None:
    for child in sp_tree:
        tag = _local_name(child)
        if tag == "AlternateContent":
            _collect_alternate_content(child, slide_part, state, blocks, transform, style_context)
        elif tag in _SHAPE_TAGS:
            _collect_shape_element(child, slide_part, state, blocks, transform, style_context)


def _collect_shape_element(
    element, slide_part, state: _ImporterState, blocks: list[Any], transform: _Transform, style_context
) -> None:
    tag = _local_name(element)
    if tag == "grpSp":
        _collect_sp_tree(element, slide_part, state, blocks, _group_child_transform(element, transform), style_context)
        return
    xfrm = _shape_xfrm(element)
    if xfrm is None:
        xfrm = _placeholder_geometry(element, state)
    if xfrm is None:
        return
    left, top, width, height = _apply_transform(transform, *xfrm[:4])
    if width <= 0 or height <= 0:
        return
    box = Box(
        x=_emu_to_pt(left),
        y=_emu_to_pt(top),
        width=_emu_to_pt(width),
        height=_emu_to_pt(height),
        rotation=transform.rotation + xfrm[4],
    )
    if tag == "sp":
        _handle_text_shape(element, slide_part, state, blocks, box, style_context)
    elif tag == "cxnSp":
        blocks.append(_shape_paragraph_from_element(element, box, slide_part))
    elif tag == "pic":
        _handle_picture(element, slide_part, state, blocks, box)
    elif tag == "graphicFrame":
        _handle_graphic_frame(element, slide_part, state, blocks, box)


def _collect_alternate_content(
    element, slide_part, state: _ImporterState, blocks: list[Any], transform: _Transform, style_context
) -> None:
    choice = element.find(f"{{{_MC_NS}}}Choice")
    if choice is None:
        return
    for child in choice:
        if _local_name(child) in _SHAPE_TAGS:
            _collect_shape_element(child, slide_part, state, blocks, transform, style_context)


def _apply_transform(transform: _Transform, x: float, y: float, cx: float, cy: float) -> tuple[float, float, float, float]:
    return transform.ox + x * transform.sx, transform.oy + y * transform.sy, cx * transform.sx, cy * transform.sy


def _shape_xfrm(element) -> Optional[tuple[float, float, float, float, float]]:
    """Вернуть (x, y, cx, cy, rot) фигуры в EMU из XML."""
    xfrm = None
    tag = _local_name(element)
    if tag == "graphicFrame":
        xfrm = element.find(_p("xfrm"))
    else:
        sp_pr = element.find(_p("spPr"))
        if sp_pr is not None:
            xfrm = sp_pr.find(_a("xfrm"))
    if xfrm is None:
        return None
    off = xfrm.find(_a("off"))
    ext = xfrm.find(_a("ext"))
    if off is None or ext is None:
        return None
    return (
        float(off.get("x", 0)),
        float(off.get("y", 0)),
        float(ext.get("cx", 0)),
        float(ext.get("cy", 0)),
        float(xfrm.get("rot", 0)) / 60000.0,
    )


def _group_child_transform(group_element, parent: _Transform) -> _Transform:
    """Посчитать трансформацию дочерних фигур группы.

    Дочерние координаты заданы в пространстве chOff..chExt; масштаб
    пересчитывается в размер ext группы. Если chOff/chExt отсутствуют,
    дочерние координаты считаются абсолютными в пространстве страницы.
    """
    grp_pr = group_element.find(_p("grpSpPr"))
    xfrm = grp_pr.find(_a("xfrm")) if grp_pr is not None else None
    if xfrm is None:
        return parent
    off = xfrm.find(_a("off"))
    ext = xfrm.find(_a("ext"))
    ch_off = xfrm.find(_a("chOff"))
    ch_ext = xfrm.find(_a("chExt"))
    if ch_off is None or ch_ext is None or off is None or ext is None:
        return parent
    gx = float(off.get("x", 0))
    gy = float(off.get("y", 0))
    gcx = float(ext.get("cx", 1))
    gcy = float(ext.get("cy", 1))
    cox = float(ch_off.get("x", 0))
    coy = float(ch_off.get("y", 0))
    ccx = float(ch_ext.get("cx", gcx))
    ccy = float(ch_ext.get("cy", gcy))
    sx = gcx / ccx if ccx else 1.0
    sy = gcy / ccy if ccy else 1.0
    rotation = parent.rotation + (float(xfrm.get("rot", 0)) / 60000.0)
    # Абсолютная точка = точка группы + (child - chOff) * масштаб.
    ox = parent.ox + gx * parent.sx - cox * parent.sx * sx
    oy = parent.oy + gy * parent.sy - coy * parent.sy * sy
    return _Transform(ox=ox, oy=oy, sx=parent.sx * sx, sy=parent.sy * sy, rotation=rotation)


def _handle_text_shape(element, slide_part, state: _ImporterState, blocks: list[Any], box: Box, style_context=None) -> None:
    tx_body = element.find(_p("txBody"))
    paragraphs = tx_body.findall(_a("p")) if tx_body is not None else []
    shape_meta = _shape_metadata(element, box)
    ph = _placeholder_info(element)
    category = _placeholder_category(ph[0]) if ph else None
    content: list[Any] = []
    paras_meta: list[dict[str, Any]] = []
    for index, p_el in enumerate(paragraphs):
        meta = _paragraph_metadata(p_el)
        defaults = _level_defaults(style_context, category, int(meta.get("level", 0)))
        if defaults is not None:
            if meta.get("alignment") is None and defaults.alignment:
                meta["alignment"] = defaults.alignment
            if defaults.style is not None and defaults.style.font_size:
                meta["default_font_size_pt"] = defaults.style.font_size.pt
        paras_meta.append(meta)
        inherited = defaults.style if defaults is not None else None
        _append_paragraph_runs(p_el, content, slide_part, inherited)
        if index < len(paragraphs) - 1:
            content.append(TextRun(text="\n"))
    alignment = paras_meta[0].get("alignment") if paras_meta else None
    has_visual = shape_meta is not None and (shape_meta.get("fill") not in (None, "none") or shape_meta.get("line"))
    if not content and not has_visual:
        return
    properties: dict[str, Any] = {}
    if shape_meta is not None:
        properties["pptx"] = {"shape": shape_meta, "paragraphs": paras_meta}
    else:
        properties["pptx"] = {"paragraphs": paras_meta}
    blocks.append(Paragraph(content=content, box=box, alignment=alignment, properties=properties))


def _shape_paragraph_from_element(element, box: Box, slide_part) -> Paragraph:
    tx_body = element.find(_p("txBody"))
    content: list[Any] = []
    if tx_body is not None:
        paragraphs = tx_body.findall(_a("p"))
        for index, p_el in enumerate(paragraphs):
            _append_paragraph_runs(p_el, content, slide_part)
            if index < len(paragraphs) - 1:
                content.append(TextRun(text="\n"))
    return Paragraph(content=content, box=box, properties={"pptx": {"shape": _shape_metadata(element, box)}})


def _append_paragraph_runs(p_el, content: list[Any], slide_part, inherited: Optional[TextStyle] = None) -> None:
    for child in p_el:
        tag = _local_name(child)
        if tag == "r":
            run = _parse_run(child, slide_part, inherited)
            if run is not None and (run.text or run.link):
                content.append(run)
        elif tag == "br":
            content.append(TextRun(text="\n"))
        elif tag in _OMATH_TAGS:
            formula = _parse_omml(child)
            if formula is not None:
                content.append(formula)
        elif tag == "fld":
            text = "".join(t.text or "" for t in child.iter(_a("t")))
            if text:
                content.append(TextRun(text=text))
        elif tag == "t":
            if child.text:
                content.append(TextRun(text=child.text))


def _parse_run(r_el, slide_part, inherited: Optional[TextStyle] = None) -> Optional[TextRun]:
    text = "".join(t.text or "" for t in r_el.findall(_a("t")))
    r_pr = r_el.find(_a("rPr"))
    style = _run_style(r_pr) if r_pr is not None else (inherited or TextStyle())
    link = None
    if r_pr is not None:
        link_el = r_pr.find(_a("hlinkClick"))
        if link_el is not None:
            r_id = link_el.get(f"{{{_R_NS}}}id")
            link = _resolve_hyperlink(slide_part, r_id) if r_id else None
    return TextRun(text=text, style=style, link=link)


def _resolve_hyperlink(slide_part, r_id: str) -> Optional[str]:
    try:
        rel = slide_part.rels[r_id]
    except (KeyError, AttributeError):
        return None
    if getattr(rel, "is_external", False):
        return getattr(rel, "target_ref", None)
    return None


def _run_style(r_pr) -> TextStyle:
    style = TextStyle()
    if r_pr is None:
        return style
    font = r_pr.find(_a("latin"))
    if font is not None and font.get("typeface"):
        style.font_family = font.get("typeface")
    size = r_pr.get("sz")
    if size:
        style.font_size = Length(float(size) / 100.0)
    style.bold = _attr_bool(r_pr, "b")
    style.italic = _attr_bool(r_pr, "i")
    underline = r_pr.get("u")
    if underline is not None:
        style.underline = underline not in ("none",)
    baseline = r_pr.get("baseline")
    if baseline is not None:
        base_val = int(baseline)
        if base_val > 0:
            style.superscript = True
        elif base_val < 0:
            style.subscript = True
    color = _color_from_rpr(r_pr)
    if color is not None:
        style.color = color
    lang = r_pr.get("lang")
    if lang:
        style.language = lang
    return style


def _attr_bool(r_pr, tag: str) -> Optional[bool]:
    value = r_pr.get(tag)
    if value is None:
        return None
    return value not in ("0", "false")


def _color_from_rpr(r_pr) -> Optional[str]:
    solid = r_pr.find(_a("solidFill"))
    return _resolve_color_node(solid) if solid is not None else None


def _resolve_color_node(node) -> Optional[str]:
    """Разрешить a:srgbClr / a:schemeClr / a:sysClr в #RRGGBB."""
    if node is None:
        return None
    srgb = node.find(_a("srgbClr"))
    if srgb is not None:
        return "#" + (srgb.get("val") or "").upper()
    scheme = node.find(_a("schemeClr"))
    if scheme is not None:
        base = _THEME_COLORS.get(scheme.get("val") or "")
        if base is None:
            return None
        return "#" + base
    sys_clr = node.find(_a("sysClr"))
    if sys_clr is not None:
        last = sys_clr.get("lastClr")
        if last:
            return "#" + last.upper()
    return None


def _parse_omml(m_el) -> Optional[Formula]:
    omath = m_el.find(f".//{_m('oMath')}")
    target = omath if omath is not None else m_el
    try:
        xml = etree.tostring(target, encoding="unicode")
    except Exception:  # noqa: BLE001
        return None
    fallback = "".join(t.text or "" for t in target.iter(_m("t")))
    return Formula(value=xml, format=FormulaFormat.OMML, fallback_text=fallback, display=False)


def _paragraph_metadata(p_el) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    p_pr = p_el.find(_a("pPr"))
    if p_pr is None:
        return meta
    align = p_pr.get("algn")
    if align:
        meta["alignment"] = _ALIGN_MAP.get(align, align)
    for attr, target in (("marL", "marL"), ("marR", "marR"), ("indent", "indent")):
        value = p_pr.get(attr)
        if value is not None:
            meta[target] = _emu_to_pt(float(value))
    level = p_pr.get("lvl")
    if level:
        meta["level"] = int(level)
    spc_bef = p_pr.find(_a("spcBef"))
    if spc_bef is not None and spc_bef.find(_a("spcPts")) is not None:
        meta["space_before_pt"] = float(spc_bef.find(_a("spcPts")).get("val", 0)) / 100.0
    spc_aft = p_pr.find(_a("spcAft"))
    if spc_aft is not None and spc_aft.find(_a("spcPts")) is not None:
        meta["space_after_pt"] = float(spc_aft.find(_a("spcPts")).get("val", 0)) / 100.0
    ln_spc = p_pr.find(_a("lnSpc"))
    if ln_spc is not None and ln_spc.find(_a("spcPct")) is not None:
        meta["line_spacing_pct"] = float(ln_spc.find(_a("spcPct")).get("val", 100)) / 100000.0
    bullet = p_pr.find(_a("buChar"))
    if bullet is not None:
        meta["bullet_char"] = bullet.get("char")
    auto_num = p_pr.find(_a("buAutoNum"))
    if auto_num is not None:
        meta["numbered"] = auto_num.get("type")
    return meta


def _shape_metadata(element, box: Box) -> Optional[dict[str, Any]]:
    """Метаданные автофигуры/коннектора для faithful-рендера."""
    tag = _local_name(element)
    if tag not in ("sp", "cxnSp"):
        return None
    sp_pr = element.find(_p("spPr"))
    meta: dict[str, Any] = {"kind": "cxnSp" if tag == "cxnSp" else "sp"}
    if sp_pr is not None:
        prst = sp_pr.find(_a("prstGeom"))
        if prst is not None:
            meta["prst"] = prst.get("prst")
        fill = _shape_fill(sp_pr)
        if fill is not None:
            meta["fill"] = fill
        line = _shape_line(sp_pr)
        if line is not None:
            meta["line"] = line
    meta["box"] = {
        "x": box.x,
        "y": box.y,
        "width": box.width,
        "height": box.height,
        "rotation": box.rotation,
    }
    return meta


def _shape_fill(sp_pr) -> Optional[str]:
    fill = sp_pr.find(_a("solidFill"))
    if fill is not None:
        return _resolve_color_node(fill)
    if sp_pr.find(_a("noFill")) is not None:
        return "none"
    grad = sp_pr.find(_a("gradFill"))
    if grad is not None:
        stops = grad.findall(_a("gs"))
        if stops:
            color = _resolve_color_node(stops[-1])
            if color is not None:
                return color
    if sp_pr.find(_a("blipFill")) is not None:
        return "blip"
    return None


def _shape_line(sp_pr) -> Optional[dict[str, Any]]:
    line = sp_pr.find(_a("ln"))
    if line is None:
        return None
    meta: dict[str, Any] = {}
    width = line.get("w")
    if width is not None:
        meta["width"] = float(width) / 12700.0
    fill = line.find(_a("solidFill"))
    if fill is not None:
        color = _resolve_color_node(fill)
        if color is not None:
            meta["color"] = color
    return meta


def _handle_picture(element, slide_part, state: _ImporterState, blocks: list[Any], box: Box) -> None:
    blip_fill = element.find(_p("blipFill"))
    blip = blip_fill.find(_a("blip")) if blip_fill is not None else None
    if blip is None:
        return
    c_nv_pr = element.find(_p("nvPicPr"))
    alt_text = ""
    if c_nv_pr is not None:
        c_nv_pr = c_nv_pr.find(_p("cNvPr"))
        if c_nv_pr is not None:
            alt_text = c_nv_pr.get("descr", "") or ""
    r_id = blip.get(f"{{{_R_NS}}}embed") or blip.get(f"{{{_R_NS}}}link")
    if r_id is None:
        return
    part = _related_part(slide_part, r_id)
    if part is None:
        return
    resource_id = state.add_image_resource(
        media_type=part.content_type or "image/png",
        data=part.blob,
        filename=_part_filename(part),
    )
    blocks.append(Image(resource_id=resource_id, alt_text=alt_text, box=box))


def _part_filename(part) -> str | None:
    try:
        return part.partname
    except Exception:  # noqa: BLE001
        return None


def _related_part(slide_part, r_id: str):
    try:
        return slide_part.related_part(r_id)
    except Exception:  # noqa: BLE001
        return None


def _handle_graphic_frame(element, slide_part, state: _ImporterState, blocks: list[Any], box: Box) -> None:
    table = element.find(f".//{_a('tbl')}")
    if table is not None:
        blocks.append(_table_block(table, box))
        return
    graphic_data = element.find(f".//{_a('graphicData')}")
    if graphic_data is not None:
        chart_el = graphic_data.find(_c("chart"))
        if chart_el is not None:
            blocks.append(_chart_block(chart_el, slide_part, box))
            return
    blip = element.find(f".//{_a('blip')}")
    if blip is not None:
        r_id = blip.get(f"{{{_R_NS}}}embed")
        if r_id:
            part = _related_part(slide_part, r_id)
            if part is not None and part.blob:
                resource_id = state.add_image_resource(
                    media_type=part.content_type or "image/png",
                    data=part.blob,
                    filename=_part_filename(part),
                )
                blocks.append(Image(resource_id=resource_id, alt_text="", box=box))
                return
    blocks.append(Paragraph(content=[], box=box, properties={"pptx": {"shape": {"kind": "graphicFrame"}}}))


def _chart_block(chart_el, slide_part, box: Box) -> Paragraph:
    r_id = chart_el.get(f"{{{_R_NS}}}id")
    chart_data = _read_chart_data(slide_part, r_id) if r_id else {}
    fallback_text = _chart_summary(chart_data)
    content = [TextRun(text=fallback_text)] if fallback_text else []
    return Paragraph(content=content, box=box, properties={"pptx": {"shape": {"kind": "chart"}, "chart": chart_data}})


def _read_chart_data(slide_part, r_id: str) -> dict[str, Any]:
    """Прочитать данные диаграммы из её part (заголовок, категории, серии)."""
    part = _related_part(slide_part, r_id)
    if part is None:
        return {}
    try:
        root = etree.fromstring(part.blob)
    except etree.XMLSyntaxError:
        return {}
    chart = root.find(_c("chart"))
    if chart is None:
        return {}
    data: dict[str, Any] = {}
    title_el = chart.find(_c("title"))
    if title_el is not None:
        values = _pt_values(title_el)
        if values:
            data["title"] = values[0]
    plot_area = chart.find(_c("plotArea"))
    if plot_area is not None:
        chart_type = None
        for child in plot_area:
            tag = _local_name(child)
            if tag.endswith("Chart"):
                chart_type = tag
                break
        data["chart_type"] = chart_type
        series: list[dict[str, Any]] = []
        categories: list[str] = []
        for ser in plot_area.iter(_c("ser")):
            tx = ser.find(_c("tx"))
            name = _pt_values(tx)[0] if tx is not None and _pt_values(tx) else ""
            cat = ser.find(_c("cat"))
            if cat is not None:
                cats = _pt_values(cat)
                if not categories:
                    categories = cats
            val = ser.find(_c("val"))
            values = _pt_values(val) if val is not None else []
            series.append({"name": name, "values": values})
        if categories:
            data["categories"] = categories
        if series:
            data["series"] = series
    return data


def _pt_values(node) -> list[str]:
    return [value.text for value in node.iter(_c("v")) if value.text is not None]


def _chart_summary(chart_data: dict[str, Any]) -> str:
    """Краткое текстовое представление данных диаграммы (для доступности)."""
    categories = chart_data.get("categories") or []
    series = chart_data.get("series") or []
    title = chart_data.get("title") or ""
    lines: list[str] = []
    if title:
        lines.append(f"[{chart_data.get('chart_type') or 'chart'}] {title}")
    if not series:
        return "\n".join(lines)
    header = ["Category"] + [str(s["name"]) for s in series]
    lines.append("\t".join(header))
    for index, category in enumerate(categories):
        row = [str(category)]
        for s in series:
            values = s.get("values") or []
            row.append(str(values[index]) if index < len(values) else "")
        lines.append("\t".join(row))
    return "\n".join(lines)


def _table_block(table_el, box: Box) -> RichTable:
    rows: list[TableRow] = []
    for tr in table_el.findall(_a("tr")):
        cells: list[TableCell] = []
        for tc in tr.findall(_a("tc")):
            cell_text = _cell_text(tc)
            grid_span = int(tc.get("gridSpan", 1) or 1)
            row_span = int(tc.get("rowSpan", 1) or 1)
            cell = TableCell(
                blocks=[Paragraph(content=[TextRun(text=cell_text)])],
                row_span=row_span,
                column_span=grid_span,
            )
            cells.append(cell)
        rows.append(TableRow(cells=cells))
    properties: dict[str, Any] = {}
    grid = table_el.find(_a("tblGrid"))
    if grid is not None:
        widths = [float(gc.get("w", 0)) / EMU_PER_PT for gc in grid.findall(_a("gridCol"))]
        properties["column_widths_pt"] = widths
    return RichTable(rows=rows, box=box, properties=properties)


def _cell_text(tc) -> str:
    parts: list[str] = []
    for p_el in tc.findall(f".//{_a('p')}"):
        text = "".join(t.text or "" for t in p_el.iter(_a("t")))
        parts.append(text)
    return "\n".join(part for part in parts if part)


def _background_fill(slide) -> Optional[str]:
    c_sld = slide._element.find(_p("cSld"))
    bg = c_sld.find(_p("bg")) if c_sld is not None else None
    if bg is None:
        return None
    bg_ref = bg.find(_a("bgRef"))
    if bg_ref is not None:
        index = int(bg_ref.get("idx", 0) or 0)
        name = _BGREF_INDEX.get(index)
        if name is not None:
            return "#" + _THEME_COLORS[name]
        resolved = _resolve_color_node(bg_ref)
        if resolved:
            return resolved
    bg_pr = bg.find(_p("bgPr"))
    if bg_pr is not None:
        solid = bg_pr.find(_a("solidFill"))
        if solid is not None:
            return _resolve_color_node(solid)
        grad = bg_pr.find(_a("gradFill"))
        if grad is not None:
            stops = grad.findall(_a("gs"))
            if stops:
                return _resolve_color_node(stops[0])
    return None


def _slide_notes(slide) -> str:
    try:
        if not slide.has_notes_slide:
            return ""
        notes = slide.notes_slide.notes_text_frame.text or ""
        return notes.strip()
    except Exception:  # noqa: BLE001
        return ""


def _presentation_metadata(presentation, source: Path) -> dict[str, Any]:
    props = presentation.core_properties
    return {
        "title": props.title or "",
        "subject": props.subject or "",
        "author": props.author or "",
        "keywords": props.keywords or "",
        "comments": props.comments or "",
        "created": props.created.isoformat() if props.created else None,
        "modified": props.modified.isoformat() if props.modified else None,
        "source_name": source.name,
        "slide_width_pt": _emu_to_pt(presentation.slide_width),
        "slide_height_pt": _emu_to_pt(presentation.slide_height),
    }


__all__ = ["read_pptx", "read_pptx_model"]
