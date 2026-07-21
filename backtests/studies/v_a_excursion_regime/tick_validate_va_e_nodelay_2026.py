"""Tick-validate no-delay E on 2026 OOS using MBP-1.

E (no-delay V_A): delayed entry @+7m + dual momentum filter
  alive @+7m AND
  f_net_move_150s_7m >= IS-q10 AND
  f_net_move_300s_7m >= IS-q20

Uses checkpoint_features_nodelay.parquet built from no-delay V_A
trades.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
COMMISSION = 5.0
DELAY_S = 420   # +7m for E

OUT = Path("studies/v_a_excursion_regime/results_v0")
MBP1_PATHS = {
    1: "data/raw/NQ_v0_mbp1_2026_01.parquet",
    2: "data/raw/NQ_v0_mbp1_2026_02.parquet",
    3: "data/raw/NQ_v0_mbp1_2026_03.parquet",
    4: "data/raw/NQ_v0_mbp1_2026_04.parquet",
}


def load_mbp1_month(path):
    print(f"  loading {path}...", flush=True)
    df = pd.read_parquet(
        path, columns=["ts_event", "bid_px_00", "ask_px_00",
                          "bid_sz_00", "ask_sz_00"])
    print(f"    {len(df):,} quotes", flush=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def lookup_quotes_at(mbp_df, target_ts_array):
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


def main():
    t0 = time.time()
    print("=" * 78)
    print("TICK VALIDATION — NO-DELAY E on 2026 OOS")
    print("=" * 78)

    feats = pd.read_parquet(OUT / "checkpoint_features_nodelay.parquet")
    feats = feats.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)

    is_alive_7m = feats[feats["alive_7m"]
                          & feats["year"].isin([2024, 2025])
                          & feats["f_net_move_150s_7m"].notna()
                          & feats["f_net_move_300s_7m"].notna()]
    thr_150 = is_alive_7m["f_net_move_150s_7m"].quantile(0.10)
    thr_300 = is_alive_7m["f_net_move_300s_7m"].quantile(0.20)
    print(f"\n  no-delay E filters:")
    print(f"    f_net_move_150s_7m >= ${thr_150:.2f}")
    print(f"    f_net_move_300s_7m >= ${thr_300:.2f}")

    e_pop = feats[feats["alive_7m"]
                    & (feats["f_net_move_150s_7m"] >= thr_150)
                    & (feats["f_net_move_300s_7m"] >= thr_300)].copy()
    e_2026 = e_pop[e_pop["year"] == 2026].copy()
    e_2026 = e_2026.sort_values("entry_ts").reset_index(drop=True)
    e_2026 = e_2026.rename(columns={"fill_px": "fill_price",
                                          "exit_px": "exit_price"})
    print(f"\n  no-delay E 2026 OOS cohort: {len(e_2026):,} trades")

    e_2026["entry_ts_E"] = e_2026["entry_ts"] + DELAY_S * 1_000_000_000
    e_2026["entry_dt"] = pd.to_datetime(
        e_2026["entry_ts_E"], unit="ns", utc=True)
    e_2026["entry_month"] = e_2026["entry_dt"].dt.month
    e_2026["exit_dt"] = pd.to_datetime(
        e_2026["exit_ts"], unit="ns", utc=True)
    e_2026["exit_month"] = e_2026["exit_dt"].dt.month

    print(f"\n  By month: {e_2026['entry_month'].value_counts().sort_index().to_dict()}")

    entry_quotes = pd.DataFrame()
    exit_quotes = pd.DataFrame()
    months_needed = sorted(set(e_2026["entry_month"].unique())
                              | set(e_2026["exit_month"].unique()))
    for month in months_needed:
        if month not in MBP1_PATHS:
            print(f"  WARN: no MBP-1 file for month {month}")
            continue
        mbp = load_mbp1_month(MBP1_PATHS[month])
        entry_mask = e_2026["entry_month"] == month
        if entry_mask.sum() > 0:
            sub_idx = e_2026[entry_mask].index
            ts_arr = e_2026.loc[sub_idx, "entry_ts_E"].values
            res = lookup_quotes_at(mbp, ts_arr)
            res.index = sub_idx
            res.columns = [f"entry_{c}" for c in res.columns]
            entry_quotes = pd.concat([entry_quotes, res])
        exit_mask = e_2026["exit_month"] == month
        if exit_mask.sum() > 0:
            sub_idx = e_2026[exit_mask].index
            ts_arr = e_2026.loc[sub_idx, "exit_ts"].values
            res = lookup_quotes_at(mbp, ts_arr)
            res.index = sub_idx
            res.columns = [f"exit_{c}" for c in res.columns]
            exit_quotes = pd.concat([exit_quotes, res])
        del mbp

    e_2026 = e_2026.join(entry_quotes).join(exit_quotes)
    long_mask = e_2026["direction"] == 1
    e_2026["entry_fill_tick"] = np.where(
        long_mask, e_2026["entry_ask"], e_2026["entry_bid"])
    e_2026["exit_fill_tick"] = np.where(
        long_mask, e_2026["exit_bid"], e_2026["exit_ask"])
    e_2026["pts_tick"] = np.where(
        long_mask,
        e_2026["exit_fill_tick"] - e_2026["entry_fill_tick"],
        e_2026["entry_fill_tick"] - e_2026["exit_fill_tick"])
    e_2026["pnl_tick"] = e_2026["pts_tick"] * NQ_MULT - 2 * COMMISSION
    e_2026["pnl_bar"] = e_2026["d_pnl_7m"]
    e_2026["slippage_per_trade"] = e_2026["pnl_bar"] - e_2026["pnl_tick"]

    bad_entry = ~e_2026["entry_ok"]
    bad_exit = ~e_2026["exit_ok"]
    valid = ~(bad_entry | bad_exit)

    print(f"\n=== HEADLINE no-delay E 2026 OOS ===")
    print(f"  Quote quality: bad entries={bad_entry.sum()}, "
          f"bad exits={bad_exit.sum()}, valid both={valid.sum()}/{len(e_2026)}")
    for sub_label, mask in [("ALL", e_2026.index),
                                ("Valid quotes", e_2026[valid].index)]:
        sub = e_2026.loc[mask]
        n = len(sub)
        if n == 0: continue
        bar_t = sub["pnl_bar"].sum(); tick_t = sub["pnl_tick"].sum()
        bar_p = bar_t / n; tick_p = tick_t / n
        slip = sub["slippage_per_trade"].sum()
        bar_wr = (sub["pnl_bar"] > 0).mean() * 100
        tick_wr = (sub["pnl_tick"] > 0).mean() * 100
        print(f"  {sub_label} (n={n:,})")
        print(f"    bar:  ${bar_t:>+10,.0f}  ${bar_p:>+8.2f}/tr  "
              f"WR={bar_wr:.1f}%")
        print(f"    tick: ${tick_t:>+10,.0f}  ${tick_p:>+8.2f}/tr  "
              f"WR={tick_wr:.1f}%")
        print(f"    Δ:    ${tick_t-bar_t:>+10,.0f}  "
              f"${(tick_p-bar_p):>+8.2f}/tr  "
              f"slip ${slip/n:+.2f}/tr")

    e_2026.to_parquet(
        OUT / "tick_validation_va_e_nodelay_2026.parquet")
    print(f"\n  Saved: tick_validation_va_e_nodelay_2026.parquet")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
