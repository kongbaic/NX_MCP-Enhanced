from __future__ import annotations

import json
from pathlib import Path

import pytest

from nx_mcp.drawing_intelligence.structural_context import (
    StructuralContextAnswers,
    StructuralContextError,
    assemble_structural_context,
    build_structural_context_queries,
)

ROOT = Path(__file__).resolve().parents[1]
SHKSS_CONTEXT = ROOT / "benchmarks" / "hybrid_integration" / "shkss20-40-adapter-context.json"


def _symmetry_hint(axis_direction: str) -> dict[str, object]:
    return {
        "status": "established",
        "axis_direction": axis_direction,
        "method": "foreground_mirror_consensus_v1",
        "vertical_score": 0.76 if axis_direction == "vertical" else 0.31,
        "horizontal_score": 0.31 if axis_direction == "vertical" else 0.76,
        "score_margin": 0.45,
    }


def test_shkss_multiview_direct_closure_ignores_bilateral_hints_without_rotation():
    expected = json.loads(SHKSS_CONTEXT.read_text(encoding="utf-8"))

    reader_input = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R1",
                "crop_path": "C:/work/shkss-front.png",
                # Deliberately present: a topology hint alone must never create
                # rotational closure for this ordinary multiview part.
                "bilateral_symmetry_hint": _symmetry_hint("vertical"),
            },
            {
                "region_id": "R2",
                "crop_path": "C:/work/shkss-side.png",
                "bilateral_symmetry_hint": _symmetry_hint("horizontal"),
            },
        ],
    }
    plan = build_structural_context_queries(reader_input)
    answers = StructuralContextAnswers.model_validate(
        {
            "schema": "structural-context-answers-v1",
            "answers": [
                {
                    "query_id": "S001",
                    "view_kind": "front",
                    "evidence": ["structural:R1:crop"],
                    "overall_dimension_facts": [
                        {
                            "axis": "X",
                            "value": 40,
                            "evidence": ["structural:R1:crop"],
                        },
                        {
                            "axis": "Z",
                            "value": 66,
                            "evidence": ["structural:R1:crop"],
                        },
                    ],
                    "rotational_symmetry": {
                        "status": "not_established",
                        "evidence": ["structural:R1:crop"],
                    },
                    "unresolved": [],
                },
                {
                    "query_id": "S002",
                    "view_kind": "side",
                    "evidence": ["structural:R2:crop"],
                    "overall_dimension_facts": [
                        {
                            "axis": "Y",
                            "value": 32,
                            "evidence": ["structural:R2:crop"],
                        }
                    ],
                    "rotational_symmetry": {
                        "status": "not_established",
                        "evidence": ["structural:R2:crop"],
                    },
                    "unresolved": [],
                },
            ],
        }
    )

    context = assemble_structural_context(plan, answers)

    expected_overalls = {
        (item["axis"], float(item["value"])) for item in expected["overall_dimension_facts"]
    }
    actual_overalls = {(item.axis, float(item.value)) for item in context.overall_dimension_facts}

    assert (
        actual_overalls
        == expected_overalls
        == {
            ("X", 40.0),
            ("Y", 32.0),
            ("Z", 66.0),
        }
    )
    assert [(item.region_id, item.view_kind) for item in context.region_views] == [
        ("R1", "front"),
        ("R2", "side"),
    ]
    assert context.rotational_symmetry_facts == []


def test_single_view_axial_section_uses_deterministic_vertical_hint_for_rotation():
    reader_input = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R1",
                "crop_path": "C:/work/axial-section.png",
                "bilateral_symmetry_hint": _symmetry_hint("vertical"),
            },
            {
                "region_id": "R2",
                "crop_path": "C:/work/axial-section-middle.png",
                "bilateral_symmetry_hint": _symmetry_hint("vertical"),
            },
            {
                "region_id": "R3",
                "crop_path": "C:/work/annotation-only.png",
            },
        ],
    }
    plan = build_structural_context_queries(reader_input)
    answers = StructuralContextAnswers.model_validate(
        {
            "schema": "structural-context-answers-v1",
            "answers": [
                {
                    "query_id": "S001",
                    "view_kind": "front",
                    "evidence": ["structural:R1:crop"],
                    "overall_dimension_facts": [
                        {
                            "axis": "X",
                            "value": 300,
                            "evidence": ["structural:R1:crop"],
                        },
                        {
                            "axis": "Z",
                            "value": 75,
                            "evidence": ["structural:R1:crop"],
                        },
                    ],
                    "rotational_symmetry": {
                        "status": "established",
                        "basis": "axial_section_symmetry",
                        "evidence": ["structural:R1:crop"],
                    },
                    "unresolved": [],
                },
                {
                    "query_id": "S002",
                    "view_kind": "front",
                    "evidence": ["structural:R2:crop"],
                    "overall_dimension_facts": [],
                    "rotational_symmetry": {
                        "status": "established",
                        "basis": "axial_section_symmetry",
                        "evidence": ["structural:R2:crop"],
                    },
                    "unresolved": [],
                },
                {
                    "query_id": "S003",
                    "view_kind": "front",
                    "evidence": ["structural:R3:crop"],
                    "overall_dimension_facts": [],
                    "rotational_symmetry": None,
                    "unresolved": ["rotational_symmetry_not_visible_in_region"],
                }
            ],
        }
    )

    context = assemble_structural_context(plan, answers)

    assert {(item.axis, float(item.value)) for item in context.overall_dimension_facts} == {
        ("X", 300.0),
        ("Z", 75.0),
    }
    assert len(context.rotational_symmetry_facts) == 1
    assert context.rotational_symmetry_facts[0].axis == "Z"


def test_bilateral_hint_alone_cannot_turn_symmetric_nonrotational_part_into_revolved_part():
    reader_input = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R1",
                "crop_path": "C:/work/symmetric-nonrotational.png",
                "bilateral_symmetry_hint": _symmetry_hint("vertical"),
            }
        ],
    }
    plan = build_structural_context_queries(reader_input)
    answers = StructuralContextAnswers.model_validate(
        {
            "schema": "structural-context-answers-v1",
            "answers": [
                {
                    "query_id": "S001",
                    "view_kind": "front",
                    "evidence": ["structural:R1:crop"],
                    "overall_dimension_facts": [
                        {
                            "axis": "X",
                            "value": 120,
                            "evidence": ["structural:R1:crop"],
                        },
                        {
                            "axis": "Z",
                            "value": 80,
                            "evidence": ["structural:R1:crop"],
                        },
                    ],
                    "rotational_symmetry": {
                        "status": "not_established",
                        "evidence": ["structural:R1:crop"],
                    },
                    "unresolved": [],
                }
            ],
        }
    )

    with pytest.raises(
        StructuralContextError,
        match="missing structural overall fact for axis Y",
    ):
        assemble_structural_context(plan, answers)
