from __future__ import annotations

import math
from typing import Literal

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


class StructuralRegionQuery(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    kind: Literal["structural_context"] = "structural_context"
    region_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    evidence_label: str = Field(min_length=1)
    instruction_key: Literal["structural-context-v1"] = "structural-context-v1"


class StructuralViewAxes(_StrictStructuralModel):
    horizontal: Axis
    vertical: Axis


_CANONICAL_VIEW_AXIS_MAP: dict[ViewKind, dict[str, Axis]] = {
    "front": {"horizontal": "X", "vertical": "Z"},
    "side": {"horizontal": "Y", "vertical": "Z"},
    "top": {"horizontal": "X", "vertical": "Y"},
}


class StructuralContextQueryPlan(_StrictStructuralModel):
    schema_version: Literal["structural-context-queries-v1"] = Field(
        default="structural-context-queries-v1",
        alias="schema",
    )
    queries: list[StructuralRegionQuery] = Field(min_length=1, max_length=4)
    rules: dict[str, bool]
    view_axis_map: dict[ViewKind, StructuralViewAxes]
    answer_template: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_queries(self) -> StructuralContextQueryPlan:
        query_ids = [item.query_id for item in self.queries]
        region_ids = [item.region_id for item in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("structural query ids must be unique")
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("structural query region ids must be unique")
        actual_axis_map = {
            view_kind: {
                "horizontal": axes.horizontal,
                "vertical": axes.vertical,
            }
            for view_kind, axes in self.view_axis_map.items()
        }
        if actual_axis_map != _CANONICAL_VIEW_AXIS_MAP:
            raise ValueError("structural view_axis_map must match canonical view semantics")
        return self


class StructuralOverallFact(_StrictStructuralModel):
    axis: Axis
    value: float = Field(gt=0)
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class StructuralRegionAnswer(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    view_kind: ViewKind | None = None
    evidence: list[str] = Field(default_factory=list)
    overall_dimension_facts: list[StructuralOverallFact] = Field(default_factory=list)
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
            if self.overall_dimension_facts:
                raise ValueError("unresolved view_kind cannot carry overall dimension facts")
        elif not self.evidence:
            raise ValueError("resolved view_kind requires evidence")
        return self


class StructuralContextAnswers(_StrictStructuralModel):
    schema_version: Literal["structural-context-answers-v1"] = Field(
        default="structural-context-answers-v1",
        alias="schema",
    )
    answers: list[StructuralRegionAnswer] = Field(min_length=1, max_length=4)


def build_structural_context_queries(
    reader_input: dict,
    *,
    max_region_queries: int = 4,
) -> StructuralContextQueryPlan:
    if reader_input.get("schema") != "reader-input-v1":
        raise StructuralContextError("structural context requires reader-input-v1")
    if not 1 <= max_region_queries <= 4:
        raise StructuralContextError("max_region_queries must be between 1 and 4")

    regions = reader_input.get("regions")
    if not isinstance(regions, list) or not regions:
        raise StructuralContextError("reader input requires at least one region")
    if len(regions) > max_region_queries:
        raise StructuralContextError(
            f"region query count {len(regions)} exceeds bounded maximum {max_region_queries}"
        )

    queries: list[StructuralRegionQuery] = []
    seen_regions: set[str] = set()

    for index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            raise StructuralContextError("reader input region must be an object")
        region_id = region.get("region_id")
        image_path = region.get("crop_path")
        if not isinstance(region_id, str) or not region_id:
            raise StructuralContextError("reader input region requires region_id")
        if region_id in seen_regions:
            raise StructuralContextError(f"duplicate reader region {region_id!r}")
        seen_regions.add(region_id)
        if not isinstance(image_path, str) or not image_path:
            raise StructuralContextError(f"reader region {region_id!r} requires crop_path")

        queries.append(
            StructuralRegionQuery(
                query_id=f"S{index:03d}",
                region_id=region_id,
                image_path=image_path,
                evidence_label=f"structural:{region_id}:crop",
            )
        )

    return StructuralContextQueryPlan(
        queries=queries,
        rules={
            "read_only_query_image": True,
            "open_unlisted_images": False,
            "scan_workspace": False,
            "report_only_view_kind_and_direct_overall_dimensions": True,
            "derive_missing_dimensions": False,
            "cross_view_identity": False,
            "feature_inventory": False,
            "dimension_endpoint_ownership": False,
            "local_feature_values": False,
            "pixel_measurement": False,
        },
        view_axis_map={
            view_kind: StructuralViewAxes(
                horizontal=axes["horizontal"],
                vertical=axes["vertical"],
            )
            for view_kind, axes in _CANONICAL_VIEW_AXIS_MAP.items()
        },
        answer_template={
            "schema": "structural-context-answers-v1",
            "answers": [
                {
                    "query_id": query.query_id,
                    "view_kind": None,
                    "evidence": [query.evidence_label],
                    "overall_dimension_facts": [],
                    "unresolved": ["pending_structural_visual_read"],
                }
                for query in queries
            ],
        },
    )


def _assert_evidence(
    evidence: list[str],
    expected: str,
    *,
    query_id: str,
) -> None:
    if set(evidence) != {expected}:
        raise StructuralContextError(f"query {query_id!r} evidence must be exactly {expected!r}")


def assemble_structural_context(
    plan: StructuralContextQueryPlan,
    answers: StructuralContextAnswers,
) -> HybridAdapterContext:
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

    answers_by_id = {item.query_id: item for item in answers.answers}
    region_views: list[HybridRegionView] = []
    overall_facts: list[PartialOverallDimensionFact] = []

    for query in plan.queries:
        answer = answers_by_id[query.query_id]
        if answer.unresolved:
            raise StructuralContextError(
                f"query {query.query_id!r} remains unresolved: {answer.unresolved}"
            )
        if answer.view_kind is None:
            raise StructuralContextError(f"query {query.query_id!r} has no resolved view_kind")

        _assert_evidence(
            answer.evidence,
            query.evidence_label,
            query_id=query.query_id,
        )
        region_views.append(
            HybridRegionView(
                region_id=query.region_id,
                view_kind=answer.view_kind,
                evidence=answer.evidence,
            )
        )

        view_axes = plan.view_axis_map[answer.view_kind]
        visible_axes = {view_axes.horizontal, view_axes.vertical}
        seen_axes: set[Axis] = set()
        for fact in answer.overall_dimension_facts:
            if fact.axis not in visible_axes:
                raise StructuralContextError(
                    f"query {query.query_id!r} axis {fact.axis!r} is not visible "
                    f"in {answer.view_kind!r} view"
                )
            if fact.axis in seen_axes:
                raise StructuralContextError(
                    f"query {query.query_id!r} repeats overall axis {fact.axis}"
                )
            seen_axes.add(fact.axis)
            _assert_evidence(
                fact.evidence,
                query.evidence_label,
                query_id=query.query_id,
            )
            overall_facts.append(
                PartialOverallDimensionFact(
                    axis=fact.axis,
                    value=fact.value,
                    evidence=fact.evidence,
                )
            )

    by_axis: dict[Axis, list[float]] = {"X": [], "Y": [], "Z": []}
    for overall_fact in overall_facts:
        by_axis[overall_fact.axis].append(overall_fact.value)

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
