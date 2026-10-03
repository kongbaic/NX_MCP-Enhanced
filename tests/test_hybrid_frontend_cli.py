from __future__ import annotations

import json

from nx_mcp.drawing_intelligence import cli


def test_cli_run_hybrid_frontend_preserves_structural_wait_boundary(
    monkeypatch,
    capsys,
):
    calls = {}

    def fake_start(image, run_directory):
        calls["args"] = (image, run_directory)
        return 4, {
            "schema": "hybrid-frontend-run-v1",
            "status": "awaiting_structural_context",
            "phase": "awaiting_structural_context",
            "terminal": False,
            "errors": [],
        }

    monkeypatch.setattr(cli, "start_hybrid_frontend", fake_start)

    code = cli.main(
        [
            "run-hybrid-frontend",
            "drawing.png",
            "frontend-run",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 4
    assert calls["args"] == ("drawing.png", "frontend-run")
    assert report["phase"] == "awaiting_structural_context"
    assert report["terminal"] is False


def test_cli_resume_hybrid_frontend_hands_off_to_existing_coordinator(
    monkeypatch,
    capsys,
):
    calls = {}

    def fake_resume(manifest, structural_answers, mode_b_prefix):
        calls["args"] = (manifest, structural_answers, mode_b_prefix)
        return 0, {
            "schema": "hybrid-frontend-run-v1",
            "status": "success",
            "phase": "mode_b_gate_a_pass",
            "terminal": True,
            "errors": [],
        }

    monkeypatch.setattr(cli, "resume_hybrid_frontend", fake_resume)

    code = cli.main(
        [
            "resume-hybrid-frontend",
            "hybrid-frontend-manifest.json",
            "structural-context-answers.json",
            "shkss-production",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls["args"] == (
        "hybrid-frontend-manifest.json",
        "structural-context-answers.json",
        "shkss-production",
    )
    assert report["phase"] == "mode_b_gate_a_pass"
    assert report["terminal"] is True
