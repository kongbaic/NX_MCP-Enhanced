from __future__ import annotations

from typing import Any

from .dimension_endpoint_candidates import derive_dimension_endpoint_candidates


_AXIS_BY_VIEW_ORIENTATION: dict[tuple[str, str], str] = {
    ("front", "horizontal"): "X",
    ("front", "vertical"): "Z",
    ("side", "horizontal"): "Y",
    ("side", "vertical"): "Z",
    ("top", "horizontal"): "X",
    ("top", "vertical"): "Y",
}


def _linear_value(token: Any) -> float | None:
    if not isinstance(token, str) or not token:
        return None
    nominal = token.split("±", 1)[0]
    try:
        value = float(nominal)
    except ValueError:
        return None
    return value if value > 0 else None


def _overall_value(overall_dimensions: dict[str, float], axis: str) -> float | None:
    key = {"X": "length_x", "Y": "width_y", "Z": "height_z"}[axis]
    value = overall_dimensions.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _profile_extreme(
    endpoint: dict[str, Any],
) -> tuple[str, float, str] | None:
    if endpoint.get("status") != "unique_physical_candidate":
        return None
    candidates = endpoint.get("physical_candidates")
    if not (
        isinstance(candidates, list)
        and len(candidates) == 1
        and isinstance(candidates[0], dict)
    ):
        return None
    item = candidates[0]
    if item.get("kind") != "profile_edge_candidate":
        return None
    side = item.get("relative_extreme_side")
    if side not in {"min", "max"}:
        return None
    position_px = item.get("position_px")
    if not isinstance(position_px, (int, float)):
        return None
    ref = str(item.get("ref") or "")
    if not ref:
        return None
    return side, float(position_px), ref


def derive_view_metric_calibrations(
    *,
    candidates: list[dict[str, Any]],
    region_views: dict[str, str],
    overall_dimensions: dict[str, float],
    relative_tolerance: float = 1e-6,
) -> list[dict[str, Any]]:
    """Derive fail-closed view-local pixel->mm calibrations.

    A calibration is emitted only when one accepted linear dimension:
    - belongs to one known orthographic view;
    - has two unique physical profile-edge endpoints;
    - marks those endpoints as opposite min/max extremes;
    - equals the independently supplied overall dimension for that axis.

    No OCR conflict is resolved here and no internal/local dimension is promoted
    to a global metric anchor.
    """

    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        region_id = str(candidate.get("region_id") or "")
        orientation = str(candidate.get("orientation") or "")
        view_kind = region_views.get(region_id)
        axis = (
            _AXIS_BY_VIEW_ORIENTATION.get((view_kind, orientation))
            if view_kind is not None
            else None
        )
        if not candidate_id or axis is None:
            continue

        dimension_value = _linear_value(candidate.get("accepted_token"))
        overall_value = _overall_value(overall_dimensions, axis)
        if dimension_value is None or overall_value is None:
            continue
        tolerance = max(abs(overall_value) * relative_tolerance, 1e-9)
        if abs(dimension_value - overall_value) > tolerance:
            continue

        endpoint_evidence = derive_dimension_endpoint_candidates(candidate)
        endpoints = endpoint_evidence.get("endpoints")
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            continue

        first = _profile_extreme(endpoints[0])
        second = _profile_extreme(endpoints[1])
        if first is None or second is None:
            continue
        by_side = {first[0]: first, second[0]: second}
        if set(by_side) != {"min", "max"}:
            continue

        min_px = by_side["min"][1]
        max_px = by_side["max"][1]
        if abs(max_px - min_px) <= 1e-9:
            continue

        if axis in {"X", "Y"}:
            min_mm = -overall_value / 2.0
            max_mm = overall_value / 2.0
        else:
            min_mm = 0.0
            max_mm = overall_value

        mm_per_px = (max_mm - min_mm) / (max_px - min_px)
        offset_mm = min_mm - mm_per_px * min_px
        key = (region_id, axis)
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "region_id": region_id,
                "view_kind": view_kind,
                "axis": axis,
                "candidate_id": candidate_id,
                "dimension_value": dimension_value,
                "overall_dimension_value": overall_value,
                "min_anchor": {
                    "ref": by_side["min"][2],
                    "position_px": min_px,
                    "coordinate_mm": min_mm,
                },
                "max_anchor": {
                    "ref": by_side["max"][2],
                    "position_px": max_px,
                    "coordinate_mm": max_mm,
                },
                "mm_per_px": mm_per_px,
                "offset_mm": offset_mm,
                "basis": "overall_dimension_with_opposite_profile_extremes",
            }
        )

    return sorted(output, key=lambda item: (item["region_id"], item["axis"]))
