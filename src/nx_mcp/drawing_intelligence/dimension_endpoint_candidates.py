from __future__ import annotations

import math
from typing import Any

_PHYSICAL_ANCHOR_KINDS = {
    "profile_edge_candidate",
    "profile_vertex_candidate",
    "circle_center_axis",
    "hidden_projection_center_axis",
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


def _witness_line_lookup(
    candidate: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    evidence = candidate.get("witness_line_evidence", [])
    if not isinstance(evidence, list):
        return output

    for item in evidence:
        if not isinstance(item, dict):
            continue
        index = item.get("witness_index")
        if isinstance(index, int):
            output[index] = item
    return output


def _same_source_profile_line(
    profile: dict[str, Any],
    source_line: dict[str, Any],
) -> bool:
    if source_line.get("crosses_dimension_axis") is not True:
        return False
    if str(profile.get("source_orientation") or "") != str(
        source_line.get("orientation") or ""
    ):
        return False

    position = profile.get("position_px")
    axis = source_line.get("axis_px")
    profile_span = profile.get("span_px")
    source_span = source_line.get("span_px")
    if (
        not isinstance(position, (int, float))
        or isinstance(position, bool)
        or not isinstance(axis, (int, float))
        or isinstance(axis, bool)
        or not isinstance(profile_span, list)
        or len(profile_span) != 2
        or not isinstance(source_span, list)
        or len(source_span) != 2
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in [*profile_span, *source_span]
        )
    ):
        return False

    return (
        math.isclose(float(position), float(axis), abs_tol=1e-9)
        and math.isclose(float(profile_span[0]), float(source_span[0]), abs_tol=1e-9)
        and math.isclose(float(profile_span[1]), float(source_span[1]), abs_tol=1e-9)
    )


def _collinear_profile_continuation(
    profile: dict[str, Any],
    source_line: dict[str, Any],
) -> bool:
    """Prove that a structural profile edge continues the dimension witness line.

    Raster geometry is used only for physical identity.  The profile must have
    an independent geometry source, be collinear with the crossing witness
    within its declared axis tolerance, and cover most of the witness segment.
    """

    if (
        profile.get("kind") != "profile_edge_candidate"
        or source_line.get("crosses_dimension_axis") is not True
        or str(profile.get("source_orientation") or "")
        != str(source_line.get("orientation") or "")
    ):
        return False

    independent_geometry_source_count = profile.get(
        "independent_geometry_source_count"
    )
    position = profile.get("position_px")
    profile_span = profile.get("span_px")
    source_axis = source_line.get("axis_px")
    source_span = source_line.get("span_px")
    axis_tolerance = profile.get("axis_tolerance_px")
    if (
        not isinstance(independent_geometry_source_count, int)
        or isinstance(independent_geometry_source_count, bool)
        or independent_geometry_source_count < 1
        or not isinstance(position, (int, float))
        or isinstance(position, bool)
        or not isinstance(source_axis, (int, float))
        or isinstance(source_axis, bool)
        or not isinstance(axis_tolerance, (int, float))
        or isinstance(axis_tolerance, bool)
        or not isinstance(profile_span, list)
        or len(profile_span) != 2
        or not isinstance(source_span, list)
        or len(source_span) != 2
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in [*profile_span, *source_span]
        )
    ):
        return False

    if abs(float(position) - float(source_axis)) > float(axis_tolerance):
        return False

    profile_low, profile_high = sorted(float(value) for value in profile_span)
    source_low, source_high = sorted(float(value) for value in source_span)
    source_length = source_high - source_low
    if source_length <= 1e-9:
        return False
    overlap = max(
        0.0,
        min(profile_high, source_high) - max(profile_low, source_low),
    )
    return overlap / source_length >= 0.80


def _profile_source_identity(
    profile: dict[str, Any],
) -> tuple[str, float, float, float] | None:
    """Return raster-source identity for one physical profile line.

    Region IDs are crop provenance, not physical line identity.  Two profile
    anchors from overlapping crops may therefore refer to the same source line.
    This key is used only to collapse exact duplicate ownership candidates; it
    never converts pixel geometry into engineering coordinates.
    """

    if profile.get("kind") != "profile_edge_candidate":
        return None
    orientation = str(profile.get("source_orientation") or "")
    position = profile.get("position_px")
    span = profile.get("span_px")
    if (
        orientation not in {"horizontal", "vertical"}
        or not isinstance(position, (int, float))
        or isinstance(position, bool)
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
        orientation,
        round(float(position), 9),
        round(low, 9),
        round(high, 9),
    )


def _profile_connects_to_witness_terminal(
    profile: dict[str, Any],
    *,
    witness_lines: list[Any],
    dimension_axis_px: float | None,
) -> bool | None:
    """Check whether a profile edge is physically connected to the witness terminal."""

    if profile.get("kind") != "profile_edge_candidate":
        return None

    orientation = str(profile.get("source_orientation") or "")
    position = profile.get("position_px")
    profile_span = profile.get("span_px")
    axis_tolerance = profile.get("axis_tolerance_px")
    junction_tolerance = profile.get("junction_tolerance_px")
    if (
        orientation not in {"horizontal", "vertical"}
        or not isinstance(position, (int, float))
        or isinstance(position, bool)
        or not isinstance(profile_span, list)
        or len(profile_span) != 2
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in profile_span
        )
        or not isinstance(axis_tolerance, (int, float))
        or isinstance(axis_tolerance, bool)
        or not isinstance(junction_tolerance, (int, float))
        or isinstance(junction_tolerance, bool)
        or not isinstance(dimension_axis_px, (int, float))
        or isinstance(dimension_axis_px, bool)
    ):
        return None

    profile_low, profile_high = sorted(float(value) for value in profile_span)
    for source_line in witness_lines:
        if not isinstance(source_line, dict):
            continue
        if source_line.get("crosses_dimension_axis") is not True:
            continue
        if str(source_line.get("orientation") or "") != orientation:
            continue

        source_axis = source_line.get("axis_px")
        source_span = source_line.get("span_px")
        if (
            not isinstance(source_axis, (int, float))
            or isinstance(source_axis, bool)
            or not isinstance(source_span, list)
            or len(source_span) != 2
            or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in source_span
            )
        ):
            continue
        if abs(float(source_axis) - float(position)) > float(axis_tolerance):
            continue

        source_low, source_high = sorted(float(value) for value in source_span)
        terminal = max(
            (source_low, source_high),
            key=lambda value: abs(value - float(dimension_axis_px)),
        )
        if profile_low <= terminal <= profile_high:
            return True
        if min(
            abs(terminal - profile_low),
            abs(terminal - profile_high),
        ) <= float(junction_tolerance):
            return True

    return False



def _profile_vertex_connects_to_witness_terminal(
    vertex: dict[str, Any],
    *,
    witness_lines: list[Any],
    dimension_axis_px: float | None,
) -> bool:
    """Require a structural vertex to coincide with the extension-line terminal."""

    if vertex.get("kind") != "profile_vertex_candidate":
        return False

    position = vertex.get("position_px")
    transverse = vertex.get("vertex_transverse_px")
    supporting_orientation = str(
        vertex.get("supporting_profile_orientation") or ""
    )
    axis_tolerance = vertex.get("axis_tolerance_px")
    junction_tolerance = vertex.get("junction_tolerance_px")
    match_tolerance = vertex.get("vertex_match_tolerance_px")
    if (
        supporting_orientation not in {"horizontal", "vertical"}
        or not isinstance(position, (int, float))
        or isinstance(position, bool)
        or not isinstance(transverse, (int, float))
        or isinstance(transverse, bool)
        or not isinstance(axis_tolerance, (int, float))
        or isinstance(axis_tolerance, bool)
        or not isinstance(junction_tolerance, (int, float))
        or isinstance(junction_tolerance, bool)
        or not isinstance(match_tolerance, (int, float))
        or isinstance(match_tolerance, bool)
        or not isinstance(dimension_axis_px, (int, float))
        or isinstance(dimension_axis_px, bool)
    ):
        return False

    witness_orientation = (
        "vertical" if supporting_orientation == "horizontal" else "horizontal"
    )
    for source_line in witness_lines:
        if not isinstance(source_line, dict):
            continue
        if source_line.get("crosses_dimension_axis") is not True:
            continue
        if str(source_line.get("orientation") or "") != witness_orientation:
            continue

        source_axis = source_line.get("axis_px")
        source_span = source_line.get("span_px")
        if (
            not isinstance(source_axis, (int, float))
            or isinstance(source_axis, bool)
            or not isinstance(source_span, list)
            or len(source_span) != 2
            or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in source_span
            )
        ):
            continue
        if abs(float(source_axis) - float(position)) > float(match_tolerance):
            continue

        source_low, source_high = sorted(float(value) for value in source_span)
        terminal = max(
            (source_low, source_high),
            key=lambda value: abs(value - float(dimension_axis_px)),
        )
        if abs(terminal - float(transverse)) <= float(junction_tolerance):
            return True

    return False

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

    selection_basis = "accepted_ocr_text_center_between_adjacent_witnesses"
    if len(brackets) != 1:
        exterior_pair = None
        assignment = accepted_assignments[0]
        if assignment.get("exterior_single_digit_witness_proven") is True:
            # Re-evaluate the production OCR proof here rather than trusting
            # a flag in an unverified handoff. It demands exactly two
            # crossing witness strokes, unique different physical owners,
            # and the OCR glyph immediately outside the rail end.
            from .hybrid_ocr import _exterior_single_digit_witness_proof

            if _exterior_single_digit_witness_proof(candidate, assignment):
                span = candidate.get("line_span_px")
                if (
                    isinstance(span, list)
                    and len(span) == 2
                    and all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        for value in span
                    )
                ):
                    low, high = sorted(float(value) for value in span)
                    inside = [
                        witness
                        for witness in indexed_witnesses
                        if low + 2.0 <= witness[1] <= high + 2.0
                    ]
                    if len(inside) == 2:
                        first_index = indexed_witnesses.index(inside[0])
                        second_index = indexed_witnesses.index(inside[1])
                        if second_index == first_index + 1:
                            exterior_pair = (inside[0], inside[1])
        if exterior_pair is None:
            return {
                "candidate_id": candidate_id,
                "status": "unresolved",
                "reason": "accepted_text_does_not_select_one_unique_adjacent_witness_pair",
                "text_axis_coordinate_px": round(text_coordinate, 3),
                "bracket_count": len(brackets),
            }
        brackets = [exterior_pair]
        selection_basis = "proven_exterior_label_unique_crossing_witness_pair"

    first, second = brackets[0]
    anchor_lookup = _witness_anchor_lookup(candidate)
    line_lookup = _witness_line_lookup(candidate)

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

        witness_lines = line_lookup.get(witness_index, {}).get("source_lines", [])
        if not isinstance(witness_lines, list):
            witness_lines = []
        dimension_axis_px = candidate.get("axis_px")
        disconnected_profiles: list[dict[str, Any]] = []
        disconnected_vertices: list[dict[str, Any]] = []
        connected_candidates: list[dict[str, Any]] = []
        typed_dimension_axis_px = (
            float(dimension_axis_px)
            if isinstance(dimension_axis_px, (int, float))
            and not isinstance(dimension_axis_px, bool)
            else None
        )
        for item in physical_candidates:
            if item.get("kind") == "profile_vertex_candidate":
                if not _profile_vertex_connects_to_witness_terminal(
                    item,
                    witness_lines=witness_lines,
                    dimension_axis_px=typed_dimension_axis_px,
                ):
                    disconnected_vertices.append(item)
                    continue
                connected_candidates.append(item)
                continue
            if item.get("kind") != "profile_edge_candidate":
                connected_candidates.append(item)
                continue
            connectivity = _profile_connects_to_witness_terminal(
                item,
                witness_lines=witness_lines,
                dimension_axis_px=typed_dimension_axis_px,
            )
            if connectivity is False:
                disconnected_profiles.append(item)
                continue
            connected_candidates.append(item)
        physical_candidates = connected_candidates

        narrowing_basis = None
        if isinstance(witness_lines, list):
            exact_profile_candidates = [
                item
                for item in physical_candidates
                if item.get("kind") == "profile_edge_candidate"
                and any(
                    isinstance(source_line, dict)
                    and _same_source_profile_line(item, source_line)
                    for source_line in witness_lines
                )
            ]
            if exact_profile_candidates:
                physical_identities = {
                    identity
                    for item in exact_profile_candidates
                    for identity in [_profile_source_identity(item)]
                    if identity is not None
                }
                if len(physical_identities) == 1:
                    physical_candidates = [
                        min(
                            exact_profile_candidates,
                            key=lambda item: str(item.get("ref") or ""),
                        )
                    ]
                    narrowing_basis = "exact_crossing_witness_profile_line_identity"
            if narrowing_basis is None:
                continuation_profile_candidates = [
                    item
                    for item in physical_candidates
                    if item.get("kind") == "profile_edge_candidate"
                    and any(
                        isinstance(source_line, dict)
                        and _collinear_profile_continuation(item, source_line)
                        for source_line in witness_lines
                    )
                ]
                if len(continuation_profile_candidates) == 1:
                    physical_candidates = continuation_profile_candidates
                    narrowing_basis = (
                        "unique_collinear_crossing_witness_profile_continuation"
                    )

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
                "ownership_narrowing_basis": narrowing_basis,
                "ignored_nonownership_anchors": [
                    *[
                        {
                            **item,
                            "ownership_rejection_reason": (
                                "profile_not_connected_to_witness_terminal"
                            ),
                        }
                        for item in disconnected_profiles
                    ],
                    *[
                        {
                            **item,
                            "ownership_rejection_reason": (
                                "profile_vertex_not_connected_to_witness_terminal"
                            ),
                        }
                        for item in disconnected_vertices
                    ],
                    *[
                        item
                        for item in nearest
                        if isinstance(item, dict)
                        and item.get("kind") not in _PHYSICAL_ANCHOR_KINDS
                    ],
                ],
            }
        )

    return {
        "candidate_id": candidate_id,
        "status": "bracketed",
        "selection_basis": selection_basis,
        "numeric_value_used_for_geometry": False,
        "text_axis_coordinate_px": round(text_coordinate, 3),
        "selected_witness_indices": [first[0], second[0]],
        "selected_witness_positions_px": [first[1], second[1]],
        "all_endpoint_candidates_unique": all(
            item["status"] == "unique_physical_candidate" for item in endpoints
        ),
        "endpoints": endpoints,
    }
