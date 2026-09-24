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
                lines[key] = {
                    "orientation": orientation,
                    "axis_px": float(axis),
                    "span_px": [start, end],
                    "span_length_px": end - start,
                }

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
        merged.append(
            {
                "orientation": group[0]["orientation"],
                "axis_px": round(axis, 3),
                "span_px": [start, end],
                "span_length_px": end - start,
                "merged_source_line_count": len(group),
            }
        )

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

        junction_count, endpoint_junction_count = _junction_metrics(
            line,
            all_lines,
            junction_tolerance=junction_tolerance,
        )
        span_local_norm = float(line["span_length_px"]) / span_denominator

        strong_topology = (
            span_local_norm >= 0.15 and junction_count >= 2 and endpoint_junction_count >= 1
        )
        long_single_corner = (
            span_local_norm >= 0.25 and junction_count >= 1 and endpoint_junction_count >= 1
        )
        if not (strong_topology or long_single_corner):
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
        is_extreme = at_minimum or at_maximum

        strong_extreme = (
            float(line["span_local_norm"]) >= 0.30 and int(line["endpoint_junction_count"]) >= 2
        ) or (
            float(line["span_local_norm"]) >= 0.75
            and int(line["junction_count"]) >= 3
            and int(line["endpoint_junction_count"]) >= 1
        )

        if is_extreme and strong_extreme:
            kind = "silhouette_extreme_candidate"
            extreme_side = "min" if at_minimum else "max"
        elif not is_extreme:
            kind = "step_or_shoulder_candidate"
            extreme_side = None
        else:
            kind = "profile_edge_candidate"
            extreme_side = None

        anchor = {
            "kind": kind,
            "ref": (f"{region_id}.structural.{source_orientation}.{index:03d}"),
            "position_px": round(axis, 3),
            "source_orientation": source_orientation,
            "span_px": list(line["span_px"]),
            "span_length_px": int(line["span_length_px"]),
            "span_local_norm": float(line["span_local_norm"]),
            "junction_count": int(line["junction_count"]),
            "endpoint_junction_count": int(line["endpoint_junction_count"]),
            "merged_source_line_count": int(line["merged_source_line_count"]),
            "candidate_only": True,
            "ownership_claimed": False,
        }
        if extreme_side is not None:
            anchor["extreme_side"] = extreme_side
        anchors.append(anchor)

    return anchors
