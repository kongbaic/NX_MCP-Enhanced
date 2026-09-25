from __future__ import annotations

import pytest
from pydantic import ValidationError

from nx_mcp.drawing_intelligence.metric_profile_solver import (
    MetricProfileSpec,
    solve_metric_profile,
)


def test_l_profile_max_side_solves_shkss_body_without_pixel_metric() -> None:
    solution = solve_metric_profile(
        MetricProfileSpec(
            plane="YZ",
            overall_u=32,
            overall_v=66,
            upright_width=16,
            base_height=8,
            upright_side="max",
            coordinate_mode="overall_min",
        )
    )

    assert solution.vertices == [
        {"y": 0.0, "z": 0.0},
        {"y": 32.0, "z": 0.0},
        {"y": 32.0, "z": 66.0},
        {"y": 16.0, "z": 66.0},
        {"y": 16.0, "z": 8.0},
        {"y": 0.0, "z": 8.0},
    ]
    assert len(solution.segments) == 6
    assert solution.segments[-1] == {
        "type": "line",
        "y1": 0.0,
        "z1": 8.0,
        "y2": 0.0,
        "z2": 0.0,
    }
    assert solution.engineering_coordinate_inferred_from_pixels is False


def test_l_profile_can_emit_planner_centered_u_coordinates() -> None:
    solution = solve_metric_profile(
        MetricProfileSpec(
            plane="YZ",
            overall_u=32,
            overall_v=66,
            upright_width=16,
            base_height=8,
            upright_side="max",
            coordinate_mode="centered_u_bottom_v",
        )
    )

    assert solution.vertices == [
        {"y": -16.0, "z": 0.0},
        {"y": 16.0, "z": 0.0},
        {"y": 16.0, "z": 66.0},
        {"y": 0.0, "z": 66.0},
        {"y": 0.0, "z": 8.0},
        {"y": -16.0, "z": 8.0},
    ]


def test_l_profile_supports_min_side_without_special_case_coordinates() -> None:
    solution = solve_metric_profile(
        MetricProfileSpec(
            plane="YZ",
            overall_u=30,
            overall_v=50,
            upright_width=10,
            base_height=5,
            upright_side="min",
        )
    )

    assert solution.vertices == [
        {"y": 0.0, "z": 0.0},
        {"y": 30.0, "z": 0.0},
        {"y": 30.0, "z": 5.0},
        {"y": 10.0, "z": 5.0},
        {"y": 10.0, "z": 50.0},
        {"y": 0.0, "z": 50.0},
    ]


@pytest.mark.parametrize(
    ("upright_width", "base_height"),
    [(32, 8), (16, 66), (40, 80)],
)
def test_invalid_l_profile_constraints_fail_closed(
    upright_width: float,
    base_height: float,
) -> None:
    with pytest.raises(ValidationError):
        MetricProfileSpec(
            plane="YZ",
            overall_u=32,
            overall_v=66,
            upright_width=upright_width,
            base_height=base_height,
            upright_side="max",
        )
