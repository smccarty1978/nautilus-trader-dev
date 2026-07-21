# 1m Bar Source Reconciliation

Sample window: 2024-01-08 00:00:00+00:00 -> 2024-01-15 23:59:59+00:00
Catalog: data/catalog/NQ_v0_2020_2026

- Matched close_ts: 8038
- Real-only (missing synthetic bucket): 1
- Synthetic-only (missing real bar): 0
- max_abs_diff open: 0.0
- max_abs_diff high: 0.0
- max_abs_diff low: 0.0
- max_abs_diff close: 0.0

**Result: FAIL (script threshold), PASS (substantive)**

The single "real-only" close_ts is `2024-01-15 23:59:00 UTC` -- the
very last 1m bar of this sample window. `TimeframeAggregator` by
design "does NOT close the final partial bucket; that data is
discarded for safety" (see its module docstring) -- this standalone
reconciliation script truncates the 1s stream at the sample window's
end, so the synthetic aggregator's final in-progress 1m bucket never
receives the next-bucket 1s bar needed to close it. This is an
artifact of this validation script's own sample-window boundary, not a
discrepancy that exists in the live NT strategy (which runs
continuously across the full backtest date range with subsequent bars
always available, so no such truncation occurs there).

Every bar that DID match is **byte-identical** across all 4 OHLC
fields (max_abs_diff = 0.0 across 8,038 matched close_ts) over a full
week. The two 1m sources (`bar_type_1m` catalog subscription vs the
1s-aggregated synthetic bucket) agree. WARNING [D1-adjacent] from the
pre-execution lookahead audit is resolved.
