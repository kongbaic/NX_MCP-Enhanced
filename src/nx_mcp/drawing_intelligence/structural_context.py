from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import Axis, ViewKind
from .hybrid_capture_adapter import HybridAdapterContext, HybridRegionView
from .reader_semantic_answers import PartialOverallDimensionFact


class StructuralContextError(ValueError):
    """Raised when minimal structural context cannot be assembled safely."""


class _StrictStructuralModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _clean_evidence(value: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    if not cleaned:
        raise ValueError("evidence must contain at least one non-empty label")
    return cleaned


class StructuralCandidate(_StrictStructuralModel):
    candidate_id: str = Field(min_length=1)
    orientation: Literal["horizontal", "vertical"]
    accepted_token: str = Field(min_length=1)
    evidence_label: str = Field(min_length=1)


class StructuralRegionQuery(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    kind: Literal["structural_context"] = "structural_context"
    region_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    crop_evidence_label: str = Field(min_length=1)
    accepted_candidates: list[StructuralCandidate] = Field(default_factory=list)
    instruction_key: Literal["structural-context-v1"] = "structural-context-v1"


class StructuralContextQueryPlan(_StrictStructuralModel):
    schema_version: Literal["structural-context-queries-v1"] = Field(
        default="structural-context-queries-v1",
        alias="schema",
    )
    queries: list[StructuralRegionQuery] = Field(min_length=1, max_length=4)
    rules: dict[str, bool]

    @model_validator(mode="after")
    def _unique_queries(self) -> StructuralContextQueryPlan:
        query_ids = [item.query_id for item in self.queries]
        region_ids = [item.region_id for item in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("structural query ids must be unique")
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("structural query region ids must be unique")
        return self


class StructuralOverallAssignment(_StrictStructuralModel):
    candidate_id: str = Field(min_length=1)
    axis: Axis
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class StructuralRegionAnswer(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    view_kind: ViewKind | None = None
    evidence: list[str] = Field(default_factory=list)
    overall_assignments: list[StructuralOverallAssignment] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _clean_optional_evidence(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("unresolved")
    @classmethod
    def _clean_unresolved(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @model_validator(mode="after")
    def _shape(self) -> StructuralRegionAnswer:
        if self.view_kind is None:
            if not self.unresolved:
                raise ValueError("missing view_kind requires structured unresolved reason")
            if self.overall_assignments:
                raise ValueError("unresolved view_kind cannot carry overall assignments")
        elif not self.evidence:
            raise ValueError("resolved view_kind requires evidence")
        return self


class StructuralContextAnswers(_StrictStructuralModel):
    schema_version: Literal["structural-context-answers-v1"] = Field(
        default="structural-context-answers-v1",
        alias="schema",
    )
    answers: list[StructuralRegionAnswer] = Field(min_length=1, max_length=4)


def _accepted_candidates_by_region(
    hybrid_report: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for candidate in hybrid_report.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        candidate_id = candidate.get("candidate_id")
        region_id = candidate.get("region_id")
        orientation = candidate.get("orientation")
        token = candidate.get("accepted_token")
        if (
            isinstance(candidate_id, str)
            and candidate_id
            and isinstance(region_id, str)
            and region_id
            and orientation in {"horizontal", "vertical"}
            and isinstance(token, str)
            and token
        ):
            output.setdefault(region_id, []).append(candidate)
    for items in output.values():
        items.sort(key=lambda item: str(item["candidate_id"]))
    return output


def build_structural_context_queries(
    reader_input: dict[str, Any],
    hybrid_report: dict[str, Any],
    *,
    max_region_queries: int = 4,
) -> StructuralContextQueryPlan:
    if reader_input.get("schema") != "reader-input-v1":
        raise StructuralContextError("structural context requires reader-input-v1")
    if hybrid_report.get("schema") != "dg-hybrid-ocr-bakeoff-v2":
        raise StructuralContextError("structural context requires Hybrid OCR v2 report")
    if not 1 <= max_region_queries <= 4:
        raise StructuralContextError("max_region_queries must be between 1 and 4")

    regions = reader_input.get("regions")
    if not isinstance(regions, list) or not regions:
        raise StructuralContextError("reader input requires at least one region")
    if len(regions) > max_region_queries:
        raise StructuralContextError(
            f"region query count {len(regions)} exceeds bounded maximum {max_region_queries}"
        )

    accepted_by_region = _accepted_candidates_by_region(hybrid_report)
    queries: list[StructuralRegionQuery] = []
    seen_regions: set[str] = set()

    for index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            raise StructuralContextError("reader input region must be an object")
        region_id = region.get("region_id")
        image_path = region.get("candidate_overlay_path")
        if not isinstance(region_id, str) or not region_id:
            raise StructuralContextError("reader input region requires region_id")
        if region_id in seen_regions:
            raise StructuralContextError(f"duplicate reader region {region_id!r}")
        seen_regions.add(region_id)
        if not isinstance(image_path, str) or not image_path:
            raise StructuralContextError(
                f"reader region {region_id!r} requires candidate_overlay_path"
            )

        crop_label = f"structural:{region_id}:overlay"
        candidates = [
            StructuralCandidate(
                candidate_id=str(item["candidate_id"]),
                orientation=str(item["orientation"]),
                accepted_token=str(item["accepted_token"]),
                evidence_label=f"hybrid-ocr:{item['candidate_id']}",
            )
            for item in accepted_by_region.get(region_id, [])
        ]
        queries.append(
            StructuralRegionQuery(
                query_id=f"S{index:03d}",
                region_id=region_id,
                image_path=image_path,
                crop_evidence_label=crop_label,
                accepted_candidates=candidates,
            )
        )

    return StructuralContextQueryPlan(
        queries=queries,
        rules={
            "read_only_query_image": True,
            "open_unlisted_images": False,
            "scan_workspace": False,
            "read_numeric_value_from_image": False,
            "reinterpret_ocr_token": False,
            "select_only_listed_accepted_candidates": True,
            "cross_view_identity": False,
            "feature_inventory": False,
            "dimension_endpoint_ownership": False,
            "pixel_measurement": False,
        },
    )


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
        raise StructuralContextError(
            f"unsupported view/orientation combination {view_kind!r}/{orientation!r}"
        ) from exc


def _accepted_dimension_value(token: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:±\d+(?:\.\d+)?)?", token)
    if match is None:
        raise StructuralContextError(
            f"overall assignment requires accepted linear token, got {token!r}"
        )
    value = float(match.group(1))
    if value <= 0:
        raise StructuralContextError("overall dimension value must be positive")
    return value


def _assert_allowed_evidence(
    evidence: list[str],
    allowed: set[str],
    *,
    query_id: str,
) -> None:
    forbidden = sorted(set(evidence) - allowed)
    if forbidden:
        raise StructuralContextError(
            f"query {query_id!r} uses unlisted evidence labels {forbidden}"
        )


def assemble_structural_context(
    plan: StructuralContextQueryPlan,
    answers: StructuralContextAnswers,
    hybrid_report: dict[str, Any],
) -> HybridAdapterContext:
    if hybrid_report.get("schema") != "dg-hybrid-ocr-bakeoff-v2":
        raise StructuralContextError("structural context requires Hybrid OCR v2 report")

    queries = {item.query_id: item for item in plan.queries}
    answer_ids = [item.query_id for item in answers.answers]
    if len(answer_ids) != len(set(answer_ids)):
        raise StructuralContextError("structural answer query_ids must be unique")
    if set(answer_ids) != set(queries):
        missing = sorted(set(queries) - set(answer_ids))
        extra = sorted(set(answer_ids) - set(queries))
        raise StructuralContextError(
            f"structural answers do not match query plan; missing={missing}, extra={extra}"
        )

    report_candidates = {
        str(item["candidate_id"]): item
        for item in hybrid_report.get("candidates", [])
        if isinstance(item, dict) and item.get("candidate_id")
    }
    answers_by_id = {item.query_id: item for item in answers.answers}

    region_views: list[HybridRegionView] = []
    overall_facts: list[PartialOverallDimensionFact] = []
    used_candidates: set[str] = set()

    for query in plan.queries:
        answer = answers_by_id[query.query_id]
        if answer.unresolved:
            raise StructuralContextError(
                f"query {query.query_id!r} remains unresolved: {answer.unresolved}"
            )
        if answer.view_kind is None:
            raise StructuralContextError(f"query {query.query_id!r} has no resolved view_kind")

        allowed = {query.crop_evidence_label}
        allowed.update(item.evidence_label for item in query.accepted_candidates)
        _assert_allowed_evidence(answer.evidence, allowed, query_id=query.query_id)
        if query.crop_evidence_label not in answer.evidence:
            raise StructuralContextError(
                f"query {query.query_id!r} view evidence must include its overlay label"
            )

        region_views.append(
            HybridRegionView(
                region_id=query.region_id,
                view_kind=answer.view_kind,
                evidence=answer.evidence,
            )
        )

        query_candidates = {item.candidate_id: item for item in query.accepted_candidates}
        for assignment in answer.overall_assignments:
            candidate = query_candidates.get(assignment.candidate_id)
            if candidate is None:
                raise StructuralContextError(
                    f"query {query.query_id!r} selected unlisted candidate "
                    f"{assignment.candidate_id!r}"
                )
            if assignment.candidate_id in used_candidates:
                raise StructuralContextError(
                    f"candidate {assignment.candidate_id!r} assigned more than once"
                )
            used_candidates.add(assignment.candidate_id)

            report_candidate = report_candidates.get(assignment.candidate_id)
            if report_candidate is None:
                raise StructuralContextError(
                    f"Hybrid report missing candidate {assignment.candidate_id!r}"
                )
            if str(report_candidate.get("region_id") or "") != query.region_id:
                raise StructuralContextError(
                    f"candidate {assignment.candidate_id!r} belongs to another region"
                )
            if report_candidate.get("accepted_token") != candidate.accepted_token:
                raise StructuralContextError(
                    f"candidate {assignment.candidate_id!r} accepted token drift"
                )

            expected_axis = _axis_for(answer.view_kind, candidate.orientation)
            if assignment.axis != expected_axis:
                raise StructuralContextError(
                    f"candidate {assignment.candidate_id!r} axis {assignment.axis!r} "
                    f"does not match {answer.view_kind!r}/{candidate.orientation!r} "
                    f"expected axis {expected_axis!r}"
                )

            _assert_allowed_evidence(
                assignment.evidence,
                allowed,
                query_id=query.query_id,
            )
            if query.crop_evidence_label not in assignment.evidence:
                raise StructuralContextError(
                    f"candidate {assignment.candidate_id!r} assignment must include overlay evidence"
                )
            if candidate.evidence_label not in assignment.evidence:
                raise StructuralContextError(
                    f"candidate {assignment.candidate_id!r} assignment must include OCR evidence"
                )

            overall_facts.append(
                PartialOverallDimensionFact(
                    axis=assignment.axis,
                    value=_accepted_dimension_value(candidate.accepted_token),
                    evidence=assignment.evidence,
                )
            )

    by_axis: dict[Axis, list[float]] = {"X": [], "Y": [], "Z": []}
    for fact in overall_facts:
        by_axis[fact.axis].append(fact.value)

    for axis in ("X", "Y", "Z"):
        values = by_axis[axis]
        if not values:
            raise StructuralContextError(f"missing structural overall fact for axis {axis}")
        reference = values[0]
        if any(not math.isclose(value, reference, abs_tol=1e-9) for value in values[1:]):
            raise StructuralContextError(
                f"conflicting structural overall facts for axis {axis}: {values}"
            )

    return HybridAdapterContext(
        region_views=region_views,
        overall_dimension_facts=overall_facts,
        confirmed_start_sides=[],
    )
