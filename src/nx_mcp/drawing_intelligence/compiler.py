from __future__ import annotations

import copy
import re
from typing import Any, Literal, cast

from .evidence import (
    Axis,
    DatumAlignmentEvidence,
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


def _compile_overall_dimension_facts(
    graph: EvidenceGraph,
    direct: list[DirectValueEvidence],
    unresolved: list[dict[str, Any]],
) -> None:
    expected = {
        "X": ("overall_dimensions.length_x", graph.overall_dimensions.length_x),
        "Y": ("overall_dimensions.width_y", graph.overall_dimensions.width_y),
        "Z": ("overall_dimensions.height_z", graph.overall_dimensions.height_z),
    }

    for observation_index, observation in enumerate(graph.observations):
        if not isinstance(observation, dict):
            continue
        if observation.get("kind") != "overall_dimension_fact_ledger":
            continue
        facts = observation.get("facts")
        if not isinstance(facts, list):
            continue

        for fact_index, fact in enumerate(facts):
            if not isinstance(fact, dict):
                continue
            axis = str(fact.get("axis") or "").upper()
            if axis not in expected:
                continue
            value = fact.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            target, expected_value = expected[axis]
            source_ids = [
                item
                for item in fact.get("evidence", [])
                if isinstance(item, str) and item
            ]
            if abs(float(value) - float(expected_value)) > 1e-9:
                _append_unresolved(
                    unresolved,
                    uid=f"U_OVERALL_FACT_{axis}_{observation_index}_{fact_index}",
                    reason=(
                        f"overall dimension fact for axis {axis} disagrees with "
                        f"canonical overall_dimensions: {value!r} vs {expected_value!r}"
                    ),
                    target=target,
                    evidence=source_ids,
                )
                continue

            _append_direct(
                direct,
                unresolved,
                DirectValueEvidence(
                    id=f"ODF_{axis}_{observation_index}_{fact_index}",
                    target=target,
                    value=float(value),
                    semantic="overall_dimension",
                    source_ids=source_ids,
                ),
            )


def _compile_overall_dimension_derivations(
    graph: EvidenceGraph,
    relations: list[RelationEvidence],
    unresolved: list[dict[str, Any]],
) -> None:
    expected = {
        "X": ("overall_dimensions.length_x", graph.overall_dimensions.length_x),
        "Y": ("overall_dimensions.width_y", graph.overall_dimensions.width_y),
        "Z": ("overall_dimensions.height_z", graph.overall_dimensions.height_z),
    }

    for observation_index, observation in enumerate(graph.observations):
        if observation.get("kind") != "overall_dimension_derivation_ledger":
            continue
        facts = observation.get("facts")
        if not isinstance(facts, list):
            continue

        for fact_index, fact in enumerate(facts):
            if not isinstance(fact, dict):
                continue
            axis = str(fact.get("axis") or "").upper()
            source_axis = str(fact.get("source_axis") or "").upper()
            rotation_axis = str(fact.get("rotation_axis") or "").upper()
            basis = str(fact.get("basis") or "")
            value = fact.get("value")
            source_ids = [
                item
                for item in fact.get("evidence", [])
                if isinstance(item, str) and item
            ]

            valid_axes = {"X", "Y", "Z"}
            if (
                axis not in valid_axes
                or source_axis not in valid_axes
                or rotation_axis not in valid_axes
                or basis != "rotational_symmetry_equal_transverse_extents"
                or axis == source_axis
                or rotation_axis in {axis, source_axis}
            ):
                _append_unresolved(
                    unresolved,
                    uid=f"U_OVERALL_DERIVATION_{observation_index}_{fact_index}",
                    reason="invalid rotational-symmetry overall derivation contract",
                    evidence=source_ids,
                )
                continue

            axis_typed = cast(Axis, axis)
            source_axis_typed = cast(Axis, source_axis)
            rotation_axis_typed = cast(Axis, rotation_axis)

            target, expected_value = expected[axis_typed]
            source_target, expected_source_value = expected[source_axis_typed]
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or abs(float(value) - float(expected_value)) > 1e-9
                or abs(float(value) - float(expected_source_value)) > 1e-9
            ):
                _append_unresolved(
                    unresolved,
                    uid=f"U_OVERALL_DERIVATION_{axis}_{observation_index}_{fact_index}",
                    reason=(
                        "rotational-symmetry overall derivation disagrees with "
                        "canonical overall_dimensions"
                    ),
                    target=target,
                    evidence=source_ids,
                )
                continue

            _append_relation(
                relations,
                RelationEvidence(
                    id=f"ODR_{axis}_{observation_index}_{fact_index}",
                    kind="alignment",
                    axis=axis_typed,
                    targets=[source_target, target],
                    source_ids=source_ids,
                    required_for_modeling=True,
                    metadata={
                        "basis": basis,
                        "rotation_axis": rotation_axis_typed,
                        "source_axis": source_axis_typed,
                    },
                ),
            )


def _compile_labeled_profile_transitions(
    graph: EvidenceGraph,
    relations: list[RelationEvidence],
    unresolved: list[dict[str, Any]],
) -> None:
    """Compile only deterministic overall-to-profile transition offsets.

    The OCR value remains authoritative. Structural Context supplies the bounded
    relation semantic, while raster geometry is provenance-only and never
    becomes an engineering coordinate. Profile-to-profile dimensions remain
    provenance-only until both endpoint identities are deterministically known.
    """

    overall_by_axis = {
        "X": float(graph.overall_dimensions.length_x),
        "Y": float(graph.overall_dimensions.width_y),
        "Z": float(graph.overall_dimensions.height_z),
    }

    for observation_index, observation in enumerate(graph.observations):
        if (
            not isinstance(observation, dict)
            or observation.get("kind")
            != "hybrid_labeled_dimension_relation_ledger"
            or observation.get("schema") != "1.0"
            or observation.get("engineering_value_source") != "hybrid_ocr"
            or observation.get("relation_source") != "bounded_structural_context"
            or observation.get("engineering_coordinate_inferred_from_pixels") is not False
            or observation.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue

        items = observation.get("items")
        if not isinstance(items, list):
            continue

        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            relation = str(item.get("relation") or "")
            if relation not in {
                "overall_min_to_profile_transition",
                "overall_max_to_profile_transition",
            }:
                continue

            target_id = str(item.get("target_id") or "")
            axis = str(item.get("axis") or "").upper()
            value = item.get("value")
            source_ids = [
                source
                for source in item.get("evidence", [])
                if isinstance(source, str) and source
            ]

            if (
                not target_id
                or axis not in {"X", "Y", "Z"}
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) <= 0.0
                or float(value) >= overall_by_axis[axis]
                or item.get("engineering_coordinate_inferred_from_pixels") is not False
                or item.get("pixel_geometry_used_for_topology_only") is not True
            ):
                _append_unresolved(
                    unresolved,
                    uid=(
                        "U_LABELED_PROFILE_TRANSITION_"
                        f"{observation_index}_{item_index}"
                    ),
                    reason=(
                        "invalid labeled overall-to-profile transition contract"
                    ),
                    evidence=source_ids,
                )
                continue

            region_id = str(item.get("region_id") or "")
            expected_overall_role = (
                "overall_min"
                if relation == "overall_min_to_profile_transition"
                else "overall_max"
            )
            expected_contact_marker = (
                "hybrid:labeled-overall-boundary-contact:"
                f"{region_id}:{axis}:{expected_overall_role}"
            )
            if not region_id or expected_contact_marker not in source_ids:
                _append_unresolved(
                    unresolved,
                    uid=(
                        "U_LABELED_PROFILE_TRANSITION_CONTACT_"
                        f"{observation_index}_{item_index}"
                    ),
                    reason=(
                        "labeled overall-to-profile relation lacks deterministic "
                        "overall-boundary contact evidence"
                    ),
                    evidence=source_ids,
                )
                continue

            axis_typed = cast(Axis, axis)
            side: Literal["min", "max"] = (
                "min"
                if relation == "overall_min_to_profile_transition"
                else "max"
            )
            target = (
                "constraints.profile_transitions."
                f"{target_id}.{axis.lower()}"
            )
            relation_id = f"LPT_{target_id}"

            _append_relation(
                relations,
                RelationEvidence(
                    id=relation_id,
                    kind="edge_offset",
                    axis=axis_typed,
                    targets=[target],
                    value=float(value),
                    from_side=side,
                    source_ids=source_ids,
                    required_for_modeling=True,
                    metadata={
                        "basis": "labeled_overall_to_profile_transition",
                        "labeled_target_id": target_id,
                        "relation": relation,
                        "profile_transition_geometry": item.get(
                            "profile_transition_geometry"
                        ),
                        "symmetry_scope": item.get("symmetry_scope"),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    },
                ),
            )


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


def _target_axis(target: str) -> str | None:
    lower = target.lower()
    if lower.endswith(".x") or lower.endswith("_x"):
        return "X"
    if lower.endswith(".y") or lower.endswith("_y"):
        return "Y"
    if lower.endswith(".z") or lower.endswith("_z"):
        return "Z"

    match = re.search(r"\.explicit_centers\.\d+\.(0|1|2)$", lower)
    if match:
        return {"0": "X", "1": "Y", "2": "Z"}[match.group(1)]
    return None


def _overall_center_value(graph: EvidenceGraph, axis: str) -> float:
    """Return the center in Reader-local 0..overall engineering coordinates."""

    return _overall_value(graph, axis) / 2.0


def _compile_datum_alignments(
    graph: EvidenceGraph,
    direct: list[DirectValueEvidence],
    unresolved: list[dict[str, Any]],
) -> None:
    for observation in sorted(graph.datum_alignments, key=lambda item: item.id):
        target_axis = _target_axis(observation.target)
        if target_axis != observation.axis:
            _append_unresolved(
                unresolved,
                uid=f"U_{observation.id}",
                reason=(
                    f"datum alignment axis {observation.axis} is incompatible with "
                    f"target {observation.target!r}"
                ),
                target=observation.target,
                required=observation.required_for_modeling,
                evidence=[observation.id, *observation.source_ids],
            )
            continue

        _append_direct(
            direct,
            unresolved,
            DirectValueEvidence(
                id=observation.id,
                target=observation.target,
                value=_overall_center_value(graph, observation.axis),
                semantic="center_position",
                source_ids=observation.source_ids,
            ),
        )


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
    measured = next(
        (
            endpoint
            for endpoint in observation.endpoints
            if endpoint.role in {"feature_center", "profile_boundary"}
        ),
        None,
    )
    if boundary is None or measured is None or not measured.target:
        return False
    _append_relation(
        relations,
        RelationEvidence(
            id=observation.id,
            kind="edge_offset",
            axis=observation.axis,
            value=observation.value,
            from_side="min" if boundary.role == "overall_min" else "max",
            targets=[measured.target],
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
    typed_targets = [
        target
        for target in targets
        if isinstance(target, str) and target
    ]
    if len(typed_targets) != 2:
        return False
    first_feature = _feature_id(typed_targets[0])
    second_feature = _feature_id(typed_targets[1])
    kind: Literal["center_spacing", "center_distance"] = (
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
            targets=typed_targets,
            source_ids=observation.source_ids,
            required_for_modeling=observation.required_for_modeling,
        ),
    )
    return True


def _compile_coordinate_distance(
    observation: DimensionObservation,
    relations: list[RelationEvidence],
) -> bool:
    roles = {endpoint.role for endpoint in observation.endpoints}
    if not roles.issubset({"feature_center", "profile_boundary"}):
        return False
    if roles == {"feature_center"}:
        return False
    targets = [
        endpoint.target
        for endpoint in observation.endpoints
        if isinstance(endpoint.target, str) and endpoint.target
    ]
    if len(targets) != 2:
        return False
    _append_relation(
        relations,
        RelationEvidence(
            id=observation.id,
            kind="coordinate_distance",
            axis=observation.axis,
            value=observation.value,
            direction=observation.direction,
            targets=targets,
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
        if _compile_coordinate_distance(observation, relations):
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

    _compile_overall_dimension_facts(graph, direct, unresolved)
    _compile_overall_dimension_derivations(graph, relations, unresolved)
    _compile_labeled_profile_transitions(graph, relations, unresolved)
    _compile_axis_evidence(graph, direct, unresolved)
    _compile_datum_alignments(graph, direct, unresolved)
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
