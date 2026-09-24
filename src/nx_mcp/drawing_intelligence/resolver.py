from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from typing import Any

from .evidence import EvidenceGraph, RelationEvidence

_EPS = 1e-9


@dataclass
class ResolutionResult:
    values: dict[str, float] = field(default_factory=dict)
    traces: dict[str, list[str]] = field(default_factory=dict)
    derivations: dict[str, dict[str, Any]] = field(default_factory=dict)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts and not any(
            item.get("required_for_modeling", True) for item in self.unresolved
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": dict(sorted(self.values.items())),
            "traces": {key: self.traces[key] for key in sorted(self.traces)},
            "derivations": {
                key: self.derivations[key] for key in sorted(self.derivations)
            },
            "unresolved": self.unresolved,
            "conflicts": self.conflicts,
            "ok": self.ok,
        }


class _State:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}
        self.traces: dict[str, list[str]] = {}
        self.derivations: dict[str, dict[str, Any]] = {}
        self.conflicts: list[dict[str, Any]] = []

    def assign(
        self,
        target: str,
        value: float,
        trace: list[str],
        derivation: dict[str, Any] | None = None,
    ) -> bool:
        if target not in self.values:
            self.values[target] = float(value)
            self.traces[target] = list(trace)
            if derivation is not None:
                self.derivations[target] = dict(derivation)
            return True
        if not isclose(self.values[target], float(value), abs_tol=_EPS, rel_tol=0.0):
            conflict = {
                "target": target,
                "existing": self.values[target],
                "candidate": float(value),
                "existing_trace": self.traces.get(target, []),
                "candidate_trace": list(trace),
            }
            if conflict not in self.conflicts:
                self.conflicts.append(conflict)
        return False


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _bounds(graph: EvidenceGraph, axis: str) -> tuple[float, float]:
    """Reader-local engineering bounds use overall_min=0 on every axis."""

    dims = graph.overall_dimensions
    if axis == "X":
        return (0.0, dims.length_x)
    if axis == "Y":
        return (0.0, dims.width_y)
    return (0.0, dims.height_z)


def _relation_trace(relation: RelationEvidence) -> list[str]:
    return [relation.id, *relation.source_ids]


def _apply_edge_offset(
    graph: EvidenceGraph, relation: RelationEvidence, state: _State
) -> bool:
    lo, hi = _bounds(graph, relation.axis)
    assert relation.value is not None
    assert relation.from_side is not None
    value = lo + relation.value if relation.from_side == "min" else hi - relation.value
    changed = False
    for target in relation.targets:
        changed = state.assign(
            target,
            value,
            _relation_trace(relation),
            {
                "kind": "edge_offset",
                "relation_id": relation.id,
                "dependencies": [],
            },
        ) or changed
    return changed


def _apply_alignment(relation: RelationEvidence, state: _State) -> bool:
    known = [(target, state.values[target]) for target in relation.targets if target in state.values]
    if not known:
        return False

    reference_target, reference = known[0]
    if any(
        not isclose(value, reference, abs_tol=_EPS, rel_tol=0.0)
        for _, value in known[1:]
    ):
        for target, _ in known[1:]:
            state.assign(target, reference, _relation_trace(relation))
        return False

    changed = False
    for target in relation.targets:
        if target == reference_target:
            continue
        changed = state.assign(
            target,
            reference,
            _relation_trace(relation),
            {
                "kind": "alignment",
                "relation_id": relation.id,
                "dependencies": [reference_target],
            },
        ) or changed
    return changed


def _apply_spacing(relation: RelationEvidence, state: _State) -> bool:
    first, second = relation.targets
    assert relation.value is not None
    first_known = first in state.values
    second_known = second in state.values

    if first_known and second_known:
        actual = abs(state.values[second] - state.values[first])
        if not isclose(actual, abs(relation.value), abs_tol=_EPS, rel_tol=0.0):
            conflict = {
                "relation": relation.id,
                "kind": relation.kind,
                "expected_distance": abs(relation.value),
                "actual_distance": actual,
                "targets": relation.targets,
            }
            if conflict not in state.conflicts:
                state.conflicts.append(conflict)
        return False

    # An unsigned center distance has two mathematical solutions. Do not guess.
    if relation.direction is None:
        return False

    distance = abs(relation.value)
    if first_known:
        op = "add" if relation.direction == 1 else "sub"
        value = state.values[first] + relation.direction * distance
        return state.assign(
            second,
            value,
            _relation_trace(relation),
            {
                "kind": relation.kind,
                "relation_id": relation.id,
                "dependencies": [first],
                "op": op,
            },
        )

    if second_known:
        op = "sub" if relation.direction == 1 else "add"
        value = state.values[second] - relation.direction * distance
        return state.assign(
            first,
            value,
            _relation_trace(relation),
            {
                "kind": relation.kind,
                "relation_id": relation.id,
                "dependencies": [second],
                "op": op,
            },
        )
    return False


def _apply_tangent(relation: RelationEvidence, state: _State) -> bool:
    center_target, tangent_target = relation.targets
    diameter_target = relation.diameter_target
    assert diameter_target is not None
    if center_target not in state.values or diameter_target not in state.values:
        return False
    sign = 1.0 if relation.kind == "upper_tangent" else -1.0
    tangent = state.values[center_target] + sign * state.values[diameter_target] / 2.0
    return state.assign(
        tangent_target,
        tangent,
        _relation_trace(relation),
        {
            "kind": relation.kind,
            "relation_id": relation.id,
            "dependencies": [center_target, diameter_target],
        },
    )


def _apply_relation(
    graph: EvidenceGraph, relation: RelationEvidence, state: _State
) -> bool:
    if relation.kind == "edge_offset":
        return _apply_edge_offset(graph, relation, state)
    if relation.kind == "alignment":
        return _apply_alignment(relation, state)
    if relation.kind in {"center_spacing", "center_distance"}:
        return _apply_spacing(relation, state)
    if relation.kind in {"upper_tangent", "lower_tangent"}:
        return _apply_tangent(relation, state)
    return False


def _relation_required_targets(relation: RelationEvidence) -> list[str]:
    targets = list(relation.targets)
    if relation.kind in {"upper_tangent", "lower_tangent"} and relation.diameter_target:
        targets.append(relation.diameter_target)
    return targets


def resolve_evidence_graph(graph: EvidenceGraph) -> ResolutionResult:
    """Resolve evidence with deterministic arithmetic only.

    The function never reads an image, never invents relations, and never
    chooses between multiple geometric solutions. Ambiguity remains unresolved.
    """

    state = _State()

    for fact in sorted(graph.direct_values, key=lambda item: (item.target, item.id)):
        number = _number(fact.value)
        if number is not None:
            state.assign(fact.target, number, [fact.id, *fact.source_ids, "direct_value"])

    for fact in sorted(graph.direct_facts, key=lambda item: item.target):
        state.assign(fact.target, fact.value, [*fact.source_ids, "direct_fact"])

    relations = sorted(graph.relations, key=lambda item: item.id)
    for _ in range(max(1, len(relations) + len(graph.required_targets) + 1)):
        changed = False
        for relation in relations:
            changed = _apply_relation(graph, relation, state) or changed
        if not changed:
            break

    unresolved: list[dict[str, Any]] = []

    for relation in relations:
        if not relation.required_for_modeling:
            continue
        required = _relation_required_targets(relation)
        missing = [target for target in required if target not in state.values]
        if not missing:
            continue
        if relation.kind in {"center_spacing", "center_distance"}:
            reason = (
                "center distance has no unique signed solution"
                if relation.direction is None
                else "insufficient known endpoint coordinates"
            )
        else:
            reason = "relation could not be resolved from supplied evidence"
        unresolved.append(
            {
                "id": f"relation:{relation.id}",
                "reason": reason,
                "targets": missing,
                "required_for_modeling": True,
            }
        )

    unresolved_targets = {
        target
        for item in unresolved
        for target in item.get("targets", [])
        if isinstance(target, str)
    }
    for target in graph.required_targets:
        if target not in state.values and target not in unresolved_targets:
            unresolved.append(
                {
                    "id": f"target:{target}",
                    "reason": "required target has no evidence-backed unique solution",
                    "targets": [target],
                    "required_for_modeling": True,
                }
            )

    unresolved.extend(graph.unresolved_evidence)

    return ResolutionResult(
        values=state.values,
        traces=state.traces,
        derivations=state.derivations,
        unresolved=unresolved,
        conflicts=state.conflicts,
    )
