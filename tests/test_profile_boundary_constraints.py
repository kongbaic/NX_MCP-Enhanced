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

    entity_id_by_key = {
        observed.key: captured.id
        for observed, captured in zip(observations.entities, capture.entities)
    }
    feature_id = linked.entity_to_feature[entity_id_by_key["R2.STEP_EDGE"]]
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

    assert draft["coordinate_system"]["reader_local_bounds"]["y"] == [0.0, 32]
    assert draft["coordinate_system"]["reader_to_planner_translation"]["y"] == -16.0
    relation_source = next(
        item
        for item in draft["source_ledger"]
        if item.get("id") == "R2.STEP_TO_RIGHT"
    )
    assert relation_source["semantic"] == "edge_offset"
    assert relation_source["value"] == 24.0
    assert relation_source["from"] == "max"
    assert relation_source["targets"] == [target]



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

    entity_id_by_key = {
        observed.key: captured.id
        for observed, captured in zip(observations.entities, capture.entities)
    }
    step_key = next(
        item.key
        for item in observations.entities
        if item.key.endswith("R2.structural.vertical.STEP")
    )
    feature_id = linked.entity_to_feature[entity_id_by_key[step_key]]
    target = f"feature:{feature_id}.boundary.y"
    assert resolution.values[target] == 8.0



def test_side_24_uses_profile_step_and_independent_overall_y():
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
                "bbox_px": [617, 109, 250, 561],
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
                "position_px": 620.667,
                "source_orientation": "vertical",
                "span_px": [482, 667],
                "relative_extreme_side": "min",
            },
            {
                "region_id": "R2",
                "kind": "profile_edge_candidate",
                "ref": "R2.structural.vertical.STEP",
                "position_px": 653.4,
                "source_orientation": "vertical",
                "span_px": [485, 580],
            },
            {
                "region_id": "R2",
                "kind": "profile_edge_candidate",
                "ref": "R2.structural.vertical.RIGHT",
                "position_px": 785.8,
                "source_orientation": "vertical",
                "span_px": [110, 667],
                "relative_extreme_side": "max",
            },
        ],
        "candidates": [
            {
                "candidate_id": "DG13",
                "region_id": "R2",
                "orientation": "horizontal",
                "accepted_token": "24",
                "global_assignments": [
                    {
                        "token": "24",
                        "bbox": [
                            [698.0, 565.0],
                            [744.0, 565.0],
                            [744.0, 605.0],
                            [698.0, 605.0],
                        ],
                    }
                ],
                "witness_positions_px": [653.0, 785.8],
                "witness_anchor_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 653.0,
                        "nearest_anchors": [
                            {
                                "kind": "profile_edge_candidate",
                                "ref": "R2.structural.vertical.STEP",
                                "position_px": 653.4,
                                "source_orientation": "vertical",
                            }
                        ],
                    },
                    {
                        "witness_index": 1,
                        "position_px": 785.8,
                        "nearest_anchors": [
                            {
                                "kind": "profile_edge_candidate",
                                "ref": "R2.structural.vertical.RIGHT",
                                "position_px": 785.8,
                                "source_orientation": "vertical",
                                "relative_extreme_side": "max",
                            }
                        ],
                    },
                ],
            }
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
    dimension = next(item for item in partial.dimensions if item.key == "R2.DG13")

    assert [endpoint.role for endpoint in dimension.endpoints] == [
        "profile_boundary",
        "overall_max",
    ]

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
    entity_id_by_key = {
        observed.key: captured.id
        for observed, captured in zip(observations.entities, capture.entities)
    }
    step_key = next(
        item.key
        for item in observations.entities
        if item.key.endswith("R2.structural.vertical.STEP")
    )
    feature_id = linked.entity_to_feature[entity_id_by_key[step_key]]
    assert resolution.values[f"feature:{feature_id}.boundary.y"] == 8.0
