from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nx_mcp.drawing_intelligence import hybrid_frontend_coordinator as coordinator
from nx_mcp.drawing_intelligence.reader_semantic_answers import PartialReaderObservations


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _install_start_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_prepare(image: Path, run_dir: Path) -> dict:
        reader_input = run_dir / "reader-input.json"
        _write_json(
            reader_input,
            {
                "schema": "reader-input-v1",
                "regions": [
                    {"region_id": "R1", "crop_path": str(run_dir / "R1.png")},
                    {"region_id": "R2", "crop_path": str(run_dir / "R2.png")},
                ],
            },
        )
        return {
            "reader_input": str(reader_input),
            "summary": {"region_count": 2},
        }

    def fake_ocr(reader_input: Path, out: Path, *, artifact_dir: Path) -> dict:
        assert reader_input.name == "reader-input.json"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        _write_json(out, {"schema": "dg-hybrid-ocr-bakeoff-v2", "candidates": []})
        return {
            "candidate_count": 26,
            "accepted_count": 5,
            "unresolved_count": 21,
            "ocr_elapsed_s": {"total": 1.18},
        }

    monkeypatch.setattr(coordinator, "prepare_reader_input", fake_prepare)
    monkeypatch.setattr(coordinator, "run_hybrid_ocr", fake_ocr)


def _start_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str = "run",
) -> tuple[Path, Path]:
    monkeypatch.setenv("NX_MCP_WORKSPACE", str(tmp_path))
    image = tmp_path / f"{name}.png"
    image.write_bytes(b"image")
    run_dir = tmp_path / f"{name}-frontend"
    _install_start_fakes(monkeypatch)

    code, report = coordinator.start_hybrid_frontend(image, run_dir)

    assert code == 4
    assert report["phase"] == "awaiting_structural_context"
    manifest = Path(report["manifest"])
    assert manifest.is_file()
    assert Path(report["artifacts"]["structural_queries"]).is_file()
    return manifest, run_dir


def _write_structural_answers(path: Path) -> None:
    _write_json(
        path,
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
                        },
                        {
                            "axis": "Z",
                            "value": 66,
                            "evidence": ["structural:R2:crop"],
                        },
                    ],
                    "rotational_symmetry": {
                        "status": "not_established",
                        "evidence": ["structural:R2:crop"],
                    },
                    "unresolved": [],
                },
            ],
        },
    )


class _FullObservations:
    dimensions: list[object] = []
    unresolved: list[object] = []

    def model_dump(self, *, mode: str, by_alias: bool) -> dict:
        assert mode == "json"
        assert by_alias is True
        return {
            "schema": "reader-observations-v1",
            "overall_dimensions": {
                "length_x": 40,
                "width_y": 32,
                "height_z": 66,
            },
            "views": [],
            "entities": [],
            "associations": [],
            "values": [],
            "dimensions": [],
            "datum_alignments": [],
            "centerline_alignments": [],
            "observations": [],
            "unresolved": [],
        }


def _install_resume_fakes(
    monkeypatch: pytest.MonkeyPatch,
    mode_b_code: int,
) -> None:
    monkeypatch.setattr(
        coordinator,
        "adapt_hybrid_ocr_report",
        lambda report, context: PartialReaderObservations(),
    )
    monkeypatch.setattr(
        coordinator,
        "finalize_partial_reader_observations",
        lambda partial: _FullObservations(),
    )
    monkeypatch.setattr(
        coordinator,
        "run_mode_b_coordinator",
        lambda observations, prefix: (
            mode_b_code,
            {
                "schema": "mode-b-coordinator-state-v1",
                "status": "success" if mode_b_code == 0 else "awaiting_confirmation",
                "phase": "gate_a_pass" if mode_b_code == 0 else "awaiting_confirmation",
                "state": str(Path(str(prefix) + "-mode-b-state.json")),
            },
        ),
    )


def test_start_runs_deterministic_prep_ocr_and_structural_query_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest, run_dir = _start_ready(tmp_path, monkeypatch)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["summary"]["prep"]["region_count"] == 2
    assert payload["summary"]["hybrid_ocr"]["candidate_count"] == 26
    assert payload["summary"]["hybrid_ocr"]["accepted_count"] == 5
    assert payload["summary"]["hybrid_ocr"]["unresolved_count"] == 21
    assert payload["summary"]["structural_query_count"] == 2
    assert payload["summary"]["structural_unique_image_count"] == 2
    assert payload["summary"]["structural_labeled_target_count"] == 0
    assert payload["summary"]["structural_seeded_target_count"] == 0
    assert payload["summary"]["structural_agent_pending_target_count"] == 0
    assert (run_dir / "hybrid-ocr-report.json").is_file()


@pytest.mark.parametrize(
    ("mode_b_code", "expected_code", "expected_phase", "expected_terminal"),
    [
        (0, 0, "mode_b_gate_a_pass", True),
        (4, 4, "mode_b_awaiting_confirmation", False),
        (2, 1, "terminal_failed", True),
    ],
)
def test_resume_builds_reader_observations_and_hands_off_to_mode_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode_b_code: int,
    expected_code: int,
    expected_phase: str,
    expected_terminal: bool,
):
    manifest, run_dir = _start_ready(tmp_path, monkeypatch, f"resume-{mode_b_code}")
    answers = run_dir / "structural-context-answers.json"
    _write_structural_answers(answers)
    _install_resume_fakes(monkeypatch, mode_b_code)

    prefix = tmp_path / f"mode-b-{mode_b_code}"
    code, report = coordinator.resume_hybrid_frontend(manifest, answers, prefix)

    assert code == expected_code
    assert report["phase"] == expected_phase
    assert report["terminal"] is expected_terminal
    assert (run_dir / "hybrid-adapter-context.json").is_file()
    assert (run_dir / "partial-reader-observations.json").is_file()
    assert (run_dir / "reader-observations.json").is_file()
    if mode_b_code == 2:
        assert report["errors"][-1]["stage"] == "mode_b_coordinator"


def test_structural_context_wait_timing_spans_agent_answer_write_and_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    timestamps = iter([100.0, 107.0])
    monkeypatch.setattr(coordinator.time, "time", lambda: next(timestamps))

    manifest, run_dir = _start_ready(
        tmp_path,
        monkeypatch,
        "structural-wall-time",
    )

    start_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert start_payload["timing_markers_epoch_s"][
        "structural_context_wait_started"
    ] == 100.0

    answers = run_dir / "structural-context-answers.json"
    _write_structural_answers(answers)
    os.utime(answers, (105.0, 105.0))
    _install_resume_fakes(monkeypatch, 0)

    code, report = coordinator.resume_hybrid_frontend(
        manifest,
        answers,
        tmp_path / "structural-wall-time-mode-b",
    )

    assert code == 0
    assert report["timing_seconds"]["structural_context_agent_wait"] == 5.0
    assert report["timing_seconds"]["structural_context_resume_lag"] == 2.0


def test_start_blocks_without_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("NX_MCP_WORKSPACE", raising=False)
    image = tmp_path / "drawing.png"
    image.write_bytes(b"image")

    code, report = coordinator.start_hybrid_frontend(image, tmp_path / "run")

    assert code == 2
    assert report["phase"] == "start_check"
    assert "NX_MCP_WORKSPACE is missing" in report["errors"][0]


def test_start_blocks_existing_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("NX_MCP_WORKSPACE", str(tmp_path))
    image = tmp_path / "drawing.png"
    image.write_bytes(b"image")
    run_dir = tmp_path / "existing"
    run_dir.mkdir()

    code, report = coordinator.start_hybrid_frontend(image, run_dir)

    assert code == 2
    assert "already exists" in report["errors"][0]


def test_start_fails_closed_when_prep_does_not_write_expected_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("NX_MCP_WORKSPACE", str(tmp_path))
    image = tmp_path / "drawing.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(
        coordinator,
        "prepare_reader_input",
        lambda image, run_dir: {"reader_input": str(run_dir / "missing.json")},
    )

    code, report = coordinator.start_hybrid_frontend(image, tmp_path / "bad-prep")

    assert code == 1
    assert report["phase"] == "terminal_failed"
    assert report["errors"][0]["stage"] == "deterministic_reader_prep"


def test_start_fails_closed_when_ocr_report_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("NX_MCP_WORKSPACE", str(tmp_path))
    image = tmp_path / "drawing.png"
    image.write_bytes(b"image")
    _install_start_fakes(monkeypatch)
    monkeypatch.setattr(
        coordinator,
        "run_hybrid_ocr",
        lambda reader_input, out, artifact_dir: {},
    )

    code, report = coordinator.start_hybrid_frontend(image, tmp_path / "bad-ocr")

    assert code == 1
    assert report["errors"][0]["stage"] == "hybrid_ocr"


def test_resume_is_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest, run_dir = _start_ready(tmp_path, monkeypatch, "once")
    answers = run_dir / "structural-context-answers.json"
    _write_structural_answers(answers)
    _install_resume_fakes(monkeypatch, 0)

    first_code, _ = coordinator.resume_hybrid_frontend(
        manifest,
        answers,
        tmp_path / "once-mode-b",
    )
    second_code, second_report = coordinator.resume_hybrid_frontend(
        manifest,
        answers,
        tmp_path / "unused-mode-b",
    )

    assert first_code == 0
    assert second_code == 3
    assert second_report["terminal"] is True
    assert second_report["must_stop"] is True
    assert second_report["may_retry"] is False
    assert second_report["may_edit_structural_answers"] is False
    assert second_report["reason"] == "invalid_resume_phase"


def test_resume_rejects_structural_answers_from_another_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest, _ = _start_ready(tmp_path, monkeypatch, "current-run")
    stale_answers = tmp_path / "previous-run" / "structural-context-answers.json"
    _write_structural_answers(stale_answers)

    code, report = coordinator.resume_hybrid_frontend(
        manifest,
        stale_answers,
        tmp_path / "mode-b",
    )

    assert code == 2
    assert report["phase"] == "resume_check"
    assert "current Hybrid Frontend run artifact" in report["errors"][0]


def test_resume_blocks_missing_answers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest, _ = _start_ready(tmp_path, monkeypatch, "missing-answer")

    code, report = coordinator.resume_hybrid_frontend(
        manifest,
        tmp_path / "does-not-exist.json",
        tmp_path / "mode-b",
    )

    assert code == 2
    assert report["phase"] == "resume_check"


def test_resume_fails_closed_on_unresolved_structural_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest, run_dir = _start_ready(tmp_path, monkeypatch, "structural-fail")
    answers = run_dir / "structural-context-answers.json"
    _write_structural_answers(answers)
    payload = json.loads(answers.read_text(encoding="utf-8"))
    payload["answers"][0]["unresolved"] = ["view is ambiguous"]
    _write_json(answers, payload)

    code, report = coordinator.resume_hybrid_frontend(
        manifest,
        answers,
        tmp_path / "mode-b",
    )

    assert code == 1
    assert report["phase"] == "terminal_failed"
    assert report["terminal"] is True
    assert report["must_stop"] is True
    assert report["may_retry"] is False
    assert report["may_edit_structural_answers"] is False
    assert report["errors"][-1]["stage"] == "structural_context"

    second_code, second_report = coordinator.resume_hybrid_frontend(
        manifest,
        answers,
        tmp_path / "mode-b-second-attempt",
    )
    assert second_code == 3
    assert second_report["terminal"] is True
    assert second_report["must_stop"] is True
    assert second_report["may_retry"] is False
    assert second_report["may_edit_structural_answers"] is False
    assert second_report["reason"] == "invalid_resume_phase"
