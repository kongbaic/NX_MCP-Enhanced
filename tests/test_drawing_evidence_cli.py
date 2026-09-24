from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _evidence(*, signed: bool) -> dict:
    relation = {
        "id": "R_SPACING",
        "kind": "center_spacing",
        "axis": "X",
        "value": 20,
        "targets": [
            "feature:F_A.centerline.x",
            "feature:F_B.centerline.x",
        ],
    }
    if signed:
        relation["direction"] = 1

    return {
        "schema_version": "1.0",
        "coordinate_system": "overall_min_xyz",
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 32,
            "height_z": 66,
        },
        "direct_values": [
            {"id": "OX", "target": "overall_dimensions.length_x", "value": 40},
            {"id": "OY", "target": "overall_dimensions.width_y", "value": 32},
            {"id": "OZ", "target": "overall_dimensions.height_z", "value": 66},
            {"id": "AK", "target": "feature:F_A.type", "value": "through_hole"},
            {"id": "AA", "target": "feature:F_A.axis", "value": "Z"},
            {"id": "AX", "target": "feature:F_A.centerline.x", "value": -10},
            {"id": "AY", "target": "feature:F_A.centerline.y", "value": 0},
            {"id": "AD", "target": "feature:F_A.diameter", "value": 5},
            {"id": "AN", "target": "feature:F_A.count", "value": 1},
            {"id": "BK", "target": "feature:F_B.type", "value": "through_hole"},
            {"id": "BA", "target": "feature:F_B.axis", "value": "Z"},
            {"id": "BY", "target": "feature:F_B.centerline.y", "value": 0},
            {"id": "BD", "target": "feature:F_B.diameter", "value": 5},
            {"id": "BN", "target": "feature:F_B.count", "value": 1},
        ],
        "relations": [relation],
        "required_targets": ["feature:F_B.centerline.x"],
    }


def _run(tmp_path: Path, payload: dict):
    evidence = tmp_path / "drawing-evidence.json"
    draft = tmp_path / "semantic-draft.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "resolve",
            str(evidence),
            str(draft),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, draft


def test_cli_writes_closed_semantic_draft_for_unique_solution(tmp_path):
    completed, draft = _run(tmp_path, _evidence(signed=True))

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    data = json.loads(draft.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["dimension_closure"] == "closed"
    feature_b = next(item for item in data["features"] if item["id"] == "F_B")
    assert feature_b["centerline"]["x"] == 10
    assert data["dimension_closure"] == {"status": "closed"}


def test_cli_writes_incomplete_draft_but_returns_nonzero_for_ambiguity(tmp_path):
    completed, draft = _run(tmp_path, _evidence(signed=False))

    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    data = json.loads(draft.read_text(encoding="utf-8"))
    assert report["written"] is True
    assert report["ok"] is False
    assert report["blocking_unresolved"] >= 1
    assert data["dimension_closure"] == {"status": "incomplete"}
    assert any(
        item.get("target") == "feature:F_B.centerline.x"
        for item in data["unresolved"]
    )
