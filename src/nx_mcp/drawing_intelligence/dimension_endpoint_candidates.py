from __future__ import annotations

from typing import Any

_PHYSICAL_ANCHOR_KINDS = {
    "profile_edge_candidate",
    "circle_center_axis",
}


def _assignment_axis_coordinate(
    assignment: dict[str, Any],
    orientation: str,
) -> float:
    bbox = assignment.get("bbox")
    if not (
        isinstance(bbox, list)
        and len(bbox) >= 4
        and all(
            isinstance(point, list)
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
            for point in bbox
        )
    ):
        raise ValueError("accepted text assignment requires a numeric bbox")

    coordinate_index = 0 if orientation == "horizontal" else 1
    return sum(float(point[coordinate_index]) for point in bbox) / len(bbox)


def _witness_anchor_lookup(
    candidate: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    evidence = candidate.get("witness_anchor_evidence", [])
    if not isinstance(evidence, list):
        return output

    for item in evidence:
        if not isinstance(item, dict):
            continue
        index = item.get("witness_index")
        if isinstance(index, int):
            output[index] = item
    return output


def derive_dimension_endpoint_candidates(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Derive endpoint candidates without claiming endpoint ownership.

    The accepted OCR label is used only as a spatial bracket selector.  Numeric
    dimension values are never compared with witness spacing, scale, or geometry.
    """

    candidate_id = str(candidate.get("candidate_id") or "")
    accepted_token = candidate.get("accepted_token")
    orientation = str(candidate.get("orientation") or "")

    if not candidate_id:
        raise ValueError("candidate_id is required")
    if not isinstance(accepted_token, str) or not accepted_token:
        raise ValueError("accepted_token is required")
    if orientation not in {"horizontal", "vertical"}:
        raise ValueError("orientation must be horizontal or vertical")

    assignments = candidate.get("global_assignments", [])
    if not isinstance(assignments, list):
        raise ValueError("global_assignments must be a list")

    accepted_assignments = [
        item
        for item in assignments
        if isinstance(item, dict) and str(item.get("token") or "") == accepted_token
    ]
    if len(accepted_assignments) != 1:
        return {
            "candidate_id": candidate_id,
            "status": "unresolved",
            "reason": "accepted_token_does_not_have_one_unique_global_assignment",
            "accepted_assignment_count": len(accepted_assignments),
        }

    text_coordinate = _assignment_axis_coordinate(
        accepted_assignments[0],
        orientation,
    )

    witnesses = candidate.get("witness_positions_px", [])
    if not isinstance(witnesses, list):
        raise ValueError("witness_positions_px must be a list")

    indexed_witnesses = sorted(
        [
            (index, float(value))
            for index, value in enumerate(witnesses)
            if isinstance(value, (int, float))
        ],
        key=lambda item: (item[1], item[0]),
    )
    if len(indexed_witnesses) < 2:
        return {
            "candidate_id": candidate_id,
            "status": "unresolved",
            "reason": "fewer_than_two_numeric_witnesses",
            "text_axis_coordinate_px": round(text_coordinate, 3),
        }

    brackets: list[tuple[tuple[int, float], tuple[int, float]]] = []
    for first, second in zip(
        indexed_witnesses,
        indexed_witnesses[1:],
        strict=False,
    ):
        low = first[1]
        high = second[1]
        if low < text_coordinate < high:
            brackets.append((first, second))

    if len(brackets) != 1:
        return {
            "candidate_id": candidate_id,
            "status": "unresolved",
            "reason": "accepted_text_does_not_select_one_unique_adjacent_witness_pair",
            "text_axis_coordinate_px": round(text_coordinate, 3),
            "bracket_count": len(brackets),
        }

    first, second = brackets[0]
    anchor_lookup = _witness_anchor_lookup(candidate)

    endpoints: list[dict[str, Any]] = []
    for endpoint_index, (witness_index, position_px) in enumerate((first, second)):
        witness_evidence = anchor_lookup.get(witness_index, {})
        nearest = witness_evidence.get("nearest_anchors", [])
        if not isinstance(nearest, list):
            nearest = []

        physical_candidates = [
            item
            for item in nearest
            if isinstance(item, dict) and item.get("kind") in _PHYSICAL_ANCHOR_KINDS
        ]

        endpoint_status = (
            "unique_physical_candidate"
            if len(physical_candidates) == 1
            else "no_physical_candidate"
            if not physical_candidates
            else "ambiguous_physical_candidates"
        )

        endpoints.append(
            {
                "endpoint_index": endpoint_index,
                "witness_index": witness_index,
                "position_px": position_px,
                "status": endpoint_status,
                "physical_candidates": physical_candidates,
                "ignored_nonownership_anchors": [
                    item
                    for item in nearest
                    if isinstance(item, dict) and item.get("kind") not in _PHYSICAL_ANCHOR_KINDS
                ],
            }
        )

    return {
        "candidate_id": candidate_id,
        "status": "bracketed",
        "selection_basis": "accepted_ocr_text_center_between_adjacent_witnesses",
        "numeric_value_used_for_geometry": False,
        "text_axis_coordinate_px": round(text_coordinate, 3),
        "selected_witness_indices": [first[0], second[0]],
        "selected_witness_positions_px": [first[1], second[1]],
        "all_endpoint_candidates_unique": all(
            item["status"] == "unique_physical_candidate" for item in endpoints
        ),
        "endpoints": endpoints,
    }
