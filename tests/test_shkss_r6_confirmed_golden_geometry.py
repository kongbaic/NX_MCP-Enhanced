"""SHKSS R6 historical *confirmed-canonical* golden contract (not Fresh OCR).

Evidence: 2026-09-28 R6 real-NX report, 39/39 operations, one solid body;
historical corrected plan-contracts with split M6 material/entry semantics.
No original-raster SHA/zero-human Gate A PASS is asserted here. These are
off-line, model-capability regressions, NOT permission to inject goldens into
the production Reader, Adapter, or Gate A. Keep the input-provenance tiers apart.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "agent" / "nx-mcp-plan-runner" / "runner.py"
SPEC = importlib.util.spec_from_file_location("shkss_r6_golden_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)

# These values are *test expectations* from the corrected R6 plan contracts.
# Never load them as asserted observations in a fresh production image replay.
R6_DIMS = {"length_x": 40.0, "width_y": 32.0, "height_z": 66.0}
SLOT = "F_1F5E0912CCE2E33E"
MAIN_BORE = "F_56FFD46336D8385C"
THREAD = "F_5970300AA4931F50"
COUNTERBORE = "F_5F09A95EB16298BA"
BOTTOM_PAIR = "F_A0EDF90B9A2044C5"


def _r6_profile() -> dict:
    points = [
        (-16.0, 0.0),
        (16.0, 0.0),
        (16.0, 66.0),
        (0.0, 66.0),
        (0.0, 8.0),
        (-16.0, 8.0),
    ]
    return {
        "plane": "YZ",
        "topology": "L",
        "segments": [
            {"type": "line", "y1": y1, "z1": z1, "y2": y2, "z2": z2}
            for (y1, z1), (y2, z2) in zip(points, points[1:] + points[:1])
        ],
    }


def _r6_drawing(*included: str) -> dict:
    # Isolate dependent capabilities: the same coaxial through-hole and M6
    # surrogate must not be double-counted as competing material subtraction.
    features = {
        "slot": {
            "id": SLOT, "type": "slot", "width": 2.0, "width_axis": "X",
            "through_axis": "Y", "centerline": {"x": 0.0},
            "bottom_z": 50.0, "top_z": 66.0,
        },
        "main": {
            "id": MAIN_BORE, "type": "hole", "axis": "Y", "diameter": 20.0,
            "through": True, "centerline": {"x": 0.0, "z": 40.0},
        },
        "thread": {
            "id": THREAD, "type": "threaded_hole", "axis": "X", "thread_spec": "M6",
            "thread_depth": 12.0, "centerline": {"y": 8.0, "z": 58.0},
            "material_side": "min", "entry_endpoint": "max",
        },
        "counterbore": {
            "id": COUNTERBORE, "type": "counterbore_hole", "axis": "X",
            "diameter": 6.6, "counterbore_diameter": 11.0,
            "counterbore_depth": 6.5, "through": True, "start_side": "max",
            "centerline": {"y": 8.0, "z": 58.0},
        },
        "bottom": {
            "id": BOTTOM_PAIR, "type": "hole", "axis": "Z", "diameter": 6.6,
            "through": True, "count": 2,
            "explicit_centers": [[-12.0, -8.0], [12.0, -8.0]],
        },
    }
    return {
        "overall_dimensions": dict(R6_DIMS),
        "profile": _r6_profile(),
        "features": [features[key] for key in included],
    }


def test_confirmed_r6_golden_metric_geometry_all_four_capabilities():
    # The R6 geometry is assembled from independent engineering truths;
    # pixels are never consulted and no OCR confidence is overridden.
    y_holes, errors = R.resolve_hole_drawing_geometries(
        _r6_drawing("slot", "main"), axes={"Y"}
    )
    assert errors == []
    assert [(x["feature_id"], x["axis"], x["diameter"], x["axial_range"])
            for x in y_holes] == [(MAIN_BORE, "Y", 20.0, [0.0, 16.0])]

    z_holes, errors = R.resolve_hole_drawing_geometries(
        _r6_drawing("bottom"), axes={"Z"}
    )
    assert errors == []
    assert len(z_holes) == 1
    assert z_holes[0] == {
        "feature_id": BOTTOM_PAIR, "axis": "Z",
        "transverse_centers": [[-12.0, -8.0], [12.0, -8.0]],
        "diameter": 6.6, "axial_range": [0.0, 8.0], "count": 2,
    }

    threads, errors = R.resolve_thread_drawing_geometries(
        _r6_drawing("slot", "thread"), axes={"X"}
    )
    assert errors == []
    assert len(threads) == 1
    assert threads[0]["feature_id"] == THREAD
    assert threads[0]["transverse_centers"] == [[8.0, 58.0]]
    assert threads[0]["axial_range"] == [-1.0, -13.0]
    assert threads[0]["material_side"] == "min"
    assert threads[0]["entry_endpoint"] == "max"

    recesses, errors = R.resolve_transverse_recess_drawing_geometries(
        _r6_drawing("slot", "counterbore"), axes={"X"}
    )
    assert errors == []
    assert len(recesses) == 1
    assert recesses[0]["feature_id"] == COUNTERBORE
    assert recesses[0]["material_intervals"] == [[-20.0, -1.0], [1.0, 20.0]]
    assert recesses[0]["through_axial_range"] == [20.0, 1.0]
    assert recesses[0]["counterbore_axial_range"] == [20.0, 13.5]


def test_confirmed_r6_golden_principal_hole_slot_remains_one_continuous_cut():
    drawing = _r6_drawing("slot", "main")
    capability = R.resolve_modeling_capabilities("hole", "Y")[0][0]
    payload, errors = R.dispatch_planner_adapter(capability, drawing)
    assert errors == []
    assert payload is not None
    geometries = payload["geometries"]
    assert len(geometries) == 1
    assert geometries[0]["representation"] == "continuous_hole_slot_profile"
    assert geometries[0]["composed_feature_ids"] == [MAIN_BORE, SLOT]
    operations = payload["operation_contracts"][0]["operations"]
    assert sum(op["tool"] == "nx_extrude" for op in operations) == 1
    assert operations[-1]["fixed_args"]["operation"] == "subtract"


def test_confirmed_r6_golden_refuses_unproven_thread_entry():
    # No reverse-injection of historical manual start_side into Fresh.
    drawing = _r6_drawing("slot", "thread")
    feature = drawing["features"][-1]
    feature.pop("material_side")
    feature.pop("entry_endpoint")
    geometries, errors = R.resolve_thread_drawing_geometries(drawing, axes={"X"})
    assert geometries == []
    assert any("no complete machining-entry semantics" in e for e in errors)

    # Even explicit split-side labels cannot fabricate two material intervals.
    drawing = _r6_drawing("thread")
    geometries, errors = R.resolve_thread_drawing_geometries(drawing, axes={"X"})
    assert geometries == []
    assert any("canonical material is not interrupted" in e for e in errors)
