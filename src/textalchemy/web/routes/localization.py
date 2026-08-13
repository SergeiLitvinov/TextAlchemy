"""HTTP adapter for interface locale catalogs."""

from __future__ import annotations

from fastapi import HTTPException

from textalchemy.web.app import app
from textalchemy.web.services.localization import locale_catalog, locale_manifest


@app.get("/api/locales")
async def api_locales():
    return locale_manifest()


@app.get("/api/locales/{code}")
async def api_locale(code: str):
    catalog = locale_catalog(code)
    if catalog is None:
        raise HTTPException(status_code=404, detail="Перевод пока недоступен")
    return catalog


__all__ = ["api_locale", "api_locales"]
