from __future__ import annotations

from nx_mcp.drawing_intelligence.dimension_endpoint_candidates import (
    derive_dimension_endpoint_candidates,
)


def _profile(position: float) -> dict[str, object]:
    return {
        "kind": "profile_edge_candidate",
        "ref": f"profile:{position}",
        "position_px": position,
        "candidate_only": True,
        "ownership_claimed": False,
        "distance_px": 0.0,
        "distance_local_norm": 0.0,
    }


def _circle(position: float) -> dict[str, object]:
    return {
        "kind": "circle_center_axis",
        "ref": f"circle:{position}",
        "position_px": position,
        "distance_px": 0.0,
        "distance_local_norm": 0.0,
    }


def _candidate(
    *,
    orientation: str = "vertical",
    witnesses: list[float],
    text_coordinate: float,
    anchors: dict[int, list[dict[str, object]]],
    witness_lines: dict[int, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    if orientation == "vertical":
        bbox = [
            [400.0, text_coordinate - 10.0],
            [440.0, text_coordinate - 10.0],
            [440.0, text_coordinate + 10.0],
            [400.0, text_coordinate + 10.0],
        ]
    else:
        bbox = [
            [text_coordinate - 10.0, 400.0],
            [text_coordinate + 10.0, 400.0],
            [text_coordinate + 10.0, 440.0],
            [text_coordinate - 10.0, 440.0],
        ]

    return {
        "candidate_id": "DG_TEST",
        "orientation": orientation,
        "accepted_token": "18",
        "global_assignments": [
            {
                "token": "18",
                "bbox": bbox,
            }
        ],
        "witness_positions_px": witnesses,
        "witness_anchor_evidence": [
            {
                "witness_index": index,
                "position_px": value,
                "nearest_anchors": anchors.get(index, []),
            }
            for index, value in enumerate(witnesses)
        ],
        "witness_line_evidence": [
            {
                "witness_index": index,
                "position_px": value,
                "source_lines": (witness_lines or {}).get(index, []),
            }
            for index, value in enumerate(witnesses)
        ],
    }


def test_text_bracket_selects_adjacent_pair_without_using_dimension_value():
    result = derive_dimension_endpoint_candidates(
        _candidate(
            witnesses=[235.0, 315.3, 484.0, 550.7],
            text_coordinate=280.0,
            anchors={
                0: [_profile(234.0)],
                1: [_circle(315.0)],
                2: [_profile(483.7)],
                3: [_profile(550.6)],
            },
        )
    )

    assert result["status"] == "bracketed"
    assert result["selected_witness_indices"] == [0, 1]
    assert result["selected_witness_positions_px"] == [235.0, 315.3]
    assert result["numeric_value_used_for_geometry"] is False
    assert result["all_endpoint_candidates_unique"] is True
    assert result["endpoints"][0]["physical_candidates"][0]["kind"] == ("profile_edge_candidate")
    assert result["endpoints"][1]["physical_candidates"][0]["kind"] == ("circle_center_axis")


def test_profile_candidate_wins_without_treating_linear_pattern_as_owner():
    candidate = _candidate(
        orientation="horizontal",
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={
            0: [
                _profile(100.0),
                {
                    "kind": "linear_pattern_axis",
                    "ref": "pattern:100",
                    "position_px": 100.0,
                },
            ],
            1: [_profile(200.0)],
        },
    )

    result = derive_dimension_endpoint_candidates(candidate)

    assert result["all_endpoint_candidates_unique"] is True
    first = result["endpoints"][0]
    assert len(first["physical_candidates"]) == 1
    assert first["physical_candidates"][0]["kind"] == "profile_edge_candidate"
    assert first["ignored_nonownership_anchors"][0]["kind"] == ("linear_pattern_axis")


def test_exact_crossing_witness_profile_line_narrows_nearby_anchors():
    profile = {
        **_profile(110.0),
        "source_orientation": "vertical",
        "span_px": [20.0, 180.0],
    }
    nearby_circle = {
        **_circle(112.0),
        "distance_px": 2.0,
        "distance_local_norm": 0.01,
    }
    distant_profile = {
        **_profile(125.0),
        "source_orientation": "vertical",
        "span_px": [20.0, 180.0],
        "distance_px": 15.0,
        "distance_local_norm": 0.03,
    }

    result = derive_dimension_endpoint_candidates(
        _candidate(
            orientation="horizontal",
            witnesses=[110.0, 200.0],
            text_coordinate=150.0,
            anchors={
                0: [profile, nearby_circle, distant_profile],
                1: [_profile(200.0)],
            },
            witness_lines={
                0: [
                    {
                        "orientation": "vertical",
                        "axis_px": 110.0,
                        "span_px": [20.0, 180.0],
                        "crosses_dimension_axis": True,
                    }
                ]
            },
        )
    )

    first = result["endpoints"][0]
    assert first["status"] == "unique_physical_candidate"
    assert first["physical_candidates"] == [profile]
    assert first["ownership_narrowing_basis"] == (
        "exact_crossing_witness_profile_line_identity"
    )


def test_unique_collinear_structural_profile_continuation_narrows_vertex_ambiguity():
    profile = {
        **_profile(100.6),
        "source_orientation": "vertical",
        "span_px": [80.0, 180.0],
        "axis_tolerance_px": 2.0,
        "junction_tolerance_px": 5.0,
        "independent_geometry_source_count": 1,
    }
    vertex = {
        "kind": "profile_vertex_candidate",
        "ref": "R1.edge.vertex.min",
        "position_px": 100.0,
        "vertex_transverse_px": 121.0,
        "supporting_profile_orientation": "horizontal",
        "axis_tolerance_px": 3.0,
        "junction_tolerance_px": 5.0,
        "vertex_match_tolerance_px": 3.0,
    }
    candidate = _candidate(
        orientation="horizontal",
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={0: [profile, vertex], 1: [_profile(200.0)]},
        witness_lines={
            0: [
                {
                    "orientation": "vertical",
                    "axis_px": 100.0,
                    "span_px": [120.0, 180.0],
                    "crosses_dimension_axis": True,
                }
            ]
        },
    )
    candidate["axis_px"] = 175.0

    result = derive_dimension_endpoint_candidates(candidate)

    first = result["endpoints"][0]
    assert first["status"] == "unique_physical_candidate"
    assert first["physical_candidates"] == [profile]
    assert first["ownership_narrowing_basis"] == (
        "unique_collinear_crossing_witness_profile_continuation"
    )


def test_collinear_profile_without_independent_geometry_does_not_narrow_vertex_ambiguity():
    profile = {
        **_profile(100.6),
        "source_orientation": "vertical",
        "span_px": [80.0, 180.0],
        "axis_tolerance_px": 2.0,
        "junction_tolerance_px": 5.0,
        "independent_geometry_source_count": 0,
    }
    vertex = {
        "kind": "profile_vertex_candidate",
        "ref": "R1.edge.vertex.min",
        "position_px": 100.0,
        "vertex_transverse_px": 121.0,
        "supporting_profile_orientation": "horizontal",
        "axis_tolerance_px": 3.0,
        "junction_tolerance_px": 5.0,
        "vertex_match_tolerance_px": 3.0,
    }
    candidate = _candidate(
        orientation="horizontal",
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={0: [profile, vertex], 1: [_profile(200.0)]},
        witness_lines={
            0: [
                {
                    "orientation": "vertical",
                    "axis_px": 100.0,
                    "span_px": [120.0, 180.0],
                    "crosses_dimension_axis": True,
                }
            ]
        },
    )
    candidate["axis_px"] = 175.0

    result = derive_dimension_endpoint_candidates(candidate)

    first = result["endpoints"][0]
    assert first["status"] == "ambiguous_physical_candidates"
    assert len(first["physical_candidates"]) == 2
    assert first["ownership_narrowing_basis"] is None


def test_non_crossing_profile_line_does_not_narrow_ambiguous_candidates():
    profile = {
        **_profile(110.0),
        "source_orientation": "vertical",
        "span_px": [20.0, 180.0],
    }
    circle = _circle(110.0)

    result = derive_dimension_endpoint_candidates(
        _candidate(
            orientation="horizontal",
            witnesses=[110.0, 200.0],
            text_coordinate=150.0,
            anchors={0: [profile, circle], 1: [_profile(200.0)]},
            witness_lines={
                0: [
                    {
                        "orientation": "vertical",
                        "axis_px": 110.0,
                        "span_px": [20.0, 180.0],
                        "crosses_dimension_axis": False,
                    }
                ]
            },
        )
    )

    first = result["endpoints"][0]
    assert first["status"] == "ambiguous_physical_candidates"
    assert len(first["physical_candidates"]) == 2
    assert first["ownership_narrowing_basis"] is None


def test_nearest_profile_without_witness_terminal_contact_is_not_owner():
    far_profile = {
        **_profile(100.0),
        "source_orientation": "vertical",
        "span_px": [200.0, 280.0],
        "axis_tolerance_px": 3.0,
        "junction_tolerance_px": 5.0,
    }
    connected_profile = {
        **_profile(200.0),
        "source_orientation": "vertical",
        "span_px": [115.0, 180.0],
        "axis_tolerance_px": 3.0,
        "junction_tolerance_px": 5.0,
    }
    candidate = _candidate(
        orientation="horizontal",
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={0: [far_profile], 1: [connected_profile]},
        witness_lines={
            0: [
                {
                    "orientation": "vertical",
                    "axis_px": 100.0,
                    "span_px": [40.0, 120.0],
                    "crosses_dimension_axis": True,
                }
            ],
            1: [
                {
                    "orientation": "vertical",
                    "axis_px": 200.0,
                    "span_px": [40.0, 120.0],
                    "crosses_dimension_axis": True,
                }
            ],
        },
    )
    candidate["axis_px"] = 50.0

    result = derive_dimension_endpoint_candidates(candidate)

    first, second = result["endpoints"]
    assert first["status"] == "no_physical_candidate"
    assert first["physical_candidates"] == []
    assert first["ignored_nonownership_anchors"][0][
        "ownership_rejection_reason"
    ] == "profile_not_connected_to_witness_terminal"
    assert second["status"] == "unique_physical_candidate"
    assert second["physical_candidates"] == [connected_profile]


def test_profile_with_small_terminal_gap_remains_candidate():
    profile = {
        **_profile(100.0),
        "source_orientation": "vertical",
        "span_px": [124.0, 180.0],
        "axis_tolerance_px": 3.0,
        "junction_tolerance_px": 5.0,
    }
    candidate = _candidate(
        orientation="horizontal",
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={0: [profile], 1: [_profile(200.0)]},
        witness_lines={
            0: [
                {
                    "orientation": "vertical",
                    "axis_px": 100.0,
                    "span_px": [40.0, 120.0],
                    "crosses_dimension_axis": True,
                }
            ]
        },
    )
    candidate["axis_px"] = 50.0

    result = derive_dimension_endpoint_candidates(candidate)

    first = result["endpoints"][0]
    assert first["status"] == "unique_physical_candidate"
    assert first["physical_candidates"] == [profile]


def test_bracket_can_remain_unresolved_when_no_physical_anchor_exists():
    result = derive_dimension_endpoint_candidates(
        _candidate(
            orientation="horizontal",
            witnesses=[175.0, 370.0],
            text_coordinate=272.0,
            anchors={},
        )
    )

    assert result["status"] == "bracketed"
    assert result["selected_witness_indices"] == [0, 1]
    assert result["all_endpoint_candidates_unique"] is False
    assert [item["status"] for item in result["endpoints"]] == [
        "no_physical_candidate",
        "no_physical_candidate",
    ]


def test_duplicate_accepted_assignment_fails_closed():
    candidate = _candidate(
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={0: [_profile(100.0)], 1: [_profile(200.0)]},
    )
    candidate["global_assignments"].append(
        {
            "token": "18",
            "bbox": [
                [400.0, 140.0],
                [440.0, 140.0],
                [440.0, 160.0],
                [400.0, 160.0],
            ],
        }
    )

    result = derive_dimension_endpoint_candidates(candidate)

    assert result["status"] == "unresolved"
    assert result["reason"] == ("accepted_token_does_not_have_one_unique_global_assignment")


def test_profile_vertex_at_witness_terminal_is_physical_owner():
    vertex = {
        "kind": "profile_vertex_candidate",
        "ref": "R1.edge.vertex.min",
        "position_px": 100.0,
        "vertex_transverse_px": 120.0,
        "supporting_profile_orientation": "horizontal",
        "axis_tolerance_px": 3.0,
        "junction_tolerance_px": 5.0,
        "vertex_match_tolerance_px": 3.0,
    }
    candidate = _candidate(
        orientation="horizontal",
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={0: [vertex], 1: [_profile(200.0)]},
        witness_lines={
            0: [
                {
                    "orientation": "vertical",
                    "axis_px": 100.0,
                    "span_px": [50.0, 121.0],
                    "crosses_dimension_axis": True,
                }
            ]
        },
    )
    candidate["axis_px"] = 50.0

    result = derive_dimension_endpoint_candidates(candidate)

    first = result["endpoints"][0]
    assert first["status"] == "unique_physical_candidate"
    assert first["physical_candidates"] == [vertex]


def test_profile_vertex_without_terminal_contact_is_not_owner():
    vertex = {
        "kind": "profile_vertex_candidate",
        "ref": "R1.edge.vertex.min",
        "position_px": 100.0,
        "vertex_transverse_px": 160.0,
        "supporting_profile_orientation": "horizontal",
        "axis_tolerance_px": 3.0,
        "junction_tolerance_px": 5.0,
        "vertex_match_tolerance_px": 3.0,
    }
    candidate = _candidate(
        orientation="horizontal",
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={0: [vertex], 1: [_profile(200.0)]},
        witness_lines={
            0: [
                {
                    "orientation": "vertical",
                    "axis_px": 100.0,
                    "span_px": [50.0, 121.0],
                    "crosses_dimension_axis": True,
                }
            ]
        },
    )
    candidate["axis_px"] = 50.0

    result = derive_dimension_endpoint_candidates(candidate)

    first = result["endpoints"][0]
    assert first["status"] == "no_physical_candidate"
    assert first["physical_candidates"] == []
    assert first["ignored_nonownership_anchors"][0][
        "ownership_rejection_reason"
    ] == "profile_vertex_not_connected_to_witness_terminal"


def test_profile_vertex_filters_non_contact_witness_lines_before_accepting_owner():
    vertex = {
        "kind": "profile_vertex_candidate",
        "ref": "R1.edge.vertex.max",
        "position_px": 100.0,
        "vertex_transverse_px": 120.0,
        "supporting_profile_orientation": "vertical",
        "axis_tolerance_px": 3.0,
        "junction_tolerance_px": 5.0,
        "vertex_match_tolerance_px": 3.0,
    }
    candidate = _candidate(
        orientation="vertical",
        witnesses=[100.0, 200.0],
        text_coordinate=150.0,
        anchors={0: [vertex], 1: [_profile(200.0)]},
        witness_lines={
            0: [
                {
                    "orientation": "horizontal",
                    "axis_px": 100.0,
                    "span_px": [50.0, 121.0],
                    "crosses_dimension_axis": False,
                },
                {
                    "orientation": "vertical",
                    "axis_px": 100.0,
                    "span_px": [50.0, 121.0],
                    "crosses_dimension_axis": True,
                },
                {
                    "orientation": "horizontal",
                    "axis_px": "bad",
                    "span_px": [50.0, 121.0],
                    "crosses_dimension_axis": True,
                },
                {
                    "orientation": "horizontal",
                    "axis_px": 130.0,
                    "span_px": [50.0, 121.0],
                    "crosses_dimension_axis": True,
                },
                {
                    "orientation": "horizontal",
                    "axis_px": 100.0,
                    "span_px": [50.0, 121.0],
                    "crosses_dimension_axis": True,
                },
            ]
        },
    )
    candidate["axis_px"] = 50.0

    result = derive_dimension_endpoint_candidates(candidate)

    first = result["endpoints"][0]
    assert first["status"] == "unique_physical_candidate"
    assert first["physical_candidates"] == [vertex]



def _exterior_one_glyph_candidate() -> dict[str, object]:
    """A numeric glyph printed just beyond a two-owner dimension rail."""
    return {
        "candidate_id": "DG_EXTERNAL",
        "orientation": "horizontal",
        "axis_px": 160.0,
        "line_span_px": [737, 795],
        "accepted_token": "8",
        "global_assignments": [{
            "token": "8",
            "bbox": [[812, 120], [838, 120], [838, 156], [812, 156]],
            "exterior_single_digit_witness_proven": True,
        }],
        "witness_positions_px": [703.7, 744.0, 785.8],
        "witness_anchor_evidence": [
            {"witness_index": 0, "nearest_anchors": [
                {"kind": "profile_edge_candidate", "ref": "outside"},
            ]},
            {"witness_index": 1, "nearest_anchors": [
                {"kind": "circle_center_axis", "ref": "R2.C1.center_x"},
            ]},
            {"witness_index": 2, "nearest_anchors": [
                {"kind": "profile_edge_candidate", "ref": "R2.profile.right"},
            ]},
        ],
        "witness_line_evidence": [
            {
                "witness_index": index,
                "source_lines": [{
                    "orientation": "vertical",
                    "axis_px": position,
                    "span_px": [110, 200],
                    "crosses_dimension_axis": True,
                }],
            }
            for index, position in enumerate([703.7, 744.0, 785.8])
        ],
    }


def test_proven_exterior_one_glyph_selects_unique_witness_pair_without_metric_inference():
    result = derive_dimension_endpoint_candidates(_exterior_one_glyph_candidate())
    assert result["status"] == "bracketed"
    assert result["selection_basis"] == (
        "proven_exterior_label_unique_crossing_witness_pair"
    )
    assert result["selected_witness_indices"] == [1, 2]
    assert result["selected_witness_positions_px"] == [744.0, 785.8]
    assert result["all_endpoint_candidates_unique"] is True
    assert [e["physical_candidates"][0]["ref"] for e in result["endpoints"]] == [
        "R2.C1.center_x", "R2.profile.right"
    ]
    assert result["numeric_value_used_for_geometry"] is False


def test_exterior_witness_pair_fails_closed_without_complete_independent_proof():
    variants = (
        "missing_attestation", "different_text", "missing_crossing",
        "duplicate_owner", "three_rail_witnesses", "moved_text",
    )
    for variant in variants:
        candidate = _exterior_one_glyph_candidate()
        if variant == "missing_attestation":
            candidate["global_assignments"][0].pop(
                "exterior_single_digit_witness_proven"
            )
        elif variant == "different_text":
            candidate["global_assignments"][0]["token"] = "18"
            candidate["accepted_token"] = "18"
        elif variant == "missing_crossing":
            candidate["witness_line_evidence"][2]["source_lines"][0][
                "crosses_dimension_axis"
            ] = False
        elif variant == "duplicate_owner":
            candidate["witness_anchor_evidence"][2]["nearest_anchors"][0][
                "ref"
            ] = "R2.C1.center_x"
        elif variant == "three_rail_witnesses":
            candidate["line_span_px"] = [700, 795]
        elif variant == "moved_text":
            candidate["global_assignments"][0]["bbox"] = [
                [870, 120], [899, 120], [899, 156], [870, 156]
            ]
        result = derive_dimension_endpoint_candidates(candidate)
        assert result["status"] == "unresolved", variant
        assert result["reason"] == (
            "accepted_text_does_not_select_one_unique_adjacent_witness_pair"
        )
