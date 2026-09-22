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


def _conflict_signature(item: dict[str, Any]) -> dict[str, Any]:
    if "target" in item:
        return _canon(
            {
                "target": item.get("target"),
                "existing": item.get("existing"),
                "candidate": item.get("candidate"),
            }
        )
    return _canon(
        {
            "kind": item.get("kind"),
            "targets": item.get("targets"),
            "expected_distance": item.get("expected_distance"),
            "actual_distance": item.get("actual_distance"),
        }
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




def _endpoint_signature(endpoint: Any) -> Any:
    if not isinstance(endpoint, dict):
        return _canon(endpoint)
    return _canon(
        {
            "role": endpoint.get("role"),
            "target": endpoint.get("target"),
        }
    )


def _quarantine_raw_signature(raw_record: Any) -> Any:
    """Normalize Gate 0 raw records while ignoring IDs, sources and prose."""

    if not isinstance(raw_record, dict):
        return _canon(raw_record)

    signature: dict[str, Any] = {}

    for key in (
        "value",
        "axis",
        "direction",
        "kind",
        "type",
        "target",
        "feature_id",
        "from_side",
        "diameter_target",
        "required_for_modeling",
    ):
        if key in raw_record:
            signature[key] = _canon(raw_record.get(key))

    endpoints = raw_record.get("endpoints")
    if isinstance(endpoints, list):
        signature["endpoints"] = [
            _endpoint_signature(endpoint)
            for endpoint in endpoints
        ]
    elif "endpoints" in raw_record:
        signature["endpoints"] = _canon(endpoints)
    else:
        signature["endpoints"] = "<missing>"

    targets = raw_record.get("targets")
    if isinstance(targets, list):
        signature["targets"] = sorted(
            (_canon(value) for value in targets),
            key=lambda value: json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
            ),
        )
    elif "targets" in raw_record:
        signature["targets"] = _canon(targets)

    members = raw_record.get("members")
    if isinstance(members, list):
        signature["members"] = sorted(_canon(value) for value in members)
    elif "members" in raw_record:
        signature["members"] = _canon(members)

    return _canon(signature)


def _gate0_quarantine_signatures(graph: EvidenceGraph) -> list[dict[str, Any]]:
    """Return semantic signatures for Gate 0 quarantines.

    Gate 0 intentionally preserves raw invalid Reader records inside
    unresolved_evidence. Stability comparison must not ignore those records
    merely because endpoint ownership was too incomplete to expose a safe
    target. At the same time, evidence IDs, source IDs, prose and raw array
    positions are intentionally excluded.
    """

    signatures: list[dict[str, Any]] = []
    for item in graph.unresolved_evidence:
        raw_record = item.get("raw_record")
        raw_path = item.get("raw_path")
        item_id = item.get("id")

        is_gate0 = (
            isinstance(item_id, str)
            and item_id.startswith("G0_")
        ) or (
            isinstance(raw_path, str)
            and raw_path.startswith("$.")
            and raw_record is not None
        )
        if not is_gate0:
            continue

        section = None
        if isinstance(raw_path, str) and raw_path.startswith("$."):
            section = raw_path[2:].split("[", 1)[0]

        signatures.append(
            {
                "section": section,
                "target": item.get("target"),
                "required_for_modeling": item.get(
                    "required_for_modeling",
                    True,
                ),
                "raw": _quarantine_raw_signature(raw_record),
            }
        )

    return sorted(
        (_canon(item) for item in signatures),
        key=lambda item: json.dumps(
            item,
            sort_keys=True,
            ensure_ascii=False,
        ),
    )

def _reader_unresolved_signatures(graph: EvidenceGraph) -> list[dict[str, Any]]:
    """Normalize Reader/linker unresolved semantics without prose or local IDs."""

    signatures: list[dict[str, Any]] = []
    for item in graph.unresolved_evidence:
        item_id = item.get("id")
        raw_path = item.get("raw_path")
        raw_record = item.get("raw_record")
        is_gate0 = (
            isinstance(item_id, str)
            and item_id.startswith("G0_")
        ) or (
            isinstance(raw_path, str)
            and raw_path.startswith("$.")
            and raw_record is not None
        )
        if is_gate0:
            continue

        feature_ids = item.get("feature_ids")
        if isinstance(feature_ids, list):
            normalized_feature_ids = sorted(
                value
                for value in feature_ids
                if isinstance(value, str) and value
            )
        else:
            normalized_feature_ids = []

        signature = {
            "kind": item.get("kind") or "unstructured",
            "feature_ids": normalized_feature_ids,
            "dimension_value": _canon(item.get("dimension_value")),
            "field": item.get("field"),
            "axis": item.get("axis"),
            "target": item.get("target"),
            "targets": sorted(item.get("targets") or []),
            "candidates": _canon(item.get("candidates")),
            "required_for_modeling": item.get(
                "required_for_modeling",
                True,
            ),
        }
        signatures.append(_canon(signature))

    return sorted(
        signatures,
        key=lambda item: json.dumps(
            item,
            sort_keys=True,
            ensure_ascii=False,
        ),
    )


def _unresolved_semantic_drift(
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counters: list[dict[str, int]] = []
    signature_by_key: dict[str, dict[str, Any]] = {}

    for snapshot in snapshots:
        counter: dict[str, int] = {}
        for signature in snapshot["unresolved_semantics"]:
            key = json.dumps(
                _canon(signature),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            signature_by_key[key] = signature
            counter[key] = counter.get(key, 0) + 1
        counters.append(counter)

    drift: list[dict[str, Any]] = []
    for key in sorted(signature_by_key):
        counts = [counter.get(key, 0) for counter in counters]
        if len(set(counts)) > 1:
            drift.append(
                {
                    "signature": signature_by_key[key],
                    "counts": counts,
                }
            )
    return drift


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
        [_conflict_signature(item) for item in resolution.conflicts],
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
        "unresolved_semantics": _reader_unresolved_signatures(graph),
        "gate0_quarantines": _gate0_quarantine_signatures(graph),
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
    unresolved_semantic_drift: list[dict[str, Any]]
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
            "unresolved_semantic_drift": self.unresolved_semantic_drift,
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

    unresolved_semantic_drift = _unresolved_semantic_drift(snapshots)

    stable = len(set(fingerprints)) == 1
    return StabilityReport(
        stable=stable,
        run_count=len(graphs),
        unique_fingerprints=len(set(fingerprints)),
        fingerprints=fingerprints,
        changed_sections=changed_sections,
        value_drift=value_drift,
        unresolved_presence=unresolved_presence,
        unresolved_semantic_drift=unresolved_semantic_drift,
        snapshots=snapshots,
    )
