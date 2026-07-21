# Completion Lookahead, Isolation, and Reproducibility Audit

**Status:** **PASS**

**Findings:** **0 CRITICAL, 0 WARNING**

## Scope and frozen authorization

Audited the completed isolation study's specification, config, policy freeze, runner, tests, pre-execution audit/authorization, both yearly work artifacts and reconciliation seals, all final Parquet outputs, run manifest, and final report.

The pre-execution authorization remains exact and current:

- runner SHA-256: `efc561aa6ca2002fbdf8e245d5559c9e0b9fc5ce4295865696daa0a843cb344e`
- config SHA-256: `0d70aebbbfd2a6a60edb78d5c53db609bc4b64437edc11e91c359dafbba02f54`
- freeze SHA-256: `adb19643fedd3244811d32bab0a963906178f837d89d5060351e7bcc4e175746`
- pre-execution audit SHA-256: `61e604c6938262e0edcdff6fdc24dc1fee4746429460cb864bf16e71c331b957`

The raw 2025/2026 inputs, repaired trades, repaired runner/common, prior confirmation runner, and prior completion audit all retain their frozen hashes. W4 was not retrained or rescored; the exact repaired 4,383-entry set was preserved. The executed policy set is exactly S (1.25 stop only), T (1.50 stop plus fixed five-minute timeout), and A (1.25 stop plus the same timeout), with no extra grid, target, continuation, or protection rule.

## Independent full replay

I independently replayed all **4,383 baseline paths** and all **13,149 S/T/A policy paths** directly from the frozen raw one-second bars and source trades.

The independent replay found **zero discrepancies** in:

- exact entry opens and integer-nanosecond timestamps;
- baseline 1.50 ATR stop reconciliation to every repaired exit timestamp, price, and net PnL;
- S/A 1.25 ATR pre-flip stop behavior and T's unchanged 1.50 ATR pre-flip stop;
- exact-300-second flip inclusion, flips inside raw gaps, and late flips that cannot cancel a prior timeout decision;
- post-alignment reversion to the original 1.50 ATR stop;
- timeout-labelled-bar stop activity and strictly-next-available-open timeout fills;
- stored scheduled decisions mapping to the first available raw open, with the fill bar's range excluded;
- conservative loss-first stop treatment, stop gap fills, checkpoint-ATR denominator, direction, $20/point multiplier, and one $10 round-trip cost;
- reached-aligning-flip state, including no-timeout gap paths whose first later open is the scheduled exit boundary.

All **4,383 Policy A rows** also match the prior audited confirmation-clock Policy A exactly for exit timestamp, exit price, exit reason, gross points/dollars, net PnL, and paired PnL change.

## Paired flags and classifications

I independently reconstructed every field in `isolation_trade_diffs.parquet`. All 13,149 rows match for the exclusive primary class and every intentionally overlapping flag:

- unchanged;
- stopped by the changed 1.25 ATR pre-flip stop;
- exited by the five-minute timeout;
- baseline reached-flip trade lost before alignment;
- stop-before loss reduced;
- planned winner clipped;
- planned loser improved;
- planned loser avoided;
- stop-after trade improved or worsened.

The strict avoided-loss rule is correct: an original planned exit must have net PnL `< 0` and policy net PnL `>= 0`. The 27 original zero-net planned exits are not counted as avoided losses. Primary classes partition each policy's 4,383 rows; overlapping diagnostic flags are not presented as a partition.

## Year isolation, seals, and outputs

- 2025 work artifact: **9,738 rows**, clean dependency seal, matching artifact SHA-256.
- 2026 work artifact: **3,411 rows**, clean dependency seal tied to the exact authorized runner/config/freeze/audit, exact 2025 predecessor artifact, and frozen 2025 inputs.
- Combined trade-level output: **13,149 unique policy/trade rows** and the exact ordered concatenation of the sealed 2025 then 2026 work artifacts.
- All emitted timestamp columns are non-null integer nanoseconds.
- All three output hashes in `run_manifest.json` match their current files.

The policy definitions were frozen before the authorized 2025-first replay. The untouched 2026 path could not execute without the exact 2025 predecessor seal. No trading-policy parameter or entry was selected from 2026; the frozen 5% interaction tolerance changes descriptive wording only.

## Independent metrics reconstruction

I independently rebuilt every baseline, policy, and change-class row in `isolation_policy_results.parquet`; there were **zero differences**.

Verified metrics include:

- trade count, mean/total net PnL, profit factor, win rate, stop rate, and timeout count;
- reached-flip count and lost reached-flip count;
- all outcome-change counts and stop-after net change;
- average positive net winner and average negative net loser;
- maximum trade-sequence drawdown as the largest peak-to-trough decline of cumulative net trade PnL, starting from zero and sorted by the original unique entry timestamp;
- overall, year, direction, and session splits;
- every overlapping class count, baseline/policy total, total paired delta, and average paired delta.

The drawdown is correctly labeled as original-entry-order trade-sequence drawdown, not intratrade marked-to-market portfolio drawdown.

## Attribution and report audit

Independent paired attribution exactly reproduced:

- stop only: **+$3,734.26 (2025), +$8,967.40 (2026), +$12,701.65 combined**;
- timeout only: **+$4,702.83, +$2,396.98, +$7,099.80**;
- combined A: **+$9,494.14, +$10,392.30, +$19,886.44**;
- interaction: **+$1,057.06, -$972.08, +$84.98**.

The frozen interpretation threshold is computed as `0.05 * min(abs(combined S), abs(combined T)) = $354.99`. The $84.98 combined residual is 1.20% of the smaller component and is therefore correctly labeled `approximately zero; additive`. The formula, inclusive boundary, and sign labels are covered by tests and do not alter any policy result.

Every number and material statement in `final_report.md` was traced to the sealed outputs, including all overall/yearly metrics, direction/session changes and PFs, year-level split caveats, outcome-change counts, class tables, average winner/loser values, drawdowns, and the interpretation of complementary stop and timeout effects. The report clearly distinguishes the one-second OHLC research contract from NT-native/tick-exact validation.

The decision `COMBINATION_ADDITIVE` is supported: S and T each improve total net PnL in both years, A is better than either component in both years, and the frozen combined interaction is economically approximately zero. The report does not claim production readiness or parameter stability beyond the measured splits.

The report-encoding warning was corrected before completion. The final report contains no Unicode replacement or non-ASCII characters and has SHA-256 `8564e65975fb75fe0adf7abe978f83717a08ac6bb55bc8561906391663d21013`.

## Tests and limitation

- Repository isolation tests: **14 passed**.
- Contract: paired **1-second OHLC research simulation**, not NT-native executable validation, tick-order proof, or intratrade portfolio drawdown measurement.

The completed study passes the repository's causal sequencing, time-isolation, reproducibility, attribution, and reporting gates.
