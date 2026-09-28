"""Supported semantic edits to PDF text blocks without rebuilding their contents."""
from textalchemy.core.document_model import Paragraph, TextRun

ROLES = {"paragraph": ("paragraph", "Normal", None),
         "heading1": ("heading", "Heading 1", 1),
         "heading2": ("heading", "Heading 2", 2),
         "heading3": ("heading", "Heading 3", 3)}


def describe(block) -> dict:
    editable = isinstance(block, Paragraph) and bool(block.content) and all(isinstance(run, TextRun) for run in block.content)
    return {"classifiable": editable, "classification": block.properties.get("pdf_editor_role", "auto")}


def apply_classifications(value: dict, changes: dict[str, str]) -> None:
    blocks = {block_id: block for ids, section in zip(value["order"], value["model"]["document"]["sections"], strict=True)
              for block_id, block in zip(ids, section["blocks"], strict=True)}
    for block_id, role in changes.items():
        block = blocks.get(block_id)
        if block is None or role not in ROLES:
            raise ValueError("Неизвестный блок или неподдержанный тип текста")
        if block["type"] != "paragraph" or not block["content"] or any(run["type"] != "text" for run in block["content"]):
            raise ValueError("Тип можно менять только у текстового абзаца без изображений и формул")
    for block_id, role in changes.items():
        block = blocks[block_id]
        kind, style, level = ROLES[role]
        block["style_id"] = style
        props = block["properties"]
        props.update(legacy_type=kind, style_name=style, pdf_editor_role=role)
        if level is None:
            props.pop("heading_level", None)
            props.pop("level", None)
        else:
            props.update(heading_level=level, level=level)
