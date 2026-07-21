"""Controlled directional-model test (final ML salvage).

Hypothesis: a pooled model is dominated by long-side structure; a
short-only model may carry signal the pooled model suppresses.

Four directional model families + a pooled baseline, all rolling
walk-forward (6m train / 1m deploy, strict months<M causality):
  long-A   : long candidates,  Target A (raw flip to +1 next bar)
  short-A  : short candidates, Target A (raw flip to -1 next bar)
  long-B   : long candidates,  Target B (flip to +1 AND bar1 confirm)
  short-B  : short candidates, Target B (flip to -1 AND bar1 confirm)
  pooled-B : all candidates,   Target B  (the incumbent T-1 model)

Phase 1 (this script) — MODEL DIAGNOSTICS only:
  - AUC by direction by year
  - top-decile lift (positive-rate enrichment) by direction by year
  - the key comparison: does short-B beat pooled-B *on short
    candidates*?  does long-B beat pooled-B on longs?

Phase 2 (live strategy PnL) is gated on Phase 1 showing real signal.
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

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from rolling_train import build_1m_bars, compute_1m_regime

NS = 1_000_000_000
FEAT_LOG_DIR = Path("studies/v_a_excursion_regime/results_v0/"
                       "live_feature_log")
FROZEN = Path("studies/v_a_excursion_regime/results_v0/frozen_t1")
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
    """Rolling 6m-train/1m-deploy. Returns df with an 'oos_score'
    column for every row in a scored deploy month."""
    df = df.sort_values("close_ts_ns").reset_index(drop=True)
    months = sorted(df["ym"].unique())
    out = []
    for i in range(TRAIN_MONTHS, len(months)):
        dep = months[i]
        tr = df[df["ym"].isin(months[i - TRAIN_MONTHS:i])
                   ].sort_values("close_ts_ns")
        de = df[df["ym"] == dep]
        if len(tr) < 300 or tr[target_col].sum() < 15 or len(de) < 10:
            continue
        n_val = int(len(tr) * VAL_FRAC)
        n_tro = len(tr) - n_val
        if n_val < 30 or tr.iloc[:n_tro][target_col].sum() < 5:
            continue
        m = fit_es(tr.iloc[:n_tro][feats], tr.iloc[:n_tro][target_col],
                      tr.iloc[n_tro:][feats], tr.iloc[n_tro:][target_col])
        sc = m.predict_proba(de[feats])[:, 1]
        o = de[["close_ts_ns", "direction", "year",
                   target_col]].copy()
        o["oos_score"] = sc
        out.append(o)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def diag(name, oos, target_col):
    """AUC + top-decile lift by year."""
    print(f"\n  [{name}]  n={len(oos):,}  "
          f"base rate={oos[target_col].mean():.1%}")
    print(f"  {'year':<6} {'n':>6} {'base':>7} {'AUC':>7} "
          f"{'top10 rate':>11} {'lift':>7}")
    rows = []
    for yr in range(2020, 2027):
        s = oos[oos["year"] == yr]
        if len(s) < 100 or s[target_col].nunique() < 2:
            continue
        auc = roc_auc_score(s[target_col], s["oos_score"])
        base = s[target_col].mean()
        thr = s["oos_score"].quantile(0.90)
        top = s[s["oos_score"] >= thr]
        toprate = top[target_col].mean() if len(top) else 0
        lift = toprate / base if base > 0 else 0
        rows.append((yr, len(s), base, auc, toprate, lift))
        print(f"  {yr:<6} {len(s):>6} {base:>6.1%} {auc:>7.4f} "
              f"{toprate:>10.1%} {lift:>6.2f}x")
    if rows:
        aucs = [r[3] for r in rows]
        lifts = [r[5] for r in rows]
        print(f"  {'MEAN':<6} {'':>6} {'':>7} "
              f"{np.mean(aucs):>7.4f} {'':>11} "
              f"{np.mean(lifts):>6.2f}x")
    return rows


def main():
    t0 = time.time()
    feats = json.loads((FROZEN / "feature_list.json").read_text())

    df = pd.concat([pd.read_parquet(p)
                       for p in sorted(FEAT_LOG_DIR.glob("feat_*.parquet"))],
                      ignore_index=True)
    df["dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["ym"] = (df["dt"].dt.tz_convert("America/Chicago")
                  ).dt.to_period("M")
    df["year"] = df["dt"].dt.year
    print(f"Feature-log candidates: {len(df):,}  "
          f"long={int((df['direction']==1).sum()):,}  "
          f"short={int((df['direction']==-1).sum()):,}")

    # --- Targets A (raw flip) and B (flip + confirm) ---
    print("Computing Target A (raw flip) and Target B (flip+confirm)...")
    bars1m = {}
    for y in range(2020, 2027):
        try:
            bars1m[y] = build_1m_bars(y)
        except FileNotFoundError:
            pass
    one_m = pd.concat(bars1m.values()).sort_index()
    om_h, om_l = one_m["high"].values, one_m["low"].values
    om_o, om_c = one_m["open"].values, one_m["close"].values
    om_reg = compute_1m_regime(one_m)
    idx = {int(t): i for i, t in enumerate(one_m.index.values)}

    A = np.zeros(len(df), dtype=np.int8)
    B = np.zeros(len(df), dtype=np.int8)
    for k in range(len(df)):
        cts = int(df["close_ts_ns"].iat[k])
        d = int(df["direction"].iat[k])
        fb = idx.get(cts, -1)
        b1 = idx.get(cts + 60 * NS, -1)
        if fb < 1:
            continue
        flip = (om_reg[fb] == d and om_reg[fb - 1] != 0
                   and om_reg[fb] != om_reg[fb - 1])
        if not flip:
            continue
        A[k] = 1
        if b1 < 0:
            continue
        if d == 1:
            conf = om_h[b1] > om_h[fb] and om_c[b1] > om_o[b1]
        else:
            conf = om_l[b1] < om_l[fb] and om_c[b1] < om_o[b1]
        B[k] = 1 if conf else 0
    df["target_A"] = A
    df["target_B"] = B
    print(f"  Target A rate: {A.mean():.1%}  "
          f"Target B rate: {B.mean():.1%}")

    longs = df[df["direction"] == 1].copy()
    shorts = df[df["direction"] == -1].copy()

    print(f"\n{'='*70}")
    print(f"ROLLING WALK-FORWARD — model diagnostics by family")
    print(f"{'='*70}")

    results = {}
    results["long-A"] = rolling_oos(longs, feats, "target_A")
    diag("long-A  (raw flip, long)", results["long-A"], "target_A")
    results["short-A"] = rolling_oos(shorts, feats, "target_A")
    diag("short-A (raw flip, short)", results["short-A"], "target_A")
    results["long-B"] = rolling_oos(longs, feats, "target_B")
    diag("long-B  (flip+confirm, long)", results["long-B"], "target_B")
    results["short-B"] = rolling_oos(shorts, feats, "target_B")
    diag("short-B (flip+confirm, short)", results["short-B"],
            "target_B")
    results["pooled-B"] = rolling_oos(df, feats, "target_B")
    diag("pooled-B (flip+confirm, all dirs)", results["pooled-B"],
            "target_B")

    # --- KEY COMPARISON: directional vs pooled, on each direction ---
    print(f"\n{'='*70}")
    print(f"KEY COMPARISON — does a directional model beat pooled?")
    print(f"{'='*70}")
    pб = results["pooled-B"]
    for d, name, dir_res in [(1, "LONG", results["long-B"]),
                                  (-1, "SHORT", results["short-B"])]:
        pooled_on_dir = pб[pб["direction"] == d]
        if len(pooled_on_dir) > 100 and len(dir_res) > 100:
            auc_pooled = roc_auc_score(pooled_on_dir["target_B"],
                                              pooled_on_dir["oos_score"])
            auc_dir = roc_auc_score(dir_res["target_B"],
                                          dir_res["oos_score"])
            print(f"  {name}: pooled-B model AUC {auc_pooled:.4f}  "
                  f"vs {name.lower()}-only-B AUC {auc_dir:.4f}  "
                  f"-> delta {auc_dir - auc_pooled:+.4f}")

    for name, r in results.items():
        if len(r):
            r.to_parquet(
                f"studies/v_a_excursion_regime/results_v0/"
                f"dirmodel_oos_{name}.parquet", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
