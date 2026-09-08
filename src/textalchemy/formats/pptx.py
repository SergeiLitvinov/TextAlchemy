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

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

try:
    from lxml import etree  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - python-pptx тянет lxml транзитивно
    etree = None  # type: ignore[assignment]

from textalchemy.core.color import ColorValue
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
    Provenance,
    ProvenanceEvent,
    Resource,
    ResourceKind,
    Section,
    TextRun,
    TextStyle,
)
from textalchemy.core.document_model import (
    Table as RichTable,
)
from textalchemy.core.io import check_archive_safety
from textalchemy.core.types import Block, BlockType, DocFormat, Table, Text
from textalchemy.core.units import canonical_coordinate_contract, emu_to_points, ooxml_angle_to_degrees
from textalchemy.ooxml.color import resolve_drawingml_color

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"

_SHAPE_TAGS = frozenset({"sp", "cxnSp", "pic", "graphicFrame", "grpSp"})

# Сведение 3D-типов диаграмм к базовым типам внутренней модели.
# Конус/цилиндр/пирамида кодируются через ``c:bar3DChart/c:shape``, а не
# отдельными chart-тегами.
_CHART_3D_MAP = {
    "bar3DChart": "barChart",
    "line3DChart": "lineChart",
    "area3DChart": "areaChart",
    "pie3DChart": "pieChart",
    "doughnut3DChart": "doughnutChart",
    "surfaceChart": "surfaceChart",
    "surface3DChart": "surfaceChart",
}

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
    return emu_to_points(value or 0.0)


@dataclass(frozen=True)
class _Matrix:
    """2D affine matrix using the SVG/CSS ``a,b,c,d,e,f`` convention."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def then(self, child: "_Matrix") -> "_Matrix":
        """Compose this parent matrix with a child/local matrix."""

        return _Matrix(
            a=self.a * child.a + self.c * child.b,
            b=self.b * child.a + self.d * child.b,
            c=self.a * child.c + self.c * child.d,
            d=self.b * child.c + self.d * child.d,
            e=self.a * child.e + self.c * child.f + self.e,
            f=self.b * child.e + self.d * child.f + self.f,
        )

    def point(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f


@dataclass(frozen=True)
class _Transform:
    """Mapping from a group child coordinate space to absolute slide EMU."""

    matrix: _Matrix = _Matrix()
    rotation: float = 0.0
    requires_affine: bool = False


@dataclass
class _ImporterState:
    """Состояние импорта: ресурсы и индекс слайда."""

    model: DocumentModel
    slide_index: int = 0
    layout_element: Optional[Any] = None
    master_element: Optional[Any] = None
    theme_colors: dict[str, str] | None = None

    def origin(self, *, object_id: str | None = None, package_part: str | None = None) -> Provenance:
        return Provenance(
            source_format=DocFormat.PPTX.value,
            source_path=str(self.model.metadata.get("source_path") or "") or None,
            page=self.slide_index,
            object_id=object_id,
            package_part=package_part or f"/ppt/slides/slide{self.slide_index}.xml",
            events=[ProvenanceEvent("import.pptx", "parsed OOXML slide element")],
        )

    def add_image_resource(
        self, media_type: str, data: bytes, filename: str | None, *, object_id: str | None = None
    ) -> str:
        resource_id = f"slide{self.slide_index}_img{len(self.model.resources) + 1}"
        self.model.add_resource(
            Resource(
                id=resource_id,
                kind=ResourceKind.RASTER_IMAGE,
                media_type=media_type,
                data=data,
                filename=filename,
                provenance=self.origin(object_id=object_id, package_part=filename),
            )
        )
        return resource_id


@dataclass
class _LevelDefaults:
    """Стиль уровня из ``p:txStyles`` (layout/master) для placeholder-текста."""

    alignment: str | None = None
    style: TextStyle | None = None
    paragraph: dict[str, Any] = field(default_factory=dict)


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
) -> Optional[tuple[float, float, float, float, float, bool, bool]]:
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
            return (left, top, width, height, transform.rotation + xfrm[4], xfrm[5], xfrm[6])
    return None


def _placeholder_geometry(element, state: _ImporterState) -> Optional[tuple[float, float, float, float, float, bool, bool]]:
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
    from textalchemy.formats.pptx_paragraph import merge_paragraph_settings, paragraph_properties

    tx_styles = element.find(_p("txStyles"))
    if tx_styles is None:
        return
    for category, tag in (("title", "titleStyle"), ("body", "bodyStyle"), ("other", "otherStyle")):
        style_el = tx_styles.find(_p(tag))
        if style_el is None:
            continue
        for level in range(1, 10):
            lvl_el = style_el.find(_a(f"lvl{level}pPr"))
            if lvl_el is None:
                continue
            defaults = context.setdefault(category, {}).setdefault(level, _LevelDefaults())
            defaults.paragraph = merge_paragraph_settings(paragraph_properties(lvl_el, _ALIGN_MAP), defaults.paragraph)
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
    check_archive_safety(source)
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
    check_archive_safety(source)
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
        state.theme_colors = _load_theme_colors(slide.part)
        blocks: list[Any] = []
        style_context = _slide_style_context(slide)
        sp_tree = _slide_sp_tree(slide)
        if sp_tree is not None:
            _collect_sp_tree(sp_tree, slide.part, state, blocks, _Transform(), style_context)
        section = Section(blocks=blocks, page=page, provenance=state.origin(object_id=f"slide-{slide_index}"))
        background_color = _background_color(slide, state.theme_colors)
        background = background_color.to_hex() if background_color is not None else None
        if background is not None:
            section.properties["background_fill"] = background
            section.properties["background_color"] = background_color.to_dict()
        background_gradient = _background_gradient(slide, state.theme_colors)
        if background_gradient:
            section.properties["background_gradient_colors"] = background_gradient
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
    if (width <= 0 or height <= 0) and not (tag == "cxnSp" and width >= 0 and height >= 0):
        return
    box = Box(
        x=_emu_to_pt(left),
        y=_emu_to_pt(top),
        width=_emu_to_pt(width),
        height=_emu_to_pt(height),
        rotation=transform.rotation + xfrm[4],
    )
    affine = _shape_affine_metadata(transform, xfrm)
    first_block = len(blocks)
    if tag == "sp":
        _handle_text_shape(element, slide_part, state, blocks, box, style_context)
    elif tag == "cxnSp":
        blocks.append(_shape_paragraph_from_element(element, box, slide_part, state.theme_colors))
    elif tag == "pic":
        _handle_picture(element, slide_part, state, blocks, box)
    elif tag == "graphicFrame":
        _handle_graphic_frame(element, slide_part, state, blocks, box)
    if affine is not None:
        for block in blocks[first_block:]:
            _set_pptx_affine(block, affine)
    from textalchemy.formats.pptx_geometry import remember_shape_identity

    for block in blocks[first_block:]:
        remember_shape_identity(block, element)


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
    points = (
        transform.matrix.point(x, y),
        transform.matrix.point(x + cx, y),
        transform.matrix.point(x, y + cy),
        transform.matrix.point(x + cx, y + cy),
    )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _shape_affine_metadata(
    transform: _Transform,
    xfrm: tuple[float, float, float, float, float, bool, bool],
) -> dict[str, Any] | None:
    x, y, width, height, rotation, flip_h, flip_v = xfrm
    nonuniform_parent = not _is_uniform_axis_scale(transform.matrix)
    if not (transform.requires_affine or flip_h or flip_v or (rotation and nonuniform_parent)):
        return None
    local = (
        _translate(x + width / 2, y + height / 2)
        .then(_rotation_flip(rotation, flip_h=flip_h, flip_v=flip_v))
        .then(_translate(-width / 2, -height / 2))
    )
    total = transform.matrix.then(local)
    return {
        "matrix": [total.a, total.b, total.c, total.d, _emu_to_pt(total.e), _emu_to_pt(total.f)],
        "width_pt": _emu_to_pt(width),
        "height_pt": _emu_to_pt(height),
        "rotation": transform.rotation + rotation,
        "flip_horizontal": flip_h,
        "flip_vertical": flip_v,
    }


def _set_pptx_affine(block: Any, affine: dict[str, Any]) -> None:
    properties = getattr(block, "properties", None)
    if properties is None:
        return
    pptx = properties.get("pptx")
    if not isinstance(pptx, dict):
        pptx = {}
        properties["pptx"] = pptx
    pptx["transform"] = affine


def _translate(x: float, y: float) -> _Matrix:
    return _Matrix(e=x, f=y)


def _scale(x: float, y: float) -> _Matrix:
    return _Matrix(a=x, d=y)


def _rotation_flip(rotation: float, *, flip_h: bool, flip_v: bool) -> _Matrix:
    radians = math.radians(rotation)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    horizontal = -1.0 if flip_h else 1.0
    vertical = -1.0 if flip_v else 1.0
    return _Matrix(
        a=cosine * horizontal,
        b=sine * horizontal,
        c=-sine * vertical,
        d=cosine * vertical,
    )


def _around_center(
    center_x: float,
    center_y: float,
    *,
    rotation: float,
    flip_h: bool,
    flip_v: bool,
) -> _Matrix:
    return (
        _translate(center_x, center_y)
        .then(_rotation_flip(rotation, flip_h=flip_h, flip_v=flip_v))
        .then(_translate(-center_x, -center_y))
    )


def _is_uniform_axis_scale(matrix: _Matrix) -> bool:
    return (
        math.isclose(matrix.b, 0.0, abs_tol=1e-9)
        and math.isclose(matrix.c, 0.0, abs_tol=1e-9)
        and math.isclose(abs(matrix.a), abs(matrix.d), rel_tol=1e-9, abs_tol=1e-9)
    )


def _xml_bool(value: str | None) -> bool:
    return value in {"1", "true", "on"}


def _shape_xfrm(element) -> Optional[tuple[float, float, float, float, float, bool, bool]]:
    """Return ``x, y, cx, cy, rotation, flipH, flipV`` from DrawingML."""
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
        ooxml_angle_to_degrees(float(xfrm.get("rot", 0))),
        _xml_bool(xfrm.get("flipH")),
        _xml_bool(xfrm.get("flipV")),
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
    rotation = ooxml_angle_to_degrees(float(xfrm.get("rot", 0)))
    flip_h = _xml_bool(xfrm.get("flipH"))
    flip_v = _xml_bool(xfrm.get("flipV"))
    mapping = _translate(gx, gy).then(_scale(sx, sy)).then(_translate(-cox, -coy))
    orientation = _around_center(
        gx + gcx / 2,
        gy + gcy / 2,
        rotation=rotation,
        flip_h=flip_h,
        flip_v=flip_v,
    )
    local = orientation.then(mapping)
    return _Transform(
        matrix=parent.matrix.then(local),
        rotation=parent.rotation + rotation,
        requires_affine=parent.requires_affine or bool(rotation) or flip_h or flip_v,
    )


def _handle_text_shape(element, slide_part, state: _ImporterState, blocks: list[Any], box: Box, style_context=None) -> None:
    from textalchemy.formats.pptx_paragraph import (
        frame_metadata,
        merge_paragraph_settings,
        merge_text_styles,
        paragraph_properties,
    )

    tx_body = element.find(_p("txBody"))
    paragraphs = tx_body.findall(_a("p")) if tx_body is not None else []
    shape_meta = _shape_metadata(element, box, state.theme_colors)
    ph = _placeholder_info(element)
    category = _placeholder_category(ph[0]) if ph else None
    content: list[Any] = []
    paras_meta: list[dict[str, Any]] = []
    for index, p_el in enumerate(paragraphs):
        meta = _paragraph_metadata(p_el)
        defaults = _level_defaults(style_context, category, int(meta.get("level", 0)))
        local_style = tx_body.find(f"{_a('lstStyle')}/{_a('lvl' + str(int(meta.get('level', 0)) + 1) + 'pPr')}")
        inherited_meta = defaults.paragraph if defaults is not None else {}
        inherited_meta = merge_paragraph_settings(inherited_meta, paragraph_properties(local_style, _ALIGN_MAP))
        meta = merge_paragraph_settings(inherited_meta, meta)
        if defaults is not None:
            if meta.get("alignment") is None and defaults.alignment:
                meta["alignment"] = defaults.alignment
            if defaults.style is not None and defaults.style.font_size:
                meta["default_font_size_pt"] = defaults.style.font_size.pt
        paras_meta.append(meta)
        inherited = defaults.style if defaults is not None else None
        local_rpr = local_style.find(_a("defRPr")) if local_style is not None else None
        inherited = merge_text_styles(inherited, _run_style(local_rpr, state.theme_colors))
        _append_paragraph_runs(p_el, content, slide_part, inherited, state.theme_colors)
        if index < len(paragraphs) - 1:
            content.append(TextRun(text="\n"))
    alignment = paras_meta[0].get("alignment") if paras_meta else None
    has_visual = shape_meta is not None and (
        shape_meta.get("fill") not in (None, "none") or shape_meta.get("line") or shape_meta.get("geometry_xml")
    )
    if not content and not has_visual:
        return
    properties: dict[str, Any] = {}
    if shape_meta is not None:
        properties["pptx"] = {"shape": shape_meta, "paragraphs": paras_meta}
    else:
        properties["pptx"] = {"paragraphs": paras_meta}
    properties["pptx"]["text_frame"] = frame_metadata(tx_body)
    blocks.append(
        Paragraph(
            content=content,
            box=box,
            alignment=alignment,
            properties=properties,
            provenance=state.origin(object_id=_element_object_id(element)),
        )
    )


def _shape_paragraph_from_element(element, box: Box, slide_part, theme_colors=None) -> Paragraph:
    tx_body = element.find(_p("txBody"))
    content: list[Any] = []
    if tx_body is not None:
        paragraphs = tx_body.findall(_a("p"))
        for index, p_el in enumerate(paragraphs):
            _append_paragraph_runs(p_el, content, slide_part)
            if index < len(paragraphs) - 1:
                content.append(TextRun(text="\n"))
    return Paragraph(content=content, box=box, properties={"pptx": {"shape": _shape_metadata(element, box, theme_colors)}})


def _element_object_id(element) -> str | None:
    c_nv_pr = element.find(f".//{_p('cNvPr')}")
    return c_nv_pr.get("id") if c_nv_pr is not None else None


def _append_paragraph_runs(
    p_el, content: list[Any], slide_part, inherited: Optional[TextStyle] = None, theme_colors: dict[str, str] | None = None
) -> None:
    from textalchemy.formats.pptx_paragraph import merge_text_styles

    defaults = p_el.find(f"{_a('pPr')}/{_a('defRPr')}")
    inherited = merge_text_styles(inherited, _run_style(defaults, theme_colors))
    for child in p_el:
        tag = _local_name(child)
        if tag == "r":
            run = _parse_run(child, slide_part, inherited, theme_colors)
            if run is not None and (run.text or run.link):
                content.append(run)
        elif tag == "br":
            content.append(TextRun(text="\n", properties={"pptx_break": "line"}))
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


def _parse_run(
    r_el, slide_part, inherited: Optional[TextStyle] = None, theme_colors: dict[str, str] | None = None
) -> Optional[TextRun]:
    from textalchemy.formats.pptx_paragraph import merge_text_styles

    text = "".join(t.text or "" for t in r_el.findall(_a("t")))
    r_pr = r_el.find(_a("rPr"))
    style = merge_text_styles(inherited, _run_style(r_pr, theme_colors))
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


def _run_style(r_pr, theme_colors: dict[str, str] | None = None) -> TextStyle:
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
    color, color_properties = _color_from_rpr(r_pr, theme_colors)
    if color is not None:
        style.color = color
        style.properties.update(color_properties)
    lang = r_pr.get("lang")
    if lang:
        style.language = lang
    return style


def _attr_bool(r_pr, tag: str) -> Optional[bool]:
    value = r_pr.get(tag)
    if value is None:
        return None
    return value not in ("0", "false")


def _color_from_rpr(r_pr, theme_colors: dict[str, str] | None = None) -> tuple[ColorValue | None, dict[str, Any]]:
    solid = r_pr.find(_a("solidFill"))
    return _resolve_color_value(solid, theme_colors) if solid is not None else (None, {})


def _resolve_color_value(node, theme_colors: dict[str, str] | None = None) -> tuple[ColorValue | None, dict[str, Any]]:
    """Resolve DrawingML color plus tint/shade/luminance/alpha metadata."""
    return resolve_drawingml_color(node, theme_colors or _THEME_COLORS)


def _resolve_color_node(node) -> Optional[str]:
    """Разрешить a:srgbClr / a:schemeClr / a:sysClr в #RRGGBB."""
    color, _ = _resolve_color_value(node)
    return color.to_hex() if color is not None else None


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
    from textalchemy.formats.pptx_paragraph import paragraph_metadata

    return paragraph_metadata(p_el, _ALIGN_MAP)


def _shape_metadata(element, box: Box, theme_colors: dict[str, str] | None = None) -> Optional[dict[str, Any]]:
    """Метаданные автофигуры/коннектора для faithful-рендера."""
    tag = _local_name(element)
    if tag not in ("sp", "cxnSp"):
        return None
    sp_pr = element.find(_p("spPr"))
    from textalchemy.formats.pptx_geometry import shape_geometry

    meta: dict[str, Any] = {"kind": "cxnSp" if tag == "cxnSp" else "sp", **shape_geometry(element)}
    if sp_pr is not None:
        prst = sp_pr.find(_a("prstGeom"))
        if prst is not None:
            meta["prst"] = prst.get("prst")
        fill, fill_color = _shape_fill(sp_pr, theme_colors)
        if fill is not None:
            meta["fill"] = fill
        if fill_color is not None:
            meta["fill_color"] = fill_color.to_dict()
        gradient = sp_pr.find(_a("gradFill"))
        if gradient is not None:
            stops = _gradient_colors(gradient, theme_colors)
            if stops:
                meta["gradient_colors"] = stops
        line = _shape_line(sp_pr, theme_colors)
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


def _shape_fill(sp_pr, theme_colors: dict[str, str] | None = None) -> tuple[str | None, ColorValue | None]:
    fill = sp_pr.find(_a("solidFill"))
    if fill is not None:
        color, _ = _resolve_color_value(fill, theme_colors)
        return (color.to_hex() if color else None), color
    if sp_pr.find(_a("noFill")) is not None:
        return "none", None
    grad = sp_pr.find(_a("gradFill"))
    if grad is not None:
        stops = grad.findall(f".//{_a('gs')}")
        if stops:
            color, _ = _resolve_color_value(stops[-1], theme_colors)
            if color is not None:
                return color.to_hex(), color
    if sp_pr.find(_a("blipFill")) is not None:
        return "blip", None
    return None, None


def _gradient_colors(gradient, theme_colors: dict[str, str] | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for stop in gradient.findall(f".//{_a('gs')}"):
        color, metadata = _resolve_color_value(stop, theme_colors)
        if color is None:
            continue
        position = float(stop.get("pos", 0)) / 100000.0
        result.append({"position": position, "color": color.to_dict(), "source": metadata})
    return result


def _shape_line(sp_pr, theme_colors: dict[str, str] | None = None) -> Optional[dict[str, Any]]:
    line = sp_pr.find(_a("ln"))
    if line is None:
        return None
    meta: dict[str, Any] = {}
    width = line.get("w")
    if width is not None:
        meta["width"] = emu_to_points(float(width))
    fill = line.find(_a("solidFill"))
    if fill is not None:
        color, _ = _resolve_color_value(fill, theme_colors)
        if color is not None:
            meta["color"] = color.to_hex()
            meta["stroke_color"] = color.to_dict()
    return meta


def _handle_picture(element, slide_part, state: _ImporterState, blocks: list[Any], box: Box) -> None:
    from textalchemy.formats.pptx_picture import read_picture

    picture = read_picture(element, slide_part, state, box)
    if picture is not None:
        blocks.append(picture)


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
        blocks.append(_table_block(table, box, slide_part, state.theme_colors))
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
    """Прочитать данные диаграммы из её part (заголовок, категории, серии, оси)."""
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
    theme_colors = _load_theme_colors(slide_part)
    data: dict[str, Any] = {}
    view3d = chart.find(_c("view3D"))
    if view3d is not None:
        view: dict[str, Any] = {}
        for tag, key, cast in (
            ("rotX", "rot_x", _chart_float),
            ("rotY", "rot_y", _chart_float),
            ("perspective", "perspective", _chart_float),
            ("depthPercent", "depth_percent", _chart_float),
            ("rAngAx", "right_angle_axes", _chart_bool),
        ):
            element = view3d.find(_c(tag))
            if element is not None and element.get("val") is not None:
                view[key] = cast(element.get("val"))
        if view:
            data["view3d"] = view
    for tag, key in (("sideWall", "side_wall"), ("backWall", "back_wall")):
        wall = chart.find(_c(tag))
        if wall is not None:
            wall_info = _chart_wall_floor(wall, theme_colors)
            if wall_info:
                data[key] = wall_info
    floor = chart.find(_c("floor"))
    if floor is not None:
        floor_info = _chart_wall_floor(floor, theme_colors)
        if floor_info:
            data["floor"] = floor_info
    title = _chart_element_title(chart)
    if title:
        data["title"] = title
    legend = chart.find(_c("legend"))
    if legend is not None:
        legend_position = legend.find(_c("legendPos"))
        data["legend"] = True
        if legend_position is not None and legend_position.get("val"):
            data["legend_position"] = legend_position.get("val")
    plot_area = chart.find(_c("plotArea"))
    if plot_area is not None:
        axis_elements = _collect_axes(plot_area)
        chart_nodes: list[Any] = []
        node_value_ids: list[str | None] = []
        for child in plot_area:
            tag = _local_name(child)
            if not tag.endswith("Chart"):
                continue
            chart_nodes.append(child)
            ids = [el.get("val") for el in child.findall(_c("axId")) if el.get("val")]
            node_value_ids.append(ids[1] if len(ids) > 1 else None)
        if not chart_nodes:
            data["chart_type"] = None
            return data
        primary_value_id = node_value_ids[0]
        axes = _build_axes(axis_elements, primary_value_id)
        if axes:
            data["axes"] = axes
        for tag, element, ax_id in axis_elements:
            axis_title = _chart_element_title(element)
            if not axis_title:
                continue
            if tag in {"catAx", "dateAx"}:
                data["category_axis_title"] = axis_title
            elif ax_id == (axes.get("value") or {}).get("ax_id"):
                data["value_axis_title"] = axis_title
            else:
                data["secondary_value_axis_title"] = axis_title
        if len(chart_nodes) > 1:
            data["combo_types"] = [_local_name(node) for node in chart_nodes]
        primary_tag = _local_name(chart_nodes[0])
        if primary_tag in {"scatterChart", "bubbleChart"} and len(chart_nodes) == 1:
            if "secondary_value" in axes:
                axes["x"] = axes.pop("secondary_value")
            if "value" in axes:
                axes["y"] = axes.pop("value")
        chart_node = chart_nodes[0]
        scatter_style = chart_node.find(_c("scatterStyle"))
        if scatter_style is not None:
            data["scatter_style"] = scatter_style.get("val")
        data["chart_type"] = _chart_base_type(primary_tag)
        if primary_tag != data["chart_type"]:
            data["chart_3d"] = True
            data["chart_3d_type"] = primary_tag
        data_labels = _read_data_labels(chart_node)
        if data_labels:
            data["data_labels"] = data_labels
        if chart_node is not None:
            bar_direction = chart_node.find(_c("barDir"))
            grouping = chart_node.find(_c("grouping"))
            shape = chart_node.find(_c("shape"))
            if bar_direction is not None and bar_direction.get("val"):
                data["bar_direction"] = bar_direction.get("val")
            if grouping is not None and grouping.get("val"):
                data["grouping"] = grouping.get("val")
            if shape is not None and shape.get("val"):
                data["chart_3d_shape"] = shape.get("val")
            from textalchemy.formats.pptx_chart_data import plot_appearance

            data.update(plot_appearance(chart_node))
        secondary_value_id = (axes.get("secondary_value") or {}).get("ax_id")
        series: list[dict[str, Any]] = []
        categories: list[str] = []
        for node_index, node in enumerate(chart_nodes):
            node_tag = _local_name(node)
            series_index = 0
            node_value_id = node_value_ids[node_index] if node_index < len(node_value_ids) else None
            secondary = bool(secondary_value_id) and node_value_id == secondary_value_id
            for ser in node.findall(_c("ser")):
                from textalchemy.formats.pptx_chart_data import cached_values, numeric_series, plot_settings

                tx = ser.find(_c("tx"))
                name = _pt_values(tx)[0] if tx is not None and _pt_values(tx) else ""
                cat = ser.find(_c("cat"))
                if cat is not None:
                    cats = [value if value is not None else "" for value in cached_values(cat)]
                    if not categories:
                        categories = cats
                val = ser.find(_c("val"))
                values = cached_values(val)
                item: dict[str, Any] = {"name": name, "values": values}
                item.update(numeric_series(ser))
                item["plot"], item["plot_index"] = plot_settings(node), node_index
                if node_index > 0:
                    item["plot"].update(plot_appearance(node))
                plot_labels = _read_data_labels(node)
                if plot_labels is not None and node_index > 0:
                    item["plot"]["data_labels"] = plot_labels
                if cat is not None and cats != categories:
                    item["categories"] = cats
                item["chart_type"] = _chart_base_type(node_tag)
                if secondary:
                    item["axis"] = "secondary_value"
                color_value = _chart_series_color_value(ser, theme_colors)
                if color_value is None:
                    # Без явного цвета PowerPoint берёт акцентные цвета темы по порядку.
                    accent = theme_colors.get(f"accent{series_index % 6 + 1}")
                    if accent:
                        color_value = ColorValue.from_hex("#" + accent)
                if color_value is not None:
                    item["color"] = color_value.to_hex()
                    item["color_value"] = color_value.to_dict()
                series_data_labels = _read_data_labels(ser)
                if series_data_labels:
                    item["data_labels"] = series_data_labels
                trendline = _read_trendline(ser, theme_colors)
                if trendline:
                    item["trendline"] = trendline
                error_bars = _read_error_bars(ser, theme_colors)
                if error_bars:
                    item["error_bars"] = error_bars
                data_points = _read_data_points(ser, theme_colors)
                if data_points:
                    item["data_points"] = data_points
                series.append(item)
                series_index += 1
        if categories:
            data["categories"] = categories
        if series:
            data["series"] = series
    return data


def _collect_axes(plot_area) -> list[tuple[str, Any, str | None]]:
    """Собрать все оси диаграммы с их ``axId``: (тип, элемент, axId)."""
    axes: list[tuple[str, Any, str | None]] = []
    for child in plot_area:
        tag = _local_name(child)
        if tag not in {"catAx", "dateAx", "valAx", "serAx"}:
            continue
        ax_id_element = child.find(_c("axId"))
        ax_id = ax_id_element.get("val") if ax_id_element is not None else None
        axes.append((tag, child, ax_id))
    return axes


def _build_axes(axis_elements: list[tuple[str, Any, str | None]], primary_value_id: str | None) -> dict[str, Any]:
    """Построить словарь осей, выделив первичную и вторичную оси значений."""
    axes: dict[str, Any] = {}
    category_axis: dict[str, Any] | None = None
    series_axis: dict[str, Any] | None = None
    value_axes: dict[str, Any] = {}
    for tag, element, ax_id in axis_elements:
        info = _chart_axis_info(element)
        if info is None:
            continue
        info["ax_id"] = ax_id
        if tag in {"catAx", "dateAx"}:
            if category_axis is None:
                category_axis = info
        elif tag == "serAx":
            if series_axis is None:
                series_axis = info
        elif tag == "valAx":
            key = ax_id or f"{id(element)}"
            if key not in value_axes:
                value_axes[key] = info
    if category_axis is not None:
        axes["category"] = category_axis
    if series_axis is not None:
        axes["series"] = series_axis
    if not value_axes:
        return axes
    primary_key = primary_value_id
    if primary_key not in value_axes:
        primary_key = next(iter(value_axes))
    primary_info = value_axes.pop(primary_key)
    axes["value"] = primary_info
    if value_axes:
        axes["secondary_value"] = value_axes.pop(next(iter(value_axes)))
    return axes


def _chart_base_type(tag: str) -> str:
    """Свести 3D-тип диаграммы к базовому 2D-типу."""
    return _CHART_3D_MAP.get(tag, tag)


def _load_theme_colors(slide_part) -> dict[str, str]:
    """Прочитать схему цветов темы презентации из её part.

    Возвращает словарь вида ``{"accent1": "4F81BD", ...}``; при отсутствии
    темы или ошибках — стандартную палитру PowerPoint (Office 2013+).
    """
    colors = dict(_THEME_COLORS)
    try:
        from pptx.opc.constants import RELATIONSHIP_TYPE as _RT  # type: ignore[import-not-found]

        package = slide_part.package
        presentation_part = getattr(package, "main_document_part", None)
        if presentation_part is None:
            return colors
        theme = presentation_part.part_related_by(_RT.THEME)
        if theme is None or not theme.blob:
            return colors
        root = etree.fromstring(theme.blob)
        scheme = root.find(f".//{_a('clrScheme')}")
        if scheme is None:
            return colors
        for child in scheme:
            key = _local_name(child)
            srgb = child.find(_a("srgbClr"))
            if srgb is not None:
                colors[key] = (srgb.get("val") or "").upper()
                continue
            sys_clr = child.find(_a("sysClr"))
            if sys_clr is not None:
                last = sys_clr.get("lastClr")
                if last:
                    colors[key] = last.upper()
    except Exception:  # noqa: BLE001
        pass
    return colors


def _chart_axis_info(axis) -> dict[str, Any] | None:
    """Собрать настройки оси диаграммы (scaling, единицы, формат, видимость)."""
    if axis is None:
        return None
    info: dict[str, Any] = {}
    title = _chart_element_title(axis)
    if title:
        info["title"] = title
    delete = axis.find(_c("delete"))
    if delete is not None:
        info["hidden"] = _chart_bool(delete.get("val"))
    ax_pos = axis.find(_c("axPos"))
    if ax_pos is not None and ax_pos.get("val"):
        info["position"] = ax_pos.get("val")
    scaling = axis.find(_c("scaling"))
    if scaling is not None:
        for child in scaling:
            tag = _local_name(child)
            val = child.get("val")
            if val is None:
                continue
            if tag == "min":
                info["min"] = _chart_float(val)
            elif tag == "max":
                info["max"] = _chart_float(val)
            elif tag == "autoMin":
                info["auto_min"] = _chart_bool(val)
            elif tag == "autoMax":
                info["auto_max"] = _chart_bool(val)
            elif tag == "logBase":
                info["log_base"] = _chart_float(val)
            elif tag == "orientation":
                info["reverse_order"] = val == "maxMin"
    for tag, key in (
        ("majorUnit", "major_unit"),
        ("minorUnit", "minor_unit"),
    ):
        unit = axis.find(_c(tag))
        if unit is not None and unit.get("val"):
            info[key] = _chart_float(unit.get("val"))
    num_fmt = axis.find(_c("numFmt"))
    if num_fmt is not None:
        format_code = num_fmt.get("formatCode")
        if format_code:
            info["num_format"] = format_code
            linked = (num_fmt.get("sourceLinked") or "1").lower()
            info["num_format_linked"] = linked in {"1", "true"}
    tick_label = axis.find(_c("tickLblPos"))
    if tick_label is not None and tick_label.get("val"):
        info["tick_label_position"] = tick_label.get("val")
    for tag, key in (("majorTickMark", "major_tick_mark"), ("minorTickMark", "minor_tick_mark")):
        mark = axis.find(_c(tag))
        if mark is not None and mark.get("val"):
            info[key] = mark.get("val")
    return info


def _chart_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _chart_bool(value: str | None, *, default: bool = False) -> bool:
    """Разобрать OOXML-булево значение: ``1``/``true`` — истина."""
    if value is None:
        return default
    return value.lower() in {"1", "true"}


def _read_data_labels(node) -> dict[str, Any] | None:
    """Прочитать настройки подписей данных из ``c:dLbls``."""
    if node is None:
        return None
    labels = node.find(_c("dLbls"))
    if labels is None:
        return None
    info: dict[str, Any] = {}
    show = {
        "showLegendKey": "show_legend_key",
        "showVal": "show_value",
        "showCatName": "show_category",
        "showSerName": "show_series",
        "showPercent": "show_percent",
        "showBubbleSize": "show_bubble_size",
        "showLeaderLines": "show_leader_lines",
        "delete": "hidden",
    }
    for tag, key in show.items():
        element = labels.find(_c(tag))
        if element is None:
            continue
        info[key] = _chart_bool(element.get("val"))
    num_fmt = labels.find(_c("numFmt"))
    if num_fmt is not None and num_fmt.get("formatCode"):
        info["num_format"] = num_fmt.get("formatCode")
        info["num_format_linked"] = _chart_bool(num_fmt.get("sourceLinked"), default=True)
    position = labels.find(_c("dLblPos"))
    if position is not None and position.get("val"):
        info["position"] = position.get("val")
    separator = labels.find(_c("separator"))
    if separator is not None:
        info["separator"] = separator.get("val", separator.text or "")
    return info or None


def _chart_element_title(element) -> str | None:
    if element is None:
        return None
    title = element.find(_c("title"))
    values = _pt_values(title) if title is not None else []
    if values:
        return values[0]
    text = "".join(node.text or "" for node in title.iter(_a("t"))) if title is not None else ""
    return text or None


def _read_trendline(series, theme_colors: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Прочитать линию тренда серии (тип, порядок, период, видимость формулы/R²)."""
    trend = series.find(_c("trendline"))
    if trend is None:
        return None
    info: dict[str, Any] = {}
    trend_type = trend.find(_c("trendlineType"))
    if trend_type is not None and trend_type.get("val"):
        info["type"] = trend_type.get("val")
    for tag, key in (("order", "order"), ("period", "period")):
        element = trend.find(_c(tag))
        if element is not None and element.get("val"):
            try:
                info[key] = int(float(element.get("val")))
            except ValueError:
                pass
    for tag, key in (("dispRSqr", "show_r_squared"), ("dispEq", "show_equation")):
        element = trend.find(_c(tag))
        if element is not None:
            info[key] = _chart_bool(element.get("val"))
    color = _chart_series_color_value(trend, theme_colors)
    if color:
        info["color"] = color.to_hex()
        info["color_value"] = color.to_dict()
    return info


def _read_error_bars(series, theme_colors: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Прочитать планки погрешностей серии (тип, направление, величина)."""
    error = series.find(_c("errBars"))
    if error is None:
        return None
    info: dict[str, Any] = {}
    for tag, key in (("errDir", "direction"), ("errBarType", "bar_type"), ("errValType", "value_type")):
        element = error.find(_c(tag))
        if element is not None and element.get("val"):
            info[key] = element.get("val")
    fixed = error.find(_c("val"))
    if fixed is not None and fixed.get("val"):
        info["value"] = _chart_float(fixed.get("val"))
    for tag, key in (("yVal", "y_val"), ("plus", "plus"), ("minus", "minus")):
        values = _pt_values(error.find(_c(tag))) if error.find(_c(tag)) is not None else []
        if values:
            info[key] = values
    num_fmt = error.find(_c("numFmt"))
    if num_fmt is not None and num_fmt.get("formatCode"):
        info["num_format"] = num_fmt.get("formatCode")
    color = _chart_series_color_value(error, theme_colors)
    if color:
        info["color"] = color.to_hex()
        info["color_value"] = color.to_dict()
    return info


def _read_data_points(series, theme_colors: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Прочитать форматирование отдельных точек данных (цвет, отрыв у сектора)."""
    points: dict[str, Any] = {}
    for point in series.findall(_c("dPt")):
        idx_el = point.find(_c("idx"))
        if idx_el is None or idx_el.get("val") is None:
            continue
        try:
            index = int(float(idx_el.get("val")))
        except ValueError:
            continue
        entry: dict[str, Any] = {}
        color = _chart_series_color_value(point, theme_colors)
        if color:
            entry["color"] = color.to_hex()
            entry["color_value"] = color.to_dict()
        explosion = point.find(_c("explosion"))
        if explosion is not None and explosion.get("val"):
            entry["explosion"] = _chart_float(explosion.get("val"))
        if entry:
            points[index] = entry
    return points or None


def _chart_series_color(series, theme_colors: dict[str, str] | None = None) -> str | None:
    color = _chart_series_color_value(series, theme_colors)
    return color.to_hex() if color is not None else None


def _chart_series_color_value(series, theme_colors: dict[str, str] | None = None) -> ColorValue | None:
    shape_properties = series.find(_c("spPr"))
    if shape_properties is None:
        return None
    solid = shape_properties.find(_a("solidFill"))
    if solid is None:
        return None
    return _resolve_color_value(solid, theme_colors)[0]


def _chart_wall_floor(element, theme_colors: dict[str, str] | None = None) -> dict[str, Any]:
    """Прочитать оформление стенки/пола 3D-диаграммы: толщину и заливку."""
    info: dict[str, Any] = {}
    thickness = element.find(_c("thickness"))
    if thickness is not None and thickness.get("val") is not None:
        info["thickness"] = _chart_float(thickness.get("val"))
    shape_properties = element.find(_c("spPr"))
    solid = shape_properties.find(_a("solidFill")) if shape_properties is not None else None
    if solid is None:
        solid = element.find(_a("solidFill"))
    if solid is not None:
        color, _ = _resolve_color_value(solid, theme_colors)
        if color is not None:
            info["fill"] = color.to_hex()
            info["fill_color"] = color.to_dict()
    return info


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


def _table_block(table_el, box: Box, slide_part=None, theme_colors=None) -> RichTable:
    from textalchemy.formats.pptx_table import read_table

    return read_table(table_el, box, slide_part, theme_colors, _append_paragraph_runs, _resolve_color_value, _ALIGN_MAP)


def _cell_text(tc) -> str:
    parts: list[str] = []
    for p_el in tc.findall(f".//{_a('p')}"):
        text = "".join(t.text or "" for t in p_el.iter(_a("t")))
        parts.append(text)
    return "\n".join(part for part in parts if part)


def _background_color(slide, theme_colors: dict[str, str] | None = None) -> ColorValue | None:
    c_sld = slide._element.find(_p("cSld"))
    bg = c_sld.find(_p("bg")) if c_sld is not None else None
    if bg is None:
        return None
    bg_ref = bg.find(_a("bgRef"))
    if bg_ref is not None:
        index = int(bg_ref.get("idx", 0) or 0)
        name = _BGREF_INDEX.get(index)
        if name is not None:
            palette = theme_colors or _THEME_COLORS
            if name in palette:
                return ColorValue.from_hex("#" + palette[name])
        resolved, _ = _resolve_color_value(bg_ref, theme_colors)
        if resolved:
            return resolved
    bg_pr = bg.find(_p("bgPr"))
    if bg_pr is not None:
        solid = bg_pr.find(_a("solidFill"))
        if solid is not None:
            return _resolve_color_value(solid, theme_colors)[0]
        grad = bg_pr.find(_a("gradFill"))
        if grad is not None:
            stops = grad.findall(f".//{_a('gs')}")
            if stops:
                return _resolve_color_value(stops[0], theme_colors)[0]
    return None


def _background_gradient(slide, theme_colors: dict[str, str] | None = None) -> list[dict[str, Any]]:
    c_sld = slide._element.find(_p("cSld"))
    bg = c_sld.find(_p("bg")) if c_sld is not None else None
    bg_pr = bg.find(_p("bgPr")) if bg is not None else None
    gradient = bg_pr.find(_a("gradFill")) if bg_pr is not None else None
    return _gradient_colors(gradient, theme_colors) if gradient is not None else []


def _background_fill(slide) -> Optional[str]:
    """Compatibility wrapper returning the resolved legacy hex token."""
    color = _background_color(slide)
    return color.to_hex() if color is not None else None


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
        "source_path": str(source),
        "slide_width_pt": _emu_to_pt(presentation.slide_width),
        "slide_height_pt": _emu_to_pt(presentation.slide_height),
        "coordinate_system": canonical_coordinate_contract(),
    }


__all__ = ["read_pptx", "read_pptx_model"]
