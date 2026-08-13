"""Cross-platform font registry and metric-aware deterministic substitutions."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from textalchemy.core.document_model import DocumentModel, Paragraph, Table, TextRun, TextStyle


@dataclass(frozen=True)
class FontFace:
    family: str
    path: Path
    weight: int = 400
    italic: bool = False
    width_class: int = 5
    units_per_em: int = 1000
    average_width: float = 500.0
    glyphs: frozenset[int] = frozenset()
    embeddable: bool = True
    subsettable: bool = True

    @property
    def normalized_family(self) -> str:
        return _normalize_family(self.family)


@dataclass(frozen=True)
class FontResolution:
    requested: str
    resolved: str
    path: Path | None
    exact: bool
    metric_distance: float
    missing_glyphs: tuple[str, ...] = ()
    embeddable: bool = False
    subsettable: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "resolved": self.resolved,
            "path": str(self.path) if self.path else None,
            "exact": self.exact,
            "metric_distance": round(self.metric_distance, 4),
            "missing_glyphs": list(self.missing_glyphs),
            "embeddable": self.embeddable,
            "subsettable": self.subsettable,
        }


@dataclass
class FontResolutionReport:
    resolutions: dict[str, FontResolution] = field(default_factory=dict)

    @property
    def substitutions(self) -> list[FontResolution]:
        return [item for item in self.resolutions.values() if not item.exact]

    @property
    def missing_glyphs(self) -> dict[str, tuple[str, ...]]:
        return {name: item.missing_glyphs for name, item in self.resolutions.items() if item.missing_glyphs}

    def to_dict(self) -> dict[str, object]:
        return {
            "resolutions": {name: item.to_dict() for name, item in sorted(self.resolutions.items())},
            "substitution_count": len(self.substitutions),
            "fonts_with_missing_glyphs": len(self.missing_glyphs),
        }


class FontResolver:
    """Immutable registry whose ordering and tie-breaking are platform-stable."""

    def __init__(self, faces: Iterable[FontFace] = ()) -> None:
        self._faces = tuple(sorted(faces, key=lambda item: (item.normalized_family, str(item.path).casefold())))

    @classmethod
    def system(cls, search_paths: Iterable[str | Path] | None = None) -> FontResolver:
        paths = tuple(Path(path) for path in search_paths) if search_paths is not None else _system_font_paths()
        return cls(_load_faces(tuple(str(path.resolve()) for path in paths)))

    @property
    def faces(self) -> tuple[FontFace, ...]:
        return self._faces

    def resolve(self, family: str, text: str = "", *, bold: bool = False, italic: bool = False) -> FontResolution:
        requested = family.strip() or "sans-serif"
        normalized = _normalize_family(requested)
        exact_faces = [face for face in self._faces if face.normalized_family == normalized]
        candidates = exact_faces or list(self._faces)
        if not candidates:
            return FontResolution(requested, requested, None, False, 1.0, tuple(sorted(set(text))), False)
        target_weight = 700 if bold else 400
        requested_class = _generic_class(requested)

        def rank(face: FontFace) -> tuple[float, str, str]:
            metric = abs(face.weight - target_weight) / 500 + abs(face.width_class - 5) / 8
            metric += 0.35 if face.italic != italic else 0
            metric += 0.45 if requested_class != _generic_class(face.family) else 0
            coverage = _missing(face, text)
            metric += min(2.0, len(coverage) / max(1, len(set(text))))
            return metric, face.normalized_family, str(face.path).casefold()

        face = min(candidates, key=rank)
        missing = tuple(sorted(_missing(face, text)))
        return FontResolution(
            requested=requested,
            resolved=face.family,
            path=face.path,
            exact=face.normalized_family == normalized,
            metric_distance=rank(face)[0],
            missing_glyphs=missing,
            embeddable=face.embeddable,
            subsettable=face.subsettable,
        )


@lru_cache(maxsize=8)
def _load_faces(search_paths: tuple[str, ...]) -> tuple[FontFace, ...]:
    paths = tuple(Path(path) for path in search_paths)
    extensions = ("*.ttf", "*.otf")
    files = sorted(
        {file.resolve() for root in paths if root.is_dir() for pattern in extensions for file in root.rglob(pattern)},
        key=lambda item: str(item).casefold(),
    )
    return tuple(face for path in files if (face := _read_face(path)) is not None)


def prepare_document_fonts(
    document: DocumentModel,
    resolver: FontResolver | None = None,
) -> tuple[DocumentModel, FontResolutionReport]:
    """Resolve fonts in a deep copy, preserving the caller's canonical model."""
    prepared = copy.deepcopy(document)
    registry = resolver or FontResolver.system()
    report = FontResolutionReport()
    usages: dict[str, dict[str, object]] = {}

    def collect_style(style: TextStyle, text: str) -> None:
        if not style.font_family:
            return
        key = f"{style.font_family}|{int(bool(style.bold))}|{int(bool(style.italic))}"
        usage = usages.setdefault(key, {"styles": [], "style_ids": set(), "text": []})
        style_ids = usage["style_ids"]
        if isinstance(style_ids, set) and id(style) not in style_ids:
            style_ids.add(id(style))
            styles = usage["styles"]
            if isinstance(styles, list):
                styles.append(style)
        texts = usage["text"]
        if isinstance(texts, list):
            texts.append(text)

    for style in prepared.styles.values():
        collect_style(style, "")
    for section in prepared.sections:
        for collection in (
            section.headers, section.first_page_headers, section.even_page_headers, section.blocks,
            section.footers, section.first_page_footers, section.even_page_footers,
        ):
            for block in collection:
                _resolve_block_fonts(block, collect_style)

    for key, usage in sorted(usages.items()):
        styles = usage["styles"]
        texts = usage["text"]
        if not isinstance(styles, list) or not styles or not isinstance(texts, list):
            continue
        style = styles[0]
        text = "".join(str(value) for value in texts)
        resolution = registry.resolve(style.font_family or "", text, bold=bool(style.bold), italic=bool(style.italic))
        report.resolutions[key] = resolution
        for used_style in styles:
            used_style.font_family = resolution.resolved
            used_style.properties["font_resolution"] = resolution.to_dict()
    prepared.metadata["font_resolution"] = report.to_dict()
    return prepared, report


def _resolve_block_fonts(block, resolve_style) -> None:
    if isinstance(block, Paragraph):
        for item in block.content:
            if isinstance(item, TextRun):
                resolve_style(item.style, item.text)
    elif isinstance(block, Table):
        for row in block.rows:
            for cell in row.cells:
                for child in cell.blocks:
                    _resolve_block_fonts(child, resolve_style)


def _read_face(path: Path) -> FontFace | None:
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(path, lazy=True, fontNumber=0)
        names = font["name"]
        family = names.getDebugName(16) or names.getDebugName(1) or path.stem
        os2 = font.get("OS/2")
        head = font.get("head")
        glyphs = frozenset((font.getBestCmap() or {}).keys())
        fs_type = int(getattr(os2, "fsType", 0))
        face = FontFace(
            family=family,
            path=path,
            weight=int(getattr(os2, "usWeightClass", 400)),
            italic=bool(getattr(font.get("post"), "italicAngle", 0)),
            width_class=int(getattr(os2, "usWidthClass", 5)),
            units_per_em=int(getattr(head, "unitsPerEm", 1000)),
            average_width=float(getattr(os2, "xAvgCharWidth", 500) or 500),
            glyphs=glyphs,
            embeddable=not bool(fs_type & (0x0002 | 0x0200)),
            subsettable=not bool(fs_type & 0x0100),
        )
        font.close()
        return face
    except Exception:  # noqa: BLE001 - malformed/system fonts are skipped independently
        return None


def _missing(face: FontFace, text: str) -> set[str]:
    return {character for character in text if not character.isspace() and ord(character) not in face.glyphs}


def _normalize_family(name: str) -> str:
    return "".join(character for character in name.casefold() if character.isalnum())


def _generic_class(name: str) -> str:
    normalized = _normalize_family(name)
    if any(token in normalized for token in ("mono", "courier", "consol", "code")):
        return "mono"
    if any(token in normalized for token in ("serif", "times", "georgia", "cambria")) and "sans" not in normalized:
        return "serif"
    return "sans"


def _system_font_paths() -> tuple[Path, ...]:
    candidates = []
    windows = os.environ.get("WINDIR")
    if windows:
        candidates.append(Path(windows) / "Fonts")
    candidates.extend(
        (
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / "Library/Fonts",
        )
    )
    return tuple(dict.fromkeys(candidates))


__all__ = ["FontFace", "FontResolution", "FontResolutionReport", "FontResolver", "prepare_document_fonts"]
