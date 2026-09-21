from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from nx_mcp.drawing_intelligence import (
    AssociationClaim,
    CaptureDimension,
    CaptureDimensionEndpoint,
    CaptureEntity,
    CaptureRequiredTarget,
    CaptureValue,
    CaptureView,
    ReaderCapture,
    build_semantic_draft,
    compile_evidence_graph,
    link_reader_capture,
    resolve_evidence_graph,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions

ROOT = Path(__file__).resolve().parents[1]


def _capture(prefix: str, *, reverse_association: bool = False) -> ReaderCapture:
    front = f"{prefix}_FRONT_ENTITY"
    side = f"{prefix}_SIDE_ENTITY"
    association_entities = [front, side]
    if reverse_association:
        association_entities.reverse()

    return ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id=f"{prefix}_VF", kind="front"),
            CaptureView(id=f"{prefix}_VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id=front,
                view_id=f"{prefix}_VF",
                shape="circle",
            ),
            CaptureEntity(
                id=side,
                view_id=f"{prefix}_VS",
                shape="hidden_parallel",
            ),
        ],
        associations=[
            AssociationClaim(
                id=f"{prefix}_ASSOC",
                entity_ids=association_entities,
                source_ids=[f"{prefix}_SRC_ASSOC"],
            )
        ],
        values=[
            CaptureValue(
                id=f"{prefix}_DIA",
                entity_id=front,
                field="diameter",
                value=20,
                source_ids=[f"{prefix}_SRC_DIA"],
            ),
            CaptureValue(
                id=f"{prefix}_FIT",
                entity_id=front,
                field="fit",
                value="H7",
            ),
        ],
        dimensions=[
            CaptureDimension(
                id=f"{prefix}_Z40",
                value=40,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(role="overall_min"),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id=front,
                    ),
                ],
            )
        ],
        required_targets=[
            CaptureRequiredTarget(
                entity_id=front,
                field="centerline.z",
            )
        ],
    )


def test_identity_linker_feature_id_ignores_reader_local_entity_names():
    first = link_reader_capture(_capture("A"))
    second = link_reader_capture(_capture("TOTALLY_DIFFERENT"))

    first_ids = {item.feature_id for item in first.evidence.projections}
    second_ids = {item.feature_id for item in second.evidence.projections}

    assert len(first_ids) == 1
    assert first_ids == second_ids

    first_feature = next(iter(first_ids))
    assert first.evidence.direct_values[0].target.startswith(
        f"feature:{first_feature}."
    )
    assert first.evidence.dimensions[0].endpoints[1].target == (
        f"feature:{first_feature}.centerline.z"
    )


def test_identity_linker_association_order_does_not_change_feature_id():
    first = link_reader_capture(_capture("A", reverse_association=False))
    second = link_reader_capture(_capture("A", reverse_association=True))

    assert first.entity_to_feature == second.entity_to_feature
    assert {
        item.feature_id for item in first.evidence.projections
    } == {
        item.feature_id for item in second.evidence.projections
    }


def test_identity_linker_without_association_keeps_view_entities_separate():
    capture = _capture("A")
    capture.associations = []

    result = link_reader_capture(capture)

    assert result.report["physical_components"] == 2
    assert len(set(result.entity_to_feature.values())) == 2


def test_identity_linker_rejects_same_view_multi_entity_association_as_unresolved():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(id="E1", view_id="VF", shape="circle"),
            CaptureEntity(id="E2", view_id="VF", shape="circle"),
        ],
        associations=[
            AssociationClaim(
                id="A_BAD",
                entity_ids=["E1", "E2"],
                required_for_modeling=True,
            )
        ],
    )

    result = link_reader_capture(capture)

    assert result.report["physical_components"] == 2
    assert any(
        item["id"] == "U_ASSOC_A_BAD"
        and item["required_for_modeling"] is True
        for item in result.evidence.unresolved_evidence
    )


def test_identity_linker_identical_disconnected_components_fail_closed():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(id="E1", view_id="VF", shape="circle"),
            CaptureEntity(id="E2", view_id="VF", shape="circle"),
        ],
    )

    result = link_reader_capture(capture)

    assert result.report["identity_collisions"] == 1
    assert result.report["blocking_unresolved"] >= 1
    assert any(
        str(item.get("id", "")).startswith("U_IDENTITY_COLLISION_")
        for item in result.evidence.unresolved_evidence
    )


def test_identity_linker_dimension_axis_maps_entity_center_target_deterministically():
    capture = _capture("A")
    result = link_reader_capture(capture)
    feature_id = result.entity_to_feature["A_FRONT_ENTITY"]

    dimension = result.evidence.dimensions[0]
    assert dimension.axis == "Z"
    assert dimension.endpoints[1].target == (
        f"feature:{feature_id}.centerline.z"
    )


def test_identity_linker_output_passes_strict_evidence_schema():
    result = link_reader_capture(_capture("A"))

    # model_dump + model_validate exercises the public strict boundary.
    raw = result.evidence.model_dump(mode="json")
    validated = type(result.evidence).model_validate(raw)

    assert validated.schema_version == "1.0"
    assert validated.coordinate_system == "part_center_xy_bottom_z0"


def test_link_capture_cli_produces_strict_downstream_consumable_evidence(tmp_path: Path):
    capture = _capture("CLI")
    capture_path = tmp_path / "reader-capture.json"
    evidence_path = tmp_path / "drawing-evidence.json"
    capture_path.write_text(
        json.dumps(capture.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "link-capture",
            str(capture_path),
            str(evidence_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["written"] is True
    assert report["schema_valid"] is True
    assert report["capture_entities"] == 2
    assert report["physical_components"] == 1
    assert evidence_path.exists()

    from nx_mcp.drawing_intelligence import EvidenceGraph

    graph = EvidenceGraph.model_validate(
        json.loads(evidence_path.read_text(encoding="utf-8"))
    )
    compiled = compile_evidence_graph(graph)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)

    assert draft["features"]
    assert draft["dimension_closure"]["status"] in {
        "closed",
        "incomplete",
        "conflict",
    }


def test_link_capture_cli_feature_identity_is_local_id_independent(tmp_path: Path):
    feature_ids = []

    for prefix in ("FIRST", "SECOND_COMPLETELY_DIFFERENT"):
        capture = _capture(prefix)
        capture_path = tmp_path / f"{prefix}-capture.json"
        evidence_path = tmp_path / f"{prefix}-evidence.json"
        capture_path.write_text(
            json.dumps(capture.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "nx_mcp.drawing_intelligence",
                "link-capture",
                str(capture_path),
                str(evidence_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

        raw = json.loads(evidence_path.read_text(encoding="utf-8"))
        feature_ids.append(
            sorted({item["feature_id"] for item in raw["projections"]})
        )

    assert feature_ids[0] == feature_ids[1]


def test_link_capture_cli_refuses_in_place_overwrite(tmp_path: Path):
    capture = _capture("CLI")
    path = tmp_path / "reader-capture.json"
    path.write_text(
        json.dumps(capture.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "link-capture",
            str(path),
            str(path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["written"] is False
    assert path.exists()


def test_reader_capture_normalizes_string_observations():
    capture = ReaderCapture.model_validate(
        {
            "schema_version": "2.0",
            "coordinate_system": "part_center_xy_bottom_z0",
            "overall_dimensions": {
                "length_x": 40,
                "width_y": 32,
                "height_z": 66,
            },
            "views": [],
            "entities": [],
            "associations": [],
            "values": [],
            "dimensions": [],
            "datum_alignments": [],
            "required_targets": [],
            "observations": [
                "first prose observation",
                {"kind": "already_structured", "value": 1},
            ],
            "unresolved_evidence": [],
        }
    )

    assert capture.observations[0] == {
        "kind": "reader_observation",
        "text": "first prose observation",
        "capture_index": 0,
    }
    assert capture.observations[1] == {
        "kind": "already_structured",
        "value": 1,
    }


def test_identity_collision_placeholders_keep_disconnected_components_distinct():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(
                id="E_LEFT",
                view_id="VF",
                shape="hidden_parallel",
            ),
            CaptureEntity(
                id="E_RIGHT",
                view_id="VF",
                shape="hidden_parallel",
            ),
        ],
        dimensions=[
            CaptureDimension(
                id="D_SPACING",
                value=24,
                axis="X",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_LEFT",
                    ),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E_RIGHT",
                    ),
                ],
                required_for_modeling=True,
            )
        ],
        unresolved_evidence=[
            {
                "id": "U_PAIRING",
                "reason": "cross-view pairing is not uniquely established",
                "required_for_modeling": True,
            }
        ],
    )

    result = link_reader_capture(capture)

    left = result.entity_to_feature["E_LEFT"]
    right = result.entity_to_feature["E_RIGHT"]

    assert left != right
    assert left.endswith("_AMB_01")
    assert right.endswith("_AMB_02")
    assert result.report["identity_collisions"] == 1

    compiled = compile_evidence_graph(result.evidence)
    spacing = next(
        item for item in compiled.relations
        if item.id == "D_SPACING"
    )

    assert spacing.kind == "center_distance"
    assert len(spacing.targets) == 2
    assert spacing.targets[0] != spacing.targets[1]


def test_run02_shape_string_observations_collision_and_spacing_is_linkable(tmp_path: Path):
    capture = ReaderCapture.model_validate(
        {
            "schema_version": "2.0",
            "coordinate_system": "part_center_xy_bottom_z0",
            "overall_dimensions": {
                "length_x": 40,
                "width_y": 32,
                "height_z": 66,
            },
            "views": [
                {"id": "V_FRONT", "kind": "front"},
                {"id": "V_SIDE", "kind": "side"},
            ],
            "entities": [
                {
                    "id": "E_FRONT_05",
                    "view_id": "V_FRONT",
                    "shape": "hidden_parallel",
                    "required_for_modeling": True,
                },
                {
                    "id": "E_FRONT_06",
                    "view_id": "V_FRONT",
                    "shape": "hidden_parallel",
                    "required_for_modeling": True,
                },
            ],
            "associations": [],
            "values": [],
            "dimensions": [
                {
                    "id": "D_04",
                    "value": 24,
                    "axis": "X",
                    "endpoints": [
                        {
                            "role": "entity_center",
                            "entity_id": "E_FRONT_05",
                        },
                        {
                            "role": "entity_center",
                            "entity_id": "E_FRONT_06",
                        },
                    ],
                    "required_for_modeling": True,
                }
            ],
            "datum_alignments": [],
            "required_targets": [],
            "observations": [
                "Two hidden groups are visible in the front view."
            ],
            "unresolved_evidence": [
                {
                    "id": "U_05",
                    "reason": "the two candidates cannot be uniquely paired across views",
                    "required_for_modeling": True,
                }
            ],
        }
    )

    capture_path = tmp_path / "capture-run-02.json"
    evidence_path = tmp_path / "linked-run-02.json"
    capture_path.write_text(
        json.dumps(capture.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "link-capture",
            str(capture_path),
            str(evidence_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["written"] is True
    assert report["schema_valid"] is True
    assert report["identity_collisions"] == 1
    assert evidence_path.exists()
