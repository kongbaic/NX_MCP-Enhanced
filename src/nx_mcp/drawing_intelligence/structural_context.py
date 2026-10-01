from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import Axis, ViewKind
from .hybrid_capture_adapter import (
    HybridAdapterContext,
    HybridLabeledDimensionFact,
    HybridRegionView,
)
from .reader_semantic_answers import (
    PartialOverallDimensionFact,
    PartialRotationalSymmetryFact,
)


class StructuralContextError(ValueError):
    """Raised when minimal structural context cannot be assembled safely."""


_REGION_LOCAL_DEFERRED_UNRESOLVED = {
    "rotational_symmetry_not_visible_in_region",
}


class _StrictStructuralModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _clean_evidence(value: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    if not cleaned:
        raise ValueError("evidence must contain at least one non-empty label")
    return cleaned


class StructuralLabeledDimensionTarget(_StrictStructuralModel):
    """One OCR-read labeled linear value needing only visual relation semantics."""

    target_id: str = Field(min_length=1)
    source_item_index: int = Field(ge=0)
    source_text: str = Field(min_length=1)
    value: float = Field(gt=0)


_LABELED_MM_DIMENSION_RE = re.compile(
    r"(?i)(?P<label>[a-z][a-z0-9_]*)\s*[-=:]\s*"
    r"(?P<value>\d+(?:[.,]\d+)?)\s*mm(?:\b|$)"
)


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) and number > 0 else None


def _ocr_bbox_center(raw: object) -> tuple[float, float] | None:
    if not isinstance(raw, list):
        return None
    points = [
        point
        for point in raw
        if (
            isinstance(point, list)
            and len(point) >= 2
            and not isinstance(point[0], bool)
            and not isinstance(point[1], bool)
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        )
    ]
    if len(points) < 2:
        return None
    return (
        sum(float(point[0]) for point in points) / len(points),
        sum(float(point[1]) for point in points) / len(points),
    )


def _region_source_bbox(region: dict) -> tuple[float, float, float, float] | None:
    raw = region.get("source_bbox_px")
    if not (
        isinstance(raw, list)
        and len(raw) == 4
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in raw
        )
    ):
        return None
    x, y, width, height = (float(value) for value in raw)
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _point_rect_distance(
    point: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> float:
    px, py = point
    x, y, width, height = rect
    right = x + width
    bottom = y + height
    dx = max(x - px, 0.0, px - right)
    dy = max(y - py, 0.0, py - bottom)
    return math.hypot(dx, dy)


def _labeled_dimension_targets_by_region(
    regions: list[object],
    hybrid_report: dict | None,
) -> dict[str, list[StructuralLabeledDimensionTarget]]:
    """Route only explicit labeled-mm OCR items to one unique nearby region.

    Raster positions are used solely to choose which bounded structural query may
    inspect the already OCR-read label.  They never define an engineering value
    or coordinate.
    """

    if hybrid_report is None:
        return {}
    if hybrid_report.get("schema") != "dg-hybrid-ocr-bakeoff-v2":
        raise StructuralContextError(
            "labeled dimension targets require dg-hybrid-ocr-bakeoff-v2"
        )
    coverage = hybrid_report.get("coverage")
    if not isinstance(coverage, dict):
        return {}
    raw_items = coverage.get("unassigned_linear_observations")
    if not isinstance(raw_items, list):
        return {}

    region_boxes: list[
        tuple[str, tuple[float, float, float, float]]
    ] = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "")
        bbox = _region_source_bbox(region)
        if region_id and bbox is not None:
            region_boxes.append((region_id, bbox))

    output: dict[str, list[StructuralLabeledDimensionTarget]] = {}
    seen_sources: set[int] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        source_index = item.get("source_item_index")
        text = item.get("text")
        token_value = _positive_number(item.get("token"))
        center = _ocr_bbox_center(item.get("bbox"))
        if (
            not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or source_index < 0
            or source_index in seen_sources
            or not isinstance(text, str)
            or not text.strip()
            or token_value is None
            or center is None
        ):
            continue

        match = _LABELED_MM_DIMENSION_RE.search(text)
        if match is None:
            continue
        text_value = _positive_number(match.group("value"))
        if text_value is None or not math.isclose(
            text_value,
            token_value,
            abs_tol=max(abs(token_value) * 1e-6, 1e-9),
        ):
            continue

        distances: list[
            tuple[float, str, tuple[float, float, float, float]]
        ] = [
            (_point_rect_distance(center, bbox), region_id, bbox)
            for region_id, bbox in region_boxes
        ]
        distances.sort(key=lambda item: (item[0], item[1]))
        if not distances:
            continue

        nearest_distance, region_id, nearest_bbox = distances[0]
        region_scale = min(nearest_bbox[2], nearest_bbox[3])
        if nearest_distance > max(32.0, region_scale * 0.50):
            continue
        if len(distances) > 1:
            second_distance = distances[1][0]
            if second_distance - nearest_distance < max(
                8.0,
                region_scale * 0.03,
            ):
                continue

        output.setdefault(region_id, []).append(
            StructuralLabeledDimensionTarget(
                target_id=f"LD_{source_index:04d}",
                source_item_index=source_index,
                source_text=text.strip(),
                value=token_value,
            )
        )
        seen_sources.add(source_index)

    for values in output.values():
        values.sort(key=lambda item: (item.source_item_index, item.target_id))
    return output


class StructuralRegionQuery(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    kind: Literal["structural_context"] = "structural_context"
    region_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    evidence_label: str = Field(min_length=1)
    labeled_dimension_targets: list[StructuralLabeledDimensionTarget] = Field(
        default_factory=list
    )
    deterministic_profile_symmetry_axis: Literal["horizontal", "vertical"] | None = None
    deterministic_profile_symmetry_method: Literal[
        "foreground_mirror_consensus_v1"
    ] | None = None
    deterministic_profile_symmetry_overlay: Literal[
        "blue_dashed_topology_axis"
    ] | None = None
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
        target_ids = [
            target.target_id
            for query in self.queries
            for target in query.labeled_dimension_targets
        ]
        source_indices = [
            target.source_item_index
            for query in self.queries
            for target in query.labeled_dimension_targets
        ]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("labeled dimension target ids must be unique")
        if len(source_indices) != len(set(source_indices)):
            raise ValueError("labeled dimension source indices must be unique")
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
    basis: Literal["centerline", "axial_section_symmetry"] | None = None
    centerline_direction: Literal["horizontal", "vertical"] | None = None
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _shape(self) -> StructuralRotationalSymmetryDecision:
        if self.status == "not_established":
            if self.basis is not None or self.centerline_direction is not None:
                raise ValueError(
                    "not_established rotational symmetry requires null visual basis fields"
                )
            return self

        if self.basis is None:
            raise ValueError("established rotational symmetry requires visual basis")
        if self.basis == "centerline" and self.centerline_direction is None:
            raise ValueError("centerline basis requires centerline_direction")
        if (
            self.basis == "axial_section_symmetry"
            and self.centerline_direction is not None
        ):
            raise ValueError(
                "axial_section_symmetry basis forbids centerline_direction"
            )
        return self


class StructuralLabeledDimensionDecision(_StrictStructuralModel):
    target_id: str = Field(min_length=1)
    status: Literal["resolved", "unresolved"]
    visual_direction: Literal["horizontal", "vertical"] | None = None
    relation: Literal[
        "overall_extent",
        "overall_min_to_profile_transition",
        "overall_max_to_profile_transition",
        "between_profile_boundaries",
    ] | None = None
    profile_transition_geometry: Literal[
        "orthogonal",
        "non_orthogonal",
        "mixed",
    ] | None = None
    symmetry_scope: Literal["single", "bilateral"] | None = None
    evidence: list[str] = Field(min_length=1)
    reason: str | None = None

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _shape(self) -> StructuralLabeledDimensionDecision:
        if self.status == "unresolved":
            if (
                self.visual_direction is not None
                or self.relation is not None
                or self.profile_transition_geometry is not None
                or self.symmetry_scope is not None
            ):
                raise ValueError(
                    "unresolved labeled dimension relation forbids semantic fields"
                )
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError(
                    "unresolved labeled dimension relation requires reason"
                )
            return self

        if self.visual_direction is None or self.relation is None:
            raise ValueError(
                "resolved labeled dimension relation requires visual_direction "
                "and relation"
            )
        if self.reason is not None:
            raise ValueError(
                "resolved labeled dimension relation forbids unresolved reason"
            )
        if self.relation == "overall_extent":
            if (
                self.profile_transition_geometry is not None
                or self.symmetry_scope is not None
            ):
                raise ValueError(
                    "overall_extent labeled dimension forbids profile topology fields"
                )
            return self
        if (
            self.profile_transition_geometry is None
            or self.symmetry_scope is None
        ):
            raise ValueError(
                "local labeled dimension relation requires profile topology "
                "and symmetry scope"
            )
        return self


class StructuralRegionAnswer(_StrictStructuralModel):
    query_id: str = Field(min_length=1)
    view_kind: ViewKind | None = None
    evidence: list[str] = Field(default_factory=list)
    overall_dimension_facts: list[StructuralOverallFact] = Field(default_factory=list)
    rotational_symmetry: StructuralRotationalSymmetryDecision | None = Field(...)
    labeled_dimension_decisions: list[StructuralLabeledDimensionDecision] = Field(
        default_factory=list
    )
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
    hybrid_report: dict | None = None,
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

    labeled_targets_by_region = _labeled_dimension_targets_by_region(
        regions,
        hybrid_report,
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

        using_structural_context_image = False
        if isinstance(structural_context_path, str) and structural_context_path:
            image_path = structural_context_path
            evidence_label = f"structural:{region_id}:context"
            using_structural_context_image = True
        elif isinstance(crop_path, str) and crop_path:
            image_path = crop_path
            evidence_label = f"structural:{region_id}:crop"
        else:
            raise StructuralContextError(
                f"reader region {region_id!r} requires crop_path or structural_context_path"
            )

        symmetry_hint = region.get("bilateral_symmetry_hint")
        deterministic_axis: Literal["horizontal", "vertical"] | None = None
        deterministic_method: Literal["foreground_mirror_consensus_v1"] | None = None
        if isinstance(symmetry_hint, dict) and symmetry_hint.get("status") == "established":
            axis_direction = symmetry_hint.get("axis_direction")
            method = symmetry_hint.get("method")
            if axis_direction in {"horizontal", "vertical"}:
                deterministic_axis = axis_direction
            if method == "foreground_mirror_consensus_v1":
                deterministic_method = "foreground_mirror_consensus_v1"

        queries.append(
            StructuralRegionQuery(
                query_id=f"S{index:03d}",
                region_id=region_id,
                image_path=image_path,
                evidence_label=evidence_label,
                labeled_dimension_targets=labeled_targets_by_region.get(
                    region_id,
                    [],
                ),
                deterministic_profile_symmetry_axis=deterministic_axis,
                deterministic_profile_symmetry_method=deterministic_method,
                deterministic_profile_symmetry_overlay=(
                    "blue_dashed_topology_axis"
                    if using_structural_context_image
                    and deterministic_axis is not None
                    and deterministic_method == "foreground_mirror_consensus_v1"
                    else None
                ),
            )
        )

    return StructuralContextQueryPlan(
        queries=queries,
        rules={
            "read_only_query_image": True,
            "open_unlisted_images": False,
            "scan_workspace": False,
            "report_only_view_kind_and_direct_overall_dimensions": True,
            "report_only_visual_rotational_symmetry_basis": True,
            "agent_must_not_report_engineering_rotation_axis": True,
            "agent_must_not_report_axial_section_symmetry_direction": True,
            "axial_section_axis_from_deterministic_profile_symmetry": True,
            "topology_axis_overlay_is_visual_aid_not_centerline": True,
            "centerline_absence_alone_is_not_rotation_counterevidence": True,
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
            "region_local_rotation_unobservable_may_defer": True,
            "global_rotation_closure_remains_fail_closed": True,
            "derive_missing_dimensions": False,
            "cross_view_identity": False,
            "feature_inventory": False,
            "dimension_endpoint_ownership": False,
            "local_feature_values": False,
            "labeled_dimension_value_from_hybrid_ocr_only": True,
            "labeled_dimension_relation_only": True,
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
                    "labeled_dimension_decisions": [
                        {
                            "target_id": target.target_id,
                            "status": "unresolved",
                            "visual_direction": None,
                            "relation": None,
                            "profile_transition_geometry": None,
                            "symmetry_scope": None,
                            "evidence": [query.evidence_label],
                            "reason": "pending_labeled_dimension_relation_read",
                        }
                        for target in query.labeled_dimension_targets
                    ],
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
    rotational_counterevidence: list[str] = []
    labeled_dimension_facts: list[HybridLabeledDimensionFact] = []

    for query in plan.queries:
        answer = answers_by_id[query.query_id]
        unresolved = set(answer.unresolved)
        deferred_local_rotation = bool(unresolved) and unresolved.issubset(
            _REGION_LOCAL_DEFERRED_UNRESOLVED
        )
        if unresolved and not deferred_local_rotation:
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

        target_by_id = {
            item.target_id: item
            for item in query.labeled_dimension_targets
        }
        decision_ids = [
            item.target_id for item in answer.labeled_dimension_decisions
        ]
        if len(decision_ids) != len(set(decision_ids)):
            raise StructuralContextError(
                f"query {query.query_id!r} repeats labeled dimension decision"
            )
        decision_by_id = {
            item.target_id: item
            for item in answer.labeled_dimension_decisions
        }
        if set(decision_by_id) != set(target_by_id):
            missing_targets = sorted(set(target_by_id) - set(decision_by_id))
            extra_targets = sorted(set(decision_by_id) - set(target_by_id))
            raise StructuralContextError(
                f"query {query.query_id!r} labeled dimension decisions mismatch; "
                f"missing={missing_targets}, extra={extra_targets}"
            )
        for target_id in sorted(target_by_id):
            target = target_by_id[target_id]
            decision = decision_by_id[target_id]
            _assert_evidence(
                decision.evidence,
                query.evidence_label,
                query_id=query.query_id,
            )
            if decision.status != "resolved":
                raise StructuralContextError(
                    f"query {query.query_id!r} labeled dimension "
                    f"{target_id!r} remains unresolved: {decision.reason}"
                )
            assert decision.visual_direction is not None
            assert decision.relation is not None
            labeled_dimension_facts.append(
                HybridLabeledDimensionFact(
                    target_id=target.target_id,
                    source_item_index=target.source_item_index,
                    source_text=target.source_text,
                    region_id=query.region_id,
                    value=target.value,
                    axis=getattr(view_axes, decision.visual_direction),
                    relation=decision.relation,
                    profile_transition_geometry=decision.profile_transition_geometry,
                    symmetry_scope=decision.symmetry_scope,
                    evidence=[
                        f"hybrid:whole:{target.source_item_index}",
                        query.evidence_label,
                    ],
                )
            )

        rotation_decision = answer.rotational_symmetry
        if rotation_decision is None and not deferred_local_rotation:
            raise StructuralContextError(
                f"query {query.query_id!r} has no explicit rotational symmetry decision"
            )
        if rotation_decision is not None:
            _assert_evidence(
                rotation_decision.evidence,
                query.evidence_label,
                query_id=query.query_id,
            )
        if rotation_decision is not None and rotation_decision.status == "not_established":
            rotational_counterevidence.extend(rotation_decision.evidence)
        if rotation_decision is not None and rotation_decision.status == "established":
            if rotation_decision.basis == "centerline":
                visual_axis_direction = rotation_decision.centerline_direction
            else:
                visual_axis_direction = query.deterministic_profile_symmetry_axis
                if visual_axis_direction is None:
                    raise StructuralContextError(
                        f"query {query.query_id!r} axial section lacks deterministic "
                        "profile symmetry axis"
                    )
            if visual_axis_direction not in ("horizontal", "vertical"):
                raise StructuralContextError(
                    f"query {query.query_id!r} has no deterministic visual rotation axis"
                )
            rotation_axis = getattr(view_axes, visual_axis_direction)
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
    if rotational_axes and rotational_counterevidence:
        raise StructuralContextError(
            "conflicting structural rotational symmetry evidence: "
            "established rotation conflicts with explicit not_established "
            "counterevidence"
        )
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
        labeled_dimension_facts=labeled_dimension_facts,
    )
