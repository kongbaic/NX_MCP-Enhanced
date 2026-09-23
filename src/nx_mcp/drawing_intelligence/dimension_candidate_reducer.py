from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Orientation = Literal["horizontal", "vertical"]
Band = Literal["top", "middle", "bottom", "left", "right"]


class DimensionCandidateQuery(BaseModel):
    region_id: str = Field(min_length=1)
    orientation: Orientation
    band: Band
    max_candidates: int = Field(default=4, ge=1, le=4)

    @field_validator("band")
    @classmethod
    def _band_matches_orientation(cls, value: str, info):
        orientation = info.data.get("orientation")
        if orientation == "horizontal" and value not in {"top", "middle", "bottom"}:
            raise ValueError("horizontal queries require top/middle/bottom band")
        if orientation == "vertical" and value not in {"left", "middle", "right"}:
            raise ValueError("vertical queries require left/middle/right band")
        return value


def classify_candidate_band(candidate: dict[str, Any]) -> Band:
    orientation = candidate.get("orientation")
    axis_local = candidate.get("axis_local_norm")
    if orientation not in {"horizontal", "vertical"}:
        raise ValueError("candidate orientation must be horizontal or vertical")
    if not isinstance(axis_local, (int, float)):
        raise ValueError("candidate axis_local_norm must be numeric")

    value = float(axis_local)
    if orientation == "horizontal":
        if value < 0.25:
            return "top"
        if value > 0.72:
            return "bottom"
        return "middle"

    if value <= 0.40:
        return "left"
    if value > 0.75:
        return "right"
    return "middle"


def _dedupe_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    witnesses = candidate.get("witness_positions_px", [])
    rounded_witnesses = tuple(
        round(float(value) / 3.0) * 3
        for value in witnesses
        if isinstance(value, (int, float))
    )
    return (
        candidate.get("region_id"),
        candidate.get("orientation"),
        classify_candidate_band(candidate),
        rounded_witnesses,
    )


def reduce_dimension_candidates(
    raw_evidence: dict[str, Any],
    query: DimensionCandidateQuery | dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(query, DimensionCandidateQuery):
        query = DimensionCandidateQuery.model_validate(query)

    raw_candidates = raw_evidence.get("dimension_geometry_candidates", [])
    if not isinstance(raw_candidates, list):
        raise ValueError("dimension_geometry_candidates must be a list")

    filtered: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for candidate in raw_candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("region_id") != query.region_id:
            continue
        if candidate.get("orientation") != query.orientation:
            continue
        if classify_candidate_band(candidate) != query.band:
            continue

        key = _dedupe_key(candidate)
        if key in seen:
            continue
        seen.add(key)

        filtered.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "region_id": candidate.get("region_id"),
                "orientation": candidate.get("orientation"),
                "band": query.band,
                "axis_px": candidate.get("axis_px"),
                "axis_local_norm": candidate.get("axis_local_norm"),
                "line_span_px": candidate.get("line_span_px"),
                "witness_positions_px": candidate.get("witness_positions_px", []),
                "witness_positions_local_norm": candidate.get(
                    "witness_positions_local_norm", []
                ),
            }
        )

    filtered.sort(
        key=lambda item: (
            float(item["axis_local_norm"]),
            str(item["candidate_id"]),
        )
    )

    if len(filtered) > query.max_candidates:
        return {
            "status": "needs_more_hint",
            "query": query.model_dump(mode="json"),
            "candidate_count": len(filtered),
            "candidates": [],
            "reason": (
                "deterministic view/orientation/band filter still leaves "
                f"{len(filtered)} candidates; do not truncate arbitrarily"
            ),
        }

    return {
        "status": "reduced",
        "query": query.model_dump(mode="json"),
        "candidate_count": len(filtered),
        "candidates": filtered,
    }
