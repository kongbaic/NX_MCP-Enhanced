from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPLAY_PATH = ROOT / "benchmarks" / "replay_hybrid_constraint_bridge.py"

SPEC = importlib.util.spec_from_file_location(
    "hybrid_constraint_bridge_report",
    REPLAY_PATH,
)
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def test_final_blocking_status_replaces_reader_stage_blocker() -> None:
    result = {
        "blocking_unresolved": [
            {
                "kind": "feature_value",
                "field": "bottom_z",
                "required_for_modeling": True,
            }
        ],
        "blocking_summary": [{"field": "bottom_z"}],
    }

    R._set_final_blocking_status(
        result,
        [
            {
                "id": "U_ADVISORY",
                "kind": "other",
                "field": "dimension_tolerance",
                "required_for_modeling": False,
            }
        ],
    )

    assert result["blocking_unresolved"] == []
    assert result["blocking_summary"] == []


def test_reader_blocker_summary_preserves_stage_identity_fields() -> None:
    items = [
        {
            "kind": "feature_value",
            "field": "bottom_z",
            "dimension_key": None,
            "entity_keys": ["R1.OPEN_SLOT.2"],
            "reason": "reader-stage unresolved",
            "required_for_modeling": True,
        }
    ]

    summary = R._blocking_summary(items)

    assert summary == [
        {
            "kind": "feature_value",
            "field": "bottom_z",
            "dimension_key": None,
            "entity_keys": ["R1.OPEN_SLOT.2"],
            "feature_ids": [],
            "reason": "reader-stage unresolved",
        }
    ]
