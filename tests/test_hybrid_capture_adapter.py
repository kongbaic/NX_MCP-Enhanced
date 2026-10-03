from __future__ import annotations

import pytest

import nx_mcp.drawing_intelligence.compiler as compiler_module
import nx_mcp.drawing_intelligence.hybrid_capture_adapter as hybrid_adapter

from nx_mcp.drawing_intelligence.compiler import compile_evidence_graph
from nx_mcp.drawing_intelligence.draft import build_semantic_draft
from nx_mcp.drawing_intelligence.evidence import (
    CoordinateFact,
    DimensionEndpoint,
    DimensionObservation,
    EvidenceGraph,
    OverallDimensions,
    RelationEvidence,
)
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    HybridCaptureAdapterError,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.resolver import resolve_evidence_graph


def test_coordinate_distance_compiler_rejects_non_coordinate_endpoint_sets():
    relations = []
    mixed_with_overall = DimensionObservation(
        id="D_OVERALL_EDGE",
        value=20,
        axis="X",
        endpoints=[
            DimensionEndpoint(role="overall_min"),
            DimensionEndpoint(role="profile_boundary", target="feature:F1.boundary.x"),
        ],
    )
    centers_only = DimensionObservation(
        id="D_CENTERS",
        value=20,
        axis="X",
        endpoints=[
            DimensionEndpoint(role="feature_center", target="feature:F1.centerline.x"),
            DimensionEndpoint(role="feature_center", target="feature:F2.centerline.x"),
        ],
    )

    assert not compiler_module._compile_coordinate_distance(
        mixed_with_overall,
        relations,
    )
    assert not compiler_module._compile_coordinate_distance(
        centers_only,
        relations,
    )
    assert relations == []


def test_coordinate_distance_relation_requires_two_targets():
    with pytest.raises(ValueError, match="requires value and exactly two targets"):
        RelationEvidence(
            id="R_COORD",
            kind="coordinate_distance",
            axis="X",
            value=26,
            targets=["feature:F1.boundary.x"],
        )


def test_profile_boundary_span_compiles_to_resolvable_coordinate_distance():
    left = "feature:F_LEFT.boundary.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=300,
            width_y=300,
            height_z=75,
        ),
        direct_facts=[
            CoordinateFact(
                target=left,
                axis="X",
                value=25,
                source_ids=["test:left"],
            )
        ],
        dimensions=[
            DimensionObservation(
                id="D_PROFILE",
                value=26,
                axis="X",
                direction=1,
                endpoints=[
                    DimensionEndpoint(role="profile_boundary", target=left),
                    DimensionEndpoint(role="profile_boundary", target=right),
                ],
                source_ids=["test:dimension"],
            )
        ],
        required_targets=[left, right],
    )

    compiled = compile_evidence_graph(graph)

    assert [item.kind for item in compiled.relations] == ["coordinate_distance"]
    assert not any(
        item.get("id") == "U_D_PROFILE"
        for item in compiled.unresolved_evidence
    )

    resolved = resolve_evidence_graph(compiled)

    assert resolved.values[left] == 25
    assert resolved.values[right] == 51
    assert resolved.unresolved == []
    assert resolved.conflicts == []

    draft = build_semantic_draft(compiled, resolved)
    relation_sources = [
        item
        for item in draft["source_ledger"]
        if item.get("semantic") == "coordinate_distance"
    ]
    assert len(relation_sources) == 1
    assert relation_sources[0]["value"] == 26
    assert relation_sources[0]["axis"] == "X"
    assert relation_sources[0]["between"] == [left, right]


def _report() -> dict:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [
                {
                    "candidate_id": "DG17",
                    "source_item_index": 9,
                    "token": "6",
                    "local_tokens": ["66"],
                }
            ],
            "secondary_assignment_observations": [
                {
                    "candidate_id": "DG13",
                    "source_item_index": 21,
                    "token": "32",
                    "selected_proposal_token": "24",
                }
            ],
            "unassigned_linear_observations": [
                {
                    "source_item_index": 0,
                    "token": "16",
                }
            ],
            "local_only_linear_observations": [
                {
                    "candidate_id": "DG17",
                    "token": "66",
                }
            ],
        },
        "candidates": [
            {
                "candidate_id": "DG12",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": "24",
                "global_assignments": [
                    {
                        "token": "24",
                        "bbox": [
                            [140.0, 80.0],
                            [160.0, 80.0],
                            [160.0, 100.0],
                            [140.0, 100.0],
                        ],
                    }
                ],
                "witness_positions_px": [100.0, 200.0],
                "witness_anchor_evidence": [
                    {
                        "witness_index": 0,
                        "axis": "x",
                        "nearest_anchors": [
                            {
                                "kind": "circle_center_axis",
                                "ref": "R1.CG001.center_x",
                                "distance_px": 0.0,
                                "distance_local_norm": 0.0,
                            }
                        ],
                    },
                    {
                        "witness_index": 1,
                        "axis": "x",
                        "nearest_anchors": [
                            {
                                "kind": "profile_edge_candidate",
                                "ref": "R1.structural.vertical.001",
                                "position_px": 200.0,
                                "candidate_only": True,
                                "ownership_claimed": False,
                                "distance_px": 0.0,
                                "distance_local_norm": 0.0,
                            }
                        ],
                    },
                ],
                "witness_line_evidence": [
                    {
                        "witness_index": 0,
                        "position_px": 100.0,
                        "source_lines": [
                            {
                                "orientation": "vertical",
                                "axis_px": 100.0,
                                "span_px": [20, 180],
                                "span_length_px": 160,
                                "crosses_dimension_axis": True,
                            }
                        ],
                    },
                    {
                        "witness_index": 1,
                        "position_px": 200.0,
                        "source_lines": [
                            {
                                "orientation": "vertical",
                                "axis_px": 200.0,
                                "span_px": [20, 180],
                                "span_length_px": 160,
                                "crosses_dimension_axis": True,
                            }
                        ],
                    },
                ],
            },
            {
                "candidate_id": "DG17",
                "region_id": "R1",
                "orientation": "vertical",
                "accepted_token": None,
            },
            {
                "candidate_id": "DG25",
                "region_id": "R1",
                "orientation": "vertical",
                "accepted_token": "40±0.02",
            },
            {
                "candidate_id": "DG13",
                "region_id": "R2",
                "orientation": "horizontal",
                "accepted_token": "24",
            },
        ],
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
                },
                {
                    "region_id": "R2",
                    "view_kind": "side",
                    "evidence": ["structural:R2"],
                },
            ],
        }
    )


def test_hybrid_context_rejects_legacy_confirmed_start_side_injection():
    with pytest.raises(
        ValueError,
        match="confirmed_start_sides is legacy-only",
    ):
        HybridAdapterContext.model_validate(
            {
                "schema": "hybrid-adapter-context-v1",
                "region_views": [
                    {
                        "region_id": "R1",
                        "view_kind": "front",
                        "evidence": ["structural:R1"],
                    }
                ],
                "confirmed_start_sides": [
                    {
                        "entity_key": "R1.HIDDEN_PAIR.horizontal.004.005",
                        "start_side": "min",
                        "evidence": ["human-confirmation:test:min"],
                    }
                ],
            }
        )


def test_missing_transverse_thread_start_side_is_blocking_unresolved():
    unresolved = hybrid_adapter._missing_transverse_thread_start_side_unresolved(
        values=[
            hybrid_adapter.ObservationValue(
                entity_key="R1.THREAD",
                field="axis",
                value="X",
                semantic="axis",
                evidence=["axis"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key="R1.THREAD",
                field="thread_spec",
                value="M6",
                evidence=["thread"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key="R1.THREAD",
                field="thread_depth",
                value=12.0,
                evidence=["depth"],
            ),
        ]
    )

    assert len(unresolved) == 1
    assert unresolved[0].kind == "start_side"
    assert unresolved[0].entity_keys == ["R1.THREAD"]
    assert unresolved[0].field == "start_side"
    assert unresolved[0].axis == "X"
    assert unresolved[0].required_for_modeling is True


def test_confirmed_transverse_thread_start_side_suppresses_unresolved():
    unresolved = hybrid_adapter._missing_transverse_thread_start_side_unresolved(
        values=[
            hybrid_adapter.ObservationValue(
                entity_key="R1.THREAD",
                field="axis",
                value="X",
                semantic="axis",
                evidence=["axis"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key="R1.THREAD",
                field="thread_spec",
                value="M6",
                evidence=["thread"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key="R1.THREAD",
                field="thread_depth",
                value=12.0,
                evidence=["depth"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key="R1.THREAD",
                field="start_side",
                value="min",
                semantic="start_side",
                evidence=["human-confirmation"],
            ),
        ]
    )

    assert unresolved == []


def test_adapter_emits_accepted_dimensions_with_unresolved_endpoints():
    partial = adapt_hybrid_ocr_report(_report(), _context())

    by_key = {item.key: item for item in partial.dimensions}
    assert by_key["R1.DG12"].value == 24
    assert by_key["R1.DG12"].axis == "X"
    assert "R1.DG17" not in by_key
    assert all(endpoint.role == "unresolved" for endpoint in by_key["R1.DG12"].endpoints)
    assert by_key["R2.DG13"].axis == "Y"

    anchor_ledger = next(
        item for item in partial.observations if item["kind"] == "hybrid_dimension_anchor_ledger"
    )
    dg12 = next(item for item in anchor_ledger["items"] if item["candidate_id"] == "DG12")
    assert dg12["witness_anchor_evidence"][0]["nearest_anchors"][0]["kind"] == "circle_center_axis"
    assert dg12["witness_line_evidence"][0]["source_lines"][0]["span_length_px"] == 160
    assert anchor_ledger["schema"] == "1.1"
    endpoint_candidates = dg12["endpoint_candidate_evidence"]
    assert endpoint_candidates["status"] == "bracketed"
    assert endpoint_candidates["selected_witness_indices"] == [0, 1]
    assert endpoint_candidates["all_endpoint_candidates_unique"] is True
    assert all(endpoint.role == "unresolved" for endpoint in by_key["R1.DG12"].endpoints)



def test_unresolved_dimension_matching_independent_same_region_overall_is_advisory():
    context = HybridAdapterContext.model_validate(
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
                    "value": 24,
                    "evidence": ["structural:R1"],
                }
            ],
        }
    )

    partial = adapt_hybrid_ocr_report(_report(), context)
    by_key = {item.key: item for item in partial.dimensions}

    assert by_key["R1.DG12"].unresolved_reason is not None
    assert by_key["R1.DG12"].required_for_modeling is False
    assert by_key["R2.DG13"].required_for_modeling is True

def test_adapter_preserves_labeled_dimension_facts_as_provenance_only():
    context_payload = _context().model_dump(mode="json", by_alias=True)
    context_payload["labeled_dimension_facts"] = [
        {
            "target_id": "LD_0004",
            "source_item_index": 4,
            "source_text": "S- 4.5 mm",
            "region_id": "R1",
            "value": 4.5,
            "axis": "X",
            "relation": "between_profile_boundaries",
            "profile_transition_geometry": "orthogonal",
            "symmetry_scope": "single",
            "evidence": ["hybrid:whole:4", "structural:R1"],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    ]
    context = HybridAdapterContext.model_validate(context_payload)

    baseline = adapt_hybrid_ocr_report(_report(), _context())
    partial = adapt_hybrid_ocr_report(_report(), context)

    ledger = next(
        item
        for item in partial.observations
        if item["kind"] == "hybrid_labeled_dimension_relation_ledger"
    )
    assert ledger["schema"] == "1.0"
    assert ledger["engineering_value_source"] == "hybrid_ocr"
    assert ledger["relation_source"] == "bounded_structural_context"
    assert ledger["engineering_coordinate_inferred_from_pixels"] is False
    assert ledger["pixel_geometry_used_for_topology_only"] is True
    assert ledger["items"] == [
        {
            "target_id": "LD_0004",
            "source_item_index": 4,
            "source_text": "S- 4.5 mm",
            "region_id": "R1",
            "value": 4.5,
            "axis": "X",
            "relation": "between_profile_boundaries",
            "profile_transition_geometry": "orthogonal",
            "symmetry_scope": "single",
            "evidence": ["hybrid:whole:4", "structural:R1"],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    ]

    assert partial.dimensions == baseline.dimensions
    assert partial.values == baseline.values
    assert partial.datum_alignments == baseline.datum_alignments
    assert partial.unresolved == baseline.unresolved


def test_labeled_dimension_relation_reconciles_unique_overall_boundary_contact(
    monkeypatch,
):
    fact = hybrid_adapter.HybridLabeledDimensionFact(
        target_id="LD_0005",
        source_item_index=5,
        source_text="H3 - 12 mm",
        region_id="R1",
        value=12,
        axis="Z",
        relation="between_profile_boundaries",
        profile_transition_geometry="orthogonal",
        symmetry_scope="single",
        evidence=["hybrid:whole:5", "structural:R1"],
    )
    report = {
        "source_raster": "drawing.png",
        "regions": [{"region_id": "R1", "bbox_px": [0, 0, 1000, 400]}],
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 5,
                    "bbox": [[80, 100], [220, 100], [220, 130], [80, 130]],
                }
            ]
        },
    }
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R1",
            "axis": "Z",
            "anchors": [
                {"role": "overall_max", "position_px": 100.0},
                {"role": "overall_min", "position_px": 300.0},
            ],
        }
    ]
    monkeypatch.setattr(
        hybrid_adapter,
        "infer_short_dimension_visual_topology",
        lambda *_args: ("vertical", [(100.5, 145.0)]),
    )

    reconciled = hybrid_adapter._reconcile_labeled_dimension_relations(
        report=report,
        facts=[fact],
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1"],
            )
        },
        boundaries=boundaries,
    )

    assert reconciled[0].relation == "overall_max_to_profile_transition"
    assert (
        "hybrid:labeled-overall-boundary-contact:R1:Z:overall_max"
        in reconciled[0].evidence
    )
    assert reconciled[0].engineering_coordinate_inferred_from_pixels is False
    assert reconciled[0].pixel_geometry_used_for_topology_only is True


def test_conflicting_agent_overall_side_is_canonicalized_by_unique_topology(
    monkeypatch,
):
    fact = hybrid_adapter.HybridLabeledDimensionFact(
        target_id="LD_0005",
        source_item_index=5,
        source_text="H3 - 12 mm",
        region_id="R1",
        value=12,
        axis="Z",
        relation="overall_min_to_profile_transition",
        profile_transition_geometry="orthogonal",
        symmetry_scope="single",
        evidence=["hybrid:whole:5", "structural:R1:context"],
    )
    report = {
        "source_raster": "drawing.png",
        "regions": [{"region_id": "R1", "bbox_px": [0, 0, 1000, 400]}],
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 5,
                    "bbox": [[80, 100], [220, 100], [220, 130], [80, 130]],
                }
            ]
        },
    }
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R1",
            "axis": "Z",
            "anchors": [
                {"role": "overall_max", "position_px": 100.0},
                {"role": "overall_min", "position_px": 300.0},
            ],
        }
    ]
    monkeypatch.setattr(
        hybrid_adapter,
        "infer_short_dimension_visual_topology",
        lambda *_args: ("vertical", [(100.5, 145.0)]),
    )

    reconciled = hybrid_adapter._reconcile_labeled_dimension_relations(
        report=report,
        facts=[fact],
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1"],
            )
        },
        boundaries=boundaries,
    )

    assert reconciled[0].relation == "overall_max_to_profile_transition"
    assert (
        "hybrid:labeled-overall-boundary-contact:R1:Z:overall_max"
        in reconciled[0].evidence
    )
    assert (
        "hybrid:labeled-overall-relation-canonicalized:"
        "LD_0005:overall_min_to_profile_transition:"
        "overall_max_to_profile_transition"
        in reconciled[0].evidence
    )
    assert reconciled[0].engineering_coordinate_inferred_from_pixels is False
    assert reconciled[0].pixel_geometry_used_for_topology_only is True


def test_verified_existing_overall_relation_records_contact_marker(
    monkeypatch,
):
    fact = hybrid_adapter.HybridLabeledDimensionFact(
        target_id="LD_0005",
        source_item_index=5,
        source_text="H3 - 12 mm",
        region_id="R1",
        value=12,
        axis="Z",
        relation="overall_max_to_profile_transition",
        profile_transition_geometry="orthogonal",
        symmetry_scope="single",
        evidence=["hybrid:whole:5", "structural:R1:context"],
    )
    report = {
        "source_raster": "drawing.png",
        "regions": [{"region_id": "R1", "bbox_px": [0, 0, 1000, 400]}],
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 5,
                    "bbox": [[80, 100], [220, 100], [220, 130], [80, 130]],
                }
            ]
        },
    }
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R1",
            "axis": "Z",
            "anchors": [
                {"role": "overall_max", "position_px": 100.0},
                {"role": "overall_min", "position_px": 300.0},
            ],
        }
    ]
    monkeypatch.setattr(
        hybrid_adapter,
        "infer_short_dimension_visual_topology",
        lambda *_args: ("vertical", [(100.5, 145.0)]),
    )

    reconciled = hybrid_adapter._reconcile_labeled_dimension_relations(
        report=report,
        facts=[fact],
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1"],
            )
        },
        boundaries=boundaries,
    )

    assert reconciled[0].relation == "overall_max_to_profile_transition"
    assert (
        "hybrid:labeled-overall-boundary-contact:R1:Z:overall_max"
        in reconciled[0].evidence
    )


def test_labeled_dimension_relation_keeps_ambiguous_witness_topology_fail_closed(
    monkeypatch,
):
    fact = hybrid_adapter.HybridLabeledDimensionFact(
        target_id="LD_0004",
        source_item_index=4,
        source_text="S - 4.5 mm",
        region_id="R1",
        value=4.5,
        axis="X",
        relation="between_profile_boundaries",
        profile_transition_geometry="orthogonal",
        symmetry_scope="single",
        evidence=["hybrid:whole:4", "structural:R1"],
    )
    report = {
        "source_raster": "drawing.png",
        "regions": [{"region_id": "R1", "bbox_px": [0, 0, 1000, 400]}],
        "coverage": {
            "unconfirmed_proposal_observations": [
                {
                    "source_item_index": 4,
                    "bbox": [[400, 150], [530, 150], [530, 190], [400, 190]],
                }
            ]
        },
    }
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R1",
            "axis": "X",
            "anchors": [
                {"role": "overall_min", "position_px": 100.0},
                {"role": "overall_max", "position_px": 900.0},
            ],
        }
    ]
    monkeypatch.setattr(
        hybrid_adapter,
        "infer_short_dimension_visual_topology",
        lambda *_args: ("horizontal", [(100.5, 150.0), (120.0, 150.0)]),
    )

    reconciled = hybrid_adapter._reconcile_labeled_dimension_relations(
        report=report,
        facts=[fact],
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1"],
            )
        },
        boundaries=boundaries,
    )

    assert reconciled == [fact]


def test_labeled_profile_span_recovers_unique_two_boundary_identity(
    monkeypatch,
):
    fact = hybrid_adapter.HybridLabeledDimensionFact(
        target_id="LD_0004",
        source_item_index=4,
        source_text="S - 4.5 mm",
        region_id="R3",
        value=4.5,
        axis="X",
        relation="between_profile_boundaries",
        profile_transition_geometry="orthogonal",
        symmetry_scope="single",
        evidence=["hybrid:whole:4", "structural:R3:context"],
    )
    report = {
        "source_raster": "drawing.png",
        "regions": [
            {"region_id": "R3", "bbox_px": [432, 88, 592, 211]},
            {"region_id": "R2", "bbox_px": [337, 138, 793, 496]},
            {"region_id": "R1", "bbox_px": [268, 294, 1025, 390]},
        ],
        "coverage": {
            "unconfirmed_proposal_observations": [
                {
                    "source_item_index": 4,
                    "bbox": [
                        [416.0, 162.0],
                        [538.0, 162.0],
                        [538.0, 192.0],
                        [416.0, 192.0],
                    ],
                }
            ]
        },
    }
    profile_inventory = [
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "R2.LEFT",
            "source_orientation": "vertical",
            "position_px": 472.2,
            "span_px": [140.0, 454.0],
            "axis_tolerance_px": 4.0,
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "R2.RIGHT",
            "source_orientation": "vertical",
            "position_px": 484.6,
            "span_px": [183.0, 523.0],
            "axis_tolerance_px": 4.0,
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R3",
            "ref": "R3.LEFT",
            "source_orientation": "vertical",
            "position_px": 472.1,
            "span_px": [140.0, 454.0],
            "axis_tolerance_px": 4.0,
        },
    ]
    entity_by_ref = {
        "R2.LEFT": "R2.PROFILE.LEFT",
        "R2.RIGHT": "R2.PROFILE.RIGHT",
        "R3.LEFT": "R3.PROFILE.LEFT",
    }
    monkeypatch.setattr(
        hybrid_adapter,
        "infer_short_dimension_visual_topology",
        lambda *_args: ("horizontal", [(472.0, 484.8)]),
    )

    dimensions, ledger = (
        hybrid_adapter._recover_labeled_profile_span_dimensions(
            report=report,
            facts=[fact],
            view_lookup={
                "R1": hybrid_adapter.HybridRegionView(
                    region_id="R1",
                    view_kind="front",
                    evidence=["structural:R1:context"],
                ),
                "R2": hybrid_adapter.HybridRegionView(
                    region_id="R2",
                    view_kind="front",
                    evidence=["structural:R2:context"],
                ),
                "R3": hybrid_adapter.HybridRegionView(
                    region_id="R3",
                    view_kind="front",
                    evidence=["structural:R3:context"],
                ),
            },
            profile_inventory=profile_inventory,
            profile_entity_by_ref=entity_by_ref,
        )
    )

    assert len(dimensions) == 1
    dimension = dimensions[0]
    assert dimension.key == "R3.LABELED_PROFILE_SPAN_LD_0004"
    assert dimension.value == 4.5
    assert dimension.axis == "X"
    assert dimension.direction == 1
    assert [
        endpoint.entity_key
        for endpoint in dimension.endpoints
    ] == ["R2.PROFILE.LEFT", "R2.PROFILE.RIGHT"]
    assert all(
        endpoint.role == "profile_boundary"
        for endpoint in dimension.endpoints
    )
    assert ledger == [
        {
            "dimension_key": "R3.LABELED_PROFILE_SPAN_LD_0004",
            "target_id": "LD_0004",
            "source_item_index": 4,
            "source_text": "S - 4.5 mm",
            "region_id": "R3",
            "selected_region_id": "R2",
            "axis": "X",
            "value": 4.5,
            "source_relation": "between_profile_boundaries",
            "profile_refs": ["R2.LEFT", "R2.RIGHT"],
            "profile_entity_keys": [
                "R2.PROFILE.LEFT",
                "R2.PROFILE.RIGHT",
            ],
            "selected_witness_positions_px": [472.0, 484.8],
            "basis": (
                "unique_short_dimension_witness_pair_to_two_"
                "structural_profile_boundaries"
            ),
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        }
    ]


def test_unique_profile_span_identity_overrides_unverified_overall_relation():
    fact = hybrid_adapter.HybridLabeledDimensionFact(
        target_id="LD_0004",
        source_item_index=4,
        source_text="S - 4.5 mm",
        region_id="R3",
        value=4.5,
        axis="X",
        relation="overall_min_to_profile_transition",
        profile_transition_geometry="orthogonal",
        symmetry_scope="single",
        evidence=["hybrid:whole:4", "structural:R3:context"],
    )

    reconciled = hybrid_adapter._reconcile_labeled_profile_span_relations(
        facts=[fact],
        identity_ledger=[
            {
                "target_id": "LD_0004",
                "basis": (
                    "unique_short_dimension_witness_pair_to_two_"
                    "structural_profile_boundaries"
                ),
            }
        ],
    )

    assert reconciled[0].relation == "between_profile_boundaries"
    assert (
        "hybrid:labeled-profile-span-relation:LD_0004"
        in reconciled[0].evidence
    )
    assert reconciled[0].engineering_coordinate_inferred_from_pixels is False
    assert reconciled[0].pixel_geometry_used_for_topology_only is True


def test_verified_overall_relation_is_not_overridden_by_profile_span_identity():
    fact = hybrid_adapter.HybridLabeledDimensionFact(
        target_id="LD_0005",
        source_item_index=5,
        source_text="H3 - 12 mm",
        region_id="R1",
        value=12,
        axis="Z",
        relation="overall_max_to_profile_transition",
        profile_transition_geometry="orthogonal",
        symmetry_scope="bilateral",
        evidence=[
            "hybrid:whole:5",
            "structural:R1:context",
            "hybrid:labeled-overall-boundary-contact:R1:Z:overall_max",
        ],
    )

    reconciled = hybrid_adapter._reconcile_labeled_profile_span_relations(
        facts=[fact],
        identity_ledger=[
            {
                "target_id": "LD_0005",
                "basis": (
                    "unique_short_dimension_witness_pair_to_two_"
                    "structural_profile_boundaries"
                ),
            }
        ],
    )

    assert reconciled == [fact]


def test_labeled_profile_span_fails_closed_when_two_regions_supply_full_pairs(
    monkeypatch,
):
    fact = hybrid_adapter.HybridLabeledDimensionFact(
        target_id="LD_0004",
        source_item_index=4,
        source_text="S - 4.5 mm",
        region_id="R3",
        value=4.5,
        axis="X",
        relation="between_profile_boundaries",
        profile_transition_geometry="orthogonal",
        symmetry_scope="single",
        evidence=["hybrid:whole:4", "structural:R3:context"],
    )
    report = {
        "source_raster": "drawing.png",
        "regions": [
            {"region_id": "R3", "bbox_px": [432, 88, 592, 211]},
            {"region_id": "R2", "bbox_px": [337, 138, 793, 496]},
        ],
        "coverage": {
            "unconfirmed_proposal_observations": [
                {
                    "source_item_index": 4,
                    "bbox": [
                        [416.0, 162.0],
                        [538.0, 162.0],
                        [538.0, 192.0],
                        [416.0, 192.0],
                    ],
                }
            ]
        },
    }
    profile_inventory = [
        {
            "kind": "profile_edge_candidate",
            "region_id": region_id,
            "ref": f"{region_id}.LEFT",
            "source_orientation": "vertical",
            "position_px": 472.2,
            "span_px": [140.0, 454.0],
            "axis_tolerance_px": 4.0,
        }
        for region_id in ("R2", "R3")
    ] + [
        {
            "kind": "profile_edge_candidate",
            "region_id": region_id,
            "ref": f"{region_id}.RIGHT",
            "source_orientation": "vertical",
            "position_px": 484.6,
            "span_px": [183.0, 523.0],
            "axis_tolerance_px": 4.0,
        }
        for region_id in ("R2", "R3")
    ]
    entity_by_ref = {
        item["ref"]: f"ENTITY.{item['ref']}"
        for item in profile_inventory
    }
    monkeypatch.setattr(
        hybrid_adapter,
        "infer_short_dimension_visual_topology",
        lambda *_args: ("horizontal", [(472.0, 484.8)]),
    )

    dimensions, ledger = (
        hybrid_adapter._recover_labeled_profile_span_dimensions(
            report=report,
            facts=[fact],
            view_lookup={
                "R2": hybrid_adapter.HybridRegionView(
                    region_id="R2",
                    view_kind="front",
                    evidence=["structural:R2:context"],
                ),
                "R3": hybrid_adapter.HybridRegionView(
                    region_id="R3",
                    view_kind="front",
                    evidence=["structural:R3:context"],
                ),
            },
            profile_inventory=profile_inventory,
            profile_entity_by_ref=entity_by_ref,
        )
    )

    assert dimensions == []
    assert ledger == []


def test_adapter_preserves_tolerance_without_claiming_endpoint_ownership():
    partial = adapt_hybrid_ocr_report(_report(), _context())

    tolerance = [item for item in partial.unresolved if item.field == "dimension_tolerance"]
    assert len(tolerance) == 1
    assert tolerance[0].dimension_key == "R1.DG25"
    assert tolerance[0].required_for_modeling is False


def test_adapter_preserves_coverage_evidence_and_blocks_unconsumed_linear_tokens():
    partial = adapt_hybrid_ocr_report(_report(), _context())

    fields = [item.field for item in partial.unresolved]
    assert "dimension_value_candidate" in fields
    assert "secondary_linear_assignment" in fields
    assert "unassigned_linear_text" in fields
    assert "local_only_linear_text" in fields

    blocking = [item for item in partial.unresolved if item.required_for_modeling]
    assert [(item.kind, item.field) for item in blocking] == [
        ("unsupported_representation", "dimension_value_candidate"),
        ("unsupported_representation", "unassigned_linear_text"),
    ]

    advisory_fields = {item.field for item in partial.unresolved if not item.required_for_modeling}
    assert {
        "secondary_linear_assignment",
        "local_only_linear_text",
    } <= advisory_fields
    assert "unassigned_linear_text" not in advisory_fields
    assert partial.observations[0]["kind"] == "hybrid_ocr_coverage_ledger"


def test_adapter_does_not_double_block_unassigned_source_claimed_by_labeled_fact():
    context_payload = _context().model_dump(mode="json", by_alias=True)
    context_payload["labeled_dimension_facts"] = [
        {
            "target_id": "LD_0000",
            "source_item_index": 0,
            "source_text": "16",
            "region_id": "R1",
            "value": 16,
            "axis": "X",
            "relation": "between_profile_boundaries",
            "profile_transition_geometry": "orthogonal",
            "symmetry_scope": "single",
            "evidence": ["hybrid:whole:0", "structural:R1"],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    ]
    partial = adapt_hybrid_ocr_report(
        _report(),
        HybridAdapterContext.model_validate(context_payload),
    )

    assert not [
        item
        for item in partial.unresolved
        if (
            item.field == "unassigned_linear_text"
            and "hybrid:whole:0" in item.evidence
        )
    ]
    ledger = next(
        item
        for item in partial.observations
        if item["kind"] == "hybrid_labeled_dimension_relation_ledger"
    )
    assert ledger["items"][0]["source_item_index"] == 0


def test_adapter_rejects_silent_drop_report():
    report = _report()
    report["coverage"]["observed_silent_drop_count"] = 1

    with pytest.raises(HybridCaptureAdapterError, match="silent evidence drops"):
        adapt_hybrid_ocr_report(report, _context())


def test_adapter_rejects_missing_region_view_context():
    context = HybridAdapterContext.model_validate(
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

    with pytest.raises(HybridCaptureAdapterError, match="missing view context"):
        adapt_hybrid_ocr_report(_report(), context)


def test_adapter_rejects_old_hybrid_report_schema():
    report = _report()
    report["schema"] = "dg-hybrid-ocr-bakeoff-v1"

    with pytest.raises(HybridCaptureAdapterError, match="requires"):
        adapt_hybrid_ocr_report(report, _context())


def test_adapter_materializes_circle_geometry_and_parsed_callouts_without_guessing_owner():
    report = _report()
    report["regions"] = [
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
        },
        {
            "region_id": "R2",
            "bbox_px": [500, 0, 300, 400],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [650, 200],
                    "rings": [{"radius_px": 20}, {"radius_px": 35}],
                }
            ],
        },
    ]
    report["coverage"]["routed_elsewhere_or_unclassified_observations"] = [
        {
            "source_item_index": 1,
            "text": "M6深12",
            "bbox": [[100, 100], [180, 100], [180, 130], [100, 130]],
            "confidence": 0.99,
        },
        {
            "source_item_index": 7,
            "text": "∅20 H7",
            "bbox": [[650, 250], [720, 250], [720, 290], [650, 290]],
            "confidence": 0.99,
        },
    ]

    partial = adapt_hybrid_ocr_report(report, _context())

    assert [(item.key, item.shape) for item in partial.entities] == [
        ("R1.C1", "circle"),
        ("R2.C1", "concentric_circles"),
        ("R1.CALLOUT.1", "other"),
        ("R2.CALLOUT.7", "other"),
    ]
    assert partial.entities[0].required_for_modeling is False
    assert partial.entities[1].required_for_modeling is False
    assert partial.entities[2].required_for_modeling is False
    assert partial.entities[3].required_for_modeling is False

    ledger = next(
        item for item in partial.observations if item["kind"] == "hybrid_engineering_callout_ledger"
    )
    assert ledger["items"][0]["facts"] == {
        "thread_spec": "M6",
        "thread_depth": 12.0,
    }
    assert ledger["items"][0]["region_candidates"] == ["R1"]
    assert ledger["items"][1]["facts"] == {
        "diameter": 20.0,
        "fit": "H7",
    }
    assert ledger["items"][1]["region_candidates"] == ["R2"]

    assert [(item.entity_key, item.field, item.value) for item in partial.values] == [
        ("R1.CALLOUT.1", "thread_depth", 12.0),
        ("R1.CALLOUT.1", "thread_spec", "M6"),
        ("R2.CALLOUT.7", "diameter", 20.0),
        ("R2.CALLOUT.7", "fit", "H7"),
    ]
    callout_unresolved = [
        item
        for item in partial.unresolved
        if item.kind == "feature_inventory"
        and item.field == "engineering_callout_geometry_binding"
        and item.entity_keys
    ]
    assert len(callout_unresolved) == 2
    assert all(item.required_for_modeling for item in callout_unresolved)


def test_adapter_writes_values_only_with_explicit_callout_geometry_binding():
    report = _report()
    report["regions"] = [
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
    report["annotation_line_candidates"] = [
        {
            "kind": "oblique_line_candidate",
            "endpoints_px": [[95, 45], [228, 228]],
            "candidate_only": True,
        }
    ]
    report["coverage"]["routed_elsewhere_or_unclassified_observations"] = [
        {
            "source_item_index": 7,
            "text": "∅20 H7",
            "bbox": [[20, 20], [100, 20], [100, 50], [20, 50]],
            "confidence": 0.99,
        }
    ]

    partial = adapt_hybrid_ocr_report(report, _context())

    assert [(item.entity_key, item.field, item.value) for item in partial.values] == [
        ("R1.C1", "diameter", 20.0),
        ("R1.C1", "fit", "H7"),
    ]
    assert not [
        item for item in partial.unresolved if item.field == "engineering_callout_geometry_binding"
    ]

    ledger = next(
        item for item in partial.observations if item["kind"] == "hybrid_engineering_callout_ledger"
    )
    assert ledger["items"][0]["binding"]["status"] == "bound"
    assert ledger["items"][0]["binding"]["entity_key"] == "R1.C1"


def test_adapter_transports_nearby_callout_without_claiming_geometry_binding():
    report = _report()
    report["regions"] = [
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
    report["coverage"]["routed_elsewhere_or_unclassified_observations"] = [
        {
            "source_item_index": 7,
            "text": "∅20 H7",
            "bbox": [[140, 120], [220, 120], [220, 150], [140, 150]],
            "confidence": 0.99,
        }
    ]

    partial = adapt_hybrid_ocr_report(report, _context())

    assert [(item.entity_key, item.field, item.value) for item in partial.values] == [
        ("R1.CALLOUT.7", "diameter", 20.0),
        ("R1.CALLOUT.7", "fit", "H7"),
    ]
    unresolved = [
        item
        for item in partial.unresolved
        if item.kind == "feature_inventory"
        and item.entity_keys == ["R1.CALLOUT.7"]
        and item.field == "engineering_callout_geometry_binding"
    ]
    assert len(unresolved) == 1
    ledger = next(
        item for item in partial.observations if item["kind"] == "hybrid_engineering_callout_ledger"
    )
    assert ledger["items"][0]["binding"]["status"] == "callout_backed"


def test_bound_recess_callout_preserves_noncanonical_facts_as_structured_unresolved():
    report = _report()
    report["regions"] = [
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
    report["annotation_line_candidates"] = [
        {
            "kind": "oblique_line_candidate",
            "endpoints_px": [[96, 96], [125, 125]],
            "angle_deg": 45.0,
            "candidate_only": True,
        },
        {
            "kind": "oblique_line_candidate",
            "endpoints_px": [[130, 130], [155, 155]],
            "angle_deg": 45.0,
            "candidate_only": True,
        },
        {
            "kind": "oblique_line_candidate",
            "endpoints_px": [[160, 160], [192, 192]],
            "angle_deg": 45.0,
            "candidate_only": True,
        },
    ]
    report["coverage"]["routed_elsewhere_or_unclassified_observations"] = [
        {
            "source_item_index": 5,
            "text": "011沉孔深6.5",
            "bbox": [[20, 20], [100, 20], [100, 100], [20, 100]],
            "confidence": 0.99,
        }
    ]

    partial = adapt_hybrid_ocr_report(report, _context())

    values = {
        item.field: item.value
        for item in partial.values
        if item.entity_key == "R1.C1"
    }
    assert values["recess_diameter"] == 11.0
    assert values["recess_depth"] == 6.5
    assert values["recessed_hole"] is True

    fields = {
        item.field
        for item in partial.unresolved
        if item.kind == "feature_value" and item.entity_keys == ["R1.C1"]
    }
    assert fields == {"recessed_hole_subtype"}


def test_adapter_transports_unbound_callout_facts_when_view_region_is_unique():
    report = _report()
    report["regions"] = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 400, 400],
            "circle_groups": [],
        }
    ]
    report["coverage"]["routed_elsewhere_or_unclassified_observations"] = [
        {
            "source_item_index": 1,
            "text": "M6深12",
            "bbox": [[100, 100], [180, 100], [180, 130], [100, 130]],
            "confidence": 0.99,
        }
    ]

    partial = adapt_hybrid_ocr_report(report, _context())

    callout_entities = [item for item in partial.entities if ".CALLOUT." in item.key]
    assert len(callout_entities) == 1
    entity = callout_entities[0]
    assert entity.key == "R1.CALLOUT.1"
    assert entity.view_key == "view.R1"
    assert entity.shape == "other"
    assert entity.cross_view_disposition is None
    assert entity.required_for_modeling is False

    assert [(item.entity_key, item.field, item.value) for item in partial.values] == [
        ("R1.CALLOUT.1", "thread_depth", 12.0),
        ("R1.CALLOUT.1", "thread_spec", "M6"),
    ]

    ownership = [
        item
        for item in partial.unresolved
        if item.kind == "feature_inventory"
        and item.entity_keys == ["R1.CALLOUT.1"]
        and item.field == "engineering_callout_geometry_binding"
    ]
    assert len(ownership) == 1

    ledger = next(
        item for item in partial.observations if item["kind"] == "hybrid_engineering_callout_ledger"
    )
    assert ledger["items"][0]["binding"]["status"] == "callout_backed"
    assert ledger["items"][0]["binding"]["basis"] == "unique_region_callout_fact_transport"


def test_adapter_does_not_transport_unbound_callout_without_unique_view_region():
    report = _report()
    report["regions"] = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 100, 100],
            "circle_groups": [],
        },
        {
            "region_id": "R2",
            "bbox_px": [200, 0, 100, 100],
            "circle_groups": [],
        },
    ]
    report["coverage"]["routed_elsewhere_or_unclassified_observations"] = [
        {
            "source_item_index": 1,
            "text": "M6深12",
            "bbox": [[120, 20], [180, 20], [180, 50], [120, 50]],
            "confidence": 0.99,
        }
    ]

    partial = adapt_hybrid_ocr_report(report, _context())

    assert not [item for item in partial.entities if ".CALLOUT." in item.key]
    assert partial.values == []
    unresolved = [
        item for item in partial.unresolved if item.field == "engineering_callout_geometry_binding"
    ]
    assert len(unresolved) == 1
    assert unresolved[0].kind == "feature_inventory"


def test_secondary_linear_assignments_block_when_no_unique_global_proposal_exists():
    report = {
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "unconfirmed_proposal_observations": [],
            "secondary_assignment_observations": [
                {
                    "candidate_id": "DG10",
                    "source_item_index": 10,
                    "token": "24",
                    "selected_proposal_token": None,
                },
                {
                    "candidate_id": "DG10",
                    "source_item_index": 11,
                    "token": "32",
                    "selected_proposal_token": None,
                },
            ],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [],
        }
    }

    unresolved = hybrid_adapter._coverage_unresolved(
        report,
        {
            "DG10": {
                "candidate_id": "DG10",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": None,
            }
        },
        {
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1"],
            )
        },
        boundaries=[],
        overall_dimension_facts=[],
    )

    blockers = [
        item
        for item in unresolved
        if item.required_for_modeling
        and item.field == "secondary_linear_assignment"
    ]
    assert len(blockers) == 2
    assert all(
        "no unique selected global proposal" in item.reason
        for item in blockers
    )


def test_unconfirmed_global_linear_proposal_stays_blocking_until_consumed():
    report = {
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "unconfirmed_proposal_observations": [
                {
                    "candidate_id": "DG10",
                    "source_item_index": 10,
                    "token": "24",
                    "reason": "insufficient_deterministic_acceptance_evidence",
                }
            ],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [],
        }
    }
    unresolved = hybrid_adapter._coverage_unresolved(
        report,
        {
            "DG10": {
                "candidate_id": "DG10",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": None,
            }
        },
        {
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1"],
            )
        },
        boundaries=[],
        overall_dimension_facts=[],
    )

    blockers = [
        item
        for item in unresolved
        if item.required_for_modeling
        and item.field == "unconfirmed_linear_proposal"
    ]
    assert len(blockers) == 1
    assert blockers[0].axis == "X"
    assert blockers[0].evidence == [
        "hybrid:DG10:whole",
        "hybrid:DG10:wide",
    ]


def test_unconfirmed_global_linear_proposal_is_not_double_blocked_when_consumed():
    report = {
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "unconfirmed_proposal_observations": [
                {
                    "candidate_id": "DG10",
                    "source_item_index": 10,
                    "token": "24",
                    "reason": "insufficient_deterministic_acceptance_evidence",
                }
            ],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [],
        }
    }
    unresolved = hybrid_adapter._coverage_unresolved(
        report,
        {
            "DG10": {
                "candidate_id": "DG10",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": None,
            }
        },
        {
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1"],
            )
        },
        boundaries=[],
        overall_dimension_facts=[],
        excluded_source_item_indices={10},
    )

    assert not [
        item
        for item in unresolved
        if item.field == "unconfirmed_linear_proposal"
    ]


def test_local_only_linear_stays_blocking_for_unresolved_nonconflicting_candidate():
    report = _report()
    report["candidates"].append(
        {
            "candidate_id": "DG10",
            "region_id": "R1",
            "orientation": "horizontal",
            "accepted_token": None,
        }
    )
    report["coverage"]["local_only_linear_observations"].append(
        {
            "candidate_id": "DG10",
            "token": "24",
        }
    )

    partial = adapt_hybrid_ocr_report(report, _context())

    blockers = [
        item
        for item in partial.unresolved
        if item.required_for_modeling and item.field == "local_only_linear_text"
    ]
    assert len(blockers) == 1
    assert blockers[0].evidence == [
        "hybrid:DG10:whole",
        "hybrid:DG10:wide",
    ]


def test_local_only_token_from_rejected_dimension_role_is_advisory():
    report = _report()
    report["candidates"].append(
        {
            "candidate_id": "DG10",
            "region_id": "R1",
            "orientation": "horizontal",
            "accepted_token": None,
            "decision_reason": (
                "candidate_line_is_extension_witness_of_accepted_dimension"
            ),
        }
    )
    report["coverage"]["local_only_linear_observations"].append(
        {
            "candidate_id": "DG10",
            "token": "24",
        }
    )

    partial = adapt_hybrid_ocr_report(report, _context())

    item = next(
        entry
        for entry in partial.unresolved
        if entry.field == "local_only_linear_text"
        and entry.evidence == ["hybrid:DG10:whole", "hybrid:DG10:wide"]
    )
    assert item.required_for_modeling is False
    assert "extension/witness line" in item.reason
    assert "advisory OCR coverage" in item.reason


def _overlap_profile_edge(
    region_id,
    ref,
    *,
    orientation,
    position,
    span,
    support=1,
):
    return {
        "kind": "profile_edge_candidate",
        "region_id": region_id,
        "ref": ref,
        "source_orientation": orientation,
        "position_px": float(position),
        "span_px": [float(span[0]), float(span[1])],
        "axis_tolerance_px": 1.0,
        "non_dimension_crossing_source_count": support,
    }


def test_overlapping_profile_associations_merge_only_mutual_unique_edges():
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
            {"region_id": "R2", "bbox_px": [50, 0, 200, 200]},
        ]
    }
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["structural:R1"],
        ),
        "R2": hybrid_adapter.HybridRegionView(
            region_id="R2",
            view_kind="front",
            evidence=["structural:R2"],
        ),
    }
    inventory = [
        _overlap_profile_edge(
            "R1", "R1.H1", orientation="horizontal", position=40, span=[20, 180]
        ),
        _overlap_profile_edge(
            "R1", "R1.V1", orientation="vertical", position=80, span=[10, 190]
        ),
        _overlap_profile_edge(
            "R1", "R1.V2", orientation="vertical", position=140, span=[20, 180]
        ),
        _overlap_profile_edge(
            "R2", "R2.H1", orientation="horizontal", position=40, span=[60, 180]
        ),
        _overlap_profile_edge(
            "R2", "R2.V1", orientation="vertical", position=80, span=[20, 190]
        ),
        _overlap_profile_edge(
            "R2", "R2.V2", orientation="vertical", position=140, span=[30, 170]
        ),
    ]
    by_ref = {
        item["ref"]: f"{item['region_id']}.PROFILE.{item['ref']}"
        for item in inventory
    }

    associations = hybrid_adapter._overlapping_profile_associations(
        report=report,
        profile_inventory=inventory,
        view_lookup=view_lookup,
        profile_entity_by_ref=by_ref,
    )

    paired_refs = {
        tuple(
            sorted(
                entity.split(".PROFILE.", 1)[1]
                for entity in association.entity_keys
            )
        )
        for association in associations
    }
    assert ("R1.H1", "R2.H1") in paired_refs
    assert ("R1.V1", "R2.V1") in paired_refs
    assert ("R1.V2", "R2.V2") in paired_refs
    assert all(
        association.basis == ["shared_raster_profile_identity"]
        for association in associations
    )


def test_overlapping_profile_associations_merge_exact_geometry_without_nondimension_support():
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
            {"region_id": "R2", "bbox_px": [50, 0, 200, 200]},
        ]
    }
    view_lookup = {
        region_id: hybrid_adapter.HybridRegionView(
            region_id=region_id,
            view_kind="front",
            evidence=[f"structural:{region_id}"],
        )
        for region_id in ("R1", "R2")
    }
    inventory = [
        _overlap_profile_edge(
            "R1",
            "R1.EXACT",
            orientation="vertical",
            position=386.0,
            span=[383.0, 442.0],
            support=0,
        ),
        _overlap_profile_edge(
            "R2",
            "R2.EXACT",
            orientation="vertical",
            position=386.0,
            span=[383.0, 442.0],
            support=0,
        ),
        # Two independently supported recurring edges prove that R1/R2 are
        # overlapping crops of the same raster view. They are intentionally
        # omitted from profile_entity_by_ref below so this test isolates the
        # exact-geometry identity path for the support=0 edge.
        _overlap_profile_edge(
            "R1",
            "R1.PROOF_H",
            orientation="horizontal",
            position=100.0,
            span=[60.0, 180.0],
            support=1,
        ),
        _overlap_profile_edge(
            "R2",
            "R2.PROOF_H",
            orientation="horizontal",
            position=100.0,
            span=[60.0, 180.0],
            support=1,
        ),
        _overlap_profile_edge(
            "R1",
            "R1.PROOF_V",
            orientation="vertical",
            position=120.0,
            span=[20.0, 190.0],
            support=1,
        ),
        _overlap_profile_edge(
            "R2",
            "R2.PROOF_V",
            orientation="vertical",
            position=120.0,
            span=[20.0, 190.0],
            support=1,
        ),
    ]
    by_ref = {
        item["ref"]: f"{item['region_id']}.PROFILE.{item['ref']}"
        for item in inventory
        if item["ref"].endswith(".EXACT")
    }

    associations = hybrid_adapter._overlapping_profile_associations(
        report=report,
        profile_inventory=inventory,
        view_lookup=view_lookup,
        profile_entity_by_ref=by_ref,
    )

    assert len(associations) == 1
    assert sorted(associations[0].entity_keys) == sorted(by_ref.values())
    assert associations[0].basis == ["shared_raster_profile_identity"]


def test_overlapping_profile_associations_keep_support_gate_for_approximate_geometry():
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
            {"region_id": "R2", "bbox_px": [50, 0, 200, 200]},
        ]
    }
    view_lookup = {
        region_id: hybrid_adapter.HybridRegionView(
            region_id=region_id,
            view_kind="front",
            evidence=[f"structural:{region_id}"],
        )
        for region_id in ("R1", "R2")
    }
    inventory = [
        _overlap_profile_edge(
            "R1",
            "R1.APPROX",
            orientation="vertical",
            position=386.0,
            span=[383.0, 442.0],
            support=0,
        ),
        _overlap_profile_edge(
            "R2",
            "R2.APPROX",
            orientation="vertical",
            position=386.5,
            span=[383.0, 442.0],
            support=0,
        ),
        _overlap_profile_edge(
            "R1",
            "R1.PROOF_H",
            orientation="horizontal",
            position=100.0,
            span=[60.0, 180.0],
            support=1,
        ),
        _overlap_profile_edge(
            "R2",
            "R2.PROOF_H",
            orientation="horizontal",
            position=100.0,
            span=[60.0, 180.0],
            support=1,
        ),
        _overlap_profile_edge(
            "R1",
            "R1.PROOF_V",
            orientation="vertical",
            position=120.0,
            span=[20.0, 190.0],
            support=1,
        ),
        _overlap_profile_edge(
            "R2",
            "R2.PROOF_V",
            orientation="vertical",
            position=120.0,
            span=[20.0, 190.0],
            support=1,
        ),
    ]
    by_ref = {
        item["ref"]: f"{item['region_id']}.PROFILE.{item['ref']}"
        for item in inventory
        if item["ref"].endswith(".APPROX")
    }

    associations = hybrid_adapter._overlapping_profile_associations(
        report=report,
        profile_inventory=inventory,
        view_lookup=view_lookup,
        profile_entity_by_ref=by_ref,
    )

    assert associations == []


def test_overlapping_profile_associations_fail_closed_on_one_to_many_match():
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
            {"region_id": "R2", "bbox_px": [50, 0, 200, 200]},
        ]
    }
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["structural:R1"],
        ),
        "R2": hybrid_adapter.HybridRegionView(
            region_id="R2",
            view_kind="front",
            evidence=["structural:R2"],
        ),
    }
    inventory = [
        _overlap_profile_edge(
            "R1", "R1.SHARED_A", orientation="horizontal", position=40, span=[20, 180]
        ),
        _overlap_profile_edge(
            "R1", "R1.SHARED_B", orientation="vertical", position=80, span=[10, 190]
        ),
        _overlap_profile_edge(
            "R1", "R1.AMB", orientation="vertical", position=140, span=[20, 180]
        ),
        _overlap_profile_edge(
            "R2", "R2.SHARED_A", orientation="horizontal", position=40, span=[60, 180]
        ),
        _overlap_profile_edge(
            "R2", "R2.SHARED_B", orientation="vertical", position=80, span=[20, 190]
        ),
        _overlap_profile_edge(
            "R2", "R2.AMB_TOP", orientation="vertical", position=140, span=[20, 120]
        ),
        _overlap_profile_edge(
            "R2", "R2.AMB_BOTTOM", orientation="vertical", position=140, span=[80, 180]
        ),
    ]
    by_ref = {
        item["ref"]: f"{item['region_id']}.PROFILE.{item['ref']}"
        for item in inventory
    }

    associations = hybrid_adapter._overlapping_profile_associations(
        report=report,
        profile_inventory=inventory,
        view_lookup=view_lookup,
        profile_entity_by_ref=by_ref,
    )

    associated_entities = {
        entity
        for association in associations
        for entity in association.entity_keys
    }
    assert by_ref["R1.AMB"] not in associated_entities
    assert by_ref["R2.AMB_TOP"] not in associated_entities
    assert by_ref["R2.AMB_BOTTOM"] not in associated_entities


def _symmetric_profile_test_context():
    return hybrid_adapter.HybridAdapterContext(
        region_views=[
            hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1:context"],
            ),
            hybrid_adapter.HybridRegionView(
                region_id="R2",
                view_kind="front",
                evidence=["structural:R2:context"],
            ),
        ],
        overall_dimension_facts=[
            hybrid_adapter.PartialOverallDimensionFact(
                axis="X",
                value=100.0,
                evidence=["structural:R1:context"],
            )
        ],
        rotational_symmetry_facts=[
            hybrid_adapter.PartialRotationalSymmetryFact(
                axis="Z",
                evidence=[
                    "structural:R1:context",
                    "structural:R2:context",
                ],
            )
        ],
    )


def _symmetric_profile_test_candidate(
    candidate_id,
    region_id,
    token,
    witnesses,
):
    midpoint = sum(witnesses) / len(witnesses)
    return {
        "candidate_id": candidate_id,
        "region_id": region_id,
        "orientation": "horizontal",
        "axis_px": 50.0,
        "accepted_token": str(token),
        "global_assignments": [
            {
                "token": str(token),
                "bbox": [
                    [midpoint - 5.0, 40.0],
                    [midpoint + 5.0, 40.0],
                    [midpoint + 5.0, 60.0],
                    [midpoint - 5.0, 60.0],
                ],
            }
        ],
        "witness_positions_px": witnesses,
        "witness_anchor_evidence": [
            {
                "witness_index": index,
                "position_px": witness,
                "nearest_anchors": [],
            }
            for index, witness in enumerate(witnesses)
        ],
        "witness_line_evidence": [
            {
                "witness_index": index,
                "position_px": witness,
                "source_lines": [],
            }
            for index, witness in enumerate(witnesses)
        ],
    }


def _symmetric_profile_test_inventory():
    return [
        {
            "region_id": region_id,
            "kind": "profile_edge_candidate",
            "ref": f"{region_id}.LEFT",
            "position_px": 20.0,
            "source_orientation": "vertical",
            "span_px": [20.0, 80.0],
            "axis_tolerance_px": 2.0,
            "non_dimension_crossing_source_count": 2,
        }
        for region_id in ("R1", "R2")
    ] + [
        {
            "region_id": region_id,
            "kind": "profile_edge_candidate",
            "ref": f"{region_id}.RIGHT",
            "position_px": 80.0,
            "source_orientation": "vertical",
            "span_px": [20.0, 80.0],
            "axis_tolerance_px": 2.0,
            "non_dimension_crossing_source_count": 2,
        }
        for region_id in ("R1", "R2")
    ]


def _resolved_profile_span_center_test_record(
    *,
    dimension_key="R1.DG_SPAN",
    region_id="R1",
    midpoint=50.0,
):
    return {
        "dimension_key": dimension_key,
        "candidate_id": dimension_key.split(".")[-1],
        "region_id": region_id,
        "axis": "X",
        "profile_entity_keys": [
            f"{region_id}.LEFT_PROFILE",
            f"{region_id}.RIGHT_PROFILE",
        ],
        "selected_witness_positions_px": [midpoint - 20.0, midpoint + 20.0],
        "span_midpoint_px": midpoint,
        "source_ids": [f"test:{dimension_key}"],
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }


def test_profile_span_center_record_needs_only_resolved_profile_pair():
    candidate = _symmetric_profile_test_candidate(
        "DG_SPAN",
        "R1",
        "40",
        [30.0, 70.0],
    )
    record = hybrid_adapter._profile_span_center_record(
        candidate=candidate,
        dimension_key="R1.DG_SPAN",
        axis="X",
        dimension_endpoints=[
            hybrid_adapter.ObservationDimensionEndpoint(
                role="profile_boundary",
                entity_key="R1.LEFT_PROFILE",
                basis="profile_edge",
                evidence=["test:left"],
            ),
            hybrid_adapter.ObservationDimensionEndpoint(
                role="profile_boundary",
                entity_key="R1.RIGHT_PROFILE",
                basis="profile_edge",
                evidence=["test:right"],
            ),
        ],
    )

    assert record is not None
    assert record["span_midpoint_px"] == 50.0
    assert record["engineering_coordinate_inferred_from_pixels"] is False


def test_dimension_span_center_identity_accepts_unique_witness_match():
    candidate = _symmetric_profile_test_candidate(
        "DG_DISTANCE",
        "R1",
        "30",
        [50.0, 90.0],
    )
    dimension = hybrid_adapter.ObservationDimension(
        key="R1.DG_DISTANCE",
        value=30,
        axis="X",
        endpoints=[
            hybrid_adapter.ObservationDimensionEndpoint(
                role="unresolved",
                unresolved_kind="intermediate_surface",
                evidence=["test:w0"],
            ),
            hybrid_adapter.ObservationDimensionEndpoint(
                role="overall_max",
                evidence=["test:w1"],
            ),
        ],
        unresolved_reason="first endpoint unresolved",
        direction=1,
        evidence=["test:dimension"],
    )

    records = hybrid_adapter._dimension_span_center_identity_records(
        dimensions=[dimension],
        candidates=[candidate],
        profile_span_records=[_resolved_profile_span_center_test_record()],
        report={"regions": [{"region_id": "R1", "bbox_px": [0, 0, 100, 100]}]},
        view_lookup={"R1": _symmetric_profile_test_context().region_views[0]},
        profile_inventory=[],
    )

    assert len(records) == 1
    assert records[0]["endpoint_index"] == 0
    assert records[0]["span_dimension_key"] == "R1.DG_SPAN"
    assert records[0]["basis"] == (
        "unique_witness_to_resolved_profile_span_midpoint"
    )
    assert records[0]["engineering_coordinate_inferred_from_pixels"] is False


def test_dimension_span_center_identity_rejects_ambiguous_midpoint_match():
    candidate = _symmetric_profile_test_candidate(
        "DG_DISTANCE",
        "R1",
        "30",
        [50.0, 90.0],
    )
    dimension = hybrid_adapter.ObservationDimension(
        key="R1.DG_DISTANCE",
        value=30,
        axis="X",
        endpoints=[
            hybrid_adapter.ObservationDimensionEndpoint(
                role="unresolved",
                unresolved_kind="intermediate_surface",
                evidence=["test:w0"],
            ),
            hybrid_adapter.ObservationDimensionEndpoint(
                role="overall_max",
                evidence=["test:w1"],
            ),
        ],
        unresolved_reason="first endpoint unresolved",
        evidence=["test:dimension"],
    )

    records = hybrid_adapter._dimension_span_center_identity_records(
        dimensions=[dimension],
        candidates=[candidate],
        profile_span_records=[
            _resolved_profile_span_center_test_record(
                dimension_key="R1.DG_SPAN_A"
            ),
            _resolved_profile_span_center_test_record(
                dimension_key="R1.DG_SPAN_B"
            ),
        ],
        report={"regions": [{"region_id": "R1", "bbox_px": [0, 0, 100, 100]}]},
        view_lookup={"R1": _symmetric_profile_test_context().region_views[0]},
        profile_inventory=[],
    )

    assert records == []


def test_dimension_span_center_identity_does_not_override_ambiguous_owner():
    candidate = _symmetric_profile_test_candidate(
        "DG_DISTANCE",
        "R1",
        "30",
        [50.0, 90.0],
    )
    dimension = hybrid_adapter.ObservationDimension(
        key="R1.DG_DISTANCE",
        value=30,
        axis="X",
        endpoints=[
            hybrid_adapter.ObservationDimensionEndpoint(
                role="unresolved",
                candidate_entity_keys=["R1.LEFT_PROFILE", "R1.RIGHT_PROFILE"],
                unresolved_kind="ambiguous_owner",
                evidence=["test:w0"],
            ),
            hybrid_adapter.ObservationDimensionEndpoint(
                role="overall_max",
                evidence=["test:w1"],
            ),
        ],
        unresolved_reason="first endpoint ambiguous",
        evidence=["test:dimension"],
    )

    records = hybrid_adapter._dimension_span_center_identity_records(
        dimensions=[dimension],
        candidates=[candidate],
        profile_span_records=[_resolved_profile_span_center_test_record()],
        report={"regions": [{"region_id": "R1", "bbox_px": [0, 0, 100, 100]}]},
        view_lookup={"R1": _symmetric_profile_test_context().region_views[0]},
        profile_inventory=[],
    )

    assert records == []


def test_projected_profile_level_accepts_structural_collinear_gap(monkeypatch):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_dimension_endpoint_candidates",
        lambda candidate: {
            "selected_witness_positions_px": [100.0, 200.0],
            "endpoints": [
                {
                    "ignored_nonownership_anchors": [
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.structural.vertical.010",
                            "position_px": 101.0,
                            "source_orientation": "vertical",
                            "axis_tolerance_px": 4.0,
                            "junction_count": 2,
                            "endpoint_junction_count": 2,
                            "non_dimension_crossing_source_count": 3,
                            "ownership_rejection_reason": (
                                "profile_not_connected_to_witness_terminal"
                            ),
                        }
                    ]
                },
                {"ignored_nonownership_anchors": []},
            ],
        },
    )
    candidate = {
        "candidate_id": "DG_PROJECTED",
        "region_id": "R1",
        "orientation": "horizontal",
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 100.0,
                        "span_px": [10.0, 40.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            }
        ],
    }
    endpoints = [
        hybrid_adapter.ObservationDimensionEndpoint(
            role="unresolved",
            unresolved_kind="intermediate_surface",
            evidence=["test:left"],
        ),
        hybrid_adapter.ObservationDimensionEndpoint(
            role="unresolved",
            unresolved_kind="intermediate_surface",
            evidence=["test:right"],
        ),
    ]

    records = hybrid_adapter._projected_profile_level_records(
        candidate=candidate,
        dimension_key="R1.DG_PROJECTED",
        axis="X",
        dimension_endpoints=endpoints,
        boundary_roles={"R1.structural.vertical.010": "overall_min"},
        profile_entity_by_ref={
            "R1.structural.vertical.010": "R1.PROFILE.LEFT",
        },
    )

    assert len(records) == 1
    assert records[0]["endpoint_index"] == 0
    assert records[0]["profile_refs"] == ["R1.structural.vertical.010"]
    assert records[0]["profile_entity_keys"] == ["R1.PROFILE.LEFT"]
    assert records[0]["overall_role"] == "overall_min"
    assert records[0]["engineering_coordinate_inferred_from_pixels"] is False


def test_projected_profile_level_rejects_multiple_coordinate_clusters(monkeypatch):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_dimension_endpoint_candidates",
        lambda candidate: {
            "selected_witness_positions_px": [100.0, 200.0],
            "endpoints": [
                {
                    "ignored_nonownership_anchors": [
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.structural.vertical.010",
                            "position_px": 98.0,
                            "source_orientation": "vertical",
                            "axis_tolerance_px": 2.0,
                            "junction_count": 2,
                            "endpoint_junction_count": 2,
                            "non_dimension_crossing_source_count": 2,
                            "ownership_rejection_reason": (
                                "profile_not_connected_to_witness_terminal"
                            ),
                        },
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.structural.vertical.020",
                            "position_px": 102.0,
                            "source_orientation": "vertical",
                            "axis_tolerance_px": 2.0,
                            "junction_count": 2,
                            "endpoint_junction_count": 2,
                            "non_dimension_crossing_source_count": 2,
                            "ownership_rejection_reason": (
                                "profile_not_connected_to_witness_terminal"
                            ),
                        },
                    ]
                },
                {"ignored_nonownership_anchors": []},
            ],
        },
    )
    candidate = {
        "candidate_id": "DG_AMBIG_LEVEL",
        "region_id": "R1",
        "orientation": "horizontal",
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 100.0,
                        "span_px": [10.0, 40.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            }
        ],
    }
    endpoints = [
        hybrid_adapter.ObservationDimensionEndpoint(
            role="unresolved",
            unresolved_kind="intermediate_surface",
            evidence=["test:left"],
        ),
        hybrid_adapter.ObservationDimensionEndpoint(
            role="unresolved",
            unresolved_kind="intermediate_surface",
            evidence=["test:right"],
        ),
    ]

    assert hybrid_adapter._projected_profile_level_records(
        candidate=candidate,
        dimension_key="R1.DG_AMBIG_LEVEL",
        axis="X",
        dimension_endpoints=endpoints,
        boundary_roles={},
        profile_entity_by_ref={
            "R1.structural.vertical.010": "R1.PROFILE.LEFT_A",
            "R1.structural.vertical.020": "R1.PROFILE.LEFT_B",
        },
    ) == []


def test_projected_profile_level_never_overrides_ambiguous_owner(monkeypatch):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_dimension_endpoint_candidates",
        lambda candidate: {
            "selected_witness_positions_px": [100.0, 200.0],
            "endpoints": [
                {
                    "ignored_nonownership_anchors": [
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.structural.vertical.010",
                            "position_px": 100.0,
                            "source_orientation": "vertical",
                            "axis_tolerance_px": 4.0,
                            "junction_count": 2,
                            "endpoint_junction_count": 2,
                            "non_dimension_crossing_source_count": 2,
                            "ownership_rejection_reason": (
                                "profile_not_connected_to_witness_terminal"
                            ),
                        }
                    ]
                },
                {"ignored_nonownership_anchors": []},
            ],
        },
    )
    candidate = {
        "candidate_id": "DG_AMBIG_OWNER",
        "region_id": "R1",
        "orientation": "horizontal",
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 100.0,
                        "span_px": [10.0, 40.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            }
        ],
    }
    endpoints = [
        hybrid_adapter.ObservationDimensionEndpoint(
            role="unresolved",
            unresolved_kind="ambiguous_owner",
            candidate_entity_keys=[
                "R1.PROFILE_BOUNDARY.LEFT_A",
                "R1.PROFILE_BOUNDARY.LEFT_B",
            ],
            evidence=["test:left"],
        ),
        hybrid_adapter.ObservationDimensionEndpoint(
            role="unresolved",
            unresolved_kind="intermediate_surface",
            evidence=["test:right"],
        ),
    ]

    assert hybrid_adapter._projected_profile_level_records(
        candidate=candidate,
        dimension_key="R1.DG_AMBIG_OWNER",
        axis="X",
        dimension_endpoints=endpoints,
        boundary_roles={},
        profile_entity_by_ref={
            "R1.structural.vertical.010": "R1.PROFILE.LEFT_A",
            "R1.structural.vertical.020": "R1.PROFILE.LEFT_B",
        },
    ) == []


def test_symmetric_dimension_pair_accepts_centered_pair_without_endpoint_ownership():
    context = _symmetric_profile_test_context()
    anchor = _symmetric_profile_test_candidate(
        "DG_OVERALL",
        "R1",
        "100",
        [0.0, 100.0],
    )
    candidate = _symmetric_profile_test_candidate(
        "DG_CENTER_DISTANCE",
        "R2",
        "60",
        [20.0, 80.0],
    )

    record = hybrid_adapter._symmetric_dimension_pair_record(
        candidate=candidate,
        dimension_key="R2.DG_CENTER_DISTANCE",
        dimension_value=60.0,
        axis="X",
        candidates=[anchor, candidate],
        report={
            "regions": [
                {"region_id": "R1", "bbox_px": [0, 10, 100, 80]},
                {"region_id": "R2", "bbox_px": [10, 0, 80, 100]},
            ]
        },
        context=context,
        view_lookup={item.region_id: item for item in context.region_views},
        profile_inventory=_symmetric_profile_test_inventory(),
        overall_dimensions={"length_x": 100.0},
    )

    assert record is not None
    assert record["dimension_key"] == "R2.DG_CENTER_DISTANCE"
    assert record["overall_candidate_id"] == "DG_OVERALL"
    assert record["engineering_coordinate_inferred_from_pixels"] is False
    assert "profile_entity_keys" not in record


def test_symmetric_dimension_pair_rejects_off_center_pair():
    context = _symmetric_profile_test_context()
    anchor = _symmetric_profile_test_candidate(
        "DG_OVERALL",
        "R1",
        "100",
        [0.0, 100.0],
    )
    candidate = _symmetric_profile_test_candidate(
        "DG_LOCAL",
        "R2",
        "20",
        [10.0, 30.0],
    )

    assert hybrid_adapter._symmetric_dimension_pair_record(
        candidate=candidate,
        dimension_key="R2.DG_LOCAL",
        dimension_value=20.0,
        axis="X",
        candidates=[anchor, candidate],
        report={
            "regions": [
                {"region_id": "R1", "bbox_px": [0, 10, 100, 80]},
                {"region_id": "R2", "bbox_px": [10, 0, 80, 100]},
            ]
        },
        context=context,
        view_lookup={item.region_id: item for item in context.region_views},
        profile_inventory=_symmetric_profile_test_inventory(),
        overall_dimensions={"length_x": 100.0},
    ) is None


def test_symmetric_dimension_pair_does_not_duplicate_overall_dimension():
    context = _symmetric_profile_test_context()
    anchor = _symmetric_profile_test_candidate(
        "DG_OVERALL",
        "R1",
        "100",
        [0.0, 100.0],
    )

    assert hybrid_adapter._symmetric_dimension_pair_record(
        candidate=anchor,
        dimension_key="R1.DG_OVERALL",
        dimension_value=100.0,
        axis="X",
        candidates=[anchor],
        report={
            "regions": [
                {"region_id": "R1", "bbox_px": [0, 0, 100, 100]},
            ]
        },
        context=context,
        view_lookup={item.region_id: item for item in context.region_views},
        profile_inventory=_symmetric_profile_test_inventory(),
        overall_dimensions={"length_x": 100.0},
    ) is None


def test_symmetric_profile_span_accepts_resolved_centered_profile_pair():
    context = _symmetric_profile_test_context()
    anchor = _symmetric_profile_test_candidate(
        "DG_OVERALL",
        "R1",
        "100",
        [0.0, 100.0],
    )
    candidate = _symmetric_profile_test_candidate(
        "DG_SPAN",
        "R2",
        "40",
        [30.0, 70.0],
    )
    record = hybrid_adapter._symmetric_profile_span_record(
        candidate=candidate,
        dimension_key="R2.DG_SPAN",
        dimension_value=40.0,
        axis="X",
        dimension_endpoints=[
            hybrid_adapter.ObservationDimensionEndpoint(
                role="profile_boundary",
                entity_key="R2.LEFT_PROFILE",
                basis="profile_edge",
                evidence=["test:left"],
            ),
            hybrid_adapter.ObservationDimensionEndpoint(
                role="profile_boundary",
                entity_key="R2.RIGHT_PROFILE",
                basis="profile_edge",
                evidence=["test:right"],
            ),
        ],
        candidates=[anchor, candidate],
        report={
            "regions": [
                {"region_id": "R1", "bbox_px": [0, 10, 100, 80]},
                {"region_id": "R2", "bbox_px": [10, 0, 80, 100]},
            ]
        },
        context=context,
        view_lookup={item.region_id: item for item in context.region_views},
        profile_inventory=_symmetric_profile_test_inventory(),
        overall_dimensions={"length_x": 100.0},
    )

    assert record is not None
    assert record["profile_entity_keys"] == [
        "R2.LEFT_PROFILE",
        "R2.RIGHT_PROFILE",
    ]
    assert record["overall_candidate_id"] == "DG_OVERALL"
    assert record["engineering_coordinate_inferred_from_pixels"] is False


def test_symmetric_profile_span_rejects_off_center_local_profile_pair():
    context = _symmetric_profile_test_context()
    anchor = _symmetric_profile_test_candidate(
        "DG_OVERALL",
        "R1",
        "100",
        [0.0, 100.0],
    )
    candidate = _symmetric_profile_test_candidate(
        "DG_LOCAL",
        "R2",
        "20",
        [10.0, 30.0],
    )
    record = hybrid_adapter._symmetric_profile_span_record(
        candidate=candidate,
        dimension_key="R2.DG_LOCAL",
        dimension_value=20.0,
        axis="X",
        dimension_endpoints=[
            hybrid_adapter.ObservationDimensionEndpoint(
                role="profile_boundary",
                entity_key="R2.LEFT_PROFILE",
                basis="profile_edge",
                evidence=["test:left"],
            ),
            hybrid_adapter.ObservationDimensionEndpoint(
                role="profile_boundary",
                entity_key="R2.RIGHT_PROFILE",
                basis="profile_edge",
                evidence=["test:right"],
            ),
        ],
        candidates=[anchor, candidate],
        report={
            "regions": [
                {"region_id": "R1", "bbox_px": [0, 10, 100, 80]},
                {"region_id": "R2", "bbox_px": [10, 0, 80, 100]},
            ]
        },
        context=context,
        view_lookup={item.region_id: item for item in context.region_views},
        profile_inventory=_symmetric_profile_test_inventory(),
        overall_dimensions={"length_x": 100.0},
    )

    assert record is None


def test_adapter_closes_only_explicit_circle_center_endpoint_candidate():
    report = _report()
    report["regions"] = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 400, 400],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [100, 100],
                    "rings": [{"radius_px": 20}],
                }
            ],
        },
        {
            "region_id": "R2",
            "bbox_px": [500, 0, 300, 400],
            "circle_groups": [],
        },
    ]
    report["candidates"][0]["witness_anchor_evidence"][0]["nearest_anchors"][0]["ref"] = (
        "R1.C1.center_x"
    )

    partial = adapt_hybrid_ocr_report(report, _context())

    dimension = next(item for item in partial.dimensions if item.key == "R1.DG12")
    assert dimension.endpoints[0].role == "entity_center"
    assert dimension.endpoints[0].entity_key == "R1.C1"
    assert dimension.endpoints[0].basis == "circle_center"
    assert dimension.endpoints[1].role == "unresolved"
    assert dimension.endpoints[1].unresolved_kind == "intermediate_surface"
    assert dimension.unresolved_reason is not None


def test_adapter_never_emits_pixel_derived_metric_ledgers():
    partial = adapt_hybrid_ocr_report(
        _report(),
        HybridAdapterContext.model_validate(
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
                    {"axis": "X", "value": 40, "evidence": ["overall:X"]},
                    {"axis": "Z", "value": 66, "evidence": ["overall:Z"]},
                ],
            }
        ),
    )

    forbidden = {
        "hybrid_view_metric_calibration_ledger",
        "hybrid_metric_profile_edge_ledger",
        "hybrid_metric_profile_segment_ledger",
        "hybrid_metric_circle_primitive_ledger",
    }
    assert forbidden.isdisjoint(
        {
            item.get("kind")
            for item in partial.observations
            if isinstance(item, dict)
        }
    )


def test_adapter_preserves_ocr_conflict_without_pixel_metric_fallback():
    partial = adapt_hybrid_ocr_report(
        _report(),
        HybridAdapterContext.model_validate(
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
                    {"axis": "Z", "value": 66, "evidence": ["overall:Z"]},
                ],
            }
        ),
    )

    assert "R1.DG17" not in {item.key for item in partial.dimensions}
    blockers = [
        item
        for item in partial.unresolved
        if item.required_for_modeling and item.field == "dimension_value_candidate"
    ]
    assert len(blockers) == 1
    assert not any(
        str(item.get("kind", "")).startswith("hybrid_metric_")
        or item.get("kind") == "hybrid_view_metric_calibration_ledger"
        for item in partial.observations
        if isinstance(item, dict)
    )


def test_adapter_does_not_turn_circle_or_profile_pixels_into_engineering_coordinates():
    report = _report()
    report["regions"] = [
        {
            "region_id": "R1",
            "bbox_px": [0, 0, 400, 300],
            "circle_groups": [
                {
                    "circle_group_id": "C1",
                    "center_px": [200, 150],
                    "rings": [{"radius_px": 30}],
                }
            ],
        },
        {
            "region_id": "R2",
            "bbox_px": [400, 0, 300, 300],
            "circle_groups": [],
        },
    ]

    partial = adapt_hybrid_ocr_report(
        report,
        HybridAdapterContext.model_validate(
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
                    {"axis": "X", "value": 40, "evidence": ["overall:X"]},
                    {"axis": "Z", "value": 66, "evidence": ["overall:Z"]},
                ],
            }
        ),
    )

    serialized = partial.model_dump(mode="json")
    text = repr(serialized)
    for forbidden_key in (
        "mm_per_px",
        "coordinate_mm",
        "center_mm",
        "point_mm",
        "fixed_coordinate_mm",
    ):
        assert forbidden_key not in text


def test_full_profile_inventory_remains_visual_evidence_not_metric_truth():
    report = _report()
    report["structural_profile_inventory"] = [
        {
            "region_id": "R1",
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.UNREFERENCED",
            "position_px": 200.0,
            "source_orientation": "vertical",
            "span_px": [40, 260],
        }
    ]

    partial = adapt_hybrid_ocr_report(
        report,
        HybridAdapterContext.model_validate(
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
                    {"axis": "X", "value": 40, "evidence": ["overall:X"]},
                    {"axis": "Z", "value": 66, "evidence": ["overall:Z"]},
                ],
            }
        ),
    )

    assert not any(
        item.get("kind")
        in {
            "hybrid_view_metric_calibration_ledger",
            "hybrid_metric_profile_edge_ledger",
            "hybrid_metric_profile_segment_ledger",
            "hybrid_metric_circle_primitive_ledger",
        }
        for item in partial.observations
        if isinstance(item, dict)
    )




def test_pattern_backed_m6_reuses_existing_hidden_pair_entity(monkeypatch):
    report = {
        "coverage": {
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 1,
                    "text": "M6深12",
                    "bbox": [[100, 100], [180, 100], [180, 130], [100, 130]],
                    "confidence": 0.99,
                }
            ]
        },
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 400, 400],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            }
        ],
        "annotation_line_candidates": [],
    }
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        )
    }

    monkeypatch.setattr(
        hybrid_adapter,
        "bind_callout_to_circle_entity",
        lambda *args, **kwargs: {"status": "unresolved"},
    )
    monkeypatch.setattr(
        hybrid_adapter,
        "bind_callout_to_linear_pattern",
        lambda *args, **kwargs: {
            "status": "bound",
            "entity_key": "R1.LINEAR_PATTERN.004",
            "region_id": "R1",
            "pattern_index": 3,
            "orientation": "horizontal",
            "axis": "X",
        },
    )

    ledger, entities, values, unresolved = hybrid_adapter._engineering_callout_routing(
        report,
        [],
        view_lookup,
        hidden_pattern_owner_by_index={
            ("R1", 3): "R1.HIDDEN_PAIR.horizontal.004.005"
        },
        existing_entity_keys={"R1.HIDDEN_PAIR.horizontal.004.005"},
    )

    assert entities == []
    assert unresolved == []
    assert {
        (item.entity_key, item.field, item.value)
        for item in values
    } == {
        ("R1.HIDDEN_PAIR.horizontal.004.005", "thread_depth", 12.0),
        ("R1.HIDDEN_PAIR.horizontal.004.005", "thread_spec", "M6"),
    }
    assert ledger[0]["binding"]["entity_key"] == "R1.HIDDEN_PAIR.horizontal.004.005"
    assert ledger[0]["binding"]["hidden_pair_owner_reused"] is True

def test_overall_ocr_conflict_becomes_advisory_only_with_independent_closed_overall(
    monkeypatch,
):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_view_axis_boundaries",
        lambda **kwargs: [
            {
                "status": "resolved",
                "region_id": "R1",
                "view_kind": "front",
                "axis": "Z",
                "candidate_id": "DG17",
                "overall_dimension_value": 66.0,
                "anchors": [
                    {"role": "overall_max"},
                    {"role": "overall_min"},
                ],
                "basis": "conflict_preserved_overall_dimension_endpoint_identity",
                "engineering_coordinate_inferred_from_pixels": False,
            }
        ],
    )

    partial = adapt_hybrid_ocr_report(
        _report(),
        HybridAdapterContext.model_validate(
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
                        "axis": "Z",
                        "value": 66,
                        "evidence": ["independent:overall-Z-66"],
                    },
                ],
            }
        ),
    )

    conflict = next(
        item
        for item in partial.unresolved
        if item.field == "dimension_value_candidate"
    )
    assert conflict.required_for_modeling is False
    assert conflict.basis == []
    assert "preserved as advisory evidence" in conflict.reason


def test_overall_ocr_conflict_stays_blocking_when_overall_fact_reuses_same_candidate(
    monkeypatch,
):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_view_axis_boundaries",
        lambda **kwargs: [
            {
                "status": "resolved",
                "region_id": "R1",
                "view_kind": "front",
                "axis": "Z",
                "candidate_id": "DG17",
                "overall_dimension_value": 66.0,
                "anchors": [
                    {"role": "overall_max"},
                    {"role": "overall_min"},
                ],
                "basis": "conflict_preserved_overall_dimension_endpoint_identity",
                "engineering_coordinate_inferred_from_pixels": False,
            }
        ],
    )

    partial = adapt_hybrid_ocr_report(
        _report(),
        HybridAdapterContext.model_validate(
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
                        "axis": "Z",
                        "value": 66,
                        "evidence": ["hybrid:DG17:wide"],
                    },
                ],
            }
        ),
    )

    conflict = next(
        item
        for item in partial.unresolved
        if item.field == "dimension_value_candidate"
    )
    assert conflict.required_for_modeling is True

def test_local_only_duplicate_witness_topology_is_advisory():
    shared_left = {
        "orientation": "vertical",
        "axis_px": 100.0,
        "span_px": [20, 180],
    }
    shared_right = {
        "orientation": "vertical",
        "axis_px": 200.0,
        "span_px": [20, 180],
    }
    accepted = {
        "candidate_id": "DG_ACCEPTED",
        "region_id": "R1",
        "orientation": "horizontal",
        "accepted_token": "24",
        "witness_line_evidence": [
            {"witness_index": 0, "source_lines": [shared_left]},
            {"witness_index": 1, "source_lines": [shared_right]},
        ],
    }
    local_only = {
        "candidate_id": "DG_LOCAL",
        "region_id": "R1",
        "orientation": "horizontal",
        "accepted_token": None,
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 50.0,
                        "span_px": [10, 190],
                    }
                ],
            },
            {"witness_index": 1, "source_lines": [shared_left]},
            {"witness_index": 2, "source_lines": [shared_right]},
        ],
    }
    report = {
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [
                {"candidate_id": "DG_LOCAL", "token": "24"}
            ],
        }
    }
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        )
    }

    unresolved = hybrid_adapter._coverage_unresolved(
        report,
        {
            "DG_ACCEPTED": accepted,
            "DG_LOCAL": local_only,
        },
        view_lookup,
        boundaries=[],
        overall_dimension_facts=[],
    )

    item = next(entry for entry in unresolved if entry.field == "local_only_linear_text")
    assert item.required_for_modeling is False
    assert "advisory duplicate coverage" in item.reason


def test_equal_local_only_value_without_shared_witness_topology_stays_blocking():
    accepted = {
        "candidate_id": "DG_ACCEPTED",
        "region_id": "R1",
        "orientation": "horizontal",
        "accepted_token": "24",
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 100.0,
                        "span_px": [20, 180],
                    }
                ],
            },
            {
                "witness_index": 1,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 200.0,
                        "span_px": [20, 180],
                    }
                ],
            },
        ],
    }
    local_only = {
        "candidate_id": "DG_LOCAL",
        "region_id": "R1",
        "orientation": "horizontal",
        "accepted_token": None,
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 300.0,
                        "span_px": [20, 180],
                    }
                ],
            },
            {
                "witness_index": 1,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 400.0,
                        "span_px": [20, 180],
                    }
                ],
            },
        ],
    }
    report = {
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [
                {"candidate_id": "DG_LOCAL", "token": "24"}
            ],
        }
    }
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        )
    }

    unresolved = hybrid_adapter._coverage_unresolved(
        report,
        {
            "DG_ACCEPTED": accepted,
            "DG_LOCAL": local_only,
        },
        view_lookup,
        boundaries=[],
        overall_dimension_facts=[],
    )

    item = next(entry for entry in unresolved if entry.field == "local_only_linear_text")
    assert item.required_for_modeling is True

def test_off_region_callout_can_bind_one_unique_linear_pattern(monkeypatch):
    report = {
        "coverage": {
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 11,
                    "text": "2-06.6通孔",
                    "bbox": [[120, 40], [180, 40], [180, 70], [120, 70]],
                    "confidence": 0.99,
                }
            ]
        },
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 100, 100],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            },
            {
                "region_id": "R2",
                "bbox_px": [200, 0, 100, 100],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            },
        ],
        "annotation_line_candidates": [],
    }
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        ),
        "R2": hybrid_adapter.HybridRegionView(
            region_id="R2",
            view_kind="side",
            evidence=["test:R2"],
        ),
    }

    monkeypatch.setattr(
        hybrid_adapter,
        "bind_callout_to_circle_entity",
        lambda *args, **kwargs: {"status": "unresolved"},
    )

    def fake_pattern_binding(*args, **kwargs):
        region = args[2]
        if region["region_id"] == "R2":
            return {
                "status": "bound",
                "entity_key": "R2.LINEAR_PATTERN.003",
                "region_id": "R2",
                "pattern_index": 2,
                "orientation": "horizontal",
                "axis": "Y",
            }
        return {"status": "unresolved"}

    monkeypatch.setattr(
        hybrid_adapter,
        "bind_callout_to_linear_pattern",
        fake_pattern_binding,
    )

    ledger, entities, values, unresolved = hybrid_adapter._engineering_callout_routing(
        report,
        [],
        view_lookup,
        hidden_pattern_owner_by_index={},
        existing_entity_keys=set(),
    )

    assert ledger[0]["region_candidates"] == []
    assert ledger[0]["binding"]["status"] == "pattern_backed"
    assert ledger[0]["binding"]["region_id"] == "R2"
    assert not any(
        item.field == "engineering_callout_geometry_binding"
        and item.required_for_modeling
        for item in unresolved
    )
    assert {
        (item.field, item.value)
        for item in values
        if item.entity_key == "R2.LINEAR_PATTERN.003"
    } >= {
        ("count", 2),
        ("through", True),
        ("diameter", 6.6),
    }


def test_off_region_callout_with_multiple_pattern_targets_stays_unresolved(monkeypatch):
    report = {
        "coverage": {
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 11,
                    "text": "2-06.6通孔",
                    "bbox": [[120, 40], [180, 40], [180, 70], [120, 70]],
                    "confidence": 0.99,
                }
            ]
        },
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 100, 100],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            },
            {
                "region_id": "R2",
                "bbox_px": [200, 0, 100, 100],
                "circle_groups": [],
                "linear_pattern_candidates": [],
            },
        ],
        "annotation_line_candidates": [],
    }
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        ),
        "R2": hybrid_adapter.HybridRegionView(
            region_id="R2",
            view_kind="side",
            evidence=["test:R2"],
        ),
    }

    monkeypatch.setattr(
        hybrid_adapter,
        "bind_callout_to_circle_entity",
        lambda *args, **kwargs: {"status": "unresolved"},
    )

    def fake_pattern_binding(*args, **kwargs):
        region = args[2]
        region_id = region["region_id"]
        return {
            "status": "bound",
            "entity_key": f"{region_id}.LINEAR_PATTERN.003",
            "region_id": region_id,
            "pattern_index": 2,
            "orientation": "horizontal",
            "axis": "X" if region_id == "R1" else "Y",
        }

    monkeypatch.setattr(
        hybrid_adapter,
        "bind_callout_to_linear_pattern",
        fake_pattern_binding,
    )

    ledger, _entities, _values, unresolved = hybrid_adapter._engineering_callout_routing(
        report,
        [],
        view_lookup,
        hidden_pattern_owner_by_index={},
        existing_entity_keys=set(),
    )

    assert ledger[0]["binding"]["status"] == "unresolved"
    assert (
        ledger[0]["binding"]["reason"]
        == "multiple_callout_linear_pattern_regions_without_unique_target"
    )
    blockers = [
        item
        for item in unresolved
        if item.required_for_modeling
        and item.field == "engineering_callout_geometry_binding"
    ]
    assert len(blockers) == 1

def test_full_extent_roles_reject_mismatched_local_dimension_value():
    endpoints = [
        hybrid_adapter.ObservationDimensionEndpoint(
            role="overall_min",
            evidence=["test"],
        ),
        hybrid_adapter.ObservationDimensionEndpoint(
            role="overall_max",
            evidence=["test"],
        ),
    ]

    assert hybrid_adapter._full_extent_roles_disagree_with_declared_overall(
        endpoints,
        axis="Z",
        value=4.5,
        overall_dimensions={
            "length_x": 300.0,
            "width_y": 300.0,
            "height_z": 75.0,
        },
    )
    assert not hybrid_adapter._full_extent_roles_disagree_with_declared_overall(
        endpoints,
        axis="Z",
        value=75.0,
        overall_dimensions={
            "length_x": 300.0,
            "width_y": 300.0,
            "height_z": 75.0,
        },
    )


def test_callout_owned_linear_pattern_overrides_overlapping_profile_endpoint():
    candidate = {
        "candidate_id": "DG_CENTER",
        "region_id": "R2",
        "orientation": "horizontal",
        "accepted_token": "24",
        "global_assignments": [
            {
                "token": "24",
                "bbox": [[40, 20], [60, 20], [60, 40], [40, 40]],
            }
        ],
        "witness_positions_px": [10.0, 90.0],
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "position_px": 10.0,
                "nearest_anchors": [
                    {
                        "kind": "linear_pattern_axis",
                        "ref": "R2.linear_pattern.005",
                        "position_px": 10.5,
                    },
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.002",
                        "position_px": 10.4,
                    },
                ],
            },
            {
                "witness_index": 1,
                "position_px": 90.0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.004",
                        "position_px": 90.0,
                    }
                ],
            },
        ],
    }

    endpoints, reason = hybrid_adapter._dimension_endpoints_from_candidates(
        candidate,
        entity_keys={"R2.LINEAR_PATTERN.005", "R2.PROFILE_BOUNDARY.OUTER"},
        boundary_roles={"R2.structural.vertical.004": "overall_max"},
        profile_entity_by_ref={
            "R2.structural.vertical.002": "R2.PROFILE_BOUNDARY.INNER",
            "R2.structural.vertical.004": "R2.PROFILE_BOUNDARY.OUTER",
        },
        pattern_entity_by_ref={
            "R2.linear_pattern.005": "R2.LINEAR_PATTERN.005",
        },
        evidence=["test:DG_CENTER"],
    )

    assert reason is None
    assert endpoints[0].role == "entity_center"
    assert endpoints[0].entity_key == "R2.LINEAR_PATTERN.005"
    assert endpoints[0].basis == "centerline"
    assert endpoints[1].role == "overall_max"

def test_unqualified_profile_candidate_does_not_suppress_valid_center_candidate(
    monkeypatch,
):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_dimension_endpoint_candidates",
        lambda candidate: {
            "endpoints": [
                {
                    "status": "ambiguous_physical_candidates",
                    "physical_candidates": [
                        {
                            "kind": "hidden_projection_center_axis",
                            "entity_key": "R1.HIDDEN_PAIR.horizontal.001.002",
                            "ref": "R1.HIDDEN_PAIR.horizontal.001.002.center",
                        },
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.centerlike.001",
                        },
                    ],
                },
                {
                    "status": "unique_physical_candidate",
                    "physical_candidates": [
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.outer.max",
                        }
                    ],
                },
            ]
        },
    )

    endpoints, reason = hybrid_adapter._dimension_endpoints_from_candidates(
        {"candidate_id": "DG_CENTER_WITH_WEAK_PROFILE"},
        entity_keys={
            "R1.HIDDEN_PAIR.horizontal.001.002",
            "R1.PROFILE_BOUNDARY.CENTERLIKE",
            "R1.PROFILE_BOUNDARY.OUTER_MAX",
        },
        boundary_roles={"R1.outer.max": "overall_max"},
        profile_entity_by_ref={
            "R1.centerlike.001": "R1.PROFILE_BOUNDARY.CENTERLIKE",
            "R1.outer.max": "R1.PROFILE_BOUNDARY.OUTER_MAX",
        },
        evidence=["test:center-with-weak-profile"],
    )

    assert reason is not None
    assert endpoints[0].role == "unresolved"
    assert endpoints[0].unresolved_kind == "ambiguous_owner"
    assert endpoints[0].candidate_entity_keys == [
        "R1.HIDDEN_PAIR.horizontal.001.002"
    ]
    assert endpoints[1].role == "overall_max"


def test_ambiguous_internal_profile_candidates_are_preserved_for_confirmation(
    monkeypatch,
):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_dimension_endpoint_candidates",
        lambda candidate: {
            "endpoints": [
                {
                    "status": "ambiguous_physical_candidates",
                    "physical_candidates": [
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.internal.001",
                            "span_local_norm": 0.3,
                            "junction_count": 2,
                            "endpoint_junction_count": 1,
                        },
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.internal.002",
                            "span_local_norm": 0.3,
                            "junction_count": 2,
                            "endpoint_junction_count": 1,
                        },
                    ],
                },
                {
                    "status": "unique_physical_candidate",
                    "physical_candidates": [
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.outer.max",
                        }
                    ],
                },
            ]
        },
    )

    endpoints, reason = hybrid_adapter._dimension_endpoints_from_candidates(
        {"candidate_id": "DG_PROFILE_AMBIG"},
        entity_keys={
            "R1.PROFILE_BOUNDARY.INTERNAL_1",
            "R1.PROFILE_BOUNDARY.INTERNAL_2",
            "R1.PROFILE_BOUNDARY.OUTER_MAX",
        },
        boundary_roles={"R1.outer.max": "overall_max"},
        profile_entity_by_ref={
            "R1.internal.001": "R1.PROFILE_BOUNDARY.INTERNAL_1",
            "R1.internal.002": "R1.PROFILE_BOUNDARY.INTERNAL_2",
            "R1.outer.max": "R1.PROFILE_BOUNDARY.OUTER_MAX",
        },
        evidence=["test:profile-ambiguity"],
    )

    assert reason is not None
    assert endpoints[0].role == "unresolved"
    assert endpoints[0].unresolved_kind == "ambiguous_owner"
    assert endpoints[0].candidate_entity_keys == [
        "R1.PROFILE_BOUNDARY.INTERNAL_1",
        "R1.PROFILE_BOUNDARY.INTERNAL_2",
    ]
    assert endpoints[1].role == "overall_max"


def test_ambiguous_profile_candidates_with_overall_boundary_stay_unconfirmable(
    monkeypatch,
):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_dimension_endpoint_candidates",
        lambda candidate: {
            "endpoints": [
                {
                    "status": "ambiguous_physical_candidates",
                    "physical_candidates": [
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.internal.001",
                            "span_local_norm": 0.3,
                            "junction_count": 2,
                            "endpoint_junction_count": 1,
                        },
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.outer.min",
                        },
                    ],
                },
                {
                    "status": "unique_physical_candidate",
                    "physical_candidates": [
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "R1.outer.max",
                        }
                    ],
                },
            ]
        },
    )

    endpoints, _ = hybrid_adapter._dimension_endpoints_from_candidates(
        {"candidate_id": "DG_PROFILE_OVERALL_AMBIG"},
        entity_keys={
            "R1.PROFILE_BOUNDARY.INTERNAL_1",
            "R1.PROFILE_BOUNDARY.OUTER_MIN",
            "R1.PROFILE_BOUNDARY.OUTER_MAX",
        },
        boundary_roles={
            "R1.outer.min": "overall_min",
            "R1.outer.max": "overall_max",
        },
        profile_entity_by_ref={
            "R1.internal.001": "R1.PROFILE_BOUNDARY.INTERNAL_1",
            "R1.outer.min": "R1.PROFILE_BOUNDARY.OUTER_MIN",
            "R1.outer.max": "R1.PROFILE_BOUNDARY.OUTER_MAX",
        },
        evidence=["test:profile-overall-ambiguity"],
    )

    assert endpoints[0].role == "unresolved"
    assert endpoints[0].candidate_entity_keys == []
    assert endpoints[0].unresolved_kind == "intermediate_surface"


def test_exact_crossing_duplicate_region_profile_refs_collapse_to_one_source_line():
    candidate = {
        "candidate_id": "DG_DUPLICATE_PROFILE",
        "region_id": "R2",
        "orientation": "horizontal",
        "accepted_token": "24",
        "global_assignments": [
            {
                "token": "24",
                "bbox": [[40, 20], [60, 20], [60, 40], [40, 40]],
            }
        ],
        "witness_positions_px": [10.0, 90.0],
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "position_px": 10.0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.001",
                        "position_px": 10.0,
                        "source_orientation": "vertical",
                        "span_px": [0.0, 100.0],
                    },
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R3.structural.vertical.004",
                        "position_px": 10.0,
                        "source_orientation": "vertical",
                        "span_px": [0.0, 100.0],
                    },
                ],
            },
            {
                "witness_index": 1,
                "position_px": 90.0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.009",
                        "position_px": 90.0,
                        "source_orientation": "vertical",
                        "span_px": [0.0, 100.0],
                    }
                ],
            },
        ],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 10.0,
                        "span_px": [0.0, 100.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            },
            {
                "witness_index": 1,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 90.0,
                        "span_px": [0.0, 100.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            },
        ],
    }

    evidence = hybrid_adapter.derive_dimension_endpoint_candidates(candidate)

    assert evidence["endpoints"][0]["status"] == "unique_physical_candidate"
    assert evidence["endpoints"][0]["ownership_narrowing_basis"] == (
        "exact_crossing_witness_profile_line_identity"
    )
    assert [
        item["ref"] for item in evidence["endpoints"][0]["physical_candidates"]
    ] == ["R2.structural.vertical.001"]


def test_exact_crossing_distinct_profile_source_lines_remain_ambiguous():
    candidate = {
        "candidate_id": "DG_DISTINCT_PROFILE",
        "region_id": "R2",
        "orientation": "horizontal",
        "accepted_token": "24",
        "global_assignments": [
            {
                "token": "24",
                "bbox": [[40, 20], [60, 20], [60, 40], [40, 40]],
            }
        ],
        "witness_positions_px": [10.0, 90.0],
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "position_px": 10.0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.001",
                        "position_px": 10.0,
                        "source_orientation": "vertical",
                        "span_px": [0.0, 100.0],
                    },
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R3.structural.vertical.004",
                        "position_px": 10.0,
                        "source_orientation": "vertical",
                        "span_px": [10.0, 90.0],
                    },
                ],
            },
            {
                "witness_index": 1,
                "position_px": 90.0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.009",
                        "position_px": 90.0,
                        "source_orientation": "vertical",
                        "span_px": [0.0, 100.0],
                    }
                ],
            },
        ],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 10.0,
                        "span_px": [0.0, 100.0],
                        "crosses_dimension_axis": True,
                    },
                    {
                        "orientation": "vertical",
                        "axis_px": 10.0,
                        "span_px": [10.0, 90.0],
                        "crosses_dimension_axis": True,
                    },
                ],
            },
            {
                "witness_index": 1,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 90.0,
                        "span_px": [0.0, 100.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            },
        ],
    }

    evidence = hybrid_adapter.derive_dimension_endpoint_candidates(candidate)

    assert evidence["endpoints"][0]["status"] == "ambiguous_physical_candidates"
    assert len(evidence["endpoints"][0]["physical_candidates"]) == 2


def test_exact_crossing_profile_identity_supersedes_overlapping_callout_pattern_axis():
    candidate = {
        "candidate_id": "DG_PROFILE",
        "region_id": "R2",
        "orientation": "horizontal",
        "accepted_token": "24",
        "global_assignments": [
            {
                "token": "24",
                "bbox": [[40, 20], [60, 20], [60, 40], [40, 40]],
            }
        ],
        "witness_positions_px": [10.0, 90.0],
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "position_px": 10.0,
                "nearest_anchors": [
                    {
                        "kind": "linear_pattern_axis",
                        "ref": "R2.linear_pattern.005",
                        "position_px": 10.5,
                    },
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.002",
                        "position_px": 10.4,
                        "source_orientation": "vertical",
                        "span_px": [0.0, 100.0],
                    },
                ],
            },
            {
                "witness_index": 1,
                "position_px": 90.0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.004",
                        "position_px": 90.0,
                    }
                ],
            },
        ],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 10.4,
                        "span_px": [0.0, 100.0],
                        "crosses_dimension_axis": True,
                    }
                ],
            }
        ],
    }

    endpoints, reason = hybrid_adapter._dimension_endpoints_from_candidates(
        candidate,
        entity_keys={"R2.LINEAR_PATTERN.005", "R2.PROFILE_BOUNDARY.INNER"},
        boundary_roles={"R2.structural.vertical.004": "overall_max"},
        profile_entity_by_ref={
            "R2.structural.vertical.002": "R2.PROFILE_BOUNDARY.INNER",
            "R2.structural.vertical.004": "R2.PROFILE_BOUNDARY.OUTER",
        },
        pattern_entity_by_ref={
            "R2.linear_pattern.005": "R2.LINEAR_PATTERN.005",
        },
        evidence=["test:DG_PROFILE"],
    )

    assert reason is None
    assert endpoints[0].role == "profile_boundary"
    assert endpoints[0].entity_key == "R2.PROFILE_BOUNDARY.INNER"
    assert endpoints[0].basis == "profile_edge"
    assert endpoints[1].role == "overall_max"


def test_adapter_does_not_grant_annotation_region_global_boundary_roles():
    context = HybridAdapterContext(
        region_views=[
            hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["structural:R1:context"],
            ),
            hybrid_adapter.HybridRegionView(
                region_id="R3",
                view_kind="front",
                evidence=["structural:R3:context"],
            ),
        ],
        overall_dimension_facts=[
            hybrid_adapter.PartialOverallDimensionFact(
                axis="X",
                value=300,
                evidence=["structural:R1:context"],
            ),
            hybrid_adapter.PartialOverallDimensionFact(
                axis="Z",
                value=75,
                evidence=["structural:R1:context"],
            ),
        ],
    )

    region_axes = hybrid_adapter._region_overall_fact_axes(context)

    assert region_axes == {("R1", "X"), ("R1", "Z")}
    assert ("R3", "X") not in region_axes
    assert ("R3", "Z") not in region_axes


def test_unscoped_overall_fact_binds_when_only_one_region_can_own_axis():
    context = hybrid_adapter.HybridAdapterContext(
        region_views=[
            hybrid_adapter.HybridRegionView(
                region_id="R2",
                view_kind="side",
                evidence=["test:R2"],
            )
        ],
        overall_dimension_facts=[
            hybrid_adapter.PartialOverallDimensionFact(
                axis="Y",
                value=32,
                evidence=["test:overall-y"],
            )
        ],
    )

    assert hybrid_adapter._region_overall_fact_axes(context) == {("R2", "Y")}


def _cross_region_variant(
    *,
    candidate_id: str,
    region_id: str,
    first_anchor: dict[str, object],
    second_anchor: dict[str, object],
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "region_id": region_id,
        "orientation": "horizontal",
        "axis_px": 100.0,
        "line_span_px": [100.0, 200.0],
        "witness_positions_px": [100.0, 200.0],
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "position_px": 100.0,
                "axis": "x",
                "nearest_anchors": [first_anchor],
            },
            {
                "witness_index": 1,
                "position_px": 200.0,
                "axis": "x",
                "nearest_anchors": [second_anchor],
            },
        ],
        "witness_line_evidence": [],
    }


def _accepted_cross_region_group(
    canonical: dict[str, object],
    alternate: dict[str, object],
) -> dict[str, object]:
    return {
        **canonical,
        "accepted_token": "40",
        "global_assignments": [
            {
                "token": "40",
                "bbox": [[140, 90], [160, 90], [160, 110], [140, 110]],
            }
        ],
        "source_candidate_ids": [
            str(canonical["candidate_id"]),
            str(alternate["candidate_id"]),
        ],
        "source_region_ids": [
            str(canonical["region_id"]),
            str(alternate["region_id"]),
        ],
        "source_candidate_variants": [canonical, alternate],
    }


def test_cross_region_variant_selection_uses_strict_endpoint_evidence_dominance():
    weak = _cross_region_variant(
        candidate_id="DG1",
        region_id="R1",
        first_anchor={"kind": "linear_pattern_axis", "ref": "R1.pattern.001"},
        second_anchor={"kind": "profile_edge_candidate", "ref": "R1.profile.right"},
    )
    strong = _cross_region_variant(
        candidate_id="DG2",
        region_id="R2",
        first_anchor={"kind": "profile_edge_candidate", "ref": "R2.profile.left"},
        second_anchor={"kind": "profile_edge_candidate", "ref": "R2.profile.right"},
    )

    selected = hybrid_adapter._select_cross_region_candidate_variant(
        _accepted_cross_region_group(weak, strong)
    )

    assert selected["candidate_id"] == "DG1"
    assert selected["region_id"] == "R2"
    assert selected["selected_source_candidate_id"] == "DG2"
    assert (
        selected["cross_region_variant_selection_basis"]
        == "strict_selected_endpoint_evidence_dominance"
    )


def test_cross_region_variant_selection_fails_closed_on_crossed_advantages():
    first_strong = _cross_region_variant(
        candidate_id="DG1",
        region_id="R1",
        first_anchor={"kind": "profile_edge_candidate", "ref": "R1.profile.left"},
        second_anchor={"kind": "linear_pattern_axis", "ref": "R1.pattern.002"},
    )
    second_strong = _cross_region_variant(
        candidate_id="DG2",
        region_id="R2",
        first_anchor={"kind": "linear_pattern_axis", "ref": "R2.pattern.001"},
        second_anchor={"kind": "profile_edge_candidate", "ref": "R2.profile.right"},
    )

    selected = hybrid_adapter._select_cross_region_candidate_variant(
        _accepted_cross_region_group(first_strong, second_strong)
    )

    assert selected["region_id"] == "R1"
    assert "selected_source_candidate_id" not in selected


def test_cross_region_variant_selection_preserves_selected_region_boundary_roles():
    weak = _cross_region_variant(
        candidate_id="DG1",
        region_id="R1",
        first_anchor={"kind": "linear_pattern_axis", "ref": "R1.pattern.001"},
        second_anchor={"kind": "profile_edge_candidate", "ref": "R1.profile.right"},
    )
    strong = _cross_region_variant(
        candidate_id="DG2",
        region_id="R2",
        first_anchor={"kind": "profile_edge_candidate", "ref": "R2.profile.left"},
        second_anchor={"kind": "profile_edge_candidate", "ref": "R2.profile.right"},
    )
    selected = hybrid_adapter._select_cross_region_candidate_variant(
        _accepted_cross_region_group(weak, strong)
    )

    endpoints, unresolved = hybrid_adapter._dimension_endpoints_from_candidates(
        selected,
        entity_keys={
            "R2.PROFILE_BOUNDARY.LEFT",
            "R2.PROFILE_BOUNDARY.RIGHT",
        },
        boundary_roles={
            "R2.profile.left": "overall_min",
            "R2.profile.right": "overall_max",
        },
        profile_entity_by_ref={
            "R2.profile.left": "R2.PROFILE_BOUNDARY.LEFT",
            "R2.profile.right": "R2.PROFILE_BOUNDARY.RIGHT",
        },
        evidence=["test:cross-region"],
    )

    assert unresolved is None
    assert {item.role for item in endpoints} == {"overall_min", "overall_max"}
    assert hybrid_adapter._full_extent_roles_disagree_with_declared_overall(
        endpoints,
        axis="X",
        value=40.0,
        overall_dimensions={"length_x": 100.0},
    ) is True


def test_centered_symmetric_pair_rejects_mixed_local_overall_endpoint_role():
    candidate = _cross_region_variant(
        candidate_id="DG_SPAN",
        region_id="R2",
        first_anchor={
            "kind": "profile_edge_candidate",
            "ref": "R2.profile.left",
        },
        second_anchor={
            "kind": "profile_edge_candidate",
            "ref": "R2.profile.right",
        },
    )
    candidate["accepted_token"] = "40"
    candidate["global_assignments"] = [
        {
            "token": "40",
            "bbox": [[140, 90], [160, 90], [160, 110], [140, 110]],
        }
    ]
    entity_keys = {
        "R2.PROFILE_BOUNDARY.LEFT",
        "R2.PROFILE_BOUNDARY.RIGHT",
    }
    profile_entity_by_ref = {
        "R2.profile.left": "R2.PROFILE_BOUNDARY.LEFT",
        "R2.profile.right": "R2.PROFILE_BOUNDARY.RIGHT",
    }

    endpoints, unresolved = hybrid_adapter._dimension_endpoints_from_candidates(
        candidate,
        entity_keys=entity_keys,
        boundary_roles={"R2.profile.right": "overall_max"},
        profile_entity_by_ref=profile_entity_by_ref,
        evidence=["test:centered-span"],
    )
    assert unresolved is None
    assert [item.role for item in endpoints] == [
        "profile_boundary",
        "overall_max",
    ]

    endpoints, unresolved = (
        hybrid_adapter._reconcile_centered_symmetric_dimension_endpoint_roles(
            candidate,
            endpoints=endpoints,
            unresolved_reason=unresolved,
            symmetric_dimension_pair={
                "datum": "overall_center",
                "dimension_value": 40.0,
                "overall_dimension_value": 100.0,
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            },
            entity_keys=entity_keys,
            profile_entity_by_ref=profile_entity_by_ref,
            profile_vertex_entity_by_ref=None,
            pattern_entity_by_ref=None,
            evidence=["test:centered-span"],
        )
    )

    assert unresolved is None
    assert [item.role for item in endpoints] == [
        "profile_boundary",
        "profile_boundary",
    ]
    assert [item.entity_key for item in endpoints] == [
        "R2.PROFILE_BOUNDARY.LEFT",
        "R2.PROFILE_BOUNDARY.RIGHT",
    ]


def test_non_symmetric_dimension_keeps_valid_profile_to_overall_offset():
    candidate = _cross_region_variant(
        candidate_id="DG_OFFSET",
        region_id="R2",
        first_anchor={
            "kind": "profile_edge_candidate",
            "ref": "R2.profile.left",
        },
        second_anchor={
            "kind": "profile_edge_candidate",
            "ref": "R2.profile.right",
        },
    )
    candidate["accepted_token"] = "40"
    candidate["global_assignments"] = [
        {
            "token": "40",
            "bbox": [[140, 90], [160, 90], [160, 110], [140, 110]],
        }
    ]
    entity_keys = {
        "R2.PROFILE_BOUNDARY.LEFT",
        "R2.PROFILE_BOUNDARY.RIGHT",
    }
    profile_entity_by_ref = {
        "R2.profile.left": "R2.PROFILE_BOUNDARY.LEFT",
        "R2.profile.right": "R2.PROFILE_BOUNDARY.RIGHT",
    }
    endpoints, unresolved = hybrid_adapter._dimension_endpoints_from_candidates(
        candidate,
        entity_keys=entity_keys,
        boundary_roles={"R2.profile.right": "overall_max"},
        profile_entity_by_ref=profile_entity_by_ref,
        evidence=["test:ordinary-offset"],
    )

    reconciled, reconciled_unresolved = (
        hybrid_adapter._reconcile_centered_symmetric_dimension_endpoint_roles(
            candidate,
            endpoints=endpoints,
            unresolved_reason=unresolved,
            symmetric_dimension_pair=None,
            entity_keys=entity_keys,
            profile_entity_by_ref=profile_entity_by_ref,
            profile_vertex_entity_by_ref=None,
            pattern_entity_by_ref=None,
            evidence=["test:ordinary-offset"],
        )
    )

    assert reconciled_unresolved is None
    assert [item.role for item in reconciled] == [
        "profile_boundary",
        "overall_max",
    ]


def test_symmetric_count_two_pattern_owner_uses_pixels_only_for_identity():
    candidate = {
        "candidate_id": "DG_PAIR",
        "region_id": "R1",
        "orientation": "horizontal",
        "accepted_token": "24",
        "global_assignments": [
            {
                "token": "24",
                "bbox": [[45, 20], [55, 20], [55, 40], [45, 40]],
            }
        ],
        "witness_positions_px": [10.0, 90.0],
        "witness_anchor_evidence": [
            {"witness_index": 0, "position_px": 10.0, "nearest_anchors": []},
            {"witness_index": 1, "position_px": 90.0, "nearest_anchors": []},
        ],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "position_px": 10.0,
                "source_lines": [
                    {"orientation": "vertical", "axis_px": 10.0, "span_px": [50, 100]}
                ],
            },
            {
                "witness_index": 1,
                "position_px": 90.0,
                "source_lines": [
                    {"orientation": "vertical", "axis_px": 90.0, "span_px": [50, 100]}
                ],
            },
        ],
    }
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R1",
            "axis": "X",
            "overall_dimension_value": 40.0,
            "anchors": [
                {"role": "overall_min", "position_px": 0.0},
                {"role": "overall_max", "position_px": 100.0},
            ],
            "engineering_coordinate_inferred_from_pixels": False,
        }
    ]
    callout_ledger = [
        {
            "binding": {
                "status": "pattern_backed",
                "entity_key": "R2.PAIR",
                "axis": "Z",
                "pattern_span_px": [50, 100],
            },
            "facts": {"count": 2, "diameter": 6.6, "through": True},
        }
    ]

    result = hybrid_adapter._symmetric_count_two_pattern_owner(
        candidate,
        region_view=hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        ),
        axis="X",
        boundaries=boundaries,
        callout_ledger=callout_ledger,
        entity_keys={"R2.PAIR"},
    )

    assert result is not None
    assert result["entity_key"] == "R2.PAIR"
    assert result["engineering_coordinate_inferred_from_pixels"] is False
    assert result["pixel_geometry_used_for_identity_only"] is True
    assert result["spacing_dimension_value"] == 24.0
    assert result["projection_support"]["overlap_ratios"] == [1.0, 1.0]


def test_symmetric_count_two_pattern_owner_rejects_visually_off_center_pair():
    candidate = {
        "candidate_id": "DG_PAIR",
        "region_id": "R1",
        "orientation": "horizontal",
        "accepted_token": "24",
        "global_assignments": [
            {
                "token": "24",
                "bbox": [[45, 20], [55, 20], [55, 40], [45, 40]],
            }
        ],
        "witness_positions_px": [10.0, 70.0],
        "witness_anchor_evidence": [
            {"witness_index": 0, "position_px": 10.0, "nearest_anchors": []},
            {"witness_index": 1, "position_px": 70.0, "nearest_anchors": []},
        ],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "position_px": 10.0,
                "source_lines": [
                    {"orientation": "vertical", "axis_px": 10.0, "span_px": [50, 100]}
                ],
            },
            {
                "witness_index": 1,
                "position_px": 70.0,
                "source_lines": [
                    {"orientation": "vertical", "axis_px": 70.0, "span_px": [50, 100]}
                ],
            },
        ],
    }

    result = hybrid_adapter._symmetric_count_two_pattern_owner(
        candidate,
        region_view=hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        ),
        axis="X",
        boundaries=[
            {
                "status": "resolved",
                "region_id": "R1",
                "axis": "X",
                "overall_dimension_value": 40.0,
                "anchors": [
                    {"role": "overall_min", "position_px": 0.0},
                    {"role": "overall_max", "position_px": 100.0},
                ],
                "engineering_coordinate_inferred_from_pixels": False,
            }
        ],
        callout_ledger=[
            {
                "binding": {
                    "status": "pattern_backed",
                    "entity_key": "R2.PAIR",
                    "axis": "Z",
                },
                "facts": {"count": 2},
            }
        ],
        entity_keys={"R2.PAIR"},
    )

    assert result is None

def test_symmetric_count_two_pattern_owner_rejects_disjoint_projection_span():
    candidate = {
        "candidate_id": "DG_PAIR",
        "region_id": "R1",
        "orientation": "horizontal",
        "accepted_token": "24",
        "global_assignments": [
            {
                "token": "24",
                "bbox": [[45, 20], [55, 20], [55, 40], [45, 40]],
            }
        ],
        "witness_positions_px": [10.0, 90.0],
        "witness_anchor_evidence": [
            {"witness_index": 0, "position_px": 10.0, "nearest_anchors": []},
            {"witness_index": 1, "position_px": 90.0, "nearest_anchors": []},
        ],
        "witness_line_evidence": [
            {
                "witness_index": 0,
                "position_px": 10.0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 10.0,
                        "span_px": [50, 100],
                        "crosses_dimension_axis": False,
                    }
                ],
            },
            {
                "witness_index": 1,
                "position_px": 90.0,
                "source_lines": [
                    {
                        "orientation": "vertical",
                        "axis_px": 90.0,
                        "span_px": [50, 100],
                        "crosses_dimension_axis": False,
                    }
                ],
            },
        ],
    }

    result = hybrid_adapter._symmetric_count_two_pattern_owner(
        candidate,
        region_view=hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        ),
        axis="X",
        boundaries=[
            {
                "status": "resolved",
                "region_id": "R1",
                "axis": "X",
                "overall_dimension_value": 40.0,
                "anchors": [
                    {"role": "overall_min", "position_px": 0.0},
                    {"role": "overall_max", "position_px": 100.0},
                ],
                "engineering_coordinate_inferred_from_pixels": False,
            }
        ],
        callout_ledger=[
            {
                "binding": {
                    "status": "pattern_backed",
                    "entity_key": "R2.UNRELATED_PAIR",
                    "axis": "Z",
                    "pattern_span_px": [180, 240],
                },
                "facts": {"count": 2, "diameter": 6.6, "through": True},
            }
        ],
        entity_keys={"R2.UNRELATED_PAIR"},
    )

    assert result is None

def test_unique_thread_recess_centerline_alignment_uses_pixels_only_for_identity():
    alignments, ledger = hybrid_adapter._unique_thread_recess_centerline_alignments(
        report={
            "regions": [
                {
                    "region_id": "R1",
                    "bbox_px": [0, 0, 200, 300],
                    "circle_groups": [],
                },
                {
                    "region_id": "R2",
                    "bbox_px": [200, 0, 200, 300],
                    "circle_groups": [
                        {
                            "circle_group_id": "C1",
                            "center_px": [300.0, 101.0],
                            "rings": [{"radius_px": 20}],
                        }
                    ],
                },
            ]
        },
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["R1"],
            ),
            "R2": hybrid_adapter.HybridRegionView(
                region_id="R2",
                view_kind="side",
                evidence=["R2"],
            ),
        },
        hidden_entity_records={
            "R1.HIDDEN_PAIR.horizontal.001.002": {
                "entity_key": "R1.HIDDEN_PAIR.horizontal.001.002",
                "feature_axis": "X",
                "pattern_orientation": "horizontal",
                "position_px": 100.0,
            }
        },
        callout_values=[
            hybrid_adapter.ObservationValue(
                entity_key="R1.HIDDEN_PAIR.horizontal.001.002",
                field="thread_spec",
                value="M6",
                evidence=["thread"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key="R2.C1",
                field="recessed_hole",
                value=True,
                evidence=["recess"],
            ),
        ],
        entity_keys={
            "R1.HIDDEN_PAIR.horizontal.001.002",
            "R2.C1",
        },
    )

    assert len(alignments) == 1
    assert alignments[0].entity_keys == [
        "R1.HIDDEN_PAIR.horizontal.001.002",
        "R2.C1",
    ]
    assert alignments[0].feature_axis == "X"
    assert ledger[0]["projection_residual_px"] == 1.0
    assert ledger[0]["engineering_coordinate_inferred_from_pixels"] is False
    assert ledger[0]["pixel_geometry_used_for_identity_only"] is True


def test_transverse_recess_start_side_uses_unique_boundary_contact():
    hidden = "R1.HIDDEN_PAIR.horizontal.001.002"
    target = "R2.C1"
    values, ledger = hybrid_adapter._transverse_recess_start_side_values(
        report={
            "regions": [
                {
                    "region_id": "R1",
                    "bbox_px": [0, 0, 120, 100],
                    "linear_pattern_candidates": [
                        {
                            "orientation": "horizontal",
                            "axis_px": 50.5,
                            "segments_px": [
                                [20, 40],
                                [92, 98],
                                [102, 115],
                            ],
                        }
                    ],
                }
            ]
        },
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["R1"],
            )
        },
        boundaries=[
            {
                "status": "resolved",
                "region_id": "R1",
                "axis": "X",
                "anchors": [
                    {
                        "ref": "R1.LEFT",
                        "role": "overall_min",
                        "position_px": 0.0,
                    },
                    {
                        "ref": "R1.RIGHT",
                        "role": "overall_max",
                        "position_px": 100.0,
                    },
                ],
            }
        ],
        hidden_entity_records={
            hidden: {
                "entity_key": hidden,
                "feature_axis": "X",
                "pattern_orientation": "horizontal",
                "position_px": 50.0,
            }
        },
        callout_values=[
            hybrid_adapter.ObservationValue(
                entity_key=hidden,
                field="thread_spec",
                value="M6",
                evidence=["thread"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key=target,
                field="recessed_hole",
                value=True,
                evidence=["recess"],
            ),
        ],
        centerline_alignments=[
            hybrid_adapter.ObservationCenterlineAlignment(
                entity_keys=[hidden, target],
                feature_axis="X",
                evidence=["centerline"],
            )
        ],
    )

    assert len(values) == 1
    assert values[0].entity_key == target
    assert values[0].field == "start_side"
    assert values[0].value == "max"
    assert values[0].semantic == "start_side"
    assert ledger[0]["start_side"] == "max"
    assert ledger[0]["boundary_role"] == "overall_max"
    assert ledger[0]["engineering_coordinate_inferred_from_pixels"] is False
    assert ledger[0]["pixel_geometry_used_for_topology_only"] is True


def test_coaxial_recess_does_not_infer_thread_material_or_entry_side():
    thread = "R1.HIDDEN_PAIR.horizontal.001.002"
    values = [
        hybrid_adapter.ObservationValue(
            entity_key=thread,
            field="axis",
            value="X",
            semantic="axis",
            evidence=["axis"],
        ),
        hybrid_adapter.ObservationValue(
            entity_key=thread,
            field="thread_spec",
            value="M6",
            evidence=["thread"],
        ),
        hybrid_adapter.ObservationValue(
            entity_key=thread,
            field="thread_depth",
            value=12.0,
            evidence=["depth"],
        ),
    ]

    unresolved = hybrid_adapter._missing_transverse_thread_start_side_unresolved(
        values=values
    )

    assert len(unresolved) == 1
    assert unresolved[0].entity_keys == [thread]
    assert unresolved[0].field == "start_side"
    assert unresolved[0].required_for_modeling is True
    assert "material_side + entry_endpoint" in unresolved[0].reason



def test_transverse_recess_start_side_fails_closed_when_both_boundaries_touch():
    hidden = "R1.HIDDEN_PAIR.horizontal.001.002"
    target = "R2.C1"
    values, ledger = hybrid_adapter._transverse_recess_start_side_values(
        report={
            "regions": [
                {
                    "region_id": "R1",
                    "bbox_px": [0, 0, 120, 100],
                    "linear_pattern_candidates": [
                        {
                            "orientation": "horizontal",
                            "axis_px": 50.0,
                            "segments_px": [
                                [-2, 4],
                                [96, 104],
                            ],
                        }
                    ],
                }
            ]
        },
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["R1"],
            )
        },
        boundaries=[
            {
                "status": "resolved",
                "region_id": "R1",
                "axis": "X",
                "anchors": [
                    {"ref": "R1.LEFT", "role": "overall_min", "position_px": 0.0},
                    {"ref": "R1.RIGHT", "role": "overall_max", "position_px": 100.0},
                ],
            }
        ],
        hidden_entity_records={
            hidden: {
                "entity_key": hidden,
                "feature_axis": "X",
                "pattern_orientation": "horizontal",
                "position_px": 50.0,
            }
        },
        callout_values=[
            hybrid_adapter.ObservationValue(
                entity_key=target,
                field="recessed_hole",
                value=True,
                evidence=["recess"],
            )
        ],
        centerline_alignments=[
            hybrid_adapter.ObservationCenterlineAlignment(
                entity_keys=[hidden, target],
                feature_axis="X",
                evidence=["centerline"],
            )
        ],
    )

    assert values == []
    assert ledger == []


def test_thread_recess_centerline_alignment_fails_closed_with_two_circle_matches():
    alignments, ledger = hybrid_adapter._unique_thread_recess_centerline_alignments(
        report={
            "regions": [
                {
                    "region_id": "R1",
                    "bbox_px": [0, 0, 200, 300],
                    "circle_groups": [],
                },
                {
                    "region_id": "R2",
                    "bbox_px": [200, 0, 200, 300],
                    "circle_groups": [
                        {"circle_group_id": "C1", "center_px": [300.0, 100.0]},
                        {"circle_group_id": "C2", "center_px": [340.0, 101.0]},
                    ],
                },
            ]
        },
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["R1"],
            ),
            "R2": hybrid_adapter.HybridRegionView(
                region_id="R2",
                view_kind="side",
                evidence=["R2"],
            ),
        },
        hidden_entity_records={
            "R1.HIDDEN_PAIR.horizontal.001.002": {
                "entity_key": "R1.HIDDEN_PAIR.horizontal.001.002",
                "feature_axis": "X",
                "pattern_orientation": "horizontal",
                "position_px": 100.0,
            }
        },
        callout_values=[
            hybrid_adapter.ObservationValue(
                entity_key="R1.HIDDEN_PAIR.horizontal.001.002",
                field="thread_spec",
                value="M6",
                evidence=["thread"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key="R2.C1",
                field="recessed_hole",
                value=True,
                evidence=["recess-1"],
            ),
            hybrid_adapter.ObservationValue(
                entity_key="R2.C2",
                field="recessed_hole",
                value=True,
                evidence=["recess-2"],
            ),
        ],
        entity_keys={
            "R1.HIDDEN_PAIR.horizontal.001.002",
            "R2.C1",
            "R2.C2",
        },
    )

    assert alignments == []
    assert ledger == []

def test_dimension_backed_through_support_requires_dashed_rail_across_local_material():
    support = hybrid_adapter._dimension_backed_through_projection_support(
        {
            "status": "dimension_backed",
            "region_id": "R2",
            "orientation": "vertical",
            "witness_positions_px": [100.0, 200.0],
        },
        report={
            "regions": [
                {
                    "region_id": "R2",
                    "bbox_px": [0, 0, 240, 300],
                    "linear_pattern_candidates": [
                        {
                            "orientation": "horizontal",
                            "axis_px": 200.0,
                            "span_px": [50, 170],
                            "segment_count": 5,
                            "gap_count": 3,
                            "dash_score": 0.68,
                        }
                    ],
                }
            ]
        },
        profile_inventory=[
            {
                "kind": "profile_edge_candidate",
                "ref": "R2.left",
                "region_id": "R2",
                "source_orientation": "vertical",
                "position_px": 60.0,
                "span_px": [40, 260],
            },
            {
                "kind": "profile_edge_candidate",
                "ref": "R2.right",
                "region_id": "R2",
                "source_orientation": "vertical",
                "position_px": 160.0,
                "span_px": [40, 260],
            },
        ],
    )

    assert support is not None
    assert support["profile_boundary_refs"] == ["R2.left", "R2.right"]
    assert support["engineering_coordinate_inferred_from_pixels"] is False
    assert support["pixel_geometry_used_for_topology_only"] is True



def test_dimension_backed_through_support_allows_one_pixel_endpoint_quantization():
    support = hybrid_adapter._dimension_backed_through_projection_support(
        {
            "status": "dimension_backed",
            "region_id": "R2",
            "orientation": "vertical",
            "witness_positions_px": [100.0, 200.0],
        },
        report={
            "regions": [
                {
                    "region_id": "R2",
                    "bbox_px": [0, 0, 240, 300],
                    "linear_pattern_candidates": [
                        {
                            "orientation": "horizontal",
                            "axis_px": 200.0,
                            "span_px": [64.0, 170.0],
                            "segment_count": 5,
                            "gap_count": 3,
                            "dash_score": 0.68,
                        }
                    ],
                }
            ]
        },
        profile_inventory=[
            {
                "kind": "profile_edge_candidate",
                "ref": "R2.left",
                "region_id": "R2",
                "source_orientation": "vertical",
                "position_px": 60.0,
                "span_px": [40, 260],
            },
            {
                "kind": "profile_edge_candidate",
                "ref": "R2.right",
                "region_id": "R2",
                "source_orientation": "vertical",
                "position_px": 160.0,
                "span_px": [40, 260],
            },
        ],
    )

    assert support is not None
    assert support["profile_boundary_refs"] == ["R2.left", "R2.right"]
    assert support["engineering_coordinate_inferred_from_pixels"] is False
    assert support["pixel_geometry_used_for_topology_only"] is True


def test_dimension_backed_through_support_rejects_blind_rail_before_far_boundary():
    support = hybrid_adapter._dimension_backed_through_projection_support(
        {
            "status": "dimension_backed",
            "region_id": "R2",
            "orientation": "vertical",
            "witness_positions_px": [100.0, 200.0],
        },
        report={
            "regions": [
                {
                    "region_id": "R2",
                    "bbox_px": [0, 0, 240, 300],
                    "linear_pattern_candidates": [
                        {
                            "orientation": "horizontal",
                            "axis_px": 200.0,
                            "span_px": [50, 120],
                            "segment_count": 5,
                            "gap_count": 3,
                            "dash_score": 0.68,
                        }
                    ],
                }
            ]
        },
        profile_inventory=[
            {
                "kind": "profile_edge_candidate",
                "ref": "R2.left",
                "region_id": "R2",
                "source_orientation": "vertical",
                "position_px": 60.0,
                "span_px": [40, 260],
            },
            {
                "kind": "profile_edge_candidate",
                "ref": "R2.right",
                "region_id": "R2",
                "source_orientation": "vertical",
                "position_px": 160.0,
                "span_px": [40, 260],
            },
        ],
    )

    assert support is None



def test_unassigned_profile_offset_recovery_uses_unique_subspan_without_pixel_metric():
    candidate = {
        "candidate_id": "DG_PROFILE",
        "region_id": "R2",
        "orientation": "horizontal",
        "axis_px": 100.0,
        "line_span_px": [10, 90],
        "witness_positions_px": [10.0, 50.0, 90.0],
        "accepted_token": None,
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.001",
                    }
                ],
            },
            {
                "witness_index": 1,
                "nearest_anchors": [],
            },
            {
                "witness_index": 2,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.vertical.002",
                    }
                ],
            },
        ],
    }
    report = {
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 7,
                    "token": "16",
                    "bbox": [[42, 55], [58, 55], [58, 75], [42, 75]],
                }
            ]
        }
    }
    view_lookup = {
        "R2": hybrid_adapter.HybridRegionView(
            region_id="R2",
            view_kind="side",
            evidence=["test:R2"],
        )
    }

    recovered, ledger = hybrid_adapter._recover_unassigned_profile_edge_offsets(
        report=report,
        candidates=[candidate],
        view_lookup=view_lookup,
        boundary_roles={"R2.structural.vertical.002": "overall_max"},
        profile_entity_by_ref={
            "R2.structural.vertical.001": "R2.PROFILE.LEFT",
            "R2.structural.vertical.002": "R2.PROFILE.RIGHT",
        },
    )

    assert len(recovered) == 1
    assert recovered[0].value == 16
    assert recovered[0].axis == "Y"
    assert {endpoint.role for endpoint in recovered[0].endpoints} == {
        "profile_boundary",
        "overall_max",
    }
    assert ledger[0]["engineering_coordinate_inferred_from_pixels"] is False
    assert ledger[0]["pixel_geometry_used_for_identity_only"] is True


def test_unassigned_profile_offset_recovery_rejects_internal_to_internal_span():
    candidate = {
        "candidate_id": "DG_SLOT",
        "region_id": "R1",
        "orientation": "horizontal",
        "axis_px": 100.0,
        "line_span_px": [40, 60],
        "witness_positions_px": [40.0, 60.0],
        "accepted_token": None,
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R1.structural.vertical.001",
                    }
                ],
            },
            {
                "witness_index": 1,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R1.structural.vertical.002",
                    }
                ],
            },
        ],
    }
    report = {
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 2,
                    "token": "2",
                    "bbox": [[45, 60], [55, 60], [55, 80], [45, 80]],
                }
            ]
        }
    }
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        )
    }

    recovered, ledger = hybrid_adapter._recover_unassigned_profile_edge_offsets(
        report=report,
        candidates=[candidate],
        view_lookup=view_lookup,
        boundary_roles={},
        profile_entity_by_ref={
            "R1.structural.vertical.001": "R1.PROFILE.LEFT",
            "R1.structural.vertical.002": "R1.PROFILE.RIGHT",
        },
    )

    assert recovered == []
    assert ledger == []


def _open_slot_fixture(extra_tokens=None):
    report = {
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 2,
                    "token": "2",
                    "bbox": [[108, 8], [124, 8], [124, 24], [108, 24]],
                },
                *(extra_tokens or []),
            ]
        },
        "regions": [
            {
                "region_id": "R1",
                "bbox_px": [0, 0, 200, 200],
                "circle_groups": [
                    {
                        "circle_group_id": "C1",
                        "center_px": [100, 100],
                        "rings": [{"radius_px": 30}],
                    }
                ],
            }
        ],
    }
    candidates = [
        {
            "candidate_id": "DG_TOP",
            "region_id": "R1",
            "witness_line_evidence": [
                {
                    "witness_index": 0,
                    "source_lines": [
                        {"orientation": "horizontal", "axis_px": 40, "span_px": [10, 94]},
                        {"orientation": "horizontal", "axis_px": 40, "span_px": [106, 190]},
                        {"orientation": "vertical", "axis_px": 94, "span_px": [45, 70]},
                        {"orientation": "vertical", "axis_px": 106, "span_px": [40, 70]},
                    ],
                }
            ],
        }
    ]
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        )
    }
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R1",
            "axis": "Z",
            "anchors": [
                {"role": "overall_max", "position_px": 40, "ref": "R1.TOP"},
                {"role": "overall_min", "position_px": 180, "ref": "R1.BOTTOM"},
            ],
        }
    ]
    facts = [
        hybrid_adapter.PartialOverallDimensionFact(
            axis="Z",
            value=66,
            evidence=["test:overall-z"],
        )
    ]
    return report, candidates, view_lookup, boundaries, facts


def test_open_slot_materializes_stable_core_without_pixel_metric():
    report, candidates, view_lookup, boundaries, facts = _open_slot_fixture()

    entities, values, unresolved, ledger, claimed = (
        hybrid_adapter._open_slot_observations(
            report=report,
            candidates=candidates,
            view_lookup=view_lookup,
            boundaries=boundaries,
            overall_dimension_facts=facts,
        )
    )

    assert len(entities) == 1
    assert entities[0].shape == "slot_edges"
    by_field = {item.field: item.value for item in values}
    assert by_field["type"] == "slot"
    assert by_field["width"] == 2
    assert by_field["width_axis"] == "X"
    assert by_field["through_axis"] == "Y"
    assert by_field["top_z"] == 66
    assert {item.field for item in unresolved} == {"bottom_z"}
    assert claimed == {2}
    assert ledger[0]["through_axis"] == "Y"
    assert (
        ledger[0]["through_axis_basis"]
        == "proved_gap_in_resolved_overall_silhouette_plus_view_normal"
    )
    assert ledger[0]["engineering_coordinate_inferred_from_pixels"] is False
    assert ledger[0]["pixel_geometry_used_for_topology_only"] is True
    assert ledger[0]["slot_edge_positions_px"] == [94.0, 106.0]


def test_open_slot_fails_closed_when_two_tokens_compete():
    report, candidates, view_lookup, boundaries, facts = _open_slot_fixture(
        extra_tokens=[
            {
                "source_item_index": 3,
                "token": "3",
                "bbox": [[90, 10], [104, 10], [104, 24], [90, 24]],
            }
        ]
    )

    entities, values, unresolved, ledger, claimed = (
        hybrid_adapter._open_slot_observations(
            report=report,
            candidates=candidates,
            view_lookup=view_lookup,
            boundaries=boundaries,
            overall_dimension_facts=facts,
        )
    )

    assert entities == []
    assert values == []
    assert unresolved == []
    assert ledger == []
    assert claimed == set()



def _rotational_profile_context(*, include_rotation=True, ambiguous_axes=False):
    facts = []
    if include_rotation:
        facts.append(
            hybrid_adapter.PartialRotationalSymmetryFact(
                axis="Z",
                evidence=["test:R1"],
            )
        )
    if ambiguous_axes:
        facts.append(
            hybrid_adapter.PartialRotationalSymmetryFact(
                axis="X",
                evidence=["test:R1"],
            )
        )
    return hybrid_adapter.HybridAdapterContext(
        region_views=[
            hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        ],
        rotational_symmetry_facts=facts,
    )


def _rotational_profile_inventory():
    return [
        {
            "kind": "profile_edge_candidate",
            "region_id": "R1",
            "ref": "LEFT",
            "source_orientation": "vertical",
            "position_px": 20.0,
            "span_px": [20.0, 80.0],
            "axis_ink_run_fraction": 1.0,
            "one_sided_boundary_candidate": True,
            "material_side_index": 0,
            "background_side_index": 1,
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R1",
            "ref": "SHOULDER",
            "source_orientation": "horizontal",
            "position_px": 20.0,
            "span_px": [20.0, 50.0],
            "axis_ink_run_fraction": 1.0,
            "one_sided_boundary_candidate": True,
            "material_side_index": 1,
            "background_side_index": 0,
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R1",
            "ref": "STEP",
            "source_orientation": "vertical",
            "position_px": 50.0,
            "span_px": [20.0, 60.0],
            "axis_ink_run_fraction": 1.0,
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R1",
            "ref": "ISOLATED",
            "source_orientation": "vertical",
            "position_px": 90.0,
            "span_px": [5.0, 10.0],
            "axis_ink_run_fraction": 1.0,
        },
    ]



def _independent_profile_edge(
    ref,
    *,
    orientation,
    position,
    span,
    support=1,
    ink_run=1.0,
):
    return {
        "kind": "profile_edge_candidate",
        "region_id": "R1",
        "ref": ref,
        "source_orientation": orientation,
        "position_px": float(position),
        "span_px": [float(span[0]), float(span[1])],
        "non_dimension_crossing_source_count": support,
        "axis_ink_run_fraction": float(ink_run),
    }


def test_rotational_oblique_profile_candidate_records_only_topology_evidence():
    inventory = [
        _independent_profile_edge(
            "VERTICAL_A",
            orientation="vertical",
            position=40,
            span=[20, 170],
        ),
        _independent_profile_edge(
            "HORIZONTAL_B",
            orientation="horizontal",
            position=140,
            span=[40, 180],
        ),
        _independent_profile_edge(
            "DIMENSION_ONLY",
            orientation="vertical",
            position=120,
            span=[20, 170],
            support=0,
        ),
    ]
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
        ],
        "annotation_line_candidates": [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[42, 60], [120, 138]],
                "angle_deg": 45.0,
                "length_px": 110.0,
                "line_edge_support_fraction": 0.96,
                "candidate_only": True,
                "exterior_boundary_candidate": True,
            }
        ],
    }

    hints = hybrid_adapter._rotational_oblique_profile_hints(
        report=report,
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
    )

    assert len(hints) == 1
    hint = hints[0]
    assert hint["region_id"] == "R1"
    assert hint["rotation_axis"] == "Z"
    assert hint["plane"] == "XZ"
    assert hint["supporting_profile_refs"] == [
        "VERTICAL_A",
        "HORIZONTAL_B",
    ]
    assert hint["engineering_coordinate_inferred_from_pixels"] is False
    assert hint["pixel_geometry_used_for_topology_only"] is True
    assert hint["primitive_kind"] == "line"
    assert hint["primitive_kind_basis"] == (
        "verified_continuous_straight_raster_segment_"
        "between_structural_contacts"
    )
    assert hint["line_edge_support_fraction"] == 0.96
    assert hint["basis"] == (
        "established_rotational_symmetry_plus_"
        "unique_independent_structural_contacts"
    )


def test_rotational_oblique_profile_direct_contacts_stay_unresolved_without_line_continuity():
    inventory = [
        _independent_profile_edge(
            "VERTICAL_A",
            orientation="vertical",
            position=40,
            span=[20, 170],
        ),
        _independent_profile_edge(
            "HORIZONTAL_B",
            orientation="horizontal",
            position=140,
            span=[40, 180],
        ),
    ]
    report = {
        "regions": [{"region_id": "R1", "bbox_px": [0, 0, 200, 200]}],
        "annotation_line_candidates": [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[42, 60], [120, 138]],
                "angle_deg": 45.0,
                "length_px": 110.0,
                "line_edge_support_fraction": 0.42,
                "candidate_only": True,
                "exterior_boundary_candidate": True,
            }
        ],
    }

    hints = hybrid_adapter._rotational_oblique_profile_hints(
        report=report,
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
    )

    assert len(hints) == 1
    assert hints[0]["supporting_profile_refs"] == [
        "VERTICAL_A",
        "HORIZONTAL_B",
    ]
    assert hints[0]["primitive_kind"] == "unresolved"
    assert hints[0]["primitive_kind_basis"] == (
        "two_structural_contacts_without_continuous_"
        "straight_raster_support"
    )


def test_rotational_oblique_profile_candidate_fails_closed_on_ambiguous_contact():
    inventory = [
        _independent_profile_edge(
            "VERTICAL_A",
            orientation="vertical",
            position=40,
            span=[20, 170],
        ),
        _independent_profile_edge(
            "HORIZONTAL_B1",
            orientation="horizontal",
            position=139,
            span=[40, 180],
        ),
        _independent_profile_edge(
            "HORIZONTAL_B2",
            orientation="horizontal",
            position=142,
            span=[40, 180],
        ),
    ]
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
        ],
        "annotation_line_candidates": [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[42, 60], [120, 140]],
                "angle_deg": 45.0,
                "length_px": 112.0,
                "candidate_only": True,
                "exterior_boundary_candidate": True,
            }
        ],
    }

    hints = hybrid_adapter._rotational_oblique_profile_hints(
        report=report,
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
    )

    assert hints == []


def test_rotational_oblique_profile_candidate_accepts_one_sided_boundary_continuation():
    inventory = [
        _independent_profile_edge(
            "VERTICAL_A",
            orientation="vertical",
            position=40,
            span=[20, 170],
        ),
        _independent_profile_edge(
            "HORIZONTAL_FAR",
            orientation="horizontal",
            position=180,
            span=[120, 190],
        ),
    ]
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
        ],
        "annotation_line_candidates": [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[42, 40], [80, 120]],
                "angle_deg": 64.6,
                "length_px": 88.5,
                "candidate_only": True,
                "one_sided_boundary_candidate": True,
                "boundary_evidence": {
                    "one_sided_boundary_candidate": True,
                    "material_side_index": 1,
                    "background_side_index": 0,
                },
                "exterior_boundary_candidate": True,
            }
        ],
    }

    hints = hybrid_adapter._rotational_oblique_profile_hints(
        report=report,
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
        profile_entity_by_ref={
            "VERTICAL_A": "R1.PROFILE.VERTICAL_A",
            "HORIZONTAL_FAR": "R1.PROFILE.HORIZONTAL_FAR",
        },
    )

    assert len(hints) == 1
    assert hints[0]["supporting_profile_refs"] == ["VERTICAL_A"]
    assert hints[0]["supporting_profile_entity_keys"] == [
        "R1.PROFILE.VERTICAL_A"
    ]
    assert hints[0]["supporting_profile_constant_axes"] == ["X"]
    assert hints[0]["support_status"] == "verified"
    assert hints[0]["primitive_kind"] == "unresolved"
    assert hints[0]["primitive_kind_basis"] == (
        "fragment_without_verified_full_straight_support"
    )
    assert hints[0]["one_sided_boundary_candidate"] is True
    assert hints[0]["material_side_index"] == 1
    assert hints[0]["background_side_index"] == 0
    assert hints[0]["basis"] == (
        "established_rotational_symmetry_plus_"
        "one_sided_boundary_plus_unique_structural_contact"
    )
    assert hints[0]["engineering_coordinate_inferred_from_pixels"] is False
    assert hints[0]["pixel_geometry_used_for_topology_only"] is True


def test_rotational_oblique_profile_candidate_rejects_ambiguous_one_sided_contact():
    inventory = [
        _independent_profile_edge(
            "VERTICAL_A",
            orientation="vertical",
            position=40,
            span=[20, 170],
        ),
        _independent_profile_edge(
            "VERTICAL_B",
            orientation="vertical",
            position=43,
            span=[20, 170],
        ),
    ]
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
        ],
        "annotation_line_candidates": [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[42, 40], [80, 120]],
                "angle_deg": 64.6,
                "length_px": 88.5,
                "candidate_only": True,
                "one_sided_boundary_candidate": True,
                "exterior_boundary_candidate": True,
            }
        ],
    }

    hints = hybrid_adapter._rotational_oblique_profile_hints(
        report=report,
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
    )

    assert hints == []


def test_rotational_oblique_profile_rejects_non_exterior_candidate():
    inventory = [
        _independent_profile_edge(
            "VERTICAL_A",
            orientation="vertical",
            position=40,
            span=[20, 170],
        ),
    ]
    report = {
        "regions": [
            {"region_id": "R1", "bbox_px": [0, 0, 200, 200]},
        ],
        "annotation_line_candidates": [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[42, 40], [80, 120]],
                "angle_deg": 64.6,
                "length_px": 88.5,
                "candidate_only": True,
                "one_sided_boundary_candidate": True,
                "exterior_boundary_candidate": False,
            }
        ],
    }

    hints = hybrid_adapter._rotational_oblique_profile_hints(
        report=report,
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
        profile_entity_by_ref={
            "VERTICAL_A": "R1.PROFILE.VERTICAL_A",
        },
    )

    assert hints == []


def test_rotational_oblique_profile_preserves_exterior_when_axis_support_is_unverified():
    inventory = [
        _independent_profile_edge(
            "FAKE_VERTICAL",
            orientation="vertical",
            position=80,
            span=[20, 170],
            ink_run=0.05,
        ),
    ]
    report = {
        "regions": [{"region_id": "R1", "bbox_px": [0, 0, 200, 200]}],
        "annotation_line_candidates": [
            {
                "kind": "oblique_line_candidate",
                "endpoints_px": [[82, 40], [120, 120]],
                "angle_deg": 64.6,
                "length_px": 88.5,
                "candidate_only": True,
                "one_sided_boundary_candidate": True,
                "exterior_boundary_candidate": True,
            }
        ],
    }

    hints = hybrid_adapter._rotational_oblique_profile_hints(
        report=report,
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
        profile_entity_by_ref={"FAKE_VERTICAL": "R1.PROFILE.FAKE_VERTICAL"},
    )

    assert len(hints) == 1
    hint = hints[0]
    assert hint["supporting_profile_refs"] == []
    assert hint["supporting_profile_entity_keys"] == []
    assert hint["supporting_profile_constant_axes"] == []
    assert hint["support_status"] == "unresolved"
    assert hint["basis"] == (
        "established_rotational_symmetry_plus_"
        "exterior_one_sided_boundary_without_verified_structural_contact"
    )
    assert hint["engineering_coordinate_inferred_from_pixels"] is False
    assert hint["pixel_geometry_used_for_topology_only"] is True


def test_rotational_profile_topology_records_connectivity_without_pixel_metric():
    inventory = _rotational_profile_inventory()
    hints = hybrid_adapter._rotational_profile_topology_hints(
        report={"regions": [{"region_id": "R1", "bbox_px": [0, 0, 100, 100]}]},
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
        profile_entity_by_ref={
            "LEFT": "R1.PROFILE.LEFT",
            "SHOULDER": "R1.PROFILE.SHOULDER",
            "STEP": "R1.PROFILE.STEP",
            "ISOLATED": "R1.PROFILE.ISOLATED",
        },
    )

    assert len(hints) == 1
    hint = hints[0]
    assert hint["rotation_axis"] == "Z"
    assert hint["plane"] == "XZ"
    assert [item["ref"] for item in hint["edges"]] == [
        "LEFT",
        "SHOULDER",
        "STEP",
    ]
    assert {
        item["ref"]: item["constant_axis"]
        for item in hint["edges"]
    } == {
        "LEFT": "X",
        "SHOULDER": "Z",
        "STEP": "X",
    }
    assert hint["junctions"] == [
        ["LEFT", "SHOULDER"],
        ["SHOULDER", "STEP"],
    ]
    by_ref = {item["ref"]: item for item in hint["edges"]}
    assert by_ref["LEFT"]["material_axis_direction"] == "positive"
    assert by_ref["LEFT"]["background_axis_direction"] == "negative"
    assert by_ref["SHOULDER"]["material_axis_direction"] == "negative"
    assert by_ref["SHOULDER"]["background_axis_direction"] == "positive"
    assert hint["engineering_coordinate_inferred_from_pixels"] is False
    assert hint["pixel_geometry_used_for_topology_only"] is True
    assert "position_px" not in repr(hint)
    assert "span_px" not in repr(hint)


def test_rotational_profile_topology_rejects_low_continuity_structural_edge():
    inventory = _rotational_profile_inventory()
    for item in inventory:
        if item["ref"] == "STEP":
            item["axis_ink_run_fraction"] = 0.05

    hints = hybrid_adapter._rotational_profile_topology_hints(
        report={"regions": [{"region_id": "R1", "bbox_px": [0, 0, 100, 100]}]},
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(),
        profile_entity_by_ref={
            item["ref"]: f"R1.PROFILE.{item['ref']}"
            for item in inventory
        },
    )

    assert len(hints) == 1
    assert [item["ref"] for item in hints[0]["edges"]] == [
        "LEFT",
        "SHOULDER",
    ]
    assert hints[0]["junctions"] == [["LEFT", "SHOULDER"]]
    assert "axis_ink_run_fraction" not in repr(hints[0])


def test_rotational_profile_topology_requires_established_rotation():
    inventory = _rotational_profile_inventory()
    hints = hybrid_adapter._rotational_profile_topology_hints(
        report={"regions": [{"region_id": "R1", "bbox_px": [0, 0, 100, 100]}]},
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(include_rotation=False),
        profile_entity_by_ref={
            item["ref"]: f"R1.PROFILE.{item['ref']}"
            for item in inventory
        },
    )

    assert hints == []


def test_rotational_profile_topology_rejects_ambiguous_rotation_axis():
    inventory = _rotational_profile_inventory()
    hints = hybrid_adapter._rotational_profile_topology_hints(
        report={"regions": [{"region_id": "R1", "bbox_px": [0, 0, 100, 100]}]},
        profile_inventory=inventory,
        view_lookup={
            "R1": hybrid_adapter.HybridRegionView(
                region_id="R1",
                view_kind="front",
                evidence=["test:R1"],
            )
        },
        context=_rotational_profile_context(ambiguous_axes=True),
        profile_entity_by_ref={
            item["ref"]: f"R1.PROFILE.{item['ref']}"
            for item in inventory
        },
    )

    assert hints == []


def test_metric_profile_topology_hint_finds_unique_l_cycle_without_pixel_metric():
    inventory = [
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_MIN",
            "source_orientation": "vertical",
            "position_px": 0.0,
            "span_px": [0.0, 8.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_MAX",
            "source_orientation": "vertical",
            "position_px": 32.0,
            "span_px": [0.0, 66.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_MIN",
            "source_orientation": "horizontal",
            "position_px": 0.0,
            "span_px": [0.0, 32.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_MAX",
            "source_orientation": "horizontal",
            "position_px": 66.0,
            "span_px": [16.0, 32.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_INTERNAL",
            "source_orientation": "vertical",
            "position_px": 16.0,
            "span_px": [8.0, 66.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_INTERNAL",
            "source_orientation": "horizontal",
            "position_px": 8.0,
            "span_px": [0.0, 16.0],
        },
    ]
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R2",
            "axis": "Y",
            "anchors": [
                {"ref": "U_MIN", "role": "overall_min"},
                {"ref": "U_MAX", "role": "overall_max"},
            ],
        },
        {
            "status": "resolved",
            "region_id": "R2",
            "axis": "Z",
            "anchors": [
                {"ref": "V_MIN", "role": "overall_min"},
                {"ref": "V_MAX", "role": "overall_max"},
            ],
        },
    ]
    hints = hybrid_adapter._metric_profile_topology_hints(
        report={"regions": [{"region_id": "R2", "bbox_px": [0, 0, 100, 100]}]},
        profile_inventory=inventory,
        view_lookup={
            "R2": hybrid_adapter.HybridRegionView(
                region_id="R2",
                view_kind="side",
                evidence=["test:R2"],
            )
        },
        boundaries=boundaries,
        profile_entity_by_ref={
            "U_INTERNAL": "R2.PROFILE.U_INTERNAL",
            "V_INTERNAL": "R2.PROFILE.V_INTERNAL",
        },
    )

    assert len(hints) == 1
    hint = hints[0]
    assert hint["plane"] == "YZ"
    assert hint["topology"] == "L"
    assert hint["upright_side"] == "max"
    assert hint["base_side"] == "min"
    assert hint["internal_u_entity_key"] == "R2.PROFILE.U_INTERNAL"
    assert hint["internal_v_entity_key"] == "R2.PROFILE.V_INTERNAL"
    assert hint["engineering_coordinate_inferred_from_pixels"] is False
    assert hint["pixel_geometry_used_for_topology_only"] is True


def test_metric_profile_topology_hint_rejects_non_unique_internal_cycles():
    inventory = [
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_MIN",
            "source_orientation": "vertical",
            "position_px": 0.0,
            "span_px": [0.0, 8.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_MAX",
            "source_orientation": "vertical",
            "position_px": 32.0,
            "span_px": [0.0, 66.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_MIN",
            "source_orientation": "horizontal",
            "position_px": 0.0,
            "span_px": [0.0, 32.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_MAX",
            "source_orientation": "horizontal",
            "position_px": 66.0,
            "span_px": [16.0, 32.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_INTERNAL_A",
            "source_orientation": "vertical",
            "position_px": 16.0,
            "span_px": [8.0, 66.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_INTERNAL_B",
            "source_orientation": "vertical",
            "position_px": 16.2,
            "span_px": [8.0, 66.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_INTERNAL",
            "source_orientation": "horizontal",
            "position_px": 8.0,
            "span_px": [0.0, 16.2],
        },
    ]
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R2",
            "axis": "Y",
            "anchors": [
                {"ref": "U_MIN", "role": "overall_min"},
                {"ref": "U_MAX", "role": "overall_max"},
            ],
        },
        {
            "status": "resolved",
            "region_id": "R2",
            "axis": "Z",
            "anchors": [
                {"ref": "V_MIN", "role": "overall_min"},
                {"ref": "V_MAX", "role": "overall_max"},
            ],
        },
    ]
    hints = hybrid_adapter._metric_profile_topology_hints(
        report={"regions": [{"region_id": "R2", "bbox_px": [0, 0, 100, 100]}]},
        profile_inventory=inventory,
        view_lookup={
            "R2": hybrid_adapter.HybridRegionView(
                region_id="R2",
                view_kind="side",
                evidence=["test:R2"],
            )
        },
        boundaries=boundaries,
        profile_entity_by_ref={
            "U_INTERNAL_A": "R2.PROFILE.U_INTERNAL_A",
            "U_INTERNAL_B": "R2.PROFILE.U_INTERNAL_B",
            "V_INTERNAL": "R2.PROFILE.V_INTERNAL",
        },
    )

    assert hints == []


def test_unassigned_profile_offset_recovery_rejects_far_text():
    candidate = {
        "candidate_id": "DG_PROFILE",
        "region_id": "R2",
        "orientation": "vertical",
        "axis_px": 100.0,
        "line_span_px": [0, 100],
        "witness_positions_px": [10.0, 80.0],
        "accepted_token": None,
        "witness_anchor_evidence": [
            {
                "witness_index": 0,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.horizontal.001",
                    }
                ],
            },
            {
                "witness_index": 1,
                "nearest_anchors": [
                    {
                        "kind": "profile_edge_candidate",
                        "ref": "R2.structural.horizontal.002",
                    }
                ],
            },
        ],
    }
    report = {
        "regions": [{"region_id": "R2", "bbox_px": [0, 0, 250, 560]}],
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 15,
                    "token": "63",
                    "bbox": [[280, 40], [330, 40], [330, 80], [280, 80]],
                }
            ]
        },
    }
    recovered, ledger = hybrid_adapter._recover_unassigned_profile_edge_offsets(
        report=report,
        candidates=[candidate],
        view_lookup={
            "R2": hybrid_adapter.HybridRegionView(
                region_id="R2",
                view_kind="side",
                evidence=["test:R2"],
            )
        },
        boundary_roles={"R2.structural.horizontal.002": "overall_min"},
        profile_entity_by_ref={
            "R2.structural.horizontal.001": "R2.PROFILE.INTERNAL",
            "R2.structural.horizontal.002": "R2.PROFILE.BOTTOM",
        },
    )

    assert recovered == []
    assert ledger == []


def test_metric_profile_topology_hint_accepts_fragmented_outer_edge_when_span_topology_is_unique():
    inventory = [
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_MIN",
            "source_orientation": "vertical",
            "position_px": 620.667,
            "span_px": [482.0, 667.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_DISTRACTOR",
            "source_orientation": "vertical",
            "position_px": 653.4,
            "span_px": [485.0, 580.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_INTERNAL",
            "source_orientation": "vertical",
            "position_px": 702.515,
            "span_px": [110.0, 484.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "U_MAX",
            "source_orientation": "vertical",
            "position_px": 785.8,
            "span_px": [110.0, 667.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_MAX",
            "source_orientation": "horizontal",
            "position_px": 160.0,
            "span_px": [737.0, 795.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_DISTRACTOR",
            "source_orientation": "horizontal",
            "position_px": 375.0,
            "span_px": [791.0, 864.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_INTERNAL",
            "source_orientation": "horizontal",
            "position_px": 481.606,
            "span_px": [621.0, 700.0],
        },
        {
            "kind": "profile_edge_candidate",
            "region_id": "R2",
            "ref": "V_MIN",
            "source_orientation": "horizontal",
            "position_px": 551.486,
            "span_px": [619.0, 787.0],
        },
    ]
    boundaries = [
        {
            "status": "resolved",
            "region_id": "R2",
            "axis": "Y",
            "anchors": [
                {"ref": "U_MIN", "role": "overall_min"},
                {"ref": "U_MAX", "role": "overall_max"},
            ],
        },
        {
            "status": "resolved",
            "region_id": "R2",
            "axis": "Z",
            "anchors": [
                {"ref": "V_MIN", "role": "overall_min"},
                {"ref": "V_MAX", "role": "overall_max"},
            ],
        },
    ]
    hints = hybrid_adapter._metric_profile_topology_hints(
        report={"regions": [{"region_id": "R2", "bbox_px": [0, 0, 250, 560]}]},
        profile_inventory=inventory,
        view_lookup={
            "R2": hybrid_adapter.HybridRegionView(
                region_id="R2",
                view_kind="side",
                evidence=["test:R2"],
            )
        },
        boundaries=boundaries,
        profile_entity_by_ref={
            "U_DISTRACTOR": "R2.PROFILE.U_DISTRACTOR",
            "U_INTERNAL": "R2.PROFILE.U_INTERNAL",
            "V_DISTRACTOR": "R2.PROFILE.V_DISTRACTOR",
            "V_INTERNAL": "R2.PROFILE.V_INTERNAL",
        },
    )

    assert len(hints) == 1
    assert hints[0]["upright_side"] == "max"
    assert hints[0]["base_side"] == "min"
    assert hints[0]["internal_u_ref"] == "U_INTERNAL"
    assert hints[0]["internal_v_ref"] == "V_INTERNAL"
    assert hints[0]["engineering_coordinate_inferred_from_pixels"] is False
    assert hints[0]["pixel_geometry_used_for_topology_only"] is True


def test_profile_vertices_map_to_distinct_profile_boundary_entities(monkeypatch):
    monkeypatch.setattr(
        hybrid_adapter,
        "derive_dimension_endpoint_candidates",
        lambda candidate: {
            "endpoints": [
                {
                    "status": "unique_physical_candidate",
                    "physical_candidates": [
                        {
                            "kind": "profile_vertex_candidate",
                            "ref": "V_LEFT",
                        }
                    ],
                },
                {
                    "status": "unique_physical_candidate",
                    "physical_candidates": [
                        {
                            "kind": "profile_vertex_candidate",
                            "ref": "V_RIGHT",
                        }
                    ],
                },
            ]
        },
    )

    endpoints, reason = hybrid_adapter._dimension_endpoints_from_candidates(
        {},
        entity_keys={"E_LEFT", "E_RIGHT"},
        boundary_roles={},
        profile_entity_by_ref={},
        profile_vertex_entity_by_ref={
            "V_LEFT": "E_LEFT",
            "V_RIGHT": "E_RIGHT",
        },
        evidence=["test:profile-vertex"],
    )

    assert reason is None
    assert [item.role for item in endpoints] == [
        "profile_boundary",
        "profile_boundary",
    ]
    assert [item.entity_key for item in endpoints] == ["E_LEFT", "E_RIGHT"]


def test_profile_vertex_entities_are_view_local_filtered_and_deduplicated():
    view_lookup = {
        "R1": hybrid_adapter.HybridRegionView(
            region_id="R1",
            view_kind="front",
            evidence=["test:R1"],
        )
    }
    candidates = [
        {
            "region_id": "UNKNOWN",
            "witness_anchor_evidence": [],
        },
        {
            "region_id": "R1",
            "witness_anchor_evidence": [
                "not-a-witness",
                {
                    "witness_index": 0,
                    "nearest_anchors": [
                        "not-an-anchor",
                        {
                            "kind": "profile_edge_candidate",
                            "ref": "EDGE_ONLY",
                        },
                        {
                            "kind": "profile_vertex_candidate",
                            "ref": "",
                        },
                        {
                            "kind": "profile_vertex_candidate",
                            "ref": "VERTEX_A",
                            "supporting_profile_ref": "EDGE_A",
                        },
                        {
                            "kind": "profile_vertex_candidate",
                            "ref": "VERTEX_A",
                            "supporting_profile_ref": "EDGE_A",
                        },
                        {
                            "kind": "profile_vertex_candidate",
                            "ref": "VERTEX_B",
                        },
                    ],
                },
            ],
        },
    ]

    entities, by_ref = hybrid_adapter._profile_vertex_entities(
        candidates,
        view_lookup,
    )

    assert set(by_ref) == {"VERTEX_A", "VERTEX_B"}
    assert len(entities) == 2
    assert all(item.view_key == "view.R1" for item in entities)
    assert all(item.shape == "profile" for item in entities)
    vertex_a = next(item for item in entities if item.key.endswith("VERTEX_A"))
    assert vertex_a.evidence == [
        "hybrid:profile-vertex:VERTEX_A",
        "hybrid:profile-edge:EDGE_A",
    ]
