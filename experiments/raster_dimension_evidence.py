from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise SystemExit(
        "This feasibility probe requires opencv-python and numpy. "
        "It does not require any model weights."
    ) from exc


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
            group_axis = float(np.mean([value[1] for value in group]))
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
            float(np.mean([value[1] for value in group])),
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


def extract_dimension_geometry(
    image_path: Path,
    raw_evidence: dict,
) -> list[dict]:
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise SystemExit(f"Unable to read image: {image_path}")

    height, width = image.shape
    edges = cv2.Canny(image, 50, 150, apertureSize=3)

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
        region["region_id"]: region["bbox_px"]
        for region in raw_evidence.get("regions", [])
    }

    minimum_span = max(50, round(width * 0.028))
    witness_minimum = max(20, round(width * 0.011))
    witness_tolerance = max(5, round(width * 0.0045))
    witness_dedup = max(6, round(width * 0.004))

    output: list[dict] = []
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

            output.append(
                {
                    "candidate_id": f"DG{next_id}",
                    "region_id": region_id,
                    "orientation": "horizontal",
                    "axis_px": round(axis, 1),
                    "axis_local_norm": round((axis - y) / region_height, 5),
                    "line_span_px": [start, end],
                    "witness_positions_px": witnesses,
                    "witness_positions_local_norm": [
                        round((value - x) / region_width, 5)
                        for value in witnesses
                    ],
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

            output.append(
                {
                    "candidate_id": f"DG{next_id}",
                    "region_id": region_id,
                    "orientation": "vertical",
                    "axis_px": round(axis, 1),
                    "axis_local_norm": round((axis - x) / region_width, 5),
                    "line_span_px": [start, end],
                    "witness_positions_px": witnesses,
                    "witness_positions_local_norm": [
                        round((value - y) / region_height, 5)
                        for value in witnesses
                    ],
                    "status": "candidate_only_no_semantics",
                }
            )
            next_id += 1

    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add lightweight dimension witness geometry to RawEvidence",
    )
    parser.add_argument("image")
    parser.add_argument("raw_evidence")
    parser.add_argument("out")
    args = parser.parse_args()

    raw_path = Path(args.raw_evidence)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["schema"] = "raw-evidence-v1"
    payload["dimension_geometry_candidates"] = extract_dimension_geometry(
        Path(args.image),
        payload,
    )
    payload.setdefault("summary", {})[
        "dimension_geometry_candidate_count"
    ] = len(payload["dimension_geometry_candidates"])
    payload["notes"] = [
        "Raster geometry only. No OCR model, VLM, neural detector, or model weights were used.",
        "Dimension geometry is candidate-only: dimension-axis geometry plus perpendicular witness positions; no numeric label or engineering ownership is asserted.",
    ]

    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            payload["summary"],
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
