from nx_mcp.drawing_intelligence.engineering_callout_binding import (
    bind_callout_to_circle_entity,
    bind_callout_to_curve_candidate,
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


def _curve_candidates():
    return [
        {
            "kind": "curved_boundary_candidate",
            "curve_trace_px": [
                [160, 130],
                [170, 140],
                [181, 149],
                [193, 157],
                [206, 164],
            ],
            "candidate_only": True,
            "exterior_boundary_candidate": True,
            "curve_classification_basis": (
                "stable_cocircular_exterior_contour_turning"
            ),
        }
    ]


def test_callout_binds_only_to_one_allowed_curve_trace_through_leader():
    result = bind_callout_to_curve_candidate(
        [[20, 20], [100, 20], [100, 50], [20, 50]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[95, 45], [160, 130]],
                "candidate_only": True,
            }
        ],
        _curve_candidates(),
        allowed_curve_source_ids={"hybrid:curve-boundary:0"},
    )

    assert result["status"] == "bound"
    assert result["curve_source_id"] == "hybrid:curve-boundary:0"
    assert (
        result["basis"]
        == "callout_bbox_to_collinear_segment_chain_to_curve_trace"
    )
    assert result["engineering_coordinate_inferred_from_pixels"] is False
    assert result["pixel_geometry_used_for_identity_only"] is True


def test_curve_callout_does_not_bind_disallowed_or_nearby_curve_without_leader():
    disallowed = bind_callout_to_curve_candidate(
        [[20, 20], [100, 20], [100, 50], [20, 50]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[95, 45], [160, 130]],
                "candidate_only": True,
            }
        ],
        _curve_candidates(),
        allowed_curve_source_ids={"hybrid:curve-boundary:9"},
    )
    nearby_without_leader = bind_callout_to_curve_candidate(
        [[120, 90], [155, 90], [155, 120], [120, 120]],
        [],
        _curve_candidates(),
        allowed_curve_source_ids={"hybrid:curve-boundary:0"},
    )

    assert disallowed["status"] == "unresolved"
    assert nearby_without_leader["status"] == "unresolved"


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
    assert result["basis"] == "callout_bbox_to_collinear_segment_chain_to_circle_ring"


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



def test_leader_shaft_may_extend_a_bounded_distance_to_arrow_tip_on_circle():
    regions = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 320, 320],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [240, 220],
                    "rings": [{"radius_px": 40}],
                }
            ],
        }
    ]

    result = bind_callout_to_circle_entity(
        [[20, 20], [120, 20], [120, 100], [20, 100]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[115, 95], [185, 165]],
                "angle_deg": 45.0,
                "candidate_only": True,
            }
        ],
        regions,
    )

    assert result["status"] == "bound"
    support = result["support"][0]
    assert support["binding_mode"] == "bounded_arrow_extension_to_circle_ring"
    assert 0 < support["arrow_extension_px"] <= 38.5


def test_bounded_arrow_extension_does_not_reverse_or_snap_to_unrelated_circle():
    regions = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 320, 320],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [60, 60],
                    "rings": [{"radius_px": 30}],
                }
            ],
        }
    ]

    result = bind_callout_to_circle_entity(
        [[20, 120], [120, 120], [120, 180], [20, 180]],
        [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[115, 145], [180, 210]],
                "angle_deg": 45.0,
                "candidate_only": True,
            }
        ],
        regions,
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "no_unique_callout_to_circle_leader"
