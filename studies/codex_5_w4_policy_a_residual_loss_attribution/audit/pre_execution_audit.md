# Pre-Execution Lookahead and Attribution Audit

**Status:** **PASS — authorized for the frozen descriptive attribution build**

**Findings:** **0 CRITICAL, 0 WARNING**

## Scope

Audited before executing the attribution builder:

- `SPEC.md`
- `config.json`
- `input_freeze.json`
- `build_attribution.py`
- `tests/test_attribution.py`

The study `results/` directory contained no generated artifacts at authorization time. This authorization covers only the exact hashes recorded in `pre_execution_authorization.json`.

## Frozen input and analysis-only scope

- The sole policy input is the exact `POLICY_A_COMBINED_1P25_300S` subset of the independently audited isolation trade-level output: 4,383 unique repaired entries, comprising 3,246 rows for 2025 and 1,137 for 2026.
- The frozen isolation diff, isolation completion audit, isolation manifest, both repaired trade files, and both raw one-second inputs match every SHA-256 in `input_freeze.json`.
- The one-to-one join uses the canonical trade IDs produced from the chronologically sorted repaired yearly trades. Runtime gates require 4,383 joined rows, no missing confirming flip, and exact entry-timestamp parity with the policy rows.
- No W4 training/scoring, entry construction, fill replay, policy simulation, parameter selection, threshold search, or candidate filter is performed. The study is retrospective descriptive attribution of already-frozen Policy A outcomes.
- Both years are summarized descriptively. The frozen dimensions are explicitly not presented as 2026-selected trading filters.

## Frozen buckets and source semantics

- Exact config validation freezes all boundaries before the build:
  - align time: `[0,60]`, `(60,120]`, `(120,300]`, and `>300` seconds, plus `no_flip_before_exit`;
  - entry regime age: `<15`, `15-30`, `30-60`, `60-120`, and `>=120` minutes;
  - W4 score: `<0.70`, `0.70-0.75`, `0.75-0.80`, and `>=0.80`;
  - timeout MFE: `<0.25`, `0.25-0.50`, `0.50-0.75`, `0.75-1.00`, and `>=1.00` ATR, plus not alive;
  - timeout PnL: `<-1.00`, `-1.00--0.50`, `-0.50-0.00`, `0.00-0.50`, `0.50-1.00`, and `>=1.00` ATR, plus not alive.
- Align time uses the frozen confirming-flip timestamp relative to entry. A Policy A trade whose pending timeout order fills after a late `>300s` flip can be described in the late bucket even though the flip did not causally cancel the timeout. If the flip is at or after the actual exit and Policy A did not reach it, the row is `no_flip_before_exit`.
- W4 score is the repaired causal decision/checkpoint score. Upstream `regime_age_s` is also measured at that decision. Exact entry-time regime age is correctly exported and bucketed as `regime_age_s + (entry_fill_ts - decision_ts) / 1s`; negative entry delay is rejected. The source has nonzero fill delay, so this distinction is materially documented even though no frozen row crosses the selected bucket edges.
- Runtime exact-value checks prevent any unapproved bucket or timeout configuration change.

## Timeout-state audit

- The timeout instant is exactly `entry_fill_ts + 300s`.
- Alive state is evaluated at the timeout-open decision instant. An exit strictly after timeout is alive. A stop whose containing one-second bar is labelled exactly at timeout is alive because the stop occurs in that bar's range after the open. A market opposing-flip exit at the timeout open is not alive.
- MFE and mark-to-market PnL use only completed open-labelled bars with `ts_event < timeout`. The timeout-labelled bar is excluded.
- MFE is favorable high/low movement from the stored entry fill, direction-adjusted and divided by the stored `atr_at_checkpoint`. PnL uses the latest completed bar close, the same entry/direction, and the same ATR denominator.
- Raw gaps are not filled or interpolated. `timeout_mark_ts` records the actual last completed bar and `timeout_mark_staleness_s` measures wall-clock staleness after that bar's one-second interval. Independent source inspection found valid intervals for every alive row, with documented positive staleness in both years.
- Nullable `timeout_mark_ts` is explicitly written as pandas `Int64`, preserving nanosecond values above `2^53` exactly; required non-null output timestamps are runtime-checked as integer types.

## Loss modes and retrospective diagnostics

- `residual_loss_mode` is mutually exclusive and exhaustive: non-loss; stopped before alignment; timed out before alignment; other pre-alignment loss; reached alignment then stopped; reached alignment then planned-exit loss; or other post-alignment loss.
- `late_aligning_baseline_winner_timed_out` requires an original planned winner, a Policy A timeout exit, and confirming flip elapsed time strictly greater than 300 seconds. It is a hindsight diagnostic, not an execution feature.
- `positive_pnl_capture_change_usd = max(policy net, 0) - max(original net, 0)` measures change in positive-PnL capture only. It does not disguise reduced negative loss as positive capture.

## Summary and aggregation audit

- Every configured dimension partitions the same 4,383 fixed trades: year, direction, session, year-direction-session, original outcome, Policy A exit reason, align-time bucket, entry-regime-age bucket, W4 bucket, timeout MFE bucket, timeout PnL bucket, residual loss mode, and late-winner timeout diagnostic.
- Each bucket reports count, Policy A total/mean net PnL, win rate, profit factor, average positive winner, average negative loser, gross loss, gross-loss share within its complete dimension, baseline total, paired Policy A change, positive-capture change, and separate 2025/2026 counts and totals.
- Bucket drawdown is correctly computed only from that bucket's Policy A trades in original entry-time order, starting equity at zero. It is explicitly labeled non-additive and is not an intratrade marked-to-market portfolio drawdown.
- Gross-loss shares use the total Policy A gross loss as the denominator for each complete dimension, so bucket shares within each dimension sum to one aside from floating-point representation.
- Profit factor and winner/loser averages use net PnL after the upstream frozen execution costs; no costs or fills are recomputed here.

## Output gating and independent checks

- Authorization and all input hashes are checked before attribution is built. Both full output frames are computed in memory before any artifact is written; the manifest is written only after both Parquets and records their exact hashes.
- Repository tests: **8 passed**.
- Independently verified all input hashes, Policy A cardinality/uniqueness/year counts, one-to-one source joins, exact entry parity, score/age completeness, bucket equality edges, strict pre-timeout bar exclusion, timeout-stop versus open-exit state, raw-gap staleness, residual modes, bucket metrics, drawdown definition, and exact nullable-nanosecond preservation.
- Frozen data include exact 60/120/300-second align boundaries, all timeout-open exit-type cases, and late flips before/equal/after pending timeout fills; the declared classifiers handle each consistently with the audited Policy A contract.

## Limitation

This is post-policy, one-second OHLC descriptive analysis. Future outcomes are used only for retrospective attribution labels. The results cannot be claimed as NT-native executable validation, tick-order proof, a new causal policy test, or evidence for a 2026-selected filter.
