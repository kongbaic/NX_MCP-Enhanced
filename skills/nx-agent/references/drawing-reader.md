# 二维工程图读取模块

本文件是 `nx-agent` 的内部工程图解析规则，不是独立 Skill。

## 1. 目标

把二维机械工程图一次性转换为三维 CAD 建模所需的结构化 JSON。只提取会改变最终三维几何结果的信息。

核心原则：
- 清晰标注直接采信。
- 禁止根据像素、轮廓比例或图纸比例反推尺寸。
- 优先整图一次读取，禁止为非关键内容反复 OCR / 裁剪 / 放大。
- 多视图重复表达同一特征时合并，不重复计数。
- 最终只输出一份结构化 JSON。

## 2. 读取流程

必须按以下顺序执行，禁止把“成员先定全局坐标、之后再归组”作为正常流程：

1. 先观察整张图，识别主视图、俯视图、侧视图、剖视图、局部放大图。
2. 第一轮只保存 **view-local evidence** 和来源，不给候选成员猜全局 centerline。
3. 做 **feature association**：用中心线、同心圆、正投影对应、引线归属和尺寸链关联同一 feature / composite group。其它正交视图里的隐藏矩形或隐藏平行线只作轴向投影候选，不能用该视图 normal 重定义孔轴。
4. 完成 **dimension ownership**：只沿 witness/extension line、leader、arrow endpoint、centerline endpoint、feature boundary endpoint 绑定字段；相同数值出现在不同位置时分别绑定，禁止跨 feature 复用。
5. 建立明确 relation，并计算带唯一 `target` 的 derived；同组成员继承组级 axis/centerline。
6. 最后才转换到固定全局坐标系 `part_center_xy_bottom_z0`；center coordinate 与沿孔轴的 start/end/range 必须分开。
7. 运行 `runner.py validate-drawing <drawing.json>` 做机器反算；机器 Gate A 通过后才交给 Planner。

若 validate-drawing 因 schema 表示形式失败，只允许 schema-only normalization。禁止为了 PASS 新增或修改 source evidence、geometry、ownership、derived relation 或 unresolved；真正缺少 evidence/geometry/ownership 时必须保持 Gate A BLOCKED。禁止从 example 抄取当前零件的 evidence。

## 3. 必须提取

- 总长、总宽、总高、板厚、壳体壁厚
- 线性尺寸、中心距
- Ø 直径、R 圆角、C 倒角
- 通孔、Counterbore、Countersink
- 孔中心、PCD、数量
- 对称、镜像、linear / rectangular / circular pattern
- Shell 开口面和壁厚
- Profile-First 所需的连续轮廓段、圆弧、斜线、圆角、DETAIL / SECTION

## 4. 禁止事项

1. 禁止像素测量、OpenCV/Hough 比例估算或按图纸比例猜尺寸。
2. 禁止为了让尺寸链闭合而自行补尺寸。
3. 禁止把多个分离特征误合并成一个 feature。
4. 禁止忽略 DETAIL / SECTION 后根据主视图外观猜局部结构。
5. 禁止额外生成 HTML、bbox 标注图、重绘图或制造质量报告。

## 5. 固定坐标系与正投影视图方向

```json
{
  "origin": "part_center_xy_bottom_z0",
  "x_positive": "right",
  "y_positive": "up",
  "z_positive": "up",
  "unit": "mm"
}
```

XY 原点为零件整体外形中心，Z=0 为零件底面，+X 向右、+Y 为俯视图向上、+Z 向上。禁止把原点留给下游猜测。

在该固定坐标系下，标准正投影视图与全局轴固定对应：
- 正视图 / Front：位于 **XZ** 平面，视图法向轴为 **Y**；
- 侧视图 / Side：位于 **YZ** 平面，视图法向轴为 **X**；
- 俯视图 / Top：位于 **XY** 平面，视图法向轴为 **Z**。

左右侧视图只改变观察正负方向，不改变“法向轴 = X”的轴语义。第一角/第三角投影只改变视图在图纸上的排布，不改变上述平面/法向轴对应。

方向读取硬规则：
1. 某孔/沉孔/圆柱特征在一个已确定方向的正投影视图中显示为圆时，孔轴/圆柱轴 = 该视图法向轴；若其它视图明确表达不同轴向则进入 `unresolved`/conflict，不得自行选择。
2. 同一孔在其它正交视图中的隐藏矩形或隐藏平行线只表示轴向投影，不能因为其所在视图的 normal 改写孔轴。
3. 槽/开缝/切口在某视图中显示为两条平行轮廓线时，两线间的明确尺寸只定义该视图平面内的 **width_axis**；**不能由这两条线直接推断 through_axis**。
4. 对 slot/cut 必须分别记录 `width_axis` 与 `through_axis`。若贯穿方向会改变三维结果而图纸不能唯一确定，必须 `unresolved`。
5. DETAIL / 局部放大图若明确由某母视图引出，则继承母视图的平面/法向；若无法确认母视图方向，不得只凭局部图朝向推断全局轴。

## 6. 尺寸归属与特征语义

- **明确箭头/引线优先绑定其实际指向的几何特征。** HARD 几何字段一旦由明确证据绑定，其 ownership 锁定；一个 source 默认不能跨 feature 复用，除非图纸明确表达共享约束。
- 对开缝/槽：只有直接跨两侧边界的尺寸可作为 `width`；`slot.width` 一旦明确绑定，不得被其它邻近数值覆盖。
- `depth` / `bottom` 只能来自明确深度语义、剖视图明确起止面或确定性终止关系。中心距、中心位置和普通位置尺寸不能被重新解释成 slot depth / bottom。
- `derived` 必须明确 `target`，并保存所用 source/relation；没有额外证据不得将结果跨 feature 复用。
- 孔类 feature 必须输出 `axis`；slot/cut 必须输出 `width_axis`、`through_axis`（若非贯穿则再输出有明确证据的 `depth`）。任何会改变三维结果的方向字段不能唯一确定时，Gate A 不得 closed。
- 孔的 `center` 只包含与孔轴垂直的横向坐标：`axis=X` 时必须给 Y/Z，X 只能表示 axial start/end/range；`axis=Y` 时必须给 X/Z；`axis=Z` 时必须给 X/Y。禁止把轴向范围误报成横向 center，也禁止把 X-axis hole 描述成“缺 XY center”。
- **同轴复合孔必须先做 association，再求全局 centerline**：通孔、沉孔、盲孔、螺纹孔等若在不同视图中由共中心线、同心圆、正投影对应、共同引线/尺寸链等明确证据指向同一加工轴，先建立一个候选 `coaxial_hole_group`；**禁止先给每个候选 member 分别赋全局 Z/Y/X，再根据已经猜出的坐标决定是否归组**。
- M 系列螺纹、through hole、counterbore 等邻近候选必须按 projection alignment、centerline、specification、leader/witness endpoint 与 feature identity 做 association，再决定是否属于同一同轴组；文本邻近、数值相同或 axis 相同都不能单独证明归组。
- association 阶段只比较图纸证据，不要求成员已经拥有最终全局坐标。归组完成后才统一求组级 `axis` 与 `centerline`，再让所有 member 继承。成员可以有不同直径、深度、轴向起止侧或加工语义，但不能拥有不同的非轴向中心坐标。
- 同轴归组的证据必须来自中心线、同心圆、跨视图投影对应、明确中心距链或等价确定性关系；**仅仅 axis 相同、数值接近或位于同一区域不足以归组**。证据不足且归组与否会改变实体时，进入 blocking unresolved。
- 对同轴组，两条轴线之间的位置尺寸绑定到**组 centerline**，不能只绑定到一个 member 后再为其它 member 猜中心位置；所有 member 共享同一 `axis` 与 transverse centerline，只允许各自的直径、深度、side 和 axial range 不同。
- `side` / 轴向起止范围若会改变实体且无法由图纸唯一确定，仍属于 HARD unresolved。
- **倒角必须有明确边绑定**：只有图中实际出现并通过尺寸线/引线/局部细节绑定到某条边的 `C2`、`C2×45°` 等，才可输出 chamfer feature。参数表中的字段名 `C` 与数值 `2`（即 `C=2`）不能仅因拼起来像 “C2” 就自动解释为 2 mm 倒角。

## 7. 尺寸闭合

`dimension_closure.status` 只允许：
- `closed`：已给尺寸足够且互相一致
- `incomplete`：缺失尺寸导致不能唯一建模
- `conflict`：图上已给尺寸互相矛盾

禁止为了闭合而补尺寸。

## 8. DETAIL / SECTION 与跨视图一致性

DETAIL / SECTION 是局部几何高优先级证据。出现矛盾必须进入 `unresolved`，不得自行选择一个“看起来更合理”的解释。

输出 `closed` 前必须确认：
- 每个孔中心位于最终材料区域；
- 每个切除不会删除其它视图明确存在的关键特征；
- 主视图、DETAIL、SECTION 的拓扑一致。

## 9. Profile-First 复杂轮廓

如果图纸表达一个连续外轮廓，禁止用“矩形 + 圆”等包络图元替代真实轮廓。JSON 必须提供足以唯一重建的 `profile.segments`。正交视图明确表达左对齐、右对齐或偏置时必须保留；不得因为 overall bbox 对称就自动居中。任一轮廓段不能唯一确定时，加入 `unresolved`。

## 10. Pattern / 数量语义

- 图纸的 `N×` 是该 feature 的总实例数；symmetry/mirror 只能解释位置，不能再翻倍。
- `explicit_centers.length == count`；rectangular 必须满足 `count_x * count_y == count`。
- 机器 Gate A 必须用最终 centers/count/pitch/span 反算源数量；不一致即失败。

## 11. 输出结构

```json
{
  "views": [],
  "overall_dimensions": {},
  "coordinate_system": {},
  "profile": {},
  "features": [],
  "patterns": [],
  "symmetry": [],
  "source_ledger": [],
  "derived": [],
  "unresolved": [],
  "dimension_closure": {"status": "closed"}
}
```

`source_ledger` 使用机器可判定的固定语义：

- direct：`overall_dimension / profile_dimension / feature_dimension / feature_count / diameter / radius / slot_width / depth / thickness / axis / center_position / position_dimension / thread_spec / feature_kind / side / through / pattern_dimension`；
- relation：`center_distance / center_spacing / edge_offset / symmetry / upper_tangent / lower_tangent / coincident / alignment`。

Direct source 只写一个 `target`，并且只表示图上尺寸线、引线或符号直接绑定的目标。关系尺寸禁止降级成泛化 `feature_dimension`。由 edge offset、center distance、symmetry、tangent 或其它关系计算的坐标不得伪装成 direct `center_position` / `position_dimension`。

`center_distance / center_spacing` 必须写 `between:[targetA,targetB]`；两个 endpoint 必须是真正的 center coordinate target，例如两个 feature 的 `centerline.z`，不能连接 depth、slot bottom 或其它无关字段。该关系只能服务这两个 endpoint 的推导。

`derived` 必须包含稳定 `id`、唯一 `target`、声明的 `value` 和机器可计算的 `expr`。`expr` 只能通过 `target` / `source` 引用已绑定证据，或使用数值 `const`，并使用 `add/sub/mul/div/neg/abs`；需要相切、对齐、共线等非数值关系时，用 `relation_refs` 引用对应 relation source。跨 feature 推导没有匹配的 relation evidence 时必须 BLOCK。

通用中心距推导形状如下，不得替换为型号专用常量：

```json
{
  "id": "D_TARGET_CENTER",
  "target": "feature:F_TARGET.centerline.z",
  "value": "<computed-value>",
  "expr": {
    "op": "add",
    "args": [
      {"target": "feature:F_REFERENCE.centerline.z"},
      {"source": "S_CENTER_DISTANCE"}
    ]
  }
}
```

从 overall 外形边到中心的尺寸必须写成 `edge_offset`，并保存 `axis`、`from:min|max`、`value` 与一个或多个 `targets`。Reader 必须根据真实 witness/extension endpoint 决定 `from`，不能根据期待坐标反推：

- `from=min`：`coord = min_edge + offset`；
- `from=max`：`coord = max_edge - offset`。

`explicit_centers` 的关系证据应指向具体坐标分量，例如 `feature:F_HOLES.explicit_centers.0.1`。数量和单轴 spacing 不能凭空生成另一轴坐标；缺少该轴的 direct 或 relation evidence 时保持 blocking unresolved。

Reader 不得自报 `coordinate_sanity=pass`。`validate-drawing` 机器计算 source ownership、required geometry evidence、overall/profile/feature bbox、center distance、symmetry 和 count back-check；validator 只能验证图纸已给关系，禁止创造尺寸或修正坐标。

完整示例：`examples/example-output.json`。
快速视图/标注识别规则：`references/nx-drawing-rules.md`。
