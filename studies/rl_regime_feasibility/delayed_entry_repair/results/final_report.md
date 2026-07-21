# Delayed Entry Repair -- Final Report

**Study**: rl_regime_feasibility/delayed_entry_repair
**Date**: 2026-07-04
**Status**: Complete

---

## Context

This study repairs three bugs found in the delayed_health study:

| Bug | delayed_health | This study |
|-----|---------------|------------|
| KNN merge | Double-merge created _x/_y suffixes; KNN absent from entry model | Single clean merge; suffix check PASS |
| KNN test delay | Model at best_delay (may be pre-bar4; KNN=0 at inference) | KNN model always at 240s where KNN has real values |
| Delay targeting | step_index cutoff (variable elapsed time) | seconds_since_flip >= delay_s (exact) |

Additionally: new period splits (Jan-Jun 2024 train / Jul-Oct 2024 val / Nov 2024-May 2025 test split across two windows) confirm or deny cross-period robustness.

---

## Period Splits

| Period | Dates | Episodes |
|--------|-------|---------|
| train | Jan 2024 -- Jun 2024 | 13,730 |
| val | Jul 2024 -- Oct 2024 | 9,462 |
| test_2024q4 | Nov 2024 -- Dec 2024 | 4,459 |
| test_2025h1 | Jan 2025 -- May 2025 | 10,904 |

---

## Phase 4: Delay Sweep on Val (Unconditional)

All delays evaluated on val period (Jul-Oct 2024). Best delay selected by fixed_300s EV/episode.

| Delay | EV/ep (fixed_300s) | N Traded | EV/ep (regime) |
|-------|-------------------|----------|----------------|
| 60s | -9.92 | 9173 | -9.92 |
| 120s | -7.01 | 8578 | -7.70 |
| 180s (*) | -5.54 | 7892 | -6.27 |
| 240s | -7.73 | 7217 | -7.56 |

**Selected delay**: 180s

> Note: All delays show negative EV on the val period (Jul-Oct 2024). The selected delay is the least-negative, not a profitable benchmark. This is an unfavorable val period; test periods below show split behavior (2024-Q4 negative, 2025-H1 positive).

---

## Phase 5: Unconditional Entry at 180s -- Test Periods

### By test period and direction (base cost)

| Period | Direction | Policy | EV/ep | WR | 95% CI | N Traded / Total |
|--------|-----------|--------|-------|-----|--------|-----------------|
| test_2024q4 | combined | fixed_300s | -2.44 | 43.0% | (-8.70,+3.54) | 3700/4459 |
| test_2024q4 | long | fixed_300s | -2.22 | 45.1% | (-9.53,+5.57) | 1862/2230 |
| test_2024q4 | short | fixed_300s | -2.66 | 40.8% | (-11.70,+6.55) | 1838/2229 |
| test_2024q4 | combined | opposing_regime | -3.14 | 41.2% | (-9.25,+2.92) | 3701/4459 |
| test_2024q4 | long | opposing_regime | -2.60 | 43.7% | (-9.90,+5.26) | 1864/2230 |
| test_2024q4 | short | opposing_regime | -3.68 | 38.6% | (-12.78,+5.48) | 1837/2229 |
| test_2025h1 | combined | fixed_300s | +3.81 | 44.8% | (-3.03,+10.59) | 9159/10904 |
| test_2025h1 | long | fixed_300s | +9.11 | 46.2% | (-0.86,+19.55) | 4600/5452 |
| test_2025h1 | short | fixed_300s | -1.50 | 43.4% | (-11.13,+8.23) | 4559/5452 |
| test_2025h1 | combined | opposing_regime | +2.87 | 43.3% | (-3.71,+9.58) | 9161/10904 |
| test_2025h1 | long | opposing_regime | +8.24 | 44.6% | (-1.75,+18.66) | 4601/5452 |
| test_2025h1 | short | opposing_regime | -2.50 | 42.0% | (-11.13,+6.53) | 4560/5452 |

### Cost stress (unconditional, combined direction)

| Period | Policy | Base | +1T | +2T |
|--------|--------|------|-----|-----|
| test_2024q4 | fixed_300s | -2.44 | -6.67 | -10.97 |
| test_2024q4 | opposing_regime | -3.14 | -7.52 | -11.72 |
| test_2025h1 | fixed_300s | +3.81 | -0.27 | -4.46 |
| test_2025h1 | opposing_regime | +2.87 | -1.32 | -5.43 |

---

## Phase 5b: Matched Cohort Decomposition at 180s

Decomposes delay improvement into:
- **Survival filter benefit**: EV lost by entering regimes that die before the delay
  (negative for those episodes = eliminated by delay).
- **Timing benefit**: EV difference for episodes that survive to the delay.
  Negative = entering at the delay is WORSE than entering immediately.

| Period | Policy | Immediate | Delayed | Survive% | Filter benefit | Timing benefit | Total |
|--------|--------|-----------|---------|----------|---------------|---------------|-------|
| test_2024q4 | fixed_300s | -10.88 | -2.44 | 84.2% | +169.74 | -21.75 | +8.44 |
| test_2024q4 | opposing_regime | -11.19 | -3.14 | 84.2% | +172.74 | -22.77 | +8.05 |
| test_2025h1 | fixed_300s | -4.47 | +3.81 | 84.9% | +275.01 | -39.08 | +8.28 |
| test_2025h1 | opposing_regime | -4.97 | +2.87 | 84.9% | +274.12 | -39.44 | +7.84 |

> Interpretation: Delay benefit is ENTIRELY from the survival filter (avoiding quick-fail regimes). Within regimes that survive to 180s, entering at 180s is WORSE than entering immediately (timing benefit is negative). The delay's value is as a failure-avoidance filter, not a better entry point.

---

## Phase 6: Bar-4 KNN Entry Model (Repaired)

KNN model trained exclusively at delay=240s where KNN data exists. Manifest assertion enforced before any results are reported.

### Manifest assertion

| Field | Present |
|-------|---------|
| knn_hA | PASS |
| knn_hB | PASS |
| knn_hC | PASS |
| knn_mean_dist | PASS |
| knn_n_eff | PASS |
| KNN coverage at inference (val, 240s) | 92.9% |

**All required KNN fields present and have real values at inference.** This is the first correct implementation of the KNN entry model.

| Metric | Value |
|--------|-------|
| Val AUC | 0.5381 |
| Entry threshold (val-tuned) | 0.60 |
| N features | 35 |
| Training population | bar-4+ observations (seconds_since_flip >= 240) |

---

## Phase 7: Bar-4 ML-Gated Results -- Test Periods

### Base cost, combined direction

| Period | Policy | EV/ep | WR | 95% CI | N Traded / Total |
|--------|--------|-------|-----|--------|-----------------|
| test_2024q4 | fixed_300s | -0.21 | 50.0% | (-1.05,+0.63) | 20/4459 |
| test_2024q4 | opposing_regime | -0.19 | 50.0% | (-0.99,+0.59) | 20/4459 |
| test_2025h1 | fixed_300s | -0.33 | 31.4% | (-0.79,+0.15) | 35/10904 |
| test_2025h1 | opposing_regime | -0.41 | 28.6% | (-0.91,+0.09) | 35/10904 |

> **Critical finding**: The 0.60 threshold selects only 20-35 trades out of 4,000-11,000 episodes (0.3-0.5% take rate). Any EV estimate from 20-35 trades is statistically meaningless. The model is too restrictive to be useful, and AUC=0.54 confirms there is no genuine predictive signal.

---

## Phase 7b: KNN Shuffle Control (Required)

KNN features permuted randomly across episodes at the bar-4 delay step. KNN coverage at inference is 93-97% (real values, not zeros). A Δ near zero means KNN adds no information after baseline features.

| Period | Policy | Real KNN | KNN Shuffle | Delta | Verdict |
|--------|--------|----------|------------|-------|---------|
| test_2024q4 | fixed_300s | -0.21 | -0.21 | 0.00 | **NULL** |
| test_2025h1 | fixed_300s | -0.33 | -0.33 | 0.00 | **NULL** |
| test_2024q4 | opposing_regime | -0.19 | -0.19 | 0.00 | **NULL** |
| test_2025h1 | opposing_regime | -0.41 | -0.41 | 0.00 | **NULL** |

**KNN verdict: NULL across all periods and policies.** Shuffling real KNN values (93-97% coverage) produces identical results to real KNN. The bar-4 KNN path-health scores add zero incremental predictive value beyond the 28 baseline OHLCV features.

---

## Phase 7c: Combined Test Summary

Combined test = Nov 2024 -- May 2025 (test_2024q4 + test_2025h1)

| Variant | Delay | EV/ep | WR | 95% CI | N Traded / Total |
|---------|-------|-------|-----|--------|-----------------|
| uncond_fixed | 180s | +1.99 | 44.2% | (-2.97,+7.28) | 12859/15363 |
| uncond_regime | 180s | +1.13 | 42.7% | (-3.61,+6.16) | 12862/15363 |
| bar4_uncond_f | 240s | -1.88 | 44.2% | (-6.62,+2.99) | 11811/15363 |
| bar4_ml_fixed | 240s | -0.30 | 38.2% | (-0.71,+0.14) | 55/15363 |
| bar4_ml_regime | 240s | -0.35 | 36.4% | (-0.76,+0.10) | 55/15363 |

---

## Final Verdict

### What this study confirmed

| Question | Answer |
|----------|--------|
| Is KNN properly implemented now? | Yes. Manifest PASS. 93-97% real values at inference. |
| Does KNN add value? | No. Shuffle control: Δ=0.00 across all conditions. KNN NULL. |
| Best unconditional delay on val? | 180s (least negative at -5.54 EV/ep on val). |
| Does 180s delay replicate positive on 2025-H1? | Yes (+3.81). |
| Is the result robust across both test periods? | No. 2024-Q4 = -2.44; 2025-H1 = +3.81. |
| Combined test EV positive? | +1.99 EV/ep (combined), but CI = (-2.97, +7.28). |
| Does ML gating at bar-4 help? | No. Only 20-35 trades; EV negative. |
| Survival filter vs timing? | Delay benefit is 100% survival filter. Timing is negative. |

### Updated recording of the branch

> A 2-3 minute survival delay with a fixed 300s exit shows mixed cross-period performance: positive on 2025-H1 (+3.81/ep) but negative on 2024-Q4 (-2.44/ep). The delay's benefit is entirely from the survival filter (avoiding quick-fail regimes), not from better entry timing. KNN is confirmed NULL -- even correctly implemented with real values at inference, permuting KNN features produces identical results. ML gating at bar-4 produces too few trades (20-35 per period) to be actionable. The OHLCV ceiling applies at every delay tested.

### Recommended action

Close the delayed-entry OHLCV branch. Three independent studies (delayed_health, delayed_entry_repair, v_a_1m_flip) all arrive at the same ceiling: OHLCV + KNN path features cannot discriminate profitable from losing post-flip entries. The survival filter is real but not monetizable with OHLCV features alone. Any further work requires orderflow / book depth / footprint data as input.

---

## Output File Inventory

| File | Description |
|------|-------------|
| `study_features.parquet` | All observations: features + KNN + forward labels (57 cols) |
| `episode_meta.parquet` | Per-episode metadata with new period assignments |
| `knn_manifest.json` | KNN field presence assertion (PASS) |
| `delay_sweep_val.parquet` | Val-period delay sweep results (60/120/180/240s) |
| `uncond_policy_results.parquet` | Unconditional test results (policy x cost x period x direction) |
| `matched_cohort.parquet` | Matched cohort decomposition (filter vs timing benefit) |
| `ml_policy_results.parquet` | Bar-4 ML-gated test results |
| `knn_control_results.parquet` | KNN shuffle control results with verdicts |
| `combined_test_results.parquet` | All variants combined test summary |
| `model_manifest.json` | Bar-4 model features, val AUC, manifest assertion |
| `final_report.md` | This file |
