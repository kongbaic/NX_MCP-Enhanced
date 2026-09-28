from __future__ import annotations

import pytest
from pydantic import ValidationError

from nx_mcp.drawing_intelligence.structural_context import (
    StructuralContextAnswers,
    StructuralContextError,
    StructuralContextQueryPlan,
    StructuralOverallFact,
    StructuralRegionAnswer,
    StructuralRegionQuery,
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


def test_structural_query_builder_only_requests_region_structure():
    plan = build_structural_context_queries(_reader_input())

    assert [item.region_id for item in plan.queries] == ["R1", "R2"]
    assert plan.queries[0].image_path.endswith("R1.png")
    assert plan.queries[0].evidence_label == "structural:R1:crop"
    assert plan.rules["report_only_view_kind_and_direct_overall_dimensions"] is True
    assert plan.rules["report_only_visual_rotational_symmetry_basis"] is True
    assert plan.rules["agent_must_not_report_engineering_rotation_axis"] is True
    assert plan.rules["agent_must_not_report_axial_section_symmetry_direction"] is True
    assert plan.rules["axial_section_axis_from_deterministic_profile_symmetry"] is True
    assert plan.rules["require_explicit_rotational_symmetry_decision"] is True
    assert plan.rules["allow_nonsection_longitudinal_revolved_profile"] is True
    assert plan.rules["allow_axial_section_without_drawn_centerline"] is True
    assert plan.rules["require_centerline_for_nonsection_rotation"] is True
    assert plan.rules["require_unique_section_symmetry_axis_without_centerline"] is True
    assert plan.rules["require_section_semantics_without_centerline"] is True
    assert plan.rules["solid_profile_line_is_not_centerline"] is True
    assert plan.rules["mirror_symmetry_alone_insufficient"] is True
    assert "require_whole_part_centerline_for_rotation" not in plan.rules
    assert plan.rules["require_paired_coaxial_profile_for_rotation"] is True
    assert plan.rules["not_established_requires_counterevidence"] is True
    assert plan.rules["insufficient_rotation_evidence_is_unresolved"] is True
    assert plan.rules["derive_missing_dimensions"] is False
    assert plan.rules["feature_inventory"] is False
    assert plan.rules["dimension_endpoint_ownership"] is False
    assert plan.rules["pixel_measurement"] is False
    assert plan.view_axis_map["front"].horizontal == "X"
    assert plan.view_axis_map["front"].vertical == "Z"
    assert plan.view_axis_map["side"].horizontal == "Y"
    assert plan.view_axis_map["side"].vertical == "Z"
    assert plan.view_axis_map["top"].horizontal == "X"
    assert plan.view_axis_map["top"].vertical == "Y"
    template = StructuralContextAnswers.model_validate(plan.answer_template)
    assert [item.query_id for item in template.answers] == ["S001", "S002"]
    assert template.answers[0].evidence == ["structural:R1:crop"]
    assert template.answers[1].evidence == ["structural:R2:crop"]
    assert template.answers[0].rotational_symmetry is None
    assert template.answers[1].rotational_symmetry is None
    assert all(item.unresolved == ["pending_structural_visual_read"] for item in template.answers)


def test_structural_query_builder_carries_deterministic_profile_symmetry_axis():
    reader_input = _reader_input()
    reader_input["regions"][0]["bilateral_symmetry_hint"] = {
        "status": "established",
        "axis_direction": "vertical",
        "method": "foreground_mirror_consensus_v1",
        "vertical_score": 0.72,
        "horizontal_score": 0.31,
        "score_margin": 0.41,
    }

    plan = build_structural_context_queries(reader_input)

    assert plan.queries[0].deterministic_profile_symmetry_axis == "vertical"
    assert (
        plan.queries[0].deterministic_profile_symmetry_method
        == "foreground_mirror_consensus_v1"
    )
    assert plan.queries[1].deterministic_profile_symmetry_axis is None


def test_structural_query_builder_prefers_full_drawing_context_image():
    reader_input = _reader_input()
    reader_input["regions"][0]["structural_context_path"] = "C:/work/R1-structural-context.png"

    plan = build_structural_context_queries(reader_input)

    assert plan.queries[0].image_path.endswith("R1-structural-context.png")
    assert plan.queries[0].evidence_label == "structural:R1:context"
    assert plan.queries[1].image_path.endswith("R2.png")
    assert plan.queries[1].evidence_label == "structural:R2:crop"

    template = StructuralContextAnswers.model_validate(plan.answer_template)
    assert template.answers[0].evidence == ["structural:R1:context"]
    assert template.answers[1].evidence == ["structural:R2:crop"]


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


def test_structural_query_plan_rejects_axis_map_drift():
    plan = build_structural_context_queries(_reader_input())
    payload = plan.model_dump(mode="json", by_alias=True)
    payload["view_axis_map"]["front"]["vertical"] = "Y"
    with pytest.raises(ValidationError, match="view_axis_map"):
        StructuralContextQueryPlan.model_validate(payload)


def test_structural_context_rejects_axis_not_visible_in_view():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["overall_dimension_facts"][0]["axis"] = "Y"
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="is not visible"):
        assemble_structural_context(plan, answers)


def test_structural_context_allows_one_missing_transverse_axis_with_explicit_rotation_axis():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "basis": "centerline",
        "centerline_direction": "vertical",
        "evidence": ["structural:R1:crop"],
    }
    payload["answers"][1]["view_kind"] = "front"
    payload["answers"][1]["rotational_symmetry"] = {
        "status": "established",
        "basis": "centerline",
        "centerline_direction": "vertical",
        "evidence": ["structural:R2:crop"],
    }
    payload["answers"][1]["overall_dimension_facts"] = []
    answers = StructuralContextAnswers.model_validate(payload)

    context = assemble_structural_context(plan, answers)

    facts = {(item.axis, item.value) for item in context.overall_dimension_facts}
    assert facts == {("X", 40.0), ("Z", 66.0)}
    assert len(context.rotational_symmetry_facts) == 1
    assert context.rotational_symmetry_facts[0].axis == "Z"
    assert context.rotational_symmetry_facts[0].evidence == [
        "structural:R1:crop",
        "structural:R2:crop",
    ]


def test_structural_context_derives_axis_from_deterministic_profile_symmetry():
    reader_input = _reader_input()
    for region in reader_input["regions"]:
        region["bilateral_symmetry_hint"] = {
            "status": "established",
            "axis_direction": "vertical",
            "method": "foreground_mirror_consensus_v1",
            "vertical_score": 0.72,
            "horizontal_score": 0.31,
            "score_margin": 0.41,
        }
    plan = build_structural_context_queries(reader_input)
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "basis": "axial_section_symmetry",
        "evidence": ["structural:R1:crop"],
    }
    payload["answers"][1]["view_kind"] = "front"
    payload["answers"][1]["overall_dimension_facts"] = []
    payload["answers"][1]["rotational_symmetry"] = {
        "status": "established",
        "basis": "axial_section_symmetry",
        "evidence": ["structural:R2:crop"],
    }
    answers = StructuralContextAnswers.model_validate(payload)

    context = assemble_structural_context(plan, answers)

    assert len(context.rotational_symmetry_facts) == 1
    assert context.rotational_symmetry_facts[0].axis == "Z"


def test_structural_context_maps_deterministic_horizontal_symmetry_to_x():
    reader_input = _reader_input()
    for region in reader_input["regions"]:
        region["bilateral_symmetry_hint"] = {
            "status": "established",
            "axis_direction": "horizontal",
            "method": "foreground_mirror_consensus_v1",
            "vertical_score": 0.30,
            "horizontal_score": 0.70,
            "score_margin": 0.40,
        }
    plan = build_structural_context_queries(reader_input)
    payload = _answers().model_dump(mode="json", by_alias=True)
    for index, evidence in ((0, "structural:R1:crop"), (1, "structural:R2:crop")):
        payload["answers"][index]["view_kind"] = "front"
        payload["answers"][index]["overall_dimension_facts"] = []
        payload["answers"][index]["rotational_symmetry"] = {
            "status": "established",
            "basis": "axial_section_symmetry",
            "evidence": [evidence],
        }
    payload["answers"][0]["overall_dimension_facts"] = [
        {"axis": "X", "value": 40, "evidence": ["structural:R1:crop"]},
        {"axis": "Z", "value": 66, "evidence": ["structural:R1:crop"]},
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    context = assemble_structural_context(plan, answers)

    assert len(context.rotational_symmetry_facts) == 1
    assert context.rotational_symmetry_facts[0].axis == "X"


def test_structural_context_rejects_axial_section_without_deterministic_symmetry_axis():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "basis": "axial_section_symmetry",
        "evidence": ["structural:R1:crop"],
    }
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="lacks deterministic profile symmetry axis"):
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
    payload["answers"][0]["rotational_symmetry"] = None
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
                "rotational_symmetry": {
                    "status": "not_established",
                    "evidence": ["structural:R1:crop"],
                },
                "entities": [{"key": "main_bore"}],
                "unresolved": [],
            }
        )


def test_structural_query_builder_fails_closed_on_invalid_prep_contracts():
    with pytest.raises(StructuralContextError, match="requires reader-input-v1"):
        build_structural_context_queries({"schema": "wrong", "regions": []})

    with pytest.raises(StructuralContextError, match="max_region_queries"):
        build_structural_context_queries(_reader_input(), max_region_queries=0)

    with pytest.raises(StructuralContextError, match="at least one region"):
        build_structural_context_queries({"schema": "reader-input-v1", "regions": []})

    with pytest.raises(StructuralContextError, match="exceeds bounded maximum"):
        build_structural_context_queries(_reader_input(), max_region_queries=1)


def test_structural_query_builder_fails_closed_on_malformed_regions():
    with pytest.raises(StructuralContextError, match="must be an object"):
        build_structural_context_queries(
            {"schema": "reader-input-v1", "regions": ["not-an-object"]}
        )

    with pytest.raises(StructuralContextError, match="requires region_id"):
        build_structural_context_queries(
            {"schema": "reader-input-v1", "regions": [{"crop_path": "C:/work/R1.png"}]}
        )

    with pytest.raises(StructuralContextError, match="duplicate reader region"):
        build_structural_context_queries(
            {
                "schema": "reader-input-v1",
                "regions": [
                    {"region_id": "R1", "crop_path": "C:/work/R1.png"},
                    {"region_id": "R1", "crop_path": "C:/work/R1-copy.png"},
                ],
            }
        )

    with pytest.raises(StructuralContextError, match="requires crop_path"):
        build_structural_context_queries(
            {"schema": "reader-input-v1", "regions": [{"region_id": "R1"}]}
        )


def test_structural_context_rejects_duplicate_answer_query_ids():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][1]["query_id"] = "S001"
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="query_ids must be unique"):
        assemble_structural_context(plan, answers)


def test_structural_context_rejects_answer_plan_mismatch():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][1]["query_id"] = "S999"
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="do not match query plan"):
        assemble_structural_context(plan, answers)


def test_structural_context_rejects_duplicate_overall_axis():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["overall_dimension_facts"].append(
        {
            "axis": "X",
            "value": 40,
            "evidence": ["structural:R1:crop"],
        }
    )
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="repeats overall axis X"):
        assemble_structural_context(plan, answers)


def test_structural_context_rejects_conflicting_cross_view_overall():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][1]["overall_dimension_facts"].append(
        {
            "axis": "Z",
            "value": 65,
            "evidence": ["structural:R2:crop"],
        }
    )
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="conflicting structural overall facts"):
        assemble_structural_context(plan, answers)


def test_structural_models_fail_closed_on_invalid_evidence_and_answer_shape():
    with pytest.raises(ValidationError, match="evidence must contain"):
        StructuralOverallFact.model_validate({"axis": "X", "value": 40, "evidence": [" "]})

    with pytest.raises(ValidationError, match="structured unresolved reason"):
        StructuralRegionAnswer.model_validate(
            {
                "query_id": "S001",
                "view_kind": None,
                "evidence": [],
                "overall_dimension_facts": [],
                "rotational_symmetry": None,
                "unresolved": [],
            }
        )

    with pytest.raises(ValidationError, match="cannot carry overall dimension facts"):
        StructuralRegionAnswer.model_validate(
            {
                "query_id": "S001",
                "view_kind": None,
                "evidence": [],
                "overall_dimension_facts": [
                    {
                        "axis": "X",
                        "value": 40,
                        "evidence": ["structural:R1:crop"],
                    }
                ],
                "rotational_symmetry": None,
                "unresolved": ["view kind unresolved"],
            }
        )

    with pytest.raises(ValidationError, match="resolved view_kind requires evidence"):
        StructuralRegionAnswer.model_validate(
            {
                "query_id": "S001",
                "view_kind": "front",
                "evidence": [],
                "overall_dimension_facts": [],
                "rotational_symmetry": {
                    "status": "not_established",
                    "evidence": ["structural:R1:crop"],
                },
                "unresolved": [],
            }
        )


def test_structural_answer_requires_explicit_rotational_symmetry_decision():
    payload = _answers().model_dump(mode="json", by_alias=True)
    del payload["answers"][0]["rotational_symmetry"]

    with pytest.raises(ValidationError, match="Field required"):
        StructuralContextAnswers.model_validate(payload)

    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = None
    with pytest.raises(ValidationError, match="requires explicit rotational symmetry decision"):
        StructuralContextAnswers.model_validate(payload)


def test_structural_rotational_symmetry_decision_is_fail_closed():
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "evidence": ["structural:R1:crop"],
    }
    with pytest.raises(ValidationError, match="requires visual basis"):
        StructuralContextAnswers.model_validate(payload)

    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "basis": "centerline",
        "evidence": ["structural:R1:crop"],
    }
    with pytest.raises(ValidationError, match="requires centerline_direction"):
        StructuralContextAnswers.model_validate(payload)

    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "basis": "axial_section_symmetry",
        "paired_sides": "left_right",
        "evidence": ["structural:R1:crop"],
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StructuralContextAnswers.model_validate(payload)

    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "not_established",
        "basis": "centerline",
        "centerline_direction": "horizontal",
        "evidence": ["structural:R1:crop"],
    }
    with pytest.raises(ValidationError, match="requires null visual basis fields"):
        StructuralContextAnswers.model_validate(payload)


def test_structural_rotational_symmetry_decision_requires_current_query_evidence():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "basis": "centerline",
        "centerline_direction": "horizontal",
        "evidence": ["structural:R2:crop"],
    }
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="evidence must be exactly"):
        assemble_structural_context(plan, answers)


def test_structural_rotational_symmetry_may_stay_null_only_when_unresolved():
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = None
    payload["answers"][0]["unresolved"] = ["rotational symmetry cannot be established visually"]
    answers = StructuralContextAnswers.model_validate(payload)
    plan = build_structural_context_queries(_reader_input())

    with pytest.raises(StructuralContextError, match="remains unresolved"):
        assemble_structural_context(plan, answers)


def test_structural_answer_rejects_engineering_axis_input():
    payload = _answers().model_dump(mode="json", by_alias=True)["answers"][0]
    payload["rotational_symmetry"] = {
        "status": "established",
        "axis": "X",
        "evidence": ["structural:R1:crop"],
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StructuralRegionAnswer.model_validate(payload)

    payload = _answers().model_dump(mode="json", by_alias=True)["answers"][0]
    payload["rotational_symmetry_axis"] = "X"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StructuralRegionAnswer.model_validate(payload)


def test_structural_query_plan_rejects_duplicate_query_and_region_ids():
    query = {
        "kind": "structural_context",
        "region_id": "R1",
        "image_path": "C:/work/R1.png",
        "evidence_label": "structural:R1:crop",
        "instruction_key": "structural-context-v1",
    }
    view_axis_map = {
        "front": {"horizontal": "X", "vertical": "Z"},
        "side": {"horizontal": "Y", "vertical": "Z"},
        "top": {"horizontal": "X", "vertical": "Y"},
    }

    with pytest.raises(ValidationError, match="query ids must be unique"):
        StructuralContextQueryPlan.model_validate(
            {
                "schema": "structural-context-queries-v1",
                "queries": [
                    {"query_id": "S001", **query},
                    {"query_id": "S001", **{**query, "region_id": "R2"}},
                ],
                "rules": {},
                "view_axis_map": view_axis_map,
            }
        )

    with pytest.raises(ValidationError, match="region ids must be unique"):
        StructuralContextQueryPlan.model_validate(
            {
                "schema": "structural-context-queries-v1",
                "queries": [
                    {"query_id": "S001", **query},
                    {"query_id": "S002", **query},
                ],
                "rules": {},
                "view_axis_map": view_axis_map,
            }
        )

    StructuralRegionQuery.model_validate({"query_id": "S001", **query})
