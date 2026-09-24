from __future__ import annotations

import math
from typing import Any


def _bbox_bounds(bbox: Any) -> tuple[float, float, float, float] | None:
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
    dx = max(left - x, 0.0, x - right)
    dy = max(top - y, 0.0, y - bottom)
    return math.hypot(dx, dy)


def _circle_target_matches(
    point: tuple[float, float],
    regions: list[Any],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    px, py = point
    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        groups = region.get("circle_groups", [])
        if not region_id or not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("circle_group_id") or "")
            center = group.get("center_px")
            rings = group.get("rings", [])
            if not (
                group_id
                and isinstance(center, list)
                and len(center) >= 2
                and all(isinstance(value, (int, float)) for value in center[:2])
                and isinstance(rings, list)
                and rings
            ):
                continue
            cx, cy = float(center[0]), float(center[1])
            radial_distance = math.hypot(px - cx, py - cy)
            ring_matches: list[tuple[float, float]] = []
            for ring in rings:
                if not isinstance(ring, dict):
                    continue
                radius = ring.get("radius_px")
                if not isinstance(radius, (int, float)) or float(radius) <= 0:
                    continue
                radius_f = float(radius)
                residual = abs(radial_distance - radius_f)
                tolerance = max(5.0, radius_f * 0.18)
                if residual <= tolerance:
                    ring_matches.append((residual, radius_f))
            if not ring_matches:
                continue
            ring_matches.sort()
            residual, radius = ring_matches[0]
            matches.append(
                {
                    "region_id": region_id,
                    "circle_group_id": group_id,
                    "entity_key": f"{region_id}.{group_id}",
                    "ring_radius_px": radius,
                    "radial_residual_px": round(residual, 3),
                }
            )
    return matches


def _parallel_pair_target_matches(
    point: tuple[float, float],
    regions: list[Any],
    *,
    tolerance: float = 5.0,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    px, py = point

    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        pairs = region.get("parallel_dash_pair_candidates", [])
        if not region_id or not isinstance(pairs, list):
            continue

        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            pair_id = str(pair.get("pair_id") or "")
            orientation = str(pair.get("orientation") or "")
            axes = pair.get("axes_px")
            span = pair.get("span_px")
            if not (
                pair_id
                and orientation in {"horizontal", "vertical"}
                and isinstance(axes, list)
                and len(axes) == 2
                and isinstance(span, list)
                and len(span) == 2
                and all(isinstance(value, (int, float)) for value in [*axes, *span])
            ):
                continue

            axis_min, axis_max = sorted(float(value) for value in axes)
            span_min, span_max = sorted(float(value) for value in span)

            if orientation == "horizontal":
                inside = (
                    span_min - tolerance <= px <= span_max + tolerance
                    and axis_min - tolerance <= py <= axis_max + tolerance
                )
            else:
                inside = (
                    axis_min - tolerance <= px <= axis_max + tolerance
                    and span_min - tolerance <= py <= span_max + tolerance
                )
            if not inside:
                continue

            matches.append(
                {
                    "region_id": region_id,
                    "pair_id": pair_id,
                    "entity_key": f"{region_id}.{pair_id}",
                    "target_kind": "parallel_dash_pair",
                    "orientation": orientation,
                    "axes_px": [axis_min, axis_max],
                    "span_px": [span_min, span_max],
                }
            )

    return matches


def _ray_rect_distance(
    start: tuple[float, float],
    direction: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> float | None:
    sx, sy = start
    dx, dy = direction
    left, top, right, bottom = rect

    t_min = 0.0
    t_max = float("inf")
    for origin, delta, low, high in (
        (sx, dx, left, right),
        (sy, dy, top, bottom),
    ):
        if abs(delta) < 1e-9:
            if origin < low or origin > high:
                return None
            continue
        first = (low - origin) / delta
        second = (high - origin) / delta
        entry = min(first, second)
        exit_ = max(first, second)
        t_min = max(t_min, entry)
        t_max = min(t_max, exit_)
        if t_min > t_max:
            return None

    if t_max < 0:
        return None
    return max(0.0, t_min)


def _forward_parallel_pair_matches(
    entry_point: tuple[float, float],
    exit_point: tuple[float, float],
    regions: list[Any],
    *,
    max_extension: float,
) -> list[dict[str, Any]]:
    dx = exit_point[0] - entry_point[0]
    dy = exit_point[1] - entry_point[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return []

    direction = (dx / length, dy / length)
    matches: list[dict[str, Any]] = []

    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        pairs = region.get("parallel_dash_pair_candidates", [])
        if not region_id or not isinstance(pairs, list):
            continue

        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            pair_id = str(pair.get("pair_id") or "")
            orientation = str(pair.get("orientation") or "")
            axes = pair.get("axes_px")
            span = pair.get("span_px")
            if not (
                pair_id
                and orientation in {"horizontal", "vertical"}
                and isinstance(axes, list)
                and len(axes) == 2
                and isinstance(span, list)
                and len(span) == 2
                and all(isinstance(value, (int, float)) for value in [*axes, *span])
            ):
                continue

            axis_min, axis_max = sorted(float(value) for value in axes)
            span_min, span_max = sorted(float(value) for value in span)
            margin = 3.0
            if orientation == "horizontal":
                rect = (
                    span_min - margin,
                    axis_min - margin,
                    span_max + margin,
                    axis_max + margin,
                )
            else:
                rect = (
                    axis_min - margin,
                    span_min - margin,
                    axis_max + margin,
                    span_max + margin,
                )

            distance = _ray_rect_distance(exit_point, direction, rect)
            if distance is None or distance <= 0 or distance > max_extension:
                continue

            hit_point = (
                exit_point[0] + direction[0] * distance,
                exit_point[1] + direction[1] * distance,
            )
            matches.append(
                {
                    "region_id": region_id,
                    "pair_id": pair_id,
                    "entity_key": f"{region_id}.{pair_id}",
                    "target_kind": "parallel_dash_pair",
                    "orientation": orientation,
                    "axes_px": [axis_min, axis_max],
                    "span_px": [span_min, span_max],
                    "forward_extension_px": round(distance, 3),
                    "geometry_hit_px": [
                        round(hit_point[0], 3),
                        round(hit_point[1], 3),
                    ],
                }
            )

    return matches


def _geometry_target_matches(
    point: tuple[float, float],
    regions: list[Any],
) -> list[dict[str, Any]]:
    return [
        *_circle_target_matches(point, regions),
        *_parallel_pair_target_matches(point, regions),
    ]


def _line_angle(line: dict[str, Any]) -> float | None:
    angle = line.get("angle_deg")
    if isinstance(angle, (int, float)):
        return float(angle)

    pair = _endpoint_pair(line)
    if pair is None:
        return None
    (x1, y1), (x2, y2) = pair
    raw = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180.0
    return 180.0 - raw if raw > 90.0 else raw


def _endpoint_pair(line: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]] | None:
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


def _angle_difference(left: float, right: float) -> float:
    delta = abs(left - right)
    return min(delta, 180.0 - delta)


def _chain_bindings(
    bounds: tuple[float, float, float, float],
    annotation_lines: list[Any],
    regions: list[Any],
) -> list[dict[str, Any]]:
    text_height = max(1.0, bounds[3] - bounds[1])
    touch_tolerance = max(5.0, text_height * 0.30)
    chain_gap_tolerance = max(6.0, text_height * 0.20)
    max_angle_delta = 14.0
    max_segments = 5

    normalized: list[dict[str, Any]] = []
    for line_index, line in enumerate(annotation_lines):
        if not isinstance(line, dict):
            continue
        pair = _endpoint_pair(line)
        angle = _line_angle(line)
        if pair is None or angle is None:
            continue
        normalized.append(
            {
                "line_index": line_index,
                "endpoints": pair,
                "angle_deg": angle,
            }
        )

    bindings: list[dict[str, Any]] = []

    def visit(
        path: list[int],
        current_index: int,
        entry_endpoint: int,
        text_distance: float,
        gap_trace: list[float],
    ) -> None:
        current = normalized[current_index]
        exit_endpoint = 1 - entry_endpoint
        exit_point = current["endpoints"][exit_endpoint]
        targets = _geometry_target_matches(exit_point, regions)
        binding_endpoint = exit_point
        if not targets:
            entry_point = current["endpoints"][entry_endpoint]
            targets = _forward_parallel_pair_matches(
                entry_point,
                exit_point,
                regions,
                max_extension=max(10.0, text_height * 0.65),
            )
            if len(targets) == 1 and "geometry_hit_px" in targets[0]:
                binding_endpoint = (
                    float(targets[0]["geometry_hit_px"][0]),
                    float(targets[0]["geometry_hit_px"][1]),
                )

        if len(targets) == 1:
            used = [normalized[index] for index in path]
            angles = [float(item["angle_deg"]) for item in used]
            bindings.append(
                {
                    "line_indices": [int(item["line_index"]) for item in used],
                    "segment_count": len(path),
                    "text_touch_distance_px": round(text_distance, 3),
                    "chain_gap_px": [round(value, 3) for value in gap_trace],
                    "chain_angle_span_deg": round(max(angles) - min(angles), 3),
                    "geometry_endpoint_px": [
                        round(binding_endpoint[0], 3),
                        round(binding_endpoint[1], 3),
                    ],
                    **targets[0],
                }
            )
            return

        if len(path) >= max_segments:
            return

        current_angle = float(current["angle_deg"])
        used_indices = set(path)

        for next_index, candidate in enumerate(normalized):
            if next_index in used_indices:
                continue
            if _angle_difference(current_angle, float(candidate["angle_deg"])) > max_angle_delta:
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
            if _point_to_rect_distance(next_exit, bounds) <= touch_tolerance:
                continue

            visit(
                [*path, next_index],
                next_index,
                next_entry,
                text_distance,
                [*gap_trace, gap],
            )

    for line_index, line in enumerate(normalized):
        first, second = line["endpoints"]
        distances = [
            _point_to_rect_distance(first, bounds),
            _point_to_rect_distance(second, bounds),
        ]
        for entry_endpoint, text_distance in enumerate(distances):
            if text_distance > touch_tolerance:
                continue
            visit(
                [line_index],
                line_index,
                entry_endpoint,
                text_distance,
                [],
            )

    return bindings


def bind_callout_to_circle_entity(
    callout_bbox: Any,
    annotation_lines: Any,
    regions: Any,
) -> dict[str, Any]:
    """Bind only through a deterministic text-to-line-chain-to-geometry path."""

    bounds = _bbox_bounds(callout_bbox)
    if bounds is None:
        return {
            "status": "unresolved",
            "reason": "callout_bbox_invalid",
        }
    if not isinstance(annotation_lines, list) or not isinstance(regions, list):
        return {
            "status": "unresolved",
            "reason": "annotation_geometry_unavailable",
        }

    bindings = _chain_bindings(bounds, annotation_lines, regions)
    unique_entities = sorted({item["entity_key"] for item in bindings})
    if len(unique_entities) != 1:
        return {
            "status": "unresolved",
            "reason": (
                "no_unique_callout_to_circle_leader"
                if not unique_entities
                else "multiple_circle_entities_supported_by_annotation_lines"
            ),
            "candidate_bindings": bindings,
        }

    entity_key = unique_entities[0]
    entity_bindings = [item for item in bindings if item["entity_key"] == entity_key]
    shortest = min(item["segment_count"] for item in entity_bindings)
    support = [item for item in entity_bindings if item["segment_count"] == shortest]
    return {
        "status": "bound",
        "basis": "callout_bbox_to_collinear_segment_chain_to_geometry",
        "entity_key": entity_key,
        "support": support,
    }
