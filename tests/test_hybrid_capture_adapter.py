from __future__ import annotations

import pytest

import nx_mcp.drawing_intelligence.hybrid_capture_adapter as hybrid_adapter

from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    HybridCaptureAdapterError,
    adapt_hybrid_ocr_report,
)


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


def test_adapter_preserves_tolerance_without_claiming_endpoint_ownership():
    partial = adapt_hybrid_ocr_report(_report(), _context())

    tolerance = [item for item in partial.unresolved if item.field == "dimension_tolerance"]
    assert len(tolerance) == 1
    assert tolerance[0].dimension_key == "R1.DG25"
    assert tolerance[0].required_for_modeling is False


def test_adapter_preserves_coverage_evidence_without_overblocking_bookkeeping():
    partial = adapt_hybrid_ocr_report(_report(), _context())

    fields = [item.field for item in partial.unresolved]
    assert "dimension_value_candidate" in fields
    assert "secondary_linear_assignment" in fields
    assert "unassigned_linear_text" in fields
    assert "local_only_linear_text" in fields

    blocking = [item for item in partial.unresolved if item.required_for_modeling]
    assert [(item.kind, item.field) for item in blocking] == [
        ("unsupported_representation", "dimension_value_candidate")
    ]

    advisory_fields = {item.field for item in partial.unresolved if not item.required_for_modeling}
    assert {
        "secondary_linear_assignment",
        "unassigned_linear_text",
        "local_only_linear_text",
    } <= advisory_fields
    assert partial.observations[0]["kind"] == "hybrid_ocr_coverage_ledger"


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
