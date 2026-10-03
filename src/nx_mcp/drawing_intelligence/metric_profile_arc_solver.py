from __future__ import annotations

import math
from typing import Any


_AXES = {"X", "Y", "Z"}
_DIRECTIONS = {"negative", "positive"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _boundary_contract(
    boundary: dict[str, Any],
    axes: tuple[str, str],
) -> dict[str, Any] | None:
    axis = str(boundary.get("axis") or "").upper()
    if axis not in axes:
        return None
    varying_axis = axes[1] if axis == axes[0] else axes[0]
    value = _number(boundary.get("value"))
    span = boundary.get("span")
    material_direction = boundary.get("material_axis_direction")
    if (
        value is None
        or not isinstance(span, (list, tuple))
        or len(span) != 2
        or material_direction not in _DIRECTIONS
    ):
        return None
    lower = _number(span[0])
    upper = _number(span[1])
    if lower is None or upper is None:
        return None
    lower, upper = sorted((lower, upper))
    if upper - lower <= 1e-12:
        return None
    target = boundary.get("target")
    return {
        "axis": axis,
        "varying_axis": varying_axis,
        "value": value,
        "span": (lower, upper),
        "material_axis_direction": str(material_direction),
        "target": target if isinstance(target, str) and target else None,
    }


def solve_orthogonal_tangent_arc(
    *,
    axes: tuple[str, str],
    first_boundary: dict[str, Any],
    second_boundary: dict[str, Any],
    radius: float,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Solve one engineering fillet arc tangent to two finite orthogonal edges.

    Every metric coordinate comes from the supplied engineering boundary
    coordinates/spans and the explicit engineering radius.  No raster position,
    pixel radius, or fitted pixel center participates in the solution.

    Four circle centers are mathematically tangent to two infinite orthogonal
    lines.  This solver keeps only candidates whose two tangent points lie on
    the finite engineering boundary segments.  Exactly one candidate is
    required; zero or multiple candidates remain unresolved.
    """

    normalized_axes = tuple(str(axis).upper() for axis in axes)
    if (
        len(normalized_axes) != 2
        or normalized_axes[0] == normalized_axes[1]
        or any(axis not in _AXES for axis in normalized_axes)
    ):
        return {
            "status": "unresolved",
            "reason": "invalid_profile_plane_axes",
            "candidate_count": 0,
        }

    radius_value = _number(radius)
    if radius_value is None or radius_value <= 0.0:
        return {
            "status": "unresolved",
            "reason": "invalid_engineering_radius",
            "candidate_count": 0,
        }

    first = _boundary_contract(first_boundary, normalized_axes)
    second = _boundary_contract(second_boundary, normalized_axes)
    if first is None or second is None:
        return {
            "status": "unresolved",
            "reason": "incomplete_engineering_boundary_contract",
            "candidate_count": 0,
        }
    if first["axis"] == second["axis"]:
        return {
            "status": "unresolved",
            "reason": "supporting_boundaries_are_not_orthogonal",
            "candidate_count": 0,
        }

    by_axis = {
        first["axis"]: first,
        second["axis"]: second,
    }
    if set(by_axis) != set(normalized_axes):
        return {
            "status": "unresolved",
            "reason": "supporting_boundaries_do_not_span_profile_plane",
            "candidate_count": 0,
        }

    intersection = {
        normalized_axes[0]: float(by_axis[normalized_axes[0]]["value"]),
        normalized_axes[1]: float(by_axis[normalized_axes[1]]["value"]),
    }

    candidates: list[dict[str, Any]] = []
    for first_sign in (-1.0, 1.0):
        for second_sign in (-1.0, 1.0):
            center = {
                normalized_axes[0]: (
                    intersection[normalized_axes[0]]
                    + first_sign * radius_value
                ),
                normalized_axes[1]: (
                    intersection[normalized_axes[1]]
                    + second_sign * radius_value
                ),
            }
            tangent_points: dict[str, dict[str, float]] = {}
            valid = True
            for axis in normalized_axes:
                boundary = by_axis[axis]
                varying_axis = str(boundary["varying_axis"])
                tangent = {
                    axis: float(boundary["value"]),
                    varying_axis: float(center[varying_axis]),
                }
                lower, upper = boundary["span"]
                varying_value = tangent[varying_axis]
                if not (
                    float(lower) - tolerance
                    <= varying_value
                    <= float(upper) + tolerance
                ):
                    valid = False
                    break
                tangent_points[axis] = tangent
            if not valid:
                continue

            candidates.append(
                {
                    "center": center,
                    "tangent_points": tangent_points,
                    "center_offsets": {
                        normalized_axes[0]: int(first_sign),
                        normalized_axes[1]: int(second_sign),
                    },
                }
            )

    if len(candidates) != 1:
        return {
            "status": "unresolved",
            "reason": (
                "no_unique_engineering_arc_center"
                if candidates
                else "engineering_radius_does_not_fit_supporting_segments"
            ),
            "candidate_count": len(candidates),
            "intersection": intersection,
            "engineering_coordinate_inferred_from_pixels": False,
        }

    solution = candidates[0]
    return {
        "status": "resolved",
        "basis": (
            "explicit_engineering_radius_plus_finite_orthogonal_"
            "engineering_boundary_segments"
        ),
        "axes": list(normalized_axes),
        "radius": radius_value,
        "intersection": intersection,
        "center": solution["center"],
        "tangent_points": solution["tangent_points"],
        "center_offsets": solution["center_offsets"],
        "supporting_targets": [
            target
            for target in (
                by_axis[normalized_axes[0]].get("target"),
                by_axis[normalized_axes[1]].get("target"),
            )
            if isinstance(target, str) and target
        ],
        "material_axis_directions": {
            axis: by_axis[axis]["material_axis_direction"]
            for axis in normalized_axes
        },
        "candidate_count": 1,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }
