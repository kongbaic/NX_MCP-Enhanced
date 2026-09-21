# 二维工程图读取模块

本文件是 `nx-agent` 唯一的工程图语义决策 contract。`references/nx-drawing-rules.md` 只提供视觉识别词典，不得覆盖本文件的 association、ownership、relation 或 derived policy。

## 1. 目标与边界

把二维机械工程图一次性转换为三维 CAD 建模所需的 semantic draft，只提取会改变最终实体的内容。

- 清晰标注直接采信；禁止像素、轮廓比例或图纸比例反推尺寸。
- 多视图中同一 feature 的重复表达合并，不重复计数。
- 不确定且影响实体的内容进入 blocking `unresolved`，不得猜测、默认或静默省略。
- 最终只输出一份 `semantic-draft.json`；不得直接创建正式 `drawing.json`。

## 2. 唯一 semantic decision chain

必须严格按以下顺序执行；后一步不得重新分类前一步已经锁定的 annotation 或 ownership。

1. **Annotation / same-feature projection association**：保存 view-local evidence；必须穷尽整图中的 same-feature orthographic candidates 后才能输出 axis/center 或 unresolved。association 本身不建立不同 feature 之间的数值关系。
2. **Physical endpoint ownership**：按 witness/leader/arrow 绑定 annotation identity、feature/view、physical endpoints 和唯一 measured quantity；此前 annotation 的数值不得进入后续任何 geometry completion 或 concrete coordinate。
3. **Direct coordinate / evidence-backed relation lock**：direct witness写direct；跨feature关系写Gate A支持的正式ledger relation。锁定后不得在全局坐标转换时重分类。
4. **Eligible derived**：只用已锁定source/target与明确relation唯一计算缺失target；禁止无relation的跨feature derived。
5. **Required HARD feature inventory**：列出所有改变实体的必需feature；不能可靠表达的项进入blocking `unresolved`，不得静默删除。
6. **Semantic draft assembly**：把上述内容写入现有drawing结构；所有target/link/between须解析到draft中真实canonical path，canonicalizer不猜path或semantic intent。
7. **Output**：完成first-write semantic check后，只写一次 `semantic-draft.json`。不得直接写 `drawing.json`，不得在失败后生成第二版 draft。

## 3. 视图、association 与坐标系

固定坐标系：

```json
{
  "origin": "part_center_xy_bottom_z0",
  "x_positive": "right",
  "y_positive": "declared side-view positive",
  "z_positive": "up",
  "unit": "mm"
}
```

XY 原点为零件整体外形中心，Z=0 为零件底面。标准正投影视图映射：

- Front：XZ 平面，normal=Y；
- Side：YZ 平面，normal=X；
- Top：XY 平面，normal=Z。

第一角/第三角投影只改变视图排布。左右侧视图只改变观察方向，不改变 normal=X。

- 先为每个view记录projected geometry与annotation endpoints，再用投影对齐、shared centerline、specification和leader/witness证据合并same-feature identity，最后绑定dimension endpoints。圆形end-view提供axis候选；隐藏线投影提供transverse center、axial range及其尺寸候选。
- 孔的 transverse coordinates 由轴唯一确定：`axis=X`→Y/Z、axis=Y→X/Z、axis=Z→X/Y。
- 锁定 axis/每个 transverse center 或宣告 unresolved 前，必须逐项核对该 identity 的全部正交视图记录；邻近、同值或axis相同不足以association。任一视图上绑定的center/spacing不得因另一视图显示为圆或隐藏线而丢失。
- start face 只能在 axis 锁定后解释，不得反向决定 axis；看见孔位所在的面也不能代替 orthographic axis evidence。start side证据不足时保持缺省/`null`并写blocking unresolved，不得猜值。
- same-feature association只合并identity；distinct-feature alignment/spacing须建立独立relation并保留evidence/`relation_refs`。
- slot/cut 分别记录 `width_axis` 与 `through_axis`；两条平行边只能识别 width_axis，不能单独决定 through_axis。
- center coordinate 与沿轴 start/end/range 分开。side 或 axial range 会改变实体而不能唯一确定时进入 blocking `unresolved`。

全局转换只序列化已经锁定 ownership 后得到的 concrete coordinate；不得重新解释 annotation、改变 measured quantity 或增加局部尺寸。`part_center_xy_bottom_z0` 下 X/Y 必须始终使用同一 centered frame：overall边界分别为 `[-length_x/2,+length_x/2]`、`[-width_y/2,+width_y/2]`，Z为 `[0,height_z]`；profile、center、edge relation不得在同一draft中混入 `0..extent` X/Y frame。

## 4. Physical endpoint ownership

每个annotation只有一个稳定source identity、associated feature/view、measured quantity和真实endpoint ownership；同值但endpoints不同的annotations保持独立，不得克隆改义。

dimension-bearing annotation参与derived/completion/global calculation前必须完成绑定并锁定ownership。未绑定尺寸不得作为裸 numeric operand 或 mental arithmetic 输入，也不得只留coordinate或伪装成direct `center_position`。

按 endpoints 使用唯一决策表：

| 物理 endpoints | ownership / representation |
|---|---|
| absolute/ordinate datum → centerline | direct center coordinate |
| overall min/max boundary → centerline | `edge_offset(value,axis,from,targets)` |
| intermediate surface → centerline | local measurement source；需要全局 target 时 derived 必须引用该 surface target 与该 source |
| centerline → centerline | `center_distance / center_spacing`，`between` 为两个真实scalar center paths |
| profile/body boundary → profile/body boundary | `profile_dimension` |
| slot 两侧 boundary → boundary | `slot_width` |

endpoint 是箭头/extension line 实际终止的 geometry，不是尺寸线途中经过的edge/surface。两端终止于两个feature centerlines时必须先写`center_spacing/center_distance`，邻近overall edge不得抢占endpoint改写为`edge_offset`。datum/overall boundary→centerline的direct witness锁定后，不得叠加plate、pad、step、thickness、neighboring dimension或inferred offset。

明确属于 `overall_dimensions` 的全局 boundary 使用：

- `X=[-length_x/2,+length_x/2]`
- `Y=[-width_y/2,+width_y/2]`
- `Z=[0,height_z]`
- `from=min`: `coordinate = min_edge + value`；`from=max`: `coordinate = max_edge - value`

局部 profile/body/step boundary 不得套 overall bbox，必须引用其实际 geometry endpoint。

一个overall edge→center annotation可用一个`edge_offset`覆盖多个target；这些 centers 不要求位于同一个 feature object。pattern/symmetry/spacing不得删除该ownership、改作group center/半距或换成数学等价的另一侧offset。

`edge_offset` relation 保存 `value / axis / from / targets`，自身提供 target coverage；`edge_offset` 不得作为 derived expression 的 numeric source。`center_distance / center_spacing` relation 本身不覆盖 endpoints；若派生其中一个 endpoint，expr 同时引用 known opposite endpoint target 和 relation source。

## 5. Formal relation 与 feature-local geometry

- distinct-feature relation必须有证据和稳定identity，并作为`source_ledger`中Gate A支持的semantic序列化；只写 `connected_to / notes / reason / evidence` 不构成 relation coverage。无正式relation禁止跨feature numeric derived。
- shared centerline由`alignment`表达；slot width只定义两侧边界距离，不得兼任position或edge offset。
- slot/slit 明确连接 circle/arc 时，用 `alignment` 保存共享中心坐标，并用 `upper_tangent` 或 `lower_tangent` 保存 nominal endpoint；tangent relation 必须携带真实 `center / diameter / tangent / links` paths。不得另造非正式 `connected` semantic。derived endpoint引用该正式 relation identity；这只描述 drawing semantic，不规定具有非零 width 的实体 cut realization。
- feature-local dimension只绑定endpoints所属feature。其它 feature 的 depth、spec、diameter、center、start/end 或 nominal size 不得成为当前 feature position 的自由 operand。
- coaxial members继承group axis/centerline，只保留自身diameter/spec/depth/side/range。
- slot/cut位置或中心距不得改作width/depth/bottom；termination只来自明确深度、剖视起止面或正式relation。

## 6. HARD / DERIVED / SOFT 与 required inventory

### 6.1 HARD

required HARD feature inventory包括：

- overall dimensions 与主体/profile；
- 明确表达的孔、槽、切口、台阶、壳体等 feature；
- feature 的位置、数量、直径/半径、axis；
- slot/cut 的 width_axis、through_axis；
- through/depth/termination，以及会改变实体的局部轮廓、圆角和倒角。

无法唯一表达的必需feature写blocking `unresolved(required_for_modeling=true)`；不得因provenance/representation麻烦而省略。

### 6.2 Eligible derived

derived仅用于无direct writer/relation coverage且可由已锁定证据唯一求得的target：

- 每项包含稳定 `id`、实际 `target`、declared `value`、可计算 `expr`；
- dimension-bearing number 必须通过 `source` 或已有 geometry `target` identity 进入 expr；不得把图纸尺寸脱离 provenance 后降级成裸 numeric `const`；
- `const` 只允许无量纲数学恒等系数或符号运算所需的纯数学常数，不得承载长度、角度、直径、半径、深度、间距或坐标；
- 跨 feature derived 必须引用实际参与 evidence-backed relation 的 source/target，并保存 `relation_refs`；
- target 已由 direct 或 relation coverage 给定时禁止再创建 derived writer。

已知中心加 distance/spacing 派生另一中心时，expr 必须引用 opposite endpoint target 与 relation source，而不是因缺少 direct dimension 进入 blocking unresolved。

需要像素比例、经验判断、任意符号、未绑定邻近值或有多解时，必须unresolved/conflict。

### 6.3 SOFT

不改变实体唯一性的材料、粗糙度、普通公差、制造说明等可进入 warning 或 `required_for_modeling=false`，不得改变 geometry。

### 6.4 Closure

`dimension_closure`只验证既有geometry，不创建source/writer、补coordinate、改变ownership或推导缺失geometry。状态仅为`closed / incomplete / conflict`；`closed`不能替代inventory、coverage、coordinate与conflict validation。

## 7. Pattern 与数量

- `N×`是feature总实例数，不因symmetry/mirror翻倍；pattern/symmetry/spacing只在ownership锁定后补全有明确关系的geometry。
- 无法可靠分类时保留有证据的`explicit_centers`；symmetry不自动产生实例或把edge offset改为半距。输出前核对count与centers/pattern counts，不一致进入conflict。

## 8. Semantic draft contract

`semantic-draft.json`必须在首次输出就使用当前drawing contract：`features`是带`id`的object array，`profile.segments`是segment array，`centerline`是直接包含横向scalar坐标的object，`explicit_centers`是numeric coordinate arrays。必需root为`overall_dimensions / coordinate_system / features / source_ledger / derived / unresolved / dimension_conflicts / dimension_closure`。

source entry必须有`id + semantic`；direct source用真实scalar `target`，relation source不得用`target`。直接semantic限定为`overall_dimension / profile_dimension / feature_count / diameter / radius / slot_width / depth / thickness / axis / center_position / position_dimension / thread_spec / feature_kind / side / through / pattern_dimension / feature_dimension`；relation semantic限定为`center_distance / center_spacing / edge_offset / symmetry / upper_tangent / lower_tangent / coincident / alignment`。旧`type`字段不是source semantic。

relation的machine shape是：

- `center_spacing/center_distance`: `id + semantic + value + between=[scalar center A, scalar center B]`；
- `edge_offset`: `id + semantic + value + axis + from(min|max) + targets=[scalar paths]`；
- `alignment/coincident`: `id + semantic + links=[至少两个相等numeric scalar paths]`；
- `upper_tangent/lower_tangent`: `id + semantic + center + diameter + tangent + links`，`links`必须包含前三个paths。

derived entry必须是`{"id":...,"target":<scalar path>,"value":<number>,"expr":<object>}`。`expr`只能递归使用`{"target":path}`、`{"source":id}`、纯数学`{"const":number}`或`{"op":"add|sub|mul|div|neg|abs","args":[...]}`；跨feature relation另列`relation_refs`。禁止string arithmetic。`dimension_closure`必须是`{"status":"closed|incomplete|conflict"}`，禁止单独字符串。


路径必须落到draft中已存在的scalar leaf：`feature:<id>.centerline.<axis>`、`feature:<id>.explicit_centers.<index>.<coordinate-index>`、`profile.segments.<index>.<field>`。禁止对象容器target、抽象`.center`及不存在的`top_z / z_local / z_to_top`。coordinate正确不能代替measured ownership；blocking unresolved不得与同一字段的猜测concrete value/writer并存。canonicalizer只修无损representation，不猜path/semantic，不补semantic内容。

## 9. First-write semantic check

首次且唯一一次落盘前只检查semantic truth：HARD inventory无静默遗漏；每个 dimension-bearing annotation 在 numeric use 前已有 identity、feature/view、endpoints 和 source/relation ownership；relation/derived有证据；coordinate与ownership一致；blocking ambiguity已写入unresolved。检查失败时仍写明unresolved并停止，不得生成第二版draft或直接写`drawing.json`。
