from __future__ import annotations

from typing import Any

from .dimension_candidate_reducer import reduce_dimension_candidates
from .dimension_witness_anchors import enrich_reduced_dimension_candidates

_HORIZONTAL_BANDS = ("top", "middle", "bottom")
_VERTICAL_BANDS = ("left", "middle", "right")


def build_reader_visual_aid(
    raw_evidence: dict[str, Any],
    *,
    max_candidates_per_bucket: int = 4,
    nearest_anchor_count: int = 3,
    max_anchor_distance_local_norm: float = 0.04,
) -> dict[str, Any]:
    """Build a bounded geometry-only visual aid for first-pass Reader use."""

    if raw_evidence.get("schema") != "raw-evidence-v1":
        raise ValueError("reader visual aid requires raw-evidence-v1")
    if not 1 <= max_candidates_per_bucket <= 4:
        raise ValueError("max_candidates_per_bucket must be between 1 and 4")

    regions = raw_evidence.get("regions", [])
    if not isinstance(regions, list):
        raise ValueError("regions must be a list")

    pseudo_dimensions: list[dict[str, Any]] = []
    overflow_buckets: list[dict[str, Any]] = []

    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = region.get("region_id")
        if not isinstance(region_id, str) or not region_id:
            continue

        for orientation, bands in (
            ("horizontal", _HORIZONTAL_BANDS),
            ("vertical", _VERTICAL_BANDS),
        ):
            for band in bands:
                query = {
                    "region_id": region_id,
                    "orientation": orientation,
                    "band": band,
                    "max_candidates": max_candidates_per_bucket,
                }
                reduced = reduce_dimension_candidates(raw_evidence, query)
                candidate_count = int(reduced.get("candidate_count", 0))
                if candidate_count == 0:
                    continue

                bucket_id = f"{region_id}.{orientation}.{band}"
                if reduced.get("status") != "reduced":
                    overflow_buckets.append(
                        {
                            "bucket_id": bucket_id,
                            "region_id": region_id,
                            "orientation": orientation,
                            "band": band,
                            "status": "overflow",
                            "candidate_count": candidate_count,
                            "candidates": [],
                            "reason": reduced.get("reason"),
                        }
                    )
                    continue

                pseudo_dimensions.append(
                    {
                        "dimension_id": bucket_id,
                        "bucket_id": bucket_id,
                        "region_id": region_id,
                        "orientation": orientation,
                        "band": band,
                        "status": "bounded",
                        "candidate_count": candidate_count,
                        "candidates": reduced.get("candidates", []),
                    }
                )

    enriched = enrich_reduced_dimension_candidates(
        raw_evidence,
        {"dimensions": pseudo_dimensions},
        nearest_count=nearest_anchor_count,
        max_distance_local_norm=max_anchor_distance_local_norm,
    )

    bounded_buckets = enriched.get("dimensions", [])
    candidate_buckets = [
        *bounded_buckets,
        *overflow_buckets,
    ]
    candidate_buckets.sort(key=lambda item: str(item["bucket_id"]))

    compact_regions = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        compact_regions.append(
            {
                "region_id": region.get("region_id"),
                "bbox_px": region.get("bbox_px"),
                "bbox_norm": region.get("bbox_norm"),
                "circle_groups": region.get("circle_groups", []),
                "linear_pattern_candidates": region.get(
                    "linear_pattern_candidates",
                    [],
                ),
            }
        )

    bucket_sizes = [
        int(item.get("candidate_count", 0))
        for item in candidate_buckets
    ]

    return {
        "schema": "reader-visual-aid-v1",
        "source_schema": "raw-evidence-v1",
        "semantics_policy": "geometry_only_no_engineering_claims",
        "source_drawing_authoritative": True,
        "image": raw_evidence.get("image"),
        "regions": compact_regions,
        "candidate_buckets": candidate_buckets,
        "summary": {
            "region_count": len(compact_regions),
            "bucket_count": len(candidate_buckets),
            "bounded_bucket_count": len(bounded_buckets),
            "overflow_bucket_count": len(overflow_buckets),
            "max_bucket_candidate_count": max(bucket_sizes, default=0),
            "raw_dimension_candidate_count": len(
                raw_evidence.get("dimension_geometry_candidates", [])
            ),
        },
        "rules": {
            "bucket_key": "region_id + orientation + normalized_position_band",
            "max_candidates_per_bucket": max_candidates_per_bucket,
            "candidate_truncation": False,
            "engineering_semantics_asserted": False,
            "numeric_dimension_labels_asserted": False,
        },
    }
