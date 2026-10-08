"""Синтетический EPUB-корпус без зависимости от тестируемого обработчика."""

from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_STORED, ZipFile, ZipInfo


def write_epub_fixture(
    path: Path,
    *,
    title: str,
    language: str,
    chapters: list[tuple[str, str, str]],
    assets: dict[str, tuple[str, bytes]] | None = None,
) -> None:
    """Записать фиксированные ZIP/XML данные; порядок глав задаёт spine, а не manifest."""
    manifest, spine, navigation = [], [], []
    entries: dict[str, bytes] = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": (
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
        ).encode(),
    }
    for index, (name, chapter_title, content) in enumerate(chapters):
        identifier = f"chapter-{index}"
        manifest.append(f'<item id="{identifier}" href={quoteattr(name)} media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{identifier}"/>')
        navigation.append(f'<li><a href={quoteattr(name)}>{escape(chapter_title)}</a></li>')
        entries[name] = content.encode("utf-8")
    for index, (name, (media_type, content)) in enumerate((assets or {}).items()):
        manifest.append(f'<item id="asset-{index}" href={quoteattr(name)} media-type={quoteattr(media_type)}/>')
        entries[name] = content
    manifest.append('<item id="navigation" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    entries["nav.xhtml"] = (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>'
        '<nav epub:type="toc"><ol>' + "".join(navigation) + "</ol></nav></body></html>"
    ).encode("utf-8")
    entries["package.opf"] = (
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="identifier">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="identifier">synthetic-corpus</dc:identifier><dc:title>{escape(title)}</dc:title>'
        f'<dc:language>{escape(language)}</dc:language></metadata><manifest>{"".join(reversed(manifest))}</manifest>'
        f'<spine>{"".join(spine)}</spine></package>'
    ).encode("utf-8")
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            entry = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_STORED
            archive.writestr(entry, content)
