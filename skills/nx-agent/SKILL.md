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
3a. **Reader 已确定的语义不再交给 Agent 重判。** 若 structural query 带 `deterministic_non_geometric_reference:true`，其 `answer_template` 的 `unresolved:["non_geometric_reference_region"]` 是 Reader 根据同一区域的明确 OCR 表格标题、无结构候选及独占归属得到的机器判定。Agent 必须原样保留该 query 的 answer，**不看图、不重新判断、不增删字段**。该判定不能用于填补整体尺寸、回转、工程坐标，不能凭“没检测到线条”推断其它区域也是表格。未被 Reader 证明的结构语义继续 fail-closed。此阶段仅迁移了已证实的非几何区域分类，不能声称整个 Structural Reader 已独立化。
3b. 若某个 structural query 自带非空 `deterministic_view_kind` 和 `deterministic_view_label_source_index`，该值是独立 Reader 根据明确的 FRONT/SIDE/TOP VIEW 或中文视图标题、唯一 OCR region 归属及该 region 的正向结构几何证据确定的 view_kind。Agent 必须**原样保留 answer_template 中已填写的 view_kind，不再亲自判断视图名称**，也不能根据其它视觉印象改写它；assembly 会验证其不可篡改。该命中只减少视图分类任务，**不自动宣称 overall、回转、尺寸关系已解决**。若 `deterministic_view_kind` 为空则仍须按正常视觉语义门禁处理，禁止从位置、文件名或邻近视图猜测名称。

4. **正常生产的 Structural Agent 精简规则（旧版完整答案仅作为兼容）**：当前 Fresh Mode B 仅按第4a条输出 `structural-visual-decisions-v1`，禁止写入旧版 `structural-context-answers-v1` 完整模板。进入结构上下文时，只读取本轮 `structural-context-queries.json`；对 Reader 已独立确定的 reference region / view owner / seeded labeled dimension 不再重复看图或回答。未决 query 只读取其已提供的 overview/region 图，若共享 overview 只能读取一次；不得额外裁图、像素换算毫米或根据文字猜测工程尺寸。回转必须有原图中心线及成对同轴轮廓、或明确轴向剖面的成对回转轮廓支持；普通镜像对称和连续实体轮廓线不足以证明回转。视图坐标映射、局部/整体尺寸、结构关系和未解决项严格按 `references/reader-runtime-contract.md` 与第4a条执行；证据不足保持 unresolved 并 fail-closed。不得自行补第三工程轴尺寸、猜孔或尺寸归属。旧版逐字段完整答案规则已原样归档到 `references/legacy-structural-context-contract.md`，**仅处理显式旧版兼容/历史回放时读取；Fresh 生产禁止加载**。
4a. **正常 Mode B 输出精简视觉决策，不再由 Agent 组装整份模板。** **Reader 若将 query 标记为 `deterministic_non_geometric_reference=true`（正证据证明为表格）或带有非空 `deterministic_view_owner_region_id`（多条被接受的尺寸已唯一关联到主视图的辅助标注区），Agent 必须跳过该 query，不得输出对应决策或视觉重分类。表格中的规格数值继续保留于 OCR evidence，不得用于推断几何。标注区的 view_kind 由 Reader 对主区域的已验证 view_kind 继承，绝不自动写 overall/rotation/特征。若所有者主区域仍无视图归属，则 fail-closed。** 【重要：`rotational_symmetry` 只允许 `status`、可选 `basis` 和可选 `centerline_direction`，不允许 `evidence`；整个精简决策都不能抄写模板中的证据字段，Reader 会在合成 canonical answers 时补上。本条优先于旧规则 4；写文件前一次性核对 JSON 键，绝不能以新 schema 装旧 full-answer 内容。】本规则覆盖第4条旧的“原样复制 answer_template、写 structural-context-answers.json”生产步骤；旧格式只保留兼容。每个 `deterministic_non_geometric_reference=false` query 只写一条 `decisions`，最终一次写入本轮目录的 `structural-visual-decisions.json`，顶层 schema 固定 `structural-visual-decisions-v1`。decision 只含 `query_id`、`view_kind`（已 `deterministic_view_kind` 证明可省略）、`overall_dimension_facts:[{axis,value}]`、`rotational_symmetry`、`labeled_dimension_decisions`、`unresolved`；每个数组可以为空，但不可编造工程事实。不写 `evidence`、OCR 数值、模板固定字段、已 seed 的尺寸判断，也不为非几何参考区生成 decision。旋转决策仅给原合同允许的 status/basis/centerline_direction；无法判定则 null 加原合同 unresolved，不能当作 `not_established`。每个未 seed 的 `labeled_dimension_targets` 必须恰好提交一个 target_id/status/visual_direction/relation/可选拓扑字段/reason，禁止漏项或重答。**写入前必须逐个将 `labeled_dimension_decisions[].target_id` 与本轮 queries 中的 `labeled_dimension_targets[].deterministic_relation_seed` 核对：非空 seed 的 target 完全由 Reader 负责，在精简 decisions 中绝不能再次出现（即使值与 seed 一样）；只输出 seed 为空的 target。不得把完整模板中的已 resolved 决策复制进精简 JSON。**由 `resume-hybrid-frontend <hybrid-frontend-manifest.json> <structural-visual-decisions.json> <fresh-mode-b-prefix>` 在一次调用内合成并验证 canonical `structural-context-answers.json`，自动补全 query evidence、已证实 view、OCR topology seeds、完整证据标签；之后直接走现有 Adapter/Resolver/Gate A。仍须逐图确认未确定的 overall/rotation/target 视觉语义；本优化只去除模板机械组装，不等同于独立 Reader 完全替代视觉 Agent。禁止额外单独 assemble 命令或在失败后改用旧格式重试。

4b. **Fresh Structural Reader 不得丢失的直接安全约束**：本轮只按第4a条写精简 decision。结构查询若有共同 `image_path`，**多个 query 若共享同一路径，只打开该共享图一次**，每个 query_id 必须独立判定，不能复制一个结论给全部 query。若 Reader 提供 `deterministic_profile_symmetry_overlay="blue_dashed_topology_axis"`，图中的 `TOPOLOGY SYM AXIS` 蓝色虚线只用于视觉定位，不是原始图纸中心线，**不能单独证明回转**；无原始中心线时，仅当明确是轴向/直径剖视且主要实体轮廓围绕独立拓扑轴成对出现，才允许 `"basis":"axial_section_symmetry"`，普通外形镜像绝不够。对已证实的 `non_geometric_reference_region` 禁止臆造视图或回转。若输入为 `完整工程图 + 当前 target region 矩形框选`，红框仅指示区域，不得把每个 `deterministic region 假设成独立 view`；**矩形框只用于 region→view 归属，不是尺寸标注读取边界**：只有同一 query 图内尺寸线确实指向该区域所属同一视图的整体外轮廓，且可唯一归属时，才能填 overall，**即使尺寸文字或尺寸线画在红框外**也必须按独立证据判定；局部尺寸、跨视图或归属不唯一必须 unresolved，不允许按像素换算或猜测填空。以上规则对精简 decision 仍强制适用，不得因旧版详细规则归档而绕过。

5. **首次 resume 为唯一执行机会。** 正常模式的输入是本轮 `structural-visual-decisions.json`，prefix 必须由 `runtime-config.json` 的 `workspace_root` 和当前 fresh run 名称组成绝对路径；不可依赖当前 PowerShell 工作目录。任何一次 resume 返回失败或 terminal 都必须 STOP，不得修正 prefix/JSON 后重试。历史完整结构输入只作为兼容。 structural answers 写出后只允许执行一次：`python_exe -m nx_mcp.drawing_intelligence resume-hybrid-frontend <hybrid-frontend-manifest.json> <structural-context-answers.json> <fresh-mode-b-prefix>`。**在调用前必须先确定 `<fresh-mode-b-prefix>` 是 `workspace_root` 的 fresh 直接子级 prefix。**prefix 是文件名前缀，不是实际会创建的文件/目录，因此禁止只用 `Test-Path $prefix` 判断 fresh；这种检查即使旧的 `<prefix>-mode-b-state.json` 已存在也可能返回 false。** prefix 必须从本轮 fresh Hybrid run directory 名称确定性派生，例如 `<workspace_root>\\hybrid-run-20260929-140233-mode-b`，禁止继续复用仅含 drawing 名/日期的旧 prefix；也禁止放入 `<workspace_root>\\mode-b-runs\\...`、Hybrid run directory 或任何其它二级子目录。Hybrid run directory 可以位于 workspace 内子目录，但 Mode B artifact prefix 不可以。**为避免额外 Agent 往返，禁止在 structural answers 写出后再单独执行 PowerShell/Test-Path/Get-ChildItem 等 prefix 派生物扫描或 freshness 预检查；Mode B coordinator 已在 resume 内部对 `state_exists` 与全部 stale outputs 做权威门禁。answers 写完后应立即执行唯一一次 resume。若 coordinator 返回 state_exists / stale_outputs / prefix/path 错误，本轮立即 STOP，禁止“修正路径后重试”或换 prefix 再调用。** resume 内部独占执行 structural context assembly → Hybrid Adapter → Reader Observation Finalizer → deterministic Mode B coordinator；Agent 不得手工拼接 partial-reader-observations.json / reader-observations.json，也不得绕过 Hybrid Adapter。
6. Hybrid Frontend resume 返回 exit code=0、phase=mode_b_gate_a_pass 时，唯一允许向后传递的是其 `mode_b` 子报告/state 指向的本轮 canonical drawing artifact。若 exit code=4、phase=mode_b_awaiting_confirmation，或机器报告出现 `human_input_required=true` / `must_stop_for_user_input=true`，**这是强制的人机交互边界**：当前这一轮 Agent 执行必须在读取 confirmation-request、向用户展示当前 request 中最多 1～3 个 evidence-backed **dimension endpoint ownership** confirmation questions/options 后立即结束。**standalone `start_side` 不再属于生产 Human Confirmation：横向螺纹入口语义统一拆为 `material_side + entry_endpoint`；这两个字段必须由确定性拓扑/关联规则建立，无法建立就 fail-closed，不得让用户用单个 `start_side` 替系统补真值。**展示时只允许输出每个 option 的 `option_id` + `label_zh`；**禁止把内部 `target`、`feature:F_...`、`F_..._AMB_...`、Capture E/V/D ID 暴露给用户，也禁止自行扩展 confirmation-request 中不存在的“其它特征中心/整体边界”选项。**若某个 blocking unresolved 没有 evidence-backed candidate，Coordinator 会把它视为不可人工确认并 fail-closed；Agent 不得自己补选项。**严禁 Agent 根据工程图、尺寸大小关系、候选排序、evidence_candidate、历史经验或任何自身推理替用户选择；严禁在同一 assistant/tool turn 内创建 `user-confirmations.json`、调用 coordinator resume，哪怕 Agent 认为答案“显而易见”。** 只有收到**后续一条新的用户消息**，且用户在该消息中明确选择某个现有 option / option_id（或明确选择 KEEP_UNRESOLVED），才允许继续。用户选择后必须为**每一个 confirmation question**写一条 answer（即使选择 KEEP_UNRESOLVED 也必须写），并且 `user-confirmations.json` 顶层与字段固定为 `{"schema_version":"1.0","answers":[{"confirmation_id":"CONF_...","selected_option_ids":["E0_..."]}]}`。**禁止使用 `schema:user-confirmations-v1`、`confirmations` 或单数 `selected_option_id`；这些都不是运行时 schema。** 写完后只允许执行一次 `python_exe -m nx_mcp.drawing_intelligence.mode_b_coordinator resume <mode-b-state.json> <user-confirmations.json>`。其它 exit code / phase 一律 BLOCKED / STOP；禁止第二轮确认。
7. 若当前请求没有明确 runtime-local raster 路径或输入不是 raster，才允许使用 reader-runtime-contract.md 的 fallback semantic Reader：当前图纸一次连续 first-pass → immutable reader-observations.json → `python_exe -m nx_mcp.drawing_intelligence.mode_b_coordinator <reader-observations.json> <fresh-artifact-prefix>`。该 fallback 不得扫描寻找 raster，也不得调用 Hybrid Frontend 猜路径。
8. Hybrid Frontend 或 Mode B coordinator 接管后，正常运行禁止为了处理错误读取实现源码、schema、tool signatures，禁止重写 observations/partial observations，禁止换 fresh prefix 重试，禁止绕过 state machine 手工串联 `assemble-reader-capture` / `link-capture` / `resolve` / Gate A。**terminal 后禁止二次诊断：任何 Hybrid Frontend 失败报告只要出现 `terminal=true` 或 `must_stop=true`，尤其同时给出 `may_retry=false` / `may_edit_structural_answers=false`，这些机器字段优先于 Agent 的自我修复判断；首次 terminal/blocked 结果出现后，只允许向用户报告该首次失败的 phase/reason/errors 并 STOP；不得再读取 OCR report、reader-input、structural queries/answers、manifest 或其它中间 artifact 来寻找“缺什么”，不得重新解释图纸，也不得提供“重开 fresh / fallback / 修正后重试”选项。terminal 回复在失败报告后必须立即结束：禁止附加任何“建议”“下一步”“继续方式”“替代输入”“模式 A”“重新开始”“发起新任务”等恢复性或操作性内容。新的独立任务只能由用户在后续消息中主动发起，Agent 不得在 terminal 回复里建议或诱导用户发起。若本轮一开始存在明确 raster path，fallback semantic Reader 永远不能作为失败恢复路径。只有用户之后明确发起新的独立任务，才允许开启新的 fresh production run。**前端失败不属于 Controlled Self-Healing。只有用户明确要求开发排障时才允许源码审计。
9. Gate A PASS 后进入建模规划时，必须读取 `references/modeling-planner.md`、`references/runner-contract.md`、`references/certified-tool-contract.json`、`references/nx-mcp-rules.md`、`references/topology-safety.md`；Planner 只读取 state 指向的本轮 canonical drawing.json，不得读取中间 reader-capture、drawing-evidence 或 semantic-draft。写 frozen plan **之前**必须先调用已安装 Runner：`runner.py plan-contracts <current-drawing.json>`。只有 exit code=0、`ok=true`、`errors=[]` 才允许继续；任何 capability / adapter / materialization 缺口立即 BLOCKED / STOP。
9a. **Mode B Gate A 后的参考资料读取必须合并，减少 Agent 交互往返。**第9条规定的五份安全参考仍须完整读取、不得省略：若当前工具支持一次传入多个文件，必须在同一次读取调用中批量打开这五份；只有工具确实不支持批量文件读取时才逐份打开。所有文件仅在本轮首次进入 Planner 阶段读取一次，禁止逐文件进度播报、重复检查同一参考、再次浏览目录或读取无关源码；规则已经读取且 plan-contracts 成功后，直接完成 wiring → materialize-frozen → build → check，不插入额外文档读取。任何 Stage B 首次错误仍立即 STOP；本条只优化 Agent 往返，不改变 Gate A/B、工程参数、能力契约或 NX 执行逻辑。
10. Planner 必须直接消费 `plan-contracts` 返回的 selected implementation、geometries、`operation_contracts` 与 `planner_contract`，并把返回的顶层 `drawing` **原样复制到 frozen plan 顶层 `source_drawing`**。Mode B 的 build/check 会把 `source_drawing` 与命令行 `--drawing` 做 canonical absolute-path 精确绑定；缺失或不一致立即 B 阶段失败。每个 contract operation 必须按三层规则机械展开：① `tool` 原样使用；② `fixed_args` 按完整 key set + 完整 value 原样复制进对应 `tool_args`，显式 `false`、`0`、空对象/空集合不得省略；③ 若存在 `operation_fields`，其每个 key/value 必须原样复制到 **frozen operation 顶层**，例如 `operation_fields.thread_surrogate_use` → operation 顶层 `thread_surrogate_use`，**禁止放进 tool_args，也禁止省略**。Planner 只允许再补 `requires` 指定的 symbol wiring、合法步骤顺序与非工程真值执行编排；禁止重算、改写、反推或补默认值；完成机械映射后必须**从零写本轮新的 frozen plan**，不得补丁或复用已有 frozen。
10a. **本轮新建零件输出路径必须在 frozen plan 首次落盘前一次性确定且不复用旧任务文件名。**对于 Mode B 的 `nx_create_part`，直接从本轮已存在的 fresh Hybrid run directory 名称提取 run-id（例如 `hybrid-run-20261008-104002-mode-b` → `20261008-104002`），作为非几何语义的输出文件名后缀：`<part_stem>_20261008-104002.prt`，对应 `nx_export_step` 使用完全相同的 run-id 后缀 `<part_stem>_20261008-104002.step`；这只是命名示例，实际值必须来自**本轮**目录，禁止硬编码示例日期或 DN150 名称。两者都使用 workspace-relative 文件路径，保留全部 geometry / source_drawing / plan-contracts fixed_args 原值，不允许为了文件名改变任何工程参数。禁止为检查文件名重复扫描旧 PRT、run history 或调用额外工具，Runner preflight 是唯一权威的磁盘存在性门禁。若真实用户明确要求固定文件名，仍不得覆盖已存在文件；无法安全实现时 STOP。若 Stage C 正常 attempt 1 返回 `precheck_blocked / planned_part_exists`，本轮立即 STOP：不得事后改 frozen/executable 文件名、第二次 build/check 或自动重跑；文件名碰撞不是 Controlled Self-Healing，也不得以 repair-attempt 绕开 Runner 的保护。

10b. **正常 Mode B 由 Runner 机械展开 Frozen Plan，Agent 不再手写完整参数清单。**第10条的三层参数保存与 Gate B 强制原则不变，但由 deterministic `materialize-frozen` 执行。Agent 只基于本轮 `plan-contracts` 结果一次写出当前工作区的 `mode-b-contract-wiring-v1` JSON（顶层 `schema`、`operations`、可选 `notes`）。**Agent 正常写入的 `notes` 必须是字符串数组（`list[str]`），例如 `"notes":["仅作说明，不参与几何"]`；不要写成单个字符串或对象。`notes` 仅作说明性元数据，不得承载工具参数、工程尺寸或新增操作。Runner 可以将历史 wiring 的字符串/JSON 对象说明规范化为纯文本记录，但绝不把 notes 解释为几何或执行指令。**`operations` 每项必须是 `{"contract_ref":[dispatch_index,contract_index,operation_index],"requires":{...},"topology_changes":true|false}` 或 `{"manual":{"tool":"nx_create_part|nx_save_part|nx_export_step|nx_list_bodies|nx_list_edges|nx_list_faces|nx_list_features|nx_list_sketches","tool_args":{...}},"topology_changes":true|false}`，可带只用于执行编排的 `goal` / `selection_criteria` / `expectation` / `refresh_edges_after` / `refresh_faces_after`。从 `plan-contracts` 的 `wiring_template.operations` 直接复制各个 Adapter `contract_ref`，必须使用 Python 已枚举的三层真实索引；只填写模板中 `requires` 的逻辑符号、`topology_changes`、必要的编排与非几何手动步骤，禁止 Agent 手算 group/index 或自行构造新 ref。模板里的 `null` 表示必须填充，不能直接提交给 materializer。**同一 canonical drawing 最多一次生产 materialize-frozen 调用**：Runner 会以独占 sidecar 记录首次尝试，即使失败时未生成 Frozen、或改 wiring/输出文件名也不得重试。离线开发测试调用纯函数，不可把旧任务再次作为生产 materialize。所有已返回的 Adapter operations 必须恰好覆盖一次；`requires` 名称集合必须与 Adapter 声明完全一致，值必须是 Builder 可绑定、且来自前序生产者的逻辑名（`sketch_id` 用 `sketch_*`，`body_id` / `target_body_id` 用 `body_*`，仅允许 ASCII 字母/数字/下划线）；禁止复制或修改固定参数、写入不属于已选 contract 的几何操作。直接调用已安装 Runner：`runner.py materialize-frozen <current-drawing.json> <current-wiring.json> <fresh-frozen-plan.json>`，它只从**本轮 drawing** 再次取得原始 Adapter 几何参数并逐项展开，同时运行 Frozen Plan/Gate B 检查，首次通过才创建 frozen 文件。**失败即 B 阶段 STOP，不得再手工写 frozen 补救或第二次 materialize/build/check。**旧手工 Frozen 路径仅限既有独立任务兼容；新 Mode B 默认使用该命令。此优化仅减少 Agent 机械参数誊写；图纸尺寸、Feature Contract、Gate A、Stage B、Stage C 门禁完全不变。

10c. **Mode B 可选通用紧凑 wiring（只减少 Agent 重复写 JSON，不减少校验）**：当本轮 `contract_ref_index` 证明一组 Adapter 操作可以共享相同符号时，`operations` 可用 `{"contract_group_ref":[dispatch_index,group_index],"requires":{"sketch_id":"sketch_main"},"topology_changes":false,"topology_change_indices":[N]}` 精确展开一个 group；或者用 `{"contract_dispatch_ref":dispatch_index,"requires":{"body_id":"body_main"},"topology_changes":true}` 按 Adapter 自带顺序展开该 dispatch 下所有 groups。`N` 是**该块内从0开始的操作位置**，仅将相应操作明确标成拓扑变化；它不是工程尺寸或工具参数。共享 `requires` 必须精确等于选中各 operation.requires 的字段并且每个值对所有使用者都成立；如果操作依赖不能共用，**必须退回逐条 `contract_ref` 显式绑定**，不可猜测、覆盖或遗漏。group/dispatch 选择和先后次序由 Planner 根据已经返回的 `contract_ref_index`、生产者与消费者关系明确决定；Runner 只机械展开引用、筛出各操作声明的绑定并重新执行全部固定参数/Gate B 检查。紧凑项不允许附带 `fixed_args`、新几何操作或未知字段，不允许空 group、跳过操作、重复覆盖；失败仍按现有 Stage B 一次性 STOP。原格式仍完全有效，功能仅在证据支持可共享绑定的场景使用。

10d. **使用 Python 预生成的紧凑候选，不再由 Agent 自己从21条引用重新猜分组。** `plan-contracts` 成功返回 `compact_wiring_candidates.dispatch_blocks` 和 `group_blocks`（根据真实 Adapter 索引与 `requires` 联集确定）。这些只是**未完成候选**：`requires` 值为 null，`topology_changes` 为 null，不能直接当作生产 wiring。正常 Mode B 必须先检查候选块能否为其中全部 operation 提供真实相同的符号绑定、明确拓扑变化标记及正确生产者优先顺序；可以共享时优先复制相应候选块，只补必要 symbol 和拓扑信息，以减少逐项 JSON 生成。dispatch/group 块不能重叠覆盖；如果同一 required key 在块内需要不同值、操作必须穿插其它几何操作、或依赖无法唯一求解，则**对该块回退到逐项 `contract_ref`**。最终仍由 `materialize-frozen` 展开并执行完整 Gate B 与首次失败 STOP。候选顺序仅为 Adapter 枚举次序，不是最终建模次序；不得盲目按枚举顺序生成。禁止把候选中的 null 当成有效工程值，禁止从本提示词生成零件专属硬编码。\n
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
