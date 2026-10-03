from __future__ import annotations

from typing import Any


_AXIS_BY_VIEW_ORIENTATION: dict[tuple[str, str], str] = {
    ("front", "horizontal"): "X",
    ("front", "vertical"): "Z",
    ("side", "horizontal"): "Y",
    ("side", "vertical"): "Z",
    ("top", "horizontal"): "X",
    ("top", "vertical"): "Y",
}


def _span_overlap_ratio(
    first: list[Any],
    second: list[Any],
) -> float:
    if not (
        len(first) == 2
        and len(second) == 2
        and all(isinstance(value, (int, float)) for value in [*first, *second])
    ):
        return 0.0
    first_start, first_end = sorted(float(value) for value in first)
    second_start, second_end = sorted(float(value) for value in second)
    overlap = max(
        0.0,
        min(first_end, second_end) - max(first_start, second_start),
    )
    shorter = min(first_end - first_start, second_end - second_start)
    return overlap / shorter if shorter > 0 else 0.0


def derive_hidden_projection_center_candidates(
    candidate: dict[str, Any],
    *,
    region: dict[str, Any],
    view_kind: str,
    profile_inventory: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Derive center candidates from symmetric hidden/dashed line pairs.

    The pair geometry only proposes a feature center.  It never overrides a
    competing physical endpoint owner; Adapter/Confirmation remains responsible
    for ownership.
    """

    region_id = str(candidate.get("region_id") or "")
    if region_id != str(region.get("region_id") or "") or not region_id:
        return []

    dimension_orientation = str(candidate.get("orientation") or "")
    if dimension_orientation == "horizontal":
        pattern_orientation = "vertical"
    elif dimension_orientation == "vertical":
        pattern_orientation = "horizontal"
    else:
        return []

    feature_axis = _AXIS_BY_VIEW_ORIENTATION.get(
        (view_kind, pattern_orientation)
    )
    if feature_axis is None:
        return []

    bbox = region.get("bbox_px")
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(value, (int, float)) for value in bbox)
    ):
        return []

    witness_positions = [
        float(value)
        for value in candidate.get("witness_positions_px", [])
        if isinstance(value, (int, float))
    ]
    if not witness_positions:
        return []

    span_extent = (
        float(bbox[2])
        if dimension_orientation == "horizontal"
        else float(bbox[3])
    )
    if span_extent <= 0:
        return []

    midpoint_tolerance = max(3.0, span_extent * 0.01)
    maximum_pair_separation = span_extent * 0.18
    minimum_pair_separation = max(4.0, span_extent * 0.008)
    profile_axis_tolerance = 2.0
    profile_items = profile_inventory or []

    patterns = region.get("linear_pattern_candidates", [])
    if not isinstance(patterns, list):
        return []

    eligible: list[tuple[int, dict[str, Any]]] = []
    for pattern_index, pattern in enumerate(patterns):
        if not isinstance(pattern, dict):
            continue
        if str(pattern.get("orientation") or "") != pattern_orientation:
            continue
        axis = pattern.get("axis_px")
        span = pattern.get("span_px")
        if not (
            isinstance(axis, (int, float))
            and isinstance(span, list)
            and len(span) == 2
        ):
            continue

        overlaps_profile = any(
            isinstance(item, dict)
            and str(item.get("region_id") or "") == region_id
            and str(item.get("source_orientation") or "") == pattern_orientation
            and isinstance(item.get("position_px"), (int, float))
            and abs(float(item["position_px"]) - float(axis))
            <= profile_axis_tolerance
            for item in profile_items
        )
        if overlaps_profile:
            continue
        eligible.append((pattern_index, pattern))

    output: list[dict[str, Any]] = []
    for witness_index, witness_position in enumerate(witness_positions):
        matches: list[dict[str, Any]] = []
        for left_index in range(len(eligible)):
            first_pattern_index, first = eligible[left_index]
            first_axis = float(first["axis_px"])
            for right_index in range(left_index + 1, len(eligible)):
                second_pattern_index, second = eligible[right_index]
                second_axis = float(second["axis_px"])
                separation = abs(second_axis - first_axis)
                if (
                    separation < minimum_pair_separation
                    or separation > maximum_pair_separation
                ):
                    continue
                overlap_ratio = _span_overlap_ratio(
                    first.get("span_px", []),
                    second.get("span_px", []),
                )
                if overlap_ratio < 0.75:
                    continue
                midpoint = (first_axis + second_axis) / 2.0
                residual = abs(midpoint - witness_position)
                if residual > midpoint_tolerance:
                    continue

                low_index, high_index = sorted(
                    (first_pattern_index, second_pattern_index)
                )
                entity_key = (
                    f"{region_id}.HIDDEN_PAIR."
                    f"{pattern_orientation}."
                    f"{low_index + 1:03d}.{high_index + 1:03d}"
                )
                matches.append(
                    {
                        "kind": "hidden_projection_center_axis",
                        "entity_key": entity_key,
                        "ref": f"{entity_key}.center",
                        "position_px": midpoint,
                        "feature_axis": feature_axis,
                        "pattern_orientation": pattern_orientation,
                        "source_pattern_indices": [
                            low_index,
                            high_index,
                        ],
                        "source_pattern_axes_px": [
                            first_axis,
                            second_axis,
                        ],
                        "pair_separation_px": separation,
                        "span_overlap_ratio": round(overlap_ratio, 5),
                        "witness_midpoint_residual_px": round(residual, 3),
                        "candidate_only": True,
                        "ownership_claimed": False,
                    }
                )

        matches.sort(
            key=lambda item: (
                float(item["witness_midpoint_residual_px"]),
                -float(item["span_overlap_ratio"]),
                str(item["entity_key"]),
            )
        )
        if not matches:
            continue

        best = matches[0]
        maximum_residual = max(2.0, midpoint_tolerance * 0.50)
        if float(best["witness_midpoint_residual_px"]) > maximum_residual:
            continue

        uniqueness_margin = max(3.0, midpoint_tolerance * 0.25)
        if len(matches) > 1:
            margin = (
                float(matches[1]["witness_midpoint_residual_px"])
                - float(best["witness_midpoint_residual_px"])
            )
            if margin < uniqueness_margin:
                continue
        else:
            margin = None

        output.append(
            {
                "witness_index": witness_index,
                **best,
                "selection_basis": "unique_best_hidden_projection_pair",
                "selection_margin_px": (
                    round(margin, 3) if margin is not None else None
                ),
            }
        )

    return output
