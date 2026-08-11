# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-11
**Scope:** `SPEC.md` §5; `implementation/{rungs.py,build.py,validate.py}`;
`analysis/{phases.py,examples.py,close_out.py}`. Data-level verification run
against `results/{rung_transitions,ratchet_economics,stop_survival_frontier}.parquet`.
**Scope hash:** `3245e1f29209cd0e89077dc19ba86426d9b0ae2e446d8a9cd9ffed72b5a3a3d0`
**Lint:** 0 critical / 0 warning from `causal_lint.py` (9 files scanned, clean)
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 1
- Note: 1

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [D5 WARNING] `rungs.py:198-199` optimistic bound collapsed onto adverse value on single-bar transitions | **FIXED** | `opt = self._adverse(r, t-1, X) if ok else adv` now relies on `_adverse`'s `t<=r` guard. Re-ran on live output: 273 SUCCESS rows with `secs_to_target<=1s` (i.e. `t=r+1`) all now show `mae_from_hwm_optimistic_atr==0.0` and `collision_at_target==True` where the adverse value is nonzero — the exact behavior the fix specifies. No residual case where `opt==adv` for a single-bar transition. |

## Critical findings

### [D1/H2] `analysis/phases.py:291-355` `survival_frontier()` — Phase 5 reads STOP-LIVE-gated exits instead of the UNCONSTRAINED simulation SPEC D1 requires, and the one gate built to catch it (`validate.py` gate 7) is hardcoded to pass

**Failure path:** SPEC D1 states Phase 5 must be **UNCONSTRAINED** ("undefined if a different stop already ended the path") and D4 states the correspondence `pct_success_surviving(D) == mean(mae_from_hwm_atr < D)` holds **exactly, to the row** — the frontier is defined to be nothing but the CDF of the Phase-2 statistic. `survival_frontier()` instead joins `xd` (Phase 2, correctly unconstrained) to `cd` = `ratchet_economics.parquet`, whose `policy_exit_idx`/`policy_exit_kind` come from `RatchetTrade.policy()` (`rungs.py:346-370`), which is explicitly the **STOP-LIVE** function: `if r > w.nat_i: return {"policy_exit_kind": "NOT_REACHABLE", "policy_exit_idx": int(w.nat_i), ...}`. `stopped_before_target` (`phases.py:311-313`) only recognizes `policy_exit_kind == "RATCHET"`, so every `NOT_REACHABLE` row — a rung reached after the accepted 1.00 ATR stop already closed the trade, ≈1.7–2.4% of rung events per SPEC's own count — is unconditionally counted as **surviving**, regardless of its actual `mae_from_hwm_atr`.

I reproduced this directly against the checked-in outputs (not hypothetical):
```
rung=1.0 step=0.5 D=0.25 arch=HWM: n_success=2447, NOT_REACHABLE=42 (1.72%)
  frontier pct_success_surviving (incl. NOT_REACHABLE) = 19.452%
  same population excl. NOT_REACHABLE                  = 18.046%
  raw CDF mean(mae_from_hwm_atr < D)                    = 18.186%
```
Then swept all 168 `(rung × step × D)` POOLED cells for both `HWM` and `STATIC`:
**168/168 disagree** between `stop_survival_frontier.pct_success_surviving` and the direct Phase-2 CDF, every one biased the same direction (frontier reads higher survival than the CDF), by up to 2.5 pp. `validate.py` gate 7 (`"frontier_is_cdf_of_phase2"`) computes the same CDF into a `detail` list and then reports `_g("frontier_is_cdf_of_phase2", True, {...})` — the boolean is a **literal for the check that never runs**; nothing in the function reads `stop_survival_frontier.parquet` or compares to it. `validation_report.json` (already generated) shows `"frontier_is_cdf_of_phase2": true`.

This reaches the decision gate directly: `master()` (`phases.py:515-546`) takes `success_050_survival` and `giveback_prevented`/`failure_stop_rate` straight from `fr` (this same frontier table), and `decision_gate()` condition 1 (`>= 90%` preservation) and condition 2 (`giveback >= 0.50` AND `fail_stop_rate >= 25%`) are evaluated on those numbers. `NOT_REACHABLE` FAIL rows are also folded into `pct_fail_stopped`'s denominator (`fail["stopped_at_all"].mean()`) while never able to be `stopped_at_all=True`, deflating `failure_stop_rate` for the same population. Both gate-1 and gate-2 inputs are therefore computed on the wrong track for a systematic subset of rows, in violation of D1's explicit UNCONSTRAINED-vs-STOP-LIVE separation.

**Smallest fix:** give `survival_frontier()` its own unconstrained exit simulation (e.g. call `exit_index`/`_next_hit` directly, bypassing `policy()`'s `r > w.nat_i` gate — that gate belongs only to Phases 6–7), or at minimum drop `NOT_REACHABLE` rows before computing `stopped_before_target`/`stopped_at_all`. Separately, make `validate.py` gate 7 actually load `stop_survival_frontier.parquet` and assert `abs(pct_success_surviving/100 - cdf) < eps` per row instead of returning a hardcoded `True`.

## Warnings

### [general] `validate.py:271-275` gate 14 (`placebo_causality`) is also hardcoded `True`
Same anti-pattern as gate 7 but lower stakes: SPEC gate 14's claim (offset support is lifetime-independent) is enforced structurally in `build.py::placebo_armings` (confirmed clean in pass 1) rather than being a per-row numeric identity, so there is no comparably concrete failure path today. Flagged as WARNING because a future edit to `placebo_armings` would not be caught by this gate either.

## Notes

### `rungs.py:266` `censored_h{H}s` compares a bar count to a second count
`k` (bars elapsed since `r+1`) is compared against `H` (seconds) as `bool(k < H)`. Correct only if the 1s path has exactly one bar per elapsed second with no gaps; not verified here. Not wired into any headline number (`HORIZONS_S` columns are not in the SPEC §6 Deliverable #6 column list), so it is disclosure-only.

## Referred to contract-checker
- `rungs.py:242-277`'s `mae_from_hwm_h{H}s_atr` / `censored_h{H}s` horizon columns are not listed among Deliverable #6's required `failure_geometry` contents in SPEC §6 — manifest coverage, not a causal defect in the values themselves.

## Clean checks
- **D5 fix (re-verified):** confirmed FIXED above with fresh output evidence, not just code reading.
- **D12 (Phase 3 symmetry):** `_failure_geometry(r, unc, X)` is called with identical arguments regardless of `outcome` (`rungs.py:197, 221`) — the fixed-horizon MAE columns cannot be asymmetric between SUCCESS/FAIL because the code path does not branch on outcome.
- **`overlap()` matched AUC:** `auc_horizon_matched` and each `auc_matched_h{H}s` in `analysis/phases.py:246-254` read the **same column name** (`mae_from_hwm_h{H}s_atr`) from both `fail[...]` and `suc[...]` — no cross-class column substitution. `auc_raw_DURATION_CONFOUNDED` intentionally compares different columns (target-window vs terminal-window), which is the disclosed design, not a defect.
- **`survival_frontier()` join keys:** `tr.join(ec, on=["regime_id","rung_atr"])` cannot cross architecture or stop distance — both come uniquely from `ec`'s own per-row `stop_d`/`architecture`, and `stopped_before_target`/`stopped_at_all` are recomputed per joined row, not aggregated pre-join.
- **`ratchet_summary()` non-achiever handling:** `economics_rows()` (`build.py:79-135`) emits a row for every trade at every one of the 126 `(X,D,arch)` cells regardless of achievement, with `delta_atr=0.0` for non-achievers — `vec=np.zeros(n_tr)` in `ratchet_summary` is consistent with, not a substitute for, that structural zero-fill. Non-achievers are never dropped.
- **`ratchet_summary()` bootstrap:** `boot_idx` resamples indices into the unique `regime_id` array (`ids = cd["regime_id"].unique()`), i.e. trades, not the 126x-exploded row table — satisfies D10.
- **`examples.py::path_rows`:** `live_stop_level_atr = hwm_prev[k] - D` exactly, matching the spec's bar-`k`-from-bar-`k-1` requirement; selection criteria (`eventual_max_mfe_atr`, `runner_survived_3_0`) are used only for choosing which trades to display, never for arming.
- **Gate 8 (`ladder_hwm_identical_to_hwm`):** genuinely tests the D7 claim — arms `HWM` at a later rung and compares its exit index to the lowest-rung arming, correctly excluding cases where the lowest arming had already fired by the later rung. Not a rubber-stamp.
- **Gate 10 (`hard_truncated_replay`):** recomputes rung/adverse-excursion state from independently-sliced truncated arrays and diffs against production output; catches implementation drift in `_adverse`/`rung_index`, though its docstring's "absent from memory" framing overstates the mechanism (referred above as manifest/wording, not causal).
