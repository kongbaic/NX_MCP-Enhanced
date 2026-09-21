from __future__ import annotations

from nx_mcp.drawing_intelligence import (
    AssociationClaim,
    CaptureDimension,
    CaptureDimensionEndpoint,
    CaptureEntity,
    CaptureRequiredTarget,
    CaptureValue,
    CaptureView,
    ReaderCapture,
    link_reader_capture,
)
from nx_mcp.drawing_intelligence.evidence import OverallDimensions


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
