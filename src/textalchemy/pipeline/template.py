"""Pipeline-операции шаблонизации богатой модели документа."""

from typing import Any

from textalchemy.core.document_model import DocumentModel
from textalchemy.core.registry import operation
from textalchemy.generate.model_template import render_document_template


@operation(
    "template.render",
    input_type="DocumentModel",
    output_type="DocumentModel",
    input_param="document",
    description="Заполнить DocumentModel данными: переменные, условия и циклы.",
    tags=["template", "generate"],
)
def render_template(
    *,
    document: DocumentModel,
    data: dict[str, Any],
    strict: bool = True,
    schema: dict[str, Any] | None = None,
) -> DocumentModel:
    return render_document_template(document, data, strict=strict, schema=schema)


__all__ = ["render_template"]
