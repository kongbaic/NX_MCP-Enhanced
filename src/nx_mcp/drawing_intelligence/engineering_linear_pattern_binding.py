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


def _angle_difference(left: float, right: float) -> float:
    delta = abs(left - right)
    return min(delta, 180.0 - delta)


def _strong_fragmented_pattern_support(pattern: dict[str, Any]) -> bool:
    segment_count = pattern.get("segment_count")
    gap_count = pattern.get("gap_count")
    dash_score = pattern.get("dash_score")
    return (
        isinstance(segment_count, int)
        and segment_count >= 3
        and isinstance(gap_count, int)
        and gap_count >= 2
        and isinstance(dash_score, (int, float))
        and not isinstance(dash_score, bool)
        and float(dash_score) >= 0.55
    )


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


def _ray_to_pattern_extension(
    entry_point: tuple[float, float],
    exit_point: tuple[float, float],
    pattern: dict[str, Any],
    *,
    max_extension: float,
    target_tolerance: float,
) -> float | None:
    dx = exit_point[0] - entry_point[0]
    dy = exit_point[1] - entry_point[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9 or max_extension <= 0:
        return None
    ux, uy = dx / length, dy / length

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

    start, end = sorted(float(value) for value in span)
    if orientation == "horizontal":
        if abs(uy) <= 1e-9:
            return None
        extension = (float(axis) - exit_point[1]) / uy
        cross = exit_point[0] + ux * extension
    else:
        if abs(ux) <= 1e-9:
            return None
        extension = (float(axis) - exit_point[0]) / ux
        cross = exit_point[1] + uy * extension

    if extension <= 1e-9 or extension > max_extension:
        return None
    if cross < start - target_tolerance or cross > end + target_tolerance:
        return None
    return float(extension)


def bind_callout_to_linear_pattern(
    callout_bbox: Any,
    annotation_lines: Any,
    region: dict[str, Any],
    *,
    view_kind: str,
    profile_inventory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind a callout leader to one dashed/centerline pattern candidate.

    Pixel geometry is used only for topology and identity. Fragmented oblique
    leader shafts may be chained when their direction and gaps are consistent.
    No engineering coordinate is inferred from pixels.
    """

    bounds = _bbox_bounds(callout_bbox)
    if bounds is None:
        return {"status": "unresolved", "reason": "callout_bbox_invalid"}
    if not isinstance(annotation_lines, list):
        return {"status": "unresolved", "reason": "annotation_geometry_unavailable"}

    patterns = region.get("linear_pattern_candidates", [])
    if not isinstance(patterns, list) or not patterns:
        return {"status": "unresolved", "reason": "linear_pattern_geometry_unavailable"}

    region_id = str(region.get("region_id") or "")
    profile_items = profile_inventory or []
    profile_axis_tolerance = 2.0

    def overlaps_structural_profile(pattern: dict[str, Any]) -> bool:
        orientation = str(pattern.get("orientation") or "")
        axis = pattern.get("axis_px")
        if orientation not in {"horizontal", "vertical"} or not isinstance(
            axis,
            (int, float),
        ):
            return False
        return any(
            isinstance(item, dict)
            and str(item.get("region_id") or "") == region_id
            and str(item.get("source_orientation") or "") == orientation
            and isinstance(item.get("position_px"), (int, float))
            and abs(float(item["position_px"]) - float(axis))
            <= profile_axis_tolerance
            for item in profile_items
        )

    text_height = max(1.0, bounds[3] - bounds[1])
    touch_tolerance = max(5.0, text_height * 0.30)
    target_tolerance = max(5.0, text_height * 0.18)
    minimum_margin = max(3.0, text_height * 0.08)
    minimum_leader_length = max(14.0, text_height * 0.30)
    chain_gap_tolerance = max(6.0, text_height * 0.20)
    max_angle_delta = 14.0
    max_segments = 5

    normalized: list[dict[str, Any]] = []
    for line_index, line in enumerate(annotation_lines):
        if not isinstance(line, dict):
            continue
        pair = _line_pair(line)
        if pair is None:
            continue
        angle = _line_angle(line, pair)
        if angle < 15.0 or angle > 75.0:
            continue
        length = math.dist(pair[0], pair[1])
        if length < minimum_leader_length:
            continue
        normalized.append(
            {
                "line_index": line_index,
                "endpoints": pair,
                "angle_deg": angle,
                "length_px": length,
            }
        )

    matches: list[dict[str, Any]] = []

    def collect_matches(
        path: list[int],
        current_index: int,
        entry_endpoint: int,
        text_distance: float,
        gap_trace: list[float],
        chain_length: float,
    ) -> None:
        current = normalized[current_index]
        entry_point = current["endpoints"][entry_endpoint]
        exit_point = current["endpoints"][1 - entry_endpoint]

        for pattern_index, pattern in enumerate(patterns):
            if not isinstance(pattern, dict):
                continue

            profile_overlap = overlaps_structural_profile(pattern)
            strong_fragmented_support = _strong_fragmented_pattern_support(pattern)
            if profile_overlap and not (
                len(path) > 1 and strong_fragmented_support
            ):
                continue

            target_distance = _point_to_pattern_distance(exit_point, pattern)
            if target_distance is None:
                continue

            forward_extension: float | None = None
            binding_mode = (
                "observed_endpoint_on_linear_pattern"
                if len(path) == 1
                else "fragmented_leader_endpoint_on_linear_pattern"
            )
            geometry_endpoint = exit_point

            if target_distance > target_tolerance:
                forward_extension = _ray_to_pattern_extension(
                    entry_point,
                    exit_point,
                    pattern,
                    max_extension=max(
                        6.0,
                        min(
                            chain_length * 0.70,
                            text_height * 1.25,
                        ),
                    ),
                    target_tolerance=target_tolerance,
                )
                if forward_extension is None:
                    continue
                segment_length = math.dist(entry_point, exit_point)
                if segment_length <= 1e-9:
                    continue
                direction_x = (exit_point[0] - entry_point[0]) / segment_length
                direction_y = (exit_point[1] - entry_point[1]) / segment_length
                geometry_endpoint = (
                    exit_point[0] + direction_x * forward_extension,
                    exit_point[1] + direction_y * forward_extension,
                )
                target_distance = 0.0
                binding_mode = (
                    "bounded_forward_extension_to_linear_pattern"
                    if len(path) == 1
                    else "fragmented_bounded_forward_extension_to_linear_pattern"
                )

            orientation = str(pattern.get("orientation") or "")
            axis = _AXIS_BY_VIEW_ORIENTATION.get((view_kind, orientation))
            if axis is None:
                continue

            matches.append(
                {
                    "line_index": int(current["line_index"]),
                    "line_indices": [
                        int(normalized[index]["line_index"])
                        for index in path
                    ],
                    "segment_count": len(path),
                    "chain_gap_px": [
                        round(value, 3) for value in gap_trace
                    ],
                    "pattern_index": pattern_index,
                    "orientation": orientation,
                    "axis": axis,
                    "pattern_axis_px": float(pattern["axis_px"]),
                    "pattern_span_px": list(pattern["span_px"]),
                    "text_touch_distance_px": round(text_distance, 3),
                    "pattern_target_distance_px": round(target_distance, 3),
                    "leader_forward_extension_px": (
                        round(forward_extension, 3)
                        if forward_extension is not None
                        else 0.0
                    ),
                    "binding_mode": binding_mode,
                    "geometry_endpoint_px": [
                        round(geometry_endpoint[0], 3),
                        round(geometry_endpoint[1], 3),
                    ],
                    "profile_overlap": profile_overlap,
                    "fragmented_pattern_support": (
                        {
                            "segment_count": pattern.get("segment_count"),
                            "gap_count": pattern.get("gap_count"),
                            "dash_score": pattern.get("dash_score"),
                        }
                        if profile_overlap and strong_fragmented_support
                        else None
                    ),
                }
            )

        if len(path) >= max_segments:
            return

        current_angle = float(current["angle_deg"])
        used = set(path)
        for next_index, candidate in enumerate(normalized):
            if next_index in used:
                continue
            if (
                _angle_difference(
                    current_angle,
                    float(candidate["angle_deg"]),
                )
                > max_angle_delta
            ):
                continue

            distances = [
                math.dist(exit_point, candidate["endpoints"][0]),
                math.dist(exit_point, candidate["endpoints"][1]),
            ]
            next_entry = 0 if distances[0] <= distances[1] else 1
            gap = distances[next_entry]
            if gap > chain_gap_tolerance:
                continue

            next_exit = candidate["endpoints"][1 - next_entry]
            if _point_to_rect_distance(next_exit, bounds) <= text_distance:
                continue

            collect_matches(
                [*path, next_index],
                next_index,
                next_entry,
                text_distance,
                [*gap_trace, gap],
                chain_length + float(candidate["length_px"]),
            )

    for line_index, line in enumerate(normalized):
        distances = [
            _point_to_rect_distance(line["endpoints"][0], bounds),
            _point_to_rect_distance(line["endpoints"][1], bounds),
        ]
        for entry_endpoint, text_distance in enumerate(distances):
            if text_distance > touch_tolerance:
                continue
            exit_point = line["endpoints"][1 - entry_endpoint]
            if _point_to_rect_distance(exit_point, bounds) <= text_distance:
                continue
            collect_matches(
                [line_index],
                line_index,
                entry_endpoint,
                text_distance,
                [],
                float(line["length_px"]),
            )

    matches.sort(
        key=lambda item: (
            item.get("binding_mode")
            not in {
                "observed_endpoint_on_linear_pattern",
                "fragmented_leader_endpoint_on_linear_pattern",
            },
            float(item["pattern_target_distance_px"]),
            float(item.get("leader_forward_extension_px", 0.0)),
            int(item.get("segment_count", 1)),
            float(item["text_touch_distance_px"]),
            int(item["line_index"]),
            int(item["pattern_index"]),
        )
    )

    duplicate_axis_tolerance = max(3.5, target_tolerance * 0.25)
    distinct_matches: list[dict[str, Any]] = []
    for match in matches:
        orientation = str(match.get("orientation") or "")
        pattern_axis_value = float(match["pattern_axis_px"])
        span = match.get("pattern_span_px", [])
        duplicate = False
        for existing in distinct_matches:
            if str(existing.get("orientation") or "") != orientation:
                continue
            if (
                abs(float(existing["pattern_axis_px"]) - pattern_axis_value)
                > duplicate_axis_tolerance
            ):
                continue
            existing_span = existing.get("pattern_span_px", [])
            if not (
                isinstance(span, list)
                and len(span) == 2
                and isinstance(existing_span, list)
                and len(existing_span) == 2
            ):
                continue
            start_a, end_a = sorted(float(value) for value in span)
            start_b, end_b = sorted(float(value) for value in existing_span)
            overlap = max(0.0, min(end_a, end_b) - max(start_a, start_b))
            shorter = min(end_a - start_a, end_b - start_b)
            if shorter > 0 and overlap / shorter >= 0.75:
                duplicate = True
                break
        if not duplicate:
            distinct_matches.append(match)

    matches = distinct_matches
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
            and abs(
                float(second.get("leader_forward_extension_px", 0.0))
                - float(best.get("leader_forward_extension_px", 0.0))
            )
            < minimum_margin
        ):
            return {
                "status": "unresolved",
                "reason": "multiple_linear_pattern_targets_without_margin",
                "candidate_bindings": matches,
            }

    if not region_id:
        return {"status": "unresolved", "reason": "region_id_missing"}

    basis = (
        "callout_fragmented_oblique_leader_to_unique_linear_pattern"
        if int(best.get("segment_count", 1)) > 1
        else "callout_oblique_leader_to_unique_linear_pattern"
    )
    return {
        "status": "bound",
        "basis": basis,
        "region_id": region_id,
        "entity_key": (
            f"{region_id}.LINEAR_PATTERN."
            f"{int(best['pattern_index']) + 1:03d}"
        ),
        **best,
    }

