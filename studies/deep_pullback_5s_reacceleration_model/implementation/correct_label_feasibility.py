"""CORRECT-LABEL FIXED BASELINE FEASIBILITY FIT.

    DIAGNOSTIC_ONLY  /  NON_ACCEPTANCE_EVIDENCE  /  POST_COLLECTION_RELABELED_TARGET

Same causal X (already collected 35-input surface), CORRECT ordered-barrier y
(independently replayed from 1s bars in target_replay_diagnostic.py).

  fit   : 2021 + 2022
  eval  : 2023 (once)
  arms  : POOLED_BROAD, LONG_BROAD, SHORT_BROAD
  model : the conservative fixed LightGBM baseline (hyperparameters={}, seed 0)

NO tuning / feature selection / threshold optimization / architecture search /
target change / 2024 access. The diagnostic P90/P95/P97.5 are derived on 2021-2022
and applied unchanged to 2023; they are NOT promoted into study authority.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from research.analysis.modeling import SplitPolicy, fit_model
from studies.deep_pullback_5s_reacceleration_model.implementation.target_replay_diagnostic import RUN_DIRS
from studies.deep_pullback_5s_reacceleration_model.implementation.train_merge_fit_freeze import (
    KEY, build_modeling_frame, merge_train_partitions,
)

SD = Path("studies/deep_pullback_5s_reacceleration_model")
SEED = 0
STAMP = ["DIAGNOSTIC_ONLY", "NON_ACCEPTANCE_EVIDENCE", "POST_COLLECTION_RELABELED_TARGET"]


def _metrics(y, s) -> Dict[str, Any]:
    y = np.asarray(y, float); s = np.asarray(s, float)
    out = {"n": int(len(y)), "base_rate": float(y.mean()), "mean_prediction": float(s.mean())}
    if len(np.unique(y)) == 2:
        out["ROC_AUC"] = float(roc_auc_score(y, s))
        out["PR_AUC"] = float(average_precision_score(y, s))
        out["Brier"] = float(brier_score_loss(y, s))
        out["log_loss"] = float(log_loss(y, np.clip(s, 1e-6, 1 - 1e-6), labels=[0, 1]))
    return out


def _decile_table(y_val, s_val) -> list:
    q = pd.qcut(pd.Series(s_val), 10, labels=False, duplicates="drop")
    rows = []
    for d in sorted(pd.Series(q).dropna().unique()):
        m = (q == d).values
        rows.append({"decile": int(d) + 1, "n": int(m.sum()),
                     "score_min": float(s_val[m].min()), "score_max": float(s_val[m].max()),
                     "mean_pred": float(s_val[m].mean()),
                     "success_rate_2023": float(np.asarray(y_val)[m].mean())})
    return rows


def _tail_table(s_dev, s_val, y_val, base_rate) -> dict:
    q = np.quantile(s_dev, [0.90, 0.95, 0.975])
    out = {}
    for name, thr in zip(("P90", "P95", "P97_5"), q):
        sel = s_val >= thr
        sr = float(np.asarray(y_val)[sel].mean()) if sel.any() else None
        out[name] = {"threshold": float(thr), "n": int(sel.sum()),
                     "success_rate": sr,
                     "lift_vs_arm_base_rate": (float(sr / base_rate) if sr is not None and base_rate else None)}
    return out


def _fit_arm(name, Xd, yd, Xv, yv) -> Dict[str, Any]:
    model = fit_model(
        Xd, pd.Series(yd), arm="BROAD", estimator="lightgbm", seed=SEED,
        hyperparameters={},
        split_policy=SplitPolicy(kind="explicit_index",
                                 description=f"{name} diagnostic fit 2021+2022 (relabeled target)"),
        meta=pd.DataFrame({"_partition": "train"}, index=Xd.index),
    )
    s_dev = model.predict_proba(Xd)
    s_val = model.predict_proba(Xv)
    m = _metrics(yv, s_val)
    return {
        "arm": name,
        "train_rows": int(len(Xd)),
        "validation_rows": int(len(Xv)),
        **m,
        "score_deciles_dev": [float(x) for x in np.quantile(s_dev, np.arange(0.1, 1.0, 0.1))],
        "success_rate_2023_by_score_decile": _decile_table(yv, s_val),
        "diagnostic_score_tails_2021_2022_applied_to_2023": _tail_table(s_dev, s_val, yv, m["base_rate"]),
    }


def run() -> Dict[str, Any]:
    fc = json.loads((SD / "config" / "feature_contract.json").read_text(encoding="utf-8"))
    of = list(fc["feature_list"]); dn = fc["derived_causal_inputs"][0]["name"]

    mi = merge_train_partitions(SD, {y: Path(p) for y, p in RUN_DIRS.items()}, of)
    fr = build_modeling_frame(mi["merged_candidates"], mi["merged_observations"], of, dn)
    model_cols = fr["model_columns"]

    # full causal candidate surface (all 59,724 rows), keyed by candidate_ts
    cand = mi["merged_candidates"].copy()
    cand["_year"] = pd.to_datetime(cand["candidate_ts"], unit="ns", utc=True).dt.year
    X_all = cand[model_cols].apply(pd.to_numeric, errors="coerce").astype("float64")
    X_all.index = cand["candidate_ts"].values

    rep = pd.read_parquet(SD / "artifacts" / "target_replay_full.parquet")
    rep = rep.drop_duplicates("candidate_ts").set_index("candidate_ts")
    y_all = rep["label"]                     # 1 / 0 / NaN(excluded: AMBIGUOUS + CENSORED)
    dirn = rep["direction"]

    frame = pd.DataFrame({
        "y": y_all, "direction": dirn,
        "year": pd.Series(cand["_year"].values, index=cand["candidate_ts"].values),
    }).dropna(subset=["y"])
    frame["y"] = frame["y"].astype(int)
    Xf = X_all.loc[frame.index]

    dev_mask = frame["year"].isin([2021, 2022]).values
    val_mask = (frame["year"] == 2023).values

    excl = int(len(rep) - len(frame))
    result: Dict[str, Any] = {
        "stamp": STAMP,
        "target": "ordered_barrier +1.00/-0.75 ATR within 300s, entry next 1s open, ATR_T frozen",
        "label_source": "independent 1s-bar replay (target_replay_diagnostic.py)",
        "binary_population": {
            "replay_resolved_rows": int(len(frame)),
            "excluded_ambiguous_or_censored": excl,
            "replay_disposition_counts": rep["disposition"].value_counts().to_dict(),
        },
        "config": {"model_family": "lightgbm", "hyperparameters": {}, "seed": SEED,
                   "feature_surface": model_cols, "n_features": len(model_cols)},
        "arms": {},
    }

    arms = {
        "POOLED_BROAD": np.ones(len(frame), bool),
        "LONG_BROAD": (frame["direction"] == "LONG").values,
        "SHORT_BROAD": (frame["direction"] == "SHORT").values,
    }
    for name, amask in arms.items():
        d = dev_mask & amask
        v = val_mask & amask
        result["arms"][name] = _fit_arm(name, Xf.iloc[d], frame["y"].values[d],
                                        Xf.iloc[v], frame["y"].values[v])

    (SD / "artifacts" / "correct_label_feasibility.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    import sys
    json.dump(run(), sys.stdout, indent=2, default=str)
    print()
