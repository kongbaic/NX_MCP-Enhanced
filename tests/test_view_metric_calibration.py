from __future__ import annotations

import pytest

from nx_mcp.drawing_intelligence.view_metric_calibration import (
    derive_metric_profile_segments,
    derive_view_axis_boundaries,
    derive_view_metric_calibrations,
    metricize_profile_edge_candidates,
)


def _candidate(
    *,
    token: str = "40",
    left_side: str | None = "min",
    right_side: str | None = "max",
) -> dict[str, object]:
    left_anchor = {
        "kind": "profile_edge_candidate",
        "ref": "R1.structural.vertical.001",
        "position_px": 100.0,
        "source_orientation": "vertical",
        "span_px": [50, 350],
        "candidate_only": True,
        "ownership_claimed": False,
        "distance_px": 0.0,
        "distance_local_norm": 0.0,
    }
    right_anchor = {
        "kind": "profile_edge_candidate",
        "ref": "R1.structural.vertical.002",
        "position_px": 300.0,
        "source_orientation": "vertical",
        "span_px": [50, 350],
        "candidate_only": True,
        "ownership_claimed": False,
        "distance_px": 0.0,
        "distance_local_norm": 0.0,
    }
    if left_side is not None:
        left_anchor["relative_extreme_side"] = left_side
    if right_side is not None:
        right_anchor["relative_extreme_side"] = right_side

    return {
        "candidate_id": "DG_CAL",
        "region_id": "R1",
        "orientation": "horizontal",
        "accepted_token": token,
        "global_assignments": [
            {
                "token": token,
                "bbox": [
                    [180.0, 400.0],
                    [220.0, 400.0],
                    [220.0, 440.0],
                    [180.0, 440.0],
                ],
            }
        ],
        "witness_positions_px": [100.0, 300.0],
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "position_px": 100.0,
                "nearest_anchors": [left_anchor],
            },
            {
                "witness_index": 1,
                "position_px": 300.0,
                "nearest_anchors": [right_anchor],
            },
        ],
    }


def test_overall_profile_extremes_define_absolute_view_calibration():
    items = derive_view_metric_calibrations(
        candidates=[_candidate()],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0, "width_y": 32.0, "height_z": 66.0},
    )

    assert len(items) == 1
    item = items[0]
    assert item["region_id"] == "R1"
    assert item["axis"] == "X"
    assert item["candidate_id"] == "DG_CAL"
    assert item["min_anchor"]["coordinate_mm"] == -20.0
    assert item["max_anchor"]["coordinate_mm"] == 20.0
    assert item["mm_per_px"] == pytest.approx(0.2)
    assert item["offset_mm"] == pytest.approx(-40.0)
    assert item["basis"] == "overall_dimension_with_opposite_profile_extremes"


def test_internal_dimension_is_not_promoted_to_global_calibration():
    items = derive_view_metric_calibrations(
        candidates=[_candidate(token="24")],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0, "width_y": 32.0, "height_z": 66.0},
    )

    assert items == []


def test_missing_profile_extreme_side_fails_closed():
    items = derive_view_metric_calibrations(
        candidates=[_candidate(left_side=None)],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0, "width_y": 32.0, "height_z": 66.0},
    )

    assert items == []


def test_mismatched_overall_dimension_fails_closed():
    items = derive_view_metric_calibrations(
        candidates=[_candidate()],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 50.0, "width_y": 32.0, "height_z": 66.0},
    )

    assert items == []


def test_metricize_profile_edge_candidates_converts_only_calibrated_axis():
    candidate = _candidate()
    calibrations = derive_view_metric_calibrations(
        candidates=[candidate],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0, "width_y": 32.0, "height_z": 66.0},
    )

    edges = metricize_profile_edge_candidates(
        candidates=[candidate],
        calibrations=calibrations,
    )

    assert len(edges) == 2
    by_ref = {item["ref"]: item for item in edges}
    assert by_ref["R1.structural.vertical.001"]["axis"] == "X"
    assert by_ref["R1.structural.vertical.001"]["coordinate_mm"] == pytest.approx(-20.0)
    assert by_ref["R1.structural.vertical.002"]["coordinate_mm"] == pytest.approx(20.0)
    assert all(item["basis"] == "view_metric_calibration" for item in edges)


def test_metricize_profile_edge_candidates_does_not_invent_uncalibrated_axis():
    calibration_candidate = _candidate()
    calibrations = derive_view_metric_calibrations(
        candidates=[calibration_candidate],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0, "width_y": 32.0, "height_z": 66.0},
    )

    observed_candidate = _candidate()
    observed_candidate["witness_anchor_evidence"][0]["nearest_anchors"].append(
        {
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.horizontal.001",
            "position_px": 120.0,
            "source_orientation": "horizontal",
            "span_px": [100, 300],
        }
    )
    edges = metricize_profile_edge_candidates(
        candidates=[observed_candidate],
        calibrations=calibrations,
    )

    assert {item["ref"] for item in edges} == {
        "R1.structural.vertical.001",
        "R1.structural.vertical.002",
    }


def _conflict_candidate(
    *,
    local_tokens: list[str] | None = None,
    right_side: str | None = "max",
) -> dict[str, object]:
    candidate = _candidate(token="6")
    candidate["orientation"] = "vertical"
    candidate["accepted_token"] = None
    candidate["global_proposal_token"] = "6"
    candidate["decision_reason"] = "global_local_token_disagreement"
    candidate["wide_local_linear_tokens"] = local_tokens or ["66"]
    candidate["global_assignments"][0]["bbox"] = [
        [400.0, 180.0],
        [440.0, 180.0],
        [440.0, 220.0],
        [400.0, 220.0],
    ]
    candidate["witness_anchor_evidence"][0]["nearest_anchors"][0].update(
        {
            "ref": "R1.structural.horizontal.001",
            "source_orientation": "horizontal",
            "relative_extreme_side": "min",
        }
    )
    candidate["witness_anchor_evidence"][1]["nearest_anchors"][0].update(
        {
            "ref": "R1.structural.horizontal.004",
            "source_orientation": "horizontal",
        }
    )
    if right_side is None:
        candidate["witness_anchor_evidence"][1]["nearest_anchors"][0].pop(
            "relative_extreme_side",
            None,
        )
    else:
        candidate["witness_anchor_evidence"][1]["nearest_anchors"][0]["relative_extreme_side"] = (
            right_side
        )
    return candidate


def test_conflicting_ocr_can_calibrate_from_independent_overall_and_opposite_extremes():
    candidate = _conflict_candidate()

    items = derive_view_metric_calibrations(
        candidates=[candidate],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0, "width_y": 32.0, "height_z": 66.0},
    )

    assert candidate["accepted_token"] is None
    assert len(items) == 1
    item = items[0]
    assert item["axis"] == "Z"
    assert item["dimension_value"] == 66.0
    assert item["overall_dimension_value"] == 66.0
    assert item["min_anchor"]["coordinate_mm"] == 0.0
    assert item["max_anchor"]["coordinate_mm"] == 66.0
    assert item["dimension_value_source"] == "overall_dimension_context"
    assert item["spatial_label_token"] == "6"
    assert item["supporting_local_token"] == "66"
    assert item["ocr_conflict_preserved"] is True
    assert item["basis"] == (
        "overall_dimension_with_conflict_local_match_and_opposite_profile_extremes"
    )


def test_conflict_backed_calibration_rejects_local_value_that_does_not_match_overall():
    items = derive_view_metric_calibrations(
        candidates=[_conflict_candidate(local_tokens=["65"])],
        region_views={"R1": "front"},
        overall_dimensions={"height_z": 66.0},
    )

    assert items == []


def test_conflict_backed_calibration_rejects_multiple_local_linear_tokens():
    items = derive_view_metric_calibrations(
        candidates=[_conflict_candidate(local_tokens=["66", "6"])],
        region_views={"R1": "front"},
        overall_dimensions={"height_z": 66.0},
    )

    assert items == []


def test_conflict_backed_calibration_still_requires_opposite_profile_extremes():
    items = derive_view_metric_calibrations(
        candidates=[_conflict_candidate(right_side=None)],
        region_views={"R1": "front"},
        overall_dimensions={"height_z": 66.0},
    )

    assert items == []


def _metric_edge(
    ref: str,
    *,
    orientation: str,
    axis: str,
    position_px: float,
    coordinate_mm: float,
    span_px: list[float],
) -> dict[str, object]:
    return {
        "ref": ref,
        "region_id": "R1",
        "view_kind": "front",
        "axis": axis,
        "source_orientation": orientation,
        "position_px": position_px,
        "coordinate_mm": coordinate_mm,
        "span_px": span_px,
        "basis": "view_metric_calibration",
    }


def test_metric_profile_segments_use_junctions_instead_of_raw_span_endpoints():
    edges = [
        _metric_edge(
            "V_LEFT",
            orientation="vertical",
            axis="X",
            position_px=100,
            coordinate_mm=-20,
            span_px=[40, 260],
        ),
        _metric_edge(
            "V_RIGHT",
            orientation="vertical",
            axis="X",
            position_px=300,
            coordinate_mm=20,
            span_px=[40, 260],
        ),
        _metric_edge(
            "H_LOW",
            orientation="horizontal",
            axis="Z",
            position_px=80,
            coordinate_mm=0,
            span_px=[95, 305],
        ),
        _metric_edge(
            "H_HIGH",
            orientation="horizontal",
            axis="Z",
            position_px=220,
            coordinate_mm=66,
            span_px=[95, 305],
        ),
    ]

    result = derive_metric_profile_segments(
        metric_edges=edges,
        junction_tolerance_by_region={"R1": 5.0},
    )

    assert len(result["junctions"]) == 4
    assert len(result["segments"]) == 4
    assert result["unresolved_edges"] == []
    by_edge = {item["source_edge_ref"]: item for item in result["segments"]}
    assert by_edge["V_LEFT"]["start_mm"] == {"X": -20.0, "Z": 0.0}
    assert by_edge["V_LEFT"]["end_mm"] == {"X": -20.0, "Z": 66.0}
    assert by_edge["V_LEFT"]["length_mm"] == pytest.approx(66.0)
    assert by_edge["H_LOW"]["length_mm"] == pytest.approx(40.0)
    assert all(
        item["basis"] == "observed_profile_line_between_metric_junctions"
        for item in result["segments"]
    )


def test_metric_profile_segments_fail_closed_without_explicit_gap_tolerance():
    edges = [
        _metric_edge(
            "V_LEFT",
            orientation="vertical",
            axis="X",
            position_px=100,
            coordinate_mm=-20,
            span_px=[40, 260],
        ),
        _metric_edge(
            "V_RIGHT",
            orientation="vertical",
            axis="X",
            position_px=300,
            coordinate_mm=20,
            span_px=[40, 260],
        ),
        _metric_edge(
            "H_ONLY_NEAR",
            orientation="horizontal",
            axis="Z",
            position_px=80,
            coordinate_mm=0,
            span_px=[95, 296],
        ),
    ]

    strict = derive_metric_profile_segments(metric_edges=edges)
    tolerant = derive_metric_profile_segments(
        metric_edges=edges,
        junction_tolerance_by_region={"R1": 5.0},
    )

    assert len(strict["junctions"]) == 1
    assert strict["segments"] == []
    assert len(tolerant["junctions"]) == 2
    assert len(tolerant["segments"]) == 1
    assert tolerant["segments"][0]["source_edge_ref"] == "H_ONLY_NEAR"
    assert tolerant["segments"][0]["length_mm"] == pytest.approx(40.0)


def _overall_candidate_with_witness_pair(
    *,
    region_id: str = "R1",
    value: str = "40",
    witnesses: list[float],
) -> dict[str, object]:
    midpoint = sum(witnesses) / len(witnesses)
    return {
        "candidate_id": "DG_OVERALL",
        "region_id": region_id,
        "orientation": "horizontal",
        "axis_px": 50.0,
        "accepted_token": value,
        "global_assignments": [
            {
                "token": value,
                "bbox": [
                    [midpoint - 10.0, 40.0],
                    [midpoint + 10.0, 40.0],
                    [midpoint + 10.0, 60.0],
                    [midpoint - 10.0, 60.0],
                ],
            }
        ],
        "witness_positions_px": witnesses,
        "witness_anchor_evidence": [
            {
                "witness_index": index,
                "position_px": witness,
                "nearest_anchors": [],
            }
            for index, witness in enumerate(witnesses)
        ],
        "witness_line_evidence": [
            {
                "witness_index": index,
                "position_px": witness,
                "source_lines": [],
            }
            for index, witness in enumerate(witnesses)
        ],
    }


def test_profile_extreme_fallback_allows_matching_overall_witness_pair():
    profile_inventory = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.LEFT",
            "position_px": 100.0,
            "source_orientation": "vertical",
            "relative_extreme_side": "min",
            "axis_tolerance_px": 3.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.RIGHT",
            "position_px": 300.0,
            "source_orientation": "vertical",
            "relative_extreme_side": "max",
            "axis_tolerance_px": 3.0,
        },
    ]

    items = derive_view_axis_boundaries(
        candidates=[
            _overall_candidate_with_witness_pair(
                witnesses=[101.0, 299.0],
            )
        ],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0},
        profile_inventory=profile_inventory,
        region_overall_fact_axes={("R1", "X")},
    )

    assert [(item["region_id"], item["axis"]) for item in items] == [("R1", "X")]
    assert items[0]["basis"] == (
        "independent_overall_dimension_plus_unique_profile_extremes"
    )


def test_profile_extreme_fallback_rejects_conflicting_overall_witness_pair():
    profile_inventory = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.LEFT",
            "position_px": 100.0,
            "source_orientation": "vertical",
            "relative_extreme_side": "min",
            "axis_tolerance_px": 3.0,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.LOCAL_RIGHT",
            "position_px": 300.0,
            "source_orientation": "vertical",
            "relative_extreme_side": "max",
            "axis_tolerance_px": 3.0,
        },
    ]

    items = derive_view_axis_boundaries(
        candidates=[
            _overall_candidate_with_witness_pair(
                witnesses=[101.0, 420.0],
            )
        ],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0},
        profile_inventory=profile_inventory,
        region_overall_fact_axes={("R1", "X")},
    )

    assert items == []


def test_profile_extreme_fallback_requires_same_region_overall_fact_scope():
    profile_inventory = [
        {
            "region_id": region_id,
            "kind": "profile_edge_candidate",
            "ref": f"{region_id}.LEFT",
            "position_px": 100.0,
            "source_orientation": "vertical",
            "relative_extreme_side": "min",
        }
        for region_id in ("R1", "R2")
    ] + [
        {
            "region_id": region_id,
            "kind": "profile_edge_candidate",
            "ref": f"{region_id}.RIGHT",
            "position_px": 300.0,
            "source_orientation": "vertical",
            "relative_extreme_side": "max",
        }
        for region_id in ("R1", "R2")
    ]

    items = derive_view_axis_boundaries(
        candidates=[],
        region_views={"R1": "front", "R2": "front"},
        overall_dimensions={"length_x": 40.0},
        profile_inventory=profile_inventory,
        region_overall_fact_axes={("R1", "X")},
    )

    assert [(item["region_id"], item["axis"]) for item in items] == [("R1", "X")]
    assert items[0]["overall_fact_scope"] == "same_region_structural_evidence"


def _overlap_profile_edge(
    region_id,
    ref,
    *,
    position,
    span,
    orientation,
    side=None,
):
    item = {
        "region_id": region_id,
        "kind": "profile_edge_candidate",
        "ref": ref,
        "position_px": position,
        "source_orientation": orientation,
        "span_px": list(span),
    }
    if side is not None:
        item["relative_extreme_side"] = side
    return item


def test_overlapping_region_local_extreme_cannot_impersonate_global_overall_boundary():
    profile_inventory = [
        _overlap_profile_edge(
            "R1",
            "R1.TOP_LOCAL",
            position=296.0,
            span=[470.0, 950.0],
            orientation="horizontal",
            side="min",
        ),
        _overlap_profile_edge(
            "R1",
            "R1.BOTTOM",
            position=524.0,
            span=[395.0, 1060.0],
            orientation="horizontal",
            side="max",
        ),
        _overlap_profile_edge(
            "R1",
            "R1.SHARED_A",
            position=441.0,
            span=[338.0, 486.0],
            orientation="horizontal",
        ),
        _overlap_profile_edge(
            "R1",
            "R1.SHARED_B",
            position=472.0,
            span=[140.0, 454.0],
            orientation="vertical",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.TOP_GLOBAL",
            position=146.0,
            span=[470.0, 974.0],
            orientation="horizontal",
            side="min",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.BOTTOM",
            position=524.0,
            span=[395.0, 1060.0],
            orientation="horizontal",
            side="max",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.SHARED_A",
            position=441.0,
            span=[338.0, 486.0],
            orientation="horizontal",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.SHARED_B",
            position=472.0,
            span=[140.0, 454.0],
            orientation="vertical",
        ),
    ]

    items = derive_view_axis_boundaries(
        candidates=[],
        region_views={"R1": "front", "R2": "front"},
        overall_dimensions={"height_z": 75.0},
        profile_inventory=profile_inventory,
        region_overall_fact_axes={("R1", "Z"), ("R2", "Z")},
    )

    assert [(item["region_id"], item["axis"]) for item in items] == [
        ("R2", "Z")
    ]
    assert {
        (anchor["ref"], anchor["role"])
        for anchor in items[0]["anchors"]
    } == {
        ("R2.TOP_GLOBAL", "overall_max"),
        ("R2.BOTTOM", "overall_min"),
    }


def test_separate_same_kind_views_are_not_cross_region_reconciled_without_shared_raster_edges():
    profile_inventory = [
        _overlap_profile_edge(
            "R1",
            "R1.TOP",
            position=100.0,
            span=[10.0, 200.0],
            orientation="horizontal",
            side="min",
        ),
        _overlap_profile_edge(
            "R1",
            "R1.BOTTOM",
            position=300.0,
            span=[10.0, 200.0],
            orientation="horizontal",
            side="max",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.TOP",
            position=500.0,
            span=[400.0, 600.0],
            orientation="horizontal",
            side="min",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.BOTTOM",
            position=700.0,
            span=[400.0, 600.0],
            orientation="horizontal",
            side="max",
        ),
    ]

    items = derive_view_axis_boundaries(
        candidates=[],
        region_views={"R1": "front", "R2": "front"},
        overall_dimensions={"height_z": 75.0},
        profile_inventory=profile_inventory,
        region_overall_fact_axes={("R1", "Z"), ("R2", "Z")},
    )

    assert [(item["region_id"], item["axis"]) for item in items] == [
        ("R1", "Z"),
        ("R2", "Z"),
    ]


def test_overlapping_partial_regions_fail_closed_when_no_region_spans_global_extremes():
    profile_inventory = [
        _overlap_profile_edge(
            "R1",
            "R1.TOP",
            position=100.0,
            span=[10.0, 300.0],
            orientation="horizontal",
            side="min",
        ),
        _overlap_profile_edge(
            "R1",
            "R1.BOTTOM_LOCAL",
            position=300.0,
            span=[10.0, 300.0],
            orientation="horizontal",
            side="max",
        ),
        _overlap_profile_edge(
            "R1",
            "R1.SHARED_A",
            position=180.0,
            span=[20.0, 250.0],
            orientation="horizontal",
        ),
        _overlap_profile_edge(
            "R1",
            "R1.SHARED_B",
            position=220.0,
            span=[50.0, 280.0],
            orientation="vertical",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.TOP_LOCAL",
            position=200.0,
            span=[10.0, 300.0],
            orientation="horizontal",
            side="min",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.BOTTOM",
            position=400.0,
            span=[10.0, 300.0],
            orientation="horizontal",
            side="max",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.SHARED_A",
            position=180.0,
            span=[20.0, 250.0],
            orientation="horizontal",
        ),
        _overlap_profile_edge(
            "R2",
            "R2.SHARED_B",
            position=220.0,
            span=[50.0, 280.0],
            orientation="vertical",
        ),
    ]

    items = derive_view_axis_boundaries(
        candidates=[],
        region_views={"R1": "front", "R2": "front"},
        overall_dimensions={"height_z": 75.0},
        profile_inventory=profile_inventory,
        region_overall_fact_axes={("R1", "Z"), ("R2", "Z")},
    )

    assert items == []


def test_profile_extreme_fallback_rejects_annotation_only_region_without_overall_fact():
    items = derive_view_axis_boundaries(
        candidates=[],
        region_views={"R3": "front"},
        overall_dimensions={"length_x": 300.0, "height_z": 75.0},
        profile_inventory=[
            {
                "region_id": "R3",
                "kind": "profile_edge_candidate",
                "ref": "R3.LEFT",
                "position_px": 100.0,
                "source_orientation": "vertical",
                "relative_extreme_side": "min",
            },
            {
                "region_id": "R3",
                "kind": "profile_edge_candidate",
                "ref": "R3.RIGHT",
                "position_px": 300.0,
                "source_orientation": "vertical",
                "relative_extreme_side": "max",
            },
            {
                "region_id": "R3",
                "kind": "profile_edge_candidate",
                "ref": "R3.TOP",
                "position_px": 50.0,
                "source_orientation": "horizontal",
                "relative_extreme_side": "min",
            },
            {
                "region_id": "R3",
                "kind": "profile_edge_candidate",
                "ref": "R3.BOTTOM",
                "position_px": 250.0,
                "source_orientation": "horizontal",
                "relative_extreme_side": "max",
            },
        ],
        region_overall_fact_axes=set(),
    )

    assert items == []


def test_metricize_profile_inventory_includes_edges_not_referenced_by_dimensions():
    candidate = _candidate()
    calibrations = derive_view_metric_calibrations(
        candidates=[candidate],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0},
    )
    inventory = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.001",
            "position_px": 100.0,
            "source_orientation": "vertical",
            "span_px": [50, 350],
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.002",
            "position_px": 200.0,
            "source_orientation": "vertical",
            "span_px": [80, 220],
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.003",
            "position_px": 300.0,
            "source_orientation": "vertical",
            "span_px": [50, 350],
        },
    ]

    edges = metricize_profile_edge_candidates(
        candidates=[candidate],
        calibrations=calibrations,
        profile_inventory=inventory,
    )

    assert {item["ref"] for item in edges} == {
        "R1.structural.vertical.001",
        "R1.structural.vertical.002",
        "R1.structural.vertical.003",
    }
    by_ref = {item["ref"]: item for item in edges}
    assert by_ref["R1.structural.vertical.002"]["coordinate_mm"] == pytest.approx(0.0)
    assert all(item["source_scope"] == "full_structural_profile_inventory" for item in edges)


def test_metricize_profile_inventory_does_not_fall_back_to_witness_subset_when_present():
    candidate = _candidate()
    calibrations = derive_view_metric_calibrations(
        candidates=[candidate],
        region_views={"R1": "front"},
        overall_dimensions={"length_x": 40.0},
    )
    inventory = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.002",
            "position_px": 200.0,
            "source_orientation": "vertical",
            "span_px": [80, 220],
        }
    ]

    edges = metricize_profile_edge_candidates(
        candidates=[candidate],
        calibrations=calibrations,
        profile_inventory=inventory,
    )

    assert [item["ref"] for item in edges] == ["R1.structural.vertical.002"]
