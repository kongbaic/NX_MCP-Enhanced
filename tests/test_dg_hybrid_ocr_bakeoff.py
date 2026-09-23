from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"

local_spec = importlib.util.spec_from_file_location(
    "dg_local_ocr_bakeoff",
    BENCHMARKS / "dg_local_ocr_bakeoff.py",
)
assert local_spec is not None
assert local_spec.loader is not None
local_module = importlib.util.module_from_spec(local_spec)
sys.modules[local_spec.name] = local_module
local_spec.loader.exec_module(local_module)

hybrid_spec = importlib.util.spec_from_file_location(
    "dg_hybrid_ocr_bakeoff",
    BENCHMARKS / "dg_hybrid_ocr_bakeoff.py",
)
assert hybrid_spec is not None
assert hybrid_spec.loader is not None
hybrid = importlib.util.module_from_spec(hybrid_spec)
sys.modules[hybrid_spec.name] = hybrid
hybrid_spec.loader.exec_module(hybrid)


def _item(
    text: str,
    center_x: float,
    center_y: float,
    width: float = 20.0,
    height: float = 10.0,
):
    half_w = width / 2
    half_h = height / 2
    return {
        "text": text,
        "confidence": 0.99,
        "bbox": [
            [center_x - half_w, center_y - half_h],
            [center_x + half_w, center_y - half_h],
            [center_x + half_w, center_y + half_h],
            [center_x - half_w, center_y + half_h],
        ],
    }


def _candidate(
    candidate_id: str,
    axis: float,
    box: list[int],
    *,
    orientation: str = "horizontal",
):
    return {
        "candidate_id": candidate_id,
        "orientation": orientation,
        "axis_px": axis,
        "wide": {
            "source_roi_bbox_px": box,
        },
    }


def test_linear_tokens_exclude_non_linear_engineering_callouts():
    assert hybrid._linear_tokens("Ø20") == set()
    assert hybrid._linear_tokens("R5") == set()
    assert hybrid._linear_tokens("M6") == set()
    assert hybrid._linear_tokens("40±0.02") == {"40±0.02"}
    assert hybrid._linear_tokens("24") == {"24"}


def test_linear_tokens_reject_leading_zero_integer():
    assert hybrid._linear_tokens("012") == set()


def test_global_observation_is_assigned_to_only_nearest_candidate():
    candidates = [
        _candidate("DG-A", 100.0, [0, 60, 200, 80]),
        _candidate("DG-B", 130.0, [0, 60, 200, 100]),
    ]
    items = [_item("24", 80.0, 105.0)]

    assigned = hybrid._assign_global_items(candidates, items)

    assert len(assigned["DG-A"]) == 1
    assert assigned["DG-A"][0]["token"] == "24"
    assert assigned["DG-B"] == []


def test_global_observation_stays_unassigned_without_distance_margin():
    candidates = [
        _candidate("DG-A", 100.0, [0, 60, 200, 80]),
        _candidate("DG-B", 108.0, [0, 60, 200, 80]),
    ]
    items = [_item("24", 80.0, 104.0)]

    assigned = hybrid._assign_global_items(candidates, items)

    assert assigned["DG-A"] == []
    assert assigned["DG-B"] == []


def test_global_proposal_uses_nearest_token_with_margin():
    candidate = _candidate("DG-A", 100.0, [0, 60, 200, 100])
    assignments = [
        {
            "source_item_index": 1,
            "token": "24",
            "perpendicular_distance_px": 10.0,
        },
        {
            "source_item_index": 2,
            "token": "40",
            "perpendicular_distance_px": 25.0,
        },
    ]

    token, reason = hybrid._global_proposal(candidate, assignments)

    assert token == "24"
    assert reason == "nearest_unique_global_linear_token"


def test_hybrid_decision_accepts_only_global_local_agreement():
    accepted, reason = hybrid._hybrid_decision("24", {"24", "40"})

    assert accepted == "24"
    assert reason == "global_geometry_assignment_confirmed_by_local_roi"


def test_hybrid_decision_rejects_partial_digit_conflict():
    accepted, reason = hybrid._hybrid_decision("6", {"66"})

    assert accepted is None
    assert reason == "global_local_token_disagreement"
