from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .capture import CaptureEndpointUnresolvedKind
from .evidence import Axis, ProjectionShape, ViewKind
from .reader_semantic_answers import (
    PartialReaderObservations,
    ReaderSemanticAnswerError,
    ReaderSemanticAnswers,
    RegionDatumAlignmentAnswer,
    RegionDimensionAnswer,
    RegionDimensionEndpointAnswer,
    RegionEntityAnswer,
    RegionObservationAnswer,
    RegionOverallDimensionFact,
    RegionUnresolvedAnswer,
    RegionValueAnswer,
    merge_region_semantic_answers,
)
from .reader_semantic_queries import ReaderSemanticQueryPlan


class ReaderSemanticCompactError(ValueError):
    """Raised when compact region-local semantic facts are invalid."""


class _StrictCompactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


CompactFactKind = Literal["overall", "entity", "value", "dimension", "datum", "unresolved"]
CompactUnresolvedKind = Literal[
    "feature_inventory",
    "feature_value",
    "start_side",
    "termination",
    "local_surface",
    "unsupported_representation",
    "other",
]


class CompactSemanticFact(_StrictCompactModel):
    kind: CompactFactKind
    key: str | None = None
    entity_key: str | None = None
    entity_keys: list[str] = Field(default_factory=list)
    shape: str | None = None
    axis: Axis | None = None
    value: Any = None
    field: str | None = None
    semantic: str | None = None
    endpoint_a: str | None = None
    endpoint_b: str | None = None
    direction: Literal[-1, 1] | None = None
    category: CompactUnresolvedKind | None = None
    reason: str | None = None
    dimension_key: str | None = None
    dimension_value: float | None = Field(default=None, gt=0)
    evidence: str = Field(min_length=1)
    required_for_modeling: bool = True

    @model_validator(mode="after")
    def _required_fields(self) -> CompactSemanticFact:
        if self.kind == "overall":
            if self.axis is None or not isinstance(self.value, (int, float)) or self.value <= 0:
                raise ValueError("overall fact requires positive numeric value and axis")
        elif self.kind == "entity":
            if not self.key or not self.shape:
                raise ValueError("entity fact requires key and shape")
        elif self.kind == "value":
            if not self.entity_key or not self.field:
                raise ValueError("value fact requires entity_key and field")
        elif self.kind == "dimension":
            if (
                not self.key
                or self.axis is None
                or not isinstance(self.value, (int, float))
                or self.value <= 0
                or not self.endpoint_a
                or not self.endpoint_b
            ):
                raise ValueError(
                    "dimension fact requires key, positive value, axis, endpoint_a and endpoint_b"
                )
        elif self.kind == "datum":
            if not self.entity_key or self.axis is None:
                raise ValueError("datum fact requires entity_key and axis")
        elif self.kind == "unresolved" and (self.category is None or not self.reason):
            raise ValueError("unresolved fact requires category and reason")
        return self


class CompactRegionSemanticAnswer(_StrictCompactModel):
    schema_version: Literal["reader-semantic-region-v1"] = Field(
        default="reader-semantic-region-v1",
        alias="schema",
    )
    query_id: str = Field(min_length=1)
    view_kind: ViewKind
    facts: list[CompactSemanticFact] = Field(default_factory=list)


_SHAPE_ALIASES: dict[str, ProjectionShape] = {
    "circle": "circle",
    "concentric": "concentric_circles",
    "concentric_circles": "concentric_circles",
    "hidden_parallel": "hidden_parallel",
    "slot": "slot_edges",
    "slot_edges": "slot_edges",
    "profile": "profile",
    "rectangle": "profile",
    "rect": "profile",
    "plane": "profile",
    "plate": "profile",
    "face": "profile",
    "step": "profile",
    "other": "other",
}

_BASIS_VALUES: set[str] = {"centerline", "center_mark", "explicit_midline"}


def _shape(value: str) -> ProjectionShape:
    normalized = value.strip().lower()
    try:
        return _SHAPE_ALIASES[normalized]
    except KeyError as exc:
        raise ReaderSemanticCompactError(f"unknown compact shape token {value!r}") from exc


def _endpoint(token: str, evidence: str) -> RegionDimensionEndpointAnswer:
    normalized = token.strip()
    if normalized == "overall_min":
        return RegionDimensionEndpointAnswer(
            role="overall_min",
            evidence=[evidence],
        )
    if normalized == "overall_max":
        return RegionDimensionEndpointAnswer(
            role="overall_max",
            evidence=[evidence],
        )

    if normalized.startswith("center:"):
        parts = normalized.split(":")
        if len(parts) != 3 or not parts[1] or parts[2] not in _BASIS_VALUES:
            raise ReaderSemanticCompactError(
                "center endpoint must be center:<entity_key>:"
                "<centerline|center_mark|explicit_midline>"
            )
        basis = parts[2]
        center_basis: Literal["centerline", "center_mark", "explicit_midline"]
        if basis == "centerline":
            center_basis = "centerline"
        elif basis == "center_mark":
            center_basis = "center_mark"
        else:
            center_basis = "explicit_midline"
        return RegionDimensionEndpointAnswer(
            role="entity_center",
            entity_key=parts[1],
            basis=center_basis,
            evidence=[evidence],
        )

    if normalized.startswith("ambiguous:"):
        candidates = [
            item.strip()
            for item in normalized.removeprefix("ambiguous:").split(",")
            if item.strip()
        ]
        if len(candidates) < 2 or len(candidates) != len(set(candidates)):
            raise ReaderSemanticCompactError(
                "ambiguous endpoint requires at least two unique local entity keys"
            )
        return RegionDimensionEndpointAnswer(
            role="unresolved",
            candidate_entity_keys=candidates,
            unresolved_kind="ambiguous_owner",
            evidence=[evidence],
        )

    unresolved_map: dict[str, CaptureEndpointUnresolvedKind] = {
        "intermediate_surface": "intermediate_surface",
        "unsupported_reference": "unsupported_reference",
    }
    if normalized in unresolved_map:
        return RegionDimensionEndpointAnswer(
            role="unresolved",
            unresolved_kind=unresolved_map[normalized],
            evidence=[evidence],
        )

    raise ReaderSemanticCompactError(f"unknown compact endpoint token {token!r}")


def _dimension_unresolved_reason(
    endpoints: list[RegionDimensionEndpointAnswer],
    explicit_reason: str | None,
) -> str | None:
    if not any(item.role == "unresolved" for item in endpoints):
        return None
    if explicit_reason:
        return explicit_reason
    return "One or more local dimension endpoints remain unresolved in the bounded region query."


def build_reader_semantic_answers_from_regions(
    plan: ReaderSemanticQueryPlan,
    region_answers: list[CompactRegionSemanticAnswer],
) -> ReaderSemanticAnswers:
    queries = {item.query_id: item for item in plan.queries}
    supplied = {item.query_id: item for item in region_answers}
    if len(supplied) != len(region_answers):
        raise ReaderSemanticCompactError("compact query_id values must be unique")

    missing = sorted(set(queries) - set(supplied))
    extra = sorted(set(supplied) - set(queries))
    if missing or extra:
        raise ReaderSemanticCompactError(
            f"compact regions mismatch query plan: missing={missing}, extra={extra}"
        )

    strict_answers: list[RegionObservationAnswer] = []

    for query_id in sorted(queries):
        query = queries[query_id]
        compact = supplied[query_id]
        allowed = set(query.allowed_evidence_labels)

        overall: list[RegionOverallDimensionFact] = []
        entities: list[RegionEntityAnswer] = []
        values: list[RegionValueAnswer] = []
        dimensions: list[RegionDimensionAnswer] = []
        datum: list[RegionDatumAlignmentAnswer] = []
        unresolved: list[RegionUnresolvedAnswer] = []

        for fact in compact.facts:
            if fact.evidence not in allowed:
                raise ReaderSemanticCompactError(
                    f"query {query_id!r} uses unlisted evidence label {fact.evidence!r}"
                )

            if fact.kind == "overall":
                assert fact.axis is not None
                overall.append(
                    RegionOverallDimensionFact(
                        axis=fact.axis,
                        value=float(fact.value),
                        evidence=[fact.evidence],
                    )
                )
            elif fact.kind == "entity":
                assert fact.key is not None
                entities.append(
                    RegionEntityAnswer(
                        key=fact.key,
                        shape=_shape(fact.shape or ""),
                        evidence=[fact.evidence],
                        required_for_modeling=fact.required_for_modeling,
                    )
                )
            elif fact.kind == "value":
                assert fact.entity_key is not None
                assert fact.field is not None
                values.append(
                    RegionValueAnswer(
                        entity_key=fact.entity_key,
                        field=fact.field,
                        value=fact.value,
                        semantic=fact.semantic,
                        evidence=[fact.evidence],
                    )
                )
            elif fact.kind == "dimension":
                assert fact.key is not None
                assert fact.axis is not None
                endpoints = [
                    _endpoint(fact.endpoint_a or "", fact.evidence),
                    _endpoint(fact.endpoint_b or "", fact.evidence),
                ]
                dimensions.append(
                    RegionDimensionAnswer(
                        key=fact.key,
                        value=float(fact.value),
                        axis=fact.axis,
                        endpoints=endpoints,
                        unresolved_reason=_dimension_unresolved_reason(
                            endpoints,
                            fact.reason,
                        ),
                        direction=fact.direction,
                        evidence=[fact.evidence],
                        required_for_modeling=fact.required_for_modeling,
                    )
                )
            elif fact.kind == "datum":
                assert fact.entity_key is not None
                assert fact.axis is not None
                datum.append(
                    RegionDatumAlignmentAnswer(
                        entity_key=fact.entity_key,
                        axis=fact.axis,
                        evidence=[fact.evidence],
                        required_for_modeling=fact.required_for_modeling,
                    )
                )
            else:
                assert fact.category is not None
                assert fact.reason is not None
                unresolved.append(
                    RegionUnresolvedAnswer(
                        kind=fact.category,
                        reason=fact.reason,
                        entity_keys=fact.entity_keys,
                        dimension_key=fact.dimension_key,
                        dimension_value=fact.dimension_value,
                        field=fact.field,
                        axis=fact.axis,
                        evidence=[fact.evidence],
                        required_for_modeling=fact.required_for_modeling,
                    )
                )

        strict_answers.append(
            RegionObservationAnswer(
                query_id=query_id,
                view_kind=compact.view_kind,
                evidence=[query.region_id],
                overall_dimension_facts=overall,
                entities=entities,
                values=values,
                dimensions=dimensions,
                datum_alignments=datum,
                unresolved=unresolved,
            )
        )

    return ReaderSemanticAnswers(answers=strict_answers)


def assemble_compact_regions(
    plan: ReaderSemanticQueryPlan,
    region_answers: list[CompactRegionSemanticAnswer],
) -> tuple[ReaderSemanticAnswers, PartialReaderObservations]:
    strict = build_reader_semantic_answers_from_regions(plan, region_answers)
    try:
        partial = merge_region_semantic_answers(plan, strict)
    except ReaderSemanticAnswerError as exc:
        raise ReaderSemanticCompactError(str(exc)) from exc
    return strict, partial
