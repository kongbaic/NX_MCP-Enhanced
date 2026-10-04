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


def _radial_gradient_alignment(
    edges: Any,
    gradient_x: Any,
    gradient_y: Any,
    cx: int,
    cy: int,
    radius: int,
    *,
    tol: int = 1,
    samples: int = 180,
    aligned_cosine_threshold: float = 0.85,
) -> tuple[float, float]:
    """Measure whether nearby edge normals consistently point toward circle center."""

    h, w = edges.shape
    alignment_sum = 0.0
    hit_count = 0
    aligned_count = 0

    for index in range(samples):
        theta = 2.0 * math.pi * index / samples
        radial_x = math.cos(theta)
        radial_y = math.sin(theta)
        x = int(round(cx + radius * radial_x))
        y = int(round(cy + radius * radial_y))

        best_alignment: float | None = None
        for dy in range(-tol, tol + 1):
            for dx in range(-tol, tol + 1):
                xx, yy = x + dx, y + dy
                if not (0 <= xx < w and 0 <= yy < h) or edges[yy, xx] == 0:
                    continue
                gx = float(gradient_x[yy, xx])
                gy = float(gradient_y[yy, xx])
                magnitude = math.hypot(gx, gy)
                if magnitude <= 1e-9:
                    continue
                alignment = abs((gx * radial_x + gy * radial_y) / magnitude)
                if best_alignment is None or alignment > best_alignment:
                    best_alignment = alignment

        if best_alignment is None:
            continue
        hit_count += 1
        alignment_sum += best_alignment
        if best_alignment >= aligned_cosine_threshold:
            aligned_count += 1

    if hit_count == 0:
        return 0.0, 0.0
    return alignment_sum / hit_count, aligned_count / samples


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


def _one_sided_boundary_evidence(
    gray: Any,
    first: tuple[int, int],
    second: tuple[int, int],
) -> dict[str, Any]:
    """Measure whether a raster line separates background from filled geometry."""

    image_height, image_width = gray.shape[:2]
    dx = float(second[0] - first[0])
    dy = float(second[1] - first[1])
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return {
            "one_sided_boundary_candidate": False,
            "sample_offset_px": 0,
            "near_sample_offset_px": 0,
            "sample_count": 0,
            "side_mean_gray": [],
            "side_background_fraction": [],
            "near_side_background_fraction": [],
            "mean_gray_delta": 0.0,
            "background_side_index": None,
            "material_side_index": None,
        }

    normal_x = -dy / length
    normal_y = dx / length
    sample_offset = max(4, int(round(min(image_width, image_height) * 0.01)))
    near_sample_offset = max(2, min(sample_offset - 1, int(round(sample_offset * 0.25))))
    sample_count = max(12, min(24, int(round(length / 3.0))))
    side_samples: list[list[float]] = [[], []]
    near_side_samples: list[list[float]] = [[], []]

    for index in range(2, sample_count - 2):
        ratio = index / float(sample_count - 1)
        x = float(first[0]) + dx * ratio
        y = float(first[1]) + dy * ratio
        for side_index, sign in enumerate((-1.0, 1.0)):
            sample_x = int(round(x + sign * sample_offset * normal_x))
            sample_y = int(round(y + sign * sample_offset * normal_y))
            if 0 <= sample_x < image_width and 0 <= sample_y < image_height:
                side_samples[side_index].append(float(gray[sample_y, sample_x]))

            near_x = int(round(x + sign * near_sample_offset * normal_x))
            near_y = int(round(y + sign * near_sample_offset * normal_y))
            if 0 <= near_x < image_width and 0 <= near_y < image_height:
                near_side_samples[side_index].append(float(gray[near_y, near_x]))

    if (
        min(len(values) for values in side_samples) < 6
        or min(len(values) for values in near_side_samples) < 6
    ):
        return {
            "one_sided_boundary_candidate": False,
            "sample_offset_px": sample_offset,
            "near_sample_offset_px": near_sample_offset,
            "sample_count": min(
                min(len(values) for values in side_samples),
                min(len(values) for values in near_side_samples),
            ),
            "side_mean_gray": [],
            "side_background_fraction": [],
            "near_side_background_fraction": [],
            "mean_gray_delta": 0.0,
            "background_side_index": None,
            "material_side_index": None,
        }

    side_means = [
        sum(values) / len(values)
        for values in side_samples
    ]
    background_fractions = [
        sum(value >= 245.0 for value in values) / len(values)
        for values in side_samples
    ]
    near_background_fractions = [
        sum(value >= 245.0 for value in values) / len(values)
        for values in near_side_samples
    ]
    mean_delta = abs(side_means[0] - side_means[1])
    one_sided = (
        max(background_fractions) >= 0.70
        and min(background_fractions) <= 0.25
        and max(near_background_fractions) >= 0.60
        and min(near_background_fractions) <= 0.25
        and mean_delta >= 30.0
    )
    background_side_index: int | None = None
    material_side_index: int | None = None
    if one_sided:
        background_side_index = max(
            range(2),
            key=lambda index: (
                background_fractions[index],
                near_background_fractions[index],
                side_means[index],
            ),
        )
        material_side_index = 1 - background_side_index

    return {
        "one_sided_boundary_candidate": one_sided,
        "sample_offset_px": sample_offset,
        "near_sample_offset_px": near_sample_offset,
        "sample_count": min(
            min(len(values) for values in side_samples),
            min(len(values) for values in near_side_samples),
        ),
        "side_mean_gray": [round(value, 3) for value in side_means],
        "side_background_fraction": [
            round(value, 3)
            for value in background_fractions
        ],
        "near_side_background_fraction": [
            round(value, 3)
            for value in near_background_fractions
        ],
        "mean_gray_delta": round(mean_delta, 3),
        "background_side_index": background_side_index,
        "material_side_index": material_side_index,
    }


def _exterior_edge_mask(
    edges: Any,
    gray: Any,
    cv2: Any,
    np: Any,
) -> Any:
    """Keep only edge pixels immediately adjacent to exterior white background.

    This stays raster/topology-only.  It is intentionally stricter than the
    farther one-sided sampling check so nearby internal hatch lines cannot be
    promoted merely because the true silhouette is a few pixels away.
    """

    image_height, image_width = gray.shape[:2]
    radius = max(
        2,
        int(round(min(image_width, image_height) * 0.0025)),
    )
    background = np.where(gray >= 245, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (radius * 2 + 1, radius * 2 + 1),
    )
    near_background = cv2.dilate(background, kernel)
    return cv2.bitwise_and(edges, near_background)


def _segment_edge_support_fraction(
    edge_mask: Any,
    first: tuple[int, int],
    second: tuple[int, int],
    np: Any,
    *,
    radius: int = 1,
) -> float:
    """Measure candidate straight-line raster support without metric inference."""

    length = math.hypot(
        float(second[0] - first[0]),
        float(second[1] - first[1]),
    )
    sample_count = max(2, int(round(length)) + 1)
    xs = np.rint(np.linspace(first[0], second[0], sample_count)).astype(int)
    ys = np.rint(np.linspace(first[1], second[1], sample_count)).astype(int)
    height, width = edge_mask.shape[:2]

    hits = 0
    for x, y in zip(xs, ys, strict=True):
        x0 = max(0, int(x) - radius)
        x1 = min(width, int(x) + radius + 1)
        y0 = max(0, int(y) - radius)
        y1 = min(height, int(y) + radius + 1)
        if x0 < x1 and y0 < y1 and np.any(edge_mask[y0:y1, x0:x1] > 0):
            hits += 1

    return hits / sample_count


def _curved_annotation_candidates(
    gray: Any,
    cv2: Any,
    np: Any,
) -> list[dict[str, Any]]:
    """Return conservative exterior curved-boundary candidates.

    The fitted circle is used only to classify local raster curvature. Pixel
    center/radius values are intentionally discarded and never exposed as
    engineering geometry.
    """

    image_height, image_width = gray.shape[:2]
    ink = np.where(gray < 245, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)

    padded = cv2.copyMakeBorder(
        ink,
        1,
        1,
        1,
        1,
        cv2.BORDER_CONSTANT,
        value=0,
    )
    open_space = cv2.bitwise_not(padded)
    flooded = open_space.copy()
    flood_mask = np.zeros(
        (flooded.shape[0] + 2, flooded.shape[1] + 2),
        dtype=np.uint8,
    )
    cv2.floodFill(
        flooded,
        flood_mask,
        (0, 0),
        128,
    )
    enclosed = (open_space == 255) & (flooded != 128)
    silhouette = np.where(
        (padded > 0) | enclosed,
        255,
        0,
    ).astype(np.uint8)[1:-1, 1:-1]

    contours, _ = cv2.findContours(
        silhouette,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    minimum_area = float(image_width * image_height) * 0.002
    candidates: list[dict[str, Any]] = []

    for contour_index, contour in enumerate(contours):
        if cv2.contourArea(contour) < minimum_area:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter < 40.0:
            continue

        epsilon = max(0.8, min(2.0, perimeter * 0.0015))
        approximated = cv2.approxPolyDP(
            contour,
            epsilon,
            True,
        )
        points = [
            (float(point[0][0]), float(point[0][1]))
            for point in approximated
        ]
        point_count = len(points)
        if point_count < 5:
            continue

        passing: list[dict[str, Any]] = []
        maximum_window = min(12, point_count)
        for start_index in range(point_count):
            for window_size in range(5, maximum_window + 1):
                indices = [
                    (start_index + offset) % point_count
                    for offset in range(window_size)
                ]
                if len(set(indices)) != window_size:
                    continue
                sample = np.asarray(
                    [points[index] for index in indices],
                    dtype=float,
                )
                vectors = np.diff(sample, axis=0)
                segment_lengths = np.hypot(
                    vectors[:, 0],
                    vectors[:, 1],
                )
                if (
                    np.any(segment_lengths <= 1e-6)
                    or float(np.max(segment_lengths))
                    / max(float(np.median(segment_lengths)), 1e-6)
                    > 3.0
                ):
                    continue

                directions = np.unwrap(
                    np.arctan2(vectors[:, 1], vectors[:, 0])
                )
                turns = np.diff(directions)
                turns = (turns + np.pi) % (2.0 * np.pi) - np.pi
                significant_turns = turns[
                    np.abs(turns) >= math.radians(1.0)
                ]
                if len(significant_turns) < 3:
                    continue
                turn_sign = (
                    1.0
                    if float(np.median(significant_turns)) > 0.0
                    else -1.0
                )
                turn_consistency = float(
                    np.mean(significant_turns * turn_sign > 0.0)
                )
                turn_magnitudes = np.abs(significant_turns)
                mean_turn = float(np.mean(turn_magnitudes))
                turn_cv = float(
                    np.std(turn_magnitudes)
                    / max(mean_turn, 1e-9)
                )
                mean_turn_deg = math.degrees(mean_turn)
                if (
                    turn_consistency < 0.90
                    or not 3.0 <= mean_turn_deg <= 40.0
                    or turn_cv > 0.25
                ):
                    continue

                xs = sample[:, 0]
                ys = sample[:, 1]
                matrix = np.column_stack(
                    (2.0 * xs, 2.0 * ys, np.ones(len(sample)))
                )
                target = xs * xs + ys * ys
                try:
                    solution, _, _, _ = np.linalg.lstsq(
                        matrix,
                        target,
                        rcond=None,
                    )
                except np.linalg.LinAlgError:
                    continue
                center_x, center_y, constant = (
                    float(value)
                    for value in solution
                )
                radius_squared = (
                    constant
                    + center_x * center_x
                    + center_y * center_y
                )
                if radius_squared <= 1e-6:
                    continue
                radius = math.sqrt(radius_squared)
                distances = np.hypot(
                    xs - center_x,
                    ys - center_y,
                )
                residual_fraction = float(
                    np.max(np.abs(distances - radius))
                    / radius
                )
                if residual_fraction > 0.025:
                    continue

                angles = np.unwrap(
                    np.arctan2(
                        ys - center_y,
                        xs - center_x,
                    )
                )
                sweep_deg = abs(
                    math.degrees(
                        float(angles[-1] - angles[0])
                    )
                )
                if not 20.0 <= sweep_deg <= 200.0:
                    continue

                chord = math.hypot(
                    float(xs[-1] - xs[0]),
                    float(ys[-1] - ys[0]),
                )
                if chord <= 1e-6:
                    continue
                deviations = np.abs(
                    (ys[-1] - ys[0]) * xs
                    - (xs[-1] - xs[0]) * ys
                    + xs[-1] * ys[0]
                    - ys[-1] * xs[0]
                ) / chord
                if float(np.max(deviations)) / chord < 0.03:
                    continue

                passing.append(
                    {
                        "_indices": set(indices),
                        "_window_size": window_size,
                        "kind": "curved_boundary_candidate",
                        "endpoints_px": [
                            [
                                round(float(xs[0]), 3),
                                round(float(ys[0]), 3),
                            ],
                            [
                                round(float(xs[-1]), 3),
                                round(float(ys[-1]), 3),
                            ],
                        ],
                        "curve_trace_px": [
                            [
                                round(float(point[0]), 3),
                                round(float(point[1]), 3),
                            ]
                            for point in sample
                        ],
                        "curve_fit_residual_fraction": round(
                            residual_fraction,
                            4,
                        ),
                        "turn_consistency_fraction": round(
                            turn_consistency,
                            4,
                        ),
                        "turn_magnitude_cv": round(
                            turn_cv,
                            4,
                        ),
                        "sweep_deg_px": round(
                            sweep_deg,
                            3,
                        ),
                        "candidate_only": True,
                        "exterior_boundary_candidate": True,
                        "curve_classification_basis": (
                            "stable_cocircular_exterior_contour_turning"
                        ),
                        "_contour_index": contour_index,
                    }
                )

        selected: list[dict[str, Any]] = []
        for candidate in sorted(
            passing,
            key=lambda item: (
                -int(item["_window_size"]),
                float(item["curve_fit_residual_fraction"]),
                item["endpoints_px"],
            ),
        ):
            indices = candidate["_indices"]
            if any(
                len(indices.intersection(previous["_indices"]))
                / max(
                    1,
                    min(
                        len(indices),
                        len(previous["_indices"]),
                    ),
                )
                >= 0.80
                for previous in selected
            ):
                continue
            selected.append(candidate)

        for candidate in selected:
            candidate.pop("_indices", None)
            candidate.pop("_window_size", None)
            candidate.pop("_contour_index", None)
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            float(item["curve_fit_residual_fraction"]),
            -float(item["sweep_deg_px"]),
            item["endpoints_px"],
        )
    )
    return candidates[:128]


def _oblique_annotation_lines(
    edges: Any,
    image_width: int,
    image_height: int,
    cv2: Any,
    np: Any,
    *,
    gray: Any | None = None,
) -> list[dict[str, Any]]:
    """Return geometry-only oblique candidates with explicit exterior provenance."""

    hough_sources: list[tuple[Any, bool]] = [(edges, False)]
    if gray is not None:
        hough_sources.append(
            (
                _exterior_edge_mask(
                    edges,
                    gray,
                    cv2,
                    np,
                ),
                True,
            )
        )

    minimum_length = max(14.0, image_width * 0.009)
    maximum_length = math.hypot(image_width, image_height) * 0.45
    candidates: list[dict[str, Any]] = []

    for source_edges, exterior_boundary_candidate in hough_sources:
        raw = cv2.HoughLinesP(
            source_edges,
            1,
            np.pi / 180,
            threshold=max(18, round(image_width * 0.014)),
            minLineLength=max(14, round(image_width * 0.009)),
            maxLineGap=max(3, round(image_width * 0.0035)),
        )
        if raw is None:
            continue

        for x1, y1, x2, y2 in raw[:, 0]:
            dx = float(x2 - x1)
            dy = float(y2 - y1)
            length = math.hypot(dx, dy)
            if length < minimum_length or length > maximum_length:
                continue

            angle = math.degrees(math.atan2(dy, dx))
            normalized = abs(angle) % 180.0
            if normalized > 90.0:
                normalized = 180.0 - normalized
            if normalized <= 3.0 or abs(normalized - 90.0) <= 3.0:
                continue

            first = (int(x1), int(y1))
            second = (int(x2), int(y2))
            if second < first:
                first, second = second, first

            line_edge_support_fraction = _segment_edge_support_fraction(
                source_edges,
                first,
                second,
                np,
            )
            candidate = {
                "kind": "oblique_line_candidate",
                "endpoints_px": [
                    [first[0], first[1]],
                    [second[0], second[1]],
                ],
                "angle_deg": round(float(normalized), 3),
                "length_px": round(float(length), 2),
                "line_edge_support_fraction": round(
                    float(line_edge_support_fraction),
                    3,
                ),
                "candidate_only": True,
                "exterior_boundary_candidate": exterior_boundary_candidate,
            }
            if gray is not None:
                boundary_evidence = _one_sided_boundary_evidence(
                    gray,
                    first,
                    second,
                )
                candidate["boundary_evidence"] = boundary_evidence
                candidate["one_sided_boundary_candidate"] = bool(
                    boundary_evidence["one_sided_boundary_candidate"]
                )

            duplicate = False
            for previous in candidates:
                p0, p1 = previous["endpoints_px"]
                if (
                    math.hypot(first[0] - p0[0], first[1] - p0[1]) <= 4.0
                    and math.hypot(second[0] - p1[0], second[1] - p1[1]) <= 4.0
                    and abs(float(previous["angle_deg"]) - normalized) <= 3.0
                ):
                    if exterior_boundary_candidate:
                        previous["exterior_boundary_candidate"] = True
                    raw_previous_support = previous.get(
                        "line_edge_support_fraction"
                    )
                    previous_support = (
                        float(raw_previous_support)
                        if (
                            isinstance(raw_previous_support, (int, float))
                            and not isinstance(raw_previous_support, bool)
                        )
                        else 0.0
                    )
                    previous["line_edge_support_fraction"] = max(
                        previous_support,
                        float(line_edge_support_fraction),
                    )
                    duplicate = True
                    break
            if not duplicate:
                candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item.get("exterior_boundary_candidate") is not True,
            -float(item["length_px"]),
            item["endpoints_px"][0],
            item["endpoints_px"][1],
        )
    )
    return candidates[:128]

def _orthogonal_line_candidates(
    gray: Any,
    axis_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve geometry-only H/V line candidates independently of dimensions."""

    output: list[dict[str, Any]] = []
    for line in axis_lines:
        orientation = str(line.get("orientation") or "")
        x1 = line.get("x1")
        y1 = line.get("y1")
        x2 = line.get("x2")
        y2 = line.get("y2")
        if (
            orientation not in {"horizontal", "vertical"}
            or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in (x1, y1, x2, y2)
            )
        ):
            continue

        first = (int(round(float(x1))), int(round(float(y1))))
        second = (int(round(float(x2))), int(round(float(y2))))
        if orientation == "horizontal":
            axis = (float(y1) + float(y2)) / 2.0
            start = min(int(round(float(x1))), int(round(float(x2))))
            end = max(int(round(float(x1))), int(round(float(x2))))
        else:
            axis = (float(x1) + float(x2)) / 2.0
            start = min(int(round(float(y1))), int(round(float(y2))))
            end = max(int(round(float(y1))), int(round(float(y2))))
        if end <= start:
            continue

        ink_fraction, ink_run_fraction = _axis_ink_continuity(
            gray,
            orientation,
            axis,
            start,
            end,
        )
        output.append(
            {
                "orientation": orientation,
                "axis_px": round(float(axis), 3),
                "span_px": [start, end],
                "span_length_px": end - start,
                "axis_ink_fraction": ink_fraction,
                "axis_ink_run_fraction": ink_run_fraction,
                "boundary_evidence": _one_sided_boundary_evidence(
                    gray,
                    first,
                    second,
                ),
                "candidate_only": True,
            }
        )

    output.sort(
        key=lambda item: (
            str(item["orientation"]),
            float(item["axis_px"]),
            int(item["span_px"][0]),
            int(item["span_px"][1]),
        )
    )
    return output


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
    gradient_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)

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
        radial_alignment, radial_aligned_fraction = _radial_gradient_alignment(
            edges,
            gradient_x,
            gradient_y,
            global_x,
            global_y,
            radius,
        )
        if radial_alignment < 0.82 or radial_aligned_fraction < 0.65:
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
            if support < 0.90:
                continue
            radial_alignment, radial_aligned_fraction = _radial_gradient_alignment(
                edges,
                gradient_x,
                gradient_y,
                cx,
                cy,
                radius,
            )
            if radial_alignment < 0.82 or radial_aligned_fraction < 0.65:
                continue
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
        if not (x0 <= midpoint_x <= x0 + width and y0 <= midpoint_y <= y0 + height):
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
            if not buckets or abs(item[1] - mean(part[1] for part in buckets[-1])) > 3:
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
                intervals[index + 1][0] - intervals[index][1] for index in range(len(intervals) - 1)
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
            if not clusters or int(item["radius_px"]) - int(clusters[-1][-1]["radius_px"]) > 5:
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
    limit: int = 24,
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
                "segments_px": [
                    [int(start), int(end)]
                    for start, end in segments
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
        x, y, width, height = (int(bbox[key]) for key in ("x", "y", "width", "height"))
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
        "annotation_line_candidates": probe.get(
            "oblique_annotation_lines",
            [],
        ),
        "annotation_curve_candidates": probe.get(
            "curved_annotation_candidates",
            [],
        ),
        "regions": regions,
        "summary": {
            "region_count": len(regions),
            "circle_group_count": sum(len(region["circle_groups"]) for region in regions),
            "ring_count": sum(
                len(group["rings"]) for region in regions for group in region["circle_groups"]
            ),
            "linear_pattern_candidate_count": sum(
                len(region["linear_pattern_candidates"]) for region in regions
            ),
            "annotation_line_candidate_count": len(probe.get("oblique_annotation_lines", [])),
            "annotation_curve_candidate_count": len(
                probe.get("curved_annotation_candidates", [])
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


def _source_line_intersects_region(
    orientation: str,
    axis: float,
    start: int,
    end: int,
    region_bbox: list[int],
    *,
    margin: float,
) -> bool:
    """Return whether one orthogonal source line belongs to the candidate view region."""

    x, y, width, height = (float(value) for value in region_bbox)
    right = x + width
    bottom = y + height
    start_f = float(start)
    end_f = float(end)
    axis_f = float(axis)

    if orientation == "vertical":
        return (
            x - margin <= axis_f <= right + margin
            and end_f >= y - margin
            and start_f <= bottom + margin
        )
    if orientation == "horizontal":
        return (
            y - margin <= axis_f <= bottom + margin
            and end_f >= x - margin
            and start_f <= right + margin
        )
    return False


def _axis_ink_continuity(
    gray: Any,
    orientation: str,
    axis: float,
    start: int,
    end: int,
) -> tuple[float, float]:
    """Measure actual drafting-ink continuity along one H/V source line."""

    height, width = gray.shape[:2]
    lower = int(round(min(start, end)))
    upper = int(round(max(start, end)))
    axis_index = int(round(float(axis)))
    if orientation == "vertical":
        lower = max(0, lower)
        upper = min(height - 1, upper)
        left = max(0, axis_index - 1)
        right = min(width, axis_index + 2)
        if upper < lower or right <= left:
            return 0.0, 0.0
        samples = gray[lower : upper + 1, left:right].min(axis=1)
    elif orientation == "horizontal":
        lower = max(0, lower)
        upper = min(width - 1, upper)
        top = max(0, axis_index - 1)
        bottom = min(height, axis_index + 2)
        if upper < lower or bottom <= top:
            return 0.0, 0.0
        samples = gray[top:bottom, lower : upper + 1].min(axis=0)
    else:
        return 0.0, 0.0

    if len(samples) == 0:
        return 0.0, 0.0

    ink = samples <= 96
    ink_fraction = float(ink.mean())
    longest = 0
    current = 0
    for value in ink.tolist():
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return (
        round(ink_fraction, 5),
        round(float(longest) / float(len(samples)), 5),
    )


def _witness_line_evidence(
    witnesses: list[float],
    source_lines: list[tuple[str, float, int, int]],
    *,
    dimension_axis: float,
    witness_axis_tolerance: float,
    cross_tolerance: float,
    region_bbox: list[int],
    region_margin: float,
    gray: Any | None = None,
) -> list[dict[str, Any]]:
    """Preserve same-region merged orthogonal lines that produced each witness axis."""

    output: list[dict[str, Any]] = []
    for witness_index, witness in enumerate(witnesses):
        matched: list[dict[str, Any]] = []
        for orientation, axis, start, end in source_lines:
            if abs(float(axis) - float(witness)) > witness_axis_tolerance:
                continue
            if not _source_line_intersects_region(
                orientation,
                axis,
                start,
                end,
                region_bbox,
                margin=region_margin,
            ):
                continue
            record = {
                "orientation": orientation,
                "axis_px": round(float(axis), 3),
                "span_px": [int(start), int(end)],
                "span_length_px": int(end - start),
                "crosses_dimension_axis": (
                    float(start) - cross_tolerance
                    <= float(dimension_axis)
                    <= float(end) + cross_tolerance
                ),
            }
            if gray is not None:
                ink_fraction, ink_run_fraction = _axis_ink_continuity(
                    gray,
                    orientation,
                    axis,
                    start,
                    end,
                )
                record["axis_ink_fraction"] = ink_fraction
                record["axis_ink_run_fraction"] = ink_run_fraction
                if orientation == "horizontal":
                    boundary_first = (int(start), int(round(float(axis))))
                    boundary_second = (int(end), int(round(float(axis))))
                else:
                    boundary_first = (int(round(float(axis))), int(start))
                    boundary_second = (int(round(float(axis))), int(end))
                record["boundary_evidence"] = _one_sided_boundary_evidence(
                    gray,
                    boundary_first,
                    boundary_second,
                )
            matched.append(record)
        matched.sort(
            key=lambda item: (
                abs(float(item["axis_px"]) - float(witness)),
                -int(item["span_length_px"]),
                int(item["span_px"][0]),
            )
        )
        output.append(
            {
                "witness_index": witness_index,
                "position_px": float(witness),
                "source_lines": matched,
            }
        )
    return output


def _region_scoped_witnesses(
    witnesses: list[float],
    *,
    orientation: str,
    region_bbox: list[int],
    margin: float,
) -> list[float]:
    x, y, width, height = (float(value) for value in region_bbox)
    if orientation == "horizontal":
        lower, upper = x - margin, x + width + margin
    elif orientation == "vertical":
        lower, upper = y - margin, y + height + margin
    else:
        raise ValueError("candidate orientation must be horizontal or vertical")
    return [value for value in witnesses if lower <= float(value) <= upper]


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
        region["region_id"]: region["bbox_px"] for region in raw_evidence.get("regions", [])
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
            if axis < y - 0.15 * region_height or axis > region_bottom + 0.15 * region_height:
                continue
            region_witnesses = _region_scoped_witnesses(
                witnesses,
                orientation="horizontal",
                region_bbox=bbox,
                margin=float(witness_tolerance),
            )
            if len(region_witnesses) < 2:
                continue

            output.append(
                {
                    "candidate_id": f"DG{next_id}",
                    "region_id": region_id,
                    "orientation": "horizontal",
                    "axis_px": round(axis, 1),
                    "axis_local_norm": round((axis - y) / region_height, 5),
                    "line_span_px": [start, end],
                    "witness_positions_px": region_witnesses,
                    "witness_positions_local_norm": [
                        round((value - x) / region_width, 5)
                        for value in region_witnesses
                    ],
                    "witness_line_evidence": _witness_line_evidence(
                        region_witnesses,
                        vertical,
                        dimension_axis=axis,
                        witness_axis_tolerance=float(witness_dedup),
                        cross_tolerance=float(witness_tolerance),
                        region_bbox=bbox,
                        region_margin=float(witness_tolerance),
                        gray=gray,
                    ),
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
            if axis < x - 0.15 * region_width or axis > region_right + 0.15 * region_width:
                continue
            region_witnesses = _region_scoped_witnesses(
                witnesses,
                orientation="vertical",
                region_bbox=bbox,
                margin=float(witness_tolerance),
            )
            if len(region_witnesses) < 2:
                continue

            output.append(
                {
                    "candidate_id": f"DG{next_id}",
                    "region_id": region_id,
                    "orientation": "vertical",
                    "axis_px": round(axis, 1),
                    "axis_local_norm": round((axis - x) / region_width, 5),
                    "line_span_px": [start, end],
                    "witness_positions_px": region_witnesses,
                    "witness_positions_local_norm": [
                        round((value - y) / region_height, 5)
                        for value in region_witnesses
                    ],
                    "witness_line_evidence": _witness_line_evidence(
                        region_witnesses,
                        horizontal,
                        dimension_axis=axis,
                        witness_axis_tolerance=float(witness_dedup),
                        cross_tolerance=float(witness_tolerance),
                        region_bbox=bbox,
                        region_margin=float(witness_tolerance),
                        gray=gray,
                    ),
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
    min_fragment_length, max_fragment_length = fragment_length_limits(int(gray.shape[1]))

    probe_regions: list[dict[str, Any]] = []
    for index, region in enumerate(regions, start=1):
        probe_regions.append(
            {
                "region_id": f"R{index}",
                "bbox": {key: region[key] for key in ("x", "y", "width", "height")},
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
        "oblique_annotation_lines": _oblique_annotation_lines(
            edges,
            int(gray.shape[1]),
            int(gray.shape[0]),
            cv2,
            np,
            gray=gray,
        ),
        "curved_annotation_candidates": _curved_annotation_candidates(
            gray,
            cv2,
            np,
        ),
        "regions": probe_regions,
    }

    raw = _adapt_probe(probe)
    raw["schema"] = "raw-evidence-v1"
    raw["orthogonal_line_candidates"] = _orthogonal_line_candidates(
        gray,
        lines,
    )
    raw["summary"]["orthogonal_line_candidate_count"] = len(
        raw["orthogonal_line_candidates"]
    )
    raw["dimension_geometry_candidates"] = _dimension_geometry(
        gray,
        raw,
        cv2,
        np,
    )
    raw["summary"]["dimension_geometry_candidate_count"] = len(raw["dimension_geometry_candidates"])
    raw["notes"] = [
        "Raster geometry only. No OCR model, VLM, neural detector, or model weights were used.",
        "Dimension geometry is candidate-only: dimension-axis geometry plus perpendicular witness positions; no numeric label or engineering ownership is asserted.",
    ]
    return raw
