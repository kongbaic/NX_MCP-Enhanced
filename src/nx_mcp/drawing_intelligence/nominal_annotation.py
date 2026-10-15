"""Proof-only classification of raster surface finish and tolerance markings.

Never substitutes pixel lengths for engineering dimensions or repairs OCR text.
Only precisely recognized non-dimensional mark topology can suppress nominal
CAD dimension blocking; raw text and source identity must still be preserved.
"""
from __future__ import annotations

import importlib
import math
from pathlib import Path
from typing import Any


def _bounds(raw: Any) -> tuple[int, int, int, int] | None:
    if not (
        isinstance(raw, list)
        and len(raw) == 4
        and all(
            isinstance(point, (list, tuple))
            and len(point) == 2
            and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in point
            )
            for point in raw
        )
    ):
        return None
    xs = [point[0] for point in raw]
    ys = [point[1] for point in raw]
    x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def _tolerance_frame(gray: Any, bbox: tuple[int, int, int, int]) -> bool:
    """Require a number enclosed by a complete three-compartment frame."""
    x0, y0, x1, y1 = bbox
    height, width = gray.shape
    if (
        x0 < 25
        or x1 + 20 >= width
        or y0 < 7
        or y1 + 7 >= height
        or not 15 <= y1 - y0 <= 70
        or not 16 <= x1 - x0 <= 150
    ):
        return False

    def horizontal(y: int, left: int, right: int) -> bool:
        return (
            0 <= left < right < width
            and right - left >= 15
            and float((gray[y, left : right + 1] < 145).mean()) >= 0.82
        )

    def vertical(x: int, top: int, bottom: int) -> bool:
        return (
            0 <= x < width
            and 0 <= top < bottom < height
            and bottom - top >= 18
            and float((gray[top + 4 : bottom - 3, x] < 145).mean()) >= 0.83
        )

    for top in range(y0 - 5, y0 + 4):
        if not horizontal(top, x0 + 6, x1 - 6):
            continue
        for bottom in range(y1 - 5, y1 + 4):
            if bottom - top < 19 or not horizontal(bottom, x0 + 6, x1 - 6):
                continue
            for left in range(x0 - 5, x0 + 4):
                if not vertical(left, top, bottom):
                    continue
                for right in range(x1 - 2, x1 + 11):
                    if not (
                        right - left >= 20
                        and vertical(right, top, bottom)
                        and horizontal(top, left, right)
                        and horizontal(bottom, left, right)
                    ):
                        continue
                    left_cell = any(
                        vertical(x, top, bottom)
                        and horizontal(top, x, left)
                        and horizontal(bottom, x, left)
                        for x in range(max(0, left - 65), left - 18)
                    )
                    right_cell = any(
                        vertical(x, top, bottom)
                        and horizontal(top, right, x)
                        and horizontal(bottom, right, x)
                        for x in range(right + 18, min(width, right + 65))
                    )
                    if left_cell and right_cell:
                        return True
    return False


def _bbox_gap(point: tuple[float, float], bbox: tuple[int, int, int, int]) -> float:
    x, y = point
    x0, y0, x1, y1 = bbox
    return math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))


def _inside_margin(
    point: tuple[float, float], bbox: tuple[int, int, int, int]
) -> float:
    x, y = point
    x0, y0, x1, y1 = bbox
    if x0 <= x <= x1 and y0 <= y <= y1:
        return min(x - x0, x1 - x, y - y0, y1 - y)
    return 0.0


def _surface_texture_mark(
    gray: Any,
    bbox: tuple[int, int, int, int],
    cv2: Any,
) -> bool:
    """Require unequal V strokes joined near text and touching a surface line.

    Small dimension arrowheads and V-shaped numerals cannot qualify by shape
    alone. The proof requires a long/short stroke pair, apex at the text edge
    rather than in a digit, and a separate straight material-contact line.
    """
    x0, y0, x1, y1 = bbox
    height, width = gray.shape
    left, top = max(0, x0 - 45), max(0, y0 - 45)
    right, bottom = min(width, x1 + 45), min(height, y1 + 45)
    if right - left < 30 or bottom - top < 30:
        return False
    mask = (gray[top:bottom, left:right] < 130).astype("uint8") * 255
    detected = cv2.HoughLinesP(
        mask,
        1,
        math.pi / 180,
        threshold=9,
        minLineLength=11,
        maxLineGap=4,
    )
    if detected is None:
        return False

    sloped: list[tuple[tuple[int, int], tuple[int, int], float]] = []
    straight: list[tuple[tuple[int, int], tuple[int, int], float]] = []
    for line in detected[:, 0, :]:
        ax, ay, bx, by = map(int, line)
        a, b = (ax + left, ay + top), (bx + left, by + top)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        angle = abs(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))) % 180
        if length >= 11 and (20 <= angle <= 75 or 105 <= angle <= 160):
            sloped.append((a, b, length))
        if length >= 25 and (angle < 10 or angle > 170 or 80 < angle < 100):
            straight.append((a, b, angle))

    for index, first in enumerate(sloped):
        for second in sloped[index + 1 :]:
            if (
                max(first[2], second[2]) < 29
                or max(first[2], second[2]) / min(first[2], second[2]) < 1.65
            ):
                continue
            for first_point in first[:2]:
                for second_point in second[:2]:
                    if math.dist(first_point, second_point) > 4.5:
                        continue
                    apex = (
                        (first_point[0] + second_point[0]) / 2,
                        (first_point[1] + second_point[1]) / 2,
                    )
                    if _bbox_gap(apex, bbox) > 29 or _inside_margin(apex, bbox) > 4:
                        continue
                    vectors: list[tuple[float, float]] = []
                    for stroke, point in (
                        (first, first_point),
                        (second, second_point),
                    ):
                        far = stroke[1] if stroke[0] == point else stroke[0]
                        vectors.append((far[0] - apex[0], far[1] - apex[1]))
                    denominator = math.hypot(*vectors[0]) * math.hypot(*vectors[1])
                    if denominator <= 0:
                        continue
                    cosine = (
                        vectors[0][0] * vectors[1][0]
                        + vectors[0][1] * vectors[1][1]
                    ) / denominator
                    aperture = math.degrees(math.acos(max(-1, min(1, cosine))))
                    if not 36 <= aperture <= 92:
                        continue
                    longest = max((first, second), key=lambda item: item[2])
                    long_ends = [
                        point
                        for point in longest[:2]
                        if math.dist(point, apex) > 4
                    ]
                    if not long_ends or _bbox_gap(long_ends[0], bbox) > 22:
                        continue
                    for line_a, line_b, angle in straight:
                        if angle < 10 or angle > 170:
                            touches = (
                                abs(apex[1] - line_a[1]) <= 5
                                and min(line_a[0], line_b[0]) - 3
                                <= apex[0]
                                <= max(line_a[0], line_b[0]) + 3
                            )
                        else:
                            touches = (
                                abs(apex[0] - line_a[0]) <= 5
                                and min(line_a[1], line_b[1]) - 3
                                <= apex[1]
                                <= max(line_a[1], line_b[1]) + 3
                            )
                        if touches:
                            return True
    return False


def classify_unassigned_marks(report: dict[str, Any]) -> dict[int, str]:
    """Classify only raster-proven annotations; missing evidence fails closed."""
    raster = report.get("source_raster")
    if not isinstance(raster, str) or not Path(raster).is_file():
        return {}
    try:
        # Lazy import avoids making NumPy stubs part of the Python 3.10
        # mypy analysis: OpenCV and NumPy are optional drawing dependencies.
        cv2 = importlib.import_module("cv2")
        image = cv2.imread(raster, cv2.IMREAD_GRAYSCALE)
    except (ImportError, OSError):
        return {}
    if image is None:
        return {}

    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        return {}
    proven: dict[int, str] = {}
    for item in coverage.get("unassigned_linear_observations", []):
        if not isinstance(item, dict):
            continue
        source_index = item.get("source_item_index")
        bbox = _bounds(item.get("bbox"))
        if (
            not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or bbox is None
        ):
            continue
        if _tolerance_frame(image, bbox):
            proven[source_index] = "geometric_tolerance_frame"
        elif _surface_texture_mark(image, bbox, cv2):
            proven[source_index] = "surface_texture_symbol"
    return proven
