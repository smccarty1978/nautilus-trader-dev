# Pre-execution audit: isolated execution-contract fixture (rerun)

Date: 2026-07-11  
Scope: `build_execution_contract_report.py` only  
Gate status: **PASS — fixture may execute**

This pass authorizes only the isolated execution-contract fixture. It does not authorize the D10 policy pipeline or final policy economics.

## Causality

- The NT entry is submitted from the first completed 1-second bar callback.
- The native stop is submitted only in the entry-fill callback.
- The close-detected exit uses the low of the currently completed bar at `ts_init` and submits its market exit without inspecting the next bar.
- No future bar is used to decide an order inside either NT fixture strategy.
- `select_path()` does use the candidate entry bar's low to choose an ex-post diagnostic path. The generated report now discloses this explicitly and correctly limits it to a forced mechanics edge case, not a trade-selection rule, representative sample, or economics result.

## Timestamp and evidence semantics

The prior false precision is resolved:

- The explicit-next-open OHLC row leaves actual entry and actual stop-fill timestamps/prices null.
- Its entry is stored under `assumed_entry_fill_*`.
- Its stop touch is bounded only by `assumed_stop_touch_window_start = ts_event` and `assumed_stop_touch_window_end = ts_init`.
- It records only an `assumed_stop_fill_price`; no exact intrabar fill timestamp is claimed.
- NT-observed entry/exit timestamps and prices remain in actual fields for the native and close-detected contracts.
- All timestamp columns are explicitly constructed with pandas nullable `Int64`, preventing null rows from coercing nanosecond integers to floating point.

These labels are consistent with one-second OHLC information limits. The report also states that intrabar ordering is unresolved and no tick/quote fill accuracy is claimed.

## PnL comparability

The prior mixed-basis comparison is resolved:

- Native primary PnL uses its engine-observed entry and exit.
- Close-detected primary PnL also uses its engine-observed entry and exit.
- The close-detected exit-only comparison normalized to the expected open is retained in a separately named `exit_only_normalized_pnl_from_expected_open_usd` field.
- Every row carries an explicit `pnl_basis`.
- The OHLC contract's gross PnL is clearly labeled as an assumed open-entry/adverse-touch research value rather than an observed fill result.
- Missing fills produce null PnL/difference values through guarded calculations rather than arithmetic failure.

The table is suitable for mechanics comparison so long as the assumed OHLC row is not ranked as equivalent observed execution evidence. Its `evidence_type` and `pnl_basis` make that distinction explicit.

## Claim boundaries

- The close-detected contract is now described as delayed-information and expressly not guaranteed economically conservative under gaps.
- The report does not claim fill-anchored stop accuracy.
- It does not infer frequency, expectancy, or policy performance from the ex-post selected path.
- No D10 strategy, score lookup, policy event, or D10 economics path is imported or invoked.
- The generated report keeps the full D10 study blocked pending explicit contract selection.

## Findings

**CRITICAL: 0**  
**WARNING: 0**

## Required post-run checks

After this fixture executes, verify before relying on its report:

1. Nullable timestamp columns remain integer nanoseconds/null after parquet round-trip.
2. Trace events reconcile exactly with the two NT-observed rows.
3. The assumed OHLC row retains null actual fill fields.
4. No D10 policy result files or policy-run directories were created or modified by the fixture.

