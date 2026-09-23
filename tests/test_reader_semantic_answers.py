from __future__ import annotations

import pytest

from nx_mcp.drawing_intelligence.reader_semantic_answers import (
    ReaderSemanticAnswerError,
    ReaderSemanticAnswers,
    merge_region_semantic_answers,
)
from nx_mcp.drawing_intelligence.reader_semantic_queries import (
    build_reader_semantic_queries,
)


def _reader_input() -> dict:
    return {
        "schema": "reader-input-v1",
        "regions": [
            {
                "region_id": "R1",
                "crop_path": "C:/workspace/reader-crops/R1.png",
            },
            {
                "region_id": "R2",
                "crop_path": "C:/workspace/reader-crops/R2.png",
            },
        ],
        "candidate_buckets": [
            {
                "bucket_id": "R1.vertical.right",
                "region_id": "R1",
                "orientation": "vertical",
                "band": "right",
                "status": "bounded",
                "candidate_count": 1,
                "candidates": [
                    {
                        "candidate_id": "DG19",
                        "orientation": "vertical",
                        "anchor_hints": [],
                    }
                ],
            },
            {
                "bucket_id": "R2.horizontal.bottom",
                "region_id": "R2",
                "orientation": "horizontal",
                "band": "bottom",
                "status": "bounded",
                "candidate_count": 1,
                "candidates": [
                    {
                        "candidate_id": "DG10",
                        "orientation": "horizontal",
                        "anchor_hints": [],
                    }
                ],
            },
        ],
    }


def _answers() -> dict:
    return {
        "schema": "reader-semantic-answers-v1",
        "answers": [
            {
                "query_id": "Q001",
                "view_kind": "front",
                "evidence": ["R1"],
                "overall_dimension_facts": [
                    {
                        "axis": "X",
                        "value": 40,
                        "evidence": ["R1"],
                    },
                    {
                        "axis": "Z",
                        "value": 66,
                        "evidence": ["R1"],
                    },
                ],
                "entities": [
                    {
                        "key": "main_bore",
                        "shape": "circle",
                        "evidence": ["R1"],
                    }
                ],
                "values": [
                    {
                        "entity_key": "main_bore",
                        "field": "diameter",
                        "value": 20,
                        "semantic": "diameter",
                        "evidence": ["R1"],
                    }
                ],
                "dimensions": [
                    {
                        "key": "center_height",
                        "value": 40,
                        "axis": "Z",
                        "endpoints": [
                            {
                                "role": "overall_min",
                                "evidence": ["R1.vertical.right"],
                            },
                            {
                                "role": "entity_center",
                                "entity_key": "main_bore",
                                "basis": "centerline",
                                "evidence": ["R1.vertical.right"],
                            },
                        ],
                        "evidence": ["R1.vertical.right"],
                    }
                ],
                "datum_alignments": [],
                "unresolved": [],
            },
            {
                "query_id": "Q002",
                "view_kind": "side",
                "evidence": ["R2"],
                "overall_dimension_facts": [
                    {
                        "axis": "Y",
                        "value": 32,
                        "evidence": ["R2"],
                    }
                ],
                "entities": [
                    {
                        "key": "main_bore_projection",
                        "shape": "hidden_parallel",
                        "evidence": ["R2"],
                    }
                ],
                "values": [],
                "dimensions": [],
                "datum_alignments": [],
                "unresolved": [],
            },
        ],
    }


def test_merge_prefixes_region_local_keys_without_cross_view_merge():
    plan = build_reader_semantic_queries(_reader_input())
    answers = ReaderSemanticAnswers.model_validate(_answers())

    partial = merge_region_semantic_answers(plan, answers)

    assert partial.schema_version == "reader-partial-observations-v1"
    assert [item.key for item in partial.views] == ["view.R1", "view.R2"]
    assert [item.key for item in partial.entities] == [
        "R1.main_bore",
        "R2.main_bore_projection",
    ]
    assert [item.cross_view_disposition for item in partial.entities] == [None, None]
    assert partial.values[0].entity_key == "R1.main_bore"
    assert partial.dimensions[0].key == "R1.center_height"
    assert partial.dimensions[0].endpoints[1].entity_key == "R1.main_bore"


def test_merge_keeps_overall_dimension_facts_separate():
    plan = build_reader_semantic_queries(_reader_input())
    answers = ReaderSemanticAnswers.model_validate(_answers())

    partial = merge_region_semantic_answers(plan, answers)

    assert [(item.axis, item.value) for item in partial.overall_dimension_facts] == [
        ("X", 40),
        ("Z", 66),
        ("Y", 32),
    ]


def test_answer_cannot_use_evidence_outside_query():
    payload = _answers()
    payload["answers"][0]["entities"][0]["evidence"] = ["R2"]

    plan = build_reader_semantic_queries(_reader_input())
    answers = ReaderSemanticAnswers.model_validate(payload)

    with pytest.raises(ReaderSemanticAnswerError, match="unlisted evidence"):
        merge_region_semantic_answers(plan, answers)


def test_answer_set_must_match_query_plan_exactly():
    payload = _answers()
    payload["answers"] = payload["answers"][:1]

    plan = build_reader_semantic_queries(_reader_input())
    answers = ReaderSemanticAnswers.model_validate(payload)

    with pytest.raises(ReaderSemanticAnswerError, match="missing"):
        merge_region_semantic_answers(plan, answers)


def test_unknown_local_entity_reference_rejected():
    payload = _answers()
    payload["answers"][0]["values"][0]["entity_key"] = "missing"

    with pytest.raises(ValueError, match="unknown local entity"):
        ReaderSemanticAnswers.model_validate(payload)
