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

1. **Annotation / same-feature projection association**：保存 view-local evidence，只确认投影属于同一 feature；axis/centerline 仍是待锁定候选。hole/thread/counterbore 必须穷尽整图中的 same-feature orthographic candidates 后才能输出 axis/center、宣告 unresolved 或解释 start face。association 本身不建立不同 feature 之间的数值关系，也不授权跨 feature derived。
2. **Physical endpoint ownership**：沿 witness/leader/arrow、centerline 与 feature boundary，为每个 dimension-bearing annotation 建立稳定 annotation/source identity、feature/view identity、physical endpoints 和唯一 measured quantity。绑定前，annotation 的数值不得进入后续任何 geometry completion 或 concrete coordinate。
3. **Direct coordinate / evidence-backed relation lock**：直接证据写 direct；alignment、connected、tangent、coincident、spacing、symmetry 等不同 feature 关系必须单独建立并保存 evidence。ownership 和 relation 锁定后不得在全局坐标转换时重分类。
4. **Eligible derived**：只用已锁定的 source/target 与明确 relation 唯一计算缺失 target。没有 evidence-backed relation 禁止跨 feature derived。
5. **Required HARD feature inventory**：根据工程图列出总体、主体/profile、明确孔槽及其它会改变实体的必需 feature。无法可靠表达的必需项进入 blocking `unresolved`，不得从 inventory 或输出中静默删除。
6. **Semantic draft assembly**：把已锁定的 feature、ownership、relation、derived、unresolved 与 HARD inventory 写入现有 drawing 结构；representation spelling 交给 deterministic canonicalizer，不得为适配 schema 改写 semantic truth。
7. **Output**：完成first-write semantic check后，只写一次 `semantic-draft.json`。不得直接写 `drawing.json`，不得在失败后生成第二版 draft。

## 3. 视图、association 与坐标系

固定坐标系：

```json
{
  "origin": "part_center_xy_bottom_z0",
  "x_positive": "right",
  "y_positive": "up",
  "z_positive": "up",
  "unit": "mm"
}
```

XY 原点为零件整体外形中心，Z=0 为零件底面。标准正投影视图映射：

- Front：XZ 平面，normal=Y；
- Side：YZ 平面，normal=X；
- Top：XY 平面，normal=Z。

第一角/第三角投影只改变视图排布。左右侧视图只改变观察方向，不改变 normal=X。

- hole/thread/counterbore 的圆形 end-view 提供 axis 候选；隐藏线投影提供 transverse center、axial range 及绑定 dimension 的候选证据。
- 孔的 transverse coordinates 由轴唯一确定：`axis=X`→Y/Z、axis=Y→X/Z、axis=Z→X/Y。
- `M-series thread / through hole / counterbore` 等跨视图候选只按 projection alignment、shared centerline、feature identity、specification 和 leader/witness endpoints 判断是否为同一 feature/coaxial group；邻近、同值或 axis 相同不足以 association。
- 锁定 axis/center 或宣告 unresolved 前必须核对全部正交视图候选。start face 只能在 axis 锁定后解释，不得反向决定 axis。
- thread projection 必须先按 projection alignment 与 identity evidence 完成 same-feature association，不能靠邻近关系归组。
- same-feature association 只合并 identity；axis 与 shared transverse centerline 必须由完整候选证据锁定。distinct-feature alignment/connected/spacing 必须建立独立 relation，并保留 evidence / `relation_refs`。
- slot/cut 分别记录 `width_axis` 与 `through_axis`；两条平行边只能识别 width_axis，不能单独决定 through_axis。
- center coordinate 与沿轴 start/end/range 分开。side 或 axial range 会改变实体而不能唯一确定时进入 blocking `unresolved`。

全局转换只序列化已经锁定 ownership 后得到的 concrete coordinate；不得重新解释 annotation、改变 measured quantity 或增加局部尺寸。

## 4. Physical endpoint ownership

一个物理 annotation 只有一个稳定 annotation/source identity、一个 associated feature/view identity、一个 measured quantity 和一组真实 endpoint ownership。相同数值但 endpoints 不同的 annotations 保持独立 source；不得克隆 source 后赋予另一种物理含义。

dimension-bearing annotation 参与 derived、spacing/pattern/projection completion、global calculation 或 concrete assignment 前，必须完成上述绑定并按第3步锁定 source/relation ownership。未绑定尺寸不得作为裸 numeric operand 或 mental arithmetic 输入，不得只保留 coordinate 或在 canonical 阶段伪装成 direct `center_position`。

按 endpoints 使用唯一决策表：

| 物理 endpoints | ownership / representation |
|---|---|
| absolute/ordinate datum → centerline | direct center coordinate |
| overall min/max boundary → centerline | `edge_offset(value,axis,from,targets)` |
| intermediate surface → centerline | local measurement source；需要全局 target 时 derived 必须引用该 surface target 与该 source |
| centerline → centerline | `center_distance / center_spacing`，`between` 为两个真实 center paths |
| profile/body boundary → profile/body boundary | `profile_dimension` |
| slot 两侧 boundary → boundary | `slot_width` |

只有 witness endpoint 确实落在 intermediate surface，尺寸才是 local measurement。overall datum/boundary→centerline ownership 一旦锁定，不得因投影路径经过 plate、pad、step 或 thickness 而改写成 local measurement，也不得叠加 neighboring feature dimension 或 inferred offset。

`profile_dimension` 只用于两个 endpoints 都属于 profile/body boundary 的 annotation。

明确属于 `overall_dimensions` 的全局 boundary 使用：

- `X=[-length_x/2,+length_x/2]`
- `Y=[-width_y/2,+width_y/2]`
- `Z=[0,height_z]`
- `from=min`: `coordinate = min_edge + value`；`from=max`: `coordinate = max_edge - value`

局部 profile/body/step boundary 不得套 overall bbox，必须引用其实际 geometry endpoint。

一个 overall edge→center annotation 可用一个 `edge_offset` relation 覆盖多个实际 target paths；这些 centers 不要求位于同一个 feature object。ownership 必须先于 pattern/symmetry/spacing completion 锁定；后者不得删除真实 edge dimension、改写成 group center/半距，或换成数学等价但 ownership 不同的另一侧 offset。

`edge_offset` relation 保存 `value / axis / from / targets`，自身提供 target coverage；`edge_offset` 不得作为 derived expression 的 numeric source。`center_distance / center_spacing` relation 本身不覆盖 endpoints；若派生其中一个 endpoint，expr 同时引用 known opposite endpoint target 和 relation source。

## 5. Relation 与 feature-local geometry

- distinct-feature `alignment / connected / tangent / coincident / spacing / symmetry` 必须有图纸证据和稳定 relation identity。没有 relation 时禁止跨 feature numeric derived。
- slot/slit 与 circle/hole 由 shared centerline、对称边界或明确连通表达共线时，alignment relation 可让 slot center 继承 circle center。slot width annotation 只定义两侧边界距离，不得兼任 position 或 edge offset。
- slot/slit 明确连接 circle/arc 时，保存 connected feature identity、relation evidence 与 nominal centerline endpoint。endpoint 可引用 circle center 与 radius/diameter source 求得，符号由连接侧证据决定，并保存 `relation_refs`。这只描述 drawing semantic，不规定具有非零 width 的实体 cut realization。
- feature-local dimension 只绑定其 endpoints 所属 feature。其它 feature 的 depth、spec、diameter、center、start/end 或 nominal size 不得成为当前 feature position 的自由 operand。
- coaxial group 保存共享 axis/centerline，members 继承共享 geometry，只保留自己的 diameter/spec/depth/side/range。
- 对 slot/cut，位置或中心距不得改作 width/depth/bottom。depth/termination 只来自明确深度语义、剖视起止面或 evidence-backed termination relation。

## 6. HARD / DERIVED / SOFT 与 required inventory

### 6.1 HARD

先从工程图建立 required HARD feature inventory，包括：

- overall dimensions 与主体/profile；
- 明确表达的孔、槽、切口、台阶、壳体等 feature；
- feature 的位置、数量、直径/半径、axis；
- slot/cut 的 width_axis、through_axis；
- through/depth/termination，以及会改变实体的局部轮廓、圆角和倒角。

主体/profile 或明确 feature 无法唯一表达时，写 blocking `unresolved(required_for_modeling=true)`；不得因为 provenance 或 representation 麻烦而省略 feature。required inventory 必须在 semantic draft 落盘前完成。

### 6.2 Eligible derived

derived 只在 target 没有 direct writer 或 relation coverage，且可由已锁定证据唯一求得时使用：

- 每项包含稳定 `id`、实际 `target`、declared `value`、可计算 `expr`；
- dimension-bearing number 必须通过 `source` 或已有 geometry `target` identity 进入 expr；不得把图纸尺寸脱离 provenance 后降级成裸 numeric `const`；
- `const` 只允许无量纲数学恒等系数或符号运算所需的纯数学常数，不得承载长度、角度、直径、半径、深度、间距或坐标；
- 跨 feature derived 必须引用实际参与 evidence-backed relation 的 source/target，并保存 `relation_refs`；
- target 已由 direct 或 relation coverage 给定时禁止再创建 derived writer。

已知中心加 distance/spacing 派生另一中心时，expr 必须引用 opposite endpoint target 与 relation source，而不是因缺少 direct dimension 进入 blocking unresolved。

需要像素比例、经验判断、任意正负号、未绑定邻近数值，或存在多个合理解释时，不得伪装成 derived，必须 unresolved/conflict。

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

`semantic-draft.json` 继续使用现有 drawing 结构，不创建第二套 schema。它必须携带 `overall_dimensions / coordinate_system / features / source_ledger / derived / unresolved / dimension_conflicts / dimension_closure`，并保留稳定 feature、annotation、source、relation 与 unresolved identity。

- feature 必须表达真实 type、axis/center/profile、尺寸、数量和termination；source/relation必须保留 measured quantity与physical endpoint ownership，coordinate 正确不能替代该 ownership。
- dimension-bearing数值只能通过已识别的source、relation或geometry target参与derived；不得降级为free numeric const。
- blocking unresolved不得同时带猜测的concrete value；semantic缺失不得用schema convenience掩盖。
- semantic draft可使用canonicalizer白名单能够无损识别的pre-canonical representation；Reader不承担path prefix、endpoint field spelling、object/list或numeric-string repair，也不得据Gate A错误试写semantic token。
- canonicalizer只修representation，不补feature、ownership、relation、derived或unresolved。

## 9. First-write semantic check

首次且唯一一次落盘前只检查semantic truth：HARD inventory无静默遗漏；每个 dimension-bearing annotation 在 numeric use 前已有 identity、feature/view、endpoints 和 source/relation ownership；relation/derived有证据；coordinate与ownership一致；blocking ambiguity已写入unresolved。检查失败时仍写明unresolved并停止，不得生成第二版draft或直接写`drawing.json`。

快速视觉识别词典：`references/nx-drawing-rules.md`。
