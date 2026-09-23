# Hybrid Raster VLM Feasibility Smoke

Goal: decide quickly whether lightweight raster geometry evidence materially improves engineering-drawing interpretation.

Time budget: 5 minutes. If this smoke cannot finish within 5 minutes, stop and report HYBRID_VLM_TIMEOUT.

Inputs:
- the current SHKSS20-40 source drawing;
- a RawEvidence v0 JSON produced by the raster experiment.

Rules:
- The drawing remains authoritative.
- RawEvidence contains pixel geometry candidates only; it does not assert engineering semantics.
- Do not read historical captures, Reader benchmark artifacts, tests, fixtures, expected answers, or downstream NX artifacts.
- Do not read the full Reader contracts for this smoke.
- Do not create ReaderCapture, run linker, Resolver, Gate A, Planner, Runner, or NX.
- Do not perform an open-ended self-audit loop.

Answer only these questions:

1. Views
Map each RawEvidence region to the engineering view it most likely contains.

2. Feature inventory
For every circle group, state the most likely physical feature from the drawing.
Do not merge two groups merely because both are circular.

3. Cross-view candidates
For each identified circular feature, identify any linear-pattern candidate in another view that is plausibly its orthographic projection.
If the evidence is not sufficient for a unique association, return unresolved rather than guessing.

4. Dimension ownership coverage
State whether RawEvidence v0 itself contains enough evidence to determine visible dimension endpoint ownership.
This is a capability check, not a request to invent missing evidence.

Return compact JSON only:

{
  "views": [],
  "features": [],
  "cross_view_candidates": [],
  "dimension_ownership_supported": false,
  "unresolved": [],
  "result": "useful|not_useful"
}
