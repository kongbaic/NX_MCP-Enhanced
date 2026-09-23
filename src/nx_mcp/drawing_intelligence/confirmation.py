from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .evidence import DimensionEndpoint, DimensionObservation, EvidenceGraph


class ConfirmationError(ValueError):
    """Human confirmation payload is invalid for the current evidence graph."""


class ConfirmationAnswer(BaseModel):
    confirmation_id: str = Field(min_length=1)
    selected_option_ids: list[str] = Field(default_factory=list)

    @field_validator("selected_option_ids")
    @classmethod
    def _unique_options(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("selected_option_ids must be unique")
        return value


class ConfirmationAnswers(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    answers: list[ConfirmationAnswer] = Field(default_factory=list)

    @field_validator("answers")
    @classmethod
    def _unique_confirmation_ids(
        cls, value: list[ConfirmationAnswer]
    ) -> list[ConfirmationAnswer]:
        ids = [item.confirmation_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("confirmation_id values must be unique")
        return value


def _known_feature_targets(graph: EvidenceGraph, axis: str) -> list[str]:
    suffix = axis.lower()
    feature_ids = sorted({item.feature_id for item in graph.projections})
    return [
        f"feature:{feature_id}.centerline.{suffix}"
        for feature_id in feature_ids
    ]


def _option(
    option_id: str,
    *,
    role: str,
    label_zh: str,
    target: str | None = None,
    evidence_candidate: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "option_id": option_id,
        "role": role,
        "label_zh": label_zh,
        "evidence_candidate": evidence_candidate,
    }
    if target is not None:
        item["target"] = target
    return item


def _unresolved_options(
    graph: EvidenceGraph,
    *,
    endpoint_index: int,
    axis: str,
    endpoint_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    options = [
        _option(
            f"E{endpoint_index}_OVERALL_MIN",
            role="overall_min",
            label_zh="整体最小边界",
        ),
        _option(
            f"E{endpoint_index}_OVERALL_MAX",
            role="overall_max",
            label_zh="整体最大边界",
        ),
    ]

    evidence_candidates = {
        item
        for item in endpoint_spec.get("candidate_targets", [])
        if isinstance(item, str) and item
    }
    for number, target in enumerate(_known_feature_targets(graph, axis), start=1):
        feature_id = target[len("feature:") :].partition(".")[0]
        options.append(
            _option(
                f"E{endpoint_index}_FEATURE_{number:03d}",
                role="feature_center",
                target=target,
                label_zh=f"特征 {feature_id} 中心",
                evidence_candidate=target in evidence_candidates,
            )
        )

    options.append(
        _option(
            f"E{endpoint_index}_KEEP_UNRESOLVED",
            role="keep_unresolved",
            label_zh="以上都不是，保持未解决",
        )
    )
    return options


def build_confirmation_request(graph: EvidenceGraph) -> dict[str, Any]:
    """Build bounded user questions from dimension endpoint unresolved evidence."""

    questions: list[dict[str, Any]] = []
    for item in sorted(
        graph.unresolved_evidence,
        key=lambda entry: str(entry.get("id") or ""),
    ):
        if item.get("kind") != "dimension_endpoint":
            continue
        endpoint_specs = item.get("endpoint_specs")
        if not isinstance(endpoint_specs, list) or len(endpoint_specs) != 2:
            continue
        dimension_id = item.get("capture_dimension_id")
        value = item.get("dimension_value")
        axis = item.get("axis")
        if not isinstance(dimension_id, str) or not dimension_id:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if axis not in {"X", "Y", "Z"}:
            continue

        endpoints: list[dict[str, Any]] = []
        unresolved_count = 0
        for index, spec in enumerate(endpoint_specs):
            if not isinstance(spec, dict):
                break
            role = spec.get("role")
            record: dict[str, Any] = {
                "index": index,
                "current_role": role,
                "unresolved_kind": spec.get("unresolved_kind"),
                "source_ids": [
                    source
                    for source in spec.get("source_ids", [])
                    if isinstance(source, str) and source
                ],
            }
            if role == "unresolved":
                unresolved_count += 1
                record["requires_confirmation"] = True
                record["options"] = _unresolved_options(
                    graph,
                    endpoint_index=index,
                    axis=axis,
                    endpoint_spec=spec,
                )
            elif role in {"overall_min", "overall_max"}:
                record["requires_confirmation"] = False
                record["fixed"] = {"role": role}
            elif role == "feature_center" and isinstance(spec.get("target"), str):
                record["requires_confirmation"] = False
                record["fixed"] = {
                    "role": "feature_center",
                    "target": spec["target"],
                }
            else:
                break
            endpoints.append(record)
        else:
            if unresolved_count:
                questions.append(
                    {
                        "confirmation_id": f"CONF_{item['id']}",
                        "unresolved_id": item["id"],
                        "kind": "dimension_endpoint_ownership",
                        "dimension_id": dimension_id,
                        "dimension_value": float(value),
                        "axis": axis,
                        "prompt_zh": (
                            f"尺寸 {value:g}（{axis}轴）的端点归属需要确认"
                        ),
                        "endpoints": endpoints,
                        "source_ids": [
                            source
                            for source in item.get("source_ids", [])
                            if isinstance(source, str) and source
                        ],
                    }
                )

    return {
        "schema_version": "1.0",
        "question_count": len(questions),
        "questions": questions,
    }


def _selected_by_endpoint(
    question: dict[str, Any],
    answer: ConfirmationAnswer,
) -> dict[int, dict[str, Any]]:
    option_lookup: dict[str, tuple[int, dict[str, Any]]] = {}
    required_indexes: set[int] = set()

    for endpoint in question["endpoints"]:
        index = int(endpoint["index"])
        if not endpoint.get("requires_confirmation"):
            continue
        required_indexes.add(index)
        for option in endpoint.get("options", []):
            option_lookup[str(option["option_id"])] = (index, option)

    selected: dict[int, dict[str, Any]] = {}
    for option_id in answer.selected_option_ids:
        entry = option_lookup.get(option_id)
        if entry is None:
            raise ConfirmationError(
                f"{answer.confirmation_id}: option {option_id!r} is not allowed"
            )
        index, option = entry
        if index in selected:
            raise ConfirmationError(
                f"{answer.confirmation_id}: endpoint {index} has multiple selections"
            )
        selected[index] = option

    missing = sorted(required_indexes - set(selected))
    if missing:
        raise ConfirmationError(
            f"{answer.confirmation_id}: missing selections for endpoints {missing}"
        )
    return selected


def apply_confirmation_answers(
    graph: EvidenceGraph,
    answers: ConfirmationAnswers | dict[str, Any],
) -> EvidenceGraph:
    """Apply only validated endpoint ownership choices to a copy of EvidenceGraph."""

    if not isinstance(answers, ConfirmationAnswers):
        answers = ConfirmationAnswers.model_validate(answers)

    request = build_confirmation_request(graph)
    questions = {
        item["confirmation_id"]: item
        for item in request["questions"]
    }
    answer_map = {
        item.confirmation_id: item
        for item in answers.answers
    }

    unknown = sorted(set(answer_map) - set(questions))
    if unknown:
        raise ConfirmationError(f"unknown confirmation ids: {unknown}")

    dimensions = [item.model_copy(deep=True) for item in graph.dimensions]
    unresolved = copy.deepcopy(graph.unresolved_evidence)
    required_targets = set(graph.required_targets)
    observations = copy.deepcopy(graph.observations)
    applied: list[str] = []

    unresolved_by_id = {
        str(item.get("id")): item
        for item in unresolved
        if item.get("id") is not None
    }

    for confirmation_id, answer in answer_map.items():
        question = questions[confirmation_id]
        selected = _selected_by_endpoint(question, answer)

        if any(
            option.get("role") == "keep_unresolved"
            for option in selected.values()
        ):
            continue

        unresolved_id = str(question["unresolved_id"])
        source = unresolved_by_id.get(unresolved_id)
        if source is None:
            raise ConfirmationError(
                f"{confirmation_id}: source unresolved record is missing"
            )

        endpoints: list[DimensionEndpoint] = []
        for endpoint in question["endpoints"]:
            index = int(endpoint["index"])
            if endpoint.get("requires_confirmation"):
                option = selected[index]
                role = option["role"]
                target = option.get("target")
            else:
                fixed = endpoint["fixed"]
                role = fixed["role"]
                target = fixed.get("target")

            if role == "feature_center":
                if not isinstance(target, str) or not target:
                    raise ConfirmationError(
                        f"{confirmation_id}: feature_center target missing"
                    )
                endpoints.append(
                    DimensionEndpoint(role="feature_center", target=target)
                )
                required_targets.add(target)
            elif role in {"overall_min", "overall_max"}:
                endpoints.append(DimensionEndpoint(role=role))
            else:
                raise ConfirmationError(
                    f"{confirmation_id}: unsupported selected role {role!r}"
                )

        dimension_id = str(question["dimension_id"])
        if any(item.id == dimension_id for item in dimensions):
            raise ConfirmationError(
                f"{confirmation_id}: dimension {dimension_id!r} already exists"
            )

        dimensions.append(
            DimensionObservation(
                id=dimension_id,
                value=float(question["dimension_value"]),
                axis=question["axis"],
                endpoints=endpoints,
                direction=source.get("dimension_direction"),
                source_ids=[
                    item
                    for item in source.get("source_ids", [])
                    if isinstance(item, str) and item
                ],
                required_for_modeling=bool(
                    source.get("required_for_modeling", True)
                ),
            )
        )
        unresolved = [
            item
            for item in unresolved
            if str(item.get("id")) != unresolved_id
        ]
        unresolved_by_id.pop(unresolved_id, None)
        applied.append(confirmation_id)

    if applied:
        observations.append(
            {
                "kind": "human_confirmation_v1",
                "confirmation_ids": sorted(applied),
            }
        )

    dimensions.sort(key=lambda item: item.id)
    return graph.model_copy(
        deep=True,
        update={
            "dimensions": dimensions,
            "unresolved_evidence": unresolved,
            "required_targets": sorted(required_targets),
            "observations": observations,
        },
    )
