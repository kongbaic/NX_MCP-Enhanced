from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Orientation = Literal["horizontal", "vertical"]
Band = Literal["top", "middle", "bottom", "left", "right"]


class ReaderCandidateQueryError(ValueError):
    """Raised when candidate-addressed Reader queries cannot be built safely."""


class _StrictCandidateQueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CandidateAnchorOption(_StrictCandidateQueryModel):
    kind: Literal["region_bbox_edge", "circle_center_axis", "linear_pattern_axis"]
    ref: str = Field(min_length=1)


class CandidateWitnessHint(_StrictCandidateQueryModel):
    witness_index: int = Field(ge=0)
    anchor_options: list[CandidateAnchorOption] = Field(default_factory=list)


class CandidateDimensionTarget(_StrictCandidateQueryModel):
    target_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    evidence_label: str = Field(min_length=1)
    orientation: Orientation
    band: Band
    witness_hints: list[CandidateWitnessHint] = Field(default_factory=list)

    @field_validator("witness_hints")
    @classmethod
    def _unique_witnesses(cls, value: list[CandidateWitnessHint]) -> list[CandidateWitnessHint]:
        indexes = [item.witness_index for item in value]
        if len(indexes) != len(set(indexes)):
            raise ValueError("candidate witness indexes must be unique")
        return value


class CandidateCircleEntity(_StrictCandidateQueryModel):
    entity_key: str = Field(min_length=1)
    ring_count: int = Field(ge=1)


class CandidateOverflowBucket(_StrictCandidateQueryModel):
    evidence_label: str = Field(min_length=1)
    orientation: Orientation
    band: Band
    candidate_count: int = Field(ge=1)
    reason: str = Field(min_length=1)


class CandidateRegionQuery(_StrictCandidateQueryModel):
    query_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    allowed_evidence_labels: list[str] = Field(min_length=1)
    circle_entities: list[CandidateCircleEntity] = Field(default_factory=list)
    dimension_targets: list[CandidateDimensionTarget] = Field(default_factory=list)
    overflow_buckets: list[CandidateOverflowBucket] = Field(default_factory=list)

    @model_validator(mode="after")
    def _local_ids(self) -> CandidateRegionQuery:
        target_ids = [item.target_id for item in self.dimension_targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("candidate target ids must be unique within a region")
        entity_keys = [item.entity_key for item in self.circle_entities]
        if len(entity_keys) != len(set(entity_keys)):
            raise ValueError("candidate circle entity keys must be unique within a region")
        return self


class ReaderCandidateQueryPlan(_StrictCandidateQueryModel):
    schema_version: Literal["reader-candidate-queries-v1"] = Field(
        default="reader-candidate-queries-v1",
        alias="schema",
    )
    source_drawing_authoritative: Literal[True] = True
    query_policy: Literal["candidate_addressed_dimension_semantics_only"] = (
        "candidate_addressed_dimension_semantics_only"
    )
    queries: list[CandidateRegionQuery] = Field(min_length=1, max_length=4)
    rules: dict[str, bool] = Field(default_factory=dict)


def _circle_entities_for_region(
    visual_aid: dict[str, Any],
    region_id: str,
) -> list[CandidateCircleEntity]:
    regions = visual_aid.get("regions", [])
    if not isinstance(regions, list):
        raise ReaderCandidateQueryError("reader visual aid regions must be a list")

    for region in regions:
        if not isinstance(region, dict) or region.get("region_id") != region_id:
            continue
        output: list[CandidateCircleEntity] = []
        for group in region.get("circle_groups", []):
            if not isinstance(group, dict):
                continue
            group_id = group.get("circle_group_id")
            rings = group.get("rings", [])
            if not isinstance(group_id, str) or not group_id:
                continue
            if not isinstance(rings, list) or not rings:
                continue
            output.append(
                CandidateCircleEntity(
                    entity_key=group_id,
                    ring_count=len(rings),
                )
            )
        return output
    return []


def _anchor_options(raw_hints: list[dict[str, Any]]) -> list[CandidateWitnessHint]:
    output: list[CandidateWitnessHint] = []
    for hint in raw_hints:
        if not isinstance(hint, dict):
            continue
        witness_index = hint.get("witness_index")
        if not isinstance(witness_index, int) or witness_index < 0:
            continue
        options: list[CandidateAnchorOption] = []
        for anchor in hint.get("nearby_anchors", []):
            if not isinstance(anchor, dict):
                continue
            kind = anchor.get("kind")
            ref = anchor.get("ref")
            if kind not in {
                "region_bbox_edge",
                "circle_center_axis",
                "linear_pattern_axis",
            }:
                continue
            if not isinstance(ref, str) or not ref:
                continue
            options.append(CandidateAnchorOption(kind=kind, ref=ref))
        output.append(
            CandidateWitnessHint(
                witness_index=witness_index,
                anchor_options=options,
            )
        )
    return output


def build_reader_candidate_queries(
    reader_input: dict[str, Any],
    visual_aid: dict[str, Any],
    *,
    max_targets_per_region: int = 20,
) -> ReaderCandidateQueryPlan:
    """Build generic candidate-addressed dimension queries without semantic inference."""

    if reader_input.get("schema") != "reader-input-v1":
        raise ReaderCandidateQueryError("candidate queries require reader-input-v1")
    if visual_aid.get("schema") != "reader-visual-aid-v1":
        raise ReaderCandidateQueryError(
            "candidate queries require reader-visual-aid-v1"
        )
    if not 1 <= max_targets_per_region <= 32:
        raise ReaderCandidateQueryError(
            "max_targets_per_region must be between 1 and 32"
        )

    regions = reader_input.get("regions")
    buckets = reader_input.get("candidate_buckets")
    if not isinstance(regions, list) or not regions:
        raise ReaderCandidateQueryError("reader input requires regions")
    if not isinstance(buckets, list):
        raise ReaderCandidateQueryError("reader input candidate_buckets must be a list")
    if len(regions) > 4:
        raise ReaderCandidateQueryError("candidate query count exceeds bounded maximum 4")

    buckets_by_region: dict[str, list[dict[str, Any]]] = {}
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        region_id = bucket.get("region_id")
        if isinstance(region_id, str) and region_id:
            buckets_by_region.setdefault(region_id, []).append(bucket)

    queries: list[CandidateRegionQuery] = []
    for index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            raise ReaderCandidateQueryError("reader input region must be an object")
        region_id = region.get("region_id")
        image_path = region.get("crop_path")
        if not isinstance(region_id, str) or not region_id:
            raise ReaderCandidateQueryError("reader region requires region_id")
        if not isinstance(image_path, str) or not image_path:
            raise ReaderCandidateQueryError(
                f"reader region {region_id!r} requires crop_path"
            )

        labels = [region_id]
        targets: list[CandidateDimensionTarget] = []
        overflow: list[CandidateOverflowBucket] = []

        for bucket in sorted(
            buckets_by_region.get(region_id, []),
            key=lambda item: str(item.get("bucket_id") or ""),
        ):
            bucket_id = bucket.get("bucket_id")
            orientation = bucket.get("orientation")
            band = bucket.get("band")
            status = bucket.get("status")
            candidate_count = bucket.get("candidate_count", 0)
            if (
                not isinstance(bucket_id, str)
                or not bucket_id
                or orientation not in {"horizontal", "vertical"}
                or band not in {"top", "middle", "bottom", "left", "right"}
                or not isinstance(candidate_count, int)
            ):
                raise ReaderCandidateQueryError(
                    f"region {region_id!r} has malformed candidate bucket"
                )
            labels.append(bucket_id)

            if status == "overflow":
                overflow.append(
                    CandidateOverflowBucket(
                        evidence_label=bucket_id,
                        orientation=orientation,
                        band=band,
                        candidate_count=candidate_count,
                        reason=str(bucket.get("reason") or "candidate bucket overflow"),
                    )
                )
                continue
            if status != "bounded":
                raise ReaderCandidateQueryError(
                    f"candidate bucket {bucket_id!r} has unsupported status {status!r}"
                )

            candidates = bucket.get("candidates", [])
            if not isinstance(candidates, list):
                raise ReaderCandidateQueryError(
                    f"candidate bucket {bucket_id!r} candidates must be a list"
                )
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                candidate_id = candidate.get("candidate_id")
                if not isinstance(candidate_id, str) or not candidate_id:
                    raise ReaderCandidateQueryError(
                        f"candidate bucket {bucket_id!r} has candidate without id"
                    )
                targets.append(
                    CandidateDimensionTarget(
                        target_id=candidate_id,
                        candidate_id=candidate_id,
                        evidence_label=bucket_id,
                        orientation=orientation,
                        band=band,
                        witness_hints=_anchor_options(
                            candidate.get("anchor_hints", [])
                            if isinstance(candidate.get("anchor_hints", []), list)
                            else []
                        ),
                    )
                )

        if len(targets) > max_targets_per_region:
            raise ReaderCandidateQueryError(
                f"region {region_id!r} has {len(targets)} addressed targets; "
                f"bounded maximum is {max_targets_per_region}"
            )

        queries.append(
            CandidateRegionQuery(
                query_id=f"Q{index:03d}",
                region_id=region_id,
                image_path=image_path,
                allowed_evidence_labels=labels,
                circle_entities=_circle_entities_for_region(
                    visual_aid,
                    region_id,
                ),
                dimension_targets=targets,
                overflow_buckets=overflow,
            )
        )

    return ReaderCandidateQueryPlan(
        queries=queries,
        rules={
            "read_only_query_image": True,
            "open_unlisted_images": False,
            "scan_region_for_unaddressed_facts": False,
            "answer_only_listed_dimension_targets": True,
            "cross_view_identity": False,
            "programmatic_image_analysis": False,
            "pixel_measurement": False,
            "image_transform": False,
            "second_interpretation": False,
        },
    )
