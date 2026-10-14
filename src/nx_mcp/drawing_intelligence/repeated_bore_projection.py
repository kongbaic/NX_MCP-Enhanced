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
