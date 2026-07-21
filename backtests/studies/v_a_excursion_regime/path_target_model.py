"""Clean final test — train the PATH target directly.

Distinct from flip_precision_check.py: that trained on `flip` and
evaluated on the +1/-1 path (proved flip-score does not predict
follow-through).  This trains directly on the path outcome, so the
model is free to DOWN-weight high-flip-score (marginal) candidates.

Target  (per T-1 candidate, +1.0/-1.0 ATR, 5-bar first-touch):
  primary  : 1 = +1 ATR before -1 ATR ; 0 = -1 before +1 ;
             NEITHER excluded from train and eval.
  sens     : 1 = +1 ATR first ; 0 = -1-ATR-first OR neither.

Universe : all T-1 candidates (not just known flips), 2020-2026.
Features : set_all  = the 20 on-stream log features
           set_geom = EMA-distance + flip-threshold-distance only.
Scopes   : pooled / long-only / short-only.
Validation: rolling 6m-train / 1m-deploy walk-forward.
Reports  : OOS AUC overall + by year; top-decile path win rate
           (within each year's OOS scores) — must lift meaningfully
           above 50% and hold year-by-year to pass.
"""
from __future__ import annotations
import os, sys, json, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

FEAT_LOG = Path("studies/v_a_excursion_regime/results_v0/live_feature_log")
FROZEN = Path("studies/v_a_excursion_regime/results_v0/frozen_t1")
POP = Path("studies/v_a_excursion_regime/results_v0/"
           "preflip_path_population.parquet")
NS = 1_000_000_000
WIN_BARS = 5
TRAIN_MONTHS = 6
SEED = 42
VAL_FRAC = 0.20


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


def rolling_oos(df, feats, target_col):
    """Rolling 6m/1m. Train rows must have target in {0,1}; rows with
    NaN target (excluded neither) are dropped from BOTH train & eval."""
    df = df.dropna(subset=[target_col]).sort_values(
        "close_ts_ns").reset_index(drop=True)
    months = sorted(df["ym"].unique())
    out = []
    for i in range(TRAIN_MONTHS, len(months)):
        dep = months[i]
        tr = df[df["ym"].isin(months[i - TRAIN_MONTHS:i])
                ].sort_values("close_ts_ns")
        de = df[df["ym"] == dep]
        if len(tr) < 400 or tr[target_col].nunique() < 2 or len(de) < 20:
            continue
        n_val = int(len(tr) * VAL_FRAC)
        n_tro = len(tr) - n_val
        if (tr.iloc[:n_tro][target_col].nunique() < 2
                or tr.iloc[n_tro:][target_col].nunique() < 2):
            continue
        m = fit_es(tr.iloc[:n_tro][feats], tr.iloc[:n_tro][target_col],
                   tr.iloc[n_tro:][feats], tr.iloc[n_tro:][target_col])
        sc = m.predict_proba(de[feats])[:, 1]
        o = de[["close_ts_ns", "year", target_col]].copy()
        o["score"] = sc
        out.append(o)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def report(name, oos, target_col):
    if len(oos) < 500:
        print(f"  [{name}] insufficient OOS ({len(oos)})")
        return
    auc_all = roc_auc_score(oos[target_col], oos["score"])
    base = oos[target_col].mean()
    print(f"\n  [{name}]  n={len(oos):,}  base win%={base:.1%}  "
          f"OOS AUC(all)={auc_all:.4f}")
    print(f"   {'year':<6}{'n':>8}{'base%':>8}{'AUC':>8}"
          f"{'topdec n':>10}{'topdec win%':>13}{'lift':>8}")
    aucs, decs = [], []
    for yr in range(2020, 2027):
        s = oos[oos["year"] == yr]
        if len(s) < 200 or s[target_col].nunique() < 2:
            continue
        auc = roc_auc_score(s[target_col], s["score"])
        b = s[target_col].mean()
        thr = s["score"].quantile(0.90)
        top = s[s["score"] >= thr]
        tw = top[target_col].mean() if len(top) else float("nan")
        aucs.append(auc); decs.append(tw)
        print(f"   {yr:<6}{len(s):>8,}{b:>7.1%}{auc:>8.4f}"
              f"{len(top):>10,}{tw:>12.1%}{tw-b:>+8.1%}")
    if aucs:
        print(f"   {'MEAN':<6}{'':>8}{'':>8}{np.mean(aucs):>8.4f}"
              f"{'':>10}{np.mean(decs):>12.1%}")


def main():
    t0 = time.time()
    logs = sorted(FEAT_LOG.glob("feat_*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in logs], ignore_index=True)
    pop = pd.read_parquet(POP)
    df = df.merge(pop[["close_ts_ns", "direction", "year", "entry_ok",
                       "ft_1.0_1.0", "at_1.0_1.0"]],
                  on=["close_ts_ns", "direction"], how="inner")
    df = df[df["entry_ok"]].copy()
    df["dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["ym"] = (df["dt"].dt.tz_convert("America/Chicago")
                .dt.to_period("M").astype(str))

    lim = WIN_BARS * 60 * NS
    ft = df["ft_1.0_1.0"].to_numpy()
    at = df["at_1.0_1.0"].to_numpy()
    win = (ft < at) & (ft <= lim)
    loss = (at <= ft) & (at <= lim)
    df["t_primary"] = np.where(win, 1.0,
                               np.where(loss, 0.0, np.nan))
    df["t_sens"] = win.astype(float)
    nb = (~win & ~loss).sum()
    print(f"Candidates (entry_ok): {len(df):,}  "
          f"win {win.sum():,}  loss {loss.sum():,}  neither {nb:,}")
    print(f"  primary base win% (resolved only): "
          f"{df['t_primary'].mean():.1%}")

    all_feats = json.loads((FROZEN / "feature_list.json").read_text())
    geom = [f for f in all_feats
            if f.startswith("dist_close_to_ema")
            or f.startswith("dist_to_1m_flip_threshold")]
    print(f"  set_all : {len(all_feats)} features")
    print(f"  set_geom: {len(geom)} features  {geom}")

    longs = df[df["direction"] == 1]
    shorts = df[df["direction"] == -1]

    for tcol, tname in [("t_primary", "PRIMARY (neither excluded)"),
                        ("t_sens", "SENSITIVITY (neither = 0)")]:
        print(f"\n{'='*72}\nTARGET: {tname}\n{'='*72}")
        for fname, feats in [("set_all", all_feats),
                             ("set_geom", geom)]:
            print(f"\n--- features: {fname} ---")
            report(f"pooled/{fname}",
                   rolling_oos(df, feats, tcol), tcol)
            report(f"long/{fname}",
                   rolling_oos(longs, feats, tcol), tcol)
            report(f"short/{fname}",
                   rolling_oos(shorts, feats, tcol), tcol)

    print(f"\n[done] {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
