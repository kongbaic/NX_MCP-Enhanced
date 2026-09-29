from __future__ import annotations

from nx_mcp.drawing_intelligence.circle_datum_alignment import (
    derive_circle_overall_center_alignments,
)


def _boundary() -> dict[str, object]:
    return {
        "status": "resolved",
        "region_id": "R1",
        "view_kind": "front",
        "axis": "X",
        "candidate_id": "DG_WIDTH",
        "overall_dimension_value": 40.0,
        "anchors": [
            {
                "ref": "R1.structural.vertical.LEFT",
                "pixel_extreme_side": "min",
                "role": "overall_min",
                "position_px": 20.0,
            },
            {
                "ref": "R1.structural.vertical.RIGHT",
                "pixel_extreme_side": "max",
                "role": "overall_max",
                "position_px": 180.0,
            },
        ],
        "engineering_coordinate_inferred_from_pixels": False,
    }


def _regions(center_x: float = 100.0) -> list[dict[str, object]]:
    return [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 200, 300],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [center_x, 150.0],
                    "rings": [{"radius_px": 30}],
                }
            ],
        }
    ]


def _axis_line(position_px: float = 100.0) -> dict[str, object]:
    return {
        "region_id": "R1",
        "kind": "profile_edge_candidate",
        "ref": "R1.structural.vertical.CENTER_AXIS",
        "position_px": position_px,
        "source_orientation": "vertical",
        "span_px": [80, 220],
    }


def test_circle_on_unique_overall_center_axis_becomes_datum_alignment():
    items = derive_circle_overall_center_alignments(
        regions=_regions(center_x=101.0),
        region_views={"R1": "front"},
        boundaries=[_boundary()],
        profile_inventory=[_axis_line(position_px=100.0)],
    )

    assert len(items) == 1
    item = items[0]
    assert item["entity_key"] == "R1.C1"
    assert item["axis"] == "X"
    assert item["datum"] == "overall_center"
    assert item["axis_line_ref"] == "R1.structural.vertical.CENTER_AXIS"
    assert item["engineering_coordinate_inferred_from_pixels"] is False
    assert "coordinate_mm" not in item


def test_circle_center_alignment_fails_closed_without_axis_line_support():
    items = derive_circle_overall_center_alignments(
        regions=_regions(center_x=100.0),
        region_views={"R1": "front"},
        boundaries=[_boundary()],
        profile_inventory=[],
    )

    assert items == []


def test_circle_center_alignment_fails_closed_when_circle_is_visibly_off_center():
    items = derive_circle_overall_center_alignments(
        regions=_regions(center_x=112.0),
        region_views={"R1": "front"},
        boundaries=[_boundary()],
        profile_inventory=[_axis_line(position_px=100.0)],
    )

    assert items == []


def test_circle_center_alignment_fails_closed_with_multiple_axis_lines():
    items = derive_circle_overall_center_alignments(
        regions=_regions(center_x=100.0),
        region_views={"R1": "front"},
        boundaries=[_boundary()],
        profile_inventory=[
            _axis_line(position_px=99.0),
            {
                **_axis_line(position_px=101.0),
                "ref": "R1.structural.vertical.CENTER_AXIS_2",
            },
        ],
    )

    assert items == []

def test_front_view_z_center_can_become_overall_center_datum_alignment():
    boundary = {
        "status": "resolved",
        "region_id": "R1",
        "view_kind": "front",
        "axis": "Z",
        "candidate_id": "DG_HEIGHT",
        "overall_dimension_value": 80.0,
        "anchors": [
            {
                "ref": "R1.structural.horizontal.BOTTOM",
                "pixel_extreme_side": "min",
                "role": "overall_min",
                "position_px": 20.0,
            },
            {
                "ref": "R1.structural.horizontal.TOP",
                "pixel_extreme_side": "max",
                "role": "overall_max",
                "position_px": 180.0,
            },
        ],
        "engineering_coordinate_inferred_from_pixels": False,
    }
    regions = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 300, 200],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [150.0, 100.0],
                    "rings": [{"radius_px": 24}],
                }
            ],
        }
    ]
    axis_line = {
        "region_id": "R1",
        "kind": "profile_edge_candidate",
        "ref": "R1.structural.horizontal.CENTER_AXIS",
        "position_px": 100.0,
        "source_orientation": "horizontal",
        "span_px": [90, 210],
    }

    items = derive_circle_overall_center_alignments(
        regions=regions,
        region_views={"R1": "front"},
        boundaries=[boundary],
        profile_inventory=[axis_line],
    )

    assert len(items) == 1
    assert items[0]["entity_key"] == "R1.C1"
    assert items[0]["axis"] == "Z"
    assert items[0]["datum"] == "overall_center"
    assert items[0]["engineering_coordinate_inferred_from_pixels"] is False
    assert "coordinate_mm" not in items[0]


def test_side_view_z_center_can_become_overall_center_datum_alignment():
    boundary = {
        "status": "resolved",
        "region_id": "R1",
        "view_kind": "side",
        "axis": "Z",
        "candidate_id": "DG_HEIGHT",
        "overall_dimension_value": 80.0,
        "anchors": [
            {"ref": "BOTTOM", "position_px": 40.0},
            {"ref": "TOP", "position_px": 200.0},
        ],
        "engineering_coordinate_inferred_from_pixels": False,
    }
    regions = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 300, 240],
            "circle_groups": [
                {
                    "circle_group_id": "C2",
                    "center_px": [150.0, 120.0],
                    "rings": [{"radius_px": 20}],
                }
            ],
        }
    ]
    axis_line = {
        "region_id": "R1",
        "kind": "profile_edge_candidate",
        "ref": "R1.structural.horizontal.CENTER_AXIS",
        "position_px": 120.0,
        "source_orientation": "horizontal",
        "span_px": [100, 200],
    }

    items = derive_circle_overall_center_alignments(
        regions=regions,
        region_views={"R1": "side"},
        boundaries=[boundary],
        profile_inventory=[axis_line],
    )

    assert len(items) == 1
    assert items[0]["entity_key"] == "R1.C2"
    assert items[0]["axis"] == "Z"


def test_front_view_z_center_still_fails_closed_when_circle_is_off_center():
    boundary = {
        "status": "resolved",
        "region_id": "R1",
        "view_kind": "front",
        "axis": "Z",
        "candidate_id": "DG_HEIGHT",
        "overall_dimension_value": 80.0,
        "anchors": [
            {"ref": "BOTTOM", "position_px": 20.0},
            {"ref": "TOP", "position_px": 180.0},
        ],
        "engineering_coordinate_inferred_from_pixels": False,
    }
    regions = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 300, 200],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [150.0, 118.0],
                    "rings": [{"radius_px": 24}],
                }
            ],
        }
    ]
    axis_line = {
        "region_id": "R1",
        "kind": "profile_edge_candidate",
        "ref": "R1.structural.horizontal.CENTER_AXIS",
        "position_px": 100.0,
        "source_orientation": "horizontal",
        "span_px": [90, 210],
    }

    items = derive_circle_overall_center_alignments(
        regions=regions,
        region_views={"R1": "front"},
        boundaries=[boundary],
        profile_inventory=[axis_line],
    )

    assert items == []


def test_circle_center_alignment_accepts_unique_circle_center_witness_axis():
    candidates = [
        {
            "candidate_id": "DG_HALF",
            "region_id": "R1",
            "witness_anchor_evidence": [
                {
                    "witness_index": 1,
                    "nearest_anchors": [
                        {
                            "kind": "circle_center_axis",
                            "ref": "R1.C1.center_x",
                            "position_px": 100.0,
                        }
                    ],
                }
            ],
            "witness_line_evidence": [
                {
                    "witness_index": 1,
                    "source_lines": [
                        {
                            "orientation": "vertical",
                            "axis_px": 101.0,
                            "span_px": [80, 220],
                        },
                        {
                            "orientation": "vertical",
                            "axis_px": 108.0,
                            "span_px": [80, 120],
                        },
                    ],
                }
            ],
        }
    ]

    items = derive_circle_overall_center_alignments(
        regions=_regions(center_x=100.0),
        region_views={"R1": "front"},
        boundaries=[_boundary()],
        profile_inventory=[],
        candidates=candidates,
    )

    assert len(items) == 1
    item = items[0]
    assert item["entity_key"] == "R1.C1"
    assert item["axis"] == "X"
    assert item["datum"] == "overall_center"
    assert item["axis_line_support_kind"] == (
        "circle_center_anchored_witness_axis"
    )
    assert item["axis_line_candidate_id"] == "DG_HALF"
    assert item["engineering_coordinate_inferred_from_pixels"] is False
    assert "coordinate_mm" not in item


def test_circle_center_witness_axis_fails_closed_when_line_misses_circle_center():
    candidates = [
        {
            "candidate_id": "DG_HALF",
            "region_id": "R1",
            "witness_anchor_evidence": [
                {
                    "witness_index": 1,
                    "nearest_anchors": [
                        {
                            "kind": "circle_center_axis",
                            "ref": "R1.C1.center_x",
                            "position_px": 100.0,
                        }
                    ],
                }
            ],
            "witness_line_evidence": [
                {
                    "witness_index": 1,
                    "source_lines": [
                        {
                            "orientation": "vertical",
                            "axis_px": 100.0,
                            "span_px": [20, 60],
                        }
                    ],
                }
            ],
        }
    ]

    items = derive_circle_overall_center_alignments(
        regions=_regions(center_x=100.0),
        region_views={"R1": "front"},
        boundaries=[_boundary()],
        profile_inventory=[],
        candidates=candidates,
    )

    assert items == []

