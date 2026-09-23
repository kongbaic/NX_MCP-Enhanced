from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .raster_evidence import _load_cv_modules, extract_raw_evidence
from .reader_visual_aid import build_reader_visual_aid


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, path)


def _clip_box(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    image_width: int,
    image_height: int,
) -> list[int]:
    left = max(0, min(image_width - 1, int(x1)))
    top = max(0, min(image_height - 1, int(y1)))
    right = max(left + 1, min(image_width, int(x2)))
    bottom = max(top + 1, min(image_height, int(y2)))
    return [left, top, right - left, bottom - top]


def _region_crop_box(
    bbox: list[int],
    image_width: int,
    image_height: int,
) -> list[int]:
    x, y, width, height = (int(value) for value in bbox)
    padding = max(24, int(round(max(width, height) * 0.12)))
    return _clip_box(
        x - padding,
        y - padding,
        x + width + padding,
        y + height + padding,
        image_width,
        image_height,
    )


def _bucket_crop_box(
    bbox: list[int],
    orientation: str,
    band: str,
    image_width: int,
    image_height: int,
) -> list[int]:
    x, y, width, height = (int(value) for value in bbox)
    padding = max(24, int(round(max(width, height) * 0.12)))

    if orientation == "horizontal":
        left = x - padding
        right = x + width + padding
        if band == "top":
            top = y - padding
            bottom = y + int(round(height * 0.40))
        elif band == "middle":
            top = y + int(round(height * 0.22))
            bottom = y + int(round(height * 0.78))
        elif band == "bottom":
            top = y + int(round(height * 0.60))
            bottom = y + height + padding
        else:
            raise ValueError(f"unsupported horizontal band: {band}")
    elif orientation == "vertical":
        top = y - padding
        bottom = y + height + padding
        if band == "left":
            left = x - padding
            right = x + int(round(width * 0.45))
        elif band == "middle":
            left = x + int(round(width * 0.22))
            right = x + int(round(width * 0.78))
        elif band == "right":
            left = x + int(round(width * 0.55))
            right = x + width + padding
        else:
            raise ValueError(f"unsupported vertical band: {band}")
    else:
        raise ValueError(f"unsupported orientation: {orientation}")

    return _clip_box(
        left,
        top,
        right,
        bottom,
        image_width,
        image_height,
    )


def _write_crop(
    image: Any,
    path: Path,
    bbox: list[int],
    cv2: Any,
) -> None:
    x, y, width, height = bbox
    crop = image[y : y + height, x : x + width]
    if crop.size == 0:
        raise ValueError(f"empty crop for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), crop):
        raise ValueError(f"failed to write crop: {path}")


def _region_candidate_geometry(
    visual_aid: dict[str, Any],
    region_id: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for bucket in visual_aid.get("candidate_buckets", []):
        if not isinstance(bucket, dict):
            continue
        if bucket.get("region_id") != region_id or bucket.get("status") != "bounded":
            continue
        for candidate in bucket.get("candidates", []):
            if isinstance(candidate, dict):
                candidates.append(candidate)
    candidates.sort(key=lambda item: str(item.get("candidate_id") or ""))
    return candidates


def _clamp_local(value: float, limit: int) -> int:
    return max(0, min(limit - 1, int(round(value))))


def _write_candidate_overlay(
    image: Any,
    path: Path,
    crop_bbox: list[int],
    candidates: list[dict[str, Any]],
    cv2: Any,
) -> None:
    crop_x, crop_y, crop_width, crop_height = crop_bbox
    canvas = image[
        crop_y : crop_y + crop_height,
        crop_x : crop_x + crop_width,
    ].copy()
    if canvas.size == 0:
        raise ValueError(f"empty candidate overlay source for {path.name}")

    for index, candidate in enumerate(candidates):
        candidate_id = candidate.get("candidate_id")
        orientation = candidate.get("orientation")
        axis = candidate.get("axis_px")
        span = candidate.get("line_span_px")
        witnesses = candidate.get("witness_positions_px", [])
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or orientation not in {"horizontal", "vertical"}
            or not isinstance(axis, (int, float))
            or not isinstance(span, list)
            or len(span) != 2
            or not all(isinstance(value, (int, float)) for value in span)
        ):
            continue

        if orientation == "horizontal":
            y = _clamp_local(float(axis) - crop_y, crop_height)
            x1 = _clamp_local(float(span[0]) - crop_x, crop_width)
            x2 = _clamp_local(float(span[1]) - crop_x, crop_width)
            point_a = (x1, y)
            point_b = (x2, y)
            midpoint = ((x1 + x2) // 2, y)
            witness_points = [
                (_clamp_local(float(value) - crop_x, crop_width), y)
                for value in witnesses
                if isinstance(value, (int, float))
            ]
            label_origin = (
                midpoint[0],
                _clamp_local(midpoint[1] - 10 - 14 * (index % 3), crop_height),
            )
        else:
            x = _clamp_local(float(axis) - crop_x, crop_width)
            y1 = _clamp_local(float(span[0]) - crop_y, crop_height)
            y2 = _clamp_local(float(span[1]) - crop_y, crop_height)
            point_a = (x, y1)
            point_b = (x, y2)
            midpoint = (x, (y1 + y2) // 2)
            witness_points = [
                (x, _clamp_local(float(value) - crop_y, crop_height))
                for value in witnesses
                if isinstance(value, (int, float))
            ]
            label_origin = (
                _clamp_local(midpoint[0] + 8 + 18 * (index % 3), crop_width),
                midpoint[1],
            )

        cv2.line(canvas, point_a, point_b, (0, 0, 220), 2, cv2.LINE_AA)
        for point in witness_points:
            cv2.circle(canvas, point, 3, (0, 0, 220), -1, cv2.LINE_AA)

        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.45
        thickness = 1
        (text_width, text_height), baseline = cv2.getTextSize(
            candidate_id,
            font,
            scale,
            thickness,
        )
        text_x = _clamp_local(label_origin[0], crop_width)
        text_y = _clamp_local(label_origin[1], crop_height)
        box_left = max(0, text_x - 3)
        box_top = max(0, text_y - text_height - 4)
        box_right = min(crop_width - 1, text_x + text_width + 3)
        box_bottom = min(crop_height - 1, text_y + baseline + 3)
        cv2.rectangle(
            canvas,
            (box_left, box_top),
            (box_right, box_bottom),
            (255, 255, 255),
            -1,
        )
        cv2.rectangle(
            canvas,
            (box_left, box_top),
            (box_right, box_bottom),
            (0, 0, 220),
            1,
        )
        cv2.putText(
            canvas,
            candidate_id,
            (text_x, text_y),
            font,
            scale,
            (0, 0, 0),
            thickness,
            cv2.LINE_AA,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), canvas):
        raise ValueError(f"failed to write candidate overlay: {path}")


def _fit_image_into_cell(
    image: Any,
    cell_width: int,
    cell_height: int,
    cv2: Any,
    np: Any,
) -> Any:
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("contact sheet source image is empty")

    scale = min(cell_width / width, cell_height / height)
    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(
        image,
        (resized_width, resized_height),
        interpolation=interpolation,
    )

    canvas = np.full((cell_height, cell_width, 3), 255, dtype=np.uint8)
    x = (cell_width - resized_width) // 2
    y = (cell_height - resized_height) // 2
    canvas[y : y + resized_height, x : x + resized_width] = resized
    return canvas


def _write_contact_sheet(
    items: list[tuple[str, Path]],
    output_path: Path,
    cv2: Any,
    np: Any,
) -> None:
    if not items:
        raise ValueError("contact sheet requires at least one image")

    columns = 3
    cell_width = 700
    image_height = 420
    title_height = 44
    cell_height = title_height + image_height
    rows = (len(items) + columns - 1) // columns

    sheet = np.full(
        (rows * cell_height, columns * cell_width, 3),
        255,
        dtype=np.uint8,
    )

    for index, (label, image_path) in enumerate(items):
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"unable to read contact sheet image: {image_path}")

        tile = _fit_image_into_cell(
            image,
            cell_width,
            image_height,
            cv2,
            np,
        )
        row = index // columns
        column = index % columns
        x1 = column * cell_width
        y1 = row * cell_height

        cv2.rectangle(
            sheet,
            (x1, y1),
            (x1 + cell_width - 1, y1 + cell_height - 1),
            (210, 210, 210),
            1,
        )
        cv2.putText(
            sheet,
            label,
            (x1 + 14, y1 + 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )
        sheet[
            y1 + title_height : y1 + title_height + image_height,
            x1 : x1 + cell_width,
        ] = tile

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), sheet):
        raise ValueError(f"failed to write contact sheet: {output_path}")


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    anchor_hints: list[dict[str, Any]] = []
    for witness in candidate.get("witness_anchor_evidence", []):
        if not isinstance(witness, dict):
            continue
        nearby = []
        for anchor in witness.get("nearest_anchors", []):
            if not isinstance(anchor, dict):
                continue
            kind = anchor.get("kind")
            ref = anchor.get("ref")
            if isinstance(kind, str) and isinstance(ref, str):
                nearby.append({"kind": kind, "ref": ref})
        anchor_hints.append(
            {
                "witness_index": witness.get("witness_index"),
                "nearby_anchors": nearby,
            }
        )

    return {
        "candidate_id": candidate.get("candidate_id"),
        "orientation": candidate.get("orientation"),
        "anchor_hints": anchor_hints,
    }


def prepare_reader_input(
    image_path: str | Path,
    workspace_root: str | Path,
) -> dict[str, Any]:
    """Prepare all deterministic geometry-only inputs for one Reader pass."""

    started = time.perf_counter()
    image_path = Path(image_path).resolve()
    workspace_root = Path(workspace_root).resolve()

    if not image_path.is_file():
        raise ValueError(f"current raster path does not exist: {image_path}")
    workspace_root.mkdir(parents=True, exist_ok=True)

    cv2, np = _load_cv_modules()
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"unable to read raster image: {image_path}")
    image_height, image_width = image.shape[:2]

    raw_started = time.perf_counter()
    raw = extract_raw_evidence(image_path)
    raw_elapsed_ms = round((time.perf_counter() - raw_started) * 1000, 3)

    aid_started = time.perf_counter()
    aid = build_reader_visual_aid(raw)
    aid_elapsed_ms = round((time.perf_counter() - aid_started) * 1000, 3)

    raw_path = workspace_root / "raw-evidence.json"
    aid_path = workspace_root / "reader-visual-aid.json"
    input_path = workspace_root / "reader-input.json"
    crops_dir = workspace_root / "reader-crops"

    _atomic_write_json(raw_path, raw)
    _atomic_write_json(aid_path, aid)

    crops_started = time.perf_counter()
    if crops_dir.exists():
        shutil.rmtree(crops_dir)
    crops_dir.mkdir(parents=True, exist_ok=True)

    overview_path = crops_dir / "overview.png"
    if not cv2.imwrite(str(overview_path), image):
        raise ValueError(f"failed to write overview: {overview_path}")

    region_lookup = {
        str(region["region_id"]): region
        for region in aid.get("regions", [])
        if isinstance(region, dict) and region.get("region_id")
    }

    region_entries: list[dict[str, Any]] = []
    for region_id, region in sorted(region_lookup.items()):
        bbox = _region_crop_box(
            list(region["bbox_px"]),
            image_width,
            image_height,
        )
        crop_path = crops_dir / f"{region_id}.png"
        overlay_path = crops_dir / f"{region_id}-candidates.png"
        _write_crop(image, crop_path, bbox, cv2)
        overlay_candidates = _region_candidate_geometry(aid, region_id)
        _write_candidate_overlay(
            image,
            overlay_path,
            bbox,
            overlay_candidates,
            cv2,
        )
        region_entries.append(
            {
                "region_id": region_id,
                "crop_path": str(crop_path),
                "candidate_overlay_path": str(overlay_path),
                "candidate_overlay_count": len(overlay_candidates),
                "crop_bbox_px": bbox,
                "source_bbox_px": region.get("bbox_px"),
                "circle_group_count": len(region.get("circle_groups", [])),
                "linear_pattern_candidate_count": len(region.get("linear_pattern_candidates", [])),
            }
        )

    bucket_entries: list[dict[str, Any]] = []
    for bucket in aid.get("candidate_buckets", []):
        if not isinstance(bucket, dict):
            continue
        bucket_id = str(bucket.get("bucket_id") or "")
        region_id = str(bucket.get("region_id") or "")
        orientation = str(bucket.get("orientation") or "")
        band = str(bucket.get("band") or "")
        bucket_region = region_lookup.get(region_id)
        if not bucket_id or bucket_region is None:
            continue

        crop_bbox = _bucket_crop_box(
            list(bucket_region["bbox_px"]),
            orientation,
            band,
            image_width,
            image_height,
        )
        crop_path = crops_dir / f"{bucket_id}.png"
        _write_crop(image, crop_path, crop_bbox, cv2)

        entry: dict[str, Any] = {
            "bucket_id": bucket_id,
            "region_id": region_id,
            "orientation": orientation,
            "band": band,
            "status": bucket.get("status"),
            "candidate_count": bucket.get("candidate_count", 0),
            "crop_path": str(crop_path),
            "crop_bbox_px": crop_bbox,
            "candidates": [],
        }
        if bucket.get("status") == "bounded":
            entry["candidates"] = [
                _compact_candidate(candidate)
                for candidate in bucket.get("candidates", [])
                if isinstance(candidate, dict)
            ]
        else:
            entry["reason"] = bucket.get("reason")
        bucket_entries.append(entry)

    contact_items: list[tuple[str, Path]] = [("overview", overview_path)]
    contact_items.extend(
        (str(item["region_id"]), Path(str(item["crop_path"]))) for item in region_entries
    )
    contact_items.extend(
        (str(item["bucket_id"]), Path(str(item["crop_path"]))) for item in bucket_entries
    )
    contact_sheet_path = workspace_root / "reader-contact-sheet.png"
    _write_contact_sheet(
        contact_items,
        contact_sheet_path,
        cv2,
        np,
    )

    crops_elapsed_ms = round((time.perf_counter() - crops_started) * 1000, 3)
    total_elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    manifest = {
        "schema": "reader-input-v1",
        "source_raster_path": str(image_path),
        "source_drawing_authoritative": True,
        "semantics_policy": "geometry_only_no_engineering_claims",
        "raw_evidence_path": str(raw_path),
        "reader_visual_aid_path": str(aid_path),
        "overview_crop_path": str(overview_path),
        "contact_sheet_path": str(contact_sheet_path),
        "regions": region_entries,
        "candidate_buckets": bucket_entries,
        "summary": {
            "region_count": len(region_entries),
            "bucket_count": len(bucket_entries),
            "overflow_bucket_count": sum(
                1 for item in bucket_entries if item["status"] == "overflow"
            ),
            "max_bucket_candidate_count": max(
                (int(item.get("candidate_count", 0)) for item in bucket_entries),
                default=0,
            ),
            "crop_count": 1 + 2 * len(region_entries) + len(bucket_entries),
            "candidate_overlay_count": len(region_entries),
        },
        "timing_ms": {
            "raw_evidence": raw_elapsed_ms,
            "visual_aid": aid_elapsed_ms,
            "crops": crops_elapsed_ms,
            "total": total_elapsed_ms,
        },
        "reader_contract": {
            "read_source_drawing": True,
            "may_read_reader_input": True,
            "may_read_contact_sheet": True,
            "may_read_listed_crops": True,
            "prefer_contact_sheet": True,
            "agent_output_schema": "reader-observations-v1",
            "agent_writes_reader_capture_directly": False,
            "assembler_decides_engineering_semantics": False,
            "read_raw_evidence_directly": False,
            "scan_workspace": False,
            "scan_history": False,
            "create_additional_crops": False,
            "numeric_pixel_scale_matching": False,
            "visual_aid_decides_feature_identity": False,
            "visual_aid_decides_endpoint_ownership": False,
            "overflow_requires_source_drawing": True,
        },
    }
    _atomic_write_json(input_path, manifest)

    return {
        "written": True,
        "schema": "reader-input-v1",
        "reader_input": str(input_path),
        "raw_evidence": str(raw_path),
        "reader_visual_aid": str(aid_path),
        "crops_directory": str(crops_dir),
        "contact_sheet": str(contact_sheet_path),
        "summary": manifest["summary"],
        "timing_ms": manifest["timing_ms"],
    }
