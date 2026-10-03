from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .reader_candidate_answers import _axis_for
from .reader_candidate_queries import CandidateRegionQuery, ReaderCandidateQueryPlan
from .reader_semantic_answers import (
    PartialReaderObservations,
    ReaderSemanticAnswers,
    RegionDimensionAnswer,
    RegionDimensionEndpointAnswer,
    RegionEntityAnswer,
    RegionObservationAnswer,
    RegionUnresolvedAnswer,
    merge_region_semantic_answers,
)
from .reader_semantic_queries import ReaderSemanticQueryPlan, RegionObservationQuery


class ReaderCandidateValueError(ValueError):
    """Raised when value-only candidate answers violate their query plan."""


class _StrictValueModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CandidateValueAnswer(_StrictValueModel):
    target_id: str = Field(min_length=1)
    value: float | None = Field(default=None, gt=0)


class CandidateValueRegionAnswer(_StrictValueModel):
    schema_version: Literal["reader-candidate-value-region-v1"] = Field(
        default="reader-candidate-value-region-v1",
        alias="schema",
    )
    query_id: str = Field(min_length=1)
    view_kind: Literal["front", "side", "top"]
    targets: list[CandidateValueAnswer] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_targets(self) -> CandidateValueRegionAnswer:
        ids = [item.target_id for item in self.targets]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate value target ids must be unique")
        return self


def _region_value_answer_to_strict(
    query: CandidateRegionQuery,
    answer: CandidateValueRegionAnswer,
) -> RegionObservationAnswer:
    expected = {item.target_id: item for item in query.dimension_targets}
    supplied = {item.target_id: item for item in answer.targets}
    if set(expected) != set(supplied):
        missing = sorted(set(expected) - set(supplied))
        extra = sorted(set(supplied) - set(expected))
        raise ReaderCandidateValueError(
            f"candidate value target mismatch: missing={missing}, extra={extra}"
        )

    entities = [
        RegionEntityAnswer(
            key=item.entity_key,
            shape="concentric_circles" if item.ring_count > 1 else "circle",
            evidence=[query.region_id],
        )
        for item in query.circle_entities
    ]

    dimensions: list[RegionDimensionAnswer] = []
    unresolved: list[RegionUnresolvedAnswer] = []

    for target_id in sorted(expected):
        target = expected[target_id]
        result = supplied[target_id]
        if result.value is None:
            unresolved.append(
                RegionUnresolvedAnswer(
                    kind="other",
                    reason=(
                        f"Addressed candidate {target.target_id} has no clear "
                        "visible numeric dimension value from the single region read."
                    ),
                    field="dimension_value_candidate",
                    evidence=[target.evidence_label],
                )
            )
            continue

        endpoints = [
            RegionDimensionEndpointAnswer(
                role="unresolved",
                unresolved_kind="intermediate_surface",
                evidence=[target.evidence_label],
            ),
            RegionDimensionEndpointAnswer(
                role="unresolved",
                unresolved_kind="intermediate_surface",
                evidence=[target.evidence_label],
            ),
        ]
        dimensions.append(
            RegionDimensionAnswer(
                key=target.target_id,
                value=result.value,
                axis=_axis_for(answer.view_kind, target.orientation),
                endpoints=endpoints,
                unresolved_reason=(
                    "Value-only Reader defers endpoint ownership to downstream closure."
                ),
                evidence=[target.evidence_label],
            )
        )

    for bucket in query.overflow_buckets:
        unresolved.append(
            RegionUnresolvedAnswer(
                kind="other",
                reason=(
                    f"Deterministic candidate bucket {bucket.evidence_label} "
                    f"overflowed with {bucket.candidate_count} candidates."
                ),
                field="dimension_candidate_bucket",
                evidence=[bucket.evidence_label],
            )
        )

    return RegionObservationAnswer(
        query_id=query.query_id,
        view_kind=answer.view_kind,
        evidence=[query.region_id],
        entities=entities,
        dimensions=dimensions,
        unresolved=unresolved,
    )


def assemble_candidate_value_regions(
    plan: ReaderCandidateQueryPlan,
    answers: list[CandidateValueRegionAnswer],
) -> PartialReaderObservations:
    queries = {item.query_id: item for item in plan.queries}
    supplied = {item.query_id: item for item in answers}
    if len(supplied) != len(answers):
        raise ReaderCandidateValueError("candidate value query_id values must be unique")

    missing = sorted(set(queries) - set(supplied))
    extra = sorted(set(supplied) - set(queries))
    if missing or extra:
        raise ReaderCandidateValueError(
            f"candidate value regions mismatch query plan: missing={missing}, extra={extra}"
        )

    strict = ReaderSemanticAnswers(
        answers=[
            _region_value_answer_to_strict(queries[query_id], supplied[query_id])
            for query_id in sorted(queries)
        ]
    )
    semantic_plan = ReaderSemanticQueryPlan(
        queries=[
            RegionObservationQuery(
                query_id=query.query_id,
                region_id=query.region_id,
                image_path=query.image_path,
                allowed_evidence_labels=query.allowed_evidence_labels,
                candidate_buckets=[],
            )
            for query in plan.queries
        ]
    )
    return merge_region_semantic_answers(semantic_plan, strict)
