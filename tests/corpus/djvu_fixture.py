"""Synthetic DjVu pages made by DjVuLibre tools; no third-party document content."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PAGE_TEXT = ("Пример №1 — Иванов Иван Иванович", "Résumé: café, Straße, Ελληνικά")


def make_djvu(directory: Path, *, with_text: bool = True) -> Path:
    """Build two blank image pages with a known hidden Unicode text layer."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in ('c44', 'djvused', 'djvm', 'djvutxt'):
        if shutil.which(name) is None:
            raise RuntimeError(f'DjVu fixture requires {name} in PATH')
    image = directory / 'page.ppm'
    image.write_bytes(b'P6\n320 180\n255\n' + b'\xff\xff\xff' * (320 * 180))
    pages = []
    for index, text in enumerate(PAGE_TEXT):
        page = directory / f'page-{index + 1}.djvu'
        subprocess.run(['c44', str(image), str(page)], check=True, capture_output=True, timeout=30)
        if with_text:
            layer = directory / f'text-{index + 1}.sexp'
            layer.write_text(f'(page 0 0 320 180 {json.dumps(text, ensure_ascii=False)})\n', encoding='utf-8')
            script = directory / f'text-{index + 1}.script'
            script.write_text(f'select 1\nset-txt "{layer.as_posix()}"\nsave\n', encoding='utf-8')
            subprocess.run(['djvused', str(page), '-f', str(script)], check=True, capture_output=True, timeout=30)
        pages.append(page)
    output = directory / ('unicode.djvu' if with_text else 'no-text.djvu')
    subprocess.run(['djvm', '-c', str(output), *(str(page) for page in pages)],
                   check=True, capture_output=True, timeout=30)
    return output
