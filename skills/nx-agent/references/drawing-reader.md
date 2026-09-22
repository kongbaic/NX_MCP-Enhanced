# 二维工程图 Reader Capture v2

本文件是 nx-agent 的二维工程图视觉读取规则。Reader 的职责只到
**view-local evidence capture** 为止，不再直接创建最终 physical feature
identity，也不直接写 `drawing-evidence.json`。

正式字段合同见：

- `references/reader-capture-contract.md`
- `references/nx-drawing-rules.md` 仅作为通用视觉词典

禁止把 benchmark 文档、测试 fixture、旧 evidence、旧 plan 或历史零件答案
作为当前 Reader 输入。

## 1. 固定链路

~~~text
当前上传工程图
↓
Reader
↓
reader-capture.json              immutable first-pass
↓
link-capture                     deterministic
↓
drawing-evidence.json
↓
resolve                          deterministic
↓
semantic-draft.json
↓
canonicalize-drawing / Gate A
↓
Backend v1
~~~

Reader 只执行第一段：

~~~text
工程图 → reader-capture.json
~~~

其余阶段不得重新读取工程图。

## 2. Reader 允许做什么

Reader 可以：

- 识别 front / side / top 标准视图；
- 识别每个 view 中的局部实体及 canonical shape；
- 读取明确尺寸文字、孔径、螺纹、深度、数量、fit、through 等直接信息，并使用固定 canonical field；
- 根据真实箭头 / witness / extension line 绑定 dimension endpoint；
- 记录 measured axis；
- 把图纸直接标出的 overall extent 按标准视图轴映射写入 length_x / width_y / height_z；
- 记录显式 overall-center coincidence；
- 对跨视图候选只记录结构化 association visual basis，由 deterministic linker 决定是否 merge；
- 对 entity_center endpoint 记录 centerline / center_mark / explicit_midline basis；
- 对重复特征使用固定 grouped/member 粒度规则；
- 把不能唯一确定的内容写入 structured unresolved_evidence。
- 新 capture 的 required_targets 固定写空数组，由 linker 确定性派生。

## 3. Reader 不允许做什么

Reader 不得：

- 创建任何最终 physical feature ID（例如自行命名的 `F_FINAL_01`）；
- 在不同 view 之间靠命名强行维持同一 feature；
- 输出任何 `feature:...` final target；
- 根据 overall dimensions 手算 centered global coordinate；
- 把 edge distance 手算成绝对坐标；
- 因为“需要视图轴映射”就把图纸已明确标出的 overall dimension 留成 null；
- 根据圆形投影自己写最终 axis；
- 仅因为数字相等、靠得近、都是孔、看起来对称就合并 entity；
- 猜 start_side / termination / missing dimension；
- 为了闭合而把 intermediate surface 冒充 overall boundary；
- 在 `diameter` / `hole_diameter`、`depth` / `thread_depth` 等同义表达之间自由选择；
- 把 hole 的 edge-on 平行线投影写成 body `profile`；
- 同一 quantity callout 在 grouped entity 与多个 duplicate entity 之间任意切换；
- 自由填写 `centerline` / `centerline.z` 等 required_targets；
- 读取旧 capture/evidence/draft/drawing/plan/report/PRT/STEP；
- 根据 linker / Gate 0 / Resolver / Gate A 错误第二次看图修答案；
- 直接写 semantic-draft.json / drawing.json；
- 宣布 Gate A PASS。

## 4. View-local entity

每个可建模候选只在当前 view 内建立 local entity：

~~~json
{
  "id": "E_FRONT_01",
  "view_id": "V_FRONT",
  "shape": "circle",
  "cross_view_disposition": "associated",
  "source_ids": ["OBS_FRONT_01"],
  "required_for_modeling": true
}
~~~

这个 ID 只是本次 capture 的局部引用，不代表物理 feature 名称。

同一物理 feature 在另一个 view 中必须是另一个 local entity。

## 5. Cross-view association

Reader 不直接下“这两个就是同一 physical feature”的最终结论。

Reader 只记录标准化 visual basis：

~~~json
{
  "id": "A_01",
  "entity_ids": ["E_FRONT_01", "E_SIDE_02"],
  "basis": ["projection_alignment", "shared_centerline"],
  "source_ids": ["OBS_ALIGNMENT", "OBS_CENTERLINE"]
}
~~~

允许的 basis：

- projection_alignment
- shared_centerline
- shared_center_mark
- leader_correspondence
- matching_specification
- explicit_section_correspondence

最终是否 merge 由 deterministic identity linker 决定。

一个 association claim 表示一个候选 physical identity component。新 Capture 中：
- 同一个 entity 只能属于一个 association claim；
- 一个 association claim 在同一个 view 中最多只能包含一个 entity；
- 如果一个 entity 对应多个 plausible counterparts，不得创建多条重叠 association，
  必须改为 cross_view_identity / member_identity unresolved。

对于包含多个标准视图的图纸，每个 modeling-critical local entity 都必须完成一次
cross-view census，并显式写入 `cross_view_disposition`：

- `associated`：该 entity 已进入一个有结构化 basis 的 association；
- `unresolved`：存在合理候选，但不能唯一确认，并且必须进入
  `cross_view_identity` / `member_identity` blocking unresolved；
- `single_view`：已经检查其它标准视图，没有合理的 modeling-relevant counterpart。

不能用“associations 里没写东西”代替 cross-view 判断结果。

标准正交视图中：

- projection_alignment 单独不够；
- shared_centerline / shared_center_mark 只证明对齐、同轴或共线候选，
  不能单独证明 same physical identity；
- same physical identity 必须是 projection_alignment +
  matching_specification / leader_correspondence 之一；
- explicit_section_correspondence 可作为独立强证据；
- matching_specification 指同一个明确 specification 对两个投影形成可追踪对应，
  不是“两个对象都是孔”或两个互补但不同的加工语义；
- 只有 shared_centerline/shared_center_mark、但无法排除 coaxial group /
  overlapping members 时，必须 unresolved，不得 merge。

证据不足：

- 不靠 AI 主观补 merge；
- linker 保持实体分离；
- affected entity 标记 `cross_view_disposition="unresolved"`；
- 如影响建模，进入 `cross_view_identity` / `member_identity`
  blocking unresolved。

如果完整检查其它标准视图后不存在合理 counterpart，则明确标记
`cross_view_disposition="single_view"`。

## 6. Dimension ownership

每个 modeling-critical 可见尺寸标注必须在 `dimensions[]` 中出现且只出现一次。

v2 endpoint 允许：

- overall_min
- overall_max
- entity_center
- unresolved

resolved 示例：

~~~json
{
  "id": "D_01",
  "value": 15,
  "axis": "Y",
  "endpoints": [
    {"role": "overall_max"},
    {"role": "entity_center", "entity_id": "E_TOP_02", "basis": "centerline"}
  ]
}
~~~

Reader 只记录可见的 physical ownership，不计算结果坐标。

每个 endpoint 必须从 dimension line / arrow 出发，沿实际 witness / extension
geometry 单独追踪到被测 geometry。仅仅看到附近存在 centerline、数值正好等于
某个孔距、或根据对称/数量关系推断，都不能把 endpoint 绑定为 entity_center。

`entity_center` 只有在箭头 / witness / extension line 明确落到某一个 local
entity 的 center reference 时才能使用，而且必须写 basis：

- centerline
- center_mark
- explicit_midline

没有 basis 的 entity_center 不属于有效的新 Capture contract。

如果 endpoint 不能唯一归属，不把整条尺寸移到另一套 unresolved 容器。
仍然保留同一个 `dimensions[]` record，把该 endpoint 写成：

~~~json
{
  "role": "unresolved",
  "candidate_entity_ids": ["E_SIDE_01", "E_SIDE_02"]
}
~~~

并在 enclosing dimension 写 `unresolved_reason`。

对于 repeated holes、重叠投影、hidden parallel groups：

- 不能因为“看起来应该在中间”就绑定 entity_center；
- 不能根据对称关系、count、pitch/span 数值反推成员中心；
- 若一条尺寸被解释成 member-center ↔ member-center，两个 endpoint 都必须各自有
  独立可追踪的 witness/extension → center reference；
- 任一端无法独立追踪时，该端必须 unresolved；
- member center 不能唯一对应时使用 unresolved endpoint；
- candidate_entity_ids 只列 visible annotation geometry 真正支持的候选。

如果箭头落在当前 schema 无法表达的 local/intermediate surface：

- 不把它改成 overall；
- 不把它改成 entity center；
- 使用 unresolved endpoint；
- candidate_entity_ids 可以为空；
- 用 unresolved_reason 说明 visible ownership 为什么不可表达。

linker 会 deterministic 地把含 unresolved endpoint 的 dimension 转成 blocking
unresolved，不会替 Reader 猜 endpoint。

## 7. Direct value

v2 direct value 写成：

~~~json
{
  "id": "S_01",
  "entity_id": "E_FRONT_01",
  "field": "diameter",
  "value": 12
}
~~~

Reader 不写：

~~~text
feature:F_XXX.diameter
~~~

最终 target 由 linker 生成。

新 Reader 必须使用固定字段：

~~~text
diameter
fit
thread_spec
thread_depth
depth          # 仅非线程深度
count
through
width
counterbore_diameter
counterbore_depth
~~~

禁止输出 `hole_diameter`；线程“深 N”必须写 `thread_depth`。

重复特征固定规则：

- 一个数量标注、成员没有独立中心定位 → 一个 entity + count=N；
- 成员中心分别有明确、逐成员可追踪的尺寸/标识 → 分成独立 entities；
- 同一 view 禁止同时输出 grouped entity 和同组 member entities；
- 如果一个 view 是 grouped entity、另一个 view 是 individual members，
  禁止把 grouped entity 分别 association 到多个 members；
- 如果无法建立唯一的一对一 member correspondence，保留各 view-local 表示并写
  member_identity unresolved，不得靠 association 把粒度差异压成一个 feature。

外轮廓若只是 overall silhouette、没有被 feature-local value/dimension/association
引用，只放 observations，不额外创建 profile modeling entity。

## 8. Axis

feature 轴向的标准 view 法向映射由 deterministic Compiler 完成：

- front → Y
- side → X
- top → Z

Reader 不根据圆形投影自行写最终 feature axis。

但 dimension / overall extent 的 measured axis 必须在 Capture 阶段按标准视图
方向写成 canonical X/Y/Z。这个动作只是轴映射，不是坐标计算：

- front 水平尺寸 → X；
- side 水平尺寸 → Y；
- 标准正/侧视图竖向尺寸 → Z。

因此，图纸明确标出的 overall extent 必须写入：

~~~text
overall_dimensions.length_x
overall_dimensions.width_y
overall_dimensions.height_z
~~~

三项都必须是正数，禁止 null / 缺省 / 0。

Reader 不得通过算术推导一个图纸没有直接给出的 overall 数值；如果某一 overall
extent 确实无法直接读取，应写 blocking unresolved，并停止本轮 schema-valid
capture 交付，而不是写 null 后宣称验证通过。

## 9. First-pass

First-pass 指一个独立、连续的 drawing interpretation session，不是“只能看图片一眼”。

在唯一一次写盘之前，Reader 可以对当前原始工程图进行必要的反复查看、放大、
分区核对和标注追踪，只要几何输入始终只有当前原图，且没有读取任何 downstream
结果、历史 artifact 或 expected answer。

本 session 最终只允许输出一次：

~~~text
reader-capture.json
~~~

写出后立即冻结。

Reader 写出前必须先在内存中执行生产 schema 校验：

~~~python
ReaderCapture.model_validate(payload)
~~~

仅做 JSON parse、顶层键数量检查或自定义字段扫描不算生产 schema 校验。

如果该校验失败：

- 不写 reader-capture.json；
- 不第二次看图修复；
- 直接汇报验证错误并停止。

生产 schema 校验通过后，才允许执行唯一一次文件写入。

Reader 写出前还要检查：

- overall_dimensions 三轴是否均为正数且来自图纸直接标注；
- 对每个 modeling-critical entity 的可见 centerline / center mark 完成 datum census：
  只有明确与 overall center datum 重合时才写 datum_alignments，所有明确 positive
  alignment 不得遗漏；仅“看起来居中”不得写；
- 每个 view-local entity 是否只属于一个 view；
- 每个 modeling-critical entity 是否有 cross_view_disposition；
- associated / unresolved / single_view 是否和 association / unresolved evidence 自洽；
- direct value 是否绑定到正确 local entity；
- 每个 modeling-critical 可见尺寸是否在 dimensions[] 中恰好出现一次；
- dimension endpoint 是否由真实标注 geometry 支持；
- 不确定 endpoint 是否使用 role="unresolved" + unresolved_reason；
- association 是否有明确跨视图证据；
- required_targets 是否为 []；
- modeling-critical 缺失语义是否进入 structured unresolved_evidence；
- blocking unresolved 是否使用明确 kind，而不是只写自由文本 reason；
- 新 capture 是否没有 standalone kind="dimension_endpoint" unresolved；
- ambiguity 是否显式 unresolved；
- 没有 final feature ID；
- 没有 global-coordinate arithmetic。

写出后 Reader 阶段结束。

## 10. Reader-facing benchmark isolation

Reader benchmark 时只允许看到：

- 当前原始工程图；
- 本文件；
- reader-capture-contract.md；
- 通用 nx-drawing-rules.md。

Reader 不得读取：

- reader-stability-benchmark.md；
- tests / fixtures；
- 任何同图历史 capture/evidence；
- benchmark expected values；
- 其它 Agent/Codex 运行结果。

Reader-facing 文档本身不得包含某一张 benchmark 图的标准答案或 sentinel 数值。
