"""Own PDF interaction fixture, independent of the adapters under acceptance."""

import pymupdf


def write_interactive_pdf(path, *, unsupported=False, rotated=False, small=False):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=240 if small else 595, height=200 if small else 842)
        page.insert_text((20, 30), "Own PDF acceptance", fontsize=10)
        note = page.add_text_annot((20, 45), "Own note")
        note.update()
        highlight = page.add_highlight_annot(page.search_for("Own PDF"))
        highlight.update()
        page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(20, 80, 100, 100),
                          "uri": "https://example.invalid/"})
        field = pymupdf.Widget()
        field.field_name = "own-name"
        field.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        field.field_value = "Initial"
        field.rect = pymupdf.Rect(20, 110, 150, 135)
        field.script = "/* Own inert QA marker */"
        page.add_widget(field)
        if unsupported:
            page.add_rect_annot(pymupdf.Rect(170, 50, 200, 80)).update()
            pdf.set_toc([[1, "Own outline", 1]])
        if rotated:
            page.set_rotation(90)
        pdf.save(path)
    return path
