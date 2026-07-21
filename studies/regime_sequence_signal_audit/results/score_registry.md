# score/model registry

| Score/Model Name | Exact Definition | Model Type | Training Target | Feature Set | Training Years | Output Column | Score Direction | Calibration Method | Artifact Path | Policies Consuming the Score | Proposed for Integration |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Ridge Risk** | Ridge regression probability of early flip failure or low progress | Ridge Classifier | `outcome_class` is rotational failure or low progress | 5m/15m/30m/60m median centers and regime sequence features | 2021-2024 | `ridge_log_fail_prob` | High = High risk | None (Raw logits/probabilities) | `studies/regime_sequence_chop_context/results/flip_context_atlas.parquet` | F4, F5, R1-R4 | Yes (as feature) |
| **F4 Threshold** | Fixed probability threshold at 0.15 | Decision rule | `ridge_log_fail_prob > 0.15` | N/A | 2025 (validation) | `filter_F4_keep` | Binary keep/skip | N/A | `studies/regime_sequence_chop_context/results/flip_context_atlas.parquet` | F4 | Yes (as baseline) |
| **F5 Threshold** | Grid-searched optimal probability threshold on Val | Decision rule | `ridge_log_fail_prob > threshold_val` | N/A | 2025 (validation) | `filter_F5_keep` | Binary keep/skip | N/A | `studies/regime_sequence_signal_audit/results/rank_skip_frozen_config.json` | F5 | Yes |
| **W4 Weakness** | GBDT probability of terminal regime weakness | LightGBM Classifier | Regime weakness event (fails to progress before opposite flip) | Combined local, median center, and sequence features | 2021-2024 | `w4_weakness_prob` (or `weakness_prob`) | High = High weakness risk | Platt scaling / isotonic regression on 2025 | `studies/regime_sequence_signal_audit/results/track_b_w4.weights` | B1-B5 exits | Yes |

## Answers to Score Questions:
1. **What is the exact F4 rule?**
   F4 is a binary trade skip filter. It skips/omits any trade if the predicted failure probability from the Ridge model (`ridge_log_fail_prob`) exceeds a hard threshold of `0.15`. That is: if `ridge_log_fail_prob > 0.15`, the trade is skipped (`filter_F4_keep = False`).
   
2. **Is F5 a separate model, a renamed score, or a policy?**
   F5 is a **policy/threshold** applied to the same underlying Ridge context model score (`ridge_log_fail_prob`), but whose probability threshold is selected dynamically via a grid search on the validation set to maximize the trade expected value (EV). It is not a separate model.
   
3. **Which score column was ranked for R1–R5?**
   The score column `ridge_log_fail_prob` was ranked to determine the high-risk percentiles for R1, R2, R3, and R4. R5 did not rank a score; it simply inherited the pre-calculated binary `filter_F4_keep` column.
   
4. **What score produced the reported Ridge risk deciles?**
   The score `ridge_log_fail_prob` was partitioned into deciles to evaluate its ranking and calibration properties.
   
5. **Which score is proposed for unified-policy integration?**
   The `ridge_log_fail_prob` is proposed as the primary feature for entry-filtering policies (Track A), and the `W4` terminal weakness probability is proposed as the primary input for active regime exit execution policies (Track B).
   
6. **Are any names referring to duplicate versions of the same score?**
   Yes. F4, F5, the Ridge risk decile score, and the score ranked for R1-R4 all refer to the exact same underlying column: `ridge_log_fail_prob`.
