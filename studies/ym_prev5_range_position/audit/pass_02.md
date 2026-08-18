<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "causal-audit-scottm-ym-prev5-pass02", "critical": 0, "warning": 0, "note": 1, "study": "ym_prev5_range_position", "audited_execution_composite_sha256": "9b6b51243d215f3c6d83909c84d06c9805b2091d1eb23fe96bdad1d0b48d187a"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-18
**Scope:** `strategies/flip_prediction_collector.py` (the 4-line wiring diff: import line 28,
`self.range_position_tracker = RangePositionTracker()` line 186, `self.range_position_tracker.update(h, l, c)`
line 333, `range_position_feats` merge lines 874/887), `features/trackers/range_position.py` (re-read,
unchanged since pass_01), `studies/ym_prev5_range_position/compiled_study.json` (feature_contract,
`bound_trackers`, `strategy_class`).
**Preflight:** run_id `20260818T124331Z_7a57e510557a` — **BLOCKED** on `ARTIFACT_SCHEMA`/`STATUS_SCHEMA`
(`audit/contract_status.json` missing an integer `critical` field). This is a stale
**contract-checker** artifact from pass_01 (still carries `"verdict":"blocking":1` under the old
schema key and the old composite sha `e0e613...`) — a `C4`/deliverable-artifact defect, not a causal
one. The two causally-relevant deterministic checks both ran clean on the new composite:
`CAUSAL_LINT` 0 critical/0 warning, 63/63 files, `blocking_clean: true`; `EXECUTION_MANIFEST`
78/78 files resolved, 100% coverage, composite matches the target sha. Proceeding with the causal
re-audit on that basis; referred below.
**Verdict:** CLEAR (causal scope A, B, C1–C3, F, G, H)

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | pass_01 NOTE (referred, not blocking): `flip_prediction_collector.py` never instantiates/updates `RangePositionTracker`; sole declared feature always `None`. | **FIXED** | `flip_prediction_collector.py:28` imports `RangePositionTracker`; `:186` instantiates it unconditionally in `__init__`; `:333` calls `.update(h, l, c)` inside `_handle_1m_bar`; `:874`/`:887` calculate and merge it into `merged_raw`, which is read at `:894` (`feats_to_log = {k: merged_raw.get(k, None) for k in study_universe}`) against `study_universe = ['latest_1m_close_position_prev5_range']`. The key now resolves. |

## Critical findings
None.

## Warnings
None.

## Notes

### [N1] Preflight ARTIFACT_SCHEMA failure is a stale contract-checker artifact, out of causal scope
`audit/contract_status.json` is contract-checker's pass_01 convenience copy (`auditor:
"contract-checker-pass01-2026-08-18"`, `audited_execution_composite_sha256: "e0e613..."`, uses the
key `"blocking"` where the current schema validator expects `"critical"`). It predates this fix and
was never regenerated against the new composite. This is a `C4`/deliverable-artifact defect
(contract-checker's own output schema/staleness), explicitly out of this auditor's scope per
`docs/CAUSAL_CHECKLIST.md`. Referred below; not adjudicated as a causal finding and does not affect
this verdict.

## New findings — causal soundness of the 4-line diff

### Update-site causality — CLEAN (A1, A3, B2, B9)
`_handle_1m_bar` (`flip_prediction_collector.py:246-334`) is dispatched from `on_bar` (`:239-244`)
only when `"1-MINUTE" in str(bar.bar_type.spec)`, i.e. once per NT-delivered completed 1-minute bar
(NT only delivers closed bars historically/in backtest — same dispatch convention already verified
for `wick_tracker` in pass_01). `h, l, c` are extracted from the `bar` argument at function entry
(`:250-252`) and never reassigned before use. `self.range_position_tracker.update(h, l, c)` at
`:333` fires exactly once per call, immediately after `self.wick_tracker.update(o, h, l, c)` at
`:332` — the same causal point already verified clean for the sibling tracker, downstream of regime
computation (`:257`) and regime-flip handling (`:305-329`), neither of which mutates `h/l/c`. No
reordering relative to any other tracker changes what data is visible at update time.

### Tracker-internal exclusion — CLEAN, re-verified (B2, B3)
`RangePositionTracker.update()` (`features/trackers/range_position.py:50-65`, byte-identical to
pass_01) computes `prev5_high`/`prev5_low` from `self._history`'s **pre-update** contents, then
appends `(high, low)` for the bar just processed — bar t is structurally excluded from its own
reference range regardless of which call site invokes `.update()`. This property is a function of
the tracker's own state machine, not the caller, so the new call site inherits the same guarantee
already tested by `scripts/tests/test_range_position_availability.py`.

### Merge/read timing — CLEAN, no skew (C2)
`range_position_feats = self.range_position_tracker.calculate()` (`:874`) and its merge into
`merged_raw` (`:887`) execute synchronously within the same observation-time snapshot function as
`wick_feats` (`:873`/`:886`) and every other tracker snapshot in that dict — all read at the same
tick, from state as of the same `T`. `merged_raw` is read once, immediately after, at `:894` to
build `feats_to_log`. No caching, no deferred read, no cross-call state leak.

### Targeted-60 path — NOT touched, confirmed (D-adjacent but verified for causal correctness)
`self._is_targeted_60 = bool(config.feature_list and len(config.feature_list) == 60)` (`:178`); this
study's `compiled_study.json` `feature_contract.feature_count = 1` and `feature_list =
["latest_1m_close_position_prev5_range"]`, so `_is_targeted_60` is `False` for this study. The
`all_computed_60` branch (`:760-842`, gated by `if self._is_targeted_60:`, ends with `return` at
`:842`) is never reached; execution falls through to the general fallback block at `:844-894`, which
is the only place `range_position_feats` is merged. The tracker is still unconditionally instantiated
and updated (`:186`, `:333`) regardless of `_is_targeted_60`, which is correct — updating is cheap and
harmless even when unused, and avoids a second conditional causal-update path to audit.

## Referred to contract-checker
- `audit/contract_status.json` is a stale pass_01 convenience copy (old composite sha, old schema key
  `"blocking"` vs current `"critical"`) causing the deterministic `ARTIFACT_SCHEMA` preflight check to
  fail; needs regeneration against the new composite (`9b6b512...`) before overall preflight can read
  `CLEAR`. Not a causal defect.

## Clean checks
- A1, A2, A3, A5, B1-B9, C1, C2, C3, F1, F2, G1, G2, G3 — unchanged from pass_01, no new session/
  timestamp/label logic introduced by this diff, re-confirmed via direct re-read of the touched call
  sites.
- H1-H4 not applicable — collect-only study, no bracket/exit simulation in this SPEC.
