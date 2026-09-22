# Reader First-Pass Benchmark Prompt Template

> Operator-only template. Do not add source-specific expected values, feature
> names, dimensions, historical failures or correctness hints.
>
> For one frozen benchmark revision, only replace:
>
> - `{{EXPECTED_HEAD}}`
> - `{{RUN_ID}}`
> - `{{OUTPUT_PATH}}`
>
> All other text must remain byte-for-byte unchanged between independent runs.

~~~text
项目：

C:\NX_MCP_FAST_113CDB15

分支：

reader-evidence-resolver-v1

当前 HEAD 必须为：

{{EXPECTED_HEAD}}


这是 Reader Capture first-pass stability benchmark。

RUN_ID = {{RUN_ID}}

本轮不是 NX 建模任务。
本轮只测试 Reader first-pass capture。


【唯一允许的语义输入】

1. 当前会话上传的原始工程图。
2. 以下四份当前 HEAD 下的规则文件：

skills\nx-agent\SKILL.md
skills\nx-agent\references\drawing-reader.md
skills\nx-agent\references\reader-capture-contract.md
skills\nx-agent\references\nx-drawing-rules.md


【禁止读取】

除上述四份规则文件和当前原始工程图外，不得读取任何其它可能影响工程图解释的内容，包括但不限于：

- reader-stability-benchmark.md
- 任何 benchmark/operator 文档或 prompt 历史版本
- tests
- fixtures
- 旧 reader-capture.json
- 旧 drawing-evidence.json
- semantic-draft.json
- drawing.json
- frozen/executable plan
- Runner report
- run_history.json
- PRT / STEP
- expected answer
- regression sentinel
- 其它 Agent / Codex 会话结果
- 仓库或 workspace 中当前工程图/零件的历史结果

禁止在仓库、workspace 或历史聊天中搜索当前工程图/零件的答案。


【唯一任务】

只执行：

当前原始工程图
→ Reader Capture
→ reader-capture.json

严格遵守当前 HEAD 的：

drawing-reader.md
reader-capture-contract.md
nx-drawing-rules.md

不要自行增加第二套字段、推理规则或兼容规则。


【First-pass 定义】

本轮是一个独立、连续的 drawing interpretation session。

在唯一一次写盘之前，可以对当前原始工程图进行必要的反复查看、放大、分区核对和标注追踪。

这不算第二次 interpretation。

禁止读取任何 downstream 或历史结果以后重新解释工程图。


【写盘前生产 schema 门禁】

在内存中完成 payload 后，必须使用当前项目的生产模型执行：

ReaderCapture.model_validate(payload)

仅 JSON parse、键数量检查、文字扫描或自定义 validator 不能代替生产 schema。

如果生产 schema 校验失败：

- 不写 reader-capture.json；
- 不第二次看图修复；
- 不生成第二版 payload；
- 立即停止本轮。


【唯一输出】

只允许写一次：

{{OUTPUT_PATH}}

如果目标文件在本轮开始前已经存在：

立即停止，不覆盖、不修改。

写出成功后，reader-capture.json 立即冻结。


【禁止 downstream】

本轮禁止调用：

- check-capture
- link-capture
- Gate 0
- Compiler
- Resolver
- Gate A
- canonicalizer
- Planner
- Runner
- NX

禁止生成任何 downstream artifact。


【写盘后】

写盘后：

- 不回读 capture 修答案；
- 不第二次查看工程图；
- 不修改或重写 capture；
- 不运行 downstream；
- 不做 correctness 自评；
- 不输出工程图答案解释。

最终只输出一行：

FIRST_PASS_FROZEN = YES
~~~
