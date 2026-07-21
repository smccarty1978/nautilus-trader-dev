# Population Definition: ALL_FLIPS

## Population

Every completed 1m regime flip on NQ (`NQ.XCME-1-MINUTE-LAST-EXTERNAL`),
RTH only (08:30-15:00 CT, configurable via `rth_start_min`/`rth_end_min`),
one contract, no confirmation filter of any kind.

## Executable entry anchor

1. The 1m regime flip bar closes. In NT, this is detected in
   `_on_1m_bucket_closed`, called from `_on_1s_bar` at the instant the
   1s bar arrives whose `ts_init` closes the 1m bucket in the registry
   (`s_1m.close_ts != self._last_seen_1m_close_ts`). `decision_ts` is
   set to **that 1s bar's `ts_init`** -- never the 1m bar's `ts_event`
   (which is its OPEN time) and never a pandas-resampled calendar
   boundary.
2. The signal (new regime, opposite the previous regime) is known at
   `decision_ts`. No waiting period, no confirmation bar.
3. Entry is scheduled immediately: `_schedule_entry(...)` sets
   `fill_ts_target = decision_ts + entry_delay_ns` with
   `entry_delay_ns = 0`, so `fill_ts_target == decision_ts`.
4. `_on_1s_bar` submits the market order once
   `decision_ts_now >= fill_ts_target - 1s` -- i.e. on the very next 1s
   bar after the flip bar closes -- and NT's `bar_execution=True` venue
   fills a market order at the **next** bar's open, not the bar that
   triggered submission. This is the "next available executable 1s-open"
   fill described in the study spec; it is not a pandas-derived
   `flip_close` price used as if it were fillable.

`regime_start_ts` recorded on the trade = the flip bar's own
`close_ts` (`bar_data["ts_init"]`), since for this population entry and
regime-start are the same event.

## Baseline (A0)

Enter every RTH flip as above. Exit at the next opposing 1m regime
flip (`_submit_exit(reason="opposite_flip")`, triggered in
`_on_1m_bucket_closed` before the new pending flip/entry state is set).
One contract. Cost model: NQ multiplier 20, commission $5/RT + $5
tick cost (matches `collectors/collector_v2/strategy.py`'s established
convention, `TICK_COST`/`COMMISSION`).

## What this population does NOT include

- No bar+1 HH/LL or momentum confirmation (that is the F2_CONFIRMED
  population in the sibling study -- see
  `studies/f2_confirmed_exit_management/audit/population_definition.md`).
  All_flips and F2_confirmed strategies are separate classes
  (`AllFlipsStrategy` vs `F2ConfirmedStrategy`) built on a shared,
  population-agnostic base (`studies/_shared_exit_mgmt/base_strategy.py`)
  that itself contains no confirmation logic -- confirmation is
  entirely supplied by the F2 subclass, so there is no risk of the
  all-flips population silently inheriting F2's gating.
- No 5m alignment gate, no microstructure gate, no rank/skip filter --
  those belong to unrelated, out-of-scope studies
  (`rank_filter_oos_validation`, `f5_flip_filter_repair`,
  `adaptive_rank_filter_walkforward`) per the study's explicit
  exclusion list.

## Causality self-check (answers required by Phase 0)

- Is the population exactly the intended one? Yes -- every RTH 1m
  regime flip, unconditionally.
- Is the executable entry anchor causal? Yes -- `decision_ts` is a
  `ts_init` value throughout; the registry's `audit_provenance()`
  (inherited via `CompletedBarRegistry`, called implicitly through the
  regime engine's write path) raises `CausalityViolation` if any stored
  timeframe state has `close_ts > decision_ts`.
- Are PnL/MFE/MAE/giveback features measured from the executable entry?
  Yes -- `_update_open_trade` anchors every running/checkpoint field to
  `t["fill_price"]` (the actual NT fill), never to `flip_close` or any
  other pre-fill reference price. See
  `studies/_shared_exit_mgmt/mfe_mae.py`.
- Are training and NT serving using the same anchor? N/A at this phase
  (Phase 0/1 produces the atlas directly from this NT strategy's own
  output; there is no separate offline re-derivation of entry price).
- Are checkpoints strictly after entry and before terminal exit?
  Yes -- `_update_open_trade` is only invoked while `self._trade is not
  None` and only appends a checkpoint after `entry_ts`/`fill_price` are
  set (post-fill); the last checkpoint before exit is naturally the
  1s bar preceding the exit fill, since `_trade` is cleared in
  `_finalize_trade` before any further checkpoint could be appended.
- Are future outcomes excluded from live features? Yes -- all fields
  written into `checkpoints.parquet` at runtime are causal (computed
  from bars with `ts_init <= checkpoint_ts` only). Forward-looking
  labels (`eventual_new_mfe`, `eventual_recovery_to_prior_mfe`,
  `eventual_opposite_flip`, `terminal_weakness_label`,
  `remaining_mfe_atr`, `remaining_mae_before_next_mfe_atr`) are NOT
  computed inside the NT event loop at all -- they are computed in a
  separate, offline Phase 1 atlas-builder script that reads the
  already-completed `trades.parquet`/`checkpoints.parquet` output and
  looks *within a trade's own already-closed path* to construct
  labels, exactly as required by CLAUDE.md's "ML MODEL REQUIREMENTS"
  (labels from NT backtest outcomes; future outcomes used only as
  labels/evaluation, never fed back into the live decision path).

## Status

Code written. Pre-execution lookahead audit (shared with the sibling
F2_CONFIRMED study, since both subclass the same base class) found 1
CRITICAL (RTH classification used bar open-time instead of close-time,
inherited from an unaudited pattern in `collector_v2/strategy.py`) and
5 WARNINGs, all fixed or explicitly resolved (see
`studies/_shared_exit_mgmt/audit.md` for the full report and
`studies/_shared_exit_mgmt/base_strategy.py` for the fixes: RTH
close-time fix, exit-rejection retry, ATR-warmup entry gate, 1m-bar
monotonicity assertion, giveback formula deduplication). The remaining
D1-adjacent warning (unverified equivalence of the two independent 1m
bar sources) is a data-validation step, addressed separately in
`audit/bar_source_reconciliation.md` before first execution. Re-audit
required before running the backtest per CLAUDE.md.
