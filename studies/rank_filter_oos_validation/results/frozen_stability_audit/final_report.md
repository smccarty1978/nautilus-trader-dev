NEW FORWARD DATA AVAILABLE:
NO

POLICIES FROZEN:
YES

R2 POSITIVE PERIODS:
6/8

R4 POSITIVE PERIODS:
7/8

R2 MEDIAN PERIOD LIFT:
$+1.03

R4 MEDIAN PERIOD LIFT:
$+1.71

R2 WORST PERIOD:
2022, $-0.22

R4 WORST PERIOD:
2026_JanApr29, $-0.39

R4 RUNNER RETENTION:
0.9473 average across periods (range 0.9321-0.9578); see Section 3

R4 MATCHED-RANDOM STABILITY:
clears p<=0.10 in 1/8 periods (R2: 1/8); see Section 5

BRANCH STATUS:
HOLD — AWAITING NEW DATA

---
# Frozen R2/R4 Policy — Retrospective Stability Audit

Study directory: `studies/rank_filter_oos_validation/results/frozen_stability_audit/`
**No forward test beyond 2026-04-29 was run — no such data are available.** **R2 and R4 are frozen exactly as previously implemented** (score threshold 0.12855426455573915, R2 = strong-center-migration exemption, R4 = favorable-regime-asymmetry exemption, 30s entry delay, E0 exit) — nothing was retrained, retuned, or altered. This audit re-runs the existing NautilusTrader implementation over 8 retrospective blocks purely to characterize whether R4's (and R2's) apparent value is broadly distributed across market regimes or concentrated in isolated periods. **Every number below is a retrospective robustness diagnostic, not new out-of-sample evidence** — none of these blocks (including 2021-2024, never previously backtested with this exact frozen policy) should be read as validating or invalidating the branch; they only describe the shape of the historical distribution.

## 1. Data-Quality Caveat (2021-2024)

No bug-fixed per-year catalog exists for 2021-2024 (only `NQ_v0_2020_2026`, which has a documented ~1-second look-ahead in its separately-published 1-minute bar type from an un-fixed `closed='right'` resample). `CollectorV2Strategy`'s regime-flip *detection* is built causally from the 1-second bar stream (unaffected), but the bar+1 HH/LL *confirmation* check reads the catalog's 1-minute bar OHLC directly, so **2021-2024 confirmation checks inherit up to ~1s of look-ahead**. 2025 (all three blocks) and 2026 use the bug-fixed `NQ_v0_2025_fixed`/`NQ_v0_2026_fixed` catalogs and are unaffected. 2021-2024 rows are marked with `*` throughout and should be read as directionally informative, not decision-grade.

## 2. Period Metrics (`period_metrics.parquet`)

### R2

| block | eligible | filled | EV lift vs R0 | net PnL Δ | max DD Δ | matched-random p | largest avoided loss | largest skipped winner | lift excl top1 | lift excl top2 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2021 * | 11640 | 11108 | $+0.73 | $+8,440 | n/a | 0.427 | $-970 | $+1,815 | $+0.64 | $+0.58 |
| 2022 * | 11834 | 11368 | $-0.22 | $-2,655 | n/a | 0.777 | $-950 | $+2,740 | $-0.30 | $-0.38 |
| 2023 * | 11801 | 11272 | $+1.68 | $+19,775 | n/a | 0.007 | $-1,560 | $+1,195 | $+1.54 | $+1.45 |
| 2024 * | 11845 | 11276 | $+0.85 | $+10,075 | n/a | 0.265 | $-1,590 | $+2,380 | $+0.72 | $+0.63 |
| 2025_JanFeb | 1779 | 1714 | $+1.41 | $+2,510 | n/a | 0.229 | $-695 | $+915 | $+1.02 | $+0.73 |
| 2025_MarMay | 3005 | 2894 | $+2.22 | $+6,685 | n/a | 0.131 | $-2,360 | $+2,315 | $+1.44 | $+0.68 |
| 2025_JunDec | 6905 | 6603 | $+1.21 | $+8,355 | n/a | 0.236 | $-1,115 | $+2,985 | $+1.05 | $+0.90 |
| 2026_JanApr29 | 3957 | 3805 | $-0.14 | $-560 | n/a | 0.583 | $-1,825 | $+3,260 | $-0.60 | $-0.95 |

### R4

| block | eligible | filled | EV lift vs R0 | net PnL Δ | max DD Δ | matched-random p | largest avoided loss | largest skipped winner | lift excl top1 | lift excl top2 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2021 * | 11640 | 10757 | $+0.69 | $+8,035 | n/a | 0.698 | $-910 | $+1,530 | $+0.61 | $+0.55 |
| 2022 * | 11834 | 11091 | $+0.77 | $+9,130 | n/a | 0.398 | $-2,630 | $+2,400 | $+0.55 | $+0.40 |
| 2023 * | 11801 | 10898 | $+2.11 | $+24,945 | n/a | 0.032 | $-1,560 | $+2,290 | $+1.98 | $+1.86 |
| 2024 * | 11845 | 10868 | $+1.32 | $+15,600 | n/a | 0.300 | $-1,590 | $+2,380 | $+1.18 | $+1.07 |
| 2025_JanFeb | 1779 | 1664 | $+2.59 | $+4,610 | n/a | 0.147 | $-1,225 | $+1,335 | $+1.90 | $+1.57 |
| 2025_MarMay | 3005 | 2824 | $+3.08 | $+9,260 | n/a | 0.121 | $-2,290 | $+3,340 | $+2.32 | $+1.77 |
| 2025_JunDec | 6905 | 6370 | $+2.11 | $+14,565 | n/a | 0.188 | $-4,485 | $+3,035 | $+1.46 | $+1.31 |
| 2026_JanApr29 | 3957 | 3721 | $-0.39 | $-1,525 | n/a | 0.766 | $-1,825 | $+4,500 | $-0.85 | $-1.30 |

(`*` = 2021-2024, subject to the Section 1 catalog caveat. Max-DD change is in `period_drawdown_metrics.parquet`.)

## 3. Runner-PnL Retention by Period (`period_runner_retention.parquet`, top-decile tier)

| block | R2 | R4 |
|---|---|---|
| 2021 | 0.9632 | 0.9485 |
| 2022 | 0.9587 | 0.9347 |
| 2023 | 0.9735 | 0.9558 |
| 2024 | 0.9570 | 0.9321 |
| 2025_JanFeb | 0.9707 | 0.9423 |
| 2025_MarMay | 0.9653 | 0.9578 |
| 2025_JunDec | 0.9751 | 0.9573 |
| 2026_JanApr29 | 0.9756 | 0.9503 |

## 4. Drawdown Change by Period (`period_drawdown_metrics.parquet`)

| block | R2 Δ | R4 Δ |
|---|---|---|
| 2021 | $+10,235 | $+10,560 |
| 2022 | $-5,085 | $+5,810 |
| 2023 | $+18,900 | $+24,375 |
| 2024 | $+6,365 | $+16,420 |
| 2025_JanFeb | $+775 | $+2,015 |
| 2025_MarMay | $+2,025 | $+5,040 |
| 2025_JunDec | $+4,115 | $+8,560 |
| 2026_JanApr29 | $-3,975 | $-2,610 |

(Positive = drawdown improved relative to R0; negative = drawdown worsened.)

## 5. Matched-Random Stability (`period_matched_random.parquet`, 1,000 seeds/block, ATR-bucket edges frozen on validation period)

R4 clears the pre-declared p≤0.10 significance bar in **1 of 8** blocks; R2 clears it in **1 of 8**. Per-block p-values:

| block | R2 p | R4 p |
|---|---|---|
| 2021 | 0.427 | 0.698 |
| 2022 | 0.777 | 0.398 |
| 2023 | 0.007 | 0.032 |
| 2024 | 0.265 | 0.300 |
| 2025_JanFeb | 0.229 | 0.147 |
| 2025_MarMay | 0.131 | 0.121 |
| 2025_JunDec | 0.236 | 0.188 |
| 2026_JanApr29 | 0.583 | 0.766 |

## 6. Cross-Period Summary

| | R2 | R4 |
|---|---|---|
| Positive periods | 6/8 | 7/8 |
| Negative periods | 2/8 | 1/8 |
| Median period lift | $+1.03 | $+1.71 |
| Worst period | 2022, $-0.22 | 2026_JanApr29, $-0.39 |
| Cross-period std (lift) | $0.85 | $1.15 |
| Corr(R0 baseline environment, filter lift) | +0.680 | +0.814 |

**Correlation interpretation:** this is the Pearson correlation, across the 8 blocks, between R0's own EV-per-eligible-signal (a proxy for "how favorable was the underlying environment that block") and the filter's paired EV lift that same block. A value near zero means the filter's benefit doesn't depend on whether the baseline environment was itself good or bad; a strongly negative value would mean the filter mainly helps in bad environments (defensive value); a strongly positive value would mean it mainly helps when the environment is already good (adds on top of a tailwind, provides little diversification benefit).

## 7. Tail Dependence (`tail_dependence.parquet`)

For each block/policy, the paired lift is recomputed after removing the single largest avoided loss, and again after removing the top 2, from the skipped-trade set. This tests whether a period's apparent benefit is a broad, distributed effect or concentrated in one or two large avoided losses.

Full detail in the parquet; see the "lift excl top1/top2" columns in Section 2's tables above for values per block. A period where `lift_excl_top2_avoided_losses` flips sign or drops close to zero indicates that block's apparent benefit was concentrated in a small number of trades rather than broadly distributed.

## 8. Interpretation

This audit does not select a preferred threshold and does not modify R2 or R4. It exists solely to answer: **is the apparent value of the frozen policies broadly distributed across market regimes, or concentrated in isolated periods?** The cross-period positive/negative split, median/worst-period lift, cross-period standard deviation, matched-random pass rate, and tail-dependence figures above are the evidence for that question; read together with the existing `final_report.md` (the primary 2025H2/2026 NT validation) and the `HOLD` verdict already on file there.

## 9. Branch Status

**BRANCH STATUS: HOLD — AWAITING NEW DATA.**

No capital decision is made or implied by this audit. The branch remains on hold pending genuinely new data after 2026-04-29. Do not continue tuning, retraining, or threshold selection until that data is available.
