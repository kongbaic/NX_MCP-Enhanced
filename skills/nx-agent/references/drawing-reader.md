# 二维工程图 Evidence Reader v1

本文件是 nx-agent 的工程图视觉读取 contract。它只负责观察与记录证据，不再负责最终几何求解、全局坐标计算、relation 语义选择或 Gate A 判定。

references/nx-drawing-rules.md 只提供视觉识别词典，不得覆盖本文件的 evidence identity、endpoint ownership、same-feature association 或 unresolved policy。

## 1. 目标与边界

把当前上传的二维机械工程图一次性转换为 drawing-evidence.json。

Reader 的唯一职责是回答：图上实际看到了什么？这些标注、投影、端点分别属于谁？

Reader 不负责根据这些证据计算最终全局坐标；该职责交给 deterministic compiler / resolver。

固定链路：

~~~text
工程图
↓
Evidence Reader
↓
drawing-evidence.json
↓
python -m nx_mcp.drawing_intelligence resolve
↓
semantic-draft.json
↓
runner.py canonicalize-drawing
↓
drawing.json / Gate A
~~~

Backend v1 不属于本文件职责。

## 2. Reader 允许做什么

Reader 可以：

- 识别标准正投影视图 identity：front / side / top；
- 为同一物理 feature 的不同投影建立稳定 feature identity；
- 识别 view-local projection shape：circle、concentric_circles、hidden_parallel、slot_edges、profile、other；
- 读取明确的尺寸文字、孔径、螺纹规格、数量、feature 类型；
- 绑定 dimension 的两个物理 endpoints；
- 标记 dimension measured axis；
- 当图纸明确表达方向时记录 center-to-center 的 direction；
- 记录 direct value evidence；
- 记录 required HARD target；
- 把证据不足或 identity 冲突写入 unresolved_evidence；
- 对已经机器可辨且无歧义的 relation 直接写 formal relation，但 v1 优先让 compiler 从 endpoints 编译 relation。

Reader 不可以：

- 根据 overall size 自己算 centered global coordinate；
- 把 overall max → center = 24 心算成 Y=-8；
- 把 bottom → center = 40 心算成 Z=40；
- 自己选择 edge_offset / center_spacing / center_distance，只因为看起来像；
- 从无符号中心距任意决定左右方向；
- 猜孔 axis、start side、depth、termination；
- 因为邻近、同值、同轴就合并两个不同 feature；
- 读取旧 plan / old drawing / old report / NX 输出帮助理解当前图纸；
- 直接写 semantic-draft.json；
- 直接写 drawing.json；
- 宣布 Gate A PASS。

## 3. 固定坐标语义

项目唯一全局坐标系仍是：

~~~json
{
  "origin": "part_center_xy_bottom_z0",
  "x_positive": "right",
  "y_positive": "declared side-view positive",
  "z_positive": "up",
  "unit": "mm"
}
~~~

标准视图到法向轴的确定性映射由 compiler 完成：

- Front → normal Y
- Side → normal X
- Top → normal Z

Reader 只写 view kind 与 projection；不得自己把 projection 手工改写成最终 axis，除非 axis 本身有独立直接证据。

## 4. drawing-evidence.json v1

顶层结构：

~~~json
{
  "schema_version": "1.0",
  "coordinate_system": "part_center_xy_bottom_z0",
  "overall_dimensions": {
    "length_x": 40,
    "width_y": 32,
    "height_z": 66
  },
  "views": [],
  "projections": [],
  "dimensions": [],
  "direct_values": [],
  "relations": [],
  "required_targets": [],
  "observations": [],
  "unresolved_evidence": []
}
~~~

### 4.1 views

示例：

~~~json
{
  "id": "V_FRONT",
  "kind": "front",
  "source_ids": ["OBS_VIEW_FRONT"]
}
~~~

kind 只允许 front / side / top。DETAIL / SECTION 可保留在 observations 作为辅助 evidence；v1 不把它们伪装成标准 view kind。

### 4.2 projections

同一 feature 在不同 view 中的投影使用同一个稳定 feature_id：

~~~json
{
  "id": "P_MAIN_FRONT",
  "feature_id": "F_MAIN_HOLE",
  "view_id": "V_FRONT",
  "shape": "circle",
  "source_ids": ["OBS_MAIN_CIRCLE"],
  "required_for_modeling": true
}
~~~

Reader 必须先完成 same-feature identity，再使用相同 feature_id。

如果无法确定两个 projection 是否属于同一 feature：

- 不得强行合并；
- 写 unresolved_evidence；
- 不得通过邻近、同值或 axis 猜测消除歧义。

### 4.3 direct_values

只放图纸直接支持的语义值。

~~~json
{
  "id": "S_MAIN_KIND",
  "target": "feature:F_MAIN_HOLE.type",
  "value": "through_hole",
  "source_ids": ["OBS_MAIN_HOLE"]
}
~~~

典型 direct values：

- feature kind；
- diameter / hole_diameter；
- thread spec；
- count；
- through；
- slot width；
- 明确 datum/ordinate 直接给出的 coordinate；
- 明确标注的 feature-local dimension。

禁止把通过 overall bbox 或 relation 计算得到的 coordinate 写成 direct value。

### 4.4 dimensions

dimension 只记录 identity、value、axis、两个 physical endpoints、可选 direction 和 source evidence。

示例：overall max Y boundary → mount hole center = 24

~~~json
{
  "id": "D_MOUNT_Y24",
  "value": 24,
  "axis": "Y",
  "endpoints": [
    {"role": "overall_max"},
    {
      "role": "feature_center",
      "target": "feature:F_MOUNT.centerline.y"
    }
  ],
  "source_ids": ["ANN_Y24"],
  "required_for_modeling": true
}
~~~

Reader 不得在这里写 Y=-8。compiler 会固定得到 overall Y max=+16，再从 max 减 24，最终 Y=-8。

示例：两个中心的明确中心距：

~~~json
{
  "id": "D_PAIR_SPACING",
  "value": 20,
  "axis": "X",
  "direction": 1,
  "endpoints": [
    {
      "role": "feature_center",
      "target": "feature:F_PAIR.explicit_centers.0.0"
    },
    {
      "role": "feature_center",
      "target": "feature:F_PAIR.explicit_centers.1.0"
    }
  ]
}
~~~

如果只有中心距数值但无法从图纸确定正负方向：省略 direction；Resolver 保留 ambiguity，Reader 禁止替它选方向。

### 4.5 required_targets

列出所有会改变最终实体、但需要 evidence/Resolver 闭合的 HARD target。

例如：

~~~json
[
  "feature:F_MAIN_HOLE.centerline.z",
  "feature:F_MOUNT.explicit_centers.0.1"
]
~~~

如果 required target 最终没有唯一 evidence-backed solution，Resolver 必须输出 blocking unresolved。

### 4.6 unresolved_evidence

任何影响实体且无法唯一确定的内容必须显式记录。

~~~json
{
  "id": "U_M6_START_SIDE",
  "target": "feature:F_M6.start_side",
  "reason": "drawing does not uniquely establish start side",
  "required_for_modeling": true,
  "evidence": ["OBS_M6_SECTION"]
}
~~~

禁止同时给该 target 一个猜测 concrete value。

## 5. Physical endpoint ownership

dimension-bearing annotation 在进入 dimensions 前必须先绑定真实 physical endpoints。

v1 endpoint role：overall_min、overall_max、feature_center。

Reader 必须按箭头、witness、extension line 实际终止 geometry 判断 endpoint，而不是 dimension line 经过哪里、附近有什么 feature、哪个数字看起来刚好能算通。

典型映射：

| 图纸物理 endpoints | Reader 输出 |
|---|---|
| overall min/max boundary ↔ overall max/min boundary | two overall endpoints |
| overall min/max boundary ↔ feature center | overall endpoint + feature_center |
| feature center ↔ feature center | two feature_center endpoints |

v1 尚不能确定性表示 intermediate local surface 时：不得降级成 overall boundary，不得自己计算，写 blocking unresolved。

## 6. same-feature association

Reader 仍然负责这是不是同一个物理 feature 的视觉 association，因为这是视觉 identity，不是数学计算。

允许依据：orthographic projection alignment、shared centerline、matching diameter/spec、leader/witness endpoints、DETAIL/SECTION 明确局部引用、圆形投影与其它正交投影的一致性。

单独以下任一项都不足以 association：图上靠得近、数字相同、axis 相同、都是孔、经验上应该是同一个。

发生冲突时写 unresolved_evidence，而不是挑一个。

## 7. HARD feature inventory

Reader 必须穷尽当前图纸中会改变实体的 feature：主体/profile、through hole、threaded hole、counterbore/countersink、slot/slit/cut、step/boss/pocket、明确圆角/倒角、pattern/repeated holes，以及其它当前 certified backend 可建模的 feature。

不能可靠表达但会改变实体时，仍必须保留 required_for_modeling=true 并进入 unresolved；不得静默省略。

## 8. Reader first-write 规则

Reader 对当前上传工程图只允许生成一次 drawing-evidence.json。它是 immutable first-pass visual evidence artifact。

Reader 写出前只检查：

- evidence identity 是否稳定；
- same-feature identity 是否自洽；
- dimension endpoints 是否已绑定；
- required HARD inventory 是否无静默遗漏；
- ambiguity 是否已显式 unresolved；
- 没有把 deterministic calculation 偷写成 visual direct fact。

写出后 Reader 阶段结束。

失败后禁止第二次看图补答案、根据 compiler/Resolver/Gate A 错误重新解释、编辑旧 evidence 让它过门、读取旧 plan 或 NX model 倒推图纸。

## 9. deterministic compile / resolve

Reader 写出 drawing-evidence.json 后，由固定程序执行：

~~~text
<runtime python> -m nx_mcp.drawing_intelligence resolve <drawing-evidence.json> <semantic-draft.json>
~~~

程序负责：view kind → axis、dimension endpoint → edge_offset / center_spacing / center_distance、centered X/Y bounds、Z bottom datum、alignment、tangent、unique coordinate propagation、conflict detection、required target closure、provenance-preserving semantic draft assembly。

程序不得读取图片。

如果不存在唯一解：exit != 0，semantic-draft.json 可以保留 blocking unresolved，然后 STOP；不得重新调用 Reader 修答案。

只有 exit=0、written=true、ok=true、dimension_closure=closed 才进入 canonicalizer / Gate A。

## 10. 关键 v1 不变量

以下历史问题必须由程序确定性处理：

1. overall Y=32，max-edge→center=24 → Y=-8；
2. bottom→Ø20 center=40 → Z=40，不允许 48；
3. front circle → axis Y；
4. side circle → axis X；
5. conflicting circular views → unresolved，不选 axis；
6. unsigned center spacing 无方向 → unresolved；
7. direct 与 relation 写入冲突 → conflict；
8. identical evidence input → identical logical resolution output。

## 11. 外部开源组件边界

v1 Reader / Resolver 不复制第三方项目实现。

后续输入 adapter 可以接 DXF vector parser、PDF vector/text parser、OCR、VLM。adapter 只能产生本合同中的 evidence，不得绕过 Resolver 直接写最终 geometry。
