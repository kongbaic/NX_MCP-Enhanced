from __future__ import annotations

import argparse
import importlib
import json
import re
import time
from pathlib import Path
from typing import Any

from dg_local_ocr_bakeoff import (
    _assign_items_to_cells,
    _build_sheet,
    _load_json,
    _ocr_items,
)

ASSIGNMENT_MARGIN_MIN_PX = 6.0


def _stdout_json(payload: dict[str, Any]) -> str:
    """Render JSON safely for Windows legacy stdout encodings."""

    return json.dumps(payload, ensure_ascii=True, indent=2)


def _normalize(text: str) -> str:
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


def _linear_tokens(text: str) -> set[str]:
    normalized = _normalize(text)

    tolerance = re.fullmatch(
        r"(\d+(?:\.\d+)?)±(\d+(?:\.\d+)?)",
        normalized,
    )
    if tolerance:
        return {
            (f"{_canonical_number(tolerance.group(1))}±{_canonical_number(tolerance.group(2))}")
        }

    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
        return set()

    unsigned = normalized.lstrip("+").lstrip("-")
    if re.fullmatch(r"0\d+", unsigned):
        return set()
    return {_canonical_number(unsigned)}


def _item_center(item: dict[str, Any]) -> tuple[float, float]:
    points = item.get("bbox", [])
    if not isinstance(points, list) or len(points) < 4:
        raise ValueError("OCR item requires a four-point bbox")
    return (
        sum(float(point[0]) for point in points) / len(points),
        sum(float(point[1]) for point in points) / len(points),
    )


def _item_orientation(item: dict[str, Any]) -> str:
    points = item.get("bbox", [])
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width > height * 1.25:
        return "horizontal"
    if height > width * 1.25:
        return "vertical"
    return "ambiguous"


def _inside_box(
    point: tuple[float, float],
    box: list[int],
) -> bool:
    x, y = point
    left, top, width, height = box
    return float(left) <= x <= float(left + width) and float(top) <= y <= float(top + height)


def _perpendicular_distance(
    item: dict[str, Any],
    candidate: dict[str, Any],
) -> float:
    center_x, center_y = _item_center(item)
    axis = float(candidate["axis_px"])
    if candidate["orientation"] == "horizontal":
        return abs(center_y - axis)
    return abs(center_x - axis)


def _assignment_margin(candidate: dict[str, Any]) -> float:
    box = candidate["wide"]["source_roi_bbox_px"]
    cross_size = float(box[3]) if candidate["orientation"] == "horizontal" else float(box[2])
    return max(ASSIGNMENT_MARGIN_MIN_PX, cross_size * 0.08)


def _candidate_matches_item(
    candidate: dict[str, Any],
    item: dict[str, Any],
) -> bool:
    tokens = _linear_tokens(str(item.get("text") or ""))
    if len(tokens) != 1:
        return False

    item_orientation = _item_orientation(item)
    candidate_orientation = str(candidate["orientation"])
    if item_orientation != "ambiguous" and item_orientation != candidate_orientation:
        return False

    return _inside_box(
        _item_center(item),
        list(candidate["wide"]["source_roi_bbox_px"]),
    )


def _assign_global_items(
    candidates: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    assigned = {str(candidate["candidate_id"]): [] for candidate in candidates}

    for item_index, item in enumerate(items):
        tokens = _linear_tokens(str(item.get("text") or ""))
        if len(tokens) != 1:
            continue
        token = next(iter(tokens))

        matches: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            if not _candidate_matches_item(candidate, item):
                continue
            matches.append(
                (
                    _perpendicular_distance(item, candidate),
                    candidate,
                )
            )

        matches.sort(
            key=lambda value: (
                value[0],
                str(value[1]["candidate_id"]),
            )
        )
        if not matches:
            continue

        nearest_distance, nearest = matches[0]
        if len(matches) > 1:
            second_distance = matches[1][0]
            if second_distance - nearest_distance < _assignment_margin(nearest):
                continue

        candidate_id = str(nearest["candidate_id"])
        assigned[candidate_id].append(
            {
                "source_item_index": item_index,
                "text": str(item.get("text") or ""),
                "token": token,
                "perpendicular_distance_px": round(
                    nearest_distance,
                    3,
                ),
                "bbox": item.get("bbox"),
                "confidence": item.get("confidence"),
            }
        )

    return assigned


def _global_proposal(
    candidate: dict[str, Any],
    assignments: list[dict[str, Any]],
) -> tuple[str | None, str]:
    if not assignments:
        return None, "no_unique_global_text_assignment"

    ranked = sorted(
        assignments,
        key=lambda item: (
            float(item["perpendicular_distance_px"]),
            int(item["source_item_index"]),
        ),
    )
    if len(ranked) > 1:
        first = float(ranked[0]["perpendicular_distance_px"])
        second = float(ranked[1]["perpendicular_distance_px"])
        if second - first < _assignment_margin(candidate):
            return None, "multiple_global_tokens_without_distance_margin"

    return str(ranked[0]["token"]), "nearest_unique_global_linear_token"


def _local_linear_tokens(items: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for item in items:
        tokens.update(_linear_tokens(str(item.get("text") or "")))
    return tokens


def _hybrid_decision(
    global_token: str | None,
    local_tokens: set[str],
) -> tuple[str | None, str]:
    if global_token is None:
        return None, "no_global_proposal"
    if global_token not in local_tokens:
        return None, "global_local_token_disagreement"
    return global_token, "global_geometry_assignment_confirmed_by_local_roi"


def _observation_ref(
    source_item_index: int,
    item: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_item_index": source_item_index,
        "text": str(item.get("text") or ""),
        "bbox": item.get("bbox"),
        "confidence": item.get("confidence"),
        "primary_tokens": item.get("primary_tokens", []),
    }


def _coverage_ledger(
    whole_items: list[dict[str, Any]],
    candidate_results: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted_support: list[dict[str, Any]] = []
    conflicting_linear: list[dict[str, Any]] = []
    unconfirmed_proposals: list[dict[str, Any]] = []
    secondary_assignments: list[dict[str, Any]] = []
    unassigned_linear: list[dict[str, Any]] = []
    routed_elsewhere: list[dict[str, Any]] = []
    local_only_linear: list[dict[str, Any]] = []

    assignments_by_index: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    for candidate in candidate_results:
        for assignment in candidate.get("global_assignments", []):
            source_item_index = int(assignment["source_item_index"])
            if source_item_index in assignments_by_index:
                raise ValueError("whole OCR observation assigned to more than one DG candidate")
            assignments_by_index[source_item_index] = (candidate, assignment)

        global_tokens = {
            str(assignment["token"]) for assignment in candidate.get("global_assignments", [])
        }
        for token in candidate.get("wide_local_linear_tokens", []):
            token = str(token)
            if token in global_tokens:
                continue
            local_only_linear.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "token": token,
                    "reason": "local_linear_token_without_matching_global_assignment",
                }
            )

    categorized_indices: set[int] = set()
    whole_linear_count = 0

    for source_item_index, item in enumerate(whole_items):
        linear = _linear_tokens(str(item.get("text") or ""))
        observation = _observation_ref(source_item_index, item)

        if len(linear) != 1:
            routed_elsewhere.append(
                {
                    **observation,
                    "reason": "not_one_standalone_linear_token",
                }
            )
            categorized_indices.add(source_item_index)
            continue

        whole_linear_count += 1
        assigned = assignments_by_index.get(source_item_index)
        if assigned is None:
            unassigned_linear.append(
                {
                    **observation,
                    "token": next(iter(linear)),
                    "reason": "no_unique_DG_assignment",
                }
            )
            categorized_indices.add(source_item_index)
            continue

        candidate, assignment = assigned
        candidate_id = str(candidate["candidate_id"])
        assignment_token = str(assignment["token"])
        proposal_token = candidate.get("global_proposal_token")
        accepted_token = candidate.get("accepted_token")
        decision_reason = str(candidate.get("decision_reason") or "")

        base = {
            **observation,
            "candidate_id": candidate_id,
            "token": assignment_token,
        }
        if accepted_token is not None and assignment_token == str(accepted_token):
            accepted_support.append(
                {
                    **base,
                    "reason": "supports_accepted_DG_value",
                }
            )
        elif proposal_token is not None and assignment_token == str(proposal_token):
            if decision_reason == "global_local_token_disagreement":
                conflicting_linear.append(
                    {
                        **base,
                        "local_tokens": candidate.get(
                            "wide_local_linear_tokens",
                            [],
                        ),
                        "reason": decision_reason,
                    }
                )
            else:
                unconfirmed_proposals.append(
                    {
                        **base,
                        "reason": decision_reason,
                    }
                )
        else:
            secondary_assignments.append(
                {
                    **base,
                    "selected_proposal_token": proposal_token,
                    "reason": "assigned_to_DG_but_not_selected_as_global_proposal",
                }
            )
        categorized_indices.add(source_item_index)

    all_indices = set(range(len(whole_items)))
    dropped_indices = sorted(all_indices - categorized_indices)

    return {
        "whole_observation_count": len(whole_items),
        "whole_linear_observation_count": whole_linear_count,
        "accepted_support_observations": accepted_support,
        "conflicting_linear_observations": conflicting_linear,
        "unconfirmed_proposal_observations": unconfirmed_proposals,
        "secondary_assignment_observations": secondary_assignments,
        "unassigned_linear_observations": unassigned_linear,
        "routed_elsewhere_or_unclassified_observations": routed_elsewhere,
        "local_only_linear_observations": local_only_linear,
        "observed_silent_drop_count": len(dropped_indices),
        "observed_silent_drop_indices": dropped_indices,
        "source_extraction_completeness_proven": False,
    }


def _collect_candidates(
    visual_aid: dict[str, Any],
) -> list[dict[str, Any]]:
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
    return candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reader_input")
    parser.add_argument("output")
    parser.add_argument("--artifact-dir")
    args = parser.parse_args(argv)

    reader_input_path = Path(args.reader_input).resolve()
    output_path = Path(args.output).resolve()
    reader_input = _load_json(reader_input_path)
    visual_aid_path = Path(str(reader_input["reader_visual_aid_path"])).resolve()
    source_path = Path(str(reader_input["source_raster_path"])).resolve()
    visual_aid = _load_json(visual_aid_path)

    cv2 = importlib.import_module("cv2")
    np = importlib.import_module("numpy")
    rapidocr = importlib.import_module("rapidocr")
    image = cv2.imread(str(source_path))
    if image is None:
        raise ValueError(f"unable to read source raster: {source_path}")
    image_height, image_width = image.shape[:2]

    artifact_dir = (
        Path(args.artifact_dir).resolve()
        if args.artifact_dir
        else output_path.parent / "dg-hybrid-ocr"
    )
    crop_dir = artifact_dir / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)

    region_lookup = {
        str(region["region_id"]): list(region["bbox_px"])
        for region in visual_aid.get("regions", [])
        if isinstance(region, dict)
        and region.get("region_id")
        and isinstance(region.get("bbox_px"), list)
    }

    candidates = _collect_candidates(visual_aid)
    wide_sheet_path = artifact_dir / "dg-hybrid-wide.png"
    wide_sheet, wide_cells = _build_sheet(
        image,
        candidates,
        region_lookup,
        image_width,
        image_height,
        scale="wide",
        output_path=wide_sheet_path,
        crop_dir=crop_dir,
        cv2=cv2,
        np=np,
    )

    init_started = time.perf_counter()
    engine = rapidocr.RapidOCR(
        params={
            "Global.use_cls": True,
            "Global.return_word_box": False,
        }
    )
    init_elapsed = time.perf_counter() - init_started

    full_started = time.perf_counter()
    full_result = engine(image)
    full_elapsed = time.perf_counter() - full_started
    full_items = _ocr_items(full_result)

    wide_started = time.perf_counter()
    wide_result = engine(wide_sheet)
    wide_elapsed = time.perf_counter() - wide_started
    wide_items = _ocr_items(wide_result)
    wide_assigned = _assign_items_to_cells(
        wide_items,
        wide_cells,
    )

    candidate_shells = []
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        candidate_shells.append(
            {
                **candidate,
                "wide": wide_cells[candidate_id],
            }
        )

    global_assignments = _assign_global_items(
        candidate_shells,
        full_items,
    )

    results: list[dict[str, Any]] = []
    for candidate in candidate_shells:
        candidate_id = str(candidate["candidate_id"])
        assignments = global_assignments[candidate_id]
        global_token, proposal_reason = _global_proposal(
            candidate,
            assignments,
        )
        local_items = wide_assigned[candidate_id]
        local_tokens = _local_linear_tokens(local_items)
        accepted, decision_reason = _hybrid_decision(
            global_token,
            local_tokens,
        )
        results.append(
            {
                "candidate_id": candidate_id,
                "region_id": candidate.get("region_id"),
                "orientation": candidate.get("orientation"),
                "axis_px": candidate.get("axis_px"),
                "line_span_px": candidate.get("line_span_px"),
                "witness_positions_px": candidate.get(
                    "witness_positions_px",
                    [],
                ),
                "witness_anchor_evidence": candidate.get(
                    "witness_anchor_evidence",
                    [],
                ),
                "witness_line_evidence": candidate.get(
                    "witness_line_evidence",
                    [],
                ),
                "global_assignments": assignments,
                "global_proposal_token": global_token,
                "global_proposal_reason": proposal_reason,
                "wide_local_items": local_items,
                "wide_local_linear_tokens": sorted(local_tokens),
                "accepted_token": accepted,
                "decision_reason": decision_reason,
            }
        )

    accepted_count = sum(1 for result in results if result["accepted_token"] is not None)
    coverage = _coverage_ledger(full_items, results)
    total_ocr_elapsed = full_elapsed + wide_elapsed
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "source_raster": str(source_path),
        "reader_visual_aid": str(visual_aid_path),
        "candidate_count": len(results),
        "accepted_count": accepted_count,
        "unresolved_count": len(results) - accepted_count,
        "engine_init_elapsed_s": round(init_elapsed, 6),
        "ocr_elapsed_s": {
            "whole_drawing": round(full_elapsed, 6),
            "wide_local_sheet": round(wide_elapsed, 6),
            "total": round(total_ocr_elapsed, 6),
        },
        "policy": {
            "ocr_calls_per_drawing": 2,
            "whole_drawing_text_inventory": True,
            "global_text_observation_one_to_one": True,
            "nearest_candidate_margin_required": True,
            "wide_local_confirmation_required": True,
            "linear_dg_excludes_diameter_radius_thread": True,
            "confidence_is_correctness_gate": False,
            "leading_zero_integer_is_ambiguous": True,
            "observed_evidence_silent_drop_forbidden": True,
        },
        "whole_drawing_items": full_items,
        "regions": visual_aid.get("regions", []),
        "annotation_line_candidates": visual_aid.get(
            "annotation_line_candidates",
            [],
        ),
        "structural_profile_inventory": visual_aid.get(
            "structural_profile_inventory",
            [],
        ),
        "coverage": coverage,
        "candidates": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(_stdout_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
