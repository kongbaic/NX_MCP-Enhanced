from __future__ import annotations

import json
from pathlib import Path

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
CONTEXT_PATH = (
    ROOT
    / "benchmarks"
    / "hybrid_integration"
    / "shkss20-40-adapter-context.json"
)


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
    assert validate_reader_capture_contract(capture) == []
