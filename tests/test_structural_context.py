from __future__ import annotations

from pathlib import Path

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


def test_nx_agent_skill_keeps_structural_topology_axis_contract():
    skill = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "nx-agent"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert 'deterministic_profile_symmetry_overlay="blue_dashed_topology_axis"' in skill
    assert "TOPOLOGY SYM AXIS" in skill
    assert '"basis":"axial_section_symmetry"' in skill
    assert "non_geometric_reference_region" in skill


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
    assert plan.rules["allow_non_geometric_reference_region"] is True
    assert plan.rules["derive_missing_dimensions"] is False
    assert plan.rules["feature_inventory"] is False
    assert plan.rules["dimension_endpoint_ownership"] is False
    assert plan.rules["labeled_dimension_resolved_reason_must_be_null"] is True
    assert plan.rules["labeled_dimension_unresolved_reason_required"] is True
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
    reader_input["regions"][0]["structural_context_path"] = (
        "C:/work/R1-structural-context.png"
    )

    plan = build_structural_context_queries(reader_input)

    assert plan.queries[0].deterministic_profile_symmetry_axis == "vertical"
    assert (
        plan.queries[0].deterministic_profile_symmetry_method
        == "foreground_mirror_consensus_v1"
    )
    assert (
        plan.queries[0].deterministic_profile_symmetry_overlay
        == "blue_dashed_topology_axis"
    )
    assert plan.rules["topology_axis_overlay_is_visual_aid_not_centerline"] is True
    assert plan.rules["centerline_absence_alone_is_not_rotation_counterevidence"] is True
    assert plan.queries[1].deterministic_profile_symmetry_axis is None
    assert plan.queries[1].deterministic_profile_symmetry_overlay is None


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


def _hybrid_report_with_accepted_linear_span_bounds() -> dict:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {},
        "candidates": [
            {
                "candidate_id": "DG_INNER",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": "250",
                "witness_positions_px": [20.0, 180.0],
            },
            {
                "candidate_id": "DG_OUTER",
                "region_id": "R1",
                "orientation": "horizontal",
                "accepted_token": "300",
                "witness_positions_px": [10.0, 190.0],
            },
            {
                "candidate_id": "DG_HEIGHT_LOCAL",
                "region_id": "R1",
                "orientation": "vertical",
                "accepted_token": "28",
                "witness_positions_px": [40.0, 100.0],
            },
        ],
    }


def test_structural_query_records_accepted_linear_span_lower_bounds():
    plan = build_structural_context_queries(
        _reader_input(),
        hybrid_report=_hybrid_report_with_accepted_linear_span_bounds(),
    )

    bounds = {
        item.visual_direction: item
        for item in plan.queries[0].accepted_linear_span_lower_bounds
    }
    assert bounds["horizontal"].minimum_value == 300
    assert bounds["horizontal"].candidate_ids == ["DG_OUTER"]
    assert bounds["vertical"].minimum_value == 28
    assert bounds["vertical"].candidate_ids == ["DG_HEIGHT_LOCAL"]
    assert (
        plan.rules["overall_dimension_must_cover_accepted_linear_spans"]
        is True
    )


def test_structural_context_rejects_overall_smaller_than_accepted_linear_span():
    plan = build_structural_context_queries(
        _reader_input(),
        hybrid_report=_hybrid_report_with_accepted_linear_span_bounds(),
    )
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["overall_dimension_facts"][0]["value"] = 250
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(
        StructuralContextError,
        match="overall axis X=250 is smaller than accepted same-axis linear span 300",
    ):
        assemble_structural_context(plan, answers)


def test_structural_context_accepts_overall_covering_accepted_linear_span():
    plan = build_structural_context_queries(
        _reader_input(),
        hybrid_report=_hybrid_report_with_accepted_linear_span_bounds(),
    )
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["overall_dimension_facts"][0]["value"] = 300
    answers = StructuralContextAnswers.model_validate(payload)

    context = assemble_structural_context(plan, answers)
    facts = {(item.axis, item.value) for item in context.overall_dimension_facts}
    assert ("X", 300.0) in facts


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


def test_structural_context_rejects_established_rotation_with_explicit_counterevidence():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "basis": "centerline",
        "centerline_direction": "vertical",
        "evidence": ["structural:R1:crop"],
    }
    payload["answers"][1]["rotational_symmetry"] = {
        "status": "not_established",
        "evidence": ["structural:R2:crop"],
    }
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(
        StructuralContextError,
        match="established rotation conflicts with explicit not_established",
    ):
        assemble_structural_context(plan, answers)


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


def test_structural_context_skips_explicit_non_geometric_reference_region():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = {
        "status": "established",
        "basis": "centerline",
        "centerline_direction": "horizontal",
        "evidence": ["structural:R1:crop"],
    }
    payload["answers"][1] = {
        "query_id": "S002",
        "view_kind": None,
        "evidence": ["structural:R2:crop"],
        "overall_dimension_facts": [],
        "rotational_symmetry": None,
        "labeled_dimension_decisions": [],
        "unresolved": ["non_geometric_reference_region"],
    }

    context = assemble_structural_context(
        plan,
        StructuralContextAnswers.model_validate(payload),
    )

    assert [(item.region_id, item.view_kind) for item in context.region_views] == [
        ("R1", "front"),
    ]


def test_non_geometric_reference_region_rejects_structural_geometry_targets():
    plan = build_structural_context_queries(_reader_input())
    plan_payload = plan.model_dump(mode="json", by_alias=True)
    plan_payload["queries"][1]["accepted_linear_span_lower_bounds"] = [
        {
            "visual_direction": "horizontal",
            "minimum_value": 25.0,
            "candidate_ids": ["DG_TABLE_LIKE"],
        }
    ]
    guarded_plan = StructuralContextQueryPlan.model_validate(plan_payload)

    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][1] = {
        "query_id": "S002",
        "view_kind": None,
        "evidence": ["structural:R2:crop"],
        "overall_dimension_facts": [],
        "rotational_symmetry": None,
        "labeled_dimension_decisions": [],
        "unresolved": ["non_geometric_reference_region"],
    }

    with pytest.raises(StructuralContextError, match="structural geometry targets"):
        assemble_structural_context(
            guarded_plan,
            StructuralContextAnswers.model_validate(payload),
        )


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


def test_region_local_rotation_not_visible_defers_to_other_region():
    reader_input = _reader_input()
    reader_input["regions"][0]["bilateral_symmetry_hint"] = {
        "status": "established",
        "axis_direction": "vertical",
        "method": "foreground_mirror_consensus_v1",
        "vertical_score": 0.74,
        "horizontal_score": 0.28,
        "score_margin": 0.46,
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
    payload["answers"][1]["rotational_symmetry"] = None
    payload["answers"][1]["unresolved"] = [
        "rotational_symmetry_not_visible_in_region"
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    context = assemble_structural_context(plan, answers)

    assert len(context.rotational_symmetry_facts) == 1
    assert context.rotational_symmetry_facts[0].axis == "Z"


def test_region_local_rotation_not_visible_does_not_hide_other_unresolved():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["rotational_symmetry"] = None
    payload["answers"][0]["unresolved"] = [
        "rotational_symmetry_not_visible_in_region",
        "view_geometry_ambiguous",
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="remains unresolved"):
        assemble_structural_context(plan, answers)


def test_all_regions_rotation_not_visible_still_fail_closed_when_axis_missing():
    plan = build_structural_context_queries(_reader_input())
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["overall_dimension_facts"] = [
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
    ]
    payload["answers"][1]["view_kind"] = "front"
    payload["answers"][1]["overall_dimension_facts"] = []
    for item in payload["answers"]:
        item["rotational_symmetry"] = None
        item["unresolved"] = ["rotational_symmetry_not_visible_in_region"]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(StructuralContextError, match="missing structural overall fact for axis Y"):
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


def _reader_input_with_labeled_dimension_regions() -> dict:
    payload = _reader_input()
    payload["regions"][0]["source_bbox_px"] = [100, 100, 240, 220]
    payload["regions"][1]["source_bbox_px"] = [500, 100, 220, 220]
    return payload


def _hybrid_report_with_labeled_unassigned_dimension() -> dict:
    return {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 17,
                    "text": "P2 - 12 mm",
                    "bbox": [
                        [52, 180],
                        [132, 180],
                        [132, 205],
                        [52, 205],
                    ],
                    "primary_tokens": ["12"],
                    "token": "12",
                    "reason": "no_unique_DG_assignment",
                },
                {
                    "source_item_index": 18,
                    "text": "4",
                    "bbox": [
                        [70, 220],
                        [82, 220],
                        [82, 235],
                        [70, 235],
                    ],
                    "primary_tokens": ["4"],
                    "token": "4",
                    "reason": "no_unique_DG_assignment",
                },
            ]
        },
    }


def test_structural_query_builder_targets_only_explicit_labeled_mm_dimensions():
    plan = build_structural_context_queries(
        _reader_input_with_labeled_dimension_regions(),
        hybrid_report=_hybrid_report_with_labeled_unassigned_dimension(),
    )

    targets = [
        target
        for query in plan.queries
        for target in query.labeled_dimension_targets
    ]
    assert len(targets) == 1
    assert targets[0].target_id == "LD_0017"
    assert targets[0].source_item_index == 17
    assert targets[0].source_text == "P2 - 12 mm"
    assert targets[0].value == 12
    assert plan.queries[0].labeled_dimension_targets == targets
    assert plan.queries[1].labeled_dimension_targets == []
    assert plan.rules["labeled_dimension_value_from_hybrid_ocr_only"] is True
    assert plan.rules["labeled_dimension_relation_only"] is True

    template = StructuralContextAnswers.model_validate(plan.answer_template)
    decision = template.answers[0].labeled_dimension_decisions[0]
    assert decision.target_id == "LD_0017"
    assert decision.status == "unresolved"
    assert decision.reason == "pending_labeled_dimension_relation_read"


def test_structural_context_uses_ocr_value_for_labeled_dimension_fact():
    plan = build_structural_context_queries(
        _reader_input_with_labeled_dimension_regions(),
        hybrid_report=_hybrid_report_with_labeled_unassigned_dimension(),
    )
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["labeled_dimension_decisions"] = [
        {
            "target_id": "LD_0017",
            "status": "resolved",
            "visual_direction": "vertical",
            "relation": "overall_max_to_profile_transition",
            "profile_transition_geometry": "non_orthogonal",
            "symmetry_scope": "bilateral",
            "evidence": ["structural:R1:crop"],
            "reason": None,
        }
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    context = assemble_structural_context(plan, answers)

    assert len(context.labeled_dimension_facts) == 1
    fact = context.labeled_dimension_facts[0]
    assert fact.target_id == "LD_0017"
    assert fact.source_item_index == 17
    assert fact.value == 12
    assert fact.axis == "Z"
    assert fact.relation == "overall_max_to_profile_transition"
    assert fact.profile_transition_geometry == "non_orthogonal"
    assert fact.symmetry_scope == "bilateral"
    assert fact.engineering_coordinate_inferred_from_pixels is False
    assert fact.pixel_geometry_used_for_topology_only is True
    assert fact.evidence == ["hybrid:whole:17", "structural:R1:crop"]


def test_structural_context_allows_local_relation_without_optional_topology_metadata():
    plan = build_structural_context_queries(
        _reader_input_with_labeled_dimension_regions(),
        hybrid_report=_hybrid_report_with_labeled_unassigned_dimension(),
    )
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["labeled_dimension_decisions"] = [
        {
            "target_id": "LD_0017",
            "status": "resolved",
            "visual_direction": "vertical",
            "relation": "between_profile_boundaries",
            "profile_transition_geometry": None,
            "symmetry_scope": None,
            "evidence": ["structural:R1:crop"],
            "reason": None,
        }
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    context = assemble_structural_context(plan, answers)

    assert len(context.labeled_dimension_facts) == 1
    fact = context.labeled_dimension_facts[0]
    assert fact.relation == "between_profile_boundaries"
    assert fact.profile_transition_geometry is None
    assert fact.symmetry_scope is None
    assert fact.value == 12
    assert fact.axis == "Z"
    assert fact.engineering_coordinate_inferred_from_pixels is False
    assert fact.pixel_geometry_used_for_topology_only is True


def test_structural_context_fails_closed_when_labeled_dimension_decision_missing():
    plan = build_structural_context_queries(
        _reader_input_with_labeled_dimension_regions(),
        hybrid_report=_hybrid_report_with_labeled_unassigned_dimension(),
    )

    with pytest.raises(
        StructuralContextError,
        match="labeled dimension decisions mismatch",
    ):
        assemble_structural_context(plan, _answers())


def test_structural_context_fails_closed_when_labeled_dimension_relation_unresolved():
    plan = build_structural_context_queries(
        _reader_input_with_labeled_dimension_regions(),
        hybrid_report=_hybrid_report_with_labeled_unassigned_dimension(),
    )
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["labeled_dimension_decisions"] = [
        {
            "target_id": "LD_0017",
            "status": "unresolved",
            "visual_direction": None,
            "relation": None,
            "profile_transition_geometry": None,
            "symmetry_scope": None,
            "evidence": ["structural:R1:crop"],
            "reason": "relation is not uniquely visible",
        }
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(
        StructuralContextError,
        match="labeled dimension 'LD_0017' remains unresolved",
    ):
        assemble_structural_context(plan, answers)


def test_structural_labeled_dimension_answer_cannot_inject_numeric_value():
    plan = build_structural_context_queries(
        _reader_input_with_labeled_dimension_regions(),
        hybrid_report=_hybrid_report_with_labeled_unassigned_dimension(),
    )
    payload = plan.answer_template
    payload["answers"][0]["labeled_dimension_decisions"][0] = {
        "target_id": "LD_0017",
        "status": "resolved",
        "visual_direction": "vertical",
        "relation": "between_profile_boundaries",
        "profile_transition_geometry": "mixed",
        "symmetry_scope": "single",
        "evidence": ["structural:R1:crop"],
        "reason": None,
        "value": 999,
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StructuralContextAnswers.model_validate(payload)


def test_structural_query_builder_covers_safe_labeled_dimension_coverage_buckets():
    reader_input = _reader_input_with_labeled_dimension_regions()
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 5,
                    "text": "H3 - 12 mm",
                    "bbox": [
                        [86, 180],
                        [223, 180],
                        [223, 205],
                        [86, 205],
                    ],
                    "primary_tokens": ["12"],
                    "token": "12",
                    "reason": "no_unique_DG_assignment",
                }
            ],
            "unconfirmed_proposal_observations": [
                {
                    "source_item_index": 4,
                    "text": "S- 4.5 mm",
                    "bbox": [
                        [150, 130],
                        [240, 130],
                        [240, 155],
                        [150, 155],
                    ],
                    "primary_tokens": ["4.5"],
                    "token": "4.5",
                    "candidate_id": "DG122",
                    "reason": "candidate_line_is_extension_witness_of_accepted_dimension",
                }
            ],
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 10,
                    "text": "fl - 3 mmx",
                    "bbox": [
                        [70, 250],
                        [180, 250],
                        [180, 275],
                        [70, 275],
                    ],
                    "primary_tokens": ["3"],
                    "reason": "not_one_standalone_linear_token",
                }
            ],
        },
    }

    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    targets = [
        target
        for query in plan.queries
        for target in query.labeled_dimension_targets
    ]
    assert [
        (item.source_item_index, item.source_text, item.value)
        for item in targets
    ] == [
        (4, "S- 4.5 mm", 4.5),
        (5, "H3 - 12 mm", 12.0),
        (10, "fl - 3 mmx", 3.0),
    ]


def test_structural_query_builder_rejects_ambiguous_primary_token_fallback():
    reader_input = _reader_input_with_labeled_dimension_regions()
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 10,
                    "text": "f1 - 3 mmx",
                    "bbox": [
                        [70, 250],
                        [180, 250],
                        [180, 275],
                        [70, 275],
                    ],
                    "primary_tokens": ["3", "30"],
                    "reason": "not_one_standalone_linear_token",
                }
            ]
        },
    }

    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    assert all(
        not query.labeled_dimension_targets
        for query in plan.queries
    )


def test_labeled_dimension_candidate_region_provenance_resolves_overlapping_regions():
    reader_input = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R2",
                "crop_path": "C:/work/R2.png",
                "source_bbox_px": [337, 138, 793, 496],
            },
            {
                "region_id": "R3",
                "crop_path": "C:/work/R3.png",
                "source_bbox_px": [432, 88, 592, 211],
            },
        ],
    }
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "candidates": [
            {
                "candidate_id": "DG122",
                "region_id": "R3",
                "source_region_ids": ["R3"],
            }
        ],
        "coverage": {
            "unconfirmed_proposal_observations": [
                {
                    "source_item_index": 4,
                    "text": "S- 4.5 mm",
                    "bbox": [
                        [416.0, 162.0],
                        [538.0, 162.0],
                        [538.0, 192.0],
                        [416.0, 192.0],
                    ],
                    "primary_tokens": ["4.5"],
                    "token": "4.5",
                    "candidate_id": "DG122",
                    "reason": "candidate_line_is_extension_witness_of_accepted_dimension",
                }
            ]
        },
    }

    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    by_region = {
        query.region_id: query.labeled_dimension_targets
        for query in plan.queries
    }
    assert by_region["R2"] == []
    assert len(by_region["R3"]) == 1
    assert by_region["R3"][0].target_id == "LD_0004"
    assert by_region["R3"][0].value == 4.5


def test_labeled_dimension_ambiguous_candidate_region_still_fails_closed():
    reader_input = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R2",
                "crop_path": "C:/work/R2.png",
                "source_bbox_px": [337, 138, 793, 496],
            },
            {
                "region_id": "R3",
                "crop_path": "C:/work/R3.png",
                "source_bbox_px": [432, 88, 592, 211],
            },
        ],
    }
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "candidates": [
            {
                "candidate_id": "DG122",
                "region_id": "R3",
                "source_region_ids": ["R2", "R3"],
            }
        ],
        "coverage": {
            "unconfirmed_proposal_observations": [
                {
                    "source_item_index": 4,
                    "text": "S- 4.5 mm",
                    "bbox": [
                        [416.0, 162.0],
                        [538.0, 162.0],
                        [538.0, 192.0],
                        [416.0, 192.0],
                    ],
                    "primary_tokens": ["4.5"],
                    "token": "4.5",
                    "candidate_id": "DG122",
                    "reason": "candidate_line_is_extension_witness_of_accepted_dimension",
                }
            ]
        },
    }

    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    assert all(
        not query.labeled_dimension_targets
        for query in plan.queries
    )


def _write_short_dimension_direction_fixture(
    tmp_path: Path,
    *,
    witness_orientation: str,
) -> tuple[str, list[list[float]]]:
    import cv2
    import numpy as np

    image = np.full((300, 420), 255, np.uint8)
    bbox = [
        [120.0, 120.0],
        [220.0, 120.0],
        [220.0, 150.0],
        [120.0, 150.0],
    ]
    if witness_orientation == "vertical":
        cv2.line(image, (185, 155), (185, 235), 0, 2)
        cv2.line(image, (210, 155), (210, 235), 0, 2)
    elif witness_orientation == "horizontal":
        cv2.line(image, (225, 125), (310, 125), 0, 2)
        cv2.line(image, (225, 165), (310, 165), 0, 2)
    else:
        raise AssertionError(witness_orientation)

    path = tmp_path / f"short-{witness_orientation}.png"
    assert cv2.imwrite(str(path), image)
    return str(path), bbox


@pytest.mark.parametrize(
    ("witness_orientation", "expected_direction"),
    [
        ("vertical", "horizontal"),
        ("horizontal", "vertical"),
    ],
)
def test_structural_labeled_dimension_uses_deterministic_short_direction(
    tmp_path: Path,
    witness_orientation: str,
    expected_direction: str,
):
    source_raster, bbox = _write_short_dimension_direction_fixture(
        tmp_path,
        witness_orientation=witness_orientation,
    )
    reader_input = _reader_input_with_labeled_dimension_regions()
    report = _hybrid_report_with_labeled_unassigned_dimension()
    report["source_raster"] = source_raster
    report["coverage"]["unassigned_linear_observations"][0]["bbox"] = bbox

    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    target = next(
        target
        for query in plan.queries
        for target in query.labeled_dimension_targets
        if target.target_id == "LD_0017"
    )
    assert target.deterministic_visual_direction == expected_direction
    assert plan.rules["labeled_dimension_direction_from_topology_only"] is True
    assert plan.rules["labeled_dimension_direction_hint_must_be_preserved"] is True


def test_structural_context_rejects_visual_direction_against_deterministic_hint(
    tmp_path: Path,
):
    source_raster, bbox = _write_short_dimension_direction_fixture(
        tmp_path,
        witness_orientation="horizontal",
    )
    reader_input = _reader_input_with_labeled_dimension_regions()
    report = _hybrid_report_with_labeled_unassigned_dimension()
    report["source_raster"] = source_raster
    report["coverage"]["unassigned_linear_observations"][0]["bbox"] = bbox
    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][0]["labeled_dimension_decisions"] = [
        {
            "target_id": "LD_0017",
            "status": "resolved",
            "visual_direction": "horizontal",
            "relation": "between_profile_boundaries",
            "profile_transition_geometry": "orthogonal",
            "symmetry_scope": "bilateral",
            "evidence": ["structural:R1:crop"],
            "reason": None,
        }
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(
        StructuralContextError,
        match="visual direction conflicts with deterministic short-dimension topology",
    ):
        assemble_structural_context(plan, answers)
