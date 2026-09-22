# NX Engineering Drawing Reader — Quick Recognition Rules

本文件只提供视觉识别与制图符号词典。association、endpoint ownership、relation、derived、closure、global conversion、writer 和 canonical policy 唯一由 `references/drawing-reader.md` 定义；本文件不得建立第二套 inference policy。

## 1. 视图识别

| 视图 | 识别线索 | 固定映射 |
|---|---|---|
| Front / 正视图 | 主要外形；常见总高/总长 | XZ plane，normal=Y |
| Top / 俯视图 | 与 Front 垂直投影；常见总长/总宽 | XY plane，normal=Z |
| Side / 侧视图 | 另一正交投影；常见总宽/总高 | YZ plane，normal=X |
| Section / 剖视图 | 剖切符号、剖面线、`A-A` | 读取内部孔、深度、壁厚和台阶 |
| Detail / 局部图 | 放大圈、`DETAIL`、局部编号 | 继承明确母视图的 plane/normal |

第一角/第三角投影只改变视图排布。母视图不明的 Detail 不得仅凭图面朝向确定全局轴。

## 2. Projection 与 same-feature 识别线索

- 圆形投影是 hole/cylinder axis 候选；axis 为该视图 normal。
- 另一正交视图中的隐藏矩形/隐藏平行线是 axial projection candidate，不能单独改写 axis。
- projection alignment、shared centerline、同心圆、相同 specification、leader/witness endpoint 和一致轮廓类型是 same-feature association evidence。
- `M-series thread / through hole / counterbore / countersink` 可在不同视图表达同一 feature 或 coaxial group；邻近、相同数值或相同 axis 本身不是 association evidence。
- same-feature association 只识别 identity；axis projection 和共享 centerline 只作为同一 identity 下的视觉候选，锁定由 `drawing-reader.md` 完成。不同 feature 的 alignment/connected/spacing 仍须建立 evidence-backed relation。
- center coordinate 与 axial start/end/range 是不同几何概念；隐藏线长度不能冒充 transverse center。
- 视觉轴映射速记：axis=X→Y/Z、axis=Y→X/Z、axis=Z→X/Y；它只识别 transverse coordinate axes，不决定尺寸 ownership。

## 3. Annotation 视觉线索

| 图元 | 视觉意义 |
|---|---|
| extension / witness line | 标出被测量端点所在 geometry |
| dimension line + arrows | 连接两个 measured endpoints |
| leader | 将文字、规格或直径/深度符号绑定到 feature |
| centerline / center mark | 表示轴线、圆心、对称或对齐候选 |
| hidden line | 不可见边或孔的轴向投影候选 |
| datum symbol | datum/boundary endpoint 候选 |

邻近文字、相同数字和视觉距离不能替代 endpoint/leader evidence。实际 ownership 只按 `drawing-reader.md` 的 endpoint decision table 判定。

endpoint pair 识别词汇包括 datum→centerline、centerline↔centerline、profile boundary↔profile boundary；这些词汇不在本文件决定 direct/relation/derived representation。

## 4. 常用符号

| 符号/写法 | 含义 |
|---|---|
| `Ø13` | 直径 13 |
| `R8` / `4×R8` | 半径 8，数量由前缀给出 |
| `C2×45°` / `C2` | 明确绑定边时表示倒角 |
| `THRU` / `通孔` | 贯穿 |
| `DEPTH 5` / `深5` | 明确 feature 的深度 |
| `PCD Ø44` / `分布圆Ø44` | 圆周阵列分布圆直径 |
| `⌴` / Counterbore / `沉孔` | 平底沉孔，通常另有直径与深度 |
| `⌵` / Countersink / `沉头孔` | 锥形沉头，通常另有直径与角度 |
| `M8` / `M8深10` | 公制螺纹规格 / 螺纹深度 |
| `2×` / `4×` | 紧随 feature 的总数量 |
| `☐` / `▢` | 方形截面或方台尺寸 |

参数表 `C=2` 不等于实际边上的 `C2`；没有 leader/edge binding 时不能识别为倒角。

## 5. Hole、slot 与 compound-hole 线索

- 圆与中心线：hole/cylinder 候选；同心圆可能表示 counterbore/countersink/coaxial members。
- 螺纹粗细实线、`M` 规格及轴向投影：thread 候选。
- 剖视中的台阶直径和明确深度：counterbore/countersink/stepped-hole member 候选。
- slot/slit 的两条平行 boundary：width_axis 候选；不能仅凭两线推断 through_axis。
- slot 与 circle 共享中心线或轮廓相接：alignment/connected relation evidence 候选；最终 relation 必须由 `drawing-reader.md` 的独立 relation policy 确认。
- 同轴复合孔必须具有同轴线/同心圆/投影对应等视觉证据；只有 axis 相同不能归组。

## 6. Quantity、pattern 与 symmetry 识别线索

| 类型 | 识别线索 |
|---|---|
| Quantity | `N×规格`，数量作用于紧随 feature |
| Symmetry | 点划中心线、双侧对称轮廓、`对称`字样 |
| Mirror | `MIRROR`/`镜像`及明确镜像面 |
| Linear pattern | 单方向重复、明确 count/spacing |
| Rectangular pattern | 两方向 count/spacing |
| Circular pattern | `ON PCD`、`N×均布`、角度或径向中心线 |

这些只用于识别候选关系。pattern/symmetry 不得在本文件中创建坐标、半距、edge offset、source 或 writer；ownership 锁定和 geometry completion 由 `drawing-reader.md` 唯一处理。

## 7. Profile、section 与壳体线索

- 外轮廓、内轮廓、圆弧、斜边及连接点用于识别连续 profile segments。
- Section 的剖面线区域和边界用于识别内部开口、板厚、台阶与壳体壁。
- 两侧明确轮廓及其标注可识别 wall-thickness annotation；无标注时不得按像素估算。
- DETAIL/SECTION 明确表达的局部轮廓优先于主视图中被遮挡的外观。
- 主体/profile 或明确 feature 看得出存在但无法可靠表达时，记录 blocking `unresolved_evidence`，不得静默省略。

## 8. 重复标注与冲突识别

- 同一 feature 在多个视图重复出现的同一 annotation 是 cross-confirmation 候选；保留全部 source views。
- 数值相同但 leader/witness endpoints 不同，不是重复 annotation。
- 同一 measured quantity 在不同视图出现不同数值时，记录 conflict 候选，不得选择较方便的值。
- 数量、规格、直径、深度的文字相同不能单独证明 feature identity。

## 9. Closure 与输出边界

Closure is validation only：不创建 source/writer，不补 concrete coordinate，不改变 endpoint ownership，不推导缺失 geometry。具体状态和 canonical validation 由 `drawing-reader.md` 定义。

- 整图一次读取；禁止像素比例、轮廓测量、Hough/OpenCV 二次估算。
- 只有 schema 本身允许为空、且确实不影响唯一实体的可选信息，才可为 `null / required_for_modeling=false`；不得把此规则用于 `ReaderCapture.overall_dimensions.length_x / width_y / height_z` 等生产 schema 要求为正数的必填字段。
- 影响实体且无法读取的内容必须交由 HARD inventory 进入 blocking unresolved。
- 不输出 bbox 标注图、HTML、图例、质量报告或额外文档。
