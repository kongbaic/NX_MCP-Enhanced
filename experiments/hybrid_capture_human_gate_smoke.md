# SHKSS20-40 Hybrid Capture + Human Gate Smoke

Goal: produce one current-contract ReaderCapture quickly enough to exercise the Human Confirmation Gate.

Hard time budget: 5 minutes.
If the immutable capture is not written within 5 minutes, stop and report:
HYBRID_CAPTURE_TIMEOUT

Inputs allowed:
- current SHKSS20-40 source drawing;
- SHKSS20-40_raw_evidence_v0.json;
- skills/nx-agent/SKILL.md;
- skills/nx-agent/references/reader-runtime-contract.md;
- skills/nx-agent/references/nx-drawing-rules.md.

Do not read historical capture/evidence/draft/drawing/plan/report/PRT/STEP,
tests, fixtures, expected answers, benchmark/operator documents, or other Agent results.

Rules:
1. The source drawing is authoritative. RawEvidence is geometry assistance only.
2. Perform one continuous first-pass. No open-ended self-audit.
3. Use RawEvidence to reduce work on view regions, circles/concentric circles, and dashed/centerline candidates.
4. Capture visible feature inventory, direct values, and only identity-sufficient cross-view associations.
5. Do NOT spend time trying to force dimension endpoint ownership.
   - If the witness clearly lands on overall_min / overall_max / an explicit entity center, record it.
   - Otherwise immediately record role="unresolved" with the correct unresolved_kind:
     intermediate_surface | ambiguous_owner | unsupported_reference.
   - For ambiguous_owner, include only evidence-supported candidate_entity_ids.
   - Preserve endpoint source_ids.
6. Do not invent dimensions, targets, associations, or feature identities to make the model close.
7. required_targets must remain [].
8. Before writing, execute production ReaderCapture.model_validate(payload) exactly once.
9. Validation failure: do not repair or create a second interpretation; stop.
10. Validation success: write the same validated payload exactly once to the requested path and freeze.
11. Do not run check-capture, link-capture, Resolver, Human Confirmation Gate, Gate A, Planner, Runner, or NX in this smoke.

Output path:
C:\Users\Kavin\NX_MCP_FAST_BASELINE\human-confirmation-smoke\SHKSS20-40\reader-capture.json

Final output only:
FIRST_PASS_FROZEN = YES
