import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from textalchemy.core.exceptions import GenerateError

TEMPLATES_DIR = Path(__file__).parent / "templates"
_BUILTIN_TEMPLATE_DESCRIPTIONS = {
    "abstract": "Аннотация научной работы",
    "article": "Научная статья",
    "laboratory": "Отчёт по лабораторной работе",
    "report": "Универсальный отчёт",
}


@dataclass
class DocumentTemplate:
    name: str
    description: str
    template_type: str = "docx"


class TemplateEngine:
    def __init__(self, templates_dir: str | Path | None = None):
        self.templates_dir = Path(templates_dir) if templates_dir else TEMPLATES_DIR

    def list_templates(self) -> List[DocumentTemplate]:
        if not self.templates_dir.exists():
            return []
        templates: List[DocumentTemplate] = []
        for f in sorted(self.templates_dir.iterdir()):
            if f.suffix.lower() in (".docx", ".doc", ".dotx"):
                templates.append(
                    DocumentTemplate(
                        name=f.stem,
                        description=_BUILTIN_TEMPLATE_DESCRIPTIONS.get(f.stem, f"Шаблон {f.name}"),
                        template_type=f.suffix[1:],
                    )
                )
        return templates

    def resolve_template(self, template_name: str) -> Path:
        """Найти шаблон по пути или имени в каталоге шаблонов."""

        direct = Path(template_name)
        candidates = [direct] if direct.is_file() else []
        candidates.extend(
            [
                self.templates_dir / template_name,
                self.templates_dir / f"{template_name}.docx",
                self.templates_dir / f"{template_name}.doc",
            ]
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        available = ", ".join(t.name for t in self.list_templates())
        msg = f"Template '{template_name}' not found. Available: {available or 'none'}"
        raise GenerateError(msg)

    def generate(
        self,
        template_name: str,
        output_path: str | Path,
        params: Optional[Dict[str, Any]] = None,
    ) -> Path:
        output_path = Path(output_path)
        template_path = self.resolve_template(template_name)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from opendoc_formats.docx import DocxPackage, ReplaceTextSpan

            params = params or {}
            values = {"{{" + key + "}}": str(value) for key, value in params.items()}
            pattern = re.compile("|".join(re.escape(key) for key in sorted(values, key=len, reverse=True))) if values else None
            with DocxPackage(template_path) as package:
                patches = [
                    ReplaceTextSpan(paragraph.id, *match.span(), values[match[0]])
                    for paragraph in package.paragraphs
                    for match in (pattern.finditer(paragraph.text) if pattern else ())
                ]
                package.write(output_path, patches)
        except Exception as e:
            raise GenerateError(f"Failed to generate document: {e}") from e

        return output_path


def generate_document(
    template_name: str,
    output_path: str | Path,
    params: Optional[Dict[str, Any]] = None,
    templates_dir: Optional[str | Path] = None,
) -> Path:
    engine = TemplateEngine(templates_dir)
    return engine.generate(template_name, output_path, params)


def list_templates(templates_dir: Optional[str | Path] = None) -> List[DocumentTemplate]:
    engine = TemplateEngine(templates_dir)
    return engine.list_templates()
