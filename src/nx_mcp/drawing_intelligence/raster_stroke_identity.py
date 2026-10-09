"""Conservatively prove duplicate raster detections of one physical stroke.

Never calculate engineering length, direction or position from raster pixels.
If any precondition or scan fails, preserve both possible physical owners.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    val = float(value)
    return val if math.isfinite(val) else None


def _span(profile: dict[str, Any]) -> tuple[float, float] | None:
    points = profile.get("span_px")
    if not isinstance(points, list) or len(points) != 2:
        return None
    lo, hi = (_number(item) for item in points)
    if lo is None or hi is None or lo == hi:
        return None
    return min(lo, hi), max(lo, hi)


def single_ink_stroke_alias(
    profiles: list[dict[str, Any]], raster_path: str | None
) -> dict[str, Any] | None:
    """Return one existing profile only if two candidates hit one ink stroke.

    Strict: same orientation and extreme, substantial span overlap,
    independently supported contours, sub-stroke coordinate separation,
    >=11/13 image samples with a unique joint dark run. Missing/corrupted
    rasters and nearby DISTINCT parallel strokes always remain ambiguous.
    """
    if len(profiles) != 2 or not raster_path:
        return None
    first, second = profiles
    if any(item.get("kind") != "profile_edge_candidate" for item in profiles):
        return None
    if first.get("ref") == second.get("ref") or not all(
        isinstance(item.get("ref"), str) and item["ref"] for item in profiles
    ):
        return None
    orientation = first.get("source_orientation")
    if orientation not in ("horizontal", "vertical") or second.get("source_orientation") != orientation:
        return None
    if (first.get("relative_extreme_side") not in ("min", "max")
        or first.get("relative_extreme_side") != second.get("relative_extreme_side")):
        return None
    spans = [_span(item) for item in profiles]
    if any(span is None for span in spans):
        return None
    low = max(spans[0][0], spans[1][0])
    high = min(spans[0][1], spans[1][1])
    if high <= low or (high - low) / max(
        spans[0][1] - spans[0][0], spans[1][1] - spans[1][0]
    ) < 0.80:
        return None
    positions = [_number(item.get("position_px")) for item in profiles]
    tolerances = [_number(item.get("axis_tolerance_px")) for item in profiles]
    if any(value is None for value in (*positions, *tolerances)):
        return None
    if min(tolerances) < 1 or abs(positions[0] - positions[1]) > min(
        1.5, min(tolerances) / 2
    ):
        return None
    for item in profiles:
        for key in ("independent_geometry_source_count", "non_dimension_crossing_source_count"):
            value = item.get(key)
            if type(value) is not int or value <= 0:
                return None

    try:
        import cv2
        image = cv2.imread(str(Path(raster_path)), cv2.IMREAD_GRAYSCALE)
    except (ImportError, OSError, ValueError, TypeError):
        return None
    if image is None or image.ndim != 2:
        return None
    height, width = image.shape
    center = sum(positions) / 2
    strip_start = math.floor(center) - 7
    strip_end = math.floor(center) + 8
    if strip_start < 0 or (strip_end > height if orientation == "horizontal" else strip_end > width):
        return None
    unique_samples = 0
    samples = 13
    # Avoid segment endpoints, where projections and witness crossings cluster.
    for index in range(samples):
        along = low + (high - low) * (0.08 + 0.84 * index / (samples - 1))
        coordinate = round(along)
        if (not 0 <= coordinate < width if orientation == "horizontal"
            else not 0 <= coordinate < height):
            continue
        line = (
            image[strip_start:strip_end, coordinate]
            if orientation == "horizontal"
            else image[coordinate, strip_start:strip_end]
        )
        dark = [int(v) < 145 for v in line]
        runs: list[tuple[int, int]] = []
        beginning: int | None = None
        for ix, value in enumerate([*dark, False]):
            if value and beginning is None:
                beginning = ix
            elif not value and beginning is not None:
                runs.append((strip_start + beginning, strip_start + ix - 1))
                beginning = None
        if len(runs) != 1:
            continue
        start, end = runs[0]
        if end - start > 4:
            continue
        if all(start - 1 <= position <= end + 1 for position in positions):
            unique_samples += 1
    if unique_samples < 11:
        return None
    # Canonicalization selects an EXISTING physical candidate, not new geometry.
    return min(
        profiles,
        key=lambda item: (
            -item["non_dimension_crossing_source_count"],
            str(item["ref"]),
        ),
    )
