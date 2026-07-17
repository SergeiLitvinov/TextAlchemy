import re
from pathlib import Path


def sanitize_key(name: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]", "", Path(name).stem[:30])
    return key if key else "ref"


def extract_year(text: str) -> str:
    for m in re.finditer(r"\b(19|20)\d{2}\b", text):
        return m.group()
    return "n.d."


def make_bibtex_entry(filename: str, pdf_info: dict) -> str:
    key = sanitize_key(filename)
    title = pdf_info.get("title", "").strip()
    if not title:
        title = Path(filename).stem
    author = pdf_info.get("author", "").strip()
    year = extract_year(pdf_info.get("title", "") + " " + pdf_info.get("subject", ""))
    lines = [f"@misc{{{key},"]
    if author:
        lines.append(f"  author = {{{author}}},")
    lines.append(f"  title = {{{title}}},")
    lines.append(f"  year = {{{year}}},")
    lines.append("  note = {PDF}")
    lines.append("}")
    return "\n".join(lines)


def generate_bib(source_dir: str | Path, output: str | Path | None = None) -> str:
    source = Path(source_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"Folder not found: {source}")

    pdfs = sorted(f for f in source.iterdir() if f.suffix.lower() == ".pdf")
    entries = []

    for pdf in pdfs:
        try:
            from textalchemy.formats.pdf import get_pdf_info

            info = get_pdf_info(str(pdf))
            entries.append(make_bibtex_entry(pdf.name, info))
        except Exception:
            entries.append(make_bibtex_entry(pdf.name, {}))

    bib = "\n\n".join(entries)
    if output:
        Path(output).write_text(bib, encoding="utf-8")
    return bib
