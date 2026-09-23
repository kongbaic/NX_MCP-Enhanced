from __future__ import annotations

import copy
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


def _anchor_pool(
    region: dict[str, Any],
    orientation: str,
) -> tuple[str, float, list[dict[str, Any]]]:
    bbox = region.get("bbox_px")
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(value, (int, float)) for value in bbox)
    ):
        raise ValueError("region bbox_px must contain four numeric values")

    x, y, width, height = (float(value) for value in bbox)
    region_id = str(region.get("region_id") or "")
    anchors: list[dict[str, Any]] = []

    if orientation == "horizontal":
        axis = "x"
        denominator = width
        anchors.extend(
            [
                {
                    "kind": "region_bbox_edge",
                    "ref": f"{region_id}.bbox.left",
                    "position_px": x,
                },
                {
                    "kind": "region_bbox_edge",
                    "ref": f"{region_id}.bbox.right",
                    "position_px": x + width,
                },
            ]
        )
        compatible_linear_orientation = "vertical"
        circle_index = 0
    elif orientation == "vertical":
        axis = "y"
        denominator = height
        anchors.extend(
            [
                {
                    "kind": "region_bbox_edge",
                    "ref": f"{region_id}.bbox.top",
                    "position_px": y,
                },
                {
                    "kind": "region_bbox_edge",
                    "ref": f"{region_id}.bbox.bottom",
                    "position_px": y + height,
                },
            ]
        )
        compatible_linear_orientation = "horizontal"
        circle_index = 1
    else:
        raise ValueError("candidate orientation must be horizontal or vertical")

    for group in region.get("circle_groups", []):
        if not isinstance(group, dict):
            continue
        center = group.get("center_px")
        group_id = group.get("circle_group_id")
        if not (
            isinstance(center, list)
            and len(center) == 2
            and isinstance(center[circle_index], (int, float))
            and isinstance(group_id, str)
            and group_id
        ):
            continue
        anchors.append(
            {
                "kind": "circle_center_axis",
                "ref": f"{region_id}.{group_id}.center_{axis}",
                "position_px": float(center[circle_index]),
            }
        )

    for index, item in enumerate(
        region.get("linear_pattern_candidates", []),
        start=1,
    ):
        if not isinstance(item, dict):
            continue
        if item.get("orientation") != compatible_linear_orientation:
            continue
        position = item.get("axis_px")
        if not isinstance(position, (int, float)):
            continue
        anchors.append(
            {
                "kind": "linear_pattern_axis",
                "ref": f"{region_id}.linear_pattern.{index:03d}",
                "position_px": float(position),
                "source_kind": item.get("kind"),
                "dash_score": item.get("dash_score"),
            }
        )

    return axis, denominator, anchors


def enrich_reduced_dimension_candidates(
    raw_evidence: dict[str, Any],
    reduced_payload: dict[str, Any],
    *,
    nearest_count: int = 3,
    max_distance_local_norm: float = 0.04,
) -> dict[str, Any]:
    """Attach geometry-only nearest-anchor evidence to reduced candidates."""

    if not 1 <= nearest_count <= 5:
        raise ValueError("nearest_count must be between 1 and 5")
    if not 0 < max_distance_local_norm <= 0.25:
        raise ValueError(
            "max_distance_local_norm must be greater than 0 and at most 0.25"
        )

    regions = _region_lookup(raw_evidence)
    output = copy.deepcopy(reduced_payload)
    dimensions = output.get("dimensions", [])
    if not isinstance(dimensions, list):
        raise ValueError("reduced dimensions must be a list")

    witness_total = 0
    candidate_total = 0

    for dimension in dimensions:
        if not isinstance(dimension, dict):
            continue
        candidates = dimension.get("candidates", [])
        if not isinstance(candidates, list):
            raise ValueError("dimension candidates must be a list")

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_total += 1
            region_id = candidate.get("region_id")
            orientation = candidate.get("orientation")
            if not isinstance(region_id, str) or region_id not in regions:
                raise ValueError(f"unknown candidate region_id: {region_id!r}")
            if not isinstance(orientation, str):
                raise ValueError("candidate orientation must be present")

            axis, denominator, anchors = _anchor_pool(
                regions[region_id],
                orientation,
            )
            if denominator <= 0:
                raise ValueError("region axis span must be positive")

            witnesses = candidate.get("witness_positions_px", [])
            if not isinstance(witnesses, list):
                raise ValueError("witness_positions_px must be a list")

            enriched_witnesses: list[dict[str, Any]] = []
            for witness_index, witness in enumerate(witnesses):
                if not isinstance(witness, (int, float)):
                    continue
                witness_total += 1
                ranked = []
                for anchor in anchors:
                    distance = abs(float(witness) - float(anchor["position_px"]))
                    ranked.append(
                        {
                            **anchor,
                            "distance_px": round(distance, 3),
                            "distance_local_norm": round(
                                distance / denominator,
                                5,
                            ),
                        }
                    )
                ranked.sort(
                    key=lambda item: (
                        float(item["distance_px"]),
                        str(item["kind"]),
                        str(item["ref"]),
                    )
                )
                nearby = [
                    item
                    for item in ranked
                    if float(item["distance_local_norm"])
                    <= max_distance_local_norm
                ]
                enriched_witnesses.append(
                    {
                        "witness_index": witness_index,
                        "position_px": float(witness),
                        "axis": axis,
                        "nearest_anchors": nearby[:nearest_count],
                    }
                )

            candidate["witness_anchor_evidence"] = enriched_witnesses

    output["anchor_schema_version"] = "1.0"
    output["anchor_policy"] = (
        "geometry_only_no_engineering_ownership_claims"
    )
    output["anchor_summary"] = {
        "candidate_count": candidate_total,
        "witness_count": witness_total,
        "nearest_anchor_count": nearest_count,
        "max_distance_local_norm": max_distance_local_norm,
    }
    return output
