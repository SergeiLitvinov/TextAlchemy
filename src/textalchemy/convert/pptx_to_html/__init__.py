"""Пакет ``textalchemy.convert.pptx_to_html``.

Преобразует ``.pptx`` в автономный HTML/CSS/JS-просмотрщик
с поддержкой:

* текстовых плейсхолдеров и обычных текстбоксов
* изображений (PNG/JPG/WMF/EMF/др.) и OLE-объектов
* автофигур и линий-коннекторов (SVG)
* групп фигур
* встроенных таблиц
* уравнений OMML → MathML (рендер через MathJax v3)
* режима редактирования в браузере (перетаскивание, локальное
  хранилище, экспорт изменённого HTML)

Публичный API
-------------

::

    from textalchemy.convert.pptx_to_html import PptxToHtmlConverter, convert
    convert("source.pptx", "out_dir")
"""
from .converter import PptxToHtmlConverter, convert

__all__ = [
    "PptxToHtmlConverter",
    "convert",
]
