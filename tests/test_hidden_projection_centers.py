from __future__ import annotations

from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.confirmation import (
    ConfirmationAnswers,
    apply_confirmation_answers,
    build_confirmation_request,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.hidden_projection_centers import (
    derive_hidden_projection_center_candidates,
)
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.reader_observations import (
    ObservationDimension,
    ObservationDimensionEndpoint,
    ReaderObservations,
    assemble_reader_capture,
)


def _region() -> dict[str, object]:
    return {
        "region_id": "R1",
        "bbox_px": [0, 0, 400, 400],
        "circle_groups": [
            {
                "circle_group_id": "C_MAIN",
                "center_px": [200, 250],
                "rings": [{"radius_px": 40}],
            }
        ],
        "linear_pattern_candidates": [
            {
                "orientation": "horizontal",
                "axis_px": 100.0,
                "span_px": [120, 300],
                "kind": "dashed_or_centerline_candidate",
            },
            {
                "orientation": "horizontal",
                "axis_px": 140.0,
                "span_px": [122, 302],
                "kind": "dashed_or_centerline_candidate",
            },
        ],
    }


def _distance_candidate() -> dict[str, object]:
    return {
        "candidate_id": "DG_DISTANCE",
        "region_id": "R1",
        "orientation": "vertical",
        "accepted_token": "18",
        "global_proposal_token": "18",
        "decision_reason": "global_geometry_assignment_confirmed_by_local_roi",
        "wide_local_linear_tokens": ["18"],
        "global_assignments": [
            {
                "source_item_index": 4,
                "text": "18",
                "token": "18",
                "bbox": [
                    [320.0, 165.0],
                    [350.0, 165.0],
                    [350.0, 205.0],
                    [320.0, 205.0],
                ],
            }
        ],
        "witness_positions_px": [120.0, 250.0],
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "position_px": 120.0,
                "axis": "y",
                "nearest_anchors": [],
            },
            {
                "witness_index": 1,
                "position_px": 250.0,
                "axis": "y",
                "nearest_anchors": [
                    {
                        "kind": "circle_center_axis",
                        "ref": "R1.C_MAIN.center_y",
                        "position_px": 250.0,
                    }
                ],
            },
        ],
    }


def _profile_inventory() -> list[dict[str, object]]:
    return [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.horizontal.CENTERLIKE",
            "position_px": 120.0,
            "source_orientation": "horizontal",
            "span_px": [80, 310],
            "candidate_only": True,
            "ownership_claimed": False,
        }
    ]


def test_hidden_pair_midpoint_becomes_center_candidate_not_owner_claim():
    items = derive_hidden_projection_center_candidates(
        _distance_candidate(),
        region=_region(),
        view_kind="front",
        profile_inventory=_profile_inventory(),
    )

    assert len(items) == 1
    item = items[0]
    assert item["witness_index"] == 0
    assert item["kind"] == "hidden_projection_center_axis"
    assert item["position_px"] == 120.0
    assert item["feature_axis"] == "X"
    assert item["source_pattern_axes_px"] == [100.0, 140.0]
    assert item["ownership_claimed"] is False


def _report() -> dict[str, object]:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [],
            "routed_elsewhere_or_unclassified_observations": [],
        },
        "regions": [_region()],
        "annotation_line_candidates": [],
        "structural_profile_inventory": _profile_inventory(),
        "candidates": [_distance_candidate()],
    }


def _context() -> HybridAdapterContext:
    return HybridAdapterContext.model_validate(
        {
            "schema": "hybrid-adapter-context-v1",
            "region_views": [
                {
                    "region_id": "R1",
                    "view_kind": "front",
                    "evidence": ["structural:R1"],
                }
            ],
        }
    )


def test_ambiguous_profile_vs_hidden_center_is_exposed_to_one_confirmation():
    partial = adapt_hybrid_ocr_report(_report(), _context())
    dimension = next(
        item for item in partial.dimensions if item.key == "R1.DG_DISTANCE"
    )

    assert dimension.direction == -1
    assert dimension.endpoints[0].role == "unresolved"
    assert dimension.endpoints[0].unresolved_kind == "ambiguous_owner"
    assert len(dimension.endpoints[0].candidate_entity_keys) == 1
    hidden_key = dimension.endpoints[0].candidate_entity_keys[0]
    assert hidden_key.startswith("R1.HIDDEN_PAIR.horizontal.")
    assert dimension.endpoints[1].role == "entity_center"
    assert dimension.endpoints[1].entity_key == "R1.C_MAIN"

    hidden_value = next(
        item
        for item in partial.values
        if item.entity_key == hidden_key and item.field == "axis"
    )
    assert hidden_value.value == "X"

    main_z = ObservationDimension(
        key="R1.MAIN_Z",
        value=40,
        axis="Z",
        endpoints=[
            ObservationDimensionEndpoint(
                role="entity_center",
                entity_key="R1.C_MAIN",
                basis="circle_center",
                evidence=["test:main-center"],
            ),
            ObservationDimensionEndpoint(
                role="overall_min",
                evidence=["test:bottom"],
            ),
        ],
        evidence=["test:main-z"],
        required_for_modeling=True,
    )

    observations = ReaderObservations(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=partial.views,
        entities=partial.entities,
        values=partial.values,
        dimensions=[dimension, main_z],
    )
    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)

    request = build_confirmation_request(linked.evidence)
    assert request["eligible_for_user_confirmation"] is True
    assert request["question_count"] == 1
    question = request["questions"][0]
    first_endpoint = question["endpoints"][0]
    hidden_option = next(
        item
        for item in first_endpoint["options"]
        if item.get("evidence_candidate") is True
    )

    confirmed = apply_confirmation_answers(
        linked.evidence,
        ConfirmationAnswers(
            answers=[
                {
                    "confirmation_id": question["confirmation_id"],
                    "selected_option_ids": [hidden_option["option_id"]],
                }
            ]
        ),
    )
    compiled = compile_evidence_graph(confirmed)
    resolution = resolve_evidence_graph(compiled)

    hidden_feature = hidden_option["target"].split(".centerline.", 1)[0]
    main_feature = next(
        target.split(".centerline.", 1)[0]
        for target, value in resolution.values.items()
        if target.endswith(".centerline.z") and value == 40.0
    )
    assert hidden_feature != main_feature
    assert resolution.values[f"{hidden_feature}.centerline.z"] == 58.0



def test_multiple_near_equal_hidden_pairs_fail_closed():
    region = _region()
    region["linear_pattern_candidates"] = [
        {
            "orientation": "horizontal",
            "axis_px": 100.0,
            "span_px": [120, 300],
            "kind": "dashed_or_centerline_candidate",
        },
        {
            "orientation": "horizontal",
            "axis_px": 140.0,
            "span_px": [122, 302],
            "kind": "dashed_or_centerline_candidate",
        },
        {
            "orientation": "horizontal",
            "axis_px": 102.0,
            "span_px": [121, 301],
            "kind": "dashed_or_centerline_candidate",
        },
        {
            "orientation": "horizontal",
            "axis_px": 140.0,
            "span_px": [123, 303],
            "kind": "dashed_or_centerline_candidate",
        },
    ]

    items = derive_hidden_projection_center_candidates(
        _distance_candidate(),
        region=region,
        view_kind="front",
        profile_inventory=[],
    )

    assert items == []


def test_hidden_pair_rejects_weak_midpoint_alignment_even_when_only_pair():
    region = _region()
    region["linear_pattern_candidates"] = [
        {
            "orientation": "horizontal",
            "axis_px": 90.0,
            "span_px": [120, 300],
            "kind": "dashed_or_centerline_candidate",
        },
        {
            "orientation": "horizontal",
            "axis_px": 130.0,
            "span_px": [122, 302],
            "kind": "dashed_or_centerline_candidate",
        },
    ]

    items = derive_hidden_projection_center_candidates(
        _distance_candidate(),
        region=region,
        view_kind="front",
        profile_inventory=[],
    )

    assert items == []
