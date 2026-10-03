from __future__ import annotations

import copy
import re
from typing import Any

from .evidence import DirectValueEvidence, EvidenceGraph, RelationEvidence
from .metric_profile_solver import MetricProfileSpec, solve_metric_profile
from .resolver import ResolutionResult


class DraftAssemblyError(ValueError):
    """Evidence cannot be serialized into the existing Gate A contract."""


_MISSING = object()


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        if isinstance(right, (int, float)) and not isinstance(right, bool):
            return abs(float(left) - float(right)) <= 1e-9
    return left == right


def _planner_axis_shift(graph: EvidenceGraph, axis: str) -> float:
    if axis == "X":
        return graph.overall_dimensions.length_x / 2.0
    if axis == "Y":
        return graph.overall_dimensions.width_y / 2.0
    return 0.0


def _scalar_coordinate_axis(target: str) -> str | None:
    lower = target.lower()

    match = re.search(r"\.(?:centerline|boundary)\.(x|y|z)$", lower)
    if match:
        return match.group(1).upper()

    match = re.search(r"\.position\.center\.(x|y|z)$", lower)
    if match:
        return match.group(1).upper()

    match = re.search(
        r"^constraints\.(?:span_centers|symmetric_centers|symmetric_profile_levels|profile_transitions)\.[^.]+\.(x|y|z)$",
        lower,
    )
    if match:
        return match.group(1).upper()

    match = re.search(r"\.explicit_centers\.\d+\.(0|1|2)$", lower)
    if match:
        return {"0": "X", "1": "Y", "2": "Z"}[match.group(1)]

    leaf = lower.split(".")[-1]
    leaf_axis = {
        "centerline_x": "X",
        "centerline_y": "Y",
        "centerline_z": "Z",
        "hole_x": "X",
        "hole_y": "Y",
        "hole_z": "Z",
        "top_z": "Z",
        "bottom_z": "Z",
        "start_z": "Z",
        "end_z": "Z",
        "x1": "X",
        "x2": "X",
        "y1": "Y",
        "y2": "Y",
        "z1": "Z",
        "z2": "Z",
    }
    return leaf_axis.get(leaf)


def _transform_center_value(
    graph: EvidenceGraph,
    value: Any,
) -> Any:
    if isinstance(value, dict):
        output = copy.deepcopy(value)
        for key, axis in (("x", "X"), ("y", "Y"), ("z", "Z")):
            raw = output.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                output[key] = float(raw) - _planner_axis_shift(graph, axis)
        return output

    if isinstance(value, list):
        output: list[Any] = copy.deepcopy(value)
        for index, axis in enumerate(("X", "Y", "Z")):
            if index >= len(output):
                break
            raw = output[index]
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                output[index] = float(raw) - _planner_axis_shift(graph, axis)
        return output

    return copy.deepcopy(value)


def _planner_value_for_target(
    graph: EvidenceGraph,
    target: str,
    value: Any,
) -> Any:
    """Convert Reader-local 0..overall coordinates to Planner centered XY."""

    axis = _scalar_coordinate_axis(target)
    if axis is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) - _planner_axis_shift(graph, axis)

    lower = target.lower()
    if lower.endswith(".centerline") or lower.endswith(".position.center"):
        return _transform_center_value(graph, value)

    if lower.endswith(".explicit_centers") and isinstance(value, list):
        return [_transform_center_value(graph, item) for item in value]

    for suffix, axis_name in (
        (".centers_x", "X"),
        (".centers_y", "Y"),
        (".centers_z", "Z"),
    ):
        if lower.endswith(suffix) and isinstance(value, list):
            shift = _planner_axis_shift(graph, axis_name)
            return [
                float(item) - shift
                if isinstance(item, (int, float)) and not isinstance(item, bool)
                else copy.deepcopy(item)
                for item in value
            ]

    if lower.endswith(".x_range") and isinstance(value, list):
        shift = _planner_axis_shift(graph, "X")
        return [float(item) - shift for item in value]
    if lower.endswith(".y_range") and isinstance(value, list):
        shift = _planner_axis_shift(graph, "Y")
        return [float(item) - shift for item in value]

    return copy.deepcopy(value)


def _feature(root: dict[str, Any], feature_id: str) -> dict[str, Any]:
    features = root.setdefault("features", [])
    for item in features:
        if isinstance(item, dict) and item.get("id") == feature_id:
            return item
    item = {"id": feature_id}
    features.append(item)
    return item


def _target_root(root: dict[str, Any], target: str) -> tuple[Any, list[str]]:
    if target.startswith("feature:"):
        rest = target[len("feature:") :]
        feature_id, dot, tail = rest.partition(".")
        if not feature_id or not dot or not tail:
            raise DraftAssemblyError(f"invalid feature target {target!r}")
        return _feature(root, feature_id), tail.split(".")
    if not target:
        raise DraftAssemblyError("empty target")
    return root, target.split(".")


def _read_child(container: Any, key: str) -> Any:
    if isinstance(container, dict):
        return container.get(key, _MISSING)
    if isinstance(container, list) and key.isdigit():
        index = int(key)
        if 0 <= index < len(container):
            return container[index]
        return _MISSING
    return _MISSING


def _ensure_child(container: Any, key: str, next_key: str) -> Any:
    want_list = next_key.isdigit()
    if isinstance(container, dict):
        child = container.get(key, _MISSING)
        if child is _MISSING or child is None:
            child = [] if want_list else {}
            container[key] = child
        elif want_list and not isinstance(child, list):
            raise DraftAssemblyError(f"path component {key!r} is not a list")
        elif not want_list and not isinstance(child, dict):
            raise DraftAssemblyError(f"path component {key!r} is not an object")
        return child

    if isinstance(container, list) and key.isdigit():
        index = int(key)
        while len(container) <= index:
            container.append(None)
        child = container[index]
        if child is None:
            child = [] if want_list else {}
            container[index] = child
        elif want_list and not isinstance(child, list):
            raise DraftAssemblyError(f"list component {key!r} is not a list")
        elif not want_list and not isinstance(child, dict):
            raise DraftAssemblyError(f"list component {key!r} is not an object")
        return child

    raise DraftAssemblyError(f"cannot traverse path component {key!r}")


def _set_target(root: dict[str, Any], target: str, value: Any) -> None:
    container, parts = _target_root(root, target)
    if not parts:
        raise DraftAssemblyError(f"target {target!r} has no leaf")

    for index, part in enumerate(parts[:-1]):
        container = _ensure_child(container, part, parts[index + 1])

    leaf = parts[-1]
    current = _read_child(container, leaf)
    if current is not _MISSING and current is not None and not _equal(current, value):
        raise DraftAssemblyError(
            f"target {target!r} already has incompatible value "
            f"{current!r} vs {value!r}"
        )

    if isinstance(container, dict):
        container[leaf] = copy.deepcopy(value)
        return
    if isinstance(container, list) and leaf.isdigit():
        item_index = int(leaf)
        while len(container) <= item_index:
            container.append(None)
        container[item_index] = copy.deepcopy(value)
        return
    raise DraftAssemblyError(f"cannot assign target {target!r}")


def _get_target(root: dict[str, Any], target: str) -> Any:
    container, parts = _target_root(root, target)
    current: Any = container
    for part in parts:
        current = _read_child(current, part)
        if current is _MISSING:
            return _MISSING
    return current


def _source_writes_target(source: dict[str, Any], target: str) -> bool:
    if source.get("target") == target:
        return True
    targets = source.get("targets")
    return isinstance(targets, list) and target in targets


def _append_inferred_feature_type_source(
    draft: dict[str, Any],
    *,
    feature_id: str,
    feature_type: str,
    basis_targets: list[str],
) -> None:
    """Record provenance for a type inferred from already-proven semantics."""

    supporting_source_ids: list[str] = []
    supporting_evidence: list[str] = []
    for source in draft.get("source_ledger", []):
        if not isinstance(source, dict):
            continue
        if not any(_source_writes_target(source, target) for target in basis_targets):
            continue
        source_id = source.get("id")
        if isinstance(source_id, str) and source_id:
            supporting_source_ids.append(source_id)
        evidence = source.get("evidence")
        if isinstance(evidence, list):
            supporting_evidence.extend(
                item for item in evidence if isinstance(item, str) and item
            )

    evidence = list(dict.fromkeys([*supporting_evidence, *supporting_source_ids]))
    draft["source_ledger"].append(
        {
            "id": f"TYPE_{_stable_fragment(feature_id)}",
            "semantic": "feature_kind",
            "value": feature_type,
            "target": f"feature:{feature_id}.type",
            "evidence": evidence,
            "inference_basis_targets": list(basis_targets),
            "inference_basis_sources": list(dict.fromkeys(supporting_source_ids)),
        }
    )


def _infer_feature_types(draft: dict[str, Any]) -> None:
    """Assign only feature types implied by already-materialized semantics."""

    for feature in draft.get("features", []):
        if not isinstance(feature, dict) or feature.get("type"):
            continue

        feature_id = str(feature.get("id") or "")
        if not feature_id:
            continue

        feature_type: str | None = None
        basis_targets: list[str] = []
        keys = set(feature)

        if "boundary" in keys and keys <= {"id", "boundary"}:
            boundary = feature.get("boundary")
            if isinstance(boundary, dict):
                basis_targets = [
                    f"feature:{feature_id}.boundary.{axis}"
                    for axis in ("x", "y", "z")
                    if boundary.get(axis) is not None
                ]
            if basis_targets:
                feature_type = "reference_boundary"

        elif feature.get("thread_spec") is not None or feature.get("thread_depth") is not None:
            feature_type = "threaded_hole"
            basis_targets = [
                f"feature:{feature_id}.{field}"
                for field in ("thread_spec", "thread_depth")
                if feature.get(field) is not None
            ]

        elif (
            feature.get("counterbore_diameter") is not None
            or feature.get("counterbore_depth") is not None
        ):
            feature_type = "counterbore_hole"
            basis_targets = [
                f"feature:{feature_id}.{field}"
                for field in (
                    "diameter",
                    "counterbore_diameter",
                    "counterbore_depth",
                    "through",
                )
                if feature.get(field) is not None
            ]

        elif (
            feature.get("recessed_hole") is True
            or feature.get("recess_diameter") is not None
            or feature.get("recess_depth") is not None
        ):
            feature_type = "recessed_hole"
            basis_targets = [
                f"feature:{feature_id}.{field}"
                for field in ("recessed_hole", "recess_diameter", "recess_depth")
                if feature.get(field) is not None
            ]

        elif feature.get("diameter") is not None and feature.get("axis") in {"X", "Y", "Z"}:
            feature_type = "hole"
            basis_targets = [
                f"feature:{feature_id}.diameter",
                f"feature:{feature_id}.axis",
            ]

        if feature_type is None:
            continue

        feature["type"] = feature_type
        _append_inferred_feature_type_source(
            draft,
            feature_id=feature_id,
            feature_type=feature_type,
            basis_targets=basis_targets,
        )


def _feature_type(root: dict[str, Any], target: str) -> str:
    if not target.startswith("feature:"):
        return ""
    rest = target[len("feature:") :]
    feature_id = rest.partition(".")[0]
    item = next(
        (
            value
            for value in root.get("features", [])
            if isinstance(value, dict) and value.get("id") == feature_id
        ),
        {},
    )
    return str(item.get("type") or item.get("kind") or "").lower()


def _semantic_for_target(root: dict[str, Any], fact: DirectValueEvidence) -> str:
    if fact.semantic:
        return fact.semantic

    target = fact.target
    leaf = target.split(".")[-1].lower()
    if target.startswith("overall_dimensions."):
        return "overall_dimension"
    if target.startswith("profile."):
        return "profile_dimension"
    if leaf == "count":
        return "feature_count"
    if leaf in {
        "diameter",
        "hole_diameter",
        "counterbore_diameter",
        "countersink_diameter",
    }:
        return "diameter"
    if leaf == "radius":
        return "radius"
    if leaf == "width" and _feature_type(root, target) in {"slot", "cut", "slit"}:
        return "slot_width"
    if leaf in {"depth", "hole_depth", "counterbore_depth"}:
        return "depth"
    if leaf == "thickness":
        return "thickness"
    if leaf in {"axis", "width_axis", "through_axis"}:
        return "axis"
    if ".centerline." in target or ".position.center." in target:
        return "center_position"
    if leaf in {
        "center",
        "centerline_x",
        "centerline_y",
        "centerline_z",
        "hole_x",
        "hole_y",
        "hole_z",
    }:
        return "center_position"
    if leaf in {"x", "y", "z", "top_z", "bottom_z", "start_z", "end_z"}:
        return "position_dimension"
    if leaf == "spec":
        return "thread_spec"
    if leaf in {"type", "kind"}:
        return "feature_kind"
    if leaf in {"side", "start_side"}:
        return "side"
    if leaf in {"through", "through_z"}:
        return "through"
    if leaf in {
        "count_x",
        "count_y",
        "spacing",
        "spacing_x",
        "spacing_y",
        "pitch",
        "pcd",
        "start_angle_deg",
        "centers",
        "centers_x",
        "centers_y",
        "explicit_centers",
        "pattern_type",
    }:
        return "pattern_dimension"
    if target.startswith("feature:"):
        return "feature_dimension"
    raise DraftAssemblyError(f"cannot infer Gate A semantic for target {target!r}")


def _direct_source(
    root: dict[str, Any],
    graph: EvidenceGraph,
    fact: DirectValueEvidence,
) -> dict[str, Any]:
    planner_value = _planner_value_for_target(graph, fact.target, fact.value)
    source = {
        "id": fact.id,
        "semantic": _semantic_for_target(root, fact),
        "value": planner_value,
        "target": fact.target,
    }
    if planner_value != fact.value:
        source["reader_local_value"] = copy.deepcopy(fact.value)
    if fact.source_ids:
        source["evidence"] = list(fact.source_ids)
    return source


def _relation_source(relation: RelationEvidence) -> dict[str, Any]:
    source: dict[str, Any] = {
        "id": relation.id,
        "semantic": relation.kind,
    }
    if relation.source_ids:
        source["evidence"] = list(relation.source_ids)

    if relation.kind == "edge_offset":
        source.update(
            {
                "value": relation.value,
                "axis": relation.axis,
                "from": relation.from_side,
                "targets": list(relation.targets),
            }
        )
    elif relation.kind in {"center_spacing", "center_distance", "coordinate_distance"}:
        source.update(
            {
                "value": relation.value,
                "axis": relation.axis,
                "between": list(relation.targets),
            }
        )
    elif relation.kind in {"alignment", "midpoint"}:
        source["links"] = list(relation.targets)
        source["axis"] = relation.axis
    elif relation.kind == "centered_span":
        source.update(
            {
                "value": relation.value,
                "axis": relation.axis,
                "direction": relation.direction,
                "links": list(relation.targets),
            }
        )
    elif relation.kind in {"upper_tangent", "lower_tangent"}:
        center_target, tangent_target = relation.targets
        source.update(
            {
                "center": center_target,
                "diameter": relation.diameter_target,
                "tangent": tangent_target,
                "links": [
                    center_target,
                    relation.diameter_target,
                    tangent_target,
                ],
            }
        )
    else:
        raise DraftAssemblyError(f"unsupported relation kind {relation.kind!r}")
    return source


def _stable_fragment(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return value or "VALUE"


def _derived_entry(
    target: str, value: float, derivation: dict[str, Any]
) -> dict[str, Any] | None:
    kind = str(derivation.get("kind") or "")
    relation_id = str(derivation.get("relation_id") or "")
    dependencies = [
        item for item in derivation.get("dependencies", []) if isinstance(item, str)
    ]

    # Gate A treats these relations as geometry writers themselves.
    if kind in {
        "edge_offset",
        "centered_span",
        "upper_tangent",
        "lower_tangent",
    }:
        return None

    if kind == "alignment":
        if len(dependencies) != 1 or not relation_id:
            raise DraftAssemblyError(f"alignment derivation for {target!r} is incomplete")
        return {
            "id": f"D_{_stable_fragment(relation_id)}_{_stable_fragment(target)}",
            "target": target,
            "value": value,
            "expr": {"target": dependencies[0]},
            "relation_refs": [relation_id],
        }

    if kind in {"center_spacing", "center_distance", "coordinate_distance"}:
        op = derivation.get("op")
        if len(dependencies) != 1 or op not in {"add", "sub"} or not relation_id:
            raise DraftAssemblyError(f"spacing derivation for {target!r} is incomplete")
        return {
            "id": f"D_{_stable_fragment(relation_id)}_{_stable_fragment(target)}",
            "target": target,
            "value": value,
            "expr": {
                "op": op,
                "args": [
                    {"target": dependencies[0]},
                    {"source": relation_id},
                ],
            },
        }

    if kind == "midpoint":
        op = derivation.get("op")
        if len(dependencies) != 2 or op not in {"mean", "reflect"} or not relation_id:
            raise DraftAssemblyError(
                f"midpoint derivation for {target!r} is incomplete"
            )
        if op == "mean":
            expr = {
                "op": "div",
                "args": [
                    {
                        "op": "add",
                        "args": [
                            {"target": dependencies[0]},
                            {"target": dependencies[1]},
                        ],
                    },
                    {"const": 2.0},
                ],
            }
        else:
            expr = {
                "op": "sub",
                "args": [
                    {
                        "op": "mul",
                        "args": [
                            {"const": 2.0},
                            {"target": dependencies[0]},
                        ],
                    },
                    {"target": dependencies[1]},
                ],
            }
        return {
            "id": f"D_{_stable_fragment(relation_id)}_{_stable_fragment(target)}",
            "target": target,
            "value": value,
            "expr": expr,
            "relation_refs": [relation_id],
        }

    raise DraftAssemblyError(
        f"unsupported deterministic derivation kind {kind!r} for {target!r}"
    )


def _unresolved_entries(
    resolution: ResolutionResult,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for index, item in enumerate(resolution.unresolved):
        required = bool(item.get("required_for_modeling", True))
        reason = str(item.get("reason") or "unresolved evidence")
        raw_targets = item.get("targets")
        if isinstance(raw_targets, list):
            targets = [
                target
                for target in raw_targets
                if isinstance(target, str) and target not in resolution.values
            ]
        else:
            target = item.get("target")
            targets = [target] if isinstance(target, str) else []

        if not targets:
            # Preserve non-target unresolved evidence as a blocker/warning record.
            entry = copy.deepcopy(item)
            entry.setdefault("id", f"U_EVIDENCE_{index}")
            entry.setdefault("required_for_modeling", required)
            entry.setdefault("reason", reason)
            entries.append(entry)
            continue

        base_id = str(item.get("id") or f"U_TARGET_{index}")
        for target_index, target in enumerate(targets):
            uid = (
                base_id
                if len(targets) == 1
                else f"{base_id}:{target_index}"
            )
            while uid in used_ids:
                uid += "_"
            used_ids.add(uid)
            entries.append(
                {
                    "id": uid,
                    "target": target,
                    "reason": reason,
                    "required_for_modeling": required,
                }
            )
    return entries


def _expected_profile_overall(
    graph: EvidenceGraph,
    plane: str,
) -> tuple[float, float]:
    return {
        "XY": (
            float(graph.overall_dimensions.length_x),
            float(graph.overall_dimensions.width_y),
        ),
        "XZ": (
            float(graph.overall_dimensions.length_x),
            float(graph.overall_dimensions.height_z),
        ),
        "YZ": (
            float(graph.overall_dimensions.width_y),
            float(graph.overall_dimensions.height_z),
        ),
    }[plane]


def _rotational_profile_key(item: dict[str, Any]) -> tuple[str, str, str, int] | None:
    axis = str(item.get("rotation_axis") or "")
    plane = str(item.get("plane") or "")
    region_id = str(item.get("region_id") or "")
    component_index = item.get("component_index")
    if (
        axis not in {"X", "Y", "Z"}
        or plane not in {"XY", "XZ", "YZ"}
        or axis not in plane
        or not region_id
        or not isinstance(component_index, int)
        or isinstance(component_index, bool)
    ):
        return None
    return axis, plane, region_id, component_index


def _rotational_axis_center(
    graph: EvidenceGraph,
    radial_axis: str,
) -> float:
    if radial_axis in {"X", "Y"}:
        return 0.0
    return float(graph.overall_dimensions.height_z) / 2.0


def _point_key(point: dict[str, float], axes: tuple[str, str]) -> tuple[float, float]:
    return (
        round(float(point[axes[0]]), 12),
        round(float(point[axes[1]]), 12),
    )


def _branched_rotational_material_segments(
    edges: dict[str, dict[str, Any]],
    adjacency: dict[str, set[str]],
    axes: tuple[str, str],
) -> list[dict[str, Any]] | None:
    """Split a branched physical boundary graph into material-only segments.

    Each physical boundary line may intersect more than two perpendicular
    boundaries after crop-local aliases are merged. Engineering coordinates
    order those intersections; material-side direction determines whether each
    interval is material or a void gap. No raster distance supplies metric
    geometry.
    """

    if not any(len(neighbors) > 2 for neighbors in adjacency.values()):
        return None
    if any(len(neighbors) < 2 for neighbors in adjacency.values()):
        return None

    segments: list[dict[str, Any]] = []
    for ref, edge in sorted(edges.items()):
        if edge.get("material_axis_direction") not in {"negative", "positive"}:
            return None

        varying_axis = axes[1] if edge["axis"] == axes[0] else axes[0]
        neighbors = sorted(
            adjacency[ref],
            key=lambda neighbor: (
                float(edges[neighbor]["value"]),
                neighbor,
            ),
        )
        if any(
            edges[neighbor]["axis"] != varying_axis
            or edges[neighbor].get("material_axis_direction")
            not in {"negative", "positive"}
            for neighbor in neighbors
        ):
            return None

        for index in range(len(neighbors) - 1):
            lower_ref = neighbors[index]
            upper_ref = neighbors[index + 1]
            lower = edges[lower_ref]
            upper = edges[upper_ref]
            lower_value = float(lower["value"])
            upper_value = float(upper["value"])
            if upper_value - lower_value <= 1e-9:
                return None

            directions = (
                lower["material_axis_direction"],
                upper["material_axis_direction"],
            )
            if directions == ("negative", "positive"):
                # Both crossing boundaries point material away from the
                # interval, so this span is a deterministic void gap.
                continue
            if directions != ("positive", "negative"):
                # Same-direction or otherwise inconsistent boundaries do not
                # prove either material or void; preserve fail-closed behavior.
                return None

            first = {
                edge["axis"]: float(edge["value"]),
                varying_axis: lower_value,
            }
            second = {
                edge["axis"]: float(edge["value"]),
                varying_axis: upper_value,
            }
            segments.append(
                {
                    "start": first,
                    "end": second,
                    "source_targets": sorted(
                        {
                            edge["target"],
                            lower["target"],
                            upper["target"],
                        }
                    ),
                    "source_ref": ref,
                }
            )

    return segments or None


def _ordered_rotational_cycle_matches_material_polarity(
    ordered: list[dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    axes: tuple[str, str],
) -> bool:
    """Require every decomposed boundary normal to point into the material cycle."""

    if len(ordered) < 3:
        return False

    area2 = 0.0
    for segment in ordered:
        start = segment["start"]
        end = segment["end"]
        area2 += (
            float(start[axes[0]]) * float(end[axes[1]])
            - float(end[axes[0]]) * float(start[axes[1]])
        )
    if abs(area2) <= 1e-9:
        return False
    counter_clockwise = area2 > 0.0

    for segment in ordered:
        ref = str(segment.get("source_ref") or "")
        edge = edges.get(ref)
        if edge is None:
            return False
        material_direction = edge.get("material_axis_direction")
        if material_direction not in {"negative", "positive"}:
            return False

        start = segment["start"]
        end = segment["end"]
        delta_u = float(end[axes[0]]) - float(start[axes[0]])
        delta_v = float(end[axes[1]]) - float(start[axes[1]])

        if edge["axis"] == axes[0]:
            if abs(delta_u) > 1e-9 or abs(delta_v) <= 1e-9:
                return False
            if counter_clockwise:
                interior_direction = "negative" if delta_v > 0.0 else "positive"
            else:
                interior_direction = "positive" if delta_v > 0.0 else "negative"
        elif edge["axis"] == axes[1]:
            if abs(delta_v) > 1e-9 or abs(delta_u) <= 1e-9:
                return False
            if counter_clockwise:
                interior_direction = "positive" if delta_u > 0.0 else "negative"
            else:
                interior_direction = "negative" if delta_u > 0.0 else "positive"
        else:
            return False

        if material_direction != interior_direction:
            return False

    return True


def _bilateral_exterior_oblique_sources(
    graph: EvidenceGraph,
    item: dict[str, Any],
) -> list[str] | None:
    """Prove a bilateral straight exterior transition without raster-to-metric inference.

    Raster coordinates may confirm bilateral topology only. They cannot prove a
    canonical primitive type. Materialization therefore requires each physical
    fragment to already carry verified straight-profile semantics and verified
    structural contacts; unresolved exterior fragments are blockers, never
    authority to synthesize a line.
    """

    fragments = item.get("non_orthogonal_fragments")
    if not isinstance(fragments, list):
        return None

    fragment_sources: set[str] = set()
    evidence: list[str] = []
    for fragment in fragments:
        if (
            not isinstance(fragment, dict)
            or fragment.get("connection_kind")
            != "non_orthogonal_profile_connection"
            or fragment.get("primitive_kind") != "line"
            or fragment.get("primitive_kind_basis")
            != (
                "verified_continuous_straight_raster_segment_"
                "between_structural_contacts"
            )
            or not isinstance(fragment.get("supporting_physical_edges"), list)
            or len(fragment["supporting_physical_edges"]) < 2
            or fragment.get("engineering_coordinate_inferred_from_pixels") is not False
            or fragment.get("pixel_geometry_used_for_topology_only") is not True
            or fragment.get("material_side_index") not in {0, 1}
            or fragment.get("background_side_index") not in {0, 1}
            or fragment.get("material_side_index")
            == fragment.get("background_side_index")
        ):
            continue
        sources = [
            value
            for value in fragment.get("source_ids", [])
            if isinstance(value, str) and value
        ]
        oblique_sources = {
            value
            for value in sources
            if value.startswith("hybrid:oblique-line:")
        }
        if len(oblique_sources) != 1:
            return None
        fragment_sources.update(oblique_sources)
        evidence.extend(sources)

    if len(fragment_sources) != 2:
        return None

    raw_by_source: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}
    for observation in graph.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind")
            != "hybrid_rotational_oblique_profile_candidate_ledger"
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
                or raw_item.get("plane") != item.get("plane")
                or raw_item.get("rotation_axis") != item.get("rotation_axis")
                or raw_item.get("view_kind") != item.get("view_kind")
                or raw_item.get("exterior_boundary_candidate") is not True
                or raw_item.get("one_sided_boundary_candidate") is not True
            ):
                continue
            raw_sources = {
                value
                for value in raw_item.get("source_ids", [])
                if isinstance(value, str)
                and value.startswith("hybrid:oblique-line:")
            }
            matched = raw_sources.intersection(fragment_sources)
            if len(matched) != 1:
                continue
            source = next(iter(matched))
            endpoints = raw_item.get("endpoints_px")
            if not (
                isinstance(endpoints, list)
                and len(endpoints) == 2
                and all(
                    isinstance(point, list)
                    and len(point) == 2
                    and all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        for value in point
                    )
                    for point in endpoints
                )
            ):
                return None
            ordered_points = sorted(
                (
                    (float(point[0]), float(point[1]))
                    for point in endpoints
                ),
                key=lambda point: (point[1], point[0]),
            )
            ordered = (ordered_points[0], ordered_points[1])
            if source in raw_by_source and raw_by_source[source] != ordered:
                return None
            raw_by_source[source] = ordered
            evidence.extend(
                value
                for value in raw_item.get("source_ids", [])
                if isinstance(value, str) and value
            )

    if set(raw_by_source) != fragment_sources:
        return None

    first, second = [raw_by_source[source] for source in sorted(fragment_sources)]
    tolerance = 3.0
    if any(abs(first[index][1] - second[index][1]) > tolerance for index in (0, 1)):
        return None
    mirror_sums = [
        first[index][0] + second[index][0]
        for index in (0, 1)
    ]
    if abs(mirror_sums[0] - mirror_sums[1]) > tolerance:
        return None

    return list(dict.fromkeys(evidence))


def _materialize_symmetric_tapered_annular_profile(
    draft: dict[str, Any],
    graph: EvidenceGraph,
    resolution: ResolutionResult,
) -> set[tuple[str, str, str, int]]:
    """Materialize a symmetric annular hub/taper profile from engineering constraints.

    The supported pattern is intentionally strict: a Z-axis rotational view,
    two globally centered radial profile spans, one local wall-thickness span
    sharing the smaller centered span, one unique interior axial profile level,
    a through inner-bore boundary, and bilateral exterior oblique topology.
    All metric vertices come from Resolver/overall dimensions.
    """

    if draft.get("profile") not in (None, {}):
        return set()

    topology_items: list[dict[str, Any]] = []
    for observation in graph.observations:
        if (
            isinstance(observation, dict)
            and observation.get("kind")
            == "hybrid_rotational_profile_topology_ledger"
            and observation.get("engineering_coordinate_inferred_from_pixels")
            is False
            and observation.get("pixel_geometry_used_for_topology_only") is True
        ):
            items = observation.get("items")
            if isinstance(items, list):
                topology_items.extend(
                    value for value in items if isinstance(value, dict)
                )

    materialized: set[tuple[str, str, str, int]] = set()
    for item in topology_items:
        key = _rotational_profile_key(item)
        if key is None:
            continue
        rotation_axis, plane, _region_id, _component_index = key
        if rotation_axis != "Z" or plane not in {"XZ", "YZ"}:
            continue
        radial_axis = plane[0]
        radial_extent = {
            "X": float(graph.overall_dimensions.length_x),
            "Y": float(graph.overall_dimensions.width_y),
        }[radial_axis]
        axial_extent = float(graph.overall_dimensions.height_z)
        radial_center = radial_extent / 2.0
        tolerance = 1e-7

        oblique_evidence = _bilateral_exterior_oblique_sources(graph, item)
        if oblique_evidence is None:
            continue

        centered_spans: list[dict[str, Any]] = []
        radial_dimensions: list[dict[str, Any]] = []
        for dimension in graph.dimensions:
            if dimension.axis != radial_axis:
                continue
            endpoints = dimension.endpoints
            if (
                len(endpoints) != 2
                or any(endpoint.role != "profile_boundary" for endpoint in endpoints)
                or any(not endpoint.target for endpoint in endpoints)
            ):
                continue
            targets = [str(endpoint.target) for endpoint in endpoints]
            if any(target not in resolution.values for target in targets):
                continue
            values = [resolution.values[target] for target in targets]
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                for value in values
            ):
                continue
            first, second = (float(value) for value in values)
            span = abs(second - first)
            if abs(span - float(dimension.value)) > tolerance:
                continue
            record = {
                "dimension": dimension,
                "targets": targets,
                "values": [first, second],
                "span": span,
            }
            radial_dimensions.append(record)
            if abs(((first + second) / 2.0) - radial_center) <= tolerance:
                centered_spans.append(record)

        neck_candidates: list[tuple[dict[str, Any], dict[str, Any], str, float]] = []
        for centered in centered_spans:
            centered_targets = set(centered["targets"])
            neck_radius = float(centered["span"]) / 2.0
            for local in radial_dimensions:
                if local is centered:
                    continue
                shared = centered_targets.intersection(local["targets"])
                if len(shared) != 1:
                    continue
                shared_target = next(iter(shared))
                other_targets = [
                    target
                    for target in local["targets"]
                    if target != shared_target
                ]
                if len(other_targets) != 1:
                    continue
                other_target = other_targets[0]
                other_value = float(
                    resolution.values[other_target]
                )
                inner_radius = abs(other_value - radial_center)
                shared_value = float(
                    resolution.values[shared_target]
                )
                shared_radius = abs(shared_value - radial_center)
                if (
                    abs(shared_radius - neck_radius) > tolerance
                    or not (0.0 < inner_radius < neck_radius)
                    or abs(
                        (neck_radius - inner_radius)
                        - float(local["span"])
                    ) > tolerance
                ):
                    continue
                neck_candidates.append(
                    (centered, local, other_target, inner_radius)
                )

        if len(neck_candidates) != 1:
            continue
        neck_span, wall_span, inner_target, inner_radius = neck_candidates[0]
        neck_radius = float(neck_span["span"]) / 2.0

        hub_candidates = [
            candidate
            for candidate in centered_spans
            if (
                candidate is not neck_span
                and float(candidate["span"]) > float(neck_span["span"]) + tolerance
                and float(candidate["span"]) < radial_extent - tolerance
            )
        ]
        if len(hub_candidates) != 1:
            continue
        hub_span = hub_candidates[0]
        hub_radius = float(hub_span["span"]) / 2.0
        flange_radius = radial_extent / 2.0
        if not (
            0.0 < inner_radius < neck_radius < hub_radius < flange_radius
        ):
            continue

        raw_edges = item.get("edges")
        raw_junctions = item.get("junctions")
        if not isinstance(raw_edges, list) or not isinstance(raw_junctions, list):
            continue
        edges = {
            str(edge.get("ref") or ""): edge
            for edge in raw_edges
            if isinstance(edge, dict) and str(edge.get("ref") or "")
        }
        inner_refs = [
            ref
            for ref, edge in edges.items()
            if (
                str(edge.get("constant_axis") or "").upper() == radial_axis
                and edge.get("boundary_target") == inner_target
            )
        ]
        if len(inner_refs) != 1:
            continue

        adjacency: dict[str, set[str]] = {ref: set() for ref in edges}
        valid_junctions = True
        for pair in raw_junctions:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(ref, str) for ref in pair)
                or pair[0] not in edges
                or pair[1] not in edges
            ):
                valid_junctions = False
                break
            adjacency[pair[0]].add(pair[1])
            adjacency[pair[1]].add(pair[0])
        if not valid_junctions:
            continue

        inner_axial_values: set[float] = set()
        for neighbor in adjacency.get(inner_refs[0], set()):
            edge = edges[neighbor]
            if str(edge.get("constant_axis") or "").upper() != rotation_axis:
                continue
            target = edge.get("boundary_target")
            if not isinstance(target, str) or target not in resolution.values:
                continue
            value = resolution.values[target]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                inner_axial_values.add(round(float(value), 9))
        if (
            round(0.0, 9) not in inner_axial_values
            or round(axial_extent, 9) not in inner_axial_values
        ):
            continue

        axial_edge_targets = {
            str(edge.get("boundary_target"))
            for edge in edges.values()
            if str(edge.get("constant_axis") or "").upper() == rotation_axis
            and isinstance(edge.get("boundary_target"), str)
        }
        interior_levels: list[tuple[float, RelationEvidence]] = []
        for relation in graph.relations:
            if (
                relation.kind != "edge_offset"
                or relation.axis != rotation_axis
                or len(relation.targets) != 1
                or relation.targets[0] not in axial_edge_targets
                or relation.targets[0] not in resolution.values
            ):
                continue
            raw_value = resolution.values[relation.targets[0]]
            if (
                not isinstance(raw_value, (int, float))
                or isinstance(raw_value, bool)
            ):
                continue
            level = float(raw_value)
            if tolerance < level < axial_extent - tolerance:
                interior_levels.append((level, relation))
        unique_levels = {
            round(level, 9)
            for level, _relation in interior_levels
        }
        if len(unique_levels) != 1:
            continue
        flange_level = next(iter(unique_levels))
        level_relations = [
            relation
            for level, relation in interior_levels
            if round(level, 9) == flange_level
        ]

        points = [
            {radial_axis: inner_radius, rotation_axis: 0.0},
            {radial_axis: flange_radius, rotation_axis: 0.0},
            {radial_axis: flange_radius, rotation_axis: flange_level},
            {radial_axis: hub_radius, rotation_axis: flange_level},
            {radial_axis: neck_radius, rotation_axis: axial_extent},
            {radial_axis: inner_radius, rotation_axis: axial_extent},
        ]
        profile_segments: list[dict[str, Any]] = []
        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            profile_segments.append(
                {
                    "type": "line",
                    f"{radial_axis.lower()}1": float(start[radial_axis]),
                    f"{rotation_axis.lower()}1": float(start[rotation_axis]),
                    f"{radial_axis.lower()}2": float(end[radial_axis]),
                    f"{rotation_axis.lower()}2": float(end[rotation_axis]),
                }
            )

        source_ids = list(
            dict.fromkeys(
                [
                    *[
                        value
                        for value in item.get("source_ids", [])
                        if isinstance(value, str) and value
                    ],
                    *oblique_evidence,
                    *neck_span["dimension"].source_ids,
                    *wall_span["dimension"].source_ids,
                    *hub_span["dimension"].source_ids,
                    *[
                        source
                        for relation in level_relations
                        for source in [relation.id, *relation.source_ids]
                    ],
                ]
            )
        )
        draft["profile"] = {
            "plane": plane,
            "topology": "closed_polygon",
            "rotation_axis": rotation_axis,
            "segments": profile_segments,
        }
        for index, segment in enumerate(profile_segments):
            for field, value in segment.items():
                draft["source_ledger"].append(
                    {
                        "id": (
                            "ROTATIONAL_TAPER_PROFILE_"
                            f"{index}_{field.upper()}"
                        ),
                        "semantic": "profile_dimension",
                        "value": copy.deepcopy(value),
                        "target": f"profile.segments.{index}.{field}",
                        "evidence": source_ids,
                        "solver": "rotational_taper_profile_solver",
                    }
                )
        draft["source_ledger"].extend(
            [
                {
                    "id": "ROTATIONAL_TAPER_PROFILE_PLANE",
                    "semantic": "profile_dimension",
                    "value": plane,
                    "target": "profile.plane",
                    "evidence": source_ids,
                    "solver": "rotational_taper_profile_solver",
                },
                {
                    "id": "ROTATIONAL_TAPER_PROFILE_TOPOLOGY",
                    "semantic": "profile_dimension",
                    "value": "closed_polygon",
                    "target": "profile.topology",
                    "evidence": source_ids,
                    "solver": "rotational_taper_profile_solver",
                },
                {
                    "id": "ROTATIONAL_TAPER_PROFILE_AXIS",
                    "semantic": "profile_dimension",
                    "value": rotation_axis,
                    "target": "profile.rotation_axis",
                    "evidence": source_ids,
                    "solver": "rotational_taper_profile_solver",
                },
            ]
        )
        materialized.add(key)
        break

    return materialized


def _materialize_rotational_profile(
    draft: dict[str, Any],
    graph: EvidenceGraph,
    resolution: ResolutionResult,
) -> set[tuple[str, str, str, int]]:
    """Build one deterministic max-radial meridian from resolved topology.

    Topology may identify which structural profile edges connect, but only
    Resolver values attached to engineering boundary targets supply metric
    coordinates.  A full closed silhouette cycle is clipped to the max-radial
    half about the established rotation axis and then closed on that axis.
    Anything incomplete or non-unique remains unmaterialized and therefore
    fail-closed.
    """

    if draft.get("profile") not in (None, {}):
        return set()

    candidates: list[dict[str, Any]] = []
    for observation in graph.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind")
            != "hybrid_rotational_profile_topology_ledger"
            or observation.get("engineering_coordinate_inferred_from_pixels")
            is not False
            or observation.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue
        items = observation.get("items")
        if isinstance(items, list):
            candidates.extend(item for item in items if isinstance(item, dict))

    materialized: set[tuple[str, str, str, int]] = set()
    for item in candidates:
        key = _rotational_profile_key(item)
        if key is None:
            continue
        rotation_axis, plane, _region_id, _component_index = key
        axes = (plane[0], plane[1])
        radial_axis = axes[1] if axes[0] == rotation_axis else axes[0]
        axis_center = _rotational_axis_center(graph, radial_axis)
        tolerance = 1e-9

        raw_edges = item.get("edges")
        raw_junctions = item.get("junctions")
        if (
            not isinstance(raw_edges, list)
            or len(raw_edges) < 4
            or not isinstance(raw_junctions, list)
        ):
            continue

        edges: dict[str, dict[str, Any]] = {}
        valid = True
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                valid = False
                break
            ref = str(raw_edge.get("ref") or "")
            constant_axis = str(raw_edge.get("constant_axis") or "").upper()
            target = raw_edge.get("boundary_target")
            if (
                not ref
                or ref in edges
                or constant_axis not in axes
                or not isinstance(target, str)
                or target not in resolution.values
            ):
                valid = False
                break
            raw_value = resolution.values[target]
            if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
                valid = False
                break
            edges[ref] = {
                "axis": constant_axis,
                "target": target,
                "value": float(
                    _planner_value_for_target(graph, target, raw_value)
                ),
                **(
                    {
                        "material_axis_direction": str(
                            raw_edge["material_axis_direction"]
                        )
                    }
                    if raw_edge.get("material_axis_direction")
                    in {"negative", "positive"}
                    else {}
                ),
            }
        if not valid:
            continue

        adjacency: dict[str, set[str]] = {ref: set() for ref in edges}
        for raw_pair in raw_junctions:
            if (
                not isinstance(raw_pair, list)
                or len(raw_pair) != 2
                or not all(isinstance(ref, str) for ref in raw_pair)
            ):
                valid = False
                break
            left, right = raw_pair
            if (
                left not in edges
                or right not in edges
                or left == right
                or edges[left]["axis"] == edges[right]["axis"]
            ):
                valid = False
                break
            adjacency[left].add(right)
            adjacency[right].add(left)
        if not valid:
            continue

        seen: set[str] = set()
        stack = [next(iter(edges))]
        while stack:
            ref = stack.pop()
            if ref in seen:
                continue
            seen.add(ref)
            stack.extend(adjacency[ref] - seen)
        if seen != set(edges):
            continue

        branched_topology = any(
            len(neighbors) != 2
            for neighbors in adjacency.values()
        )
        segments: list[dict[str, Any]]
        if branched_topology:
            decomposed = _branched_rotational_material_segments(
                edges,
                adjacency,
                axes,
            )
            if decomposed is None:
                continue
            segments = decomposed
        else:
            junction_points: dict[tuple[str, str], dict[str, float]] = {}
            for left in sorted(edges):
                for right in sorted(adjacency[left]):
                    if left >= right:
                        continue
                    point = {
                        edges[left]["axis"]: edges[left]["value"],
                        edges[right]["axis"]: edges[right]["value"],
                    }
                    if set(point) != set(axes):
                        valid = False
                        break
                    junction_points[(left, right)] = point
                if not valid:
                    break
            if not valid:
                continue

            segments = []
            for ref, edge in sorted(edges.items()):
                neighbors = sorted(adjacency[ref])
                if len(neighbors) != 2:
                    valid = False
                    break
                points = [
                    junction_points[
                        (ref, neighbor)
                        if ref < neighbor
                        else (neighbor, ref)
                    ]
                    for neighbor in neighbors
                ]
                segments.append(
                    {
                        "start": dict(points[0]),
                        "end": dict(points[1]),
                        "source_targets": sorted(
                            {
                                edge["target"],
                                edges[neighbors[0]]["target"],
                                edges[neighbors[1]]["target"],
                            }
                        ),
                        "source_ref": ref,
                    }
                )
            if not valid:
                continue

        clipped_segments: list[dict[str, Any]] = []
        for segment in segments:
            source_ref = str(segment.get("source_ref") or "")
            source_edge = edges.get(source_ref)
            if source_edge is None:
                valid = False
                break
            first = dict(segment["start"])
            second = dict(segment["end"])

            if source_edge["axis"] == radial_axis:
                radial = float(source_edge["value"])
                if radial <= axis_center + tolerance:
                    continue
            else:
                first_radial = float(first[radial_axis])
                second_radial = float(second[radial_axis])
                if (
                    first_radial < axis_center - tolerance
                    and second_radial < axis_center - tolerance
                ):
                    continue
                if first_radial < axis_center - tolerance:
                    first[radial_axis] = axis_center
                if second_radial < axis_center - tolerance:
                    second[radial_axis] = axis_center

            if _point_key(first, axes) == _point_key(second, axes):
                continue
            clipped_segments.append(
                {
                    **segment,
                    "start": first,
                    "end": second,
                }
            )
        if not valid:
            continue
        segments = clipped_segments

        if len(segments) < 3:
            continue

        degrees: dict[tuple[float, float], int] = {}
        point_values: dict[tuple[float, float], dict[str, float]] = {}
        for segment in segments:
            for name in ("start", "end"):
                point = segment[name]
                point_id = _point_key(point, axes)
                point_values[point_id] = point
                degrees[point_id] = degrees.get(point_id, 0) + 1

        endpoints = sorted(point for point, degree in degrees.items() if degree == 1)
        if any(degree not in {1, 2} for degree in degrees.values()):
            continue

        if len(endpoints) == 2:
            if any(
                abs(point_values[point][radial_axis] - axis_center) > tolerance
                for point in endpoints
            ):
                continue
            axis_sources: set[str] = set()
            for segment in segments:
                if (
                    _point_key(segment["start"], axes) in endpoints
                    or _point_key(segment["end"], axes) in endpoints
                ):
                    axis_sources.update(segment["source_targets"])
            segments.append(
                {
                    "start": dict(point_values[endpoints[0]]),
                    "end": dict(point_values[endpoints[1]]),
                    "source_targets": sorted(axis_sources),
                    "source_ref": "rotation_axis_closure",
                }
            )
        elif endpoints:
            continue

        by_vertex: dict[tuple[float, float], list[int]] = {}
        for index, segment in enumerate(segments):
            for name in ("start", "end"):
                point_id = _point_key(segment[name], axes)
                by_vertex.setdefault(point_id, []).append(index)
        if any(len(indices) != 2 for indices in by_vertex.values()):
            continue

        start_vertex = min(by_vertex)
        first_options = sorted(
            by_vertex[start_vertex],
            key=lambda index: (
                _point_key(
                    segments[index]["end"]
                    if _point_key(segments[index]["start"], axes) == start_vertex
                    else segments[index]["start"],
                    axes,
                ),
                segments[index]["source_ref"],
            ),
        )
        if not first_options:
            continue

        ordered: list[dict[str, Any]] = []
        used: set[int] = set()
        current_vertex = start_vertex
        current_index = first_options[0]
        while current_index not in used:
            segment = segments[current_index]
            start_id = _point_key(segment["start"], axes)
            end_id = _point_key(segment["end"], axes)
            if start_id == current_vertex:
                oriented = segment
                next_vertex = end_id
            elif end_id == current_vertex:
                oriented = {
                    **segment,
                    "start": segment["end"],
                    "end": segment["start"],
                }
                next_vertex = start_id
            else:
                valid = False
                break
            ordered.append(oriented)
            used.add(current_index)
            current_vertex = next_vertex
            next_indices = [
                index
                for index in by_vertex[current_vertex]
                if index not in used
            ]
            if not next_indices:
                break
            current_index = next_indices[0]

        if (
            not valid
            or len(used) != len(segments)
            or current_vertex != start_vertex
        ):
            continue
        if (
            branched_topology
            and not _ordered_rotational_cycle_matches_material_polarity(
                ordered,
                edges,
                axes,
            )
        ):
            continue

        profile_segments: list[dict[str, Any]] = []
        all_sources = [
            source
            for source in item.get("source_ids", [])
            if isinstance(source, str) and source
        ]
        for index, segment in enumerate(ordered):
            start_point = segment["start"]
            end_point = segment["end"]
            profile_segment: dict[str, Any] = {"type": "line"}
            for axis in axes:
                lower = axis.lower()
                profile_segment[f"{lower}1"] = start_point[axis]
                profile_segment[f"{lower}2"] = end_point[axis]
            profile_segments.append(profile_segment)

            trace_sources = list(all_sources)
            for source_target in segment["source_targets"]:
                trace_sources.extend(resolution.traces.get(source_target, []))
            trace_sources = list(dict.fromkeys(trace_sources))
            draft["source_ledger"].append(
                {
                    "id": f"ROTATIONAL_PROFILE_{index}_TYPE",
                    "semantic": "profile_dimension",
                    "value": "line",
                    "target": f"profile.segments.{index}.type",
                    "evidence": trace_sources,
                    "solver": "rotational_profile_solver",
                }
            )
            for field, value in profile_segment.items():
                if field == "type":
                    continue
                draft["source_ledger"].append(
                    {
                        "id": f"ROTATIONAL_PROFILE_{index}_{field.upper()}",
                        "semantic": "profile_dimension",
                        "value": value,
                        "target": f"profile.segments.{index}.{field}",
                        "evidence": trace_sources,
                        "solver": "rotational_profile_solver",
                        "source_targets": list(segment["source_targets"]),
                    }
                )

        draft["profile"] = {
            "plane": plane,
            "topology": "closed_polygon",
            "rotation_axis": rotation_axis,
            "segments": profile_segments,
        }
        draft["source_ledger"].extend(
            [
                {
                    "id": "ROTATIONAL_PROFILE_PLANE",
                    "semantic": "profile_dimension",
                    "value": plane,
                    "target": "profile.plane",
                    "evidence": list(dict.fromkeys(all_sources)),
                    "solver": "rotational_profile_solver",
                },
                {
                    "id": "ROTATIONAL_PROFILE_TOPOLOGY",
                    "semantic": "profile_dimension",
                    "value": "closed_polygon",
                    "target": "profile.topology",
                    "evidence": list(dict.fromkeys(all_sources)),
                    "solver": "rotational_profile_solver",
                },
                {
                    "id": "ROTATIONAL_PROFILE_AXIS",
                    "semantic": "profile_dimension",
                    "value": rotation_axis,
                    "target": "profile.rotation_axis",
                    "evidence": list(dict.fromkeys(all_sources)),
                    "solver": "rotational_profile_solver",
                },
            ]
        )
        materialized.add(key)
        break

    return materialized


def _rotational_profile_topology_unresolved(
    graph: EvidenceGraph,
    *,
    materialized: set[tuple[str, str, str, int]] | None = None,
) -> list[dict[str, Any]]:
    """Block topology components that still lack canonical metric geometry."""

    materialized = materialized or set()
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int]] = set()
    for observation in graph.observations:
        if (
            not isinstance(observation, dict)
            or observation.get("kind")
            != "hybrid_rotational_profile_topology_ledger"
        ):
            continue
        items = observation.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            key = _rotational_profile_key(item)
            edges = item.get("edges")
            if (
                key is None
                or key in materialized
                or not isinstance(edges, list)
                or not edges
            ):
                continue
            if key in seen:
                continue
            seen.add(key)
            axis, plane, region_id, component_index = key

            source_ids = [
                value
                for value in item.get("source_ids", [])
                if isinstance(value, str) and value
            ]
            stable = _stable_fragment(
                "|".join((axis, plane, region_id, str(component_index)))
            )
            output.append(
                {
                    "id": f"U_ROTATIONAL_PROFILE_{stable}",
                    "kind": "unsupported_representation",
                    "field": "rotational_profile",
                    "axis": axis,
                    "reason": (
                        "established rotational profile topology has not been "
                        "materialized from engineering dimensions into canonical "
                        "profile geometry"
                    ),
                    "source_ids": list(dict.fromkeys(source_ids)),
                    "required_for_modeling": True,
                    "metadata": {
                        "plane": plane,
                        "region_id": region_id,
                        "component_index": component_index,
                        "engineering_coordinate_inferred_from_pixels": False,
                        "pixel_geometry_used_for_topology_only": True,
                    },
                }
            )
    return output


def _unconsumed_rotational_profile_primitive_unresolved(
    draft: dict[str, Any],
    graph: EvidenceGraph,
) -> list[dict[str, Any]]:
    """Block verified non-orthogonal profile primitives absent from geometry.

    Raster evidence may classify a physical boundary as a line or arc, but that
    topology is modeling-critical only when canonical profile geometry actually
    consumes the same physical primitive evidence.  This gate never derives a
    metric coordinate from raster data.
    """

    geometry_evidence: set[str] = set()
    for source in draft.get("source_ledger", []):
        if not isinstance(source, dict):
            continue
        target = source.get("target")
        evidence = source.get("evidence")
        if not (
            isinstance(target, str)
            and target.startswith("profile.")
            and isinstance(evidence, list)
        ):
            continue
        geometry_evidence.update(
            value
            for value in evidence
            if isinstance(value, str) and value
        )

    fragments: dict[str, dict[str, Any]] = {}
    for observation in graph.observations:
        if not isinstance(observation, dict):
            continue
        kind = observation.get("kind")
        items = observation.get("items")
        if not isinstance(items, list):
            continue

        raw_fragments: list[dict[str, Any]] = []
        if kind == "hybrid_physical_rotational_oblique_profile_topology_ledger":
            raw_fragments.extend(
                item for item in items if isinstance(item, dict)
            )
        elif kind == "hybrid_rotational_profile_topology_ledger":
            for item in items:
                if not isinstance(item, dict):
                    continue
                attached = item.get("non_orthogonal_fragments")
                if not isinstance(attached, list):
                    continue
                raw_fragments.extend(
                    fragment
                    for fragment in attached
                    if isinstance(fragment, dict)
                )
        else:
            continue

        for fragment in raw_fragments:
            fragment_id = str(fragment.get("id") or "")
            if fragment_id:
                fragments.setdefault(fragment_id, fragment)

    basis_by_kind = {
        "line": (
            "verified_continuous_straight_raster_segment_"
            "between_structural_contacts"
        ),
        "arc": (
            "verified_continuous_curved_raster_segment_"
            "between_structural_contacts"
        ),
    }
    prefix_by_kind = {
        "line": "hybrid:oblique-line:",
        "arc": "hybrid:curve-boundary:",
    }

    output: list[dict[str, Any]] = []
    for fragment_id, fragment in sorted(fragments.items()):
        primitive_kind = str(fragment.get("primitive_kind") or "")
        if primitive_kind not in basis_by_kind:
            continue
        if (
            fragment.get("primitive_kind_basis")
            != basis_by_kind[primitive_kind]
            or fragment.get("connection_kind")
            != "non_orthogonal_profile_connection"
            or fragment.get("engineering_coordinate_inferred_from_pixels") is not False
            or fragment.get("pixel_geometry_used_for_topology_only") is not True
        ):
            continue

        supporting_edges = fragment.get("supporting_physical_edges")
        if not isinstance(supporting_edges, list) or len(supporting_edges) < 2:
            continue

        source_ids = [
            value
            for value in fragment.get("source_ids", [])
            if isinstance(value, str) and value
        ]
        primitive_sources = sorted(
            {
                value
                for value in source_ids
                if value.startswith(prefix_by_kind[primitive_kind])
            }
        )
        consumed = (
            fragment_id in geometry_evidence
            or (
                bool(primitive_sources)
                and all(
                    source in geometry_evidence
                    for source in primitive_sources
                )
            )
        )
        if consumed:
            continue

        output.append(
            {
                "id": (
                    "U_ROTATIONAL_PRIMITIVE_UNCONSUMED_"
                    f"{_stable_fragment(fragment_id)}"
                ),
                "kind": "unsupported_representation",
                "field": "rotational_profile_primitive",
                "axis": fragment.get("rotation_axis"),
                "reason": (
                    f"verified rotational profile {primitive_kind} primitive "
                    "was not consumed by canonical profile geometry"
                ),
                "source_ids": list(
                    dict.fromkeys([fragment_id, *source_ids])
                ),
                "required_for_modeling": True,
                "metadata": {
                    "primitive_kind": primitive_kind,
                    "primitive_kind_basis": fragment.get(
                        "primitive_kind_basis"
                    ),
                    "plane": fragment.get("plane"),
                    "primitive_sources": primitive_sources,
                    "engineering_coordinate_inferred_from_pixels": False,
                    "pixel_geometry_used_for_topology_only": True,
                },
            }
        )

    return output


def _unconsumed_profile_transition_unresolved(
    draft: dict[str, Any],
    graph: EvidenceGraph,
) -> list[dict[str, Any]]:
    """Block required profile-transition constraints that never affect geometry.

    Resolver/canonical relation consumption is not sufficient for Gate A closure:
    a required profile transition must be explicitly cited by materialized
    profile geometry. This prevents provenance-only constraint values from being
    mistaken for a modeled transition.
    """

    geometry_relation_ids: set[str] = set()
    for source in draft.get("source_ledger", []):
        if not isinstance(source, dict):
            continue
        target = source.get("target")
        evidence = source.get("evidence")
        if not (
            isinstance(target, str)
            and target.startswith("profile.")
            and isinstance(evidence, list)
        ):
            continue
        geometry_relation_ids.update(
            value
            for value in evidence
            if isinstance(value, str) and value
        )

    output: list[dict[str, Any]] = []
    for relation in graph.relations:
        if (
            not relation.required_for_modeling
            or relation.metadata.get("basis")
            != "labeled_overall_to_profile_transition"
            or not relation.targets
            or not all(
                isinstance(target, str)
                and target.startswith("constraints.profile_transitions.")
                for target in relation.targets
            )
            or relation.id in geometry_relation_ids
        ):
            continue

        output.append(
            {
                "id": (
                    "U_PROFILE_TRANSITION_UNCONSUMED_"
                    f"{_stable_fragment(relation.id)}"
                ),
                "kind": "unsupported_representation",
                "field": "profile_transition",
                "axis": relation.axis,
                "reason": (
                    "required labeled profile-transition constraint was resolved "
                    "canonically but was not consumed by materialized profile "
                    "geometry"
                ),
                "target": relation.targets[0],
                "source_ids": list(
                    dict.fromkeys([relation.id, *relation.source_ids])
                ),
                "required_for_modeling": True,
                "metadata": {
                    "relation_id": relation.id,
                    "basis": relation.metadata.get("basis"),
                    "engineering_coordinate_inferred_from_pixels": False,
                },
            }
        )
    return output


def _auto_metric_profile_spec(
    graph: EvidenceGraph,
    resolution: ResolutionResult,
) -> MetricProfileSpec | None:
    topology_items: list[dict[str, Any]] = []
    entity_to_feature: dict[str, str] | None = None

    for observation in graph.observations:
        if not isinstance(observation, dict):
            continue
        if observation.get("kind") == "hybrid_profile_topology_ledger":
            items = observation.get("items")
            if isinstance(items, list):
                topology_items.extend(
                    item for item in items if isinstance(item, dict)
                )
        elif observation.get("kind") == "identity_linker_v2":
            mapping = observation.get("entity_to_feature")
            if isinstance(mapping, dict):
                typed = {
                    str(entity_id): str(feature_id)
                    for entity_id, feature_id in mapping.items()
                    if isinstance(entity_id, str)
                    and entity_id
                    and isinstance(feature_id, str)
                    and feature_id
                }
                if typed:
                    entity_to_feature = typed

    if not topology_items or entity_to_feature is None:
        return None

    def resolved_boundary_coordinate(
        *,
        axis: str,
        entity_id: str,
    ) -> tuple[float, list[str]] | None:
        # Cross-view coordinate reuse is valid only after Identity Linker has
        # proven that this topology entity belongs to the same physical feature.
        # Numeric uniqueness on an engineering axis is not identity evidence.
        feature_id = entity_to_feature.get(entity_id)
        if feature_id is None:
            return None

        direct_target = f"feature:{feature_id}.boundary.{axis}"
        if direct_target not in resolution.values:
            return None

        return (
            float(resolution.values[direct_target]),
            list(resolution.traces.get(direct_target, [])),
        )

    complete: list[MetricProfileSpec] = []
    for item in topology_items:
        plane = str(item.get("plane") or "")
        topology = str(item.get("topology") or "")
        upright_side = str(item.get("upright_side") or "")
        base_side = str(item.get("base_side") or "")
        internal_u_entity_id = str(item.get("internal_u_entity_id") or "")
        internal_v_entity_id = str(item.get("internal_v_entity_id") or "")
        if (
            plane not in {"XY", "XZ", "YZ"}
            or topology != "L"
            or upright_side not in {"min", "max"}
            or base_side not in {"min", "max"}
            or not internal_u_entity_id
            or not internal_v_entity_id
        ):
            continue

        axis_u, axis_v = plane[0].lower(), plane[1].lower()
        resolved_u = resolved_boundary_coordinate(
            axis=axis_u,
            entity_id=internal_u_entity_id,
        )
        resolved_v = resolved_boundary_coordinate(
            axis=axis_v,
            entity_id=internal_v_entity_id,
        )
        if resolved_u is None or resolved_v is None:
            continue

        internal_u, sources_u = resolved_u
        internal_v, sources_v = resolved_v
        overall_u, overall_v = _expected_profile_overall(graph, plane)
        upright_width = (
            internal_u
            if upright_side == "min"
            else overall_u - internal_u
        )
        base_height = (
            internal_v
            if base_side == "min"
            else overall_v - internal_v
        )
        if upright_width <= 0 or base_height <= 0:
            continue

        sources: list[str] = []
        sources.extend(sources_u)
        sources.extend(sources_v)
        for key in ("internal_u_ref", "internal_v_ref"):
            value = item.get(key)
            if isinstance(value, str) and value:
                sources.append(value)
        outer_refs = item.get("outer_refs")
        if isinstance(outer_refs, dict):
            sources.extend(
                value
                for value in outer_refs.values()
                if isinstance(value, str) and value
            )
        region_id = item.get("region_id")
        if isinstance(region_id, str) and region_id:
            sources.append(f"profile-topology:{region_id}")

        try:
            complete.append(
                MetricProfileSpec(
                    plane=plane,
                    topology="L",
                    overall_u=overall_u,
                    overall_v=overall_v,
                    upright_width=upright_width,
                    base_height=base_height,
                    upright_side=upright_side,
                    base_side=base_side,
                    source_ids=list(dict.fromkeys(sources)),
                )
            )
        except ValueError:
            continue

    if len(complete) > 1:
        raise DraftAssemblyError(
            "multiple complete metric profile solutions are available"
        )
    return complete[0] if complete else None



def _materialize_metric_profile(
    draft: dict[str, Any],
    graph: EvidenceGraph,
    spec: MetricProfileSpec,
) -> None:
    expected_u, expected_v = _expected_profile_overall(graph, spec.plane)
    if abs(float(spec.overall_u) - expected_u) > 1e-9:
        raise DraftAssemblyError(
            "metric profile overall_u disagrees with canonical overall dimensions"
        )
    if abs(float(spec.overall_v) - expected_v) > 1e-9:
        raise DraftAssemblyError(
            "metric profile overall_v disagrees with canonical overall dimensions"
        )

    planner_spec = spec.model_copy(
        update={"coordinate_mode": "centered_u_bottom_v"}
    )
    solution = solve_metric_profile(planner_spec)
    if solution.engineering_coordinate_inferred_from_pixels:
        raise DraftAssemblyError(
            "metric profile solver must not infer engineering coordinates from pixels"
        )

    existing = draft.get("profile")
    solved_profile = {
        "plane": solution.plane,
        "topology": solution.topology,
        "segments": copy.deepcopy(solution.segments),
    }
    if existing not in (None, {}) and not _equal(existing, solved_profile):
        raise DraftAssemblyError(
            "metric profile solution conflicts with existing canonical profile"
        )
    draft["profile"] = solved_profile

    evidence = list(dict.fromkeys(spec.source_ids))
    draft["source_ledger"].extend(
        [
            {
                "id": "METRIC_PROFILE_PLANE",
                "semantic": "profile_dimension",
                "value": solution.plane,
                "target": "profile.plane",
                "evidence": evidence,
                "solver": "metric_profile_solver",
            },
            {
                "id": "METRIC_PROFILE_TOPOLOGY",
                "semantic": "profile_dimension",
                "value": solution.topology,
                "target": "profile.topology",
                "evidence": evidence,
                "solver": "metric_profile_solver",
            },
        ]
    )
    for segment_index, segment in enumerate(solution.segments):
        for field, value in segment.items():
            target = f"profile.segments.{segment_index}.{field}"
            draft["source_ledger"].append(
                {
                    "id": (
                        "METRIC_PROFILE_"
                        f"{segment_index}_{field.upper()}"
                    ),
                    "semantic": "profile_dimension",
                    "value": copy.deepcopy(value),
                    "target": target,
                    "evidence": evidence,
                    "solver": "metric_profile_solver",
                }
            )


def build_semantic_draft(
    graph: EvidenceGraph,
    resolution: ResolutionResult | None = None,
    metric_profile: MetricProfileSpec | None = None,
) -> dict[str, Any]:
    """Serialize resolved evidence into the existing semantic-draft contract.

    This function never reads a drawing and never changes Gate A semantics.
    It only materializes already-observed direct values and deterministic
    Resolver results into the contract that the existing canonicalizer expects.
    """

    if resolution is None:
        from .resolver import resolve_evidence_graph

        resolution = resolve_evidence_graph(graph)

    draft: dict[str, Any] = {
        "overall_dimensions": {
            "length_x": graph.overall_dimensions.length_x,
            "width_y": graph.overall_dimensions.width_y,
            "height_z": graph.overall_dimensions.height_z,
        },
        "coordinate_system": {
            "origin": "part_center_xy_bottom_z0",
            "source_origin": "overall_min_xyz",
            "reader_local_bounds": {
                "x": [0.0, graph.overall_dimensions.length_x],
                "y": [0.0, graph.overall_dimensions.width_y],
                "z": [0.0, graph.overall_dimensions.height_z],
            },
            "reader_to_planner_translation": {
                "x": -graph.overall_dimensions.length_x / 2.0,
                "y": -graph.overall_dimensions.width_y / 2.0,
                "z": 0.0,
            },
            "x_positive": "right",
            "y_positive": "declared side-view positive",
            "z_positive": "up",
            "unit": "mm",
        },
        "features": [],
        "patterns": [],
        "symmetry": [],
        "source_ledger": [],
        "derived": [],
        "unresolved": [],
        "dimension_conflicts": copy.deepcopy(resolution.conflicts),
        "dimension_closure": {"status": "closed"},
    }

    if metric_profile is None:
        metric_profile = _auto_metric_profile_spec(graph, resolution)
    if metric_profile is not None:
        _materialize_metric_profile(draft, graph, metric_profile)

    rotational_profile_keys = _materialize_symmetric_tapered_annular_profile(
        draft,
        graph,
        resolution,
    )
    rotational_profile_keys.update(
        _materialize_rotational_profile(
            draft,
            graph,
            resolution,
        )
    )

    # Materialize all direct observations first so feature type is available
    # before semantic inference (for example slot width -> slot_width).
    for fact in sorted(graph.direct_values, key=lambda item: (item.target, item.id)):
        _set_target(
            draft,
            fact.target,
            _planner_value_for_target(graph, fact.target, fact.value),
        )

    direct_targets: set[str] = set()
    for fact in sorted(graph.direct_values, key=lambda item: item.id):
        if fact.target in direct_targets:
            raise DraftAssemblyError(f"multiple direct evidence writers for {fact.target!r}")
        direct_targets.add(fact.target)
        draft["source_ledger"].append(_direct_source(draft, graph, fact))

    relations_by_id = {relation.id: relation for relation in graph.relations}
    for relation in sorted(graph.relations, key=lambda item: item.id):
        draft["source_ledger"].append(_relation_source(relation))

    # Materialize deterministic numeric results only when they were not already
    # written by a direct observation.
    for target, value in sorted(resolution.values.items()):
        planner_value = _planner_value_for_target(graph, target, value)
        current = _get_target(draft, target)
        if current is _MISSING or current is None:
            _set_target(draft, target, planner_value)
        elif not _equal(current, planner_value):
            # Keep the direct value. The Resolver conflict and/or Gate A relation
            # check will reject the inconsistent evidence instead of overwriting it.
            continue

    for target, derivation in sorted(resolution.derivations.items()):
        if target in direct_targets:
            continue
        relation_id = str(derivation.get("relation_id") or "")
        if relation_id and relation_id not in relations_by_id:
            raise DraftAssemblyError(
                f"derivation for {target!r} references unknown relation {relation_id!r}"
            )
        entry = _derived_entry(
            target,
            _planner_value_for_target(
                graph,
                target,
                resolution.values[target],
            ),
            derivation,
        )
        if entry is not None and entry.get("value") != resolution.values[target]:
            entry["reader_local_value"] = resolution.values[target]
        if entry is not None:
            draft["derived"].append(entry)

    draft["unresolved"] = _unresolved_entries(resolution)
    draft["unresolved"].extend(
        _rotational_profile_topology_unresolved(
            graph,
            materialized=rotational_profile_keys,
        )
    )
    draft["unresolved"].extend(
        _unconsumed_rotational_profile_primitive_unresolved(
            draft,
            graph,
        )
    )
    draft["unresolved"].extend(
        _unconsumed_profile_transition_unresolved(
            draft,
            graph,
        )
    )

    if resolution.conflicts:
        draft["dimension_closure"]["status"] = "conflict"
    elif any(
        item.get("required_for_modeling", True)
        for item in draft["unresolved"]
    ):
        draft["dimension_closure"]["status"] = "incomplete"

    _infer_feature_types(draft)
    draft["features"].sort(key=lambda item: str(item.get("id") or ""))
    return draft
