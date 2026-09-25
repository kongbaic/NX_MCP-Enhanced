from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .capture import AssociationClaim, ReaderCapture
from .evidence import (
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

_TRANSVERSE_CENTER_INDEX: dict[str, dict[str, int]] = {
    "X": {"Y": 0, "Z": 1},
    "Y": {"X": 0, "Z": 1},
    "Z": {"X": 0, "Y": 1},
}


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


def _association_basis_sufficient(basis: list[str]) -> bool:
    kinds = set(basis)

    if "explicit_section_correspondence" in kinds:
        return True

    supporting = {
        "matching_specification",
        "leader_correspondence",
        "unique_orthographic_counterpart",
    }
    return (
        "projection_alignment" in kinds
        and bool(kinds & supporting)
    )


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


def _linked_reader_unresolved(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for item in capture.unresolved_evidence:
        feature_ids = sorted(
            {
                entity_to_feature[entity_id]
                for entity_id in item.entity_ids
                if entity_id in entity_to_feature
            }
        )
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
        for fid in sorted(collision_ids):
            unresolved.append(
                {
                    "id": f"U_IDENTITY_COLLISION_{fid}",
                    "reason": (
                        "multiple disconnected capture components have the same "
                        "semantic signature; deterministic physical identity is "
                        "not unique"
                    ),
                    "required_for_modeling": True,
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

    direct_values, direct_unresolved = _normalize_direct_values(
        [
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
        ]
    )
    unresolved.extend(direct_unresolved)

    dimensions: list[DimensionObservation] = []
    synthetic_relations: list[RelationEvidence] = []
    for item in capture.dimensions:
        if any(endpoint.role == "unresolved" for endpoint in item.endpoints):
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
                    spec["candidate_targets"] = sorted(
                        {
                            (
                                f"feature:{entity_to_feature[entity_id]}"
                                f".centerline.{axis_leaf}"
                            )
                            for entity_id in endpoint.candidate_entity_ids
                            if entity_id in entity_to_feature
                        }
                    )
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
            all_source_ids = list(
                dict.fromkeys([*item.source_ids, *endpoint_source_ids])
            )
            feature_ids = {
                entity_to_feature[entity_id]
                for entity_id in local_endpoint_entities
                if entity_id in entity_to_feature
            }
            feature_id = next(iter(feature_ids)) if len(feature_ids) == 1 else None
            count_value = (
                _direct_target_value(
                    direct_values,
                    f"feature:{feature_id}.count",
                )
                if feature_id is not None
                else None
            )
            feature_axis = str(
                _direct_target_value(
                    direct_values,
                    f"feature:{feature_id}.axis",
                )
                if feature_id is not None
                else ""
            ).upper()
            center_indexes = _TRANSVERSE_CENTER_INDEX.get(feature_axis, {})
            coordinate_index = center_indexes.get(item.axis)
            marker_present = _SYMMETRIC_COUNT_TWO_MARKER in all_source_ids
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
                marker_present
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
                            "basis": "overall_center_symmetry_plus_spacing",
                            "overall_extent": overall_extent,
                        },
                    )
                )

                other_axes = [
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
        for axis in ("X", "Y", "Z"):
            if axis == item.feature_axis:
                continue
            synthetic_relations.append(
                RelationEvidence(
                    id=f"{item.id}_{axis}",
                    kind="alignment",
                    axis=axis,
                    targets=[
                        f"feature:{feature_id}.centerline.{axis.lower()}"
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
            *capture.observations,
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
            *_linked_reader_unresolved(capture, entity_to_feature),
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
