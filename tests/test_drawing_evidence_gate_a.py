from __future__ import annotations

import importlib.util
from pathlib import Path

from nx_mcp.drawing_intelligence import (
    DimensionEndpoint,
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    OverallDimensions,
    RelationEvidence,
    build_semantic_draft,
    resolve_evidence_graph,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "agent" / "nx-mcp-plan-runner" / "runner.py"
SPEC = importlib.util.spec_from_file_location("gate_a_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def _overall_values(length_x=40, width_y=32, height_z=66):
    return [
        DirectValueEvidence(
            id="S_OVERALL_X",
            target="overall_dimensions.length_x",
            value=length_x,
            source_ids=["ANN_OVERALL_X"],
        ),
        DirectValueEvidence(
            id="S_OVERALL_Y",
            target="overall_dimensions.width_y",
            value=width_y,
            source_ids=["ANN_OVERALL_Y"],
        ),
        DirectValueEvidence(
            id="S_OVERALL_Z",
            target="overall_dimensions.height_z",
            value=height_z,
            source_ids=["ANN_OVERALL_Z"],
        ),
    ]


def _rotational_rectangle_graph(*, omit_top=False):
    left = "feature:F_LEFT.boundary.x"
    right = "feature:F_RIGHT.boundary.x"
    bottom = "feature:F_BOTTOM.boundary.z"
    top = "feature:F_TOP.boundary.z"
    direct = [
        *_overall_values(length_x=100, width_y=100, height_z=60),
        DirectValueEvidence(id="LEFT", target=left, value=20),
        DirectValueEvidence(id="RIGHT", target=right, value=80),
        DirectValueEvidence(id="BOTTOM", target=bottom, value=0),
    ]
    if not omit_top:
        direct.append(DirectValueEvidence(id="TOP", target=top, value=60))

    return EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=100,
            height_z=60,
        ),
        direct_values=direct,
        observations=[
            {
                "kind": "hybrid_rotational_profile_topology_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "region_id": "R1",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "component_index": 0,
                        "edges": [
                            {
                                "ref": "LEFT",
                                "profile_entity_id": "E_LEFT",
                                "physical_feature_id": "F_LEFT",
                                "constant_axis": "X",
                                "boundary_target": left,
                            },
                            {
                                "ref": "RIGHT",
                                "profile_entity_id": "E_RIGHT",
                                "physical_feature_id": "F_RIGHT",
                                "constant_axis": "X",
                                "boundary_target": right,
                            },
                            {
                                "ref": "BOTTOM",
                                "profile_entity_id": "E_BOTTOM",
                                "physical_feature_id": "F_BOTTOM",
                                "constant_axis": "Z",
                                "boundary_target": bottom,
                            },
                            {
                                "ref": "TOP",
                                "profile_entity_id": "E_TOP",
                                "physical_feature_id": "F_TOP",
                                "constant_axis": "Z",
                                "boundary_target": top,
                            },
                        ],
                        "junctions": [
                            ["LEFT", "BOTTOM"],
                            ["BOTTOM", "RIGHT"],
                            ["RIGHT", "TOP"],
                            ["TOP", "LEFT"],
                        ],
                        "source_ids": ["structural:R1:rotation"],
                        "basis": (
                            "established_rotational_symmetry_plus_"
                            "structural_profile_connectivity"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        ],
    )


def test_resolved_rotational_silhouette_materializes_max_radial_meridian():
    graph = _rotational_rectangle_graph()
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["dimension_closure"] == {"status": "closed"}
    assert draft["profile"]["plane"] == "XZ"
    assert draft["profile"]["rotation_axis"] == "Z"
    assert draft["profile"]["topology"] == "closed_polygon"
    segments = draft["profile"]["segments"]
    assert len(segments) == 4

    points = {
        (segment["x1"], segment["z1"])
        for segment in segments
    } | {
        (segment["x2"], segment["z2"])
        for segment in segments
    }
    assert points == {
        (0.0, 0.0),
        (30.0, 0.0),
        (30.0, 60.0),
        (0.0, 60.0),
    }
    assert not [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
    ]
    assert all(
        item.get("solver") == "rotational_profile_solver"
        for item in draft["source_ledger"]
        if str(item.get("id", "")).startswith("ROTATIONAL_PROFILE_")
    )
    assert R.check_drawing_json(draft) == []


def test_rotational_profile_blocks_verified_non_orthogonal_primitive_not_consumed():
    cases = [
        (
            "line",
            (
                "verified_continuous_straight_raster_segment_"
                "between_structural_contacts"
            ),
            "hybrid:oblique-line:7",
        ),
        (
            "arc",
            (
                "verified_continuous_curved_raster_segment_"
                "between_structural_contacts"
            ),
            "hybrid:curve-boundary:7",
        ),
    ]

    for primitive_kind, primitive_basis, primitive_source in cases:
        graph = _rotational_rectangle_graph()
        fragment = {
            "id": f"P_{primitive_kind.upper()}",
            "region_ids": ["R1"],
            "view_kind": "front",
            "plane": "XZ",
            "rotation_axis": "Z",
            "supporting_physical_feature_ids": ["F_RIGHT", "F_TOP"],
            "supporting_physical_edges": [
                {
                    "physical_feature_id": "F_RIGHT",
                    "constant_axis": "X",
                    "boundary_target": "feature:F_RIGHT.boundary.x",
                },
                {
                    "physical_feature_id": "F_TOP",
                    "constant_axis": "Z",
                    "boundary_target": "feature:F_TOP.boundary.z",
                },
            ],
            "connection_kind": "non_orthogonal_profile_connection",
            "primitive_kind": primitive_kind,
            "primitive_kind_basis": primitive_basis,
            "source_ids": [primitive_source],
            "basis": "identity_linked_physical_oblique_profile_topology",
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
        graph.observations[0]["items"][0]["non_orthogonal_fragments"] = [
            fragment
        ]
        graph.observations.append(
            {
                "kind": (
                    "hybrid_physical_rotational_oblique_profile_"
                    "topology_ledger"
                ),
                "schema": "1.0",
                "items": [fragment],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        )

        result = resolve_evidence_graph(graph)
        draft = build_semantic_draft(graph, result)

        assert result.ok
        assert "profile" in draft
        blockers = [
            item
            for item in draft["unresolved"]
            if item.get("field") == "rotational_profile_primitive"
        ]
        assert len(blockers) == 1
        assert blockers[0]["metadata"]["primitive_kind"] == primitive_kind
        assert primitive_source in blockers[0]["source_ids"]
        assert blockers[0]["required_for_modeling"] is True
        assert draft["dimension_closure"] == {"status": "incomplete"}


def _rotational_rectangle_with_arc(*, radius=5.0):
    graph = _rotational_rectangle_graph()
    right_target = "feature:F_RIGHT.boundary.x"
    top_target = "feature:F_TOP.boundary.z"
    topology = graph.observations[0]["items"][0]
    for edge in topology["edges"]:
        if edge["ref"] == "RIGHT":
            edge["material_axis_direction"] = "negative"
            edge["background_axis_direction"] = "positive"
        elif edge["ref"] == "TOP":
            edge["material_axis_direction"] = "negative"
            edge["background_axis_direction"] = "positive"

    fragment = {
        "id": "PHYSICAL_ARC_TOP_RIGHT",
        "region_ids": ["R1"],
        "view_kind": "front",
        "plane": "XZ",
        "rotation_axis": "Z",
        "supporting_physical_feature_ids": ["F_RIGHT", "F_TOP"],
        "supporting_physical_edges": [
            {
                "physical_feature_id": "F_RIGHT",
                "constant_axis": "X",
                "boundary_target": right_target,
                "material_axis_direction": "negative",
                "background_axis_direction": "positive",
            },
            {
                "physical_feature_id": "F_TOP",
                "constant_axis": "Z",
                "boundary_target": top_target,
                "material_axis_direction": "negative",
                "background_axis_direction": "positive",
            },
        ],
        "connection_kind": "non_orthogonal_profile_connection",
        "primitive_kind": "arc",
        "primitive_kind_basis": (
            "verified_continuous_curved_raster_segment_"
            "between_structural_contacts"
        ),
        "source_ids": ["hybrid:curve-boundary:7"],
        "basis": "identity_linked_physical_oblique_profile_topology",
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_topology_only": True,
    }
    topology["non_orthogonal_fragments"] = [fragment]
    graph.observations.append(
        {
            "kind": (
                "hybrid_physical_rotational_oblique_profile_"
                "topology_ledger"
            ),
            "schema": "1.0",
            "items": [fragment],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        }
    )

    radius_target = (
        "constraints.profile_arc_radii."
        "PHYSICAL_ARC_TOP_RIGHT.radius"
    )
    graph.direct_values.append(
        DirectValueEvidence(
            id="ARC_RADIUS",
            target=radius_target,
            value=radius,
            semantic="radius",
            source_ids=[
                "hybrid:whole:7",
                "hybrid:curve-boundary:7",
            ],
        )
    )
    graph.required_targets.append(radius_target)
    return graph


def test_rotational_profile_materializes_verified_engineering_arc():
    graph = _rotational_rectangle_with_arc(radius=5.0)
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["dimension_closure"] == {"status": "closed"}
    arcs = [
        segment
        for segment in draft["profile"]["segments"]
        if segment["type"] == "arc"
    ]
    assert len(arcs) == 1
    assert arcs[0]["center"] == {"x": 25.0, "z": 55.0}
    assert arcs[0]["radius"] == 5.0
    assert arcs[0]["start_angle"] == 0.0
    assert arcs[0]["end_angle"] == 90.0

    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile_primitive"
    ]
    assert blockers == []

    arc_sources = [
        item
        for item in draft["source_ledger"]
        if item.get("target", "").startswith("profile.segments.")
        and item.get("solver") == "rotational_profile_arc_solver"
    ]
    assert arc_sources
    assert all(
        "hybrid:curve-boundary:7" in item["evidence"]
        for item in arc_sources
    )
    assert any(
        item["target"].endswith(".radius")
        and (
            "constraints.profile_arc_radii."
            "PHYSICAL_ARC_TOP_RIGHT.radius"
        )
        in item["source_targets"]
        for item in arc_sources
    )
    assert R.check_drawing_json(draft) == []

    dispatches, errors = R.resolve_drawing_capability_dispatches(draft)
    assert errors == []
    assert len(dispatches) == 1
    contracts = dispatches[0]["payload"]["operation_contracts"]
    assert len(contracts) == 1
    arc_operations = [
        operation
        for operation in contracts[0]["operations"]
        if operation["tool"] == "nx_sketch_arc"
    ]
    assert len(arc_operations) == 1
    assert arc_operations[0]["fixed_args"] == {
        "center": {"x": 25.0, "y": 55.0},
        "radius": 5.0,
        "start_angle": 0.0,
        "end_angle": 90.0,
    }
    assert arc_operations[0]["requires"] == ["sketch_id"]


def test_rotational_profile_keeps_arc_blocking_when_radius_does_not_fit():
    graph = _rotational_rectangle_with_arc(radius=40.0)
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert all(
        segment["type"] == "line"
        for segment in draft["profile"]["segments"]
    )
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile_primitive"
    ]
    assert len(blockers) == 1
    assert blockers[0]["metadata"]["primitive_kind"] == "arc"
    assert blockers[0]["required_for_modeling"] is True
    assert draft["dimension_closure"] == {"status": "incomplete"}


def test_resolved_annular_rotational_meridian_materializes_without_axis_closure():
    inner = "feature:F_INNER.boundary.x"
    outer = "feature:F_OUTER.boundary.x"
    bottom = "feature:F_BOTTOM.boundary.z"
    top = "feature:F_TOP.boundary.z"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=100,
            height_z=60,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=100, height_z=60),
            DirectValueEvidence(id="INNER", target=inner, value=70),
            DirectValueEvidence(id="OUTER", target=outer, value=80),
            DirectValueEvidence(id="BOTTOM", target=bottom, value=0),
            DirectValueEvidence(id="TOP", target=top, value=60),
        ],
        observations=[
            {
                "kind": "hybrid_rotational_profile_topology_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "region_id": "R1",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "component_index": 0,
                        "edges": [
                            {
                                "ref": "INNER",
                                "profile_entity_id": "E_INNER",
                                "physical_feature_id": "F_INNER",
                                "constant_axis": "X",
                                "boundary_target": inner,
                            },
                            {
                                "ref": "OUTER",
                                "profile_entity_id": "E_OUTER",
                                "physical_feature_id": "F_OUTER",
                                "constant_axis": "X",
                                "boundary_target": outer,
                            },
                            {
                                "ref": "BOTTOM",
                                "profile_entity_id": "E_BOTTOM",
                                "physical_feature_id": "F_BOTTOM",
                                "constant_axis": "Z",
                                "boundary_target": bottom,
                            },
                            {
                                "ref": "TOP",
                                "profile_entity_id": "E_TOP",
                                "physical_feature_id": "F_TOP",
                                "constant_axis": "Z",
                                "boundary_target": top,
                            },
                        ],
                        "junctions": [
                            ["INNER", "BOTTOM"],
                            ["BOTTOM", "OUTER"],
                            ["OUTER", "TOP"],
                            ["TOP", "INNER"],
                        ],
                        "source_ids": ["structural:R1:rotation"],
                        "basis": (
                            "established_rotational_symmetry_plus_"
                            "structural_profile_connectivity"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        ],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["dimension_closure"] == {"status": "closed"}
    assert draft["profile"]["plane"] == "XZ"
    assert draft["profile"]["rotation_axis"] == "Z"
    assert draft["profile"]["topology"] == "closed_polygon"

    segments = draft["profile"]["segments"]
    assert len(segments) == 4
    points = {
        (segment["x1"], segment["z1"])
        for segment in segments
    } | {
        (segment["x2"], segment["z2"])
        for segment in segments
    }
    assert points == {
        (20.0, 0.0),
        (30.0, 0.0),
        (30.0, 60.0),
        (20.0, 60.0),
    }
    assert all(point[0] > 0 for point in points)
    geometry, errors = R._rotational_profile_geometry(draft)
    assert errors == []
    assert geometry is not None
    assert geometry["representation"] == "canonical_rotational_profile"
    assert R.check_drawing_json(draft) == []


def _branched_rotational_material_graph(*, omit_inner_right_polarity=False):
    targets = {
        "LEFT": "feature:F_LEFT.boundary.x",
        "INNER_LEFT": "feature:F_INNER_LEFT.boundary.x",
        "INNER_RIGHT": "feature:F_INNER_RIGHT.boundary.x",
        "RIGHT": "feature:F_RIGHT.boundary.x",
        "BOTTOM": "feature:F_BOTTOM.boundary.z",
        "TOP": "feature:F_TOP.boundary.z",
    }
    raw_values = {
        "LEFT": 20,
        "INNER_LEFT": 45,
        "INNER_RIGHT": 55,
        "RIGHT": 80,
        "BOTTOM": 0,
        "TOP": 60,
    }
    material_directions = {
        "LEFT": "positive",
        "INNER_LEFT": "negative",
        "INNER_RIGHT": "positive",
        "RIGHT": "negative",
        "BOTTOM": "positive",
        "TOP": "negative",
    }
    edges = []
    for ref in (
        "LEFT",
        "INNER_LEFT",
        "INNER_RIGHT",
        "RIGHT",
        "BOTTOM",
        "TOP",
    ):
        axis = "X" if ref not in {"BOTTOM", "TOP"} else "Z"
        edge = {
            "ref": ref,
            "profile_entity_id": f"E_{ref}",
            "physical_feature_id": f"F_{ref}",
            "constant_axis": axis,
            "boundary_target": targets[ref],
        }
        if not (omit_inner_right_polarity and ref == "INNER_RIGHT"):
            edge["material_axis_direction"] = material_directions[ref]
            edge["background_axis_direction"] = (
                "negative"
                if material_directions[ref] == "positive"
                else "positive"
            )
        edges.append(edge)

    junctions = [
        [vertical, horizontal]
        for vertical in ("LEFT", "INNER_LEFT", "INNER_RIGHT", "RIGHT")
        for horizontal in ("BOTTOM", "TOP")
    ]
    return EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=100,
            height_z=60,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=100, height_z=60),
            *[
                DirectValueEvidence(
                    id=ref,
                    target=targets[ref],
                    value=value,
                )
                for ref, value in raw_values.items()
            ],
        ],
        observations=[
            {
                "kind": "hybrid_rotational_profile_topology_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "region_id": "PHYSICAL_BRANCH",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "component_index": 0,
                        "edges": edges,
                        "junctions": junctions,
                        "source_ids": ["structural:branched:rotation"],
                        "basis": (
                            "identity_linked_physical_rotational_profile_topology"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        ],
    )


def test_branched_rotational_topology_decomposes_material_away_from_void_gap():
    graph = _branched_rotational_material_graph()
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["dimension_closure"] == {"status": "closed"}
    assert draft["profile"]["plane"] == "XZ"
    assert draft["profile"]["rotation_axis"] == "Z"
    assert draft["profile"]["topology"] == "closed_polygon"

    points = {
        (segment["x1"], segment["z1"])
        for segment in draft["profile"]["segments"]
    } | {
        (segment["x2"], segment["z2"])
        for segment in draft["profile"]["segments"]
    }
    assert points == {
        (5.0, 0.0),
        (30.0, 0.0),
        (30.0, 60.0),
        (5.0, 60.0),
    }
    assert not [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
    ]
    assert R.check_drawing_json(draft) == []


def test_branched_rotational_topology_stays_blocked_without_complete_polarity():
    graph = _branched_rotational_material_graph(
        omit_inner_right_polarity=True,
    )
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert "profile" not in draft
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
        and item.get("required_for_modeling") is True
    ]
    assert len(blockers) == 1
    assert draft["dimension_closure"] == {"status": "incomplete"}


def _symmetric_tapered_annular_graph(
    *,
    include_oblique_pair=True,
    verified_straight_primitive=False,
    primitive_kind_basis=(
        "verified_continuous_straight_raster_segment_"
        "between_structural_contacts"
    ),
):
    hub_left = "feature:F_HUB_LEFT.boundary.x"
    hub_right = "feature:F_HUB_RIGHT.boundary.x"
    neck_left = "feature:F_NECK_LEFT.boundary.x"
    neck_right = "feature:F_NECK_RIGHT.boundary.x"
    inner_left = "feature:F_INNER_LEFT.boundary.x"
    z_bottom = "feature:F_Z_BOTTOM.boundary.z"
    z_flange = "feature:F_Z_FLANGE.boundary.z"
    z_top = "feature:F_Z_TOP.boundary.z"

    direct = [
        *_overall_values(length_x=300, width_y=300, height_z=75),
        DirectValueEvidence(id="HUB_L", target=hub_left, value=41.0),
        DirectValueEvidence(id="HUB_R", target=hub_right, value=259.0),
        DirectValueEvidence(id="NECK_L", target=neck_left, value=65.85),
        DirectValueEvidence(id="NECK_R", target=neck_right, value=234.15),
        DirectValueEvidence(id="INNER_L", target=inner_left, value=70.35),
        DirectValueEvidence(id="Z_BOTTOM", target=z_bottom, value=0.0),
        DirectValueEvidence(id="Z_TOP", target=z_top, value=75.0),
    ]
    dimensions = [
        DimensionObservation(
            id="D_HUB",
            value=218.0,
            axis="X",
            endpoints=[
                DimensionEndpoint(
                    role="profile_boundary",
                    target=hub_left,
                ),
                DimensionEndpoint(
                    role="profile_boundary",
                    target=hub_right,
                ),
            ],
            direction=1,
            source_ids=["dim:hub"],
        ),
        DimensionObservation(
            id="D_NECK",
            value=168.3,
            axis="X",
            endpoints=[
                DimensionEndpoint(
                    role="profile_boundary",
                    target=neck_left,
                ),
                DimensionEndpoint(
                    role="profile_boundary",
                    target=neck_right,
                ),
            ],
            direction=1,
            source_ids=["dim:neck"],
        ),
        DimensionObservation(
            id="D_WALL",
            value=4.5,
            axis="X",
            endpoints=[
                DimensionEndpoint(
                    role="profile_boundary",
                    target=neck_left,
                ),
                DimensionEndpoint(
                    role="profile_boundary",
                    target=inner_left,
                ),
            ],
            direction=1,
            source_ids=["dim:wall"],
        ),
    ]
    relations = [
        RelationEvidence(
            id="R_FLANGE",
            kind="edge_offset",
            axis="Z",
            targets=[z_flange],
            value=28.0,
            from_side="min",
            source_ids=["dim:flange"],
        ),
    ]

    fragments = []
    raw_oblique_items = []
    if include_oblique_pair:
        verified_edges = [
            {
                "physical_feature_id": "F_HUB",
                "constant_axis": "Z",
                "boundary_target": z_flange,
            },
            {
                "physical_feature_id": "F_NECK",
                "constant_axis": "X",
                "boundary_target": neck_left,
            },
        ]
        fragments = [
            {
                "id": "P_OBL_LEFT",
                "region_ids": ["R1", "R2"],
                "material_side_index": 1,
                "background_side_index": 0,
                "view_kind": "front",
                "plane": "XZ",
                "rotation_axis": "Z",
                "supporting_physical_feature_ids": (
                    ["F_HUB", "F_NECK"]
                    if verified_straight_primitive
                    else []
                ),
                "supporting_physical_edges": (
                    verified_edges
                    if verified_straight_primitive
                    else []
                ),
                "connection_kind": (
                    "non_orthogonal_profile_connection"
                    if verified_straight_primitive
                    else "exterior_non_orthogonal_boundary_fragment"
                ),
                **(
                    {
                        "primitive_kind": "line",
                        "primitive_kind_basis": primitive_kind_basis,
                    }
                    if verified_straight_primitive
                    else {}
                ),
                "source_ids": ["hybrid:oblique-line:0"],
                "basis": "identity_linked_physical_oblique_profile_topology",
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            },
            {
                "id": "P_OBL_RIGHT",
                "region_ids": ["R1", "R2"],
                "material_side_index": 1,
                "background_side_index": 0,
                "view_kind": "front",
                "plane": "XZ",
                "rotation_axis": "Z",
                "supporting_physical_feature_ids": (
                    ["F_HUB", "F_NECK"]
                    if verified_straight_primitive
                    else []
                ),
                "supporting_physical_edges": (
                    verified_edges
                    if verified_straight_primitive
                    else []
                ),
                "connection_kind": (
                    "non_orthogonal_profile_connection"
                    if verified_straight_primitive
                    else "exterior_non_orthogonal_boundary_fragment"
                ),
                **(
                    {
                        "primitive_kind": "line",
                        "primitive_kind_basis": primitive_kind_basis,
                    }
                    if verified_straight_primitive
                    else {}
                ),
                "source_ids": ["hybrid:oblique-line:1"],
                "basis": "identity_linked_physical_oblique_profile_topology",
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            },
        ]
        raw_oblique_items = [
            {
                "id": "OBL_LEFT",
                "region_id": "R1",
                "view_kind": "front",
                "plane": "XZ",
                "rotation_axis": "Z",
                "endpoints_px": [[438.0, 425.0], [470.0, 332.0]],
                "source_ids": ["hybrid:oblique-line:0"],
                "one_sided_boundary_candidate": True,
                "exterior_boundary_candidate": True,
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            },
            {
                "id": "OBL_RIGHT",
                "region_id": "R1",
                "view_kind": "front",
                "plane": "XZ",
                "rotation_axis": "Z",
                "endpoints_px": [[985.0, 331.0], [1017.0, 425.0]],
                "source_ids": ["hybrid:oblique-line:1"],
                "one_sided_boundary_candidate": True,
                "exterior_boundary_candidate": True,
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            },
        ]

    observations = [
        {
            "kind": "hybrid_rotational_profile_topology_ledger",
            "schema": "1.0",
            "items": [
                {
                    "region_id": "PHYSICAL_TAPER",
                    "region_ids": ["R1", "R2"],
                    "view_kind": "front",
                    "plane": "XZ",
                    "rotation_axis": "Z",
                    "component_index": 0,
                    "edges": [
                        {
                            "ref": "INNER",
                            "constant_axis": "X",
                            "boundary_target": inner_left,
                        },
                        {
                            "ref": "NECK",
                            "constant_axis": "X",
                            "boundary_target": neck_left,
                        },
                        {
                            "ref": "BOTTOM",
                            "constant_axis": "Z",
                            "boundary_target": z_bottom,
                        },
                        {
                            "ref": "FLANGE",
                            "constant_axis": "Z",
                            "boundary_target": z_flange,
                        },
                        {
                            "ref": "TOP",
                            "constant_axis": "Z",
                            "boundary_target": z_top,
                        },
                    ],
                    "junctions": [
                        ["INNER", "BOTTOM"],
                        ["INNER", "FLANGE"],
                        ["INNER", "TOP"],
                    ],
                    "non_orthogonal_fragments": fragments,
                    "source_ids": ["structural:R1:rotation"],
                    "basis": (
                        "identity_linked_physical_rotational_profile_topology"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                }
            ],
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        },
        {
            "kind": "hybrid_rotational_oblique_profile_candidate_ledger",
            "schema": "1.0",
            "items": raw_oblique_items,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_topology_only": True,
        },
    ]

    return EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=300,
            width_y=300,
            height_z=75,
        ),
        direct_values=direct,
        dimensions=dimensions,
        relations=relations,
        observations=observations,
    )


def _bilateral_straight_silhouette_observation(*, duplicate=False):
    record = {
        "id": "BILATERAL_STRAIGHT_SILHOUETTE_TEST",
        "view_kind": "front",
        "plane": "XZ",
        "rotation_axis": "Z",
        "radial_axis": "X",
        "negative_side_source_ids": ["hybrid:oblique-line:0"],
        "positive_side_source_ids": ["hybrid:oblique-line:1"],
        "source_ids": [
            "hybrid:oblique-line:0",
            "hybrid:oblique-line:1",
            "hybrid:center-proof:left",
            "hybrid:center-proof:right",
        ],
        "primitive_kind": "line",
        "primitive_kind_basis": (
            "bilateral_mirrored_continuous_straight_exterior_silhouette"
        ),
        "basis": (
            "full_support_exterior_fragments_plus_"
            "independent_symmetric_span_midpoint"
        ),
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_topology_only": True,
    }
    items = [record]
    if duplicate:
        items.append({**record, "id": "BILATERAL_STRAIGHT_SILHOUETTE_DUPLICATE"})
    return {
        "kind": "hybrid_bilateral_rotational_straight_silhouette_ledger",
        "schema": "1.0",
        "items": items,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_topology_only": True,
    }


def test_symmetric_tapered_annular_profile_consumes_unique_bilateral_silhouette_ledger():
    graph = _symmetric_tapered_annular_graph()
    graph.observations.append(_bilateral_straight_silhouette_observation())
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["dimension_closure"] == {"status": "closed"}
    assert draft["profile"]["plane"] == "XZ"
    assert draft["profile"]["rotation_axis"] == "Z"
    evidence = {
        value
        for item in draft["source_ledger"]
        if str(item.get("target", "")).startswith("profile.")
        for value in item.get("evidence", [])
    }
    assert "BILATERAL_STRAIGHT_SILHOUETTE_TEST" in evidence
    assert not [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
    ]


def test_symmetric_tapered_annular_profile_rejects_ambiguous_bilateral_silhouette_ledger():
    graph = _symmetric_tapered_annular_graph()
    graph.observations.append(
        _bilateral_straight_silhouette_observation(duplicate=True)
    )
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert "profile" not in draft
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
        and item.get("required_for_modeling") is True
    ]
    assert len(blockers) == 1
    assert draft["dimension_closure"] == {"status": "incomplete"}


def _multilevel_tapered_annular_graph(*, ambiguous_oblique_transition=False):
    graph = _symmetric_tapered_annular_graph()
    graph.observations.append(_bilateral_straight_silhouette_observation())

    mid_left = "feature:F_MID_LEFT.boundary.x"
    mid_right = "feature:F_MID_RIGHT.boundary.x"
    z_step1 = "feature:F_Z_STEP1.boundary.z"
    z_step2 = "feature:F_Z_STEP2.boundary.z"
    taper_target = "constraints.profile_transitions.TAPER.z"

    graph.direct_values.extend(
        [
            DirectValueEvidence(id="MID_L", target=mid_left, value=54.0),
            DirectValueEvidence(id="MID_R", target=mid_right, value=246.0),
        ]
    )
    graph.dimensions.append(
        DimensionObservation(
            id="D_MID",
            value=192.0,
            axis="X",
            endpoints=[
                DimensionEndpoint(
                    role="profile_boundary",
                    target=mid_left,
                ),
                DimensionEndpoint(
                    role="profile_boundary",
                    target=mid_right,
                ),
            ],
            direction=1,
            source_ids=["dim:mid"],
        )
    )
    graph.relations.extend(
        [
            RelationEvidence(
                id="LPT_STEP1",
                kind="edge_offset",
                axis="Z",
                targets=[z_step1],
                value=3.0,
                from_side="min",
                source_ids=["dim:step1"],
                metadata={
                    "basis": "labeled_overall_to_profile_transition",
                    "labeled_target_id": "STEP1",
                },
            ),
            RelationEvidence(
                id="LPT_STEP2",
                kind="edge_offset",
                axis="Z",
                targets=[z_step2],
                value=12.0,
                from_side="min",
                source_ids=["dim:step2"],
                metadata={
                    "basis": "labeled_overall_to_profile_transition",
                    "labeled_target_id": "STEP2",
                },
            ),
            RelationEvidence(
                id="LPT_TAPER",
                kind="edge_offset",
                axis="Z",
                targets=[taper_target],
                value=28.0,
                from_side="min",
                source_ids=["dim:taper"],
                metadata={
                    "basis": "labeled_overall_to_profile_transition",
                    "labeled_target_id": "TAPER",
                },
            ),
        ]
    )

    topology = next(
        observation
        for observation in graph.observations
        if observation.get("kind") == "hybrid_rotational_profile_topology_ledger"
    )
    item = topology["items"][0]
    item["edges"].extend(
        [
            {
                "ref": "STEP1",
                "constant_axis": "Z",
                "boundary_target": z_step1,
            },
            {
                "ref": "STEP2",
                "constant_axis": "Z",
                "boundary_target": z_step2,
            },
        ]
    )

    transition_items = [
        {
            "target_id": "STEP1",
            "axis": "Z",
            "profile_refs": ["STEP1"],
            "profile_entity_keys": ["profile.step1"],
            "identity_kind": "physical_profile_boundary",
            "source_ids": ["transition:step1"],
            "basis": (
                "labeled_overall_offset_plus_unique_"
                "transition_level_profile_identity"
            ),
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "target_id": "STEP2",
            "axis": "Z",
            "profile_refs": ["STEP2"],
            "profile_entity_keys": ["profile.step2"],
            "identity_kind": "physical_profile_boundary",
            "source_ids": ["transition:step2"],
            "basis": (
                "labeled_overall_offset_plus_unique_"
                "transition_level_profile_identity"
            ),
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
        {
            "target_id": "TAPER",
            "axis": "Z",
            "profile_refs": [],
            "profile_entity_keys": [],
            "oblique_source_ids": [
                "hybrid:oblique-line:0",
                "hybrid:oblique-line:1",
            ],
            "identity_kind": "bilateral_oblique_transition_endpoint_level",
            "source_ids": [
                "transition:taper",
                "hybrid:oblique-line:0",
                "hybrid:oblique-line:1",
            ],
            "basis": (
                "labeled_overall_offset_plus_bilateral_"
                "oblique_endpoint_identity"
            ),
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        },
    ]
    if ambiguous_oblique_transition:
        transition_items.append(
            {
                **transition_items[-1],
                "source_ids": [
                    "transition:taper:duplicate",
                    "hybrid:oblique-line:0",
                    "hybrid:oblique-line:1",
                ],
            }
        )
    graph.observations.append(
        {
            "kind": "hybrid_labeled_profile_transition_boundary_ledger",
            "schema": "1.0",
            "items": transition_items,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        }
    )
    return graph


def _split_multilevel_tapered_annular_graph(*, same_region=True):
    graph = _multilevel_tapered_annular_graph()
    topology = next(
        observation
        for observation in graph.observations
        if observation.get("kind") == "hybrid_rotational_profile_topology_ledger"
    )
    primary = topology["items"][0]
    step2 = next(
        edge
        for edge in primary["edges"]
        if edge.get("ref") == "STEP2"
    )
    primary["edges"] = [
        edge
        for edge in primary["edges"]
        if edge.get("ref") != "STEP2"
    ]
    primary["component_index"] = 0
    primary.pop("non_orthogonal_fragments", None)

    companion = {
        "region_id": (
            primary["region_id"]
            if same_region
            else "INDEPENDENT_ROTATIONAL_REGION"
        ),
        "region_ids": list(primary.get("region_ids", [])),
        "view_kind": primary["view_kind"],
        "plane": primary["plane"],
        "rotation_axis": primary["rotation_axis"],
        "component_index": 1,
        "edges": [step2],
        "junctions": [],
        "source_ids": ["structural:companion-component"],
        "basis": "identity_linked_physical_rotational_profile_topology",
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_topology_only": True,
    }
    topology["items"].append(companion)
    return graph


def test_multilevel_tapered_profile_consumes_same_view_companion_components():
    graph = _split_multilevel_tapered_annular_graph()
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["dimension_closure"] == {"status": "closed"}
    assert draft["profile"]["plane"] == "XZ"
    assert len(draft["profile"]["segments"]) == 9
    assert not [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
    ]


def test_multilevel_tapered_profile_does_not_merge_independent_region_component():
    graph = _split_multilevel_tapered_annular_graph(same_region=False)
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert "profile" not in draft
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
        and item.get("required_for_modeling") is True
    ]
    assert len(blockers) == 2
    assert draft["dimension_closure"] == {"status": "incomplete"}


def test_multilevel_tapered_annular_profile_consumes_nested_radial_and_axial_levels():
    graph = _multilevel_tapered_annular_graph()
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["dimension_closure"] == {"status": "closed"}
    assert draft["profile"]["plane"] == "XZ"
    assert draft["profile"]["rotation_axis"] == "Z"

    segments = draft["profile"]["segments"]
    assert len(segments) == 9
    points = {
        (segment["x1"], segment["z1"])
        for segment in segments
    } | {
        (segment["x2"], segment["z2"])
        for segment in segments
    }
    assert points == {
        (79.65, 0.0),
        (150.0, 0.0),
        (150.0, 3.0),
        (109.0, 3.0),
        (109.0, 12.0),
        (96.0, 12.0),
        (96.0, 28.0),
        (84.15, 75.0),
        (79.65, 75.0),
    }

    geometry_evidence = {
        value
        for item in draft["source_ledger"]
        if str(item.get("target", "")).startswith("profile.")
        for value in item.get("evidence", [])
    }
    assert {"LPT_STEP1", "LPT_STEP2", "LPT_TAPER"} <= geometry_evidence
    assert all(
        item.get("solver") == "rotational_multilevel_taper_profile_solver"
        for item in draft["source_ledger"]
        if str(item.get("id", "")).startswith(
            "ROTATIONAL_MULTILEVEL_TAPER_PROFILE_"
        )
    )
    assert not [
        item
        for item in draft["unresolved"]
        if item.get("field") in {
            "rotational_profile",
            "profile_transition",
        }
    ]
    assert R.check_drawing_json(draft) == []


def test_multilevel_tapered_annular_profile_fails_closed_on_ambiguous_oblique_transition():
    graph = _multilevel_tapered_annular_graph(
        ambiguous_oblique_transition=True,
    )
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert "profile" not in draft
    assert draft["dimension_closure"] == {"status": "incomplete"}
    assert [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
        and item.get("required_for_modeling") is True
    ]


def test_symmetric_tapered_annular_profile_rejects_legacy_straight_basis():
    graph = _symmetric_tapered_annular_graph(
        verified_straight_primitive=True,
        primitive_kind_basis="explicit_straight_profile_semantics",
    )
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert "profile" not in draft
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
        and item.get("required_for_modeling") is True
    ]
    assert len(blockers) == 1
    assert draft["dimension_closure"] == {"status": "incomplete"}


def test_symmetric_tapered_annular_profile_materializes_only_with_verified_straight_primitive():
    graph = _symmetric_tapered_annular_graph(
        verified_straight_primitive=True,
    )
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["dimension_closure"] == {"status": "closed"}
    assert draft["profile"]["plane"] == "XZ"
    assert draft["profile"]["rotation_axis"] == "Z"
    assert draft["profile"]["topology"] == "closed_polygon"

    segments = draft["profile"]["segments"]
    assert len(segments) == 6
    points = {
        (segment["x1"], segment["z1"])
        for segment in segments
    } | {
        (segment["x2"], segment["z2"])
        for segment in segments
    }
    assert points == {
        (79.65, 0.0),
        (150.0, 0.0),
        (150.0, 28.0),
        (109.0, 28.0),
        (84.15, 75.0),
        (79.65, 75.0),
    }
    assert all(
        item.get("solver") == "rotational_taper_profile_solver"
        for item in draft["source_ledger"]
        if str(item.get("id", "")).startswith("ROTATIONAL_TAPER_PROFILE_")
    )
    assert not [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
    ]
    assert R.check_drawing_json(draft) == []


def test_symmetric_tapered_annular_profile_blocks_unresolved_exterior_fragments():
    graph = _symmetric_tapered_annular_graph()
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert "profile" not in draft
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
        and item.get("required_for_modeling") is True
    ]
    assert len(blockers) == 1
    assert draft["dimension_closure"] == {"status": "incomplete"}


def test_symmetric_tapered_annular_profile_requires_bilateral_oblique_topology():
    graph = _symmetric_tapered_annular_graph(include_oblique_pair=False)
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert "profile" not in draft
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
        and item.get("required_for_modeling") is True
    ]
    assert len(blockers) == 1
    assert draft["dimension_closure"] == {"status": "incomplete"}


def test_rotational_profile_stays_blocked_when_one_engineering_boundary_is_unresolved():
    graph = _rotational_rectangle_graph(omit_top=True)
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert "profile" not in draft
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("field") == "rotational_profile"
        and item.get("required_for_modeling") is True
    ]
    assert len(blockers) == 1
    assert draft["dimension_closure"] == {"status": "incomplete"}


def test_rotational_topology_without_metric_profile_fails_closed_before_planner():
    boundary = "feature:F_PROFILE_EDGE.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=300, width_y=300, height_z=75),
        direct_values=[
            *_overall_values(length_x=300, width_y=300, height_z=75),
            DirectValueEvidence(
                id="S_PROFILE_BOUNDARY",
                target=boundary,
                value=54,
                source_ids=["DIM_PROFILE"],
            ),
        ],
        observations=[
            {
                "kind": "hybrid_rotational_profile_topology_ledger",
                "schema": "1.0",
                "items": [
                    {
                        "region_id": "R1",
                        "view_kind": "front",
                        "plane": "XZ",
                        "rotation_axis": "Z",
                        "component_index": 0,
                        "edges": [
                            {
                                "ref": "R1.profile.edge.1",
                                "profile_entity_id": "E001",
                                "source_orientation": "vertical",
                                "constant_axis": "X",
                            }
                        ],
                        "junctions": [],
                        "source_ids": ["structural:R1:context"],
                        "basis": (
                            "established_rotational_symmetry_plus_"
                            "structural_profile_connectivity"
                        ),
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    }
                ],
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        ],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    blockers = [
        item
        for item in draft["unresolved"]
        if item.get("required_for_modeling") is True
    ]
    assert len(blockers) == 1
    assert blockers[0]["kind"] == "unsupported_representation"
    assert blockers[0]["field"] == "rotational_profile"
    assert blockers[0]["axis"] == "Z"
    assert (
        blockers[0]["metadata"]["engineering_coordinate_inferred_from_pixels"]
        is False
    )
    assert draft["dimension_closure"] == {"status": "incomplete"}
    errors = R.check_drawing_json(draft)
    assert "blocking_unresolved=1" in errors
    assert "dimension_closure.status must be closed" in errors


def test_resolver_to_semantic_draft_passes_existing_gate_a_for_bottom_offset():
    target = "feature:F_MAIN_HOLE.centerline.z"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(
                id="S_MAIN_KIND",
                target="feature:F_MAIN_HOLE.type",
                value="through_hole",
            ),
            DirectValueEvidence(
                id="S_MAIN_AXIS",
                target="feature:F_MAIN_HOLE.axis",
                value="Y",
            ),
            DirectValueEvidence(
                id="S_MAIN_X",
                target="feature:F_MAIN_HOLE.centerline.x",
                value=0,
            ),
            DirectValueEvidence(
                id="S_MAIN_D",
                target="feature:F_MAIN_HOLE.diameter",
                value=20,
            ),
            DirectValueEvidence(
                id="S_MAIN_COUNT",
                target="feature:F_MAIN_HOLE.count",
                value=1,
            ),
        ],
        relations=[
            RelationEvidence(
                id="S_MAIN_Z40",
                kind="edge_offset",
                axis="Z",
                from_side="min",
                value=40,
                targets=[target],
                source_ids=["ANN_BOTTOM_TO_CENTER_40"],
            )
        ],
        required_targets=[target],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert draft["features"][0]["centerline"]["z"] == 40
    assert draft["dimension_closure"] == {"status": "closed"}
    assert R.check_drawing_json(draft) == []


def test_mount_pair_resolves_edge_offsets_and_signed_spacing_then_passes_gate_a():
    x0 = "feature:F_PAIR.explicit_centers.0.0"
    x1 = "feature:F_PAIR.explicit_centers.1.0"
    y0 = "feature:F_PAIR.explicit_centers.0.1"
    y1 = "feature:F_PAIR.explicit_centers.1.1"

    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(
                id="S_PAIR_KIND",
                target="feature:F_PAIR.type",
                value="through_hole",
            ),
            DirectValueEvidence(
                id="S_PAIR_AXIS",
                target="feature:F_PAIR.axis",
                value="Z",
            ),
            DirectValueEvidence(
                id="S_PAIR_D",
                target="feature:F_PAIR.diameter",
                value=6.6,
            ),
            DirectValueEvidence(
                id="S_PAIR_COUNT",
                target="feature:F_PAIR.count",
                value=2,
            ),
        ],
        relations=[
            RelationEvidence(
                id="S_PAIR_X0",
                kind="edge_offset",
                axis="X",
                from_side="min",
                value=10,
                targets=[x0],
            ),
            RelationEvidence(
                id="S_PAIR_SPACING",
                kind="center_spacing",
                axis="X",
                value=20,
                direction=1,
                targets=[x0, x1],
            ),
            RelationEvidence(
                id="S_PAIR_Y",
                kind="edge_offset",
                axis="Y",
                from_side="max",
                value=24,
                targets=[y0, y1],
            ),
        ],
        required_targets=[x0, x1, y0, y1],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    pair = draft["features"][0]
    assert pair["explicit_centers"] == [[-10, -8], [10, -8]]
    assert result.ok
    assert any(item["target"] == x1 for item in draft["derived"])
    assert R.check_drawing_json(draft) == []


def test_alignment_propagation_is_serialized_as_derived_with_relation_ref():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(id="A_KIND", target="feature:F_A.type", value="through_hole"),
            DirectValueEvidence(id="A_AXIS", target="feature:F_A.axis", value="Z"),
            DirectValueEvidence(id="A_X", target=a, value=20),
            DirectValueEvidence(id="A_Y", target="feature:F_A.centerline.y", value=16),
            DirectValueEvidence(id="A_D", target="feature:F_A.diameter", value=5),
            DirectValueEvidence(id="A_N", target="feature:F_A.count", value=1),
            DirectValueEvidence(id="B_KIND", target="feature:F_B.type", value="through_hole"),
            DirectValueEvidence(id="B_AXIS", target="feature:F_B.axis", value="Z"),
            DirectValueEvidence(id="B_Y", target="feature:F_B.centerline.y", value=16),
            DirectValueEvidence(id="B_D", target="feature:F_B.diameter", value=5),
            DirectValueEvidence(id="B_N", target="feature:F_B.count", value=1),
        ],
        relations=[
            RelationEvidence(
                id="R_ALIGN_X",
                kind="alignment",
                axis="X",
                targets=[a, b],
                source_ids=["CENTERLINE_EVIDENCE"],
            )
        ],
        required_targets=[b],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert next(item for item in draft["features"] if item["id"] == "F_B")["centerline"]["x"] == 0
    derived = next(item for item in draft["derived"] if item["target"] == b)
    assert derived["expr"] == {"target": a}
    assert derived["relation_refs"] == ["R_ALIGN_X"]
    assert R.check_drawing_json(draft) == []


def test_unsigned_spacing_stays_incomplete_and_existing_gate_a_rejects_it():
    a = "feature:F_A.centerline.x"
    b = "feature:F_B.centerline.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(id="A_KIND", target="feature:F_A.type", value="through_hole"),
            DirectValueEvidence(id="A_AXIS", target="feature:F_A.axis", value="Z"),
            DirectValueEvidence(id="A_X", target=a, value=-10),
            DirectValueEvidence(id="A_Y", target="feature:F_A.centerline.y", value=0),
            DirectValueEvidence(id="A_D", target="feature:F_A.diameter", value=5),
            DirectValueEvidence(id="A_N", target="feature:F_A.count", value=1),
            DirectValueEvidence(id="B_KIND", target="feature:F_B.type", value="through_hole"),
            DirectValueEvidence(id="B_AXIS", target="feature:F_B.axis", value="Z"),
            DirectValueEvidence(id="B_Y", target="feature:F_B.centerline.y", value=0),
            DirectValueEvidence(id="B_D", target="feature:F_B.diameter", value=5),
            DirectValueEvidence(id="B_N", target="feature:F_B.count", value=1),
        ],
        relations=[
            RelationEvidence(
                id="R_UNSIGNED",
                kind="center_spacing",
                axis="X",
                value=20,
                targets=[a, b],
            )
        ],
        required_targets=[b],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)
    errors = R.check_drawing_json(draft)

    assert not result.ok
    assert draft["dimension_closure"] == {"status": "incomplete"}
    assert any(item.get("target") == b for item in draft["unresolved"])
    assert errors
    assert any("unresolved" in error or "dimension_closure" in error for error in errors)

def test_inferred_feature_types_emit_gate_a_provenance_writers():
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=40, width_y=32, height_z=66),
        direct_values=[
            *_overall_values(),
            DirectValueEvidence(
                id="S_HOLE_AXIS",
                target="feature:F_HOLE.axis",
                value="Y",
                source_ids=["ANN_HOLE_AXIS"],
            ),
            DirectValueEvidence(
                id="S_HOLE_D",
                target="feature:F_HOLE.diameter",
                value=20,
                source_ids=["ANN_HOLE_D"],
            ),
            DirectValueEvidence(
                id="S_HOLE_Z",
                target="feature:F_HOLE.centerline.z",
                value=40,
                source_ids=["ANN_HOLE_Z"],
            ),
            DirectValueEvidence(
                id="S_THREAD_AXIS",
                target="feature:F_THREAD.axis",
                value="X",
                source_ids=["ANN_THREAD_AXIS"],
            ),
            DirectValueEvidence(
                id="S_THREAD_SPEC",
                target="feature:F_THREAD.thread_spec",
                value="M6",
                source_ids=["ANN_THREAD_SPEC"],
            ),
            DirectValueEvidence(
                id="S_THREAD_DEPTH",
                target="feature:F_THREAD.thread_depth",
                value=12,
                source_ids=["ANN_THREAD_DEPTH"],
            ),
            DirectValueEvidence(
                id="S_THREAD_Z",
                target="feature:F_THREAD.centerline.z",
                value=58,
                source_ids=["ANN_THREAD_Z"],
            ),
            DirectValueEvidence(
                id="S_RECESS_AXIS",
                target="feature:F_RECESS.axis",
                value="X",
                source_ids=["ANN_RECESS_AXIS"],
            ),
            DirectValueEvidence(
                id="S_RECESS_D",
                target="feature:F_RECESS.diameter",
                value=6.6,
                source_ids=["ANN_RECESS_D"],
            ),
            DirectValueEvidence(
                id="S_RECESS_FLAG",
                target="feature:F_RECESS.recessed_hole",
                value=True,
                source_ids=["ANN_RECESS_FLAG"],
            ),
            DirectValueEvidence(
                id="S_RECESS_D2",
                target="feature:F_RECESS.recess_diameter",
                value=11,
                source_ids=["ANN_RECESS_D2"],
            ),
            DirectValueEvidence(
                id="S_RECESS_DEPTH",
                target="feature:F_RECESS.recess_depth",
                value=6.5,
                source_ids=["ANN_RECESS_DEPTH"],
            ),
            DirectValueEvidence(
                id="S_RECESS_Y",
                target="feature:F_RECESS.centerline.y",
                value=24,
                source_ids=["ANN_RECESS_Y"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="S_BOUNDARY_Y",
                kind="edge_offset",
                axis="Y",
                from_side="max",
                value=24,
                targets=["feature:F_BOUNDARY.boundary.y"],
                source_ids=["ANN_BOUNDARY_Y"],
            ),
        ],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    inferred = {item["id"]: item["type"] for item in draft["features"]}
    assert inferred == {
        "F_BOUNDARY": "reference_boundary",
        "F_HOLE": "hole",
        "F_RECESS": "recessed_hole",
        "F_THREAD": "threaded_hole",
    }

    type_sources = {
        item.get("target"): item
        for item in draft["source_ledger"]
        if item.get("semantic") == "feature_kind"
    }
    assert set(type_sources) == {
        "feature:F_BOUNDARY.type",
        "feature:F_HOLE.type",
        "feature:F_RECESS.type",
        "feature:F_THREAD.type",
    }
    assert all(item.get("evidence") for item in type_sources.values())
    assert all(item.get("inference_basis_targets") for item in type_sources.values())
    assert all(item.get("inference_basis_sources") for item in type_sources.values())

    errors = R.check_drawing_json(draft)
    assert not any(
        error.startswith("required geometry field lacks evidence: feature:")
        and error.endswith(".type")
        for error in errors
    )



def test_midpoint_constraint_round_trips_through_draft_and_gate_a():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_GENERIC.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(length_x=100, width_y=40, height_z=20),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
            DirectValueEvidence(
                id="LEFT_BOUNDARY",
                target=left,
                value=20,
                source_ids=["LEFT_PROFILE"],
            ),
            DirectValueEvidence(
                id="RIGHT_BOUNDARY",
                target=right,
                value=60,
                source_ids=["RIGHT_PROFILE"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_MID_GENERIC",
                kind="midpoint",
                axis="X",
                targets=[left, center, right],
                source_ids=["SPAN_PROFILE"],
                required_for_modeling=False,
            )
        ],
    )
    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[center] == 40.0
    assert draft["constraints"]["span_centers"]["C_GENERIC"]["x"] == -10.0
    relation = next(
        item for item in draft["source_ledger"]
        if item["id"] == "R_MID_GENERIC"
    )
    assert relation["semantic"] == "midpoint"
    assert relation["links"] == [left, center, right]
    derived = next(item for item in draft["derived"] if item["target"] == center)
    assert derived["relation_refs"] == ["R_MID_GENERIC"]
    assert R.check_drawing_json(draft) == []


def test_centered_span_constraint_round_trips_through_gate_a():
    left = "feature:F_LEFT.boundary.x"
    center = "constraints.span_centers.C_GENERIC.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
        ],
        relations=[
            RelationEvidence(
                id="R_CENTER",
                kind="edge_offset",
                axis="X",
                from_side="min",
                value=50,
                targets=[center],
                source_ids=["CENTER_ANCHOR"],
                required_for_modeling=True,
            ),
            RelationEvidence(
                id="R_CENTERED_SPAN",
                kind="centered_span",
                axis="X",
                value=20,
                direction=1,
                targets=[left, center, right],
                source_ids=["SPAN_DIMENSION"],
                required_for_modeling=False,
            ),
        ],
        required_targets=[left, right],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.ok
    assert result.values[left] == 40.0
    assert result.values[center] == 50.0
    assert result.values[right] == 60.0
    assert draft["constraints"]["span_centers"]["C_GENERIC"]["x"] == 0.0

    left_feature = next(
        item for item in draft["features"] if item["id"] == "F_LEFT"
    )
    right_feature = next(
        item for item in draft["features"] if item["id"] == "F_RIGHT"
    )
    assert left_feature["boundary"]["x"] == -10.0
    assert right_feature["boundary"]["x"] == 10.0

    source = next(
        item for item in draft["source_ledger"]
        if item["id"] == "R_CENTERED_SPAN"
    )
    assert source["semantic"] == "centered_span"
    assert source["value"] == 20
    assert source["direction"] == 1
    assert source["links"] == [left, center, right]
    assert R.check_drawing_json(draft) == []


def test_profile_arc_radius_constraint_round_trips_without_materializing_arc():
    graph = _rotational_rectangle_graph()
    target = (
        "constraints.profile_arc_radii."
        "PHYSICAL_OBLIQUE_ARC.radius"
    )
    graph.direct_values.append(
        DirectValueEvidence(
            id="ARC_RADIUS_R5",
            target=target,
            value=5.0,
            semantic="radius",
            source_ids=[
                "hybrid:whole:7",
                "hybrid:curve-boundary:3",
            ],
        )
    )
    graph.required_targets.append(target)

    resolved = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, resolved)

    assert resolved.values[target] == 5.0
    assert (
        draft["constraints"]["profile_arc_radii"]
        ["PHYSICAL_OBLIQUE_ARC"]["radius"]
        == 5.0
    )
    source = next(
        item
        for item in draft["source_ledger"]
        if item["id"] == "ARC_RADIUS_R5"
    )
    assert source["semantic"] == "radius"
    assert source["target"] == target
    assert source["value"] == 5.0
    assert all(
        segment["type"] == "line"
        for segment in draft["profile"]["segments"]
    )
    assert R.check_drawing_json(draft) == []


def test_coordinate_distance_is_audited_as_formal_relation():
    left = "feature:F_LEFT.boundary.x"
    right = "feature:F_RIGHT.boundary.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
            DirectValueEvidence(
                id="LEFT_BOUNDARY",
                target=left,
                value=20,
                source_ids=["LEFT"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_COORD_DISTANCE",
                kind="coordinate_distance",
                axis="X",
                value=30,
                direction=1,
                targets=[left, right],
                source_ids=["DIMENSION"],
                required_for_modeling=True,
            )
        ],
        required_targets=[right],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[right] == 50.0
    source = next(
        item
        for item in draft["source_ledger"]
        if item["id"] == "R_COORD_DISTANCE"
    )
    assert source["semantic"] == "coordinate_distance"
    assert source["between"] == [left, right]
    assert R.check_drawing_json(draft) == []


def test_center_distance_accepts_profile_span_constraint_center():
    span_center = "constraints.span_centers.C_GENERIC.x"
    feature_center = "feature:F_HOLE.centerline.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
            DirectValueEvidence(
                id="F_HOLE_TYPE",
                target="feature:F_HOLE.type",
                value="reference_point",
                source_ids=["REFERENCE_POINT"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_SPAN_CENTER",
                kind="edge_offset",
                axis="X",
                value=30,
                from_side="min",
                targets=[span_center],
                source_ids=["SPAN_CENTER"],
                required_for_modeling=True,
            ),
            RelationEvidence(
                id="R_CENTER_DISTANCE",
                kind="center_distance",
                axis="X",
                value=20,
                direction=1,
                targets=[span_center, feature_center],
                source_ids=["CENTER_DISTANCE"],
                required_for_modeling=True,
            ),
        ],
        required_targets=[feature_center],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[span_center] == 30.0
    assert result.values[feature_center] == 50.0
    assert R.check_drawing_json(draft) == []


def test_symmetric_profile_level_constraint_round_trips_through_gate_a():
    profile_boundary = "feature:F_PROFILE.boundary.x"
    mirror_level = "constraints.symmetric_profile_levels.C_MIRROR.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
        ],
        relations=[
            RelationEvidence(
                id="R_PROFILE_LEFT",
                kind="edge_offset",
                axis="X",
                value=20,
                from_side="min",
                targets=[profile_boundary],
                source_ids=["PROFILE_LEVEL"],
                required_for_modeling=False,
            ),
            RelationEvidence(
                id="R_PROFILE_RIGHT",
                kind="edge_offset",
                axis="X",
                value=20,
                from_side="max",
                targets=[mirror_level],
                source_ids=["MIRROR_LEVEL"],
                required_for_modeling=False,
            ),
            RelationEvidence(
                id="R_PROFILE_DISTANCE",
                kind="coordinate_distance",
                axis="X",
                value=60,
                direction=1,
                targets=[profile_boundary, mirror_level],
                source_ids=["SYMMETRIC_PROFILE_DISTANCE"],
                required_for_modeling=True,
            ),
        ],
        required_targets=[profile_boundary, mirror_level],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[profile_boundary] == 20.0
    assert result.values[mirror_level] == 80.0
    assert draft["features"][0]["boundary"]["x"] == -30.0
    assert draft["features"][0]["type"] == "reference_boundary"
    assert draft["constraints"]["symmetric_profile_levels"]["C_MIRROR"]["x"] == 30.0
    assert R.check_drawing_json(draft) == []


def test_symmetric_center_constraint_round_trips_through_gate_a():
    span_center = "constraints.span_centers.C_LEFT.x"
    mirror_center = "constraints.symmetric_centers.C_RIGHT.x"
    graph = EvidenceGraph(
        overall_dimensions=OverallDimensions(
            length_x=100,
            width_y=40,
            height_z=20,
        ),
        direct_values=[
            *_overall_values(length_x=100, width_y=40, height_z=20),
            DirectValueEvidence(
                id="F_REFERENCE_TYPE",
                target="feature:F_REFERENCE.type",
                value="reference_point",
                source_ids=["REFERENCE_POINT"],
            ),
        ],
        relations=[
            RelationEvidence(
                id="R_LEFT",
                kind="edge_offset",
                axis="X",
                value=20,
                from_side="min",
                targets=[span_center],
                source_ids=["LEFT_CENTER"],
                required_for_modeling=False,
            ),
            RelationEvidence(
                id="R_RIGHT",
                kind="edge_offset",
                axis="X",
                value=20,
                from_side="max",
                targets=[mirror_center],
                source_ids=["RIGHT_CENTER"],
                required_for_modeling=False,
            ),
            RelationEvidence(
                id="R_DISTANCE",
                kind="center_distance",
                axis="X",
                value=60,
                direction=1,
                targets=[span_center, mirror_center],
                source_ids=["CENTER_DISTANCE"],
                required_for_modeling=True,
            ),
        ],
        required_targets=[span_center, mirror_center],
    )

    result = resolve_evidence_graph(graph)
    draft = build_semantic_draft(graph, result)

    assert result.values[span_center] == 20.0
    assert result.values[mirror_center] == 80.0
    assert draft["constraints"]["span_centers"]["C_LEFT"]["x"] == -30.0
    assert draft["constraints"]["symmetric_centers"]["C_RIGHT"]["x"] == 30.0
    assert R.check_drawing_json(draft) == []
