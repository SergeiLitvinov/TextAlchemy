"""Independent local QA for PDF raster geometry and DjVu text; never application parsing."""

import argparse
import json
import subprocess
from pathlib import Path

from tools.acceptance.corpus import ROOT, digest


def compare_pdf(source: Path, result: Path) -> dict:
    import pymupdf
    from PIL import Image, ImageChops, ImageStat

    evidence = {"basis": "PyMuPDF-1x-RGB-all-pages", "full_visual_acceptance": None, "pages": []}
    with pymupdf.open(source) as before, pymupdf.open(result) as after:
        evidence.update(source_page_count=len(before), result_page_count=len(after), page_count_equal=len(before) == len(after))
        for index in range(min(len(before), len(after))):
            first, second = before[index], after[index]
            def boxes(page):
                return [list(box) for image in page.get_images() for box in page.get_image_rects(image[0])]
            a, b = first.get_pixmap(alpha=False), second.get_pixmap(alpha=False)
            measured = {"page": index + 1, "page_size_equal": list(first.rect) == list(second.rect),
                        "source_image_boxes": boxes(first), "result_image_boxes": boxes(second),
                        "source_text_empty": not first.get_text().strip(), "result_text_empty": not second.get_text().strip(),
                        "pixel_bytes_equal": a.width == b.width and a.height == b.height and a.samples == b.samples,
                        "mae_normalized": None}
            if (a.width, a.height) == (b.width, b.height):
                images = [Image.frombytes("RGB", (pix.width, pix.height), pix.samples) for pix in (a, b)]
                measured["mae_normalized"] = sum(ImageStat.Stat(ImageChops.difference(*images)).mean) / 3 / 255
            evidence["pages"].append(measured)
    return evidence


def compare_djvu_text(source: Path, result: Path) -> dict:
    extracted = subprocess.run(["djvutxt", str(source.resolve())], capture_output=True, check=True, timeout=60)
    expected = " ".join(extracted.stdout.decode("utf-8").split())
    actual = " ".join(result.read_text(encoding="utf-8").split())
    return {"basis": "DjVuLibre-djvutxt-whitespace-normalized", "normalized_text_equal": expected == actual,
            "source_text_empty": not expected, "source_characters": len(expected), "result_characters": len(actual),
            "page_geometry_verified": None}


def inspect_run(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    if (ROOT / ".textalchemy/acceptance").resolve() not in directory.parents:
        raise ValueError("Measurements must stay in the application's local acceptance directory")
    acceptance = json.loads((directory / "acceptance.json").read_text(encoding="utf-8"))
    evidence = {"schema": "scan-corpus-measurements-v1", "versions": acceptance["versions"], "cases": []}
    for case in acceptance["cases"]:
        identifier = case["id"]
        if not identifier.isascii() or not identifier.replace("-", "").isalnum():
            raise ValueError("Unsafe case identifier")
        folder = directory / identifier
        source = folder / ("source." + case["source_format"])
        if digest(source) != case["source_sha256"]:
            raise ValueError("Working source no longer matches the accepted snapshot")
        record = {"id": identifier, "source_sha256": digest(source), "cycles": []}
        for cycle in case["cycles"]:
            exported = cycle.get("export")
            result = folder / f"cycle-{cycle['cycle']}.{case['cycle_format']}"
            if not exported or not result.is_file():
                continue
            if digest(result) != exported["result_sha256"]:
                raise ValueError("Result no longer matches the recorded Web artifact")
            measured = compare_pdf(source, result) if source.suffix == result.suffix == ".pdf" else (
                compare_djvu_text(source, result) if source.suffix == ".djvu" and result.suffix == ".txt" else None)
            record["cycles"].append({"cycle": cycle["cycle"], "result_sha256": digest(result), "measurement": measured})
        evidence["cases"].append(record)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    args = parser.parse_args()
    measured = inspect_run(args.run_directory)
    with (args.run_directory / "scan-measurements.json").open("x", encoding="utf-8") as output:
        output.write(json.dumps(measured, indent=2))
    print(json.dumps({"cases": len(measured["cases"]), "scope": "local independent QA; no OCR or native viewer acceptance"}))


if __name__ == "__main__":
    main()
