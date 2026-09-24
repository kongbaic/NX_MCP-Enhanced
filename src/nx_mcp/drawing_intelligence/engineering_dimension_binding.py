from __future__ import annotations

import math
from typing import Any


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


def _segment_rect_distance(
    *,
    orientation: str,
    axis: float,
    span: list[Any],
    bounds: tuple[float, float, float, float],
) -> float | None:
    if not (
        len(span) == 2
        and all(isinstance(value, (int, float)) for value in span)
    ):
        return None
    start, end = sorted(float(value) for value in span)
    left, top, right, bottom = bounds

    if orientation == "vertical":
        dx = max(left - axis, 0.0, axis - right)
        dy = max(top - end, 0.0, start - bottom)
    elif orientation == "horizontal":
        dx = max(left - end, 0.0, start - right)
        dy = max(top - axis, 0.0, axis - bottom)
    else:
        return None
    return math.hypot(dx, dy)


def bind_callout_to_dimension_candidate(
    callout_bbox: Any,
    candidates: list[dict[str, Any]],
    *,
    region_id: str,
) -> dict[str, Any]:
    """Bind a non-linear engineering callout to one existing DG carrier.

    The function does not interpret the callout value. It only establishes that
    the text box is geometrically adjacent to one dimension-axis candidate with
    two or more witness positions. Accepted linear DGs are excluded.
    """

    bounds = _bbox_bounds(callout_bbox)
    if bounds is None:
        return {
            "status": "unresolved",
            "reason": "callout_bbox_invalid",
        }

    left, top, right, bottom = bounds
    width = max(1.0, right - left)
    height = max(1.0, bottom - top)
    expected_orientation: str | None
    if width > height * 1.25:
        expected_orientation = "horizontal"
    elif height > width * 1.25:
        expected_orientation = "vertical"
    else:
        expected_orientation = None

    maximum_distance = max(6.0, min(width, height) * 0.25)
    minimum_margin = max(4.0, min(width, height) * 0.10)
    matches: list[dict[str, Any]] = []

    for candidate in candidates:
        if str(candidate.get("region_id") or "") != region_id:
            continue
        if candidate.get("accepted_token") is not None:
            continue

        candidate_id = str(candidate.get("candidate_id") or "")
        orientation = str(candidate.get("orientation") or "")
        axis = candidate.get("axis_px")
        span = candidate.get("line_span_px")
        witnesses = [
            float(value)
            for value in candidate.get("witness_positions_px", [])
            if isinstance(value, (int, float))
        ]
        if not candidate_id or orientation not in {"horizontal", "vertical"}:
            continue
        if expected_orientation is not None and orientation != expected_orientation:
            continue
        if not isinstance(axis, (int, float)) or not isinstance(span, list):
            continue
        if len(witnesses) < 2:
            continue

        distance = _segment_rect_distance(
            orientation=orientation,
            axis=float(axis),
            span=span,
            bounds=bounds,
        )
        if distance is None or distance > maximum_distance:
            continue

        matches.append(
            {
                "candidate_id": candidate_id,
                "region_id": region_id,
                "orientation": orientation,
                "axis_px": float(axis),
                "line_span_px": list(span),
                "witness_positions_px": witnesses,
                "projected_center_axis_px": sum(witnesses) / len(witnesses),
                "text_geometry_distance_px": distance,
            }
        )

    matches.sort(
        key=lambda item: (
            float(item["text_geometry_distance_px"]),
            str(item["candidate_id"]),
        )
    )
    if not matches:
        return {
            "status": "unresolved",
            "reason": "no_nearby_unaccepted_dimension_geometry_candidate",
        }

    if len(matches) > 1:
        first = float(matches[0]["text_geometry_distance_px"])
        second = float(matches[1]["text_geometry_distance_px"])
        if second - first < minimum_margin:
            return {
                "status": "unresolved",
                "reason": "multiple_dimension_geometry_candidates_without_margin",
                "candidate_bindings": matches,
            }

    selected = matches[0]
    return {
        "status": "bound",
        "basis": "callout_bbox_to_existing_dimension_geometry_candidate",
        **selected,
    }
