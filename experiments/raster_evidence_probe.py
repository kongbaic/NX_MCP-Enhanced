from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - prototype guard
    raise SystemExit(
        "This feasibility probe requires opencv-python and numpy. "
        "It does not require any model weights."
    ) from exc


def _edge_support(
    edges: np.ndarray,
    cx: int,
    cy: int,
    radius: int,
    *,
    tol: int = 2,
) -> float:
    h, w = edges.shape
    hits = 0
    samples = 180
    for theta in np.linspace(0.0, 2.0 * np.pi, samples, endpoint=False):
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


def _axis_lines(edges: np.ndarray) -> list[dict[str, float | int | str]]:
    raw = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=80,
        minLineLength=35,
        maxLineGap=8,
    )
    result: list[dict[str, float | int | str]] = []
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


def _view_regions(
    shape: tuple[int, int],
    axis_lines: list[dict[str, float | int | str]],
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
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw * bh < min_area:
            continue
        boxes.append(
            {
                "x": x,
                "y": y,
                "width": bw,
                "height": bh,
                "area": bw * bh,
            }
        )
    boxes.sort(key=lambda item: item["area"], reverse=True)
    return boxes[:4]


def _circle_candidates(
    gray: np.ndarray,
    edges: np.ndarray,
    region: dict[str, int],
) -> list[dict[str, float | int]]:
    x = region["x"]
    y = region["y"]
    bw = region["width"]
    bh = region["height"]
    roi = gray[y : y + bh, x : x + bw]
    max_radius = max(12, min(120, min(bw, bh) // 2))

    circles = cv2.HoughCircles(
        roi,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(18, min(bw, bh) // 12),
        param1=120,
        param2=45,
        minRadius=8,
        maxRadius=max_radius,
    )
    if circles is None:
        return []

    scored: list[dict[str, float | int]] = []
    for cx, cy, radius in np.round(circles[0]).astype(int):
        gx, gy = x + int(cx), y + int(cy)
        support = _edge_support(edges, gx, gy, int(radius))
        if support < 0.82:
            continue
        scored.append(
            {
                "cx": gx,
                "cy": gy,
                "radius_px": int(radius),
                "edge_support": round(float(support), 3),
            }
        )

    scored.sort(
        key=lambda item: float(item["edge_support"]),
        reverse=True,
    )
    centers: list[dict[str, float | int]] = []
    min_center_dist = max(12, min(bw, bh) * 0.08)
    for item in scored:
        if any(
            math.hypot(
                int(item["cx"]) - int(prev["cx"]),
                int(item["cy"]) - int(prev["cy"]),
            )
            < min_center_dist
            for prev in centers
        ):
            continue
        centers.append(item)
        if len(centers) >= 4:
            break

    enriched: list[dict[str, float | int]] = []
    for center in centers:
        cx, cy = int(center["cx"]), int(center["cy"])
        radial: list[tuple[float, int]] = []
        for radius in range(8, max_radius + 1):
            support = _edge_support(edges, cx, cy, radius, tol=1)
            if support >= 0.90:
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
    edges: np.ndarray,
    region: dict[str, int],
) -> list[dict[str, object]]:
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

    x0 = region["x"]
    y0 = region["y"]
    bw = region["width"]
    bh = region["height"]
    fragments: list[tuple[str, float, int, int]] = []

    for x1, y1, x2, y2 in raw[:, 0]:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if not (x0 <= mx <= x0 + bw and y0 <= my <= y0 + bh):
            continue
        dx, dy = int(x2 - x1), int(y2 - y1)
        length = math.hypot(dx, dy)
        if not 10 <= length <= 90:
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

    groups: list[dict[str, object]] = []
    for orientation in ("horizontal", "vertical"):
        items = sorted(
            (item for item in fragments if item[0] == orientation),
            key=lambda item: item[1],
        )
        buckets: list[list[tuple[str, float, int, int]]] = []
        for item in items:
            if (
                not buckets
                or abs(item[1] - np.mean([part[1] for part in buckets[-1]])) > 3
            ):
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
                intervals[index + 1][0] - intervals[index][1]
                for index in range(len(intervals) - 1)
            ]
            positive_gaps = [gap for gap in gaps if gap > 2]
            if len(positive_gaps) < 2:
                continue

            groups.append(
                {
                    "orientation": orientation,
                    "axis_px": round(
                        float(np.mean([part[1] for part in bucket])),
                        1,
                    ),
                    "segments": intervals,
                    "positive_gaps_px": positive_gaps,
                    "kind": "dashed_or_centerline_candidate",
                }
            )
    return groups


def probe(image_path: Path) -> tuple[dict[str, object], np.ndarray]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"Unable to read image: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = _axis_lines(edges)
    regions = _view_regions(gray.shape, lines)

    evidence_regions: list[dict[str, object]] = []
    for index, region in enumerate(regions, start=1):
        evidence_regions.append(
            {
                "region_id": f"R{index}",
                "bbox": {
                    key: region[key]
                    for key in ("x", "y", "width", "height")
                },
                "circle_evidence": _circle_candidates(
                    gray,
                    edges,
                    region,
                ),
                "fragment_groups": _fragment_groups(edges, region),
            }
        )

    output: dict[str, object] = {
        "schema": "raster-evidence-feasibility-v0",
        "source": str(image_path),
        "image": {
            "width": int(gray.shape[1]),
            "height": int(gray.shape[0]),
        },
        "notes": [
            "No OCR, VLM, neural detector, or model weights were used.",
            "Regions and geometry are pixel evidence only; no engineering semantics are asserted.",
        ],
        "axis_line_count": len(lines),
        "regions": evidence_regions,
    }

    overlay = image.copy()
    colors = [
        (0, 0, 255),
        (255, 0, 0),
        (0, 128, 0),
        (255, 0, 255),
    ]
    for index, item in enumerate(evidence_regions):
        color = colors[index % len(colors)]
        bbox = item["bbox"]
        x = int(bbox["x"])
        y = int(bbox["y"])
        bw = int(bbox["width"])
        bh = int(bbox["height"])
        cv2.rectangle(
            overlay,
            (x, y),
            (x + bw, y + bh),
            color,
            3,
        )
        cv2.putText(
            overlay,
            str(item["region_id"]),
            (x + 5, y + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
        )
        for circle in item["circle_evidence"]:
            cv2.circle(
                overlay,
                (int(circle["cx"]), int(circle["cy"])),
                int(circle["radius_px"]),
                color,
                2,
            )
    return output, overlay


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lightweight raster engineering-drawing evidence probe",
    )
    parser.add_argument("image")
    parser.add_argument("--json-out")
    parser.add_argument("--overlay-out")
    args = parser.parse_args()

    output, overlay = probe(Path(args.image))
    payload = json.dumps(output, ensure_ascii=False, indent=2)

    if args.json_out:
        Path(args.json_out).write_text(
            payload + "\n",
            encoding="utf-8",
        )
    else:
        print(payload)

    if args.overlay_out:
        cv2.imwrite(args.overlay_out, overlay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
