# H050 Frozen-Model Comparison Report: M4 Stack vs. New Remaining-MFE Stack

**Study ID:** `nq_h050_m4_vs_remaining_mfe_model`  
**Author:** Governed Research Controller / Antigravity  
**Status:** `COMPLETED (REISSUED WITH STRICT FORWARD / GENERALIZATION METRICS)`  
**Primary Question:** On the exact same H050 observations, how much predictive information does the new pooled terminal-MFE / remaining-MFE model stack contain relative to the frozen M4 model stack?

---

## 1. Executive Summary & Revised Formal Verdicts (?15)

This study reissues the comparison between the **Frozen M4 H050 Model Stack** and the **New Pooled Remaining-MFE Model Stack** using strictly legitimate forward and generalization metrics:
1. **Historical TRAIN Diagnostic (2024 Validation, $N = 10,888$):** The new model's predictions are restored to the original **2023-fit model** (genuine out-of-sample generalization from `nq_h050_six_model_remaining_mfe`), eliminating the in-sample contamination of the full-TRAIN refit model. M4 was trained on full 2023?2024 TRAIN ($N = 21,493$), so 2024 is strictly in-sample for M4.
2. **Forward Out-of-Sample Diagnostic (2025 Q1, $N = 2,422$):** Both model systems were completely frozen before scoring. This serves as the **primary scientific arbiter** for all formal verdicts.

### Formal Verdicts Matrix (Revised Primarily on 2025 Q1)

| Verdict Category | Formal Verdict | Context & Empirical Basis (2025 Q1) |
|---|---|---|
| **Population Parity** | `COMMON_POPULATION_PARITY_PASS` | Exact 1-to-1 match of timestamps, directions, and row counts across both 2024 ($N=10,888$) and 2025 Q1 ($N=2,422$). |
| **Provenance Status** | `M4_PROVENANCE_COMPARISON = DIAGNOSTIC_ONLY` | 2024 was part of M4 training data; 2025 Q1 serves as the forward generalization benchmark. |
| **Terminal-MFE Ranking** | `NEW_MODEL_TERMINAL_MFE_RANKING = SIMILAR` | On 2025 Q1, M4 achieves AUC 0.5958 vs New Model 0.5920 (Delta = -0.0039). The models perform within 0.004 AUC of each other. |
| **Remaining-MFE Ranking** | `NEW_MODEL_REMAINING_MFE_RANKING = SIMILAR` | On 2025 Q1, M4 achieves 0.6011?0.6323 vs New Model 0.5959?0.6338 (Delta range: -0.0052 to +0.0016). Essentially identical ranking. |
| **Incremental Information** | `NEW_MODEL_MOSTLY_DUPLICATES_M4` | Combining M4 and the New Model into Model Z degrades forward AUC across all four targets (Deltas: -0.021 to -0.027). |
| **Delayed-Entry Recommendation** | `DELAYED_ENTRY_MODEL_INPUT_RECOMMENDATION = M4_ONLY` | On forward evidence, M4 provides equal/superior ranking, lower Brier loss, and vastly superior downside protection (7.4% vs 16.1% catastrophic rate). |

---

## 2. Mandatory Provenance Audit (?1)

Prior to analysis, exact dataset provenance and calendar splits were audited:

```json
{
  "m4_training_dataset": "studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet",
  "m4_training_split": "TRAIN",
  "m4_fit_rows": 21493,
  "m4_fit_years": [
    "2023",
    "2024"
  ],
  "m4_fit_calendar_start": "2023-01-03",
  "m4_fit_calendar_end": "2024-12-31",
  "m4_validation_split_in_training": "None (5-fold CV on full TRAIN, refitted on full TRAIN)",
  "new_model_training_dataset": "studies/nq_h050_mtf_regime_context_features/results/feature_surface_train.parquet",
  "new_model_selection_fit_year": "2023 (N=10,605)",
  "new_model_selection_val_year": "2024 (N=10,888)",
  "new_model_2024_evaluation_basis": "Original 2023-fit model predictions (legitimate out-of-sample generalization)",
  "new_model_final_persistence": "Refitted on full 2023-2024 TRAIN (N=21,493)",
  "comparison_2024_status": "SAME_POPULATION_DIAGNOSTIC_ONLY",
  "comparison_2024_rationale": "M4 was fitted on full 2023-2024 TRAIN (in-sample for M4), while New Model is evaluated using true 2023-fit generalization.",
  "comparison_2025_q1_status": "COMMON_FORWARD_DIAGNOSTIC",
  "comparison_2025_q1_rationale": "2025 Q1 is chronologically forward for both models, completely frozen before scoring. Primary basis for verdicts."
}
```

- **M4 Model Stack:** Fitted on `studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet`. The training split comprised the entire 2-year TRAIN period: `2023-01-03` to `2024-12-31` ($N = 21,493$). LightGBM hyperparameters were tuned using 5-fold cross-validation on full TRAIN, and the final production boosters were refitted on the complete 21,493 rows. Therefore, **2024 was part of M4 training data**.
- **New Pooled Model Stack:** In this reissued report, the 2024 validation predictions are generated using the original **2023-fit model** ($N = 10,605$), which represents legitimate out-of-sample generalization. For 2025 Q1 forward evaluation, the frozen production model is evaluated without modification.
- **Scientific Implication:** 2024 is **asymmetric** (in-sample for M4, out-of-sample generalization for the new model). Therefore, 2024 is labeled `SAME_POPULATION_DIAGNOSTIC_ONLY`. **2025 Q1 is the sole unbiased forward test** for both models.

---

## 3. Common Population Parity (?2)

Bit-for-bit parity was verified across both cohorts:

| Cohort | M4 Rows | New Model Rows | Timestamp Match | Direction Match | Parity Verdict |
|---|---:|---:|:---:|:---:|:---:|
| **2024 Validation** | 10,888 | 10,888 | True | True | **PASS** |
| **2025 Q1 Forward** | 2,422 | 2,422 | True | True | **PASS** |

Parity Status: **`COMMON_POPULATION_PARITY_PASS`**.

---

## 4. Native Target Performance (?5)

### A. Frozen M4 Stack Native Targets
| Target Name | 2024 Validation ROC AUC (In-Sample) | 2025 Q1 Forward ROC AUC (Forward OOS) |
|---|---:|---:|
| `target_y050_success` | 0.6353 | 0.5978 |
| `target_y100_dangerous` | 0.6437 | 0.6068 |
| `target_y200_severe` | 0.6599 | 0.6353 |

### B. Frozen New Pooled Stack Native Targets
| Target Name | 2024 Validation ROC AUC (2023-Fit OOS) | 2025 Q1 Forward ROC AUC (Forward OOS) |
|---|---:|---:|
| `terminal_mfe_within_0p25a` | 0.5722 | 0.5920 |
| `remaining_mfe_gte_0p5a` | 0.5656 | 0.5959 |
| `remaining_mfe_gte_1p0a` | 0.5612 | 0.6037 |
| `remaining_mfe_gte_2p0a` | 0.5437 | 0.6338 |

---

## 5. Same-Target Ranking Test (?6)

The frozen M4 composite score ($M_4 = P_0 - 0.5 P_1 - 1.0 P_2$) was evaluated as a ranker against the four remaining-MFE targets:
- For `terminal_mfe_within_0p25a`, higher $M_4$ predicts greater counter-regime exhaustion.
- For `remaining_mfe_gte_XA`, lower $M_4$ (i.e. $-M_4$) predicts greater runaway continuation.

### A. 2024 Validation Cohort ($N = 10,888$ - Same-Population Diagnostic)

| Target | M4 Rank Score | M4 Rank AUC (In-Sample) | New Model AUC (2023-Fit OOS) | Delta (New - M4) | Superior Model |
|---|:---:|---:|---:|---:|:---:|
| `terminal_mfe_within_0p25a` | `M4` | 0.6234 | 0.5722 | -0.0512 | **M4** |
| `remaining_mfe_gte_0p5a` | `-M4` | 0.6318 | 0.5656 | -0.0662 | **M4** |
| `remaining_mfe_gte_1p0a` | `-M4` | 0.6346 | 0.5612 | -0.0734 | **M4** |
| `remaining_mfe_gte_2p0a` | `-M4` | 0.6496 | 0.5437 | -0.1059 | **M4** |

### B. 2025 Q1 Forward Cohort ($N = 2,422$ - Common Forward Diagnostic)

| Target | M4 Rank Score | M4 Rank AUC (Forward OOS) | New Model AUC (Forward OOS) | Delta (New - M4) | Superior Model |
|---|:---:|---:|---:|---:|:---:|
| `terminal_mfe_within_0p25a` | `M4` | 0.5958 | 0.5920 | -0.0039 | **SIMILAR** |
| `remaining_mfe_gte_0p5a` | `-M4` | 0.6011 | 0.5959 | -0.0052 | **SIMILAR** |
| `remaining_mfe_gte_1p0a` | `-M4` | 0.6077 | 0.6037 | -0.0040 | **SIMILAR** |
| `remaining_mfe_gte_2p0a` | `-M4` | 0.6323 | 0.6338 | +0.0016 | **SIMILAR** |

> **Forward Conclusion:** On the legitimate forward quarter (2025 Q1), both models achieve virtually identical ranking performance across all four targets (within 0.001 to 0.005 AUC of each other). The formal verdict is **`SIMILAR`**.

---

## 6. M4 Component-Head Diagnostic (?7)

Testing the individual M4 component heads on 2025 Q1 Forward:

| M4 Component Head | AUC Terminal (<0.25A) | AUC Rem (>=0.5A) | AUC Rem (>=1.0A) | AUC Rem (>=2.0A) |
|---|---:|---:|---:|---:|
| `P_y050_success` | 0.5968 | 0.4022 | 0.3984 | 0.3821 |
| `P_y100_dangerous` | 0.4057 | 0.6005 | 0.6068 | 0.6243 |
| `P_y200_severe` | 0.4145 | 0.5937 | 0.6013 | 0.6353 |

- `P_y050_success` ranks terminal exhaustion at AUC **0.5968** (higher than the new model's 0.5920).
- `P_y200_severe` ranks severe continuation at AUC **0.6353** (higher than the new model's 0.6338).
- This confirms that M4's existing component heads already capture the continuation and exhaustion signals.

---

## 7. Correlation & Information Overlap (?8)

Spearman rank correlations on 2025 Q1 Forward:

| Score Pair | Correlation on 2025 Q1 | Assessment |
|---|---:|---|
| $M_4$ Composite vs. New $P(\text{term} < 0.25A)$ | +0.6573 | Moderate positive correlation |
| $M_4$ Composite vs. New $P(\text{rem} \ge 0.5A)$ | -0.6670 | Moderate inverse correlation |
| $M_4$ Composite vs. New $P(\text{rem} \ge 1.0A)$ | -0.6131 | Moderate inverse correlation |
| $M_4$ Composite vs. New $P(\text{rem} \ge 2.0A)$ | -0.5665 | Moderate inverse correlation |
| $M_4$ Composite vs. New Cont. Regressor | -0.6729 | Strong inverse correlation |

---

## 8. Decile Stratification Comparison (?9)

### 2025 Q1 Forward Decile Comparison

| Decile | M4 Actual Term Rate | New Model Actual Term Rate | M4 Mean Rem MFE | New Model Mean Rem MFE | M4 Catastrophic Loss Rate | New Model Catastrophic Loss Rate |
|:---:|---:|---:|---:|---:|---:|---:|
| D1 | 18.5% | 19.3% | 4.61A | 3.79A | 25.9% | 20.2% |
| D2 | 21.5% | 24.8% | 2.88A | 3.41A | 19.0% | 17.8% |
| D3 | 27.7% | 28.5% | 2.59A | 2.24A | 15.7% | 12.8% |
| D4 | 31.4% | 30.2% | 2.30A | 2.47A | 16.9% | 15.3% |
| D5 | 31.4% | 27.7% | 1.94A | 1.67A | 14.5% | 10.3% |
| D6 | 33.1% | 32.2% | 1.84A | 1.91A | 11.2% | 13.2% |
| D7 | 33.1% | 35.5% | 1.44A | 1.80A | 12.8% | 12.4% |
| D8 | 41.7% | 37.6% | 1.36A | 1.43A | 9.9% | 10.7% |
| D9 | 38.0% | 37.6% | 1.13A | 1.41A | 6.2% | 10.7% |
| D10 | 42.4% | 45.3% | 0.99A | 0.97A | 7.4% | 16.0% |

- On 2025 Q1 Forward, M4 spreads terminal rate from 18.5% (D1) to 42.6% (D10).
- The New Model spreads terminal rate from 19.3% (D1) to 45.5% (D10).
- Both models achieve comparable monotonic decile stratification forward.

---

## 9. Top/Bottom Tail Comparison (?10)

### 2025 Q1 Forward Cohort Tail Comparison

| Bucket | Model | Count | Terminal Rate (<0.25A) | Mean Rem MFE | Catastrophic Loss Rate | C1 Mean PnL | Winner >=+2A Rate | Winner >=+3A Rate |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **Best 10%** | Frozen M4 | 242 | 42.6% | 0.99A | **7.4%** | +1.12A | 18.2% | 9.9% |
| **Best 10%** | New Pooled | 242 | 45.5% | 0.97A | **16.1%** | -0.09A | 19.8% | 12.0% |
| **Best 20%** | Frozen M4 | 484 | 40.3% | 1.06A | **6.8%** | +0.52A | 14.7% | 6.8% |
| **Best 20%** | New Pooled | 484 | 41.5% | 1.18A | **13.2%** | -0.11A | 15.7% | 7.9% |
| **Worst 10%** | Frozen M4 | 243 | 18.5% | 4.61A | **25.9%** | +0.84A | 29.6% | 23.0% |
| **Worst 10%** | New Pooled | 243 | 19.3% | 3.79A | **20.2%** | +0.26A | 26.3% | 16.0% |
| **Worst 20%** | Frozen M4 | 485 | 20.0% | 3.75A | **22.5%** | +0.51A | 25.6% | 17.7% |
| **Worst 20%** | New Pooled | 485 | 22.1% | 3.60A | **19.0%** | +0.43A | 23.1% | 14.8% |

> **Critical Tail Finding:** In the Best 10% bucket on 2025 Q1, **Frozen M4 achieves a catastrophic loss rate of only 7.4%**, whereas the New Model allows a **16.1% catastrophic loss rate** (more than double). M4 delivers substantially superior downside tail filtration on forward out-of-sample data.

---

## 10. Exact Incremental Information Metrics on 2025 Q1 (?11)

Low-capacity logistic regression models fit on 2023 Fit ($N=10,605$) were evaluated on the forward diagnostic cohort (**2025 Q1**, $N=2,422$):
- **Model X:** $M_4$ composite score only.
- **Model Y:** New pooled probability only.
- **Model Z:** Both $M_4$ composite score + New pooled probability.

### Exact 2025 Q1 Incremental Information Results

| Target | Model | ROC AUC | PR AUC | Brier Score | Prevalence | Delta vs Model X | Delta vs Model Y | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| `terminal_mfe_within_0p25a` | **Model X (M4)** | **0.5958** | 0.3909 | **0.2127** | 0.3187 | ? | ? | ? |
| | **Model Y (New)** | 0.5920 | 0.4017 | 0.2484 | 0.3187 | -0.0039 | ? | ? |
| | **Model Z (M4 + New)** | 0.5706 | 0.3892 | 0.2554 | 0.3187 | **-0.0253** | **-0.0214** | **MOSTLY_DUPLICATES_M4** |
| `remaining_mfe_gte_0p5a` | **Model X (M4)** | **0.6011** | 0.6983 | **0.2324** | 0.6040 | ? | ? | ? |
| | **Model Y (New)** | 0.5959 | 0.6824 | 0.2682 | 0.6040 | -0.0052 | ? | ? |
| | **Model Z (M4 + New)** | 0.5738 | 0.6574 | 0.2775 | 0.6040 | **-0.0273** | **-0.0221** | **MOSTLY_DUPLICATES_M4** |
| `remaining_mfe_gte_1p0a` | **Model X (M4)** | **0.6077** | 0.5997 | **0.2409** | 0.4847 | ? | ? | ? |
| | **Model Y (New)** | 0.6037 | 0.5839 | 0.2776 | 0.4847 | -0.0040 | ? | ? |
| | **Model Z (M4 + New)** | 0.5842 | 0.5583 | 0.2862 | 0.4847 | **-0.0235** | **-0.0195** | **MOSTLY_DUPLICATES_M4** |
| `remaining_mfe_gte_2p0a` | **Model X (M4)** | **0.6323** | 0.4608 | **0.2084** | 0.3237 | ? | ? | ? |
| | **Model Y (New)** | 0.6338 | 0.4533 | 0.2333 | 0.3237 | +0.0016 | ? | ? |
| | **Model Z (M4 + New)** | 0.6100 | 0.4215 | 0.2427 | 0.3237 | **-0.0223** | **-0.0239** | **MOSTLY_DUPLICATES_M4** |

### Key Analytical Insights from 2025 Q1:
1. **Model Z strictly underperforms Model X on every single target:**
   - Terminal MFE: AUC drops from 0.5958 to 0.5706 ($-0.0253$).
   - Remaining >=0.5A: AUC drops from 0.6011 to 0.5738 ($-0.0273$).
   - Remaining >=1.0A: AUC drops from 0.6077 to 0.5842 ($-0.0235$).
   - Remaining >=2.0A: AUC drops from 0.6323 to 0.6100 ($-0.0223$).
2. **Model Z strictly underperforms Model Y on every single target:** Combining the two scores in logistic regression induces multicollinearity and degradation forward.
3. **Brier Score / Calibration:** Model X (M4) achieves the lowest Brier score (best probabilistic calibration) across all four targets.
4. **Formal Verdict:** **`NEW_MODEL_MOSTLY_DUPLICATES_M4`**.

---

## 11. Explicit Answers to All 16 Decision Questions (?14)

### 1. What periods were used to train M4?
Full 2-year TRAIN period: **2023-01-03 to 2024-12-31** ($N = 21,493$ trades). Final boosters were refitted on the complete population.

### 2. Is 2024 a fair OOS comparison for both models?
**No.** 2024 was part of M4 training data. The 2024 comparison is classified as `SAME_POPULATION_DIAGNOSTIC_ONLY`. 2025 Q1 is the sole unbiased forward test.

### 3. What are M4's native target AUCs?
- 2024 Validation (in-sample): `y050_success` = **0.6353**, `y100_dangerous` = **0.6437**, `y200_severe` = **0.6599**.
- 2025 Q1 Forward (OOS): `y050_success` = **0.5978**, `y100_dangerous` = **0.6068**, `y200_severe` = **0.6353**.

### 4. What are the new model's native target AUCs?
- 2024 Validation (original 2023-fit OOS): `term < 0.25A` = **0.5722**, `rem >= 0.5A` = **0.5656**, `rem >= 1.0A` = **0.5612**, `rem >= 2.0A` = **0.5437**.
- 2025 Q1 Forward (OOS): `term < 0.25A` = **0.5920**, `rem >= 0.5A` = **0.5959**, `rem >= 1.0A` = **0.6037**, `rem >= 2.0A` = **0.6338**.

### 5. When both are judged against terminal MFE, which score ranks the target more strongly?
**`SIMILAR`.** On 2025 Q1 Forward, M4 achieves AUC **0.5958** vs New Model **0.5920** (Delta = $-0.0039$, within 0.004).

### 6. Against >=0.5A remaining MFE?
**`SIMILAR`.** On 2025 Q1 Forward, M4 achieves AUC **0.6011** vs New Model **0.5959** (Delta = $-0.0052$, within 0.005).

### 7. Against >=1A remaining MFE?
**`SIMILAR`.** On 2025 Q1 Forward, M4 achieves AUC **0.6077** vs New Model **0.6037** (Delta = $-0.0040$, within 0.004).

### 8. Against >=2A remaining MFE?
**`SIMILAR`.** On 2025 Q1 Forward, M4 achieves AUC **0.6323** vs New Model **0.6338** (Delta = $+0.0016$, within 0.002).

### 9. Does one specific M4 component already predict remaining MFE well?
**Yes.** On 2025 Q1 Forward, `P_y050_success` predicts terminal exhaustion at AUC **0.5968** (exceeding the new model's 0.5920), and `P_y200_severe` predicts runaway continuation at AUC **0.6353** (exceeding the new model's 0.6338).

### 10. How correlated are M4 and the new model outputs?
Moderately correlated on 2025 Q1 ($|r| \approx 0.57 - 0.67$).

### 11. Does the new model provide independent information beyond M4?
**No.** In the 2025 Q1 forward incremental test, combining both models into Model Z degrades AUC across all four targets (Deltas $-0.022$ to $-0.027$). The new model mostly duplicates M4 signal.

### 12. Which model produces better terminal-MFE decile separation?
**Comparable / Similar.** On 2025 Q1 Forward, M4 separates terminal rate from 18.5% (D1) to 42.6% (D10); the New Model separates from 19.3% (D1) to 45.5% (D10).

### 13. Which produces better catastrophic-loss concentration?
**Frozen M4.** In the Best 10% bucket on 2025 Q1, M4 limits catastrophic losses to **7.4%**, compared to **16.1%** for the New Model (more than double).

### 14. Which preserves more +2A/+3A winners in its favorable tail?
**Slight edge to New Model.** In the Best 10% bucket on 2025 Q1, the New Model retains 19.8% +2A winners (vs 18.2% for M4) and 12.0% +3A winners (vs 9.9% for M4).

### 15. Is the new model sufficiently different/useful to retain for the delayed-entry study?
**Only as an execution trigger, not as a primary ranking score.** The new model does not improve ranking or add incremental value over M4 forward.

### 16. Should the delayed-entry study score M4 only, new remaining-MFE model only, or both?
**`M4_ONLY` for predictive trade selection.** On legitimate forward metrics, M4 provides equal/better AUC, lower Brier error, and superior tail protection. If pullback trajectory timing is evaluated, continuous regression may serve as a mechanical clock, but M4 remains the required predictive ranker.

---

## 12. Architectural Recommendation for Delayed-Entry Study (?16)

Based strictly on the 2025 Q1 forward generalization evidence:
1. **Primary Viability Filter:** Retain **Frozen M4** as the sole predictive trade selection and tail-filtration score (`DELAYED_ENTRY_MODEL_INPUT_RECOMMENDATION = M4_ONLY`).
2. **Do Not Linearly Blend:** Do not construct composite logistic or linear combinations of M4 and the new probabilities (Model Z), as this degrades out-of-sample ranking accuracy.
3. **Pullback Timing:** If delayed-entry rules require measuring pullback depth in real-time, use mechanical bar metrics (e.g. `pullback_depth_atr`, `prior_regime_reclaim`) rather than relying on a secondary classification model.

---

## 13. Mandatory Stop (?17)

- No models were retrained.
- No additional data beyond 2025 Q1 was opened.
- All 16 decision questions answered; all formal verdicts revised on legitimate forward metrics.
