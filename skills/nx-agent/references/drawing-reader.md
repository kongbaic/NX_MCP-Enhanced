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
2. 第一轮尽可能读取所有会影响三维建模的尺寸、中心线、投影对应与符号；此时只记录**视图内原始证据**和来源，不给可能属于复合特征的成员各自猜全局 centerline。
3. 先做 **feature association**：用中心线、同心圆、投影对应、引线归属、尺寸链等证据，把跨视图重复表达或同一加工轴上的候选成员关联成同一个 feature / composite group。
4. association 完成后，才在**组级别**求 axis、centerline、数量、位置尺寸及 derived 值；同组成员继承组级位置，不得各自重新求一个不同 centerline。
5. 把组级几何一次性转换到固定全局坐标系 `part_center_xy_bottom_z0`。
6. 只用图中明确数值与确定性关系进行尺寸闭合。
7. 输出结构化 JSON。

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
2. 槽/开缝/切口在某视图中显示为两条平行轮廓线时，两线间的明确尺寸只定义该视图平面内的 **width_axis**；**不能由这两条线直接推断 through_axis**。
3. 对 slot/cut 必须分别记录 `width_axis` 与 `through_axis`。若贯穿方向会改变三维结果而图纸不能唯一确定，必须 `unresolved`。
4. DETAIL / 局部放大图若明确由某母视图引出，则继承母视图的平面/法向；若无法确认母视图方向，不得只凭局部图朝向推断全局轴。

## 6. 尺寸归属与特征语义

- **明确箭头/引线优先绑定其实际指向的几何特征。** 同一区域出现其它孤立数值、表格字段或邻近标注时，禁止因为“位置接近”就覆盖明确箭头标注。
- 对开缝/槽：直接跨两侧边界的线性尺寸才可作为 `width`；例如两条槽边之间明确标注 `2`，则槽宽就是 2。附近未通过尺寸线/引线绑定到该槽的 `1.6` 不得替代它。
- `depth` 只能来自明确的深度语义（如 `深12` / `DEPTH 12`）、剖视图中明确的起止面，或其它能够唯一限定切除深度的标注。**普通线性位置尺寸不得因为数值合适就被改解释成 slot/cut depth。**
- 因此像 `E=18` 这类线性/位置参数，除非图纸明确把它绑定为槽深，否则只能保留其原始位置尺寸语义，不能自动写成 `slot.depth=18`。
- 孔类 feature 必须输出 `axis`；slot/cut 必须输出 `width_axis`、`through_axis`（若非贯穿则再输出有明确证据的 `depth`）。任何会改变三维结果的方向字段不能唯一确定时，Gate A 不得 closed。
- **同轴复合孔必须先做 association，再求全局 centerline**：通孔、沉孔、盲孔、螺纹孔等若在不同视图中由共中心线、同心圆、正投影对应、共同引线/尺寸链等明确证据指向同一加工轴，先建立一个候选 `coaxial_hole_group`；**禁止先给每个候选 member 分别赋全局 Z/Y/X，再根据已经猜出的坐标决定是否归组**。
- association 阶段只比较图纸证据，不要求成员已经拥有最终全局坐标。归组完成后才统一求组级 `axis` 与 `centerline`，再让所有 member 继承。成员可以有不同直径、深度、轴向起止侧或加工语义，但不能拥有不同的非轴向中心坐标。
- 同轴归组的证据必须来自中心线、同心圆、跨视图投影对应、明确中心距链或等价确定性关系；**仅仅 axis 相同、数值接近或位于同一区域不足以归组**。证据不足且归组与否会改变实体时，进入 blocking unresolved。
- 对同轴组，位置尺寸（例如两条轴线之间的 `E`）绑定到**组 centerline**，不能只绑定到其中一个 member 后再给其它 member 另猜中心高度。若某参考轴中心高为 40、目标组与其明确中心距为 18，则目标组中心高通过确定性关系得到 58；同组所有 member 继承这一中心线。
- 推荐结构：
  ```json
  {
    "type": "coaxial_hole_group",
    "axis": "X",
    "centerline": {"y": -8, "z": 58},
    "members": [
      {"kind": "threaded_hole", "spec": "M6", "depth": 12, "side": "one_side"},
      {"kind": "through_hole", "diameter": 6.6, "side": "opposite_side"},
      {"kind": "counterbore", "diameter": 11, "depth": 6.5, "side": "opposite_side"}
    ]
  }
  ```
  `side` / 轴向起止范围若会改变实体且无法由图纸唯一确定，仍属于 HARD unresolved；不得用示例中的 side 文本代替真实方向。
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

如果图纸表达一个连续外轮廓，禁止用“矩形 + 圆”等包络图元替代真实轮廓。JSON 必须提供足以唯一重建的 `profile.segments`：直线端点、圆弧圆心/半径/角度、圆角 R、斜边角度及参考方向、相切/连接关系。任一轮廓段不能唯一确定时，加入 `unresolved`。

## 10. Pattern 语义

二维孔阵列同时存在 X/Y 间距时必须输出 `rectangular`。圆周阵列除 count / PCD / angle 外，还必须输出 `start_angle_deg`、`angle_reference` 或 `explicit_centers`。中心线已经明确方向时可直接输出坐标，这不属于比例测量。

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
  "unresolved": [],
  "dimension_closure": {"status": "closed"}
}
```

完整示例：`examples/example-output.json`。
快速视图/标注识别规则：`references/nx-drawing-rules.md`。
