from __future__ import annotations

from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.reader_observations import (
    ObservationDimension,
    ObservationDimensionEndpoint,
    ObservationEntity,
    ObservationView,
    ReaderObservations,
    assemble_reader_capture,
)
from nx_mcp.drawing_intelligence.draft import build_semantic_draft
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)


def test_internal_profile_boundary_resolves_from_overall_max_dimension():
    observations = ReaderObservations(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            ObservationView(
                key="R2",
                kind="side",
                evidence=["test:R2"],
            )
        ],
        entities=[
            ObservationEntity(
                key="R2.STEP_EDGE",
                view_key="R2",
                shape="profile",
                cross_view_disposition="single_view",
                evidence=["test:step-edge"],
            )
        ],
        dimensions=[
            ObservationDimension(
                key="R2.STEP_TO_RIGHT",
                value=24,
                axis="Y",
                endpoints=[
                    ObservationDimensionEndpoint(
                        role="profile_boundary",
                        entity_key="R2.STEP_EDGE",
                        basis="profile_edge",
                        evidence=["test:step-edge"],
                    ),
                    ObservationDimensionEndpoint(
                        role="overall_max",
                        evidence=["test:right-edge"],
                    ),
                ],
                evidence=["test:dimension-24"],
                required_for_modeling=True,
            )
        ],
    )

    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)
    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    profile_entity = next(
        item for item in capture.entities if item.source_key == "R2.STEP_EDGE"
    )
    feature_id = linked.entity_to_feature[profile_entity.id]
    target = f"feature:{feature_id}.boundary.y"

    assert resolution.values[target] == 8.0
    assert len(compiled.relations) == 1
    relation = compiled.relations[0]
    assert relation.kind == "edge_offset"
    assert relation.axis == "Y"
    assert relation.from_side == "max"
    assert relation.value == 24.0
    assert relation.targets == [target]

    draft = build_semantic_draft(compiled, resolution)
    feature = next(item for item in draft["features"] if item["id"] == feature_id)
    assert feature["boundary"]["y"] == -8.0

    derived = next(
        item
        for item in draft["derived_dimensions"]
        if item.get("target") == target
    )
    assert derived["reader_local_value"] == 8.0
    assert derived["value"] == -8.0



def test_adapter_turns_unique_internal_profile_edge_into_constraint_endpoint():
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [],
            "routed_elsewhere_or_unclassified_observations": [],
        },
        "regions": [
            {
                "region_id": "R2",
                "bbox_px": [0, 0, 400, 300],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "annotation_line_candidates": [],
        "structural_profile_inventory": [
            {
                "region_id": "R2",
                "kind": "profile_edge_candidate",
                "ref": "R2.structural.vertical.LEFT",
                "position_px": 50.0,
                "source_orientation": "vertical",
                "span_px": [20, 260],
                "relative_extreme_side": "min",
            },
            {
                "region_id": "R2",
                "kind": "profile_edge_candidate",
                "ref": "R2.structural.vertical.STEP",
                "position_px": 110.0,
                "source_orientation": "vertical",
                "span_px": [120, 260],
            },
            {
                "region_id": "R2",
                "kind": "profile_edge_candidate",
                "ref": "R2.structural.vertical.RIGHT",
                "position_px": 350.0,
                "source_orientation": "vertical",
                "span_px": [20, 260],
                "relative_extreme_side": "max",
            },
        ],
        "candidates": [
            {
                "candidate_id": "DG_OVERALL_Y",
                "region_id": "R2",
                "orientation": "horizontal",
                "accepted_token": "32",
                "global_assignments": [
                    {
                        "token": "32",
                        "bbox": [
                            [190.0, 270.0],
                            [210.0, 270.0],
                            [210.0, 290.0],
                            [190.0, 290.0],
                        ],
                    }
                ],
                "witness_positions_px": [50.0, 350.0],
                "witness_anchor_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 50.0,
                        "nearest_anchors": [
                            {
                                "kind": "profile_edge_candidate",
                                "ref": "R2.structural.vertical.LEFT",
                                "position_px": 50.0,
                                "source_orientation": "vertical",
                                "relative_extreme_side": "min",
                            }
                        ],
                    },
                    {
                        "witness_index": 1,
                        "position_px": 350.0,
                        "nearest_anchors": [
                            {
                                "kind": "profile_edge_candidate",
                                "ref": "R2.structural.vertical.RIGHT",
                                "position_px": 350.0,
                                "source_orientation": "vertical",
                                "relative_extreme_side": "max",
                            }
                        ],
                    },
                ],
            },
            {
                "candidate_id": "DG_STEP_TO_RIGHT",
                "region_id": "R2",
                "orientation": "horizontal",
                "accepted_token": "24",
                "global_assignments": [
                    {
                        "token": "24",
                        "bbox": [
                            [220.0, 230.0],
                            [240.0, 230.0],
                            [240.0, 250.0],
                            [220.0, 250.0],
                        ],
                    }
                ],
                "witness_positions_px": [110.0, 350.0],
                "witness_anchor_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 110.0,
                        "nearest_anchors": [
                            {
                                "kind": "profile_edge_candidate",
                                "ref": "R2.structural.vertical.STEP",
                                "position_px": 110.0,
                                "source_orientation": "vertical",
                            }
                        ],
                    },
                    {
                        "witness_index": 1,
                        "position_px": 350.0,
                        "nearest_anchors": [
                            {
                                "kind": "profile_edge_candidate",
                                "ref": "R2.structural.vertical.RIGHT",
                                "position_px": 350.0,
                                "source_orientation": "vertical",
                                "relative_extreme_side": "max",
                            }
                        ],
                    },
                ],
            },
        ],
    }
    context = HybridAdapterContext.model_validate(
        {
            "schema": "hybrid-adapter-context-v1",
            "region_views": [
                {
                    "region_id": "R2",
                    "view_kind": "side",
                    "evidence": ["test:R2"],
                }
            ],
            "overall_dimension_facts": [
                {
                    "axis": "Y",
                    "value": 32,
                    "evidence": ["test:overall-y"],
                }
            ],
        }
    )

    partial = adapt_hybrid_ocr_report(report, context)
    dimension = next(
        item for item in partial.dimensions if item.key == "R2.DG_STEP_TO_RIGHT"
    )

    assert dimension.unresolved_reason is None
    assert [endpoint.role for endpoint in dimension.endpoints] == [
        "profile_boundary",
        "overall_max",
    ]
    assert dimension.endpoints[0].basis == "profile_edge"

    observations = ReaderObservations(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=partial.views,
        entities=partial.entities,
        dimensions=[dimension],
    )
    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)
    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    profile_entity = next(
        item
        for item in capture.entities
        if item.source_key.endswith("R2.structural.vertical.STEP")
    )
    feature_id = linked.entity_to_feature[profile_entity.id]
    target = f"feature:{feature_id}.boundary.y"
    assert resolution.values[target] == 8.0
