from __future__ import annotations

import copy
import io
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


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

    def test_modeling_body_gate_accepts_evidence_backed_profile(self) -> None:
        self.assertEqual([], R._drawing_modeling_body_errors(canonical_reader_fixture()))

    def test_modeling_body_gate_rejects_subtractive_only_drawing(self) -> None:
        data = canonical_reader_fixture()
        data.pop("profile", None)
        data["source_ledger"] = [
            item
            for item in data["source_ledger"]
            if not str(item.get("target") or "").startswith("profile.")
            and not any(
                str(target).startswith("profile.")
                for target in item.get("targets") or []
            )
        ]
        data["derived"] = [
            item
            for item in data["derived"]
            if not str(item.get("target") or "").startswith("profile.")
        ]
        errors = R._drawing_modeling_body_errors(data)
        self.assertEqual(1, len(errors))
        self.assertIn("lacks body-defining geometry", errors[0])


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

    def test_start_side_semantic_matches_start_side_target(self) -> None:
        data = {
            "features": [
                {
                    "id": "F_RECESS",
                    "type": "counterbore_hole",
                    "axis": "X",
                    "start_side": "max",
                }
            ]
        }
        source_item = {
            "id": "S_SIDE",
            "semantic": "start_side",
            "value": "max",
            "target": "feature:F_RECESS.start_side",
        }

        self.assertTrue(R._drawing_direct_semantic_ok(data, source_item))

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

    def test_transverse_recessed_holes_require_start_side(self) -> None:
        centers = {
            "X": {"y": 8, "z": 58},
            "Y": {"x": 0, "z": 40},
        }
        for feature_type in ("counterbore_hole", "countersink_hole"):
            for axis in ("X", "Y"):
                base = {
                    "id": f"{feature_type}-{axis}",
                    "type": feature_type,
                    "axis": axis,
                    "centerline": centers[axis],
                }
                R._drawing_check_feature_structure(errors := [], base)
                self.assertTrue(
                    any("requires start_side/side min|max" in error for error in errors),
                    (feature_type, axis, errors),
                )
                for field in ("start_side", "side"):
                    for value in ("min", "max"):
                        feature = dict(base)
                        feature[field] = value
                        R._drawing_check_feature_structure(errors := [], feature)
                        self.assertEqual(
                            [],
                            errors,
                            (feature_type, axis, field, value),
                        )

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
        top = (ROOT / "skills" / "nx-agent" / "SKILL.md").read_text(encoding="utf-8")
        reader = (ROOT / "skills" / "nx-agent" / "references" / "drawing-reader.md").read_text(encoding="utf-8")
        quick = (ROOT / "skills" / "nx-agent" / "references" / "nx-drawing-rules.md").read_text(encoding="utf-8")
        planner = (ROOT / "skills" / "nx-agent" / "references" / "modeling-planner.md").read_text(encoding="utf-8")
        pipeline = (ROOT / "skills" / "nx-agent" / "references" / "pipeline-contract.md").read_text(encoding="utf-8")
        for token in (
            "唯一 semantic decision chain",
            "Annotation / same-feature projection association",
            "Physical endpoint ownership",
            "Direct coordinate / evidence-backed relation lock",
            "Eligible derived",
            "Required HARD feature inventory",
            "Semantic draft assembly",
            "First-write semantic check",
            "只写一次 `semantic-draft.json`",
            "association 本身不建立不同 feature 之间的数值关系",
            "不得在全局坐标转换时重分类",
            "必须穷尽整图中的 same-feature orthographic candidates",
            "annotation 的数值不得进入后续任何 geometry completion 或 concrete coordinate",
            "不得作为裸 numeric operand 或 mental arithmetic 输入",
            "start face 只能在 axis 锁定后解释",
            "coordinate 正确不能替代该 ownership",
            "这些 centers 不要求位于同一个 feature object",
            "direct witness 优先于所有 arithmetic",
            "view→projection geometry→annotation endpoints",
            "不得在同一draft中混入 `0..extent` X/Y frame",
            "只写 `connected_to / notes / reason / evidence` 不构成 relation coverage",
            "`upper_tangent` 或 `lower_tangent`",
            "feature:<id>.centerline.<axis>",
            "feature:<id>.explicit_centers.<index>.<coordinate-index>",
            "不得把歧义path交给canonicalizer猜测",
            "`center_spacing/center_distance`使用`value + between=[两个真实center coordinate paths]`",
            "`edge_offset`使用`value + axis + from + targets`",
            "看见孔位所在的面也不能代替 orthographic axis evidence",
            "blocking unresolved不得同时带猜测的concrete value",
        ):
            self.assertIn(token, reader)
        for forbidden in (
            "Reader不承担path prefix",
            "alignment、connected、tangent",
            "representation spelling 交给 deterministic canonicalizer",
        ):
            self.assertNotIn(forbidden, reader)
        for token in (
            "只提供视觉识别与制图符号词典",
            "Front / 正视图",
            "axial projection candidate",
            "projection alignment",
            "extension / witness line",
            "centerline / center mark",
            "M-series thread / through hole / counterbore / countersink",
            "pattern/symmetry 不得在本文件中创建坐标",
            "连续 profile segments",
            "Closure is validation only",
        ):
            self.assertIn(token, quick)
        for forbidden in (
            "view-local evidence → feature association → dimension ownership → relation/derived → global coordinates",
            "ownership precedence",
            "dimension-bearing number",
            "Canonical serialization / validation",
            "relation coverage 后没有额外 direct/derived writer",
        ):
            self.assertNotIn(forbidden, quick)
        for token in (
            "Reader 只能一次写出 `semantic-draft.json`",
            "`drawing.json` 只能由该命令成功生成",
            "process exit code = 0",
            "`written=true`",
            "`output_exists=true`",
            "immutable first-pass semantic artifact",
            "单独调用 `validate-drawing` 绕过 canonicalizer",
        ):
            self.assertIn(token, top)
        for token in (
            "当前 semantic-draft.json → canonicalize-drawing → 当前 drawing.json",
            "其它结果`BLOCKED / STOP`",
            "drawing不存在，STOP",
        ):
            self.assertIn(token, pipeline)
        for forbidden in (
            "直接覆盖写入当前 `drawing.json`",
            "当前 drawing interpretation → 当前 drawing.json → validate-drawing",
            "首次 current `drawing.json`",
        ):
            self.assertNotIn(forbidden, top + reader + pipeline)
        for token in (
            "`canonicalize-drawing`成功生成的canonical `drawing.json`",
            "禁止消费`semantic-draft.json`",
            "Agent手写或仅经独立`validate-drawing`通过的drawing",
            "同轴复合孔 centerline 是不可变输入",
            "不得平移",
            "改正负号",
            "自动镜像",
        ):
            self.assertIn(token, planner)

    def test_validator_does_not_mutate_drawing(self) -> None:
        data = example()
        before = copy.deepcopy(data)
        R.check_drawing_json(data)
        self.assertEqual(before, data)


class DrawingSchemaNormalizationTests(unittest.TestCase):
    @staticmethod
    def run_canonicalize(draft: Path, output: Path) -> tuple[int, dict]:
        args = type("Args", (), {"draft": str(draft), "out": str(output)})()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            return_code = R._cmd_canonicalize_drawing(args)
        return return_code, json.loads(stdout.getvalue())

    @staticmethod
    def write_stale_output(output: Path) -> bytes:
        stale = canonical_reader_fixture()
        stale["stale_output_test_sentinel"] = "STALE_SENTINEL"
        output.write_text(json.dumps(stale, ensure_ascii=False, indent=2), encoding="utf-8")
        return output.read_bytes()

    @staticmethod
    def range_alias_data() -> dict:
        return {
            "features": [{"id": "F_SLOT", "range_z": {"from": "5", "to": 15}}],
            "source_ledger": [
                {"id": "S_BOTTOM", "target": "feature:F_SLOT.range_z.from"},
                {
                    "id": "R_TARGETS",
                    "semantic": "edge_offset",
                    "targets": ["feature:F_SLOT.range_z.from"],
                },
                {
                    "id": "R_BETWEEN",
                    "semantic": "center_spacing",
                    "between": [
                        "feature:F_SLOT.range_z.from",
                        "feature:F_SLOT.range_z.to",
                    ],
                },
                {
                    "id": "R_LINKS",
                    "semantic": "alignment",
                    "links": ["F_SLOT.range_z.from", "feature:F_SLOT.range_z.to"],
                },
            ],
            "relations": [
                {
                    "id": "R_TOP_LEVEL",
                    "targets": ["feature:F_SLOT.range_z.to"],
                    "between": [
                        "feature:F_SLOT.range_z.from",
                        "feature:F_SLOT.range_z.to",
                    ],
                    "links": [
                        "feature:F_SLOT.range_z.from",
                        "feature:F_SLOT.range_z.to",
                    ],
                }
            ],
            "derived": [
                {
                    "id": "D_TOP",
                    "target": "feature:F_SLOT.range_z.to",
                    "expr": {"target": "feature:F_SLOT.range_z.from"},
                    "refs": ["feature:F_SLOT.range_z.to"],
                }
            ],
            "unresolved": [
                {"id": "U_BOTTOM", "target": "feature:F_SLOT.range_z.from"}
            ],
        }

    @staticmethod
    def gate_a_range_alias_data() -> dict:
        data = canonical_reader_fixture()
        slot = next(item for item in data["features"] if item["id"] == "F_SLOT")
        slot["range_z"] = {"from": 5, "to": 15}
        data["source_ledger"].extend([
            {
                "id": "S_SLOT_BOTTOM",
                "semantic": "position_dimension",
                "value": 5,
                "target": "feature:F_SLOT.range_z.from",
            },
            {
                "id": "S_SLOT_TOP",
                "semantic": "position_dimension",
                "value": 15,
                "target": "feature:F_SLOT.range_z.to",
            },
        ])
        return data

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

    def test_range_z_and_source_target_are_canonicalized_together(self) -> None:
        data = self.range_alias_data()
        out, errors, changes = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertTrue(changes)
        feature = out["features"][0]
        self.assertNotIn("range_z", feature)
        self.assertEqual(5, feature["bottom_z"])
        self.assertEqual(15, feature["top_z"])
        self.assertEqual("feature:F_SLOT.bottom_z", out["source_ledger"][0]["target"])

    def test_all_declared_reference_shapes_follow_range_z_rewrite(self) -> None:
        out, errors, _ = R.normalize_drawing_schema(self.range_alias_data())
        self.assertEqual([], errors)
        serialized = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("range_z", serialized)
        self.assertEqual(
            ["feature:F_SLOT.bottom_z"], out["source_ledger"][1]["targets"]
        )
        self.assertEqual(
            ["feature:F_SLOT.bottom_z", "feature:F_SLOT.top_z"],
            out["source_ledger"][2]["between"],
        )
        self.assertEqual(
            ["feature:F_SLOT.bottom_z", "feature:F_SLOT.top_z"],
            out["source_ledger"][3]["links"],
        )
        self.assertEqual("feature:F_SLOT.top_z", out["derived"][0]["target"])
        self.assertEqual(
            "feature:F_SLOT.bottom_z", out["derived"][0]["expr"]["target"]
        )
        self.assertEqual(["feature:F_SLOT.top_z"], out["derived"][0]["refs"])
        self.assertEqual("feature:F_SLOT.bottom_z", out["unresolved"][0]["target"])

    def test_canonicalization_preserves_numeric_and_id_inventories(self) -> None:
        data = self.range_alias_data()
        before = R.drawing_preservation_inventory(data)
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual(before, R.drawing_preservation_inventory(out))
        self.assertEqual(
            R.drawing_semantic_projection(data), R.drawing_semantic_projection(out)
        )
        self.assertEqual(
            ["F_SLOT"], [item["id"] for item in out["features"]]
        )
        self.assertEqual(
            ["S_BOTTOM", "R_TARGETS", "R_BETWEEN", "R_LINKS"],
            [item["id"] for item in out["source_ledger"]],
        )
        self.assertEqual(["R_TOP_LEVEL"], [item["id"] for item in out["relations"]])
        self.assertEqual(["D_TOP"], [item["id"] for item in out["derived"]])
        self.assertEqual(["U_BOTTOM"], [item["id"] for item in out["unresolved"]])

    def test_conflicting_range_destination_fails_closed(self) -> None:
        data = self.range_alias_data()
        data["features"][0]["bottom_z"] = 5
        out, errors, changes = R.normalize_drawing_schema(data)
        self.assertTrue(any("conflicting range_z" in error for error in errors))
        self.assertEqual(data, out)
        self.assertEqual([], changes)

    def test_unknown_range_alias_fails_without_guessing(self) -> None:
        data = self.range_alias_data()
        data["features"][0]["range_z"] = {"start": 5, "to": 15}
        out, errors, changes = R.normalize_drawing_schema(data)
        self.assertTrue(any("unknown or ambiguous range_z" in error for error in errors))
        self.assertEqual(data, out)
        self.assertEqual([], changes)

    def test_bare_feature_path_alias_is_rewritten_only_when_resolvable(self) -> None:
        data = {"features": [{"id": "F1", "diameter": 6}], "source_ledger": [
            {"id": "S1", "target": "F1.diameter"}
        ]}
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertEqual("feature:F1.diameter", out["source_ledger"][0]["target"])
        data["source_ledger"][0]["target"] = "F1.missing"
        out, errors, changes = R.normalize_drawing_schema(data)
        self.assertTrue(any("cannot resolve canonical target" in error for error in errors))
        self.assertEqual(data, out)
        self.assertEqual([], changes)

    def test_missing_ownership_is_not_invented_by_canonicalizer(self) -> None:
        data = self.range_alias_data()
        data.pop("source_ledger")
        out, errors, _ = R.normalize_drawing_schema(data)
        self.assertEqual([], errors)
        self.assertNotIn("source_ledger", out)
        self.assertEqual([], R.drawing_preservation_inventory(out)["source_ids"])

    def test_canonicalize_cli_gate_failure_writes_nothing(self) -> None:
        data = self.gate_a_range_alias_data()
        data["source_ledger"] = [
            item for item in data["source_ledger"] if item["id"] != "S_SLOT_WIDTH"
        ]
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            original = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            draft.write_text(original, encoding="utf-8")
            args = type("Args", (), {"draft": str(draft), "out": str(output)})()
            with redirect_stdout(io.StringIO()):
                result = R._cmd_canonicalize_drawing(args)
            self.assertEqual(1, result)
            self.assertFalse(output.exists())
            self.assertEqual(original, draft.read_text(encoding="utf-8"))

    def test_canonicalize_cli_rejects_invalid_dimension_closure_types(self) -> None:
        for value in ("incomplete", None, [], 1):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                data = self.gate_a_range_alias_data()
                data["dimension_closure"] = value
                draft = Path(tmp) / "semantic-draft.json"
                output = Path(tmp) / "drawing.json"
                draft.write_text(json.dumps(data), encoding="utf-8")
                result, report = self.run_canonicalize(draft, output)
                self.assertEqual(1, result)
                self.assertTrue(report["gate_a"]["attempted"])
                self.assertIn(
                    "dimension_closure must be an object",
                    report["gate_a"]["errors"],
                )
                self.assertFalse(report["written"])
                self.assertFalse(report["output_exists"])
                self.assertFalse(output.exists())

    def test_canonicalize_cli_keeps_incomplete_closure_as_gate_failure(self) -> None:
        data = self.gate_a_range_alias_data()
        data["dimension_closure"] = {"status": "incomplete"}
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertFalse(any(
                "dimension_closure" in change
                for change in report["normalization"]["changes"]
            ))
            self.assertIn(
                "dimension_closure.status must be closed",
                report["gate_a"]["errors"],
            )
            self.assertFalse(report["written"])
            self.assertFalse(report["output_exists"])
            self.assertFalse(output.exists())

    def test_canonicalize_cli_wraps_unexpected_gate_exception(self) -> None:
        data = self.gate_a_range_alias_data()
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            with mock.patch.object(
                R, "check_drawing_json", side_effect=AttributeError("bad shape")
            ):
                result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertEqual(
                ["Gate A internal error (AttributeError): bad shape"],
                report["gate_a"]["errors"],
            )
            self.assertFalse(report["written"])
            self.assertFalse(report["output_exists"])
            self.assertFalse(output.exists())

    def test_canonicalize_cli_gate_failure_removes_stale_output(self) -> None:
        data = self.gate_a_range_alias_data()
        data["source_ledger"] = [
            item for item in data["source_ledger"] if item["id"] != "S_SLOT_WIDTH"
        ]
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            self.write_stale_output(output)
            result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertFalse(report["written"])
            self.assertFalse(report["output_exists"])
            self.assertFalse(output.exists())

    def test_canonicalize_cli_normalization_failure_removes_stale_output(self) -> None:
        data = {"features": [{"id": "F_BAD", "range_z": {"start": 1, "to": 2}}]}
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            self.write_stale_output(output)
            result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertTrue(report["normalization"]["errors"])
            self.assertFalse(report["written"])
            self.assertFalse(report["output_exists"])
            self.assertFalse(output.exists())

    def test_canonicalize_cli_missing_input_removes_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "missing-semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            self.write_stale_output(output)
            result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertFalse(report["written"])
            self.assertFalse(report["output_exists"])
            self.assertFalse(output.exists())

    def test_canonicalize_cli_malformed_input_removes_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text("{malformed", encoding="utf-8")
            self.write_stale_output(output)
            result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertFalse(report["written"])
            self.assertFalse(report["output_exists"])
            self.assertFalse(output.exists())

    def test_canonicalize_cli_unreadable_input_removes_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text("{}", encoding="utf-8")
            self.write_stale_output(output)
            with mock.patch.object(R, "_load_drawing", side_effect=PermissionError("unreadable")):
                result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertFalse(report["written"])
            self.assertFalse(report["output_exists"])
            self.assertFalse(output.exists())

    def test_canonicalize_cli_rejects_overwriting_semantic_draft(self) -> None:
        data = self.gate_a_range_alias_data()
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            original = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            draft.write_text(original, encoding="utf-8")
            args = type("Args", (), {"draft": str(draft), "out": str(draft)})()
            with redirect_stdout(io.StringIO()):
                result = R._cmd_canonicalize_drawing(args)
            self.assertEqual(1, result)
            self.assertEqual(original, draft.read_text(encoding="utf-8"))

    def test_canonicalize_cli_rejects_output_directory_without_deleting_it(self) -> None:
        data = self.gate_a_range_alias_data()
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            output.mkdir()
            result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertFalse(report["written"])
            self.assertTrue(report["output_exists"])
            self.assertTrue(output.is_dir())

    def test_canonicalize_cli_output_invalidation_failure_is_nonzero(self) -> None:
        data = self.gate_a_range_alias_data()
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            stale_bytes = self.write_stale_output(output)
            with mock.patch.object(R.os, "unlink", side_effect=PermissionError("denied")):
                result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertFalse(report["written"])
            self.assertTrue(report["output_exists"])
            self.assertEqual(stale_bytes, output.read_bytes())

    def test_canonicalize_cli_atomic_write_failure_leaves_no_output_or_temp(self) -> None:
        data = self.gate_a_range_alias_data()
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            self.write_stale_output(output)
            with mock.patch.object(R.os, "replace", side_effect=OSError("replace failed")):
                result, report = self.run_canonicalize(draft, output)
            self.assertEqual(1, result)
            self.assertFalse(report["written"])
            self.assertFalse(report["output_exists"])
            self.assertFalse(output.exists())
            self.assertEqual([], list(Path(tmp).glob(".drawing-canonical-*.tmp")))

    def test_canonicalize_cli_passes_gate_then_writes_output_atomically(self) -> None:
        data = self.gate_a_range_alias_data()
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            original = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            draft.write_text(original, encoding="utf-8")
            args = type("Args", (), {"draft": str(draft), "out": str(output)})()
            with redirect_stdout(io.StringIO()):
                result = R._cmd_canonicalize_drawing(args)
            self.assertEqual(0, result)
            self.assertTrue(output.exists())
            canonical = json.loads(output.read_text(encoding="utf-8"))
            slot = next(item for item in canonical["features"] if item["id"] == "F_SLOT")
            self.assertEqual(5, slot["bottom_z"])
            self.assertEqual(15, slot["top_z"])
            self.assertNotIn("range_z", slot)
            self.assertEqual([], R.check_drawing_json(canonical))
            self.assertEqual(original, draft.read_text(encoding="utf-8"))
            self.assertEqual([], list(Path(tmp).glob(".drawing-canonical-*.tmp")))

    def test_canonicalize_cli_pass_replaces_stale_output(self) -> None:
        data = self.gate_a_range_alias_data()
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "semantic-draft.json"
            output = Path(tmp) / "drawing.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            stale_bytes = self.write_stale_output(output)
            result, report = self.run_canonicalize(draft, output)
            self.assertEqual(0, result)
            self.assertTrue(report["written"])
            self.assertTrue(report["output_exists"])
            self.assertNotEqual(stale_bytes, output.read_bytes())
            canonical = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotIn("stale_output_test_sentinel", canonical)
            self.assertEqual([], R.check_drawing_json(canonical))
            self.assertEqual([], list(Path(tmp).glob(".drawing-canonical-*.tmp")))


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

    def test_coaxial_larger_through_hole_subsumes_thread_surrogate(self) -> None:
        drawing = {
            "features": [
                {
                    "id": "T1",
                    "type": "threaded_hole",
                    "thread_spec": "M6",
                    "thread_depth": 12,
                    "axis": "X",
                    "centerline": {"y": 8, "z": 58},
                },
                {
                    "id": "H1",
                    "type": "counterbore_hole",
                    "axis": "X",
                    "centerline": {"y": 8, "z": 58},
                    "diameter": 6.6,
                    "counterbore_diameter": 11,
                    "counterbore_depth": 6.5,
                    "through": True,
                },
            ],
            "unresolved": [],
        }

        geometries, geometry_errors = R.resolve_thread_drawing_geometries(drawing)
        recipes, recipe_errors = R.resolve_thread_surrogates(drawing)

        self.assertEqual([], geometry_errors)
        self.assertEqual([], recipe_errors)
        self.assertEqual(1, len(geometries))
        self.assertEqual(
            "subsumed_by_coaxial_through_hole",
            geometries[0]["representation"],
        )
        self.assertEqual("H1", geometries[0]["subsumed_by_feature_id"])
        self.assertEqual(0, geometries[0]["count"])
        self.assertEqual([], R.thread_surrogate_plan_errors({"operations": []}, recipes, geometries))

    def test_thread_subsumption_fails_closed_without_matching_through_hole(self) -> None:
        drawing = {
            "features": [
                {
                    "id": "T1",
                    "type": "threaded_hole",
                    "thread_spec": "M6",
                    "thread_depth": 12,
                    "axis": "X",
                    "centerline": {"y": 8, "z": 58},
                },
                {
                    "id": "H1",
                    "type": "hole",
                    "axis": "X",
                    "centerline": {"y": 9, "z": 58},
                    "diameter": 6.6,
                    "through": True,
                },
            ],
            "unresolved": [],
        }

        _, errors = R.resolve_thread_drawing_geometries(drawing)

        self.assertTrue(any("thread_geometry_violation" in item for item in errors))

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
