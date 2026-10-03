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


def _circle_target_matches_on_ray(
    entry_point: tuple[float, float],
    exit_point: tuple[float, float],
    regions: list[Any],
    *,
    max_extension: float,
) -> list[dict[str, Any]]:
    """Match a leader shaft whose Hough segment stops before the arrow tip.

    The ray may extend only a bounded distance beyond the observed shaft, and
    only along the observed shaft direction.  This recovers common arrowhead
    gaps without allowing arbitrary point-to-circle snapping.
    """

    dx = exit_point[0] - entry_point[0]
    dy = exit_point[1] - entry_point[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9 or max_extension <= 0:
        return []

    ux = dx / length
    uy = dy / length
    matches: list[dict[str, Any]] = []

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
            fx = exit_point[0] - cx
            fy = exit_point[1] - cy

            for ring in rings:
                if not isinstance(ring, dict):
                    continue
                radius = ring.get("radius_px")
                if not isinstance(radius, (int, float)) or float(radius) <= 0:
                    continue
                radius_f = float(radius)
                tolerance = max(4.0, radius_f * 0.15)

                projection = -(fx * ux + fy * uy)
                probe_values = {
                    0.0,
                    max_extension,
                    min(max(projection, 0.0), max_extension),
                }

                b = 2.0 * (fx * ux + fy * uy)
                c = fx * fx + fy * fy - radius_f * radius_f
                discriminant = b * b - 4.0 * c
                if discriminant >= 0.0:
                    root = math.sqrt(discriminant)
                    for value in ((-b - root) / 2.0, (-b + root) / 2.0):
                        if 0.0 <= value <= max_extension:
                            probe_values.add(value)

                best: tuple[float, float, tuple[float, float]] | None = None
                for extension in probe_values:
                    px = exit_point[0] + ux * extension
                    py = exit_point[1] + uy * extension
                    residual = abs(math.hypot(px - cx, py - cy) - radius_f)
                    candidate = (residual, extension, (px, py))
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate

                if best is None or best[0] > tolerance or best[1] <= 1e-9:
                    continue
                residual, extension, point = best
                matches.append(
                    {
                        "region_id": region_id,
                        "circle_group_id": group_id,
                        "entity_key": f"{region_id}.{group_id}",
                        "ring_radius_px": radius_f,
                        "radial_residual_px": round(residual, 3),
                        "arrow_extension_px": round(extension, 3),
                        "extended_geometry_endpoint_px": [
                            round(point[0], 3),
                            round(point[1], 3),
                        ],
                    }
                )

    matches.sort(
        key=lambda item: (
            float(item["radial_residual_px"]),
            float(item["arrow_extension_px"]),
            str(item["entity_key"]),
            float(item["ring_radius_px"]),
        )
    )
    return matches


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
        targets = _circle_target_matches(exit_point, regions)
        binding_mode = "observed_endpoint_on_circle_ring"
        if not targets:
            entry_point = current["endpoints"][entry_endpoint]
            shaft_length = math.dist(entry_point, exit_point)
            max_extension = max(
                6.0,
                min(
                    shaft_length * 0.55,
                    text_height * 0.60,
                ),
            )
            targets = _circle_target_matches_on_ray(
                entry_point,
                exit_point,
                regions,
                max_extension=max_extension,
            )
            binding_mode = "bounded_arrow_extension_to_circle_ring"

        if len({item["entity_key"] for item in targets}) == 1 and targets:
            used = [normalized[index] for index in path]
            angles = [float(item["angle_deg"]) for item in used]
            selected = targets[0]
            geometry_endpoint = selected.get(
                "extended_geometry_endpoint_px",
                [
                    round(exit_point[0], 3),
                    round(exit_point[1], 3),
                ],
            )
            bindings.append(
                {
                    "line_indices": [int(item["line_index"]) for item in used],
                    "segment_count": len(path),
                    "text_touch_distance_px": round(text_distance, 3),
                    "chain_gap_px": [round(value, 3) for value in gap_trace],
                    "chain_angle_span_deg": round(max(angles) - min(angles), 3),
                    "geometry_endpoint_px": geometry_endpoint,
                    "binding_mode": binding_mode,
                    **selected,
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


def _curve_trace(
    candidate: dict[str, Any],
) -> list[tuple[float, float]] | None:
    if (
        candidate.get("kind") != "curved_boundary_candidate"
        or candidate.get("candidate_only") is not True
        or candidate.get("exterior_boundary_candidate") is not True
        or candidate.get("curve_classification_basis")
        != "stable_cocircular_exterior_contour_turning"
    ):
        return None
    raw = candidate.get("curve_trace_px")
    if not (
        isinstance(raw, list)
        and len(raw) >= 5
        and all(
            isinstance(point, list)
            and len(point) >= 2
            and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in point[:2]
            )
            for point in raw
        )
    ):
        return None
    return [
        (float(point[0]), float(point[1]))
        for point in raw
    ]


def _point_to_segment_distance(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    px, py = point
    ax, ay = first
    bx, by = second
    dx = bx - ax
    dy = by - ay
    denominator = dx * dx + dy * dy
    if denominator <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / denominator
    t = min(1.0, max(0.0, t))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.hypot(px - qx, py - qy)


def _point_to_curve_distance(
    point: tuple[float, float],
    trace: list[tuple[float, float]],
) -> float:
    return min(
        _point_to_segment_distance(point, first, second)
        for first, second in zip(trace, trace[1:], strict=True)
    )


def _curve_target_matches(
    point: tuple[float, float],
    curve_candidates: list[Any],
    *,
    tolerance: float,
    allowed_curve_source_ids: set[str] | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for curve_index, candidate in enumerate(curve_candidates):
        if not isinstance(candidate, dict):
            continue
        source_id = f"hybrid:curve-boundary:{curve_index}"
        if (
            allowed_curve_source_ids is not None
            and source_id not in allowed_curve_source_ids
        ):
            continue
        trace = _curve_trace(candidate)
        if trace is None:
            continue
        residual = _point_to_curve_distance(point, trace)
        if residual > tolerance:
            continue
        matches.append(
            {
                "curve_index": curve_index,
                "curve_source_id": source_id,
                "curve_contact_residual_px": round(residual, 3),
            }
        )
    return matches


def _curve_target_matches_on_ray(
    entry_point: tuple[float, float],
    exit_point: tuple[float, float],
    curve_candidates: list[Any],
    *,
    max_extension: float,
    tolerance: float,
    allowed_curve_source_ids: set[str] | None,
) -> list[dict[str, Any]]:
    dx = exit_point[0] - entry_point[0]
    dy = exit_point[1] - entry_point[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9 or max_extension <= 0.0:
        return []

    ux = dx / length
    uy = dy / length
    steps = max(1, int(math.ceil(max_extension)))
    matches: list[dict[str, Any]] = []
    for curve_index, candidate in enumerate(curve_candidates):
        if not isinstance(candidate, dict):
            continue
        source_id = f"hybrid:curve-boundary:{curve_index}"
        if (
            allowed_curve_source_ids is not None
            and source_id not in allowed_curve_source_ids
        ):
            continue
        trace = _curve_trace(candidate)
        if trace is None:
            continue

        best: tuple[float, float, tuple[float, float]] | None = None
        for step in range(1, steps + 1):
            extension = min(float(step), max_extension)
            point = (
                exit_point[0] + ux * extension,
                exit_point[1] + uy * extension,
            )
            residual = _point_to_curve_distance(point, trace)
            current = (residual, extension, point)
            if best is None or current[:2] < best[:2]:
                best = current

        if best is None or best[0] > tolerance:
            continue
        residual, extension, point = best
        matches.append(
            {
                "curve_index": curve_index,
                "curve_source_id": source_id,
                "curve_contact_residual_px": round(residual, 3),
                "arrow_extension_px": round(extension, 3),
                "extended_geometry_endpoint_px": [
                    round(point[0], 3),
                    round(point[1], 3),
                ],
            }
        )
    matches.sort(
        key=lambda item: (
            float(item["curve_contact_residual_px"]),
            float(item.get("arrow_extension_px", 0.0)),
            str(item["curve_source_id"]),
        )
    )
    return matches


def _curve_chain_bindings(
    bounds: tuple[float, float, float, float],
    annotation_lines: list[Any],
    curve_candidates: list[Any],
    *,
    allowed_curve_source_ids: set[str] | None,
) -> list[dict[str, Any]]:
    text_height = max(1.0, bounds[3] - bounds[1])
    touch_tolerance = max(5.0, text_height * 0.30)
    chain_gap_tolerance = max(6.0, text_height * 0.20)
    curve_contact_tolerance = max(3.0, text_height * 0.12)
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
        targets = _curve_target_matches(
            exit_point,
            curve_candidates,
            tolerance=curve_contact_tolerance,
            allowed_curve_source_ids=allowed_curve_source_ids,
        )
        binding_mode = "observed_endpoint_on_curve_trace"
        if not targets:
            entry_point = current["endpoints"][entry_endpoint]
            shaft_length = math.dist(entry_point, exit_point)
            max_extension = max(
                6.0,
                min(
                    shaft_length * 0.55,
                    text_height * 0.60,
                ),
            )
            targets = _curve_target_matches_on_ray(
                entry_point,
                exit_point,
                curve_candidates,
                max_extension=max_extension,
                tolerance=curve_contact_tolerance,
                allowed_curve_source_ids=allowed_curve_source_ids,
            )
            binding_mode = "bounded_arrow_extension_to_curve_trace"

        unique_sources = {
            item["curve_source_id"]
            for item in targets
        }
        if len(unique_sources) == 1 and targets:
            used = [normalized[index] for index in path]
            angles = [float(item["angle_deg"]) for item in used]
            selected = sorted(
                targets,
                key=lambda item: (
                    float(item["curve_contact_residual_px"]),
                    float(item.get("arrow_extension_px", 0.0)),
                    str(item["curve_source_id"]),
                ),
            )[0]
            bindings.append(
                {
                    "line_indices": [
                        int(item["line_index"])
                        for item in used
                    ],
                    "segment_count": len(path),
                    "text_touch_distance_px": round(text_distance, 3),
                    "chain_gap_px": [
                        round(value, 3)
                        for value in gap_trace
                    ],
                    "chain_angle_span_deg": round(
                        max(angles) - min(angles),
                        3,
                    ),
                    "binding_mode": binding_mode,
                    **selected,
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


def bind_callout_to_curve_candidate(
    callout_bbox: Any,
    annotation_lines: Any,
    curve_candidates: Any,
    *,
    allowed_curve_source_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Bind a callout only through a leader chain that contacts a curve trace."""

    bounds = _bbox_bounds(callout_bbox)
    if bounds is None:
        return {
            "status": "unresolved",
            "reason": "callout_bbox_invalid",
        }
    if not isinstance(annotation_lines, list) or not isinstance(
        curve_candidates,
        list,
    ):
        return {
            "status": "unresolved",
            "reason": "annotation_geometry_unavailable",
        }

    bindings = _curve_chain_bindings(
        bounds,
        annotation_lines,
        curve_candidates,
        allowed_curve_source_ids=allowed_curve_source_ids,
    )
    unique_sources = sorted(
        {
            item["curve_source_id"]
            for item in bindings
        }
    )
    if len(unique_sources) != 1:
        return {
            "status": "unresolved",
            "reason": (
                "no_unique_callout_to_curve_leader"
                if not unique_sources
                else "multiple_curve_candidates_supported_by_annotation_lines"
            ),
            "candidate_bindings": bindings,
        }

    curve_source_id = unique_sources[0]
    source_bindings = [
        item
        for item in bindings
        if item["curve_source_id"] == curve_source_id
    ]
    shortest = min(
        item["segment_count"]
        for item in source_bindings
    )
    support = [
        item
        for item in source_bindings
        if item["segment_count"] == shortest
    ]
    return {
        "status": "bound",
        "basis": "callout_bbox_to_collinear_segment_chain_to_curve_trace",
        "curve_source_id": curve_source_id,
        "curve_index": int(support[0]["curve_index"]),
        "support": support,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }


def bind_callout_to_circle_entity(
    callout_bbox: Any,
    annotation_lines: Any,
    regions: Any,
) -> dict[str, Any]:
    """Bind only through a deterministic text-to-line-chain-to-circle path."""

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
        "basis": "callout_bbox_to_collinear_segment_chain_to_circle_ring",
        "entity_key": entity_key,
        "support": support,
    }
