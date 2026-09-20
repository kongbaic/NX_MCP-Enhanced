from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = ROOT / "agent" / "nx-mcp-plan-runner" / "runner.py"
EXAMPLE_PATH = ROOT / "skills" / "nx-agent" / "examples" / "example-output.json"

SPEC = importlib.util.spec_from_file_location("audited_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def source(data: dict, source_id: str) -> dict:
    return next(item for item in data["source_ledger"] if item["id"] == source_id)


class DrawingGateATests(unittest.TestCase):
    def test_example_passes_machine_gate_a(self) -> None:
        self.assertEqual([], R.check_drawing_json(example()))

    def test_bbox_inconsistent_drawing_fails(self) -> None:
        data = example()
        boss = next(item for item in data["features"] if item["id"] == "F_BOSS")
        boss["position"]["center"] = [50, 0]
        source(data, "S_BOSS_C")["value"] = [50, 0]
        self.assertTrue(R.check_drawing_json(data))

    def test_center_distance_back_check_fails(self) -> None:
        data = example()
        data["source_ledger"].append({
            "id": "S_DISTANCE",
            "semantic": "center_distance",
            "value": 12,
            "between": [
                "feature:F_BOSS.position.center.0",
                "feature:F_HOLE.position.center.0",
            ],
        })
        self.assertTrue(R.check_drawing_json(data))

    def test_symmetry_back_check_fails(self) -> None:
        data = example()
        hole = next(item for item in data["features"] if item["id"] == "F_HOLE")
        hole["count"] = 2
        hole["explicit_centers"] = [[-5, 0], [7, 0]]
        source(data, "S_HOLE_N")["value"] = 2
        data["source_ledger"].extend([
            {"id": "S_HOLE_CENTERS", "semantic": "pattern_dimension", "value": [[-5, 0], [7, 0]], "target": "feature:F_HOLE.explicit_centers"},
            {"id": "S_HOLE_SYM", "semantic": "symmetry", "feature": "F_HOLE", "axis": "x", "about": 0},
        ])
        self.assertTrue(R.check_drawing_json(data))

    def test_count_two_cannot_expand_to_four(self) -> None:
        data = example()
        hole = next(item for item in data["features"] if item["id"] == "F_HOLE")
        hole["count"] = 2
        hole["explicit_centers"] = [[-5, 0], [5, 0], [-5, 5], [5, 5]]
        source(data, "S_HOLE_N")["value"] = 2
        data["source_ledger"].append({"id": "S_HOLE_CENTERS", "semantic": "pattern_dimension", "value": hole["explicit_centers"], "target": "feature:F_HOLE.explicit_centers"})
        self.assertTrue(R.check_drawing_json(data))

    def test_required_geometry_needs_evidence(self) -> None:
        data = example()
        data["source_ledger"] = [item for item in data["source_ledger"] if item["id"] != "S_HOLE_AXIS"]
        self.assertTrue(R.check_drawing_json(data))

    def test_blocking_unresolved_fails(self) -> None:
        data = example()
        data["unresolved"] = [{"item": "axis", "required_for_modeling": True}]
        self.assertTrue(R.check_drawing_json(data))

    def test_dimension_conflict_fails(self) -> None:
        data = example()
        data["dimension_conflicts"] = [{"item": "width"}]
        self.assertTrue(R.check_drawing_json(data))

    def test_reader_and_planner_rules_are_locked(self) -> None:
        reader = (ROOT / "skills" / "nx-agent" / "references" / "drawing-reader.md").read_text(encoding="utf-8")
        planner = (ROOT / "skills" / "nx-agent" / "references" / "modeling-planner.md").read_text(encoding="utf-8")
        for token in ("隐藏矩形", "slot.width", "center distance", "不得因为 overall bbox 对称", "不能再翻倍"):
            self.assertIn(token, reader)
        for token in ("同轴复合孔 centerline 是不可变输入", "不得平移", "改正负号", "自动镜像"):
            self.assertIn(token, planner)

    def test_validator_does_not_mutate_drawing(self) -> None:
        data = example()
        before = copy.deepcopy(data)
        R.check_drawing_json(data)
        self.assertEqual(before, data)


if __name__ == "__main__":
    unittest.main()
