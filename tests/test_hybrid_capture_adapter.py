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
                    }
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
