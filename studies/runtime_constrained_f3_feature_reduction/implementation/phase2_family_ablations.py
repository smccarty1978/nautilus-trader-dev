"""Phase 2 -- baseline family ablations A-G. Frozen hyperparameters (via
`fit_gbt`), GBT only, descriptive metrics only (no economic backtest).
A (695) reuses the already-verified+promoted F3_695_baseline rather than
re-fitting an identical model under a new id.
"""
from __future__ import annotations

import json
import time

from common import RESULTS, load_train_dev, train_and_persist, ARTIFACTS

MODEL_IDS = {
    "A_full_695": "F3_695_baseline",  # already trained + promoted in Phase 0 -- reused, not refit
    "B_live546": "F3_live546_gbt_v1",
    "C_f0_only_149": "F3_ablation_C_f0only_gbt_v1",
    "D_ohlcv_est_delta_214": "F3_ablation_D_ohlcv_gbt_v1",
    "E_price_level_context_332": "F3_ablation_E_pricelvl_gbt_v1",
    "F_f0_plus_ohlcv": "F3_ablation_F_f0_ohlcv_gbt_v1",
    "G_f0_plus_price_level": "F3_ablation_G_f0_pricelvl_gbt_v1",
}


def main() -> None:
    family_sets = json.loads((RESULTS / "family_ablation_feature_sets.json").read_text())["feature_sets"]
    t0 = time.time()

    rows = []
    # A: reuse existing baseline manifest/metrics, no retrain.
    a_manifest = json.loads((ARTIFACTS / "F3_695_baseline" / "manifest.json").read_text())
    a_metrics = json.loads((ARTIFACTS / "F3_695_baseline" / "metrics_2025.json").read_text())
    rows.append({"family": "A_full_695", "model_id": "F3_695_baseline", "n_features": 695,
                 "dev_auc": a_metrics["dev_2025"]["auc"], "dev_ap": a_metrics["dev_2025"]["average_precision"],
                 "dev_logloss": a_metrics["dev_2025"]["logloss"], "dev_brier": a_metrics["dev_2025"]["brier"],
                 "reused_existing_artifact": True})

    for family, model_id in MODEL_IDS.items():
        if family == "A_full_695":
            continue
        cols = family_sets[family]
        manifest = train_and_persist(model_id, cols, source_note=f"Phase 2 family ablation {family}",
                                     status="candidate")
        metrics = json.loads((ARTIFACTS / model_id / "metrics_2025.json").read_text())
        rows.append({"family": family, "model_id": model_id, "n_features": len(cols),
                     "dev_auc": metrics["dev_2025"]["auc"], "dev_ap": metrics["dev_2025"]["average_precision"],
                     "dev_logloss": metrics["dev_2025"]["logloss"], "dev_brier": metrics["dev_2025"]["brier"],
                     "reused_existing_artifact": False})

    import pandas as pd
    pd.DataFrame(rows).to_csv(RESULTS / "family_ablation_summary.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"Phase 2 done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
