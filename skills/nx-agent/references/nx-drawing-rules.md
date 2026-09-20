# NX Engineering Drawing Reader — Quick Recognition Rules

快速识别规则手册。用于把二维机械工程图一次性转换为三维建模结构化 JSON。
核心原则：**有印刷标注就信标注，禁止像素测量与比例估算；只看一次，重复尺寸跨视图合并。**

---

## 1. 视图识别（主视图 / 俯视图 / 侧视图 / 剖视图）

| 视图 | 识别线索 |
|---|---|
| 主视图 Main | 图面最完整的外形轮廓；常标 总高/总宽；通常标注“主视图”或无需标注即为基准视图 |
| 俯视图 Top | 与主视图垂直投影；常标 总长/总宽；轮廓上方/下方常有“俯视图”字样 |
| 侧视图 Side | 与主视图正交的另一投影；提供 总宽/总高 的补充尺寸 |
| 剖视图 Section | 带剖切符号与标注（如 `A-A`、`SECTION A-A`、剖面线 hatched）；给出内部结构：孔径、深度、壁厚、台阶 |
| 局部放大图 Detail | 标注如 `DETAIL B`、`I` 放大圈；用于读小尺寸与倒角/圆角细节 |

**规则**：先确定各视图 plane / normal 和 view-local 轴，再登记标注；feature association、dimension ownership 完成后才转换全局坐标。

### 1.1 正投影视图 → 全局轴（硬契约）

在 nx-agent 固定坐标系中：
- Front/正视图 = XZ 平面，法向轴 Y；
- Side/侧视图 = YZ 平面，法向轴 X；
- Top/俯视图 = XY 平面，法向轴 Z。

第一角/第三角投影只改变排布，不改变该轴对应。

由此：
- 某孔在一个已确定方向的正投影视图中显示为圆 → 该孔 `axis` = 该视图法向轴；
- 同一孔在另一正交视图中的隐藏矩形/隐藏平行线只是轴向投影候选，不能据此把孔轴改为该视图法向；
- 槽/开缝在某视图显示成两条平行边 → 两边间距只确定 `width_axis`，不能直接当作 `through_axis`；
- 局部放大图必须继承明确母视图的方向；母视图不明则方向保持 unresolved。

## 2. 跨视图尺寸对应关系

**处理顺序：view-local evidence → feature association → dimension ownership → relation/derived → global coordinates。**
禁止先给每个视图里的孔/沉孔/螺纹孔各自写一个全局中心坐标，再根据这些已猜坐标决定是否属于同一特征。

- 圆形投影决定候选孔 axis；其它正交视图中的隐藏矩形/隐藏平行线只是 axial projection candidate，不得用该视图 normal 改写 axis。
- M 系列螺纹、through hole、counterbore 等候选按 projection alignment、centerline、specification、leader/witness endpoint 和 feature identity 关联；邻近或数值相同不足以归组。
- 同一 feature 在多个视图重复表达时合并为一个 feature；同一 coaxial group 的 members 共享 `axis` 与 transverse centerline。
- center coordinate 与 axial start/end/range 必须分开；沿孔轴的范围不得写成横向中心坐标。
- 视图明确显示左/右对齐或偏置时保留该关系，不得因 overall bbox 对称而自动居中。

## 3. 标注符号速查

| 符号/写法 | 含义 | 建模用法 |
|---|---|---|
| `Ø20` | 直径 20 | 圆柱/孔直径 |
| `R8` / `4×R8` | 半径 8，4 处 | 圆角/圆弧半径 |
| `C2×45°` / `C2` | 2mm×45° 倒角 | 棱边倒角 |
| `THRU` / `通孔` | 贯穿 | 通孔 |
| `DEPTH 5` / `深5` | 深度 5 | 沉孔/盲孔深度 |
| `PCD Ø44` / `分布圆Ø44` | 分布圆直径 44 | 圆周阵列孔所在圆 |
| Counterbore / `沉孔` / `⌴` | 平底沉孔 | 沉孔直径+深度 |
| Countersink / `沉头孔` / `⌵` | 锥形沉头 | 沉头孔直径+角度（通常 90°） |
| `2×` `4×` `6×` | 数量 | 特征 count |
| `☐`/`▢` | 正方形/方形特征（如 `☐60` 方台） | 方形截面尺寸 |

## 4. 数量标注

- 格式 `数量×规格`，如 `4×Ø8 THRU`、`4×R8`、`4×Ø6.6 ON PCD Ø44`。
- 数量作用于紧随其后的特征；同一标注行内多个规格依次计数。
- `N×` 是该 feature 的总实例数，不得再因 symmetry/mirror 翻倍；`explicit_centers.length` 和 `count_x*count_y` 必须与 count 一致。

## 5. 对称 / 镜像 / 阵列

| 类型 | 识别线索 | 建模输出 |
|---|---|---|
| 对称 Symmetry | 十字中心线（点划线）、双侧对称轮廓；`对称` 字样 | symmetry 条目；中心位置由中心线确认 |
| 镜像 Mirror | `MIRROR`/`镜像` 字样、左右相同结构 | symmetry 条目（镜像面） |
| 线性阵列 Linear | 单方向等距重复（`N× 间距`） | patterns: type=linear，spacing 取标注间距 |
| 矩形阵列 Rectangular | X/Y 两方向均有间距的规则孔阵 | patterns: type=rectangular，count_x/count_y/spacing_x/spacing_y；**禁止写成单一 linear**；阵列形式无法明确判断时保留 explicit_centers 明确坐标，不强行分类 |
| 圆周阵列 Circular | `ON PCD Øxx`、`N× 均布`、角度标注；孔位与中心线/对称线对齐 | patterns: type=circular，pcd=直径，angle=均布角（360/N）。图纸以中心线/对称线/水平垂直关系表达孔位方向时必须输出 start_angle_deg + angle_reference + explicit_centers（读取“对齐关系”不属于比例测量、不属于尺寸猜测）；只有图纸确实未表达旋转方向且方向不影响模型时，start_angle_deg 才可为 null |

## 6. 壳体壁厚

- 剖视图两侧轮廓线间距即为壁厚；常有直接标注（如 `壁厚2`、`T=2`）。
- 无标注时：不得测量轮廓估算；标 unresolved（仅当影响唯一建模结果时）。

## 7. 尺寸归属与深度语义

- 只沿 witness/extension line、leader、arrow endpoint、centerline endpoint 和 feature boundary endpoint 确定 ownership；邻近数字不能替代端点证据。
- HARD 字段一旦绑定便锁定；同一 source 默认只服务一个 geometry field。
- datum→centerline 直接约束中心，不因中间经过 step/thickness 再叠加；只有起点实际落在 intermediate surface 时才做 local→global derived。
- centerline↔centerline 使用 `center_distance/center_spacing` 与真实 endpoints；已知中心加 relation source 派生另一中心。
- outer min/max edge→centerline 使用 `edge_offset`；只有 profile boundary↔profile boundary 才是 `profile_dimension`。
- 相同数值但 endpoints 不同的标注保持独立 ownership。
- 槽两侧边界之间的尺寸才是槽宽；中心距和普通位置尺寸不得解释为 slot depth/bottom。
- hole/counterbore/countersink 输出 `axis`；slot/cut 输出 `width_axis` 与 `through_axis`。孔横向中心为 `axis=X→Y/Z`、`axis=Y→X/Z`、`axis=Z→X/Y`。

### 7.1 同轴复合孔归组

- 通孔 / 沉孔 / 盲孔 / 螺纹孔若有明确证据共享同一轴线，先输出一个 `coaxial_hole_group`，再把不同加工段放入 `members`。
- 归组必须同时满足：同一 `axis`、同一横向 `centerline`、图纸存在共中心线/同心圆/跨视图投影/明确尺寸链等确定性证据。
- 同组 member 必须继承同一个 axis 和 transverse centerline；禁止按视觉邻近为各 member 另设中心。
- 只有 axis 相同但中心线证据不足时不得强行合并；若会影响实体则 blocking unresolved。
- 位置尺寸绑定同轴组 centerline，而不是分别绑定各 member。

### 7.2 C 参数与倒角

- `C2` / `C2×45°` 只有在实际标注明确绑定到边时才表示倒角。
- 参数表字段 `C=2` 不等价于边标注 `C2`；没有明确边绑定时禁止自动生成 chamfer。

## 8. 尺寸闭合检查

- 仅基于图上已标注数值进行一致性校验，例如：
  - 总高 = 底板厚度 + 凸台高度
  - 总宽 = 2 × 孔中心距 + 分布圆直径
  - 沉孔数量 = 通孔数量
- 允许的结论：`closed`（自洽）、`incomplete`（标注不足）、`conflict`（矛盾）。
- **禁止自行补尺寸来闭合**；不闭合不影响已确认特征的输出。

## 9. 重复尺寸跨视图合并规则

1. 同一几何特征在 ≥2 个视图（俯视/主视/剖视）出现相同尺寸或相同标注 → 视为**交叉确认**：合并为 1 个 feature，`source_views` 收录全部来源视图，confidence 升为 high，**不得因此产生 unresolved**。
   - 示例：同一个凸台顶外圆 `C2×45°` 在两个视图中重复出现 → 只输出一个 chamfer feature。
2. 同一特征不同数值（如总高在主视图与剖视图）→ 合并核对：一致则保留并升 confidence；矛盾则入 unresolved 并标 dimension_closure=conflict。
3. 合并依据：特征类型 + 数值 + 位置关系一致，而非标注文字相同。
4. 只有两个标注**明确指向不同几何位置**且无法判断所指时，才允许 unresolved。

## 10. 性能与边界规则

- 整图只看一次；第一轮提取全部建模信息。
- 清晰标注直接采信，禁止像素比例/轮廓测量/Hough/OpenCV 二次估算。
- 禁止为确认非关键信息反复裁剪放大 OCR。
- 图纸未定义且不影响唯一建模结果的信息 → `null` + `required_for_modeling: false`，停止分析。
- 影响建模且确实无法读取 → `unresolved`。
- 不输出 bbox 标注图 / HTML / 图例 / 质量报告 / 额外文档，只输出结构化 JSON。

## 11. 固定输出坐标系

- XY 原点 = **零件整体外形中心**；Z=0 = **零件底面**；+X 向右、+Y 向上（俯视图）、+Z 向上。
- association、ownership 和 relation 完成后，才换算 profile、孔/槽横向中心与 pattern centers；边缘基准尺寸不能原样冒充中心坐标。
- 明确左/右对齐或偏置的 profile 不得因整体 bbox 对称而自动居中；center coordinate 与轴向 start/end/range 分离。
- 禁止让下游建模端自行猜测原点。JSON 声明：
```json
"coordinate_system": {
  "origin": "part_center_xy_bottom_z0",
  "x_positive": "right",
  "y_positive": "up",
  "z_positive": "up",
  "unit": "mm"
}
```
