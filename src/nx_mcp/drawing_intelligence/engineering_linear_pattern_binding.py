from __future__ import annotations

import math
from typing import Any


_AXIS_BY_VIEW_ORIENTATION: dict[tuple[str, str], str] = {
    ("front", "horizontal"): "X",
    ("front", "vertical"): "Z",
    ("side", "horizontal"): "Y",
    ("side", "vertical"): "Z",
    ("top", "horizontal"): "X",
    ("top", "vertical"): "Y",
}


def _bbox_bounds(
    bbox: Any,
) -> tuple[float, float, float, float] | None:
    if not (
        isinstance(bbox, list)
        and len(bbox) >= 4
        and all(
            isinstance(point, list)
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
            for point in bbox
        )
    ):
        return None
    xs = [float(point[0]) for point in bbox]
    ys = [float(point[1]) for point in bbox]
    return min(xs), min(ys), max(xs), max(ys)


def _point_to_rect_distance(
    point: tuple[float, float],
    bounds: tuple[float, float, float, float],
) -> float:
    x, y = point
    left, top, right, bottom = bounds
    return math.hypot(
        max(left - x, 0.0, x - right),
        max(top - y, 0.0, y - bottom),
    )


def _line_pair(
    line: dict[str, Any],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    endpoints = line.get("endpoints_px")
    if not (
        isinstance(endpoints, list)
        and len(endpoints) == 2
        and all(
            isinstance(point, list)
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
            for point in endpoints
        )
    ):
        return None
    return (
        (float(endpoints[0][0]), float(endpoints[0][1])),
        (float(endpoints[1][0]), float(endpoints[1][1])),
    )


def _line_angle(
    line: dict[str, Any],
    pair: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    angle = line.get("angle_deg")
    if isinstance(angle, (int, float)):
        return float(angle)
    (x1, y1), (x2, y2) = pair
    raw = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180.0
    return 180.0 - raw if raw > 90.0 else raw


def _point_to_pattern_distance(
    point: tuple[float, float],
    pattern: dict[str, Any],
) -> float | None:
    orientation = str(pattern.get("orientation") or "")
    axis = pattern.get("axis_px")
    span = pattern.get("span_px")
    if not (
        orientation in {"horizontal", "vertical"}
        and isinstance(axis, (int, float))
        and isinstance(span, list)
        and len(span) == 2
        and all(isinstance(value, (int, float)) for value in span)
    ):
        return None

    x, y = point
    start, end = sorted(float(value) for value in span)
    axis_f = float(axis)
    if orientation == "horizontal":
        return math.hypot(
            max(start - x, 0.0, x - end),
            abs(y - axis_f),
        )
    return math.hypot(
        abs(x - axis_f),
        max(start - y, 0.0, y - end),
    )


def bind_callout_to_linear_pattern(
    callout_bbox: Any,
    annotation_lines: Any,
    region: dict[str, Any],
    *,
    view_kind: str,
) -> dict[str, Any]:
    """Bind one callout leader to one dashed/centerline pattern candidate.

    The path is deliberately narrow: an oblique leader must touch the text,
    point away from it, and terminate close to one unique pattern with a clear
    distance margin.  No engineering coordinate is inferred from pixels.
    """

    bounds = _bbox_bounds(callout_bbox)
    if bounds is None:
        return {"status": "unresolved", "reason": "callout_bbox_invalid"}
    if not isinstance(annotation_lines, list):
        return {"status": "unresolved", "reason": "annotation_geometry_unavailable"}

    patterns = region.get("linear_pattern_candidates", [])
    if not isinstance(patterns, list) or not patterns:
        return {"status": "unresolved", "reason": "linear_pattern_geometry_unavailable"}

    text_height = max(1.0, bounds[3] - bounds[1])
    touch_tolerance = max(5.0, text_height * 0.30)
    target_tolerance = max(5.0, text_height * 0.18)
    minimum_margin = max(3.0, text_height * 0.08)
    minimum_leader_length = max(18.0, text_height * 0.55)

    matches: list[dict[str, Any]] = []
    for line_index, line in enumerate(annotation_lines):
        if not isinstance(line, dict):
            continue
        pair = _line_pair(line)
        if pair is None:
            continue
        angle = _line_angle(line, pair)
        if angle < 15.0 or angle > 75.0:
            continue
        leader_length = math.dist(pair[0], pair[1])
        if leader_length < minimum_leader_length:
            continue

        endpoint_distances = [
            _point_to_rect_distance(pair[0], bounds),
            _point_to_rect_distance(pair[1], bounds),
        ]
        for entry_index, text_distance in enumerate(endpoint_distances):
            if text_distance > touch_tolerance:
                continue
            exit_point = pair[1 - entry_index]
            if _point_to_rect_distance(exit_point, bounds) <= text_distance:
                continue

            for pattern_index, pattern in enumerate(patterns):
                if not isinstance(pattern, dict):
                    continue
                target_distance = _point_to_pattern_distance(exit_point, pattern)
                if target_distance is None or target_distance > target_tolerance:
                    continue
                orientation = str(pattern.get("orientation") or "")
                axis = _AXIS_BY_VIEW_ORIENTATION.get((view_kind, orientation))
                if axis is None:
                    continue

                matches.append(
                    {
                        "line_index": line_index,
                        "pattern_index": pattern_index,
                        "orientation": orientation,
                        "axis": axis,
                        "pattern_axis_px": float(pattern["axis_px"]),
                        "pattern_span_px": list(pattern["span_px"]),
                        "text_touch_distance_px": round(text_distance, 3),
                        "pattern_target_distance_px": round(target_distance, 3),
                        "geometry_endpoint_px": [
                            round(exit_point[0], 3),
                            round(exit_point[1], 3),
                        ],
                    }
                )

    matches.sort(
        key=lambda item: (
            float(item["pattern_target_distance_px"]),
            float(item["text_touch_distance_px"]),
            int(item["line_index"]),
            int(item["pattern_index"]),
        )
    )
    if not matches:
        return {
            "status": "unresolved",
            "reason": "no_leader_to_linear_pattern_match",
        }

    best = matches[0]
    if len(matches) > 1:
        second = matches[1]
        if (
            float(second["pattern_target_distance_px"])
            - float(best["pattern_target_distance_px"])
            < minimum_margin
        ):
            return {
                "status": "unresolved",
                "reason": "multiple_linear_pattern_targets_without_margin",
                "candidate_bindings": matches,
            }

    region_id = str(region.get("region_id") or "")
    if not region_id:
        return {"status": "unresolved", "reason": "region_id_missing"}

    return {
        "status": "bound",
        "basis": "callout_oblique_leader_to_unique_linear_pattern",
        "region_id": region_id,
        "entity_key": (
            f"{region_id}.LINEAR_PATTERN."
            f"{int(best['pattern_index']) + 1:03d}"
        ),
        **best,
    }
