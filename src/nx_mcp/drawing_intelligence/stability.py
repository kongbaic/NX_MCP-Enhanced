from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .compiler import compile_evidence_graph
from .draft import build_semantic_draft
from .evidence import EvidenceGraph, RelationEvidence
from .resolver import resolve_evidence_graph


def _canon(value: Any) -> Any:
    if isinstance(value, float):
        if value == 0:
            return 0.0
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _canon(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canon(item) for item in value]
    return value


def _relation_signature(relation: RelationEvidence) -> dict[str, Any]:
    targets = list(relation.targets)
    direction = relation.direction

    if relation.kind in {"center_spacing", "center_distance"} and len(targets) == 2:
        if targets[1] < targets[0]:
            targets.reverse()
            if direction is not None:
                direction = -direction
    elif relation.kind == "alignment":
        targets = sorted(targets)

    return _canon(
        {
            "kind": relation.kind,
            "axis": relation.axis,
            "targets": targets,
            "value": relation.value,
            "from_side": relation.from_side,
            "direction": direction,
            "diameter_target": relation.diameter_target,
            "required_for_modeling": relation.required_for_modeling,
        }
    )


def _projection_signatures(graph: EvidenceGraph) -> list[dict[str, Any]]:
    view_kind = {view.id: view.kind for view in graph.views}
    result: list[dict[str, Any]] = []
    for projection in graph.projections:
        result.append(
            {
                "feature_id": projection.feature_id,
                "view_kind": view_kind.get(projection.view_id, "<missing>"),
                "shape": projection.shape,
                "required_for_modeling": projection.required_for_modeling,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["feature_id"],
            item["view_kind"],
            item["shape"],
            item["required_for_modeling"],
        ),
    )


def _datum_signatures(graph: EvidenceGraph) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "target": item.target,
                "axis": item.axis,
                "datum": item.datum,
                "required_for_modeling": item.required_for_modeling,
            }
            for item in graph.datum_alignments
        ],
        key=lambda item: (
            item["target"],
            item["axis"],
            item["datum"],
            item["required_for_modeling"],
        ),
    )


def _unresolved_targets(items: list[dict[str, Any]]) -> list[str]:
    targets: set[str] = set()
    for item in items:
        target = item.get("target")
        if isinstance(target, str) and target:
            targets.add(target)
        raw_targets = item.get("targets")
        if isinstance(raw_targets, list):
            for value in raw_targets:
                if isinstance(value, str) and value:
                    targets.add(value)
    return sorted(targets)


def logical_snapshot(graph: EvidenceGraph) -> dict[str, Any]:
    """Return an ID/order-insensitive snapshot of Reader semantics."""

    compiled = compile_evidence_graph(graph)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)

    direct_values = {
        item.target: _canon(item.value)
        for item in sorted(compiled.direct_values, key=lambda item: item.target)
    }

    relations = sorted(
        [_relation_signature(item) for item in compiled.relations],
        key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
    )

    resolved_values = {
        key: _canon(value)
        for key, value in sorted(resolution.values.items())
    }

    conflicts = sorted(
        [_canon(item) for item in resolution.conflicts],
        key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
    )

    return {
        "overall_dimensions": _canon(graph.overall_dimensions.model_dump()),
        "coordinate_system": graph.coordinate_system,
        "projections": _projection_signatures(graph),
        "datum_alignments": _datum_signatures(graph),
        "direct_values": direct_values,
        "relations": relations,
        "required_targets": sorted(graph.required_targets),
        "resolved_values": resolved_values,
        "unresolved_targets": _unresolved_targets(resolution.unresolved),
        "conflicts": conflicts,
        "resolution_ok": resolution.ok,
        "dimension_closure": draft["dimension_closure"]["status"],
    }


def snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        _canon(snapshot),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _section_diff(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    keys = sorted(set(baseline) | set(candidate))
    return [key for key in keys if _canon(baseline.get(key)) != _canon(candidate.get(key))]


@dataclass
class StabilityReport:
    stable: bool
    run_count: int
    unique_fingerprints: int
    fingerprints: list[str]
    changed_sections: dict[int, list[str]]
    value_drift: dict[str, list[Any]]
    unresolved_presence: dict[str, list[int]]
    snapshots: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable": self.stable,
            "run_count": self.run_count,
            "unique_fingerprints": self.unique_fingerprints,
            "fingerprints": self.fingerprints,
            "changed_sections": {
                str(index): sections
                for index, sections in sorted(self.changed_sections.items())
            },
            "value_drift": self.value_drift,
            "unresolved_presence": self.unresolved_presence,
            "snapshots": self.snapshots,
        }


def compare_evidence_runs(graphs: list[EvidenceGraph]) -> StabilityReport:
    if len(graphs) < 2:
        raise ValueError("stability comparison requires at least two evidence runs")

    snapshots = [logical_snapshot(graph) for graph in graphs]
    fingerprints = [snapshot_fingerprint(snapshot) for snapshot in snapshots]
    baseline = snapshots[0]

    changed_sections = {
        index + 2: _section_diff(baseline, snapshot)
        for index, snapshot in enumerate(snapshots[1:])
        if _section_diff(baseline, snapshot)
    }

    all_targets = sorted(
        {
            target
            for snapshot in snapshots
            for target in (
                set(snapshot["direct_values"])
                | set(snapshot["resolved_values"])
            )
        }
    )
    value_drift: dict[str, list[Any]] = {}
    for target in all_targets:
        values = []
        for snapshot in snapshots:
            if target in snapshot["resolved_values"]:
                value = snapshot["resolved_values"][target]
            elif target in snapshot["direct_values"]:
                value = snapshot["direct_values"][target]
            else:
                value = "<missing>"
            values.append(value)
        unique = {
            json.dumps(_canon(value), sort_keys=True, ensure_ascii=False)
            for value in values
        }
        if len(unique) > 1:
            value_drift[target] = values

    unresolved_targets = sorted(
        {
            target
            for snapshot in snapshots
            for target in snapshot["unresolved_targets"]
        }
    )
    unresolved_presence = {
        target: [
            index + 1
            for index, snapshot in enumerate(snapshots)
            if target in snapshot["unresolved_targets"]
        ]
        for target in unresolved_targets
    }
    unresolved_presence = {
        target: runs
        for target, runs in unresolved_presence.items()
        if len(runs) != len(snapshots)
    }

    stable = len(set(fingerprints)) == 1
    return StabilityReport(
        stable=stable,
        run_count=len(graphs),
        unique_fingerprints=len(set(fingerprints)),
        fingerprints=fingerprints,
        changed_sections=changed_sections,
        value_drift=value_drift,
        unresolved_presence=unresolved_presence,
        snapshots=snapshots,
    )
