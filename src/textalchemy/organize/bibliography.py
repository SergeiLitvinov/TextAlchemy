import re
from pathlib import Path
from typing import List

from textalchemy.core.types import BibItem  # noqa: F401

# ── Форматы библиографии ──────────────────────────

_DOC_TYPE_PATTERNS = [
    ("abstract", [r"автореферат", r"автореф\.?"]),
    ("dissertation", [r"диссертация", r"дис\.", r"кандидатск", r"докторск", r"специальность\s*\d+"]),
    ("standard", [r"гост", r"стандарт", r"сп\s*\d+"]),
    ("patent", [r"патент", r"пат\.", r"изобретение", r"полезная\s+модель"]),
    ("book", [r"учебник", r"учебное\s*пособие", r"издание\b", r"м\.?\s*:", r"издательств"]),
    ("monograph", [r"монография"]),
    ("conference", [r"материалы\s", r"тезисы", r"конференц", r"симпозиум", r"труды\s+конференц"]),
    ("article", [r"//\s", r"журнал", r"вып\.\s*\d+", r"№\s*\d+", r"с\.\s*\d+[-–]\d+", r"pp\.\s*\d+"]),
    ("collection", [r"сборник", r"редколлегия", r"составитель"]),
    ("report", [r"отчёт", r"отчет\b", r"грант", r"проект", r"методическ", r"technical\s+brochure"]),
]


def _extract_doc_type(text: str) -> str:
    text_lower = text.lower()
    for doc_type, patterns in _DOC_TYPE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return doc_type
    return "unknown"


def _extract_authors(text: str) -> List[str]:
    if not text:
        return []
    prefix = text[:250]

    corporate = [
        r"^(Министерство\s[^,]+?)(?:[,]|\s[–—-]|\s\d|\s*$)",
        r"^(ОАО\s[^,]+?)(?:[,]|\s[–—-]|\s\d|\s*$)",
        r"^(ПАО\s[^,]+?)(?:[,]|\s[–—-]|\s\d|\s*$)",
        r"^(IEEE[^,]*?)(?:[,]|\s[–—-]|\s\d|\s*$)",
        r"^(ГОСТ\s[^,]+?)(?:[,]|\s[–—-]|\s\d|\s*$)",
    ]
    for pat in corporate:
        m = re.search(pat, prefix)
        if m:
            name = m.group(1).strip().rstrip("., ")
            if len(name) > 2:
                return [name]

    ru = re.findall(r"([А-Я][а-яё]+(?:-[А-Я][а-яё]+)?)\s+[А-Я]\.[А-Я]?\.?", prefix)
    if ru:
        return [m.strip() for m in ru if m.strip()][:5]

    en = re.findall(r"([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s+[A-Z]\.", prefix)
    if en:
        return [m.strip() for m in en if m.strip()][:5]

    return []


def _extract_title(text: str) -> str:
    for delim in ["//", "URL:", "ISBN:", "doi:"]:
        pos = text.lower().find(delim.lower())
        if pos >= 0:
            text = text[:pos]

    title_end = len(text)
    for pat in [r"\b\d{4}\b", r"\bМ\.?\s*:", r"\bМосква\b", r"\bСПб\b",
                r"\bLondon\b", r"\bNew York\b"]:
        m = re.search(pat, text)
        if m and m.start() < title_end:
            title_end = m.start()

    author_pat = (  # noqa: E501
        r"^(?:[A-Za-zА-Яа-яёЁčšžČŠŽ][A-Za-zА-Яа-яёЁčšžČŠŽ-]+(?:\s+[A-Za-zА-Яа-яёЁčšžČŠŽ]\.[A-Za-zА-Яа-яёЁčšžČŠŽ]?\.?)\s*,\s*)*"
        r"[A-Za-zА-Яа-яёЁčšžČŠŽ][A-Za-zА-Яа-яёЁčšžČŠŽ-]+(?:\s+[A-Za-zА-Яа-яёЁčšžČŠŽ]\.[A-Za-zА-Яа-яёЁčšžČŠŽ]?\.?)"
    )
    m = re.match(author_pat, text[:200])
    title = text[m.end():title_end].strip() if m else text[:title_end].strip()

    title = re.sub(r"^[,;:\s]+", "", title)
    title = re.sub(r"^и\.д\.\s*", "", title)
    title = re.sub(r"\s+", " ", title)
    return title[:200] if len(title) >= 3 else text[:100]


def _parse_single(index: int, text: str) -> BibItem:
    item = BibItem(index=index, raw_text=text)
    item.authors = _extract_authors(text)
    item.title = _extract_title(text)
    item.doc_type = _extract_doc_type(text)

    year_m = re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)
    if year_m:
        item.year = int(year_m[-1])

    pages_m = re.search(r"(?:с\.\s*|pp\.\s*|p\.\s*)(\d+[–—\-]\d+)", text, re.IGNORECASE)
    if pages_m:
        item.pages = pages_m.group(1)

    doi_m = re.search(r"10\.\d{4,}/[\w./-]+(?<!\.)(?=[.,\s]|$)", text)
    if doi_m:
        item.doi = doi_m.group()

    isbn_m = re.search(r"(?:ISBN[:\s]*)?([\d-]{10,})", text, re.IGNORECASE)
    if isbn_m:
        item.isbn = isbn_m.group(1)

    url_m = re.search(r"https?://[^\s]+", text)
    if url_m:
        item.url = url_m.group()

    return item


def detect_format(text: str | List[str]) -> str:
    if isinstance(text, list):
        lines = [line.strip() for line in text if line.strip()]
        if not lines:
            return "blank"
        text_str = "\n".join(lines)
    else:
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        if not lines:
            return "blank"
        text_str = text
    numbered = len(re.findall(r"(?m)^\s*\d+[.)]\s+", text_str))
    gost_slashes = sum(1 for line in lines if " // " in line)
    blank_sep = bool(re.search(r"\n\s*\n", text_str.strip()))
    if gost_slashes > len(lines) * 0.3:
        return "gost"
    if numbered >= 3:
        return "numbered"
    if blank_sep:
        return "blank_separated"
    return "simple_lines"


def _split_numbered(text: str) -> List[str]:
    parts = re.split(r"(?m)^\s*\d+(?:\.|\))\s+", text)
    result = []
    for part in parts:
        clean = " ".join(part.split())
        if len(clean) > 10:
            result.append(clean)
    return result


def _split_blank_lines(text: str) -> List[str]:
    return [e.strip() for e in re.split(r"\n\s*\n", text.strip()) if len(e.strip()) > 10]


def _split_lines(text: str) -> List[str]:
    return [line.strip() for line in text.strip().split("\n") if len(line.strip()) > 10]


def smart_parse(text: str) -> List[BibItem]:
    fmt = detect_format(text)
    if fmt == "numbered":
        parts = _split_numbered(text)
    elif fmt in ("gost", "blank_separated"):
        parts = _split_blank_lines(text)
    else:
        parts = _split_lines(text)
    return [_parse_single(i + 1, p) for i, p in enumerate(parts)]


# ── Parser class ──────────────────────────────────

class BibliographyParser:
    @staticmethod
    def parse_file(file_path: str) -> List[BibItem]:
        path = Path(file_path)
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="cp1251")
        return smart_parse(text)

    @staticmethod
    def parse_item(index: int, text: str) -> BibItem:
        return _parse_single(index, text)

    @staticmethod
    def to_json(items: List[BibItem]) -> List[dict]:
        return [
            {
                "index": i.index,
                "authors": i.authors,
                "title": i.title,
                "year": i.year,
                "doc_type": i.doc_type,
                "source": i.source,
                "pages": i.pages,
                "doi": i.doi,
                "isbn": i.isbn,
                "url": i.url,
                "raw": i.raw_text,
            }
            for i in items
        ]

    @staticmethod
    def to_markdown(items: List[BibItem]) -> str:
        lines = []
        for item in items:
            authors = ", ".join(item.authors) if item.authors else "Без автора"
            year = f" ({item.year})" if item.year else ""
            title = f"**{item.title}**" if item.title else ""
            line = f"{item.index}. {authors}{year}. {title}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def to_gost(items: List[BibItem]) -> str:
        from textalchemy.organize.gost import GostFormatter
        formatter = GostFormatter()
        lines = [formatter.format_item(item) for item in items]
        return "\n\n".join(lines)
