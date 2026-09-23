# Reader First-Pass Stability Benchmark

## 1. Purpose

Measure whether independent visual Reader sessions produce the same logical
engineering-drawing semantics after deterministic Capture validation,
identity linking, Gate 0, compilation and resolution.

This benchmark measures Reader/front-end stability. It does not measure
Planner, Runner, Loader or NX stability.

Stability and correctness are separate gates. A Reader can be consistently
wrong; therefore stability PASS never substitutes for a source-drawing
correctness audit.

## 2. Benchmark revision freeze

Reader stability uses two separately recorded revisions.

### 2.1 Capture revision

Before starting a smoke or formal Reader batch, freeze and record:

- repository branch and capture HEAD;
- exact source-drawing bytes and SHA256;
- exact benchmark prompt template revision/hash from
  `docs/benchmarks/reader-first-pass-prompt-template.md`;
- exact allowed Reader document revisions;
- production `capture.py` revision;
- benchmark run count;
- output directory.

The only prompt substitutions allowed between independent runs are:

- RUN_ID;
- OUTPUT_PATH.

Do not change examples, wording, hints, expected values or troubleshooting
instructions between runs.

Any change to the source drawing, benchmark prompt, Reader-visible documents,
or production Capture schema creates a new **capture revision** and requires
fresh Reader sessions.

### 2.2 Normalizer revision

Record separately the exact Git HEAD used for deterministic:

- `check-capture`;
- identity linking;
- Gate 0;
- compiler/resolver/draft consumability checks;
- stability comparison.

A deterministic normalizer/comparator-only code change does **not** invalidate
already frozen captures when the capture revision is unchanged.

In that case:

- keep the original immutable captures;
- record the original capture HEAD;
- record the new normalizer HEAD;
- rerun only the deterministic post-capture stages;
- never edit or replace the capture files.

Do not mix captures from different capture revisions in one stability report.

## 3. Reader isolation

Each run starts in a fresh independent Agent/model session.

The Reader may receive only:

- the exact current source drawing;
- `skills/nx-agent/SKILL.md`;
- `skills/nx-agent/references/reader-runtime-contract.md`;
- `skills/nx-agent/references/nx-drawing-rules.md`;
- the generic benchmark prompt for the frozen revision.

The verbose development/audit references `drawing-reader.md` and
`reader-capture-contract.md` are intentionally excluded from normal benchmark
runtime so the benchmark matches the production fast Reader path.

The Reader must not receive or read:

- this benchmark/operator document;
- tests or fixtures;
- another run's capture/evidence;
- historical captures/evidence/drafts/drawings/plans/reports;
- PRT/STEP outputs;
- expected answers or regression sentinels;
- repository search results for the benchmark part/drawing;
- another Agent/Codex result.

The benchmark prompt and Reader-visible documents must not contain
source-specific expected dimensions, feature names, answers or historical
failure values.

## 4. First-pass definition

First-pass means one independent, continuous drawing-interpretation session.

Before the single capture write, the Reader may repeatedly inspect, zoom and
cross-check regions of the current source drawing. This is still one first
pass.

The Reader must not:

- read downstream output and reinterpret the drawing;
- read another run;
- repair after `check-capture`, `link-capture`, Resolver or Gate A feedback;
- write a second capture.

The first immutable artifact is `reader-capture.json`.

The capture artifact is authoritative for benchmark completion. Agent/chat final
text is not authoritative. In particular, absence of a final
`FIRST_PASS_FROZEN = YES` message does not by itself fail or invalidate a run.

Do not send a follow-up prompt merely to obtain a missing final acknowledgement.
If the target capture exists, continue with the external artifact checks below.

## 5. Capture production gate

Before its single write, the Reader contract requires in-memory production
schema validation with `ReaderCapture.model_validate(payload)`.

After the capture is written, the authoritative external gate is:

~~~text
python -m nx_mcp.drawing_intelligence check-capture <reader-capture.json>
~~~

A valid run requires:

~~~text
process exit code = 0
schema_valid = true
contract_valid = true
errors = []
~~~

Agent self-reported validation is informational only and must not be used as
the benchmark verdict.

If `check-capture` fails, that run is FAIL for the current benchmark
revision. Do not edit, rewrite, repair or replace that run in-place.

## 6. Deterministic link gate

For each capture that passes `check-capture`, run exactly once:

~~~text
python -m nx_mcp.drawing_intelligence link-capture \
  <reader-capture.json> \
  <linked-evidence.json>
~~~

A valid linked run requires:

~~~text
process exit code = 0
written = true
schema_valid = true
contract_valid = true
errors = []
~~~

Do not edit either the capture or linked evidence.

## 7. Two-run smoke

Every new benchmark revision first runs exactly two fresh independent Reader
sessions.

The smoke passes stability only when both runs pass Sections 5 and 6 and the
comparator returns:

~~~text
stable = true
run_count = 2
unique_fingerprints = 1
changed_sections = {}
value_drift = {}
unresolved_presence = {}
unresolved_semantic_drift = []
~~~

If either capture is invalid, link fails, or semantic drift exists, stop.
Do not run eight more sessions merely to confirm the same failure.

After a capture-revision fix, start a new smoke revision with two new Reader
sessions.

After a deterministic normalizer/comparator-only fix, replay the same immutable
captures under the new normalizer revision. Do not rerun Reader merely because
post-capture deterministic code changed.

## 8. Correctness audit

After a two-run smoke is stable, perform an independent correctness audit
against the original source drawing before starting the formal ten-run test.

The correctness audit checks that the stable linked semantics are actually
supported by the source drawing.

Expected answers used by the correctness auditor must remain hidden from the
Reader sessions and must never be copied into Reader-visible documents or the
benchmark prompt.

Do not feed correctness findings back into either frozen smoke capture.

A stable-but-wrong result fails the correctness gate.

## 9. Formal ten-run benchmark

Only after:

- two-run smoke stability PASS; and
- source correctness audit PASS

start ten new independent Reader sessions under the exact same frozen
benchmark revision.

The formal comparison command is:

~~~text
python -m nx_mcp.drawing_intelligence stability \
  linked/run-01.json \
  linked/run-02.json \
  ... \
  linked/run-10.json \
  --report report.json
~~~

Formal Reader stability PASS requires:

~~~text
stable = true
run_count = 10
unique_fingerprints = 1
changed_sections = {}
value_drift = {}
unresolved_presence = {}
unresolved_semantic_drift = []
~~~

Reader-local entity IDs, evidence IDs, source IDs, JSON ordering and free-text
observation wording do not need to match.

## 10. Unresolved semantics

`unresolved_presence` reports unresolved target presence that differs across
runs. The comparator intentionally removes a target from this diagnostic when
it is unresolved in every run.

`unresolved_semantic_drift` compares structured Reader/linker unresolved
semantics, including targetless ambiguity.

Therefore:

- a consistent unresolved condition can be stable;
- a run-dependent unresolved condition is stability drift;
- stable unresolved does not mean the drawing is closed or modelable.

Resolver/Gate A remain responsible for closure after the Reader stability
benchmark.

## 11. Exit-code interpretation

`check-capture`:

- exit 0 = schema + current Capture contract valid;
- exit 1 = invalid capture/input/runtime error.

`link-capture`:

- exit 0 = deterministic link/Gate0 output written;
- exit 1 = input/link/Gate0/runtime error.

`stability`:

- exit 0 = comparator completed and all fingerprints are identical;
- exit 2 = comparator completed and true semantic drift exists;
- exit 1 = comparator/input/runtime error.

Never label exit 1 as semantic drift.

## 12. Timing

Reader latency is measured only by an external wall clock controlled by the
operator.

Agent self-reported elapsed time is not authoritative.

Use the same timing boundary for every run in a benchmark revision. Recommended
boundary:

- start: benchmark prompt submitted to the fresh Reader session;
- stop: first immutable capture write completes / the Reader task ends without
  a valid capture.

A delayed, missing, truncated or suppressed Agent final response does not extend
the Reader timing boundary after the immutable capture has already been written.

Do not compare latency across different benchmark revisions as if conditions
were identical.

For smoke/recovery runs, use an operator-enforced wall-clock ceiling of
20 minutes per Reader capture unless the frozen revision specifies a stricter
limit. If no immutable capture has been written by that ceiling, abort the run
and record `reader_runtime_timeout`. Do not wait indefinitely for a stability
run. This ceiling is only a runaway guard; it is not the final performance
acceptance target.

## 13. No replacement runs

A run that fails schema/contract, produces no capture, rewrites its capture,
reads forbidden history, requires a follow-up prompt to reinterpret the
drawing, or otherwise violates isolation remains a failed run.

A missing Agent final acknowledgement alone is not a failed run. Do not replace
or rerun a valid immutable capture merely because the chat UI did not display
the expected final line.

Do not discard it and insert a replacement while claiming the original
benchmark run count.

For a smoke test, a defect in the capture revision requires restarting both
Reader runs. A defect only in deterministic post-capture normalization permits
replay of the same immutable captures under a new normalizer revision.

For a formal ten-run benchmark, the same rule applies: capture/input defects
invalidate the Reader batch; deterministic normalizer/comparator defects do
not invalidate immutable captures and may be corrected by replay.

## 14. Backend boundary

Reader benchmark failures must not be hidden by changing:

- Planner;
- Runner;
- Loader;
- NX core;
- Gate A acceptance strictness.

Fix only the Reader Capture contract/extraction, deterministic front-end
normalization/linking/comparison, or preserve ambiguity as unresolved.

## 15. What this benchmark does not test

It does not test:

- full drawing closure;
- Planner quality;
- Runner stability;
- Loader/NX behavior;
- PRT/STEP export;
- controlled repair;
- post-NX geometry validation.

Those are separate downstream gates after Reader stability and correctness.
