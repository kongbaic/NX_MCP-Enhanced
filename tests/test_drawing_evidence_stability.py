from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from nx_mcp.drawing_intelligence import (
    DatumAlignmentEvidence,
    DimensionEndpoint,
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    OverallDimensions,
    ProjectionEvidence,
    ViewEvidence,
    compare_evidence_runs,
    write_strict_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def _main_hole_graph(*, z_value: float, suffix: str, reverse_direct: bool = False):
    direct = [
        DirectValueEvidence(
            id=f"KIND_{suffix}",
            target="feature:F_MAIN.type",
            value="through_hole",
            source_ids=[f"SRC_KIND_{suffix}"],
        ),
        DirectValueEvidence(
            id=f"DIA_{suffix}",
            target="feature:F_MAIN.diameter",
            value=20,
            source_ids=[f"SRC_DIA_{suffix}"],
        ),
        DirectValueEvidence(
            id=f"COUNT_{suffix}",
            target="feature:F_MAIN.count",
            value=1,
            source_ids=[f"SRC_COUNT_{suffix}"],
        ),
    ]
    if reverse_direct:
        direct.reverse()

    return EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[
            ViewEvidence(
                id=f"VIEW_{suffix}",
                kind="front",
                source_ids=[f"SRC_VIEW_{suffix}"],
            )
        ],
        projections=[
            ProjectionEvidence(
                id=f"PROJ_{suffix}",
                feature_id="F_MAIN",
                view_id=f"VIEW_{suffix}",
                shape="circle",
                source_ids=[f"SRC_PROJ_{suffix}"],
            )
        ],
        datum_alignments=[
            DatumAlignmentEvidence(
                id=f"ALIGN_X_{suffix}",
                target="feature:F_MAIN.centerline.x",
                axis="X",
                source_ids=[f"SRC_CENTERLINE_{suffix}"],
            )
        ],
        dimensions=[
            DimensionObservation(
                id=f"DIM_Z_{suffix}",
                value=z_value,
                axis="Z",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(
                        role="feature_center",
                        target="feature:F_MAIN.centerline.z",
                    ),
                ],
                source_ids=[f"SRC_DIM_{suffix}"],
            )
        ],
        direct_values=direct,
        required_targets=[
            "feature:F_MAIN.centerline.x",
            "feature:F_MAIN.centerline.z",
        ],
    )


def _spacing_graph(*, signed: bool):
    relation = {
        "id": "R_SPACING",
        "kind": "center_spacing",
        "axis": "X",
        "value": 20,
        "targets": [
            "feature:F_A.centerline.x",
            "feature:F_B.centerline.x",
        ],
    }
    if signed:
        relation["direction"] = 1

    return EvidenceGraph.model_validate(
        {
            "overall_dimensions": {
                "length_x": 40,
                "width_y": 32,
                "height_z": 66,
            },
            "direct_values": [
                {
                    "id": "A_X",
                    "target": "feature:F_A.centerline.x",
                    "value": -10,
                }
            ],
            "relations": [relation],
            "required_targets": ["feature:F_B.centerline.x"],
        }
    )


def test_stability_ignores_evidence_ids_sources_and_order():
    first = _main_hole_graph(z_value=40, suffix="A")
    second = _main_hole_graph(
        z_value=40,
        suffix="B",
        reverse_direct=True,
    )

    report = compare_evidence_runs([first, second])

    assert report.stable
    assert report.unique_fingerprints == 1
    assert report.changed_sections == {}
    assert report.value_drift == {}
    assert report.unresolved_presence == {}


def test_stability_detects_resolved_value_drift_by_target():
    first = _main_hole_graph(z_value=40, suffix="A")
    second = _main_hole_graph(z_value=41, suffix="B")

    report = compare_evidence_runs([first, second])

    assert not report.stable
    assert report.unique_fingerprints == 2
    assert report.value_drift["feature:F_MAIN.centerline.z"] == [40.0, 41.0]
    assert 2 in report.changed_sections
    assert "relations" in report.changed_sections[2]
    assert "resolved_values" in report.changed_sections[2]


def test_stability_detects_resolved_vs_unresolved_drift():
    resolved = _spacing_graph(signed=True)
    unresolved = _spacing_graph(signed=False)

    report = compare_evidence_runs([resolved, unresolved])

    assert not report.stable
    assert report.unresolved_presence["feature:F_B.centerline.x"] == [2]
    assert report.value_drift["feature:F_B.centerline.x"] == [10.0, "<missing>"]


def test_stability_cli_exit_codes_and_report(tmp_path: Path):
    first = _main_hole_graph(z_value=40, suffix="A")
    same = _main_hole_graph(z_value=40, suffix="B", reverse_direct=True)
    drift = _main_hole_graph(z_value=41, suffix="C")

    paths = []
    for index, graph in enumerate((first, same, drift), start=1):
        path = tmp_path / f"run-{index}.json"
        path.write_text(
            json.dumps(graph.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )
        paths.append(path)

    stable_report = tmp_path / "stable-report.json"
    stable = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "stability",
            str(paths[0]),
            str(paths[1]),
            "--report",
            str(stable_report),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stable.returncode == 0, stable.stdout + stable.stderr
    stable_data = json.loads(stable.stdout)
    assert stable_data["stable"] is True
    assert stable_report.exists()

    changed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "stability",
            str(paths[0]),
            str(paths[2]),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert changed.returncode == 2, changed.stdout + changed.stderr
    changed_data = json.loads(changed.stdout)
    assert changed_data["stable"] is False
    assert changed_data["value_drift"]["feature:F_MAIN.centerline.z"] == [
        40.0,
        41.0,
    ]


def _gate0_graph_with_bad_dimension(record: dict):
    capture = {
        "schema_version": "1.0",
        "coordinate_system": "overall_min_xyz",
        "overall_dimensions": {
            "length_x": 40,
            "width_y": 32,
            "height_z": 66,
        },
        "views": [],
        "projections": [],
        "dimensions": [record],
        "datum_alignments": [],
        "direct_values": [],
        "relations": [],
        "required_targets": [],
        "observations": [],
        "unresolved_evidence": [],
    }
    return write_strict_evidence(capture).evidence


def test_stability_ignores_gate0_quarantine_ids_sources_notes_and_array_position():
    first = _gate0_graph_with_bad_dimension(
        {
            "id": "DIM_A",
            "value": 40,
            "axis": "Z",
            "endpoints": [],
            "source_ids": ["SRC_A"],
            "note": "first wording",
            "required_for_modeling": True,
        }
    )
    second = _gate0_graph_with_bad_dimension(
        {
            "id": "COMPLETELY_DIFFERENT_ID",
            "value": 40,
            "axis": "Z",
            "endpoints": [],
            "source_ids": ["OTHER_SOURCE"],
            "note": "different prose",
            "required_for_modeling": True,
        }
    )

    report = compare_evidence_runs([first, second])

    assert report.stable
    assert report.unique_fingerprints == 1
    assert report.changed_sections == {}


def test_stability_detects_gate0_quarantine_shape_drift_without_safe_target():
    missing = _gate0_graph_with_bad_dimension(
        {
            "id": "D_MISSING",
            "value": 40,
            "axis": "Z",
            "source_ids": ["SRC"],
            "required_for_modeling": True,
        }
    )
    empty = _gate0_graph_with_bad_dimension(
        {
            "id": "D_EMPTY",
            "value": 40,
            "axis": "Z",
            "endpoints": [],
            "source_ids": ["SRC"],
            "required_for_modeling": True,
        }
    )

    report = compare_evidence_runs([missing, empty])

    assert not report.stable
    assert report.unique_fingerprints == 2
    assert 2 in report.changed_sections
    assert "gate0_quarantines" in report.changed_sections[2]


def test_stability_detects_gate0_quarantine_value_axis_and_role_drift():
    first = _gate0_graph_with_bad_dimension(
        {
            "id": "D_A",
            "value": 40,
            "axis": "Z",
            "endpoints": [
                {"role": "overall_min"},
                {
                    "role": "intermediate_surface",
                    "target": "feature:F_MAIN.centerline.z",
                },
            ],
            "required_for_modeling": True,
        }
    )
    second = _gate0_graph_with_bad_dimension(
        {
            "id": "D_B",
            "value": 48,
            "axis": "Y",
            "endpoints": [
                {"role": "overall_min"},
                {
                    "role": "step_surface",
                    "target": "feature:F_MAIN.centerline.z",
                },
            ],
            "required_for_modeling": True,
        }
    )

    report = compare_evidence_runs([first, second])

    assert not report.stable
    assert 2 in report.changed_sections
    assert "gate0_quarantines" in report.changed_sections[2]


def test_stability_cli_writes_report_on_comparator_error(tmp_path: Path):
    bad_graph = EvidenceGraph.model_validate(
        {
            "overall_dimensions": {
                "length_x": 40,
                "width_y": 32,
                "height_z": 66,
            },
            "direct_values": [
                {
                    "id": "BAD_DATUM",
                    "target": "datum:A",
                    "value": 1,
                }
            ],
        }
    )

    paths = []
    for index in (1, 2):
        path = tmp_path / f"bad-run-{index}.json"
        path.write_text(
            json.dumps(bad_graph.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )
        paths.append(path)

    report_path = tmp_path / "error-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "stability",
            str(paths[0]),
            str(paths[1]),
            "--report",
            str(report_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert report_path.exists()

    stdout_report = json.loads(completed.stdout)
    file_report = json.loads(report_path.read_text(encoding="utf-8"))

    assert stdout_report == file_report
    assert file_report["stable"] is False
    assert file_report["run_count"] == 0
    assert file_report["unique_fingerprints"] == 0
    assert any(
        "DraftAssemblyError" in error and "datum:A" in error
        for error in file_report["errors"]
    )


def test_stability_ignores_duplicate_overall_dimension_observations():
    base = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
    )
    repeated = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        dimensions=[
            DimensionObservation(
                id="DX",
                value=40,
                axis="X",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="overall_max"),
                ],
            ),
            DimensionObservation(
                id="DY",
                value=32,
                axis="Y",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="overall_max"),
                ],
            ),
            DimensionObservation(
                id="DZ",
                value=66,
                axis="Z",
                endpoints=[
                    DimensionEndpoint(role="overall_min"),
                    DimensionEndpoint(role="overall_max"),
                ],
            ),
        ],
    )

    report = compare_evidence_runs([base, repeated])

    assert report.stable
    assert report.unique_fingerprints == 1
