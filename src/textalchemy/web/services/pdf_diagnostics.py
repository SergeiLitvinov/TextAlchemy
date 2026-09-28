"""Resolve exporter locations to stable PDF editor block IDs."""
import re

from textalchemy.core.document_codec import document_from_dict


def attach_targets(value: dict, report: dict) -> dict:
    model = document_from_dict(value["model"])
    for issue in report["issues"]:
        issue["target"] = None
        match = re.match(r"^sections\[(\d+)\]\.blocks\[(\d+)\](?:\.|$)", issue["location"])
        if match is None:
            continue
        page, index = map(int, match.groups())
        if page >= len(value["order"]) or index >= len(value["order"][page]):
            continue
        block = model.sections[page].blocks[index]
        issue["target"] = {"page": page, "block_id": value["order"][page][index],
                           "label": (getattr(block, "plain_text", "") or type(block).__name__)[:160]}
    return {"revision": value["revision"], "issues": report["issues"], "success": report["success"]}
