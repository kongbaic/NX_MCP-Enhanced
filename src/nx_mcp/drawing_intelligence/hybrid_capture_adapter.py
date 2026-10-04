from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .circle_datum_alignment import derive_circle_overall_center_alignments
from .dimension_endpoint_candidates import derive_dimension_endpoint_candidates
from .engineering_callout_binding import (
    bind_callout_to_circle_entity,
    bind_callout_to_curve_candidate,
)
from .engineering_callouts import parse_engineering_callout
from .engineering_dimension_binding import bind_callout_to_dimension_candidate
from .engineering_linear_pattern_binding import bind_callout_to_linear_pattern
from .hidden_projection_centers import derive_hidden_projection_center_candidates
from .evidence import Axis, ViewKind
from .reader_observations import (
    ObservationAssociation,
    ObservationCenterlineAlignment,
    ObservationDimension,
    ObservationDimensionEndpoint,
    ObservationDatumAlignment,
    ObservationEntity,
    ObservationPatternSymmetry,
    ObservationUnresolved,
    ObservationValue,
    ObservationView,
)
from .short_dimension_orientation import infer_short_dimension_visual_topology
from .reader_semantic_answers import (
    PartialOverallDimensionFact,
    PartialReaderObservations,
    PartialRotationalSymmetryFact,
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


class HybridConfirmedStartSide(_StrictAdapterModel):
    entity_key: str = Field(min_length=1)
    start_side: Literal["min", "max"]
    evidence: list[str] = Field(min_length=1)


class HybridLabeledDimensionFact(_StrictAdapterModel):
    """OCR-authoritative value plus bounded visual relation semantics."""

    target_id: str = Field(min_length=1)
    source_item_index: int = Field(ge=0)
    source_text: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    value: float = Field(gt=0)
    axis: Axis
    relation: Literal[
        "overall_extent",
        "overall_min_to_profile_transition",
        "overall_max_to_profile_transition",
        "between_profile_boundaries",
    ]
    profile_transition_geometry: Literal[
        "orthogonal",
        "non_orthogonal",
        "mixed",
    ] | None = None
    symmetry_scope: Literal["single", "bilateral"] | None = None
    evidence: list[str] = Field(min_length=1)
    engineering_coordinate_inferred_from_pixels: Literal[False] = False
    pixel_geometry_used_for_topology_only: Literal[True] = True


class HybridAdapterContext(_StrictAdapterModel):
    schema_version: Literal["hybrid-adapter-context-v1"] = Field(
        default="hybrid-adapter-context-v1",
        alias="schema",
    )
    region_views: list[HybridRegionView] = Field(min_length=1)
    overall_dimension_facts: list[PartialOverallDimensionFact] = Field(default_factory=list)
    rotational_symmetry_facts: list[PartialRotationalSymmetryFact] = Field(
        default_factory=list
    )
    confirmed_start_sides: list[HybridConfirmedStartSide] = Field(default_factory=list)
    labeled_dimension_facts: list[HybridLabeledDimensionFact] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _unique_regions(self) -> HybridAdapterContext:
        region_ids = [item.region_id for item in self.region_views]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("hybrid adapter region_ids must be unique")
        if self.confirmed_start_sides:
            raise ValueError(
                "confirmed_start_sides is legacy-only and cannot inject "
                "production start_side truth"
            )
        fact_ids = [item.target_id for item in self.labeled_dimension_facts]
        source_indices = [
            item.source_item_index for item in self.labeled_dimension_facts
        ]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("labeled dimension target_ids must be unique")
        if len(source_indices) != len(set(source_indices)):
            raise ValueError("labeled dimension source_item_index values must be unique")
        region_set = set(region_ids)
        if any(
            item.region_id not in region_set
            for item in self.labeled_dimension_facts
        ):
            raise ValueError("labeled dimension fact references unknown region")
        return self


def _confirmed_start_side_values(
    context: HybridAdapterContext,
    *,
    entity_keys: set[str],
    existing_values: list[ObservationValue],
) -> tuple[list[ObservationValue], list[dict[str, Any]]]:
    existing = {
        (item.entity_key, item.field): item.value
        for item in existing_values
    }
    output: list[ObservationValue] = []
    ledger: list[dict[str, Any]] = []

    for item in context.confirmed_start_sides:
        if item.entity_key not in entity_keys:
            raise HybridCaptureAdapterError(
                f"confirmed start_side entity {item.entity_key!r} is absent"
            )
        key = (item.entity_key, "start_side")
        if key in existing:
            if existing[key] != item.start_side:
                raise HybridCaptureAdapterError(
                    f"confirmed start_side conflicts for {item.entity_key!r}"
                )
            continue

        evidence = list(dict.fromkeys(item.evidence))
        output.append(
            ObservationValue(
                entity_key=item.entity_key,
                field="start_side",
                value=item.start_side,
                semantic="start_side",
                evidence=evidence,
            )
        )
        ledger.append(
            {
                "entity_key": item.entity_key,
                "field": "start_side",
                "value": item.start_side,
                "evidence": evidence,
                "basis": "explicit_human_confirmation",
                "engineering_coordinate_inferred_from_pixels": False,
            }
        )
    return output, ledger


def _missing_transverse_thread_start_side_unresolved(
    *,
    values: list[ObservationValue],
) -> list[ObservationUnresolved]:
    by_entity: dict[str, dict[str, ObservationValue]] = {}
    for item in values:
        by_entity.setdefault(item.entity_key, {})[item.field] = item

    output: list[ObservationUnresolved] = []
    for entity_key, fields in sorted(by_entity.items()):
        axis_item = fields.get("axis")
        spec_item = fields.get("thread_spec")
        depth_item = fields.get("thread_depth")
        side_item = fields.get("start_side")
        material_side_item = fields.get("material_side")
        entry_endpoint_item = fields.get("entry_endpoint")

        axis_text = str(axis_item.value).upper() if axis_item is not None else ""
        depth = depth_item.value if depth_item is not None else None
        legacy_side_ok = (
            side_item is not None and side_item.value in {"min", "max"}
        )
        split_entry_ok = (
            material_side_item is not None
            and material_side_item.value in {"min", "max"}
            and entry_endpoint_item is not None
            and entry_endpoint_item.value in {"min", "max"}
        )
        if (
            axis_text not in {"X", "Y"}
            or spec_item is None
            or not isinstance(spec_item.value, str)
            or not spec_item.value.strip()
            or not isinstance(depth, (int, float))
            or isinstance(depth, bool)
            or float(depth) <= 0
            or legacy_side_ok
            or split_entry_ok
        ):
            continue

        axis: Axis = "X" if axis_text == "X" else "Y"
        evidence = list(
            dict.fromkeys(
                source
                for item in (
                    axis_item,
                    spec_item,
                    depth_item,
                    material_side_item,
                    entry_endpoint_item,
                )
                if item is not None
                for source in item.evidence
            )
        )
        output.append(
            ObservationUnresolved(
                kind="start_side",
                reason=(
                    "Transverse threaded feature has explicit thread depth but no "
                    "complete machining-entry semantics; provide material_side + "
                    "entry_endpoint, or a legacy confirmed start_side, to derive "
                    "its canonical axial range without pixel-to-mm conversion."
                ),
                entity_keys=[entity_key],
                field="start_side",
                axis=axis,
                evidence=evidence,
                required_for_modeling=True,
            )
        )
    return output


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


def _linear_token_number(token: Any) -> float | None:
    if not isinstance(token, str) or not re.fullmatch(r"\d+(?:\.\d+)?", token):
        return None
    value = float(token)
    return value if value > 0 else None


def _conflict_superseded_by_independent_overall(
    *,
    item: dict[str, Any],
    candidate: dict[str, Any],
    axis: Axis,
    boundaries: list[dict[str, Any]],
    overall_dimension_facts: list[PartialOverallDimensionFact],
) -> bool:
    """Return True only when independent engineering truth makes OCR conflict redundant."""

    candidate_id = str(item.get("candidate_id") or "")
    region_id = str(candidate.get("region_id") or "")
    if not candidate_id or not region_id:
        return False

    boundary_matches = [
        boundary
        for boundary in boundaries
        if isinstance(boundary, dict)
        and boundary.get("status") == "resolved"
        and str(boundary.get("region_id") or "") == region_id
        and str(boundary.get("axis") or "") == axis
        and str(boundary.get("candidate_id") or "") == candidate_id
        and boundary.get("engineering_coordinate_inferred_from_pixels") is False
    ]
    if len(boundary_matches) != 1:
        return False

    boundary = boundary_matches[0]
    boundary_value = boundary.get("overall_dimension_value")
    if not isinstance(boundary_value, (int, float)) or isinstance(boundary_value, bool):
        return False

    roles = {
        str(anchor.get("role") or "")
        for anchor in boundary.get("anchors", [])
        if isinstance(anchor, dict)
    }
    if roles != {"overall_min", "overall_max"}:
        return False

    matching_facts = [
        fact
        for fact in overall_dimension_facts
        if fact.axis == axis and math.isclose(fact.value, float(boundary_value), abs_tol=1e-9)
    ]
    if len(matching_facts) != 1:
        return False

    fact = matching_facts[0]
    if not fact.evidence:
        return False
    if any(candidate_id in str(evidence) for evidence in fact.evidence):
        return False

    observed_values = [
        value
        for value in [
            _linear_token_number(item.get("token")),
            *[
                _linear_token_number(token)
                for token in item.get("local_tokens", [])
                if isinstance(token, str)
            ],
        ]
        if value is not None
    ]
    return any(
        math.isclose(value, fact.value, abs_tol=1e-9)
        for value in observed_values
    )


def _witness_source_line_sets(
    candidate: dict[str, Any],
) -> list[set[tuple[str, float, float, float]]]:
    """Return per-witness raw line identities for topology-only matching."""

    result: list[set[tuple[str, float, float, float]]] = []
    for witness in candidate.get("witness_line_evidence", []):
        if not isinstance(witness, dict):
            continue
        signatures: set[tuple[str, float, float, float]] = set()
        for line in witness.get("source_lines", []):
            if not isinstance(line, dict):
                continue
            orientation = str(line.get("orientation") or "")
            axis_px = line.get("axis_px")
            span_px = line.get("span_px")
            if (
                not orientation
                or not isinstance(axis_px, (int, float))
                or isinstance(axis_px, bool)
                or not isinstance(span_px, list)
                or len(span_px) != 2
                or not all(
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    for value in span_px
                )
            ):
                continue
            signatures.add(
                (
                    orientation,
                    round(float(axis_px), 3),
                    round(float(span_px[0]), 3),
                    round(float(span_px[1]), 3),
                )
            )
        if signatures:
            result.append(signatures)
    return result


def _witness_topology_contains(
    candidate: dict[str, Any],
    accepted: dict[str, Any],
) -> bool:
    """Whether candidate contains every accepted witness as the same raw line."""

    accepted_sets = _witness_source_line_sets(accepted)
    candidate_sets = _witness_source_line_sets(candidate)
    if (
        len(accepted_sets) < 2
        or len(candidate_sets) < len(accepted_sets)
    ):
        return False

    def match(index: int, used: set[int]) -> bool:
        if index == len(accepted_sets):
            return True
        for candidate_index, candidate_set in enumerate(candidate_sets):
            if candidate_index in used:
                continue
            if not (accepted_sets[index] & candidate_set):
                continue
            if match(index + 1, {*used, candidate_index}):
                return True
        return False

    return match(0, set())


def _local_only_redundant_with_accepted_dimension(
    *,
    item: dict[str, Any],
    candidate: dict[str, Any],
    candidate_lookup: dict[str, dict[str, Any]],
) -> bool:
    """Suppress duplicate local coverage only when visual witness identity proves it."""

    token_value = _linear_token_number(item.get("token"))
    if token_value is None:
        return False

    region_id = str(candidate.get("region_id") or "")
    orientation = str(candidate.get("orientation") or "")
    if not region_id or not orientation:
        return False

    for accepted in candidate_lookup.values():
        if accepted is candidate:
            continue
        accepted_token = accepted.get("accepted_token")
        if not isinstance(accepted_token, str):
            continue
        try:
            accepted_value, _ = _dimension_value(accepted_token)
        except HybridCaptureAdapterError:
            continue
        if not math.isclose(token_value, accepted_value, abs_tol=1e-9):
            continue
        if str(accepted.get("region_id") or "") != region_id:
            continue
        if str(accepted.get("orientation") or "") != orientation:
            continue
        if _witness_topology_contains(candidate, accepted):
            return True
    return False


def _reference_only_region_ids(
    report: dict[str, Any],
    view_lookup: dict[str, HybridRegionView],
) -> set[str]:
    regions = report.get("regions", [])
    if not isinstance(regions, list):
        return set()
    return {
        region_id
        for region in regions
        if isinstance(region, dict)
        for region_id in [str(region.get("region_id") or "")]
        if region_id and region_id not in view_lookup
    }


def _bbox_reference_only_region_ids(
    report: dict[str, Any],
    view_lookup: dict[str, HybridRegionView],
    bbox: Any,
) -> list[str]:
    center = _bbox_center(bbox)
    if center is None:
        return []

    reference_region_ids = _reference_only_region_ids(report, view_lookup)
    containing_region_ids = sorted(
        str(region.get("region_id") or "")
        for region in report.get("regions", [])
        if (
            isinstance(region, dict)
            and str(region.get("region_id") or "")
            and isinstance(region.get("bbox_px"), list)
            and _point_in_bbox(center, region["bbox_px"])
        )
    )
    if (
        not containing_region_ids
        or any(region_id not in reference_region_ids for region_id in containing_region_ids)
    ):
        return []
    return containing_region_ids


def _coverage_unresolved(
    report: dict[str, Any],
    candidate_lookup: dict[str, dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    *,
    boundaries: list[dict[str, Any]],
    overall_dimension_facts: list[PartialOverallDimensionFact],
    excluded_source_item_indices: set[Any] | None = None,
) -> list[ObservationUnresolved]:
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        raise HybridCaptureAdapterError("Hybrid OCR v2 report requires a coverage ledger")
    if coverage.get("observed_silent_drop_count") != 0:
        raise HybridCaptureAdapterError("Hybrid OCR report has observed silent evidence drops")

    unresolved: list[ObservationUnresolved] = []
    excluded_source_indices = excluded_source_item_indices or set()
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
        superseded = _conflict_superseded_by_independent_overall(
            item=item,
            candidate=candidate,
            axis=axis,
            boundaries=boundaries,
            overall_dimension_facts=overall_dimension_facts,
        )
        reason = (
            "Hybrid whole/local OCR disagreement: "
            f"whole={item.get('token')!r}, "
            f"local={item.get('local_tokens')!r}."
        )
        if superseded:
            reason += (
                " Independent overall-dimension evidence plus resolved overall "
                "boundary identity already closes this engineering axis; the OCR "
                "conflict is preserved as advisory evidence."
            )
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=reason,
                field="dimension_value_candidate",
                axis=axis,
                evidence=_candidate_evidence(candidate_id),
                required_for_modeling=not superseded,
            )
        )

    for item in coverage.get("unconfirmed_proposal_observations", []):
        if not isinstance(item, dict):
            continue
        source_index = item.get("source_item_index")
        if source_index in excluded_source_indices:
            continue
        candidate_id = str(item.get("candidate_id") or "")
        candidate = candidate_lookup.get(candidate_id)
        if candidate is None:
            raise HybridCaptureAdapterError(
                f"unconfirmed proposal references unknown candidate {candidate_id!r}"
            )
        region_id = str(candidate.get("region_id") or "")
        region_view = view_lookup.get(region_id)
        if region_view is None:
            raise HybridCaptureAdapterError(
                f"missing view context for region {region_id!r}"
            )
        axis = _axis_for(
            region_view.view_kind,
            str(candidate.get("orientation") or ""),
        )
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=(
                    "Whole OCR linear observation is the selected global proposal "
                    "for one DG but was not accepted as an engineering dimension: "
                    f"token={item.get('token')!r}, "
                    f"reason={item.get('reason')!r}. The proposal remains "
                    "modeling-blocking until a deterministic consumer or explicit "
                    "non-modeling classification exists."
                ),
                field="unconfirmed_linear_proposal",
                axis=axis,
                evidence=_candidate_evidence(candidate_id),
                required_for_modeling=True,
            )
        )

    for item in coverage.get("secondary_assignment_observations", []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        candidate = candidate_lookup.get(candidate_id)
        if candidate is None:
            raise HybridCaptureAdapterError(
                f"secondary assignment references unknown candidate {candidate_id!r}"
            )
        selected_proposal = item.get("selected_proposal_token")
        no_unique_proposal = selected_proposal is None
        reason = (
            "Whole OCR linear observation was associated with a DG "
            "but was not selected as that DG's global proposal: "
            f"token={item.get('token')!r}, selected={selected_proposal!r}."
        )
        if no_unique_proposal:
            reason += (
                " The DG has no unique selected global proposal, so competing "
                "assigned engineering values remain modeling-blocking."
            )
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=reason,
                field="secondary_linear_assignment",
                evidence=_candidate_evidence(candidate_id),
                required_for_modeling=no_unique_proposal,
            )
        )

    for item in coverage.get("unassigned_linear_observations", []):
        if not isinstance(item, dict):
            continue
        if item.get("source_item_index") in excluded_source_indices:
            continue
        reference_region_ids = _bbox_reference_only_region_ids(
            report,
            view_lookup,
            item.get("bbox"),
        )
        reason = (
            "Whole OCR found a standalone linear token with no unique "
            f"DG assignment: token={item.get('token')!r}."
        )
        if reference_region_ids:
            reason += (
                " The observation is contained only by non-geometric reference "
                f"region(s) {reference_region_ids!r}; preserve it as advisory "
                "reference evidence until deterministic table/header/row semantics "
                "prove a geometry consumer."
            )
        else:
            reason += (
                " The engineering value remains modeling-blocking until a "
                "deterministic consumer or explicit non-modeling classification "
                "exists."
            )
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=reason,
                field="unassigned_linear_text",
                evidence=[f"hybrid:whole:{item.get('source_item_index')}"],
                required_for_modeling=not reference_region_ids,
            )
        )

    reference_only_region_ids = _reference_only_region_ids(report, view_lookup)
    for item in coverage.get("local_only_linear_observations", []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        candidate = candidate_lookup.get(candidate_id)
        if candidate is None:
            raise HybridCaptureAdapterError(
                f"local-only coverage references unknown candidate {candidate_id!r}"
            )
        redundant = _local_only_redundant_with_accepted_dimension(
            item=item,
            candidate=candidate,
            candidate_lookup=candidate_lookup,
        )
        rejected_dimension_role = (
            candidate.get("decision_reason")
            == "candidate_line_is_extension_witness_of_accepted_dimension"
        )
        candidate_region_id = str(candidate.get("region_id") or "")
        reference_only_region = candidate_region_id in reference_only_region_ids
        required = (
            candidate.get("accepted_token") is None
            and candidate_id not in conflicting_candidate_ids
            and not redundant
            and not rejected_dimension_role
            and not reference_only_region
        )
        reason = (
            "Wide local OCR found a linear token without a matching "
            f"whole-drawing assignment: token={item.get('token')!r}."
        )
        if reference_only_region:
            reason += (
                " The parent candidate belongs to a non-geometric reference "
                f"region {candidate_region_id!r}; preserve the token as advisory "
                "reference evidence until deterministic table/header/row semantics "
                "prove a geometry consumer."
            )
        elif redundant:
            reason += (
                " An accepted dimension in the same view/orientation reuses the "
                "same raw witness source-line topology and carries this value; "
                "the local-only observation is preserved as advisory duplicate "
                "coverage."
            )
        elif rejected_dimension_role:
            reason += (
                " The parent candidate was deterministically rejected as an "
                "extension/witness line of another accepted dimension; the "
                "local-only token is preserved as advisory OCR coverage rather "
                "than an independent modeling blocker."
            )
        unresolved.append(
            ObservationUnresolved(
                kind="unsupported_representation",
                reason=reason,
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


def _coverage_bbox_for_source_index(
    report: dict[str, Any],
    source_item_index: int,
) -> object | None:
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        return None

    matches: list[object] = []
    for raw_bucket in coverage.values():
        if not isinstance(raw_bucket, list):
            continue
        for item in raw_bucket:
            if (
                isinstance(item, dict)
                and item.get("source_item_index") == source_item_index
                and isinstance(item.get("bbox"), list)
            ):
                matches.append(item["bbox"])

    if not matches:
        return None
    first = matches[0]
    if any(item != first for item in matches[1:]):
        return None
    return first


def _visual_direction_for_axis(
    view_kind: ViewKind,
    axis: Axis,
) -> Literal["horizontal", "vertical"] | None:
    mapping: dict[
        tuple[ViewKind, Axis],
        Literal["horizontal", "vertical"],
    ] = {
        ("front", "X"): "horizontal",
        ("front", "Z"): "vertical",
        ("side", "Y"): "horizontal",
        ("side", "Z"): "vertical",
        ("top", "X"): "horizontal",
        ("top", "Y"): "vertical",
    }
    return mapping.get((view_kind, axis))


def _reconcile_labeled_dimension_relations(
    *,
    report: dict[str, Any],
    facts: list[HybridLabeledDimensionFact],
    view_lookup: dict[str, HybridRegionView],
    boundaries: list[dict[str, Any]],
) -> list[HybridLabeledDimensionFact]:
    """Tighten local relation semantics only from proven overall contact.

    Pixel positions are identity/topology evidence only. They never become an
    engineering value or coordinate.
    """

    source_raster = report.get("source_raster")
    if not isinstance(source_raster, str) or not source_raster:
        return [item.model_copy(deep=True) for item in facts]

    output: list[HybridLabeledDimensionFact] = []
    for fact in facts:
        copied = fact.model_copy(deep=True)
        if fact.relation == "overall_extent":
            output.append(copied)
            continue

        region_view = view_lookup.get(fact.region_id)
        expected_direction = (
            _visual_direction_for_axis(region_view.view_kind, fact.axis)
            if region_view is not None
            else None
        )
        bbox = _coverage_bbox_for_source_index(report, fact.source_item_index)
        if expected_direction is None or bbox is None:
            output.append(copied)
            continue

        topology = infer_short_dimension_visual_topology(source_raster, bbox)
        if topology is None or topology[0] != expected_direction:
            output.append(copied)
            continue

        anchors: list[tuple[str, float]] = []
        for boundary in boundaries:
            if (
                not isinstance(boundary, dict)
                or boundary.get("status") != "resolved"
                or str(boundary.get("region_id") or "") != fact.region_id
                or str(boundary.get("axis") or "") != fact.axis
            ):
                continue
            for anchor in boundary.get("anchors", []):
                if not isinstance(anchor, dict):
                    continue
                role = str(anchor.get("role") or "")
                position = anchor.get("position_px")
                if (
                    role in {"overall_min", "overall_max"}
                    and isinstance(position, (int, float))
                    and not isinstance(position, bool)
                ):
                    anchors.append((role, float(position)))

        if not anchors:
            output.append(copied)
            continue

        tolerance = _region_profile_match_tolerance(report, fact.region_id)
        pair_contacts: list[str | None] = []
        for pair in topology[1]:
            endpoint_roles: list[str | None] = []
            for position in pair:
                roles = {
                    role
                    for role, anchor_position in anchors
                    if abs(float(position) - anchor_position) <= tolerance
                }
                endpoint_roles.append(
                    next(iter(roles)) if len(roles) == 1 else None
                )
            contacts = [role for role in endpoint_roles if role is not None]
            pair_contacts.append(contacts[0] if len(contacts) == 1 else None)

        if (
            not pair_contacts
            or any(role is None for role in pair_contacts)
            or len(set(pair_contacts)) != 1
        ):
            output.append(copied)
            continue

        overall_role = pair_contacts[0]
        assert overall_role in {"overall_min", "overall_max"}
        reconciled_relation = {
            "overall_min": "overall_min_to_profile_transition",
            "overall_max": "overall_max_to_profile_transition",
        }[overall_role]

        contact_marker = (
            "hybrid:labeled-overall-boundary-contact:"
            f"{fact.region_id}:{fact.axis}:{overall_role}"
        )
        if fact.relation == "between_profile_boundaries":
            copied = copied.model_copy(
                update={
                    "relation": reconciled_relation,
                    "evidence": list(
                        dict.fromkeys(
                            [
                                *fact.evidence,
                                contact_marker,
                            ]
                        )
                    ),
                }
            )
        elif fact.relation in {
            "overall_min_to_profile_transition",
            "overall_max_to_profile_transition",
        }:
            evidence = [
                *fact.evidence,
                contact_marker,
            ]
            if fact.relation != reconciled_relation:
                evidence.append(
                    (
                        "hybrid:labeled-overall-relation-canonicalized:"
                        f"{fact.target_id}:{fact.relation}:{reconciled_relation}"
                    )
                )
            copied = copied.model_copy(
                update={
                    "relation": reconciled_relation,
                    "evidence": list(dict.fromkeys(evidence)),
                }
            )

        output.append(copied)

    return output


def _labeled_profile_transition_boundary_records(
    *,
    report: dict[str, Any],
    facts: list[HybridLabeledDimensionFact],
    view_lookup: dict[str, HybridRegionView],
    boundaries: list[dict[str, Any]],
    profile_inventory: list[dict[str, Any]],
    profile_entity_by_ref: dict[str, str],
    rotational_oblique_profile_hints: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Bind a labeled overall-offset transition to structural profile levels.

    OCR remains authoritative for the engineering offset. Raster geometry is
    used only to identify which already-observed profile boundary shares the
    non-overall witness level. Ambiguous or missing identity stays unbound.
    """

    source_raster = report.get("source_raster")
    if not isinstance(source_raster, str) or not source_raster:
        return []

    output: list[dict[str, Any]] = []
    for fact in facts:
        if fact.relation not in {
            "overall_min_to_profile_transition",
            "overall_max_to_profile_transition",
        }:
            continue

        overall_role = (
            "overall_min"
            if fact.relation == "overall_min_to_profile_transition"
            else "overall_max"
        )
        contact_marker = (
            "hybrid:labeled-overall-boundary-contact:"
            f"{fact.region_id}:{fact.axis}:{overall_role}"
        )
        if contact_marker not in fact.evidence:
            continue

        region_view = view_lookup.get(fact.region_id)
        expected_direction = (
            _visual_direction_for_axis(region_view.view_kind, fact.axis)
            if region_view is not None
            else None
        )
        raw_bbox = _coverage_bbox_for_source_index(
            report,
            fact.source_item_index,
        )
        if region_view is None or expected_direction is None or raw_bbox is None:
            continue

        topology = infer_short_dimension_visual_topology(
            source_raster,
            raw_bbox,
        )
        if topology is None or topology[0] != expected_direction:
            continue

        overall_positions: list[float] = []
        for boundary in boundaries:
            if (
                not isinstance(boundary, dict)
                or boundary.get("status") != "resolved"
                or str(boundary.get("region_id") or "") != fact.region_id
                or str(boundary.get("axis") or "") != fact.axis
            ):
                continue
            for anchor in boundary.get("anchors", []):
                if (
                    isinstance(anchor, dict)
                    and str(anchor.get("role") or "") == overall_role
                    and isinstance(anchor.get("position_px"), (int, float))
                    and not isinstance(anchor.get("position_px"), bool)
                ):
                    overall_positions.append(float(anchor["position_px"]))
        if not overall_positions:
            continue

        tolerance = _region_profile_match_tolerance(
            report,
            fact.region_id,
        )
        transition_positions: list[float] = []
        for pair in topology[1]:
            if len(pair) != 2:
                continue
            flags = [
                any(
                    abs(float(position) - overall_position) <= tolerance
                    for overall_position in overall_positions
                )
                for position in pair
            ]
            if flags.count(True) != 1:
                continue
            transition_positions.append(
                float(pair[1] if flags[0] else pair[0])
            )

        if not transition_positions:
            continue
        if (
            max(transition_positions) - min(transition_positions)
            > tolerance
        ):
            continue
        transition_position = (
            sum(transition_positions) / len(transition_positions)
        )

        expected_profile_orientation = (
            "horizontal"
            if expected_direction == "vertical"
            else "vertical"
        )
        matched_refs: set[str] = set()
        for profile in profile_inventory:
            if (
                not isinstance(profile, dict)
                or profile.get("kind") != "profile_edge_candidate"
                or str(profile.get("source_orientation") or "")
                != expected_profile_orientation
            ):
                continue
            profile_region_id = str(profile.get("region_id") or "")
            profile_view = view_lookup.get(profile_region_id)
            if (
                profile_view is None
                or profile_view.view_kind != region_view.view_kind
            ):
                continue
            ref = str(profile.get("ref") or "")
            position = profile.get("position_px")
            if (
                not ref
                or ref not in profile_entity_by_ref
                or not isinstance(position, (int, float))
                or isinstance(position, bool)
            ):
                continue
            raw_axis_tolerance = profile.get("axis_tolerance_px")
            axis_tolerance = (
                float(raw_axis_tolerance)
                if isinstance(raw_axis_tolerance, (int, float))
                and not isinstance(raw_axis_tolerance, bool)
                else 0.0
            )
            if (
                abs(float(position) - transition_position)
                <= max(tolerance, axis_tolerance)
            ):
                matched_refs.add(ref)

        if matched_refs:
            profile_refs = sorted(matched_refs)
            output.append(
                {
                    "target_id": fact.target_id,
                    "source_item_index": fact.source_item_index,
                    "region_id": fact.region_id,
                    "view_kind": region_view.view_kind,
                    "axis": fact.axis,
                    "overall_role": overall_role,
                    "profile_refs": profile_refs,
                    "profile_entity_keys": [
                        profile_entity_by_ref[ref]
                        for ref in profile_refs
                    ],
                    "selected_transition_position_px": round(
                        transition_position,
                        3,
                    ),
                    "identity_kind": "physical_profile_boundary",
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *fact.evidence,
                                *[
                                    f"hybrid:profile-edge:{ref}"
                                    for ref in profile_refs
                                ],
                            ]
                        )
                    ),
                    "basis": (
                        "labeled_overall_offset_plus_unique_"
                        "transition_level_profile_identity"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_identity_only": True,
                }
            )
            continue

        if (
            fact.symmetry_scope != "bilateral"
            or not isinstance(rotational_oblique_profile_hints, list)
        ):
            continue

        transition_axis_index = 1 if expected_direction == "vertical" else 0
        transverse_axis_index = 1 - transition_axis_index
        oblique_matches: list[dict[str, Any]] = []

        for hint in rotational_oblique_profile_hints:
            if (
                not isinstance(hint, dict)
                or hint.get("view_kind") != region_view.view_kind
                or str(hint.get("rotation_axis") or "").upper() != fact.axis
                or hint.get("one_sided_boundary_candidate") is not True
                or hint.get("exterior_boundary_candidate") is not True
            ):
                continue
            line_support = hint.get("line_edge_support_fraction")
            endpoints = hint.get("endpoints_px")
            if (
                not isinstance(line_support, (int, float))
                or isinstance(line_support, bool)
                or float(line_support) < 0.85
                or not isinstance(endpoints, list)
                or len(endpoints) != 2
                or not all(
                    isinstance(point, list)
                    and len(point) == 2
                    and all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        for value in point
                    )
                    for point in endpoints
                )
            ):
                continue

            matching_indices = [
                index
                for index, point in enumerate(endpoints)
                if abs(
                    float(point[transition_axis_index])
                    - transition_position
                )
                <= tolerance
            ]
            if len(matching_indices) != 1:
                continue

            source_ids = [
                source
                for source in hint.get("source_ids", [])
                if isinstance(source, str)
                and source.startswith("hybrid:oblique-line:")
            ]
            if len(source_ids) != 1:
                continue

            match_index = matching_indices[0]
            other_index = 1 - match_index
            oblique_matches.append(
                {
                    "source_id": source_ids[0],
                    "transition_point": [
                        float(value)
                        for value in endpoints[match_index]
                    ],
                    "other_point": [
                        float(value)
                        for value in endpoints[other_index]
                    ],
                }
            )

        unique_by_source = {
            str(item["source_id"]): item
            for item in oblique_matches
        }
        if len(unique_by_source) != 2:
            continue
        oblique_pair = [
            unique_by_source[source]
            for source in sorted(unique_by_source)
        ]
        first_oblique, second_oblique = oblique_pair
        first_transition = first_oblique["transition_point"]
        second_transition = second_oblique["transition_point"]
        first_other = first_oblique["other_point"]
        second_other = second_oblique["other_point"]

        if (
            abs(
                first_transition[transition_axis_index]
                - second_transition[transition_axis_index]
            )
            > tolerance
            or abs(
                first_other[transition_axis_index]
                - second_other[transition_axis_index]
            )
            > tolerance
        ):
            continue

        first_delta = (
            first_other[transverse_axis_index]
            - first_transition[transverse_axis_index]
        )
        second_delta = (
            second_other[transverse_axis_index]
            - second_transition[transverse_axis_index]
        )
        if (
            first_delta == 0.0
            or second_delta == 0.0
            or first_delta * second_delta >= 0.0
            or abs(abs(first_delta) - abs(second_delta)) > tolerance
        ):
            continue

        oblique_source_ids = sorted(unique_by_source)
        output.append(
            {
                "target_id": fact.target_id,
                "source_item_index": fact.source_item_index,
                "region_id": fact.region_id,
                "view_kind": region_view.view_kind,
                "axis": fact.axis,
                "overall_role": overall_role,
                "profile_refs": [],
                "profile_entity_keys": [],
                "oblique_source_ids": oblique_source_ids,
                "selected_transition_position_px": round(
                    transition_position,
                    3,
                ),
                "identity_kind": (
                    "bilateral_oblique_transition_endpoint_level"
                ),
                "source_ids": list(
                    dict.fromkeys(
                        [
                            *fact.evidence,
                            *oblique_source_ids,
                        ]
                    )
                ),
                "basis": (
                    "labeled_overall_offset_plus_bilateral_"
                    "oblique_endpoint_identity"
                ),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            }
        )

    return output


def _recover_labeled_profile_span_dimensions(
    *,
    report: dict[str, Any],
    facts: list[HybridLabeledDimensionFact],
    view_lookup: dict[str, HybridRegionView],
    profile_inventory: list[dict[str, Any]],
    profile_entity_by_ref: dict[str, str],
    bbox_override_by_target_id: dict[str, object] | None = None,
) -> tuple[list[ObservationDimension], list[dict[str, Any]]]:
    """Bind labeled profile-to-profile dimensions only from unique raster identity.

    OCR supplies the engineering value. Short-dimension witness topology and
    structural profile lines are used only to identify the two physical profile
    boundaries. Pixel distances never become engineering values or coordinates.
    """

    source_raster = report.get("source_raster")
    if not isinstance(source_raster, str) or not source_raster:
        return [], []

    region_boxes: dict[str, tuple[float, float, float, float]] = {}
    for region in report.get("regions", []):
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        bbox = region.get("bbox_px")
        if (
            not region_id
            or not isinstance(bbox, list)
            or len(bbox) != 4
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in bbox
            )
        ):
            continue
        x, y, width, height = (float(value) for value in bbox)
        if width > 0 and height > 0:
            region_boxes[region_id] = (x, y, width, height)

    dimensions: list[ObservationDimension] = []
    ledger: list[dict[str, Any]] = []

    for fact in facts:
        verified_overall_contact = any(
            source.startswith("hybrid:labeled-overall-boundary-contact:")
            for source in fact.evidence
        )
        if (
            fact.relation == "overall_extent"
            or verified_overall_contact
            or fact.relation
            not in {
                "between_profile_boundaries",
                "overall_min_to_profile_transition",
                "overall_max_to_profile_transition",
            }
        ):
            continue

        region_view = view_lookup.get(fact.region_id)
        expected_direction = (
            _visual_direction_for_axis(region_view.view_kind, fact.axis)
            if region_view is not None
            else None
        )
        raw_bbox = (
            (bbox_override_by_target_id or {}).get(fact.target_id)
            or _coverage_bbox_for_source_index(
                report,
                fact.source_item_index,
            )
        )
        bounds = _bbox_bounds(raw_bbox)
        if (
            region_view is None
            or expected_direction is None
            or bounds is None
        ):
            continue

        topology = infer_short_dimension_visual_topology(
            source_raster,
            raw_bbox,
        )
        if topology is None or topology[0] != expected_direction:
            continue

        topology_pairs = list(topology[1])
        if len(topology_pairs) > 1:
            text_axis_coordinate = (
                (bounds[0] + bounds[2]) / 2.0
                if expected_direction == "horizontal"
                else (bounds[1] + bounds[3]) / 2.0
            )
            witness_positions = sorted(
                {
                    float(position)
                    for pair in topology_pairs
                    for position in pair
                }
            )
            adjacent_brackets = [
                (first, second)
                for first, second in zip(
                    witness_positions,
                    witness_positions[1:],
                    strict=False,
                )
                if first < text_axis_coordinate < second
            ]
            if len(adjacent_brackets) != 1:
                continue
            topology_pairs = adjacent_brackets

        expected_profile_orientation = (
            "vertical"
            if expected_direction == "horizontal"
            else "horizontal"
        )
        left, top, right, bottom = bounds
        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0

        eligible_regions: list[str] = []
        if fact.region_id in region_boxes:
            eligible_regions.append(fact.region_id)

        for region_id, (rx, ry, rw, rh) in region_boxes.items():
            candidate_view = view_lookup.get(region_id)
            if (
                region_id in eligible_regions
                or candidate_view is None
                or candidate_view.view_kind != region_view.view_kind
                or not (
                    rx <= center_x <= rx + rw
                    and ry <= center_y <= ry + rh
                )
            ):
                continue
            eligible_regions.append(region_id)

        if not eligible_regions:
            continue

        candidate_records: list[dict[str, Any]] = []
        base_tolerance = _region_profile_match_tolerance(
            report,
            fact.region_id,
        )
        for first_position, second_position in topology_pairs:
            for candidate_region in sorted(eligible_regions):
                region_edges = [
                    item
                    for item in profile_inventory
                    if (
                        isinstance(item, dict)
                        and item.get("kind") == "profile_edge_candidate"
                        and str(item.get("region_id") or "") == candidate_region
                        and str(item.get("source_orientation") or "")
                        == expected_profile_orientation
                        and str(item.get("ref") or "") in profile_entity_by_ref
                        and isinstance(item.get("position_px"), (int, float))
                        and not isinstance(item.get("position_px"), bool)
                    )
                ]

                endpoint_matches: list[list[dict[str, Any]]] = []
                for witness_position in (first_position, second_position):
                    matches: list[dict[str, Any]] = []
                    for edge in region_edges:
                        edge_position = float(edge["position_px"])
                        edge_tolerance = edge.get("axis_tolerance_px")
                        tolerance = max(
                            base_tolerance,
                            float(edge_tolerance)
                            if (
                                isinstance(edge_tolerance, (int, float))
                                and not isinstance(edge_tolerance, bool)
                            )
                            else 0.0,
                        )
                        if abs(edge_position - float(witness_position)) > tolerance:
                            continue

                        span = edge.get("span_px")
                        if not (
                            isinstance(span, list)
                            and len(span) == 2
                            and all(
                                isinstance(value, (int, float))
                                and not isinstance(value, bool)
                                for value in span
                            )
                        ):
                            continue

                        # The OCR text box may sit outside the part, as is normal
                        # for engineering dimensions. Endpoint identity comes
                        # from the short-dimension witness-axis positions, not
                        # from spatial overlap between the text box and the
                        # physical profile segment.
                        matches.append(edge)

                    endpoint_matches.append(matches)

                if (
                    len(endpoint_matches) != 2
                    or len(endpoint_matches[0]) != 1
                    or len(endpoint_matches[1]) != 1
                ):
                    continue
                first_edge = endpoint_matches[0][0]
                second_edge = endpoint_matches[1][0]
                first_ref = str(first_edge.get("ref") or "")
                second_ref = str(second_edge.get("ref") or "")
                if not first_ref or not second_ref or first_ref == second_ref:
                    continue

                candidate_records.append(
                    {
                        "selected_region_id": candidate_region,
                        "profile_refs": [first_ref, second_ref],
                        "profile_entity_keys": [
                            profile_entity_by_ref[first_ref],
                            profile_entity_by_ref[second_ref],
                        ],
                        "selected_witness_positions_px": [
                            float(first_position),
                            float(second_position),
                        ],
                    }
                )

        unique: dict[tuple[str, str, str], dict[str, Any]] = {}
        for record in candidate_records:
            key = (
                str(record["selected_region_id"]),
                str(record["profile_refs"][0]),
                str(record["profile_refs"][1]),
            )
            unique.setdefault(key, record)
        if len(unique) != 1:
            continue

        selected = next(iter(unique.values()))
        evidence = list(
            dict.fromkeys(
                [
                    *fact.evidence,
                    f"hybrid:labeled-profile-span:{fact.target_id}",
                    *[
                        f"hybrid:profile-edge:{ref}"
                        for ref in selected["profile_refs"]
                    ],
                ]
            )
        )
        dimension_key = (
            f"{fact.region_id}.LABELED_PROFILE_SPAN_{fact.target_id}"
        )
        endpoint_entities = [
            str(value)
            for value in selected["profile_entity_keys"]
        ]
        dimensions.append(
            ObservationDimension(
                key=dimension_key,
                value=fact.value,
                axis=fact.axis,
                endpoints=[
                    ObservationDimensionEndpoint(
                        role="profile_boundary",
                        entity_key=endpoint_entities[0],
                        basis="profile_edge",
                        evidence=evidence,
                    ),
                    ObservationDimensionEndpoint(
                        role="profile_boundary",
                        entity_key=endpoint_entities[1],
                        basis="profile_edge",
                        evidence=evidence,
                    ),
                ],
                direction=_dimension_direction_from_image_order(
                    region_view.view_kind,
                    expected_direction,
                ),
                evidence=evidence,
                required_for_modeling=True,
            )
        )
        ledger.append(
            {
                "dimension_key": dimension_key,
                "target_id": fact.target_id,
                "source_item_index": fact.source_item_index,
                "source_text": fact.source_text,
                "region_id": fact.region_id,
                "selected_region_id": selected["selected_region_id"],
                "axis": fact.axis,
                "value": fact.value,
                "source_relation": fact.relation,
                "profile_refs": list(selected["profile_refs"]),
                "profile_entity_keys": endpoint_entities,
                "selected_witness_positions_px": list(
                    selected["selected_witness_positions_px"]
                ),
                "basis": (
                    "unique_short_dimension_witness_pair_to_two_"
                    "structural_profile_boundaries"
                ),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            }
        )

    return dimensions, ledger


def _recover_reference_table_profile_span_dimensions(
    *,
    report: dict[str, Any],
    corroborating_facts: list[HybridLabeledDimensionFact],
    view_lookup: dict[str, HybridRegionView],
    profile_inventory: list[dict[str, Any]],
    profile_entity_by_ref: dict[str, str],
) -> tuple[list[ObservationDimension], list[dict[str, Any]]]:
    """Recover a broken local dimension from a corroborated reference table row.

    A reference row is trusted only after at least three independent labeled
    dimensions in the drawing match the same header/value row. The table may
    then supply an engineering value for a label whose local OCR is visibly
    fragmented, but only when the remaining local numeric glyphs are compatible
    with that table value and short-dimension witness topology uniquely binds
    two physical profile boundaries. Raster geometry is identity-only.
    """

    whole_items = report.get("whole_drawing_items")
    if not isinstance(whole_items, list):
        return [], []

    reference_region_ids = _reference_only_region_ids(report, view_lookup)
    if not reference_region_ids:
        return [], []

    region_boxes = {
        region_id: _region_bbox(report, region_id)
        for region_id in {
            *reference_region_ids,
            *view_lookup.keys(),
        }
    }

    def item_rect(index: int) -> tuple[float, float, float, float] | None:
        if not 0 <= index < len(whole_items):
            return None
        item = whole_items[index]
        if not isinstance(item, dict):
            return None
        bounds = _bbox_bounds(item.get("bbox"))
        if bounds is None:
            return None
        left, top, right, bottom = bounds
        if right <= left or bottom <= top:
            return None
        return left, top, right - left, bottom - top

    def center(rect: tuple[float, float, float, float]) -> tuple[float, float]:
        x, y, width, height = rect
        return x + width / 2.0, y + height / 2.0

    def inside(
        point: tuple[float, float],
        rect: tuple[float, float, float, float],
    ) -> bool:
        px, py = point
        x, y, width, height = rect
        return x <= px <= x + width and y <= py <= y + height

    def row_clusters(
        items: list[tuple[int, str, tuple[float, float, float, float]]],
    ) -> list[list[tuple[int, str, tuple[float, float, float, float]]]]:
        clusters: list[list[tuple[int, str, tuple[float, float, float, float]]]] = []
        for item in sorted(items, key=lambda value: (center(value[2])[1], center(value[2])[0])):
            item_y = center(item[2])[1]
            selected = next(
                (
                    cluster
                    for cluster in clusters
                    if abs(
                        item_y
                        - sum(center(value[2])[1] for value in cluster)
                        / len(cluster)
                    )
                    <= 10.0
                ),
                None,
            )
            if selected is None:
                clusters.append([item])
            else:
                selected.append(item)
        return clusters

    header_re = re.compile(r"(?i)^\s*(?P<label>[a-z][a-z0-9]*)\s*$")
    numeric_re = re.compile(r"^\s*(?P<value>\d+(?:[.,]\d+)?)\s*$")
    unit_re = re.compile(r"(?i)^\s*mm[a-z]?\s*$")
    fact_label_re = re.compile(r"(?i)^\s*(?P<label>[a-z][a-z0-9]*)\b")

    table_rows: list[dict[str, Any]] = []
    for reference_region_id in sorted(reference_region_ids):
        reference_rect = region_boxes.get(reference_region_id)
        if reference_rect is None:
            continue

        headers: list[tuple[int, str, tuple[float, float, float, float]]] = []
        numeric_values: list[
            tuple[int, str, tuple[float, float, float, float]]
        ] = []
        for index, raw_item in enumerate(whole_items):
            if not isinstance(raw_item, dict):
                continue
            text = raw_item.get("text")
            rect = item_rect(index)
            if not isinstance(text, str) or rect is None or not inside(
                center(rect),
                reference_rect,
            ):
                continue
            header_match = header_re.fullmatch(text)
            if header_match is not None:
                headers.append((index, header_match.group("label").upper(), rect))
                continue
            numeric_match = numeric_re.fullmatch(text)
            if numeric_match is not None:
                numeric_values.append((index, numeric_match.group("value"), rect))

        header_clusters = row_clusters(headers)
        value_clusters = row_clusters(numeric_values)
        if not header_clusters or not value_clusters:
            continue
        header_row = max(header_clusters, key=len)
        header_y = sum(center(value[2])[1] for value in header_row) / len(header_row)
        value_candidates = [
            cluster
            for cluster in value_clusters
            if (
                len(cluster) >= 4
                and sum(center(value[2])[1] for value in cluster) / len(cluster)
                > header_y
            )
        ]
        if len(header_row) < 4 or not value_candidates:
            continue
        value_row = max(value_candidates, key=len)

        sorted_headers = sorted(header_row, key=lambda value: center(value[2])[0])
        paired: dict[str, dict[str, Any]] = {}
        used_value_indices: set[int] = set()
        reference_width = reference_rect[2]
        column_tolerance = max(
            24.0,
            min(80.0, reference_width / max(1, len(sorted_headers)) * 0.60),
        )
        for header_index, label, header_rect in sorted_headers:
            header_x = center(header_rect)[0]
            matches: list[
                tuple[float, int, str, tuple[float, float, float, float]]
            ] = []
            for value_index, value_text, value_rect in value_row:
                if value_index in used_value_indices:
                    continue
                distance = abs(center(value_rect)[0] - header_x)
                if distance <= column_tolerance:
                    matches.append(
                        (distance, value_index, value_text, value_rect)
                    )
            matches.sort(key=lambda value: (value[0], value[1]))
            if len(matches) != 1:
                continue
            _distance, value_index, value_text, value_rect = matches[0]
            parsed = _linear_token_number(value_text.replace(",", "."))
            if parsed is None:
                continue
            used_value_indices.add(value_index)
            paired[label] = {
                "label": label,
                "value": parsed,
                "header_source_item_index": header_index,
                "value_source_item_index": value_index,
                "header_bbox": header_rect,
                "value_bbox": value_rect,
            }

        if len(paired) >= 4:
            table_rows.append(
                {
                    "reference_region_id": reference_region_id,
                    "paired": paired,
                }
            )

    if not table_rows:
        return [], []

    corroborated_rows: list[dict[str, Any]] = []
    for row in table_rows:
        paired = row["paired"]
        matched_labels: list[str] = []
        for fact in corroborating_facts:
            match = fact_label_re.match(fact.source_text)
            if match is None:
                continue
            label = match.group("label").upper()
            table_fact = paired.get(label)
            if table_fact is None:
                continue
            if math.isclose(
                float(table_fact["value"]),
                float(fact.value),
                abs_tol=max(abs(float(fact.value)) * 1e-6, 1e-9),
            ):
                matched_labels.append(label)
        matched_labels = sorted(set(matched_labels))
        if len(matched_labels) >= 3:
            corroborated_rows.append(
                {
                    **row,
                    "corroborating_labels": matched_labels,
                }
            )

    if len(corroborated_rows) != 1:
        return [], []
    row = corroborated_rows[0]
    paired = row["paired"]

    reference_rects = [
        rect
        for region_id, rect in region_boxes.items()
        if region_id in reference_region_ids and rect is not None
    ]

    def is_reference_item(rect: tuple[float, float, float, float]) -> bool:
        point = center(rect)
        return any(inside(point, reference_rect) for reference_rect in reference_rects)

    def vertical_overlap_fraction(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> float:
        _x1, y1, _w1, h1 = first
        _x2, y2, _w2, h2 = second
        overlap = min(y1 + h1, y2 + h2) - max(y1, y2)
        if overlap <= 0.0:
            return 0.0
        return overlap / max(1.0, min(h1, h2))

    drawing_labels: list[
        tuple[int, str, tuple[float, float, float, float]]
    ] = []
    drawing_units: list[tuple[int, tuple[float, float, float, float]]] = []
    drawing_numbers: list[
        tuple[int, str, tuple[float, float, float, float]]
    ] = []
    for index, raw_item in enumerate(whole_items):
        if not isinstance(raw_item, dict):
            continue
        text = raw_item.get("text")
        rect = item_rect(index)
        if not isinstance(text, str) or rect is None or is_reference_item(rect):
            continue
        if unit_re.fullmatch(text) is not None:
            drawing_units.append((index, rect))
            continue
        header_match = header_re.fullmatch(text)
        if header_match is not None:
            drawing_labels.append(
                (index, header_match.group("label").upper(), rect)
            )
            continue
        if numeric_re.fullmatch(text) is not None:
            drawing_numbers.append((index, text.strip(), rect))

    recovered_dimensions: list[ObservationDimension] = []
    recovered_ledger: list[dict[str, Any]] = []
    claimed_numeric_sources: set[int] = set()

    for label_index, label, label_rect in drawing_labels:
        table_fact = paired.get(label)
        if table_fact is None:
            continue

        candidate_triplets: list[
            tuple[
                int,
                str,
                tuple[float, float, float, float],
                int,
                tuple[float, float, float, float],
            ]
        ] = []
        label_right = label_rect[0] + label_rect[2]
        for unit_index, unit_rect in drawing_units:
            unit_left = unit_rect[0]
            if (
                unit_left < label_right
                or unit_left - label_right > 180.0
                or vertical_overlap_fraction(label_rect, unit_rect) < 0.55
            ):
                continue
            for number_index, number_text, number_rect in drawing_numbers:
                number_center_x = center(number_rect)[0]
                if not (
                    label_right <= number_center_x <= unit_left
                    and vertical_overlap_fraction(label_rect, number_rect) >= 0.55
                    and vertical_overlap_fraction(number_rect, unit_rect) >= 0.55
                ):
                    continue
                candidate_triplets.append(
                    (
                        number_index,
                        number_text,
                        number_rect,
                        unit_index,
                        unit_rect,
                    )
                )

        if len(candidate_triplets) != 1:
            continue
        number_index, number_text, number_rect, unit_index, unit_rect = (
            candidate_triplets[0]
        )
        if number_index in claimed_numeric_sources:
            continue

        table_value = float(table_fact["value"])
        table_digits = re.sub(
            r"\D",
            "",
            str(table_value).rstrip("0").rstrip("."),
        )
        local_digits = re.sub(r"\D", "", number_text)
        if (
            not table_digits
            or not local_digits
            or local_digits not in table_digits
        ):
            continue

        left = min(label_rect[0], number_rect[0], unit_rect[0])
        top = min(label_rect[1], number_rect[1], unit_rect[1])
        right = max(
            label_rect[0] + label_rect[2],
            number_rect[0] + number_rect[2],
            unit_rect[0] + unit_rect[2],
        )
        bottom = max(
            label_rect[1] + label_rect[3],
            number_rect[1] + number_rect[3],
            unit_rect[1] + unit_rect[3],
        )
        combined_bbox = [
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
        ]
        combined_center = ((left + right) / 2.0, (top + bottom) / 2.0)

        region_candidates: list[
            tuple[float, str, HybridRegionView]
        ] = []
        for region_id, region_view in view_lookup.items():
            region_rect = region_boxes.get(region_id)
            if region_rect is None or not inside(combined_center, region_rect):
                continue
            region_candidates.append(
                (region_rect[2] * region_rect[3], region_id, region_view)
            )
        region_candidates.sort(key=lambda value: (value[0], value[1]))
        if not region_candidates:
            continue
        if (
            len(region_candidates) > 1
            and region_candidates[0][0] >= region_candidates[1][0] * 0.95
        ):
            continue
        _area, region_id, region_view = region_candidates[0]

        topology = infer_short_dimension_visual_topology(
            str(report.get("source_raster") or ""),
            combined_bbox,
        )
        if topology is None:
            continue
        visual_direction = topology[0]
        candidate_axes: tuple[Axis, ...] = ("X", "Y", "Z")
        matching_axes: list[Axis] = [
            axis
            for axis in candidate_axes
            if _visual_direction_for_axis(
                region_view.view_kind,
                axis,
            )
            == visual_direction
        ]
        if len(matching_axes) != 1:
            continue
        axis = matching_axes[0]

        target_id = f"REF_TABLE_LD_{number_index:04d}"
        evidence = [
            f"hybrid:whole:{label_index}",
            f"hybrid:whole:{number_index}",
            f"hybrid:whole:{unit_index}",
            (
                "hybrid:reference-table-header:"
                f"{table_fact['header_source_item_index']}"
            ),
            (
                "hybrid:reference-table-value:"
                f"{table_fact['value_source_item_index']}"
            ),
            (
                "hybrid:reference-table-row-corroborated:"
                f"{row['reference_region_id']}"
            ),
        ]
        provisional_fact = HybridLabeledDimensionFact(
            target_id=target_id,
            source_item_index=number_index,
            source_text=f"{label} - {table_value:g} mm",
            region_id=region_id,
            value=table_value,
            axis=axis,
            relation="between_profile_boundaries",
            evidence=evidence,
        )
        dimensions, identity_ledger = _recover_labeled_profile_span_dimensions(
            report=report,
            facts=[provisional_fact],
            view_lookup=view_lookup,
            profile_inventory=profile_inventory,
            profile_entity_by_ref=profile_entity_by_ref,
            bbox_override_by_target_id={target_id: combined_bbox},
        )
        if len(dimensions) != 1 or len(identity_ledger) != 1:
            continue

        recovered_dimensions.extend(dimensions)
        recovered_ledger.append(
            {
                **identity_ledger[0],
                "reference_region_id": row["reference_region_id"],
                "reference_header_source_item_index": (
                    table_fact["header_source_item_index"]
                ),
                "reference_value_source_item_index": (
                    table_fact["value_source_item_index"]
                ),
                "drawing_label_source_item_index": label_index,
                "drawing_numeric_source_item_index": number_index,
                "drawing_unit_source_item_index": unit_index,
                "local_numeric_fragment": number_text,
                "corroborating_labels": list(row["corroborating_labels"]),
                "engineering_value_source": "corroborated_reference_table_row",
                "basis": (
                    "corroborated_reference_table_value_plus_unique_"
                    "short_dimension_profile_identity"
                ),
            }
        )
        claimed_numeric_sources.add(number_index)

    return recovered_dimensions, recovered_ledger


def _reconcile_labeled_profile_span_relations(
    *,
    facts: list[HybridLabeledDimensionFact],
    identity_ledger: list[dict[str, Any]],
) -> list[HybridLabeledDimensionFact]:
    """Prefer deterministic two-profile identity over an unverified overall claim."""

    recovered = {
        str(item.get("target_id") or "")
        for item in identity_ledger
        if isinstance(item, dict)
        and item.get("basis")
        == "unique_short_dimension_witness_pair_to_two_structural_profile_boundaries"
    }

    output: list[HybridLabeledDimensionFact] = []
    for fact in facts:
        if (
            fact.target_id in recovered
            and fact.relation
            in {
                "overall_min_to_profile_transition",
                "overall_max_to_profile_transition",
            }
            and not any(
                source.startswith("hybrid:labeled-overall-boundary-contact:")
                for source in fact.evidence
            )
        ):
            output.append(
                fact.model_copy(
                    update={
                        "relation": "between_profile_boundaries",
                        "evidence": list(
                            dict.fromkeys(
                                [
                                    *fact.evidence,
                                    (
                                        "hybrid:labeled-profile-span-relation:"
                                        f"{fact.target_id}"
                                    ),
                                ]
                            )
                        ),
                    }
                )
            )
            continue
        output.append(fact.model_copy(deep=True))
    return output


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


_PROFILE_PLANE_BY_VIEW_KIND: dict[str, str] = {
    "front": "XZ",
    "side": "YZ",
    "top": "XY",
}


def _orthogonal_boundary_axis_direction(
    *,
    orientation: str,
    side_index: Any,
) -> Literal["negative", "positive"] | None:
    """Normalize raster side polarity into engineering-axis direction only.

    Structural orthogonal source lines are canonicalized left-to-right for
    horizontal lines and top-to-bottom for vertical lines. With the raster
    sampler's (-normal, +normal) side ordering, side 0 therefore points toward
    the positive engineering axis and side 1 toward the negative axis. This is
    a topology/direction label only; it does not infer an engineering coordinate
    or metric from pixels.
    """

    if (
        orientation not in {"horizontal", "vertical"}
        or side_index not in {0, 1}
        or isinstance(side_index, bool)
    ):
        return None
    return "positive" if int(side_index) == 0 else "negative"


def _profile_line_segment_px(
    item: dict[str, Any],
) -> tuple[str, float, float, float] | None:
    orientation = str(item.get("source_orientation") or "")
    position = item.get("position_px")
    span = item.get("span_px")
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
    start, end = sorted(float(value) for value in span)
    if end <= start:
        return None
    return orientation, float(position), start, end


def _profile_lines_touch(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    tolerance: float,
) -> bool:
    first = _profile_line_segment_px(left)
    second = _profile_line_segment_px(right)
    if first is None or second is None or first[0] == second[0]:
        return False

    if first[0] == "vertical":
        vertical = first
        horizontal = second
    else:
        vertical = second
        horizontal = first

    _, vx, vy0, vy1 = vertical
    _, hy, hx0, hx1 = horizontal
    return (
        hx0 - tolerance <= vx <= hx1 + tolerance
        and vy0 - tolerance <= hy <= vy1 + tolerance
    )




def _point_to_axis_profile_segment_distance(
    point: tuple[float, float],
    item: dict[str, Any],
) -> float | None:
    segment = _profile_line_segment_px(item)
    if segment is None:
        return None
    orientation, position, start, end = segment
    x, y = point
    if orientation == "vertical":
        nearest_y = min(max(y, start), end)
        return math.hypot(x - position, y - nearest_y)
    nearest_x = min(max(x, start), end)
    return math.hypot(x - nearest_x, y - position)


def _rotational_oblique_profile_hints(
    *,
    report: dict[str, Any],
    profile_inventory: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    context: HybridAdapterContext,
    profile_entity_by_ref: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Record only strictly corroborated oblique rotational-profile evidence.

    Raw oblique Hough segments remain candidate-only.  A segment is promoted
    into this topology ledger only when one proven rotational view contains
    the segment midpoint and each segment endpoint uniquely contacts a
    different independently supported structural profile edge.  Pixel geometry
    establishes topology/identity only and never becomes an engineering value.
    """

    line_candidates = report.get("annotation_line_candidates")
    curve_candidates = report.get("annotation_curve_candidates")
    raw_candidates: list[tuple[str, int, dict[str, Any]]] = []
    if isinstance(line_candidates, list):
        raw_candidates.extend(
            ("hybrid:oblique-line", index, candidate)
            for index, candidate in enumerate(line_candidates)
            if isinstance(candidate, dict)
        )
    if isinstance(curve_candidates, list):
        raw_candidates.extend(
            ("hybrid:curve-boundary", index, candidate)
            for index, candidate in enumerate(curve_candidates)
            if isinstance(candidate, dict)
        )
    if not raw_candidates:
        return []

    hints: list[dict[str, Any]] = []
    for region_id, region_view in sorted(view_lookup.items()):
        plane = _PROFILE_PLANE_BY_VIEW_KIND.get(region_view.view_kind)
        if plane is None:
            continue
        region_evidence = set(region_view.evidence)
        rotation_axes = {
            fact.axis
            for fact in context.rotational_symmetry_facts
            if fact.axis in set(plane)
            and region_evidence.intersection(fact.evidence)
        }
        if len(rotation_axes) != 1:
            continue
        rotation_axis = next(iter(rotation_axes))

        bbox = _region_bbox(report, region_id)
        if bbox is None:
            continue
        bx, by, bw, bh = bbox

        supports = [
            item
            for item in profile_inventory
            if (
                isinstance(item, dict)
                and item.get("kind") == "profile_edge_candidate"
                and str(item.get("region_id") or "") == region_id
                and _profile_line_segment_px(item) is not None
                and isinstance(
                    item.get("non_dimension_crossing_source_count"),
                    int,
                )
                and not isinstance(
                    item.get("non_dimension_crossing_source_count"),
                    bool,
                )
                and int(item.get("non_dimension_crossing_source_count", 0)) > 0
                and isinstance(item.get("axis_ink_run_fraction"), (int, float))
                and not isinstance(item.get("axis_ink_run_fraction"), bool)
                and float(item.get("axis_ink_run_fraction", 0.0)) >= 0.25
                and str(item.get("ref") or "")
            )
        ]
        strict_contact_tolerance = _region_profile_match_tolerance(
            report,
            region_id,
        )
        tolerance = max(
            5.0,
            strict_contact_tolerance * 2.0,
        )

        for source_prefix, candidate_index, candidate in raw_candidates:
            candidate_kind = str(candidate.get("kind") or "")
            if (
                candidate.get("candidate_only") is not True
                or candidate_kind not in {
                    "oblique_line_candidate",
                    "curved_boundary_candidate",
                }
            ):
                continue
            endpoints = candidate.get("endpoints_px")
            if (
                not isinstance(endpoints, list)
                or len(endpoints) != 2
                or not all(
                    isinstance(point, list)
                    and len(point) == 2
                    and all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        for value in point
                    )
                    for point in endpoints
                )
            ):
                continue

            angle_value: float | None = None
            verified_curve_support = False
            if candidate_kind == "oblique_line_candidate":
                angle = candidate.get("angle_deg")
                if (
                    not isinstance(angle, (int, float))
                    or isinstance(angle, bool)
                ):
                    continue
                angle_value = float(angle)
                if not 10.0 <= angle_value <= 80.0:
                    continue
            else:
                residual = candidate.get("curve_fit_residual_fraction")
                turn_consistency = candidate.get(
                    "turn_consistency_fraction"
                )
                turn_cv = candidate.get("turn_magnitude_cv")
                sweep = candidate.get("sweep_deg_px")
                verified_curve_support = (
                    candidate.get("curve_classification_basis")
                    == "stable_cocircular_exterior_contour_turning"
                    and isinstance(residual, (int, float))
                    and not isinstance(residual, bool)
                    and float(residual) <= 0.025
                    and isinstance(turn_consistency, (int, float))
                    and not isinstance(turn_consistency, bool)
                    and float(turn_consistency) >= 0.90
                    and isinstance(turn_cv, (int, float))
                    and not isinstance(turn_cv, bool)
                    and float(turn_cv) <= 0.25
                    and isinstance(sweep, (int, float))
                    and not isinstance(sweep, bool)
                    and 20.0 <= float(sweep) <= 200.0
                )
                if not verified_curve_support:
                    continue

            if candidate.get("exterior_boundary_candidate") is not True:
                continue

            first = (float(endpoints[0][0]), float(endpoints[0][1]))
            second = (float(endpoints[1][0]), float(endpoints[1][1]))
            midpoint = (
                (first[0] + second[0]) / 2.0,
                (first[1] + second[1]) / 2.0,
            )
            if not (
                bx <= midpoint[0] <= bx + bw
                and by <= midpoint[1] <= by + bh
            ):
                continue

            endpoint_matches: list[list[str]] = []
            for point in (first, second):
                matches = sorted(
                    str(item.get("ref") or "")
                    for item in supports
                    if (
                        (
                            distance := _point_to_axis_profile_segment_distance(
                                point,
                                item,
                            )
                        )
                        is not None
                        and distance <= tolerance
                    )
                )
                endpoint_matches.append(list(dict.fromkeys(matches)))

            direct_contact = (
                len(endpoint_matches[0]) == 1
                and len(endpoint_matches[1]) == 1
                and endpoint_matches[0][0] != endpoint_matches[1][0]
            )
            support_refs: list[str]
            basis: str
            primitive_kind = "unresolved"
            primitive_kind_basis = (
                "fragment_without_verified_full_straight_support"
            )
            line_support = candidate.get("line_edge_support_fraction")
            continuous_straight_support = (
                candidate_kind == "oblique_line_candidate"
                and isinstance(line_support, (int, float))
                and not isinstance(line_support, bool)
                and float(line_support) >= 0.85
            )

            if direct_contact:
                support_refs = [
                    endpoint_matches[0][0],
                    endpoint_matches[1][0],
                ]
                basis = (
                    "established_rotational_symmetry_plus_"
                    "unique_independent_structural_contacts"
                )
                if continuous_straight_support:
                    primitive_kind = "line"
                    primitive_kind_basis = (
                        "verified_continuous_straight_raster_segment_"
                        "between_structural_contacts"
                    )
                elif (
                    candidate_kind == "curved_boundary_candidate"
                    and verified_curve_support
                ):
                    primitive_kind = "arc"
                    primitive_kind_basis = (
                        "verified_continuous_curved_raster_segment_"
                        "between_structural_contacts"
                    )
                else:
                    primitive_kind_basis = (
                        "two_structural_contacts_without_verified_"
                        "primitive_support"
                    )
            elif (
                candidate_kind == "oblique_line_candidate"
                and candidate.get("one_sided_boundary_candidate") is True
            ):
                strict_endpoint_matches: list[list[str]] = []
                for point in (first, second):
                    matches = sorted(
                        str(item.get("ref") or "")
                        for item in supports
                        if (
                            (
                                distance := _point_to_axis_profile_segment_distance(
                                    point,
                                    item,
                                )
                            )
                            is not None
                            and distance
                            <= max(
                                strict_contact_tolerance,
                                (
                                    float(item["axis_tolerance_px"])
                                    if (
                                        isinstance(
                                            item.get("axis_tolerance_px"),
                                            (int, float),
                                        )
                                        and not isinstance(
                                            item.get("axis_tolerance_px"),
                                            bool,
                                        )
                                    )
                                    else 0.0
                                ),
                            )
                        )
                    )
                    strict_endpoint_matches.append(
                        list(dict.fromkeys(matches))
                    )

                match_sizes = sorted(
                    len(matches)
                    for matches in strict_endpoint_matches
                )
                if match_sizes == [0, 1]:
                    support_refs = (
                        strict_endpoint_matches[0]
                        or strict_endpoint_matches[1]
                    )
                    basis = (
                        "established_rotational_symmetry_plus_"
                        "one_sided_boundary_plus_unique_structural_contact"
                    )
                elif match_sizes == [0, 0]:
                    support_refs = []
                    basis = (
                        "established_rotational_symmetry_plus_"
                        "exterior_one_sided_boundary_without_verified_"
                        "structural_contact"
                    )
                else:
                    continue
            else:
                continue

            support_entity_keys = [
                profile_entity_by_ref[ref]
                for ref in support_refs
                if (
                    profile_entity_by_ref is not None
                    and ref in profile_entity_by_ref
                )
            ]
            if (
                profile_entity_by_ref is not None
                and len(support_entity_keys) != len(support_refs)
            ):
                continue

            support_by_ref = {
                str(item.get("ref") or ""): item
                for item in supports
            }
            support_constant_axes: list[str] = []
            support_axes_valid = True
            for ref in support_refs:
                support = support_by_ref.get(ref)
                if support is None:
                    support_axes_valid = False
                    break
                orientation = str(support.get("source_orientation") or "")
                pixel_index = 0 if orientation == "vertical" else 1
                constant_axes = [
                    axis
                    for axis in plane
                    if _PIXEL_INDEX_BY_VIEW_AXIS.get(
                        (region_view.view_kind, axis)
                    )
                    == pixel_index
                ]
                if len(constant_axes) != 1:
                    support_axes_valid = False
                    break
                support_constant_axes.append(constant_axes[0])
            if not support_axes_valid:
                continue

            digest = hashlib.sha256(
                "|".join(
                    [
                        region_id,
                        source_prefix,
                        str(candidate_index),
                        *support_refs,
                        f"{first[0]:.3f},{first[1]:.3f}",
                        f"{second[0]:.3f},{second[1]:.3f}",
                    ]
                ).encode("utf-8")
            ).hexdigest()[:12].upper()
            hints.append(
                {
                    "id": f"OBLIQUE_PROFILE_{digest}",
                    "region_id": region_id,
                    "view_kind": region_view.view_kind,
                    "plane": plane,
                    "rotation_axis": rotation_axis,
                    "supporting_profile_refs": support_refs,
                    "supporting_profile_entity_keys": support_entity_keys,
                    "supporting_profile_constant_axes": support_constant_axes,
                    "support_status": (
                        "verified" if support_refs else "unresolved"
                    ),
                    "primitive_kind": primitive_kind,
                    "primitive_kind_basis": primitive_kind_basis,
                    **(
                        {
                            "line_edge_support_fraction": round(
                                float(line_support),
                                3,
                            )
                        }
                        if (
                            isinstance(line_support, (int, float))
                            and not isinstance(line_support, bool)
                        )
                        else {}
                    ),
                    **(
                        {
                            "curve_fit_residual_fraction": round(
                                float(candidate["curve_fit_residual_fraction"]),
                                4,
                            ),
                            "turn_consistency_fraction": round(
                                float(candidate["turn_consistency_fraction"]),
                                4,
                            ),
                            "turn_magnitude_cv": round(
                                float(candidate["turn_magnitude_cv"]),
                                4,
                            ),
                            "sweep_deg_px": round(
                                float(candidate["sweep_deg_px"]),
                                3,
                            ),
                        }
                        if (
                            candidate_kind == "curved_boundary_candidate"
                            and verified_curve_support
                        )
                        else {}
                    ),
                    "endpoints_px": [
                        [round(first[0], 3), round(first[1], 3)],
                        [round(second[0], 3), round(second[1], 3)],
                    ],
                    **(
                        {"angle_deg": round(angle_value, 3)}
                        if angle_value is not None
                        else {}
                    ),
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *region_view.evidence,
                                f"{source_prefix}:{candidate_index}",
                                *[
                                    f"hybrid:profile-edge:{ref}"
                                    for ref in support_refs
                                ],
                            ]
                        )
                    ),
                    "one_sided_boundary_candidate": (
                        candidate.get("one_sided_boundary_candidate") is True
                    ),
                    **(
                        {
                            "material_side_index": int(
                                candidate["boundary_evidence"]["material_side_index"]
                            ),
                            "background_side_index": int(
                                candidate["boundary_evidence"]["background_side_index"]
                            ),
                        }
                        if (
                            isinstance(candidate.get("boundary_evidence"), dict)
                            and candidate["boundary_evidence"].get(
                                "material_side_index"
                            )
                            in {0, 1}
                            and candidate["boundary_evidence"].get(
                                "background_side_index"
                            )
                            in {0, 1}
                            and candidate["boundary_evidence"].get(
                                "material_side_index"
                            )
                            != candidate["boundary_evidence"].get(
                                "background_side_index"
                            )
                        )
                        else {}
                    ),
                    "exterior_boundary_candidate": True,
                    "basis": basis,
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                }
            )

    hints.sort(
        key=lambda item: (
            str(item.get("region_id") or ""),
            str(item.get("id") or ""),
        )
    )
    return hints


def _rotational_profile_topology_hints(
    *,
    report: dict[str, Any],
    profile_inventory: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    context: HybridAdapterContext,
    profile_entity_by_ref: dict[str, str],
    excluded_profile_refs: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Record structural profile connectivity in views with proven rotation.

    This is an evidence-only topology ledger. Raster geometry is used only to
    prove orthogonal edge connectivity. It never converts pixel positions or
    spans into engineering coordinates, radii, diameters, or axial distances.
    """

    excluded_profile_refs = excluded_profile_refs or set()
    hints: list[dict[str, Any]] = []
    for region_id, region_view in sorted(view_lookup.items()):
        plane = _PROFILE_PLANE_BY_VIEW_KIND.get(region_view.view_kind)
        if plane is None:
            continue

        region_evidence = set(region_view.evidence)
        rotation_axes = {
            fact.axis
            for fact in context.rotational_symmetry_facts
            if fact.axis in set(plane)
            and region_evidence.intersection(fact.evidence)
        }
        if len(rotation_axes) != 1:
            continue
        rotation_axis = next(iter(rotation_axes))

        edges: dict[str, dict[str, Any]] = {}
        for item in profile_inventory:
            if (
                not isinstance(item, dict)
                or item.get("kind") != "profile_edge_candidate"
                or str(item.get("region_id") or "") != region_id
            ):
                continue
            ref = str(item.get("ref") or "")
            if (
                not ref
                or ref not in profile_entity_by_ref
                or ref in excluded_profile_refs
            ):
                continue
            if _profile_line_segment_px(item) is None:
                continue
            ink_run = item.get("axis_ink_run_fraction")
            if (
                not isinstance(ink_run, (int, float))
                or isinstance(ink_run, bool)
                or float(ink_run) < 0.25
            ):
                continue
            edges[ref] = item

        if len(edges) < 2:
            continue

        tolerance = max(
            5.0,
            _region_profile_match_tolerance(report, region_id) * 2.0,
        )
        adjacency: dict[str, set[str]] = {ref: set() for ref in edges}
        refs = sorted(edges)
        for index, left_ref in enumerate(refs):
            for right_ref in refs[index + 1 :]:
                if _profile_lines_touch(
                    edges[left_ref],
                    edges[right_ref],
                    tolerance=tolerance,
                ):
                    adjacency[left_ref].add(right_ref)
                    adjacency[right_ref].add(left_ref)

        visited: set[str] = set()
        components: list[list[str]] = []
        for seed in refs:
            if seed in visited or not adjacency[seed]:
                continue
            stack = [seed]
            component: list[str] = []
            while stack:
                ref = stack.pop()
                if ref in visited:
                    continue
                visited.add(ref)
                component.append(ref)
                stack.extend(sorted(adjacency[ref] - visited, reverse=True))
            if len(component) >= 2:
                components.append(sorted(component))

        components.sort(key=lambda item: tuple(item))
        for component_index, component in enumerate(components):
            component_set = set(component)
            junctions = [
                [left_ref, right_ref]
                for left_ref in component
                for right_ref in sorted(adjacency[left_ref])
                if right_ref in component_set and left_ref < right_ref
            ]
            if not junctions:
                continue

            edge_records: list[dict[str, Any]] = []
            for ref in component:
                item = edges[ref]
                orientation = str(item.get("source_orientation") or "")
                pixel_index = 0 if orientation == "vertical" else 1
                constant_axes = [
                    axis
                    for axis in plane
                    if _PIXEL_INDEX_BY_VIEW_AXIS.get(
                        (region_view.view_kind, axis)
                    )
                    == pixel_index
                ]
                if len(constant_axes) != 1:
                    edge_records = []
                    break
                edge_record: dict[str, Any] = {
                    "ref": ref,
                    "profile_entity_key": profile_entity_by_ref[ref],
                    "source_orientation": orientation,
                    "constant_axis": constant_axes[0],
                }
                if item.get("one_sided_boundary_candidate") is True:
                    material_side_index = item.get("material_side_index")
                    background_side_index = item.get("background_side_index")
                    if (
                        material_side_index in {0, 1}
                        and background_side_index in {0, 1}
                        and material_side_index != background_side_index
                    ):
                        edge_record["one_sided_boundary_candidate"] = True
                        edge_record["material_side_index"] = int(
                            material_side_index
                        )
                        edge_record["background_side_index"] = int(
                            background_side_index
                        )
                        material_axis_direction = (
                            _orthogonal_boundary_axis_direction(
                                orientation=orientation,
                                side_index=material_side_index,
                            )
                        )
                        background_axis_direction = (
                            _orthogonal_boundary_axis_direction(
                                orientation=orientation,
                                side_index=background_side_index,
                            )
                        )
                        if (
                            material_axis_direction is not None
                            and background_axis_direction is not None
                            and material_axis_direction
                            != background_axis_direction
                        ):
                            edge_record["material_axis_direction"] = (
                                material_axis_direction
                            )
                            edge_record["background_axis_direction"] = (
                                background_axis_direction
                            )
                elif item.get("material_side_ambiguous") is True:
                    edge_record["material_side_ambiguous"] = True
                edge_records.append(edge_record)
            if not edge_records:
                continue

            fact_evidence = [
                evidence
                for fact in context.rotational_symmetry_facts
                if fact.axis == rotation_axis
                and region_evidence.intersection(fact.evidence)
                for evidence in fact.evidence
            ]
            hints.append(
                {
                    "region_id": region_id,
                    "view_kind": region_view.view_kind,
                    "plane": plane,
                    "rotation_axis": rotation_axis,
                    "component_index": component_index,
                    "edges": edge_records,
                    "junctions": junctions,
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *region_view.evidence,
                                *fact_evidence,
                                *[
                                    f"hybrid:profile-edge:{ref}"
                                    for ref in component
                                ],
                            ]
                        )
                    ),
                    "basis": (
                        "established_rotational_symmetry_plus_"
                        "structural_profile_connectivity"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                }
            )

    return hints


def _metric_profile_topology_hints(
    *,
    report: dict[str, Any],
    profile_inventory: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    boundaries: list[dict[str, Any]],
    profile_entity_by_ref: dict[str, str],
) -> list[dict[str, Any]]:
    """Classify a unique orthogonal L profile from geometry topology only.

    Overall-boundary ownership is engineering evidence. Pixel spans are used
    only to prove which outer side is continuous and which two internal profile
    edges form the unique L-corner. No pixel distance becomes an engineering
    coordinate.
    """

    boundary_refs: dict[tuple[str, str, str], str] = {}
    conflicted: set[tuple[str, str, str]] = set()
    for boundary in boundaries:
        if (
            not isinstance(boundary, dict)
            or boundary.get("status") != "resolved"
        ):
            continue
        region_id = str(boundary.get("region_id") or "")
        axis = str(boundary.get("axis") or "")
        if not region_id or axis not in {"X", "Y", "Z"}:
            continue
        for item in boundary.get("anchors", []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            ref = str(item.get("ref") or "")
            if role not in {"overall_min", "overall_max"} or not ref:
                continue
            key = (region_id, axis, role)
            previous = boundary_refs.get(key)
            if previous is not None and previous != ref:
                conflicted.add(key)
            else:
                boundary_refs[key] = ref
    for key in conflicted:
        boundary_refs.pop(key, None)

    by_ref = {
        str(item.get("ref") or ""): item
        for item in profile_inventory
        if isinstance(item, dict)
        and item.get("kind") == "profile_edge_candidate"
        and str(item.get("ref") or "")
    }

    def position(item: dict[str, Any]) -> float | None:
        segment = _profile_line_segment_px(item)
        return segment[1] if segment is not None else None

    def covers(
        item: dict[str, Any],
        coordinate: float,
        *,
        tolerance: float,
    ) -> bool:
        segment = _profile_line_segment_px(item)
        return (
            segment is not None
            and segment[2] - tolerance <= coordinate <= segment[3] + tolerance
        )

    hints: list[dict[str, Any]] = []
    for region_id, region_view in sorted(view_lookup.items()):
        plane = _PROFILE_PLANE_BY_VIEW_KIND.get(region_view.view_kind)
        if plane is None:
            continue
        axis_u, axis_v = plane[0], plane[1]
        required = {
            "u_min": boundary_refs.get((region_id, axis_u, "overall_min")),
            "u_max": boundary_refs.get((region_id, axis_u, "overall_max")),
            "v_min": boundary_refs.get((region_id, axis_v, "overall_min")),
            "v_max": boundary_refs.get((region_id, axis_v, "overall_max")),
        }
        if any(ref is None or ref not in by_ref for ref in required.values()):
            continue

        u_pixel_index = _PIXEL_INDEX_BY_VIEW_AXIS.get(
            (region_view.view_kind, axis_u)
        )
        v_pixel_index = _PIXEL_INDEX_BY_VIEW_AXIS.get(
            (region_view.view_kind, axis_v)
        )
        if {u_pixel_index, v_pixel_index} != {0, 1}:
            continue
        u_orientation = "vertical" if u_pixel_index == 0 else "horizontal"
        v_orientation = "vertical" if v_pixel_index == 0 else "horizontal"

        outer_refs = {str(ref) for ref in required.values()}
        internal_u = [
            item
            for item in profile_inventory
            if isinstance(item, dict)
            and str(item.get("region_id") or "") == region_id
            and item.get("kind") == "profile_edge_candidate"
            and str(item.get("source_orientation") or "") == u_orientation
            and str(item.get("ref") or "") not in outer_refs
            and str(item.get("ref") or "") in profile_entity_by_ref
        ]
        internal_v = [
            item
            for item in profile_inventory
            if isinstance(item, dict)
            and str(item.get("region_id") or "") == region_id
            and item.get("kind") == "profile_edge_candidate"
            and str(item.get("source_orientation") or "") == v_orientation
            and str(item.get("ref") or "") not in outer_refs
            and str(item.get("ref") or "") in profile_entity_by_ref
        ]

        # Topology needs a slightly wider junction tolerance than endpoint
        # ownership matching because structural line extraction may fragment
        # physical corners by a few pixels.
        tolerance = max(
            5.0,
            _region_profile_match_tolerance(report, region_id) * 2.0,
        )

        u_min_pos = position(by_ref[str(required["u_min"])])
        u_max_pos = position(by_ref[str(required["u_max"])])
        v_min_pos = position(by_ref[str(required["v_min"])])
        v_max_pos = position(by_ref[str(required["v_max"])])
        if None in {u_min_pos, u_max_pos, v_min_pos, v_max_pos}:
            continue

        upright_candidates = [
            role
            for role, ref in (
                ("min", str(required["u_min"])),
                ("max", str(required["u_max"])),
            )
            if covers(by_ref[ref], float(v_min_pos), tolerance=tolerance)
            and covers(by_ref[ref], float(v_max_pos), tolerance=tolerance)
        ]
        base_candidates = [
            role
            for role, ref in (
                ("min", str(required["v_min"])),
                ("max", str(required["v_max"])),
            )
            if covers(by_ref[ref], float(u_min_pos), tolerance=tolerance)
            and covers(by_ref[ref], float(u_max_pos), tolerance=tolerance)
        ]
        if len(upright_candidates) != 1 or len(base_candidates) != 1:
            continue

        upright_side = upright_candidates[0]
        base_side = base_candidates[0]

        opposite_base_coordinate = (
            float(v_max_pos) if base_side == "min" else float(v_min_pos)
        )
        opposite_upright_coordinate = (
            float(u_max_pos) if upright_side == "min" else float(u_min_pos)
        )

        corner_pairs = [
            (u_item, v_item)
            for u_item in internal_u
            if covers(
                u_item,
                opposite_base_coordinate,
                tolerance=tolerance,
            )
            for v_item in internal_v
            if covers(
                v_item,
                opposite_upright_coordinate,
                tolerance=tolerance,
            )
            and _profile_lines_touch(
                u_item,
                v_item,
                tolerance=tolerance,
            )
        ]
        if len(corner_pairs) != 1:
            continue

        u_item, v_item = corner_pairs[0]
        u_ref = str(u_item.get("ref") or "")
        v_ref = str(v_item.get("ref") or "")
        hints.append(
            {
                "region_id": region_id,
                "plane": plane,
                "topology": "L",
                "upright_side": upright_side,
                "base_side": base_side,
                "internal_u_ref": u_ref,
                "internal_v_ref": v_ref,
                "internal_u_entity_key": profile_entity_by_ref[u_ref],
                "internal_v_entity_key": profile_entity_by_ref[v_ref],
                "outer_refs": dict(required),
                "basis": (
                    "unique_internal_corner_with_full_span_outer_"
                    "u_and_v_boundaries"
                ),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        )

    return hints


def _profile_boundary_entities(
    profile_inventory: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
) -> tuple[list[ObservationEntity], dict[str, str]]:
    entities: list[ObservationEntity] = []
    by_ref: dict[str, str] = {}
    seen_keys: set[str] = set()

    for item in profile_inventory:
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


def _profile_vertex_entities(
    candidates: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
) -> tuple[list[ObservationEntity], dict[str, str]]:
    """Materialize evidence-backed profile vertices as distinct local entities."""

    entities: list[ObservationEntity] = []
    by_ref: dict[str, str] = {}
    for candidate in candidates:
        region_id = str(candidate.get("region_id") or "")
        if not region_id or region_id not in view_lookup:
            continue
        for witness in candidate.get("witness_anchor_evidence", []):
            if not isinstance(witness, dict):
                continue
            for anchor in witness.get("nearest_anchors", []):
                if (
                    not isinstance(anchor, dict)
                    or anchor.get("kind") != "profile_vertex_candidate"
                ):
                    continue
                ref = str(anchor.get("ref") or "")
                if not ref or ref in by_ref:
                    continue
                supporting_ref = str(
                    anchor.get("supporting_profile_ref") or ""
                )
                entity_key = f"{region_id}.PROFILE_VERTEX.{ref}"
                evidence = [f"hybrid:profile-vertex:{ref}"]
                if supporting_ref:
                    evidence.append(
                        f"hybrid:profile-edge:{supporting_ref}"
                    )
                by_ref[ref] = entity_key
                entities.append(
                    ObservationEntity(
                        key=entity_key,
                        view_key=f"view.{region_id}",
                        shape="profile",
                        cross_view_disposition="single_view",
                        evidence=evidence,
                        required_for_modeling=False,
                    )
                )

    return entities, by_ref


_SYMMETRIC_COUNT_TWO_MARKER = "hybrid:symmetric-count2-overall-center"


def _symmetric_count_two_pattern_owner(
    candidate: dict[str, Any],
    *,
    region_view: HybridRegionView,
    axis: Axis,
    boundaries: list[dict[str, Any]],
    callout_ledger: list[dict[str, Any]],
    entity_keys: set[str],
) -> dict[str, Any] | None:
    """Identify a count-two feature whose measured centers are visually symmetric.

    Pixel coordinates are used only to prove topology/identity and symmetry.
    Engineering coordinates remain derived from the accepted dimension values
    and overall dimensions downstream.
    """

    accepted_token = candidate.get("accepted_token")
    if not isinstance(accepted_token, str):
        return None
    try:
        spacing_value, _ = _dimension_value(accepted_token)
    except HybridCaptureAdapterError:
        return None

    endpoint_evidence = derive_dimension_endpoint_candidates(candidate)
    raw_endpoints = endpoint_evidence.get("endpoints")
    witness_positions = endpoint_evidence.get("selected_witness_positions_px")
    if not (
        isinstance(raw_endpoints, list)
        and len(raw_endpoints) == 2
        and all(
            isinstance(item, dict)
            and item.get("status") == "no_physical_candidate"
            for item in raw_endpoints
        )
        and isinstance(witness_positions, list)
        and len(witness_positions) == 2
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in witness_positions
        )
    ):
        return None

    region_id = str(candidate.get("region_id") or "")
    boundary_matches = [
        item
        for item in boundaries
        if isinstance(item, dict)
        and item.get("status") == "resolved"
        and str(item.get("region_id") or "") == region_id
        and str(item.get("axis") or "") == axis
        and item.get("engineering_coordinate_inferred_from_pixels") is False
    ]
    if len(boundary_matches) != 1:
        return None

    boundary = boundary_matches[0]
    overall_value = boundary.get("overall_dimension_value")
    anchors = [
        item
        for item in boundary.get("anchors", [])
        if isinstance(item, dict)
        and item.get("role") in {"overall_min", "overall_max"}
        and isinstance(item.get("position_px"), (int, float))
        and not isinstance(item.get("position_px"), bool)
    ]
    if (
        not isinstance(overall_value, (int, float))
        or isinstance(overall_value, bool)
        or float(overall_value) <= 0
        or spacing_value > float(overall_value) + 1e-9
        or {str(item.get("role") or "") for item in anchors}
        != {"overall_min", "overall_max"}
        or len(anchors) != 2
    ):
        return None

    boundary_positions = sorted(float(item["position_px"]) for item in anchors)
    witness_values = [float(value) for value in witness_positions]
    if not all(
        boundary_positions[0] <= value <= boundary_positions[1]
        for value in witness_values
    ):
        return None

    boundary_span = boundary_positions[1] - boundary_positions[0]
    if boundary_span <= 0:
        return None
    boundary_midpoint = sum(boundary_positions) / 2.0
    witness_midpoint = sum(witness_values) / 2.0
    midpoint_residual = abs(witness_midpoint - boundary_midpoint)
    midpoint_tolerance = max(2.0, boundary_span * 0.015)
    if midpoint_residual > midpoint_tolerance:
        return None

    witness_line_axes: dict[int, set[Axis]] = {}
    for record in candidate.get("witness_line_evidence", []):
        if not isinstance(record, dict):
            continue
        witness_index = record.get("witness_index")
        if not isinstance(witness_index, int):
            continue
        axes: set[Axis] = set()
        for line in record.get("source_lines", []):
            if not isinstance(line, dict):
                continue
            orientation = str(line.get("orientation") or "")
            try:
                axes.add(_axis_for(region_view.view_kind, orientation))
            except HybridCaptureAdapterError:
                continue
        witness_line_axes[witness_index] = axes

    selected_indices = endpoint_evidence.get("selected_witness_indices")
    if not (
        isinstance(selected_indices, list)
        and len(selected_indices) == 2
        and all(isinstance(index, int) for index in selected_indices)
    ):
        return None

    def witness_projection_span(
        witness_index: int,
        owner_axis: Axis,
    ) -> tuple[float, float] | None:
        records = [
            item
            for item in candidate.get("witness_line_evidence", [])
            if isinstance(item, dict)
            and item.get("witness_index") == witness_index
        ]
        if len(records) != 1:
            return None

        spans: list[tuple[float, float]] = []
        for line in records[0].get("source_lines", []):
            if (
                not isinstance(line, dict)
                or line.get("crosses_dimension_axis") is True
            ):
                continue
            orientation = str(line.get("orientation") or "")
            try:
                line_axis = _axis_for(region_view.view_kind, orientation)
            except HybridCaptureAdapterError:
                continue
            if line_axis != owner_axis:
                continue
            raw_span = line.get("span_px")
            if (
                isinstance(raw_span, list)
                and len(raw_span) == 2
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    for value in raw_span
                )
            ):
                spans.append(
                    (
                        float(raw_span[0]),
                        float(raw_span[1]),
                    )
                )

        if not spans:
            return None
        return (
            min(min(span) for span in spans),
            max(max(span) for span in spans),
        )

    def overlap_ratio(
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> float:
        first_min, first_max = sorted(first)
        second_min, second_max = sorted(second)
        overlap = max(
            0.0,
            min(first_max, second_max) - max(first_min, second_min),
        )
        shorter = min(first_max - first_min, second_max - second_min)
        return overlap / shorter if shorter > 1e-9 else 0.0

    owner_records: dict[str, dict[str, Any]] = {}
    projection_support_by_entity: dict[str, dict[str, Any]] = {}
    for record in callout_ledger:
        if not isinstance(record, dict):
            continue
        binding = record.get("binding")
        facts = record.get("facts")
        if not isinstance(binding, dict) or not isinstance(facts, dict):
            continue
        count = facts.get("count")
        owner_axis = str(binding.get("axis") or "")
        entity_key = str(binding.get("entity_key") or "")
        if (
            binding.get("status") != "pattern_backed"
            or isinstance(count, bool)
            or not isinstance(count, (int, float))
            or float(count) != 2.0
            or owner_axis not in {"X", "Y", "Z"}
            or owner_axis == axis
            or entity_key not in entity_keys
        ):
            continue
        if not all(
            owner_axis in witness_line_axes.get(index, set())
            for index in selected_indices
        ):
            continue

        raw_pattern_span = binding.get("pattern_span_px")
        if not (
            isinstance(raw_pattern_span, list)
            and len(raw_pattern_span) == 2
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                for value in raw_pattern_span
            )
        ):
            continue
        pattern_span = (
            float(raw_pattern_span[0]),
            float(raw_pattern_span[1]),
        )
        witness_spans = [
            witness_projection_span(index, owner_axis)
            for index in selected_indices
        ]
        if any(span is None for span in witness_spans):
            continue
        typed_witness_spans = [
            span for span in witness_spans if span is not None
        ]
        overlap_ratios = [
            overlap_ratio(span, pattern_span)
            for span in typed_witness_spans
        ]
        if not all(ratio >= 0.80 for ratio in overlap_ratios):
            continue

        owner_records[entity_key] = record
        projection_support_by_entity[entity_key] = {
            "pattern_span_px": [
                round(pattern_span[0], 3),
                round(pattern_span[1], 3),
            ],
            "witness_projection_spans_px": [
                [round(span[0], 3), round(span[1], 3)]
                for span in typed_witness_spans
            ],
            "overlap_ratios": [
                round(ratio, 6) for ratio in overlap_ratios
            ],
        }

    if len(owner_records) != 1:
        return None

    entity_key, owner_record = next(iter(owner_records.items()))
    binding = owner_record["binding"]
    projection_support = projection_support_by_entity[entity_key]
    return {
        "entity_key": entity_key,
        "feature_axis": binding["axis"],
        "dimension_axis": axis,
        "spacing_dimension_value": spacing_value,
        "overall_dimension_value": float(overall_value),
        "selected_witness_positions_px": witness_values,
        "overall_boundary_positions_px": boundary_positions,
        "midpoint_residual_px": round(midpoint_residual, 3),
        "midpoint_tolerance_px": round(midpoint_tolerance, 3),
        "projection_support": projection_support,
        "basis": (
            "unique_count_two_pattern_plus_overall_center_symmetry"
            "_plus_orthographic_span_overlap"
        ),
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
        "marker": _SYMMETRIC_COUNT_TWO_MARKER,
    }


def _full_extent_roles_disagree_with_declared_overall(
    endpoints: list[ObservationDimensionEndpoint],
    *,
    axis: Axis,
    value: float,
    overall_dimensions: dict[str, float],
) -> bool:
    roles = {item.role for item in endpoints}
    if roles != {"overall_min", "overall_max"}:
        return False
    overall_key = {
        "X": "length_x",
        "Y": "width_y",
        "Z": "height_z",
    }[axis]
    declared = overall_dimensions.get(overall_key)
    if (
        not isinstance(declared, (int, float))
        or isinstance(declared, bool)
    ):
        return False
    return not math.isclose(
        value,
        float(declared),
        abs_tol=max(abs(value) * 1e-6, 1e-9),
    )


def _reconcile_centered_symmetric_dimension_endpoint_roles(
    candidate: dict[str, Any],
    *,
    endpoints: list[ObservationDimensionEndpoint],
    unresolved_reason: str | None,
    symmetric_dimension_pair: dict[str, Any] | None,
    entity_keys: set[str],
    profile_entity_by_ref: dict[str, str],
    profile_vertex_entity_by_ref: dict[str, str] | None,
    pattern_entity_by_ref: dict[str, str] | None,
    evidence: list[str],
) -> tuple[list[ObservationDimensionEndpoint], str | None]:
    """Reject global-boundary roles that contradict a proven centered span.

    A validated centered pair has a dimension strictly smaller than the overall
    extent and both selected witnesses inside the independently observed overall
    witness pair.  Therefore neither selected endpoint can simultaneously be an
    overall_min/overall_max endpoint.  Re-run physical endpoint ownership
    without region-local boundary-role promotion; if physical ownership cannot
    be represented deterministically, the ordinary unresolved path remains.
    """

    if symmetric_dimension_pair is None or not any(
        item.role in {"overall_min", "overall_max"} for item in endpoints
    ):
        return endpoints, unresolved_reason

    return _dimension_endpoints_from_candidates(
        candidate,
        entity_keys=entity_keys,
        boundary_roles={},
        profile_entity_by_ref=profile_entity_by_ref,
        profile_vertex_entity_by_ref=profile_vertex_entity_by_ref,
        pattern_entity_by_ref=pattern_entity_by_ref,
        evidence=evidence,
    )


def _dimension_endpoints_from_candidates(
    candidate: dict[str, Any],
    *,
    entity_keys: set[str],
    boundary_roles: dict[str, Literal["overall_min", "overall_max"]],
    profile_entity_by_ref: dict[str, str],
    profile_vertex_entity_by_ref: dict[str, str] | None = None,
    pattern_entity_by_ref: dict[str, str] | None = None,
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

        exact_profile_identity = (
            raw_endpoint.get("ownership_narrowing_basis")
            == "exact_crossing_witness_profile_line_identity"
        )
        owned_pattern_entities = sorted(
            {
                pattern_entity_by_ref[ref]
                for anchor in raw_endpoint.get("ignored_nonownership_anchors", [])
                if isinstance(anchor, dict)
                and anchor.get("kind") == "linear_pattern_axis"
                for ref in [str(anchor.get("ref") or "")]
                if pattern_entity_by_ref is not None
                and ref in pattern_entity_by_ref
                and pattern_entity_by_ref[ref] in entity_keys
            }
        )
        if len(owned_pattern_entities) == 1 and not exact_profile_identity:
            output.append(
                ObservationDimensionEndpoint(
                    role="entity_center",
                    entity_key=owned_pattern_entities[0],
                    basis="centerline",
                    evidence=evidence,
                )
            )
            continue

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

            if physical.get("kind") == "profile_vertex_candidate":
                ref = str(physical.get("ref") or "")
                vertex_entity_key = (
                    (profile_vertex_entity_by_ref or {}).get(ref)
                )
                if (
                    vertex_entity_key is not None
                    and vertex_entity_key in entity_keys
                ):
                    output.append(
                        ObservationDimensionEndpoint(
                            role="profile_boundary",
                            entity_key=vertex_entity_key,
                            basis="profile_edge",
                            evidence=evidence,
                        )
                    )
                    continue

        representable_candidate_keys: list[str] = []
        candidate_set_blocked = False
        for physical_candidate in physical_candidates:
            if not isinstance(physical_candidate, dict):
                candidate_set_blocked = True
                break

            center_candidate = _center_entity_candidate(
                physical_candidate,
                entity_keys,
            )
            if center_candidate is not None:
                representable_candidate_keys.append(center_candidate[0])
                continue

            if physical_candidate.get("kind") == "profile_edge_candidate":
                ref = str(physical_candidate.get("ref") or "")
                if ref in boundary_roles:
                    # An overall boundary is a real engineering alternative,
                    # but Human Confirmation must not choose overall roles from
                    # this candidate channel. Do not expose a partial option set.
                    candidate_set_blocked = True
                    break

                span_local_norm = physical_candidate.get("span_local_norm")
                junction_count = physical_candidate.get("junction_count")
                endpoint_junction_count = physical_candidate.get(
                    "endpoint_junction_count"
                )
                structurally_qualified = (
                    isinstance(span_local_norm, (int, float))
                    and not isinstance(span_local_norm, bool)
                    and isinstance(junction_count, int)
                    and not isinstance(junction_count, bool)
                    and isinstance(endpoint_junction_count, int)
                    and not isinstance(endpoint_junction_count, bool)
                    and (
                        (
                            float(span_local_norm) >= 0.15
                            and junction_count >= 2
                        )
                        or (
                            float(span_local_norm) >= 0.25
                            and junction_count >= 1
                            and endpoint_junction_count >= 1
                        )
                    )
                )
                if not structurally_qualified:
                    # A candidate-only visual profile without independent
                    # structural topology is not a human-selectable physical
                    # owner. Ignore it rather than letting it suppress a
                    # stronger center candidate.
                    continue

                profile_entity_key = profile_entity_by_ref.get(ref)
                if (
                    profile_entity_key is not None
                    and profile_entity_key in entity_keys
                ):
                    representable_candidate_keys.append(profile_entity_key)
                    continue

            if physical_candidate.get("kind") == "profile_vertex_candidate":
                ref = str(physical_candidate.get("ref") or "")
                vertex_entity_key = (
                    (profile_vertex_entity_by_ref or {}).get(ref)
                )
                if (
                    vertex_entity_key is not None
                    and vertex_entity_key in entity_keys
                ):
                    representable_candidate_keys.append(vertex_entity_key)
                    continue

            candidate_set_blocked = True
            break

        candidate_entity_keys = (
            []
            if candidate_set_blocked
            else sorted(set(representable_candidate_keys))
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
        bound_left, bound_top, bound_right, bound_bottom = bounds
        records.append(
            {
                "source_item_index": source_item_index,
                "bounds": bounds,
                "width": max(1.0, bound_right - bound_left),
                "height": max(1.0, bound_bottom - bound_top),
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


def _dimension_backed_through_projection_support(
    binding: dict[str, Any],
    *,
    report: dict[str, Any],
    profile_inventory: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Prove a projected cylindrical feature crosses its local material span.

    Pixel geometry is used only for topology: a dashed diameter rail must sit
    on one diameter witness and cross the unique pair of physical profile
    boundaries that enclose material at that rail height.  No pixel distance
    becomes an engineering coordinate or depth.
    """

    if binding.get("status") != "dimension_backed":
        return None
    region_id = str(binding.get("region_id") or "")
    orientation = str(binding.get("orientation") or "")
    witnesses = binding.get("witness_positions_px")
    if (
        not region_id
        or orientation not in {"horizontal", "vertical"}
        or not isinstance(witnesses, list)
        or len(witnesses) != 2
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in witnesses
        )
    ):
        return None

    rail_orientation = (
        "horizontal" if orientation == "vertical" else "vertical"
    )
    boundary_orientation = (
        "vertical" if rail_orientation == "horizontal" else "horizontal"
    )
    region = next(
        (
            item
            for item in report.get("regions", [])
            if isinstance(item, dict)
            and str(item.get("region_id") or "") == region_id
        ),
        None,
    )
    if not isinstance(region, dict):
        return None

    tolerance = _projection_alignment_tolerance(report, region_id)
    supports: list[dict[str, Any]] = []
    for witness_index, witness in enumerate(witnesses):
        witness_value = float(witness)
        patterns = [
            item
            for item in region.get("linear_pattern_candidates", [])
            if isinstance(item, dict)
            and str(item.get("orientation") or "") == rail_orientation
            and isinstance(item.get("axis_px"), (int, float))
            and abs(float(item["axis_px"]) - witness_value) <= tolerance
            and int(item.get("segment_count") or 0) >= 3
            and int(item.get("gap_count") or 0) >= 2
            and float(item.get("dash_score") or 0.0) >= 0.55
            and isinstance(item.get("span_px"), list)
            and len(item["span_px"]) == 2
        ]
        if len(patterns) != 1:
            continue
        pattern = patterns[0]
        rail_axis = float(pattern["axis_px"])
        rail_start, rail_end = sorted(
            float(value) for value in pattern["span_px"]
        )

        crossing_edges: list[dict[str, Any]] = []
        for edge in profile_inventory:
            if (
                not isinstance(edge, dict)
                or edge.get("kind") != "profile_edge_candidate"
                or str(edge.get("region_id") or "") != region_id
                or str(edge.get("source_orientation") or "")
                != boundary_orientation
                or not isinstance(edge.get("position_px"), (int, float))
            ):
                continue
            span = edge.get("span_px")
            if not (
                isinstance(span, list)
                and len(span) == 2
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    for value in span
                )
            ):
                continue
            edge_start, edge_end = sorted(float(value) for value in span)
            if edge_start - tolerance <= rail_axis <= edge_end + tolerance:
                crossing_edges.append(edge)

        crossing_edges.sort(key=lambda item: float(item["position_px"]))
        if len(crossing_edges) != 2:
            continue
        low = float(crossing_edges[0]["position_px"])
        high = float(crossing_edges[1]["position_px"])
        if high - low <= tolerance:
            continue
        endpoint_tolerance = tolerance + 1.0
        if not (
            rail_start <= low + endpoint_tolerance
            and rail_end >= high - endpoint_tolerance
        ):
            continue

        supports.append(
            {
                "witness_index": witness_index,
                "witness_position_px": witness_value,
                "rail_axis_px": rail_axis,
                "rail_span_px": [rail_start, rail_end],
                "profile_boundary_refs": [
                    str(crossing_edges[0].get("ref") or ""),
                    str(crossing_edges[1].get("ref") or ""),
                ],
                "profile_boundary_positions_px": [low, high],
                "dash_score": float(pattern.get("dash_score") or 0.0),
                "segment_count": int(pattern.get("segment_count") or 0),
                "gap_count": int(pattern.get("gap_count") or 0),
            }
        )

    if not supports:
        return None

    boundary_pairs = {
        tuple(item["profile_boundary_refs"])
        for item in supports
    }
    if len(boundary_pairs) != 1:
        return None

    supports.sort(
        key=lambda item: (
            -float(item["dash_score"]),
            -int(item["segment_count"]),
            int(item["witness_index"]),
        )
    )
    selected = supports[0]
    return {
        **selected,
        "basis": (
            "diameter_witness_dashed_projection_crosses_unique_local_"
            "material_boundaries"
        ),
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_topology_only": True,
    }


def _engineering_callout_routing(
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    *,
    hidden_pattern_owner_by_index: dict[tuple[str, int], str],
    existing_entity_keys: set[str],
    profile_inventory: list[dict[str, Any]] | None = None,
    verified_profile_arc_sources: set[str] | None = None,
    excluded_source_item_indices: set[Any] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[ObservationEntity],
    list[ObservationValue],
    list[ObservationUnresolved],
]:
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        return [], [], [], []

    profile_inventory = profile_inventory or []
    verified_profile_arc_sources = verified_profile_arc_sources or set()
    excluded_source_indices = excluded_source_item_indices or set()
    regions = report.get("regions", [])
    annotation_lines = report.get("annotation_line_candidates", [])
    annotation_curves = report.get("annotation_curve_candidates", [])
    region_boxes: list[tuple[str, list[Any]]] = []
    geometric_regions: list[dict[str, Any]] = []
    if isinstance(regions, list):
        for region in regions:
            if not isinstance(region, dict):
                continue
            region_id = str(region.get("region_id") or "")
            bbox = region.get("bbox_px")
            if region_id and isinstance(bbox, list):
                region_boxes.append((region_id, bbox))
            if region_id in view_lookup:
                geometric_regions.append(region)

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
        if source_item_index in excluded_source_indices:
            continue
        evidence = [f"hybrid:whole:{source_item_index}"]
        binding_bbox = binding_bbox_by_index.get(
            source_item_index,
            item.get("bbox"),
        )
        center = _bbox_center(item.get("bbox"))
        raw_region_candidates = (
            sorted(
                region_id
                for region_id, bbox in region_boxes
                if _point_in_bbox(center, bbox)
            )
            if center is not None
            else []
        )
        region_candidates = [
            region_id
            for region_id in raw_region_candidates
            if region_id in view_lookup
        ]
        reference_region_candidates = [
            region_id
            for region_id in raw_region_candidates
            if region_id not in view_lookup
        ]

        if reference_region_candidates and not region_candidates:
            ledger.append(
                {
                    "source_item_index": source_item_index,
                    "bbox": item.get("bbox"),
                    "binding_bbox": binding_bbox,
                    "binding_group_source_item_indices": (
                        binding_group_by_index.get(
                            source_item_index,
                            [source_item_index],
                        )
                    ),
                    "confidence": item.get("confidence"),
                    "region_candidates": [],
                    "reference_region_candidates": (
                        reference_region_candidates
                    ),
                    "binding": {
                        "status": "reference_only",
                        "basis": "non_geometric_reference_region",
                        "region_ids": reference_region_candidates,
                    },
                    **parsed,
                }
            )
            continue

        leader_binding = bind_callout_to_circle_entity(
            binding_bbox,
            annotation_lines,
            geometric_regions,
        )
        profile_arc_radius_binding: dict[str, Any] | None = None
        radius_value = parsed["facts"].get("radius")
        if (
            isinstance(radius_value, (int, float))
            and not isinstance(radius_value, bool)
            and isinstance(annotation_curves, list)
        ):
            curve_binding = bind_callout_to_curve_candidate(
                binding_bbox,
                annotation_lines,
                annotation_curves,
                allowed_curve_source_ids=verified_profile_arc_sources,
            )
            if curve_binding.get("status") == "bound":
                profile_arc_radius_binding = {
                    **curve_binding,
                    "status": "profile_arc_candidate_backed",
                    "engineering_radius": float(radius_value),
                    "engineering_value_source": "hybrid_ocr",
                }
            else:
                profile_arc_radius_binding = curve_binding

        linear_pattern_binding: dict[str, Any] | None = None
        linear_pattern_ambiguity: dict[str, Any] | None = None
        if any(
            key in parsed["facts"]
            for key in {
                "diameter",
                "thread_spec",
                "through",
                "recessed_hole",
            }
        ):
            search_region_ids = (
                list(region_candidates)
                if region_candidates
                else sorted(view_lookup)
            )
            pattern_matches: list[dict[str, Any]] = []
            for region_id in search_region_ids:
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
                if region is None or region_view is None:
                    continue

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
                if candidate_pattern_binding.get("status") != "bound":
                    continue

                pattern_index = candidate_pattern_binding.get("pattern_index")
                hidden_owner = (
                    hidden_pattern_owner_by_index.get(
                        (region_id, int(pattern_index))
                    )
                    if isinstance(pattern_index, int)
                    else None
                )
                if hidden_owner is not None:
                    candidate_pattern_binding = {
                        **candidate_pattern_binding,
                        "entity_key": hidden_owner,
                        "hidden_pair_owner_reused": True,
                        "basis": (
                            "callout_oblique_leader_to_hidden_pair_member"
                        ),
                    }
                pattern_matches.append(candidate_pattern_binding)

            if len(pattern_matches) == 1:
                linear_pattern_binding = pattern_matches[0]
            elif len(pattern_matches) > 1:
                linear_pattern_ambiguity = {
                    "status": "unresolved",
                    "reason": (
                        "multiple_callout_linear_pattern_regions_without_unique_target"
                    ),
                    "candidate_bindings": pattern_matches,
                }

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
                if (
                    pattern_entity_key not in existing_entity_keys
                    and pattern_entity_key not in callout_entity_keys
                ):
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
            elif (
                binding.get("status") != "bound"
                and linear_pattern_ambiguity is not None
            ):
                binding = linear_pattern_ambiguity

        parsed = _recover_geometry_backed_leading_zero_hole_value(
            parsed,
            binding,
        )

        through_projection_support = (
            _dimension_backed_through_projection_support(
                binding,
                report=report,
                profile_inventory=profile_inventory,
            )
            if (
                binding.get("status") == "dimension_backed"
                and isinstance(parsed.get("facts"), dict)
                and isinstance(parsed["facts"].get("diameter"), (int, float))
                and not any(
                    key in parsed["facts"]
                    for key in (
                        "through",
                        "depth",
                        "thread_depth",
                        "counterbore_depth",
                        "recess_depth",
                    )
                )
            )
            else None
        )
        if through_projection_support is not None:
            parsed = {
                **parsed,
                "facts": {
                    **parsed["facts"],
                    "through": True,
                },
                "geometry_backed_termination": through_projection_support,
            }

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
            "reference_region_candidates": reference_region_candidates,
            "binding": binding,
            **(
                {
                    "profile_arc_radius_binding": profile_arc_radius_binding,
                }
                if profile_arc_radius_binding is not None
                else {}
            ),
            **parsed,
        }
        ledger.append(record)

        radius_arc_bound = (
            isinstance(profile_arc_radius_binding, dict)
            and profile_arc_radius_binding.get("status")
            == "profile_arc_candidate_backed"
        )

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
                "counterbore_diameter",
                "counterbore_depth",
                "recessed_hole",
            }
        }

        if radius_arc_bound and set(parsed["facts"]) == {"radius"}:
            continue

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

        if (
            binding.get("status") == "pattern_backed"
            and not binding.get("hidden_pair_owner_reused")
        ):
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
            key: value
            for key, value in parsed["facts"].items()
            if (
                key not in safe_facts
                and not (key == "radius" and radius_arc_bound)
            )
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


def _recover_unassigned_profile_edge_offsets(
    *,
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    boundary_roles: dict[str, Literal["overall_min", "overall_max"]],
    profile_entity_by_ref: dict[str, str],
    excluded_source_item_indices: set[Any] | None = None,
) -> tuple[list[ObservationDimension], list[dict[str, Any]]]:
    """Recover profile offsets only from uniquely owned dimension sub-spans.

    OCR provides the engineering value. Pixel geometry is used only to bind one
    unassigned text item to one dimension witness pair and its physical profile
    endpoints. No pixel distance is converted into an engineering coordinate.
    """

    coverage = report.get("coverage", {})
    raw_items = (
        coverage.get("unassigned_linear_observations", [])
        if isinstance(coverage, dict)
        else []
    )
    excluded = excluded_source_item_indices or set()

    def witness_owner(
        candidate: dict[str, Any],
        witness_index: int,
    ) -> tuple[str, str | None, str] | None:
        record = next(
            (
                item
                for item in candidate.get("witness_anchor_evidence", [])
                if isinstance(item, dict)
                and item.get("witness_index") == witness_index
            ),
            None,
        )
        if record is None:
            return None

        refs = sorted(
            {
                str(anchor.get("ref") or "")
                for anchor in record.get("nearest_anchors", [])
                if isinstance(anchor, dict)
                and anchor.get("kind") == "profile_edge_candidate"
                and str(anchor.get("ref") or "")
            }
        )
        resolved: list[tuple[str, str | None, str]] = []
        for ref in refs:
            boundary_role = boundary_roles.get(ref)
            if boundary_role is not None:
                resolved.append((boundary_role, None, ref))
                continue
            entity_key = profile_entity_by_ref.get(ref)
            if entity_key is not None:
                resolved.append(("profile_boundary", entity_key, ref))
        return resolved[0] if len(resolved) == 1 else None

    recovered: list[ObservationDimension] = []
    ledger: list[dict[str, Any]] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        source_index = item.get("source_item_index")
        if source_index in excluded:
            continue
        value = _token_numeric_value(item.get("token"))
        center = _bbox_center(item.get("bbox"))
        bounds = _bbox_bounds(item.get("bbox"))
        if value is None or value <= 0 or center is None or bounds is None:
            continue

        matches: list[dict[str, Any]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict) or candidate.get("accepted_token") is not None:
                continue
            region_id = str(candidate.get("region_id") or "")
            region_view = view_lookup.get(region_id)
            orientation = str(candidate.get("orientation") or "")
            candidate_axis = candidate.get("axis_px")
            witness_positions = candidate.get("witness_positions_px", [])
            if (
                region_view is None
                or orientation not in {"horizontal", "vertical"}
                or not isinstance(candidate_axis, (int, float))
                or not isinstance(witness_positions, list)
            ):
                continue

            typed_positions = [
                (index, float(position))
                for index, position in enumerate(witness_positions)
                if isinstance(position, (int, float))
                and not isinstance(position, bool)
            ]
            if len(typed_positions) < 2:
                continue

            left, top, right, bottom = bounds
            if orientation == "horizontal":
                along = center[0]
                perpendicular_gap = max(
                    top - float(candidate_axis),
                    0.0,
                    float(candidate_axis) - bottom,
                )
            else:
                along = center[1]
                perpendicular_gap = max(
                    left - float(candidate_axis),
                    0.0,
                    float(candidate_axis) - right,
                )

            for first_pos in range(len(typed_positions)):
                first_index, first_value = typed_positions[first_pos]
                first_owner = witness_owner(candidate, first_index)
                if first_owner is None:
                    continue
                for second_pos in range(first_pos + 1, len(typed_positions)):
                    second_index, second_value = typed_positions[second_pos]
                    second_owner = witness_owner(candidate, second_index)
                    if second_owner is None:
                        continue

                    owners = [first_owner, second_owner]
                    if (
                        sum(owner[0] == "profile_boundary" for owner in owners) != 1
                        or sum(
                            owner[0] in {"overall_min", "overall_max"}
                            for owner in owners
                        ) != 1
                    ):
                        continue

                    pair_span = abs(second_value - first_value)
                    if pair_span <= 0:
                        continue
                    midpoint = (first_value + second_value) / 2.0
                    along_residual = abs(along - midpoint)
                    if along_residual > max(12.0, pair_span * 0.60):
                        continue

                    region_minor_span = 0.0
                    for region in report.get("regions", []):
                        if (
                            isinstance(region, dict)
                            and str(region.get("region_id") or "") == region_id
                        ):
                            bbox = region.get("bbox_px")
                            if (
                                isinstance(bbox, list)
                                and len(bbox) == 4
                                and isinstance(bbox[2], (int, float))
                                and isinstance(bbox[3], (int, float))
                            ):
                                region_minor_span = min(
                                    float(bbox[2]),
                                    float(bbox[3]),
                                )
                            break
                    perpendicular_limit = max(
                        32.0,
                        region_minor_span * 0.22,
                        pair_span * 0.75,
                    )
                    if perpendicular_gap > perpendicular_limit:
                        continue

                    matches.append(
                        {
                            "candidate": candidate,
                            "region_id": region_id,
                            "orientation": orientation,
                            "first_owner": first_owner,
                            "second_owner": second_owner,
                            "first_index": first_index,
                            "second_index": second_index,
                            "pair_span_px": pair_span,
                            "along_residual_px": along_residual,
                            "perpendicular_gap_px": perpendicular_gap,
                            "score_px": along_residual + perpendicular_gap,
                        }
                    )

        matches.sort(
            key=lambda match: (
                float(match["score_px"]),
                float(match["along_residual_px"]),
                str(match["candidate"].get("candidate_id") or ""),
                int(match["first_index"]),
                int(match["second_index"]),
            )
        )
        if not matches:
            continue
        best = matches[0]
        if len(matches) > 1:
            uniqueness_margin = max(6.0, float(best["pair_span_px"]) * 0.10)
            if float(matches[1]["score_px"]) - float(best["score_px"]) < uniqueness_margin:
                continue

        candidate = best["candidate"]
        orientation = str(best["orientation"])
        region_view = view_lookup[str(best["region_id"])]
        axis = _axis_for(region_view.view_kind, orientation)
        evidence = [
            f"hybrid:whole:{source_index}",
            (
                "hybrid:"
                f"{candidate.get('candidate_id')}:"
                "unassigned-profile-offset-recovery"
            ),
        ]

        endpoints: list[ObservationDimensionEndpoint] = []
        for role, entity_key, _ref in [
            best["first_owner"],
            best["second_owner"],
        ]:
            if role == "profile_boundary":
                assert entity_key is not None
                endpoints.append(
                    ObservationDimensionEndpoint(
                        role="profile_boundary",
                        entity_key=entity_key,
                        basis="profile_edge",
                        evidence=evidence,
                    )
                )
            else:
                endpoints.append(
                    ObservationDimensionEndpoint(
                        role=role,
                        evidence=evidence,
                    )
                )

        dimension_key = (
            f"{best['region_id']}.RECOVERED_PROFILE_OFFSET_{source_index}"
        )
        recovered.append(
            ObservationDimension(
                key=dimension_key,
                value=value,
                axis=axis,
                endpoints=endpoints,
                direction=_dimension_direction_from_image_order(
                    region_view.view_kind,
                    orientation,
                ),
                evidence=evidence,
                required_for_modeling=True,
            )
        )
        profile_owner = next(
            owner
            for owner in [best["first_owner"], best["second_owner"]]
            if owner[0] == "profile_boundary"
        )
        overall_owner = next(
            owner
            for owner in [best["first_owner"], best["second_owner"]]
            if owner[0] in {"overall_min", "overall_max"}
        )
        ledger.append(
            {
                "dimension_key": dimension_key,
                "source_item_index": source_index,
                "candidate_id": candidate.get("candidate_id"),
                "region_id": best["region_id"],
                "axis": axis,
                "value": value,
                "profile_entity_key": profile_owner[1],
                "profile_ref": profile_owner[2],
                "overall_role": overall_owner[0],
                "overall_ref": overall_owner[2],
                "witness_indices": [
                    best["first_index"],
                    best["second_index"],
                ],
                "basis": (
                    "unique_unassigned_text_to_dimension_subspan_with_"
                    "profile_and_overall_endpoint_ownership"
                ),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
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


_VIEW_NORMAL_BY_KIND: dict[str, Axis] = {
    "front": "Y",
    "side": "X",
    "top": "Z",
}


def _projection_center_axis(
    view_kind: ViewKind,
    line_orientation: str,
) -> Axis:
    """Return the engineering axis represented by a line's axis_px position."""

    pixel_index = 1 if line_orientation == "horizontal" else 0
    matches = [
        axis
        for (candidate_view, axis), candidate_index
        in _PIXEL_INDEX_BY_VIEW_AXIS.items()
        if candidate_view == view_kind and candidate_index == pixel_index
    ]
    if len(matches) != 1:
        raise HybridCaptureAdapterError(
            "projection line center axis is not uniquely defined for "
            f"{view_kind!r}/{line_orientation!r}"
        )
    return matches[0]


def _unique_thread_recess_centerline_alignments(
    *,
    report: dict[str, Any],
    view_lookup: dict[str, HybridRegionView],
    hidden_entity_records: dict[str, dict[str, Any]],
    callout_values: list[ObservationValue],
    entity_keys: set[str],
) -> tuple[list[ObservationCenterlineAlignment], list[dict[str, Any]]]:
    """Identify a unique threaded/recessed coaxial continuation across views.

    Pixels establish only orthographic centerline identity. The resolver gets
    engineering coordinates from dimensions and propagates them by alignment.
    """

    values_by_entity: dict[str, dict[str, Any]] = {}
    for item in callout_values:
        values_by_entity.setdefault(item.entity_key, {})[item.field] = item.value

    regions = {
        str(item.get("region_id") or ""): item
        for item in report.get("regions", [])
        if isinstance(item, dict) and item.get("region_id")
    }
    alignments: list[ObservationCenterlineAlignment] = []
    ledger: list[dict[str, Any]] = []

    for hidden_entity, record in sorted(hidden_entity_records.items()):
        if hidden_entity not in entity_keys:
            continue
        source_fields = values_by_entity.get(hidden_entity, {})
        if not isinstance(source_fields.get("thread_spec"), str):
            continue

        feature_axis = str(record.get("feature_axis") or "").upper()
        if feature_axis not in {"X", "Y", "Z"}:
            continue
        source_region = hidden_entity.split(".", 1)[0]
        source_view = view_lookup.get(source_region)
        if source_view is None:
            continue
        orientation = str(record.get("pattern_orientation") or "")
        if orientation not in {"horizontal", "vertical"}:
            continue
        shared_axis = _projection_center_axis(
            source_view.view_kind,
            orientation,
        )
        if shared_axis == feature_axis:
            continue

        source_pixel_index = _PIXEL_INDEX_BY_VIEW_AXIS.get(
            (source_view.view_kind, shared_axis)
        )
        source_position = record.get("position_px")
        if (
            source_pixel_index is None
            or not isinstance(source_position, (int, float))
            or isinstance(source_position, bool)
        ):
            continue

        matches: list[dict[str, Any]] = []
        for target_region, region in sorted(regions.items()):
            if target_region == source_region:
                continue
            target_view = view_lookup.get(target_region)
            if (
                target_view is None
                or _VIEW_NORMAL_BY_KIND.get(target_view.view_kind) != feature_axis
            ):
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
                target_entity = f"{target_region}.{group_id}" if group_id else ""
                target_fields = values_by_entity.get(target_entity, {})
                if (
                    target_entity not in entity_keys
                    or target_fields.get("recessed_hole") is not True
                    or not isinstance(center, list)
                    or len(center) < 2
                    or not isinstance(center[target_pixel_index], (int, float))
                    or isinstance(center[target_pixel_index], bool)
                ):
                    continue

                residual = abs(
                    float(center[target_pixel_index]) - float(source_position)
                )
                if residual <= tolerance:
                    matches.append(
                        {
                            "entity_key": target_entity,
                            "shared_axis": shared_axis,
                            "residual_px": residual,
                            "tolerance_px": tolerance,
                        }
                    )

        matches.sort(key=lambda item: (item["residual_px"], item["entity_key"]))
        if len(matches) != 1:
            continue

        match = matches[0]
        target_entity = str(match["entity_key"])
        evidence = [
            f"hybrid:centerline:{hidden_entity}",
            f"hybrid:centerline:{target_entity}",
            (
                "hybrid:orthographic_centerline_residual_px:"
                f"{float(match['residual_px']):.3f}"
            ),
        ]
        alignments.append(
            ObservationCenterlineAlignment(
                entity_keys=[hidden_entity, target_entity],
                feature_axis=feature_axis,
                evidence=evidence,
                required_for_modeling=True,
            )
        )
        ledger.append(
            {
                "entity_keys": [hidden_entity, target_entity],
                "feature_axis": feature_axis,
                "shared_projection_axis": match["shared_axis"],
                "projection_residual_px": round(float(match["residual_px"]), 3),
                "projection_tolerance_px": round(float(match["tolerance_px"]), 3),
                "basis": (
                    "unique_orthographic_centerline_alignment_plus_"
                    "threaded_and_recessed_continuation_semantics"
                ),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            }
        )

    return alignments, ledger


def _resolved_axis_boundary_positions(
    boundaries: list[dict[str, Any]],
    *,
    region_id: str,
    axis: Axis,
) -> dict[str, tuple[float, str]] | None:
    matches: list[dict[str, tuple[float, str]]] = []
    for boundary in boundaries:
        if not isinstance(boundary, dict) or boundary.get("status") != "resolved":
            continue
        if str(boundary.get("region_id") or "") != region_id:
            continue
        if str(boundary.get("axis") or "").upper() != axis:
            continue

        positions: dict[str, tuple[float, str]] = {}
        valid = True
        for anchor in boundary.get("anchors", []):
            if not isinstance(anchor, dict):
                continue
            role = str(anchor.get("role") or "")
            position = anchor.get("position_px")
            ref = str(anchor.get("ref") or "")
            if (
                role not in {"overall_min", "overall_max"}
                or not isinstance(position, (int, float))
                or isinstance(position, bool)
            ):
                continue
            previous = positions.get(role)
            current = (float(position), ref)
            if previous is not None and not math.isclose(
                previous[0],
                current[0],
                abs_tol=1e-6,
            ):
                valid = False
                break
            positions[role] = current

        if valid and set(positions) == {"overall_min", "overall_max"}:
            matches.append(positions)

    if len(matches) != 1:
        return None
    return matches[0]


def _open_slot_observations(
    *,
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    boundaries: list[dict[str, Any]],
    overall_dimension_facts: list[PartialOverallDimensionFact],
) -> tuple[
    list[ObservationEntity],
    list[ObservationValue],
    list[ObservationUnresolved],
    list[dict[str, Any]],
    set[Any],
]:
    """Materialize only uniquely owned top-open slot geometry.

    Engineering width comes from OCR. Pixel geometry is used only to prove one
    open-top notch: a gap in the resolved overall-Z-max contour, two descending
    slot walls, midpoint alignment to one circular projection, and termination
    at that circle's upper projected edge. No pixel distance is converted to mm.

    Through-axis and lower-Z engineering semantics remain unresolved here.
    """

    coverage = report.get("coverage", {})
    raw_unassigned = (
        coverage.get("unassigned_linear_observations", [])
        if isinstance(coverage, dict)
        else []
    )
    unassigned = [
        item
        for item in raw_unassigned
        if isinstance(item, dict)
        and _token_numeric_value(item.get("token")) is not None
        and _bbox_center(item.get("bbox")) is not None
    ]
    if not unassigned:
        return [], [], [], [], set()

    z_facts = [
        fact
        for fact in overall_dimension_facts
        if fact.axis == "Z" and fact.evidence
    ]
    if len(z_facts) != 1:
        return [], [], [], [], set()
    z_fact = z_facts[0]

    def source_lines(
        region_id: str,
        orientation: str,
    ) -> list[tuple[float, float, float]]:
        seen: set[tuple[float, float, float]] = set()
        output: list[tuple[float, float, float]] = []
        for candidate in candidates:
            if (
                not isinstance(candidate, dict)
                or str(candidate.get("region_id") or "") != region_id
            ):
                continue
            for witness in candidate.get("witness_line_evidence", []):
                if not isinstance(witness, dict):
                    continue
                for line in witness.get("source_lines", []):
                    if not isinstance(line, dict):
                        continue
                    if str(line.get("orientation") or "") != orientation:
                        continue
                    axis_px = line.get("axis_px")
                    span_px = line.get("span_px")
                    if not (
                        isinstance(axis_px, (int, float))
                        and not isinstance(axis_px, bool)
                        and isinstance(span_px, list)
                        and len(span_px) == 2
                        and all(
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            for value in span_px
                        )
                    ):
                        continue
                    start, end = sorted(float(value) for value in span_px)
                    record = (
                        round(float(axis_px), 3),
                        round(start, 3),
                        round(end, 3),
                    )
                    if record in seen:
                        continue
                    seen.add(record)
                    output.append(record)
        return output

    entities: list[ObservationEntity] = []
    values: list[ObservationValue] = []
    unresolved: list[ObservationUnresolved] = []
    ledger: list[dict[str, Any]] = []
    claimed_source_indices: set[Any] = set()

    for region in report.get("regions", []):
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        view = view_lookup.get(region_id)
        if view is None or view.view_kind not in {"front", "side"}:
            continue
        if _axis_for(view.view_kind, "vertical") != "Z":
            continue

        bbox = region.get("bbox_px")
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in bbox
            )
        ):
            continue
        rx, ry, rw, rh = (float(value) for value in bbox)
        tolerance = max(3.0, min(rw, rh) * 0.01)

        boundary_positions = _resolved_axis_boundary_positions(
            boundaries,
            region_id=region_id,
            axis="Z",
        )
        if boundary_positions is None:
            continue
        top_y, top_ref = boundary_positions["overall_max"]

        horizontal_lines = [
            line
            for line in source_lines(region_id, "horizontal")
            if abs(line[0] - top_y) <= tolerance
        ]
        spans = sorted((line[1], line[2]) for line in horizontal_lines)
        merged: list[list[float]] = []
        for start, end in spans:
            if not merged or start > merged[-1][1] + tolerance:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        if len(merged) < 2:
            continue

        vertical_lines = source_lines(region_id, "vertical")
        region_matches: list[dict[str, Any]] = []

        groups = region.get("circle_groups", [])
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("circle_group_id") or "")
            center = group.get("center_px")
            rings = group.get("rings")
            if not (
                group_id
                and isinstance(center, list)
                and len(center) >= 2
                and all(
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    for value in center[:2]
                )
                and isinstance(rings, list)
                and len(rings) == 1
                and isinstance(rings[0], dict)
                and isinstance(rings[0].get("radius_px"), (int, float))
                and not isinstance(rings[0].get("radius_px"), bool)
            ):
                continue

            center_x = float(center[0])
            center_y = float(center[1])
            radius = float(rings[0]["radius_px"])
            if radius <= 0:
                continue
            circle_top_y = center_y - radius
            if circle_top_y <= top_y + tolerance:
                continue

            gaps = []
            for left_span, right_span in zip(merged, merged[1:]):
                left_edge = float(left_span[1])
                right_edge = float(right_span[0])
                if right_edge <= left_edge:
                    continue
                gap_width = right_edge - left_edge
                midpoint = (left_edge + right_edge) / 2.0
                if not (left_edge - tolerance <= center_x <= right_edge + tolerance):
                    continue
                if abs(midpoint - center_x) > max(tolerance, gap_width * 0.35):
                    continue
                gaps.append((left_edge, right_edge, gap_width, midpoint))
            if len(gaps) != 1:
                continue

            left_edge, right_edge, gap_width, midpoint = gaps[0]
            interval_length = circle_top_y - top_y
            if interval_length <= 0:
                continue

            def wall_support(edge_x: float) -> list[tuple[float, float, float]]:
                matches: list[tuple[float, float, float]] = []
                end_tolerance = max(tolerance * 1.5, radius * 0.12)
                for axis_px, start, end in vertical_lines:
                    if abs(axis_px - edge_x) > tolerance:
                        continue
                    overlap = max(
                        0.0,
                        min(end, circle_top_y) - max(start, top_y),
                    )
                    if overlap / interval_length < 0.45:
                        continue
                    if abs(end - circle_top_y) > end_tolerance:
                        continue
                    matches.append((axis_px, start, end))
                return matches

            left_walls = wall_support(left_edge)
            right_walls = wall_support(right_edge)
            if not left_walls or not right_walls:
                continue

            token_candidates = []
            for item in unassigned:
                source_index = item.get("source_item_index")
                if source_index in claimed_source_indices:
                    continue
                center_px = _bbox_center(item.get("bbox"))
                value = _token_numeric_value(item.get("token"))
                if center_px is None or value is None or value <= 0:
                    continue
                cx, cy = center_px
                if not (
                    rx - rw * 0.05 <= cx <= rx + rw * 1.05
                    and ry - rh * 0.25 <= cy <= top_y + rh * 0.05
                    and abs(cx - midpoint) <= rw * 0.20
                ):
                    continue
                token_candidates.append(item)
            if len(token_candidates) != 1:
                continue

            token_item = token_candidates[0]
            region_matches.append(
                {
                    "group_id": group_id,
                    "circle_entity": f"{region_id}.{group_id}",
                    "circle_center_px": [center_x, center_y],
                    "circle_radius_px": radius,
                    "circle_top_y_px": circle_top_y,
                    "top_boundary_position_px": top_y,
                    "top_boundary_ref": top_ref,
                    "left_edge_px": left_edge,
                    "right_edge_px": right_edge,
                    "gap_width_px": gap_width,
                    "gap_midpoint_px": midpoint,
                    "left_walls": left_walls,
                    "right_walls": right_walls,
                    "token_item": token_item,
                }
            )

        if len(region_matches) != 1:
            continue

        match = region_matches[0]
        token_item = match["token_item"]
        source_index = token_item.get("source_item_index")
        value = _token_numeric_value(token_item.get("token"))
        if value is None or value <= 0:
            continue

        width_axis = _axis_for(view.view_kind, "horizontal")
        through_axis = _VIEW_NORMAL_BY_KIND.get(view.view_kind)
        if through_axis is None or through_axis == width_axis:
            continue
        entity_key = f"{region_id}.OPEN_SLOT.{source_index}"
        evidence = list(
            dict.fromkeys(
                [
                    f"hybrid:whole:{source_index}",
                    f"hybrid:open-slot:{region_id}:{source_index}",
                    f"hybrid:boundary:{match['top_boundary_ref'] or 'overall_max_z'}",
                    f"hybrid:geometry:{match['circle_entity']}",
                    *z_fact.evidence,
                ]
            )
        )

        entities.append(
            ObservationEntity(
                key=entity_key,
                view_key=f"view.{region_id}",
                shape="slot_edges",
                cross_view_disposition="single_view",
                evidence=evidence,
                required_for_modeling=True,
            )
        )
        values.extend(
            [
                ObservationValue(
                    entity_key=entity_key,
                    field="type",
                    value="slot",
                    semantic="feature_kind",
                    evidence=evidence,
                ),
                ObservationValue(
                    entity_key=entity_key,
                    field="width",
                    value=float(value),
                    semantic="slot_width",
                    evidence=evidence,
                ),
                ObservationValue(
                    entity_key=entity_key,
                    field="width_axis",
                    value=width_axis,
                    semantic="axis",
                    evidence=evidence,
                ),
                ObservationValue(
                    entity_key=entity_key,
                    field="through_axis",
                    value=through_axis,
                    semantic="axis",
                    evidence=[
                        *evidence,
                        f"hybrid:view-normal:{view.view_kind}:{through_axis}",
                    ],
                ),
                ObservationValue(
                    entity_key=entity_key,
                    field="top_z",
                    value=float(z_fact.value),
                    semantic="position_dimension",
                    evidence=evidence,
                ),
            ]
        )
        unresolved.append(
            ObservationUnresolved(
                kind="feature_value",
                reason=(
                    "Slot walls terminate at the circular projection's upper "
                    "edge in pixel topology, but lower_z must be closed later "
                    "from engineering circle center/diameter relations rather "
                    "than pixel-to-mm conversion."
                ),
                entity_keys=[entity_key],
                field="bottom_z",
                evidence=evidence,
                required_for_modeling=True,
            )
        )
        claimed_source_indices.add(source_index)
        ledger.append(
            {
                "entity_key": entity_key,
                "source_item_index": source_index,
                "region_id": region_id,
                "view_kind": view.view_kind,
                "width": float(value),
                "width_axis": width_axis,
                "through_axis": through_axis,
                "through_axis_basis": (
                    "proved_gap_in_resolved_overall_silhouette_plus_view_normal"
                ),
                "top_z": float(z_fact.value),
                "top_boundary_ref": match["top_boundary_ref"],
                "top_boundary_position_px": round(
                    float(match["top_boundary_position_px"]), 3
                ),
                "circle_entity": match["circle_entity"],
                "circle_center_px": [
                    round(float(item), 3)
                    for item in match["circle_center_px"]
                ],
                "circle_radius_px": round(float(match["circle_radius_px"]), 3),
                "circle_top_y_px": round(float(match["circle_top_y_px"]), 3),
                "slot_edge_positions_px": [
                    round(float(match["left_edge_px"]), 3),
                    round(float(match["right_edge_px"]), 3),
                ],
                "slot_gap_midpoint_px": round(
                    float(match["gap_midpoint_px"]), 3
                ),
                "left_wall_support": [
                    [round(float(v), 3) for v in item]
                    for item in match["left_walls"]
                ],
                "right_wall_support": [
                    [round(float(v), 3) for v in item]
                    for item in match["right_walls"]
                ],
                "basis": (
                    "unique_overall_top_gap_plus_two_descending_walls_plus_"
                    "circle_center_alignment_and_upper_circle_termination"
                ),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        )

    return entities, values, unresolved, ledger, claimed_source_indices


def _segment_distance_to_position(
    segments: Any,
    position: float,
) -> float | None:
    distances: list[float] = []
    if not isinstance(segments, list):
        return None
    for segment in segments:
        if not (
            isinstance(segment, list)
            and len(segment) == 2
            and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in segment
            )
        ):
            continue
        start, end = sorted(float(value) for value in segment)
        if start <= position <= end:
            return 0.0
        distances.append(min(abs(position - start), abs(position - end)))
    return min(distances) if distances else None


def _transverse_recess_start_side_values(
    *,
    report: dict[str, Any],
    view_lookup: dict[str, HybridRegionView],
    boundaries: list[dict[str, Any]],
    hidden_entity_records: dict[str, dict[str, Any]],
    callout_values: list[ObservationValue],
    centerline_alignments: list[ObservationCenterlineAlignment],
) -> tuple[list[ObservationValue], list[dict[str, Any]]]:
    """Resolve transverse recess entry side from local fragment topology only.

    The rule is intentionally narrow: an already-unique threaded/recessed
    centerline alignment supplies the source projection centerline.  The
    closest fragmented line on that centerline must uniquely contact exactly
    one resolved overall boundary along the feature axis.  Pixels establish
    only min/max topology; no pixel distance is converted to engineering units.
    """

    values_by_entity: dict[str, dict[str, Any]] = {}
    for item in callout_values:
        values_by_entity.setdefault(item.entity_key, {})[item.field] = item.value

    regions = {
        str(item.get("region_id") or ""): item
        for item in report.get("regions", [])
        if isinstance(item, dict) and item.get("region_id")
    }

    output: list[ObservationValue] = []
    ledger: list[dict[str, Any]] = []
    claimed_targets: set[str] = set()

    for alignment in centerline_alignments:
        feature_axis = alignment.feature_axis
        if feature_axis not in {"X", "Y"}:
            continue

        hidden_entities = [
            entity
            for entity in alignment.entity_keys
            if entity in hidden_entity_records
        ]
        target_entities = [
            entity
            for entity in alignment.entity_keys
            if entity not in hidden_entity_records
            and (
                values_by_entity.get(entity, {}).get("recessed_hole") is True
                or values_by_entity.get(entity, {}).get("counterbore_diameter") is not None
                or values_by_entity.get(entity, {}).get("counterbore_depth") is not None
            )
        ]
        if len(hidden_entities) != 1 or len(target_entities) != 1:
            continue

        hidden_entity = hidden_entities[0]
        target_entity = target_entities[0]
        if target_entity in claimed_targets:
            continue
        if values_by_entity.get(target_entity, {}).get("start_side") in {"min", "max"}:
            continue

        record = hidden_entity_records[hidden_entity]
        source_region = hidden_entity.split(".", 1)[0]
        source_view = view_lookup.get(source_region)
        region = regions.get(source_region)
        center_position = record.get("position_px")
        if (
            source_view is None
            or region is None
            or not isinstance(center_position, (int, float))
            or isinstance(center_position, bool)
        ):
            continue

        axis_pixel_index = _PIXEL_INDEX_BY_VIEW_AXIS.get(
            (source_view.view_kind, feature_axis)
        )
        if axis_pixel_index is None:
            continue
        line_orientation = "horizontal" if axis_pixel_index == 0 else "vertical"
        if str(record.get("pattern_orientation") or "") != line_orientation:
            continue

        boundary_positions = _resolved_axis_boundary_positions(
            boundaries,
            region_id=source_region,
            axis=feature_axis,
        )
        if boundary_positions is None:
            continue

        center_tolerance = _projection_alignment_tolerance(report, source_region)
        pattern_matches: list[tuple[float, int, dict[str, Any]]] = []
        for pattern_index, pattern in enumerate(
            region.get("linear_pattern_candidates", [])
        ):
            if not isinstance(pattern, dict):
                continue
            if str(pattern.get("orientation") or "") != line_orientation:
                continue
            pattern_axis = pattern.get("axis_px")
            if (
                not isinstance(pattern_axis, (int, float))
                or isinstance(pattern_axis, bool)
            ):
                continue
            if _segment_distance_to_position(
                pattern.get("segments_px"),
                boundary_positions["overall_min"][0],
            ) is None:
                continue
            residual = abs(float(pattern_axis) - float(center_position))
            if residual <= center_tolerance:
                pattern_matches.append((residual, pattern_index, pattern))

        pattern_matches.sort(key=lambda item: (item[0], item[1]))
        if len(pattern_matches) != 1:
            continue

        residual, pattern_index, pattern = pattern_matches[0]
        boundary_tolerance = center_tolerance
        boundary_distances: dict[str, float] = {}
        for role, (position, _) in boundary_positions.items():
            distance = _segment_distance_to_position(
                pattern.get("segments_px"),
                position,
            )
            if distance is not None:
                boundary_distances[role] = distance

        touched = [
            role
            for role in ("overall_min", "overall_max")
            if boundary_distances.get(role, float("inf")) <= boundary_tolerance
        ]
        if len(touched) != 1:
            continue

        touched_role = touched[0]
        side = "min" if touched_role == "overall_min" else "max"
        boundary_position, boundary_ref = boundary_positions[touched_role]
        pattern_ref = f"{source_region}.linear_pattern.{pattern_index + 1:03d}"
        evidence = list(
            dict.fromkeys(
                [
                    *alignment.evidence,
                    f"hybrid:recess-start-side:{target_entity}:{side}",
                    f"hybrid:boundary:{boundary_ref or touched_role}",
                    f"hybrid:fragment-pattern:{pattern_ref}",
                ]
            )
        )

        output.append(
            ObservationValue(
                entity_key=target_entity,
                field="start_side",
                value=side,
                semantic="start_side",
                evidence=evidence,
            )
        )
        claimed_targets.add(target_entity)
        ledger.append(
            {
                "entity_key": target_entity,
                "source_hidden_entity": hidden_entity,
                "feature_axis": feature_axis,
                "source_region": source_region,
                "source_view_kind": source_view.view_kind,
                "start_side": side,
                "centerline_position_px": round(float(center_position), 3),
                "pattern_ref": pattern_ref,
                "pattern_axis_px": round(float(pattern["axis_px"]), 3),
                "centerline_residual_px": round(float(residual), 3),
                "boundary_role": touched_role,
                "boundary_ref": boundary_ref,
                "boundary_position_px": round(boundary_position, 3),
                "boundary_distance_px": round(boundary_distances[touched_role], 3),
                "boundary_tolerance_px": round(boundary_tolerance, 3),
                "basis": (
                    "unique_thread_recess_centerline_plus_"
                    "unique_fragment_contact_with_resolved_overall_boundary"
                ),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        )

    return output, ledger


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


_VISIBLE_AXES_BY_VIEW: dict[ViewKind, set[Axis]] = {
    "front": {"X", "Z"},
    "side": {"Y", "Z"},
    "top": {"X", "Y"},
}


def _region_overall_fact_axes(
    context: HybridAdapterContext,
) -> set[tuple[str, Axis]]:
    """Assign overall facts only when region ownership is evidence-backed or unique."""

    result: set[tuple[str, Axis]] = set()
    for fact in context.overall_dimension_facts:
        visible_regions = [
            region
            for region in context.region_views
            if fact.axis in _VISIBLE_AXES_BY_VIEW[region.view_kind]
        ]
        explicit_regions = [
            region
            for region in visible_regions
            if set(region.evidence) & set(fact.evidence)
        ]
        if explicit_regions:
            result.update((region.region_id, fact.axis) for region in explicit_regions)
            continue
        if len(visible_regions) == 1:
            result.add((visible_regions[0].region_id, fact.axis))
    return result



def _region_has_rotational_symmetry(
    context: HybridAdapterContext,
    *,
    region_id: str,
    dimension_axis: Axis,
) -> bool:
    region = next(
        (item for item in context.region_views if item.region_id == region_id),
        None,
    )
    if region is None:
        return False
    visible_axes = _VISIBLE_AXES_BY_VIEW.get(region.view_kind, set())
    for fact in context.rotational_symmetry_facts:
        if fact.axis == dimension_axis or fact.axis not in visible_axes:
            continue
        if set(region.evidence) & set(fact.evidence):
            return True
    return False


def _region_bbox(
    report: dict[str, Any],
    region_id: str,
) -> tuple[float, float, float, float] | None:
    matches = [
        item
        for item in report.get("regions", [])
        if isinstance(item, dict)
        and str(item.get("region_id") or "") == region_id
    ]
    if len(matches) != 1:
        return None
    bbox = matches[0].get("bbox_px")
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in bbox
        )
    ):
        return None
    x, y, width, height = (float(value) for value in bbox)
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _regions_share_structural_raster_view(
    *,
    report: dict[str, Any],
    profile_inventory: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    first_region_id: str,
    second_region_id: str,
) -> bool:
    """Prove that two region crops observe the same physical raster view.

    Region labels remain distinct.  This relation is identity-only: it uses
    overlapping source-image crops plus at least two independently supported
    structural profile edges that recur at the same raster positions.
    """

    if first_region_id == second_region_id:
        return True
    first_view = view_lookup.get(first_region_id)
    second_view = view_lookup.get(second_region_id)
    if (
        first_view is None
        or second_view is None
        or first_view.view_kind != second_view.view_kind
    ):
        return False

    first_bbox = _region_bbox(report, first_region_id)
    second_bbox = _region_bbox(report, second_region_id)
    if first_bbox is None or second_bbox is None:
        return False
    fx, fy, fw, fh = first_bbox
    sx, sy, sw, sh = second_bbox
    if min(fx + fw, sx + sw) <= max(fx, sx):
        return False
    if min(fy + fh, sy + sh) <= max(fy, sy):
        return False

    def independent_edges(region_id: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for item in profile_inventory:
            span = item.get("span_px")
            if (
                item.get("kind") != "profile_edge_candidate"
                or str(item.get("region_id") or "") != region_id
                or not isinstance(item.get("position_px"), (int, float))
                or isinstance(item.get("position_px"), bool)
                or not isinstance(span, list)
                or len(span) != 2
                or not all(
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    for value in span
                )
                or not isinstance(
                    item.get("non_dimension_crossing_source_count"),
                    int,
                )
                or not isinstance(
                    item.get("independent_geometry_source_count", 0),
                    int,
                )
                or (
                    item.get("non_dimension_crossing_source_count", 0) <= 0
                    and item.get("independent_geometry_source_count", 0) < 2
                )
            ):
                continue
            output.append(item)
        return output

    first_edges = independent_edges(first_region_id)
    second_edges = independent_edges(second_region_id)
    first_matches: set[str] = set()
    second_matches: set[str] = set()
    for first in first_edges:
        for second in second_edges:
            if str(first.get("source_orientation") or "") != str(
                second.get("source_orientation") or ""
            ):
                continue
            first_tolerance = float(first.get("axis_tolerance_px", 0.0) or 0.0)
            second_tolerance = float(second.get("axis_tolerance_px", 0.0) or 0.0)
            if abs(float(first["position_px"]) - float(second["position_px"])) > max(
                1.0,
                first_tolerance,
                second_tolerance,
            ):
                continue
            first_span = sorted(float(value) for value in first["span_px"])
            second_span = sorted(float(value) for value in second["span_px"])
            if min(first_span[1], second_span[1]) <= max(
                first_span[0],
                second_span[0],
            ):
                continue
            first_ref = str(first.get("ref") or "")
            second_ref = str(second.get("ref") or "")
            if first_ref and second_ref:
                first_matches.add(first_ref)
                second_matches.add(second_ref)

    return len(first_matches) >= 2 and len(second_matches) >= 2


def _overlapping_profile_associations(
    *,
    report: dict[str, Any],
    profile_inventory: list[dict[str, Any]],
    view_lookup: dict[str, HybridRegionView],
    profile_entity_by_ref: dict[str, str],
) -> list[ObservationAssociation]:
    """Merge only mutually unique structural edges from proven overlapping crops.

    Raster geometry proves identity only.  It never supplies an engineering
    coordinate. Exact same-raster line geometry may establish identity even
    when the line was exposed only through dimension witnesses. Approximate
    overlap still requires independent structural support, and every match
    must remain mutually unique within its region pair.
    """

    eligible_by_region: dict[str, list[dict[str, Any]]] = {}
    ref_region: dict[str, str] = {}

    for item in profile_inventory:
        if item.get("kind") != "profile_edge_candidate":
            continue
        region_id = str(item.get("region_id") or "")
        ref = str(item.get("ref") or "")
        orientation = str(item.get("source_orientation") or "")
        position = item.get("position_px")
        span = item.get("span_px")
        support = item.get("non_dimension_crossing_source_count")
        if (
            not region_id
            or region_id not in view_lookup
            or not ref
            or ref not in profile_entity_by_ref
            or orientation not in {"horizontal", "vertical"}
            or isinstance(position, bool)
            or not isinstance(position, (int, float))
            or not isinstance(span, list)
            or len(span) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in span
            )
            or not isinstance(support, int)
            or isinstance(support, bool)
            or support < 0
        ):
            continue
        low, high = sorted(float(value) for value in span)
        if high <= low:
            continue
        eligible_by_region.setdefault(region_id, []).append(item)
        ref_region[ref] = region_id

    def pair_matches(
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> bool:
        if str(left.get("source_orientation") or "") != str(
            right.get("source_orientation") or ""
        ):
            return False
        left_position = float(left["position_px"])
        right_position = float(right["position_px"])
        left_low, left_high = sorted(float(value) for value in left["span_px"])
        right_low, right_high = sorted(float(value) for value in right["span_px"])

        exact_same_raster_geometry = (
            abs(left_position - right_position) <= 1e-9
            and abs(left_low - right_low) <= 1e-9
            and abs(left_high - right_high) <= 1e-9
        )
        if exact_same_raster_geometry:
            return True

        # Approximate overlap is intentionally stricter. It may bridge
        # independently detected structural lines from overlapping crops, but
        # dimension-only exposure is not enough unless the underlying raster
        # segment is exactly the same.
        if (
            int(left.get("non_dimension_crossing_source_count", 0)) <= 0
            or int(right.get("non_dimension_crossing_source_count", 0)) <= 0
        ):
            return False

        left_tolerance = float(left.get("axis_tolerance_px", 0.0) or 0.0)
        right_tolerance = float(right.get("axis_tolerance_px", 0.0) or 0.0)
        if abs(left_position - right_position) > max(
            1.0,
            left_tolerance,
            right_tolerance,
        ):
            return False

        overlap = min(left_high, right_high) - max(left_low, right_low)
        shorter = min(left_high - left_low, right_high - right_low)
        if shorter <= 0 or overlap <= 0:
            return False
        return overlap / shorter >= 0.8

    graph: dict[str, set[str]] = {}
    regions = sorted(eligible_by_region)
    for index, left_region in enumerate(regions):
        for right_region in regions[index + 1 :]:
            if not _regions_share_structural_raster_view(
                report=report,
                profile_inventory=profile_inventory,
                view_lookup=view_lookup,
                first_region_id=left_region,
                second_region_id=right_region,
            ):
                continue

            left_edges = eligible_by_region[left_region]
            right_edges = eligible_by_region[right_region]
            right_candidates_by_left: dict[str, list[str]] = {}
            left_candidates_by_right: dict[str, list[str]] = {}
            for left in left_edges:
                left_ref = str(left["ref"])
                for right in right_edges:
                    right_ref = str(right["ref"])
                    if not pair_matches(left, right):
                        continue
                    right_candidates_by_left.setdefault(left_ref, []).append(
                        right_ref
                    )
                    left_candidates_by_right.setdefault(right_ref, []).append(
                        left_ref
                    )

            for left_ref, right_refs in sorted(right_candidates_by_left.items()):
                unique_rights = sorted(set(right_refs))
                if len(unique_rights) != 1:
                    continue
                right_ref = unique_rights[0]
                unique_lefts = sorted(
                    set(left_candidates_by_right.get(right_ref, []))
                )
                if unique_lefts != [left_ref]:
                    continue
                graph.setdefault(left_ref, set()).add(right_ref)
                graph.setdefault(right_ref, set()).add(left_ref)

    associations: list[ObservationAssociation] = []
    visited: set[str] = set()
    for seed in sorted(graph):
        if seed in visited:
            continue
        stack = [seed]
        component: list[str] = []
        while stack:
            ref = stack.pop()
            if ref in visited:
                continue
            visited.add(ref)
            component.append(ref)
            stack.extend(sorted(graph.get(ref, set()) - visited, reverse=True))
        if len(component) < 2:
            continue

        regions_in_component = [ref_region[ref] for ref in component]
        if len(regions_in_component) != len(set(regions_in_component)):
            continue

        refs = sorted(component)
        entity_keys = [profile_entity_by_ref[ref] for ref in refs]
        digest = hashlib.sha256("|".join(refs).encode("utf-8")).hexdigest()[:12]
        associations.append(
            ObservationAssociation(
                entity_keys=entity_keys,
                basis=["shared_raster_profile_identity"],
                evidence=[
                    f"hybrid:shared-raster-profile:{digest}",
                    *[f"hybrid:profile-edge:{ref}" for ref in refs],
                ],
                required_for_modeling=False,
            )
        )

    return associations


def _selected_witness_pair(
    candidate: dict[str, Any],
) -> list[float] | None:
    endpoint_evidence = derive_dimension_endpoint_candidates(candidate)
    raw = endpoint_evidence.get("selected_witness_positions_px")
    if not (
        isinstance(raw, list)
        and len(raw) == 2
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in raw
        )
    ):
        return None
    return [float(value) for value in raw]


def _projected_profile_level_records(
    *,
    candidate: dict[str, Any],
    dimension_key: str,
    axis: Axis,
    dimension_endpoints: list[ObservationDimensionEndpoint],
    boundary_roles: dict[str, Literal["overall_min", "overall_max"]],
    profile_entity_by_ref: dict[str, str],
) -> list[dict[str, Any]]:
    """Record extension-line projection onto one structural profile coordinate.

    Pixel coordinates establish only that an unresolved witness and a
    structurally validated profile edge share the same measured-axis level.
    The record never converts raster position into engineering units.
    """

    if len(dimension_endpoints) != 2:
        return []

    endpoint_evidence = derive_dimension_endpoint_candidates(candidate)
    raw_endpoints = endpoint_evidence.get("endpoints")
    witness_positions = endpoint_evidence.get("selected_witness_positions_px")
    if not (
        isinstance(raw_endpoints, list)
        and len(raw_endpoints) == 2
        and isinstance(witness_positions, list)
        and len(witness_positions) == 2
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in witness_positions
        )
    ):
        return []

    orientation = str(candidate.get("orientation") or "")
    expected_profile_orientation = {
        "horizontal": "vertical",
        "vertical": "horizontal",
    }.get(orientation)
    if expected_profile_orientation is None:
        return []

    witness_lines_by_index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for witness in candidate.get("witness_line_evidence", []):
        if not isinstance(witness, dict):
            continue
        witness_index = witness.get("witness_index")
        if not isinstance(witness_index, int) or isinstance(witness_index, bool):
            continue
        witness_lines_by_index[witness_index].extend(
            item
            for item in witness.get("source_lines", [])
            if isinstance(item, dict)
        )

    candidate_id = str(candidate.get("candidate_id") or "")
    region_id = str(candidate.get("region_id") or "")
    if not candidate_id or not region_id:
        return []

    output: list[dict[str, Any]] = []
    for endpoint_index, (observed, raw_endpoint) in enumerate(
        zip(dimension_endpoints, raw_endpoints, strict=True)
    ):
        if (
            observed.role != "unresolved"
            or observed.unresolved_kind != "intermediate_surface"
            or not isinstance(raw_endpoint, dict)
        ):
            continue

        witness_position = float(witness_positions[endpoint_index])
        eligible: list[dict[str, Any]] = []
        for anchor in raw_endpoint.get("ignored_nonownership_anchors", []):
            if not isinstance(anchor, dict):
                continue
            if anchor.get("kind") != "profile_edge_candidate":
                continue
            if (
                anchor.get("ownership_rejection_reason")
                != "profile_not_connected_to_witness_terminal"
            ):
                continue
            if (
                str(anchor.get("source_orientation") or "")
                != expected_profile_orientation
            ):
                continue

            ref = str(anchor.get("ref") or "")
            position = anchor.get("position_px")
            axis_tolerance = anchor.get("axis_tolerance_px")
            junction_count = anchor.get("junction_count")
            endpoint_junction_count = anchor.get("endpoint_junction_count")
            independent_count = anchor.get(
                "non_dimension_crossing_source_count"
            )
            if (
                not ref
                or not isinstance(position, (int, float))
                or isinstance(position, bool)
                or not isinstance(axis_tolerance, (int, float))
                or isinstance(axis_tolerance, bool)
                or not isinstance(junction_count, int)
                or isinstance(junction_count, bool)
                or junction_count < 2
                or not isinstance(endpoint_junction_count, int)
                or isinstance(endpoint_junction_count, bool)
                or endpoint_junction_count < 2
                or not isinstance(independent_count, int)
                or isinstance(independent_count, bool)
                or independent_count <= 0
            ):
                continue
            tolerance = max(2.0, float(axis_tolerance))
            if abs(float(position) - witness_position) > tolerance:
                continue

            crossing_support = any(
                line.get("crosses_dimension_axis") is True
                and str(line.get("orientation") or "")
                == expected_profile_orientation
                and isinstance(line.get("axis_px"), (int, float))
                and not isinstance(line.get("axis_px"), bool)
                and abs(float(line["axis_px"]) - witness_position)
                <= tolerance
                for line in witness_lines_by_index.get(endpoint_index, [])
            )
            if not crossing_support:
                continue

            eligible.append(
                {
                    "ref": ref,
                    "position_px": float(position),
                    "tolerance_px": tolerance,
                }
            )

        if not eligible:
            continue

        eligible.sort(key=lambda item: item["position_px"])
        clusters: list[list[dict[str, Any]]] = []
        for item in eligible:
            if not clusters:
                clusters.append([item])
                continue
            previous = clusters[-1][-1]
            cluster_tolerance = max(
                float(previous["tolerance_px"]),
                float(item["tolerance_px"]),
            )
            if (
                abs(float(item["position_px"]) - float(previous["position_px"]))
                <= cluster_tolerance
            ):
                clusters[-1].append(item)
            else:
                clusters.append([item])

        if len(clusters) != 1:
            continue
        cluster = clusters[0]
        refs = sorted({str(item["ref"]) for item in cluster})
        if not refs:
            continue
        if any(ref not in profile_entity_by_ref for ref in refs):
            continue
        profile_entity_keys = sorted(
            {profile_entity_by_ref[ref] for ref in refs}
        )
        if not profile_entity_keys:
            continue

        roles = {
            boundary_roles[ref]
            for ref in refs
            if ref in boundary_roles
        }
        if len(roles) > 1:
            continue
        overall_role = next(iter(roles)) if roles else None
        profile_position = sum(
            float(item["position_px"]) for item in cluster
        ) / len(cluster)
        residual = abs(profile_position - witness_position)

        output.append(
            {
                "dimension_key": dimension_key,
                "candidate_id": candidate_id,
                "region_id": region_id,
                "endpoint_index": endpoint_index,
                "axis": axis,
                "witness_position_px": witness_position,
                "profile_position_px": round(profile_position, 3),
                "profile_refs": refs,
                "profile_entity_keys": profile_entity_keys,
                "overall_role": overall_role,
                "projection_residual_px": round(residual, 3),
                "basis": (
                    "extension_line_projection_to_structural_profile_level"
                ),
                "source_ids": _candidate_evidence(candidate_id),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            }
        )

    return output


def _profile_span_center_record(
    *,
    candidate: dict[str, Any],
    dimension_key: str,
    axis: Axis,
    dimension_endpoints: list[ObservationDimensionEndpoint],
) -> dict[str, Any] | None:
    """Describe one resolved profile span center as raster identity only."""

    if not (
        len(dimension_endpoints) == 2
        and all(item.role == "profile_boundary" for item in dimension_endpoints)
        and all(item.entity_key for item in dimension_endpoints)
        and dimension_endpoints[0].entity_key != dimension_endpoints[1].entity_key
    ):
        return None

    witness_pair = _selected_witness_pair(candidate)
    if witness_pair is None:
        return None
    witness_low, witness_high = sorted(witness_pair)
    if witness_high <= witness_low:
        return None

    candidate_id = str(candidate.get("candidate_id") or "")
    region_id = str(candidate.get("region_id") or "")
    if not candidate_id or not region_id:
        return None

    return {
        "dimension_key": dimension_key,
        "candidate_id": candidate_id,
        "region_id": region_id,
        "axis": axis,
        "profile_entity_keys": [
            str(dimension_endpoints[0].entity_key),
            str(dimension_endpoints[1].entity_key),
        ],
        "selected_witness_positions_px": [witness_low, witness_high],
        "span_midpoint_px": (witness_low + witness_high) / 2.0,
        "source_ids": _candidate_evidence(candidate_id),
        "basis": "resolved_profile_boundary_span_midpoint",
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }


def _dimension_span_center_identity_records(
    *,
    dimensions: list[ObservationDimension],
    candidates: list[dict[str, Any]],
    profile_span_records: list[dict[str, Any]],
    report: dict[str, Any],
    view_lookup: dict[str, HybridRegionView],
    profile_inventory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match unresolved dimension witnesses to unique resolved span midpoints."""

    candidate_by_dimension_key = {
        f"{str(item.get('region_id') or '')}.{str(item.get('candidate_id') or '')}": item
        for item in candidates
        if str(item.get("region_id") or "")
        and str(item.get("candidate_id") or "")
        and item.get("accepted_token") is not None
    }
    output: list[dict[str, Any]] = []

    for dimension in dimensions:
        if not any(endpoint.role == "unresolved" for endpoint in dimension.endpoints):
            continue
        candidate = candidate_by_dimension_key.get(dimension.key)
        if candidate is None:
            continue
        witness_pair = _selected_witness_pair(candidate)
        if witness_pair is None:
            continue
        region_id = str(candidate.get("region_id") or "")
        if not region_id:
            continue

        for endpoint_index, endpoint in enumerate(dimension.endpoints):
            if endpoint.role != "unresolved":
                continue
            if endpoint.unresolved_kind == "ambiguous_owner":
                continue

            witness_position = witness_pair[endpoint_index]
            matches: list[dict[str, Any]] = []
            for span in profile_span_records:
                if span.get("axis") != dimension.axis:
                    continue
                span_dimension_key = str(span.get("dimension_key") or "")
                span_region_id = str(span.get("region_id") or "")
                if (
                    not span_dimension_key
                    or not span_region_id
                    or span_dimension_key == dimension.key
                ):
                    continue
                same_raster_view = region_id == span_region_id
                if not same_raster_view:
                    same_raster_view = _regions_share_structural_raster_view(
                        report=report,
                        profile_inventory=profile_inventory,
                        view_lookup=view_lookup,
                        first_region_id=region_id,
                        second_region_id=span_region_id,
                    )
                if not same_raster_view:
                    continue

                raw_span_pair = span.get("selected_witness_positions_px")
                span_midpoint = span.get("span_midpoint_px")
                if not (
                    isinstance(raw_span_pair, list)
                    and len(raw_span_pair) == 2
                    and all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        for value in raw_span_pair
                    )
                    and isinstance(span_midpoint, (int, float))
                    and not isinstance(span_midpoint, bool)
                ):
                    continue
                span_low, span_high = sorted(float(value) for value in raw_span_pair)
                span_width = span_high - span_low
                if span_width <= 0:
                    continue
                tolerance = max(2.0, span_width * 0.015)
                residual = abs(witness_position - float(span_midpoint))
                if residual > tolerance:
                    continue
                matches.append(
                    {
                        "span_dimension_key": span_dimension_key,
                        "span_region_id": span_region_id,
                        "span_midpoint_px": float(span_midpoint),
                        "midpoint_residual_px": residual,
                        "midpoint_tolerance_px": tolerance,
                        "source_ids": [
                            item
                            for item in span.get("source_ids", [])
                            if isinstance(item, str) and item
                        ],
                    }
                )

            if len(matches) != 1:
                continue

            match = matches[0]
            candidate_id = str(candidate.get("candidate_id") or "")
            output.append(
                {
                    "dimension_key": dimension.key,
                    "endpoint_index": endpoint_index,
                    "axis": dimension.axis,
                    "witness_position_px": witness_position,
                    "span_dimension_key": match["span_dimension_key"],
                    "span_region_id": match["span_region_id"],
                    "span_midpoint_px": match["span_midpoint_px"],
                    "midpoint_residual_px": round(
                        float(match["midpoint_residual_px"]),
                        3,
                    ),
                    "midpoint_tolerance_px": round(
                        float(match["midpoint_tolerance_px"]),
                        3,
                    ),
                    "basis": "unique_witness_to_resolved_profile_span_midpoint",
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *_candidate_evidence(candidate_id),
                                *match["source_ids"],
                            ]
                        )
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_identity_only": True,
                }
            )

    return output


def _symmetric_local_section_feature_records(
    *,
    dimensions: list[ObservationDimension],
    profile_span_records: list[dict[str, Any]],
    span_center_identity_records: list[dict[str, Any]],
    symmetric_dimension_pair_records: list[dict[str, Any]],
    profile_entity_by_ref: dict[str, str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Separate local symmetric section features from the rotational body profile.

    A local profile span whose midpoint is uniquely reused as one endpoint of a
    second dimension centered on the overall datum is not a global body-profile
    span.  It is a local paired section feature whose eventual 3D representation
    may be a discrete hole/slot pair, an annular groove, or another local
    subtractive/additive feature.  This helper preserves only that identity.

    Pixel positions prove midpoint identity/symmetry only.  Width and center
    distance remain OCR engineering values; no pixel distance becomes metric
    geometry.  Until a later feature classifier resolves the 3D representation,
    the involved profile refs must not be consumed as the primary rotational
    body silhouette.
    """

    dimension_by_key = {dimension.key: dimension for dimension in dimensions}
    spans_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in profile_span_records:
        if not isinstance(record, dict):
            continue
        key = str(record.get("dimension_key") or "")
        if key:
            spans_by_key[key].append(record)

    symmetric_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in symmetric_dimension_pair_records:
        if not isinstance(record, dict):
            continue
        key = str(record.get("dimension_key") or "")
        if key:
            symmetric_by_key[key].append(record)

    refs_by_entity: dict[str, list[str]] = defaultdict(list)
    for ref, entity_key in profile_entity_by_ref.items():
        if ref and entity_key:
            refs_by_entity[str(entity_key)].append(str(ref))

    output: list[dict[str, Any]] = []
    excluded_refs: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()

    for identity in span_center_identity_records:
        if (
            not isinstance(identity, dict)
            or identity.get("basis")
            != "unique_witness_to_resolved_profile_span_midpoint"
            or identity.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or identity.get("pixel_geometry_used_for_identity_only") is not True
        ):
            continue

        center_key = str(identity.get("dimension_key") or "")
        span_key = str(identity.get("span_dimension_key") or "")
        pair_key = (span_key, center_key)
        if (
            not span_key
            or not center_key
            or span_key == center_key
            or pair_key in seen_pairs
        ):
            continue

        span_dimension = dimension_by_key.get(span_key)
        center_dimension = dimension_by_key.get(center_key)
        span_records = spans_by_key.get(span_key, [])
        center_symmetry = [
            record
            for record in symmetric_by_key.get(center_key, [])
            if record.get("datum") == "overall_center"
            and record.get("engineering_coordinate_inferred_from_pixels")
            is False
            and record.get("pixel_geometry_used_for_identity_only") is True
        ]
        if (
            span_dimension is None
            or center_dimension is None
            or len(span_records) != 1
            or len(center_symmetry) != 1
            or symmetric_by_key.get(span_key)
        ):
            continue
        if (
            span_dimension.axis != center_dimension.axis
            or str(center_symmetry[0].get("axis") or "")
            != center_dimension.axis
            or not (0.0 < span_dimension.value < center_dimension.value)
            or not any(
                endpoint.role == "unresolved"
                for endpoint in center_dimension.endpoints
            )
        ):
            continue
        if not all(
            endpoint.role == "profile_boundary" and endpoint.entity_key
            for endpoint in span_dimension.endpoints
        ):
            continue

        span_record = span_records[0]
        span_entity_keys = [
            str(value)
            for value in span_record.get("profile_entity_keys", [])
            if isinstance(value, str) and value
        ]
        endpoint_entity_keys = [
            str(endpoint.entity_key)
            for endpoint in span_dimension.endpoints
            if endpoint.entity_key
        ]
        if (
            len(span_entity_keys) != 2
            or len(set(span_entity_keys)) != 2
            or set(span_entity_keys) != set(endpoint_entity_keys)
        ):
            continue

        profile_refs: list[str] = []
        valid_refs = True
        for entity_key in span_entity_keys:
            matches = sorted(set(refs_by_entity.get(entity_key, [])))
            if len(matches) != 1:
                valid_refs = False
                break
            profile_refs.append(matches[0])
        if not valid_refs or len(set(profile_refs)) != 2:
            continue

        raw_center_value = center_symmetry[0].get("dimension_value")
        if (
            not isinstance(raw_center_value, (int, float))
            or isinstance(raw_center_value, bool)
            or not math.isclose(
                float(raw_center_value),
                float(center_dimension.value),
                abs_tol=max(abs(float(center_dimension.value)) * 1e-6, 1e-9),
            )
        ):
            continue

        source_ids = list(
            dict.fromkeys(
                [
                    *span_dimension.evidence,
                    *center_dimension.evidence,
                    *[
                        value
                        for value in span_record.get("source_ids", [])
                        if isinstance(value, str) and value
                    ],
                    *[
                        value
                        for value in identity.get("source_ids", [])
                        if isinstance(value, str) and value
                    ],
                    *[
                        value
                        for value in center_symmetry[0].get("source_ids", [])
                        if isinstance(value, str) and value
                    ],
                ]
            )
        )
        digest = hashlib.sha1(
            f"{span_key}|{center_key}".encode("utf-8")
        ).hexdigest()[:16].upper()

        output.append(
            {
                "id": f"LOCAL_SECTION_PAIR_{digest}",
                "axis": span_dimension.axis,
                "span_dimension_key": span_key,
                "center_distance_dimension_key": center_key,
                "span_width": float(span_dimension.value),
                "center_distance": float(center_dimension.value),
                "matched_center_endpoint_index": identity.get(
                    "endpoint_index"
                ),
                "profile_entity_keys": span_entity_keys,
                "profile_refs": sorted(profile_refs),
                "representation_status": "unresolved_3d_representation",
                "count_status": "unresolved",
                "excluded_from_rotational_body_profile": True,
                "basis": (
                    "resolved_local_profile_span_plus_unique_"
                    "span_midpoint_endpoint_plus_overall_center_symmetry"
                ),
                "source_ids": source_ids,
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_identity_only": True,
            }
        )
        excluded_refs.update(profile_refs)
        seen_pairs.add(pair_key)

    output.sort(key=lambda item: str(item.get("id") or ""))
    return output, excluded_refs


def _symmetric_dimension_pair_record(
    *,
    candidate: dict[str, Any],
    dimension_key: str,
    dimension_value: float,
    axis: Axis,
    candidates: list[dict[str, Any]],
    report: dict[str, Any],
    context: HybridAdapterContext,
    view_lookup: dict[str, HybridRegionView],
    profile_inventory: list[dict[str, Any]],
    overall_dimensions: dict[str, float],
) -> dict[str, Any] | None:
    """Prove only that a dimension witness pair is centered on the overall datum.

    Raster geometry establishes identity/symmetry only. No endpoint ownership
    and no engineering coordinate are inferred here.
    """

    region_id = str(candidate.get("region_id") or "")
    if not region_id or region_id not in view_lookup:
        return None

    overall_key = {"X": "length_x", "Y": "width_y", "Z": "height_z"}[axis]
    overall_value = overall_dimensions.get(overall_key)
    if (
        not isinstance(overall_value, (int, float))
        or isinstance(overall_value, bool)
        or float(overall_value) <= 0
        or dimension_value <= 0
        or dimension_value >= float(overall_value) - 1e-9
    ):
        return None

    witness_pair = _selected_witness_pair(candidate)
    if witness_pair is None:
        return None
    witness_low, witness_high = sorted(witness_pair)
    witness_midpoint = (witness_low + witness_high) / 2.0

    anchors: list[dict[str, Any]] = []
    for overall_candidate in candidates:
        accepted_token = overall_candidate.get("accepted_token")
        anchor_region_id = str(overall_candidate.get("region_id") or "")
        if not isinstance(accepted_token, str) or not anchor_region_id:
            continue
        anchor_view = view_lookup.get(anchor_region_id)
        if anchor_view is None:
            continue
        try:
            anchor_axis = _axis_for(
                anchor_view.view_kind,
                str(overall_candidate.get("orientation") or ""),
            )
            anchor_value, _ = _dimension_value(accepted_token)
        except HybridCaptureAdapterError:
            continue
        if anchor_axis != axis or not math.isclose(
            anchor_value,
            float(overall_value),
            abs_tol=max(abs(float(overall_value)) * 1e-6, 1e-9),
        ):
            continue
        if not _region_has_rotational_symmetry(
            context,
            region_id=anchor_region_id,
            dimension_axis=axis,
        ):
            continue
        if not _regions_share_structural_raster_view(
            report=report,
            profile_inventory=profile_inventory,
            view_lookup=view_lookup,
            first_region_id=region_id,
            second_region_id=anchor_region_id,
        ):
            continue

        anchor_pair = _selected_witness_pair(overall_candidate)
        if anchor_pair is None:
            continue
        anchor_low, anchor_high = sorted(anchor_pair)
        anchor_span = anchor_high - anchor_low
        if (
            anchor_span <= 0
            or witness_low < anchor_low
            or witness_high > anchor_high
        ):
            continue
        anchor_midpoint = (anchor_low + anchor_high) / 2.0
        midpoint_tolerance = max(2.0, anchor_span * 0.015)
        midpoint_residual = abs(witness_midpoint - anchor_midpoint)
        if midpoint_residual > midpoint_tolerance:
            continue
        anchors.append(
            {
                "candidate_id": str(overall_candidate.get("candidate_id") or ""),
                "region_id": anchor_region_id,
                "witness_positions_px": [anchor_low, anchor_high],
                "midpoint_residual_px": midpoint_residual,
                "midpoint_tolerance_px": midpoint_tolerance,
            }
        )

    if len(anchors) != 1:
        return None

    anchor = anchors[0]
    candidate_id = str(candidate.get("candidate_id") or "")
    symmetry_evidence: list[str] = []
    for fact in context.rotational_symmetry_facts:
        if fact.axis == axis:
            continue
        if set(fact.evidence) & {
            evidence
            for region in context.region_views
            if region.region_id in {region_id, anchor["region_id"]}
            for evidence in region.evidence
        }:
            symmetry_evidence.extend(fact.evidence)

    return {
        "dimension_key": dimension_key,
        "candidate_id": candidate_id,
        "region_id": region_id,
        "axis": axis,
        "datum": "overall_center",
        "dimension_value": dimension_value,
        "overall_dimension_value": float(overall_value),
        "selected_witness_positions_px": [witness_low, witness_high],
        "overall_candidate_id": anchor["candidate_id"],
        "overall_region_id": anchor["region_id"],
        "overall_witness_positions_px": anchor["witness_positions_px"],
        "midpoint_residual_px": round(float(anchor["midpoint_residual_px"]), 3),
        "midpoint_tolerance_px": round(float(anchor["midpoint_tolerance_px"]), 3),
        "basis": (
            "rotational_symmetry_anchor_plus_structurally_shared_raster_view"
            "_plus_overall_witness_midpoint"
        ),
        "symmetry_region_id": anchor["region_id"],
        "source_ids": list(
            dict.fromkeys(
                [
                    *_candidate_evidence(candidate_id),
                    f"hybrid:{anchor['candidate_id']}:overall-center-anchor",
                    *symmetry_evidence,
                ]
            )
        ),
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }


def _symmetric_profile_span_record(
    *,
    candidate: dict[str, Any],
    dimension_key: str,
    dimension_value: float,
    axis: Axis,
    dimension_endpoints: list[ObservationDimensionEndpoint],
    candidates: list[dict[str, Any]],
    report: dict[str, Any],
    context: HybridAdapterContext,
    view_lookup: dict[str, HybridRegionView],
    profile_inventory: list[dict[str, Any]],
    overall_dimensions: dict[str, float],
) -> dict[str, Any] | None:
    """Prove that a resolved profile span is symmetric about the overall center."""

    if not (
        len(dimension_endpoints) == 2
        and all(item.role == "profile_boundary" for item in dimension_endpoints)
        and all(item.entity_key for item in dimension_endpoints)
        and dimension_endpoints[0].entity_key != dimension_endpoints[1].entity_key
    ):
        return None

    record = _symmetric_dimension_pair_record(
        candidate=candidate,
        dimension_key=dimension_key,
        dimension_value=dimension_value,
        axis=axis,
        candidates=candidates,
        report=report,
        context=context,
        view_lookup=view_lookup,
        profile_inventory=profile_inventory,
        overall_dimensions=overall_dimensions,
    )
    if record is None:
        return None

    return {
        **record,
        "profile_entity_keys": [
            str(dimension_endpoints[0].entity_key),
            str(dimension_endpoints[1].entity_key),
        ],
    }


_CROSS_REGION_ENDPOINT_STATUS_RANK = {
    "no_physical_candidate": 0,
    "ambiguous_physical_candidates": 1,
    "unique_physical_candidate": 2,
}


def _cross_region_variant_endpoint_rank(
    candidate: dict[str, Any],
) -> tuple[int, int] | None:
    accepted_token = candidate.get("accepted_token")
    assignments = candidate.get("global_assignments")
    if not isinstance(accepted_token, str) or not isinstance(assignments, list):
        return None

    evidence = derive_dimension_endpoint_candidates(candidate)
    endpoints = evidence.get("endpoints")
    if evidence.get("status") != "bracketed" or not (
        isinstance(endpoints, list) and len(endpoints) == 2
    ):
        return None

    ranks: list[int] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            return None
        rank = _CROSS_REGION_ENDPOINT_STATUS_RANK.get(
            str(endpoint.get("status") or "")
        )
        if rank is None:
            return None
        ranks.append(rank)
    return (ranks[0], ranks[1])


def _select_cross_region_candidate_variant(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Choose a region-scoped duplicate only under strict evidence dominance.

    Exact-geometry deduplication is an OCR optimization, not permission to mix
    ownership anchors from different deterministic regions.  A non-canonical
    source region may replace the representative only when its two selected
    endpoint statuses are component-wise no worse than every alternative and
    strictly better than at least one.  Ties or crossed advantages retain the
    canonical representative and therefore fail closed downstream.
    """

    variants = candidate.get("source_candidate_variants")
    if not isinstance(variants, list) or len(variants) <= 1:
        return candidate

    evaluated: list[tuple[dict[str, Any], tuple[int, int]]] = []
    for raw_variant in variants:
        if not isinstance(raw_variant, dict):
            continue
        variant = {
            **raw_variant,
            "accepted_token": candidate.get("accepted_token"),
            "global_assignments": candidate.get("global_assignments", []),
        }
        rank = _cross_region_variant_endpoint_rank(variant)
        if rank is not None:
            evaluated.append((variant, rank))

    if len(evaluated) <= 1:
        return candidate

    winners: list[tuple[dict[str, Any], tuple[int, int]]] = []
    for index, (variant, rank) in enumerate(evaluated):
        others = [
            other_rank
            for other_index, (_, other_rank) in enumerate(evaluated)
            if other_index != index
        ]
        if not others:
            continue
        no_worse_than_all = all(
            rank[0] >= other[0] and rank[1] >= other[1]
            for other in others
        )
        strictly_better_than_one = any(
            rank[0] > other[0] or rank[1] > other[1]
            for other in others
        )
        if no_worse_than_all and strictly_better_than_one:
            winners.append((variant, rank))

    if len(winners) != 1:
        return candidate

    selected, selected_rank = winners[0]
    selected_source_candidate_id = str(selected.get("candidate_id") or "")
    selected_source_region_id = str(selected.get("region_id") or "")
    if not selected_source_candidate_id or not selected_source_region_id:
        return candidate

    return {
        **candidate,
        "region_id": selected_source_region_id,
        "witness_anchor_evidence": selected.get(
            "witness_anchor_evidence",
            [],
        ),
        "witness_line_evidence": selected.get(
            "witness_line_evidence",
            [],
        ),
        "selected_source_candidate_id": selected_source_candidate_id,
        "selected_source_region_id": selected_source_region_id,
        "cross_region_variant_selection_basis": (
            "strict_selected_endpoint_evidence_dominance"
        ),
        "cross_region_variant_endpoint_rank": list(selected_rank),
    }


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
    raw_profile_inventory = report.get("structural_profile_inventory")
    profile_inventory: list[dict[str, Any]] = (
        [item for item in raw_profile_inventory if isinstance(item, dict)]
        if isinstance(raw_profile_inventory, list)
        else []
    )
    selected_candidates = [
        _select_cross_region_candidate_variant(item)
        for item in candidates
        if isinstance(item, dict)
    ]
    working_candidates = [
        _enrich_candidate_from_profile_inventory(
            item,
            report=report,
            profile_inventory=profile_inventory,
        )
        for item in selected_candidates
    ]
    overall_dimensions = {
        {"X": "length_x", "Y": "width_y", "Z": "height_z"}[fact.axis]: fact.value
        for fact in context.overall_dimension_facts
    }
    region_overall_fact_axes = _region_overall_fact_axes(context)
    boundaries = derive_view_axis_boundaries(
        candidates=working_candidates,
        region_views={item.region_id: item.view_kind for item in context.region_views},
        overall_dimensions=overall_dimensions,
        profile_inventory=profile_inventory,
        region_overall_fact_axes=region_overall_fact_axes,
    )
    boundary_roles = _boundary_role_lookup(boundaries)
    labeled_dimension_facts = _reconcile_labeled_dimension_relations(
        report=report,
        facts=context.labeled_dimension_facts,
        view_lookup=view_lookup,
        boundaries=boundaries,
    )

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
    symmetric_pair_records: list[dict[str, Any]] = []
    symmetric_dimension_pair_records: list[dict[str, Any]] = []
    projected_profile_level_records: list[dict[str, Any]] = []
    profile_span_center_records: list[dict[str, Any]] = []
    symmetric_profile_span_records: list[dict[str, Any]] = []
    unresolved: list[ObservationUnresolved] = []
    entities = _circle_entities(report, view_lookup)
    profile_entities, profile_entity_by_ref = _profile_boundary_entities(
        profile_inventory,
        view_lookup,
    )
    entities.extend(profile_entities)
    profile_vertex_entities, profile_vertex_entity_by_ref = (
        _profile_vertex_entities(
            dimension_candidates,
            view_lookup,
        )
    )
    entities.extend(profile_vertex_entities)

    metric_profile_topology_hints = _metric_profile_topology_hints(
        report=report,
        profile_inventory=profile_inventory,
        view_lookup=view_lookup,
        boundaries=boundaries,
        profile_entity_by_ref=profile_entity_by_ref,
    )

    rotational_oblique_profile_hints = _rotational_oblique_profile_hints(
        report=report,
        profile_inventory=profile_inventory,
        view_lookup=view_lookup,
        context=context,
        profile_entity_by_ref=profile_entity_by_ref,
    )

    labeled_profile_transition_boundary_ledger = (
        _labeled_profile_transition_boundary_records(
            report=report,
            facts=labeled_dimension_facts,
            view_lookup=view_lookup,
            boundaries=boundaries,
            profile_inventory=profile_inventory,
            profile_entity_by_ref=profile_entity_by_ref,
            rotational_oblique_profile_hints=(
                rotational_oblique_profile_hints
            ),
        )
    )

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
    hidden_pattern_candidates: dict[tuple[str, int], set[str]] = {}
    for entity_key, record in hidden_entity_records.items():
        region_id = entity_key.split(".", 1)[0]
        for raw_index in record.get("source_pattern_indices", []):
            if not isinstance(raw_index, int):
                continue
            hidden_pattern_candidates.setdefault(
                (region_id, raw_index),
                set(),
            ).add(entity_key)
    hidden_pattern_owner_by_index = {
        key: next(iter(owners))
        for key, owners in hidden_pattern_candidates.items()
        if len(owners) == 1
    }

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

    (
        callout_ledger,
        callout_entities,
        callout_values,
        callout_unresolved,
    ) = _engineering_callout_routing(
        report,
        working_candidates,
        view_lookup,
        hidden_pattern_owner_by_index=hidden_pattern_owner_by_index,
        existing_entity_keys={item.key for item in entities},
        profile_inventory=profile_inventory,
        verified_profile_arc_sources={
            source
            for hint in rotational_oblique_profile_hints
            if (
                hint.get("primitive_kind") == "arc"
                and hint.get("support_status") == "verified"
                and hint.get("primitive_kind_basis")
                == (
                    "verified_continuous_curved_raster_segment_"
                    "between_structural_contacts"
                )
                and hint.get("engineering_coordinate_inferred_from_pixels")
                is False
                and hint.get("pixel_geometry_used_for_topology_only") is True
            )
            for source in hint.get("source_ids", [])
            if (
                isinstance(source, str)
                and source.startswith("hybrid:curve-boundary:")
            )
        },
        excluded_source_item_indices={
            fact.source_item_index for fact in labeled_dimension_facts
        },
    )
    entities.extend(callout_entities)
    unresolved.extend(callout_unresolved)

    centerline_alignments, centerline_alignment_ledger = (
        _unique_thread_recess_centerline_alignments(
            report=report,
            view_lookup=view_lookup,
            hidden_entity_records=hidden_entity_records,
            callout_values=callout_values,
            entity_keys={item.key for item in entities},
        )
    )
    recess_start_side_values, recess_start_side_ledger = (
        _transverse_recess_start_side_values(
            report=report,
            view_lookup=view_lookup,
            boundaries=boundaries,
            hidden_entity_records=hidden_entity_records,
            callout_values=callout_values,
            centerline_alignments=centerline_alignments,
        )
    )
    confirmed_start_side_values, confirmed_start_side_ledger = (
        _confirmed_start_side_values(
            context,
            entity_keys={item.key for item in entities},
            existing_values=[
                *callout_values,
                *recess_start_side_values,
            ],
        )
    )
    unresolved.extend(
        _missing_transverse_thread_start_side_unresolved(
            values=[
                *geometry_values,
                *callout_values,
                *recess_start_side_values,
                *confirmed_start_side_values,
            ],
        )
    )
    (
        slot_entities,
        slot_values,
        slot_unresolved,
        slot_ledger,
        slot_claimed_source_indices,
    ) = _open_slot_observations(
        report=report,
        candidates=dimension_candidates,
        view_lookup=view_lookup,
        boundaries=boundaries,
        overall_dimension_facts=context.overall_dimension_facts,
    )
    entities.extend(slot_entities)
    unresolved.extend(slot_unresolved)

    pattern_entity_by_ref: dict[str, str] = {}
    for record in callout_ledger:
        if not isinstance(record, dict):
            continue
        binding = record.get("binding")
        if not isinstance(binding, dict) or binding.get("status") != "pattern_backed":
            continue
        region_id = str(binding.get("region_id") or "")
        pattern_index = binding.get("pattern_index")
        entity_key = str(binding.get("entity_key") or "")
        if (
            region_id
            and isinstance(pattern_index, int)
            and entity_key in {item.key for item in entities}
        ):
            pattern_entity_by_ref[
                f"{region_id}.linear_pattern.{pattern_index + 1:03d}"
            ] = entity_key

    circle_alignment_records = derive_circle_overall_center_alignments(
        regions=[
            item for item in report.get("regions", []) if isinstance(item, dict)
        ],
        region_views={item.region_id: item.view_kind for item in context.region_views},
        boundaries=boundaries,
        profile_inventory=profile_inventory,
        candidates=working_candidates,
    )
    datum_alignments: list[ObservationDatumAlignment] = [
        ObservationDatumAlignment(
            entity_key=str(record["entity_key"]),
            axis=record["axis"],
            evidence=[
                (
                    "hybrid:circle-datum:"
                    f"{record['entity_key']}:{record['axis']}"
                ),
                str(record.get("axis_line_ref") or "circle-center-axis"),
            ],
            required_for_modeling=True,
        )
        for record in circle_alignment_records
        if str(record.get("entity_key") or "")
        in {item.key for item in entities}
        and record.get("axis") in {"X", "Y", "Z"}
        and record.get("engineering_coordinate_inferred_from_pixels") is False
    ]

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

        symmetric_pair = _symmetric_count_two_pattern_owner(
            raw_candidate,
            region_view=region_view,
            axis=axis,
            boundaries=boundaries,
            callout_ledger=callout_ledger,
            entity_keys={item.key for item in entities},
        )
        dimension_evidence = list(evidence)
        if symmetric_pair is not None:
            dimension_evidence.append(_SYMMETRIC_COUNT_TWO_MARKER)
            owner = str(symmetric_pair["entity_key"])
            dimension_endpoints = [
                ObservationDimensionEndpoint(
                    role="entity_center",
                    entity_key=owner,
                    basis="centerline",
                    evidence=dimension_evidence,
                ),
                ObservationDimensionEndpoint(
                    role="entity_center",
                    entity_key=owner,
                    basis="centerline",
                    evidence=dimension_evidence,
                ),
            ]
            unresolved_reason = None
            symmetric_pair_records.append(
                {
                    "dimension_key": dimension_key,
                    "evidence": list(dimension_evidence),
                    **symmetric_pair,
                }
            )
        else:
            dimension_endpoints, unresolved_reason = _dimension_endpoints_from_candidates(
                raw_candidate,
                entity_keys={item.key for item in entities},
                boundary_roles=boundary_roles,
                profile_entity_by_ref=profile_entity_by_ref,
                profile_vertex_entity_by_ref=profile_vertex_entity_by_ref,
                pattern_entity_by_ref=pattern_entity_by_ref,
                evidence=evidence,
            )
            if _full_extent_roles_disagree_with_declared_overall(
                dimension_endpoints,
                axis=axis,
                value=value,
                overall_dimensions=overall_dimensions,
            ):
                # A local dimension cannot legitimately span both declared
                # overall boundaries while carrying a different engineering
                # value.  Keep the same witness/candidate evidence but remove
                # global-boundary ownership and fall back to profile ownership
                # (or unresolved) instead of manufacturing contradictory
                # overall evidence.
                dimension_endpoints, unresolved_reason = (
                    _dimension_endpoints_from_candidates(
                        raw_candidate,
                        entity_keys={item.key for item in entities},
                        boundary_roles={},
                        profile_entity_by_ref=profile_entity_by_ref,
                        profile_vertex_entity_by_ref=profile_vertex_entity_by_ref,
                        pattern_entity_by_ref=pattern_entity_by_ref,
                        evidence=evidence,
                    )
                )

        symmetric_dimension_pair = _symmetric_dimension_pair_record(
            candidate=raw_candidate,
            dimension_key=dimension_key,
            dimension_value=value,
            axis=axis,
            candidates=dimension_candidates,
            report=report,
            context=context,
            view_lookup=view_lookup,
            profile_inventory=profile_inventory,
            overall_dimensions=overall_dimensions,
        )
        dimension_endpoints, unresolved_reason = (
            _reconcile_centered_symmetric_dimension_endpoint_roles(
                raw_candidate,
                endpoints=dimension_endpoints,
                unresolved_reason=unresolved_reason,
                symmetric_dimension_pair=symmetric_dimension_pair,
                entity_keys={item.key for item in entities},
                profile_entity_by_ref=profile_entity_by_ref,
                profile_vertex_entity_by_ref=profile_vertex_entity_by_ref,
                pattern_entity_by_ref=pattern_entity_by_ref,
                evidence=evidence,
            )
        )

        projected_profile_level_records.extend(
            _projected_profile_level_records(
                candidate=raw_candidate,
                dimension_key=dimension_key,
                axis=axis,
                dimension_endpoints=dimension_endpoints,
                boundary_roles=boundary_roles,
                profile_entity_by_ref=profile_entity_by_ref,
            )
        )

        if symmetric_dimension_pair is not None:
            symmetric_dimension_pair_records.append(symmetric_dimension_pair)

        if unresolved_reason is None and symmetric_pair is None:
            profile_span_center = _profile_span_center_record(
                candidate=raw_candidate,
                dimension_key=dimension_key,
                axis=axis,
                dimension_endpoints=dimension_endpoints,
            )
            if profile_span_center is not None:
                profile_span_center_records.append(profile_span_center)

            symmetric_profile_span = _symmetric_profile_span_record(
                candidate=raw_candidate,
                dimension_key=dimension_key,
                dimension_value=value,
                axis=axis,
                dimension_endpoints=dimension_endpoints,
                candidates=dimension_candidates,
                report=report,
                context=context,
                view_lookup=view_lookup,
                profile_inventory=profile_inventory,
                overall_dimensions=overall_dimensions,
            )
            if symmetric_profile_span is not None:
                symmetric_profile_span_records.append(symmetric_profile_span)

        dimension_required_for_modeling = True
        if (
            unresolved_reason is not None
            and (region_id, axis) in region_overall_fact_axes
        ):
            overall_key = {
                "X": "length_x",
                "Y": "width_y",
                "Z": "height_z",
            }[axis]
            independent_overall = overall_dimensions.get(overall_key)
            if (
                isinstance(independent_overall, (int, float))
                and not isinstance(independent_overall, bool)
                and math.isclose(
                    value,
                    float(independent_overall),
                    abs_tol=max(abs(value) * 1e-6, 1e-9),
                )
            ):
                # The local endpoint identity is still unresolved, but it
                # carries no additional modeling requirement: an independent
                # same-region structural fact already closes this full overall
                # extent. Preserve the OCR dimension as advisory evidence
                # instead of turning redundant endpoint ownership into a hard
                # stop.
                dimension_required_for_modeling = False

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
                evidence=dimension_evidence,
                required_for_modeling=dimension_required_for_modeling,
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

    dimension_span_center_identity_records = (
        _dimension_span_center_identity_records(
            dimensions=dimensions,
            candidates=dimension_candidates,
            profile_span_records=profile_span_center_records,
            report=report,
            view_lookup=view_lookup,
            profile_inventory=profile_inventory,
        )
    )

    (
        symmetric_local_section_feature_records,
        excluded_rotational_profile_refs,
    ) = _symmetric_local_section_feature_records(
        dimensions=dimensions,
        profile_span_records=profile_span_center_records,
        span_center_identity_records=(
            dimension_span_center_identity_records
        ),
        symmetric_dimension_pair_records=(
            symmetric_dimension_pair_records
        ),
        profile_entity_by_ref=profile_entity_by_ref,
    )

    rotational_profile_topology_hints = _rotational_profile_topology_hints(
        report=report,
        profile_inventory=profile_inventory,
        view_lookup=view_lookup,
        context=context,
        profile_entity_by_ref=profile_entity_by_ref,
        excluded_profile_refs=excluded_rotational_profile_refs,
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

    recovered_profile_dimensions, profile_offset_ledger = (
        _recover_unassigned_profile_edge_offsets(
            report=report,
            candidates=dimension_candidates,
            view_lookup=view_lookup,
            boundary_roles=boundary_roles,
            profile_entity_by_ref=profile_entity_by_ref,
            excluded_source_item_indices={
                item.get("half_source_item_index")
                for item in symmetric_chain_ledger
                if isinstance(item, dict)
            }
            | slot_claimed_source_indices,
        )
    )
    dimensions.extend(recovered_profile_dimensions)

    (
        labeled_profile_dimensions,
        labeled_profile_span_ledger,
    ) = _recover_labeled_profile_span_dimensions(
        report=report,
        facts=labeled_dimension_facts,
        view_lookup=view_lookup,
        profile_inventory=profile_inventory,
        profile_entity_by_ref=profile_entity_by_ref,
    )
    dimensions.extend(labeled_profile_dimensions)

    (
        reference_table_dimensions,
        reference_table_dimension_ledger,
    ) = _recover_reference_table_profile_span_dimensions(
        report=report,
        corroborating_facts=labeled_dimension_facts,
        view_lookup=view_lookup,
        profile_inventory=profile_inventory,
        profile_entity_by_ref=profile_entity_by_ref,
    )
    dimensions.extend(reference_table_dimensions)

    labeled_dimension_facts = _reconcile_labeled_profile_span_relations(
        facts=labeled_dimension_facts,
        identity_ledger=labeled_profile_span_ledger,
    )

    claimed_unassigned_source_indices: set[Any] = set(
        slot_claimed_source_indices
    )
    for record in symmetric_chain_ledger:
        if not isinstance(record, dict):
            continue
        claimed_unassigned_source_indices.update(
            record.get(key)
            for key in (
                "half_source_item_index",
                "total_source_item_index",
            )
        )
    for record in profile_offset_ledger:
        if isinstance(record, dict):
            claimed_unassigned_source_indices.add(
                record.get("source_item_index")
            )
    for record in reference_table_dimension_ledger:
        if isinstance(record, dict):
            claimed_unassigned_source_indices.add(
                record.get("drawing_numeric_source_item_index")
            )
    claimed_unassigned_source_indices.update(
        fact.source_item_index
        for fact in labeled_dimension_facts
    )
    claimed_unassigned_source_indices = {
        source_index
        for source_index in claimed_unassigned_source_indices
        if (
            isinstance(source_index, int)
            and not isinstance(source_index, bool)
            and source_index >= 0
        )
    }

    unresolved.extend(
        _coverage_unresolved(
            report,
            candidate_lookup,
            view_lookup,
            boundaries=boundaries,
            overall_dimension_facts=context.overall_dimension_facts,
            excluded_source_item_indices=claimed_unassigned_source_indices,
        )
    )

    associations, association_unresolved = _unique_orthographic_associations(
        report=report,
        view_lookup=view_lookup,
        entity_keys={item.key for item in entities},
        callout_ledger=callout_ledger,
    )
    unresolved.extend(association_unresolved)

    profile_associations = _overlapping_profile_associations(
        report=report,
        profile_inventory=profile_inventory,
        view_lookup=view_lookup,
        profile_entity_by_ref=profile_entity_by_ref,
    )
    associations.extend(profile_associations)
    associated_profile_keys = {
        entity_key
        for association in profile_associations
        for entity_key in association.entity_keys
    }
    if associated_profile_keys:
        entities = [
            item.model_copy(
                update={"cross_view_disposition": "associated"}
            )
            if item.key in associated_profile_keys
            else item
            for item in entities
        ]

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
            "kind": "hybrid_centerline_alignment_ledger",
            "schema": "1.0",
            "items": centerline_alignment_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_recess_start_side_ledger",
            "schema": "1.0",
            "items": recess_start_side_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        },
        {
            "kind": "human_confirmed_start_side_ledger",
            "schema": "1.0",
            "items": confirmed_start_side_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
        },
        {
            "kind": "hybrid_open_slot_ledger",
            "schema": "1.0",
            "items": slot_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        },
        {
            "kind": "hybrid_circle_datum_alignment_ledger",
            "schema": "1.0",
            "items": circle_alignment_records,
            "engineering_authoritative": True,
            "purpose": "overall_center_datum_alignment_from_explicit_center_axis",
            "engineering_coordinate_inferred_from_pixels": False,
        },
        {
            "kind": "hybrid_symmetric_dimension_recovery_ledger",
            "schema": "1.0",
            "items": symmetric_chain_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
        },
        {
            "kind": "hybrid_symmetric_count_two_ledger",
            "schema": "1.0",
            "items": symmetric_pair_records,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_projected_profile_level_ledger",
            "schema": "1.0",
            "items": projected_profile_level_records,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_symmetric_dimension_pair_ledger",
            "schema": "1.0",
            "items": symmetric_dimension_pair_records,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_profile_span_center_ledger",
            "schema": "1.0",
            "items": profile_span_center_records,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_dimension_span_center_identity_ledger",
            "schema": "1.0",
            "items": dimension_span_center_identity_records,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_symmetric_local_section_feature_ledger",
            "schema": "1.0",
            "items": symmetric_local_section_feature_records,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_symmetric_profile_span_ledger",
            "schema": "1.0",
            "items": symmetric_profile_span_records,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_profile_offset_recovery_ledger",
            "schema": "1.0",
            "items": profile_offset_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_labeled_profile_span_identity_ledger",
            "schema": "1.0",
            "items": labeled_profile_span_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_reference_table_dimension_recovery_ledger",
            "schema": "1.0",
            "items": reference_table_dimension_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
            "engineering_value_source": "corroborated_reference_table_row",
        },
        {
            "kind": "hybrid_labeled_dimension_relation_ledger",
            "schema": "1.0",
            "items": [
                item.model_dump(mode="json")
                for item in labeled_dimension_facts
            ],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
            "engineering_value_source": "hybrid_ocr",
            "relation_source": "bounded_structural_context",
        },
        {
            "kind": "hybrid_labeled_profile_transition_boundary_ledger",
            "schema": "1.0",
            "items": labeled_profile_transition_boundary_ledger,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "kind": "hybrid_rotational_profile_topology_ledger",
            "schema": "1.0",
            "items": rotational_profile_topology_hints,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        },
        {
            "kind": "hybrid_rotational_oblique_profile_candidate_ledger",
            "schema": "1.0",
            "items": rotational_oblique_profile_hints,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        },
        {
            "kind": "hybrid_profile_topology_ledger",
            "schema": "1.0",
            "items": metric_profile_topology_hints,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
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
        rotational_symmetry_facts=context.rotational_symmetry_facts,
        views=views,
        entities=entities,
        associations=associations,
        values=[
            *geometry_values,
            *callout_values,
            *recess_start_side_values,
            *confirmed_start_side_values,
            *slot_values,
        ],
        dimensions=dimensions,
        datum_alignments=datum_alignments,
        pattern_symmetries=[
            ObservationPatternSymmetry(
                entity_key=str(record["entity_key"]),
                axis=record["dimension_axis"],
                evidence=[
                    item
                    for item in record.get("evidence", [])
                    if isinstance(item, str) and item
                ],
                required_for_modeling=True,
            )
            for record in symmetric_pair_records
            if (
                isinstance(record, dict)
                and str(record.get("entity_key") or "")
                and record.get("dimension_axis") in {"X", "Y", "Z"}
            )
        ],
        centerline_alignments=centerline_alignments,
        observations=observations,
        unresolved=unresolved,
    )
