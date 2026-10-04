from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

from .capture import (
    AssociationClaim,
    CaptureDimension,
    ReaderCapture,
    _association_basis_sufficient,
)
from .evidence import (
    Axis,
    DatumAlignmentEvidence,
    DimensionEndpoint,
    DimensionObservation,
    DirectValueEvidence,
    EvidenceGraph,
    ProjectionEvidence,
    RelationEvidence,
    ViewEvidence,
)


class IdentityLinkError(ValueError):
    """Reader Capture cannot be deterministically linked without guessing."""


@dataclass
class IdentityLinkResult:
    evidence: EvidenceGraph
    entity_to_feature: dict[str, str]
    report: dict[str, Any]


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        a = self.find(left)
        b = self.find(right)
        if a != b:
            self.parent[b] = a


def _canon(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _canon(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canon(item) for item in value]
    return value


_ROTATIONAL_PROFILE_TOPOLOGY_KIND = "hybrid_rotational_profile_topology_ledger"
_ROTATIONAL_OBLIQUE_PROFILE_KIND = (
    "hybrid_rotational_oblique_profile_candidate_ledger"
)
_PHYSICAL_ROTATIONAL_OBLIQUE_PROFILE_KIND = (
    "hybrid_physical_rotational_oblique_profile_topology_ledger"
)
_VIEW_AXIS_BOUNDARY_KIND = "hybrid_view_axis_boundary_ledger"
_LABELED_DIMENSION_RELATION_KIND = "hybrid_labeled_dimension_relation_ledger"
_ENGINEERING_CALLOUT_LEDGER_KIND = "hybrid_engineering_callout_ledger"
_PHYSICAL_PROFILE_ARC_RADIUS_KIND = "hybrid_physical_profile_arc_radius_ledger"



def _merge_physical_rotational_topology_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge crop-local topology only after physical profile identity overlaps."""

    if len(items) < 2:
        return items

    edge_sets: list[set[tuple[str, str]]] = []
    for item in items:
        current: set[tuple[str, str]] = set()
        edges = item.get("edges")
        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                feature_id = edge.get("physical_feature_id")
                axis = str(edge.get("constant_axis") or "").upper()
                if isinstance(feature_id, str) and feature_id and axis in {"X", "Y", "Z"}:
                    current.add((feature_id, axis))
        edge_sets.append(current)

    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        lroot = find(left)
        rroot = find(right)
        if lroot != rroot:
            parent[rroot] = lroot

    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if (
                items[left].get("plane") == items[right].get("plane")
                and items[left].get("rotation_axis") == items[right].get("rotation_axis")
                and items[left].get("view_kind") == items[right].get("view_kind")
                and edge_sets[left].intersection(edge_sets[right])
            ):
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index in range(len(items)):
        groups.setdefault(find(index), []).append(index)

    output: list[dict[str, Any]] = []
    for indices in groups.values():
        if len(indices) == 1:
            output.append(items[indices[0]])
            continue

        grouped = [items[index] for index in indices]
        by_physical: dict[tuple[str, str], list[dict[str, Any]]] = {}
        original_to_physical: dict[str, tuple[str, str]] = {}
        valid = True

        for item in grouped:
            for edge in item.get("edges", []):
                if not isinstance(edge, dict):
                    valid = False
                    break
                feature_id = str(edge.get("physical_feature_id") or "")
                axis = str(edge.get("constant_axis") or "").upper()
                ref = str(edge.get("ref") or "")
                target = edge.get("boundary_target")
                if (
                    not feature_id
                    or not ref
                    or axis not in {"X", "Y", "Z"}
                    or target != f"feature:{feature_id}.boundary.{axis.lower()}"
                ):
                    valid = False
                    break
                key = (feature_id, axis)
                by_physical.setdefault(key, []).append(edge)
                original_to_physical[ref] = key
            if not valid:
                break

        if not valid:
            output.extend(grouped)
            continue

        canonical_ref: dict[tuple[str, str], str] = {}
        merged_edges: list[dict[str, Any]] = []
        for key, records in sorted(by_physical.items()):
            refs = sorted(str(record.get("ref") or "") for record in records)
            representative = min(records, key=lambda record: str(record.get("ref") or ""))
            canonical_ref[key] = refs[0]
            merged_edge = copy.deepcopy(representative)
            merged_edge["ref"] = refs[0]
            merged_edge["source_refs"] = refs
            polarity = {
                (
                    int(record["material_side_index"]),
                    int(record["background_side_index"]),
                )
                for record in records
                if (
                    record.get("one_sided_boundary_candidate") is True
                    and record.get("material_side_index") in {0, 1}
                    and record.get("background_side_index") in {0, 1}
                    and record.get("material_side_index")
                    != record.get("background_side_index")
                )
            }
            axis_directions = {
                (
                    str(record["material_axis_direction"]),
                    str(record["background_axis_direction"]),
                )
                for record in records
                if (
                    record.get("material_axis_direction")
                    in {"negative", "positive"}
                    and record.get("background_axis_direction")
                    in {"negative", "positive"}
                    and record.get("material_axis_direction")
                    != record.get("background_axis_direction")
                )
            }
            direction_conflict = len(axis_directions) > 1
            if (
                len(polarity) == 1
                and not direction_conflict
                and not any(
                    record.get("material_side_ambiguous") is True
                    for record in records
                )
            ):
                material_side_index, background_side_index = next(iter(polarity))
                merged_edge["one_sided_boundary_candidate"] = True
                merged_edge["material_side_index"] = material_side_index
                merged_edge["background_side_index"] = background_side_index
                if len(axis_directions) == 1:
                    (
                        material_axis_direction,
                        background_axis_direction,
                    ) = next(iter(axis_directions))
                    merged_edge["material_axis_direction"] = (
                        material_axis_direction
                    )
                    merged_edge["background_axis_direction"] = (
                        background_axis_direction
                    )
                else:
                    merged_edge.pop("material_axis_direction", None)
                    merged_edge.pop("background_axis_direction", None)
                merged_edge.pop("material_side_ambiguous", None)
            elif (
                polarity
                or direction_conflict
                or any(
                    record.get("material_side_ambiguous") is True
                    for record in records
                )
            ):
                merged_edge.pop("one_sided_boundary_candidate", None)
                merged_edge.pop("material_side_index", None)
                merged_edge.pop("background_side_index", None)
                merged_edge.pop("material_axis_direction", None)
                merged_edge.pop("background_axis_direction", None)
                merged_edge["material_side_ambiguous"] = True
            merged_edges.append(merged_edge)

        junctions: set[tuple[str, str]] = set()
        for item in grouped:
            for pair in item.get("junctions", []):
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or not all(isinstance(ref, str) for ref in pair)
                ):
                    continue
                left_key = original_to_physical.get(pair[0])
                right_key = original_to_physical.get(pair[1])
                if left_key is None or right_key is None or left_key == right_key:
                    continue
                left_ref = canonical_ref[left_key]
                right_ref = canonical_ref[right_key]
                junctions.add(
                    (left_ref, right_ref)
                    if left_ref < right_ref
                    else (right_ref, left_ref)
                )

        region_ids = sorted(
            {
                str(item.get("region_id") or "")
                for item in grouped
                if str(item.get("region_id") or "")
            }
        )
        source_ids = list(
            dict.fromkeys(
                source_id
                for item in grouped
                for source_id in item.get("source_ids", [])
                if isinstance(source_id, str) and source_id
            )
        )
        digest = hashlib.sha256(
            "|".join(
                [
                    str(grouped[0].get("plane") or ""),
                    str(grouped[0].get("rotation_axis") or ""),
                    *region_ids,
                    *[
                        f"{feature_id}:{axis}"
                        for feature_id, axis in sorted(by_physical)
                    ],
                ]
            ).encode("utf-8")
        ).hexdigest()[:12].upper()

        merged = copy.deepcopy(grouped[0])
        merged["region_id"] = f"PHYSICAL_{digest}"
        merged["region_ids"] = region_ids
        merged["component_index"] = 0
        merged["edges"] = merged_edges
        merged["junctions"] = [list(pair) for pair in sorted(junctions)]
        merged["source_ids"] = source_ids
        merged["basis"] = "identity_linked_physical_rotational_profile_topology"
        output.append(merged)

    output.sort(
        key=lambda item: (
            str(item.get("plane") or ""),
            str(item.get("rotation_axis") or ""),
            str(item.get("region_id") or ""),
            int(item.get("component_index") or 0),
        )
    )
    return output


def _physical_rotational_oblique_profile_items(
    observations: list[dict[str, Any]],
    entity_to_feature: dict[str, str],
) -> list[dict[str, Any]]:
    """Collapse crop-local oblique evidence only after physical identity is proven.

    This bridge records topology/identity only.  Pixel endpoints and angles stay
    in the source candidate ledger and never become engineering coordinates.
    """

    physical_edge_directions: dict[
        tuple[str, str, str, str, str],
        set[tuple[str, str]],
    ] = defaultdict(set)
    physical_edge_direction_ambiguous: set[
        tuple[str, str, str, str, str]
    ] = set()
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _ROTATIONAL_PROFILE_TOPOLOGY_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            plane = str(item.get("plane") or "").upper()
            rotation_axis = str(item.get("rotation_axis") or "").upper()
            view_kind = str(item.get("view_kind") or "")
            edges = item.get("edges")
            if (
                plane not in {"XY", "XZ", "YZ"}
                or rotation_axis not in set(plane)
                or not view_kind
                or not isinstance(edges, list)
            ):
                continue
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                feature_id = str(edge.get("physical_feature_id") or "")
                axis = str(edge.get("constant_axis") or "").upper()
                if (
                    not feature_id
                    or axis not in {"X", "Y", "Z"}
                    or edge.get("boundary_target")
                    != f"feature:{feature_id}.boundary.{axis.lower()}"
                ):
                    continue
                direction_key = (
                    plane,
                    rotation_axis,
                    view_kind,
                    feature_id,
                    axis,
                )
                if edge.get("material_side_ambiguous") is True:
                    physical_edge_direction_ambiguous.add(direction_key)
                    continue
                material_direction = edge.get("material_axis_direction")
                background_direction = edge.get("background_axis_direction")
                if (
                    material_direction in {"negative", "positive"}
                    and background_direction in {"negative", "positive"}
                    and material_direction != background_direction
                ):
                    physical_edge_directions[direction_key].add(
                        (
                            str(material_direction),
                            str(background_direction),
                        )
                    )

    grouped: dict[
        tuple[
            str,
            str,
            str,
            tuple[tuple[str, str], ...],
            str,
            str,
        ],
        list[dict[str, Any]],
    ] = {}

    for observation in observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _ROTATIONAL_OBLIQUE_PROFILE_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            region_id = str(item.get("region_id") or "")
            view_kind = str(item.get("view_kind") or "")
            plane = str(item.get("plane") or "").upper()
            rotation_axis = str(item.get("rotation_axis") or "").upper()
            entity_ids = item.get("supporting_profile_entity_ids")
            constant_axes = item.get("supporting_profile_constant_axes")
            source_ids = [
                value
                for value in item.get("source_ids", [])
                if isinstance(value, str) and value
            ]
            oblique_sources = sorted(
                value
                for value in source_ids
                if value.startswith(
                    (
                        "hybrid:oblique-line:",
                        "hybrid:curve-boundary:",
                    )
                )
            )
            if (
                not region_id
                or not view_kind
                or plane not in {"XY", "XZ", "YZ"}
                or rotation_axis not in set(plane)
                or not isinstance(entity_ids, list)
                or not all(
                    isinstance(entity_id, str) and entity_id
                    for entity_id in entity_ids
                )
                or not isinstance(constant_axes, list)
                or len(constant_axes) != len(entity_ids)
                or not all(
                    isinstance(axis, str)
                    and axis.upper() in {"X", "Y", "Z"}
                    and axis.upper() in set(plane)
                    for axis in constant_axes
                )
                or len(oblique_sources) != 1
            ):
                continue
            if any(entity_id not in entity_to_feature for entity_id in entity_ids):
                continue

            physical_edges = tuple(
                sorted(
                    {
                        (
                            entity_to_feature[entity_id],
                            str(axis).upper(),
                        )
                        for entity_id, axis in zip(
                            entity_ids,
                            constant_axes,
                            strict=True,
                        )
                    }
                )
            )
            one_sided = item.get("one_sided_boundary_candidate") is True
            exterior = item.get("exterior_boundary_candidate") is True
            support_status = str(item.get("support_status") or "")
            if one_sided and len(physical_edges) == 1:
                connection_kind = "one_sided_non_orthogonal_boundary_continuation"
            elif len(physical_edges) >= 2:
                connection_kind = "non_orthogonal_profile_connection"
            elif (
                not physical_edges
                and exterior
                and one_sided
                and support_status == "unresolved"
            ):
                connection_kind = "exterior_non_orthogonal_boundary_fragment"
            else:
                continue

            group_key = (
                plane,
                rotation_axis,
                view_kind,
                physical_edges,
                oblique_sources[0],
                connection_kind,
            )
            grouped.setdefault(group_key, []).append(
                {
                    "region_id": region_id,
                    "source_ids": source_ids,
                    "material_side_index": item.get("material_side_index"),
                    "background_side_index": item.get("background_side_index"),
                    "primitive_kind": item.get("primitive_kind"),
                    "primitive_kind_basis": item.get("primitive_kind_basis"),
                }
            )

    output: list[dict[str, Any]] = []
    for group_key, records in sorted(grouped.items()):
        (
            plane,
            rotation_axis,
            view_kind,
            physical_edges,
            oblique_source,
            connection_kind,
        ) = group_key
        region_ids = sorted(
            {
                str(record["region_id"])
                for record in records
                if str(record.get("region_id") or "")
            }
        )
        source_ids = list(
            dict.fromkeys(
                source_id
                for record in records
                for source_id in record.get("source_ids", [])
                if isinstance(source_id, str) and source_id
            )
        )
        digest = hashlib.sha256(
            "|".join(
                [
                    plane,
                    rotation_axis,
                    view_kind,
                    *[
                        f"{feature_id}:{axis}"
                        for feature_id, axis in physical_edges
                    ],
                    oblique_source,
                    connection_kind,
                ]
            ).encode("utf-8")
        ).hexdigest()[:12].upper()
        polarity = {
            (
                int(record["material_side_index"]),
                int(record["background_side_index"]),
            )
            for record in records
            if (
                record.get("material_side_index") in {0, 1}
                and record.get("background_side_index") in {0, 1}
                and record.get("material_side_index")
                != record.get("background_side_index")
            )
        }
        primitive_records = {
            (
                str(record.get("primitive_kind") or ""),
                str(record.get("primitive_kind_basis") or ""),
            )
            for record in records
            if str(record.get("primitive_kind") or "")
            in {"line", "arc", "unresolved"}
            and str(record.get("primitive_kind_basis") or "")
        }
        primitive_fields: dict[str, Any]
        if len(primitive_records) == 1:
            primitive_kind, primitive_kind_basis = next(iter(primitive_records))
            primitive_fields = {
                "primitive_kind": primitive_kind,
                "primitive_kind_basis": primitive_kind_basis,
            }
        elif primitive_records:
            primitive_fields = {
                "primitive_kind": "unresolved",
                "primitive_kind_basis": (
                    "conflicting_crop_local_primitive_classification"
                ),
            }
        else:
            primitive_fields = {
                "primitive_kind": "unresolved",
                "primitive_kind_basis": (
                    "missing_deterministic_primitive_classification"
                ),
            }

        polarity_fields: dict[str, Any] = {}
        if len(polarity) == 1:
            material_side_index, background_side_index = next(iter(polarity))
            polarity_fields = {
                "material_side_index": material_side_index,
                "background_side_index": background_side_index,
            }
        elif polarity:
            polarity_fields = {"material_side_ambiguous": True}

        output.append(
            {
                "id": f"PHYSICAL_OBLIQUE_{digest}",
                "region_ids": region_ids,
                **polarity_fields,
                **primitive_fields,
                "view_kind": view_kind,
                "plane": plane,
                "rotation_axis": rotation_axis,
                "supporting_physical_feature_ids": sorted(
                    {
                        feature_id
                        for feature_id, _axis in physical_edges
                    }
                ),
                "supporting_physical_edges": [
                    {
                        "physical_feature_id": feature_id,
                        "constant_axis": axis,
                        "boundary_target": (
                            f"feature:{feature_id}.boundary.{axis.lower()}"
                        ),
                        **(
                            {
                                "material_axis_direction": next(
                                    iter(
                                        physical_edge_directions[
                                            (
                                                plane,
                                                rotation_axis,
                                                view_kind,
                                                feature_id,
                                                axis,
                                            )
                                        ]
                                    )
                                )[0],
                                "background_axis_direction": next(
                                    iter(
                                        physical_edge_directions[
                                            (
                                                plane,
                                                rotation_axis,
                                                view_kind,
                                                feature_id,
                                                axis,
                                            )
                                        ]
                                    )
                                )[1],
                            }
                            if (
                                (
                                    plane,
                                    rotation_axis,
                                    view_kind,
                                    feature_id,
                                    axis,
                                )
                                not in physical_edge_direction_ambiguous
                                and len(
                                    physical_edge_directions.get(
                                        (
                                            plane,
                                            rotation_axis,
                                            view_kind,
                                            feature_id,
                                            axis,
                                        ),
                                        set(),
                                    )
                                )
                                == 1
                            )
                            else (
                                {"material_axis_direction_ambiguous": True}
                                if (
                                    (
                                        plane,
                                        rotation_axis,
                                        view_kind,
                                        feature_id,
                                        axis,
                                    )
                                    in physical_edge_direction_ambiguous
                                    or len(
                                        physical_edge_directions.get(
                                            (
                                                plane,
                                                rotation_axis,
                                                view_kind,
                                                feature_id,
                                                axis,
                                            ),
                                            set(),
                                        )
                                    )
                                    > 1
                                )
                                else {}
                            )
                        ),
                    }
                    for feature_id, axis in physical_edges
                ],
                "connection_kind": connection_kind,
                "source_ids": source_ids,
                "basis": (
                    "identity_linked_physical_oblique_profile_topology"
                ),
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        )

    return output


def _bridge_symmetric_oblique_counterpart_supports(
    capture: ReaderCapture,
    items: list[dict[str, Any]],
    entity_to_feature: dict[str, str],
) -> list[dict[str, Any]]:
    """Recover one missing oblique support only from proven bilateral identity.

    A crop-local straight exterior fragment may stop short of one structural
    profile segment even though a structured centered span has already proven
    the two opposite physical profile boundaries. Pixel coordinates are used
    only to prove mirror identity around that established span midpoint; they
    never become engineering coordinates.
    """

    output = copy.deepcopy(items)
    if not output:
        return output

    raw_by_source: dict[str, dict[str, Any] | None] = {}
    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _ROTATIONAL_OBLIQUE_PROFILE_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue
        raw_items = observation.get("items")
        if not isinstance(raw_items, list):
            continue
        for raw_item in raw_items:
            if (
                not isinstance(raw_item, dict)
                or raw_item.get("one_sided_boundary_candidate") is not True
                or raw_item.get("exterior_boundary_candidate") is not True
                or raw_item.get("material_side_index") not in {0, 1}
                or raw_item.get("background_side_index") not in {0, 1}
                or raw_item.get("material_side_index")
                == raw_item.get("background_side_index")
            ):
                continue
            line_support = raw_item.get("line_edge_support_fraction")
            endpoints = raw_item.get("endpoints_px")
            source_ids = [
                value
                for value in raw_item.get("source_ids", [])
                if isinstance(value, str) and value
            ]
            line_sources = [
                value
                for value in source_ids
                if value.startswith("hybrid:oblique-line:")
            ]
            if (
                not isinstance(line_support, (int, float))
                or isinstance(line_support, bool)
                or float(line_support) < 0.85
                or not isinstance(endpoints, list)
                or len(endpoints) != 2
                or not all(
                    isinstance(point, list)
                    and len(point) == 2
                    and all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        for value in point
                    )
                    for point in endpoints
                )
                or len(line_sources) != 1
            ):
                continue

            source = line_sources[0]
            normalized = {
                "view_kind": str(raw_item.get("view_kind") or ""),
                "plane": str(raw_item.get("plane") or "").upper(),
                "rotation_axis": str(raw_item.get("rotation_axis") or "").upper(),
                "endpoints_px": [
                    [float(point[0]), float(point[1])]
                    for point in endpoints
                ],
                "material_side_index": int(raw_item["material_side_index"]),
                "background_side_index": int(raw_item["background_side_index"]),
            }
            previous = raw_by_source.get(source)
            if previous is None and source not in raw_by_source:
                raw_by_source[source] = normalized
            elif previous != normalized:
                raw_by_source[source] = None

    def raw_for_item(item: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        sources = [
            value
            for value in item.get("source_ids", [])
            if isinstance(value, str)
            and value.startswith("hybrid:oblique-line:")
        ]
        if len(sources) != 1:
            return None
        raw = raw_by_source.get(sources[0])
        if not isinstance(raw, dict):
            return None
        return sources[0], raw

    proposals: dict[
        str,
        list[tuple[str, str, list[str], str]],
    ] = defaultdict(list)

    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _STRUCTURED_SYMMETRIC_PROFILE_SPAN_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_identity_only") is not True
        ):
            continue
        records = observation.get("items")
        if not isinstance(records, list):
            continue

        for record in records:
            if (
                not isinstance(record, dict)
                or record.get("datum") != "overall_center"
                or record.get("engineering_coordinate_inferred_from_pixels")
                is not False
                or record.get("pixel_geometry_used_for_identity_only") is not True
            ):
                continue
            axis = str(record.get("axis") or "").upper()
            entity_ids = record.get("profile_entity_ids")
            witness_positions = record.get("selected_witness_positions_px")
            raw_tolerance = record.get("midpoint_tolerance_px")
            if (
                axis not in {"X", "Y", "Z"}
                or not isinstance(entity_ids, list)
                or len(entity_ids) != 2
                or len(set(entity_ids)) != 2
                or not all(
                    isinstance(entity_id, str)
                    and entity_id in entity_to_feature
                    for entity_id in entity_ids
                )
                or not isinstance(witness_positions, list)
                or len(witness_positions) != 2
                or not all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    for value in witness_positions
                )
                or not isinstance(raw_tolerance, (int, float))
                or isinstance(raw_tolerance, bool)
                or float(raw_tolerance) <= 0.0
            ):
                continue

            features = [
                entity_to_feature[entity_id]
                for entity_id in entity_ids
            ]
            if len(set(features)) != 2:
                continue
            feature_positions = {
                feature_id: float(position)
                for feature_id, position in zip(
                    features,
                    witness_positions,
                    strict=True,
                )
            }
            tolerance = float(raw_tolerance)
            mirror_center = sum(feature_positions.values()) / 2.0
            span_sources = [
                value
                for value in record.get("source_ids", [])
                if isinstance(value, str) and value
            ]

            for supported in output:
                supported_id = str(supported.get("id") or "")
                supported_edges = supported.get("supporting_physical_edges")
                supported_raw = raw_for_item(supported)
                if (
                    not supported_id
                    or not isinstance(supported_edges, list)
                    or len(supported_edges) != 1
                    or supported_raw is None
                    or supported.get("connection_kind")
                    != "one_sided_non_orthogonal_boundary_continuation"
                ):
                    continue
                support_edge = supported_edges[0]
                if not isinstance(support_edge, dict):
                    continue
                support_feature = str(
                    support_edge.get("physical_feature_id") or ""
                )
                if (
                    support_feature not in feature_positions
                    or str(support_edge.get("constant_axis") or "").upper()
                    != axis
                ):
                    continue

                _supported_source, supported_geometry = supported_raw
                if (
                    supported_geometry["plane"] not in {"XY", "XZ", "YZ"}
                    or axis not in supported_geometry["plane"]
                    or supported_geometry["rotation_axis"] == axis
                ):
                    continue

                supported_position = feature_positions[support_feature]
                coordinate_distances = [
                    min(
                        abs(float(point[index]) - supported_position)
                        for point in supported_geometry["endpoints_px"]
                    )
                    for index in (0, 1)
                ]
                radial_indices = [
                    index
                    for index, distance in enumerate(coordinate_distances)
                    if distance <= tolerance
                ]
                if len(radial_indices) != 1:
                    continue
                radial_index = radial_indices[0]
                axial_index = 1 - radial_index
                counterpart_features = [
                    feature_id
                    for feature_id in features
                    if feature_id != support_feature
                ]
                if len(counterpart_features) != 1:
                    continue
                counterpart_feature = counterpart_features[0]
                counterpart_position = feature_positions[counterpart_feature]

                for unsupported in output:
                    unsupported_id = str(unsupported.get("id") or "")
                    if not unsupported_id or unsupported_id == supported_id:
                        continue
                    unsupported_edges = unsupported.get(
                        "supporting_physical_edges"
                    )
                    unsupported_raw = raw_for_item(unsupported)
                    if (
                        not isinstance(unsupported_edges, list)
                        or unsupported_edges
                        or unsupported_raw is None
                        or unsupported.get("connection_kind")
                        != "exterior_non_orthogonal_boundary_fragment"
                        or unsupported.get("plane") != supported.get("plane")
                        or unsupported.get("rotation_axis")
                        != supported.get("rotation_axis")
                        or unsupported.get("view_kind")
                        != supported.get("view_kind")
                    ):
                        continue

                    _unsupported_source, unsupported_geometry = unsupported_raw
                    if (
                        unsupported_geometry["plane"]
                        != supported_geometry["plane"]
                        or unsupported_geometry["rotation_axis"]
                        != supported_geometry["rotation_axis"]
                        or unsupported_geometry["view_kind"]
                        != supported_geometry["view_kind"]
                        or unsupported_geometry["material_side_index"]
                        != supported_geometry["material_side_index"]
                        or unsupported_geometry["background_side_index"]
                        != supported_geometry["background_side_index"]
                    ):
                        continue
                    if (
                        min(
                            abs(float(point[radial_index]) - counterpart_position)
                            for point in unsupported_geometry["endpoints_px"]
                        )
                        > tolerance
                    ):
                        continue

                    supported_points = sorted(
                        supported_geometry["endpoints_px"],
                        key=lambda point: (
                            float(point[axial_index]),
                            float(point[radial_index]),
                        ),
                    )
                    unsupported_points = sorted(
                        unsupported_geometry["endpoints_px"],
                        key=lambda point: (
                            float(point[axial_index]),
                            float(point[radial_index]),
                        ),
                    )
                    mirrored = all(
                        abs(
                            float(supported_point[axial_index])
                            - float(unsupported_point[axial_index])
                        )
                        <= tolerance
                        and abs(
                            (
                                float(supported_point[radial_index])
                                + float(unsupported_point[radial_index])
                            )
                            / 2.0
                            - mirror_center
                        )
                        <= tolerance
                        for supported_point, unsupported_point in zip(
                            supported_points,
                            unsupported_points,
                            strict=True,
                        )
                    )
                    if not mirrored:
                        continue

                    proposals[unsupported_id].append(
                        (
                            counterpart_feature,
                            axis,
                            span_sources,
                            supported_id,
                        )
                    )

    by_id = {
        str(item.get("id") or ""): item
        for item in output
        if str(item.get("id") or "")
    }
    for item_id, raw_proposals in proposals.items():
        unique = {
            (
                feature_id,
                axis,
                tuple(source_ids),
                supported_id,
            )
            for feature_id, axis, source_ids, supported_id in raw_proposals
        }
        if len(unique) != 1:
            continue
        feature_id, axis, source_ids_tuple, supported_id = next(iter(unique))
        item = by_id.get(item_id)
        if item is None:
            continue
        item["supporting_physical_feature_ids"] = [feature_id]
        item["supporting_physical_edges"] = [
            {
                "physical_feature_id": feature_id,
                "constant_axis": axis,
                "boundary_target": (
                    f"feature:{feature_id}.boundary.{axis.lower()}"
                ),
            }
        ]
        item["connection_kind"] = (
            "one_sided_non_orthogonal_boundary_continuation"
        )
        item["source_ids"] = list(
            dict.fromkeys(
                [
                    *[
                        value
                        for value in item.get("source_ids", [])
                        if isinstance(value, str) and value
                    ],
                    *source_ids_tuple,
                ]
            )
        )
        item["support_identity_basis"] = (
            "bilateral_oblique_mirror_plus_structured_symmetric_profile_span"
        )
        item["support_counterpart_fragment_id"] = supported_id

    return output


def _linked_physical_profile_arc_radius_observations(
    observations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Link an explicit engineering radius to one verified physical profile arc.

    The engineering radius remains OCR-authoritative. Pixel curve traces are
    used only upstream to identify the curve source. This linker consumes only
    stable curve-source identity and physical profile topology.
    """

    physical_by_curve_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _PHYSICAL_ROTATIONAL_OBLIQUE_PROFILE_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("primitive_kind") != "arc"
                or item.get("primitive_kind_basis")
                != (
                    "verified_continuous_curved_raster_segment_"
                    "between_structural_contacts"
                )
                or item.get("connection_kind")
                != "non_orthogonal_profile_connection"
                or item.get("engineering_coordinate_inferred_from_pixels")
                is not False
                or item.get("pixel_geometry_used_for_topology_only") is not True
            ):
                continue
            physical_arc_id = str(item.get("id") or "")
            if not physical_arc_id:
                continue
            for source_id in item.get("source_ids", []):
                if (
                    isinstance(source_id, str)
                    and source_id.startswith("hybrid:curve-boundary:")
                ):
                    physical_by_curve_source[source_id].append(item)

    linked_items: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _ENGINEERING_CALLOUT_LEDGER_KIND
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            binding = record.get("profile_arc_radius_binding")
            facts = record.get("facts")
            if not (
                isinstance(binding, dict)
                and binding.get("status") == "profile_arc_candidate_backed"
                and isinstance(facts, dict)
            ):
                continue

            curve_source_id = str(binding.get("curve_source_id") or "")
            raw_radius = facts.get("radius")
            raw_bound_radius = binding.get("engineering_radius")
            radius = (
                float(raw_radius)
                if (
                    isinstance(raw_radius, (int, float))
                    and not isinstance(raw_radius, bool)
                    and float(raw_radius) > 0.0
                )
                else None
            )
            bound_radius = (
                float(raw_bound_radius)
                if (
                    isinstance(raw_bound_radius, (int, float))
                    and not isinstance(raw_bound_radius, bool)
                )
                else None
            )
            source_item_index = record.get("source_item_index")
            source_ids = list(
                dict.fromkeys(
                    [
                        *(
                            [f"hybrid:whole:{source_item_index}"]
                            if source_item_index is not None
                            else []
                        ),
                        *([curve_source_id] if curve_source_id else []),
                    ]
                )
            )
            valid_contract = (
                curve_source_id.startswith("hybrid:curve-boundary:")
                and radius is not None
                and bound_radius is not None
                and abs(radius - bound_radius) <= 1e-9
                and binding.get("engineering_value_source") == "hybrid_ocr"
                and binding.get("engineering_coordinate_inferred_from_pixels")
                is False
                and binding.get("pixel_geometry_used_for_identity_only") is True
            )
            digest = hashlib.sha256(
                "|".join(
                    [
                        str(source_item_index),
                        curve_source_id,
                        str(radius),
                    ]
                ).encode("utf-8")
            ).hexdigest()[:12].upper()

            if not valid_contract:
                unresolved.append(
                    {
                        "id": f"U_PROFILE_ARC_RADIUS_IDENTITY_{digest}",
                        "kind": "feature_value",
                        "field": "profile_arc_radius_identity",
                        "reason": (
                            "profile arc radius callout binding does not satisfy "
                            "the engineering-value and pixel-identity contract"
                        ),
                        "source_ids": source_ids,
                        "required_for_modeling": True,
                    }
                )
                continue

            matches_by_id = {
                str(item["id"]): item
                for item in physical_by_curve_source.get(
                    curve_source_id,
                    [],
                )
                if isinstance(item, dict) and str(item.get("id") or "")
            }
            if len(matches_by_id) != 1:
                unresolved.append(
                    {
                        "id": f"U_PROFILE_ARC_RADIUS_IDENTITY_{digest}",
                        "kind": "feature_inventory",
                        "field": "profile_arc_radius_identity",
                        "reason": (
                            "engineering radius callout does not map to exactly "
                            "one verified physical profile arc identity"
                        ),
                        "curve_source_id": curve_source_id,
                        "candidate_physical_arc_ids": sorted(matches_by_id),
                        "source_ids": source_ids,
                        "required_for_modeling": True,
                    }
                )
                continue

            physical_arc_id, physical_arc = next(iter(matches_by_id.items()))
            linked_source_ids = list(
                dict.fromkeys(
                    [
                        *source_ids,
                        *[
                            value
                            for value in physical_arc.get("source_ids", [])
                            if isinstance(value, str) and value
                        ],
                    ]
                )
            )
            linked_items.append(
                {
                    "id": f"PHYSICAL_ARC_RADIUS_{digest}",
                    "physical_arc_id": physical_arc_id,
                    "curve_source_id": curve_source_id,
                    "engineering_radius": radius,
                    "engineering_value_source": "hybrid_ocr",
                    "plane": physical_arc.get("plane"),
                    "rotation_axis": physical_arc.get("rotation_axis"),
                    "supporting_physical_feature_ids": list(
                        physical_arc.get(
                            "supporting_physical_feature_ids",
                            [],
                        )
                    ),
                    "supporting_physical_edges": copy.deepcopy(
                        physical_arc.get(
                            "supporting_physical_edges",
                            [],
                        )
                    ),
                    "source_ids": linked_source_ids,
                    "basis": (
                        "explicit_engineering_radius_callout_plus_"
                        "unique_physical_arc_identity"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_identity_only": True,
                }
            )

    if not linked_items:
        return [], unresolved
    linked_items.sort(
        key=lambda item: (
            str(item["physical_arc_id"]),
            str(item["curve_source_id"]),
            float(item["engineering_radius"]),
            str(item["id"]),
        )
    )
    return [
        {
            "kind": _PHYSICAL_PROFILE_ARC_RADIUS_KIND,
            "schema": "1.0",
            "items": linked_items,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        }
    ], unresolved


def _physical_profile_arc_radius_direct_values(
    observations: list[dict[str, Any]],
) -> tuple[list[DirectValueEvidence], list[dict[str, Any]]]:
    """Expose identity-linked engineering arc radii to the Resolver.

    The target lives under constraints until center/endpoints are solved, so
    radius evidence cannot masquerade as a complete canonical profile arc.
    """

    values: list[DirectValueEvidence] = []
    unresolved: list[dict[str, Any]] = []
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _PHYSICAL_PROFILE_ARC_RADIUS_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_identity_only") is not True
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            physical_arc_id = str(item.get("physical_arc_id") or "")
            raw_radius = item.get("engineering_radius")
            radius = (
                float(raw_radius)
                if (
                    isinstance(raw_radius, (int, float))
                    and not isinstance(raw_radius, bool)
                    and float(raw_radius) > 0.0
                )
                else None
            )
            source_ids = [
                source_id
                for source_id in item.get("source_ids", [])
                if isinstance(source_id, str) and source_id
            ]
            valid = (
                physical_arc_id
                and radius is not None
                and item.get("engineering_value_source") == "hybrid_ocr"
                and item.get("basis")
                == (
                    "explicit_engineering_radius_callout_plus_"
                    "unique_physical_arc_identity"
                )
                and item.get("engineering_coordinate_inferred_from_pixels")
                is False
                and item.get("pixel_geometry_used_for_identity_only") is True
            )
            stable = hashlib.sha256(
                "|".join(
                    [
                        physical_arc_id,
                        str(radius),
                        *source_ids,
                    ]
                ).encode("utf-8")
            ).hexdigest()[:12].upper()
            if not valid:
                unresolved.append(
                    {
                        "id": f"U_PROFILE_ARC_RADIUS_VALUE_{stable}",
                        "kind": "feature_value",
                        "field": "profile_arc_radius",
                        "reason": (
                            "identity-linked profile arc radius does not satisfy "
                            "the engineering-value provenance contract"
                        ),
                        "physical_arc_id": physical_arc_id or None,
                        "source_ids": source_ids,
                        "required_for_modeling": True,
                    }
                )
                continue

            target = (
                "constraints.profile_arc_radii."
                f"{physical_arc_id}.radius"
            )
            values.append(
                DirectValueEvidence(
                    id=(
                        "L_PROFILE_ARC_RADIUS_"
                        + hashlib.sha256(
                            "|".join(
                                [
                                    physical_arc_id,
                                    str(radius),
                                    *source_ids,
                                ]
                            ).encode("utf-8")
                        ).hexdigest()[:16].upper()
                    ),
                    target=target,
                    value=radius,
                    semantic="radius",
                    source_ids=[
                        *source_ids,
                        str(item.get("id") or ""),
                    ],
                )
            )

    return values, unresolved


def _oblique_dimension_projection_relations(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> list[RelationEvidence]:
    """Align a dimension extension projection with a proven exterior profile.

    The accepted dimension keeps all engineering metric authority.  Raster
    positions are used only to prove that an exact crossing extension line and
    one exterior-oblique support represent the same measured-axis coordinate.
    """

    supports_by_ref: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _ROTATIONAL_OBLIQUE_PROFILE_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("exterior_boundary_candidate") is not True
                or item.get("one_sided_boundary_candidate") is not True
            ):
                continue
            refs = item.get("supporting_profile_refs")
            entity_ids = item.get("supporting_profile_entity_ids")
            axes = item.get("supporting_profile_constant_axes")
            if not (
                isinstance(refs, list)
                and isinstance(entity_ids, list)
                and isinstance(axes, list)
                and len(refs) == len(entity_ids) == len(axes)
            ):
                continue
            region_id = str(item.get("region_id") or "")
            source_ids = [
                value
                for value in item.get("source_ids", [])
                if isinstance(value, str) and value
            ]
            for ref, entity_id, raw_axis in zip(
                refs,
                entity_ids,
                axes,
                strict=True,
            ):
                axis = str(raw_axis).upper()
                if (
                    not isinstance(ref, str)
                    or not ref
                    or not isinstance(entity_id, str)
                    or not entity_id
                    or axis not in {"X", "Y", "Z"}
                    or not region_id
                ):
                    continue
                supports_by_ref[ref].append(
                    {
                        "entity_id": entity_id,
                        "axis": axis,
                        "region_id": region_id,
                        "source_ids": source_ids,
                    }
                )

    anchor_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != "hybrid_dimension_anchor_ledger"
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id") or "")
            if candidate_id:
                anchor_records[candidate_id].append(item)

    relations: list[RelationEvidence] = []
    seen: set[tuple[str, str, str]] = set()
    for dimension in capture.dimensions:
        candidate_ids = {
            parts[1]
            for source_id in dimension.source_ids
            for parts in [source_id.split(":")]
            if (
                len(parts) == 3
                and parts[0] == "hybrid"
                and parts[1]
                and parts[2] in {"whole", "wide"}
            )
        }
        if len(candidate_ids) != 1:
            continue
        candidate_id = next(iter(candidate_ids))
        records = anchor_records.get(candidate_id, [])
        if len(records) != 1:
            continue
        record = records[0]
        endpoint_evidence = record.get("endpoint_candidate_evidence")
        if not isinstance(endpoint_evidence, dict):
            continue
        raw_endpoints = endpoint_evidence.get("endpoints")
        if (
            not isinstance(raw_endpoints, list)
            or len(raw_endpoints) != len(dimension.endpoints)
        ):
            continue

        region_id = str(record.get("region_id") or "")
        for endpoint_index, (endpoint, raw_endpoint) in enumerate(
            zip(dimension.endpoints, raw_endpoints, strict=True)
        ):
            if (
                endpoint.role != "profile_boundary"
                or not endpoint.entity_id
                or not isinstance(raw_endpoint, dict)
                or raw_endpoint.get("ownership_narrowing_basis")
                != "exact_crossing_witness_profile_line_identity"
            ):
                continue
            physical_candidates = raw_endpoint.get("physical_candidates")
            if not (
                isinstance(physical_candidates, list)
                and len(physical_candidates) == 1
                and isinstance(physical_candidates[0], dict)
                and physical_candidates[0].get("kind")
                == "profile_edge_candidate"
            ):
                continue

            witness_position = raw_endpoint.get("position_px")
            if (
                isinstance(witness_position, bool)
                or not isinstance(witness_position, (int, float))
            ):
                continue

            projected_supports: dict[tuple[str, str], dict[str, Any]] = {}
            ignored = raw_endpoint.get("ignored_nonownership_anchors")
            if not isinstance(ignored, list):
                continue
            for anchor in ignored:
                if (
                    not isinstance(anchor, dict)
                    or anchor.get("kind") != "profile_edge_candidate"
                    or anchor.get("ownership_rejection_reason")
                    != "profile_not_connected_to_witness_terminal"
                ):
                    continue
                ref = str(anchor.get("ref") or "")
                position = anchor.get("position_px")
                tolerance = anchor.get("axis_tolerance_px")
                if (
                    not ref
                    or isinstance(position, bool)
                    or not isinstance(position, (int, float))
                    or isinstance(tolerance, bool)
                    or not isinstance(tolerance, (int, float))
                    or abs(float(position) - float(witness_position))
                    > max(2.0, float(tolerance))
                ):
                    continue
                for support in supports_by_ref.get(ref, []):
                    if (
                        support["region_id"] != region_id
                        or support["axis"] != dimension.axis
                        or support["entity_id"] == endpoint.entity_id
                    ):
                        continue
                    projected_supports[
                        (support["entity_id"], support["axis"])
                    ] = {
                        **support,
                        "ref": ref,
                    }

            if len(projected_supports) != 1:
                continue
            support = next(iter(projected_supports.values()))
            owned_feature = entity_to_feature.get(endpoint.entity_id)
            support_feature = entity_to_feature.get(support["entity_id"])
            if (
                owned_feature is None
                or support_feature is None
                or owned_feature == support_feature
            ):
                continue

            axis = dimension.axis
            owned_target = (
                f"feature:{owned_feature}.boundary.{axis.lower()}"
            )
            support_target = (
                f"feature:{support_feature}.boundary.{axis.lower()}"
            )
            key = (axis, owned_target, support_target)
            if key in seen:
                continue
            seen.add(key)

            digest = hashlib.sha256(
                "|".join(
                    [
                        dimension.id,
                        str(endpoint_index),
                        axis,
                        owned_target,
                        support_target,
                    ]
                ).encode("utf-8")
            ).hexdigest()[:12].upper()
            relations.append(
                RelationEvidence(
                    id=f"R_OBLIQUE_DIMENSION_PROJECTION_{digest}",
                    kind="alignment",
                    axis=axis,
                    targets=[owned_target, support_target],
                    source_ids=list(
                        dict.fromkeys(
                            [
                                *dimension.source_ids,
                                *endpoint.source_ids,
                                *support["source_ids"],
                                (
                                    "hybrid:dimension-extension-projection:"
                                    f"{candidate_id}:{endpoint_index}"
                                ),
                            ]
                        )
                    ),
                    required_for_modeling=False,
                    metadata={
                        "basis": (
                            "accepted_dimension_extension_projection_to_"
                            "exterior_oblique_profile"
                        ),
                        "dimension_id": dimension.id,
                        "endpoint_index": endpoint_index,
                        "supporting_profile_ref": support["ref"],
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_identity_only": True,
                    },
                )
            )

    relations.sort(key=lambda item: item.id)
    return relations


def _attach_physical_oblique_fragments(
    topology_items: list[dict[str, Any]],
    oblique_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach physical non-orthogonal fragments to one unambiguous topology item."""

    output = copy.deepcopy(topology_items)
    for fragment in oblique_items:
        fragment_regions = {
            str(region_id)
            for region_id in fragment.get("region_ids", [])
            if isinstance(region_id, str) and region_id
        }
        if not fragment_regions:
            continue

        matches: list[int] = []
        for index, item in enumerate(output):
            item_regions = {
                str(region_id)
                for region_id in item.get("region_ids", [])
                if isinstance(region_id, str) and region_id
            }
            if not item_regions:
                region_id = str(item.get("region_id") or "")
                if region_id and not region_id.startswith("PHYSICAL_"):
                    item_regions = {region_id}
            if (
                item.get("plane") == fragment.get("plane")
                and item.get("rotation_axis") == fragment.get("rotation_axis")
                and item.get("view_kind") == fragment.get("view_kind")
                and fragment_regions.intersection(item_regions)
            ):
                matches.append(index)

        if len(matches) != 1:
            continue

        target = output[matches[0]]
        fragments = target.setdefault("non_orthogonal_fragments", [])
        if not isinstance(fragments, list):
            continue
        fragments.append(copy.deepcopy(fragment))
        fragments.sort(key=lambda item: str(item.get("id") or ""))

    return output


def _linked_labeled_dimension_relation_observations(
    capture: ReaderCapture,
) -> list[dict[str, Any]]:
    """Preserve validated labeled-dimension provenance without adding geometry.

    This bridge intentionally creates no RelationEvidence and no required target.
    It only carries forward OCR-authoritative values plus bounded structural
    relation semantics so a later deterministic stage can decide whether a
    unique engineering constraint exists.
    """

    output: list[dict[str, Any]] = []
    allowed_relations = {
        "overall_extent",
        "overall_min_to_profile_transition",
        "overall_max_to_profile_transition",
        "between_profile_boundaries",
    }
    allowed_geometries = {"orthogonal", "non_orthogonal", "mixed"}
    allowed_scopes = {"single", "bilateral"}

    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _LABELED_DIMENSION_RELATION_KIND
            or observation.get("schema") != "1.0"
            or observation.get("engineering_value_source") != "hybrid_ocr"
            or observation.get("relation_source") != "bounded_structural_context"
            or observation.get("engineering_coordinate_inferred_from_pixels") is not False
            or observation.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue

        raw_items = observation.get("items")
        if not isinstance(raw_items, list):
            continue

        validated_items: list[dict[str, Any]] = []
        seen_target_ids: set[str] = set()
        seen_source_indices: set[int] = set()
        valid = True
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                valid = False
                break
            target_id = raw_item.get("target_id")
            source_index = raw_item.get("source_item_index")
            source_text = raw_item.get("source_text")
            region_id = raw_item.get("region_id")
            value = raw_item.get("value")
            axis = str(raw_item.get("axis") or "").upper()
            relation = raw_item.get("relation")
            geometry = raw_item.get("profile_transition_geometry")
            scope = raw_item.get("symmetry_scope")
            evidence = raw_item.get("evidence")
            if (
                not isinstance(target_id, str)
                or not target_id
                or target_id in seen_target_ids
                or not isinstance(source_index, int)
                or isinstance(source_index, bool)
                or source_index < 0
                or source_index in seen_source_indices
                or not isinstance(source_text, str)
                or not source_text.strip()
                or not isinstance(region_id, str)
                or not region_id
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) <= 0.0
                or axis not in {"X", "Y", "Z"}
                or relation not in allowed_relations
                or (
                    geometry is not None
                    and geometry not in allowed_geometries
                )
                or (scope is not None and scope not in allowed_scopes)
                or not isinstance(evidence, list)
                or not evidence
                or not all(isinstance(item, str) and item for item in evidence)
                or raw_item.get("engineering_coordinate_inferred_from_pixels") is not False
                or raw_item.get("pixel_geometry_used_for_topology_only") is not True
            ):
                valid = False
                break
            if (
                relation == "overall_extent"
                and (geometry is not None or scope is not None)
            ):
                valid = False
                break

            seen_target_ids.add(target_id)
            seen_source_indices.add(source_index)
            validated_items.append(copy.deepcopy(raw_item))

        if not valid:
            continue

        copied = copy.deepcopy(observation)
        copied["items"] = validated_items
        output.append(copied)

    return output


def _linked_rotational_profile_topology_observations(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> list[dict[str, Any]]:
    """Attach deterministic physical boundary targets to rotational topology edges.

    The Capture ledger already proves only view-local topology.  This bridge
    adds no geometry: it maps each recorded Capture entity through the
    Identity Linker's physical identity and names the engineering boundary
    target for the edge's constant axis.  Missing/ambiguous identity stays
    unmaterialized and is handled fail-closed downstream.
    """

    observations = [
        copy.deepcopy(observation)
        for observation in capture.observations
        if not (
            isinstance(observation, dict)
            and observation.get("kind") == _LABELED_DIMENSION_RELATION_KIND
        )
    ]
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _ROTATIONAL_PROFILE_TOPOLOGY_KIND
        ):
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_topology_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            edges = item.get("edges")
            if not isinstance(edges, list):
                continue
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                entity_id = edge.get("profile_entity_id")
                axis = str(edge.get("constant_axis") or "").upper()
                if (
                    not isinstance(entity_id, str)
                    or not entity_id
                    or axis not in {"X", "Y", "Z"}
                ):
                    continue
                feature_id = entity_to_feature.get(entity_id)
                if feature_id is None:
                    continue
                edge["physical_feature_id"] = feature_id
                edge["boundary_target"] = (
                    f"feature:{feature_id}.boundary.{axis.lower()}"
                )

        linked_items = observation.get("items")
        if isinstance(linked_items, list):
            observation["items"] = _merge_physical_rotational_topology_items(
                [
                    linked_item
                    for linked_item in linked_items
                    if isinstance(linked_item, dict)
                ]
            )

    physical_oblique_items = _physical_rotational_oblique_profile_items(
        observations,
        entity_to_feature,
    )
    physical_oblique_items = _bridge_symmetric_oblique_counterpart_supports(
        capture,
        physical_oblique_items,
        entity_to_feature,
    )
    if physical_oblique_items:
        for observation in observations:
            if (
                isinstance(observation, dict)
                and observation.get("kind") == _ROTATIONAL_PROFILE_TOPOLOGY_KIND
                and isinstance(observation.get("items"), list)
            ):
                observation["items"] = _attach_physical_oblique_fragments(
                    [
                        item
                        for item in observation["items"]
                        if isinstance(item, dict)
                    ],
                    physical_oblique_items,
                )
        observations.append(
            {
                "kind": _PHYSICAL_ROTATIONAL_OBLIQUE_PROFILE_KIND,
                "schema": "1.0",
                "items": physical_oblique_items,
                "engineering_coordinate_inferred_from_pixels": False,
                "pixel_geometry_used_for_topology_only": True,
            }
        )
    return observations


def _profile_entity_ids_for_ref(
    capture: ReaderCapture,
    ref: str,
) -> list[str]:
    token = f"hybrid:profile-edge:{ref}"
    return sorted(
        item.id
        for item in capture.entities
        if (
            item.shape == "profile"
            and token in item.source_ids
            and not any(
                source_id.startswith("hybrid:profile-vertex:")
                for source_id in item.source_ids
            )
        )
    )


def _overall_extent(capture: ReaderCapture, axis: Axis) -> float:
    return {
        "X": float(capture.overall_dimensions.length_x),
        "Y": float(capture.overall_dimensions.width_y),
        "Z": float(capture.overall_dimensions.height_z),
    }[axis]


def _valid_view_axis_boundary_items(
    capture: ReaderCapture,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != _VIEW_AXIS_BOUNDARY_KIND
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("status") != "resolved"
                or item.get("engineering_coordinate_inferred_from_pixels")
                is not False
            ):
                continue
            raw_axis = str(item.get("axis") or "").upper()
            if raw_axis == "X":
                axis: Axis = "X"
            elif raw_axis == "Y":
                axis = "Y"
            elif raw_axis == "Z":
                axis = "Z"
            else:
                continue
            raw_value = item.get("overall_dimension_value")
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
                or abs(float(raw_value) - _overall_extent(capture, axis)) > 1e-9
            ):
                continue
            anchors = item.get("anchors")
            if not isinstance(anchors, list):
                continue
            roles = {
                str(anchor.get("role") or "")
                for anchor in anchors
                if isinstance(anchor, dict)
            }
            if roles != {"overall_min", "overall_max"}:
                continue
            output.append(item)
    return output


def _view_axis_boundary_relations(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> list[RelationEvidence]:
    """Bind resolved overall profile extremes to engineering boundary targets.

    The Hybrid ledger proves only which structural profile edge is the min/max
    extreme for an independently known overall dimension. The metric value
    comes from overall dimensions; raster positions are identity evidence only
    and are never converted to engineering coordinates.
    """

    views = {item.id: item for item in capture.views}
    entities = {item.id: item for item in capture.entities}
    relations: list[RelationEvidence] = []
    seen: set[tuple[str, str, str]] = set()

    for item in _valid_view_axis_boundary_items(capture):
        raw_axis = str(item["axis"]).upper()
        if raw_axis == "X":
            axis: Axis = "X"
        elif raw_axis == "Y":
            axis = "Y"
        elif raw_axis == "Z":
            axis = "Z"
        else:
            continue
        for anchor in item.get("anchors", []):
            if not isinstance(anchor, dict):
                continue
            ref = str(anchor.get("ref") or "")
            role = str(anchor.get("role") or "")
            if not ref or role not in {"overall_min", "overall_max"}:
                continue
            entity_ids = _profile_entity_ids_for_ref(capture, ref)
            if len(entity_ids) != 1:
                continue
            entity_id = entity_ids[0]
            feature_id = entity_to_feature.get(entity_id)
            if feature_id is None:
                continue
            key = (feature_id, axis, role)
            if key in seen:
                continue
            seen.add(key)

            entity = entities.get(entity_id)
            view = views.get(entity.view_id) if entity is not None else None
            source_ids = list(
                dict.fromkeys(
                    [
                        f"hybrid:profile-edge:{ref}",
                        *([] if entity is None else entity.source_ids),
                        *([] if view is None else [view.id, *view.source_ids]),
                    ]
                )
            )
            digest = hashlib.sha256(
                "|".join((feature_id, axis, role, ref)).encode("utf-8")
            ).hexdigest()[:12].upper()
            relations.append(
                RelationEvidence(
                    id=f"R_VIEW_AXIS_BOUNDARY_{digest}",
                    kind="edge_offset",
                    axis=axis,
                    value=0.0,
                    from_side="min" if role == "overall_min" else "max",
                    targets=[
                        f"feature:{feature_id}.boundary.{axis.lower()}"
                    ],
                    source_ids=source_ids,
                    required_for_modeling=False,
                    metadata={
                        "basis": (
                            "independent_overall_dimension_plus_"
                            "unique_profile_extremes"
                        ),
                        "overall_role": role,
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_identity_only": True,
                    },
                )
            )
    return relations


def _raw_fields_by_entity(capture: ReaderCapture) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = defaultdict(set)
    for item in capture.values:
        fields[item.entity_id].add(item.field)
    return fields


def _canonical_field(
    capture: ReaderCapture,
    entity_id: str,
    field: str,
) -> str:
    if field == "hole_diameter":
        return "diameter"

    raw_fields = _raw_fields_by_entity(capture).get(entity_id, set())
    if field == "depth" and "thread_spec" in raw_fields:
        return "thread_depth"

    return field


_SYMMETRIC_COUNT_TWO_MARKER = "hybrid:symmetric-count2-overall-center"
_STRUCTURED_SYMMETRIC_COUNT_TWO_KIND = "symmetric_count_two_overall_center"
_STRUCTURED_SYMMETRIC_PROFILE_SPAN_KIND = "hybrid_symmetric_profile_span_ledger"
_PROFILE_SPAN_CENTER_KIND = "hybrid_profile_span_center_ledger"
_DIMENSION_SPAN_CENTER_IDENTITY_KIND = (
    "hybrid_dimension_span_center_identity_ledger"
)
_SYMMETRIC_DIMENSION_PAIR_KIND = "hybrid_symmetric_dimension_pair_ledger"
_PROJECTED_PROFILE_LEVEL_KIND = "hybrid_projected_profile_level_ledger"

_TRANSVERSE_CENTER_INDEX: dict[Axis, dict[Axis, int]] = {
    "X": {"Y": 0, "Z": 1},
    "Y": {"X": 0, "Z": 1},
    "Z": {"X": 0, "Y": 1},
}

_VIEW_NORMAL_AXIS: dict[str, Axis] = {
    "front": "Y",
    "side": "X",
    "top": "Z",
}
_ALL_AXES: tuple[Axis, ...] = ("X", "Y", "Z")
_CIRCULAR_PROJECTION_SHAPES = {"circle", "concentric_circles"}


def _component_axis_from_projections(
    capture: ReaderCapture,
    entity_ids: list[str],
) -> tuple[Axis | None, list[str]]:
    """Infer a principal cylindrical axis from orthographic projection classes."""

    entities = {item.id: item for item in capture.entities}
    views = {item.id: item for item in capture.views}
    candidates: set[Axis] = set(_ALL_AXES)
    evidence: list[str] = []
    constrained = False

    for entity_id in entity_ids:
        entity = entities.get(entity_id)
        if entity is None:
            continue
        view = views.get(entity.view_id)
        if view is None:
            continue
        normal = _VIEW_NORMAL_AXIS[view.kind]

        if entity.shape in _CIRCULAR_PROJECTION_SHAPES:
            allowed: set[Axis] = {normal}
        elif entity.shape == "hidden_parallel":
            allowed = set(_ALL_AXES)
            allowed.discard(normal)
        else:
            continue

        constrained = True
        candidates.intersection_update(allowed)
        evidence.extend([entity.id, *entity.source_ids, view.id, *view.source_ids])

    if constrained and len(candidates) == 1:
        return next(iter(candidates)), list(dict.fromkeys(evidence))
    return None, list(dict.fromkeys(evidence))


def _structured_symmetric_count_two_sources(
    capture: ReaderCapture,
    *,
    feature_id: str,
    axis: str,
    entity_to_feature: dict[str, str],
) -> list[str]:
    source_ids: list[str] = []
    for observation in capture.observations:
        if observation.get("kind") != _STRUCTURED_SYMMETRIC_COUNT_TWO_KIND:
            continue
        if observation.get("axis") != axis or observation.get("datum") != "overall_center":
            continue
        entity_id = observation.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        if entity_to_feature.get(entity_id) != feature_id:
            continue
        observation_id = observation.get("id")
        if isinstance(observation_id, str) and observation_id:
            source_ids.append(observation_id)
        raw_sources = observation.get("source_ids")
        if isinstance(raw_sources, list):
            source_ids.extend(item for item in raw_sources if isinstance(item, str) and item)
    return list(dict.fromkeys(source_ids))


def _profile_span_constraint_identity(
    *,
    axis: Axis,
    boundary_targets: list[str],
) -> tuple[str, str] | None:
    if len(boundary_targets) != 2 or len(set(boundary_targets)) != 2:
        return None

    ordered_boundaries = sorted(boundary_targets)
    identity_payload = json.dumps(
        {
            "axis": axis,
            "boundaries": ordered_boundaries,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(identity_payload).hexdigest()[:16].upper()
    center_target = f"constraints.span_centers.C_{digest}.{axis.lower()}"
    return digest, center_target


def _profile_span_midpoint_relation(
    *,
    dimension: CaptureDimension,
    boundary_targets: list[str],
    endpoint_source_ids: list[str],
) -> RelationEvidence | None:
    """Create a stable midpoint constraint for one resolved profile span."""

    identity = _profile_span_constraint_identity(
        axis=dimension.axis,
        boundary_targets=boundary_targets,
    )
    if identity is None:
        return None
    digest, center_target = identity
    return RelationEvidence(
        id=f"R_PROFILE_SPAN_MIDPOINT_{digest}",
        kind="midpoint",
        axis=dimension.axis,
        targets=[
            boundary_targets[0],
            center_target,
            boundary_targets[1],
        ],
        source_ids=list(
            dict.fromkeys(
                [
                    *dimension.source_ids,
                    *endpoint_source_ids,
                ]
            )
        ),
        required_for_modeling=False,
        metadata={
            "basis": "resolved_profile_boundary_span_midpoint",
            "constraint_target": center_target,
            "engineering_coordinate_inferred_from_pixels": False,
        },
    )


def _profile_span_centered_relation(
    *,
    dimension: CaptureDimension,
    boundary_targets: list[str],
    endpoint_source_ids: list[str],
) -> RelationEvidence | None:
    """Bind a resolved profile span width to its non-modeling center target."""

    identity = _profile_span_constraint_identity(
        axis=dimension.axis,
        boundary_targets=boundary_targets,
    )
    if identity is None:
        return None
    digest, center_target = identity
    return RelationEvidence(
        id=f"R_PROFILE_SPAN_CENTERED_{digest}",
        kind="centered_span",
        axis=dimension.axis,
        value=dimension.value,
        direction=dimension.direction,
        targets=[
            boundary_targets[0],
            center_target,
            boundary_targets[1],
        ],
        source_ids=list(
            dict.fromkeys(
                [
                    *dimension.source_ids,
                    *endpoint_source_ids,
                ]
            )
        ),
        required_for_modeling=False,
        metadata={
            "basis": "resolved_profile_boundary_span_width_and_midpoint",
            "constraint_target": center_target,
            "engineering_coordinate_inferred_from_pixels": False,
        },
    )


def _profile_span_boundary_targets(
    dimension: CaptureDimension,
    entity_to_feature: dict[str, str],
) -> list[str] | None:
    if any(endpoint.role == "unresolved" for endpoint in dimension.endpoints):
        return None
    if not all(
        endpoint.role == "profile_boundary" and endpoint.entity_id
        for endpoint in dimension.endpoints
    ):
        return None

    axis_leaf = dimension.axis.lower()
    targets: list[str] = []
    for endpoint in dimension.endpoints:
        assert endpoint.entity_id is not None
        feature_id = entity_to_feature.get(endpoint.entity_id)
        if feature_id is None:
            return None
        targets.append(f"feature:{feature_id}.boundary.{axis_leaf}")
    if len(set(targets)) != 2:
        return None
    return targets


def _validated_profile_span_centers(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Return only structurally traceable profile-span center identities."""

    dimension_by_id = {item.id: item for item in capture.dimensions}
    records_by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for observation in capture.observations:
        if observation.get("kind") != _PROFILE_SPAN_CENTER_KIND:
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_identity_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            dimension_id = record.get("dimension_id")
            if not isinstance(dimension_id, str) or not dimension_id:
                continue
            dimension = dimension_by_id.get(dimension_id)
            if dimension is None or record.get("axis") != dimension.axis:
                continue
            if record.get("basis") != "resolved_profile_boundary_span_midpoint":
                continue
            raw_entities = record.get("profile_entity_ids")
            endpoint_entities = [
                endpoint.entity_id
                for endpoint in dimension.endpoints
                if endpoint.role == "profile_boundary" and endpoint.entity_id
            ]
            if (
                not isinstance(raw_entities, list)
                or raw_entities != endpoint_entities
                or len(endpoint_entities) != 2
            ):
                continue
            raw_pair = record.get("selected_witness_positions_px")
            raw_midpoint = record.get("span_midpoint_px")
            if not (
                isinstance(raw_pair, list)
                and len(raw_pair) == 2
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    for value in raw_pair
                )
                and isinstance(raw_midpoint, (int, float))
                and not isinstance(raw_midpoint, bool)
            ):
                continue

            boundary_targets = _profile_span_boundary_targets(
                dimension,
                entity_to_feature,
            )
            if boundary_targets is None:
                continue
            identity = _profile_span_constraint_identity(
                axis=dimension.axis,
                boundary_targets=boundary_targets,
            )
            if identity is None:
                continue
            _digest, center_target = identity
            raw_sources = record.get("source_ids")
            source_ids = [
                item
                for item in raw_sources
                if isinstance(item, str) and item
            ] if isinstance(raw_sources, list) else []
            records_by_dimension[dimension_id].append(
                {
                    "target": center_target,
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *dimension.source_ids,
                                *source_ids,
                            ]
                        )
                    ),
                }
            )

    return {
        dimension_id: records[0]
        for dimension_id, records in records_by_dimension.items()
        if len(records) == 1
    }


def _span_center_identity_matches_by_endpoint(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    span_centers: dict[str, dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """Collect evidence-backed span-center matches for intermediate endpoints."""

    unresolved_indices = {
        index
        for index, endpoint in enumerate(dimension.endpoints)
        if (
            endpoint.role == "unresolved"
            and endpoint.unresolved_kind == "intermediate_surface"
        )
    }
    matches_by_index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not unresolved_indices:
        return matches_by_index

    for observation in capture.observations:
        if observation.get("kind") != _DIMENSION_SPAN_CENTER_IDENTITY_KIND:
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_identity_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            if record.get("dimension_id") != dimension.id:
                continue
            if record.get("axis") != dimension.axis:
                continue
            if record.get("basis") != (
                "unique_witness_to_resolved_profile_span_midpoint"
            ):
                continue
            endpoint_index = record.get("endpoint_index")
            if (
                not isinstance(endpoint_index, int)
                or isinstance(endpoint_index, bool)
                or endpoint_index not in unresolved_indices
            ):
                continue
            span_dimension_id = record.get("span_dimension_id")
            if (
                not isinstance(span_dimension_id, str)
                or not span_dimension_id
                or span_dimension_id == dimension.id
            ):
                continue
            span_center = span_centers.get(span_dimension_id)
            if span_center is None:
                continue
            raw_sources = record.get("source_ids")
            source_ids = (
                [
                    item
                    for item in raw_sources
                    if isinstance(item, str) and item
                ]
                if isinstance(raw_sources, list)
                else []
            )
            matches_by_index[endpoint_index].append(
                {
                    "target": span_center["target"],
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *span_center["source_ids"],
                                *source_ids,
                            ]
                        )
                    ),
                }
            )
    return matches_by_index


def _validated_symmetric_dimension_pairs(
    capture: ReaderCapture,
) -> dict[str, dict[str, Any]]:
    """Return unique centered-dimension topology records tied to capture dimensions."""

    dimension_by_id = {item.id: item for item in capture.dimensions}
    by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for observation in capture.observations:
        if observation.get("kind") != _SYMMETRIC_DIMENSION_PAIR_KIND:
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_identity_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            dimension_id = record.get("dimension_id")
            if not isinstance(dimension_id, str) or not dimension_id:
                continue
            dimension = dimension_by_id.get(dimension_id)
            if dimension is None:
                continue
            if record.get("axis") != dimension.axis:
                continue
            if record.get("datum") != "overall_center":
                continue
            if record.get("basis") != (
                "rotational_symmetry_plus_structurally_shared_raster_view"
                "_plus_overall_witness_midpoint"
            ):
                continue
            raw_dimension_value = record.get("dimension_value")
            raw_overall_value = record.get("overall_dimension_value")
            if (
                isinstance(raw_dimension_value, bool)
                or not isinstance(raw_dimension_value, (int, float))
                or isinstance(raw_overall_value, bool)
                or not isinstance(raw_overall_value, (int, float))
            ):
                continue
            overall_value = {
                "X": capture.overall_dimensions.length_x,
                "Y": capture.overall_dimensions.width_y,
                "Z": capture.overall_dimensions.height_z,
            }[dimension.axis]
            if (
                abs(float(raw_dimension_value) - float(dimension.value)) > 1e-9
                or abs(float(raw_overall_value) - float(overall_value)) > 1e-9
                or float(dimension.value) <= 0
                or float(dimension.value) >= float(overall_value)
            ):
                continue

            selected_pair = record.get("selected_witness_positions_px")
            overall_pair = record.get("overall_witness_positions_px")
            if not (
                isinstance(selected_pair, list)
                and len(selected_pair) == 2
                and isinstance(overall_pair, list)
                and len(overall_pair) == 2
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    for value in [*selected_pair, *overall_pair]
                )
            ):
                continue
            selected_low, selected_high = sorted(float(v) for v in selected_pair)
            overall_low, overall_high = sorted(float(v) for v in overall_pair)
            overall_span = overall_high - overall_low
            if (
                selected_high <= selected_low
                or overall_span <= 0
                or selected_low < overall_low
                or selected_high > overall_high
            ):
                continue
            tolerance = max(2.0, overall_span * 0.015)
            residual = abs(
                (selected_low + selected_high) / 2.0
                - (overall_low + overall_high) / 2.0
            )
            if residual > tolerance:
                continue

            candidate_id = str(record.get("candidate_id") or "")
            if not candidate_id:
                continue
            if not {
                f"hybrid:{candidate_id}:whole",
                f"hybrid:{candidate_id}:wide",
            }.intersection(dimension.source_ids):
                continue

            raw_sources = record.get("source_ids")
            source_ids = (
                [
                    item
                    for item in raw_sources
                    if isinstance(item, str) and item
                ]
                if isinstance(raw_sources, list)
                else []
            )
            by_dimension[dimension_id].append(
                {
                    "overall_value": float(overall_value),
                    "source_ids": list(
                        dict.fromkeys(
                            [
                                *dimension.source_ids,
                                *source_ids,
                            ]
                        )
                    ),
                }
            )

    return {
        dimension_id: records[0]
        for dimension_id, records in by_dimension.items()
        if len(records) == 1
    }


def _symmetric_center_distance_bridge(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    span_centers: dict[str, dict[str, Any]],
    symmetric_pairs: dict[str, dict[str, Any]],
) -> list[RelationEvidence] | None:
    """Anchor one identified center and its mirror from engineering dimensions."""

    pair = symmetric_pairs.get(dimension.id)
    if pair is None or dimension.direction not in {-1, 1}:
        return None
    if len(dimension.endpoints) != 2:
        return None
    if any(
        endpoint.role != "unresolved"
        or endpoint.unresolved_kind != "intermediate_surface"
        for endpoint in dimension.endpoints
    ):
        return None

    matches = _span_center_identity_matches_by_endpoint(
        capture,
        dimension=dimension,
        span_centers=span_centers,
    )
    if any(len(items) > 1 for items in matches.values()):
        return None
    unique_matches = {
        index: items[0]
        for index, items in matches.items()
        if len(items) == 1
    }
    if len(unique_matches) != 1:
        return None

    matched_index, match = next(iter(unique_matches.items()))
    overall_value = float(pair["overall_value"])
    distance = float(dimension.value)
    offset = (overall_value - distance) / 2.0
    if offset < 0:
        return None

    if dimension.direction == 1:
        matched_side: Literal["min", "max"] = (
            "min" if matched_index == 0 else "max"
        )
    else:
        matched_side = "max" if matched_index == 0 else "min"

    known_target = str(match["target"])
    identity_payload = json.dumps(
        {
            "axis": dimension.axis,
            "known_target": known_target,
            "distance": distance,
            "overall": overall_value,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(identity_payload).hexdigest()[:16].upper()
    mirror_target = (
        f"constraints.symmetric_centers.C_{digest}.{dimension.axis.lower()}"
    )

    if matched_side == "min":
        min_target, max_target = known_target, mirror_target
    else:
        min_target, max_target = mirror_target, known_target

    source_ids = list(
        dict.fromkeys(
            [
                *dimension.source_ids,
                *[
                    source_id
                    for endpoint in dimension.endpoints
                    for source_id in endpoint.source_ids
                ],
                *match["source_ids"],
                *pair["source_ids"],
            ]
        )
    )
    metadata = {
        "basis": "overall_center_symmetric_center_distance",
        "matched_span_center_endpoint_index": matched_index,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }

    return [
        RelationEvidence(
            id=f"R_SYMMETRIC_CENTER_PAIR_{digest}_MIN",
            kind="edge_offset",
            axis=dimension.axis,
            value=offset,
            from_side="min",
            targets=[min_target],
            source_ids=source_ids,
            required_for_modeling=False,
            metadata=metadata,
        ),
        RelationEvidence(
            id=f"R_SYMMETRIC_CENTER_PAIR_{digest}_MAX",
            kind="edge_offset",
            axis=dimension.axis,
            value=offset,
            from_side="max",
            targets=[max_target],
            source_ids=source_ids,
            required_for_modeling=False,
            metadata=metadata,
        ),
        RelationEvidence(
            id=dimension.id,
            kind="center_distance",
            axis=dimension.axis,
            value=distance,
            direction=1,
            targets=[min_target, max_target],
            source_ids=source_ids,
            required_for_modeling=dimension.required_for_modeling,
            metadata=metadata,
        ),
    ]


def _projected_profile_endpoint_matches(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    entity_to_feature: dict[str, str],
) -> dict[int, list[dict[str, Any]]]:
    """Collect unique physical profile-level projections per unresolved endpoint."""

    unresolved_indices = {
        index
        for index, endpoint in enumerate(dimension.endpoints)
        if (
            endpoint.role == "unresolved"
            and endpoint.unresolved_kind == "intermediate_surface"
        )
    }
    matches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not unresolved_indices:
        return matches

    entity_by_id = {item.id: item for item in capture.entities}
    for observation in capture.observations:
        if observation.get("kind") != _PROJECTED_PROFILE_LEVEL_KIND:
            continue
        if observation.get("engineering_coordinate_inferred_from_pixels") is not False:
            continue
        if observation.get("pixel_geometry_used_for_identity_only") is not True:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue

        for record in items:
            if not isinstance(record, dict):
                continue
            if record.get("dimension_id") != dimension.id:
                continue
            if record.get("axis") != dimension.axis:
                continue
            if record.get("basis") != (
                "extension_line_projection_to_structural_profile_level"
            ):
                continue
            endpoint_index = record.get("endpoint_index")
            if (
                not isinstance(endpoint_index, int)
                or isinstance(endpoint_index, bool)
                or endpoint_index not in unresolved_indices
            ):
                continue

            candidate_id = str(record.get("candidate_id") or "")
            if not candidate_id:
                continue
            if not {
                f"hybrid:{candidate_id}:whole",
                f"hybrid:{candidate_id}:wide",
            }.intersection(dimension.source_ids):
                continue

            raw_entity_ids = record.get("profile_entity_ids")
            raw_refs = record.get("profile_refs")
            if not (
                isinstance(raw_entity_ids, list)
                and raw_entity_ids
                and len(set(raw_entity_ids)) == len(raw_entity_ids)
                and all(
                    isinstance(entity_id, str) and entity_id
                    for entity_id in raw_entity_ids
                )
                and isinstance(raw_refs, list)
                and raw_refs
                and all(isinstance(ref, str) and ref for ref in raw_refs)
            ):
                continue

            entities = [
                entity_by_id.get(entity_id)
                for entity_id in raw_entity_ids
            ]
            if any(
                entity is None or entity.shape != "profile"
                for entity in entities
            ):
                continue
            if any(
                not any(
                    f"hybrid:profile-edge:{ref}" in entity.source_ids
                    for entity in entities
                    if entity is not None
                )
                for ref in raw_refs
            ):
                continue

            raw_sources = record.get("source_ids")
            record_sources = (
                [
                    source_id
                    for source_id in raw_sources
                    if isinstance(source_id, str) and source_id
                ]
                if isinstance(raw_sources, list)
                else []
            )
            entity_sources = [
                source_id
                for entity in entities
                if entity is not None
                for source_id in entity.source_ids
            ]
            source_ids = list(
                dict.fromkeys(
                    [
                        *dimension.source_ids,
                        *record_sources,
                        *entity_sources,
                    ]
                )
            )

            overall_role = record.get("overall_role")
            if overall_role in {"overall_min", "overall_max"}:
                matches[endpoint_index].append(
                    {
                        "role": overall_role,
                        "target": None,
                        "source_ids": source_ids,
                    }
                )
                continue
            if overall_role is not None:
                continue
            if any(
                entity_id not in entity_to_feature
                for entity_id in raw_entity_ids
            ):
                continue

            targets = {
                (
                    f"feature:{entity_to_feature[entity_id]}"
                    f".boundary.{dimension.axis.lower()}"
                )
                for entity_id in raw_entity_ids
            }
            if not targets:
                continue
            for target in sorted(targets):
                matches[endpoint_index].append(
                    {
                        "role": "profile",
                        "target": target,
                        "source_ids": source_ids,
                    }
                )

    return matches


def _symmetric_intermediate_surface_bridge(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    entity_to_feature: dict[str, str],
    span_centers: dict[str, dict[str, Any]],
    symmetric_pairs: dict[str, dict[str, Any]],
) -> list[RelationEvidence] | None:
    """Preserve a proven centered span without inventing physical endpoint owners.

    The engineering distance and overall-center symmetry are authoritative.
    Raster witness positions are used only to validate the symmetric identity;
    the resulting targets stay virtual until a later topology/materialization
    stage can bind them to physical profile geometry.
    """

    pair = symmetric_pairs.get(dimension.id)
    if pair is None or dimension.direction not in {-1, 1}:
        return None
    if len(dimension.endpoints) != 2:
        return None
    if any(
        endpoint.role != "unresolved"
        or endpoint.unresolved_kind != "intermediate_surface"
        for endpoint in dimension.endpoints
    ):
        return None

    projected_matches = _projected_profile_endpoint_matches(
        capture,
        dimension=dimension,
        entity_to_feature=entity_to_feature,
    )
    if any(projected_matches.get(index) for index in range(2)):
        return None

    span_matches = _span_center_identity_matches_by_endpoint(
        capture,
        dimension=dimension,
        span_centers=span_centers,
    )
    if any(span_matches.get(index) for index in range(2)):
        return None

    overall_value = float(pair["overall_value"])
    distance = float(dimension.value)
    offset = (overall_value - distance) / 2.0
    if offset < 0:
        return None

    identity_payload = json.dumps(
        {
            "axis": dimension.axis,
            "distance": distance,
            "overall": overall_value,
            "source_ids": sorted(pair["source_ids"]),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(identity_payload).hexdigest()[:16].upper()
    axis_leaf = dimension.axis.lower()
    min_target = (
        "constraints.symmetric_profile_levels."
        f"C_{digest}_MIN.{axis_leaf}"
    )
    max_target = (
        "constraints.symmetric_profile_levels."
        f"C_{digest}_MAX.{axis_leaf}"
    )

    source_ids = list(
        dict.fromkeys(
            [
                *dimension.source_ids,
                *[
                    source_id
                    for endpoint in dimension.endpoints
                    for source_id in endpoint.source_ids
                ],
                *pair["source_ids"],
            ]
        )
    )
    metadata = {
        "basis": "overall_center_symmetric_intermediate_surface_span",
        "physical_endpoint_ownership_unresolved": True,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }

    return [
        RelationEvidence(
            id=f"R_SYMMETRIC_INTERMEDIATE_{digest}_MIN",
            kind="edge_offset",
            axis=dimension.axis,
            value=offset,
            from_side="min",
            targets=[min_target],
            source_ids=source_ids,
            required_for_modeling=False,
            metadata=metadata,
        ),
        RelationEvidence(
            id=f"R_SYMMETRIC_INTERMEDIATE_{digest}_MAX",
            kind="edge_offset",
            axis=dimension.axis,
            value=offset,
            from_side="max",
            targets=[max_target],
            source_ids=source_ids,
            required_for_modeling=False,
            metadata=metadata,
        ),
        RelationEvidence(
            id=dimension.id,
            kind="coordinate_distance",
            axis=dimension.axis,
            value=distance,
            direction=1,
            targets=[min_target, max_target],
            source_ids=source_ids,
            required_for_modeling=dimension.required_for_modeling,
            metadata=metadata,
        ),
    ]


def _projected_profile_dimension_bridge(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    entity_to_feature: dict[str, str],
    symmetric_pairs: dict[str, dict[str, Any]],
) -> list[RelationEvidence] | None:
    """Promote fully proven projected profile levels to engineering relations."""

    unresolved_indices = [
        index
        for index, endpoint in enumerate(dimension.endpoints)
        if endpoint.role == "unresolved"
    ]
    if not unresolved_indices:
        return None
    if any(
        dimension.endpoints[index].unresolved_kind != "intermediate_surface"
        for index in unresolved_indices
    ):
        return None

    matches = _projected_profile_endpoint_matches(
        capture,
        dimension=dimension,
        entity_to_feature=entity_to_feature,
    )
    if any(len(matches.get(index, [])) > 1 for index in unresolved_indices):
        return None

    unique_matches = {
        index: matches[index][0]
        for index in unresolved_indices
        if len(matches.get(index, [])) == 1
    }
    if len(unique_matches) != len(unresolved_indices):
        pair = symmetric_pairs.get(dimension.id)
        if (
            len(unresolved_indices) != 2
            or len(unique_matches) != 1
            or pair is None
            or dimension.direction not in {-1, 1}
        ):
            return None

        matched_index, match = next(iter(unique_matches.items()))
        if match.get("role") != "profile":
            return None
        known_target = match.get("target")
        if not isinstance(known_target, str) or not known_target:
            return None

        overall_value = float(pair["overall_value"])
        distance = float(dimension.value)
        offset = (overall_value - distance) / 2.0
        if offset < 0:
            return None

        if dimension.direction == 1:
            matched_side: Literal["min", "max"] = (
                "min" if matched_index == 0 else "max"
            )
        else:
            matched_side = "max" if matched_index == 0 else "min"

        identity_payload = json.dumps(
            {
                "axis": dimension.axis,
                "known_target": known_target,
                "distance": distance,
                "overall": overall_value,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(identity_payload).hexdigest()[:16].upper()
        mirror_target = (
            "constraints.symmetric_profile_levels."
            f"C_{digest}.{dimension.axis.lower()}"
        )

        if matched_side == "min":
            min_target, max_target = known_target, mirror_target
        else:
            min_target, max_target = mirror_target, known_target

        source_ids = list(
            dict.fromkeys(
                [
                    *dimension.source_ids,
                    *[
                        source_id
                        for endpoint in dimension.endpoints
                        for source_id in endpoint.source_ids
                    ],
                    *match["source_ids"],
                    *pair["source_ids"],
                ]
            )
        )
        metadata = {
            "basis": "overall_center_symmetric_projected_profile_level",
            "matched_projected_profile_endpoint_index": matched_index,
            "engineering_coordinate_inferred_from_pixels": False,
            "pixel_geometry_used_for_identity_only": True,
        }

        return [
            RelationEvidence(
                id=f"R_PROJECTED_PROFILE_MIRROR_{digest}_MIN",
                kind="edge_offset",
                axis=dimension.axis,
                value=offset,
                from_side="min",
                targets=[min_target],
                source_ids=source_ids,
                required_for_modeling=False,
                metadata=metadata,
            ),
            RelationEvidence(
                id=f"R_PROJECTED_PROFILE_MIRROR_{digest}_MAX",
                kind="edge_offset",
                axis=dimension.axis,
                value=offset,
                from_side="max",
                targets=[max_target],
                source_ids=source_ids,
                required_for_modeling=False,
                metadata=metadata,
            ),
            RelationEvidence(
                id=dimension.id,
                kind="coordinate_distance",
                axis=dimension.axis,
                value=distance,
                direction=1,
                targets=[min_target, max_target],
                source_ids=source_ids,
                required_for_modeling=dimension.required_for_modeling,
                metadata=metadata,
            ),
        ]

    axis_leaf = dimension.axis.lower()
    specs: list[tuple[str, str | None]] = []
    source_ids = list(dimension.source_ids)
    projected_indices: list[int] = []

    for index, endpoint in enumerate(dimension.endpoints):
        source_ids.extend(endpoint.source_ids)
        if endpoint.role == "unresolved":
            match = matches[index][0]
            specs.append((str(match["role"]), match.get("target")))
            source_ids.extend(match["source_ids"])
            projected_indices.append(index)
            continue

        known = _known_dimension_endpoint_target(
            endpoint,
            axis_leaf=axis_leaf,
            entity_to_feature=entity_to_feature,
        )
        if known is None:
            return None
        specs.append(known)

    source_ids = list(dict.fromkeys(source_ids))
    metadata = {
        "basis": "dimension_endpoint_resolved_by_projected_profile_level",
        "projected_profile_endpoint_indices": projected_indices,
        "engineering_coordinate_inferred_from_pixels": False,
        "pixel_geometry_used_for_identity_only": True,
    }

    overall = [
        (index, role)
        for index, (role, _target) in enumerate(specs)
        if role in {"overall_min", "overall_max"}
    ]
    if overall:
        if len(overall) != 1:
            return None
        other_index = 1 - overall[0][0]
        other_target = specs[other_index][1]
        if other_target is None:
            return None
        from_side: Literal["min", "max"] = (
            "min" if overall[0][1] == "overall_min" else "max"
        )
        return [
            RelationEvidence(
                id=dimension.id,
                kind="edge_offset",
                axis=dimension.axis,
                value=dimension.value,
                from_side=from_side,
                targets=[other_target],
                source_ids=source_ids,
                required_for_modeling=dimension.required_for_modeling,
                metadata=metadata,
            )
        ]

    targets = [target for _role, target in specs if target is not None]
    if len(targets) != 2 or len(set(targets)) != 2:
        return None

    pair = symmetric_pairs.get(dimension.id)
    if (
        pair is not None
        and [role for role, _target in specs] == ["profile", "profile"]
        and dimension.direction in {-1, 1}
    ):
        overall_value = float(pair["overall_value"])
        offset = (overall_value - float(dimension.value)) / 2.0
        if offset < 0:
            return None
        if dimension.direction == 1:
            min_target, max_target = targets
        else:
            max_target, min_target = targets

        symmetric_sources = list(
            dict.fromkeys([*source_ids, *pair["source_ids"]])
        )
        symmetric_metadata = {
            **metadata,
            "basis": "overall_center_symmetric_projected_profile_levels",
        }
        digest_payload = json.dumps(
            {
                "axis": dimension.axis,
                "min_target": min_target,
                "max_target": max_target,
                "distance": dimension.value,
                "overall": overall_value,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(digest_payload).hexdigest()[:16].upper()
        return [
            RelationEvidence(
                id=f"R_PROJECTED_PROFILE_SYMMETRY_{digest}_MIN",
                kind="edge_offset",
                axis=dimension.axis,
                value=offset,
                from_side="min",
                targets=[min_target],
                source_ids=symmetric_sources,
                required_for_modeling=False,
                metadata=symmetric_metadata,
            ),
            RelationEvidence(
                id=f"R_PROJECTED_PROFILE_SYMMETRY_{digest}_MAX",
                kind="edge_offset",
                axis=dimension.axis,
                value=offset,
                from_side="max",
                targets=[max_target],
                source_ids=symmetric_sources,
                required_for_modeling=False,
                metadata=symmetric_metadata,
            ),
            RelationEvidence(
                id=dimension.id,
                kind="coordinate_distance",
                axis=dimension.axis,
                value=dimension.value,
                direction=1,
                targets=[min_target, max_target],
                source_ids=symmetric_sources,
                required_for_modeling=dimension.required_for_modeling,
                metadata=symmetric_metadata,
            ),
        ]

    return [
        RelationEvidence(
            id=dimension.id,
            kind="coordinate_distance",
            axis=dimension.axis,
            value=dimension.value,
            direction=dimension.direction,
            targets=targets,
            source_ids=source_ids,
            required_for_modeling=dimension.required_for_modeling,
            metadata=metadata,
        )
    ]


def _dimension_span_center_endpoint_matches(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    span_centers: dict[str, dict[str, Any]],
) -> dict[int, dict[str, Any]] | None:
    """Resolve every intermediate-surface endpoint through unique span identity."""

    unresolved_indices = [
        index
        for index, endpoint in enumerate(dimension.endpoints)
        if endpoint.role == "unresolved"
    ]
    if not unresolved_indices:
        return None
    if any(
        dimension.endpoints[index].unresolved_kind != "intermediate_surface"
        for index in unresolved_indices
    ):
        return None

    matches_by_index = _span_center_identity_matches_by_endpoint(
        capture,
        dimension=dimension,
        span_centers=span_centers,
    )

    if any(len(matches_by_index.get(index, [])) != 1 for index in unresolved_indices):
        return None
    result = {
        index: matches_by_index[index][0]
        for index in unresolved_indices
    }
    targets = [item["target"] for item in result.values()]
    if len(set(targets)) != len(targets):
        return None
    return result


def _known_dimension_endpoint_target(
    endpoint: Any,
    *,
    axis_leaf: str,
    entity_to_feature: dict[str, str],
) -> tuple[str, str | None] | None:
    if endpoint.role in {"overall_min", "overall_max"}:
        return endpoint.role, None
    if endpoint.role not in {"entity_center", "profile_boundary"}:
        return None
    if not endpoint.entity_id:
        return None
    feature_id = entity_to_feature.get(endpoint.entity_id)
    if feature_id is None:
        return None
    if endpoint.role == "entity_center":
        return "center", f"feature:{feature_id}.centerline.{axis_leaf}"
    return "profile", f"feature:{feature_id}.boundary.{axis_leaf}"


def _dimension_relation_from_span_center_identity(
    *,
    dimension: CaptureDimension,
    endpoint_matches: dict[int, dict[str, Any]],
    entity_to_feature: dict[str, str],
) -> RelationEvidence | None:
    """Promote one fully covered unresolved dimension to a formal relation."""

    axis_leaf = dimension.axis.lower()
    specs: list[tuple[str, str | None]] = []
    source_ids = list(dimension.source_ids)

    for index, endpoint in enumerate(dimension.endpoints):
        source_ids.extend(endpoint.source_ids)
        if endpoint.role == "unresolved":
            match = endpoint_matches.get(index)
            if match is None:
                return None
            specs.append(("center", str(match["target"])))
            source_ids.extend(match["source_ids"])
            continue
        known = _known_dimension_endpoint_target(
            endpoint,
            axis_leaf=axis_leaf,
            entity_to_feature=entity_to_feature,
        )
        if known is None:
            return None
        specs.append(known)

    overall = [
        (index, role)
        for index, (role, _target) in enumerate(specs)
        if role in {"overall_min", "overall_max"}
    ]
    if overall:
        if len(overall) != 1:
            return None
        measured_index = 1 - overall[0][0]
        measured_target = specs[measured_index][1]
        if measured_target is None:
            return None
        from_side: Literal["min", "max"] = (
            "min" if overall[0][1] == "overall_min" else "max"
        )
        return RelationEvidence(
            id=dimension.id,
            kind="edge_offset",
            axis=dimension.axis,
            value=dimension.value,
            from_side=from_side,
            targets=[measured_target],
            source_ids=list(dict.fromkeys(source_ids)),
            required_for_modeling=dimension.required_for_modeling,
            metadata={
                "basis": "dimension_endpoint_resolved_by_profile_span_center_identity",
                "span_center_endpoint_indices": sorted(endpoint_matches),
                "engineering_coordinate_inferred_from_pixels": False,
            },
        )

    targets = [target for _role, target in specs if target is not None]
    if len(targets) != 2 or len(set(targets)) != 2:
        return None
    roles = [role for role, _target in specs]
    kind: Literal["center_distance", "coordinate_distance"] = (
        "center_distance"
        if roles == ["center", "center"]
        else "coordinate_distance"
    )
    return RelationEvidence(
        id=dimension.id,
        kind=kind,
        axis=dimension.axis,
        value=dimension.value,
        direction=dimension.direction,
        targets=targets,
        source_ids=list(dict.fromkeys(source_ids)),
        required_for_modeling=dimension.required_for_modeling,
        metadata={
            "basis": "dimension_endpoint_resolved_by_profile_span_center_identity",
            "span_center_endpoint_indices": sorted(endpoint_matches),
            "engineering_coordinate_inferred_from_pixels": False,
        },
    )


def _structured_symmetric_profile_span_sources(
    capture: ReaderCapture,
    *,
    dimension: CaptureDimension,
    endpoint_entity_ids: list[str],
) -> list[str]:
    if len(endpoint_entity_ids) != 2 or len(set(endpoint_entity_ids)) != 2:
        return []

    source_ids: list[str] = []
    for observation in capture.observations:
        if observation.get("kind") != _STRUCTURED_SYMMETRIC_PROFILE_SPAN_KIND:
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for record in items:
            if not isinstance(record, dict):
                continue
            if record.get("axis") != dimension.axis or record.get("datum") != "overall_center":
                continue
            raw_entities = record.get("profile_entity_ids")
            if not (
                isinstance(raw_entities, list)
                and len(raw_entities) == 2
                and all(isinstance(entity_id, str) for entity_id in raw_entities)
                and raw_entities == endpoint_entity_ids
            ):
                continue
            raw_value = record.get("dimension_value")
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
                or abs(float(raw_value) - float(dimension.value)) > 1e-9
            ):
                continue
            candidate_id = str(record.get("candidate_id") or "")
            if not candidate_id:
                continue
            candidate_sources = {
                f"hybrid:{candidate_id}:whole",
                f"hybrid:{candidate_id}:wide",
            }
            if not candidate_sources.intersection(dimension.source_ids):
                continue
            raw_sources = record.get("source_ids")
            if isinstance(raw_sources, list):
                source_ids.extend(
                    item for item in raw_sources if isinstance(item, str) and item
                )
    return list(dict.fromkeys(source_ids))


def _direct_target_value(
    direct_values: list[DirectValueEvidence],
    target: str,
) -> Any:
    matches = [item.value for item in direct_values if item.target == target]
    return matches[0] if len(matches) == 1 else None


def _materialized_entity_ids(capture: ReaderCapture) -> set[str]:
    referenced: set[str] = set()

    for association in capture.associations:
        referenced.update(association.entity_ids)

    for item in capture.values:
        referenced.add(item.entity_id)

    for item in capture.dimensions:
        for endpoint in item.endpoints:
            if endpoint.entity_id:
                referenced.add(endpoint.entity_id)
            referenced.update(endpoint.candidate_entity_ids)

    for item in capture.datum_alignments:
        referenced.add(item.entity_id)

    for item in capture.centerline_alignments:
        referenced.update(item.entity_ids)

    for item in capture.required_targets:
        referenced.add(item.entity_id)

    for item in capture.unresolved_evidence:
        referenced.update(item.entity_ids)

    profile_entity_ids = {
        item.id
        for item in capture.entities
        if item.shape == "profile"
    }

    for observation in capture.observations:
        kind = observation.get("kind")
        if kind == _VIEW_AXIS_BOUNDARY_KIND:
            valid_items = _valid_view_axis_boundary_items(capture)
            for boundary_item in valid_items:
                if boundary_item not in observation.get("items", []):
                    continue
                for anchor in boundary_item.get("anchors", []):
                    if not isinstance(anchor, dict):
                        continue
                    ref = str(anchor.get("ref") or "")
                    entity_ids = _profile_entity_ids_for_ref(capture, ref)
                    if len(entity_ids) == 1:
                        referenced.add(entity_ids[0])
            continue

        if kind == _PROJECTED_PROFILE_LEVEL_KIND:
            items = observation.get("items")
            if not isinstance(items, list):
                continue
            for record in items:
                if not isinstance(record, dict):
                    continue
                if record.get("overall_role") in {"overall_min", "overall_max"}:
                    continue
                raw_entity_ids = record.get("profile_entity_ids")
                if not isinstance(raw_entity_ids, list):
                    continue
                referenced.update(
                    entity_id
                    for entity_id in raw_entity_ids
                    if (
                        isinstance(entity_id, str)
                        and entity_id in profile_entity_ids
                    )
                )
            continue

        if kind != _ROTATIONAL_PROFILE_TOPOLOGY_KIND:
            continue
        if (
            observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_topology_only")
            is not True
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            axis = str(item.get("rotation_axis") or "").upper()
            plane = str(item.get("plane") or "").upper()
            edges = item.get("edges")
            if (
                axis not in {"X", "Y", "Z"}
                or plane not in {"XY", "XZ", "YZ"}
                or axis not in plane
                or not isinstance(edges, list)
            ):
                continue
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                entity_id = edge.get("profile_entity_id")
                constant_axis = str(edge.get("constant_axis") or "").upper()
                if (
                    isinstance(entity_id, str)
                    and entity_id in profile_entity_ids
                    and constant_axis in set(plane)
                ):
                    referenced.add(entity_id)

    return referenced


def _resolver_numeric_value(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _canonical_projection_shape(
    capture: ReaderCapture,
    entity_id: str,
    component_entity_ids: set[str],
) -> str:
    entity_by_id = {item.id: item for item in capture.entities}
    entity = entity_by_id[entity_id]

    if entity.shape != "profile":
        return entity.shape

    canonical_fields = {
        _canonical_field(capture, item.entity_id, item.field)
        for item in capture.values
        if item.entity_id == entity_id
    }
    hole_fields = {
        "diameter",
        "fit",
        "thread_spec",
        "thread_depth",
        "through",
        "counterbore_diameter",
        "counterbore_depth",
    }
    if canonical_fields & hole_fields:
        return "hidden_parallel"

    if any(
        entity_by_id[other_id].shape in {"circle", "concentric_circles"}
        for other_id in component_entity_ids
        if other_id != entity_id
    ):
        return "hidden_parallel"

    return entity.shape


def _component_signature(
    capture: ReaderCapture,
    entity_ids: list[str],
) -> dict[str, Any]:
    entity_set = set(entity_ids)
    view_kind = {item.id: item.kind for item in capture.views}

    projections = sorted(
        [
            {
                "view_kind": view_kind[item.view_id],
                "shape": _canonical_projection_shape(
                    capture,
                    item.id,
                    entity_set,
                ),
                "required_for_modeling": item.required_for_modeling,
            }
            for item in capture.entities
            if item.id in entity_set
        ],
        key=lambda item: json.dumps(item, sort_keys=True),
    )

    # Physical identity must not depend on semantic payload that stability
    # comparison is itself trying to measure. Direct values and datum
    # alignments can legitimately be missing or disputed between independent
    # Reader runs; including them in the feature-id hash turns value/datum drift
    # into artificial identity churn. Projection topology is the structural
    # identity signature. Structurally indistinguishable disconnected
    # components are handled separately by the identity-collision fail-closed
    # path below.
    return {
        "projections": projections,
    }


def _feature_id(signature: dict[str, Any]) -> str:
    payload = json.dumps(
        _canon(signature),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "F_" + hashlib.sha256(payload).hexdigest()[:16].upper()


def _association_components(
    capture: ReaderCapture,
) -> tuple[list[list[str]], list[dict[str, Any]], list[str]]:
    materialized = _materialized_entity_ids(capture)
    ignored_orphan_profiles = sorted(
        item.id
        for item in capture.entities
        if item.shape == "profile" and item.id not in materialized
    )
    entities = {
        item.id: item
        for item in capture.entities
        if item.id not in ignored_orphan_profiles
    }
    unresolved: list[dict[str, Any]] = []
    admissible: list[AssociationClaim] = []

    for association in capture.associations:
        if any(entity_id not in entities for entity_id in association.entity_ids):
            raise IdentityLinkError(
                f"association {association.id!r} references a non-materialized entity"
            )

        by_view: dict[str, list[str]] = defaultdict(list)
        for entity_id in association.entity_ids:
            by_view[entities[entity_id].view_id].append(entity_id)

        duplicate_views = {
            view_id: ids
            for view_id, ids in by_view.items()
            if len(ids) > 1
        }
        if duplicate_views:
            unresolved.append(
                {
                    "id": f"U_ASSOC_{association.id}",
                    "kind": "association_structure",
                    "reason": (
                        "association contains multiple view-local entities from "
                        f"the same view: {duplicate_views}"
                    ),
                    "entity_ids": list(association.entity_ids),
                    "required_for_modeling": association.required_for_modeling,
                    "evidence": [
                        association.id,
                        *association.source_ids,
                    ],
                }
            )
            continue

        if not _association_basis_sufficient(association.basis):
            unresolved.append(
                {
                    "id": f"U_ASSOC_EVIDENCE_{association.id}",
                    "kind": "association_evidence",
                    "reason": (
                        "association visual basis is insufficient for "
                        "deterministic physical merge"
                    ),
                    "basis": sorted(association.basis),
                    "entity_ids": list(association.entity_ids),
                    "required_for_modeling": association.required_for_modeling,
                    "evidence": [
                        association.id,
                        *association.source_ids,
                    ],
                }
            )
            continue

        admissible.append(association)

    # Validate connected association components before committing any physical
    # merge. Pairwise-valid claims can still create a transitive component that
    # contains multiple entities from the same view (A_front1↔B_side and
    # A_front2↔B_side). Choosing one edge would be order-dependent, so quarantine
    # the whole ambiguous component instead.
    candidate_uf = _UnionFind(list(entities))
    for association in admissible:
        first = association.entity_ids[0]
        for entity_id in association.entity_ids[1:]:
            candidate_uf.union(first, entity_id)

    candidate_components: dict[str, list[str]] = defaultdict(list)
    for entity_id in entities:
        candidate_components[candidate_uf.find(entity_id)].append(entity_id)

    conflicting_roots: set[str] = set()
    for root, component_entity_ids in candidate_components.items():
        by_view: dict[str, list[str]] = defaultdict(list)
        for entity_id in component_entity_ids:
            by_view[entities[entity_id].view_id].append(entity_id)
        duplicate_views = {
            view_id: sorted(ids)
            for view_id, ids in by_view.items()
            if len(ids) > 1
        }
        if not duplicate_views:
            continue

        conflicting_roots.add(root)
        component_associations = [
            association
            for association in admissible
            if candidate_uf.find(association.entity_ids[0]) == root
        ]
        evidence = sorted(
            {
                token
                for association in component_associations
                for token in [association.id, *association.source_ids]
            }
        )
        component_ids = sorted(component_entity_ids)
        component_hash = hashlib.sha256(
            "|".join(component_ids).encode("utf-8")
        ).hexdigest()[:12].upper()
        unresolved.append(
            {
                "id": f"U_ASSOC_COMPONENT_{component_hash}",
                "kind": "association_structure",
                "reason": (
                    "transitive association component contains multiple "
                    f"view-local entities from the same view: {duplicate_views}"
                ),
                "entity_ids": component_ids,
                "required_for_modeling": any(
                    association.required_for_modeling
                    for association in component_associations
                ),
                "evidence": evidence,
            }
        )

    uf = _UnionFind(list(entities))
    for association in admissible:
        root = candidate_uf.find(association.entity_ids[0])
        if root in conflicting_roots:
            continue
        first = association.entity_ids[0]
        for entity_id in association.entity_ids[1:]:
            uf.union(first, entity_id)

    components: dict[str, list[str]] = defaultdict(list)
    for entity_id in entities:
        components[uf.find(entity_id)].append(entity_id)

    return (
        [sorted(items) for items in components.values()],
        unresolved,
        ignored_orphan_profiles,
    )


def _direct_value_equivalence_key(item: DirectValueEvidence) -> str:
    return json.dumps(
        {
            "value": _canon(item.value),
            "semantic": item.semantic,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _normalize_direct_values(
    items: list[DirectValueEvidence],
) -> tuple[list[DirectValueEvidence], list[dict[str, Any]]]:
    """Normalize Reader direct writers without guessing.

    Equivalent cross-view confirmations collapse into one writer. Multiple
    non-equivalent writers for the same physical target are quarantined as a
    blocking unresolved record so frozen downstream never receives duplicate
    writers and no candidate value is chosen.
    """

    by_target: dict[str, list[DirectValueEvidence]] = defaultdict(list)
    for item in items:
        by_target[item.target].append(item)

    normalized: list[DirectValueEvidence] = []
    unresolved: list[dict[str, Any]] = []

    for target in sorted(by_target):
        target_items = sorted(by_target[target], key=lambda item: item.id)
        by_equivalence: dict[str, list[DirectValueEvidence]] = defaultdict(list)
        for item in target_items:
            by_equivalence[_direct_value_equivalence_key(item)].append(item)

        if len(by_equivalence) > 1:
            candidate_records = sorted(
                [
                    {
                        "value": _canon(group[0].value),
                        "semantic": group[0].semantic,
                    }
                    for group in by_equivalence.values()
                ],
                key=lambda item: json.dumps(
                    item,
                    sort_keys=True,
                    ensure_ascii=False,
                ),
            )
            conflict_key = json.dumps(
                {
                    "target": target,
                    "candidates": candidate_records,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            unresolved.append(
                {
                    "id": (
                        "U_DIRECT_CONFLICT_"
                        + hashlib.sha256(
                            conflict_key.encode("utf-8")
                        ).hexdigest()[:16].upper()
                    ),
                    "kind": "direct_value_conflict",
                    "reason": (
                        "multiple non-equivalent direct observations target "
                        "the same physical property"
                    ),
                    "target": target,
                    "candidates": candidate_records,
                    "required_for_modeling": True,
                    "evidence": list(
                        dict.fromkeys(
                            evidence_id
                            for item in target_items
                            for evidence_id in [item.id, *item.source_ids]
                        )
                    ),
                }
            )
            continue

        equivalence_group = next(iter(by_equivalence.values()))
        first = equivalence_group[0].model_copy(deep=True)
        if len(equivalence_group) > 1:
            merge_key = json.dumps(
                {
                    "target": target,
                    "value": _canon(first.value),
                    "semantic": first.semantic,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            first.id = (
                "L_DIRECT_"
                + hashlib.sha256(
                    merge_key.encode("utf-8")
                ).hexdigest()[:16].upper()
            )
            first.source_ids = list(
                dict.fromkeys(
                    source_id
                    for item in equivalence_group
                    for source_id in [item.id, *item.source_ids]
                )
            )
        normalized.append(first)

    return (
        sorted(normalized, key=lambda item: (item.target, item.id)),
        unresolved,
    )


def _open_slot_tangent_relations(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
) -> tuple[list[RelationEvidence], set[tuple[str, str]]]:
    relations: list[RelationEvidence] = []
    resolved_fields: set[tuple[str, str]] = set()

    for observation in capture.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind") != "hybrid_open_slot_ledger"
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            slot_entity_id = str(item.get("slot_entity_id") or "")
            circle_entity_id = str(item.get("circle_entity_id") or "")
            if (
                slot_entity_id not in entity_to_feature
                or circle_entity_id not in entity_to_feature
            ):
                continue

            slot_feature = entity_to_feature[slot_entity_id]
            circle_feature = entity_to_feature[circle_entity_id]
            if slot_feature == circle_feature:
                continue

            basis = str(item.get("basis") or "")
            if (
                basis
                != (
                    "unique_overall_top_gap_plus_two_descending_walls_plus_"
                    "circle_center_alignment_and_upper_circle_termination"
                )
            ):
                continue
            if item.get("engineering_coordinate_inferred_from_pixels") is not False:
                continue
            if item.get("pixel_geometry_used_for_topology_only") is not True:
                continue

            source_item_index = item.get("source_item_index")
            region_id = str(item.get("region_id") or "")
            source_ids = [
                source
                for source in [
                    f"hybrid:open-slot:{region_id}:{source_item_index}",
                    str(item.get("top_boundary_ref") or ""),
                    str(item.get("circle_entity") or ""),
                ]
                if source
            ]

            tangent_relation = RelationEvidence(
                id=f"R_OPEN_SLOT_UPPER_TANGENT_{index + 1:03d}",
                kind="upper_tangent",
                axis="Z",
                targets=[
                    f"feature:{circle_feature}.centerline.z",
                    f"feature:{slot_feature}.bottom_z",
                ],
                diameter_target=f"feature:{circle_feature}.diameter",
                source_ids=source_ids,
                required_for_modeling=True,
                metadata={
                    "basis": basis,
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                },
            )
            center_alignment = RelationEvidence(
                id=f"R_OPEN_SLOT_CENTER_X_{index + 1:03d}",
                kind="alignment",
                axis="X",
                targets=[
                    f"feature:{circle_feature}.centerline.x",
                    f"feature:{slot_feature}.centerline.x",
                ],
                source_ids=source_ids,
                required_for_modeling=True,
                metadata={
                    "basis": (
                        "unique_open_slot_gap_midpoint_aligned_to_circle_center"
                    ),
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                },
            )
            relations.extend([tangent_relation, center_alignment])
            resolved_fields.add((slot_feature, "bottom_z"))

    return relations, resolved_fields


def _linked_reader_unresolved(
    capture: ReaderCapture,
    entity_to_feature: dict[str, str],
    *,
    relation_resolved_fields: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    resolved_fields = relation_resolved_fields or set()

    for item in capture.unresolved_evidence:
        feature_ids = sorted(
            {
                entity_to_feature[entity_id]
                for entity_id in item.entity_ids
                if entity_id in entity_to_feature
            }
        )
        if (
            item.field is not None
            and len(feature_ids) == 1
            and (feature_ids[0], item.field) in resolved_fields
        ):
            continue

        record: dict[str, Any] = {
            "id": item.id,
            "kind": item.kind,
            "reason": item.reason,
            "required_for_modeling": item.required_for_modeling,
            "source_ids": item.source_ids,
        }

        if feature_ids:
            record["feature_ids"] = feature_ids
        if item.dimension_id is not None:
            record["capture_dimension_id"] = item.dimension_id
        if item.dimension_value is not None:
            record["dimension_value"] = item.dimension_value
        if item.field is not None:
            record["field"] = item.field
        if item.axis is not None:
            record["axis"] = item.axis
        if item.basis:
            record["basis"] = sorted(item.basis)

        result.append(record)

    return result


def link_reader_capture(capture: ReaderCapture) -> IdentityLinkResult:
    """Build stable physical feature identities from view-local Reader capture.

    Raw entity IDs never become physical feature IDs. Association claims only
    connect entities when structurally admissible; no geometry is guessed.
    """

    components, unresolved, ignored_orphan_profiles = _association_components(capture)

    signatures: list[tuple[list[str], dict[str, Any], str]] = []
    by_feature_id: dict[str, list[list[str]]] = defaultdict(list)
    for component in components:
        signature = _component_signature(capture, component)
        fid = _feature_id(signature)
        signatures.append((component, signature, fid))
        by_feature_id[fid].append(component)

    collision_ids = {
        fid
        for fid, grouped in by_feature_id.items()
        if len(grouped) > 1
    }
    if collision_ids:
        entity_required = {
            item.id: item.required_for_modeling
            for item in capture.entities
        }
        for fid in sorted(collision_ids):
            collision_required = any(
                entity_required.get(entity_id, True)
                for component in by_feature_id[fid]
                for entity_id in component
            )
            unresolved.append(
                {
                    "id": f"U_IDENTITY_COLLISION_{fid}",
                    "reason": (
                        "multiple disconnected capture components have the same "
                        "semantic signature; deterministic physical identity is "
                        "not unique"
                    ),
                    # A collision is modeling-blocking only when one of the
                    # colliding projections is itself modeling-critical.  The
                    # linker still assigns distinct deterministic AMB
                    # placeholders either way; required dimensions/unresolved
                    # endpoint records carry their own blocking semantics.
                    "required_for_modeling": collision_required,
                    "components": by_feature_id[fid],
                }
            )

    collision_component_index: dict[tuple[str, ...], int] = {}
    for fid in sorted(collision_ids):
        grouped = sorted(
            (tuple(component) for component in by_feature_id[fid]),
            key=lambda component: component,
        )
        for ordinal, component in enumerate(grouped, start=1):
            collision_component_index[component] = ordinal

    entity_to_feature: dict[str, str] = {}
    for component, _signature, fid in signatures:
        if fid in collision_ids:
            # Keep disconnected ambiguous components technically distinct so
            # downstream relations never collapse two physical candidates into
            # one target. The suffix is only an intra-capture placeholder; it
            # carries no physical left/right/order meaning. Modeling remains
            # blocked by U_IDENTITY_COLLISION_*.
            ordinal = collision_component_index[tuple(component)]
            placeholder = f"{fid}_AMB_{ordinal:02d}"
            for entity_id in component:
                entity_to_feature[entity_id] = placeholder
            continue
        for entity_id in component:
            entity_to_feature[entity_id] = fid

    views = [
        ViewEvidence(
            id=item.id,
            kind=item.kind,
            source_ids=item.source_ids,
        )
        for item in capture.views
    ]

    component_by_entity = {
        entity_id: set(component)
        for component in components
        for entity_id in component
    }

    projections = [
        ProjectionEvidence(
            id=f"P_{item.id}",
            feature_id=entity_to_feature[item.id],
            view_id=item.view_id,
            shape=_canonical_projection_shape(
                capture,
                item.id,
                component_by_entity[item.id],
            ),
            source_ids=[item.id, *item.source_ids],
            required_for_modeling=item.required_for_modeling,
        )
        for item in capture.entities
        if item.id in entity_to_feature
    ]

    inferred_axis_values: list[DirectValueEvidence] = []
    for component in components:
        if not component:
            continue
        feature_id = entity_to_feature.get(component[0])
        if feature_id is None:
            continue
        component_axis, axis_sources = _component_axis_from_projections(
            capture,
            component,
        )
        if component_axis is None:
            continue
        inferred_axis_values.append(
            DirectValueEvidence(
                id=f"L_AXIS_{feature_id}",
                target=f"feature:{feature_id}.axis",
                value=component_axis,
                semantic="axis",
                source_ids=axis_sources,
            )
        )

    direct_values, direct_unresolved = _normalize_direct_values(
        [
            *[
                DirectValueEvidence(
                    id=item.id,
                    target=(
                        f"feature:{entity_to_feature[item.entity_id]}."
                        f"{_canonical_field(capture, item.entity_id, item.field)}"
                    ),
                    value=item.value,
                    semantic=item.semantic,
                    source_ids=item.source_ids,
                )
                for item in capture.values
                if item.entity_id in entity_to_feature
            ],
            *inferred_axis_values,
        ]
    )
    unresolved.extend(direct_unresolved)

    dimensions: list[DimensionObservation] = []
    synthetic_relations: list[RelationEvidence] = []
    profile_span_centers = _validated_profile_span_centers(
        capture,
        entity_to_feature,
    )
    symmetric_dimension_pairs = _validated_symmetric_dimension_pairs(capture)
    for item in capture.dimensions:
        if any(endpoint.role == "unresolved" for endpoint in item.endpoints):
            endpoint_matches = _dimension_span_center_endpoint_matches(
                capture,
                dimension=item,
                span_centers=profile_span_centers,
            )
            if endpoint_matches is not None:
                bridged_relation = _dimension_relation_from_span_center_identity(
                    dimension=item,
                    endpoint_matches=endpoint_matches,
                    entity_to_feature=entity_to_feature,
                )
                if bridged_relation is not None:
                    synthetic_relations.append(bridged_relation)
                    continue

            symmetric_bridge = _symmetric_center_distance_bridge(
                capture,
                dimension=item,
                span_centers=profile_span_centers,
                symmetric_pairs=symmetric_dimension_pairs,
            )
            if symmetric_bridge is not None:
                synthetic_relations.extend(symmetric_bridge)
                continue

            projected_profile_bridge = _projected_profile_dimension_bridge(
                capture,
                dimension=item,
                entity_to_feature=entity_to_feature,
                symmetric_pairs=symmetric_dimension_pairs,
            )
            if projected_profile_bridge is not None:
                synthetic_relations.extend(projected_profile_bridge)
                continue

            symmetric_intermediate_bridge = _symmetric_intermediate_surface_bridge(
                capture,
                dimension=item,
                entity_to_feature=entity_to_feature,
                span_centers=profile_span_centers,
                symmetric_pairs=symmetric_dimension_pairs,
            )
            if symmetric_intermediate_bridge is not None:
                synthetic_relations.extend(symmetric_intermediate_bridge)
                continue

            related_entity_ids = sorted(
                {
                    entity_id
                    for endpoint in item.endpoints
                    for entity_id in (
                        ([endpoint.entity_id] if endpoint.entity_id else [])
                        + endpoint.candidate_entity_ids
                    )
                }
            )
            unresolved_kinds = sorted(
                {
                    endpoint.unresolved_kind
                    for endpoint in item.endpoints
                    if (
                        endpoint.role == "unresolved"
                        and endpoint.unresolved_kind is not None
                    )
                }
            )
            endpoint_source_ids = [
                source_id
                for endpoint in item.endpoints
                for source_id in endpoint.source_ids
            ]
            axis_leaf = item.axis.lower()
            endpoint_specs: list[dict[str, Any]] = []
            for endpoint_index, endpoint in enumerate(item.endpoints):
                downstream_role = (
                    "feature_center"
                    if endpoint.role == "entity_center"
                    else endpoint.role
                )
                spec: dict[str, Any] = {
                    "index": endpoint_index,
                    "role": downstream_role,
                    "unresolved_kind": endpoint.unresolved_kind,
                    "source_ids": endpoint.source_ids,
                }
                if endpoint.role in {"entity_center", "profile_boundary"} and endpoint.entity_id:
                    feature_id = entity_to_feature.get(endpoint.entity_id)
                    if feature_id:
                        suffix = (
                            f"centerline.{axis_leaf}"
                            if endpoint.role == "entity_center"
                            else f"boundary.{axis_leaf}"
                        )
                        spec["target"] = f"feature:{feature_id}.{suffix}"
                if endpoint.role == "unresolved":
                    candidate_targets: set[str] = set()
                    for entity_id in endpoint.candidate_entity_ids:
                        feature_id = entity_to_feature.get(entity_id)
                        component_entity_ids = component_by_entity.get(entity_id)
                        if feature_id is None or component_entity_ids is None:
                            continue
                        shape = _canonical_projection_shape(
                            capture,
                            entity_id,
                            component_entity_ids,
                        )
                        suffix = (
                            f"boundary.{axis_leaf}"
                            if shape == "profile"
                            else f"centerline.{axis_leaf}"
                        )
                        candidate_targets.add(
                            f"feature:{feature_id}.{suffix}"
                        )
                    spec["candidate_targets"] = sorted(candidate_targets)
                endpoint_specs.append(spec)

            unresolved.append(
                {
                    "id": f"U_DIM_{item.id}",
                    "kind": "dimension_endpoint",
                    "reason": item.unresolved_reason
                    or "dimension endpoint ownership is unresolved",
                    "required_for_modeling": item.required_for_modeling,
                    "entity_ids": related_entity_ids,
                    "capture_dimension_id": item.id,
                    "dimension_value": item.value,
                    "axis": item.axis,
                    "dimension_direction": item.direction,
                    "endpoint_unresolved_kinds": unresolved_kinds,
                    "endpoint_specs": endpoint_specs,
                    "source_ids": list(
                        dict.fromkeys([*item.source_ids, *endpoint_source_ids])
                    ),
                }
            )
            continue

        endpoints: list[DimensionEndpoint] = []
        local_endpoint_entities: list[str] = []
        for endpoint in item.endpoints:
            if endpoint.role == "overall_min":
                endpoints.append(DimensionEndpoint(role="overall_min"))
                continue
            if endpoint.role == "overall_max":
                endpoints.append(DimensionEndpoint(role="overall_max"))
                continue

            assert endpoint.role in {"entity_center", "profile_boundary"}
            assert endpoint.entity_id is not None
            local_endpoint_entities.append(endpoint.entity_id)
            axis_leaf = item.axis.lower()
            if endpoint.role == "entity_center":
                endpoints.append(
                    DimensionEndpoint(
                        role="feature_center",
                        target=(
                            f"feature:{entity_to_feature[endpoint.entity_id]}"
                            f".centerline.{axis_leaf}"
                        ),
                    )
                )
            else:
                endpoints.append(
                    DimensionEndpoint(
                        role="profile_boundary",
                        target=(
                            f"feature:{entity_to_feature[endpoint.entity_id]}"
                            f".boundary.{axis_leaf}"
                        ),
                    )
                )

        profile_boundary_targets = [
            endpoint.target
            for endpoint in endpoints
            if endpoint.role == "profile_boundary" and endpoint.target
        ]
        if (
            len(profile_boundary_targets) == 2
            and len(set(profile_boundary_targets)) == 2
        ):
            endpoint_source_ids = [
                source_id
                for endpoint in item.endpoints
                for source_id in endpoint.source_ids
            ]
            midpoint_relation = _profile_span_midpoint_relation(
                dimension=item,
                boundary_targets=profile_boundary_targets,
                endpoint_source_ids=endpoint_source_ids,
            )
            if (
                midpoint_relation is not None
                and not any(
                    relation.id == midpoint_relation.id
                    for relation in synthetic_relations
                )
            ):
                synthetic_relations.append(midpoint_relation)
            centered_relation = _profile_span_centered_relation(
                dimension=item,
                boundary_targets=profile_boundary_targets,
                endpoint_source_ids=endpoint_source_ids,
            )
            if (
                centered_relation is not None
                and not any(
                    relation.id == centered_relation.id
                    for relation in synthetic_relations
                )
            ):
                synthetic_relations.append(centered_relation)

        if (
            len(profile_boundary_targets) == 2
            and len(set(profile_boundary_targets)) == 2
            and len(local_endpoint_entities) == 2
        ):
            structured_profile_sources = _structured_symmetric_profile_span_sources(
                capture,
                dimension=item,
                endpoint_entity_ids=local_endpoint_entities,
            )
            if structured_profile_sources:
                overall_extent = {
                    "X": capture.overall_dimensions.length_x,
                    "Y": capture.overall_dimensions.width_y,
                    "Z": capture.overall_dimensions.height_z,
                }[item.axis]
                if item.direction in {-1, 1} and item.value <= overall_extent + 1e-9:
                    endpoint_source_ids = [
                        source_id
                        for endpoint in item.endpoints
                        for source_id in endpoint.source_ids
                    ]
                    all_source_ids = list(
                        dict.fromkeys(
                            [
                                *item.source_ids,
                                *endpoint_source_ids,
                                *structured_profile_sources,
                            ]
                        )
                    )
                    synthetic_relations.append(
                        RelationEvidence(
                            id=f"R_SYMMETRIC_PROFILE_ANCHOR_{item.id}",
                            kind="edge_offset",
                            axis=item.axis,
                            value=max(0.0, (overall_extent - item.value) / 2.0),
                            from_side="min" if item.direction == 1 else "max",
                            targets=[profile_boundary_targets[0]],
                            source_ids=all_source_ids,
                            required_for_modeling=item.required_for_modeling,
                            metadata={
                                "basis": (
                                    "structured_overall_center_symmetric_profile_span"
                                ),
                                "overall_extent": overall_extent,
                            },
                        )
                    )

        feature_center_targets = [
            endpoint.target
            for endpoint in endpoints
            if endpoint.role == "feature_center" and endpoint.target
        ]
        if (
            len(feature_center_targets) == 2
            and feature_center_targets[0] == feature_center_targets[1]
        ):
            endpoint_source_ids = [
                source_id
                for endpoint in item.endpoints
                for source_id in endpoint.source_ids
            ]
            base_source_ids = list(
                dict.fromkeys([*item.source_ids, *endpoint_source_ids])
            )
            feature_ids = {
                entity_to_feature[entity_id]
                for entity_id in local_endpoint_entities
                if entity_id in entity_to_feature
            }
            feature_id = next(iter(feature_ids)) if len(feature_ids) == 1 else None
            structured_symmetry_sources = (
                _structured_symmetric_count_two_sources(
                    capture,
                    feature_id=feature_id,
                    axis=item.axis,
                    entity_to_feature=entity_to_feature,
                )
                if feature_id is not None
                else []
            )
            all_source_ids = list(
                dict.fromkeys([*base_source_ids, *structured_symmetry_sources])
            )
            count_value = (
                _direct_target_value(
                    direct_values,
                    f"feature:{feature_id}.count",
                )
                if feature_id is not None
                else None
            )
            raw_feature_axis = (
                _direct_target_value(
                    direct_values,
                    f"feature:{feature_id}.axis",
                )
                if feature_id is not None
                else None
            )
            feature_axis: Axis | None
            if raw_feature_axis == "X":
                feature_axis = "X"
            elif raw_feature_axis == "Y":
                feature_axis = "Y"
            elif raw_feature_axis == "Z":
                feature_axis = "Z"
            else:
                feature_axis = None
            center_indexes: dict[Axis, int] = (
                _TRANSVERSE_CENTER_INDEX[feature_axis]
                if feature_axis is not None
                else {}
            )
            coordinate_index = center_indexes.get(item.axis)
            symmetry_proven = bool(structured_symmetry_sources)
            count_is_two = (
                not isinstance(count_value, bool)
                and isinstance(count_value, (int, float))
                and float(count_value) == 2.0
            )
            overall_extent = {
                "X": capture.overall_dimensions.length_x,
                "Y": capture.overall_dimensions.width_y,
                "Z": capture.overall_dimensions.height_z,
            }[item.axis]
            can_expand_symmetric_pair = (
                symmetry_proven
                and feature_id is not None
                and count_is_two
                and coordinate_index is not None
                and item.direction in {-1, 1}
                and item.value <= overall_extent + 1e-9
            )

            if can_expand_symmetric_pair:
                assert feature_id is not None
                assert coordinate_index is not None
                member_targets = [
                    (
                        f"feature:{feature_id}.explicit_centers."
                        f"{member_index}.{coordinate_index}"
                    )
                    for member_index in range(2)
                ]
                endpoints = [
                    DimensionEndpoint(
                        role="feature_center",
                        target=member_targets[0],
                    ),
                    DimensionEndpoint(
                        role="feature_center",
                        target=member_targets[1],
                    ),
                ]

                offset = max(0.0, (overall_extent - item.value) / 2.0)
                synthetic_relations.append(
                    RelationEvidence(
                        id=f"R_SYMMETRIC_ANCHOR_{item.id}",
                        kind="edge_offset",
                        axis=item.axis,
                        value=offset,
                        from_side=(
                            "min"
                            if item.direction == 1
                            else "max"
                        ),
                        targets=[member_targets[0]],
                        source_ids=all_source_ids,
                        required_for_modeling=item.required_for_modeling,
                        metadata={
                            "basis": (
                                "structured_overall_center_symmetry_plus_spacing"
                                if structured_symmetry_sources
                                else "overall_center_symmetry_plus_spacing"
                            ),
                            "overall_extent": overall_extent,
                        },
                    )
                )

                other_axes: list[Axis] = [
                    axis_name
                    for axis_name in center_indexes
                    if axis_name != item.axis
                ]
                if len(other_axes) == 1:
                    other_axis = other_axes[0]
                    other_index = center_indexes[other_axis]
                    synthetic_relations.append(
                        RelationEvidence(
                            id=f"R_SYMMETRIC_ROW_{item.id}",
                            kind="alignment",
                            axis=other_axis,
                            targets=[
                                f"feature:{feature_id}.centerline.{other_axis.lower()}",
                                f"feature:{feature_id}.explicit_centers.0.{other_index}",
                                f"feature:{feature_id}.explicit_centers.1.{other_index}",
                            ],
                            source_ids=all_source_ids,
                            required_for_modeling=item.required_for_modeling,
                            metadata={
                                "basis": "collapsed_projection_shared_transverse_center",
                            },
                        )
                    )
            else:
                unresolved.append(
                    {
                        "id": f"U_DIM_COLLAPSE_{item.id}",
                        "kind": "dimension_endpoint",
                        "reason": (
                            "dimension endpoints collapse to the same physical "
                            "center target after identity linking"
                        ),
                        "required_for_modeling": item.required_for_modeling,
                        "entity_ids": sorted(set(local_endpoint_entities)),
                        "capture_dimension_id": item.id,
                        "dimension_value": item.value,
                        "axis": item.axis,
                        "source_ids": item.source_ids,
                    }
                )
                continue

        endpoint_source_ids = [
            source_id
            for endpoint in item.endpoints
            for source_id in endpoint.source_ids
        ]
        dimensions.append(
            DimensionObservation(
                id=item.id,
                value=item.value,
                axis=item.axis,
                endpoints=endpoints,
                direction=item.direction,
                source_ids=list(
                    dict.fromkeys([*item.source_ids, *endpoint_source_ids])
                ),
                required_for_modeling=item.required_for_modeling,
            )
        )

    datum_alignments = [
        DatumAlignmentEvidence(
            id=item.id,
            target=(
                f"feature:{entity_to_feature[item.entity_id]}"
                f".centerline.{item.axis.lower()}"
            ),
            axis=item.axis,
            datum=item.datum,
            source_ids=item.source_ids,
            required_for_modeling=item.required_for_modeling,
        )
        for item in capture.datum_alignments
    ]

    for item in capture.centerline_alignments:
        feature_ids = [
            entity_to_feature[entity_id]
            for entity_id in item.entity_ids
            if entity_id in entity_to_feature
        ]
        if len(feature_ids) != len(item.entity_ids) or len(set(feature_ids)) < 2:
            continue
        for alignment_axis in _ALL_AXES:
            if alignment_axis == item.feature_axis:
                continue
            synthetic_relations.append(
                RelationEvidence(
                    id=f"{item.id}_{alignment_axis}",
                    kind="alignment",
                    axis=alignment_axis,
                    targets=[
                        f"feature:{feature_id}.centerline.{alignment_axis.lower()}"
                        for feature_id in feature_ids
                    ],
                    source_ids=item.source_ids,
                    required_for_modeling=item.required_for_modeling,
                    metadata={
                        "basis": "coaxial_centerline_alignment",
                        "feature_axis": item.feature_axis,
                    },
                )
            )

    slot_tangent_relations, slot_relation_resolved_fields = (
        _open_slot_tangent_relations(capture, entity_to_feature)
    )
    synthetic_relations.extend(slot_tangent_relations)
    synthetic_relations.extend(
        _view_axis_boundary_relations(
            capture,
            entity_to_feature,
        )
    )
    synthetic_relations.extend(
        _oblique_dimension_projection_relations(
            capture,
            entity_to_feature,
        )
    )

    linked_rotational_observations = (
        _linked_rotational_profile_topology_observations(
            capture,
            entity_to_feature,
        )
    )
    (
        linked_physical_arc_radius_observations,
        linked_physical_arc_radius_unresolved,
    ) = _linked_physical_profile_arc_radius_observations(
        linked_rotational_observations,
    )
    (
        physical_arc_radius_values,
        physical_arc_radius_value_unresolved,
    ) = _physical_profile_arc_radius_direct_values(
        linked_physical_arc_radius_observations,
    )
    direct_values, physical_arc_radius_direct_unresolved = (
        _normalize_direct_values(
            [
                *direct_values,
                *physical_arc_radius_values,
            ]
        )
    )
    unresolved.extend(physical_arc_radius_value_unresolved)
    unresolved.extend(physical_arc_radius_direct_unresolved)

    required_targets = {
        item.target
        for item in direct_values
        if _resolver_numeric_value(item.value)
    }
    for item in dimensions:
        if not item.required_for_modeling:
            continue
        for endpoint in item.endpoints:
            if endpoint.role in {"feature_center", "profile_boundary"} and endpoint.target:
                required_targets.add(endpoint.target)
    for item in datum_alignments:
        if item.required_for_modeling:
            required_targets.add(item.target)
    for relation in synthetic_relations:
        if relation.required_for_modeling:
            required_targets.update(relation.targets)
    required_targets = sorted(required_targets)

    evidence = EvidenceGraph(
        schema_version="1.0",
        coordinate_system=capture.coordinate_system,
        overall_dimensions=capture.overall_dimensions,
        views=views,
        projections=projections,
        dimensions=dimensions,
        datum_alignments=datum_alignments,
        direct_values=direct_values,
        relations=synthetic_relations,
        required_targets=required_targets,
        observations=[
            *_linked_labeled_dimension_relation_observations(capture),
            *linked_rotational_observations,
            *linked_physical_arc_radius_observations,
            {
                "kind": "reader_required_targets_advisory",
                "items": [
                    item.model_dump(mode="json")
                    for item in capture.required_targets
                ],
            },
            {
                "kind": "identity_linker_v2",
                "entity_to_feature": dict(sorted(entity_to_feature.items())),
                "ignored_orphan_profiles": ignored_orphan_profiles,
            },
        ],
        unresolved_evidence=[
            *linked_physical_arc_radius_unresolved,
            *_linked_reader_unresolved(
                capture,
                entity_to_feature,
                relation_resolved_fields=slot_relation_resolved_fields,
            ),
            *[
                {
                    **item,
                    **(
                        {
                            "feature_ids": sorted(
                                {
                                    entity_to_feature[entity_id]
                                    for entity_id in item.get("entity_ids", [])
                                    if entity_id in entity_to_feature
                                }
                            )
                        }
                        if item.get("entity_ids")
                        else {}
                    ),
                }
                for item in unresolved
            ],
        ],
    )

    report = {
        "capture_entities": len(capture.entities),
        "physical_components": len(components),
        "association_claims": len(capture.associations),
        "rejected_associations": sum(
            1
            for item in unresolved
            if str(item.get("id", "")).startswith("U_ASSOC")
        ),
        "ignored_orphan_profiles": len(ignored_orphan_profiles),
        "identity_collisions": len(collision_ids),
        "blocking_unresolved": sum(
            1
            for item in evidence.unresolved_evidence
            if item.get("required_for_modeling", True)
        ),
    }
    return IdentityLinkResult(
        evidence=evidence,
        entity_to_feature=entity_to_feature,
        report=report,
    )
