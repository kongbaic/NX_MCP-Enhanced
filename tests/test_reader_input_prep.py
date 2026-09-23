from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from nx_mcp.drawing_intelligence.reader_input_prep import prepare_reader_input


def _write_synthetic_drawing(path: Path) -> None:
    image = np.full((650, 1200, 3), 255, np.uint8)

    cv2.rectangle(image, (100, 100), (520, 400), (0, 0, 0), 3)
    cv2.circle(image, (310, 240), 80, (0, 0, 0), 3)
    for x in range(180, 440, 28):
        cv2.line(image, (x, 240), (x + 14, 240), (0, 0, 0), 2)
    for y in range(140, 350, 28):
        cv2.line(image, (310, y), (310, y + 14), (0, 0, 0), 2)

    cv2.rectangle(image, (720, 120), (980, 410), (0, 0, 0), 3)
    for y in range(150, 380, 30):
        cv2.line(image, (800, y), (800, y + 15), (0, 0, 0), 2)
        cv2.line(image, (900, y), (900, y + 15), (0, 0, 0), 2)

    cv2.line(image, (100, 470), (520, 470), (0, 0, 0), 2)
    cv2.line(image, (100, 400), (100, 490), (0, 0, 0), 2)
    cv2.line(image, (520, 400), (520, 490), (0, 0, 0), 2)
    cv2.line(image, (180, 440), (440, 440), (0, 0, 0), 2)
    cv2.line(image, (180, 390), (180, 460), (0, 0, 0), 2)
    cv2.line(image, (440, 390), (440, 460), (0, 0, 0), 2)

    cv2.line(image, (580, 100), (580, 400), (0, 0, 0), 2)
    cv2.line(image, (520, 100), (600, 100), (0, 0, 0), 2)
    cv2.line(image, (520, 400), (600, 400), (0, 0, 0), 2)

    cv2.line(image, (720, 470), (980, 470), (0, 0, 0), 2)
    cv2.line(image, (720, 410), (720, 490), (0, 0, 0), 2)
    cv2.line(image, (980, 410), (980, 490), (0, 0, 0), 2)

    assert cv2.imwrite(str(path), image)


def test_prepare_reader_input_writes_one_shot_bundle(tmp_path: Path):
    image_path = tmp_path / "drawing.png"
    workspace = tmp_path / "workspace"
    _write_synthetic_drawing(image_path)

    stale_dir = workspace / "reader-crops"
    stale_dir.mkdir(parents=True)
    stale_path = stale_dir / "stale.png"
    stale_path.write_bytes(b"stale")

    result = prepare_reader_input(image_path, workspace)

    assert result["written"] is True
    assert result["schema"] == "reader-input-v1"
    assert not stale_path.exists()

    raw_path = workspace / "raw-evidence.json"
    aid_path = workspace / "reader-visual-aid.json"
    input_path = workspace / "reader-input.json"
    crops_dir = workspace / "reader-crops"

    assert raw_path.is_file()
    assert aid_path.is_file()
    assert input_path.is_file()
    assert crops_dir.is_dir()
    assert (crops_dir / "overview.png").is_file()
    assert (workspace / "reader-contact-sheet.png").is_file()

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "reader-input-v1"
    assert payload["source_drawing_authoritative"] is True
    assert payload["semantics_policy"] == ("geometry_only_no_engineering_claims")
    assert payload["summary"]["region_count"] >= 1
    assert payload["summary"]["bucket_count"] >= 1
    assert payload["summary"]["candidate_overlay_count"] == payload["summary"]["region_count"]
    assert payload["summary"]["crop_count"] == (
        1 + 2 * payload["summary"]["region_count"] + payload["summary"]["bucket_count"]
    )

    assert payload["reader_contract"] == {
        "read_source_drawing": True,
        "may_read_reader_input": True,
        "may_read_contact_sheet": True,
        "may_read_listed_crops": True,
        "prefer_contact_sheet": True,
        "agent_output_schema": "reader-observations-v1",
        "agent_writes_reader_capture_directly": False,
        "assembler_decides_engineering_semantics": False,
        "read_raw_evidence_directly": False,
        "scan_workspace": False,
        "scan_history": False,
        "create_additional_crops": False,
        "numeric_pixel_scale_matching": False,
        "visual_aid_decides_feature_identity": False,
        "visual_aid_decides_endpoint_ownership": False,
        "overflow_requires_source_drawing": True,
    }

    for region in payload["regions"]:
        crop_path = Path(region["crop_path"])
        overlay_path = Path(region["candidate_overlay_path"])
        assert crop_path.is_file()
        assert overlay_path.is_file()
        assert region["candidate_overlay_count"] >= 0
        if region["candidate_overlay_count"] > 0:
            crop = cv2.imread(str(crop_path))
            overlay = cv2.imread(str(overlay_path))
            assert crop is not None
            assert overlay is not None
            assert crop.shape == overlay.shape
            assert int(cv2.absdiff(crop, overlay).sum()) > 0
        assert "circle_groups" not in region
        assert "linear_pattern_candidates" not in region
        assert "circle_group_count" in region
        assert "linear_pattern_candidate_count" in region

    for bucket in payload["candidate_buckets"]:
        assert Path(bucket["crop_path"]).is_file()
        if bucket["status"] == "overflow":
            assert bucket["candidates"] == []
        else:
            assert len(bucket["candidates"]) <= 4
            for candidate in bucket["candidates"]:
                assert set(candidate) == {
                    "candidate_id",
                    "orientation",
                    "anchor_hints",
                }
                assert "axis_px" not in candidate
                assert "line_span_px" not in candidate
                assert "witness_positions_px" not in candidate

    assert result["timing_ms"]["total"] >= 0
    assert result["timing_ms"]["raw_evidence"] >= 0
    assert result["timing_ms"]["visual_aid"] >= 0
    assert result["timing_ms"]["crops"] >= 0


ROOT = Path(__file__).resolve().parents[1]


def test_prepare_reader_input_cli_e2e(tmp_path: Path):
    image_path = tmp_path / "drawing.png"
    workspace = tmp_path / "workspace-cli"
    _write_synthetic_drawing(image_path)

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "prepare-reader-input",
            str(image_path),
            str(workspace),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads(run.stdout)
    assert report["written"] is True
    assert report["schema"] == "reader-input-v1"
    assert report["summary"]["region_count"] >= 1
    assert report["summary"]["bucket_count"] >= 1
    assert Path(report["contact_sheet"]).is_file()
    assert (workspace / "reader-input.json").is_file()
    assert (workspace / "reader-crops" / "overview.png").is_file()
    assert (workspace / "reader-contact-sheet.png").is_file()
