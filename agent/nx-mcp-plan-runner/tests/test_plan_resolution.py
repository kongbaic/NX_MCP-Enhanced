# -*- coding: utf-8 -*-
"""Unit tests for nx-mcp-plan-runner (no NX involved).

Run:  python tests/test_plan_resolution.py
or:   pytest tests/test_plan_resolution.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runner as R  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN_PLAN = os.path.join(PROJECT, "examples", "modeling-plan-example.json")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class ObjectRef:
    def __init__(self, oid):
        self.id = oid


def make_edge(index, **kw):
    base = {"index": index, "tag": index, "curve_type": "Linear", "start": [0, 0, 0],
            "end": [0, 0, 0], "midpoint": [0, 0, 0], "length": 12.0,
            "bbox_min": [0, 0, 0], "bbox_max": [0, 0, 0], "direction": "Z",
            "adjacent_faces": 2}
    base.update(kw)
    return base


def make_face(index, **kw):
    base = {"index": index, "tag": index, "face_type": "Planar",
            "centroid": [0, 0, 0], "area": 100.0, "normal": [0, 0, 1]}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 1. symbol table
# --------------------------------------------------------------------------
def test_symbol_table():
    s = R.Symbols()
    s.bind("sketch_base", "SKT1")
    s.bind_selection("r6_edges", [9, 135, 151, 65])
    assert s.names["sketch_base"] == "SKT1"
    assert s.selection["r6_edges"] == [9, 135, 151, 65]


# --------------------------------------------------------------------------
# 2. result binding (producer op binds response fields to logical names)
# --------------------------------------------------------------------------
def test_result_binding_single():
    resp = {"body": ObjectRef("BODY_1")}
    s = R.Symbols()
    for n in ["body_base"]:
        s.bind(n, R._item_id(resp["body"]))
    assert s.names["body_base"] == "BODY_1"


def test_result_binding_multi():
    resp = {"objects": [ObjectRef("B2"), ObjectRef("B3"), ObjectRef("B4")]}
    names = ["body_boss2", "body_boss3", "body_boss4"]
    s = R.Symbols()
    vals = [R._item_id(v) for v in resp["objects"]]
    for n, v in zip(names, vals):
        s.bind(n, v)
    assert s.names["body_boss2"] == "B2"
    assert s.names["body_boss3"] == "B3"
    assert s.names["body_boss4"] == "B4"


def test_result_binding_mismatch_raises():
    # len mismatch between response list and names must be an error
    resp = {"objects": [ObjectRef("B2"), ObjectRef("B3")]}
    names = ["a", "b", "c"]
    s = R.Symbols()
    try:
        vals = [R._item_id(v) for v in resp["objects"]]
        if len(vals) != len(names):
            raise R.PlanError("mismatch")
        for n, v in zip(names, vals):
            s.bind(n, v)
        assert False, "should have raised"
    except R.PlanError:
        pass


# --------------------------------------------------------------------------
# 3. variable resolution
# --------------------------------------------------------------------------
def test_resolution_forms():
    s = R.Symbols()
    s.bind("body_main", "BODY_9")
    s.bind_selection("sel_49", [9, 135, 151, 65])
    s.bind_selection("sel_56", {"flange_top": [1], "boss_tops": [2, 3, 4, 5]})

    assert R.resolve_value("$body_main", s) == "BODY_9"
    assert R.resolve_value("$selection.sel_49", s) == [9, 135, 151, 65]
    assert R.resolve_value("$selection.sel_56.flange_top", s) == [1]
    assert R.resolve_value("body_main", s) == "BODY_9"  # bare name


def test_resolution_nested_args():
    s = R.Symbols()
    s.bind("body_main", "BODY_9")
    args = {
        "target_body_id": "$body_main",
        "tool_body_ids": ["$body_a", "$body_b"],
        "center": {"x": 1.0, "y": 2.0},
    }
    s.bind("body_a", "A1")
    s.bind("body_b", "B1")
    out = R.resolve_value(args, s)
    assert out["target_body_id"] == "BODY_9"
    assert out["tool_body_ids"] == ["A1", "B1"]
    assert out["center"] == {"x": 1.0, "y": 2.0}


def test_unresolved_raises():
    s = R.Symbols()
    try:
        R.resolve_value("$ghost", s)
        assert False, "should have raised"
    except R.PlanError:
        pass


def test_finalize_args():
    args = {"body_id": "B1", "remove_face_index": [3], "edge_indices": [1.0, 2.0],
            "tool_body_ids": ["B2", "B3"], "count": 4.0}
    out = R.finalize_args(args)
    assert out["remove_face_index"] == 3
    assert out["edge_indices"] == [1, 2]
    assert out["tool_body_ids"] == ["B2", "B3"]
    assert out["count"] == 4


# --------------------------------------------------------------------------
# 4. rectangle adapter (generic, no step numbers)
# --------------------------------------------------------------------------
def test_rectangle_adapter():
    args = {"sketch_id": "$sketch_base",
            "corner1": {"x": -90.0, "y": -60.0},
            "corner2": {"x": 90.0, "y": 60.0}}
    out = R.adapt_rectangle(args)
    assert out["corner1"] == {"x": 0.0, "y": 0.0}   # center
    assert out["corner2"] == {"x": 180.0, "y": 120.0}  # width/height


def test_rectangle_adapter_passthrough_without_corners():
    args = {"sketch_id": "$s", "center": {"x": 0, "y": 0}, "diameter": 10}
    assert R.adapt_rectangle(args) == args


# --------------------------------------------------------------------------
# 5. edge selection engine
# --------------------------------------------------------------------------
def test_edge_selection_corner_candidates():
    edges = [
        make_edge(0, bbox_min=[-90, -60, 0], bbox_max=[-90, -60, 12]),
        make_edge(1, bbox_min=[-90, 60, 0], bbox_max=[-90, 60, 12]),
        make_edge(2, bbox_min=[90, -60, 0], bbox_max=[90, -60, 12]),
        make_edge(3, bbox_min=[90, 60, 0], bbox_max=[90, 60, 12]),
        make_edge(4, bbox_min=[-90, -22, 0], bbox_max=[-90, -22, 12]),  # distractor
    ]
    crit = {"curve_type": "Linear", "direction": "Z", "length": {"value": 12.0, "tol": 0.05},
            "corners_xy": [[-90, -60], [-90, 60], [90, -60], [90, 60]],
            "bbox_z": {"min": 0.0, "max": 12.0}}
    sel = R.run_selection(edges, crit, "edges")
    assert sel["count"] == 4
    assert sorted(it["index"] for it in sel["items"]) == [0, 1, 2, 3]


def test_edge_selection_curve_type_list_and_length_tol():
    edges = [
        make_edge(0, curve_type="Circular", length=326.73),
        make_edge(1, curve_type="Elliptical", length=326.7),
        make_edge(2, curve_type="Linear", length=100.0),
    ]
    crit = {"curve_type": ["Circular", "Elliptical"], "length": {"value": 326.73, "tol": 1.5}}
    sel = R.run_selection(edges, crit, "edges")
    assert sel["count"] == 2


def test_edge_selection_midpoint_z_and_linear_only():
    edges = [
        make_edge(0, curve_type="Linear", midpoint=[0, 0, 56]),
        make_edge(1, curve_type="Circular", midpoint=[52, 0, 56]),
        make_edge(2, curve_type="Linear", midpoint=[0, 0, 10]),
    ]
    crit = {"linear_only": True, "midpoint_z": {"value": 56.0, "tol": 0.5}}
    sel = R.run_selection(edges, crit, "edges")
    assert [it["index"] for it in sel["items"]] == [0]


def test_edge_selection_bbox_x_containment():
    edges = [
        make_edge(0, bbox_min=[-115, -60, 0], bbox_max=[-115, -60, 12]),
        make_edge(1, bbox_min=[-115, 60, 0], bbox_max=[-115, 60, 12]),
        make_edge(2, bbox_min=[-120, -60, 0], bbox_max=[-120, -60, 12]),  # outside x
        make_edge(3, bbox_min=[-115, 80, 0], bbox_max=[-115, 80, 12]),    # outside y
    ]
    crit = {"bbox_x": [-115.0, 115.0], "bbox_y": [-60.0, 60.0]}
    sel = R.run_selection(edges, crit, "edges")
    assert [it["index"] for it in sel["items"]] == [0, 1]


def test_edge_selection_adjacent_faces_and_count():
    edges = [make_edge(0, adjacent_faces=2), make_edge(1, adjacent_faces=1)]
    sel = R.run_selection(edges, {"adjacent_faces": 2}, "edges")
    assert sel["count"] == 1


# --------------------------------------------------------------------------
# 6. face selection engine
# --------------------------------------------------------------------------
def test_face_selection_flat():
    faces = [
        make_face(0, face_type="Planar", centroid=[0, 0, 48], area=5541.77, normal=[0, 0, 1]),
        make_face(1, face_type="Cylindrical", centroid=[0, 0, 20]),
        make_face(2, face_type="Planar", centroid=[0, 0, 10], normal=[0, 0, 1]),
    ]
    crit = {"face_type": "Planar", "centroid": [0, 0, 48], "normal": [0, 0, 1],
            "area_approx_auxiliary": 5541.77}  # auxiliary key must be ignored
    sel = R.run_selection(faces, crit, "faces")
    assert sel["count"] == 1
    assert sel["items"][0]["index"] == 0


def test_face_selection_named_groups():
    faces = [
        make_face(0, face_type="Planar", centroid=[0, 0, 56], normal=[0, 0, 1]),
        make_face(1, face_type="Planar", centroid=[65, 0, 20], normal=[0, 0, 1]),
        make_face(2, face_type="Planar", centroid=[-65, 0, 20], normal=[0, 0, 1]),
        make_face(3, face_type="Cylindrical", centroid=[0, 0, 20]),
    ]
    crit = {
        "flange_top": {"face_type": "Planar", "centroid": [0, 0, 56]},
        "boss_tops": {"face_type": "Planar", "centroid_z": 20.0,
                      "centroid_radius": {"value": 65.0, "tol": 1.0}},
        "holes_reasonable": {"face_type": "Cylindrical"},
    }
    sel = R.run_selection(faces, crit, "faces")
    assert sel["count"] == 4
    assert sel["groups"]["flange_top"] == 1
    assert sel["groups"]["boss_tops"] == 2
    assert sel["groups"]["holes_reasonable"] == 1


def test_face_selection_centroid_radius_and_centroid_z():
    faces = [
        make_face(0, face_type="Planar", centroid=[52, 0, 56]),
        make_face(1, face_type="Planar", centroid=[10, 0, 56]),
    ]
    sel = R.run_selection(faces, {"centroid_radius": {"value": 52.0, "tol": 0.5}}, "faces")
    assert [it["index"] for it in sel["items"]] == [0]
    sel2 = R.run_selection(faces, {"centroid_z": {"value": 56.0, "tol": 0.5}}, "faces")
    assert sel2["count"] == 2


def test_centroid_radius_is_global_xy_distance_not_local_face_radius():
    # centroid_radius is sqrt(global_x^2 + global_y^2), not a cylinder/hole radius.
    face = make_face(0, face_type="Swept", centroid=[10, 10, 5])
    wrong = R.run_selection(
        [face], {"centroid_radius": {"value": 4.0, "tol": 0.5}}, "faces"
    )
    assert wrong["count"] == 0

    correct = R.run_selection(
        [face], {"centroid_radius": {"value": 14.142, "tol": 0.5}}, "faces"
    )
    assert [it["index"] for it in correct["items"]] == [0]


def test_hole_face_verification_by_explicit_centroid_groups():
    faces = [
        make_face(0, face_type="Swept", centroid=[10, 10, 5]),
        make_face(1, face_type="Swept", centroid=[90, 10, 5]),
        make_face(2, face_type="Cylindrical", centroid=[10, 50, 5]),
        make_face(3, face_type="Swept", centroid=[90, 50, 5]),
        make_face(4, face_type="Planar", centroid=[50, 30, 10]),
    ]
    crit = {
        "hole_1": {"face_type": ["Swept", "Cylindrical"], "centroid": [10, 10, 5]},
        "hole_2": {"face_type": ["Swept", "Cylindrical"], "centroid": [90, 10, 5]},
        "hole_3": {"face_type": ["Swept", "Cylindrical"], "centroid": [10, 50, 5]},
        "hole_4": {"face_type": ["Swept", "Cylindrical"], "centroid": [90, 50, 5]},
    }
    sel = R.run_selection(faces, crit, "faces")
    assert sel["count"] == 4
    assert R.check_expectation(
        {
            "hole_1_count": 1,
            "hole_2_count": 1,
            "hole_3_count": 1,
            "hole_4_count": 1,
        },
        sel,
        {},
    ) == []


# --------------------------------------------------------------------------
# 7. topology cache invalidation
# --------------------------------------------------------------------------
def test_raw_loader_ok_false_stops_runner_before_following_operations():
    import asyncio

    calls = []

    class T:
        async def call_raw(self, tool, args):
            calls.append(("raw", tool))
            return {
                "ok": False,
                "error": {
                    "code": "NX_OPERATION_FAILED",
                    "message": "synthetic blend failure",
                },
            }

        async def call(self, tool, args):
            calls.append(("normal", tool))
            return {"status": "success"}

    plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_edge_blend",
                "tool_args": {
                    "body_id": "BODY1",
                    "radius": 5,
                    "edge_indices": [1],
                },
                "topology_changes": True,
            },
            {
                "step": 2,
                "tool": "nx_status",
                "tool_args": {},
                "topology_changes": False,
            },
        ]
    }

    report = asyncio.run(R.run_plan(plan, T()))

    assert report["status"] == "failed"
    assert report["failed_step"] == 1
    assert report["operations_completed"] == 0
    assert calls == [("raw", "nx_edge_blend")]
    assert "synthetic blend failure" in report["steps"][0]["error"]


def test_raw_loader_success_preserves_done_response():
    response = R._require_raw_loader_success(
        "nx_chamfer",
        {"ok": True, "result": "done=4"},
    )

    assert response == {"ok": True, "result": "done=4"}
    assert R._parse_done(response) == 4


def test_topology_invalidation():
    topo = R.TopologyState()
    assert topo.edges_valid and topo.faces_valid
    topo.edges_cached = [1, 2]
    topo.faces_cached = [3]
    topo.invalidate()
    assert not topo.edges_valid and not topo.faces_valid
    assert topo.edges_cached == [] and topo.faces_cached == []


def test_topology_invalidation_does_not_auto_list():
    # a topology_changes op must NOT trigger list calls by itself
    calls = []

    async def fake_loop():
        plan = {"operations": [{"step": 1, "tool": "nx_unite",
                                "tool_args": {"target_body_id": "b", "tool_body_ids": ["c"]},
                                "topology_changes": True}]}
        s = R.Symbols()
        s.bind("b", "B1")
        s.bind("c", "B2")

        class T:
            async def call(self, tool, args):
                calls.append(tool)
                return {"message": "ok", "target": ObjectRef("B1")}

        await R.run_plan(plan, T())
        assert calls == ["nx_unite"], calls

    import asyncio
    asyncio.run(fake_loop())


# --------------------------------------------------------------------------
# 8. expectation checker
# --------------------------------------------------------------------------
def test_expectation_checks():
    sel = {"count": 4, "groups": {"flange_top": 1, "boss_tops": 4},
           "extents": {"x_min": -115.0, "x_max": 115.0, "y_min": -60.0,
                       "y_max": 60.0, "z_min": 0.0, "z_max": 56.0}}
    assert R.check_expectation({"count": 4}, sel, {}) == []
    assert R.check_expectation({"count": 5}, sel, {}) != []
    assert R.check_expectation({"flange_top_count": 1, "boss_tops_count": 4}, sel, {}) == []
    assert R.check_expectation({"boss_tops_count": 3}, sel, {}) != []
    assert R.check_expectation({"cylindrical_count_range": [4, 12]}, sel, {}) != []  # unknown group
    assert R.check_expectation({"x_min": -115.0, "z_max": 56.0, "tolerance_mm": 0.5}, sel, {}) == []
    assert R.check_expectation({"body_count": 1}, sel, {"objects": [ObjectRef("B1")]}) == []
    assert R.check_expectation({"body_count": 2}, sel, {"objects": [ObjectRef("B1")]}) != []
    # informational keys must be ignored
    assert R.check_expectation({"purpose": "check", "area_auxiliary": 123.0}, sel, {}) == []
    # done check on raw pipe result
    raw = {"result": "blend ok done=4"}
    assert R.check_expectation({"done": 4}, sel, raw) == []
    assert R.check_expectation({"done": 3}, sel, raw) != []


def test_extents_computation():
    edges = [
        make_edge(0, bbox_min=[-115, -60, 0], bbox_max=[-115, -60, 12]),
        make_edge(1, bbox_min=[115, 60, 48], bbox_max=[115, 60, 56]),
    ]
    ext = R.compute_extents(edges, "edges")
    assert ext["x_min"] == -115 and ext["x_max"] == 115
    assert ext["y_min"] == -60 and ext["y_max"] == 60
    assert ext["z_min"] == 0 and ext["z_max"] == 56


# --------------------------------------------------------------------------
# 9. build + static check on the real frozen plan (no NX)
# --------------------------------------------------------------------------
def test_frozen_plan_loads():
    assert os.path.isfile(FROZEN_PLAN)
    with open(FROZEN_PLAN, encoding="utf-8") as f:
        plan = json.load(f)
    assert plan["mode"] == "FAST"
    assert len(plan["operations"]) == 59


def test_build_executable_plan_preserves_geometry_and_operation_order():
    with open(FROZEN_PLAN, encoding="utf-8") as f:
        plan = json.load(f)

    executable = R.build_executable_plan(plan)

    assert R._build_geometry_conservation_errors(plan, executable) == []


def test_arc_geometry_is_conserved_from_frozen_to_executable():
    frozen = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_sketch",
                "tool_args": {"plane": "XZ"},
                "topology_changes": False,
            },
            {
                "step": 2,
                "tool": "nx_sketch_arc",
                "tool_args": {
                    "sketch_id": "sketch_profile",
                    "center": {"x": 25.0, "y": 55.0},
                    "radius": 5.0,
                    "start_angle": 0.0,
                    "end_angle": 90.0,
                },
                "topology_changes": False,
            },
        ],
    }

    executable = R.build_executable_plan(frozen)

    assert R._build_geometry_conservation_errors(
        frozen,
        executable,
    ) == []
    assert executable["operations"][0]["result_bindings"] == {
        "object": "sketch_profile"
    }
    arc_args = executable["operations"][1]["tool_args"]
    assert arc_args == {
        "sketch_id": "$sketch_profile",
        "center": {"x": 25.0, "y": 55.0},
        "radius": 5.0,
        "start_angle": 0.0,
        "end_angle": 90.0,
    }


def test_runner_dispatches_executable_arc_geometry_without_mutation():
    import asyncio

    frozen = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_sketch",
                "tool_args": {"plane": "XZ"},
                "topology_changes": False,
            },
            {
                "step": 2,
                "tool": "nx_sketch_arc",
                "tool_args": {
                    "sketch_id": "sketch_profile",
                    "center": {"x": 25.0, "y": 55.0},
                    "radius": 5.0,
                    "start_angle": 0.0,
                    "end_angle": 90.0,
                },
                "topology_changes": False,
            },
        ],
    }
    executable = R.build_executable_plan(frozen)
    calls = []

    class Transport:
        async def call(self, tool, args):
            calls.append((tool, args))
            if tool == "nx_create_sketch":
                return {"object": "S_PROFILE", "message": "created"}
            return {"message": "ok"}

    report = asyncio.run(R.run_plan(executable, Transport()))

    assert report["status"] == "success"
    assert calls == [
        ("nx_create_sketch", {"plane": "XZ"}),
        (
            "nx_sketch_arc",
            {
                "sketch_id": "S_PROFILE",
                "center": {"x": 25.0, "y": 55.0},
                "radius": 5.0,
                "start_angle": 0.0,
                "end_angle": 90.0,
            },
        ),
    ]


def test_build_geometry_conservation_rejects_geometry_argument_mutation():
    frozen = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_sketch_circle",
                "tool_args": {
                    "sketch_id": "sketch_main",
                    "center": {"x": 0.0, "y": 0.0},
                    "diameter": 10.0,
                },
            }
        ]
    }
    executable = R.build_executable_plan(frozen)
    executable["operations"][0]["tool_args"]["diameter"] = 12.0

    errors = R._build_geometry_conservation_errors(frozen, executable)

    assert errors == [
        "build conservation violation: step 1 changed tool_args.diameter"
    ]


def test_build_geometry_conservation_rejects_operation_loss():
    frozen = {
        "operations": [
            {"step": 1, "tool": "nx_status", "tool_args": {}},
            {"step": 2, "tool": "nx_save_part", "tool_args": {}},
        ]
    }
    executable = R.build_executable_plan(frozen)
    executable["operations"].pop()

    errors = R._build_geometry_conservation_errors(frozen, executable)

    assert errors == [
        "build conservation violation: operation count changed 2 -> 1"
    ]


def test_build_executable_plan_resolves_all_references():
    with open(FROZEN_PLAN, encoding="utf-8") as f:
        plan = json.load(f)
    exe = R.build_executable_plan(plan)
    errs = R.check_plan(exe, executable=True)
    assert errs == [], errs
    # no natural-language placeholders left in any tool_args
    for op in exe["operations"]:
        for v in R._walk(op.get("tool_args") or {}):
            assert not (isinstance(v, str) and ("<" in v or "匹配" in v)), (op["step"], v)
    # selection consumers rewritten to machine references
    ta = {op["step"]: op.get("tool_args") or {} for op in exe["operations"]}
    assert ta[17]["remove_face_index"] == "$selection.sel_16"
    assert ta[50]["edge_indices"] == "$selection.sel_49"
    assert ta[52]["edge_indices"] == "$selection.sel_51"
    assert ta[54]["edge_indices"] == "$selection.sel_53"
    # key logical bindings present
    bindings = {}
    for op in exe["operations"]:
        for field, names in (op.get("result_bindings") or {}).items():
            ns = [names] if isinstance(names, str) else names
            for n in ns:
                bindings[n] = (op["step"], field)
    assert bindings.get("sketch_base") and bindings.get("body_base")
    assert bindings.get("body_main") is not None       # alias on the base producer
    assert bindings.get("body_cyl") and bindings.get("body_flange")
    assert bindings.get("body_boss1") and bindings.get("body_boss2")
    assert bindings.get("body_ribL1") and bindings.get("body_ribR1")
    # pattern copies bound via the "objects" response field
    assert bindings.get("body_boss2")[1] == "objects"
    assert bindings.get("body_ribR2")[1] == "objects"
    # mirror results bound via the bridge's "object" field (regression)
    assert bindings.get("body_earR") == (10, "object")
    assert bindings.get("body_ribR1") == (36, "object")
    # save retry declared
    save = [op for op in exe["operations"] if op["tool"] == "nx_save_part"]
    assert save and save[0].get("retry", {}).get("max", 0) >= 1


def test_frozen_check_rejects_executable_only_fields():
    plan = {"mode": "FAST", "plan_format": "executable-v1", "operations": [{
        "step": 1,
        "tool": "nx_list_edges",
        "tool_args": {"body_id": "body_main"},
        "selection_criteria": {"linear_only": True},
        "result_bindings": {"edges": "selected_edges"},
        "selection_binding": "sel_1",
        "retry": {"max": 1, "if_error_contains": ["x"]},
        "topology_changes": False,
    }]}
    errs = R.check_plan(plan, executable=False)
    assert any("plan_format" in e for e in errs)
    assert any("result_bindings" in e for e in errs)
    assert any("selection_binding" in e for e in errs)
    assert any("retry" in e for e in errs)


def test_check_plan_can_defer_embedded_thread_contract_to_drawing_gate():
    plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_status",
                "tool_args": {},
                "topology_changes": False,
            }
        ],
        "thread_surrogates": [
            {
                "feature_id": "T1",
                "surrogate_diameter": 5.0,
            }
        ],
        "thread_drawing_geometries": [
            {
                "feature_id": "T1",
                "owner_feature_id": "T1",
                "axis": "Z",
                "transverse_centers": [[0.0, 0.0]],
                "depth": 10.0,
                "axial_range": [0.0, 10.0],
                "count": 1,
            }
        ],
    }

    embedded_errors = R.check_plan(plan, executable=False)
    delegated_errors = R.check_plan(
        plan,
        executable=False,
        validate_embedded_thread_contract=False,
    )

    assert any(
        "operation count differs from drawing" in item
        for item in embedded_errors
    )
    assert delegated_errors == []


def test_plan_check_rejects_absolute_workspace_paths():
    plan = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_part",
                "tool_args": {"path": r"C:\\workspace\\part.prt", "units": "mm"},
                "topology_changes": False,
            },
            {
                "step": 2,
                "tool": "nx_export_step",
                "tool_args": {"path": "/tmp/part.step"},
                "topology_changes": False,
            },
        ],
    }

    errors = R.check_plan(plan, executable=False)

    assert sum("NX_MCP_WORKSPACE-relative" in item for item in errors) == 2


def test_build_marks_binding_free_plan_executable():
    frozen = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_part",
                "tool_args": {"path": "binding-free.prt", "units": "mm"},
                "topology_changes": False,
            },
            {
                "step": 2,
                "tool": "nx_save_part",
                "tool_args": {},
                "topology_changes": False,
            },
        ],
    }

    assert R._is_executable(frozen) is False

    executable = R.build_executable_plan(frozen)

    assert executable["plan_format"] == "executable-v1"
    assert not any(
        op.get("result_bindings") or op.get("selection_binding")
        for op in executable["operations"]
    )
    assert R._is_executable(executable) is True
    assert R.check_plan(executable, executable=True) == []


def test_cmd_run_early_failure_writes_requested_report(tmp_path=None):
    import argparse
    import asyncio
    import tempfile

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    plan_path = os.path.join(directory, "not-executable.json")
    report_path = os.path.join(directory, "early-report.json")

    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "mode": "FAST",
                "operations": [
                    {
                        "step": 1,
                        "tool": "nx_status",
                        "tool_args": {},
                        "topology_changes": False,
                    }
                ],
            },
            handle,
        )

    args = argparse.Namespace(
        plan=plan_path,
        workspace=directory,
        report=report_path,
        mode="normal",
        allow_overwrite=False,
        history=None,
        repair_attempt=0,
        repair_report=None,
    )

    exit_code = asyncio.run(R._cmd_run(args))

    assert exit_code == 1
    assert os.path.isfile(report_path)
    with open(report_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["status"] == "failed"
    assert payload["failed_step"] is None
    assert any("not in executable format" in item for item in payload["errors"])


def _capture_async_runner(coro):
    import asyncio
    import contextlib
    import io

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = asyncio.run(coro)
    marker = "===REPORT===\n"
    payload_text = output.getvalue().split(marker, 1)[1]
    return exit_code, json.loads(payload_text)


def _write_executable_for_run(path, *, source_drawing=None):
    frozen = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_status",
                "tool_args": {},
                "topology_changes": False,
            }
        ],
    }
    if source_drawing is not None:
        frozen["source_drawing"] = source_drawing
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(R.build_executable_plan(frozen), handle)


def _run_args(plan_path, directory, *, drawing):
    import argparse

    return argparse.Namespace(
        plan=plan_path,
        workspace=directory,
        report=None,
        drawing=drawing,
        mode="normal",
        allow_overwrite=False,
        history=None,
        repair_attempt=0,
        repair_report=None,
    )


def test_mode_b_run_rejects_mismatched_source_drawing_before_loader(tmp_path=None):
    import tempfile

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    current = os.path.join(directory, "current-drawing.json")
    stale = os.path.join(directory, "stale-drawing.json")
    executable = os.path.join(directory, "stale-executable.json")
    _write_executable_for_run(executable, source_drawing=os.path.abspath(stale))

    original_transport = R.NXTransport
    try:
        R.NXTransport = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Loader must not be touched on source_drawing mismatch")
        )
        exit_code, result = _capture_async_runner(
            R._cmd_run(_run_args(executable, directory, drawing=current))
        )
    finally:
        R.NXTransport = original_transport

    assert exit_code == 1
    assert result["status"] == "failed"
    assert any("source_drawing mismatch" in item for item in result["errors"])


def test_mode_b_run_requires_source_drawing_before_loader(tmp_path=None):
    import tempfile

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    current = os.path.join(directory, "current-drawing.json")
    executable = os.path.join(directory, "missing-source-executable.json")
    _write_executable_for_run(executable)

    original_transport = R.NXTransport
    try:
        R.NXTransport = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Loader must not be touched when source_drawing is missing")
        )
        exit_code, result = _capture_async_runner(
            R._cmd_run(_run_args(executable, directory, drawing=current))
        )
    finally:
        R.NXTransport = original_transport

    assert exit_code == 1
    assert any("missing source_drawing" in item for item in result["errors"])


def test_mode_b_run_matching_source_drawing_reaches_loader(tmp_path=None):
    import tempfile

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    current = os.path.join(directory, "current-drawing.json")
    executable = os.path.join(directory, "matching-source-executable.json")
    _write_executable_for_run(executable, source_drawing=os.path.abspath(current))

    class OfflineTransport:
        def __init__(self, workspace_root=None):
            self.workspace_root = workspace_root

        def ping(self):
            return False

        def ping_error(self):
            return "expected offline test transport"

    original_transport = R.NXTransport
    try:
        R.NXTransport = OfflineTransport
        exit_code, result = _capture_async_runner(
            R._cmd_run(_run_args(executable, directory, drawing=current))
        )
    finally:
        R.NXTransport = original_transport

    assert exit_code == 1
    assert any("loader health check failed" in item for item in result["errors"])
    assert not any("source_drawing" in item for item in result["errors"])


def test_text_mode_run_allows_missing_source_drawing(tmp_path=None):
    import tempfile

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    executable = os.path.join(directory, "text-executable.json")
    _write_executable_for_run(executable)

    class OfflineTransport:
        def __init__(self, workspace_root=None):
            self.workspace_root = workspace_root

        def ping(self):
            return False

        def ping_error(self):
            return "expected offline test transport"

    original_transport = R.NXTransport
    try:
        R.NXTransport = OfflineTransport
        exit_code, result = _capture_async_runner(
            R._cmd_run(_run_args(executable, directory, drawing=None))
        )
    finally:
        R.NXTransport = original_transport

    assert exit_code == 1
    assert any("loader health check failed" in item for item in result["errors"])
    assert not any("source_drawing" in item for item in result["errors"])


def test_frozen_check_rejects_dollar_references():
    plan = {"mode": "FAST", "operations": [{
        "step": 1,
        "tool": "nx_list_edges",
        "tool_args": {"body_id": "$body_main"},
        "topology_changes": False,
    }]}
    errs = R.check_plan(plan, executable=False)
    assert any("executable reference" in e for e in errs)


def test_frozen_check_rejects_bare_selection_consumer_name():
    plan = {"mode": "FAST", "operations": [{
        "step": 24,
        "tool": "nx_edge_blend",
        "tool_args": {
            "body_id": "body_main",
            "radius": 5,
            "edge_indices": "base_plate_vertical_edges",
        },
        "topology_changes": True,
    }]}
    errs = R.check_plan(plan, executable=False)
    assert any("frozen edge_indices string must be a <stepN" in e for e in errs)


def test_executable_check_rejects_unresolved_selection_consumer_name():
    plan = {"mode": "FAST", "operations": [{
        "step": 24,
        "tool": "nx_edge_blend",
        "tool_args": {
            "body_id": "$body_main",
            "radius": 5,
            "edge_indices": "base_plate_vertical_edges",
        },
        "topology_changes": True,
        "result_bindings": {"body": "body_dummy"},
    }]}
    errs = R.check_plan(plan, executable=True)
    assert any("executable edge_indices string must be a $selection reference" in e for e in errs)


def test_build_is_idempotent_shape():
    with open(FROZEN_PLAN, encoding="utf-8") as f:
        plan = json.load(f)
    exe1 = R.build_executable_plan(plan)
    exe2 = R.build_executable_plan(exe1)  # re-running build must not break
    errs = R.check_plan(exe2, executable=True)
    assert errs == [], errs


def test_param_validation_rejects_planner_fields_in_tool_args():
    # planner custom fields in tool_args must be flagged
    plan = {"operations": [{
        "step": 1, "tool": "nx_list_edges",
        "tool_args": {"body_id": "$body_main", "expected_count": 4},  # illegal
        "selection_criteria": {}, "expectation": {}}]}
    errs = R.check_plan(plan, executable=True)
    assert any("illegal param" in e for e in errs)


# --------------------------------------------------------------------------
# 10. preflight safety policy (no NX)
# --------------------------------------------------------------------------
def test_preflight_unrelated_part_open_blocked():
    dec, payload = R.preflight_decision(
        active_path=r"C:\work\user_own.prt", planned_path=r"C:\work\test.prt",
        mode="benchmark", overwrite_allowed=True, dirty=False, runner_parts=())
    assert dec == "blocked"
    assert payload["reason"] == "unrelated_part_open"


def test_preflight_unrelated_part_preserved_for_create_new():
    dec, payload = R.preflight_decision(
        active_path=r"C:\work\user_own.prt",
        planned_path=r"C:\work\new_task.prt",
        mode="normal",
        overwrite_allowed=False,
        dirty=True,
        runner_parts=(),
        part_entry_tool="nx_create_part",
    )
    assert dec == "allow"
    assert payload["state"] == "unrelated_part_preserved_for_create"


def test_preflight_runner_history_part_preserved_for_create_new():
    old_part = r"C:\work\previous_runner_part.prt"
    dec, payload = R.preflight_decision(
        active_path=old_part,
        planned_path=r"C:\work\new_task.prt",
        mode="normal",
        overwrite_allowed=False,
        dirty=False,
        runner_parts=(old_part,),
        part_entry_tool="nx_create_part",
    )
    assert dec == "allow"
    assert payload["state"] == "unrelated_part_preserved_for_create"


def test_preflight_unrelated_part_open_existing_edit_blocked():
    dec, payload = R.preflight_decision(
        active_path=r"C:\work\user_own.prt",
        planned_path=r"C:\work\existing_task.prt",
        mode="normal",
        overwrite_allowed=False,
        dirty=True,
        runner_parts=(),
        part_entry_tool="nx_open_part",
    )
    assert dec == "blocked"
    assert payload["reason"] == "unrelated_part_open"


def test_run_preflight_create_new_does_not_close_unrelated_part():
    import asyncio

    class History:
        def most_recent(self, path):
            return {"save_ok": True}

        def paths(self):
            return (r"C:\work\user_own.prt",)

    class Transport:
        def __init__(self):
            self.calls = []

        def resolve_path(self, path):
            return path

        async def call(self, tool, args):
            self.calls.append((tool, args))
            if tool == "nx_status":
                return {"active_part": ObjectRef(r"C:\work\user_own.prt")}
            if tool == "nx_close_part":
                raise AssertionError("unrelated user part must not be closed")
            raise AssertionError(f"unexpected preflight tool {tool}")

    transport = Transport()
    plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_part",
                "tool_args": {"path": r"C:\work\new_task.prt"},
            }
        ]
    }
    blocked, info = asyncio.run(
        R.run_preflight(
            transport,
            plan,
            "normal",
            False,
            History(),
            repair_authorized=False,
        )
    )
    assert blocked is None
    assert info["state"] == "unrelated_part_preserved_for_create"
    assert [tool for tool, _ in transport.calls] == ["nx_status"]


def test_run_preflight_create_new_blocks_existing_disk_target_without_repair():
    import asyncio
    import os
    import tempfile

    directory = tempfile.mkdtemp()
    planned = os.path.join(directory, "existing.prt")
    with open(planned, "wb") as handle:
        handle.write(b"do-not-delete")

    class History:
        def most_recent(self, path):
            return None

        def paths(self):
            return ()

    class Transport:
        def resolve_path(self, path):
            return path

        async def call(self, tool, args):
            raise AssertionError("disk target gate must block before NX calls")

    plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_part",
                "tool_args": {"path": planned},
            }
        ]
    }

    blocked, info = asyncio.run(
        R.run_preflight(
            Transport(),
            plan,
            "normal",
            False,
            History(),
            repair_authorized=False,
        )
    )

    assert info is None
    assert blocked["reason"] == "planned_part_exists"
    with open(planned, "rb") as handle:
        assert handle.read() == b"do-not-delete"


def test_run_preflight_controlled_repair_removes_only_planned_disk_target():
    import asyncio
    import os
    import tempfile

    directory = tempfile.mkdtemp()
    planned = os.path.join(directory, "failed.prt")
    unrelated = os.path.join(directory, "keep.prt")
    for path, payload in ((planned, b"failed"), (unrelated, b"keep")):
        with open(path, "wb") as handle:
            handle.write(payload)

    class History:
        def most_recent(self, path):
            return {"save_ok": False}

        def paths(self):
            return (planned,)

    class Transport:
        def __init__(self):
            self.calls = []

        def resolve_path(self, path):
            return path

        async def call(self, tool, args):
            self.calls.append((tool, args))
            if tool == "nx_status":
                return {"active_part": ObjectRef(planned)}
            if tool == "nx_close_part":
                return {"status": "success"}
            raise AssertionError(f"unexpected tool {tool}")

    transport = Transport()
    plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_part",
                "tool_args": {"path": planned},
            }
        ]
    }

    blocked, info = asyncio.run(
        R.run_preflight(
            transport,
            plan,
            "benchmark",
            True,
            History(),
            repair_authorized=True,
        )
    )

    assert blocked is None
    assert info["controlled_overwrite"] is True
    assert not os.path.exists(planned)
    with open(unrelated, "rb") as handle:
        assert handle.read() == b"keep"
    assert [tool for tool, _ in transport.calls] == ["nx_status", "nx_close_part"]


def test_create_part_verifies_real_work_part_before_continuing():
    import asyncio

    expected = r"C:\work\new_task.prt"

    class Transport:
        def __init__(self, active_after_create, displayed_parts=None):
            self.active_after_create = active_after_create
            self.displayed_parts = list(displayed_parts or [active_after_create])

        def resolve_path(self, path):
            return path

        async def call(self, tool, args):
            if tool == "nx_create_part":
                return {
                    "status": "success",
                    "part": ObjectRef(args["path"]),
                    "message": "created",
                }
            if tool == "nx_status":
                return {
                    "status": "success",
                    "active_part": ObjectRef(self.active_after_create),
                    "displayed_parts": list(self.displayed_parts),
                }
            raise AssertionError(f"unexpected tool {tool}")

    plan = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_part",
                "tool_args": {"path": expected},
            }
        ],
    }

    ok = asyncio.run(
        R.run_plan(plan, Transport(expected), planned_part=expected)
    )
    assert ok["status"] == "success"
    assert ok["operations_completed"] == 1

    wrong = asyncio.run(
        R.run_plan(
            plan,
            Transport(r"C:\work\user_own.prt"),
            planned_part=expected,
        )
    )
    assert wrong["status"] == "failed"
    assert wrong["failed_step"] == 1
    assert "did not become active work part" in wrong["steps"][0]["error"]

    old_part = r"C:\work\previous_runner_part.prt"
    preserved = asyncio.run(
        R.run_plan(
            plan,
            Transport(expected, [old_part, expected]),
            planned_part=expected,
            preserved_displayed_part=old_part,
        )
    )
    assert preserved["status"] == "success"

    lost = asyncio.run(
        R.run_plan(
            plan,
            Transport(expected, [expected]),
            planned_part=expected,
            preserved_displayed_part=old_part,
        )
    )
    assert lost["status"] == "failed"
    assert lost["failed_step"] == 1
    assert "did not preserve pre-existing displayed part" in lost["steps"][0]["error"]


def test_preflight_planned_benchmark_clean_allowed():
    dec, payload = R.preflight_decision(
        active_path=r"C:\work\test.prt", planned_path=r"C:\work\test.prt",
        mode="benchmark", overwrite_allowed=False, dirty=False, runner_parts=())
    assert dec == "allow"
    assert payload["state"] == "planned_clean"


def test_preflight_planned_clean_normal_allowed():
    dec, _ = R.preflight_decision(
        active_path=r"C:\work\test.prt", planned_path=r"C:\work\test.prt",
        mode="normal", overwrite_allowed=False, dirty=False, runner_parts=())
    assert dec == "allow"


def test_preflight_planned_dirty_controlled_repair_allowed():
    dec, payload = R.preflight_decision(
        active_path=r"C:\work\test.prt", planned_path=r"C:\work\test.prt",
        mode="benchmark", overwrite_allowed=True, dirty=True, runner_parts=(),
        repair_authorized=True)
    assert dec == "allow"
    assert payload["state"] == "planned_dirty_controlled_repair"


def test_preflight_planned_dirty_benchmark_without_repair_blocked():
    dec, payload = R.preflight_decision(
        active_path=r"C:\work\test.prt", planned_path=r"C:\work\test.prt",
        mode="benchmark", overwrite_allowed=True, dirty=True, runner_parts=(),
        repair_authorized=False)
    assert dec == "blocked"
    assert payload["reason"] == "planned_part_dirty"


def test_preflight_planned_dirty_normal_blocked():
    dec, payload = R.preflight_decision(
        active_path=r"C:\work\test.prt", planned_path=r"C:\work\test.prt",
        mode="normal", overwrite_allowed=True, dirty=True, runner_parts=())
    assert dec == "blocked"
    assert payload["reason"] == "planned_part_dirty"


def test_preflight_planned_dirty_benchmark_without_overwrite_blocked():
    dec, _ = R.preflight_decision(
        active_path=r"C:\work\test.prt", planned_path=r"C:\work\test.prt",
        mode="benchmark", overwrite_allowed=False, dirty=True, runner_parts=())
    assert dec == "blocked"


def test_preflight_no_active_part_allowed():
    dec, payload = R.preflight_decision(
        active_path="", planned_path=r"C:\work\test.prt",
        mode="normal", overwrite_allowed=False, dirty=False, runner_parts=())
    assert dec == "allow"
    assert payload["state"] == "no_active_part"


def test_preflight_runner_own_test_part_allowed():
    # category B: a part the Runner itself created and recorded
    dec, payload = R.preflight_decision(
        active_path=r"C:\work\tmp_test.prt", planned_path=r"C:\work\test.prt",
        mode="normal", overwrite_allowed=False, dirty=False,
        runner_parts=(R._norm_path(r"C:\work\tmp_test.prt"),))
    assert dec == "allow"
    assert payload["state"] == "runner_test_part"


def test_preflight_path_normalization():
    # same file, different slash/case spelling must still match
    dec, _ = R.preflight_decision(
        active_path="c:/Work/Test.prt", planned_path=r"C:\work\test.prt",
        mode="normal", overwrite_allowed=False, dirty=False, runner_parts=())
    assert dec == "allow"


def test_run_history_and_runtime_dirty(tmp_path=None):
    import tempfile
    d = tmp_path or tempfile.mkdtemp()
    hp = os.path.join(str(d), "history.json")
    h = R.RunHistory(hp)
    # unknown provenance -> dirty (conservative)
    assert R.runtime_dirty(r"C:\work\test.prt", h) is True
    # Runner started a run, did not save -> dirty
    h.record_start(r"C:\work\test.prt", "benchmark", "plan.json")
    assert h.most_recent(r"C:\work\test.prt")["repair_attempt"] == 0
    assert R.runtime_dirty(r"C:\work\test.prt", h) is True
    # saved -> clean
    h.record_saved(r"C:\work\test.prt")
    assert R.runtime_dirty(r"C:\work\test.prt", h) is False
    # path normalization in history keys
    assert h.most_recent("c:/work/TEST.prt")["save_ok"] is True
    h.record_failed(r"C:\work\test.prt")
    assert R.runtime_dirty(r"C:\work\test.prt", h) is True
    # history persists across instances
    h2 = R.RunHistory(hp)
    assert h2.most_recent(r"C:\work\test.prt")["save_ok"] is False



def test_build_revolve_body_producer_binds_downstream_consumers():
    frozen = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_sketch",
                "tool_args": {"plane": "XZ"},
                "topology_changes": False,
            },
            {
                "step": 2,
                "tool": "nx_finish_sketch",
                "tool_args": {"sketch_id": "sketch_body"},
                "topology_changes": False,
            },
            {
                "step": 3,
                "tool": "nx_revolve",
                "tool_args": {
                    "sketch_id": "sketch_body",
                    "axis_start": {"x": 0.0, "y": 0.0},
                    "axis_end": {"x": 0.0, "y": 75.0},
                    "angle": 360.0,
                    "reverse": False,
                },
                "topology_changes": True,
            },
            {
                "step": 4,
                "tool": "nx_hole",
                "tool_args": {
                    "body_id": "body_main",
                    "center": {"x": 10.0, "y": 0.0},
                    "diameter": 6.0,
                    "depth": 20.0,
                    "start_offset": 0.0,
                },
                "topology_changes": True,
            },
            {
                "step": 5,
                "tool": "nx_hole",
                "tool_args": {
                    "body_id": "body_main",
                    "center": {"x": -10.0, "y": 0.0},
                    "diameter": 6.0,
                    "depth": 20.0,
                    "start_offset": 0.0,
                },
                "topology_changes": True,
            },
        ],
    }

    executable = R.build_executable_plan(frozen)

    assert executable["operations"][0]["result_bindings"] == {
        "object": "sketch_body"
    }
    assert executable["operations"][2]["result_bindings"] == {
        "object": "body_main"
    }
    assert executable["operations"][3]["tool_args"]["body_id"] == "$body_main"
    assert executable["operations"][4]["tool_args"]["body_id"] == "$body_main"
    assert R.check_plan(executable, executable=True) == []


def test_run_plan_revolve_object_binding_resolves_body_consumer():
    import asyncio

    plan = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_revolve",
                "tool_args": {
                    "sketch_id": "SK1",
                    "axis_start": {"x": 0.0, "y": 0.0},
                    "axis_end": {"x": 0.0, "y": 10.0},
                    "angle": 360.0,
                    "reverse": False,
                },
                "result_bindings": {"object": "body_main"},
                "topology_changes": True,
            },
            {
                "step": 2,
                "tool": "nx_hole",
                "tool_args": {
                    "body_id": "$body_main",
                    "center": {"x": 1.0, "y": 2.0},
                    "diameter": 3.0,
                    "depth": 4.0,
                    "start_offset": 0.0,
                },
                "topology_changes": True,
            },
        ],
    }
    calls = []

    class T:
        async def call(self, tool, args):
            calls.append((tool, args))
            if tool == "nx_revolve":
                return {
                    "status": "success",
                    "object": ObjectRef("REV_BODY"),
                    "message": "revolved",
                }
            return {"status": "success", "message": "hole ok"}

    report = asyncio.run(R.run_plan(plan, T()))

    assert report["status"] == "success", report["steps"]
    assert calls[1][0] == "nx_hole"
    assert calls[1][1]["body_id"] == "REV_BODY"



def test_run_plan_mirror_object_binding():
    # regression: the bridge adapts nx_mirror results under "object"; a plan that
    # binds {"object": ...} must resolve in the very next step
    import asyncio
    plan = {"mode": "FAST", "operations": [
        {"step": 10, "tool": "nx_mirror", "tool_args": {"body_id": "src", "plane": "YZ"},
         "result_bindings": {"object": "body_earR"}, "topology_changes": True},
        {"step": 11, "tool": "nx_list_edges", "tool_args": {"body_id": "$body_earR"},
         "selection_criteria": {"linear_only": True}, "expectation": {"count": 1}}]}

    class T:
        async def call(self, tool, args):
            if tool == "nx_mirror":
                return {"status": "success", "object": ObjectRef("MIR1"), "message": "mirrored"}
            return {"status": "success",
                    "edges": [{"index": 0, "curve_type": "Linear", "length": 1.0,
                               "midpoint": [0, 0, 0], "bbox_min": [0, 0, 0],
                               "bbox_max": [1, 1, 1], "direction": "X",
                               "adjacent_faces": 2}],
                    "message": "1 edge"}

    rep = asyncio.run(R.run_plan(plan, T()))
    assert rep["status"] == "success", rep["steps"]




def test_build_existing_single_body_part_binding():
    frozen = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_open_part",
                "tool_args": {"path": "existing.prt"},
                "topology_changes": False,
            },
            {
                "step": 2,
                "tool": "nx_list_bodies",
                "tool_args": {},
                "expectation": {"body_count": 1},
                "topology_changes": False,
            },
            {
                "step": 3,
                "tool": "nx_hole",
                "tool_args": {
                    "body_id": "body_main",
                    "center": {"x": 0, "y": 0},
                    "diameter": 8,
                    "depth": 10,
                },
                "topology_changes": True,
            },
        ],
    }
    exe = R.build_executable_plan(frozen)
    assert exe["operations"][1]["result_bindings"] == {"objects": "body_main"}
    assert exe["operations"][2]["tool_args"]["body_id"] == "$body_main"
    assert R.check_plan(exe, executable=True) == []

# --------------------------------------------------------------------------
# controlled self-healing + runtime config
# --------------------------------------------------------------------------
def test_transport_ping_error_passthrough():
    class Bridge:
        last_ping_error = "status failed: inactive NX object"

        def ping(self):
            return False

    transport = R.NXTransport(workspace_root=".")
    transport._bridge = Bridge()
    assert transport.ping() is False
    assert transport.ping_error() == "status failed: inactive NX object"


def test_load_runtime_config_missing_is_empty():
    missing = os.path.join(PROJECT, "__missing_runtime_config__.json")
    assert R.load_runtime_config(missing) == {}


def test_repair_request_first_attempt_rejects_report():
    errs = R.repair_request_errors(
        0,
        "normal",
        False,
        r"C:\\ws\\part.prt",
        {
            "status": "failed",
            "failed_step": 4,
            "repair_attempt": 0,
            "planned_part": r"C:\\ws\\part.prt",
        },
    )
    assert any("only valid" in e for e in errs)


def test_default_modeling_capability_registry_is_valid():
    registry = R.load_modeling_capability_registry()
    assert R.capability_registry_errors(registry) == []


def _rotational_body_drawing():
    return {
        "profile": {
            "plane": "XZ",
            "rotation_axis": "Z",
            "topology": "closed_polygon",
            "segments": [
                {
                    "type": "line",
                    "x1": 0.0,
                    "z1": 0.0,
                    "x2": 30.0,
                    "z2": 0.0,
                },
                {
                    "type": "line",
                    "x1": 30.0,
                    "z1": 0.0,
                    "x2": 30.0,
                    "z2": 60.0,
                },
                {
                    "type": "line",
                    "x1": 30.0,
                    "z1": 60.0,
                    "x2": 0.0,
                    "z2": 60.0,
                },
                {
                    "type": "line",
                    "x1": 0.0,
                    "z1": 60.0,
                    "x2": 0.0,
                    "z2": 0.0,
                },
            ],
        },
        "features": [],
    }


def _plan_from_operation_contract(contract):
    operations = []
    sketch_id = "SK_BODY"
    step = 1
    for item in contract["operations"]:
        tool_args = json.loads(json.dumps(item.get("fixed_args") or {}))
        if "sketch_id" in item.get("requires", []):
            tool_args["sketch_id"] = sketch_id
        operations.append(
            {
                "step": step,
                "tool": item["tool"],
                "tool_args": tool_args,
            }
        )
        step += 1
    return {"operations": operations}


def test_operation_contract_match_rejects_undeclared_optional_tool_arg():
    expected = {
        "tool": "nx_create_sketch",
        "fixed_args": {"plane": "XZ"},
    }
    actual = {
        "tool": "nx_create_sketch",
        "tool_args": {
            "plane": "XZ",
            "name": "planner-added-name",
        },
    }

    assert R._operation_matches_fixed_args(actual, expected) is False


def test_operation_contract_match_rejects_extra_nested_fixed_arg_key():
    expected = {
        "tool": "nx_sketch_circle",
        "fixed_args": {
            "center": {"x": 4.0, "y": 5.0},
            "diameter": 6.0,
        },
        "requires": ["sketch_id"],
    }
    actual = {
        "tool": "nx_sketch_circle",
        "tool_args": {
            "sketch_id": "S1",
            "center": {"x": 4.0, "y": 5.0, "z": 0.0},
            "diameter": 6.0,
        },
    }

    assert R._operation_matches_fixed_args(actual, expected) is False


def test_operation_contract_match_allows_only_declared_symbolic_wiring():
    expected = {
        "tool": "nx_sketch_line",
        "fixed_args": {
            "start": {"x": 1.0, "y": 2.0},
            "end": {"x": 3.0, "y": 4.0},
        },
        "requires": ["sketch_id"],
    }
    actual = {
        "tool": "nx_sketch_line",
        "tool_args": {
            "sketch_id": "S1",
            "start": {"x": 1.0, "y": 2.0},
            "end": {"x": 3.0, "y": 4.0},
        },
    }

    assert R._operation_matches_fixed_args(actual, expected) is True


def test_rotational_profile_arc_materializes_exact_sketch_arc_operation():
    drawing = {
        "profile": {
            "plane": "XZ",
            "rotation_axis": "Z",
            "topology": "closed_polygon",
            "segments": [
                {
                    "type": "line",
                    "x1": 2.0,
                    "z1": 0.0,
                    "x2": 5.0,
                    "z2": 0.0,
                },
                {
                    "type": "arc",
                    "center": {"x": 5.0, "z": 2.0},
                    "radius": 2.0,
                    "start_angle": -90.0,
                    "end_angle": 0.0,
                },
                {
                    "type": "line",
                    "x1": 7.0,
                    "z1": 2.0,
                    "x2": 7.0,
                    "z2": 8.0,
                },
                {
                    "type": "line",
                    "x1": 7.0,
                    "z1": 8.0,
                    "x2": 2.0,
                    "z2": 8.0,
                },
                {
                    "type": "line",
                    "x1": 2.0,
                    "z1": 8.0,
                    "x2": 2.0,
                    "z2": 0.0,
                },
            ],
        },
        "features": [],
    }

    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)

    assert errors == []
    assert len(dispatches) == 1
    contract = dispatches[0]["payload"]["operation_contracts"][0]
    assert [item["tool"] for item in contract["operations"]] == [
        "nx_create_sketch",
        "nx_sketch_line",
        "nx_sketch_arc",
        "nx_sketch_line",
        "nx_sketch_line",
        "nx_sketch_line",
        "nx_finish_sketch",
        "nx_revolve",
    ]
    arc = contract["operations"][2]
    assert arc["fixed_args"] == {
        "center": {"x": 5.0, "y": 2.0},
        "radius": 2.0,
        "start_angle": -90.0,
        "end_angle": 0.0,
    }
    assert arc["requires"] == ["sketch_id"]

    plan = _plan_from_operation_contract(contract)
    assert R.capability_plan_errors(plan, dispatches) == []


def test_rotational_profile_gate_rejects_arc_fixed_arg_drift():
    drawing = {
        "profile": {
            "plane": "XZ",
            "rotation_axis": "Z",
            "topology": "closed_polygon",
            "segments": [
                {
                    "type": "line",
                    "x1": 2.0,
                    "z1": 0.0,
                    "x2": 5.0,
                    "z2": 0.0,
                },
                {
                    "type": "arc",
                    "center": {"x": 5.0, "z": 2.0},
                    "radius": 2.0,
                    "start_angle": -90.0,
                    "end_angle": 0.0,
                },
                {
                    "type": "line",
                    "x1": 7.0,
                    "z1": 2.0,
                    "x2": 7.0,
                    "z2": 8.0,
                },
                {
                    "type": "line",
                    "x1": 7.0,
                    "z1": 8.0,
                    "x2": 2.0,
                    "z2": 8.0,
                },
                {
                    "type": "line",
                    "x1": 2.0,
                    "z1": 8.0,
                    "x2": 2.0,
                    "z2": 0.0,
                },
            ],
        },
        "features": [],
    }
    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)
    assert errors == []
    assert len(dispatches) == 1
    contract = dispatches[0]["payload"]["operation_contracts"][0]

    mutations = [
        ("center.x", lambda args: args["center"].__setitem__("x", 5.25)),
        ("radius", lambda args: args.__setitem__("radius", 2.25)),
        (
            "start_angle",
            lambda args: args.__setitem__("start_angle", -89.0),
        ),
        (
            "end_angle",
            lambda args: args.__setitem__("end_angle", 1.0),
        ),
    ]
    for field, mutate in mutations:
        plan = _plan_from_operation_contract(contract)
        arc = next(
            item
            for item in plan["operations"]
            if item["tool"] == "nx_sketch_arc"
        )
        mutate(arc["tool_args"])

        gate_errors = R.capability_plan_errors(plan, dispatches)

        assert any(
            "exact revolve operation count must be 1, got 0" in item
            for item in gate_errors
        ), (field, gate_errors)


def test_rotational_profile_arc_fails_closed_without_engineering_radius():
    drawing = {
        "profile": {
            "plane": "XZ",
            "rotation_axis": "Z",
            "segments": [
                {
                    "type": "line",
                    "x1": 2.0,
                    "z1": 0.0,
                    "x2": 5.0,
                    "z2": 0.0,
                },
                {
                    "type": "arc",
                    "center": {"x": 5.0, "z": 2.0},
                    "start_angle": -90.0,
                    "end_angle": 0.0,
                },
                {
                    "type": "line",
                    "x1": 7.0,
                    "z1": 2.0,
                    "x2": 2.0,
                    "z2": 0.0,
                },
            ],
        },
        "features": [],
    }
    capability = R.resolve_modeling_capabilities(
        "rotational_body",
        "Z",
    )[0][0]

    payload, errors = R.dispatch_planner_adapter(capability, drawing)

    assert payload is None
    assert any(
        "incomplete engineering center/radius/angle parameters" in item
        for item in errors
    )


def test_rotational_profile_selects_exact_revolve_capability_and_contract():
    drawing = _rotational_body_drawing()

    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)

    assert errors == []
    assert len(dispatches) == 1
    capability = dispatches[0]["capability"]
    payload = dispatches[0]["payload"]
    assert capability["implementation_id"] == "rotational-profile-revolve-v1"
    assert capability["feature_kind"] == "rotational_body"
    geometry = payload["geometries"][0]
    assert geometry["axis"] == "Z"
    assert geometry["plane"] == "XZ"
    contract = payload["operation_contracts"][0]
    assert [item["tool"] for item in contract["operations"]] == [
        "nx_create_sketch",
        "nx_sketch_line",
        "nx_sketch_line",
        "nx_sketch_line",
        "nx_sketch_line",
        "nx_finish_sketch",
        "nx_revolve",
    ]
    assert contract["operations"][-1]["fixed_args"] == {
        "axis_start": {"x": 0.0, "y": 0.0},
        "axis_end": {"x": 0.0, "y": 60.0},
        "angle": 360.0,
        "reverse": False,
    }

    plan = _plan_from_operation_contract(contract)
    assert R.capability_plan_errors(plan, dispatches) == []


def test_rotational_profile_revolve_fails_closed_when_meridian_crosses_axis():
    drawing = _rotational_body_drawing()
    drawing["profile"]["segments"][0]["x1"] = -1.0
    drawing["profile"]["segments"][2]["x2"] = -1.0
    drawing["profile"]["segments"][3]["x1"] = -1.0
    drawing["profile"]["segments"][3]["x2"] = -1.0

    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)

    assert dispatches == []
    assert any("crosses the rotation axis" in item for item in errors)


def test_capability_resolution_is_feature_axis_scoped():
    candidates, errors = R.resolve_modeling_capabilities(
        "counterbore_hole",
        "X",
    )
    assert errors == []
    assert [item["implementation_id"] for item in candidates] == [
        "principal-axis-counterbore-v1"
    ]


def test_capability_resolution_can_require_exact_only():
    candidates, errors = R.resolve_modeling_capabilities(
        "threaded_hole",
        "X",
        allow_surrogate=False,
    )
    assert candidates == []
    assert any("no modeling capability" in item for item in errors)


def test_future_native_tool_can_preempt_surrogate_without_changing_feature_contract():
    registry = {
        "schema_version": 1,
        "registry_kind": "static_modeling_capabilities",
        "implementations": [
            {
                "implementation_id": "thread-surrogate",
                "feature_kind": "threaded_hole",
                "exactness": "surrogate",
                "supported_axes": ["X"],
                "required_tools": ["nx_extrude"],
                "planner_adapter": "metric_thread_surrogate",
                "gate_b_validator": "thread_surrogate",
                "priority": 100,
            },
            {
                "implementation_id": "native-thread",
                "feature_kind": "threaded_hole",
                "exactness": "exact",
                "supported_axes": ["X"],
                "required_tools": ["nx_thread"],
                "planner_adapter": "native_thread",
                "gate_b_validator": "native_thread_geometry",
                "priority": 10,
            },
        ],
    }

    candidates, errors = R.resolve_modeling_capabilities(
        "threaded_hole",
        "X",
        registry=registry,
        available_tools={*R.CERTIFIED_TOOLS, "nx_thread"},
        planner_adapter_handlers={
            *R.REGISTERED_PLANNER_ADAPTER_HANDLERS,
            "native_thread",
        },
        gate_b_validator_handlers={
            *R.REGISTERED_GATE_B_VALIDATOR_HANDLERS,
            "native_thread_geometry",
        },
    )

    assert errors == []
    assert [item["implementation_id"] for item in candidates] == [
        "native-thread",
        "thread-surrogate",
    ]


def test_capability_registry_fails_closed_when_planner_adapter_is_unbound():
    registry = R.load_modeling_capability_registry()
    registry = json.loads(json.dumps(registry))
    registry["implementations"][0]["planner_adapter"] = "missing_adapter"

    errors = R.capability_registry_errors(registry)

    assert any(
        "unbound planner_adapter 'missing_adapter'" in item
        for item in errors
    )


def test_capability_registry_fails_closed_when_gate_b_validator_is_unbound():
    registry = R.load_modeling_capability_registry()
    registry = json.loads(json.dumps(registry))
    registry["implementations"][0]["gate_b_validator"] = "missing_validator"

    errors = R.capability_registry_errors(registry)

    assert any(
        "unbound gate_b_validator 'missing_validator'" in item
        for item in errors
    )



def _rect_profile(plane, u_min, u_max, v_min, v_max):
    axis_u, axis_v = plane.lower()
    points = [
        (u_min, v_min),
        (u_max, v_min),
        (u_max, v_max),
        (u_min, v_max),
    ]
    segments = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        segments.append(
            {
                "type": "line",
                f"{axis_u}1": start[0],
                f"{axis_v}1": start[1],
                f"{axis_u}2": end[0],
                f"{axis_v}2": end[1],
            }
        )
    return {"plane": plane, "topology": "rect", "segments": segments}


def _r6_l_profile():
    points = [
        (-16.0, 0.0),
        (16.0, 0.0),
        (16.0, 66.0),
        (0.0, 66.0),
        (0.0, 8.0),
        (-16.0, 8.0),
    ]
    segments = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        segments.append(
            {
                "type": "line",
                "y1": start[0],
                "z1": start[1],
                "y2": end[0],
                "z2": end[1],
            }
        )
    return {
        "plane": "YZ",
        "topology": "L",
        "segments": segments,
    }


def _r6_continuous_hole_slot_drawing():
    return {
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 32,
            "height_z": 66,
        },
        "profile": _r6_l_profile(),
        "features": [
            {
                "id": "S1",
                "type": "slot",
                "width": 2,
                "width_axis": "X",
                "through_axis": "Y",
                "centerline": {"x": 0},
                "bottom_z": 50,
                "top_z": 66,
            },
            {
                "id": "H1",
                "type": "hole",
                "axis": "Y",
                "diameter": 20,
                "through": True,
                "centerline": {"x": 0, "z": 40},
                "count": 1,
            },
        ],
    }


def _plan_from_operation_contract(contract):
    operations = []
    sketch_id = "sketch_hole_slot"
    step = 1
    for item in contract["operations"]:
        tool = item["tool"]
        args = json.loads(json.dumps(item.get("fixed_args") or {}))
        if "sketch_id" in item.get("requires", []):
            args["sketch_id"] = sketch_id
        if "target_body_id" in item.get("requires", []):
            args["target_body_id"] = "body_main"
        operation = {
            "step": step,
            "tool": tool,
            "tool_args": args,
        }
        for key, value in (item.get("operation_fields") or {}).items():
            operation[key] = json.loads(json.dumps(value))
        operations.append(operation)
        step += 1
    return {"operations": operations}


def test_capability_handler_maps_cover_registered_bindings():
    assert set(R.PLANNER_ADAPTER_HANDLER_MAP) == set(
        R.REGISTERED_PLANNER_ADAPTER_HANDLERS
    )
    assert set(R.GATE_B_VALIDATOR_HANDLER_MAP) == set(
        R.REGISTERED_GATE_B_VALIDATOR_HANDLERS
    )


def test_native_z_hole_capability_dispatch_round_trip():
    drawing = {
        "overall_dimensions": {
            "length_x": 20,
            "width_y": 20,
            "height_z": 10,
        },
        "profile": _rect_profile("XY", -10, 10, -10, 10),
        "features": [
            {
                "id": "H1",
                "type": "hole",
                "axis": "Z",
                "diameter": 6,
                "through": True,
                "centerline": {"x": 0, "y": 0},
                "count": 1,
            }
        ],
    }
    capability = R.resolve_modeling_capabilities("hole", "Z")[0][0]
    payload, errors = R.dispatch_planner_adapter(capability, drawing)

    assert errors == []
    assert payload is not None
    assert payload["geometries"] == [
        {
            "feature_id": "H1",
            "axis": "Z",
            "transverse_centers": [[0.0, 0.0]],
            "diameter": 6.0,
            "axial_range": [0.0, 10.0],
            "count": 1,
        }
    ]
    assert payload["operation_contracts"] == [
        {
            "feature_id": "H1",
            "role": "hole",
            "axis": "Z",
            "operations": [
                {
                    "tool": "nx_hole",
                    "fixed_args": {
                        "center": {"x": 0.0, "y": 0.0},
                        "diameter": 6.0,
                        "depth": 10.0,
                        "start_offset": 0.0,
                    },
                    "requires": ["body_id"],
                }
            ],
        }
    ]

    plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_hole",
                "tool_args": {
                    "body_id": "$body",
                    "center": {"x": 0, "y": 0},
                    "diameter": 6,
                    "depth": 10,
                    "start_offset": 0,
                },
            }
        ]
    }

    assert R.dispatch_gate_b_validator(capability, plan, payload) == []

    plan["operations"][0]["tool_args"]["depth"] = 9
    assert any(
        "changes axial range" in item
        for item in R.dispatch_gate_b_validator(capability, plan, payload)
    )



def test_native_z_hole_material_interval_supports_curved_rotational_profile():
    drawing = {
        "overall_dimensions": {
            "length_x": 14,
            "width_y": 14,
            "height_z": 8,
        },
        "profile": {
            "plane": "XZ",
            "rotation_axis": "Z",
            "topology": "closed_polygon",
            "segments": [
                {
                    "type": "line",
                    "x1": 2.0,
                    "z1": 0.0,
                    "x2": 5.0,
                    "z2": 0.0,
                },
                {
                    "type": "arc",
                    "center": {"x": 5.0, "z": 2.0},
                    "radius": 2.0,
                    "start_angle": -90.0,
                    "end_angle": 0.0,
                },
                {
                    "type": "line",
                    "x1": 7.0,
                    "z1": 2.0,
                    "x2": 7.0,
                    "z2": 8.0,
                },
                {
                    "type": "line",
                    "x1": 7.0,
                    "z1": 8.0,
                    "x2": 2.0,
                    "z2": 8.0,
                },
                {
                    "type": "line",
                    "x1": 2.0,
                    "z1": 8.0,
                    "x2": 2.0,
                    "z2": 0.0,
                },
            ],
        },
        "features": [
            {
                "id": "H1",
                "type": "hole",
                "axis": "Z",
                "diameter": 1.0,
                "through": True,
                "centerline": {"x": 6.0, "y": 0.0},
                "count": 1,
            }
        ],
    }
    capability = R.resolve_modeling_capabilities("hole", "Z")[0][0]

    payload, errors = R.dispatch_planner_adapter(capability, drawing)

    expected_start = 2.0 - math.sqrt(3.0)
    assert errors == []
    assert payload is not None
    assert len(payload["geometries"]) == 1
    axial_range = payload["geometries"][0]["axial_range"]
    assert abs(axial_range[0] - expected_start) <= 1e-9
    assert abs(axial_range[1] - 8.0) <= 1e-9

    radial_equivalent, radial_errors = R.resolve_axis_material_intervals(
        drawing,
        "Z",
        [0.0, 6.0],
        exclude_feature_ids={"H1"},
    )
    assert radial_errors == []
    assert len(radial_equivalent) == 1
    assert abs(radial_equivalent[0][0] - expected_start) <= 1e-9
    assert abs(radial_equivalent[0][1] - 8.0) <= 1e-9



def test_principal_axis_hole_composes_point_tangent_slot_profile():
    drawing = _r6_continuous_hole_slot_drawing()
    capability = R.resolve_modeling_capabilities("hole", "Y")[0][0]

    payload, errors = R.dispatch_planner_adapter(
        capability,
        drawing,
    )

    assert errors == []
    assert payload is not None
    geometry = payload["geometries"][0]
    assert geometry["axial_range"] == [0.0, 16.0]
    assert geometry["representation"] == "continuous_hole_slot_profile"
    assert geometry["composed_feature_ids"] == ["H1", "S1"]

    contract = payload["operation_contracts"][0]
    assert contract["role"] == "continuous_hole_slot_cut"
    assert contract["representation"] == "continuous_hole_slot_profile"
    assert [item["tool"] for item in contract["operations"]] == [
        "nx_create_sketch",
        "nx_sketch_line",
        "nx_sketch_line",
        "nx_sketch_arc",
        "nx_sketch_arc",
        "nx_sketch_arc",
        "nx_sketch_arc",
        "nx_sketch_line",
        "nx_finish_sketch",
        "nx_extrude",
    ]
    assert contract["operations"][-1]["fixed_args"] == {
        "distance": 16.0,
        "start_offset": 0.0,
        "reverse": False,
        "operation": "subtract",
    }

    plan = _plan_from_operation_contract(contract)
    assert R.dispatch_gate_b_validator(capability, plan, payload) == []


def test_principal_axis_hole_composite_gate_rejects_slot_profile_drift():
    drawing = _r6_continuous_hole_slot_drawing()
    capability = R.resolve_modeling_capabilities("hole", "Y")[0][0]
    payload, errors = R.dispatch_planner_adapter(capability, drawing)
    assert errors == []
    assert payload is not None

    plan = _plan_from_operation_contract(
        payload["operation_contracts"][0]
    )
    line = next(
        item
        for item in plan["operations"]
        if item["tool"] == "nx_sketch_line"
    )
    line["tool_args"]["end"]["y"] = 65.0

    gate_errors = R.dispatch_gate_b_validator(
        capability,
        plan,
        payload,
    )

    assert any(
        "continuous profile operation count must be 1, got 0" in item
        for item in gate_errors
    )


def test_principal_axis_hole_capability_dispatch_round_trip():
    drawing = {
        "overall_dimensions": {
            "length_x": 20,
            "width_y": 20,
            "height_z": 10,
        },
        "profile": _rect_profile("YZ", -10, 10, 0, 10),
        "features": [
            {
                "id": "HX",
                "type": "hole",
                "axis": "X",
                "diameter": 6,
                "through": True,
                "centerline": {"y": 0, "z": 5},
                "count": 1,
            }
        ],
    }
    capability = R.resolve_modeling_capabilities("hole", "X")[0][0]
    payload, errors = R.dispatch_planner_adapter(capability, drawing)

    assert errors == []
    assert payload is not None
    assert payload["geometries"][0]["axial_range"] == [-10.0, 10.0]
    assert payload["operation_contracts"][0]["operations"][-1]["fixed_args"] == {
        "distance": 20.0,
        "start_offset": -10.0,
        "reverse": False,
        "operation": "subtract",
    }

    plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_sketch",
                "tool_args": {"plane": "YZ"},
            },
            {
                "step": 2,
                "tool": "nx_sketch_circle",
                "tool_args": {
                    "sketch_id": "S1",
                    "center": {"x": 0, "y": 5},
                    "diameter": 6,
                },
            },
            {
                "step": 3,
                "tool": "nx_extrude",
                "tool_args": {
                    "sketch_id": "S1",
                    "distance": 20,
                    "start_offset": -10,
                    "reverse": False,
                    "operation": "subtract",
                },
            },
        ]
    }

    assert R.dispatch_gate_b_validator(capability, plan, payload) == []


def test_native_z_counterbore_capability_dispatch_round_trip():
    drawing = {
        "overall_dimensions": {
            "length_x": 20,
            "width_y": 20,
            "height_z": 10,
        },
        "profile": _rect_profile("XY", -10, 10, -10, 10),
        "features": [
            {
                "id": "CB1",
                "type": "counterbore_hole",
                "axis": "Z",
                "hole_diameter": 6,
                "counterbore_diameter": 10,
                "counterbore_depth": 3,
                "through": True,
                "centerline": {"x": 0, "y": 0},
            }
        ],
    }
    capability = R.resolve_modeling_capabilities("counterbore_hole", "Z")[0][0]
    payload, errors = R.dispatch_planner_adapter(capability, drawing)

    assert errors == []
    assert payload is not None

    plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_counterbore_hole",
                "tool_args": {
                    "body_id": "$body",
                    "center": {"x": 0, "y": 0},
                    "hole_diameter": 6,
                    "hole_depth": 10,
                    "counterbore_diameter": 10,
                    "counterbore_depth": 3,
                    "start_offset": 0,
                },
            }
        ]
    }

    assert R.dispatch_gate_b_validator(capability, plan, payload) == []



def test_thread_adapter_materializes_split_entry_operation_contract():
    drawing = {
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 32,
            "height_z": 66,
        },
        "profile": _rect_profile("YZ", -16, 16, 0, 66),
        "features": [
            {
                "id": "S1",
                "type": "slot",
                "width": 2,
                "width_axis": "X",
                "through_axis": "Y",
                "centerline": {"x": 0},
                "bottom_z": 50,
                "top_z": 66,
            },
            {
                "id": "T1",
                "type": "threaded_hole",
                "thread_spec": "M6",
                "thread_depth": 12,
                "axis": "X",
                "centerline": {"y": 8, "z": 58},
                "material_side": "min",
                "entry_endpoint": "max",
            },
        ],
    }
    capability = R.resolve_modeling_capabilities(
        "threaded_hole",
        "X",
    )[0][0]

    payload, errors = R.dispatch_planner_adapter(
        capability,
        drawing,
    )

    assert errors == []
    assert payload is not None
    assert payload["geometries"][0]["axial_range"] == [-1.0, -13.0]

    contract = payload["operation_contracts"][0]
    assert contract["feature_id"] == "T1"
    assert contract["role"] == "thread_surrogate"
    assert contract["axis"] == "X"
    assert contract["operations"][0]["fixed_args"] == {"plane": "YZ"}
    assert contract["operations"][1]["fixed_args"] == {
        "center": {"x": 8.0, "y": 58.0},
        "diameter": 5.0,
    }
    assert contract["operations"][-1]["fixed_args"] == {
        "distance": 12.0,
        "start_offset": 1.0,
        "reverse": True,
        "operation": "subtract",
    }
    assert contract["operations"][-1]["operation_fields"] == {
        "thread_surrogate_use": {
            "feature_id": "T1",
            "owner_feature_id": "T1",
            "material_side": "min",
            "entry_endpoint": "max",
        }
    }


def test_thread_operation_contract_operation_fields_round_trip():
    drawing = {
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 32,
            "height_z": 66,
        },
        "profile": _rect_profile("YZ", -16, 16, 0, 66),
        "features": [
            {
                "id": "S1",
                "type": "slot",
                "width": 2,
                "width_axis": "X",
                "through_axis": "Y",
                "centerline": {"x": 0},
                "bottom_z": 50,
                "top_z": 66,
            },
            {
                "id": "T1",
                "type": "threaded_hole",
                "thread_spec": "M6",
                "thread_depth": 12,
                "axis": "X",
                "centerline": {"y": 8, "z": 58},
                "material_side": "min",
                "entry_endpoint": "max",
            },
        ],
    }
    capability = R.resolve_modeling_capabilities(
        "threaded_hole",
        "X",
    )[0][0]
    payload, errors = R.dispatch_planner_adapter(capability, drawing)

    assert errors == []
    assert payload is not None
    contract = payload["operation_contracts"][0]
    plan = _plan_from_operation_contract(contract)

    marked = [
        op
        for op in plan["operations"]
        if isinstance(op.get("thread_surrogate_use"), dict)
    ]
    assert len(marked) == 1
    assert marked[0]["thread_surrogate_use"] == {
        "feature_id": "T1",
        "owner_feature_id": "T1",
        "material_side": "min",
        "entry_endpoint": "max",
    }
    assert R.dispatch_gate_b_validator(capability, plan, payload) == []

    marked[0].pop("thread_surrogate_use")
    gate_errors = R.dispatch_gate_b_validator(capability, plan, payload)
    assert any(
        "operation count differs from drawing" in item
        for item in gate_errors
    )


def test_required_supported_feature_must_survive_adapter_geometry_payload():
    drawing = {
        "overall_dimensions": {
            "length_x": 20,
            "width_y": 20,
            "height_z": 10,
        },
        "profile": _rect_profile("XY", -10, 10, -10, 10),
        "features": [
            {
                "id": "H1",
                "type": "hole",
                "axis": "Z",
                "diameter": 6,
                "through": True,
                "centerline": {"x": 0, "y": 0},
                "count": 1,
            }
        ],
    }

    original = R.dispatch_planner_adapter

    def drop_geometry(capability, source_drawing):
        if capability.get("feature_kind") == "hole":
            return (
                {
                    "implementation_id": capability.get("implementation_id"),
                    "planner_adapter": capability.get("planner_adapter"),
                    "gate_b_validator": capability.get("gate_b_validator"),
                    "feature_kind": capability.get("feature_kind"),
                    "supported_axes": list(capability.get("supported_axes") or []),
                    "geometries": [],
                    "operation_contracts": [],
                },
                [],
            )
        return original(capability, source_drawing)

    R.dispatch_planner_adapter = drop_geometry
    try:
        dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)
    finally:
        R.dispatch_planner_adapter = original

    assert dispatches == []
    assert errors == [
        "capability_materialization_violation: required feature 'H1' (hole) "
        "is missing from adapter geometry payload"
    ]


def test_required_supported_feature_must_survive_operation_contract_materialization():
    drawing = {
        "overall_dimensions": {
            "length_x": 20,
            "width_y": 20,
            "height_z": 10,
        },
        "profile": _rect_profile("XY", -10, 10, -10, 10),
        "features": [
            {
                "id": "H1",
                "type": "hole",
                "axis": "Z",
                "diameter": 6,
                "through": True,
                "centerline": {"x": 0, "y": 0},
                "count": 1,
            }
        ],
    }

    original = R.dispatch_planner_adapter

    def drop_contract(capability, source_drawing):
        payload, errors = original(capability, source_drawing)
        if (
            not errors
            and payload is not None
            and capability.get("feature_kind") == "hole"
        ):
            payload = dict(payload)
            payload["operation_contracts"] = []
        return payload, errors

    R.dispatch_planner_adapter = drop_contract
    try:
        dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)
    finally:
        R.dispatch_planner_adapter = original

    assert dispatches == []
    assert errors == [
        "capability_materialization_violation: required feature 'H1' (hole) "
        "is missing from operation contracts"
    ]


def test_required_slot_without_capability_fails_closed_instead_of_being_ignored():
    drawing = {
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 30,
            "height_z": 20,
        },
        "profile": _rect_profile("XY", -20, 20, -15, 15),
        "features": [
            {
                "id": "SLOT1",
                "type": "slot",
                "width": 6,
                "width_axis": "X",
                "through_axis": "Z",
                "top_z": 20,
                "bottom_z": 0,
                "required_for_modeling": True,
            }
        ],
    }

    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)

    assert dispatches == []
    assert errors == [
        "capability_selection_violation: feature 'SLOT1': "
        "no modeling capability for required feature_kind='slot'"
    ]


def test_required_recessed_hole_without_capability_fails_closed():
    drawing = {
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 30,
            "height_z": 20,
        },
        "profile": _rect_profile("XY", -20, 20, -15, 15),
        "features": [
            {
                "id": "R1",
                "type": "recessed_hole",
                "axis": "Z",
                "diameter": 6,
                "recess_diameter": 10,
                "recess_depth": 3,
                "through": True,
                "centerline": {"x": 0, "y": 0},
                "required_for_modeling": True,
            }
        ],
    }

    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)

    assert dispatches == []
    assert errors == [
        "capability_selection_violation: feature 'R1': "
        "no modeling capability for required feature_kind='recessed_hole'"
    ]


def test_reference_boundary_without_capability_remains_nonphysical_advisory():
    drawing = {
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 30,
            "height_z": 20,
        },
        "profile": _rect_profile("XY", -20, 20, -15, 15),
        "features": [
            {
                "id": "REF1",
                "type": "reference_boundary",
                "boundary": {"x": 0},
                "required_for_modeling": True,
            }
        ],
    }

    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)

    assert errors == []
    assert [
        item["capability"]["implementation_id"]
        for item in dispatches
    ] == []


def test_unified_capability_dispatch_selects_native_z_hole():
    drawing = {
        "overall_dimensions": {
            "length_x": 20,
            "width_y": 20,
            "height_z": 10,
        },
        "profile": _rect_profile("XY", -10, 10, -10, 10),
        "features": [
            {
                "id": "H1",
                "type": "hole",
                "axis": "Z",
                "diameter": 6,
                "through": True,
                "centerline": {"x": 0, "y": 0},
                "count": 1,
            }
        ],
    }

    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)

    assert errors == []
    assert [
        item["capability"]["implementation_id"]
        for item in dispatches
    ] == ["native-z-hole-v1"]


def test_unified_capability_gate_b_rejects_plain_hole_range_drift():
    drawing = {
        "overall_dimensions": {
            "length_x": 20,
            "width_y": 20,
            "height_z": 10,
        },
        "profile": _rect_profile("XY", -10, 10, -10, 10),
        "features": [
            {
                "id": "H1",
                "type": "hole",
                "axis": "Z",
                "diameter": 6,
                "through": True,
                "centerline": {"x": 0, "y": 0},
                "count": 1,
            }
        ],
    }
    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)
    assert errors == []

    wrong_plan = {
        "operations": [
            {
                "step": 1,
                "tool": "nx_hole",
                "tool_args": {
                    "body_id": "$body",
                    "center": {"x": 0, "y": 0},
                    "diameter": 6,
                    "depth": 9,
                    "start_offset": 0,
                },
            }
        ]
    }

    gate_errors = R.capability_plan_errors(wrong_plan, dispatches)

    assert any("changes axial range" in item for item in gate_errors)


def test_unified_capability_dispatch_deduplicates_shared_xy_implementation():
    drawing = {
        "overall_dimensions": {
            "length_x": 20,
            "width_y": 20,
            "height_z": 10,
        },
        "profile": _rect_profile("YZ", -10, 10, 0, 10),
        "features": [
            {
                "id": "HX",
                "type": "hole",
                "axis": "X",
                "diameter": 4,
                "through": True,
                "centerline": {"y": -4, "z": 2},
            },
            {
                "id": "HY",
                "type": "hole",
                "axis": "Y",
                "diameter": 4,
                "axial_range": [-10, 10],
                "centerline": {"x": 0, "z": 8},
            },
        ],
    }

    dispatches, errors = R.resolve_drawing_capability_dispatches(drawing)

    assert errors == []
    assert [
        item["capability"]["implementation_id"]
        for item in dispatches
    ] == ["principal-axis-hole-v1"]
    assert {
        geometry["feature_id"]
        for geometry in dispatches[0]["payload"]["geometries"]
    } == {"HX", "HY"}


def test_capability_registry_fails_closed_when_required_tool_is_unavailable():
    registry = {
        "schema_version": 1,
        "registry_kind": "static_modeling_capabilities",
        "implementations": [
            {
                "implementation_id": "native-thread",
                "feature_kind": "threaded_hole",
                "exactness": "exact",
                "supported_axes": ["X"],
                "required_tools": ["nx_thread"],
                "planner_adapter": "native_thread",
                "gate_b_validator": "native_thread_geometry",
                "priority": 10,
            }
        ],
    }

    candidates, errors = R.resolve_modeling_capabilities(
        "threaded_hole",
        "X",
        registry=registry,
    )

    assert candidates == []
    assert any("unavailable certified tools" in item for item in errors)


def test_repair_request_second_attempt_requires_benchmark_overwrite():
    prev = {
        "status": "failed",
        "failed_step": 4,
        "repair_attempt": 0,
        "planned_part": r"C:\\ws\\part.prt",
    }
    errs = R.repair_request_errors(1, "normal", False, r"C:\\ws\\part.prt", prev)
    assert any("benchmark" in e for e in errs)
    assert any("allow-overwrite" in e for e in errs)


def test_repair_request_second_attempt_accepts_same_failed_part():
    prev = {
        "status": "failed",
        "failed_step": 4,
        "repair_attempt": 0,
        "planned_part": r"C:\\ws\\part.prt",
    }
    assert R.repair_request_errors(
        1, "benchmark", True, r"C:\\ws\\part.prt", prev
    ) == []


def test_repair_request_rejects_second_repair():
    prev = {
        "status": "failed",
        "failed_step": 8,
        "repair_attempt": 1,
        "planned_part": r"C:\\ws\\part.prt",
    }
    errs = R.repair_request_errors(
        1, "benchmark", True, r"C:\\ws\\part.prt", prev
    )
    assert any("already consumed" in e for e in errs)


def test_repair_request_rejects_different_part():
    prev = {
        "status": "failed",
        "failed_step": 4,
        "repair_attempt": 0,
        "planned_part": r"C:\\ws\\part-a.prt",
    }
    errs = R.repair_request_errors(
        1, "benchmark", True, r"C:\\ws\\part-b.prt", prev
    )
    assert any("different part" in e for e in errs)


def test_run_history_persists_consumed_repair(tmp_path=None):
    import tempfile
    d = tmp_path or tempfile.mkdtemp()
    hp = os.path.join(str(d), "repair-history.json")
    h = R.RunHistory(hp)
    h.record_start(
        r"C:\work\repair.prt",
        "benchmark",
        "repair.json",
        repair_attempt=1,
    )
    assert h.most_recent(r"C:\work\repair.prt")["repair_attempt"] == 1
    h2 = R.RunHistory(hp)
    assert h2.most_recent(r"C:\work\repair.prt")["repair_attempt"] == 1


def _capture_json_command(command, args):
    import contextlib
    import io

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = command(args)
    return exit_code, json.loads(output.getvalue())


def _contract_wiring_fixture():
    """Synthetic Adapter output: fixed geometry belongs only to the Adapter."""
    dispatches = [
        {
            "capability": {"implementation_id": "synthetic-test-v1"},
            "payload": {
                "operation_contracts": [
                    {
                        "feature_id": "F1",
                        "role": "synthetic",
                        "operations": [
                            {
                                "tool": "nx_create_sketch",
                                "fixed_args": {"plane": "XZ", "offset": 0.0},
                                "requires": [],
                            },
                            {
                                "tool": "nx_extrude",
                                "fixed_args": {
                                    "distance": 10.0,
                                    "reverse": False,
                                    "start_offset": 0,
                                    "metadata": {},
                                },
                                "requires": ["sketch_id", "target_body_id"],
                                "operation_fields": {
                                    "thread_surrogate_use": {
                                        "implementation": "contract-owned",
                                    },
                                },
                            },
                        ],
                    },
                ],
            },
        },
    ]
    wiring = {
        "schema": "mode-b-contract-wiring-v1",
        "operations": [
            {
                "manual": {
                    "tool": "nx_create_part",
                    "tool_args": {"path": "fresh-test.prt", "units": "mm"},
                },
                "topology_changes": False,
            },
            {
                "contract_ref": [0, 0, 0],
                "requires": {},
                "topology_changes": False,
            },
            {
                "contract_ref": [0, 0, 1],
                "requires": {
                    "sketch_id": "SKETCH_MAIN",
                    "target_body_id": "BODY_MAIN",
                },
                "topology_changes": True,
            },
            {
                "manual": {"tool": "nx_save_part", "tool_args": {}},
                "topology_changes": False,
            },
        ],
    }
    return dispatches, wiring


def test_contract_wiring_copies_every_fixed_arg_and_operation_field():
    import copy

    dispatches, wiring = _contract_wiring_fixture()
    original = copy.deepcopy(dispatches)
    plan, errors = R.materialize_frozen_from_contract_wiring(
        "current-drawing.json", dispatches, wiring
    )
    assert errors == []
    assert plan is not None
    assert dispatches == original
    assert [op["step"] for op in plan["operations"]] == [1, 2, 3, 4]
    assert plan["operations"][2]["tool_args"] == {
        "distance": 10.0,
        "reverse": False,
        "start_offset": 0,
        "metadata": {},
        "sketch_id": "SKETCH_MAIN",
        "target_body_id": "BODY_MAIN",
    }
    assert plan["operations"][2]["thread_surrogate_use"] == {
        "implementation": "contract-owned"
    }


def test_contract_wiring_rejects_missing_duplicate_or_unauthorized_operations():
    import copy

    dispatches, source = _contract_wiring_fixture()
    for variant in (
        "missing", "duplicate", "manual_geometry", "extra_requires",
        "bad_ref", "bad_topology_type",
    ):
        wiring = copy.deepcopy(source)
        if variant == "missing":
            wiring["operations"].pop(2)
        elif variant == "duplicate":
            wiring["operations"][3] = copy.deepcopy(wiring["operations"][2])
        elif variant == "manual_geometry":
            wiring["operations"][0]["manual"]["tool"] = "nx_extrude"
        elif variant == "extra_requires":
            wiring["operations"][2]["requires"]["distance"] = "12"
        elif variant == "bad_ref":
            wiring["operations"][1]["contract_ref"] = [9, 0, 0]
        elif variant == "bad_topology_type":
            wiring["operations"][2]["topology_changes"] = "true"
        plan, errors = R.materialize_frozen_from_contract_wiring(
            "current-drawing.json", dispatches, wiring
        )
        assert plan is None, variant
        assert errors, variant


def test_materialize_frozen_cli_rejects_existing_frozen_without_reading_drawing(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    out = os.path.join(directory, "frozen.json")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("do-not-overwrite")
    original = R._drawing_modeling_context
    try:
        def forbidden(_path):
            raise AssertionError("existing frozen file must stop before drawing")
        R._drawing_modeling_context = forbidden
        code, report = _capture_json_command(
            R._cmd_materialize_frozen,
            SimpleNamespace(
                drawing=os.path.join(directory, "drawing.json"),
                wiring=os.path.join(directory, "wiring.json"),
                out=out,
            ),
        )
    finally:
        R._drawing_modeling_context = original
    assert code == 1
    assert report["ok"] is False
    assert "already exists" in report["errors"][0]
    with open(out, encoding="utf-8") as handle:
        assert handle.read() == "do-not-overwrite"


def test_materialize_frozen_cli_writes_only_validated_plan(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    wiring_path = os.path.join(directory, "wiring.json")
    drawing_path = os.path.join(directory, "drawing.json")
    out = os.path.join(directory, "fresh-frozen.json")
    dispatches, wiring = _contract_wiring_fixture()
    with open(wiring_path, "w", encoding="utf-8") as handle:
        json.dump(wiring, handle)

    original_model = R._drawing_modeling_context
    original_check = R.check_plan
    original_gate = R.capability_plan_errors
    try:
        R._drawing_modeling_context = lambda path: ({}, dispatches, [])
        R.check_plan = lambda *args, **kwargs: []
        R.capability_plan_errors = lambda *args, **kwargs: []
        args = SimpleNamespace(drawing=drawing_path, wiring=wiring_path, out=out)
        code, result = _capture_json_command(R._cmd_materialize_frozen, args)
    finally:
        R._drawing_modeling_context = original_model
        R.check_plan = original_check
        R.capability_plan_errors = original_gate

    assert code == 0, result
    assert result["ok"] is True
    assert result["operations"] == 4
    with open(out, encoding="utf-8") as handle:
        frozen = json.load(handle)
    assert frozen["source_drawing"] == os.path.abspath(drawing_path)
    assert frozen["operations"][2]["tool_args"]["reverse"] is False
    assert frozen["operations"][2]["tool_args"]["start_offset"] == 0
    assert frozen["operations"][2]["tool_args"]["metadata"] == {}


def test_plan_contracts_cli_exposes_adapter_operation_contracts(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    drawing_path = os.path.join(directory, "drawing.json")
    with open(drawing_path, "w", encoding="utf-8") as handle:
        json.dump({}, handle)

    original = R._drawing_modeling_context
    try:
        R._drawing_modeling_context = lambda path: (
            {},
            [
                {
                    "capability": {
                        "implementation_id": "principal-axis-thread-v1",
                        "feature_kind": "threaded_hole",
                        "exactness": "surrogate",
                        "supported_axes": ["X", "Y"],
                        "planner_adapter": "metric_thread_surrogate",
                        "gate_b_validator": "thread_surrogate",
                    },
                    "payload": {
                        "geometries": [
                            {
                                "feature_id": "T1",
                                "axis": "X",
                                "axial_range": [-1.0, -13.0],
                            }
                        ],
                        "recipes": [
                            {
                                "feature_id": "T1",
                                "surrogate_diameter": 5.0,
                            }
                        ],
                        "operation_contracts": [
                            {
                                "feature_id": "T1",
                                "role": "thread_surrogate",
                                "axis": "X",
                                "operations": [
                                    {
                                        "tool": "nx_extrude",
                                        "fixed_args": {
                                            "distance": 12.0,
                                            "start_offset": 1.0,
                                            "reverse": True,
                                            "operation": "subtract",
                                        },
                                        "requires": [
                                            "sketch_id",
                                            "target_body_id",
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
            [],
        )
        exit_code, result = _capture_json_command(
            R._cmd_plan_contracts,
            SimpleNamespace(drawing=drawing_path),
        )
    finally:
        R._drawing_modeling_context = original

    assert exit_code == 0
    assert result["ok"] is True
    assert result["errors"] == []
    assert result["drawing"] == os.path.abspath(drawing_path)
    assert result["planner_contract"] == {
        "fixed_args_policy": "copy_exact_key_set_and_values",
        "preserve_explicit_false_zero_and_empty_objects": True,
        "operation_fields_policy": "copy_exact_to_frozen_operation_root",
        "operation_fields_are_not_tool_args": True,
        "requires_policy": "fill_only_declared_symbolic_wiring",
        "source_drawing_policy": "copy_exact_plan_contracts_drawing_to_frozen_top_level",
        "stage_b_failure_policy": "stop_no_retry_no_source_inspection",
        "must_stop_after_first_stage_b_failure": True,
        "may_edit_frozen_after_stage_b_failure": False,
        "may_retry_stage_b": False,
        "may_inspect_source_after_stage_b_failure": False,
    }
    assert result["contracts"][0]["implementation_id"] == (
        "principal-axis-thread-v1"
    )
    assert result["contracts"][0]["operation_contracts"][0]["operations"][0][
        "fixed_args"
    ] == {
        "distance": 12.0,
        "start_offset": 1.0,
        "reverse": True,
        "operation": "subtract",
    }


def test_mode_b_source_drawing_binding_requires_exact_current_path(tmp_path=None):
    import tempfile

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    current = os.path.join(directory, "current-drawing.json")
    stale = os.path.join(directory, "stale-drawing.json")
    plan = {
        "source_drawing": os.path.abspath(current),
        "operations": [{"step": 1, "tool": "nx_status", "tool_args": {}}],
    }

    assert R._mode_b_source_drawing_errors(plan, current) == []

    missing = dict(plan)
    missing.pop("source_drawing")
    missing_errors = R._mode_b_source_drawing_errors(missing, current)
    assert any("missing source_drawing" in item for item in missing_errors)

    stale_plan = dict(plan)
    stale_plan["source_drawing"] = os.path.abspath(stale)
    stale_errors = R._mode_b_source_drawing_errors(stale_plan, current)
    assert any("source_drawing mismatch" in item for item in stale_errors)


def _write_minimal_plan(path, *, source_drawing=None):
    plan = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_status",
                "tool_args": {},
                "topology_changes": False,
            }
        ],
    }
    if source_drawing is not None:
        plan["source_drawing"] = source_drawing
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(plan, handle)


def _with_empty_mode_b_context(callback):
    original_context = R._drawing_modeling_context
    original_capability_errors = R.capability_plan_errors
    try:
        R._drawing_modeling_context = lambda path: ({}, [], [])
        R.capability_plan_errors = lambda plan, dispatches: []
        return callback()
    finally:
        R._drawing_modeling_context = original_context
        R.capability_plan_errors = original_capability_errors


def test_mode_b_build_and_check_accept_matching_source_drawing(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    drawing = os.path.join(directory, "current-drawing.json")
    frozen = os.path.join(directory, "matching-frozen.json")
    executable = os.path.join(directory, "matching-executable.json")
    _write_minimal_plan(frozen, source_drawing=os.path.abspath(drawing))

    def exercise():
        build_code, build_result = _capture_json_command(
            R._cmd_build,
            SimpleNamespace(plan=frozen, out=executable, drawing=drawing),
        )
        assert build_code == 0, build_result
        assert build_result["ok"] is True
        with open(executable, encoding="utf-8") as handle:
            built = json.load(handle)
        assert built["source_drawing"] == os.path.abspath(drawing)

        check_code, check_result = _capture_json_command(
            R._cmd_check,
            SimpleNamespace(plan=executable, frozen=False, drawing=drawing),
        )
        assert check_code == 0, check_result
        assert check_result["ok"] is True

    _with_empty_mode_b_context(exercise)


def test_mode_b_build_rejects_mismatched_source_drawing(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    current = os.path.join(directory, "current-drawing.json")
    stale = os.path.join(directory, "stale-drawing.json")
    frozen = os.path.join(directory, "mismatch-frozen.json")
    executable = os.path.join(directory, "mismatch-executable.json")
    _write_minimal_plan(frozen, source_drawing=os.path.abspath(stale))

    def exercise():
        build_code, build_result = _capture_json_command(
            R._cmd_build,
            SimpleNamespace(plan=frozen, out=executable, drawing=current),
        )
        assert build_code == 1
        assert build_result["ok"] is False
        assert build_result["built"] is None
        assert any(
            "source_drawing mismatch" in item
            for item in build_result["frozen_check_errors"]
        )
        assert not os.path.exists(executable)

    _with_empty_mode_b_context(exercise)


def test_mode_b_check_rejects_mismatched_source_drawing(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    current = os.path.join(directory, "current-drawing.json")
    stale = os.path.join(directory, "stale-drawing.json")
    executable = os.path.join(directory, "mismatch-check-executable.json")
    plan = {
        "mode": "FAST",
        "source_drawing": os.path.abspath(stale),
        "operations": [
            {
                "step": 1,
                "tool": "nx_status",
                "tool_args": {},
                "topology_changes": False,
            }
        ],
    }
    with open(executable, "w", encoding="utf-8") as handle:
        json.dump(R.build_executable_plan(plan), handle)

    def exercise():
        check_code, check_result = _capture_json_command(
            R._cmd_check,
            SimpleNamespace(plan=executable, frozen=False, drawing=current),
        )
        assert check_code == 1
        assert check_result["ok"] is False
        assert any(
            "source_drawing mismatch" in item for item in check_result["errors"]
        )

    _with_empty_mode_b_context(exercise)


def test_mode_b_build_and_check_require_source_drawing(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    drawing = os.path.join(directory, "current-drawing.json")
    frozen = os.path.join(directory, "missing-source-frozen.json")
    executable = os.path.join(directory, "missing-source-executable.json")
    _write_minimal_plan(frozen)

    def exercise():
        build_code, build_result = _capture_json_command(
            R._cmd_build,
            SimpleNamespace(plan=frozen, out=executable, drawing=drawing),
        )
        assert build_code == 1
        assert any(
            "missing source_drawing" in item
            for item in build_result["frozen_check_errors"]
        )

        with open(executable, "w", encoding="utf-8") as handle:
            plan = {
                "mode": "FAST",
                "operations": [
                    {
                        "step": 1,
                        "tool": "nx_status",
                        "tool_args": {},
                        "topology_changes": False,
                    }
                ],
            }
            json.dump(R.build_executable_plan(plan), handle)

        check_code, check_result = _capture_json_command(
            R._cmd_check,
            SimpleNamespace(plan=executable, frozen=False, drawing=drawing),
        )
        assert check_code == 1
        assert any("missing source_drawing" in item for item in check_result["errors"])

    _with_empty_mode_b_context(exercise)


def test_text_mode_build_and_check_allow_missing_source_drawing(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    frozen = os.path.join(directory, "text-frozen.json")
    executable = os.path.join(directory, "text-executable.json")
    _write_minimal_plan(frozen)

    build_code, build_result = _capture_json_command(
        R._cmd_build,
        SimpleNamespace(plan=frozen, out=executable, drawing=None),
    )
    assert build_code == 0, build_result
    assert build_result["ok"] is True

    check_code, check_result = _capture_json_command(
        R._cmd_check,
        SimpleNamespace(plan=executable, frozen=False, drawing=None),
    )
    assert check_code == 0, check_result
    assert check_result["ok"] is True


def test_plan_contracts_cli_fails_closed_on_drawing_context_error(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    drawing_path = os.path.join(directory, "drawing.json")
    with open(drawing_path, "w", encoding="utf-8") as handle:
        json.dump({}, handle)

    original = R._drawing_modeling_context
    try:
        R._drawing_modeling_context = lambda path: (
            {},
            [],
            ["dimension_closure is not closed"],
        )
        exit_code, result = _capture_json_command(
            R._cmd_plan_contracts,
            SimpleNamespace(drawing=drawing_path),
        )
    finally:
        R._drawing_modeling_context = original

    assert exit_code == 1
    assert result["ok"] is False
    assert result["contracts"] == []
    assert result["errors"] == ["dimension_closure is not closed"]


def _write_timing_drawing_fixture(directory):
    path = os.path.join(directory, "timing-drawing.json")
    drawing = {
        "overall_dimensions": {"length": 10, "width": 8, "height": 2},
        "coordinate_system": {"origin": "part_center_xy_bottom_z0"},
        "features": [
            {
                "id": "F_BASE",
                "type": "base_plate",
                "dimensions": {"length": 10, "width": 8, "thickness": 2},
                "count": 1,
                "required_for_modeling": True,
            }
        ],
        "source_ledger": [
            {"id": "S_OL", "semantic": "overall_dimension", "value": 10, "target": "overall_dimensions.length"},
            {"id": "S_OW", "semantic": "overall_dimension", "value": 8, "target": "overall_dimensions.width"},
            {"id": "S_OH", "semantic": "overall_dimension", "value": 2, "target": "overall_dimensions.height"},
            {"id": "S_KIND", "semantic": "feature_kind", "value": "base_plate", "target": "feature:F_BASE.type"},
            {"id": "S_L", "semantic": "feature_dimension", "value": 10, "target": "feature:F_BASE.dimensions.length"},
            {"id": "S_W", "semantic": "feature_dimension", "value": 8, "target": "feature:F_BASE.dimensions.width"},
            {"id": "S_T", "semantic": "thickness", "value": 2, "target": "feature:F_BASE.dimensions.thickness"},
            {"id": "S_N", "semantic": "feature_count", "value": 1, "target": "feature:F_BASE.count"},
        ],
        "derived": [],
        "unresolved": [],
        "dimension_conflicts": [],
        "dimension_closure": {"status": "closed"},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(drawing, handle)
    return path


def test_validate_build_check_return_independent_timing(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    drawing = _write_timing_drawing_fixture(directory)
    for _ in range(2):
        exit_code, result = _capture_json_command(R._cmd_validate_drawing, SimpleNamespace(drawing=drawing))
        assert exit_code == 0
        assert result["timing"]["stage"] == "A4_VALIDATE"
        assert result["timing"]["elapsed_ms"] is None or result["timing"]["elapsed_ms"] >= 0
        assert result["timing"]["input_file"]["file_mtime_utc"] is not None
        assert result["timing"]["input_file"]["first_write_reliable"] is False

    executable = os.path.join(directory, "timing-executable.json")
    build_code, build_result = _capture_json_command(R._cmd_build, SimpleNamespace(plan=FROZEN_PLAN, out=executable))
    assert build_code == 0
    assert build_result["timing"]["stage"] == "B3_BUILD"
    assert build_result["timing"]["input_file"]["first_write_reliable"] is False

    check_code, check_result = _capture_json_command(R._cmd_check, SimpleNamespace(plan=executable, frozen=False))
    assert check_code == 0
    assert check_result["timing"]["stage"] == "B3_CHECK"
    assert check_result["timing"]["input_file"]["first_write_reliable"] is False


def test_timing_failure_does_not_change_validate_result(tmp_path=None):
    import tempfile
    from types import SimpleNamespace

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    drawing = _write_timing_drawing_fixture(directory)
    original = R.time.perf_counter_ns
    try:
        R.time.perf_counter_ns = lambda: (_ for _ in ()).throw(RuntimeError("clock failed"))
        exit_code, result = _capture_json_command(R._cmd_validate_drawing, SimpleNamespace(drawing=drawing))
    finally:
        R.time.perf_counter_ns = original
    assert exit_code == 0
    assert result["ok"] is True
    assert result["timing"]["elapsed_ms"] is None


def test_runner_timing_boundaries_are_operation_events(tmp_path=None):
    import asyncio
    import tempfile

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    step_path = os.path.join(directory, "timing.step")

    class Transport:
        def resolve_path(self, path):
            return path

        async def call(self, tool, args):
            if tool == "nx_export_step":
                with open(args["path"], "wb") as handle:
                    handle.write(b"STEP")
                return {"status": "success", "path": args["path"]}
            return {"status": "success"}

    plan = {"mode": "FAST", "operations": [
        {"step": 1, "tool": "nx_extrude", "tool_args": {"sketch_id": "S1", "distance": 1}, "topology_changes": True},
        {"step": 2, "tool": "nx_export_step", "tool_args": {"path": step_path}, "topology_changes": False},
    ]}
    state = R._begin_command_timing("C_RUNNER")
    state["c2_modeling_complete_utc"] = None
    state["c3_export_complete_utc"] = None
    report = asyncio.run(R.run_plan(plan, Transport(), timing_state=state))
    assert report["status"] == "success"
    assert state["c2_modeling_complete_utc"] is not None
    assert state["c3_export_complete_utc"] is not None

    failed_state = R._begin_command_timing("C_RUNNER")
    failed_state["c2_modeling_complete_utc"] = None
    failed_state["c3_export_complete_utc"] = None

    class FailingTransport(Transport):
        async def call(self, tool, args):
            raise R.PlanError("synthetic failure")

    report = asyncio.run(R.run_plan(plan, FailingTransport(), timing_state=failed_state))
    assert report["status"] == "failed"
    assert failed_state["c2_modeling_complete_utc"] is None
    assert failed_state["c3_export_complete_utc"] is None

def test_load_plan_accepts_utf8_bom_from_powershell_51(tmp_path=None):
    import tempfile

    directory = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp()
    path = os.path.join(directory, "powershell51-plan.json")
    payload = {
        "mode": "FAST",
        "operations": [
            {
                "step": 1,
                "tool": "nx_create_part",
                "tool_args": {"path": "bom-smoke.prt", "units": "mm"},
                "topology_changes": False,
            }
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    with open(path, "wb") as handle:
        handle.write(b"\xef\xbb\xbf" + raw)

    loaded = R._load_plan(path)

    assert loaded == payload


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def _run_all():
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
