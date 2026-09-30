from __future__ import annotations

from typing import Any


def _region_lookup(raw_evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    regions = raw_evidence.get("regions", [])
    if not isinstance(regions, list):
        raise ValueError("regions must be a list")

    output: dict[str, dict[str, Any]] = {}
    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = region.get("region_id")
        if isinstance(region_id, str) and region_id:
            output[region_id] = region
    return output


def _collect_source_lines(
    raw_evidence: dict[str, Any],
    region_id: str,
) -> list[dict[str, Any]]:
    lines: dict[tuple[str, float, int, int], dict[str, Any]] = {}

    candidates = raw_evidence.get("dimension_geometry_candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("dimension_geometry_candidates must be a list")

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("region_id") != region_id:
            continue
        witnesses = candidate.get("witness_line_evidence", [])
        if not isinstance(witnesses, list):
            continue
        for witness in witnesses:
            if not isinstance(witness, dict):
                continue
            source_lines = witness.get("source_lines", [])
            if not isinstance(source_lines, list):
                continue
            for source in source_lines:
                if not isinstance(source, dict):
                    continue
                orientation = source.get("orientation")
                axis = source.get("axis_px")
                span = source.get("span_px")
                if orientation not in {"horizontal", "vertical"}:
                    continue
                if not isinstance(axis, (int, float)):
                    continue
                if not (
                    isinstance(span, list)
                    and len(span) == 2
                    and all(isinstance(value, (int, float)) for value in span)
                ):
                    continue
                start = int(round(float(span[0])))
                end = int(round(float(span[1])))
                if end <= start:
                    continue
                key = (
                    orientation,
                    round(float(axis), 3),
                    start,
                    end,
                )
                record = lines.setdefault(
                    key,
                    {
                        "orientation": orientation,
                        "axis_px": float(axis),
                        "span_px": [start, end],
                        "span_length_px": end - start,
                        "dimension_crossing_source_count": 0,
                        "non_dimension_crossing_source_count": 0,
                    },
                )
                if source.get("crosses_dimension_axis") is True:
                    record["dimension_crossing_source_count"] += 1
                elif source.get("crosses_dimension_axis") is False:
                    record["non_dimension_crossing_source_count"] += 1
                for field in ("axis_ink_fraction", "axis_ink_run_fraction"):
                    raw_value = source.get(field)
                    if (
                        isinstance(raw_value, (int, float))
                        and not isinstance(raw_value, bool)
                    ):
                        record[field] = max(
                            float(record.get(field, 0.0)),
                            float(raw_value),
                        )

    return sorted(
        lines.values(),
        key=lambda item: (
            str(item["orientation"]),
            float(item["axis_px"]),
            int(item["span_px"][0]),
            int(item["span_px"][1]),
        ),
    )


def _overlap_ratio(
    first: dict[str, Any],
    second: dict[str, Any],
) -> float:
    first_start, first_end = (int(value) for value in first["span_px"])
    second_start, second_end = (int(value) for value in second["span_px"])
    overlap = max(
        0,
        min(first_end, second_end) - max(first_start, second_start),
    )
    shorter = min(first_end - first_start, second_end - second_start)
    if shorter <= 0:
        return 0.0
    return overlap / shorter


def _merge_near_duplicate_lines(
    lines: list[dict[str, Any]],
    *,
    axis_tolerance: float,
    minimum_overlap_ratio: float,
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []

    for line in lines:
        placed = False
        for group in groups:
            if group[0]["orientation"] != line["orientation"]:
                continue
            total_weight = sum(max(1, int(item["span_length_px"])) for item in group)
            group_axis = (
                sum(float(item["axis_px"]) * max(1, int(item["span_length_px"])) for item in group)
                / total_weight
            )
            if abs(float(line["axis_px"]) - group_axis) > axis_tolerance:
                continue

            group_proxy = {
                "span_px": [
                    min(int(item["span_px"][0]) for item in group),
                    max(int(item["span_px"][1]) for item in group),
                ]
            }
            if _overlap_ratio(line, group_proxy) < minimum_overlap_ratio:
                continue

            group.append(line)
            placed = True
            break

        if not placed:
            groups.append([line])

    merged: list[dict[str, Any]] = []
    for group in groups:
        total_weight = sum(max(1, int(item["span_length_px"])) for item in group)
        axis = (
            sum(float(item["axis_px"]) * max(1, int(item["span_length_px"])) for item in group)
            / total_weight
        )
        start = min(int(item["span_px"][0]) for item in group)
        end = max(int(item["span_px"][1]) for item in group)
        merged_record = {
            "orientation": group[0]["orientation"],
            "axis_px": round(axis, 3),
            "span_px": [start, end],
            "span_length_px": end - start,
            "merged_source_line_count": len(group),
            "dimension_crossing_source_count": sum(
                int(item.get("dimension_crossing_source_count", 0))
                for item in group
            ),
            "non_dimension_crossing_source_count": sum(
                int(item.get("non_dimension_crossing_source_count", 0))
                for item in group
            ),
        }
        for field in ("axis_ink_fraction", "axis_ink_run_fraction"):
            values = [
                float(item[field])
                for item in group
                if (
                    isinstance(item.get(field), (int, float))
                    and not isinstance(item.get(field), bool)
                )
            ]
            if values:
                merged_record[field] = round(max(values), 5)
        merged.append(merged_record)

    merged.sort(
        key=lambda item: (
            str(item["orientation"]),
            float(item["axis_px"]),
            int(item["span_px"][0]),
            int(item["span_px"][1]),
        )
    )
    return merged


def _junction_metrics(
    line: dict[str, Any],
    lines: list[dict[str, Any]],
    *,
    junction_tolerance: float,
) -> tuple[int, int]:
    orientation = str(line["orientation"])
    axis = float(line["axis_px"])
    start, end = (float(value) for value in line["span_px"])

    junction_positions: list[float] = []
    endpoint_positions: list[float] = []

    for other in lines:
        if other is line or other["orientation"] == orientation:
            continue

        other_axis = float(other["axis_px"])
        other_start, other_end = (float(value) for value in other["span_px"])

        if orientation == "vertical":
            inside = (
                start - junction_tolerance <= other_axis <= end + junction_tolerance
                and other_start - junction_tolerance <= axis <= other_end + junction_tolerance
            )
            line_endpoint_distance = min(
                abs(other_axis - start),
                abs(other_axis - end),
            )
            other_endpoint_distance = min(
                abs(axis - other_start),
                abs(axis - other_end),
            )
            position = other_axis
        else:
            inside = (
                start - junction_tolerance <= other_axis <= end + junction_tolerance
                and other_start - junction_tolerance <= axis <= other_end + junction_tolerance
            )
            line_endpoint_distance = min(
                abs(other_axis - start),
                abs(other_axis - end),
            )
            other_endpoint_distance = min(
                abs(axis - other_start),
                abs(axis - other_end),
            )
            position = other_axis

        if not inside:
            continue

        junction_positions.append(position)
        if min(line_endpoint_distance, other_endpoint_distance) <= junction_tolerance:
            endpoint_positions.append(position)

    def distinct_count(values: list[float]) -> int:
        groups: list[list[float]] = []
        for value in sorted(values):
            if not groups or value - groups[-1][-1] > junction_tolerance:
                groups.append([value])
            else:
                groups[-1].append(value)
        return len(groups)

    return (
        distinct_count(junction_positions),
        distinct_count(endpoint_positions),
    )


def _is_circle_centerline(
    line: dict[str, Any],
    region: dict[str, Any],
    *,
    axis_tolerance: float,
) -> bool:
    """Reject structural lines that are explicit center axes through a circle."""

    orientation = str(line.get("orientation") or "")
    axis = line.get("axis_px")
    span = line.get("span_px")
    if not (
        orientation in {"horizontal", "vertical"}
        and isinstance(axis, (int, float))
        and isinstance(span, list)
        and len(span) == 2
        and all(isinstance(value, (int, float)) for value in span)
    ):
        return False

    start, end = sorted(float(value) for value in span)
    groups = region.get("circle_groups", [])
    if not isinstance(groups, list):
        return False

    for group in groups:
        if not isinstance(group, dict):
            continue
        center = group.get("center_px")
        if not (
            isinstance(center, list)
            and len(center) >= 2
            and isinstance(center[0], (int, float))
            and isinstance(center[1], (int, float))
        ):
            continue
        center_x = float(center[0])
        center_y = float(center[1])
        if orientation == "vertical":
            if abs(float(axis) - center_x) <= axis_tolerance and (
                start - axis_tolerance <= center_y <= end + axis_tolerance
            ):
                return True
        else:
            if abs(float(axis) - center_y) <= axis_tolerance and (
                start - axis_tolerance <= center_x <= end + axis_tolerance
            ):
                return True
    return False


def _is_hidden_pair_midline(
    line: dict[str, Any],
    region: dict[str, Any],
    *,
    axis_tolerance: float,
) -> bool:
    """Return whether one source line is the centerline of a dashed hidden pair."""

    patterns = region.get("linear_pattern_candidates", [])
    if not isinstance(patterns, list):
        return False

    orientation = str(line.get("orientation") or "")
    if orientation not in {"horizontal", "vertical"}:
        return False
    line_axis = float(line["axis_px"])
    line_span = line.get("span_px", [])
    if not (isinstance(line_span, list) and len(line_span) == 2):
        return False

    bbox = region.get("bbox_px", [])
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(value, (int, float)) for value in bbox)
    ):
        return False

    axis_extent = float(bbox[3] if orientation == "horizontal" else bbox[2])
    minimum_pair_separation = max(4.0, axis_extent * 0.008)
    maximum_pair_separation = axis_extent * 0.25

    eligible = [
        item
        for item in patterns
        if isinstance(item, dict)
        and str(item.get("orientation") or "") == orientation
        and isinstance(item.get("axis_px"), (int, float))
        and isinstance(item.get("span_px"), list)
        and len(item["span_px"]) == 2
        and (
            not isinstance(item.get("dash_score"), (int, float))
            or isinstance(item.get("dash_score"), bool)
            or float(item["dash_score"]) >= 0.60
        )
    ]

    for left_index in range(len(eligible)):
        first = eligible[left_index]
        first_axis = float(first["axis_px"])
        for right_index in range(left_index + 1, len(eligible)):
            second = eligible[right_index]
            second_axis = float(second["axis_px"])
            separation = abs(second_axis - first_axis)
            if (
                separation < minimum_pair_separation
                or separation > maximum_pair_separation
            ):
                continue
            if _overlap_ratio(first, second) < 0.75:
                continue

            midpoint = (first_axis + second_axis) / 2.0
            midpoint_tolerance = min(
                axis_tolerance,
                max(1.0, separation * 0.25),
            )
            if abs(midpoint - line_axis) > midpoint_tolerance:
                continue
            if _overlap_ratio(line, first) < 0.40:
                continue
            if _overlap_ratio(line, second) < 0.40:
                continue
            return True

    return False


def derive_structural_profile_anchors(
    raw_evidence: dict[str, Any],
    region_id: str,
    dimension_orientation: str,
) -> list[dict[str, Any]]:
    """Derive geometry-only physical-profile candidates for one view.

    These anchors are deliberately candidate-only.  They do not claim
    engineering ownership and must not by themselves close a dimension
    endpoint.
    """

    regions = _region_lookup(raw_evidence)
    region = regions.get(region_id)
    if region is None:
        raise ValueError(f"unknown region_id: {region_id!r}")

    bbox = region.get("bbox_px")
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(value, (int, float)) for value in bbox)
    ):
        raise ValueError("region bbox_px must contain four numeric values")

    image = raw_evidence.get("image", {})
    image_width = image.get("width")
    if not isinstance(image_width, (int, float)) or image_width <= 0:
        image_width = float(bbox[2])

    axis_tolerance = max(2.0, round(float(image_width) * 0.003))
    junction_tolerance = max(
        5.0,
        round(float(image_width) * 0.0075),
    )

    if dimension_orientation == "horizontal":
        source_orientation = "vertical"
    elif dimension_orientation == "vertical":
        source_orientation = "horizontal"
    else:
        raise ValueError("dimension_orientation must be horizontal or vertical")

    all_lines = _merge_near_duplicate_lines(
        _collect_source_lines(raw_evidence, region_id),
        axis_tolerance=axis_tolerance,
        minimum_overlap_ratio=0.8,
    )

    _, _, region_width, region_height = (float(value) for value in bbox)
    span_denominator = region_height if source_orientation == "vertical" else region_width
    if span_denominator <= 0:
        raise ValueError("region span must be positive")

    profile_lines: list[dict[str, Any]] = []
    for line in all_lines:
        if line["orientation"] != source_orientation:
            continue
        if _is_circle_centerline(
            line,
            region,
            axis_tolerance=axis_tolerance,
        ):
            continue
        if _is_hidden_pair_midline(
            line,
            region,
            axis_tolerance=axis_tolerance,
        ):
            continue

        junction_count, endpoint_junction_count = _junction_metrics(
            line,
            all_lines,
            junction_tolerance=junction_tolerance,
        )
        span_local_norm = float(line["span_length_px"]) / span_denominator

        strong_topology = span_local_norm >= 0.15 and junction_count >= 2
        short_closed_edge = (
            span_local_norm >= 0.10
            and junction_count >= 2
            and endpoint_junction_count >= 2
        )
        independent_profile_source = (
            int(line.get("non_dimension_crossing_source_count", 0)) > 0
        )
        long_single_corner = (
            span_local_norm >= 0.25
            and junction_count >= 1
            and endpoint_junction_count >= 1
            and independent_profile_source
        )
        if not (strong_topology or short_closed_edge or long_single_corner):
            continue

        profile_lines.append(
            {
                **line,
                "span_local_norm": round(span_local_norm, 5),
                "junction_count": junction_count,
                "endpoint_junction_count": endpoint_junction_count,
            }
        )

    if not profile_lines:
        return []

    minimum_axis = min(float(item["axis_px"]) for item in profile_lines)
    maximum_axis = max(float(item["axis_px"]) for item in profile_lines)

    anchors: list[dict[str, Any]] = []
    for index, line in enumerate(profile_lines, start=1):
        axis = float(line["axis_px"])
        at_minimum = abs(axis - minimum_axis) <= axis_tolerance
        at_maximum = abs(axis - maximum_axis) <= axis_tolerance

        anchor = {
            "kind": "profile_edge_candidate",
            "ref": (f"{region_id}.structural.{source_orientation}.{index:03d}"),
            "position_px": round(axis, 3),
            "source_orientation": source_orientation,
            "span_px": list(line["span_px"]),
            "span_length_px": int(line["span_length_px"]),
            "span_local_norm": float(line["span_local_norm"]),
            "junction_count": int(line["junction_count"]),
            "endpoint_junction_count": int(line["endpoint_junction_count"]),
            "merged_source_line_count": int(line["merged_source_line_count"]),
            "axis_tolerance_px": float(axis_tolerance),
            "junction_tolerance_px": float(junction_tolerance),
            "dimension_crossing_source_count": int(
                line.get("dimension_crossing_source_count", 0)
            ),
            "non_dimension_crossing_source_count": int(
                line.get("non_dimension_crossing_source_count", 0)
            ),
            "candidate_only": True,
            "ownership_claimed": False,
        }
        if at_minimum:
            anchor["relative_extreme_side"] = "min"
        elif at_maximum:
            anchor["relative_extreme_side"] = "max"
        anchors.append(anchor)

    return anchors


def derive_structural_profile_vertex_anchors(
    raw_evidence: dict[str, Any],
    region_id: str,
    dimension_orientation: str,
) -> list[dict[str, Any]]:
    """Derive profile vertices that can own dimension extension-line endpoints.

    A vertex is emitted only from an independently supported structural profile
    edge whose two endpoints participate in structural junctions. Raster
    coordinates prove physical contact/identity only; they are never converted
    into engineering coordinates.
    """

    if dimension_orientation == "horizontal":
        supporting_dimension_orientation = "vertical"
    elif dimension_orientation == "vertical":
        supporting_dimension_orientation = "horizontal"
    else:
        raise ValueError("dimension_orientation must be horizontal or vertical")

    supporting_edges = derive_structural_profile_anchors(
        raw_evidence,
        region_id,
        supporting_dimension_orientation,
    )

    anchors: list[dict[str, Any]] = []
    for edge in supporting_edges:
        span = edge.get("span_px")
        transverse = edge.get("position_px")
        endpoint_junction_count = edge.get("endpoint_junction_count")
        independent_source_count = edge.get(
            "non_dimension_crossing_source_count"
        )
        axis_tolerance = edge.get("axis_tolerance_px")
        junction_tolerance = edge.get("junction_tolerance_px")
        ref = str(edge.get("ref") or "")
        if (
            edge.get("kind") != "profile_edge_candidate"
            or not ref
            or not isinstance(span, list)
            or len(span) != 2
            or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in span
            )
            or not isinstance(transverse, (int, float))
            or isinstance(transverse, bool)
            or not isinstance(endpoint_junction_count, int)
            or isinstance(endpoint_junction_count, bool)
            or endpoint_junction_count < 2
            or not isinstance(independent_source_count, int)
            or isinstance(independent_source_count, bool)
            or independent_source_count <= 0
            or not isinstance(axis_tolerance, (int, float))
            or isinstance(axis_tolerance, bool)
            or not isinstance(junction_tolerance, (int, float))
            or isinstance(junction_tolerance, bool)
        ):
            continue

        low, high = sorted(float(value) for value in span)
        if high <= low:
            continue
        match_tolerance = max(
            float(axis_tolerance),
            min(float(junction_tolerance) * 0.5, 6.0),
        )
        for endpoint_side, endpoint_position in (
            ("min", low),
            ("max", high),
        ):
            anchors.append(
                {
                    "kind": "profile_vertex_candidate",
                    "ref": f"{ref}.vertex.{endpoint_side}",
                    "position_px": round(endpoint_position, 3),
                    "vertex_transverse_px": round(float(transverse), 3),
                    "supporting_profile_ref": ref,
                    "supporting_profile_orientation": edge.get(
                        "source_orientation"
                    ),
                    "endpoint_side": endpoint_side,
                    "profile_span_px": [low, high],
                    "axis_tolerance_px": float(axis_tolerance),
                    "junction_tolerance_px": float(junction_tolerance),
                    "vertex_match_tolerance_px": round(match_tolerance, 3),
                    "junction_count": int(edge.get("junction_count", 0)),
                    "endpoint_junction_count": endpoint_junction_count,
                    "non_dimension_crossing_source_count": (
                        independent_source_count
                    ),
                    "candidate_only": True,
                    "ownership_claimed": False,
                }
            )

    return anchors
