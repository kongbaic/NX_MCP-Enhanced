from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import zipfile


def _load():
    filename = Path(__file__).resolve().parents[1] / "scripts" / "audit_mode_b_resolution.py"
    spec = importlib.util.spec_from_file_location("audit_mode_b_resolution", filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(archive, run, scope, filename, payload):
    # Exercise PowerShell ZIPs that embed Windows backslash delimiters.
    prefix = f"root\\{run}\\{scope}\\{filename}"
    archive.writestr(prefix, json.dumps(payload))


def _bundle(path: Path):
    for run, accepted, blockers, draft_extra in [
        ("hybrid-run-20261009-193616-mode-b", 2, 23, 0),
        ("hybrid-run-20261009-202125-mode-b", 5, 16, 2),
    ]:
        ocr = {
            "candidate_count": 26,
            "accepted_count": accepted,
            "candidates": [
                {"candidate_id": id, "accepted_token": token}
                for id, token in (
                    [("DG12", "24"), ("DG25", "40±0.02")]
                    + ([("DG13", "24"), ("DG16", "40"), ("DG23", "18")]
                       if accepted == 5 else [])
                )
            ],
        }
        entries = [
            {"id": "relation:D002:0",
             "target": "feature:test.boundary.y",
             "reason": "center distance has no unique signed solution",
             "required_for_modeling": True},
            {"id": "U001", "field": "start_side",
             "reason": "missing entry semantics",
             "required_for_modeling": True},
        ]
        entries.extend({"id": f"U_FAKE_{i}", "required_for_modeling": True}
                       for i in range(draft_extra))
        with zipfile.ZipFile(path, "a") as archive:
            _write(archive, run, "frontend", "hybrid-ocr-report.json", ocr)
            _write(archive, run, "coordinator", run + "-mode-b-state.json",
                   {"phase": "terminal_failed",
                    "summary": {"blocking_unresolved": blockers,
                                "dimension_closure": "incomplete"}})
            _write(archive, run, "coordinator", run + "-reader-capture.json",
                   {"dimensions": [{
                       "id": "D002", "axis": "Y", "value": 24,
                       "direction": None,
                       "source_ids": ["hybrid:DG13:whole"],
                       "endpoints": [
                           {"role": "profile_boundary", "entity_id": "E01"},
                           {"role": "profile_boundary", "entity_id": "E02"},
                       ],
                   }]})
            _write(archive, run, "coordinator", run + "-semantic-draft.json",
                   {"unresolved": entries})


def test_audit_respects_windows_zip_and_separate_gate_vs_draft_counts(tmp_path):
    m = _load()
    path = tmp_path / "evidence.zip"
    _bundle(path)
    result = m.analyze_bundle(path)
    assert result["production_artifacts_modified"] is False
    assert [x["ocr"]["accepted_count"] for x in result["runs"]] == [2, 5]
    assert [x["resolver"]["reported_blocking_unresolved"]
            for x in result["runs"]] == [23, 16]
    assert [x["draft"]["expanded_blocker_records"]
            for x in result["runs"]] == [2, 4]
    assert result["comparisons"][0]["accepted_added"] == {
        "DG13": "24", "DG16": "40", "DG23": "18"
    }
    assert result["comparisons"][0]["resolver_blocker_count_change"] == -7
    dimension = result["runs"][1]["dimensions"][0]
    assert dimension["direction"] is None
    assert dimension["linked_blockers"][0]["id"] == "relation:D002:0"
    assert result["runs"][1]["draft"]["diagnostic_categories"][
        "constraint_missing_prerequisite"
    ] == 1


def test_audit_rejects_duplicate_or_missing_evidence(tmp_path):
    m = _load()
    path = tmp_path / "broken.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for _ in range(2):
            _write(archive, "hybrid-run-20261009-202125-mode-b",
                   "frontend", "hybrid-ocr-report.json", {})
    try:
        m.analyze_bundle(path)
    except ValueError as exc:
        assert "duplicate bundle entry" in str(exc)
    else:
        raise AssertionError("duplicate evidence must be rejected")
