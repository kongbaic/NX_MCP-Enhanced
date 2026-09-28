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
2a. 仅当用户明确要求 bounded semantic query / Region Query Reader 性能验收时，先立即记录本轮 smoke_start。新的性能验收默认只读 references/reader-candidate-value-contract.md，执行 Candidate Value-Only Reader v3.2：deterministic setup 先生成 candidate overlay 与 reader-candidate-queries.json；Agent 每个 query 只能直接视觉读取 query.image_path 一次，只为每个已列出的 target 返回可见正数值或 null，禁止输出 dimension/not_dimension/uncertain 分类，禁止判断 endpoint ownership、feature ownership、cross-view identity、datum 或其它工程语义；每个 query 后立即写 reader-candidate-value-<query_id>.json，全部 query 完成后只允许调用 deterministic assemble-reader-candidate-values 生成 reader-candidate-value-partial-observations.json。只有用户明确要求 Candidate-Addressed v3/v3.1 时才读 references/reader-candidate-addressed-contract.md；只有用户明确要求 Token Reader v2 时才读 references/reader-bounded-token-contract.md；只有用户明确要求 legacy strict smoke 时才读 references/reader-bounded-query-contract.md。所有 smoke 都必须在各自合同规定的 partial observations 产物后 STOP，不得继续 ReaderCapture / linker / Resolver / Gate A / Planner / Runner / NX；严禁 PIL/Pillow、OpenCV、System.Drawing、PowerShell/.NET 图像代码、GetPixel/LockBits、ASCII 图、OCR、像素坐标测量、边线检测或任何二次程序化图像分析；证据不足保持 null/unresolved。该 smoke 未经验收前不得替代正常 Mode B 主线。
3. 当前上传工程图是本轮 interpretation 的唯一权威几何输入。若当前请求环境明确提供本轮上传工程图的 runtime-local raster 路径，正常 Mode B 的唯一前端入口是 runtime-config 指定的：`python_exe -m nx_mcp.drawing_intelligence run-hybrid-frontend <current-raster-path> <fresh-hybrid-run-directory>`。**一旦 raster 路径已明确，在执行该命令前禁止打开、查看或视觉解读整张工程图，禁止提前判断零件类型、孔/槽/螺纹/沉孔等 feature inventory 或读取尺寸；这里只允许确认该候选 raster 路径存在。** fresh-hybrid-run-directory 必须是尚不存在的候选路径；只允许对该候选路径做存在性检查，禁止先创建目录、再删除目录或因目录已存在执行第二次 frontend。该命令只允许执行一次；它内部独占执行 deterministic Reader prep（含 prepare-reader-input）→ production Whole + Wide-Local Hybrid OCR → structural-context query plan。Agent 在该 raster 路径下禁止自行调用 `prepare-reader-input`、`run-hybrid-ocr`，也禁止跳过 Hybrid OCR 改走完整自由视觉 first-pass。
4. `run-hybrid-frontend` 正常返回 exit code=4、phase=awaiting_structural_context。此时 Agent 只允许读取本轮 `structural-context-queries.json`，逐个直接查看 query.image_path 一次。**生产 prep 的 query.image_path 优先指向“完整工程图 + 当前 target region 矩形框选”的 deterministic structural context image；Agent 必须判断框选 region 属于哪个正投影视图，而不是把每个 deterministic region 假设成独立 view。矩形框只用于 region→view 归属，不是尺寸标注读取边界：只要某个明确 overall 尺寸位于同一 query image 中、能唯一归属于该框选 region 所属的同一个正投影视图，并且尺寸线确实跨越该视图完整外包轮廓，就允许写入 overall_dimension_facts，即使尺寸文字或尺寸线画在红框外。禁止读取属于其它视图的 overall；归属不唯一则 unresolved。旧 reader-input 没有 structural_context_path 时才兼容使用 region crop。**该 JSON 自带 `answer_template`；Agent 必须**原样复制 answer_template，并且只允许写入当前 fresh-hybrid-run-directory 内固定路径 `structural-context-answers.json`**，禁止把其它目录/上一轮 answers 传给 resume，禁止自行设计 schema 或字段，且顶层 `schema` 必须保持 `structural-context-answers-v1`。每个 answer 的 `query_id` 与顶层 `evidence` 必须保持模板原值；只允许填写 `view_kind`（仅 `front` / `side` / `top`，无法唯一判断则保持 null）、当前 query 视图直接标出的 `overall_dimension_facts`（每项固定为 `axis` + 正数 `value` + `evidence:[原样 evidence_label]`）、必填的 `rotational_symmetry` 显式判定以及 `unresolved`。对已解析且准备继续的 answer，`rotational_symmetry` 只能是 `{"status":"established","basis":"centerline","centerline_direction":"horizontal|vertical","evidence":[原样 evidence_label]}`、`{"status":"established","basis":"axial_section_symmetry","evidence":[原样 evidence_label]}` 或 `{"status":"not_established","evidence":[原样 evidence_label]}`；字段省略不是 not_established，schema 必须拒绝。模板中的 null 只用于 pending/unresolved：若视觉上无法完成该判定，保持 null 并写入 unresolved，本轮 fail-closed，禁止增加 unknown/uncertain 状态继续执行。只有当完整工程图明确且唯一表达整件绕某一可见工程轴回转时才允许 established。**不要求图纸额外打印 X/Y/Z 轴名**。允许两类 established 视觉依据：①**中心线依据**：纵向正投影或 axial/longitudinal section 中存在贯穿主要主体的明确整件中心线，且主要阶梯/圆柱主体段由围绕该中心线成对出现的相对同轴轮廓边/肩部表达回转体；②**无中心线轴向剖视依据**：query 通过剖面线/剖切语义明确属于 axial/diametral section，主要材料轮廓与各阶梯/圆柱主体段围绕一条唯一的剖面对称轴成对出现，可唯一确定回转轴方向，即使图中没有画出中心线也允许 established。第二类只适用于明确剖视，不适用于普通非剖视镜像轮廓。**连续实线的物体轮廓/边界绝不能冒充中心线。**Agent **禁止填写 X/Y/Z 回转轴，也禁止填写无中心线轴向剖视的 horizontal/vertical 或 left_right/top_bottom 方向**。centerline basis 仅可报告明确绘制中心线的 `centerline_direction=horizontal|vertical`；axial_section_symmetry 只报告剖视回转语义本身。该分支的轴方向必须来自 query 自带的 deterministic_profile_symmetry_axis，它由 Reader prep 对当前 region raster 做多阈值双边拓扑一致性判定，只分类 horizontal/vertical，不产生任何工程尺寸或坐标；hint 缺失时必须 unresolved。assembler 再按 `view_axis_map` 得到工程轴：front horizontal→X / vertical→Z，side horizontal→Y / vertical→Z，top horizontal→X / vertical→Y。该判断属于工程制图拓扑语义，禁止测像素距离、禁止把视觉“等距”换算成工程值。普通镜像对称、只有中心线但无成对同轴回转轮廓、外观“像回转件”、连续实线冒充中心线或参数名猜测都不足以 established。**not_established 不是“没看出来”的兜底值**：只有 query 明确显示整件不具备回转对称时才允许使用；若既没有足够 established 证据，也没有明确反证，必须保持 rotational_symmetry=null、写 unresolved 并 fail-closed。**Agent 禁止据此手工补第三轴 overall；确定性闭合固定为：rotation X ⇒ Y=Z，rotation Y ⇒ X=Z，rotation Z ⇒ X=Y。缺失第三轴只允许由后续 deterministic finalizer 从一个直接 transverse overall + rotational_symmetry_axis 推导，并保留 derivation provenance。****局部尺寸不得冒充 `overall_dimension_facts`：只有明确跨越当前视图完整零件外包边界/整体轮廓两端的直接 overall 标注才可写入；局部链尺寸、孔/圆中心距、中心到边、半径/直径、角度以及仅覆盖局部轮廓的线性尺寸，即使数值较大或恰好为 70/50，也禁止提升为 overall。若图中没有明确 overall 标注，对应 axis 不写 fact，保持 unresolved；不得为了让 Hybrid Adapter 继续而补值、算术推导或用像素估计。****overall fact 的 axis 禁止由 Agent 自行推断，必须严格使用 queries JSON 的 `view_axis_map`：front horizontal=X / vertical=Z；side horizontal=Y / vertical=Z；top horizontal=X / vertical=Y。**view_kind 已确定时清空模板中的 `pending_structural_visual_read`；view_kind 无法确定时保留/改写 unresolved 且不得写 overall_dimension_facts。禁止增加其它字段。禁止在 Structural Reader 阶段判断 feature inventory、cross-view identity、feature/local value、dimension endpoint ownership、start side、termination 或 pixel→mm；无法唯一判断就写 unresolved，不得猜。
5. structural answers 写出后只允许执行一次：`python_exe -m nx_mcp.drawing_intelligence resume-hybrid-frontend <hybrid-frontend-manifest.json> <structural-context-answers.json> <fresh-mode-b-prefix>`。**在调用前必须先确定 `<fresh-mode-b-prefix>` 是 `workspace_root` 的 fresh 直接子级 prefix：例如 `<workspace_root>\\drawing-02-radial-angular-20260928-mode-b`；禁止放入 `<workspace_root>\\mode-b-runs\\...`、Hybrid run directory 或任何其它二级子目录。Hybrid run directory 可以位于 workspace 内子目录，但 Mode B artifact prefix 不可以。该 prefix 路径门禁必须在唯一一次 resume 调用前满足；若 resume 因 prefix/路径错误返回失败，本轮必须 STOP，禁止“修正路径后重试”或换 prefix 再调用。** resume 内部独占执行 structural context assembly → Hybrid Adapter → Reader Observation Finalizer → deterministic Mode B coordinator；Agent 不得手工拼接 partial-reader-observations.json / reader-observations.json，也不得绕过 Hybrid Adapter。
6. Hybrid Frontend resume 返回 exit code=0、phase=mode_b_gate_a_pass 时，唯一允许向后传递的是其 `mode_b` 子报告/state 指向的本轮 canonical drawing artifact。若 exit code=4、phase=mode_b_awaiting_confirmation，只允许读取其 `mode_b` 子报告指向的 confirmation-request 并向用户展示现有 1..3 个 option；用户选择后只允许执行一次 `python_exe -m nx_mcp.drawing_intelligence.mode_b_coordinator resume <mode-b-state.json> <user-confirmations.json>`。其它 exit code / phase 一律 BLOCKED / STOP；禁止第二轮确认。
7. 若当前请求没有明确 runtime-local raster 路径或输入不是 raster，才允许使用 reader-runtime-contract.md 的 fallback semantic Reader：当前图纸一次连续 first-pass → immutable reader-observations.json → `python_exe -m nx_mcp.drawing_intelligence.mode_b_coordinator <reader-observations.json> <fresh-artifact-prefix>`。该 fallback 不得扫描寻找 raster，也不得调用 Hybrid Frontend 猜路径。
8. Hybrid Frontend 或 Mode B coordinator 接管后，正常运行禁止为了处理错误读取实现源码、schema、tool signatures，禁止重写 observations/partial observations，禁止换 fresh prefix 重试，禁止绕过 state machine 手工串联 `assemble-reader-capture` / `link-capture` / `resolve` / Gate A。**terminal 后禁止二次诊断：任何 Hybrid Frontend 失败报告只要出现 `terminal=true` 或 `must_stop=true`，尤其同时给出 `may_retry=false` / `may_edit_structural_answers=false`，这些机器字段优先于 Agent 的自我修复判断；首次 terminal/blocked 结果出现后，只允许向用户报告该首次失败的 phase/reason/errors 并 STOP；不得再读取 OCR report、reader-input、structural queries/answers、manifest 或其它中间 artifact 来寻找“缺什么”，不得重新解释图纸，也不得提供“重开 fresh / fallback / 修正后重试”选项。terminal 回复在失败报告后必须立即结束：禁止附加任何“建议”“下一步”“继续方式”“替代输入”“模式 A”“重新开始”“发起新任务”等恢复性或操作性内容。新的独立任务只能由用户在后续消息中主动发起，Agent 不得在 terminal 回复里建议或诱导用户发起。若本轮一开始存在明确 raster path，fallback semantic Reader 永远不能作为失败恢复路径。只有用户之后明确发起新的独立任务，才允许开启新的 fresh production run。**前端失败不属于 Controlled Self-Healing。只有用户明确要求开发排障时才允许源码审计。
9. Gate A PASS 后进入建模规划时，必须读取 `references/modeling-planner.md`、`references/runner-contract.md`、`references/certified-tool-contract.json`、`references/nx-mcp-rules.md`、`references/topology-safety.md`；Planner 只读取 state 指向的本轮 canonical drawing.json，不得读取中间 reader-capture、drawing-evidence 或 semantic-draft。写 frozen plan **之前**必须先调用已安装 Runner：`runner.py plan-contracts <current-drawing.json>`。只有 exit code=0、`ok=true`、`errors=[]` 才允许继续；任何 capability / adapter / materialization 缺口立即 BLOCKED / STOP。
10. Planner 必须直接消费 `plan-contracts` 返回的 selected implementation、geometries、`operation_contracts` 与 `planner_contract`，并把返回的顶层 `drawing` **原样复制到 frozen plan 顶层 `source_drawing`**。Mode B 的 build/check 会把 `source_drawing` 与命令行 `--drawing` 做 canonical absolute-path 精确绑定；缺失或不一致立即 B 阶段失败。每个 contract operation 必须按三层规则机械展开：① `tool` 原样使用；② `fixed_args` 按完整 key set + 完整 value 原样复制进对应 `tool_args`，显式 `false`、`0`、空对象/空集合不得省略；③ 若存在 `operation_fields`，其每个 key/value 必须原样复制到 **frozen operation 顶层**，例如 `operation_fields.thread_surrogate_use` → operation 顶层 `thread_surrogate_use`，**禁止放进 tool_args，也禁止省略**。Planner 只允许再补 `requires` 指定的 symbol wiring、合法步骤顺序与非工程真值执行编排；禁止重算、改写、反推或补默认值；完成机械映射后必须**从零写本轮新的 frozen plan**，不得补丁或复用已有 frozen。
11. Mode B 固定执行：`runner.py build <current-frozen> <current-executable> --drawing <current-drawing>`，随后 `runner.py check <current-executable> --drawing <current-drawing>`；两者 PASS 后，Stage C 也必须使用 `runner.py run <current-executable> --drawing <current-drawing> ...`，Runner 在连接 Loader 前再次校验 executable 顶层 `source_drawing` 与当前 drawing 路径一致。plan-contracts / build / check 任一首次失败立即 B 阶段失败 / STOP；**看到任何 B 阶段 error 后，本轮唯一允许动作是向用户报告失败并结束：不得写/改任何 frozen/executable 文件，不得执行第二次 build/check，不得读取 runner.py / plan_schema / NX_MCP 源码，不得自行“修正后重试”。B 阶段不属于 Controlled Self-Healing；Controlled Self-Healing 只可能在 Stage C Runner attempt 1 已实际执行并失败后发生。** 两者 PASS 后才允许调用 Runner 执行当前 executable。
12. 本轮 interpretation 开始后，禁止主动读取或把工作区中的旧 raw-evidence、reader-visual-aid、reader-input、reader-contact-sheet、reader-crops、reader-observations、mode-b-state、reader-capture、drawing-evidence、semantic-draft、drawing、frozen/executable plan、旧 report、旧 run_history.json、旧 PRT/STEP 当作当前任务输入或规划参考。禁止扫描工作区寻找可复用历史 plan；文件名、零件类型或尺寸看起来相同也不构成复用依据。
13. 总控规则见 references/pipeline-contract.md；用户输出规范见 references/chinese-output.md。

两条链路：

~~~text
文字描述
→ 建模规划
→ Plan Runner
→ Siemens NX
→ PRT + STEP

二维工程图
→ [有明确 raster path：run-hybrid-frontend
   → Hybrid OCR
   → awaiting_structural_context
   → bounded Structural Reader answers
   → resume-hybrid-frontend
   → Hybrid Adapter / Reader finalizer
   → deterministic Mode B coordinator]
→ [无 raster path：fallback semantic Reader → reader-observations.json → deterministic Mode B coordinator]
→ Gate A canonical drawing.json
→ plan-contracts（Capability Resolver + deterministic Adapter operation_contracts）
→ Planner（只补 requires wiring + step 顺序）
→ frozen plan
→ build --drawing
→ check --drawing
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

- B 阶段 build/check 全部 PASS 后，正常 attempt 1 必须直接执行本轮 current executable：
  `python_exe runner.py run <current-executable.json> --workspace <workspace_root> --report <attempt1-report.json> --mode normal --repair-attempt 0`
- 正常 attempt 1 禁止 `--allow-overwrite` 和 `--repair-report`；不得改用 benchmark 模式。Runner report 是阶段 C 成败的唯一执行结果。
- **新建零件任务（本轮 part-entry tool 为 `nx_create_part`）允许 NX 中已有其它零件保持打开，**包括 Runner history 中上一轮创建的旧零件**；Runner preflight 必须保留该零件、不得调用 `nx_close_part`；正常 attempt 1 的 `nx_create_part` 若 planned PRT 已存在于磁盘，Runner 必须以 `planned_part_exists` fail-closed，Loader 自身也严禁删除/覆盖已有 PRT。只有已通过 `repair_attempt=1 + benchmark + --allow-overwrite + previous failed report 同一 planned_part` 门禁的 Controlled Self-Healing，Runner 才可在关闭本任务失败目标后删除该精确 planned path。Loader 的 `nx_create_part` 必须使用 `FileNew` + `DisplayPartOption.AllowAdditional` 创建新零件，禁止再使用会替换现有 display 的 `NewDisplay`；创建后 `nx_status` 必须同时证明真实 Work Part 已切换到 planned part 且原 displayed part 仍存在于 `displayed_parts`，任一验证失败则 attempt 1 fail-fast。对于 `nx_open_part` / 修改已有零件等非新建任务，若 Runner preflight 返回 `precheck_blocked` 且 reason=`unrelated_part_open`，本轮必须立即 STOP 并要求用户手动处理；Agent 严禁创建、生成或执行任何关闭用户零件的计划，严禁读取或修改 close-part frozen/executable，严禁手工补 result_bindings / selection_binding，严禁自动重跑当前 Runner；该环境 blocker 不属于 Controlled Self-Healing。**
- 单次 Runner 尝试严格 fail-fast：任意 modeling step 失败，当前尝试立即停止。
- **Controlled Self-Healing 仅适用于 Stage C Runner attempt 1 已实际执行后的失败；Stage B 的 plan-contracts / build / check 失败永远不允许自修复。** 每个任务最多允许 1 次 Stage C Controlled Self-Healing。
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
- 连续切除若仅点/线精确相切（典型：圆孔 + 通顶槽/keyhole），禁止拆成两次独立 subtract；必须由工程尺寸解析求连接点，合并成单一闭合 cut profile 一次减料。禁止 epsilon/numeric nudge，禁止像素换算连接点。
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
