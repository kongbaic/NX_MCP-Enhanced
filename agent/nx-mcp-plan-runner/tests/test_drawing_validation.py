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

    def test_schema_retry_keeps_missing_evidence_blocked(self) -> None:
        data = example()
        data["source_ledger"] = [
            item for item in data["source_ledger"] if item["id"] != "S_HOLE_AXIS"
        ]
        before = copy.deepcopy(data)
        normalized, normalization_errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], normalization_errors)
        self.assertEqual(before["source_ledger"], normalized["source_ledger"])
        gate_errors = R.check_drawing_json(normalized)
        self.assertTrue(any("required geometry field lacks evidence" in error for error in gate_errors))

    def test_unresolved_is_not_deleted(self) -> None:
        unresolved = [{"item": "axis", "required_for_modeling": True}]
        data = {"features": [], "unresolved": unresolved}
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual(unresolved, out["unresolved"])


def thread_drawing(**overrides) -> dict:
    feature = {
        "id": "T1",
        "type": "threaded_hole",
        "spec": "M6",
        "axis": "Z",
        "position": {"center": [2, 3]},
        "depth": 12,
        "axial_range": [0, 12],
        "count": 1,
        "required_for_modeling": True,
    }
    feature.update(overrides)
    return {"features": [feature], "unresolved": []}


def thread_plan(**arg_overrides) -> dict:
    args = {"body_id": "body", "center": [2, 3, 0], "diameter": 5, "depth": 12, "start_offset": 0}
    args.update(arg_overrides)
    return {"operations": [{
        "step": 1,
        "tool": "nx_hole",
        "tool_args": args,
        "thread_surrogate_use": {"feature_id": "T1", "owner_feature_id": "T1"},
    }]}


class MetricThreadSurrogateTests(unittest.TestCase):
    def test_m6_parameters(self) -> None:
        value, error = R.resolve_metric_thread_parameters("M6")
        self.assertIsNone(error)
        self.assertEqual((6.0, 1.0, 5.0), (value["nominal_diameter"], value["pitch"], value["surrogate_diameter"]))

    def test_m6x1_parameters(self) -> None:
        value, error = R.resolve_metric_thread_parameters("M6x1")
        self.assertIsNone(error)
        self.assertEqual(5.0, value["surrogate_diameter"])
        self.assertEqual("drawing_explicit", value["pitch_source"])

    def test_m8_and_m8x1_25_parameters(self) -> None:
        coarse, coarse_error = R.resolve_metric_thread_parameters("M8")
        explicit, explicit_error = R.resolve_metric_thread_parameters("M8x1.25")
        self.assertIsNone(coarse_error)
        self.assertIsNone(explicit_error)
        self.assertEqual(6.75, coarse["surrogate_diameter"])
        self.assertEqual(6.75, explicit["surrogate_diameter"])

    def test_unsupported_thread_fails_closed(self) -> None:
        value, error = R.resolve_metric_thread_parameters("UNC 1/4")
        self.assertIsNone(value)
        self.assertIn("unsupported", error)

    def test_missing_axis_center_depth_and_range_are_blocked(self) -> None:
        for changes in ({"axis": None}, {"position": {}}, {"depth": None}, {"axial_range": None}):
            _, errors = R.resolve_thread_drawing_geometries(thread_drawing(**changes))
            self.assertTrue(errors, changes)

    def test_valid_drawing_geometry_is_preserved(self) -> None:
        geometries, errors = R.resolve_thread_drawing_geometries(thread_drawing())
        self.assertEqual([], errors)
        self.assertEqual("Z", geometries[0]["axis"])
        self.assertEqual([[2.0, 3.0]], geometries[0]["transverse_centers"])
        self.assertEqual([0.0, 12.0], geometries[0]["axial_range"])

    def test_surrogate_cannot_change_axis(self) -> None:
        drawing = thread_drawing(axis="X", position={"center": [3, 4]})
        geometries, _ = R.resolve_thread_drawing_geometries(drawing)
        recipes, _ = R.resolve_thread_surrogates(drawing)
        self.assertTrue(any("changes axis" in item for item in R.thread_surrogate_plan_errors(thread_plan(), recipes, geometries)))

    def test_surrogate_cannot_change_center(self) -> None:
        drawing = thread_drawing()
        geometries, _ = R.resolve_thread_drawing_geometries(drawing)
        recipes, _ = R.resolve_thread_surrogates(drawing)
        errors = R.thread_surrogate_plan_errors(thread_plan(center=[4, 3, 0]), recipes, geometries)
        self.assertTrue(any("changes center" in item for item in errors))

    def test_surrogate_cannot_change_depth_or_range(self) -> None:
        drawing = thread_drawing()
        geometries, _ = R.resolve_thread_drawing_geometries(drawing)
        recipes, _ = R.resolve_thread_surrogates(drawing)
        errors = R.thread_surrogate_plan_errors(thread_plan(depth=11), recipes, geometries)
        self.assertTrue(any("changes depth" in item for item in errors))
        self.assertTrue(any("changes axial range" in item for item in errors))

    def test_surrogate_operation_count_must_match(self) -> None:
        drawing = thread_drawing(count=2, explicit_centers=[[2, 3], [4, 3]])
        geometries, _ = R.resolve_thread_drawing_geometries(drawing)
        recipes, _ = R.resolve_thread_surrogates(drawing)
        errors = R.thread_surrogate_plan_errors(thread_plan(), recipes, geometries)
        self.assertTrue(any("operation count" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
