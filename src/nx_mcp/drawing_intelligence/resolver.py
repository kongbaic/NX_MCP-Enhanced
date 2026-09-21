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
            "unresolved": self.unresolved,
            "conflicts": self.conflicts,
            "ok": self.ok,
        }


class _State:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}
        self.traces: dict[str, list[str]] = {}
        self.conflicts: list[dict[str, Any]] = []

    def assign(self, target: str, value: float, trace: list[str]) -> bool:
        if target not in self.values:
            self.values[target] = float(value)
            self.traces[target] = list(trace)
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


def _bounds(graph: EvidenceGraph, axis: str) -> tuple[float, float]:
    dims = graph.overall_dimensions
    if axis == "X":
        return (-dims.length_x / 2.0, dims.length_x / 2.0)
    if axis == "Y":
        return (-dims.width_y / 2.0, dims.width_y / 2.0)
    return (0.0, dims.height_z)


def _relation_trace(relation: RelationEvidence) -> list[str]:
    return [relation.id, *relation.source_ids]


def _apply_edge_offset(graph: EvidenceGraph, relation: RelationEvidence, state: _State) -> bool:
    lo, hi = _bounds(graph, relation.axis)
    assert relation.value is not None
    assert relation.from_side is not None
    value = lo + relation.value if relation.from_side == "min" else hi - relation.value
    changed = False
    for target in relation.targets:
        changed = state.assign(target, value, _relation_trace(relation)) or changed
    return changed


def _apply_alignment(relation: RelationEvidence, state: _State) -> bool:
    known = [(target, state.values[target]) for target in relation.targets if target in state.values]
    if not known:
        return False
    reference = known[0][1]
    if any(not isclose(value, reference, abs_tol=_EPS, rel_tol=0.0) for _, value in known[1:]):
        for target, value in known[1:]:
            state.assign(target, reference, _relation_trace(relation))
        return False
    changed = False
    for target in relation.targets:
        changed = state.assign(target, reference, _relation_trace(relation)) or changed
    return changed


def _apply_spacing(relation: RelationEvidence, state: _State) -> bool:
    first, second = relation.targets
    assert relation.value is not None
    first_known = first in state.values
    second_known = second in state.values

    if first_known and second_known:
        actual = abs(state.values[second] - state.values[first])
        if not isclose(actual, abs(relation.value), abs_tol=_EPS, rel_tol=0.0):
            state.conflicts.append(
                {
                    "relation": relation.id,
                    "kind": relation.kind,
                    "expected_distance": abs(relation.value),
                    "actual_distance": actual,
                    "targets": relation.targets,
                }
            )
        return False

    # An unsigned center distance has two mathematical solutions. Do not guess.
    if relation.direction is None:
        return False

    delta = relation.direction * abs(relation.value)
    if first_known:
        return state.assign(second, state.values[first] + delta, _relation_trace(relation))
    if second_known:
        return state.assign(first, state.values[second] - delta, _relation_trace(relation))
    return False


def _apply_tangent(relation: RelationEvidence, state: _State) -> bool:
    center_target, tangent_target = relation.targets
    if center_target not in state.values:
        return False
    assert relation.diameter is not None
    sign = 1.0 if relation.kind == "upper_tangent" else -1.0
    tangent = state.values[center_target] + sign * relation.diameter / 2.0
    return state.assign(tangent_target, tangent, _relation_trace(relation))


def _apply_relation(graph: EvidenceGraph, relation: RelationEvidence, state: _State) -> bool:
    if relation.kind == "edge_offset":
        return _apply_edge_offset(graph, relation, state)
    if relation.kind == "alignment":
        return _apply_alignment(relation, state)
    if relation.kind in {"center_spacing", "center_distance"}:
        return _apply_spacing(relation, state)
    if relation.kind in {"upper_tangent", "lower_tangent"}:
        return _apply_tangent(relation, state)
    return False


def resolve_evidence_graph(graph: EvidenceGraph) -> ResolutionResult:
    """Resolve evidence with deterministic arithmetic only.

    The function never reads an image, never invents relations, and never
    chooses between multiple geometric solutions. Ambiguity remains unresolved.
    """

    state = _State()

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
        if relation.kind in {"center_spacing", "center_distance"}:
            if any(target not in state.values for target in relation.targets):
                unresolved.append(
                    {
                        "id": f"relation:{relation.id}",
                        "reason": (
                            "center distance has no unique signed solution"
                            if relation.direction is None
                            else "insufficient known endpoint coordinates"
                        ),
                        "targets": relation.targets,
                        "required_for_modeling": True,
                    }
                )
        elif any(target not in state.values for target in relation.targets):
            unresolved.append(
                {
                    "id": f"relation:{relation.id}",
                    "reason": "relation could not be resolved from supplied evidence",
                    "targets": relation.targets,
                    "required_for_modeling": True,
                }
            )

    unresolved_targets = {item_target for item in unresolved for item_target in item["targets"]}
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
        unresolved=unresolved,
        conflicts=state.conflicts,
    )
