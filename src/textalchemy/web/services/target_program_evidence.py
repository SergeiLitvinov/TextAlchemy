"""Validate scoped QA evidence; the application never infers a target-app edit."""

import copy
import re
from datetime import datetime

CHECKS = {"text_edit", "table_cell_edit", "save_reopen", "heading_outline", "inline_image", "bold"}
SCOPES = {"paragraph_text", "table_cell", "heading_outline", "inline_image", "bold", "save_reopen"}


def validated_check(record: dict) -> dict:
    """Only local QA supplies this evidence; there is no HTTP submission endpoint."""
    if record.get("schema") != "target-program-check-v1" or record.get("driver") != "word-com":
        raise ValueError("Unsupported target-program evidence")
    program = record.get("program", {})
    if not isinstance(program, dict) or any(
        not isinstance(program.get(key), str) or not 0 < len(program[key]) <= 128 for key in ("name", "version", "build")
    ):
        raise ValueError("Target program and exact version are required")
    for key in ("artifact_sha256", "edited_sha256"):
        if not isinstance(record.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", record[key]):
            raise ValueError("Artifact SHA-256 is required")
    timestamp = datetime.fromisoformat(record["checked_at"])
    if timestamp.tzinfo is None:
        raise ValueError("Evidence timestamp requires a timezone")
    scope, checks = record.get("scope"), record.get("checks")
    if not isinstance(scope, list) or not scope or len(scope) != len(set(scope)) or not set(scope) <= SCOPES:
        raise ValueError("Evidence scope must be explicit")
    if not isinstance(checks, dict) or not checks or not set(checks) <= CHECKS:
        raise ValueError("Explicit target-program checks are required")
    check_scopes = {"text_edit": "paragraph_text", "table_cell_edit": "table_cell"}
    if any(check_scopes.get(key, key) not in scope for key in checks):
        raise ValueError("Every recorded check requires a declared scope")
    if any(value is not None and type(value) is not bool for value in checks.values()):
        raise ValueError("Unknown checks must remain null")
    observations = record.get("observations", {})
    outline = observations.get("heading_outline_level") if isinstance(observations, dict) else None
    if outline is not None and (type(outline) is not int or not 1 <= outline <= 10):
        raise ValueError("Invalid observed heading outline level")
    edit_checks = [checks.get(key) for key in ("text_edit", "table_cell_edit", "save_reopen")]
    verified = (
        False if False in edit_checks else None if None in edit_checks
        else record["artifact_sha256"] != record["edited_sha256"]
    )
    return copy.deepcopy({
        "schema": record["schema"], "driver": record["driver"],
        "program": {key: program[key] for key in ("name", "version", "build")},
        "checked_at": record["checked_at"], "artifact_sha256": record["artifact_sha256"],
        "edited_sha256": record["edited_sha256"], "scope": scope, "checks": checks,
        "editability_verified": verified, "visual_score": None,
        "observations": {"heading_outline_level": outline},
    })
