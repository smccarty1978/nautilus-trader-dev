"""Pre-OOS directional diagnostic decomposition (TRAIN-only, read-only).

Decomposes the pooled 2023 ROC-AUC of the frozen BROAD baseline into:
  A unconditional pooled prior      (2021-2022 -> 2023)
  B direction-only prior            (LONG / SHORT priors from 2021-2022)
  C availability-only prior         (model_c available? priors from 2021-2022)
  D direction x availability prior  (4 group priors from 2021-2022)
  E frozen BROAD model pooled       (gated: fit 2021+2022, score 2023 -- the 0.793 path)
  F/G frozen BROAD model per-direction

Every baseline is frozen on 2021-2022 development rows and applied to 2023.
No tuning. No feature change. No model replacement.

The frozen research target is the ordered +1.00 / -0.75 ATR barrier race. Because an
independent exhaustive replay (`target_replay_diagnostic.py`) shows the AS-COLLECTED
`target_flip_within_horizon` is a *different* target (opposing 1m regime flip within
300s), every metric here is reported on BOTH labels:
  collected_label  -- what the frozen BROAD model was actually fit against
  replay_label     -- the frozen ordered-barrier target, recomputed from 1s bars
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from studies.deep_pullback_5s_reacceleration_model.implementation.target_replay_diagnostic import RUN_DIRS
from studies.deep_pullback_5s_reacceleration_model.implementation.train_merge_fit_freeze import (
    KEY, build_modeling_frame, merge_train_partitions,
)

SD = Path("studies/deep_pullback_5s_reacceleration_model")
ARM = "BROAD"
SEED = 0


def _metrics(y: np.ndarray, s: np.ndarray) -> Dict[str, Any]:
    y = np.asarray(y, float)
    s = np.asarray(s, float)
    keep = ~np.isnan(y)
    y, s = y[keep], s[keep]
    out: Dict[str, Any] = {
        "n": int(len(y)),
        "base_rate": (float(y.mean()) if len(y) else None),
        "mean_prediction": (float(s.mean()) if len(s) else None),
    }
    if len(y) and len(np.unique(y)) == 2:
        out["ROC_AUC"] = float(roc_auc_score(y, s))
        out["PR_AUC"] = float(average_precision_score(y, s))
        out["Brier"] = float(brier_score_loss(y, s))
        try:
            out["log_loss"] = float(log_loss(y, np.clip(s, 1e-6, 1 - 1e-6), labels=[0, 1]))
        except ValueError:
            out["log_loss"] = None
    else:
        out.update({"ROC_AUC": None, "PR_AUC": None, "Brier": None, "log_loss": None,
                    "note": "N/A -- stratum lacks both classes"})
    return out


def _prior_score(dev: pd.DataFrame, val: pd.DataFrame, group_cols, label_col: str) -> np.ndarray:
    if not group_cols:
        p = dev[label_col].mean()
        return np.full(len(val), float(p))
    priors = dev.groupby(group_cols)[label_col].mean()
    keys = val[group_cols[0]] if len(group_cols) == 1 else list(zip(*[val[c] for c in group_cols]))
    return np.array([float(priors.get(k, dev[label_col].mean())) for k in keys])


def run() -> Dict[str, Any]:
    fc = json.loads((SD / "config" / "feature_contract.json").read_text(encoding="utf-8"))
    of = list(fc["feature_list"])
    dn = fc["derived_causal_inputs"][0]["name"]

    mi = merge_train_partitions(SD, {y: Path(p) for y, p in RUN_DIRS.items()}, of)
    fr = build_modeling_frame(mi["merged_candidates"], mi["merged_observations"], of, dn)

    X, y_coll, meta = fr["X"], fr["y"], fr["meta"]
    direction = fr["prevailing_direction"].map({1: "LONG", -1: "SHORT"}).values
    mc_avail = X[dn].notna().values

    # bring in the replay label, aligned on the candidate key
    rep = pd.read_parquet(SD / "artifacts" / "target_replay_full.parquet")
    joined = mi["merged_candidates"].merge(
        mi["merged_observations"][KEY + ["disposition", "target_flip_within_horizon"]],
        on=KEY, how="inner", validate="one_to_one",
    )
    resolved = joined["disposition"].isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"]).values
    rk = joined.loc[resolved, "candidate_ts"].values
    rep_by_ts = rep.set_index("candidate_ts")["label"]
    y_rep = pd.Series(rk).map(rep_by_ts).astype(float).values  # replay label on the SAME rows

    df = pd.DataFrame({
        "year": meta["_year"].values,
        "role": meta["_selection_role"].values,
        "direction": direction,
        "mc_avail": mc_avail,
        "y_coll": y_coll.values,
        "y_rep": y_rep,
    })
    Xr = X.reset_index(drop=True)

    dev = df[df["year"].isin([2021, 2022])]
    v23 = df[df["year"] == 2023]
    v23X = Xr.loc[v23.index]
    v22 = df[df["year"] == 2022]
    v22X = Xr.loc[v22.index]

    # ---- frozen BROAD model, gated (fit 2021+2022 -> predict 2023) and inner (fit 2021 -> 2022)
    from research.analysis.modeling import SplitPolicy, fit_model

    def _fit(mask_df, label):
        m = df.loc[mask_df.index]
        return fit_model(
            Xr.loc[mask_df.index], pd.Series(m[label].values), arm=ARM, estimator="lightgbm",
            seed=SEED, split_policy=SplitPolicy(kind="explicit_index", description="diagnostic"),
            meta=pd.DataFrame({"_partition": "train"}, index=mask_df.index),
        )

    gated_coll = _fit(dev, "y_coll")
    s23_gated_coll = gated_coll.predict_proba(v23X)
    inner_coll = _fit(dev[dev["year"] == 2021], "y_coll")
    s22_inner_coll = inner_coll.predict_proba(v22X)

    out: Dict[str, Any] = {"baselines_2023": {}, "broad_model": {}, "availability_stratified": {},
                           "per_direction_calibration": {}, "within_direction_score_tails": {},
                           "direction_base_rates": {}, "model_c_availability": {}}

    for lbl_name, lbl in (("collected_label", "y_coll"), ("replay_label", "y_rep")):
        d = dev.dropna(subset=[lbl])
        v = v23.dropna(subset=[lbl])
        base = {
            "unconditional": _metrics(v[lbl], _prior_score(d, v, [], lbl)),
            "direction_only": _metrics(v[lbl], _prior_score(d, v, ["direction"], lbl)),
            "availability_only": _metrics(v[lbl], _prior_score(d, v, ["mc_avail"], lbl)),
            "direction_x_availability": _metrics(v[lbl], _prior_score(d, v, ["direction", "mc_avail"], lbl)),
        }
        out["baselines_2023"][lbl_name] = base

    # frozen BROAD model metrics (collected-label model is the real frozen artifact)
    for yr, sc, dd, tag in ((2023, s23_gated_coll, v23, "2023_gated"), (2022, s22_inner_coll, v22, "2022_inner")):
        blk = {"pooled": _metrics(dd["y_coll"].values, sc)}
        for D in ("LONG", "SHORT"):
            mask = (dd["direction"] == D).values
            blk[D] = _metrics(dd["y_coll"].values[mask], sc[mask])
        blk["pooled_on_replay_label"] = _metrics(dd["y_rep"].values, sc)
        for D in ("LONG", "SHORT"):
            mask = (dd["direction"] == D).values
            blk[f"{D}_on_replay_label"] = _metrics(dd["y_rep"].values[mask], sc[mask])
        out["broad_model"][tag] = blk

    # availability-stratified frozen BROAD on 2023
    for D in ("LONG", "SHORT"):
        for av, avl in ((True, "available"), (False, "unavailable")):
            m = ((v23["direction"] == D) & (v23["mc_avail"] == av)).values
            out["availability_stratified"][f"{D}_{avl}"] = {
                "collected_label": _metrics(v23["y_coll"].values[m], s23_gated_coll[m]),
                "replay_label": _metrics(v23["y_rep"].values[m], s23_gated_coll[m]),
            }

    # per-direction calibration (descriptive, no calibration fit)
    for D in ("LONG", "SHORT"):
        m = (v23["direction"] == D).values
        sc = s23_gated_coll[m]
        yy = v23["y_coll"].values[m]
        bins = pd.qcut(pd.Series(sc), q=5, duplicates="drop")
        rows = []
        for b, idx in pd.Series(range(len(sc))).groupby(bins, observed=True):
            i = idx.values
            rows.append({"bin": str(b), "n": int(len(i)),
                         "mean_pred": float(np.mean(sc[i])),
                         "observed_rate_collected": float(np.mean(yy[i])),
                         "observed_rate_replay": float(np.nanmean(v23["y_rep"].values[m][i]))})
        out["per_direction_calibration"][D] = {
            "base_rate_collected": float(np.mean(yy)),
            "base_rate_replay": float(np.nanmean(v23["y_rep"].values[m])),
            "mean_prediction": float(np.mean(sc)),
            "Brier_collected": float(brier_score_loss(yy, sc)),
            "bins": rows,
        }

    # within-direction TRAIN score tails (2021-2022 dev), applied to 2023 (diagnostic only)
    dev_scored = gated_coll.predict_proba(Xr.loc[dev.index])
    for D in ("LONG", "SHORT"):
        dm = (dev["direction"] == D).values
        q = np.quantile(dev_scored[dm], [0.90, 0.95, 0.975])
        vm = (v23["direction"] == D).values
        v_s = s23_gated_coll[vm]
        v_yc = v23["y_coll"].values[vm]
        v_yr = v23["y_rep"].values[vm]
        tails = {}
        for name, thr in zip(("P90", "P95", "P97_5"), q):
            sel = v_s >= thr
            tails[name] = {
                "threshold": float(thr), "n": int(sel.sum()),
                "pos_rate_collected": (float(v_yc[sel].mean()) if sel.any() else None),
                "lift_vs_dir_base_collected": (float(v_yc[sel].mean() / v_yc.mean()) if sel.any() and v_yc.mean() else None),
                "pos_rate_replay": (float(np.nanmean(v_yr[sel])) if sel.any() else None),
                "lift_vs_dir_base_replay": (float(np.nanmean(v_yr[sel]) / np.nanmean(v_yr)) if sel.any() else None),
                "median_score": (float(np.median(v_s[sel])) if sel.any() else None),
            }
        out["within_direction_score_tails"][D] = tails

    # direction base rates
    for lbl_name, lbl in (("collected", "y_coll"), ("replay", "y_rep")):
        out["direction_base_rates"][lbl_name] = {
            "development_2021_2022": {
                D: float(dev[dev["direction"] == D][lbl].mean(skipna=True)) for D in ("LONG", "SHORT")
            },
            "validation_2023": {
                D: float(v23[v23["direction"] == D][lbl].mean(skipna=True)) for D in ("LONG", "SHORT")
            },
        }

    # model-c availability
    out["model_c_availability"] = {
        "overall": float(df["mc_avail"].mean()),
        "LONG": float(df[df["direction"] == "LONG"]["mc_avail"].mean()),
        "SHORT": float(df[df["direction"] == "SHORT"]["mc_avail"].mean()),
        "P_success_given_available_collected_dev": float(dev[dev["mc_avail"]]["y_coll"].mean()),
        "P_success_given_unavailable_collected_dev": float(dev[~dev["mc_avail"]]["y_coll"].mean()),
        "P_success_given_available_replay_dev": float(dev[dev["mc_avail"]]["y_rep"].mean(skipna=True)),
        "P_success_given_unavailable_replay_dev": float(dev[~dev["mc_avail"]]["y_rep"].mean(skipna=True)),
    }

    (SD / "artifacts" / "pre_oos_directional_diagnostic.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys

    json.dump(run(), sys.stdout, indent=2, default=str)
    print()
