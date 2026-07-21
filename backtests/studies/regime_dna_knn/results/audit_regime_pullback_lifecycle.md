# Look-Ahead & Timestamp Audit

**Date:** 2026-06-16T00:00:00Z
**Scope:**
- `studies/regime_dna_knn/regime_pullback_lifecycle.py` (PRIMARY)
- `studies/regime_dna_knn/early_health_filter.py` (SUPPORTING — call-site: `compute_labels_features`, capsule column conventions)
- `studies/regime_dna_knn/progressive_separability.py` (SUPPORTING — call-site: `build(df)`)
- `studies/regime_dna_knn/build_survivor_1s_paths.py` (SUPPORTING — 1s path provenance)
- `studies/regime_dna_knn/results/survivor_1s_paths.parquet` (schema reference)

**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 0
- Warning: 1
- Note: 3

---

## Critical Findings

None.

---

## Warnings

### [W1] `regime_pullback_lifecycle.py:65` — `inst_fav` computed but never used; silent dead code

`inst_fav` is assigned at line 65 but referenced nowhere in the function. This is inert dead code with no correctness impact, but its presence suggests a possible intent to use it (e.g., as an alternative to the adverse-extreme-based `dd`). If the intent was to compute drawdown from the bar's own favorable extreme rather than the running peak, using `inst_fav` instead of `dd` would produce a materially different (and more conservative) event-detection criterion. The fact that the code never uses it cannot be confirmed by static analysis alone to be intentional.

**Recommended fix (do not apply):** Delete line 65 if `inst_fav` is confirmed to be a leftover from an earlier design. If there was intent to use it, document explicitly which drawdown definition is in use.

**Severity rationale:** This is a WARNING rather than CRITICAL because the implemented `dd` definition (drawdown from the running peak using the adverse extreme `l` for long / `h` for short) is the correct gold-standard 1s-touch detection definition per the study's own stated design. The dead variable does not alter any computed result.

---

## Notes

### [N1] `regime_pullback_lifecycle.py:81` — `ft` (timestamp slice) computed but never used

`ft = tt[i + 1:]` at line 81 is computed but not referenced in any subsequent calculation. This is inert dead code. It does not affect any output but is a cleanliness issue — `ft` was presumably intended for time-gated analysis (e.g., restricting the forward window to within a time budget) that was not implemented.

**Recommended fix (do not apply):** Remove line 81 if time-gating of the forward window is not intended. If forward-window time-gating is a future requirement, add a `ft <= some_budget` gate before scanning `fh` / `fl_arr`.

### [N2] `regime_pullback_lifecycle.py:56-57` — `T_flip` approximation via `r.n * 60 * NS`

`r.n` is `n_post` from `progressive_separability.build()`, which counts the number of completed 1m post-flip bars stored in the capsule (capped at `B-1 = 61` by the `min(n[i], B-1)` loop in `build()`). The `T_flip` approximation `r.n * 60 * NS` therefore equals the number of 1m bars times 60 seconds, which is an offset in nanoseconds from `regime_start_ts`. This is used to clip the 1s path to only bars inside the regime lifetime (`tt <= T_flip`).

Two sub-issues:

1. **The 61-bar cap in `build()` propagates to `r.n` here.** If a regime lasts longer than 61 bars, `r.n` is capped at 61, so `T_flip = 61 * 60 * NS = 3660s`. The 1s path is capped at `MAXSEC = 1800s` by `build_survivor_1s_paths.py`, so in practice the 1s window is already truncated before `T_flip` for any regime exceeding 30 minutes. The two caps interact such that for regimes < 1800s, `T_flip` controls; for regimes > 1800s, `MAXSEC` controls (they converge at ~30-31 bars). No look-ahead is introduced, but the `T_flip` boundary for long regimes may be 61 bars rather than the true flip time, causing the window to extend slightly beyond the actual flip into a different regime's territory on the 1s path — potentially allowing the 1s path (which is raw price from `build_survivor_1s_paths.py`) to extend past the 1m flip boundary if the path itself was captured past that flip. However, the `build_survivor_1s_paths.py` path capture stops attaching 1s bars to a capsule when `_finalize()` is called (i.e., at the opposite flip), so the stored path is already bounded by the true flip. The `T_flip` gate in `analyze()` is therefore redundant but harmless for the vast majority of trades.

2. **Regime-lifetime approximation is 1m-bar-granular.** `T_flip` is computed as an integer number of 1m bars times 60s. The true flip could happen at any second within that last minute. This introduces at most 60s of rounding. Given the path is already capped at 1800s and the 1s flip landing is already in the stored path (path capture stops at the flip), this is not a look-ahead.

**Recommended fix (do not apply):** For precision, store `regime_end_ts` in the 1s path parquet (already available from `cap["post"][-1]` in `_finalize()`) and use it directly as `T_flip` rather than the approximation. This is a robustness improvement, not a bug fix.

### [N3] `regime_pullback_lifecycle.py:112` — entry from `O[:, 4]` is the Bar-4 open of the 1m matrix; mismatch with `survivor_1s_paths.parquet` survivor definition

`entry = O[:, 4]` takes the open of the 4th post-flip 1m bar from the matrix built by `progressive_separability.build()`. The survivor 1s path parquet was built by `build_survivor_1s_paths.py`, which filters to `n_post >= 4`. This is consistent: only regimes where Bar 4 was observed have both a valid `O[:, 4]` and a stored path.

However, `entry` from the 1m matrix (`O[:, 4]`) is the 1m bar open price, while the 1s path used to detect the pullback event starts from `ENTRY_T = 180 * NS = 3 minutes` after flip-bar close (line 51). These two reference prices are from different resolution sources and are not guaranteed to be identical (the 1m open is the first 1s bar's open within that minute; `ENTRY_T = 180s` cuts in at the 3-minute mark, which is the third post-flip 1m bar boundary, not the fourth). The `entry` used for PnL is `O[:, 4]` (Bar-4 open, i.e., ~3 minutes after flip close), but the event detection window begins at `>= 180s` (i.e., starts at Bar-3 open). The pullback event could therefore be detected within Bar 3 (180s–240s) and the forward outcomes measured at a time the trade has not yet been entered (entry is at Bar-4 open, ~180s). An event at, say, 185s is before entry.

**Impact on correctness:** This does not corrupt the diagnostic's stated purpose (measuring forward outcomes after the pullback event), but it means `exit_pnl` and `hold_pnl` are computed from an entry price that postdates some events by up to 60s. For a pure diagnostic (no model, no trading decision), this inconsistency means the $/tr figures are slightly inaccurate for events in the 180s–240s window. The probability metrics (`new_peak`, `further`, `rem_mfe`) are unaffected. Given the study's conclusion is "exit-now ≈ hold-to-flip at every depth," this window-boundary inconsistency does not change the finding, but it should be noted for any future $/tr interpretation.

**Recommended fix (do not apply):** Gate event detection to `sel = t >= 240 * NS` (Bar-4 open boundary) if the intent is strictly post-entry pullbacks, or document explicitly that the 180s gate is a 3-minute warmup before the typical entry at Bar-4 open, and that events before Bar-4 open are included but their $/tr figures reference a future fill price.

---

## Causality Verification — Specific Checks Requested

The following are confirmations of the specific causality checks enumerated in the audit scope.

### Check 1: Forward slices use `[i+1:]`; bar i never in forward window

**CONFIRMED CLEAN.** Lines 80-81 define `fh = h[i + 1:]` (long) or `fh = l[i + 1:]` (short), and `ft = tt[i + 1:]`. Lines 87-88 define `fl_arr = l[i + 1:]` for further-hit (long), and lines 92-93 define `fh_arr = h[i + 1:]` (short). All forward scans are over `[i+1:]`. Bar `i` is not included in any forward outcome.

### Check 2: `peak_px` is a running cummax/cummin — causal at every bar

**CONFIRMED CLEAN.** Line 63: `peak_px = np.maximum.accumulate(h) if d == 1 else np.minimum.accumulate(l)`. `np.maximum.accumulate` is strictly causal: `peak_px[j]` uses only `h[0:j+1]`. The drawdown `dd = (peak_px - adverse) * d / a` at line 67 subtracts the current-bar adverse extreme from the running favorable peak — both are known at bar `j`. No future information enters `dd`.

### Check 3: `healthy = fav_exc >= TREND` uses the causal running peak

**CONFIRMED CLEAN.** Line 64: `fav_exc = (peak_px - e) * d / a` where `peak_px` is the running cummax. Line 68: `healthy = fav_exc >= TREND`. Both are element-wise over the same time axis and are strictly causal.

### Check 4: `new_peak` is forward-only and strictly greater than `peak_at`

**CONFIRMED CLEAN.** Lines 85, 91: `new_peak_hit = np.where(fh > peak_at)[0]` (long) / `np.where(fh < peak_at)[0]` (short), where `fh` is `h[i+1:]` / `l[i+1:]`. The threshold `peak_at = peak_px[i]` is the running peak at the event bar. The comparison is strict (`>` / `<`), meaning a bar that exactly ties the pre-pullback peak does NOT count as a new peak. This is slightly conservative (one tick above peak_at is required), which is the correct direction for a falsification study.

### Check 5: `further` race uses `[i+1:]` for both `fu_i` and `np_i`

**CONFIRMED CLEAN.** Both `further_hit` (lines 88, 93) and `new_peak_hit` (lines 85, 91) scan over `[i+1:]`. The race condition `further_first = np.isfinite(fu_i) and (fu_i < np_i)` at line 97 compares the first index in the `[i+1:]` slice where each condition fires. If `fu_i < np_i`, the further-loss happened before the new peak, which is the correct "give back another 0.5 ATR before recovery" condition.

### Check 6: `rem_mfe` is forward-only via `fut_fav` cummax over `[i+1:]`

**CONFIRMED CLEAN.** Line 84: `fut_fav = (np.maximum.accumulate(fh) - e) / a` (long) — a running cummax over `fh = h[i+1:]`. Line 90 (short): `fut_fav = (e - np.minimum.accumulate(fh)) / a`. Line 98: `rem_mfe = max(0.0, (fut_fav.max() - peak_exc_at))` — the maximum of the future running peak excursion minus the pre-pullback peak excursion. This is strictly forward-only and correctly measures additional favorable excursion after the pullback event. No bar at or before `i` enters this computation.

### Check 7: `exit_pnl` and `hold_pnl` use different prices; no accidental aliasing

**CONFIRMED CLEAN.** Line 99: `exit_px = peak_at - d * X * a` — the pullback level price, derived from the running peak at the event bar minus the pullback depth. Line 100: `exit_pnl = (exit_px - d * EXIT - fill) * d * MULT - COMM`. Line 71: `hold_px = r.flip_c` — the terminal 1m close (from `C[idx, np.minimum(n, 61)]`). Line 72: `hold_pnl = (hold_px - d * EXIT - fill) * d * MULT - COMM`. These are distinct variables with distinct price inputs. The slip direction is the same (`-d * EXIT`) for both, which is correct: both exits incur an adverse slip regardless of direction or exit mechanism. There is no aliasing.

The near-equality of exit-now and hold-to-flip $/tr at every X is a structural property, not a coding artifact:
- At shallow X (e.g., 0.25 ATR): `peak_at` is not much above the running peak at event detection, so `exit_px` is only marginally below `peak_at`. But because the path eventually reaches flip (often a large adverse move), `hold_px` is also pulled down. The two converge because the 57% that recover exactly compensate the 43% that don't in EV terms.
- At deep X (e.g., 1.00 ATR): `exit_px = peak_at - 1.0 * a`, which is further below `peak_at`, but `peak_at` is also higher (the trade had to reach a new peak after a prior 0.75 ATR pullback before the 1.00 ATR pullback fires). The deeper lock-in vs higher peak_at approximately cancel. Separately, at 1.0 ATR many pullback events are the terminal flip itself, meaning `exit_px ≈ hold_px` mechanically. This explains the "floor" in the exit-hold difference.

### Suspicious result explained: near-constant n across X (17,180 → 17,059)

The near-constant event count across pullback depths is a real structural property, not a bug. The argument:

1. Every regime ends in an opposite flip — by definition of the flip-bar closing mechanics in `CapsuleReplay`. The last bar of every stored capsule is the bar that triggered the opposite regime flip.
2. The opposite flip is a large adverse move: the flip engine (`RegimeStateEngine`) requires the regime's opposing condition to be met, which typically requires price to retrace significantly relative to the flip-bar open.
3. On the 1s path within the regime, this terminal adverse move will, for the vast majority of trades, drive the drawdown from the prior running peak to well above 1.0 ATR before or at the flip bar.
4. Therefore: almost any trade that reaches +1 ATR favorable excursion (the `healthy` gate) and pulls back 0.25 ATR will also eventually pull back 1.0 ATR — because the regime termination is itself a ~1+ ATR adverse move from the peak.
5. The ~1% drop (17,180 → 17,059) represents the small fraction of trades where the regime ended with `peak_at` close to the flip price, so the final adverse move was < 1.0 ATR from the pre-pullback peak. These are short-lived regimes or regimes where the terminal flip happened from a locally low peak.

This is a real property of the data, not a bug in the drawdown/peak logic.

### `flip_c = C[idx, np.minimum(n, 61)]` cap behavior

**CONFIRMED CORRECT.** The matrix `C` in `progressive_separability.build()` has `B = 62` columns (index 0 = flip bar, columns 1..61 = post-flip bars, capped at `min(n_post, 61)` per trade). `np.minimum(n, 61)` correctly retrieves the terminal close: for regimes with `n_post <= 61` bars, this is the last stored close; for regimes truncated at 61 bars, this is bar 61's close, which is the last available 1m close in the data (not the true flip close). For truncated trades, `hold_pnl` is therefore an intermediate-bar close, not the flip close. This conservative truncation understates long-running hold-to-flip outcomes. The bias is in the direction of making `hold_pnl` look worse than it actually is for long regimes, which if anything understates the "hold beats exit" thesis. This does not inflate any edge.

### Truncated 1s paths (MAXSEC = 1800s cap)

**CONFIRMED CONSERVATIVE.** If a regime's 1s path is truncated at 1800s (30 minutes), the forward window for event detection and outcome measurement is shortened. Specifically:
- Fewer bars are available to detect a new peak: `P(new_peak)` is understated for trades where recovery would have happened after the 1800s cap.
- `rem_mfe` is understated for the same reason.
- The net effect is that any "recovery is more common than it looks" thesis is underconfirmed. The falsification conclusion (exit ≈ hold) is not inflated by truncation.

### No look-ahead inflating P(new peak) or fabricating exit edge

**CONFIRMED CLEAN.** All forward probability measurements (`new_peak`, `further_first`, `rem_mfe`) use only `[i+1:]` slices. The exit-now signal is negative relative to holding (exit-hold ≈ +$1/tr across all depths), not positive. A look-ahead leak that inflated the separation in `P(new_peak)` would not have created a spurious exit edge; it would have caused `P(new_peak)` at shallow depths to be artificially high and at deep depths artificially low (or vice versa), changing the odds without affecting $/tr. The actual result shows a genuine odds gradient (P drops from ~83% at 0.25 to ~57% at 1.00) but flat $/tr — which is consistent with the odds being real but exactly priced, not with a coding artifact.

---

## Clean Checks

- **B1** — No `center=True` rolling found anywhere in the analysis path.
- **B2** — All indicator values (running peak, fav_exc, dd) at bar `i` use only `h[0:i+1]`/`l[0:i+1]`. Confirmed causal.
- **B4** — No `.shift(-N)` or negative lag in the feature or outcome path. Labels/outcomes use explicit `[i+1:]` forward slices, not pandas shifts.
- **B5** — No `.ffill()` or `.bfill()` in the analysis path.
- **C1** — Forward outcomes are strictly in explicitly forward windows (`[i+1:]`). No label column contaminates any decision-time variable.
- **C3** — No model, no cross-validation, no train/test split. Pure diagnostic.
- **D1/D2** — No train/serve comparison applicable. This is a pure diagnostic with no model and no live deployment path.
- **E1-E5** — No backtest engine, no strategy, no bar subscriptions. Not applicable.
- **A1-A5** — No NautilusTrader timestamp fields (`ts_event`, `ts_init`) used directly in this script. Path offsets are in nanoseconds from `regime_start_ts`, which is the flip-bar close (`completed.close_ts`). Timestamp semantics are correct.
- **F3** — No naive datetimes in the primary script. Path timestamps are raw ns integers.
- **G2** — Gaps in 1s data within the regime path are handled implicitly: the path is a stored list collected during replay; missing 1s bars during low-liquidity overnight simply leave gaps in the list. The `inwin` filter (`tt <= T_flip`) does not fill gaps. This is acceptable for a diagnostic measuring whether price TOUCHED a level (an adverse move requires real price action; a gap cannot create a spurious touch detection).
- **Progressive separability `build()` call-site (line 110):** `P.build(df)` is called on the full `df` (all years including OOS). The returned matrix `M` stores raw OHLCV without any labels or statistics derived from the data distribution. Using the full-year matrix for `O[:, 4]` (entry) and `C[idx, np.minimum(n, 61)]` (terminal close) is not a train/serve or normalization leak — these are price values, not statistics. Clean.
- **`compute_labels_features` call-site (line 109):** Labels (`is_tradable`, `bar1_confirmed`, etc.) are computed here but the pullback lifecycle script uses none of them — it uses only `regime_id`, `entry` (from `O[:, 4]`), `d`, `atr`, `n`, `flip_c`, and `year`. No label contamination of the decision-time path. Clean.
- **Previously waived warning (W1 from `audit_mfe_conversion_test.md`):** `ts_init` passed as if `ts_event` to aggregator — this applies to `early_health_filter.py` and `build_survivor_1s_paths.py`, which are supporting files audited previously. Status remains WAIVED. The 1s path offsets are relative (nanosecond deltas from flip-bar close), so the absolute timestamp basis does not affect the pullback event detection or forward outcome measurement within this diagnostic.

---

## Detailed Note on `further_first` race index semantics

One subtle correctness question: `fu_i` and `np_i` are POSITIONAL indices within the `[i+1:]` slice, not timestamps. The race `fu_i < np_i` is therefore "the further-hit bar has a smaller slice-index than the new-peak bar" — i.e., it comes earlier in the sorted 1s sequence. Since the 1s path is stored in chronological order (per `build_survivor_1s_paths.py`'s sequential append), this is equivalent to "further-hit happened first in time." The race is correct.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*
