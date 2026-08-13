# Long Strict Retrain — Deployment Decision Audit

## Executive summary

1. **Economically meaningful improvement:** Not established. This audit measures transition prediction, not PnL; the frozen global gains are modest (AUC +0.0050, AP +0.0097, Brier -0.00115).
2. **Intended operating region:** At top 5%, Top25 precision is 0.540 versus 0.558 for Top103, with 31.9 versus 31.9 signals/day. The difference is not large enough to establish economic value without an execution study.
3. **Different opportunities:** At top 5%, Jaccard similarity is 0.465; 2986 rows are Top25-only and 2985 are Top103-only. Top103 materially reorders candidates, but this is not proof the differences are trade-profitable.
4. **Year stability:** The 2024 comparison is in-sample and cannot validate stability. Top103 AUC is 0.720 vs 0.695 in-sample and remains ahead on frozen 2025 (0.655 vs 0.650); independent year stability is therefore not established.
5. **Additional-feature value:** The top 20 features account for 72.8% of total mean absolute SHAP. The 78 features absent from Top25 carry 74.0% of native gain, 59.9% of split count, and 69.6% of mean-absolute SHAP. Their attribution is material, though descriptive rather than causal.
6. **Complexity justified:** No. Top103 requires 4.12x model columns and 3.40x canonical calculations for modest predictive gains, increasing parity, drift, debugging, and audit surface.
7. **Deployment:** **Deploy Top103**, with Top25 retained as the parsimonious fallback.

## Frozen statistical winner

`LONG_STRICT_TOP103_SELECTED`

## Deployment recommendation

**Deploy Top103**

The parsimony override is not supported because at least one frozen criterion failed. Top103 remains the deployment recommendation; the manifest records each criterion so the decision is reproducible. 2025 calibration ECE is 0.0180 for Top25 versus 0.0134 for Top103. However, Top103 MCE is 0.9172 versus 0.0503: a severe but sample-sparse extreme-bin failure caused by five scores at or above 0.9 with zero observed flips. This tail warning does not alter the frozen ECE-based gate, but it requires monitoring before deployment.

## Important limitation

“Signals” here are model-selected bearish-regime checkpoints whose label is a bullish flip within 300 seconds. They are not executed trades. Precision/flip-rate improvements must not be described as profitability.
