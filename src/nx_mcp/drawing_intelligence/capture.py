from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import Axis, OverallDimensions, ProjectionShape, ViewKind


class _StrictCaptureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaptureView(_StrictCaptureModel):
    """One standard view observed by the visual Reader."""

    id: str = Field(min_length=1)
    kind: ViewKind
    source_ids: list[str] = Field(default_factory=list)


CaptureCrossViewDisposition = Literal["associated", "unresolved", "single_view"]


class CaptureEntity(_StrictCaptureModel):
    """One view-local visual entity.

    This is deliberately not a physical feature identity. The same physical
    feature may have one CaptureEntity per orthographic view.
    """

    id: str = Field(min_length=1)
    view_id: str = Field(min_length=1)
    shape: ProjectionShape
    cross_view_disposition: CaptureCrossViewDisposition | None = None
    source_ids: list[str] = Field(default_factory=list)
    required_for_modeling: bool = True


AssociationEvidenceKind = Literal[
    "projection_alignment",
    "shared_centerline",
    "shared_center_mark",
    "leader_correspondence",
    "matching_specification",
    "explicit_section_correspondence",
]


class AssociationClaim(_StrictCaptureModel):
    """Visual evidence that view-local entities may depict one physical feature."""

    id: str = Field(min_length=1)
    entity_ids: list[str] = Field(min_length=2)
    basis: list[AssociationEvidenceKind] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    required_for_modeling: bool = True

    @field_validator("entity_ids")
    @classmethod
    def _unique_entities(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("association entity_ids must be unique")
        return value

    @field_validator("basis")
    @classmethod
    def _unique_basis(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("association basis entries must be unique")
        return value


class CaptureValue(_StrictCaptureModel):
    """Direct semantic value attached to one view-local entity."""

    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    value: Any
    semantic: str | None = None
    source_ids: list[str] = Field(default_factory=list)


CaptureEndpointRole = Literal[
    "overall_min",
    "overall_max",
    "entity_center",
    "unresolved",
]
DimensionEndpointEvidenceKind = Literal[
    "centerline",
    "center_mark",
    "explicit_midline",
]


class CaptureDimensionEndpoint(_StrictCaptureModel):
    role: CaptureEndpointRole
    entity_id: str | None = None
    candidate_entity_ids: list[str] = Field(default_factory=list)
    basis: DimensionEndpointEvidenceKind | None = None

    @field_validator("candidate_entity_ids")
    @classmethod
    def _unique_candidate_entity_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("dimension endpoint candidate_entity_ids must be unique")
        return value

    @model_validator(mode="after")
    def _shape(self) -> "CaptureDimensionEndpoint":
        if self.role == "entity_center":
            if not self.entity_id:
                raise ValueError("entity_center endpoint requires entity_id")
            if self.candidate_entity_ids:
                raise ValueError(
                    "entity_center endpoint must not carry candidate_entity_ids"
                )
        elif self.role in {"overall_min", "overall_max"}:
            if self.entity_id is not None:
                raise ValueError(f"{self.role} endpoint must not carry entity_id")
            if self.basis is not None:
                raise ValueError(f"{self.role} endpoint must not carry center basis")
            if self.candidate_entity_ids:
                raise ValueError(
                    f"{self.role} endpoint must not carry candidate_entity_ids"
                )
        else:
            if self.entity_id is not None:
                raise ValueError("unresolved endpoint must not carry entity_id")
            if self.basis is not None:
                raise ValueError("unresolved endpoint must not carry center basis")
        return self


class CaptureDimension(_StrictCaptureModel):
    id: str = Field(min_length=1)
    value: float = Field(gt=0)
    axis: Axis
    endpoints: list[CaptureDimensionEndpoint] = Field(min_length=2, max_length=2)
    unresolved_reason: str | None = None
    direction: Literal[-1, 1] | None = None
    source_ids: list[str] = Field(default_factory=list)
    required_for_modeling: bool = True

    @model_validator(mode="after")
    def _unresolved_shape(self) -> "CaptureDimension":
        has_unresolved = any(
            endpoint.role == "unresolved"
            for endpoint in self.endpoints
        )
        if has_unresolved and not self.unresolved_reason:
            raise ValueError(
                "dimension with unresolved endpoint requires unresolved_reason"
            )
        if not has_unresolved and self.unresolved_reason is not None:
            raise ValueError(
                "resolved dimension must not carry unresolved_reason"
            )
        return self


class CaptureDatumAlignment(_StrictCaptureModel):
    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    axis: Axis
    datum: Literal["overall_center"] = "overall_center"
    source_ids: list[str] = Field(default_factory=list)
    required_for_modeling: bool = True


class CaptureRequiredTarget(_StrictCaptureModel):
    entity_id: str = Field(min_length=1)
    field: str = Field(min_length=1)


CaptureUnresolvedKind = Literal[
    "cross_view_identity",
    "dimension_endpoint",
    "feature_inventory",
    "feature_value",
    "member_identity",
    "start_side",
    "termination",
    "local_surface",
    "unsupported_representation",
    "other",
]


class CaptureUnresolvedEvidence(_StrictCaptureModel):
    id: str = Field(min_length=1)
    kind: CaptureUnresolvedKind = "other"
    reason: str = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    dimension_id: str | None = None
    dimension_value: float | None = Field(default=None, gt=0)
    field: str | None = None
    axis: Axis | None = None
    source_ids: list[str] = Field(default_factory=list)
    required_for_modeling: bool = True

    @field_validator("entity_ids")
    @classmethod
    def _unique_entity_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("unresolved entity_ids must be unique")
        return value


class ReaderCapture(_StrictCaptureModel):
    """Reader Capture v2: visual observations before physical feature identity."""

    schema_version: Literal["2.0"] = "2.0"
    coordinate_system: Literal["part_center_xy_bottom_z0"] = "part_center_xy_bottom_z0"
    overall_dimensions: OverallDimensions
    views: list[CaptureView] = Field(default_factory=list)
    entities: list[CaptureEntity] = Field(default_factory=list)
    associations: list[AssociationClaim] = Field(default_factory=list)
    values: list[CaptureValue] = Field(default_factory=list)
    dimensions: list[CaptureDimension] = Field(default_factory=list)
    datum_alignments: list[CaptureDatumAlignment] = Field(default_factory=list)
    required_targets: list[CaptureRequiredTarget] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_evidence: list[CaptureUnresolvedEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _strict_overall_dimensions(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        overall = value.get("overall_dimensions")
        if not isinstance(overall, dict):
            return value

        allowed = {"length_x", "width_y", "height_z"}
        extra = sorted(set(overall) - allowed)
        if extra:
            raise ValueError(
                f"overall_dimensions contains unexpected fields {extra}"
            )

        for key in sorted(allowed):
            if key not in overall:
                continue
            raw = overall[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(
                    f"overall_dimensions.{key} must be a numeric scalar"
                )
        return value

    @field_validator("observations", mode="before")
    @classmethod
    def _normalize_observations(cls, value: Any) -> list[dict[str, Any]]:
        """Normalize Reader prose observations without changing semantics.

        Agent/VLM first-pass output commonly emits observations as plain
        strings. They are representation-only notes, so preserve them
        deterministically as structured text records instead of rejecting the
        whole capture.
        """

        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("observations must be a list")

        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str):
                normalized.append(
                    {
                        "kind": "reader_observation",
                        "text": item,
                        "capture_index": index,
                    }
                )
            else:
                raise ValueError(
                    "observation entries must be objects or strings"
                )
        return normalized

    @model_validator(mode="after")
    def _ids_and_references(self) -> "ReaderCapture":
        view_ids = [item.id for item in self.views]
        entity_ids = [item.id for item in self.entities]

        if len(view_ids) != len(set(view_ids)):
            raise ValueError("capture view ids must be unique")
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("capture entity ids must be unique")

        view_set = set(view_ids)
        entity_set = set(entity_ids)

        for entity in self.entities:
            if entity.view_id not in view_set:
                raise ValueError(
                    f"entity {entity.id!r} references unknown view {entity.view_id!r}"
                )

        for association in self.associations:
            missing = [item for item in association.entity_ids if item not in entity_set]
            if missing:
                raise ValueError(
                    f"association {association.id!r} references unknown entities {missing}"
                )

        for value in self.values:
            if value.entity_id not in entity_set:
                raise ValueError(
                    f"value {value.id!r} references unknown entity {value.entity_id!r}"
                )

        for dimension in self.dimensions:
            for endpoint in dimension.endpoints:
                if (
                    endpoint.role == "entity_center"
                    and endpoint.entity_id not in entity_set
                ):
                    raise ValueError(
                        f"dimension {dimension.id!r} references unknown entity "
                        f"{endpoint.entity_id!r}"
                    )
                missing_candidates = [
                    item
                    for item in endpoint.candidate_entity_ids
                    if item not in entity_set
                ]
                if missing_candidates:
                    raise ValueError(
                        f"dimension {dimension.id!r} references unknown candidate "
                        f"entities {missing_candidates}"
                    )

        for alignment in self.datum_alignments:
            if alignment.entity_id not in entity_set:
                raise ValueError(
                    f"datum alignment {alignment.id!r} references unknown entity "
                    f"{alignment.entity_id!r}"
                )

        for target in self.required_targets:
            if target.entity_id not in entity_set:
                raise ValueError(
                    f"required target references unknown entity {target.entity_id!r}"
                )

        for unresolved in self.unresolved_evidence:
            missing = [
                item
                for item in unresolved.entity_ids
                if item not in entity_set
            ]
            if missing:
                raise ValueError(
                    f"unresolved {unresolved.id!r} references unknown entities {missing}"
                )

        ids = (
            [item.id for item in self.associations]
            + [item.id for item in self.values]
            + [item.id for item in self.dimensions]
            + [item.id for item in self.datum_alignments]
            + [item.id for item in self.unresolved_evidence]
        )
        if len(ids) != len(set(ids)):
            raise ValueError("capture evidence ids must be unique")

        return self



CANONICAL_CAPTURE_VALUE_FIELDS = frozenset(
    {
        "diameter",
        "fit",
        "thread_spec",
        "thread_depth",
        "depth",
        "count",
        "through",
        "width",
        "counterbore_diameter",
        "counterbore_depth",
        "type",
    }
)


def validate_reader_capture_contract(capture: ReaderCapture) -> list[str]:
    """Return current-production Capture v2 contract violations.

    This is intentionally stricter than legacy compatibility normalization in
    the identity linker. New Reader output must use the canonical contract.
    """

    errors: list[str] = []

    if capture.required_targets:
        errors.append("required_targets must be [] for new Capture v2 output")

    for association in capture.associations:
        if not association.basis:
            errors.append(
                f"association {association.id!r} requires structured visual basis"
            )

    for dimension in capture.dimensions:
        for endpoint in dimension.endpoints:
            if endpoint.role == "entity_center" and endpoint.basis is None:
                errors.append(
                    f"dimension {dimension.id!r} entity_center endpoint "
                    "requires centerline/center_mark/explicit_midline basis"
                )

    entity_fields: dict[str, set[str]] = {}
    for item in capture.values:
        entity_fields.setdefault(item.entity_id, set()).add(item.field)
        if item.field not in CANONICAL_CAPTURE_VALUE_FIELDS:
            errors.append(
                f"value {item.id!r} uses non-canonical field {item.field!r}"
            )

    for entity_id, fields in sorted(entity_fields.items()):
        if "thread_spec" in fields and "depth" in fields:
            errors.append(
                f"threaded entity {entity_id!r} must use thread_depth, not depth"
            )

    for entity in capture.entities:
        if entity.id.startswith("F_"):
            errors.append(
                f"entity {entity.id!r} looks like a final physical feature id"
            )

    for item in capture.unresolved_evidence:
        if item.required_for_modeling and item.kind == "other":
            errors.append(
                f"blocking unresolved {item.id!r} must use a structured kind"
            )
        if item.kind == "dimension_endpoint":
            if item.dimension_value is None:
                errors.append(
                    f"dimension unresolved {item.id!r} requires dimension_value"
                )
            if item.axis is None:
                errors.append(
                    f"dimension unresolved {item.id!r} requires axis"
                )

    return errors
