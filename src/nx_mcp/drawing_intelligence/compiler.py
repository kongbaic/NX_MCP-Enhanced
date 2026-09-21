from __future__ import annotations

import copy
import re
from typing import Any

from .evidence import (
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    RelationEvidence,
)

_VIEW_NORMAL = {
    "front": "Y",
    "side": "X",
    "top": "Z",
}
_CIRCULAR_PROJECTIONS = {"circle", "concentric_circles"}
_OVERALL_TARGET = {
    "X": "overall_dimensions.length_x",
    "Y": "overall_dimensions.width_y",
    "Z": "overall_dimensions.height_z",
}


class EvidenceCompileError(ValueError):
    """Raw evidence cannot be deterministically compiled."""


def _feature_id(target: str) -> str | None:
    if not target.startswith("feature:"):
        return None
    rest = target[len("feature:") :]
    feature_id = rest.partition(".")[0]
    return feature_id or None


def _append_unresolved(
    unresolved: list[dict[str, Any]],
    *,
    uid: str,
    reason: str,
    target: str | None = None,
    required: bool = True,
    evidence: list[str] | None = None,
) -> None:
    item: dict[str, Any] = {
        "id": uid,
        "reason": reason,
        "required_for_modeling": required,
    }
    if target:
        item["target"] = target
    if evidence:
        item["evidence"] = list(dict.fromkeys(evidence))
    unresolved.append(item)


def _append_direct(
    direct: list[DirectValueEvidence],
    unresolved: list[dict[str, Any]],
    fact: DirectValueEvidence,
) -> None:
    existing = next((item for item in direct if item.target == fact.target), None)
    if existing is None:
        if any(item.id == fact.id for item in direct):
            raise EvidenceCompileError(f"duplicate direct evidence id {fact.id!r}")
        direct.append(fact)
        return
    if existing.value != fact.value:
        _append_unresolved(
            unresolved,
            uid=f"U_CONFLICT_{fact.id}",
            reason=(
                f"direct evidence for {fact.target!r} disagrees: "
                f"{existing.value!r} vs {fact.value!r}"
            ),
            target=fact.target,
            evidence=[existing.id, fact.id, *existing.source_ids, *fact.source_ids],
        )


def _append_relation(
    relations: list[RelationEvidence],
    relation: RelationEvidence,
) -> None:
    if any(item.id == relation.id for item in relations):
        raise EvidenceCompileError(f"duplicate relation id {relation.id!r}")
    relations.append(relation)


def _compile_axis_evidence(
    graph: EvidenceGraph,
    direct: list[DirectValueEvidence],
    unresolved: list[dict[str, Any]],
) -> None:
    views = {view.id: view for view in graph.views}
    by_feature: dict[str, list[Any]] = {}
    for projection in graph.projections:
        if projection.shape in _CIRCULAR_PROJECTIONS:
            by_feature.setdefault(projection.feature_id, []).append(projection)

    for feature_id, projections in sorted(by_feature.items()):
        axes: dict[str, list[str]] = {}
        evidence_ids: list[str] = []
        required = any(item.required_for_modeling for item in projections)
        for projection in projections:
            view = views.get(projection.view_id)
            if view is None:
                _append_unresolved(
                    unresolved,
                    uid=f"U_VIEW_{projection.id}",
                    reason=f"projection references unknown view {projection.view_id!r}",
                    target=f"feature:{feature_id}.axis",
                    required=projection.required_for_modeling,
                    evidence=[projection.id, *projection.source_ids],
                )
                continue
            axis = _VIEW_NORMAL[view.kind]
            axes.setdefault(axis, []).append(projection.id)
            evidence_ids.extend(
                [projection.id, *projection.source_ids, view.id, *view.source_ids]
            )

        if len(axes) == 1:
            axis = next(iter(axes))
            _append_direct(
                direct,
                unresolved,
                DirectValueEvidence(
                    id=f"C_AXIS_{feature_id}",
                    target=f"feature:{feature_id}.axis",
                    value=axis,
                    semantic="axis",
                    source_ids=list(dict.fromkeys(evidence_ids)),
                ),
            )
        elif len(axes) > 1:
            _append_unresolved(
                unresolved,
                uid=f"U_AXIS_{feature_id}",
                reason=f"circular projections imply conflicting axes {sorted(axes)}",
                target=f"feature:{feature_id}.axis",
                required=required,
                evidence=list(dict.fromkeys(evidence_ids)),
            )


def _overall_value(graph: EvidenceGraph, axis: str) -> float:
    if axis == "X":
        return graph.overall_dimensions.length_x
    if axis == "Y":
        return graph.overall_dimensions.width_y
    return graph.overall_dimensions.height_z


def _compile_overall_dimension(
    graph: EvidenceGraph,
    observation: DimensionObservation,
    direct: list[DirectValueEvidence],
    unresolved: list[dict[str, Any]],
) -> bool:
    roles = {endpoint.role for endpoint in observation.endpoints}
    if roles != {"overall_min", "overall_max"}:
        return False
    target = _OVERALL_TARGET[observation.axis]
    declared = _overall_value(graph, observation.axis)
    if abs(declared - observation.value) > 1e-9:
        _append_unresolved(
            unresolved,
            uid=f"U_{observation.id}",
            reason=(
                f"overall {observation.axis} evidence {observation.value:g} "
                f"disagrees with declared extent {declared:g}"
            ),
            target=target,
            required=observation.required_for_modeling,
            evidence=[observation.id, *observation.source_ids],
        )
        return True
    _append_direct(
        direct,
        unresolved,
        DirectValueEvidence(
            id=observation.id,
            target=target,
            value=observation.value,
            semantic="overall_dimension",
            source_ids=observation.source_ids,
        ),
    )
    return True


def _compile_edge_offset(
    observation: DimensionObservation,
    relations: list[RelationEvidence],
) -> bool:
    boundary = next(
        (
            endpoint
            for endpoint in observation.endpoints
            if endpoint.role in {"overall_min", "overall_max"}
        ),
        None,
    )
    center = next(
        (
            endpoint
            for endpoint in observation.endpoints
            if endpoint.role == "feature_center"
        ),
        None,
    )
    if boundary is None or center is None or not center.target:
        return False
    _append_relation(
        relations,
        RelationEvidence(
            id=observation.id,
            kind="edge_offset",
            axis=observation.axis,
            value=observation.value,
            from_side="min" if boundary.role == "overall_min" else "max",
            targets=[center.target],
            source_ids=observation.source_ids,
            required_for_modeling=observation.required_for_modeling,
        ),
    )
    return True


def _compile_center_distance(
    observation: DimensionObservation,
    relations: list[RelationEvidence],
) -> bool:
    if not all(endpoint.role == "feature_center" for endpoint in observation.endpoints):
        return False
    targets = [endpoint.target for endpoint in observation.endpoints]
    if not all(isinstance(target, str) and target for target in targets):
        return False
    first_feature = _feature_id(targets[0])
    second_feature = _feature_id(targets[1])
    kind = (
        "center_spacing"
        if first_feature is not None and first_feature == second_feature
        else "center_distance"
    )
    _append_relation(
        relations,
        RelationEvidence(
            id=observation.id,
            kind=kind,
            axis=observation.axis,
            value=observation.value,
            direction=observation.direction,
            targets=[targets[0], targets[1]],
            source_ids=observation.source_ids,
            required_for_modeling=observation.required_for_modeling,
        ),
    )
    return True


def _compile_dimensions(
    graph: EvidenceGraph,
    direct: list[DirectValueEvidence],
    relations: list[RelationEvidence],
    unresolved: list[dict[str, Any]],
) -> None:
    for observation in sorted(graph.dimensions, key=lambda item: item.id):
        if _compile_overall_dimension(graph, observation, direct, unresolved):
            continue
        if _compile_edge_offset(observation, relations):
            continue
        if _compile_center_distance(observation, relations):
            continue
        _append_unresolved(
            unresolved,
            uid=f"U_{observation.id}",
            reason="dimension endpoint combination is not supported by deterministic v1 compiler",
            required=observation.required_for_modeling,
            evidence=[observation.id, *observation.source_ids],
        )


def compile_evidence_graph(graph: EvidenceGraph) -> EvidenceGraph:
    """Compile raw view/dimension evidence into formal deterministic evidence.

    This stage assigns only semantics that follow from explicit endpoint/view
    classes. It never reads the source image and never chooses among ambiguous
    interpretations.
    """

    direct = [item.model_copy(deep=True) for item in graph.direct_values]
    relations = [item.model_copy(deep=True) for item in graph.relations]
    unresolved = copy.deepcopy(graph.unresolved_evidence)

    _compile_axis_evidence(graph, direct, unresolved)
    _compile_dimensions(graph, direct, relations, unresolved)

    # Preserve deterministic ordering for byte/logical repeatability.
    direct.sort(key=lambda item: (item.target, item.id))
    relations.sort(key=lambda item: item.id)
    unresolved.sort(key=lambda item: str(item.get("id") or ""))

    return graph.model_copy(
        deep=True,
        update={
            "direct_values": direct,
            "relations": relations,
            "unresolved_evidence": unresolved,
        },
    )
