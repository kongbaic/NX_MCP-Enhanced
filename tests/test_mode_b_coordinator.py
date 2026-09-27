from __future__ import annotations

import json
import sys
from pathlib import Path

from nx_mcp.drawing_intelligence.confirmation import build_confirmation_request
from nx_mcp.drawing_intelligence.evidence import (
    EvidenceGraph,
    OverallDimensions,
    ProjectionEvidence,
    ViewEvidence,
)
from nx_mcp.drawing_intelligence.mode_b_coordinator import (
    STATE_SCHEMA,
    _classify_resolution,
    _run_gate_a,
    resume_mode_b_coordinator,
    run_mode_b_coordinator,
)


def _prepare_runtime(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    runner_dir = workspace / "nx-mcp-plan-runner"
    runner_dir.mkdir(parents=True)

    nx_src = tmp_path / "nx-src"
    nx_src.mkdir()

    runtime = {
        "python_exe": sys.executable,
        "workspace_root": str(workspace),
        "nx_mcp_src": str(nx_src),
    }
    (runner_dir / "runtime-config.json").write_text(
        json.dumps(runtime),
        encoding="utf-8",
    )
    monkeypatch.setenv("NX_MCP_WORKSPACE", str(workspace))
    return workspace, runner_dir


def test_invalid_observations_terminal_fail_and_second_submission_is_blocked(
    tmp_path: Path,
    monkeypatch,
):
    workspace, runner_dir = _prepare_runtime(tmp_path, monkeypatch)
    (runner_dir / "runner.py").write_text("", encoding="utf-8")

    observations = workspace / "reader-observations.json"
    observations.write_text("{}", encoding="utf-8")
    prefix = workspace / "case1"

    code1, report1 = run_mode_b_coordinator(observations, prefix)

    assert code1 == 1
    assert report1["phase"] == "terminal_failed"
    assert report1["terminal"] is True
    assert report1["stage_timings"]["capture_assembly"]["status"] == "failed"

    state_path = workspace / "case1-mode-b-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "terminal_failed"

    observations.write_text('{"schema":"reader-observations-v1"}', encoding="utf-8")
    code2, report2 = run_mode_b_coordinator(observations, prefix)

    assert code2 == 3
    assert report2["reason"] == "state_exists"
    assert report2["phase"] == "terminal_failed"


def test_resolution_route_conflict_is_terminal():
    assert (
        _classify_resolution(
            resolution_ok=False,
            conflicts=1,
            confirmation_request=None,
        )
        == "terminal_failed"
    )


def test_resolution_route_accepts_only_bounded_confirmation():
    request = {
        "eligible_for_user_confirmation": True,
        "question_count": 2,
        "unconfirmable_blocking_ids": [],
    }
    assert (
        _classify_resolution(
            resolution_ok=False,
            conflicts=0,
            confirmation_request=request,
        )
        == "awaiting_confirmation"
    )

    request["question_count"] = 4
    assert (
        _classify_resolution(
            resolution_ok=False,
            conflicts=0,
            confirmation_request=request,
        )
        == "terminal_failed"
    )


def test_resolution_route_passes_directly_to_gate_a():
    assert (
        _classify_resolution(
            resolution_ok=True,
            conflicts=0,
            confirmation_request=None,
        )
        == "gate_a"
    )


def test_gate_a_uses_frozen_runtime_runner(tmp_path: Path):
    workspace = tmp_path / "workspace"
    runner_dir = workspace / "nx-mcp-plan-runner"
    runner_dir.mkdir(parents=True)
    runner = runner_dir / "runner.py"
    runner.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "out = pathlib.Path(sys.argv[3])",
                "out.write_text('{}', encoding='utf-8')",
                "print(json.dumps({'ok': True, 'written': True, 'errors': []}))",
            ]
        ),
        encoding="utf-8",
    )

    draft = workspace / "draft.json"
    drawing = workspace / "drawing.json"
    draft.write_text("{}", encoding="utf-8")

    result = _run_gate_a(
        draft,
        drawing,
        {
            "python_exe_path": Path(sys.executable),
            "runner_path": runner,
        },
    )

    assert result["ok"] is True
    assert drawing.is_file()

def _confirmation_graph() -> EvidenceGraph:
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


def _write_resume_case(
    workspace: Path,
    prefix_name: str,
    selected_role: str,
) -> tuple[Path, Path]:
    graph = _confirmation_graph()
    request = build_confirmation_request(graph)
    question = request["questions"][0]
    endpoint = next(
        item
        for item in question["endpoints"]
        if item["requires_confirmation"]
    )
    option = next(
        item
        for item in endpoint["options"]
        if item["role"] == selected_role
    )

    prefix = workspace / prefix_name
    state_path = Path(str(prefix) + "-mode-b-state.json")
    evidence_path = Path(str(prefix) + "-drawing-evidence.json")
    request_path = Path(str(prefix) + "-confirmation-request.json")
    confirmed_evidence = Path(str(prefix) + "-drawing-evidence-confirmed.json")
    confirmed_draft = Path(str(prefix) + "-semantic-draft-confirmed.json")
    drawing = Path(str(prefix) + "-drawing.json")
    answers_path = workspace / f"{prefix_name}-user-confirmations.json"

    evidence_path.write_text(
        json.dumps(graph.model_dump(mode="json")),
        encoding="utf-8",
    )
    request_path.write_text(
        json.dumps(request),
        encoding="utf-8",
    )
    answers_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "answers": [
                    {
                        "confirmation_id": question["confirmation_id"],
                        "selected_option_ids": [option["option_id"]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(
            {
                "schema": STATE_SCHEMA,
                "status": "awaiting_confirmation",
                "phase": "awaiting_confirmation",
                "terminal": False,
                "artifacts": {
                    "evidence": str(evidence_path),
                    "confirmation_request": str(request_path),
                    "confirmed_evidence": str(confirmed_evidence),
                    "confirmed_draft": str(confirmed_draft),
                    "drawing": str(drawing),
                },
                "started_at_utc": "2026-09-27T00:00:00.000Z",
                "updated_at_utc": "2026-09-27T00:00:00.000Z",
                "stage_timings": {},
                "summary": {"confirmation_question_count": 1},
                "errors": [],
                "total_elapsed_seconds": 1.0,
            }
        ),
        encoding="utf-8",
    )
    return state_path, answers_path


def _write_success_runner(runner_dir: Path) -> None:
    (runner_dir / "runner.py").write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "out = pathlib.Path(sys.argv[3])",
                "out.write_text('{}', encoding='utf-8')",
                "print(json.dumps({'ok': True, 'written': True, 'errors': []}))",
            ]
        ),
        encoding="utf-8",
    )


def test_confirmation_resume_closes_once_then_passes_gate_a(
    tmp_path: Path,
    monkeypatch,
):
    workspace, runner_dir = _prepare_runtime(tmp_path, monkeypatch)
    _write_success_runner(runner_dir)
    state_path, answers_path = _write_resume_case(
        workspace,
        "resume-pass",
        "feature_center",
    )

    code, report = resume_mode_b_coordinator(state_path, answers_path)

    assert code == 0
    assert report["phase"] == "gate_a_pass"
    assert report["terminal"] is True
    assert report["summary"]["second_resolve_blocking_unresolved"] == 0
    assert report["summary"]["second_resolve_conflicts"] == 0
    assert report["summary"]["second_resolve_dimension_closure"] == "closed"
    assert report["stage_timings"]["apply_confirmations"]["status"] == "passed"
    assert report["stage_timings"]["second_resolve"]["status"] == "passed"
    assert report["stage_timings"]["gate_a"]["status"] == "passed"
    assert Path(
        report["artifacts"]["confirmed_evidence"]
    ).is_file()
    assert Path(
        report["artifacts"]["confirmed_draft"]
    ).is_file()
    assert Path(report["artifacts"]["drawing"]).is_file()

    code2, report2 = resume_mode_b_coordinator(state_path, answers_path)
    assert code2 == 3
    assert report2["reason"] == "invalid_resume_phase"
    assert report2["phase"] == "gate_a_pass"


def test_confirmation_resume_second_resolve_failure_is_terminal(
    tmp_path: Path,
    monkeypatch,
):
    workspace, runner_dir = _prepare_runtime(tmp_path, monkeypatch)
    _write_success_runner(runner_dir)
    state_path, answers_path = _write_resume_case(
        workspace,
        "resume-fail",
        "keep_unresolved",
    )

    code, report = resume_mode_b_coordinator(state_path, answers_path)

    assert code == 1
    assert report["phase"] == "terminal_failed"
    assert report["terminal"] is True
    assert report["summary"]["second_resolve_blocking_unresolved"] == 1
    assert report["summary"]["second_resolve_dimension_closure"] == "incomplete"
    assert not Path(report["artifacts"]["drawing"]).exists()

    code2, report2 = resume_mode_b_coordinator(state_path, answers_path)
    assert code2 == 3
    assert report2["reason"] == "invalid_resume_phase"
    assert report2["phase"] == "terminal_failed"

