from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nx_mcp.drawing_intelligence.structural_context import (
    StructuralCompactVisualAnswers,
    StructuralContextAnswers,
    StructuralContextError,
    StructuralContextQueryPlan,
    StructuralOverallFact,
    StructuralRegionAnswer,
    StructuralRegionQuery,
    assemble_structural_context,
    build_structural_context_queries,
    compose_structural_visual_answers,
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
    assert "多个 query 若共享同一路径，只打开该共享图一次" in skill


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


def _compact_answers() -> StructuralCompactVisualAnswers:
    return StructuralCompactVisualAnswers.model_validate(
        {
            "schema": "structural-visual-decisions-v1",
            "decisions": [
                {
                    "query_id": "S001",
                    "view_kind": "front",
                    "overall_dimension_facts": [
                        {"axis": "X", "value": 40},
                        {"axis": "Z", "value": 66},
                    ],
                    "rotational_symmetry": {"status": "not_established"},
                },
                {
                    "query_id": "S002",
                    "view_kind": "side",
                    "overall_dimension_facts": [{"axis": "Y", "value": 32}],
                    "rotational_symmetry": {"status": "not_established"},
                },
            ],
        }
    )


def test_compact_rotational_decision_basis_requires_exclusive_fields():
    # Regression: a Fresh axial-section decision cannot also claim a drawn
    # centerline direction, even before the canonical answer is assembled.
    valid = [
        {"status": "established", "basis": "centerline",
         "centerline_direction": "vertical"},
        {"status": "established", "basis": "axial_section_symmetry"},
        {"status": "not_established"},
    ]
    for decision in valid:
        payload = {
            "schema": "structural-visual-decisions-v1",
            "decisions": [{"query_id": "S001", "rotational_symmetry": decision}],
        }
        visual = StructuralCompactVisualAnswers.model_validate(payload)
        assert visual.decisions[0].rotational_symmetry.status == decision["status"]

    invalid = [
        {"status": "established", "basis": "axial_section_symmetry",
         "centerline_direction": "vertical"},
        {"status": "established", "basis": "centerline"},
        {"status": "established"},
        {"status": "not_established", "basis": "centerline",
         "centerline_direction": "horizontal"},
    ]
    for decision in invalid:
        payload = {
            "schema": "structural-visual-decisions-v1",
            "decisions": [{"query_id": "S001", "rotational_symmetry": decision}],
        }
        with pytest.raises(ValidationError):
            StructuralCompactVisualAnswers.model_validate(payload)


def test_fresh_skill_lists_mutually_exclusive_rotational_decision_shapes():
    skill = (
        Path(__file__).resolve().parents[1]
        / "skills" / "nx-agent" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert '"basis":"axial_section_symmetry"}' in skill
    assert "绝对禁止携带 `centerline_direction`" in skill
    assert '"status":"not_established"}' in skill
    assert "第一次落盘前检查" in skill
    assert "首次 resume 失败后修 JSON 重试" in skill


def test_compact_labeled_relation_resolved_requires_direction_and_relation():
    # Regression from 220020: a pending C2-style target cannot be marked
    # resolved with no arrow direction. The compact input must fail before
    # composing/serializing any full structural answer.
    def validate(decision):
        payload = {
            "schema": "structural-visual-decisions-v1",
            "decisions": [
                {"query_id": "S004", "labeled_dimension_decisions": [decision]}
            ],
        }
        return StructuralCompactVisualAnswers.model_validate(payload)

    valid_resolved = validate({
        "target_id": "LD_0011", "status": "resolved",
        "visual_direction": "vertical",
        "relation": "between_profile_boundaries",
    })
    assert valid_resolved.decisions[0].labeled_dimension_decisions[0].relation == (
        "between_profile_boundaries"
    )
    valid_unresolved = validate({
        "target_id": "LD_0011", "status": "unresolved",
        "reason": "dimension arrow direction not established from visual evidence",
    })
    assert valid_unresolved.decisions[0].labeled_dimension_decisions[0].reason

    invalid = [
        {"target_id": "LD_0011", "status": "resolved"},
        {"target_id": "LD_0011", "status": "resolved",
         "relation": "between_profile_boundaries", "visual_direction": None},
        {"target_id": "LD_0011", "status": "resolved",
         "visual_direction": "vertical", "relation": None},
        {"target_id": "LD_0011", "status": "resolved",
         "visual_direction": "vertical", "relation": "overall_extent",
         "profile_transition_geometry": "orthogonal"},
        {"target_id": "LD_0011", "status": "resolved",
         "visual_direction": "vertical", "relation": "between_profile_boundaries",
         "reason": "uncertain"},
        {"target_id": "LD_0011", "status": "unresolved"},
        {"target_id": "LD_0011", "status": "unresolved",
         "visual_direction": "vertical", "reason": "uncertain"},
        {"target_id": "LD_0011", "status": "unresolved",
         "relation": "between_profile_boundaries", "reason": "uncertain"},
    ]
    for decision in invalid:
        with pytest.raises(ValidationError):
            validate(decision)


def test_fresh_skill_forbids_labeled_resolved_with_missing_direction():
    text = (
        Path(__file__).resolve().parents[1]
        / "skills" / "nx-agent" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "4d. **精简标注尺寸决策的互斥字段契约" in text
    assert '"visual_direction":"vertical","relation":"between_profile_boundaries"' in text
    assert '"status":"unresolved","reason":"' in text
    assert "未确定箭头方向时不得填写 resolved" in text
    assert "首次 resume 失败后不得修改文件重试" in text


def test_machine_composes_minimal_visual_responses_with_provenance():
    plan = build_structural_context_queries(_reader_input())
    answers = compose_structural_visual_answers(plan, _compact_answers())
    assert answers.model_dump(mode="json", by_alias=True) == _answers().model_dump(
        mode="json", by_alias=True
    )
    context = assemble_structural_context(plan, answers)
    assert len(context.region_views) == 2
    assert len(context.overall_dimension_facts) == 3


@pytest.mark.parametrize(
    "failure", ["missing_region", "extra_region", "duplicate_region"],
)
def test_machine_composer_rejects_incomplete_or_extra_queries(failure):
    plan = build_structural_context_queries(_reader_input())
    payload = _compact_answers().model_dump(mode="json", by_alias=True)
    if failure == "missing_region":
        payload["decisions"].pop()
    elif failure == "extra_region":
        payload["decisions"].append(
            {"query_id": "S999", "view_kind": "top"}
        )
    elif failure == "duplicate_region":
        payload["decisions"].append(dict(payload["decisions"][0]))
    with pytest.raises(StructuralContextError, match="compact visual query"):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(payload)
        )


def _compact_seed_echo_fixture():
    """Synthetic Reader-seeded target alongside a genuinely pending target."""
    from nx_mcp.drawing_intelligence.structural_context import (
        StructuralLabeledDimensionTarget,
    )

    plan = build_structural_context_queries(
        _reader_input_with_labeled_dimension_regions(),
        hybrid_report=_hybrid_report_with_labeled_unassigned_dimension(),
    )
    seeded = plan.queries[0].labeled_dimension_targets[0]
    assert seeded.target_id == "LD_0017"
    seeded.deterministic_visual_direction = "horizontal"
    seeded.deterministic_relation_seed = "between_profile_boundaries"

    pending = StructuralLabeledDimensionTarget(
        target_id="LD_0023",
        source_item_index=23,
        source_text="Q4 - 18 mm",
        value=18,
    )
    plan.queries[0].labeled_dimension_targets.append(pending)

    entries = plan.answer_template["answers"][0]["labeled_dimension_decisions"]
    entries[0]["status"] = "resolved"
    entries[0]["visual_direction"] = "horizontal"
    entries[0]["relation"] = "between_profile_boundaries"
    entries[0]["reason"] = None
    entries.append(
        {
            "target_id": pending.target_id,
            "status": "unresolved",
            "visual_direction": None,
            "relation": None,
            "profile_transition_geometry": None,
            "symmetry_scope": None,
            "evidence": ["structural:R1:crop"],
            "reason": "pending_labeled_dimension_relation_read",
        }
    )
    compact = _compact_answers().model_dump(mode="json", by_alias=True)
    compact["decisions"][0]["labeled_dimension_decisions"] = [
        {
            "target_id": "LD_0017",
            "status": "resolved",
            "visual_direction": "horizontal",
            "relation": "between_profile_boundaries",
        },
        {
            "target_id": "LD_0023",
            "status": "resolved",
            "visual_direction": "vertical",
            "relation": "between_profile_boundaries",
        },
    ]
    return plan, compact


def test_compact_exact_seed_echo_ignored_while_pending_target_preserved():
    plan, payload = _compact_seed_echo_fixture()
    answers = compose_structural_visual_answers(
        plan, StructuralCompactVisualAnswers.model_validate(payload)
    )
    seeded, pending = answers.answers[0].labeled_dimension_decisions
    assert seeded.target_id == "LD_0017"
    assert seeded.status == "resolved"
    assert seeded.visual_direction == "horizontal"
    assert seeded.relation == "between_profile_boundaries"
    assert seeded.profile_transition_geometry is None
    assert seeded.symmetry_scope is None
    assert seeded.evidence == ["structural:R1:crop"]
    assert pending.target_id == "LD_0023"
    assert pending.status == "resolved"
    assert pending.visual_direction == "vertical"
    assert pending.relation == "between_profile_boundaries"
    context = assemble_structural_context(plan, answers)
    by_id = {fact.target_id: fact for fact in context.labeled_dimension_facts}
    assert set(by_id) == {"LD_0017", "LD_0023"}
    assert by_id["LD_0017"].value == 12
    assert by_id["LD_0023"].value == 18


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("seed_direction_changed", "overrides deterministic labeled relation seed"),
        ("seed_relation_changed", "overrides deterministic labeled relation seed"),
        ("seed_unresolved", "overrides deterministic labeled relation seed"),
        ("seed_extra_metadata", "overrides deterministic labeled relation seed"),
        ("missing_pending", "compact labeled coverage mismatch"),
        ("extra_unknown", "compact labeled coverage mismatch"),
        ("duplicate_seed", "repeats compact labeled decision"),
    ],
)
def test_compact_seed_echo_cannot_override_reader_or_hide_pending(
    case: str, expected_error: str
):
    plan, payload = _compact_seed_echo_fixture()
    decisions = payload["decisions"][0]["labeled_dimension_decisions"]
    seeded = decisions[0]
    if case == "seed_direction_changed":
        seeded["visual_direction"] = "vertical"
    elif case == "seed_relation_changed":
        seeded["relation"] = "overall_extent"
    elif case == "seed_unresolved":
        seeded.update(
            status="unresolved", visual_direction=None,
            relation=None, reason="changed",
        )
    elif case == "seed_extra_metadata":
        seeded["symmetry_scope"] = "bilateral"
    elif case == "missing_pending":
        decisions.pop(1)
    elif case == "extra_unknown":
        decisions.append(
            {
                "target_id": "LD_0099",
                "status": "resolved",
                "visual_direction": "vertical",
                "relation": "overall_extent",
            }
        )
    else:
        decisions.append(dict(seeded))
    with pytest.raises(StructuralContextError, match=expected_error):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(payload)
        )


def test_compact_seed_echo_cannot_supply_engineering_value():
    plan, payload = _compact_seed_echo_fixture()
    payload["decisions"][0]["labeled_dimension_decisions"][0]["value"] = 500
    with pytest.raises(ValidationError, match="extra_forbidden"):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(payload)
        )


def test_machine_composer_preserves_proven_ocr_view():
    reader, report = _view_label_fixture()
    plan = build_structural_context_queries(reader, hybrid_report=report)
    payload = {
        "schema": "structural-visual-decisions-v1",
        "decisions": [
            {
                "query_id": "S001",
                "overall_dimension_facts": [
                    {"axis": "X", "value": 40},
                    {"axis": "Z", "value": 66},
                ],
                "rotational_symmetry": {"status": "not_established"},
            }
        ],
    }
    answers = compose_structural_visual_answers(
        plan, StructuralCompactVisualAnswers.model_validate(payload)
    )
    assert answers.answers[0].view_kind == "front"
    assert answers.answers[1].view_kind is None
    assert answers.answers[1].unresolved == ["non_geometric_reference_region"]

    payload["decisions"][0]["view_kind"] = "top"
    with pytest.raises(StructuralContextError, match="overrides deterministic OCR view"):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(payload)
        )


def test_machine_composer_does_not_invent_missing_rotation():
    plan = build_structural_context_queries(_reader_input())
    payload = _compact_answers().model_dump(mode="json", by_alias=True)
    payload["decisions"][0].pop("rotational_symmetry")
    with pytest.raises(ValidationError, match="rotational symmetry"):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(payload)
        )


def test_machine_composer_forbids_missing_labeled_target_decision():
    plan = build_structural_context_queries(_reader_input())
    query = plan.queries[0]
    from nx_mcp.drawing_intelligence.structural_context import (
        StructuralLabeledDimensionTarget,
    )

    query.labeled_dimension_targets.append(
        StructuralLabeledDimensionTarget(
            target_id="LD_0042",
            source_item_index=42,
            source_text="H- 12 mm",
            value=12.0,
            deterministic_visual_direction="horizontal",
        )
    )
    plan.answer_template["answers"][0]["labeled_dimension_decisions"].append(
        {
            "target_id": "LD_0042",
            "status": "unresolved",
            "visual_direction": None,
            "relation": None,
            "profile_transition_geometry": None,
            "symmetry_scope": None,
            "evidence": ["structural:R1:crop"],
            "reason": "pending_labeled_dimension_relation_read",
        }
    )
    payload = _compact_answers().model_dump(mode="json", by_alias=True)
    with pytest.raises(StructuralContextError, match="compact labeled coverage mismatch"):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(payload)
        )
    payload["decisions"][0]["labeled_dimension_decisions"] = [
        {
            "target_id": "LD_0042",
            "status": "resolved",
            "visual_direction": "vertical",
            "relation": "between_profile_boundaries",
        }
    ]
    with pytest.raises(StructuralContextError, match="conflicts with deterministic topology"):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(payload)
        )
    payload["decisions"][0]["labeled_dimension_decisions"][0]["visual_direction"] = "horizontal"
    answers = compose_structural_visual_answers(
        plan, StructuralCompactVisualAnswers.model_validate(payload)
    )
    assert answers.answers[0].labeled_dimension_decisions[0].evidence == [
        "structural:R1:crop"
    ]


def test_structural_query_builder_only_requests_region_structure():
    plan = build_structural_context_queries(_reader_input())

    assert [item.region_id for item in plan.queries] == ["R1", "R2"]
    assert plan.queries[0].image_path.endswith("R1.png")
    assert plan.queries[0].evidence_label == "structural:R1:crop"
    assert plan.rules["structural_query_images_may_be_shared"] is True
    assert plan.rules["deduplicate_identical_query_image_paths"] is True
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


def _reference_fixture() -> tuple[dict, dict]:
    reader = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R1", "crop_path": "C:/work/R1.png",
                "source_bbox_px": [0, 0, 240, 240],
                "circle_group_count": 1, "linear_pattern_candidate_count": 0,
                "candidate_overlay_count": 0,
            },
            {
                "region_id": "R2", "crop_path": "C:/work/R2.png",
                "source_bbox_px": [300, 0, 240, 240],
                "circle_group_count": 0, "linear_pattern_candidate_count": 0,
                "candidate_overlay_count": 0,
            },
        ],
    }
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2", "coverage": {},
        "candidates": [], "structural_profile_inventory": [],
        "whole_drawing_items": [
            {"text": "PARTS LIST",
             "bbox": [[310, 20], [415, 20], [415, 38], [310, 38]]},
            {"text": "MATERIAL",
             "bbox": [[310, 45], [430, 45], [430, 63], [310, 63]]},
        ],
    }
    return reader, report


def test_reader_owns_explicit_non_geometric_reference_detection():
    reader, report = _reference_fixture()
    plan = build_structural_context_queries(reader, hybrid_report=report)
    assert plan.queries[0].deterministic_non_geometric_reference is False
    assert plan.queries[1].deterministic_non_geometric_reference is True
    answers = StructuralContextAnswers.model_validate(plan.answer_template)
    assert answers.answers[0].unresolved == ["pending_structural_visual_read"]
    assert answers.answers[1].unresolved == ["non_geometric_reference_region"]


@pytest.mark.parametrize(
    "failure",
    [
        "missing_title", "unknown_geometry_inventory", "profile_present",
        "candidate_present", "circle_present", "target_present",
        "overlapping_region",
    ],
)
def test_reader_reference_classifier_stays_fail_closed(failure):
    reader, report = _reference_fixture()
    region = reader["regions"][1]
    if failure == "missing_title":
        report["whole_drawing_items"][0]["text"] = "12"
    elif failure == "unknown_geometry_inventory":
        region.pop("candidate_overlay_count")
    elif failure == "profile_present":
        report["structural_profile_inventory"].append({"region_id": "R2"})
    elif failure == "candidate_present":
        report["candidates"].append({"region_id": "R2"})
    elif failure == "circle_present":
        region["circle_group_count"] = 1
    elif failure == "target_present":
        report["coverage"]["unassigned_linear_observations"] = [
            {
                "source_item_index": 7, "text": "H- 12 mm", "token": "12",
                "bbox": [[350, 85], [440, 85], [440, 100], [350, 100]],
            }
        ]
    elif failure == "overlapping_region":
        reader["regions"][0]["source_bbox_px"] = [100, 0, 300, 240]
    plan = build_structural_context_queries(reader, hybrid_report=report)
    assert plan.queries[1].deterministic_non_geometric_reference is False



def _table_annotation_fixture() -> tuple[dict, dict]:
    """Independent synthetic geometry: no DN150 strings, dimensions or R3 rules."""
    reader = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "GEOMETRY", "crop_path": "C:/work/geometry.png",
                "source_bbox_px": [150, 200, 1250, 710],
                "circle_group_count": 0, "linear_pattern_candidate_count": 8,
                "candidate_overlay_count": 4,
            },
            {
                "region_id": "REFERENCE", "crop_path": "C:/work/ref.png",
                "source_bbox_px": [20, 1010, 1700, 210],
                "circle_group_count": 0, "linear_pattern_candidate_count": 12,
                "candidate_overlay_count": 6,
            },
            {
                "region_id": "ANNOTATION", "crop_path": "C:/work/top.png",
                "source_bbox_px": [450, 210, 750, 260],
                "circle_group_count": 0, "linear_pattern_candidate_count": 1,
                "candidate_overlay_count": 2,
            },
        ],
    }
    inventory = [
        {
            "region_id": "REFERENCE", "source_orientation": "horizontal",
            "span_px": [22, 1718],
        }
        for _ in range(3)
    ] + [
        {"region_id": "REFERENCE", "source_orientation": "vertical"}
        for _ in range(10)
    ]
    def text_item(value, left, top):
        return {
            "text": value,
            "bbox": [
                [left, top], [left + 45, top],
                [left + 45, top + 22], [left, top + 22],
            ],
        }
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {},
        "structural_profile_inventory": inventory,
        "whole_drawing_items": [
            text_item(f"COL{index}", 40 + index * 120, 1030)
            for index in range(9)
        ] + [
            text_item(str(100 + index), 40 + index * 120, 1100)
            for index in range(9)
        ],
        "candidates": [
            {
                "candidate_id": key,
                "region_id": "GEOMETRY",
                "source_region_ids": ["GEOMETRY", "ANNOTATION"],
                "axis_px": axis_px,
                "accepted_token": token,
            }
            for key, axis_px, token in (
                ("D_A", 221.0, "87"),
                ("D_B", 279.0, "75.4"),
            )
        ] + [
            {
                "candidate_id": "GRID_DIM",
                "region_id": "REFERENCE",
                "source_region_ids": ["REFERENCE"],
                "axis_px": 1120.0,
                "accepted_token": None,
            },
            {
                "candidate_id": "LOCAL_UNACCEPTED",
                "region_id": "ANNOTATION",
                "source_region_ids": ["ANNOTATION"],
                "axis_px": 300.0,
                "accepted_token": None,
            },
        ],
    }
    return reader, report


def test_reader_proves_table_and_annotation_view_owner_without_new_geometry():
    reader, report = _table_annotation_fixture()
    # Symmetric table grid and annotation witness lines may have false
    # profile symmetry hints; neither may become geometric rotation evidence.
    for region in reader["regions"][1:]:
        region["bilateral_symmetry_hint"] = {
            "status": "established",
            "axis_direction": "vertical",
            "method": "profile_edge_midpoint_consensus_v2",
        }
    plan = build_structural_context_queries(reader, hybrid_report=report)
    main, table, annotation = plan.queries
    assert not main.deterministic_non_geometric_reference
    assert table.deterministic_non_geometric_reference
    assert table.deterministic_profile_symmetry_axis is None
    assert annotation.deterministic_view_owner_region_id == "GEOMETRY"
    assert annotation.deterministic_view_kind is None
    assert plan.rules["annotation_view_owner_supplies_only_view_identity"] is True
    visual = StructuralCompactVisualAnswers.model_validate(
        {
            "schema": "structural-visual-decisions-v1",
            "decisions": [
                {
                    "query_id": main.query_id, "view_kind": "front",
                    "overall_dimension_facts": [
                        {"axis": "X", "value": 175},
                        {"axis": "Z", "value": 90},
                    ],
                    "rotational_symmetry": {
                        "status": "established", "basis": "centerline",
                        "centerline_direction": "vertical",
                    },
                },
            ],
        }
    )
    answers = compose_structural_visual_answers(plan, visual)
    assert answers.answers[1].view_kind is None
    assert answers.answers[1].unresolved == ["non_geometric_reference_region"]
    assert answers.answers[2].view_kind == "front"
    assert answers.answers[2].rotational_symmetry is None
    assert answers.answers[2].overall_dimension_facts == []
    assert answers.answers[2].unresolved == ["rotational_symmetry_not_visible_in_region"]
    assert answers.answers[2].evidence == ["structural:ANNOTATION:crop"]


@pytest.mark.parametrize(
    "counterexample",
    ["missing_grid", "missing_row", "accepted_grid_value",
     "cross_region_grid_candidate", "circle_geometry", "bad_alignment"],
)
def test_grid_reference_proof_rejects_weak_or_conflicting_evidence(counterexample):
    reader, report = _table_annotation_fixture()
    table = reader["regions"][1]
    if counterexample == "missing_grid":
        report["structural_profile_inventory"] = []
    elif counterexample == "missing_row":
        report["whole_drawing_items"] = report["whole_drawing_items"][:9]
    elif counterexample == "accepted_grid_value":
        report["candidates"][-2]["accepted_token"] = "900"
    elif counterexample == "cross_region_grid_candidate":
        report["candidates"][-2]["source_region_ids"] = [
            "REFERENCE", "GEOMETRY",
        ]
    elif counterexample == "circle_geometry":
        table["circle_group_count"] = 1
    else:
        for item in report["whole_drawing_items"][9:]:
            item["bbox"] = [
                [a + 58, b] for a, b in item["bbox"]
            ]
    query = build_structural_context_queries(
        reader, hybrid_report=report
    ).queries[1]
    assert query.deterministic_non_geometric_reference is False


def _annotation_with_labeled_target_fixture():
    reader, report = _table_annotation_fixture()
    report["source_raster"] = "C:/synthetic/source.png"
    report["coverage"]["unassigned_linear_observations"] = [{
        "source_item_index": 901,
        "text": "H9 - 24 mm",
        "token": "24",
        "bbox": [[900, 260], [1040, 260], [1040, 280], [900, 280]],
        "candidate_id": "LOCAL_LABEL",
    }]
    report["candidates"].append({
        "candidate_id": "LOCAL_LABEL",
        "region_id": "ANNOTATION",
        "source_region_ids": ["ANNOTATION"],
        "axis_px": 310.0,
        "accepted_token": None,
    })
    return reader, report


def test_proven_annotation_owner_preserves_all_seeded_targets(monkeypatch):
    from nx_mcp.drawing_intelligence import structural_context as structural

    reader, report = _annotation_with_labeled_target_fixture()
    monkeypatch.setattr(
        structural, "infer_short_dimension_visual_direction",
        lambda *_: "vertical",
    )
    monkeypatch.setattr(
        structural, "_deterministic_labeled_relation_seed",
        lambda **_: "between_profile_boundaries",
    )
    plan = build_structural_context_queries(reader, hybrid_report=report)
    main, reference, annotation = plan.queries
    assert reference.deterministic_non_geometric_reference is True
    assert annotation.deterministic_view_owner_region_id == main.region_id
    assert len(annotation.labeled_dimension_targets) == 1
    assert annotation.labeled_dimension_targets[0].deterministic_relation_seed == (
        "between_profile_boundaries"
    )
    visual = StructuralCompactVisualAnswers.model_validate({
        "schema": "structural-visual-decisions-v1",
        "decisions": [{
            "query_id": main.query_id,
            "view_kind": "front",
            "overall_dimension_facts": [
                {"axis": "X", "value": 175},
                {"axis": "Z", "value": 90},
            ],
            "rotational_symmetry": {
                "status": "established",
                "basis": "centerline",
                "centerline_direction": "vertical",
            },
        }],
    })
    answers = compose_structural_visual_answers(plan, visual)
    retained = answers.answers[2]
    assert retained.view_kind == "front"
    assert retained.rotational_symmetry is None
    assert retained.unresolved == ["rotational_symmetry_not_visible_in_region"]
    assert len(retained.labeled_dimension_decisions) == 1
    labeled = retained.labeled_dimension_decisions[0]
    assert labeled.status == "resolved"
    assert labeled.relation == "between_profile_boundaries"
    assert labeled.visual_direction == "vertical"
    assert labeled.evidence == ["structural:ANNOTATION:crop"]


@pytest.mark.parametrize("counterexample", ["pending_target", "missing_cross_link"])
def test_annotation_owner_never_skips_pending_target_or_missing_proof(
    monkeypatch, counterexample
):
    from nx_mcp.drawing_intelligence import structural_context as structural

    reader, report = _annotation_with_labeled_target_fixture()
    monkeypatch.setattr(
        structural, "infer_short_dimension_visual_direction",
        lambda *_: "vertical",
    )
    monkeypatch.setattr(
        structural, "_deterministic_labeled_relation_seed",
        lambda **_: (
            None if counterexample == "pending_target"
            else "between_profile_boundaries"
        ),
    )
    monkeypatch.setattr(
        structural, "_proven_labeled_vertical_overall", lambda **_: False,
    )
    if counterexample == "missing_cross_link":
        report["candidates"].pop(1)
    plan = build_structural_context_queries(reader, hybrid_report=report)
    annotation = plan.queries[2]
    assert len(annotation.labeled_dimension_targets) == 1
    assert annotation.deterministic_view_owner_region_id is None


@pytest.mark.parametrize(
    "counterexample",
    ["single_dimension", "unaccepted_dimension", "local_accepted",
     "no_overlap", "ambiguous_owner", "real_circle", "same_dimension_axis"],
)
def test_annotation_owner_requires_unique_accepted_cross_region_identity(counterexample):
    reader, report = _table_annotation_fixture()
    annotation = reader["regions"][2]
    if counterexample == "single_dimension":
        report["candidates"].pop(1)
    elif counterexample == "unaccepted_dimension":
        report["candidates"][1]["accepted_token"] = None
    elif counterexample == "local_accepted":
        report["candidates"][-1]["accepted_token"] = "20"
    elif counterexample == "no_overlap":
        annotation["source_bbox_px"] = [1500, 210, 170, 200]
    elif counterexample == "ambiguous_owner":
        report["candidates"].extend([
            {
                "candidate_id": "COMPETE_1", "region_id": "OTHER",
                "source_region_ids": ["OTHER", "ANNOTATION"],
                "axis_px": 321.0, "accepted_token": "45",
            },
        ])
    elif counterexample == "real_circle":
        annotation["circle_group_count"] = 1
    else:
        report["candidates"][1]["axis_px"] = 221.0
    query = build_structural_context_queries(
        reader, hybrid_report=report
    ).queries[2]
    assert query.deterministic_view_owner_region_id is None


def test_reader_owned_regions_ignore_only_benign_legacy_compact_records():
    reader, report = _table_annotation_fixture()
    plan = build_structural_context_queries(reader, hybrid_report=report)
    visual = {
        "schema": "structural-visual-decisions-v1",
        "decisions": [
            {
                "query_id": "S001", "view_kind": "front",
                "rotational_symmetry": {"status": "not_established"},
            },
            {
                "query_id": "S002",
                "view_kind": None,
                "rotational_symmetry": None,
                "unresolved": ["non_geometric_reference_region"],
            },
            {
                "query_id": "S003",
                "view_kind": None,
                "rotational_symmetry": None,
                "unresolved": ["rotational_symmetry_not_visible_in_region"],
            },
        ],
    }
    answers = compose_structural_visual_answers(
        plan, StructuralCompactVisualAnswers.model_validate(visual)
    )
    assert answers.answers[2].view_kind == "front"
    assert answers.answers[2].rotational_symmetry is None
    assert answers.answers[2].overall_dimension_facts == []
    visual["decisions"][1]["overall_dimension_facts"] = [
        {"axis": "X", "value": 12},
    ]
    with pytest.raises(StructuralContextError, match="overrides Reader-owned"):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(visual)
        )


def test_compact_annotation_cannot_inject_an_independent_view_decision():
    reader, report = _table_annotation_fixture()
    plan = build_structural_context_queries(reader, hybrid_report=report)
    payload = {
        "schema": "structural-visual-decisions-v1",
        "decisions": [
            {
                "query_id": "S001", "view_kind": "front",
                "rotational_symmetry": {"status": "not_established"},
            },
            {
                "query_id": "S003", "view_kind": "top",
                "rotational_symmetry": {"status": "not_established"},
            },
        ],
    }
    with pytest.raises(StructuralContextError, match="overrides Reader-owned region"):
        compose_structural_visual_answers(
            plan, StructuralCompactVisualAnswers.model_validate(payload)
        )


def _material_contact_fixture() -> tuple[dict, dict]:
    """An unrelated axial part with an exterior vertical length callout."""
    reader = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "BODY",
                "crop_path": "C:/work/body.png",
                "source_bbox_px": [70, 30, 700, 570],
                "circle_group_count": 0,
                "linear_pattern_candidate_count": 1,
                "candidate_overlay_count": 1,
            },
            {
                "region_id": "DIMENSIONS",
                "crop_path": "C:/work/callout.png",
                "source_bbox_px": [760, 100, 220, 380],
                "circle_group_count": 0,
                "linear_pattern_candidate_count": 0,
                "candidate_overlay_count": 1,
            },
        ],
    }
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "source_raster": "synthetic-drawing.png",
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 42,
                    "text": "T - 62 mm",
                    "token": "62",
                    "primary_tokens": ["62"],
                    "bbox": [[820, 295], [915, 295], [915, 327], [820, 327]],
                    "reason": "no_unique_DG_assignment",
                },
            ]
        },
        "candidates": [],
        "structural_profile_inventory": [
            {
                "kind": "profile_edge_candidate",
                "region_id": "BODY",
                "ref": "body-top",
                "source_orientation": "horizontal",
                "position_px": 120,
                "span_px": [160, 620],
                "one_sided_boundary_candidate": True,
                "material_side_index": 1,
                "background_side_index": 0,
                "independent_geometry_source_count": 3,
                "junction_tolerance_px": 12,
            },
            {
                "kind": "profile_edge_candidate",
                "region_id": "BODY",
                "ref": "body-bottom",
                "source_orientation": "horizontal",
                "position_px": 500,
                "span_px": [140, 640],
                "one_sided_boundary_candidate": True,
                "material_side_index": 0,
                "background_side_index": 1,
                "independent_geometry_source_count": 3,
                "junction_tolerance_px": 12,
            },
        ],
    }
    return reader, report


def test_labeled_vertical_overall_with_actual_dimension_line_raster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Exercise the raster axis helper, not a mocked dimensions result."""
    import cv2
    import numpy as np
    from nx_mcp.drawing_intelligence import structural_context as sc

    reader, report = _material_contact_fixture()
    canvas = np.full((700, 1100), 255, np.uint8)
    cv2.rectangle(canvas, (160, 120), (620, 500), 180, -1)
    cv2.line(canvas, (160, 120), (620, 120), 0, 2)
    cv2.line(canvas, (160, 500), (620, 500), 0, 2)
    cv2.line(canvas, (620, 120), (815, 120), 0, 2)
    cv2.line(canvas, (620, 500), (815, 500), 0, 2)
    cv2.line(canvas, (815, 120), (815, 500), 0, 2)
    raster = tmp_path / "independent_axial_part.png"
    assert cv2.imwrite(str(raster), canvas)
    report["source_raster"] = str(raster)

    monkeypatch.setattr(
        sc, "infer_short_dimension_visual_direction",
        lambda *_args, **_kwargs: None,
    )
    plan = build_structural_context_queries(reader, hybrid_report=report)
    target = plan.queries[1].labeled_dimension_targets[0]
    assert target.deterministic_visual_direction == "vertical"
    assert target.deterministic_relation_seed == "overall_extent"


def test_material_boundaries_prove_reader_owned_labeled_global_overall(
    monkeypatch: pytest.MonkeyPatch,
):
    from nx_mcp.drawing_intelligence import structural_context as sc

    reader, report = _material_contact_fixture()
    monkeypatch.setattr(
        sc, "infer_labeled_dimension_axis_span",
        lambda *_args, **_kwargs: (121.0, 500.0),
    )
    monkeypatch.setattr(
        sc, "infer_short_dimension_visual_direction",
        lambda *_args, **_kwargs: None,
    )
    plan = build_structural_context_queries(reader, hybrid_report=report)
    target = plan.queries[1].labeled_dimension_targets[0]
    assert target.source_item_index == 42
    assert target.value == 62.0
    assert target.deterministic_visual_direction == "vertical"
    assert target.deterministic_relation_seed == "overall_extent"

    compact = StructuralCompactVisualAnswers.model_validate({
        "schema": "structural-visual-decisions-v1",
        "decisions": [
            {
                "query_id": "S001",
                "view_kind": "front",
                "overall_dimension_facts": [{"axis": "X", "value": 100}],
                "rotational_symmetry": {
                    "status": "established",
                    "basis": "centerline",
                    "centerline_direction": "vertical",
                },
            },
            {
                "query_id": "S002",
                "view_kind": "front",
                "rotational_symmetry": None,
                "unresolved": ["rotational_symmetry_not_visible_in_region"],
            },
        ],
    })
    answers = compose_structural_visual_answers(plan, compact)
    context = assemble_structural_context(plan, answers)
    assert {(f.axis, f.value) for f in context.overall_dimension_facts} == {
        ("X", 100), ("Z", 62),
    }
    assert [f.axis for f in context.rotational_symmetry_facts] == ["Z"]
    assert [(f.source_item_index, f.relation) for f in context.labeled_dimension_facts] == [
        (42, "overall_extent"),
    ]


@pytest.mark.parametrize(
    "failure",
    [
        "wrong_terminal", "missing_bottom", "same_material_side",
        "ambiguous_top", "insufficient_geometry", "short_surface",
        "distant_view", "conflicting_second_owner",
    ],
)
def test_material_boundary_overall_proof_stays_fail_closed(
    monkeypatch: pytest.MonkeyPatch, failure: str,
):
    from nx_mcp.drawing_intelligence import structural_context as sc

    reader, report = _material_contact_fixture()
    surfaces = report["structural_profile_inventory"]
    pair = (120.0, 500.0)
    if failure == "wrong_terminal":
        pair = (160.0, 500.0)
    elif failure == "missing_bottom":
        surfaces.pop()
    elif failure == "same_material_side":
        surfaces[1]["material_side_index"] = 1
        surfaces[1]["background_side_index"] = 0
    elif failure == "ambiguous_top":
        surfaces.append(dict(surfaces[0], ref="other-top"))
    elif failure == "insufficient_geometry":
        surfaces[0]["independent_geometry_source_count"] = 1
    elif failure == "short_surface":
        surfaces[0]["span_px"] = [200, 250]
    elif failure == "distant_view":
        reader["regions"][1]["source_bbox_px"] = [1500, 100, 220, 380]
        report["coverage"]["unassigned_linear_observations"][0]["bbox"] = [
            [1560, 295], [1655, 295], [1655, 327], [1560, 327],
        ]
    elif failure == "conflicting_second_owner":
        reader["regions"].insert(1, {
            "region_id": "OTHER",
            "crop_path": "C:/work/other.png",
            "source_bbox_px": [70, 30, 700, 570],
            "circle_group_count": 0,
            "linear_pattern_candidate_count": 1,
            "candidate_overlay_count": 1,
        })
        surfaces.extend([
            dict(edge, region_id="OTHER", ref=edge["ref"] + "-other")
            for edge in surfaces[:2]
        ])
    monkeypatch.setattr(
        sc, "infer_labeled_dimension_axis_span",
        lambda *_args, **_kwargs: pair,
    )
    monkeypatch.setattr(
        sc, "infer_short_dimension_visual_direction",
        lambda *_args, **_kwargs: None,
    )
    plan = build_structural_context_queries(reader, hybrid_report=report)
    targets = [
        t for q in plan.queries for t in q.labeled_dimension_targets
        if t.source_item_index == 42
    ]
    if targets:
        assert targets[0].deterministic_relation_seed is None


def _view_label_fixture() -> tuple[dict, dict]:
    reader, report = _reference_fixture()
    report["whole_drawing_items"].append(
        {
            "source_item_index": 29,
            "text": "FRONT VIEW",
            "bbox": [[12, 25], [125, 25], [125, 42], [12, 42]],
        }
    )
    return reader, report


def test_reader_owns_unique_explicit_ocr_view_caption():
    reader, report = _view_label_fixture()
    plan = build_structural_context_queries(reader, hybrid_report=report)
    first, second = plan.queries
    assert first.deterministic_view_kind == "front"
    assert first.deterministic_view_label_source_index == 29
    assert second.deterministic_view_kind is None
    assert second.deterministic_non_geometric_reference is True
    answers = StructuralContextAnswers.model_validate(plan.answer_template)
    assert answers.answers[0].view_kind == "front"
    assert answers.answers[0].rotational_symmetry is None
    assert answers.answers[0].unresolved == ["pending_structural_visual_read"]
    assert answers.answers[1].unresolved == ["non_geometric_reference_region"]
    assert plan.rules["explicit_ocr_view_title_is_reader_owned"] is True
    assert plan.rules["agent_must_preserve_deterministic_view_kind"] is True


@pytest.mark.parametrize(
    ("text", "expected_kind"),
    [
        ("FRONT VIEW", "front"),
        ("SIDE VIEW", "side"),
        ("TOP VIEW", "top"),
        ("主视图", "front"),
        ("左视图", "side"),
        ("俯视图", "top"),
    ],
)
def test_reader_accepts_explicit_multilingual_view_titles(text, expected_kind):
    reader, report = _view_label_fixture()
    report["whole_drawing_items"][-1]["text"] = text
    query = build_structural_context_queries(
        reader, hybrid_report=report
    ).queries[0]
    assert query.deterministic_view_kind == expected_kind


@pytest.mark.parametrize(
    "counterexample",
    [
        "missing_geometry", "unknown_label", "bad_bbox", "other_region_overlap",
        "conflicting_titles", "duplicate_title", "missing_source_index",
        "unassigned_bbox",
    ],
)
def test_reader_view_caption_fails_closed_on_ambiguous_evidence(counterexample):
    reader, report = _view_label_fixture()
    item = report["whole_drawing_items"][-1]
    if counterexample == "missing_geometry":
        reader["regions"][0]["circle_group_count"] = 0
    elif counterexample == "unknown_label":
        item["text"] = "FRONT?"
    elif counterexample == "bad_bbox":
        item["bbox"] = [[12, 25], [12, 25]]
    elif counterexample == "other_region_overlap":
        reader["regions"][1]["source_bbox_px"] = [50, 0, 290, 240]
    elif counterexample == "conflicting_titles":
        report["whole_drawing_items"].append({
            "source_item_index": 30, "text": "SIDE VIEW",
            "bbox": [[12, 50], [125, 50], [125, 67], [12, 67]],
        })
    elif counterexample == "duplicate_title":
        report["whole_drawing_items"].append({
            "source_item_index": 30, "text": "FRONT VIEW",
            "bbox": [[12, 50], [125, 50], [125, 67], [12, 67]],
        })
    elif counterexample == "missing_source_index":
        item.pop("source_item_index")
    elif counterexample == "unassigned_bbox":
        item["bbox"] = [[10, 230], [125, 230], [125, 260], [10, 260]]
    query = build_structural_context_queries(
        reader, hybrid_report=report
    ).queries[0]
    assert query.deterministic_view_kind is None
    assert query.deterministic_view_label_source_index is None


def test_reader_view_caption_cannot_be_changed_during_assembly():
    reader, report = _view_label_fixture()
    plan = build_structural_context_queries(reader, hybrid_report=report)
    answers = _answers().model_dump(mode="json", by_alias=True)
    answers["answers"][0]["view_kind"] = "top"
    with pytest.raises(
        StructuralContextError, match="changed deterministic OCR view kind"
    ):
        assemble_structural_context(
            plan, StructuralContextAnswers.model_validate(answers)
        )


def test_reader_reference_classification_cannot_be_overwritten_by_agent():
    reader, report = _reference_fixture()
    plan = build_structural_context_queries(reader, hybrid_report=report)
    payload = _answers().model_dump(mode="json", by_alias=True)
    payload["answers"][1]["unresolved"] = []
    with pytest.raises(StructuralContextError, match="changed deterministic reference classification"):
        assemble_structural_context(
            plan, StructuralContextAnswers.model_validate(payload)
        )


def test_structural_query_builder_prefers_shared_full_drawing_context_image():
    reader_input = _reader_input()
    reader_input["structural_context_overview_path"] = (
        "C:/work/structural-context-overview.png"
    )
    reader_input["regions"][0]["structural_context_path"] = (
        "C:/work/R1-structural-context.png"
    )
    reader_input["regions"][1]["structural_context_path"] = (
        "C:/work/R2-structural-context.png"
    )

    plan = build_structural_context_queries(reader_input)

    assert {
        item.image_path
        for item in plan.queries
    } == {"C:/work/structural-context-overview.png"}
    assert [item.evidence_label for item in plan.queries] == [
        "structural:R1:context",
        "structural:R2:context",
    ]
    template = StructuralContextAnswers.model_validate(plan.answer_template)
    assert [item.evidence for item in template.answers] == [
        ["structural:R1:context"],
        ["structural:R2:context"],
    ]


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


def test_structural_query_builder_accepts_profile_edge_symmetry_provenance():
    reader_input = _reader_input()
    reader_input["regions"][0]["bilateral_symmetry_hint"] = {
        "status": "established",
        "axis_direction": "vertical",
        "method": "profile_edge_midpoint_consensus_v2",
        "vertical_score": 1.0,
        "horizontal_score": 0.0,
        "score_margin": 1.0,
    }

    plan = build_structural_context_queries(reader_input)

    assert plan.queries[0].deterministic_profile_symmetry_axis == "vertical"
    assert (
        plan.queries[0].deterministic_profile_symmetry_method
        == "profile_edge_midpoint_consensus_v2"
    )


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


def test_non_geometric_reference_region_may_ignore_candidate_symmetry_hint():
    plan = build_structural_context_queries(_reader_input())
    plan_payload = plan.model_dump(mode="json", by_alias=True)
    plan_payload["queries"][1]["deterministic_profile_symmetry_axis"] = "vertical"
    plan_payload["queries"][1]["deterministic_profile_symmetry_method"] = (
        "profile_edge_midpoint_consensus_v2"
    )
    plan_payload["queries"][1]["deterministic_profile_symmetry_overlay"] = (
        "blue_dashed_topology_axis"
    )
    guarded_plan = StructuralContextQueryPlan.model_validate(plan_payload)

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
        guarded_plan,
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


def _labeled_overall_rotation_fixture(
    *,
    relation: str = "overall_extent",
    with_direct_z: bool = False,
) -> tuple[StructuralContextQueryPlan, StructuralContextAnswers]:
    """OCR value is 12; compact visual decision supplies no number."""
    plan = build_structural_context_queries(
        _reader_input_with_labeled_dimension_regions(),
        hybrid_report=_hybrid_report_with_labeled_unassigned_dimension(),
    )
    payload = _answers().model_dump(mode="json", by_alias=True)
    first, second = payload["answers"]
    first["overall_dimension_facts"] = [
        first["overall_dimension_facts"][0],
    ]
    if with_direct_z:
        first["overall_dimension_facts"].append({
            "axis": "Z",
            "value": 66,
            "evidence": ["structural:R1:crop"],
        })
    first["rotational_symmetry"] = {
        "status": "established",
        "basis": "centerline",
        "centerline_direction": "vertical",
        "evidence": ["structural:R1:crop"],
    }
    first["labeled_dimension_decisions"] = [{
        "target_id": "LD_0017",
        "status": "resolved",
        "visual_direction": "vertical",
        "relation": relation,
        "evidence": ["structural:R1:crop"],
        "reason": None,
    }]
    second["view_kind"] = "front"
    second["overall_dimension_facts"] = []
    second["rotational_symmetry"] = None
    second["unresolved"] = ["rotational_symmetry_not_visible_in_region"]
    return plan, StructuralContextAnswers.model_validate(payload)


def test_ocr_labeled_overall_dimension_closes_rotational_missing_axis():
    plan, answers = _labeled_overall_rotation_fixture()
    context = assemble_structural_context(plan, answers)

    by_axis = {fact.axis: fact for fact in context.overall_dimension_facts}
    assert set(by_axis) == {"X", "Z"}
    assert by_axis["X"].value == 40.0
    assert by_axis["Z"].value == 12.0
    assert by_axis["Z"].evidence == [
        "hybrid:whole:17", "structural:R1:crop",
    ]
    assert len(context.rotational_symmetry_facts) == 1
    assert context.rotational_symmetry_facts[0].axis == "Z"
    assert len(context.labeled_dimension_facts) == 1
    assert context.labeled_dimension_facts[0].value == 12.0
    assert context.labeled_dimension_facts[0].relation == "overall_extent"


def test_local_labeled_dimension_does_not_fill_missing_overall_axis():
    plan, answers = _labeled_overall_rotation_fixture(
        relation="between_profile_boundaries",
    )
    with pytest.raises(
        StructuralContextError, match="missing structural overall fact"
    ):
        assemble_structural_context(plan, answers)


def test_labeled_overall_conflicting_with_direct_overall_is_rejected():
    plan, answers = _labeled_overall_rotation_fixture(with_direct_z=True)
    with pytest.raises(
        StructuralContextError,
        match="labeled overall_extent conflicts with direct overall for axis Z",
    ):
        assemble_structural_context(plan, answers)


def test_multiple_labeled_overalls_on_one_axis_fail_closed():
    reader = _reader_input_with_labeled_dimension_regions()
    report = _hybrid_report_with_labeled_unassigned_dimension()
    report["coverage"]["unassigned_linear_observations"].append({
        "source_item_index": 23,
        "text": "Q4 - 18 mm",
        "bbox": [[52, 143], [135, 143], [135, 167], [52, 167]],
        "primary_tokens": ["18"],
        "token": "18",
        "reason": "no_unique_DG_assignment",
    })
    plan = build_structural_context_queries(reader, hybrid_report=report)
    assert len(plan.queries[0].labeled_dimension_targets) == 2
    payload = _answers().model_dump(mode="json", by_alias=True)
    first, second = payload["answers"]
    first["overall_dimension_facts"] = [first["overall_dimension_facts"][0]]
    first["rotational_symmetry"] = {
        "status": "established",
        "basis": "centerline",
        "centerline_direction": "vertical",
        "evidence": ["structural:R1:crop"],
    }
    first["labeled_dimension_decisions"] = [
        {
            "target_id": target.target_id,
            "status": "resolved",
            "visual_direction": "vertical",
            "relation": "overall_extent",
            "evidence": ["structural:R1:crop"],
            "reason": None,
        }
        for target in plan.queries[0].labeled_dimension_targets
    ]
    second["view_kind"] = "front"
    second["overall_dimension_facts"] = []
    second["rotational_symmetry"] = None
    second["unresolved"] = ["rotational_symmetry_not_visible_in_region"]
    with pytest.raises(
        StructuralContextError, match="ambiguous labeled overall_extent for axis Z"
    ):
        assemble_structural_context(
            plan, StructuralContextAnswers.model_validate(payload)
        )


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


def test_labeled_dimension_reassembles_unique_adjacent_label_and_value_unit():
    reader_input = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R4",
                "crop_path": "C:/work/R4.png",
                "source_bbox_px": [1400, 500, 260, 260],
            }
        ],
    }
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 10,
                    "text": "C2",
                    "bbox": [
                        [1493.0, 651.0],
                        [1538.0, 651.0],
                        [1538.0, 682.0],
                        [1493.0, 682.0],
                    ],
                    "primary_tokens": [],
                    "reason": "not_one_standalone_linear_token",
                }
            ],
            "unassigned_linear_observations": [
                {
                    "source_item_index": 11,
                    "text": "28 mm",
                    "bbox": [
                        [1547.0, 651.0],
                        [1641.0, 651.0],
                        [1641.0, 683.0],
                        [1547.0, 683.0],
                    ],
                    "primary_tokens": ["28"],
                    "token": "28",
                    "reason": "no_unique_DG_assignment",
                }
            ],
        },
    }

    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    targets = plan.queries[0].labeled_dimension_targets
    assert len(targets) == 1
    assert targets[0].target_id == "LD_0011"
    assert targets[0].source_item_index == 11
    assert targets[0].source_text == "C2 - 28 mm"
    assert targets[0].value == 28.0


def test_labeled_dimension_does_not_reconstruct_incomplete_numeric_fragments():
    reader_input = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R1",
                "crop_path": "C:/work/R1.png",
                "source_bbox_px": [500, 250, 220, 120],
            }
        ],
    }
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "routed_elsewhere_or_unclassified_observations": [
                {
                    "source_item_index": 4,
                    "text": "S",
                    "bbox": [[545.0, 302.0], [568.0, 302.0], [568.0, 328.0], [545.0, 328.0]],
                    "primary_tokens": [],
                    "reason": "not_one_standalone_linear_token",
                },
                {
                    "source_item_index": 6,
                    "text": "mm",
                    "bbox": [[626.0, 304.0], [680.0, 304.0], [680.0, 330.0], [626.0, 330.0]],
                    "primary_tokens": [],
                    "reason": "not_one_standalone_linear_token",
                },
            ],
            "unassigned_linear_observations": [
                {
                    "source_item_index": 5,
                    "text": "5",
                    "bbox": [[605.0, 302.0], [626.0, 302.0], [626.0, 326.0], [605.0, 326.0]],
                    "primary_tokens": ["5"],
                    "token": "5",
                    "reason": "no_unique_DG_assignment",
                }
            ],
        },
    }

    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    assert plan.queries[0].labeled_dimension_targets == []


def test_labeled_dimension_routes_long_bbox_touching_narrow_region():
    reader_input = {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R4",
                "crop_path": "C:/work/R4.png",
                "source_bbox_px": [1428, 452, 127, 269],
            }
        ],
    }
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "coverage": {
            "unassigned_linear_observations": [
                {
                    "source_item_index": 9,
                    "text": "H2- 75 mm",
                    "bbox": [
                        [1549.0, 569.0],
                        [1700.0, 569.0],
                        [1700.0, 600.0],
                        [1549.0, 600.0],
                    ],
                    "primary_tokens": ["75"],
                    "token": "75",
                    "reason": "no_unique_DG_assignment",
                }
            ]
        },
    }

    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )

    assert len(plan.queries[0].labeled_dimension_targets) == 1
    target = plan.queries[0].labeled_dimension_targets[0]
    assert target.target_id == "LD_0009"
    assert target.value == 75.0


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
    assert plan.rules["labeled_dimension_relation_seed_from_topology_only"] is True
    assert plan.rules["labeled_dimension_seeded_decisions_must_be_preserved"] is True


def test_structural_labeled_dimension_prefills_topology_proven_relation(
    tmp_path: Path,
):
    source_raster, bbox = _write_short_dimension_direction_fixture(
        tmp_path,
        witness_orientation="vertical",
    )
    reader_input = _reader_input_with_labeled_dimension_regions()
    report = _hybrid_report_with_labeled_unassigned_dimension()
    report["source_raster"] = source_raster
    report["coverage"]["unassigned_linear_observations"][0]["bbox"] = bbox
    report["structural_profile_inventory"] = [
        {
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.001",
            "region_id": "R1",
            "source_orientation": "vertical",
            "position_px": 185.0,
            "axis_tolerance_px": 5.0,
            "independent_geometry_source_count": 2,
            "non_dimension_crossing_source_count": 0,
            "relative_extreme_side": None,
        },
        {
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.002",
            "region_id": "R1",
            "source_orientation": "vertical",
            "position_px": 210.0,
            "axis_tolerance_px": 5.0,
            "independent_geometry_source_count": 2,
            "non_dimension_crossing_source_count": 0,
            "relative_extreme_side": None,
        },
    ]

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
    assert target.deterministic_visual_direction == "horizontal"
    assert target.deterministic_relation_seed == "between_profile_boundaries"

    template = StructuralContextAnswers.model_validate(plan.answer_template)
    decision = template.answers[0].labeled_dimension_decisions[0]
    assert decision.status == "resolved"
    assert decision.visual_direction == "horizontal"
    assert decision.relation == "between_profile_boundaries"
    assert decision.profile_transition_geometry is None
    assert decision.symmetry_scope is None
    assert decision.reason is None


def test_structural_labeled_relation_seed_does_not_promote_region_extremes(
    tmp_path: Path,
):
    source_raster, bbox = _write_short_dimension_direction_fixture(
        tmp_path,
        witness_orientation="vertical",
    )
    reader_input = _reader_input_with_labeled_dimension_regions()
    report = _hybrid_report_with_labeled_unassigned_dimension()
    report["source_raster"] = source_raster
    report["coverage"]["unassigned_linear_observations"][0]["bbox"] = bbox
    report["structural_profile_inventory"] = [
        {
            "kind": "profile_edge_candidate",
            "ref": f"R1.structural.vertical.00{index}",
            "region_id": "R1",
            "source_orientation": "vertical",
            "position_px": position,
            "axis_tolerance_px": 5.0,
            "independent_geometry_source_count": 2,
            "relative_extreme_side": extreme,
        }
        for index, (position, extreme) in enumerate(
            [(185.0, "min"), (210.0, "max")], start=1
        )
    ]
    plan = build_structural_context_queries(
        reader_input,
        hybrid_report=report,
    )
    target = plan.queries[0].labeled_dimension_targets[0]
    assert target.deterministic_visual_direction == "horizontal"
    assert target.deterministic_relation_seed is None
    template = StructuralContextAnswers.model_validate(plan.answer_template)
    decision = template.answers[0].labeled_dimension_decisions[0]
    assert decision.status == "unresolved"
    assert decision.reason == "pending_labeled_dimension_relation_read"


def test_structural_context_rejects_changed_deterministic_relation_seed(
    tmp_path: Path,
):
    source_raster, bbox = _write_short_dimension_direction_fixture(
        tmp_path,
        witness_orientation="vertical",
    )
    reader_input = _reader_input_with_labeled_dimension_regions()
    report = _hybrid_report_with_labeled_unassigned_dimension()
    report["source_raster"] = source_raster
    report["coverage"]["unassigned_linear_observations"][0]["bbox"] = bbox
    report["structural_profile_inventory"] = [
        {
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.001",
            "region_id": "R1",
            "source_orientation": "vertical",
            "position_px": 185.0,
            "axis_tolerance_px": 5.0,
            "independent_geometry_source_count": 2,
            "non_dimension_crossing_source_count": 0,
        },
        {
            "kind": "profile_edge_candidate",
            "ref": "R1.structural.vertical.002",
            "region_id": "R1",
            "source_orientation": "vertical",
            "position_px": 210.0,
            "axis_tolerance_px": 5.0,
            "independent_geometry_source_count": 2,
            "non_dimension_crossing_source_count": 0,
        },
    ]
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
            "relation": "overall_extent",
            "profile_transition_geometry": None,
            "symmetry_scope": None,
            "evidence": ["structural:R1:crop"],
            "reason": None,
        }
    ]
    answers = StructuralContextAnswers.model_validate(payload)

    with pytest.raises(
        StructuralContextError,
        match="changed deterministic relation seed",
    ):
        assemble_structural_context(plan, answers)


def test_short_direction_ignores_nearby_perpendicular_profile_pair(
    tmp_path: Path,
):
    import cv2
    import numpy as np

    image = np.full((320, 460), 255, np.uint8)
    bbox = [
        [120.0, 120.0],
        [252.0, 120.0],
        [252.0, 154.0],
        [120.0, 154.0],
    ]

    # True vertical witness pair for a horizontal short dimension.  Its
    # separation intentionally exceeds the legacy fixed 90 px cutoff.
    cv2.line(image, (140, 161), (140, 255), 0, 2)
    cv2.line(image, (232, 161), (232, 255), 0, 2)

    # Strong unrelated horizontal profile lines below the label must not be
    # mistaken for horizontal witnesses and flip the dimension direction.
    cv2.line(image, (120, 161), (260, 161), 0, 2)
    cv2.line(image, (120, 220), (330, 220), 0, 2)

    source_raster = tmp_path / "short-horizontal-with-profile-noise.png"
    assert cv2.imwrite(str(source_raster), image)

    reader_input = _reader_input_with_labeled_dimension_regions()
    report = _hybrid_report_with_labeled_unassigned_dimension()
    report["source_raster"] = str(source_raster)
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
    assert target.deterministic_visual_direction == "horizontal"


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
