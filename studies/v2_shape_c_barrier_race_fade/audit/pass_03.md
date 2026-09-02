# Look-Ahead & Timestamp Audit — Pass 03 (delta)

**Date** 2026-09-02 · **Scope** `compiled_plan.json` (`outcome.horizon_end_rule`, `model.models[*].subset` delta),
`research_workflow/host/outcomes.py` (barrier arm loop, hash changed), `research_workflow/grammar/spec.py` (new field, hash changed)
**Scope hash (audited composite)** `ecfb18141c0ac4cde99b38ad59c2457cb4e833f51af2e4a14994d5bed976a57f`
**Lint** preflight CLEAR; readiness overall PASS (36/36 tests, up from 34) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 0 · Note: 3

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | [pass_02] `nq_1m` role/mux fix | **WITHDRAWN (superseded, already FIXED)** | Unaffected by this delta; `nq_1m` still `role: "context"`/`"strictly_before"` in `compiled_plan.json:streams`. Not re-verified line-by-line again since nothing in this closure touches `mux.py` (hash unchanged, `63f4b6...`). |
| 2 | [pass_02 Note] Frozen-model reuse governance (`reuse_status`/`scientific_status`) | **OPEN, unaffected** | Referred to contract-checker previously; this delta's `subset` correction is a routing fix, not a reuse-governance change. Not re-derived. |
| 3 | [pass_02 Note] Model-input-surface conformance enforced at score time only | **OPEN, unaffected** | No change to `columns.features` or `ordered_model_inputs` in this delta. |

## Checks performed (delta-scoped)
- **`horizon_end_rule: "first_bar_at_or_after"` — traced for look-ahead relative to T (coordinator's question).** In `LabelOutcomeKernel.on_bar`'s per-arm loop (`outcomes.py:316-363`), the new branch only activates when `ts > end` where `end = p.arm_end[i] = entry_ts + horizon_ns`, and `entry_ts` is already strictly after `T` (next-bar-open entry). The bar evaluated (`bar.high/low` of the *current* `on_bar(bar)` call, `ts = bar.ts_init`) is therefore always strictly later than the entry bar and strictly later than the nominal horizon end — never a bar at or before `T`. The branch changes only *how many bars past the horizon end are checked before the arm expires* (one, vs. zero under `strict`); it reads no additional state, no feature, no candidate column, and nothing that was not already going to be delivered to the kernel in the normal event stream. This is label-window construction, not feature computation — squarely inside C1's "labels use future windows by design." **Answer: no, evaluating one bar past the horizon end introduces no look-ahead relative to the decision at T.**
- **`_Pending.arm_end`/`entry_ts` unaffected**, so `atr_availability: through_decision_ts` and the deferred-open mechanism (pass_02, unchanged) are untouched by this delta.
- **Session/gap precedence, minor edge case (not a look-ahead, not blocking).** The new `past_end` branch does not re-check `session_close`/`gap` for the one extra bar it evaluates (unlike the branch below it, which does, for bars still inside the horizon). If an arm's horizon end falls just before session close (so it wasn't already resolved `SESSION_END` at entry) and the *next* bar happens to close after session close or after a tape gap, that bar's touch is still scored as a normal POSITIVE/NEGATIVE/TIMEOUT rather than `SESSION_END`/`GAP`. This is a labeling-precedence nuance (F2/G2 territory), not a causal defect — it never reads anything ahead of when it's naturally delivered. Noting for disclosure only.
- **`model.models[*].subset` correction (`regime_direction`: LONG cells `-1→1`, SHORT cells `1→-1`).** Confirmed this is scoring-stage bookkeeping consumed only by fit/analyze on the already-collected, merged candidate+observation frame — `compiled_plan.json`'s `trackers`/`streams`/`columns.features` sections are byte-identical to pass_02 for the causal host. No collector code path reads `model.models[*].subset`; it does not affect what is visible at `T`, what is emitted as a candidate, or how the barrier kernel resolves. Out of causal scope by construction; confirmed non-causal, not re-audited as a modeling-quality question (that belongs to analysis-decider/contract-checker).
- `research_workflow/target_replay_oracle.py` hash changed (independent second implementation now also carries the rule) — consistent with the stated design that the oracle re-implements the contract independently; not separately re-derived here (parity is proven by the study's own bounded fixture tests, 36/36 passing).

## Notes
- (new) `first_bar_at_or_after` bypasses `SESSION_END`/`GAP` precedence for the one extra evaluated bar — narrow edge case, disclosure only, not blocking.
- (carried forward, open) Frozen-model reuse governance (`reuse_status`/`scientific_status`) — contract-checker scope.
- (carried forward, open) Model-input-surface conformance enforced at score time via column selection, not a compile-time cross-check.

## Referred to contract-checker
- (carried forward) Frozen-model reuse governance / target-authority `21d598a8...` provenance.

## Clean checks
A1-A5, B1-B7, B9, B10, C1-C3, F1 (F2 edge case noted above), F3-F4, G1, G3-G4 clean. H1, H2, H3, H4 clean.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "v2_shape_c_barrier_race_fade", "auditor": "lookahead-auditor", "audited_execution_composite_sha256": "ecfb18141c0ac4cde99b38ad59c2457cb4e833f51af2e4a14994d5bed976a57f", "critical": 0, "warning": 0, "note": 3}
<!-- AUDIT_SUMMARY_V2_END -->
