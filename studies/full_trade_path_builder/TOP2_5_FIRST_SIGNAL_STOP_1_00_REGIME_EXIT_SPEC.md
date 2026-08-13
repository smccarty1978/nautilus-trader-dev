# Top 2.5% First-Signal Entries: 1.00 ATR Stop and Regime-Flip Outcomes

Status: FROZEN

## Objective and population

Repeat the accepted Top-2.5% first-signal stop study on the same 5,836
entry-anchored canonical paths, changing only the fixed stop distance to
**1.00 ATR**. The population remains 3,329 bullish-fade shorts and 2,507
bearish-fade longs, one selected first signal per qualifying regime.

## Incorporated contract

`TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md` is incorporated in full
except for these replacements:

- stop touch: `adverse_intrabar_extreme_atr <= -1.00`
- stop remains 1.00 ATR before and after confirmation
- study id: `top2_5_first_signal_stop_1_00_regime_exit`
- results: `results/top2_5_stop_1_00_regime_exit_results.parquet`
- summary: `results/top2_5_stop_1_00_regime_exit_summary.json`
- report: `TOP2_5_STOP_1_00_REGIME_EXIT_REPORT.md`

All remaining rules are unchanged: canonical inputs, frozen selection
thresholds, completed one-second high/low stop detection, next-path-bar open
price and timestamp fills, boundary ambiguity, final-bar censoring, canonical
confirmation and opposing-flip marks, 0.125-point flat tolerance, seven
exclusive outcomes, and fixed-seed independent replay of 100 paths.

## Acceptance and scope

Counts must reconcile to 5,836 unique trades. Causal lint, pre-execution and
completion causal audits, contract validation, path ordering, and independent
replay must pass.

No stop optimization or comparison, targets, policy recommendation, retraining,
threshold change, canonical rebuild, or transaction-cost overlay is permitted.

The report ends with exactly `RESULTS VALID`, `RESULTS VALID WITH LIMITATIONS`,
or `RESULTS NOT VALID`.
