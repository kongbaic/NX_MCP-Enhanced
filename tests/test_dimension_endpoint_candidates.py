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
    assert result["endpoints"][0]["physical_candidates"][0]["kind"] == (
        "profile_edge_candidate"
    )
    assert result["endpoints"][1]["physical_candidates"][0]["kind"] == (
        "circle_center_axis"
    )


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
    assert first["ignored_nonownership_anchors"][0]["kind"] == (
        "linear_pattern_axis"
    )


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
    assert result["reason"] == (
        "accepted_token_does_not_have_one_unique_global_assignment"
    )
