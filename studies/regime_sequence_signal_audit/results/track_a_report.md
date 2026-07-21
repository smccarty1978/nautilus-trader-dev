# Track A: Payoff-Aligned Context Model Report

## Model Comparison Statistics (Test Set 2026)
| Target Variable | Model Specification | Metric | Val Value | Test Value |
|---|---|---|---|---|
| pnl_base | Model 1 (Event Age only) | Spearman Corr | 0.0699 | 0.0605 |
| pnl_base | Model 2 (Existing score only) | Spearman Corr | -0.0083 | 0.0114 |
| pnl_base | Model 3 (Local+Contextual without score) | Spearman Corr | 0.0083 | -0.0082 |
| pnl_base | Model 4 (Combined model) | Spearman Corr | 0.0246 | 0.0044 |
| target_loss_prob | Model 1 (Event Age only) | ROC AUC | 0.7655 | 0.7199 |
| target_loss_prob | Model 2 (Existing score only) | ROC AUC | 0.5729 | 0.5561 |
| target_loss_prob | Model 3 (Local+Contextual without score) | ROC AUC | 0.8904 | 0.8297 |
| target_loss_prob | Model 4 (Combined model) | ROC AUC | 0.8906 | 0.8298 |
| target_mfe_atr | Model 1 (Event Age only) | Spearman Corr | 0.0092 | -0.0354 |
| target_mfe_atr | Model 2 (Existing score only) | Spearman Corr | 0.0582 | 0.0706 |
| target_mfe_atr | Model 3 (Local+Contextual without score) | Spearman Corr | 0.1088 | 0.1189 |
| target_mfe_atr | Model 4 (Combined model) | Spearman Corr | 0.1096 | 0.1151 |

## Pairwise Ranking Performance
* **Regressor pairwise ranking accuracy on test set**: 47.07%

## Placebo Permutation Analysis
* **Frozen optimal validation skip percentile**: 20%
* **Real test EV lift**: $-2.4903 per opportunity
* **Placebo percentile (multiple-testing corrected)**: 7.80%

## Final Track A Decision:
`USEFUL_ONLY_AS_FEATURE`
