

def read_pdf(file_path: str) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        text = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text)
        result = "\n".join(text)

        if result.count("\u0000") > len(result) * 0.1:
            result = result.replace("\u0000", "")
            result = result.replace("\ufffd", "")

        return result
    except Exception:
        return ""


def get_pdf_info(file_path: str) -> dict:
    info = {"title": "", "author": "", "subject": ""}
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        meta = reader.metadata
        if meta:
            info["title"] = getattr(meta, "title", "") or ""
            info["author"] = getattr(meta, "author", "") or ""
            info["subject"] = getattr(meta, "subject", "") or ""
    except Exception:
        pass
    return info
