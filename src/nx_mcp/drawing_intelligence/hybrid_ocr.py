"""Production Hybrid OCR frontend.

This module preserves the accepted Whole + Wide-Local OCR behavior from the
original bake-off while moving executable logic under the production package.
The report schema remains unchanged during migration so the existing Hybrid
Capture Adapter and replay fixtures keep their current contract.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import time
from pathlib import Path
from typing import Any

from .dimension_candidate_reducer import _dedupe_key, classify_candidate_band
from .dimension_witness_anchors import enrich_reduced_dimension_candidates
from .ocr_runtime import (
    assign_items_to_cells,
    build_sheet,
    load_json,
    ocr_items,
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
        .replace("–", "-")
        .replace("—", "-")
        .replace("，", ".")
        .replace(",", ".")
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

    plain_scalar = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)(?:MM)?", normalized)
    if plain_scalar:
        number = plain_scalar.group(1)
        unsigned = number.lstrip("+").lstrip("-")
        if re.fullmatch(r"0\d+", unsigned):
            return set()
        return {_canonical_number(unsigned)}

    labeled_scalar = re.fullmatch(
        r"[A-Z][A-Z0-9]{0,2}[-=:]([-+]?\d+(?:\.\d+)?)(?:MM)?",
        normalized,
    )
    if labeled_scalar:
        number = labeled_scalar.group(1)
        unsigned = number.lstrip("+").lstrip("-")
        if re.fullmatch(r"0\d+", unsigned):
            return set()
        return {_canonical_number(unsigned)}

    return set()


def _linear_text_strength(text: str) -> int:
    normalized = _normalize(text)
    if re.fullmatch(
        r"[A-Z][A-Z0-9]{0,2}[-=:][-+]?\d+(?:\.\d+)?(?:MM)?",
        normalized,
    ):
        return 3
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?MM", normalized):
        return 2
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
        return 1
    if re.fullmatch(r"\d+(?:\.\d+)?±\d+(?:\.\d+)?", normalized):
        return 3
    return 0


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


def _exterior_single_digit_witness_proof(
    candidate: dict[str, Any],
    item: dict[str, Any],
) -> bool:
    """Bind exterior one-glyph text only to one double-witness rail.

    The text must be immediately beyond a drawn rail end, close to its
    perpendicular axis. Both witness strokes must cross the rail and each
    must possess a unique, different physical anchor. The value comes from
    OCR, never from pixel spacing.
    """
    if re.fullmatch(r"[1-9]", _normalize(str(item.get("text") or ""))) is None:
        return False
    points = item.get("bbox")
    orientation = candidate.get("orientation")
    axis = candidate.get("axis_px")
    span = candidate.get("line_span_px")
    witnesses = candidate.get("witness_positions_px")
    records = candidate.get("witness_line_evidence")
    anchors = candidate.get("witness_anchor_evidence")
    if (
        orientation not in {"horizontal", "vertical"}
        or not isinstance(axis, (float, int))
        or isinstance(axis, bool)
        or not isinstance(span, list)
        or len(span) != 2
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in span)
        or not isinstance(witnesses, list)
        or not isinstance(records, list)
        or not isinstance(anchors, list)
        or not isinstance(points, list)
        or len(points) < 4
    ):
        return False
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        axis_low, axis_high = sorted(float(v) for v in span)
        along_low, along_high = (
            (min(xs), max(xs)) if orientation == "horizontal"
            else (min(ys), max(ys))
        )
        cross_low, cross_high = (
            (min(ys), max(ys)) if orientation == "horizontal"
            else (min(xs), max(xs))
        )
    except (TypeError, ValueError, IndexError):
        return False
    if axis_high - axis_low < 20:
        return False
    text_span = along_high - along_low
    cross_span = cross_high - cross_low
    gap = (
        axis_low - along_high if along_high < axis_low
        else along_low - axis_high if along_low > axis_high
        else -1.0
    )
    if gap < 0 or gap > max(12.0, text_span * 0.85):
        return False
    cross_gap = max(cross_low - float(axis), float(axis) - cross_high, 0.0)
    if cross_gap > max(7.0, cross_span * 0.20):
        return False

    within = [
        (index, float(position))
        for index, position in enumerate(witnesses)
        if isinstance(position, (int, float))
        and not isinstance(position, bool)
        and axis_low + 2.0 <= float(position) <= axis_high + 2.0
    ]
    if len(within) != 2 or abs(within[0][1] - within[1][1]) < 6:
        return False

    expected_orientation = "vertical" if orientation == "horizontal" else "horizontal"
    owned_refs: list[str] = []
    for index, position in within:
        line_records = [
            record for record in records
            if isinstance(record, dict) and record.get("witness_index") == index
        ]
        anchor_records = [
            record for record in anchors
            if isinstance(record, dict) and record.get("witness_index") == index
        ]
        if len(line_records) != 1 or len(anchor_records) != 1:
            return False
        crossing = [
            record
            for record in line_records[0].get("source_lines", [])
            if isinstance(record, dict)
            and record.get("crosses_dimension_axis") is True
            and record.get("orientation") == expected_orientation
            and isinstance(record.get("axis_px"), (int, float))
            and abs(float(record["axis_px"]) - position) <= 2.5
        ]
        if not crossing:
            return False
        supported = {
            str(anchor.get("ref"))
            for anchor in anchor_records[0].get("nearest_anchors", [])
            if isinstance(anchor, dict)
            and anchor.get("kind") in {
                "profile_edge_candidate", "circle_center_axis",
                "hidden_projection_center_axis",
            }
            and isinstance(anchor.get("ref"), str)
            and anchor.get("ref")
        }
        if len(supported) != 1:
            return False
        owned_refs.append(next(iter(supported)))
    return owned_refs[0] != owned_refs[1]


def _candidate_matches_item(
    candidate: dict[str, Any],
    item: dict[str, Any],
) -> bool:
    tokens = _linear_tokens(str(item.get("text") or ""))
    if len(tokens) != 1:
        return False
    if _exterior_single_digit_witness_proof(candidate, item):
        return True

    item_orientation = _item_orientation(item)
    candidate_orientation = str(candidate["orientation"])
    # Ambiguous two-or-more digit OCR boxes are eligible for the existing
    # ROI/distance/margin checks, not automatically accepted. Single bare
    # glyphs and definite cross-orientation conflicts remain excluded.
    ambiguity_candidate = (
        item_orientation == "ambiguous"
        and re.fullmatch(r"\d{2,}", _normalize(str(item.get("text") or ""))) is not None
    )
    if (
        _linear_text_strength(str(item.get("text") or "")) < 2
        and item_orientation != candidate_orientation
        and not ambiguity_candidate
    ):
        return False

    return _inside_box(
        _item_center(item),
        list(candidate["wide"]["source_roi_bbox_px"]),
    )


def _assign_global_items(
    candidates: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    assigned: dict[str, list[dict[str, Any]]] = {
        str(candidate["candidate_id"]): [] for candidate in candidates
    }

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
                "exterior_single_digit_witness_proven": (
                    _exterior_single_digit_witness_proof(nearest, item)
                ),
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
            -_linear_text_strength(str(item.get("text") or "")),
            float(item["perpendicular_distance_px"]),
            int(item["source_item_index"]),
        ),
    )
    if len(ranked) > 1:
        first_strength = _linear_text_strength(str(ranked[0].get("text") or ""))
        second_strength = _linear_text_strength(str(ranked[1].get("text") or ""))
        if first_strength == second_strength:
            first = float(ranked[0]["perpendicular_distance_px"])
            second = float(ranked[1]["perpendicular_distance_px"])
            if second - first < _assignment_margin(candidate):
                return None, "multiple_global_tokens_without_distance_margin"

    return str(ranked[0]["token"]), "strongest_unique_global_linear_token"


def _local_linear_tokens(items: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for item in items:
        tokens.update(_linear_tokens(str(item.get("text") or "")))
    return tokens


def _hybrid_decision(
    global_token: str | None,
    local_tokens: set[str],
    *,
    global_text_strength: int = 0,
    local_strong_tokens: set[str] | None = None,
) -> tuple[str | None, str]:
    if global_token is None:
        return None, "no_global_proposal"
    if global_token in local_tokens:
        return global_token, "global_geometry_assignment_confirmed_by_local_roi"

    decimal = re.fullmatch(r"(\d+)\.(\d+)", global_token)
    if decimal is not None:
        integer_part = _canonical_number(decimal.group(1))
        fractional_part = decimal.group(2).lstrip("0")
        decimal_fragments = {integer_part, fractional_part} if fractional_part else set()
        if decimal_fragments and local_tokens == decimal_fragments:
            return global_token, "global_decimal_confirmed_by_local_fragments"
        strong_local = local_strong_tokens or set()
        if (
            decimal_fragments
            and global_text_strength >= 3
            and decimal_fragments.issubset(local_tokens)
            and not strong_local
        ):
            return (
                global_token,
                "structured_global_decimal_confirmed_by_local_fragment_subset",
            )

    return None, "global_local_token_disagreement"


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


def _bare_glyph_dimension_endpoint_owner(
    item: dict[str, Any],
    candidate_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Classify OCR glyphs that geometrically cover a proven dimension arrow tip.

    Bare one-token OCR is intentionally fail-closed unless topology proves that
    the glyph sits on an endpoint of an already accepted dimension line.  This
    prevents arrowheads misread as digits from becoming fake engineering values
    without using pixel geometry as an engineering measurement.
    """

    if _linear_text_strength(str(item.get("text") or "")) != 1:
        return None

    points = item.get("bbox", [])
    if not isinstance(points, list) or len(points) < 4:
        return None
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except (TypeError, ValueError, IndexError):
        return None

    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    item_orientation = _item_orientation(item)

    owners: list[dict[str, Any]] = []
    for candidate in candidate_results:
        if candidate.get("accepted_token") is None:
            continue
        orientation = candidate.get("orientation")
        axis = candidate.get("axis_px")
        span = candidate.get("line_span_px")
        if (
            orientation not in {"horizontal", "vertical"}
            or not isinstance(axis, (int, float))
            or isinstance(axis, bool)
            or not isinstance(span, list)
            or len(span) != 2
            or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in span
            )
        ):
            continue
        if item_orientation == orientation:
            continue

        endpoint_positions = sorted(float(value) for value in span)
        if orientation == "horizontal":
            if not top <= float(axis) <= bottom:
                continue
            covered = [
                endpoint for endpoint in endpoint_positions if left <= endpoint <= right
            ]
        else:
            if not left <= float(axis) <= right:
                continue
            covered = [
                endpoint for endpoint in endpoint_positions if top <= endpoint <= bottom
            ]
        if not covered:
            continue

        owners.append(
            {
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "orientation": str(orientation),
                "axis_px": float(axis),
                "line_endpoint_px": covered[0],
            }
        )

    if len(owners) != 1 or not owners[0]["candidate_id"]:
        return None
    return owners[0]


def _coverage_ledger(
    whole_items: list[dict[str, Any]],
    candidate_results: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted_support: list[dict[str, Any]] = []
    conflicting_linear: list[dict[str, Any]] = []
    unconfirmed_proposals: list[dict[str, Any]] = []
    secondary_assignments: list[dict[str, Any]] = []
    unassigned_linear: list[dict[str, Any]] = []
    non_modeling_dimension_arrow_glyphs: list[dict[str, Any]] = []
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
            arrow_owner = _bare_glyph_dimension_endpoint_owner(
                item,
                candidate_results,
            )
            if arrow_owner is not None:
                non_modeling_dimension_arrow_glyphs.append(
                    {
                        **observation,
                        "token": next(iter(linear)),
                        **arrow_owner,
                        "reason": "covers_accepted_dimension_line_endpoint",
                    }
                )
                categorized_indices.add(source_item_index)
                continue
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
        "non_modeling_dimension_arrow_glyph_observations": (
            non_modeling_dimension_arrow_glyphs
        ),
        "routed_elsewhere_or_unclassified_observations": routed_elsewhere,
        "local_only_linear_observations": local_only_linear,
        "observed_silent_drop_count": len(dropped_indices),
        "observed_silent_drop_indices": dropped_indices,
        "source_extraction_completeness_proven": False,
    }


def _candidate_geometry_key(candidate: dict[str, Any]) -> tuple[Any, ...] | None:
    orientation = candidate.get("orientation")
    axis = candidate.get("axis_px")
    span = candidate.get("line_span_px")
    witnesses = candidate.get("witness_positions_px", [])
    if (
        orientation not in {"horizontal", "vertical"}
        or not isinstance(axis, (int, float))
        or not isinstance(span, list)
        or len(span) != 2
        or not all(isinstance(value, (int, float)) for value in span)
        or not isinstance(witnesses, list)
        or not all(isinstance(value, (int, float)) for value in witnesses)
    ):
        return None
    return (
        str(orientation),
        round(float(axis), 3),
        tuple(round(float(value), 3) for value in span),
        tuple(round(float(value), 3) for value in witnesses),
    )



def _candidate_line_identity(
    candidate: dict[str, Any],
) -> tuple[str, float, float, float] | None:
    orientation = candidate.get("orientation")
    axis = candidate.get("axis_px")
    span = candidate.get("line_span_px")
    if (
        orientation not in {"horizontal", "vertical"}
        or not isinstance(axis, (int, float))
        or isinstance(axis, bool)
        or not isinstance(span, list)
        or len(span) != 2
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in span
        )
    ):
        return None
    low, high = sorted(float(value) for value in span)
    return (
        str(orientation),
        round(float(axis), 3),
        round(low, 3),
        round(high, 3),
    )


def _witness_envelope_covers_majority(
    candidate: dict[str, Any],
) -> bool | None:
    span = candidate.get("line_span_px")
    witnesses = candidate.get("witness_positions_px")
    if not (
        isinstance(span, list)
        and len(span) == 2
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in span
        )
        and isinstance(witnesses, list)
        and len(witnesses) >= 2
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in witnesses
        )
    ):
        return None

    line_low, line_high = sorted(float(value) for value in span)
    witness_low = min(float(value) for value in witnesses)
    witness_high = max(float(value) for value in witnesses)
    line_length = line_high - line_low
    if line_length <= 0:
        return None

    overlap = max(
        0.0,
        min(line_high, witness_high) - max(line_low, witness_low),
    )
    return overlap * 2.0 >= line_length


def _accepted_witness_line_owners(
    results: list[dict[str, Any]],
) -> dict[tuple[str, float, float, float], set[str]]:
    owners: dict[tuple[str, float, float, float], set[str]] = {}
    for result in results:
        if result.get("accepted_token") is None:
            continue
        owner_id = str(result.get("candidate_id") or "")
        if not owner_id:
            continue
        evidence = result.get("witness_line_evidence", [])
        if not isinstance(evidence, list):
            continue
        for record in evidence:
            if not isinstance(record, dict):
                continue
            source_lines = record.get("source_lines", [])
            if not isinstance(source_lines, list):
                continue
            for source_line in source_lines:
                if not isinstance(source_line, dict):
                    continue
                if source_line.get("crosses_dimension_axis") is not True:
                    continue
                key = _candidate_line_identity(
                    {
                        "orientation": source_line.get("orientation"),
                        "axis_px": source_line.get("axis_px"),
                        "line_span_px": source_line.get("span_px"),
                    }
                )
                if key is not None:
                    owners.setdefault(key, set()).add(owner_id)
    return owners


def _apply_dimension_role_conflict_gate(
    results: list[dict[str, Any]],
) -> None:
    """Fail closed when an accepted candidate is structurally an extension line.

    Candidate generation is intentionally high-recall.  A line may therefore be
    proposed both as a dimension line and as an orthogonal witness/extension line.
    Do not accept an engineering dimension solely from nearby OCR text when the
    same exact source line is already witness evidence for another accepted
    dimension and less than half of its own line is bounded by its witnesses.
    """

    witness_owners = _accepted_witness_line_owners(results)
    for result in results:
        if result.get("accepted_token") is None:
            continue
        candidate_id = str(result.get("candidate_id") or "")
        line_key = _candidate_line_identity(result)
        if not candidate_id or line_key is None:
            continue

        other_owners = sorted(
            owner_id
            for owner_id in witness_owners.get(line_key, set())
            if owner_id != candidate_id
        )
        if not other_owners:
            continue

        majority_bounded = _witness_envelope_covers_majority(result)
        if majority_bounded is not False:
            continue

        result["accepted_token"] = None
        result["decision_reason"] = (
            "candidate_line_is_extension_witness_of_accepted_dimension"
        )
        result["dimension_role_conflict"] = {
            "witness_owner_candidate_ids": other_owners,
            "own_witness_envelope_covers_majority": False,
            "pixel_geometry_used_for_role_disambiguation_only": True,
        }


def _overflow_candidates_for_machine_ocr(
    visual_aid: dict[str, Any],
    raw_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    """Restore bounded-out candidates for OCR without expanding Reader/Agent UI.

    The reader visual aid intentionally hides ambiguous >4-candidate buckets.
    Machine OCR must not interpret that human-facing display limit as missing
    source geometry. It takes the exact reduced, deduplicated geometry from
    the saved raw evidence and enriches only the otherwise hidden buckets.
    """
    if raw_evidence.get("schema") != "raw-evidence-v1":
        raise ValueError("OCR overflow recovery requires raw-evidence-v1")
    overflow_keys = {
        (
            bucket.get("region_id"),
            bucket.get("orientation"),
            bucket.get("band"),
        )
        for bucket in visual_aid.get("candidate_buckets", [])
        if isinstance(bucket, dict) and bucket.get("status") == "overflow"
    }
    if not overflow_keys:
        return []

    by_bucket: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    seen: set[tuple[Any, ...]] = set()
    for raw_candidate in raw_evidence.get("dimension_geometry_candidates", []):
        if not isinstance(raw_candidate, dict):
            continue
        region_id = raw_candidate.get("region_id")
        orientation = raw_candidate.get("orientation")
        if not isinstance(region_id, str) or orientation not in {"horizontal", "vertical"}:
            continue
        band = classify_candidate_band(raw_candidate)
        key = (region_id, orientation, band)
        if key not in overflow_keys:
            continue
        identity = _dedupe_key(raw_candidate)
        if identity in seen:
            continue
        seen.add(identity)
        by_bucket.setdefault(key, []).append(
            {
                "candidate_id": raw_candidate.get("candidate_id"),
                "region_id": region_id,
                "orientation": orientation,
                "band": band,
                "axis_px": raw_candidate.get("axis_px"),
                "axis_local_norm": raw_candidate.get("axis_local_norm"),
                "line_span_px": raw_candidate.get("line_span_px"),
                "witness_positions_px": raw_candidate.get("witness_positions_px", []),
                "witness_positions_local_norm": raw_candidate.get(
                    "witness_positions_local_norm", []
                ),
                "witness_line_evidence": raw_candidate.get("witness_line_evidence", []),
            }
        )

    # Fail closed on an inconsistent view: never silently drop candidates.
    visible_overflows = {
        (
            str(bucket.get("region_id")),
            str(bucket.get("orientation")),
            str(bucket.get("band")),
        ): int(bucket.get("candidate_count", -1))
        for bucket in visual_aid.get("candidate_buckets", [])
        if isinstance(bucket, dict) and bucket.get("status") == "overflow"
    }
    for overflow_key, declared_count in visible_overflows.items():
        if len(by_bucket.get(overflow_key, [])) != declared_count:
            raise ValueError(
                f"OCR overflow candidate count mismatch: {overflow_key} "
                f"raw={len(by_bucket.get(overflow_key, []))} visual_aid={declared_count}"
            )

    overflow_candidates = [
        item
        for key in sorted(by_bucket)
        for item in by_bucket[key]
    ]
    enriched = enrich_reduced_dimension_candidates(
        raw_evidence,
        {"dimensions": [{"candidates": overflow_candidates}]},
    )
    return enriched["dimensions"][0]["candidates"]


def _collect_candidates(
    visual_aid: dict[str, Any],
    raw_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for bucket in visual_aid.get("candidate_buckets", []):
        if not isinstance(bucket, dict) or bucket.get("status") != "bounded":
            continue
        for candidate in bucket.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id or candidate_id in by_id:
                continue
            by_id[candidate_id] = candidate

    if raw_evidence is not None:
        for candidate in _overflow_candidates_for_machine_ocr(
            visual_aid, raw_evidence
        ):
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id or candidate_id in by_id:
                raise ValueError(
                    "OCR overflow recovery produced a duplicate/invalid candidate ID"
                )
            by_id[candidate_id] = candidate
    elif any(
        isinstance(bucket, dict) and bucket.get("status") == "overflow"
        for bucket in visual_aid.get("candidate_buckets", [])
    ):
        # Legacy tests may use the bounded-only helper directly. Production
        # explicitly supplies raw evidence whenever there are overflow buckets.
        pass

    candidates: list[dict[str, Any]] = []
    canonical_by_geometry: dict[tuple[Any, ...], dict[str, Any]] = {}
    for candidate_id in sorted(by_id):
        candidate = by_id[candidate_id]
        region_id = str(candidate.get("region_id") or "")
        geometry_key = _candidate_geometry_key(candidate)
        if geometry_key is None:
            candidates.append(
                {
                    **candidate,
                    "source_candidate_ids": [candidate_id],
                    "source_region_ids": ([region_id] if region_id else []),
                    "source_candidate_variants": [candidate],
                }
            )
            continue

        canonical = canonical_by_geometry.get(geometry_key)
        if canonical is None:
            canonical = {
                **candidate,
                "source_candidate_ids": [candidate_id],
                "source_region_ids": ([region_id] if region_id else []),
                "source_candidate_variants": [candidate],
            }
            canonical_by_geometry[geometry_key] = canonical
            candidates.append(canonical)
            continue

        canonical["source_candidate_variants"].append(candidate)
        canonical["source_candidate_ids"].append(candidate_id)
        if region_id and region_id not in canonical["source_region_ids"]:
            canonical["source_region_ids"].append(region_id)

    candidates.sort(key=lambda item: str(item.get("candidate_id") or ""))
    return candidates


def run_hybrid_ocr(
    reader_input: str | Path,
    output: str | Path,
    *,
    artifact_dir: str | Path | None = None,
) -> dict[str, Any]:
    reader_input_path = Path(reader_input).resolve()
    output_path = Path(output).resolve()
    reader_input_payload = load_json(reader_input_path)
    visual_aid_path = Path(str(reader_input_payload["reader_visual_aid_path"])).resolve()
    source_path = Path(str(reader_input_payload["source_raster_path"])).resolve()
    visual_aid = load_json(visual_aid_path)

    cv2 = importlib.import_module("cv2")
    np = importlib.import_module("numpy")
    rapidocr = importlib.import_module("rapidocr")
    image = cv2.imread(str(source_path))
    if image is None:
        raise ValueError(f"unable to read source raster: {source_path}")
    image_height, image_width = image.shape[:2]

    artifact_root = (
        Path(artifact_dir).resolve()
        if artifact_dir is not None
        else output_path.parent / "dg-hybrid-ocr"
    )
    crop_dir = artifact_root / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)

    region_lookup = {
        str(region["region_id"]): list(region["bbox_px"])
        for region in visual_aid.get("regions", [])
        if isinstance(region, dict)
        and region.get("region_id")
        and isinstance(region.get("bbox_px"), list)
    }

    raw_path_value = reader_input_payload.get("raw_evidence_path")
    raw_evidence = (
        load_json(Path(raw_path_value).resolve())
        if isinstance(raw_path_value, str) and raw_path_value
        else None
    )
    if (
        any(
            isinstance(bucket, dict) and bucket.get("status") == "overflow"
            for bucket in visual_aid.get("candidate_buckets", [])
        )
        and raw_evidence is None
    ):
        raise ValueError("Hybrid OCR cannot ignore overflow without raw evidence")
    candidates = _collect_candidates(visual_aid, raw_evidence)
    wide_sheet_path = artifact_root / "dg-hybrid-wide.png"
    wide_sheet, wide_cells = build_sheet(
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
    full_items = ocr_items(full_result)

    wide_started = time.perf_counter()
    wide_result = engine(wide_sheet)
    wide_elapsed = time.perf_counter() - wide_started
    wide_items = ocr_items(wide_result)
    wide_assigned = assign_items_to_cells(
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
        global_text_strength = max(
            (
                _linear_text_strength(str(item.get("text") or ""))
                for item in assignments
                if global_token is not None and str(item.get("token")) == global_token
            ),
            default=0,
        )
        local_strong_tokens = {
            token
            for item in local_items
            if _linear_text_strength(str(item.get("text") or "")) >= 2
            for token in _linear_tokens(str(item.get("text") or ""))
            if token != global_token
        }
        accepted, decision_reason = _hybrid_decision(
            global_token,
            local_tokens,
            global_text_strength=global_text_strength,
            local_strong_tokens=local_strong_tokens,
        )
        # The standard whole/local corroboration remains the default. For
        # text printed outside the local crop, an independently proved pair
        # of distinct witness owners can replace that corroboration.
        if (
            accepted is None
            and global_token is not None
            and not local_tokens
            and len(assignments) == 1
            and assignments[0].get("token") == global_token
            and assignments[0].get("exterior_single_digit_witness_proven") is True
        ):
            accepted = global_token
            decision_reason = "unique_exterior_single_digit_witness_proof"
        results.append(
            {
                "candidate_id": candidate_id,
                "region_id": candidate.get("region_id"),
                "source_candidate_ids": candidate.get(
                    "source_candidate_ids",
                    [candidate_id],
                ),
                "source_region_ids": candidate.get(
                    "source_region_ids",
                    [candidate.get("region_id")],
                ),
                "source_candidate_variants": candidate.get(
                    "source_candidate_variants",
                    [candidate],
                ),
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

    _apply_dimension_role_conflict_gate(results)
    accepted_count = sum(1 for result in results if result["accepted_token"] is not None)
    coverage = _coverage_ledger(full_items, results)
    total_ocr_elapsed = full_elapsed + wide_elapsed
    report = {
        "schema": "dg-hybrid-ocr-bakeoff-v2",
        "source_raster": str(source_path),
        "reader_visual_aid": str(visual_aid_path),
        "raw_candidate_count": sum(
            len(candidate.get("source_candidate_ids", []))
            for candidate in candidates
        ),
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
            "cross_region_exact_geometry_dedup": True,
            "cross_region_region_scoped_evidence_merge": False,
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
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reader_input")
    parser.add_argument("output")
    parser.add_argument("--artifact-dir")
    args = parser.parse_args(argv)

    report = run_hybrid_ocr(
        args.reader_input,
        args.output,
        artifact_dir=args.artifact_dir,
    )
    print(_stdout_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
