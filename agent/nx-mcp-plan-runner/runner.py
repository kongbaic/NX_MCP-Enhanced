# -*- coding: utf-8 -*-
"""nx-mcp-plan-runner — a generic, plan-driven executor for nx-agent modeling plans.

This Runner is PART-AGNOSTIC and PLAN-AGNOSTIC:
- it never branches on step numbers, feature names, or part dimensions;
- every behaviour is driven by the plan JSON (tool_args / selection_criteria /
  expectation / topology_changes) and by the executable-format extensions
  (result_bindings / selection_binding / $references / declared retries);
- it never invents repairs: a failed step stops the run (declared retries only).

Modes:
  python runner.py canonicalize-drawing <semantic-draft.json> <drawing.json>
  python runner.py validate-drawing <drawing.json>  # Gate A structural/evidence check, no NX
  python runner.py run   <plan.json> [--workspace DIR] [--report OUT.json]
  python runner.py check <plan.json> [--frozen]     # static, no NX
  python runner.py build <plan.json> <out.json>     # frozen -> executable, no NX

The Runner talks to the resident C# Loader through the existing NX_MCP-Enhanced
bridge (named pipe / SendMessage architecture is untouched). Nothing in
NX_MCP-Enhanced, the C# Loader, or the environment is modified.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import datetime as _dt
import inspect
import json
import math
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import PureWindowsPath
from typing import Any

# --------------------------------------------------------------------------
# certified tool contract — static data, not part-specific
# --------------------------------------------------------------------------
CERTIFIED_TOOLS = {
    "nx_status", "nx_create_part", "nx_open_part", "nx_save_part",
    "nx_close_part", "nx_export_step", "nx_list_sketches", "nx_list_bodies",
    "nx_list_features", "nx_list_edges", "nx_list_faces", "nx_create_sketch",
    "nx_sketch_line", "nx_sketch_rectangle", "nx_sketch_circle",
    "nx_sketch_arc", "nx_finish_sketch", "nx_extrude", "nx_hole",
    "nx_counterbore_hole", "nx_countersink_hole", "nx_shell", "nx_edge_blend",
    "nx_chamfer", "nx_unite", "nx_revolve", "nx_mirror", "nx_linear_pattern",
    "nx_circular_pattern", "nx_undo", "nx_fit_view", "nx_release",
}

# tool -> (required params, optional params). Derived from certified.py.
TOOL_PARAMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "nx_status": ((), ()),
    "nx_create_part": (("path",), ("units",)),
    "nx_open_part": (("path",), ()),
    "nx_save_part": ((), ()),
    "nx_close_part": ((), ("save",)),
    "nx_export_step": (("path",), ()),
    "nx_list_sketches": ((), ()),
    "nx_list_bodies": ((), ()),
    "nx_list_features": ((), ()),
    "nx_list_edges": (("body_id",), ()),
    "nx_list_faces": (("body_id",), ()),
    "nx_create_sketch": ((), ("plane", "name")),
    "nx_sketch_line": (("sketch_id", "start", "end"), ()),
    "nx_sketch_rectangle": (("sketch_id", "corner1", "corner2"), ()),
    "nx_sketch_circle": (("sketch_id", "center", "diameter"), ()),
    "nx_sketch_arc": (("sketch_id", "center", "radius"), ("start_angle", "end_angle")),
    "nx_finish_sketch": (("sketch_id",), ()),
    "nx_extrude": (("sketch_id", "distance"), ("reverse", "start_offset", "operation", "target_body_id")),
    "nx_hole": (("body_id", "center", "diameter", "depth"), ("start_offset",)),
    "nx_counterbore_hole": (("body_id", "center", "hole_diameter", "hole_depth", "counterbore_diameter", "counterbore_depth"), ("start_offset",)),
    "nx_countersink_hole": (("body_id", "center", "hole_diameter", "hole_depth", "countersink_diameter"), ("countersink_angle", "start_offset")),
    "nx_shell": (("body_id", "thickness", "remove_face_index"), ("inward",)),
    "nx_edge_blend": (("body_id", "radius"), ("edge_indices",)),
    "nx_chamfer": (("body_id", "offset"), ("edge_indices",)),
    "nx_unite": (("target_body_id", "tool_body_ids"), ()),
    "nx_revolve": (("sketch_id", "axis_start", "axis_end"), ("angle", "reverse")),
    "nx_mirror": (("body_id", "plane"), ("offset",)),
    "nx_linear_pattern": (("body_id", "direction", "count", "spacing"), ("reverse",)),
    "nx_circular_pattern": (("body_id", "axis", "center", "count", "angle"), ("reverse",)),
    "nx_undo": ((), ()),
    "nx_fit_view": ((), ()),
    "nx_release": ((), ()),
}

# params that always stay lists after $selection resolution
LIST_PARAMS = {"edge_indices", "tool_body_ids"}
# tools whose raw loader result carries a "done=N" count that the bridge drops
RAW_PIPE_TOOLS = {"nx_edge_blend", "nx_chamfer"}

RUNTIME_CONFIG_FILENAME = "runtime-config.json"
CAPABILITY_REGISTRY_FILENAME = "modeling_capabilities.json"

# Static handler binding surface for capability declarations. These identifiers
# are deliberately separate from task/run state: the capability file may only
# reference adapter/validator handlers that this Runner knows how to dispatch.
REGISTERED_PLANNER_ADAPTER_HANDLERS = frozenset(
    {
        "rotational_profile_revolve",
        "native_z_hole",
        "principal_axis_circular_subtract",
        "native_z_counterbore",
        "principal_axis_counterbore",
        "metric_thread_surrogate",
    }
)
REGISTERED_GATE_B_VALIDATOR_HANDLERS = frozenset(
    {
        "rotational_profile_revolve_geometry",
        "native_hole_geometry",
        "circular_subtract_geometry",
        "native_counterbore_geometry",
        "transverse_recess_geometry",
        "thread_surrogate",
    }
)


def _default_capability_registry_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        CAPABILITY_REGISTRY_FILENAME,
    )


def capability_registry_errors(
    data: dict[str, Any],
    *,
    available_tools: set[str] | None = None,
    planner_adapter_handlers: set[str] | frozenset[str] | None = None,
    gate_b_validator_handlers: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Validate the static feature-to-implementation capability seam."""
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("capability registry schema_version must be 1")
    if data.get("registry_kind") != "static_modeling_capabilities":
        errors.append(
            "capability registry kind must be static_modeling_capabilities"
        )
    implementations = data.get("implementations")
    if not isinstance(implementations, list):
        return [*errors, "capability registry implementations must be a list"]

    tools = set(CERTIFIED_TOOLS if available_tools is None else available_tools)
    adapter_handlers = set(
        REGISTERED_PLANNER_ADAPTER_HANDLERS
        if planner_adapter_handlers is None
        else planner_adapter_handlers
    )
    validator_handlers = set(
        REGISTERED_GATE_B_VALIDATOR_HANDLERS
        if gate_b_validator_handlers is None
        else gate_b_validator_handlers
    )
    seen: set[str] = set()
    for index, item in enumerate(implementations):
        label = f"capability implementations[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue

        implementation_id = item.get("implementation_id")
        if not isinstance(implementation_id, str) or not implementation_id:
            errors.append(f"{label} requires implementation_id")
        elif implementation_id in seen:
            errors.append(f"duplicate capability implementation_id {implementation_id!r}")
        else:
            seen.add(implementation_id)

        if not isinstance(item.get("feature_kind"), str) or not item["feature_kind"]:
            errors.append(f"{label} requires feature_kind")
        if item.get("exactness") not in {"exact", "surrogate"}:
            errors.append(f"{label} exactness must be exact|surrogate")

        axes = item.get("supported_axes")
        if (
            not isinstance(axes, list)
            or not axes
            or any(axis not in {"X", "Y", "Z"} for axis in axes)
            or len(set(axes)) != len(axes)
        ):
            errors.append(f"{label} supported_axes must be unique X/Y/Z values")

        required_tools = item.get("required_tools")
        if (
            not isinstance(required_tools, list)
            or not required_tools
            or any(not isinstance(tool, str) or not tool for tool in required_tools)
        ):
            errors.append(f"{label} required_tools must be a non-empty string list")
        else:
            missing = sorted(set(required_tools) - tools)
            if missing:
                errors.append(
                    f"{label} requires unavailable certified tools: "
                    + ", ".join(missing)
                )

        planner_adapter = item.get("planner_adapter")
        if not isinstance(planner_adapter, str) or not planner_adapter:
            errors.append(f"{label} requires planner_adapter")
        elif planner_adapter not in adapter_handlers:
            errors.append(
                f"{label} references unbound planner_adapter {planner_adapter!r}"
            )

        gate_b_validator = item.get("gate_b_validator")
        if not isinstance(gate_b_validator, str) or not gate_b_validator:
            errors.append(f"{label} requires gate_b_validator")
        elif gate_b_validator not in validator_handlers:
            errors.append(
                f"{label} references unbound gate_b_validator {gate_b_validator!r}"
            )

        priority = item.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 0:
            errors.append(f"{label} priority must be a non-negative integer")

    return errors


def load_modeling_capability_registry(path: str | None = None) -> dict[str, Any]:
    """Load the installer-copied static capability registry beside runner.py."""
    registry_path = path or _default_capability_registry_path()
    try:
        with open(registry_path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(
            f"cannot load modeling capability registry {registry_path!r}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise PlanError("modeling capability registry root must be an object")
    return data


def resolve_modeling_capabilities(
    feature_kind: str,
    axis: str,
    *,
    allow_surrogate: bool = True,
    registry: dict[str, Any] | None = None,
    available_tools: set[str] | None = None,
    planner_adapter_handlers: set[str] | frozenset[str] | None = None,
    gate_b_validator_handlers: set[str] | frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return deterministic implementation candidates for one Feature Contract."""
    axis = str(axis or "").upper()
    if axis not in {"X", "Y", "Z"}:
        return [], [f"unsupported feature axis {axis!r}"]

    data = registry if registry is not None else load_modeling_capability_registry()
    errors = capability_registry_errors(
        data,
        available_tools=available_tools,
        planner_adapter_handlers=planner_adapter_handlers,
        gate_b_validator_handlers=gate_b_validator_handlers,
    )
    if errors:
        return [], errors

    candidates = [
        dict(item)
        for item in data.get("implementations", [])
        if isinstance(item, dict)
        and item.get("feature_kind") == feature_kind
        and axis in item.get("supported_axes", [])
        and (allow_surrogate or item.get("exactness") == "exact")
    ]
    candidates.sort(
        key=lambda item: (
            0 if item.get("exactness") == "exact" else 1,
            int(item.get("priority", 0)),
            str(item.get("implementation_id") or ""),
        )
    )
    if not candidates:
        return [], [
            f"no modeling capability for feature_kind={feature_kind!r}, "
            f"axis={axis!r}, allow_surrogate={allow_surrogate}"
        ]
    return candidates, []


def _cmd_capabilities(args: argparse.Namespace) -> int:
    try:
        registry = load_modeling_capability_registry(
            getattr(args, "registry", None)
        )
    except PlanError as exc:
        result = {
            "registry": getattr(args, "registry", None)
            or _default_capability_registry_path(),
            "capabilities": [],
            "errors": [str(exc)],
            "ok": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    feature_kind = getattr(args, "feature_kind", None)
    axis = getattr(args, "axis", None)
    exact_only = bool(getattr(args, "exact_only", False))
    if feature_kind is None and axis is None:
        errors = capability_registry_errors(registry)
        candidates = (
            []
            if errors
            else sorted(
                (
                    dict(item)
                    for item in registry.get("implementations", [])
                    if isinstance(item, dict)
                ),
                key=lambda item: (
                    str(item.get("feature_kind") or ""),
                    0 if item.get("exactness") == "exact" else 1,
                    int(item.get("priority", 0)),
                    str(item.get("implementation_id") or ""),
                ),
            )
        )
    elif feature_kind is None or axis is None:
        candidates = []
        errors = ["--feature-kind and --axis must be supplied together"]
    else:
        candidates, errors = resolve_modeling_capabilities(
            feature_kind,
            axis,
            allow_surrogate=not exact_only,
            registry=registry,
        )

    result = {
        "schema_version": registry.get("schema_version"),
        "registry_kind": registry.get("registry_kind"),
        "feature_kind": feature_kind,
        "axis": axis,
        "exact_only": exact_only,
        "capabilities": candidates,
        "errors": errors,
        "ok": not errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def load_runtime_config(path: str | None = None) -> dict:
    """Load installer-written runtime config; missing/invalid config is non-fatal."""
    cfg_path = path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), RUNTIME_CONFIG_FILENAME
    )
    if not os.path.isfile(cfg_path):
        return {}
    try:
        with open(cfg_path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}



DEFAULT_TOL = 0.5


class PlanError(Exception):
    """Fatal, plan-level error (stops the run)."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _num(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _approx(a: Any, b: Any, tol: float) -> bool:
    a, b = _num(a), _num(b)
    return a is not None and b is not None and abs(a - b) <= tol


def _item_id(x: Any) -> Any:
    return getattr(x, "id", x)


def _walk(value: Any):
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)
    else:
        yield value


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _utc_now_iso_best_effort() -> str | None:
    try:
        return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except Exception:
        return None


def _perf_counter_ns_best_effort() -> int | None:
    try:
        return time.perf_counter_ns()
    except Exception:
        return None


def _file_metadata_observation(path: str) -> dict[str, Any]:
    """Observe mtime only; it is not proof of the file's first write."""
    result = {
        "path": path,
        "file_mtime_utc": None,
        "observed_at_utc": _utc_now_iso_best_effort(),
        "first_write_reliable": False,
    }
    try:
        modified = os.stat(path).st_mtime
        result["file_mtime_utc"] = _dt.datetime.fromtimestamp(modified, _dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except Exception:
        pass
    return result


def _begin_command_timing(stage: str, input_path: str | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "stage": stage,
        "started_at_utc": _utc_now_iso_best_effort(),
        "started_perf_ns": _perf_counter_ns_best_effort(),
    }
    if input_path is not None:
        state["input_file"] = _file_metadata_observation(input_path)
    return state


def _finish_command_timing(state: dict[str, Any], boundaries: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        ended = _perf_counter_ns_best_effort()
        started = state.get("started_perf_ns")
        elapsed_ms = round((ended - started) / 1_000_000.0, 3) if isinstance(started, int) and isinstance(ended, int) else None
        result = {
            "stage": state.get("stage"),
            "started_at_utc": state.get("started_at_utc"),
            "ended_at_utc": _utc_now_iso_best_effort(),
            "elapsed_ms": elapsed_ms,
        }
        if "input_file" in state:
            result["input_file"] = state.get("input_file")
        if boundaries:
            result.update(boundaries)
        return result
    except Exception:
        return {"stage": state.get("stage"), "started_at_utc": state.get("started_at_utc"), "ended_at_utc": None, "elapsed_ms": None}


def _attach_command_timing(result: dict[str, Any], state: dict[str, Any], boundaries: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        result["timing"] = _finish_command_timing(state, boundaries)
    except Exception:
        pass
    return result


# --------------------------------------------------------------------------
# symbol table and reference resolution
# --------------------------------------------------------------------------
class Symbols:
    """Unified symbol table: logical names -> real ids, plus selection symbols."""

    def __init__(self) -> None:
        self.names: dict[str, Any] = {}
        self.selection: dict[str, Any] = {}

    def bind(self, name: str, value: Any) -> None:
        self.names[name] = value

    def bind_selection(self, name: str, value: Any) -> None:
        self.selection[name] = value


def resolve_value(value: Any, symbols: Symbols) -> Any:
    """Resolve $references and bare logical names recursively.

    - "$name"             -> symbols.names[name]
    - "$selection.x"      -> symbols.selection[x] (or dotted path into it)
    - a bare string that is a known logical name -> its real id
    """
    if isinstance(value, dict):
        return {k: resolve_value(v, symbols) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, symbols) for v in value]
    if isinstance(value, str):
        if value.startswith("$"):
            return _resolve_ref(value, symbols)
        if value in symbols.names:
            return symbols.names[value]
    return value


def _resolve_ref(text: str, symbols: Symbols) -> Any:
    path = text[1:].split(".")
    if path[0] == "selection":
        cur: Any = symbols.selection
        for p in path[1:]:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                raise PlanError(f"unresolved reference {text!r}")
        return cur
    if path[0] in symbols.names:
        return symbols.names[path[0]]
    raise PlanError(f"unresolved reference {text!r}")


def finalize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Post-resolution coercions: unwrap single-element selection lists for
    scalar params; int-ify index / count params. tool_body_ids stay strings."""
    out = dict(args)
    for k, v in list(out.items()):
        if k == "edge_indices":
            if isinstance(v, list):
                out[k] = [int(_item_id(x)) for x in v]
        elif isinstance(v, list) and len(v) == 1:
            out[k] = _item_id(v[0])
        if k in ("remove_face_index", "count"):
            out[k] = int(_item_id(out[k]))
    return out


# --------------------------------------------------------------------------
# generic adapters (loader grammar, tool-level only)
# --------------------------------------------------------------------------
def adapt_rectangle(args: dict[str, Any]) -> dict[str, Any]:
    """nx_sketch_rectangle: plan corner1/corner2 -> bridge slots corner1={cx,cy},
    corner2={w,h} (the loader grammar is: sketch_id cx cy w h = center, size)."""
    c1, c2 = args.get("corner1"), args.get("corner2")
    if not (isinstance(c1, dict) and isinstance(c2, dict) and "x" in c1 and "x" in c2):
        return args
    out = dict(args)
    out["corner1"] = {
        "x": (c1["x"] + c2["x"]) / 2.0,
        "y": (c1["y"] + c2["y"]) / 2.0,
    }
    out["corner2"] = {"x": c2["x"] - c1["x"], "y": c2["y"] - c1["y"]}
    return out


# --------------------------------------------------------------------------
# generic selection engine (understands geometry only)
# --------------------------------------------------------------------------
def _is_info_key(key: str) -> bool:
    return key in ("note", "use") or "auxiliary" in key


def _base_key(key: str) -> str:
    return key[:-6] if key.endswith("_approx") else key


def _match_num(actual: Any, spec: Any, tol: float) -> bool:
    a = _num(actual)
    if a is None:
        return False
    if isinstance(spec, bool):
        return False
    if isinstance(spec, (int, float)):
        return _approx(a, spec, tol)
    if isinstance(spec, dict):
        if "value" in spec:
            return _approx(a, spec["value"], spec.get("tol", tol))
        if "min" in spec or "max" in spec:
            lo = spec.get("min", -math.inf)
            hi = spec.get("max", math.inf)
            return lo <= a <= hi
        if "any" in spec:
            return any(_match_num(a, c, tol) for c in spec["any"])
        return False
    if isinstance(spec, (list, tuple)):
        if len(spec) == 2 and all(isinstance(i, (int, float)) and not isinstance(i, bool) for i in spec):
            return spec[0] <= a <= spec[1]
        return any(_approx(a, c, tol) for c in spec)
    return False


def _vec_close(a: Any, b: Any, tol: float) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return all(_approx(a[i], b[i], tol) for i in range(len(b)))


def _match_vec(actual: Any, spec: Any, tol: float) -> bool:
    if actual is None:
        return False
    if isinstance(spec, dict):
        if "any" in spec:
            return any(_vec_close(actual, c, spec.get("tol", tol)) for c in spec["any"])
        if "value" in spec:
            return _vec_close(actual, spec["value"], spec.get("tol", tol))
        return all(_approx(actual[i], spec[k], tol) for i, k in enumerate(("x", "y", "z")) if k in spec)
    if isinstance(spec, (list, tuple)):
        return _vec_close(actual, spec, tol)
    return False


def _match_edge(e: dict, criteria: dict, tol: float) -> bool:
    for key, spec in criteria.items():
        if _is_info_key(key):
            continue
        k = _base_key(key)
        if k == "curve_type":
            types = spec if isinstance(spec, list) else [spec]
            if e.get("curve_type") not in types:
                return False
        elif k == "direction":
            dirs = spec if isinstance(spec, list) else [spec]
            if e.get("direction") not in dirs:
                return False
        elif k == "length":
            if not _match_num(e.get("length"), spec, tol):
                return False
        elif k == "midpoint":
            if not _match_vec(e.get("midpoint"), spec, tol):
                return False
        elif k == "midpoint_z":
            mid = e.get("midpoint")
            if mid is None or not _match_num(mid[2], spec, tol):
                return False
        elif k == "bbox":
            bmin, bmax = e.get("bbox_min"), e.get("bbox_max")
            if bmin is None or bmax is None:
                return False
            if isinstance(spec, dict) and "min" in spec and "max" in spec:
                if not (_vec_close(bmin, spec["min"], tol) and _vec_close(bmax, spec["max"], tol)):
                    return False
            else:
                return False
        elif k in ("bbox_x", "bbox_y", "bbox_z"):
            bmin, bmax = e.get("bbox_min"), e.get("bbox_max")
            if bmin is None or bmax is None:
                return False
            axis = {"bbox_x": 0, "bbox_y": 1, "bbox_z": 2}[k]
            lo, hi = min(bmin[axis], bmax[axis]), max(bmin[axis], bmax[axis])
            if not (_match_num(lo, spec, tol) and _match_num(hi, spec, tol)):
                return False
        elif k == "corners_xy":
            bmin, bmax = e.get("bbox_min"), e.get("bbox_max")
            if bmin is None or bmax is None:
                return False
            cands = spec if isinstance(spec, list) else spec.get("any", [])
            ctol = spec.get("tol", tol) if isinstance(spec, dict) else tol
            if not any(_approx(bmin[0], cx, ctol) and _approx(bmin[1], cy, ctol)
                       and _approx(bmax[0], cx, ctol) and _approx(bmax[1], cy, ctol)
                       for cx, cy in cands):
                return False
        elif k == "adjacent_faces":
            if not _match_num(e.get("adjacent_faces"), spec, tol):
                return False
        elif k == "linear_only":
            if spec and e.get("curve_type") != "Linear":
                return False
        # unknown keys are ignored (forward compatible)
    return True


def _match_face(f: dict, criteria: dict, tol: float) -> bool:
    for key, spec in criteria.items():
        if _is_info_key(key):
            continue
        k = _base_key(key)
        if k == "face_type":
            types = spec if isinstance(spec, list) else [spec]
            if f.get("face_type") not in types:
                return False
        elif k == "centroid":
            if not _match_vec(f.get("centroid"), spec, tol):
                return False
        elif k == "centroid_z":
            c = f.get("centroid")
            if c is None or not _match_num(c[2], spec, tol):
                return False
        elif k == "centroid_radius":
            c = f.get("centroid")
            if c is None or not _match_num(math.hypot(c[0], c[1]), spec, tol):
                return False
        elif k == "normal":
            if not _match_vec(f.get("normal"), spec, tol):
                return False
        elif k == "area":
            if not _match_num(f.get("area"), spec, tol):
                return False
        # unknown keys ignored
    return True


def _match_items(items: list, criteria: dict, kind: str, tol: float) -> list:
    if kind == "edges":
        return [it for it in items if _match_edge(it, criteria, tol)]
    return [it for it in items if _match_face(it, criteria, tol)]


def _is_group_criteria(criteria: dict) -> bool:
    known = {
        "curve_type", "direction", "length", "midpoint", "midpoint_z", "bbox",
        "bbox_x", "bbox_y", "bbox_z", "corners_xy", "adjacent_faces",
        "linear_only", "face_type", "centroid", "centroid_z",
        "centroid_radius", "normal", "area",
    }
    return any(key not in known and not _is_info_key(key) for key in criteria)


def compute_extents(items: list, kind: str) -> dict | None:
    xs, ys, zs = [], [], []
    for it in items:
        if kind == "edges":
            if it.get("curve_type") != "Linear":
                continue
            bmin, bmax = it.get("bbox_min"), it.get("bbox_max")
            if not bmin or not bmax:
                continue
            xs += [bmin[0], bmax[0]]
            ys += [bmin[1], bmax[1]]
            zs += [bmin[2], bmax[2]]
        else:
            c = it.get("centroid")
            if not c:
                continue
            xs.append(c[0])
            ys.append(c[1])
            zs.append(c[2])
    if not xs:
        return None
    return {"x_min": min(xs), "x_max": max(xs),
            "y_min": min(ys), "y_max": max(ys),
            "z_min": min(zs), "z_max": max(zs)}


def merge_extents(a: dict | None, b: dict | None) -> dict | None:
    """Span-wise union of two extents dicts (None-safe). Report semantics only."""
    if not b:
        return a
    if not a:
        return dict(b)
    return {
        "x_min": min(a["x_min"], b["x_min"]), "x_max": max(a["x_max"], b["x_max"]),
        "y_min": min(a["y_min"], b["y_min"]), "y_max": max(a["y_max"], b["y_max"]),
        "z_min": min(a["z_min"], b["z_min"]), "z_max": max(a["z_max"], b["z_max"]),
    }


def run_selection(items: list, criteria: dict, kind: str, tol: float = DEFAULT_TOL) -> dict:
    """Run flat or named-group criteria. Returns counts / group items / extents."""
    if _is_group_criteria(criteria):
        group_items: dict[str, list] = {}
        for gname, gcrit in criteria.items():
            if _is_info_key(gname):
                continue
            if isinstance(gcrit, dict):
                group_items[gname] = _match_items(items, gcrit, kind, tol)
        flat = [it for g in group_items.values() for it in g]
        return {
            "count": len(flat),
            "groups": {g: len(v) for g, v in group_items.items()},
            "group_items": group_items,
            "extents": compute_extents(flat, kind),
            "items": flat,
        }
    flat = _match_items(items, criteria, kind, tol)
    return {"count": len(flat), "groups": {}, "group_items": {},
            "extents": compute_extents(flat, kind), "items": flat}


def _require_raw_loader_success(tool: str, resp: Any) -> dict:
    """Reject raw Loader responses that did not explicitly succeed."""

    if not isinstance(resp, dict):
        raise PlanError(
            f"{tool}: raw loader response must be an object"
        )
    if resp.get("ok") is not True:
        raw_error = resp.get("error")
        if isinstance(raw_error, dict):
            detail = str(
                raw_error.get("message")
                or raw_error.get("code")
                or json.dumps(raw_error, ensure_ascii=False, sort_keys=True)
            )
        else:
            detail = str(raw_error or "loader returned ok=false")
        raise PlanError(
            f"{tool}: raw loader command failed: {detail}"
        )
    return resp


def _parse_done(resp: dict) -> int | None:
    for key in ("result", "message"):
        m = re.search(r"done=(\d+)", str(resp.get(key, "")))
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


# --------------------------------------------------------------------------
# expectation checker
# --------------------------------------------------------------------------
def check_expectation(expect: dict, selection: dict, resp: dict, tol: float = DEFAULT_TOL) -> list[str]:
    fails: list[str] = []
    count = selection.get("count", 0)
    groups = selection.get("groups", {})
    ext = selection.get("extents") or {}
    for key, spec in expect.items():
        if key in ("purpose", "note", "tolerance_mm") or "auxiliary" in key or key.endswith("_approx"):
            continue
        if key == "count":
            if count != spec:
                fails.append(f"count {count} != {spec}")
        elif key == "count_range":
            lo, hi = spec if isinstance(spec, (list, tuple)) else (spec["min"], spec["max"])
            if not (lo <= count <= hi):
                fails.append(f"count {count} outside {lo}..{hi}")
        elif key == "body_count":
            n = len(resp.get("objects") or [])
            if n != spec:
                fails.append(f"body_count {n} != {spec}")
        elif key.endswith("_count_range"):
            gname = key[: -len("_count_range")]
            n = groups.get(gname)
            lo, hi = spec if isinstance(spec, (list, tuple)) else (spec["min"], spec["max"])
            if n is None or not (lo <= n <= hi):
                fails.append(f"{gname} count {n} outside {lo}..{hi}")
        elif key.endswith("_count"):
            gname = key[: -len("_count")]
            n = groups.get(gname)
            if n != spec:
                fails.append(f"{gname} count {n} != {spec}")
        elif key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"):
            t = expect.get("tolerance_mm", tol)
            if key not in ext:
                fails.append(f"{key}: no extent available")
            elif not _approx(ext[key], spec, t):
                fails.append(f"{key} {ext[key]} != {spec} (±{t})")
        elif key == "done":
            got = _parse_done(resp)
            if got != spec:
                fails.append(f"done {got} != {spec}")
        # unknown expectation keys ignored (forward compatible)
    return fails


# --------------------------------------------------------------------------
# transport (lazy NX imports; resident Loader via existing bridge)
# --------------------------------------------------------------------------
class NXTransport:
    def __init__(self, workspace_root: str | None = None) -> None:
        self._bridge = None
        self._lb = None
        self._ws = None
        self._runtime_config = load_runtime_config()
        self.workspace_root = (
            workspace_root
            or os.environ.get("NX_MCP_WORKSPACE")
            or str(self._runtime_config.get("workspace_root") or "")
        )

    def _ensure(self):
        if self._bridge is not None:
            return
        src = (
            os.environ.get("NX_MCP_ENHANCED_SRC")
            or str(self._runtime_config.get("nx_mcp_src") or "")
        )
        if not src:
            cand = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "NX_MCP-Enhanced",
                "src",
            )
            if os.path.isdir(cand):
                src = cand
        if src and os.path.isdir(src):
            sys.path.insert(0, src)
        try:
            from nx_mcp.loader_bridge import LoaderBridge
            import nx_mcp.loader_bridge as lb
            from nx_mcp.workspace import Workspace
        except Exception as e:  # pragma: no cover - env-dependent
            raise PlanError(f"cannot import NX_MCP bridge: {e}") from e
        self._lb = lb
        self._bridge = LoaderBridge()
        self._ws = Workspace(self.workspace_root or ".")

    def ping(self) -> bool:
        self._ensure()
        return bool(self._bridge.ping())

    def ping_error(self) -> str | None:
        self._ensure()
        return getattr(self._bridge, "last_ping_error", None)

    def resolve_path(self, path: str) -> str:
        self._ensure()
        return str(self._ws.resolve(path))

    async def call(self, tool: str, args: dict) -> dict:
        self._ensure()
        return await self._bridge.call(tool, args)

    async def call_raw(self, tool: str, args: dict) -> dict:
        """Direct named-pipe call (keeps the loader's done=N in the result)."""
        self._ensure()
        cmd = self._lb._command(tool, args)
        if cmd is None:
            raise PlanError(f"tool {tool!r} not supported by the C# Loader")
        return await asyncio.to_thread(self._lb._pipe_call, cmd, 180.0, self._bridge.pipe)

    async def preflight_close(self) -> None:
        """Close a stale part left by an aborted earlier run (never saved)."""
        try:
            await self.call("nx_close_part", {"save": False})
        except Exception:
            pass


# --------------------------------------------------------------------------
# topology state
# --------------------------------------------------------------------------
class TopologyState:
    def __init__(self) -> None:
        self.edges_valid = True
        self.faces_valid = True
        self.edges_cached: list = []
        self.faces_cached: list = []

    def invalidate(self) -> None:
        self.edges_valid = False
        self.faces_valid = False
        self.edges_cached = []
        self.faces_cached = []


# --------------------------------------------------------------------------
# run history (preflight safety: never destroy parts we do not own)
# --------------------------------------------------------------------------
def _norm_path(p: str) -> str:
    return os.path.normcase(os.path.normpath(p or ""))


class RunHistory:
    """Persistent record of parts the Runner created and their save state.

    The C# Loader exposes no dirty/modified flag through certified tools, so the
    Runner reconstructs dirtiness conservatively: a part is CLEAN only when the
    Runner's own record proves the last run saved it; anything else (no record,
    or a failed/aborted run) is treated as DIRTY.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.entries = data
        except (OSError, ValueError):
            self.entries = {}

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _key(self, p: str) -> str:
        return _norm_path(p)

    def paths(self) -> set[str]:
        return set(self.entries.keys())

    def most_recent(self, p: str) -> dict | None:
        return self.entries.get(self._key(p))

    def record_start(
        self, p: str, mode: str, plan: str, repair_attempt: int = 0
    ) -> None:
        self.entries[self._key(p)] = {
            "save_ok": False,
            "mode": mode,
            "plan": plan or "",
            "repair_attempt": int(repair_attempt),
            "started_at": _now_iso(),
            "saved_at": None,
        }
        self.save()

    def record_saved(self, p: str) -> None:
        e = self.entries.setdefault(self._key(p), {})
        e["save_ok"] = True
        e["saved_at"] = _now_iso()
        self.save()

    def record_failed(self, p: str) -> None:
        e = self.entries.setdefault(self._key(p), {})
        e["save_ok"] = False
        e["failed_at"] = _now_iso()
        self.save()


# --------------------------------------------------------------------------
# preflight safety policy
# --------------------------------------------------------------------------
def runtime_dirty(active_path: str, history: RunHistory | None) -> bool:
    """Dirty state of the active part as seen by the Runner.

    The loader cannot report IsModified, so the Runner is conservative:
    no record / failed last run -> dirty; proven successful save -> clean.
    """
    if not active_path:
        return False
    rec = history.most_recent(active_path) if history is not None else None
    if rec is None:
        return True
    return not rec.get("save_ok", False)


def preflight_decision(active_path: str, planned_path: str, mode: str,
                       overwrite_allowed: bool, dirty: bool,
                       runner_parts, repair_authorized: bool = False,
                       part_entry_tool: str | None = None) -> tuple[str, dict]:
    """Pure preflight policy (unit-testable without NX).

    Runner may auto-close ONLY:
      A. the part whose path exactly matches the plan's target part, and
      B. parts the Runner itself created (recorded in its own history),
         except when the current task is a fresh nx_create_part.
    For a fresh nx_create_part task, any unrelated active part -- including a
    part recorded in Runner history -- remains open and is never closed;
    nx_create_part must switch the real NX Work Part to planned_path and the
    executor verifies that immediately after creation. Other unrelated active
    parts -> blocked. A dirty planned part is closed only for an explicitly
    authorized controlled-repair attempt in benchmark mode.
    """
    if not active_path:
        return ("allow", {"active_part": None, "state": "no_active_part"})
    active_n = _norm_path(active_path)
    planned_n = _norm_path(planned_path) if planned_path else ""
    if planned_n and active_n == planned_n:
        if not dirty:
            return ("allow", {"active_part": active_path, "state": "planned_clean"})
        if mode == "benchmark" and overwrite_allowed and repair_authorized:
            return ("allow", {"active_part": active_path,
                              "state": "planned_dirty_controlled_repair"})
        return ("blocked", {
            "reason": "planned_part_dirty",
            "active_part": active_path, "planned_part": planned_path,
            "mode": mode, "overwrite_allowed": overwrite_allowed})
    if part_entry_tool == "nx_create_part" and planned_n:
        return ("allow", {
            "active_part": active_path,
            "planned_part": planned_path,
            "state": "unrelated_part_preserved_for_create",
        })
    if active_n in {_norm_path(p) for p in (runner_parts or ())}:
        return ("allow", {"active_part": active_path, "state": "runner_test_part"})
    return ("blocked", {
        "reason": "unrelated_part_open",
        "active_part": active_path, "planned_part": planned_path})


def derive_part_entry_tool(plan: dict) -> str | None:
    """Return the first part-entry tool that establishes the task work part."""
    for op in plan.get("operations") or []:
        tool = op.get("tool")
        if tool in ("nx_create_part", "nx_open_part"):
            return str(tool)
    return None


def derive_planned_part(plan: dict, transport) -> str | None:
    """The plan's target output part (first nx_create_part / nx_open_part path)."""
    for op in plan.get("operations") or []:
        if op.get("tool") in ("nx_create_part", "nx_open_part"):
            p = (op.get("tool_args") or {}).get("path")
            if isinstance(p, str):
                return transport.resolve_path(p)
    return None


def repair_request_errors(
    repair_attempt: int,
    mode: str,
    overwrite_allowed: bool,
    planned_part: str | None,
    previous_report: dict | None,
) -> list[str]:
    """Validate the one-shot Controlled Self-Healing gate."""
    if repair_attempt not in (0, 1):
        return ["repair_attempt must be 0 or 1"]

    errors: list[str] = []
    if repair_attempt == 0:
        if previous_report is not None:
            errors.append("repair_report is only valid when repair_attempt=1")
        return errors

    if mode != "benchmark":
        errors.append("repair attempt requires --mode benchmark")
    if not overwrite_allowed:
        errors.append("repair attempt requires --allow-overwrite")
    if previous_report is None:
        errors.append("repair attempt requires a previous failed report")
        return errors

    if previous_report.get("status") != "failed":
        errors.append("previous report is not failed")
    if previous_report.get("failed_step") is None:
        errors.append("previous report has no failed_step")
    if int(previous_report.get("repair_attempt", 0) or 0) != 0:
        errors.append("controlled self-healing already consumed")

    previous_part = previous_report.get("planned_part")
    if not previous_part or not planned_part:
        errors.append("planned part is missing from repair metadata")
    elif _norm_path(str(previous_part)) != _norm_path(str(planned_part)):
        errors.append("repair plan targets a different part")

    return errors


async def run_preflight(transport, plan: dict, mode: str, overwrite_allowed: bool,
                        history: RunHistory, repair_authorized: bool = False
                        ) -> tuple[dict | None, dict | None]:
    """Query the active part and apply the safety policy.

    Returns (blocked_payload, info); exactly one is non-None.
    """
    planned = derive_planned_part(plan, transport)
    part_entry_tool = derive_part_entry_tool(plan)
    planned_exists = bool(
        part_entry_tool == "nx_create_part"
        and planned
        and os.path.exists(planned)
    )
    controlled_overwrite = bool(
        planned_exists
        and repair_authorized
        and mode == "benchmark"
        and overwrite_allowed
    )
    if planned_exists and not controlled_overwrite:
        return {
            "status": "precheck_blocked",
            "reason": "planned_part_exists",
            "planned_part": planned,
            "mode": mode,
            "overwrite_allowed": overwrite_allowed,
        }, None

    resp = await transport.call("nx_status", {})
    active = resp.get("active_part")
    active_path = str(_item_id(active)) if active else ""
    dirty = runtime_dirty(active_path, history) if active_path else False
    decision, payload = preflight_decision(
        active_path, planned or "", mode, overwrite_allowed, dirty, history.paths(),
        repair_authorized=repair_authorized, part_entry_tool=part_entry_tool)
    if decision == "blocked":
        payload["status"] = "precheck_blocked"
        return payload, None
    preserve_active = payload.get("state") == "unrelated_part_preserved_for_create"
    if active_path and not preserve_active:
        # allowed close: planned part (clean / benchmark overwrite) or own test part
        await transport.call("nx_close_part", {"save": False})

    if controlled_overwrite:
        try:
            os.remove(planned)
        except OSError as exc:
            raise PlanError(
                "authorized repair could not remove existing planned part: "
                f"{planned!r}: {exc}"
            ) from exc

    return None, {"planned_part": planned, "active_part": active_path,
                  "part_entry_tool": part_entry_tool,
                  "state": payload.get("state"),
                  "controlled_overwrite": controlled_overwrite}


async def verify_created_work_part(
    transport,
    expected_path: str,
    preserved_displayed_path: str | None = None,
) -> str:
    """Fail closed unless create switched Work Part and preserved the old display."""
    resp = await transport.call("nx_status", {})
    active = resp.get("active_part")
    actual_path = str(_item_id(active)) if active else ""
    if (
        not expected_path
        or not actual_path
        or _norm_path(actual_path) != _norm_path(expected_path)
    ):
        raise PlanError(
            "nx_create_part did not become active work part: "
            f"expected={expected_path!r} actual={actual_path!r}"
        )
    if preserved_displayed_path:
        displayed = [
            _norm_path(str(item))
            for item in (resp.get("displayed_parts") or [])
            if item
        ]
        if _norm_path(preserved_displayed_path) not in displayed:
            raise PlanError(
                "nx_create_part did not preserve pre-existing displayed part: "
                f"expected_preserved={preserved_displayed_path!r} "
                f"displayed_parts={resp.get('displayed_parts')!r}"
            )
    return actual_path


# --------------------------------------------------------------------------
# executor
# --------------------------------------------------------------------------
def _validate_params(tool: str, args: dict) -> None:
    spec = TOOL_PARAMS.get(tool)
    if spec is None:
        raise PlanError(f"tool {tool!r} is not a certified tool")
    required, optional = spec
    for k in required:
        if k not in args:
            raise PlanError(f"{tool}: missing required param {k!r}")
    for k in args:
        if k not in required and k not in optional:
            raise PlanError(f"{tool}: illegal param {k!r} (certified params: {', '.join(required + optional)})")


def _timing_bucket(tool: str, op_index: int, validation_start_idx: int) -> str:
    """Classify operation wall time for report diagnostics.

    Save/export are separated from geometric validation so an asynchronous STEP
    file settle cannot make "final validation" look slow.
    """
    if tool == "nx_save_part":
        return "save"
    if tool == "nx_export_step":
        return "export"
    if op_index >= validation_start_idx and tool in {
        "nx_list_bodies", "nx_list_faces", "nx_list_edges", "nx_list_features",
        "nx_list_sketches", "nx_status", "nx_fit_view",
    }:
        return "validation"
    if op_index < validation_start_idx:
        return "modeling"
    return "other"


async def run_plan(plan: dict, transport: NXTransport, plan_path: str = "",
                   wall_start: float | None = None, history: RunHistory | None = None,
                   mode: str = "normal", planned_part: str | None = None,
                   preserved_displayed_part: str | None = None,
                   timing_state: dict[str, Any] | None = None) -> dict:
    ops = plan.get("operations") or []
    symbols = Symbols()
    topo = TopologyState()
    steps_log: list[dict] = []
    body_count = None
    model_bbox = None
    linear_edge_bbox = None
    prt_path = ""
    step_path = ""
    status = "success"
    failed_step = None
    operations_completed = 0
    total_retries = 0
    selections: dict[str, Any] = {}
    export_settle_elapsed = 0.0
    phase_elapsed = {
        "modeling": 0.0,
        "validation": 0.0,
        "save": 0.0,
        "export": 0.0,
        "other": 0.0,
    }

    # validation phase = first step after the last topology-changing operation
    validation_start_idx = len(ops)
    last_topology_idx: int | None = None
    for i in range(len(ops) - 1, -1, -1):
        if ops[i].get("topology_changes"):
            last_topology_idx = i
            validation_start_idx = i + 1
            break

    first_op_at: float | None = None
    last_op_at: float | None = None
    validation_start_at: float | None = None
    loop_start = time.monotonic()

    for idx, op in enumerate(ops):
        step = op.get("step")
        tool = op.get("tool")
        if idx == validation_start_idx:
            validation_start_at = time.monotonic()
        t0 = time.monotonic()
        if first_op_at is None:
            first_op_at = t0
        started_at = _now_iso()
        retried = 0
        try:
            args = copy.deepcopy(op.get("tool_args") or {})
            args = resolve_value(args, symbols)
            if tool == "nx_sketch_rectangle":
                args = adapt_rectangle(args)
            if tool in ("nx_create_part", "nx_open_part", "nx_export_step"):
                args["path"] = transport.resolve_path(args["path"])
            args = finalize_args(args)
            _validate_params(tool, args)

            # dispatch with plan-declared retries only
            max_retry = int((op.get("retry") or {}).get("max", 0))
            while True:
                try:
                    if tool in RAW_PIPE_TOOLS:
                        resp = _require_raw_loader_success(
                            tool,
                            await transport.call_raw(tool, args),
                        )
                    else:
                        resp = await transport.call(tool, args)
                    break
                except Exception as e:
                    err = str(e)
                    if retried >= max_retry or not _retry_applies(op, err):
                        raise
                    retried += 1
                    total_retries += 1

            if tool == "nx_create_part":
                expected_created_path = str(args.get("path") or planned_part or "")
                await verify_created_work_part(
                    transport,
                    expected_created_path,
                    preserved_displayed_part,
                )

            # selection (list steps with selection_criteria)
            selection = None
            # full-model extents for the report: every list step contributes
            if tool in ("nx_list_edges", "nx_list_faces"):
                _kind = "edges" if tool == "nx_list_edges" else "faces"
                _items = resp.get("edges") or resp.get("faces") or []
                model_bbox = merge_extents(model_bbox, compute_extents(_items, _kind))
                if tool == "nx_list_edges":
                    linear_edge_bbox = merge_extents(linear_edge_bbox,
                                                     compute_extents(_items, "edges"))
            if op.get("selection_criteria") and tool in ("nx_list_edges", "nx_list_faces"):
                kind = "edges" if tool == "nx_list_edges" else "faces"
                sel = run_selection(resp.get("edges") or resp.get("faces") or [],
                                    op["selection_criteria"], kind)
                if op.get("selection_binding"):
                    if sel["group_items"]:
                        bound = {g: [it.get("index") for it in its]
                                 for g, its in sel["group_items"].items()}
                    else:
                        bound = [it.get("index") for it in sel["items"]]
                    symbols.bind_selection(op["selection_binding"], bound)
                    selections[op["selection_binding"]] = bound
                selection = sel
            elif tool == "nx_list_bodies":
                n = len(resp.get("objects") or [])
                body_count = n
                selection = {"count": n, "groups": {}, "group_items": {},
                             "extents": None, "items": []}
            elif tool == "nx_list_edges":
                items = resp.get("edges") or []
                selection = {"count": len(items), "groups": {}, "group_items": {},
                             "extents": compute_extents(items, "edges"), "items": items}
            elif tool == "nx_list_faces":
                items = resp.get("faces") or []
                selection = {"count": len(items), "groups": {}, "group_items": {},
                             "extents": compute_extents(items, "faces"), "items": items}

            # expectation
            if op.get("expectation"):
                sel0 = selection or {"count": 0, "groups": {}, "group_items": {},
                                     "extents": None, "items": []}
                fails = check_expectation(op["expectation"], sel0, resp)
                if fails:
                    raise PlanError(f"{tool}: expectation failed: " + "; ".join(fails))

            # result bindings
            for field, names in (op.get("result_bindings") or {}).items():
                val = resp.get(field)
                if val is None:
                    raise PlanError(f"{tool}: result_bindings field {field!r} missing from response")
                names_list = [names] if isinstance(names, str) else names
                if isinstance(val, list):
                    vals = [_item_id(v) for v in val]
                    if len(vals) != len(names_list):
                        raise PlanError(f"{tool}: result_bindings {field}: got {len(vals)} values for {len(names_list)} names")
                    for n, v in zip(names_list, vals):
                        symbols.bind(n, v)
                else:
                    oid = _item_id(val)
                    for n in names_list:
                        symbols.bind(n, oid)

            # topology invalidation
            topo_note = ""
            if op.get("topology_changes"):
                topo.invalidate()
                topo_note = " [topology changed: edge/face caches invalidated]"

            # generic report bookkeeping
            if tool in ("nx_create_part", "nx_open_part") and resp.get("part"):
                prt_path = str(_item_id(resp["part"]))
            if tool == "nx_save_part" and history is not None:
                history.record_saved(planned_part or prt_path or "")
            if tool == "nx_export_step":
                target = args.get("path") or str(resp.get("path") or "")
                step_path = target
                t_settle = time.monotonic()
                file_ok = False
                for _ in range(120):  # up to 60 s for the async file settle
                    if target and os.path.isfile(target) and os.path.getsize(target) > 0:
                        file_ok = True
                        break
                    await asyncio.sleep(0.5)
                settle = time.monotonic() - t_settle
                export_settle_elapsed += settle
                if not file_ok:
                    raise PlanError(f"STEP export returned but file not present/non-empty: {target}")
                if timing_state is not None:
                    timing_state["c3_export_complete_utc"] = _utc_now_iso_best_effort()

            if idx == last_topology_idx and timing_state is not None:
                timing_state["c2_modeling_complete_utc"] = _utc_now_iso_best_effort()

            dur = time.monotonic() - t0
            bucket = _timing_bucket(tool, idx, validation_start_idx)
            phase_elapsed[bucket] += dur
            operations_completed += 1
            last_op_at = time.monotonic()
            msg = str(resp.get("message") or resp.get("result") or "")
            done = _parse_done(resp)
            if done is not None:
                msg += f" done={done}"
            steps_log.append({
                "step": step, "tool": tool, "started_at": started_at,
                "elapsed_seconds": round(dur, 3), "phase": bucket, "status": "ok",
                "retry_count": retried, "note": (msg + topo_note).strip(),
            })
        except Exception as e:
            dur = time.monotonic() - t0
            bucket = _timing_bucket(tool, idx, validation_start_idx)
            phase_elapsed[bucket] += dur
            last_op_at = time.monotonic()
            steps_log.append({
                "step": step, "tool": tool, "started_at": started_at,
                "elapsed_seconds": round(dur, 3), "phase": bucket, "status": "failed",
                "retry_count": retried, "error": str(e),
            })
            status = "failed"
            failed_step = step
            if history is not None and planned_part:
                history.record_failed(planned_part)
            break

    loop_end = time.monotonic()
    nx_execution = (last_op_at - first_op_at) if (first_op_at and last_op_at) else 0.0
    validation_ops_elapsed = phase_elapsed["validation"]
    export_total_elapsed = phase_elapsed["export"]
    export_call_elapsed = max(0.0, export_total_elapsed - export_settle_elapsed)
    report = {
        "status": status,
        "elapsed_seconds": round(loop_end - loop_start, 3),
        "runner_start_to_first_nx_call": round(first_op_at - wall_start, 3) if wall_start and first_op_at else None,
        "nx_execution_elapsed": round(nx_execution, 3),
        "nx_modeling_elapsed": round(phase_elapsed["modeling"], 3),
        "final_validation_elapsed": round(validation_ops_elapsed, 3),
        "validation_ops_elapsed": round(validation_ops_elapsed, 3),
        "save_elapsed": round(phase_elapsed["save"], 3),
        "export_call_elapsed": round(export_call_elapsed, 3),
        "export_settle_elapsed": round(export_settle_elapsed, 3),
        "step_export_settle_elapsed": round(export_settle_elapsed, 3),
        "other_ops_elapsed": round(phase_elapsed["other"], 3),
        "total_runner_elapsed": round(time.monotonic() - wall_start, 3) if wall_start else None,
        "operations_total": len(ops),
        "operations_completed": operations_completed,
        "failed_step": failed_step,
        "retries": total_retries,
        "body_count": body_count,
        "model_bbox": model_bbox,
        "linear_edge_bbox": linear_edge_bbox,
        "selections": selections,
        "prt_path": prt_path,
        "step_path": step_path,
        "plan": plan_path,
        "planned_part": planned_part,
        "mode": plan.get("mode"),
        "run_mode": mode,
        "modified_nx_mcp_enhanced": False,
        "steps": steps_log,
    }
    return report


def _retry_applies(op: dict, err: str) -> bool:
    retry = op.get("retry") or {}
    subs = retry.get("if_error_contains") or []
    return any(s and s in err for s in subs)


# --------------------------------------------------------------------------
# builder: frozen plan -> executable plan (mechanical, plan-driven)
# --------------------------------------------------------------------------
def _refs_in(args: dict, kind: str) -> list[str]:
    """Logical names referenced by one op's tool_args, in order."""
    out: list[str] = []
    if not isinstance(args, dict):
        return out
    pref = "sketch_" if kind == "sketch" else "body_"
    for k in ("sketch_id", "body_id", "target_body_id"):
        v = args.get(k)
        if isinstance(v, str) and v.startswith(pref):
            out.append(v)
    if kind == "body":
        tl = args.get("tool_body_ids")
        if isinstance(tl, list):
            out.extend(t for t in tl if isinstance(t, str) and t.startswith("body_"))
    return out


def _build_geometry_conservation_errors(
    frozen: dict,
    executable: dict,
) -> list[str]:
    """Prove build changed bindings only, never modeled geometry."""

    errors: list[str] = []
    frozen_ops = frozen.get("operations")
    executable_ops = executable.get("operations")
    if not isinstance(frozen_ops, list) or not isinstance(executable_ops, list):
        return ["build conservation requires operation lists"]
    if len(frozen_ops) != len(executable_ops):
        return [
            "build conservation violation: operation count changed "
            f"{len(frozen_ops)} -> {len(executable_ops)}"
        ]

    generated_root_fields = {"result_bindings", "selection_binding", "retry"}
    logical_scalar_keys = {"sketch_id", "body_id", "target_body_id"}

    def expected_arg_value(key: str, value: Any) -> Any:
        if key in logical_scalar_keys:
            if isinstance(value, str) and (
                value.startswith("sketch_") or value.startswith("body_")
            ):
                return "$" + value
            return value
        if key == "tool_body_ids" and isinstance(value, list):
            return [
                "$" + item
                if isinstance(item, str) and item.startswith("body_")
                else item
                for item in value
            ]
        if isinstance(value, str):
            match = re.match(r"<step(\d+)[^>]*>", value)
            if match:
                return "$selection.sel_" + match.group(1)
        return value

    for index, (before, after) in enumerate(
        zip(frozen_ops, executable_ops, strict=False)
    ):
        if not isinstance(before, dict) or not isinstance(after, dict):
            errors.append(
                f"build conservation violation: operation[{index}] must remain an object"
            )
            continue

        step = before.get("step", index + 1)
        for field in ("step", "tool"):
            if after.get(field) != before.get(field):
                errors.append(
                    "build conservation violation: "
                    f"step {step} changed {field}"
                )

        extra_root = set(after) - set(before) - generated_root_fields
        if extra_root:
            errors.append(
                "build conservation violation: "
                f"step {step} added undeclared operation fields "
                f"{sorted(extra_root)}"
            )

        for field, value in before.items():
            if field == "tool_args":
                continue
            if after.get(field) != value:
                errors.append(
                    "build conservation violation: "
                    f"step {step} changed operation field {field!r}"
                )

        if "retry" not in before and "retry" in after:
            expected_retry = {
                "max": 1,
                "if_error_contains": ["撤消"],
            }
            if before.get("tool") != "nx_save_part" or after.get("retry") != expected_retry:
                errors.append(
                    "build conservation violation: "
                    f"step {step} added an undeclared retry contract"
                )

        before_args = before.get("tool_args") or {}
        after_args = after.get("tool_args") or {}
        if not isinstance(before_args, dict) or not isinstance(after_args, dict):
            errors.append(
                "build conservation violation: "
                f"step {step} tool_args must remain objects"
            )
            continue
        if set(before_args) != set(after_args):
            errors.append(
                "build conservation violation: "
                f"step {step} tool_args key set changed"
            )
            continue

        for key, value in before_args.items():
            expected_value = expected_arg_value(key, value)
            if after_args.get(key) != expected_value:
                errors.append(
                    "build conservation violation: "
                    f"step {step} changed tool_args.{key}"
                )

    return errors


def build_executable_plan(plan: dict) -> dict:
    """Convert a frozen planner plan into the executable form:
    - explicit top-level plan_format marker,
    - explicit result_bindings (producer -> logical name of its first consumer),
    - explicit selection_binding + $selection references,
    - machine-readable retry metadata (declared safe retries only),
    - $ references everywhere logical names are used.
    The modelling rules themselves are untouched.
    """
    out = copy.deepcopy(plan)
    out["plan_format"] = "executable-v1"
    ops = out["operations"]

    sk_live: list[int] = []          # producer op indices with unbound sketch results
    bd_live: list[int] = []          # producer op indices with unbound body results
    sk_bound: dict[str, int] = {}    # sketch name -> producing op index
    bd_bound: dict[str, int] = {}    # body name -> producing op index
    consumed: set[int] = set()       # producer indices consumed as unite tools
    emits: dict[int, dict[str, Any]] = {}  # producer op index -> result_bindings fields

    def emit(op_idx: int, field: str, name: str) -> None:
        cur = emits.setdefault(op_idx, {})
        cur.setdefault(field, [])
        if name not in cur[field]:
            cur[field].append(name)

    def bind_sketch(name: str, op_idx: int) -> None:
        sk_bound[name] = op_idx
        emit(op_idx, "object", name)

    def bind_body(name: str, op_idx: int) -> None:
        bd_bound[name] = op_idx
        tool = ops[op_idx]["tool"]
        if tool in ("nx_circular_pattern", "nx_linear_pattern", "nx_list_bodies"):
            field = "objects"
        elif tool in ("nx_mirror", "nx_unite"):
            field = "object"   # bridge adapted-response field for mirror/unite
        else:
            field = "body"
        emit(op_idx, field, name)

    for i, op in enumerate(ops):
        tool = op["tool"]
        args = op.get("tool_args") or {}

        # 1) resolve referenced sketch names (against previous producers)
        for r in _refs_in(args, "sketch"):
            if r not in sk_bound and sk_live:
                bind_sketch(r, sk_live.pop())

        # 2) resolve referenced body names (against previous producers)
        for r in _refs_in(args, "body"):
            if r in bd_bound:
                continue
            if tool == "nx_unite" and r == args.get("target_body_id"):
                # unite target: oldest live unbound body; alias if none
                if bd_live:
                    bind_body(r, bd_live.pop(0))
                else:
                    live_names = [n for n, p in bd_bound.items() if p not in consumed]
                    if live_names:
                        oldest = min(live_names, key=lambda n: bd_bound[n])
                        bind_body(r, bd_bound[oldest])
                    else:
                        bind_body(r, i)
            else:
                # source / list / feature body: most recent live unbound
                if bd_live:
                    bind_body(r, bd_live.pop())

        # 3) register this op's own producers (results become live for later ops)
        if tool == "nx_create_sketch":
            sk_live.append(i)
        elif tool == "nx_extrude" and args.get("operation", "create") == "create":
            bd_live.append(i)
        elif tool == "nx_mirror":
            bd_live.append(i)
        elif tool in ("nx_circular_pattern", "nx_linear_pattern"):
            try:
                copies = max(0, int(args.get("count", 1)) - 1)
            except (TypeError, ValueError):
                copies = 0
            for _ in range(copies):
                bd_live.append(i)
        elif tool == "nx_list_bodies":
            # Safe existing-part binding: only expose the sole body as a producer
            # when the frozen plan explicitly requires body_count == 1.
            exp = op.get("expectation") or {}
            if exp.get("body_count") == 1:
                bd_live.append(i)

        # 4) unite consumes tool bodies
        if tool == "nx_unite":
            for t in (args.get("tool_body_ids") or []):
                if isinstance(t, str) and t in bd_bound:
                    consumed.add(bd_bound[t])

    # --- apply result_bindings to ops --------------------------------------
    for op_idx, fields in emits.items():
        rb = ops[op_idx].setdefault("result_bindings", {})
        for field, names in fields.items():
            rb[field] = names if len(names) > 1 else names[0]

    # --- selection bindings + $selection references ------------------------
    sel_syms: dict[int, str] = {}
    for op in ops:
        if op.get("selection_criteria") and op["tool"] in ("nx_list_edges", "nx_list_faces"):
            sym = "sel_%s" % op["step"]
            sel_syms[op["step"]] = sym
            op["selection_binding"] = sym
    for op in ops:
        args = op.get("tool_args") or {}
        for k, v in list(args.items()):
            if isinstance(v, str):
                m = re.match(r"<step(\d+)[^>]*>", v)
                if m and int(m.group(1)) in sel_syms:
                    args[k] = "$selection." + sel_syms[int(m.group(1))]

    # --- rewrite logical names to $ references -----------------------------
    for op in ops:
        args = op.get("tool_args") or {}
        for k in ("sketch_id", "body_id", "target_body_id"):
            v = args.get(k)
            if isinstance(v, str) and (v.startswith("sketch_") or v.startswith("body_")):
                args[k] = "$" + v
        tools = args.get("tool_body_ids")
        if isinstance(tools, list):
            args["tool_body_ids"] = [
                "$" + t if isinstance(t, str) and t.startswith("body_") else t
                for t in tools]

    # --- declared safe retries (documented loader transients only) ---------
    for op in ops:
        if op["tool"] == "nx_save_part" and "retry" not in op:
            op["retry"] = {"max": 1, "if_error_contains": ["撤消"]}

    out["notes"] = list(out.get("notes") or [])
    out["notes"].append(
        "executable format: result_bindings / selection_binding / $references added; "
        "natural-language placeholders removed; retries are plan-declared only.")
    return out


# --------------------------------------------------------------------------
# static plan check (no NX)
# --------------------------------------------------------------------------
EDGE_KEYS = {"curve_type", "direction", "length", "midpoint", "midpoint_z",
             "bbox", "bbox_x", "bbox_y", "bbox_z", "corners_xy",
             "adjacent_faces", "linear_only"}
FACE_KEYS = {"face_type", "centroid", "centroid_z", "centroid_radius",
             "normal", "area"}


def _unknown_criteria_keys(criteria: dict, kind: str) -> list[str]:
    known = EDGE_KEYS if kind == "edges" else FACE_KEYS
    unknown: list[str] = []
    if _is_group_criteria(criteria):
        for gname, gcrit in criteria.items():
            if _is_info_key(gname):
                continue
            if not isinstance(gcrit, dict):
                unknown.append(f"{gname}: group criteria must be an object")
                continue
            for k in gcrit:
                if k not in known and not _is_info_key(k) and not k.endswith("_approx"):
                    unknown.append(f"{gname}.{k}")
    else:
        for k in criteria:
            if k not in known and not _is_info_key(k) and not k.endswith("_approx"):
                unknown.append(k)
    return unknown


def _plan_path_is_absolute(path: str) -> bool:
    """Return True for POSIX, drive-letter, or UNC absolute plan paths."""
    return os.path.isabs(path) or bool(PureWindowsPath(path).anchor)


def check_plan(
    plan: dict,
    executable: bool = True,
    *,
    validate_embedded_thread_contract: bool = True,
) -> list[str]:
    errors: list[str] = []
    ops = plan.get("operations") or []
    if not ops:
        errors.append("plan has no operations")
        return errors
    bound_names: set[str] = set()
    bound_selections: dict[str, dict] = {}

    for op in ops:
        step = op.get("step")
        tool = op.get("tool")
        if tool not in CERTIFIED_TOOLS:
            errors.append(f"step {step}: unknown tool {tool!r}")
            continue
        args = op.get("tool_args") or {}
        if not isinstance(args, dict):
            errors.append(f"step {step}: tool_args must be an object")
            continue

        if tool in ("nx_create_part", "nx_open_part", "nx_export_step"):
            path_value = args.get("path")
            if isinstance(path_value, str) and _plan_path_is_absolute(path_value):
                errors.append(
                    f"step {step}: {tool} path must be NX_MCP_WORKSPACE-relative, "
                    f"got {path_value!r}"
                )

        # selection_criteria grammar
        crit = op.get("selection_criteria") or {}
        if isinstance(crit, dict) and crit and tool in ("nx_list_edges", "nx_list_faces"):
            kind = "edges" if tool == "nx_list_edges" else "faces"
            for k in _unknown_criteria_keys(crit, kind):
                errors.append(f"step {step}: unknown {kind} criterion key {k!r}")

        # Frozen plans are Planner output only. Executable-only extensions
        # must be produced by build, never hand-authored by the Planner.
        if not executable:
            if plan.get("plan_format") is not None:
                errors.append("frozen plan must not contain executable top-level field 'plan_format'")
            for key in ("result_bindings", "selection_binding", "retry"):
                if key in op:
                    errors.append(
                        f"step {step}: frozen plan must not contain executable field {key!r}"
                    )
            for v in _walk(args):
                if isinstance(v, str) and v.startswith("$"):
                    errors.append(
                        f"step {step}: frozen plan must not contain executable reference {v!r}"
                    )

        # natural-language placeholders (executable plans only)
        if executable:
            for v in _walk(args):
                if isinstance(v, str):
                    if re.search(r"<[^>]*>", v):
                        errors.append(f"step {step}: natural-language placeholder {v!r}")
                    if "匹配的" in v:
                        errors.append(f"step {step}: natural-language placeholder {v!r}")

        # reference resolution
        for v in _walk(args):
            if not isinstance(v, str) or not v.startswith("$"):
                continue
            path = v[1:].split(".")
            if path[0] == "selection":
                if len(path) < 2 or path[1] not in bound_selections:
                    errors.append(f"step {step}: unresolved {v!r}")
                else:
                    sel = bound_selections[path[1]]
                    if len(path) > 2 and (sel["kind"] != "groups" or path[2] not in sel["groups"]):
                        errors.append(f"step {step}: bad group reference {v!r}")
            else:
                if path[0] not in bound_names:
                    errors.append(f"step {step}: unresolved {v!r}")

        # Selection-consuming params must use the format-specific reference syntax.
        # A bare semantic string such as "base_plate_vertical_edges" cannot be
        # resolved by build/runtime and must fail statically.
        selection_params = {
            "nx_edge_blend": ("edge_indices",),
            "nx_chamfer": ("edge_indices",),
            "nx_shell": ("remove_face_index",),
        }
        for param in selection_params.get(tool, ()):
            if param not in args:
                continue
            value = args[param]
            if isinstance(value, str):
                if executable:
                    if not value.startswith("$selection."):
                        errors.append(
                            f"step {step}: executable {param} string must be a "
                            f"$selection reference, got {value!r}"
                        )
                else:
                    if not re.fullmatch(r"<step\d+[^>]*>", value):
                        errors.append(
                            f"step {step}: frozen {param} string must be a "
                            f"<stepN ...> selection placeholder, got {value!r}"
                        )

        # param validation (after adaptation)
        a = dict(args)
        if tool == "nx_sketch_rectangle":
            a = adapt_rectangle(a)
        required, optional = TOOL_PARAMS.get(tool, ((), ()))
        for k in required:
            if k not in a:
                errors.append(f"step {step}: {tool} missing required param {k!r}")
        for k in a:
            if k not in required and k not in optional:
                errors.append(f"step {step}: {tool} illegal param {k!r}")

        # apply declared bindings
        for field, names in (op.get("result_bindings") or {}).items():
            names_list = [names] if isinstance(names, str) else names
            for n in names_list:
                bound_names.add(n)
        if op.get("selection_binding"):
            crit2 = op.get("selection_criteria") or {}
            kind2 = "groups" if _is_group_criteria(crit2) else "indices"
            groups = [k for k in crit2 if not _is_info_key(k)] if kind2 == "groups" else []
            bound_selections[op["selection_binding"]] = {"kind": kind2, "groups": groups}

    if (
        validate_embedded_thread_contract
        and (
            plan.get("thread_surrogates") is not None
            or plan.get("thread_drawing_geometries") is not None
        )
    ):
        errors.extend(
            thread_surrogate_plan_errors(
                plan,
                plan.get("thread_surrogates") or [],
                plan.get("thread_drawing_geometries") or [],
            )
        )
    return errors


# --------------------------------------------------------------------------
# Drawing schema normalization — representation only, no inferred geometry
# --------------------------------------------------------------------------
_DRAWING_NUMERIC_KEYS = {
    "length", "length_x", "width", "width_y", "height", "height_z",
    "thickness", "diameter", "hole_diameter", "counterbore_diameter",
    "countersink_diameter", "radius", "depth", "hole_depth",
    "counterbore_depth", "count", "count_x", "count_y", "spacing",
    "spacing_x", "spacing_y", "pitch", "pcd", "start_angle_deg",
    "top_z", "bottom_z", "start_z", "end_z", "start_offset",
    "distance", "angle", "angle_deg", "x", "y", "z", "x1", "y1",
    "z1", "x2", "y2", "z2", "value",
}
_DRAWING_OBJECT_LIST_KEYS = {
    "features", "source_ledger", "derived", "relations", "patterns",
    "unresolved", "dimension_conflicts",
}


def _drawing_canonical_number(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return value
    number = float(text)
    return int(number) if number.is_integer() else number


def _drawing_named_dimensions(value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, list):
        return value, None
    if not value:
        return {}, None
    out: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            return value, "dimensions list must contain named value objects"
        name = item.get("name", item.get("key"))
        if (
            not isinstance(name, str)
            or not name
            or "value" not in item
            or name in out
            or set(item) - {"name", "key", "value"}
        ):
            return value, "dimensions list shape is ambiguous"
        out[name] = item["value"]
    return out, None


def _drawing_object_list(value: Any, key: str) -> tuple[Any, str | None]:
    if isinstance(value, list):
        return copy.deepcopy(value), None
    if not isinstance(value, dict):
        return value, f"{key} must be a list or an object of objects"
    out = []
    for item_id, child in value.items():
        if not isinstance(child, dict):
            return value, f"{key} object shape is ambiguous"
        item = copy.deepcopy(child)
        if key in {"features", "source_ledger", "derived", "relations"}:
            if "id" in item and str(item["id"]) != str(item_id):
                return value, f"{key} key/id conflict for {item_id!r}"
            item.setdefault("id", str(item_id))
        out.append(item)
    return out, None


def _normalize_drawing_feature(feature: dict, changes: list[str]) -> tuple[dict, list[str]]:
    item = copy.deepcopy(feature)
    errors: list[str] = []
    if "dimension" in item:
        if "dimensions" in item and item["dimensions"] != item["dimension"]:
            errors.append("feature has conflicting dimension and dimensions")
        elif "dimensions" not in item:
            item["dimensions"] = item["dimension"]
            changes.append("normalized feature dimension -> dimensions")
        item.pop("dimension", None)

    if "dimensions" in item:
        normalized, error = _drawing_named_dimensions(item["dimensions"])
        if error:
            errors.append(error)
        elif normalized != item["dimensions"]:
            item["dimensions"] = normalized
            changes.append("normalized feature dimensions list -> object")

    if "center" in item:
        position = item.get("position")
        if isinstance(position, dict) and "center" in position:
            if position["center"] != item["center"]:
                errors.append("feature has conflicting center and position.center")
        else:
            if position is not None and not isinstance(position, dict):
                errors.append("feature position shape is ambiguous")
            else:
                position = dict(position or {})
                position["center"] = item["center"]
                item["position"] = position
                changes.append("normalized feature center -> position.center")
        item.pop("center", None)

    members = item.get("members")
    if isinstance(members, list):
        normalized_members = []
        for member in members:
            if not isinstance(member, dict):
                errors.append("feature members must contain objects")
                normalized_members.append(member)
                continue
            normalized, member_errors = _normalize_drawing_feature(member, changes)
            normalized_members.append(normalized)
            errors.extend(member_errors)
        item["members"] = normalized_members
    return item, errors


_DRAWING_PATH_SCALAR_KEYS = {"target", "center", "diameter", "tangent"}
_DRAWING_PATH_LIST_KEYS = {"targets", "between", "links", "refs"}


def _drawing_feature_id_set(data: dict) -> tuple[set[str], list[str]]:
    ids: set[str] = set()
    errors: list[str] = []
    for feature in data.get("features") or []:
        if not isinstance(feature, dict):
            continue
        feature_id = feature.get("id")
        if not isinstance(feature_id, str) or not feature_id:
            continue
        if feature_id in ids:
            errors.append(f"duplicate feature id {feature_id!r} prevents canonical path rewrite")
        ids.add(feature_id)
    return ids, errors


def _drawing_add_path_mapping(
    mapping: dict[str, str], old: str, new: str, errors: list[str]
) -> None:
    prior = mapping.get(old)
    if prior is not None and prior != new:
        errors.append(f"ambiguous drawing path alias {old!r}: {prior!r} vs {new!r}")
        return
    for other_old, other_new in mapping.items():
        if other_old != old and other_new == new:
            errors.append(
                f"multiple drawing path aliases target the same destination {new!r}"
            )
            return
    mapping[old] = new


def _drawing_canonicalize_range_z(
    item: dict,
    prefix: str,
    mapping: dict[str, str],
    errors: list[str],
    changes: list[str],
) -> None:
    if "range_z" in item:
        value = item["range_z"]
        if not isinstance(value, dict) or set(value) != {"from", "to"}:
            errors.append(
                f"unknown or ambiguous range_z alias at {prefix!r}; expected exactly from/to"
            )
        elif "bottom_z" in item or "top_z" in item:
            errors.append(
                f"conflicting range_z and bottom_z/top_z representations at {prefix!r}"
            )
        else:
            bottom = value["from"]
            top = value["to"]
            _drawing_add_path_mapping(
                mapping, f"{prefix}.range_z.from", f"{prefix}.bottom_z", errors
            )
            _drawing_add_path_mapping(
                mapping, f"{prefix}.range_z.to", f"{prefix}.top_z", errors
            )
            if not errors:
                item.pop("range_z")
                item["bottom_z"] = bottom
                item["top_z"] = top
                changes.append(f"normalized {prefix}.range_z.from/to -> bottom_z/top_z")

    members = item.get("members")
    if isinstance(members, list):
        for index, member in enumerate(members):
            if isinstance(member, dict):
                _drawing_canonicalize_range_z(
                    member,
                    f"{prefix}.members.{index}",
                    mapping,
                    errors,
                    changes,
                )


def _drawing_iter_path_references(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _DRAWING_PATH_SCALAR_KEYS and isinstance(child, str):
                yield child
            elif key in _DRAWING_PATH_LIST_KEYS and isinstance(child, list):
                for item in child:
                    if isinstance(item, str):
                        yield item
            yield from _drawing_iter_path_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _drawing_iter_path_references(child)


def _drawing_rewrite_path_references(value: Any, mapping: dict[str, str]) -> Any:
    def rewrite(path: str) -> str:
        seen: set[str] = set()
        while path in mapping:
            if path in seen:
                break
            seen.add(path)
            path = mapping[path]
        return path

    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if key in _DRAWING_PATH_SCALAR_KEYS and isinstance(child, str):
                out[key] = rewrite(child)
            elif key in _DRAWING_PATH_LIST_KEYS and isinstance(child, list):
                out[key] = [rewrite(item) if isinstance(item, str) else copy.deepcopy(item)
                            for item in child]
            else:
                out[key] = _drawing_rewrite_path_references(child, mapping)
        return out
    if isinstance(value, list):
        return [_drawing_rewrite_path_references(child, mapping) for child in value]
    return copy.deepcopy(value)


def _drawing_canonicalize_paths(
    data: dict, changes: list[str]
) -> tuple[dict, list[str]]:
    """Apply only proven one-to-one drawing field/path aliases."""
    out = copy.deepcopy(data)
    errors: list[str] = []
    feature_ids, id_errors = _drawing_feature_id_set(out)
    errors.extend(id_errors)
    mapping: dict[str, str] = {}

    for feature in out.get("features") or []:
        if not isinstance(feature, dict):
            continue
        feature_id = feature.get("id")
        if isinstance(feature_id, str) and feature_id:
            _drawing_canonicalize_range_z(
                feature, f"feature:{feature_id}", mapping, errors, changes
            )

    if errors:
        return data, errors

    for path in list(_drawing_iter_path_references(out)):
        if path in mapping:
            continue
        if path.startswith("feature:"):
            if ".range_z." in path:
                errors.append(f"unknown drawing path alias {path!r}")
            continue
        head, dot, tail = path.partition(".")
        if dot and head in feature_ids:
            candidate = f"feature:{head}.{tail}"
            if candidate in mapping:
                _drawing_add_path_mapping(mapping, path, candidate, errors)
            else:
                try:
                    _drawing_path_get(out, candidate)
                except KeyError:
                    errors.append(
                        f"drawing path alias {path!r} cannot resolve canonical target {candidate!r}"
                    )
                else:
                    _drawing_add_path_mapping(mapping, path, candidate, errors)
        elif ".range_z." in path:
            errors.append(f"unknown drawing path alias {path!r}")

    if errors:
        return data, errors

    rewritten = _drawing_rewrite_path_references(out, mapping)
    for old, new in mapping.items():
        seen: set[str] = set()
        while new in mapping:
            if new in seen:
                errors.append(f"cyclic drawing path alias involving {new!r}")
                break
            seen.add(new)
            new = mapping[new]
        try:
            new_value = _drawing_path_get(rewritten, new)
        except KeyError:
            errors.append(f"canonical drawing target {new!r} does not exist")
            continue
        if old.startswith("feature:") and ".range_z." in old:
            feature_id, _, tail = old[len("feature:"):].partition(".")
            original_feature = next(
                (item for item in data.get("features", [])
                 if isinstance(item, dict) and item.get("id") == feature_id),
                None,
            )
            if original_feature is None:
                errors.append(f"canonicalization lost feature identity {feature_id!r}")
                continue
            cur: Any = original_feature
            try:
                for part in tail.split("."):
                    if isinstance(cur, dict):
                        cur = cur[part]
                    elif isinstance(cur, list) and part.isdigit():
                        cur = cur[int(part)]
                    else:
                        raise KeyError(old)
            except (KeyError, IndexError):
                errors.append(f"original drawing target {old!r} does not exist")
                continue
            if cur != new_value:
                errors.append(f"canonical path rewrite changes leaf value for {old!r}")

    if errors:
        return data, errors
    for old, new in mapping.items():
        if old != new:
            changes.append(f"rewrote drawing path {old} -> {new}")
    return rewritten, []


def _drawing_normalize_numbers(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _drawing_normalize_numbers(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_drawing_normalize_numbers(item, key) for item in value]
    return _drawing_canonical_number(value) if key in _DRAWING_NUMERIC_KEYS else value


def drawing_semantic_projection(data: dict) -> dict:
    """Canonical in-memory view proving representation-only equivalence."""
    projection = copy.deepcopy(data)
    for key in _DRAWING_OBJECT_LIST_KEYS:
        if key in projection:
            normalized, error = _drawing_object_list(projection[key], key)
            if error is None:
                projection[key] = normalized
    if isinstance(projection.get("features"), list):
        canonical_features = []
        for feature in projection["features"]:
            if isinstance(feature, dict):
                normalized, _ = _normalize_drawing_feature(feature, [])
                canonical_features.append(normalized)
            else:
                canonical_features.append(feature)
        projection["features"] = canonical_features
    projection = _drawing_normalize_numbers(projection)
    projected_changes: list[str] = []
    projected, errors = _drawing_canonicalize_paths(projection, projected_changes)
    return projection if errors else _drawing_normalize_numbers(projected)


def drawing_preservation_inventory(data: dict) -> dict:
    """Stable inventories that canonicalization is never allowed to change."""
    projection = drawing_semantic_projection(data)
    source_ledger = projection.get("source_ledger") or []
    relations = projection.get("relations") or []
    return {
        "feature_ids": [item.get("id") for item in projection.get("features") or []
                        if isinstance(item, dict)],
        "source_ids": [item.get("id") for item in source_ledger
                       if isinstance(item, dict)],
        "relation_ids": [item.get("id") for item in relations
                         if isinstance(item, dict)],
        "ledger_relation_ids": [item.get("id") for item in source_ledger
                                if isinstance(item, dict)
                                and item.get("semantic") in _DRAWING_RELATION_SEMANTICS],
        "derived_ids": [item.get("id") for item in projection.get("derived") or []
                        if isinstance(item, dict)],
        "unresolved_ids": [item.get("id") for item in projection.get("unresolved") or []
                           if isinstance(item, dict)],
        "source_count": len(source_ledger),
        "relation_count": len(relations),
    }


def normalize_drawing_schema(data: dict) -> tuple[dict, list[str], list[str]]:
    """Normalize equivalent shapes only; never invent geometry or evidence."""
    if not isinstance(data, dict):
        return data, ["drawing JSON root must be an object"], []
    before = drawing_semantic_projection(data)
    before_inventory = drawing_preservation_inventory(data)
    out = copy.deepcopy(data)
    errors: list[str] = []
    changes: list[str] = []

    for key in _DRAWING_OBJECT_LIST_KEYS:
        if key not in out:
            continue
        normalized, error = _drawing_object_list(out[key], key)
        if error:
            errors.append(error)
        elif normalized != out[key]:
            out[key] = normalized
            changes.append(f"normalized {key} object/list shape")

    if isinstance(out.get("features"), list):
        normalized_features = []
        for feature in out["features"]:
            if not isinstance(feature, dict):
                errors.append("features must contain objects")
                normalized_features.append(feature)
                continue
            normalized, feature_errors = _normalize_drawing_feature(feature, changes)
            normalized_features.append(normalized)
            errors.extend(feature_errors)
        out["features"] = normalized_features

    number_normalized = _drawing_normalize_numbers(out)
    if number_normalized != out:
        out = number_normalized
        changes.append("normalized unambiguous numeric strings")

    out, path_errors = _drawing_canonicalize_paths(out, changes)
    errors.extend(path_errors)
    post_path_numbers = _drawing_normalize_numbers(out)
    if post_path_numbers != out:
        out = post_path_numbers
        changes.append("normalized numeric strings exposed by canonical path rewrite")

    if errors:
        return copy.deepcopy(data), errors, []
    if drawing_preservation_inventory(out) != before_inventory:
        return copy.deepcopy(data), ["normalizer identity/count preservation check failed"], []
    if drawing_semantic_projection(out) != before:
        return copy.deepcopy(data), ["normalizer semantic preservation check failed"], []
    return out, [], changes


# --------------------------------------------------------------------------
# Lightweight metric thread surrogate semantics — no design lineage/hashes
# --------------------------------------------------------------------------
_THREAD_INHERITED_GEOMETRY_KEYS = (
    "axis", "center", "position", "centerline", "explicit_centers", "count",
    "side", "owner_feature_id", "axis_range", "axial_range", "range",
    "through_range", "start_offset", "end_offset",
)

# Project-supported coarse-pitch metadata subset. Explicit pitch in the drawing
# always wins; unsupported bare designations fail closed.
_PROJECT_METRIC_COARSE_PITCH_MM = {
    3.0: 0.50,
    4.0: 0.70,
    5.0: 0.80,
    6.0: 1.00,
    8.0: 1.25,
    10.0: 1.50,
    12.0: 1.75,
    16.0: 2.00,
    20.0: 2.50,
}


def _thread_feature_records(drawing: dict) -> list[dict]:
    records: list[dict] = []

    def visit(value: Any, path: str, inherited: dict, owner_id: str | None) -> None:
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}.{index}", inherited, owner_id)
            return
        if not isinstance(value, dict):
            return
        current = copy.deepcopy(inherited)
        for key in _THREAD_INHERITED_GEOMETRY_KEYS:
            if key in value:
                current[key] = copy.deepcopy(value[key])
        current_owner = str(value.get("id")) if value.get("id") else owner_id
        dimensions = value.get("dimensions")
        dimensions = dimensions if isinstance(dimensions, dict) else {}
        type_text = str(value.get("type") or value.get("kind") or "").lower()
        has_spec = any(key in value or key in dimensions for key in ("thread_spec", "thread_size", "spec"))
        if has_spec or any(token in type_text for token in ("thread", "tapped", "螺纹")):
            feature = copy.deepcopy(value)
            for key, inherited_value in current.items():
                feature.setdefault(key, copy.deepcopy(inherited_value))
            records.append({
                "feature": feature,
                "path": path,
                "owner_feature_id": owner_id or current_owner,
            })
        members = value.get("members")
        if isinstance(members, list):
            visit(members, f"{path}.members", current, current_owner)

    visit(drawing.get("features") or [], "features", {}, None)
    return records


def _thread_feature_value(feature: dict, *keys: str) -> Any:
    dimensions = feature.get("dimensions")
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    for key in keys:
        if key in feature:
            return feature[key]
        if key in dimensions:
            return dimensions[key]
    return None


def _axis_transverse_center(axis: str, center: Any) -> list[float] | None:
    axis = axis.upper()
    if axis not in {"X", "Y", "Z"}:
        return None
    if isinstance(center, (list, tuple)):
        values = [_num(value) for value in center]
        if len(values) == 2 and all(value is not None for value in values):
            return [float(values[0]), float(values[1])]
        if len(values) == 3 and all(value is not None for value in values):
            indexes = {"X": (1, 2), "Y": (0, 2), "Z": (0, 1)}[axis]
            return [float(values[indexes[0]]), float(values[indexes[1]])]
    if isinstance(center, dict):
        keys = {"X": ("y", "z"), "Y": ("x", "z"), "Z": ("x", "y")}[axis]
        values = [_num(center.get(key)) for key in keys]
        if all(value is not None for value in values):
            return [float(values[0]), float(values[1])]
    return None


def _thread_spec(feature: dict) -> str | None:
    value = _thread_feature_value(feature, "thread_spec", "thread_size", "spec")
    return str(value).strip() if value is not None and str(value).strip() else None


def _metric_number_text(value: float) -> str:
    return f"{value:.12g}"


def resolve_metric_thread_parameters(spec: str | None) -> tuple[dict | None, str | None]:
    """Resolve metric designation to nominal, pitch and nominal-minus-pitch drill."""
    if not isinstance(spec, str):
        return None, "thread designation is missing"
    compact = re.sub(r"\s+", "", spec.upper().replace("×", "X"))
    match = re.fullmatch(r"M(\d+(?:\.\d+)?)(?:X(\d+(?:\.\d+)?))?", compact)
    if not match:
        return None, f"unsupported metric thread designation {spec!r}"
    nominal = float(match.group(1))
    if nominal <= 0:
        return None, f"invalid nominal diameter in thread designation {spec!r}"
    if match.group(2) is not None:
        pitch = float(match.group(2))
        pitch_source = "drawing_explicit"
    else:
        pitch = _PROJECT_METRIC_COARSE_PITCH_MM.get(nominal)
        pitch_source = "project_coarse_metadata"
        if pitch is None:
            return None, f"no supported coarse-pitch metadata for M{nominal:g}"
    if pitch <= 0 or pitch >= nominal:
        return None, f"invalid pitch in thread designation {spec!r}"
    canonical = f"M{_metric_number_text(nominal)}"
    if match.group(2) is not None:
        canonical += f"x{_metric_number_text(pitch)}"
    return {
        "thread_spec": canonical,
        "nominal_diameter": nominal,
        "pitch": pitch,
        "pitch_source": pitch_source,
        "representation": "tap_drill",
        "surrogate_method": "nominal_minus_pitch",
        "surrogate_diameter": round(nominal - pitch, 12),
        "approximation": True,
        "reason": "real thread form is unavailable in the current toolset",
    }, None


def _thread_subsuming_through_feature(
    drawing: dict,
    thread_feature: dict,
    surrogate_diameter: float,
) -> dict | None:
    """Return one unique coaxial through feature that fully covers the surrogate void.

    This is geometry-only subsumption: the threaded drawing semantics remain intact,
    but no redundant subtract operation is required when a larger/equal coaxial
    through void already exists. Ambiguous or incomplete matches fail closed.
    """

    axis = str(_thread_feature_value(thread_feature, "axis") or "").upper()
    if axis not in {"X", "Y", "Z"}:
        return None

    thread_center_value = _thread_feature_value(
        thread_feature, "center", "centerline"
    )
    position = thread_feature.get("position")
    if thread_center_value is None and isinstance(position, dict):
        thread_center_value = position.get("center")
    thread_center = _axis_transverse_center(axis, thread_center_value)
    if thread_center is None:
        return None

    thread_range_value = _thread_feature_value(
        thread_feature, "axis_range", "axial_range", "through_range", "range"
    )
    if not (
        isinstance(thread_range_value, (list, tuple))
        and len(thread_range_value) == 2
        and all(_num(value) is not None for value in thread_range_value)
    ):
        return None
    thread_range = sorted(
        [float(_num(thread_range_value[0])), float(_num(thread_range_value[1]))]
    )

    matches: list[dict] = []
    for feature in drawing.get("features") or []:
        if not isinstance(feature, dict) or feature is thread_feature:
            continue
        if feature.get("id") == thread_feature.get("id"):
            continue
        feature_type = str(feature.get("type") or feature.get("kind") or "").lower()
        if any(token in feature_type for token in ("thread", "tapped", "螺纹")):
            continue
        if feature.get("through") is not True:
            continue
        if str(feature.get("axis") or "").upper() != axis:
            continue
        count = _num(feature.get("count"))
        if count is not None and (not float(count).is_integer() or int(count) != 1):
            continue

        diameter = _num(
            feature.get("diameter")
            if feature.get("diameter") is not None
            else feature.get("hole_diameter")
        )
        if diameter is None or diameter + 1e-9 < surrogate_diameter:
            continue

        center_value = feature.get("centerline")
        candidate_position = feature.get("position")
        if center_value is None and isinstance(candidate_position, dict):
            center_value = candidate_position.get("center")
        center = _axis_transverse_center(axis, center_value)
        if center is None:
            continue
        if len(center) != len(thread_center) or any(
            not _drawing_equal(a, b) for a, b in zip(center, thread_center)
        ):
            continue

        candidate_range_value = _thread_feature_value(
            feature, "axis_range", "axial_range", "through_range", "range"
        )
        if not (
            isinstance(candidate_range_value, (list, tuple))
            and len(candidate_range_value) == 2
            and all(_num(value) is not None for value in candidate_range_value)
        ):
            continue
        candidate_range = sorted(
            [float(_num(candidate_range_value[0])), float(_num(candidate_range_value[1]))]
        )
        if (
            candidate_range[0] > thread_range[0] + 1e-9
            or candidate_range[1] < thread_range[1] - 1e-9
        ):
            continue

        matches.append(feature)

    return matches[0] if len(matches) == 1 else None


def resolve_thread_drawing_geometries(
    drawing: dict,
    *,
    axes: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Resolve thread surrogate geometry from explicit drawing facts only.

    An absent axial range may be derived only when the drawing explicitly provides
    start_side/side, a positive thread depth, and overall dimensions. This uses the
    canonical engineering coordinate system; pixel geometry is never consulted.
    """
    geometries: list[dict] = []
    errors: list[str] = []
    for index, record in enumerate(_thread_feature_records(drawing)):
        feature = record["feature"]
        if feature.get("required_for_modeling") is False:
            continue
        fid = str(feature.get("id") or f"thread[{index}]")
        feature_axis = str(_thread_feature_value(feature, "axis") or "").upper()
        if axes is not None and feature_axis not in axes:
            continue
        parameters, parameter_error = resolve_metric_thread_parameters(_thread_spec(feature))
        if parameter_error is None and parameters is not None:
            covering = _thread_subsuming_through_feature(
                drawing,
                feature,
                float(parameters["surrogate_diameter"]),
            )
            if covering is not None:
                center_value = _thread_feature_value(feature, "center", "centerline")
                position = feature.get("position")
                if center_value is None and isinstance(position, dict):
                    center_value = position.get("center")
                axis_value = str(_thread_feature_value(feature, "axis") or "").upper()
                geometries.append(
                    {
                        "feature_id": fid,
                        "owner_feature_id": record.get("owner_feature_id") or fid,
                        "representation": "subsumed_by_coaxial_through_hole",
                        "subsumed_by_feature_id": str(covering.get("id") or ""),
                        "axis": axis_value,
                        "transverse_centers": [
                            _axis_transverse_center(axis_value, center_value)
                        ],
                        "count": 0,
                    }
                )
                continue
        axis = feature_axis
        if axis not in {"X", "Y", "Z"}:
            errors.append(f"thread_geometry_violation: feature {fid!r} has no valid axis")
            continue
        centers_value = _thread_feature_value(feature, "explicit_centers")
        if not isinstance(centers_value, list) or not centers_value:
            position = feature.get("position")
            center = position.get("center") if isinstance(position, dict) else None
            center = center if center is not None else _thread_feature_value(feature, "center", "centerline")
            centers_value = [center] if center is not None else []
        centers = [_axis_transverse_center(axis, center) for center in centers_value]
        if not centers or any(center is None for center in centers):
            errors.append(f"thread_geometry_violation: feature {fid!r} has no valid center")
            continue
        depth = _num(
            _thread_feature_value(feature, "depth", "hole_depth", "thread_depth")
        )
        if depth is None or depth <= 0:
            errors.append(f"thread_geometry_violation: feature {fid!r} has no valid depth")
            continue

        axial_range = _thread_feature_value(
            feature, "axis_range", "axial_range", "through_range", "range"
        )
        if (
            isinstance(axial_range, (list, tuple))
            and len(axial_range) == 2
            and all(_num(value) is not None for value in axial_range)
        ):
            axial_range = [
                float(_num(axial_range[0])),
                float(_num(axial_range[1])),
            ]
        else:
            legacy_side_value = _thread_feature_value(feature, "start_side", "side")
            legacy_side = str(legacy_side_value or "").lower()
            material_side_value = _thread_feature_value(feature, "material_side")
            entry_endpoint_value = _thread_feature_value(feature, "entry_endpoint")
            material_side = str(material_side_value or "").lower()
            entry_endpoint = str(entry_endpoint_value or "").lower()

            split_present = (
                material_side_value is not None or entry_endpoint_value is not None
            )
            if split_present:
                if legacy_side in {"min", "max"}:
                    errors.append(
                        f"thread_geometry_violation: feature {fid!r} mixes legacy "
                        "start_side with material_side/entry_endpoint"
                    )
                    continue
                if (
                    material_side not in {"min", "max"}
                    or entry_endpoint not in {"min", "max"}
                ):
                    errors.append(
                        f"thread_geometry_violation: feature {fid!r} requires both "
                        "material_side and entry_endpoint as min|max"
                    )
                    continue
            else:
                if legacy_side not in {"min", "max"}:
                    errors.append(
                        f"thread_geometry_violation: feature {fid!r} has no explicit "
                        "axial range and no complete machining-entry semantics"
                    )
                    continue
                material_side = legacy_side
                entry_endpoint = legacy_side

            derived_ranges: list[list[float]] = []
            material_failed = False
            for center in centers:
                material, material_errors = resolve_axis_material_intervals(
                    drawing,
                    axis,
                    center,
                    exclude_feature_ids={fid},
                )
                if material_errors:
                    errors.extend(
                        f"thread_geometry_violation: feature {fid!r}: {item}"
                        for item in material_errors
                    )
                    material_failed = True
                    break
                normalized_material = _merge_intervals(material)
                if material_side != entry_endpoint and len(normalized_material) < 2:
                    errors.append(
                        f"thread_geometry_violation: feature {fid!r} uses split "
                        "material/entry semantics but canonical material is not interrupted"
                    )
                    material_failed = True
                    break
                selected = _select_material_interval(material, material_side)
                if selected is None:
                    errors.append(
                        f"thread_geometry_violation: feature {fid!r} has no "
                        f"material interval on material_side={material_side}"
                    )
                    material_failed = True
                    break
                value = _depth_range_from_material_interval(
                    selected,
                    entry_endpoint,
                    float(depth),
                )
                if value is None:
                    errors.append(
                        f"thread_geometry_violation: feature {fid!r} depth exceeds "
                        "the selected material interval from entry_endpoint="
                        f"{entry_endpoint}"
                    )
                    material_failed = True
                    break
                derived_ranges.append(value)
            if material_failed:
                continue
            if not derived_ranges or any(
                len(value) != 2
                or any(
                    not _drawing_equal(left, right)
                    for left, right in zip(
                        value,
                        derived_ranges[0],
                        strict=False,
                    )
                )
                for value in derived_ranges[1:]
            ):
                errors.append(
                    f"thread_geometry_violation: feature {fid!r} centers do not "
                    "share one deterministic axial range"
                )
                continue
            axial_range = derived_ranges[0]

        if not _drawing_equal(abs(axial_range[1] - axial_range[0]), depth):
            errors.append(f"thread_geometry_violation: feature {fid!r} depth and axial range disagree")
            continue

        count_value = _num(_thread_feature_value(feature, "count"))
        if count_value is None:
            count = len(centers)
        else:
            if count_value <= 0 or not float(count_value).is_integer():
                errors.append(f"thread_geometry_violation: feature {fid!r} has no valid count")
                continue
            count = int(count_value)
        if len(centers) != count:
            errors.append(f"thread_geometry_violation: feature {fid!r} center count does not equal count")
            continue
        geometry = {
            "feature_id": fid,
            "owner_feature_id": record.get("owner_feature_id") or fid,
            "axis": axis,
            "transverse_centers": centers,
            "depth": float(depth),
            "axial_range": axial_range,
            "count": count,
        }
        side_value = _thread_feature_value(feature, "start_side", "side")
        side = str(side_value or "").lower()
        material_side_value = _thread_feature_value(feature, "material_side")
        entry_endpoint_value = _thread_feature_value(feature, "entry_endpoint")
        material_side = str(material_side_value or "").lower()
        entry_endpoint = str(entry_endpoint_value or "").lower()
        if side in {"min", "max"}:
            geometry["side"] = side
            geometry["material_side"] = side
            geometry["entry_endpoint"] = side
        elif (
            material_side in {"min", "max"}
            and entry_endpoint in {"min", "max"}
        ):
            geometry["material_side"] = material_side
            geometry["entry_endpoint"] = entry_endpoint
        geometries.append(geometry)
    return geometries, errors


def resolve_thread_surrogates(
    drawing: dict,
    *,
    axes: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    resolved: list[dict] = []
    errors: list[str] = []
    for index, record in enumerate(_thread_feature_records(drawing)):
        feature = record["feature"]
        if feature.get("required_for_modeling") is False:
            continue
        fid = str(feature.get("id") or f"thread[{index}]")
        feature_axis = str(_thread_feature_value(feature, "axis") or "").upper()
        if axes is not None and feature_axis not in axes:
            continue
        parameters, error = resolve_metric_thread_parameters(_thread_spec(feature))
        if error or parameters is None:
            errors.append(f"capability_violation: threaded feature {fid!r}: {error}")
            continue
        resolved.append({"feature_id": fid, **parameters})
    return resolved, errors


def _thread_operation_geometry(plan: dict, op: dict, expected_diameter: float) -> tuple[dict | None, list[str]]:
    step = op.get("step")
    tool = op.get("tool")
    args = op.get("tool_args") or {}
    if tool == "nx_hole":
        if any(key not in args for key in ("center", "diameter", "depth", "start_offset")):
            return None, [f"step {step}: thread hole geometry must be explicit"]
        center = _axis_transverse_center("Z", args.get("center"))
        depth, start, diameter = _num(args.get("depth")), _num(args.get("start_offset")), _num(args.get("diameter"))
        if center is None or depth is None or depth <= 0 or start is None:
            return None, [f"step {step}: invalid thread hole geometry"]
        errors = [] if _drawing_equal(diameter, expected_diameter) else [f"step {step}: thread surrogate diameter differs from resolver"]
        return {"axis": "Z", "transverse_center": center, "depth": float(depth), "axial_range": [float(start), float(start + depth)]}, errors
    if tool != "nx_extrude" or args.get("operation") != "subtract":
        return None, [f"step {step}: thread surrogate must use nx_hole or subtract nx_extrude"]
    if any(key not in args for key in ("sketch_id", "distance", "start_offset", "reverse")):
        return None, [f"step {step}: thread subtract geometry must be explicit"]
    operations = plan.get("operations") or []
    op_index = operations.index(op)
    sketch_id = args.get("sketch_id")
    circles = [candidate for candidate in operations[:op_index] if candidate.get("tool") == "nx_sketch_circle" and (candidate.get("tool_args") or {}).get("sketch_id") == sketch_id]
    if len(circles) != 1:
        return None, [f"step {step}: thread subtract needs exactly one sketch circle"]
    circle = circles[0]
    circle_index = operations.index(circle)
    creates = [candidate for candidate in operations[:circle_index] if candidate.get("tool") == "nx_create_sketch"]
    if not creates:
        return None, [f"step {step}: thread sketch has no create operation"]
    axis = {"XY": "Z", "XZ": "Y", "YZ": "X"}.get(str((creates[-1].get("tool_args") or {}).get("plane") or "").upper())
    center = _axis_transverse_center("Z", (circle.get("tool_args") or {}).get("center")) if axis else None
    depth, start = _num(args.get("distance")), _num(args.get("start_offset"))
    diameter = _num((circle.get("tool_args") or {}).get("diameter"))
    if axis is None or center is None or depth is None or depth <= 0 or start is None or not isinstance(args.get("reverse"), bool):
        return None, [f"step {step}: invalid thread subtract geometry"]
    direction = -1.0 if args["reverse"] else 1.0
    errors = [] if _drawing_equal(diameter, expected_diameter) else [f"step {step}: thread surrogate diameter differs from resolver"]
    return {
        "axis": axis,
        "transverse_center": center,
        "depth": float(depth),
        "axial_range": [
            float(direction * start),
            float(direction * (start + depth)),
        ],
    }, errors


def thread_surrogate_plan_errors(plan: dict, recipes: list[dict], geometries: list[dict]) -> list[str]:
    """Gate B structural equality for axis, center, depth, range, count and owner."""
    errors: list[str] = []
    recipe_by_id = {item.get("feature_id"): item for item in recipes if isinstance(item, dict)}
    geometry_by_id = {item.get("feature_id"): item for item in geometries if isinstance(item, dict)}
    marked = [op for op in plan.get("operations") or [] if isinstance(op.get("thread_surrogate_use"), dict)]
    for op in marked:
        fid = op["thread_surrogate_use"].get("feature_id")
        if fid not in recipe_by_id:
            errors.append(f"step {op.get('step')}: thread surrogate feature is absent from drawing")
    for fid, recipe in recipe_by_id.items():
        expected = geometry_by_id.get(fid)
        if expected is None:
            errors.append(f"thread feature {fid!r} has no validated drawing geometry")
            continue
        matches = [op for op in marked if op["thread_surrogate_use"].get("feature_id") == fid]
        if expected.get("representation") == "subsumed_by_coaxial_through_hole":
            if matches:
                errors.append(
                    f"thread surrogate for feature {fid!r} is redundant because "
                    f"coaxial through feature {expected.get('subsumed_by_feature_id')!r} "
                    "already covers its tap-drill geometry"
                )
            continue
        if len(matches) != expected.get("count"):
            errors.append(f"thread surrogate for feature {fid!r} operation count differs from drawing")
        actual_geometries = []
        for op in matches:
            use = op["thread_surrogate_use"]
            if use.get("owner_feature_id") != expected.get("owner_feature_id"):
                errors.append(f"thread surrogate for feature {fid!r} changes feature ownership")
            expected_material_side = expected.get("material_side")
            expected_entry_endpoint = expected.get("entry_endpoint")
            if (
                expected_material_side is not None
                or expected_entry_endpoint is not None
            ):
                if (
                    use.get("material_side") is not None
                    or use.get("entry_endpoint") is not None
                ):
                    if use.get("material_side") != expected_material_side:
                        errors.append(
                            f"thread surrogate for feature {fid!r} changes material-side semantics"
                        )
                    if use.get("entry_endpoint") != expected_entry_endpoint:
                        errors.append(
                            f"thread surrogate for feature {fid!r} changes entry-endpoint semantics"
                        )
                else:
                    legacy_use_side = use.get("side")
                    if not (
                        expected_material_side == expected_entry_endpoint
                        and legacy_use_side == expected_material_side
                    ):
                        errors.append(
                            f"thread surrogate for feature {fid!r} cannot represent "
                            "split material-side/entry-endpoint semantics"
                        )
            elif use.get("side") != expected.get("side"):
                errors.append(f"thread surrogate for feature {fid!r} changes side semantics")
            actual, op_errors = _thread_operation_geometry(plan, op, float(recipe["surrogate_diameter"]))
            errors.extend(op_errors)
            if actual is not None:
                actual_geometries.append(actual)
        expected_centers = sorted(expected.get("transverse_centers") or [])
        actual_centers = sorted(item["transverse_center"] for item in actual_geometries)
        if actual_centers != expected_centers:
            errors.append(f"thread surrogate for feature {fid!r} changes center")
        for actual in actual_geometries:
            if actual["axis"] != expected.get("axis"):
                errors.append(f"thread surrogate for feature {fid!r} changes axis")
            if not _drawing_equal(actual["depth"], expected.get("depth")):
                errors.append(f"thread surrogate for feature {fid!r} changes depth")
            if len(expected.get("axial_range") or []) != 2 or any(not _drawing_equal(a, b) for a, b in zip(actual["axial_range"], expected["axial_range"])):
                errors.append(f"thread surrogate for feature {fid!r} changes axial range")
    return errors


def _axis_bounds(
    drawing: dict,
    axis: str,
) -> tuple[float, float] | None:
    bbox = _drawing_overall_bbox(drawing)
    if bbox is None:
        return None
    lx, ly, hz = bbox
    return {
        "X": (-lx / 2.0, lx / 2.0),
        "Y": (-ly / 2.0, ly / 2.0),
        "Z": (0.0, hz),
    }.get(axis.upper())


def _fixed_global_coordinates(
    axis: str,
    transverse_point: Any,
) -> dict[str, float] | None:
    center = _axis_transverse_center(axis, transverse_point)
    if center is None:
        return None
    keys = {
        "X": ("Y", "Z"),
        "Y": ("X", "Z"),
        "Z": ("X", "Y"),
    }.get(axis.upper())
    if keys is None:
        return None
    return {keys[0]: center[0], keys[1]: center[1]}


def _profile_line_polygon(
    drawing: dict,
) -> tuple[tuple[str, str] | None, list[tuple[float, float]], list[str]]:
    """Read one ordered closed, line-segment canonical body profile."""
    profile = drawing.get("profile")
    if not isinstance(profile, dict):
        return None, [], ["material_interval_violation: canonical profile is missing"]

    plane = str(profile.get("plane") or "").upper()
    if plane not in {"XY", "XZ", "YZ"}:
        return None, [], [
            f"material_interval_violation: unsupported profile plane {plane!r}"
        ]
    axes = (plane[0], plane[1])
    segments = profile.get("segments")
    if not isinstance(segments, list) or len(segments) < 3:
        return None, [], [
            "material_interval_violation: profile requires at least three line segments"
        ]

    polygon: list[tuple[float, float]] = []
    errors: list[str] = []
    first_start: tuple[float, float] | None = None
    previous_end: tuple[float, float] | None = None
    for index, segment in enumerate(segments):
        label = f"profile.segments[{index}]"
        if not isinstance(segment, dict) or str(segment.get("type") or "").lower() != "line":
            errors.append(
                f"material_interval_violation: {label} must be a line segment"
            )
            continue
        a = axes[0].lower()
        b = axes[1].lower()
        values = [
            _num(segment.get(f"{a}1")),
            _num(segment.get(f"{b}1")),
            _num(segment.get(f"{a}2")),
            _num(segment.get(f"{b}2")),
        ]
        if any(value is None for value in values):
            errors.append(
                f"material_interval_violation: {label} has incomplete coordinates"
            )
            continue
        start = (float(values[0]), float(values[1]))
        end = (float(values[2]), float(values[3]))
        if start == end:
            errors.append(
                f"material_interval_violation: {label} has zero length"
            )
            continue
        if first_start is None:
            first_start = start
            polygon.append(start)
        elif previous_end is None or any(
            abs(left - right) > 1e-9
            for left, right in zip(previous_end, start, strict=False)
        ):
            errors.append(
                f"material_interval_violation: {label} is not continuous with "
                "the previous profile segment"
            )
        polygon.append(end)
        previous_end = end

    if errors:
        return None, [], errors
    if first_start is None or previous_end is None or any(
        abs(left - right) > 1e-9
        for left, right in zip(previous_end, first_start, strict=False)
    ):
        return None, [], [
            "material_interval_violation: profile is not closed"
        ]
    return axes, polygon[:-1], []



def _rotational_profile_axis_material_intervals(
    drawing: dict,
    axis: str,
    transverse_point: Any,
) -> tuple[list[list[float]], list[str]]:
    """Intersect an axis-of-revolution query line with a canonical meridian.

    The meridian may contain exact line and arc primitives.  The transverse
    query is reduced to its engineering radial distance from the canonical
    rotation axis; raster coordinates never participate.
    """
    geometry, geometry_errors = _rotational_profile_geometry(drawing)
    if geometry_errors or geometry is None:
        return [], [
            f"material_interval_violation: {item}"
            for item in geometry_errors
        ]

    axis = str(axis or "").upper()
    if str(geometry.get("axis") or "").upper() != axis:
        return [], [
            "material_interval_violation: rotational profile query axis does "
            "not match rotation_axis"
        ]

    transverse = _axis_transverse_center(axis, transverse_point)
    if transverse is None:
        return [], [
            "material_interval_violation: rotational profile query center is invalid"
        ]
    radial = math.hypot(float(transverse[0]), float(transverse[1]))

    plane = str(geometry.get("plane") or "").upper()
    axes = (plane[0], plane[1])
    axis_index = axes.index(axis)
    radial_index = 1 - axis_index
    local_keys = ("x", "y")
    axial_key = local_keys[axis_index]
    radial_key = local_keys[radial_index]
    tolerance = 1e-7
    crossings: list[float] = []

    def angle_on_arc(angle: float, start: float, end: float) -> bool:
        sweep = (end - start) % 360.0
        if sweep <= tolerance:
            return False
        relative = (angle - start) % 360.0
        return relative <= sweep + tolerance

    for index, segment in enumerate(geometry.get("segments") or []):
        segment_type = str(segment.get("type") or "").lower()

        if segment_type == "line":
            start = segment.get("start")
            end = segment.get("end")
            if not isinstance(start, dict) or not isinstance(end, dict):
                return [], [
                    f"material_interval_violation: rotational profile line {index} "
                    "is malformed"
                ]
            start_radial = _num(start.get(radial_key))
            end_radial = _num(end.get(radial_key))
            start_axial = _num(start.get(axial_key))
            end_axial = _num(end.get(axial_key))
            if any(
                value is None
                for value in (
                    start_radial,
                    end_radial,
                    start_axial,
                    end_axial,
                )
            ):
                return [], [
                    f"material_interval_violation: rotational profile line {index} "
                    "has incomplete engineering coordinates"
                ]

            start_radial = float(start_radial)
            end_radial = float(end_radial)
            start_axial = float(start_axial)
            end_axial = float(end_axial)
            if (
                abs(start_radial - radial) <= tolerance
                and abs(end_radial - radial) <= tolerance
            ):
                return [], [
                    "material_interval_violation: rotational profile scan "
                    f"coincides with profile line {index}"
                ]
            if abs(end_radial - start_radial) <= tolerance:
                continue
            if (
                radial < min(start_radial, end_radial) - tolerance
                or radial > max(start_radial, end_radial) + tolerance
            ):
                continue

            ratio = (radial - start_radial) / (end_radial - start_radial)
            if -tolerance <= ratio <= 1.0 + tolerance:
                crossings.append(
                    float(start_axial + ratio * (end_axial - start_axial))
                )
            continue

        if segment_type == "arc":
            center = segment.get("center")
            radius = _num(segment.get("radius"))
            start_angle = _num(segment.get("start_angle"))
            end_angle = _num(segment.get("end_angle"))
            if (
                not isinstance(center, dict)
                or radius is None
                or radius <= 0
                or start_angle is None
                or end_angle is None
            ):
                return [], [
                    f"material_interval_violation: rotational profile arc {index} "
                    "is malformed"
                ]

            center_radial = _num(center.get(radial_key))
            center_axial = _num(center.get(axial_key))
            center_x = _num(center.get("x"))
            center_y = _num(center.get("y"))
            if any(
                value is None
                for value in (
                    center_radial,
                    center_axial,
                    center_x,
                    center_y,
                )
            ):
                return [], [
                    f"material_interval_violation: rotational profile arc {index} "
                    "has incomplete engineering center"
                ]

            radius_value = float(radius)
            delta = radial - float(center_radial)
            remaining = radius_value * radius_value - delta * delta
            if remaining < -tolerance:
                continue
            if remaining <= tolerance:
                # A tangential touch does not toggle inside/outside parity.
                continue

            offset = math.sqrt(max(0.0, remaining))
            for axial_value in (
                float(center_axial) - offset,
                float(center_axial) + offset,
            ):
                point = {
                    radial_key: radial,
                    axial_key: axial_value,
                }
                angle = math.degrees(
                    math.atan2(
                        float(point["y"]) - float(center_y),
                        float(point["x"]) - float(center_x),
                    )
                )
                if angle_on_arc(
                    angle,
                    float(start_angle),
                    float(end_angle),
                ):
                    crossings.append(float(axial_value))
            continue

        return [], [
            f"material_interval_violation: rotational profile segment {index} "
            f"uses unsupported primitive type {segment_type!r}"
        ]

    unique: list[float] = []
    for value in sorted(crossings):
        if not unique or abs(value - unique[-1]) > tolerance:
            unique.append(value)

    if len(unique) % 2:
        return [], [
            "material_interval_violation: rotational profile scan has an odd "
            "number of boundary crossings"
        ]

    intervals = [
        [unique[index], unique[index + 1]]
        for index in range(0, len(unique), 2)
        if unique[index + 1] > unique[index] + tolerance
    ]
    return _merge_intervals(intervals), []


def _point_on_segment_2d(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    px, py = point
    ax, ay = start
    bx, by = end
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > 1e-9:
        return False
    return (
        min(ax, bx) - 1e-9 <= px <= max(ax, bx) + 1e-9
        and min(ay, by) - 1e-9 <= py <= max(ay, by) + 1e-9
    )


def _point_in_polygon(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> tuple[bool, bool]:
    """Return (strictly_inside, on_boundary) for a simple line polygon."""
    if len(polygon) < 3:
        return False, False
    inside = False
    px, py = point
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _point_on_segment_2d(point, start, end):
            return False, True
        ax, ay = start
        bx, by = end
        if (ay > py) == (by > py):
            continue
        x_cross = ax + (py - ay) * (bx - ax) / (by - ay)
        if x_cross > px:
            inside = not inside
    return inside, False


def _merge_intervals(
    intervals: list[list[float]],
) -> list[list[float]]:
    normalized = sorted(
        (
            [min(float(value[0]), float(value[1])), max(float(value[0]), float(value[1]))]
            for value in intervals
            if len(value) == 2 and abs(float(value[1]) - float(value[0])) > 1e-9
        ),
        key=lambda value: (value[0], value[1]),
    )
    merged: list[list[float]] = []
    for interval in normalized:
        if not merged or interval[0] > merged[-1][1] + 1e-9:
            merged.append(interval)
        else:
            merged[-1][1] = max(merged[-1][1], interval[1])
    return merged


def _subtract_intervals(
    material: list[list[float]],
    voids: list[list[float]],
) -> list[list[float]]:
    output = _merge_intervals(material)
    for void_lo, void_hi in _merge_intervals(voids):
        next_output: list[list[float]] = []
        for mat_lo, mat_hi in output:
            overlap_lo = max(mat_lo, void_lo)
            overlap_hi = min(mat_hi, void_hi)
            if overlap_hi <= overlap_lo + 1e-9:
                next_output.append([mat_lo, mat_hi])
                continue
            if overlap_lo > mat_lo + 1e-9:
                next_output.append([mat_lo, overlap_lo])
            if overlap_hi < mat_hi - 1e-9:
                next_output.append([overlap_hi, mat_hi])
        output = next_output
    return output


def _profile_material_intervals(
    drawing: dict,
    axis: str,
    transverse_point: Any,
) -> tuple[list[list[float]], list[str]]:
    """Intersect one principal-axis query line with canonical body profile."""
    axis = axis.upper()
    profile = drawing.get("profile")
    rotation_axis = (
        str(profile.get("rotation_axis") or "").upper()
        if isinstance(profile, dict)
        else ""
    )
    if rotation_axis == axis:
        return _rotational_profile_axis_material_intervals(
            drawing,
            axis,
            transverse_point,
        )

    bounds = _axis_bounds(drawing, axis)
    fixed = _fixed_global_coordinates(axis, transverse_point)
    profile_axes, polygon, errors = _profile_line_polygon(drawing)
    if errors:
        return [], errors
    if bounds is None or fixed is None or profile_axes is None:
        return [], [
            "material_interval_violation: incomplete query axis/overall geometry"
        ]

    extrusion_axis = next(
        value for value in ("X", "Y", "Z") if value not in profile_axes
    )
    if axis == extrusion_axis:
        point = (fixed[profile_axes[0]], fixed[profile_axes[1]])
        inside, boundary = _point_in_polygon(point, polygon)
        if boundary:
            return [], [
                "material_interval_violation: query line lies on profile boundary"
            ]
        return ([list(bounds)] if inside else []), []

    if axis not in profile_axes:
        return [], [
            f"material_interval_violation: axis {axis!r} is incompatible with "
            f"profile plane {''.join(profile_axes)!r}"
        ]

    extrusion_coordinate = fixed.get(extrusion_axis)
    extrusion_bounds = _axis_bounds(drawing, extrusion_axis)
    if extrusion_coordinate is None or extrusion_bounds is None:
        return [], [
            "material_interval_violation: profile extrusion coordinate is unavailable"
        ]
    if not (
        extrusion_bounds[0] - 1e-9
        <= extrusion_coordinate
        <= extrusion_bounds[1] + 1e-9
    ):
        return [], []

    axis_index = profile_axes.index(axis)
    other_index = 1 - axis_index
    other_axis = profile_axes[other_index]
    fixed_value = fixed.get(other_axis)
    if fixed_value is None:
        return [], [
            "material_interval_violation: profile scan coordinate is unavailable"
        ]

    crossings: list[float] = []
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        start_axis = start[axis_index]
        end_axis = end[axis_index]
        start_fixed = start[other_index]
        end_fixed = end[other_index]

        if (
            abs(start_fixed - fixed_value) <= 1e-9
            and abs(end_fixed - fixed_value) <= 1e-9
        ):
            return [], [
                "material_interval_violation: profile scan coincides with a "
                "profile boundary segment"
            ]
        if abs(end_fixed - start_fixed) <= 1e-12:
            continue
        low = min(start_fixed, end_fixed)
        high = max(start_fixed, end_fixed)
        if fixed_value < low - 1e-9 or fixed_value > high + 1e-9:
            continue
        ratio = (fixed_value - start_fixed) / (end_fixed - start_fixed)
        if -1e-9 <= ratio <= 1.0 + 1e-9:
            crossings.append(
                float(start_axis + ratio * (end_axis - start_axis))
            )

    unique: list[float] = []
    for value in sorted(crossings):
        if not unique or abs(value - unique[-1]) > 1e-9:
            unique.append(value)

    intervals: list[list[float]] = []
    for lo, hi in zip(unique, unique[1:], strict=False):
        if hi <= lo + 1e-9:
            continue
        midpoint = (lo + hi) / 2.0
        point = (
            (midpoint, fixed_value)
            if axis_index == 0
            else (fixed_value, midpoint)
        )
        inside, boundary = _point_in_polygon(point, polygon)
        if inside and not boundary:
            intervals.append([float(lo), float(hi)])
    return _merge_intervals(intervals), []


def _slot_void_intervals(
    drawing: dict,
    feature: dict,
    axis: str,
    transverse_point: Any,
) -> tuple[list[list[float]], list[str]]:
    if str(feature.get("type") or "").lower() not in {"slot", "slit", "cut"}:
        return [], []

    width_axis = str(feature.get("width_axis") or "").upper()
    through_axis = str(feature.get("through_axis") or "").upper()
    if (
        width_axis not in {"X", "Y"}
        or through_axis not in {"X", "Y"}
        or width_axis == through_axis
    ):
        return [], [
            "material_interval_violation: prismatic slot requires distinct "
            "horizontal width_axis/through_axis"
        ]

    width = _num(feature.get("width"))
    center = _num(_drawing_feature_coord(feature, width_axis.lower()))
    bottom_z = _num(feature.get("bottom_z"))
    top_z = _num(feature.get("top_z"))
    fixed = _fixed_global_coordinates(axis, transverse_point)
    through_bounds = _axis_bounds(drawing, through_axis)
    if (
        width is None
        or width <= 0
        or center is None
        or bottom_z is None
        or top_z is None
        or top_z <= bottom_z
        or fixed is None
        or through_bounds is None
    ):
        return [], [
            f"material_interval_violation: slot {feature.get('id')!r} has "
            "incomplete canonical geometry"
        ]

    width_interval = [
        float(center - width / 2.0),
        float(center + width / 2.0),
    ]
    z_interval = [float(bottom_z), float(top_z)]

    if axis == width_axis:
        through_value = fixed.get(through_axis)
        z_value = fixed.get("Z")
        if (
            through_value is None
            or z_value is None
            or not (
                through_bounds[0] - 1e-9
                <= through_value
                <= through_bounds[1] + 1e-9
            )
            or not (z_interval[0] - 1e-9 <= z_value <= z_interval[1] + 1e-9)
        ):
            return [], []
        return [width_interval], []

    if axis == through_axis:
        width_value = fixed.get(width_axis)
        z_value = fixed.get("Z")
        if (
            width_value is None
            or z_value is None
            or not (
                width_interval[0] - 1e-9
                <= width_value
                <= width_interval[1] + 1e-9
            )
            or not (z_interval[0] - 1e-9 <= z_value <= z_interval[1] + 1e-9)
        ):
            return [], []
        return [list(through_bounds)], []

    if axis == "Z":
        width_value = fixed.get(width_axis)
        through_value = fixed.get(through_axis)
        if (
            width_value is None
            or through_value is None
            or not (
                width_interval[0] - 1e-9
                <= width_value
                <= width_interval[1] + 1e-9
            )
            or not (
                through_bounds[0] - 1e-9
                <= through_value
                <= through_bounds[1] + 1e-9
            )
        ):
            return [], []
        return [z_interval], []

    return [], []


def _feature_explicit_axial_range(feature: dict) -> list[float] | None:
    value = _thread_feature_value(
        feature,
        "axis_range",
        "axial_range",
        "through_range",
        "range",
    )
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(_num(item) is None for item in value)
    ):
        return None
    first = float(_num(value[0]))
    second = float(_num(value[1]))
    if abs(first - second) <= 1e-9:
        return None
    return [min(first, second), max(first, second)]


def _cylindrical_void_intervals(
    drawing: dict,
    feature: dict,
    axis: str,
    transverse_point: Any,
) -> tuple[list[list[float]], list[str]]:
    if str(feature.get("type") or "").lower() not in {
        "hole",
        "through_hole",
        "threaded_hole",
        "counterbore_hole",
        "countersink_hole",
    }:
        return [], []

    feature_axis = str(feature.get("axis") or "").upper()
    axial_range = _feature_explicit_axial_range(feature)
    diameter = _num(
        feature.get("diameter")
        if feature.get("diameter") is not None
        else feature.get("hole_diameter")
    )
    if (
        feature_axis not in {"X", "Y", "Z"}
        or axial_range is None
        or diameter is None
        or diameter <= 0
    ):
        return [], []

    fixed = _fixed_global_coordinates(axis, transverse_point)
    if fixed is None:
        return [], [
            "material_interval_violation: cylindrical void query center is invalid"
        ]

    transverse_axes = [
        value for value in ("X", "Y", "Z") if value != feature_axis
    ]
    feature_center = {
        value: _num(_drawing_feature_coord(feature, value.lower()))
        for value in transverse_axes
    }
    if any(feature_center[value] is None for value in transverse_axes):
        return [], []

    radius = float(diameter) / 2.0
    if axis == feature_axis:
        radial_sq = 0.0
        for value in transverse_axes:
            coordinate = fixed.get(value)
            if coordinate is None:
                return [], []
            radial_sq += (coordinate - float(feature_center[value])) ** 2
        return ([axial_range] if radial_sq < radius * radius - 1e-12 else []), []

    if axis not in transverse_axes:
        return [], []
    third_axis = next(
        value for value in transverse_axes if value != axis
    )
    feature_axis_coordinate = fixed.get(feature_axis)
    third_coordinate = fixed.get(third_axis)
    axis_center = feature_center.get(axis)
    third_center = feature_center.get(third_axis)
    if (
        feature_axis_coordinate is None
        or third_coordinate is None
        or axis_center is None
        or third_center is None
        or not (
            axial_range[0] - 1e-9
            <= feature_axis_coordinate
            <= axial_range[1] + 1e-9
        )
    ):
        return [], []

    radial_offset = third_coordinate - float(third_center)
    remaining = radius * radius - radial_offset * radial_offset
    if remaining <= 1e-12:
        return [], []
    half_span = math.sqrt(remaining)
    return [[float(axis_center) - half_span, float(axis_center) + half_span]], []


_MATERIAL_VOID_PROVIDERS = (
    _slot_void_intervals,
    _cylindrical_void_intervals,
)


def resolve_axis_material_intervals(
    drawing: dict,
    axis: str,
    transverse_point: Any,
    *,
    exclude_feature_ids: set[str] | None = None,
) -> tuple[list[list[float]], list[str]]:
    """Resolve real solid intervals on one principal-axis engineering query line.

    The body contribution comes from the canonical closed profile.  Canonical
    subtractive features are projected through independent void providers and
    subtracted as intervals.  The result contains engineering coordinates only;
    no pixel measurement and no NX tool implementation participates.
    """
    axis = str(axis or "").upper()
    if axis not in {"X", "Y", "Z"}:
        return [], [f"material_interval_violation: invalid axis {axis!r}"]

    material, errors = _profile_material_intervals(
        drawing,
        axis,
        transverse_point,
    )
    if errors or not material:
        return material, errors

    excluded = set(exclude_feature_ids or set())
    voids: list[list[float]] = []
    for feature in drawing.get("features") or []:
        if not isinstance(feature, dict):
            continue
        feature_id = str(feature.get("id") or "")
        if feature_id and feature_id in excluded:
            continue
        for provider in _MATERIAL_VOID_PROVIDERS:
            intervals, provider_errors = provider(
                drawing,
                feature,
                axis,
                transverse_point,
            )
            if provider_errors:
                errors.extend(provider_errors)
            voids.extend(intervals)

    if errors:
        return [], errors
    return _subtract_intervals(material, voids), []


def _select_material_interval(
    intervals: list[list[float]],
    side: str,
) -> list[float] | None:
    normalized = _merge_intervals(intervals)
    if not normalized or side not in {"min", "max"}:
        return None
    return list(normalized[0] if side == "min" else normalized[-1])


def _depth_range_from_material_interval(
    interval: list[float],
    side: str,
    depth: float,
) -> list[float] | None:
    if len(interval) != 2 or depth <= 0 or side not in {"min", "max"}:
        return None
    lo, hi = min(interval), max(interval)
    start = lo if side == "min" else hi
    end = start + depth if side == "min" else start - depth
    if end < lo - 1e-9 or end > hi + 1e-9:
        return None
    return [float(start), float(end)]


def resolve_transverse_recess_drawing_geometries(
    drawing: dict,
    *,
    axes: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Derive X/Y counterbore execution ranges from canonical material intervals."""
    geometries: list[dict] = []
    errors: list[str] = []

    for feature in drawing.get("features") or []:
        if not isinstance(feature, dict):
            continue
        if str(feature.get("type") or "").lower() != "counterbore_hole":
            continue
        axis = str(feature.get("axis") or "").upper()
        if (
            axis not in {"X", "Y"}
            or (axes is not None and axis not in axes)
            or feature.get("through") is not True
        ):
            continue

        fid = str(feature.get("id") or "?")
        side_value = (
            feature.get("start_side")
            if feature.get("start_side") is not None
            else feature.get("side")
        )
        side = str(side_value or "").lower()
        if side not in {"min", "max"}:
            errors.append(
                f"transverse_recess_geometry_violation: feature {fid!r} has no "
                "confirmed start_side/side"
            )
            continue

        center = _axis_transverse_center(axis, feature.get("centerline"))
        through_diameter = _num(
            feature.get("diameter")
            if feature.get("diameter") is not None
            else feature.get("hole_diameter")
        )
        recess_diameter = _num(feature.get("counterbore_diameter"))
        recess_depth = _num(feature.get("counterbore_depth"))
        if (
            center is None
            or through_diameter is None
            or through_diameter <= 0
            or recess_diameter is None
            or recess_diameter <= through_diameter
            or recess_depth is None
            or recess_depth <= 0
        ):
            errors.append(
                f"transverse_recess_geometry_violation: feature {fid!r} has "
                "incomplete counterbore geometry"
            )
            continue

        material, material_errors = resolve_axis_material_intervals(
            drawing,
            axis,
            center,
            exclude_feature_ids={fid},
        )
        if material_errors:
            errors.extend(
                f"transverse_recess_geometry_violation: feature {fid!r}: {item}"
                for item in material_errors
            )
            continue
        selected = _select_material_interval(material, side)
        if selected is None:
            errors.append(
                f"transverse_recess_geometry_violation: feature {fid!r} has no "
                f"material interval on start_side={side}"
            )
            continue

        through_range = (
            [selected[0], selected[1]]
            if side == "min"
            else [selected[1], selected[0]]
        )
        counterbore_range = _depth_range_from_material_interval(
            selected,
            side,
            float(recess_depth),
        )
        if counterbore_range is None:
            errors.append(
                f"transverse_recess_geometry_violation: feature {fid!r} "
                "counterbore depth exceeds the selected material interval"
            )
            continue

        geometries.append(
            {
                "feature_id": fid,
                "axis": axis,
                "transverse_center": center,
                "side": side,
                "material_intervals": material,
                "material_interval": selected,
                "through_diameter": float(through_diameter),
                "counterbore_diameter": float(recess_diameter),
                "counterbore_depth": float(recess_depth),
                "through_axial_range": through_range,
                "counterbore_axial_range": counterbore_range,
            }
        )

    return geometries, errors


def _subtract_circle_operation_geometry(
    plan: dict,
    op: dict,
) -> dict | None:
    """Read one principal-plane circular subtract in global engineering coordinates."""
    args = op.get("tool_args") or {}
    if op.get("tool") != "nx_extrude" or args.get("operation") != "subtract":
        return None
    if any(
        key not in args
        for key in ("sketch_id", "distance", "start_offset", "reverse")
    ):
        return None
    if not isinstance(args.get("reverse"), bool):
        return None

    operations = plan.get("operations") or []
    try:
        op_index = operations.index(op)
    except ValueError:
        return None
    sketch_id = args.get("sketch_id")
    circles = [
        candidate
        for candidate in operations[:op_index]
        if candidate.get("tool") == "nx_sketch_circle"
        and (candidate.get("tool_args") or {}).get("sketch_id") == sketch_id
    ]
    if len(circles) != 1:
        return None

    circle = circles[0]
    circle_index = operations.index(circle)
    creates = [
        candidate
        for candidate in operations[:circle_index]
        if candidate.get("tool") == "nx_create_sketch"
    ]
    if not creates:
        return None
    plane = str((creates[-1].get("tool_args") or {}).get("plane") or "").upper()
    axis = {"XY": "Z", "XZ": "Y", "YZ": "X"}.get(plane)
    if axis is None:
        return None

    center = _axis_transverse_center(
        "Z",
        (circle.get("tool_args") or {}).get("center"),
    )
    diameter = _num((circle.get("tool_args") or {}).get("diameter"))
    distance = _num(args.get("distance"))
    start = _num(args.get("start_offset"))
    if (
        center is None
        or diameter is None
        or diameter <= 0
        or distance is None
        or distance <= 0
        or start is None
    ):
        return None

    direction = -1.0 if args["reverse"] else 1.0
    return {
        "step": op.get("step"),
        "axis": axis,
        "transverse_center": center,
        "diameter": float(diameter),
        "axial_range": [
            float(direction * start),
            float(direction * (start + distance)),
        ],
    }


def transverse_recess_plan_errors(
    plan: dict,
    geometries: list[dict],
) -> list[str]:
    """Gate B check for material-resolved X/Y through + counterbore operations."""
    if not geometries:
        return []

    actual = [
        geometry
        for op in plan.get("operations") or []
        if isinstance(op, dict)
        if (geometry := _subtract_circle_operation_geometry(plan, op)) is not None
    ]
    errors: list[str] = []

    for expected in geometries:
        fid = str(expected.get("feature_id") or "?")
        axis = expected.get("axis")
        center = expected.get("transverse_center")

        for label, diameter_key, range_key in (
            ("through", "through_diameter", "through_axial_range"),
            ("counterbore", "counterbore_diameter", "counterbore_axial_range"),
        ):
            diameter = expected.get(diameter_key)
            expected_range = expected.get(range_key)
            matches = [
                item
                for item in actual
                if item.get("axis") == axis
                and item.get("transverse_center") == center
                and _drawing_equal(item.get("diameter"), diameter)
            ]
            if len(matches) != 1:
                errors.append(
                    f"transverse recess feature {fid!r} {label} operation count "
                    f"must be 1, got {len(matches)}"
                )
                continue
            actual_range = matches[0].get("axial_range")
            if (
                not isinstance(expected_range, list)
                or len(expected_range) != 2
                or not isinstance(actual_range, list)
                or len(actual_range) != 2
                or any(
                    not _drawing_equal(a, b)
                    for a, b in zip(actual_range, expected_range, strict=False)
                )
            ):
                errors.append(
                    f"transverse recess feature {fid!r} {label} changes axial range"
                )

    return errors



def _capability_feature_centers(
    feature: dict,
    axis: str,
) -> tuple[list[list[float]], list[str]]:
    """Normalize one feature's explicit/transverse centers without pixel geometry."""
    fid = str(feature.get("id") or "?")
    centers_value = feature.get("explicit_centers")
    if not isinstance(centers_value, list) or not centers_value:
        center_value = feature.get("centerline")
        position = feature.get("position")
        if center_value is None and isinstance(position, dict):
            center_value = position.get("center")
        if center_value is None:
            center_value = feature.get("center")
        centers_value = [center_value] if center_value is not None else []

    centers = [_axis_transverse_center(axis, value) for value in centers_value]
    if not centers or any(value is None for value in centers):
        return [], [f"capability_geometry_violation: feature {fid!r} has no valid center"]

    normalized = [list(value) for value in centers if value is not None]
    count_value = _num(feature.get("count"))
    if count_value is not None:
        if count_value <= 0 or not float(count_value).is_integer():
            return [], [
                f"capability_geometry_violation: feature {fid!r} has invalid count"
            ]
        if len(normalized) != int(count_value):
            return [], [
                f"capability_geometry_violation: feature {fid!r} center count "
                f"{len(normalized)} != count {int(count_value)}"
            ]
    return normalized, []


def _feature_explicit_axial_range(feature: dict) -> list[float] | None:
    value = _thread_feature_value(
        feature,
        "axis_range",
        "axial_range",
        "through_range",
        "range",
    )
    if not (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(_num(item) is not None for item in value)
    ):
        return None
    return [float(_num(value[0])), float(_num(value[1]))]


def resolve_hole_drawing_geometries(
    drawing: dict,
    *,
    axes: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Resolve plain-hole Feature Contracts into deterministic engineering ranges."""
    geometries: list[dict] = []
    errors: list[str] = []

    for feature in drawing.get("features") or []:
        if not isinstance(feature, dict):
            continue
        feature_type = str(feature.get("type") or feature.get("kind") or "").lower()
        if feature_type not in {"hole", "through_hole"}:
            continue
        if feature.get("required_for_modeling") is False:
            continue

        fid = str(feature.get("id") or "?")
        axis = str(feature.get("axis") or "").upper()
        if axes is not None and axis not in axes:
            continue
        if axis not in {"X", "Y", "Z"}:
            errors.append(
                f"capability_geometry_violation: hole {fid!r} has invalid axis {axis!r}"
            )
            continue

        diameter = _num(
            feature.get("diameter")
            if feature.get("diameter") is not None
            else feature.get("hole_diameter")
        )
        if diameter is None or diameter <= 0:
            errors.append(
                f"capability_geometry_violation: hole {fid!r} has invalid diameter"
            )
            continue

        centers, center_errors = _capability_feature_centers(feature, axis)
        if center_errors:
            errors.extend(center_errors)
            continue

        explicit_range = _feature_explicit_axial_range(feature)
        ranges: list[list[float]] = []
        failed = False

        for center in centers:
            if explicit_range is not None:
                ranges.append(list(explicit_range))
                continue

            material, material_errors = resolve_axis_material_intervals(
                drawing,
                axis,
                center,
                exclude_feature_ids={fid},
            )
            if material_errors:
                errors.extend(
                    f"capability_geometry_violation: hole {fid!r}: {item}"
                    for item in material_errors
                )
                failed = True
                break
            normalized_material = _merge_intervals(material)
            if not normalized_material:
                errors.append(
                    f"capability_geometry_violation: hole {fid!r} has no material "
                    "interval at its center"
                )
                failed = True
                break

            through = feature.get("through") is True or feature_type == "through_hole"
            side_value = (
                feature.get("start_side")
                if feature.get("start_side") is not None
                else feature.get("side")
            )
            side = str(side_value or "").lower()
            if axis == "Z" and side not in {"min", "max"}:
                side = "min"

            if through:
                if len(normalized_material) != 1:
                    errors.append(
                        f"capability_geometry_violation: through hole {fid!r} "
                        "crosses multiple material intervals without explicit axial range"
                    )
                    failed = True
                    break
                selected = normalized_material[0]
                ranges.append(
                    [selected[0], selected[1]]
                    if side != "max"
                    else [selected[1], selected[0]]
                )
                continue

            depth = _num(
                feature.get("depth")
                if feature.get("depth") is not None
                else feature.get("hole_depth")
            )
            if depth is None or depth <= 0 or side not in {"min", "max"}:
                errors.append(
                    f"capability_geometry_violation: blind hole {fid!r} requires "
                    "positive depth and deterministic start_side"
                )
                failed = True
                break
            selected = _select_material_interval(normalized_material, side)
            axial_range = (
                _depth_range_from_material_interval(selected, side, float(depth))
                if selected is not None
                else None
            )
            if axial_range is None:
                errors.append(
                    f"capability_geometry_violation: blind hole {fid!r} depth "
                    "exceeds selected material interval"
                )
                failed = True
                break
            ranges.append(axial_range)

        if failed:
            continue
        if not ranges or any(
            len(value) != 2
            or any(
                not _drawing_equal(left, right)
                for left, right in zip(value, ranges[0], strict=False)
            )
            for value in ranges[1:]
        ):
            errors.append(
                f"capability_geometry_violation: hole {fid!r} centers do not share "
                "one deterministic axial range"
            )
            continue

        geometries.append(
            {
                "feature_id": fid,
                "axis": axis,
                "transverse_centers": centers,
                "diameter": float(diameter),
                "axial_range": ranges[0],
                "count": len(centers),
            }
        )

    return geometries, errors


def resolve_counterbore_drawing_geometries(
    drawing: dict,
    *,
    axes: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Resolve both principal-axis and native-Z counterbore Feature Contracts."""
    transverse_axes = {"X", "Y"} if axes is None else (set(axes) & {"X", "Y"})
    if transverse_axes:
        geometries, errors = resolve_transverse_recess_drawing_geometries(
            drawing,
            axes=transverse_axes,
        )
    else:
        geometries, errors = [], []

    for feature in drawing.get("features") or []:
        if not isinstance(feature, dict):
            continue
        if str(feature.get("type") or "").lower() != "counterbore_hole":
            continue
        if feature.get("required_for_modeling") is False:
            continue
        if str(feature.get("axis") or "").upper() != "Z":
            continue
        if axes is not None and "Z" not in axes:
            continue

        fid = str(feature.get("id") or "?")
        centers, center_errors = _capability_feature_centers(feature, "Z")
        if center_errors:
            errors.extend(center_errors)
            continue

        through_diameter = _num(
            feature.get("diameter")
            if feature.get("diameter") is not None
            else feature.get("hole_diameter")
        )
        counterbore_diameter = _num(feature.get("counterbore_diameter"))
        counterbore_depth = _num(feature.get("counterbore_depth"))
        if (
            through_diameter is None
            or through_diameter <= 0
            or counterbore_diameter is None
            or counterbore_diameter <= through_diameter
            or counterbore_depth is None
            or counterbore_depth <= 0
        ):
            errors.append(
                f"capability_geometry_violation: counterbore {fid!r} has incomplete geometry"
            )
            continue

        side_value = (
            feature.get("start_side")
            if feature.get("start_side") is not None
            else feature.get("side")
        )
        side = str(side_value or "").lower()
        if side not in {"", "min"}:
            errors.append(
                f"capability_geometry_violation: native Z counterbore {fid!r} "
                "cannot enter from max side"
            )
            continue

        explicit_range = _feature_explicit_axial_range(feature)
        for center in centers:
            material, material_errors = resolve_axis_material_intervals(
                drawing,
                "Z",
                center,
                exclude_feature_ids={fid},
            )
            if material_errors:
                errors.extend(
                    f"capability_geometry_violation: counterbore {fid!r}: {item}"
                    for item in material_errors
                )
                continue
            normalized = _merge_intervals(material)
            if not normalized:
                errors.append(
                    f"capability_geometry_violation: counterbore {fid!r} has no material"
                )
                continue

            selected = normalized[0]
            if explicit_range is not None:
                through_range = list(explicit_range)
            elif feature.get("through") is True:
                if len(normalized) != 1:
                    errors.append(
                        f"capability_geometry_violation: counterbore {fid!r} crosses "
                        "multiple material intervals without explicit axial range"
                    )
                    continue
                through_range = [selected[0], selected[1]]
            else:
                hole_depth = _num(feature.get("hole_depth"))
                through_range = (
                    _depth_range_from_material_interval(
                        selected,
                        "min",
                        float(hole_depth),
                    )
                    if hole_depth is not None and hole_depth > 0
                    else None
                )
                if through_range is None:
                    errors.append(
                        f"capability_geometry_violation: counterbore {fid!r} requires "
                        "through=true, explicit axial range, or valid hole_depth"
                    )
                    continue

            counterbore_range = _depth_range_from_material_interval(
                selected,
                "min",
                float(counterbore_depth),
            )
            if counterbore_range is None:
                errors.append(
                    f"capability_geometry_violation: counterbore {fid!r} depth exceeds material"
                )
                continue

            geometries.append(
                {
                    "feature_id": fid,
                    "axis": "Z",
                    "transverse_center": center,
                    "side": "min",
                    "material_intervals": normalized,
                    "material_interval": selected,
                    "through_diameter": float(through_diameter),
                    "counterbore_diameter": float(counterbore_diameter),
                    "counterbore_depth": float(counterbore_depth),
                    "through_axial_range": through_range,
                    "counterbore_axial_range": counterbore_range,
                }
            )

    return geometries, errors


def _native_hole_operation_geometry(op: dict) -> dict | None:
    args = op.get("tool_args") or {}
    if op.get("tool") != "nx_hole":
        return None
    center = _axis_transverse_center("Z", args.get("center"))
    diameter = _num(args.get("diameter"))
    depth = _num(args.get("depth"))
    start = _num(args.get("start_offset", 0.0))
    if (
        center is None
        or diameter is None
        or diameter <= 0
        or depth is None
        or depth <= 0
        or start is None
    ):
        return None
    return {
        "step": op.get("step"),
        "axis": "Z",
        "transverse_center": center,
        "diameter": float(diameter),
        "axial_range": [float(start), float(start + depth)],
    }


def hole_plan_errors(
    plan: dict,
    geometries: list[dict],
    *,
    adapter_name: str,
) -> list[str]:
    """Gate B for plain-hole adapters using engineering-coordinate geometry."""
    if not geometries:
        return []

    if adapter_name == "native_z_hole":
        actual = [
            geometry
            for op in plan.get("operations") or []
            if isinstance(op, dict)
            if (geometry := _native_hole_operation_geometry(op)) is not None
        ]
        allowed_axes = {"Z"}
    elif adapter_name == "principal_axis_circular_subtract":
        actual = [
            geometry
            for op in plan.get("operations") or []
            if isinstance(op, dict)
            if (geometry := _subtract_circle_operation_geometry(plan, op)) is not None
        ]
        allowed_axes = {"X", "Y"}
    else:
        return [f"capability_dispatch_violation: unknown hole adapter {adapter_name!r}"]

    errors: list[str] = []
    for expected in geometries:
        if expected.get("axis") not in allowed_axes:
            continue
        fid = str(expected.get("feature_id") or "?")
        for center in expected.get("transverse_centers") or []:
            matches = [
                item
                for item in actual
                if item.get("axis") == expected.get("axis")
                and item.get("transverse_center") == center
                and _drawing_equal(item.get("diameter"), expected.get("diameter"))
            ]
            if len(matches) != 1:
                errors.append(
                    f"hole feature {fid!r} operation count must be 1, got {len(matches)}"
                )
                continue
            actual_range = matches[0].get("axial_range")
            expected_range = expected.get("axial_range")
            if (
                not isinstance(actual_range, list)
                or not isinstance(expected_range, list)
                or len(actual_range) != 2
                or len(expected_range) != 2
                or any(
                    not _drawing_equal(left, right)
                    for left, right in zip(actual_range, expected_range, strict=False)
                )
            ):
                errors.append(
                    f"hole feature {fid!r} changes axial range"
                )
    return errors


def _native_counterbore_operation_geometry(op: dict) -> dict | None:
    args = op.get("tool_args") or {}
    if op.get("tool") != "nx_counterbore_hole":
        return None
    center = _axis_transverse_center("Z", args.get("center"))
    hole_diameter = _num(args.get("hole_diameter"))
    hole_depth = _num(args.get("hole_depth"))
    counterbore_diameter = _num(args.get("counterbore_diameter"))
    counterbore_depth = _num(args.get("counterbore_depth"))
    start = _num(args.get("start_offset", 0.0))
    if (
        center is None
        or hole_diameter is None
        or hole_diameter <= 0
        or hole_depth is None
        or hole_depth <= 0
        or counterbore_diameter is None
        or counterbore_diameter <= hole_diameter
        or counterbore_depth is None
        or counterbore_depth <= 0
        or start is None
    ):
        return None
    return {
        "step": op.get("step"),
        "axis": "Z",
        "transverse_center": center,
        "through_diameter": float(hole_diameter),
        "counterbore_diameter": float(counterbore_diameter),
        "through_axial_range": [float(start), float(start + hole_depth)],
        "counterbore_axial_range": [
            float(start),
            float(start + counterbore_depth),
        ],
    }


def native_counterbore_plan_errors(
    plan: dict,
    geometries: list[dict],
) -> list[str]:
    actual = [
        geometry
        for op in plan.get("operations") or []
        if isinstance(op, dict)
        if (geometry := _native_counterbore_operation_geometry(op)) is not None
    ]
    errors: list[str] = []
    for expected in geometries:
        if expected.get("axis") != "Z":
            continue
        fid = str(expected.get("feature_id") or "?")
        matches = [
            item
            for item in actual
            if item.get("transverse_center") == expected.get("transverse_center")
            and _drawing_equal(
                item.get("through_diameter"),
                expected.get("through_diameter"),
            )
            and _drawing_equal(
                item.get("counterbore_diameter"),
                expected.get("counterbore_diameter"),
            )
        ]
        if len(matches) != 1:
            errors.append(
                f"counterbore feature {fid!r} operation count must be 1, got {len(matches)}"
            )
            continue
        actual_geometry = matches[0]
        for label, key in (
            ("through", "through_axial_range"),
            ("counterbore", "counterbore_axial_range"),
        ):
            actual_range = actual_geometry.get(key)
            expected_range = expected.get(key)
            if (
                not isinstance(actual_range, list)
                or not isinstance(expected_range, list)
                or len(actual_range) != 2
                or len(expected_range) != 2
                or any(
                    not _drawing_equal(left, right)
                    for left, right in zip(actual_range, expected_range, strict=False)
                )
            ):
                errors.append(
                    f"counterbore feature {fid!r} {label} changes axial range"
                )
    return errors


def _adapter_payload(
    capability: dict,
    geometries: list[dict],
    errors: list[str],
    *,
    recipes: list[dict] | None = None,
) -> tuple[dict | None, list[str]]:
    if errors:
        return None, errors
    supported_axes = set(capability.get("supported_axes") or [])
    selected = [
        geometry
        for geometry in geometries
        if geometry.get("axis") in supported_axes
    ]
    feature_ids = {str(item.get("feature_id") or "") for item in selected}
    payload: dict[str, Any] = {
        "implementation_id": capability.get("implementation_id"),
        "planner_adapter": capability.get("planner_adapter"),
        "gate_b_validator": capability.get("gate_b_validator"),
        "feature_kind": capability.get("feature_kind"),
        "supported_axes": list(capability.get("supported_axes") or []),
        "geometries": selected,
    }
    if recipes is not None:
        payload["recipes"] = [
            item for item in recipes if str(item.get("feature_id") or "") in feature_ids
        ]
    return payload, []


def _operation_contract_axial_range(
    value: Any,
    *,
    feature_id: str,
    role: str,
) -> tuple[list[float] | None, list[str]]:
    if not (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(_num(item) is not None for item in value)
    ):
        return None, [
            f"capability_materialization_violation: feature {feature_id!r} "
            f"{role} has no explicit two-value axial range"
        ]
    start = float(_num(value[0]))
    end = float(_num(value[1]))
    if abs(end - start) <= 1e-9:
        return None, [
            f"capability_materialization_violation: feature {feature_id!r} "
            f"{role} has zero axial distance"
        ]
    return [start, end], []


def _native_z_range_args(
    axial_range: Any,
    *,
    feature_id: str,
    role: str,
) -> tuple[dict | None, list[str]]:
    normalized, errors = _operation_contract_axial_range(
        axial_range,
        feature_id=feature_id,
        role=role,
    )
    if errors or normalized is None:
        return None, errors
    start, end = normalized
    if end <= start:
        return None, [
            f"capability_materialization_violation: feature {feature_id!r} "
            f"{role} requires a descending Z range that the native tool cannot represent"
        ]
    return {
        "start_offset": start,
        "depth": end - start,
    }, []


def _principal_axis_range_args(
    axial_range: Any,
    *,
    feature_id: str,
    role: str,
) -> tuple[dict | None, list[str]]:
    normalized, errors = _operation_contract_axial_range(
        axial_range,
        feature_id=feature_id,
        role=role,
    )
    if errors or normalized is None:
        return None, errors
    start, end = normalized
    reverse = end < start
    return {
        "distance": abs(end - start),
        "start_offset": -start if reverse else start,
        "reverse": reverse,
    }, []


def _principal_axis_circle_operation_contract(
    *,
    feature_id: str,
    role: str,
    axis: str,
    center: Any,
    diameter: Any,
    axial_range: Any,
    operation_fields: dict | None = None,
) -> tuple[dict | None, list[str]]:
    plane = {"X": "YZ", "Y": "XZ"}.get(axis)
    transverse = _axis_transverse_center(axis, center)
    diameter_value = _num(diameter)
    if plane is None or transverse is None or diameter_value is None or diameter_value <= 0:
        return None, [
            f"capability_materialization_violation: feature {feature_id!r} "
            f"{role} has invalid principal-axis circle geometry"
        ]
    range_args, errors = _principal_axis_range_args(
        axial_range,
        feature_id=feature_id,
        role=role,
    )
    if errors or range_args is None:
        return None, errors

    final_operation: dict[str, Any] = {
        "tool": "nx_extrude",
        "fixed_args": {
            **range_args,
            "operation": "subtract",
        },
        "requires": ["sketch_id", "target_body_id"],
    }
    if operation_fields:
        final_operation["operation_fields"] = dict(operation_fields)

    return {
        "feature_id": feature_id,
        "role": role,
        "axis": axis,
        "operations": [
            {
                "tool": "nx_create_sketch",
                "fixed_args": {"plane": plane},
            },
            {
                "tool": "nx_sketch_circle",
                "fixed_args": {
                    "center": {
                        "x": transverse[0],
                        "y": transverse[1],
                    },
                    "diameter": float(diameter_value),
                },
                "requires": ["sketch_id"],
            },
            {
                "tool": "nx_finish_sketch",
                "fixed_args": {},
                "requires": ["sketch_id"],
            },
            final_operation,
        ],
    }, []


def _thread_surrogate_operation_fields(geometry: dict) -> dict:
    use: dict[str, Any] = {
        "feature_id": geometry.get("feature_id"),
        "owner_feature_id": geometry.get("owner_feature_id"),
    }
    if (
        geometry.get("material_side") is not None
        or geometry.get("entry_endpoint") is not None
    ):
        use["material_side"] = geometry.get("material_side")
        use["entry_endpoint"] = geometry.get("entry_endpoint")
    elif geometry.get("side") is not None:
        use["side"] = geometry.get("side")
    return {"thread_surrogate_use": use}


def _rotational_profile_geometry(
    drawing: dict,
) -> tuple[dict | None, list[str]]:
    """Normalize one canonical rotational body profile for exact revolve.

    Line and arc primitives are accepted only from canonical engineering
    geometry.  Arc center/radius/angles are never inferred from raster pixels
    here; they must already exist in the canonical drawing.
    """

    profile = drawing.get("profile")
    if not isinstance(profile, dict):
        return None, [
            "capability_adapter_violation: rotational body requires canonical profile"
        ]
    plane = str(profile.get("plane") or "").upper()
    axis = str(profile.get("rotation_axis") or "").upper()
    if plane not in {"XY", "XZ", "YZ"} or axis not in {"X", "Y", "Z"}:
        return None, [
            "capability_adapter_violation: rotational body requires valid profile "
            "plane and rotation_axis"
        ]
    if axis not in plane:
        return None, [
            f"capability_adapter_violation: rotation axis {axis!r} is not in "
            f"profile plane {plane!r}"
        ]

    raw_segments = profile.get("segments")
    if not isinstance(raw_segments, list) or len(raw_segments) < 3:
        return None, [
            "capability_adapter_violation: rotational profile requires at least "
            "three canonical primitives"
        ]

    axes = (plane[0], plane[1])
    axis_index = 0 if axes[0] == axis else 1
    radial_index = 1 - axis_index
    first_axis = axes[0].lower()
    second_axis = axes[1].lower()
    tolerance = 1e-7

    local_segments: list[dict[str, Any]] = []
    axial_values: list[float] = []
    radial_lower_bounds: list[float] = []
    radial_upper_bounds: list[float] = []
    first_start: tuple[float, float] | None = None
    previous_end: tuple[float, float] | None = None

    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            return None, [
                f"capability_adapter_violation: profile segment {index} is not an object"
            ]

        segment_type = str(segment.get("type") or "").lower()
        if segment_type == "line":
            values = [
                _num(segment.get(f"{first_axis}1")),
                _num(segment.get(f"{second_axis}1")),
                _num(segment.get(f"{first_axis}2")),
                _num(segment.get(f"{second_axis}2")),
            ]
            if any(value is None for value in values):
                return None, [
                    f"capability_adapter_violation: profile segment {index} has "
                    "incomplete numeric coordinates"
                ]
            first, second, third, fourth = (
                float(value) for value in values
            )
            start = (first, second)
            end = (third, fourth)
            if math.hypot(
                end[0] - start[0],
                end[1] - start[1],
            ) <= tolerance:
                return None, [
                    f"capability_adapter_violation: profile segment {index} "
                    "has zero length"
                ]
            local_segments.append(
                {
                    "type": "line",
                    "start": {"x": start[0], "y": start[1]},
                    "end": {"x": end[0], "y": end[1]},
                }
            )
            radial_values = [start[radial_index], end[radial_index]]
            axial_values.extend(
                [start[axis_index], end[axis_index]]
            )

        elif segment_type == "arc":
            center = segment.get("center")
            radius = _num(segment.get("radius"))
            start_angle = _num(segment.get("start_angle"))
            end_angle = _num(segment.get("end_angle"))
            if not isinstance(center, dict):
                return None, [
                    f"capability_adapter_violation: profile arc {index} requires "
                    "an engineering center in profile-plane coordinates"
                ]
            center_first = _num(center.get(first_axis))
            center_second = _num(center.get(second_axis))
            if (
                center_first is None
                or center_second is None
                or radius is None
                or radius <= 0
                or start_angle is None
                or end_angle is None
                or not all(
                    math.isfinite(float(value))
                    for value in (
                        center_first,
                        center_second,
                        radius,
                        start_angle,
                        end_angle,
                    )
                )
            ):
                return None, [
                    f"capability_adapter_violation: profile arc {index} has "
                    "incomplete engineering center/radius/angle parameters"
                ]

            center_point = (
                float(center_first),
                float(center_second),
            )
            radius_value = float(radius)
            start_angle_value = float(start_angle)
            end_angle_value = float(end_angle)
            start_radians = math.radians(start_angle_value)
            end_radians = math.radians(end_angle_value)
            start = (
                center_point[0] + radius_value * math.cos(start_radians),
                center_point[1] + radius_value * math.sin(start_radians),
            )
            end = (
                center_point[0] + radius_value * math.cos(end_radians),
                center_point[1] + radius_value * math.sin(end_radians),
            )
            if math.hypot(
                end[0] - start[0],
                end[1] - start[1],
            ) <= tolerance:
                return None, [
                    f"capability_adapter_violation: profile arc {index} has "
                    "zero/full-circle sweep and is not a bounded arc primitive"
                ]

            local_segments.append(
                {
                    "type": "arc",
                    "center": {
                        "x": center_point[0],
                        "y": center_point[1],
                    },
                    "radius": radius_value,
                    "start_angle": start_angle_value,
                    "end_angle": end_angle_value,
                }
            )
            radial_center = center_point[radial_index]
            radial_values = [
                radial_center - radius_value,
                radial_center + radius_value,
            ]
            axial_center = center_point[axis_index]
            axial_values.extend(
                [
                    axial_center - radius_value,
                    axial_center + radius_value,
                ]
            )

        else:
            return None, [
                f"capability_adapter_violation: profile segment {index} uses "
                f"unsupported primitive type {segment_type!r}"
            ]

        if first_start is None:
            first_start = start
        elif previous_end is None or any(
            abs(left - right) > tolerance
            for left, right in zip(previous_end, start, strict=False)
        ):
            return None, [
                f"capability_adapter_violation: profile segment {index} is not "
                "continuous with the previous primitive"
            ]
        previous_end = end
        radial_lower_bounds.append(min(radial_values))
        radial_upper_bounds.append(max(radial_values))

    if (
        first_start is None
        or previous_end is None
        or any(
            abs(left - right) > tolerance
            for left, right in zip(previous_end, first_start, strict=False)
        )
    ):
        return None, [
            "capability_adapter_violation: rotational profile is not closed"
        ]

    if min(radial_lower_bounds) < -tolerance:
        return None, [
            "capability_adapter_violation: canonical rotational meridian crosses "
            "the rotation axis"
        ]
    if max(radial_upper_bounds) <= tolerance:
        return None, [
            "capability_adapter_violation: canonical rotational meridian has no "
            "positive radial extent"
        ]

    axis_min = min(axial_values)
    axis_max = max(axial_values)
    if axis_max - axis_min <= tolerance:
        return None, [
            "capability_adapter_violation: rotational profile has zero axial span"
        ]

    if axis_index == 0:
        axis_start = {"x": axis_min, "y": 0.0}
        axis_end = {"x": axis_max, "y": 0.0}
    else:
        axis_start = {"x": 0.0, "y": axis_min}
        axis_end = {"x": 0.0, "y": axis_max}

    return {
        "feature_id": "BODY_PROFILE",
        "axis": axis,
        "plane": plane,
        "representation": "canonical_rotational_profile",
        "segments": local_segments,
        "axis_start": axis_start,
        "axis_end": axis_end,
        "angle": 360.0,
    }, []


def _rotational_profile_operation_contract(
    geometry: dict,
) -> tuple[dict | None, list[str]]:
    feature_id = str(geometry.get("feature_id") or "BODY_PROFILE")
    plane = str(geometry.get("plane") or "").upper()
    axis = str(geometry.get("axis") or "").upper()
    segments = geometry.get("segments")
    axis_start = geometry.get("axis_start")
    axis_end = geometry.get("axis_end")
    angle = _num(geometry.get("angle"))
    if (
        plane not in {"XY", "XZ", "YZ"}
        or axis not in {"X", "Y", "Z"}
        or axis not in plane
        or not isinstance(segments, list)
        or len(segments) < 3
        or not isinstance(axis_start, dict)
        or not isinstance(axis_end, dict)
        or angle is None
        or angle <= 0
        or angle > 360
    ):
        return None, [
            f"capability_materialization_violation: rotational body "
            f"{feature_id!r} geometry is incomplete"
        ]

    operations: list[dict[str, Any]] = [
        {
            "tool": "nx_create_sketch",
            "fixed_args": {"plane": plane},
        }
    ]
    for segment_index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            return None, [
                f"capability_materialization_violation: rotational body "
                f"{feature_id!r} has malformed profile segment"
            ]

        segment_type = str(segment.get("type") or "").lower()
        if segment_type == "line":
            start = segment.get("start")
            end = segment.get("end")
            if not isinstance(start, dict) or not isinstance(end, dict):
                return None, [
                    f"capability_materialization_violation: rotational body "
                    f"{feature_id!r} has malformed line coordinates"
                ]
            operations.append(
                {
                    "tool": "nx_sketch_line",
                    "fixed_args": {
                        "start": copy.deepcopy(start),
                        "end": copy.deepcopy(end),
                    },
                    "requires": ["sketch_id"],
                }
            )
            continue

        if segment_type == "arc":
            center = segment.get("center")
            radius = _num(segment.get("radius"))
            start_angle = _num(segment.get("start_angle"))
            end_angle = _num(segment.get("end_angle"))
            if (
                not isinstance(center, dict)
                or radius is None
                or radius <= 0
                or start_angle is None
                or end_angle is None
                or not all(
                    _num(center.get(key)) is not None
                    for key in ("x", "y")
                )
            ):
                return None, [
                    f"capability_materialization_violation: rotational body "
                    f"{feature_id!r} arc {segment_index} is incomplete"
                ]
            operations.append(
                {
                    "tool": "nx_sketch_arc",
                    "fixed_args": {
                        "center": copy.deepcopy(center),
                        "radius": float(radius),
                        "start_angle": float(start_angle),
                        "end_angle": float(end_angle),
                    },
                    "requires": ["sketch_id"],
                }
            )
            continue

        return None, [
            f"capability_materialization_violation: rotational body "
            f"{feature_id!r} uses unsupported profile primitive "
            f"{segment_type!r}"
        ]

    operations.extend(
        [
            {
                "tool": "nx_finish_sketch",
                "fixed_args": {},
                "requires": ["sketch_id"],
            },
            {
                "tool": "nx_revolve",
                "fixed_args": {
                    "axis_start": copy.deepcopy(axis_start),
                    "axis_end": copy.deepcopy(axis_end),
                    "angle": float(angle),
                    "reverse": False,
                },
                "requires": ["sketch_id"],
            },
        ]
    )
    return {
        "feature_id": feature_id,
        "role": "rotational_body",
        "axis": axis,
        "representation": "canonical_rotational_profile",
        "operations": operations,
    }, []


def materialize_capability_operation_contracts(
    capability: dict,
    payload: dict,
) -> tuple[list[dict], list[str]]:
    """Materialize geometry-critical operation recipes; Planner owns only wiring/order."""
    adapter_name = str(capability.get("planner_adapter") or "")
    geometries = [
        item for item in payload.get("geometries") or [] if isinstance(item, dict)
    ]
    recipes = {
        str(item.get("feature_id") or ""): item
        for item in payload.get("recipes") or []
        if isinstance(item, dict)
    }
    contracts: list[dict] = []
    errors: list[str] = []

    for geometry in geometries:
        feature_id = str(geometry.get("feature_id") or "?")
        axis = str(geometry.get("axis") or "").upper()

        if adapter_name == "rotational_profile_revolve":
            contract, contract_errors = _rotational_profile_operation_contract(
                geometry
            )
            errors.extend(contract_errors)
            if contract is not None:
                contracts.append(contract)
            continue

        if adapter_name == "native_z_hole":
            for center in geometry.get("transverse_centers") or []:
                transverse = _axis_transverse_center("Z", center)
                diameter = _num(geometry.get("diameter"))
                range_args, range_errors = _native_z_range_args(
                    geometry.get("axial_range"),
                    feature_id=feature_id,
                    role="hole",
                )
                if (
                    transverse is None
                    or diameter is None
                    or diameter <= 0
                    or range_errors
                    or range_args is None
                ):
                    errors.extend(range_errors)
                    if not range_errors:
                        errors.append(
                            f"capability_materialization_violation: hole "
                            f"{feature_id!r} has invalid native-Z geometry"
                        )
                    continue
                contracts.append(
                    {
                        "feature_id": feature_id,
                        "role": "hole",
                        "axis": "Z",
                        "operations": [
                            {
                                "tool": "nx_hole",
                                "fixed_args": {
                                    "center": {
                                        "x": transverse[0],
                                        "y": transverse[1],
                                    },
                                    "diameter": float(diameter),
                                    "depth": range_args["depth"],
                                    "start_offset": range_args["start_offset"],
                                },
                                "requires": ["body_id"],
                            }
                        ],
                    }
                )
            continue

        if adapter_name == "principal_axis_circular_subtract":
            if geometry.get("representation") == "continuous_hole_slot_profile":
                contract, contract_errors = (
                    _continuous_hole_slot_operation_contract(
                        geometry,
                    )
                )
                errors.extend(contract_errors)
                if contract is not None:
                    contracts.append(contract)
                continue

            for center in geometry.get("transverse_centers") or []:
                contract, contract_errors = _principal_axis_circle_operation_contract(
                    feature_id=feature_id,
                    role="hole",
                    axis=axis,
                    center=center,
                    diameter=geometry.get("diameter"),
                    axial_range=geometry.get("axial_range"),
                )
                errors.extend(contract_errors)
                if contract is not None:
                    contracts.append(contract)
            continue

        if adapter_name == "native_z_counterbore":
            center = geometry.get("transverse_center")
            transverse = _axis_transverse_center("Z", center)
            through_diameter = _num(geometry.get("through_diameter"))
            counterbore_diameter = _num(geometry.get("counterbore_diameter"))
            through_args, through_errors = _native_z_range_args(
                geometry.get("through_axial_range"),
                feature_id=feature_id,
                role="counterbore through",
            )
            recess_args, recess_errors = _native_z_range_args(
                geometry.get("counterbore_axial_range"),
                feature_id=feature_id,
                role="counterbore recess",
            )
            errors.extend(through_errors)
            errors.extend(recess_errors)
            if (
                transverse is None
                or through_diameter is None
                or through_diameter <= 0
                or counterbore_diameter is None
                or counterbore_diameter <= through_diameter
                or through_args is None
                or recess_args is None
            ):
                if not through_errors and not recess_errors:
                    errors.append(
                        f"capability_materialization_violation: counterbore "
                        f"{feature_id!r} has invalid native-Z geometry"
                    )
                continue
            if not _drawing_equal(
                through_args["start_offset"],
                recess_args["start_offset"],
            ):
                errors.append(
                    f"capability_materialization_violation: counterbore "
                    f"{feature_id!r} native-Z ranges have different entry offsets"
                )
                continue
            contracts.append(
                {
                    "feature_id": feature_id,
                    "role": "counterbore",
                    "axis": "Z",
                    "operations": [
                        {
                            "tool": "nx_counterbore_hole",
                            "fixed_args": {
                                "center": {
                                    "x": transverse[0],
                                    "y": transverse[1],
                                },
                                "hole_diameter": float(through_diameter),
                                "hole_depth": through_args["depth"],
                                "counterbore_diameter": float(counterbore_diameter),
                                "counterbore_depth": recess_args["depth"],
                                "start_offset": through_args["start_offset"],
                            },
                            "requires": ["body_id"],
                        }
                    ],
                }
            )
            continue

        if adapter_name == "principal_axis_counterbore":
            for role, diameter_key, range_key in (
                ("through", "through_diameter", "through_axial_range"),
                (
                    "counterbore",
                    "counterbore_diameter",
                    "counterbore_axial_range",
                ),
            ):
                contract, contract_errors = _principal_axis_circle_operation_contract(
                    feature_id=feature_id,
                    role=role,
                    axis=axis,
                    center=geometry.get("transverse_center"),
                    diameter=geometry.get(diameter_key),
                    axial_range=geometry.get(range_key),
                )
                errors.extend(contract_errors)
                if contract is not None:
                    contracts.append(contract)
            continue

        if adapter_name == "metric_thread_surrogate":
            if geometry.get("representation") == "subsumed_by_coaxial_through_hole":
                contracts.append(
                    {
                        "feature_id": feature_id,
                        "role": "thread_surrogate",
                        "axis": axis,
                        "representation": "subsumed_by_coaxial_through_hole",
                        "subsumed_by_feature_id": geometry.get(
                            "subsumed_by_feature_id"
                        ),
                        "operations": [],
                    }
                )
                continue

            recipe = recipes.get(feature_id)
            surrogate_diameter = (
                _num(recipe.get("surrogate_diameter")) if recipe is not None else None
            )
            if surrogate_diameter is None or surrogate_diameter <= 0:
                errors.append(
                    f"capability_materialization_violation: thread "
                    f"{feature_id!r} has no surrogate diameter"
                )
                continue
            operation_fields = _thread_surrogate_operation_fields(geometry)
            for center in geometry.get("transverse_centers") or []:
                if axis == "Z":
                    transverse = _axis_transverse_center("Z", center)
                    range_args, range_errors = _native_z_range_args(
                        geometry.get("axial_range"),
                        feature_id=feature_id,
                        role="thread surrogate",
                    )
                    errors.extend(range_errors)
                    if (
                        transverse is None
                        or range_args is None
                    ):
                        if not range_errors:
                            errors.append(
                                f"capability_materialization_violation: thread "
                                f"{feature_id!r} has invalid native-Z center"
                            )
                        continue
                    contracts.append(
                        {
                            "feature_id": feature_id,
                            "role": "thread_surrogate",
                            "axis": "Z",
                            "operations": [
                                {
                                    "tool": "nx_hole",
                                    "fixed_args": {
                                        "center": {
                                            "x": transverse[0],
                                            "y": transverse[1],
                                        },
                                        "diameter": float(surrogate_diameter),
                                        "depth": range_args["depth"],
                                        "start_offset": range_args["start_offset"],
                                    },
                                    "requires": ["body_id"],
                                    "operation_fields": operation_fields,
                                }
                            ],
                        }
                    )
                else:
                    contract, contract_errors = (
                        _principal_axis_circle_operation_contract(
                            feature_id=feature_id,
                            role="thread_surrogate",
                            axis=axis,
                            center=center,
                            diameter=surrogate_diameter,
                            axial_range=geometry.get("axial_range"),
                            operation_fields=operation_fields,
                        )
                    )
                    errors.extend(contract_errors)
                    if contract is not None:
                        contracts.append(contract)
            continue

        errors.append(
            f"capability_materialization_violation: planner_adapter "
            f"{adapter_name!r} has no operation materializer"
        )

    return contracts, errors


def _principal_hole_continuous_slot_compositions(
    drawing: dict,
    geometries: list[dict],
) -> tuple[list[dict], list[str]]:
    """Mark point-tangent principal-axis hole/slot pairs for one-profile subtract."""
    output = copy.deepcopy(geometries)
    errors: list[str] = []

    for geometry in output:
        axis = str(geometry.get("axis") or "").upper()
        if axis not in {"X", "Y"}:
            continue
        centers = geometry.get("transverse_centers") or []
        if len(centers) != 1:
            continue

        feature_id = str(geometry.get("feature_id") or "?")
        center = centers[0]
        if not (
            isinstance(center, (list, tuple))
            and len(center) == 2
            and all(_num(value) is not None for value in center)
        ):
            continue
        diameter = _num(geometry.get("diameter"))
        if diameter is None or diameter <= 0:
            continue

        width_axis = "Y" if axis == "X" else "X"
        width_coordinate = float(_num(center[0]))
        center_z = float(_num(center[1]))
        radius = float(diameter) / 2.0
        matches: list[dict] = []

        for feature in drawing.get("features") or []:
            if not isinstance(feature, dict):
                continue
            if feature.get("required_for_modeling") is False:
                continue
            if str(feature.get("type") or "").lower() not in {"slot", "slit", "cut"}:
                continue
            if str(feature.get("through_axis") or "").upper() != axis:
                continue
            if str(feature.get("width_axis") or "").upper() != width_axis:
                continue

            width = _num(feature.get("width"))
            slot_center = _num(
                _drawing_feature_coord(feature, width_axis.lower())
            )
            bottom_z = _num(feature.get("bottom_z"))
            top_z = _num(feature.get("top_z"))
            if (
                width is None
                or width <= 0
                or width >= float(diameter)
                or slot_center is None
                or bottom_z is None
                or top_z is None
                or top_z <= bottom_z
                or not _drawing_equal(slot_center, width_coordinate)
                or not _drawing_equal(bottom_z, center_z + radius)
            ):
                continue

            half_width = float(width) / 2.0
            join_delta = math.sqrt(max(0.0, radius * radius - half_width * half_width))
            join_z = center_z + join_delta
            if top_z <= join_z + 1e-9:
                continue

            matches.append(
                {
                    "feature_id": str(feature.get("id") or "?"),
                    "through_axis": axis,
                    "width_axis": width_axis,
                    "width": float(width),
                    "center": float(slot_center),
                    "bottom_z": float(bottom_z),
                    "top_z": float(top_z),
                    "join_z": float(join_z),
                }
            )

        if len(matches) > 1:
            errors.append(
                f"capability_composition_violation: hole {feature_id!r} has "
                "multiple point-tangent continuous slot candidates"
            )
            continue
        if not matches:
            continue

        slot = matches[0]
        geometry["representation"] = "continuous_hole_slot_profile"
        geometry["composed_feature_ids"] = [
            feature_id,
            slot["feature_id"],
        ]
        geometry["continuous_slot"] = slot

    return output, errors


def _continuous_hole_slot_operation_contract(
    geometry: dict,
) -> tuple[dict | None, list[str]]:
    feature_id = str(geometry.get("feature_id") or "?")
    axis = str(geometry.get("axis") or "").upper()
    plane = {"X": "YZ", "Y": "XZ"}.get(axis)
    centers = geometry.get("transverse_centers") or []
    slot = geometry.get("continuous_slot")
    diameter = _num(geometry.get("diameter"))
    if (
        plane is None
        or len(centers) != 1
        or not isinstance(slot, dict)
        or diameter is None
        or diameter <= 0
    ):
        return None, [
            f"capability_materialization_violation: continuous hole-slot "
            f"feature {feature_id!r} is incomplete"
        ]

    center = centers[0]
    transverse = _axis_transverse_center(axis, center)
    width = _num(slot.get("width"))
    slot_center = _num(slot.get("center"))
    top_z = _num(slot.get("top_z"))
    join_z = _num(slot.get("join_z"))
    if (
        transverse is None
        or width is None
        or width <= 0
        or slot_center is None
        or top_z is None
        or join_z is None
    ):
        return None, [
            f"capability_materialization_violation: continuous hole-slot "
            f"feature {feature_id!r} has invalid slot geometry"
        ]

    range_args, range_errors = _principal_axis_range_args(
        geometry.get("axial_range"),
        feature_id=feature_id,
        role="continuous hole-slot cut",
    )
    if range_errors or range_args is None:
        return None, range_errors

    radius = float(diameter) / 2.0
    half_width = float(width) / 2.0
    if half_width >= radius:
        return None, [
            f"capability_materialization_violation: continuous hole-slot "
            f"feature {feature_id!r} slot width does not intersect the circle sides"
        ]

    angle_right = math.degrees(
        math.atan2(float(join_z) - float(transverse[1]), half_width)
    )
    angle_left = 180.0 - angle_right
    left_x = float(slot_center) - half_width
    right_x = float(slot_center) + half_width
    center_local = {
        "x": float(transverse[0]),
        "y": float(transverse[1]),
    }

    operations = [
        {
            "tool": "nx_create_sketch",
            "fixed_args": {"plane": plane},
        },
        {
            "tool": "nx_sketch_line",
            "fixed_args": {
                "start": {"x": left_x, "y": float(top_z)},
                "end": {"x": right_x, "y": float(top_z)},
            },
            "requires": ["sketch_id"],
        },
        {
            "tool": "nx_sketch_line",
            "fixed_args": {
                "start": {"x": right_x, "y": float(top_z)},
                "end": {"x": right_x, "y": float(join_z)},
            },
            "requires": ["sketch_id"],
        },
    ]
    for start_angle, end_angle in (
        (angle_left, 180.0),
        (180.0, 270.0),
        (270.0, 360.0),
        (0.0, angle_right),
    ):
        operations.append(
            {
                "tool": "nx_sketch_arc",
                "fixed_args": {
                    "center": dict(center_local),
                    "radius": radius,
                    "start_angle": start_angle,
                    "end_angle": end_angle,
                },
                "requires": ["sketch_id"],
            }
        )
    operations.extend(
        [
            {
                "tool": "nx_sketch_line",
                "fixed_args": {
                    "start": {"x": left_x, "y": float(join_z)},
                    "end": {"x": left_x, "y": float(top_z)},
                },
                "requires": ["sketch_id"],
            },
            {
                "tool": "nx_finish_sketch",
                "fixed_args": {},
                "requires": ["sketch_id"],
            },
            {
                "tool": "nx_extrude",
                "fixed_args": {
                    **range_args,
                    "operation": "subtract",
                },
                "requires": ["sketch_id", "target_body_id"],
            },
        ]
    )
    return {
        "feature_id": feature_id,
        "role": "continuous_hole_slot_cut",
        "axis": axis,
        "representation": "continuous_hole_slot_profile",
        "composed_feature_ids": list(
            geometry.get("composed_feature_ids") or []
        ),
        "operations": operations,
    }, []


def _contract_value_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            return False
        return all(
            _contract_value_equal(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return _drawing_equal(actual, expected)
    return actual == expected


def _operation_matches_fixed_args(
    op: dict,
    expected: dict,
) -> bool:
    if op.get("tool") != expected.get("tool"):
        return False
    actual_args = op.get("tool_args") or {}
    fixed_args = expected.get("fixed_args") or {}
    requires = expected.get("requires") or []
    if (
        not isinstance(actual_args, dict)
        or not isinstance(fixed_args, dict)
        or not isinstance(requires, list)
        or not all(isinstance(item, str) and item for item in requires)
    ):
        return False
    allowed_keys = set(fixed_args) | set(requires)
    if set(actual_args) != allowed_keys:
        return False
    actual_fixed = {
        key: actual_args[key]
        for key in fixed_args
    }
    return _contract_value_equal(actual_fixed, fixed_args)


def _continuous_hole_slot_plan_errors(
    plan: dict,
    contract: dict,
) -> list[str]:
    feature_id = str(contract.get("feature_id") or "?")
    expected_operations = contract.get("operations") or []
    expected_profile = [
        item
        for item in expected_operations
        if item.get("tool") in {"nx_sketch_line", "nx_sketch_arc"}
    ]
    expected_create = next(
        (
            item
            for item in expected_operations
            if item.get("tool") == "nx_create_sketch"
        ),
        None,
    )
    expected_extrude = next(
        (
            item
            for item in reversed(expected_operations)
            if item.get("tool") == "nx_extrude"
        ),
        None,
    )
    if expected_create is None or expected_extrude is None:
        return [
            f"capability_dispatch_violation: continuous hole-slot contract "
            f"{feature_id!r} is incomplete"
        ]

    operations = plan.get("operations") or []
    matches = 0
    for index, op in enumerate(operations):
        if not isinstance(op, dict):
            continue
        if not _operation_matches_fixed_args(op, expected_extrude):
            continue

        sketch_id = (op.get("tool_args") or {}).get("sketch_id")
        if not isinstance(sketch_id, str) or not sketch_id:
            continue

        profile_ops = [
            candidate
            for candidate in operations[:index]
            if isinstance(candidate, dict)
            and candidate.get("tool") in {"nx_sketch_line", "nx_sketch_arc"}
            and (candidate.get("tool_args") or {}).get("sketch_id") == sketch_id
        ]
        if len(profile_ops) != len(expected_profile):
            continue
        if any(
            not _operation_matches_fixed_args(actual, expected)
            for actual, expected in zip(
                profile_ops,
                expected_profile,
                strict=False,
            )
        ):
            continue

        first_profile_index = operations.index(profile_ops[0])
        creates = [
            candidate
            for candidate in operations[:first_profile_index]
            if isinstance(candidate, dict)
            and candidate.get("tool") == "nx_create_sketch"
        ]
        if not creates:
            continue
        if not _operation_matches_fixed_args(creates[-1], expected_create):
            continue
        matches += 1

    if matches != 1:
        return [
            f"hole feature {feature_id!r} continuous profile operation count "
            f"must be 1, got {matches}"
        ]
    return []


def _planner_adapter_rotational_profile_revolve(
    drawing: dict,
    capability: dict,
) -> tuple[dict | None, list[str]]:
    geometry, errors = _rotational_profile_geometry(drawing)
    if errors or geometry is None:
        return None, errors
    supported_axes = {
        str(item).upper()
        for item in capability.get("supported_axes") or []
    }
    if geometry["axis"] not in supported_axes:
        return None, [
            f"capability_adapter_violation: rotational body axis "
            f"{geometry['axis']!r} is unsupported"
        ]
    return _adapter_payload(capability, [geometry], [])


def _rotational_profile_plan_errors(
    plan: dict,
    contract: dict,
) -> list[str]:
    feature_id = str(contract.get("feature_id") or "BODY_PROFILE")
    expected_operations = contract.get("operations")
    if not isinstance(expected_operations, list) or len(expected_operations) < 5:
        return [
            f"capability_dispatch_violation: rotational body contract "
            f"{feature_id!r} is incomplete"
        ]

    expected_create = expected_operations[0]
    expected_profile_ops = expected_operations[1:-2]
    expected_finish = expected_operations[-2]
    expected_revolve = expected_operations[-1]
    operations = plan.get("operations") or []
    matches = 0

    for revolve_index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            continue
        if not _operation_matches_fixed_args(operation, expected_revolve):
            continue
        revolve_args = operation.get("tool_args") or {}
        sketch_id = revolve_args.get("sketch_id")
        if not isinstance(sketch_id, str) or not sketch_id:
            continue

        prior = operations[:revolve_index]
        finishes = [
            (index, candidate)
            for index, candidate in enumerate(prior)
            if isinstance(candidate, dict)
            and candidate.get("tool") == "nx_finish_sketch"
            and (candidate.get("tool_args") or {}).get("sketch_id") == sketch_id
        ]
        if len(finishes) != 1:
            continue
        finish_index, finish_op = finishes[0]
        if not _operation_matches_fixed_args(finish_op, expected_finish):
            continue

        profile_ops = [
            candidate
            for candidate in prior[:finish_index]
            if isinstance(candidate, dict)
            and candidate.get("tool") in {"nx_sketch_line", "nx_sketch_arc"}
            and (candidate.get("tool_args") or {}).get("sketch_id") == sketch_id
        ]
        if len(profile_ops) != len(expected_profile_ops):
            continue
        if any(
            not _operation_matches_fixed_args(actual, expected)
            for actual, expected in zip(
                profile_ops,
                expected_profile_ops,
                strict=False,
            )
        ):
            continue

        first_profile_index = prior.index(profile_ops[0])
        creates = [
            candidate
            for candidate in prior[:first_profile_index]
            if isinstance(candidate, dict)
            and candidate.get("tool") == "nx_create_sketch"
        ]
        if not creates or not _operation_matches_fixed_args(
            creates[-1], expected_create
        ):
            continue
        matches += 1

    if matches != 1:
        return [
            f"rotational body {feature_id!r} exact revolve operation count "
            f"must be 1, got {matches}"
        ]
    return []


def _gate_b_rotational_profile_revolve_geometry(
    plan: dict,
    payload: dict,
) -> list[str]:
    contracts = [
        item
        for item in payload.get("operation_contracts") or []
        if isinstance(item, dict)
        and item.get("role") == "rotational_body"
    ]
    if len(contracts) != 1:
        return [
            "capability_dispatch_violation: rotational body requires exactly "
            "one operation contract"
        ]
    return _rotational_profile_plan_errors(plan, contracts[0])


def _planner_adapter_native_z_hole(
    drawing: dict,
    capability: dict,
) -> tuple[dict | None, list[str]]:
    geometries, errors = resolve_hole_drawing_geometries(
        drawing,
        axes=set(capability.get("supported_axes") or []),
    )
    return _adapter_payload(capability, geometries, errors)


def _planner_adapter_principal_axis_circular_subtract(
    drawing: dict,
    capability: dict,
) -> tuple[dict | None, list[str]]:
    geometries, errors = resolve_hole_drawing_geometries(
        drawing,
        axes=set(capability.get("supported_axes") or []),
    )
    if errors:
        return None, errors
    geometries, composition_errors = (
        _principal_hole_continuous_slot_compositions(
            drawing,
            geometries,
        )
    )
    return _adapter_payload(
        capability,
        geometries,
        composition_errors,
    )


def _planner_adapter_native_z_counterbore(
    drawing: dict,
    capability: dict,
) -> tuple[dict | None, list[str]]:
    geometries, errors = resolve_counterbore_drawing_geometries(
        drawing,
        axes=set(capability.get("supported_axes") or []),
    )
    return _adapter_payload(capability, geometries, errors)


def _planner_adapter_principal_axis_counterbore(
    drawing: dict,
    capability: dict,
) -> tuple[dict | None, list[str]]:
    geometries, errors = resolve_counterbore_drawing_geometries(
        drawing,
        axes=set(capability.get("supported_axes") or []),
    )
    return _adapter_payload(capability, geometries, errors)


def _planner_adapter_metric_thread_surrogate(
    drawing: dict,
    capability: dict,
) -> tuple[dict | None, list[str]]:
    axes = set(capability.get("supported_axes") or [])
    geometries, geometry_errors = resolve_thread_drawing_geometries(
        drawing,
        axes=axes,
    )
    recipes, recipe_errors = resolve_thread_surrogates(
        drawing,
        axes=axes,
    )
    return _adapter_payload(
        capability,
        geometries,
        [*geometry_errors, *recipe_errors],
        recipes=recipes,
    )


def _gate_b_native_hole_geometry(
    plan: dict,
    payload: dict,
) -> list[str]:
    return hole_plan_errors(
        plan,
        payload.get("geometries") or [],
        adapter_name="native_z_hole",
    )


def _gate_b_circular_subtract_geometry(
    plan: dict,
    payload: dict,
) -> list[str]:
    geometries = [
        item
        for item in payload.get("geometries") or []
        if isinstance(item, dict)
    ]
    simple_geometries = [
        item
        for item in geometries
        if item.get("representation") != "continuous_hole_slot_profile"
    ]
    errors = hole_plan_errors(
        plan,
        simple_geometries,
        adapter_name="principal_axis_circular_subtract",
    )

    contracts = [
        item
        for item in payload.get("operation_contracts") or []
        if isinstance(item, dict)
        and item.get("representation") == "continuous_hole_slot_profile"
    ]
    for contract in contracts:
        errors.extend(
            _continuous_hole_slot_plan_errors(
                plan,
                contract,
            )
        )
    composite_ids = {
        str(item.get("feature_id") or "")
        for item in geometries
        if item.get("representation") == "continuous_hole_slot_profile"
    }
    contract_ids = {
        str(item.get("feature_id") or "")
        for item in contracts
    }
    if composite_ids != contract_ids:
        errors.append(
            "capability_dispatch_violation: continuous hole-slot geometry/"
            "operation-contract feature sets differ"
        )
    return errors


def _gate_b_native_counterbore_geometry(
    plan: dict,
    payload: dict,
) -> list[str]:
    return native_counterbore_plan_errors(
        plan,
        payload.get("geometries") or [],
    )


def _gate_b_transverse_recess_geometry(
    plan: dict,
    payload: dict,
) -> list[str]:
    return transverse_recess_plan_errors(
        plan,
        payload.get("geometries") or [],
    )


def _gate_b_thread_surrogate(
    plan: dict,
    payload: dict,
) -> list[str]:
    return thread_surrogate_plan_errors(
        plan,
        payload.get("recipes") or [],
        payload.get("geometries") or [],
    )


PLANNER_ADAPTER_HANDLER_MAP: dict[
    str,
    Callable[[dict, dict], tuple[dict | None, list[str]]],
] = {
    "rotational_profile_revolve": _planner_adapter_rotational_profile_revolve,
    "native_z_hole": _planner_adapter_native_z_hole,
    "principal_axis_circular_subtract": (
        _planner_adapter_principal_axis_circular_subtract
    ),
    "native_z_counterbore": _planner_adapter_native_z_counterbore,
    "principal_axis_counterbore": _planner_adapter_principal_axis_counterbore,
    "metric_thread_surrogate": _planner_adapter_metric_thread_surrogate,
}

GATE_B_VALIDATOR_HANDLER_MAP: dict[
    str,
    Callable[[dict, dict], list[str]],
] = {
    "rotational_profile_revolve_geometry": (
        _gate_b_rotational_profile_revolve_geometry
    ),
    "native_hole_geometry": _gate_b_native_hole_geometry,
    "circular_subtract_geometry": _gate_b_circular_subtract_geometry,
    "native_counterbore_geometry": _gate_b_native_counterbore_geometry,
    "transverse_recess_geometry": _gate_b_transverse_recess_geometry,
    "thread_surrogate": _gate_b_thread_surrogate,
}


def resolve_capability_handlers(
    capability: dict,
) -> tuple[
    Callable[[dict, dict], tuple[dict | None, list[str]]] | None,
    Callable[[dict, dict], list[str]] | None,
    list[str],
]:
    """Resolve a capability declaration to concrete executable handlers."""
    adapter_name = str(capability.get("planner_adapter") or "")
    validator_name = str(capability.get("gate_b_validator") or "")
    adapter = PLANNER_ADAPTER_HANDLER_MAP.get(adapter_name)
    validator = GATE_B_VALIDATOR_HANDLER_MAP.get(validator_name)
    errors: list[str] = []
    if adapter is None:
        errors.append(
            f"capability_dispatch_violation: planner_adapter {adapter_name!r} is not executable"
        )
    if validator is None:
        errors.append(
            f"capability_dispatch_violation: gate_b_validator {validator_name!r} is not executable"
        )
    return adapter, validator, errors


def dispatch_planner_adapter(
    capability: dict,
    drawing: dict,
) -> tuple[dict | None, list[str]]:
    adapter, _, errors = resolve_capability_handlers(capability)
    if errors or adapter is None:
        return None, errors

    payload, adapter_errors = adapter(drawing, capability)
    if adapter_errors or payload is None:
        return payload, adapter_errors

    operation_contracts, materialization_errors = (
        materialize_capability_operation_contracts(
            capability,
            payload,
        )
    )
    if materialization_errors:
        return None, materialization_errors
    payload["operation_contracts"] = operation_contracts
    return payload, []


def dispatch_gate_b_validator(
    capability: dict,
    plan: dict,
    adapter_payload: dict,
) -> list[str]:
    _, validator, errors = resolve_capability_handlers(capability)
    if errors or validator is None:
        return errors
    if adapter_payload.get("implementation_id") != capability.get("implementation_id"):
        return [
            "capability_dispatch_violation: adapter payload implementation_id "
            "does not match selected capability"
        ]
    return validator(plan, adapter_payload)



def _capability_feature_kind(feature: dict) -> str:
    kind = str(feature.get("type") or feature.get("kind") or "").lower()
    if kind == "through_hole":
        return "hole"
    return kind


def resolve_drawing_capability_dispatches(
    drawing: dict,
    *,
    registry: dict[str, Any] | None = None,
) -> tuple[list[dict], list[str]]:
    """Select one implementation per supported Feature Contract and bind handlers."""
    data = registry if registry is not None else load_modeling_capability_registry()
    registry_errors = capability_registry_errors(data)
    if registry_errors:
        return [], registry_errors

    supported_feature_kinds = {
        str(item.get("feature_kind") or "")
        for item in data.get("implementations", [])
        if isinstance(item, dict)
    }
    selected: dict[str, dict] = {}
    required_supported_features: dict[str, str] = {}
    errors: list[str] = []

    profile = drawing.get("profile")
    if isinstance(profile, dict) and profile.get("rotation_axis") is not None:
        feature_kind = "rotational_body"
        axis = str(profile.get("rotation_axis") or "").upper()
        if feature_kind in supported_feature_kinds:
            candidates, resolution_errors = resolve_modeling_capabilities(
                feature_kind,
                axis,
                registry=data,
            )
            if resolution_errors:
                errors.extend(
                    "capability_selection_violation: profile rotational body: "
                    + item
                    for item in resolution_errors
                )
            else:
                capability = candidates[0]
                implementation_id = str(
                    capability.get("implementation_id") or ""
                )
                selected[implementation_id] = capability

    for feature in drawing.get("features") or []:
        if not isinstance(feature, dict):
            continue
        if feature.get("required_for_modeling") is False:
            continue

        feature_kind = _capability_feature_kind(feature)
        fid = str(feature.get("id") or "?")
        known_subtractive = (
            feature_kind in _SUBTRACTIVE_MODELING_FEATURE_TYPES
            or "hole" in feature_kind
        )
        if feature_kind not in supported_feature_kinds:
            if known_subtractive:
                errors.append(
                    "capability_selection_violation: "
                    f"feature {fid!r}: no modeling capability for "
                    f"required feature_kind={feature_kind!r}"
                )
            continue

        required_supported_features[fid] = feature_kind

        axis = str(feature.get("axis") or "").upper()
        candidates, resolution_errors = resolve_modeling_capabilities(
            feature_kind,
            axis,
            registry=data,
        )
        if resolution_errors:
            errors.extend(
                f"capability_selection_violation: feature {fid!r}: {item}"
                for item in resolution_errors
            )
            continue

        capability = candidates[0]
        implementation_id = str(capability.get("implementation_id") or "")
        previous = selected.get(implementation_id)
        if previous is not None and previous != capability:
            errors.append(
                f"capability_selection_violation: implementation_id "
                f"{implementation_id!r} resolved inconsistently"
            )
            continue
        selected[implementation_id] = capability

    if errors:
        return [], errors

    dispatches: list[dict] = []
    for implementation_id in sorted(selected):
        capability = selected[implementation_id]
        payload, adapter_errors = dispatch_planner_adapter(capability, drawing)
        if adapter_errors:
            errors.extend(
                f"capability_adapter_violation: {implementation_id}: {item}"
                for item in adapter_errors
            )
            continue
        if payload is None:
            errors.append(
                f"capability_adapter_violation: {implementation_id}: "
                "adapter returned no payload"
            )
            continue
        dispatches.append(
            {
                "capability": capability,
                "payload": payload,
            }
        )

    geometry_feature_ids: set[str] = set()
    operation_feature_ids: set[str] = set()
    for dispatch in dispatches:
        payload = dispatch.get("payload")
        if not isinstance(payload, dict):
            continue
        geometry_feature_ids.update(
            str(item.get("feature_id") or "")
            for item in payload.get("geometries") or []
            if isinstance(item, dict) and item.get("feature_id")
        )
        operation_feature_ids.update(
            str(item.get("feature_id") or "")
            for item in payload.get("operation_contracts") or []
            if isinstance(item, dict) and item.get("feature_id")
        )

    for fid, feature_kind in sorted(required_supported_features.items()):
        if fid not in geometry_feature_ids:
            errors.append(
                "capability_materialization_violation: "
                f"required feature {fid!r} ({feature_kind}) is missing from "
                "adapter geometry payload"
            )
            continue
        if fid not in operation_feature_ids:
            errors.append(
                "capability_materialization_violation: "
                f"required feature {fid!r} ({feature_kind}) is missing from "
                "operation contracts"
            )

    if errors:
        return [], errors
    return dispatches, []


def capability_plan_errors(
    plan: dict,
    dispatches: list[dict],
) -> list[str]:
    """Run each selected capability's bound Gate B validator."""
    errors: list[str] = []
    for item in dispatches:
        capability = item.get("capability")
        payload = item.get("payload")
        if not isinstance(capability, dict) or not isinstance(payload, dict):
            errors.append(
                "capability_dispatch_violation: malformed selected dispatch"
            )
            continue
        errors.extend(
            dispatch_gate_b_validator(
                capability,
                plan,
                payload,
            )
        )
    return errors


def _canonical_drawing_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _mode_b_source_drawing_errors(plan: dict, drawing_path: str) -> list[str]:
    source = plan.get("source_drawing")
    if not isinstance(source, str) or not source.strip():
        return [
            "Mode B plan missing source_drawing copied from plan-contracts output"
        ]
    expected = _canonical_drawing_path(drawing_path)
    actual = _canonical_drawing_path(source)
    if actual != expected:
        return [
            "Mode B source_drawing mismatch: "
            f"plan={source!r} cli_drawing={drawing_path!r}"
        ]
    return []


def _drawing_modeling_context(
    path: str,
) -> tuple[dict, list[dict], list[str]]:
    original = _load_drawing(path)
    drawing, normalization_errors, _ = normalize_drawing_schema(original)
    errors = list(normalization_errors)
    if not errors:
        errors.extend(check_drawing_json(drawing))
    errors.extend(_drawing_modeling_body_errors(drawing))
    if errors:
        return drawing, [], errors

    dispatches, capability_errors = resolve_drawing_capability_dispatches(drawing)
    errors.extend(capability_errors)
    return drawing, dispatches, errors


def _thread_metadata_from_dispatches(
    dispatches: list[dict],
) -> tuple[list[dict], list[dict]]:
    recipes: list[dict] = []
    geometries: list[dict] = []
    for item in dispatches:
        capability = item.get("capability")
        payload = item.get("payload")
        if not isinstance(capability, dict) or not isinstance(payload, dict):
            continue
        if capability.get("feature_kind") != "threaded_hole":
            continue
        recipes.extend(
            entry
            for entry in payload.get("recipes") or []
            if isinstance(entry, dict)
        )
        geometries.extend(
            entry
            for entry in payload.get("geometries") or []
            if isinstance(entry, dict)
        )

    def dedupe(items: list[dict]) -> list[dict]:
        by_id: dict[str, dict] = {}
        for item in items:
            feature_id = str(item.get("feature_id") or "")
            if feature_id:
                by_id[feature_id] = item
        return [by_id[key] for key in sorted(by_id)]

    return dedupe(recipes), dedupe(geometries)


# --------------------------------------------------------------------------
# Gate A drawing JSON validator — deterministic, part-agnostic, no NX
# --------------------------------------------------------------------------
_DRAWING_HARD_KEYS = {
    "type",
    "length",
    "length_x",
    "width",
    "width_y",
    "height",
    "height_z",
    "thickness",
    "diameter",
    "hole_diameter",
    "counterbore_diameter",
    "countersink_diameter",
    "radius",
    "depth",
    "hole_depth",
    "counterbore_depth",
    "axis",
    "width_axis",
    "through_axis",
    "center",
    "centerline",
    "centerline_x",
    "centerline_y",
    "centerline_z",
    "x",
    "y",
    "z",
    "top_z",
    "bottom_z",
    "start_z",
    "end_z",
    "side",
    "start_side",
    "material_side",
    "entry_endpoint",
    "through",
    "through_z",
    "count",
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
    "hole_x",
    "hole_y",
    "hole_z",
    "x1",
    "y1",
    "z1",
    "x2",
    "y2",
    "z2",
    "start",
    "end",
    "angle",
    "angle_deg",
    "start_angle",
    "end_angle",
    "spec",
    "kind",
    "pattern_type",
}
_DRAWING_META_KEYS = {
    "id",
    "name",
    "source_views",
    "confidence",
    "required_for_modeling",
    "notes",
    "warning",
    "warnings",
    "description",
    "evidence",
    "hard_fields",
}
_DRAWING_RELATION_SEMANTICS = {
    "center_distance",
    "center_spacing",
    "coordinate_distance",
    "edge_offset",
    "symmetry",
    "upper_tangent",
    "lower_tangent",
    "coincident",
    "alignment",
    "midpoint",
    "centered_span",
}


def _drawing_path_get(data: dict, target: str) -> Any:
    """Resolve feature:<id>.<path> or a normal dotted/list path."""
    if target.startswith("feature:"):
        rest = target[len("feature:") :]
        feature_id, dot, tail = rest.partition(".")
        if not feature_id:
            raise KeyError(target)
        feature = next(
            (
                item
                for item in data.get("features", [])
                if isinstance(item, dict) and item.get("id") == feature_id
            ),
            None,
        )
        if feature is None:
            raise KeyError(target)
        cur: Any = feature
        parts = tail.split(".") if dot and tail else []
    else:
        cur = data
        parts = target.split(".")
    for part in parts:
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(target)
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if idx < 0 or idx >= len(cur):
                raise KeyError(target)
            cur = cur[idx]
        else:
            raise KeyError(target)
    return cur


def _drawing_unresolved_geometry_pattern(item: dict) -> str | None:
    """Map a blocking unresolved field to a canonical geometry target pattern."""
    target = item.get("target")
    if isinstance(target, str) and target.strip():
        pattern = target.strip()
    else:
        field = item.get("field")
        if not isinstance(field, str) or not field.strip():
            return None
        field = field.strip()
        feature_id = (
            item.get("feature_id")
            or item.get("owner_feature_id")
            or item.get("feature")
        )
        if isinstance(feature_id, str) and feature_id.strip():
            pattern = f"feature:{feature_id.strip()}.{field}"
        elif field.startswith(("feature:", "profile.")):
            pattern = field
        elif field.startswith("segments."):
            pattern = f"profile.{field}"
        else:
            return None

    pattern = re.sub(r"\[(\d+|\*)\]", r".\1", pattern)
    pattern = re.sub(r"\.{2,}", ".", pattern).strip(".")
    lower = pattern.lower()
    leaf = lower.split(".")[-1]
    if re.search(r"\.centerline\.(x|y|z)$", lower):
        return pattern
    if ".position.center" in lower:
        return pattern
    if ".explicit_centers." in lower and leaf in {"0", "1", "2", "*"}:
        return pattern
    if leaf in {
        "top_z", "bottom_z", "start_z", "end_z", "side", "start_side",
        "material_side", "entry_endpoint",
    }:
        return pattern
    if re.fullmatch(
        r"profile\.segments\.(\d+|\*)\.(x1|y1|z1|x2|y2|z2|start|end)",
        lower,
    ):
        return pattern
    return None


def _drawing_expand_target_pattern(data: dict, pattern: str) -> list[tuple[str, Any]]:
    """Resolve canonical target patterns, expanding list wildcards only."""
    candidates = [pattern]
    while any(".*" in candidate for candidate in candidates):
        expanded: list[str] = []
        for candidate in candidates:
            if ".*" not in candidate:
                expanded.append(candidate)
                continue
            prefix, suffix = candidate.split(".*", 1)
            try:
                container = _drawing_path_get(data, prefix)
            except KeyError:
                continue
            if isinstance(container, list):
                expanded.extend(
                    f"{prefix}.{index}{suffix}" for index in range(len(container))
                )
            elif isinstance(container, dict):
                expanded.extend(
                    f"{prefix}.{key}{suffix}" for key in sorted(container)
                )
        candidates = expanded

    resolved: list[tuple[str, Any]] = []
    for candidate in candidates:
        try:
            resolved.append((candidate, _drawing_path_get(data, candidate)))
        except KeyError:
            continue
    return resolved


def _drawing_has_concrete_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_drawing_has_concrete_value(child) for child in value.values())
    if isinstance(value, list):
        return any(_drawing_has_concrete_value(child) for child in value)
    return value is not None


def _drawing_target_feature(data: dict, target: str) -> dict | None:
    if not target.startswith("feature:"):
        return None
    rest = target[len("feature:") :]
    feature_id, _, _ = rest.partition(".")
    return next(
        (
            item
            for item in data.get("features", [])
            if isinstance(item, dict) and item.get("id") == feature_id
        ),
        None,
    )


def _drawing_target_feature_id(target: str) -> str | None:
    if not target.startswith("feature:"):
        return None
    rest = target[len("feature:") :]
    feature_id, _, _ = rest.partition(".")
    return feature_id or None


def _drawing_is_center_target(target: str) -> bool:
    leaf = target.split(".")[-1].lower()
    return (
        target.startswith("constraints.span_centers.")
        or target.startswith("constraints.symmetric_centers.")
        or ".centerline." in target
        or ".position.center" in target
        or ".explicit_centers." in target
        or leaf in {
            "center",
            "centerline_x",
            "centerline_y",
            "centerline_z",
            "hole_x",
            "hole_y",
            "hole_z",
        }
    )


def _drawing_hard_paths(value: Any, prefix: str = "") -> set[str]:
    """Collect geometry-bearing leaf paths from one required feature/profile."""
    out: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _DRAWING_META_KEYS:
                continue
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(child, dict):
                out.update(_drawing_hard_paths(child, path))
            elif isinstance(child, list):
                if child and all(isinstance(item, dict) for item in child):
                    for idx, item in enumerate(child):
                        out.update(_drawing_hard_paths(item, f"{path}.{idx}"))
                elif key == "explicit_centers":
                    for idx, item in enumerate(child):
                        if isinstance(item, list):
                            for coord_idx, _ in enumerate(item):
                                out.add(f"{path}.{idx}.{coord_idx}")
                        elif isinstance(item, dict):
                            out.update(_drawing_hard_paths(item, f"{path}.{idx}"))
                        else:
                            out.add(f"{path}.{idx}")
                elif key in _DRAWING_HARD_KEYS:
                    out.add(path)
            elif key in _DRAWING_HARD_KEYS:
                out.add(path)
    return out


def _drawing_target_covered(target: str, covered: set[str]) -> bool:
    if target in covered:
        return True
    return any(target.startswith(f"{ancestor}.") for ancestor in covered)


_SUBTRACTIVE_MODELING_FEATURE_TYPES = {
    "hole",
    "through_hole",
    "threaded_hole",
    "counterbore_hole",
    "countersink_hole",
    "slot",
    "cut",
    "slit",
}


def _drawing_modeling_body_errors(data: dict) -> list[str]:
    """Reject Planner/Runner input that has no evidence-backed body geometry."""
    profile = data.get("profile")
    if isinstance(profile, dict) and _drawing_hard_paths(profile):
        return []

    required_features = [
        item
        for item in data.get("features", [])
        if isinstance(item, dict) and item.get("required_for_modeling", True) is not False
    ]
    if any(
        str(item.get("type") or "").lower()
        not in _SUBTRACTIVE_MODELING_FEATURE_TYPES
        for item in required_features
    ):
        return []

    return [
        "drawing lacks body-defining geometry: provide an evidence-backed profile "
        "or an additive/base modeling feature before Planner/Runner"
    ]


def _drawing_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= tol
    return a == b


def _drawing_direct_semantic_ok(data: dict, source: dict) -> bool:
    semantic = str(source.get("semantic") or "")
    target = source.get("target")
    if not isinstance(target, str) or not target:
        return False
    feature = _drawing_target_feature(data, target)
    feature_type = str((feature or {}).get("type") or "").lower()
    leaf = target.split(".")[-1].lower()

    if semantic == "overall_dimension":
        return target.startswith("overall_dimensions.")
    if semantic == "profile_dimension":
        return target.startswith("profile.")
    if semantic == "feature_count":
        return leaf == "count"
    if semantic == "diameter":
        return leaf in {
            "diameter",
            "hole_diameter",
            "counterbore_diameter",
            "countersink_diameter",
        }
    if semantic == "radius":
        return leaf == "radius"
    if semantic == "slot_width":
        return feature_type in {"slot", "cut", "slit"} and leaf == "width"
    if semantic == "depth":
        return leaf in {"depth", "hole_depth", "counterbore_depth"}
    if semantic == "thickness":
        return leaf == "thickness"
    if semantic == "axis":
        return leaf in {"axis", "width_axis", "through_axis"}
    if semantic == "center_position":
        return (
            ".centerline" in target
            or ".position.center" in target
            or leaf in {
                "center",
                "centerline_x",
                "centerline_y",
                "centerline_z",
                "hole_x",
                "hole_y",
                "hole_z",
            }
        )
    if semantic == "position_dimension":
        return leaf in {"x", "y", "z", "top_z", "bottom_z", "start_z", "end_z"}
    if semantic == "thread_spec":
        return leaf == "spec"
    if semantic == "feature_kind":
        return leaf in {"type", "kind"}
    if semantic == "side":
        return leaf in {"side", "start_side"}
    if semantic == "start_side":
        return leaf == "start_side"
    if semantic == "material_side":
        return leaf == "material_side"
    if semantic == "entry_endpoint":
        return leaf == "entry_endpoint"
    if semantic == "through":
        return leaf in {"through", "through_z"}
    if semantic == "pattern_dimension":
        return leaf in {
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
        }
    if semantic == "feature_dimension":
        # Generic direct dimensions are intentionally forbidden from fields whose
        # meaning needs a more specific semantic class. A normal body's width is
        # fine; a slot/cut width must use slot_width.
        forbidden = {
            "count",
            "diameter",
            "hole_diameter",
            "counterbore_diameter",
            "countersink_diameter",
            "radius",
            "depth",
            "hole_depth",
            "counterbore_depth",
            "axis",
            "width_axis",
            "through_axis",
            "center",
            "centerline",
            "centerline_x",
            "centerline_y",
            "centerline_z",
            "bottom_z",
            "top_z",
            "side",
            "start_side",
            "material_side",
            "entry_endpoint",
            "spec",
            "pattern_type",
        }
        if feature_type in {"slot", "cut", "slit"} and leaf == "width":
            return False
        return target.startswith("feature:") and leaf not in forbidden
    return False


def _drawing_source_value(source: dict) -> float | None:
    value = source.get("value")
    return _num(value)


def _drawing_eval_expr(
    data: dict,
    sources: dict[str, dict],
    expr: Any,
) -> tuple[float | None, set[str], set[str], list[str]]:
    """Validate a tiny arithmetic expression and return provenance.

    Gate A intentionally does not re-evaluate composite derived arithmetic.
    Numeric solving belongs to the deterministic Resolver; this helper only
    validates expression shape, references, and numeric operand sanity.
    """
    errors: list[str] = []
    if not isinstance(expr, dict):
        return None, set(), set(), ["derived expr must be an object"]

    if "const" in expr:
        value = _num(expr.get("const"))
        if value is None:
            errors.append("derived const must be numeric")
        return value, set(), set(), errors

    if "target" in expr:
        target = expr.get("target")
        if not isinstance(target, str) or not target:
            return None, set(), set(), ["derived target reference must be a string"]
        try:
            value = _drawing_path_get(data, target)
        except KeyError:
            return None, set(), {target}, [f"derived references missing target {target!r}"]
        number = _num(value)
        if number is None:
            errors.append(f"derived target {target!r} is not numeric")
        return number, set(), {target}, errors

    if "source" in expr:
        sid = expr.get("source")
        if not isinstance(sid, str) or not sid:
            return None, set(), set(), ["derived source reference must be a string"]
        source = sources.get(sid)
        if source is None:
            return None, {sid}, set(), [f"derived references unknown source {sid!r}"]
        value = _drawing_source_value(source)
        if value is None:
            errors.append(f"derived source {sid!r} has no numeric value")
        return value, {sid}, set(), errors

    op = expr.get("op")
    args = expr.get("args")
    if op not in {"add", "sub", "mul", "div", "neg", "abs"}:
        return None, set(), set(), [f"unsupported derived op {op!r}"]
    if not isinstance(args, list):
        return None, set(), set(), ["derived op args must be a list"]

    expected = 1 if op in {"neg", "abs"} else 2
    if len(args) != expected:
        return None, set(), set(), [f"derived op {op!r} requires {expected} args"]

    source_refs: set[str] = set()
    target_refs: set[str] = set()
    for arg in args:
        _, child_sources, child_targets, child_errors = _drawing_eval_expr(
            data, sources, arg
        )
        errors.extend(child_errors)
        source_refs.update(child_sources)
        target_refs.update(child_targets)

    return None, source_refs, target_refs, errors


def _drawing_relation_source_ok(
    data: dict,
    source: dict,
    derived_target: str,
    target_refs: set[str],
) -> tuple[bool, str | None]:
    semantic = str(source.get("semantic") or "")

    if semantic in {"center_distance", "center_spacing", "coordinate_distance"}:
        between = source.get("between")
        if (
            not isinstance(between, list)
            or len(between) != 2
            or not all(isinstance(item, str) and item for item in between)
        ):
            return False, f"{semantic} source requires between=[targetA,targetB]"
        if derived_target not in between:
            return False, f"{semantic} source cannot derive {derived_target!r}"
        other = between[1] if between[0] == derived_target else between[0]
        if other not in target_refs:
            return False, f"{semantic} source requires the opposite endpoint {other!r}"
        try:
            a = _num(_drawing_path_get(data, between[0]))
            b = _num(_drawing_path_get(data, between[1]))
        except KeyError:
            return False, f"{semantic} source references a missing endpoint"
        expected = _drawing_source_value(source)
        if a is None or b is None or expected is None:
            return False, f"{semantic} source/endpoints must be numeric"
        return True, None

    return True, None


def _drawing_relation_ref_ok(
    data: dict,
    source: dict,
    derived_target: str,
    target_refs: set[str],
) -> tuple[bool, str | None]:
    semantic = str(source.get("semantic") or "")
    links = source.get("links")
    if semantic not in {
        "upper_tangent",
        "lower_tangent",
        "coincident",
        "alignment",
        "midpoint",
    }:
        return False, f"source semantic {semantic!r} is not a relation_ref"
    if not isinstance(links, list) or not all(isinstance(item, str) for item in links):
        return False, f"relation source {semantic!r} requires links"
    if derived_target not in links:
        return False, f"relation source {semantic!r} does not cover {derived_target!r}"

    if semantic == "midpoint":
        if len(links) != 3 or len(set(links)) != 3:
            return False, "midpoint source requires [endpoint_a, midpoint, endpoint_b]"
        required_dependencies = set(links) - {derived_target}
        if target_refs != required_dependencies:
            return False, (
                "midpoint derivation must reference the other two constraint targets"
            )
        try:
            first = _num(_drawing_path_get(data, links[0]))
            center = _num(_drawing_path_get(data, links[1]))
            second = _num(_drawing_path_get(data, links[2]))
        except KeyError:
            return False, "midpoint source references a missing target"
        if first is None or center is None or second is None:
            return False, "midpoint source links must be numeric scalars"
        if abs(center - (first + second) / 2.0) > 1e-9:
            return False, "midpoint source does not match target geometry"
        return True, None

    if target_refs and not any(ref in links for ref in target_refs):
        return False, f"relation source {semantic!r} does not link a derived dependency"

    if semantic in {"coincident", "alignment"}:
        values: list[float] = []
        if len(links) < 2:
            return False, f"relation source {semantic!r} requires at least two links"
        for link in links:
            try:
                value = _num(_drawing_path_get(data, link))
            except KeyError:
                return False, f"relation source {semantic!r} references a missing target"
            if value is None:
                return False, f"relation source {semantic!r} links must be numeric scalars"
            values.append(value)
        if semantic == "coincident" and any(
            abs(value - values[0]) > 1e-9 for value in values[1:]
        ):
            return False, f"relation source {semantic!r} does not match target geometry"

    if semantic in {"upper_tangent", "lower_tangent"}:
        center = source.get("center")
        diameter = source.get("diameter")
        tangent = source.get("tangent")
        if not all(isinstance(item, str) and item for item in (center, diameter, tangent)):
            return False, f"{semantic} source requires center/diameter/tangent targets"
        try:
            center_value = _num(_drawing_path_get(data, center))
            diameter_value = _num(_drawing_path_get(data, diameter))
            tangent_value = _num(_drawing_path_get(data, tangent))
        except KeyError:
            return False, f"{semantic} source references a missing target"
        if center_value is None or diameter_value is None or tangent_value is None:
            return False, f"{semantic} targets must be numeric"
    return True, None


def _drawing_overall_bbox(data: dict) -> tuple[float, float, float] | None:
    overall = data.get("overall_dimensions")
    if not isinstance(overall, dict):
        return None

    def first_number(*keys: str) -> float | None:
        for key in keys:
            value = _num(overall.get(key))
            if value is not None:
                return value
        return None

    lx = first_number("length_x", "length")
    ly = first_number("width_y", "width")
    hz = first_number("height_z", "height")
    if lx is None or ly is None or hz is None:
        return None
    if lx <= 0 or ly <= 0 or hz <= 0:
        return None
    return lx, ly, hz


def _drawing_check_coord(
    errors: list[str],
    label: str,
    axis: str,
    value: Any,
    bbox: tuple[float, float, float],
) -> None:
    number = _num(value)
    if number is None:
        return
    lx, ly, hz = bbox
    if axis == "x":
        lo, hi = -lx / 2.0, lx / 2.0
    elif axis == "y":
        lo, hi = -ly / 2.0, ly / 2.0
    else:
        lo, hi = 0.0, hz
    if number < lo - 1e-9 or number > hi + 1e-9:
        errors.append(
            f"{label} {axis}={number:g} outside overall bbox [{lo:g},{hi:g}]"
        )


def _drawing_check_feature_bbox(
    errors: list[str],
    feature: dict,
    bbox: tuple[float, float, float],
) -> None:
    fid = str(feature.get("id") or "?")
    centerline = feature.get("centerline")
    if isinstance(centerline, dict):
        for axis in ("x", "y", "z"):
            if axis in centerline:
                _drawing_check_coord(
                    errors,
                    f"feature {fid} centerline",
                    axis,
                    centerline.get(axis),
                    bbox,
                )

    for axis in ("x", "y", "z"):
        key = f"centerline_{axis}"
        if key in feature:
            _drawing_check_coord(errors, f"feature {fid}", axis, feature.get(key), bbox)
        hole_key = f"hole_{axis}"
        if hole_key in feature:
            _drawing_check_coord(
                errors, f"feature {fid}", axis, feature.get(hole_key), bbox
            )

    position = feature.get("position")
    if isinstance(position, dict):
        center = position.get("center")
        if isinstance(center, dict):
            for axis in ("x", "y", "z"):
                if axis in center:
                    _drawing_check_coord(
                        errors,
                        f"feature {fid} position.center",
                        axis,
                        center.get(axis),
                        bbox,
                    )
        elif isinstance(center, list):
            for axis, value in zip(("x", "y", "z"), center, strict=False):
                _drawing_check_coord(
                    errors, f"feature {fid} position.center", axis, value, bbox
                )

    centers = feature.get("explicit_centers")
    if isinstance(centers, list):
        for idx, center in enumerate(centers):
            label = f"feature {fid} explicit_centers[{idx}]"
            if isinstance(center, dict):
                for axis in ("x", "y", "z"):
                    if axis in center:
                        _drawing_check_coord(
                            errors, label, axis, center.get(axis), bbox
                        )
            elif isinstance(center, list):
                for axis, value in zip(("x", "y", "z"), center, strict=False):
                    _drawing_check_coord(errors, label, axis, value, bbox)

    for axis in ("x", "y", "z"):
        values = feature.get(f"centers_{axis}")
        if isinstance(values, list):
            for idx, value in enumerate(values):
                _drawing_check_coord(
                    errors,
                    f"feature {fid} centers_{axis}[{idx}]",
                    axis,
                    value,
                    bbox,
                )


def _drawing_check_profile_bbox(
    errors: list[str],
    value: Any,
    bbox: tuple[float, float, float],
    prefix: str = "profile",
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            if key in {"x", "y", "z", "x_range", "y_range", "z_range"}:
                axis = key[0]
                if (
                    isinstance(child, list)
                    and len(child) == 2
                    and all(_num(item) is not None for item in child)
                ):
                    for item in child:
                        _drawing_check_coord(errors, path, axis, item, bbox)
                    continue
            if key in {"x1", "x2", "y1", "y2", "z1", "z2"}:
                _drawing_check_coord(errors, path, key[0], child, bbox)
                continue
            if key in {"start", "end", "center"} and isinstance(child, list):
                for axis, item in zip(("x", "y", "z"), child, strict=False):
                    _drawing_check_coord(errors, path, axis, item, bbox)
                continue
            _drawing_check_profile_bbox(errors, child, bbox, path)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _drawing_check_profile_bbox(errors, child, bbox, f"{prefix}.{idx}")


def _drawing_feature_coord(feature: dict, axis: str) -> Any:
    centerline = feature.get("centerline")
    if isinstance(centerline, dict) and axis in centerline:
        return centerline.get(axis)
    key = f"centerline_{axis}"
    if key in feature:
        return feature.get(key)
    position = feature.get("position")
    if isinstance(position, dict):
        center = position.get("center")
        if isinstance(center, dict):
            return center.get(axis)
        if isinstance(center, list):
            idx = {"x": 0, "y": 1, "z": 2}[axis]
            if idx < len(center):
                return center[idx]
    return None


def _drawing_check_feature_structure(errors: list[str], feature: dict) -> None:
    fid = str(feature.get("id") or "?")
    feature_type = str(feature.get("type") or "").lower()
    if not feature_type:
        errors.append(f"feature {fid!r} requires a non-empty type")
        return

    position = feature.get("position")
    if isinstance(position, dict) and isinstance(position.get("center"), list):
        center = position["center"]
        if len(center) not in {2, 3} or not all(_num(item) is not None for item in center):
            errors.append(
                f"feature {fid!r} position.center must contain 2 or 3 numeric coordinates"
            )

    explicit = feature.get("explicit_centers")
    if isinstance(explicit, list):
        for idx, center in enumerate(explicit):
            if isinstance(center, list) and (
                len(center) not in {2, 3} or not all(_num(item) is not None for item in center)
            ):
                errors.append(
                    f"feature {fid!r} explicit_centers[{idx}] must contain 2 or 3 numeric coordinates"
                )

    if feature_type in {"slot", "slit"}:
        width = _num(feature.get("width"))
        width_axis = str(feature.get("width_axis") or "").upper()
        through_axis = str(feature.get("through_axis") or "").upper()
        if width is None or width <= 0:
            errors.append(f"feature {fid!r} {feature_type} requires positive width")
        if width_axis not in {"X", "Y", "Z"}:
            errors.append(f"feature {fid!r} {feature_type} requires width_axis X/Y/Z")
        if through_axis not in {"X", "Y", "Z"}:
            errors.append(f"feature {fid!r} {feature_type} requires through_axis X/Y/Z")
        if width_axis == through_axis and width_axis in {"X", "Y", "Z"}:
            errors.append(f"feature {fid!r} {feature_type} width_axis and through_axis must differ")
    hole_like = "hole" in feature_type or feature_type == "coaxial_hole_group"
    if not hole_like:
        return

    axis = str(feature.get("axis") or "").upper()
    if axis not in {"X", "Y", "Z"}:
        errors.append(f"feature {fid!r} hole-like geometry requires axis X/Y/Z")
        return

    count = _num(feature.get("count"))
    if isinstance(explicit, list) and count is not None and count > 1:
        return

    if axis in {"X", "Y"} and isinstance(position, dict):
        center = position.get("center")
        if isinstance(center, list) and len(center) != 3:
            errors.append(
                f"feature {fid!r} axis {axis} requires a 3D center list or named center coordinates"
            )

    needed = {
        "X": ("y", "z"),
        "Y": ("x", "z"),
        "Z": ("x", "y"),
    }[axis]
    for coord in needed:
        if _drawing_feature_coord(feature, coord) is None:
            errors.append(
                f"feature {fid!r} axis {axis} requires center coordinate {coord}"
            )

    if feature_type == "threaded_hole" and axis in {"X", "Y"}:
        explicit_range = next(
            (
                feature.get(key)
                for key in ("axis_range", "axial_range", "through_range", "range")
                if isinstance(feature.get(key), (list, tuple))
                and len(feature.get(key)) == 2
            ),
            None,
        )
        legacy_side_value = (
            feature.get("start_side")
            if feature.get("start_side") is not None
            else feature.get("side")
        )
        legacy_side = str(legacy_side_value or "").lower()
        material_side_value = feature.get("material_side")
        entry_endpoint_value = feature.get("entry_endpoint")
        material_side = str(material_side_value or "").lower()
        entry_endpoint = str(entry_endpoint_value or "").lower()
        split_present = (
            material_side_value is not None or entry_endpoint_value is not None
        )
        if split_present and legacy_side in {"min", "max"}:
            errors.append(
                f"feature {fid!r} threaded_hole must not mix legacy start_side/side "
                "with material_side/entry_endpoint"
            )
        elif split_present and (
            material_side not in {"min", "max"}
            or entry_endpoint not in {"min", "max"}
        ):
            errors.append(
                f"feature {fid!r} threaded_hole requires both material_side and "
                "entry_endpoint as min|max"
            )
        elif explicit_range is None and not split_present and legacy_side not in {"min", "max"}:
            errors.append(
                f"feature {fid!r} axis {axis} threaded_hole requires explicit axial "
                "range, material_side+entry_endpoint, or legacy start_side/side"
            )

    if feature_type in {"counterbore_hole", "countersink_hole"} and axis in {"X", "Y"}:
        side_value = (
            feature.get("start_side")
            if feature.get("start_side") is not None
            else feature.get("side")
        )
        side = str(side_value or "").lower()
        if side not in {"min", "max"}:
            errors.append(
                f"feature {fid!r} axis {axis} {feature_type} requires "
                "start_side/side min|max"
            )


def _drawing_check_count(errors: list[str], item: dict, label: str) -> None:
    count = item.get("count")
    if count is None:
        return
    n = _num(count)
    if n is None or int(n) != n or n <= 0:
        errors.append(f"{label} count must be a positive integer")
        return
    n_int = int(n)

    explicit = item.get("explicit_centers")
    if isinstance(explicit, list) and len(explicit) != n_int:
        errors.append(f"{label} explicit_centers {len(explicit)} != count {n_int}")

    count_x, count_y = _num(item.get("count_x")), _num(item.get("count_y"))
    if item.get("pattern_type") == "rectangular":
        if count_x is None or count_y is None:
            errors.append(f"{label} rectangular pattern requires count_x and count_y")
        elif any(value <= 0 or int(value) != value for value in (count_x, count_y)):
            errors.append(f"{label} count_x and count_y must be positive integers")
        else:
            product = int(count_x) * int(count_y)
            if product != n_int:
                errors.append(f"{label} count_x*count_y {product} != count {n_int}")


def _drawing_check_symmetry(
    errors: list[str],
    source: dict,
    features: dict[str, dict],
) -> None:
    feature_id = source.get("feature")
    axis = str(source.get("axis") or "").lower()
    about = _num(source.get("about"))
    feature = features.get(str(feature_id))
    if feature is None or axis not in {"x", "y", "z"} or about is None:
        errors.append("symmetry source requires feature, axis and numeric about")
        return

    values: list[float] = []
    explicit = feature.get("explicit_centers")
    if isinstance(explicit, list):
        for center in explicit:
            value: Any = None
            if isinstance(center, dict):
                value = center.get(axis)
            elif isinstance(center, list):
                idx = {"x": 0, "y": 1, "z": 2}[axis]
                if idx < len(center):
                    value = center[idx]
            number = _num(value)
            if number is not None:
                values.append(number)
    if not values:
        axis_values = feature.get(f"centers_{axis}")
        if isinstance(axis_values, list):
            values = [number for item in axis_values if (number := _num(item)) is not None]
    if not values:
        errors.append(
            f"symmetry source has no machine-checkable centers for feature {feature_id!r}"
        )
        return

    for value in values:
        mirror = 2.0 * about - value
        if not any(abs(other - mirror) <= 1e-9 for other in values):
            errors.append(
                f"feature {feature_id!r} centers are not symmetric about {axis}={about:g}"
            )
            return


def check_drawing_json(data: dict) -> list[str]:
    """Machine-check Gate A provenance, derivations, counts and coordinate sanity."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["drawing JSON root must be an object"]

    required_roots = (
        "overall_dimensions",
        "coordinate_system",
        "features",
        "source_ledger",
        "derived",
        "unresolved",
        "dimension_conflicts",
        "dimension_closure",
    )
    for key in required_roots:
        if key not in data:
            errors.append(f"drawing JSON missing {key}")

    features_raw = data.get("features")
    if not isinstance(features_raw, list) or not features_raw:
        errors.append("features must be a non-empty list")
        features_raw = []

    features: dict[str, dict] = {}
    for idx, feature in enumerate(features_raw):
        if not isinstance(feature, dict):
            errors.append(f"features[{idx}] must be an object")
            continue
        fid = feature.get("id")
        if not isinstance(fid, str) or not fid.strip():
            errors.append(f"features[{idx}] missing stable id")
            continue
        if fid in features:
            errors.append(f"duplicate feature id {fid!r}")
            continue
        features[fid] = feature

    ledger = data.get("source_ledger")
    if not isinstance(ledger, list) or not ledger:
        errors.append("source_ledger must be a non-empty list")
        ledger = []

    sources: dict[str, dict] = {}
    direct_targets: set[str] = set()
    relation_targets: set[str] = set()
    for idx, source in enumerate(ledger):
        if not isinstance(source, dict):
            errors.append(f"source_ledger[{idx}] must be an object")
            continue
        sid = source.get("id")
        semantic = source.get("semantic")
        if not isinstance(sid, str) or not sid.strip():
            errors.append(f"source_ledger[{idx}] missing id")
            continue
        if sid in sources:
            errors.append(f"duplicate source id {sid!r}")
            continue
        if not isinstance(semantic, str) or not semantic:
            errors.append(f"source {sid!r} missing semantic")
            continue
        sources[sid] = source

        if semantic in _DRAWING_RELATION_SEMANTICS:
            if "target" in source:
                errors.append(f"relation source {sid!r} must not use direct target")
            if semantic == "edge_offset":
                targets = source.get("targets")
                axis = str(source.get("axis") or "").lower()
                side = str(source.get("from") or "").lower()
                value = _drawing_source_value(source)
                if (
                    not isinstance(targets, list)
                    or not targets
                    or not all(isinstance(item, str) and item for item in targets)
                    or axis not in {"x", "y", "z"}
                    or side not in {"min", "max"}
                    or value is None
                ):
                    errors.append(
                        f"source {sid!r} edge_offset requires targets/axis/from/value"
                    )
                else:
                    # Numerical relation solving belongs to the deterministic
                    # Resolver. Gate A only validates relation shape, concrete
                    # target presence/type, and provenance coverage.
                    for target in targets:
                        try:
                            actual = _num(_drawing_path_get(data, target))
                        except KeyError:
                            actual = None
                        if actual is None:
                            errors.append(
                                f"source {sid!r} edge_offset target {target!r} is missing"
                            )
                            continue
                        relation_targets.add(target)
                continue
            if semantic in {"center_distance", "center_spacing", "coordinate_distance"}:
                between = source.get("between")
                if (
                    not isinstance(between, list)
                    or len(between) != 2
                    or not all(isinstance(item, str) and item for item in between)
                ):
                    errors.append(f"source {sid!r} requires between=[targetA,targetB]")
                else:
                    if (
                        semantic != "coordinate_distance"
                        and not all(
                            _drawing_is_center_target(target)
                            for target in between
                        )
                    ):
                        errors.append(
                            f"source {sid!r} center distance endpoints must be center coordinates"
                        )
                    for target in between:
                        try:
                            _drawing_path_get(data, target)
                        except KeyError:
                            errors.append(
                                f"source {sid!r} references missing endpoint {target!r}"
                            )
                    value = _drawing_source_value(source)
                    if value is None:
                        errors.append(f"source {sid!r} must have numeric value")
                    for target in between:
                        try:
                            endpoint = _num(_drawing_path_get(data, target))
                        except KeyError:
                            endpoint = None
                        if endpoint is None:
                            errors.append(
                                f"source {sid!r} center distance endpoint {target!r} must be numeric"
                            )
            elif semantic in {"upper_tangent", "lower_tangent"}:
                center = source.get("center")
                diameter = source.get("diameter")
                tangent = source.get("tangent")
                links = source.get("links")
                if not all(
                    isinstance(item, str) and item
                    for item in (center, diameter, tangent)
                ):
                    errors.append(
                        f"source {sid!r} requires center/diameter/tangent targets"
                    )
                if (
                    not isinstance(links, list)
                    or tangent not in links
                    or center not in links
                    or diameter not in links
                ):
                    errors.append(f"source {sid!r} tangent links are incomplete")
                else:
                    try:
                        center_value = _num(_drawing_path_get(data, center))
                        diameter_value = _num(_drawing_path_get(data, diameter))
                        tangent_value = _num(_drawing_path_get(data, tangent))
                    except KeyError:
                        center_value, diameter_value, tangent_value = None, None, None
                    if (
                        center_value is None
                        or diameter_value is None
                        or tangent_value is None
                    ):
                        errors.append(f"source {sid!r} tangent targets must be numeric")
                    relation_targets.add(tangent)
            elif semantic == "symmetry":
                _drawing_check_symmetry(errors, source, features)
            elif semantic == "centered_span":
                links = source.get("links")
                span_value = _num(source.get("value"))
                direction = source.get("direction")
                if (
                    not isinstance(links, list)
                    or len(links) != 3
                    or len(set(links)) != 3
                    or not all(isinstance(item, str) and item for item in links)
                    or span_value is None
                    or span_value <= 0
                    or direction not in {None, -1, 1}
                ):
                    errors.append(
                        f"source {sid!r} centered_span requires "
                        "[endpoint_a, midpoint, endpoint_b], positive value, "
                        "and optional direction ±1"
                    )
                else:
                    try:
                        first = _num(_drawing_path_get(data, links[0]))
                        center = _num(_drawing_path_get(data, links[1]))
                        second = _num(_drawing_path_get(data, links[2]))
                    except KeyError:
                        first, center, second = None, None, None
                    if first is None or center is None or second is None:
                        errors.append(
                            f"source {sid!r} centered_span targets must be numeric"
                        )
                    else:
                        if abs(center - (first + second) / 2.0) > 1e-9:
                            errors.append(
                                f"source {sid!r} centered_span midpoint mismatch"
                            )
                        if abs(abs(second - first) - span_value) > 1e-9:
                            errors.append(
                                f"source {sid!r} centered_span width mismatch"
                            )
                        if (
                            direction in {-1, 1}
                            and abs((second - first) - direction * span_value) > 1e-9
                        ):
                            errors.append(
                                f"source {sid!r} centered_span direction mismatch"
                            )
                        relation_targets.update(links)
            elif semantic in {"coincident", "alignment", "midpoint"}:
                links = source.get("links")
                required_link_count = 3 if semantic == "midpoint" else 1
                if (
                    not isinstance(links, list)
                    or len(links) < required_link_count
                    or not all(isinstance(item, str) and item for item in links)
                ):
                    errors.append(f"source {sid!r} {semantic} requires valid links")
                else:
                    probe_target = links[1] if semantic == "midpoint" else links[0]
                    probe_dependencies = (
                        {links[0], links[2]}
                        if semantic == "midpoint"
                        else set(links[1:])
                    )
                    ok, reason = _drawing_relation_ref_ok(
                        data,
                        source,
                        probe_target,
                        probe_dependencies,
                    )
                    if not ok and reason:
                        errors.append(f"source {sid!r}: {reason}")
            continue

        target = source.get("target")
        if not isinstance(target, str) or not target:
            errors.append(f"direct source {sid!r} missing target")
            continue
        try:
            actual = _drawing_path_get(data, target)
        except KeyError:
            errors.append(f"source {sid!r} targets missing field {target!r}")
            continue
        if not _drawing_direct_semantic_ok(data, source):
            errors.append(
                f"source {sid!r} semantic {semantic!r} is incompatible with {target!r}"
            )
            continue
        if "value" in source and not _drawing_equal(actual, source.get("value")):
            errors.append(f"source {sid!r} value does not match {target!r}")
        direct_targets.add(target)

    derived_raw = data.get("derived")
    if not isinstance(derived_raw, list):
        errors.append("derived must be a list")
        derived_raw = []

    derived_targets: set[str] = set()
    for idx, item in enumerate(derived_raw):
        if not isinstance(item, dict):
            errors.append(f"derived[{idx}] must be an object")
            continue
        did = item.get("id")
        target = item.get("target")
        if not isinstance(did, str) or not did:
            errors.append(f"derived[{idx}] missing id")
            did = f"#{idx}"
        if not isinstance(target, str) or not target:
            errors.append(f"derived {did!r} missing target")
            continue
        if target in derived_targets:
            errors.append(f"multiple derived entries target {target!r}")
        derived_targets.add(target)
        try:
            actual = _drawing_path_get(data, target)
        except KeyError:
            errors.append(f"derived {did!r} targets missing field {target!r}")
            actual = None

        _, source_refs, target_refs, expr_errors = _drawing_eval_expr(
            data, sources, item.get("expr")
        )
        errors.extend(f"derived {did!r}: {error}" for error in expr_errors)

        if "value" not in item:
            errors.append(f"derived {did!r} missing value")
        else:
            declared_value = _num(item.get("value"))
            if declared_value is None:
                errors.append(f"derived {did!r} value must be numeric")
            elif actual is not None:
                actual_value = _num(actual)
                if actual_value is None:
                    errors.append(f"derived {did!r} target {target!r} must be numeric")
                elif not _drawing_equal(declared_value, actual_value):
                    errors.append(
                        f"derived {did!r} declared value does not match target {target!r}"
                    )

        relation_refs = item.get("relation_refs") or []
        if not isinstance(relation_refs, list) or not all(
            isinstance(ref, str) and ref for ref in relation_refs
        ):
            errors.append(f"derived {did!r} relation_refs must be a list")
            relation_refs = []

        relation_ok = False
        for sid in source_refs:
            source = sources.get(sid)
            if source is None:
                continue
            semantic = str(source.get("semantic") or "")
            if semantic in {
                "center_distance",
                "center_spacing",
                "coordinate_distance",
            }:
                ok, reason = _drawing_relation_source_ok(
                    data, source, target, target_refs
                )
                if not ok and reason:
                    errors.append(f"derived {did!r}: {reason}")
                relation_ok = relation_ok or ok
            elif semantic in _DRAWING_RELATION_SEMANTICS:
                errors.append(
                    f"derived {did!r}: relation source {sid!r} cannot be numeric operand"
                )

        for sid in relation_refs:
            source = sources.get(sid)
            if source is None:
                errors.append(f"derived {did!r} references unknown relation {sid!r}")
                continue
            ok, reason = _drawing_relation_ref_ok(data, source, target, target_refs)
            if not ok and reason:
                errors.append(f"derived {did!r}: {reason}")
            relation_ok = relation_ok or ok

        target_feature = _drawing_target_feature_id(target)
        dependency_features = {
            feature_id
            for ref in target_refs
            if (feature_id := _drawing_target_feature_id(ref)) is not None
        }
        cross_feature = (
            target_feature is not None
            and any(feature_id != target_feature for feature_id in dependency_features)
        )
        if cross_feature and not relation_ok:
            errors.append(
                f"derived {did!r} crosses feature boundaries without relation evidence"
            )

    computed_targets = derived_targets | relation_targets
    for target in sorted(direct_targets & computed_targets):
        errors.append(
            f"drawing geometry target {target!r} has a writer conflict: "
            "both direct and derived/relation writers are present"
        )

    covered_targets = direct_targets | derived_targets | relation_targets

    # Required feature geometry must have evidence; profile/overall get the same rule.
    for fid, feature in features.items():
        if feature.get("required_for_modeling") is False:
            continue
        hard_paths = _drawing_hard_paths(feature)
        declared = feature.get("hard_fields")
        if isinstance(declared, list):
            hard_paths.update(
                item for item in declared if isinstance(item, str) and item
            )
        for path in sorted(hard_paths):
            target = f"feature:{fid}.{path}"
            if not _drawing_target_covered(target, covered_targets):
                errors.append(f"required geometry field lacks evidence: {target}")

    overall = data.get("overall_dimensions")
    if isinstance(overall, dict):
        for key in ("length_x", "length", "width_y", "width", "height_z", "height"):
            if key in overall and _num(overall.get(key)) is not None:
                target = f"overall_dimensions.{key}"
                if target not in direct_targets and target not in derived_targets:
                    errors.append(f"overall dimension lacks evidence: {target}")

    profile = data.get("profile")
    if isinstance(profile, dict):
        for path in sorted(_drawing_hard_paths(profile)):
            target = f"profile.{path}"
            if not _drawing_target_covered(
                target, direct_targets | derived_targets | relation_targets
            ):
                errors.append(f"profile geometry lacks evidence: {target}")

    for feature in features.values():
        _drawing_check_feature_structure(errors, feature)

    # Machine-computed coordinate sanity.
    coord = data.get("coordinate_system")
    if not isinstance(coord, dict) or coord.get("origin") != "part_center_xy_bottom_z0":
        errors.append("coordinate_system.origin must be part_center_xy_bottom_z0")
    bbox = _drawing_overall_bbox(data)
    if bbox is None:
        errors.append("overall_dimensions must provide positive X/Y/Z extents")
    else:
        for feature in features.values():
            _drawing_check_feature_bbox(errors, feature, bbox)
        if isinstance(profile, dict):
            _drawing_check_profile_bbox(errors, profile, bbox)

    # Count conservation for features and top-level patterns.
    for fid, feature in features.items():
        _drawing_check_count(errors, feature, f"feature {fid!r}")
    patterns = data.get("patterns")
    if isinstance(patterns, list):
        for idx, pattern in enumerate(patterns):
            if not isinstance(pattern, dict):
                continue
            _drawing_check_count(errors, pattern, f"patterns[{idx}]")
            for path in sorted(_drawing_hard_paths(pattern)):
                target = f"patterns.{idx}.{path}"
                if not _drawing_target_covered(
                    target, direct_targets | derived_targets | relation_targets
                ):
                    errors.append(f"pattern geometry lacks evidence: {target}")

    unresolved = data.get("unresolved")
    if isinstance(unresolved, list):
        blockers = [
            item
            for item in unresolved
            if isinstance(item, dict) and item.get("required_for_modeling") is True
        ]
        for item in blockers:
            pattern = _drawing_unresolved_geometry_pattern(item)
            if pattern is None:
                continue
            for target, value in _drawing_expand_target_pattern(data, pattern):
                if _drawing_has_concrete_value(value):
                    errors.append(
                        f"unresolved geometry has concrete placeholder: {target}"
                    )
        if blockers:
            errors.append(f"blocking_unresolved={len(blockers)}")

    conflicts = data.get("dimension_conflicts")
    if isinstance(conflicts, list) and conflicts:
        errors.append(f"dimension_conflicts={len(conflicts)}")

    dimension_closure = data.get("dimension_closure")
    if not isinstance(dimension_closure, dict):
        errors.append("dimension_closure must be an object")
    elif dimension_closure.get("status") != "closed":
        errors.append("dimension_closure.status must be closed")

    return errors


def _load_drawing(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise PlanError(f"{path}: drawing JSON root must be an object")
    return data


def _cmd_validate_drawing(args: argparse.Namespace) -> int:
    timing_state = _begin_command_timing("A4_VALIDATE", args.drawing)
    original = _load_drawing(args.drawing)
    drawing, normalization_errors, changes = normalize_drawing_schema(original)
    errors = normalization_errors + check_drawing_json(drawing)
    result = {
        "drawing": args.drawing,
        "normalization": {"changes": changes, "errors": normalization_errors},
        "source_ownership": {"status": "pass" if not errors else "fail"},
        "coordinate_sanity": {"status": "pass" if not errors else "fail"},
        "errors": errors,
        "ok": not errors,
    }
    _attach_command_timing(result, timing_state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def _atomic_write_json(path: str, data: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or os.curdir
    if not os.path.isdir(directory):
        raise PlanError(f"canonical drawing output directory does not exist: {directory}")
    fd, temporary = tempfile.mkstemp(prefix=".drawing-canonical-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _invalidate_canonical_output(path: str) -> None:
    if not os.path.lexists(path):
        return
    if os.path.isdir(path):
        raise PlanError(f"canonical drawing output path is a directory: {path}")
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    if os.path.lexists(path):
        raise PlanError(f"failed to invalidate pre-existing canonical drawing: {path}")


def _cmd_canonicalize_drawing(args: argparse.Namespace) -> int:
    timing_state = _begin_command_timing("A3_CANONICALIZE", args.draft)
    draft_path = os.path.abspath(args.draft)
    output_path = os.path.abspath(args.out)
    errors: list[str] = []
    normalization_errors: list[str] = []
    gate_errors: list[str] = []
    gate_attempted = False
    changes: list[str] = []
    drawing: dict | None = None

    if os.path.normcase(draft_path) == os.path.normcase(output_path):
        errors.append("semantic draft and canonical drawing output must be different paths")
    else:
        try:
            _invalidate_canonical_output(output_path)
            original = _load_drawing(draft_path)
            drawing, normalization_errors, changes = normalize_drawing_schema(original)
            errors.extend(normalization_errors)
            if not errors:
                gate_attempted = True
                try:
                    gate_errors = check_drawing_json(drawing)
                except Exception as exc:
                    gate_errors = [
                        f"Gate A internal error ({type(exc).__name__}): {exc}"
                    ]
                errors.extend(gate_errors)
        except (OSError, ValueError, PlanError) as exc:
            errors.append(str(exc))

    result = {
        "semantic_draft": draft_path,
        "canonical_drawing": output_path,
        "normalization": {"changes": changes, "errors": normalization_errors},
        "gate_a": {
            "attempted": gate_attempted,
            "errors": gate_errors,
            "ok": gate_attempted and not gate_errors,
        },
        "source_ownership": {"status": "pass" if not errors else "fail"},
        "coordinate_sanity": {"status": "pass" if not errors else "fail"},
        "errors": errors,
        "written": False,
        "ok": False,
    }

    if not errors and drawing is not None:
        try:
            _atomic_write_json(output_path, drawing)
        except (OSError, PlanError) as exc:
            errors.append(str(exc))
            result["errors"] = errors
        else:
            result["written"] = True
            result["ok"] = True

    result["output_exists"] = os.path.lexists(output_path)
    _attach_command_timing(result, timing_state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _load_plan(path: str) -> dict:
    # Windows PowerShell 5.1 writes a UTF-8 BOM for -Encoding UTF8.
    # Accept both BOM and non-BOM plan JSON consistently with drawing/runtime JSON.
    with open(path, encoding="utf-8-sig") as f:
        plan = json.load(f)
    if not isinstance(plan, dict) or "operations" not in plan:
        raise PlanError(f"{path}: not a modeling plan (missing operations)")
    return plan


def _is_executable(plan: dict) -> bool:
    if plan.get("plan_format") == "executable-v1":
        return True
    # Backward compatibility for executable plans built before plan_format existed.
    return any(
        op.get("result_bindings") or op.get("selection_binding")
        for op in plan.get("operations") or []
    )


async def _cmd_run(args: argparse.Namespace) -> int:
    timing_state = _begin_command_timing("C_RUNNER")
    timing_state["c2_modeling_complete_utc"] = None
    timing_state["c3_export_complete_utc"] = None

    def timed(result: dict[str, Any]) -> dict[str, Any]:
        return _attach_command_timing(result, timing_state, {
            "c1_runner_start_utc": timing_state.get("started_at_utc"),
            "c2_modeling_complete_utc": timing_state.get("c2_modeling_complete_utc"),
            "c3_export_complete_utc": timing_state.get("c3_export_complete_utc"),
        })

    def finish(result: dict[str, Any], exit_code: int) -> int:
        timed(result)
        if args.report:
            try:
                with open(args.report, "w", encoding="utf-8") as handle:
                    json.dump(result, handle, ensure_ascii=False, indent=2)
            except OSError as exc:
                result["status"] = "failed"
                result.setdefault("errors", []).append(
                    f"cannot write runner report: {type(exc).__name__}: {exc}"
                )
                exit_code = 1
        print("===REPORT===")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code

    t_start = time.monotonic()
    try:
        plan = _load_plan(args.plan)
    except Exception as exc:
        return finish(
            {
                "status": "failed",
                "failed_step": None,
                "errors": [f"cannot load plan: {type(exc).__name__}: {exc}"],
            },
            1,
        )
    if not _is_executable(plan):
        result = {"status": "failed", "failed_step": None,
                          "errors": ["plan is not in executable format "
                                     "(no result_bindings / selection_binding); run `build` first"]}
        return finish(result, 1)
    errs = check_plan(plan, executable=True)
    drawing_path = getattr(args, "drawing", None)
    if drawing_path:
        errs.extend(_mode_b_source_drawing_errors(plan, drawing_path))
    if errs:
        result = {"status": "failed", "failed_step": None,
                  "errors": errs[:20], "error_count": len(errs)}
        return finish(result, 1)
    try:
        transport = NXTransport(workspace_root=args.workspace)
        if not transport.ping():
            detail = transport.ping_error()
            error = "loader health check failed"
            if detail:
                error += ": " + detail
            result = {"status": "failed", "failed_step": None, "errors": [error]}
            return finish(result, 1)
    except Exception as exc:
        return finish(
            {
                "status": "failed",
                "failed_step": None,
                "errors": [
                    f"loader health check failed: {type(exc).__name__}: {exc}"
                ],
            },
            1,
        )

    try:
        planned_for_repair = derive_planned_part(plan, transport)
    except Exception as exc:
        return finish(
            {
                "status": "failed",
                "failed_step": None,
                "errors": [
                    f"planned part resolution failed: {type(exc).__name__}: {exc}"
                ],
            },
            1,
        )
    previous_report = None
    if args.repair_report:
        try:
            with open(args.repair_report, encoding="utf-8-sig") as f:
                previous_report = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            result = {
                "status": "repair_precheck_blocked",
                "failed_step": None,
                "errors": [f"cannot read repair report: {exc}"],
            }
            return finish(result, 1)

    repair_errors = repair_request_errors(
        args.repair_attempt,
        args.mode,
        args.allow_overwrite,
        planned_for_repair,
        previous_report,
    )
    if repair_errors:
        result = {
            "status": "repair_precheck_blocked",
            "failed_step": None,
            "errors": repair_errors,
        }
        return finish(result, 1)

    history_path = args.history or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "run_history.json")
    history = RunHistory(history_path)

    if args.repair_attempt == 1 and planned_for_repair:
        prior_history = history.most_recent(planned_for_repair) or {}
        if int(prior_history.get("repair_attempt", 0) or 0) >= 1:
            result = {
                "status": "repair_precheck_blocked",
                "failed_step": None,
                "errors": ["controlled self-healing already consumed for this planned part"],
            }
            return finish(result, 1)

    t_preflight = time.monotonic()
    try:
        blocked, info = await run_preflight(
            transport,
            plan,
            args.mode,
            args.allow_overwrite,
            history,
            repair_authorized=(args.repair_attempt == 1),
        )
    except Exception as exc:
        return finish(
            {
                "status": "failed",
                "failed_step": None,
                "errors": [f"preflight failed: {type(exc).__name__}: {exc}"],
            },
            1,
        )
    preflight_elapsed = time.monotonic() - t_preflight
    if blocked is not None:
        return finish(blocked, 1)
    planned_part = info["planned_part"] if info else None
    preserved_displayed_part = None
    if info and info.get("state") == "unrelated_part_preserved_for_create":
        preserved_displayed_part = info.get("active_part") or None
    if planned_part:
        history.record_start(
            planned_part, args.mode, args.plan, repair_attempt=args.repair_attempt
        )
    report = await run_plan(plan, transport, plan_path=args.plan,
                            wall_start=t_start, history=history,
                            mode=args.mode, planned_part=planned_part,
                            preserved_displayed_part=preserved_displayed_part,
                            timing_state=timing_state)
    report["preflight_elapsed"] = round(preflight_elapsed, 3)
    report["repair_attempt"] = int(args.repair_attempt)
    report["repair_source_report"] = args.repair_report
    return finish(report, 0 if report["status"] == "success" else 1)


def _cmd_plan_contracts(args: argparse.Namespace) -> int:
    """Expose deterministic capability/geometry/operation contracts to Planner."""
    timing_state = _begin_command_timing("B2_PLAN_CONTRACTS", args.drawing)
    drawing_path = os.path.abspath(args.drawing)
    _drawing, dispatches, errors = _drawing_modeling_context(drawing_path)

    contracts: list[dict] = []
    if not errors:
        for item in dispatches:
            capability = item.get("capability")
            payload = item.get("payload")
            if not isinstance(capability, dict) or not isinstance(payload, dict):
                errors.append(
                    "capability_dispatch_violation: malformed selected dispatch"
                )
                continue

            contracts.append(
                {
                    "implementation_id": capability.get("implementation_id"),
                    "feature_kind": capability.get("feature_kind"),
                    "exactness": capability.get("exactness"),
                    "supported_axes": list(
                        capability.get("supported_axes") or []
                    ),
                    "planner_adapter": capability.get("planner_adapter"),
                    "gate_b_validator": capability.get("gate_b_validator"),
                    "geometries": list(payload.get("geometries") or []),
                    "recipes": list(payload.get("recipes") or []),
                    "operation_contracts": list(
                        payload.get("operation_contracts") or []
                    ),
                }
            )

    result = {
        "drawing": drawing_path,
        "planner_contract": {
            "fixed_args_policy": "copy_exact_key_set_and_values",
            "preserve_explicit_false_zero_and_empty_objects": True,
            "operation_fields_policy": "copy_exact_to_frozen_operation_root",
            "operation_fields_are_not_tool_args": True,
            "requires_policy": "fill_only_declared_symbolic_wiring",
            "source_drawing_policy": "copy_exact_plan_contracts_drawing_to_frozen_top_level",
            "stage_b_failure_policy": "stop_no_retry_no_source_inspection",
            "must_stop_after_first_stage_b_failure": True,
            "may_edit_frozen_after_stage_b_failure": False,
            "may_retry_stage_b": False,
            "may_inspect_source_after_stage_b_failure": False,
        },
        "contracts": contracts if not errors else [],
        "errors": errors,
        "ok": not errors,
    }
    _attach_command_timing(result, timing_state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def _cmd_check(args: argparse.Namespace) -> int:
    timing_state = _begin_command_timing("B3_CHECK", args.plan)
    plan = _load_plan(args.plan)
    drawing_path = getattr(args, "drawing", None)
    errs = check_plan(
        plan,
        executable=not args.frozen,
        validate_embedded_thread_contract=not bool(drawing_path),
    )
    if drawing_path:
        errs.extend(_mode_b_source_drawing_errors(plan, drawing_path))
        _drawing, dispatches, drawing_errors = _drawing_modeling_context(
            drawing_path
        )
        errs.extend(drawing_errors)
        if not drawing_errors:
            errs.extend(capability_plan_errors(plan, dispatches))
    result = {"plan": args.plan, "frozen": bool(args.frozen),
                      "drawing": drawing_path,
                      "operations": len(plan.get("operations") or []),
                      "errors": errs, "ok": not errs}
    _attach_command_timing(result, timing_state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errs else 1


def _cmd_build(args: argparse.Namespace) -> int:
    timing_state = _begin_command_timing("B3_BUILD", args.plan)
    plan = _load_plan(args.plan)
    drawing_path = getattr(args, "drawing", None)
    frozen_errs = check_plan(
        plan,
        executable=False,
        validate_embedded_thread_contract=not bool(drawing_path),
    )
    recipes: list[dict] = []
    geometries: list[dict] = []
    dispatches: list[dict] = []
    if drawing_path:
        frozen_errs.extend(_mode_b_source_drawing_errors(plan, drawing_path))
        _drawing, dispatches, drawing_errors = _drawing_modeling_context(
            drawing_path
        )
        frozen_errs.extend(drawing_errors)
        if not drawing_errors:
            frozen_errs.extend(capability_plan_errors(plan, dispatches))
            recipes, geometries = _thread_metadata_from_dispatches(dispatches)
    if frozen_errs:
        result = {
            "built": None,
            "operations": len(plan.get("operations") or []),
            "frozen_check_errors": frozen_errs,
            "ok": False,
        }
        _attach_command_timing(result, timing_state)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    exe = build_executable_plan(plan)
    build_conservation_errors = _build_geometry_conservation_errors(plan, exe)
    if build_conservation_errors:
        result = {
            "built": None,
            "operations": len(exe.get("operations") or []),
            "check_errors": build_conservation_errors,
            "ok": False,
        }
        _attach_command_timing(result, timing_state)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    if drawing_path:
        exe["thread_surrogates"] = recipes
        exe["thread_drawing_geometries"] = geometries
    errs = check_plan(
        exe,
        executable=True,
        validate_embedded_thread_contract=not bool(drawing_path),
    )
    if drawing_path and not frozen_errs:
        errs.extend(capability_plan_errors(exe, dispatches))
    if not errs:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(exe, f, ensure_ascii=False, indent=2)
    result = {"built": args.out if not errs else None,
                      "operations": len(exe.get("operations") or []),
                      "check_errors": errs, "ok": not errs}
    _attach_command_timing(result, timing_state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errs else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nx-mcp-plan-runner",
                                description="Generic plan-driven executor for nx-mcp-modeling-planner plans")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="execute an executable plan against the resident NX Loader")
    pr.add_argument("plan")
    pr.add_argument("--workspace", default=None)
    pr.add_argument("--report", default=None)
    pr.add_argument("--drawing", default=None,
                    help="optional Mode B drawing path binding; must match plan source_drawing")
    pr.add_argument("--mode", choices=("normal", "benchmark"), default="normal",
                    help="normal: never discard an unsaved part; "
                         "benchmark: allow overwriting the plan's own test part only")
    pr.add_argument("--allow-overwrite", action="store_true",
                    help="explicit permission to close the plan's test part without saving "
                         "(required in benchmark mode when the part is dirty)")
    pr.add_argument("--history", default=None,
                    help="run-history JSON (default: run_history.json next to runner.py)")
    pr.add_argument("--repair-attempt", type=int, choices=(0, 1), default=0,
                    help="0=normal first attempt; 1=the single allowed controlled repair attempt")
    pr.add_argument("--repair-report", default=None,
                    help="attempt-1 failed report; required when --repair-attempt 1")
    pr.set_defaults(func=_cmd_run)

    pc = sub.add_parser("check", help="static plan check (no NX)")
    pc.add_argument("plan")
    pc.add_argument("--frozen", action="store_true")
    pc.add_argument("--drawing", default=None,
                    help="optional Mode B drawing for capability-selected Gate B checks")
    pc.set_defaults(func=_cmd_check)

    pb = sub.add_parser("build", help="convert a frozen plan to the executable format (no NX)")
    pb.add_argument("plan")
    pb.add_argument("out")
    pb.add_argument("--drawing", default=None,
                    help="optional Mode B drawing for thread surrogate validation")
    pb.set_defaults(func=_cmd_build)

    pcontracts = sub.add_parser(
        "plan-contracts",
        help=(
            "resolve canonical drawing Feature Contracts into deterministic "
            "Planner operation contracts (no NX)"
        ),
    )
    pcontracts.add_argument("drawing")
    pcontracts.set_defaults(func=_cmd_plan_contracts)

    pcap = sub.add_parser(
        "capabilities",
        help="query static Feature Contract implementation capabilities (no NX)",
    )
    pcap.add_argument("--feature-kind", default=None)
    pcap.add_argument("--axis", choices=("X", "Y", "Z"), default=None)
    pcap.add_argument("--exact-only", action="store_true")
    pcap.add_argument("--registry", default=None)
    pcap.set_defaults(func=_cmd_capabilities)

    pd = sub.add_parser("validate-drawing", help="Gate A evidence/source validator (no NX)")
    pd.add_argument("drawing")
    pd.set_defaults(func=_cmd_validate_drawing)

    pcan = sub.add_parser(
        "canonicalize-drawing",
        help="losslessly canonicalize a semantic draft and write only after Gate A passes",
    )
    pcan.add_argument("draft")
    pcan.add_argument("out")
    pcan.set_defaults(func=_cmd_canonicalize_drawing)

    args = p.parse_args(argv)
    if inspect.iscoroutinefunction(args.func):
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
