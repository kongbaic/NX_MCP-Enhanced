from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

CELL_WIDTH = 360
CELL_HEIGHT = 160
SHEET_COLUMNS = 4
CELL_MARGIN = 10


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

    _, _, region_width, region_height = map(int, region_bbox)
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


def _plain_number_token(raw: str) -> str | None:
    unsigned = raw.lstrip("+").lstrip("-")
    if re.fullmatch(r"0\d+", unsigned):
        return None
    return _canonical_number(unsigned)


def _primary_tokens(text: str) -> set[str]:
    normalized = _normalize_token(text)
    tokens: set[str] = set()

    tolerance = re.search(r"(\d+(?:\.\d+)?)±(\d+(?:\.\d+)?)", normalized)
    if tolerance:
        tokens.add(
            f"{_canonical_number(tolerance.group(1))}±{_canonical_number(tolerance.group(2))}"
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
        token = _plain_number_token(numbers[0])
        if token is not None:
            tokens.add(token)
    return tokens


def ocr_items(result: Any) -> list[dict[str, Any]]:
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or txts is None or scores is None:
        return []

    items: list[dict[str, Any]] = []
    for box, text, score in zip(boxes, txts, scores, strict=True):
        points = [[float(point[0]), float(point[1])] for point in box]
        items.append(
            {
                "text": str(text),
                "confidence": float(score),
                "bbox": points,
                "primary_tokens": sorted(_primary_tokens(str(text))),
            }
        )
    return items


def _fit_into_cell(image: Any, cv2: Any, np: Any) -> Any:
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("ROI image is empty")
    usable_width = CELL_WIDTH - 2 * CELL_MARGIN
    usable_height = CELL_HEIGHT - 2 * CELL_MARGIN
    scale = min(usable_width / width, usable_height / height)
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(
        image,
        (target_width, target_height),
        interpolation=interpolation,
    )
    cell = np.full((CELL_HEIGHT, CELL_WIDTH, 3), 255, dtype=np.uint8)
    x = (CELL_WIDTH - target_width) // 2
    y = (CELL_HEIGHT - target_height) // 2
    cell[y : y + target_height, x : x + target_width] = resized
    return cell


def build_sheet(
    image: Any,
    candidates: list[dict[str, Any]],
    region_lookup: dict[str, list[int]],
    image_width: int,
    image_height: int,
    *,
    scale: str,
    output_path: Path,
    crop_dir: Path,
    cv2: Any,
    np: Any,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    rows = max(1, math.ceil(len(candidates) / SHEET_COLUMNS))
    sheet = np.full(
        (rows * CELL_HEIGHT, SHEET_COLUMNS * CELL_WIDTH, 3),
        255,
        dtype=np.uint8,
    )
    cells: dict[str, dict[str, Any]] = {}

    for index, candidate in enumerate(candidates):
        candidate_id = str(candidate["candidate_id"])
        region_id = str(candidate["region_id"])
        orientation = str(candidate["orientation"])
        region_bbox = region_lookup.get(region_id)
        if region_bbox is None:
            raise ValueError(f"missing region bbox for {region_id}")

        roi_bbox = _candidate_roi_box(
            candidate,
            region_bbox,
            image_width,
            image_height,
            scale=scale,
        )
        x, y, width, height = roi_bbox
        roi = image[y : y + height, x : x + width].copy()
        if orientation == "vertical":
            roi = cv2.rotate(roi, cv2.ROTATE_90_CLOCKWISE)

        crop_path = crop_dir / f"{candidate_id}-{scale}.png"
        if not cv2.imwrite(str(crop_path), roi):
            raise ValueError(f"failed to write ROI: {crop_path}")

        cell = _fit_into_cell(roi, cv2, np)
        row = index // SHEET_COLUMNS
        column = index % SHEET_COLUMNS
        cell_x = column * CELL_WIDTH
        cell_y = row * CELL_HEIGHT
        sheet[
            cell_y : cell_y + CELL_HEIGHT,
            cell_x : cell_x + CELL_WIDTH,
        ] = cell
        cells[candidate_id] = {
            "source_roi_bbox_px": roi_bbox,
            "crop_path": str(crop_path),
            "sheet_cell_bbox_px": [
                cell_x,
                cell_y,
                CELL_WIDTH,
                CELL_HEIGHT,
            ],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), sheet):
        raise ValueError(f"failed to write sheet: {output_path}")
    return sheet, cells


def _item_center(item: dict[str, Any]) -> tuple[float, float]:
    points = item["bbox"]
    return (
        sum(float(point[0]) for point in points) / len(points),
        sum(float(point[1]) for point in points) / len(points),
    )


def assign_items_to_cells(
    items: list[dict[str, Any]],
    cells: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    assigned: dict[str, list[dict[str, Any]]] = {candidate_id: [] for candidate_id in cells}
    for item in items:
        center_x, center_y = _item_center(item)
        owners = []
        for candidate_id, cell in cells.items():
            x, y, width, height = cell["sheet_cell_bbox_px"]
            if x <= center_x < x + width and y <= center_y < y + height:
                owners.append(candidate_id)
        if len(owners) == 1:
            assigned[owners[0]].append(item)
    return assigned


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload
