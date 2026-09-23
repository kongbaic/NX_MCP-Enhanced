from __future__ import annotations

import argparse
import importlib
import json
import math
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OcrItem:
    text: str
    bbox: list[list[float]]
    confidence: float
    orientation_deg: float | None


def _bbox_orientation_deg(box: list[list[float]]) -> float | None:
    if len(box) < 2:
        return None
    x1, y1 = box[0]
    x2, y2 = box[1]
    angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
    while angle < 0:
        angle += 180
    while angle >= 180:
        angle -= 180
    return round(angle, 3)


def _build_rapidocr_runner() -> tuple[Callable[[Path], tuple[list[OcrItem], float]], float]:
    started = time.perf_counter()
    module = importlib.import_module("rapidocr")
    engine = module.RapidOCR(
        params={
            "Global.use_cls": True,
            "Global.return_word_box": False,
        }
    )
    init_elapsed = time.perf_counter() - started

    def run(image_path: Path) -> tuple[list[OcrItem], float]:
        inference_started = time.perf_counter()
        result = engine(str(image_path))
        elapsed = time.perf_counter() - inference_started

        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or txts is None or scores is None:
            return [], elapsed

        items: list[OcrItem] = []
        for box, text, score in zip(boxes, txts, scores, strict=True):
            points = [[float(point[0]), float(point[1])] for point in box]
            items.append(
                OcrItem(
                    text=str(text),
                    bbox=points,
                    confidence=float(score),
                    orientation_deg=_bbox_orientation_deg(points),
                )
            )
        return items, elapsed

    return run, init_elapsed


def _tesseract(image_path: Path) -> tuple[list[OcrItem], float]:
    started = time.perf_counter()
    run = subprocess.run(
        [
            "tesseract",
            str(image_path),
            "stdout",
            "--psm",
            "11",
            "tsv",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or "tesseract failed")

    items: list[OcrItem] = []
    rows = run.stdout.splitlines()
    if not rows:
        return items, elapsed
    header = rows[0].split("\t")
    index = {name: position for position, name in enumerate(header)}
    required = {"left", "top", "width", "height", "conf", "text"}
    if not required.issubset(index):
        raise RuntimeError("unexpected tesseract TSV schema")

    for row in rows[1:]:
        fields = row.split("\t")
        if len(fields) != len(header):
            continue
        text_value = fields[index["text"]].strip()
        if not text_value:
            continue
        confidence = float(fields[index["conf"]])
        if confidence < 0:
            continue
        left = float(fields[index["left"]])
        top = float(fields[index["top"]])
        width = float(fields[index["width"]])
        height = float(fields[index["height"]])
        box = [
            [left, top],
            [left + width, top],
            [left + width, top + height],
            [left, top + height],
        ]
        items.append(
            OcrItem(
                text=text_value,
                bbox=box,
                confidence=confidence / 100.0,
                orientation_deg=0.0,
            )
        )
    return items, elapsed


def _normalize_token(text: str) -> str:
    return (
        text.strip()
        .replace("Φ", "Ø")
        .replace("φ", "Ø")
        .replace("∅", "Ø")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("± ", "±")
        .replace(" ", "")
    )


def _score(
    expected: list[str],
    items: list[OcrItem],
    *,
    complete_token_inventory: bool,
) -> dict[str, Any]:
    expected_normalized = [_normalize_token(item) for item in expected]
    observed_normalized = [_normalize_token(item.text) for item in items]

    remaining = list(observed_normalized)
    matched: list[str] = []
    missed: list[str] = []
    for token in expected_normalized:
        if token in remaining:
            matched.append(token)
            remaining.remove(token)
        else:
            missed.append(token)

    recall = len(matched) / len(expected_normalized) if expected_normalized else 1.0
    precision: float | None = None
    extra_text: list[str] | None = None
    if complete_token_inventory:
        precision = len(matched) / (len(matched) + len(remaining)) if items else 1.0
        extra_text = remaining

    return {
        "expected_count": len(expected_normalized),
        "detected_count": len(items),
        "matched_count": len(matched),
        "exact_token_recall": round(recall, 6),
        "exact_token_precision": round(precision, 6) if precision is not None else None,
        "complete_token_inventory": complete_token_inventory,
        "matched": matched,
        "missed": missed,
        "extra_text": extra_text,
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "text-extraction-bakeoff-v1":
        raise ValueError("manifest must use text-extraction-bakeoff-v1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest requires at least one case")
    return payload


def _build_engine(
    engine_name: str,
) -> tuple[Callable[[Path], tuple[list[OcrItem], float]], float]:
    if engine_name == "rapidocr":
        return _build_rapidocr_runner()
    if engine_name == "tesseract":
        return _tesseract, 0.0
    raise ValueError(f"unsupported engine: {engine_name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("output")
    parser.add_argument(
        "--engine",
        action="append",
        choices=["rapidocr", "tesseract"],
        required=True,
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest).resolve()
    output_path = Path(args.output).resolve()
    manifest = _load_manifest(manifest_path)
    root = manifest_path.parent

    report: dict[str, Any] = {
        "schema": "text-extraction-bakeoff-report-v1",
        "manifest": str(manifest_path),
        "engines": {},
    }

    for engine_name in args.engine:
        engine, init_elapsed = _build_engine(engine_name)
        engine_cases: list[dict[str, Any]] = []
        for case in manifest["cases"]:
            case_id = str(case["case_id"])
            image_path = (root / str(case["image"])).resolve()
            expected = [str(value) for value in case.get("expected_tokens", [])]
            complete_inventory = bool(case.get("complete_token_inventory", False))
            if not image_path.is_file():
                raise ValueError(f"case {case_id!r} image does not exist: {image_path}")

            items, elapsed = engine(image_path)
            score = _score(
                expected,
                items,
                complete_token_inventory=complete_inventory,
            )
            engine_cases.append(
                {
                    "case_id": case_id,
                    "image": str(image_path),
                    "elapsed_s": round(elapsed, 6),
                    "score": score,
                    "items": [
                        {
                            "text": item.text,
                            "bbox": item.bbox,
                            "confidence": item.confidence,
                            "orientation_deg": item.orientation_deg,
                        }
                        for item in items
                    ],
                }
            )

        elapsed_values = [item["elapsed_s"] for item in engine_cases]
        recall_values = [item["score"]["exact_token_recall"] for item in engine_cases]
        precision_values = [
            item["score"]["exact_token_precision"]
            for item in engine_cases
            if item["score"]["exact_token_precision"] is not None
        ]
        report["engines"][engine_name] = {
            "cases": engine_cases,
            "summary": {
                "case_count": len(engine_cases),
                "engine_init_elapsed_s": round(init_elapsed, 6),
                "mean_elapsed_s": round(sum(elapsed_values) / len(elapsed_values), 6),
                "max_elapsed_s": round(max(elapsed_values), 6),
                "mean_exact_token_recall": round(
                    sum(recall_values) / len(recall_values),
                    6,
                ),
                "mean_exact_token_precision": (
                    round(sum(precision_values) / len(precision_values), 6)
                    if precision_values
                    else None
                ),
            },
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
