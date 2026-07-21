# Population Definition: F2_CONFIRMED

## Population

Bar+1-confirmed 1m regime-flip entries on NQ
(`NQ.XCME-1-MINUTE-LAST-EXTERNAL`), RTH only, one contract.
**No 30-second delayed activation** -- that convention (used downstream
in `rank_filter_oos_validation`/`f5_flip_filter_repair`, layered on top
of an already-computed no-delay F2 atlas, never inside the confirmation
logic itself -- confirmed by codebase survey 2026-07-11) is explicitly
treated as a deprecated artifact and is NOT used in this study.

## Entry anchor

1. 1m regime flip closes. `_on_regime_flip` stores
   `self._pending_flip = {flip_ts_event, flip_ts_init, flip_h, flip_l,
   flip_c, direction}` -- `flip_ts_init` is the flip bar's `ts_init`
   (its true close time), not a resampled calendar boundary.
2. **Bar+1 HH/LL confirmation**, evaluated in
   `_check_pending_confirmation` the moment the NEXT 1m bucket closes
   (`bar_ts_event > pending_flip["flip_ts_event"]`):
   - long: `bar+1.high > flip.high`
   - short: `bar+1.low < flip.low`
3. **Bar+1 directional close** (evaluated on the same bar):
   - long: `bar+1.close > bar+1.open`
   - short: `bar+1.close < bar+1.open`
4. Both conditions must hold (`confirmed = hhll_ok and momentum_ok`).
   This predicate is bit-identical in logic to
   `collectors/collector_v2/strategy.py._evaluate_bar1_check` (verified
   by codebase survey) -- re-derived here rather than imported because
   that class also carries collector_v2's microstructure/snapshot
   machinery, which is out of scope and would violate this study's
   isolation requirement if imported wholesale.
5. Entry scheduled immediately at confirmation:
   `fill_ts_target = decision_ts + entry_delay_ns` with
   `entry_delay_ns = 0` (hardcoded to 0 via `F2ConfirmedConfig`
   inheriting the base default; **not** exposed as a tunable in this
   study -- do not set nonzero).
6. Next available executable 1s-open fill, via the same
   "submit ~1s before target" mechanism as ALL_FLIPS.
7. **Pending-entry cancellation on opposite flip before fill**: handled
   by the shared base class in `_on_1m_bucket_closed` -- if a new
   opposing flip is detected while `self._pending_entry` still awaits
   its fill, the entry is canceled and logged to
   `pending_cancellations.parquet` (never silently dropped -- this
   mirrors the already-audited `collector_v2` behavior, not a fresh
   design).

`regime_start_ts` recorded on the trade = `pending_flip["flip_ts_init"]`
(the ORIGINAL flip bar's close, one bar before the confirmation/entry
decision) -- this is deliberately NOT the same as `entry_ts` or
`decision_ts`, since the regime began one bar earlier than the trade.

## Baseline (F0)

Enter every confirmed F2 signal as above. Exit at the next opposing 1m
regime flip. One contract. Same cost model as ALL_FLIPS (project
standard).

## What this population does NOT include

- No 30-second delay (see above).
- No 5m alignment, no microstructure gate, no rank/skip filter -- out
  of scope per the study's explicit exclusion list.
- Does NOT reuse the cached `flip_context_atlas.parquet` from
  `studies/regime_sequence_chop_context` (that atlas's F2 population is
  pandas-derived, not NT-executable, and is excluded per this study's
  "no pandas signal detection" rule) nor any cached weakness score
  trained on a different entry anchor (e.g. the bar-4/180s-240s-delayed
  population used in `delayed_entry_repair`/`exit_optimal_stopping`/
  `state_only_exit_policy_v2` -- confirmed by survey to be a
  structurally different population, not reusable here).

## Causality self-check (answers required by Phase 0)

- Is the population exactly the intended one? Yes -- bar+1 HH/LL +
  momentum confirmed flips only, zero delay.
- Is the executable entry anchor causal? Yes -- confirmation is
  evaluated using only the confirmation bar's own OHLC (available at
  its own `ts_init`) and the flip bar's OHLC (available earlier);
  `decision_ts` is the confirmation bar's `ts_init`.
- Are PnL/MFE/MAE/giveback features measured from the executable entry?
  Yes -- same fill-anchored mechanism as ALL_FLIPS
  (`studies/_shared_exit_mgmt/mfe_mae.py`), anchored to the actual NT
  fill price, not `flip_close` and not the confirmation bar's close.
- Are training and NT serving using the same anchor? N/A at Phase 0/1
  (atlas built directly from this strategy's own NT output).
- Are checkpoints strictly after entry and before terminal exit? Yes,
  same mechanism as ALL_FLIPS.
- Are future outcomes excluded from live features, used only as
  labels/evaluation? Yes, same separation as ALL_FLIPS: forward-looking
  fields are computed entirely offline, post-hoc, from already-closed
  trades.

## RTH boundary decision (user-confirmed 2026-07-11)

The pre-execution lookahead audit flagged a genuine ambiguity: if a 1m
regime flip closes in the last tradable minute of RTH (e.g. 14:59 CT),
bar+1 confirmation is evaluated one minute later, at/after the 15:00 CT
session close. Two options were presented; the user confirmed:
**gate RTH only at the original flip bar** (current code behavior,
matching the existing `collector_v2` precedent) -- the confirmation
and any resulting entry are NOT re-gated against RTH. This is a rare
edge case (at most once per session) and is intentionally NOT
re-checked at confirmation/entry time.

## Status

Code written. Pre-execution lookahead audit found 1 CRITICAL (RTH
classification used bar open-time instead of close-time, inherited
from an unaudited pattern in `collector_v2/strategy.py`) and 5
WARNINGs, all fixed or explicitly resolved (see
`studies/_shared_exit_mgmt/audit.md` for the full report and
`studies/_shared_exit_mgmt/base_strategy.py` for the fixes: RTH
close-time fix, exit-rejection retry, ATR-warmup entry gate, 1m-bar
monotonicity assertion, giveback formula deduplication). The remaining
D1-adjacent warning (unverified equivalence of the two independent 1m
bar sources -- the real `bar_type_1m` catalog subscription vs the
1s-aggregated synthetic 1m bucket) is a data-validation step, addressed
separately in `audit/bar_source_reconciliation.md` before first
execution. Re-audit required before running the backtest per CLAUDE.md.
