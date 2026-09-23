from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence import Axis, ViewKind
from .reader_observations import (
    ObservationDimension,
    ObservationDimensionEndpoint,
    ObservationUnresolved,
    ObservationView,
)
from .reader_semantic_answers import (
    PartialOverallDimensionFact,
    PartialReaderObservations,
)


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
    overall_dimension_facts: list[PartialOverallDimensionFact] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _unique_regions(self) -> "HybridAdapterContext":
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
        raise HybridCaptureAdapterError(
            "Hybrid OCR v2 report requires a coverage ledger"
        )
    if coverage.get("observed_silent_drop_count") != 0:
        raise HybridCaptureAdapterError(
            "Hybrid OCR report has observed silent evidence drops"
        )

    unresolved: list[ObservationUnresolved] = []

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
            raise HybridCaptureAdapterError(
                f"missing view context for region {region_id!r}"
            )
        axis = _axis_for(
            region_view.view_kind,
            str(candidate.get("orientation") or ""),
        )
        unresolved.append(
            ObservationUnresolved(
                kind="other",
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
                kind="other",
                reason=(
                    "Whole OCR linear observation was associated with a DG "
                    "but was not selected as that DG's global proposal: "
                    f"token={item.get('token')!r}, "
                    f"selected={item.get('selected_proposal_token')!r}."
                ),
                field="secondary_linear_assignment",
                evidence=evidence,
                required_for_modeling=True,
            )
        )

    for item in coverage.get("unassigned_linear_observations", []):
        if not isinstance(item, dict):
            continue
        unresolved.append(
            ObservationUnresolved(
                kind="other",
                reason=(
                    "Whole OCR found a standalone linear token with no unique "
                    f"DG assignment: token={item.get('token')!r}."
                ),
                field="unassigned_linear_text",
                evidence=[f"hybrid:whole:{item.get('source_item_index')}"],
                required_for_modeling=True,
            )
        )

    for item in coverage.get("local_only_linear_observations", []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        unresolved.append(
            ObservationUnresolved(
                kind="other",
                reason=(
                    "Wide local OCR found a linear token without a matching "
                    f"whole-drawing assignment: token={item.get('token')!r}."
                ),
                field="local_only_linear_text",
                evidence=_candidate_evidence(candidate_id),
                required_for_modeling=True,
            )
        )

    return unresolved


def adapt_hybrid_ocr_report(
    report: dict[str, Any],
    context: HybridAdapterContext,
) -> PartialReaderObservations:
    """Adapt Hybrid OCR v2 into partial Reader observations without inference."""

    if report.get("schema") != "dg-hybrid-ocr-bakeoff-v2":
        raise HybridCaptureAdapterError(
            "adapter requires dg-hybrid-ocr-bakeoff-v2"
        )

    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise HybridCaptureAdapterError("Hybrid report candidates must be a list")

    view_lookup = {item.region_id: item for item in context.region_views}
    candidate_lookup: dict[str, dict[str, Any]] = {}
    dimensions: list[ObservationDimension] = []
    unresolved: list[ObservationUnresolved] = []

    for raw_candidate in candidates:
        if not isinstance(raw_candidate, dict):
            raise HybridCaptureAdapterError("Hybrid candidate must be an object")
        candidate_id = str(raw_candidate.get("candidate_id") or "")
        region_id = str(raw_candidate.get("region_id") or "")
        if not candidate_id or not region_id:
            raise HybridCaptureAdapterError(
                "Hybrid candidate requires candidate_id and region_id"
            )
        if candidate_id in candidate_lookup:
            raise HybridCaptureAdapterError(
                f"duplicate Hybrid candidate_id {candidate_id!r}"
            )
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
            raise HybridCaptureAdapterError(
                f"missing view context for region {region_id!r}"
            )
        orientation = str(raw_candidate.get("orientation") or "")
        axis = _axis_for(region_view.view_kind, orientation)
        value, tolerance_token = _dimension_value(accepted_token)
        dimension_key = f"{region_id}.{candidate_id}"
        evidence = _candidate_evidence(candidate_id)

        dimensions.append(
            ObservationDimension(
                key=dimension_key,
                value=value,
                axis=axis,
                endpoints=[
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
                unresolved_reason=(
                    "Hybrid OCR confirms value and measured axis only; "
                    "endpoint ownership remains unresolved."
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

    unresolved.extend(
        _coverage_unresolved(
            report,
            candidate_lookup,
            view_lookup,
        )
    )

    coverage = report["coverage"]
    observations = [
        {
            "kind": "hybrid_ocr_coverage_ledger",
            "schema": report.get("schema"),
            "coverage": coverage,
        }
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
        dimensions=dimensions,
        observations=observations,
        unresolved=unresolved,
    )
