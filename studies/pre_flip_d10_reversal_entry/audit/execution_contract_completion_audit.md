# Completion audit: isolated execution-contract fixture

Date: 2026-07-11  
Scope: `build_execution_contract_report.py` and generated `execution_contract_comparison.parquet`, `execution_contract_trace.json`, `execution_contract_report.md`  
Status: **PASS — isolated fixture complete**

This status applies only to the execution-contract fixture. The full D10 study remains blocked and was not executed.

## Artifact reconciliation

The generated report values reconcile exactly to `execution_contract_trace.json` and the fixture formulas.

### Shared bar contract

The four trace bars each satisfy the repository's one-second convention:

```text
ts_init = ts_event + 1,000,000,000 ns
```

The selected decision bar has `ts_init = 1741042801000000000`, equal to the candidate entry bar's `ts_event`. The candidate entry bar is:

```text
ts_event  1741042801000000000
ts_init   1741042802000000000
open      20511.25
high      20511.75
low       20505.25
close     20508.25
```

The assumed one-tick long stop is `20511.00`; `20505.25 <= 20511.00`, so `entry_bar_crosses_stop = True` is correct.

### NT native contract

The trace records:

- entry submission at `1741042801000000000`;
- engine entry fill at that timestamp at `20514.25`;
- native stop submission in the fill handler at that timestamp, trigger `20511.00`;
- engine stop fill at `1741042802000000000` at `20511.00`.

The comparison/report reproduce those actual values. Gross PnL is correct:

```text
(20511.00 - 20514.25) * $20 = -$65.00
```

The assumed explicit-open/trigger result is `-$5.00`, so native difference versus that assumption is `-$60.00`, also correct.

The report accurately concludes that the stop submitted inside the entry-fill callback was not active against the entry bar's already-processing OHLC. It does not claim the engine entry fill equals the next bar open; it preserves the observed `20514.25` versus expected open `20511.25` discrepancy.

### Explicit next-open OHLC label

The comparison correctly leaves actual entry and stop fill fields null. It records:

- assumed entry timestamp `1741042801000000000`;
- assumed entry price `20511.25`;
- possible touch window `[1741042801000000000, 1741042802000000000]`;
- assumed stop price `20511.00`;
- no exact stop-fill timestamp.

The assumed gross label is correctly calculated:

```text
(20511.00 - 20511.25) * $20 = -$5.00
```

The evidence and PnL-basis fields clearly identify this as a one-second OHLC adverse-touch assumption, not an NT fill or tick-path accuracy claim.

### Close-detected contract

The trace records:

- engine entry fill at `1741042801000000000` at `20514.25`;
- completed entry-bar callback/touch detection and exit submission at `1741042802000000000`;
- engine market-exit fill at that timestamp at `20508.25`.

Primary gross PnL uses both engine-observed prices:

```text
(20508.25 - 20514.25) * $20 = -$120.00
```

Difference versus the assumed `-$5.00` contract is `-$115.00`. The separately named exit-only normalized diagnostic is also correct:

```text
(20508.25 - 20511.25) * $20 = -$60.00
```

The primary and normalized bases are not conflated in the report.

## Causality and claim review

- Entry orders are decided from the first completed bar callback.
- The close-detected exit uses only the currently completed bar's low and submits at its `ts_init`; the subsequent fill is engine-produced.
- The path is selected ex post using the candidate entry bar low solely to force the edge case. The report explicitly discloses this and makes no frequency, representativeness, or strategy-economics inference.
- Actual NT fields and assumed OHLC fields are separated.
- The report states that intrabar timing is unknown without tick/quote data and makes no fill-anchored accuracy claim.
- The close-detected convention is described as delayed-information and not necessarily economically conservative.
- All reported PnL is gross and uses the stated NQ multiplier of `$20`; no inconsistent costs are applied.

## D10 isolation

`build_execution_contract_report.py` defines its own minimal `ContractFixture`. It does not import or instantiate `PreFlipD10Strategy`, does not load frozen scores or D10 events, and does not call the D10 policy runner. The generated artifacts contain only two four-bar NT mechanics runs and one OHLC research-label row. No D10 policy-run output is attributable to this fixture.

## Findings

**CRITICAL: 0**  
**WARNING: 0**

## Conclusion

The isolated fixture is complete, internally consistent, causally labeled, and appropriately limited. Its evidence supports only the documented execution-contract comparison. It does **not** authorize or validate the full D10 strategy.

