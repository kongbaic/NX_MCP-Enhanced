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

**规则**：先确定各视图 plane / normal 并登记 view-local evidence；严格按 `view-local evidence → feature association → dimension ownership → relation/derived → global coordinates → machine back-check → Gate A` 执行。

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

- 只沿 witness/extension line、leader、arrow endpoint、centerline endpoint、feature boundary endpoint 确定 ownership；附近孤立数字不得覆盖。
- endpoint 决策优先：datum→centerline 直接约束中心，不能因中间经过 step/thickness 再叠加；只有 witness endpoint 真正在 intermediate surface 时才做 local→global derived。
- centerline↔centerline 必须是 `center_distance/center_spacing`；已知 center + relation source 派生 opposite center，同轴组只绑定 group centerline。
- outer min/max edge→feature centerline 必须是 `edge_offset(from=min|max)`，不得写进 profile；只有 profile boundary↔profile boundary 才允许 `profile_dimension`。
- 相同数值若 endpoints 不同，必须保留不同 source/semantic，禁止按数值相同合并 ownership。
- HARD 字段一旦由明确 source 绑定便锁定；同一 source 默认不能跨 feature 复用。
- 槽两侧边界之间的明确尺寸才是槽宽；已绑定的 `slot.width` 不得改写。
- 中心距/中心位置不得解释为 slot depth/bottom；derived 必须声明唯一 `target`。
- directional feature 输出要求：hole/counterbore/countersink → `axis`；slot/cut → `width_axis` + `through_axis`，非贯穿时才另给有证据的 `depth`。
- 孔横向中心坐标固定为：`axis=X → Y/Z`、`axis=Y → X/Z`、`axis=Z → X/Y`；轴本身只用于 axial start/end/range。
- direct source 只表示直接绑定目标；`center_position/position_dimension` 不能承载 edge offset、center distance、symmetry、tangent 或 derived coordinate。
- `center_distance/center_spacing` 是 relation，必须保存 `between:[targetA,targetB]`，且两个 endpoint 都必须是 center coordinate target；不能连接 depth、slot bottom 或 generic field。
- `edge_offset` 必须保存 `axis`、`from:min|max`、`value` 和 `targets`。centered bbox 中 `from=min` 使用 `min_edge + offset`，`from=max` 使用 `max_edge - offset`；`from` 只由真实 witness/extension endpoint 决定。
- `derived` 必须保存唯一 `target`、可计算 `expr` 及所需 source/relation references；关系尺寸不得降级成 direct `feature_dimension`。

### 7.1 同轴复合孔归组

- 通孔 / 沉孔 / 盲孔 / 螺纹孔若有明确证据共享同一轴线，先输出一个 `coaxial_hole_group`，再把不同加工段放入 `members`。
- 归组必须同时满足：同一 `axis`、同一横向 `centerline`、图纸存在共中心线/同心圆/跨视图投影/明确尺寸链等确定性证据。
- 同组 member 必须继承同一个 axis 和 transverse centerline；禁止按视觉邻近为各 member 另设中心。
- 只有 axis 相同但中心线证据不足时不得强行合并；若会影响实体则 blocking unresolved。
- 位置尺寸绑定同轴组 centerline，而不是分别绑定各 member。

### 7.2 C 参数与倒角

- `C2` / `C2×45°` 只有在实际标注明确绑定到边时才表示倒角。
- 参数表字段 `C=2` 不等价于边标注 `C2`；没有明确边绑定时禁止自动生成 chamfer。

### 7.3 Gate A canonical 字段速查

- overall extent：`overall_dimensions.length_x / width_y / height_z`；不用 `x / y / z`。
- feature identity/count：required feature 固定写 `type` 与 `count`，并分别提供 `feature_kind`、`feature_count` provenance；不用 `kind` 代替 `type`。
- hole center：使用 `centerline.x/y/z`、`centerline_x/y/z`、`position.center` 或 `explicit_centers`；不用 `center_x/y/z`。
- slot：`width / width_axis / through_axis`，有直接边界证据时使用 `top_z / bottom_z / start_z / end_z`；不用 `open_from_z`。
- thread：规格写 `spec`，由 `thread_spec` semantic 指向；不用 feature 字段 `thread_spec` 或 `x_start`。
- counterbore：`hole_diameter / counterbore_diameter / counterbore_depth`；不用 `through_diameter / cbore_diameter / cbore_depth`。
- target 必须是实际 JSON path；list 只接受数字索引。relation 不写 direct `target`，中心距 `between` 的两端必须是真实 center coordinate path。
- 第一版必须显式输出 `unresolved / dimension_conflicts / dimension_closure`。normalizer 只做无歧义 schema shape 转换，不承担上述语义字段重命名。

### 7.4 First-pass provenance coherence

- blocking unresolved 指向的 HARD field 必须缺失，不得写猜测值、默认值或 placeholder `0`；已有唯一 provenance 的 concrete field 则不得同时 unresolved。
- 每个 geometry target 只能有一种 value writer：direct 或 derived/relation。direct source 的 `value` 必须等于 target 当前实际值。
- required feature 的 `type`、`count` 和所有已存在 HARD geometry 必须 provenance-complete；`type → feature_kind`，`count → feature_count`。
- canonical profile 固定使用 `profile.segments`；每个 HARD leaf 都要 evidence。由连续/对齐关系确定的 endpoint 使用 derived/relation，不伪装成 direct `profile_dimension`。
- `center_spacing.between` 保留两个真实 endpoint。derived `expr` 必须引用 opposite endpoint target 与 spacing source；若还依赖 symmetry/alignment，关系也必须保留。禁止只计算 `±0.5 * spacing` 生成两端。

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
- 若 overall 为 `Lx×Ly×H`，最终全局 bbox 必须是 X=`[-Lx/2,+Lx/2]`、Y=`[-Ly/2,+Ly/2]`、Z=`[0,H]`。
- 所有 Reader 最终输出的 profile 范围、孔/槽非轴向中心、pattern centers 必须按该坐标系归一化；边缘基准尺寸不能原样冒充中心原点坐标。
- 明确左/右对齐或偏置的 profile 不得因整体 bbox 对称而自动居中；center coordinate 与沿孔轴 start/end/range 必须分离。
- Gate A 前必须做 bbox sanity：用于实体内部加工的孔/沉孔/螺纹孔非轴向中心若超出 overall bbox 且没有图纸明确依据，必须 BLOCK，不得 closed。
- Gate A 前必须做**中心距反算**：图纸明确中心距/节距为 P 时，最终坐标差必须反算为 P。
- Gate A 前必须做**对称反算**：图纸明确关于中心线对称时，成对坐标中点必须回到对称线；若同时已知中心距 P，则关于 0 对称的坐标必须为 `±P/2`，不得产生无依据整体偏移。
- pattern / explicit centers 必须同时通过 count、pitch/span、symmetry 的反算校验；失败即 blocking conflict。
- `N×` 与单轴 spacing 只约束数量和该轴位置，不能创造另一轴坐标；另一轴必须有 direct evidence 或指向各 `explicit_centers` 坐标分量的 relation evidence。
- 上述反算由 `validate-drawing` 机器完成。validator 只能检查图纸已有关系，不得创造尺寸、平移、改符号或修正坐标。
- 所有孔位、凸台位置、特征坐标一律转换到该坐标系后再输出；**不得让下游建模端自行猜测原点**。
- 示例：160×100 底板、孔中心距四周边缘 20 mm → 四孔中心输出 `[-60,-30]`、`[-60,30]`、`[60,-30]`、`[60,30]`。
- JSON 必须包含：
```json
"coordinate_system": {
  "origin": "part_center_xy_bottom_z0",
  "x_positive": "right",
  "y_positive": "up",
  "z_positive": "up",
  "unit": "mm"
}
```
