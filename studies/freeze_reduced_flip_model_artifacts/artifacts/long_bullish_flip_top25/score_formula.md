# Score formula — `long_bullish_flip_top25`

Features **are standardized**. The full transform chain, in order, is exactly:

1. **Median impute** — missing values replaced per-feature by `null_policy` in
   `coefficients.csv` (the `SimpleImputer(strategy="median")` statistic fitted on
   the 2021–2024 train split).
2. **Standardize** — `x' = (x - mean_train) / std_train`, both columns in
   `coefficients.csv` (`StandardScaler` fitted on the same train split).
3. **Linear + logistic**:

```
z = intercept + Σ_i ( coefficient_i * x'_i )
p = 1 / (1 + exp(-z))
```

`intercept = -1.1242977837958268` (see `intercept.json`).
`p` is the probability of class `1` = flip occurs within 300 s.

## Where the scaler lives

The imputer and scaler are **not** separate files — they are steps inside the
single `model.joblib` `Pipeline`
(`imputer` → `scaler` → `model`). `coefficients.csv` reproduces their fitted
parameters so the model can be audited and re-implemented in NT **without
unpickling anything**.

## Manual reimplementation check

Apply steps 1–3 to any row of `score_reference_2025.parquet` using only
`coefficients.csv` + `intercept.json`; the result matches the stored `score`
column. This is verified programmatically in `parity_checks.csv` as the
`manual_formula` check — it recomputes every row from the CSV alone.

Feature order is **significant** and frozen in `feature_order.csv`.
