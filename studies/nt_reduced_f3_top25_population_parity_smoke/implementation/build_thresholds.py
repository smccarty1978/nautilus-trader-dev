"""Freeze R5/R2.5 thresholds from the COMPLETE full-2025 offline F3_top25_gbt_v1
score population -- never tuned on March. Per SPEC.md Threshold policy."""
from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

import common as C

FEATURE_COLS_EXTRA = ["regime_start_ns", "observation_time", "entry_ts", "entry_px",
                      "atr_at_entry", "entry_direction", "confirm_flip_ns", C.TARGET]


def main() -> None:
    verified = C.verify_frozen_model_inputs()
    feat_list = verified["feature_list"]

    model = joblib.load(C.MODEL_PATH)
    assert list(model.classes_) == [0, 1], f"unexpected classes {model.classes_}"

    dev_hash = C.sha256_file(C.PREPARED_2025_PATH)
    dev = pd.read_parquet(C.PREPARED_2025_PATH, columns=feat_list + FEATURE_COLS_EXTRA)
    assert (dev["entry_direction"] == -1).all(), "expected entry_direction==-1 for every row"

    t0 = time.time()
    scores = model.predict_proba(dev[feat_list])[:, 1]
    dev["score"] = scores

    top5 = float(np.quantile(scores, 0.95))
    top2_5 = float(np.quantile(scores, 0.975))

    binding = {
        "model_id": C.MODEL_ID, "model_path": str(C.MODEL_PATH.relative_to(C.ROOT)),
        "model_sha256": verified["model_sha256"],
        "feature_list_path": str(C.FEATURE_SETS_PATH.relative_to(C.ROOT)),
        "feature_list_sha256": verified["feature_list_sha256"], "feature_count": len(feat_list),
        "score_method": "predict_proba(...)[:, 1]", "positive_class_index": 1,
        "sklearn_version": sklearn.__version__, "numpy_version": np.__version__,
        "threshold_file": "config/frozen_thresholds.json",
        "threshold_file_sha256": None,  # filled after write, self-referential hash not attempted
    }
    (C.CONFIG / "model_binding.json").write_text(json.dumps(binding, indent=2))

    thresholds = {
        "model_id": C.MODEL_ID, "model_sha256": verified["model_sha256"],
        "feature_list_sha256": verified["feature_list_sha256"],
        "source_population": "full-year 2025 prepared_2025.parquet (198,255 rows)",
        "source_population_sha256": dev_hash,
        "threshold_derivation_method": ("np.quantile(scores, 0.95) and np.quantile(scores, 0.975) "
                                        "over the complete 2025 population; never tuned on March"),
        "top_5pct_threshold": top5, "top_2_5pct_threshold": top2_5,
        "source_score_column_sha256": __import__("hashlib").sha256(scores.tobytes()).hexdigest(),
        "n_rows_scored": len(dev),
        "creation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script_sha256": C.sha256_file(Path(__file__).resolve()),
    }
    (C.CONFIG / "frozen_thresholds.json").write_text(json.dumps(thresholds, indent=2))
    dev.to_parquet(C.WORK / "full_2025_scored_for_thresholds.parquet", index=False)
    print(json.dumps({**binding, **thresholds}, indent=2))
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
