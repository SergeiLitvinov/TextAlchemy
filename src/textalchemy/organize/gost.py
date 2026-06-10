from pathlib import Path

from textalchemy.organize.bibliography import BibItem, BibliographyParser


class GostFormatter:
    def format_item(self, item: BibItem) -> str:
        formatter = self._get_formatter(item.doc_type)
        return formatter(item)

    def format(self, item: BibItem) -> str:
        return self.format_item(item)

    def _get_formatter(self, doc_type: str):
        formatters = {
            "article": self._format_article,
            "book": self._format_book,
            "dissertation": self._format_dissertation,
            "monograph": self._format_monograph,
            "conference": self._format_conference,
            "patent": self._format_patent,
            "standard": self._format_standard,
            "abstract": self._format_abstract,
            "report": self._format_report,
            "collection": self._format_collection,
        }
        return formatters.get(doc_type, self._format_article)

    def _fa(self, authors) -> str:
        if isinstance(authors, list):
            return ", ".join(authors)
        return authors

    def _format_article(self, item: BibItem) -> str:
        parts = [self._fa(item.authors), item.title]
        if item.source:
            parts.append(f"// {item.source}")
        if item.year:
            parts.append(f". – {item.year}")
        if item.pages:
            parts.append(f". – {item.pages}")
        if item.doi:
            parts.append(f". – DOI: {item.doi}")
        return " ".join(parts)

    def _format_book(self, item: BibItem) -> str:
        parts = [self._fa(item.authors), item.title]
        if item.year:
            parts.append(f". – {item.year}")
        if item.pages:
            parts.append(f". – {item.pages} с.")
        if item.isbn:
            parts.append(f". – ISBN: {item.isbn}")
        return " ".join(parts)

    def _format_dissertation(self, item: BibItem) -> str:
        parts = [self._fa(item.authors), item.title]
        if item.year:
            parts.append(f": дис. ... канд. техн. наук. – {item.year}")
        if item.pages:
            parts.append(f". – {item.pages} с.")
        return " ".join(parts)

    def _format_monograph(self, item: BibItem) -> str:
        parts = [self._fa(item.authors), item.title]
        if item.year:
            parts.append(f". – {item.year}")
        if item.pages:
            parts.append(f". – {item.pages} с.")
        if item.isbn:
            parts.append(f". – ISBN: {item.isbn}")
        return " ".join(parts)

    def _format_conference(self, item: BibItem) -> str:
        parts = [self._fa(item.authors), item.title]
        if item.source:
            parts.append(f"// {item.source}")
        if item.year:
            parts.append(f". – {item.year}")
        if item.pages:
            parts.append(f". – {item.pages}")
        if item.doi:
            parts.append(f". – DOI: {item.doi}")
        return " ".join(parts)

    def _format_patent(self, item: BibItem) -> str:
        parts = [item.title]
        if item.authors:
            parts.insert(0, self._fa(item.authors))
        if item.year:
            parts.append(f". – {item.year}")
        return " ".join(parts)

    def _format_standard(self, item: BibItem) -> str:
        parts = [item.title]
        if item.year:
            parts.append(f". – {item.year}")
        return " ".join(parts)

    def _format_abstract(self, item: BibItem) -> str:
        parts = [self._fa(item.authors), item.title]
        if item.year:
            parts.append(f". – {item.year}")
        if item.pages:
            parts.append(f". – {item.pages} с.")
        return " ".join(parts)

    def _format_report(self, item: BibItem) -> str:
        parts = [self._fa(item.authors), item.title]
        if item.year:
            parts.append(f". – {item.year}")
        return " ".join(parts)

    def _format_collection(self, item: BibItem) -> str:
        parts = [item.title]
        if item.year:
            parts.append(f". – {item.year}")
        return " ".join(parts)

    def format_bibliography(self, items: list[BibItem]) -> str:
        return "\n".join(f"{i+1}. {self.format_item(item)}" for i, item in enumerate(items))

    def convert_file(self, input_path: str, output_path: str) -> None:
        items = BibliographyParser.parse_file(input_path)
        result = self.format_bibliography(items)
        Path(output_path).write_text(result, encoding="utf-8")
