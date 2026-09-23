from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReaderSemanticQueryError(ValueError):
    """Raised when bounded semantic queries cannot be built safely."""


class _StrictQueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RegionCandidateBucket(_StrictQueryModel):
    bucket_id: str = Field(min_length=1)
    orientation: Literal["horizontal", "vertical"]
    band: Literal["top", "middle", "bottom", "left", "right"]
    status: Literal["bounded", "overflow"]
    candidate_count: int = Field(ge=0)
    candidates: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _overflow_shape(self) -> RegionCandidateBucket:
        if self.status == "overflow" and self.candidates:
            raise ValueError("overflow bucket must not expose candidate entries")
        if self.status == "bounded" and self.candidate_count != len(self.candidates):
            raise ValueError("bounded bucket candidate_count must match candidates")
        return self


class RegionObservationQuery(_StrictQueryModel):
    query_id: str = Field(min_length=1)
    kind: Literal["region_observation"] = "region_observation"
    region_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    allowed_evidence_labels: list[str] = Field(min_length=1)
    candidate_buckets: list[RegionCandidateBucket] = Field(default_factory=list)
    instruction_key: Literal["region-observation-v1"] = "region-observation-v1"

    @field_validator("allowed_evidence_labels")
    @classmethod
    def _unique_labels(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("allowed_evidence_labels must be unique")
        return value


class ReaderSemanticQueryPlan(_StrictQueryModel):
    schema_version: Literal["reader-semantic-queries-v1"] = Field(
        default="reader-semantic-queries-v1",
        alias="schema",
    )
    source_drawing_authoritative: Literal[True] = True
    query_policy: Literal["bounded_local_semantics_only"] = "bounded_local_semantics_only"
    queries: list[RegionObservationQuery] = Field(min_length=1, max_length=4)
    rules: dict[str, bool] = Field(default_factory=dict)


def build_reader_semantic_queries(
    reader_input: dict[str, Any],
    *,
    max_region_queries: int = 4,
) -> ReaderSemanticQueryPlan:
    """Build bounded region-local semantic questions without semantic inference."""

    if reader_input.get("schema") != "reader-input-v1":
        raise ReaderSemanticQueryError("semantic queries require reader-input-v1")
    if not 1 <= max_region_queries <= 4:
        raise ReaderSemanticQueryError("max_region_queries must be between 1 and 4")

    regions = reader_input.get("regions")
    buckets = reader_input.get("candidate_buckets")
    if not isinstance(regions, list) or not regions:
        raise ReaderSemanticQueryError("reader input requires at least one region")
    if not isinstance(buckets, list):
        raise ReaderSemanticQueryError("reader input candidate_buckets must be a list")
    if len(regions) > max_region_queries:
        raise ReaderSemanticQueryError(
            f"region query count {len(regions)} exceeds bounded maximum {max_region_queries}"
        )

    buckets_by_region: dict[str, list[dict[str, Any]]] = {}
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        region_id = bucket.get("region_id")
        if isinstance(region_id, str) and region_id:
            buckets_by_region.setdefault(region_id, []).append(bucket)

    queries: list[RegionObservationQuery] = []
    seen_regions: set[str] = set()

    for index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            raise ReaderSemanticQueryError("reader input region must be an object")

        region_id = region.get("region_id")
        crop_path = region.get("crop_path")
        if not isinstance(region_id, str) or not region_id:
            raise ReaderSemanticQueryError("reader input region requires region_id")
        if region_id in seen_regions:
            raise ReaderSemanticQueryError(f"duplicate reader region {region_id!r}")
        seen_regions.add(region_id)
        if not isinstance(crop_path, str) or not crop_path:
            raise ReaderSemanticQueryError(f"reader region {region_id!r} requires crop_path")

        compact_buckets: list[RegionCandidateBucket] = []
        labels = [region_id]

        region_buckets = sorted(
            buckets_by_region.get(region_id, []),
            key=lambda item: str(item.get("bucket_id") or ""),
        )
        for bucket in region_buckets:
            bucket_id = bucket.get("bucket_id")
            if not isinstance(bucket_id, str) or not bucket_id:
                raise ReaderSemanticQueryError(f"region {region_id!r} has bucket without bucket_id")
            labels.append(bucket_id)
            compact_buckets.append(
                RegionCandidateBucket.model_validate(
                    {
                        "bucket_id": bucket_id,
                        "orientation": bucket.get("orientation"),
                        "band": bucket.get("band"),
                        "status": bucket.get("status"),
                        "candidate_count": bucket.get("candidate_count", 0),
                        "candidates": bucket.get("candidates", []),
                    }
                )
            )

        queries.append(
            RegionObservationQuery(
                query_id=f"Q{index:03d}",
                region_id=region_id,
                image_path=crop_path,
                allowed_evidence_labels=labels,
                candidate_buckets=compact_buckets,
            )
        )

    return ReaderSemanticQueryPlan(
        queries=queries,
        rules={
            "read_only_query_image": True,
            "open_unlisted_images": False,
            "scan_workspace": False,
            "cross_view_identity": False,
            "global_feature_merge": False,
            "reader_capture_output": False,
            "second_interpretation": False,
        },
    )
