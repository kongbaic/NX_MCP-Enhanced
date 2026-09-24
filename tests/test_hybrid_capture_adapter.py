from __future__ import annotations

import pytest

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


def test_adapter_preserves_conflicts_secondary_and_unassigned_evidence():
    partial = adapt_hybrid_ocr_report(_report(), _context())

    fields = [item.field for item in partial.unresolved]
    assert "dimension_value_candidate" in fields
    assert "secondary_linear_assignment" in fields
    assert "unassigned_linear_text" in fields
    assert "local_only_linear_text" in fields
    blocking = [item for item in partial.unresolved if item.required_for_modeling]
    assert blocking
    assert all(item.kind == "unsupported_representation" for item in blocking)
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
    ]

    ledger = next(
        item
        for item in partial.observations
        if item["kind"] == "hybrid_engineering_callout_ledger"
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

    callout_unresolved = [
        item
        for item in partial.unresolved
        if item.field == "engineering_callout_geometry_binding"
    ]
    assert len(callout_unresolved) == 2
    assert all(item.kind == "feature_inventory" for item in callout_unresolved)
    assert all(item.required_for_modeling for item in callout_unresolved)
    assert all(not item.entity_keys for item in callout_unresolved)

