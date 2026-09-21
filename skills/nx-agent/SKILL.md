---
name: nx-agent
description: 作者：抖音 无趣。Siemens NX 自动建模统一入口。支持文字描述建模、工作区内已保存零件的安全修改，以及二维机械工程图 Evidence-first 读取→确定性求解→Gate A→建模规划→Plan Runner→PRT/STEP。
---

# NX Agent — Siemens NX 自动建模统一入口

本 Skill 是 NX_MCP-Enhanced 的唯一用户入口。对外只显示一个 Skill，对内按模块化规则执行。

## 1. 自动选择模式

### 模式 A：文字描述建模（Fast Path）

用户直接用文字描述零件、尺寸、孔位、圆角、倒角等要求时：

1. 正常路径只读取 references/text-modeling.md 与 references/certified-tool-contract.json；本 SKILL.md 已包含阶段 C、拓扑和输出硬规则。禁止为了确认规则重复读取其它 reference。
2. 不经过工程图读取模块；把明确文字尺寸直接整理为结构化建模意图。
3. 按 text-modeling.md 的固定 runtime-config 路径一次定位 Runner；禁止扫描 Skill 目录、仓库目录、安装脚本、Python 环境或聊天目录。
4. 正常新零件任务禁止主动读取 run_history.json、旧 frozen/executable plan、旧 report 或旧 PRT/STEP 内容。历史安全判断由 Runner preflight 自己完成。
5. 直接生成 frozen plan → build/check → Plan Runner。
6. 只有 build/check 明确报告 schema/contract incompatibility、attempt 1 失败且符合 Controlled Self-Healing、或用户明确要求解释底层 Planner 规则时，才读取对应详细 reference。

默认用于创建新零件。修改已有零件时，仅允许打开 NX_MCP_WORKSPACE 内、用户明确指定路径的已保存零件；不得自动接管无关或未保存的当前零件。

### 模式 B：二维机械工程图自动建模

用户上传二维机械工程图并要求开始建模、按图建模、用 NX 画出来等时：

1. 在开始 drawing interpretation 前，按“运行时与路径”的 Mode B 规则只定位并读取一次 runtime-config.json；本轮固定使用该 runtime，之后不得重新发现或切换 runtime。
2. 读取 references/drawing-reader.md + references/reader-capture-contract.md + references/nx-drawing-rules.md。
3. 当前上传工程图是本轮 interpretation 的唯一几何输入。Reader 在唯一一次写盘前，必须先在内存中使用生产 `ReaderCapture.model_validate(payload)` 完整校验；仅 JSON parse、键数量检查或自定义扫描不算通过。只有生产 schema 校验通过后，才允许一次写出 reader-capture.json；它是 immutable first-pass visual evidence artifact。校验失败则不写文件、不第二次看图修复，立即 BLOCKED / STOP。Reader 不得直接创建 drawing-evidence.json、semantic-draft.json 或 drawing.json。
4. capture 写出后，立即使用 runtime-config 指定 python_exe 执行：python -m nx_mcp.drawing_intelligence link-capture <reader-capture.json> <drawing-evidence.json>。该步骤只做 deterministic identity linking + Gate 0；禁止重新读取工程图。
5. 只有 link-capture 的 process exit code=0、written=true、schema_valid=true 才允许继续；否则 BLOCKED / STOP。link-capture 产生 blocking unresolved 可以保留在 drawing-evidence.json，是否闭合由下一步 resolve 判定。
6. 立即执行：python -m nx_mcp.drawing_intelligence resolve <drawing-evidence.json> <semantic-draft.json>。
7. 只有 resolve 的 process exit code=0、written=true、ok=true、blocking_unresolved=0、conflicts=0、dimension_closure=closed 全部成立，才允许继续。否则 BLOCKED / STOP；禁止第二次看图、Edit/Rewrite capture/evidence、生成第二版 capture/evidence、修改 draft 后重试、进入 canonicalizer 或 Planner。
8. Resolve PASS 后立即执行 runner.py canonicalize-drawing <semantic-draft.json> <drawing.json>。只有 process exit code=0、written=true、output_exists=true、gate_a.ok=true 才算 Gate A PASS。
9. Gate A 失败立即 BLOCKED / STOP。禁止修改 capture/evidence/draft、重新 interpretation、semantic token retry、手写 drawing.json、单独 validate-drawing 绕过 canonicalizer，或进入 Planner。
10. Gate A PASS 后根据本轮 canonical drawing.json 从零生成新的 frozen plan；即使工作区已有同名 plan 或相同零件，也不得跳过 Planner。
11. 固定执行 runner.py build <current-frozen> <current-executable> --drawing <current-drawing>，随后 check 当前 executable，再调用 Runner。
12. 本轮 interpretation 开始后，禁止主动读取或把工作区中的旧 reader-capture、drawing-evidence、semantic-draft、drawing、frozen/executable plan、旧 report、旧 run_history.json、旧 PRT/STEP 当作当前任务输入或规划参考。
13. 禁止扫描工作区寻找可复用历史 plan；文件名、零件类型或尺寸看起来相同也不构成复用依据。
14. 总控规则见 references/pipeline-contract.md；用户输出规范见 references/chinese-output.md。

两条链路：

~~~text
文字描述
→ 建模规划
→ Plan Runner
→ Siemens NX
→ PRT + STEP

二维工程图
→ reader-capture.json
→ deterministic identity link / Gate 0
→ drawing-evidence.json
→ deterministic compile / resolve
→ semantic-draft.json
→ canonicalize / Gate A
→ 建模规划
→ Plan Runner
→ Siemens NX
→ PRT + STEP
~~~

## 2. 运行时与路径

安装器会在 Plan Runner 目录生成 runtime-config.json。Mode B 必须使用以下确定性发现规则：

1. 要求环境变量 NX_MCP_WORKSPACE 非空，并且只能读取：<NX_MCP_WORKSPACE>\nx-mcp-plan-runner\runtime-config.json。
2. 禁止扫描用户目录、仓库目录、其它 NX_MCP_WORKSPACE*、历史 CLEAN workspace、聊天目录、安装目录列表或 Python 环境来寻找其它 runtime-config。
3. 环境变量缺失、该唯一文件不存在或必需字段缺失时，立即停止并报告 runtime configuration missing；禁止自动寻找其它 runtime-config。
4. 读取后原样使用 python_exe、workspace_root、nx_mcp_src。
5. python_exe 必须是 runtime-config 指定且实际存在的文件；禁止 fallback 到 python / python3 / py、系统 Python 或 PATH 中其它 Python。
6. workspace_root 与 NX_MCP_WORKSPACE 规范化后必须相同，否则 fail closed。
7. nx_mcp_src 只能取自当前 runtime-config，不得从历史仓库、备份仓库或其它 workspace 推断。
8. runtime 一旦解析，本轮不得重新发现或切换 runtime。

当前 reader-capture.json / drawing-evidence.json / semantic-draft.json / drawing.json / frozen plan / executable plan / report / PRT / STEP 都必须只落在该 workspace_root。其它目录中已有文件不能触发 workspace 切换。

## 3. 模式选择优先级

1. 有工程图且用户要求依据图纸建模 → 模式 B。
2. 没有工程图、用户直接给明确几何要求 → 模式 A。
3. 工程图 + 补充文字同时存在：工程图为几何主来源；补充文字仅作为明确附加约束。发生冲突必须停止并报告。
4. 禁止把工程图任务退化成看图后直接手工调用 NX_MCP。
5. 禁止让纯文字建模任务无意义地走工程图读取。

## 4. 工程图门禁

### Evidence Gate

- Reader 只允许在生产 `ReaderCapture` schema 校验通过后一次写出本轮 reader-capture.json；overall_dimensions 三轴必须为正数，禁止 null / 缺省 / 0。
- Reader 只记录 view-local entities、显式 association claims、physical endpoints、direct values 与 unresolved evidence；新 capture 的 required_targets 固定为 []，正式 required targets 由 linker 确定性派生；禁止创建最终 physical feature ID。
- 立即执行 link-capture，确定性生成 drawing-evidence.json。
- Reader 禁止做 centered global coordinate arithmetic、relation 语义猜测或 Gate A 判定。
- 再执行 deterministic resolve，生成 semantic-draft.json。
- resolve 非零、blocking_unresolved>0、conflicts>0 或 dimension_closure 非 closed → STOP。
- 任一前端门禁失败时禁止重新看图修答案、禁止第二版 reader-capture。

### Gate A

- 只在 Resolver PASS 后执行 runner.py canonicalize-drawing <semantic-draft.json> <drawing.json>。
- 只有 exit code=0、written=true、output_exists=true、gate_a.ok=true 才算 PASS。
- 此时 drawing.json 是本轮唯一正式 canonical artifact。
- 其它结果立即 BLOCKED / STOP。禁止 retry、第二版 draft、Edit/Rewrite evidence/draft、手写 drawing、单独 validate-drawing 或进入 Planner。
- Canonicalizer 不补 geometry、ownership、relation 或 unresolved。

### Gate B

- 当前 frozen plan 必须由本轮 Gate A PASS 的 drawing JSON 新生成。
- runner build 必须带 --drawing <current-drawing>，随后 build/check 通过。
- unresolved reference = 0。
- illegal tool_args = 0。
- natural language placeholder = 0。
- executable plan 存在且非空。

frozen plan 首次落盘前必须完成静态自检。B 阶段 build/check 失败直接结束，禁止现场补丁后继续。

## 5. 阶段 C 与受控自动修复

- 单次 Runner 尝试严格 fail-fast：任意 modeling step 失败，当前尝试立即停止。
- 每个任务最多允许 1 次 Controlled Self-Healing。
- 只允许修复根因明确、且不改变尺寸/位置/特征数量/几何语义的计划级问题。
- 典型允许：edge/face selection_criteria 过严、Loader 已冻结的类型语义差异。
- 禁止：重新看图、修改 reader-capture/drawing-evidence、猜尺寸、改图纸、改变主体结构、绕过能力边界、修改 Runner/NX_MCP/Loader。
- 禁止 geometry / numeric nudge。
- 修复后必须重新 build/check，并由 Runner 安全 preflight 丢弃本任务自己的失败零件，然后从第 1 步完整重跑。
- 禁止从失败步骤续跑。
- 第二次失败必须结束。

## 6. 拓扑与选择规则

- edge / face index 都是临时数据；任何拓扑变化后旧 index 立即失效。
- Linear 边 direction 只能是 X/Y/Z/OTHER。
- 四角竖边优先 corners_xy + bbox_z/midpoint_z。
- Circular / Elliptical / Conical 曲线边禁止 bbox 类条件。
- 完整圆边优先 curve_type:[Elliptical,Circular] + length + midpoint_z + expectation.count。
- 唯一顶/底 Planar 面优先 face_type:Planar + centroid_z + expectation.count。
- normal 与 area 只作辅助，不作为唯一顶/底面的首要硬筛选条件。
- 连续多个圆角/倒角必须每次重新 nx_list_edges。
- 禁止只按 index 数字猜边/面。

## 7. 输出

- 用户可见回复全部使用自然中文。
- 阶段 C 状态必须与 Runner report 完全一致：只有 report.status=success 才能写成功。
- 自动修复后成功必须披露首次失败步骤、原因和修复内容，不能伪装成一次通过。
- 总耗时必须是真实 wall clock，包含失败、诊断、修复、清理和第二次执行。
- 不输出长 plan、内部 JSON 状态或调试噪音。

## 8. 能力边界

只使用仓库当前 32 个 certified tools。禁止为了完成任务自行新增工具或修改 NX_MCP / Loader。

当前不建议或不支持：Sweep、Loft、真实螺纹、渐开线/斜齿轮、任意倾斜工作平面、复杂自由曲面。
