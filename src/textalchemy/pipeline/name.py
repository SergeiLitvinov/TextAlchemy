"""Генерация имени файла по ``BibItem``/``Match``.

Перенос ``organize/filename.py::build_filename`` с тем же алгоритмом
аббревиации, но контракт: ``build(BibItem, *, template=...) -> str`` и
``from_match(Match) -> Optional[str]`` (None если матч не сработал).
"""
from __future__ import annotations

import enum
import re
from typing import Optional

from textalchemy.core.registry import operation
from textalchemy.core.types import BibItem, Match


class DocType(enum.Enum):
    ARTICLE = "article"
    DISSERTATION = "dissertation"
    MONOGRAPH = "monograph"
    BOOK = "book"
    CONFERENCE = "conference"
    COLLECTION = "collection"
    REPORT = "report"
    STANDARD = "standard"
    PATENT = "patent"
    ABSTRACT = "abstract"
    UNKNOWN = "unknown"

    @classmethod
    def from_str(cls, s: str) -> "DocType":
        m = {
            "article": cls.ARTICLE, "book": cls.BOOK,
            "dissertation": cls.DISSERTATION, "monograph": cls.MONOGRAPH,
            "conference": cls.CONFERENCE, "collection": cls.COLLECTION,
            "report": cls.REPORT, "standard": cls.STANDARD,
            "patent": cls.PATENT, "abstract": cls.ABSTRACT,
        }
        return m.get((s or "").lower(), cls.UNKNOWN)

    def label_ru(self) -> str:
        return {
            "article": "статья", "book": "книга", "dissertation": "диссертация",
            "monograph": "монография", "conference": "конференция",
            "collection": "сборник", "report": "отчёт", "standard": "стандарт",
            "patent": "патент", "abstract": "автореферат", "unknown": "документ",
        }.get(self.value, "документ")

    def short_rus(self) -> str:
        return {
            "article": "статья", "book": "книга", "dissertation": "дисс",
            "monograph": "моногр", "conference": "докл", "collection": "сб",
            "report": "отчет", "standard": "стандарт", "patent": "патент",
            "abstract": "автореф", "unknown": "док",
        }.get(self.value, self.value)


_RU_SUFFIXES = [
    (r"изировани(е|я)$", "изир."), (r"ировани(е|я)$", "ир."),
    (r"овани(е|я)$", "ов."), (r"ени(е|я)$", "ен."),
    (r"ани(е|я)$", "ан."), (r"ическ(ий|ая|ое|ие)$", "ич."),
    (r"еск(ий|ая|ое|ие)$", "еск."), (r"ацион(ный|ная|ное|ные|ных)$", "ац."),
    (r"изаци(я|и|ей)$", "изац."), (r"енци(я|и)$", "енц."),
    (r"льн(ый|ая|ое|ые)$", "л."), (r"тельн(ый|ая|ое|ые)$", "тел."),
    (r"ност(и|ь|ью|ей)$", "н."), (r"ческ(ий|ая|ое|ие)$", "ч."),
    (r"ичн(ый|ая|ое|ые)$", "ич."), (r"ственн(ый|ая|ое|ые|ых)$", "ств."),
    (r"енн(ый|ая|ое|ые)$", "ен."), (r"онн(ый|ая|ое|ые)$", "он."),
    (r"изи(я|и|ей)$", "из."), (r"ци(я|и|ей)$", "ц."),
]
_EN_SUFFIXES = [
    (r"ization$", "iz."), (r"isation$", "is."),
    (r"ationally$", "ally"), (r"ability$", "abl."),
    (r"ibility$", "ibl."), (r"ography$", "ogr."),
    (r"ology$", "ol."), (r"ometer$", "om."),
    (r"tion$", "t."), (r"ment$", "m."),
    (r"ance$", "ance"), (r"ence$", "ence"),
    (r"ing$", "ing"), (r"less$", "less"), (r"ness$", "n."),
]
_KEEP_RU = {"в", "на", "с", "со", "от", "из", "у", "к", "о", "об", "по", "за",
            "при", "для", "до", "через", "и", "а", "но", "или", "не", "ни",
            "же", "бы", "ли", "то", "как"}
_KEEP_EN = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or",
            "with", "from", "by", "is", "it", "as", "its", "are", "was", "but",
            "not", "nor", "per"}


def transliterate(text: str) -> str:
    mapping = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    return "".join(mapping.get(c, c) for c in text.lower())


def normalize_filename(text: str, max_len: int = 50) -> str:
    if not text:
        return ""
    text = re.sub(r"[^\w\s\-а-яА-ЯёЁA-Za-z]", "", text)
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    if len(text) > max_len:
        text = text[:max_len].rstrip("_")
        if len(text) > max_len - 3:
            text = text[: max_len - 3] + "..."
    return text.lower().strip("_")


def _is_cyr(word: str) -> bool:
    return any("\u0400" <= c <= "\u04FF" or c == "ё" for c in word)


def _abbreviate_word(word: str, min_keep: int = 5) -> str:
    if len(word) <= min_keep:
        return word
    suffixes = _RU_SUFFIXES if _is_cyr(word) else _EN_SUFFIXES
    for pattern, repl in suffixes:
        result = re.sub(pattern, repl, word, count=1)
        if result != word and len(result) < len(word):
            return result.rstrip(".")
    cut = min(7, len(word))
    vowels = "аеёиоуыэюя" if _is_cyr(word) else "aeiouy"
    while cut > 4 and word[cut - 1] in vowels:
        cut -= 1
    return word[:cut] + "."


def _abbrev_title_word(word: str) -> str:
    keep = _KEEP_RU if _is_cyr(word) else _KEEP_EN
    w = word.lower()
    if w in keep or len(w) <= 5:
        return w
    if len(w) <= 10:
        return _abbreviate_word(w, 4)
    return _abbreviate_word(w, 6)


def abbreviate_title(title: str, max_len: int = 55) -> str:
    if not title:
        return ""
    clean = re.sub(r'[^\w\s\-а-яА-ЯёЁA-Za-z]', "", title)
    abbreviated: list[str] = []
    for w in clean.split():
        if "-" in w:
            parts = w.split("-")
            abbreviated.append("-".join(_abbrev_title_word(p) for p in parts))
        else:
            abbreviated.append(_abbrev_title_word(w))
    result: list[str] = []
    total = 0
    for word in abbreviated:
        sep = "_" if result else ""
        cand = total + len(sep) + len(word)
        if cand <= max_len:
            result.append(word)
            total = cand
        else:
            break
    while result and (len(result[-1]) <= 2 or result[-1] in _KEEP_RU | _KEEP_EN):
        result.pop()
    if not result and abbreviated:
        return abbreviated[0][:max_len]
    return "_".join(result)


def _preserve_case(text: str, max_len: int = 20) -> str:
    text = re.sub(r"[^\w\-а-яА-ЯёЁA-Za-z]", "", text)
    text = re.sub(r"_+", "_", text)
    if not text:
        return "Unknown"
    if len(text) > max_len:
        text = text[:max_len]
    return text[0].upper() + text[1:].lower()


def format_authors(authors: list[str], max_count: int = 3) -> str:
    if not authors:
        return "Unknown"
    if len(authors) == 1:
        return _preserve_case(authors[0], 20)
    if max_count >= len(authors):
        return "_".join(_preserve_case(a, 15) for a in authors[:max_count])
    first = _preserve_case(authors[0], 15)
    has_cyr = any(_is_cyr(a) for a in authors)
    suffix = "et_al" if not has_cyr else "и_др"
    return f"{first}_{suffix}"


def build_filename(
    item: BibItem,
    *,
    template: str = "{index:02d}_{type}_{authors}_{title}",
    max_title_len: int = 55,
    max_authors: int = 3,
    include_type: bool = True,
    ext: str = ".pdf",
    separator: str = "_",
    transliterate_title: bool = False,
) -> str:
    """Сгенерировать имя файла по ``BibItem``."""
    required = {"index", "authors", "title"}
    if include_type:
        required.add("type")
    found = set(re.findall(r"\{(\w+)(?::[^}]*)?\}", template))
    missing = required - found
    if missing:
        raise ValueError(f"template must contain keys: {missing}")

    authors_str = format_authors(item.authors or [], max_authors)
    title_str = abbreviate_title(item.title, max_title_len)

    if transliterate_title:
        title_str = transliterate(title_str)

    type_str = DocType.from_str(item.doc_type).short_rus() if include_type else ""

    if not include_type:
        template = re.sub(r"_?\{type\}?", "", template)

    filename = template.format(
        index=item.index or 0,
        type=type_str,
        authors=authors_str,
        title=title_str,
    )
    filename = re.sub(re.escape(separator) + "+", separator, filename)
    filename = filename.strip(separator).rstrip(".")
    return filename + ext.lower()


@operation(
    "name.from_match", input_type="Match", output_type="str", input_param="match",
    description="Match → имя файла (None если матч не сработал).",
    tags=["name"],
)
def name_from_match(
    *,
    match: Match,
    ext: str = ".pdf",
    template: str = "{index:02d}_{type}_{authors}_{title}",
    require_match: bool = True,
) -> Optional[str]:
    """Сгенерировать имя файла из Match. Возвращает ``None`` если ``require_match=True`` и матча нет."""
    if require_match and (not match.matched or match.item is None):
        return None
    if match.item is None:
        return None
    return build_filename(match.item, template=template, ext=ext)


__all__ = [
    "DocType",
    "abbreviate_title",
    "format_authors",
    "build_filename",
    "name_from_match",
    "transliterate",
    "normalize_filename",
]
