"""A success log and plausible PNG header cannot prove that the image is usable."""

import io
import json
import runpy
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
STUDY = runpy.run_path(str(ROOT / "tests/integration/test_engineering_bracket.py"))


@pytest.mark.parametrize("damage", [None, "header_only", "missing_end"])
def test_bracket_image_evidence_requires_a_complete_png(tmp_path, damage):
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "gray").save(stream, format="PNG")
    valid = stream.getvalue()
    # Both corrupt variants retain the exact header and positive dimensions that
    # the original check accepted, even though the export log claims success.
    data = valid if damage is None else valid[:34] if damage == "header_only" else valid[:-12]
    names = STUDY["IMAGE_NAMES"]
    for name in names:
        (tmp_path / name).write_bytes(data)
    (tmp_path / "mechanical-artifacts.json").write_text(
        json.dumps({"visual_review": [{"name": name, "status": "PASS"} for name in names]}),
        encoding="utf-8",
    )
    check = STUDY["_png_evidence"](tmp_path)
    assert check["status"] == ("PASS" if damage is None else "FAIL")
    assert all(item["fully_decoded"] is (damage is None) for item in check["evidence"]["items"])
