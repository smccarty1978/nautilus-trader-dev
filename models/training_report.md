# ML Model Training Report
Generated: 2026-01-27 20:15:21.976768

## Data Summary
- **Source**: studies/mfe_mae_foundation/results/ml_features_2025.parquet
- **Train**: Jan-Sep 2025
- **Test**: Oct-Dec 2025 (holdout)
- **Features**: 64 (from FEATURES.md)
- **Algorithm**: LightGBM

---

## Model 1: Immediate Fail Detector

### Performance Metrics
| Metric | Train | Test |
|--------|-------|------|
| ROC-AUC | 0.6902 | 0.6067 |
| Accuracy | 0.7028 | 0.6704 |

### Precision/Recall by Threshold
| Threshold | Precision | Recall | F1 | N Predicted |
|-----------|-----------|--------|-----|-------------|
| 0.3 | 0.239 | 0.985 | 0.385 | 12,868 |
| 0.4 | 0.261 | 0.845 | 0.399 | 10,122 |
| 0.5 | 0.324 | 0.370 | 0.346 | 3,576 |
| 0.6 | 0.419 | 0.111 | 0.175 | 825 |
| 0.7 | 0.510 | 0.034 | 0.064 | 210 |
| 0.8 | 0.773 | 0.005 | 0.011 | 22 |

### Top 10 Features
| Rank | Feature | Importance |
|------|---------|------------|
| 1 | touch_overshoot_atr | 10476.1 |
| 2 | touch_precision | 9547.1 |
| 3 | touch_bar_size_atr | 4503.4 |
| 4 | touch_bar_body_ratio | 1858.9 |
| 5 | touch_bar_upper_wick | 1636.0 |
| 6 | touch_bar_lower_wick | 1419.7 |
| 7 | close_vs_range_30s | 1218.9 |
| 8 | touch_bar_body_atr | 1174.2 |
| 9 | vel_ratio_5_20 | 1021.1 |
| 10 | pullback_linearity_1s | 990.4 |

### Confusion Matrix (threshold=0.5)
```
Predicted:    0        1
Actual 0:   7,764   2,417
Actual 1:   1,970   1,159
```

---

## Model 2: 1.0 ATR Winner Predictor

### Performance Metrics
| Metric | Train | Test |
|--------|-------|------|
| ROC-AUC | 0.6137 | 0.5432 |
| Accuracy | 0.5767 | 0.5279 |

### Precision/Recall by Threshold
| Threshold | Precision | Recall | F1 | N Predicted |
|-----------|-----------|--------|-----|-------------|
| 0.3 | 0.489 | 0.999 | 0.656 | 13,281 |
| 0.4 | 0.492 | 0.985 | 0.656 | 12,999 |
| 0.5 | 0.519 | 0.452 | 0.483 | 5,664 |
| 0.6 | 1.000 | 0.000 | 0.000 | 1 |
| 0.7 | 0.000 | 0.000 | 0.000 | 0 |
| 0.8 | 0.000 | 0.000 | 0.000 | 0 |

### Top 10 Features
| Rank | Feature | Importance |
|------|---------|------------|
| 1 | touch_overshoot_atr | 1704.7 |
| 2 | touch_precision | 1283.1 |
| 3 | touch_bar_size_atr | 451.3 |
| 4 | touch_bar_upper_wick | 299.6 |
| 5 | max_vel_30s | 294.8 |
| 6 | vol_price_corr_10s | 241.3 |
| 7 | rvol_1s | 234.7 |
| 8 | touch_bar_lower_wick | 229.1 |
| 9 | vel_ratio_5_20 | 202.5 |
| 10 | touch_bar_body_ratio | 190.1 |

### Confusion Matrix (threshold=0.5)
```
Predicted:    0        1
Actual 0:   4,089   2,727
Actual 1:   3,557   2,937
```

---

## Model 3: 1.5 ATR Winner Predictor

### Performance Metrics
| Metric | Train | Test |
|--------|-------|------|
| ROC-AUC | 0.8333 | 0.5389 |
| Accuracy | 0.6630 | 0.6046 |

### Precision/Recall by Threshold
| Threshold | Precision | Recall | F1 | N Predicted |
|-----------|-----------|--------|-----|-------------|
| 0.3 | 0.398 | 0.955 | 0.562 | 12,554 |
| 0.4 | 0.424 | 0.475 | 0.448 | 5,852 |
| 0.5 | 0.462 | 0.038 | 0.070 | 431 |
| 0.6 | 0.588 | 0.002 | 0.004 | 17 |
| 0.7 | 1.000 | 0.000 | 0.001 | 2 |
| 0.8 | 0.000 | 0.000 | 0.000 | 0 |

### Top 10 Features
| Rank | Feature | Importance |
|------|---------|------------|
| 1 | touch_overshoot_atr | 2565.4 |
| 2 | touch_bar_size_atr | 1865.0 |
| 3 | pullback_linearity_1s | 1788.8 |
| 4 | atr_ratio_5_20 | 1730.0 |
| 5 | touch_precision | 1724.4 |
| 6 | vol_price_corr_10s | 1642.9 |
| 7 | rvol_1s | 1558.3 |
| 8 | up_vol_ratio_10s | 1545.8 |
| 9 | rvol_5s | 1531.7 |
| 10 | atr_1m | 1507.7 |

### Confusion Matrix (threshold=0.5)
```
Predicted:    0        1
Actual 0:   7,848     232
Actual 1:   5,031     199
```
