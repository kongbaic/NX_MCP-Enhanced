from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

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

    return (
        target.startswith("feature:")
        or target.startswith("overall_dimensions.")
        or target.startswith("profile.")
    )

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


def write_strict_evidence(capture: dict[str, Any]) -> Gate0Result:
    """Convert loose Reader capture into strict EvidenceGraph without inference."""

    if not isinstance(capture, dict):
        raise Gate0Error("reader capture root must be an object")

    schema_version, coordinate_system, overall = _validate_header(capture)

    observations = _normalize_existing_observations(capture)
    unresolved = _normalize_existing_unresolved(capture)
    original_unresolved_count = len(unresolved)

    seen_ids: set[str] = set()
    accepted: dict[str, list[BaseModel]] = {}
    passed: dict[str, int] = {}
    quarantined: dict[str, int] = {}

    for section, model in _LIST_SECTIONS:
        accepted_items: list[BaseModel] = []
        raw_items = _raw_list(
            capture,
            section,
            observations=observations,
            unresolved=unresolved,
        )
        q_before = len(unresolved)
        for index, record in enumerate(raw_items):
            parsed = _validate_record(
                section=section,
                index=index,
                record=record,
                model=model,
                seen_ids=seen_ids,
                observations=observations,
                unresolved=unresolved,
            )
            if parsed is not None:
                accepted_items.append(parsed)
        accepted[section] = accepted_items
        passed[section] = len(accepted_items)
        quarantined[section] = len(unresolved) - q_before

    required_targets = _normalize_required_targets(
        capture,
        observations=observations,
        unresolved=unresolved,
    )

    output = {
        "schema_version": schema_version,
        "coordinate_system": coordinate_system,
        "overall_dimensions": overall.model_dump(mode="json"),
        "views": [item.model_dump(mode="json") for item in accepted["views"]],
        "projections": [
            item.model_dump(mode="json") for item in accepted["projections"]
        ],
        "dimensions": [
            item.model_dump(mode="json") for item in accepted["dimensions"]
        ],
        "datum_alignments": [
            item.model_dump(mode="json") for item in accepted["datum_alignments"]
        ],
        "direct_values": [
            item.model_dump(mode="json") for item in accepted["direct_values"]
        ],
        "relations": [
            item.model_dump(mode="json") for item in accepted["relations"]
        ],
        "required_targets": required_targets,
        "observations": observations,
        "unresolved_evidence": unresolved,
    }

    try:
        strict = EvidenceGraph.model_validate(output)
    except ValidationError as exc:
        raise Gate0Error(
            "Gate 0 produced invalid strict evidence; this is an internal bug: "
            f"{exc}"
        ) from exc

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
