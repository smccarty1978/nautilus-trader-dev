"""Refit W4 on train checkpoints only and freeze the D10 threshold from val.

Train: atlas period == 'train' (2021-2024). Val: period == 'val'
(2025-01-01..2025-02-28). No test/secondary_oos row is touched here.
The threshold is an ABSOLUTE validation-frozen score threshold (90th
percentile of val W4 probabilities), persisted with provenance before any
test-period economics exist anywhere in this study.
"""
from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studies.fable5_pre_flip_d10_reversal_entry.common import (
    ATLAS_PATH, MANIFEST_PATH, WORK, w4_feature_list,
)

SEED = 42
D10_PCT = 90.0
NAN_GATE = "aligned_price_minus_center_5m"  # matches upstream trainer


def main() -> None:
    t0 = time.time()
    feats = w4_feature_list()
    cols = list(dict.fromkeys(
        feats + [NAN_GATE, "observation_time", "direction", "regime_age",
                 "period", "opp_flip_in_120s", "terminal_deterioration"]
    ))

    print(f"Loading train+val checkpoint rows ({len(feats)} features)...")
    df = pd.read_parquet(
        ATLAS_PATH, columns=cols,
        filters=[("period", "in", ["train", "val"])],
    )
    df = df.dropna(subset=[NAN_GATE])
    train = df[df["period"] == "train"]
    val = df[df["period"] == "val"]
    del df
    print(f"  train rows: {len(train):,}  val rows: {len(val):,} "
          f"({time.time()-t0:.0f}s)")
    assert len(train) > 1_000_000 and len(val) > 100_000, "unexpected split sizes"

    y_tr = ((train["opp_flip_in_120s"] == 1)
            | (train["terminal_deterioration"] == 1)).to_numpy(dtype=int)
    y_vl = ((val["opp_flip_in_120s"] == 1)
            | (val["terminal_deterioration"] == 1)).to_numpy(dtype=int)

    clf = HistGradientBoostingClassifier(
        max_iter=100, max_depth=5, learning_rate=0.05, random_state=SEED,
    )
    print("Fitting W4 (seed 42, upstream hyperparameters)...")
    clf.fit(train[feats].to_numpy(), y_tr)

    prob_tr = clf.predict_proba(train[feats].to_numpy())[:, 1]
    prob_vl = clf.predict_proba(val[feats].to_numpy())[:, 1]
    auc_tr = roc_auc_score(y_tr, prob_tr)
    auc_vl = roc_auc_score(y_vl, prob_vl)
    print(f"  AUC train={auc_tr:.4f}  val={auc_vl:.4f}")

    threshold = float(np.percentile(prob_vl, D10_PCT))
    print(f"  Frozen D10 threshold (P{D10_PCT:.0f} of val scores): {threshold:.6f}")
    print(f"  val fraction >= threshold: {(prob_vl >= threshold).mean():.4f}")

    with open(WORK / "w4_fable5.pkl", "wb") as f:
        pickle.dump({"model": clf, "features": feats, "seed": SEED}, f)

    from studies.fable5_pre_flip_d10_reversal_entry.common import sha256_file
    provenance = {
        "frozen_at_utc": pd.Timestamp.utcnow().isoformat(),
        "definition": "absolute validation-frozen score threshold",
        "threshold": threshold,
        "percentile": D10_PCT,
        "val_period": "2025-01-01..2025-02-28",
        "train_period": "2021-01-01..2024-12-31",
        "train_rows": int(len(train)),
        "val_rows": int(len(val)),
        "train_base_rate": float(y_tr.mean()),
        "val_base_rate": float(y_vl.mean()),
        "auc_train": float(auc_tr),
        "auc_val": float(auc_vl),
        "n_features": len(feats),
        "model": "HistGradientBoostingClassifier(max_iter=100, max_depth=5, "
                 "learning_rate=0.05, random_state=42)",
        "nan_gate": NAN_GATE,
        "atlas_sha256": sha256_file(ATLAS_PATH),
        "manifest_sha256": sha256_file(MANIFEST_PATH),
    }
    (WORK / "frozen_threshold.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"Frozen threshold + provenance written ({time.time()-t0:.0f}s total).")


if __name__ == "__main__":
    main()
