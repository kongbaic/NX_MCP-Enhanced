from __future__ import annotations

from nx_mcp.drawing_intelligence.engineering_dimension_binding import (
    bind_callout_to_dimension_candidate,
)
from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.reader_observations import (
    ReaderObservations,
    assemble_reader_capture,
)


def _candidate(
    candidate_id: str,
    *,
    axis_px: float,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "region_id": "R2",
        "orientation": "vertical",
        "axis_px": axis_px,
        "line_span_px": [110, 190],
        "witness_positions_px": [90.0, 210.0],
        "witness_anchor_evidence": [],
        "global_assignments": [],
        "global_proposal_token": None,
        "wide_local_linear_tokens": [],
        "accepted_token": None,
        "decision_reason": "no_global_proposal",
    }


def test_diameter_callout_binds_unique_existing_dimension_geometry_candidate():
    binding = bind_callout_to_dimension_candidate(
        [
            [250.0, 105.0],
            [300.0, 105.0],
            [300.0, 195.0],
            [250.0, 195.0],
        ],
        [
            _candidate("DG_TARGET", axis_px=300.0),
            _candidate("DG_DISTRACTOR", axis_px=220.0),
        ],
        region_id="R2",
    )

    assert binding["status"] == "bound"
    assert binding["candidate_id"] == "DG_TARGET"
    assert binding["orientation"] == "vertical"
    assert binding["witness_positions_px"] == [90.0, 210.0]
    assert binding["projected_center_axis_px"] == 150.0
    assert binding["basis"] == (
        "callout_bbox_to_existing_dimension_geometry_candidate"
    )


def test_dimension_geometry_binding_fails_closed_without_unique_margin():
    binding = bind_callout_to_dimension_candidate(
        [
            [250.0, 105.0],
            [300.0, 105.0],
            [300.0, 195.0],
            [250.0, 195.0],
        ],
        [
            _candidate("DG_A", axis_px=300.0),
            _candidate("DG_B", axis_px=303.0),
        ],
        region_id="R2",
    )

    assert binding["status"] == "unresolved"
    assert binding["reason"] == (
        "multiple_dimension_geometry_candidates_without_margin"
    )


def _report() -> dict[str, object]:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [],
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 7,
                    "text": "∅20 H7",
                    "bbox": [
                        [250.0, 105.0],
                        [300.0, 105.0],
                        [300.0, 195.0],
                        [250.0, 195.0],
                    ],
                    "confidence": 0.99,
                }
            ],
        },
        "regions": [
            {
                "region_id": "R2",
                "bbox_px": [0, 0, 400, 300],
                "circle_groups": [],
            }
        ],
        "annotation_line_candidates": [],
        "candidates": [
            _candidate("DG_DIAMETER", axis_px=300.0),
            _candidate("DG_DISTRACTOR", axis_px=220.0),
        ],
    }


def test_adapter_materializes_diameter_projection_instead_of_advisory_callout():
    context = HybridAdapterContext.model_validate(
        {
            "schema": "hybrid-adapter-context-v1",
            "region_views": [
                {
                    "region_id": "R2",
                    "view_kind": "side",
                    "evidence": ["structural:R2"],
                }
            ],
        }
    )

    partial = adapt_hybrid_ocr_report(_report(), context)

    projection = next(
        item
        for item in partial.entities
        if item.key == "R2.DG_DIAMETER.DIAMETER_PROJECTION"
    )
    assert projection.shape == "hidden_parallel"

    assert {
        (item.entity_key, item.field): item.value
        for item in partial.values
    } == {
        ("R2.DG_DIAMETER.DIAMETER_PROJECTION", "diameter"): 20.0,
        ("R2.DG_DIAMETER.DIAMETER_PROJECTION", "fit"): "H7",
    }

    assert not [
        item
        for item in partial.unresolved
        if item.field == "engineering_callout_geometry_binding"
    ]

    ledger = next(
        item
        for item in partial.observations
        if item["kind"] == "hybrid_engineering_callout_ledger"
    )
    binding = ledger["items"][0]["binding"]
    assert binding["status"] == "dimension_backed"
    assert binding["candidate_id"] == "DG_DIAMETER"
    assert binding["projected_center_axis_px"] == 150.0



def _two_view_report(*, duplicate_circle: bool = False) -> dict[str, object]:
    report = _report()
    circles = [
        {
            "circle_group_id": "C_MAIN",
            "center_px": [100, 150],
            "rings": [{"radius_px": 30}],
        }
    ]
    if duplicate_circle:
        circles.append(
            {
                "circle_group_id": "C_AMBIGUOUS",
                "center_px": [180, 151],
                "rings": [{"radius_px": 25}],
            }
        )

    report["regions"] = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 200, 300],
            "circle_groups": circles,
        },
        {
            "region_id": "R2",
            "bbox_px": [200, 0, 200, 300],
            "circle_groups": [],
        },
    ]
    return report


def _two_view_context() -> HybridAdapterContext:
    return HybridAdapterContext.model_validate(
        {
            "schema": "hybrid-adapter-context-v1",
            "region_views": [
                {
                    "region_id": "R1",
                    "view_kind": "front",
                    "evidence": ["structural:R1"],
                },
                {
                    "region_id": "R2",
                    "view_kind": "side",
                    "evidence": ["structural:R2"],
                },
            ],
        }
    )


def test_unique_orthographic_circle_and_diameter_projection_merge_into_one_feature():
    partial = adapt_hybrid_ocr_report(
        _two_view_report(),
        _two_view_context(),
    )

    assert len(partial.associations) == 1
    association = partial.associations[0]
    assert association.entity_keys == [
        "R2.DG_DIAMETER.DIAMETER_PROJECTION",
        "R1.C_MAIN",
    ]
    assert association.basis == [
        "projection_alignment",
        "unique_orthographic_counterpart",
    ]

    observations = ReaderObservations(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=partial.views,
        entities=partial.entities,
        associations=partial.associations,
        values=partial.values,
    )
    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)

    projection_entity_id = next(
        item.id
        for item in capture.entities
        if item.shape == "hidden_parallel"
    )
    circle_entity_id = next(
        item.id
        for item in capture.entities
        if item.shape == "circle"
    )
    assert linked.entity_to_feature[projection_entity_id] == (
        linked.entity_to_feature[circle_entity_id]
    )

    compiled = compile_evidence_graph(linked.evidence)
    feature_id = linked.entity_to_feature[circle_entity_id]
    direct = {
        item.target: item.value
        for item in compiled.direct_values
    }
    assert direct[f"feature:{feature_id}.diameter"] == 20.0
    assert direct[f"feature:{feature_id}.fit"] == "H7"
    assert direct[f"feature:{feature_id}.axis"] == "Y"


def test_multiple_aligned_circles_fail_closed_instead_of_auto_associating():
    partial = adapt_hybrid_ocr_report(
        _two_view_report(duplicate_circle=True),
        _two_view_context(),
    )

    assert partial.associations == []
    blockers = [
        item
        for item in partial.unresolved
        if item.kind == "cross_view_identity"
        and item.required_for_modeling
    ]
    assert len(blockers) == 1
    assert blockers[0].basis == ["projection_alignment"]
    assert set(blockers[0].entity_keys) == {
        "R2.DG_DIAMETER.DIAMETER_PROJECTION",
        "R1.C_MAIN",
        "R1.C_AMBIGUOUS",
    }
