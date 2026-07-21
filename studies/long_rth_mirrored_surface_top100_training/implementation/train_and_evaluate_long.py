"""Phase 5-8 - train + evaluate the mirrored long-side top-100 pure-flip model.

Reuses fit_gbt / fit_logistic VERBATIM from
`short_rth_enriched_volume_level_retrain/train_and_evaluate.py` (the same
functions the short-side pure-flip study used), asserting RANDOM_STATE==42
before any fit. Single feature set (frozen top-100), two models. Selection on
2025 only; 2026 sealed (used for evaluation only, never fit/select/calibrate).

Target: bullish_regime_flip_within_300s.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.inspection import permutation_importance
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             log_loss, roc_auc_score)
from sklearn.pipeline import Pipeline

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
WORK, RESULTS = STUDY / "_work", STUDY / "results"
ENRICHED = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"


def _load_module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


_te = _load_module("_enriched_retrain_train_eval", ENRICHED / "train_and_evaluate.py")
assert _te.RANDOM_STATE == 42, "reused fit_gbt/fit_logistic RANDOM_STATE must be 42"
fit_gbt, fit_logistic = _te.fit_gbt, _te.fit_logistic

TARGET = "bullish_regime_flip_within_300s"
RANDOM_STATE = 42
KEY = ["regime_start_ns", "observation_time"]
TOP100 = json.load(open(STUDY / "results" / "top100_feature_manifest.json"))["feature_names_in_order"]
FAMILY = dict(zip(pd.read_csv(STUDY / "results" / "top100_feature_list.csv")["feature_name"],
                  pd.read_csv(STUDY / "results" / "top100_feature_list.csv")["family"]))


def sha256_file(path, block=1 << 20):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def base_metrics(y, p):
    if len(np.unique(y)) < 2:
        return dict(auc=np.nan, average_precision=np.nan, brier=np.nan, logloss=np.nan)
    return dict(auc=float(roc_auc_score(y, p)),
                average_precision=float(average_precision_score(y, p)),
                brier=float(brier_score_loss(y, p)),
                logloss=float(log_loss(y, p, labels=[0, 1])))


def decile_metrics(y, p):
    df = pd.DataFrame({"y": y, "p": p})
    df["dec"] = pd.qcut(df["p"].rank(method="first"), 10, labels=False)
    g = df.groupby("dec")["y"].mean()
    base = df["y"].mean()
    top, bot = float(g.loc[9]), float(g.loc[0])
    # monotonicity: Spearman between decile index and actual rate
    mono = float(pd.Series(g.values).corr(pd.Series(range(10)), method="spearman"))
    return dict(top_decile_flip_rate=top, bottom_decile_flip_rate=bot,
                top_decile_lift=float(top / base) if base else np.nan,
                decile_monotonicity_spearman=mono,
                decile_actual_rates=[float(x) for x in g.values])


def monthly_auc(df, y, p, tscol="observation_time"):
    months = pd.to_datetime(df[tscol], unit="ns", utc=True).dt.strftime("%Y-%m")
    out = {}
    for m, idx in pd.Series(range(len(df))).groupby(months.values):
        yy, pp = y[idx.values], p[idx.values]
        out[m] = float(roc_auc_score(yy, pp)) if len(np.unique(yy)) == 2 else None
    return out


def regime_diagnostics(df, y, p):
    """Regime-level (timing-inside-regime framing). Per regime:
       regime score = max checkpoint score; regime label = 1 if the regime EVER
       has a within-300s checkpoint (max row label). Reported as diagnostic, not
       a promotion gate (per brief)."""
    d = pd.DataFrame({"regime": df["regime_start_ns"].values, "y": y, "p": p,
                      "ttf": df["time_to_bullish_flip_s"].values})
    agg = d.groupby("regime").agg(rmax_p=("p", "max"), rlabel=("y", "max")).reset_index()
    base = float(agg["rlabel"].mean())
    res = {"n_regimes": int(len(agg)), "base_regime_flip_rate": base,
           "regime_level_auc": float(roc_auc_score(agg["rlabel"], agg["rmax_p"]))
           if agg["rlabel"].nunique() == 2 else None}
    thr_dec = agg["rmax_p"].quantile(0.90)
    top = agg[agg["rmax_p"] >= thr_dec]
    res["top_decile_regime_flip_rate"] = float(top["rlabel"].mean()) if len(top) else None
    for pct, q in (("top20", 0.80), ("top10", 0.90), ("top5", 0.95)):
        sel = agg[agg["rmax_p"] >= agg["rmax_p"].quantile(q)]
        res[f"{pct}_crossing_flip_rate"] = float(sel["rlabel"].mean()) if len(sel) else None
    # operating point = top-decile regime score threshold
    pred_pos = agg["rmax_p"] >= thr_dec
    tp = int(((pred_pos) & (agg["rlabel"] == 1)).sum())
    fp = int(((pred_pos) & (agg["rlabel"] == 0)).sum())
    fn = int(((~pred_pos) & (agg["rlabel"] == 1)).sum())
    res["false_positive_regime_rate"] = float(fp / max(1, (agg["rlabel"] == 0).sum()))
    res["missed_flip_regime_rate"] = float(fn / max(1, (agg["rlabel"] == 1).sum()))
    # median lead time: among flipping regimes flagged, first checkpoint crossing
    flagged = d.merge(agg[pred_pos][["regime"]], on="regime")
    flagged = flagged[(flagged["p"] >= thr_dec) & (flagged["y"] == 1)]
    lead = flagged.groupby("regime")["ttf"].max()  # earliest cross => largest ttf
    res["median_lead_time_to_bullish_flip_s"] = float(lead.median()) if len(lead) else None
    return res


def main():
    t0 = time.time()
    train_df = pd.concat([pd.read_parquet(WORK / f"prepared_long_{y}.parquet")
                          for y in (2021, 2022, 2023, 2024)], ignore_index=True)
    dev_df = pd.read_parquet(WORK / "prepared_long_2025.parquet")
    test_df = pd.read_parquet(WORK / "prepared_long_2026.parquet")

    # No categorical expansion expected for the raw-100 (all numeric); assert it.
    obj = [c for c in TOP100 if train_df[c].dtype == object]
    if obj:
        raise RuntimeError(f"unexpected categorical top-100 columns need encoding: {obj}")

    yb = {"train": train_df[TARGET].astype(int).to_numpy(),
          "2025": dev_df[TARGET].astype(int).to_numpy(),
          "2026": test_df[TARGET].astype(int).to_numpy()}
    Xb = {"train": train_df[TOP100], "2025": dev_df[TOP100], "2026": test_df[TOP100]}
    print(f"train={len(train_df):,} dev={len(dev_df):,} test={len(test_df):,}")
    print(f"pos rate train={yb['train'].mean():.4f} 2025={yb['2025'].mean():.4f} 2026={yb['2026'].mean():.4f}")

    diag_rows, calib_frames, importance_rows, regime_rows = [], [], [], []
    monthly, selected = {}, {}

    for model_name in ("logreg", "gbt"):
        tm0 = time.time()
        if model_name == "logreg":
            model, imputer, scaler = fit_logistic(Xb["train"], yb["train"])
            est = Pipeline([("imputer", imputer), ("scaler", scaler), ("model", model)])
            for fi, feat in enumerate(TOP100):
                importance_rows.append({"model": model_name, "feature": feat,
                                        "family": FAMILY[feat], "importance": float(model.coef_[0][fi]),
                                        "importance_kind": "logreg_coef"})
        else:
            est = fit_gbt(Xb["train"], yb["train"])
            rng = np.random.default_rng(RANDOM_STATE)
            idx = rng.choice(len(Xb["2025"]), size=min(20000, len(Xb["2025"])), replace=False)
            r = permutation_importance(est, Xb["2025"].iloc[idx], yb["2025"][idx],
                                       n_repeats=3, random_state=RANDOM_STATE, scoring="roc_auc", n_jobs=1)
            for fi, feat in enumerate(TOP100):
                importance_rows.append({"model": model_name, "feature": feat,
                                        "family": FAMILY[feat], "importance": float(r.importances_mean[fi]),
                                        "importance_kind": "perm_auc_2025"})

        proba = {sp: est.predict_proba(Xb[sp])[:, 1] for sp in ("train", "2025", "2026")}
        row = {"model": model_name, "n_features": len(TOP100), "fit_time_s": round(time.time() - tm0, 1)}
        for sp in ("train", "2025", "2026"):
            for k, v in base_metrics(yb[sp], proba[sp]).items():
                row[f"{sp}_{k}"] = v
            for k, v in decile_metrics(yb[sp], proba[sp]).items():
                if k != "decile_actual_rates":
                    row[f"{sp}_{k}"] = v

        # calibration on 2025 only
        for method in ("isotonic", "sigmoid"):
            cal = CalibratedClassifierCV(FrozenEstimator(est), method=method).fit(Xb["2025"], yb["2025"])
            for sp in ("2025", "2026"):
                cp = cal.predict_proba(Xb[sp])[:, 1]
                for k, v in base_metrics(yb[sp], cp).items():
                    row[f"{sp}_{k}_cal_{method}"] = v
        diag_rows.append(row)

        monthly[model_name] = monthly_auc(test_df, yb["2026"], proba["2026"])
        for sp, dfr in (("2025", dev_df), ("2026", test_df)):
            rd = regime_diagnostics(dfr, yb[sp], proba["2025" if sp == "2025" else "2026"])
            rd.update({"model": model_name, "split": sp})
            regime_rows.append(rd)
        for sp, dfr, y in (("2025", dev_df, yb["2025"]), ("2026", test_df, yb["2026"])):
            c = pd.DataFrame({"score": proba[sp], "y": y})
            c["decile"] = pd.qcut(c["score"].rank(method="first"), 10, labels=False)
            cc = c.groupby("decile").agg(n=("y", "size"), mean_pred=("score", "mean"),
                                         actual=("y", "mean")).reset_index()
            cc["model"], cc["split"] = model_name, sp
            calib_frames.append(cc)
        selected[model_name] = {"2025_auc": row["2025_auc"], "proba": proba}
        print(f"  {model_name}: 2025 AUC={row['2025_auc']:.4f} 2026 AUC={row['2026_auc']:.4f} "
              f"2025 top-dec lift={row['2025_top_decile_lift']:.2f} 2026 lift={row['2026_top_decile_lift']:.2f}")

    # select by 2025 AUC
    sel_model = max(selected, key=lambda m: selected[m]["2025_auc"])
    for sp, dfr in (("2025", dev_df), ("2026", test_df)):
        out = dfr[KEY + ["year", "confirm_flip_ns", "time_to_bullish_flip_s", TARGET]].copy()
        out["score"] = selected[sel_model]["proba"][sp]
        out.to_parquet(RESULTS / f"selected_model_predictions_{sp}.parquet", index=False)

    pd.DataFrame(diag_rows).to_csv(RESULTS / "model_metrics.csv", index=False)
    pd.concat(calib_frames, ignore_index=True).to_csv(RESULTS / "calibration_deciles.csv", index=False)
    pd.DataFrame(importance_rows).to_csv(RESULTS / "feature_importance.csv", index=False)
    pd.DataFrame(regime_rows).to_csv(RESULTS / "regime_level_diagnostics.csv", index=False)
    imp = pd.DataFrame(importance_rows)
    fam = imp.groupby(["model", "family"])["importance"].apply(lambda s: float(np.abs(s).sum())).reset_index()
    fam.to_csv(RESULTS / "feature_family_contribution.csv", index=False)
    (RESULTS / "monthly_auc_2026.json").write_text(json.dumps(monthly, indent=2), encoding="utf-8")

    manifest = {
        "target": TARGET, "selected_model": sel_model, "n_features": len(TOP100),
        "random_state": RANDOM_STATE,
        "reused_fit_from": str(ENRICHED / "train_and_evaluate.py"),
        "train_rows": len(train_df), "dev_rows": len(dev_df), "test_rows": len(test_df),
        "positive_rate": {k: float(v.mean()) for k, v in yb.items()},
        "generator_sha256": sha256_file(Path(__file__).resolve()),
        "runtime_s": round(time.time() - t0, 1),
    }
    (RESULTS / "model_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"selected={sel_model}  done {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
