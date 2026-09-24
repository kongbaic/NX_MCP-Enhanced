from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nx_mcp.drawing_intelligence.dimension_candidate_reducer import (
    DimensionCandidateQuery,
    reduce_dimension_candidates,
)


def _candidate(
    candidate_id: str,
    region_id: str,
    orientation: str,
    axis_local_norm: float,
    witnesses: list[float],
) -> dict:
    return {
        "candidate_id": candidate_id,
        "region_id": region_id,
        "orientation": orientation,
        "axis_px": axis_local_norm * 1000,
        "axis_local_norm": axis_local_norm,
        "line_span_px": [0, 100],
        "witness_positions_px": witnesses,
        "witness_positions_local_norm": [value / 1000 for value in witnesses],
        "witness_line_evidence": [
            {
                "witness_index": index,
                "position_px": value,
                "source_lines": [
                    {
                        "orientation": (
                            "vertical"
                            if orientation == "horizontal"
                            else "horizontal"
                        ),
                        "axis_px": value,
                        "span_px": [0, 100],
                        "span_length_px": 100,
                        "crosses_dimension_axis": True,
                    }
                ],
            }
            for index, value in enumerate(witnesses)
        ],
    }


def _raw() -> dict:
    return {
        "dimension_geometry_candidates": [
            # front / vertical
            _candidate("DG13", "R1", "vertical", 0.078, [255.0, 704.5]),
            _candidate("DG15", "R1", "vertical", 0.362, [619.0, 706.3]),
            _candidate(
                "DG19",
                "R1",
                "vertical",
                0.866,
                [299.0, 402.6, 619.0, 706.3],
            ),
            _candidate("DG20", "R1", "vertical", 0.973, [402.6, 706.3]),
            # front / horizontal
            _candidate(
                "DG9",
                "R1",
                "horizontal",
                0.776,
                [182.0, 225.0, 476.0, 521.0],
            ),
            _candidate(
                "DG12",
                "R1",
                "horizontal",
                0.979,
                [182.0, 521.0],
            ),
            # side / horizontal
            _candidate(
                "DG10",
                "R2",
                "horizontal",
                0.789,
                [795.2, 838.0, 1007.2],
            ),
            _candidate(
                "DG11",
                "R2",
                "horizontal",
                0.885,
                [837.8, 1006.6],
            ),
            # noise from a different orientation / band
            _candidate("DGX", "R1", "horizontal", 0.400, [10.0, 20.0]),
        ]
    }


@pytest.mark.parametrize(
    ("query", "expected_ids"),
    [
        (
            {
                "region_id": "R1",
                "orientation": "vertical",
                "band": "left",
            },
            {"DG13", "DG15"},
        ),
        (
            {
                "region_id": "R1",
                "orientation": "vertical",
                "band": "right",
            },
            {"DG19", "DG20"},
        ),
        (
            {
                "region_id": "R1",
                "orientation": "horizontal",
                "band": "bottom",
            },
            {"DG9", "DG12"},
        ),
        (
            {
                "region_id": "R2",
                "orientation": "horizontal",
                "band": "bottom",
            },
            {"DG10", "DG11"},
        ),
    ],
)
def test_reducer_keeps_expected_small_candidate_pool(query, expected_ids):
    result = reduce_dimension_candidates(_raw(), query)

    assert result["status"] == "reduced"
    assert result["candidate_count"] == len(expected_ids)
    assert {
        item["candidate_id"]
        for item in result["candidates"]
    } == expected_ids
    assert result["candidate_count"] <= 2
    assert all(
        len(item["witness_line_evidence"]) == len(item["witness_positions_px"])
        for item in result["candidates"]
    )


def test_reducer_does_not_mix_orientation():
    result = reduce_dimension_candidates(
        _raw(),
        {
            "region_id": "R1",
            "orientation": "vertical",
            "band": "left",
        },
    )

    assert all(
        item["orientation"] == "vertical"
        for item in result["candidates"]
    )


def test_reducer_does_not_arbitrarily_truncate_more_than_four_candidates():
    raw = {
        "dimension_geometry_candidates": [
            _candidate(
                f"DG{index}",
                "R1",
                "horizontal",
                0.80 + index * 0.01,
                [index * 10.0, index * 10.0 + 5.0],
            )
            for index in range(5)
        ]
    }

    result = reduce_dimension_candidates(
        raw,
        DimensionCandidateQuery(
            region_id="R1",
            orientation="horizontal",
            band="bottom",
        ),
    )

    assert result["status"] == "needs_more_hint"
    assert result["candidate_count"] == 5
    assert result["candidates"] == []


ROOT = Path(__file__).resolve().parents[1]


def test_reduce_dimension_candidates_cli_e2e(tmp_path: Path):
    raw_path = tmp_path / "raw-evidence.json"
    hints_path = tmp_path / "dimension-hints.json"
    out_path = tmp_path / "reduced.json"

    raw_path.write_text(
        json.dumps(_raw()),
        encoding="utf-8",
    )
    hints_path.write_text(
        json.dumps(
            {
                "dimensions": [
                    {
                        "dimension_id": "D_FRONT_8",
                        "label": "8",
                        "region_id": "R1",
                        "orientation": "vertical",
                        "band": "left",
                    },
                    {
                        "dimension_id": "D_FRONT_40TOL",
                        "label": "40±0.02",
                        "region_id": "R1",
                        "orientation": "vertical",
                        "band": "right",
                    },
                    {
                        "dimension_id": "D_FRONT_24",
                        "label": "24",
                        "region_id": "R1",
                        "orientation": "horizontal",
                        "band": "bottom",
                    },
                    {
                        "dimension_id": "D_SIDE_24",
                        "label": "24",
                        "region_id": "R2",
                        "orientation": "horizontal",
                        "band": "bottom",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "reduce-dimension-candidates",
            str(raw_path),
            str(hints_path),
            str(out_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    output = json.loads(out_path.read_text(encoding="utf-8"))
    assert output["dimension_count"] == 4

    by_id = {
        item["dimension_id"]: item
        for item in output["dimensions"]
    }
    assert by_id["D_FRONT_8"]["candidate_count"] == 2
    assert by_id["D_FRONT_40TOL"]["candidate_count"] == 2
    assert by_id["D_FRONT_24"]["candidate_count"] == 2
    assert by_id["D_SIDE_24"]["candidate_count"] == 2

    front_40_ids = {
        item["candidate_id"]
        for item in by_id["D_FRONT_40TOL"]["candidates"]
    }
    assert front_40_ids == {"DG19", "DG20"}
