from __future__ import annotations

import importlib
import math
from typing import Any, Literal

Direction = Literal["horizontal", "vertical"]


def _bbox_rect(raw: object) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, list):
        return None
    points: list[tuple[float, float]] = []
    for point in raw:
        if (
            isinstance(point, list)
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and not isinstance(point[0], bool)
            and isinstance(point[1], (int, float))
            and not isinstance(point[1], bool)
        ):
            points.append((float(point[0]), float(point[1])))
    if len(points) < 2:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _cluster_axis_segments(
    segments: list[tuple[float, float, float]],
    *,
    axis_tolerance: float = 3.0,
) -> list[tuple[float, float, float]]:
    clusters: list[dict[str, Any]] = []
    for axis, low, high in sorted(segments, key=lambda item: item[0]):
        selected: dict[str, Any] | None = None
        for cluster in clusters:
            if abs(axis - float(cluster["axis"])) <= axis_tolerance:
                selected = cluster
                break
        if selected is None:
            clusters.append(
                {
                    "axes": [axis],
                    "axis": axis,
                    "low": low,
                    "high": high,
                }
            )
            continue
        axes = selected["axes"]
        assert isinstance(axes, list)
        axes.append(axis)
        selected["axis"] = sum(float(value) for value in axes) / len(axes)
        selected["low"] = min(float(selected["low"]), low)
        selected["high"] = max(float(selected["high"]), high)

    output: list[tuple[float, float, float]] = []
    for cluster in clusters:
        low = float(cluster["low"])
        high = float(cluster["high"])
        if high - low >= 10.0:
            output.append((float(cluster["axis"]), low, high))
    return output


def _interval_distance(
    first_low: float,
    first_high: float,
    second_low: float,
    second_high: float,
) -> float:
    if first_high < second_low:
        return second_low - first_high
    if second_high < first_low:
        return first_low - second_high
    return 0.0


def _parallel_pair_candidates(
    lines: list[tuple[float, float, float]],
    *,
    bbox_axis_low: float,
    bbox_axis_high: float,
    bbox_span_low: float,
    bbox_span_high: float,
) -> list[tuple[float, float, float]]:
    output: list[tuple[float, float, float]] = []
    bbox_axis_span = max(0.0, bbox_axis_high - bbox_axis_low)
    # A short-dimension label often occupies the middle third between
    # witness lines. The line endpoints can lie one full glyph height
    # outside its OCR box. The separate pair-score and direction-ambiguity
    # gates still require two uniquely supported physical witness lines.
    axis_margin = max(8.0, min(40.0, bbox_axis_span * 1.0))
    max_pair_separation = max(90.0, min(160.0, bbox_axis_span))
    for first_index in range(len(lines)):
        first = lines[first_index]
        for second in lines[first_index + 1 :]:
            if not (
                bbox_axis_low - axis_margin
                <= first[0]
                <= bbox_axis_high + axis_margin
                and bbox_axis_low - axis_margin
                <= second[0]
                <= bbox_axis_high + axis_margin
            ):
                continue
            separation = abs(first[0] - second[0])
            if separation < 6.0 or separation > max_pair_separation:
                continue
            overlap_low = max(first[1], second[1])
            overlap_high = min(first[2], second[2])
            overlap = overlap_high - overlap_low
            if overlap < 8.0:
                continue
            axis_distance = _interval_distance(
                min(first[0], second[0]),
                max(first[0], second[0]),
                bbox_axis_low,
                bbox_axis_high,
            )
            span_distance = _interval_distance(
                overlap_low,
                overlap_high,
                bbox_span_low,
                bbox_span_high,
            )
            if axis_distance > 60.0 or span_distance > 60.0:
                continue
            score = overlap / (
                1.0
                + axis_distance / 12.0
                + span_distance / 12.0
                + max(0.0, separation - 50.0) / 100.0
            )
            output.append(
                (
                    score,
                    min(float(first[0]), float(second[0])),
                    max(float(first[0]), float(second[0])),
                )
            )
    output.sort(key=lambda item: (-item[0], item[1], item[2]))
    return output


def _best_parallel_pair_score(
    lines: list[tuple[float, float, float]],
    *,
    bbox_axis_low: float,
    bbox_axis_high: float,
    bbox_span_low: float,
    bbox_span_high: float,
) -> float:
    candidates = _parallel_pair_candidates(
        lines,
        bbox_axis_low=bbox_axis_low,
        bbox_axis_high=bbox_axis_high,
        bbox_span_low=bbox_span_low,
        bbox_span_high=bbox_span_high,
    )
    return candidates[0][0] if candidates else 0.0


def infer_labeled_dimension_axis_span(
    image_path: str,
    raw_bbox: object,
    *,
    expected_direction: Direction,
) -> tuple[float, float] | None:
    """Recover a labeled dimension-line span for topology/identity only.

    Unlike the short-dimension witness helper, this follows the dimension axis
    itself, so long overall dimensions can remain usable without converting any
    raster distance into an engineering value. The selected line must be unique
    near one edge of the OCR label box and must span the label center.
    """

    rect = _bbox_rect(raw_bbox)
    if rect is None or not isinstance(image_path, str) or not image_path:
        return None

    try:
        cv2: Any = importlib.import_module("cv2")
    except ImportError:
        return None

    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None

    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0
    x_margin = max(160.0, width * 1.8)
    y_margin = max(220.0, height * 8.0)

    image_height, image_width = gray.shape[:2]
    roi_x0 = max(0, int(math.floor(x0 - x_margin)))
    roi_x1 = min(image_width, int(math.ceil(x1 + x_margin)))
    roi_y0 = max(0, int(math.floor(y0 - y_margin)))
    roi_y1 = min(image_height, int(math.ceil(y1 + y_margin)))
    if roi_x1 <= roi_x0 or roi_y1 <= roi_y0:
        return None

    roi = gray[roi_y0:roi_y1, roi_x0:roi_x1].copy()
    local_x0 = x0 - roi_x0
    local_x1 = x1 - roi_x0
    local_y0 = y0 - roi_y0
    local_y1 = y1 - roi_y0

    mask_margin = 8
    text_x0 = max(0, int(math.floor(local_x0 - mask_margin)))
    text_x1 = min(roi.shape[1], int(math.ceil(local_x1 + mask_margin)))
    text_y0 = max(0, int(math.floor(local_y0 - mask_margin)))
    text_y1 = min(roi.shape[0], int(math.ceil(local_y1 + mask_margin)))
    roi[text_y0:text_y1, text_x0:text_x1] = 255

    edges = cv2.Canny(roi, 50, 150)
    raw_lines = cv2.HoughLinesP(
        edges,
        1,
        math.pi / 180.0,
        threshold=16,
        minLineLength=16,
        maxLineGap=8,
    )
    if raw_lines is None:
        return None

    horizontal_segments: list[tuple[float, float, float]] = []
    vertical_segments: list[tuple[float, float, float]] = []
    for x_start, y_start, x_end, y_end in raw_lines.reshape(-1, 4).tolist():
        dx = float(x_end - x_start)
        dy = float(y_end - y_start)
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180.0
        if angle > 90.0:
            angle = 180.0 - angle
        if angle <= 7.0:
            horizontal_segments.append(
                (
                    (float(y_start) + float(y_end)) / 2.0,
                    float(min(x_start, x_end)),
                    float(max(x_start, x_end)),
                )
            )
        elif angle >= 83.0:
            vertical_segments.append(
                (
                    (float(x_start) + float(x_end)) / 2.0,
                    float(min(y_start, y_end)),
                    float(max(y_start, y_end)),
                )
            )

    if expected_direction == "vertical":
        lines = _cluster_axis_segments(vertical_segments)
        span_center = ((y0 + y1) / 2.0) - roi_y0
        box_edge_low = local_x0
        box_edge_high = local_x1
        box_axis_span = height
        perpendicular_span = width
        global_span_offset = float(roi_y0)
    else:
        lines = _cluster_axis_segments(horizontal_segments)
        span_center = ((x0 + x1) / 2.0) - roi_x0
        box_edge_low = local_y0
        box_edge_high = local_y1
        box_axis_span = width
        perpendicular_span = height
        global_span_offset = float(roi_x0)

    minimum_span = max(30.0, box_axis_span * 1.5)
    maximum_edge_distance = max(80.0, perpendicular_span * 0.75)
    candidates: list[tuple[float, float, float, float, float]] = []

    for axis_position, low, high in lines:
        span_length = high - low
        if span_length < minimum_span:
            continue
        if not low - 8.0 <= span_center <= high + 8.0:
            continue

        if axis_position < box_edge_low:
            edge_distance = box_edge_low - axis_position
        elif axis_position > box_edge_high:
            edge_distance = axis_position - box_edge_high
        else:
            edge_distance = min(
                axis_position - box_edge_low,
                box_edge_high - axis_position,
            )
        if edge_distance > maximum_edge_distance:
            continue

        candidates.append(
            (
                edge_distance,
                -span_length,
                axis_position,
                low,
                high,
            )
        )

    candidates.sort()
    if not candidates:
        return None

    if len(candidates) > 1:
        ambiguity_margin = max(
            4.0,
            min(12.0, perpendicular_span * 0.08),
        )
        if candidates[1][0] - candidates[0][0] < ambiguity_margin:
            return None

    _distance, _negative_span, axis_position, low, high = candidates[0]

    perpendicular_lines = (
        _cluster_axis_segments(horizontal_segments)
        if expected_direction == "vertical"
        else _cluster_axis_segments(vertical_segments)
    )
    terminal_tolerance = max(
        12.0,
        min(28.0, perpendicular_span * 0.15),
    )

    def snapped_terminal(raw_position: float) -> float:
        terminal_candidates: list[tuple[float, float]] = []
        for terminal_axis, terminal_low, terminal_high in perpendicular_lines:
            if terminal_high - terminal_low < 20.0:
                continue
            if not (
                terminal_low - 8.0
                <= axis_position
                <= terminal_high + 8.0
            ):
                continue
            residual = abs(float(terminal_axis) - raw_position)
            if residual <= terminal_tolerance:
                terminal_candidates.append(
                    (residual, float(terminal_axis))
                )

        terminal_candidates.sort()
        if not terminal_candidates:
            return raw_position
        if (
            len(terminal_candidates) > 1
            and terminal_candidates[1][0] - terminal_candidates[0][0] < 3.0
        ):
            return raw_position
        return terminal_candidates[0][1]

    low = snapped_terminal(low)
    high = snapped_terminal(high)
    if low >= high:
        return None
    return low + global_span_offset, high + global_span_offset


def infer_short_dimension_visual_topology(
    image_path: str,
    raw_bbox: object,
) -> tuple[Direction, list[tuple[float, float]]] | None:
    """Infer short dimension direction and plausible witness-axis pairs.

    Returned pixel positions stay in source-raster coordinates and are for
    identity/topology checks only. They are never engineering values or
    coordinates.
    """

    rect = _bbox_rect(raw_bbox)
    if rect is None or not isinstance(image_path, str) or not image_path:
        return None

    try:
        cv2: Any = importlib.import_module("cv2")
    except ImportError:
        return None

    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None

    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0
    x_margin = max(120.0, width * 1.6)
    y_margin = max(80.0, height * 3.0)

    image_height, image_width = gray.shape[:2]
    roi_x0 = max(0, int(math.floor(x0 - x_margin)))
    roi_x1 = min(image_width, int(math.ceil(x1 + x_margin)))
    roi_y0 = max(0, int(math.floor(y0 - y_margin)))
    roi_y1 = min(image_height, int(math.ceil(y1 + y_margin)))
    if roi_x1 <= roi_x0 or roi_y1 <= roi_y0:
        return None

    roi = gray[roi_y0:roi_y1, roi_x0:roi_x1].copy()
    local_x0 = x0 - roi_x0
    local_x1 = x1 - roi_x0
    local_y0 = y0 - roi_y0
    local_y1 = y1 - roi_y0

    mask_margin = 6
    text_x0 = max(0, int(math.floor(local_x0 - mask_margin)))
    text_x1 = min(roi.shape[1], int(math.ceil(local_x1 + mask_margin)))
    text_y0 = max(0, int(math.floor(local_y0 - mask_margin)))
    text_y1 = min(roi.shape[0], int(math.ceil(local_y1 + mask_margin)))
    roi[text_y0:text_y1, text_x0:text_x1] = 255

    edges = cv2.Canny(roi, 50, 150)
    raw_lines = cv2.HoughLinesP(
        edges,
        1,
        math.pi / 180.0,
        threshold=12,
        minLineLength=10,
        maxLineGap=4,
    )
    if raw_lines is None:
        return None

    horizontal_segments: list[tuple[float, float, float]] = []
    vertical_segments: list[tuple[float, float, float]] = []
    for x_start, y_start, x_end, y_end in raw_lines.reshape(-1, 4).tolist():
        dx = float(x_end - x_start)
        dy = float(y_end - y_start)
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180.0
        if angle > 90.0:
            angle = 180.0 - angle
        if angle <= 7.0:
            horizontal_segments.append(
                (
                    (float(y_start) + float(y_end)) / 2.0,
                    float(min(x_start, x_end)),
                    float(max(x_start, x_end)),
                )
            )
        elif angle >= 83.0:
            vertical_segments.append(
                (
                    (float(x_start) + float(x_end)) / 2.0,
                    float(min(y_start, y_end)),
                    float(max(y_start, y_end)),
                )
            )

    horizontal_lines = _cluster_axis_segments(horizontal_segments)
    vertical_lines = _cluster_axis_segments(vertical_segments)
    horizontal_pairs = _parallel_pair_candidates(
        horizontal_lines,
        bbox_axis_low=local_y0,
        bbox_axis_high=local_y1,
        bbox_span_low=local_x0,
        bbox_span_high=local_x1,
    )
    vertical_pairs = _parallel_pair_candidates(
        vertical_lines,
        bbox_axis_low=local_x0,
        bbox_axis_high=local_x1,
        bbox_span_low=local_y0,
        bbox_span_high=local_y1,
    )

    horizontal_witness_score = horizontal_pairs[0][0] if horizontal_pairs else 0.0
    vertical_witness_score = vertical_pairs[0][0] if vertical_pairs else 0.0
    best = max(horizontal_witness_score, vertical_witness_score)
    other = min(horizontal_witness_score, vertical_witness_score)
    if best < 12.0:
        return None
    if other > 0.0 and best / other < 1.20:
        return None

    if horizontal_witness_score > vertical_witness_score:
        direction: Direction = "vertical"
        pairs = [
            (low + float(roi_y0), high + float(roi_y0))
            for score, low, high in horizontal_pairs
            if score >= 12.0
        ]
    elif vertical_witness_score > horizontal_witness_score:
        direction = "horizontal"
        pairs = [
            (low + float(roi_x0), high + float(roi_x0))
            for score, low, high in vertical_pairs
            if score >= 12.0
        ]
    else:
        return None

    if not pairs:
        return None
    return direction, pairs


def infer_short_dimension_visual_direction(
    image_path: str,
    raw_bbox: object,
) -> Direction | None:
    """Infer only short orthogonal dimension-line direction from witness topology."""

    topology = infer_short_dimension_visual_topology(image_path, raw_bbox)
    return topology[0] if topology is not None else None
