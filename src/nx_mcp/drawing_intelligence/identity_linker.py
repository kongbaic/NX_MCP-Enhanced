from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .capture import ReaderCapture
from .evidence import (
    DatumAlignmentEvidence,
    DimensionEndpoint,
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    ProjectionEvidence,
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

    for item in capture.datum_alignments:
        referenced.add(item.entity_id)

    for item in capture.required_targets:
        referenced.add(item.entity_id)

    for item in capture.unresolved_evidence:
        referenced.update(item.entity_ids)

    return referenced


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

    values = sorted(
        [
            {
                "field": _canonical_field(
                    capture,
                    item.entity_id,
                    item.field,
                ),
                "value": _canon(item.value),
                "semantic": item.semantic,
            }
            for item in capture.values
            if item.entity_id in entity_set
        ],
        key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
    )

    datums = sorted(
        [
            {
                "axis": item.axis,
                "datum": item.datum,
            }
            for item in capture.datum_alignments
            if item.entity_id in entity_set
        ],
        key=lambda item: json.dumps(item, sort_keys=True),
    )

    return {
        "projections": projections,
        "values": values,
        "datums": datums,
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
        "shared_centerline",
        "shared_center_mark",
        "matching_specification",
        "leader_correspondence",
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
    uf = _UnionFind(list(entities))
    unresolved: list[dict[str, Any]] = []

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

    direct_values = [
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

    dimensions: list[DimensionObservation] = []
    for item in capture.dimensions:
        endpoints: list[DimensionEndpoint] = []
        for endpoint in item.endpoints:
            if endpoint.role in {"overall_min", "overall_max"}:
                endpoints.append(DimensionEndpoint(role=endpoint.role))
            else:
                assert endpoint.entity_id is not None
                axis_leaf = item.axis.lower()
                endpoints.append(
                    DimensionEndpoint(
                        role="feature_center",
                        target=(
                            f"feature:{entity_to_feature[endpoint.entity_id]}"
                            f".centerline.{axis_leaf}"
                        ),
                    )
                )

        dimensions.append(
            DimensionObservation(
                id=item.id,
                value=item.value,
                axis=item.axis,
                endpoints=endpoints,
                direction=item.direction,
                source_ids=item.source_ids,
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

    required_targets = {
        item.target
        for item in direct_values
    }
    for item in dimensions:
        if not item.required_for_modeling:
            continue
        for endpoint in item.endpoints:
            if endpoint.role == "feature_center" and endpoint.target:
                required_targets.add(endpoint.target)
    for item in datum_alignments:
        if item.required_for_modeling:
            required_targets.add(item.target)
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
        relations=[],
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
