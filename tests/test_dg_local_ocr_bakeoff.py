from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "benchmarks" / "dg_local_ocr_bakeoff.py"

spec = importlib.util.spec_from_file_location("dg_local_ocr_bakeoff", MODULE_PATH)
assert spec is not None
assert spec.loader is not None
local_ocr = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = local_ocr
spec.loader.exec_module(local_ocr)


def test_candidate_roi_box_uses_witness_span_for_horizontal():
    candidate = {
        "orientation": "horizontal",
        "axis_px": 100,
        "line_span_px": [20, 180],
        "witness_positions_px": [50, 150],
    }

    tight = local_ocr._candidate_roi_box(
        candidate,
        [0, 0, 200, 200],
        200,
        200,
        scale="tight",
    )
    wide = local_ocr._candidate_roi_box(
        candidate,
        [0, 0, 200, 200],
        200,
        200,
        scale="wide",
    )

    assert tight[0] < 50
    assert tight[0] + tight[2] > 150
    assert wide[2] >= tight[2]
    assert wide[3] >= tight[3]


def test_candidate_roi_box_uses_witness_span_for_vertical():
    candidate = {
        "orientation": "vertical",
        "axis_px": 100,
        "line_span_px": [20, 180],
        "witness_positions_px": [40, 160],
    }

    box = local_ocr._candidate_roi_box(
        candidate,
        [0, 0, 200, 200],
        200,
        200,
        scale="tight",
    )

    assert box[1] < 40
    assert box[1] + box[3] > 160


def test_primary_tokens_never_infer_diameter_from_plain_zero():
    assert local_ocr._primary_tokens("012") == set()
    assert local_ocr._primary_tokens("Ø12") == {"Ø12"}


def test_primary_tokens_preserve_tolerance_as_one_claim():
    assert local_ocr._primary_tokens("40±0.02") == {"40±0.02"}


def test_decision_requires_tight_wide_consensus():
    accepted, reason = local_ocr._decision({"66"}, {"66"})

    assert accepted == "66"
    assert reason == "same_unique_token_in_tight_and_wide_roi"


def test_decision_rejects_single_scale_token():
    accepted, reason = local_ocr._decision({"66"}, set())

    assert accepted is None
    assert reason == "no_token_consensus_between_tight_and_wide_roi"


def test_decision_rejects_multiple_consensus_tokens():
    accepted, reason = local_ocr._decision({"63", "66"}, {"63", "66"})

    assert accepted is None
    assert reason == "multiple_tokens_consistent_across_tight_and_wide_roi"
