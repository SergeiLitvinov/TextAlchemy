"""Руководство и справочники на том же локальном сервере, что и приложение."""

from __future__ import annotations

from zipfile import BadZipFile

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from textalchemy.web.app import app
from textalchemy.web.services.documentation import DocumentationService


@app.get("/help", include_in_schema=False)
def documentation_root() -> RedirectResponse:
    return RedirectResponse("/help/", status_code=307)


@app.get("/help/{path:path}", include_in_schema=False)
def documentation_page(request: Request, path: str) -> Response:
    legacy = path.startswith("docs/")
    target = "doc/" + path[5:] if legacy else path
    try:
        asset = DocumentationService().read(target)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (OSError, BadZipFile) as error:
        raise HTTPException(503, "Не удалось открыть встроенную документацию. Проверьте установку приложения.") from error
    if legacy:
        return RedirectResponse("/help/" + target + ("/" if asset.directory else ""), status_code=308)
    if asset.directory:
        return RedirectResponse(request.url.path + "/", status_code=307)
    return Response(asset.content, media_type=asset.media_type, headers={"Cache-Control": "no-cache"})
