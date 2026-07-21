"""Directional feature-family ablation — the gate for the directional
rebuild.

Question: is the model just measuring distance-to-sticky-regime-trigger
(EMA / threshold geometry), or do non-EMA context features add
independent discrimination — especially for SHORTS?

Runs rolling walk-forward (6m train / 1m deploy) on the 97-feature
augmented candidate table (2024-2026), separately for long and short
candidates, under 4 feature-family ablations:

  set1 ALL        : all 97 features
  set2 NO_EMA     : all EXCEPT EMA-distance + threshold-distance
  set3 CONTEXT    : ONLY non-EMA context (volume / VWAP / time /
                    regime-maturity / micro MFE-MAE)
  set4 EMA_ONLY   : ONLY EMA-distance + threshold-distance

Target = label_T1 (V_A-confirmed flip — the deployment target).

Reports per direction per set: OOS AUC, top-decile lift, VA-confirm
capture; plus feature-importance share by family for set1.

Gate: if set3 (context-only) has real AUC and set1 (all) clearly beats
set4 (EMA-only) — especially for shorts — the directional rebuild is
justified. If set4 ~ set1, the model is just geometry and the rebuild
is moot.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

CANDS = ("studies/v_a_excursion_regime/results_v0/"
            "pre_flip_candidates_augmented.parquet")
SEED = 42
VAL_FRAC = 0.20
TRAIN_MONTHS = 6


def feature_columns(df):
    drop = set([
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        "candidate_direction", "ym", "dt",
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s", "close_3m", "close_5m",
        "vwap_value", "label_T1", "label_T2", "label_T3",
    ])
    feats = [c for c in df.columns if c not in drop]
    return [c for c in feats
            if df[c].dtype not in ("object", "datetime64[ns, UTC]")]


def classify(feat):
    """Assign a feature to a family."""
    if feat.startswith("dist_close_to_ema"):
        return "EMA"
    if feat.startswith("dist_to_1m_flip_threshold"):
        return "THRESH"
    if feat.startswith("dist_close_to_vwap") or feat.startswith("vwap") \
            or feat == "dist_to_vwap_dir_atr":
        return "VWAP"
    if feat.startswith("vol_"):
        return "VOL"
    if feat.startswith("micro_"):
        return "MICRO"
    if feat.startswith("current_regime_"):
        return "MATURITY"
    if feat in ("hour_ct", "minute_ct", "day_of_week",
                   "minutes_since_rth_open", "cum_vol_session",
                   "obv_session"):
        return "TIME"
    if feat.startswith("regime_") or feat.startswith("bars_in_regime") \
            or feat.startswith("atr_"):
        return "TFSTATE"
    return "OTHER"


def fit_es(X_tr, y_tr, X_val, y_val):
    m = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1,
        is_unbalance=True, verbose=-1)
    m.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
          callbacks=[lgb.early_stopping(50, verbose=False),
                      lgb.log_evaluation(0)])
    return m


def rolling_oos(df, fset, want_importance=False):
    """Rolling 6m/1m walk-forward; returns (oos_df, summed_gain|None)."""
    df = df.sort_values("close_ts_ns").reset_index(drop=True)
    months = sorted(df["ym"].unique())
    out = []
    gain_sum = None
    for i in range(TRAIN_MONTHS, len(months)):
        dep = months[i]
        tr = df[df["ym"].isin(months[i - TRAIN_MONTHS:i])
                   ].sort_values("close_ts_ns")
        de = df[df["ym"] == dep]
        if len(tr) < 300 or tr["label_T1"].sum() < 15 or len(de) < 10:
            continue
        n_val = int(len(tr) * VAL_FRAC)
        n_tro = len(tr) - n_val
        if n_val < 30 or tr.iloc[:n_tro]["label_T1"].sum() < 5:
            continue
        m = fit_es(tr.iloc[:n_tro][fset], tr.iloc[:n_tro]["label_T1"],
                      tr.iloc[n_tro:][fset], tr.iloc[n_tro:]["label_T1"])
        sc = m.predict_proba(de[fset])[:, 1]
        o = de[["close_ts_ns", "year", "label_T1"]].copy()
        o["score"] = sc
        out.append(o)
        if want_importance:
            g = m.booster_.feature_importance(importance_type="gain")
            gain_sum = (g if gain_sum is None else gain_sum + g)
    oos = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    return oos, gain_sum


def summarize(name, oos):
    if len(oos) < 200 or oos["label_T1"].nunique() < 2:
        print(f"  {name:<22} (insufficient OOS)")
        return
    auc = roc_auc_score(oos["label_T1"], oos["score"])
    base = oos["label_T1"].mean()
    thr = oos["score"].quantile(0.90)
    top = oos[oos["score"] >= thr]
    toprate = top["label_T1"].mean() if len(top) else 0
    lift = toprate / base if base > 0 else 0
    # VA-confirm capture: of all true confirms, how many are in top decile
    capture = (top["label_T1"].sum() / oos["label_T1"].sum()
                  if oos["label_T1"].sum() else 0)
    print(f"  {name:<22} AUC={auc:.4f}  base={base:.1%}  "
          f"top10_lift={lift:.2f}x  VA_capture={capture:.1%}")
    return auc


def main():
    t0 = time.time()
    df = pd.read_parquet(CANDS)
    df = df[df["year"].isin([2024, 2025, 2026])].copy()
    df["dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["ym"] = (df["dt"].dt.tz_convert("America/Chicago")
                  ).dt.to_period("M")
    feats = feature_columns(df)
    fam = {f: classify(f) for f in feats}
    from collections import Counter
    print(f"Augmented candidates 2024-2026: {len(df):,}  "
          f"({len(feats)} features)")
    print(f"Feature families: {dict(Counter(fam.values()))}")

    ema_thresh = [f for f in feats if fam[f] in ("EMA", "THRESH")]
    context = [f for f in feats
                  if fam[f] in ("VOL", "VWAP", "TIME", "MATURITY",
                                  "MICRO")]
    sets = {
        "set1_ALL": feats,
        "set2_NO_EMA": [f for f in feats if fam[f] not in
                           ("EMA", "THRESH")],
        "set3_CONTEXT": context,
        "set4_EMA_ONLY": ema_thresh,
    }
    for k, v in sets.items():
        print(f"  {k}: {len(v)} features")

    longs = df[df["candidate_direction"] == 1].copy()
    shorts = df[df["candidate_direction"] == -1].copy()

    for dname, dd in [("LONG", longs), ("SHORT", shorts)]:
        print(f"\n{'='*72}")
        print(f"{dname} candidates  (n={len(dd):,}, rolling OOS "
              f"2024-07..2026)")
        print(f"{'='*72}")
        imp_set1 = None
        for sname, fset in sets.items():
            oos, gain = rolling_oos(
                dd, fset, want_importance=(sname == "set1_ALL"))
            summarize(sname, oos)
            if sname == "set1_ALL" and gain is not None:
                imp_set1 = pd.DataFrame({"feat": fset, "gain": gain})
        # Feature-importance share by family (set1)
        if imp_set1 is not None:
            imp_set1["fam"] = imp_set1["feat"].map(fam)
            byfam = (imp_set1.groupby("fam")["gain"].sum()
                        .sort_values(ascending=False))
            tot = byfam.sum()
            print(f"  -- set1 gain share by family --")
            for f, g in byfam.items():
                print(f"     {f:<10} {g/tot:>6.1%}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
