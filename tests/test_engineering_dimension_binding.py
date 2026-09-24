from __future__ import annotations

from nx_mcp.drawing_intelligence.engineering_dimension_binding import (
    bind_callout_to_dimension_candidate,
)
from nx_mcp.drawing_intelligence import (
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
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
    termination = [
        item
        for item in partial.unresolved
        if item.kind == "termination" and item.required_for_modeling
    ]
    assert len(termination) == 1
    assert termination[0].entity_keys == [
        "R2.DG_DIAMETER.DIAMETER_PROJECTION"
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



def _integrated_circle_report() -> dict[str, object]:
    report = _two_view_report()
    report["coverage"]["conflicting_linear_observations"] = [
        {
            "candidate_id": "DG_OVERALL",
            "source_item_index": 9,
            "token": "6",
            "local_tokens": ["66"],
        }
    ]
    report["coverage"]["local_only_linear_observations"] = [
        {
            "candidate_id": "DG_OVERALL",
            "token": "66",
        }
    ]
    report["structural_profile_inventory"] = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.horizontal.TOP",
            "position_px": 100.0,
            "source_orientation": "horizontal",
            "span_px": [40, 190],
            "relative_extreme_side": "min",
            "candidate_only": True,
            "ownership_claimed": False,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.horizontal.BOTTOM",
            "position_px": 300.0,
            "source_orientation": "horizontal",
            "span_px": [40, 190],
            "relative_extreme_side": "max",
            "candidate_only": True,
            "ownership_claimed": False,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.LEFT",
            "position_px": 20.0,
            "source_orientation": "vertical",
            "span_px": [80, 300],
            "relative_extreme_side": "min",
            "candidate_only": True,
            "ownership_claimed": False,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.CENTER_AXIS",
            "position_px": 100.0,
            "source_orientation": "vertical",
            "span_px": [80, 220],
            "candidate_only": True,
            "ownership_claimed": False,
        },
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.RIGHT",
            "position_px": 180.0,
            "source_orientation": "vertical",
            "span_px": [80, 300],
            "relative_extreme_side": "max",
            "candidate_only": True,
            "ownership_claimed": False,
        },
    ]
    report["candidates"].extend(
        [
            {
                "candidate_id": "DG_WIDTH",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": "40",
                "global_proposal_token": "40",
                "decision_reason": (
                    "global_geometry_assignment_confirmed_by_local_roi"
                ),
                "wide_local_linear_tokens": ["40"],
                "global_assignments": [
                    {
                        "source_item_index": 20,
                        "text": "40",
                        "token": "40",
                        "bbox": [
                            [80.0, 260.0],
                            [120.0, 260.0],
                            [120.0, 290.0],
                            [80.0, 290.0],
                        ],
                    }
                ],
                "witness_positions_px": [20.0, 180.0],
                "witness_anchor_evidence": [],
            },
            {
                "candidate_id": "DG_OVERALL",
                "region_id": "R1",
                "orientation": "vertical",
                "accepted_token": None,
                "global_proposal_token": "6",
                "decision_reason": "global_local_token_disagreement",
                "wide_local_linear_tokens": ["66"],
                "global_assignments": [
                    {
                        "source_item_index": 9,
                        "text": "6",
                        "token": "6",
                        "bbox": [
                            [10.0, 180.0],
                            [40.0, 180.0],
                            [40.0, 220.0],
                            [10.0, 220.0],
                        ],
                    }
                ],
                "witness_positions_px": [100.0, 300.0],
                "witness_anchor_evidence": [],
            },
            {
                "candidate_id": "DG_CENTER_FROM_BOTTOM",
                "region_id": "R1",
                "orientation": "vertical",
                "accepted_token": "40±0.02",
                "global_proposal_token": "40±0.02",
                "decision_reason": (
                    "global_geometry_assignment_confirmed_by_local_roi"
                ),
                "wide_local_linear_tokens": ["40±0.02"],
                "global_assignments": [
                    {
                        "source_item_index": 10,
                        "text": "40±0.02",
                        "token": "40±0.02",
                        "bbox": [
                            [180.0, 200.0],
                            [198.0, 200.0],
                            [198.0, 240.0],
                            [180.0, 240.0],
                        ],
                    }
                ],
                "witness_positions_px": [150.0, 300.0],
                "witness_anchor_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 150.0,
                        "nearest_anchors": [
                            {
                                "kind": "circle_center_axis",
                                "ref": "R1.C_MAIN.center_y",
                                "position_px": 150.0,
                            }
                        ],
                    },
                    {
                        "witness_index": 1,
                        "position_px": 300.0,
                        "nearest_anchors": [],
                    },
                ],
            },
        ]
    )
    return report


def _integrated_context() -> HybridAdapterContext:
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
            "overall_dimension_facts": [
                {
                    "axis": "X",
                    "value": 40,
                    "evidence": ["overall:X"],
                },
                {
                    "axis": "Z",
                    "value": 66,
                    "evidence": ["overall:Z"],
                },
            ],
        }
    )


def test_integrated_circle_feature_resolves_axis_diameter_fit_and_exact_center_z():
    partial = adapt_hybrid_ocr_report(
        _integrated_circle_report(),
        _integrated_context(),
    )

    conflict_blockers = [
        item
        for item in partial.unresolved
        if item.required_for_modeling
        and item.field == "dimension_value_candidate"
    ]
    assert len(conflict_blockers) == 1
    termination_blockers = [
        item
        for item in partial.unresolved
        if item.required_for_modeling and item.kind == "termination"
    ]
    assert len(termination_blockers) == 1

    center_dimension = next(
        item
        for item in partial.dimensions
        if item.key == "R1.DG_CENTER_FROM_BOTTOM"
    )
    assert center_dimension.unresolved_reason is None
    assert len(partial.associations) == 1

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
        dimensions=[center_dimension],
        datum_alignments=partial.datum_alignments,
    )
    capture = assemble_reader_capture(observations)
    linked = link_reader_capture(capture)
    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)

    circle_entity_id = next(
        item.id
        for item in capture.entities
        if item.shape == "circle"
    )
    feature_id = linked.entity_to_feature[circle_entity_id]

    direct = {
        item.target: item.value
        for item in compiled.direct_values
    }
    assert direct[f"feature:{feature_id}.axis"] == "Y"
    assert direct[f"feature:{feature_id}.diameter"] == 20.0
    assert direct[f"feature:{feature_id}.fit"] == "H7"
    assert resolution.values[f"feature:{feature_id}.centerline.x"] == 0.0
    assert resolution.values[f"feature:{feature_id}.centerline.z"] == 40.0



def test_missing_orthographic_circle_is_feature_inventory_blocker_not_identity_record():
    partial = adapt_hybrid_ocr_report(
        _report(),
        _two_view_context(),
    )

    assert partial.associations == []
    inventory_blockers = [
        item
        for item in partial.unresolved
        if item.required_for_modeling and item.kind == "feature_inventory"
    ]
    assert len(inventory_blockers) == 1
    assert inventory_blockers[0].field == "orthographic_circular_counterpart"
    assert inventory_blockers[0].entity_keys == [
        "R2.DG_DIAMETER.DIAMETER_PROJECTION"
    ]
    termination_blockers = [
        item
        for item in partial.unresolved
        if item.required_for_modeling and item.kind == "termination"
    ]
    assert len(termination_blockers) == 1



def test_exact_dimension_carrier_beats_incidental_circle_leader_binding():
    report = _report()
    report["regions"] = [
        {
            "region_id": "R2",
            "bbox_px": [0, 0, 400, 300],
            "circle_groups": [
                {
                    "circle_group_id": "C_FALSE",
                    "center_px": [218, 150],
                    "rings": [{"radius_px": 28}],
                }
            ],
        }
    ]
    report["annotation_line_candidates"] = [
        {
            "kind": "oblique_line_candidate",
            "endpoints_px": [[230, 140], [246, 150]],
            "angle_deg": 32.0,
            "length_px": 18.9,
            "candidate_only": True,
        }
    ]

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
    partial = adapt_hybrid_ocr_report(report, context)

    ledger = next(
        item
        for item in partial.observations
        if item["kind"] == "hybrid_engineering_callout_ledger"
    )
    binding = ledger["items"][0]["binding"]
    assert binding["status"] == "dimension_backed"
    assert binding["candidate_id"] == "DG_DIAMETER"
    assert binding["text_geometry_distance_px"] == 0.0
    assert binding["competing_leader_binding"]["status"] == "bound"
    assert binding["competing_leader_binding"]["entity_key"] == "R2.C_FALSE"

    assert {
        (item.entity_key, item.field): item.value
        for item in partial.values
    } == {
        ("R2.DG_DIAMETER.DIAMETER_PROJECTION", "diameter"): 20.0,
        ("R2.DG_DIAMETER.DIAMETER_PROJECTION", "fit"): "H7",
    }
