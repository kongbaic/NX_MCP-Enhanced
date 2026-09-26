from __future__ import annotations

from typing import Any

_PIXEL_INDEX_BY_VIEW_AXIS: dict[tuple[str, str], int] = {
    ("front", "X"): 0,
    ("front", "Z"): 1,
    ("side", "Y"): 0,
    ("side", "Z"): 1,
    ("top", "X"): 0,
    ("top", "Y"): 1,
}

_LINE_ORIENTATION_BY_VIEW_AXIS: dict[tuple[str, str], str] = {
    ("front", "X"): "vertical",
    ("front", "Z"): "horizontal",
    ("side", "Y"): "vertical",
    ("side", "Z"): "horizontal",
    ("top", "X"): "vertical",
    ("top", "Y"): "horizontal",
}


def derive_circle_overall_center_alignments(
    *,
    regions: list[dict[str, Any]],
    region_views: dict[str, str],
    boundaries: list[dict[str, Any]],
    profile_inventory: list[dict[str, Any]],
    candidates: list[dict[str, Any]] | None = None,
    relative_tolerance: float = 0.012,
) -> list[dict[str, Any]]:
    """Identify circle centers coincident with an overall center datum.

    Pixel positions are used only for coincidence/topology: a circle center must
    lie on one unique observed axis line that also lies at the midpoint between
    two independently identified overall boundaries. No engineering coordinate
    is interpolated from pixel distance.
    """

    regions_by_id = {
        str(region.get("region_id") or ""): region
        for region in regions
        if isinstance(region, dict) and region.get("region_id")
    }
    output: list[dict[str, Any]] = []

    for boundary in boundaries:
        if not isinstance(boundary, dict) or boundary.get("status") != "resolved":
            continue
        region_id = str(boundary.get("region_id") or "")
        axis = str(boundary.get("axis") or "")
        view_kind = region_views.get(region_id)
        if axis not in {"X", "Y"} or view_kind is None:
            continue

        pixel_index = _PIXEL_INDEX_BY_VIEW_AXIS.get((view_kind, axis))
        line_orientation = _LINE_ORIENTATION_BY_VIEW_AXIS.get((view_kind, axis))
        if pixel_index is None or line_orientation is None:
            continue

        anchors = boundary.get("anchors", [])
        if not (
            isinstance(anchors, list)
            and len(anchors) == 2
            and all(isinstance(item, dict) for item in anchors)
        ):
            continue
        if boundary.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        positions = [
            item.get("position_px") for item in anchors
        ]
        if not all(isinstance(value, (int, float)) for value in positions):
            continue
        low, high = sorted(float(value) for value in positions)
        span = high - low
        if span <= 1e-9:
            continue
        midpoint = (low + high) / 2.0
        tolerance = max(2.0, span * relative_tolerance)

        region = regions_by_id.get(region_id)
        if region is None:
            continue
        groups = region.get("circle_groups", [])
        if not isinstance(groups, list):
            continue

        axis_lines = [
            item
            for item in profile_inventory
            if isinstance(item, dict)
            and str(item.get("region_id") or "") == region_id
            and str(item.get("source_orientation") or "") == line_orientation
            and isinstance(item.get("position_px"), (int, float))
            and abs(float(item["position_px"]) - midpoint) <= tolerance
        ]

        for group in groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("circle_group_id") or "")
            center = group.get("center_px")
            if not (
                group_id
                and isinstance(center, list)
                and len(center) >= 2
                and isinstance(center[0], (int, float))
                and isinstance(center[1], (int, float))
            ):
                continue

            center_axis_px = float(center[pixel_index])
            if abs(center_axis_px - midpoint) > tolerance:
                continue
            orthogonal_index = 1 - pixel_index
            center_cross_px = float(center[orthogonal_index])

            supporting_lines: list[dict[str, Any]] = []
            for line in axis_lines:
                position = float(line["position_px"])
                if abs(position - center_axis_px) > tolerance:
                    continue
                line_span = line.get("span_px")
                if not (
                    isinstance(line_span, list)
                    and len(line_span) == 2
                    and all(
                        isinstance(value, (int, float))
                        for value in line_span
                    )
                ):
                    continue
                start, end = sorted(float(value) for value in line_span)
                if start - tolerance <= center_cross_px <= end + tolerance:
                    supporting_lines.append(
                        {
                            **line,
                            "support_kind": "profile_inventory_axis",
                        }
                    )

            center_ref = (
                f"{region_id}.{group_id}.center_"
                f"{'x' if pixel_index == 0 else 'y'}"
            )
            for candidate in candidates or []:
                if (
                    not isinstance(candidate, dict)
                    or str(candidate.get("region_id") or "") != region_id
                ):
                    continue

                witness_lines_by_index = {
                    item.get("witness_index"): item
                    for item in candidate.get("witness_line_evidence", [])
                    if isinstance(item, dict)
                    and isinstance(item.get("witness_index"), int)
                }
                for anchor_record in candidate.get("witness_anchor_evidence", []):
                    if not (
                        isinstance(anchor_record, dict)
                        and isinstance(anchor_record.get("witness_index"), int)
                    ):
                        continue
                    witness_index = anchor_record["witness_index"]
                    has_circle_center_anchor = any(
                        isinstance(anchor, dict)
                        and anchor.get("kind") == "circle_center_axis"
                        and str(anchor.get("ref") or "") == center_ref
                        for anchor in anchor_record.get("nearest_anchors", [])
                    )
                    if not has_circle_center_anchor:
                        continue

                    witness_record = witness_lines_by_index.get(witness_index)
                    if not isinstance(witness_record, dict):
                        continue
                    for line_index, line in enumerate(
                        witness_record.get("source_lines", [])
                    ):
                        if (
                            not isinstance(line, dict)
                            or str(line.get("orientation") or "")
                            != line_orientation
                            or not isinstance(line.get("axis_px"), (int, float))
                        ):
                            continue
                        position = float(line["axis_px"])
                        if abs(position - center_axis_px) > tolerance:
                            continue
                        line_span = line.get("span_px")
                        if not (
                            isinstance(line_span, list)
                            and len(line_span) == 2
                            and all(
                                isinstance(value, (int, float))
                                for value in line_span
                            )
                        ):
                            continue
                        start, end = sorted(float(value) for value in line_span)
                        if not (
                            start - tolerance
                            <= center_cross_px
                            <= end + tolerance
                        ):
                            continue
                        supporting_lines.append(
                            {
                                "ref": (
                                    f"{candidate.get('candidate_id')}"
                                    f".witness.{witness_index}.line.{line_index}"
                                ),
                                "position_px": position,
                                "span_px": [start, end],
                                "support_kind": (
                                    "circle_center_anchored_witness_axis"
                                ),
                                "candidate_id": candidate.get("candidate_id"),
                                "witness_index": witness_index,
                            }
                        )

            deduplicated_support: dict[
                tuple[float, float, float],
                dict[str, Any],
            ] = {}
            for line in supporting_lines:
                span_values = line.get("span_px")
                if not (
                    isinstance(span_values, list)
                    and len(span_values) == 2
                ):
                    continue
                key = (
                    round(float(line["position_px"]), 1),
                    round(float(span_values[0]), 1),
                    round(float(span_values[1]), 1),
                )
                deduplicated_support.setdefault(key, line)
            supporting_lines = list(deduplicated_support.values())

            if len(supporting_lines) != 1:
                continue

            support = supporting_lines[0]
            output.append(
                {
                    "entity_key": f"{region_id}.{group_id}",
                    "region_id": region_id,
                    "view_kind": view_kind,
                    "axis": axis,
                    "datum": "overall_center",
                    "overall_boundary_candidate_id": boundary.get("candidate_id"),
                    "overall_boundary_refs": [
                        str(item.get("ref") or "") for item in anchors
                    ],
                    "axis_line_ref": str(support.get("ref") or ""),
                    "axis_line_position_px": float(support["position_px"]),
                    "axis_line_support_kind": support.get("support_kind"),
                    "axis_line_candidate_id": support.get("candidate_id"),
                    "overall_midpoint_px": midpoint,
                    "circle_center_axis_px": center_axis_px,
                    "coincidence_tolerance_px": tolerance,
                    "engineering_coordinate_inferred_from_pixels": False,
                    "basis": (
                        "overall_boundaries_plus_unique_center_axis_line"
                        "_through_circle_center"
                    ),
                }
            )

    output.sort(
        key=lambda item: (
            item["region_id"],
            item["axis"],
            item["entity_key"],
        )
    )
    return output
