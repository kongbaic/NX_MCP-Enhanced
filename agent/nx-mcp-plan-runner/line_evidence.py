"""Deterministic, non-semantic raster line-evidence prototype.

This module deliberately does not perform OCR or infer drawing semantics.  It
only reports pixel-space horizontal/vertical line candidates, line-style
evidence, arrowhead candidates, and nearby line candidates for arrow tips.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np


_ROUND_DIGITS = 4


def _round(value: float) -> float:
    return round(float(value), _ROUND_DIGITS)


def _distance_point_segment(
    point: tuple[float, float], segment: tuple[int, int, int, int]
) -> tuple[float, tuple[float, float]]:
    px, py = point
    x1, y1, x2, y2 = segment
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - x1, py - y1), (float(x1), float(y1))
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    closest = (x1 + t * dx, y1 + t * dy)
    return math.hypot(px - closest[0], py - closest[1]), closest


def _runs(values: np.ndarray) -> list[tuple[bool, int]]:
    if values.size == 0:
        return []
    result: list[tuple[bool, int]] = []
    current = bool(values[0])
    length = 1
    for raw in values[1:]:
        value = bool(raw)
        if value == current:
            length += 1
        else:
            result.append((current, length))
            current = value
            length = 1
    result.append((current, length))
    return result


def _style_evidence(occupancy_vector: np.ndarray) -> dict[str, Any]:
    length = int(occupancy_vector.size)
    occupancy = float(np.mean(occupancy_vector)) if length else 0.0
    sequence = _runs(occupancy_vector)
    black_runs = [size for black, size in sequence if black]
    internal_gaps = [
        size
        for index, (black, size) in enumerate(sequence)
        if not black and 0 < index < len(sequence) - 1
    ]

    solid_score = max(0.0, min(1.0, (occupancy - 0.55) / 0.4))
    if internal_gaps:
        largest_gap = max(internal_gaps)
        solid_score *= max(0.0, 1.0 - largest_gap / max(4.0, length * 0.08))

    dashed_score = 0.0
    if len(black_runs) >= 3 and len(internal_gaps) >= 2:
        black_mean = float(np.mean(black_runs))
        gap_mean = float(np.mean(internal_gaps))
        black_cv = float(np.std(black_runs) / black_mean) if black_mean else 1.0
        gap_cv = float(np.std(internal_gaps) / gap_mean) if gap_mean else 1.0
        periodicity = max(0.0, 1.0 - min(1.0, (black_cv + gap_cv) / 1.2))
        count_score = min(1.0, len(black_runs) / 5.0)
        gap_score = min(1.0, gap_mean / 2.0)
        dashed_score = periodicity * count_score * gap_score

    dash_dot_score = 0.0
    if len(black_runs) >= 4 and len(internal_gaps) >= 3:
        even = black_runs[0::2]
        odd = black_runs[1::2]
        if len(even) >= 2 and len(odd) >= 2:
            even_mean = float(np.mean(even))
            odd_mean = float(np.mean(odd))
            long_mean = max(even_mean, odd_mean)
            short_mean = min(even_mean, odd_mean)
            ratio = long_mean / max(1.0, short_mean)
            long_runs = even if even_mean >= odd_mean else odd
            short_runs = odd if even_mean >= odd_mean else even
            long_cv = float(np.std(long_runs) / max(1.0, long_mean))
            short_cv = float(np.std(short_runs) / max(1.0, short_mean))
            alternation = max(0.0, 1.0 - min(1.0, (long_cv + short_cv) / 1.0))
            ratio_score = max(0.0, min(1.0, (ratio - 1.5) / 2.0))
            dash_dot_score = alternation * ratio_score * min(1.0, len(black_runs) / 6.0)

    scores = {
        "solid": _round(solid_score),
        "dashed": _round(dashed_score),
        "dash_dot": _round(dash_dot_score),
    }
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_style, best_score = ordered[0]
    second_score = ordered[1][1]
    style = best_style if best_score >= 0.55 and best_score - second_score >= 0.08 else "unknown"
    confidence = best_score if style != "unknown" else min(best_score, 0.49)
    return {
        "occupancy": _round(occupancy),
        "run_stats": {
            "black_run_count": len(black_runs),
            "black_run_lengths_px": black_runs,
            "internal_gap_count": len(internal_gaps),
            "internal_gap_lengths_px": internal_gaps,
        },
        "style": style,
        "style_scores": scores,
        "confidence": _round(confidence),
    }


def _extract_fragments(binary: np.ndarray) -> list[dict[str, Any]]:
    height, width = binary.shape
    minimum = max(7, min(height, width) // 100)
    threshold = max(10, min(height, width) // 90)
    detected = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi / 180,
        threshold=threshold,
        minLineLength=minimum,
        maxLineGap=1,
    )
    fragments: set[tuple[str, int, int, int]] = set()
    if detected is None:
        return []
    for entry in detected[:, 0, :]:
        x1, y1, x2, y2 = (int(value) for value in entry)
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dx >= minimum and dy <= max(2, int(dx * 0.04)):
            start, end = sorted((x1, x2))
            fragments.add(("horizontal", int(round((y1 + y2) / 2)), start, end))
        elif dy >= minimum and dx <= max(2, int(dy * 0.04)):
            start, end = sorted((y1, y2))
            fragments.add(("vertical", int(round((x1 + x2) / 2)), start, end))
    return [
        {"orientation": orientation, "coord": coord, "start": start, "end": end}
        for orientation, coord, start, end in sorted(fragments)
    ]


def _group_fragments(binary: np.ndarray, fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    height, width = binary.shape
    coord_tolerance = 2
    max_gap = max(24, min(height, width) // 40)
    groups: list[dict[str, Any]] = []
    ordered = sorted(
        fragments,
        key=lambda item: (item["orientation"], item["coord"], item["start"], item["end"]),
    )
    for fragment in ordered:
        matches = [
            group
            for group in groups
            if group["orientation"] == fragment["orientation"]
            and abs(group["coord"] - fragment["coord"]) <= coord_tolerance
            and fragment["start"] <= group["end"] + max_gap
            and fragment["end"] >= group["start"] - max_gap
        ]
        if matches:
            group = sorted(matches, key=lambda item: (abs(item["coord"] - fragment["coord"]), item["start"]))[0]
            group["raw"].append(fragment)
            coords = [item["coord"] for item in group["raw"]]
            group["coord"] = int(round(float(np.median(coords))))
            group["start"] = min(group["start"], fragment["start"])
            group["end"] = max(group["end"], fragment["end"])
        else:
            groups.append({**fragment, "raw": [fragment.copy()]})

    # Hough commonly reports both edges of the same thin stroke. Merge those
    # duplicate supports while retaining all original fragments.
    merged: list[dict[str, Any]] = []
    for group in sorted(groups, key=lambda item: (item["orientation"], item["coord"], item["start"])):
        duplicate = next(
            (
                item
                for item in merged
                if item["orientation"] == group["orientation"]
                and abs(item["coord"] - group["coord"]) <= coord_tolerance
                and min(item["end"], group["end"]) - max(item["start"], group["start"])
                >= 0.6 * min(item["end"] - item["start"], group["end"] - group["start"])
            ),
            None,
        )
        if duplicate:
            duplicate["raw"].extend(group["raw"])
            duplicate["start"] = min(duplicate["start"], group["start"])
            duplicate["end"] = max(duplicate["end"], group["end"])
            duplicate["coord"] = int(round(float(np.median([x["coord"] for x in duplicate["raw"]]))))
        else:
            merged.append(group)

    result: list[dict[str, Any]] = []
    for group in merged:
        orientation = group["orientation"]
        coord, start, end = group["coord"], group["start"], group["end"]
        if end - start < max(8, min(height, width) // 90):
            continue
        if orientation == "horizontal":
            y0, y1 = max(0, coord - 1), min(height, coord + 2)
            vector = np.max(binary[y0:y1, start : end + 1], axis=0) > 0
            segment = [start, coord, end, coord]
            raw_segments = [[item["start"], item["coord"], item["end"], item["coord"]] for item in group["raw"]]
        else:
            x0, x1 = max(0, coord - 1), min(width, coord + 2)
            vector = np.max(binary[start : end + 1, x0:x1], axis=1) > 0
            segment = [coord, start, coord, end]
            raw_segments = [[item["coord"], item["start"], item["coord"], item["end"]] for item in group["raw"]]
        style = _style_evidence(vector)
        result.append(
            {
                "orientation": orientation,
                "segment_px": segment,
                "fragments_px": sorted({tuple(item) for item in raw_segments}),
                **style,
            }
        )
    result.sort(key=lambda item: (item["orientation"], item["segment_px"]))
    for index, item in enumerate(result, start=1):
        item["id"] = f"L{index:04d}"
        item["fragments_px"] = [list(fragment) for fragment in item["fragments_px"]]
    return result


def _detect_arrowheads(
    binary: np.ndarray, lines: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    height, width = binary.shape
    candidates: list[dict[str, Any]] = []
    minimum_support = max(24, min(height, width) // 30)
    depth = max(9, min(15, min(height, width) // 35))
    half_width = max(6, min(10, min(height, width) // 50))
    for line in lines:
        x1, y1, x2, y2 = line["segment_px"]
        length = math.hypot(x2 - x1, y2 - y1)
        if length < minimum_support:
            continue
        if line["orientation"] == "horizontal":
            trials = [((x1, y1), (1, 0), (-1.0, 0.0)), ((x2, y2), (-1, 0), (1.0, 0.0))]
        else:
            trials = [((x1, y1), (0, 1), (0.0, -1.0)), ((x2, y2), (0, -1), (0.0, 1.0))]
        for tip, inward, direction in trials:
            profile: list[int] = []
            for distance in range(2, depth + 1):
                cx = tip[0] + inward[0] * distance
                cy = tip[1] + inward[1] * distance
                count = 0
                for offset in range(-half_width, half_width + 1):
                    if abs(offset) <= 1:
                        continue
                    px = cx if line["orientation"] == "horizontal" else cx + offset
                    py = cy + offset if line["orientation"] == "horizontal" else cy
                    if 0 <= px < width and 0 <= py < height and binary[py, px] > 0:
                        count += 1
                profile.append(count)
            active = sum(value > 0 for value in profile)
            midpoint = max(1, len(profile) // 2)
            near_mean = float(np.mean(profile[:midpoint]))
            far_mean = float(np.mean(profile[midpoint:]))
            # A filled wedge broadens away from its tip.  A plain line endpoint
            # or a perpendicular crossing does not have this off-axis profile.
            if active < max(4, len(profile) // 2) or sum(profile) < 10 or far_mean <= near_mean + 0.4:
                continue
            growth = max(0.0, min(1.0, (far_mean - near_mean) / 3.0))
            coverage = min(1.0, active / max(1.0, len(profile)))
            confidence = 0.45 * coverage + 0.55 * growth
            min_x = max(0, tip[0] - (half_width if line["orientation"] == "vertical" else depth))
            min_y = max(0, tip[1] - (half_width if line["orientation"] == "horizontal" else depth))
            max_x = min(width - 1, tip[0] + (half_width if line["orientation"] == "vertical" else depth))
            max_y = min(height - 1, tip[1] + (half_width if line["orientation"] == "horizontal" else depth))
            candidates.append(
                {
                    "tip_px": [int(tip[0]), int(tip[1])],
                    "direction_px": [direction[0], direction[1]],
                    "bbox_px": [int(min_x), int(min_y), int(max_x - min_x + 1), int(max_y - min_y + 1)],
                    "confidence": _round(confidence),
                    "_support_line_ref": line["id"],
                }
            )
    deduplicated: dict[tuple[int, int, float, float], dict[str, Any]] = {}
    for item in candidates:
        key = (*item["tip_px"], *item["direction_px"])
        previous = deduplicated.get(key)
        if previous is None or item["confidence"] > previous["confidence"]:
            deduplicated[key] = item
    candidates = sorted(deduplicated.values(), key=lambda item: (item["tip_px"], item["direction_px"]))
    for index, item in enumerate(candidates, start=1):
        item["id"] = f"A{index:04d}"
    return candidates


def _dimension_candidates(lines: list[dict[str, Any]], arrows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in lines:
        supported = [arrow for arrow in arrows if arrow["_support_line_ref"] == line["id"]]
        opposing_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for index, first in enumerate(supported):
            first_direction = np.asarray(first["direction_px"], dtype=float)
            for second in supported[index + 1 :]:
                second_direction = np.asarray(second["direction_px"], dtype=float)
                if float(np.dot(first_direction, second_direction)) <= -0.9:
                    opposing_pairs.append((first, second))
        if opposing_pairs:
            pair = max(
                opposing_pairs,
                key=lambda item: (item[0]["confidence"] + item[1]["confidence"], item[0]["id"], item[1]["id"]),
            )
            refs = sorted((pair[0]["id"], pair[1]["id"]))
            confidence = min(
                1.0,
                0.35 + 0.2 * line["confidence"] + 0.225 * pair[0]["confidence"] + 0.225 * pair[1]["confidence"],
            )
            result.append(
                {
                    "line_ref": line["id"],
                    "arrow_refs": refs,
                    "confidence": _round(confidence),
                }
            )
    result.sort(key=lambda item: (item["line_ref"], item["arrow_refs"]))
    for index, item in enumerate(result, start=1):
        item["id"] = f"D{index:04d}"
    return result


def _retain_supported_arrows(
    arrows: list[dict[str, Any]], dimensions: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    referenced = {ref for item in dimensions for ref in item["arrow_refs"]}
    retained = [item for item in arrows if item["id"] in referenced]
    id_map: dict[str, str] = {}
    for index, item in enumerate(retained, start=1):
        old_id = item["id"]
        item["id"] = f"A{index:04d}"
        item.pop("_support_line_ref", None)
        id_map[old_id] = item["id"]
    normalized_dimensions: list[dict[str, Any]] = []
    for item in dimensions:
        refs = sorted(id_map[ref] for ref in item["arrow_refs"] if ref in id_map)
        if not refs:
            continue
        normalized_dimensions.append({**item, "arrow_refs": refs})
    normalized_dimensions.sort(key=lambda item: (item["line_ref"], item["arrow_refs"]))
    for index, item in enumerate(normalized_dimensions, start=1):
        item["id"] = f"D{index:04d}"
    return retained, normalized_dimensions


def _endpoint_candidates(
    lines: list[dict[str, Any]],
    arrows: list[dict[str, Any]],
    dimensions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dimension_lines_by_arrow: dict[str, set[str]] = {}
    for dimension in dimensions:
        for arrow_ref in dimension["arrow_refs"]:
            dimension_lines_by_arrow.setdefault(arrow_ref, set()).add(dimension["line_ref"])
    endpoints: list[dict[str, Any]] = []
    ambiguities: list[dict[str, Any]] = []
    for arrow in arrows:
        arrow_id = arrow["id"]
        tip = tuple(float(value) for value in arrow["tip_px"])
        direction = np.asarray(arrow["direction_px"], dtype=float)
        candidates: list[dict[str, Any]] = []
        for line in lines:
            if line["id"] in dimension_lines_by_arrow.get(arrow_id, set()):
                continue
            distance, intersection = _distance_point_segment(tip, tuple(line["segment_px"]))
            if distance > 12.0:
                continue
            x1, y1, x2, y2 = line["segment_px"]
            line_vector = np.asarray([x2 - x1, y2 - y1], dtype=float)
            line_vector /= max(1.0, float(np.linalg.norm(line_vector)))
            perpendicularity = 1.0 - abs(float(np.dot(line_vector, direction)))
            compatible = perpendicularity >= 0.65
            confidence = math.exp(-distance / 6.0) * (0.55 + 0.45 * max(0.0, perpendicularity))
            candidates.append(
                {
                    "line_ref": line["id"],
                    "distance_px": _round(distance),
                    "intersection_px": [_round(intersection[0]), _round(intersection[1])],
                    "orientation_compatible": bool(compatible),
                    "confidence": _round(confidence),
                }
            )
        candidates.sort(key=lambda item: (item["distance_px"], item["line_ref"]))
        if not candidates:
            status = "none"
        elif len(candidates) == 1:
            status = "unique"
        else:
            first, second = candidates[0], candidates[1]
            status = "ambiguous" if second["distance_px"] - first["distance_px"] <= 2.0 else "unique"
        endpoints.append({"arrow_ref": arrow_id, "status": status, "line_candidates": candidates})
        if status == "ambiguous":
            refs = [arrow_id, candidates[0]["line_ref"], candidates[1]["line_ref"]]
            ambiguities.append(
                {
                    "id": f"U{len(ambiguities) + 1:04d}",
                    "refs": refs,
                    "reason": "nearest candidate line distances are not separable",
                }
            )
    return endpoints, ambiguities


def analyze_image(path: str | os.PathLike[str]) -> dict[str, Any]:
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    image_path = Path(path)
    raw = np.fromfile(image_path, dtype=np.uint8)
    if raw.size == 0:
        raise ValueError("input image is empty")
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("input is not a decodable raster image")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    fragments = _extract_fragments(binary)
    lines = _group_fragments(binary, fragments)
    arrows = _detect_arrowheads(binary, lines)
    dimensions = _dimension_candidates(lines, arrows)
    arrows, dimensions = _retain_supported_arrows(arrows, dimensions)
    endpoints, ambiguities = _endpoint_candidates(lines, arrows, dimensions)
    return {
        "image": {"width_px": int(image.shape[1]), "height_px": int(image.shape[0])},
        "lines": lines,
        "arrowheads": arrows,
        "dimension_line_candidates": dimensions,
        "endpoint_candidates": endpoints,
        "ambiguities": ambiguities,
    }


def compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return the stable Reader-facing subset without recomputing evidence."""
    lines_by_id = {item["id"]: item for item in evidence["lines"]}
    arrows_by_id = {item["id"]: item for item in evidence["arrowheads"]}
    endpoints_by_arrow = {
        item["arrow_ref"]: item for item in evidence["endpoint_candidates"]
    }

    referenced_lines = {
        item["line_ref"] for item in evidence["dimension_line_candidates"]
    }
    referenced_lines.update(
        candidate["line_ref"]
        for endpoint in evidence["endpoint_candidates"]
        for candidate in endpoint["line_candidates"]
    )
    referenced_lines.update(
        ref
        for ambiguity in evidence["ambiguities"]
        for ref in ambiguity["refs"]
        if ref.startswith("L")
    )

    unknown_refs = sorted(referenced_lines.difference(lines_by_id))
    if unknown_refs:
        raise ValueError(f"compact evidence references unknown lines: {unknown_refs}")

    def compact_line(line_id: str) -> dict[str, Any]:
        line = lines_by_id[line_id]
        return {
            "orientation": line["orientation"],
            "segment_px": line["segment_px"],
            "style_candidate": {
                "label": line["style"],
                "confidence": line["confidence"],
            },
        }

    unlinked_uncertain = {
        item["id"]
        for item in evidence["lines"]
        if item["id"] not in referenced_lines and item["confidence"] < 0.60
    }

    dimensions = [
        {
            "id": item["id"],
            "line_ref": item["line_ref"],
            "arrow_refs": sorted(item["arrow_refs"]),
            "confidence": item["confidence"],
        }
        for item in sorted(
            evidence["dimension_line_candidates"], key=lambda item: item["id"]
        )
    ]

    arrows: dict[str, dict[str, Any]] = {}
    for arrow_id in sorted(arrows_by_id):
        arrow = arrows_by_id[arrow_id]
        try:
            endpoint = endpoints_by_arrow[arrow_id]
        except KeyError as exc:
            raise ValueError(
                f"compact evidence is missing endpoint data for {arrow_id}"
            ) from exc
        arrows[arrow_id] = {
            "tip_px": arrow["tip_px"],
            "confidence": arrow["confidence"],
            "endpoint_status": endpoint["status"],
            "candidates": [
                {
                    "line_ref": candidate["line_ref"],
                    "distance_px": candidate["distance_px"],
                    "orientation_compatible": candidate[
                        "orientation_compatible"
                    ],
                }
                for candidate in sorted(
                    endpoint["line_candidates"],
                    key=lambda candidate: (
                        candidate["distance_px"],
                        candidate["line_ref"],
                    ),
                )
            ],
        }

    return {
        "image": {
            "width_px": evidence["image"]["width_px"],
            "height_px": evidence["image"]["height_px"],
        },
        "lines": {
            "referenced": {
                line_id: compact_line(line_id)
                for line_id in sorted(referenced_lines)
            },
            "unlinked_uncertain": {
                line_id: compact_line(line_id)
                for line_id in sorted(unlinked_uncertain)
            },
        },
        "dimensions": dimensions,
        "arrows": arrows,
    }


def serialize_evidence(evidence: dict[str, Any]) -> bytes:
    return (json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_evidence(path: str | os.PathLike[str], evidence: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(serialize_evidence(evidence))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, output)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_debug_overlay(
    input_path: str | os.PathLike[str], output_path: str | os.PathLike[str], evidence: dict[str, Any]
) -> None:
    raw = np.fromfile(Path(input_path), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("input is not a decodable raster image")
    colours = {"solid": (0, 160, 0), "dashed": (255, 120, 0), "dash_dot": (180, 0, 180), "unknown": (0, 180, 255)}
    for line in evidence["lines"]:
        x1, y1, x2, y2 = line["segment_px"]
        cv2.line(image, (x1, y1), (x2, y2), colours[line["style"]], 1, cv2.LINE_AA)
    for arrow in evidence["arrowheads"]:
        x, y = arrow["tip_px"]
        cv2.circle(image, (x, y), 4, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.putText(image, arrow["id"], (x + 3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 255), 1, cv2.LINE_AA)
    extension = Path(output_path).suffix or ".png"
    success, encoded = cv2.imencode(extension, image)
    if not success:
        raise ValueError(f"cannot encode debug overlay as {extension}")
    Path(output_path).write_bytes(encoded.tobytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_image")
    parser.add_argument("output_json")
    parser.add_argument("--compact-output")
    parser.add_argument("--debug-overlay")
    args = parser.parse_args(argv)
    try:
        if args.compact_output and Path(args.compact_output).resolve() == Path(
            args.output_json
        ).resolve():
            raise ValueError("full and compact output paths must differ")
        evidence = analyze_image(args.input_image)
        compact = compact_evidence(evidence) if args.compact_output else None
        if args.debug_overlay:
            write_debug_overlay(args.input_image, args.debug_overlay, evidence)
        write_evidence(args.output_json, evidence)
        if args.compact_output:
            assert compact is not None
            write_evidence(args.compact_output, compact)
    except Exception as exc:
        print(f"line-evidence failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
