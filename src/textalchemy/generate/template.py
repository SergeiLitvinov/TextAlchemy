from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from textalchemy.core.exceptions import GenerateError

TEMPLATES_DIR = Path(__file__).parent / "templates"


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
                templates.append(DocumentTemplate(
                    name=f.stem,
                    description=f"Template: {f.name}",
                    template_type=f.suffix[1:],
                ))
        return templates

    def generate(
        self,
        template_name: str,
        output_path: str | Path,
        params: Optional[Dict[str, Any]] = None,
    ) -> Path:
        output_path = Path(output_path)
        template_path = self.templates_dir / template_name

        if not template_path.exists():
            template_path = self.templates_dir / f"{template_name}.docx"
        if not template_path.exists():
            template_path = self.templates_dir / f"{template_name}.doc"

        if not template_path.exists():
            available = ", ".join(t.name for t in self.list_templates())
            msg = f"Template '{template_name}' not found. Available: {available or 'none'}"
            raise GenerateError(msg)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from docx import Document
            doc = Document(str(template_path))
            params = params or {}

            for para in doc.paragraphs:
                for key, value in params.items():
                    placeholder = "{{" + key + "}}"
                    if placeholder in para.text:
                        para.text = para.text.replace(placeholder, str(value))

            doc.save(str(output_path))
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
