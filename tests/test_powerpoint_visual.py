"""Image/witness consistency only; these synthetic records are not Office acceptance."""

import json

import pytest
from PIL import Image

from tools.acceptance.corpus import digest
from tools.acceptance.powerpoint_visual import compare, load_render


def own_render(directory, label, *, changed=False, count=2):
    folder = directory / label
    folder.mkdir()
    files = []
    for slide in range(1, count + 1):
        image = Image.new("RGB", (10, 8), "white")
        if changed and slide == 2:
            image.putpixel((0, 0), (0, 0, 0))
        path = folder / f"slide-{slide:03d}.png"
        image.save(path)
        files.append({"slide": slide, "file": path.name, "sha256": digest(path)})
    record = {"input_unchanged": True, "driver": "powerpoint-com", "artifact_sha256": "a" * 64,
              "program": {"name": "Own synthetic QA witness", "version": "1", "build": "own"},
              "inventory": {"slide_count": count}, "native_render": {"basis": "PowerPoint-Slide.Export-PNG",
              "scope": "all-slides-before-QA-edit", "files": files, "width": 10, "height": 8}}
    (directory / f"{label}.json").write_text(json.dumps(record))
    return record


def test_all_slides_are_compared_and_small_change_is_not_hidden(tmp_path):
    own_render(tmp_path, "source")
    own_render(tmp_path, "result", changed=True)
    evidence = compare(tmp_path, "source", "result")
    assert evidence["all_slides_compared"] and evidence["all_pixels_equal"] is False
    assert evidence["slides"][0]["pixels_equal"]
    assert evidence["slides"][1]["changed_pixel_fraction"] == pytest.approx(1 / 80)
    assert evidence["slides"][1]["mae_normalized"] == pytest.approx(1 / 80)
    assert evidence["full_visual_acceptance"] is None


def test_missing_slide_is_not_full_visual_acceptance(tmp_path):
    own_render(tmp_path, "source")
    own_render(tmp_path, "result", count=1)
    evidence = compare(tmp_path, "source", "result")
    assert not evidence["all_slides_compared"] and evidence["all_pixels_equal"] is None


@pytest.mark.parametrize("failure", ["hash", "unsafe-path", "missing-slide", "program", "dimensions"])
def test_inconsistent_native_witness_is_rejected(tmp_path, failure):
    own_render(tmp_path, "source")
    record = own_render(tmp_path, "result")
    if failure == "hash":
        record["native_render"]["files"][0]["sha256"] = "b" * 64
    elif failure == "unsafe-path":
        record["native_render"]["files"][0]["file"] = "../source/slide-001.png"
    elif failure == "missing-slide":
        record["native_render"]["files"].pop()
    elif failure == "program":
        record["program"]["version"] = "2"
    else:
        record["native_render"]["width"] = 11
    (tmp_path / "result.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        compare(tmp_path, "source", "result")


def test_changed_input_does_not_become_a_native_witness(tmp_path):
    record = own_render(tmp_path, "source")
    record["input_unchanged"] = False
    (tmp_path / "source.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="preservation"):
        load_render(tmp_path, "source")
