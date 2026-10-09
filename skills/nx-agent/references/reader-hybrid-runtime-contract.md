# Hybrid Raster Reader Runtime Contract

This is the normal runtime contract for raster Mode B drawing interpretation.
Read this file plus `nx-drawing-rules.md` on the raster path. The full
`reader-runtime-contract.md` is required only for explicit non-raster/no-raster
fallback or development/audit; do not load it on the normal Hybrid path.
`drawing-reader.md` and `reader-capture-contract.md` are development/audit
references and are not normal runtime input.

## 1. Mission

For a current request with an explicit runtime-local raster path, normal production
Mode B does **not** run the full free-form semantic Reader first. The sole raster
front-end entry is:

~~~text
python_exe -m nx_mcp.drawing_intelligence run-hybrid-frontend <current-raster-path> <fresh-hybrid-run-directory>
~~~

That coordinator owns deterministic Reader input preparation, production Whole +
Wide-Local Hybrid OCR, and the structural query plan. It intentionally stops at
`phase=awaiting_structural_context`. Current production still uses the Agent for unresolved structural image
semantics; this is a transitional architecture debt, not a coordinator-only
Reader. The deterministic Reader may certify strictly evidenced text-only
reference regions with `deterministic_non_geometric_reference=true`. For these
queries the answer template already contains the only allowed unresolved code
`non_geometric_reference_region`. The Agent must preserve such entries
unchanged, must not open the image on account of that query, and must never
use missing geometry detections alone as proof of a reference region.
The deterministic Reader may also extract an explicit OCR view caption
(FRONT/SIDE/TOP VIEW, or its unambiguous Chinese counterpart) only when its
full text bbox belongs to exactly one geometry-bearing region. The result is
`deterministic_view_kind` plus `deterministic_view_label_source_index`,
copied into the answer template and enforced by the structural assembler.
Agent must preserve this `view_kind` without reclassification. A caption
is NOT evidence for overall dimensions, full-part rotation, or endpoint
ownership; any ambiguity leaves `deterministic_view_kind=null`.
Only the remaining visual queries require a bounded image read: inspect each
distinct image_path referenced by those remaining queries once. Multiple
queries may intentionally share one deterministic full-drawing structural overview;
when they do, open that shared image once and answer each query independently by its
`query_id` / `region_id`. Production query images prefer a deterministic
full-drawing context image with target regions boxed and labeled; classify each boxed
region's orthographic view, not the deterministic region as an assumed standalone
view. The box is only a region-to-view locator, not an annotation-reading
boundary. An explicit overall dimension anywhere in that query image may be reported
when it unambiguously belongs to the boxed region's same orthographic view and spans
that view's complete visible part/profile extent, even when its dimension line or text
is outside the box. Never borrow an overall dimension from another view; ambiguous
ownership stays unresolved. Normal Fresh Hybrid production writes ONLY
`structural-visual-decisions-v1`, not legacy full answers; Reader supplies all
evidence labels when composing canonical structural answers. Never put `evidence`
inside a compact decision. A resolved rotational decision must follow exactly
one permitted shape specified below, with no extra keys. Missing rotation is not
equivalent to `not_established`: use `rotational_symmetry:null` and a genuine
unresolved reason, and fail closed when evidence is insufficient.
Use `established` only when the drawing explicitly and uniquely establishes
whole-part revolution about one visible engineering axis. A printed X/Y/Z axis name
is not required. Two visual bases are allowed.

(1) Centerline basis: a longitudinal orthographic or axial/longitudinal section has an
explicit whole-part centerline, and the principal stepped/cylindrical body stages are
represented by paired opposite coaxial profile boundaries/shoulders about that
centerline.

(2) Centerline-omitted axial-section basis: the query is clearly an axial/diametral
section by section/hatching/cut semantics, the principal material/profile stages occur
as paired opposite coaxial boundaries/shoulders about one unique bilateral section
symmetry axis, and that unique axis direction is sufficient to establish the revolution
axis even though no centerline is drawn. This basis is unavailable for an ordinary
non-section mirror-symmetric profile. A solid continuous object/profile boundary is
never a centerline.

The Agent must not report X/Y/Z for rotational symmetry. For centerline basis it
reports only `centerline_direction=horizontal|vertical` when an explicit centerline is
actually drawn. For centerline-omitted axial-section symmetry the Agent reports no
direction at all. The query must carry a non-null
`deterministic_profile_symmetry_axis=horizontal|vertical` produced by Reader prep's
multi-threshold bilateral raster-topology classifier; that classifier never converts
pixels into engineering dimensions or coordinates. If the deterministic hint is absent,
the axial-section answer must remain unresolved. When the query also reports
`deterministic_profile_symmetry_overlay=blue_dashed_topology_axis`, the listed
structural-context image contains a blue dashed `TOPOLOGY SYM AXIS` visual aid at that
deterministic mirror axis. This overlay is not an original drawing centerline and may
never be used as `basis=centerline` or as proof of revolution by itself. Use it only
to stabilize the visual check that principal profile boundaries/shoulders occur in
paired opposite form around the deterministic candidate axis. If axial/diametral
section semantics are visually established and those principal profile stages are
paired around the overlay, absence of an original centerline alone is not a reason to
defer rotational symmetry; report `basis=axial_section_symmetry`. Ordinary
non-section mirror symmetry still remains insufficient. The assembler maps the deterministic
visual direction through the resolved `view_axis_map`: front horizontal=>X / vertical=>Z;
side horizontal=>Y / vertical=>Z; top horizontal=>X / vertical=>Y. The section-symmetry basis is visual drafting topology,
not pixel measurement: do not compare pixel distances or convert visual spacing into
engineering values. Mirror symmetry alone, a centerline without paired coaxial
revolved-profile evidence, visual resemblance, solid-profile-line-as-centerline
interpretation, or parameter-name guessing is insufficient. `rotational_symmetry_not_visible_in_region` is the only region-local deferred rotational unresolved code. Use it only when the current query region contains labels/annotations or partial content without enough part geometry to judge rotation; set `rotational_symmetry:null`. It does not mean `not_established`, does not create a rotational fact, and does not by itself satisfy global closure. The assembler may defer only this code across regions; any other unresolved remains terminal, and if no other region establishes rotation while a transverse overall is missing, global closure still fails. `not_established` is not
an uncertainty fallback: use it only when the query positively shows that whole-part
rotational symmetry does not hold. If positive establishment evidence and positive
counterevidence are both absent or ambiguous, keep `rotational_symmetry:null`, record
unresolved, and fail closed.
The Agent must never synthesize the missing overall extent.
Deterministic closure is fixed as rotation X => Y=Z, rotation Y => X=Z, rotation Z =>
X=Y, and the finalizer must preserve derivation provenance. Local dimensions must never be promoted to `overall_dimension_facts`.
An overall fact requires an explicit dimension spanning the complete visible part/profile
extent on that view axis. Chained/local lengths, hole-center spacing, center-to-edge
dimensions, radii, diameters, angles, and dimensions that cover only a local profile
segment remain local even when they are the largest visible numbers. If no explicit
overall dimension is shown for an allowed axis, omit that fact and keep it unresolved;
never invent it to satisfy the Adapter, derive it arithmetically, or estimate it from
pixels. Do not answer feature inventory, cross-view identity, local feature values,
dimension endpoint ownership, start side, termination, or pixel-derived coordinates.

Production now prefers compact, evidence-free visual decisions:
write exactly one `structural-visual-decisions.json` with schema
`structural-visual-decisions-v1` and one `decisions` item per remaining
non-reference query. Items report only view_kind when not already proven,
direct overall_dimension_facts as {axis,value}, rotational_symmetry
with EXACTLY ONE evidence-backed shape:
`{"status":"established","basis":"centerline","centerline_direction":"vertical"}`
(or actual visible horizontal direction) for a drawn, whole-part centerline;
`{"status":"established","basis":"axial_section_symmetry"}` for a uniquely
supported axial/diametral section (NO `centerline_direction` key, not even
a guessed orientation); or `{"status":"not_established"}` only for explicit
counterevidence (NO `basis` or `centerline_direction`). If uncertain, supply
`rotational_symmetry:null` and a real unresolved reason. These alternatives
are mutually exclusive. Never use the orientation of the drawing or the
blue dashed topology overlay as a substitute for a drawn centerline. Do a
single in-memory shape/visual-evidence check BEFORE writing the one-shot
`structural-visual-decisions.json`; never edit/resubmit after a terminal
resume failure. Other unresolved reasons and only pending
labeled_dimension_decisions are supplied without evidence or OCR value. For each unseeded labeled target, `resolved` requires BOTH an evidence-backed
`visual_direction` (`horizontal` or `vertical`) and `relation`
(`overall_extent`, `overall_min_to_profile_transition`,
`overall_max_to_profile_transition`, or `between_profile_boundaries`).
A dimension label such as C2=28 alone cannot prove arrow direction or
endpoint ownership. When either is uncertain, use
`{"target_id":"...","status":"unresolved","reason":"..."}` with a genuine
nonempty reason and NO semantic fields; this may block Gate A and must never
be auto-filled, interpreted as successful resolution, or repaired after a
terminal resume. Do not echo Reader-seeded targets or numeric OCR values.
`resolved` must not include `reason`; `overall_extent` cannot include
local profile transition metadata. Check these mutually exclusive forms
before the one and only Fresh visual decision file is written.
The Reader
automatically composes the strict canonical `structural-context-answers-v1`
in the same single resume invocation. It restores all fixed evidence,
machine-owned OCR view and seeded topology decisions; omission of any
pending region/target remains an error, not a guess. The new production
command is:

~~~text
python_exe -m nx_mcp.drawing_intelligence resume-hybrid-frontend <hybrid-frontend-manifest.json> <structural-visual-decisions.json> <fresh-mode-b-prefix>
~~~

The legacy full-answer command is documented only in the separate compatibility
contract; Fresh Hybrid must never invoke it.

Before that one call, choose `<fresh-mode-b-prefix>` as a fresh **direct child prefix**
of the current `workspace_root` / `NX_MCP_WORKSPACE`, deterministically derived from
the current fresh Hybrid Frontend run name
(e.g. `<workspace_root>\\<fresh-run-directory-name>-mode-b`). Do not reuse a
drawing/date-only prefix from an earlier attempt. For example,
`<workspace_root>\\hybrid-run-20260929-140233-mode-b` is valid, while
`<workspace_root>\\mode-b-runs\\hybrid-run-20260929-140233-mode-b` is invalid.
The Hybrid Frontend run directory may be nested anywhere inside the workspace; the
Mode B artifact prefix may not.

After writing structural answers, **do not issue a separate PowerShell/Test-Path/
Get-ChildItem or other derived-artifact freshness scan before resume**. The Mode B
coordinator performs the authoritative `state_exists` / stale-output gate inside the
single resume call. Invoke resume immediately after the answer file is written. Where the Agent's
code execution tool safely supports sequential commands in ONE tool invocation,
prefer writing the fully reviewed, evidence-backed compact JSON once and
immediately invoking the one allowed `resume-hybrid-frontend` process in that
same invocation. Check write success before the process; never retry, alter
decisions, or change prefix on any error. If a one-call write+resume is not
supported, keep two calls, with no intervening narration, tooling or freshness
checks. This removes an optional Agent tool round-trip, not any Reader gates.
If the coordinator reports an existing state, stale output, or invalid prefix/path, STOP and
do not switch to another prefix or retry.

The resume path owns Structural Context assembly → Hybrid Adapter → Reader Observation
Finalizer → deterministic Mode B coordinator. Do not hand-write
`partial-reader-observations.json` or `reader-observations.json` on this raster path.

Only when the current request has no explicit runtime-local raster path, or the input
is not raster, load `reader-runtime-contract.md` for the fallback semantic Reader: read the
current engineering drawing once as a continuous first-pass session and produce exactly one
immutable `reader-observations-v1` payload, then hand it to the Mode B coordinator.

Do not read historical artifacts, tests, fixtures, expected answers, benchmark
operator documents, previous Agent results, or downstream outputs.

### Deterministic Reader input bundle

On the Hybrid raster path, `prepare-reader-input` is an internal implementation
stage owned by `run-hybrid-frontend`; the Agent must not invoke it separately.
The first Hybrid Frontend failure is terminal for the production run; report it and
STOP. Machine stop fields are authoritative: when a Hybrid Frontend report has
`terminal=true` or `must_stop=true`, especially with `may_retry=false` and
`may_edit_structural_answers=false`, do not rewrite structural answers and do not issue
a second resume. On the fallback semantic path, no raster path may be scanned or guessed.

The current engineering drawing remains the sole authoritative geometry source.

When Hybrid Frontend successfully generated the current `reader-input.json`, its
Structural Reader may inspect only the image paths listed by
`structural-context-queries.json`. The fallback semantic Reader may use the source
drawing directly only under the fallback rules in `reader-runtime-contract.md`.

Do not open all individual crops sequentially. Only when one specific contact-sheet
panel is unreadable may Reader open the corresponding already-listed crop from the
manifest, then return to the same first-pass.

Hard boundaries:

- do not read `raw-evidence.json` or `reader-visual-aid.json` directly;
- do not read historical or pre-existing Reader input/contact-sheet/crop files;
- do not scan the workspace, chat history, repository, or user directories;
- do not create additional crops, PowerShell image scripts, PIL/.NET image helpers, or
  alternate image preprocessing during Reader interpretation;
- use only bounded candidate buckets; an `overflow` bucket has no candidate list and
  must be handled from the authoritative source drawing itself;
- candidate buckets may narrow visual search by region, line orientation and normalized
  position band only;
- witness anchors may indicate nearby region edges, circle-center axes or detected
  linear-pattern axes only;
- never match a dimension by numeric/pixel-scale coincidence;
- never create or merge a physical feature, assign a numeric label, or decide endpoint
  ownership solely from deterministic Reader input.

## 2. Runtime discipline

### Hybrid raster Structural Reader

Inspect each distinct structural-query `image_path` exactly once and answer only the
fields allowed by the generated query contract. If several queries share the same
`image_path`, open that shared image once and answer those `query_id` values
independently using their labeled `region_id` boxes. When the runtime image reader
supports multiple image paths in one call, deduplicate paths first, then batch all
remaining structural-query images into one visual-read call and still answer each
`query_id` independently. Do not insert
per-image progress narration, rule re-reading, or unrelated tool calls between those
visual reads; after all judgments are complete, write the one Fresh
`structural-visual-decisions.json` and call resume exactly once, without extra
`evidence` fields. Only if batch image reading is unsupported may images be read
sequentially. If view_kind is unresolved, provide a structured unresolved reason
and no overall facts. Never use OCR output, pixel scale, old artifacts, or
another crop to fill a missing structural answer.


## 3. Freeze, Confirmation and terminal safety

On the Hybrid raster path, `resume-hybrid-frontend` writes the canonical
`reader-observations.json` through Hybrid Adapter + Reader Observation Finalizer and
immediately hands it to the deterministic Mode B coordinator. The Agent must not
create or rewrite that observations file.

The artifact prefix must be a fresh direct child prefix of the current
`NX_MCP_WORKSPACE`. The coordinator owns the production sequence after visual
interpretation: ReaderObservations validation → ReaderCapture assembly and
contract check → identity linker / Gate 0 → Resolver → bounded Human
Confirmation when eligible → second resolve at most once → canonicalizer /
Gate A. Production Human Confirmation is limited to 1–3 evidence-backed
dimension-endpoint ownership questions. A standalone transverse-thread
`start_side` is not confirmable production truth: canonical entry semantics
use `material_side + entry_endpoint`, which must be established by
deterministic topology/association or remain fail-closed.

The coordinator writes a persistent `*-mode-b-state.json` before assembly.
Therefore a failed first submission is terminal for that prefix: do not rewrite
observations, do not perform a second interpretation, and do not retry by
manually invoking downstream CLI stages.

If the coordinator returns `phase=awaiting_confirmation`, or its public report
sets `human_input_required=true` / `must_stop_for_user_input=true`, this is a hard
human-interaction boundary. In the current assistant/tool turn, read only the generated
confirmation request, present the existing options to the user, and then STOP. Present
only each option's `option_id` and `label_zh`; do not expose internal `target`
strings, `feature:F_...` identities, `F_*_AMB_*` IDs, or Capture E/V/D IDs. Do not
invent extra feature-center/overall-boundary choices beyond the generated request. An
unresolved endpoint with no evidence-backed candidate is unconfirmable and must remain
fail-closed rather than being converted into a broad guessing menu. The Agent must not
infer, rank, or auto-select an option from drawing geometry, dimension ordering,
`evidence_candidate`, candidate count, or any other internal reasoning. It must not
create `user-confirmations.json` or call coordinator `resume` in that same turn.
Resume is allowed only after a subsequent new user message explicitly selects one of
the presented options (or explicitly chooses `KEEP_UNRESOLVED`).

After that later user selection, write `user-confirmations.json` using exactly the
runtime schema below; write one answer for every generated confirmation question, even
when the selected option is `KEEP_UNRESOLVED`:

~~~json
{
  "schema_version": "1.0",
  "answers": [
    {
      "confirmation_id": "CONF_...",
      "selected_option_ids": ["E0_..."]
    }
  ]
}
~~~

Do not write `schema=user-confirmations-v1`, `confirmations`, or singular
`selected_option_id`; those are not accepted runtime fields. Then resume exactly once:

~~~text
python_exe -m nx_mcp.drawing_intelligence.mode_b_coordinator resume <mode-b-state.json> <user-confirmations.json>
~~~

Only `exit code=0` with `phase=gate_a_pass` may continue to Planner. Any other
terminal or blocked result stops the production run.

A Mode B front-end failure from Reader input preparation through Gate A is never
eligible for Controlled Self-Healing. After the first coordinator terminal/blocked
result, do not read schema/source code, do not rewrite `reader-observations.json`,
do not choose a new artifact prefix to retry, and do not call the coordinator again.
After a terminal/blocked result, do not inspect OCR reports or Reader inputs; do not offer restart/fallback/retry as recovery.
Report only the first terminal phase/reason/errors and stop. End the user-facing reply
immediately after that failure report: do not append recommendations, next steps,
alternative inputs, Mode A, restart instructions, or suggestions to start a new task.
A separate fresh task may begin only when the user independently requests it in a later
message; the Agent must not prompt or steer the user to do so. If this task started with
an explicit raster path, the fallback semantic Reader cannot be selected as a recovery
path. A new fresh production run is allowed only after the user explicitly starts a
separate new task.
Report the first state/phase/errors and STOP.

Standalone `assemble-reader-capture`, `check-capture`, `link-capture`,
`resolve`, confirmation, and Gate A commands remain available only for
development, audit, or explicitly requested single-stage troubleshooting; they
must not be chained manually during normal Mode B.
