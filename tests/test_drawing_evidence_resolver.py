from nx_mcp.drawing_intelligence import (
    CoordinateFact,
    DirectValueEvidence,
    EvidenceGraph,
    OverallDimensions,
    RelationEvidence,
    build_semantic_draft,
    resolve_evidence_graph,
)


def _graph(*, facts=None, relations=None, required_targets=None):
    return EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_facts=facts or [],
        relations=relations or [],
        required_targets=required_targets or [],
    )


def test_mount_hole_max_edge_offset_resolves_to_8_in_local_coordinates():
    graph = _graph(
        relations=[
            RelationEvidence(
                id="S_MOUNT_Y",
                kind="edge_offset",
                axis="Y",
                from_side="max",
                value=24,
                targets=[
                    "feature:F_MOUNT_HOLES.explicit_centers.0.1",
                    "feature:F_MOUNT_HOLES.explicit_centers.1.1",
                ],
                source_ids=["ANN_MOUNT_Y_24"],
            )
        ]
    )

    result = resolve_evidence_graph(graph)

    assert result.ok
    assert result.values["feature:F_MOUNT_HOLES.explicit_centers.0.1"] == 8
    assert result.values["feature:F_MOUNT_HOLES.explicit_centers.1.1"] == 8


def test_bottom_datum_offset_resolves_main_hole_z_to_40():
    target = "feature:F_MAIN_HOLE.centerline.z"
    graph = _graph(
        relations=[
            RelationEvidence(
                id="S_MAIN_HOLE_Z",
                kind="edge_offset",
                axis="Z",
                from_side="min",
                value=40,
                targets=[target],
                source_ids=["ANN_BOTTOM_TO_HOLE_CENTER_40"],
            )
        ],
        required_targets=[target],
    )

    result = resolve_evidence_graph(graph)

    assert result.ok
    assert result.values[target] == 40


def test_alignment_propagates_a_known_coordinate_without_guessing():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = _graph(
        facts=[CoordinateFact(target=a, axis="X", value=0, source_ids=["ANN_A_X0"])],
        relations=[
            RelationEvidence(
                id="R_COAXIAL",
                kind="alignment",
                axis="X",
                targets=[a, b],
                source_ids=["CENTERLINE_SHARED"],
            )
        ],
        required_targets=[a, b],
    )

    result = resolve_evidence_graph(graph)

    assert result.ok
    assert result.values[b] == 0


def test_unsigned_center_spacing_stays_unresolved_instead_of_guessing_side():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = _graph(
        facts=[CoordinateFact(target=a, axis="X", value=10, source_ids=["ANN_A_X10"])],
        relations=[
            RelationEvidence(
                id="R_SPACING",
                kind="center_spacing",
                axis="X",
                value=24,
                targets=[a, b],
                source_ids=["ANN_CENTER_SPACING_24"],
            )
        ],
        required_targets=[b],
    )

    result = resolve_evidence_graph(graph)

    assert not result.ok
    assert b not in result.values
    assert result.unresolved[0]["id"] == "relation:R_SPACING"


def test_signed_center_spacing_can_be_resolved():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = _graph(
        facts=[CoordinateFact(target=a, axis="X", value=8, source_ids=["ANN_A_X"])],
        relations=[
            RelationEvidence(
                id="R_SPACING",
                kind="center_spacing",
                axis="X",
                value=24,
                direction=1,
                targets=[a, b],
                source_ids=["ANN_CENTER_SPACING_24"],
            )
        ],
        required_targets=[b],
    )

    result = resolve_evidence_graph(graph)

    assert result.ok
    assert result.values[b] == 32


def test_conflicting_writers_are_reported_not_overwritten():
    target = "feature:F_MAIN_HOLE.centerline.z"
    graph = _graph(
        facts=[CoordinateFact(target=target, axis="Z", value=48, source_ids=["BAD_DIRECT"])],
        relations=[
            RelationEvidence(
                id="S_MAIN_HOLE_Z",
                kind="edge_offset",
                axis="Z",
                from_side="min",
                value=40,
                targets=[target],
                source_ids=["ANN_BOTTOM_TO_HOLE_CENTER_40"],
            )
        ],
        required_targets=[target],
    )

    result = resolve_evidence_graph(graph)

    assert not result.ok
    assert result.values[target] == 48
    assert result.conflicts
    assert result.conflicts[0]["candidate"] == 40


def test_open_slot_upper_tangent_closes_bottom_and_dimension_closure():
    circle_center = "feature:F_CIRCLE.centerline.z"
    circle_diameter = "feature:F_CIRCLE.diameter"
    slot_bottom = "feature:F_SLOT.bottom_z"

    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        direct_values=[
            DirectValueEvidence(
                id="S_CIRCLE_Z",
                target=circle_center,
                value=40,
                semantic="center_position",
                source_ids=["test:center-z"],
            ),
            DirectValueEvidence(
                id="S_CIRCLE_D",
                target=circle_diameter,
                value=20,
                semantic="diameter",
                source_ids=["test:diameter"],
            ),
            DirectValueEvidence(
                id="S_SLOT_KIND",
                target="feature:F_SLOT.type",
                value="slot",
                semantic="feature_kind",
                source_ids=["test:slot"],
            ),
            DirectValueEvidence(
                id="S_SLOT_WIDTH",
                target="feature:F_SLOT.width",
                value=2,
                semantic="slot_width",
                source_ids=["test:slot"],
            ),
            DirectValueEvidence(
                id="S_SLOT_WIDTH_AXIS",
                target="feature:F_SLOT.width_axis",
                value="X",
                semantic="axis",
                source_ids=["test:slot"],
            ),
            DirectValueEvidence(
                id="S_SLOT_THROUGH_AXIS",
                target="feature:F_SLOT.through_axis",
                value="Y",
                semantic="axis",
                source_ids=["test:slot"],
            ),
            DirectValueEvidence(
                id="S_SLOT_TOP",
                target="feature:F_SLOT.top_z",
                value=66,
                semantic="position_dimension",
                source_ids=["test:overall-z"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_SLOT_BOTTOM",
                kind="upper_tangent",
                axis="Z",
                targets=[circle_center, slot_bottom],
                diameter_target=circle_diameter,
                source_ids=["test:topology-only"],
            )
        ],
        required_targets=[
            circle_center,
            circle_diameter,
            slot_bottom,
        ],
    )

    result = resolve_evidence_graph(graph)

    assert result.ok
    assert result.values[slot_bottom] == 50
    assert result.derivations[slot_bottom]["kind"] == "upper_tangent"

    draft = build_semantic_draft(graph, result)
    slot = next(item for item in draft["features"] if item["id"] == "F_SLOT")

    assert slot["bottom_z"] == 50
    assert slot["through_axis"] == "Y"
    assert draft["unresolved"] == []
    assert draft["dimension_conflicts"] == []
    assert draft["dimension_closure"]["status"] == "closed"


def test_resolution_is_deterministic_for_identical_input():
    target = "feature:F_MAIN_HOLE.centerline.z"
    graph = _graph(
        relations=[
            RelationEvidence(
                id="S_MAIN_HOLE_Z",
                kind="edge_offset",
                axis="Z",
                from_side="min",
                value=40,
                targets=[target],
            )
        ],
        required_targets=[target],
    )

    first = resolve_evidence_graph(graph).to_dict()
    second = resolve_evidence_graph(graph).to_dict()

    assert first == second
