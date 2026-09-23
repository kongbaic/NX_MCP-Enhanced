from __future__ import annotations

import argparse
import importlib
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any


def _clip_box(
    left: float,
    top: float,
    right: float,
    bottom: float,
    width: int,
    height: int,
) -> list[int]:
    x1 = max(0, min(width - 1, int(math.floor(left))))
    y1 = max(0, min(height - 1, int(math.floor(top))))
    x2 = max(x1 + 1, min(width, int(math.ceil(right))))
    y2 = max(y1 + 1, min(height, int(math.ceil(bottom))))
    return [x1, y1, x2 - x1, y2 - y1]


def _candidate_roi_box(
    candidate: dict[str, Any],
    region_bbox: list[int],
    image_width: int,
    image_height: int,
    *,
    scale: str,
) -> list[int]:
    orientation = candidate.get("orientation")
    axis = candidate.get("axis_px")
    span = candidate.get("line_span_px")
    witnesses = [
        float(value)
        for value in candidate.get("witness_positions_px", [])
        if isinstance(value, (int, float))
    ]
    if (
        orientation not in {"horizontal", "vertical"}
        or not isinstance(axis, (int, float))
        or not isinstance(span, list)
        or len(span) != 2
        or not all(isinstance(value, (int, float)) for value in span)
    ):
        raise ValueError("candidate is missing deterministic ROI geometry")

    region_x, region_y, region_width, region_height = map(int, region_bbox)
    along_values = witnesses if len(witnesses) >= 2 else [float(span[0]), float(span[1])]
    along_start = min(along_values)
    along_end = max(along_values)
    along_length = max(1.0, along_end - along_start)

    if scale == "tight":
        along_pad = max(10.0, along_length * 0.05)
        cross_ratio = 0.055
        minimum_cross = 24.0
    elif scale == "wide":
        along_pad = max(16.0, along_length * 0.09)
        cross_ratio = 0.09
        minimum_cross = 36.0
    else:
        raise ValueError(f"unsupported ROI scale: {scale}")

    if orientation == "horizontal":
        cross_pad = max(minimum_cross, region_height * cross_ratio)
        return _clip_box(
            along_start - along_pad,
            float(axis) - cross_pad,
            along_end + along_pad,
            float(axis) + cross_pad,
            image_width,
            image_height,
        )

    cross_pad = max(minimum_cross, region_width * cross_ratio)
    return _clip_box(
        float(axis) - cross_pad,
        along_start - along_pad,
        float(axis) + cross_pad,
        along_end + along_pad,
        image_width,
        image_height,
    )


def _normalize_token(text: str) -> str:
    return (
        text.strip()
        .upper()
        .replace("Φ", "Ø")
        .replace("φ", "Ø")
        .replace("∅", "Ø")
        .replace("＋", "+")
        .replace("－", "-")
        .replace(" ", "")
    )


def _canonical_number(text: str) -> str:
    value = float(text)
    if value.is_integer():
        return str(int(value))
    return format(value, ".12g")


def _primary_tokens(text: str) -> set[str]:
    import re

    normalized = _normalize_token(text)
    tokens: set[str] = set()

    tolerance = re.search(r"(\d+(?:\.\d+)?)±(\d+(?:\.\d+)?)", normalized)
    if tolerance:
        tokens.add(
            f"{_canonical_number(tolerance.group(1))}±"
            f"{_canonical_number(tolerance.group(2))}"
        )
        return tokens

    for prefix in ("Ø", "R", "M"):
        match = re.search(rf"{prefix}(\d+(?:\.\d+)?)", normalized)
        if match:
            tokens.add(f"{prefix}{_canonical_number(match.group(1))}")
            return tokens

    angle = re.search(r"(\d+(?:\.\d+)?)°", normalized)
    if angle:
        tokens.add(f"{_canonical_number(angle.group(1))}°")
        return tokens

    fit = re.search(r"(\d+(?:\.\d+)?)H(\d+)", normalized)
    if fit:
        tokens.add(f"{_canonical_number(fit.group(1))}H{fit.group(2)}")
        return tokens

    numbers = re.findall(r"(?<![A-Z])[-+]?\d+(?:\.\d+)?", normalized)
    if len(numbers) == 1:
        tokens.add(_canonical_number(numbers[0].lstrip("+").lstrip("-")))
    return tokens


def _ocr_items(result: Any) -> list[dict[str, Any]]:
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or txts is None or scores is None:
        return []

    items: list[dict[str, Any]] = []
    for box, text, score in zip(boxes, txts, scores, strict=True):
        items.append(
            {
                "text": str(text),
                "confidence": float(score),
                "bbox": [
                    [float(point[0]), float(point[1])]
                    for point in box
                ],
                "primary_tokens": sorted(_primary_tokens(str(text))),
            }
        )
    return items


def _variant_tokens(items: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for item in items:
        tokens.update(str(token) for token in item.get("primary_tokens", []))
    return tokens


def _decision(variant_tokens: dict[str, set[str]]) -> tuple[str | None, str]:
    support = Counter(
        token
        for tokens in variant_tokens.values()
        for token in tokens
    )
    eligible = sorted(token for token, count in support.items() if count >= 2)
    if len(eligible) == 1:
        return eligible[0], "consensus_across_independent_roi_variants"
    if not eligible:
        return None, "no_token_repeated_across_independent_roi_variants"
    return None, "multiple_tokens_have_independent_variant_support"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reader_input")
    parser.add_argument("output")
    parser.add_argument("--roi-dir")
    args = parser.parse_args(argv)

    reader_input_path = Path(args.reader_input).resolve()
    output_path = Path(args.output).resolve()
    reader_input = _load_json(reader_input_path)

    visual_aid_path = Path(str(reader_input["reader_visual_aid_path"])).resolve()
    source_path = Path(str(reader_input["source_raster_path"])).resolve()
    visual_aid = _load_json(visual_aid_path)

    cv2 = importlib.import_module("cv2")
    rapidocr = importlib.import_module("rapidocr")
    image = cv2.imread(str(source_path))
    if image is None:
        raise ValueError(f"unable to read source raster: {source_path}")
    image_height, image_width = image.shape[:2]

    roi_dir = (
        Path(args.roi_dir).resolve()
        if args.roi_dir
        else output_path.parent / "dg-local-rois"
    )
    roi_dir.mkdir(parents=True, exist_ok=True)

    region_lookup = {
        str(region["region_id"]): list(region["bbox_px"])
        for region in visual_aid.get("regions", [])
        if isinstance(region, dict)
        and region.get("region_id")
        and isinstance(region.get("bbox_px"), list)
    }

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in visual_aid.get("candidate_buckets", []):
        if not isinstance(bucket, dict) or bucket.get("status") != "bounded":
            continue
        for candidate in bucket.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id or candidate_id in seen:
                continue
            seen.add(candidate_id)
            candidates.append(candidate)
    candidates.sort(key=lambda item: str(item.get("candidate_id") or ""))

    init_started = time.perf_counter()
    engine = rapidocr.RapidOCR(
        params={
            "Global.use_cls": True,
            "Global.return_word_box": False,
        }
    )
    init_elapsed = time.perf_counter() - init_started

    benchmark_started = time.perf_counter()
    results: list[dict[str, Any]] = []

    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        region_id = str(candidate["region_id"])
        orientation = str(candidate["orientation"])
        region_bbox = region_lookup.get(region_id)
        if region_bbox is None:
            raise ValueError(f"missing region bbox for {region_id}")

        variants: dict[str, dict[str, Any]] = {}
        token_sets: dict[str, set[str]] = {}

        for scale in ("tight", "wide"):
            roi_bbox = _candidate_roi_box(
                candidate,
                region_bbox,
                image_width,
                image_height,
                scale=scale,
            )
            x, y, width, height = roi_bbox
            raw_roi = image[y : y + height, x : x + width].copy()

            if orientation == "horizontal":
                variant_images = {"native": raw_roi}
            else:
                variant_images = {
                    "cw": cv2.rotate(raw_roi, cv2.ROTATE_90_CLOCKWISE),
                    "ccw": cv2.rotate(raw_roi, cv2.ROTATE_90_COUNTERCLOCKWISE),
                }

            for rotation, variant_image in variant_images.items():
                variant_id = f"{scale}-{rotation}"
                variant_path = roi_dir / f"{candidate_id}-{variant_id}.png"
                if not cv2.imwrite(str(variant_path), variant_image):
                    raise ValueError(f"failed to write ROI: {variant_path}")

                started = time.perf_counter()
                result = engine(variant_image)
                elapsed = time.perf_counter() - started
                items = _ocr_items(result)
                tokens = _variant_tokens(items)
                token_sets[variant_id] = tokens
                variants[variant_id] = {
                    "roi_bbox_source_px": roi_bbox,
                    "image_path": str(variant_path),
                    "elapsed_s": round(elapsed, 6),
                    "items": items,
                    "primary_tokens": sorted(tokens),
                }

        accepted, reason = _decision(token_sets)
        results.append(
            {
                "candidate_id": candidate_id,
                "region_id": region_id,
                "orientation": orientation,
                "axis_px": candidate.get("axis_px"),
                "line_span_px": candidate.get("line_span_px"),
                "witness_positions_px": candidate.get("witness_positions_px", []),
                "variants": variants,
                "accepted_token": accepted,
                "decision_reason": reason,
            }
        )

    benchmark_elapsed = time.perf_counter() - benchmark_started
    accepted_count = sum(1 for item in results if item["accepted_token"] is not None)

    report = {
        "schema": "dg-local-ocr-bakeoff-v1",
        "source_raster": str(source_path),
        "reader_visual_aid": str(visual_aid_path),
        "candidate_count": len(results),
        "accepted_count": accepted_count,
        "unresolved_count": len(results) - accepted_count,
        "engine_init_elapsed_s": round(init_elapsed, 6),
        "benchmark_elapsed_s": round(benchmark_elapsed, 6),
        "policy": {
            "wrong_value_preferred_over_unresolved": False,
            "minimum_independent_variant_support": 2,
            "confidence_is_correctness_gate": False,
            "infer_diameter_from_plain_zero": False,
        },
        "candidates": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
