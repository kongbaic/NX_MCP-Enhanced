from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from nx_mcp.drawing_intelligence.dimension_witness_anchors import (
    enrich_reduced_dimension_candidates,
)


def _raw() -> dict:
    return {
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [100, 200, 400, 300],
                "circle_groups": [
                    {
                        "circle_group_id": "C1",
                        "center_px": [300, 320],
                    }
                ],
                "linear_pattern_candidates": [
                    {
                        "orientation": "vertical",
                        "axis_px": 180.0,
                        "kind": "dashed_or_centerline_candidate",
                        "dash_score": 0.8,
                    },
                    {
                        "orientation": "horizontal",
                        "axis_px": 260.0,
                        "kind": "dashed_or_centerline_candidate",
                        "dash_score": 0.7,
                    },
                ],
            }
        ]
    }


def _reduced() -> dict:
    return {
        "schema_version": "1.0",
        "dimensions": [
            {
                "dimension_id": "DH",
                "candidates": [
                    {
                        "candidate_id": "DGH",
                        "region_id": "R1",
                        "orientation": "horizontal",
                        "witness_positions_px": [182.0, 300.0],
                    }
                ],
            },
            {
                "dimension_id": "DV",
                "candidates": [
                    {
                        "candidate_id": "DGV",
                        "region_id": "R1",
                        "orientation": "vertical",
                        "witness_positions_px": [258.0, 320.0],
                    }
                ],
            },
        ],
    }


def test_horizontal_witness_uses_x_axis_geometry_only():
    result = enrich_reduced_dimension_candidates(_raw(), _reduced())
    candidate = result["dimensions"][0]["candidates"][0]
    first = candidate["witness_anchor_evidence"][0]

    assert first["axis"] == "x"
    assert first["nearest_anchors"][0]["kind"] == "linear_pattern_axis"
    assert first["nearest_anchors"][0]["position_px"] == 180.0
    assert first["nearest_anchors"][0]["distance_px"] == 2.0

    refs = {item["ref"] for item in first["nearest_anchors"]}
    assert "R1.linear_pattern.001" in refs
    assert "R1.linear_pattern.002" not in refs


def test_vertical_witness_uses_y_axis_geometry_only():
    result = enrich_reduced_dimension_candidates(_raw(), _reduced())
    candidate = result["dimensions"][1]["candidates"][0]
    first = candidate["witness_anchor_evidence"][0]

    assert first["axis"] == "y"
    assert first["nearest_anchors"][0]["kind"] == "linear_pattern_axis"
    assert first["nearest_anchors"][0]["position_px"] == 260.0
    assert first["nearest_anchors"][0]["distance_px"] == 2.0

    second = candidate["witness_anchor_evidence"][1]
    circle = next(
        item
        for item in second["nearest_anchors"]
        if item["kind"] == "circle_center_axis"
    )
    assert circle["ref"] == "R1.C1.center_y"
    assert circle["distance_px"] == 0.0


def test_anchor_enrichment_stays_geometry_only():
    reduced = _reduced()
    result = enrich_reduced_dimension_candidates(_raw(), reduced)

    assert "anchor_schema_version" not in reduced
    assert result["anchor_policy"] == (
        "geometry_only_no_engineering_ownership_claims"
    )
    assert result["anchor_summary"] == {
        "candidate_count": 2,
        "witness_count": 4,
        "nearest_anchor_count": 3,
        "max_distance_local_norm": 0.04,
    }

    allowed_kinds = {
        "region_bbox_edge",
        "circle_center_axis",
        "linear_pattern_axis",
    }
    for dimension in result["dimensions"]:
        for candidate in dimension["candidates"]:
            for witness in candidate["witness_anchor_evidence"]:
                assert {
                    item["kind"]
                    for item in witness["nearest_anchors"]
                } <= allowed_kinds
                assert all(
                    item["distance_local_norm"] <= 0.04
                    for item in witness["nearest_anchors"]
                )


ROOT = Path(__file__).resolve().parents[1]


def test_anchor_dimension_candidates_cli_e2e(tmp_path: Path):
    raw_path = tmp_path / "raw.json"
    reduced_path = tmp_path / "reduced.json"
    out_path = tmp_path / "anchored.json"

    raw_path.write_text(json.dumps(_raw()), encoding="utf-8")
    reduced_path.write_text(json.dumps(_reduced()), encoding="utf-8")

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "anchor-dimension-candidates",
            str(raw_path),
            str(reduced_path),
            str(out_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    output = json.loads(out_path.read_text(encoding="utf-8"))
    assert output["anchor_policy"] == (
        "geometry_only_no_engineering_ownership_claims"
    )
    assert output["anchor_summary"]["candidate_count"] == 2
    assert output["anchor_summary"]["witness_count"] == 4
    assert output["anchor_summary"]["max_distance_local_norm"] == 0.04
