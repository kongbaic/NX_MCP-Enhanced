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


def test_structural_profile_anchors_stay_geometry_only():
    anchors = derive_structural_profile_anchors(
        _raw(),
        "R1",
        "horizontal",
    )

    by_position = {round(float(anchor["position_px"]), 3): anchor for anchor in anchors}

    assert by_position[20.0]["kind"] == "profile_edge_candidate"
    assert by_position[20.0]["relative_extreme_side"] == "min"
    assert by_position[80.0]["kind"] == "profile_edge_candidate"
    assert "relative_extreme_side" not in by_position[80.0]
    assert by_position[160.0]["kind"] == "profile_edge_candidate"
    assert by_position[160.0]["relative_extreme_side"] == "max"

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
        {item["kind"] for item in witness["nearest_anchors"]} for witness in evidence
    ]

    assert kinds_by_witness == [
        {"profile_edge_candidate"},
        {"profile_edge_candidate"},
        {"profile_edge_candidate"},
    ]
    assert result["anchor_schema_version"] == "1.1"


def test_long_single_corner_stays_profile_candidate_without_claiming_shoulder():
    raw = {
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
                "candidate_id": "DG_SINGLE_CORNER",
                "region_id": "R1",
                "orientation": "vertical",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 60.0,
                        "source_lines": [
                            _source("horizontal", 60.0, 20, 100),
                            _source("vertical", 100.0, 60, 100),
                        ],
                    }
                ],
            }
        ],
    }

    anchors = derive_structural_profile_anchors(
        raw,
        "R1",
        "vertical",
    )

    assert len(anchors) == 1
    assert anchors[0]["kind"] == "profile_edge_candidate"
    assert anchors[0]["position_px"] == 60.0
    assert anchors[0]["candidate_only"] is True
    assert anchors[0]["ownership_claimed"] is False



def test_hidden_pair_midline_is_not_promoted_to_physical_profile_edge():
    raw = _raw()
    raw["regions"][0]["linear_pattern_candidates"] = [
        {
            "orientation": "horizontal",
            "axis_px": 80.0,
            "span_px": [20, 170],
            "kind": "dashed_or_centerline_candidate",
        },
        {
            "orientation": "horizontal",
            "axis_px": 120.0,
            "span_px": [22, 172],
            "kind": "dashed_or_centerline_candidate",
        },
    ]
    raw["dimension_geometry_candidates"][0]["witness_line_evidence"][0][
        "source_lines"
    ].extend(
        [
            _source("horizontal", 100.0, 20, 160),
            _source("vertical", 20.0, 80, 120),
            _source("vertical", 160.0, 80, 120),
        ]
    )

    anchors = derive_structural_profile_anchors(
        raw,
        "R1",
        "vertical",
    )

    positions = {round(float(item["position_px"]), 3) for item in anchors}
    assert 100.0 not in positions


def test_realistic_upper_hidden_pair_midline_is_suppressed_but_outer_profiles_survive():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1000, "height": 700},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [35, 138, 434, 533],
                "circle_groups": [],
                "linear_pattern_candidates": [
                    {
                        "orientation": "horizontal",
                        "axis_px": 216.6,
                        "span_px": [228, 378],
                        "kind": "dashed_or_centerline_candidate",
                    },
                    {
                        "orientation": "horizontal",
                        "axis_px": 249.8,
                        "span_px": [226, 376],
                        "kind": "dashed_or_centerline_candidate",
                    },
                ],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_REALISTIC",
                "region_id": "R1",
                "orientation": "vertical",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 234.0,
                        "source_lines": [
                            _source("horizontal", 200.5, 37, 226),
                            _source("horizontal", 234.0, 156, 285),
                            _source("horizontal", 483.7, 146, 403),
                            _source("horizontal", 550.6, 94, 465),
                            _source("vertical", 142.5, 199, 668),
                            _source("vertical", 406.5, 199, 668),
                        ],
                    }
                ],
            }
        ],
    }

    anchors = derive_structural_profile_anchors(
        raw,
        "R1",
        "vertical",
    )

    positions = {round(float(item["position_px"]), 1) for item in anchors}
    assert 234.0 not in positions
    assert 483.7 in positions
    assert 550.6 in positions



def test_line_coincident_with_linear_pattern_is_not_profile_boundary():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1000, "height": 700},
        "regions": [
            {
                "region_id": "R2",
                "bbox_px": [600, 100, 250, 560],
                "circle_groups": [],
                "linear_pattern_candidates": [
                    {
                        "orientation": "vertical",
                        "axis_px": 654.0,
                        "span_px": [455, 580],
                        "kind": "dashed_or_centerline_candidate",
                    }
                ],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG13",
                "region_id": "R2",
                "orientation": "horizontal",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 653.0,
                        "source_lines": [
                            _source("vertical", 653.4, 485, 580),
                            _source("vertical", 620.7, 482, 667),
                            _source("vertical", 785.8, 110, 667),
                            _source("horizontal", 485.0, 620, 703),
                            _source("horizontal", 580.0, 620, 703),
                        ],
                    }
                ],
            }
        ],
    }

    anchors = derive_structural_profile_anchors(raw, "R2", "horizontal")
    positions = {round(float(item["position_px"]), 1) for item in anchors}

    assert 653.4 not in positions
