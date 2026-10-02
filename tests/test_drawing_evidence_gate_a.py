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


def _symmetric_tapered_annular_graph(*, include_oblique_pair=True):
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
        fragments = [
            {
                "id": "P_OBL_LEFT",
                "region_ids": ["R1", "R2"],
                "material_side_index": 1,
                "background_side_index": 0,
                "view_kind": "front",
                "plane": "XZ",
                "rotation_axis": "Z",
                "supporting_physical_feature_ids": [],
                "supporting_physical_edges": [],
                "connection_kind": "exterior_non_orthogonal_boundary_fragment",
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
                "supporting_physical_feature_ids": [],
                "supporting_physical_edges": [],
                "connection_kind": "exterior_non_orthogonal_boundary_fragment",
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


def test_symmetric_tapered_annular_profile_materializes_from_constraints_not_pixels():
    graph = _symmetric_tapered_annular_graph()
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
