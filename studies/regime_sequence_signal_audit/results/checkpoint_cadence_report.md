# Phase 12: Checkpoint Cadence Audit Report

## 1. Event Rate Comparison
* **Train (30s step)**: 30.5161%
* **Validation (5s step)**: 27.5767%
* **Test (5s step)**: 27.2058%

*Event rates match closely, suggesting the sampling step does not bias the class balance.*

## 2. Score Distribution Comparison
* **train_30s**: Mean=0.3052, Std=0.2415, Median=0.2373, 90th Pct=0.6594
* **validation_5s**: Mean=0.2835, Std=0.2199, Median=0.2210, 90th Pct=0.6183
* **test_5s**: Mean=0.2758, Std=0.2211, Median=0.2070, 90th Pct=0.6174

## 3. Generalization Experiment: 5s vs 30s Training Cadence (Evaluated on Test 5s)
### Model: val_5s_trained
* **ROC AUC**: 0.8196
* **PR AUC**: 0.6361
* **Brier Score**: 0.1450
* **Calibration Slope**: 1.0344
* **Calibration Intercept**: -0.0083

### Model: val_30s_trained
* **ROC AUC**: 0.8156
* **PR AUC**: 0.6231
* **Brier Score**: 0.1468
* **Calibration Slope**: 1.0579
* **Calibration Intercept**: -0.0127


## Conclusion
* **Is there a calibration mismatch due to 30s step training?**
  Yes, training on 30s steps vs 5s steps changes the calibration slope slightly, but the ranking (AUC) remains highly robust.
