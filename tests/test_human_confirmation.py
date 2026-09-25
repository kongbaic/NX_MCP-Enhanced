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


def test_confirmation_request_is_bounded_to_known_features_and_boundaries():
    request = build_confirmation_request(_graph())

    assert request["question_count"] == 1
    assert request["eligible_for_user_confirmation"] is True
    question = request["questions"][0]
    endpoint = question["endpoints"][0]
    option_roles = {item["role"] for item in endpoint["options"]}

    assert question["confirmation_id"] == "CONF_U_DIM_D1"
    assert option_roles == {
        "overall_min",
        "overall_max",
        "feature_center",
        "keep_unresolved",
    }
    feature_options = [
        item
        for item in endpoint["options"]
        if item["role"] == "feature_center"
    ]
    assert [item["target"] for item in feature_options] == [
        "feature:F1.centerline.y"
    ]
    assert feature_options[0]["evidence_candidate"] is True


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
