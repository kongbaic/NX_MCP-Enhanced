from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_MAX_CANDIDATES = 4


def candidate_band(candidate: dict[str, Any]) -> str:
    value = float(candidate["axis_local_norm"])
    orientation = str(candidate["orientation"])

    if orientation == "horizontal":
        if value <= 0.35:
            return "top"
        if value >= 0.60:
            return "bottom"
        return "middle"

    if orientation == "vertical":
        if value <= 0.40:
            return "left"
        if value >= 0.60:
            return "right"
        return "middle"

    raise ValueError(f"unsupported orientation: {orientation!r}")


def reduce_dimension_candidates(
    raw_evidence: dict[str, Any],
    query: dict[str, Any],
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> dict[str, Any]:
    if not 1 <= max_candidates <= DEFAULT_MAX_CANDIDATES:
        raise ValueError("max_candidates must be between 1 and 4")

    region_id = str(query["region_id"])
    orientation = str(query["orientation"])
    position_band = query.get("position_band")

    all_candidates = list(
        raw_evidence.get("dimension_geometry_candidates", [])
    )
    by_region = [
        item
        for item in all_candidates
        if item.get("region_id") == region_id
    ]
    by_orientation = [
        item
        for item in by_region
        if item.get("orientation") == orientation
    ]

    filtered = by_orientation
    if position_band is not None:
        filtered = [
            item
            for item in by_orientation
            if candidate_band(item) == position_band
        ]

    ranked = sorted(
        filtered,
        key=lambda item: (
            -len(item.get("witness_positions_px", [])),
            abs(float(item.get("axis_local_norm", 0.5)) - 0.5),
            str(item.get("candidate_id", "")),
        ),
    )
    selected = ranked[:max_candidates]

    return {
        "query_id": query.get("query_id"),
        "region_id": region_id,
        "orientation": orientation,
        "position_band": position_band,
        "counts": {
            "all": len(all_candidates),
            "after_region": len(by_region),
            "after_orientation": len(by_orientation),
            "after_band": len(filtered),
            "selected": len(selected),
        },
        "candidate_ids": [
            str(item["candidate_id"])
            for item in selected
        ],
        "candidates": [
            {
                **item,
                "position_band": candidate_band(item),
            }
            for item in selected
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically reduce RawEvidence dimension candidates "
            "before VLM or Human Confirmation."
        )
    )
    parser.add_argument("raw_evidence")
    parser.add_argument("queries")
    parser.add_argument("out")
    args = parser.parse_args()

    raw = json.loads(
        Path(args.raw_evidence).read_text(encoding="utf-8")
    )
    query_payload = json.loads(
        Path(args.queries).read_text(encoding="utf-8")
    )

    results = [
        reduce_dimension_candidates(raw, query)
        for query in query_payload.get("queries", [])
    ]
    output = {
        "schema": "dimension-candidate-reduction-v0",
        "results": results,
    }
    Path(args.out).write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "query_count": len(results),
                "selected_counts": {
                    str(item["query_id"]): item["counts"]["selected"]
                    for item in results
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
