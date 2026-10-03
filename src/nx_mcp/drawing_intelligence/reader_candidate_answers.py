from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence import Axis
from .reader_candidate_queries import (
    CandidateDimensionTarget,
    CandidateRegionQuery,
    ReaderCandidateQueryPlan,
)
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
from .reader_semantic_queries import (
    ReaderSemanticQueryPlan,
    RegionObservationQuery,
)

CandidateClassification = Literal["dimension", "not_dimension", "uncertain"]


class ReaderCandidateAnswerError(ValueError):
    """Raised when candidate-addressed semantic answers violate their query."""


class _StrictCandidateAnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CandidateTargetAnswer(_StrictCandidateAnswerModel):
    target_id: str = Field(min_length=1)
    classification: CandidateClassification
    value: float | None = Field(default=None, gt=0)
    endpoint_a: str | None = None
    endpoint_b: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> CandidateTargetAnswer:
        if self.classification == "dimension":
            if self.value is None or not self.endpoint_a or not self.endpoint_b:
                raise ValueError(
                    "dimension candidate answer requires value and two endpoint tokens"
                )
        elif self.value is not None or self.endpoint_a is not None or self.endpoint_b is not None:
            raise ValueError(
                "non-dimension/uncertain candidate answer must not carry value or endpoints"
            )
        return self


class CandidateRegionAnswer(_StrictCandidateAnswerModel):
    schema_version: Literal["reader-candidate-region-v1"] = Field(
        default="reader-candidate-region-v1",
        alias="schema",
    )
    query_id: str = Field(min_length=1)
    view_kind: Literal["front", "side", "top"]
    targets: list[CandidateTargetAnswer] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_targets(self) -> CandidateRegionAnswer:
        ids = [item.target_id for item in self.targets]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate answer target ids must be unique")
        return self


def _axis_for(view_kind: str, orientation: str) -> Axis:
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
        raise ReaderCandidateAnswerError(
            f"unsupported view/orientation combination {view_kind!r}/{orientation!r}"
        ) from exc


def _anchor_kind_map(target: CandidateDimensionTarget) -> dict[str, str]:
    output: dict[str, str] = {}
    for witness in target.witness_hints:
        for option in witness.anchor_options:
            output[option.ref] = option.kind
    return output


def _circle_entity_from_ref(query: CandidateRegionQuery, ref: str) -> str:
    prefix = f"{query.region_id}."
    if not ref.startswith(prefix) or ".center_" not in ref:
        raise ReaderCandidateAnswerError(
            f"circle endpoint ref does not belong to query region: {ref!r}"
        )
    local = ref[len(prefix) :].split(".center_", 1)[0]
    allowed = {item.entity_key for item in query.circle_entities}
    if local not in allowed:
        raise ReaderCandidateAnswerError(
            f"circle endpoint ref names unknown local circle entity {local!r}"
        )
    return local


def _bbox_endpoint(
    target: CandidateDimensionTarget,
    ref: str,
    evidence: str,
) -> RegionDimensionEndpointAnswer:
    suffix = ref.rsplit(".", 1)[-1]
    if target.orientation == "horizontal":
        if suffix == "left":
            return RegionDimensionEndpointAnswer(
                role="overall_min",
                evidence=[evidence],
            )
        if suffix == "right":
            return RegionDimensionEndpointAnswer(
                role="overall_max",
                evidence=[evidence],
            )
        raise ReaderCandidateAnswerError(f"horizontal dimension cannot use bbox endpoint {ref!r}")

    if suffix == "bottom":
        return RegionDimensionEndpointAnswer(
            role="overall_min",
            evidence=[evidence],
        )
    if suffix == "top":
        return RegionDimensionEndpointAnswer(
            role="overall_max",
            evidence=[evidence],
        )
    raise ReaderCandidateAnswerError(f"vertical dimension cannot use bbox endpoint {ref!r}")


def _endpoint(
    query: CandidateRegionQuery,
    target: CandidateDimensionTarget,
    token: str,
) -> RegionDimensionEndpointAnswer:
    evidence = target.evidence_label
    normalized = token.strip()
    if normalized == "intermediate_surface":
        return RegionDimensionEndpointAnswer(
            role="unresolved",
            unresolved_kind="intermediate_surface",
            evidence=[evidence],
        )
    if normalized == "unsupported_reference":
        return RegionDimensionEndpointAnswer(
            role="unresolved",
            unresolved_kind="unsupported_reference",
            evidence=[evidence],
        )

    kinds = _anchor_kind_map(target)

    if normalized.startswith("bbox:"):
        ref = normalized.removeprefix("bbox:")
        if kinds.get(ref) != "region_bbox_edge":
            raise ReaderCandidateAnswerError(f"endpoint token uses unavailable bbox anchor {ref!r}")
        return _bbox_endpoint(target, ref, evidence)

    if normalized.startswith("circle:"):
        parts = normalized.split(":")
        if len(parts) != 3:
            raise ReaderCandidateAnswerError("circle endpoint token must be circle:<ref>:<basis>")
        ref, basis = parts[1], parts[2]
        if kinds.get(ref) != "circle_center_axis":
            raise ReaderCandidateAnswerError(
                f"endpoint token uses unavailable circle anchor {ref!r}"
            )
        center_basis: Literal["centerline", "center_mark", "explicit_midline"]
        if basis == "centerline":
            center_basis = "centerline"
        elif basis == "center_mark":
            center_basis = "center_mark"
        elif basis == "explicit_midline":
            center_basis = "explicit_midline"
        else:
            raise ReaderCandidateAnswerError(f"unsupported circle endpoint basis {basis!r}")
        entity_key = _circle_entity_from_ref(query, ref)
        return RegionDimensionEndpointAnswer(
            role="entity_center",
            entity_key=entity_key,
            basis=center_basis,
            evidence=[evidence],
        )

    if normalized.startswith("ambiguous:"):
        refs = [
            item.strip()
            for item in normalized.removeprefix("ambiguous:").split(",")
            if item.strip()
        ]
        if len(refs) < 2 or len(refs) != len(set(refs)):
            raise ReaderCandidateAnswerError(
                "ambiguous endpoint requires at least two unique circle refs"
            )
        entity_keys: list[str] = []
        for ref in refs:
            if kinds.get(ref) != "circle_center_axis":
                raise ReaderCandidateAnswerError(
                    f"ambiguous endpoint uses unavailable circle anchor {ref!r}"
                )
            entity_keys.append(_circle_entity_from_ref(query, ref))
        return RegionDimensionEndpointAnswer(
            role="unresolved",
            candidate_entity_keys=entity_keys,
            unresolved_kind="ambiguous_owner",
            evidence=[evidence],
        )

    raise ReaderCandidateAnswerError(f"unknown candidate endpoint token {token!r}")


def _dimension_reason(endpoints: list[RegionDimensionEndpointAnswer]) -> str | None:
    if any(item.role == "unresolved" for item in endpoints):
        return "One or more addressed candidate endpoints remain unresolved."
    return None


def _region_answer_to_strict(
    query: CandidateRegionQuery,
    answer: CandidateRegionAnswer,
) -> RegionObservationAnswer:
    expected = {item.target_id: item for item in query.dimension_targets}
    supplied = {item.target_id: item for item in answer.targets}
    if set(expected) != set(supplied):
        missing = sorted(set(expected) - set(supplied))
        extra = sorted(set(supplied) - set(expected))
        raise ReaderCandidateAnswerError(
            f"candidate answer target mismatch: missing={missing}, extra={extra}"
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
        if result.classification == "not_dimension":
            continue
        if result.classification == "uncertain":
            unresolved.append(
                RegionUnresolvedAnswer(
                    kind="other",
                    reason=(
                        f"Addressed candidate {target.target_id} could not be "
                        "classified from the single region read."
                    ),
                    field="dimension_candidate",
                    evidence=[target.evidence_label],
                )
            )
            continue

        assert result.value is not None
        assert result.endpoint_a is not None
        assert result.endpoint_b is not None
        endpoints = [
            _endpoint(query, target, result.endpoint_a),
            _endpoint(query, target, result.endpoint_b),
        ]
        dimensions.append(
            RegionDimensionAnswer(
                key=target.target_id,
                value=result.value,
                axis=_axis_for(answer.view_kind, target.orientation),
                endpoints=endpoints,
                unresolved_reason=_dimension_reason(endpoints),
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


def assemble_candidate_regions(
    plan: ReaderCandidateQueryPlan,
    answers: list[CandidateRegionAnswer],
) -> PartialReaderObservations:
    queries = {item.query_id: item for item in plan.queries}
    supplied = {item.query_id: item for item in answers}
    if len(supplied) != len(answers):
        raise ReaderCandidateAnswerError("candidate query_id values must be unique")

    missing = sorted(set(queries) - set(supplied))
    extra = sorted(set(supplied) - set(queries))
    if missing or extra:
        raise ReaderCandidateAnswerError(
            f"candidate regions mismatch query plan: missing={missing}, extra={extra}"
        )

    strict = ReaderSemanticAnswers(
        answers=[
            _region_answer_to_strict(queries[query_id], supplied[query_id])
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
