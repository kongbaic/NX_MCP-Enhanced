from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

from .capture import (
    AssociationClaim,
    CaptureDimension,
    ReaderCapture,
    _association_basis_sufficient,
)
from .evidence import (
    Axis,
    DatumAlignmentEvidence,
    DimensionEndpoint,
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    ProjectionEvidence,
    RelationEvidence,
    ViewEvidence,
)


class IdentityLinkError(ValueError):
    """Reader Capture cannot be deterministically linked without guessing."""


@dataclass
class IdentityLinkResult:
    evidence: EvidenceGraph
    entity_to_feature: dict[str, str]
    report: dict[str, Any]


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        a = self.find(left)
        b = self.find(right)
        if a != b:
            self.parent[b] = a


def _canon(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _canon(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canon(item) for item in value]
    return value


_ROTATIONAL_PROFILE_TOPOLOGY_KIND = "hybrid_rotational_profile_topology_ledger"
_VIEW_AXIS_BOUNDARY_KIND = "hybrid_view_axis_boundary_ledger"


def _linked_rotational_profile_topology_observations(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> list[dict[str, Any]]:
    """Attach deterministic physical boundary targets to rotational topology edges.

    The Capture ledger already proves only view-local topology.  This bridge
    adds no geometry: it maps each recorded Capture entity through the
    Identity Linker's physical identity and names the engineering boundary
    target for the edge's constant axis.  Missing/ambiguous identity stays
    unmaterialized and is handled fail-closed downstream.
    """

    observations = copy.deepcopy(capture.observations)
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _ROTATIONAL_PROFILE_TOPOLOGY_KIND
        ):
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_topology_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            edges = item.get("edges")
            if not isinstance(edges, list):
                continue
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                entity_id = edge.get("profile_entity_id")
                axis = str(edge.get("constant_axis") or "").upper()
                if (
                    not isinstance(entity_id, str)
                    or not entity_id
                    or axis not in {"X", "Y", "Z"}
                ):
                    continue
                feature_id = entity_to_feature.get(entity_id)
                if feature_id is None:
                    continue
                edge["physical_feature_id"] = feature_id
                edge["boundary_target"] = (
                    f"feature:{feature_id}.boundary.{axis.lower()}"
                )
    return observations


def _profile_entity_ids_for_ref(
    capture: ReaderCapture,
    ref: str,
) -> list[str]:
    token = f"hybrid:profile-edge:{ref}"
    return sorted(
        item.id
        for item in capture.entities
        if (
            item.shape == "profile"
            and token in item.source_ids
            and not any(
                source_id.startswith("hybrid:profile-vertex:")
                for source_id in item.source_ids
            )
        )
    )


def _overall_extent(capture: ReaderCapture, axis: Axis) -> float:
    return {
        "X": float(capture.overall_dimensions.length_x),
        "Y": float(capture.overall_dimensions.width_y),
        "Z": float(capture.overall_dimensions.height_z),
    }[axis]


def _valid_view_axis_boundary_items(
    capture: ReaderCapture,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _VIEW_AXIS_BOUNDARY_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("status") != "resolved"
                or item.get("engineering_coordinate_inferred_from_pixels")
                is not False
            ):
                continue
            raw_axis = str(item.get("axis") or "").upper()
            if raw_axis == "X":
                axis: Axis = "X"
            elif raw_axis == "Y":
                axis = "Y"
            elif raw_axis == "Z":
                axis = "Z"
            else:
                continue
            raw_value = item.get("overall_dimension_value")
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
                or abs(float(raw_value) - _overall_extent(capture, axis)) > 1e-9
            ):
                continue
            anchors = item.get("anchors")
            if not isinstance(anchors, list):
                continue
            roles = {
                str(anchor.get("role") or "")
                for anchor in anchors
                if isinstance(anchor, dict)
            }
            if roles != {"overall_min", "overall_max"}:
                continue
            output.append(item)
    return output


def _view_axis_boundary_relations(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> list[RelationEvidence]:
    """Bind resolved overall profile extremes to engineering boundary targets.

    The Hybrid ledger proves only which structural profile edge is the min/max
    extreme for an independently known overall dimension. The metric value
    comes from overall dimensions; raster positions are identity evidence only
    and are never converted to engineering coordinates.
    """

    views = {item.id: item for item in capture.views}
    entities = {item.id: item for item in capture.entities}
    relations: list[RelationEvidence] = []
    seen: set[tuple[str, str, str]] = set()

    for item in _valid_view_axis_boundary_items(capture):
        raw_axis = str(item["axis"]).upper()
        if raw_axis == "X":
            axis: Axis = "X"
        elif raw_axis == "Y":
            axis = "Y"
        elif raw_axis == "Z":
            axis = "Z"
        else:
            continue
        for anchor in item.get("anchors", []):
            if not isinstance(anchor, dict):
                continue
            ref = str(anchor.get("ref") or "")
            role = str(anchor.get("role") or "")
            if not ref or role not in {"overall_min", "overall_max"}:
                continue
            entity_ids = _profile_entity_ids_for_ref(capture, ref)
            if len(entity_ids) != 1:
                continue
            entity_id = entity_ids[0]
            feature_id = entity_to_feature.get(entity_id)
            if feature_id is None:
                continue
            key = (feature_id, axis, role)
            if key in seen:
                continue
            seen.add(key)

            entity = entities.get(entity_id)
            view = views.get(entity.view_id) if entity is not None else None
            source_ids = list(
                dict.fromkeys(
                    [
                        f"hybrid:profile-edge:{ref}",
                        *([] if entity is None else entity.source_ids),
                        *([] if view is None else [view.id, *view.source_ids]),
                    ]
                )
            )
            digest = hashlib.sha256(
                "|".join((feature_id, axis, role, ref)).encode("utf-8")
            ).hexdigest()[:12].upper()
            relations.append(
                RelationEvidence(
                    id=f"R_VIEW_AXIS_BOUNDARY_{digest}",
                    kind="edge_offset",
                    axis=axis,
                    value=0.0,
                    from_side="min" if role == "overall_min" else "max",
                    targets=[
                        f"feature:{feature_id}.boundary.{axis.lower()}"
                    ],
                    source_ids=source_ids,
                    required_for_modeling=False,
                    metadata={
                        "basis": (
                            "independent_overall_dimension_plus_"
                            "unique_profile_extremes"
                        ),
                        "overall_role": role,
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_identity_only": True,
                    },
                )
            )
    return relations


def _raw_fields_by_entity(capture: ReaderCapture) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = defaultdict(set)
    for item in capture.values:
        fields[item.entity_id].add(item.field)
    return fields


def _canonical_field(
    capture: ReaderCapture,
    entity_id: str,
    field: str,
) -> str:
    if field == "hole_diameter":
        return "diameter"

    raw_fields = _raw_fields_by_entity(capture).get(entity_id, set())
    if field == "depth" and "thread_spec" in raw_fields:
        return "thread_depth"

    return field


_SYMMETRIC_COUNT_TWO_MARKER = "hybrid:symmetric-count2-overall-center"
_STRUCTURED_SYMMETRIC_COUNT_TWO_KIND = "symmetric_count_two_overall_center"
_STRUCTURED_SYMMETRIC_PROFILE_SPAN_KIND = "hybrid_symmetric_profile_span_ledger"
_PROFILE_SPAN_CENTER_KIND = "hybrid_profile_span_center_ledger"
_DIMENSION_SPAN_CENTER_IDENTITY_KIND = (
    "hybrid_dimension_span_center_identity_ledger"
)
_SYMMETRIC_DIMENSION_PAIR_KIND = "hybrid_symmetric_dimension_pair_ledger"
_PROJECTED_PROFILE_LEVEL_KIND = "hybrid_projected_profile_level_ledger"

_TRANSVERSE_CENTER_INDEX: dict[Axis, dict[Axis, int]] = {
    "X": {"Y": 0, "Z": 1},
    "Y": {"X": 0, "Z": 1},
    "Z": {"X": 0, "Y": 1},
}

_VIEW_NORMAL_AXIS: dict[str, Axis] = {
    "front": "Y",
    "side": "X",
    "top": "Z",
}
_ALL_AXES: tuple[Axis, ...] = ("X", "Y", "Z")
_CIRCULAR_PROJECTION_SHAPES = {"circle", "concentric_circles"}


def _component_axis_from_projections(
    capture: ReaderCapture,
    entity_ids: list[str],
) -> tuple[Axis | None, list[str]]:
    """Infer a principal cylindrical axis from orthographic projection classes."""

    entities = {item.id: item for item in capture.entities}
    views = {item.id: item for item in capture.views}
    candidates: set[Axis] = set(_ALL_AXES)
    evidence: list[str] = []
    constrained = False

    for entity_id in entity_ids:
        entity = entities.get(entity_id)
        if entity is None:
            continue
        view = views.get(entity.view_id)
        if view is None:
            continue
        normal = _VIEW_NORMAL_AXIS[view.kind]

        if entity.shape in _CIRCULAR_PROJECTION_SHAPES:
            allowed: set[Axis] = {normal}
        elif entity.shape == "hidden_parallel":
            allowed = set(_ALL_AXES)
            allowed.discard(normal)
        else:
            continue

        constrained = True
        candidates.intersection_update(allowed)
        evidence.extend([entity.id, *entity.source_ids, view.id, *view.source_ids])

    if constrained and len(candidates) == 1:
        return next(iter(candidates)), list(dict.fromkeys(evidence))
    return None, list(dict.fromkeys(evidence))


def _structured_symmetric_count_two_sources(
    capture: ReaderCapture,
    *,
    feature_id: str,
    axis: str,
    entity_to_feature: dict[str, str],
) -> list[str]:
    source_ids: list[str] = []
    for observation in capture.observations:
        if observation.get("kind") != _STRUCTURED_SYMMETRIC_COUNT_TWO_KIND:
            continue
        if observation.get("axis") != axis or observation.get("datum") != "overall_center":
            continue
        entity_id = observation.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        if entity_to_feature.get(entity_id) != feature_id:
            continue
        observation_id = observation.get("id")
        if isinstance(observation_id, str) and observation_id:
            source_ids.append(observation_id)
        raw_sources = observation.get("source_ids")
        if isinstance(raw_sources, list):
            source_ids.extend(item for item in raw_sources if isinstance(item, str) and item)
    return list(dict.fromkeys(source_ids))


def _profile_span_constraint_identity(
    *,
    axis: Axis,
    boundary_targets: list[str],
) -> tuple[str, str] | None:
    if len(boundary_targets) != 2 or len(set(boundary_targets)) != 2:
        return None

    ordered_boundaries = sorted(boundary_targets)
    identity_payload = json.dumps(
        {
            "axis": axis,
            "boundaries": ordered_boundaries,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(identity_payload).hexdigest()[:16].upper()
    center_target = f"constraints.span_centers.C_{digest}.{axis.lower()}"
    return digest, center_target


def _profile_span_midpoint_relation(
    *,
    dimension: CaptureDimension,
    boundary_targets: list[str],
    endpoint_source_ids: list[str],
) -> RelationEvidence | None:
    """Create a stable midpoint constraint for one resolved profile span."""

    identity = _profile_span_constraint_identity(
        axis=dimension.axis,
        boundary_targets=boundary_targets,
    )
    if identity is None:
        return None
    digest, center_target = identity
    return RelationEvidence(
        id=f"R_PROFILE_SPAN_MIDPOINT_{digest}",
        kind="midpoint",
        axis=dimension.axis,
        targets=[
            boundary_targets[0],
            center_target,
            boundary_targets[1],
        ],
        source_ids=list(
            dict.fromkeys(
                [
                    *dimension.source_ids,
                    *endpoint_source_ids,
                ]
            )
        ),
        required_for_modeling=False,
        metadata={
            "basis": "resolved_profile_boundary_span_midpoint",
            "constraint_target": center_target,
            "engineering_coordinate_inferred_from_pixels": False,
        },
    )


def _profile_span_centered_relation(
    *,
    dimension: CaptureDimension,
    boundary_targets: list[str],
    endpoint_source_ids: list[str],
) -> RelationEvidence | None:
    """Bind a resolved profile span width to its non-modeling center target."""

    identity = _profile_span_constraint_identity(
        axis=dimension.axis,
        boundary_targets=boundary_targets,
    )
    if identity is None:
        return None
    digest, center_target = identity
    return RelationEvidence(
        id=f"R_PROFILE_SPAN_CENTERED_{digest}",
        kind="centered_span",
        axis=dimension.axis,
        value=dimension.value,
        direction=dimension.direction,
        targets=[
            boundary_targets[0],
            center_target,
            boundary_targets[1],
        ],
        source_ids=list(
            dict.fromkeys(
                [
                    *dimension.source_ids,
                    *endpoint_source_ids,
                ]
            )
        ),
        required_for_modeling=False,
        metadata={
            "basis": "resolved_profile_boundary_span_width_and_midpoint",
            "constraint_target": center_target,
            "engineering_coordinate_inferred_from_pixels": False,
        },
    )


def _profile_span_boundary_targets(
    dimension: CaptureDimension,
    entity_to_feature: dict[str, str],
) -> list[str] | None:
    if any(endpoint.role == "unresolved" for endpoint in dimension.endpoints):
        return None
    if not all(
        endpoint.role == "profile_boundary" and endpoint.entity_id
        for endpoint in dimension.endpoints
    ):
        return None

    axis_leaf = dimension.axis.lower()
    targets: list[str] = []
    for endpoint in dimension.endpoints:
        assert endpoint.entity_id is not None
        feature_id = entity_to_feature.get(endpoint.entity_id)
        if feature_id is None:
            return None
        targets.append(f"feature:{feature_id}.boundary.{axis_leaf}")
    if len(set(targets)) != 2:
        return None
    return targets


def _validated_profile_span_centers(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Return only structurally traceable profile-span center identities."""

    dimension_by_id = {item.id: item for item in capture.dimensions}
    records_by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for observation in capture.observations:
        if observation.get("kind") != _PROFILE_SPAN_CENTER_KIND:
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_identity_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            dimension_id = record.get("dimension_id")
            if not isinstance(dimension_id, str) or not dimension_id:
                continue
            dimension = dimension_by_id.get(dimension_id)
            if dimension is None or record.get("axis") != dimension.axis:
                continue
            if record.get("basis") != "resolved_profile_boundary_span_midpoint":
                continue
            raw_entities = record.get("profile_entity_ids")
            endpoint_entities = [
                endpoint.entity_id
                for endpoint in dimension.endpoints
                if endpoint.role == "profile_boundary" and endpoint.entity_id
            ]
            if (
                not isinstance(raw_entities, list)
                or raw_entities != endpoint_entities
                or len(endpoint_entities) != 2
            ):
                continue
            raw_pair = record.get("selected_witness_positions_px")
            raw_midpoint = record.get("span_midpoint_px")
            if not (
                isinstance(raw_pair, list)
                and len(raw_pair) == 2
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    for value in raw_pair
                )
                and isinstance(raw_midpoint, (int, float))
                and not isinstance(raw_midpoint, bool)
            ):
                continue

            boundary_targets = _profile_span_boundary_targets(
                dimension,
                entity_to_feature,
            )
            if boundary_targets is None:
                continue
            identity = _profile_span_constraint_identity(
                axis=dimension.axis,
                boundary_targets=boundary_targets,
            )
            if identity is None:
                continue
            _digest, center_target = identity
            raw_sources = record.get("source_ids")
            source_ids = [
                item
                for item in raw_sources
                if isinstance(item, str) and item
            ] if isinstance(raw_sources, list) else []
            records_by_dimension[dimension_id].append(
                {
                    "target": center_target,
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *dimension.source_ids,
                                *source_ids,
                            ]
                        )
                    ),
                }
            )

    return {
        dimension_id: records[0]
        for dimension_id, records in records_by_dimension.items()
        if len(records) == 1
    }


def _span_center_identity_matches_by_endpoint(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    span_centers: dict[str, dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """Collect evidence-backed span-center matches for intermediate endpoints."""

    unresolved_indices = {
        index
        for index, endpoint in enumerate(dimension.endpoints)
        if (
            endpoint.role == "unresolved"
            and endpoint.unresolved_kind == "intermediate_surface"
        )
    }
    matches_by_index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not unresolved_indices:
        return matches_by_index

    for observation in capture.observations:
        if observation.get("kind") != _DIMENSION_SPAN_CENTER_IDENTITY_KIND:
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_identity_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            if record.get("dimension_id") != dimension.id:
                continue
            if record.get("axis") != dimension.axis:
                continue
            if record.get("basis") != (
                "unique_witness_to_resolved_profile_span_midpoint"
            ):
                continue
            endpoint_index = record.get("endpoint_index")
            if (
                not isinstance(endpoint_index, int)
                or isinstance(endpoint_index, bool)
                or endpoint_index not in unresolved_indices
            ):
                continue
            span_dimension_id = record.get("span_dimension_id")
            if (
                not isinstance(span_dimension_id, str)
                or not span_dimension_id
                or span_dimension_id == dimension.id
            ):
                continue
            span_center = span_centers.get(span_dimension_id)
            if span_center is None:
                continue
            raw_sources = record.get("source_ids")
            source_ids = (
                [
                    item
                    for item in raw_sources
                    if isinstance(item, str) and item
                ]
                if isinstance(raw_sources, list)
                else []
            )
            matches_by_index[endpoint_index].append(
                {
                    "target": span_center["target"],
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *span_center["source_ids"],
                                *source_ids,
                            ]
                        )
                    ),
                }
            )
    return matches_by_index


def _validated_symmetric_dimension_pairs(
    capture: ReaderCapture,
) -> dict[str, dict[str, Any]]:
    """Return unique centered-dimension topology records tied to capture dimensions."""

    dimension_by_id = {item.id: item for item in capture.dimensions}
    by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for observation in capture.observations:
        if observation.get("kind") != _SYMMETRIC_DIMENSION_PAIR_KIND:
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_identity_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            dimension_id = record.get("dimension_id")
            if not isinstance(dimension_id, str) or not dimension_id:
                continue
            dimension = dimension_by_id.get(dimension_id)
            if dimension is None:
                continue
            if record.get("axis") != dimension.axis:
                continue
            if record.get("datum") != "overall_center":
                continue
            if record.get("basis") != (
                "rotational_symmetry_plus_structurally_shared_raster_view"
                "_plus_overall_witness_midpoint"
            ):
                continue
            raw_dimension_value = record.get("dimension_value")
            raw_overall_value = record.get("overall_dimension_value")
            if (
                isinstance(raw_dimension_value, bool)
                or not isinstance(raw_dimension_value, (int, float))
                or isinstance(raw_overall_value, bool)
                or not isinstance(raw_overall_value, (int, float))
            ):
                continue
            overall_value = {
                "X": capture.overall_dimensions.length_x,
                "Y": capture.overall_dimensions.width_y,
                "Z": capture.overall_dimensions.height_z,
            }[dimension.axis]
            if (
                abs(float(raw_dimension_value) - float(dimension.value)) > 1e-9
                or abs(float(raw_overall_value) - float(overall_value)) > 1e-9
                or float(dimension.value) <= 0
                or float(dimension.value) >= float(overall_value)
            ):
                continue

            selected_pair = record.get("selected_witness_positions_px")
            overall_pair = record.get("overall_witness_positions_px")
            if not (
                isinstance(selected_pair, list)
                and len(selected_pair) == 2
                and isinstance(overall_pair, list)
                and len(overall_pair) == 2
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    for value in [*selected_pair, *overall_pair]
                )
            ):
                continue
            selected_low, selected_high = sorted(float(v) for v in selected_pair)
            overall_low, overall_high = sorted(float(v) for v in overall_pair)
            overall_span = overall_high - overall_low
            if (
                selected_high <= selected_low
                or overall_span <= 0
                or selected_low < overall_low
                or selected_high > overall_high
            ):
                continue
            tolerance = max(2.0, overall_span * 0.015)
            residual = abs(
                (selected_low + selected_high) / 2.0
                - (overall_low + overall_high) / 2.0
            )
            if residual > tolerance:
                continue

            candidate_id = str(record.get("candidate_id") or "")
            if not candidate_id:
                continue
            if not {
                f"hybrid:{candidate_id}:whole",
                f"hybrid:{candidate_id}:wide",
            }.intersection(dimension.source_ids):
                continue

            raw_sources = record.get("source_ids")
            source_ids = (
                [
                    item
                    for item in raw_sources
                    if isinstance(item, str) and item
                ]
                if isinstance(raw_sources, list)
                else []
            )
            by_dimension[dimension_id].append(
                {
                    "overall_value": float(overall_value),
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *dimension.source_ids,
                                *source_ids,
                            ]
                        )
                    ),
                }
            )

    return {
        dimension_id: records[0]
        for dimension_id, records in by_dimension.items()
        if len(records) == 1
    }


def _symmetric_center_distance_bridge(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    span_centers: dict[str, dict[str, Any]],
    symmetric_pairs: dict[str, dict[str, Any]],
) -> list[RelationEvidence] | None:
    """Anchor one identified center and its mirror from engineering dimensions."""

    pair = symmetric_pairs.get(dimension.id)
    if pair is None or dimension.direction not in {-1, 1}:
        return None
    if len(dimension.endpoints) != 2:
        return None
    if any(
        endpoint.role != "unresolved"
        or endpoint.unresolved_kind != "intermediate_surface"
        for endpoint in dimension.endpoints
    ):
        return None

    matches = _span_center_identity_matches_by_endpoint(
        capture,
        dimension=dimension,
        span_centers=span_centers,
    )
    if any(len(items) > 1 for items in matches.values()):
        return None
    unique_matches = {
        index: items[0]
        for index, items in matches.items()
        if len(items) == 1
    }
    if len(unique_matches) != 1:
        return None

    matched_index, match = next(iter(unique_matches.items()))
    overall_value = float(pair["overall_value"])
    distance = float(dimension.value)
    offset = (overall_value - distance) / 2.0
    if offset < 0:
        return None

    if dimension.direction == 1:
        matched_side: Literal["min", "max"] = (
            "min" if matched_index == 0 else "max"
        )
    else:
        matched_side = "max" if matched_index == 0 else "min"

    known_target = str(match["target"])
    identity_payload = json.dumps(
        {
            "axis": dimension.axis,
            "known_target": known_target,
            "distance": distance,
            "overall": overall_value,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(identity_payload).hexdigest()[:16].upper()
    mirror_target = (
        f"constraints.symmetric_centers.C_{digest}.{dimension.axis.lower()}"
    )

    if matched_side == "min":
        min_target, max_target = known_target, mirror_target
    else:
        min_target, max_target = mirror_target, known_target

    source_ids = list(
        dict.fromkeys(
            [
                *dimension.source_ids,
                *[
                    source_id
                    for endpoint in dimension.endpoints
                    for source_id in endpoint.source_ids
                ],
                *match["source_ids"],
                *pair["source_ids"],
            ]
        )
    )
    metadata = {
        "basis": "overall_center_symmetric_center_distance",
        "matched_span_center_endpoint_index": matched_index,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }

    return [
        RelationEvidence(
            id=f"R_SYMMETRIC_CENTER_PAIR_{digest}_MIN",
            kind="edge_offset",
            axis=dimension.axis,
            value=offset,
            from_side="min",
            targets=[min_target],
            source_ids=source_ids,
            required_for_modeling=False,
            metadata=metadata,
        ),
        RelationEvidence(
            id=f"R_SYMMETRIC_CENTER_PAIR_{digest}_MAX",
            kind="edge_offset",
            axis=dimension.axis,
            value=offset,
            from_side="max",
            targets=[max_target],
            source_ids=source_ids,
            required_for_modeling=False,
            metadata=metadata,
        ),
        RelationEvidence(
            id=dimension.id,
            kind="center_distance",
            axis=dimension.axis,
            value=distance,
            direction=1,
            targets=[min_target, max_target],
            source_ids=source_ids,
            required_for_modeling=dimension.required_for_modeling,
            metadata=metadata,
        ),
    ]


def _projected_profile_endpoint_matches(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    entity_to_feature: dict[str, str],
) -> dict[int, list[dict[str, Any]]]:
    """Collect unique physical profile-level projections per unresolved endpoint."""

    unresolved_indices = {
        index
        for index, endpoint in enumerate(dimension.endpoints)
        if (
            endpoint.role == "unresolved"
            and endpoint.unresolved_kind == "intermediate_surface"
        )
    }
    matches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not unresolved_indices:
        return matches

    entity_by_id = {item.id: item for item in capture.entities}
    for observation in capture.observations:
        if observation.get("kind") != _PROJECTED_PROFILE_LEVEL_KIND:
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_identity_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue

        for record in items:
            if not isinstance(record, dict):
                continue
            if record.get("dimension_id") != dimension.id:
                continue
            if record.get("axis") != dimension.axis:
                continue
            if record.get("basis") != (
                "extension_line_projection_to_structural_profile_level"
            ):
                continue
            endpoint_index = record.get("endpoint_index")
            if (
                not isinstance(endpoint_index, int)
                or isinstance(endpoint_index, bool)
                or endpoint_index not in unresolved_indices
            ):
                continue

            candidate_id = str(record.get("candidate_id") or "")
            if not candidate_id:
                continue
            if not {
                f"hybrid:{candidate_id}:whole",
                f"hybrid:{candidate_id}:wide",
            }.intersection(dimension.source_ids):
                continue

            raw_entity_ids = record.get("profile_entity_ids")
            raw_refs = record.get("profile_refs")
            if not (
                isinstance(raw_entity_ids, list)
                and raw_entity_ids
                and len(set(raw_entity_ids)) == len(raw_entity_ids)
                and all(
                    isinstance(entity_id, str) and entity_id
                    for entity_id in raw_entity_ids
                )
                and isinstance(raw_refs, list)
                and raw_refs
                and all(isinstance(ref, str) and ref for ref in raw_refs)
            ):
                continue

            entities = [
                entity_by_id.get(entity_id)
                for entity_id in raw_entity_ids
            ]
            if any(
                entity is None or entity.shape != "profile"
                for entity in entities
            ):
                continue
            if any(
                not any(
                    f"hybrid:profile-edge:{ref}" in entity.source_ids
                    for entity in entities
                    if entity is not None
                )
                for ref in raw_refs
            ):
                continue

            raw_sources = record.get("source_ids")
            record_sources = (
                [
                    source_id
                    for source_id in raw_sources
                    if isinstance(source_id, str) and source_id
                ]
                if isinstance(raw_sources, list)
                else []
            )
            entity_sources = [
                source_id
                for entity in entities
                if entity is not None
                for source_id in entity.source_ids
            ]
            source_ids = list(
                dict.fromkeys(
                    [
                        *dimension.source_ids,
                        *record_sources,
                        *entity_sources,
                    ]
                )
            )

            overall_role = record.get("overall_role")
            if overall_role in {"overall_min", "overall_max"}:
                matches[endpoint_index].append(
                    {
                        "role": overall_role,
                        "target": None,
                        "source_ids": source_ids,
                    }
                )
                continue
            if overall_role is not None:
                continue
            if any(
                entity_id not in entity_to_feature
                for entity_id in raw_entity_ids
            ):
                continue

            targets = {
                (
                    f"feature:{entity_to_feature[entity_id]}"
                    f".boundary.{dimension.axis.lower()}"
                )
                for entity_id in raw_entity_ids
            }
            if not targets:
                continue
            for target in sorted(targets):
                matches[endpoint_index].append(
                    {
                        "role": "profile",
                        "target": target,
                        "source_ids": source_ids,
                    }
                )

    return matches


def _projected_profile_dimension_bridge(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    entity_to_feature: dict[str, str],
    symmetric_pairs: dict[str, dict[str, Any]],
) -> list[RelationEvidence] | None:
    """Promote fully proven projected profile levels to engineering relations."""

    unresolved_indices = [
        index
        for index, endpoint in enumerate(dimension.endpoints)
        if endpoint.role == "unresolved"
    ]
    if not unresolved_indices:
        return None
    if any(
        dimension.endpoints[index].unresolved_kind != "intermediate_surface"
        for index in unresolved_indices
    ):
        return None

    matches = _projected_profile_endpoint_matches(
        capture,
        dimension=dimension,
        entity_to_feature=entity_to_feature,
    )
    if any(len(matches.get(index, [])) > 1 for index in unresolved_indices):
        return None

    unique_matches = {
        index: matches[index][0]
        for index in unresolved_indices
        if len(matches.get(index, [])) == 1
    }
    if len(unique_matches) != len(unresolved_indices):
        pair = symmetric_pairs.get(dimension.id)
        if (
            len(unresolved_indices) != 2
            or len(unique_matches) != 1
            or pair is None
            or dimension.direction not in {-1, 1}
        ):
            return None

        matched_index, match = next(iter(unique_matches.items()))
        if match.get("role") != "profile":
            return None
        known_target = match.get("target")
        if not isinstance(known_target, str) or not known_target:
            return None

        overall_value = float(pair["overall_value"])
        distance = float(dimension.value)
        offset = (overall_value - distance) / 2.0
        if offset < 0:
            return None

        if dimension.direction == 1:
            matched_side: Literal["min", "max"] = (
                "min" if matched_index == 0 else "max"
            )
        else:
            matched_side = "max" if matched_index == 0 else "min"

        identity_payload = json.dumps(
            {
                "axis": dimension.axis,
                "known_target": known_target,
                "distance": distance,
                "overall": overall_value,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(identity_payload).hexdigest()[:16].upper()
        mirror_target = (
            "constraints.symmetric_profile_levels."
            f"C_{digest}.{dimension.axis.lower()}"
        )

        if matched_side == "min":
            min_target, max_target = known_target, mirror_target
        else:
            min_target, max_target = mirror_target, known_target

        source_ids = list(
            dict.fromkeys(
                [
                    *dimension.source_ids,
                    *[
                        source_id
                        for endpoint in dimension.endpoints
                        for source_id in endpoint.source_ids
                    ],
                    *match["source_ids"],
                    *pair["source_ids"],
                ]
            )
        )
        metadata = {
            "basis": "overall_center_symmetric_projected_profile_level",
            "matched_projected_profile_endpoint_index": matched_index,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        }

        return [
            RelationEvidence(
                id=f"R_PROJECTED_PROFILE_MIRROR_{digest}_MIN",
                kind="edge_offset",
                axis=dimension.axis,
                value=offset,
                from_side="min",
                targets=[min_target],
                source_ids=source_ids,
                required_for_modeling=False,
                metadata=metadata,
            ),
            RelationEvidence(
                id=f"R_PROJECTED_PROFILE_MIRROR_{digest}_MAX",
                kind="edge_offset",
                axis=dimension.axis,
                value=offset,
                from_side="max",
                targets=[max_target],
                source_ids=source_ids,
                required_for_modeling=False,
                metadata=metadata,
            ),
            RelationEvidence(
                id=dimension.id,
                kind="coordinate_distance",
                axis=dimension.axis,
                value=distance,
                direction=1,
                targets=[min_target, max_target],
                source_ids=source_ids,
                required_for_modeling=dimension.required_for_modeling,
                metadata=metadata,
            ),
        ]

    axis_leaf = dimension.axis.lower()
    specs: list[tuple[str, str | None]] = []
    source_ids = list(dimension.source_ids)
    projected_indices: list[int] = []

    for index, endpoint in enumerate(dimension.endpoints):
        source_ids.extend(endpoint.source_ids)
        if endpoint.role == "unresolved":
            match = matches[index][0]
            specs.append((str(match["role"]), match.get("target")))
            source_ids.extend(match["source_ids"])
            projected_indices.append(index)
            continue

        known = _known_dimension_endpoint_target(
            endpoint,
            axis_leaf=axis_leaf,
            entity_to_feature=entity_to_feature,
        )
        if known is None:
            return None
        specs.append(known)

    source_ids = list(dict.fromkeys(source_ids))
    metadata = {
        "basis": "dimension_endpoint_resolved_by_projected_profile_level",
        "projected_profile_endpoint_indices": projected_indices,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }

    overall = [
        (index, role)
        for index, (role, _target) in enumerate(specs)
        if role in {"overall_min", "overall_max"}
    ]
    if overall:
        if len(overall) != 1:
            return None
        other_index = 1 - overall[0][0]
        other_target = specs[other_index][1]
        if other_target is None:
            return None
        from_side: Literal["min", "max"] = (
            "min" if overall[0][1] == "overall_min" else "max"
        )
        return [
            RelationEvidence(
                id=dimension.id,
                kind="edge_offset",
                axis=dimension.axis,
                value=dimension.value,
                from_side=from_side,
                targets=[other_target],
                source_ids=source_ids,
                required_for_modeling=dimension.required_for_modeling,
                metadata=metadata,
            )
        ]

    targets = [target for _role, target in specs if target is not None]
    if len(targets) != 2 or len(set(targets)) != 2:
        return None

    pair = symmetric_pairs.get(dimension.id)
    if (
        pair is not None
        and [role for role, _target in specs] == ["profile", "profile"]
        and dimension.direction in {-1, 1}
    ):
        overall_value = float(pair["overall_value"])
        offset = (overall_value - float(dimension.value)) / 2.0
        if offset < 0:
            return None
        if dimension.direction == 1:
            min_target, max_target = targets
        else:
            max_target, min_target = targets

        symmetric_sources = list(
            dict.fromkeys([*source_ids, *pair["source_ids"]])
        )
        symmetric_metadata = {
            **metadata,
            "basis": "overall_center_symmetric_projected_profile_levels",
        }
        digest_payload = json.dumps(
            {
                "axis": dimension.axis,
                "min_target": min_target,
                "max_target": max_target,
                "distance": dimension.value,
                "overall": overall_value,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(digest_payload).hexdigest()[:16].upper()
        return [
            RelationEvidence(
                id=f"R_PROJECTED_PROFILE_SYMMETRY_{digest}_MIN",
                kind="edge_offset",
                axis=dimension.axis,
                value=offset,
                from_side="min",
                targets=[min_target],
                source_ids=symmetric_sources,
                required_for_modeling=False,
                metadata=symmetric_metadata,
            ),
            RelationEvidence(
                id=f"R_PROJECTED_PROFILE_SYMMETRY_{digest}_MAX",
                kind="edge_offset",
                axis=dimension.axis,
                value=offset,
                from_side="max",
                targets=[max_target],
                source_ids=symmetric_sources,
                required_for_modeling=False,
                metadata=symmetric_metadata,
            ),
            RelationEvidence(
                id=dimension.id,
                kind="coordinate_distance",
                axis=dimension.axis,
                value=dimension.value,
                direction=1,
                targets=[min_target, max_target],
                source_ids=symmetric_sources,
                required_for_modeling=dimension.required_for_modeling,
                metadata=symmetric_metadata,
            ),
        ]

    return [
        RelationEvidence(
            id=dimension.id,
            kind="coordinate_distance",
            axis=dimension.axis,
            value=dimension.value,
            direction=dimension.direction,
            targets=targets,
            source_ids=source_ids,
            required_for_modeling=dimension.required_for_modeling,
            metadata=metadata,
        )
    ]


def _dimension_span_center_endpoint_matches(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    span_centers: dict[str, dict[str, Any]],
) -> dict[int, dict[str, Any]] | None:
    """Resolve every intermediate-surface endpoint through unique span identity."""

    unresolved_indices = [
        index
        for index, endpoint in enumerate(dimension.endpoints)
        if endpoint.role == "unresolved"
    ]
    if not unresolved_indices:
        return None
    if any(
        dimension.endpoints[index].unresolved_kind != "intermediate_surface"
        for index in unresolved_indices
    ):
        return None

    matches_by_index = _span_center_identity_matches_by_endpoint(
        capture,
        dimension=dimension,
        span_centers=span_centers,
    )

    if any(len(matches_by_index.get(index, [])) != 1 for index in unresolved_indices):
        return None
    result = {
        index: matches_by_index[index][0]
        for index in unresolved_indices
    }
    targets = [item["target"] for item in result.values()]
    if len(set(targets)) != len(targets):
        return None
    return result


def _known_dimension_endpoint_target(
    endpoint: Any,
    *,
    axis_leaf: str,
    entity_to_feature: dict[str, str],
) -> tuple[str, str | None] | None:
    if endpoint.role in {"overall_min", "overall_max"}:
        return endpoint.role, None
    if endpoint.role not in {"entity_center", "profile_boundary"}:
        return None
    if not endpoint.entity_id:
        return None
    feature_id = entity_to_feature.get(endpoint.entity_id)
    if feature_id is None:
        return None
    if endpoint.role == "entity_center":
        return "center", f"feature:{feature_id}.centerline.{axis_leaf}"
    return "profile", f"feature:{feature_id}.boundary.{axis_leaf}"


def _dimension_relation_from_span_center_identity(
    *,
    dimension: CaptureDimension,
    endpoint_matches: dict[int, dict[str, Any]],
    entity_to_feature: dict[str, str],
) -> RelationEvidence | None:
    """Promote one fully covered unresolved dimension to a formal relation."""

    axis_leaf = dimension.axis.lower()
    specs: list[tuple[str, str | None]] = []
    source_ids = list(dimension.source_ids)

    for index, endpoint in enumerate(dimension.endpoints):
        source_ids.extend(endpoint.source_ids)
        if endpoint.role == "unresolved":
            match = endpoint_matches.get(index)
            if match is None:
                return None
            specs.append(("center", str(match["target"])))
            source_ids.extend(match["source_ids"])
            continue
        known = _known_dimension_endpoint_target(
            endpoint,
            axis_leaf=axis_leaf,
            entity_to_feature=entity_to_feature,
        )
        if known is None:
            return None
        specs.append(known)

    overall = [
        (index, role)
        for index, (role, _target) in enumerate(specs)
        if role in {"overall_min", "overall_max"}
    ]
    if overall:
        if len(overall) != 1:
            return None
        measured_index = 1 - overall[0][0]
        measured_target = specs[measured_index][1]
        if measured_target is None:
            return None
        from_side: Literal["min", "max"] = (
            "min" if overall[0][1] == "overall_min" else "max"
        )
        return RelationEvidence(
            id=dimension.id,
            kind="edge_offset",
            axis=dimension.axis,
            value=dimension.value,
            from_side=from_side,
            targets=[measured_target],
            source_ids=list(dict.fromkeys(source_ids)),
            required_for_modeling=dimension.required_for_modeling,
            metadata={
                "basis": "dimension_endpoint_resolved_by_profile_span_center_identity",
                "span_center_endpoint_indices": sorted(endpoint_matches),
                "engineering_coordinate_inferred_from_pixels": False,
            },
        )

    targets = [target for _role, target in specs if target is not None]
    if len(targets) != 2 or len(set(targets)) != 2:
        return None
    roles = [role for role, _target in specs]
    kind: Literal["center_distance", "coordinate_distance"] = (
        "center_distance"
        if roles == ["center", "center"]
        else "coordinate_distance"
    )
    return RelationEvidence(
        id=dimension.id,
        kind=kind,
        axis=dimension.axis,
        value=dimension.value,
        direction=dimension.direction,
        targets=targets,
        source_ids=list(dict.fromkeys(source_ids)),
        required_for_modeling=dimension.required_for_modeling,
        metadata={
            "basis": "dimension_endpoint_resolved_by_profile_span_center_identity",
            "span_center_endpoint_indices": sorted(endpoint_matches),
            "engineering_coordinate_inferred_from_pixels": False,
        },
    )


def _structured_symmetric_profile_span_sources(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    endpoint_entity_ids: list[str],
) -> list[str]:
    if len(endpoint_entity_ids) != 2 or len(set(endpoint_entity_ids)) != 2:
        return []

    source_ids: list[str] = []
    for observation in capture.observations:
        if observation.get("kind") != _STRUCTURED_SYMMETRIC_PROFILE_SPAN_KIND:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            if record.get("axis") != dimension.axis or record.get("datum") != "overall_center":
                continue
            raw_entities = record.get("profile_entity_ids")
            if not (
                isinstance(raw_entities, list)
                and len(raw_entities) == 2
                and all(isinstance(entity_id, str) for entity_id in raw_entities)
                and raw_entities == endpoint_entity_ids
            ):
                continue
            raw_value = record.get("dimension_value")
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
                or abs(float(raw_value) - float(dimension.value)) > 1e-9
            ):
                continue
            candidate_id = str(record.get("candidate_id") or "")
            if not candidate_id:
                continue
            candidate_sources = {
                f"hybrid:{candidate_id}:whole",
                f"hybrid:{candidate_id}:wide",
            }
            if not candidate_sources.intersection(dimension.source_ids):
                continue
            raw_sources = record.get("source_ids")
            if isinstance(raw_sources, list):
                source_ids.extend(
                    item for item in raw_sources if isinstance(item, str) and item
                )
    return list(dict.fromkeys(source_ids))


def _direct_target_value(
    direct_values: list[DirectValueEvidence],
    target: str,
) -> Any:
    matches = [item.value for item in direct_values if item.target == target]
    return matches[0] if len(matches) == 1 else None


def _materialized_entity_ids(capture: ReaderCapture) -> set[str]:
    referenced: set[str] = set()

    for association in capture.associations:
        referenced.update(association.entity_ids)

    for item in capture.values:
        referenced.add(item.entity_id)

    for item in capture.dimensions:
        for endpoint in item.endpoints:
            if endpoint.entity_id:
                referenced.add(endpoint.entity_id)
            referenced.update(endpoint.candidate_entity_ids)

    for item in capture.datum_alignments:
        referenced.add(item.entity_id)

    for item in capture.centerline_alignments:
        referenced.update(item.entity_ids)

    for item in capture.required_targets:
        referenced.add(item.entity_id)

    for item in capture.unresolved_evidence:
        referenced.update(item.entity_ids)

    profile_entity_ids = {
        item.id
        for item in capture.entities
        if item.shape == "profile"
    }

    for observation in capture.observations:
        kind = observation.get("kind")
        if kind == _VIEW_AXIS_BOUNDARY_KIND:
            valid_items = _valid_view_axis_boundary_items(capture)
            for boundary_item in valid_items:
                if boundary_item not in observation.get("items", []):
                    continue
                for anchor in boundary_item.get("anchors", []):
                    if not isinstance(anchor, dict):
                        continue
                    ref = str(anchor.get("ref") or "")
                    entity_ids = _profile_entity_ids_for_ref(capture, ref)
                    if len(entity_ids) == 1:
                        referenced.add(entity_ids[0])
            continue

        if kind == _PROJECTED_PROFILE_LEVEL_KIND:
            items = observation.get("items")
            if not isinstance(items, list):
                continue
            for record in items:
                if not isinstance(record, dict):
                    continue
                if record.get("overall_role") in {"overall_min", "overall_max"}:
                    continue
                raw_entity_ids = record.get("profile_entity_ids")
                if not isinstance(raw_entity_ids, list):
                    continue
                referenced.update(
                    entity_id
                    for entity_id in raw_entity_ids
                    if (
                        isinstance(entity_id, str)
                        and entity_id in profile_entity_ids
                    )
                )
            continue

        if kind != _ROTATIONAL_PROFILE_TOPOLOGY_KIND:
            continue
        if (
            observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_topology_only")
            is not True
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            axis = str(item.get("rotation_axis") or "").upper()
            plane = str(item.get("plane") or "").upper()
            edges = item.get("edges")
            if (
                axis not in {"X", "Y", "Z"}
                or plane not in {"XY", "XZ", "YZ"}
                or axis not in plane
                or not isinstance(edges, list)
            ):
                continue
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                entity_id = edge.get("profile_entity_id")
                constant_axis = str(edge.get("constant_axis") or "").upper()
                if (
                    isinstance(entity_id, str)
                    and entity_id in profile_entity_ids
                    and constant_axis in set(plane)
                ):
                    referenced.add(entity_id)

    return referenced


def _resolver_numeric_value(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _canonical_projection_shape(
    capture: ReaderCapture,
    entity_id: str,
    component_entity_ids: set[str],
) -> str:
    entity_by_id = {item.id: item for item in capture.entities}
    entity = entity_by_id[entity_id]

    if entity.shape != "profile":
        return entity.shape

    canonical_fields = {
        _canonical_field(capture, item.entity_id, item.field)
        for item in capture.values
        if item.entity_id == entity_id
    }
    hole_fields = {
        "diameter",
        "fit",
        "thread_spec",
        "thread_depth",
        "through",
        "counterbore_diameter",
        "counterbore_depth",
    }
    if canonical_fields & hole_fields:
        return "hidden_parallel"

    if any(
        entity_by_id[other_id].shape in {"circle", "concentric_circles"}
        for other_id in component_entity_ids
        if other_id != entity_id
    ):
        return "hidden_parallel"

    return entity.shape


def _component_signature(
    capture: ReaderCapture,
    entity_ids: list[str],
) -> dict[str, Any]:
    entity_set = set(entity_ids)
    view_kind = {item.id: item.kind for item in capture.views}

    projections = sorted(
        [
            {
                "view_kind": view_kind[item.view_id],
                "shape": _canonical_projection_shape(
                    capture,
                    item.id,
                    entity_set,
                ),
                "required_for_modeling": item.required_for_modeling,
            }
            for item in capture.entities
            if item.id in entity_set
        ],
        key=lambda item: json.dumps(item, sort_keys=True),
    )

    # Physical identity must not depend on semantic payload that stability
    # comparison is itself trying to measure. Direct values and datum
    # alignments can legitimately be missing or disputed between independent
    # Reader runs; including them in the feature-id hash turns value/datum drift
    # into artificial identity churn. Projection topology is the structural
    # identity signature. Structurally indistinguishable disconnected
    # components are handled separately by the identity-collision fail-closed
    # path below.
    return {
        "projections": projections,
    }


def _feature_id(signature: dict[str, Any]) -> str:
    payload = json.dumps(
        _canon(signature),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "F_" + hashlib.sha256(payload).hexdigest()[:16].upper()


def _association_components(
    capture: ReaderCapture,
) -> tuple[list[list[str]], list[dict[str, Any]], list[str]]:
    materialized = _materialized_entity_ids(capture)
    ignored_orphan_profiles = sorted(
        item.id
        for item in capture.entities
        if item.shape == "profile" and item.id not in materialized
    )
    entities = {
        item.id: item
        for item in capture.entities
        if item.id not in ignored_orphan_profiles
    }
    unresolved: list[dict[str, Any]] = []
    admissible: list[AssociationClaim] = []

    for association in capture.associations:
        if any(entity_id not in entities for entity_id in association.entity_ids):
            raise IdentityLinkError(
                f"association {association.id!r} references a non-materialized entity"
            )

        by_view: dict[str, list[str]] = defaultdict(list)
        for entity_id in association.entity_ids:
            by_view[entities[entity_id].view_id].append(entity_id)

        duplicate_views = {
            view_id: ids
            for view_id, ids in by_view.items()
            if len(ids) > 1
        }
        if duplicate_views:
            unresolved.append(
                {
                    "id": f"U_ASSOC_{association.id}",
                    "kind": "association_structure",
                    "reason": (
                        "association contains multiple view-local entities from "
                        f"the same view: {duplicate_views}"
                    ),
                    "entity_ids": list(association.entity_ids),
                    "required_for_modeling": association.required_for_modeling,
                    "evidence": [
                        association.id,
                        *association.source_ids,
                    ],
                }
            )
            continue

        if not _association_basis_sufficient(association.basis):
            unresolved.append(
                {
                    "id": f"U_ASSOC_EVIDENCE_{association.id}",
                    "kind": "association_evidence",
                    "reason": (
                        "association visual basis is insufficient for "
                        "deterministic physical merge"
                    ),
                    "basis": sorted(association.basis),
                    "entity_ids": list(association.entity_ids),
                    "required_for_modeling": association.required_for_modeling,
                    "evidence": [
                        association.id,
                        *association.source_ids,
                    ],
                }
            )
            continue

        admissible.append(association)

    # Validate connected association components before committing any physical
    # merge. Pairwise-valid claims can still create a transitive component that
    # contains multiple entities from the same view (A_front1↔B_side and
    # A_front2↔B_side). Choosing one edge would be order-dependent, so quarantine
    # the whole ambiguous component instead.
    candidate_uf = _UnionFind(list(entities))
    for association in admissible:
        first = association.entity_ids[0]
        for entity_id in association.entity_ids[1:]:
            candidate_uf.union(first, entity_id)

    candidate_components: dict[str, list[str]] = defaultdict(list)
    for entity_id in entities:
        candidate_components[candidate_uf.find(entity_id)].append(entity_id)

    conflicting_roots: set[str] = set()
    for root, component_entity_ids in candidate_components.items():
        by_view: dict[str, list[str]] = defaultdict(list)
        for entity_id in component_entity_ids:
            by_view[entities[entity_id].view_id].append(entity_id)
        duplicate_views = {
            view_id: sorted(ids)
            for view_id, ids in by_view.items()
            if len(ids) > 1
        }
        if not duplicate_views:
            continue

        conflicting_roots.add(root)
        component_associations = [
            association
            for association in admissible
            if candidate_uf.find(association.entity_ids[0]) == root
        ]
        evidence = sorted(
            {
                token
                for association in component_associations
                for token in [association.id, *association.source_ids]
            }
        )
        component_ids = sorted(component_entity_ids)
        component_hash = hashlib.sha256(
            "|".join(component_ids).encode("utf-8")
        ).hexdigest()[:12].upper()
        unresolved.append(
            {
                "id": f"U_ASSOC_COMPONENT_{component_hash}",
                "kind": "association_structure",
                "reason": (
                    "transitive association component contains multiple "
                    f"view-local entities from the same view: {duplicate_views}"
                ),
                "entity_ids": component_ids,
                "required_for_modeling": any(
                    association.required_for_modeling
                    for association in component_associations
                ),
                "evidence": evidence,
            }
        )

    uf = _UnionFind(list(entities))
    for association in admissible:
        root = candidate_uf.find(association.entity_ids[0])
        if root in conflicting_roots:
            continue
        first = association.entity_ids[0]
        for entity_id in association.entity_ids[1:]:
            uf.union(first, entity_id)

    components: dict[str, list[str]] = defaultdict(list)
    for entity_id in entities:
        components[uf.find(entity_id)].append(entity_id)

    return (
        [sorted(items) for items in components.values()],
        unresolved,
        ignored_orphan_profiles,
    )


def _direct_value_equivalence_key(item: DirectValueEvidence) -> str:
    return json.dumps(
        {
            "value": _canon(item.value),
            "semantic": item.semantic,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _normalize_direct_values(
    items: list[DirectValueEvidence],
) -> tuple[list[DirectValueEvidence], list[dict[str, Any]]]:
    """Normalize Reader direct writers without guessing.

    Equivalent cross-view confirmations collapse into one writer. Multiple
    non-equivalent writers for the same physical target are quarantined as a
    blocking unresolved record so frozen downstream never receives duplicate
    writers and no candidate value is chosen.
    """

    by_target: dict[str, list[DirectValueEvidence]] = defaultdict(list)
    for item in items:
        by_target[item.target].append(item)

    normalized: list[DirectValueEvidence] = []
    unresolved: list[dict[str, Any]] = []

    for target in sorted(by_target):
        target_items = sorted(by_target[target], key=lambda item: item.id)
        by_equivalence: dict[str, list[DirectValueEvidence]] = defaultdict(list)
        for item in target_items:
            by_equivalence[_direct_value_equivalence_key(item)].append(item)

        if len(by_equivalence) > 1:
            candidate_records = sorted(
                [
                    {
                        "value": _canon(group[0].value),
                        "semantic": group[0].semantic,
                    }
                    for group in by_equivalence.values()
                ],
                key=lambda item: json.dumps(
                    item,
                    sort_keys=True,
                    ensure_ascii=False,
                ),
            )
            conflict_key = json.dumps(
                {
                    "target": target,
                    "candidates": candidate_records,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            unresolved.append(
                {
                    "id": (
                        "U_DIRECT_CONFLICT_"
                        + hashlib.sha256(
                            conflict_key.encode("utf-8")
                        ).hexdigest()[:16].upper()
                    ),
                    "kind": "direct_value_conflict",
                    "reason": (
                        "multiple non-equivalent direct observations target "
                        "the same physical property"
                    ),
                    "target": target,
                    "candidates": candidate_records,
                    "required_for_modeling": True,
                    "evidence": list(
                        dict.fromkeys(
                            evidence_id
                            for item in target_items
                            for evidence_id in [item.id, *item.source_ids]
                        )
                    ),
                }
            )
            continue

        equivalence_group = next(iter(by_equivalence.values()))
        first = equivalence_group[0].model_copy(deep=True)
        if len(equivalence_group) > 1:
            merge_key = json.dumps(
                {
                    "target": target,
                    "value": _canon(first.value),
                    "semantic": first.semantic,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            first.id = (
                "L_DIRECT_"
                + hashlib.sha256(
                    merge_key.encode("utf-8")
                ).hexdigest()[:16].upper()
            )
            first.source_ids = list(
                dict.fromkeys(
                    source_id
                    for item in equivalence_group
                    for source_id in [item.id, *item.source_ids]
                )
            )
        normalized.append(first)

    return (
        sorted(normalized, key=lambda item: (item.target, item.id)),
        unresolved,
    )


def _open_slot_tangent_relations(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> tuple[list[RelationEvidence], set[tuple[str, str]]]:
    relations: list[RelationEvidence] = []
    resolved_fields: set[tuple[str, str]] = set()

    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != "hybrid_open_slot_ledger"
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            slot_entity_id = str(item.get("slot_entity_id") or "")
            circle_entity_id = str(item.get("circle_entity_id") or "")
            if (
                slot_entity_id not in entity_to_feature
                or circle_entity_id not in entity_to_feature
            ):
                continue

            slot_feature = entity_to_feature[slot_entity_id]
            circle_feature = entity_to_feature[circle_entity_id]
            if slot_feature == circle_feature:
                continue

            basis = str(item.get("basis") or "")
            if (
                basis
                != (
                    "unique_overall_top_gap_plus_two_descending_walls_plus_"
                    "circle_center_alignment_and_upper_circle_termination"
                )
            ):
                continue
            if item.get("engineering_coordinate_inferred_from_pixels") is not False:
                continue
            if item.get("pixel_geometry_used_for_topology_only") is not True:
                continue

            source_item_index = item.get("source_item_index")
            region_id = str(item.get("region_id") or "")
            source_ids = [
                source
                for source in [
                    f"hybrid:open-slot:{region_id}:{source_item_index}",
                    str(item.get("top_boundary_ref") or ""),
                    str(item.get("circle_entity") or ""),
                ]
                if source
            ]

            tangent_relation = RelationEvidence(
                id=f"R_OPEN_SLOT_UPPER_TANGENT_{index + 1:03d}",
                kind="upper_tangent",
                axis="Z",
                targets=[
                    f"feature:{circle_feature}.centerline.z",
                    f"feature:{slot_feature}.bottom_z",
                ],
                diameter_target=f"feature:{circle_feature}.diameter",
                source_ids=source_ids,
                required_for_modeling=True,
                metadata={
                    "basis": basis,
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                },
            )
            center_alignment = RelationEvidence(
                id=f"R_OPEN_SLOT_CENTER_X_{index + 1:03d}",
                kind="alignment",
                axis="X",
                targets=[
                    f"feature:{circle_feature}.centerline.x",
                    f"feature:{slot_feature}.centerline.x",
                ],
                source_ids=source_ids,
                required_for_modeling=True,
                metadata={
                    "basis": (
                        "unique_open_slot_gap_midpoint_aligned_to_circle_center"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                },
            )
            relations.extend([tangent_relation, center_alignment])
            resolved_fields.add((slot_feature, "bottom_z"))

    return relations, resolved_fields


def _linked_reader_unresolved(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
    *,
    relation_resolved_fields: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    resolved_fields = relation_resolved_fields or set()

    for item in capture.unresolved_evidence:
        feature_ids = sorted(
            {
                entity_to_feature[entity_id]
                for entity_id in item.entity_ids
                if entity_id in entity_to_feature
            }
        )
        if (
            item.field is not None
            and len(feature_ids) == 1
            and (feature_ids[0], item.field) in resolved_fields
        ):
            continue

        record: dict[str, Any] = {
            "id": item.id,
            "kind": item.kind,
            "reason": item.reason,
            "required_for_modeling": item.required_for_modeling,
            "source_ids": item.source_ids,
        }

        if feature_ids:
            record["feature_ids"] = feature_ids
        if item.dimension_id is not None:
            record["capture_dimension_id"] = item.dimension_id
        if item.dimension_value is not None:
            record["dimension_value"] = item.dimension_value
        if item.field is not None:
            record["field"] = item.field
        if item.axis is not None:
            record["axis"] = item.axis
        if item.basis:
            record["basis"] = sorted(item.basis)

        result.append(record)

    return result


def link_reader_capture(capture: ReaderCapture) -> IdentityLinkResult:
    """Build stable physical feature identities from view-local Reader capture.

    Raw entity IDs never become physical feature IDs. Association claims only
    connect entities when structurally admissible; no geometry is guessed.
    """

    components, unresolved, ignored_orphan_profiles = _association_components(capture)

    signatures: list[tuple[list[str], dict[str, Any], str]] = []
    by_feature_id: dict[str, list[list[str]]] = defaultdict(list)
    for component in components:
        signature = _component_signature(capture, component)
        fid = _feature_id(signature)
        signatures.append((component, signature, fid))
        by_feature_id[fid].append(component)

    collision_ids = {
        fid
        for fid, grouped in by_feature_id.items()
        if len(grouped) > 1
    }
    if collision_ids:
        entity_required = {
            item.id: item.required_for_modeling
            for item in capture.entities
        }
        for fid in sorted(collision_ids):
            collision_required = any(
                entity_required.get(entity_id, True)
                for component in by_feature_id[fid]
                for entity_id in component
            )
            unresolved.append(
                {
                    "id": f"U_IDENTITY_COLLISION_{fid}",
                    "reason": (
                        "multiple disconnected capture components have the same "
                        "semantic signature; deterministic physical identity is "
                        "not unique"
                    ),
                    # A collision is modeling-blocking only when one of the
                    # colliding projections is itself modeling-critical.  The
                    # linker still assigns distinct deterministic AMB
                    # placeholders either way; required dimensions/unresolved
                    # endpoint records carry their own blocking semantics.
                    "required_for_modeling": collision_required,
                    "components": by_feature_id[fid],
                }
            )

    collision_component_index: dict[tuple[str, ...], int] = {}
    for fid in sorted(collision_ids):
        grouped = sorted(
            (tuple(component) for component in by_feature_id[fid]),
            key=lambda component: component,
        )
        for ordinal, component in enumerate(grouped, start=1):
            collision_component_index[component] = ordinal

    entity_to_feature: dict[str, str] = {}
    for component, _signature, fid in signatures:
        if fid in collision_ids:
            # Keep disconnected ambiguous components technically distinct so
            # downstream relations never collapse two physical candidates into
            # one target. The suffix is only an intra-capture placeholder; it
            # carries no physical left/right/order meaning. Modeling remains
            # blocked by U_IDENTITY_COLLISION_*.
            ordinal = collision_component_index[tuple(component)]
            placeholder = f"{fid}_AMB_{ordinal:02d}"
            for entity_id in component:
                entity_to_feature[entity_id] = placeholder
            continue
        for entity_id in component:
            entity_to_feature[entity_id] = fid

    views = [
        ViewEvidence(
            id=item.id,
            kind=item.kind,
            source_ids=item.source_ids,
        )
        for item in capture.views
    ]

    component_by_entity = {
        entity_id: set(component)
        for component in components
        for entity_id in component
    }

    projections = [
        ProjectionEvidence(
            id=f"P_{item.id}",
            feature_id=entity_to_feature[item.id],
            view_id=item.view_id,
            shape=_canonical_projection_shape(
                capture,
                item.id,
                component_by_entity[item.id],
            ),
            source_ids=[item.id, *item.source_ids],
            required_for_modeling=item.required_for_modeling,
        )
        for item in capture.entities
        if item.id in entity_to_feature
    ]

    inferred_axis_values: list[DirectValueEvidence] = []
    for component in components:
        if not component:
            continue
        feature_id = entity_to_feature.get(component[0])
        if feature_id is None:
            continue
        component_axis, axis_sources = _component_axis_from_projections(
            capture,
            component,
        )
        if component_axis is None:
            continue
        inferred_axis_values.append(
            DirectValueEvidence(
                id=f"L_AXIS_{feature_id}",
                target=f"feature:{feature_id}.axis",
                value=component_axis,
                semantic="axis",
                source_ids=axis_sources,
            )
        )

    direct_values, direct_unresolved = _normalize_direct_values(
        [
            *[
                DirectValueEvidence(
                    id=item.id,
                    target=(
                        f"feature:{entity_to_feature[item.entity_id]}."
                        f"{_canonical_field(capture, item.entity_id, item.field)}"
                    ),
                    value=item.value,
                    semantic=item.semantic,
                    source_ids=item.source_ids,
                )
                for item in capture.values
                if item.entity_id in entity_to_feature
            ],
            *inferred_axis_values,
        ]
    )
    unresolved.extend(direct_unresolved)

    dimensions: list[DimensionObservation] = []
    synthetic_relations: list[RelationEvidence] = []
    profile_span_centers = _validated_profile_span_centers(
        capture,
        entity_to_feature,
    )
    symmetric_dimension_pairs = _validated_symmetric_dimension_pairs(capture)
    for item in capture.dimensions:
        if any(endpoint.role == "unresolved" for endpoint in item.endpoints):
            endpoint_matches = _dimension_span_center_endpoint_matches(
                capture,
                dimension=item,
                span_centers=profile_span_centers,
            )
            if endpoint_matches is not None:
                bridged_relation = _dimension_relation_from_span_center_identity(
                    dimension=item,
                    endpoint_matches=endpoint_matches,
                    entity_to_feature=entity_to_feature,
                )
                if bridged_relation is not None:
                    synthetic_relations.append(bridged_relation)
                    continue

            symmetric_bridge = _symmetric_center_distance_bridge(
                capture,
                dimension=item,
                span_centers=profile_span_centers,
                symmetric_pairs=symmetric_dimension_pairs,
            )
            if symmetric_bridge is not None:
                synthetic_relations.extend(symmetric_bridge)
                continue

            projected_profile_bridge = _projected_profile_dimension_bridge(
                capture,
                dimension=item,
                entity_to_feature=entity_to_feature,
                symmetric_pairs=symmetric_dimension_pairs,
            )
            if projected_profile_bridge is not None:
                synthetic_relations.extend(projected_profile_bridge)
                continue

            related_entity_ids = sorted(
                {
                    entity_id
                    for endpoint in item.endpoints
                    for entity_id in (
                        ([endpoint.entity_id] if endpoint.entity_id else [])
                        + endpoint.candidate_entity_ids
                    )
                }
            )
            unresolved_kinds = sorted(
                {
                    endpoint.unresolved_kind
                    for endpoint in item.endpoints
                    if (
                        endpoint.role == "unresolved"
                        and endpoint.unresolved_kind is not None
                    )
                }
            )
            endpoint_source_ids = [
                source_id
                for endpoint in item.endpoints
                for source_id in endpoint.source_ids
            ]
            axis_leaf = item.axis.lower()
            endpoint_specs: list[dict[str, Any]] = []
            for endpoint_index, endpoint in enumerate(item.endpoints):
                downstream_role = (
                    "feature_center"
                    if endpoint.role == "entity_center"
                    else endpoint.role
                )
                spec: dict[str, Any] = {
                    "index": endpoint_index,
                    "role": downstream_role,
                    "unresolved_kind": endpoint.unresolved_kind,
                    "source_ids": endpoint.source_ids,
                }
                if endpoint.role in {"entity_center", "profile_boundary"} and endpoint.entity_id:
                    feature_id = entity_to_feature.get(endpoint.entity_id)
                    if feature_id:
                        suffix = (
                            f"centerline.{axis_leaf}"
                            if endpoint.role == "entity_center"
                            else f"boundary.{axis_leaf}"
                        )
                        spec["target"] = f"feature:{feature_id}.{suffix}"
                if endpoint.role == "unresolved":
                    candidate_targets: set[str] = set()
                    for entity_id in endpoint.candidate_entity_ids:
                        feature_id = entity_to_feature.get(entity_id)
                        component_entity_ids = component_by_entity.get(entity_id)
                        if feature_id is None or component_entity_ids is None:
                            continue
                        shape = _canonical_projection_shape(
                            capture,
                            entity_id,
                            component_entity_ids,
                        )
                        suffix = (
                            f"boundary.{axis_leaf}"
                            if shape == "profile"
                            else f"centerline.{axis_leaf}"
                        )
                        candidate_targets.add(
                            f"feature:{feature_id}.{suffix}"
                        )
                    spec["candidate_targets"] = sorted(candidate_targets)
                endpoint_specs.append(spec)

            unresolved.append(
                {
                    "id": f"U_DIM_{item.id}",
                    "kind": "dimension_endpoint",
                    "reason": item.unresolved_reason
                    or "dimension endpoint ownership is unresolved",
                    "required_for_modeling": item.required_for_modeling,
                    "entity_ids": related_entity_ids,
                    "capture_dimension_id": item.id,
                    "dimension_value": item.value,
                    "axis": item.axis,
                    "dimension_direction": item.direction,
                    "endpoint_unresolved_kinds": unresolved_kinds,
                    "endpoint_specs": endpoint_specs,
                    "source_ids": list(
                        dict.fromkeys([*item.source_ids, *endpoint_source_ids])
                    ),
                }
            )
            continue

        endpoints: list[DimensionEndpoint] = []
        local_endpoint_entities: list[str] = []
        for endpoint in item.endpoints:
            if endpoint.role == "overall_min":
                endpoints.append(DimensionEndpoint(role="overall_min"))
                continue
            if endpoint.role == "overall_max":
                endpoints.append(DimensionEndpoint(role="overall_max"))
                continue

            assert endpoint.role in {"entity_center", "profile_boundary"}
            assert endpoint.entity_id is not None
            local_endpoint_entities.append(endpoint.entity_id)
            axis_leaf = item.axis.lower()
            if endpoint.role == "entity_center":
                endpoints.append(
                    DimensionEndpoint(
                        role="feature_center",
                        target=(
                            f"feature:{entity_to_feature[endpoint.entity_id]}"
                            f".centerline.{axis_leaf}"
                        ),
                    )
                )
            else:
                endpoints.append(
                    DimensionEndpoint(
                        role="profile_boundary",
                        target=(
                            f"feature:{entity_to_feature[endpoint.entity_id]}"
                            f".boundary.{axis_leaf}"
                        ),
                    )
                )

        profile_boundary_targets = [
            endpoint.target
            for endpoint in endpoints
            if endpoint.role == "profile_boundary" and endpoint.target
        ]
        if (
            len(profile_boundary_targets) == 2
            and len(set(profile_boundary_targets)) == 2
        ):
            endpoint_source_ids = [
                source_id
                for endpoint in item.endpoints
                for source_id in endpoint.source_ids
            ]
            midpoint_relation = _profile_span_midpoint_relation(
                dimension=item,
                boundary_targets=profile_boundary_targets,
                endpoint_source_ids=endpoint_source_ids,
            )
            if (
                midpoint_relation is not None
                and not any(
                    relation.id == midpoint_relation.id
                    for relation in synthetic_relations
                )
            ):
                synthetic_relations.append(midpoint_relation)
            centered_relation = _profile_span_centered_relation(
                dimension=item,
                boundary_targets=profile_boundary_targets,
                endpoint_source_ids=endpoint_source_ids,
            )
            if (
                centered_relation is not None
                and not any(
                    relation.id == centered_relation.id
                    for relation in synthetic_relations
                )
            ):
                synthetic_relations.append(centered_relation)

        if (
            len(profile_boundary_targets) == 2
            and len(set(profile_boundary_targets)) == 2
            and len(local_endpoint_entities) == 2
        ):
            structured_profile_sources = _structured_symmetric_profile_span_sources(
                capture,
                dimension=item,
                endpoint_entity_ids=local_endpoint_entities,
            )
            if structured_profile_sources:
                overall_extent = {
                    "X": capture.overall_dimensions.length_x,
                    "Y": capture.overall_dimensions.width_y,
                    "Z": capture.overall_dimensions.height_z,
                }[item.axis]
                if item.direction in {-1, 1} and item.value <= overall_extent + 1e-9:
                    endpoint_source_ids = [
                        source_id
                        for endpoint in item.endpoints
                        for source_id in endpoint.source_ids
                    ]
                    all_source_ids = list(
                        dict.fromkeys(
                            [
                                *item.source_ids,
                                *endpoint_source_ids,
                                *structured_profile_sources,
                            ]
                        )
                    )
                    synthetic_relations.append(
                        RelationEvidence(
                            id=f"R_SYMMETRIC_PROFILE_ANCHOR_{item.id}",
                            kind="edge_offset",
                            axis=item.axis,
                            value=max(0.0, (overall_extent - item.value) / 2.0),
                            from_side="min" if item.direction == 1 else "max",
                            targets=[profile_boundary_targets[0]],
                            source_ids=all_source_ids,
                            required_for_modeling=item.required_for_modeling,
                            metadata={
                                "basis": (
                                    "structured_overall_center_symmetric_profile_span"
                                ),
                                "overall_extent": overall_extent,
                            },
                        )
                    )

        feature_center_targets = [
            endpoint.target
            for endpoint in endpoints
            if endpoint.role == "feature_center" and endpoint.target
        ]
        if (
            len(feature_center_targets) == 2
            and feature_center_targets[0] == feature_center_targets[1]
        ):
            endpoint_source_ids = [
                source_id
                for endpoint in item.endpoints
                for source_id in endpoint.source_ids
            ]
            base_source_ids = list(
                dict.fromkeys([*item.source_ids, *endpoint_source_ids])
            )
            feature_ids = {
                entity_to_feature[entity_id]
                for entity_id in local_endpoint_entities
                if entity_id in entity_to_feature
            }
            feature_id = next(iter(feature_ids)) if len(feature_ids) == 1 else None
            structured_symmetry_sources = (
                _structured_symmetric_count_two_sources(
                    capture,
                    feature_id=feature_id,
                    axis=item.axis,
                    entity_to_feature=entity_to_feature,
                )
                if feature_id is not None
                else []
            )
            all_source_ids = list(
                dict.fromkeys([*base_source_ids, *structured_symmetry_sources])
            )
            count_value = (
                _direct_target_value(
                    direct_values,
                    f"feature:{feature_id}.count",
                )
                if feature_id is not None
                else None
            )
            raw_feature_axis = (
                _direct_target_value(
                    direct_values,
                    f"feature:{feature_id}.axis",
                )
                if feature_id is not None
                else None
            )
            feature_axis: Axis | None
            if raw_feature_axis == "X":
                feature_axis = "X"
            elif raw_feature_axis == "Y":
                feature_axis = "Y"
            elif raw_feature_axis == "Z":
                feature_axis = "Z"
            else:
                feature_axis = None
            center_indexes: dict[Axis, int] = (
                _TRANSVERSE_CENTER_INDEX[feature_axis]
                if feature_axis is not None
                else {}
            )
            coordinate_index = center_indexes.get(item.axis)
            symmetry_proven = bool(structured_symmetry_sources)
            count_is_two = (
                not isinstance(count_value, bool)
                and isinstance(count_value, (int, float))
                and float(count_value) == 2.0
            )
            overall_extent = {
                "X": capture.overall_dimensions.length_x,
                "Y": capture.overall_dimensions.width_y,
                "Z": capture.overall_dimensions.height_z,
            }[item.axis]
            can_expand_symmetric_pair = (
                symmetry_proven
                and feature_id is not None
                and count_is_two
                and coordinate_index is not None
                and item.direction in {-1, 1}
                and item.value <= overall_extent + 1e-9
            )

            if can_expand_symmetric_pair:
                assert feature_id is not None
                assert coordinate_index is not None
                member_targets = [
                    (
                        f"feature:{feature_id}.explicit_centers."
                        f"{member_index}.{coordinate_index}"
                    )
                    for member_index in range(2)
                ]
                endpoints = [
                    DimensionEndpoint(
                        role="feature_center",
                        target=member_targets[0],
                    ),
                    DimensionEndpoint(
                        role="feature_center",
                        target=member_targets[1],
                    ),
                ]

                offset = max(0.0, (overall_extent - item.value) / 2.0)
                synthetic_relations.append(
                    RelationEvidence(
                        id=f"R_SYMMETRIC_ANCHOR_{item.id}",
                        kind="edge_offset",
                        axis=item.axis,
                        value=offset,
                        from_side=(
                            "min"
                            if item.direction == 1
                            else "max"
                        ),
                        targets=[member_targets[0]],
                        source_ids=all_source_ids,
                        required_for_modeling=item.required_for_modeling,
                        metadata={
                            "basis": (
                                "structured_overall_center_symmetry_plus_spacing"
                                if structured_symmetry_sources
                                else "overall_center_symmetry_plus_spacing"
                            ),
                            "overall_extent": overall_extent,
                        },
                    )
                )

                other_axes: list[Axis] = [
                    axis_name
                    for axis_name in center_indexes
                    if axis_name != item.axis
                ]
                if len(other_axes) == 1:
                    other_axis = other_axes[0]
                    other_index = center_indexes[other_axis]
                    synthetic_relations.append(
                        RelationEvidence(
                            id=f"R_SYMMETRIC_ROW_{item.id}",
                            kind="alignment",
                            axis=other_axis,
                            targets=[
                                f"feature:{feature_id}.centerline.{other_axis.lower()}",
                                f"feature:{feature_id}.explicit_centers.0.{other_index}",
                                f"feature:{feature_id}.explicit_centers.1.{other_index}",
                            ],
                            source_ids=all_source_ids,
                            required_for_modeling=item.required_for_modeling,
                            metadata={
                                "basis": "collapsed_projection_shared_transverse_center",
                            },
                        )
                    )
            else:
                unresolved.append(
                    {
                        "id": f"U_DIM_COLLAPSE_{item.id}",
                        "kind": "dimension_endpoint",
                        "reason": (
                            "dimension endpoints collapse to the same physical "
                            "center target after identity linking"
                        ),
                        "required_for_modeling": item.required_for_modeling,
                        "entity_ids": sorted(set(local_endpoint_entities)),
                        "capture_dimension_id": item.id,
                        "dimension_value": item.value,
                        "axis": item.axis,
                        "source_ids": item.source_ids,
                    }
                )
                continue

        endpoint_source_ids = [
            source_id
            for endpoint in item.endpoints
            for source_id in endpoint.source_ids
        ]
        dimensions.append(
            DimensionObservation(
                id=item.id,
                value=item.value,
                axis=item.axis,
                endpoints=endpoints,
                direction=item.direction,
                source_ids=list(
                    dict.fromkeys([*item.source_ids, *endpoint_source_ids])
                ),
                required_for_modeling=item.required_for_modeling,
            )
        )

    datum_alignments = [
        DatumAlignmentEvidence(
            id=item.id,
            target=(
                f"feature:{entity_to_feature[item.entity_id]}"
                f".centerline.{item.axis.lower()}"
            ),
            axis=item.axis,
            datum=item.datum,
            source_ids=item.source_ids,
            required_for_modeling=item.required_for_modeling,
        )
        for item in capture.datum_alignments
    ]

    for item in capture.centerline_alignments:
        feature_ids = [
            entity_to_feature[entity_id]
            for entity_id in item.entity_ids
            if entity_id in entity_to_feature
        ]
        if len(feature_ids) != len(item.entity_ids) or len(set(feature_ids)) < 2:
            continue
        for alignment_axis in _ALL_AXES:
            if alignment_axis == item.feature_axis:
                continue
            synthetic_relations.append(
                RelationEvidence(
                    id=f"{item.id}_{alignment_axis}",
                    kind="alignment",
                    axis=alignment_axis,
                    targets=[
                        f"feature:{feature_id}.centerline.{alignment_axis.lower()}"
                        for feature_id in feature_ids
                    ],
                    source_ids=item.source_ids,
                    required_for_modeling=item.required_for_modeling,
                    metadata={
                        "basis": "coaxial_centerline_alignment",
                        "feature_axis": item.feature_axis,
                    },
                )
            )

    slot_tangent_relations, slot_relation_resolved_fields = (
        _open_slot_tangent_relations(capture, entity_to_feature)
    )
    synthetic_relations.extend(slot_tangent_relations)
    synthetic_relations.extend(
        _view_axis_boundary_relations(
            capture,
            entity_to_feature,
        )
    )

    required_targets = {
        item.target
        for item in direct_values
        if _resolver_numeric_value(item.value)
    }
    for item in dimensions:
        if not item.required_for_modeling:
            continue
        for endpoint in item.endpoints:
            if endpoint.role in {"feature_center", "profile_boundary"} and endpoint.target:
                required_targets.add(endpoint.target)
    for item in datum_alignments:
        if item.required_for_modeling:
            required_targets.add(item.target)
    for relation in synthetic_relations:
        if relation.required_for_modeling:
            required_targets.update(relation.targets)
    required_targets = sorted(required_targets)

    evidence = EvidenceGraph(
        schema_version="1.0",
        coordinate_system=capture.coordinate_system,
        overall_dimensions=capture.overall_dimensions,
        views=views,
        projections=projections,
        dimensions=dimensions,
        datum_alignments=datum_alignments,
        direct_values=direct_values,
        relations=synthetic_relations,
        required_targets=required_targets,
        observations=[
            *_linked_rotational_profile_topology_observations(
                capture,
                entity_to_feature,
            ),
            {
                "kind": "reader_required_targets_advisory",
                "items": [
                    item.model_dump(mode="json")
                    for item in capture.required_targets
                ],
            },
            {
                "kind": "identity_linker_v2",
                "entity_to_feature": dict(sorted(entity_to_feature.items())),
                "ignored_orphan_profiles": ignored_orphan_profiles,
            },
        ],
        unresolved_evidence=[
            *_linked_reader_unresolved(
                capture,
                entity_to_feature,
                relation_resolved_fields=slot_relation_resolved_fields,
            ),
            *[
                {
                    **item,
                    **(
                        {
                            "feature_ids": sorted(
                                {
                                    entity_to_feature[entity_id]
                                    for entity_id in item.get("entity_ids", [])
                                    if entity_id in entity_to_feature
                                }
                            )
                        }
                        if item.get("entity_ids")
                        else {}
                    ),
                }
                for item in unresolved
            ],
        ],
    )

    report = {
        "capture_entities": len(capture.entities),
        "physical_components": len(components),
        "association_claims": len(capture.associations),
        "rejected_associations": sum(
            1
            for item in unresolved
            if str(item.get("id", "")).startswith("U_ASSOC")
        ),
        "ignored_orphan_profiles": len(ignored_orphan_profiles),
        "identity_collisions": len(collision_ids),
        "blocking_unresolved": sum(
            1
            for item in evidence.unresolved_evidence
            if item.get("required_for_modeling", True)
        ),
    }
    return IdentityLinkResult(
        evidence=evidence,
        entity_to_feature=entity_to_feature,
        report=report,
    )
