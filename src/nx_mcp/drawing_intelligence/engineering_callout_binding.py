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


def bind_callout_to_circle_entity(
    callout_bbox: Any,
    annotation_lines: Any,
    regions: Any,
) -> dict[str, Any]:
    """Bind only when one visible oblique line bridges text and one circle ring."""

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

    text_height = max(1.0, bounds[3] - bounds[1])
    touch_tolerance = max(5.0, text_height * 0.30)
    bindings: list[dict[str, Any]] = []

    for line_index, line in enumerate(annotation_lines):
        if not isinstance(line, dict):
            continue
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
            continue

        first = (float(endpoints[0][0]), float(endpoints[0][1]))
        second = (float(endpoints[1][0]), float(endpoints[1][1]))
        first_text_distance = _point_to_rect_distance(first, bounds)
        second_text_distance = _point_to_rect_distance(second, bounds)

        if first_text_distance <= touch_tolerance:
            text_endpoint = 0
            geometry_point = second
            text_distance = first_text_distance
        elif second_text_distance <= touch_tolerance:
            text_endpoint = 1
            geometry_point = first
            text_distance = second_text_distance
        else:
            continue

        targets = _circle_target_matches(geometry_point, regions)
        if len(targets) != 1:
            continue

        bindings.append(
            {
                "line_index": line_index,
                "text_endpoint": text_endpoint,
                "text_touch_distance_px": round(text_distance, 3),
                "geometry_endpoint_px": [
                    round(geometry_point[0], 3),
                    round(geometry_point[1], 3),
                ],
                **targets[0],
            }
        )

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
    return {
        "status": "bound",
        "basis": "callout_bbox_to_oblique_line_to_circle_ring",
        "entity_key": entity_key,
        "support": entity_bindings,
    }
