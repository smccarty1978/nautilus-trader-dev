# Look-Ahead & Timestamp Audit — Pass 03

**Date:** 2026-08-11
**Scope:** `SPEC.md` §5, §9; `implementation/{build.py,rungs.py,validate.py}`;
`analysis/phases.py` (only files modified since pass 02, confirmed via mtime
vs `audit/pass_02.md`). Verified against regenerated
`results/{stop_survival_frontier,ratchet_economics,rung_transitions,
decision_gate}.parquet`, `validation_report.json`, `gate_verdict.json`.
**Scope hash:** `b9b5b97ce732becff4500e5f127d96c6bbf198cfab7adc62fc6a6d74080b4ce6`
**Lint:** 0 critical / 0 warning from `causal_lint.py` (9 files scanned, clean)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [CRITICAL D1/H2] `survival_frontier()` read STOP-LIVE exits; `NOT_REACHABLE` counted as surviving; gate 7 hardcoded `True` | **FIXED** | `build.py:120` (`unc_e = rt.exit_index(r, D, arch, X)`) computes the trigger bounded only by `w.unc_i`, bypassing `policy()`'s `r > w.nat_i` gate entirely — the descriptive track no longer touches `policy_exit_kind`. Independently recomputed `rung=1.0/step=0.50/D=0.25/HWM`: shipped `pct_success_surviving = 18.1855%`, matches raw Phase-2 CDF `mean(mae_from_hwm_atr < D) = 18.1855%` **exactly** (was 19.452% vs 18.186% in pass 2, a real 1.27pp defect). Swept all 168 `(rung×step×D)` POOLED cells via `gate 7`'s own recompute: `max_abs_difference_recomputed = 0.0`, `max_abs_difference_SHIPPED_TABLE = 1.1e-16` (168/168 cells, not a subset) — gate 7 now reads `stop_survival_frontier.parquet` from disk and asserts against it, not a literal. Economic columns (`giveback_prevented_*`, `realized_return_if_stopped_*`) deliberately stayed on `stopped_at_all_stop_live` (`policy_exit_kind=="RATCHET"`) — verified this split is coherent, not a mix (see Notes). Downstream: `decision_gate` condition 1 (`success_050_survival>=90`) pass-count is now 4/126 (previously inflated); `gate_verdict.json` confirms `n_cells_passing_all_7=0`, verdict unchanged at D because condition 3 (economics, untouched by this fix, reads `ratchet_economics.parquet`'s stop-live `delta_atr` directly) was already 0/126 and remains 0/126. |
| 2 | [WARNING] gate 14 hardcoded `True` | **FIXED** | `validate.py:318-357` now draws `blind`/`unif` for 120 trades (60 shortest + 60 longest lifetime quartile trades), asserts every armed `blind` index is exactly a member of `{index_at_offset(L) for L in DENSE_OFFSETS_S}` — structural set-membership, not a wall-clock tolerance. Ran result: `blind_armings_checked=1251, blind_armings_off_grid=0`, `uniform_confirmed_lifetime_dependent=120/120`. The gap-immune equality is the right property: it tests that the arming *support* (which offsets are even candidates) is fixed regardless of realised lifetime, while correctly allowing lifetime to gate *whether* a drawn offset lands in-window — exactly what "P_BLIND cannot know how long the trade lives" requires, without the false-failure risk pass 2 flagged from wall-clock tolerance on tape gaps. Can fail: any drift in `placebo_armings`' offset grid or its `index_at_offset` boundary would raise `bad14>0`. |
| 3 | [NOTE] `censored_h{H}s` compared bar-count `k` to seconds `H` | **FIXED** | `rungs.py:271-272`: `k == 0 or int(ts_suf[k-1]) < int(w.ts[r]) + H*NS` — now a timestamp comparison of the last in-window bar's own `ts` against the horizon cutoff, not a bar-count proxy. Logic checked against both branches of `_first`: when no bar exceeds the horizon (`end<0`, `k=lo.size`), the flag correctly reads the last available bar's timestamp; when a bar exceeds it (`end>=0`, `k=end`), the flag reads the last in-window bar. Not wired into any headline column (unchanged from pass 2's disclosure note). |

## Critical findings
None.

## Warnings
None.

## Notes

### Condition 2 (`decision_gate`, `phases.py:589-591`) mixes unconstrained `failure_stop_rate` with stop-live `giveback_prevented` — currently inert
`failure_stop_rate` (from `pct_fail_stopped`, `unc_stopped`-based, unconstrained) and `giveback_prevented` (from `st = fail.filter(stopped_at_all_stop_live)`, `policy_exit_kind=="RATCHET"`-based) are evaluated together in one AND condition but drawn from different populations — the unconstrained fail-stop denominator is broader than the stop-live subset the giveback mean is averaged over. Checked whether this could flip any cell: `pct_fail_stopped` min across all 126 POOLED cells is 91.6% and `pct_fail_stopped_stop_live` min is 90.6% — both far above the 25% threshold on every cell (gap 1.0–3.5pp), so the mixing never determines a pass/fail boundary in this data; the binding constraint on the 2 failing cells is `giveback_prevented < 0.50`, computed correctly on the stop-live-only track. Disclosure only; would need re-review if the D grid or population ever narrowed enough to put `failure_stop_rate` near 25%.

## Referred to contract-checker
- (carried from pass 2, unchanged) `rungs.py` `mae_from_hwm_h{H}s_atr`/`censored_h{H}s` horizon columns are not listed in SPEC §6 Deliverable #6's `failure_geometry` column manifest.

## Clean checks
- **D1/H2 fix (survival_frontier unconstrained track):** re-verified independently against shipped parquet, not just code reading — see adjudication row 1.
- **Gate 14 fix:** re-verified via `validation_report.json` detail block, not just code reading — see adjudication row 2.
- **D5 fix (pass 1, opt/adv single-bar guard):** `rungs.py:200-208` unchanged since pass 2's fix; `rungs.py` was modified this pass (mtime newer than `pass_02.md`) but only in `_failure_geometry`'s `censored_h{H}s` block and did not touch the `transition()`/`_adverse()` region — no regression.
- **`economics_rows()` unc_e wiring:** `build.py:120,135-136` computes `unc_exit_idx`/`unc_stopped` unconditionally (before the `r > w.nat_i` branch that only affects `policy_exit_kind`/`policy_return_atr`), so every achieved row — participant or not — carries a genuine unconstrained trigger; NOT_ACHIEVED rows (r<0) correctly have no `unc_exit_idx` key and are excluded from `survival_frontier`'s join population (same as before).
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1, H3, H4: unchanged since pass 1/2 (no modified file touches session/timezone/data-integrity/re-entry logic); not re-audited per re-audit protocol.
