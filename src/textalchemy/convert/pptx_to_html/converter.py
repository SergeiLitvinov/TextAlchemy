"""Конвертация .pptx в автономный HTML-просмотрщик.

Публичный API:

    from textalchemy.convert.pptx_to_html import PptxToHtmlConverter, convert
    convert(Path("source.pptx"), Path("output_dir"))
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from textalchemy.convert.base import BaseConverter, ConversionResult
from textalchemy.core.artifacts import ArtifactWorkspace
from textalchemy.core.io import atomic_replace_directory

from ._renderer import (
    convert_pptx as _convert_pptx_impl,
)

logger = logging.getLogger(__name__)


def _get_asset(name: str) -> Path:
    """Возвращает путь к встроенному ресурсу (js/css)."""
    return Path(__file__).parent / "assets" / name


class PptxToHtmlConverter(BaseConverter):
    """Конвертер .pptx → автономный HTML-просмотрщик.

    Генерирует:
      * index.html       — единый файл с просмотрщиком
      * assets/images/   — извлечённые PNG/JPG/WMF/EMF
      * assets/ole/      — OLE-объекты (PBrush и др.)
      * assets/css/main.css
      * assets/js/main.js
    """

    #: MIME/CSS/JS-файлы кладутся в `<output>/assets/...`
    SUBDIR = "assets"

    def __init__(self, copy_assets: bool = True) -> None:
        self.copy_assets = copy_assets

    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        input_path = Path(input_path)
        output_path = Path(output_path)
        try:
            if not input_path.is_file():
                return ConversionResult(
                    input_path=input_path,
                    output_path=output_path,
                    success=False,
                    error=f"Input file not found: {input_path}",
                )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with ArtifactWorkspace(parent=output_path.parent, prefix=".textalchemy_pptx_html_") as workspace:
                staged = workspace.artifact_path("rendered")
                staged.mkdir()
                (staged / self.SUBDIR).mkdir(parents=True, exist_ok=True)
                _convert_pptx_impl(input_path, staged)
                if self.copy_assets:
                    self._copy_static_assets(staged)
                workspace.validate_artifact(staged)
                atomic_replace_directory(staged, output_path)
            return ConversionResult(
                input_path=input_path,
                output_path=output_path,
                success=True,
                error=None,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("pptx → html conversion failed")
            return ConversionResult(
                input_path=input_path,
                output_path=output_path,
                success=False,
                error=str(e),
            )

    def _copy_static_assets(self, output_path: Path) -> None:
        """Копирует встроенные css/js в <output>/assets/..."""
        assets_root = output_path / self.SUBDIR
        for sub in ("css", "js"):
            src_dir = Path(__file__).parent / "assets" / sub
            dst_dir = assets_root / sub
            dst_dir.mkdir(parents=True, exist_ok=True)
            for f in src_dir.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst_dir / f.name)


def convert(input_path: str | Path, output_path: str | Path, **kwargs: Any) -> ConversionResult:
    """Удобная функция-обёртка."""
    return PptxToHtmlConverter(**kwargs).convert(input_path, output_path)
