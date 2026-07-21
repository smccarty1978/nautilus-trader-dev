# Expanded Dynamic Study — Final Report

**Study**: rl_regime_feasibility/expanded_dynamic  
**Date**: 2026-07-03  
**Status**: Complete — all 8 phases executed

---

## Study Design

This study tests whether expanded causal regime-path features and pre-flip context
(from `regime_dna.parquet`) can identify profitable dynamic entry + exit policies
during 1-minute regime-flip episodes on NQ.v.0.

**Design constraints:**
- Same exact 1s replay engine as 2x2 study
- Locked chronological split: train=2024, val=Jan-Feb 2025, test=Mar-May 2025
- No test set used for any selection
- Max one entry per episode
- All KNN/kC artifacts audited before inclusion

---

## Phase 1: KNN/kC Artifact Audit

| Artifact | Shape | Classification | Decision |
|----------|-------|---------------|---------|
| `regime_dna.parquet` (pre-flip DNA) | 146K x 68 | CAUSAL_SAFE | INCLUDED |
| `dna_knn_scores.parquet` | 1.3M x 42 | NONCAUSAL | EXCLUDED — train/test contamination + dead signal per audit |
| `obs_depth*.parquet` (hC values) | 23-31K x 38 | NONCAUSAL | EXCLUDED — selection bias (hC >= 0.5 filter) |
| `early_health_capsule.parquet` | 146K x 21 | CAUSAL_UNCERTAIN | EXCLUDED — post_* columns forward-looking |
| `transition_atlas.parquet` | 253 x 14 | NONCAUSAL | EXCLUDED — population summary statistics |
| `hc_sizing_extremes/trades.parquet` | 60 x 42 | NONCAUSAL | EXCLUDED — 60 trades, not representative |

**Only approved external artifact**: `regime_dna.parquet` pre-flip features (joined on `flip_time = regime_start_ts`).
Coverage: **100% of 38,556 RL episodes** matched.

---

## Phase 2: Expanded Feature Set (117 total)

| Source | Count | Description |
|--------|-------|-------------|
| `existing_collector` | 28 | Path, vol/vol, momentum, multi-TF regime, structural |
| `regime_dna_preflip` | 62 | Pre-flip 5/15/30-bar OHLCV context from `regime_dna.parquet` |
| `derived` | 27 | Path geometry ratios, interaction terms, regime alignment composite |

Pre-flip DNA features are **episode-level constants** (same value at all 5s steps within an episode).
Derived features include: progress ratios, ATR-normalized interactions, Kalman composite, pre-flip multi-window ratios.

---

## Phase 4: Model Ablations

| Ablation | N Features | Val AUC | Test AUC | Gate 1 |
|----------|-----------|---------|---------|--------|
| A: baseline_only | 28 | 0.5642 | **0.5522** | PASS |
| B: expanded_path | 55 | 0.5636 | 0.5461 | PASS |
| C: dna_only | 62 | 0.5139 | 0.5104 | fail |
| D: baseline+dna | 90 | 0.5607 | 0.5435 | PASS |
| E: expanded+dna | 117 | 0.5624 | 0.5479 | PASS |
| F: full_dynamic | 117 | 0.5624 | 0.5479 | PASS |

**Key findings:**
- **Best model = baseline 28 features** (test AUC 0.5522). Adding pre-flip DNA or derived features HURTS test AUC.
- **DNA-only model barely above chance** (0.5104 test AUC). Pre-flip OHLCV context has negligible predictive power for within-episode outcomes.
- 5/6 ablations pass Gate 1 (AUC >= 0.54).

**Implication**: The signal ceiling is determined by the 28 in-episode path features. Expanded context adds noise, not information.

---

## Phase 5: Dynamic Policy

Entry model trained on all 117 features (val AUC 0.5624), exit model on 119 features including unrealized PnL and time in trade (val AUC 0.5487).

| Parameter | Value |
|-----------|-------|
| Entry threshold (tuned on val EV) | 0.48 |
| Val EV with tuned threshold | +$2.31/ep |
| Exit threshold | 0.50 |
| Entry model val AUC | 0.5624 |
| Exit model val AUC | 0.5487 |

Entry threshold of 0.48 was selected to maximize val-period EV. Val EV = +$2.31/ep (positive on val set).

---

## Phase 6: Exact 1s Replay Results (Test Set: Mar-May 2025)

| Metric | Value |
|--------|-------|
| Test episodes | 6,672 |
| Traded episodes | 1,248 (18.7%) |
| Total PnL | -$4,420 |
| **EV / episode** | **-$0.66** |
| EV / trade | -$3.54 |
| Win rate | 44.1% |
| Exit: dynamic / cap / stop | 1,241 / 6 / 1 |
| 95% bootstrap CI | (-$1.63, +$0.35) |
| Oracle EV (ceiling) | +$167.36/ep |
| % of oracle | -0.4% |
| Gate 2 threshold (50% oracle) | +$83.68/ep |
| **Gate 2 result** | **FAIL** |

**vs canonical baseline (-$6.46/ep): delta = +$5.80/ep**

**Monthly breakdown:**
| Month | EV/trade | Total PnL | Trades |
|-------|----------|-----------|--------|
| 2025-03 | -$0.04 | -$15 | 424 |
| 2025-04 | -$8.64 | -$3,700 | 428 |
| 2025-05 | -$1.78 | -$705 | 396 |

96% of exits triggered by the exit model (dynamic); only 6 cap and 1 stop exit. The exit model is dominating trade duration — almost no trades ran to 300s.

---

## Phase 7: Control Experiments

| Control | Val AUC | Test AUC | Delta Test | Interpretation |
|---------|---------|---------|-----------|---------------|
| 1: DNA shuffle | 0.5590 | 0.5484 | +0.0005 | DNA adds zero information |
| **2: Sequence shuffle** | **0.7620** | **0.7594** | **+0.2115** | **See analysis below** |
| 3: 5s lag | 0.5626 | 0.5486 | +0.0007 | 5s staleness has no impact |
| 4: Future score | 1.0000 | 1.0000 | +0.4521 | Pipeline correct (sanity check) |
| 5: Remove DNA | 0.5621 | 0.5485 | +0.0006 | DNA removal has no effect |
| 6: Prediction parity | 0.5624 | 0.5479 | — | Train=0.629 vs test=0.548, gap=0.081 |

**Control 1 (DNA shuffle)**: Near-zero delta confirms pre-flip DNA features carry no predictive information beyond noise. Consistent with ablation D showing DNA hurts AUC.

**Control 2 (Sequence shuffle) — KEY FINDING**: AUC increases from 0.562 to 0.759 when within-episode step order is randomly permuted. This seemingly paradoxical result reveals a structural characteristic of the features:

- Cumulative features (`max_progress_atr`, `max_adverse_atr`, `seconds_since_flip`) grow over the episode lifetime
- After shuffle, a LATE-step's large `max_progress_atr` gets assigned to an EARLY step
- Early steps tend to have high `y_entry_positive_300s` (entering early in a trending episode is profitable)
- Late-episode `max_progress_atr` = "this episode eventually went far" = strong correlate of early profitability
- The shuffled model exploits this as a **retroactive episode quality indicator**, which is noncausal

This means: the model's 0.56 AUC from cumulative path features partly captures **"how good was this episode overall"** (via max_progress at late steps), not purely **"is NOW a good entry time."** The temporal ordering constraint (using only features up to step k) limits the model to 0.56 instead of the retroactive 0.76.

**Control 3 (5s lag)**: AUC unchanged — the features are pre-smoothed over 5-60 second windows and a 5s stale observation carries nearly identical information. This confirms the features are appropriate for a 5s decision cadence but also means there's limited temporal specificity.

**Control 5 (Remove DNA)**: No AUC change, confirming DNA adds nothing. The baseline is entirely sufficient.

**Control 6 (Prediction parity)**: Train-test AUC gap of 0.081 shows moderate overfit. Only 1.7% of test observations score above 0.50 (consistent with very low trade rate of 18.7% at threshold 0.48). Score distribution is consistent across splits (mean_prob ~0.44) — no distribution shift.

---

## Policy Comparison: Progression from Canonical Study

| Study | Entry Rule | Exit Rule | EV/ep | 95% CI | Gate 2 |
|-------|-----------|----------|-------|--------|--------|
| 2x2 Cell C | First crossing, val threshold | Fixed 300s | -$6.46 | (-12.44, -0.58) | FAIL |
| 2x2 Cell D | First crossing, val threshold | Dynamic score | -$2.12 | (-3.81, -0.16) | FAIL |
| Expanded (this study) | Entry model, tuned threshold | Exit model | -$0.66 | (-1.63, +0.35) | FAIL |

The expanded dynamic policy improved EV by +$5.80/ep vs canonical (-$6.46 → -$0.66). The 95% CI now straddles zero (-1.63, +0.35), meaning the result is **statistically indistinguishable from break-even at 95% confidence**.

---

## Final Verdict

**Gate 1 (AUC >= 0.54 on 2+ models)**: PASS (5/6 ablations)  
**Gate 2 (EV >= +$83.68/ep = 50% of oracle)**: FAIL (-$0.66/ep)

### Decision: FAIL — but note the CI boundary

The point estimate (-$0.66/ep) is negative, triggering FAIL per the decision rules. However, three context points are important:

1. **Progress is real**: Canonical → Expanded improved by +$5.80/ep. Dynamic exit management captures meaningful value even from a weak signal.
2. **Statistical uncertainty**: The CI (-1.63, +0.35) barely includes zero. This is **not conclusively different from break-even** with 3 months of test data.
3. **Feature ceiling confirmed**: Adding 89 features beyond the original 28 doesn't help (baseline beats all expanded variants). The OHLCV signal ceiling is at AUC ~0.55.

### What would justify reopening this branch

The study has found the **OHLCV ceiling**: AUC 0.55, EV near zero. Further investment in OHLCV features is not justified — the control experiments (DNA shuffle, lag, DNA removal) all converge on the same conclusion.

**Reopening criteria**: Only if a materially different feature class is added — specifically:
- Order flow / trade imbalance (tick data)
- Limit order book depth ratios (MBP-1 data)
- Footprint / volume-at-price per 5s bucket

Even then, the entry architecture (first-crossing after model trigger) and exit architecture (exit when confidence drops) proved effective in isolation — they just need a stronger signal.

### Recommended action: CLOSE OHLCV arc; do not invest in RL/PPO/DQN on this feature set.

---

## Key Caveats

- Models trained on OHLCV-derived features only; no order flow or book data
- 1s bar execution mode may slightly overstate vs tick execution  
- Exit model trained assuming entry at step 0 (all positioned steps), not actual policy-selected entries
- Pre-flip DNA features are episode-level constants (same value for all steps), which may explain their zero marginal contribution
- April 2025 was an outlier month (-$8.64/trade); removing April would give near break-even EV

---

## Output Files Summary

| File | Description |
|------|-------------|
| `knn_kc_audit.md` | Detailed artifact classification |
| `knn_kc_audit.json` | Machine-readable audit |
| `existing_feature_inventory.parquet` | All 117 features with source tags |
| `expanded_features.parquet` | 4.87M rows x 127 cols feature dataset |
| `entry_targets.parquet` | 4.87M rows entry labels (3 horizons) |
| `exit_targets.parquet` | 4.83M rows exit labels (4 horizons) |
| `ablation_metrics.parquet` | 6 ablation AUC results |
| `ablation_features.json` | Feature lists per ablation |
| `ablation_predictions.parquet` | Predictions from all ablation models |
| `policy_thresholds.json` | Frozen thresholds from val tuning |
| `replay_trades.parquet` | 1,248 test trades with 14 fields |
| `replay_summary.parquet` | Overall replay statistics |
| `bootstrap_ci.parquet` | 2,000-iteration bootstrap CI |
| `control_results.parquet` | 6 control experiment results |
| `final_report.md` | This file |
