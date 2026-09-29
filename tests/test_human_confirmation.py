from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nx_mcp.drawing_intelligence.capture import (
    CaptureDimension,
    CaptureDimensionEndpoint,
    CaptureEntity,
    CaptureView,
    ReaderCapture,
)
from nx_mcp.drawing_intelligence.compiler import compile_evidence_graph
from nx_mcp.drawing_intelligence.confirmation import (
    ConfirmationAnswers,
    ConfirmationError,
    apply_confirmation_answers,
    build_confirmation_request,
)
from nx_mcp.drawing_intelligence.evidence import (
    EvidenceGraph,
    OverallDimensions,
    ProjectionEvidence,
    ViewEvidence,
)
from nx_mcp.drawing_intelligence.identity_linker import link_reader_capture
from nx_mcp.drawing_intelligence.resolver import resolve_evidence_graph


ROOT = Path(__file__).resolve().parents[1]


def _graph() -> EvidenceGraph:
    return EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[ViewEvidence(id="V1", kind="front", source_ids=["OBS_V1"])],
        projections=[
            ProjectionEvidence(
                id="P1",
                feature_id="F1",
                view_id="V1",
                shape="circle",
                source_ids=["OBS_P1"],
            )
        ],
        unresolved_evidence=[
            {
                "id": "U_DIM_D1",
                "kind": "dimension_endpoint",
                "reason": "endpoint owner is ambiguous",
                "required_for_modeling": True,
                "capture_dimension_id": "D1",
                "dimension_value": 8,
                "axis": "Y",
                "dimension_direction": None,
                "endpoint_specs": [
                    {
                        "index": 0,
                        "role": "unresolved",
                        "unresolved_kind": "ambiguous_owner",
                        "candidate_targets": ["feature:F1.centerline.y"],
                        "source_ids": ["OBS_D1_A"],
                    },
                    {
                        "index": 1,
                        "role": "overall_max",
                        "unresolved_kind": None,
                        "source_ids": ["OBS_D1_B"],
                    },
                ],
                "source_ids": ["OBS_D1"],
            }
        ],
    )


def _start_side_graph() -> EvidenceGraph:
    return EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[ViewEvidence(id="V1", kind="front", source_ids=["OBS_V1"])],
        projections=[
            ProjectionEvidence(
                id="P_THREAD",
                feature_id="F_THREAD",
                view_id="V1",
                shape="hidden_parallel",
                source_ids=["OBS_THREAD"],
            )
        ],
        unresolved_evidence=[
            {
                "id": "U_THREAD_SIDE",
                "kind": "start_side",
                "reason": "transverse thread entry side is unresolved",
                "required_for_modeling": True,
                "feature_ids": ["F_THREAD"],
                "field": "start_side",
                "axis": "X",
                "source_ids": ["OBS_THREAD"],
            }
        ],
    )


def test_identity_linker_preserves_unresolved_endpoint_candidates():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(
                id="V1",
                kind="front",
                source_ids=["OBS_V1"],
            )
        ],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="V1",
                shape="circle",
                cross_view_disposition="single_view",
                source_ids=["OBS_E1"],
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=8,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="unresolved",
                        candidate_entity_ids=["E1"],
                        unresolved_kind="ambiguous_owner",
                        source_ids=["OBS_D1_A"],
                    ),
                    CaptureDimensionEndpoint(
                        role="overall_max",
                        source_ids=["OBS_D1_B"],
                    ),
                ],
                unresolved_reason="endpoint owner is ambiguous",
                source_ids=["OBS_D1"],
            )
        ],
    )

    linked = link_reader_capture(capture)
    item = next(
        entry
        for entry in linked.evidence.unresolved_evidence
        if entry.get("id") == "U_DIM_D1"
    )

    assert item["endpoint_specs"][0]["role"] == "unresolved"
    assert item["endpoint_specs"][0]["candidate_targets"]
    assert item["endpoint_specs"][1]["role"] == "overall_max"


def test_profile_boundary_candidates_reach_human_confirmation_as_boundaries():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(
                id="V1",
                kind="front",
                source_ids=["OBS_V1"],
            )
        ],
        entities=[
            CaptureEntity(
                id="EP1",
                view_id="V1",
                shape="profile",
                cross_view_disposition="single_view",
                source_ids=["hybrid:profile-edge:R1.internal.001"],
                required_for_modeling=False,
            ),
            CaptureEntity(
                id="EP2",
                view_id="V1",
                shape="profile",
                cross_view_disposition="single_view",
                source_ids=["hybrid:profile-edge:R1.internal.002"],
                required_for_modeling=False,
            ),
        ],
        dimensions=[
            CaptureDimension(
                id="D_PROFILE",
                value=8,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="unresolved",
                        candidate_entity_ids=["EP1", "EP2"],
                        unresolved_kind="ambiguous_owner",
                        source_ids=["OBS_D_PROFILE_A"],
                    ),
                    CaptureDimensionEndpoint(
                        role="overall_max",
                        source_ids=["OBS_D_PROFILE_B"],
                    ),
                ],
                unresolved_reason="profile endpoint owner is ambiguous",
                source_ids=["OBS_D_PROFILE"],
            )
        ],
    )

    linked = link_reader_capture(capture)
    unresolved = next(
        item
        for item in linked.evidence.unresolved_evidence
        if item.get("id") == "U_DIM_D_PROFILE"
    )
    candidate_targets = unresolved["endpoint_specs"][0]["candidate_targets"]

    assert len(candidate_targets) == 2
    assert all(".boundary.y" in target for target in candidate_targets)

    request = build_confirmation_request(linked.evidence)
    assert request["eligible_for_user_confirmation"] is True
    endpoint = request["questions"][0]["endpoints"][0]
    evidence_options = [
        item for item in endpoint["options"]
        if item["role"] != "keep_unresolved"
    ]
    assert len(evidence_options) == 2
    assert all(item["role"] == "profile_boundary" for item in evidence_options)
    assert all(".boundary.y" in item["target"] for item in evidence_options)


def test_confirmation_request_exposes_only_evidence_backed_candidates():
    request = build_confirmation_request(_graph())

    assert request["question_count"] == 1
    assert request["eligible_for_user_confirmation"] is True
    question = request["questions"][0]
    endpoint = question["endpoints"][0]

    assert question["confirmation_id"] == "CONF_U_DIM_D1"
    assert [item["role"] for item in endpoint["options"]] == [
        "feature_center",
        "keep_unresolved",
    ]
    assert endpoint["options"][0]["target"] == "feature:F1.centerline.y"
    assert endpoint["options"][0]["evidence_candidate"] is True
    assert "F1" not in endpoint["options"][0]["label_zh"]


def test_confirmation_request_skips_unresolved_endpoint_without_evidence_candidate():
    graph = _graph().model_copy(deep=True)
    unresolved = dict(graph.unresolved_evidence[0])
    endpoint_specs = [dict(item) for item in unresolved["endpoint_specs"]]
    endpoint_specs[0]["candidate_targets"] = []
    endpoint_specs[0]["unresolved_kind"] = "intermediate_surface"
    unresolved["endpoint_specs"] = endpoint_specs
    graph = graph.model_copy(
        deep=True,
        update={"unresolved_evidence": [unresolved]},
    )

    request = build_confirmation_request(graph)

    assert request["question_count"] == 0
    assert request["eligible_for_user_confirmation"] is False
    assert request["unconfirmable_blocking_ids"] == ["U_DIM_D1"]


def test_start_side_is_not_a_production_human_confirmation_question():
    request = build_confirmation_request(_start_side_graph())

    assert request["question_count"] == 0
    assert request["eligible_for_user_confirmation"] is False
    assert request["unconfirmable_blocking_ids"] == ["U_THREAD_SIDE"]


def test_legacy_start_side_answer_cannot_create_new_production_truth():
    graph = _start_side_graph()

    with pytest.raises(
        ConfirmationError,
        match="evidence is not eligible for bounded user confirmation",
    ):
        apply_confirmation_answers(
            graph,
            {
                "schema_version": "1.0",
                "answers": [
                    {
                        "confirmation_id": "CONF_U_THREAD_SIDE",
                        "selected_option_ids": ["START_SIDE_MIN"],
                    }
                ],
            },
        )


def test_apply_confirmation_closes_edge_offset_through_existing_resolver():
    graph = _graph()
    request = build_confirmation_request(graph)
    endpoint = request["questions"][0]["endpoints"][0]
    feature_option = next(
        item
        for item in endpoint["options"]
        if item.get("target") == "feature:F1.centerline.y"
    )

    confirmed = apply_confirmation_answers(
        graph,
        ConfirmationAnswers(
            answers=[
                {
                    "confirmation_id": "CONF_U_DIM_D1",
                    "selected_option_ids": [feature_option["option_id"]],
                }
            ]
        ),
    )

    assert confirmed.unresolved_evidence == []
    assert len(confirmed.dimensions) == 1
    assert confirmed.dimensions[0].endpoints[0].target == "feature:F1.centerline.y"
    assert "feature:F1.centerline.y" in confirmed.required_targets

    compiled = compile_evidence_graph(confirmed)
    resolution = resolve_evidence_graph(compiled)

    assert resolution.ok is True
    assert resolution.values["feature:F1.centerline.y"] == 24.0


def test_keep_unresolved_does_not_mutate_dimension_evidence():
    graph = _graph()
    request = build_confirmation_request(graph)
    endpoint = request["questions"][0]["endpoints"][0]
    keep = next(
        item
        for item in endpoint["options"]
        if item["role"] == "keep_unresolved"
    )

    confirmed = apply_confirmation_answers(
        graph,
        {
            "schema_version": "1.0",
            "answers": [
                {
                    "confirmation_id": "CONF_U_DIM_D1",
                    "selected_option_ids": [keep["option_id"]],
                }
            ],
        },
    )

    assert confirmed.dimensions == []
    assert confirmed.unresolved_evidence == graph.unresolved_evidence


def test_apply_confirmation_rejects_arbitrary_option():
    with pytest.raises(ConfirmationError, match="is not allowed"):
        apply_confirmation_answers(
            _graph(),
            {
                "schema_version": "1.0",
                "answers": [
                    {
                        "confirmation_id": "CONF_U_DIM_D1",
                        "selected_option_ids": ["E0_FEATURE_NOT_IN_GRAPH"],
                    }
                ],
            },
        )


def test_unconfirmable_blocker_disables_human_gate():
    graph = _graph().model_copy(
        deep=True,
        update={
            "unresolved_evidence": [
                *_graph().unresolved_evidence,
                {
                    "id": "U_OTHER",
                    "kind": "cross_view_identity",
                    "reason": "identity is still ambiguous",
                    "required_for_modeling": True,
                },
            ]
        },
    )

    request = build_confirmation_request(graph)

    assert request["question_count"] == 1
    assert request["eligible_for_user_confirmation"] is False
    assert request["unconfirmable_blocking_ids"] == ["U_OTHER"]

    with pytest.raises(
        ConfirmationError,
        match="not eligible for bounded user confirmation",
    ):
        apply_confirmation_answers(
            graph,
            {
                "schema_version": "1.0",
                "answers": [
                    {
                        "confirmation_id": "CONF_U_DIM_D1",
                        "selected_option_ids": ["E0_OVERALL_MIN"],
                    }
                ],
            },
        )



def test_advisory_unresolved_does_not_consume_confirmation_budget():
    base = _graph()
    advisory_items = [
        {
            **base.unresolved_evidence[0],
            "id": f"U_ADVISORY_{index}",
            "required_for_modeling": False,
        }
        for index in range(1, 5)
    ]
    graph = base.model_copy(
        deep=True,
        update={
            "unresolved_evidence": [
                *base.unresolved_evidence,
                *advisory_items,
            ]
        },
    )

    request = build_confirmation_request(graph)

    assert request["blocking_unresolved_count"] == 1
    assert request["question_count"] == 1
    assert request["eligible_for_user_confirmation"] is True
    assert [item["unresolved_id"] for item in request["questions"]] == [
        "U_DIM_D1"
    ]

def test_confirmation_answers_rejects_legacy_agent_shape():
    with pytest.raises(ValueError):
        ConfirmationAnswers.model_validate(
            {
                "schema": "user-confirmations-v1",
                "confirmations": [
                    {
                        "confirmation_id": "CONF_U_DIM_D1",
                        "selected_option_id": "E0_OVERALL_MIN",
                    }
                ],
            }
        )


def test_apply_confirmation_answers_requires_every_generated_question():
    graph = _graph().model_copy(deep=True)
    second = dict(graph.unresolved_evidence[0])
    second["id"] = "U_DIM_D2"
    second["capture_dimension_id"] = "D2"
    graph = graph.model_copy(
        deep=True,
        update={
            "unresolved_evidence": [
                *graph.unresolved_evidence,
                second,
            ]
        },
    )

    request = build_confirmation_request(graph)
    first = request["questions"][0]
    endpoint = next(
        item for item in first["endpoints"] if item["requires_confirmation"]
    )
    option = next(
        item for item in endpoint["options"] if item.get("evidence_candidate") is True
    )

    with pytest.raises(ConfirmationError, match="missing confirmation ids"):
        apply_confirmation_answers(
            graph,
            {
                "schema_version": "1.0",
                "answers": [
                    {
                        "confirmation_id": first["confirmation_id"],
                        "selected_option_ids": [option["option_id"]],
                    }
                ],
            },
        )


def test_confirmation_cli_e2e_closes_dimension(tmp_path: Path):
    evidence_path = tmp_path / "drawing-evidence.json"
    request_path = tmp_path / "confirmation-request.json"
    answers_path = tmp_path / "user-confirmations.json"
    confirmed_path = tmp_path / "drawing-evidence-confirmed.json"
    draft_path = tmp_path / "semantic-draft-confirmed.json"

    evidence_path.write_text(
        json.dumps(_graph().model_dump(mode="json")),
        encoding="utf-8",
    )

    request_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "request-confirmations",
            str(evidence_path),
            str(request_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert request_run.returncode == 0, request_run.stdout + request_run.stderr
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["eligible_for_user_confirmation"] is True

    question = request["questions"][0]
    endpoint = next(
        item
        for item in question["endpoints"]
        if item["requires_confirmation"]
    )
    feature_option = next(
        item
        for item in endpoint["options"]
        if item.get("target") == "feature:F1.centerline.y"
    )
    answers_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "answers": [
                    {
                        "confirmation_id": question["confirmation_id"],
                        "selected_option_ids": [feature_option["option_id"]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    apply_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "apply-confirmations",
            str(evidence_path),
            str(answers_path),
            str(confirmed_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert apply_run.returncode == 0, apply_run.stdout + apply_run.stderr

    resolve_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "resolve",
            str(confirmed_path),
            str(draft_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resolve_run.returncode == 0, resolve_run.stdout + resolve_run.stderr
    report = json.loads(resolve_run.stdout)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["blocking_unresolved"] == 0
    assert report["conflicts"] == 0
    assert report["dimension_closure"] == "closed"
    assert draft["dimension_closure"] == {"status": "closed"}
