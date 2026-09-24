from __future__ import annotations

import pytest

from nx_mcp.drawing_intelligence.view_metric_calibration import (
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
        candidate["witness_anchor_evidence"][1]["nearest_anchors"][0][
            "relative_extreme_side"
        ] = right_side
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
