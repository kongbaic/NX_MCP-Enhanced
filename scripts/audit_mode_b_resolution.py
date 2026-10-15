"""Read-only analysis of multiple Fresh Mode B evidence bundles.

Never resumes terminal tasks or treats a smaller blocker count as Gate A PASS.
The report distinguishes Resolver's unresolved count from Semantic Draft's
expanded records, and includes originating OCR and Capture evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

_RUN_FILE = re.compile(
    r"(hybrid-run-[^/]+-mode-b)/(frontend|coordinator)/([^/]+\.json)$"
)


def _decode(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("evidence file must be a JSON object")
    return value


def load_bundle(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Windows ZIPs may store literal backslash paths; normalize in memory."""
    found: dict[str, dict[str, dict[str, Any]]] = {}
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            match = _RUN_FILE.search(name)
            if not match or member.is_dir():
                continue
            run_id, scope, filename = match.groups()
            if filename not in {
                "hybrid-ocr-report.json",
                "reader-capture.json",
                "reader-observations.json",
                "hybrid-adapter-context.json",
            } and not filename.endswith((
                "-mode-b-state.json",
                "-reader-capture.json",
                "-semantic-draft.json",
            )):
                continue
            run = found.setdefault(run_id, {})
            location = run.setdefault(scope, {})
            if filename in location:
                raise ValueError(f"duplicate bundle entry: {run_id}/{scope}/{filename}")
            location[filename] = _decode(archive.read(member))
    return found


def _file(files: dict[str, Any], suffix: str) -> dict[str, Any]:
    candidates = [
        value for name, value in files.items()
        if name == suffix or name.endswith(suffix)
    ]
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one {suffix!r}; found {len(candidates)}")
    return candidates[0]


def _category(item: dict[str, Any]) -> str:
    # Diagnostic buckets only; never establish engineering truth.
    identifier = str(item.get("id") or "")
    field = str(item.get("field") or "")
    if identifier.startswith("relation:"):
        return "constraint_missing_prerequisite"
    if field in {
        "unassigned_linear_text", "local_only_linear_text",
        "unconfirmed_linear_proposal", "secondary_linear_assignment",
    }:
        return "ocr_assignment"
    if field in {
        "start_side", "material_side", "entry_endpoint",
        "engineering_callout_geometry_binding", "recessed_hole_subtype",
    }:
        return "feature_semantics"
    if identifier.startswith("U_DIM_"):
        return "dimension_endpoint_ownership"
    return "other_preserved_blocker"


def analyze_run(run_id: str, scopes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    frontend = scopes.get("frontend", {})
    coordinator = scopes.get("coordinator", {})
    ocr = _file(frontend, "hybrid-ocr-report.json")
    state = _file(coordinator, "-mode-b-state.json")
    capture = _file(coordinator, "-reader-capture.json")
    draft = _file(coordinator, "-semantic-draft.json")

    candidates = ocr.get("candidates", [])
    accepted = {
        str(item["candidate_id"]): str(item["accepted_token"])
        for item in candidates
        if isinstance(item, dict) and item.get("accepted_token") is not None
    }
    blocking = [
        item for item in draft.get("unresolved", [])
        if isinstance(item, dict) and item.get("required_for_modeling", True)
    ]
    dimension_by_id = {
        str(item["id"]): item
        for item in capture.get("dimensions", [])
        if isinstance(item, dict) and item.get("id")
    }
    dimensions = []
    for identifier, item in sorted(dimension_by_id.items()):
        reasons = [
            {"id": row.get("id"), "reason": row.get("reason")}
            for row in blocking
            if (
                str(row.get("id") or "").startswith(f"relation:{identifier}:")
                or str(row.get("id") or "") == f"U_DIM_{identifier}"
            )
        ]
        dimensions.append({
            "id": identifier,
            "axis": item.get("axis"),
            "value": item.get("value"),
            "direction": item.get("direction"),
            "endpoints": [
                {"role": end.get("role"), "entity_id": end.get("entity_id"),
                 "unresolved_kind": end.get("unresolved_kind")}
                for end in item.get("endpoints", []) if isinstance(end, dict)
            ],
            "source_ids": item.get("source_ids", []),
            "linked_blockers": reasons,
        })
    return {
        "run": run_id,
        "phase": state.get("phase"),
        "ocr": {
            "candidate_count": ocr.get("candidate_count"),
            "accepted_count": ocr.get("accepted_count"),
            "accepted": accepted,
        },
        "resolver": {
            "reported_blocking_unresolved": state.get("summary", {}).get(
                "blocking_unresolved"
            ),
            "dimension_closure": state.get("summary", {}).get("dimension_closure"),
        },
        "draft": {
            "expanded_blocker_records": len(blocking),
            "diagnostic_categories": dict(sorted(Counter(
                _category(item) for item in blocking
            ).items())),
            "blockers": [
                {"id": x.get("id"), "target": x.get("target"),
                 "field": x.get("field"), "reason": x.get("reason"),
                 "category": _category(x)}
                for x in blocking
            ],
        },
        "dimensions": dimensions,
        "warning": (
            "Read-only diagnosis. Neither accepted OCR counts nor fewer blockers "
            "prove geometric correctness or authorize bypassing Gate A."
        ),
    }


def analyze_bundle(path: Path) -> dict[str, Any]:
    loaded = load_bundle(path)
    if not loaded:
        raise ValueError("bundle contains no Fresh Mode B runs")
    runs = [analyze_run(run, scopes) for run, scopes in sorted(loaded.items())]
    changes: list[dict[str, Any]] = []
    for before, after in zip(runs[:-1], runs[1:], strict=True):
        left, right = before["ocr"]["accepted"], after["ocr"]["accepted"]
        changes.append({
            "before": before["run"], "after": after["run"],
            "accepted_added": {k: v for k, v in right.items() if k not in left},
            "accepted_removed": {k: v for k, v in left.items() if k not in right},
            "accepted_changed": {
                k: {"before": left[k], "after": right[k]}
                for k in left.keys() & right.keys() if left[k] != right[k]
            },
            "resolver_blocker_count_change": (
                after["resolver"]["reported_blocking_unresolved"]
                - before["resolver"]["reported_blocking_unresolved"]
                if isinstance(after["resolver"]["reported_blocking_unresolved"], int)
                and isinstance(before["resolver"]["reported_blocking_unresolved"], int)
                else None
            ),
        })
    return {"schema": "mode-b-evidence-audit-v1", "runs": runs,
            "comparisons": changes, "production_artifacts_modified": False}



def analyze_current_replay(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit current Resolver evidence, never stale Mode B state.

    Categories are diagnostic queues, not engineering facts or permission to
    weaken a modeling blocker. An unresolved signed relation stays unresolved.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("pipeline"), dict):
        raise ValueError("current replay is missing its pipeline")
    if payload["pipeline"].get("resolved") is not True:
        raise ValueError("current replay has not completed Resolver")
    resolution = payload.get("resolution")
    compiled = payload.get("compiled")
    capture = payload.get("capture")
    if not all(isinstance(part, dict) for part in (resolution, compiled, capture)):
        raise ValueError("current replay is missing resolution, compiled, or capture")
    unresolved = resolution.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("current replay is missing Resolver unresolved records")

    relations = {
        item["id"]: item
        for item in compiled.get("relations", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    dimensions = {
        item["id"]: item
        for item in capture.get("dimensions", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    review_tracks = {
        "constraint_missing_prerequisite": ["A", "B", "C"],
        "dimension_endpoint_ownership": ["B", "C"],
        "ocr_assignment": ["B", "C", "D"],
        "feature_semantics": ["B", "C"],
        "feature_geometry_binding": ["B", "C"],
        "other_preserved_blocker": ["A", "B", "C", "D"],
    }
    blockers: list[dict[str, Any]] = []
    for item in unresolved:
        if not isinstance(item, dict):
            raise ValueError("current Resolver has a non-object unresolved record")
        if item.get("required_for_modeling", True) is False:
            continue
        identifier = str(item.get("id") or "")
        relation = (
            relations.get(identifier.removeprefix("relation:"))
            if identifier.startswith("relation:")
            else None
        )
        dimension = (
            dimensions.get(identifier.removeprefix("U_DIM_"))
            if identifier.startswith("U_DIM_")
            else None
        )
        source_ids = list(dict.fromkeys(
            source_id
            for source_id in [
                *(item.get("source_ids") or []),
                *((relation or {}).get("source_ids") or []),
            ]
            if isinstance(source_id, str) and source_id
        ))
        category = (
            "feature_geometry_binding"
            if item.get("field") == "engineering_callout_geometry_binding"
            else _category(item)
        )
        blockers.append({
            "id": identifier,
            "kind": item.get("kind"),
            "field": item.get("field"),
            "reason": item.get("reason"),
            "targets": item.get("targets") or [],
            "source_ids": source_ids,
            "category": category,
            "candidate_review_tracks": review_tracks[category],
            "review_status": "needs_evidence_classification",
            "relation": relation,
            "capture_dimension": dimension,
        })

    draft = payload.get("draft")
    draft_unresolved = (
        draft.get("unresolved", []) if isinstance(draft, dict) else []
    )
    expanded = [
        item for item in draft_unresolved
        if isinstance(item, dict) and item.get("required_for_modeling", True)
    ]
    return {
        "schema": "mode-b-current-replay-audit-v1",
        "resolver_blocking_count": len(blockers),
        "draft_expanded_blocker_records": len(expanded),
        "resolver_conflict_count": len(resolution.get("conflicts") or []),
        "gate_a_pass": payload.get("gate_a_pass") is True,
        "gate_a_errors": payload.get("gate_a_errors") or [],
        "diagnostic_categories": dict(sorted(Counter(
            item["category"] for item in blockers
        ).items())),
        "blockers": blockers,
        "ocr_reexecuted": payload.get("ocr_reexecuted"),
        "production_artifacts_modified": False,
        "warning": (
            "A/B/C/D are possible review tracks, not automatic decisions. "
            "No missing dimension, machining direction, or annotation type "
            "has been inferred; original Gate A blockers remain unchanged."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bundle", type=Path)
    group.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = (
        analyze_bundle(args.bundle)
        if args.bundle is not None
        else analyze_current_replay(_decode(args.replay.read_bytes()))
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
