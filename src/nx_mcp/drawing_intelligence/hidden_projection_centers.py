from __future__ import annotations

import math

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


def derive_raster_hidden_bore_center_candidates(
    candidate: dict[str, Any],
    *,
    region: dict[str, Any],
    view_kind: str,
    profile_inventory: list[dict[str, Any]],
    source_raster_path: str | None,
) -> list[dict[str, Any]]:
    """Prove *both* projected bore axes from centerlines and matched hidden walls.

    A label and two dimension witnesses are necessary but insufficient.
    The independently supported pair of material faces must bound a common
    raster band. Each centerline must have one unique mirrored pair of
    dashed wall strokes within that band. Pixels prove physical identity,
    never nominal hole diameters, spacing or engineering coordinates.
    """
    if (
        candidate.get("accepted_token") is None
        or candidate.get("orientation") != "horizontal"
        or not source_raster_path
    ):
        return []
    region_id = str(candidate.get("region_id") or "")
    if region_id != str(region.get("region_id") or "") or not region_id:
        return []
    witnesses = candidate.get("witness_positions_px")
    if (
        not isinstance(witnesses, list)
        or len(witnesses) != 2
        or not all(type(value) in (int, float) for value in witnesses)
        or abs(float(witnesses[0]) - float(witnesses[1])) < 12
    ):
        return []
    region_bbox = region.get("bbox_px")
    if not isinstance(region_bbox, list) or len(region_bbox) != 4:
        return []
    region_width = region_bbox[2]
    if not isinstance(region_width, (int, float)) or region_width <= 0:
        return []
    feature_axis = _AXIS_BY_VIEW_ORIENTATION.get((view_kind, "vertical"))
    rail = candidate.get("axis_px")
    if feature_axis is None or type(rail) not in (int, float):
        return []

    try:
        import cv2
        image = cv2.imread(source_raster_path, cv2.IMREAD_GRAYSCALE)
    except (ImportError, OSError, ValueError, TypeError):
        return []
    if image is None or image.ndim != 2:
        return []

    # Candidate faces come from independent structural geometry, not OCR.
    faces = [
        item for item in profile_inventory
        if isinstance(item, dict)
        and item.get("kind") == "profile_edge_candidate"
        and item.get("region_id") == region_id
        and item.get("source_orientation") == "horizontal"
        and type(item.get("independent_geometry_source_count")) is int
        and item["independent_geometry_source_count"] >= 1
        and type(item.get("position_px")) in (int, float)
        and isinstance(item.get("span_px"), list)
        and len(item["span_px"]) == 2
        and all(type(v) in (int, float) for v in item["span_px"])
        and all(min(item["span_px"]) + 1 <= float(w) <= max(item["span_px"]) - 1 for w in witnesses)
    ]
    faces.sort(key=lambda item: float(item["position_px"]), reverse=True)
    face_groups: list[list[dict[str, Any]]] = []
    for face in faces:
        if (
            not face_groups
            or abs(float(face["position_px"]) - float(face_groups[-1][0]["position_px"])) > 2.5
        ):
            face_groups.append([face])
        else:
            face_groups[-1].append(face)
    # Only the two nearest distinct backed faces before the dimension rail.
    levels = [
        group for group in face_groups
        if float(group[0]["position_px"]) < float(rail) - 10
    ]
    if len(levels) < 2:
        return []
    low_face, high_face = levels[:2]
    lower = sum(float(x["position_px"]) for x in low_face) / len(low_face)
    upper = sum(float(x["position_px"]) for x in high_face) / len(high_face)
    if not 25 <= lower - upper <= 180:
        return []
    y0, y1 = math.ceil(upper + 4), math.floor(lower - 4)
    if y0 < 0 or y1 >= image.shape[0] or y1 - y0 < 24:
        return []

    patterns = region.get("linear_pattern_candidates")
    if not isinstance(patterns, list):
        return []
    tolerance = max(2.5, float(region_width) * 0.006)
    max_offset = min(35.0, (lower - upper) * 0.46, float(region_width) * 0.12)
    min_offset = max(6.0, (lower - upper) * 0.08)
    if min_offset >= max_offset:
        return []

    proven: list[dict[str, Any]] = []
    for witness_index, witness in enumerate(witnesses):
        center_patterns = [
            (index, item)
            for index, item in enumerate(patterns)
            if isinstance(item, dict)
            and item.get("orientation") == "vertical"
            and type(item.get("axis_px")) in (int, float)
            and abs(float(item["axis_px"]) - float(witness)) <= tolerance
            and type(item.get("segment_count")) is int
            and item["segment_count"] >= 3
            and type(item.get("dash_score")) in (int, float)
            and item["dash_score"] >= 0.60
            and isinstance(item.get("span_px"), list)
            and len(item["span_px"]) == 2
            and min(item["span_px"]) <= upper
            and max(item["span_px"]) >= lower
        ]
        if len(center_patterns) != 1:
            return []
        center_index, center = center_patterns[0]
        center_axis = float(center["axis_px"])
        center_x = round(center_axis)
        if not 0 <= center_x < image.shape[1]:
            return []
        center_ink = image[y0:y1, center_x] < 145
        if float(center_ink.mean()) < 0.25:
            return []

        strokes: list[tuple[int, Any]] = []
        for x in range(
            max(0, math.floor(center_axis - max_offset)),
            min(image.shape[1], math.ceil(center_axis + max_offset) + 1),
        ):
            distance = abs(x - center_axis)
            if not min_offset <= distance <= max_offset:
                continue
            ink = image[y0:y1, x] < 145
            fraction = float(ink.mean())
            if not 0.25 <= fraction <= 0.85:
                continue
            run_count = 0
            begin: int | None = None
            for i, dark in enumerate([*ink, False]):
                if dark and begin is None:
                    begin = i
                elif not dark and begin is not None:
                    if i - begin >= 3:
                        run_count += 1
                    begin = None
            if run_count >= 3:
                strokes.append((x, ink))
        groups: list[list[tuple[int, Any]]] = []
        for stroke in strokes:
            if groups and stroke[0] - groups[-1][-1][0] <= 2:
                groups[-1].append(stroke)
            else:
                groups.append([stroke])
        left = [group for group in groups if group[-1][0] < center_axis - min_offset]
        right = [group for group in groups if group[0][0] > center_axis + min_offset]
        possible: list[tuple[int, int, float]] = []
        for left_group in left:
            for right_group in right:
                left_stroke = left_group[len(left_group) // 2]
                right_stroke = right_group[len(right_group) // 2]
                left_x, left_mask = left_stroke
                right_x, right_mask = right_stroke
                if (
                    abs((left_x + right_x) / 2 - center_axis) > tolerance
                    or abs((center_axis - left_x) - (right_x - center_axis)) > 2 * tolerance
                ):
                    continue
                similarity = float(
                    (left_mask & right_mask).sum()
                    / max(1, (left_mask | right_mask).sum())
                )
                if similarity >= 0.85:
                    possible.append((left_x, right_x, similarity))
        if len(possible) != 1:
            return []
        left_x, right_x, similarity = possible[0]
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            return []
        entity_key = (
            f"{region_id}.HIDDEN_BORE_CENTER.{candidate_id}.{witness_index + 1:02d}"
        )
        proven.append({
            "candidate_id": candidate_id,
            "witness_index": witness_index,
            "kind": "hidden_projection_center_axis",
            "entity_key": entity_key,
            "ref": f"{entity_key}.center",
            "position_px": center_axis,
            "feature_axis": feature_axis,
            "pattern_orientation": "vertical",
            "source_pattern_indices": [center_index],
            "hidden_wall_positions_px": [left_x, right_x],
            "hidden_wall_ink_similarity": round(similarity, 4),
            "structural_face_positions_px": [round(upper, 3), round(lower, 3)],
            "selection_basis": "unique_raster_centerline_and_symmetric_hidden_walls",
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        })
    return proven if len(proven) == 2 else []


def prove_hidden_bore_axis_overlapping_profile(
    candidate: dict[str, Any],
    *,
    witness_index: int,
    region_id: str,
    profile_inventory: list[dict[str, Any]],
    source_raster_path: str | None,
) -> bool:
    """Identify an unowned dashed bore axis which masquerades as a profile.

    Reject boundary ownership only; a bore feature, hole type, or dimension
    coordinate may not be asserted by this test. Two independent material
    faces plus exactly one mirrored dashed-wall pair must support the same
    internal centerline. Missing/ambiguous evidence returns False.
    """
    if (
        not source_raster_path
        or candidate.get("orientation") != "horizontal"
        or candidate.get("accepted_token") is None
    ):
        return False
    witnesses = candidate.get("witness_anchor_evidence")
    if not isinstance(witnesses, list):
        return False
    matches = [
        item for item in witnesses
        if isinstance(item, dict) and item.get("witness_index") == witness_index
    ]
    if len(matches) != 1:
        return False
    anchors = matches[0].get("nearest_anchors")
    if not isinstance(anchors, list):
        return False
    profiles = [
        item for item in anchors
        if isinstance(item, dict)
        and item.get("kind") == "profile_edge_candidate"
        and item.get("source_orientation") == "vertical"
        and item.get("relative_extreme_side") not in {"min", "max"}
        and item.get("endpoint_junction_count") == 0
        and isinstance(item.get("position_px"), (int, float))
        and not isinstance(item.get("position_px"), bool)
        and isinstance(item.get("span_px"), list)
        and len(item["span_px"]) == 2
        and all(type(v) in (int, float) for v in item["span_px"])
    ]
    if len(profiles) != 1:
        return False
    profile = profiles[0]
    pos = float(profile["position_px"])
    dashed = [
        item for item in anchors
        if isinstance(item, dict)
        and item.get("kind") == "linear_pattern_axis"
        and item.get("source_kind") == "dashed_or_centerline_candidate"
        and type(item.get("position_px")) in (int, float)
        and type(item.get("dash_score")) in (int, float)
        and float(item["dash_score"]) >= 0.60
        and abs(float(item["position_px"]) - pos) <= 2.5
    ]
    if len(dashed) != 1:
        return False

    face_items = [
        item for item in profile_inventory
        if isinstance(item, dict)
        and item.get("region_id") == region_id
        and item.get("source_orientation") == "horizontal"
        and type(item.get("position_px")) in (int, float)
        and isinstance(item.get("span_px"), list)
        and len(item["span_px"]) == 2
        and all(type(v) in (int, float) for v in item["span_px"])
        and min(profile["span_px"]) < float(item["position_px"]) < max(profile["span_px"])
        and min(item["span_px"]) + 3 < pos < max(item["span_px"]) - 3
        and type(item.get("junction_count")) is int
        and item["junction_count"] >= 2
    ]
    face_levels = sorted(float(item["position_px"]) for item in face_items)
    distinct_levels: list[float] = []
    for level in face_levels:
        if not distinct_levels or level - distinct_levels[-1] > 2.5:
            distinct_levels.append(level)
    if len(distinct_levels) != 2:
        return False
    top, bottom = distinct_levels
    if not 24 <= bottom - top <= 180:
        return False

    try:
        import cv2
        image = cv2.imread(source_raster_path, cv2.IMREAD_GRAYSCALE)
    except (ImportError, OSError, ValueError, TypeError):
        return False
    if image is None:
        return False
    y0 = round(top + 4)
    y1 = round(bottom - 4)
    cx = round(pos)
    if y0 < 0 or y1 >= image.shape[0] or y1 - y0 < 20:
        return False
    if cx < 34 or cx >= image.shape[1] - 34:
        return False

    def stroke(x: int) -> Any:
        ink = image[y0:y1, x] < 145
        fraction = float(ink.mean())
        if fraction < 0.25 or fraction >= 0.90:
            return None
        run_count = 0
        start: int | None = None
        for row, dark in enumerate([*ink, False]):
            if dark and start is None:
                start = row
            elif not dark and start is not None:
                if row - start >= 3:
                    run_count += 1
                start = None
        return ink if run_count >= 3 else None

    center = stroke(cx)
    if center is None:
        return False
    pairs: list[tuple[int, int]] = []
    for left_x in range(cx - 34, cx - 5):
        left = stroke(left_x)
        if left is None:
            continue
        for right_x in range(cx + 6, cx + 35):
            right = stroke(right_x)
            if right is None or abs((left_x + right_x) / 2.0 - pos) > 2.5:
                continue
            agreement = float(
                (left & right).sum() / max(1, (left | right).sum())
            )
            if agreement >= 0.85:
                pairs.append((left_x, right_x))

    # Several raster columns can be the same thick ink stroke. Only one
    # distinct mirrored pair of walls is allowed; two distances stay ambiguous.
    if not pairs:
        return False
    widths = sorted((right - left) / 2.0 for left, right in pairs)
    clusters: list[float] = []
    for width in widths:
        if not clusters or width - clusters[-1] > 3.0:
            clusters.append(width)
    return len(clusters) == 1
