"""Stage-2 path-quality ML filter on T-1 fires.

Target (path-based):
    1 = +PT_ATR touched BEFORE -SL_ATR within HORIZON_S seconds
    0 = -SL_ATR touched first OR neither within HORIZON_S

Defaults: PT=1.0 ATR, SL=1.5 ATR, horizon=300s.

Pipeline:
  1. Build path labels for ALL augmented candidates (using 1s OHLC).
  2. FS on Jan-Mar 2024 → top 30 features.
  3. Walk-forward train monthly with top 30 features.
  4. Save OOS predictions.
  5. Apply as filter on T-1 top-10% fires + threshold sweep.
  6. Evaluate baseline policy (+60s exit / VA hold-to-flip) on kept
     trades per year.

Reports per-threshold:
  - kept trades (out of T-1 top-10%)
  - VA-confirm retention rate
  - no-flip retention rate
  - $/tr per year (2024, 2025, 2026)
  - total combined PnL across all 3 years
"""
from __future__ import annotations
import os, sys, time, gc
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
from bracket_2025_2026 import (
    build_schedule, PRE_FLIP_OOS, COLLECTOR_DIR,
    TOP_QUANTILE, NQ_MULT, COMMISSION_RT,
)
from bracket_grid_2024_2025 import (
    load_year_bars_and_flips, apply_roll_filter_year,
)


OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/path_filter_ml")
PRE_FLIP_CANDIDATES = ("studies/v_a_excursion_regime/results_v0/"
                          "pre_flip_candidates_augmented.parquet")
PT_ATR_LABEL = 1.0
SL_ATR_LABEL = 1.5
HORIZON_S = 300
N_FEATURES = 30
SEED = 42
VAL_FRAC = 0.20
FS_END_MONTH = "2024-03"
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"


def build_path_labels_for_year(year, candidates_year_df):
    """Compute path labels using 1s OHLC bars for a year's candidates."""
    print(f"  building path labels for {year} "
          f"(n={len(candidates_year_df):,})...")
    t0 = time.time()
    bar_ts, bar_open, bar_high, bar_low, bar_close, _, _ = \
        load_year_bars_and_flips(year)
    print(f"    {len(bar_ts):,} bars loaded ({time.time()-t0:.0f}s)")

    labels = []
    for _, row in candidates_year_df.iterrows():
        cts = int(row["close_ts_ns"])
        d = int(row["candidate_direction"])
        atr = float(row["atr_1m"]) if "atr_1m" in row else None
        if atr is None or atr <= 0:
            labels.append(-1)
            continue
        entry_idx = int(np.searchsorted(bar_ts, cts, side="right"))
        if entry_idx >= len(bar_ts):
            labels.append(-1)
            continue
        entry_px = float(bar_open[entry_idx])
        end_ts = cts + HORIZON_S * 1_000_000_000
        end_idx = int(np.searchsorted(bar_ts, end_ts, side="right"))
        end_idx = min(end_idx, len(bar_ts))
        if end_idx <= entry_idx:
            labels.append(-1)
            continue
        h = bar_high[entry_idx:end_idx]
        l = bar_low[entry_idx:end_idx]
        if d == 1:
            pt_level = entry_px + PT_ATR_LABEL * atr
            sl_level = entry_px - SL_ATR_LABEL * atr
            pt_touch = h >= pt_level
            sl_touch = l <= sl_level
        else:
            pt_level = entry_px - PT_ATR_LABEL * atr
            sl_level = entry_px + SL_ATR_LABEL * atr
            pt_touch = l <= pt_level
            sl_touch = h >= sl_level
        pt_first = int(np.argmax(pt_touch)) if pt_touch.any() else -1
        sl_first = int(np.argmax(sl_touch)) if sl_touch.any() else -1
        if pt_first < 0 and sl_first < 0:
            labels.append(0)
        elif pt_first < 0:
            labels.append(0)
        elif sl_first < 0:
            labels.append(1)
        else:
            # Same-bar tie: pessimistic (SL first)
            if pt_first < sl_first:
                labels.append(1)
            else:
                labels.append(0)
    del bar_ts, bar_open, bar_high, bar_low, bar_close
    gc.collect()
    print(f"    done ({time.time()-t0:.0f}s)")
    return labels


def feature_columns(df):
    drop = set([
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s", "close_3m", "close_5m",
        "vwap_value",
        "label_T1", "label_T2", "label_T3",
        "path_label",
    ])
    feats = [c for c in df.columns if c not in drop]
    feats = [c for c in feats
              if df[c].dtype not in ("object", "datetime64[ns, UTC]")]
    return feats


def fit_model(X_tr, y_tr, X_val, y_val):
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


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: load candidates and build labels per year
    print("Step 1: Loading candidates + building path labels")
    cands = pd.read_parquet(PRE_FLIP_CANDIDATES)
    cands["close_dt"] = pd.to_datetime(cands["close_ts_ns"],
                                              unit="ns", utc=True)
    cands["year_month"] = (
        cands["close_dt"].dt.tz_convert("America/Chicago")
        ).dt.to_period("M")
    print(f"  Loaded {len(cands):,} augmented candidates")

    labels_path = OUT_DIR / "path_labels.parquet"
    if labels_path.exists():
        print(f"  Reusing existing labels at {labels_path}")
        label_df = pd.read_parquet(labels_path)
        cands = cands.merge(
            label_df[["close_ts_ns", "candidate_direction",
                        "path_label"]],
            on=["close_ts_ns", "candidate_direction"], how="left")
    else:
        all_labels = []
        for year in [2024, 2025, 2026]:
            yr_df = cands[cands["year"] == year].copy()
            labels = build_path_labels_for_year(year, yr_df)
            yr_df = yr_df[["close_ts_ns",
                              "candidate_direction"]].copy()
            yr_df["path_label"] = labels
            all_labels.append(yr_df)
        label_df = pd.concat(all_labels, ignore_index=True)
        # 2020-2023 candidates (pre-OOS): skip labeling (we don't
        # need them for training because we start FS in 2024)
        # but we still want them for full FS data. Let's set -1.
        label_df.to_parquet(labels_path, index=False)
        cands = cands.merge(
            label_df[["close_ts_ns", "candidate_direction",
                        "path_label"]],
            on=["close_ts_ns", "candidate_direction"], how="left")
        cands["path_label"] = cands["path_label"].fillna(-1).astype(
            "int64")

    # Filter to valid labels for training
    print(f"\n  Path label distribution (all years):")
    print(f"    {cands['path_label'].value_counts().sort_index().to_dict()}")
    valid = cands[cands["path_label"].isin([0, 1])].copy()
    print(f"  Valid (labeled) candidates: {len(valid):,}  "
          f"label-1 rate: {valid['path_label'].mean():.1%}")
    print(f"  ({time.time()-t0:.0f}s)")

    # Step 2: FS on Jan-Mar 2024
    print(f"\nStep 2: FS on Jan-Mar 2024 (target=path_label)")
    fs_mask = valid["year_month"] <= FS_END_MONTH
    fs_df = valid[fs_mask].sort_values("close_ts_ns").reset_index(
        drop=True)
    all_feats = feature_columns(fs_df)
    print(f"  Full feature count: {len(all_feats)}")
    n_val = int(len(fs_df) * VAL_FRAC)
    n_tr = len(fs_df) - n_val
    fs_model = fit_model(
        fs_df.iloc[:n_tr][all_feats], fs_df.iloc[:n_tr]["path_label"],
        fs_df.iloc[n_tr:][all_feats], fs_df.iloc[n_tr:]["path_label"])
    imp = pd.DataFrame({
        "feat": all_feats,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    top_feats = imp.head(N_FEATURES)["feat"].tolist()
    print(f"  Top 10 features:")
    for i, row in imp.head(10).iterrows():
        print(f"    {i+1:>2}. {row['feat']:<40} gain={row['gain']:>8.0f}")

    # Step 3: walk-forward training
    print(f"\nStep 3: Walk-forward train (N={N_FEATURES}, "
          f"target=path)")
    months = sorted(valid["year_month"].unique())
    start_idx = next(i for i, m in enumerate(months)
                       if str(m) >= FIRST_SCORED_MONTH)
    oos_records = []
    for i in range(start_idx, len(months)):
        scoring_month = months[i]
        if str(scoring_month) > LAST_SCORED_MONTH:
            break
        train_mask = valid["year_month"] < scoring_month
        oos_mask = valid["year_month"] == scoring_month
        if int(train_mask.sum()) < 500 or int(oos_mask.sum()) < 20:
            continue
        train_df = valid[train_mask].sort_values("close_ts_ns")
        n_val = int(len(train_df) * VAL_FRAC)
        n_tr_only = len(train_df) - n_val
        X_tr = train_df.iloc[:n_tr_only][top_feats]
        y_tr = train_df.iloc[:n_tr_only]["path_label"]
        X_val = train_df.iloc[n_tr_only:][top_feats]
        y_val = train_df.iloc[n_tr_only:]["path_label"]
        if y_tr.sum() < 5 or y_val.sum() < 1:
            continue
        model = fit_model(X_tr, y_tr, X_val, y_val)
        oos_df = valid[oos_mask]
        p_oos = model.predict_proba(oos_df[top_feats])[:, 1]
        for k in range(len(oos_df)):
            oos_records.append({
                "close_ts_ns": int(oos_df["close_ts_ns"].iloc[k]),
                "direction": int(oos_df["candidate_direction"].iloc[k]),
                "year": int(oos_df["year"].iloc[k]),
                "p_path": float(p_oos[k]),
                "path_label": int(oos_df["path_label"].iloc[k]),
            })
    oos = pd.DataFrame(oos_records)
    oos.to_parquet(OUT_DIR / "path_oos.parquet", index=False)
    print(f"  OOS predictions: {len(oos):,}  "
          f"({time.time()-t0:.0f}s)")

    # AUC by year
    for yr in [2024, 2025, 2026]:
        sub = oos[oos["year"] == yr]
        if len(sub) > 50 and sub["path_label"].nunique() > 1:
            auc = roc_auc_score(sub["path_label"], sub["p_path"])
            base = sub["path_label"].mean()
            print(f"    {yr} AUC={auc:.4f}  base rate={base:.1%}  "
                  f"n={len(sub):,}")

    # Step 4: Apply as filter on T-1 top-10% fires
    print(f"\nStep 4: Apply filter on T-1 top-10% fires")
    t1_oos = pd.read_parquet(
        "studies/v_a_excursion_regime/results_v0/"
        "pre_flip_T1_n20_oos.parquet")
    t1_thresh = t1_oos["p_score"].quantile(1 - TOP_QUANTILE)
    print(f"  T-1 top-10% threshold: p_T1 >= {t1_thresh:.4f}")
    t1_fires = t1_oos[t1_oos["p_score"] >= t1_thresh].copy()
    print(f"  T-1 fires: {len(t1_fires):,} "
          f"({(t1_fires['year']==2024).sum():,} / "
          f"{(t1_fires['year']==2025).sum():,} / "
          f"{(t1_fires['year']==2026).sum():,})")

    # Join path scores
    t1_fires = t1_fires.merge(
        oos[["close_ts_ns", "direction", "p_path", "path_label"]],
        on=["close_ts_ns", "direction"], how="left")
    print(f"  Missing path scores: "
          f"{t1_fires['p_path'].isna().sum():,}")
    t1_fires = t1_fires.dropna(subset=["p_path"]).copy()

    # Build per-year cohort with actual baseline PnL from 1s mode
    # For this, we need the existing baseline replay results
    print(f"\n  Computing baseline PnL per fire (1s mode)...")
    from bracket_2025_2026 import (
        replay_va_baseline_1s, replay_no_flip_baseline_1s,
    )
    fire_pnl_dfs = []
    for year in [2024, 2025, 2026]:
        yr_fires = t1_fires[t1_fires["year"] == year].copy()
        if len(yr_fires) == 0:
            continue
        # Build schedule for this year
        sched = build_schedule(
            t1_oos, year, t1_thresh,
            f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
            f"{COLLECTOR_DIR}/v_a_v0_{year}/"
            f"snapshots_with_vol_vwap.parquet")
        n_pre = len(sched)
        sched, n_drop = apply_roll_filter_year(sched, year)
        # Join path scores
        sched = sched.merge(
            oos[["close_ts_ns", "direction", "p_path"]],
            left_on=["close_ts_ns", "direction"],
            right_on=["close_ts_ns", "direction"],
            how="left")
        # Load bars
        bar_ts, bar_open, _, _, _, _, _ = load_year_bars_and_flips(
            year)
        rows = []
        for _, tr in sched.iterrows():
            d = int(tr["direction"])
            if bool(tr["is_va_confirm"]):
                r = replay_va_baseline_1s(
                    bar_ts, bar_open,
                    int(tr["entry_ts_ns"]),
                    int(tr["exit_ts_ns"]), d)
                if r is None:
                    continue
                r["is_va_confirm"] = True
            else:
                r = replay_no_flip_baseline_1s(
                    bar_ts, bar_open,
                    int(tr["entry_ts_ns"]), d)
                if r is None:
                    continue
                r["is_va_confirm"] = False
            r["close_ts_ns"] = int(tr["close_ts_ns"])
            r["direction"] = d
            r["p_path"] = tr["p_path"] if not pd.isna(
                tr["p_path"]) else np.nan
            r["year"] = year
            r["pnl_pts"] = (r["exit_fill_price"]
                                - r["entry_fill_price"]) * d
            r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION_RT
            rows.append(r)
        fire_pnl_dfs.append(pd.DataFrame(rows))
        del bar_ts, bar_open
        gc.collect()
        print(f"    {year}: {len(rows):,} fires evaluated "
              f"({time.time()-t0:.0f}s)")
    fire_pnl = pd.concat(fire_pnl_dfs, ignore_index=True)
    fire_pnl.to_parquet(OUT_DIR / "fire_baseline_pnl.parquet",
                            index=False)
    fire_pnl = fire_pnl.dropna(subset=["p_path"]).copy()

    # Step 5: Threshold sweep
    print(f"\n{'='*100}")
    print(f"Step 5: Threshold sweep on path filter")
    print(f"{'='*100}")

    THRESHOLDS = [0.0, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50,
                       0.55, 0.60, 0.65, 0.70]
    rows = []
    for thr in THRESHOLDS:
        kept = fire_pnl[fire_pnl["p_path"] >= thr].copy()
        if len(kept) == 0:
            continue
        # Per year
        year_stats = {}
        for yr in [2024, 2025, 2026]:
            sub = kept[kept["year"] == yr]
            year_stats[f"y{yr}_n"] = len(sub)
            year_stats[f"y{yr}_total"] = sub["net_pnl"].sum()
            year_stats[f"y{yr}_per_tr"] = (sub["net_pnl"].mean()
                                                  if len(sub) else 0)
        va_kept = kept[kept["is_va_confirm"]]
        nf_kept = kept[~kept["is_va_confirm"]]
        va_total = fire_pnl[fire_pnl["is_va_confirm"]]
        nf_total = fire_pnl[~fire_pnl["is_va_confirm"]]
        va_retention = (len(va_kept) / len(va_total)
                            if len(va_total) else 0)
        nf_retention = (len(nf_kept) / len(nf_total)
                            if len(nf_total) else 0)
        rows.append({
            "threshold": thr,
            "kept": len(kept),
            "skipped": len(fire_pnl) - len(kept),
            "va_retention": va_retention,
            "nf_retention": nf_retention,
            "total_pnl": kept["net_pnl"].sum(),
            "per_tr": kept["net_pnl"].mean(),
            **year_stats,
        })
    summary = pd.DataFrame(rows)
    summary.to_parquet(OUT_DIR / "threshold_sweep.parquet",
                          index=False)

    # Print summary
    print(f"  Baseline (no filter): "
          f"n={len(fire_pnl):,}  "
          f"total=${fire_pnl['net_pnl'].sum():+,.0f}  "
          f"$/tr=${fire_pnl['net_pnl'].mean():+.2f}")
    print(f"  VA-confirm: n={(fire_pnl['is_va_confirm']).sum():,}  "
          f"No-flip: n={(~fire_pnl['is_va_confirm']).sum():,}")
    print()
    print(f"  {'Thr':<6} {'kept':>5} {'VA%':>6} {'NF%':>6} "
          f"{'tot$':>10} {'$/tr':>9} | "
          f"{'2024 $':>9} {'24/tr':>7} | "
          f"{'2025 $':>9} {'25/tr':>7} | "
          f"{'2026 $':>9} {'26/tr':>7}")
    for _, r in summary.iterrows():
        print(f"  {r['threshold']:<6.2f} {int(r['kept']):>5} "
              f"{r['va_retention']:>5.1%} {r['nf_retention']:>5.1%} "
              f"${r['total_pnl']:>+7,.0f} ${r['per_tr']:>+7.2f} | "
              f"${r['y2024_total']:>+7,.0f} ${r['y2024_per_tr']:>+5.2f} | "
              f"${r['y2025_total']:>+7,.0f} ${r['y2025_per_tr']:>+5.2f} | "
              f"${r['y2026_total']:>+7,.0f} ${r['y2026_per_tr']:>+5.2f}")

    # Best threshold by min-year $/tr
    summary["min_yr_per_tr"] = summary[[
        "y2024_per_tr", "y2025_per_tr", "y2026_per_tr"]].min(axis=1)
    best = summary.sort_values("min_yr_per_tr",
                                     ascending=False).head(3)
    print(f"\n  Top 3 by worst-year $/tr (robustness criterion):")
    for _, r in best.iterrows():
        print(f"    thr={r['threshold']:.2f}  "
              f"min-yr $/tr=${r['min_yr_per_tr']:+.2f}  "
              f"3-yr total=${r['total_pnl']:+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
