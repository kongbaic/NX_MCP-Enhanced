from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .capture import validate_reader_capture_contract
from .compiler import EvidenceCompileError, compile_evidence_graph
from .confirmation import (
    ConfirmationAnswers,
    ConfirmationError,
    apply_confirmation_answers,
    build_confirmation_request,
)
from .draft import DraftAssemblyError, build_semantic_draft
from .evidence import EvidenceGraph
from .gate0 import Gate0Error, write_strict_evidence
from .identity_linker import IdentityLinkError, link_reader_capture
from .reader_observations import (
    ReaderObservationAssemblyError,
    ReaderObservations,
    assemble_reader_capture,
)
from .resolver import resolve_evidence_graph

STATE_SCHEMA = "mode-b-coordinator-state-v1"


class ModeBCoordinatorError(RuntimeError):
    """Raised when the deterministic Mode B coordinator must fail closed."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ModeBCoordinatorError(f"{path}: JSON root must be an object")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _artifact_paths(prefix: Path) -> dict[str, Path]:
    base = str(prefix.resolve())
    return {
        "state": Path(base + "-mode-b-state.json"),
        "capture": Path(base + "-reader-capture.json"),
        "evidence": Path(base + "-drawing-evidence.json"),
        "draft": Path(base + "-semantic-draft.json"),
        "confirmation_request": Path(base + "-confirmation-request.json"),
        "confirmed_evidence": Path(base + "-drawing-evidence-confirmed.json"),
        "confirmed_draft": Path(base + "-semantic-draft-confirmed.json"),
        "drawing": Path(base + "-drawing.json"),
    }


def _load_runtime() -> dict[str, Any]:
    workspace_text = os.environ.get("NX_MCP_WORKSPACE", "").strip()
    if not workspace_text:
        raise ModeBCoordinatorError("NX_MCP_WORKSPACE is missing")

    workspace = Path(workspace_text).resolve()
    runtime_path = workspace / "nx-mcp-plan-runner" / "runtime-config.json"
    if not runtime_path.is_file():
        raise ModeBCoordinatorError(f"runtime configuration missing: {runtime_path}")

    runtime = _load_json(runtime_path)
    for key in ("python_exe", "workspace_root", "nx_mcp_src"):
        if not isinstance(runtime.get(key), str) or not runtime[key].strip():
            raise ModeBCoordinatorError(f"runtime configuration missing field: {key}")

    runtime_workspace = Path(runtime["workspace_root"]).resolve()
    if runtime_workspace != workspace:
        raise ModeBCoordinatorError(
            f"runtime workspace mismatch: env={workspace} config={runtime_workspace}"
        )

    python_exe = Path(runtime["python_exe"]).resolve()
    if not python_exe.is_file():
        raise ModeBCoordinatorError(f"runtime python missing: {python_exe}")

    runner = workspace / "nx-mcp-plan-runner" / "runner.py"
    if not runner.is_file():
        raise ModeBCoordinatorError(f"runner missing: {runner}")

    return {
        **runtime,
        "workspace": workspace,
        "runtime_path": runtime_path,
        "python_exe_path": python_exe,
        "runner_path": runner,
    }


def _require_workspace_file(path: Path, workspace: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ModeBCoordinatorError(f"{label} must be inside NX_MCP_WORKSPACE: {resolved}") from exc
    return resolved


def _record_stage(
    state: dict[str, Any],
    state_path: Path,
    name: str,
    started: float,
    *,
    status: str = "passed",
) -> None:
    elapsed = max(0.0, time.monotonic() - started)
    state.setdefault("stage_timings", {})[name] = {
        "status": status,
        "elapsed_seconds": round(elapsed, 6),
    }
    state["updated_at_utc"] = _now_utc()
    state["total_elapsed_seconds"] = round(
        max(0.0, time.monotonic() - state["_started_monotonic"]),
        6,
    )
    persisted = {key: value for key, value in state.items() if key != "_started_monotonic"}
    _atomic_write_json(state_path, persisted)


def _set_phase(
    state: dict[str, Any],
    state_path: Path,
    phase: str,
    *,
    status: str,
    terminal: bool,
) -> None:
    state["phase"] = phase
    state["status"] = status
    state["terminal"] = terminal
    state["updated_at_utc"] = _now_utc()
    state["total_elapsed_seconds"] = round(
        max(0.0, time.monotonic() - state["_started_monotonic"]),
        6,
    )
    persisted = {key: value for key, value in state.items() if key != "_started_monotonic"}
    _atomic_write_json(state_path, persisted)


def _fail(
    state: dict[str, Any],
    state_path: Path,
    stage: str,
    exc: Exception,
    started: float | None = None,
) -> tuple[int, dict[str, Any]]:
    if started is not None:
        _record_stage(state, state_path, stage, started, status="failed")
    message = f"{type(exc).__name__}: {exc}"
    state.setdefault("errors", []).append({"stage": stage, "message": message})
    _set_phase(
        state,
        state_path,
        "terminal_failed",
        status="failed",
        terminal=True,
    )
    return 1, _public_report(state, state_path)


def _public_report(state: dict[str, Any], state_path: Path) -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "state": str(state_path),
        "status": state.get("status"),
        "phase": state.get("phase"),
        "terminal": state.get("terminal"),
        "stage_timings": state.get("stage_timings", {}),
        "summary": state.get("summary", {}),
        "artifacts": state.get("artifacts", {}),
        "errors": state.get("errors", []),
        "total_elapsed_seconds": state.get("total_elapsed_seconds", 0.0),
    }


def _classify_resolution(
    *,
    resolution_ok: bool,
    conflicts: int,
    confirmation_request: dict[str, Any] | None = None,
) -> str:
    if resolution_ok:
        return "gate_a"
    if conflicts:
        return "terminal_failed"
    if confirmation_request is None:
        return "terminal_failed"

    question_count = confirmation_request.get("question_count")
    eligible = confirmation_request.get("eligible_for_user_confirmation") is True
    unconfirmable = confirmation_request.get("unconfirmable_blocking_ids")
    if (
        eligible
        and isinstance(question_count, int)
        and 1 <= question_count <= 3
        and isinstance(unconfirmable, list)
        and not unconfirmable
    ):
        return "awaiting_confirmation"
    return "terminal_failed"


def _run_gate_a(
    draft_path: Path,
    drawing_path: Path,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    command = [
        str(runtime["python_exe_path"]),
        str(runtime["runner_path"]),
        "canonicalize-drawing",
        str(draft_path),
        str(drawing_path),
    ]
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    stdout = process.stdout.strip()
    stderr = process.stderr.strip()

    try:
        result = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        raise ModeBCoordinatorError("Gate A returned non-JSON output") from exc

    if process.returncode != 0:
        errors = result.get("errors") if isinstance(result, dict) else None
        detail = errors if errors else (stderr[-2000:] or stdout[-2000:])
        raise ModeBCoordinatorError(f"Gate A failed: {detail}")

    if not isinstance(result, dict):
        raise ModeBCoordinatorError("Gate A result must be an object")
    if result.get("ok") is not True or result.get("written") is not True:
        raise ModeBCoordinatorError(
            f"Gate A did not produce canonical drawing: {result.get('errors', [])}"
        )
    if not drawing_path.is_file():
        raise ModeBCoordinatorError("Gate A reported success but drawing output is missing")
    return result


def run_mode_b_coordinator(
    observations: str | os.PathLike[str],
    artifact_prefix: str | os.PathLike[str],
) -> tuple[int, dict[str, Any]]:
    try:
        runtime = _load_runtime()
    except Exception as exc:
        return 2, {
            "schema": STATE_SCHEMA,
            "status": "blocked",
            "phase": "runtime_check",
            "terminal": True,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    workspace: Path = runtime["workspace"]
    try:
        observations_path = _require_workspace_file(
            Path(observations),
            workspace,
            "reader observations",
        )
        prefix = _require_workspace_file(
            Path(artifact_prefix),
            workspace,
            "artifact prefix",
        )
        if prefix.parent != workspace:
            raise ModeBCoordinatorError("artifact prefix must be directly inside NX_MCP_WORKSPACE")
    except Exception as exc:
        return 2, {
            "schema": STATE_SCHEMA,
            "status": "blocked",
            "phase": "artifact_check",
            "terminal": True,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    artifacts = _artifact_paths(prefix)
    state_path = artifacts["state"]

    if state_path.exists():
        try:
            previous = _load_json(state_path)
        except Exception:
            previous = {}
        return 3, {
            "schema": STATE_SCHEMA,
            "status": "blocked",
            "phase": previous.get("phase", "unknown"),
            "terminal": previous.get("terminal"),
            "reason": "state_exists",
            "state": str(state_path),
            "errors": [
                "this Mode B observation submission has already started; "
                "create a fresh artifact prefix for a new run"
            ],
        }

    stale = [str(path) for key, path in artifacts.items() if key != "state" and path.exists()]
    if stale:
        return 2, {
            "schema": STATE_SCHEMA,
            "status": "blocked",
            "phase": "artifact_check",
            "terminal": True,
            "reason": "stale_outputs",
            "errors": stale,
        }

    started = time.monotonic()
    state: dict[str, Any] = {
        "schema": STATE_SCHEMA,
        "status": "running",
        "phase": "reader_submitted",
        "terminal": False,
        "observations": str(observations_path),
        "artifacts": {key: str(path) for key, path in artifacts.items() if key != "state"},
        "started_at_utc": _now_utc(),
        "updated_at_utc": _now_utc(),
        "stage_timings": {},
        "summary": {},
        "errors": [],
        "total_elapsed_seconds": 0.0,
        "_started_monotonic": started,
    }
    _set_phase(
        state,
        state_path,
        "reader_submitted",
        status="running",
        terminal=False,
    )

    stage = "capture_assembly"
    stage_started = time.monotonic()
    try:
        raw = _load_json(observations_path)
        observation_model = ReaderObservations.model_validate(raw)
        capture = assemble_reader_capture(observation_model)
        _atomic_write_json(
            artifacts["capture"],
            capture.model_dump(mode="json"),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        ReaderObservationAssemblyError,
        ModeBCoordinatorError,
    ) as exc:
        return _fail(state, state_path, stage, exc, stage_started)
    _record_stage(state, state_path, stage, stage_started)

    stage = "capture_contract"
    stage_started = time.monotonic()
    try:
        contract_errors = validate_reader_capture_contract(capture)
        if contract_errors:
            raise ModeBCoordinatorError(
                "ReaderCapture contract failed: " + "; ".join(contract_errors[:20])
            )
    except Exception as exc:
        return _fail(state, state_path, stage, exc, stage_started)
    _record_stage(state, state_path, stage, stage_started)
    _set_phase(
        state,
        state_path,
        "capture_pass",
        status="running",
        terminal=False,
    )

    stage = "identity_link_gate0"
    stage_started = time.monotonic()
    try:
        linked = link_reader_capture(capture)
        gate0 = write_strict_evidence(linked.evidence.model_dump(mode="json"))
        evidence_payload = gate0.evidence.model_dump(mode="json")
        _atomic_write_json(artifacts["evidence"], evidence_payload)
        graph = EvidenceGraph.model_validate(evidence_payload)
        state["summary"]["linker_blocking_unresolved"] = linked.report.get("blocking_unresolved", 0)
        state["summary"]["gate0_total_unresolved"] = gate0.report.get("total_unresolved", 0)
    except (
        OSError,
        ValueError,
        ValidationError,
        IdentityLinkError,
        Gate0Error,
    ) as exc:
        return _fail(state, state_path, stage, exc, stage_started)
    _record_stage(state, state_path, stage, stage_started)
    _set_phase(
        state,
        state_path,
        "link_pass",
        status="running",
        terminal=False,
    )

    stage = "resolve"
    stage_started = time.monotonic()
    try:
        compiled = compile_evidence_graph(graph)
        resolution = resolve_evidence_graph(compiled)
        draft = build_semantic_draft(compiled, resolution)
        _atomic_write_json(artifacts["draft"], draft)
    except (
        OSError,
        ValueError,
        ValidationError,
        EvidenceCompileError,
        DraftAssemblyError,
    ) as exc:
        return _fail(state, state_path, stage, exc, stage_started)

    blocking_unresolved = sum(
        1 for item in resolution.unresolved if item.get("required_for_modeling", True)
    )
    conflicts = len(resolution.conflicts)
    state["summary"].update(
        {
            "blocking_unresolved": blocking_unresolved,
            "conflicts": conflicts,
            "dimension_closure": draft.get("dimension_closure", {}).get("status"),
        }
    )
    _record_stage(state, state_path, stage, stage_started)

    confirmation_request: dict[str, Any] | None = None
    if not resolution.ok and not conflicts:
        stage = "confirmation_request"
        stage_started = time.monotonic()
        try:
            confirmation_request = build_confirmation_request(graph)
            _atomic_write_json(
                artifacts["confirmation_request"],
                confirmation_request,
            )
        except (ValueError, ValidationError, ConfirmationError) as exc:
            return _fail(state, state_path, stage, exc, stage_started)
        _record_stage(state, state_path, stage, stage_started)

    route = _classify_resolution(
        resolution_ok=resolution.ok,
        conflicts=conflicts,
        confirmation_request=confirmation_request,
    )

    if route == "awaiting_confirmation":
        if confirmation_request is None:
            return _fail(
                state,
                state_path,
                "confirmation_request",
                ModeBCoordinatorError(
                    "awaiting_confirmation route requires a confirmation request"
                ),
            )
        state["summary"]["confirmation_question_count"] = confirmation_request["question_count"]
        _set_phase(
            state,
            state_path,
            "awaiting_confirmation",
            status="awaiting_confirmation",
            terminal=False,
        )
        return 4, _public_report(state, state_path)

    if route == "terminal_failed":
        reason = "resolver_conflict" if conflicts else "blocking_unresolved_not_confirmable"
        state.setdefault("errors", []).append({"stage": "resolve", "message": reason})
        _set_phase(
            state,
            state_path,
            "terminal_failed",
            status="failed",
            terminal=True,
        )
        return 1, _public_report(state, state_path)

    _set_phase(
        state,
        state_path,
        "resolve_pass",
        status="running",
        terminal=False,
    )

    stage = "gate_a"
    stage_started = time.monotonic()
    try:
        gate_result = _run_gate_a(
            artifacts["draft"],
            artifacts["drawing"],
            runtime,
        )
        state["summary"]["gate_a_ok"] = gate_result.get("ok") is True
    except Exception as exc:
        return _fail(state, state_path, stage, exc, stage_started)
    _record_stage(state, state_path, stage, stage_started)
    _set_phase(
        state,
        state_path,
        "gate_a_pass",
        status="success",
        terminal=True,
    )
    return 0, _public_report(state, state_path)


def resume_mode_b_coordinator(
    state_file: str | os.PathLike[str],
    answers: str | os.PathLike[str],
) -> tuple[int, dict[str, Any]]:
    try:
        runtime = _load_runtime()
    except Exception as exc:
        return 2, {
            "schema": STATE_SCHEMA,
            "status": "blocked",
            "phase": "runtime_check",
            "terminal": True,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    workspace: Path = runtime["workspace"]
    try:
        state_path = _require_workspace_file(
            Path(state_file),
            workspace,
            "Mode B state",
        )
        answers_path = _require_workspace_file(
            Path(answers),
            workspace,
            "user confirmations",
        )
        if state_path.parent != workspace or answers_path.parent != workspace:
            raise ModeBCoordinatorError(
                "state and user confirmations must be directly inside NX_MCP_WORKSPACE"
            )
        if not state_path.is_file():
            raise ModeBCoordinatorError(f"Mode B state missing: {state_path}")
        if not answers_path.is_file():
            raise ModeBCoordinatorError(f"user confirmations missing: {answers_path}")

        state = _load_json(state_path)
        if state.get("schema") != STATE_SCHEMA:
            raise ModeBCoordinatorError(f"unsupported Mode B state schema: {state.get('schema')!r}")
        if state.get("phase") != "awaiting_confirmation" or state.get("terminal") is True:
            return 3, {
                "schema": STATE_SCHEMA,
                "status": "blocked",
                "phase": state.get("phase"),
                "terminal": state.get("terminal"),
                "reason": "invalid_resume_phase",
                "state": str(state_path),
                "errors": [
                    "Mode B confirmation resume is allowed only once from awaiting_confirmation"
                ],
            }

        artifact_values = state.get("artifacts")
        if not isinstance(artifact_values, dict):
            raise ModeBCoordinatorError("Mode B state artifacts must be an object")

        required_names = (
            "evidence",
            "confirmed_evidence",
            "confirmed_draft",
            "drawing",
        )
        artifacts: dict[str, Path] = {}
        for name in required_names:
            raw_path = artifact_values.get(name)
            if not isinstance(raw_path, str) or not raw_path:
                raise ModeBCoordinatorError(f"Mode B state missing artifact path: {name}")
            path = _require_workspace_file(
                Path(raw_path),
                workspace,
                f"Mode B artifact {name}",
            )
            if path.parent != workspace:
                raise ModeBCoordinatorError(
                    f"Mode B artifact must be directly inside workspace: {path}"
                )
            artifacts[name] = path

        if not artifacts["evidence"].is_file():
            raise ModeBCoordinatorError(
                f"original drawing evidence missing: {artifacts['evidence']}"
            )
        stale = [
            str(artifacts[name])
            for name in ("confirmed_evidence", "confirmed_draft", "drawing")
            if artifacts[name].exists()
        ]
        if stale:
            return 3, {
                "schema": STATE_SCHEMA,
                "status": "blocked",
                "phase": state.get("phase"),
                "terminal": state.get("terminal"),
                "reason": "stale_resume_outputs",
                "state": str(state_path),
                "errors": stale,
            }
    except Exception as exc:
        return 2, {
            "schema": STATE_SCHEMA,
            "status": "blocked",
            "phase": "resume_check",
            "terminal": True,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    previous_elapsed = state.get("total_elapsed_seconds", 0.0)
    try:
        previous_elapsed = float(previous_elapsed)
    except (TypeError, ValueError):
        previous_elapsed = 0.0
    state["_started_monotonic"] = time.monotonic() - max(0.0, previous_elapsed)
    state["user_confirmations"] = str(answers_path)
    _set_phase(
        state,
        state_path,
        "confirmation_submitted",
        status="running",
        terminal=False,
    )

    stage = "apply_confirmations"
    stage_started = time.monotonic()
    try:
        graph = EvidenceGraph.model_validate(_load_json(artifacts["evidence"]))
        answer_model = ConfirmationAnswers.model_validate(_load_json(answers_path))
        before_request = build_confirmation_request(graph)
        confirmed = apply_confirmation_answers(graph, answer_model)
        after_request = build_confirmation_request(confirmed)
        _atomic_write_json(
            artifacts["confirmed_evidence"],
            confirmed.model_dump(mode="json"),
        )
        state["summary"].update(
            {
                "confirmation_answer_count": len(answer_model.answers),
                "confirmation_questions_before": before_request.get("question_count", 0),
                "confirmation_questions_after": after_request.get("question_count", 0),
            }
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        ConfirmationError,
        ModeBCoordinatorError,
    ) as exc:
        return _fail(state, state_path, stage, exc, stage_started)
    _record_stage(state, state_path, stage, stage_started)

    stage = "second_resolve"
    stage_started = time.monotonic()
    try:
        compiled = compile_evidence_graph(confirmed)
        resolution = resolve_evidence_graph(compiled)
        draft = build_semantic_draft(compiled, resolution)
        _atomic_write_json(artifacts["confirmed_draft"], draft)
    except (
        OSError,
        ValueError,
        ValidationError,
        EvidenceCompileError,
        DraftAssemblyError,
    ) as exc:
        return _fail(state, state_path, stage, exc, stage_started)

    blocking_unresolved = sum(
        1 for item in resolution.unresolved if item.get("required_for_modeling", True)
    )
    conflicts = len(resolution.conflicts)
    state["summary"].update(
        {
            "second_resolve_blocking_unresolved": blocking_unresolved,
            "second_resolve_conflicts": conflicts,
            "second_resolve_dimension_closure": draft.get("dimension_closure", {}).get("status"),
        }
    )
    _record_stage(state, state_path, stage, stage_started)

    if not resolution.ok:
        state.setdefault("errors", []).append(
            {"stage": "second_resolve", "message": "second_resolve_not_closed"}
        )
        _set_phase(
            state,
            state_path,
            "terminal_failed",
            status="failed",
            terminal=True,
        )
        return 1, _public_report(state, state_path)

    _set_phase(
        state,
        state_path,
        "second_resolve_pass",
        status="running",
        terminal=False,
    )

    stage = "gate_a"
    stage_started = time.monotonic()
    try:
        gate_result = _run_gate_a(
            artifacts["confirmed_draft"],
            artifacts["drawing"],
            runtime,
        )
        state["summary"]["gate_a_ok"] = gate_result.get("ok") is True
    except Exception as exc:
        return _fail(state, state_path, stage, exc, stage_started)
    _record_stage(state, state_path, stage, stage_started)
    _set_phase(
        state,
        state_path,
        "gate_a_pass",
        status="success",
        terminal=True,
    )
    return 0, _public_report(state, state_path)


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)

    if effective_argv and effective_argv[0] == "resume":
        parser = argparse.ArgumentParser(
            prog=("python -m nx_mcp.drawing_intelligence.mode_b_coordinator resume"),
            description=(
                "Resume exactly once from awaiting_confirmation through second resolve and Gate A"
            ),
        )
        parser.add_argument("state")
        parser.add_argument("answers")
        args = parser.parse_args(effective_argv[1:])
        code, report = resume_mode_b_coordinator(
            args.state,
            args.answers,
        )
    else:
        parser = argparse.ArgumentParser(
            prog="python -m nx_mcp.drawing_intelligence.mode_b_coordinator",
            description=(
                "Deterministic one-pass Mode B coordinator from immutable "
                "reader-observations through Gate A"
            ),
        )
        parser.add_argument("observations")
        parser.add_argument(
            "artifact_prefix",
            help=(
                "workspace-local prefix; coordinator creates "
                "state/capture/evidence/draft/confirmation/drawing "
                "artifacts from this prefix"
            ),
        )
        args = parser.parse_args(effective_argv)
        code, report = run_mode_b_coordinator(
            args.observations,
            args.artifact_prefix,
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
