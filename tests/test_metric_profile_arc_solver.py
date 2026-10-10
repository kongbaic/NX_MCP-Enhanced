from __future__ import annotations

import math

from nx_mcp.drawing_intelligence.metric_profile_arc_solver import (
    solve_orthogonal_tangent_arc,
    solve_tangent_arc_between_segments,
)


def _boundary(axis, value, span, direction):
    return {
        "axis": axis,
        "value": value,
        "span": span,
        "material_axis_direction": direction,
        "target": f"feature:F_{axis}.boundary.{axis.lower()}",
    }


def test_convex_corner_arc_is_solved_from_engineering_segments():
    result = solve_orthogonal_tangent_arc(
        axes=("X", "Z"),
        first_boundary=_boundary("X", 100.0, [0.0, 60.0], "negative"),
        second_boundary=_boundary("Z", 60.0, [0.0, 100.0], "negative"),
        radius=5.0,
    )

    assert result["status"] == "resolved"
    assert result["center"] == {"X": 95.0, "Z": 55.0}
    assert result["tangent_points"] == {
        "X": {"X": 100.0, "Z": 55.0},
        "Z": {"Z": 60.0, "X": 95.0},
    }
    assert result["candidate_count"] == 1
    assert result["engineering_coordinate_inferred_from_pixels"] is False


def test_concave_corner_arc_is_solved_without_convex_part_special_case():
    result = solve_orthogonal_tangent_arc(
        axes=("X", "Z"),
        first_boundary=_boundary("X", 40.0, [30.0, 80.0], "negative"),
        second_boundary=_boundary("Z", 30.0, [40.0, 90.0], "negative"),
        radius=6.0,
    )

    assert result["status"] == "resolved"
    assert result["center"] == {"X": 46.0, "Z": 36.0}
    assert result["tangent_points"] == {
        "X": {"X": 40.0, "Z": 36.0},
        "Z": {"Z": 30.0, "X": 46.0},
    }


def test_bidirectional_support_segments_fail_closed_when_center_is_not_unique():
    result = solve_orthogonal_tangent_arc(
        axes=("X", "Z"),
        first_boundary=_boundary("X", 50.0, [0.0, 100.0], "negative"),
        second_boundary=_boundary("Z", 50.0, [0.0, 100.0], "positive"),
        radius=5.0,
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "no_unique_engineering_arc_center"
    assert result["candidate_count"] == 4


def test_radius_that_exceeds_both_finite_supports_is_blocked():
    result = solve_orthogonal_tangent_arc(
        axes=("X", "Z"),
        first_boundary=_boundary("X", 100.0, [50.0, 60.0], "negative"),
        second_boundary=_boundary("Z", 60.0, [90.0, 100.0], "negative"),
        radius=20.0,
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == (
        "engineering_radius_does_not_fit_supporting_segments"
    )
    assert result["candidate_count"] == 0


def test_missing_material_direction_fails_closed_before_geometry_solution():
    first = _boundary("X", 100.0, [0.0, 60.0], "negative")
    first.pop("material_axis_direction")

    result = solve_orthogonal_tangent_arc(
        axes=("X", "Z"),
        first_boundary=first,
        second_boundary=_boundary("Z", 60.0, [0.0, 100.0], "negative"),
        radius=5.0,
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "incomplete_engineering_boundary_contract"
    assert result["candidate_count"] == 0


def test_solver_supports_other_principal_profile_planes():
    result = solve_orthogonal_tangent_arc(
        axes=("Y", "Z"),
        first_boundary=_boundary("Y", 32.0, [0.0, 66.0], "negative"),
        second_boundary=_boundary("Z", 66.0, [0.0, 32.0], "negative"),
        radius=4.0,
    )

    assert result["status"] == "resolved"
    assert result["center"] == {"Y": 28.0, "Z": 62.0}



def _segment(start, end):
    return {
        "type": "line",
        "start": {"X": float(start[0]), "Z": float(start[1])},
        "end": {"X": float(end[0]), "Z": float(end[1])},
    }


def test_adjacent_nonorthogonal_fillet_uses_only_engineering_segments_and_radius():
    result = solve_tangent_arc_between_segments(
        axes=("X", "Z"),
        first_segment=_segment((10.0, 0.0), (0.0, 0.0)),
        second_segment=_segment((0.0, 0.0), (-4.0, 12.0)),
        radius=2.0,
    )

    assert result["status"] == "resolved"
    assert result["engineering_coordinate_inferred_from_pixels"] is False
    assert result["pixel_geometry_used_for_identity_only"] is False
    assert math.isclose(result["center"]["X"], 1.4415184401, abs_tol=1e-9)
    assert math.isclose(result["center"]["Z"], 2.0, abs_tol=1e-9)
    assert math.isclose(
        result["first_tangent"]["X"],
        1.4415184401,
        abs_tol=1e-9,
    )
    assert math.isclose(result["first_tangent"]["Z"], 0.0, abs_tol=1e-9)
    assert math.isclose(
        result["second_tangent"]["X"],
        -0.4558481560,
        abs_tol=1e-9,
    )
    assert math.isclose(
        result["second_tangent"]["Z"],
        1.3675444680,
        abs_tol=1e-9,
    )
    assert result["traversal_sweep_deg"] < 0.0
    assert math.isclose(
        result["minor_sweep_deg"],
        71.5650511771,
        abs_tol=1e-9,
    )


def test_adjacent_nonorthogonal_fillet_becomes_positive_after_cycle_reversal():
    result = solve_tangent_arc_between_segments(
        axes=("X", "Z"),
        first_segment=_segment((-4.0, 12.0), (0.0, 0.0)),
        second_segment=_segment((0.0, 0.0), (10.0, 0.0)),
        radius=2.0,
    )

    assert result["status"] == "resolved"
    assert result["traversal_sweep_deg"] > 0.0
    assert math.isclose(
        result["traversal_sweep_deg"],
        71.5650511771,
        abs_tol=1e-9,
    )


def test_adjacent_nonorthogonal_fillet_fails_closed_when_radius_consumes_neighbor():
    result = solve_tangent_arc_between_segments(
        axes=("X", "Z"),
        first_segment=_segment((2.0, 0.0), (0.0, 0.0)),
        second_segment=_segment((0.0, 0.0), (-1.0, 3.0)),
        radius=10.0,
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "engineering_radius_does_not_fit_adjacent_segments"
