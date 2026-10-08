"""Run read-only user-corpus acceptance against the actual TextAlchemy Web API."""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from tools.acceptance.memory import MemoryObservation

ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(manifest: dict, destination: Path) -> list[dict]:
    """Validate every path before creating copies; source trees are never writable outputs."""
    source_root = Path(manifest["source_root"]).resolve(strict=True)
    destination = destination.resolve()
    allowed = (ROOT / ".textalchemy/acceptance").resolve()
    if allowed not in destination.parents or source_root == destination or source_root in destination.parents:
        raise ValueError("Acceptance outputs must stay inside the application's separate local acceptance directory")
    if destination.exists():
        raise ValueError("Use a fresh acceptance directory; previous evidence must not be overwritten")
    selected, seen = [], set()
    for item in manifest["documents"]:
        identifier = item["id"]
        if not identifier.isascii() or not identifier.replace("-", "").isalnum() or identifier in seen:
            raise ValueError("Unique ASCII document identifiers are required")
        source = (source_root / item["path"]).resolve(strict=True)
        if source_root not in source.parents or not source.is_file():
            raise ValueError("Selected source escapes the authorized corpus")
        if source.suffix.lower() not in {".docx", ".pdf", ".pptx", ".html", ".epub", ".txt", ".djvu"}:
            raise ValueError("Unsupported acceptance format")
        cycle_format = item.get("cycle_format", source.suffix.lower().lstrip("."))
        if cycle_format not in {"docx", "pdf", "pptx", "html", "epub", "txt", "djvu"}:
            raise ValueError("Unsupported acceptance cycle format")
        seen.add(identifier)
        selected.append({"id": identifier, "source": source, "source_sha256": digest(source), "cycle_format": cycle_format})
    if not selected:
        raise ValueError("Select at least one source document")
    destination.mkdir(parents=True)
    for item in selected:
        copied = destination / item["id"] / ("source" + item["source"].suffix.lower())
        copied.parent.mkdir()
        copied.write_bytes(item["source"].read_bytes())
        if digest(copied) != item["source_sha256"]:
            raise ValueError("Source changed while copying; do not run this snapshot")
        item["copy"] = copied
    return selected


def wait_task(client, task: dict, *, timeout: float = 180) -> dict:
    """A timeout records an unresolved live task; it does not restart or cancel it."""
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(task["status"])
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {"done", "error", "cancelled", "interrupted"}:
            return payload
        if time.monotonic() >= deadline:
            return {**payload, "acceptance_observation_timeout": True}
        time.sleep(0.25)


def conversion(client, source: Path, target: str, output: Path, *, server_pid: int | None = None) -> dict:
    with MemoryObservation(server_pid) as memory:
        record = _conversion(client, source, target, output)
    record["memory_observation"] = memory.evidence
    return record


def _conversion(client, source: Path, target: str, output: Path) -> dict:
    started = time.perf_counter()
    with source.open("rb") as stream:
        response = client.post("/api/convert", files={"file": (source.name, stream)}, data={"target_format": target})
    if response.status_code != 200:
        try:
            details = response.json()
        except ValueError:
            details = {"error": "Non-JSON HTTP response", "content_type": response.headers.get("content-type")}
        return {"submission_status": response.status_code, "response": details, "result_sha256": None}
    task = response.json()
    status = wait_task(client, task)
    record = {"task_id": task["task_id"], "status": status, "elapsed_seconds": time.perf_counter() - started,
              "peak_memory_bytes": None, "result_sha256": None}
    if status["status"] == "done":
        result = client.get(task["result"])
        result.raise_for_status()
        output.write_bytes(result.content)
        record["result_sha256"] = digest(output)
    return record


def target_program_check(source: Path, output: Path | None = None, *, program: str = "word",
                         render_directory: Path | None = None) -> dict:
    if program not in {"word", "powerpoint"}:
        raise ValueError("Unsupported target-program driver")
    command = [shutil.which("pwsh") or "powershell", "-NoProfile", "-NonInteractive", "-File",
               str(Path(__file__).with_name(f"{program}-corpus.ps1")), "-InputPath", str(source.resolve())]
    command += ["-InspectOnly"] if output is None else ["-OutputPath", str(output.resolve())]
    if render_directory is not None:
        render_directory = render_directory.resolve()
        if program != "powerpoint" or (ROOT / ".textalchemy/acceptance").resolve() not in render_directory.parents:
            raise ValueError("Native renders require PowerPoint and the separate local acceptance directory")
        if render_directory.exists():
            raise ValueError("Use a fresh native render directory")
        command += ["-RenderDirectory", str(render_directory)]
    result = subprocess.run(command, check=True, capture_output=True, encoding="utf-8", timeout=90)
    record = json.loads(result.stdout)
    if record["artifact_sha256"] != digest(source) or (output is not None and record["edited_sha256"] != digest(output)):
        raise ValueError("Target-program evidence does not match the checked artifacts")
    return record


def word_check(source: Path, output: Path | None = None) -> dict:
    return target_program_check(source, output, program="word")


def compare_word_inventory(expected: dict, actual: dict) -> dict:
    """Measured checks stay independent; absent native observations remain unknown."""
    properties = {"normalized_text_equal": "normalized_text_sha256", "page_count_equal": "pages",
                  "table_count_equal": "tables", "heading_levels_equal": "heading_levels"}
    return {name: None if expected.get(key) is None or actual.get(key) is None else expected[key] == actual[key]
            for name, key in properties.items()}


def compare_powerpoint_inventory(expected: dict, actual: dict) -> dict:
    """Compare native observations by slide/shape order, without inventing object identity."""
    result = {"basis": "top-level-slide-and-shape-order", "full_geometry_acceptance": None}
    for key in ("slide_count", "slide_width", "slide_height"):
        result[key + "_equal"] = None if expected.get(key) is None or actual.get(key) is None else expected[key] == actual[key]
    for name, key in (("text", "normalized_text_sha256"), ("charts", "charts"), ("tables", "tables")):
        first = [s.get(key) for s in expected.get("slides", [])]
        second = [s.get(key) for s in actual.get("slides", [])]
        result[name + "_equal"] = None if not first or not second or None in first + second else first == second
    def boxes(inventory, keys):
        values = [[tuple(box.get(k) for k in keys) for box in slide["top_level_boxes"]]
                  for slide in inventory["slides"]]
        if any(None in box for slide in values for box in slide):
            raise KeyError("Unmeasured native shape property")
        return values

    try:
        result["ordered_boxes_equal"] = boxes(expected, ("left", "top", "width", "height", "rotation")) == boxes(
            actual, ("left", "top", "width", "height", "rotation"))
        result["ordered_types_equal"] = boxes(expected, ("type",)) == boxes(actual, ("type",))
    except KeyError:
        result["ordered_boxes_equal"] = result["ordered_types_equal"] = None
    return result


def run(manifest: dict, destination: Path, *, base_url: str, word: bool = False, powerpoint: bool = False,
        server_pid: int | None = None) -> dict:
    address = urlsplit(base_url)
    if address.scheme != "http" or address.hostname not in {"127.0.0.1", "localhost", "::1"} or address.username:
        raise ValueError("User-corpus acceptance must use a local Web server")
    MemoryObservation(server_pid)  # Validate the optional PID before copying any sources.
    selected = prepare(manifest, destination)
    evidence = {"schema": "user-corpus-acceptance-v1", "source_policy": "read-only-local-no-publication",
                "versions": {name: version(name) for name in ("textalchemy", "opendoc-model", "opendoc-formats")},
                "base_url": base_url, "cases": [], "target_program_acceptance": None}
    with httpx.Client(base_url=base_url, timeout=60, trust_env=False) as client:
        for item in selected:
            case = {"id": item["id"], "source_sha256": item["source_sha256"],
                    "source_format": item["copy"].suffix.lstrip("."), "cycle_format": item["cycle_format"], "cycles": []}
            evidence["cases"].append(case)
            try:
                source = item["copy"]
                native = item["cycle_format"]
                expected_word = None
                program = ("word" if word and native == "docx" and source.suffix == ".docx" else
                           "powerpoint" if powerpoint and native == "pptx" and source.suffix == ".pptx" else None)
                if word and native == "docx" and source.suffix == ".docx":
                    case["source_program_inspection"] = word_check(source)
                    expected_word = case["source_program_inspection"]["inventory"]
                elif program == "powerpoint" and source.suffix == ".pptx":
                    case["source_program_inspection"] = target_program_check(source, program=program)
                    expected_powerpoint = case["source_program_inspection"]["inventory"]
                for cycle in range(1, 3):
                    model = source.parent / f"cycle-{cycle}.json"
                    imported = conversion(client, source, "model", model, server_pid=server_pid)
                    observation = {"cycle": cycle, "import": imported, "export": None}
                    case["cycles"].append(observation)
                    if not model.is_file():
                        break
                    output = source.parent / f"cycle-{cycle}.{native}"
                    exported = conversion(client, model, native, output, server_pid=server_pid)
                    observation["export"] = exported
                    if not output.is_file():
                        break
                    source = output
                    if program == "word":
                        edited = source.parent / f"word-edited-{cycle}.docx"
                        observation["target_program"] = word_check(source, edited)
                        native_check = observation["target_program"]
                        observation["native_comparison"] = compare_word_inventory(expected_word, native_check["before"])
                        expected_word = native_check["after"]
                        source = edited
                    elif program == "powerpoint":
                        edited = source.parent / f"powerpoint-edited-{cycle}.pptx"
                        observation["target_program"] = target_program_check(source, edited, program=program)
                        native_check = observation["target_program"]
                        observation["native_comparison"] = compare_powerpoint_inventory(
                            expected_powerpoint, native_check["before"])
                        expected_powerpoint = native_check["after"]
                        source = edited
            except (subprocess.SubprocessError, httpx.HTTPError, ValueError) as error:
                case["acceptance_error"] = {"type": type(error).__name__, "returncode": getattr(error, "returncode", None)}
                raise
            finally:
                case["source_unchanged"] = digest(item["source"]) == item["source_sha256"]
                (destination / "acceptance.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8002")
    parser.add_argument("--word", action="store_true", help="Edit separate DOCX copies in installed Microsoft Word")
    parser.add_argument("--powerpoint", action="store_true", help="Edit separate PPTX copies in installed Microsoft PowerPoint")
    parser.add_argument("--server-pid", type=int, help="Sample the selected Windows Web process RSS; excludes child processes")
    args = parser.parse_args()
    result = run(json.loads(args.manifest.read_text(encoding="utf-8")), args.destination,
                 base_url=args.base_url, word=args.word, powerpoint=args.powerpoint, server_pid=args.server_pid)
    print(json.dumps({"cases": len(result["cases"]), "sources_unchanged": all(c["source_unchanged"] for c in result["cases"])}))


if __name__ == "__main__":
    main()
