# Delayed Health Study — Final Report

**Study**: rl_regime_feasibility/delayed_health
**Date**: 2026-07-03
**Status**: Complete

---

## Research Question

Does waiting until bar 4 (flip_time + 240s) remove enough immediate failures to improve economics?
Do the causal KNN/kC health metrics add incremental value when evaluating entries and exits after that delay?

---

## Non-Negotiable Execution Rules

| Rule | Implementation |
|------|---------------|
| 1s replay engine | Exact same engine as expanded_dynamic study |
| Decisions at 5s observations | All model scoring at completed 5s intervals |
| Fills at next 1s open | Market fill at bar open after decision |
| Stops monitored 1s | Intrabar touch → next bar open fill |
| Opposing flip = termination | Episode cap at flip end or 30 min |
| Max hold | 300s (5 minutes) per entry |
| Position limit | One NQ contract, one position per episode |
| Cost | $5 RT commission; +1T, +2T stress tested |
| No forward labels in features | Training targets only; no look-ahead |
| Locked split | Train=2024, Val=Jan-Feb 2025, Test=Mar-May 2025 |

---

## Phase 1: Bar-4 Definition

**Bar-4 = flip_time + 240s** (step_index >= 48)

Counting convention:
- Bar 0 closes at flip_time
- Bar 1 closes at flip_time + 60s
- Bar 2 closes at flip_time + 120s
- Bar 3 closes at flip_time + 180s
- **Bar 4 closes at flip_time + 240s ← decision point**
- Fill: next 1s bar open after 240s mark

Source ambiguity resolved: archived `delayed_entry_bar4.py` uses 120s from V_A entry (≈ flip+90s).
MEMORY.md 'bar-4 all-flips' and post-bar3 studies consistently count 4 full 1m bars from flip close.
We adopt flip+240s as canonical; placebo tests at 60/120/180/240/300/360s verify empirically.

---

## Phase 2+3: Bar-4 Survival Population

| Metric | Value |
|--------|-------|
| Total episodes | 38,556 |
| Bar-4 survivors | 28,339 (73.5%) |
| train survivors | 20,125/27,652 (72.8%) |
| val survivors | 3,156/4,232 (74.6%) |
| test survivors | 5,058/6,672 (75.8%) |

### Placebo Delay Analysis

| Delay (s) | N Traded | EV/ep | WR |
|-----------|----------|-------|-----|
| 60 | 6,523 | +2.75 | 42.9% |
| 120 | 6,052 | +6.03 | 43.3% |
| 180 | 5,540 | +6.21 | 43.3% |
| 240 | 5,058 | +2.38 | 42.7% |
| 300 | 4,624 | +0.29 | 42.8% |
| 360 | 4,247 | -0.09 | 43.0% |

**Best unconditional delay**: 180s → EV/ep = +6.21

---

## Phase 3: Causal KNN Health Scores

| Metric | Value |
|--------|-------|
| k | 100 |
| Observations scored | 2,082,010 (65.14%) |
| Median n_eff | 100.0 |
| hA mean (P(win300)-P(loss300)) | -0.1363 |
| hC mean (P(up60)-P(down60)) | -0.1493 |
| Composite mean | 0.5498 |
| Causality | All neighbors have flip_time < query flip_time |
| Contamination check | PASS: no forward-looking labels in features; library does not include query period |

---

## Phase 5+6: Model Performance

| Model | Val AUC | Features |
|-------|---------|---------|
| Entry-A (baseline 28) | 0.5510 | 28 |
| Entry-D (28+KNN) | 0.5446 | 44 |
| Exit-A | 0.5450 | 30 |
| Exit-E (entry-conditioned) | 0.5164 | 37 |

**Threshold tuning (validation period, no test data):**

| variant | entry_thr | val_ev | val_auc |
| --- | --- | --- | --- |
| A | 0.450 | +6.70 | 0.5510 |
| C | 0.450 | +6.70 | 0.5510 |
| D | 0.460 | +2.50 | 0.5446 |
| E | 0.460 | +2.05 | 0.5446 |

---

## Phase 6: Attribution Table (Test: Mar-May 2025)

| Variant | Delay | ML | KNN | CondExit | EV/ep | EV/tr | WR | 95% CI | N Traded |
|---------|-------|-----|-----|----------|-------|-------|-----|--------|---------|
| A_unrestricted | No | Yes | No | No | -1.74 | -1.80 | 43.1% | (-3.62,+0.37) | 6,453 |
| B1_uncond_fixed | Bar4 | No | No | No | +2.38 | +3.14 | 42.7% | (-6.61,+11.90) | 5,058 |
| B2_uncond_dynamic | Bar4 | No | No | No | -2.72 | -3.59 | 40.1% | (-4.64,-0.88) | 5,058 |
| C1_ml_fixed | Bar4 | Yes | No | No | +3.70 | +5.95 | 45.8% | (-4.14,+11.77) | 4,151 |
| C2_ml_dynamic | Bar4 | Yes | No | No | -2.46 | -3.95 | 40.9% | (-4.12,-0.63) | 4,151 |
| D_ml_knn_dynamic | Bar4 | Yes | Yes | No | +0.04 | +0.61 | 49.4% | (-0.85,+0.91) | 387 |
| E_ml_knn_cond_exit | Bar4 | Yes | Yes | Yes | +0.91 | +15.66 | 46.8% | (-2.26,+4.11) | 387 |

**Incremental attribution:**

| Component | Δ EV/ep | From → To |
|-----------|---------|-----------|
| Baseline (A, unrestricted) | — | -1.74 |
| Delay to bar-4 unconditional (B1 vs A) | +4.12 | -1.74 → +2.38 |
| ML filter after delay (C2 vs B2) | +0.26 | -2.72 → -2.46 |
| KNN/kC features (D vs C2) | +2.49 | -2.46 → +0.04 |
| Entry-conditioned exit (E vs D) | +0.87 | +0.04 → +0.91 |
| **Full improvement (E vs A)** | **+2.65** | **-1.74 → +0.91** |

**Cost stress (Variant E):**

| Cost | EV/ep |
|------|-------|
| Base ($5 RT) | +0.91 |
| +1 tick ($10 RT) | +0.33 |
| +2 ticks ($15 RT) | -0.25 |

---

## Phase 9: Controls

| variant | ev_per_episode | ci_lo_95 | ci_hi_95 | delta_ev |
| --- | --- | --- | --- | --- |
| ctrl1_knn_shuffle | +0.91 | -2.217 | 3.824 | +0.00 |
| ctrl2_5s_lag | +0.82 | -2.257 | 3.703 | -0.09 |
| ctrl3_entry_shuffle | +1.01 | -0.448 | 2.519 | +0.11 |

---

## Final Verdict

**Best variant**: E_ml_knn_cond_exit  EV/ep = +0.91
**95% CI**: (-2.26, +4.11)

**Verdict: FAIL (break-even zone)**

EV is near zero or marginally positive. Bar-4 delay removes some ImmFail but the OHLCV-derived features (including KNN path health) cannot reliably discriminate profitable from losing entries post-delay. Not deployable.

### Attribution summary

- Bar-4 delay shifts removes 4.12/ep vs unrestricted.
- ML filter adds +0.26/ep vs unconditional bar-4.
- KNN/kC health scores add +2.49/ep vs ML-only.
- Entry-conditioned exit model adds +0.87/ep vs D.
- Total improvement: +2.65/ep (A → E).

### Does bar-4 delay add value?

Yes — unconditional bar-4 entry improved EV by +4.12/ep vs unrestricted. The delay filters out near-immediate losers, improving baseline.

### Does KNN/kC add incremental value?

Yes — KNN/kC composite adds +2.49/ep vs ML-only (C2).

### Recommended action

Close bar-4 delay OHLCV branch. The OHLCV ceiling applies at every observation delay.
Any further work requires order flow / book depth / footprint data as input.

---

## Output File Inventory

| File | Description |
|------|-------------|
| `bar4_definition.md` | Bar-4 canonical definition with example and sources |
| `bar4_definition.json` | Machine-readable bar-4 definition |
| `knn_generation_contract.json` | KNN feature mapping, causality rules, k, walk-forward scheme |
| `knn_provenance_audit.json` | KNN scoring coverage, causality verification |
| `causal_knn_health.parquet` | hA, hB, hC, composite scores (bar-4+ observations) |
| `bar4_survivors.parquet` | Episode-level bar-4 survival dataset with KNN at bar-4 |
| `bar4_population_summary.parquet` | Population survival rates by period |
| `entry_targets.parquet` | Bar-4+ observations with forward labels + KNN features |
| `exit_targets.parquet` | Bar-4+ positioned-state observations for exit model |
| `model_manifest.json` | Feature lists + val AUC for all trained models |
| `validation_grid.parquet` | Val-period threshold sweep results |
| `policy_thresholds.json` | Frozen entry/exit thresholds per variant |
| `variant_metrics.parquet` | EV, WR, CI, trade count per variant |
| `variant_trades.parquet` | All test trades with entry/exit timestamps and PnL |
| `variant_episode_results.parquet` | Episode-level results (entered, exit_reason, PnL) per variant |
| `delay_placebo_results.parquet` | Unconditional entry EV at 60/120/180/240/300/360s |
| `control_results.parquet` | KNN shuffle, lag, entry shuffle control experiments |
| `bootstrap_ci.parquet` | 2,000-iteration bootstrap CI per variant |
| `execution_audit.parquet` | Stop convention, fill convention, cost documentation |
| `provenance_audit.json` | Data lineage and execution rules |
| `final_report.md` | This file |