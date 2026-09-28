# NX Agent 工程图/文字建模执行规范

## 1. 总控职责
本规范负责统一编排文字建模与工程图建模的计划执行层，不直接手工补建几何。

核心策略：Fail-fast + Controlled Self-Healing（受控自动修复）。

含义：
- 每一次 Runner 尝试内部仍然严格 fail-fast；
- 失败后当前尝试立即停止；
- 只有满足安全门禁时，才允许最多 1 次受控自动修复；
- 自动修复必须从干净状态完整重跑，禁止从失败步骤续跑。

工程图模式额外遵守 Evidence-first 原则：
- Agent 的视觉职责在一次性 `reader-observations.json` 写出时结束；
- 正常生产运行从 observations 到 Gate A 必须由 deterministic Mode B coordinator 独占编排；
- coordinator 内部完成 ReaderCapture assembly/contract、identity linker + Gate 0、compiler / resolver、最多一次 bounded Human Confirmation resume、semantic draft 与 canonicalizer / Gate A；
- Agent 不得在正常 Mode B 中手动串联这些内部阶段，也不得因内部失败读取实现源码后修 JSON 重试；
- Backend v1 在 Gate A PASS 后保持冻结。

## 2. Runtime Config（强制）

安装器会在 Runner 目录生成 runtime-config.json，至少包含：
- python_exe
- workspace_root
- nx_mcp_src
- repo_root

Mode B 在开始 drawing interpretation 前执行一次且仅一次 runtime discovery：

1. NX_MCP_WORKSPACE 必须存在；唯一合法配置路径是 <NX_MCP_WORKSPACE>\nx-mcp-plan-runner\runtime-config.json，只能读取这一份。
2. 环境变量缺失、配置文件不存在或 python_exe / workspace_root / nx_mcp_src 缺失时，立即停止并报告 runtime configuration missing。
3. 禁止扫描用户目录、仓库目录、其它 workspace、CLEAN workspace、历史聊天目录、安装目录列表、Python 环境或 PATH 寻找替代 runtime-config、Runner 或 Python。
4. runtime-config.workspace_root 与 NX_MCP_WORKSPACE 规范化后必须相同；不一致时 fail closed。
5. python_exe 必须原样取自 runtime-config 且文件存在；禁止 fallback 到 python、python3、py、系统 Python或 PATH 中其它 Python。
6. nx_mcp_src 必须原样取自当前 runtime-config，不得由历史 repo、backup repo 或其它 workspace 推断。
7. runtime 一旦解析，本轮 drawing、Evidence、Resolver、Gate A、Planner、build/check、Runner 和导出阶段固定使用该 runtime，本轮不得重新发现或切换 runtime。

当前 Mode B 的 raw-evidence.json、reader-visual-aid.json、reader-input.json、reader-contact-sheet.png、reader-crops、reader-observations.json、reader-capture.json、drawing-evidence.json、confirmation-request.json、user-confirmations.json、drawing-evidence-confirmed.json、semantic-draft.json、semantic-draft-confirmed.json、drawing.json、frozen plan、executable plan、report、PRT 和 STEP 必须全部位于 runtime-config.workspace_root；其它目录中已有 artifact 不能成为切换 workspace 的理由。

## 3. 阶段 A：工程图 Evidence → Gate A

正常生产 Reader 只读取 `reader-runtime-contract.md` 与 `nx-drawing-rules.md`。完整 `drawing-reader.md` / `reader-capture-contract.md` 仅供开发、审计或单步排障。

### 3.0 正常 Mode B 唯一生产入口

当本轮有明确 runtime-local raster 路径时，唯一生产入口是：

~~~text
python_exe -m nx_mcp.drawing_intelligence run-hybrid-frontend <current-raster-path> <fresh-hybrid-run-directory>
~~~

一旦本轮 runtime-local raster 路径明确，Agent 禁止打开、查看或视觉解读整张工程图，
禁止提前判断零件类型、feature inventory 或尺寸；这里只允许确认候选 raster 路径存在。
`fresh-hybrid-run-directory 必须在调用前不存在`；Agent 只允许检查该候选路径是否存在，
不得预创建目录、删除目录后重试，也不得执行第二次 frontend。

该入口内部执行 deterministic Reader prep → production Hybrid OCR →
structural-context query plan，并以 `exit code=4, phase=awaiting_structural_context`
停在受限视觉边界。Agent 只读取本轮 `structural-context-queries.json`，逐个查看
query.image_path 一次。**生产 query image 优先是完整工程图上用矩形框标出当前 target region
的 deterministic structural context image；region 只是视觉连通区域，不得假设一个 region
天然等于一个独立正投影视图。Agent 判断的是框选 region 所属 view。**矩形框只负责
region→view 归属，不是尺寸读取边界：同一 query image 中位于框外的 overall 标注，只要能
唯一归属于框选 region 所属的同一个正投影视图，并且尺寸线跨越该视图完整外包轮廓，也必须
允许进入 overall_dimension_facts；不得因为标注在框外就丢弃。属于其它 view 或归属不唯一
的标注禁止借用并保持 unresolved。**旧 reader-input 缺少 `structural_context_path` 时才回退到 region crop。**queries JSON 内置 schema-valid 的 `answer_template`；
Agent 必须原样复制该模板作为 `structural-context-answers.json`，顶层 schema 保持
`structural-context-answers-v1`，禁止自行设计字段。每个 answer 的 query_id 与 evidence
保持模板原值，只允许填写 view_kind、overall_dimension_facts、必填的显式
`rotational_symmetry` 判定与 unresolved；每个 overall fact 固定为 axis + positive value +
evidence:[原样 evidence_label]。对已解析且准备继续的 answer，rotational_symmetry 只能是
`{"status":"established","basis":"centerline","centerline_direction":"horizontal|vertical","evidence":[原样 evidence_label]}`、`{"status":"established","basis":"axial_section_symmetry","evidence":[原样 evidence_label]}` 或 `{"status":"not_established","evidence":[原样 evidence_label]}`。字段省略不能视为
not_established，schema 必须拒绝；模板中的 null 只用于 pending/unresolved。视觉上无法确定时
保持 null 并写 unresolved，本轮 fail-closed，禁止添加 unknown/uncertain 后继续。只有在完整
工程图明确且唯一表达整件绕某一可见工程轴回转时才允许 established；**不要求图纸额外打印 X/Y/Z 轴名**。若 query 明确显示
允许两类 established 视觉依据：①**中心线依据**：纵向正投影或 axial/longitudinal section
中存在贯穿主要主体的明确整件中心线，且主要阶梯/圆柱主体段由围绕该中心线成对出现的相对
同轴轮廓边/肩部表达回转体；②**无中心线轴向剖视依据**：query 通过剖面线/剖切语义明确属于
axial/diametral section，主要材料轮廓与各阶梯/圆柱主体段围绕一条唯一剖面对称轴成对出现，
可唯一确定回转轴方向，即使图中没有画出中心线也允许 established。第二类只适用于明确剖视，
不适用于普通非剖视镜像轮廓；连续实线的物体轮廓/边界绝不能冒充中心线。Agent 禁止直接填写 X/Y/Z 回转轴，也禁止填写无中心线轴向剖视的方向。
centerline basis 只在确有显式中心线时报告 centerline_direction=horizontal|vertical；
axial_section_symmetry 只报告剖视回转语义。其轴方向必须来自 query 的
deterministic_profile_symmetry_axis=horizontal|vertical，由 Reader prep 对当前 region raster
执行多阈值双边拓扑一致性分类得到；该分类只决定方向，不进行 pixel→mm，也不生成工程坐标。
hint 缺失时必须 unresolved。deterministic assembler 再按当前 view_kind + view_axis_map
映射工程轴：front horizontal→X / vertical→Z，side horizontal→Y / vertical→Z，
top horizontal→X / vertical→Y。该判断只允许使用工程制图拓扑语义，禁止测量像素距离或把视觉“等距”换算
成工程值。普通镜像对称、只有中心线但无成对同轴回转轮廓、看起来像回转件、连续实线冒充
中心线或参数名猜测均不足。not_established 不是不确定性的兜底：只有 query 明确显示整件
不具备回转对称时才允许；既无足够 established 证据又无明确反证时必须保持
rotational_symmetry=null、写 unresolved 并 fail-closed。
**Agent 禁止手工补第三轴 overall；确定性闭合固定为 rotation X ⇒ Y=Z、rotation Y ⇒ X=Z、
rotation Z ⇒ X=Y，由 finalizer 从一个直接 transverse overall + established rotational_symmetry axis
推导缺失 transverse overall，并保存 derivation provenance。****局部尺寸不得冒充
`overall_dimension_facts`：只有明确跨越当前视图完整零件外包边界/整体轮廓两端的直接
overall 标注才允许写入；局部链尺寸、孔/圆中心距、中心到边、半径/直径、角度以及仅覆盖
局部轮廓的线性尺寸，即使是最大的可见数字也仍是局部尺寸。缺少明确 overall 时对应 axis
保持 unresolved，禁止为了通过 Adapter 而补值、算术推导或 pixel→mm。**overall fact 的 axis
不得由 Agent 自行推断，必须读取 queries JSON 的 `view_axis_map`：front horizontal=X /
vertical=Z，side horizontal=Y / vertical=Z，top horizontal=X / vertical=Y。view_kind 已确定时必须
清空 `pending_structural_visual_read`；无法唯一判断时保留 structured unresolved 且不得写
overall_dimension_facts。禁止增加其它字段。

随后只允许执行一次：

~~~text
python_exe -m nx_mcp.drawing_intelligence resume-hybrid-frontend <hybrid-frontend-manifest.json> <structural-context-answers.json> <fresh-mode-b-prefix>
~~~

其中 `<fresh-mode-b-prefix>` 必须在这唯一一次调用前确定为当前
`workspace_root` / `NX_MCP_WORKSPACE` 的 **fresh 直接子级 prefix**，例如
`<workspace_root>\\drawing-02-radial-angular-20260928-mode-b`；禁止使用
`<workspace_root>\\mode-b-runs\\...`、Hybrid run directory 或任何其它二级子目录。
Hybrid Frontend 的 run directory 可以位于 workspace 内部子目录，但 Mode B artifact
prefix 不可以。若 resume 因 prefix/path 校验失败，本轮立即 STOP；禁止修正路径重试、
换 prefix 重试或手工继续下游阶段。

resume 内部完成 structural context assembly → Hybrid Adapter → Reader Observation
Finalizer → deterministic Mode B coordinator。若返回 `exit code=0,
phase=mode_b_gate_a_pass`，其 mode_b 子报告/state 中的 canonical drawing 是唯一允许交给
Planner 的语义 artifact；若返回 `exit code=4, phase=mode_b_awaiting_confirmation`，
只展示 mode_b 子报告生成的 1..3 个结构化 confirmation questions，用户选择现有
option_id 后写出 `user-confirmations.json`，并只允许执行一次
`mode_b_coordinator resume <mode-b-state.json> <user-confirmations.json>`。
其它结果 BLOCKED / STOP。**terminal 后禁止二次诊断：首次 terminal/blocked 后只报告
首次失败 phase/reason/errors 并结束，不得再读 OCR report、reader-input、structural
queries/answers、manifest 或其它中间 artifact 来推断如何补救，不得重新解释图纸，也不得提供
“重开 fresh / fallback / 修正后重试”选项。失败报告写完后必须立即结束回复，禁止附加任何
“建议”“下一步”“继续方式”“替代输入”“模式 A”“重新开始”“发起新任务”等恢复性或操作性
内容；新的独立任务只能由用户后续主动发起，Agent 不得在 terminal 回复中建议或诱导用户发起。**

只有本轮没有明确 runtime-local raster 路径或输入不是 raster 时，才使用 fallback
semantic Reader：一次性写出 `reader-observations.json` 后立即调用
`python_exe -m nx_mcp.drawing_intelligence.mode_b_coordinator <reader-observations.json> <fresh-artifact-prefix>`。
若本轮开始时已有明确 raster path，则 fallback 永远不能作为 Hybrid Frontend / Mode B
失败后的恢复路径；只有用户之后明确发起新的独立任务，才允许新建另一轮 fresh production run。

正常 Mode B 中，A1–A5 的 assemble/check/link/resolve/confirmation/canonicalize 细节仅描述
deterministic coordinator 的内部阶段与开发审计语义，**不得由 Agent 逐条手动执行**。
独立 CLI 只能用于用户明确要求的开发、审计或单步排障。

以下 A1–A5 保留为 coordinator 内部阶段定义与调试参考。

### A0.5. Hybrid Frontend raster preparation

当前上传工程图始终是本轮唯一权威几何输入。当当前请求环境**明确提供本轮上传工程图的 runtime-local raster 文件路径**时，Agent 不得在 frontend 前打开/视觉解读整张 raster，不得单独调用 `prepare-reader-input`；正常生产必须直接调用 `run-hybrid-frontend`。fresh run directory 由 Hybrid Frontend 创建，Agent 不得预创建后再删除重试。Hybrid Frontend 内部会且只会对本轮 raster 执行一次等价的 deterministic Reader input preparation：

~~~text
internal: prepare-reader-input <current-raster-path> <fresh-hybrid-run-directory>
~~~

该内部阶段必须一次性生成本轮：

- `raw-evidence.json`；
- `reader-visual-aid.json`；
- `reader-input.json`；
- `reader-contact-sheet.png`；
- `reader-crops\overview.png`；
- `reader-crops\<region>.png`；
- `reader-crops\<region>.<orientation>.<band>.png`。

硬规则：

- 禁止扫描 workspace、用户目录、历史聊天目录或仓库去寻找/猜测当前上传图的文件路径；
- 有明确 current raster path 时，`run-hybrid-frontend` 的 deterministic prep / Hybrid OCR / structural query 任一阶段失败都立即 BLOCKED / STOP；禁止退回 Agent 直接调用 `prepare-reader-input`，也禁止自己写 PowerShell、PIL、.NET 或其它裁图/预处理脚本；
- 没有明确 runtime-local raster path 或输入不是 raster 时，不得扫描寻找替代文件；直接进入 A1 原始 Reader first-pass；
- Hybrid raster 路径的 Structural Reader 只读取 `structural-context-queries.json` 列出的 query.image_path；不得顺序打开全部 crop。fallback semantic Reader 才按其 runtime contract 读取当前原图/辅助图；
- `raw-evidence.json`、`reader-visual-aid.json`、`reader-input.json` 与 Hybrid OCR report 都是 deterministic 中间 artifact；Structural Reader 不得直接把它们当答案来源；
- `reader-input.json` 只提供 geometry-only 的 region / orientation / normalized band / witness-anchor 与 crop 索引，不提供尺寸数字、feature identity 或 endpoint ownership；
- `overflow` bucket 不得截断或猜测；Reader 对该 bucket 只能回到当前原图进行正常视觉判断；
- Reader 禁止创建额外 crop、重新预处理图片、扫描历史文件或重新组织一套 visual search pipeline。

### A1. Reader semantic observations + deterministic Capture assembly

Hybrid raster 路径下，本阶段由 Hybrid Adapter + Reader Observation Finalizer 从本轮
Hybrid OCR 与受限 Structural Reader answers 确定性生成一次 `reader-observations.json`；
Agent 不得手写。只有 no-raster/non-raster fallback 才由 Reader 从当前上传工程图执行一次
连续视觉语义 first-pass 并写一次 `reader-observations.json`。

`reader-observations.json` 使用 `reader-observations-v1`，只记录 Reader 真正判断出的工程语义：standard views、view-local entities、direct values、visible dimensions、physical endpoint ownership 或 structured unresolved、cross-view association visual basis、datum alignment 与 blocking ambiguity。临时 key 只用于本轮文件内引用。

Reader 禁止负责正式 evidence ID/source_ids 展开、`required_targets=[]`、ReaderCapture schema bookkeeping 或最终 Capture ID 编号。

随后立即执行：

~~~text
python_exe -m nx_mcp.drawing_intelligence assemble-reader-capture <reader-observations.json> <reader-capture.json>
~~~

Assembler 只能：
- 校验 `reader-observations-v1`；
- 把临时 view/entity/dimension key deterministic 映射成正式 Capture ID；
- 展开 Reader 已明确给出的 evidence label 为 source_ids；
- 固定写入 schema_version / coordinate_system / required_targets；
- 执行生产 `ReaderCapture.model_validate` 与 `validate_reader_capture_contract`；
- 原子写出唯一 `reader-capture.json`。

Assembler 禁止：
- 创建 Agent 没有声明的 association；
- 把 unresolved endpoint 绑定到某个 entity；
- 根据像素距离、数值相似、对称或零件类型猜 ownership；
- 补 feature inventory、feature value、cross-view identity、datum 或其它工程语义。

Assembler 返回非零或 `written!=true` 时立即 BLOCKED / STOP；保留 reader-observations.json，禁止根据错误重新看图、禁止第二版 observations、禁止手工写 reader-capture.json。

成功生成的 reader-capture.json 是 immutable compiled first-pass visual evidence artifact。Reader 不得直接写 drawing-evidence.json、semantic-draft.json 或 drawing.json，也不得从 check-capture / linker / Gate 0 / Resolver / Gate A 错误反向修正 observations/capture。

### A2. Authoritative Capture check

capture 写出后立即执行：

~~~text
python_exe -m nx_mcp.drawing_intelligence check-capture <reader-capture.json>
~~~

只有以下条件全部成立才进入 A3：

- process exit code = 0；
- schema_valid = true；
- contract_valid = true；
- errors = []。

其它结果立即 BLOCKED / STOP；禁止重新看图、重写 capture 或生成第二版 capture。

### A3. Deterministic identity link + Gate 0

立即使用 runtime-config 指定的 python_exe 执行：

~~~text
python_exe -m nx_mcp.drawing_intelligence link-capture <reader-capture.json> <drawing-evidence.json>
~~~

该命令只做：

- ReaderCapture v2 schema validation；
- view-local entity → deterministic physical feature identity linking；
- explicit association structural validation；
- identity collision detection；
- Gate 0 strict EvidenceGraph validation；
- target grammar / object-path safety；
- frozen Compiler / Resolver / Draft downstream-consumability dry-run。

该程序不得读取工程图，不得访问旧 plan / report / NX model。

只有 process exit code=0、written=true、schema_valid=true、contract_valid=true 才进入 A4。
blocking unresolved 可以保留在 drawing-evidence.json，由 resolve 正式判定 closure。

如果 link-capture 返回非零：
- 保留 reader-capture.json；
- 如已生成 drawing-evidence.json 则保留作失败证据；
- 立即 BLOCKED / STOP；
- 禁止重新看图；
- 禁止第二版 capture；
- 禁止 Edit/Rewrite capture/evidence；
- 禁止继续 Resolver / Gate A / Planner。

### A4. Deterministic compile / resolve

立即使用 runtime-config 指定的 python_exe 执行：

~~~text
python_exe -m nx_mcp.drawing_intelligence resolve <drawing-evidence.json> <semantic-draft.json>
~~~

该命令只做：
- EvidenceGraph schema validation；
- view/projection → axis 编译；
- physical endpoint → formal relation 编译；
- deterministic coordinate / relation resolution；
- conflict / unresolved closure；
- semantic-draft assembly。

该程序不得读取工程图，不得访问旧 plan / report / NX model。

只有以下条件全部成立才进入 A5：
- process exit code = 0；
- written = true；
- ok = true；
- blocking_unresolved = 0；
- conflicts = 0；
- dimension_closure = closed。

如果第一次 resolve 返回非零：
- 保留 reader-capture.json、drawing-evidence.json 与已写出的 semantic-draft.json；
- conflicts > 0 时立即 BLOCKED / STOP；
- 只有在失败原因是 blocking unresolved 时，才允许进入一次 A4.1 Human Confirmation Gate；
- 禁止重新看图；
- 禁止第二版 reader-capture.json；
- 禁止 Edit/Rewrite 原始 drawing-evidence.json 或 semantic-draft.json；
- 禁止直接进入 canonicalizer / Planner。

### A4.1 Human Confirmation Gate（最多一次）

该阶段只允许解决**尺寸端点 ownership**，不得解决 feature inventory、cross-view identity、feature value、start side、termination 或其它语义歧义。

先执行：

~~~text
python_exe -m nx_mcp.drawing_intelligence request-confirmations <drawing-evidence.json> <confirmation-request.json>
~~~

只有以下条件全部成立才允许向用户提问：
- written = true；
- eligible_for_user_confirmation = true；
- unconfirmable_blocking_ids = []；
- question_count 在 1..3 范围内。

否则立即 BLOCKED / STOP。

用户只能从 confirmation-request.json 已提供的 option_id 中选择。禁止：
- 修改尺寸数值；
- 输入任意陌生 target；
- 新增 feature；
- 改孔数量、类型或其它几何语义；
- 重新看图让 Agent 再猜一次。

用户选择写入独立 user-confirmations.json 后执行：

~~~text
python_exe -m nx_mcp.drawing_intelligence apply-confirmations <drawing-evidence.json> <user-confirmations.json> <drawing-evidence-confirmed.json>
~~~

必须保留原始 drawing-evidence.json，不得覆盖。confirmed evidence 只是由用户明确选择派生出的新 artifact。

随后只允许再执行一次：

~~~text
python_exe -m nx_mcp.drawing_intelligence resolve <drawing-evidence-confirmed.json> <semantic-draft-confirmed.json>
~~~

第二次 resolve 只有以下条件全部成立才进入 A5：
- process exit code = 0；
- written = true；
- ok = true；
- blocking_unresolved = 0；
- conflicts = 0；
- dimension_closure = closed。

其它结果立即 BLOCKED / STOP。禁止第二轮用户确认、禁止重新看图、禁止重写 capture/evidence、禁止继续试探 Resolver。

### A5. Canonicalizer + Gate A

只在 A4 直接 PASS，或 A4.1 确认后的第二次 resolve 完整 PASS 后执行。

若 A4 直接 PASS：

~~~text
runner.py canonicalize-drawing <semantic-draft.json> <drawing.json>
~~~

若 A4.1 后 PASS：

~~~text
runner.py canonicalize-drawing <semantic-draft-confirmed.json> <drawing.json>
~~~

canonicalizer 只做 representation-only normalization、preservation guards 与现有 Gate A。

只有以下条件全部成立才算 Gate A PASS：
- process exit code = 0；
- written = true；
- output_exists = true；
- gate_a.ok = true。

PASS 时 drawing.json 是本轮唯一正式 canonical drawing artifact。

其它结果立即 BLOCKED / STOP：
- 禁止改写 semantic-draft；
- 禁止重跑 Reader；
- 禁止重跑 Resolver 试探；
- 禁止手写 drawing.json；
- 禁止单独 validate-drawing 绕过 canonicalizer；
- 禁止进入 Planner。

四种典型结果：
- Evidence 完全闭合 → Resolver PASS → Gate A；
- Evidence 仅存在 1..3 个可确认的 dimension endpoint ownership → 允许一次 Human Confirmation Gate；
- Evidence 存在 feature inventory、cross-view identity 或其它不可确认歧义 → Resolver FAIL / STOP；
- Evidence/semantic 存在真实 relation / geometry conflict → Gate A FAIL / STOP。

## 4. 阶段 B：建模规划

输入可以是工程图模式 A 阶段成功生成的 canonical drawing.json，或文字模式中已经确认完整的结构化建模意图。

读取：
- modeling-planner.md
- runner-contract.md
- certified-tool-contract.json
- nx-mcp-rules.md
- topology-safety.md

正常 Mode B 路径：

~~~text
当前上传工程图
→ [若有明确 raster path：
   run-hybrid-frontend
   → Hybrid OCR
   → awaiting_structural_context
   → bounded Structural Reader answers
   → resume-hybrid-frontend
   → Hybrid Adapter / Reader Observation Finalizer
   → deterministic Mode B coordinator]
→ [若无 raster path：fallback semantic Reader → reader-observations.json → deterministic Mode B coordinator]
→ Gate A canonical drawing.json
→ runner plan-contracts <current-drawing.json>
→ Planner 直接消费 selected implementation + geometries + operation_contracts + planner_contract
   ├─ fixed_args：deterministic Adapter 所有；完整 key set + value 原样复制到 tool_args
   ├─ operation_fields：deterministic Adapter 所有；逐 key 原样展开到 frozen operation 顶层，禁止放入 tool_args/省略
   └─ requires：Planner 只补 symbol wiring + 合法 step 顺序
→ 根据当前 drawing.json 新生成 frozen plan
→ runner build <current-frozen> <current-executable> --drawing <current-drawing>
→ runner check <current-executable> --drawing <current-drawing>
→ 当前 executable plan
~~~

### 4.1 Mode B 当前请求 artifact isolation

- 新请求开始 interpretation 前，现有 raw-evidence.json、reader-visual-aid.json、reader-input.json、reader-contact-sheet.png、reader-crops、reader-observations.json、reader-capture.json、drawing-evidence.json、semantic-draft.json、drawing.json 与 frozen/executable/report/PRT/STEP 一样都是 stale output，不是输入；唯一权威几何输入是当前上传工程图。
- 旧 raw-evidence.json / reader-visual-aid.json / reader-input.json / reader-contact-sheet.png / reader-crops / hybrid-ocr-report / structural-context-queries / structural-context-answers 不得复用；只有本轮 fresh Hybrid Frontend run_dir 内的 artifact 才属于当前 raster 前端。Structural Reader answers 必须固定写入该 run_dir 的 `structural-context-answers.json`，resume 必须拒绝任何其它路径，即使其 query_id / evidence_label 表面相同。
- raster 路径必须由本轮 Hybrid Adapter + Reader Observation Finalizer 重新生成一次性 reader-observations.json；fallback 路径才由 Reader 直接生成；旧 observations 均不得复用。
- observations 写出后必须由本轮 fresh coordinator state 独占生成 reader-capture、drawing-evidence、semantic-draft、confirmation artifacts 与 canonical drawing；Agent 不得手动重建或覆盖这些中间 artifact。
- coordinator Gate A PASS 后必须重新运行 Planner，只从 state 指向的本轮 canonical drawing.json 生成新的 frozen plan；已有 frozen-plan.json 或 executable 不得作为输入，也不得作为已规划完成的依据。
- 写 frozen plan 前必须执行 `runner.py plan-contracts <current-drawing.json>`；只有 exit code=0、ok=true、errors=[] 才能继续。Planner 必须把该结果顶层 `drawing` 原样写入 frozen 顶层 `source_drawing`；后续 build/check 的 `--drawing` 必须与之 canonical absolute-path 精确一致，缺失或跨轮路径不一致 fail closed。无 capability / adapter / operation materialization 时 fail closed，禁止 Planner 自己补算法或绕过。
- Planner 必须消费 plan-contracts 返回的 selected implementation、geometries、recipes、operation_contracts 与 planner_contract；每个 contract operation 的 `tool` 原样使用，`fixed_args` 按完整 key set + 完整 value 原样复制进 tool_args（含 `false` / `0` / 空对象），`operation_fields` 若存在则逐 key 原样展开到 frozen operation 顶层且禁止放入 tool_args；Planner 只补 `requires` 的 symbol wiring 和合法 step 顺序。
- 当前 drawing interpretation 开始后，禁止主动读取旧 frozen/executable plan、旧 Runner report、旧 run_history.json、旧 PRT/STEP，以及其它历史零件的 evidence/drawing/frozen/executable。
- Planner 不得读取 drawing-evidence.json 或 semantic-draft.json；Planner 只读取本轮 Gate A PASS 的 drawing.json。
- Mode B build 固定绑定本轮 drawing：`runner.py build <current-frozen> <current-executable> --drawing <current-drawing>`。
- Mode B executable check 同样必须绑定本轮 drawing：`runner.py check <current-executable> --drawing <current-drawing>`；禁止退化成不带 `--drawing` 的 standalone check 作为 Gate B 依据。
- 只有本轮 observations → coordinator state machine → Gate A 成功后产生的 canonical drawing 才能向 Planner 传递；不引入跨任务身份或 registry。

plan-contracts / build / check 任一首次失败即 B 失败。任一 B 阶段 error 出现后，本轮只允许报告并 STOP：禁止再写或修改 frozen/executable、禁止第二次 build/check、禁止读取 runner.py / plan_schema / NX_MCP 源码排障。Controlled Self-Healing 只属于 Stage C Runner attempt 1 已实际执行后的失败。

## 5. 阶段 C：Plan Runner

Runner 路径：<runtime-config.workspace_root>\nx-mcp-plan-runner\runner.py

### 5.0 正常 attempt 1（唯一入口）

B 阶段只有在 plan-contracts / build / check 全部 PASS 后，才允许执行本轮 current executable。正常 attempt 1 必须使用：

~~~text
python_exe runner.py run <current-executable.json>
  --drawing <current-drawing.json>
  --workspace <workspace_root>
  --report <attempt1-report.json>
  --mode normal
  --repair-attempt 0
~~~

正常 attempt 1 禁止 `--allow-overwrite`、`--repair-report`，不得改用 benchmark 模式，也不得手工逐步调用 NX_MCP 绕过 Runner。Mode B 的 `run --drawing` 必须继续绑定同一本轮 canonical drawing；缺失/不一致在连接 Loader 前 fail-closed。文字模式不带 `--drawing`。阶段 C 成败只以该次 Runner report 为权威。

### 5.1 Preflight
只允许：
- 检查/启动 NX；
- 探测 named pipe nx_mcp_loader；
- 检查 Python/Runner/plan/workspace。

对于 part-entry tool=`nx_create_part` 的新建零件任务，Runner 必须先检查 planned PRT 的磁盘存在性：正常 attempt 1 若文件已存在，直接 `precheck_blocked / planned_part_exists`，禁止覆盖；Loader 自身不得删除任何已存在 PRT。仅 Controlled Self-Healing attempt 2 在 `repair_attempt=1 + benchmark + --allow-overwrite + previous failed report 同一 planned_part` 全部通过后，Runner 可在安全关闭本任务失败目标后删除该精确 planned path。NX 中存在其它已打开零件**不是 blocker**，即使该旧零件存在于 Runner history 中也必须保留：Runner 不调用 `nx_close_part`；Loader 的 `nx_create_part` 必须通过 `Parts.FileNew()` 并设置 `DisplayPartOption.AllowAdditional` 创建新零件，禁止使用 `NewDisplay` 替换当前 display；创建返回后必须立即通过 `nx_status` 同时核对真实 Work Part 路径与 planned_part 完全一致，并确认原 displayed part 仍存在于 `displayed_parts`，任一条件失败则 fail-fast，禁止执行后续建模 operation。对于 part-entry tool=`nx_open_part` / 修改已有零件等非新建任务，Runner preflight 若返回 `precheck_blocked` / reason=`unrelated_part_open`，Agent 必须立即报告并 STOP，禁止生成或执行关闭用户零件的计划，也禁止自动重跑。该 blocker 不属于 Controlled Self-Healing。

Loader ready 优先使用仓库 loader/nx_client.ps1 -Cmd nx_status；CONNECTED + ok=true + ready=true 即 ready。

禁止用 %LOCALAPPDATA%\nx-mcp\bridge.json 判断 resident Loader。

### 5.2 单次尝试的 fail-fast
Runner 正式开始建模后，任一 operation 失败：
- 当前 Runner 尝试立即停止；
- 禁止在当前 dirty model 上继续执行后续步骤；
- 禁止从失败步骤续跑；
- 禁止手动 bridge 补建；
- 禁止手动 save / STEP 导出；
- 记录 failed_step / reason / attempt_elapsed_seconds。

## 6. Controlled Self-Healing（受控自动修复）

### 6.1 次数
每次 Pipeline 最多 1 次自动修复：
- attempt 1 失败 → 可评估 repair；
- repair 后 attempt 2 成功 → 最终成功（自动修复后）；
- attempt 2 再失败 → 最终失败，禁止第三次尝试。

### 6.2 允许修复的范围
只有根因明确、可确定、不会改变设计语义时才允许：
1. edge / face selection_criteria 匹配 0 条或数量不符；
2. Loader 已冻结的返回语义差异；
3. 筛选条件过严，可替换为冻结契约中已验证的稳定组合；
4. frozen/executable 边界污染等纯计划表达错误，且不改变尺寸、特征、选择几何或建模顺序；
5. 上一次失败由当前 Pipeline 自己创建的计划输出零件处于 dirty 状态，需要无保存清理后完整重跑。

### 6.3 禁止自动修复
以下任一情况必须最终失败：
- A 阶段 evidence unresolved / Resolver conflict / Gate A unresolved / dimension conflict / 尺寸缺失；
- 需要重新看图或改 reader-capture.json / drawing-evidence.json；
- 需要猜尺寸、改尺寸、改孔位、改特征数量；
- 禁止数值 nudge / epsilon 修复；
- Controlled Self-Healing 只允许 selection criteria 修复，以及不改变已冻结设计几何语义的确定性 plan-level / selection-level 技术修复；
- 若精确相切/共面导致 NX kernel Boolean 失败，而没有 geometry-preserving 修复路径，必须失败；
- Boolean 不相交且根因属于几何设计/规划错误；
- 超出 certified tools 能力边界；
- 需要新增或修改 NX_MCP / Runner / Loader；
- 非新建任务中当前 dirty/open part 不是本 Pipeline 本次任务自己创建的目标零件；`unrelated_part_open` 必须由用户手动处理，Agent 不得自动关闭或生成关闭计划；新建任务的无关零件仅允许由 Runner 保留并通过 `nx_create_part` 安全切换 Work Part；
- 无法确定修复是否改变最终几何；
- 第一次修复后的 attempt 2 再次失败。

### 6.4 修复过程（强制）
允许修复时必须按以下顺序：
1. 保留 attempt 1 失败报告；
2. 只读诊断失败原因；
3. 生成 repair plan v1，只修改已确认的计划级问题；
4. 重新执行 runner build + check；失败则最终失败；
5. 禁止 Agent 手动关闭 dirty part；
6. 第二次执行必须交给 Runner preflight 安全处理本任务自己的 planned dirty part；
7. 从 C 的第 1 步完整重跑 executable plan；
8. 禁止从 failed_step 接着执行；
9. 最终报告必须披露自动修复次数、首次失败步骤和首次失败原因。

第二次执行必须使用：

~~~text
python_exe runner.py run <repair-executable.json>
  --drawing <current-drawing.json>
  --workspace <workspace_root>
  --report <attempt2-report.json>
  --mode benchmark
  --allow-overwrite
  --repair-attempt 1
  --repair-report <attempt1-report.json>
~~~

## 7. 面选择稳定规则

当目标是唯一顶/底 Planar 面时：
- 首选 face_type:Planar + centroid_z + expectation.count；
- normal 只作为辅助信息；
- area 只辅助；
- 同一 Z 高度存在多个 Planar 面时，再增加完整 centroid 或 area 区分。

## 8. 总耗时

total_elapsed_seconds 必须是真实墙钟时间，从收到开始建模并正式执行，到最终成功/失败报告返回。

如果发生自动修复，总耗时必须包含 attempt 1、失败诊断、repair plan、build/check、dirty part 清理、attempt 2、最终验证与汇报。

C_RUNNER_SECONDS = 所有 Runner 尝试的 elapsed_seconds 之和。

## 9. 用户输出

最终用户可见格式以 chinese-output.md 为准。
