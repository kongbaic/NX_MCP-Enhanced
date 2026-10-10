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


def test_center_distance_with_two_known_wrong_endpoints_reports_conflict():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = _graph(
        facts=[
            CoordinateFact(target=a, axis="X", value=0, source_ids=["ANN_A_X0"]),
            CoordinateFact(target=b, axis="X", value=10, source_ids=["ANN_B_X10"]),
        ],
        relations=[
            RelationEvidence(
                id="R_DISTANCE",
                kind="center_distance",
                axis="X",
                value=12,
                targets=[a, b],
                source_ids=["ANN_CENTER_DISTANCE_12"],
            )
        ],
        required_targets=[a, b],
    )

    result = resolve_evidence_graph(graph)

    assert not result.ok
    assert result.conflicts
    assert result.conflicts[0]["relation"] == "R_DISTANCE"
    assert result.conflicts[0]["expected_distance"] == 12
    assert result.conflicts[0]["actual_distance"] == 10


def test_upper_tangent_conflicting_direct_target_reports_conflict():
    center = "feature:F_CIRCLE.centerline.z"
    diameter = "feature:F_CIRCLE.diameter"
    tangent = "feature:F_SLOT.bottom_z"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=40,
            width_y=32,
            height_z=66,
        ),
        direct_values=[
            DirectValueEvidence(
                id="S_CENTER",
                target=center,
                value=40,
                semantic="center_position",
                source_ids=["ANN_CENTER_40"],
            ),
            DirectValueEvidence(
                id="S_DIAMETER",
                target=diameter,
                value=20,
                semantic="diameter",
                source_ids=["ANN_DIAMETER_20"],
            ),
            DirectValueEvidence(
                id="S_BAD_TANGENT",
                target=tangent,
                value=49,
                semantic="position_dimension",
                source_ids=["BAD_DIRECT_TANGENT"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_TANGENT",
                kind="upper_tangent",
                axis="Z",
                targets=[center, tangent],
                diameter_target=diameter,
                source_ids=["ANN_TANGENT"],
            )
        ],
        required_targets=[center, diameter, tangent],
    )

    result = resolve_evidence_graph(graph)

    assert not result.ok
    assert result.values[tangent] == 49
    assert result.conflicts
    assert result.conflicts[0]["target"] == tangent
    assert result.conflicts[0]["candidate"] == 50


def test_alignment_with_two_different_known_values_reports_conflict():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = _graph(
        facts=[
            CoordinateFact(target=a, axis="X", value=0, source_ids=["ANN_A_X0"]),
            CoordinateFact(target=b, axis="X", value=1, source_ids=["ANN_B_X1"]),
        ],
        relations=[
            RelationEvidence(
                id="R_ALIGNMENT",
                kind="alignment",
                axis="X",
                targets=[a, b],
                source_ids=["SHARED_CENTERLINE"],
            )
        ],
        required_targets=[a, b],
    )

    result = resolve_evidence_graph(graph)

    assert not result.ok
    assert result.conflicts
    assert result.conflicts[0]["target"] == b
    assert result.conflicts[0]["existing"] == 1
    assert result.conflicts[0]["candidate"] == 0



def test_midpoint_relation_derives_center_from_two_boundaries():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_TEST.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=100, width_y=40, height_z=20),
        direct_facts=[
            CoordinateFact(target=left, axis="X", value=20),
            CoordinateFact(target=right, axis="X", value=60),
        ],
        relations=[
            RelationEvidence(
                id="R_MID",
                kind="midpoint",
                axis="X",
                targets=[left, center, right],
                required_for_modeling=False,
            )
        ],
    )
    result = resolve_evidence_graph(graph)
    assert result.values[center] == 40.0
    assert result.derivations[center]["op"] == "mean"
    assert result.ok


def test_midpoint_relation_back_solves_opposite_boundary():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_TEST.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=100, width_y=40, height_z=20),
        direct_facts=[
            CoordinateFact(target=left, axis="X", value=20),
            CoordinateFact(target=center, axis="X", value=40),
        ],
        relations=[
            RelationEvidence(
                id="R_MID",
                kind="midpoint",
                axis="X",
                targets=[left, center, right],
            )
        ],
        required_targets=[right],
    )
    result = resolve_evidence_graph(graph)
    assert result.values[right] == 60.0
    assert result.derivations[right]["op"] == "reflect"
    assert result.ok


def test_midpoint_relation_reports_conflicting_known_center():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_TEST.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=100, width_y=40, height_z=20),
        direct_facts=[
            CoordinateFact(target=left, axis="X", value=20),
            CoordinateFact(target=center, axis="X", value=41),
            CoordinateFact(target=right, axis="X", value=60),
        ],
        relations=[
            RelationEvidence(
                id="R_MID",
                kind="midpoint",
                axis="X",
                targets=[left, center, right],
            )
        ],
    )
    result = resolve_evidence_graph(graph)
    assert result.conflicts[0]["kind"] == "midpoint"
    assert result.conflicts[0]["expected_midpoint"] == 40.0
    assert result.conflicts[0]["actual_midpoint"] == 41.0
    assert not result.ok


def test_midpoint_relation_with_one_known_target_does_not_guess():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_TEST.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=100, width_y=40, height_z=20),
        direct_facts=[CoordinateFact(target=left, axis="X", value=20)],
        relations=[
            RelationEvidence(
                id="R_MID",
                kind="midpoint",
                axis="X",
                targets=[left, center, right],
                required_for_modeling=False,
            )
        ],
    )
    result = resolve_evidence_graph(graph)
    assert center not in result.values
    assert right not in result.values
    assert result.conflicts == []
    assert result.ok


def test_centered_span_solves_boundaries_from_known_midpoint_and_width():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_TEST.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_facts=[
            CoordinateFact(
                target=center,
                axis="X",
                value=50,
                source_ids=["CENTER"],
            )
        ],
        relations=[
            RelationEvidence(
                id="R_CENTERED_SPAN",
                kind="centered_span",
                axis="X",
                value=20,
                direction=1,
                targets=[left, center, right],
                required_for_modeling=False,
            )
        ],
        required_targets=[left, right],
    )

    result = resolve_evidence_graph(graph)

    assert result.values[left] == 40.0
    assert result.values[center] == 50.0
    assert result.values[right] == 60.0
    assert result.ok


def test_centered_span_without_direction_does_not_guess_two_unknown_sides():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_TEST.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_facts=[CoordinateFact(target=center, axis="X", value=50)],
        relations=[
            RelationEvidence(
                id="R_CENTERED_SPAN",
                kind="centered_span",
                axis="X",
                value=20,
                targets=[left, center, right],
                required_for_modeling=False,
            )
        ],
    )

    result = resolve_evidence_graph(graph)

    assert left not in result.values
    assert right not in result.values
    assert result.conflicts == []
    assert result.ok


def test_centered_span_can_reflect_opposite_side_without_direction():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_TEST.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_facts=[
            CoordinateFact(target=left, axis="X", value=40),
            CoordinateFact(target=center, axis="X", value=50),
        ],
        relations=[
            RelationEvidence(
                id="R_CENTERED_SPAN",
                kind="centered_span",
                axis="X",
                value=20,
                targets=[left, center, right],
                required_for_modeling=False,
            )
        ],
        required_targets=[right],
    )

    result = resolve_evidence_graph(graph)

    assert result.values[right] == 60.0
    assert result.ok


def test_centered_span_reports_width_conflict():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_TEST.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_facts=[
            CoordinateFact(target=left, axis="X", value=35),
            CoordinateFact(target=center, axis="X", value=50),
            CoordinateFact(target=right, axis="X", value=60),
        ],
        relations=[
            RelationEvidence(
                id="R_CENTERED_SPAN",
                kind="centered_span",
                axis="X",
                value=20,
                direction=1,
                targets=[left, center, right],
            )
        ],
    )

    result = resolve_evidence_graph(graph)

    assert any(
        item.get("kind") == "centered_span"
        and item.get("expected_distance") == 20.0
        and item.get("actual_distance") == 25.0
        for item in result.conflicts
    )
    assert not result.ok



def test_signed_distances_reject_opposite_known_endpoint_orientation():
    """Existing coordinates must not bypass a signed constraint."""
    from nx_mcp.drawing_intelligence.evidence import CoordinateFact

    a = "feature:F_A.centerline.y"
    b = "feature:F_B.centerline.y"
    for kind in ("center_spacing", "center_distance", "coordinate_distance"):
        for sign, first, second in ((1, 24, 8), (-1, 8, 24)):
            graph = _graph(
                facts=[
                    CoordinateFact(target=a, axis="Y", value=first,
                                   source_ids=["datum:a"]),
                    CoordinateFact(target=b, axis="Y", value=second,
                                   source_ids=["datum:b"]),
                ],
                relations=[
                    RelationEvidence(
                        id="R_SIGNED",
                        kind=kind,
                        axis="Y",
                        value=16,
                        direction=sign,
                        targets=[a, b],
                        source_ids=["dimension:16"],
                    )
                ],
                required_targets=[a, b],
            )
            result = resolve_evidence_graph(graph)
            assert not result.ok
            assert len(result.conflicts) == 1
            conflict = result.conflicts[0]
            assert conflict["relation"] == "R_SIGNED"
            assert conflict["expected_distance"] == 16
            assert conflict["actual_distance"] == 16
            assert conflict["expected_signed_distance"] == sign * 16
            assert conflict["actual_signed_distance"] == -sign * 16
            assert result.values[a] == first
            assert result.values[b] == second


def test_signed_distances_accept_consistent_known_endpoints_without_regression():
    from nx_mcp.drawing_intelligence.evidence import CoordinateFact

    a = "feature:F_A.centerline.y"
    b = "feature:F_B.centerline.y"
    for kind in ("center_spacing", "center_distance", "coordinate_distance"):
        for sign, first, second in ((1, 8, 24), (-1, 24, 8)):
            graph = _graph(
                facts=[
                    CoordinateFact(target=a, axis="Y", value=first,
                                   source_ids=["datum:a"]),
                    CoordinateFact(target=b, axis="Y", value=second,
                                   source_ids=["datum:b"]),
                ],
                relations=[
                    RelationEvidence(
                        id="R_SIGNED",
                        kind=kind,
                        axis="Y",
                        value=16,
                        direction=sign,
                        targets=[a, b],
                        source_ids=["dimension:16"],
                    )
                ],
                required_targets=[a, b],
            )
            result = resolve_evidence_graph(graph)
            assert result.ok
            assert result.conflicts == []
            assert result.values[a] == first
            assert result.values[b] == second


def test_unsigned_distance_remains_direction_agnostic():
    from nx_mcp.drawing_intelligence.evidence import CoordinateFact

    a = "feature:F_A.centerline.y"
    b = "feature:F_B.centerline.y"
    graph = _graph(
        facts=[
            CoordinateFact(target=a, axis="Y", value=24, source_ids=["datum:a"]),
            CoordinateFact(target=b, axis="Y", value=8, source_ids=["datum:b"]),
        ],
        relations=[
            RelationEvidence(
                id="R_UNSIGNED",
                kind="coordinate_distance",
                axis="Y",
                value=16,
                direction=None,
                targets=[a, b],
                source_ids=["dimension:16"],
            )
        ],
        required_targets=[a, b],
    )
    result = resolve_evidence_graph(graph)
    assert result.ok
    assert result.conflicts == []



def test_centered_span_with_known_endpoints_rejects_reversed_direction():
    from nx_mcp.drawing_intelligence.evidence import CoordinateFact

    left = "feature:F_LEFT.boundary.y"
    mid = "constraints.span_centers.C_SIGNED.y"
    right = "feature:F_RIGHT.boundary.y"
    for direction, first, last in ((1, 24, 8), (-1, 8, 24)):
        graph = _graph(
            facts=[
                CoordinateFact(target=left, axis="Y", value=first),
                CoordinateFact(target=right, axis="Y", value=last),
            ],
            relations=[
                RelationEvidence(
                    id="R_SIGNED_CENTERED_SPAN",
                    kind="centered_span",
                    axis="Y",
                    value=16,
                    direction=direction,
                    targets=[left, mid, right],
                    source_ids=["witness:dimension:16"],
                )
            ],
        )
        result = resolve_evidence_graph(graph)
        assert not result.ok
        assert len(result.conflicts) == 1
        assert result.conflicts[0]["expected_signed_distance"] == direction * 16
        assert result.conflicts[0]["actual_signed_distance"] == -direction * 16
        assert result.values[mid] == 16


def test_centered_span_signed_orientation_accepts_consistent_and_unsigned():
    from nx_mcp.drawing_intelligence.evidence import CoordinateFact

    left = "feature:F_LEFT.boundary.y"
    mid = "constraints.span_centers.C_SIGNED.y"
    right = "feature:F_RIGHT.boundary.y"
    for direction, first, last in ((1, 8, 24), (-1, 24, 8), (None, 24, 8)):
        graph = _graph(
            facts=[
                CoordinateFact(target=left, axis="Y", value=first),
                CoordinateFact(target=right, axis="Y", value=last),
            ],
            relations=[
                RelationEvidence(
                    id="R_SIGNED_CENTERED_SPAN",
                    kind="centered_span",
                    axis="Y",
                    value=16,
                    direction=direction,
                    targets=[left, mid, right],
                )
            ],
        )
        result = resolve_evidence_graph(graph)
        assert result.ok
        assert result.conflicts == []
        assert result.values[mid] == 16


def test_centered_span_reflection_cannot_hide_reversed_signed_orientation():
    from nx_mcp.drawing_intelligence.evidence import CoordinateFact

    left = "feature:F_LEFT.boundary.y"
    mid = "constraints.span_centers.C_SIGNED.y"
    right = "feature:F_RIGHT.boundary.y"
    graph = _graph(
        facts=[
            CoordinateFact(target=left, axis="Y", value=24),
            CoordinateFact(target=mid, axis="Y", value=16),
        ],
        relations=[
            RelationEvidence(
                id="R_SIGNED_CENTERED_SPAN",
                kind="centered_span",
                axis="Y",
                value=16,
                direction=1,
                targets=[left, mid, right],
            )
        ],
    )
    result = resolve_evidence_graph(graph)
    assert not result.ok
    assert result.conflicts[0]["expected_signed_distance"] == 16
    assert result.conflicts[0]["actual_signed_distance"] == -16
