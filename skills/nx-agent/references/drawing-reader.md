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
- 识别每个 view 中的局部实体及 shape；
- 读取明确尺寸文字、孔径、螺纹、深度、数量、fit、through 等直接信息；
- 根据真实箭头 / witness / extension line 绑定 dimension endpoint；
- 记录 measured axis；
- 记录显式 overall-center coincidence；
- 在存在充分视觉证据时提交跨视图 association claim；
- 标出 required modeling fields；
- 把不能唯一确定的内容写入 unresolved_evidence。

## 3. Reader 不允许做什么

Reader 不得：

- 创建 `F_MAIN`、`F_BORE`、`F_HOLE20` 之类最终 physical feature ID；
- 在不同 view 之间靠命名强行维持同一 feature；
- 输出任何 `feature:...` final target；
- 根据 overall dimensions 手算 centered global coordinate；
- 把 edge distance 手算成绝对坐标；
- 根据圆形投影自己写最终 axis；
- 仅因为数字相等、靠得近、都是孔、看起来对称就合并 entity；
- 猜 start_side / termination / missing dimension；
- 为了闭合而把 intermediate surface 冒充 overall boundary；
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
  "source_ids": ["OBS_FRONT_01"],
  "required_for_modeling": true
}
~~~

这个 ID 只是本次 capture 的局部引用，不代表物理 feature 名称。

同一物理 feature 在另一个 view 中必须是另一个 local entity。

## 5. Cross-view association

只有当图纸本身提供足够证据时，Reader 才写：

~~~json
{
  "id": "A_01",
  "entity_ids": ["E_FRONT_01", "E_SIDE_02"],
  "source_ids": ["OBS_SHARED_CENTERLINE"]
}
~~~

这只是“这些 view-local observations 很可能是同一物理 feature”的明确证据声明。

最终 physical feature ID 由 deterministic identity linker 生成。

如果不能唯一确认：

- 不 association；
- 不猜；
- 如影响建模，写 blocking unresolved。

## 6. Dimension ownership

v2 endpoint 只有：

- overall_min
- overall_max
- entity_center

示例：

~~~json
{
  "id": "D_01",
  "value": 15,
  "axis": "Y",
  "endpoints": [
    {"role": "overall_max"},
    {"role": "entity_center", "entity_id": "E_TOP_02"}
  ]
}
~~~

Reader 只记录可见的 physical ownership，不计算结果坐标。

如果箭头落在当前 schema 无法表达的 local/intermediate surface：

- 不把它改成 overall；
- 不把它改成 entity center；
- 直接 unresolved。

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

## 8. Axis

标准 view 法向映射全部由 deterministic Compiler 完成：

- front → Y
- side → X
- top → Z

Reader 只记录 view kind 与 projection shape。

如果 axis 本身有独立明确标注，可作为 direct semantic evidence；否则禁止凭经验写最终 axis。

## 9. First-pass

对当前图纸只允许一次视觉读取，输出一次：

~~~text
reader-capture.json
~~~

写出后立即冻结。

Reader 写出前只检查：

- 每个 view-local entity 是否只属于一个 view；
- direct value 是否绑定到正确 local entity；
- dimension endpoint 是否由真实标注 geometry 支持；
- association 是否有明确跨视图证据；
- required HARD inventory 是否没有静默遗漏；
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
