from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .circle_datum_alignment import derive_circle_overall_center_alignments
from .dimension_endpoint_candidates import derive_dimension_endpoint_candidates
from .engineering_callout_binding import bind_callout_to_circle_entity
from .engineering_callouts import parse_engineering_callout
from .engineering_dimension_binding import bind_callout_to_dimension_candidate
from .engineering_linear_pattern_binding import bind_callout_to_linear_pattern
from .hidden_projection_centers import derive_hidden_projection_center_candidates
from .evidence import Axis, ViewKind
from .reader_observations import (
    ObservationAssociation,
    ObservationDimension,
    ObservationDimensionEndpoint,
    ObservationEntity,
    ObservationUnresolved,
    ObservationValue,
    ObservationView,
)
from .reader_semantic_answers import (
    PartialOverallDimensionFact,
    PartialReaderObservations,
)
from .view_metric_calibration import derive_view_axis_boundaries


class HybridCaptureAdapterError(ValueError):
    """Raised when Hybrid OCR evidence cannot be adapted without inference."""


class _StrictAdapterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HybridRegionView(_StrictAdapterModel):
    region_id: str = Field(min_length=1)
    view_kind: ViewKind
    evidence: list[str] = Field(min_length=1)


class HybridAdapterContext(_StrictAdapterModel):
    schema_version: Literal["hybrid-adapter-context-v1"] = Field(
        default="hybrid-adapter-context-v1",
        alias="schema",
    )
    region_views: list[HybridRegionView] = Field(min_length=1)
    overall_dimension_facts: list[PartialOverallDimensionFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_regions(self) -> HybridAdapterContext:
        region_ids = [item.region_id for item in self.region_views]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("hybrid adapter region_ids must be unique")
        return self


def _axis_for(view_kind: ViewKind, orientation: str) -> Axis:
    mapping: dict[tuple[str, str], Axis] = {
        ("front", "horizontal"): "X",
        ("front", "vertical"): "Z",
        ("side", "horizontal"): "Y",
        ("side", "vertical"): "Z",
        ("top", "horizontal"): "X",
        ("top", "vertical"): "Y",
    }
    try:
        return mapping[(view_kind, orientation)]
    except KeyError as exc:
        raise HybridCaptureAdapterError(
            f"unsupported view/orientation combination {view_kind!r}/{orientation!r}"
        ) from exc


def _dimension_value(token: str) -> tuple[float, str | None]:
    tolerance = re.fullmatch(
        r"(\d+(?:\.\d+)?)±(\d+(?:\.\d+)?)",
        token,
    )
    if tolerance:
        value = float(tolerance.group(1))
        if value <= 0:
            raise HybridCaptureAdapterError("dimension value must be positive")
        return value, token

    if not re.fullmatch(r"\d+(?:\.\d+)?", token):
        raise HybridCaptureAdapterError(
            f"accepted Hybrid token is not a supported linear dimension: {token!r}"
        )
    value = float(token)
    if value <= 0:
        raise HybridCaptureAdapterError("dimension value must be positive")
    return value, None


def _candidate_evidence(candidate_id: str) -> list[str]:
    return [
        f"hybrid:{candidate_id}:whole",
        f"hybrid:{candidate_id}:wide",
    ]


def _coverage_unresolved(
    report: dict[str, Any],
    candidate_lookup: dict[str, dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
) -> list[ObservationUnresolved]:
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        raise HybridCaptureAdapterError("Hybrid OCR v2 report requires a coverage ledger")
    if coverage.get("observed_silent_drop_count") != 0:
        raise HybridCaptureAdapterError("Hybrid OCR report has observed silent evidence drops")

    unresolved: list[ObservationUnresolved] = []
    conflicting_candidate_ids = {
        str(item.get("candidate_id") or "")
        for item in coverage.get("conflicting_linear_observations", [])
        if isinstance(item, dict) and item.get("candidate_id")
    }

    for item in coverage.get("conflicting_linear_observations", []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        candidate = candidate_lookup.get(candidate_id)
        if candidate is None:
            raise HybridCaptureAdapterError(
                f"coverage conflict references unknown candidate {candidate_id!r}"
            )
        region_id = str(candidate.get("region_id") or "")
        region_view = view_lookup.get(region_id)
        if region_view is None:
            raise HybridCaptureAdapterError(f"missing view context for region {region_id!r}")
        axis = _axis_for(
            region_view.view_kind,
            str(candidate.get("orientation") or ""),
        )
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=(
                    "Hybrid whole/local OCR disagreement: "
                    f"whole={item.get('token')!r}, "
                    f"local={item.get('local_tokens')!r}."
                ),
                field="dimension_value_candidate",
                axis=axis,
                evidence=_candidate_evidence(candidate_id),
                required_for_modeling=True,
            )
        )

    for item in coverage.get("secondary_assignment_observations", []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        evidence = (
            _candidate_evidence(candidate_id)
            if candidate_id
            else [f"hybrid:whole:{item.get('source_item_index')}"]
        )
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=(
                    "Whole OCR linear observation was associated with a DG "
                    "but was not selected as that DG's global proposal: "
                    f"token={item.get('token')!r}, "
                    f"selected={item.get('selected_proposal_token')!r}."
                ),
                field="secondary_linear_assignment",
                evidence=evidence,
                required_for_modeling=False,
            )
        )

    for item in coverage.get("unassigned_linear_observations", []):
        if not isinstance(item, dict):
            continue
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=(
                    "Whole OCR found a standalone linear token with no unique "
                    f"DG assignment: token={item.get('token')!r}."
                ),
                field="unassigned_linear_text",
                evidence=[f"hybrid:whole:{item.get('source_item_index')}"],
                required_for_modeling=False,
            )
        )

    for item in coverage.get("local_only_linear_observations", []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        candidate = candidate_lookup.get(candidate_id)
        if candidate is None:
            raise HybridCaptureAdapterError(
                f"local-only coverage references unknown candidate {candidate_id!r}"
            )
        required = (
            candidate.get("accepted_token") is None
            and candidate_id not in conflicting_candidate_ids
        )
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=(
                    "Wide local OCR found a linear token without a matching "
                    f"whole-drawing assignment: token={item.get('token')!r}."
                ),
                field="local_only_linear_text",
                evidence=_candidate_evidence(candidate_id),
                required_for_modeling=required,
            )
        )

    return unresolved


def _circle_center_entity_key(
    physical_candidate: dict[str, Any],
    entity_keys: set[str],
) -> str | None:
    if physical_candidate.get("kind") != "circle_center_axis":
        return None
    ref = str(physical_candidate.get("ref") or "")
    match = re.fullmatch(r"(.+)\.center_[xyz]", ref)
    if match is None:
        return None
    entity_key = match.group(1)
    return entity_key if entity_key in entity_keys else None


def _center_entity_candidate(
    physical_candidate: dict[str, Any],
    entity_keys: set[str],
) -> tuple[str, Literal["circle_center", "centerline"]] | None:
    circle_key = _circle_center_entity_key(
        physical_candidate,
        entity_keys,
    )
    if circle_key is not None:
        return circle_key, "circle_center"

    if physical_candidate.get("kind") == "hidden_projection_center_axis":
        entity_key = str(physical_candidate.get("entity_key") or "")
        if entity_key in entity_keys:
            return entity_key, "centerline"
    return None


def _dimension_direction_from_image_order(
    view_kind: str,
    orientation: str,
) -> Literal[-1, 1] | None:
    if view_kind == "front" and orientation == "horizontal":
        return 1
    if view_kind == "front" and orientation == "vertical":
        return -1
    return None


def _enrich_candidate_with_hidden_projection_centers(
    candidate: dict[str, Any],
    *,
    report: dict[str, Any],
    view_lookup: dict[str, HybridRegionView],
    profile_inventory: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if candidate.get("accepted_token") is None:
        return candidate, []

    region_id = str(candidate.get("region_id") or "")
    region_view = view_lookup.get(region_id)
    if region_view is None:
        return candidate, []

    region = next(
        (
            item
            for item in report.get("regions", [])
            if isinstance(item, dict)
            and str(item.get("region_id") or "") == region_id
        ),
        None,
    )
    if region is None:
        return candidate, []

    center_candidates = derive_hidden_projection_center_candidates(
        candidate,
        region=region,
        view_kind=region_view.view_kind,
        profile_inventory=profile_inventory,
    )
    if not center_candidates:
        return candidate, []

    evidence_by_index = {
        int(item["witness_index"]): dict(item)
        for item in candidate.get("witness_anchor_evidence", [])
        if isinstance(item, dict) and isinstance(item.get("witness_index"), int)
    }
    witness_positions = candidate.get("witness_positions_px", [])
    enriched: list[dict[str, Any]] = []
    for witness_index, raw_position in enumerate(witness_positions):
        if not isinstance(raw_position, (int, float)):
            continue
        existing = evidence_by_index.get(witness_index, {})
        nearest = [
            dict(item)
            for item in existing.get("nearest_anchors", [])
            if isinstance(item, dict)
        ]
        existing_refs = {str(item.get("ref") or "") for item in nearest}
        for center in center_candidates:
            if center.get("witness_index") != witness_index:
                continue
            ref = str(center.get("ref") or "")
            if not ref or ref in existing_refs:
                continue
            nearest.append(
                {
                    key: value
                    for key, value in center.items()
                    if key != "witness_index"
                }
            )
            existing_refs.add(ref)

        enriched.append(
            {
                **existing,
                "witness_index": witness_index,
                "position_px": float(raw_position),
                "axis": existing.get(
                    "axis",
                    (
                        "x"
                        if candidate.get("orientation") == "horizontal"
                        else "y"
                    ),
                ),
                "nearest_anchors": nearest,
            }
        )

    return (
        {
            **candidate,
            "witness_anchor_evidence": enriched,
        },
        center_candidates,
    )


def _region_profile_match_tolerance(
    report: dict[str, Any],
    region_id: str,
) -> float:
    for region in report.get("regions", []):
        if not isinstance(region, dict) or str(region.get("region_id") or "") != region_id:
            continue
        bbox = region.get("bbox_px")
        if (
            isinstance(bbox, list)
            and len(bbox) == 4
            and isinstance(bbox[2], (int, float))
            and isinstance(bbox[3], (int, float))
        ):
            return max(2.0, min(float(bbox[2]), float(bbox[3])) * 0.003)
    return 2.0


def _enrich_candidate_from_profile_inventory(
    candidate: dict[str, Any],
    *,
    report: dict[str, Any],
    profile_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach only pixel-coincident profile candidates to existing witnesses.

    This does not claim endpoint ownership.  Multiple matches remain multiple
    physical candidates and therefore fail closed downstream.
    """

    region_id = str(candidate.get("region_id") or "")
    orientation = str(candidate.get("orientation") or "")
    if orientation == "horizontal":
        source_orientation = "vertical"
    elif orientation == "vertical":
        source_orientation = "horizontal"
    else:
        return candidate

    tolerance = _region_profile_match_tolerance(report, region_id)
    witness_positions = candidate.get("witness_positions_px", [])
    raw_evidence = candidate.get("witness_anchor_evidence", [])
    evidence_by_index = {
        int(item["witness_index"]): item
        for item in raw_evidence
        if isinstance(item, dict) and isinstance(item.get("witness_index"), int)
    }

    enriched_evidence: list[dict[str, Any]] = []
    for index, raw_position in enumerate(witness_positions):
        if not isinstance(raw_position, (int, float)):
            continue
        position = float(raw_position)
        existing = evidence_by_index.get(index, {})
        nearest = [
            dict(item)
            for item in existing.get("nearest_anchors", [])
            if isinstance(item, dict)
        ]
        existing_refs = {str(item.get("ref") or "") for item in nearest}

        matches = [
            item
            for item in profile_inventory
            if isinstance(item, dict)
            and item.get("kind") == "profile_edge_candidate"
            and str(item.get("region_id") or "") == region_id
            and str(item.get("source_orientation") or "") == source_orientation
            and isinstance(item.get("position_px"), (int, float))
            and abs(float(item["position_px"]) - position) <= tolerance
        ]
        matches.sort(
            key=lambda item: (
                abs(float(item["position_px"]) - position),
                str(item.get("ref") or ""),
            )
        )
        for item in matches:
            ref = str(item.get("ref") or "")
            if not ref or ref in existing_refs:
                continue
            nearest.append(
                {
                    **item,
                    "distance_px": abs(float(item["position_px"]) - position),
                }
            )
            existing_refs.add(ref)

        enriched_evidence.append(
            {
                **existing,
                "witness_index": index,
                "position_px": position,
                "axis": existing.get(
                    "axis",
                    "x" if orientation == "horizontal" else "y",
                ),
                "nearest_anchors": nearest,
            }
        )

    return {
        **candidate,
        "witness_anchor_evidence": enriched_evidence,
    }


def _boundary_role_lookup(
    boundaries: list[dict[str, Any]],
) -> dict[str, Literal["overall_min", "overall_max"]]:
    output: dict[str, Literal["overall_min", "overall_max"]] = {}
    conflicted: set[str] = set()

    for boundary in boundaries:
        if not isinstance(boundary, dict) or boundary.get("status") != "resolved":
            continue
        for anchor in boundary.get("anchors", []):
            if not isinstance(anchor, dict):
                continue
            ref = str(anchor.get("ref") or "")
            role = anchor.get("role")
            if not ref or role not in {"overall_min", "overall_max"}:
                continue
            typed_role: Literal["overall_min", "overall_max"] = role
            previous = output.get(ref)
            if previous is not None and previous != typed_role:
                conflicted.add(ref)
                continue
            output[ref] = typed_role

    for ref in conflicted:
        output.pop(ref, None)
    return output


def _profile_boundary_entities(
    profile_inventory: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
) -> tuple[list[ObservationEntity], dict[str, str]]:
    entities: list[ObservationEntity] = []
    by_ref: dict[str, str] = {}
    seen_keys: set[str] = set()

    for item in profile_inventory:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "profile_edge_candidate":
            continue
        region_id = str(item.get("region_id") or "")
        ref = str(item.get("ref") or "")
        if not region_id or not ref or region_id not in view_lookup:
            continue

        entity_key = f"{region_id}.PROFILE_BOUNDARY.{ref}"
        if entity_key in seen_keys:
            continue
        seen_keys.add(entity_key)
        by_ref[ref] = entity_key
        entities.append(
            ObservationEntity(
                key=entity_key,
                view_key=f"view.{region_id}",
                shape="profile",
                cross_view_disposition="single_view",
                evidence=[f"hybrid:profile-edge:{ref}"],
                required_for_modeling=False,
            )
        )

    return entities, by_ref


def _dimension_endpoints_from_candidates(
    candidate: dict[str, Any],
    *,
    entity_keys: set[str],
    boundary_roles: dict[str, Literal["overall_min", "overall_max"]],
    profile_entity_by_ref: dict[str, str],
    evidence: list[str],
) -> tuple[list[ObservationDimensionEndpoint], str | None]:
    endpoint_candidates = derive_dimension_endpoint_candidates(candidate)
    raw_endpoints = endpoint_candidates.get("endpoints")
    if not isinstance(raw_endpoints, list) or len(raw_endpoints) != 2:
        return (
            [
                ObservationDimensionEndpoint(
                    role="unresolved",
                    unresolved_kind="intermediate_surface",
                    evidence=evidence,
                ),
                ObservationDimensionEndpoint(
                    role="unresolved",
                    unresolved_kind="intermediate_surface",
                    evidence=evidence,
                ),
            ],
            (
                "Hybrid OCR confirms value and measured axis; endpoint candidate "
                "evidence does not yet close both physical endpoints."
            ),
        )

    output: list[ObservationDimensionEndpoint] = []
    for raw_endpoint in raw_endpoints:
        if not isinstance(raw_endpoint, dict):
            output.append(
                ObservationDimensionEndpoint(
                    role="unresolved",
                    unresolved_kind="intermediate_surface",
                    evidence=evidence,
                )
            )
            continue

        physical_candidates = raw_endpoint.get("physical_candidates", [])
        if not isinstance(physical_candidates, list):
            physical_candidates = []

        if (
            raw_endpoint.get("status") == "unique_physical_candidate"
            and len(physical_candidates) == 1
            and isinstance(physical_candidates[0], dict)
        ):
            center_candidate = _center_entity_candidate(
                physical_candidates[0],
                entity_keys,
            )
            if center_candidate is not None:
                entity_key, center_basis = center_candidate
                output.append(
                    ObservationDimensionEndpoint(
                        role="entity_center",
                        entity_key=entity_key,
                        basis=center_basis,
                        evidence=evidence,
                    )
                )
                continue

            physical = physical_candidates[0]
            if physical.get("kind") == "profile_edge_candidate":
                ref = str(physical.get("ref") or "")
                boundary_role = boundary_roles.get(ref)
                if boundary_role is not None:
                    output.append(
                        ObservationDimensionEndpoint(
                            role=boundary_role,
                            evidence=evidence,
                        )
                    )
                    continue

                profile_entity_key = profile_entity_by_ref.get(ref)
                if profile_entity_key is not None:
                    output.append(
                        ObservationDimensionEndpoint(
                            role="profile_boundary",
                            entity_key=profile_entity_key,
                            basis="profile_edge",
                            evidence=evidence,
                        )
                    )
                    continue

        candidate_entity_keys = sorted(
            {
                center_candidate[0]
                for physical_candidate in physical_candidates
                if isinstance(physical_candidate, dict)
                for center_candidate in [
                    _center_entity_candidate(
                        physical_candidate,
                        entity_keys,
                    )
                ]
                if center_candidate is not None
            }
        )
        output.append(
            ObservationDimensionEndpoint(
                role="unresolved",
                candidate_entity_keys=candidate_entity_keys,
                unresolved_kind=(
                    "ambiguous_owner"
                    if candidate_entity_keys
                    else "intermediate_surface"
                ),
                evidence=evidence,
            )
        )

    reason = (
        None
        if all(item.role != "unresolved" for item in output)
        else (
            "Hybrid OCR confirms value and measured axis; deterministic endpoint "
            "candidates close only the explicitly supported physical owners."
        )
    )
    return output, reason


def _point_in_bbox(
    point: tuple[float, float],
    bbox: list[Any],
) -> bool:
    if len(bbox) != 4 or not all(isinstance(value, (int, float)) for value in bbox):
        return False
    left, top, width, height = (float(value) for value in bbox)
    x, y = point
    return left <= x <= left + width and top <= y <= top + height


def _bbox_bounds(
    bbox: Any,
) -> tuple[float, float, float, float] | None:
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
        return None
    xs = [float(point[0]) for point in bbox]
    ys = [float(point[1]) for point in bbox]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_center(bbox: Any) -> tuple[float, float] | None:
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
        return None
    return (
        sum(float(point[0]) for point in bbox) / len(bbox),
        sum(float(point[1]) for point in bbox) / len(bbox),
    )


def _circle_entities(
    report: dict[str, Any],
    view_lookup: dict[str, HybridRegionView],
) -> list[ObservationEntity]:
    regions = report.get("regions", [])
    if not isinstance(regions, list):
        return []

    output: list[ObservationEntity] = []
    seen: set[str] = set()
    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        if region_id not in view_lookup:
            continue
        groups = region.get("circle_groups", [])
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("circle_group_id") or "")
            rings = group.get("rings", [])
            if not group_id or not isinstance(rings, list) or not rings:
                continue
            key = f"{region_id}.{group_id}"
            if key in seen:
                raise HybridCaptureAdapterError(f"duplicate Hybrid circle entity key {key!r}")
            seen.add(key)
            output.append(
                ObservationEntity(
                    key=key,
                    view_key=f"view.{region_id}",
                    shape=("concentric_circles" if len(rings) > 1 else "circle"),
                    cross_view_disposition=None,
                    evidence=[f"hybrid:geometry:{region_id}:{group_id}"],
                    required_for_modeling=False,
                )
            )
    return output


def _callout_binding_groups(
    items: list[Any],
) -> tuple[
    dict[Any, list[list[float]]],
    dict[Any, list[Any]],
]:
    """Group vertically adjacent engineering callout lines for one leader.

    OCR often emits a multi-line hole note as separate text observations even
    though the drawing provides one shared leader.  Grouping affects geometry
    binding only; each line keeps its own parsed semantic facts.
    """

    records: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_item_index = item.get("source_item_index")
        parsed = parse_engineering_callout(str(item.get("text") or ""))
        bounds = _bbox_bounds(item.get("bbox"))
        if parsed is None or bounds is None:
            continue
        left, top, right, bottom = bounds
        records.append(
            {
                "source_item_index": source_item_index,
                "bounds": bounds,
                "width": max(1.0, right - left),
                "height": max(1.0, bottom - top),
            }
        )

    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, left in enumerate(records):
        l0, t0, r0, b0 = left["bounds"]
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            l1, t1, r1, b1 = right["bounds"]
            overlap = max(0.0, min(r0, r1) - max(l0, l1))
            overlap_ratio = overlap / min(
                float(left["width"]),
                float(right["width"]),
            )
            vertical_gap = max(t1 - b0, t0 - b1, 0.0)
            allowed_gap = max(
                6.0,
                min(float(left["height"]), float(right["height"])) * 0.35,
            )
            if overlap_ratio >= 0.45 and vertical_gap <= allowed_gap:
                union(left_index, right_index)

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        groups.setdefault(find(index), []).append(record)

    bbox_by_index: dict[Any, list[list[float]]] = {}
    members_by_index: dict[Any, list[Any]] = {}
    for members in groups.values():
        left = min(float(item["bounds"][0]) for item in members)
        top = min(float(item["bounds"][1]) for item in members)
        right = max(float(item["bounds"][2]) for item in members)
        bottom = max(float(item["bounds"][3]) for item in members)
        bbox = [
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
        ]
        member_ids = sorted(
            (item["source_item_index"] for item in members),
            key=lambda value: str(value),
        )
        for item in members:
            source_item_index = item["source_item_index"]
            bbox_by_index[source_item_index] = bbox
            members_by_index[source_item_index] = member_ids

    return bbox_by_index, members_by_index


def _recover_geometry_backed_leading_zero_hole_value(
    parsed: dict[str, Any],
    binding: dict[str, Any],
) -> dict[str, Any]:
    """Recover a likely lost diameter glyph only after hole geometry is bound.

    The parser remains conservative.  A leading-zero token is promoted only
    when explicit hole semantics are present and the note has deterministic
    geometry ownership.  Recess diameters stay distinct from the primary hole
    diameter until the recess subtype is independently resolved.
    """

    if binding.get("status") not in {"bound", "dimension_backed", "pattern_backed"}:
        return parsed
    ambiguities = parsed.get("ambiguities", [])
    if (
        not isinstance(ambiguities, list)
        or "leading_zero_diameter_like_token_not_promoted" not in ambiguities
    ):
        return parsed

    facts = parsed.get("facts", {})
    if not isinstance(facts, dict) or "diameter" in facts:
        return parsed
    if not (facts.get("through") is True or facts.get("recessed_hole") is True):
        return parsed

    normalized = str(parsed.get("normalized_text") or "")
    match = re.search(
        r"(?<![A-Z0-9Ø.])(0\d+(?:\.\d+)?)(?![A-Z0-9.])",
        normalized,
        flags=re.IGNORECASE,
    )
    if match is None:
        return parsed

    raw_value = match.group(1)
    try:
        value = float(raw_value[1:])
    except ValueError:
        return parsed
    if value <= 0:
        return parsed

    recovered_facts = dict(facts)
    if recovered_facts.get("recessed_hole") is True:
        recovered_facts["recess_diameter"] = value
        recovered_field = "recess_diameter"
    else:
        recovered_facts["diameter"] = value
        recovered_field = "diameter"

    return {
        **parsed,
        "facts": recovered_facts,
        "ambiguities": [
            item
            for item in ambiguities
            if item != "leading_zero_diameter_like_token_not_promoted"
        ],
        "geometry_backed_ocr_recovery": {
            "field": recovered_field,
            "value": value,
            "raw_token": raw_value,
            "basis": (
                "bound_hole_geometry_plus_explicit_through_or_recess_semantics"
            ),
        },
    }


def _engineering_callout_routing(
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
) -> tuple[
    list[dict[str, Any]],
    list[ObservationEntity],
    list[ObservationValue],
    list[ObservationUnresolved],
]:
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        return [], [], [], []

    regions = report.get("regions", [])
    annotation_lines = report.get("annotation_line_candidates", [])
    region_boxes: list[tuple[str, list[Any]]] = []
    if isinstance(regions, list):
        for region in regions:
            if not isinstance(region, dict):
                continue
            region_id = str(region.get("region_id") or "")
            bbox = region.get("bbox_px")
            if region_id and isinstance(bbox, list):
                region_boxes.append((region_id, bbox))

    routed_items = coverage.get(
        "routed_elsewhere_or_unclassified_observations",
        [],
    )
    binding_bbox_by_index, binding_group_by_index = _callout_binding_groups(
        routed_items if isinstance(routed_items, list) else []
    )

    ledger: list[dict[str, Any]] = []
    callout_entities: list[ObservationEntity] = []
    callout_entity_keys: set[str] = set()
    unresolved: list[ObservationUnresolved] = []
    value_records: dict[tuple[str, str], dict[str, Any]] = {}
    conflicted_targets: set[tuple[str, str]] = set()
    conflict_evidence: dict[tuple[str, str], list[str]] = {}

    for item in routed_items:
        if not isinstance(item, dict):
            continue
        parsed = parse_engineering_callout(str(item.get("text") or ""))
        if parsed is None:
            continue

        source_item_index = item.get("source_item_index")
        evidence = [f"hybrid:whole:{source_item_index}"]
        binding_bbox = binding_bbox_by_index.get(
            source_item_index,
            item.get("bbox"),
        )
        center = _bbox_center(item.get("bbox"))
        region_candidates = (
            sorted(region_id for region_id, bbox in region_boxes if _point_in_bbox(center, bbox))
            if center is not None
            else []
        )
        leader_binding = bind_callout_to_circle_entity(
            binding_bbox,
            annotation_lines,
            regions,
        )
        linear_pattern_binding: dict[str, Any] | None = None
        if (
            len(region_candidates) == 1
            and any(
                key in parsed["facts"]
                for key in {
                    "diameter",
                    "thread_spec",
                    "through",
                    "recessed_hole",
                }
            )
        ):
            region_id = region_candidates[0]
            region = next(
                (
                    candidate_region
                    for candidate_region in regions
                    if isinstance(candidate_region, dict)
                    and str(candidate_region.get("region_id") or "") == region_id
                ),
                None,
            )
            region_view = view_lookup.get(region_id)
            if region is not None and region_view is not None:
                candidate_pattern_binding = bind_callout_to_linear_pattern(
                    binding_bbox,
                    annotation_lines,
                    region,
                    view_kind=region_view.view_kind,
                    profile_inventory=(
                        report.get("structural_profile_inventory")
                        if isinstance(
                            report.get("structural_profile_inventory"),
                            list,
                        )
                        else []
                    ),
                )
                if candidate_pattern_binding.get("status") == "bound":
                    linear_pattern_binding = candidate_pattern_binding

        dimension_binding: dict[str, Any] | None = None
        if (
            isinstance(parsed["facts"].get("diameter"), (int, float))
            and len(region_candidates) == 1
        ):
            candidate_binding = bind_callout_to_dimension_candidate(
                binding_bbox,
                candidates,
                region_id=region_candidates[0],
            )
            if candidate_binding.get("status") == "bound":
                dimension_binding = candidate_binding

        binding = leader_binding
        if dimension_binding is not None:
            dimension_distance = float(
                dimension_binding.get("text_geometry_distance_px", float("inf"))
            )
            leader_support = (
                leader_binding.get("support", [])
                if leader_binding.get("status") == "bound"
                else []
            )
            leader_distance = min(
                (
                    float(item.get("text_touch_distance_px", float("inf")))
                    for item in leader_support
                    if isinstance(item, dict)
                ),
                default=float("inf"),
            )

            if (
                leader_binding.get("status") != "bound"
                or dimension_distance + 1e-9 < leader_distance
            ):
                projection_entity_key = (
                    f"{region_candidates[0]}."
                    f"{dimension_binding['candidate_id']}."
                    "DIAMETER_PROJECTION"
                )
                binding = {
                    **dimension_binding,
                    "status": "dimension_backed",
                    "entity_key": projection_entity_key,
                    "competing_leader_binding": (
                        leader_binding
                        if leader_binding.get("status") == "bound"
                        else None
                    ),
                }
                if projection_entity_key not in callout_entity_keys:
                    callout_entity_keys.add(projection_entity_key)
                    callout_entities.append(
                        ObservationEntity(
                            key=projection_entity_key,
                            view_key=f"view.{region_candidates[0]}",
                            shape="hidden_parallel",
                            cross_view_disposition=None,
                            evidence=[
                                *evidence,
                                (
                                    "hybrid:"
                                    f"{dimension_binding['candidate_id']}:geometry"
                                ),
                            ],
                            required_for_modeling=False,
                        )
                    )
            elif abs(dimension_distance - leader_distance) <= 1e-9:
                binding = {
                    "status": "unresolved",
                    "reason": "competing_callout_geometry_bindings",
                    "leader_binding": leader_binding,
                    "dimension_binding": dimension_binding,
                }

        if binding.get("status") != "dimension_backed":
            if (
                binding.get("status") == "bound"
                and linear_pattern_binding is not None
            ):
                binding = {
                    "status": "unresolved",
                    "reason": "competing_callout_geometry_bindings",
                    "leader_binding": binding,
                    "linear_pattern_binding": linear_pattern_binding,
                }
            elif (
                binding.get("status") != "bound"
                and linear_pattern_binding is not None
            ):
                pattern_entity_key = str(
                    linear_pattern_binding["entity_key"]
                )
                binding = {
                    **linear_pattern_binding,
                    "status": "pattern_backed",
                }
                if pattern_entity_key not in callout_entity_keys:
                    callout_entity_keys.add(pattern_entity_key)
                    callout_entities.append(
                        ObservationEntity(
                            key=pattern_entity_key,
                            view_key=f"view.{linear_pattern_binding['region_id']}",
                            shape="hidden_parallel",
                            cross_view_disposition=None,
                            evidence=[
                                *evidence,
                                (
                                    "hybrid:linear-pattern:"
                                    f"{linear_pattern_binding['pattern_index']}"
                                ),
                            ],
                            required_for_modeling=False,
                        )
                    )

        parsed = _recover_geometry_backed_leading_zero_hole_value(
            parsed,
            binding,
        )

        record = {
            "source_item_index": source_item_index,
            "bbox": item.get("bbox"),
            "binding_bbox": binding_bbox,
            "binding_group_source_item_indices": binding_group_by_index.get(
                source_item_index,
                [source_item_index],
            ),
            "confidence": item.get("confidence"),
            "region_candidates": region_candidates,
            "binding": binding,
            **parsed,
        }
        ledger.append(record)

        safe_facts = {
            key: value
            for key, value in parsed["facts"].items()
            if key
            in {
                "diameter",
                "fit",
                "thread_spec",
                "thread_depth",
                "through",
                "count",
                "recess_diameter",
                "recess_depth",
                "recessed_hole",
            }
        }

        if binding.get("status") not in {"bound", "dimension_backed", "pattern_backed"}:
            if len(region_candidates) == 1 and safe_facts:
                region_id = region_candidates[0]
                entity_key = f"{region_id}.CALLOUT.{source_item_index}"
                callout_entities.append(
                    ObservationEntity(
                        key=entity_key,
                        view_key=f"view.{region_id}",
                        shape="other",
                        cross_view_disposition=None,
                        evidence=evidence,
                        required_for_modeling=False,
                    )
                )
                unresolved.append(
                    ObservationUnresolved(
                        kind="feature_inventory",
                        reason=(
                            "Engineering callout facts are preserved on an "
                            "advisory view-local carrier, but exact geometry "
                            "ownership and physical feature identity remain unresolved."
                        ),
                        entity_keys=[entity_key],
                        field="engineering_callout_geometry_binding",
                        evidence=evidence,
                        required_for_modeling=True,
                    )
                )
                binding = {
                    **binding,
                    "status": "callout_backed",
                    "entity_key": entity_key,
                    "basis": "unique_region_callout_fact_transport",
                }
                record["binding"] = binding
            else:
                unresolved.append(
                    ObservationUnresolved(
                        kind="feature_inventory",
                        reason=(
                            "Engineering callout semantics were parsed, but visible "
                            "geometry ownership is not deterministically proven and "
                            "the callout cannot be assigned to one view region."
                        ),
                        field="engineering_callout_geometry_binding",
                        evidence=evidence,
                        required_for_modeling=True,
                    )
                )
                continue
        else:
            entity_key = str(binding["entity_key"])

        if binding.get("status") == "pattern_backed":
            axis_target = (entity_key, "axis")
            axis_value = binding.get("axis")
            if axis_value in {"X", "Y", "Z"}:
                value_records[axis_target] = {
                    "entity_key": entity_key,
                    "field": "axis",
                    "value": axis_value,
                    "evidence": [
                        *evidence,
                        (
                            "hybrid:linear-pattern:"
                            f"{binding.get('pattern_index')}"
                        ),
                    ],
                }

        for field, value in safe_facts.items():
            target = (entity_key, field)
            previous = value_records.get(target)
            if previous is None:
                value_records[target] = {
                    "entity_key": entity_key,
                    "field": field,
                    "value": value,
                    "evidence": list(evidence),
                }
                continue
            if previous["value"] == value:
                previous["evidence"] = list(dict.fromkeys([*previous["evidence"], *evidence]))
                continue
            conflicted_targets.add(target)
            conflict_evidence[target] = list(
                dict.fromkeys(
                    [
                        *conflict_evidence.get(target, []),
                        *previous["evidence"],
                        *evidence,
                    ]
                )
            )

        if (
            binding.get("status") in {"dimension_backed", "pattern_backed"}
            and "diameter" in safe_facts
            and not any(
                key in parsed["facts"]
                for key in {
                    "through",
                    "depth",
                    "thread_depth",
                    "recess_depth",
                }
            )
        ):
            unresolved.append(
                ObservationUnresolved(
                    kind="termination",
                    reason=(
                        "Diameter and projection geometry are known, but the "
                        "cylindrical feature has no explicit through/depth "
                        "termination evidence."
                    ),
                    entity_keys=[entity_key],
                    field="termination",
                    evidence=[
                        *evidence,
                        f"hybrid:{binding.get('candidate_id')}:geometry",
                    ],
                    required_for_modeling=True,
                )
            )

        unsupported_explicit_facts = {
            key: value for key, value in parsed["facts"].items() if key not in safe_facts
        }
        for field, value in sorted(unsupported_explicit_facts.items()):
            unresolved.append(
                ObservationUnresolved(
                    kind="feature_value",
                    reason=(
                        "Engineering callout explicitly provides "
                        f"{field}={value!r}, but the current canonical Capture "
                        "value contract has no safe direct representation."
                    ),
                    entity_keys=[entity_key],
                    field=field,
                    evidence=evidence,
                    required_for_modeling=True,
                )
            )

        for ambiguity in parsed["ambiguities"]:
            if ambiguity == "leading_zero_diameter_like_token_not_promoted":
                field = "diameter"
            elif ambiguity == "recessed_hole_subtype_not_explicit":
                field = "recessed_hole_subtype"
            else:
                field = "engineering_callout_value"
            unresolved.append(
                ObservationUnresolved(
                    kind="feature_value",
                    reason=(
                        "Engineering callout is bound to one visible entity but "
                        f"field {field!r} remains ambiguous: {ambiguity}."
                    ),
                    entity_keys=[entity_key],
                    field=field,
                    evidence=evidence,
                    required_for_modeling=True,
                )
            )

    for entity_key, field in sorted(conflicted_targets):
        evidence = conflict_evidence.get((entity_key, field), [])
        unresolved.append(
            ObservationUnresolved(
                kind="feature_value",
                reason=(
                    "Multiple geometry-bound engineering callouts disagree for "
                    f"{entity_key}.{field}; no value was selected."
                ),
                entity_keys=[entity_key],
                field=field,
                evidence=evidence or ["hybrid:callout:conflict"],
                required_for_modeling=True,
            )
        )

    values = [
        ObservationValue(
            entity_key=record["entity_key"],
            field=record["field"],
            value=record["value"],
            semantic=None,
            evidence=record["evidence"],
        )
        for target, record in sorted(value_records.items())
        if target not in conflicted_targets
    ]
    return ledger, callout_entities, values, unresolved


_PIXEL_INDEX_BY_VIEW_AXIS: dict[tuple[str, str], int] = {
    ("front", "X"): 0,
    ("front", "Z"): 1,
    ("side", "Y"): 0,
    ("side", "Z"): 1,
    ("top", "X"): 0,
    ("top", "Y"): 1,
}


def _token_numeric_value(token: Any) -> float | None:
    if not isinstance(token, str):
        return None
    try:
        return float(token)
    except ValueError:
        return None


def _bbox_center(bbox: Any) -> tuple[float, float] | None:
    bounds = _bbox_bounds(bbox)
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    return (left + right) / 2.0, (top + bottom) / 2.0


def _candidate_text_distance(
    candidate: dict[str, Any],
    bbox: Any,
) -> float | None:
    bounds = _bbox_bounds(bbox)
    if bounds is None:
        return None
    orientation = str(candidate.get("orientation") or "")
    axis = candidate.get("axis_px")
    span = candidate.get("line_span_px")
    if not (
        orientation in {"horizontal", "vertical"}
        and isinstance(axis, (int, float))
        and isinstance(span, list)
        and len(span) == 2
        and all(isinstance(value, (int, float)) for value in span)
    ):
        return None
    left, top, right, bottom = bounds
    start, end = sorted(float(value) for value in span)
    if orientation == "horizontal":
        dx = max(left - end, 0.0, start - right)
        dy = max(top - float(axis), 0.0, float(axis) - bottom)
    else:
        dx = max(left - float(axis), 0.0, float(axis) - right)
        dy = max(top - end, 0.0, start - bottom)
    return math.hypot(dx, dy)


def _recover_symmetric_half_dimensions(
    *,
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    profile_inventory: list[dict[str, Any]],
    boundary_roles: dict[str, Literal["overall_min", "overall_max"]],
    entity_keys: set[str],
) -> tuple[list[ObservationDimension], list[dict[str, Any]]]:
    """Recover a half-span dimension from a uniquely corroborated symmetric chain.

    Pixel geometry establishes only identity/topology. The engineering value
    comes from OCR tokens whose numeric relation is total = 2 * half.
    """

    coverage = report.get("coverage", {})
    unassigned = [
        item
        for item in coverage.get("unassigned_linear_observations", [])
        if isinstance(item, dict)
        and _token_numeric_value(item.get("token")) is not None
        and _bbox_center(item.get("bbox")) is not None
    ]
    if len(unassigned) < 2:
        return [], []

    recovered: list[ObservationDimension] = []
    ledger: list[dict[str, Any]] = []

    for region in report.get("regions", []):
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        view = view_lookup.get(region_id)
        if view is None:
            continue
        bbox = region.get("bbox_px")
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(isinstance(value, (int, float)) for value in bbox)
        ):
            continue
        rx, ry, rw, rh = (float(value) for value in bbox)
        region_tokens = []
        for item in unassigned:
            center = _bbox_center(item.get("bbox"))
            if center is None:
                continue
            cx, cy = center
            if (
                rx - rw * 0.20 <= cx <= rx + rw * 1.20
                and ry - rh * 0.20 <= cy <= ry + rh * 1.20
            ):
                region_tokens.append(item)
        if len(region_tokens) < 2:
            continue

        groups = region.get("circle_groups", [])
        if not isinstance(groups, list):
            continue
        horizontal_axis = _axis_for(view.view_kind, "horizontal")

        for group in groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("circle_group_id") or "")
            center_px = group.get("center_px")
            entity_key = f"{region_id}.{group_id}"
            if not (
                group_id
                and entity_key in entity_keys
                and isinstance(center_px, list)
                and len(center_px) >= 2
                and isinstance(center_px[0], (int, float))
            ):
                continue
            center_x = float(center_px[0])

            vertical_edges = sorted(
                [
                    item
                    for item in profile_inventory
                    if isinstance(item, dict)
                    and item.get("kind") == "profile_edge_candidate"
                    and str(item.get("region_id") or "") == region_id
                    and str(item.get("source_orientation") or "") == "vertical"
                    and isinstance(item.get("position_px"), (int, float))
                ],
                key=lambda item: float(item["position_px"]),
            )
            left_edges = [
                item for item in vertical_edges if float(item["position_px"]) < center_x
            ]
            right_edges = [
                item for item in vertical_edges if float(item["position_px"]) > center_x
            ]
            if not left_edges or not right_edges:
                continue
            left = left_edges[-1]
            right = right_edges[0]
            left_x = float(left["position_px"])
            right_x = float(right["position_px"])
            span = right_x - left_x
            if span <= 0:
                continue
            midpoint = (left_x + right_x) / 2.0
            if abs(midpoint - center_x) > max(2.0, span * 0.03):
                continue

            left_role = boundary_roles.get(str(left.get("ref") or ""))
            right_role = boundary_roles.get(str(right.get("ref") or ""))
            if left_role not in {"overall_min", "overall_max"} and right_role not in {
                "overall_min",
                "overall_max",
            }:
                continue

            chain_candidates = []
            for candidate in candidates:
                if (
                    str(candidate.get("region_id") or "") != region_id
                    or str(candidate.get("orientation") or "") != "horizontal"
                ):
                    continue
                witnesses = [
                    float(value)
                    for value in candidate.get("witness_positions_px", [])
                    if isinstance(value, (int, float))
                ]
                if len(witnesses) != 3:
                    continue
                tolerance = max(3.0, rw * 0.015)
                expected = [left_x, center_x, right_x]
                if all(
                    min(abs(witness - target) for witness in witnesses) <= tolerance
                    for target in expected
                ):
                    chain_candidates.append(candidate)
            if not chain_candidates:
                continue

            token_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for total in region_tokens:
                total_value = _token_numeric_value(total.get("token"))
                if total_value is None:
                    continue
                for half in region_tokens:
                    if half is total:
                        continue
                    half_value = _token_numeric_value(half.get("token"))
                    if half_value is None or half_value <= 0:
                        continue
                    if abs(total_value - 2.0 * half_value) <= max(
                        1e-6, abs(total_value) * 1e-6
                    ):
                        token_pairs.append((total, half))
            if not token_pairs:
                continue

            scored: list[tuple[float, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
            for candidate in chain_candidates:
                for total, half in token_pairs:
                    total_distance = _candidate_text_distance(candidate, total.get("bbox"))
                    half_distance = _candidate_text_distance(candidate, half.get("bbox"))
                    if total_distance is None or half_distance is None:
                        continue
                    scored.append(
                        (
                            total_distance + half_distance,
                            candidate,
                            total,
                            half,
                        )
                    )
            scored.sort(key=lambda item: (item[0], str(item[1].get("candidate_id") or "")))
            if not scored:
                continue
            if len(scored) > 1 and scored[1][0] - scored[0][0] < max(10.0, rh * 0.03):
                continue

            _, candidate, total, half = scored[0]
            half_center = _bbox_center(half.get("bbox"))
            if half_center is None:
                continue
            half_x = half_center[0]
            if half_x > right_x and right_role in {"overall_min", "overall_max"}:
                boundary_role = right_role
            elif half_x < left_x and left_role in {"overall_min", "overall_max"}:
                boundary_role = left_role
            else:
                continue

            half_value = _token_numeric_value(half.get("token"))
            if half_value is None:
                continue
            source_index = half.get("source_item_index")
            total_index = total.get("source_item_index")
            dimension_key = f"{region_id}.RECOVERED_HALF_{source_index}"
            recovered.append(
                ObservationDimension(
                    key=dimension_key,
                    value=half_value,
                    axis=horizontal_axis,
                    endpoints=[
                        ObservationDimensionEndpoint(
                            role="entity_center",
                            entity_key=entity_key,
                            basis="circle_center",
                            evidence=[
                                f"hybrid:whole:{source_index}",
                                f"hybrid:whole:{total_index}",
                            ],
                        ),
                        ObservationDimensionEndpoint(
                            role=boundary_role,
                            evidence=[
                                f"hybrid:whole:{source_index}",
                                f"hybrid:whole:{total_index}",
                            ],
                        ),
                    ],
                    evidence=[
                        f"hybrid:whole:{source_index}",
                        f"hybrid:whole:{total_index}",
                        f"hybrid:{candidate.get('candidate_id')}:symmetric-chain",
                    ],
                    required_for_modeling=True,
                )
            )
            ledger.append(
                {
                    "dimension_key": dimension_key,
                    "region_id": region_id,
                    "entity_key": entity_key,
                    "axis": horizontal_axis,
                    "half_value": half_value,
                    "total_value": _token_numeric_value(total.get("token")),
                    "half_source_item_index": source_index,
                    "total_source_item_index": total_index,
                    "candidate_id": candidate.get("candidate_id"),
                    "boundary_role": boundary_role,
                    "basis": (
                        "unique_three_witness_symmetric_chain_with_total_equals_two_half"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                }
            )

    return recovered, ledger


def _projection_alignment_tolerance(
    report: dict[str, Any],
    region_id: str,
) -> float:
    for region in report.get("regions", []):
        if not isinstance(region, dict) or str(region.get("region_id") or "") != region_id:
            continue
        bbox = region.get("bbox_px")
        if (
            isinstance(bbox, list)
            and len(bbox) == 4
            and isinstance(bbox[2], (int, float))
            and isinstance(bbox[3], (int, float))
        ):
            return max(3.0, min(float(bbox[2]), float(bbox[3])) * 0.006)
    return 3.0


def _unique_orthographic_associations(
    *,
    report: dict[str, Any],
    view_lookup: dict[str, HybridRegionView],
    entity_keys: set[str],
    callout_ledger: list[dict[str, Any]],
) -> tuple[list[ObservationAssociation], list[ObservationUnresolved]]:
    associations: list[ObservationAssociation] = []
    unresolved: list[ObservationUnresolved] = []
    claimed_entities: set[str] = set()

    regions = [
        item for item in report.get("regions", []) if isinstance(item, dict)
    ]

    for record in callout_ledger:
        if not isinstance(record, dict):
            continue
        binding = record.get("binding")
        if not (
            isinstance(binding, dict)
            and binding.get("status") == "dimension_backed"
        ):
            continue

        projection_entity = str(binding.get("entity_key") or "")
        source_region = str(binding.get("region_id") or "")
        orientation = str(binding.get("orientation") or "")
        projected_center = binding.get("projected_center_axis_px")
        source_view = view_lookup.get(source_region)
        if (
            not projection_entity
            or projection_entity not in entity_keys
            or source_view is None
            or orientation not in {"horizontal", "vertical"}
            or not isinstance(projected_center, (int, float))
        ):
            continue

        shared_axis = _axis_for(source_view.view_kind, orientation)
        source_pixel_index = _PIXEL_INDEX_BY_VIEW_AXIS.get(
            (source_view.view_kind, shared_axis)
        )
        if source_pixel_index is None:
            continue

        matches: list[tuple[str, float]] = []
        for region in regions:
            target_region = str(region.get("region_id") or "")
            if not target_region or target_region == source_region:
                continue
            target_view = view_lookup.get(target_region)
            if target_view is None:
                continue

            target_pixel_index = _PIXEL_INDEX_BY_VIEW_AXIS.get(
                (target_view.view_kind, shared_axis)
            )
            if target_pixel_index is None or target_pixel_index != source_pixel_index:
                continue

            tolerance = max(
                _projection_alignment_tolerance(report, source_region),
                _projection_alignment_tolerance(report, target_region),
            )
            groups = region.get("circle_groups", [])
            if not isinstance(groups, list):
                continue

            for group in groups:
                if not isinstance(group, dict):
                    continue
                group_id = str(group.get("circle_group_id") or "")
                center = group.get("center_px")
                if not (
                    group_id
                    and isinstance(center, list)
                    and len(center) >= 2
                    and isinstance(center[target_pixel_index], (int, float))
                ):
                    continue
                circle_entity = f"{target_region}.{group_id}"
                if circle_entity not in entity_keys:
                    continue

                residual = abs(
                    float(center[target_pixel_index]) - float(projected_center)
                )
                if residual <= tolerance:
                    matches.append((circle_entity, residual))

        matches.sort(key=lambda item: (item[1], item[0]))
        evidence = [
            f"hybrid:whole:{record.get('source_item_index')}",
            f"hybrid:{binding.get('candidate_id')}:geometry",
        ]

        if not matches:
            unresolved.append(
                ObservationUnresolved(
                    kind="feature_inventory",
                    reason=(
                        "Diameter projection has no orthographic circular "
                        "counterpart on the shared engineering axis."
                    ),
                    entity_keys=[projection_entity],
                    field="orthographic_circular_counterpart",
                    evidence=evidence,
                    required_for_modeling=True,
                )
            )
            continue

        if len(matches) > 1:
            unresolved.append(
                ObservationUnresolved(
                    kind="cross_view_identity",
                    reason=(
                        "Diameter projection has multiple orthographic circular "
                        "counterparts on the shared engineering axis."
                    ),
                    entity_keys=[
                        projection_entity,
                        *[item[0] for item in matches],
                    ],
                    basis=["projection_alignment"],
                    evidence=evidence,
                    required_for_modeling=True,
                )
            )
            continue

        circle_entity, residual = matches[0]
        if projection_entity in claimed_entities or circle_entity in claimed_entities:
            unresolved.append(
                ObservationUnresolved(
                    kind="cross_view_identity",
                    reason=(
                        "A unique projection match reuses an entity already claimed "
                        "by another deterministic cross-view association."
                    ),
                    entity_keys=[projection_entity, circle_entity],
                    basis=["projection_alignment"],
                    evidence=evidence,
                    required_for_modeling=True,
                )
            )
            continue

        claimed_entities.update({projection_entity, circle_entity})
        associations.append(
            ObservationAssociation(
                entity_keys=[projection_entity, circle_entity],
                basis=[
                    "projection_alignment",
                    "unique_orthographic_counterpart",
                ],
                evidence=[
                    *evidence,
                    f"hybrid:projection_alignment_residual_px:{residual:.3f}",
                ],
                required_for_modeling=True,
            )
        )

    return associations, unresolved


def adapt_hybrid_ocr_report(
    report: dict[str, Any],
    context: HybridAdapterContext,
) -> PartialReaderObservations:
    """Adapt Hybrid OCR v2 into partial Reader observations without inference."""

    if report.get("schema") != "dg-hybrid-ocr-bakeoff-v2":
        raise HybridCaptureAdapterError("adapter requires dg-hybrid-ocr-bakeoff-v2")

    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise HybridCaptureAdapterError("Hybrid report candidates must be a list")

    view_lookup = {item.region_id: item for item in context.region_views}
    profile_inventory = (
        report.get("structural_profile_inventory")
        if isinstance(report.get("structural_profile_inventory"), list)
        else []
    )
    working_candidates = [
        _enrich_candidate_from_profile_inventory(
            item,
            report=report,
            profile_inventory=profile_inventory,
        )
        for item in candidates
        if isinstance(item, dict)
    ]
    overall_dimensions = {
        {"X": "length_x", "Y": "width_y", "Z": "height_z"}[fact.axis]: fact.value
        for fact in context.overall_dimension_facts
    }
    boundaries = derive_view_axis_boundaries(
        candidates=working_candidates,
        region_views={item.region_id: item.view_kind for item in context.region_views},
        overall_dimensions=overall_dimensions,
        profile_inventory=profile_inventory,
    )
    boundary_roles = _boundary_role_lookup(boundaries)

    dimension_candidates: list[dict[str, Any]] = []
    hidden_center_records: list[dict[str, Any]] = []
    for candidate in working_candidates:
        enriched_candidate, center_records = (
            _enrich_candidate_with_hidden_projection_centers(
                candidate,
                report=report,
                view_lookup=view_lookup,
                profile_inventory=profile_inventory,
            )
        )
        dimension_candidates.append(enriched_candidate)
        hidden_center_records.extend(center_records)

    candidate_lookup: dict[str, dict[str, Any]] = {}
    dimensions: list[ObservationDimension] = []
    unresolved: list[ObservationUnresolved] = []
    entities = _circle_entities(report, view_lookup)
    profile_entities, profile_entity_by_ref = _profile_boundary_entities(
        profile_inventory,
        view_lookup,
    )
    entities.extend(profile_entities)

    hidden_entity_records: dict[str, dict[str, Any]] = {}
    for record in hidden_center_records:
        entity_key = str(record.get("entity_key") or "")
        if entity_key:
            hidden_entity_records.setdefault(entity_key, record)
    entities.extend(
        ObservationEntity(
            key=entity_key,
            view_key=f"view.{str(record['entity_key']).split('.', 1)[0]}",
            shape="hidden_parallel",
            cross_view_disposition=None,
            evidence=[
                (
                    "hybrid:hidden-pair:"
                    + ",".join(
                        str(item)
                        for item in record.get(
                            "source_pattern_indices",
                            [],
                        )
                    )
                )
            ],
            required_for_modeling=False,
        )
        for entity_key, record in sorted(hidden_entity_records.items())
    )
    geometry_values = [
        ObservationValue(
            entity_key=entity_key,
            field="axis",
            value=record["feature_axis"],
            semantic="axis",
            evidence=[
                (
                    "hybrid:hidden-pair:"
                    + ",".join(
                        str(item)
                        for item in record.get(
                            "source_pattern_indices",
                            [],
                        )
                    )
                )
            ],
        )
        for entity_key, record in sorted(hidden_entity_records.items())
        if record.get("feature_axis") in {"X", "Y", "Z"}
    ]
    circle_alignment_records = derive_circle_overall_center_alignments(
        regions=[
            item for item in report.get("regions", []) if isinstance(item, dict)
        ],
        region_views={item.region_id: item.view_kind for item in context.region_views},
        boundaries=boundaries,
        profile_inventory=profile_inventory,
    )
    datum_alignments: list[ObservationDatumAlignment] = []

    for raw_candidate in dimension_candidates:
        if not isinstance(raw_candidate, dict):
            raise HybridCaptureAdapterError("Hybrid candidate must be an object")
        candidate_id = str(raw_candidate.get("candidate_id") or "")
        region_id = str(raw_candidate.get("region_id") or "")
        if not candidate_id or not region_id:
            raise HybridCaptureAdapterError("Hybrid candidate requires candidate_id and region_id")
        if candidate_id in candidate_lookup:
            raise HybridCaptureAdapterError(f"duplicate Hybrid candidate_id {candidate_id!r}")
        candidate_lookup[candidate_id] = raw_candidate

        accepted_token = raw_candidate.get("accepted_token")
        if accepted_token is None:
            continue
        if not isinstance(accepted_token, str):
            raise HybridCaptureAdapterError(
                f"candidate {candidate_id!r} accepted_token must be a string"
            )

        region_view = view_lookup.get(region_id)
        if region_view is None:
            raise HybridCaptureAdapterError(f"missing view context for region {region_id!r}")
        orientation = str(raw_candidate.get("orientation") or "")
        axis = _axis_for(region_view.view_kind, orientation)
        value, tolerance_token = _dimension_value(accepted_token)
        dimension_key = f"{region_id}.{candidate_id}"
        evidence = _candidate_evidence(candidate_id)

        dimension_endpoints, unresolved_reason = _dimension_endpoints_from_candidates(
            raw_candidate,
            entity_keys={item.key for item in entities},
            boundary_roles=boundary_roles,
            profile_entity_by_ref=profile_entity_by_ref,
            evidence=evidence,
        )
        dimensions.append(
            ObservationDimension(
                key=dimension_key,
                value=value,
                axis=axis,
                endpoints=dimension_endpoints,
                unresolved_reason=unresolved_reason,
                direction=_dimension_direction_from_image_order(
                    region_view.view_kind,
                    orientation,
                ),
                evidence=evidence,
                required_for_modeling=True,
            )
        )

        if tolerance_token is not None:
            unresolved.append(
                ObservationUnresolved(
                    kind="other",
                    reason=(
                        "Hybrid OCR preserved a tolerance token; nominal "
                        f"dimension value is {value:g}, token={tolerance_token!r}."
                    ),
                    dimension_key=dimension_key,
                    dimension_value=value,
                    field="dimension_tolerance",
                    axis=axis,
                    evidence=evidence,
                    required_for_modeling=False,
                )
            )

    recovered_half_dimensions, symmetric_chain_ledger = (
        _recover_symmetric_half_dimensions(
            report=report,
            candidates=working_candidates,
            view_lookup=view_lookup,
            profile_inventory=profile_inventory,
            boundary_roles=boundary_roles,
            entity_keys={item.key for item in entities},
        )
    )
    dimensions.extend(recovered_half_dimensions)

    unresolved.extend(
        _coverage_unresolved(
            report,
            candidate_lookup,
            view_lookup,
        )
    )
    (
        callout_ledger,
        callout_entities,
        callout_values,
        callout_unresolved,
    ) = _engineering_callout_routing(
        report,
        working_candidates,
        view_lookup,
    )
    entities.extend(callout_entities)
    unresolved.extend(callout_unresolved)
    associations, association_unresolved = _unique_orthographic_associations(
        report=report,
        view_lookup=view_lookup,
        entity_keys={item.key for item in entities},
        callout_ledger=callout_ledger,
    )
    unresolved.extend(association_unresolved)

    coverage = report["coverage"]
    anchor_items = [
        {
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "region_id": str(candidate.get("region_id") or ""),
            "orientation": str(candidate.get("orientation") or ""),
            "accepted_token": candidate.get("accepted_token"),
            "witness_anchor_evidence": candidate.get(
                "witness_anchor_evidence",
                [],
            ),
            "witness_line_evidence": candidate.get(
                "witness_line_evidence",
                [],
            ),
            "endpoint_candidate_evidence": derive_dimension_endpoint_candidates(candidate),
        }
        for candidate in dimension_candidates
        if candidate.get("accepted_token") is not None
    ]

    observations = [
        {
            "kind": "hybrid_ocr_coverage_ledger",
            "schema": report.get("schema"),
            "coverage": coverage,
        },
        {
            "kind": "hybrid_dimension_anchor_ledger",
            "schema": "1.1",
            "items": anchor_items,
        },
        {
            "kind": "hybrid_engineering_callout_ledger",
            "schema": "1.0",
            "items": callout_ledger,
        },
        {
            "kind": "hybrid_view_axis_boundary_ledger",
            "schema": "1.0",
            "items": boundaries,
            "engineering_coordinate_inferred_from_pixels": False,
        },
        {
            "kind": "hybrid_circle_datum_alignment_ledger",
            "schema": "1.0",
            "items": circle_alignment_records,
            "engineering_authoritative": False,
            "purpose": "visual_symmetry_diagnostic_only",
            "engineering_coordinate_inferred_from_pixels": False,
        },
        {
            "kind": "hybrid_symmetric_dimension_recovery_ledger",
            "schema": "1.0",
            "items": symmetric_chain_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
        },
    ]

    views = [
        ObservationView(
            key=f"view.{item.region_id}",
            kind=item.view_kind,
            evidence=item.evidence,
        )
        for item in context.region_views
    ]

    return PartialReaderObservations(
        overall_dimension_facts=context.overall_dimension_facts,
        views=views,
        entities=entities,
        associations=associations,
        values=[*geometry_values, *callout_values],
        dimensions=dimensions,
        datum_alignments=datum_alignments,
        observations=observations,
        unresolved=unresolved,
    )
