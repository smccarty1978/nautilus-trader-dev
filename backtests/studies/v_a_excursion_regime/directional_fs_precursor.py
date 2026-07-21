"""Per-direction feature-selection precursor.

Question: did pooled FS (which produced the 20-feature list) drop
features that matter for the SHORT side? If short-only FS picks
materially different top features, the full 97-feature rebuild is
justified; if short FS ~ pooled FS, the 20-feature list is fine and
we proceed with it.

FS on the 97-feature augmented candidate table (2024-2025), target =
label_T1 (V_A-confirmed flip — the deployment target). LightGBM gain
importance, ranked. Pooled vs long-only vs short-only.
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

CANDS = ("studies/v_a_excursion_regime/results_v0/"
            "pre_flip_candidates_augmented.parquet")
FROZEN = Path("studies/v_a_excursion_regime/results_v0/frozen_t1")
SEED = 42
VAL_FRAC = 0.20
TOPN = 25


def feature_columns(df):
    drop = set([
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        "candidate_direction",
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s", "close_3m", "close_5m",
        "vwap_value", "label_T1", "label_T2", "label_T3",
    ])
    feats = [c for c in df.columns if c not in drop]
    feats = [c for c in feats
              if df[c].dtype not in ("object", "datetime64[ns, UTC]")]
    return feats


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


def fs_rank(df, feats):
    """Gain-importance ranking via an early-stopped fit."""
    df = df.sort_values("close_ts_ns").reset_index(drop=True)
    n_val = int(len(df) * VAL_FRAC)
    n_tr = len(df) - n_val
    m = fit_es(df.iloc[:n_tr][feats], df.iloc[:n_tr]["label_T1"],
                  df.iloc[n_tr:][feats], df.iloc[n_tr:]["label_T1"])
    imp = pd.DataFrame({
        "feat": feats,
        "gain": m.booster_.feature_importance(importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    return imp


def main():
    t0 = time.time()
    pooled_20 = set(json.loads(
        (FROZEN / "feature_list.json").read_text()))

    df = pd.read_parquet(CANDS)
    df = df[df["year"].isin([2024, 2025])].copy()
    feats = feature_columns(df)
    print(f"Augmented candidates 2024-2025: {len(df):,}  "
          f"({len(feats)} features)")
    longs = df[df["candidate_direction"] == 1]
    shorts = df[df["candidate_direction"] == -1]
    print(f"  long candidates:  {len(longs):,}  "
          f"label_T1 rate {longs['label_T1'].mean():.1%}")
    print(f"  short candidates: {len(shorts):,}  "
          f"label_T1 rate {shorts['label_T1'].mean():.1%}")

    print(f"\nRunning FS (pooled / long / short)...")
    imp_pool = fs_rank(df, feats)
    imp_long = fs_rank(longs, feats)
    imp_short = fs_rank(shorts, feats)

    pool_top = imp_pool.head(TOPN)["feat"].tolist()
    long_top = imp_long.head(TOPN)["feat"].tolist()
    short_top = imp_short.head(TOPN)["feat"].tolist()

    # Side-by-side ranking
    print(f"\n{'='*92}")
    print(f"TOP-{TOPN} FEATURES BY GAIN  —  pooled / long-only / short-only")
    print(f"{'='*92}")
    print(f"  {'#':>3}  {'POOLED':<32} {'LONG-ONLY':<32} {'SHORT-ONLY':<32}")
    for i in range(TOPN):
        p = pool_top[i] if i < len(pool_top) else ""
        l = long_top[i] if i < len(long_top) else ""
        s = short_top[i] if i < len(short_top) else ""
        # mark short features not in pooled-20
        smark = " *" if s and s not in pooled_20 else ""
        print(f"  {i+1:>3}  {p:<32} {l:<32} {s+smark:<32}")

    # Key diagnostic: short top-N features NOT in the pooled-20
    short_new = [f for f in short_top if f not in pooled_20]
    long_new = [f for f in long_top if f not in pooled_20]
    print(f"\n{'='*92}")
    print(f"KEY DIAGNOSTIC — features in directional top-{TOPN} but "
          f"NOT in the deployed pooled-20")
    print(f"{'='*92}")
    print(f"  SHORT-only brings in {len(short_new)} features absent "
          f"from pooled-20:")
    for f in short_new:
        rank_s = short_top.index(f) + 1
        rank_p = (imp_pool["feat"].tolist().index(f) + 1
                     if f in imp_pool["feat"].tolist() else None)
        print(f"    {f:<38} short-rank {rank_s:>2}  "
              f"pooled-rank {rank_p}")
    print(f"\n  LONG-only brings in {len(long_new)} features absent "
          f"from pooled-20:")
    for f in long_new:
        rank_l = long_top.index(f) + 1
        print(f"    {f:<38} long-rank {rank_l:>2}")

    # Overlap stats
    short_top20 = set(short_top[:20])
    long_top20 = set(long_top[:20])
    print(f"\n{'='*92}")
    print(f"OVERLAP with deployed pooled-20")
    print(f"{'='*92}")
    print(f"  short-only top-20 vs pooled-20: "
          f"{len(short_top20 & pooled_20)}/20 shared")
    print(f"  long-only  top-20 vs pooled-20: "
          f"{len(long_top20 & pooled_20)}/20 shared")
    print(f"\n  Verdict guide: if short-only top-20 shares >=17/20 with"
          f" pooled-20,\n  the 20-feature list is adequate and the full"
          f" rebuild is NOT justified.\n  If <=14/20 shared (esp. with"
          f" high-rank new features), rebuild is justified.")

    imp_pool.to_csv(OUT_csv := "studies/v_a_excursion_regime/"
                       "results_v0/fs_pooled.csv", index=False)
    imp_long.to_csv("studies/v_a_excursion_regime/results_v0/"
                       "fs_long.csv", index=False)
    imp_short.to_csv("studies/v_a_excursion_regime/results_v0/"
                        "fs_short.csv", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
