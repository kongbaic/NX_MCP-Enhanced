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

必须按以下顺序执行；association 和 ownership 完成前只保存 view-local 证据，不提前写全局坐标：

1. **视图坐标**：识别 Front / Side / Top / Section / Detail，确定 plane、normal 以及 view-local 轴与全局轴的对应。
2. **Feature association**：用投影对齐、中心线、同心圆、轮廓类型、规格和引线指向关联同一 feature；先归组，后求组级 axis / centerline。
3. **Dimension ownership**：沿 witness/extension line、leader、arrow endpoint、centerline endpoint 与 feature boundary endpoint 绑定尺寸。
4. **Relation / derived**：只用已绑定尺寸和明确的对称、相切、共线、中心距等关系闭合几何；同组成员继承组级位置。
5. **Global conversion**：最后一次性转换到 `part_center_xy_bottom_z0`；center coordinate 与沿轴 start/end/range 分开。
6. **Canonical writer finalization**：先冻结最终 canonical geometry shape，并从该 shape 枚举实际存在的 HARD leaf paths；再为这些 path 收口本次 Reader first-pass 的 direct、relation coverage 与 derived writers。禁止保留 target 不存在的 writer，禁止 direct + derived 同写一个 target，relation 已提供 coverage 后禁止再为该 target 生成 direct/derived。完成 edge coordinate 校验后才可落盘。
7. **Output**：输出本轮 drawing JSON，交由机器 Gate A 验证。

- 正交视图中的 concentric circles、hidden parallel lines 与 thread projection 必须先按 projection alignment、shared centerline、feature identity、specification 及 leader/witness endpoints 做 association。
- `M-series thread / through hole / counterbore` 不得按单视图独立解释；association 阶段不要求候选先有完整 global coordinates。关联完成后统一确定 coax/group axis 与 shared centerline；若对应 feature 在 YZ side view 呈圆形，则 axis=X、transverse center coordinates=Y/Z，members 继承而不重复推断 group axis/centerline。

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

先确定以下标准正投影视图映射，但只用于解释 view-local 证据；全局坐标必须等 association 与 ownership 完成后再写入：
- 正视图 / Front：位于 **XZ** 平面，视图法向轴为 **Y**；
- 侧视图 / Side：位于 **YZ** 平面，视图法向轴为 **X**；
- 俯视图 / Top：位于 **XY** 平面，视图法向轴为 **Z**。

左右侧视图只改变观察正负方向，不改变“法向轴 = X”的轴语义。第一角/第三角投影只改变视图在图纸上的排布，不改变上述平面/法向轴对应。

方向读取硬规则：
1. 某孔/沉孔/圆柱特征在一个已确定方向的正投影视图中显示为圆时，孔轴/圆柱轴 = 该视图法向轴；若其它视图明确表达不同轴向则进入 `unresolved`/conflict，不得自行选择。
2. 同一孔在其它正交视图中的隐藏矩形或隐藏平行线是轴向投影候选；必须先按中心线、投影位置、规格和 feature identity 与圆形投影关联，不能用该视图 normal 改写孔轴。
3. 槽/开缝/切口在某视图中显示为两条平行轮廓线时，两线间的明确尺寸只定义该视图平面内的 **width_axis**；**不能由这两条线直接推断 through_axis**。
4. 对 slot/cut 必须分别记录 `width_axis` 与 `through_axis`。若贯穿方向会改变三维结果而图纸不能唯一确定，必须 `unresolved`。
5. DETAIL / 局部放大图若明确由某母视图引出，则继承母视图的平面/法向；若无法确认母视图方向，不得只凭局部图朝向推断全局轴。

## 6. 尺寸归属与特征语义

- 尺寸 ownership 只由 witness/extension line、leader、arrow endpoint、centerline endpoint 或 feature boundary endpoint 建立；邻近文字和数值不能替代端点证据。
- HARD 字段一旦由明确证据绑定，其归属锁定。一个 source 默认只服务一个字段，除非图纸明确表达共享约束。
- 线性尺寸先按两个实际 endpoints 判定 ownership。datum→centerline 直接约束中心，不因路径经过 step/thickness 再叠加；只有起点明确落在 intermediate surface 时，才以该 surface 与局部尺寸形成 derived。
- 两个 endpoints 都是 center coordinates 时，输出 `center_distance / center_spacing` 与真实 `between`。若目标 coordinate 既没有 direct writer，也没有提供该 target coverage 的 relation，但可由 known opposite center endpoint 加该 relation 唯一求得，才输出 concrete value + derived，而不是因缺少 direct dimension 进入 blocking unresolved；derived 同时引用 opposite endpoint target 与 relation source。禁止在没有 opposite endpoint 时只用 `±0.5*spacing` 凭空生成两端。
- 明确属于 `overall_dimensions` 的全局 min/max boundary→单中心或 `explicit_centers` center coordinate，必须输出 `edge_offset(value,axis,from,targets)`，禁止输出 `center_position`。同一标注约束多个 center coordinate 时，把所有实际 canonical paths 一次列入 `targets`；relation 自身提供 target coverage，被覆盖的 target 禁止再生成 direct/derived。Reader 必须先写并校验 concrete coordinate，且不得把 `edge_offset` 放入 derived numeric expression。方向固定为：`from=min`: `coordinate = min_edge + value`；`from=max`: `coordinate = max_edge - value`。
- 只有 endpoint ownership 明确落在 `overall_dimensions` 的全局 boundary 时，才按 `part_center_xy_bottom_z0` 使用 overall bbox：`X=[-length_x/2,+length_x/2]`、`Y=[-width_y/2,+width_y/2]`、`Z=[0,height_z]`。局部 profile/body/step boundary 不得直接套用 overall bbox；必须按实际 geometry endpoint ownership 和该局部 boundary 的真实 coordinate 处理。

合法 `edge_offset` relation 形状：

```json
{
  "id": "S_EDGE",
  "semantic": "edge_offset",
  "value": 10,
  "axis": "Y",
  "from": "min",
  "targets": ["feature:F_A.centerline.y"]
}
```

- `profile_dimension` 只用于两个 endpoints 都落在 profile/body boundary 的尺寸。任一 endpoint 落在 feature/group/pattern centerline 时，该尺寸属于 feature position/relation；相同数值但 endpoints 不同的标注保持独立 source 与 ownership。
- 对开缝/槽，只有端点分别落在两侧边界的尺寸才可作为 `width`；普通位置或中心距不得改作 depth/bottom。
- `depth / bottom / termination` 只来自明确深度语义、剖视图明确起止面、相切/共线终止关系或等价唯一约束；数值相同不构成语义复用依据。
- direct dimension、relation 和 derived 各自保留来源。由中心距、边距、相切或对称得到的坐标不得伪装成 direct position。
- 孔类 feature 输出 `axis`；slot/cut 输出 `width_axis` 与 `through_axis`。孔的 transverse center 固定为：`axis=X`→Y/Z，`axis=Y`→X/Z，`axis=Z`→X/Y。
- 同轴候选先按 projection alignment、centerline、同心圆、规格和 leader/witness endpoint 做 association，再求一个 `coaxial_hole_group` 的 axis/centerline；邻近、同值或 axis 相同不足以归组。
- group 保存共享 axis/centerline，members 继承而不重复共享 geometry；member 只保留自身直径、spec、depth、side 和 axial range 等加工语义。
- 归组证据不足且是否归组会改变实体时，进入 blocking unresolved；不得先为 members 猜全局坐标再反向决定归组。
- `side` 或轴向起止范围会改变实体而又不能唯一确定时，同样属于 HARD unresolved。
- 倒角只有在 `C2`、`C2×45°` 等标注明确绑定实际边时才成立；参数表 `C=2` 不自动产生倒角。

## 7. 最低充分建模闭合：HARD / DERIVED / SOFT

工程图读取只闭合会改变最终三维实体的内容，不要求把整张图的工艺文字全部解释。

### 7.1 HARD：阻塞建模

以下项目不能唯一确定时，写入 `unresolved` 且 `required_for_modeling=true`：

- 总体尺寸和主体轮廓；
- feature 位置、数量、直径、半径；
- `axis / width_axis / through_axis`；
- 是否贯穿以及非贯穿 feature 真正需要的 depth；
- 会改变实体的圆角、倒角和局部轮廓段。

不得用默认值、视觉比例或邻近数值替代缺失的 HARD geometry。

### 7.2 DERIVED：唯一推导

没有单独标注、但可仅凭已绑定尺寸和明确拓扑关系唯一算出的值进入 `derived`：

- 保存稳定 `id`、实际 `target`、计算结果和 `expr`；
- `expr` 只引用已存在的 geometry target、source 或数学常数；
- 跨 feature 推导必须保留中心距、相切、重合、对齐或对称等关系证据；
- 唯一推导完成后不再写入 `unresolved`。

以下情况不能伪装成 derived：

- 需要像素比例或经验判断；
- 存在两个以上同样合理的解释；
- 必须忽略或修改图上冲突尺寸；
- 仅因结果“看起来合理”而选择正负号或参考面。

### 7.3 SOFT：不阻塞建模

不影响实体唯一性的内容使用 `required_for_modeling=false`，例如：

- 表面粗糙度、普通公差和制造说明；
- 材料、热处理或加工顺序；
- 未参与实体生成的表格字段；
- 与几何无关且 OCR 不清的文字。

SOFT 项可进入 warnings 或 soft unresolved，但不得改变已确认 geometry。

### 7.4 Closure

`dimension_closure.status` 只允许：

- `closed`：HARD geometry 已由 direct、relation 或 derived 唯一闭合，且无 dimension conflict；
- `incomplete`：仍有 blocking unresolved；
- `conflict`：影响实体的已给尺寸或拓扑互相矛盾。

禁止为了闭合而自行补尺寸。

## 8. DETAIL / SECTION 与跨视图一致性

DETAIL / SECTION 是局部几何高优先级证据。出现矛盾必须进入 `unresolved`，不得自行选择一个“看起来更合理”的解释。

输出 `closed` 前必须确认：
- 每个孔中心位于最终材料区域；
- 每个切除不会删除其它视图明确存在的关键特征；
- 主视图、DETAIL、SECTION 的拓扑一致。

## 9. Profile-First 复杂轮廓

如果图纸表达连续外轮廓，禁止用“矩形 + 圆”等包络图元替代。`profile.segments` 必须足以重建：

- 直线端点；
- 圆弧圆心、半径和角度；
- 圆角、斜边及参考方向；
- 段之间的连接、相切和对齐关系。

正交视图明确表达左/右对齐或偏置时必须保留，不得因 overall bbox 对称而自动居中；不能唯一确定的段进入 `unresolved`。

## 10. Pattern / 数量语义

- 图纸的 `N×` 是总实例数；symmetry/mirror 只解释位置，不能再次翻倍。
- `explicit_centers.length == count`；rectangular 满足 `count_x * count_y == count`。
- 只有图纸明确给出二维阵列证据时才输出 rectangular；否则保留 `explicit_centers`。
- circular pattern 除 count/PCD/angle 外，还需图纸明确的 start angle/reference 或 explicit centers。
- 对称中心线只约束坐标中点或镜像关系，不产生额外实例。
- 输出前按最终 centers 或 pattern counts 核对源数量标注；不一致时进入 conflict。

## 11. 输出结构

```json
{
  "overall_dimensions": {},
  "coordinate_system": {},
  "features": [],
  "source_ledger": [],
  "derived": [],
  "unresolved": [],
  "dimension_conflicts": [],
  "dimension_closure": {"status": "closed"}
}
```

### 11.1 最小 canonical contract

#### Roots 与 geometry

- 必需根为 `overall_dimensions / coordinate_system / features / source_ledger / derived / unresolved / dimension_conflicts / dimension_closure`。
- `overall_dimensions` 使用正数 `length_x / width_y / height_z`；`coordinate_system.origin` 为 `part_center_xy_bottom_z0`。
- feature 使用稳定 `id` 和非空 `type`。实际出现的 HARD geometry 必须由 direct、derived 或 relation coverage 支持；不要为了合同而添加图纸没有表达的字段。
- hole-like feature 给出 `axis` 和与该轴垂直的两个 center coordinates；slot/slit 给出正 `width` 以及不同的 `width_axis / through_axis`。
- 第一遍即使用最终 canonical shape：单中心使用 `centerline`，或一致使用 `position.center`；多中心使用 `explicit_centers`，禁止自由命名的 `centers`。geometry 与 source/relation/derived 必须引用完全相同的最终 path；normalizer 不重写 source_ledger / derived references。
- `count` 若输出，必须是正整数并与 explicit centers 或 pattern counts 一致；Runner 不要求所有 feature 一律输出 count。

#### Target 与 direct source

- `target` 必须是实际可解析 path；feature 使用 `feature:<id>.<path>`，list 使用数字索引。
- direct source 具有稳定 `id`、与 target compatible 的 `semantic` 和 direct `target`；若 source 包含 `value`，其值必须等于 target。
- 常用 direct semantic：总体尺寸=`overall_dimension`，轮廓=`profile_dimension`，类型=`feature_kind`，数量=`feature_count`，孔径=`diameter`，槽宽=`slot_width`，深度=`depth`，轴=`axis`，中心=`center_position`，螺纹规格=`thread_spec`。
- 每个已输出的 HARD leaf 同时闭合 provenance：`type→feature_kind`，`axis/width_axis/through_axis→axis`，`through→through`，`spec→thread_spec`，count/diameter/depth 使用各自 compatible semantic；每个已存在的 transverse center coordinate 由 direct、relation 或 derived 覆盖。
- 螺纹 geometry 的 feature leaf 固定为 `spec`，source semantic 才是 `thread_spec`。source 不得指向 drawing 中不存在的 summary/alias field。
- direct 只表示图上尺寸、引线或符号直接绑定的字段。关系尺寸不得降级成泛化 direct position。

#### Relation

- relation source 不写 direct `target`。
- `edge_offset` 保存 numeric `value`、`axis`、`from:min|max` 和一个或多个 `targets`。明确属于 `overall_dimensions` 的全局 boundary 才使用 overall bbox edge±offset；局部 profile/body/step boundary 必须使用其实际 geometry endpoint。Reader 先写并校验得到的 concrete coordinate；该 relation 自身提供 target coverage。
- `edge_offset` 不得作为 derived expression 的 numeric source。
- `center_distance / center_spacing` 只表示 center↔center，`between` 两端都必须是真实 center coordinate paths；`overall_dimensions.*` 或 body/profile edge 不是 center endpoint。overall/body edge→feature center 使用 `edge_offset`。
- `center_distance / center_spacing` relation 本身不覆盖任一 endpoint。
- 若一个 center endpoint 需要派生，derived expression 必须同时引用 opposite endpoint target 和该 distance/spacing source。
- symmetry、alignment、coincident、tangent 等非数值关系只作为 relation evidence，不作为自由 numeric operand。

#### Derived

- 每个 derived 包含稳定 `id`、实际 `target`、声明的 `value` 和可计算 `expr`。
- `expr` 原子只使用 `{"const": 8}`、`{"target": "feature:F_A.centerline.z"}` 或 `{"source": "S_SPACING"}`；`{"value": 8}` 不是 expression node。组合只使用 `{"op":"add|sub|mul|div|neg|abs","args":[...]}`。
- 需要 alignment、coincident 或 tangent 等非数值关系时，使用 `relation_refs`。
- 计算结果必须等于 declared value 和 target 中已写入的 concrete value。
- target 已由 direct source 明确给定时，它是 direct-known target，不得再创建 derived writer；target 已由 relation 提供 coverage 时也不得再创建 direct/derived writer。尺寸链一致性只能验证，尤其不得反向 derived 写 `overall_dimensions.*`。

#### Reader first-pass self-consistency

首次落盘前，Reader 必须以最终 canonical geometry shape 为准完成以下检查：

1. 每个 direct source target、relation `targets` / `between` path 和 derived target 都实际存在；不存在的 target 禁止生成 writer。
2. 对本次 Reader first-pass 生成的 writers 建立 target inventory：禁止 direct + derived 同 target；relation 已提供 coverage 后禁止再为该 target 生成 direct/derived。
3. overall edge→center 必须使用 `edge_offset`；共享同一 edge 标注的 `explicit_centers` coordinates 必须一次列入同一 `targets`，不得另建复制型 derived。
4. 明确属于 `overall_dimensions` 的全局 boundary 按 `part_center_xy_bottom_z0` 解析：`X=[-length_x/2,+length_x/2]`、`Y=[-width_y/2,+width_y/2]`、`Z=[0,height_z]`。每个 concrete target 必须满足 `from=min` 的 `min_edge + value` 或 `from=max` 的 `max_edge - value`。
5. 局部 profile/body/step boundary 不使用 overall bbox；按其实际 geometry endpoint ownership 与真实 coordinate 计算。

这是 Reader first-pass 输出前的 self-consistency 规则，不表示 Runner 已实现普遍的 exactly-one-writer 合同。

以下 compact canonical example 锚定 feature object 与 ledger 使用同一 canonical path，并示范合法 center relation/derived reference：

```json
{
  "features": [
    {"id": "F_A", "type": "threaded_hole", "axis": "X",
     "centerline": {"y": 0, "z": 20}, "spec": "M6"},
    {"id": "F_B", "type": "hole", "axis": "X",
     "centerline": {"y": 0, "z": 38}}
  ],
  "source_ledger": [
    {"id": "S_A_TYPE", "semantic": "feature_kind", "value": "threaded_hole", "target": "feature:F_A.type"},
    {"id": "S_A_AXIS", "semantic": "axis", "value": "X", "target": "feature:F_A.axis"},
    {"id": "S_A_Y", "semantic": "center_position", "value": 0, "target": "feature:F_A.centerline.y"},
    {"id": "S_A_Z", "semantic": "center_position", "value": 20, "target": "feature:F_A.centerline.z"},
    {"id": "S_A_SPEC", "semantic": "thread_spec", "value": "M6", "target": "feature:F_A.spec"},
    {"id": "S_B_TYPE", "semantic": "feature_kind", "value": "hole", "target": "feature:F_B.type"},
    {"id": "S_B_AXIS", "semantic": "axis", "value": "X", "target": "feature:F_B.axis"},
    {"id": "S_B_Y", "semantic": "center_position", "value": 0, "target": "feature:F_B.centerline.y"},
    {"id": "S_SPACING", "semantic": "center_spacing", "value": 18,
     "between": ["feature:F_A.centerline.z", "feature:F_B.centerline.z"]}
  ],
  "derived": [{
    "id": "D_CENTER_B", "target": "feature:F_B.centerline.z", "value": 38,
    "expr": {"op": "add", "args": [
      {"target": "feature:F_A.centerline.z"},
      {"source": "S_SPACING"}
    ]}
  }]
}
```

多中心 geometry 与 relation 统一使用 `explicit_centers`，例如 named-coordinate path `feature:F_HOLES.explicit_centers.0.x`；若 item 使用坐标数组，则 path 使用对应数字索引。不要输出或引用自由命名的 `centers`。

#### Profile、unknown 与 closure

- `profile` 中实际出现的 HARD geometry 必须有 coverage；允许一个 ancestor target 覆盖 descendants，不要求每个 leaf 独立 source。
- Profile 使用当前 accepted `profile.segments`，source/derived/relation 只能引用真实存在的 boundary path，例如 `profile.segments.0.y1`；禁止为尺寸语义发明未写入 geometry 的 `pad_height / plate_width_y / pad_width_y` 等 summary fields。
- 例如直接边界可用 `{"semantic":"profile_dimension","value":-16,"target":"profile.segments.0.y1"}`；其它已存在 HARD geometry 仍须由兼容 direct、derived、relation 或合法 ancestor coverage 闭合，本例不要求每个 leaf 都单独 source。
- 连续、对齐或 overall boundary 推导出的 profile endpoint 使用 derived/relation；只有直接标注的 profile boundary 才使用 direct `profile_dimension`。
- blocking unresolved 指向的字段不得保留 concrete value、默认值或 placeholder `0`；soft unresolved 不改变已知 geometry。
- Gate A PASS 要求 blocking unresolved=0、dimension conflicts=0、`dimension_closure.status="closed"`，并同时通过其它机器结构、coverage 和 coordinate checks；`closed` 字样本身不能替代这些检查。

快速视图/标注识别规则：`references/nx-drawing-rules.md`。
