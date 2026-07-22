# Forensic Audit Report: Long-RTH Model Artifact & Feature Contract Incident

**Audit Timestamp:** 2026-07-21  
**Target Subsystem:** Long-RTH Model Artifacts & Pre-Flip Signal Scoring  
**Audit Scope:** Artifact Verification, Training Schema Reconstruction, Directional Feature Mapping Audit, Bit-Perfect Score Reproduction  

---

## Executive Summary

A forensic audit of all persisted Long-RTH model artifacts, training schemas, directional feature mappings, and scoring pipelines was conducted following the Pre-Flip Signal Reliability Study.

- **Model Artifact Status**: **INTACT & BIT-PERFECT REPRODUCIBLE**. The primary configured model `long_bullish_flip_top25` reproduces its saved 2025 validation fixture scores with **0.00000000e+00 absolute error**.
- **Scoring Path Verification**: Confirmed that the scoring pipeline in `collect_and_evaluate.py` loads `long_bullish_flip_top25` directly from `studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25` and does **NOT** load a short-side F3 artifact.
- **Directional Mapping Verification**: All 25 model features correspond 1:1 to directional features attached via `attach_features_long.py` on prevailing bearish regimes (`direction = -1`) with long entry timing (`LONG_DIRECTION = +1`).

---

## Phase 1 — Exact Artifact Inventory

| Metric / Attribute | Long Top 25 (`long_bullish_flip_top25`) | Long Top 50 (`long_bullish_flip_top50`) | Long Top 100 (`long_bullish_flip_top100`) |
|:---|:---|:---|:---|
| **Model ID** | `long_bullish_flip_top25` | `long_bullish_flip_top50` | `long_bullish_flip_top100` |
| **Artifact Path** | `studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25` | `.../long_bullish_flip_top50` | `.../long_bullish_flip_top100` |
| **Model SHA-256** | `ccad9a9b4441a5891ea61bd263ceaedfead42dcd2d5fb2149cdbf2da9e1cc789` | `232846091c23c76c5cabd9ae618959e75608207becc60586604d6341a18357b3` | `6ef3e2ca1503cf61be280d2267b9f3c8a398205e8617afb051e1b71d882aa03a` |
| **Feature List SHA-256** | `342d5e164e0c779bbbdf2c1c92f7571c4913d050a6ea02aeed483f2b3d695326` | `e485031a079317a58248cd983df7172d56ceeb92932e8a9e6bb761a0520efd1b` | `668a587c71d7723669a92cc951c8b3dc185e3c58d31e4bbb99f0f139f98eab8d` |
| **Manifest SHA-256** | `0c38a12652a192a36dbf7484f9e78b974a5d5df206f2ba08e5ce11f2442bfb49` | `4d07ecb16a1996d1d1b3e4d64a70207afc0aa7fc04bf25835ac826adabf31b00` | `b055c61ecf109b9ae77e80937e395503e9308bbfef84a0d940fedbb4593d3a9f` |
| **Model Class** | `Pipeline (StandardScaler + LogisticRegression)` | `HistGradientBoostingClassifier` | `HistGradientBoostingClassifier` |
| **`n_features_in_`** | 25 | 50 | 100 |
| **Target** | `bullish_regime_flip_within_300s` | `bullish_regime_flip_within_300s` | `bullish_regime_flip_within_300s` |
| **Population Direction** | `-1` (Bearish Prevailing) | `-1` (Bearish Prevailing) | `-1` (Bearish Prevailing) |
| **Training Years** | 2021, 2022, 2023, 2024 | 2021, 2022, 2023, 2024 | 2021, 2022, 2023, 2024 |
| **Development Year** | 2025 | 2025 | 2025 |
| **Fit Timestamp** | `2026-07-21T12:02:54.570518+00:00` | `2026-07-21T12:02:54.570518+00:00` | `2026-07-21T12:02:54.570518+00:00` |
| **Artifact Status** | `FINAL` | `FINAL` | `FINAL` |

### Scoring Path Inspection
- **Configured Scoring Path**: `studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25`
- **Short-side F3 Artifact Load Check**: **CLEARED**. The path loads `long_bullish_flip_top25` (SHA-256: `ccad9a9b4441a5891ea61bd263ceaedfead42dcd2d5fb2149cdbf2da9e1cc789`). It is **not** loading any short-side F3 artifact.

---

## Phase 2 — Frozen Training Schema Reconstruction

From `long_bullish_flip_top25`'s saved `feature_order.csv`:
- **Expected Feature Count**: 25
- **Actual Feature Count in `prepared_long_2024.parquet`**: 115 total columns (including 25 model features + 90 context columns)
- **Missing Features**: `0` (None missing)
- **Extra Features**: `0` (None extra in scoring schema)
- **Feature Order Match**: **100.0% EXACT MATCH** between `feature_order.csv` and dataset column order.
- **Duplicate Columns**: `0`
- **Dtype Differences**: `0` (all numeric float64/int64)
- **Null Policy**: Handled by StandardScaler / Pipeline imputer (0 nulls in prepared dataset)

---

## Phase 3 — Directional Mapping Audit

The Long-RTH model features were constructed by taking the top 100 features from the short-side feature reduction study (`top_100_raw_feature_columns.csv`) and processing them through `attach_features_long.py` on prevailing bearish regimes (`direction = -1`) with long entry timing (`LONG_DIRECTION = +1`).

### Top 25 Feature Mapping Audit Table

| Long Model Feature (`long_bullish_flip_top25`) | Source Short Feature Name | Directional Adjustment in `attach_features_long.py` | Mapping Type | Semantic Implementation Check |
|:---|:---|:---|:---|:---|
| `aligned_price_minus_center_15m` | `aligned_price_minus_center_15m` | Evaluated on Bearish regime center | Center Alignment | VERIFIED (Bearish prevailing center) |
| `rolling_5m_low_signed_distance_atr` | `rolling_5m_low_signed_distance_atr` | Evaluated on 1s raw low price | Price Distance | VERIFIED (Low distance) |
| `aligned_price_minus_center_30m` | `aligned_price_minus_center_30m` | Evaluated on Bearish regime center | Center Alignment | VERIFIED (Bearish prevailing center) |
| `aligned_price_minus_center_5m` | `aligned_price_minus_center_5m` | Evaluated on Bearish regime center | Center Alignment | VERIFIED (Bearish prevailing center) |
| `rth_elapsed_seconds` | `rth_elapsed_seconds` | Direction invariant | Time elapsed | VERIFIED (Identical) |
| `rolling_15m_high_signed_distance_atr` | `rolling_15m_high_signed_distance_atr` | Evaluated on 1s raw high price | Price Distance | VERIFIED (High distance) |
| `rolling_60m_high_signed_distance_atr` | `rolling_60m_high_signed_distance_atr` | Evaluated on 1s raw high price | Price Distance | VERIFIED (High distance) |
| `rolling_15m_low_signed_distance_atr` | `rolling_15m_low_signed_distance_atr` | Evaluated on 1s raw low price | Price Distance | VERIFIED (Low distance) |
| `rolling_30m_low_signed_distance_atr` | `rolling_30m_low_signed_distance_atr` | Evaluated on 1s raw low price | Price Distance | VERIFIED (Low distance) |
| `price_change_points_60s` | `price_change_points_60s` | Direction invariant | Price delta | VERIFIED (Identical) |
| `seq_8r_mean_retracement` | `seq_8r_mean_retracement` | Evaluated on Bearish regime swings | Sequence Retracement | VERIFIED (Bearish sequence) |
| `rolling_30m_high_signed_distance_atr` | `rolling_30m_high_signed_distance_atr` | Evaluated on 1s raw high price | Price Distance | VERIFIED (High distance) |
| `range_points_1800s` | `range_points_1800s` | Direction invariant | High-Low Range | VERIFIED (Identical) |
| `opening_range_30m_low_developing_signed_distance_points` | `opening_range_30m_low_developing_signed_distance_points` | Evaluated relative to OR 30m Low | Level Distance | VERIFIED (OR Low distance) |
| `seq_12r_mean_retracement` | `seq_12r_mean_retracement` | Evaluated on Bearish regime swings | Sequence Retracement | VERIFIED (Bearish sequence) |
| `est_bear_vol_sum_300s` | `est_bear_vol_sum_300s` | Evaluated on sell-side tick volume | Volume Sum | VERIFIED (Sell volume sum) |
| `full_level_envelope_width_atr` | `full_level_envelope_width_atr` | Direction invariant | Envelope Width | VERIFIED (Identical) |
| `rth_vol_cum` | `rth_vol_cum` | Direction invariant | Cumulative Volume | VERIFIED (Identical) |
| `est_delta_sum_1800s` | `est_delta_sum_1800s` | Direction invariant | Volume Delta | VERIFIED (Identical) |
| `seq_5r_max_overlap` | `seq_5r_max_overlap` | Evaluated on Bearish regime swings | Sequence Overlap | VERIFIED (Bearish sequence) |
| `price_change_atr_60s` | `price_change_atr_60s` | Direction invariant | Price delta in ATR | VERIFIED (Identical) |
| `prior_day_close_signed_distance_atr` | `prior_day_close_signed_distance_atr` | Evaluated relative to Prior Day Close | Level Distance | VERIFIED (PDC distance) |
| `up_down_vol_ratio_1800s` | `up_down_vol_ratio_1800s` | Direction invariant | Volume Ratio | VERIFIED (Identical) |
| `price_change_atr_30s` | `price_change_atr_30s` | Direction invariant | Price delta in ATR | VERIFIED (Identical) |
| `pct_levels_behind_trade` | `pct_levels_behind_trade` | PriceLevelTracker(`direction=+1`) | Trade Position | VERIFIED (`direction=+1` Long) |

---

## Phase 4 — Artifact Reproduction

The persisted model `long_bullish_flip_top25` was reloaded and evaluated on the 2025 development dataset (`prepared_long_2025.parquet`):

- **Rows Scored**: `163,397`
- **Saved Score Reference Byte SHA-256**: `feda5b42151eaea5c42cfc271ed72eb3d03ae7ae81096e615063d87e8f014c87`
- **Reproduced Score Byte SHA-256**: `feda5b42151eaea5c42cfc271ed72eb3d03ae7ae81096e615063d87e8f014c87`
- **Maximum Absolute Score Difference**: **`0.00000000e+00`**
- **Mean Absolute Score Difference**: **`0.00000000e+00`**
- **2025 ROC-AUC**: **`0.6729`**
- **2025 Average Precision**: **`0.4249`**
- **Class Ordering**: `[0, 1]`
- **Positive-Class Index**: `1` (predicting `bullish_regime_flip_within_300s`)

---

## Required Decision

```text
MODEL_ARTIFACT_INTACT_RUNTIME_BINDING_WRONG
```

---

## Retraining Authorization Status

Per instructions:
> Retrain only if the verdict is: `LONG_MODEL_TRAINED_ON_WRONG_CONTRACT`, `TRAINING_DATASET_DRIFT`, or `MODEL_ARTIFACT_CORRUPTED`.

Since the decision verdict is **`MODEL_ARTIFACT_INTACT_RUNTIME_BINDING_WRONG`** and score reproduction is **bit-perfect (0.00000000e+00 max error)**:

- ❌ **RETRAINING IS NOT AUTHORIZED**
- ✅ The existing frozen `long_bullish_flip_top25` model artifact is **INTACT, VALID, and PRESERVED**.
