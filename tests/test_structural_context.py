from __future__ import annotations

import pytest
from pydantic import ValidationError

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
                "crop_path": "C:/work/R1.png",
            },
            {
                "region_id": "R2",
                "crop_path": "C:/work/R2.png",
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
                    "unresolved": [],
                },
            ],
        }
    )


def test_structural_query_builder_only_requests_region_structure():
    plan = build_structural_context_queries(_reader_input())

    assert [item.region_id for item in plan.queries] == ["R1", "R2"]
    assert plan.queries[0].image_path.endswith("R1.png")
    assert plan.queries[0].evidence_label == "structural:R1:crop"
    assert plan.rules["report_only_view_kind_and_direct_overall_dimensions"] is True
    assert plan.rules["derive_missing_dimensions"] is False
    assert plan.rules["feature_inventory"] is False
    assert plan.rules["dimension_endpoint_ownership"] is False
    assert plan.rules["pixel_measurement"] is False


def test_structural_context_builds_independent_overall_facts():
    plan = build_structural_context_queries(_reader_input())
    context = assemble_structural_context(plan, _answers())

    assert [(item.region_id, item.view_kind) for item in context.region_views] == [
        ("R1", "front"),
        ("R2", "side"),
    ]
    facts = {(item.axis, item.value) for item in context.overall_dimension_facts}
    assert facts == {("X", 40.0), ("Y", 32.0), ("Z", 66.0)}
    assert all(
        item.evidence in (["structural:R1:crop"], ["structural:R2:crop"])
        for item in context.overall_dimension_facts
    )
    assert context.confirmed_start_sides == []


def test_structural_context_rejects_axis_not_visible_in_view():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["overall_dimension_facts"][0]["axis"] = "Y"
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="is not visible"):
        assemble_structural_context(plan, answers)


def test_structural_context_fails_closed_when_global_axis_is_missing():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][1]["overall_dimension_facts"] = []
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="missing structural overall fact for axis Y"):
        assemble_structural_context(plan, answers)


def test_structural_context_fails_closed_on_view_unresolved():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["view_kind"] = None
    payload["answers"][0]["evidence"] = []
    payload["answers"][0]["overall_dimension_facts"] = []
    payload["answers"][0]["unresolved"] = ["view kind is not uniquely visible"]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="remains unresolved"):
        assemble_structural_context(plan, answers)


def test_structural_context_rejects_nonquery_evidence():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["overall_dimension_facts"][0]["evidence"] = ["DG17"]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="evidence must be exactly"):
        assemble_structural_context(plan, answers)


def test_structural_answer_schema_forbids_feature_or_endpoint_fields():
    with pytest.raises(ValidationError):
        StructuralRegionAnswer.model_validate(
            {
                "query_id": "S001",
                "view_kind": "front",
                "evidence": ["structural:R1:crop"],
                "overall_dimension_facts": [],
                "entities": [{"key": "main_bore"}],
                "unresolved": [],
            }
        )
