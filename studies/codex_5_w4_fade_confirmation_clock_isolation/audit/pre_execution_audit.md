# Pre-Execution Lookahead and Isolation-Contract Audit

**Status:** **PASS — authorized for the frozen 2025-first isolation replay**

**Findings:** **0 CRITICAL, 0 WARNING**

## Scope

Audited before any yearly replay:

- `SPEC.md`
- `config.json`
- `policy_freeze.json`
- `run_isolation.py`
- `tests/test_isolation.py`

The study `_work/` and `results/` directories contained no artifacts at authorization time. This authorization applies only to the exact source/configuration hashes recorded in `pre_execution_authorization.json`.

## Frozen experiment

- The input is the exact repaired 4,383-trade CODEX 5.X entry set. W4 is neither retrained nor rescored, and no entry timestamp, fill, direction, ATR, threshold, or trade membership is changed.
- The executable policy set is exactly:
  - S: 1.25 ATR pre-flip stop, no timeout;
  - T: original 1.50 ATR pre-flip stop, fixed 300-second timeout;
  - A: 1.25 ATR pre-flip stop plus the fixed 300-second timeout.
- All paths revert to the original 1.50 ATR stop after the first aligning flip and retain the frozen next-opposing-flip market exit. There is no MFE continuation, target, post-flip protection, extra stop, alternate timeout, or grid.
- All raw, repaired-trade, repaired-runner/common, prior confirmation runner, and prior completion-audit hashes match the freeze. The prior audited Policy A execution semantics are a frozen dependency.
- The 2026 invocation requires the exact clean 2025 diff artifact and dependency seal. Policies are frozen before either year and no 2026 value can select or modify a parameter.

## Causal execution audit

- Entry is the stored exact raw 1-second open. Integer nanosecond timestamps are preserved and enforced in emitted trade-level fields.
- An aligning flip at exactly `entry + 300s` is recognized before the timeout decision and before that bar's OHLC range. A within-window flip occurring in a raw gap is recognized before the first later available open.
- For timeout-enabled T/A, a late flip cannot cancel a timeout decision already made at 300 seconds. Timeout fills use the first available raw open strictly after the decision; the active stop remains live through the timeout-labelled bar and until that fill.
- For no-timeout baseline/S, an aligning flip inside a raw gap is recognized before the first later available open, including when that open is also the scheduled opposing-flip fill boundary.
- Flip state changes precede the same-timestamp range. Stops are checked before any later event in that range, with the declared conservative loss-first OHLC treatment.
- Scheduled opposing-flip decisions map to the first available raw `ts_event >= decision`. Stored planned fills must match that derived timestamp and open exactly. The fill boundary is processed before its bar range, so no unavailable/intervening path is invented across a gap.
- Pre-flip stop prices, the post-flip 1.50 ATR stop, stop gap fills, direction-adjusted PnL, $20/point multiplier, and one $10 round-trip cost are all computed from the frozen entry open and stored `atr_at_checkpoint`.
- Every trade is first replayed under the original baseline; timestamp, fill price, and net PnL must reconcile exactly before any yearly artifact can be written.
- Randomized long/short/gapped-path comparison of the new A implementation against the prior audited Policy A produced zero execution/PnL differences across 200 cases.

## Classification and statistics audit

- `primary_change_class` is an exclusive economic classification with priority: identical fill, timeout exit, changed 1.25 pre-flip stop, then other change. Separate boolean flags intentionally overlap so a timeout or tighter-stop change can also be identified as a lost reached-flip trade, clipped planned winner, improved/avoided planned loser, reduced stop-before loss, or improved/worsened stop-after trade.
- Baseline reached-flip status follows the repaired outcome contract: all planned opposing-flip and stop-after trades reached the aligning flip; stop-before trades did not. Policy reached-flip state is replay-derived, including gap cases.
- Counts and net changes for reached-flip losses, stop-before reductions, planned-winner clipping, planned-loser improvement/conversion, and stop-after improvement/worsening are calculated from paired fixed-trade results without future information influencing execution. A `planned_loser_avoided` conversion requires strictly negative original net PnL and non-negative policy net PnL; original breakevens remain in the non-winner outcome group for descriptive compatibility but are not falsely counted as avoided losses.
- Profit factor, win rate, stop rate, timeout count, average positive/negative net trade, and stop-after net changes use net PnL after the fixed cost.
- Maximum drawdown is correctly defined as the largest peak-to-trough decline of cumulative per-trade net PnL, starting from zero, after sorting by the original unique entry timestamp. It is explicitly not an intratrade marked-to-market portfolio drawdown.
- Policy summaries cover overall, year, direction, and session. Overlapping mechanism-class summaries retain counts, baseline/policy totals, total delta, and average paired delta.
- Component attribution is exact paired arithmetic for 2025, 2026, and combined samples: `interaction = change(A) - change(S) - change(T)`. Its interpretation uses the predeclared, config/freeze-validated tolerance `abs(combined interaction) <= 0.05 * min(abs(combined S), abs(combined T))`; equality is labeled `approximately zero; additive`, while values outside the band receive the appropriate sign label. This threshold changes interpretation text only, never a policy result or selection.

## Independent checks

- Repository tests: **14 passed**.
- Independently tested exact-300-second flips, long and short stops, timeout-bar stop activity, post-flip stop reversion, late flips in gaps, no-timeout flips in a gap directly before the scheduled fill, timeout persistence despite a later gap flip, scheduled-decision gaps, next-open fills, scheduled-fill range exclusion, strict negative-to-nonnegative avoided-loss classification, exact interaction arithmetic, inclusive 5% additive labeling, and just-outside-band sign labeling. The frozen source contains 27 zero-net planned exits; the corrected definition excludes them from avoided-loss counts.
- Confirmed source entry timestamps are unique and chronologically ordered, making trade-sequence drawdown ordering deterministic.
- Confirmed all frozen hashes and the absence of yearly work/results artifacts.

## Limitation

This is a paired causal 1-second OHLC research simulation. It does not claim NT-native executable validation, tick-level touch ordering, or intratrade marked-to-market drawdown accuracy.
