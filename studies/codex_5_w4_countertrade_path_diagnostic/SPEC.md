# codex_5 W4 Countertrade Path Diagnostic

## Purpose

Describe—not optimize—the price and W4 paths of the already-frozen CODEX 5.X
established-regime fade trades from 2025 and 2026.

## Frozen inputs

The exact input hashes are stored in `config.json`. The study fails closed if
any trade, score, raw-bar, atlas, or policy input changes.

## Time and price contract

- Databento 1-second `ts_event=t` is open-labelled and covers `[t,t+1s)`.
- A checkpoint at boundary `t` uses price ranges with `ts_event < t`.
- The checkpoint mark is the last completed 1-second close before `t`.
- Entry uses the stored explicit fill open. An aligning flip is marked at the
  first available 1-second open at or after its decision boundary.
- Final scheduled exits use their stored boundary-open fill.
- A stop is only localized to its 1-second bar. Primary pre-stop MFE excludes
  that stop bar; an OHLC upper bound including the stop bar is also stored. This
  avoids claiming unknown favorable/adverse ordering inside the stop bar.
- OHLC peaks retain their bar `ts_event` for localization but are checkpointed
  and timed at `ts_event+1s`, when the `[t,t+1s)` range is complete. A peak set
  by a known scheduled-exit open is available exactly at the exit timestamp.
- Price excursions are divided by the trade's `atr_at_checkpoint`, the same
  denominator as its frozen 1.5 ATR stop.

## W4 contract

- Before the aligning flip, W4 belongs to the original prevailing regime.
- After the aligning flip, W4 belongs to the new aligned regime. It is not
  carried across a regime boundary.
- Latest-score joins are backward-only and no more than five seconds stale.
- W4 slopes use same-regime observations at least 15/30/60 seconds earlier.
- An adverse post-flip W4 warning is the first aligned-regime observation at or
  above that direction's already-frozen threshold. This is diagnostic only.
- `w4_change_from_entry` is retained across the flip but explicitly marked as a
  cross-regime comparison after the aligning flip.

## Fixed checkpoints

Every five seconds from entry through the later of entry+300s, aligning
flip+120s, or actual exit, plus exact rows for entry, +30/+60/+90/+120/+180/
+300s, aligning flip, +60/+120s after it, actual holding-period peak MFE, and
final exit.

Fixed horizons after an early exit are marked `counterfactual_after_exit=True`
to prevent survivor-biased early-window summaries.

## Outcome groups

- `stop_before_aligned_flip`
- `stop_after_aligned_flip`
- `opposite_flip_exit_winner` (stored net PnL > 0)
- `opposite_flip_exit_loser` (stored net PnL <= 0)

## Guardrails

No threshold search, parameter grid, policy simulation, or 2026-driven
selection is permitted. Findings may motivate at most three later hypotheses.
