# KNN/kC Artifact Audit

**Study**: rl_regime_feasibility/expanded_dynamic
**Date**: 2026-07-03

## Summary

| Artifact | Classification | Use Decision |
|----------|---------------|-------------|
| `regime_dna.parquet` | CAUSAL_SAFE | INCLUDE |
| `early_health_capsule.parquet` | CAUSAL_UNCERTAIN | EXCLUDE |
| `dna_knn_scores.parquet` | NONCAUSAL | EXCLUDE |
| `obs_depth0p25/0p5/0p75.parquet (hC values)` | NONCAUSAL | EXCLUDE |
| `hc_sizing_extremes/trades.parquet` | NONCAUSAL | EXCLUDE |
| `transition_atlas.parquet / opportunity_curve.parquet` | NONCAUSAL | EXCLUDE |

## Detailed Findings

### `regime_dna.parquet`
**Location**: `backtests/studies/regime_dna_knn/results/regime_dna.parquet`
**Shape**: 146831 x 68
**Key columns**: regime_start_ts, pre_5/15/30_* (48 pre-flip features), ema9/21_slope, distance_to_vwap
**Classification**: **CAUSAL_SAFE**
**Rationale**: All pre_5/15/30 features are computed exclusively from 1m bars COMPLETED before the flip bar. regime_start_ts is the CLOSE of the flip bar. EMA slopes and distances are at flip-bar close. VWAP and session high/low use only bars through flip-bar close. 100% overlap with RL episode flip_time universe.
**Decision**: INCLUDE — join on flip_time=regime_start_ts as pre-flip context features

### `early_health_capsule.parquet`
**Location**: `backtests/studies/regime_dna_knn/results/early_health_capsule.parquet`
**Shape**: 146831 x 21
**Key columns**: regime_start_ts, pre5_efficiency, pre5_compression, n_post, post_o/h/l/c/v
**Classification**: **CAUSAL_UNCERTAIN**
**Rationale**: pre5_* features are CAUSAL_SAFE (same logic as regime_dna pre_5_*). But n_post and post_o/h/l/c/v record the FIRST bar AFTER the flip — forward-looking relative to the flip. No causal guarantee on post_* columns.
**Decision**: EXCLUDE — pre5 columns are redundant with regime_dna; post_* are forward-looking

### `dna_knn_scores.parquet`
**Location**: `backtests/studies/regime_dna_knn/results/dna_knn_scores.parquet`
**Shape**: 1314501 x 42
**Key columns**: regime_id, bar_ts, score_pt050_sl025..score_failure_risk, score_expected_net
**Classification**: **NONCAUSAL**
**Rationale**: KNN scores are trained on regime_dna DNA features via leave-one-out KNN lookup. The training set includes all years, meaning OOS regime IDs have neighbors from future years in the index. Additionally per MEMORY.md: 'Bar-4 KNN path-atlas: calibrated for RISK/TIMING, blind on OPPORTUNITY/DIRECTION. rem-MFE skill +5% & P(+1 before -1) FLAT ~45% (blind). Closes V_A/flip+hC/Model-B line.' Dead signal class.
**Decision**: EXCLUDE — non-causal train/test contamination + dead signal per audit

### `obs_depth0p25/0p5/0p75.parquet (hC values)`
**Location**: `studies/pullback_dna/results/obs_depth*.parquet`
**Shape**: 23K-31K x 38 (per file)
**Key columns**: regime_start_ts, entry_ts, hC, hC_velocity, state
**Classification**: **NONCAUSAL**
**Rationale**: These files record only regimes where hC >= 0.50 at pullback entry (bar 8+). Using them as RL features creates selection bias: ~57% of RL episodes have no pullback obs record. The hC value is computed at pullback entry_ts, not at the 5s observation time. The underlying components (EMA alignment, ATR, regime state) are already captured in existing features (ema3_ema9_spread, regime_5s/30s/5m aligned, adx14).
**Decision**: EXCLUDE — selection bias + already covered by existing features

### `hc_sizing_extremes/trades.parquet`
**Location**: `studies/hc_sizing_extremes/trades.parquet`
**Shape**: 60 x 42
**Key columns**: decision_ts, hC, sizing_factor
**Classification**: **NONCAUSAL**
**Rationale**: Only 60 trades covering 2025; too small a subset to use as features. hC at decision time is from the same pullback_dna computation logic. Not joinable to RL episode universe in a representative way.
**Decision**: EXCLUDE — too few samples, not representative

### `transition_atlas.parquet / opportunity_curve.parquet`
**Location**: `studies/pullback_dna/results/reports/*.parquet`
**Shape**: 253 x 14 / 9 x 5
**Key columns**: t_s (seconds), survival/probability summary statistics
**Classification**: **NONCAUSAL**
**Rationale**: Population-level summary statistics (e.g., P(reach 0.5 ATR | alive at t=30s)). These are derived from the FULL outcome distribution and would inject look-ahead if used as per-observation features. They are not per-episode.
**Decision**: EXCLUDE — population summary statistics; forward-looking if used as features

## Approved Features for Expanded Study

Only one external artifact is approved for joining:
- **`regime_dna.parquet`** (CAUSAL_SAFE): 47 pre-flip features joined on `flip_time = regime_start_ts`
- **Existing 28 features** from `feature_snapshots.parquet`
- **~25 derived interaction/ratio features** computed from the above

Total planned features: ~100
