"""Serialize model list paragraphs as nested semantic HTML lists."""

from textalchemy.core.document_model import Paragraph


def render_blocks(blocks, render):
    output, stack = [], []

    def close():
        tag, _ = stack.pop()
        output.append(f"</li></{tag}>")

    for index, block in enumerate(blocks):
        props = block.properties if isinstance(block, Paragraph) else {}
        if "html_list_id" not in props:
            while stack:
                close()
            output.append(render(block, index))
            continue
        depth = min(max(int(props.get("list_level", 0)), 0), len(stack))
        while len(stack) > depth + 1:
            close()
        key = props["html_list_id"]
        if len(stack) == depth + 1 and stack[-1][1] != key:
            close()
        if len(stack) == depth:
            tag = "ol" if props.get("list_kind") == "ordered" else "ul"
            start = f' start="{int(props.get("list_start", 1))}"' if tag == "ol" else ""
            output.append(f"<{tag}{start}><li>")
            stack.append((tag, key))
        else:
            output.append("</li><li>")
        output.append(render(block, index))
    while stack:
        close()
    return "".join(output)
