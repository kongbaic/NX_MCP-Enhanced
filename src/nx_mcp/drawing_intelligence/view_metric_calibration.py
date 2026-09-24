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
) -> list[dict[str, Any]]:
    """Convert only the calibrated coordinate of observed profile-edge candidates.

    This is deliberately partial.  A vertical edge in a front view can receive
    an X coordinate from an X calibration while its Y-pixel span remains
    unconverted until a Z calibration exists.  No segment endpoints or missing
    coordinates are invented.
    """

    calibration_lookup = {
        (str(item.get("region_id") or ""), str(item.get("axis") or "")): item
        for item in calibrations
        if isinstance(item, dict)
    }
    output: dict[tuple[str, str], dict[str, Any]] = {}

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
                if not isinstance(item, dict) or item.get("kind") != "profile_edge_candidate":
                    continue
                ref = str(item.get("ref") or "")
                source_orientation = str(item.get("source_orientation") or "")
                position_px = item.get("position_px")
                if not ref or source_orientation not in {"horizontal", "vertical"}:
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
                        offset_mm, (int, float)
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
                    }

    return sorted(
        output.values(),
        key=lambda item: (item["region_id"], item["axis"], item["ref"]),
    )


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
