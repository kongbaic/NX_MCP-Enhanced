"""Visual-scale diagnostics only.

Pixel-derived millimeter estimates in this module are non-authoritative and
must never feed canonical ReaderObservations, Resolver engineering coordinates,
Planner geometry, or NX operations. Engineering coordinates are solved only
from dimension constraints, datum relations, symmetry/alignment, and explicit
engineering facts.
"""

ENGINEERING_AUTHORITATIVE = False

from __future__ import annotations

from typing import Any

_VIEW_CENTER_AXES: dict[str, tuple[str, str, str]] = {
    "front": ("X", "Z", "Y"),
    "side": ("Y", "Z", "X"),
    "top": ("X", "Y", "Z"),
}


def _calibration_lookup(
    calibrations: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(item.get("region_id") or ""), str(item.get("axis") or "")): item
        for item in calibrations
    }


def _metric_coordinate(
    calibration: dict[str, Any],
    pixel_coordinate: float,
) -> float | None:
    mm_per_px = calibration.get("mm_per_px")
    offset_mm = calibration.get("offset_mm")
    if not isinstance(mm_per_px, (int, float)) or not isinstance(
        offset_mm,
        (int, float),
    ):
        return None
    return float(mm_per_px) * pixel_coordinate + float(offset_mm)


def _bound_callout_facts(
    callout_ledger: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, list[Any]]],
]:
    values_by_entity: dict[str, dict[str, list[Any]]] = {}

    for item in callout_ledger:
        binding = item.get("binding")
        facts = item.get("facts")
        if not (
            isinstance(binding, dict)
            and binding.get("status") == "bound"
            and isinstance(facts, dict)
        ):
            continue
        entity_key = str(binding.get("entity_key") or "")
        if not entity_key:
            continue

        entity_values = values_by_entity.setdefault(entity_key, {})
        for field, value in facts.items():
            if value is None:
                continue
            entity_values.setdefault(str(field), []).append(value)

    resolved: dict[str, dict[str, Any]] = {}
    conflicts: dict[str, dict[str, list[Any]]] = {}
    for entity_key, fields in values_by_entity.items():
        for field, raw_values in fields.items():
            unique: list[Any] = []
            for value in raw_values:
                if value not in unique:
                    unique.append(value)
            if len(unique) == 1:
                resolved.setdefault(entity_key, {})[field] = unique[0]
            elif len(unique) > 1:
                conflicts.setdefault(entity_key, {})[field] = unique

    return resolved, conflicts


def derive_metric_circle_primitives(
    *,
    regions: list[dict[str, Any]],
    region_views: dict[str, str],
    calibrations: list[dict[str, Any]],
    callout_ledger: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Metricize circle centers without inferring engineering radius from pixels.

    Circle/ring detection supplies geometry identity and pixel centers/radii.
    View calibration supplies the two transverse center coordinates in mm.
    Engineering diameter or other feature values are accepted only from an
    explicitly bound callout. Pixel radius is never converted into an
    engineering diameter.
    """

    calibration_by_axis = _calibration_lookup(calibrations)
    facts_by_entity, conflicts_by_entity = _bound_callout_facts(callout_ledger)

    items: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for region in regions:
        region_id = str(region.get("region_id") or "")
        view_kind = region_views.get(region_id)
        axis_mapping = _VIEW_CENTER_AXES.get(str(view_kind or ""))
        if not region_id or axis_mapping is None:
            continue

        horizontal_axis, vertical_axis, normal_axis = axis_mapping
        horizontal_calibration = calibration_by_axis.get((region_id, horizontal_axis))
        vertical_calibration = calibration_by_axis.get((region_id, vertical_axis))

        groups = region.get("circle_groups", [])
        if not isinstance(groups, list):
            continue

        for group in groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("circle_group_id") or "")
            center_px = group.get("center_px")
            rings = group.get("rings", [])
            if not (
                group_id
                and isinstance(center_px, list)
                and len(center_px) >= 2
                and isinstance(center_px[0], (int, float))
                and isinstance(center_px[1], (int, float))
                and isinstance(rings, list)
                and rings
            ):
                continue

            entity_key = f"{region_id}.{group_id}"
            missing_axes = [
                axis
                for axis, calibration in (
                    (horizontal_axis, horizontal_calibration),
                    (vertical_axis, vertical_calibration),
                )
                if calibration is None
            ]
            if missing_axes:
                unresolved.append(
                    {
                        "entity_key": entity_key,
                        "region_id": region_id,
                        "view_kind": view_kind,
                        "reason": "missing_view_axis_calibration",
                        "missing_axes": missing_axes,
                        "basis": "fail_closed_metric_circle_center",
                    }
                )
                continue
            if horizontal_calibration is None or vertical_calibration is None:
                continue

            horizontal_mm = _metric_coordinate(
                horizontal_calibration,
                float(center_px[0]),
            )
            vertical_mm = _metric_coordinate(
                vertical_calibration,
                float(center_px[1]),
            )
            if horizontal_mm is None or vertical_mm is None:
                unresolved.append(
                    {
                        "entity_key": entity_key,
                        "region_id": region_id,
                        "view_kind": view_kind,
                        "reason": "invalid_view_axis_calibration",
                        "missing_axes": [],
                        "basis": "fail_closed_metric_circle_center",
                    }
                )
                continue

            facts = facts_by_entity.get(entity_key, {})
            conflicts = conflicts_by_entity.get(entity_key, {})
            ring_count = len(rings)

            size_assignment_status = "missing_engineering_size"
            diameter_mm: float | None = None
            diameter = facts.get("diameter")
            if "diameter" in conflicts:
                size_assignment_status = "conflicting_bound_diameter"
            elif isinstance(diameter, (int, float)) and float(diameter) > 0:
                if ring_count == 1:
                    diameter_mm = float(diameter)
                    size_assignment_status = "single_ring_bound_diameter"
                else:
                    size_assignment_status = "group_level_diameter_ring_unresolved"

            item = {
                "entity_key": entity_key,
                "region_id": region_id,
                "view_kind": view_kind,
                "axis": normal_axis,
                "center_px": [float(center_px[0]), float(center_px[1])],
                "center_mm": {
                    horizontal_axis: horizontal_mm,
                    vertical_axis: vertical_mm,
                },
                "rings": [dict(ring) for ring in rings if isinstance(ring, dict)],
                "ring_count": ring_count,
                "engineering_facts": dict(facts),
                "engineering_fact_conflicts": dict(conflicts),
                "diameter_mm": diameter_mm,
                "size_assignment_status": size_assignment_status,
                "pixel_radius_used_for_engineering_size": False,
                "basis": (
                    "circle_detection_plus_view_metric_calibration_plus_explicit_bound_callout"
                    if facts
                    else "circle_detection_plus_view_metric_calibration"
                ),
            }
            items.append(item)

    items.sort(key=lambda item: (item["region_id"], item["entity_key"]))
    unresolved.sort(key=lambda item: (item["region_id"], item["entity_key"]))
    return {
        "items": items,
        "unresolved": unresolved,
    }
