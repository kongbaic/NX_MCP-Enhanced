from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .compiler import EvidenceCompileError, compile_evidence_graph
from .draft import DraftAssemblyError, build_semantic_draft
from .evidence import (
    DatumAlignmentEvidence,
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    OverallDimensions,
    ProjectionEvidence,
    RelationEvidence,
    ViewEvidence,
)
from .resolver import resolve_evidence_graph


class Gate0Error(ValueError):
    """Reader capture cannot be converted safely into strict EvidenceGraph."""


@dataclass
class Gate0Result:
    evidence: EvidenceGraph
    report: dict[str, Any]


_ModelT = TypeVar("_ModelT", bound=BaseModel)

_LIST_SECTIONS: tuple[
    tuple[str, type[BaseModel]],
    ...,
] = (
    ("views", ViewEvidence),
    ("projections", ProjectionEvidence),
    ("dimensions", DimensionObservation),
    ("datum_alignments", DatumAlignmentEvidence),
    ("direct_values", DirectValueEvidence),
    ("relations", RelationEvidence),
)

_GLOBAL_ID_SECTIONS = {
    "views",
    "projections",
    "dimensions",
    "datum_alignments",
    "direct_values",
    "relations",
}


def _as_json_value(value: Any) -> Any:
    """Deep-copy JSON-like input without inventing semantics."""

    return copy.deepcopy(value)


def _source_ids(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return []
    raw = record.get("source_ids")
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(item for item in raw if isinstance(item, str) and item))


def _safe_target(record: Any) -> str | None:
    """Return a target only when the raw record exposes exactly one target string."""

    if not isinstance(record, dict):
        return None

    targets: set[str] = set()

    top = record.get("target")
    if isinstance(top, str) and top:
        targets.add(top)

    endpoints = record.get("endpoints")
    if isinstance(endpoints, list):
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                continue
            value = endpoint.get("target")
            if isinstance(value, str) and value:
                targets.add(value)

    relation_targets = record.get("targets")
    if isinstance(relation_targets, list):
        for value in relation_targets:
            if isinstance(value, str) and value:
                targets.add(value)

    if len(targets) == 1:
        return next(iter(targets))
    return None


def _required_for_modeling(record: Any) -> bool:
    if isinstance(record, dict):
        value = record.get("required_for_modeling", True)
        if isinstance(value, bool):
            return value
    return True


def _quarantine_id(section: str, index: int) -> str:
    return f"G0_{section.upper()}_{index:03d}"


def _validation_reason(section: str, exc: ValidationError) -> str:
    details: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        message = str(error.get("msg") or error.get("type") or "validation error")
        details.append(f"{location}: {message}" if location else message)
    joined = "; ".join(details)
    return f"{section} record is not strict-schema compliant: {joined}"


def _quarantine(
    *,
    section: str,
    index: int,
    record: Any,
    reason: str,
    observations: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> None:
    raw_path = f"$.{section}[{index}]"
    raw_record = _as_json_value(record)
    qid = _quarantine_id(section, index)

    observations.append(
        {
            "id": f"OBS_{qid}",
            "kind": "gate0_quarantine",
            "section": section,
            "raw_path": raw_path,
            "raw_record": raw_record,
            "reason": reason,
        }
    )

    item: dict[str, Any] = {
        "id": qid,
        "reason": reason,
        "required_for_modeling": _required_for_modeling(record),
        "evidence": _source_ids(record),
        "raw_path": raw_path,
        "raw_record": raw_record,
    }
    target = _safe_target(record)
    if target is not None:
        item["target"] = target
    unresolved.append(item)


def _extra_fields(record: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
    allowed = set(model.model_fields)
    return {
        key: _as_json_value(value)
        for key, value in record.items()
        if key not in allowed
    }


def _preserve_extra_fields(
    *,
    section: str,
    index: int,
    record: dict[str, Any],
    model: type[BaseModel],
    observations: list[dict[str, Any]],
) -> None:
    extras = _extra_fields(record, model)
    if not extras:
        return
    observations.append(
        {
            "id": f"OBS_G0_EXTRA_{section.upper()}_{index:03d}",
            "kind": "gate0_extra_fields",
            "section": section,
            "raw_path": f"$.{section}[{index}]",
            "extra_fields": extras,
        }
    )




def _direct_target_is_downstream_safe(target: str) -> bool:
    """Gate 0 target grammar accepted by the frozen draft/Gate A path.

    EvidenceGraph intentionally allows arbitrary non-empty targets, but the
    downstream semantic-draft contract does not. Gate 0 must therefore reject
    syntactically valid Reader targets that the frozen backend cannot consume,
    rather than letting them fail later or inventing a mapping.
    """

    if target.startswith("feature:"):
        rest = target[len("feature:") :]
        feature_id, dot, tail = rest.partition(".")
        return bool(feature_id and dot and tail)

    if target.startswith("overall_dimensions."):
        return bool(target[len("overall_dimensions.") :])

    if target.startswith("profile."):
        return bool(target[len("profile.") :])

    return False

def _validate_record(
    *,
    section: str,
    index: int,
    record: Any,
    model: type[_ModelT],
    seen_ids: set[str],
    observations: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> _ModelT | None:
    if not isinstance(record, dict):
        _quarantine(
            section=section,
            index=index,
            record=record,
            reason=f"{section} record must be an object",
            observations=observations,
            unresolved=unresolved,
        )
        return None

    try:
        parsed = model.model_validate(record)
    except ValidationError as exc:
        _quarantine(
            section=section,
            index=index,
            record=record,
            reason=_validation_reason(section, exc),
            observations=observations,
            unresolved=unresolved,
        )
        return None

    if section == "direct_values":
        target = getattr(parsed, "target", "")
        if not _direct_target_is_downstream_safe(str(target)):
            _quarantine(
                section=section,
                index=index,
                record=record,
                reason=(
                    "direct_values target is not consumable by the frozen "
                    f"semantic-draft contract: {target!r}"
                ),
                observations=observations,
                unresolved=unresolved,
            )
            return None

    record_id = getattr(parsed, "id", None)
    if section in _GLOBAL_ID_SECTIONS and isinstance(record_id, str):
        if record_id in seen_ids:
            _quarantine(
                section=section,
                index=index,
                record=record,
                reason=f"duplicate evidence id {record_id!r}",
                observations=observations,
                unresolved=unresolved,
            )
            return None
        seen_ids.add(record_id)

    _preserve_extra_fields(
        section=section,
        index=index,
        record=record,
        model=model,
        observations=observations,
    )
    return parsed


def _raw_list(
    capture: dict[str, Any],
    section: str,
    *,
    observations: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> list[Any]:
    raw = capture.get(section, [])
    if isinstance(raw, list):
        return raw

    _quarantine(
        section=section,
        index=0,
        record=raw,
        reason=f"top-level {section} must be a list",
        observations=observations,
        unresolved=unresolved,
    )
    return []


def _normalize_existing_observations(capture: dict[str, Any]) -> list[dict[str, Any]]:
    raw = capture.get("observations", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [
            {
                "id": "OBS_G0_RAW_OBSERVATIONS",
                "kind": "gate0_raw_observations",
                "raw_path": "$.observations",
                "raw_record": _as_json_value(raw),
            }
        ]

    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if isinstance(item, dict):
            result.append(_as_json_value(item))
        else:
            result.append(
                {
                    "id": f"OBS_G0_RAW_OBSERVATION_{index:03d}",
                    "kind": "gate0_raw_observation",
                    "raw_path": f"$.observations[{index}]",
                    "raw_record": _as_json_value(item),
                }
            )
    return result


def _normalize_existing_unresolved(capture: dict[str, Any]) -> list[dict[str, Any]]:
    raw = capture.get("unresolved_evidence", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [
            {
                "id": "G0_UNRESOLVED_SECTION_000",
                "reason": "top-level unresolved_evidence must be a list",
                "required_for_modeling": True,
                "evidence": [],
                "raw_path": "$.unresolved_evidence",
                "raw_record": _as_json_value(raw),
            }
        ]

    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if isinstance(item, dict):
            result.append(_as_json_value(item))
        else:
            result.append(
                {
                    "id": f"G0_UNRESOLVED_RAW_{index:03d}",
                    "reason": "unresolved_evidence entry must be an object",
                    "required_for_modeling": True,
                    "evidence": [],
                    "raw_path": f"$.unresolved_evidence[{index}]",
                    "raw_record": _as_json_value(item),
                }
            )
    return result


def _normalize_required_targets(
    capture: dict[str, Any],
    *,
    observations: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> list[str]:
    raw = capture.get("required_targets", [])
    if not isinstance(raw, list):
        _quarantine(
            section="required_targets",
            index=0,
            record=raw,
            reason="top-level required_targets must be a list",
            observations=observations,
            unresolved=unresolved,
        )
        return []

    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if isinstance(item, str) and item:
            if item not in seen:
                seen.add(item)
                result.append(item)
            continue
        _quarantine(
            section="required_targets",
            index=index,
            record=item,
            reason="required target must be a non-empty string",
            observations=observations,
            unresolved=unresolved,
        )
    return result


def _validate_header(capture: dict[str, Any]) -> tuple[str, str, OverallDimensions]:
    schema_version = capture.get("schema_version", "1.0")
    if schema_version != "1.0":
        raise Gate0Error(f"unsupported schema_version {schema_version!r}")

    coordinate_system = capture.get(
        "coordinate_system",
        "part_center_xy_bottom_z0",
    )
    if coordinate_system != "part_center_xy_bottom_z0":
        raise Gate0Error(f"unsupported coordinate_system {coordinate_system!r}")

    try:
        overall = OverallDimensions.model_validate(capture.get("overall_dimensions"))
    except ValidationError as exc:
        raise Gate0Error(f"overall_dimensions invalid: {exc}") from exc

    return schema_version, coordinate_system, overall




def _target_path(target: str) -> tuple[str, tuple[str, ...]]:
    if target.startswith("feature:"):
        rest = target[len("feature:") :]
        feature_id, dot, tail = rest.partition(".")
        if not feature_id or not dot or not tail:
            return target, ()
        return f"feature:{feature_id}", tuple(tail.split("."))
    return "<root>", tuple(target.split("."))


def _strict_prefix(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return len(left) < len(right) and right[: len(left)] == left


def _materialized_target_conflicts(graph: EvidenceGraph) -> set[str]:
    """Find target paths that cannot coexist in the frozen draft object tree."""

    compiled = compile_evidence_graph(graph)
    resolution = resolve_evidence_graph(compiled)

    targets = {
        item.target
        for item in compiled.direct_values
        if isinstance(item.target, str) and item.target
    }
    targets.update(
        target
        for target in resolution.values
        if isinstance(target, str) and target
    )

    by_root: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for target in sorted(targets):
        root, parts = _target_path(target)
        by_root.setdefault(root, []).append((target, parts))

    conflicting: set[str] = set()
    for entries in by_root.values():
        for index, (left_target, left_parts) in enumerate(entries):
            for right_target, right_parts in entries[index + 1 :]:
                if _strict_prefix(left_parts, right_parts) or _strict_prefix(
                    right_parts,
                    left_parts,
                ):
                    conflicting.add(left_target)
                    conflicting.add(right_target)
    return conflicting


def _strict_graph_from_accepted(
    *,
    schema_version: str,
    coordinate_system: str,
    overall: OverallDimensions,
    accepted: dict[str, list[BaseModel]],
    required_targets: list[str],
    observations: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> EvidenceGraph:
    strict = _strict_graph_from_accepted(
        schema_version=schema_version,
        coordinate_system=coordinate_system,
        overall=overall,
        accepted=accepted,
        required_targets=required_targets,
        observations=observations,
        unresolved=unresolved,
    )

    removed_path_conflicts = _quarantine_direct_path_conflicts(
        capture=capture,
        accepted=accepted,
        accepted_indices=accepted_indices,
        graph=strict,
        observations=observations,
        unresolved=unresolved,
    )
    if removed_path_conflicts:
        passed["direct_values"] -= removed_path_conflicts
        quarantined["direct_values"] += removed_path_conflicts
        strict = _strict_graph_from_accepted(
            schema_version=schema_version,
            coordinate_system=coordinate_system,
            overall=overall,
            accepted=accepted,
            required_targets=required_targets,
            observations=observations,
            unresolved=unresolved,
        )

        # Removing every Reader direct record that participates in the current
        # prefix conflict is deterministic and fail-closed. Re-check once to
        # ensure no compiler/resolver-only path conflict remains.
        remaining_conflicts = _materialized_target_conflicts(strict)
        if remaining_conflicts:
            raise Gate0Error(
                "downstream target-path conflict remains after quarantining "
                f"Reader direct_values: {sorted(remaining_conflicts)}"
            )

    _assert_downstream_consumable(strict)

    added_unresolved = len(unresolved) - original_unresolved_count
    blocking_added = sum(
        1
        for item in unresolved[original_unresolved_count:]
        if item.get("required_for_modeling", True)
    )

    report = {
        "schema_valid": True,
        "passed_views": passed["views"],
        "quarantined_views": quarantined["views"],
        "passed_projections": passed["projections"],
        "quarantined_projections": quarantined["projections"],
        "passed_dimensions": passed["dimensions"],
        "quarantined_dimensions": quarantined["dimensions"],
        "passed_datum_alignments": passed["datum_alignments"],
        "quarantined_datum_alignments": quarantined["datum_alignments"],
        "passed_direct_values": passed["direct_values"],
        "quarantined_direct_values": quarantined["direct_values"],
        "passed_relations": passed["relations"],
        "quarantined_relations": quarantined["relations"],
        "added_unresolved": added_unresolved,
        "added_blocking_unresolved": blocking_added,
        "total_unresolved": len(unresolved),
    }
    return Gate0Result(evidence=strict, report=report)
