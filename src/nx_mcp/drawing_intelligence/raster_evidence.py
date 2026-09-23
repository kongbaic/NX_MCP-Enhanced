from __future__ import annotations

import math
from importlib import import_module
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

_BASE_REFERENCE_WIDTH = 1774
_FRAGMENT_MIN_RATIO = 10.0 / _BASE_REFERENCE_WIDTH
_FRAGMENT_MAX_RATIO = 90.0 / _BASE_REFERENCE_WIDTH


def fragment_length_limits(image_width: int) -> tuple[int, int]:
    """Scale the historically validated 10..90px fragment window by image width."""

    if image_width <= 0:
        raise ValueError("image_width must be positive")
    minimum = max(4, int(round(image_width * _FRAGMENT_MIN_RATIO)))
    maximum = max(minimum + 1, int(round(image_width * _FRAGMENT_MAX_RATIO)))
    return minimum, maximum


def _load_cv_modules() -> tuple[Any, Any]:
    try:
        cv2 = import_module("cv2")
        np = import_module("numpy")
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Raster drawing evidence requires the optional drawing dependencies. "
            'Install the package with: pip install -e ".[drawing]"'
        ) from exc
    return cv2, np


def _norm(value: float, denominator: float) -> float:
    return round(value / denominator, 5)


def _edge_support(
    edges: Any,
    cx: int,
    cy: int,
    radius: int,
    *,
    tol: int = 2,
) -> float:
    h, w = edges.shape
    hits = 0
    samples = 180
    for index in range(samples):
        theta = 2.0 * math.pi * index / samples
        x = int(round(cx + radius * math.cos(theta)))
        y = int(round(cy + radius * math.sin(theta)))
        found = False
        for dy in range(-tol, tol + 1):
            for dx in range(-tol, tol + 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h and edges[yy, xx] != 0:
                    found = True
                    break
            if found:
                break
        hits += int(found)
    return hits / samples


def _axis_lines(edges: Any, cv2: Any, np: Any) -> list[dict[str, Any]]:
    raw = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=80,
        minLineLength=35,
        maxLineGap=8,
    )
    result: list[dict[str, Any]] = []
    if raw is None:
        return result

    for x1, y1, x2, y2 in raw[:, 0]:
        dx, dy = int(x2 - x1), int(y2 - y1)
        length = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx))
        if abs(angle) <= 3 or abs(abs(angle) - 180) <= 3:
            orientation = "horizontal"
        elif abs(abs(angle) - 90) <= 3:
            orientation = "vertical"
        else:
            continue
        result.append(
            {
                "orientation": orientation,
                "x1": int(x1),
                "y1": int(y1),
                "x2": int(x2),
                "y2": int(y2),
                "length_px": round(length, 2),
            }
        )
    return result


def _view_regions(
    shape: tuple[int, int],
    axis_lines: list[dict[str, Any]],
    cv2: Any,
    np: Any,
) -> list[dict[str, int]]:
    h, w = shape
    mask = np.zeros((h, w), dtype=np.uint8)
    for line in axis_lines:
        if float(line["length_px"]) < 100:
            continue
        cv2.line(
            mask,
            (int(line["x1"]), int(line["y1"])),
            (int(line["x2"]), int(line["y2"])),
            255,
            3,
        )

    close_size = max(9, int(round(min(h, w) * 0.024)))
    if close_size % 2 == 0:
        close_size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size))
    connected = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(
        connected,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    min_area = h * w * 0.01
    boxes: list[dict[str, int]] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width * height < min_area:
            continue
        boxes.append(
            {
                "x": int(x),
                "y": int(y),
                "width": int(width),
                "height": int(height),
                "area": int(width * height),
            }
        )
    boxes.sort(key=lambda item: item["area"], reverse=True)
    return boxes[:4]


def _circle_candidates(
    gray: Any,
    edges: Any,
    region: dict[str, int],
    cv2: Any,
) -> list[dict[str, Any]]:
    x = region["x"]
    y = region["y"]
    width = region["width"]
    height = region["height"]
    roi = gray[y : y + height, x : x + width]
    max_radius = max(12, min(120, min(width, height) // 2))

    circles = cv2.HoughCircles(
        roi,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(18, min(width, height) // 12),
        param1=120,
        param2=45,
        minRadius=8,
        maxRadius=max_radius,
    )
    if circles is None:
        return []

    scored: list[dict[str, Any]] = []
    for raw_circle in circles[0]:
        cx, cy, radius = (int(round(float(value))) for value in raw_circle)
        global_x, global_y = x + cx, y + cy
        support = _edge_support(edges, global_x, global_y, radius)
        if support < 0.82:
            continue
        scored.append(
            {
                "cx": global_x,
                "cy": global_y,
                "radius_px": radius,
                "edge_support": round(float(support), 3),
            }
        )

    scored.sort(key=lambda item: float(item["edge_support"]), reverse=True)
    centers: list[dict[str, Any]] = []
    min_center_dist = max(12, min(width, height) * 0.08)
    for item in scored:
        if any(
            math.hypot(
                int(item["cx"]) - int(previous["cx"]),
                int(item["cy"]) - int(previous["cy"]),
            )
            < min_center_dist
            for previous in centers
        ):
            continue
        centers.append(item)
        if len(centers) >= 4:
            break

    enriched: list[dict[str, Any]] = []
    for center in centers:
        cx, cy = int(center["cx"]), int(center["cy"])
        radial: list[tuple[float, int]] = []
        for radius in range(8, max_radius + 1):
            support = _edge_support(edges, cx, cy, radius, tol=1)
            if support >= 0.90:
                radial.append((support, radius))

        peaks: list[tuple[float, int]] = []
        for support, radius in sorted(radial, key=lambda pair: pair[1]):
            if peaks and radius - peaks[-1][1] <= 3:
                if support > peaks[-1][0]:
                    peaks[-1] = (support, radius)
            else:
                peaks.append((support, radius))

        for support, radius in peaks:
            enriched.append(
                {
                    "cx": cx,
                    "cy": cy,
                    "radius_px": radius,
                    "edge_support": round(float(support), 3),
                }
            )
    return enriched


def _fragment_groups(
    edges: Any,
    region: dict[str, int],
    image_width: int,
    cv2: Any,
    np: Any,
) -> list[dict[str, Any]]:
    raw = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=25,
        minLineLength=12,
        maxLineGap=2,
    )
    if raw is None:
        return []

    min_fragment_length, max_fragment_length = fragment_length_limits(image_width)
    x0 = region["x"]
    y0 = region["y"]
    width = region["width"]
    height = region["height"]
    fragments: list[tuple[str, float, int, int]] = []

    for x1, y1, x2, y2 in raw[:, 0]:
        midpoint_x, midpoint_y = (x1 + x2) / 2, (y1 + y2) / 2
        if not (
            x0 <= midpoint_x <= x0 + width
            and y0 <= midpoint_y <= y0 + height
        ):
            continue
        dx, dy = int(x2 - x1), int(y2 - y1)
        length = math.hypot(dx, dy)
        if not min_fragment_length <= length <= max_fragment_length:
            continue

        angle = math.degrees(math.atan2(dy, dx))
        if abs(angle) <= 2.5 or abs(abs(angle) - 180) <= 2.5:
            fragments.append(
                (
                    "horizontal",
                    float((int(y1) + int(y2)) / 2),
                    int(min(x1, x2)),
                    int(max(x1, x2)),
                )
            )
        elif abs(abs(angle) - 90) <= 2.5:
            fragments.append(
                (
                    "vertical",
                    float((int(x1) + int(x2)) / 2),
                    int(min(y1, y2)),
                    int(max(y1, y2)),
                )
            )

    groups: list[dict[str, Any]] = []
    for orientation in ("horizontal", "vertical"):
        items = sorted(
            (item for item in fragments if item[0] == orientation),
            key=lambda item: item[1],
        )
        buckets: list[list[tuple[str, float, int, int]]] = []
        for item in items:
            if (
                not buckets
                or abs(item[1] - mean(part[1] for part in buckets[-1])) > 3
            ):
                buckets.append([item])
            else:
                buckets[-1].append(item)

        for bucket in buckets:
            intervals: list[list[int]] = []
            for _, _, start, end in bucket:
                duplicate = False
                for old in intervals:
                    overlap = min(end, old[1]) - max(start, old[0])
                    if overlap > 0.6 * min(
                        end - start,
                        old[1] - old[0],
                    ):
                        old[0] = min(old[0], start)
                        old[1] = max(old[1], end)
                        duplicate = True
                        break
                if not duplicate:
                    intervals.append([int(start), int(end)])

            intervals.sort()
            if len(intervals) < 3:
                continue
            gaps = [
                intervals[index + 1][0] - intervals[index][1]
                for index in range(len(intervals) - 1)
            ]
            positive_gaps = [gap for gap in gaps if gap > 2]
            if len(positive_gaps) < 2:
                continue

            groups.append(
                {
                    "orientation": orientation,
                    "axis_px": round(mean(part[1] for part in bucket), 1),
                    "segments": intervals,
                    "positive_gaps_px": positive_gaps,
                    "kind": "dashed_or_centerline_candidate",
                }
            )
    return groups


def _cluster_rings(
    circles: list[dict[str, Any]],
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    if not circles:
        return []

    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for circle in circles:
        key = (int(circle["cx"]), int(circle["cy"]))
        groups.setdefault(key, []).append(circle)

    output: list[dict[str, Any]] = []
    for group_index, ((cx, cy), items) in enumerate(
        sorted(groups.items()),
        start=1,
    ):
        items = sorted(items, key=lambda item: int(item["radius_px"]))
        clusters: list[list[dict[str, Any]]] = []
        for item in items:
            if (
                not clusters
                or int(item["radius_px"])
                - int(clusters[-1][-1]["radius_px"])
                > 5
            ):
                clusters.append([item])
            else:
                clusters[-1].append(item)

        rings = []
        for cluster in clusters:
            radii = [int(item["radius_px"]) for item in cluster]
            supports = [float(item["edge_support"]) for item in cluster]
            radius = round(sum(radii) / len(radii), 1)
            rings.append(
                {
                    "radius_px": radius,
                    "radius_norm_min_side": round(
                        radius / min(image_width, image_height),
                        5,
                    ),
                    "edge_support": round(max(supports), 3),
                    "raw_peak_count": len(cluster),
                }
            )

        output.append(
            {
                "circle_group_id": f"C{group_index}",
                "center_px": [cx, cy],
                "center_norm": [
                    _norm(cx, image_width),
                    _norm(cy, image_height),
                ],
                "rings": rings,
            }
        )
    return output


def _fragment_score(item: dict[str, Any]) -> float:
    segments = item.get("segments", [])
    gaps = [gap for gap in item.get("positive_gaps_px", []) if gap > 0]
    if len(segments) < 3 or len(gaps) < 2:
        return 0.0

    density = min(len(segments) / 6.0, 1.0)
    gap_mean = mean(gaps)
    regularity = 1.0 / (1.0 + pstdev(gaps) / gap_mean) if gap_mean > 0 else 0.0

    lengths = [max(0, end - start) for start, end in segments]
    mean_length = mean(lengths)
    mean_gap = gap_mean
    dash_balance = (
        min(mean_length, mean_gap) / max(mean_length, mean_gap)
        if max(mean_length, mean_gap)
        else 0.0
    )
    return round(
        0.45 * density + 0.35 * regularity + 0.20 * dash_balance,
        3,
    )


def _compact_fragments(
    groups: list[dict[str, Any]],
    image_width: int,
    image_height: int,
    region: dict[str, int],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for group in groups:
        score = _fragment_score(group)
        if score < 0.30:
            continue

        orientation = str(group["orientation"])
        axis_denominator = image_height if orientation == "horizontal" else image_width
        span_denominator = image_width if orientation == "horizontal" else image_height
        segments = group.get("segments", [])
        span_start = min(start for start, _ in segments)
        span_end = max(end for _, end in segments)

        region_x = int(region["x"])
        region_y = int(region["y"])
        region_width = int(region["width"])
        region_height = int(region["height"])
        local_axis = (
            (float(group["axis_px"]) - region_y) / region_height
            if orientation == "horizontal"
            else (float(group["axis_px"]) - region_x) / region_width
        )
        local_span_start = (
            (span_start - region_x) / region_width
            if orientation == "horizontal"
            else (span_start - region_y) / region_height
        )
        local_span_end = (
            (span_end - region_x) / region_width
            if orientation == "horizontal"
            else (span_end - region_y) / region_height
        )

        scored.append(
            {
                "orientation": orientation,
                "axis_px": float(group["axis_px"]),
                "axis_norm": _norm(float(group["axis_px"]), axis_denominator),
                "span_px": [span_start, span_end],
                "span_norm": [
                    _norm(span_start, span_denominator),
                    _norm(span_end, span_denominator),
                ],
                "local_axis_norm": round(local_axis, 5),
                "local_span_norm": [
                    round(local_span_start, 5),
                    round(local_span_end, 5),
                ],
                "segment_count": len(segments),
                "gap_count": len(group.get("positive_gaps_px", [])),
                "dash_score": score,
                "kind": "dashed_or_centerline_candidate",
            }
        )

    scored.sort(
        key=lambda item: (item["dash_score"], item["segment_count"]),
        reverse=True,
    )
    return scored[:limit]


def _adapt_probe(probe: dict[str, Any]) -> dict[str, Any]:
    image_width = int(probe["image"]["width"])
    image_height = int(probe["image"]["height"])
    regions = []

    for region in probe.get("regions", []):
        bbox = region["bbox"]
        x, y, width, height = (
            int(bbox[key])
            for key in ("x", "y", "width", "height")
        )
        circle_groups = _cluster_rings(
            region.get("circle_evidence", []),
            image_width,
            image_height,
        )
        for circle_group in circle_groups:
            cx, cy = circle_group["center_px"]
            circle_group["center_local_norm"] = [
                round((cx - x) / width, 5),
                round((cy - y) / height, 5),
            ]

        regions.append(
            {
                "region_id": region["region_id"],
                "bbox_px": [x, y, width, height],
                "bbox_norm": [
                    _norm(x, image_width),
                    _norm(y, image_height),
                    _norm(width, image_width),
                    _norm(height, image_height),
                ],
                "circle_groups": circle_groups,
                "linear_pattern_candidates": _compact_fragments(
                    region.get("fragment_groups", []),
                    image_width,
                    image_height,
                    bbox,
                ),
            }
        )

    return {
        "schema": "raw-evidence-v0",
        "source_type": "raster_image",
        "image": {
            "width": image_width,
            "height": image_height,
        },
        "semantics_policy": "geometry_only_no_engineering_claims",
        "probe_parameters": probe.get("probe_parameters", {}),
        "regions": regions,
        "summary": {
            "region_count": len(regions),
            "circle_group_count": sum(
                len(region["circle_groups"])
                for region in regions
            ),
            "ring_count": sum(
                len(group["rings"])
                for region in regions
                for group in region["circle_groups"]
            ),
            "linear_pattern_candidate_count": sum(
                len(region["linear_pattern_candidates"])
                for region in regions
            ),
        },
    }


def _merge_collinear(
    items: list[tuple[str, float, int, int, float]],
    axis_tolerance: int,
    join_gap: int,
) -> list[tuple[str, float, int, int]]:
    groups: list[list[tuple[str, float, int, int, float]]] = []
    for item in sorted(items, key=lambda value: (value[1], value[2])):
        _, axis, start, end, _ = item
        placed = False
        for group in groups[-15:]:
            group_axis = mean(value[1] for value in group)
            min_start = min(value[2] for value in group)
            max_end = max(value[3] for value in group)
            if (
                abs(axis - group_axis) <= axis_tolerance
                and start <= max_end + join_gap
                and end >= min_start - join_gap
            ):
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    return [
        (
            group[0][0],
            mean(value[1] for value in group),
            min(value[2] for value in group),
            max(value[3] for value in group),
        )
        for group in groups
    ]


def _deduplicate(values: list[float], tolerance: int) -> list[float]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if not groups or value - groups[-1][-1] > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [round(sum(group) / len(group), 1) for group in groups]


def _dimension_geometry(
    gray: Any,
    raw_evidence: dict[str, Any],
    cv2: Any,
    np: Any,
) -> list[dict[str, Any]]:
    height, width = gray.shape
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    threshold = max(35, round(width * 0.034))
    min_line_length = max(18, round(width * 0.017))
    max_line_gap = max(3, round(width * 0.0035))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=threshold,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )

    segments: list[tuple[str, float, int, int, float]] = []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            dx = int(x2 - x1)
            dy = int(y2 - y1)
            angle = math.degrees(math.atan2(dy, dx))
            length = math.hypot(dx, dy)
            if abs(angle) <= 3 or abs(abs(angle) - 180) <= 3:
                segments.append(
                    (
                        "horizontal",
                        float((int(y1) + int(y2)) / 2),
                        int(min(x1, x2)),
                        int(max(x1, x2)),
                        length,
                    )
                )
            elif abs(abs(angle) - 90) <= 3:
                segments.append(
                    (
                        "vertical",
                        float((int(x1) + int(x2)) / 2),
                        int(min(y1, y2)),
                        int(max(y1, y2)),
                        length,
                    )
                )

    axis_tolerance = max(2, round(width * 0.0017))
    join_gap = max(6, round(width * 0.0056))
    horizontal = _merge_collinear(
        [item for item in segments if item[0] == "horizontal"],
        axis_tolerance,
        join_gap,
    )
    vertical = _merge_collinear(
        [item for item in segments if item[0] == "vertical"],
        axis_tolerance,
        join_gap,
    )

    region_boxes = {
        region["region_id"]: region["bbox_px"]
        for region in raw_evidence.get("regions", [])
    }

    minimum_span = max(50, round(width * 0.028))
    witness_minimum = max(20, round(width * 0.011))
    witness_tolerance = max(5, round(width * 0.0045))
    witness_dedup = max(6, round(width * 0.004))

    output: list[dict[str, Any]] = []
    next_id = 1

    for _, axis, start, end in horizontal:
        if end - start < minimum_span:
            continue
        witnesses = _deduplicate(
            [
                line_axis
                for _, line_axis, line_start, line_end in vertical
                if line_end - line_start >= witness_minimum
                and line_start - witness_tolerance <= axis <= line_end + witness_tolerance
                and start - 40 <= line_axis <= end + 40
            ],
            witness_dedup,
        )
        if len(witnesses) < 2:
            continue

        for region_id, bbox in region_boxes.items():
            x, y, region_width, region_height = map(int, bbox)
            region_right = x + region_width
            region_bottom = y + region_height
            overlap = max(0, min(end, region_right) - max(start, x))
            if overlap < 0.05 * region_width:
                continue
            if (
                axis < y - 0.15 * region_height
                or axis > region_bottom + 0.15 * region_height
            ):
                continue

            output.append(
                {
                    "candidate_id": f"DG{next_id}",
                    "region_id": region_id,
                    "orientation": "horizontal",
                    "axis_px": round(axis, 1),
                    "axis_local_norm": round((axis - y) / region_height, 5),
                    "line_span_px": [start, end],
                    "witness_positions_px": witnesses,
                    "witness_positions_local_norm": [
                        round((value - x) / region_width, 5)
                        for value in witnesses
                    ],
                    "status": "candidate_only_no_semantics",
                }
            )
            next_id += 1

    for _, axis, start, end in vertical:
        if end - start < minimum_span:
            continue
        witnesses = _deduplicate(
            [
                line_axis
                for _, line_axis, line_start, line_end in horizontal
                if line_end - line_start >= witness_minimum
                and line_start - witness_tolerance <= axis <= line_end + witness_tolerance
                and start - 40 <= line_axis <= end + 40
            ],
            witness_dedup,
        )
        if len(witnesses) < 2:
            continue

        for region_id, bbox in region_boxes.items():
            x, y, region_width, region_height = map(int, bbox)
            region_right = x + region_width
            region_bottom = y + region_height
            overlap = max(0, min(end, region_bottom) - max(start, y))
            if overlap < 0.05 * region_height:
                continue
            if (
                axis < x - 0.15 * region_width
                or axis > region_right + 0.15 * region_width
            ):
                continue

            output.append(
                {
                    "candidate_id": f"DG{next_id}",
                    "region_id": region_id,
                    "orientation": "vertical",
                    "axis_px": round(axis, 1),
                    "axis_local_norm": round((axis - x) / region_width, 5),
                    "line_span_px": [start, end],
                    "witness_positions_px": witnesses,
                    "witness_positions_local_norm": [
                        round((value - y) / region_height, 5)
                        for value in witnesses
                    ],
                    "status": "candidate_only_no_semantics",
                }
            )
            next_id += 1

    return output


def extract_raw_evidence(image_path: str | Path) -> dict[str, Any]:
    """Extract lightweight geometry-only RawEvidence v1 from a raster drawing."""

    cv2, np = _load_cv_modules()
    path = Path(image_path)
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"unable to read raster image: {path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = _axis_lines(edges, cv2, np)
    regions = _view_regions(gray.shape, lines, cv2, np)
    min_fragment_length, max_fragment_length = fragment_length_limits(
        int(gray.shape[1])
    )

    probe_regions: list[dict[str, Any]] = []
    for index, region in enumerate(regions, start=1):
        probe_regions.append(
            {
                "region_id": f"R{index}",
                "bbox": {
                    key: region[key]
                    for key in ("x", "y", "width", "height")
                },
                "circle_evidence": _circle_candidates(
                    gray,
                    edges,
                    region,
                    cv2,
                ),
                "fragment_groups": _fragment_groups(
                    edges,
                    region,
                    int(gray.shape[1]),
                    cv2,
                    np,
                ),
            }
        )

    probe: dict[str, Any] = {
        "schema": "raster-evidence-probe-v1",
        "image": {
            "width": int(gray.shape[1]),
            "height": int(gray.shape[0]),
        },
        "probe_parameters": {
            "fragment_length_limits_px": [
                min_fragment_length,
                max_fragment_length,
            ],
            "fragment_length_width_ratios": [
                round(_FRAGMENT_MIN_RATIO, 7),
                round(_FRAGMENT_MAX_RATIO, 7),
            ],
        },
        "axis_line_count": len(lines),
        "regions": probe_regions,
    }

    raw = _adapt_probe(probe)
    raw["schema"] = "raw-evidence-v1"
    raw["dimension_geometry_candidates"] = _dimension_geometry(
        gray,
        raw,
        cv2,
        np,
    )
    raw["summary"]["dimension_geometry_candidate_count"] = len(
        raw["dimension_geometry_candidates"]
    )
    raw["notes"] = [
        "Raster geometry only. No OCR model, VLM, neural detector, or model weights were used.",
        "Dimension geometry is candidate-only: dimension-axis geometry plus perpendicular witness positions; no numeric label or engineering ownership is asserted.",
    ]
    return raw
