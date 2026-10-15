from __future__ import annotations

from typing import Any


def derive_repeated_bore_projection_correlations(
    *,
    dimensions: list[Any],
    hidden_center_records: list[dict[str, Any]],
    regions: list[dict[str, Any]],
    profile_inventory: list[dict[str, Any]],
    view_kinds: dict[str, str],
) -> list[dict[str, Any]]:
    """Audit two front-view bore centers sharing one side-view projection.

    This records one-to-many *projection evidence*, not a feature association.
    A single side-view center must never collapse a pair of physical holes.
    Raster coordinates prove coincident orthographic face levels, not mm.
    """
    region_by_id = {
        str(region.get("region_id")): region
        for region in regions if isinstance(region, dict) and region.get("region_id")
    }
    pairs: list[tuple[Any, list[dict[str, Any]], str]] = []
    offsets: list[tuple[Any, dict[str, Any], str]] = []
    for dimension in dimensions:
        ends = getattr(dimension, "endpoints", ())
        if len(ends) != 2 or getattr(dimension, "unresolved_reason", None):
            continue
        if (
            dimension.axis == "X"
            and [end.role for end in ends] == ["entity_center", "entity_center"]
        ):
            keys = [end.entity_key for end in ends]
            matching = [
                record for record in hidden_center_records
                if record.get("entity_key") in keys
                and record.get("selection_basis")
                == "unique_raster_centerline_and_symmetric_hidden_walls"
                and record.get("feature_axis") == "Z"
                and record.get("engineering_coordinate_inferred_from_pixels") is False
                and record.get("pixel_geometry_used_for_identity_only") is True
            ]
            if (
                len(set(keys)) != 2 or len(matching) != 2
                or {r.get("witness_index") for r in matching} != {0, 1}
                or len({r.get("candidate_id") for r in matching}) != 1
                or any(
                    f"hybrid:proven-hidden-walls:{end.entity_key}" not in end.evidence
                    for end in ends
                )
            ):
                continue
            matching.sort(key=lambda r: r["witness_index"])
            if [r["entity_key"] for r in matching] != keys:
                continue
            faces = [r.get("structural_face_positions_px") for r in matching]
            if (
                not all(isinstance(face, list) and len(face) == 2 for face in faces)
                or faces[0] != faces[1]
                or not all(type(v) in (int, float) for v in faces[0])
                or float(faces[0][1]) - float(faces[0][0]) < 20
            ):
                continue
            region_ids = {r["entity_key"].split(".", 1)[0] for r in matching}
            if len(region_ids) == 1:
                region_id = next(iter(region_ids))
                if view_kinds.get(region_id) == "front":
                    pairs.append((dimension, matching, region_id))
        if dimension.axis == "Y" and {end.role for end in ends} == {
            "entity_center", "overall_max"
        }:
            center = next(end for end in ends if end.role == "entity_center")
            matching = [
                record for record in hidden_center_records
                if record.get("entity_key") == center.entity_key
                and record.get("selection_basis")
                == "unique_raster_mirrored_hidden_wall_offset_center"
                and record.get("feature_axis") == "Z"
                and record.get("engineering_coordinate_inferred_from_pixels") is False
                and record.get("pixel_geometry_used_for_identity_only") is True
            ]
            if (
                len(matching) != 1
                or "hybrid:raster-proven-hidden-bore-offset-center:"
                + str(center.entity_key) not in center.evidence
            ):
                continue
            region_id = matching[0]["entity_key"].split(".", 1)[0]
            if view_kinds.get(region_id) == "side":
                offsets.append((dimension, matching[0], region_id))

    candidates: list[dict[str, Any]] = []
    for pair_dimension, pair, front_id in pairs:
        front_region = region_by_id.get(front_id, {})
        front_bbox = front_region.get("bbox_px")
        if not isinstance(front_bbox, list) or len(front_bbox) != 4:
            continue
        for offset_dimension, offset, side_id in offsets:
            side_region = region_by_id.get(side_id, {})
            side_bbox = side_region.get("bbox_px")
            if (
                front_id == side_id or not isinstance(side_bbox, list)
                or len(side_bbox) != 4
                or not all(type(v) in (int, float) for v in [*front_bbox, *side_bbox])
                or front_bbox[0] + front_bbox[2] >= side_bbox[0]
                or min(front_bbox[1] + front_bbox[3], side_bbox[1] + side_bbox[3])
                <= max(front_bbox[1], side_bbox[1])
            ):
                continue
            center_px = offset.get("position_px")
            if type(center_px) not in (int, float):
                continue
            faces = [
                item for item in profile_inventory
                if isinstance(item, dict)
                and item.get("region_id") == side_id
                and item.get("kind") == "profile_edge_candidate"
                and item.get("source_orientation") == "horizontal"
                and type(item.get("position_px")) in (int, float)
                and isinstance(item.get("span_px"), list)
                and len(item["span_px"]) == 2
                and all(type(v) in (int, float) for v in item["span_px"])
                and min(item["span_px"]) + 2 < center_px < max(item["span_px"]) - 2
                and type(item.get("junction_count")) is int
                and item["junction_count"] >= 2
                and (
                    item.get("independent_geometry_source_count", 0) >= 1
                    or item.get("non_dimension_crossing_source_count", 0) >= 2
                )
            ]
            levels = sorted(float(item["position_px"]) for item in faces)
            clustered: list[float] = []
            for level in levels:
                if not clustered or level - clustered[-1] > 2.5:
                    clustered.append(level)
            if len(clustered) != 2:
                continue
            front_faces = [float(v) for v in pair[0]["structural_face_positions_px"]]
            residuals = [
                abs(a - b) for a, b in zip(front_faces, clustered)
            ]
            # A drawn orthographic side view must share the same *raster*
            # Z-level material faces as the front view. This is only identity.
            if max(residuals) > 3.0:
                continue
            candidates.append({
                "basis": "two_front_hidden_bore_centers_co_project_to_one_side_hidden_axis",
                "front_dimension_key": pair_dimension.key,
                "side_dimension_key": offset_dimension.key,
                "front_entity_keys": [item["entity_key"] for item in pair],
                "side_projection_entity_key": offset["entity_key"],
                "feature_axis": "Z",
                "front_hole_count": 2,
                "side_projected_axis_count": 1,
                "source_pattern_indices": [
                    item["source_pattern_indices"] for item in pair
                ] + [offset.get("source_pattern_indices", [])],
                "shared_face_level_residuals_px": [round(v, 3) for v in residuals],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
                "modeling_authoritative": False,
            })
    # Competing viable pattern matches are deliberately not chosen.
    return candidates if len(candidates) == 1 else []



def derive_repeated_bore_callout_leader_proofs(
    *,
    callout_ledger: list[dict[str, Any]],
    correlations: list[dict[str, Any]],
    hidden_center_records: list[dict[str, Any]],
    annotation_lines: list[dict[str, Any]],
    profile_inventory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Identify a leader terminating at a unique co-projected bore group.

    An OCR callout outside both view bounding boxes may still point into one
    view. One oblique leader must meet an independently proven material face
    at the *projected center*, using only a bounded forward shaft extension.
    This proof is advisory: it transports count/through semantics without
    accepting an ambiguous diameter glyph or merging the physical holes.
    """
    import math

    if not all(
        isinstance(value, list)
        for value in (callout_ledger, correlations, hidden_center_records,
                      annotation_lines, profile_inventory)
    ):
        return []

    def bounds_of(value: Any) -> tuple[float, float, float, float] | None:
        if not (
            isinstance(value, list)
            and len(value) == 4
            and all(
                isinstance(point, list)
                and len(point) >= 2
                and all(type(v) in (int, float) for v in point[:2])
                for point in value
            )
        ):
            return None
        return (
            min(float(p[0]) for p in value),
            min(float(p[1]) for p in value),
            max(float(p[0]) for p in value),
            max(float(p[1]) for p in value),
        )

    results: list[dict[str, Any]] = []
    for callout in callout_ledger:
        if not isinstance(callout, dict):
            continue
        fact = callout.get("facts")
        bind = callout.get("binding")
        callout_index = callout.get("source_item_index")
        box = bounds_of(callout.get("binding_bbox"))
        if (
            type(callout_index) is not int
            or box is None
            or not isinstance(fact, dict)
            or fact.get("count") != 2
            or fact.get("through") is not True
            or not isinstance(bind, dict)
            or bind.get("status") not in {"unresolved", "callout_backed"}
        ):
            continue
        x0, y0, x1, y1 = box
        text_height = y1 - y0
        touch_limit = max(6.0, text_height * 0.25)
        plausible: list[dict[str, Any]] = []

        for relation in correlations:
            if not isinstance(relation, dict):
                continue
            if (
                relation.get("basis")
                != "two_front_hidden_bore_centers_co_project_to_one_side_hidden_axis"
                or relation.get("modeling_authoritative") is not False
                or relation.get("engineering_coordinate_inferred_from_pixels") is not False
                or relation.get("front_hole_count") != 2
                or relation.get("side_projected_axis_count") != 1
            ):
                continue
            keys = relation.get("front_entity_keys")
            side_key = relation.get("side_projection_entity_key")
            if (
                isinstance(side_key, str)
                and sum(
                    1 for candidate in correlations
                    if isinstance(candidate, dict)
                    and candidate.get("side_projection_entity_key") == side_key
                ) != 1
            ):
                # Never resolve duplicated / competing projected-center owners
                # merely because they yield the same leader intersection.
                continue
            if (
                not isinstance(keys, list) or len(keys) != 2
                or any(not isinstance(k, str) for k in keys)
                or len(set(keys)) != 2
                or not isinstance(side_key, str)
            ):
                continue
            centers = [
                record for record in hidden_center_records
                if isinstance(record, dict)
                and record.get("entity_key") == side_key
                and record.get("selection_basis")
                == "unique_raster_mirrored_hidden_wall_offset_center"
                and record.get("engineering_coordinate_inferred_from_pixels") is False
                and record.get("pixel_geometry_used_for_identity_only") is True
            ]
            if len(centers) != 1 or type(centers[0].get("position_px")) not in (int, float):
                continue
            axis_position = float(centers[0]["position_px"])
            region_id = side_key.split(".", 1)[0]
            faces = [
                profile for profile in profile_inventory
                if isinstance(profile, dict)
                and profile.get("region_id") == region_id
                and profile.get("kind") == "profile_edge_candidate"
                and profile.get("source_orientation") == "horizontal"
                and type(profile.get("position_px")) in (float, int)
                and type(profile.get("junction_count")) is int
                and profile["junction_count"] >= 2
                and isinstance(profile.get("span_px"), list)
                and len(profile["span_px"]) == 2
                and all(type(v) in (float, int) for v in profile["span_px"])
                and min(profile["span_px"]) + 2 < axis_position
                < max(profile["span_px"]) - 2
                and (
                    profile.get("independent_geometry_source_count", 0) >= 1
                    or profile.get("non_dimension_crossing_source_count", 0) >= 2
                )
            ]
            for line_index, raw_line in enumerate(annotation_lines):
                if not isinstance(raw_line, dict):
                    continue
                ends = raw_line.get("endpoints_px")
                if not (
                    isinstance(ends, list) and len(ends) == 2
                    and all(
                        isinstance(pt, list) and len(pt) >= 2
                        and all(type(v) in (int, float) for v in pt[:2])
                        for pt in ends
                    )
                ):
                    continue
                first, second = [
                    (float(pt[0]), float(pt[1])) for pt in ends
                ]

                def distance_to_label(point: tuple[float, float]) -> float:
                    return math.hypot(
                        max(x0 - point[0], 0.0, point[0] - x1),
                        max(y0 - point[1], 0.0, point[1] - y1),
                    )

                if distance_to_label(first) > distance_to_label(second):
                    first, second = second, first
                touch = distance_to_label(first)
                dx = second[0] - first[0]
                dy = second[1] - first[1]
                shaft = math.hypot(dx, dy)
                if (
                    touch > touch_limit
                    or distance_to_label(second) <= touch + 8.0
                    or shaft < 20.0
                    or abs(dx) < 3.0 or abs(dy) < 3.0
                ):
                    continue
                angle = math.degrees(math.atan2(abs(dy), abs(dx)))
                if not 25 <= angle <= 80:
                    continue
                for face in faces:
                    face_position = float(face["position_px"])
                    scalar = (face_position - first[1]) / dy
                    if scalar <= 1.0:
                        continue
                    arrow_extension = (scalar - 1.0) * shaft
                    if arrow_extension > min(35.0, shaft * 0.60):
                        continue
                    intersection = first[0] + dx * scalar
                    span = face["span_px"]
                    if not (
                        min(span) + 2.0 < intersection < max(span) - 2.0
                    ):
                        continue
                    residual = abs(intersection - axis_position)
                    tolerance = max(4.0, min(6.0, text_height * 0.14))
                    if residual > tolerance:
                        continue
                    plausible.append({
                        "callout_source_item_index": callout_index,
                        "front_entity_keys": keys,
                        "side_projection_entity_key": side_key,
                        "front_dimension_key": relation.get("front_dimension_key"),
                        "side_dimension_key": relation.get("side_dimension_key"),
                        "leader_segment_index": line_index,
                        "material_face_ref": face.get("ref"),
                        "leader_face_intersection_px": [
                            round(intersection, 3), round(face_position, 3)
                        ],
                        "center_axis_residual_px": round(residual, 3),
                        "leader_forward_extension_px": round(arrow_extension, 3),
                        "basis": "unique_oblique_leader_tip_on_face_of_proven_repeated_bore_projection",
                        "ocr_count": 2,
                        "ocr_through": True,
                        "diameter_authoritative": False,
                        "geometry_binding_authoritative": False,
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_identity_only": True,
                    })

        # A single uniquely grounded projected-center target is required.
        # Ambiguous or competing leader shafts/nearby faces remain blocking.
        unique = {
            (proof["side_projection_entity_key"], proof["leader_segment_index"],
             proof["material_face_ref"]): proof
            for proof in plausible
        }
        if len(unique) == 1:
            results.extend(unique.values())
    return results
