from pathlib import Path

from textalchemy.core.exceptions import ExtractError

REPLACEMENTS: dict[str, str] = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2026": "...",
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u00ab": '"',
    "\u00bb": '"',
}


def fix_encoding(file_path: str | Path, output_path: str | Path | None = None) -> str:
    file_path = Path(file_path)
    if not file_path.exists():
        raise ExtractError(f"File not found: {file_path}")

    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="cp1251")

    issues: list[str] = []
    for i, ch in enumerate(text):
        try:
            ch.encode("utf-8")
        except UnicodeEncodeError:
            issues.append(f"Position {i}: U+{ord(ch):04X}")

    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")

    summary = f"Replaced {sum(text.count(v) for v in REPLACEMENTS.values() if len(v) > 1)} characters"
    if issues:
        summary += f"\nFound {len(issues)} non-encodable characters:\n" + "\n".join(issues[:20])

    return summary
