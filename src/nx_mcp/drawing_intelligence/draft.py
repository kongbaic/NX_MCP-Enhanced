from __future__ import annotations

import copy
import re
from typing import Any

from .evidence import DirectValueEvidence, EvidenceGraph, RelationEvidence
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


def _infer_feature_types(draft: dict[str, Any]) -> None:
    """Assign only feature types implied by already-materialized semantics."""

    for feature in draft.get("features", []):
        if not isinstance(feature, dict) or feature.get("type"):
            continue

        keys = set(feature)
        if "boundary" in keys and keys <= {"id", "boundary"}:
            feature["type"] = "reference_boundary"
            continue

        if feature.get("thread_spec") is not None or feature.get("thread_depth") is not None:
            feature["type"] = "threaded_hole"
            continue

        if (
            feature.get("recessed_hole") is True
            or feature.get("recess_diameter") is not None
            or feature.get("recess_depth") is not None
        ):
            feature["type"] = "recessed_hole"
            continue

        if feature.get("diameter") is not None and feature.get("axis") in {"X", "Y", "Z"}:
            feature["type"] = "hole"


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
    elif relation.kind in {"center_spacing", "center_distance"}:
        source.update({"value": relation.value, "between": list(relation.targets)})
    elif relation.kind == "alignment":
        source["links"] = list(relation.targets)
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

    # Gate A treats edge_offset and tangent as relation writers themselves.
    if kind in {"edge_offset", "upper_tangent", "lower_tangent"}:
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

    if kind in {"center_spacing", "center_distance"}:
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


def build_semantic_draft(
    graph: EvidenceGraph, resolution: ResolutionResult | None = None
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
