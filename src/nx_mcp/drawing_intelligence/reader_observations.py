from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .capture import (
    AssociationEvidenceKind,
    CaptureCrossViewDisposition,
    CaptureEndpointRole,
    CaptureEndpointUnresolvedKind,
    DimensionEndpointEvidenceKind,
    ReaderCapture,
    validate_reader_capture_contract,
)
from .evidence import Axis, OverallDimensions, ProjectionShape, ViewKind

ReaderObservationUnresolvedKind = Literal[
    "cross_view_identity",
    "feature_inventory",
    "feature_value",
    "member_identity",
    "start_side",
    "termination",
    "local_surface",
    "unsupported_representation",
    "other",
]


class ReaderObservationAssemblyError(ValueError):
    """Raised when compact visual observations cannot form a valid ReaderCapture."""


class _StrictObservationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _clean_evidence(value: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    if not cleaned:
        raise ValueError("evidence must contain at least one non-empty source label")
    return cleaned


class ObservationView(_StrictObservationModel):
    key: str = Field(min_length=1)
    kind: ViewKind
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class ObservationEntity(_StrictObservationModel):
    key: str = Field(min_length=1)
    view_key: str = Field(min_length=1)
    shape: ProjectionShape
    cross_view_disposition: CaptureCrossViewDisposition | None = None
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class ObservationAssociation(_StrictObservationModel):
    entity_keys: list[str] = Field(min_length=2)
    basis: list[AssociationEvidenceKind] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    @field_validator("entity_keys", "basis")
    @classmethod
    def _unique_list(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("association lists must contain unique entries")
        return value

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class ObservationValue(_StrictObservationModel):
    entity_key: str = Field(min_length=1)
    field: str = Field(min_length=1)
    value: Any
    semantic: str | None = None
    evidence: list[str] = Field(min_length=1)

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class ObservationDimensionEndpoint(_StrictObservationModel):
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
    def _shape(self) -> ObservationDimensionEndpoint:
        if self.role == "entity_center":
            if not self.entity_key:
                raise ValueError("entity_center endpoint requires entity_key")
            if self.candidate_entity_keys:
                raise ValueError("entity_center endpoint must not carry candidate_entity_keys")
            if self.unresolved_kind is not None:
                raise ValueError("entity_center endpoint must not carry unresolved_kind")
            if self.basis is None:
                raise ValueError(
                    "entity_center endpoint requires centerline/center_mark/explicit_midline basis, or circle_center basis"
                )
        elif self.role in {"overall_min", "overall_max"}:
            if self.entity_key is not None:
                raise ValueError(f"{self.role} endpoint must not carry entity_key")
            if self.candidate_entity_keys:
                raise ValueError(f"{self.role} endpoint must not carry candidate_entity_keys")
            if self.basis is not None:
                raise ValueError(f"{self.role} endpoint must not carry basis")
            if self.unresolved_kind is not None:
                raise ValueError(f"{self.role} endpoint must not carry unresolved_kind")
        else:
            if self.entity_key is not None:
                raise ValueError("unresolved endpoint must not carry entity_key")
            if self.basis is not None:
                raise ValueError("unresolved endpoint must not carry center basis")
            if self.unresolved_kind is None:
                raise ValueError("unresolved endpoint requires unresolved_kind")
            if self.unresolved_kind == "ambiguous_owner" and not self.candidate_entity_keys:
                raise ValueError("ambiguous_owner endpoint requires candidate_entity_keys")
            if self.unresolved_kind != "ambiguous_owner" and self.candidate_entity_keys:
                raise ValueError(
                    f"{self.unresolved_kind} endpoint must not carry candidate_entity_keys"
                )
        return self


class ObservationDimension(_StrictObservationModel):
    key: str = Field(min_length=1)
    value: float = Field(gt=0)
    axis: Axis
    endpoints: list[ObservationDimensionEndpoint] = Field(min_length=2, max_length=2)
    unresolved_reason: str | None = None
    direction: Literal[-1, 1] | None = None
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _unresolved_shape(self) -> ObservationDimension:
        has_unresolved = any(item.role == "unresolved" for item in self.endpoints)
        if has_unresolved and not self.unresolved_reason:
            raise ValueError("dimension with unresolved endpoint requires unresolved_reason")
        if not has_unresolved and self.unresolved_reason is not None:
            raise ValueError("resolved dimension must not carry unresolved_reason")
        return self


class ObservationDatumAlignment(_StrictObservationModel):
    entity_key: str = Field(min_length=1)
    axis: Axis
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    _validate_evidence = field_validator("evidence")(_clean_evidence)


class ObservationUnresolved(_StrictObservationModel):
    kind: ReaderObservationUnresolvedKind
    reason: str = Field(min_length=1)
    entity_keys: list[str] = Field(default_factory=list)
    dimension_key: str | None = None
    dimension_value: float | None = Field(default=None, gt=0)
    field: str | None = None
    axis: Axis | None = None
    basis: list[AssociationEvidenceKind] = Field(default_factory=list)
    evidence: list[str] = Field(min_length=1)
    required_for_modeling: bool = True

    @field_validator("entity_keys", "basis")
    @classmethod
    def _unique_list(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("unresolved lists must contain unique entries")
        return value

    _validate_evidence = field_validator("evidence")(_clean_evidence)

    @model_validator(mode="after")
    def _semantic_shape(self) -> ObservationUnresolved:
        if self.kind == "feature_value":
            if len(self.entity_keys) != 1:
                raise ValueError("feature_value unresolved requires exactly one entity_key")
            if not self.field:
                raise ValueError("feature_value unresolved requires the ambiguous field")
        return self


class ReaderObservations(_StrictObservationModel):
    schema_version: Literal["reader-observations-v1"] = Field(
        default="reader-observations-v1",
        alias="schema",
    )
    overall_dimensions: OverallDimensions
    views: list[ObservationView] = Field(min_length=1)
    entities: list[ObservationEntity] = Field(default_factory=list)
    associations: list[ObservationAssociation] = Field(default_factory=list)
    values: list[ObservationValue] = Field(default_factory=list)
    dimensions: list[ObservationDimension] = Field(default_factory=list)
    datum_alignments: list[ObservationDatumAlignment] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[ObservationUnresolved] = Field(default_factory=list)

    @model_validator(mode="after")
    def _keys_and_references(self) -> ReaderObservations:
        view_keys = [item.key for item in self.views]
        entity_keys = [item.key for item in self.entities]
        dimension_keys = [item.key for item in self.dimensions]

        for label, keys in (
            ("view", view_keys),
            ("entity", entity_keys),
            ("dimension", dimension_keys),
        ):
            if len(keys) != len(set(keys)):
                raise ValueError(f"{label} keys must be unique")

        view_set = set(view_keys)
        entity_set = set(entity_keys)
        dimension_set = set(dimension_keys)

        for entity in self.entities:
            if entity.view_key not in view_set:
                raise ValueError(
                    f"entity {entity.key!r} references unknown view {entity.view_key!r}"
                )

        for association in self.associations:
            missing = [item for item in association.entity_keys if item not in entity_set]
            if missing:
                raise ValueError(f"association references unknown entity keys {missing}")

        for value in self.values:
            if value.entity_key not in entity_set:
                raise ValueError(f"value references unknown entity key {value.entity_key!r}")

        for dimension in self.dimensions:
            for endpoint in dimension.endpoints:
                if endpoint.entity_key is not None and endpoint.entity_key not in entity_set:
                    raise ValueError(
                        f"dimension {dimension.key!r} references unknown entity "
                        f"{endpoint.entity_key!r}"
                    )
                missing_candidates = [
                    item for item in endpoint.candidate_entity_keys if item not in entity_set
                ]
                if missing_candidates:
                    raise ValueError(
                        f"dimension {dimension.key!r} references unknown "
                        f"candidate entities {missing_candidates}"
                    )

        for alignment in self.datum_alignments:
            if alignment.entity_key not in entity_set:
                raise ValueError(
                    f"datum alignment references unknown entity key {alignment.entity_key!r}"
                )

        for unresolved in self.unresolved:
            missing = [item for item in unresolved.entity_keys if item not in entity_set]
            if missing:
                raise ValueError(f"unresolved references unknown entity keys {missing}")
            if (
                unresolved.dimension_key is not None
                and unresolved.dimension_key not in dimension_set
            ):
                raise ValueError(
                    f"unresolved references unknown dimension key {unresolved.dimension_key!r}"
                )

        return self


def _mapped(
    mapping: dict[str, str],
    key: str,
    label: str,
) -> str:
    try:
        return mapping[key]
    except KeyError as exc:
        raise ReaderObservationAssemblyError(f"unknown {label} key {key!r}") from exc


def assemble_reader_capture(observations: ReaderObservations) -> ReaderCapture:
    """Compile compact visual observations into ReaderCapture without inference."""

    view_ids = {item.key: f"V{index:03d}" for index, item in enumerate(observations.views, start=1)}
    entity_ids = {
        item.key: f"E{index:03d}" for index, item in enumerate(observations.entities, start=1)
    }
    dimension_ids = {
        item.key: f"D{index:03d}" for index, item in enumerate(observations.dimensions, start=1)
    }

    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "coordinate_system": "part_center_xy_bottom_z0",
        "overall_dimensions": observations.overall_dimensions.model_dump(),
        "views": [
            {
                "id": view_ids[item.key],
                "kind": item.kind,
                "source_ids": item.evidence,
            }
            for item in observations.views
        ],
        "entities": [
            {
                "id": entity_ids[item.key],
                "view_id": _mapped(view_ids, item.view_key, "view"),
                "shape": item.shape,
                "cross_view_disposition": item.cross_view_disposition,
                "source_ids": item.evidence,
                "required_for_modeling": item.required_for_modeling,
            }
            for item in observations.entities
        ],
        "associations": [],
        "values": [],
        "dimensions": [],
        "datum_alignments": [],
        "required_targets": [],
        "observations": observations.observations,
        "unresolved_evidence": [],
    }

    for index, association in enumerate(observations.associations, start=1):
        payload["associations"].append(
            {
                "id": f"A{index:03d}",
                "entity_ids": [
                    _mapped(entity_ids, key, "entity") for key in association.entity_keys
                ],
                "basis": association.basis,
                "source_ids": association.evidence,
                "required_for_modeling": association.required_for_modeling,
            }
        )

    for index, value_item in enumerate(observations.values, start=1):
        payload["values"].append(
            {
                "id": f"VAL{index:03d}",
                "entity_id": _mapped(
                    entity_ids,
                    value_item.entity_key,
                    "entity",
                ),
                "field": value_item.field,
                "value": value_item.value,
                "semantic": value_item.semantic,
                "source_ids": value_item.evidence,
            }
        )

    for dimension in observations.dimensions:
        endpoints: list[dict[str, Any]] = []
        for endpoint in dimension.endpoints:
            endpoint_payload: dict[str, Any] = {
                "role": endpoint.role,
                "entity_id": None,
                "candidate_entity_ids": [],
                "basis": endpoint.basis,
                "unresolved_kind": endpoint.unresolved_kind,
                "source_ids": endpoint.evidence,
            }
            if endpoint.entity_key is not None:
                endpoint_payload["entity_id"] = _mapped(
                    entity_ids,
                    endpoint.entity_key,
                    "entity",
                )
            endpoint_payload["candidate_entity_ids"] = [
                _mapped(entity_ids, key, "candidate entity")
                for key in endpoint.candidate_entity_keys
            ]
            endpoints.append(endpoint_payload)

        payload["dimensions"].append(
            {
                "id": dimension_ids[dimension.key],
                "value": dimension.value,
                "axis": dimension.axis,
                "endpoints": endpoints,
                "unresolved_reason": dimension.unresolved_reason,
                "direction": dimension.direction,
                "source_ids": dimension.evidence,
                "required_for_modeling": dimension.required_for_modeling,
            }
        )

    for index, alignment in enumerate(observations.datum_alignments, start=1):
        payload["datum_alignments"].append(
            {
                "id": f"DA{index:03d}",
                "entity_id": _mapped(
                    entity_ids,
                    alignment.entity_key,
                    "entity",
                ),
                "axis": alignment.axis,
                "datum": "overall_center",
                "source_ids": alignment.evidence,
                "required_for_modeling": alignment.required_for_modeling,
            }
        )

    for index, unresolved in enumerate(observations.unresolved, start=1):
        payload["unresolved_evidence"].append(
            {
                "id": f"U{index:03d}",
                "kind": unresolved.kind,
                "reason": unresolved.reason,
                "entity_ids": [
                    _mapped(entity_ids, key, "entity") for key in unresolved.entity_keys
                ],
                "dimension_id": (
                    _mapped(
                        dimension_ids,
                        unresolved.dimension_key,
                        "dimension",
                    )
                    if unresolved.dimension_key is not None
                    else None
                ),
                "dimension_value": unresolved.dimension_value,
                "field": unresolved.field,
                "axis": unresolved.axis,
                "basis": unresolved.basis,
                "source_ids": unresolved.evidence,
                "required_for_modeling": unresolved.required_for_modeling,
            }
        )

    try:
        capture = ReaderCapture.model_validate(payload)
    except ValueError as exc:
        raise ReaderObservationAssemblyError(
            f"ReaderCapture schema validation failed: {exc}"
        ) from exc

    contract_errors = validate_reader_capture_contract(capture)
    if contract_errors:
        raise ReaderObservationAssemblyError(
            "ReaderCapture contract validation failed: " + "; ".join(contract_errors)
        )

    return capture
