---
name: nx-agent
description: 作者：抖音 无趣。Siemens NX 自动建模统一入口。支持文字描述建模、工作区内已保存零件的安全修改，以及二维机械工程图自动读取→建模规划→Plan Runner 执行→输出 PRT/STEP；遵守拓扑安全、阶段门禁与 Controlled Self-Healing（受控自动修复）规则。
---

# NX Agent — Siemens NX 自动建模统一入口

本 Skill 是 NX_MCP-Enhanced 的唯一用户入口。对外只显示一个 Skill，对内按模块化规则执行。

## 1. 自动选择模式

### 模式 A：文字描述建模（Fast Path）
用户直接用文字描述零件、尺寸、孔位、圆角、倒角等要求时：

1. **正常路径只读取** `references/text-modeling.md` 与
   `references/certified-tool-contract.json`；本 `SKILL.md` 已包含阶段 C、
   拓扑和输出硬规则。禁止为了“确认规则”重复读取其它 reference。
2. 不经过工程图读取模块；把明确文字尺寸直接整理为结构化建模意图。
3. 按 `text-modeling.md` 的固定 runtime-config 路径一次定位 Runner；
   **禁止扫描 Skill 目录、仓库目录、安装脚本、Python 环境或聊天目录**。
4. 正常新零件任务禁止主动读取 `run_history.json`、旧 frozen/executable plan、
   旧 report 或旧 PRT/STEP 内容。历史安全判断由 Runner preflight 自己完成。
5. 直接生成 frozen plan → build/check → Plan Runner。
6. 只有以下触发条件才读取详细 reference：
   - build/check 明确报告 schema/contract incompatibility → `runner-contract.md`；
   - attempt 1 失败且符合 Controlled Self-Healing → `pipeline-contract.md` +
     与失败类型直接相关的 `topology-safety.md`；
   - 用户明确要求解释底层 Planner 规则 → 再读取对应详细文档。
   正常一次通过路径不得预读这些文件。

默认用于创建新零件。修改已有零件时，仅允许打开 `NX_MCP_WORKSPACE` 内、用户明确指定路径的已保存零件；不得自动接管无关或未保存的当前零件。

### 模式 B：二维机械工程图自动建模
用户上传二维机械工程图并要求“开始建模”“按图建模”“用 NX 画出来”等时：

1. 在开始 drawing interpretation 前，按“运行时与路径”的 Mode B 规则只定位并读取一次 `runtime-config.json`；本轮固定使用该 runtime，之后不得重新发现或切换 runtime。
2. 读取 `references/drawing-reader.md` + `references/nx-drawing-rules.md`。
3. 当前上传工程图是本轮 interpretation 的唯一几何输入。Reader 在内存中形成一次完整 first-pass semantic JSON payload；不得 Write/Edit `semantic-draft.json` 或 `drawing.json`，也不得创建 candidate/临时语义文件。
4. 将该 payload 通过 stdin 一次且仅一次提交给 `runner.py submit-semantic-draft <semantic-draft.json> <drawing.json>`。该命令独占创建 draft，并在同一进程立即完成 deterministic canonicalization 与 Gate A。
5. 只有 process exit code = 0 且实际返回 `submission_accepted=true`、`canonicalization_attempted=true`、`written=true`、`output_exists=true`，才允许进入 Planner；`drawing.json` 只能由这次成功 submission 生成。
6. 任一其它结果（包括 `already_submitted`、`workspace_not_clean`、malformed payload、normalization/Gate A failure）均立即 `BLOCKED / STOP`。禁止第二次 submit、retry、重新 interpretation、改写/删除 draft、手写 drawing、直接调用 `canonicalize-drawing`、单独调用 `validate-drawing`，或进入 Planner。
7. 成功后根据**本轮 canonical drawing.json 从零生成新的 frozen plan**；即使工作区已有同名 plan 或相同零件，也不得跳过 Planner。
8. 固定执行 `runner.py build <current-frozen> <current-executable> --drawing <current-drawing>`，随后 check 当前 executable，再调用 Runner。
9. 本轮 drawing interpretation 开始后，禁止主动读取或把工作区中的旧 frozen/executable plan、旧 report、旧 `run_history.json`、旧 PRT/STEP、其它历史零件的 drawing/plan 当作当前任务输入或规划参考。允许覆盖固定输出文件名，但内容必须由当前请求重新生成。
10. 禁止扫描工作区寻找“可复用”的历史 plan；文件名、零件类型或尺寸看起来相同也不构成复用依据。
11. 总控规则见 `references/pipeline-contract.md`；用户输出规范见 `references/chinese-output.md`。

两条链路：

```text
文字描述 → 建模规划 → Plan Runner → Siemens NX → PRT + STEP

二维工程图 → semantic payload → one-shot submission + deterministic canonicalization → 建模规划 → Plan Runner → Siemens NX → PRT + STEP
```

## 2. 运行时与路径

安装器会在 Plan Runner 目录生成 `runtime-config.json`。Mode B 必须使用以下确定性发现规则：

1. 要求环境变量 `NX_MCP_WORKSPACE` 非空，并且只能读取：
   `<NX_MCP_WORKSPACE>\nx-mcp-plan-runner\runtime-config.json`。
2. 禁止扫描用户目录、仓库目录、其它 `NX_MCP_WORKSPACE*`、历史 CLEAN workspace、聊天目录、安装目录列表或 Python 环境来寻找其它 runtime-config。
3. 环境变量缺失、该唯一文件不存在或必需字段缺失时，立即停止并报告 `runtime configuration missing`；禁止自动寻找其它 runtime-config。
4. 读取后原样使用其中的：

- `python_exe`
- `workspace_root`
- `nx_mcp_src`

`python_exe` 必须是 runtime-config 指定且实际存在的文件；禁止 fallback 到 `python` / `python3` / `py`、系统 Python 或 PATH 中其它 Python。`workspace_root` 与 `NX_MCP_WORKSPACE` 规范化后必须相同，否则 fail closed。`nx_mcp_src` 只能取自当前 runtime-config，不得从历史仓库、备份仓库或其它 workspace 推断。

当前 `semantic-draft.json` / `drawing.json` / frozen plan / executable plan / report / PRT / STEP 都必须只落在该 `workspace_root`。其它目录中已有文件不能触发 workspace 切换。runtime 一旦解析，本轮不得重新发现或切换 runtime。

## 3. 模式选择优先级

1. 有工程图且用户要求依据图纸建模 → 模式 B。
2. 没有工程图、用户直接给明确几何要求 → 模式 A。
3. 工程图 + 补充文字同时存在：工程图为几何主来源；补充文字仅作为明确附加约束。发生冲突必须停止并报告。
4. 禁止把工程图任务退化成“看图后直接手工调用 NX_MCP”。
5. 禁止让纯文字建模任务无意义地走工程图读取。

## 4. 工程图门禁

### 门禁 A
- Reader 不写 artifact；完整 semantic payload 只通过 stdin 一次提交给 `runner.py submit-semantic-draft <semantic-draft.json> <drawing.json>`，由命令独占创建 immutable first-pass draft，并立即执行 representation-only normalization、preservation guards 与 Gate A。
- 只有 exit code = 0、`submission_accepted=true`、`canonicalization_attempted=true`、`written=true`、`output_exists=true` 才算 PASS；此时 `drawing.json` 是本轮唯一正式 canonical artifact。
- 其它结果立即 `BLOCKED / STOP`。失败时保留首次 draft，`drawing.json` 不存在；禁止第二次提交、retry、删除/改写 draft、手写 drawing、直接 `canonicalize-drawing`、单独 `validate-drawing` 或进入 Planner。
- Canonicalizer 不补 geometry、ownership、relation 或 unresolved。Reader semantic 缺失和真实冲突必须保持失败，不得读取 example 或重新看图修到通过。

### 门禁 B
- 当前 frozen plan 必须由本轮 Gate A PASS 的 drawing JSON 新生成
- runner build 必须带 `--drawing <current-drawing>`，随后 build/check 通过
- unresolved reference = 0
- illegal tool_args = 0
- natural language placeholder = 0
- executable plan 存在且非空

frozen plan 首次落盘前必须完成静态自检。B 阶段 build/check 失败直接结束，禁止现场补丁后继续。

## 5. 阶段 C 与受控自动修复

- 单次 Runner 尝试严格 fail-fast：任意 modeling step 失败，当前尝试立即停止。
- 每个任务最多允许 1 次 Controlled Self-Healing。
- 只允许修复根因明确、且不改变尺寸/位置/特征数量/几何语义的计划级问题。
- 典型允许：edge/face `selection_criteria` 过严、Loader 已冻结的类型语义差异。
- 禁止：猜尺寸、改图纸、改变主体结构、绕过能力边界、修改 Runner/NX_MCP/Loader。
- 禁止 geometry / numeric nudge：drawing、derived、frozen plan 中的 coordinate、start/end、slot bottom、hole center、diameter、depth、thickness、radius、chamfer、fillet 均不可改写，例如 `Z=50 → Z=49`。精确相切/共面导致 Boolean 失败且无 geometry-preserving 修复路径时必须失败。
- 修复后必须重新 build/check，并由 Runner 安全 preflight 丢弃本任务自己的失败零件，然后从第 1 步完整重跑。
- 禁止从失败步骤续跑。
- 第二次失败必须结束。

## 6. 拓扑与选择规则

- edge / face index 都是临时数据；任何拓扑变化后旧 index 立即失效。
- Linear 边 `direction` 只能是 `"X"|"Y"|"Z"|"OTHER"`。
- 四角竖边优先 `corners_xy + bbox_z/midpoint_z`。
- Circular / Elliptical / Conical 曲线边禁止 bbox 类条件。
- 完整圆边优先 `curve_type:["Elliptical","Circular"] + length + midpoint_z + expectation.count`。
- 唯一顶/底 Planar 面优先 `face_type:"Planar" + centroid_z + expectation.count`。
- `normal` 与 `area` 只作辅助，不作为唯一顶/底面的首要硬筛选条件。
- 连续多个圆角/倒角必须每次重新 `nx_list_edges`。
- 禁止只按 index 数字猜边/面。

## 7. 输出

- 用户可见回复全部使用自然中文。
- 阶段 C 状态必须与 Runner report 完全一致：只有 `report.status="success"` 才能写“成功”；若 `report.status="failed"` 或存在 `failed_step`，即使 PRT/STEP 已生成也必须写“失败”。
- 自动修复后成功必须披露首次失败步骤、原因和修复内容，不能伪装成一次通过。
- 总耗时必须是真实 wall clock，包含失败、诊断、修复、清理和第二次执行。
- 不输出长 plan、内部 JSON 状态或调试噪音。

## 8. 能力边界

只使用仓库当前 32 个 certified tools。禁止为了完成任务自行新增工具或修改 NX_MCP / Loader。

当前不建议或不支持：Sweep、Loft、真实螺纹、渐开线/斜齿轮、任意倾斜工作平面、复杂自由曲面。
