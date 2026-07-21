# Look-Ahead & Timestamp Audit

**Date:** 2026-05-08
**Scope:** `studies/reversion_after_5_streak/tick_validate_2026.py` (primary); `studies/reversion_after_5_streak/scan_fade_rth_split.py` (reference scan for parity checks)
**Auditor:** lookahead-auditor v1

---

## tick_validate_2026.py audit

### Summary

- Critical: 0
- Warning: 1
- Note: 2

---

## Critical findings

None.

---

## Warnings

### [D1 / comparison-fairness] `tick_validate_2026.py:376-391` — bar-mode mean and total use the full population; tick-mode uses the `valid` subset

**Description.** The `valid` filter at line 359 excludes any signal that received `exit_reason == "no_entry_ticks"` (no trade tick found at or after `signal_ts` within the holding window). That is correct for tick-mode statistics. However, lines 376-377 and 391 report the bar-mode mean and total over `out` — the full population including those same unmatched signals. The two denominators are therefore different:

```
line 376-377  bar mean   = out['bar_outcome_atr'].mean()      # n signals
line 378-379  tick mean  = valid['tick_outcome_atr'].mean()   # n_v signals
line 382-383  delta mean = valid['delta_atr'].mean()          # n_v signals — correct for delta
line 391      bar total  = out['bar_pnl_dollars'].sum()       # n signals
line 392      tick total = valid['gross_pnl_dollars'].sum()   # n_v signals
```

If even one or two signals land in `no_entry_ticks` (possible at RTH open/close boundaries where ticks may straddle a monthly file boundary), the reported bar mean and dollar total will be computed on a slightly larger population than the tick mean. The delta on line 383 (`valid['delta_dollars'].mean()`) is computed correctly (both sides restricted to `valid`) but the headline "bar gross" on line 391 will not match the corresponding "tick gross" on a per-signal basis.

**Recommended fix (do not apply):** compute bar-mode statistics restricted to the `valid` population: `valid['bar_pnl_dollars'].mean()` and `valid['bar_pnl_dollars'].sum()`.

---

## Notes

### [E4 / timeout-exit fidelity] `tick_validate_2026.py:300-302` — `n_ticks == 0` timeout marks P&L as zero

**Description.** When an entry tick is found but no subsequent tick exists within the 600s window (`n_ticks == 0`, line 300), `tick_pts` is set to 0.0 and `exit_reason` stays `"timeout"`. These trades are included in the `valid` population. In practice this would mean NQ traded zero times in the 10 minutes after entry — essentially impossible during RTH, but the mark-to-zero is a silent assumption. If such cases occur they will show an artificially benign outcome (zero P&L) rather than the actual close price of the last available trade. No look-ahead is introduced; the handling is simply conservative but slightly inexact.

**Recommended fix (do not apply):** log a warning and count these cases. If the count is zero in practice, add an assertion to confirm this assumption holds for the 2026 RTH data.

### [E5 / no warmup assertion] `tick_validate_2026.py:139,154` — ATR warmup implicit but unguarded

**Description.** Wilder ATR(14) produces `nan` for rows 0-12 and is guarded at line 168 (`not np.isfinite(a)`). However the loop starts at `range(STREAK_LEN - 1, n)` = `range(3, n)`, which is well inside the warmup zone. The `isfinite` check at line 168 is the only guard. This is functionally correct — NaN ATR values skip the signal — but there is no assertion or log line confirming how many signals are dropped due to warmup. A count of warmup-dropped candidates would be useful to confirm no signals are generated in the first 13 bars.

**Recommended fix (do not apply):** add a counter for ATR-not-finite skips and print it alongside the signal count at line 320.

---

## Clean checks

- **A1** — Session classification uses `b.ts_init` (bar close time) via `session_of_close_ct(df["ts_init"].to_numpy())`. Correct.
- **A2** — Catalog is `NQ_v0_2020_2026`; per project memory, fixed catalog uses `closed='left'` resampling. Bar load uses `b.ts_init` not `b.ts_event`. No catalog-delta issue visible at this layer.
- **B1** — No `rolling`, `ewm`, or `expanding` with `center=True`. Regime EMA uses `ewm(adjust=False)` which is strictly causal.
- **B2** — Wilder ATR at bar `i` uses only `tr[0..i]`. Seed is `tr[:period].mean()` (bars 0..period-1), then Wilder recursion. No centering or future inclusion.
- **B4** — No `.shift(-N)` anywhere in `tick_validate_2026.py`.
- **B5** — No `.ffill()` or `.bfill()` in the feature/signal path.
- **C1 / signal causality** — `find_signals` loops over completed bars; `signal_ts = ts[i]` is `ts_init` of the streak-end bar (close time). Entry is the first tick AT-OR-AFTER that timestamp. No bar `i+1` data used to generate the signal.
- **C3 / tick-entry causal** — `i_entry = np.searchsorted(ts_arr, sig_ts, side="left")` finds the first tick `>= sig_ts`. Correct; no look-ahead into tick data.
- **C3 / exit window** — `seg_ts = ts_arr[i_entry+1:i_end]` excludes the entry tick from the exit scan. Cannot double-use the entry tick as both fill and exit candidate. Correct.
- **C3 / PT-SL tie in ticks** — Structurally impossible for a long: `sl_px = entry_px - 2*ATR < entry_px < entry_px + 1*ATR = pt_px`. A single tick cannot be both `>= pt_px` and `<= sl_px`. No same-tick ambiguity exists.
- **D1 / scan parity** — Both files implement: same Wilder ATR(14), same `ewm(adjust=False)` sticky regime, same `bear = (close < openp)`, same `consec` gap check (`ts[i]-ts[i-1] == 60_000_000_000`), same streak slice `[i-STREAK_LEN+1:i+1]`, same `last_taken` non-overlap guard (`i <= last_taken + FORWARD_BARS`), same forward-window 60s-consec + same-session check. Session forward-window check: scan uses `sess[i+k] != sess[i]`; validator uses `sess[i+k] != "RTH"` — these are semantically identical because `sess[i] == "RTH"` is confirmed at line 165 before entering the check.
- **D1 / bar-mode SL-first tie** — Both files check SL before PT in the same-bar tie scenario. Identical conservative convention.
- **E2 / action='T' filter** — Trade ticks are filtered to `action == "T"` at parquet level (line 217-220) with a fallback path that also enforces the filter (line 230). Quote updates cannot trigger fills.
- **G1 / NQ.v.0 alignment** — 1m bars from `NQ.XCME-1-MINUTE-LAST-EXTERNAL` catalog built from NQ.v.0 data; tick files named `NQ_v0_mbp1_2026_{01..04}.parquet`. Both are volume-continuous contract. No quarterly-roll spread gap. The project memory note about c.0 vs v.0 mismatch does not apply here.
- **F3 / timezone handling** — All internal computation in UTC nanoseconds. `session_of_close_ct` correctly converts to `America/Chicago` for RTH classification. No naive timestamps in the signal path.
- **Cost model** — `spread_cost_pts = 1 tick × 0.25 pt/tick = 0.25 pt`; `spread_cost_dollars = 0.25 × $20 = $5`. Plus `COMMISSION_RT = $5`. Total cost = $10/trade round-trip. Conservative by retail standards.

---

*Audit complete. Zero critical findings. One warning (reporting population mismatch in bar vs tick comparison print; does not affect per-trade CSV data or the `delta_*` columns). Two notes. Findings reflect read-only static analysis only.*

---

## Re-audit confirmation (2026-05-08)

D1 fix verified. Every summary statistic in the printed output — bar-mode mean (`valid['bar_outcome_atr'].mean()`, line 378), bar-mode dollar mean (`valid['bar_pnl_dollars'].mean()`, line 379), bar-mode dollar total (`valid['bar_pnl_dollars'].sum()`, line 393), distribution counts (lines 370-375), and all tick-side and delta figures — is now computed exclusively on the `valid` cohort (signals with a confirmed tick fill). The NB exclusion notice at lines 397-399 fires only when `excluded > 0`, making any population shrinkage visible at runtime. No new look-ahead patterns, timestamp misuse, bfill, center=True rolling, or train/serve skew were introduced by the change. The two open Notes (E4 zero-tick mark-to-zero, E5 no warmup counter) remain stylistic suggestions with no correctness impact. Re-audit result: **0 Critical, 0 Warning, 2 Notes (unchanged, non-blocking).**

---

## tick_validate_realfills.py audit (2026-05-11)

**Scope:** `studies/reversion_after_5_streak/tick_validate_realfills.py`; cross-referenced against `studies/reversion_after_5_streak/scan_fade_rth_split.py` for signal-generation parity.

### Summary

- Critical: 0
- Warning: 0
- Note: 2 (carry-forward from prior audit, non-blocking)

### W1 resolution — exit bid fallback now tracked

Lines 336-340 (PT/SL exit) and 342-349 (timeout): when `seg_bid[idx]` or `seg_bid[-1]` is not finite/positive, `exit_fill` falls back to the trade print price and `exit_bid_patched` is set `True`. The flag is written to the output CSV (line 366) and counted/reported in `run_one_year` lines 434 and 438-440 (`exit bid patched -> trade px : N / total (X.XX%)`). Any consumer of the results can filter on this column. **W1 resolved.**

### W2 resolution — spread guard covers both bad-quote cases

Lines 300-311: `entry_ask_patched` fires when raw ask is not finite/positive; `entry_bid_bad` fires when raw bid is not finite/positive. `spread_at_entry` is set to `np.nan` if either flag is true (line 308-309). The prior bug — spread computed as patched-ask minus unguarded bid — cannot occur. Lines 433-441 print both the entry-ask patch count and the spread-NaN count, making both failure modes visible at runtime. **W2 resolved.**

### Carry-forward Notes (non-blocking)

- **[E4]** `n_ticks == 0` path (lines 350-352) still silently marks P&L as zero. Essentially impossible during RTH; no look-ahead introduced. Unchanged from prior audit.
- **[E5]** ATR warmup gate is `isfinite` check only (line 195); no counter of warmup-dropped candidates. Functionally correct. Unchanged from prior audit.

### Clean checks (new scope)

- **A1** — `load_1m_df` extracts only `b.ts_init`; no `b.ts_event` column. Session classification via `session_of_close_ct(df["ts_init"].to_numpy())`. Signal timestamp `signal_ts = int(ts[i])` is ts_init. Correct.
- **A2** — Catalog `NQ_v0_2020_2026`; same fixed catalog as prior audits. No delta issue at this layer.
- **B1/B2/B4/B5** — Same `compute_atr_wilder` and `compute_regime` as prior audits. No center=True, no shift(-N), no ffill/bfill.
- **C3 / tick-entry causal** — `i_entry = np.searchsorted(ts_arr, sig_ts, side="left")` finds first tick >= signal close time. No look-ahead.
- **C3 / exit window** — `seg_ts = ts_arr[i_entry+1:i_end]` excludes entry tick. Cannot double-use entry tick as exit. Correct.
- **D1 / scan parity** — `find_signals` logic matches `scan_fade_rth_split.py` exactly: same ATR, same regime EMA, same bear/consec/last_taken/forward-window guards. Forward-window session check `sess[i+k] != "RTH"` (line 202) is semantically identical to scan's `sess[i+k] != sess[i]` because `sess[i] == "RTH"` is confirmed at line 193 before entering.
- **D1 / bar-mode comparison uses valid cohort** — Lines 453-458 (`valid['bar_outcome_atr'].mean()`, `valid['bar_pnl_dollars'].mean()`) both restricted to the tick-filled cohort. Prior W1 population-mismatch pattern does not appear here.
- **E2 / action='T' filter** — Parquet read at lines 244-260 filters `action == "T"` with fallback enforcement. Quote updates cannot trigger fills.
- **G1 / contract alignment** — 2025: `legacy_c0` tick files + roll filter ±3d; 2026: `NQ_v0_mbp1_*` tick files + `NQ_v0_2020_2026` bars, no roll filter. Consistent with project memory rule.
- **F3 / timezone** — All computation in UTC nanoseconds; CT conversion only in `session_of_close_ct`. No naive timestamps.

*Re-audit complete. 0 Critical, 0 Warning. Two Notes unchanged from prior audit, both non-blocking stylistic suggestions.*

---

## tick_validate_realfills.py fill-model correction re-audit (2026-05-11)

**Scope:** `replay_realfills` function, lines 279-374. Specific change: PT trigger changed from `seg_bid >= pt_px` to `seg_px >= pt_px` (line 327); PT fill changed from `seg_bid[idx]` to `float(pt_px)` (line 347). SL, timeout, and signal-generation paths unchanged.

### Summary

- Critical: 0
- Warning: 0
- Note: 1 (stale docstring, no runtime effect)

### Verification of the five claimed properties

**PT trigger causality (line 327).** `hit_pt = seg_px >= pt_px`. `seg_px` is the forward slice `px_arr[i_entry+1:i_end]` — strictly post-entry trade prints. `np.argmax(hit_pt)` returns the index of the first `True`, which is the earliest tick at or above `pt_px`. No look-ahead: the segment excludes the entry tick and is bounded by `end_ts = sig_ts + HOLDING_NS`. Clean.

**PT fill at `pt_px` exactly (line 347).** `exit_fill = float(pt_px)`. A resting limit sell at `pt_px` cannot fill above `pt_px` (limit semantics) and would not fill below it (the trigger requires a trade print >= pt_px, meaning the market crossed the level). Fill at exactly `pt_px` is the correct and conservative model. No look-ahead; `pt_px` is computed from `fill_buy` and `atr_at_signal`, both known at entry time. Clean.

**PT/SL same-row collision (lines 332-346).** `sl_px = fill_buy - 2*ATR`; `pt_px = fill_buy + 1*ATR`. Gap is 3*ATR. `hit_pt` requires `seg_px >= pt_px`; `hit_sl` requires `seg_px <= sl_px`. A single trade print cannot simultaneously satisfy both conditions. The collision is structurally impossible regardless of whether `i_pt == i_sl` — the `i_sl <= i_pt` tie-break on line 334 is dead code for this trade direction but harmless. Clean.

**SL path (lines 335-342).** `hit_sl = seg_px <= sl_px` (unchanged). Trigger is first trade print at or below `sl_px`. Fill at `seg_bid[idx]` with finite-positive guard and `exit_bid_patched` fallback (unchanged from prior audited version). Market-sell-at-bid is the correct conservative model for a stop-market order. Clean.

**Timeout path (lines 349-356).** Fill at `seg_bid[-1]` with same finite-positive guard (unchanged). Causal: uses the last tick within `end_ts`, not any tick after it. Clean.

### Note

**[NOTE] `tick_validate_realfills.py:15-19` — module docstring describes the old PT fill model.** The docstring still says "triggered when a T row has `bid_px_00 >= PT_px`. Fill at that bid." The code now uses trade price for trigger and `pt_px` for fill. The docstring is stale but has no runtime effect.

**Recommended fix (do not apply):** update the docstring EXIT - PT description to match the corrected model: "triggered when a T row's trade price >= PT_px (trade crossed the limit level). Fill at PT_px exactly."

### Re-audit verdict

All five claimed properties verified correct. The fill-model correction is properly scoped — signal generation, dedup, roll filter, tick loading, SL path, and timeout path are all untouched. 0 Critical, 0 Warning. One Note (stale docstring). The corrected PT model is the more defensible representation of resting-limit-sell mechanics: it removes the structural undercount from bid-based triggering and eliminates the ambiguity of filling at bid (which could be either favorable or unfavorable slippage relative to `pt_px` depending on the spread at that tick). Results produced by this version should be taken as more accurate than the prior bid-trigger version.

---

## tick_validate_eod_flatten.py audit (2026-05-11)

**Scope:** `studies/reversion_after_5_streak/tick_validate_eod_flatten.py`. Derivative of the audited-clean `tick_validate_realfills.py`. Two substantive changes: (1) EOD-flatten exit replacing the 10-bar/600s hard cap; (2) single-position chronological dedup replacing fixed `last_taken + FORWARD_BARS`. All other properties inherited from the clean baseline.

### Summary

- Critical: 0
- Warning: 0
- Note: 2 (carry-forward E4/E5, non-blocking)

### Six specific verifications

**1. `session_end_ts` DST correctness (lines 144-150).**

The function performs: UTC ns → `pd.Timestamp(tz="UTC")` → `.tz_convert("America/Chicago")` → `.replace(hour=15, ...)` → `.tz_convert("UTC").value`. The `.tz_convert` call produces a tz-aware CT timestamp with the correct UTC offset for the input date. The `.replace()` call substitutes wall-clock fields while preserving the active UTC offset for that date. On 2025-03-09 (CDT begins): the input bar is in RTH (08:30–15:00 CT), well past the 02:00 CST→CDT transition; 15:00 CDT is unambiguous and maps to 20:00 UTC. On 2025-11-02 (CST resumes): 15:00 CT is also unambiguous (fall-back ambiguity affects only 01:00–02:00 CT); maps to 21:00 UTC. Neither transition date produces an ambiguous 15:00 wall-clock hour. DST handling is correct.

**2. `i_end = np.searchsorted(ts_arr, eod_ts, side="left")` (line 280).**

`side="left"` returns the first index where `ts_arr[i] >= eod_ts`. The slice `ts_arr[i_entry+1:i_end]` therefore contains all ticks with `ts_event` strictly less than `eod_ts` (strictly before 15:00:00.000 CT). A tick with `ts_event == eod_ts` is excluded. This is the correct and conservative semantics: the last valid RTH tick is the one immediately before session close, not one timestamped at the open of the post-RTH period. Clean.

**3. Single-position dedup (lines 347-357).**

- `last_exit_ts = -10**18` (line 347): far-past sentinel; no signal is blocked on the first pass. Correct.
- `s["signal_ts"] <= last_exit_ts` (line 349): rejects signals at-or-before the prior exit nanosecond. New signal must strictly follow the prior exit. This is the stated and correct intent — at `exit_ts` the position is still being closed; simultaneous entry is not possible.
- `last_exit_ts` updated only when `out["exit_ts"] > 0` (line 355): `no_entry_ticks` outcomes leave `exit_ts == -1`. `-1 < 0`, so the update is skipped. No position was opened, so no position blocks subsequent signals. Correct.

**4. 60-second minimum EOD filter (line 194).**

`end_ts - sig_ts < 60_000_000_000` drops signals with fewer than 60 seconds to EOD. `sig_ts` is `ts_init` (bar close time), which is the earliest moment the signal is actionable in live trading. A signal at 14:59:00 CT has exactly 60 seconds remaining and passes (not strictly less than). A signal at 14:59:01 CT has 59 seconds and is dropped. The guard is slightly optimistic by up to one tick interval (entry fill may arrive a few milliseconds after `sig_ts`), but this is a reasonable and labeled live-trading constraint. Clean.

**5. Removal of forward-bar same-session / 60s-consec check (deliberate relaxation).**

In `tick_validate_realfills.py`, bars `i+1..i+10` were required to be same-session RTH and 60-second consecutive. Those checks existed to bound the exit window to a single continuous RTH session and to ensure bar coverage for bar-mode P&L. With tick-level replay bounded by `eod_ts` (15:00:00.000 CT on the signal day), neither constraint is necessary: the exit window is already hard-bounded to the same session by construction, and P&L is computed from tick fills rather than bar closes. The relaxation is correct and consistent with the EOD-flatten model.

**6. Causality chain (lines 248-340, inherited from realfills).**

- Entry `np.searchsorted(ts_arr, sig_ts, side="left")` (line 254): first tick `>= sig_ts`. Causal.
- Entry guard `ts_arr[i_entry] >= eod_ts` (line 255): if the first available tick is already past EOD, reject entry (`no_entry_ticks`). Correct.
- Forward window `ts_arr[i_entry+1:i_end]` (lines 281-283): excludes the entry tick. Cannot self-fill.
- `hit_pt = seg_px >= pt_px` (line 289): trade print at-or-above PT level. `np.argmax` returns first True. Causal.
- `hit_sl = seg_px <= sl_px` (line 290): trade print at-or-below SL level. First True. Causal.
- PT fill `float(pt_px)` (line 305): known at entry from `fill_buy + PT_ATR * a`. No look-ahead.
- SL fill `seg_bid[idx]` (lines 297-301): bid at trigger tick, with finite-positive guard and `exit_bid_patched` fallback. Causal.
- EOD fill `seg_bid[-1]` (lines 309-313): last bid before `eod_ts`. Causal. `exit_bid_patched` fallback present (lines 311-314). Clean.
- `pt_px` and `sl_px` use `atr_at_signal` (ATR at bar `i`, computed over bars 0..i only) and `fill_buy` (entry ask, observed at fill time). Both strictly causal.

### Carry-forward Notes (non-blocking)

- **[E4]** `n_ticks == 0` / `eod_no_ticks` branch (lines 315-321): no ticks between entry and EOD; P&L computed from entry bid. Essentially impossible during RTH. No look-ahead. Unchanged from prior audits.
- **[E5]** ATR warmup gate is `isfinite` check only (line 188); no counter of warmup-dropped candidates. Functionally correct. Unchanged from prior audits.

### Clean checks

- **A1** — `load_1m_df` extracts only `b.ts_init`. Session classification via `session_of_close_ct(df["ts_init"].to_numpy())`. `signal_ts = int(ts[i])` is `ts_init`. Correct.
- **A2** — Catalog `NQ_v0_2020_2026`. Same fixed catalog as prior audits; no delta issue at this layer.
- **B1/B2/B4/B5** — Same `compute_atr_wilder` and `compute_regime` as prior audits. No center=True, no shift(-N), no ffill/bfill.
- **E2 / action='T' filter** — `load_trade_rows_with_quotes` filters `action == "T"` at parquet level (lines 215-228) with fallback enforcement (lines 223-229). Quote updates cannot trigger fills.
- **F1/F2 / session boundary** — EOD exit is bounded to `session_end_ts` of the signal day. A trade cannot run into the next RTH session.
- **F3 / timezone** — All internal computation in UTC nanoseconds. CT conversion isolated to `session_of_close_ct` (lines 137-141) and `session_end_ts` (lines 144-150). No naive timestamps.
- **G1 / contract alignment** — 2025: `legacy_c0` tick files + roll filter ±3d (acknowledged in `data_warning`); 2026: `NQ_v0_mbp1_*` + `NQ_v0_2020_2026` bars, no roll filter. Consistent with project memory rule and prior audits.

### Verdict

0 Critical, 0 Warning. Both substantive changes (EOD-flatten exit, single-position dedup) are correctly implemented. DST transitions verified safe. `searchsorted(side="left")` semantics verified correct for both entry (causal fill) and EOD boundary (last tick before close). Dedup sentinel and no-fill update-skip both correct. Results from this script are trustworthy as a tick-realistic EOD-flatten simulation.

---

*Audit complete. Findings reflect read-only static analysis only.*

---

## feature_scan_signals.py re-audit (2026-05-11)

**Scope:** `studies/reversion_after_5_streak/feature_scan_signals.py`. Two targeted fixes reviewed: (1) E4 EOD-fallback ETH-bar guard; (2) NOTE docstring feature-count correction.

### Summary

- Critical: 0
- Warning: 0
- Note: 0

### Fix 1 — E4 EOD fallback (lines 238-264)

`last_bar_in_session` is initialised to `i` before the forward loop (line 238) and updated to `j` only for bars that pass the 60s-consec and same-RTH-session checks (line 251). After the loop, if no PT/SL was hit (`exit_bar is None`), the fallback branch at lines 259-264 now applies a strict two-sided guard:

```
if last_bar_in_session > i and last_bar_in_session < n:
    exit_bar = last_bar_in_session
    exit_atr_outcome = (float(close[exit_bar]) - c0) / a
else:
    exit_bar = i
    exit_atr_outcome = 0.0
```

The condition `last_bar_in_session > i` is True only when at least one valid forward RTH bar was found. The condition `last_bar_in_session < n` guards the array bounds. When neither holds (signal at 14:58 CT with no valid forward bar, or a data gap immediately after signal), the code sets `exit_bar = i` and `exit_atr_outcome = 0.0`. Entry == exit, P&L = 0. No ETH bar can be used as a fallback because every bar accepted into `last_bar_in_session` is required to pass `sess[j] != "RTH"` (line 241). The prior risk — that `last_bar_in_session` remained equal to `i` (the initial sentinel) and was then silently used as an exit bar — cannot occur: if no valid bar was found, `last_bar_in_session == i` and the `> i` guard fails, routing to the zero-P&L path. Fix is correct and complete.

### Fix 2 — NOTE docstring feature count (lines 1-35)

Docstring line 24 now reads "28 features per signal (4 windows x 7 metrics)." The metric list at lines 16-22 enumerates all 7: `mfe`, `mae`, `net_move`, `total_excursion`, `ratio`, `efficiency`, `close_loc`. The `compute_rolling_features` function at lines 159-191 constructs exactly those 7 arrays per window label and returns them under the same key names. The `find_signals_with_features` snapshot loop at lines 279-281 iterates `w_feats.items()` and writes every key, producing 4 * 7 = 28 feature columns per signal row. Count and enumeration are consistent end-to-end. Note resolved.

### Carry-forward items

None. The two prior Notes (E4 and the docstring NOTE) are both resolved by this round of changes. No outstanding findings remain on this file.

### Verdict

**0 Critical, 0 Warning, 0 Notes.** Both targeted fixes are correctly implemented. The EOD fallback can no longer silently use an ETH bar or an out-of-bounds index. The docstring feature count and metric enumeration match the implementation. `feature_scan_signals.py` is clean.
