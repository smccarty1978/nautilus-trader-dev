# Reproduce — Freeze Reduced Flip Model Artifacts

From the repository root. Total runtime ≈ 2 min. No NautilusTrader, no MBP-1, no
network, no training data rebuild.

## Prerequisites

Read-only inputs that must exist:

```
studies/runtime_constrained_f3_feature_reduction/artifacts/models/F3_top25_gbt_v1/
studies/runtime_constrained_f3_feature_reduction/artifacts/models/F3_top100_gbt_v1/
studies/nt_reduced_f3_top25_population_parity_smoke/config/{model_binding,frozen_thresholds}.json
studies/short_rth_pure_flip_prediction_enriched/_work/prepared_{2021..2026}.parquet
studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_{2021..2026}.parquet
studies/long_rth_pure_flip_top50_top25_training/_work/pred_{TOP25,TOP50,TOP100}_{logreg,gbt}_{2025,2026}.parquet
studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py   (fit_logistic / fit_gbt)
```

Versions this freeze was produced under (recorded in every `manifest.json`):
Python 3.13.7 · scikit-learn 1.7.2 · numpy 2.3.3 · pandas 2.3.3 · joblib 1.5.2.
**scikit-learn 1.7.2 matters** — the copied short-side artifacts were pickled by
it, and reconstruction determinism is only guaranteed on the same version.

## 1. Freeze all models + run parity

```bash
python studies/freeze_reduced_flip_model_artifacts/implementation/run_freeze.py
```

For each model: writes `model.joblib` + `feature_order.csv`, **reloads the
artifact from disk**, scores train/2025/2026, runs every parity check, writes the
logreg coefficient package, attempts ONNX, and writes
`threshold_manifest.json` + `manifest.json`.

Exits non-zero with `MODEL_FREEZE_BLOCKED_PARITY_FAILED` if any joblib parity
check fails, and with `MODEL_FREEZE_BLOCKED_MISSING_ARTIFACTS` if a reference
prediction file is absent.

Expected: **21/21 parity checks PASS**, with all three reconstructed long models
at `max_abs_diff = 0.0` exactly. Writes `results/artifact_inventory.csv`,
`parity_checks.csv`, `onnx_export_report.csv`, `coefficient_inventory.csv`,
`freeze_manifest.json`.

## 2. Build the registry + decision

```bash
python studies/freeze_reduced_flip_model_artifacts/implementation/build_registry.py
```

Recomputes every headline metric **from the frozen `score_reference_*.parquet`
files themselves**, so the registry describes the artifacts rather than
restating source-study claims. Writes `MODEL_REGISTRY.md`,
`results/model_registry.json`, `results/final_decision.json`.

Expected tail: `DECISION: MODEL_FREEZE_COMPLETE_WITH_PROVISIONAL_SHORT`

## 3. Model cards

```bash
python studies/freeze_reduced_flip_model_artifacts/implementation/write_model_cards.py
```

## 4. Audit

```
Agent: lookahead-auditor -> studies/freeze_reduced_flip_model_artifacts/audit/audit.md
```

Acceptance requires **0 CRITICAL**.

## Verifying a frozen model yourself

```python
import joblib, pandas as pd, numpy as np
mid  = "long_bullish_flip_top25"
base = f"studies/freeze_reduced_flip_model_artifacts/artifacts/{mid}"
m     = joblib.load(f"{base}/model.joblib")
order = pd.read_csv(f"{base}/feature_order.csv")["feature_name"].tolist()
ref   = pd.read_parquet(f"{base}/score_reference_2025.parquet")
src   = pd.read_parquet("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2025.parquet")
assert np.abs(m.predict_proba(src[order])[:, 1] - ref["score"].to_numpy()).max() <= 1e-12
```

### Scoring a logreg model without unpickling

```python
c = pd.read_csv(f"{base}/coefficients.csv")
b = json.load(open(f"{base}/intercept.json"))["intercept"]
fill = {r.feature_name: float(str(r.null_policy).split("=")[1]) for r in c.itertuples()}
X = src[c["feature_name"]].astype(float).fillna(pd.Series(fill))
z = b + ((X.to_numpy() - c["mean_train"].to_numpy()) / c["std_train"].to_numpy()) @ c["coefficient"].to_numpy()
p = 1 / (1 + np.exp(-z))     # matches predict_proba()[:,1] to ~1e-13
```

## Determinism

`random_state=42` throughout. Reconstruction reproduced the stored predictions
**bit-identically**, so a rerun on the same sklearn version regenerates
byte-identical `model.joblib` files.

> **Trusted-local only.** `joblib`/`pickle` executes code on load. Load these
> artifacts only from this repository.

## What this does NOT do

No retraining except the parity-proven reconstruction of long models that were
never persisted · no feature/threshold/target changes · no NautilusTrader · no
trade economics · no use of 2026 for any selection.
