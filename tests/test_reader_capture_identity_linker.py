from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

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
from nx_mcp.drawing_intelligence.capture import (
    CaptureUnresolvedEvidence,
    validate_reader_capture_contract,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions
from nx_mcp.drawing_intelligence.stability import compare_evidence_runs

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
                cross_view_disposition="associated",
            ),
            CaptureEntity(
                id=side,
                view_id=f"{prefix}_VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
            ),
        ],
        associations=[
            AssociationClaim(
                id=f"{prefix}_ASSOC",
                entity_ids=association_entities,
                basis=["projection_alignment", "matching_specification"],
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
                        basis="centerline",
                    ),
                ],
            )
        ],
        required_targets=[],
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
                    "cross_view_disposition": "unresolved",
                    "required_for_modeling": True,
                },
                {
                    "id": "E_FRONT_06",
                    "view_id": "V_FRONT",
                    "shape": "hidden_parallel",
                    "cross_view_disposition": "unresolved",
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
                            "basis": "centerline",
                        },
                        {
                            "role": "entity_center",
                            "entity_id": "E_FRONT_06",
                            "basis": "centerline",
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
                    "kind": "member_identity",
                    "reason": "the two candidates cannot be uniquely paired across views",
                    "entity_ids": ["E_FRONT_05", "E_FRONT_06"],
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


def test_identity_linker_canonicalizes_hole_diameter_alias():
    first = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="V_SIDE", kind="side")],
        entities=[
            CaptureEntity(
                id="E_SIDE_A",
                view_id="V_SIDE",
                shape="hidden_parallel",
            )
        ],
        values=[
            CaptureValue(
                id="S_DIA_A",
                entity_id="E_SIDE_A",
                field="hole_diameter",
                value=20,
            )
        ],
    )
    second = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="V_SIDE", kind="side")],
        entities=[
            CaptureEntity(
                id="E_SIDE_B",
                view_id="V_SIDE",
                shape="hidden_parallel",
            )
        ],
        values=[
            CaptureValue(
                id="S_DIA_B",
                entity_id="E_SIDE_B",
                field="diameter",
                value=20,
            )
        ],
    )

    linked_a = link_reader_capture(first)
    linked_b = link_reader_capture(second)

    assert set(linked_a.entity_to_feature.values()) == set(
        linked_b.entity_to_feature.values()
    )
    assert linked_a.evidence.direct_values[0].target.endswith(".diameter")
    assert linked_b.evidence.direct_values[0].target.endswith(".diameter")


def test_identity_linker_canonicalizes_thread_depth_alias():
    first = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="V_FRONT", kind="front")],
        entities=[
            CaptureEntity(
                id="E_THREAD_A",
                view_id="V_FRONT",
                shape="hidden_parallel",
            )
        ],
        values=[
            CaptureValue(
                id="S_THREAD_SPEC_A",
                entity_id="E_THREAD_A",
                field="thread_spec",
                value="M6",
            ),
            CaptureValue(
                id="S_DEPTH_A",
                entity_id="E_THREAD_A",
                field="depth",
                value=12,
            ),
        ],
    )
    second = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="V_FRONT", kind="front")],
        entities=[
            CaptureEntity(
                id="E_THREAD_B",
                view_id="V_FRONT",
                shape="hidden_parallel",
            )
        ],
        values=[
            CaptureValue(
                id="S_THREAD_SPEC_B",
                entity_id="E_THREAD_B",
                field="thread_spec",
                value="M6",
            ),
            CaptureValue(
                id="S_DEPTH_B",
                entity_id="E_THREAD_B",
                field="thread_depth",
                value=12,
            ),
        ],
    )

    linked_a = link_reader_capture(first)
    linked_b = link_reader_capture(second)

    assert set(linked_a.entity_to_feature.values()) == set(
        linked_b.entity_to_feature.values()
    )
    assert {
        item.target.rsplit(".", 1)[1]
        for item in linked_a.evidence.direct_values
    } == {"thread_spec", "thread_depth"}


def test_identity_linker_canonicalizes_edge_on_hole_profile_shape():
    first = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EFC", view_id="VF", shape="circle"),
            CaptureEntity(id="ESA", view_id="VS", shape="hidden_parallel"),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EFC", "ESA"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
        values=[
            CaptureValue(id="S1", entity_id="ESA", field="diameter", value=20)
        ],
    )
    second = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EFC2", view_id="VF", shape="circle"),
            CaptureEntity(id="ESB", view_id="VS", shape="profile"),
        ],
        associations=[
            AssociationClaim(
                id="A2",
                entity_ids=["EFC2", "ESB"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
        values=[
            CaptureValue(id="S2", entity_id="ESB", field="diameter", value=20)
        ],
    )

    linked_a = link_reader_capture(first)
    linked_b = link_reader_capture(second)

    assert set(linked_a.entity_to_feature.values()) == set(
        linked_b.entity_to_feature.values()
    )
    side_shapes_a = {
        item.shape
        for item in linked_a.evidence.projections
        if item.view_id == "VS"
    }
    side_shapes_b = {
        item.shape
        for item in linked_b.evidence.projections
        if item.view_id == "VS"
    }
    assert side_shapes_a == {"hidden_parallel"}
    assert side_shapes_b == {"hidden_parallel"}


def test_identity_linker_ignores_unreferenced_outer_profile():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="VS", kind="side")],
        entities=[
            CaptureEntity(id="E_PROFILE", view_id="VS", shape="profile"),
            CaptureEntity(id="E_HOLE", view_id="VS", shape="hidden_parallel"),
        ],
        values=[
            CaptureValue(
                id="S_HOLE",
                entity_id="E_HOLE",
                field="diameter",
                value=6.6,
            )
        ],
    )

    result = link_reader_capture(capture)

    assert "E_PROFILE" not in result.entity_to_feature
    assert "E_HOLE" in result.entity_to_feature
    assert result.report["ignored_orphan_profiles"] == 1
    assert all(
        item.source_ids[0] != "E_PROFILE"
        for item in result.evidence.projections
    )


def test_identity_linker_derives_formal_required_targets():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        views=[CaptureView(id="VF", kind="front")],
        entities=[
            CaptureEntity(id="E1", view_id="VF", shape="circle")
        ],
        values=[
            CaptureValue(
                id="S1",
                entity_id="E1",
                field="hole_diameter",
                value=20,
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=18,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(role="overall_max"),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E1",
                    ),
                ],
                required_for_modeling=True,
            )
        ],
        required_targets=[
            CaptureRequiredTarget(
                entity_id="E1",
                field="centerline",
            )
        ],
    )

    result = link_reader_capture(capture)
    feature_id = result.entity_to_feature["E1"]

    assert result.evidence.required_targets == [
        f"feature:{feature_id}.centerline.z",
        f"feature:{feature_id}.diameter",
    ]
    assert any(
        item.get("kind") == "reader_required_targets_advisory"
        for item in result.evidence.observations
    )


def test_reader_capture_rejects_unknown_top_level_and_nested_fields():
    with pytest.raises(ValidationError):
        ReaderCapture.model_validate(
            {
                "schema_version": "2.0",
                "coordinate_system": "part_center_xy_bottom_z0",
                "overall_dimensions": {
                    "length_x": 100,
                    "width_y": 50,
                    "height_z": 20,
                },
                "views": [],
                "entities": [],
                "associations": [],
                "values": [],
                "dimensions": [],
                "datum_alignments": [],
                "required_targets": [],
                "observations": [],
                "unresolved_evidence": [],
                "unexpected": 1,
            }
        )

    with pytest.raises(ValidationError):
        ReaderCapture.model_validate(
            {
                "schema_version": "2.0",
                "coordinate_system": "part_center_xy_bottom_z0",
                "overall_dimensions": {
                    "length_x": 100,
                    "width_y": 50,
                    "height_z": 20,
                    "unexpected": 1,
                },
                "views": [],
                "entities": [],
                "associations": [],
                "values": [],
                "dimensions": [],
                "datum_alignments": [],
                "required_targets": [],
                "observations": [],
                "unresolved_evidence": [],
            }
        )


def test_reader_capture_rejects_non_numeric_overall_scalar():
    with pytest.raises(ValidationError):
        ReaderCapture.model_validate(
            {
                "schema_version": "2.0",
                "coordinate_system": "part_center_xy_bottom_z0",
                "overall_dimensions": {
                    "length_x": 100,
                    "width_y": "50",
                    "height_z": 20,
                },
                "views": [],
                "entities": [],
                "associations": [],
                "values": [],
                "dimensions": [],
                "datum_alignments": [],
                "required_targets": [],
                "observations": [],
                "unresolved_evidence": [],
            }
        )


def test_current_capture_contract_rejects_legacy_value_alias_and_freeform_blocker():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="V1", shape="circle")],
        values=[
            CaptureValue(
                id="S1",
                entity_id="E1",
                field="hole_diameter",
                value=10,
            )
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                reason="modeling-critical ambiguity",
                required_for_modeling=True,
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any("non-canonical field" in item for item in errors)
    assert any("structured kind" in item for item in errors)


def _unresolved_capture(prefix: str, kind: str) -> ReaderCapture:
    entity_id = f"{prefix}_ENTITY"
    return ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id=f"{prefix}_VIEW", kind="front")],
        entities=[
            CaptureEntity(
                id=entity_id,
                view_id=f"{prefix}_VIEW",
                shape="hidden_parallel",
            )
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id=f"{prefix}_U",
                kind=kind,
                reason="wording may differ between runs",
                entity_ids=[entity_id],
                field="termination",
                required_for_modeling=True,
            )
        ],
    )


def test_structured_unresolved_is_stable_across_local_id_changes():
    first = link_reader_capture(
        _unresolved_capture("RUN_A", "termination")
    ).evidence
    second = link_reader_capture(
        _unresolved_capture("RUN_B", "termination")
    ).evidence

    report = compare_evidence_runs([first, second])

    assert report.stable is True
    assert report.unique_fingerprints == 1
    assert report.unresolved_semantic_drift == []


def test_targetless_unresolved_semantic_drift_changes_fingerprint():
    first = link_reader_capture(
        _unresolved_capture("RUN_A", "termination")
    ).evidence
    second = link_reader_capture(
        _unresolved_capture("RUN_B", "start_side")
    ).evidence

    report = compare_evidence_runs([first, second])

    assert report.stable is False
    assert report.unique_fingerprints == 2
    assert report.unresolved_semantic_drift
    assert "unresolved_semantics" in report.changed_sections[2]


def test_check_capture_cli_is_authoritative_contract_gate(tmp_path: Path):
    valid = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="V1", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="V1", shape="circle")],
        values=[
            CaptureValue(
                id="S1",
                entity_id="E1",
                field="diameter",
                value=10,
            )
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                kind="termination",
                reason="termination is not directly established",
                entity_ids=["E1"],
                field="termination",
                required_for_modeling=True,
            )
        ],
    )
    valid_path = tmp_path / "valid-capture.json"
    valid_path.write_text(
        json.dumps(valid.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "check-capture",
            str(valid_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["schema_valid"] is True
    assert report["contract_valid"] is True

    invalid = valid.model_dump(mode="json")
    invalid["values"][0]["field"] = "hole_diameter"
    invalid_path = tmp_path / "invalid-capture.json"
    invalid_path.write_text(
        json.dumps(invalid, ensure_ascii=False),
        encoding="utf-8",
    )

    failed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nx_mcp.drawing_intelligence",
            "check-capture",
            str(invalid_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert failed.returncode == 1
    failed_report = json.loads(failed.stdout)
    assert failed_report["schema_valid"] is True
    assert failed_report["contract_valid"] is False
    assert any(
        "non-canonical field" in item
        for item in failed_report["errors"]
    )


def test_production_capture_rejects_alignment_only_association_basis():
    common = dict(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EF", view_id="VF", shape="circle"),
            CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
        ],
    )

    with pytest.raises(ValidationError, match="identity-sufficient visual basis"):
        ReaderCapture(
            **common,
            associations=[
                AssociationClaim(
                    id="A_ALIGN_ONLY",
                    entity_ids=["EF", "ES"],
                    basis=["projection_alignment", "shared_centerline"],
                )
            ],
        )

    strong = ReaderCapture(
        **common,
        associations=[
            AssociationClaim(
                id="A_STRONG",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
    )
    result = link_reader_capture(strong)
    assert result.report["physical_components"] == 1
    assert result.report["rejected_associations"] == 0

def test_current_capture_contract_requires_entity_center_visual_basis():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[CaptureView(id="VF", kind="front")],
        entities=[CaptureEntity(id="E1", view_id="VF", shape="circle")],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=10,
                axis="Z",
                endpoints=[
                    CaptureDimensionEndpoint(role="overall_min"),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="E1",
                    ),
                ],
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)
    assert any("requires centerline/center_mark/explicit_midline basis" in item for item in errors)

    capture.dimensions[0].endpoints[1].basis = "center_mark"
    assert validate_reader_capture_contract(capture) == []


def test_identity_linker_collapses_equivalent_cross_view_direct_writers():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EF", view_id="VF", shape="circle"),
            CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
        values=[
            CaptureValue(
                id="VF_DIA",
                entity_id="EF",
                field="diameter",
                value=10,
                source_ids=["SRC_FRONT"],
            ),
            CaptureValue(
                id="VS_DIA",
                entity_id="ES",
                field="diameter",
                value=10,
                source_ids=["SRC_SIDE"],
            ),
        ],
    )

    result = link_reader_capture(capture)

    diameter = [
        item
        for item in result.evidence.direct_values
        if item.target.endswith(".diameter")
    ]
    assert len(diameter) == 1
    assert diameter[0].value == 10
    assert diameter[0].id.startswith("L_DIRECT_")
    assert diameter[0].source_ids == [
        "VF_DIA",
        "SRC_FRONT",
        "VS_DIA",
        "SRC_SIDE",
    ]

    compiled = compile_evidence_graph(result.evidence)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)
    assert draft["features"]


def test_identity_linker_does_not_collapse_conflicting_direct_values():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EF", view_id="VF", shape="circle"),
            CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
        values=[
            CaptureValue(
                id="VF_DIA",
                entity_id="EF",
                field="diameter",
                value=10,
            ),
            CaptureValue(
                id="VS_DIA",
                entity_id="ES",
                field="diameter",
                value=11,
            ),
        ],
    )

    result = link_reader_capture(capture)

    diameter = [
        item
        for item in result.evidence.direct_values
        if item.target.endswith(".diameter")
    ]
    assert diameter == []

    conflicts = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("kind") == "direct_value_conflict"
    ]
    assert len(conflicts) == 1
    assert conflicts[0]["required_for_modeling"] is True
    assert conflicts[0]["candidates"] == [
        {"value": 10, "semantic": None},
        {"value": 11, "semantic": None},
    ]

    compiled = compile_evidence_graph(result.evidence)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)
    assert draft["dimension_closure"]["status"] == "incomplete"


def test_identity_linker_does_not_collapse_explicit_semantic_disagreement():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(id="EF", view_id="VF", shape="circle"),
            CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
        values=[
            CaptureValue(
                id="VF_DIA",
                entity_id="EF",
                field="diameter",
                value=10,
                semantic="diameter",
            ),
            CaptureValue(
                id="VS_DIA",
                entity_id="ES",
                field="diameter",
                value=10,
                semantic="feature_dimension",
            ),
        ],
    )

    result = link_reader_capture(capture)

    diameter = [
        item
        for item in result.evidence.direct_values
        if item.target.endswith(".diameter")
    ]
    assert diameter == []

    conflicts = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("kind") == "direct_value_conflict"
    ]
    assert len(conflicts) == 1
    assert conflicts[0]["candidates"] == [
        {"value": 10, "semantic": "diameter"},
        {"value": 10, "semantic": "feature_dimension"},
    ]


def test_stability_detects_different_direct_conflict_candidates():
    def build(second_value: int):
        capture = ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=100,
                width_y=50,
                height_z=20,
            ),
            views=[
                CaptureView(id="VF", kind="front"),
                CaptureView(id="VS", kind="side"),
            ],
            entities=[
                CaptureEntity(id="EF", view_id="VF", shape="circle"),
                CaptureEntity(id="ES", view_id="VS", shape="hidden_parallel"),
            ],
            associations=[
                AssociationClaim(
                    id="A1",
                    entity_ids=["EF", "ES"],
                    basis=["projection_alignment", "matching_specification"],
                )
            ],
            values=[
                CaptureValue(
                    id="V1",
                    entity_id="EF",
                    field="diameter",
                    value=10,
                ),
                CaptureValue(
                    id="V2",
                    entity_id="ES",
                    field="diameter",
                    value=second_value,
                ),
            ],
        )
        return link_reader_capture(capture).evidence

    report = compare_evidence_runs([build(11), build(12)])

    assert report.stable is False
    assert "unresolved_semantics" in report.changed_sections[2]
    assert report.unresolved_semantic_drift


def test_contract_requires_cross_view_disposition_for_modeling_entity():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VF",
                shape="circle",
            ),
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any("requires cross_view_disposition" in error for error in errors)


def test_contract_accepts_consistent_cross_view_dispositions():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id="EA",
                view_id="VF",
                shape="circle",
                cross_view_disposition="associated",
            ),
            CaptureEntity(
                id="EB",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
            ),
            CaptureEntity(
                id="EC",
                view_id="VF",
                shape="slot_edges",
                cross_view_disposition="single_view",
            ),
            CaptureEntity(
                id="ED",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="unresolved",
            ),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EA", "EB"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U1",
                kind="cross_view_identity",
                reason="candidate correspondence is not uniquely supported",
                entity_ids=["ED"],
            )
        ],
    )

    assert validate_reader_capture_contract(capture) == []


def test_contract_rejects_inconsistent_cross_view_disposition():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id="EA",
                view_id="VF",
                shape="circle",
                cross_view_disposition="single_view",
            ),
            CaptureEntity(
                id="EB",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
            ),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EA", "EB"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any("declares single_view" in error for error in errors)


def test_unresolved_dimension_endpoint_is_normalized_by_linker():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id="E1",
                view_id="VF",
                shape="hidden_parallel",
                cross_view_disposition="single_view",
            ),
        ],
        dimensions=[
            CaptureDimension(
                id="D1",
                value=16,
                axis="Y",
                endpoints=[
                    CaptureDimensionEndpoint(role="overall_max"),
                    CaptureDimensionEndpoint(
                        role="unresolved",
                        candidate_entity_ids=["E1"],
                    ),
                ],
                unresolved_reason="visible endpoint does not uniquely own a center",
            )
        ],
    )

    assert validate_reader_capture_contract(capture) == []

    result = link_reader_capture(capture)

    assert result.evidence.dimensions == []
    unresolved = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("kind") == "dimension_endpoint"
    ]
    assert len(unresolved) == 1
    assert unresolved[0]["capture_dimension_id"] == "D1"
    assert unresolved[0]["dimension_value"] == 16
    assert unresolved[0]["axis"] == "Y"
    assert unresolved[0]["required_for_modeling"] is True
    assert unresolved[0]["feature_ids"]


def test_contract_rejects_legacy_dimension_endpoint_unresolved_container():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        views=[CaptureView(id="VF", kind="front")],
        unresolved_evidence=[
            CaptureUnresolvedEvidence(
                id="U_DIM_OLD",
                kind="dimension_endpoint",
                reason="legacy split-container dimension ambiguity",
                dimension_value=16,
                axis="Y",
            )
        ],
    )

    errors = validate_reader_capture_contract(capture)

    assert any(
        "must be represented by dimensions[]" in error
        for error in errors
    )


def test_identity_linker_quarantines_dimension_whose_endpoints_collapse():
    capture = ReaderCapture(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=50,
            height_z=20,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=[
            CaptureEntity(
                id="EF",
                view_id="VF",
                shape="circle",
                cross_view_disposition="associated",
            ),
            CaptureEntity(
                id="ES",
                view_id="VS",
                shape="hidden_parallel",
                cross_view_disposition="associated",
            ),
        ],
        associations=[
            AssociationClaim(
                id="A1",
                entity_ids=["EF", "ES"],
                basis=["projection_alignment", "matching_specification"],
            )
        ],
        dimensions=[
            CaptureDimension(
                id="D_COLLAPSE",
                value=12,
                axis="X",
                endpoints=[
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="EF",
                        basis="centerline",
                    ),
                    CaptureDimensionEndpoint(
                        role="entity_center",
                        entity_id="ES",
                        basis="centerline",
                    ),
                ],
            )
        ],
    )

    assert validate_reader_capture_contract(capture) == []

    result = link_reader_capture(capture)

    assert result.evidence.dimensions == []
    collapsed = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("id") == "U_DIM_COLLAPSE_D_COLLAPSE"
    ]
    assert len(collapsed) == 1
    assert collapsed[0]["kind"] == "dimension_endpoint"
    assert collapsed[0]["dimension_value"] == 12
    assert collapsed[0]["axis"] == "X"
    assert collapsed[0]["required_for_modeling"] is True
    assert collapsed[0]["feature_ids"]
    assert len(collapsed[0]["feature_ids"]) == 1

    compiled = compile_evidence_graph(result.evidence)
    resolution = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, resolution)
    assert draft["dimension_closure"]["status"] == "incomplete"


def test_production_capture_rejects_overlapping_association_claims():
    associations = [
        AssociationClaim(
            id="A_LEFT",
            entity_ids=["E_FRONT_LEFT", "E_SIDE_GROUP"],
            basis=["projection_alignment", "matching_specification"],
        ),
        AssociationClaim(
            id="A_RIGHT",
            entity_ids=["E_FRONT_RIGHT", "E_SIDE_GROUP"],
            basis=["projection_alignment", "matching_specification"],
        ),
    ]
    with pytest.raises(ValidationError, match="appears in multiple associations"):
        ReaderCapture(
            overall_dimensions=OverallDimensions(
                length_x=40,
                width_y=32,
                height_z=10,
            ),
            views=[
                CaptureView(id="VF", kind="front"),
                CaptureView(id="VS", kind="side"),
            ],
            entities=[
                CaptureEntity(
                    id="E_FRONT_LEFT",
                    view_id="VF",
                    shape="hidden_parallel",
                    cross_view_disposition="associated",
                ),
                CaptureEntity(
                    id="E_FRONT_RIGHT",
                    view_id="VF",
                    shape="hidden_parallel",
                    cross_view_disposition="associated",
                ),
                CaptureEntity(
                    id="E_SIDE_GROUP",
                    view_id="VS",
                    shape="hidden_parallel",
                    cross_view_disposition="associated",
                ),
            ],
            associations=associations,
        )


def test_identity_linker_quarantines_legacy_transitive_same_view_collision():
    entities = [
        CaptureEntity(
            id="E_FRONT_LEFT",
            view_id="VF",
            shape="hidden_parallel",
            cross_view_disposition="associated",
        ),
        CaptureEntity(
            id="E_FRONT_RIGHT",
            view_id="VF",
            shape="hidden_parallel",
            cross_view_disposition="associated",
        ),
        CaptureEntity(
            id="E_SIDE_GROUP",
            view_id="VS",
            shape="hidden_parallel",
            cross_view_disposition="associated",
        ),
    ]
    associations = [
        AssociationClaim(
            id="A_LEFT",
            entity_ids=["E_FRONT_LEFT", "E_SIDE_GROUP"],
            basis=["projection_alignment", "matching_specification"],
        ),
        AssociationClaim(
            id="A_RIGHT",
            entity_ids=["E_FRONT_RIGHT", "E_SIDE_GROUP"],
            basis=["projection_alignment", "matching_specification"],
        ),
    ]
    capture = ReaderCapture.model_construct(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=10,
        ),
        views=[
            CaptureView(id="VF", kind="front"),
            CaptureView(id="VS", kind="side"),
        ],
        entities=entities,
        associations=associations,
        values=[],
        dimensions=[],
        datum_alignments=[],
        required_targets=[],
        observations=[],
        unresolved_evidence=[],
        schema_version="2.0",
        coordinate_system="part_center_xy_bottom_z0",
    )

    result = link_reader_capture(capture)

    assert result.report["physical_components"] == 3
    assert len(set(result.entity_to_feature.values())) == 3
    blockers = [
        item
        for item in result.evidence.unresolved_evidence
        if item.get("kind") == "association_structure"
    ]
    assert len(blockers) == 1
    assert "transitive association component" in blockers[0]["reason"]
