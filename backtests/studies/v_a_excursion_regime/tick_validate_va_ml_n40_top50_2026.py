"""Tick-validate N=40 top-50% ML overlay on 2026 OOS.

Pipeline:
1. Re-run N=40 monthly walk-forward (Jan-Mar 2024 feature selection,
   monthly retrain Apr 2024 - Apr 2026). Saves 2026 OOS predictions.
2. Determine the global top-50% threshold from COMBINED 2024+2025+2026
   OOS predictions (matches the reporting convention).
3. Filter 2026 trades: keep those with p_unr075 >= threshold.
4. Look up MBP-1 bid/ask at entry_ts and exit_ts for each kept trade.
5. Compute tick PnL (long: entry@ask, exit@bid; short: opposite)
   vs bar PnL (existing net_pnl from trades.parquet).
6. Report slippage decomposition.

Uses WITH-DELAY trades.parquet — entry_ts = bar1_close + 30s, which
matches the ML's T_F = T_E.
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
import pyarrow.parquet as pq
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

import importlib.util
spec = importlib.util.spec_from_file_location(
    "bar1plus30s",
    "studies/v_a_excursion_regime/ml_va_walkforward_bar1plus30s.py")
b30 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b30)


OUT = Path("studies/v_a_excursion_regime/results_v0")
NQ_MULT = 20.0
COMMISSION = 5.0     # one-way; doubled below
SEED = 42
VAL_FRAC = 0.20
N_FEATURES = 40
FS_END_MONTH = "2024-03"
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"
MBP1_PATHS = {
    1: "data/raw/NQ_v0_mbp1_2026_01.parquet",
    2: "data/raw/NQ_v0_mbp1_2026_02.parquet",
    3: "data/raw/NQ_v0_mbp1_2026_03.parquet",
    4: "data/raw/NQ_v0_mbp1_2026_04.parquet",
}


def load_mbp1_month(path):
    print(f"    loading {path}...", flush=True)
    df = pd.read_parquet(
        path, columns=["ts_event", "bid_px_00", "ask_px_00",
                          "bid_sz_00", "ask_sz_00"])
    print(f"      {len(df):,} quotes", flush=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def lookup_quotes_at(mbp_df, target_ts_array):
    """Last quote at or before each target timestamp.

    Returns DataFrame indexed 0..n-1 with bid, ask, quote_age_s, ok.
    """
    ts_idx = mbp_df["ts_event"].values.astype("int64")
    bid = mbp_df["bid_px_00"].values
    ask = mbp_df["ask_px_00"].values
    out = []
    for t in target_ts_array:
        j = np.searchsorted(ts_idx, np.int64(t), side="right") - 1
        if j < 0:
            out.append({"bid": np.nan, "ask": np.nan,
                          "quote_age_s": np.nan, "ok": False})
            continue
        b = float(bid[j]); a = float(ask[j])
        age_s = (int(t) - int(ts_idx[j])) / 1e9
        ok = (a > 0 and b > 0 and a > b
                and (a - b) < 5.0 and age_s < 300)
        out.append({"bid": b, "ask": a,
                      "quote_age_s": float(age_s), "ok": ok})
    return pd.DataFrame(out)


def run_n40_walkforward():
    """Stage 1: monthly walk-forward N=40, return all OOS predictions
    joined to trade-level info (entry_ts, exit_ts, direction, net_pnl).
    """
    print("=" * 78)
    print("STAGE 1 — N=40 monthly walk-forward")
    print("=" * 78)

    all_rows = []
    for yr in b30.YEARS:
        print(f"\n=== YEAR {yr} ===", flush=True)
        t0 = time.time()
        df = b30.load_bar1_trades_with_p30(yr)
        print(f"  V_A confirmed RTH: {len(df):,}  ({time.time()-t0:.0f}s)")
        all_rows.append(df)
    all_df = pd.concat(all_rows, ignore_index=True)
    n_pre = len(all_df)
    all_df = all_df.sort_values(["decision_ts", "year"]).drop_duplicates(
        subset=["decision_ts", "direction"], keep="first"
        ).reset_index(drop=True)
    print(f"\nDedupe: {n_pre:,} -> {len(all_df):,}")

    X_full = b30.make_feature_matrix(all_df)
    y = all_df["target_unr075"]
    pnl = all_df["net_pnl"]

    # Initial feature selection on Jan-Mar 2024
    ct = pd.to_datetime(all_df["decision_ts"], unit="ns", utc=True
                          ).dt.tz_convert("America/Chicago")
    yr_month = ct.dt.to_period("M")
    fs_mask = (yr_month <= FS_END_MONTH).to_numpy()
    X_fs_full = X_full[fs_mask]
    y_fs_full = y[fs_mask]
    fs_dts = all_df.loc[fs_mask, "decision_ts"].to_numpy()
    order = np.argsort(fs_dts, kind="mergesort")
    X_fs_full = X_fs_full.iloc[order].reset_index(drop=True)
    y_fs_full = y_fs_full.iloc[order].reset_index(drop=True)
    n_val = int(len(X_fs_full) * VAL_FRAC)
    n_tr = len(X_fs_full) - n_val
    fs_model = b30.fit_model(
        X_fs_full.iloc[:n_tr], y_fs_full.iloc[:n_tr],
        X_fs_full.iloc[n_tr:], y_fs_full.iloc[n_tr:])
    imp = pd.DataFrame({
        "feat": X_full.columns,
        "gain": fs_model.booster_.feature_importance(
            importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)
    top_feats = imp.head(N_FEATURES)["feat"].tolist()
    print(f"\nInitial top-{N_FEATURES} features selected on "
          f"{fs_mask.sum():,} Jan-Mar 2024 rows")

    X = X_full[top_feats]

    # Monthly walk-forward
    all_months = sorted(yr_month.unique())
    start_idx = next(i for i, m in enumerate(all_months)
                       if str(m) >= FIRST_SCORED_MONTH)
    oos_records = []
    print(f"\nWalk-forward retrains starting {all_months[start_idx]}...")
    for i in range(start_idx, len(all_months)):
        scoring_month = all_months[i]
        if str(scoring_month) > LAST_SCORED_MONTH:
            break
        train_mask = (yr_month < scoring_month).to_numpy()
        oos_mask = (yr_month == scoring_month).to_numpy()
        if train_mask.sum() < 500 or oos_mask.sum() < 20:
            continue
        X_tr_full = X[train_mask]
        y_tr_full = y[train_mask]
        train_dts = all_df.loc[train_mask, "decision_ts"].to_numpy()
        order = np.argsort(train_dts, kind="mergesort")
        X_tr_full = X_tr_full.iloc[order].reset_index(drop=True)
        y_tr_full = y_tr_full.iloc[order].reset_index(drop=True)
        n_val = int(len(X_tr_full) * VAL_FRAC)
        n_tr_only = len(X_tr_full) - n_val
        X_tr = X_tr_full.iloc[:n_tr_only]
        y_tr = y_tr_full.iloc[:n_tr_only]
        X_val = X_tr_full.iloc[n_tr_only:]
        y_val = y_tr_full.iloc[n_tr_only:]
        model = b30.fit_model(X_tr, y_tr, X_val, y_val)
        p_oos = model.predict_proba(X[oos_mask])[:, 1]
        # Pull trade-level info
        oos_rows = all_df[oos_mask].copy()
        oos_rows["p_unr075"] = p_oos
        oos_rows["scoring_month"] = str(scoring_month)
        oos_records.append(oos_rows)

    oos_all = pd.concat(oos_records, ignore_index=True)
    oos_all.to_parquet(OUT / "ml_n40_oos_preds_with_trades.parquet")
    print(f"  Wrote {len(oos_all):,} OOS rows with predictions")
    return oos_all


def tick_validate_2026(oos_all: pd.DataFrame):
    """Stage 2: filter to top 50% by global threshold, tick-validate
    the 2026 subset.
    """
    print(f"\n{'='*78}")
    print(f"STAGE 2 — Tick validation: N=40 top-50% on 2026 OOS")
    print(f"{'='*78}")

    # Global top-50% threshold from combined OOS
    thresh50 = oos_all["p_unr075"].quantile(0.50)
    print(f"\n  Global top-50% threshold (combined OOS): "
          f"p >= {thresh50:.4f}")

    # Filter to 2026 top 50%
    oos_2026 = oos_all[oos_all["year"] == 2026].copy().reset_index(drop=True)
    print(f"  2026 OOS total: {len(oos_2026):,}")
    print(f"  2026 baseline net_pnl: mean=${oos_2026['net_pnl'].mean():+.2f}  "
          f"total=${oos_2026['net_pnl'].sum():+,.0f}  "
          f"WR={(oos_2026['net_pnl']>0).mean():.1%}")
    kept = oos_2026[oos_2026["p_unr075"] >= thresh50].copy().reset_index(
        drop=True)
    print(f"\n  2026 top-50% (p >= {thresh50:.4f}): {len(kept):,} trades")
    print(f"  2026 top-50% bar net_pnl: "
          f"mean=${kept['net_pnl'].mean():+.2f}  "
          f"total=${kept['net_pnl'].sum():+,.0f}  "
          f"WR={(kept['net_pnl']>0).mean():.1%}")

    # Prepare timestamps for quote lookup
    kept["entry_dt"] = pd.to_datetime(
        kept["entry_ts"], unit="ns", utc=True)
    kept["exit_dt"] = pd.to_datetime(
        kept["exit_ts"], unit="ns", utc=True)
    kept["entry_month"] = kept["entry_dt"].dt.month
    kept["exit_month"] = kept["exit_dt"].dt.month
    print(f"\n  Entry-month distribution: "
          f"{kept['entry_month'].value_counts().sort_index().to_dict()}")

    # Load MBP-1 month by month, look up quotes
    entry_quotes = pd.DataFrame()
    exit_quotes = pd.DataFrame()
    months_needed = sorted(set(kept["entry_month"].unique())
                              | set(kept["exit_month"].unique()))
    for month in months_needed:
        if month not in MBP1_PATHS:
            print(f"  WARN: no MBP-1 file for month {month}")
            continue
        if not Path(MBP1_PATHS[month]).exists():
            print(f"  WARN: MBP-1 file missing on disk: "
                  f"{MBP1_PATHS[month]}")
            continue
        mbp = load_mbp1_month(MBP1_PATHS[month])
        entry_mask = kept["entry_month"] == month
        if entry_mask.sum() > 0:
            sub_idx = kept[entry_mask].index
            ts_arr = kept.loc[sub_idx, "entry_ts"].values
            res = lookup_quotes_at(mbp, ts_arr)
            res.index = sub_idx
            res.columns = [f"entry_{c}" for c in res.columns]
            entry_quotes = pd.concat([entry_quotes, res])
        exit_mask = kept["exit_month"] == month
        if exit_mask.sum() > 0:
            sub_idx = kept[exit_mask].index
            ts_arr = kept.loc[sub_idx, "exit_ts"].values
            res = lookup_quotes_at(mbp, ts_arr)
            res.index = sub_idx
            res.columns = [f"exit_{c}" for c in res.columns]
            exit_quotes = pd.concat([exit_quotes, res])
        del mbp

    kept = kept.join(entry_quotes).join(exit_quotes)
    long_mask = kept["direction"] == 1
    # Real fills: long enters at ask, exits at bid; short reversed
    kept["entry_fill_tick"] = np.where(
        long_mask, kept["entry_ask"], kept["entry_bid"])
    kept["exit_fill_tick"] = np.where(
        long_mask, kept["exit_bid"], kept["exit_ask"])
    kept["pts_tick"] = np.where(
        long_mask,
        kept["exit_fill_tick"] - kept["entry_fill_tick"],
        kept["entry_fill_tick"] - kept["exit_fill_tick"])
    kept["pnl_tick"] = kept["pts_tick"] * NQ_MULT - 2 * COMMISSION
    kept["pnl_bar"] = kept["net_pnl"]
    kept["slippage_per_trade"] = kept["pnl_bar"] - kept["pnl_tick"]

    bad_entry = ~kept["entry_ok"].fillna(False)
    bad_exit = ~kept["exit_ok"].fillna(False)
    valid = ~(bad_entry | bad_exit)

    print(f"\n=== HEADLINE — N=40 top-50% 2026 OOS ===")
    print(f"  Quote quality: bad entries={bad_entry.sum()}, "
          f"bad exits={bad_exit.sum()}, valid both={valid.sum()}/{len(kept)}")
    for sub_label, mask in [("ALL", kept.index),
                                ("Valid quotes", kept[valid].index)]:
        sub = kept.loc[mask]
        n = len(sub)
        if n == 0:
            continue
        bar_t = sub["pnl_bar"].sum()
        tick_t = sub["pnl_tick"].sum()
        bar_p = bar_t / n
        tick_p = tick_t / n
        slip = sub["slippage_per_trade"].sum()
        bar_wr = (sub["pnl_bar"] > 0).mean() * 100
        tick_wr = (sub["pnl_tick"] > 0).mean() * 100
        print(f"\n  {sub_label} (n={n:,})")
        print(f"    bar:  ${bar_t:>+10,.0f}  ${bar_p:>+8.2f}/tr  "
              f"WR={bar_wr:.1f}%")
        print(f"    tick: ${tick_t:>+10,.0f}  ${tick_p:>+8.2f}/tr  "
              f"WR={tick_wr:.1f}%")
        print(f"    Δ:    ${tick_t-bar_t:>+10,.0f}  "
              f"${(tick_p-bar_p):>+8.2f}/tr  "
              f"slip ${slip/n:+.2f}/tr")

    # Slippage decomposition (valid-quote subset)
    if valid.sum() > 0:
        v = kept[valid].copy()
        long_v = v["direction"] == 1
        # Approximate "entry slip vs bar fill" — bar fill was 1s OPEN
        # at entry_ts (no quote data); use fill_price as proxy
        v["entry_slip_$"] = np.where(
            long_v,
            (v["entry_fill_tick"] - v["fill_price"]) * NQ_MULT,
            (v["fill_price"] - v["entry_fill_tick"]) * NQ_MULT,
        )
        v["exit_slip_$"] = np.where(
            long_v,
            (v["exit_price"] - v["exit_fill_tick"]) * NQ_MULT,
            (v["exit_fill_tick"] - v["exit_price"]) * NQ_MULT,
        )
        print(f"\n  Slippage decomposition (valid quotes, n={len(v):,}):")
        print(f"    {'Component':<35}  {'Mean':>10}  {'Median':>9}  "
              f"{'p90':>9}  {'Max':>9}")
        for col, label in [("entry_slip_$", "Entry slip (pay above bar OPEN)"),
                            ("exit_slip_$", "Exit slip (sell below bar exit_price)")]:
            s = v[col]
            print(f"    {label:<35}  ${s.mean():>+8.2f}/tr  "
                  f"${s.median():>+7.2f}  ${s.quantile(0.9):>+7.2f}  "
                  f"${s.max():>+7.2f}")
        total_slip = v["slippage_per_trade"].mean()
        print(f"    {'Total':<35}  ${total_slip:>+8.2f}/tr")

    # Edge retention
    if valid.sum() > 0:
        v = kept[valid]
        bar_p = v["pnl_bar"].mean()
        tick_p = v["pnl_tick"].mean()
        if bar_p != 0:
            ret = tick_p / bar_p
            print(f"\n  Edge retention (valid quotes): "
                  f"{ret:.0%} (${tick_p:+.2f} tick / ${bar_p:+.2f} bar)")

    # Per-month breakdown
    print(f"\n  Per-month breakdown (valid quotes only):")
    print(f"    {'month':<7}  {'n':>4}  {'bar_$':>10}  "
          f"{'tick_$':>10}  {'slip':>9}")
    for month in sorted(months_needed):
        v_m = kept[(kept["entry_month"] == month) & valid]
        if len(v_m) == 0:
            continue
        print(f"    2026-{month:>02}  {len(v_m):>4}  "
              f"${v_m['pnl_bar'].sum():>+8,.0f}  "
              f"${v_m['pnl_tick'].sum():>+8,.0f}  "
              f"${v_m['slippage_per_trade'].sum():>+7,.0f}")

    out_path = OUT / "tick_validate_va_ml_n40_top50_2026.parquet"
    kept.to_parquet(out_path)
    print(f"\n  Saved: {out_path}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    oos_all = run_n40_walkforward()
    tick_validate_2026(oos_all)
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
