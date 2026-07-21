"""Score the N=40 bar1+30s ML model AT EACH path_checkpoint during
top-50% trades. Track score trajectory vs MFE/PnL evolution.

Question: as MFE rises, does the model see it? As MFE peaks, does the
model score drop before the regime-flip exit?

Approach:
  - Train one model on Jan-Mar 2024 trades (the initial FS data).
    Skip trades that fall in this window for the analysis.
  - For each top-50% trade, iterate over its path_checkpoint snapshots.
  - At each path_checkpoint, build the 40-feature vector by:
    (a) Time-varying features from the path_checkpoint row itself
        (multi-TF state, vol/VWAP, calendar at that moment)
    (b) FIXED features joined from the original bar1_check row
        (bar1 shape, flip bar shape, p30_*)
  - Score with the model -> p_unr075_during_trade
  - Aggregate by trade outcome class:
      A = reach PT AND won at flip (continuation)
      B = reach PT BUT lost at flip (V-shape)
      C = didn't reach PT (mostly losers)

For each (class, elapsed_s_bucket): mean p_unr075, mean cur_mfe_atr.

If the model has online predictive power, Class B's score should
DROP relative to Class A as MFE peaks and reverses.
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

import importlib.util
spec = importlib.util.spec_from_file_location(
    "bar1plus30s",
    "studies/v_a_excursion_regime/ml_va_walkforward_bar1plus30s.py")
b30 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b30)


OUT = Path("studies/v_a_excursion_regime/results_v0")
SEED = 42
VAL_FRAC = 0.20
N_FEATURES = 40
FS_END_MONTH = "2024-03"

# Path_checkpoint elapsed_s buckets we'll evaluate at
CHECKPOINT_BUCKETS = [30, 60, 90, 120, 180, 240, 300, 420, 600, 900,
                       1200, 1800]


def build_feature_matrix_for_pcs(pcs_df: pd.DataFrame,
                                       bar1_df: pd.DataFrame) -> pd.DataFrame:
    """Build the same feature matrix as bar1+30s ML, but with
    time-varying features coming from path_checkpoint snapshots and
    FIXED features (flip bar shape, bar1 shape, p30_*) joined from the
    associated bar1_check row.

    pcs_df: path_checkpoint rows with their own decision_ts and time-
            varying features.
    bar1_df: bar1_check rows (with p30_* already computed in
             load_bar1_trades_with_p30) for the SAME trades.
    Both indexed by trade key = (entry_ts of original trade, direction).
    """
    # bar1_df is keyed by decision_ts of bar1_check (= bar1+1s).
    # path_checkpoint.trade_fill_ts maps to original trade entry_ts.
    # trade.decision_ts (in trades.parquet) == bar1_check.decision_ts.
    # We need a way to link path_checkpoint -> bar1_check.

    # The linkage: bar1_df has decision_ts (= bar1+1s) which equals the
    # trade's decision_ts. Each path_checkpoint has trade_fill_ts which
    # is the trade's entry_ts. Since entry_ts = decision_ts + 29s in
    # with-delay data, we can compute decision_ts from trade_fill_ts.
    pcs = pcs_df.copy().reset_index(drop=True)
    # Compute the corresponding bar1_check decision_ts:
    # entry_ts - 29s for with-delay. But more robust: use the trade's
    # decision_ts from a passed lookup. Here we just use bar1_df keyed
    # by (decision_ts_of_bar1check, direction) and pcs is keyed by
    # the trade's decision_ts which equals bar1_check.decision_ts.
    # Since pcs has trade_fill_ts and bar1_df has decision_ts, we need
    # the link. For with-delay data: trade_fill_ts = decision_ts + 29s.
    pcs["_bar1ck_dts"] = pcs["trade_fill_ts"] - 29_000_000_000

    # JOIN the FIXED features from bar1_df
    fixed_cols = [
        "flip_bar_h", "flip_bar_l", "flip_bar_c",
        "bar1_h", "bar1_l", "bar1_o", "bar1_c",
    ]
    p30_cols = [c for c in bar1_df.columns if c.startswith("p30_")]
    # Use trade_direction from pcs since direction in pcs may be 0
    pcs["direction"] = pcs["trade_direction"]
    # Drop NaN-only bar1/flip_bar columns from pcs before merge so we
    # don't get _x/_y suffixes (path_checkpoint rows have these as NaN).
    drop_pcs_cols = [c for c in fixed_cols + p30_cols if c in pcs.columns]
    if drop_pcs_cols:
        pcs = pcs.drop(columns=drop_pcs_cols)
    bar1_sub = bar1_df[["decision_ts", "direction"] + fixed_cols + p30_cols
                          ].copy()
    bar1_sub = bar1_sub.rename(columns={"decision_ts": "_bar1ck_dts"})
    pcs = pcs.merge(bar1_sub, on=["_bar1ck_dts", "direction"], how="left")

    # Verify the join populated bar1 fields
    miss = pcs["bar1_h"].isna().sum()
    if miss > 0:
        print(f"  WARN: {miss} path_checkpoints failed bar1 join")

    # Apply the bar1+30s make_feature_matrix logic. It expects
    # decision_ts, atr_1m, direction, flip_bar/bar1 raw, plus snapshot
    # multi-TF state and vol/VWAP. All present after join.
    pcs["atr_at_signal"] = pcs["trade_atr_at_signal"]
    X = b30.make_feature_matrix(pcs)
    return pcs, X


def main():
    t0 = time.time()
    print("=" * 78)
    print("ML SCORE TRAJECTORY DURING TRADE  (top 50% N=40)")
    print("=" * 78)

    # Load top-50% analyzed trades
    top50_df = pd.read_parquet(OUT / "ml_n40_top50_mfe_analysis.parquet")
    print(f"\nTop-50% trades: {len(top50_df):,}")

    # Identify outcome classes
    top50_df["class"] = np.where(
        top50_df["reached_pt"] & top50_df["won_at_flip"], "A_cont_win",
        np.where(
            top50_df["reached_pt"] & ~top50_df["won_at_flip"], "B_vshape",
            "C_no_pt"))
    print(f"\n  Outcome class breakdown:")
    print(top50_df["class"].value_counts().to_string())

    # Load all snapshots and trades, build bar1_check feature set
    print(f"\nLoading bar1_check features with p30_* (with-delay)...")
    bar1_all = []
    for yr in [2024, 2025, 2026]:
        df = b30.load_bar1_trades_with_p30(yr)
        bar1_all.append(df)
    bar1_df = pd.concat(bar1_all, ignore_index=True)
    bar1_df = bar1_df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset=["decision_ts", "direction"], keep="first"
        ).reset_index(drop=True)
    print(f"  bar1_check rows: {len(bar1_df):,}")

    # Train initial model on Jan-Mar 2024 bar1_check (same as N=40 FS)
    print(f"\nTraining initial model on Jan-Mar 2024 bar1_check rows...")
    X_b1 = b30.make_feature_matrix(bar1_df)
    y_b1 = bar1_df["target_unr075"]
    ct = pd.to_datetime(bar1_df["decision_ts"], unit="ns", utc=True
                          ).dt.tz_convert("America/Chicago")
    yr_month = ct.dt.to_period("M")
    fs_mask = (yr_month <= FS_END_MONTH).to_numpy()
    X_fs = X_b1[fs_mask]
    y_fs = y_b1[fs_mask]
    fs_dts = bar1_df.loc[fs_mask, "decision_ts"].to_numpy()
    order = np.argsort(fs_dts, kind="mergesort")
    X_fs = X_fs.iloc[order].reset_index(drop=True)
    y_fs = y_fs.iloc[order].reset_index(drop=True)
    n_val = int(len(X_fs) * VAL_FRAC)
    n_tr = len(X_fs) - n_val
    fs_model = b30.fit_model(
        X_fs.iloc[:n_tr], y_fs.iloc[:n_tr],
        X_fs.iloc[n_tr:], y_fs.iloc[n_tr:])
    imp = pd.DataFrame({
        "feat": X_b1.columns,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    top_feats = imp.head(N_FEATURES)["feat"].tolist()
    print(f"  Selected top-{N_FEATURES} features")

    # Final model trained on Jan-Mar 2024 with N=40 features
    X_fs_sub = X_b1[top_feats][fs_mask]
    X_fs_sub = X_fs_sub.iloc[order].reset_index(drop=True)
    model = b30.fit_model(
        X_fs_sub.iloc[:n_tr], y_fs.iloc[:n_tr],
        X_fs_sub.iloc[n_tr:], y_fs.iloc[n_tr:])
    print(f"  best_iter={model.best_iteration_}")

    # Load all path_checkpoint snapshots from with-delay data
    print(f"\nLoading path_checkpoints (with-delay)...")
    pcs_list = []
    for yr in [2024, 2025, 2026]:
        snap = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet")
        pcs = snap[(snap["kind"] == "path_checkpoint")
                    & (snap["session"] == "RTH")].copy()
        pcs["year"] = yr
        pcs_list.append(pcs)
    pcs_all = pd.concat(pcs_list, ignore_index=True)
    print(f"  Total path_checkpoints: {len(pcs_all):,}")

    # Filter to checkpoints belonging to top-50% trades
    # Link: pcs.trade_fill_ts == top50.entry_ts
    top50_keys = top50_df[["entry_ts", "direction", "class"]].copy()
    top50_keys = top50_keys.rename(columns={
        "entry_ts": "trade_fill_ts", "direction": "trade_direction"})
    pcs_top50 = pcs_all.merge(
        top50_keys, on=["trade_fill_ts", "trade_direction"], how="inner")
    print(f"  path_checkpoints for top-50% trades: {len(pcs_top50):,}")

    # Build features and score
    print(f"\nBuilding features at each path_checkpoint and scoring...")
    pcs_top50, X_pcs_full = build_feature_matrix_for_pcs(
        pcs_top50, bar1_df)
    # Restrict to top-40 features (and align order to model's expectation)
    X_pcs = X_pcs_full[top_feats]
    print(f"  Feature matrix at path_checkpoints: {X_pcs.shape}")
    # Skip rows with NaN in any feature (typically from join misses)
    valid = X_pcs.notna().all(axis=1)
    print(f"  Valid rows (no NaN): {valid.sum():,} / {len(X_pcs):,}")
    p_score = np.full(len(pcs_top50), np.nan)
    if valid.sum() > 0:
        p_score_valid = model.predict_proba(X_pcs[valid])[:, 1]
        p_score[valid.values] = p_score_valid
    pcs_top50["p_score"] = p_score

    # Save for downstream
    pcs_top50.to_parquet(
        OUT / "ml_score_trajectory_during_trade.parquet")

    # Aggregate by (class, elapsed_s_bucket)
    # Bucket elapsed_s to nearest CHECKPOINT_BUCKETS value
    def bucketize(s):
        nearest = min(CHECKPOINT_BUCKETS,
                       key=lambda b: abs(b - s)) if not pd.isna(s) else np.nan
        return nearest
    pcs_top50["e_bucket"] = pcs_top50["elapsed_s"].apply(bucketize)

    print(f"\n{'='*78}")
    print(f"MEAN p_score BY (class, elapsed_s_bucket)")
    print(f"{'='*78}")
    grp = pcs_top50.groupby(["class", "e_bucket"]).agg(
        n=("p_score", "size"),
        mean_p=("p_score", "mean"),
        mean_mfe_atr=("cur_mfe_atr", "mean"),
        mean_pnl_atr=("cur_pnl_atr", "mean"),
    ).reset_index()
    # Pivot for readability
    pvt_p = grp.pivot(index="e_bucket", columns="class",
                          values="mean_p").round(4)
    pvt_mfe = grp.pivot(index="e_bucket", columns="class",
                            values="mean_mfe_atr").round(3)
    pvt_n = grp.pivot(index="e_bucket", columns="class",
                          values="n")

    print(f"\n  Mean p_score (model confidence):")
    print(pvt_p.to_string())
    print(f"\n  Mean cur_mfe_atr:")
    print(pvt_mfe.to_string())
    print(f"\n  N (path_checkpoints per cell):")
    print(pvt_n.to_string())

    # Differential: how does score evolve from entry to mid-trade?
    print(f"\n{'='*78}")
    print(f"SCORE EVOLUTION (Δ from +30s bucket)")
    print(f"{'='*78}")
    if 30 in pvt_p.index:
        base_30 = pvt_p.loc[30]
        delta = pvt_p.subtract(base_30, axis=1)
        print(delta.to_string())

    # Cross-class comparison at each bucket
    print(f"\n{'='*78}")
    print(f"CROSS-CLASS DIFFERENCE (Class A - Class B at each bucket)")
    print(f"{'='*78}")
    if "A_cont_win" in pvt_p.columns and "B_vshape" in pvt_p.columns:
        d_ab = pvt_p["A_cont_win"] - pvt_p["B_vshape"]
        d_ac = pvt_p["A_cont_win"] - pvt_p["C_no_pt"]
        d_bc = pvt_p["B_vshape"] - pvt_p["C_no_pt"]
        print(f"  {'bucket_s':>8}  {'A-B':>7}  {'A-C':>7}  {'B-C':>7}")
        for b in sorted(pvt_p.index):
            print(f"  {b:>8}  {d_ab.get(b, np.nan):>+7.4f}  "
                  f"{d_ac.get(b, np.nan):>+7.4f}  "
                  f"{d_bc.get(b, np.nan):>+7.4f}")

    # Score-vs-MFE correlation within each class
    print(f"\n{'='*78}")
    print(f"CORRELATION (p_score vs cur_mfe_atr) — by class")
    print(f"{'='*78}")
    for cls in pcs_top50["class"].unique():
        sub = pcs_top50[(pcs_top50["class"] == cls)
                          & pcs_top50["p_score"].notna()
                          & pcs_top50["cur_mfe_atr"].notna()]
        if len(sub) > 50:
            corr = sub[["p_score", "cur_mfe_atr"]].corr().iloc[0, 1]
            print(f"  {cls}: n={len(sub):,}  corr(p_score, cur_mfe_atr)={corr:+.4f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")
    print(f"\nSaved: {OUT / 'ml_score_trajectory_during_trade.parquet'}")


if __name__ == "__main__":
    main()
