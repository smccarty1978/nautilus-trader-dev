"""Offline flip-precision gate.

Question: can a geometry model trained on the RAW-FLIP target (a
genuine 1m regime flip occurs in intended direction d) lift flip-
precision enough that a fixed +1.0/-1.0 ATR bracket is profitable?

Rolling 6m-train / 1m-deploy walk-forward on the 20-feature live
feature log; target = `flip` (from preflip_path_population.parquet).
Strict causality: model for deploy-month M sees only months < M;
thresholds (entry quantiles) calibrated on the TRAIN window only.

For each OOS deploy month, score every candidate.  At a range of
TRAIN-calibrated selection thresholds, measure on the SELECTED set:
  - flip-precision (fraction that are genuine flips)
  - the ACTUAL +1.0/-1.0 ATR / 5-bar first-touch outcome -- this
    re-measures the flip-cohort path rate on the MODEL-SELECTED
    subset, not unconditionally
  - $ EV per trade with real per-trade ATR and $5 round-trip
    commission (win=+1ATR, loss=-1ATR, neither=flat; SL slippage and
    timeout drift NOT modelled -- optimistic, flag)

Gate: model-selected sets must clear EV>0 with margin across OOS
years (esp. 2026) before the NT +1/-1 bracket backtest is worth it.
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
NQ_MULT = 20.0
COMMISSION = 5.0          # $ round trip
TRAIN_MONTHS = 6
SEED = 42
VAL_FRAC = 0.20
WIN_BARS = 5
QUANTILES = [0.95, 0.90, 0.80, 0.70, 0.60, 0.50]   # top 5%..50%


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


def path_pnl(sub):
    """Per-trade $ PnL for a +1/-1 ATR, 5-bar bracket on a subset.

    Uses the population study's first-touch offsets. Returns a frame
    with outcome + pnl; rows with no valid entry are dropped.
    """
    sub = sub[sub["entry_ok"]].copy()
    ft = sub["ft_1.0_1.0"].to_numpy()
    at = sub["at_1.0_1.0"].to_numpy()
    limit = WIN_BARS * 60 * NS
    earlier = np.minimum(ft, at)
    win = (ft < at) & (ft <= limit)
    loss = (at <= ft) & (at <= limit)
    neither = earlier > limit
    one_atr = sub["atr_1m"].to_numpy() * NQ_MULT
    pnl = np.where(win, one_atr - COMMISSION,
                   np.where(loss, -one_atr - COMMISSION, -COMMISSION))
    sub["outcome"] = np.where(win, "win",
                              np.where(loss, "loss", "neither"))
    sub["pnl"] = pnl
    return sub


def main():
    t0 = time.time()
    feats = json.loads((FROZEN / "feature_list.json").read_text())

    logs = sorted(FEAT_LOG.glob("feat_*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in logs], ignore_index=True)
    pop = pd.read_parquet(POP)
    df = df.merge(pop[["close_ts_ns", "direction", "year", "pop", "flip",
                       "atr_1m", "entry_ok", "entry_px",
                       "ft_1.0_1.0", "at_1.0_1.0"]],
                  on=["close_ts_ns", "direction"], how="inner")
    df["dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["ym"] = df["dt"].dt.tz_convert("America/Chicago").dt.to_period("M")
    df["target"] = df["flip"].astype(np.int8)
    df = df.sort_values("close_ts_ns").reset_index(drop=True)
    print(f"Candidates: {len(df):,}  raw-flip rate {df['target'].mean():.1%}")

    # --- ungated baseline: +1/-1 bracket on ALL candidates by year ---
    print(f"\n{'='*70}\nUNGATED BASELINE  (+1/-1 ATR, 5-bar, $5 RT) "
          f"-- every candidate\n{'='*70}")
    base = path_pnl(df)
    print(f"  {'year':<6}{'n':>9}{'flip%':>8}{'win%':>8}{'loss%':>8}"
          f"{'$/trade':>10}{'$ total':>12}")
    for y, g in base.groupby("year"):
        print(f"  {y:<6}{len(g):>9,}{g['flip'].mean():>7.1%}"
              f"{(g['outcome']=='win').mean():>7.1%}"
              f"{(g['outcome']=='loss').mean():>7.1%}"
              f"{g['pnl'].mean():>10.2f}{g['pnl'].sum():>12,.0f}")

    # --- rolling walk-forward flip model ---
    months = sorted(df["ym"].unique())
    print(f"\n{'='*70}\nROLLING 6m-train / 1m-deploy flip model\n{'='*70}")
    oos = []
    aucs = []
    for i in range(TRAIN_MONTHS, len(months)):
        dep = months[i]
        tr = df[df["ym"].isin(months[i - TRAIN_MONTHS:i])
                ].sort_values("close_ts_ns")
        de = df[df["ym"] == dep]
        if len(tr) < 500 or tr["target"].sum() < 30 or len(de) < 20:
            continue
        n_val = int(len(tr) * VAL_FRAC)
        n_tro = len(tr) - n_val
        if tr.iloc[:n_tro]["target"].sum() < 15:
            continue
        m = fit_es(tr.iloc[:n_tro][feats], tr.iloc[:n_tro]["target"],
                   tr.iloc[n_tro:][feats], tr.iloc[n_tro:]["target"])
        # thresholds calibrated on TRAIN-PROPER scores only
        tr_sc = m.predict_proba(tr.iloc[:n_tro][feats])[:, 1]
        thr = {q: float(np.quantile(tr_sc, q)) for q in QUANTILES}
        sc = m.predict_proba(de[feats])[:, 1]
        o = de[["close_ts_ns", "direction", "year", "pop", "target",
                "atr_1m", "entry_ok", "ft_1.0_1.0",
                "at_1.0_1.0"]].copy()
        o["score"] = sc
        for q in QUANTILES:
            o[f"sel_{q}"] = sc >= thr[q]
        oos.append(o)
        if de["target"].nunique() > 1:
            aucs.append(roc_auc_score(de["target"], sc))
    oos = pd.concat(oos, ignore_index=True)
    print(f"  scored {len(oos):,} OOS candidates  "
          f"({oos['year'].min()}-{oos['year'].max()})")
    print(f"  mean per-deploy-month AUC: {np.mean(aucs):.4f}")

    # --- precision + path EV at each threshold, by year ---
    for q in QUANTILES:
        sel = oos[oos[f"sel_{q}"]]
        print(f"\n{'-'*70}")
        print(f"SELECTION: score >= train-q{q:.2f}  "
              f"(target top {(1-q)*100:.0f}%)   n={len(sel):,}  "
              f"flip-precision {sel['target'].mean():.1%}")
        print(f"{'-'*70}")
        ev = path_pnl(sel)
        print(f"  {'year':<6}{'n':>8}{'flip%':>8}{'win%':>8}{'loss%':>8}"
              f"{'neither%':>10}{'$/trade':>10}{'$ total':>12}")
        for y, g in ev.groupby("year"):
            print(f"  {y:<6}{len(g):>8,}{g['target'].mean():>7.1%}"
                  f"{(g['outcome']=='win').mean():>7.1%}"
                  f"{(g['outcome']=='loss').mean():>7.1%}"
                  f"{(g['outcome']=='neither').mean():>9.1%}"
                  f"{g['pnl'].mean():>10.2f}{g['pnl'].sum():>12,.0f}")
        allyr = ev
        print(f"  {'ALL':<6}{len(allyr):>8,}{allyr['target'].mean():>7.1%}"
              f"{(allyr['outcome']=='win').mean():>7.1%}"
              f"{(allyr['outcome']=='loss').mean():>7.1%}"
              f"{(allyr['outcome']=='neither').mean():>9.1%}"
              f"{allyr['pnl'].mean():>10.2f}{allyr['pnl'].sum():>12,.0f}")

    oos.to_parquet(FROZEN.parent / "flip_precision_oos.parquet",
                   index=False)
    print(f"\n[done] {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
