import importlib.util
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List

from textalchemy.core.exceptions import RecognizeError


class RegionType(Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    HEADING = "heading"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    UNKNOWN = "unknown"


@dataclass
class LayoutRegion:
    x: int
    y: int
    width: int
    height: int
    type: RegionType = RegionType.UNKNOWN
    confidence: float = 0.0
    text: str = ""


class LayoutAnalyzer:
    def __init__(self):
        self._available = False
        self._pil_available = importlib.util.find_spec("PIL") is not None

    @property
    def is_available(self) -> bool:
        return self._pil_available

    def analyze(self, image_path: str | Path) -> List[LayoutRegion]:
        image_path = Path(image_path)
        if not image_path.exists():
            raise RecognizeError(f"Image not found: {image_path}")

        if not self._pil_available:
            return []

        from PIL import Image
        img = Image.open(image_path)
        width, height = img.size

        return self._analyze_basic(img, width, height)

    def _analyze_basic(self, img, width: int, height: int) -> List[LayoutRegion]:
        try:
            import numpy as np
            from PIL import ImageFilter
            edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
            edge_arr = np.array(edges)
            edge_density = np.mean(edge_arr > 128)

            has_table = edge_density > 0.15 and edge_density < 0.4
        except ImportError:
            has_table = False

        regions: List[LayoutRegion] = []

        header_h = int(height * 0.08)
        footer_h = int(height * 0.08)
        margin = int(width * 0.08)

        regions.append(LayoutRegion(0, 0, width, header_h, RegionType.HEADER, 0.5))
        regions.append(LayoutRegion(0, height - footer_h, width, footer_h, RegionType.FOOTER, 0.5))

        body_top = header_h
        body_bottom = height - footer_h
        body_height = body_bottom - body_top

        if has_table:
            table_top = body_top + int(body_height * 0.1)
            table_height = int(body_height * 0.3)
            regions.append(LayoutRegion(
                margin, table_top, width - 2 * margin, table_height,
                RegionType.TABLE, 0.4,
            ))
            text_top = table_top + table_height
            regions.append(LayoutRegion(
                margin, text_top, width - 2 * margin, body_bottom - text_top,
                RegionType.TEXT, 0.5,
            ))
        else:
            regions.append(LayoutRegion(
                margin, body_top, width - 2 * margin, body_height,
                RegionType.TEXT, 0.5,
            ))

        regions.append(LayoutRegion(
            width - margin, margin, margin // 2, margin // 2,
            RegionType.PAGE_NUMBER, 0.3,
        ))

        return regions
