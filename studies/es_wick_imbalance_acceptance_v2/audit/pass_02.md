<!-- AUDIT_SUMMARY_V2_START -->
{
  "verdict": "CLEAR",
  "audit_type": "causal",
  "study": "es_wick_imbalance_acceptance_v2",
  "auditor": "causal-audit-scottm-pass01",
  "audited_execution_composite_sha256": "3cacbb80eb5bb093353e554c3a5cf6cb0318731d76cff68970fdcdf8a2bf982c",
  "critical": 0,
  "warning": 0,
  "note": 0
}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-17
**Scope (delta from pass 01):** `strategies/flip_prediction_collector.py`
(`_sweep_elapsed_horizons`, `on_stop`), `studies/es_wick_imbalance_acceptance_v2/config/population_contract.json`,
regenerated `audit/execution_manifest.json`. Pass-01 clean areas (A1-A5, B1-B10, C1/C3, F1-F4,
G1-G4, 1s-before-1m dispatch, warmup/output-window separation) were not re-reviewed because the
diff did not touch them.
**Lint:** 0 critical / 0 warning (`audit/lint.json`, 60/60 files, `blocking_clean: true`)
**Preflight:** CLEAR (`audit/preflight.json`, run `20260817T150821Z_068c73758bba`,
`required_next_action: READY_FOR_AUDIT`)
**Execution composite:** confirmed via regenerated `audit/execution_manifest.json` →
`composite_sha256 = 3cacbb80eb5bb093353e554c3a5cf6cb0318731d76cff68970fdcdf8a2bf982c`, matching
the composite declared for this pass. (No shell/execution access in this session to independently
re-run `resolve_execution_manifest.py`; verification is against the stored, freshly-regenerated
manifest artifact, whose `strategies/flip_prediction_collector.py` hash —
`3bd3b3e302b0cef8d7a9e5ec9a97b7bb649b7a51bf07415d5db605167edf0e2d` — differs from pass 01's
`29c03b6650f75d1e3970630609f66dea9cca5c65ed81aea4516d219e8a3b5f41`, consistent with the claimed
edit.)
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | `[C2]` pass 01 CRITICAL: same-tick sweep/flip race at `strategies/flip_prediction_collector.py:391-470` — a candidate whose `horizon_end_ts` lands exactly on a same-tick opposing regime flip was resolved `DISPOSITION_NEGATIVE` by `_sweep_elapsed_horizons` (1s-bar handler) *before* the coincident `_on_regime_flip` (1m-bar handler) ever saw it, because 1s bars dispatch before the coincident 1m bar. | **FIXED** | `_sweep_elapsed_horizons(now_ts, final=False)` (line 391) now has `if horizon_end > now_ts or (horizon_end == now_ts and not final): still_pending...` (line 417) — a candidate at the exact boundary is held one extra tick instead of resolved immediately. Traced the full resolution path: (a) same-tick flip case — candidate stays pending through the 1s-bar sweep, then `_on_regime_flip` (line 474, `within_horizon = cand_ts <= flip_ts <= horizon_end_ts`) correctly marks it `POSITIVE`; (b) no-flip case — the *next* 1s tick's sweep (`now_ts` now `> horizon_end`, `final=False`) resolves it `NEGATIVE`/`CENSORED` using only data available as of that later, still-non-future tick; (c) run-end case — `on_stop()` (line 445) now calls `_sweep_elapsed_horizons(self.last_ts_seen, final=True)` before the residual-pending censor loop, so a horizon that completed exactly at the last observed bar is labeled from the data that was actually dispatched, not force-censored. No new race introduced: `pending_candidates` is still cleared wholesale on any flip (line 489) and a resolved candidate is never revisited. |
| 2 | Referral: `population_contract.json` declared `checkpoint_frequency: "1m_bar_close"` but actual cadence is the 5s grid. | **FIXED** | `config/population_contract.json:11-14` now declares `"checkpoint_frequency": "5s"`, `"checkpoint_grid_origin": "regime_start_ns"`, `"triggering_stream": "completed_1s_bar"` — matches `CANDIDATE_STEP_NS = 5 * NS` and the `_handle_1s_bar` triggering path exactly. |
| 3 | Referral: stored `execution_manifest.json` composite did not match the task-declared composite. | **FIXED** | Regenerated manifest's `composite_sha256` (`3cacbb80eb5bb093353e554c3a5cf6cb0318731d76cff68970fdcdf8a2bf982c`) now matches. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
None new this pass.

## Clean checks
- C2 (label timestamp alignment at the terminal-disposition horizon boundary): re-verified clean
  per adjudication above — this is the only area the diff touched within my scope.
- All other categories (A, B, C1/C3, F, G, H) unchanged since pass 01 and not re-reviewed, per
  the bounded re-audit protocol (diff did not touch those files/lines).
