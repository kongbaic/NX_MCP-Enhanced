from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .hybrid_capture_adapter import HybridCaptureAdapterError, adapt_hybrid_ocr_report
from .hybrid_ocr import run_hybrid_ocr
from .mode_b_coordinator import run_mode_b_coordinator
from .reader_input_prep import prepare_reader_input
from .reader_observation_finalizer import (
    ReaderObservationFinalizationError,
    finalize_partial_reader_observations,
)
from .reader_semantic_answers import PartialReaderObservations
from .structural_context import (
    StructuralCompactVisualAnswers,
    StructuralContextAnswers,
    StructuralContextError,
    StructuralContextQueryPlan,
    assemble_structural_context,
    compose_structural_visual_answers,
    build_structural_context_queries,
)

MANIFEST_SCHEMA = "hybrid-frontend-run-v1"


class HybridFrontendCoordinatorError(RuntimeError):
    """Raised when the Production Hybrid Frontend must fail closed."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise HybridFrontendCoordinatorError(f"{path}: JSON root must be an object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
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


def _workspace() -> Path:
    text = os.environ.get("NX_MCP_WORKSPACE", "").strip()
    if not text:
        raise HybridFrontendCoordinatorError("NX_MCP_WORKSPACE is missing")
    workspace = Path(text).resolve()
    if not workspace.is_dir():
        raise HybridFrontendCoordinatorError(f"NX_MCP_WORKSPACE does not exist: {workspace}")
    return workspace


def _inside_workspace(path: Path, workspace: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise HybridFrontendCoordinatorError(
            f"{label} must be inside NX_MCP_WORKSPACE: {resolved}"
        ) from exc
    return resolved


def _run_paths(run_dir: Path) -> dict[str, Path]:
    return {
        "manifest": run_dir / "hybrid-frontend-manifest.json",
        "reader_input": run_dir / "reader-input.json",
        "hybrid_report": run_dir / "hybrid-ocr-report.json",
        "ocr_artifacts": run_dir / "hybrid-ocr-artifacts",
        "structural_queries": run_dir / "structural-context-queries.json",
        "structural_answers": run_dir / "structural-context-answers.json",
        "structural_visual_decisions": run_dir / "structural-visual-decisions.json",
        "structural_context": run_dir / "hybrid-adapter-context.json",
        "partial_observations": run_dir / "partial-reader-observations.json",
        "reader_observations": run_dir / "reader-observations.json",
    }


def _report(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "manifest": str(manifest_path),
        "status": manifest.get("status"),
        "phase": manifest.get("phase"),
        "terminal": manifest.get("terminal"),
        "must_stop": manifest.get("must_stop"),
        "may_retry": manifest.get("may_retry"),
        "may_edit_structural_answers": manifest.get("may_edit_structural_answers"),
        "timing_seconds": manifest.get("timing_seconds", {}),
        "summary": manifest.get("summary", {}),
        "artifacts": manifest.get("artifacts", {}),
        "mode_b": manifest.get("mode_b"),
        "errors": manifest.get("errors", []),
    }


def _stage(
    manifest: dict[str, Any],
    manifest_path: Path,
    name: str,
    started: float,
) -> None:
    manifest.setdefault("timing_seconds", {})[name] = round(
        max(0.0, time.monotonic() - started),
        6,
    )
    _write_json(manifest_path, manifest)


def _fail(
    manifest: dict[str, Any],
    manifest_path: Path,
    stage: str,
    exc: Exception,
) -> tuple[int, dict[str, Any]]:
    manifest.setdefault("errors", []).append(
        {"stage": stage, "message": f"{type(exc).__name__}: {exc}"}
    )
    manifest.update(
        phase="terminal_failed",
        status="failed",
        terminal=True,
        must_stop=True,
        may_retry=False,
        may_edit_structural_answers=False,
    )
    _write_json(manifest_path, manifest)
    return 1, _report(manifest, manifest_path)


def start_hybrid_frontend(
    image: str | os.PathLike[str],
    run_directory: str | os.PathLike[str],
) -> tuple[int, dict[str, Any]]:
    try:
        workspace = _workspace()
        image_path = Path(image).resolve()
        run_dir = _inside_workspace(
            Path(run_directory),
            workspace,
            "Hybrid Frontend run directory",
        )
        if not image_path.is_file():
            raise HybridFrontendCoordinatorError(f"source drawing is missing: {image_path}")
        if run_dir.exists():
            raise HybridFrontendCoordinatorError(
                f"Hybrid Frontend run directory already exists: {run_dir}"
            )
        run_dir.mkdir(parents=True)
    except (OSError, ValueError, HybridFrontendCoordinatorError) as exc:
        return 2, {
            "schema": MANIFEST_SCHEMA,
            "status": "blocked",
            "phase": "start_check",
            "terminal": True,
            "must_stop": True,
            "may_retry": False,
            "may_edit_structural_answers": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    paths = _run_paths(run_dir)
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "status": "running",
        "phase": "starting",
        "terminal": False,
        "source_drawing": str(image_path),
        "run_directory": str(run_dir),
        "artifacts": {key: str(path) for key, path in paths.items() if key != "manifest"},
        "timing_seconds": {},
        "summary": {},
        "mode_b": None,
        "errors": [],
    }
    _write_json(paths["manifest"], manifest)

    stage = "deterministic_reader_prep"
    started = time.monotonic()
    try:
        prep = prepare_reader_input(image_path, run_dir)
        actual_input = Path(str(prep.get("reader_input") or "")).resolve()
        if actual_input != paths["reader_input"].resolve() or not actual_input.is_file():
            raise HybridFrontendCoordinatorError(
                "deterministic Reader prep did not produce reader-input.json"
            )
        manifest["summary"]["prep"] = prep.get("summary", {})
    except (OSError, RuntimeError, ValueError, HybridFrontendCoordinatorError) as exc:
        return _fail(manifest, paths["manifest"], stage, exc)
    _stage(manifest, paths["manifest"], stage, started)

    stage = "hybrid_ocr"
    started = time.monotonic()
    try:
        ocr = run_hybrid_ocr(
            paths["reader_input"],
            paths["hybrid_report"],
            artifact_dir=paths["ocr_artifacts"],
        )
        if not paths["hybrid_report"].is_file():
            raise HybridFrontendCoordinatorError("Hybrid OCR report was not written")
        manifest["summary"]["hybrid_ocr"] = {
            "candidate_count": ocr.get("candidate_count", 0),
            "accepted_count": ocr.get("accepted_count", 0),
            "unresolved_count": ocr.get("unresolved_count", 0),
            "ocr_elapsed_s": ocr.get("ocr_elapsed_s", {}),
        }
    except (ImportError, OSError, RuntimeError, ValueError, HybridFrontendCoordinatorError) as exc:
        return _fail(manifest, paths["manifest"], stage, exc)
    _stage(manifest, paths["manifest"], stage, started)

    stage = "structural_query_plan"
    started = time.monotonic()
    try:
        plan = build_structural_context_queries(
            _load_json(paths["reader_input"]),
            hybrid_report=_load_json(paths["hybrid_report"]),
        )
        _write_json(
            paths["structural_queries"],
            plan.model_dump(mode="json", by_alias=True),
        )
        manifest["summary"]["structural_query_count"] = len(plan.queries)
        manifest["summary"]["structural_reader_preclassified_reference_count"] = sum(
            1 for item in plan.queries
            if item.deterministic_non_geometric_reference
        )
        manifest["summary"]["structural_reader_preclassified_view_count"] = sum(
            1 for item in plan.queries
            if item.deterministic_view_kind is not None
        )
        manifest["summary"]["structural_agent_pending_view_count"] = sum(
            1 for item in plan.queries
            if (
                not item.deterministic_non_geometric_reference
                and item.deterministic_view_kind is None
            )
        )
        manifest["summary"]["structural_agent_pending_region_count"] = sum(
            1 for item in plan.queries
            if not item.deterministic_non_geometric_reference
        )
        manifest["summary"]["structural_unique_image_count"] = len(
            {item.image_path for item in plan.queries}
        )
        structural_targets = [
            target
            for query in plan.queries
            for target in query.labeled_dimension_targets
        ]
        manifest["summary"]["structural_labeled_target_count"] = len(
            structural_targets
        )
        manifest["summary"]["structural_seeded_target_count"] = sum(
            1
            for target in structural_targets
            if target.deterministic_relation_seed is not None
        )
        manifest["summary"]["structural_agent_pending_target_count"] = sum(
            1
            for target in structural_targets
            if target.deterministic_relation_seed is None
        )
    except (
        OSError,
        ValueError,
        ValidationError,
        StructuralContextError,
        HybridFrontendCoordinatorError,
    ) as exc:
        return _fail(manifest, paths["manifest"], stage, exc)
    _stage(manifest, paths["manifest"], stage, started)

    manifest.update(
        phase="awaiting_structural_context",
        status="awaiting_structural_context",
        terminal=False,
        must_stop=False,
        may_retry=None,
        may_edit_structural_answers=None,
    )
    manifest.setdefault("timing_markers_epoch_s", {})[
        "structural_context_wait_started"
    ] = round(time.time(), 6)
    _write_json(paths["manifest"], manifest)
    return 4, _report(manifest, paths["manifest"])


def resume_hybrid_frontend(
    manifest_file: str | os.PathLike[str],
    structural_answers: str | os.PathLike[str],
    mode_b_prefix: str | os.PathLike[str],
) -> tuple[int, dict[str, Any]]:
    try:
        workspace = _workspace()
        manifest_path = _inside_workspace(
            Path(manifest_file),
            workspace,
            "Hybrid Frontend manifest",
        )
        answers_path = _inside_workspace(
            Path(structural_answers),
            workspace,
            "structural answers",
        )
        prefix = _inside_workspace(
            Path(mode_b_prefix),
            workspace,
            "Mode B artifact prefix",
        )
        if prefix.parent != workspace:
            raise HybridFrontendCoordinatorError(
                "Mode B artifact prefix must be directly inside NX_MCP_WORKSPACE"
            )
        if not manifest_path.is_file() or not answers_path.is_file():
            raise HybridFrontendCoordinatorError("manifest or structural answers are missing")

        manifest = _load_json(manifest_path)
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise HybridFrontendCoordinatorError(
                f"unsupported Hybrid Frontend schema: {manifest.get('schema')!r}"
            )
        if (
            manifest.get("phase") != "awaiting_structural_context"
            or manifest.get("terminal") is True
        ):
            return 3, {
                "schema": MANIFEST_SCHEMA,
                "status": "blocked",
                "phase": manifest.get("phase"),
                "terminal": True,
                "must_stop": True,
                "may_retry": False,
                "may_edit_structural_answers": False,
                "reason": "invalid_resume_phase",
                "errors": ["resume is allowed exactly once from awaiting_structural_context"],
            }

        run_dir = _inside_workspace(
            Path(str(manifest.get("run_directory") or "")),
            workspace,
            "Hybrid Frontend run directory",
        )
        paths = _run_paths(run_dir)
        if paths["manifest"].resolve() != manifest_path.resolve():
            raise HybridFrontendCoordinatorError("manifest/run directory mismatch")
        is_compact_visual = answers_path.resolve() == paths[
            "structural_visual_decisions"
        ].resolve()
        if (
            not is_compact_visual
            and answers_path.resolve() != paths["structural_answers"].resolve()
        ):
            raise HybridFrontendCoordinatorError(
                "structural answers must be the current Hybrid Frontend run artifact: "
                + str(paths["structural_answers"])
            )
        for key in ("reader_input", "hybrid_report", "structural_queries"):
            if not paths[key].is_file():
                raise HybridFrontendCoordinatorError(f"required frontend artifact missing: {key}")
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        HybridFrontendCoordinatorError,
    ) as exc:
        return 2, {
            "schema": MANIFEST_SCHEMA,
            "status": "blocked",
            "phase": "resume_check",
            "terminal": True,
            "must_stop": True,
            "may_retry": False,
            "may_edit_structural_answers": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    timing_markers = manifest.get("timing_markers_epoch_s")
    wait_started = (
        timing_markers.get("structural_context_wait_started")
        if isinstance(timing_markers, dict)
        else None
    )
    if isinstance(wait_started, (int, float)) and not isinstance(
        wait_started,
        bool,
    ):
        answers_written = answers_path.stat().st_mtime
        resumed_at = time.time()
        if answers_written >= float(wait_started):
            manifest.setdefault("timing_seconds", {})[
                "structural_context_agent_wait"
            ] = round(
                max(0.0, answers_written - float(wait_started)),
                6,
            )
            manifest.setdefault("timing_seconds", {})[
                "structural_context_resume_lag"
            ] = round(
                max(0.0, resumed_at - answers_written),
                6,
            )
            _write_json(manifest_path, manifest)

    stage = "structural_context"
    started = time.monotonic()
    try:
        plan = StructuralContextQueryPlan.model_validate(_load_json(paths["structural_queries"]))
        if is_compact_visual:
            if paths["structural_answers"].exists():
                raise HybridFrontendCoordinatorError(
                    "canonical structural answers already exist before compact resume"
                )
            visual = StructuralCompactVisualAnswers.model_validate(
                _load_json(answers_path)
            )
            answers = compose_structural_visual_answers(plan, visual)
        else:
            answers = StructuralContextAnswers.model_validate(
                _load_json(answers_path)
            )
        context = assemble_structural_context(plan, answers)
        if is_compact_visual:
            _write_json(
                paths["structural_answers"],
                answers.model_dump(mode="json", by_alias=True),
            )
        _write_json(
            paths["structural_context"],
            context.model_dump(mode="json", by_alias=True),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        StructuralContextError,
        HybridFrontendCoordinatorError,
    ) as exc:
        return _fail(manifest, manifest_path, stage, exc)
    _stage(manifest, manifest_path, stage, started)

    stage = "hybrid_adapter"
    started = time.monotonic()
    try:
        partial = adapt_hybrid_ocr_report(_load_json(paths["hybrid_report"]), context)
        _write_json(
            paths["partial_observations"],
            partial.model_dump(mode="json", by_alias=True),
        )
        manifest["summary"]["partial_dimension_count"] = len(partial.dimensions)
        manifest["summary"]["partial_unresolved_count"] = len(partial.unresolved)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        HybridCaptureAdapterError,
        HybridFrontendCoordinatorError,
    ) as exc:
        return _fail(manifest, manifest_path, stage, exc)
    _stage(manifest, manifest_path, stage, started)

    stage = "reader_observation_finalizer"
    started = time.monotonic()
    try:
        partial = PartialReaderObservations.model_validate(
            _load_json(paths["partial_observations"])
        )
        observations = finalize_partial_reader_observations(partial)
        _write_json(
            paths["reader_observations"],
            observations.model_dump(mode="json", by_alias=True),
        )
        manifest["summary"]["reader_dimension_count"] = len(observations.dimensions)
        manifest["summary"]["reader_unresolved_count"] = len(observations.unresolved)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ValidationError,
        ReaderObservationFinalizationError,
        HybridFrontendCoordinatorError,
    ) as exc:
        return _fail(manifest, manifest_path, stage, exc)
    _stage(manifest, manifest_path, stage, started)

    manifest.update(phase="reader_observations_ready", status="running")
    _write_json(manifest_path, manifest)

    started = time.monotonic()
    mode_b_code, mode_b_report = run_mode_b_coordinator(
        paths["reader_observations"],
        prefix,
    )
    manifest["mode_b"] = mode_b_report
    _stage(manifest, manifest_path, "mode_b_coordinator", started)

    if mode_b_code == 0:
        manifest.update(phase="mode_b_gate_a_pass", status="success", terminal=True)
        _write_json(manifest_path, manifest)
        return 0, _report(manifest, manifest_path)
    if mode_b_code == 4:
        manifest.update(
            phase="mode_b_awaiting_confirmation",
            status="awaiting_confirmation",
            terminal=False,
            must_stop=False,
            may_retry=None,
            may_edit_structural_answers=None,
        )
        _write_json(manifest_path, manifest)
        return 4, _report(manifest, manifest_path)

    manifest.setdefault("errors", []).append(
        {
            "stage": "mode_b_coordinator",
            "message": f"Mode B coordinator returned exit code {mode_b_code}",
        }
    )
    manifest.update(
        phase="terminal_failed",
        status="failed",
        terminal=True,
        must_stop=True,
        may_retry=False,
        may_edit_structural_answers=False,
    )
    _write_json(manifest_path, manifest)
    return 1, _report(manifest, manifest_path)


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] == "resume":
        parser = argparse.ArgumentParser()
        parser.add_argument("manifest")
        parser.add_argument("structural_answers")
        parser.add_argument("mode_b_prefix")
        args = parser.parse_args(effective_argv[1:])
        code, report = resume_hybrid_frontend(
            args.manifest,
            args.structural_answers,
            args.mode_b_prefix,
        )
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument("image")
        parser.add_argument("run_directory")
        args = parser.parse_args(effective_argv)
        code, report = start_hybrid_frontend(args.image, args.run_directory)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
