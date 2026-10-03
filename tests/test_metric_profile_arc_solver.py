from __future__ import annotations

from nx_mcp.drawing_intelligence.metric_profile_arc_solver import (
    solve_orthogonal_tangent_arc,
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
