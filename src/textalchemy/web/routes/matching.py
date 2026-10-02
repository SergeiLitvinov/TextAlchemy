"""HTTP-адаптеры сопоставления, статистики и конфигурации."""

from typing import Any

from fastapi import Form

from textalchemy.web.app import _load_config, _save_config, app, matching_service


@app.post("/api/match/run")
async def api_run_matching(
    source_dir: str = Form("./literature_files"),
    output_dir: str = Form("./renamed"),
    threshold: float = Form(0.30),
    bibliography_file: str = Form(""),
    dry_run: bool = Form(False),
) -> dict[str, Any]:
    return matching_service().run(
        source_dir=source_dir,
        output_dir=output_dir,
        threshold=threshold,
        bibliography_file=bibliography_file,
        dry_run=dry_run,
    )


@app.get("/api/match/report")
async def api_get_matching_report() -> dict[str, Any]:
    return matching_service().report()


@app.post("/api/preview/rename")
async def api_preview_rename(
    source_dir: str = Form("./literature_files"),
    threshold: float = Form(0.30),
    bibliography_file: str = Form(""),
) -> dict[str, Any]:
    return matching_service().preview(source_dir=source_dir, threshold=threshold, bibliography_file=bibliography_file)


@app.get("/api/stats")
async def api_stats() -> dict[str, Any]:
    return matching_service().stats()


@app.get("/api/config")
async def api_get_config() -> dict[str, Any]:
    return _load_config()


@app.post("/api/config")
async def api_update_config(cfg: str = Form(...)) -> dict[str, bool]:
    import json

    _save_config(json.loads(cfg))
    return {"success": True}
