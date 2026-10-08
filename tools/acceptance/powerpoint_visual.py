"""Compare every native PowerPoint PNG without treating pixel differences as quality percentages."""

import argparse
import json
import re
from pathlib import Path

from tools.acceptance.corpus import ROOT, digest


def load_render(directory: Path, label: str) -> tuple[dict, list[Path]]:
    record = json.loads((directory / f"{label}.json").read_text(encoding="utf-8"))
    if not record.get("input_unchanged") or record.get("driver") != "powerpoint-com":
        raise ValueError("Native input preservation and driver must be recorded")
    native = record["native_render"]
    if native["basis"] != "PowerPoint-Slide.Export-PNG" or native["scope"] != "all-slides-before-QA-edit":
        raise ValueError("Unknown render basis or scope")
    expected_count = record["inventory"]["slide_count"]
    files = native["files"]
    if len(files) != expected_count or [item["slide"] for item in files] != list(range(1, expected_count + 1)):
        raise ValueError("Native render does not cover every slide in order")
    paths = []
    for item in files:
        if not re.fullmatch(r"slide-[0-9]{3,}\.png", item["file"]) or item["file"] != f"slide-{item['slide']:03d}.png":
            raise ValueError("Unsafe or inconsistent native render filename")
        path = directory / label / item["file"]
        if digest(path) != item["sha256"]:
            raise ValueError("Native image no longer matches the recorded render")
        paths.append(path)
    return record, paths


def compare(directory: Path, source_label: str, result_label: str) -> dict:
    from PIL import Image, ImageChops, ImageStat

    first, sources = load_render(directory, source_label)
    second, results = load_render(directory, result_label)
    if first["program"] != second["program"]:
        raise ValueError("Render program versions differ; comparison is not controlled")
    evidence = {"basis": "native-PowerPoint-PNG-all-slides-RGB", "program": first["program"],
                "source_artifact_sha256": first["artifact_sha256"], "result_artifact_sha256": second["artifact_sha256"],
                "source_label": source_label, "result_label": result_label, "source_slide_count": len(sources),
                "result_slide_count": len(results), "full_visual_acceptance": None, "slides": []}
    for index, (source, result) in enumerate(zip(sources, results), start=1):
        with Image.open(source) as a, Image.open(result) as b:
            for image, native in ((a, first["native_render"]), (b, second["native_render"])):
                if image.size != (native["width"], native["height"]):
                    raise ValueError("Image dimensions do not match the native render witness")
            measured = {"slide": index, "dimensions_equal": a.size == b.size, "pixels_equal": None,
                        "mae_normalized": None, "changed_pixel_fraction": None}
            if a.size == b.size:
                difference = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
                measured["pixels_equal"] = difference.getbbox() is None
                measured["mae_normalized"] = sum(ImageStat.Stat(difference).mean) / 3 / 255
                red, green, blue = difference.split()
                maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
                measured["changed_pixel_fraction"] = 1 - maximum.histogram()[0] / (a.width * a.height)
            evidence["slides"].append(measured)
    evidence["all_slides_compared"] = len(sources) == len(results) == len(evidence["slides"])
    evidence["all_pixels_equal"] = (all(s["pixels_equal"] is True for s in evidence["slides"])
                                     if evidence["all_slides_compared"] and evidence["slides"] else None)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve(strict=True)
    if (ROOT / ".textalchemy/acceptance").resolve() not in directory.parents:
        raise ValueError("Private visual comparisons must stay in the separate local acceptance directory")
    evidence = {"schema": "powerpoint-native-visual-v1", "comparisons": [
        compare(directory, "source", "cycle-1"), compare(directory, "edited-1", "cycle-2")]}
    with (directory / "visual-comparison.json").open("x", encoding="utf-8") as output:
        output.write(json.dumps(evidence, indent=2))
    print(json.dumps({"comparisons": len(evidence["comparisons"]),
                      "slides_compared": [item["all_slides_compared"] for item in evidence["comparisons"]],
                      "pixels_equal": [item["all_pixels_equal"] for item in evidence["comparisons"]]}))


if __name__ == "__main__":
    main()
