# Look-Ahead & Timestamp Audit — Pass 02 (delta)

**Date** 2026-09-02 · **Scope** `compiled_plan.json` (streams/availability_table delta), `research_workflow/grammar/compiler.py`
(role-assignment change), `research_workflow/host/mux.py` (mechanism re-verification, unchanged file)
**Scope hash (audited composite)** `7676acfb42fa863b0d0aaae57ae1859e3340b4d549c66367cd68f871d04e1515`
**Lint** preflight CLEAR; readiness overall PASS (34/34 tests, up from 33) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 0 · Note: 2

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | [A4/B9, pass_01] Same 1m-context causal-order reliance as sibling Shape A (identical closure/composite at pass_01) | **FIXED** | `compiled_plan.json:streams` now shows `nq_1m: {"role": "context", "visibility": "strictly_before"}` (was `execution`/`at_epoch`); `availability_table` shows `regime_1m` and `regime_bar_5m` now `"visibility": "strictly_before"`. Identical mechanism to Shape A's pass_02 adjudication (`research_workflow/host/mux.py` unchanged, `63f4b6...`): `nq_1m` bars now route through `StreamMux._context_queue` and are released only strictly-before the next execution-stream (`nq_1s`) bar, via `_release_context`; `assert_epoch_visibility` now has a live invariant for `nq_1m`. Same reasoning as Shape A applies verbatim since this study shares the identical closure and composite (`7676acfb42fa863b...`) both before and after the fix. |
| 2 | [pass_01 Note] Frozen-model reuse governance (`reuse_status`/`scientific_status`) | unaffected, not causal | Referred to contract-checker in pass_01; not re-derived here (out of scope). |

No CRITICAL findings existed in pass_01; nothing else to adjudicate.

## Checks performed (delta-scoped)
- **Barrier kernel unaffected by the timing fix.** `atr_availability: "through_decision_ts"` and the deferred-open mechanism (`HostCore._flush_deferred_opens`) are independent of the `nq_1m` role change — they operate on `regime_1m.atr`'s value at flush time, which is *itself* now correctly bounded by the same strictly-before-T enforcement for the underlying `nq_1m` stream. Re-traced: `regime_1m` (the ATR source) is fed by `nq_1m`, now context/strictly_before; the deferred-open flush still resolves `atr = resolve(atr_ref, epoch)` only once a bar with `ts_init > T` arrives, and by that point any `nq_1m` bar with `ts_init == T` has already been released (since release happens at `before_ts = <that later bar's ts_init> > T`). The "sealed target authority" through-decision-ts semantics (ATR reflects the 1m bar closing exactly at T) is therefore **preserved exactly**, now via the context-queue's release-on-next-execution-bar mechanism rather than via `add_bars_causal_order` load order alone — same value, stronger guarantee.
- **Six frozen models / candidate columns unaffected.** `columns.features`/`columns.observation` and the `model.mode:"score"` block are untouched by this compiler change; `preflight.json` reconfirms `leaked_outcome_columns: []` under the new composite.
- Day parity (C: 2021-01-05, 1591 rows/13 obs cols) stated exact vs. the prior composite, consistent with a defense-in-depth (not value-changing) fix — same reasoning as Shape A.

## Notes
- (carried forward, still open, not causal) Frozen-model reuse governance (`reuse_status: PERMITTED` / `scientific_status: UNASSESSED`) — referred to contract-checker.
- (carried forward) Model-input-surface conformance is enforced by column selection at score time, not a compile-time cross-check against `columns.features`; unaffected by this delta.

## Referred to contract-checker
- (carried forward) Frozen-model reuse governance / target-authority `21d598a8...` provenance.

## Clean checks
A1-A5, B1-B7, B9, B10, C1-C3, F1-F4, G1-G4, H1-H4 clean.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "v2_shape_c_barrier_race_fade", "auditor": "lookahead-auditor", "audited_execution_composite_sha256": "7676acfb42fa863b0d0aaae57ae1859e3340b4d549c66367cd68f871d04e1515", "critical": 0, "warning": 0, "note": 2}
<!-- AUDIT_SUMMARY_V2_END -->
