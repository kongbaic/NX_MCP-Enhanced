from __future__ import annotations

import json
from pathlib import Path

from nx_mcp.drawing_intelligence import (
    EvidenceGraph,
    build_semantic_draft,
    compile_evidence_graph,
    resolve_evidence_graph,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "shkss20-40-first-pass-evidence.json"
)


def test_real_shkss_first_pass_fixture_resolves_supported_geometry_and_blocks_guessing():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    graph = EvidenceGraph.model_validate(raw)

    compiled = compile_evidence_graph(graph)
    result = resolve_evidence_graph(compiled)
    draft = build_semantic_draft(compiled, result)

    values = result.values

    assert values["feature:F_MAIN_HOLE.centerline.x"] == 20
    assert values["feature:F_MAIN_HOLE.centerline.z"] == 40
    assert values["feature:F_CLAMP_CLEARANCE.centerline.y"] == 24
    assert values["feature:F_CLAMP_CLEARANCE.centerline.z"] == 58
    assert values["feature:F_M6.centerline.y"] == 24
    assert values["feature:F_M6.centerline.z"] == 58

    assert "feature:F_MOUNT_PAIR.explicit_centers.0.1" not in values
    assert "feature:F_MOUNT_PAIR.explicit_centers.1.1" not in values

    assert "feature:F_MOUNT_PAIR.explicit_centers.0.0" not in values
    assert "feature:F_MOUNT_PAIR.explicit_centers.1.0" not in values

    assert values["feature:F_SLOT.centerline.x"] == 20
    assert values["feature:F_SLOT.bottom_z"] == 50
    assert values["feature:F_SLOT.top_z"] == 66

    assert not result.ok
    assert draft["dimension_closure"]["status"] == "incomplete"

    blocking_targets = {
        target
        for item in result.unresolved
        if item.get("required_for_modeling", True)
        for target in (
            item.get("targets")
            if isinstance(item.get("targets"), list)
            else [item.get("target")]
        )
        if isinstance(target, str)
    }

    assert "feature:F_MOUNT_PAIR.explicit_centers.0.0" in blocking_targets
    assert "feature:F_MOUNT_PAIR.explicit_centers.1.0" in blocking_targets
    assert "feature:F_MOUNT_PAIR.explicit_centers.0.1" in blocking_targets
    assert "feature:F_MOUNT_PAIR.explicit_centers.1.1" in blocking_targets
    assert "feature:F_BODY.profile" in blocking_targets
    assert "feature:F_M6.start_side" in blocking_targets
    assert "feature:F_CLAMP_CLEARANCE.start_side" in blocking_targets
