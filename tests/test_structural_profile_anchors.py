from __future__ import annotations

from nx_mcp.drawing_intelligence.dimension_witness_anchors import (
    enrich_reduced_dimension_candidates,
)
from nx_mcp.drawing_intelligence.structural_profile_anchors import (
    derive_structural_profile_anchors,
)


def _source(
    orientation: str,
    axis: float,
    start: int,
    end: int,
) -> dict[str, object]:
    return {
        "orientation": orientation,
        "axis_px": axis,
        "span_px": [start, end],
        "span_length_px": end - start,
        "crosses_dimension_axis": False,
    }


def _raw() -> dict[str, object]:
    profile_lines = [
        _source("vertical", 20.0, 20, 180),
        _source("vertical", 80.0, 100, 180),
        _source("vertical", 160.0, 20, 180),
        _source("horizontal", 20.0, 20, 160),
        _source("horizontal", 100.0, 80, 160),
        _source("horizontal", 180.0, 20, 160),
        # Short annotation-like distractor: it must not become structural.
        _source("vertical", 120.0, 10, 35),
        _source("horizontal", 35.0, 120, 150),
    ]

    return {
        "schema": "raw-evidence-v1",
        "image": {"width": 200, "height": 200},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 200, 200],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_SYNTHETIC",
                "region_id": "R1",
                "orientation": "horizontal",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 20.0,
                        "source_lines": profile_lines,
                    }
                ],
            }
        ],
    }


def test_structural_profile_anchors_find_extremes_and_internal_shoulder():
    anchors = derive_structural_profile_anchors(
        _raw(),
        "R1",
        "horizontal",
    )

    by_position = {
        round(float(anchor["position_px"]), 3): anchor
        for anchor in anchors
    }

    assert by_position[20.0]["kind"] == "silhouette_extreme_candidate"
    assert by_position[20.0]["extreme_side"] == "min"
    assert by_position[80.0]["kind"] == "step_or_shoulder_candidate"
    assert by_position[160.0]["kind"] == "silhouette_extreme_candidate"
    assert by_position[160.0]["extreme_side"] == "max"

    assert 120.0 not in by_position
    assert all(anchor["candidate_only"] is True for anchor in anchors)
    assert all(anchor["ownership_claimed"] is False for anchor in anchors)


def test_structural_profile_anchors_flow_into_witness_evidence():
    reduced = {
        "dimensions": [
            {
                "bucket_id": "R1-horizontal-bottom",
                "candidates": [
                    {
                        "candidate_id": "DG_TARGET",
                        "region_id": "R1",
                        "orientation": "horizontal",
                        "witness_positions_px": [20.0, 80.0, 160.0],
                    }
                ],
            }
        ]
    }

    result = enrich_reduced_dimension_candidates(
        _raw(),
        reduced,
        nearest_count=3,
        max_distance_local_norm=0.04,
    )

    candidate = result["dimensions"][0]["candidates"][0]
    evidence = candidate["witness_anchor_evidence"]

    kinds_by_witness = [
        {item["kind"] for item in witness["nearest_anchors"]}
        for witness in evidence
    ]

    assert "silhouette_extreme_candidate" in kinds_by_witness[0]
    assert "step_or_shoulder_candidate" in kinds_by_witness[1]
    assert "silhouette_extreme_candidate" in kinds_by_witness[2]
    assert result["anchor_schema_version"] == "1.1"
