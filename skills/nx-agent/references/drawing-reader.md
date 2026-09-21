# 二维工程图读取模块

本文件是 `nx-agent` 唯一的工程图语义决策 contract。`references/nx-drawing-rules.md` 只提供视觉识别词典，不得覆盖本文件的 association、ownership、relation 或 derived policy。

## 1. 目标与边界

把二维机械工程图一次性转换为三维 CAD 建模所需的 semantic draft，只提取会改变最终实体的内容。

- 清晰标注直接采信；禁止像素、轮廓比例或图纸比例反推尺寸。
- 多视图中同一 feature 的重复表达合并，不重复计数。
- DETAIL / SECTION 是局部 geometry 的高优先级证据。
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

- 圆形end-view提供axis候选；隐藏线投影提供transverse center、axial range及绑定dimension候选。
- 孔的 transverse coordinates 由轴唯一确定：`axis=X`→Y/Z、axis=Y→X/Z、axis=Z→X/Y。
- 跨视图候选只按projection alignment、shared centerline、specification和leader/witness endpoints判断same-feature/coaxial identity；邻近、同值或axis相同不足以association。
- 每个候选先建立 view→projection geometry→annotation endpoints 的记录，再合并 same-feature identity。锁定 axis/每个 transverse center 或宣告 unresolved 前，必须逐项核对该 identity 的全部正交视图记录；任一视图上绑定的 center/spacing annotation 不得因其 feature 在另一视图显示为圆或隐藏线而丢失。
- start face 只能在 axis 锁定后解释，不得反向决定 axis；看见孔位所在的面也不能代替 orthographic axis evidence。
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
| centerline → centerline | `center_distance / center_spacing`，`between` 为两个真实 center paths |
| profile/body boundary → profile/body boundary | `profile_dimension` |
| slot 两侧 boundary → boundary | `slot_width` |

endpoint 是箭头/extension line 实际终止的 geometry，不是 dimension line、extension line 或视线途中经过的 geometry。只有 witness endpoint 确实终止在 intermediate surface，尺寸才是 local measurement。datum/overall boundary→centerline 的 direct witness 优先于所有 arithmetic：一旦锁定，不得因标注路径经过 plate、pad、step 或 thickness 而改写成 local measurement，也不得叠加 neighboring feature dimension 或 inferred offset。

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

`dimension_closure` 只验证已经建立的 geometry：

- 不创建 source；
- 不创建 writer；
- 不补 concrete coordinate；
- 不改变 endpoint ownership；
- 不推导缺失 geometry。

状态只允许 `closed / incomplete / conflict`。`closed` 字样不能替代 required inventory、coverage、coordinate 和 conflict validation。

## 7. Pattern 与数量

- `N×` 是 feature 总实例数，不因 symmetry/mirror 再次翻倍。
- pattern/symmetry/spacing 只能在 endpoint ownership 已锁定后补全关系明确的 geometry。
- rectangular/circular pattern 无法可靠分类时保留证据支持的 `explicit_centers`，不得强行分类。
- symmetry 只约束中点或镜像关系，不自动产生实例或把 edge offset 变成半距。
- 输出前核对 count 与 `explicit_centers.length` 或 pattern counts；不一致进入 conflict。

## 8. Semantic draft contract

`semantic-draft.json`使用现有drawing结构，携带`overall_dimensions / coordinate_system / features / source_ledger / derived / unresolved / dimension_conflicts / dimension_closure`与稳定 feature、annotation、source、relation 与 unresolved identity。

- feature 必须表达真实 type、axis/center/profile、尺寸、数量和termination；source/relation必须保留 measured quantity与physical endpoint ownership，coordinate 正确不能替代该 ownership。
- dimension-bearing数值只能通过已识别的source、relation或geometry target参与derived；不得降级为free numeric const。
- blocking unresolved不得同时带猜测的concrete value；semantic缺失不得用schema convenience掩盖。
- Reader必须按draft中真实字段发出可解析路径：feature字段使用`feature:<id>.<field>`；单孔中心使用`feature:<id>.centerline.<axis>`；重复孔坐标使用`feature:<id>.explicit_centers.<index>.<coordinate-index>`；profile使用`profile.segments.<index>.<field>`。不得发出抽象的`feature_id.center`，也不得引用对象中不存在的`top_z / z_local / z_to_top`等字段。
- `center_spacing/center_distance`使用`value + between=[两个真实center coordinate paths]`；`edge_offset`使用`value + axis + from + targets`；`alignment/coincident`使用`links`；`upper_tangent/lower_tangent`使用`center + diameter + tangent + links`。这些正式relation均位于`source_ledger`，不能只存在于free text或另一个未验证容器。
- canonicalizer白名单只负责object/list、numeric-string、`range_z.from/to`及可证明的一对一path形状归一化；Reader仍负责选择真实字段和正确semantic，不得把歧义path交给canonicalizer猜测，也不得据Gate A错误试写semantic token。
- canonicalizer只修representation，不补feature、ownership、relation、derived或unresolved。

## 9. First-write semantic check

首次且唯一一次落盘前只检查semantic truth：HARD inventory无静默遗漏；每个 dimension-bearing annotation 在 numeric use 前已有 identity、feature/view、endpoints 和 source/relation ownership；relation/derived有证据；coordinate与ownership一致；blocking ambiguity已写入unresolved。检查失败时仍写明unresolved并停止，不得生成第二版draft或直接写`drawing.json`。

快速视觉识别词典：`references/nx-drawing-rules.md`。
