# NX Agent 工程图/文字建模执行规范

## 1. 总控职责
本规范负责统一编排文字建模与工程图建模的计划执行层，不直接手工补建几何。

核心策略：**Fail-fast + Controlled Self-Healing（受控自动修复）**。

含义：
- 每一次 Runner 尝试内部仍然严格 fail-fast；
- 失败后当前尝试立即停止；
- 只有满足安全门禁时，才允许最多 1 次受控自动修复；
- 自动修复必须从干净状态完整重跑，禁止从失败步骤续跑。

## 2. Runtime Config（强制）

安装器会在 Runner 目录生成 `runtime-config.json`，至少包含：

- `python_exe`
- `workspace_root`
- `nx_mcp_src`
- `repo_root`

Mode B 在开始 drawing interpretation 前执行一次且仅一次 runtime discovery：

1. `NX_MCP_WORKSPACE` 必须存在；唯一合法配置路径是 `<NX_MCP_WORKSPACE>\nx-mcp-plan-runner\runtime-config.json`，只能读取这一份。
2. 环境变量缺失、配置文件不存在或 `python_exe / workspace_root / nx_mcp_src` 缺失时，立即停止并报告 `runtime configuration missing`。
3. 禁止扫描用户目录、仓库目录、其它 workspace、CLEAN workspace、历史聊天目录、安装目录列表、Python 环境或 PATH 寻找替代 runtime-config、Runner 或 Python。
4. `runtime-config.workspace_root` 与 `NX_MCP_WORKSPACE` 规范化后必须相同；不一致时 fail closed。
5. `python_exe` 必须原样取自 runtime-config 且文件存在；禁止 fallback 到 `python`、`python3`、`py`、系统 Python或 PATH 中其它 Python。
6. `nx_mcp_src` 必须原样取自当前 runtime-config，不得由历史 repo、backup repo 或其它 workspace 推断。
7. runtime 一旦解析，本轮 drawing、Gate A、Planner、build/check、Runner 和导出阶段固定使用该 runtime，本轮不得重新发现或切换 runtime。

当前 Mode B 的 semantic-draft.json、drawing.json、frozen plan、executable plan、report、PRT 和 STEP 必须全部位于 `runtime-config.workspace_root`；其它目录中已有 artifact 不能成为切换 workspace 的理由。

## 3. 阶段 A：工程图读取
读取 `drawing-reader.md` 与 `nx-drawing-rules.md`。

A1. Reader只从当前上传工程图生成一次`semantic-draft.json`。它是immutable first-pass semantic artifact；Reader不得直接写`drawing.json`。
A2. 立即执行`runner.py canonicalize-drawing <semantic-draft.json> <drawing.json>`；canonicalizer只做白名单representation normalization与preservation guards。
A3. Gate A包含在该命令内。只有process exit code = 0、`written=true`、`output_exists=true`同时成立才PASS。
A4. PASS时`drawing.json`由canonicalizer原子生成，随后才能进入Planner；其它结果`BLOCKED / STOP`，且`drawing.json`不存在。
A5. 禁止第二版或Edit/Rewrite semantic draft、重新看图、semantic token/schema retry、手写drawing、单独`validate-drawing`绕过canonicalizer，或在失败后进入Planner。

三种结果：
- Reader存在blocking unresolved：draft保留，canonicalizer/Gate A FAIL，drawing不存在，STOP。
- draft只有白名单内安全schema/path差异：无损normalization后Gate A PASS，drawing生成，进入Planner。
- draft存在真实semantic/ownership错误：canonicalizer不得修，Gate A FAIL，drawing不存在，STOP。

## 4. 阶段 B：建模规划
输入可以是工程图模式 A 阶段成功生成的canonical `drawing.json`，或文字模式中已经确认完整的结构化建模意图。
读取：
- `modeling-planner.md`
- `runner-contract.md`
- `certified-tool-contract.json`
- `nx-mcp-rules.md`
- `topology-safety.md`

正常路径：
```text
当前上传工程图 → 当前 semantic-draft.json → canonicalize-drawing → 当前 drawing.json → 根据当前 drawing.json 新生成 frozen plan → runner build --drawing <current-drawing> → runner check → 当前 executable plan
```

### 4.1 Mode B 当前请求 artifact isolation

- 新请求开始 interpretation 前，现有 `semantic-draft.json`、`drawing.json` 与 frozen/executable/report/PRT/STEP 一样都是 stale output，不是输入；唯一几何输入是当前上传工程图。
- canonicalize-drawing成功后必须重新运行Planner，只从本轮canonical `drawing.json`生成新的frozen plan；已有`frozen-plan.json`或executable不得作为输入，也不得作为“已规划完成”的依据。
- 当前 drawing interpretation 开始后，禁止主动读取旧 frozen/executable plan、旧 Runner report、旧 `run_history.json`、旧 PRT/STEP，以及其它历史零件的 drawing/frozen/executable。
- 工作区即使同时存在新 `drawing.json` 与旧 frozen/executable/report/PRT/STEP，也必须忽略旧 artifact，不能直接 build/run 或进入 Runner。
- Planner不得读取semantic draft、previous/latest/first-matching drawing、Agent手写drawing或仅由独立validate-drawing通过的drawing；不得扫描工作区判断是否存在“可用计划”。
- Mode B build 固定绑定本轮 drawing：`runner.py build <current-frozen> <current-executable> --drawing <current-drawing>`。
- 只有当前canonicalizer成功生成的drawing及其后新生成的frozen、executable才能沿本轮流程向后传递；不引入跨任务身份或registry。

runner build/check 任一失败即 B 失败。B 阶段失败**不进入自修复**，禁止修改 frozen plan 后自动重跑。

## 5. 阶段 C：Plan Runner
Runner 路径：
`<runtime-config.workspace_root>\nx-mcp-plan-runner\runner.py`

### 5.1 Preflight
只允许：
- 检查/启动 NX
- 探测 named pipe `nx_mcp_loader`
- 检查 Python/Runner/plan/workspace

Loader ready：
优先使用仓库 `loader/nx_client.ps1 -Cmd nx_status`；
CONNECTED + ok=true + ready=true 即 ready。

禁止用 `%LOCALAPPDATA%\nx-mcp\bridge.json` 判断 resident Loader。

### 5.2 单次尝试的 fail-fast
Runner 正式开始建模后，任一 operation 失败：
- 当前 Runner 尝试立即停止；
- 禁止在当前 dirty model 上继续执行后续步骤；
- 禁止从失败步骤续跑；
- 禁止手动 bridge 补建；
- 禁止手动 save / STEP 导出；
- 记录 failed_step / reason / attempt_elapsed_seconds。

这一步只结束“当前尝试”，是否进入一次受控自动修复由 §5 决定。

## 6. Controlled Self-Healing（受控自动修复）

### 6.1 次数
每次 Pipeline **最多 1 次**自动修复：
- attempt 1 失败 → 可评估 repair；
- repair 后 attempt 2 成功 → 最终“成功（自动修复后）”；
- attempt 2 再失败 → 最终失败，禁止第三次尝试。

### 6.2 允许修复的范围
只有根因明确、可确定、不会改变设计语义时才允许：
1. edge / face `selection_criteria` 匹配 0 条或数量不符；
2. Loader 已冻结的返回语义差异，例如：
   - 完整圆边 `Elliptical` / `Circular`；
   - 孔侧面 `Swept` / `Cylindrical`；
3. 筛选条件过严，可替换为冻结契约中已验证的稳定组合；
4. frozen/executable 边界污染等**纯计划表达错误**（例如 Planner 误写
   `result_bindings` / `selection_binding` / `retry` / `$reference`），
   且修复仅删除/改写绑定表达，不改变任何尺寸、特征、选择几何或建模顺序；
5. 上一次失败由**当前 Pipeline 自己创建**的计划输出零件处于 dirty 状态，需要无保存清理后完整重跑。

### 6.3 禁止自动修复
以下任一情况必须最终失败：
- A 阶段 unresolved > 0 / dimension conflict / 尺寸缺失；
- 需要猜尺寸、改尺寸、改孔位、改特征数量；
- **禁止数值 nudge / epsilon 修复**：任何来自 drawing、derived、frozen plan 的设计几何数值，包括 coordinate、start/end、slot bottom、hole center、diameter、depth、thickness、radius、chamfer、fillet，都不得为了让 NX Boolean 成功而改成邻近值，例如 `Z=50 → Z=49`。
- Controlled Self-Healing 只允许 selection criteria 修复，以及不改变已冻结设计几何语义的确定性 plan-level / selection-level 技术修复。
- 若精确相切/共面导致 NX kernel Boolean 失败，而没有 geometry-preserving 修复路径，必须失败；不得扩大、缩短、偏移或以其它方式 nudge 工具体。
- Boolean 不相交且根因属于几何设计/规划错误；
- 超出 certified tools 能力边界；
- 需要新增或修改 NX_MCP / Runner / Loader；
- 当前 dirty part 不是本 Pipeline 本次任务自己创建的目标零件；
- 无法确定修复是否改变最终几何；
- 第一次修复后的 attempt 2 再次失败。

### 6.4 修复过程（强制）
允许修复时必须按以下顺序：
1. 保留 attempt 1 失败报告；
2. 只读诊断失败原因；
3. 生成 **repair plan v1**，只修改已确认的计划级问题；
4. 重新执行 runner build + check；失败则最终失败；
5. 禁止 Agent 手动关闭 dirty part；
6. 第二次执行必须交给 Runner preflight 安全处理本任务自己的 planned dirty part；
7. 从 C 的第 1 步完整重跑 executable plan；
8. 禁止从 failed_step 接着执行；
9. 最终报告必须披露自动修复次数、首次失败步骤和首次失败原因。

第二次执行必须使用：
```text
python_exe runner.py run <repair-executable.json>
  --workspace <workspace_root>
  --report <attempt2-report.json>
  --mode benchmark
  --allow-overwrite
  --repair-attempt 1
  --repair-report <attempt1-report.json>
```

Runner 会机器校验 previous report、planned part 和 repair 次数，防止第三次 repair。

### 6.5 允许的 selection 修复示例
- 唯一顶面：
  `Planar + centroid_z + count=1`
  优先于 `Planar + normal + ...`。
- 完整圆顶边：
  `["Elliptical","Circular"] + length + midpoint_z + count`
  禁止曲线 bbox。
- 四角竖边：
  `Linear + direction="Z" + corners_xy + bbox_z + count`。

## 7. 面选择稳定规则
当目标是唯一顶/底 Planar 面时：
- 首选 `face_type:"Planar" + centroid_z + expectation.count`；
- `normal` 只作为辅助信息，不作为首要硬筛选；
- `area` 只辅助，不作单点失败条件；
- 同一 Z 高度存在多个 Planar 面时，再增加完整 `centroid` 或 `area` 区分。

Shell remove face 若最高 Z 只有一个 Planar 面，固定按：
```json
{
  "selection_criteria": {
    "face_type": "Planar",
    "centroid_z": {"value": 40.0, "tol": 0.5}
  },
  "expectation": {"count": 1}
}
```

## 8. 总耗时
`total_elapsed_seconds` 必须是**真实墙钟时间**：
从收到“开始建模”并正式执行，到最终成功/失败报告返回。

如果发生自动修复，总耗时必须包含：
- attempt 1；
- 失败诊断；
- repair plan；
- build/check；
- dirty part 清理；
- attempt 2；
- 最终验证与汇报。

禁止用“成功那一轮”的 A+B+C 或 Runner 时间冒充总耗时。

`C_RUNNER_SECONDS` = 所有 Runner 尝试的 elapsed_seconds 之和。

## 9. 用户输出
最终用户可见格式以 `chinese-output.md` 为准。
