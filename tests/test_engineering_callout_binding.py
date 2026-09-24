from nx_mcp.drawing_intelligence.engineering_callout_binding import (
    bind_callout_to_circle_entity,
)


def _regions():
    return [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 400, 400],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [200, 200],
                    "rings": [{"radius_px": 40}],
                }
            ],
        }
    ]


def test_callout_binds_only_when_one_line_bridges_text_and_circle_ring():
    result = bind_callout_to_circle_entity(
        [[20, 20], [100, 20], [100, 50], [20, 50]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[95, 45], [228, 228]],
                "candidate_only": True,
            }
        ],
        _regions(),
    )

    assert result["status"] == "bound"
    assert result["entity_key"] == "R1.C1"
    assert result["basis"] == "callout_bbox_to_collinear_segment_chain_to_geometry"


def test_nearest_circle_without_annotation_line_does_not_bind():
    result = bind_callout_to_circle_entity(
        [[150, 120], [210, 120], [210, 150], [150, 150]],
        [],
        _regions(),
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "no_unique_callout_to_circle_leader"


def test_line_touching_text_but_not_circle_ring_does_not_bind():
    result = bind_callout_to_circle_entity(
        [[20, 20], [100, 20], [100, 50], [20, 50]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[95, 45], [300, 300]],
                "candidate_only": True,
            }
        ],
        _regions(),
    )

    assert result["status"] == "unresolved"


def test_multiple_circle_targets_fail_closed():
    regions = _regions() + [
        {
            "region_id": "R2",
            "bbox_px": [400, 0, 400, 400],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [500, 200],
                    "rings": [{"radius_px": 40}],
                }
            ],
        }
    ]
    result = bind_callout_to_circle_entity(
        [[200, 20], [300, 20], [300, 50], [200, 50]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[220, 45], [228, 228]],
                "candidate_only": True,
            },
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[280, 45], [472, 228]],
                "candidate_only": True,
            },
        ],
        regions,
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "multiple_circle_entities_supported_by_annotation_lines"


def test_fragmented_collinear_leader_chain_binds_without_nearest_geometry_guess():
    regions = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 300, 300],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [220, 220],
                    "rings": [{"radius_px": 40}],
                }
            ],
        }
    ]

    result = bind_callout_to_circle_entity(
        [[20, 20], [100, 20], [100, 100], [20, 100]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[96, 96], [125, 125]],
                "candidate_only": True,
            },
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[130, 130], [155, 155]],
                "candidate_only": True,
            },
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[160, 160], [192, 192]],
                "candidate_only": True,
            },
        ],
        regions,
    )

    assert result["status"] == "bound"
    assert result["entity_key"] == "R1.C1"
    assert result["support"][0]["segment_count"] == 3
    assert result["support"][0]["line_indices"] == [0, 1, 2]


def test_short_forward_leader_extension_can_bind_unique_parallel_dash_pair():
    regions = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 300, 300],
            "circle_groups": [],
            "parallel_dash_pair_candidates": [
                {
                    "pair_id": "HP001",
                    "kind": "parallel_dash_pair_candidate",
                    "orientation": "vertical",
                    "axes_px": [200.0, 220.0],
                    "span_px": [160.0, 260.0],
                    "candidate_only": True,
                    "ownership_claimed": False,
                }
            ],
        }
    ]

    result = bind_callout_to_circle_entity(
        [[20, 20], [100, 20], [100, 60], [20, 60]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[95, 55], [180, 140]],
                "angle_deg": 45.0,
                "candidate_only": True,
            }
        ],
        regions,
    )

    assert result["status"] == "bound"
    assert result["entity_key"] == "R1.HP001"
    assert result["support"][0]["target_kind"] == "parallel_dash_pair"
    assert 0 < result["support"][0]["forward_extension_px"] <= 26

