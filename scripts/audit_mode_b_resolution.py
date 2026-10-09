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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze_bundle(args.bundle)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
