from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Axis = Literal["X", "Y", "Z"]
RelationKind = Literal[
    "edge_offset",
    "alignment",
    "center_spacing",
    "center_distance",
    "upper_tangent",
    "lower_tangent",
    "symmetry",
]
ViewKind = Literal["front", "side", "top"]
ProjectionShape = Literal[
    "circle",
    "concentric_circles",
    "hidden_parallel",
    "slot_edges",
    "profile",
    "other",
]
EndpointRole = Literal[
    "overall_min",
    "overall_max",
    "feature_center",
]


class OverallDimensions(BaseModel):
    """Global extents in the fixed part_center_xy_bottom_z0 frame."""

    length_x: float = Field(gt=0)
    width_y: float = Field(gt=0)
    height_z: float = Field(gt=0)


class DirectValueEvidence(BaseModel):
    """One directly observed semantic value with stable evidence identity.

    The extractor reports the target/value pair. The semantic-draft assembler
    maps the target shape to the existing Gate A source semantic whenever that
    mapping is deterministic.
    """

    id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    value: Any
    semantic: str | None = None
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("source_ids")
    @classmethod
    def _source_ids_are_unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in value if item))


class CoordinateFact(BaseModel):
    """Legacy/simple numeric coordinate evidence used by the resolver.

    New Evidence Extraction should prefer DirectValueEvidence so the same
    evidence can also be serialized into the Gate A source ledger.
    """

    target: str = Field(min_length=1)
    axis: Axis
    value: float
    source_ids: list[str] = Field(default_factory=list)


class ViewEvidence(BaseModel):
    """A standard orthographic view identified by the visual stage."""

    id: str = Field(min_length=1)
    kind: ViewKind
    source_ids: list[str] = Field(default_factory=list)


class ProjectionEvidence(BaseModel):
    """One view-local projection observation for a candidate feature identity."""

    id: str = Field(min_length=1)
    feature_id: str = Field(min_length=1)
    view_id: str = Field(min_length=1)
    shape: ProjectionShape
    source_ids: list[str] = Field(default_factory=list)
    required_for_modeling: bool = True


class DimensionEndpoint(BaseModel):
    """Physical endpoint identity before relation semantics are assigned."""

    role: EndpointRole
    target: str | None = None

    @model_validator(mode="after")
    def _validate_endpoint(self) -> "DimensionEndpoint":
        if self.role == "feature_center" and not self.target:
            raise ValueError("feature_center endpoint requires target")
        if self.role in {"overall_min", "overall_max"} and self.target is not None:
            raise ValueError(f"{self.role} endpoint must not carry target")
        return self


class DimensionObservation(BaseModel):
    """Raw dimension ownership evidence.

    The visual stage records physical endpoints and measured axis. It does not
    choose edge_offset/center_spacing/center_distance semantics.
    """

    id: str = Field(min_length=1)
    value: float = Field(gt=0)
    axis: Axis
    endpoints: list[DimensionEndpoint] = Field(min_length=2, max_length=2)
    direction: Literal[-1, 1] | None = None
    source_ids: list[str] = Field(default_factory=list)
    required_for_modeling: bool = True


class RelationEvidence(BaseModel):
    """A formal geometry relation extracted from physical drawing evidence.

    Normally these are emitted by the deterministic compiler. They remain in
    the schema for relations that are already explicit and machine-identifiable.
    """

    id: str = Field(min_length=1)
    kind: RelationKind
    axis: Axis
    targets: list[str] = Field(min_length=1)
    value: float | None = None
    from_side: Literal["min", "max"] | None = None
    direction: Literal[-1, 1] | None = None
    diameter_target: str | None = None
    about: float | None = None
    feature_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    required_for_modeling: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("targets")
    @classmethod
    def _targets_are_unique(cls, value: list[str]) -> list[str]:
        if any(not target for target in value):
            raise ValueError("relation targets must be non-empty")
        if len(set(value)) != len(value):
            raise ValueError("relation targets must be unique")
        return value

    @model_validator(mode="after")
    def _validate_shape(self) -> "RelationEvidence":
        if self.kind == "edge_offset":
            if self.value is None or self.from_side is None:
                raise ValueError("edge_offset requires value and from_side")
        elif self.kind in {"center_spacing", "center_distance"}:
            if self.value is None or len(self.targets) != 2:
                raise ValueError(f"{self.kind} requires value and exactly two targets")
        elif self.kind == "alignment":
            if len(self.targets) < 2:
                raise ValueError("alignment requires at least two targets")
        elif self.kind in {"upper_tangent", "lower_tangent"}:
            if len(self.targets) != 2 or not self.diameter_target:
                raise ValueError(
                    f"{self.kind} requires [center_target, tangent_target] "
                    "and diameter_target"
                )
        elif self.kind == "symmetry":
            if len(self.targets) != 2 or self.about is None or not self.feature_id:
                raise ValueError(
                    "symmetry requires exactly two targets, numeric about, and feature_id"
                )
        return self


class EvidenceGraph(BaseModel):
    """Machine-readable output of the visual evidence extraction stage."""

    schema_version: Literal["1.0"] = "1.0"
    coordinate_system: Literal["part_center_xy_bottom_z0"] = "part_center_xy_bottom_z0"
    overall_dimensions: OverallDimensions
    views: list[ViewEvidence] = Field(default_factory=list)
    projections: list[ProjectionEvidence] = Field(default_factory=list)
    dimensions: list[DimensionObservation] = Field(default_factory=list)
    direct_values: list[DirectValueEvidence] = Field(default_factory=list)
    direct_facts: list[CoordinateFact] = Field(default_factory=list)
    relations: list[RelationEvidence] = Field(default_factory=list)
    required_targets: list[str] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_evidence: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("required_targets")
    @classmethod
    def _required_targets_are_unique(cls, value: list[str]) -> list[str]:
        if any(not target for target in value):
            raise ValueError("required targets must be non-empty")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _stable_ids_are_unique(self) -> "EvidenceGraph":
        ids = (
            [item.id for item in self.views]
            + [item.id for item in self.projections]
            + [item.id for item in self.dimensions]
            + [item.id for item in self.direct_values]
            + [item.id for item in self.relations]
        )
        if len(ids) != len(set(ids)):
            raise ValueError("evidence ids must be globally unique")
        return self
