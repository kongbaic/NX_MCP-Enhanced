# Reader First-Pass Benchmark Prompt Template

> Operator-only template. For one frozen revision, only replace
> `{{EXPECTED_HEAD}}`, `{{RUN_ID}}`, and `{{OUTPUT_PATH}}`.
> All other text stays unchanged between runs.

~~~text
项目：C:\NX_MCP_FAST_113CDB15
分支：reader-evidence-resolver-v1
当前 HEAD：{{EXPECTED_HEAD}}

Reader first-pass stability benchmark
RUN_ID = {{RUN_ID}}

只做一次 Fresh Reader Capture，不做 NX 建模。

唯一允许的语义输入：
- 当前会话上传的原始工程图
- skills\nx-agent\SKILL.md
- skills\nx-agent\references\reader-runtime-contract.md
- skills\nx-agent\references\nx-drawing-rules.md

禁止读取任何历史 capture/evidence/draft/drawing/plan/report/PRT/STEP、
tests、fixtures、expected answer、benchmark/operator 文档、其它 Agent 结果，
也禁止搜索当前零件的历史答案。

严格按当前 HEAD 的 reader-runtime-contract.md 完成一次连续 first-pass。
不要额外建立第二套检查清单，不要进行开放式反复自审。

写盘前只执行一次生产：
ReaderCapture.model_validate(payload)

失败：不写文件，不修复，不进行第二次 interpretation，立即停止。
成功：将同一个已验证 payload 只写一次到：

{{OUTPUT_PATH}}

目标文件若已存在，立即停止，不覆盖。

写盘后立即冻结。禁止 check-capture、link-capture、Gate 0、Resolver、
Gate A、Planner、Runner、NX，也禁止回读 capture 后重新解释工程图。

最终只输出：
FIRST_PASS_FROZEN = YES
~~~
