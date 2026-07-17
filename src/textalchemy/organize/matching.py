import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from textalchemy.core.exceptions import OrganizeError
from textalchemy.organize.bibliography import BibItem
from textalchemy.organize.filename import normalize_filename, transliterate

DEFAULT_MANUAL_MATCHES: Dict[str, int] = {
    "42. dbbe20b": 30,
    "16. 2014.Usloviya.Vozniknoveniya.i.Sushestvovaniya.Ferroresonansa.v.Cepyah.s.Elektromagnitnimi.Izmeritel'nymi.TN": 30,
    "20. 1994.Usloviya.Ferroresonansa.s.Transformatorami.Napryazheniya.v.Seti.220kV": 34,
    "2018_222_topolskydv": 61,
}


def load_manual_matches(config_path: Optional[str | Path] = None) -> Dict[str, int]:
    matches = dict(DEFAULT_MANUAL_MATCHES)
    if config_path:
        path = Path(config_path)
        if path.exists():
            try:
                extra = json.loads(path.read_text(encoding="utf-8"))
                matches.update(extra)
            except (json.JSONDecodeError, OSError):
                pass
    return matches


def fuzzy_match_author(author: str, text: str, threshold: float = 0.6) -> bool:
    if not author or not author.strip():
        return False
    author_lower = author.lower()
    if author_lower in text.lower():
        return True
    words = text.lower().split()
    for word in words:
        if len(word) >= 4:
            ratio = SequenceMatcher(None, author_lower, word).ratio()
            if ratio >= threshold:
                return True
    return False


def extract_keywords_from_content(content: str, max_keywords: int = 30) -> set:
    words = re.findall(r"[а-яa-zёéèêëüöäîïñçčšžČŠŽăâîșțĂÂÎȘȚ]{4,}", content.lower())
    stop_words = {
        "that", "this", "with", "from", "have", "will", "been",
        "which", "their", "are", "were", "they", "there", "these",
        "это", "того", "этого", "которые", "имеют", "будут",
    }
    keywords = {w for w in words if w not in stop_words}
    sorted_kw = sorted(keywords)
    return set(sorted_kw[:max_keywords])


def extract_text_from_file(file_path: str | Path) -> str:
    from textalchemy.formats.docx import read_docx
    from textalchemy.formats.pdf import read_pdf
    from textalchemy.formats.txt import read_djvu, read_txt

    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            return read_pdf(str(file_path)).plain
        elif ext == ".docx":
            return read_docx(file_path).plain
        elif ext == ".txt":
            return read_txt(file_path).plain
        elif ext == ".djvu":
            return read_djvu(file_path).plain
        return ""
    except (OSError, ValueError, TypeError) as e:
        raise OrganizeError(f"Failed to extract text from {file_path}: {e}")


def match_file_to_bibliography(
    content: str,
    filename: str,
    bib_items: List[BibItem],
    threshold: float = 0.30,
    manual_matches: Optional[Dict[str, int]] = None,
) -> Tuple[int, str, float]:
    if manual_matches:
        file_no_ext = os.path.splitext(filename)[0]
        if file_no_ext in manual_matches:
            bib_idx = manual_matches[file_no_ext] - 1
            if 0 <= bib_idx < len(bib_items):
                return bib_idx, bib_items[bib_idx].raw_text, 1.0

    file_text = normalize_filename(content[:50000])
    file_name = normalize_filename(filename)
    file_name_translit = transliterate(file_name)
    content_keywords = extract_keywords_from_content(content)
    filename_keywords = extract_keywords_from_content(filename)
    filename_keywords.update(extract_keywords_from_content(file_name_translit))

    is_empty = len(content.strip()) < 100
    best_score, best_idx, best_text = 0.0, -1, ""

    for idx, item in enumerate(bib_items):
        score = 0.0
        author_found = False

        if item.authors:
            for author in item.authors[:5]:
                if len(author) <= 3:
                    continue
                an = normalize_filename(author)
                at = transliterate(author).lower()
                if an in file_text:
                    score += 1.0
                    author_found = True
                if at in file_text:
                    score += 0.9
                    author_found = True
                if an in file_name:
                    score += 1.2
                    author_found = True
                if at in file_name_translit:
                    score += 1.1
                    author_found = True

        if item.title and item.title not in ("Unknown", ""):
            tn = normalize_filename(item.title)
            tp = tn[:min(60, len(tn))]

            if author_found:
                if len(tp) >= 3:
                    words = [w for w in tn.split("_") if len(w) > 3]
                    for start in range(len(words) - 2):
                        phrase = "_".join(words[start:start+3])
                        if phrase in file_text:
                            score += 2.0
                            break
                tk = set(re.findall(r"[а-яa-zёéèêëüöäîïñçčšžČŠŽăâîșțĂÂÎȘȚ]{4,}", tn))
                tk.update(extract_keywords_from_content(transliterate(item.title)))
                if content_keywords:
                    overlap = len(tk & content_keywords)
                    if overlap > 0:
                        score += (overlap / max(len(tk), 1)) * 2.0
                if filename_keywords:
                    overlap = len(tk & filename_keywords)
                    if overlap > 0:
                        score += (overlap / max(len(tk), 1)) * 2.5
                if len(item.title) > 15 and tp in file_name:
                    score += 1.5
                if is_empty and len(item.title) > 15 and tp in file_name:
                    score += 2.0
                if is_empty and len(item.title) > 15:
                    tt = transliterate(tp)
                    if tt in file_name or tt in file_name_translit:
                        score += 2.5
            else:
                if is_empty and tp in file_name:
                    score += 1.0
                elif not is_empty:
                    tk = set(re.findall(r"[а-яa-zёéèêëüöäîïñçčšžČŠŽăâîșțĂÂÎȘȚ]{4,}", tn))
                    if content_keywords:
                        overlap = len(tk & content_keywords)
                        if overlap > 0:
                            score += (overlap / max(len(tk), 1)) * 1.0

        if item.year:
            ys = str(item.year)
            if ys in file_text or ys in file_name:
                score += 0.15

        if score > best_score:
            best_score, best_idx, best_text = score, idx, item.raw_text

    if best_score >= threshold:
        return best_idx, best_text, best_score
    return -1, "", best_score
