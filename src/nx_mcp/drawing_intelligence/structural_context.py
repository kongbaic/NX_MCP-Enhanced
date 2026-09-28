from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import Axis, ViewKind
from .hybrid_capture_adapter import HybridAdapterContext, HybridRegionView
from .reader_semantic_answers import (
    PartialOverallDimensionFact,
    PartialRotationalSymmetryFact,
)


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


class StructuralRotationalSymmetryDecision(_StrictStructuralModel):
    status: Literal["established", "not_established"]
    axis: Axis | None = None
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _shape(self) -> StructuralRotationalSymmetryDecision:
        if self.status == "established" and self.axis is None:
            raise ValueError("established rotational symmetry requires axis")
        if self.status == "not_established" and self.axis is not None:
            raise ValueError("not_established rotational symmetry requires null axis")
        return self


class StructuralRegionAnswer(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    view_kind: ViewKind | None = None
    evidence: list[str] = Field(default_factory=list)
    overall_dimension_facts: list[StructuralOverallFact] = Field(default_factory=list)
    rotational_symmetry: StructuralRotationalSymmetryDecision | None = Field(...)
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
            if self.rotational_symmetry is not None:
                raise ValueError("unresolved view_kind cannot carry rotational symmetry decision")
        elif not self.evidence:
            raise ValueError("resolved view_kind requires evidence")
        elif not self.unresolved and self.rotational_symmetry is None:
            raise ValueError(
                "resolved structural answer requires explicit rotational symmetry decision"
            )
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
        structural_context_path = region.get("structural_context_path")
        crop_path = region.get("crop_path")
        if not isinstance(region_id, str) or not region_id:
            raise StructuralContextError("reader input region requires region_id")
        if region_id in seen_regions:
            raise StructuralContextError(f"duplicate reader region {region_id!r}")
        seen_regions.add(region_id)

        if isinstance(structural_context_path, str) and structural_context_path:
            image_path = structural_context_path
            evidence_label = f"structural:{region_id}:context"
        elif isinstance(crop_path, str) and crop_path:
            image_path = crop_path
            evidence_label = f"structural:{region_id}:crop"
        else:
            raise StructuralContextError(
                f"reader region {region_id!r} requires crop_path or structural_context_path"
            )

        queries.append(
            StructuralRegionQuery(
                query_id=f"S{index:03d}",
                region_id=region_id,
                image_path=image_path,
                evidence_label=evidence_label,
            )
        )

    return StructuralContextQueryPlan(
        queries=queries,
        rules={
            "read_only_query_image": True,
            "open_unlisted_images": False,
            "scan_workspace": False,
            "report_only_view_kind_and_direct_overall_dimensions": True,
            "report_only_explicit_rotational_symmetry_axis": True,
            "require_explicit_rotational_symmetry_decision": True,
            "allow_nonsection_longitudinal_revolved_profile": True,
            "allow_axial_section_without_drawn_centerline": True,
            "require_centerline_for_nonsection_rotation": True,
            "require_unique_section_symmetry_axis_without_centerline": True,
            "require_section_semantics_without_centerline": True,
            "solid_profile_line_is_not_centerline": True,
            "mirror_symmetry_alone_insufficient": True,
            "require_paired_coaxial_profile_for_rotation": True,
            "not_established_requires_counterevidence": True,
            "insufficient_rotation_evidence_is_unresolved": True,
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
                    "rotational_symmetry": None,
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
    rotational_facts: list[PartialRotationalSymmetryFact] = []

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
        rotation_decision = answer.rotational_symmetry
        if rotation_decision is None:
            raise StructuralContextError(
                f"query {query.query_id!r} has no explicit rotational symmetry decision"
            )
        _assert_evidence(
            rotation_decision.evidence,
            query.evidence_label,
            query_id=query.query_id,
        )
        if rotation_decision.status == "established":
            rotation_axis = rotation_decision.axis
            if rotation_axis is None:
                raise StructuralContextError(
                    f"query {query.query_id!r} established rotational symmetry has no axis"
                )
            if rotation_axis not in visible_axes:
                raise StructuralContextError(
                    f"query {query.query_id!r} rotational symmetry axis "
                    f"{rotation_axis!r} is not visible "
                    f"in {answer.view_kind!r} view"
                )
            rotational_facts.append(
                PartialRotationalSymmetryFact(
                    axis=rotation_axis,
                    evidence=rotation_decision.evidence,
                )
            )

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

    direct_values: dict[Axis, float] = {}
    for axis in ("X", "Y", "Z"):
        values = by_axis[axis]
        if not values:
            continue
        reference = values[0]
        if any(not math.isclose(value, reference, abs_tol=1e-9) for value in values[1:]):
            raise StructuralContextError(
                f"conflicting structural overall facts for axis {axis}: {values}"
            )
        direct_values[axis] = reference

    rotational_axes = {item.axis for item in rotational_facts}
    if len(rotational_axes) > 1:
        raise StructuralContextError(
            f"conflicting structural rotational symmetry axes: {sorted(rotational_axes)}"
        )

    merged_rotational_facts: list[PartialRotationalSymmetryFact] = []
    rotation_axis = next(iter(rotational_axes), None)
    if rotation_axis is not None:
        evidence = list(
            dict.fromkeys(
                label
                for item in rotational_facts
                for label in item.evidence
            )
        )
        merged_rotational_facts.append(
            PartialRotationalSymmetryFact(
                axis=rotation_axis,
                evidence=evidence,
            )
        )

        transverse_axes = [
            axis for axis in ("X", "Y", "Z") if axis != rotation_axis
        ]
        known_transverse = [
            axis for axis in transverse_axes if axis in direct_values
        ]
        if len(known_transverse) == 2 and not math.isclose(
            direct_values[known_transverse[0]],
            direct_values[known_transverse[1]],
            abs_tol=1e-9,
        ):
            raise StructuralContextError(
                "rotational symmetry conflicts with direct transverse overall facts: "
                f"{known_transverse[0]}={direct_values[known_transverse[0]]}, "
                f"{known_transverse[1]}={direct_values[known_transverse[1]]}"
            )

    missing_axes = [
        axis for axis in ("X", "Y", "Z") if axis not in direct_values
    ]
    if missing_axes:
        derivable = False
        if rotation_axis is not None and len(missing_axes) == 1:
            missing_axis = missing_axes[0]
            transverse_axes = [
                axis for axis in ("X", "Y", "Z") if axis != rotation_axis
            ]
            if missing_axis in transverse_axes:
                source_axis = next(
                    axis for axis in transverse_axes if axis != missing_axis
                )
                derivable = source_axis in direct_values
        if not derivable:
            raise StructuralContextError(
                f"missing structural overall fact for axis {missing_axes[0]}"
            )

    return HybridAdapterContext(
        region_views=region_views,
        overall_dimension_facts=overall_facts,
        rotational_symmetry_facts=merged_rotational_facts,
        confirmed_start_sides=[],
    )
