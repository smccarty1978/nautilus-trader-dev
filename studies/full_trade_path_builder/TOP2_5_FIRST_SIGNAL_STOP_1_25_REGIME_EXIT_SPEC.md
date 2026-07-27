# Top 2.5% First-Signal Entries: 1.25 ATR Stop and Regime-Flip Outcomes

Status: FROZEN

## Objective

Describe the realized and path outcomes of the canonical 5,836 selected
first-signal Top-2.5% entries under a fixed 1.25 ATR stop which remains active
through the opposing confirmed regime-flip exit.

This is intentionally **not** an all-entry study. The canonical path store has
one selected first signal per qualifying regime. The user selected this
restricted population after the all-entry population was shown to lack
entry-anchored paths for 63,596 of 69,432 qualifying observations.

## Inputs and population

Only these immutable artifacts may be read:

- `consolidated/canonical_trade_summaries_all.parquet`
- `consolidated/canonical_trade_paths_all.parquet`

They must be opened through `implementation/canonical_research_loader.py`.
Every canonical summary row is in scope. Expected population: 5,836 unique
`trade_id` values, comprising 3,329 bullish-fade short entries and 2,507
bearish-fade long entries. No canonical parquet may be modified.

The frozen Top-2.5% rule is the builder's selected first signal using the
direction-specific frozen thresholds:

- bullish fade / short: probability >= 0.5697449423968936
- bearish fade / long: probability >= 0.5641320087327389

## Frozen fields

- entry time: `checkpoint_decision_ns`
- entry/reference price: `checkpoint_reference_price`
- entry ATR: `atr_at_entry`
- confirmation: `confirm_flip_ns`
- opposing flip terminal event: `fallback_exit_flip_ns`
- path time: `timestamp_close_ns`
- stop touch: directionally adverse 1-second high/low, represented by
  `adverse_intrabar_extreme_atr <= -1.25`

## Event and fill ordering

The path rows represent completed one-second bars.

1. Detect a stop touch using the bar high/low.
2. If a confirmation or opposing-flip boundary occurs on that same bar,
   classify `AMBIGUOUS EVENT ORDER`; do not impose a favorable order.
3. Otherwise, a stop submits an exit and fills at the **next path bar open**,
   matching project H4. The trigger price is never credited as a fill.
4. If no next path row exists, the stop fill is unobservable and the trade is
   `CENSORED / UNRESOLVED`.
5. If the next-bar fill timestamp competes with a canonical boundary, the
   outcome is `AMBIGUOUS EVENT ORDER`.
6. The 1.25 ATR stop remains active after confirmation.
7. A survivor exits at the canonical opposing confirmed flip and uses
   `fallback_exit_mark_return_atr` / points.

Stop-touch time and stop-fill time are both retained. MFE/MAE for a stopped
trade ends at the stop-touch bar because subsequent movement belongs to order
latency, not the decision path. Its realized PnL uses the next-bar open.

## Outcomes

Each trade maps to exactly one:

- `STOPPED BEFORE CONFIRMATION`
- `STOPPED AFTER CONFIRMATION`
- `REGIME-FLIP EXIT FOR PROFIT`
- `REGIME-FLIP EXIT FOR LOSS`
- `REGIME-FLIP EXIT FLAT`
- `CENSORED / UNRESOLVED`
- `AMBIGUOUS EVENT ORDER`

Flat means absolute realized points <= 0.125 points (half an NQ tick).
Ambiguous and censored trades have null realized return.

## Excursions

All excursions use entry price and `atr_at_entry`. Full-trade excursion includes
the terminal bar. Because OHLC cannot order favorable and adverse extremes
within a stop-touch bar, terminal-bar-inclusive stopped-trade MFE is descriptive
and explicitly disclosed.

Confirmation excursion ends at `confirm_flip_ns`. Stopped-before-confirmation
trades instead use excursion through the stop-touch bar. Censored excursion ends
at the last observed path row.

## Validation

- one summary and one outcome per `trade_id`
- path timestamps strictly increasing within trade
- all terminal classes mutually exclusive and counts reconcile
- resolved trades have exactly one resolved outcome
- deterministic fixed-seed sample of 100 independently replayed from path rows
- no classification mismatches in that sample
- causal lint clean
- pre-execution and completion causal audits clean
- contract validation clean

## Deliverables

- `analysis/analyze_top2_5_stop_and_regime_exit.py`
- `results/top2_5_stop_1_25_regime_exit_results.parquet`
- `results/top2_5_stop_1_25_regime_exit_summary.json`
- `TOP2_5_STOP_1_25_REGIME_EXIT_REPORT.md`

Final verdict is exactly `RESULTS VALID`, `RESULTS VALID WITH LIMITATIONS`, or
`RESULTS NOT VALID`.

## Out of scope

All-entry inference, alternate stops, targets, optimization, retraining,
threshold changes, canonical rebuilds, transaction-cost assumptions, and policy
recommendations.
