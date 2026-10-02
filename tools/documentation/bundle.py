"""Детерминированный офлайн-комплект сайта для поставки внутри приложения."""

from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from tools.documentation.generated import ROOT

BUNDLE = ROOT / "src/textalchemy/web/assets/documentation.zip"
SITE = ROOT / ".textalchemy/docs-site"


def site_archive(site: Path) -> bytes:
    """Упаковать только сборку сайта; даты и порядок файлов не влияют на результат."""
    if not (site / "index.html").is_file():
        raise ValueError("Документация не собрана")
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(site.rglob("*")):
            if not path.is_file() or path.name in {"sitemap.xml", "sitemap.xml.gz"}:
                continue
            entry = ZipInfo(path.relative_to(site).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            data = path.read_bytes()
            if path.suffix in {".html", ".css", ".js", ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".svg", ".xml"}:
                data = data.replace(b"\r\n", b"\n")
            archive.writestr(entry, data)
    return output.getvalue()


def sync_bundle(*, check: bool = False) -> bool:
    """Обновить комплект или отклонить расхождение с текущим собранным сайтом."""
    content = site_archive(SITE)
    if BUNDLE.is_file():
        with ZipFile(BUNDLE) as previous, ZipFile(io.BytesIO(content)) as current:
            names = current.namelist()
            if set(previous.namelist()) == set(names) and all(previous.read(name) == current.read(name) for name in names):
                return False
    if check:
        raise ValueError("Комплект документации устарел. Выполните uv run python -m tools.docs generate")
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE.write_bytes(content)
    return True
