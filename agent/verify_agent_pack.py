#!/usr/bin/env python3
"""Static integrity checks for the bundled nx-agent + Plan Runner pack."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "nx-agent"
RUNNER = ROOT / "agent" / "nx-mcp-plan-runner"

REQUIRED = [
    "SKILL.md",
    "references/text-modeling.md",
    "references/drawing-reader.md",
    "references/modeling-planner.md",
    "references/nx-drawing-rules.md",
    "references/nx-mcp-rules.md",
    "references/topology-safety.md",
    "references/runner-contract.md",
    "references/certified-tool-contract.json",
    "references/pipeline-contract.md",
    "references/chinese-output.md",
    "examples/example-output.json",
    "examples/modeling-plan-example.json",
    "examples/pipeline-state-example.json",
]

OLD_SKILL_NAMES = ("nx-modeling", "nx-engineering-drawing-reader", "nx-mcp-modeling-planner", "nx-mcp-pipeline")


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> None:
    for rel in REQUIRED:
        if not (SKILL / rel).is_file():
            fail(f"missing nx-agent file: {rel}")

    top = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*(\S+)\s*$", top)
    if not match or match.group(1) != "nx-agent":
        fail("nx-agent frontmatter name mismatch")

    for md in (SKILL / "references").glob("*.md"):
        text = md.read_text(encoding="utf-8")
        if re.search(r"(?m)^name:\s*nx-", text):
            fail(f"standalone Skill frontmatter leaked into {md.name}")
        for old in OLD_SKILL_NAMES:
            if old in text:
                fail(f"legacy Skill name {old!r} remains in {md.name}")

    for rel in ("references/certified-tool-contract.json", "examples/example-output.json", "examples/modeling-plan-example.json", "examples/pipeline-state-example.json"):
        json.loads((SKILL / rel).read_text(encoding="utf-8"))

    for md in [SKILL / "SKILL.md", *(SKILL / "references").glob("*.md")]:
        text = md.read_text(encoding="utf-8")
        for rel in re.findall(r"`((?:references|examples)/[^`\s]+)`", text):
            if not (SKILL / rel).exists():
                fail(f"broken nx-agent reference in {md.name}: {rel}")

    sys.path.insert(0, str(RUNNER))
    import runner  # type: ignore  # noqa: E402

    contract = json.loads((SKILL / "references" / "certified-tool-contract.json").read_text(encoding="utf-8"))
    tools = set(contract["tools"])
    if tools != set(runner.CERTIFIED_TOOLS):
        fail("certified-tool-contract.json and Runner CERTIFIED_TOOLS differ")
    if len(tools) != 32:
        fail(f"expected 32 certified tools, got {len(tools)}")

    runner_examples: dict[str, dict] = {}
    for example in (RUNNER / "examples").glob("*.json"):
        data = json.loads(example.read_text(encoding="utf-8"))
        runner_examples[example.name] = data
        if "skill" in data and data["skill"] != "nx-agent":
            fail(f"runner example has stale skill metadata: {example.name}")

    frozen = runner_examples.get("modeling-plan-example.json")
    executable = runner_examples.get("modeling-plan-executable.json")
    if frozen is None or executable is None:
        fail("runner modeling examples are incomplete")

    if frozen.get("fallbacks") != executable.get("fallbacks"):
        fail("runner frozen/executable fallback safety rules differ")

    def validation_c(data: dict) -> dict:
        for item in data.get("final_validation", []):
            if str(item.get("check", "")).startswith("C."):
                return item
        return {}

    if validation_c(frozen).get("how") != validation_c(executable).get("how"):
        fail("runner frozen/executable final validation C differs")

    def step_56_hole_types(data: dict) -> set[str]:
        for op in data.get("operations", []):
            if op.get("step") == 56:
                face_type = (
                    op.get("selection_criteria", {})
                    .get("holes_reasonable", {})
                    .get("face_type")
                )
                if isinstance(face_type, str):
                    return {face_type}
                if isinstance(face_type, list):
                    return {str(x) for x in face_type}
        return set()

    expected_hole_types = {"Swept", "Cylindrical"}
    if step_56_hole_types(frozen) != expected_hole_types:
        fail("runner frozen example hole-face semantics are stale")
    if step_56_hole_types(executable) != expected_hole_types:
        fail("runner executable example hole-face semantics are stale")

    release_pin_files = [
        SKILL / "SKILL.md",
        *(SKILL / "references").glob("*.md"),
        RUNNER / "README.md",
        RUNNER / "runner.py",
    ]
    for md in release_pin_files:
        if "v2.1.1" in md.read_text(encoding="utf-8"):
            fail(f"stale release pin remains in Agent Pack rules/docs: {md.name}")

    centroid_rule_files = [
        SKILL / "references" / "modeling-planner.md",
        SKILL / "references" / "topology-safety.md",
        SKILL / "references" / "runner-contract.md",
    ]
    for rule_file in centroid_rule_files:
        text = rule_file.read_text(encoding="utf-8")
        if "全局 XY 原点" not in text or "diameter/2" not in text:
            fail(f"centroid_radius global-origin semantics missing in {rule_file.name}")

    output_rules = (SKILL / "references" / "chinese-output.md").read_text(encoding="utf-8")
    if 'report.status == "success"' not in output_rules:
        fail("user-visible success is not bound to Runner report status")

    loader_source = (ROOT / "loader" / "NX_MCP_Loader.cs").read_text(encoding="utf-8")
    principal_plane_tokens = [
        "_sketchPlanes",
        "CreateFixedTypePlane",
        "SketchPlaneMatrix",
        "SketchLocalXAxis",
        "b.PlaneReference = planeRef",
        "b.AxisReference = axisRef",
        "b.SketchOrigin = sketchOrigin",
        "b.PlaneOption = Sketch.PlaneOption.ExistingPlane",
        "b.OriginOption = OriginMethod.SpecifyPoint",
        "SketchPointForPlane",
        'case "XZ": return new Point3d(u, 0.0, v);',
        'case "YZ": return new Point3d(0.0, u, v);',
        "SketchExtrudeAxis",
        'case "XZ": return new Vector3d(0.0, 1.0, 0.0);',
        'case "YZ": return new Vector3d(1.0, 0.0, 0.0);',
    ]
    for token in principal_plane_tokens:
        if token not in loader_source:
            fail(f"principal-plane Loader regression: missing {token}")

    for token in (
        "NXOpen.Part work = _session.Parts.Work;",
        '"<unsaved-active-part>"',
        'return ErrJson("status failed: " + e.Message);',
        '"NX_MCP_WORKSPACE"',
        '"nx_mcp_loader.log"',
    ):
        if token not in loader_source:
            fail(f"Loader stale-part/workspace regression: missing {token}")

    loader_bridge_source = (ROOT / "src" / "nx_mcp" / "loader_bridge.py").read_text(encoding="utf-8")
    for token in ("last_ping_error", "loader status returned ok=false"):
        if token not in loader_bridge_source:
            fail(f"Loader ping diagnostic regression: missing {token}")

    install_agent = (ROOT / "install-agent.ps1").read_text(encoding="utf-8")
    if 'SetEnvironmentVariable("NX_MCP_WORKSPACE", $Workspace, "User")' not in install_agent:
        fail("install-agent.ps1 does not persist NX_MCP_WORKSPACE for Loader")

    if 'Get-Content -Raw -LiteralPath $_ -Encoding UTF8 | ConvertFrom-Json' not in install_agent:
        fail("install-agent.ps1 JSON validation is not PowerShell 5.1 UTF-8 safe")

    plane_rules = (SKILL / "references" / "nx-mcp-rules.md").read_text(encoding="utf-8")
    for token in ("XY→+Z", "XZ→+Y", "YZ→+X", 'nx_extrude(operation="subtract")'):
        if token not in plane_rules:
            fail(f"principal-plane planning contract missing: {token}")

    text_fast = (SKILL / "references" / "text-modeling.md").read_text(encoding="utf-8")
    for token in (
        "正常一次通过路径只需要本文件",
        "禁止递归搜索 runtime-config",
        "正常新零件任务**不主动读取**",
        "build/check 必须一次通过；成功后直接进入 Runner",
    ):
        if token not in text_fast:
            fail(f"text-mode Fast Path regression: missing {token}")

    for token in (
        "正常路径只读取",
        "禁止扫描 Skill 目录",
        "正常新零件任务禁止主动读取",
    ):
        if token not in top:
            fail(f"SKILL Mode A Fast Path regression: missing {token}")

    drawing_reader = (SKILL / "references" / "drawing-reader.md").read_text(encoding="utf-8")
    planner_rules = (SKILL / "references" / "modeling-planner.md").read_text(encoding="utf-8")
    pipeline_contract = (SKILL / "references" / "pipeline-contract.md").read_text(encoding="utf-8")
    for token in (
        "当前上传工程图",
        "唯一几何输入",
        "禁止在 interpretation 前读取、比较或引用其内容",
        "直接覆盖写入当前 `drawing.json`",
        "从零生成新的 frozen plan",
        "不得跳过 Planner",
        "--drawing <current-drawing>",
        "禁止主动读取或把工作区中的旧 frozen/executable plan",
        "禁止扫描工作区寻找“可复用”的历史 plan",
    ):
        if token not in top:
            fail(f"Mode B current-request isolation regression: missing {token}")
    for token in (
        "<NX_MCP_WORKSPACE>\\nx-mcp-plan-runner\\runtime-config.json",
        "只能读取",
        "runtime configuration missing",
        "禁止自动寻找其它 runtime-config",
        "禁止 fallback 到 `python` / `python3` / `py`",
        "`workspace_root` 与 `NX_MCP_WORKSPACE` 规范化后必须相同",
        "`nx_mcp_src` 只能取自当前 runtime-config",
        "本轮不得重新发现或切换 runtime",
        "drawing.json` / frozen plan / executable plan / report / PRT / STEP",
    ):
        if token not in top:
            fail(f"Mode B deterministic runtime regression: missing {token}")
    for token in (
        "当前 drawing JSON，并重新生成 frozen plan",
        "旧 frozen 存在不能成为跳过 Planner",
        "旧 frozen/executable/report/PRT/STEP",
        "--drawing <current-drawing>",
    ):
        if token not in planner_rules:
            fail(f"Mode B Planner isolation regression: missing {token}")
    for token in (
        "当前上传工程图 → 当前 drawing interpretation → 当前 drawing.json",
        "已有 `frozen-plan.json` 或 executable 不得作为输入",
        "不能直接 build/run 或进入 Runner",
        "不得扫描工作区判断是否存在“可用计划”",
        "build <current-frozen> <current-executable> --drawing <current-drawing>",
    ):
        if token not in pipeline_contract:
            fail(f"Mode B stale-workspace contract regression: missing {token}")
    for token in (
        "一次且仅一次 runtime discovery",
        "<NX_MCP_WORKSPACE>\\nx-mcp-plan-runner\\runtime-config.json",
        "只能读取这一份",
        "runtime configuration missing",
        "规范化后必须相同",
        "禁止 fallback 到 `python`、`python3`、`py`",
        "`nx_mcp_src` 必须原样取自当前 runtime-config",
        "本轮不得重新发现或切换 runtime",
        "drawing.json、frozen plan、executable plan、report、PRT 和 STEP",
    ):
        if token not in pipeline_contract:
            fail(f"Mode B runtime contract regression: missing {token}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install_doc = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    for token in ("所有 `Doubao.exe` 进程", "安装器不会自动终止 Doubao 进程"):
        if token not in readme:
            fail(f"Agent Pack deployment restart note missing: {token}")
    for token in ("every `Doubao.exe` process", "does not terminate Doubao"):
        if token not in install_doc:
            fail(f"Agent Pack installation restart note missing: {token}")
    for forbidden_kill in ("Stop-Process -Name Doubao", "taskkill /IM Doubao.exe"):
        if forbidden_kill.lower() in install_agent.lower():
            fail("install-agent.ps1 must not terminate Doubao")

    # Static simulation of the reported workspace shape. Agent behavior is
    # governed by the checked contract. Before interpretation, even an existing
    # drawing is stale output; only the newly uploaded image is an input.
    simulated_pre_interpretation = {
        "drawing.json": "stale",
        "frozen-plan.json": "stale",
        "executable-plan.json": "stale",
        "old.prt": "stale",
        "old.step": "stale",
        "report.json": "stale",
    }
    allowed_pre_interpretation_inputs = {"uploaded-engineering-drawing"}
    if any(
        name in allowed_pre_interpretation_inputs
        for name in simulated_pre_interpretation
    ):
        fail("Mode B pre-interpretation simulation permits a stale artifact")

    schema_retry_tokens = {
        "SKILL.md": (
            "machine schema-only normalization", "禁止读取 `examples/example-output.json`",
            "不得 retry", "首次 current `drawing.json`", "失败后禁止 Agent/LLM 覆盖",
        ),
        "pipeline-contract.md": (
            "machine schema-only normalization", "不得 schema retry",
            "不得读取 `examples/example-output.json`", "不得再次 validate 新 drawing",
            "原始诊断证据",
        ),
    }
    schema_retry_texts = {
        "SKILL.md": top,
        "pipeline-contract.md": pipeline_contract,
    }
    for name, tokens in schema_retry_tokens.items():
        for token in tokens:
            if token not in schema_retry_texts[name]:
                fail(f"Gate A schema-retry contract regression in {name}: missing {token}")

    runner_source = (RUNNER / "runner.py").read_text(encoding="utf-8")
    for token in (
        "def drawing_semantic_projection",
        "def normalize_drawing_schema",
        "normalizer semantic preservation check failed",
        "normalized feature dimension -> dimensions",
        "normalized feature center -> position.center",
    ):
        if token not in runner_source:
            fail(f"Runner drawing normalizer regression: missing {token}")
    for token in (
        "def resolve_metric_thread_parameters",
        "nominal_minus_pitch",
        "def resolve_thread_drawing_geometries",
        "def thread_surrogate_plan_errors",
        "changes axial range",
    ):
        if token not in runner_source:
            fail(f"Runner metric-thread regression: missing {token}")
    if "_THREAD_SURROGATE_RECIPES" in runner_source:
        fail("fixed per-designation thread surrogate recipes are forbidden")
    for token in (
        "def _begin_command_timing",
        "def _finish_command_timing",
        '"c1_runner_start_utc"',
        '"c2_modeling_complete_utc"',
        '"c3_export_complete_utc"',
        '"first_write_reliable": False',
    ):
        if token not in runner_source:
            fail(f"Runner command timing regression: missing {token}")
    for token in (
        '"nx_modeling_elapsed"',
        '"validation_ops_elapsed"',
        '"export_call_elapsed"',
        '"export_settle_elapsed"',
        '"preflight_elapsed"',
        '"final_validation_elapsed": round(validation_ops_elapsed, 3)',
    ):
        if token not in runner_source:
            fail(f"Runner timing regression: missing {token}")

    if "loader health check failed" not in runner_source or "ping_error()" not in runner_source:
        fail("Runner Loader health-check diagnostics regression")

    plan_tests = (RUNNER / "tests" / "test_plan_resolution.py").read_text(encoding="utf-8")
    if "test_transport_ping_error_passthrough" not in plan_tests:
        fail("Runner Loader ping diagnostic test missing")

    for token in (
        "frozen plan must not contain executable field",
        "frozen plan must not contain executable reference",
        "frozen_errs = check_plan(plan, executable=False)",
    ):
        if token not in runner_source:
            fail(f"Runner frozen/executable boundary regression: missing {token}")

    plan_tests = (RUNNER / "tests" / "test_plan_resolution.py").read_text(encoding="utf-8")
    for token in (
        "test_frozen_check_rejects_executable_only_fields",
        "test_frozen_check_rejects_dollar_references",
    ):
        if token not in plan_tests:
            fail(f"Runner frozen-boundary test missing: {token}")

    if "frozen check/build 对混入 executable 字段的 plan 必须 fail-closed" not in text_fast:
        fail("text-mode frozen/executable boundary rule missing")

    for token in (
        "Selection-consuming params must use the format-specific reference syntax.",
        'value.startswith("$selection.")',
        're.fullmatch(r"<step\\d+[^>]*>", value)',
    ):
        if token not in runner_source:
            fail(f"Runner selection-consumer reference regression: missing {token}")

    for token in (
        "test_frozen_check_rejects_bare_selection_consumer_name",
        "test_executable_check_rejects_unresolved_selection_consumer_name",
    ):
        if token not in plan_tests:
            fail(f"Runner selection-consumer test missing: {token}")

    if "<stepN ...>" not in text_fast or "禁止写裸语义名" not in text_fast:
        fail("text-mode selection consumer placeholder rule missing")

    if "纯计划表达错误" not in pipeline_contract or "result_bindings" not in pipeline_contract:
        fail("pipeline contract does not allow safe one-shot repair of binding-only plan errors")

    for token in (
        "禁止数值 nudge / epsilon 修复",
        "drawing、derived、frozen plan",
        "Z=50 → Z=49",
        "geometry-preserving",
    ):
        if token not in pipeline_contract:
            fail(f"pipeline numeric-nudge repair regression: missing {token}")
    for token in (
        "禁止 geometry / numeric nudge",
        "Z=50 → Z=49",
        "精确相切/共面",
    ):
        if token not in top:
            fail(f"top-level numeric-nudge repair regression: missing {token}")

    drawing_reader = (SKILL / "references" / "drawing-reader.md").read_text(encoding="utf-8")
    drawing_rules = (SKILL / "references" / "nx-drawing-rules.md").read_text(encoding="utf-8")
    for token in (
        "view-local",
        "projection alignment",
        "leader/witness endpoint",
        "`axis=X`→Y/Z",
        "center_distance / center_spacing",
        "opposite endpoint target",
        "`edge_offset` 不得作为 derived expression",
        "`profile_dimension` 只用于两个 endpoints",
    ):
        if token not in drawing_reader:
            fail(f"drawing relation contract regression: missing {token}")
    for token in (
        "view-local evidence → feature association → dimension ownership → relation/derived → global coordinates",
        "axial projection candidate",
        "axis=X→Y/Z",
        "datum→centerline",
        "centerline↔centerline",
        "profile boundary↔profile boundary",
    ):
        if token not in drawing_rules:
            fail(f"quick drawing relation contract regression: missing {token}")

    for token in (
        "线性尺寸先按两个实际 endpoints",
        "不因路径经过 step/thickness 再叠加",
        "两个 endpoints 都是 center coordinates",
        "profile_dimension` 只用于两个 endpoints",
        "同轴候选先按 projection alignment",
        "thread projection 必须先按 projection alignment",
        "而不是因缺少 direct dimension 进入 blocking unresolved",
    ):
        if token not in drawing_reader:
            fail(f"drawing ownership/association contract regression: missing {token}")
    for token in (
        "datum→centerline",
        "centerline↔centerline",
        "outer min/max edge→centerline",
        "profile boundary↔profile boundary",
        "相同数值但 endpoints 不同",
    ):
        if token not in drawing_rules:
            fail(f"quick ownership contract regression: missing {token}")

    ownership_fixture_path = RUNNER / "tests" / "fixtures" / "drawing-ownership-cases.json"
    ownership_fixture = json.loads(ownership_fixture_path.read_text(encoding="utf-8"))
    ownership_cases = {
        item.get("id"): item for item in ownership_fixture.get("cases") or []
    }
    expected_ownership_cases = {
        "datum_to_centerline_ignores_intermediate_step",
        "intermediate_surface_to_centerline_uses_local_conversion",
        "centerline_to_centerline_is_relation",
        "known_center_plus_distance_derives_opposite_center",
        "coaxial_members_share_group_centerline",
        "max_edge_to_center_is_edge_offset",
        "min_edge_to_center_is_edge_offset",
        "feature_center_dimension_is_not_profile_dimension",
        "profile_boundary_pair_allows_profile_dimension",
        "equal_values_keep_endpoint_specific_ownership",
    }
    if set(ownership_cases) != expected_ownership_cases:
        fail("drawing ownership fixture case set drifted")

    datum_case = ownership_cases["datum_to_centerline_ignores_intermediate_step"]
    if (
        datum_case["expected"].get("global_value") != datum_case["dimension"].get("value")
        or "feature:F_STEP.thickness" not in datum_case["expected"].get("must_not_add", [])
    ):
        fail("datum-to-centerline fixture re-adds intermediate thickness")
    intermediate_case = ownership_cases["intermediate_surface_to_centerline_uses_local_conversion"]
    if (
        intermediate_case["expected"].get("writer") != "derived"
        or intermediate_case["expected"].get("expr_refs")
        != [
            intermediate_case["endpoints"][0].get("target"),
            intermediate_case["dimension"].get("source_id"),
        ]
    ):
        fail("intermediate-surface fixture is not local-to-global derived")
    center_case = ownership_cases["centerline_to_centerline_is_relation"]
    if (
        center_case["expected"].get("semantic") != "center_distance"
        or center_case["expected"].get("between")
        != [item["target"] for item in center_case["endpoints"]]
    ):
        fail("centerline distance fixture lost endpoint relation")
    derived_center_case = ownership_cases["known_center_plus_distance_derives_opposite_center"]
    if derived_center_case["expected"].get("expr_refs") != [
        derived_center_case.get("known_target"), derived_center_case.get("relation_source")
    ]:
        fail("derived center fixture lost known-target/relation provenance")
    coaxial_case = ownership_cases["coaxial_members_share_group_centerline"]
    if (
        coaxial_case["expected"].get("member_centerline_policy") != "inherit_group"
        or not {
            "concentric_circles", "orthographic_hidden_parallel_lines",
            "shared_centerline", "projection_alignment",
        }.issubset(coaxial_case.get("association_evidence") or [])
    ):
        fail("coaxial fixture no longer inherits the group centerline")
    if ownership_cases["max_edge_to_center_is_edge_offset"]["expected"].get("from") != "max":
        fail("max-edge fixture lost edge_offset ownership")
    if ownership_cases["min_edge_to_center_is_edge_offset"]["expected"].get("from") != "min":
        fail("min-edge fixture lost edge_offset ownership")
    feature_center_case = ownership_cases["feature_center_dimension_is_not_profile_dimension"]
    if (
        feature_center_case["expected"].get("semantic") != "edge_offset"
        or "profile_dimension"
        not in feature_center_case["expected"].get("forbidden_semantics", [])
    ):
        fail("feature-center fixture permits profile pollution")
    if ownership_cases["profile_boundary_pair_allows_profile_dimension"]["expected"].get("semantic") != "profile_dimension":
        fail("profile-boundary fixture lost profile ownership")
    equal_value_case = ownership_cases["equal_values_keep_endpoint_specific_ownership"]
    equal_dimensions = equal_value_case.get("dimensions") or []
    if (
        len({item.get("value") for item in equal_dimensions}) != 1
        or len({item.get("source_id") for item in equal_dimensions}) != len(equal_dimensions)
        or len({item.get("expected_semantic") for item in equal_dimensions}) != len(equal_dimensions)
        or equal_value_case["expected"].get("merge_sources") is not False
    ):
        fail("equal-value fixture merges endpoint-specific ownership")

    for token in (
        "最小 canonical contract",
        "length_x / width_y / height_z",
        "稳定 `id` 和非空 `type`",
        "Runner 不要求所有 feature 一律输出 count",
        "`target` 必须是实际可解析 path",
        "若 source 包含 `value`",
        "relation source 不写 direct `target`",
        "`edge_offset` 不得作为 derived expression",
        "opposite endpoint target",
        "ancestor target",
        "placeholder `0`",
        "dimension_conflicts",
        "`from=min`: `coordinate = min_edge + value`；`from=max`: `coordinate = max_edge - value`",
        "{\"source\": \"S_SPACING\"}",
        "`type→feature_kind`",
        "overall/body edge→feature center 使用 `edge_offset`",
        "profile.segments.0.y1",
        "feature:F_HOLES.explicit_centers.0.x",
        "{\"const\": 8}",
        "Canonical writer finalization",
        "Reader first-pass self-consistency",
        "禁止 direct + derived 同 target",
        "relation 已提供 coverage 后禁止再为该 target 生成 direct/derived",
        "`X=[-length_x/2,+length_x/2]`",
        "局部 profile/body/step boundary 不使用 overall bbox",
        "不表示 Runner 已实现普遍的 exactly-one-writer 合同",
    ):
        if token not in drawing_reader:
            fail(f"minimal Reader canonical contract regression: missing {token}")

    canonical_fixture_path = RUNNER / "tests" / "fixtures" / "canonical-reader-output.json"
    canonical_fixture = json.loads(canonical_fixture_path.read_text(encoding="utf-8"))
    required_drawing_roots = {
        "overall_dimensions", "coordinate_system", "features", "source_ledger",
        "derived", "unresolved", "dimension_conflicts", "dimension_closure",
    }
    if not required_drawing_roots.issubset(canonical_fixture):
        fail("canonical Reader fixture is missing a Gate A root")
    if set(canonical_fixture.get("overall_dimensions") or {}) != {
        "length_x", "width_y", "height_z",
    }:
        fail("canonical Reader fixture overall dimensions drifted")
    forbidden_reader_keys = {
        "kind", "center_x", "center_y", "center_z", "open_from_z",
        "thread_spec", "x_start", "through_diameter", "cbore_diameter",
        "cbore_depth",
    }

    def collect_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                key
                for child in value.values()
                for key in collect_keys(child)
            }
        if isinstance(value, list):
            return {key for child in value for key in collect_keys(child)}
        return set()

    bad_fixture_keys = forbidden_reader_keys & collect_keys(canonical_fixture)
    if bad_fixture_keys:
        fail(f"canonical Reader fixture uses forbidden aliases: {sorted(bad_fixture_keys)}")
    if not (canonical_fixture.get("profile") or {}).get("segments"):
        fail("canonical Reader fixture lacks a segments-based profile")
    direct_targets = {
        item.get("target")
        for item in canonical_fixture.get("source_ledger") or []
        if item.get("semantic") not in {
            "center_distance", "center_spacing", "edge_offset", "symmetry",
            "upper_tangent", "lower_tangent", "coincident", "alignment",
        }
    }
    for feature in canonical_fixture.get("features") or []:
        feature_id = feature.get("id")
        if (
            f"feature:{feature_id}.type" not in direct_targets
            or f"feature:{feature_id}.count" not in direct_targets
        ):
            fail("canonical Reader fixture feature lacks type/count provenance")

    drawing_tests = (RUNNER / "tests" / "test_drawing_validation.py").read_text(encoding="utf-8")
    for token in (
        "test_canonical_reader_fixture_passes_machine_gate_a",
        "test_canonical_reader_fixture_covers_required_field_contracts",
        "test_canonical_reader_source_targets_resolve_and_match_semantics",
        "test_free_label_center_distance_endpoints_are_rejected",
        "test_relation_source_cannot_use_direct_target_shape",
        "test_dimension_conflicts_is_a_required_root",
        "test_normalizer_does_not_rename_noncanonical_semantic_fields",
        "test_unresolved_center_has_no_concrete_placeholder_or_writer",
        "test_known_centers_have_exactly_one_writer_and_no_unresolved",
        "test_reader_fixtures_do_not_mix_concrete_and_same_field_unresolved",
        "test_direct_source_value_must_equal_actual_target",
        "test_center_distance_derived_and_fake_direct_writer_conflict",
        "test_required_feature_type_and_count_have_provenance",
        "test_canonical_profile_is_provenance_complete",
        "test_profile_join_endpoints_are_derived_not_direct",
        "test_center_spacing_derived_references_opposite_endpoint",
    ):
        if token not in drawing_tests:
            fail(f"canonical Reader regression test missing: {token}")

    for token in (
        "def _drawing_unresolved_geometry_pattern",
        "def _drawing_expand_target_pattern",
        "unresolved geometry has concrete placeholder",
    ):
        if token not in runner_source:
            fail(f"Runner unresolved-geometry coherence guard missing: {token}")
    for token in (
        "test_blocking_unresolved_centerline_with_concrete_value_fails",
        "test_blocking_unresolved_explicit_center_wildcard_with_zero_fails",
        "test_blocking_unresolved_profile_coordinate_with_concrete_value_fails",
        "test_nonblocking_warning_does_not_conflict_with_known_geometry",
    ):
        if token not in drawing_tests:
            fail(f"unresolved-geometry regression test missing: {token}")

    timing_tests = (RUNNER / "tests" / "test_bbox_report.py").read_text(encoding="utf-8")
    if "test_timing_bucket_separates_postprocess_from_validation" not in timing_tests:
        fail("Runner timing phase regression test missing")

    for ps1 in (ROOT / "install.ps1", ROOT / "install-agent.ps1"):
        if not ps1.read_bytes().startswith(b"\xef\xbb\xbf"):
            fail(f"{ps1.name} must keep UTF-8 BOM for Windows PowerShell 5.1")

    installer = (ROOT / "install.ps1").read_text(encoding="utf-8")
    if 'pip install -e ".[dev]"' in installer:
        fail("normal install.ps1 must not install development extras")
    if 'pip install -e "."' not in installer:
        fail("normal install.ps1 is missing runtime-only editable install")

    print("Agent Pack static verification passed")


if __name__ == "__main__":
    main()
