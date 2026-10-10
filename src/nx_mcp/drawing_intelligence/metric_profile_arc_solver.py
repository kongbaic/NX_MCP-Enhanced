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



def _segment_contract(
    segment: dict[str, Any],
    axes: tuple[str, str],
) -> dict[str, dict[str, float]] | None:
    start = segment.get("start")
    end = segment.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        return None
    normalized: dict[str, dict[str, float]] = {"start": {}, "end": {}}
    for key, point in (("start", start), ("end", end)):
        for axis in axes:
            value = _number(point.get(axis))
            if value is None:
                return None
            normalized[key][axis] = value
    return normalized


def solve_tangent_arc_between_segments(
    *,
    axes: tuple[str, str],
    first_segment: dict[str, Any],
    second_segment: dict[str, Any],
    radius: float,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Solve a fillet tangent to two finite adjacent engineering line segments.

    The two segments must meet at first.end == second.start. Tangency is solved
    entirely from those resolved engineering coordinates and the explicit
    engineering radius. Raster positions, fitted pixel centers, and pixel radii
    never participate.

    The returned signed traversal sweep is positive for counter-clockwise
    traversal from the first segment into the second and negative for clockwise
    traversal. Callers that can emit only positive NX sketch-arc sweeps may
    reverse the closed profile cycle and solve again; the geometric fillet is
    unchanged.
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
        }

    radius_value = _number(radius)
    if radius_value is None or radius_value <= 0.0:
        return {
            "status": "unresolved",
            "reason": "invalid_engineering_radius",
        }

    first = _segment_contract(first_segment, normalized_axes)
    second = _segment_contract(second_segment, normalized_axes)
    if first is None or second is None:
        return {
            "status": "unresolved",
            "reason": "incomplete_engineering_segment_contract",
        }

    corner = first["end"]
    if any(
        abs(float(corner[axis]) - float(second["start"][axis])) > tolerance
        for axis in normalized_axes
    ):
        return {
            "status": "unresolved",
            "reason": "engineering_segments_are_not_adjacent",
        }

    first_vector = [
        float(first["start"][axis]) - float(corner[axis])
        for axis in normalized_axes
    ]
    second_vector = [
        float(second["end"][axis]) - float(corner[axis])
        for axis in normalized_axes
    ]
    first_length = math.hypot(*first_vector)
    second_length = math.hypot(*second_vector)
    if first_length <= tolerance or second_length <= tolerance:
        return {
            "status": "unresolved",
            "reason": "zero_length_engineering_segment",
        }

    first_unit = [value / first_length for value in first_vector]
    second_unit = [value / second_length for value in second_vector]
    dot = max(
        -1.0,
        min(
            1.0,
            first_unit[0] * second_unit[0]
            + first_unit[1] * second_unit[1],
        ),
    )
    angle = math.acos(dot)
    half_angle = angle / 2.0
    sin_half = math.sin(half_angle)
    tan_half = math.tan(half_angle)
    if (
        angle <= tolerance
        or abs(math.pi - angle) <= tolerance
        or sin_half <= tolerance
        or abs(tan_half) <= tolerance
    ):
        return {
            "status": "unresolved",
            "reason": "engineering_segments_are_collinear_or_degenerate",
        }

    tangent_distance = radius_value / tan_half
    if (
        tangent_distance <= tolerance
        or tangent_distance >= first_length - tolerance
        or tangent_distance >= second_length - tolerance
    ):
        return {
            "status": "unresolved",
            "reason": "engineering_radius_does_not_fit_adjacent_segments",
        }

    bisector = [
        first_unit[0] + second_unit[0],
        first_unit[1] + second_unit[1],
    ]
    bisector_length = math.hypot(*bisector)
    if bisector_length <= tolerance:
        return {
            "status": "unresolved",
            "reason": "engineering_corner_has_no_unique_internal_bisector",
        }
    bisector_unit = [value / bisector_length for value in bisector]
    center_distance = radius_value / sin_half

    center = {
        axis: float(corner[axis]) + bisector_unit[index] * center_distance
        for index, axis in enumerate(normalized_axes)
    }
    first_tangent = {
        axis: float(corner[axis]) + first_unit[index] * tangent_distance
        for index, axis in enumerate(normalized_axes)
    }
    second_tangent = {
        axis: float(corner[axis]) + second_unit[index] * tangent_distance
        for index, axis in enumerate(normalized_axes)
    }

    def angle_degrees(point: dict[str, float]) -> float:
        raw = math.degrees(
            math.atan2(
                float(point[normalized_axes[1]])
                - float(center[normalized_axes[1]]),
                float(point[normalized_axes[0]])
                - float(center[normalized_axes[0]]),
            )
        )
        return raw % 360.0

    start_angle = angle_degrees(first_tangent)
    second_angle = angle_degrees(second_tangent)
    ccw_sweep = (second_angle - start_angle) % 360.0
    if ccw_sweep <= tolerance or 360.0 - ccw_sweep <= tolerance:
        return {
            "status": "unresolved",
            "reason": "engineering_fillet_has_degenerate_sweep",
        }
    traversal_sweep = (
        ccw_sweep
        if ccw_sweep <= 180.0
        else ccw_sweep - 360.0
    )
    if abs(traversal_sweep) >= 180.0 - tolerance:
        return {
            "status": "unresolved",
            "reason": "engineering_fillet_minor_sweep_is_not_unique",
        }

    return {
        "status": "resolved",
        "basis": (
            "explicit_engineering_radius_plus_two_finite_adjacent_"
            "engineering_segments"
        ),
        "axes": list(normalized_axes),
        "radius": radius_value,
        "corner": dict(corner),
        "center": center,
        "first_tangent": first_tangent,
        "second_tangent": second_tangent,
        "tangent_distance": tangent_distance,
        "traversal_sweep_deg": traversal_sweep,
        "minor_sweep_deg": abs(traversal_sweep),
        "start_angle_deg": start_angle,
        "second_angle_deg": second_angle,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": False,
    }
