"""Phase 1-4 - train + evaluate TOP50 / TOP25 reduced long-side pure-flip models.

Reuses fit_gbt / fit_logistic VERBATIM from
`short_rth_enriched_volume_level_retrain/train_and_evaluate.py` - the identical
functions used by the TOP100 long-side study - asserting RANDOM_STATE == 42
before any fit. TOP100 is re-fit here in the SAME harness so the comparison is
like-for-like rather than transcribed; it must reproduce the prior study's
0.6682 / 0.6512 exactly (verified in the run log and STUDY_REPORT).

Data: strict-causal prepared parquet from
`long_rth_mirrored_surface_top100_training/_work/` (read-only input).
Target: bullish_regime_flip_within_300s (unchanged).
Selection: 2025 AUC only, 2025 AP as tie-break. 2026 is sealed - it is never
used for fitting, selection, hyperparameters, thresholds, or calibration.
"""
from __future__ import annotations

import hashlib
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
RESULTS = STUDY / "results"
PRIOR_WORK = ROOT / "studies" / "long_rth_mirrored_surface_top100_training" / "_work"
ENRICHED = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"

TARGET = "bullish_regime_flip_within_300s"
RANDOM_STATE = 42
KEY = ["regime_start_ns", "observation_time"]

MANIFEST = json.load(open(RESULTS / "feature_sets_manifest.json"))
FS = MANIFEST["feature_sets"]
TOP100 = json.load(open(ROOT / "studies" / "long_rth_mirrored_surface_top100_training"
                        / "results" / "top100_feature_manifest.json"))["feature_names_in_order"]
FEATURE_SETS = {"TOP100": TOP100,
                "TOP50": FS["TOP50"]["feature_names_in_order"],
                "TOP25": FS["TOP25"]["feature_names_in_order"]}
# Guard again at fit time: reduced sets must remain exact prefixes.
for _n, _l in FEATURE_SETS.items():
    assert _l == TOP100[:len(_l)], f"{_n} is not an exact prefix of the frozen top-100"

_src = pd.read_csv(ROOT / "studies" / "runtime_constrained_f3_feature_reduction"
                   / "results" / "top_100_raw_feature_columns.csv")
FAMILY = dict(zip(_src["feature_name"], _src["family"]))

# Columns that must never enter a model matrix (outcome / future information).
# Deliberately a SUPERSET of the prepared schema - `regime_end_ns` is not a
# column in prepared_long_*.parquet (the flip time is carried as
# `confirm_flip_ns`), but it is listed so the guard stays correct if an upstream
# rename ever reintroduces it.
FORBIDDEN_IN_MATRIX = {"confirm_flip_ns", "time_to_bullish_flip_s",
                       "bullish_flip_within_600s", TARGET, "fill_ts", "fill_px",
                       "regime_end_ns", "regime_start_ns", "observation_time"}


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


def sha256_file(path, block=1 << 20):
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
                logloss=float(log_loss(y, p, labels=[0, 1])),
                base_positive_rate=float(np.mean(y)))


def decile_metrics(y, p):
    df = pd.DataFrame({"y": y, "p": p})
    df["dec"] = pd.qcut(df["p"].rank(method="first"), 10, labels=False)
    g = df.groupby("dec")["y"].mean()
    base = df["y"].mean()
    top, bot = float(g.loc[9]), float(g.loc[0])
    mono = float(pd.Series(g.values).corr(pd.Series(range(10)), method="spearman"))
    return dict(top_decile_flip_rate=top, bottom_decile_flip_rate=bot,
                top_decile_lift=float(top / base) if base else np.nan,
                decile_monotonicity_spearman=mono,
                decile_inverted=bool(mono < 0))


def monthly_auc(df, y, p, tscol="observation_time"):
    months = pd.to_datetime(df[tscol], unit="ns", utc=True).dt.strftime("%Y-%m")
    out = {}
    for m, idx in pd.Series(range(len(df))).groupby(months.values):
        yy, pp = y[idx.values], p[idx.values]
        out[m] = float(roc_auc_score(yy, pp)) if len(np.unique(yy)) == 2 else None
    return out


def regime_diagnostics(df, y, p):
    """Regime-level (entity) view. Diagnostic only - NOT a promotion gate.
    Regime score = max checkpoint score; regime label = 1 if the regime ever has
    a within-300s checkpoint."""
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
    pred_pos = agg["rmax_p"] >= thr_dec
    fp = int((pred_pos & (agg["rlabel"] == 0)).sum())
    fn = int((~pred_pos & (agg["rlabel"] == 1)).sum())
    res["false_positive_regime_rate"] = float(fp / max(1, int((agg["rlabel"] == 0).sum())))
    res["missed_flip_regime_rate"] = float(fn / max(1, int((agg["rlabel"] == 1).sum())))
    flagged = d.merge(agg[pred_pos][["regime"]], on="regime")
    flagged = flagged[(flagged["p"] >= thr_dec) & (flagged["y"] == 1)]
    lead = flagged.groupby("regime")["ttf"].max()  # earliest cross => largest ttf
    res["median_lead_time_to_bullish_flip_s"] = float(lead.median()) if len(lead) else None
    return res


def main():
    t0 = time.time()
    train_df = pd.concat([pd.read_parquet(PRIOR_WORK / f"prepared_long_{y}.parquet")
                          for y in (2021, 2022, 2023, 2024)], ignore_index=True)
    dev_df = pd.read_parquet(PRIOR_WORK / "prepared_long_2025.parquet")
    test_df = pd.read_parquet(PRIOR_WORK / "prepared_long_2026.parquet")
    print(f"train={len(train_df):,} dev={len(dev_df):,} test={len(test_df):,}")

    yb = {"train": train_df[TARGET].astype(int).to_numpy(),
          "2025": dev_df[TARGET].astype(int).to_numpy(),
          "2026": test_df[TARGET].astype(int).to_numpy()}
    dfs = {"train": train_df, "2025": dev_df, "2026": test_df}

    diag_rows, calib_frames, importance_rows, regime_rows = [], [], [], []
    monthly, store = {}, {}

    for fs_name, feats in FEATURE_SETS.items():
        leak = [f for f in feats if f in FORBIDDEN_IN_MATRIX]
        if leak:
            raise RuntimeError(f"{fs_name}: outcome/key columns in feature matrix: {leak}")
        obj = [f for f in feats if train_df[f].dtype == object]
        if obj:
            raise RuntimeError(f"{fs_name}: unexpected categorical columns: {obj}")
        Xb = {sp: dfs[sp][feats] for sp in ("train", "2025", "2026")}

        for model_name in ("logreg", "gbt"):
            tag = f"{fs_name}_{model_name}"
            tm0 = time.time()
            if model_name == "logreg":
                model, imputer, scaler = fit_logistic(Xb["train"], yb["train"])
                est = Pipeline([("imputer", imputer), ("scaler", scaler), ("model", model)])
                imps = [("logreg_coef", float(c)) for c in model.coef_[0]]
            else:
                est = fit_gbt(Xb["train"], yb["train"])
                rng = np.random.default_rng(RANDOM_STATE)
                idx = rng.choice(len(Xb["2025"]), size=min(20000, len(Xb["2025"])), replace=False)
                r = permutation_importance(est, Xb["2025"].iloc[idx], yb["2025"][idx],
                                           n_repeats=3, random_state=RANDOM_STATE,
                                           scoring="roc_auc", n_jobs=1)
                imps = [("perm_auc_2025", float(v)) for v in r.importances_mean]
            for feat, (kind, val) in zip(feats, imps):
                importance_rows.append({"feature_set": fs_name, "model": model_name,
                                        "feature": feat, "family": FAMILY[feat],
                                        "importance": val, "importance_kind": kind})

            proba = {sp: est.predict_proba(Xb[sp])[:, 1] for sp in ("train", "2025", "2026")}
            row = {"feature_set": fs_name, "model": model_name, "n_features": len(feats),
                   "fit_time_s": round(time.time() - tm0, 1)}
            for sp in ("train", "2025", "2026"):
                for k, v in base_metrics(yb[sp], proba[sp]).items():
                    row[f"{sp}_{k}"] = v
                for k, v in decile_metrics(yb[sp], proba[sp]).items():
                    row[f"{sp}_{k}"] = v

            # Calibration fit on 2025 ONLY - never on 2026.
            for method in ("isotonic", "sigmoid"):
                cal = CalibratedClassifierCV(FrozenEstimator(est), method=method).fit(
                    Xb["2025"], yb["2025"])
                for sp in ("2025", "2026"):
                    cp = cal.predict_proba(Xb[sp])[:, 1]
                    for k, v in base_metrics(yb[sp], cp).items():
                        row[f"{sp}_{k}_cal_{method}"] = v
            diag_rows.append(row)

            monthly[tag] = monthly_auc(test_df, yb["2026"], proba["2026"])
            for sp in ("2025", "2026"):
                rd = regime_diagnostics(dfs[sp], yb[sp], proba[sp])
                rd.update({"feature_set": fs_name, "model": model_name, "split": sp})
                regime_rows.append(rd)
                c = pd.DataFrame({"score": proba[sp], "y": yb[sp]})
                c["decile"] = pd.qcut(c["score"].rank(method="first"), 10, labels=False)
                cc = c.groupby("decile").agg(n=("y", "size"), mean_pred=("score", "mean"),
                                             actual=("y", "mean")).reset_index()
                cc["feature_set"], cc["model"], cc["split"] = fs_name, model_name, sp
                calib_frames.append(cc)

            store[tag] = {"2025_auc": row["2025_auc"], "2025_ap": row["2025_average_precision"],
                          "proba": proba}
            print(f"  {tag}: 2025 AUC={row['2025_auc']:.4f} 2026 AUC={row['2026_auc']:.4f} "
                  f"2025 lift={row['2025_top_decile_lift']:.2f} 2026 lift={row['2026_top_decile_lift']:.2f}")

    # Per-feature-set model selection: 2025 AUC, tie-break 2025 AP. 2026 unused.
    chosen = {}
    for fs_name in FEATURE_SETS:
        cands = [t for t in store if t.startswith(f"{fs_name}_")]
        chosen[fs_name] = max(cands, key=lambda t: (store[t]["2025_auc"], store[t]["2025_ap"]))

    pd.DataFrame(diag_rows).to_csv(RESULTS / "model_metrics.csv", index=False)
    pd.concat(calib_frames, ignore_index=True).to_csv(RESULTS / "calibration_deciles.csv", index=False)
    pd.DataFrame(importance_rows).to_csv(RESULTS / "feature_importance.csv", index=False)
    pd.DataFrame(regime_rows).to_csv(RESULTS / "regime_level_diagnostics.csv", index=False)
    imp = pd.DataFrame(importance_rows)
    imp.groupby(["feature_set", "model", "family"])["importance"].apply(
        lambda s: float(np.abs(s).sum())).reset_index().to_csv(
        RESULTS / "feature_family_contribution.csv", index=False)
    (RESULTS / "monthly_auc_2026.json").write_text(json.dumps(monthly, indent=2), encoding="utf-8")

    (RESULTS / "model_manifest.json").write_text(json.dumps({
        "target": TARGET, "random_state": RANDOM_STATE,
        "selection_rule": "max 2025 AUC, tie-break 2025 average precision; 2026 never used",
        "selected_per_feature_set": chosen,
        "feature_set_sizes": {k: len(v) for k, v in FEATURE_SETS.items()},
        "reused_fit_from": str((ENRICHED / "train_and_evaluate.py").relative_to(ROOT)).replace("\\", "/"),
        "prepared_data_source": str(PRIOR_WORK.relative_to(ROOT)).replace("\\", "/"),
        "train_rows": len(train_df), "dev_rows": len(dev_df), "test_rows": len(test_df),
        "positive_rate": {k: float(v.mean()) for k, v in yb.items()},
        "generator_sha256": sha256_file(Path(__file__).resolve()),
        "runtime_s": round(time.time() - t0, 1),
    }, indent=2, default=str), encoding="utf-8")

    # Prediction artifacts are written later by decide.py for the FINAL chosen
    # reduced model; here we persist every candidate's scores for reuse.
    for tag, s in store.items():
        for sp in ("2025", "2026"):
            out = dfs[sp][KEY + ["year", "confirm_flip_ns", "time_to_bullish_flip_s", TARGET]].copy()
            out["score"] = s["proba"][sp]
            out.to_parquet(STUDY / "_work" / f"pred_{tag}_{sp}.parquet", index=False)

    print(f"selected per set: {chosen}")
    print(f"done {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
