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
2. 正常 Mode B Reader 只读取 references/reader-runtime-contract.md + references/nx-drawing-rules.md。禁止为了“再确认规则”重复读取完整 drawing-reader.md / reader-capture-contract.md；两者仅供开发、审计或单独排障，不是正常运行时输入。
2a. 仅当用户明确要求 bounded semantic query / Region Query Reader 性能验收时，先立即记录本轮 smoke_start。新的性能验收默认只读 references/reader-candidate-addressed-contract.md，执行 Candidate-Addressed Semantic Reader v3：deterministic setup 先生成 reader-candidate-queries.json；Agent 每个 query 只能直接视觉读取 query.image_path 一次，只回答该 query 已列出的 dimension_targets，禁止扫描 region 额外盘点未寻址的实体、尺寸、孔、槽、datum、tolerance 或其它事实；每个 query 后立即写 reader-candidate-<query_id>.json，全部 query 完成后只允许调用 deterministic assemble-reader-candidate-regions 生成 reader-candidate-partial-observations.json。只有用户明确要求 Token Reader v2 时才读 references/reader-bounded-token-contract.md；只有用户明确要求 legacy strict smoke 时才读 references/reader-bounded-query-contract.md。所有 smoke 都必须在各自合同规定的 partial observations 产物后 STOP，不得继续 ReaderCapture / linker / Resolver / Gate A / Planner / Runner / NX；严禁 PIL/Pillow、OpenCV、System.Drawing、PowerShell/.NET 图像代码、GetPixel/LockBits、ASCII 图、OCR、像素坐标测量、边线检测或任何二次程序化图像分析；证据不足保持 uncertain/unresolved。该 smoke 未经验收前不得替代正常 Mode B 主线。
3. 当前上传工程图是本轮 interpretation 的唯一权威几何输入。若当前请求环境已明确提供本轮上传工程图的 runtime-local raster 路径，必须先按 pipeline-contract.md 的 A0.5 执行一次 `prepare-reader-input <current-raster-path> <workspace_root>`；失败立即 BLOCKED / STOP，禁止退回 Agent 自己写 PowerShell、PIL、.NET 或其它裁图/预处理脚本。成功后 Reader 默认只读取当前原图、当前 reader-input.json 与当前 reader-contact-sheet.png；禁止顺序打开全部单张 crop。只有 contact sheet 中某个已列出的具体区域无法辨认时，才允许打开 manifest 中对应的那一张现成 crop；不得直接读取 raw-evidence.json / reader-visual-aid.json，不得扫描 workspace / chats / 历史文件，不得创建额外 crop。若本轮没有明确 raster path，则不得扫描寻找替代文件，直接按原 Reader 路径继续。随后按 reader-runtime-contract.md 完成一次连续 first-pass，只写一次 immutable reader-observations.json。立即使用 runtime-config 指定 python_exe 执行 `python -m nx_mcp.drawing_intelligence assemble-reader-capture <reader-observations.json> <reader-capture.json>`。该程序只允许做确定性 ID/source/schema 组装，不得推断 feature identity、association、dimension endpoint ownership 或缺失工程语义；失败立即 BLOCKED / STOP，禁止第二次 interpretation、禁止第二版 observations。成功后得到唯一 reader-capture.json，再进入 check-capture。
4. capture 写出后，先使用 runtime-config 指定 python_exe 执行：python -m nx_mcp.drawing_intelligence check-capture <reader-capture.json>。只有 process exit code=0、schema_valid=true、contract_valid=true、errors=[] 才允许继续；否则 BLOCKED / STOP。禁止依据 check-capture 错误第二次看图或重写 capture。
5. check-capture PASS 后立即执行：python -m nx_mcp.drawing_intelligence link-capture <reader-capture.json> <drawing-evidence.json>。该步骤只做 deterministic identity linking + Gate 0；禁止重新读取工程图。
6. 只有 link-capture 的 process exit code=0、written=true、schema_valid=true、contract_valid=true 才允许继续；否则 BLOCKED / STOP。link-capture 产生 blocking unresolved 可以保留在 drawing-evidence.json，是否闭合由下一步 resolve 判定。
7. 立即执行：python -m nx_mcp.drawing_intelligence resolve <drawing-evidence.json> <semantic-draft.json>。
8. resolve 若 process exit code=0、written=true、ok=true、blocking_unresolved=0、conflicts=0、dimension_closure=closed，则直接继续 Gate A。若 resolve 失败且 conflicts>0，立即 BLOCKED / STOP。
9. resolve 仅因 blocking unresolved 失败时，允许且只允许执行一次：python -m nx_mcp.drawing_intelligence request-confirmations <drawing-evidence.json> <confirmation-request.json>。只有 eligible_for_user_confirmation=true、unconfirmable_blocking_ids=[]、question_count 在 1..3 内，才可向用户展示这些结构化尺寸端点问题；其它情况立即 BLOCKED / STOP。
10. 用户确认后，把选择写成 user-confirmations.json，并执行一次：python -m nx_mcp.drawing_intelligence apply-confirmations <drawing-evidence.json> <user-confirmations.json> <drawing-evidence-confirmed.json>。不得覆盖原始 drawing-evidence.json，不得修改尺寸数值，不得手写陌生 target。
11. 对 drawing-evidence-confirmed.json 只允许再执行一次 resolve，输出 semantic-draft-confirmed.json。只有第二次 resolve 完全 PASS 才允许继续；否则立即 BLOCKED / STOP。禁止第二轮用户确认、禁止重新看图、禁止重写 Reader Capture。
12. Resolve PASS 后立即执行 runner.py canonicalize-drawing <semantic-draft.json 或 semantic-draft-confirmed.json> <drawing.json>。只有 process exit code=0、written=true、output_exists=true、gate_a.ok=true 才算 Gate A PASS。
13. Gate A 失败立即 BLOCKED / STOP。禁止修改 capture/evidence/draft、重新 interpretation、semantic token retry、手写 drawing.json、单独 validate-drawing 绕过 canonicalizer，或进入 Planner。
14. Gate A PASS 后根据本轮 canonical drawing.json 从零生成新的 frozen plan；即使工作区已有同名 plan 或相同零件，也不得跳过 Planner。
15. 固定执行 runner.py build <current-frozen> <current-executable> --drawing <current-drawing>，随后 check 当前 executable，再调用 Runner。
16. 本轮 interpretation 开始后，禁止主动读取或把工作区中的旧 raw-evidence、reader-visual-aid、reader-input、reader-contact-sheet、reader-crops、reader-observations、reader-capture、drawing-evidence、semantic-draft、drawing、frozen/executable plan、旧 report、旧 run_history.json、旧 PRT/STEP 当作当前任务输入或规划参考。
17. 禁止扫描工作区寻找可复用历史 plan；文件名、零件类型或尺寸看起来相同也不构成复用依据。
18. 总控规则见 references/pipeline-contract.md；用户输出规范见 references/chinese-output.md。

两条链路：

~~~text
文字描述
→ 建模规划
→ Plan Runner
→ Siemens NX
→ PRT + STEP

二维工程图
→ [若有明确 raster path：prepare-reader-input → reader-input.json + reader-contact-sheet.png]
→ reader-observations.json
→ deterministic assemble-reader-capture → reader-capture.json
→ check-capture
→ deterministic identity link / Gate 0
→ drawing-evidence.json
→ deterministic compile / resolve
→ [仅当可确认尺寸阻塞] Human Confirmation Gate
→ semantic-draft.json / semantic-draft-confirmed.json
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

当前 raw-evidence.json / reader-visual-aid.json / reader-input.json / reader-contact-sheet.png / reader-crops / reader-observations.json / reader-capture.json / drawing-evidence.json / semantic-draft.json / drawing.json / frozen plan / executable plan / report / PRT / STEP 都必须只落在该 workspace_root。其它目录中已有文件不能触发 workspace 切换。

## 3. 模式选择优先级

1. 有工程图且用户要求依据图纸建模 → 模式 B。
2. 没有工程图、用户直接给明确几何要求 → 模式 A。
3. 工程图 + 补充文字同时存在：工程图为几何主来源；补充文字仅作为明确附加约束。发生冲突必须停止并报告。
4. 禁止把工程图任务退化成看图后直接手工调用 NX_MCP。
5. 禁止让纯文字建模任务无意义地走工程图读取。

## 4. 工程图门禁

### Evidence Gate

- Reader 只允许一次写出本轮 reader-observations.json；随后由 deterministic assemble-reader-capture 生成唯一 reader-capture.json。Assembler 不得补语义；overall_dimensions 三轴必须为正数，禁止 null / 缺省 / 0。
- Reader 只记录 view-local entities、结构化 association visual basis、带 visual basis 的 physical endpoints、direct values 与 structured unresolved evidence；新 capture 的 required_targets 固定为 []，正式 required targets 由 linker 确定性派生；禁止创建最终 physical feature ID。
- capture 写出后先执行 check-capture；只有 schema_valid=true 且 contract_valid=true 才允许进入 linker。
- check-capture PASS 后立即执行 link-capture，确定性生成 drawing-evidence.json。
- Reader 禁止做 centered global coordinate arithmetic、relation 语义猜测或 Gate A 判定。
- 再执行 deterministic resolve，生成 semantic-draft.json。
- resolve PASS 直接进入 Gate A；仅当 conflicts=0 且全部 blocking unresolved 都是最多 3 个可确认的 dimension endpoint 时，允许一次 Human Confirmation Gate；其它失败 → STOP。
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
