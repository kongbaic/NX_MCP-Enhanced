from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .capture import (
    CaptureEndpointRole,
    CaptureEndpointUnresolvedKind,
    DimensionEndpointEvidenceKind,
)
from .evidence import Axis, ProjectionShape, ViewKind
from .reader_observations import (
    ObservationDatumAlignment,
    ObservationDimension,
    ObservationDimensionEndpoint,
    ObservationEntity,
    ObservationUnresolved,
    ObservationValue,
    ObservationView,
)
from .reader_semantic_queries import ReaderSemanticQueryPlan


class ReaderSemanticAnswerError(ValueError):
    """Raised when bounded semantic answers violate their query contract."""


class _StrictAnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _clean_evidence(value: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    if not cleaned:
        raise ValueError("evidence must contain at least one non-empty label")
    return cleaned


class RegionOverallDimensionFact(_StrictAnswerModel):
    axis: Axis
    value: float = Field(gt=0)
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class RegionEntityAnswer(_StrictAnswerModel):
    key: str = Field(min_length=1)
    shape: ProjectionShape
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class RegionValueAnswer(_StrictAnswerModel):
    entity_key: str = Field(min_length=1)
    field: str = Field(min_length=1)
    value: Any
    semantic: str | None = None
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class RegionDimensionEndpointAnswer(_StrictAnswerModel):
    role: CaptureEndpointRole
    entity_key: str | None = None
    candidate_entity_keys: list[str] = Field(default_factory=list)
    basis: DimensionEndpointEvidenceKind | None = None
    unresolved_kind: CaptureEndpointUnresolvedKind | None = None
    evidence: list[str] = Field(min_length=1)

    @field_validator("candidate_entity_keys")
    @classmethod
    def _unique_candidates(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("candidate_entity_keys must be unique")
        return value

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _shape(self) -> RegionDimensionEndpointAnswer:
        ObservationDimensionEndpoint.model_validate(self.model_dump())
        return self


class RegionDimensionAnswer(_StrictAnswerModel):
    key: str = Field(min_length=1)
    value: float = Field(gt=0)
    axis: Axis
    endpoints: list[RegionDimensionEndpointAnswer] = Field(
        min_length=2,
        max_length=2,
    )
    unresolved_reason: str | None = None
    direction: Literal[-1, 1] | None = None
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _shape(self) -> RegionDimensionAnswer:
        has_unresolved = any(item.role == "unresolved" for item in self.endpoints)
        if has_unresolved and not self.unresolved_reason:
            raise ValueError("dimension with unresolved endpoint requires unresolved_reason")
        if not has_unresolved and self.unresolved_reason is not None:
            raise ValueError("resolved dimension must not carry unresolved_reason")
        return self


class RegionDatumAlignmentAnswer(_StrictAnswerModel):
    entity_key: str = Field(min_length=1)
    axis: Axis
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class RegionUnresolvedAnswer(_StrictAnswerModel):
    kind: Literal[
        "feature_inventory",
        "feature_value",
        "start_side",
        "termination",
        "local_surface",
        "unsupported_representation",
        "other",
    ]
    reason: str = Field(min_length=1)
    entity_keys: list[str] = Field(default_factory=list)
    dimension_key: str | None = None
    dimension_value: float | None = Field(default=None, gt=0)
    field: str | None = None
    axis: Axis | None = None
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    @field_validator("entity_keys")
    @classmethod
    def _unique_entity_keys(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("entity_keys must be unique")
        return value

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class RegionObservationAnswer(_StrictAnswerModel):
    query_id: str = Field(min_length=1)
    view_kind: ViewKind
    evidence: list[str] = Field(min_length=1)
    overall_dimension_facts: list[RegionOverallDimensionFact] = Field(default_factory=list)
    entities: list[RegionEntityAnswer] = Field(default_factory=list)
    values: list[RegionValueAnswer] = Field(default_factory=list)
    dimensions: list[RegionDimensionAnswer] = Field(default_factory=list)
    datum_alignments: list[RegionDatumAlignmentAnswer] = Field(default_factory=list)
    unresolved: list[RegionUnresolvedAnswer] = Field(default_factory=list)

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _local_references(self) -> RegionObservationAnswer:
        entity_keys = [item.key for item in self.entities]
        dimension_keys = [item.key for item in self.dimensions]
        if len(entity_keys) != len(set(entity_keys)):
            raise ValueError("region entity keys must be unique")
        if len(dimension_keys) != len(set(dimension_keys)):
            raise ValueError("region dimension keys must be unique")

        entity_set = set(entity_keys)
        dimension_set = set(dimension_keys)

        for value in self.values:
            if value.entity_key not in entity_set:
                raise ValueError(f"value references unknown local entity {value.entity_key!r}")

        for dimension in self.dimensions:
            for endpoint in dimension.endpoints:
                if endpoint.entity_key is not None and endpoint.entity_key not in entity_set:
                    raise ValueError(
                        f"dimension {dimension.key!r} references unknown local "
                        f"entity {endpoint.entity_key!r}"
                    )
                missing = [
                    item for item in endpoint.candidate_entity_keys if item not in entity_set
                ]
                if missing:
                    raise ValueError(
                        f"dimension {dimension.key!r} references unknown local "
                        f"candidate entities {missing}"
                    )

        for alignment in self.datum_alignments:
            if alignment.entity_key not in entity_set:
                raise ValueError(
                    f"datum alignment references unknown local entity {alignment.entity_key!r}"
                )

        for unresolved in self.unresolved:
            missing = [item for item in unresolved.entity_keys if item not in entity_set]
            if missing:
                raise ValueError(f"unresolved references unknown local entities {missing}")
            if (
                unresolved.dimension_key is not None
                and unresolved.dimension_key not in dimension_set
            ):
                raise ValueError(
                    f"unresolved references unknown local dimension {unresolved.dimension_key!r}"
                )

        return self


class ReaderSemanticAnswers(_StrictAnswerModel):
    schema_version: Literal["reader-semantic-answers-v1"] = Field(
        default="reader-semantic-answers-v1",
        alias="schema",
    )
    answers: list[RegionObservationAnswer] = Field(min_length=1, max_length=4)


class PartialOverallDimensionFact(_StrictAnswerModel):
    axis: Axis
    value: float = Field(gt=0)
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class PartialReaderObservations(_StrictAnswerModel):
    schema_version: Literal["reader-partial-observations-v1"] = Field(
        default="reader-partial-observations-v1",
        alias="schema",
    )
    overall_dimension_facts: list[PartialOverallDimensionFact] = Field(default_factory=list)
    views: list[ObservationView] = Field(default_factory=list)
    entities: list[ObservationEntity] = Field(default_factory=list)
    values: list[ObservationValue] = Field(default_factory=list)
    dimensions: list[ObservationDimension] = Field(default_factory=list)
    datum_alignments: list[ObservationDatumAlignment] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[ObservationUnresolved] = Field(default_factory=list)


def _assert_allowed_evidence(
    labels: list[str],
    allowed: set[str],
    *,
    query_id: str,
) -> None:
    forbidden = [item for item in labels if item not in allowed]
    if forbidden:
        raise ReaderSemanticAnswerError(
            f"query {query_id!r} uses unlisted evidence labels {forbidden}"
        )


def _prefixed(region_id: str, key: str) -> str:
    return f"{region_id}.{key}"


def merge_region_semantic_answers(
    plan: ReaderSemanticQueryPlan,
    answers: ReaderSemanticAnswers,
) -> PartialReaderObservations:
    """Merge region-local answers without adding cross-view semantic claims."""

    queries = {item.query_id: item for item in plan.queries}
    if len(queries) != len(plan.queries):
        raise ReaderSemanticAnswerError("semantic query ids must be unique")

    answer_ids = [item.query_id for item in answers.answers]
    if len(answer_ids) != len(set(answer_ids)):
        raise ReaderSemanticAnswerError("semantic answer query_ids must be unique")

    missing = sorted(set(queries) - set(answer_ids))
    extra = sorted(set(answer_ids) - set(queries))
    if missing or extra:
        raise ReaderSemanticAnswerError(
            f"semantic answers mismatch query plan: missing={missing}, extra={extra}"
        )

    overall_facts: list[PartialOverallDimensionFact] = []
    views: list[ObservationView] = []
    entities: list[ObservationEntity] = []
    values: list[ObservationValue] = []
    dimensions: list[ObservationDimension] = []
    alignments: list[ObservationDatumAlignment] = []
    unresolved_items: list[ObservationUnresolved] = []

    answers_by_id = {item.query_id: item for item in answers.answers}

    for query_id in sorted(queries):
        query = queries[query_id]
        answer = answers_by_id[query_id]
        allowed = set(query.allowed_evidence_labels)

        _assert_allowed_evidence(answer.evidence, allowed, query_id=query_id)

        view_key = f"view.{query.region_id}"
        views.append(
            ObservationView(
                key=view_key,
                kind=answer.view_kind,
                evidence=answer.evidence,
            )
        )

        for fact in answer.overall_dimension_facts:
            _assert_allowed_evidence(fact.evidence, allowed, query_id=query_id)
            overall_facts.append(
                PartialOverallDimensionFact(
                    axis=fact.axis,
                    value=fact.value,
                    evidence=fact.evidence,
                )
            )

        for entity in answer.entities:
            _assert_allowed_evidence(entity.evidence, allowed, query_id=query_id)
            entities.append(
                ObservationEntity(
                    key=_prefixed(query.region_id, entity.key),
                    view_key=view_key,
                    shape=entity.shape,
                    cross_view_disposition=None,
                    evidence=entity.evidence,
                    required_for_modeling=entity.required_for_modeling,
                )
            )

        for value in answer.values:
            _assert_allowed_evidence(value.evidence, allowed, query_id=query_id)
            values.append(
                ObservationValue(
                    entity_key=_prefixed(query.region_id, value.entity_key),
                    field=value.field,
                    value=value.value,
                    semantic=value.semantic,
                    evidence=value.evidence,
                )
            )

        for dimension in answer.dimensions:
            _assert_allowed_evidence(dimension.evidence, allowed, query_id=query_id)
            merged_endpoints: list[ObservationDimensionEndpoint] = []
            for endpoint in dimension.endpoints:
                _assert_allowed_evidence(
                    endpoint.evidence,
                    allowed,
                    query_id=query_id,
                )
                merged_endpoints.append(
                    ObservationDimensionEndpoint(
                        role=endpoint.role,
                        entity_key=(
                            _prefixed(query.region_id, endpoint.entity_key)
                            if endpoint.entity_key is not None
                            else None
                        ),
                        candidate_entity_keys=[
                            _prefixed(query.region_id, item)
                            for item in endpoint.candidate_entity_keys
                        ],
                        basis=endpoint.basis,
                        unresolved_kind=endpoint.unresolved_kind,
                        evidence=endpoint.evidence,
                    )
                )

            dimensions.append(
                ObservationDimension(
                    key=_prefixed(query.region_id, dimension.key),
                    value=dimension.value,
                    axis=dimension.axis,
                    endpoints=merged_endpoints,
                    unresolved_reason=dimension.unresolved_reason,
                    direction=dimension.direction,
                    evidence=dimension.evidence,
                    required_for_modeling=dimension.required_for_modeling,
                )
            )

        for alignment in answer.datum_alignments:
            _assert_allowed_evidence(
                alignment.evidence,
                allowed,
                query_id=query_id,
            )
            alignments.append(
                ObservationDatumAlignment(
                    entity_key=_prefixed(query.region_id, alignment.entity_key),
                    axis=alignment.axis,
                    evidence=alignment.evidence,
                    required_for_modeling=alignment.required_for_modeling,
                )
            )

        for unresolved in answer.unresolved:
            _assert_allowed_evidence(
                unresolved.evidence,
                allowed,
                query_id=query_id,
            )
            unresolved_items.append(
                ObservationUnresolved(
                    kind=unresolved.kind,
                    reason=unresolved.reason,
                    entity_keys=[
                        _prefixed(query.region_id, item) for item in unresolved.entity_keys
                    ],
                    dimension_key=(
                        _prefixed(query.region_id, unresolved.dimension_key)
                        if unresolved.dimension_key is not None
                        else None
                    ),
                    dimension_value=unresolved.dimension_value,
                    field=unresolved.field,
                    axis=unresolved.axis,
                    basis=[],
                    evidence=unresolved.evidence,
                    required_for_modeling=unresolved.required_for_modeling,
                )
            )

    return PartialReaderObservations(
        overall_dimension_facts=overall_facts,
        views=views,
        entities=entities,
        values=values,
        dimensions=dimensions,
        datum_alignments=alignments,
        unresolved=unresolved_items,
    )
