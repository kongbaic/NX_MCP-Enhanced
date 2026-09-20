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


class DrawingSchemaNormalizationTests(unittest.TestCase):
    def test_dimension_to_dimensions(self) -> None:
        data = {"features": [{"id": "F1", "dimension": {"width": 2}}]}
        out, errors, changes = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual({"width": 2}, out["features"][0]["dimensions"])
        self.assertNotIn("dimension", out["features"][0])
        self.assertTrue(changes)

    def test_center_to_position_center(self) -> None:
        data = {"features": [{"id": "F1", "center": [1, 2]}]}
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual([1, 2], out["features"][0]["position"]["center"])
        self.assertNotIn("center", out["features"][0])

    def test_numeric_strings_are_normalized(self) -> None:
        data = {"features": [{"id": "F1", "dimensions": {"width": "2.5"}, "count": "2"}]}
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual(2.5, out["features"][0]["dimensions"]["width"])
        self.assertEqual(2, out["features"][0]["count"])

    def test_semantic_projection_is_unchanged(self) -> None:
        data = {"features": {"F1": {"dimension": {"width": "2"}, "center": [0, 1]}}}
        before = R.drawing_semantic_projection(data)
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual(before, R.drawing_semantic_projection(out))

    def test_ambiguous_shape_is_rejected(self) -> None:
        data = {"features": [{"id": "F1", "dimensions": [{"value": 2}]}]}
        out, errors, changes = R.normalize_drawing_schema(data)
        self.assertTrue(errors)
        self.assertEqual(data, out)
        self.assertEqual([], changes)

    def test_missing_geometry_and_evidence_are_not_added(self) -> None:
        data = {"features": [{"id": "F1", "type": "slot"}]}
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual(data, out)
        self.assertNotIn("source_ledger", out)
        self.assertNotIn("dimensions", out["features"][0])

    def test_unresolved_is_not_deleted(self) -> None:
        unresolved = [{"item": "axis", "required_for_modeling": True}]
        data = {"features": [], "unresolved": unresolved}
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual(unresolved, out["unresolved"])


if __name__ == "__main__":
    unittest.main()
