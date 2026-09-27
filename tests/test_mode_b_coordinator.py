from __future__ import annotations

import json
import sys
from pathlib import Path

from nx_mcp.drawing_intelligence.mode_b_coordinator import (
    _classify_resolution,
    _run_gate_a,
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
