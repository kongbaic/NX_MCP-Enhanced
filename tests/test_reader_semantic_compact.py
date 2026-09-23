from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nx_mcp.drawing_intelligence.reader_semantic_compact import (
    CompactRegionSemanticAnswer,
    ReaderSemanticCompactError,
    assemble_compact_regions,
    build_reader_semantic_answers_from_regions,
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


def _compact_answers() -> list[CompactRegionSemanticAnswer]:
    return [
        CompactRegionSemanticAnswer.model_validate(
            {
                "schema": "reader-semantic-region-v1",
                "query_id": "Q001",
                "view_kind": "front",
                "facts": [
                    {
                        "kind": "overall",
                        "axis": "X",
                        "value": 40,
                        "evidence": "R1",
                    },
                    {
                        "kind": "entity",
                        "key": "main_bore",
                        "shape": "circle",
                        "evidence": "R1",
                    },
                    {
                        "kind": "entity",
                        "key": "base_profile",
                        "shape": "rectangle",
                        "evidence": "R1",
                    },
                    {
                        "kind": "entity",
                        "key": "hole_left",
                        "shape": "circle",
                        "evidence": "R1",
                    },
                    {
                        "kind": "entity",
                        "key": "hole_right",
                        "shape": "circle",
                        "evidence": "R1",
                    },
                    {
                        "kind": "value",
                        "entity_key": "main_bore",
                        "field": "diameter",
                        "value": 20,
                        "semantic": "diameter",
                        "evidence": "R1",
                    },
                    {
                        "kind": "dimension",
                        "key": "center_height",
                        "axis": "Z",
                        "value": 40,
                        "endpoint_a": "overall_min",
                        "endpoint_b": "center:main_bore:centerline",
                        "evidence": "R1.vertical.right",
                    },
                    {
                        "kind": "dimension",
                        "key": "hole_owner",
                        "axis": "X",
                        "value": 24,
                        "endpoint_a": "overall_min",
                        "endpoint_b": "ambiguous:hole_left,hole_right",
                        "reason": "The endpoint could belong to either visible local hole.",
                        "evidence": "R1.vertical.right",
                    },
                    {
                        "kind": "unresolved",
                        "category": "unsupported_representation",
                        "reason": "Visible tolerance is not represented in the compact dimension fact.",
                        "dimension_key": "center_height",
                        "dimension_value": 40,
                        "field": "tolerance",
                        "axis": "Z",
                        "evidence": "R1.vertical.right",
                    },
                ],
            }
        ),
        CompactRegionSemanticAnswer.model_validate(
            {
                "schema": "reader-semantic-region-v1",
                "query_id": "Q002",
                "view_kind": "side",
                "facts": [
                    {
                        "kind": "overall",
                        "axis": "Y",
                        "value": 32,
                        "evidence": "R2",
                    },
                    {
                        "kind": "entity",
                        "key": "main_bore_projection",
                        "shape": "hidden_parallel",
                        "evidence": "R2",
                    },
                ],
            }
        ),
    ]


def test_compact_regions_expand_into_existing_strict_schema():
    plan = build_reader_semantic_queries(_reader_input())
    strict = build_reader_semantic_answers_from_regions(plan, _compact_answers())

    first = strict.answers[0]
    assert first.entities[1].shape == "profile"
    assert first.dimensions[0].endpoints[1].role == "entity_center"
    assert first.dimensions[0].endpoints[1].entity_key == "main_bore"
    assert first.dimensions[0].endpoints[1].basis == "centerline"
    assert first.dimensions[1].endpoints[1].unresolved_kind == "ambiguous_owner"
    assert first.dimensions[1].endpoints[1].candidate_entity_keys == [
        "hole_left",
        "hole_right",
    ]


def test_compact_regions_reuse_existing_partial_merge():
    plan = build_reader_semantic_queries(_reader_input())
    strict, partial = assemble_compact_regions(plan, _compact_answers())

    assert len(strict.answers) == 2
    assert [item.key for item in partial.views] == ["view.R1", "view.R2"]
    assert "R1.main_bore" in [item.key for item in partial.entities]
    assert partial.dimensions[0].endpoints[1].entity_key == "R1.main_bore"
    assert partial.dimensions[1].endpoints[1].candidate_entity_keys == [
        "R1.hole_left",
        "R1.hole_right",
    ]


def test_compact_unknown_shape_alias_fails_closed():
    plan = build_reader_semantic_queries(_reader_input())
    answers = _compact_answers()
    answers[0].facts[1].shape = "hexagon"

    with pytest.raises(ReaderSemanticCompactError, match="unknown compact shape token"):
        build_reader_semantic_answers_from_regions(plan, answers)


def test_compact_unlisted_evidence_fails_closed():
    plan = build_reader_semantic_queries(_reader_input())
    answers = _compact_answers()
    answers[0].facts[0].evidence = "R2"

    with pytest.raises(ReaderSemanticCompactError, match="unlisted evidence label"):
        build_reader_semantic_answers_from_regions(plan, answers)


ROOT = Path(__file__).resolve().parents[1]


def test_token_contract_avoids_benchmark_specific_examples():
    contract = (
        ROOT / "skills" / "nx-agent" / "references" / "reader-bounded-token-contract.md"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "SHKSS",
        "main_bore",
        "center_height",
        "40±0.02",
        "20 H7",
    ):
        assert forbidden not in contract


def test_assemble_reader_semantic_regions_cli_e2e(tmp_path: Path):
    query_plan = tmp_path / "reader-semantic-queries.json"
    answers_out = tmp_path / "reader-semantic-answers.json"
    partial_out = tmp_path / "reader-partial-observations.json"

    plan = build_reader_semantic_queries(_reader_input())
    query_plan.write_text(
        json.dumps(plan.model_dump(mode="json", by_alias=True), indent=2),
        encoding="utf-8",
    )

    for answer in _compact_answers():
        path = tmp_path / f"reader-semantic-{answer.query_id}.json"
        path.write_text(
            json.dumps(answer.model_dump(mode="json", by_alias=True), indent=2),
            encoding="utf-8",
        )

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "assemble-reader-semantic-regions",
            str(query_plan),
            str(tmp_path),
            str(answers_out),
            str(partial_out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads(run.stdout)
    assert report["written"] is True
    assert report["schema"] == "reader-partial-observations-v1"
    assert report["query_count"] == 2
    assert answers_out.is_file()
    assert partial_out.is_file()
