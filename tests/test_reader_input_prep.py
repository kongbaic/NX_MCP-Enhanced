from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from nx_mcp.drawing_intelligence.reader_input_prep import (
    _structural_bilateral_symmetry_hint,
    _structural_profile_symmetry_hint,
    _write_structural_context_image,
    prepare_reader_input,
)


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


def test_structural_profile_symmetry_hint_requires_two_mirrored_edge_pairs():
    inventory = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 20.0,
            "span_px": [10.0, 120.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 45.0,
            "span_px": [35.0, 95.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 155.0,
            "span_px": [35.0, 95.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 180.0,
            "span_px": [10.0, 120.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 70.0,
            "span_px": [15.0, 70.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 82.0,
            "span_px": [50.0, 115.0],
            "axis_tolerance_px": 2.0,
        },
    ]

    hint = _structural_profile_symmetry_hint(inventory, "R1")

    assert hint["status"] == "established"
    assert hint["axis_direction"] == "vertical"
    assert hint["axis_position_px"] == 100.0
    assert hint["method"] == "profile_edge_midpoint_consensus_v2"
    assert hint["vertical_pair_count"] == 2
    assert hint["horizontal_pair_count"] == 0
    assert hint["vertical_score"] == 1.0


def test_structural_profile_symmetry_hint_rejects_single_mirrored_edge_pair():
    inventory = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 20.0,
            "span_px": [10.0, 120.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 180.0,
            "span_px": [10.0, 120.0],
            "axis_tolerance_px": 2.0,
        },
    ]

    hint = _structural_profile_symmetry_hint(inventory, "R1")

    assert hint["status"] == "unresolved"
    assert hint["axis_direction"] is None


def test_structural_profile_symmetry_hint_fails_closed_on_axis_pair_count_tie():
    inventory = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 20.0,
            "span_px": [20.0, 180.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 60.0,
            "span_px": [40.0, 160.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 140.0,
            "span_px": [40.0, 160.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "vertical",
            "position_px": 180.0,
            "span_px": [20.0, 180.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "horizontal",
            "position_px": 30.0,
            "span_px": [20.0, 180.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "horizontal",
            "position_px": 70.0,
            "span_px": [40.0, 160.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "horizontal",
            "position_px": 130.0,
            "span_px": [40.0, 160.0],
            "axis_tolerance_px": 2.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "source_orientation": "horizontal",
            "position_px": 170.0,
            "span_px": [20.0, 180.0],
            "axis_tolerance_px": 2.0,
        },
    ]

    hint = _structural_profile_symmetry_hint(inventory, "R1")

    assert hint["status"] == "unresolved"
    assert hint["axis_direction"] is None
    assert hint["vertical_pair_count"] == 2
    assert hint["horizontal_pair_count"] == 2


def test_structural_bilateral_symmetry_hint_uses_topology_not_metric_scale():
    image = np.full((260, 420, 3), 255, np.uint8)
    left_right_profile = np.array(
        [
            [40, 30],
            [380, 30],
            [380, 95],
            [320, 95],
            [320, 225],
            [100, 225],
            [100, 95],
            [40, 95],
        ],
        np.int32,
    )
    cv2.fillPoly(image, [left_right_profile], (218, 218, 218))

    hint = _structural_bilateral_symmetry_hint(
        image,
        [0, 0, 420, 260],
        cv2,
        np,
    )

    assert hint["status"] == "established"
    assert hint["axis_direction"] == "vertical"
    assert hint["vertical_score"] > hint["horizontal_score"]
    assert hint["score_margin"] >= 0.15


def test_structural_bilateral_symmetry_hint_fails_closed_when_axes_tie():
    image = np.full((240, 240, 3), 255, np.uint8)
    cv2.rectangle(image, (40, 40), (200, 200), (218, 218, 218), -1)

    hint = _structural_bilateral_symmetry_hint(
        image,
        [0, 0, 240, 240],
        cv2,
        np,
    )

    assert hint["status"] == "unresolved"
    assert hint["axis_direction"] is None



def test_structural_context_image_marks_established_topology_axis(tmp_path: Path):
    image = np.full((180, 260, 3), 255, np.uint8)
    output = tmp_path / "structural-context.png"
    hint = {
        "status": "established",
        "axis_direction": "vertical",
        "method": "foreground_mirror_consensus_v1",
    }

    _write_structural_context_image(
        image,
        output,
        [40, 30, 180, 120],
        cv2,
        hint,
    )

    rendered = cv2.imread(str(output))
    assert rendered is not None
    axis_x = 40 + 180 // 2
    axis_strip = rendered[30:150, axis_x - 2 : axis_x + 3]
    assert int(cv2.absdiff(axis_strip, image[30:150, axis_x - 2 : axis_x + 3]).sum()) > 0


def test_structural_context_image_uses_explicit_topology_axis_position(
    tmp_path: Path,
):
    image = np.full((180, 260, 3), 255, np.uint8)
    output = tmp_path / "structural-context-explicit-axis.png"
    hint = {
        "status": "established",
        "axis_direction": "vertical",
        "axis_position_px": 80.0,
        "method": "profile_edge_midpoint_consensus_v2",
    }

    _write_structural_context_image(
        image,
        output,
        [40, 30, 180, 120],
        cv2,
        hint,
    )

    rendered = cv2.imread(str(output))
    assert rendered is not None
    explicit_strip = rendered[45:135, 78:83]
    center_strip = rendered[45:135, 128:133]
    assert int(
        cv2.absdiff(explicit_strip, image[45:135, 78:83]).sum()
    ) > 0
    assert np.array_equal(
        center_strip,
        image[45:135, 128:133],
    )


def test_structural_context_image_does_not_mark_unresolved_topology_axis(tmp_path: Path):
    image = np.full((180, 260, 3), 255, np.uint8)
    output = tmp_path / "structural-context.png"
    hint = {
        "status": "unresolved",
        "axis_direction": None,
        "method": "foreground_mirror_consensus_v1",
    }

    _write_structural_context_image(
        image,
        output,
        [40, 30, 180, 120],
        cv2,
        hint,
    )

    rendered = cv2.imread(str(output))
    assert rendered is not None
    axis_x = 40 + 180 // 2
    axis_strip = rendered[45:135, axis_x - 2 : axis_x + 3]
    assert np.array_equal(
        axis_strip,
        image[45:135, axis_x - 2 : axis_x + 3],
    )

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
    assert (crops_dir / "structural-context-overview.png").is_file()
    assert (workspace / "reader-contact-sheet.png").is_file()

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "reader-input-v1"
    assert payload["source_drawing_authoritative"] is True
    assert payload["semantics_policy"] == ("geometry_only_no_engineering_claims")
    assert payload["summary"]["region_count"] >= 1
    assert payload["summary"]["bucket_count"] >= 1
    assert payload["summary"]["candidate_overlay_count"] == payload["summary"]["region_count"]
    assert payload["summary"]["structural_context_image_count"] == payload["summary"]["region_count"]
    assert payload["summary"]["shared_structural_context_image_count"] == 1
    assert payload["summary"]["crop_count"] == (
        2 + 3 * payload["summary"]["region_count"] + payload["summary"]["bucket_count"]
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

    source_image = cv2.imread(str(image_path))
    assert source_image is not None
    shared_context_path = Path(payload["structural_context_overview_path"])
    shared_context = cv2.imread(str(shared_context_path))
    assert shared_context is not None
    assert shared_context.shape == source_image.shape
    assert int(cv2.absdiff(shared_context, source_image).sum()) > 0

    for region in payload["regions"]:
        crop_path = Path(region["crop_path"])
        context_path = Path(region["structural_context_path"])
        overlay_path = Path(region["candidate_overlay_path"])
        assert crop_path.is_file()
        assert context_path.is_file()
        assert overlay_path.is_file()

        context_image = cv2.imread(str(context_path))
        assert context_image is not None
        assert context_image.shape == source_image.shape
        assert int(cv2.absdiff(context_image, source_image).sum()) > 0

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
        assert region["bilateral_symmetry_hint"]["method"] in {
            "foreground_mirror_consensus_v1",
            "profile_edge_mirror_consensus_v1",
            "profile_edge_midpoint_consensus_v2",
        }
        assert region["bilateral_symmetry_hint"]["status"] in {
            "established",
            "unresolved",
        }
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
