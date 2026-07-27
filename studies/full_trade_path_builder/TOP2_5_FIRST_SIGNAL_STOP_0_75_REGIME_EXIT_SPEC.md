# Top 2.5% First-Signal Entries: 0.75 ATR Stop and Regime-Flip Outcomes

Status: FROZEN

## Objective and population

Repeat the accepted Top-2.5% first-signal stop study on the same 5,836
entry-anchored canonical paths, changing only the fixed stop distance from
1.25 ATR to **0.75 ATR**.

This remains a one-entry-per-qualifying-regime study, not an all-observation
study. It contains 3,329 bullish-fade shorts and 2,507 bearish-fade longs.

## Incorporated contract

`TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md` is incorporated in full
except for the explicit replacements below:

- stop touch: `adverse_intrabar_extreme_atr <= -0.75`
- stop distance remains 0.75 ATR before and after confirmation
- study id: `top2_5_first_signal_stop_0_75_regime_exit`
- results: `results/top2_5_stop_0_75_regime_exit_results.parquet`
- summary: `results/top2_5_stop_0_75_regime_exit_summary.json`
- report: `TOP2_5_STOP_0_75_REGIME_EXIT_REPORT.md`

All other frozen rules are unchanged: canonical inputs and first-signal
thresholds, completed one-second high/low touch detection, next-path-bar open
price and timestamp fills, same-boundary ambiguity, final-bar censoring,
canonical confirmation and opposing-flip marks, 0.125-point flat tolerance,
terminal-bar excursion measurement, seven mutually exclusive outcomes, and
fixed-seed independent replay of 100 paths.

## Validation and verdict

Counts must reconcile to 5,836 unique trades; causal lint, pre-execution causal
audit, completion causal audit, contract check, path ordering, and independent
replay must all pass.

The report ends with exactly `RESULTS VALID`, `RESULTS VALID WITH LIMITATIONS`,
or `RESULTS NOT VALID`.

## Out of scope

No stop comparison or optimization, profit targets, policy recommendation,
retraining, threshold changes, canonical rebuild, or transaction-cost overlay.
