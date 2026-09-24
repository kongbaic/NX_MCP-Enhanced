from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .dimension_endpoint_candidates import derive_dimension_endpoint_candidates
from .engineering_callout_binding import bind_callout_to_circle_entity
from .engineering_callouts import parse_engineering_callout
from .evidence import Axis, ViewKind
from .reader_observations import (
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
from .view_metric_calibration import derive_view_metric_calibrations


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


def _dimension_endpoints_from_candidates(
    candidate: dict[str, Any],
    *,
    entity_keys: set[str],
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
            entity_key = _circle_center_entity_key(
                physical_candidates[0],
                entity_keys,
            )
            if entity_key is not None:
                output.append(
                    ObservationDimensionEndpoint(
                        role="entity_center",
                        entity_key=entity_key,
                        basis="circle_center",
                        evidence=evidence,
                    )
                )
                continue

        output.append(
            ObservationDimensionEndpoint(
                role="unresolved",
                unresolved_kind="intermediate_surface",
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


def _engineering_callout_routing(
    report: dict[str, Any],
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

    ledger: list[dict[str, Any]] = []
    callout_entities: list[ObservationEntity] = []
    unresolved: list[ObservationUnresolved] = []
    value_records: dict[tuple[str, str], dict[str, Any]] = {}
    conflicted_targets: set[tuple[str, str]] = set()
    conflict_evidence: dict[tuple[str, str], list[str]] = {}

    for item in coverage.get("routed_elsewhere_or_unclassified_observations", []):
        if not isinstance(item, dict):
            continue
        parsed = parse_engineering_callout(str(item.get("text") or ""))
        if parsed is None:
            continue

        source_item_index = item.get("source_item_index")
        evidence = [f"hybrid:whole:{source_item_index}"]
        center = _bbox_center(item.get("bbox"))
        region_candidates = (
            sorted(region_id for region_id, bbox in region_boxes if _point_in_bbox(center, bbox))
            if center is not None
            else []
        )
        binding = bind_callout_to_circle_entity(
            item.get("bbox"),
            annotation_lines,
            regions,
        )
        record = {
            "source_item_index": source_item_index,
            "bbox": item.get("bbox"),
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
            }
        }

        if binding.get("status") != "bound":
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
    candidate_lookup: dict[str, dict[str, Any]] = {}
    dimensions: list[ObservationDimension] = []
    unresolved: list[ObservationUnresolved] = []
    entities = _circle_entities(report, view_lookup)

    for raw_candidate in candidates:
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
            evidence=evidence,
        )
        dimensions.append(
            ObservationDimension(
                key=dimension_key,
                value=value,
                axis=axis,
                endpoints=dimension_endpoints,
                unresolved_reason=unresolved_reason,
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
    ) = _engineering_callout_routing(report)
    entities.extend(callout_entities)
    unresolved.extend(callout_unresolved)

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
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("accepted_token") is not None
    ]
    overall_dimensions = {
        {"X": "length_x", "Y": "width_y", "Z": "height_z"}[fact.axis]: fact.value
        for fact in context.overall_dimension_facts
    }
    calibrations = derive_view_metric_calibrations(
        candidates=[item for item in candidates if isinstance(item, dict)],
        region_views={
            item.region_id: item.view_kind
            for item in context.region_views
        },
        overall_dimensions=overall_dimensions,
    )

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
            "kind": "hybrid_view_metric_calibration_ledger",
            "schema": "1.0",
            "items": calibrations,
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
        values=callout_values,
        dimensions=dimensions,
        observations=observations,
        unresolved=unresolved,
    )
