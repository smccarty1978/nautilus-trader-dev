# Look-Ahead & Timestamp Audit — Completion

**Date:** 2026-07-17T15:01:38.3660531-05:00  
**Scope:** complete `studies/codex_5_w4_symmetric_bracket_race` source, frozen contract, tests, pre-execution audit/authorization, 2025/2026 work artifacts and reconciliations, three final Parquets, manifest, and final report; upstream repaired original W4 policy/trade/score/raw dependencies; and the separately audited Policy A alignment reference.  
**Mode:** post-execution independent raw-bar reconstruction and artifact/report audit.  
**Auditor:** lookahead-auditor v1  
**Status:** **PASS — COMPLETION GATE SATISFIED**  
**Findings:** **0 CRITICAL, 0 WARNING, 0 NOTE**

## Summary

- Critical: 0
- Warning: 0
- Note: 0

The completed study exactly implements its authorized one-second OHLC first-touch contract. An independent reconstruction from the two frozen raw files reproduced every cell of all 26,298 race rows, all 4,383 tail rows, and all 66 summary rows within exact/instrument-precision tolerances. Entry semantics, bracket geometry, first-touch ordering, same-bar policies, year-end handling, economics, splits, tail censoring, reporting, and chronology are clean.

The final decision `BRACKET_RACE_UNSTABLE_BY_YEAR` is supported. The primary conservative 1.25A race is negative combined and in 2025; only 2026 is marginally positive. All three fixed brackets are negative combined and in development-year 2025. No 2026 result selected a bracket, subgroup, or rule.

## Critical findings

None.

## Warnings

None.

## Notes

None.

## Authorization, freeze, and chronology

- The authorized runner, config, freeze, pre-execution audit, and authorization hashes exactly match the 2025 and 2026 reconciliation seals (`_work/reconciliation_2025.json:6-17`, `_work/reconciliation_2026.json:6-17`).
- The authorization JSON binds the current runner, config, freeze, and pre-execution audit with exact hashes (`audit/pre_execution_authorization.json:1-7`).
- All nine input-freeze hashes match current bytes: both upstream trade files, both raw years, both score files, the original repaired policy, its passing completion audit, and the frozen model manifest (`input_freeze.json:5-15`).
- The 2025 work seal is clean and hash-matched before the 2026 seal. The 2026 dependency seal is identical to the exact 2025 predecessor seal. Both record zero blocking errors and the exact expected population counts.
- Final output hashes and the report hash match `results/run_manifest.json:4-12` exactly. The manifest remains correctly labeled pending this completion audit.
- The runner accepts only development year 2025 and selection-isolated year 2026; 2026 requires the exact clean 2025 seal (`run_study.py:319-345`). Sensitivities are fixed in config and validated before execution (`run_study.py:74-95`).

## Deterministic test gate

The isolated suite was executed without pytest cache writes:

```text
PYTHONDONTWRITEBYTECODE=1
python -m pytest -p no:cacheprovider studies/codex_5_w4_symmetric_bracket_race/tests/test_bracket_race.py -q
15 passed in 0.38s
```

Coverage includes both directions, PT and SL first-touch, conservative and decisive same-bar rules, entry-bar activation, unresolved PnL, fixed costs, conditional-ATR breakeven, exclusion of the resolution bar from pre-resolution excursions, horizon giveback, later SL recovery, resolution-after-horizon unavailability, and entry/2A intrabar ambiguity.

## Independent full-population reconstruction

The audit did not call `first_touch`, `tail_diagnostic`, or `summarize`. It loaded the immutable upstream entries and raw arrays, independently scanned each path, independently rebuilt every metric, and compared the result to both work and final artifacts.

| Artifact | Expected rows | Reconstructed rows | Cell mismatches |
|:--|--:|--:|--:|
| 2025 race matrix | 19,476 | 19,476 | 0 |
| 2026 race matrix | 6,822 | 6,822 | 0 |
| Combined race matrix | 26,298 | 26,298 | 0 |
| 2025 tail diagnostics | 3,246 | 3,246 | 0 |
| 2026 tail diagnostics | 1,137 | 1,137 | 0 |
| Combined tail diagnostics | 4,383 | 4,383 | 0 |
| Summary matrix | 66 | 66 | 0 |

### Population and entry contract

- The exact population is 3,246 entries in 2025 and 1,137 in 2026, with unique `entry_fill_ts` values within each year.
- Every stored entry timestamp exists exactly in the corresponding strictly ordered, duplicate-free UTC raw index; every entry open equals the raw bar open with maximum absolute error `0.0`.
- Entry direction, session, checkpoint ATR, regime keys, and scheduled horizon are exact frozen upstream fields. ATR is finite and strictly positive.
- Upstream candidate construction uses the first strict below-to-threshold crossing in each regime after the frozen established filter (`CODEX_5_X_run_established_fade.py:183-290`). Its passing completion audit independently reconciles candidate/trade/skipped accounting and all 4,383 executed entries.

### Primary and sensitivity races

- Each path starts at the entry bar and scans raw one-second high/low bars forward until first touch or available raw-year end (`run_study.py:132-178`). Regime flips, original exit, timeouts, portfolio state, and later W4 observations do not affect the race.
- Long geometry uses high for PT and low for SL; short geometry uses low for PT and high for SL. PT and SL are exactly symmetric about entry at 1.00, 1.25, or 1.50 `atr_at_checkpoint`.
- Classification stops on the first touching bar. No later bar enters the label. Conservative same-bar ties are SL-first; decisive ties award PT only for strictly larger favorable normalized overshoot.
- All 4,383 primary races resolve. There are zero unresolved paths and exactly one same-bar PT/SL tie. The decisive rule also classifies that tie SL-first.
- Time-to-resolution uses exact raw open-label timestamps. Favorable/adverse excursion “before resolution” excludes the resolution bar; through-resolution fields include it. Every stored value reproduces.

Primary conservative 1.25A reconciliation:

| Period | Trades | PT first | SL first | PT rate | Mean net | PF |
|:--|--:|--:|--:|--:|--:|--:|
| Combined | 4,383 | 2,175 | 2,208 | 49.6235% | -$10.6670 | 0.921396 |
| 2025 | 3,246 | 1,601 | 1,645 | 49.3222% | -$14.8029 | 0.888534 |
| 2026 | 1,137 | 574 | 563 | 50.4837% | +$1.1404 | 1.007920 |

Fixed conservative sensitivity reconciliation:

| Bracket | Combined mean / PF | 2025 mean / PF | 2026 mean / PF |
|:--|:--|:--|:--|
| 1.00A | -$9.7870 / 0.910368 | -$12.0904 / 0.886323 | -$3.2110 / 0.972622 |
| 1.25A | -$10.6670 / 0.921396 | -$14.8029 / 0.888534 | +$1.1404 / 1.007920 |
| 1.50A | -$13.4777 / 0.917414 | -$17.0350 / 0.892859 | -$3.3221 / 0.981037 |

This verifies the reported instability: every bracket is negative combined and in 2025, and only the frozen primary bracket is marginally positive in 2026.

## Economics and all split rows

- Resolved PT and SL PnL is exactly `± bracket × atr_at_checkpoint × $20 - $10`; there is no trigger-price substitution, terminal-price invention, or missing cost (`run_study.py:167-178`).
- Profit factor independently recomputes as summed net PT gains divided by the absolute summed net SL losses.
- Conditional gross payout averages are computed separately for PT and SL cohorts. The cost-adjusted breakeven rate is exactly `(L + $10) / (W + L)`, algebraically consistent with realized expectancy under ATR/outcome covariance (`run_study.py:265-315`).
- Every one of the 66 rows—three brackets × two tie policies × eleven combined/year/direction/session/direction-session splits—reproduces for counts, rates, PnL, PF, conditional breakeven, edge, quantiles, and excursions.
- Primary split counts close exactly: long 1,871 + short 2,512 = 4,383; ETH 2,937 + RTH 1,446 = 4,383; and the four intersections 1,232 + 639 + 1,705 + 807 = 4,383.
- Every direction/session intersection has negative primary expectancy, exactly as stated in `final_report.md:21-42`.

## Tail horizon and ordered-event labels

- Tail extrema use `[entry_bar, first raw bar at/after scheduled_exit_decision_ts)`, excluding the scheduled exit bar's high/low range; the original-horizon PnL uses that bar's open (`run_study.py:181-212`).
- Post-resolution labels require the primary resolution strictly before the tail horizon. Seventy-four PT-first races resolve after the horizon and correctly retain unavailable post-resolution labels.
- Among 2,101 observable PT-first tails, 1,491 reach 2A, 968 reach 3A, and 640 reach 4A. Median additional MFE after the PT bar is 1.57869A.
- Horizon net PnL for observable PT tails has mean +$270.46, median +$70.00, 61.4469% positive, and median giveback 2.28161A.
- Of 2,101 observable PT tails, 2,100 have an unambiguous entry-versus-2A ordering label; 772 return to entry first and one exact one-second bar is explicitly ambiguous.
- Among 1,954 SL-first paths resolving before the horizon, 727 later reach the original 1.25A PT. The recovery scan begins after the SL resolution bar, so a conservative same-bar tie cannot be relabeled as later recovery.
- Every stored tail field—horizon availability, applicability, extrema, runner levels, PnL, giveback, reversal, recovery, and ambiguity—matches the independent reconstruction.

## Policy A reference

The reference `2,332 / 4,383 = 53.2056%` was verified directly from the separately completed and passing `codex_5_w4_fade_confirmation_clock_isolation` Policy A overall row. Its `isolation_policy_results.parquet` hash is `f540ae6ad3cf433c93cecc5ab5af9f7084147c0c8e152fe8edc02a0f68b36c66`, matching that study's manifest. The symmetric primary rate is lower by exactly 157 trades and 3.5820 percentage points. The report correctly distinguishes regime alignment from price reaching +1.25A.

## Final report reconciliation and decision

- Every headline, requested split, count, percentage, PnL, PF, conditional breakeven, edge, quantile, sensitivity, Policy A comparison, and tail statistic in `results/final_report.md` reproduces from the stored artifacts and independent reconstruction at the displayed precision.
- The report accurately labels the output as a one-second OHLC diagnostic, not NT-native or tick-level execution validation (`final_report.md:15-17`).
- The decision `BRACKET_RACE_UNSTABLE_BY_YEAR` follows from negative combined/development expectancy and a sign reversal to only +$1.14/trade in selection-isolated 2026 (`final_report.md:3-13`).
- The proposed follow-up is clearly separated from this study and does not alter the completed result (`final_report.md:142-147`).
- No result-driven bracket, side, session, timeout, re-entry, delayed entry, specialized model, or tail rule entered the primary race. No 2026 statistic changes the frozen study contract.

## Sign-off

Scope hash (SHA-256 of ordered `path + file SHA-256` records): `175b12c39135e5465e89dd7c43aab5b6c03a83254bdf45a735fa53c9f51139d5`

---

*Audit complete. Findings reflect independent static analysis, deterministic tests, full raw-bar replay, artifact reconciliation, and report verification. No code or result artifact was modified.*
