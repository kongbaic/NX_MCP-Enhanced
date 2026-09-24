from __future__ import annotations

import json
from pathlib import Path

from nx_mcp.drawing_intelligence import (
    build_semantic_draft,
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.capture import validate_reader_capture_contract
from nx_mcp.drawing_intelligence.hybrid_capture_adapter import (
    HybridAdapterContext,
    adapt_hybrid_ocr_report,
)
from nx_mcp.drawing_intelligence.reader_observation_finalizer import (
    finalize_partial_reader_observations,
)
from nx_mcp.drawing_intelligence.reader_observations import assemble_reader_capture

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT / "benchmarks" / "hybrid_integration" / "shkss20-40-adapter-context.json"


def _minimal_hybrid_report() -> dict:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "observed_silent_drop_count": 0,
            "conflicting_linear_observations": [],
            "secondary_assignment_observations": [],
            "unassigned_linear_observations": [],
            "local_only_linear_observations": [],
        },
        "regions": [
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
                        "rings": [{"radius_px": 20}],
                    }
                ],
            },
        ],
        "candidates": [
            {
                "candidate_id": "DG12",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": "24",
            }
        ],
    }


def test_shkss_fixture_drives_hybrid_to_contract_valid_capture():
    context = HybridAdapterContext.model_validate(
        json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    )
    partial = adapt_hybrid_ocr_report(
        _minimal_hybrid_report(),
        context,
    )
    full = finalize_partial_reader_observations(partial)
    capture = assemble_reader_capture(full)

    assert capture.overall_dimensions.length_x == 40
    assert capture.overall_dimensions.width_y == 32
    assert capture.overall_dimensions.height_z == 66
    assert [view.kind for view in capture.views] == ["front", "side"]
    assert capture.dimensions[0].value == 24
    assert capture.dimensions[0].axis == "X"
    assert capture.dimensions[0].endpoints[0].role == "unresolved"
    assert len(capture.entities) == 2
    assert all(item.required_for_modeling is False for item in capture.entities)
    assert validate_reader_capture_contract(capture) == []


def test_unowned_callout_facts_reach_backend_without_inventing_geometry():
    context = HybridAdapterContext.model_validate(
        json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    )
    report = _minimal_hybrid_report()
    report["coverage"]["routed_elsewhere_or_unclassified_observations"] = [
        {
            "source_item_index": 1,
            "text": "M6深12",
            "bbox": [[100, 100], [180, 100], [180, 130], [100, 130]],
            "confidence": 0.99,
        }
    ]

    partial = adapt_hybrid_ocr_report(report, context)
    full = finalize_partial_reader_observations(partial)
    capture = assemble_reader_capture(full)

    assert validate_reader_capture_contract(capture) == []

    carrier = next(
        item for item in capture.entities if "hybrid:whole:1" in item.source_ids
    )
    assert carrier.shape == "other"
    assert carrier.required_for_modeling is False
    assert carrier.cross_view_disposition is None

    linked = link_reader_capture(capture)
    feature_id = linked.entity_to_feature[carrier.id]

    direct = {
        item.target: item.value
        for item in linked.evidence.direct_values
    }
    assert direct[f"feature:{feature_id}.thread_spec"] == "M6"
    assert direct[f"feature:{feature_id}.thread_depth"] == 12.0
    assert not any(
        target.startswith(f"feature:{feature_id}.centerline")
        or target == f"feature:{feature_id}.axis"
        for target in direct
    )

    compiled = compile_evidence_graph(linked.evidence)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)

    feature = next(
        item for item in draft["features"] if item["id"] == feature_id
    )
    assert feature["thread_spec"] == "M6"
    assert feature["thread_depth"] == 12.0
    assert "axis" not in feature
    assert "centerline" not in feature
    assert draft["dimension_closure"]["status"] == "incomplete"
    assert any(
        item.get("required_for_modeling", True)
        and item.get("field") == "engineering_callout_geometry_binding"
        for item in draft["unresolved"]
    )

