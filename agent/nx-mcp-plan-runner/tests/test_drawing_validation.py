from __future__ import annotations

import copy
import io
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = ROOT / "agent" / "nx-mcp-plan-runner" / "runner.py"
EXAMPLE_PATH = ROOT / "skills" / "nx-agent" / "examples" / "example-output.json"
CANONICAL_READER_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "canonical-reader-output.json"

SPEC = importlib.util.spec_from_file_location("audited_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def canonical_reader_fixture() -> dict:
    return json.loads(CANONICAL_READER_FIXTURE.read_text(encoding="utf-8"))


def unresolved_center_fixture() -> dict:
    data = canonical_reader_fixture()
    thread = next(item for item in data["features"] if item["id"] == "F_THREAD")
    del thread["centerline"]["x"]
    data["source_ledger"] = [
        item for item in data["source_ledger"] if item["id"] != "S_THREAD_X"
    ]
    data["unresolved"].append({
        "id": "U_THREAD_X",
        "feature_id": "F_THREAD",
        "field": "centerline.x",
        "required_for_modeling": True,
    })
    data["dimension_closure"]["status"] = "incomplete"
    return data


def writer_kinds(data: dict, target: str) -> list[str]:
    writers: list[str] = []
    for item in data["source_ledger"]:
        if item.get("semantic") in R._DRAWING_RELATION_SEMANTICS:
            if target in (item.get("targets") or []):
                writers.append("relation")
            if item.get("tangent") == target:
                writers.append("relation")
        elif item.get("target") == target:
            writers.append("direct")
    writers.extend(
        "derived" for item in data["derived"] if item.get("target") == target
    )
    return writers


def source(data: dict, source_id: str) -> dict:
    return next(item for item in data["source_ledger"] if item["id"] == source_id)


def relation_fixture(*, target_edge: str = "min") -> dict:
    target_y = -30 if target_edge == "min" else 30
    return {
        "overall_dimensions": {"length_x": 100, "width_y": 80, "height_z": 60},
        "coordinate_system": {"origin": "part_center_xy_bottom_z0"},
        "features": [
            {
                "id": "F_REFERENCE",
                "type": "through_hole",
                "axis": "Y",
                "centerline": {"x": 0, "z": 20},
                "diameter": 10,
                "count": 1,
                "required_for_modeling": True,
            },
            {
                "id": "F_TARGET",
                "type": "through_hole",
                "axis": "X",
                "centerline": {"y": target_y, "z": 35},
                "diameter": 6,
                "count": 1,
                "required_for_modeling": True,
            },
            {
                "id": "F_PAIR",
                "type": "through_hole",
                "axis": "Z",
                "explicit_centers": [[-12, 30], [12, 30]],
                "diameter": 5,
                "count": 2,
                "required_for_modeling": True,
            },
        ],
        "source_ledger": [
            {"id": "S_L", "semantic": "overall_dimension", "value": 100, "target": "overall_dimensions.length_x"},
            {"id": "S_W", "semantic": "overall_dimension", "value": 80, "target": "overall_dimensions.width_y"},
            {"id": "S_H", "semantic": "overall_dimension", "value": 60, "target": "overall_dimensions.height_z"},
            {"id": "S_REF_KIND", "semantic": "feature_kind", "value": "through_hole", "target": "feature:F_REFERENCE.type"},
            {"id": "S_REF_AXIS", "semantic": "axis", "value": "Y", "target": "feature:F_REFERENCE.axis"},
            {"id": "S_REF_X", "semantic": "center_position", "value": 0, "target": "feature:F_REFERENCE.centerline.x"},
            {"id": "S_REF_Z", "semantic": "center_position", "value": 20, "target": "feature:F_REFERENCE.centerline.z"},
            {"id": "S_REF_D", "semantic": "diameter", "value": 10, "target": "feature:F_REFERENCE.diameter"},
            {"id": "S_REF_N", "semantic": "feature_count", "value": 1, "target": "feature:F_REFERENCE.count"},
            {"id": "S_TARGET_KIND", "semantic": "feature_kind", "value": "through_hole", "target": "feature:F_TARGET.type"},
            {"id": "S_TARGET_AXIS", "semantic": "axis", "value": "X", "target": "feature:F_TARGET.axis"},
            {"id": "S_TARGET_Y", "semantic": "edge_offset", "value": 10, "axis": "Y", "from": target_edge, "targets": ["feature:F_TARGET.centerline.y"]},
            {"id": "S_TARGET_D", "semantic": "diameter", "value": 6, "target": "feature:F_TARGET.diameter"},
            {"id": "S_TARGET_N", "semantic": "feature_count", "value": 1, "target": "feature:F_TARGET.count"},
            {"id": "S_CENTER_DISTANCE", "semantic": "center_distance", "value": 15, "between": ["feature:F_REFERENCE.centerline.z", "feature:F_TARGET.centerline.z"]},
            {"id": "S_PAIR_KIND", "semantic": "feature_kind", "value": "through_hole", "target": "feature:F_PAIR.type"},
            {"id": "S_PAIR_AXIS", "semantic": "axis", "value": "Z", "target": "feature:F_PAIR.axis"},
            {"id": "S_PAIR_D", "semantic": "diameter", "value": 5, "target": "feature:F_PAIR.diameter"},
            {"id": "S_PAIR_N", "semantic": "feature_count", "value": 2, "target": "feature:F_PAIR.count"},
            {"id": "S_PAIR_CENTERS", "semantic": "pattern_dimension", "value": [[-12, 30], [12, 30]], "target": "feature:F_PAIR.explicit_centers"},
            {"id": "S_PAIR_SPACING", "semantic": "center_spacing", "value": 24, "between": ["feature:F_PAIR.explicit_centers.0.0", "feature:F_PAIR.explicit_centers.1.0"]},
            {"id": "S_PAIR_Y", "semantic": "edge_offset", "value": 10, "axis": "Y", "from": "max", "targets": ["feature:F_PAIR.explicit_centers.0.1", "feature:F_PAIR.explicit_centers.1.1"]},
            {"id": "S_PAIR_SYMMETRY", "semantic": "symmetry", "feature": "F_PAIR", "axis": "X", "about": 0},
        ],
        "derived": [
            {
                "id": "D_TARGET_Z",
                "target": "feature:F_TARGET.centerline.z",
                "value": 35,
                "expr": {"op": "add", "args": [{"target": "feature:F_REFERENCE.centerline.z"}, {"source": "S_CENTER_DISTANCE"}]},
            }
        ],
        "patterns": [],
        "symmetry": [],
        "unresolved": [],
        "dimension_conflicts": [],
        "dimension_closure": {"status": "closed"},
    }


class DrawingGateATests(unittest.TestCase):
    def test_canonical_reader_fixture_passes_machine_gate_a(self) -> None:
        self.assertEqual([], R.check_drawing_json(canonical_reader_fixture()))

    def test_canonical_reader_fixture_covers_required_field_contracts(self) -> None:
        data = canonical_reader_fixture()
        targets = {
            item.get("target")
            for item in data["source_ledger"]
            if isinstance(item.get("target"), str)
        }
        self.assertTrue({
            "overall_dimensions.length_x",
            "overall_dimensions.width_y",
            "overall_dimensions.height_z",
            "feature:F_REFERENCE.type",
            "feature:F_REFERENCE.count",
            "feature:F_REFERENCE.centerline.x",
            "feature:F_SLOT.width",
            "feature:F_THREAD.spec",
            "feature:F_COUNTERBORE.hole_diameter",
            "feature:F_COUNTERBORE.counterbore_diameter",
            "feature:F_COUNTERBORE.counterbore_depth",
        }.issubset(targets))

    def test_unresolved_center_has_no_concrete_placeholder_or_writer(self) -> None:
        data = unresolved_center_fixture()
        thread = next(item for item in data["features"] if item["id"] == "F_THREAD")
        target = "feature:F_THREAD.centerline.x"
        self.assertNotIn("x", thread["centerline"])
        self.assertEqual([], writer_kinds(data, target))
        errors = R.check_drawing_json(data)
        self.assertTrue(any("requires center coordinate x" in error for error in errors))
        self.assertTrue(any("blocking_unresolved=1" in error for error in errors))

    def test_blocking_unresolved_centerline_with_concrete_value_fails(self) -> None:
        data = canonical_reader_fixture()
        feature = next(item for item in data["features"] if item["id"] == "F_REFERENCE")
        feature["centerline"]["z"] = 10
        data["unresolved"].append({
            "id": "U_REFERENCE_Z",
            "feature_id": "F_REFERENCE",
            "field": "centerline.z",
            "required_for_modeling": True,
        })
        errors = R.check_drawing_json(data)
        self.assertIn(
            "unresolved geometry has concrete placeholder: feature:F_REFERENCE.centerline.z",
            errors,
        )

    def test_blocking_unresolved_explicit_center_wildcard_with_zero_fails(self) -> None:
        data = canonical_reader_fixture()
        feature = next(item for item in data["features"] if item["id"] == "F_SPACED_PAIR")
        feature["explicit_centers"][0][1] = 0
        feature["explicit_centers"][1][1] = 0
        y_source = source(data, "S_PAIR_Y")
        y_source.update({"value": 40, "from": "min"})
        data["unresolved"].append({
            "id": "U_PAIR_Y",
            "feature_id": "F_SPACED_PAIR",
            "field": "explicit_centers[*].1",
            "required_for_modeling": True,
        })
        errors = R.check_drawing_json(data)
        for index in (0, 1):
            self.assertIn(
                "unresolved geometry has concrete placeholder: "
                f"feature:F_SPACED_PAIR.explicit_centers.{index}.1",
                errors,
            )

    def test_blocking_unresolved_profile_coordinate_with_concrete_value_fails(self) -> None:
        data = canonical_reader_fixture()
        data["unresolved"].append({
            "id": "U_PROFILE_Z",
            "field": "segments.1.z1",
            "required_for_modeling": True,
        })
        errors = R.check_drawing_json(data)
        self.assertIn(
            "unresolved geometry has concrete placeholder: profile.segments.1.z1",
            errors,
        )

    def test_nonblocking_warning_does_not_conflict_with_known_geometry(self) -> None:
        data = canonical_reader_fixture()
        data["unresolved"].append({
            "id": "W_REFERENCE_X",
            "feature_id": "F_REFERENCE",
            "field": "centerline.x",
            "required_for_modeling": False,
        })
        self.assertEqual([], R.check_drawing_json(data))

    def test_known_centers_have_exactly_one_writer_and_no_unresolved(self) -> None:
        data = canonical_reader_fixture()
        self.assertEqual(
            ["direct"], writer_kinds(data, "feature:F_REFERENCE.centerline.x")
        )
        self.assertEqual(
            ["derived"], writer_kinds(data, "feature:F_DERIVED.centerline.x")
        )
        self.assertEqual([], data["unresolved"])

    def test_reader_fixtures_do_not_mix_concrete_and_same_field_unresolved(self) -> None:
        unknown = unresolved_center_fixture()
        with self.assertRaises(KeyError):
            R._drawing_path_get(unknown, "feature:F_THREAD.centerline.x")
        self.assertTrue(any(
            item.get("feature_id") == "F_THREAD"
            and item.get("field") == "centerline.x"
            for item in unknown["unresolved"]
        ))

        known = canonical_reader_fixture()
        self.assertEqual(0, R._drawing_path_get(known, "feature:F_THREAD.centerline.x"))
        self.assertFalse(any(
            item.get("feature_id") == "F_THREAD"
            and item.get("field") == "centerline.x"
            for item in known["unresolved"]
        ))

    def test_direct_source_value_must_equal_actual_target(self) -> None:
        data = canonical_reader_fixture()
        source(data, "S_REFERENCE_X")["value"] = -19
        errors = R.check_drawing_json(data)
        self.assertTrue(any(
            "S_REFERENCE_X" in error and "value does not match" in error
            for error in errors
        ))

    def test_required_feature_type_and_count_have_provenance(self) -> None:
        data = canonical_reader_fixture()
        direct_targets = {
            item.get("target")
            for item in data["source_ledger"]
            if item.get("semantic") not in R._DRAWING_RELATION_SEMANTICS
        }
        for feature in data["features"]:
            with self.subTest(feature=feature["id"]):
                self.assertIn(f"feature:{feature['id']}.type", direct_targets)
                self.assertIn(f"feature:{feature['id']}.count", direct_targets)

    def test_canonical_profile_is_provenance_complete(self) -> None:
        data = canonical_reader_fixture()
        covered = {
            item["target"]
            for item in data["source_ledger"]
            if isinstance(item.get("target"), str)
        }
        covered.update(
            target
            for item in data["source_ledger"]
            for target in item.get("targets") or []
        )
        covered.update(item["target"] for item in data["derived"])
        for path in R._drawing_hard_paths(data["profile"]):
            with self.subTest(path=path):
                self.assertTrue(R._drawing_target_covered(f"profile.{path}", covered))

    def test_profile_join_endpoints_are_derived_not_direct(self) -> None:
        data = canonical_reader_fixture()
        direct_targets = {
            item.get("target")
            for item in data["source_ledger"]
            if item.get("semantic") not in R._DRAWING_RELATION_SEMANTICS
        }
        for target, relation in (
            ("profile.segments.1.y1", "S_PROFILE_JOIN_Y"),
            ("profile.segments.1.z1", "S_PROFILE_JOIN_Z"),
        ):
            with self.subTest(target=target):
                self.assertNotIn(target, direct_targets)
                derived = next(item for item in data["derived"] if item["target"] == target)
                self.assertIn(relation, derived["relation_refs"])

    def test_center_spacing_derived_references_opposite_endpoint(self) -> None:
        data = canonical_reader_fixture()
        relation = source(data, "S_PAIR_SPACING")
        derived = next(item for item in data["derived"] if item["id"] == "D_PAIR_X1")
        self.assertNotIn("target", relation)
        self.assertEqual(
            [
                "feature:F_SPACED_PAIR.explicit_centers.0.0",
                "feature:F_SPACED_PAIR.explicit_centers.1.0",
            ],
            relation["between"],
        )
        self.assertEqual(
            {"target": relation["between"][0]}, derived["expr"]["args"][0]
        )
        self.assertEqual({"source": "S_PAIR_SPACING"}, derived["expr"]["args"][1])
        self.assertEqual([], R.check_drawing_json(data))

    def test_canonical_reader_source_targets_resolve_and_match_semantics(self) -> None:
        data = canonical_reader_fixture()
        for item in data["source_ledger"]:
            if item["semantic"] in R._DRAWING_RELATION_SEMANTICS:
                continue
            with self.subTest(source=item["id"]):
                self.assertEqual(item["value"], R._drawing_path_get(data, item["target"]))
                self.assertTrue(R._drawing_direct_semantic_ok(data, item))

    def test_canonical_center_distance_uses_resolvable_center_paths(self) -> None:
        data = canonical_reader_fixture()
        relation = source(data, "S_CENTER_DISTANCE")
        self.assertNotIn("target", relation)
        for target in relation["between"]:
            self.assertTrue(R._drawing_is_center_target(target))
            self.assertIsInstance(R._drawing_path_get(data, target), (int, float))

    def test_free_label_center_distance_endpoints_are_rejected(self) -> None:
        data = canonical_reader_fixture()
        relation = source(data, "S_CENTER_DISTANCE")
        relation["between"] = ["left", "right"]
        errors = R.check_drawing_json(data)
        self.assertTrue(any("endpoints must be center coordinates" in error for error in errors))
        self.assertTrue(any("references missing endpoint" in error for error in errors))

    def test_dimension_conflicts_is_a_required_root(self) -> None:
        data = canonical_reader_fixture()
        del data["dimension_conflicts"]
        self.assertIn(
            "drawing JSON missing dimension_conflicts",
            R.check_drawing_json(data),
        )

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

    def test_relation_fixture_passes_machine_gate_a(self) -> None:
        self.assertEqual([], R.check_drawing_json(relation_fixture()))

    def test_direct_center_writer_only_passes(self) -> None:
        self.assertEqual([], R.check_drawing_json(example()))

    def test_derived_center_writer_only_passes(self) -> None:
        self.assertEqual([], R.check_drawing_json(relation_fixture()))

    def test_center_distance_derived_and_fake_direct_writer_conflict(self) -> None:
        data = relation_fixture()
        data["source_ledger"].append({
            "id": "S_FAKE_TARGET_Z",
            "semantic": "center_position",
            "value": 35,
            "target": "feature:F_TARGET.centerline.z",
        })
        errors = R.check_drawing_json(data)
        self.assertTrue(any(
            "feature:F_TARGET.centerline.z" in error and "writer conflict" in error
            for error in errors
        ))

    def test_edge_offset_and_fake_direct_center_writer_conflict(self) -> None:
        data = relation_fixture()
        data["source_ledger"].append({
            "id": "S_FAKE_TARGET_Y",
            "semantic": "center_position",
            "value": -30,
            "target": "feature:F_TARGET.centerline.y",
        })
        errors = R.check_drawing_json(data)
        self.assertTrue(any(
            "feature:F_TARGET.centerline.y" in error and "writer conflict" in error
            for error in errors
        ))

    def test_relation_metadata_on_same_feature_is_not_a_writer_conflict(self) -> None:
        data = relation_fixture()
        self.assertFalse(any(
            "writer conflict" in error for error in R.check_drawing_json(data)
        ))

    def test_edge_offset_preserves_min_and_max_side(self) -> None:
        self.assertEqual([], R.check_drawing_json(relation_fixture(target_edge="min")))
        self.assertEqual([], R.check_drawing_json(relation_fixture(target_edge="max")))

        mismatched = relation_fixture(target_edge="min")
        target = next(item for item in mismatched["features"] if item["id"] == "F_TARGET")
        target["centerline"]["y"] = 30
        self.assertTrue(any("edge_offset does not match" in error for error in R.check_drawing_json(mismatched)))

    def test_relation_source_cannot_use_direct_target_shape(self) -> None:
        data = relation_fixture()
        source(data, "S_TARGET_Y")["target"] = "feature:F_TARGET.centerline.y"
        self.assertTrue(any("must not use direct target" in error for error in R.check_drawing_json(data)))

    def test_center_distance_requires_center_endpoints(self) -> None:
        data = relation_fixture()
        source(data, "S_CENTER_DISTANCE")["between"][1] = "feature:F_TARGET.diameter"
        errors = R.check_drawing_json(data)
        self.assertTrue(any("endpoints must be center coordinates" in error for error in errors))

    def test_derived_target_expr_and_relation_source_are_checked(self) -> None:
        data = relation_fixture()
        derived = data["derived"][0]
        derived["expr"]["args"][1] = {"const": 14}
        errors = R.check_drawing_json(data)
        self.assertTrue(any("expr does not match" in error for error in errors))
        self.assertTrue(any("without relation evidence" in error for error in errors))

    def test_hole_axis_requires_transverse_center_coordinates(self) -> None:
        valid = {
            "X": {"y": 1, "z": 2},
            "Y": {"x": 1, "z": 2},
            "Z": {"x": 1, "y": 2},
        }
        missing = {
            "X": {"y": 1},
            "Y": {"x": 1},
            "Z": {"x": 1},
        }
        for axis in ("X", "Y", "Z"):
            errors: list[str] = []
            R._drawing_check_feature_structure(errors, {"id": axis, "type": "threaded_hole", "axis": axis, "centerline": valid[axis]})
            self.assertEqual([], errors, axis)
            R._drawing_check_feature_structure(errors := [], {"id": axis, "type": "threaded_hole", "axis": axis, "centerline": missing[axis]})
            self.assertTrue(errors, axis)

    def test_explicit_centers_are_tracked_per_coordinate(self) -> None:
        paths = R._drawing_hard_paths({"explicit_centers": [[-3, 4], [3, 4]]})
        self.assertEqual(
            {
                "explicit_centers.0.0",
                "explicit_centers.0.1",
                "explicit_centers.1.0",
                "explicit_centers.1.1",
            },
            paths,
        )

    def test_count_and_single_axis_spacing_do_not_create_other_axis(self) -> None:
        data = relation_fixture()
        data["source_ledger"] = [
            item for item in data["source_ledger"]
            if item["id"] not in {"S_PAIR_CENTERS", "S_PAIR_Y"}
        ]
        errors = R.check_drawing_json(data)
        self.assertTrue(any("explicit_centers.0.1" in error for error in errors))
        self.assertTrue(any("explicit_centers.1.1" in error for error in errors))

    def test_reader_and_planner_rules_are_locked(self) -> None:
        reader = (ROOT / "skills" / "nx-agent" / "references" / "drawing-reader.md").read_text(encoding="utf-8")
        quick = (ROOT / "skills" / "nx-agent" / "references" / "nx-drawing-rules.md").read_text(encoding="utf-8")
        planner = (ROOT / "skills" / "nx-agent" / "references" / "modeling-planner.md").read_text(encoding="utf-8")
        for token in (
            "view-local",
            "projection alignment",
            "leader/witness endpoint",
            "`axis=X`→Y/Z",
            "center_distance / center_spacing",
            "opposite endpoint target",
            "`edge_offset` 不得作为 derived expression",
            "`profile_dimension` 只用于两个 endpoints",
            "thread projection 必须先按 projection alignment",
            "`from=min`: `coordinate = min_edge + value`；`from=max`: `coordinate = max_edge - value`",
            "而不是因缺少 direct dimension 进入 blocking unresolved",
            "feature:F_GROUP.explicit_centers.0.1",
        ):
            self.assertIn(token, reader)
        for token in (
            "view-local evidence → feature association → dimension ownership → relation/derived → global coordinates",
            "axial projection candidate",
            "axis=X→Y/Z",
            "datum→centerline",
            "centerline↔centerline",
            "profile boundary↔profile boundary",
        ):
            self.assertIn(token, quick)
        for token in ("同轴复合孔 centerline 是不可变输入", "不得平移", "改正负号", "自动镜像"):
            self.assertIn(token, planner)

    def test_validator_does_not_mutate_drawing(self) -> None:
        data = example()
        before = copy.deepcopy(data)
        R.check_drawing_json(data)
        self.assertEqual(before, data)


class DrawingSchemaNormalizationTests(unittest.TestCase):
    def test_normalizer_does_not_rename_noncanonical_semantic_fields(self) -> None:
        data = {
            "overall_dimensions": {"x": 10, "y": 20, "z": 30},
            "features": [{
                "id": "F1",
                "kind": "threaded_hole",
                "center_x": 1,
                "open_from_z": 2,
                "thread_spec": "M6",
                "x_start": 3,
                "through_diameter": 4,
                "cbore_diameter": 8,
                "cbore_depth": 2,
            }],
        }
        normalized, errors, changes = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual([], changes)
        self.assertEqual(data, normalized)

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

    def test_schema_only_normalization_can_continue_to_gate_a(self) -> None:
        data = example()
        boss = next(item for item in data["features"] if item["id"] == "F_BOSS")
        boss["center"] = boss.pop("position")["center"]
        normalized, errors, changes = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertTrue(changes)
        self.assertEqual([], R.check_drawing_json(normalized))

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

    def test_failed_validation_does_not_overwrite_original_drawing(self) -> None:
        data = {"features": [{"id": "F1", "dimensions": [{"value": 2}]}]}
        original = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "drawing.json"
            path.write_text(original, encoding="utf-8")
            args = type("Args", (), {"drawing": str(path)})()
            with redirect_stdout(io.StringIO()):
                result = R._cmd_validate_drawing(args)
            self.assertEqual(1, result)
            self.assertEqual(original, path.read_text(encoding="utf-8"))

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
