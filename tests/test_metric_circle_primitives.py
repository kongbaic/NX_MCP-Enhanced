from __future__ import annotations

import pytest

from nx_mcp.drawing_intelligence.metric_circle_primitives import (
    derive_metric_circle_primitives,
)


def _calibration(
    axis: str,
    *,
    mm_per_px: float,
    offset_mm: float,
) -> dict[str, object]:
    return {
        "region_id": "R1",
        "view_kind": "front",
        "axis": axis,
        "candidate_id": f"DG_{axis}",
        "mm_per_px": mm_per_px,
        "offset_mm": offset_mm,
    }


def _regions(rings: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    return [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 400, 300],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [200, 150],
                    "rings": rings or [{"radius_px": 40}],
                }
            ],
        }
    ]


def _bound_callout(
    facts: dict[str, object],
) -> dict[str, object]:
    return {
        "source_item_index": 7,
        "facts": facts,
        "binding": {
            "status": "bound",
            "entity_key": "R1.C1",
            "basis": "callout_bbox_to_collinear_segment_chain_to_circle_ring",
        },
    }


def test_metric_circle_uses_two_axis_calibrations_for_center_only():
    result = derive_metric_circle_primitives(
        regions=_regions(),
        region_views={"R1": "front"},
        calibrations=[
            _calibration("X", mm_per_px=0.2, offset_mm=-40.0),
            _calibration("Z", mm_per_px=0.33, offset_mm=-16.5),
        ],
        callout_ledger=[_bound_callout({"diameter": 20.0, "fit": "H7"})],
    )

    assert result["unresolved"] == []
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["entity_key"] == "R1.C1"
    assert item["axis"] == "Y"
    assert item["center_mm"]["X"] == pytest.approx(0.0)
    assert item["center_mm"]["Z"] == pytest.approx(33.0)
    assert item["diameter_mm"] == 20.0
    assert item["engineering_facts"] == {"diameter": 20.0, "fit": "H7"}
    assert item["size_assignment_status"] == "single_ring_bound_diameter"
    assert item["pixel_radius_used_for_engineering_size"] is False


def test_metric_circle_never_converts_pixel_radius_into_engineering_diameter():
    result = derive_metric_circle_primitives(
        regions=_regions(),
        region_views={"R1": "front"},
        calibrations=[
            _calibration("X", mm_per_px=0.2, offset_mm=-40.0),
            _calibration("Z", mm_per_px=0.33, offset_mm=-16.5),
        ],
        callout_ledger=[],
    )

    item = result["items"][0]
    assert item["diameter_mm"] is None
    assert item["size_assignment_status"] == "missing_engineering_size"
    assert item["rings"][0]["radius_px"] == 40
    assert item["pixel_radius_used_for_engineering_size"] is False


def test_metric_concentric_group_does_not_assign_group_diameter_to_one_ring():
    result = derive_metric_circle_primitives(
        regions=_regions(
            [
                {"radius_px": 20},
                {"radius_px": 40},
            ]
        ),
        region_views={"R1": "front"},
        calibrations=[
            _calibration("X", mm_per_px=0.2, offset_mm=-40.0),
            _calibration("Z", mm_per_px=0.33, offset_mm=-16.5),
        ],
        callout_ledger=[_bound_callout({"diameter": 20.0})],
    )

    item = result["items"][0]
    assert item["ring_count"] == 2
    assert item["diameter_mm"] is None
    assert item["engineering_facts"]["diameter"] == 20.0
    assert item["size_assignment_status"] == "group_level_diameter_ring_unresolved"


def test_metric_circle_fails_closed_without_both_transverse_calibrations():
    result = derive_metric_circle_primitives(
        regions=_regions(),
        region_views={"R1": "front"},
        calibrations=[
            _calibration("X", mm_per_px=0.2, offset_mm=-40.0),
        ],
        callout_ledger=[_bound_callout({"diameter": 20.0})],
    )

    assert result["items"] == []
    assert result["unresolved"] == [
        {
            "entity_key": "R1.C1",
            "region_id": "R1",
            "view_kind": "front",
            "reason": "missing_view_axis_calibration",
            "missing_axes": ["Z"],
            "basis": "fail_closed_metric_circle_center",
        }
    ]


def test_metric_circle_rejects_conflicting_bound_diameters():
    result = derive_metric_circle_primitives(
        regions=_regions(),
        region_views={"R1": "front"},
        calibrations=[
            _calibration("X", mm_per_px=0.2, offset_mm=-40.0),
            _calibration("Z", mm_per_px=0.33, offset_mm=-16.5),
        ],
        callout_ledger=[
            _bound_callout({"diameter": 20.0}),
            _bound_callout({"diameter": 22.0}),
        ],
    )

    item = result["items"][0]
    assert item["diameter_mm"] is None
    assert item["engineering_fact_conflicts"] == {
        "diameter": [20.0, 22.0]
    }
    assert item["size_assignment_status"] == "conflicting_bound_diameter"
