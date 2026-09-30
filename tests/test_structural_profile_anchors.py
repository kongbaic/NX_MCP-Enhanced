from __future__ import annotations

from nx_mcp.drawing_intelligence.dimension_witness_anchors import (
    enrich_reduced_dimension_candidates,
)
from nx_mcp.drawing_intelligence.structural_profile_anchors import (
    derive_structural_profile_anchors,
    derive_structural_profile_vertex_anchors,
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


def test_structural_profile_anchors_preserve_axis_ink_continuity():
    raw = _raw()
    source_lines = raw["dimension_geometry_candidates"][0][
        "witness_line_evidence"
    ][0]["source_lines"]
    source_lines[0]["axis_ink_fraction"] = 0.88
    source_lines[0]["axis_ink_run_fraction"] = 0.77

    anchors = derive_structural_profile_anchors(
        raw,
        "R1",
        "horizontal",
    )
    by_position = {
        round(float(anchor["position_px"]), 3): anchor
        for anchor in anchors
    }

    assert by_position[20.0]["axis_ink_fraction"] == 0.88
    assert by_position[20.0]["axis_ink_run_fraction"] == 0.77


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

    assert all(
        "profile_edge_candidate" in kinds
        for kinds in kinds_by_witness
    )
    assert all(
        kinds <= {"profile_edge_candidate", "profile_vertex_candidate"}
        for kinds in kinds_by_witness
    )
    assert any(
        "profile_vertex_candidate" in kinds
        for kinds in kinds_by_witness
    )
    assert result["anchor_schema_version"] == "1.1"


def test_short_closed_edge_stays_profile_candidate():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1000, "height": 600},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 1000, 500],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_SHORT_CLOSED",
                "region_id": "R1",
                "orientation": "vertical",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 200.0,
                        "source_lines": [
                            _source("horizontal", 200.0, 100, 240),
                            _source("vertical", 100.0, 160, 240),
                            _source("vertical", 240.0, 160, 240),
                        ],
                    }
                ],
            }
        ],
    }

    anchors = derive_structural_profile_anchors(raw, "R1", "vertical")

    assert len(anchors) == 1
    assert anchors[0]["position_px"] == 200.0
    assert anchors[0]["span_local_norm"] == 0.14
    assert anchors[0]["junction_count"] >= 2
    assert anchors[0]["endpoint_junction_count"] >= 2


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



def test_dimension_extension_only_single_corner_is_not_profile():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1000, "height": 600},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 1000, 500],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_EXTENSION_ONLY",
                "region_id": "R1",
                "orientation": "vertical",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 200.0,
                        "source_lines": [
                            {
                                **_source("horizontal", 200.0, 100, 400),
                                "crosses_dimension_axis": True,
                            },
                            _source("vertical", 400.0, 200, 260),
                        ],
                    }
                ],
            }
        ],
    }

    anchors = derive_structural_profile_anchors(raw, "R1", "vertical")

    positions = {round(float(item["position_px"]), 1) for item in anchors}
    assert 200.0 not in positions


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


def test_weak_fragment_pair_cannot_suppress_physical_profile():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1200, "height": 700},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 1000, 500],
                "circle_groups": [],
                "linear_pattern_candidates": [
                    {
                        "orientation": "horizontal",
                        "axis_px": 100.0,
                        "span_px": [100, 500],
                        "dash_score": 0.52,
                        "kind": "dashed_or_centerline_candidate",
                    },
                    {
                        "orientation": "horizontal",
                        "axis_px": 106.0,
                        "span_px": [100, 500],
                        "dash_score": 0.63,
                        "kind": "dashed_or_centerline_candidate",
                    },
                ],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_WEAK_FRAGMENT_PAIR",
                "region_id": "R1",
                "orientation": "vertical",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 103.0,
                        "source_lines": [
                            _source("horizontal", 103.0, 100, 500),
                            _source("vertical", 100.0, 80, 125),
                            _source("vertical", 500.0, 80, 125),
                        ],
                    }
                ],
            }
        ],
    }

    anchors = derive_structural_profile_anchors(raw, "R1", "vertical")

    positions = {round(float(item["position_px"]), 1) for item in anchors}
    assert 103.0 in positions


def test_profile_line_near_hidden_pair_member_but_off_midpoint_survives():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1200, "height": 700},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 1000, 500],
                "circle_groups": [],
                "linear_pattern_candidates": [
                    {
                        "orientation": "horizontal",
                        "axis_px": 100.0,
                        "span_px": [100, 500],
                        "kind": "dashed_or_centerline_candidate",
                    },
                    {
                        "orientation": "horizontal",
                        "axis_px": 110.0,
                        "span_px": [100, 500],
                        "kind": "dashed_or_centerline_candidate",
                    },
                ],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_PROFILE_NEAR_PAIR",
                "region_id": "R1",
                "orientation": "vertical",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 107.8,
                        "source_lines": [
                            _source("horizontal", 107.8, 100, 500),
                            _source("vertical", 100.0, 80, 130),
                            _source("vertical", 500.0, 80, 130),
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
    assert 107.8 in positions


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



def test_strong_profile_topology_survives_incidental_linear_pattern_label():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1034, "height": 693},
        "regions": [
            {
                "region_id": "R2",
                "bbox_px": [617, 109, 250, 561],
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
                            _source("vertical", 620.667, 482, 667),
                            _source("vertical", 653.4, 485, 580),
                            _source("vertical", 785.8, 110, 667),
                            _source("horizontal", 481.0, 621, 700),
                            _source("horizontal", 550.0, 619, 787),
                            _source("horizontal", 580.0, 620, 703),
                        ],
                    }
                ],
            }
        ],
    }

    anchors = derive_structural_profile_anchors(raw, "R2", "horizontal")
    positions = {round(float(item["position_px"]), 1) for item in anchors}

    assert 653.4 in positions





def test_line_through_circle_center_is_not_physical_profile_boundary():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 1034, "height": 693},
        "regions": [
            {
                "region_id": "R2",
                "bbox_px": [617, 109, 250, 561],
                "circle_groups": [
                    {
                        "circle_group_id": "C1",
                        "center_px": [745.0, 234.0],
                        "rings": [{"radius_px": 28.0}],
                    }
                ],
                "linear_pattern_candidates": [],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_TOP",
                "region_id": "R2",
                "orientation": "horizontal",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 744.0,
                        "source_lines": [
                            _source("vertical", 703.7, 110, 482),
                            _source("vertical", 744.0, 150, 282),
                            _source("vertical", 785.8, 110, 667),
                            _source("horizontal", 160.0, 703, 786),
                            _source("horizontal", 315.0, 703, 786),
                        ],
                    }
                ],
            }
        ],
    }

    anchors = derive_structural_profile_anchors(raw, "R2", "horizontal")
    positions = {round(float(item["position_px"]), 1) for item in anchors}

    assert 744.0 not in positions


def test_structural_profile_vertices_come_from_independent_closed_edge():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 400, "height": 300},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 400, 300],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_GENERIC",
                "region_id": "R1",
                "orientation": "horizontal",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 40.0,
                        "source_lines": [
                            _source("horizontal", 120.0, 40, 300),
                            _source("vertical", 40.0, 100, 140),
                            _source("vertical", 300.0, 100, 140),
                        ],
                    }
                ],
            }
        ],
    }

    vertices = derive_structural_profile_vertex_anchors(
        raw,
        "R1",
        "horizontal",
    )

    assert [item["position_px"] for item in vertices] == [40.0, 300.0]
    assert all(item["vertex_transverse_px"] == 120.0 for item in vertices)
    assert all(item["kind"] == "profile_vertex_candidate" for item in vertices)
    assert all(item["ownership_claimed"] is False for item in vertices)


def test_dimension_crossing_only_profile_does_not_create_vertex_owner():
    raw = {
        "schema": "raw-evidence-v1",
        "image": {"width": 400, "height": 300},
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 400, 300],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "dimension_geometry_candidates": [
            {
                "candidate_id": "DG_GENERIC",
                "region_id": "R1",
                "orientation": "horizontal",
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 40.0,
                        "source_lines": [
                            {
                                **_source("horizontal", 120.0, 40, 300),
                                "crosses_dimension_axis": True,
                            },
                            _source("vertical", 40.0, 100, 140),
                            _source("vertical", 300.0, 100, 140),
                        ],
                    }
                ],
            }
        ],
    }

    assert (
        derive_structural_profile_vertex_anchors(
            raw,
            "R1",
            "horizontal",
        )
        == []
    )


def test_profile_vertex_anchor_rejects_unknown_dimension_orientation():
    with __import__("pytest").raises(ValueError):
        derive_structural_profile_vertex_anchors(
            _raw(),
            "R1",
            "diagonal",
        )
