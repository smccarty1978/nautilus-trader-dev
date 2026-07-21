# Established Regime Weakness Fade — Completion Audit

**Scope:** current study code, specification, frozen policy, Stage-1 artifacts, repaired Stage-2 artifacts, reconciliations, summaries, and final report  
**Status:** **PASS — STUDY COMPLETE UNDER THE DECLARED RESEARCH CONTRACT**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The repaired study passes the completion lookahead, timestamp, execution-contract, arithmetic, provenance, and reporting audit. The former Stage-2 regime-direction defect is closed: current candidates agree exactly with the causal score stream, and the repaired runner's fresh per-year regime build reports 27,138/27,138 matched directions in 2025 and 8,922/8,922 in 2026, with zero mismatches. The Stage-1 production summary and independent audit summary are now separate artifacts with separate writers.

An independent raw-bar replay reproduced every entry, stop, scheduled exit, exit price, and PnL across all 2,979 trades. The published decision, `NO_MONETIZABLE_WEAKNESS_FADE`, follows exactly from the frozen rule and current artifacts.

This pass applies only to the declared **1-second OHLC research simulation**. It is not NT-native executable validation, does not establish tick/quote touch ordering or fill accuracy, and is not deployable.

## Provenance and execution order

- Frozen policy SHA-256: `e290fe0726a309295b930eaeeba6cc491fd68cb21c186fd05cb4d55529fc8e7d`.
- The immutable snapshot and active policy have the same hash. Every trade and both yearly reconciliations carry that hash.
- `run_stage2_ohlc.py` SHA-256: `16a3440536786f385eb65ae640ebdb049a62018208e56cc571db7a0c2a4efdbe` (modified 2026-07-13 13:40:17 CT).
- Repaired 2025 reconciliation: modified 13:49:29 CT, SHA-256 `2e6a8b7151010e31295f1a9276ce744b29022887c8a6035e7dbe9df559848b3e`.
- Repaired 2026 reconciliation: modified 13:50:02 CT, SHA-256 `60c4e33dfc6fc69908e00b57c9791b0540c4323aa1a4a4c38a4a573a37a8e9b9`.
- The timestamps demonstrate the required ordering: repaired 2025 completed before 2026, and the report was generated after both.
- The disclosure-only analyzer update has SHA-256 `b913b3b3413e286735e2db7f063ae75d51a51d4717ed3d5b4c072c693e16349e`; the regenerated final report has SHA-256 `14d8ea746d12c23fb35c533de0fa638a6f13b7025af64df150a7093bd140c478` (13:58:25 CT).
- No 2026 value altered the filter, W4 threshold, stop, exit rule, costs, or policy hash.

## Stage 1 — independent reporting and gate verification

- Production `stage1_cohort_summary.parquet`: 48 rows, all eight cohorts across train, validation, train-long, train-short, train-RTH, and train-ETH; required `median_retained_qual` is present.
- Independent `audit/stage1_cohort_summary_independent.parquet`: 48 rows and independent `med_retained_qual` field.
- Static writer check finds one production writer (`analyze_stage1.py`) and one audit-only writer (`evaluate_stage1.py`). File timestamps show production written at 13:42:06 CT and the independent artifact at 13:42:08 CT; the evaluator does not write the production summary.
- Stage 1 contains zero 2026 rows.
- The current gate independently passes in discovery and validation:
  - winner counts: 28,789 / 7,147;
  - failed-runner counts: 36,583 / 9,156;
  - duration ratios: 2.30 / 2.30;
  - peak-MFE ratios: 2.7043 / 2.7126;
  - progress-window deltas: 1 / 1;
  - retained-MFE deltas at flip-minus-60s: 0.4567 / 0.4491;
  - paired W4 rises: 0.1328 (`n=20,551`) / 0.2009 (`n=5,042`);
  - median peak-to-flip seconds: 347 / 316;
  - median giveback ATR: 2.4089 / 2.4164.
- Gate decision: `ESTABLISHED_REGIME_FILTER_FOUND`.

## Stage 2 — causal trigger and candidate audit

- Candidate direction versus causal score direction: 0 mismatches and 0 missing keys across 2,123 candidates in 2025 and 885 in 2026.
- Every persisted strict-cross candidate has an exact predecessor below the frozen threshold and a current score at or above it; `decision_ts = score_observation_ts + 1s` for every candidate.
- Independent raw 1-second recomputation covered all 67,168 filter-evaluated crossings: 47,566 in 2025 and 19,602 in 2026. W4 score, regime age, running MFE, distinct progress-window count, and retained-MFE ratio all matched with zero error.
- Eligible trigger rows equal the candidate set exactly.
- Trigger-audit routing is complete: 2025 has 45,443 filter failures, 6,510 crosses available at/after flip, and 2,123 eligible rows; 2026 has 18,717, 2,360, and 885 respectively.
- Candidate accounting closes exactly: `2,123 = 2,103 trades + 20 skips` in 2025 and `885 = 876 + 9` in 2026.
- Skips are limited to the declared state rules: 2025 has 16 overlaps and 4 next-opens at/after the confirming flip; 2026 has 8 and 1.

## Full raw 1-second execution replay

All 2,979 trades were replayed independently from raw OHLC:

- Entry timestamp is the first available 1-second open at or after the causal decision: 0 errors.
- Entry open and price: 0 errors.
- Stop equals fill price ± exactly 1.5 trigger ATR: 0 errors. Maximum floating representation error is `1.030e-12 ATR` in 2025 and `7.179e-13 ATR` in 2026.
- Stop is active on every entry bar: 0 errors. Entry-bar stop touches occurred 0 times.
- No earlier bar touched the stop before a recorded stop or scheduled exit: 0 errors.
- Stop touch, open-gap-versus-stop pricing, before/after-aligning-flip classification, and exit price: 0 errors.
- Scheduled exits fill at the next available 1-second open after the opposing-flip decision, with market-exit priority on that eventual fill bar: 0 errors.
- Gross points, gross dollars at $20/point, and net dollars after $10 round-trip cost: 0 errors.
- Hold duration, entry delay, authorized date window, contract label, and policy hash: 0 errors.
- There is no target, so same-bar stop/target tie frequency is exactly 0 by construction.

Scheduled-exit gaps are now explicitly disclosed in the final report and `stage2_exit_fill_delay_summary.parquet`: 2025 has 1,201 scheduled exits, 900 exact and 301 delayed, maximum 189,900 seconds; 2026 has 504, 389 exact and 115 delayed, maximum 176,400 seconds. These weekend/session-gap fills are included in PnL.

## Exact results and reconciliation

| Year | Trades | Mean gross | Mean net | Total net | Win rate | Profit factor | Stop rate | Median hold |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 2,103 | $15.111149 | $5.111149 | $10,748.745670 | 0.308131 | 1.034190 | 0.428911 | 498s |
| 2026 | 876 | -$2.428579 | -$12.428579 | -$10,887.434811 | 0.328767 | 0.930980 | 0.424658 | 534s |

Exit reasons reconcile to all trades:

- 2025: 1,201 scheduled opposing-flip exits, 778 stops before the aligning flip, 124 stops after it.
- 2026: 504 scheduled opposing-flip exits, 316 stops before the aligning flip, 56 stops after it.

The direction and RTH/ETH tables in `final_report.md` reproduce directly from the trade rows. Completion reconciliation has zero candidate residual, zero exit-reason residual, zero blocking errors, and zero gross/net arithmetic error.

## Manual trace checks (America/Chicago)

| Case | Decision → entry | Entry / stop | Exit | Result |
|---|---|---|---|---|
| Stop before flip, 2025 | 2025-03-02 20:05:21 → 20:05:21 | short 20,943.75 / 20,955.961438 | 20:07:06 at stop; confirming flip was 20:11:00 | -12.211438 pts; -$254.228762 net |
| Stop after flip, 2025 | 2025-03-02 22:05:21 → 22:05:24 | short 20,920.25 / 20,927.935046 | confirming flip 22:06:00; gap stop 22:07:25 at 20,928.75 | -8.50 pts; -$180.00 net |
| Scheduled flip exit, 2025 | 2025-03-02 23:48:06 → 23:48:08 | short 20,988.25 / 20,996.306616 | opposing flip/open 23:51:00 at 20,992.00 | -3.75 pts; -$85.00 net |
| Maximum entry delay, 2025 | 2025-09-17 07:04:16 → 07:04:55 (39s) | short 24,264.00 / 24,269.117791 | scheduled next-open 07:15:10 at 24,267.75 | -3.75 pts; -$85.00 net |

The sampled entry bars, all intervening bars, and exit bars were inspected directly. Their OHLC ranges support the recorded priority and fill classification.

## Final disposition

- Stage 1: `ESTABLISHED_REGIME_FILTER_FOUND`
- Stage 2: `NO_MONETIZABLE_WEAKNESS_FADE`

The study is complete under its frozen 1-second OHLC research contract. It does not advance to execution validation.

---

# SUPERSEDED (2026-07-13, main agent)

The FAIL above was correct for the artifacts as of 13:35 (Stage-2 run under
the broken flip_context_atlas F1 direction fallback). Those artifacts were
snapshotted and fully regenerated with engine-derived regimes + a direction
parity fail-fast (0 mismatches both years, verified two independent ways).
The superseding completion audit is `audit/completion_lookahead_audit.md`
(1 CRITICAL = this stale document; findings addressed). Current results in
`results/` are the corrected run: 2025 +$5.11/tr (2,103 trades), 2026
-$12.43/tr (876 trades), decision NO_MONETIZABLE_WEAKNESS_FADE.
