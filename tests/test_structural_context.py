from __future__ import annotations

import pytest

from nx_mcp.drawing_intelligence.structural_context import (
    StructuralContextAnswers,
    StructuralContextError,
    StructuralRegionAnswer,
    assemble_structural_context,
    build_structural_context_queries,
)


def _reader_input() -> dict:
    return {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R1",
                "candidate_overlay_path": "C:/work/R1-candidates.png",
            },
            {
                "region_id": "R2",
                "candidate_overlay_path": "C:/work/R2-candidates.png",
            },
        ],
    }


def _hybrid_report() -> dict:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "candidates": [
            {
                "candidate_id": "DG_X",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": "40",
            },
            {
                "candidate_id": "DG_Z",
                "region_id": "R1",
                "orientation": "vertical",
                "accepted_token": "66",
            },
            {
                "candidate_id": "DG_Y",
                "region_id": "R2",
                "orientation": "horizontal",
                "accepted_token": "32",
            },
            {
                "candidate_id": "DG_UNRESOLVED",
                "region_id": "R2",
                "orientation": "vertical",
                "accepted_token": None,
            },
        ],
    }


def _answers() -> StructuralContextAnswers:
    return StructuralContextAnswers.model_validate(
        {
            "schema": "structural-context-answers-v1",
            "answers": [
                {
                    "query_id": "S001",
                    "view_kind": "front",
                    "evidence": ["structural:R1:overlay"],
                    "overall_assignments": [
                        {
                            "candidate_id": "DG_X",
                            "axis": "X",
                            "evidence": [
                                "structural:R1:overlay",
                                "hybrid-ocr:DG_X",
                            ],
                        },
                        {
                            "candidate_id": "DG_Z",
                            "axis": "Z",
                            "evidence": [
                                "structural:R1:overlay",
                                "hybrid-ocr:DG_Z",
                            ],
                        },
                    ],
                    "unresolved": [],
                },
                {
                    "query_id": "S002",
                    "view_kind": "side",
                    "evidence": ["structural:R2:overlay"],
                    "overall_assignments": [
                        {
                            "candidate_id": "DG_Y",
                            "axis": "Y",
                            "evidence": [
                                "structural:R2:overlay",
                                "hybrid-ocr:DG_Y",
                            ],
                        }
                    ],
                    "unresolved": [],
                },
            ],
        }
    )


def test_structural_query_builder_exposes_only_accepted_ocr_candidates():
    plan = build_structural_context_queries(_reader_input(), _hybrid_report())

    assert [item.region_id for item in plan.queries] == ["R1", "R2"]
    assert plan.queries[0].image_path.endswith("R1-candidates.png")
    assert [item.candidate_id for item in plan.queries[0].accepted_candidates] == [
        "DG_X",
        "DG_Z",
    ]
    assert [item.candidate_id for item in plan.queries[1].accepted_candidates] == [
        "DG_Y"
    ]
    assert plan.rules["read_numeric_value_from_image"] is False
    assert plan.rules["reinterpret_ocr_token"] is False
    assert plan.rules["dimension_endpoint_ownership"] is False


def test_structural_context_uses_ocr_values_and_view_axis_mapping():
    plan = build_structural_context_queries(_reader_input(), _hybrid_report())
    context = assemble_structural_context(plan, _answers(), _hybrid_report())

    assert [(item.region_id, item.view_kind) for item in context.region_views] == [
        ("R1", "front"),
        ("R2", "side"),
    ]
    facts = {(item.axis, item.value) for item in context.overall_dimension_facts}
    assert facts == {("X", 40.0), ("Y", 32.0), ("Z", 66.0)}
    assert context.confirmed_start_sides == []


def test_structural_context_rejects_axis_inconsistent_with_view_orientation():
    plan = build_structural_context_queries(_reader_input(), _hybrid_report())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["overall_assignments"][0]["axis"] = "Y"
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="expected axis 'X'"):
        assemble_structural_context(plan, answers, _hybrid_report())


def test_structural_context_rejects_unlisted_candidate():
    plan = build_structural_context_queries(_reader_input(), _hybrid_report())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][1]["overall_assignments"][0]["candidate_id"] = "DG_UNRESOLVED"
    payload["answers"][1]["overall_assignments"][0]["evidence"] = [
        "structural:R2:overlay"
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="selected unlisted candidate"):
        assemble_structural_context(plan, answers, _hybrid_report())


def test_structural_context_fails_closed_when_global_axis_is_missing():
    plan = build_structural_context_queries(_reader_input(), _hybrid_report())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][1]["overall_assignments"] = []
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="missing structural overall fact for axis Y"):
        assemble_structural_context(plan, answers, _hybrid_report())


def test_structural_context_fails_closed_on_view_unresolved():
    plan = build_structural_context_queries(_reader_input(), _hybrid_report())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["view_kind"] = None
    payload["answers"][0]["evidence"] = []
    payload["answers"][0]["overall_assignments"] = []
    payload["answers"][0]["unresolved"] = ["view kind is not uniquely visible"]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="remains unresolved"):
        assemble_structural_context(plan, answers, _hybrid_report())


def test_structural_answer_schema_forbids_numeric_value_in_assignment():
    with pytest.raises(Exception):
        StructuralRegionAnswer.model_validate(
            {
                "query_id": "S001",
                "view_kind": "front",
                "evidence": ["structural:R1:overlay"],
                "overall_assignments": [
                    {
                        "candidate_id": "DG_X",
                        "axis": "X",
                        "value": 40,
                        "evidence": [
                            "structural:R1:overlay",
                            "hybrid-ocr:DG_X",
                        ],
                    }
                ],
                "unresolved": [],
            }
        )
