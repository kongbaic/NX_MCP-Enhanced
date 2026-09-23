from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, pstdev


def _norm(value: float, denominator: float) -> float:
    return round(value / denominator, 5)


def _cluster_rings(
    circles: list[dict],
    image_width: int,
    image_height: int,
) -> list[dict]:
    if not circles:
        return []

    groups: dict[tuple[int, int], list[dict]] = {}
    for circle in circles:
        key = (int(circle["cx"]), int(circle["cy"]))
        groups.setdefault(key, []).append(circle)

    output: list[dict] = []
    for group_index, ((cx, cy), items) in enumerate(
        sorted(groups.items()),
        start=1,
    ):
        items = sorted(items, key=lambda item: int(item["radius_px"]))
        clusters: list[list[dict]] = []
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


def _fragment_score(item: dict) -> float:
    segments = item.get("segments", [])
    gaps = [gap for gap in item.get("positive_gaps_px", []) if gap > 0]
    if len(segments) < 3 or len(gaps) < 2:
        return 0.0

    density = min(len(segments) / 6.0, 1.0)
    if mean(gaps) > 0:
        gap_cv = pstdev(gaps) / mean(gaps)
        regularity = 1.0 / (1.0 + gap_cv)
    else:
        regularity = 0.0

    lengths = [max(0, end - start) for start, end in segments]
    mean_length = mean(lengths)
    mean_gap = mean(gaps)
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
    groups: list[dict],
    image_width: int,
    image_height: int,
    region: dict,
    *,
    limit: int = 8,
) -> list[dict]:
    scored: list[dict] = []
    for group in groups:
        score = _fragment_score(group)
        if score < 0.30:
            continue

        orientation = group["orientation"]
        axis_denominator = (
            image_height if orientation == "horizontal" else image_width
        )
        span_denominator = (
            image_width if orientation == "horizontal" else image_height
        )
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
                "axis_norm": _norm(
                    float(group["axis_px"]),
                    axis_denominator,
                ),
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


def adapt(probe: dict) -> dict:
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


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Compact raster probe output into RawEvidence v0",
    )
    parser.add_argument("probe_json")
    parser.add_argument("out_json")
    args = parser.parse_args()

    probe = json.loads(
        Path(args.probe_json).read_text(encoding="utf-8")
    )
    output = adapt(probe)
    Path(args.out_json).write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
