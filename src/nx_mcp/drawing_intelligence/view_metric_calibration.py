"""Visual-scale diagnostics only.

Pixel-derived millimeter estimates in this module are non-authoritative and
must never feed canonical ReaderObservations, Resolver engineering coordinates,
Planner geometry, or NX operations. Engineering coordinates are solved only
from dimension constraints, datum relations, symmetry/alignment, and explicit
engineering facts.
"""

from __future__ import annotations

ENGINEERING_AUTHORITATIVE = False

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


def _conflict_backed_overall_probe(
    candidate: dict[str, Any],
    *,
    overall_value: float,
    relative_tolerance: float,
) -> tuple[dict[str, Any], str] | None:
    """Build a spatial-only probe for a conflicting OCR overall dimension.

    The OCR conflict remains unresolved.  The whole-drawing proposal is reused
    only to select the adjacent witness pair, while the metric value comes from
    independent overall-dimension context.  A calibration is eligible only when
    one and only one local linear token agrees with that overall value.
    """

    if candidate.get("accepted_token") is not None:
        return None
    if candidate.get("decision_reason") != "global_local_token_disagreement":
        return None

    global_token = candidate.get("global_proposal_token")
    local_tokens = candidate.get("wide_local_linear_tokens")
    if not isinstance(global_token, str) or not global_token:
        return None
    if not isinstance(local_tokens, list) or len(local_tokens) != 1:
        return None

    local_token = local_tokens[0]
    local_value = _linear_value(local_token)
    if local_value is None:
        return None

    tolerance = max(abs(overall_value) * relative_tolerance, 1e-9)
    if abs(local_value - overall_value) > tolerance:
        return None

    spatial_probe = {**candidate, "accepted_token": global_token}
    return spatial_probe, str(local_token)


def _profile_extreme(
    endpoint: dict[str, Any],
) -> tuple[str, float, str] | None:
    if endpoint.get("status") != "unique_physical_candidate":
        return None
    candidates = endpoint.get("physical_candidates")
    if not (
        isinstance(candidates, list) and len(candidates) == 1 and isinstance(candidates[0], dict)
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


def derive_view_axis_boundaries(
    *,
    candidates: list[dict[str, Any]],
    region_views: dict[str, str],
    overall_dimensions: dict[str, float],
    profile_inventory: list[dict[str, Any]] | None = None,
    relative_tolerance: float = 1e-6,
) -> list[dict[str, Any]]:
    """Identify overall boundary owners without inferring mm from pixel distance.

    Pixel geometry is used only to identify the two physical endpoints of an
    independently known overall dimension.  No pixel-to-mm scale or internal
    coordinate is derived here.
    """

    resolved_by_axis: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for candidate in candidates:
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

        overall_value = _overall_value(overall_dimensions, axis)
        if overall_value is None:
            continue

        dimension_value = _linear_value(candidate.get("accepted_token"))
        endpoint_candidate = candidate
        supporting_local_token: str | None = None
        basis = "accepted_overall_dimension_endpoint_identity"

        if dimension_value is None:
            conflict_probe = _conflict_backed_overall_probe(
                candidate,
                overall_value=overall_value,
                relative_tolerance=relative_tolerance,
            )
            if conflict_probe is None:
                continue
            endpoint_candidate, supporting_local_token = conflict_probe
            dimension_value = overall_value
            basis = "conflict_preserved_overall_dimension_endpoint_identity"
        else:
            tolerance = max(abs(overall_value) * relative_tolerance, 1e-9)
            if abs(dimension_value - overall_value) > tolerance:
                continue

        endpoint_evidence = derive_dimension_endpoint_candidates(endpoint_candidate)
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

        if orientation == "horizontal":
            role_by_side = {
                "min": "overall_min",
                "max": "overall_max",
            }
        elif orientation == "vertical":
            # Image Y grows downward.  The upper pixel extreme is the positive
            # orthographic axis boundary; the lower extreme is overall_min.
            role_by_side = {
                "min": "overall_max",
                "max": "overall_min",
            }
        else:
            continue

        anchors = [
            {
                "ref": by_side[side][2],
                "pixel_extreme_side": side,
                "role": role_by_side[side],
                "position_px": by_side[side][1],
            }
            for side in ("min", "max")
        ]
        record = {
            "status": "resolved",
            "region_id": region_id,
            "view_kind": view_kind,
            "axis": axis,
            "candidate_id": candidate_id,
            "overall_dimension_value": overall_value,
            "anchors": anchors,
            "basis": basis,
            "engineering_coordinate_inferred_from_pixels": False,
            **(
                {
                    "spatial_label_token": candidate.get("global_proposal_token"),
                    "supporting_local_token": supporting_local_token,
                    "ocr_conflict_preserved": True,
                }
                if supporting_local_token is not None
                else {}
            ),
        }
        resolved_by_axis.setdefault((region_id, axis), []).append(record)

    if profile_inventory:
        resolved_keys = set(resolved_by_axis)
        for region_id, view_kind in region_views.items():
            for axis in ("X", "Y", "Z"):
                if (region_id, axis) in resolved_keys:
                    continue
                overall_value = _overall_value(overall_dimensions, axis)
                expected_orientation = _PROFILE_ORIENTATION_BY_VIEW_AXIS.get(
                    (view_kind, axis)
                )
                if overall_value is None or expected_orientation is None:
                    continue

                edges = [
                    item
                    for item in profile_inventory
                    if isinstance(item, dict)
                    and item.get("kind") == "profile_edge_candidate"
                    and str(item.get("region_id") or "") == region_id
                    and str(item.get("source_orientation") or "")
                    == expected_orientation
                ]
                minimum = [
                    item for item in edges if item.get("relative_extreme_side") == "min"
                ]
                maximum = [
                    item for item in edges if item.get("relative_extreme_side") == "max"
                ]
                if len(minimum) != 1 or len(maximum) != 1:
                    continue

                min_edge = minimum[0]
                max_edge = maximum[0]
                if str(min_edge.get("ref") or "") == str(max_edge.get("ref") or ""):
                    continue

                role_by_side = (
                    {"min": "overall_min", "max": "overall_max"}
                    if expected_orientation == "vertical"
                    else {"min": "overall_max", "max": "overall_min"}
                )
                resolved_by_axis[(region_id, axis)] = [
                    {
                        "status": "resolved",
                        "region_id": region_id,
                        "view_kind": view_kind,
                        "axis": axis,
                        "candidate_id": None,
                        "overall_dimension_value": overall_value,
                        "anchors": [
                            {
                                "ref": str(min_edge.get("ref") or ""),
                                "pixel_extreme_side": "min",
                                "role": role_by_side["min"],
                                "position_px": float(min_edge["position_px"]),
                            },
                            {
                                "ref": str(max_edge.get("ref") or ""),
                                "pixel_extreme_side": "max",
                                "role": role_by_side["max"],
                                "position_px": float(max_edge["position_px"]),
                            },
                        ],
                        "basis": (
                            "independent_overall_dimension_plus_unique_profile_extremes"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                    }
                ]

    output: list[dict[str, Any]] = []
    for (region_id, axis), records in sorted(resolved_by_axis.items()):
        signatures = {
            tuple(
                sorted(
                    (str(anchor["ref"]), str(anchor["role"]))
                    for anchor in record["anchors"]
                )
            )
            for record in records
        }
        if len(signatures) == 1:
            selected = sorted(records, key=lambda item: str(item["candidate_id"]))[0]
            output.append(selected)
            continue

        output.append(
            {
                "status": "conflict",
                "region_id": region_id,
                "axis": axis,
                "candidate_ids": sorted(str(item["candidate_id"]) for item in records),
                "reason": "multiple_overall_dimensions_disagree_on_boundary_identity",
                "engineering_coordinate_inferred_from_pixels": False,
            }
        )

    return output


_PROFILE_ORIENTATION_BY_VIEW_AXIS: dict[tuple[str, str], str] = {
    ("front", "X"): "vertical",
    ("front", "Z"): "horizontal",
    ("side", "Y"): "vertical",
    ("side", "Z"): "horizontal",
    ("top", "X"): "vertical",
    ("top", "Y"): "horizontal",
}


def metricize_profile_edge_candidates(
    *,
    candidates: list[dict[str, Any]],
    calibrations: list[dict[str, Any]],
    profile_inventory: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert calibrated profile-edge coordinates without inventing geometry.

    When a complete structural profile inventory is available, it is the
    authoritative geometry-only source.  Older reports fall back to the
    dimension-witness nearest-anchor evidence.
    """

    calibration_lookup = {
        (str(item.get("region_id") or ""), str(item.get("axis") or "")): item
        for item in calibrations
        if isinstance(item, dict)
    }

    source_items: list[dict[str, Any]] = []
    source_scope = "dimension_witness_nearest_anchors"
    if isinstance(profile_inventory, list) and profile_inventory:
        source_scope = "full_structural_profile_inventory"
        source_items = [item for item in profile_inventory if isinstance(item, dict)]
    else:
        for candidate in candidates:
            region_id = str(candidate.get("region_id") or "")
            witness_evidence = candidate.get("witness_anchor_evidence", [])
            if not region_id or not isinstance(witness_evidence, list):
                continue
            for witness in witness_evidence:
                if not isinstance(witness, dict):
                    continue
                nearest = witness.get("nearest_anchors", [])
                if not isinstance(nearest, list):
                    continue
                for item in nearest:
                    if not isinstance(item, dict):
                        continue
                    source_items.append(
                        {
                            "region_id": region_id,
                            **item,
                        }
                    )

    output: dict[tuple[str, str], dict[str, Any]] = {}
    for item in source_items:
        if item.get("kind") != "profile_edge_candidate":
            continue
        region_id = str(item.get("region_id") or "")
        ref = str(item.get("ref") or "")
        source_orientation = str(item.get("source_orientation") or "")
        position_px = item.get("position_px")
        if not region_id or not ref or source_orientation not in {"horizontal", "vertical"}:
            continue
        if not isinstance(position_px, (int, float)):
            continue

        for (cal_region, axis), calibration in calibration_lookup.items():
            if cal_region != region_id:
                continue
            view_kind = str(calibration.get("view_kind") or "")
            expected_orientation = _PROFILE_ORIENTATION_BY_VIEW_AXIS.get((view_kind, axis))
            if expected_orientation != source_orientation:
                continue

            mm_per_px = calibration.get("mm_per_px")
            offset_mm = calibration.get("offset_mm")
            if not isinstance(mm_per_px, (int, float)) or not isinstance(
                offset_mm,
                (int, float),
            ):
                continue

            key = (ref, axis)
            output[key] = {
                "ref": ref,
                "region_id": region_id,
                "view_kind": view_kind,
                "axis": axis,
                "source_orientation": source_orientation,
                "position_px": float(position_px),
                "coordinate_mm": float(mm_per_px) * float(position_px) + float(offset_mm),
                "span_px": list(item.get("span_px", []))
                if isinstance(item.get("span_px"), list)
                else [],
                "calibration_candidate_id": calibration.get("candidate_id"),
                "basis": "view_metric_calibration",
                "source_scope": source_scope,
            }

    return sorted(
        output.values(),
        key=lambda item: (item["region_id"], item["axis"], item["ref"]),
    )


def _span_gap_px(value: float, span: Any) -> float | None:
    if not (
        isinstance(span, list)
        and len(span) == 2
        and all(isinstance(item, (int, float)) for item in span)
    ):
        return None
    low, high = sorted(float(item) for item in span)
    if low <= value <= high:
        return 0.0
    return low - value if value < low else value - high


def derive_metric_profile_segments(
    *,
    metric_edges: list[dict[str, Any]],
    junction_tolerance_by_region: dict[str, float] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Derive only junction-bounded metric segments from calibrated profile lines.

    Raw source-line span endpoints are evidence bounds, not physical endpoints.
    A segment is emitted only between two observed orthogonal metric profile
    intersections on the same source line.  Small pixel endpoint gaps may be
    tolerated only through an explicit, region-scoped tolerance supplied by the
    caller; missing geometry is never extended beyond that tolerance.
    """

    tolerance_lookup = junction_tolerance_by_region or {}
    edges = [
        item
        for item in metric_edges
        if isinstance(item, dict)
        and item.get("source_orientation") in {"horizontal", "vertical"}
        and isinstance(item.get("position_px"), (int, float))
        and isinstance(item.get("coordinate_mm"), (int, float))
        and isinstance(item.get("ref"), str)
        and item.get("ref")
    ]
    edges.sort(
        key=lambda item: (
            str(item.get("region_id") or ""),
            str(item.get("view_kind") or ""),
            str(item.get("source_orientation") or ""),
            str(item.get("ref") or ""),
        )
    )

    junctions: list[dict[str, Any]] = []
    junctions_by_edge: dict[str, list[dict[str, Any]]] = {str(item["ref"]): [] for item in edges}

    vertical_edges = [item for item in edges if item["source_orientation"] == "vertical"]
    horizontal_edges = [item for item in edges if item["source_orientation"] == "horizontal"]

    for vertical in vertical_edges:
        for horizontal in horizontal_edges:
            region_id = str(vertical.get("region_id") or "")
            if not region_id or region_id != str(horizontal.get("region_id") or ""):
                continue
            view_kind = str(vertical.get("view_kind") or "")
            if not view_kind or view_kind != str(horizontal.get("view_kind") or ""):
                continue
            if vertical.get("axis") == horizontal.get("axis"):
                continue

            x_px = float(vertical["position_px"])
            y_px = float(horizontal["position_px"])
            vertical_gap = _span_gap_px(y_px, vertical.get("span_px"))
            horizontal_gap = _span_gap_px(x_px, horizontal.get("span_px"))
            if vertical_gap is None or horizontal_gap is None:
                continue

            raw_tolerance = tolerance_lookup.get(region_id, 0.0)
            tolerance = (
                max(0.0, float(raw_tolerance)) if isinstance(raw_tolerance, (int, float)) else 0.0
            )
            max_gap = max(vertical_gap, horizontal_gap)
            if max_gap > tolerance:
                continue

            vertical_ref = str(vertical["ref"])
            horizontal_ref = str(horizontal["ref"])
            point_mm = {
                str(vertical["axis"]): float(vertical["coordinate_mm"]),
                str(horizontal["axis"]): float(horizontal["coordinate_mm"]),
            }
            if len(point_mm) != 2:
                continue

            junction = {
                "key": f"{vertical_ref}|{horizontal_ref}",
                "region_id": region_id,
                "view_kind": view_kind,
                "edge_refs": [vertical_ref, horizontal_ref],
                "point_px": [x_px, y_px],
                "point_mm": point_mm,
                "max_gap_px": max_gap,
                "junction_tolerance_px": tolerance,
                "basis": "orthogonal_metric_profile_intersection_within_tolerance",
            }
            junctions.append(junction)
            junctions_by_edge[vertical_ref].append(junction)
            junctions_by_edge[horizontal_ref].append(junction)

    junctions.sort(
        key=lambda item: (
            item["region_id"],
            item["view_kind"],
            item["edge_refs"][0],
            item["edge_refs"][1],
        )
    )

    segments: list[dict[str, Any]] = []
    unresolved_edges: list[dict[str, Any]] = []

    for edge in edges:
        ref = str(edge["ref"])
        orientation = str(edge["source_orientation"])
        edge_junctions = list(junctions_by_edge.get(ref, []))
        coordinate_index = 1 if orientation == "vertical" else 0
        edge_junctions.sort(key=lambda item: float(item["point_px"][coordinate_index]))

        if len(edge_junctions) < 2:
            unresolved_edges.append(
                {
                    "ref": ref,
                    "region_id": edge.get("region_id"),
                    "view_kind": edge.get("view_kind"),
                    "reason": "fewer_than_two_observed_metric_profile_junctions",
                    "junction_count": len(edge_junctions),
                    "basis": "fail_closed_segment_extent",
                }
            )
            continue

        fixed_axis = str(edge.get("axis") or "")
        for segment_index, (start, end) in enumerate(
            zip(edge_junctions, edge_junctions[1:], strict=False),
            start=1,
        ):
            start_mm = start["point_mm"]
            end_mm = end["point_mm"]
            varying_axes = (set(start_mm) & set(end_mm)) - {fixed_axis}
            if len(varying_axes) != 1:
                continue
            varying_axis = next(iter(varying_axes))
            start_value = start_mm.get(varying_axis)
            end_value = end_mm.get(varying_axis)
            if not isinstance(start_value, (int, float)) or not isinstance(end_value, (int, float)):
                continue
            length_mm = abs(float(end_value) - float(start_value))
            if length_mm <= 1e-9:
                continue

            segments.append(
                {
                    "key": f"{ref}.segment.{segment_index:03d}",
                    "region_id": edge.get("region_id"),
                    "view_kind": edge.get("view_kind"),
                    "source_edge_ref": ref,
                    "source_orientation": orientation,
                    "fixed_axis": fixed_axis,
                    "fixed_coordinate_mm": float(edge["coordinate_mm"]),
                    "varying_axis": varying_axis,
                    "start_mm": dict(start_mm),
                    "end_mm": dict(end_mm),
                    "length_mm": length_mm,
                    "junction_keys": [start["key"], end["key"]],
                    "basis": "observed_profile_line_between_metric_junctions",
                }
            )

    segments.sort(
        key=lambda item: (
            str(item.get("region_id") or ""),
            str(item.get("source_edge_ref") or ""),
            str(item.get("key") or ""),
        )
    )
    unresolved_edges.sort(key=lambda item: str(item.get("ref") or ""))
    return {
        "junctions": junctions,
        "segments": segments,
        "unresolved_edges": unresolved_edges,
    }


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
        if overall_value is None:
            continue

        calibration_basis = "overall_dimension_with_opposite_profile_extremes"
        endpoint_candidate = candidate
        supporting_local_token: str | None = None

        if dimension_value is None:
            conflict_probe = _conflict_backed_overall_probe(
                candidate,
                overall_value=overall_value,
                relative_tolerance=relative_tolerance,
            )
            if conflict_probe is None:
                continue
            endpoint_candidate, supporting_local_token = conflict_probe
            dimension_value = overall_value
            calibration_basis = (
                "overall_dimension_with_conflict_local_match_and_opposite_profile_extremes"
            )
        else:
            tolerance = max(abs(overall_value) * relative_tolerance, 1e-9)
            if abs(dimension_value - overall_value) > tolerance:
                continue

        endpoint_evidence = derive_dimension_endpoint_candidates(endpoint_candidate)
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
                "basis": calibration_basis,
                **(
                    {
                        "dimension_value_source": "overall_dimension_context",
                        "spatial_label_token": candidate.get("global_proposal_token"),
                        "supporting_local_token": supporting_local_token,
                        "ocr_conflict_preserved": True,
                    }
                    if supporting_local_token is not None
                    else {}
                ),
            }
        )

    return sorted(output, key=lambda item: (item["region_id"], item["axis"]))
