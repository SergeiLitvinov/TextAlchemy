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

            gray = img.convert("L")
            edges = gray.filter(ImageFilter.FIND_EDGES)
            edge_arr = np.array(edges)
            edge_density = float(np.mean(edge_arr > 128))
            has_table = bool(0.15 < edge_density < 0.4)

            # Колонтитулы: считаем заполненность (dark pixels) в верхней/нижней полосах.
            margin = int(width * 0.08)
            header_h = int(height * 0.08)
            footer_h = int(height * 0.08)
            top_band = np.array(gray.crop((0, 0, width, header_h)))
            bot_band = np.array(gray.crop((0, height - footer_h, width, height)))
            ink_top = float(np.mean(top_band < 200))
            ink_bot = float(np.mean(bot_band < 200))
            has_header = ink_top > 0.02
            has_footer = ink_bot > 0.02
        except ImportError:
            has_table = False
            has_header = has_footer = False
            margin = int(width * 0.08)
            header_h = int(height * 0.08)
            footer_h = int(height * 0.08)

        regions: List[LayoutRegion] = []

        body_top = header_h if has_header else 0
        body_bottom = (height - footer_h) if has_footer else height
        body_height = max(1, body_bottom - body_top)

        if has_header:
            regions.append(LayoutRegion(0, 0, width, header_h, RegionType.HEADER,
                                        round(min(1.0, ink_top * 10), 2)))
        if has_footer:
            regions.append(LayoutRegion(0, height - footer_h, width, footer_h,
                                        RegionType.FOOTER, round(min(1.0, ink_bot * 10), 2)))

        # Широкие страницы (альбомные) — делим body на две колонки.
        is_wide = width > height * 1.15

        if has_table:
            table_top = body_top + int(body_height * 0.1)
            table_height = int(body_height * 0.3)
            regions.append(LayoutRegion(
                margin, table_top, width - 2 * margin, table_height,
                RegionType.TABLE, 0.4,
            ))
            text_top = table_top + table_height
            text_bottom = body_bottom
        else:
            text_top = body_top
            text_bottom = body_bottom

        if is_wide:
            col_w = (width - 3 * margin) // 2
            regions.append(LayoutRegion(
                margin, text_top, col_w, text_bottom - text_top, RegionType.TEXT, 0.5,
            ))
            regions.append(LayoutRegion(
                margin * 2 + col_w, text_top, col_w, text_bottom - text_top,
                RegionType.TEXT, 0.5,
            ))
        else:
            regions.append(LayoutRegion(
                margin, text_top, width - 2 * margin, text_bottom - text_top,
                RegionType.TEXT, 0.5,
            ))

        # Номер страницы — в правом нижнем углу, если есть футер.
        if has_footer:
            regions.append(LayoutRegion(
                width - margin, height - footer_h, margin // 2, footer_h,
                RegionType.PAGE_NUMBER, 0.3,
            ))

        return regions
