# Pre-Execution Look-Ahead and Timestamp Audit Report

* **Audit Date**: 2026-07-08
* **Target Files**:
  - `strategies/w4_exit_strategy.py`
  - `backtests/run_w4_backtest.py`
  - `studies/regime_sequence_signal_audit/build_chronology_firewall.py`
  - `studies/regime_sequence_signal_audit/run_session_tests.py`
  - `studies/regime_sequence_signal_audit/build_score_registry.py`
  - `studies/regime_sequence_signal_audit/run_track_a_payoff_aligned.py`
  - `studies/regime_sequence_signal_audit/run_track_b_weakness.py`
  - `studies/regime_sequence_signal_audit/run_parity_validation.py`
  - `studies/regime_sequence_signal_audit/run_mbp1_validation.py`

---

## 1. Executive Summary

A third audit pass was performed on the target files to evaluate the resolution of all prior findings (look-ahead bias, train/serve skew, timestamp conventions, and state machine boundaries) and to ensure overall code robustness.

### Prior Findings Resolution Status:
- **Missing Entry Logic in Live Strategy (Critical 1)**: **RESOLVED**. The strategy `W4ExitStrategy` inherits from `BaselineFlipParityStrategy`, which implements the correct regime-flip entry logic.
- **Missing Predictions Parquet (Critical 2)**: **RESOLVED in design**. `run_track_b_weakness.py` has been updated to generate and write `weakness_checkpoint_predictions.parquet`. However, runtime execution is currently blocked by a new MemoryError (see below).
- **Severe Train/Serve Skew for B3/B5 Exits (Critical 3)**: **RESOLVED**. `W4ExitStrategy` and the offline simulation are now fully aligned. Policy B3 uses a tight stop monitored in the 1-second bar loop, and B5 checks the 5-second checkpoint price against the median center.
- **Timestamp Convention Violation A1 (Warning 1)**: **RESOLVED**. `W4ExitStrategy` correctly uses `ts = bar.ts_init` for the 1-second bar loop to align on bar close times.
- **Checkpoint Skipping (Warning 2)**: **RESOLVED**. Binned check `ts_sec // 5 > self._last_5s_ts` ensures that gaps in 1-second bars do not skip checkpoints.
- **Hardcoded Flip Time Delay (Warning 3)**: **RESOLVED**. The strategy records flip times dynamically via `self._last_flip_ts`.
- **Stale State Variables (Warning 4)**: **RESOLVED**. Reset logic clears all tracking variables when flat in `on_bar`.
- **Lack of Exit Retry/Failure Handling (Warning 5)**: **RESOLVED**. Flat reset logic clears the warning state to `"NORMAL"`, allowing subsequent warning qualification.

### New Findings:
While the prior look-ahead biases and design skews are fully resolved, **3 new CRITICAL runtime bugs** and **2 new WARNINGS** were identified during execution validation. These bugs prevent the scripts and backtest from running to completion.

---

## 2. Detailed Audit Findings

### CRITICAL FINDINGS (NEW)

#### CRITICAL 1: AttributeError in Live Exit Strategy
* **File/Lines**: [w4_exit_strategy.py:L100](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L100) (also [w4_exit_strategy.py:L78](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L78))
* **Description**: The strategy references `self._running_mae` in `on_bar` (lines 78 and 100), but it is never initialized in `__init__`. The parent class `BaselineFlipParityStrategy` only initializes `self._running_mfe` (line 171) and does not define `self._running_mae`.
* **Impact**: The backtest engine crashes with `AttributeError: 'W4ExitStrategy' object has no attribute '_running_mae'` on the first 1-second bar processed after a position is opened.
* **Correction**: Initialize `self._running_mae = 0.0` in the `__init__` method of `W4ExitStrategy` (around line 43).

#### CRITICAL 2: NameError in Track A pay-off model training
* **File/Lines**: [run_track_a_payoff_aligned.py:L41](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/run_track_a_payoff_aligned.py#L41)
* **Description**: The script references `df_all` on line 41 (`df_f2 = df_all[df_all["population"] == "F2"].copy()`) before defining it.
* **Impact**: The Track A model script crashes immediately with a `NameError: name 'df_all' is not defined`.
* **Correction**: Insert `df_all = pd.read_parquet(atlas_path)` on line 40.

#### CRITICAL 3: MemoryError in Track B weakness model training
* **File/Lines**: [run_track_b_weakness.py:L43](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/run_track_b_weakness.py#L43)
* **Description**: The weakness checkpoint atlas dataset has 7,910,451 rows and 172 columns. Calling `.copy()` on the entire dataset requires a contiguous 10.1 GiB numpy array allocation of float64 data.
* **Impact**: The model fitting script crashes with `numpy._core._exceptions._ArrayMemoryError: Unable to allocate 10.1 GiB`. This prevents `weakness_checkpoint_predictions.parquet` from being generated, which in turn blocks the backtest and validation steps.
* **Correction**: Filter the dataframe to only the required feature columns (e.g. `LOCAL_FEATS + CENTER_FEATS + SEQUENCE_FEATS` and keys) *before* invoking `.dropna()` and `.copy()`. This will reduce memory usage by over 90%.

---

### WARNING FINDINGS (NEW)

#### WARNING 1: Unhandled IndexingError in Track B Grid Search Parameter Selection
* **File/Lines**: [run_track_b_weakness.py:L241](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/run_track_b_weakness.py#L241)
* **Description**: The print statement uses chained indexing with unalignable boolean Series: `df_grid[df_grid['theta']==best_theta][df_grid['persistence_N']==best_N]`. 
* **Impact**: The script will crash with an `IndexingError` during parameter selection printout once the memory error is bypassed.
* **Correction**: Use a single combined boolean mask: `df_grid[(df_grid['theta'] == best_theta) & (df_grid['persistence_N'] == best_N)]`.

#### WARNING 2: Missing Exit Order ID Clearing and Limit Order Cancellation in Live Strategy
* **File/Lines**: [w4_exit_strategy.py:L195-207](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L195-L207)
* **Description**: The overridden `_exit_all_market` method in `W4ExitStrategy` does not assign the submitted market order ID to `self._exit_order_id = order.client_order_id.value` or the reason to `self._exit_reason = reason`. Furthermore, it fails to cancel the profit target limit order `self._t_id`.
* **Impact**:
  - The market order fill will not trigger the base class `on_order_filled` logic that calls `_record_trade` (preventing trades from logging in `self.all_trades`).
  - The target limit order `self._t_id` remains active in the exchange order book, risking phantom double-executions if price hits the target after a warning market exit.
* **Correction**: Align the exit logic with the base class implementation by storing the exit order details and cancelling both `self._sl_id` and `self._t_id`.

---

## 3. Checklist Verification

* **A. NautilusTrader timestamp conventions**:
  - **A1**: **Clean** (Correctly uses `bar.ts_init` for indexing).
  - **A2**: **Clean** (Catalog delta shifts are baked in).
  - **A3**: **Clean** (No future-indexed lookups in the strategy).
* **B. Feature engineering look-ahead**:
  - **B1-B7**: **Clean** (Rolling computations and features are strictly causal).
* **C. Label construction**:
  - **C1-C4**: **Clean** (Temporal splits: 2021-2024 train, 2025 validation, 2026 test).
* **D. Train/serve skew**:
  - **D1-D4**: **Clean in design** (Exits match perfectly, but blocked by the predictions parquet file missing due to MemoryError).
* **E. Backtest configuration**:
  - **E4**: **Clean** (Entries execute at the next bar's open).
* **F. Session and time handling**:
  - **F1-F4**: **Clean** (CME session boundaries are verified using unit tests).
* **H. Offline simulation price resolution**:
  - **H1-H4**: **Clean** (Exits use high/low prices on 1s bars and checkpoints use 5s cadence).

---

## 4. Verdict (Pass 3)

### **PASS_WITH_WARNINGS**

*The prior look-ahead biases, session semantics boundary issues, and train/serve exit policy skews are fully resolved in code design. However, the pipeline cannot be run end-to-end until the newly discovered runtime bugs (AttributeError in the strategy, NameError in Track A, and MemoryError/IndexingError in Track B) are corrected.*

---
---

# PASS 4 — Partial-Exit / Multi-Lot Execution Path Audit

* **Audit Date**: 2026-07-08 (pass 4)
* **Scope**: Re-verification of all pass 1-3 findings, plus targeted review of the new partial-exit / multi-lot execution path:
  - `backtests/baseline_flip_parity/strategy.py` (new `entry_qty`, `_exit_partial_market`, blended `_record_trade`)
  - `strategies/w4_exit_strategy.py` (B4 branch calling `_exit_partial_market`)
  - `backtests/run_w4_backtest.py` (`entry_qty=2` threading for B4)
  - `studies/regime_sequence_signal_audit/run_parity_validation.py`, `run_mbp1_validation.py` (documentation-only edits)
* **Method**: Static review plus direct inspection of the installed NautilusTrader 1.221.0 source (`nautilus_trader/trading/trader.py`, `nautilus_trader/backtest/engine.pyx`, `nautilus_trader/risk/engine.pyx`) to resolve ambiguities about exchange-side order sequencing and reduce-only semantics, rather than assuming the benign interpretation. Also inspected the existing (partially-run) backtest artifact at `backtests/results/w4_exit_backtests/NQ_2025_B1/`.

### Re-verification of Pass 1-3 findings
All prior CRITICAL and WARNING findings remain **RESOLVED**:
- `self._running_mae` is now initialized in `W4ExitStrategy.__init__` (w4_exit_strategy.py:43).
- `run_track_a_payoff_aligned.py:40-41` now defines `df_all = pd.read_parquet(atlas_path)` before use.
- `run_track_b_weakness.py` now reads the atlas with `columns=cols_to_load` (pre-filtered) instead of loading all 172 columns, and downcasts to float32 — the MemoryError is resolved. Confirmed by evidence: `studies/regime_sequence_signal_audit/results/weakness_checkpoint_predictions.parquet` exists (221 MB, generated today), i.e. this script has actually completed a full run.
- `run_track_b_weakness.py:255` now uses a single combined boolean mask (`(df_grid['theta']==best_theta) & (df_grid['persistence_N']==best_N)`) instead of chained indexing — the IndexingError is resolved.
- The W4-specific override of `_exit_all_market` that previously failed to set `self._exit_order_id`/`self._exit_reason` and failed to cancel `self._t_id` has been **removed entirely** from `w4_exit_strategy.py`. `W4ExitStrategy` now inherits the base class's `_exit_all_market` directly, which is qty-aware and correctly manages both `_sl_id` and `_t_id`. Pass-3 Warning 2 is resolved as a side effect of this refactor.

---

## CRITICAL FINDINGS (Pass 4, new)

### CRITICAL 4 (E): `run_w4_backtest.py:133` calls a Trader method that does not exist — every backtest run crashes before producing output
* **File/Lines**: [run_w4_backtest.py:L133](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/run_w4_backtest.py#L133)
* **Description**: `trades = engine.trader.generate_trades_report()`. The installed `nautilus_trader` package (v1.221.0, `nautilus_trader/trading/trader.py:814-876`) exposes only `generate_orders_report`, `generate_order_fills_report`, `generate_fills_report`, `generate_positions_report`, and `generate_account_report`. There is no `generate_trades_report` method anywhere in the installed package (confirmed via source grep) and no local monkey-patch or shim defines one.
* **Impact**: Every invocation of `run_w4_backtest.py`, for every policy (B0-B5), will run the full backtest to completion and then crash with `AttributeError` on the very next line, before `trades.parquet` is ever written. This is corroborated directly by the existing artifact directory `backtests/results/w4_exit_backtests/NQ_2025_B1/`, which contains only a `logs/` subdirectory (two prior run attempts) and no `trades.parquet` — and by the log content itself, which shows a complete, correctly-functioning B1 trade sequence (entries, fills, SL/target brackets, cancellations) all the way through, consistent with a crash occurring only at the final report-generation step, after all compute cost has already been paid.
* **Consequence for this audit**: because this script has never completed successfully, none of the B4 partial-exit / multi-lot logic reviewed below has been observed to run end-to-end against real data — the analysis below is necessarily static-analysis-only (backed by direct NT source inspection), not confirmed by an actual completed B4 run's trade log. This must be re-verified once the bug is fixed.
* **Correction**: Replace with `engine.trader.generate_positions_report()` (NT's own per-position report, carrying real `avg_px_open`/`avg_px_close`/`realized_pnl` computed natively from actual fills — arguably a better source of truth for this study than the strategy's own manual `all_trades` bookkeeping) or assemble an equivalent from `generate_order_fills_report()`.

---

## WARNING FINDINGS (Pass 4, new)

### WARNING 3 (E4/H): Same-bar race between the base-class max-hold exit and the child-class 5s-checkpoint policy exit (B1/B4)
* **File/Lines**: [backtests/baseline_flip_parity/strategy.py:222-227](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L222-L227), [strategies/w4_exit_strategy.py:83-115](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L83-L115), [strategies/w4_exit_strategy.py:178-188](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L178-L188)
* **Description**: `W4ExitStrategy.on_bar` calls `super().on_bar(bar)` (which contains the base class's max-hold check and calls `_exit_all_market("max_hold")` if `ts - self._entry_ts >= MAX_HOLD_NS`) and *then*, later in the same callback, evaluates `if self._entry_px is not None and not self.portfolio.is_flat(...)` before calling `_process_5s_checkpoint` (which can call `_exit_all_market("W4_B1_exit")` or `_exit_partial_market(..., "W4_B4_partial_exit")`). Because an order submitted mid-`on_bar` only fills on the *next* bar (confirmed general NT/backtest semantics, also documented in this repo's own E4 convention), `self.portfolio.is_flat()` is still `False` for the remainder of the *current* callback even though a max-hold exit order was just submitted moments earlier. If a B1/B4 warning streak also concludes in that same bar, a *second*, independent reduce-only order gets submitted against the same position in the same window.
* **Investigation**: Traced through the installed NT engine source (`nautilus_trader/backtest/engine.pyx:5447-5461` and `:5912-5961`). Two safety nets exist: (1) reduce-only order fills are clipped to the *actual* open position quantity at fill time and refuse to fill at all once the position is flat (no over-close, no flip to the opposite side is possible), and (2) standalone reduce-only sibling orders (no `parent_order_id` — true of this strategy's SL/target orders) are automatically resynced by the exchange to the live position quantity, and auto-cancelled once flat, after every fill on that position. In the specific interleavings traced, this prevents an over-close or negative-quantity outcome. However: (a) this has not been exhaustively verified for every possible ordering the `bar_adaptive_high_low_ordering` model can produce, particularly gap-through bars where the open itself already satisfies a stop trigger; (b) it produces a genuine dangling/stale `_partial_exit_order_id` or duplicate order submission in the race case (see Warning 5); and (c) it has never been observed in an actual completed run (blocked by Critical 4).
* **Correction**: Add a single shared "exit already in flight" guard (e.g. `self._exit_pending_cid`) checked by *both* the base class's max-hold branch and the child class's checkpoint-driven policy branches, so at most one exit order is ever submitted per position per bar.

### WARNING 4 (H4): SL/target fill handlers trust `self._remaining_qty`, not the actual fill quantity
* **File/Lines**: [backtests/baseline_flip_parity/strategy.py:527-543](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L527-L543)
* **Description**: The `cid == self._t_id` and `cid == self._sl_id` branches of `on_order_filled` call `self._record_trade(reason, event.ts_event, px)`, and `_record_trade` weights the blended PnL using `self._remaining_qty` (a strategy-tracked value) rather than `int(event.last_qty)` (the exchange's actual reported fill quantity). By contrast, the `cid == self._partial_exit_order_id` branch correctly reads `filled_qty = int(event.last_qty)`. In ordinary operation these always agree, because the exchange keeps standalone reduce-only sibling order quantities synced to the live position (see Warning 3's investigation) — but this has not been proven to hold under every ordering the Warning 3 race can produce, and relying on an internally-tracked assumption rather than the event's own ground truth is a fragile pattern for a value that directly drives reported PnL.
* **Correction**: Use `int(event.last_qty)` (falling back to `self._remaining_qty` only if `last_qty` is unavailable) when weighting the final leg in `_record_trade`, for consistency with the partial-exit branch and defense against any future race.

### WARNING 5 (E): No rejection/cancellation handling for the partial-exit order; `_warning_state` advances unconditionally
* **File/Lines**: [strategies/w4_exit_strategy.py:178-188](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L178-L188), [backtests/baseline_flip_parity/strategy.py:615-626](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L615-L626)
* **Description**: `on_order_rejected` / `on_order_canceled` / `on_order_expired` only clear `self._pending_entry`; none of them clear `self._partial_exit_order_id` / `self._partial_exit_reason`. Meanwhile, `_process_5s_checkpoint`'s B4 branch sets `self._warning_state = "ACTION_TAKEN"` immediately after calling `_exit_partial_market(...)`, unconditionally — i.e. regardless of whether that order is ultimately accepted, filled, rejected, or cancelled. If the partial-exit order is ever rejected (e.g. denied by the risk engine's reduce-only pre-check for any reason not currently anticipated) or races to zero fill (Warning 3), the position remains fully open at its original size while the state machine believes the B4 risk-reduction action has already happened, permanently skipping any further warning-driven action for that trade with no error surfaced. This is the same class of bug that pass 3's "Warning 5" fixed for the original `_exit_order_id`, but the fix was not extended to the new `_partial_exit_order_id`.
* **Correction**: Clear `_partial_exit_order_id` / `_partial_exit_reason` in `on_order_rejected` / `on_order_canceled` / `on_order_expired`, and consider only transitioning `_warning_state` to `"ACTION_TAKEN"` once the partial-exit fill actually confirms (in the `on_order_filled` branch), not at submission time.

### WARNING 6 (D2/G): Blended-PnL formula does not model commission; latent double-round-trip cost for B4 trades
* **File/Lines**: [backtests/baseline_flip_parity/strategy.py:23](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L23), [backtests/baseline_flip_parity/strategy.py:662-687](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L662-L687)
* **Description**: `COMM_RT = 5.0` is defined at module scope but is never referenced anywhere else in the file — commission is not modeled in `_record_trade`'s PnL calculation at all, for single-leg or blended trades. This is a pre-existing gap, not introduced by this diff, but the diff makes it more consequential: a genuine 2-lot B4 trade with a partial exit involves 4 contract-sides of real execution (2 in at entry, 1 out at the partial exit, 1 out at the final exit) versus 2 contract-sides for a normal 1-lot round trip, so real commission (once modeled) would be roughly double for these trades specifically — information not currently recoverable from `all_trades`. Confirmed via the `NQ_2025_B1` backtest log that the venue currently has **no fee model configured** (every `OrderFilled` event shows `commission=0.00 USD`), so this gap is presently inert for both the manual bookkeeping and NT's own portfolio PnL — but whichever report is substituted to fix Critical 4 (e.g. `generate_positions_report`) will also show $0 commission until a fee model is added, and the per-leg-vs-blended economics question raised for this pass remains unresolved/untested rather than confirmed-safe.
* **Correction**: When/if a fee model is added to the venue config, verify `_record_trade`'s blended formula (or the substituted `generate_positions_report`/`generate_order_fills_report` path) correctly reflects per-fill commission rather than a flat per-trade assumption, particularly for B4's extra contract-sides.

---

### CLEAN (Pass 4, confirmed via NT source and static trace)
- **H4 (fill price for partial and final legs)**: Both `self._partial_leg_px` (set from the partial order's actual `event.last_px`) and the final leg's `exit_px` (from each terminal branch's own `event`-derived `px`) use real NT fill prices — no phantom trigger-price crediting for either leg of a B4 trade.
- **Over-close / reduce-only clipping**: Confirmed via `nautilus_trader/backtest/engine.pyx:5447-5461` — reduce-only order fills are clipped to the actual open position size at match time and refuse to fill once the position is already flat; the partial-exit order cannot cause an over-close or a flip to the opposite side even if `qty >= open position size` due to a bug elsewhere.
- **Reduce-only auto-resync**: Confirmed via `nautilus_trader/backtest/engine.pyx:5912-5961` — the exchange itself automatically resyncs standalone reduce-only sibling orders (the SL/target pair here, which have no `parent_order_id`) to the live position quantity after every fill, and auto-cancels them once flat, independent of the strategy's own manual cancel/resubmit in the `_partial_exit_order_id` branch.
- **State-machine interaction after a B4 partial exit**: The flat-reset guard at the top of `on_bar` (`if self.portfolio.is_flat(...) and self._entry_px is not None`) correctly does **not** fire after a B4 partial exit, because `self._remaining_qty > 0` keeps `portfolio.is_flat()` `False`. MFE/MAE tracking and the 5s-checkpoint loop both correctly continue for the remaining leg (guarded on `self._entry_px is not None and not self.portfolio.is_flat(...)`, both still true), and the state machine's lack of an `elif self._warning_state == "ACTION_TAKEN"` branch correctly prevents B4 (or any other policy) from re-triggering on the same trade.
- **`entry_qty` threading**: No hardcoded `Quantity.from_int(1)` remains anywhere in `backtests/baseline_flip_parity/strategy.py`; all order sizing now derives from `self._remaining_qty` / `self._cfg.entry_qty`. `run_w4_backtest.py:112` correctly sets `entry_qty=2` only when `policy == "B4"`.
- **Backward compatibility for other studies**: `backtests/baseline_flip_parity/run_backtest.py` (the runner used by other, non-W4 studies sharing this strategy file) never passes `entry_qty`, so it always uses the default of `1`. `_partial_leg_qty` therefore stays `0` for every trade that runner produces, and the new blended-PnL branch in `_record_trade` is unreachable/dead code for those studies — **no regression risk to previously-validated results** from other studies that depend on this file.
- **Item 4 (parity/MBP-1 script edits)**: Confirmed the tautological self-comparison (`offline_w4_prob` vs itself) has been genuinely removed from `run_parity_validation.py`, which now documents (lines 38-48) that it validates causal-feature parity only, not an independent online score. `run_mbp1_validation.py` is honestly relabeled throughout as a "slippage sensitivity check, NOT real MBP-1 validation," with explicit acknowledgment that the catalog has no `quote_tick`/`trade_tick` data. The renamed output `slippage_sensitivity_report.md` is not referenced under any old filename anywhere else in the study directory (grep-confirmed).

### NOTE (Pass 4)
* **Redundant cancel+resubmit vs. exchange auto-resync**: The strategy's explicit cancel-then-resubmit of SL/target orders in the `_partial_exit_order_id` branch is redundant with the exchange's own automatic reduce-only resync (see Clean checks above). Not incorrect, just doubles the number of order messages per partial exit; could be simplified to rely on the exchange's auto-resync if fills/orders-report noise becomes a concern.
* **Spec-vs-implementation mismatch for B0 baseline (surfaced per user request, no remediation this pass)**: The study's plan text defines policy **B0 (Baseline)** as "exit on opposite regime flip." Confirmed by direct reading of `BaselineFlipParityStrategy.on_bar` (`backtests/baseline_flip_parity/strategy.py:412-416`): the opposite-regime-flip exit only executes when `elif not self.portfolio.is_flat(self._inst_id) and self._cfg.use_stall_protection:` — i.e. only when `use_stall_protection=True`. Both `BaselineFlipParityConfig` and `W4ExitConfig` default `use_stall_protection=False`, and `run_w4_backtest.py` never overrides it. There is also no B0-specific branch anywhere in `W4ExitStrategy._process_5s_checkpoint`. **Confirmed**: the actual B0 exit for this study is the fixed 1.0-ATR stop-loss / 1.0-ATR target bracket (`sl_atr=1.0`, `tp_atr=1.0` defaults) plus the 4-hour `MAX_HOLD_NS` timer — not opposite-regime-flip. This changes what "lift over B0 baseline" means for every other policy comparison (B1-B5 are being compared against a bracket-exit baseline, not a regime-exit baseline). Flagging only, per instructions — no code change made.

---

## Verdict (Pass 4)

### **FAIL**

*Rationale*: The partial-exit / multi-lot execution logic itself is, by static analysis and direct NT source inspection, largely sound — NT's own reduce-only clipping and auto-resync mechanisms protect against the over-close and stale-bracket scenarios that were the primary concern for this pass, and the state-machine interaction after a B4 partial exit is correct. However, `backtests/run_w4_backtest.py:133` calls `engine.trader.generate_trades_report()`, a method that **does not exist** in the installed NautilusTrader version — every backtest run for every policy (B0-B5) crashes immediately after `engine.run()` completes and before any trade data is saved. This is corroborated by an existing partial-run artifact containing logs but no `trades.parquet`. No policy, including B4, has produced verifiable end-to-end output, so none of this pass's static findings on the partial-exit path have been confirmed against a real completed run. **This CRITICAL must be fixed, and at least one full B4 run must complete and be spot-checked (including verifying no B4 trade shows the Warning 3/4/5 race symptoms), before this pipeline can be declared PASS.** WARNING 3, 4, 5, and 6 should also be addressed per CLAUDE.md's audit-gate policy before the study's results are used for decisions; NOTE items are informational only.

---
---

# PASS 5 — Verification of Critical-4 / Warning-3/4/5 Fixes

* **Audit Date**: 2026-07-08 (pass 5)
* **Scope**: Re-verification of the 4 fixes applied since pass 4:
  - `backtests/run_w4_backtest.py` (`generate_positions_report()` swap, `strategy_trades.parquet` save)
  - `backtests/baseline_flip_parity/strategy.py` (`_record_trade(..., exit_qty)`, `on_order_rejected/canceled/expired`)
  - `strategies/w4_exit_strategy.py` (`_is_exit_action_order`, override of the three order-outcome handlers, flat-reset extension)
* **Method**: Static review plus direct inspection of installed NautilusTrader 1.221.0 source (`nautilus_trader/trading/trader.py`, `nautilus_trader/analysis/reporter.py`, `nautilus_trader/cache/cache.pyx`, `nautilus_trader/model/position.pyx`) to resolve the same class of ambiguity as pass 4 — i.e. what `generate_positions_report()` actually returns and how NT's own `Position` accounts for partial-fill realized PnL — rather than assuming the benign interpretation.

## Item 1 — CRITICAL 4 fix (`generate_trades_report` to `generate_positions_report`)

**Crash resolved: CONFIRMED.** `nautilus_trader/trading/trader.py:847` defines `generate_positions_report`; `generate_trades_report` is confirmed absent anywhere in the installed package (grep-confirmed again this pass). The AttributeError is gone.

**Appropriateness as an economics source: CONFIRMED, with one new caveat.** Traced `Trader.generate_positions_report` to `ReportProvider.generate_positions_report(cache.positions(), cache.position_snapshots())` (`nautilus_trader/analysis/reporter.py:117`) to `Position.to_dict()` (`nautilus_trader/model/position.pyx:177-212`). Confirmed in `position.pyx:721-781` that `Position` correctly accumulates `realized_pnl` across **multiple partial closing fills** (each partial close adds `_calculate_pnl(avg_px_open, last_px, last_qty)` to a running `Money` total, and `avg_px_close` is itself a running weighted average via `_calculate_avg_px_close_px`). For a B4 trade (2-lot entry, 1-lot partial exit, 1-lot final exit), this means NT's own position accounting produces a single, correctly quantity-weighted realized PnL for the whole round-trip — a source at least as authoritative as, and independent of, the strategy's own hand-rolled blend in `_record_trade`, exactly as the pass-4 recommendation anticipated.

### NEW WARNING (Pass 5, Item 1): `trades.parquet` can include a still-OPEN position with partial/misleading fields
* **File/Lines**: [run_w4_backtest.py:L134](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/run_w4_backtest.py#L134)
* **Description**: `Trader.generate_positions_report` sources its `positions` list from `self._cache.positions()` (`trader.py:856`), which — confirmed via `cache.pyx:5046-5076` vs. the separate, unused `cache.positions_closed()` at `cache.pyx:5110` — returns **all** positions regardless of open/closed state, not just closed ones. `Position.to_dict()` (`position.pyx:202,205,211`) reports `ts_closed`/`closing_order_id` as `None` while open, but `avg_px_close`/`realized_pnl` as **non-null** as soon as *any* partial closing fill has occurred (they reflect only the completed partial leg(s), not a final round-trip). `BacktestEngine.run()` does not auto-flatten open positions on completion (no `close_positions_on_stop`/`flatten` call anywhere in this pipeline). Since `load_end` is `{year}-12-31 23:59:59` and entries occur up to that boundary, a trade opened near year-end (B4 in particular, where a partial exit can legitimately occur before the position is scheduled to fully close) can plausibly still be open when `engine.run()` returns.
* **Impact**: `trades.parquet` may silently contain 0-1 rows per (year, policy) run that look like completed trades (non-null `avg_px_close`, non-null `realized_pnl`) but are actually partial/incomplete — `realized_pnl` reflects only the partial leg, not the true final PnL. Any downstream economics analysis that sums or averages `realized_pnl` from this file without filtering will silently include this row as if it were a closed trade.
* **Correction**: Filter to `trades[trades["ts_closed"].notna()]` (equivalently `closing_order_id.notna()`) before using `trades.parquet` for per-trade economics; do not rely on `avg_px_close`/`realized_pnl` non-nullness as a closed-position proxy, since both can be populated by a partial fill on an otherwise still-open position.

## Item 2 — Warning 4 fix (blended PnL uses actual `event.last_qty`)

**RESOLVED, verified correct.** All three terminal `on_order_filled` branches (`strategy.py:534`, `543`, `549`) now pass `int(event.last_qty)` explicitly into `_record_trade`. The `_partial_exit_order_id` branch (`strategy.py:551-587`) is confirmed to never call `_record_trade` — it only updates `_partial_leg_qty`/`_partial_leg_px`/`_remaining_qty` and resubmits the reduced-size bracket, exactly as claimed. `_record_trade`'s default (`exit_qty: int | None = None`, falling back to `self._remaining_qty`, `strategy.py:683-687`) is therefore genuinely dead code today (no live caller omits `exit_qty`) — safe, but worth a NOTE that it will silently mask a future bug if a new caller ever *does* omit it, since the fallback has no assertion that `self._remaining_qty` still agrees with reality.

Weighting math (`strategy.py:688-699`) checked dimensionally: `pnl_pts` and `blended_exit_px` are quantity-weighted **per-contract** values (`total_qty = self._partial_leg_qty + final_qty`, always equal to `entry_qty` for a fully-closed B4 trade), consistent with the per-contract semantics of the non-blended (`_partial_leg_qty == 0`) branch — so B4 (2-lot) trades remain directly comparable to 1-lot B0/B1/B2/B3/B5 trades in `exit_pnl_pts`/`exit_pnl_atr`. No bug found.

## Item 3 — Warning 5 fix (partial-exit rejection/cancellation handling)

**Ordering: CONFIRMED CORRECT, no use-after-clear bug.** `W4ExitStrategy._is_exit_action_order` (`w4_exit_strategy.py:206-209`) is called and its result captured (`was_exit_action`) **before** `super().on_order_rejected/canceled/expired(event)` runs (`w4_exit_strategy.py:211-230`), and the base class clears `_exit_order_id`/`_partial_exit_order_id` to `None` inside that `super()` call (`strategy.py:615-646`) — so the cid comparison always happens against the still-populated id. No double-clearing, no use-after-clear.

### NEW WARNING (Pass 5, Item 3): revert-to-QUALIFIED does not actually re-arm B1 or B4
* **File/Lines**: [w4_exit_strategy.py:L162-190](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L162-L190) (state machine) vs. [w4_exit_strategy.py:L211-230](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L211-L230) (revert-to-QUALIFIED)
* **Description**: `_process_5s_checkpoint`'s `elif self._warning_state == "QUALIFIED":` branch (`w4_exit_strategy.py:192-204`) only contains cases for policies **B2** and **B5** — these are persistent, per-checkpoint re-evaluated conditions, so reverting `ACTION_TAKEN -> QUALIFIED` after a rejection/cancel genuinely re-arms them (the next checkpoint re-checks the same threshold and, if still true, resubmits — this is a real, correct retry). **B1**'s exit and **B4**'s partial exit, by contrast, only fire once, inside the `if self._warning_state == "NORMAL":` block at the moment `_warn_streak` first crosses `N` (`w4_exit_strategy.py:169-190`). Once state is QUALIFIED — whether via a fresh transition or via this pass's rejection-recovery revert — the code can never re-enter that `NORMAL` block's action logic for the same trade (there is no B1/B4 case under the QUALIFIED `elif`). B3's tight-stop breach check is unaffected (it lives in the 1-second `on_bar` handler gated on `_warning_state == "QUALIFIED"`, `w4_exit_strategy.py:106-111`, so it correctly re-fires on the next 1s bar regardless of transition history).
* **Impact**: If a B1 or B4 exit/partial-exit market order is ever rejected, canceled, or expires, the position is left permanently unmanaged for the rest of the trade — state parks at `QUALIFIED` with no further action, exactly the failure mode this fix was intended to close, silently reproduced for 2 of the 4 affected policies.
* **Correction**: Add explicit `B1`/`B4` cases under the `elif self._warning_state == "QUALIFIED":` block in `_process_5s_checkpoint` (`w4_exit_strategy.py:192`), mirroring B2/B5's persistent-recheck pattern, e.g. re-attempt `_exit_all_market("W4_B1_exit")` / `_exit_partial_market(half_qty, "W4_B4_partial_exit")` on every QUALIFIED checkpoint until it actually fills.

### ESCALATION of Pass-4 Warning 3: same-bar race can silently drop a trade record (not just duplicate an order)
* **File/Lines**: [strategy.py:L648-663](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L648-L663) (`_exit_all_market`), [strategy.py:L545-549](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L545-L549) (`on_order_filled` `_exit_order_id` branch), [w4_exit_strategy.py:L73-82](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L73-L82) (flat-reset)
* **Description**: Traced through the specific mechanics of pass 4's Warning 3 race (base-class max-hold exit vs. child-class checkpoint exit firing in the same bar) for the subset of policies (B1, B2, B3, B5) whose checkpoint action calls the shared `_exit_all_market`. `_exit_order_id`/`_exit_reason` are single scalars, not a set — a second `_exit_all_market` call in the same bar **overwrites** tracking of the first order before its fill event has arrived. When the first order's `OrderFilled` event later arrives, no `elif cid ==` branch in `on_order_filled` matches it anymore (the id now points to the second order), so `_record_trade` is silently skipped for that leg — the real, filled trade is dropped from `self.all_trades`/`strategy_trades.parquet` entirely. The second order, submitted against an already-flat position, is expected to be clipped/auto-canceled per pass 4's own investigation of NT's reduce-only resync — its `on_order_canceled` fires, matching the (now current) `_exit_order_id`, reverting `_warning_state` to `QUALIFIED` per this pass's fix.
* **Bounding check performed this pass**: traced whether this produces an infinite retry loop. It does not — `self.portfolio.is_flat()` reflects the true venue-side state (already flat from the first order's fill), so the flat-reset block at the top of `on_bar` (`w4_exit_strategy.py:74`) fires on the very next 1-second bar and resets `_entry_px = None`/`_warning_state = "NORMAL"`, bounding the damage to a single wasted retry attempt, not a loop.
* **Impact**: the trade is still economically captured correctly in NT's own `generate_positions_report()` output (fill-based, independent of strategy bookkeeping — see Item 1), but is **silently missing** from `strategy_trades.parquet`, creating an undetected row-count/PnL divergence between the two report files specifically for trades hit by this race. Since this pass confirmed `strategy_trades.parquet` is the file that captures "the exact economics used by the W4 policies" (run_w4_backtest.py:139-143), any analysis that trusts it exclusively (rather than cross-checking against `trades.parquet`) would silently under-count affected trades.
* **Correction**: unchanged from pass 4 — add a single shared "exit already in flight" guard checked by both the base class's max-hold branch and the child class's checkpoint-driven branches so at most one `_exit_all_market`/`_exit_partial_market` call happens per position per bar. This also resolves the newly-traced silent-drop consequence, since it prevents the clobbering at its source.

## Item 4 — flat-reset now also clears `_partial_exit_order_id`/`_partial_exit_reason`

**Ordinary (non-race) case: CONFIRMED CORRECT.** By construction, a partial exit leaves `_remaining_qty > 0`, so `portfolio.is_flat()` is `False` until the *final* exit fills — meaning in normal operation, by the time the flat-reset condition is true, any partial-exit order must have already resolved (filled, since `_partial_exit_order_id` is cleared to `None` on fill at `strategy.py:552`), so this addition is inert/defensive in the common path, exactly as described.

### WARNING (Pass 5, Item 4, pending same investigation as Warning 3): flat-reset could null a genuinely in-flight partial-exit id
* **File/Lines**: [w4_exit_strategy.py:L74-82](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L74-L82)
* **Description**: In the Warning-3 race scenario specifically — a competing exit (e.g. max_hold) closes the position fully in the *same bar* a B4 partial-exit order was just submitted, before that partial-exit order's own fill/cancel event has been processed — the flat-reset block would now clear `self._partial_exit_order_id = None` pre-emptively on the next bar, before the partial order's own outcome event arrives. If that event is a fill (not impossible if the reduce-only clip lets a residual quantity through before the position fully zeroes), the same "unmatched cid, `_record_trade`/leg update silently skipped" failure mode described in the escalated Warning 3 applies here too, specific to the partial leg. This is genuinely ambiguous without a precise trace of NT's event-dispatch ordering between `OrderFilled` events and the next `on_bar` call within the same backtest tick — not independently resolved this pass.
* **Correction**: resolve jointly with the Warning 3 "exit already in flight" guard recommended above; no separate fix needed if that guard prevents the underlying same-bar dual-exit race from occurring at all.

## Re-confirmation of items not touched this pass

* **`entry_qty` threading**: unchanged and still correct — no hardcoded `Quantity.from_int(1)` in `strategy.py`; `run_w4_backtest.py:112` still sets `entry_qty=2` only for B4.
* **B0-vs-plan-text definitional mismatch**: unchanged since pass 4 (no remediation requested or made this pass); not re-flagged as new, carried forward as a documented, accepted note.
* **Parity / MBP-1 script edits** (`run_parity_validation.py`, `run_mbp1_validation.py`): no further changes observed since pass 4; still clean per pass 4's findings.
* **Warning 6 (commission not modeled, `COMM_RT` unused)**: unaddressed, unchanged, not part of this pass's requested fixes. Still outstanding — will still apply to whichever report (`trades.parquet` or `strategy_trades.parquet`) is used for economics once/if a fee model is ever configured.

## Verdict (Pass 5)

### **PASS_WITH_WARNINGS**

*Rationale*: The blocking CRITICAL from pass 4 (`generate_trades_report` AttributeError) is genuinely resolved — the pipeline can now run to completion and produce output for the first time. Item 2 (blended-PnL weighting) is fully and correctly resolved with no residual issues. Items 3 and 4, however, are **incompletely** resolved: the rejection/cancellation recovery mechanism only actually re-arms policies B2/B3/B5, not B1/B4 (new, specific finding, WARNING), and the underlying same-bar exit race from pass 4's Warning 3 — while confirmed *not* to cause an infinite loop or an over-close — was traced this pass to a previously undocumented silent-trade-record-loss consequence for `strategy_trades.parquet` specifically (WARNING, escalation of Warning 3). A new WARNING was also found in Item 1's fix itself: `trades.parquet` can include a trailing still-open position with misleading non-null `avg_px_close`/`realized_pnl` fields unless explicitly filtered on `ts_closed`.

**Recommendation before treating results as trustworthy**: (1) fix the B1/B4 QUALIFIED-branch retry gap, (2) implement the single shared "exit in flight" guard (resolves both the Warning 3 escalation and the Item 4 pending question in one change), (3) filter `trades.parquet` to closed positions only in any downstream analysis script, (4) then run at least one full B4 backtest end-to-end and spot-check that `trades.parquet` and `strategy_trades.parquet` agree on trade count and PnL per trade, per pass 4's original mandate — this has still never been observed against a real completed run.

---
---

# PASS 6 — Final Pre-Execution Verification (Fixes 1-3) + Holistic Diff Review

* **Audit Date**: 2026-07-08 (pass 6)
* **Scope**: Re-verification of the 3 fixes applied since pass 5, plus a full holistic re-read of all three files ahead of the intended full B0-B5 x {2025, 2026} execution:
  - `strategies/w4_exit_strategy.py` (`_fire_immediate_exit`, B1/B4 QUALIFIED-retry case)
  - `backtests/baseline_flip_parity/strategy.py` (`_exit_all_market`/`_exit_partial_market` shared "exit in flight" guard)
  - `backtests/run_w4_backtest.py` (`ts_closed.notna()` filter)
* **Method**: Static review, plus (because Item 1's correctness and — as it turned out — the entire child-class state-reset mechanism both hinge on the exact dispatch order between `on_order_filled` and `on_bar` for a fill generated by the same bar, and that ordering could not be conclusively read out of the installed package's Cython source since the actual matching internals are pyo3/Rust-backed) an executable diagnostic probe: a minimal synthetic `BacktestEngine` run (temp script, not part of the repo, scratchpad-only, no pipeline files touched) using the same venue settings as `run_w4_backtest.py` (`bar_execution=True, bar_adaptive_high_low_ordering=True`), a toy instrument, 7 synthetic 1-second bars, a market-buy entry, and a resting reduce-only stop that the 5th bar's low is engineered to breach. Every `on_bar` and `on_order_filled` call was logged with its bar/event timestamp so the true interleaving could be read directly off actual engine output rather than assumed.

## Item 1 - B1/B4 QUALIFIED-retry (`_fire_immediate_exit`)

**(a) CONFIRMED CORRECT in isolation.** Once `_fire_immediate_exit` successfully submits (or is guard-no-oped, see Item 2) and sets `_warning_state = "ACTION_TAKEN"`, the next checkpoint's `elif self._warning_state == "QUALIFIED":` branch (`w4_exit_strategy.py:180`) no longer matches, so it correctly stops re-firing every 5s for that trade. (This confirmation is subsequently made largely moot by the CRITICAL finding below - state does not reliably stay scoped to "that trade".)

**(b) WARNING - not literally infinite, but unbounded-until-max-hold repeated resubmission is possible under a persistent rejection cause.** `on_order_rejected`/`canceled`/`expired` clear `_exit_order_id`/`_partial_exit_order_id` (base class) before reverting `_warning_state` to `QUALIFIED` (child class), confirmed via direct read of `w4_exit_strategy.py:219-243` - so no stale id blocks the retry, and `self.portfolio.is_flat()` is verified true only once the position is actually closed by some mechanism. In isolation, absent the state-bleed bug, a persistent rejection cause (e.g. a config-level reduce-only violation that reproduces every time) would cause `_fire_immediate_exit` to resubmit every 5 seconds for as long as the position remains open - bounded by `MAX_HOLD_NS` (4 hours = up to 2,880 retries) rather than truly unbounded, and each retry is a fresh, independent order (no reentrancy/stack-growth risk). Not a correctness bug per se (no order ever double-fills), but worth confirming no such persistent rejection cause actually exists in this venue/instrument configuration before treating a low trade count as evidence of anything other than a rejection loop.

## Item 2 - shared "exit in flight" guard (`_exit_all_market` / `_exit_partial_market`)

**CONFIRMED: resolves the pass-5 escalated trade-record-drop.** Both guards now return immediately if `_exit_order_id is not None or _partial_exit_order_id is not None` (`strategy.py:653`, `:681`), before touching either id - so a second call in the same bar can no longer overwrite tracking of a first, still-pending order. Traced the on_order_filled dispatch for the original order once its fill event arrives: `elif cid == self._exit_order_id:` still matches (id untouched by the no-oped second call), so `_record_trade` fires correctly. Confirmed fixed.

**CONFIRMED: eliminates the specific dual-strategy-initiated-exit race from pass 4/5 Warning 3 and closes pass 5 Item 4's pending question**, for calls that go through `_exit_all_market`/`_exit_partial_market` themselves (base-class max-hold vs. child-class checkpoint exit can now never both have live orders in flight simultaneously - whichever calls first "wins" the guard, the second is a no-op).

**NEW WARNING (residual, narrower than before): the guard does not create mutual exclusion with the passively-resting SL/target bracket orders.** `_sl_id`/`_t_id` orders sit at the exchange independent of this guard and can fill on their own schedule. If an SL (sized at the full `_remaining_qty`, since a smaller bracket is only resubmitted after a partial-exit fill confirms) fires in the same window a partial-exit market order is genuinely in flight, per pass 4's own confirmed exchange-side reduce-only clipping/auto-resync this cannot over-close or produce a negative quantity - but the strategy's own `_partial_exit_order_id` tracking can be left referencing an order that the exchange itself later auto-cancels (now oversized vs. the already-flat position) rather than fills. `on_order_canceled` for that stale id would then still fire `was_exit_action = True` and, if `_warning_state` happened to be `ACTION_TAKEN`, revert it to `QUALIFIED` - for a trade that is already fully closed via the SL. This directly feeds the cross-trade bleed CRITICAL below (a `QUALIFIED` state left behind after the position is already flat). Not independently fixed this pass; folds into the same recommended fix.

**NEW WARNING (bounded, ~1 bar): guard can transiently swallow a genuinely-needed base-class max-hold exit if a still-pending policy exit is later rejected.** Because `super().on_bar(bar)` (max-hold check) always runs before the child's checkpoint logic within a single `on_bar` call, and the guard is now shared, a max-hold exit attempted while a policy exit is still pending will no-op. If that pending order is subsequently rejected, `_exit_order_id` clears and `MAX_HOLD_NS` is still exceeded on the very next 1-second bar, so the gap self-heals within about 1 second - not a permanent failure to close - but this is a newly-introduced interaction that did not exist before the shared guard and is not covered by any test.

## Item 3 - `trades.parquet` filtered to closed positions only (`run_w4_backtest.py:135-140`)

**CONFIRMED RESOLVED, CLEAN.** Matches pass 5's exact recommendation (`trades[trades["ts_closed"].notna()]`). No further issue found.

---

## CRITICAL (Pass 6, NEW): the `on_bar` flat-reset block is unreachable dead code - `_warning_state`, `_warn_streak`, `_running_mae`, and `_tight_stop` never reset between trades, for the entire life of every backtest

* **File/Lines**: [w4_exit_strategy.py:L72-83](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/strategies/w4_exit_strategy.py#L72-L83) (the reset block, unchanged since pass 3) vs. [backtests/baseline_flip_parity/strategy.py:L692-735](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L692-L735) (`_record_trade`, called from `on_order_filled`)

* **Description**: `W4ExitStrategy.on_bar`'s very first statement is `if self.portfolio.is_flat(self._inst_id) and self._entry_px is not None:` - intended (per its own comment, "Warning 4 and Warning 5 mitigation") to fire exactly once, on the first bar after a position closes, resetting `_warning_state`, `_warn_streak`, `_running_mfe`, `_running_mae`, `_tight_stop`, `_partial_exit_order_id`, `_partial_exit_reason`. But every terminal exit path (`T`, `SL`, `_exit_order_id`) calls `_record_trade` directly from `on_order_filled`, and `_record_trade` unconditionally sets `self._entry_px = None` (`strategy.py:722`) as part of the same synchronous call that closes the position. The flat-reset block's guard therefore requires `_entry_px is not None`, but by the time any subsequent `on_bar` call can observe `is_flat() == True`, `_entry_px` has already been nulled by the fill event that caused the flat state - if `on_order_filled` is dispatched before `on_bar` for the same bar.

* **Empirical verification (not assumed)**: Built and ran a minimal diagnostic `BacktestEngine` reproduction (synthetic instrument, 7 one-second bars, market-buy entry plus resting reduce-only stop breached by bar index 4's low) with the exact venue settings used by this study (`bar_execution=True, bar_adaptive_high_low_ordering=True`). Captured, in actual dispatch order:
  ```
  ('on_order_filled', 1735000004000000000, 'O-...-000-2', '2')   # SL fill, ts = bar-4's timestamp
  ('on_bar',          1735000004000000000, True)                 # on_bar for THAT SAME bar, is_flat already True
  ```
  This is corroborated by direct engine-loop source reading as well: `BacktestEngine.run`'s main loop (`engine.pyx:1538-1552`) calls `exchange.process_bar(data)` (which performs matching and, per this trace, publishes resulting fill events) before `self._data_engine.process(data)` (which delivers the `Bar` to the strategy's `on_bar`). The probe confirms empirically that the net effect is: `on_order_filled` for a same-bar fill is dispatched strictly before `on_bar` for that bar, for every terminal fill in this venue configuration.

* **Impact - this is not a rare race, it is the deterministic, universal ordering for every single trade close in this pipeline.** Consequently, the flat-reset block's guard condition (`is_flat() and entry_px is not None`) can never be true, for any trade, at any point in any backtest run using this strategy and this venue configuration. `_warning_state`, `_warn_streak`, `_running_mae`, and `_tight_stop` are never reset by any code path - they are not reset in `_record_trade` (base class, has no knowledge of these child-class-only attributes) and not reset at entry-fill time either (`W4ExitStrategy` does not override `on_order_filled`, and the base class's `_pending_entry` fill branch only resets `_running_mfe`, not `_running_mae`, `_warning_state`, `_warn_streak`, or `_tight_stop`). Concretely, for the whole remainder of a backtest after the first trade whose warning state leaves `"NORMAL"`:
  - **If the prior trade ended at `ACTION_TAKEN`** (the expected outcome once B1/B2/B4/B5 successfully fire): every subsequent trade for the rest of the year starts in `ACTION_TAKEN`. `_process_5s_checkpoint`'s `if NORMAL` / `elif QUALIFIED` branches never match `ACTION_TAKEN`, so the state machine never evaluates a single subsequent trade - B1/B2/B4/B5 effectively become "fires at most once per backtest run," with every other trade exiting via T/SL/max_hold/regime only. This alone would invalidate any policy-vs-B0 comparison built from these results (nearly all "policy" trades are actually just bracket trades).
  - **If the prior trade ended at `QUALIFIED`** (plausible whenever a different exit - SL, target, max_hold, or the Item-2 residual WARNING above - closes the position while a policy exit was mid-flight and gets auto-cancelled, reverting state to `QUALIFIED` via `on_order_canceled` after the position already closed): the next, brand-new trade starts already in `QUALIFIED`. Its very first 5s checkpoint immediately executes the `elif QUALIFIED` branch's action for B1 (immediate full exit) or evaluates B2/B5's threshold against the new trade's own (correctly zeroed) `_running_mfe` - i.e., a brand-new position can be prematurely, forcibly exited near entry, before its own `_warn_streak` ever had a chance to accumulate on its own merits. This is actively harmful, not merely inert.
  - `_tight_stop` (B3) carries a stale absolute price level from the prior trade into a new trade whenever the prior state was left at `QUALIFIED`; the 1-second-bar breach check (`w4_exit_strategy.py:106-111`) would then compare the new trade's bar highs/lows against a price level computed relative to the old trade's entry price - a check that is essentially meaningless (could fire immediately, or never, depending on unrelated price coincidence).
  - `_running_mae` (used in every policy's parity-log `runtime_giveback` computation and available to any future policy logic) is a monotonic max-accumulator across the entire backtest, never reset, so it is not a valid per-trade MAE for any trade after the first.

* **Root cause**: the reset was designed assuming `on_bar` would observe the flat transition before the closing fill's callback had already cleared `_entry_px` - the opposite of NT's actual, now-confirmed dispatch order for this venue configuration. This is the same general class of ordering assumption this study has been repeatedly burned by (c.f. CLAUDE.md's own "NT close-order SL-before-close" lesson), but applied to a different callback pair (`on_bar` vs. `on_order_filled`) than previously documented, and never before empirically tested for this specific reset mechanism in passes 1-5, all of which took the block's own comment ("Warning 4/5 mitigation") at face value.

* **Correction (read-only recommendation, not applied)**: reset `_warning_state = "NORMAL"`, `_warn_streak = 0`, `_running_mae = 0.0`, `_tight_stop = None`, `_partial_exit_order_id = None`, `_partial_exit_reason = None` synchronously at the moment a position actually closes - i.e., override `on_order_filled` in `W4ExitStrategy` (or add a hook `_record_trade` can call) so these child-class variables are cleared in the same callback as `_record_trade`'s own reset of `_entry_px`/`_running_mfe`/etc., rather than deferring to a subsequent `on_bar` call that this trace shows never observes the intended pre-condition. Additionally reset them at entry-fill time (defense in depth) so a fresh trade never inherits a workflow state from a closed one under any future refactor. The existing `on_bar` flat-reset block should either be removed (if confirmed fully redundant once the above is added) or left only as a secondary safety net - it should not be relied upon as the primary mechanism.

---

## Verdict (Pass 6)

### **FAIL - do not run the full B0-B5 x {2025, 2026} backtest sweep yet**

*Rationale*: Fixes 1-3 from pass 5 are each individually correct and verified (Item 3 fully clean; Items 1 and 2 clean modulo the bounded WARNINGs above). However, this pass's holistic re-read - prompted specifically by re-examining Item 1's "does the QUALIFIED branch correctly stop being entered" question - surfaced a new CRITICAL that predates all of pass 3-6's fixes and was not caught by any prior pass: the `on_bar` flat-reset mechanism that passes 3-5 repeatedly confirmed as "RESOLVED"/"CLEAN" is empirically dead code under this venue's actual fill-before-bar dispatch order, so none of B1/B2/B3/B4/B5's warning-state machinery is reliably scoped to a single trade. This is a single root cause but it corrupts every policy that depends on `_warning_state`/`_warn_streak`/`_tight_stop`/`_running_mae` (i.e., everything except B0) for essentially the entire backtest, in a way that would silently produce misleading B1-B5-vs-B0 comparisons (either "policy never acts again after trade 1" or "policy prematurely kills brand-new trades") without raising any runtime error.

**Recommendation**: fix the CRITICAL above (move the child-class per-trade state reset into the same synchronous path as `_record_trade`, not the `on_bar` flat-reset block), then re-invoke this auditor once more on `strategies/w4_exit_strategy.py` for a Pass 7 focused solely on confirming the fix, before running any of the 6 policies. The two new Item-1/Item-2 WARNINGs (persistent-rejection retry cadence; resting-bracket-vs-in-flight-order id staleness) are acceptable to carry forward with user acknowledgment but should not be the reason to hold - the CRITICAL is.

---
---

# PASS 7 — Empirical Verification of the on_order_filled Reset Fix

* **Audit Date**: 2026-07-08 (pass 7)
* **Scope**: Verification of the single fix applied since pass 6:
  - `strategies/w4_exit_strategy.py` — removal of the dead `on_bar` flat-reset block; new `on_order_filled` override that calls `super().on_order_filled(event)` then resets `_warning_state`/`_warn_streak`/`_running_mae`/`_tight_stop`/`_partial_exit_order_id`/`_partial_exit_reason` if `self.portfolio.is_flat(self._inst_id)`.
* **Method**: Per explicit instruction, verified **empirically**, not by reading alone. Two scratchpad-only diagnostic `BacktestEngine` probes were built against the real, unmodified `W4ExitStrategy`/`W4ExitConfig` classes (imported directly from the repo — no code under test was copied, stubbed, or rewritten):
  1. A single-lot probe (`policy="B0"`, `entry_type="random"`, `entry_prob=1.0`, steady synthetic uptrend so the profit-target bracket reliably fires) that wraps (not replaces) the real `on_order_filled` to log `portfolio.is_flat()`, `_entry_px`, `_warning_state`, `_warn_streak`, and `_running_mae` immediately before and after every fill, across 59 full round-trip trades in a single run.
  2. A two-lot B4 probe (`entry_qty=2`, `policy="B4"`) that monkeypatches only the **trigger predicate** (`_process_5s_checkpoint`, replaced with a deterministic one-shot call to the real `_fire_immediate_exit`) so a genuine partial-exit order flows through the real, unmodified `_exit_partial_market`/`on_order_filled`/reset code — across 29 full ENTRY→PARTIAL→FINAL round trips.
  - Also directly traced the installed NT 1.221.0 source (`nautilus_trader/execution/engine.pyx:1467-1596`, `nautilus_trader/common/component.pyx:2517-2540,2741-2787`, `nautilus_trader/portfolio/portfolio.pyx:579-634,1453-1471`) to confirm *why* the empirical result holds: `MessageBus.send`/`publish_c` both dispatch subscriber handlers synchronously (no queueing), and `_handle_order_fill` calls `_handle_position_update` — which synchronously updates `cache.position` and, via a synchronous `msgbus.send` to `Portfolio.update_position`, recomputes the internal net-position used by `is_flat()` — **before** it publishes the `OrderFilled` event to the topic that ultimately invokes the strategy's `on_order_filled`. So `portfolio.is_flat()` is guaranteed already correct for **any** code running inside a strategy's `on_order_filled`, not merely after `super()` is called.

## Item 1 — `portfolio.is_flat()` correctness inside `on_order_filled`

**CONFIRMED, empirically and via source trace.** In probe 1, all 59 closing fills showed `is_flat() == True` even in the *pre-call* snapshot (captured before `on_order_filled` had done anything at all), and all 59 entry fills showed `is_flat() == False` both before and after. In probe 2's B4 case, the PARTIAL fill correctly showed `is_flat() == False` (remaining_qty=1) and the FINAL fill correctly showed `is_flat() == True` pre-call already. This is stronger than the pass-6 finding required: cache/portfolio state is updated by the execution engine *before the fill event is even dispatched to the strategy*, not merely by the time `super().on_order_filled()` returns inside the child class.

## Item 2 — Reset fires exactly once per completed trade, never on entry

**CONFIRMED.** Probe 1: reset fired on all 59/59 closing fills, 0/59 entry fills, 0 closing fills failed to reset. Probe 2 (B4): across 29 trades, the reset did **not** fire on the PARTIAL fill (correctly — `remaining_qty=1 > 0` keeps `is_flat()` `False`, state stayed `ACTION_TAKEN` unchanged), and fired exactly once on each FINAL fill (`warning_state` -> `"NORMAL"`, `remaining_qty` -> `0`). No double-fire, no missed-fire, no bleed into the next trade's ENTRY fill (next trade's ENTRY pre-state showed `warn="NORMAL"`, `remaining_qty=0`, i.e. the prior trade's reset, not a stale value).

## Item 3 — No new critical interaction with `_partial_exit_order_id`/`_partial_exit_reason`

**CONFIRMED, no double-reset or inconsistent ordering.** Base class's `on_order_filled` partial-exit branch (`strategy.py:551-553`) already nulls `_partial_exit_order_id`/`_partial_exit_reason` to `None` synchronously on that order's own fill, strictly before the child class's `super().on_order_filled(event)` call returns — so by the time the child's `if self.portfolio.is_flat(...)` check runs on a *later* (final) fill, `_partial_exit_order_id` is already `None` from the partial fill's own handling; the new reset block's re-assignment to `None` is idempotent, not a race. Empirically: 29/29 B4 trades showed `partial_id=None` in both the PARTIAL fill's post-state and the FINAL fill's post-state — no stale value, no double-clear conflict.

**Positive side effect on the pass-6 residual WARNING (guard doesn't cover resting SL/target brackets):** tracing the scenario from that WARNING (an SL fires and closes the position while a partial-exit order is still nominally tracked as in-flight) shows this fix now proactively nulls `_partial_exit_order_id` as soon as the SL's own fill flattens the position — *before* the exchange's later auto-cancel event for the stale partial-exit order can arrive. That auto-cancel's `_is_exit_action_order(cid)` check will then compare against `None` and correctly return `False`, so it can no longer spuriously revert `_warning_state` for a trade that's already closed. This narrows, but does not eliminate, that WARNING's underlying race (the SL/target resting-order path itself still isn't covered by the shared "exit in flight" guard) — carried forward unchanged in severity per instructions, with this mitigating detail noted.

## Re-confirmation of Pass 6's two narrower WARNINGs (not re-litigated, per instructions)

Both still stand exactly as documented in pass 6, unaffected by this fix (neither touches the guard or the QUALIFIED-retry code):
- **Persistent-rejection retry cadence**: `_fire_immediate_exit` could still resubmit every 5s for up to `MAX_HOLD_NS` (4 hours, ≤2,880 retries) under a persistent, reproducing rejection cause. Bounded, not a correctness bug.
- **Guard doesn't cover resting SL/target brackets vs. an in-flight partial-exit order**: race source unchanged (see Item 3's mitigating note above — consequence narrowed, cause still present).

## CLEAN (Pass 7, confirmed empirically)

- `on_order_filled` MRO/dispatch: the child class's override is invoked by NT (not bypassed), calls `super()` first, and the reset check runs after — confirmed by both probes producing exactly the expected fill sequence and reset behavior with no exceptions raised over 88 total fills across the two runs.
- No regression to the entry path: entry fills never observe `is_flat()==True` and never trigger the reset, in either probe.
- No regression to B4's multi-leg accounting: `_remaining_qty`, `_partial_leg_qty`/`_partial_leg_px` bookkeeping (verified in earlier passes) is untouched by this fix and continued to behave correctly across all 29 B4 round trips in probe 2.

---

## Verdict (Pass 7)

### **PASS_WITH_WARNINGS**

*Rationale*: The pass-6 CRITICAL (dead-code flat-reset, state bleeding across trades) is **resolved and empirically confirmed**, not just read as plausible — two independent executable probes against the real strategy code, backed by a direct NT source trace of the msgbus/execution-engine dispatch order, show the new `on_order_filled` reset fires exactly once per completed trade, never on an entry fill, and interacts safely with the partial-exit tracking fields (including mitigating part of a previously documented residual WARNING). Zero CRITICAL findings remain. Two bounded, non-blocking WARNINGs carry forward unchanged from pass 6 (persistent-rejection retry cadence up to ~2,880 attempts before `MAX_HOLD_NS`; the shared "exit in flight" guard still does not create mutual exclusion with the passively-resting SL/target bracket orders, though this pass narrowed one consequence of that gap). Per CLAUDE.md's audit-gate policy these should be addressed or explicitly waived by the user, but per pass 6's own guidance they are not blocking.

**Recommendation**: Safe to proceed with the full B0-B5 x {2025, 2026} backtest matrix. Carry the two WARNINGs forward for user acknowledgment or a future low-priority fix; no further pre-execution audit pass is required for this file unless the strategy code changes again.

**Scope hash (files reviewed this pass)**: `strategies/w4_exit_strategy.py` (on_order_filled reset only; all other sections re-confirmed unchanged from pass 6 by diff inspection).


---
---

# PASS 8 — Multi-Leg FOK Entry Fix Verification (B4, `entry_qty=2`)

* **Audit Date**: 2026-07-08 (pass 8)
* **Scope**: Verification of the multi-leg entry fix applied since pass 7:
  - `backtests/baseline_flip_parity/strategy.py` — `_submit_entry_orders`, `_finalize_entry`, `_entry_pending`, `_pending_entry_ids`/`_pending_entry_fill_qty`/`_pending_entry_notional`, `_resolve_entry_leg_failure`, new `on_order_filled`/`on_order_rejected`/`on_order_canceled`/`on_order_expired` branches for multi-leg entries.
  - `strategies/w4_exit_strategy.py` — no change for this fix; re-confirmed `on_order_filled` reset interaction only.
* **Method**: Empirical, per explicit instruction. Built a scratchpad-only diagnostic (`probe_pass8.py`, not part of the repo) that imports the real, unmodified `W4ExitStrategy`/`W4ExitConfig`/`BaselineFlipParityStrategy` classes and runs three `BacktestEngine` scenarios with the exact venue settings used by `run_w4_backtest.py` (`bar_execution=True, bar_adaptive_high_low_ordering=True`, NETTING/MARGIN, NQ futures), instrumenting `submit_order`/`on_order_filled`/`on_order_rejected`/`on_order_canceled` to log dispatch order without altering behavior:
  - **TEST1**: `entry_qty=2`, `policy="B4"`, synthetic 1m bar `volume=4` (chosen so `size = max(volume/4, size_increment) = 1` — the exact "1-lot-per-tick" liquidity ceiling described in the bug report), `entry_type="random"`, `entry_prob=1.0` to force an entry at the first eligible bar. 16 full round trips observed.
  - **TEST2**: `entry_qty=1`, `policy="B0"` (legacy scalar path), same synthetic data. 19 full round trips observed.
  - **TEST3**: Same as TEST1 but `volume=40` (synthetic liquidity = 10/tick, comfortably above the 2-lot requirement), as a liquidity-sufficient control.
  - Also directly re-inspected `nautilus_trader/backtest/engine.pyx` (`_process_market_order` → `fill_market_order` → `determine_market_price_and_volume` → `self._book.simulate_fills(...)`, and `apply_fills`'s FOK check at `engine.pyx:5370-5378`) to explain the observed empirical behavior rather than assume it.

## Item 1 — Does the fix solve the entry-starvation problem?

**CONFIRMED, empirically, including under the worst-case (1-lot-per-tick) liquidity condition.** In TEST1, both 1-lot legs of every one of 16 B4 entries filled successfully — none were FOK-killed, even with synthetic liquidity capped at exactly 1 lot per tick. Observed dispatch order for entry #1:
```
submit_order  leg1 (qty=1)
submit_order  leg2 (qty=1)
on_order_filled  leg1  qty=1 @ 15000.5
on_order_filled  leg2  qty=1 @ 15000.5
```
`_finalize_entry` fired exactly once, after leg2 resolved, with `self._remaining_qty=2` and `avg_px_open=15000.5` (both legs filled at the same price here, so VWAP == that price; the VWAP-averaging arithmetic itself, `notional/fill_qty`, was independently checked by code-reading and is straightforward for the case where legs fill at different prices — no bug found in it). Confirmed against NT's own `generate_positions_report()`: every position shows `quantity=2` at entry (before exit). **This resolves the original CRITICAL** (silent 2/3-of-entries-discarded via FOK-vs-synthetic-liquidity mismatch).

## Item 2 — Is the `entry_qty=1` legacy path unchanged?

**CONFIRMED UNCHANGED.** TEST2's dispatch log shows the single-scalar pattern exactly as before the refactor: one `submit_order`, one `on_order_filled` matching `cid == self._pending_entry`, `_remaining_qty` set to 1, `_finalize_entry` called once with the fill's own price — structurally and behaviorally identical to what passes 1-7 already audited (same order count, same tracking variable, same bracket-arming call). No regression found. This path does not need re-litigation per the instructions.

## Item 3 — Race/ordering risk between the two synchronous leg submissions

**CONFIRMED SAFE, and the underlying assumption in the question was empirically wrong in an interesting way.** The dispatch trace shows both `submit_order` calls complete *before either* fill event is dispatched — i.e., order submission from within `on_bar` is not matched inline/synchronously at the point of the `self.submit_order()` call itself; both legs are queued and only fill (in submission order) after control returns from the bar callback that submitted them. Consequently there is no window in which leg 2's fill could observe state finalized by leg 1's fill, **because `_finalize_entry` is deliberately never called until the entry-id set is empty** — leg 1's fill only decrements `_pending_entry_ids` and accumulates into `_pending_entry_fill_qty`/`_pending_entry_notional`; `_entry_dir`/`_entry_atr` remain exactly as set at signal-detection time (unrelated to and unmodified by either leg's fill) for the whole window. Empirically: both fills in every TEST1 trade showed `remaining_qty_before=0` (i.e., `_finalize_entry` had not yet run for either), confirming no half-initialized-state window exists. No fix needed for this item.

**Note on the "what if only 1 of 2 legs fails" sub-question**: tracing `determine_market_price_and_volume`/`apply_fills`'s FOK check (`engine.pyx:5370-5378`) shows the L1 book's synthesized per-tick quantity is **not decremented between separately-submitted orders** matched against the same book snapshot (each order's FOK check independently compares its own `leaves_qty` against `simulate_fills`'s return for the *current, un-depleted* book state) — this is *why* TEST1's two 1-lot legs both succeeded even at liquidity=1 (each independently "saw" 1 lot available, rather than competing for a shared pool of 1). A practical implication: under this fill model, it is very difficult to construct a scenario where leg 1 fills and leg 2 is FOK-killed purely from liquidity contention within the same tick, since both draw from the same undiminished snapshot. Genuine partial multi-leg failure would need an independent cause (e.g., a risk-engine rejection unrelated to liquidity) not exercised by this probe. This narrows Item 4's practical likelihood considerably but was not exhaustively forced — carried forward as a low-priority WARNING (static-reasoning-supported, not independently forced) rather than a blocking finding, since the code path (`_resolve_entry_leg_failure`) was already confirmed correct by reading: it correctly finalizes with whatever partial quantity filled, or fully backs out (no position, no brackets armed) if the fill count is zero.

## Item 4 — Interaction with the pass-7 reset fix (`on_order_filled` dispatched twice for a 2-leg entry)

**CONFIRMED NO PREMATURE FIRE.** Per pass 7's own source trace, portfolio/cache state is updated synchronously before a fill event dispatches to the strategy. After leg 1's fill, the real venue position is 1 lot (not flat); after leg 2's fill, it is 2 lots (still not flat). `W4ExitStrategy.on_order_filled`'s `if self.portfolio.is_flat(self._inst_id):` guard therefore correctly evaluates `False` on both entry-leg dispatches in every observed trade — the reset block never executes on an entry fill, matching pass 7's finding for the single-leg case and now confirmed to extend safely to the 2-dispatch case.

---

## CRITICAL (Pass 8, NEW, not part of the original verification request): 2-lot SL/target bracket orders can themselves receive **multiple partial fills**, and `on_order_filled` treats the first one as a full close — silently stranding the remaining contract and corrupting the strategy's own trade log

* **File/Lines**: [backtests/baseline_flip_parity/strategy.py:585-601](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L585-L601) (`elif cid == self._t_id:` / `elif cid == self._sl_id:` branches of `on_order_filled`), vs. [strategy.py:295-337](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L295-L337) (`_finalize_entry`, which arms a **2-lot** SL and a **2-lot** target for B4 before any partial exit has occurred)

* **Description**: This is the same class of liquidity constraint that motivated this pass's entry-side fix, but on the **exit** side, and it was never touched by that fix. The SL (`stop_market`) and target (`limit`) bracket orders armed in `_finalize_entry` are submitted as **GTC**, `reduce_only`, sized to `self._remaining_qty` (2 for a fresh B4 entry). Unlike the entry legs (FOK), a GTC order does **not** get killed when the synthetic per-tick liquidity is insufficient — it partially fills and stays open with `leaves_qty > 0`, filling the remainder on a later tick once more synthetic liquidity becomes available. `on_order_filled`'s `elif cid == self._t_id:` / `elif cid == self._sl_id:` branches, however, unconditionally treat **any** fill of that order id as the complete close: they null the id, cancel the sibling bracket order, and call `_record_trade(...)` — which resets `self._entry_px`/`_entry_dir`/`_entry_atr`/`_remaining_qty=0` — using only `int(event.last_qty)` from that single fill event, with no check of whether `leaves_qty` on the order is actually zero.

* **Empirical confirmation**: TEST1 (synthetic liquidity = 1 lot/tick, `entry_qty=2`) hit this on **every one of 16 trades**. Observed dispatch for trade #1's target order (cid `...-4`, submitted qty=2):
  ```
  on_order_filled  cid=...-4  last_qty=1  px=15001.0  remaining_qty_before=2  entry_dir_before=1
  on_order_filled  cid=...-4  last_qty=1  px=15001.0  remaining_qty_before=0  entry_dir_before=0
  ```
  The **first** fill (1 of the 2 contracted lots) matched `elif cid == self._t_id:`, canceled the SL sibling, and called `_record_trade("T", ..., last_qty=1)` — which computed `total_qty = 1` (not 2) and reset all entry state to flat/None, even though the venue position still had 1 lot open. The **second** fill for the *same order id* then arrived — but `self._t_id` had already been nulled by the first branch, and no other `elif` matches it (not `_pending_entry`/`_pending_entry_ids`, not `_sl_id` — already nulled too — not `_exit_order_id`, not `_partial_exit_order_id`) — so it **silently matches no branch at all**. That second lot's proceeds never reach `_record_trade` and are **absent from `self.all_trades`/`strategy_trades.parquet`** for that trade. NT's own `generate_positions_report()` is unaffected (it independently and correctly shows `quantity=2` closed, `realized_pnl` reflecting both lots) — this is a divergence between the two report files of the same kind pass 5 already flagged for a different root cause (same-bar exit race), now reproduced by a **second, independent mechanism**.

  TEST3 (liquidity = 10/tick, comfortably ≥ 2) does **not** exhibit this: the target order fills in a single event with `last_qty=2`, confirming the bug is specifically liquidity-gated, not a change of code path.

* **Why this was invisible before this pass**: for `entry_qty=1` (B0/B1/B2/B3/B5, the only configurations run through pass 1-7), a 1-lot SL/target order can never receive a "partial" fill in the first place — the instrument's `size_increment` is 1 contract, so any nonzero available liquidity fills the entire 1-lot order in a single event. The bug has been latent and structurally unreachable in every prior audit pass; it only becomes reachable now that `_remaining_qty` can exceed 1, which this very pass's fix is what first makes possible in practice (the entry-side fix is a *precondition* for this exit-side bug, not its cause).

* **Why this is likely to occur frequently in the real B4 backtest, not just as an edge case**: `run_w4_backtest.py` feeds both 1s and 1m bars to the engine; per `engine.pyx:3912-3930`, the exchange's execution granularity switches to whichever bar type has the smaller timedelta once both are seen — i.e., matching resolves against **1-second bar volume**, not 1-minute volume, for the remainder of the run. NQ 1-second bar volume is frequently in the single digits (occasionally 0) even during RTH, and more so overnight/ETH — `size = max(volume/4, 1)` will very plausibly be exactly 1 at many SL/target trigger moments, i.e., below the 2 lots needed to close a fresh B4 position in one shot. This is not a rare tail case; it is likely to affect a substantial, unquantified fraction of the 2025/2026 B4 trade population once run.

* **Impact**: for affected B4 trades, `strategy_trades.parquet` (i) undercounts the exit as a 1-lot close when it was actually a 2-lot close, silently misreporting the trade's true economics whenever the two partial fills occur at *different* prices (plausible if the second synthetic tick moves before the remaining lot fills — TEST1 happened to show the same price for both fills, which is not guaranteed in the real backtest with real price movement between ticks); (ii) the sibling bracket (SL when target partially fills, or target when SL partially fills) is explicitly canceled after only the *first* partial fill, before the position is actually flat, stranding the remaining open contract with **zero protective stop** until it eventually fills on its own resting order, `max_hold`, or a regime exit; (iii) `strategy_trades.parquet` and `trades.parquet` (NT's own `generate_positions_report()`) will disagree on trade count/PnL for every affected trade, in the same direction and for the same underlying reason (silent record loss on the strategy side) that pass 5 already flagged as a trust hazard for any analysis that uses `strategy_trades.parquet` exclusively.

* **Correction (read-only recommendation, not applied)**: mirror the accumulator pattern already used correctly for multi-leg entries. Either (a) check `self.cache.order(ClientOrderId(cid)).is_closed` (or `leaves_qty == 0`) before treating a `_t_id`/`_sl_id` fill as final — only null the id / cancel the sibling / call `_record_trade` once the order is confirmed fully closed, accumulating `last_qty` across intermediate partial-fill events into a running total for `_record_trade`'s `exit_qty` argument; or (b) size SL/target orders in a way that guarantees single-tick fillability (not generally controllable, liquidity-dependent, not recommended as the primary fix). Given cache state is confirmed (pass 7) to be updated before the fill event dispatches, option (a) is straightforward and requires no new architecture — the same `_pending_entry_fill_qty`/`_pending_entry_notional`-style accumulation already implemented for entries in this pass's own diff.

---

## Re-confirmation of items not re-litigated this pass

* Pass 6/7's two carried-forward WARNINGs (persistent-rejection retry cadence; shared "exit in flight" guard not covering resting SL/target brackets) — unaffected by this pass's fix, unchanged, still outstanding.
* All pass 1-7 CRITICAL resolutions — re-confirmed still resolved by this pass's re-read of the full `strategy.py`/`w4_exit_strategy.py` (no regression observed in unrelated sections).

---

## Verdict (Pass 8)

### **FAIL — do not run the B4 backtests yet**

*Rationale*: The specific fix this pass was asked to verify (multi-leg FOK entry submission for `entry_qty=2`) is **correctly implemented and empirically confirmed** — Items 1-4 from the verification request are all resolved or confirmed safe, including under the worst-case 1-lot-per-tick liquidity condition, with no race/staleness issue in the two-leg entry path. However, this pass's holistic empirical testing (running the fix end-to-end, not just reading it) surfaced a **new CRITICAL** that is a direct, structural consequence of allowing `_remaining_qty > 1`: the 2-lot SL/target bracket orders armed for a successful B4 entry can themselves split into multiple partial fills under the same kind of thin-synthetic-liquidity conditions the entry fix was built to survive, and `on_order_filled`'s handling of `_t_id`/`_sl_id` fills was never updated to tolerate that — silently stranding a contract with no stop and dropping part of the trade's economics from the strategy's own trade log. This was reproduced on **16 of 16** synthetic trades under 1-lot/tick liquidity and is plausible to occur frequently (not rarely) in the real 1s-bar-driven B4 backtest given typical NQ 1-second bar volume. This blocks B4 specifically; B0/B1/B2/B3/B5 (all `entry_qty=1`, structurally immune to this specific bug since 1-lot orders cannot partially fill) remain unaffected and still do not need to be rerun.

**Recommendation**: fix the CRITICAL above (extend the multi-fill accumulation pattern, or an `is_closed`/`leaves_qty` check, to the `_t_id`/`_sl_id` branches of `on_order_filled`), then re-invoke this auditor for a Pass 9 focused on confirming that fix specifically (a repeat of TEST1's 1-lot/tick liquidity scenario, run to a full trade close, is sufficient) before running any B4 backtest.

**Scope hash (files reviewed this pass)**: `backtests/baseline_flip_parity/strategy.py` (full file re-read), `strategies/w4_exit_strategy.py` (full file re-read, no changes since pass 7 confirmed by diff-equivalent re-read). Empirical probe: `probe_pass8.py` (scratchpad-only, not committed to the repo).


---
---

# PASS 9 — Multi-Fill Exit-Accounting Rewrite Verification (2-lot GTC Bracket Partial Fills)

* **Audit Date**: 2026-07-08 (pass 9)
* **Scope**: Verification of the pass-8 CRITICAL fix ("2-lot SL/target bracket orders can receive multiple partial fills") — a substantial rewrite of the exit-fill accounting path in `backtests/baseline_flip_parity/strategy.py`: `self._exit_legs` accumulator, `_accumulate_exit_leg`, `_resize_sibling_bracket`, `_finalize_exit`, rewritten `on_order_filled` `_t_id`/`_sl_id` branches, `_exit_order_ids` multi-leg full-exit path, `_resolve_exit_leg_failure`, and `strategies/w4_exit_strategy.py`'s `_is_exit_action_order` extension.
* **Method**: Empirical, per explicit instruction — this is a rewrite of the core exit-accounting path shared by every policy. Built a scratchpad-only diagnostic (`probe_pass9.py`, not part of the repo) that imports the real, unmodified `W4ExitStrategy`/`W4ExitConfig`/`BaselineFlipParityStrategy` classes and runs three `BacktestEngine` scenarios with the exact venue settings used by `run_w4_backtest.py` (`bar_execution=True, bar_adaptive_high_low_ordering=True`, NETTING/MARGIN, NQ futures). Instrumented `on_order_filled`, `_accumulate_exit_leg`, `_resize_sibling_bracket`, `_finalize_exit`, `on_order_canceled`, and per-instance `submit_order` to log dispatch order, `leaves_qty`/`is_closed` of the order being processed, and `self._remaining_qty` before/after every call, without altering behavior (wraps and calls the original in every case):
  - **Scenario A**: `entry_qty=1`, B0, ample liquidity (vol=40) SL breach bar — legacy 1-lot single-fill regression check.
  - **Scenario B**: `entry_qty=2`, B0, thin liquidity (vol=4, size=1/tick) SL breach bar engineered so the breach persists from the bar's "low" synthetic sub-tick through its "close" sub-tick (same bar, `bar_adaptive_high_low_ordering` open→high→low→close sequencing) — reproduces pass 8's worst-case 1-lot/tick condition against a 2-lot bracket, with the breach staying live long enough for a resubmitted/resized order to have a chance to fill again within the same bar.
  - **Scenario C**: `entry_qty=2`, B0, ample liquidity (vol=40) SL breach bar — non-race control, single fill event for the full 2-lot order, to isolate the "clean path" (`_finalize_exit` reached normally) from the race path.
  - Also directly re-inspected `nautilus_trader/backtest/engine.pyx` (`_process_trade_ticks_from_bar`, `iterate`) to understand why a single 1-second bar can produce more than one synthetic matching pass (up to 4 sub-ticks — open/high/low/close — each an independent `update_trade_tick` + `iterate()` call), which is what makes the race in the finding below reachable within a single 1s bar rather than requiring two separate bars.

## Item 2 — Is the 1-lot path (B0/B1/B2/B3/B5) truly unchanged?

**CONFIRMED IDENTICAL.** Scenario A: entry at 20000, SL breach fills in one event at 19990, `_record_trade` produces `exit_px=19990.0, exit_pnl_pts=-10.0, exit_pnl_atr=-1.0` — the same values and the same single-fill dispatch shape (`submit_order` → one `on_order_filled` → `_accumulate_exit_leg` → `_finalize_exit` → cancel sibling T) that passes 1-7 already validated. `strategy._remaining_qty` starts at 1 and a size-1 order can never receive a genuine partial fill (`size_increment=1`), so `_resize_sibling_bracket` is structurally unreachable for entry_qty=1 — confirmed both by direct code reading and by the probe's dispatch log showing no `resize_sibling_bracket` call anywhere in Scenario A. **No regression. B0/B1/B2/B3/B5 do not need to be rerun** regardless of the finding below, because the finding below is specific to a code path (`_resize_sibling_bracket` triggered by a genuinely-partial GTC bracket fill) that is unreachable at `entry_qty=1`.

## CRITICAL (Pass 9, NEW): `_resize_sibling_bracket`'s cancel-then-resubmit does not reliably stop the just-triggered original bracket order from receiving a further fill within the same bar — reproducing pass 8's exact failure mode (silently dropped trade + orphaned live orders) via a new mechanism

* **File/Lines**: [strategy.py:L587-608](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L587-L608) (`on_order_filled`'s `_t_id`/`_sl_id` branches), [strategy.py:L762-793](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/backtests/baseline_flip_parity/strategy.py#L762-L793) (`_resize_sibling_bracket`)

* **Description**: This is exactly the risk raised in verification question 3, and it is real, though the concrete mechanism is worse than the question anticipated. Sequence observed in Scenario B (2-lot SL order `-000-3`, thin liquidity):
  1. The bar's "low" sub-tick breaches the SL trigger; `-000-3` (a GTC stop_market for qty=2) receives its first fill: `last_qty=1 @ 19990.0`, and — critically — the order is **not yet closed** (`leaves_qty=1` remains outstanding, confirmed directly via `self.cache.order(...)`).
  2. `on_order_filled`'s `elif cid == self._t_id`/`self._sl_id` branch does **not** null `self._sl_id` (since `order.is_closed` is False) and calls `_resize_sibling_bracket()`.
  3. `_resize_sibling_bracket` calls `self.cancel_order(sl_order)` on the still-open, still-partially-filled `-000-3`, then immediately submits a brand-new order `-000-5` (qty=1, same trigger price) and reassigns `self._sl_id = '-000-5'`.
  4. **The cancel does not take effect in time.** The bar's "close" sub-tick (still below the SL trigger — the breach persists through the whole bar) generates a **second** fill for the very same order `-000-3` (`last_qty=1 @ 19989.75`, `leaves_qty=0`, `is_closed=True` — i.e. this second fill is what actually closes out that order's originally-submitted 2-lot quantity, not the cancel).
  5. When this second fill dispatches to `on_order_filled`, `cid == '-000-3'` — but `self._sl_id` is now `'-000-5'` (reassigned in step 3) and `self._t_id` is `'-000-6'` (also reassigned by the same resize call). **No branch in `on_order_filled` matches `cid='-000-3'` anymore** (not `_t_id`, not `_sl_id`, not `_exit_order_id`, not `_exit_order_ids`, not `_partial_exit_order_id`). The fill is silently discarded: `_accumulate_exit_leg` is never called for this second lot, `self._remaining_qty` stays permanently stuck at `1`, and `_finalize_exit`/`_record_trade` never fires for this trade.

* **Empirical confirmation of impact**: `strategy.all_trades` — **0 trades recorded** for this position, for the entire backtest run. NT's own `generate_positions_report()`, by contrast, correctly shows the position fully closed (`quantity=0`, `avg_px_close=19989.875`, `realized_pnl=-405.00 USD`, `ts_closed` populated) — the venue-level economics are correct, but `strategy_trades.parquet` would silently contain **zero rows** for this trade. This is a **complete, silent loss of a trade record**, not merely a mispriced one — worse than pass 8's original finding (which at least recorded a 1-lot-priced version of the trade).

* **Second, compounding consequence — two live orders orphaned against an already-flat position**: The resized orders `-000-5` (SL, qty=1 @ 19990) and `-000-6` (target, qty=1 @ 20010) are never canceled — `self._sl_id`/`self._t_id` still point to them, but the strategy's own state (`_remaining_qty=1`, `_entry_px` still set to the original entry price, `_exit_legs` still holding only the first leg) is now permanently wrong, and no code path ever revisits it (the position is flat at the venue, so no further SL/T/max_hold/regime-exit logic will ever fire for `_remaining_qty` bars-in-position checks tied to this "trade"). These two orders remain **live, resting, reduce_only orders against a position that no longer exists** at the venue. (Traced, not independently forced beyond this run: if the strategy later opens a **new** position while these are still resting — `_entry_pending()`/`portfolio.is_flat()` do not check for this zombie state, so a new entry is not blocked — `_finalize_entry` overwrites `self._sl_id`/`self._t_id` with the new trade's bracket ids without first canceling `-000-5`/`-000-6`, permanently orphaning them from `self.` tracking entirely while they remain live on the exchange. If price later revisits 19990 or 20010, these stale orders could fill against the *new* position with zero strategy visibility. This specific cascade was not independently forced in this pass's probe — flagging as a strongly-implied, not empirically-observed, second-order risk.)

* **Root cause**: `self.cancel_order()` issued against an order whose stop trigger has already activated mid-processing of a bar (i.e., it is actively competing for further liquidity across that bar's remaining synthetic sub-ticks — confirmed via `engine.pyx`'s `_process_trade_ticks_from_bar`, which calls `iterate()` up to 4 times per bar, once per open/high/low/close sub-tick) is **not guaranteed to preempt a fill already resolving from a later sub-tick of that same bar**. This is a genuine NT-engine-level race, not purely a strategy-code bug — but the strategy-level consequence (silent trade-record loss + orphaned live orders) is avoidable.

* **Why Scenario C (ample liquidity) doesn't show this**: with sufficient synthetic volume, the 2-lot order fills completely in its **first** matching sub-tick (`last_qty=2`, `is_closed=True` immediately) — `_resize_sibling_bracket` is never called because `self._remaining_qty` reaches 0 on the first and only fill. The bug is specifically gated on genuine intra-order partial fills, i.e. exactly the thin-liquidity condition pass 8 already established is "likely to occur frequently, not rarely" for NQ 1-second bar volume once a real B4 backtest runs.

* **Why this is scoped to B4 only**: identical to pass 8's own scoping argument — `_resize_sibling_bracket` can only be reached when a bracket order sized `>1` receives a genuine partial fill, which requires `entry_qty>1`, which only B4 uses. B0/B1/B2/B3/B5 remain unaffected (see Item 2 above) and do not need to be rerun.

* **Correction (read-only recommendation, not applied)**: Do not rely on `cancel_order()` alone to stop a just-triggered bracket order from further matching within the same bar. Options: (a) after `_resize_sibling_bracket`'s cancel+resubmit, explicitly check whether a **second** fill for the *old* cid arrives despite the cancel (e.g. keep the old cid in a short-lived "recently superseded" set mapped to the still-live `_exit_legs` accumulator, so any late fill for it is still accumulated and, if it brings `_remaining_qty` to 0, still routes to `_finalize_exit` — this also needs to then cancel the *newly*-resubmitted sibling orders, since they'd now be stale); or (b) do not resize/resubmit at all until the *original* order's cancellation is confirmed via its own `OrderCanceled`/`OrderFilled` terminal event, accepting the brief window of an under-sized (rather than absent) bracket in between; or (c) simplest and most robust: track exit-leg accumulation purely by **fill events**, independent of which order id is "current" — i.e., accumulate into `_exit_legs` from *any* fill whose order tag/side indicates a closing fill for this position, and treat `_remaining_qty<=0` (derived from accumulated fills, cross-checked against `self.portfolio.is_flat()`) as the sole finalize trigger, rather than requiring the fill's `cid` to match a currently-tracked scalar attribute that a concurrent resize can silently reassign out from under an in-flight order.

## Item 4 — `_finalize_exit`'s defensive cancel loop: self-cancellation risk

**NOT OBSERVED in either reachable clean path (Scenario A, Scenario C).** In both, the order id whose fill triggered `_finalize_exit` (`_t_id`/`_sl_id`) is already `None` by the time the defensive cancel loop runs (nulled via the `if order is None or order.is_closed: self._t_id = None` check in the immediately-preceding branch, since a single-fill-to-zero-leaves order is always `is_closed=True` at that point) — so the loop only ever cancels the **sibling** order, never re-touches the order whose own fill it's processing. No self-cancellation exception or double-cancel warning was observed in either scenario's log. This question is **moot for the Scenario B race case specifically**, since `_finalize_exit` is never reached there at all (the bug in the CRITICAL above manifests *before* this code would run). No fix needed for this item in isolation, but note it inherits the same underlying fragility as the CRITICAL above: `_finalize_exit`'s correctness assumes `self._sl_id`/`self._t_id`/`self._exit_order_id`/`self._partial_exit_order_id` accurately reflect all outstanding orders at the moment it runs — an assumption the CRITICAL above shows can already be false by the time any exit code path executes.

## Item 5 — Verification of point 10's `_exit_order_ids` vs. `_warning_state == "ACTION_TAKEN"` reasoning

**INCOMPLETE / not fully accurate, via static trace (not independently empirically forced — see caveat below).** Traced a concrete, reachable counter-scenario to the code comment's claim that `_exit_order_ids` "is independent of the warning state machine":
- `_exit_order_ids` is populated only by `_exit_all_market` when `self._remaining_qty > 1` — for a B4 trade, this is only possible **before** any partial exit has occurred (`remaining_qty` still `2`).
- The base class's `max_hold` check runs (via `super().on_bar(bar)`) **before** the child class's 5-second-checkpoint logic within a single `on_bar` call for a 1s bar. If `max_hold` fires first on a bar where `remaining_qty` is still 2, it calls `_exit_all_market("max_hold")`, populating `_exit_order_ids` with 2 legs.
- If, on that **same** bar/checkpoint, `_warning_state` is already `"QUALIFIED"` (from an earlier checkpoint), the checkpoint logic's B4 retry branch calls `_fire_immediate_exit`, which calls `_exit_partial_market` — this is correctly a no-op (blocked by the shared "exit in flight" guard, since `_exit_order_ids` is now non-empty) — **but `_fire_immediate_exit` sets `self._warning_state = "ACTION_TAKEN"` unconditionally, regardless of whether the `_exit_partial_market` call actually submitted anything.**
- This means `_warning_state == "ACTION_TAKEN"` **can** coincide with `_exit_order_ids` being the only exit actually in flight — directly contradicting the stated assumption.

**Traced consequence, not independently forced this pass**: in the interleavings actually reachable (max_hold always evaluated before the checkpoint branch within one `on_bar` call), this appears to **self-correct rather than corrupt**: if any leg of the max_hold multi-exit is later rejected/canceled, `_is_exit_action_order` (this pass's own item 10 addition) *does* recognize `_exit_order_ids` membership, so `on_order_rejected`/`canceled` correctly reverts the spurious `ACTION_TAKEN` back to `QUALIFIED`; and if the max_hold exit resolves cleanly to fully flat, the position closes normally via `max_hold` and the `on_order_filled` reset (pass 7's fix) resets `_warning_state` to `NORMAL` regardless of the intervening spurious value. No path to a permanently stuck state or a corrupted PnL record was found in this trace. This should be classified as a **WARNING** (fragile/coincidentally-correct coupling and an inaccurate code comment, not a confirmed data-corruption bug) rather than a CRITICAL — but it was traced statically, not exercised by an executable probe (constructing it would require a loaded weakness-prediction parquet with keys matching a synthetic scenario's exact `(direction, flip_ts, observation_time)` tuples, which was judged out of proportion to this item's traced severity given the CRITICAL above already blocks B4 outright).

**Correction (read-only recommendation, not applied)**: Correct the code comment at `w4_exit_strategy.py:226-234` to acknowledge this coupling rather than assert independence; consider only setting `_warning_state = "ACTION_TAKEN"` in `_fire_immediate_exit` if the underlying `_exit_partial_market`/`_exit_all_market` call actually submitted an order (e.g. have those methods return a bool indicating whether they no-oped due to the in-flight guard).

---

## Re-confirmation of items not re-litigated this pass

* All pass 1-8 CRITICAL/WARNING resolutions unrelated to the exit-accounting rewrite: unaffected, unchanged.
* The two pass 6/7/8-carried-forward WARNINGs (persistent-rejection retry cadence; resting-bracket-vs-in-flight-order id staleness) are effectively **subsumed** by this pass's new CRITICAL, which is a more severe, concretely-reproduced instance of the same general class of risk (bracket-order state going stale relative to strategy tracking). Continue carrying them forward as-is until the CRITICAL above is fixed and re-verified.

---

## Verdict (Pass 9)

### **FAIL — do not run the B4 backtests. Do NOT rerun B0/B1/B2/B3/B5.**

*Rationale*: The specific fix this pass was asked to verify only partially resolves pass 8's finding. It is **correctly resolved in the non-race case** (Scenario C: a 2-lot bracket order that fills completely in a single event is now accumulated, finalized, and blended correctly — a genuine, verified improvement over pass 8's original code, which had no accumulation logic at all). However, empirical testing under the same thin-liquidity condition pass 8 itself used (Scenario B, mirroring pass 8's own worst-case 1-lot/tick liquidity) reproduces **the identical class of failure pass 9 was meant to eliminate** — a silently-dropped trade record — via a **new** mechanism: `_resize_sibling_bracket`'s cancel-then-resubmit of a just-triggered, still-partially-filled bracket order does not reliably prevent that original order from receiving a further fill later in the same bar, and that further fill matches no branch in `on_order_filled` once the tracking id has been reassigned to the resized replacement order. This is **worse** than pass 8's original bug in one respect: in addition to the silently-dropped trade, it leaves **two live, resting, reduce_only orders orphaned against an already-flat position**, with no code path ever canceling or re-tracking them.

The 1-lot legacy path (B0/B1/B2/B3/B5) is **confirmed unchanged and correct** (Scenario A) and is structurally immune to this bug (a size-1 order cannot receive a genuine partial fill) — **these do not need to be rerun.**

**Recommendation**: fix the CRITICAL above — per the read-only correction, decouple exit-leg accumulation/finalization from "does this fill's cid match a currently-tracked scalar attribute" (which a concurrent resize can silently invalidate) and instead accumulate from any closing fill against this position, using `self.portfolio.is_flat()`/derived `remaining_qty` as the sole finalize trigger. Then re-invoke this auditor for a **Pass 10** focused on: (a) confirming the fix under the exact Scenario-B thin-liquidity/persistent-breach condition used this pass (must show `Trades recorded: 1` with the correct blended 2-lot price, and zero orphaned live orders after the position closes), (b) re-confirming Scenario A/C still pass unchanged, and (c) addressing or explicitly waiving the WARNING in Item 5 (correct the `_is_exit_action_order` code comment's independence claim). Do not run any B4 backtest until Pass 10 passes clean.

**Scope hash (files reviewed this pass)**: `backtests/baseline_flip_parity/strategy.py` (full file re-read, exit-accounting section fully re-verified), `strategies/w4_exit_strategy.py` (full file re-read, `_is_exit_action_order`/`_fire_immediate_exit`/state-machine interaction re-traced). Empirical probe: `probe_pass9.py` (scratchpad-only, not committed to the repo; 3 scenarios, full instrumented dispatch logs retained in scratchpad for reference).
