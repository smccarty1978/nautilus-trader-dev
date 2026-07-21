# Completion Look-Ahead, Execution, and Reporting Audit

**Study:** `CODEX_5_X_W4_PRICE_RESPONSE_DELAYED_ENTRY_REPLAY`

**Status:** **PASS**

**Findings:** **0 CRITICAL, 0 WARNING**

## Completion conclusion

The completed PR10/PR30 replay is causally correct, exactly reproducible from the frozen repaired entries and raw one-second bars, internally reconciled, and faithfully reported. I independently reconstructed all **8,766** policy rows without importing or calling `run_replay.py`; every exported trade-diff field matched, with zero numeric, timestamp, categorical, boolean, or null-state discrepancies. All policy summaries, accounting cohorts, report tables, hashes, and material narrative claims also reconciled exactly.

## Independent full-row reconstruction

The audit independently loaded:

- the frozen 2025 and 2026 raw one-second OHLC inputs;
- the frozen repaired established-fade trade files;
- the frozen Policy A rows from `isolation_trade_diffs.parquet`;
- the final `price_response_trade_diffs.parquet` only as the comparison target.

For each of 4,383 candidates and both fixed delays, the audit separately recomputed the completed confirmation mark, virtual directional PnL, approval/rejection, delayed entry, timeout, alignment state, stop path, scheduled exit, realized PnL, fill-change flags, Policy A pairing, and all exported metadata. The result was:

- reconstructed rows: **8,766**;
- duplicate `(policy_id, trade_id)` keys: **0**;
- column mismatches across all 40 exported fields: **0**;
- 2025 rows: **3,246 PR10 + 3,246 PR30**;
- 2026 rows: **1,137 PR10 + 1,137 PR30**.

Approved counts were **2,105 PR10** and **1,811 PR30**. Rejections reconciled exactly:

- PR10: 2,127 adverse response, 141 regime ended by confirmation, 10 aligning flip before delayed entry;
- PR30: 2,050 adverse response, 507 regime ended by confirmation, 15 aligning flip before delayed entry.

## Causal timestamp and execution audit

- The mark is always the latest raw bar whose full `[ts_event, ts_event + 1s)` interval completed by the gate. Mark staleness was never negative; it ranged from 0–9 seconds for PR10 and 0–29 seconds for PR30, reflecting genuine raw gaps rather than imputation.
- Every approved fill is the first available raw open strictly after the gate. The observed wait was at least one second in every case, with **0** equal-or-earlier fills. Maximum waits were 45 seconds for PR10 and 28 seconds for PR30.
- No approved trade had an aligning flip at or before its gate or delayed fill. All regime-end rejections, including flips hidden before a later raw open, matched the independent reconstruction.
- Every timeout equals actual delayed fill plus exactly 300 seconds. There were **0 timeout-anchor errors**.
- Every approved stop submission timestamp equals its delayed fill, and all approved rows mark the stop active on the entry bar. Long/short touch logic, gap-through-open fills, 1.25 ATR pre-flip stops, and 1.50 ATR post-flip stops matched on every path.
- Alignment at exactly the timeout suppresses timeout; alignment after a decision already made at the timeout does not retroactively cancel it. Raw-gap ordering matched on all reconstructed paths.
- Scheduled opposing-flip exits fill at the first available raw open at or after the observed scheduled decision. Its fill-bar range is excluded after the market-open exit.
- Exit counts reconciled exactly: PR10 had 554 pre-flip stops, 229 post-flip stops, 293 timeouts, and 1,029 scheduled opposing-flip exits; PR30 had 436, 231, 238, and 906 respectively.
- There were **0 exits before entry**, **0 PnL identity errors**, **0 approved rows missing fills**, and **0 approved rows crossing a completed-regime boundary before entry**.

## Policy A pairing and frozen opportunity set

- Every repaired entry paired to the expected frozen Policy A `trade_id` and exact original entry timestamp.
- Policy A exit reason and PnL were identical across the two delayed-policy copies for every trade.
- The frozen raw inputs, repaired trades, Policy A diffs, upstream completion audit, and upstream manifest all retain the SHA-256 values in `input_freeze.json`.
- The runner, config, freeze, pre-execution audit, and pre-execution authorization retain the hashes authorized before the first test/replay.
- Both 2025 and 2026 `_work` diff artifacts match their reconciliation seals and both seals report zero blocking errors.
- The 2026 path is code-gated on the clean, hash-bound 2025 predecessor and unchanged 2025 artifact. The completed artifacts satisfy that gate.

## Summary metrics and denominators

The audit independently regenerated all **33** rows and every numeric field of `price_response_policy_results.parquet`; maximum absolute error was zero. This covers combined, 2025, 2026, long fade, short fade, ETH, RTH, and all four direction/session intersections for Policy A, PR10, and PR30.

The denominators are correct and clearly disclosed:

- candidate, approved, and skipped counts describe the full frozen opportunity set;
- total net PnL and chronological closed-trade-sequence drawdown assign zero PnL to skips;
- executed-trade mean, profit factor, win rate, stop rate, timeout rate, and average winner/loser use approved trades only;
- `mean_net_pnl_per_candidate_usd` separately reports opportunity-set EV.

Zero-valued skipped candidates preserve chronological ordering without changing cumulative equity. Independently recomputed drawdowns matched exactly, including combined Policy A **$34,574.02**, PR10 **$43,756.88**, and PR30 **$23,743.63**.

## Overlapping accounting and decomposition

All **24** rows and all fields of `price_response_trade_accounting.parquet` were independently rebuilt with zero error. The table contains the four requested skipped original-outcome cohorts, regime end before delayed entry, aggregate approved delayed-entry slippage, improved/worsened/unchanged fills, later timeouts, pre-alignment stops, and reached-alignment trades. The report correctly warns that these cohorts overlap and must not be summed.

The removal-versus-delay decomposition reconciled exactly:

| Policy | Year | Skipped-candidate benefit | Approved-trade change | Total change |
|---|---:|---:|---:|---:|
| PR10 | 2025 | +$42,670.74 | -$65,234.06 | -$22,563.32 |
| PR10 | 2026 | +$25,942.91 | -$24,171.11 | +$1,771.80 |
| PR30 | 2025 | +$101,400.94 | -$100,193.49 | +$1,207.45 |
| PR30 | 2026 | +$31,899.75 | -$38,681.22 | -$6,781.47 |

Fill classification also reconciled: PR10 had 284 improved, 1,714 worsened, and 107 unchanged fills; PR30 had 164, 1,581, and 66. The mean directional fill deterioration was 2.18 points for PR10 and 3.74 for PR30.

## Final report verification

The completion audit parsed and independently regenerated each report table:

- full policy-results table: **33/33 rows exact** after displayed rounding;
- year-by-direction/session table: **16/16 rows exact**;
- removal-versus-delay table: **6/6 rows exact**;
- overlapping trade-accounting table: **24/24 rows exact**.

All material narrative claims are supported. Neither policy improves Policy A in both years: PR10 changes 2025 by -$22,563.32 and 2026 by +$1,771.80; PR30 changes them by +$1,207.45 and -$6,781.47. Both policies improve long-fade ETH in both years:

- PR10: +$6,512.09 in 2025 and +$5,409.01 in 2026;
- PR30: +$10,858.74 in 2025 and +$9,415.00 in 2026.

The report therefore correctly uses **`LONG_ETH_IMPROVES_BUT_NOT_GLOBAL`**. It explicitly treats long ETH as retrospective subgroup evidence rather than a newly authorized policy.

## Guardrails, provenance, and tests

- The final outputs contain only predeclared PR10 and PR30. The virtual threshold is exactly zero and no additional delay, filter, W4 threshold, stop grid, MFE continuation, post-flip retained-profit rule, or alternate timeout was introduced.
- Frozen upstream hashes demonstrate no W4 retraining or input substitution.
- The runner enforced 2025 completion before 2026. No 2026 result selected or changed a candidate rule.
- The result manifest matches the runner, config, freeze, report, and all three result artifacts byte for byte.
- The report clearly limits the evidence to a causal one-second OHLC research replay and does not claim NT-native executable or tick-level validation.
- Test command: `python -m pytest studies/codex_5_w4_price_response_delayed_entry/tests/test_replay.py -q`.
- Test result: **9 passed**.

## Final determination

The study satisfies its frozen causal contract, execution rules, accounting requirements, reporting requirements, provenance controls, and selection-isolation guardrails. Completion is authorized with **0 CRITICAL and 0 WARNING**.
