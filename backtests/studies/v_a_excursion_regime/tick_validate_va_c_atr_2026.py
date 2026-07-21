"""Tick-validate ATR-normalized C filter (ATR >= 0.75) on 2026 OOS.

Mirror of tick_validate_va_c_2026.py but uses the ATR-normalized
filter instead of the fixed $325. Reports same metrics so direct
comparison is possible.

Also reports ATR >= 0.6 as alternate variant (similar performance,
slightly more trades).
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
DELAY_S = 300

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
    bsz = mbp_df["bid_sz_00"].values
    asz = mbp_df["ask_sz_00"].values
    out = []
    for t in target_ts_array:
        j = np.searchsorted(ts_idx, np.int64(t), side="right") - 1
        if j < 0:
            out.append({"bid": np.nan, "ask": np.nan,
                          "bid_sz": 0, "ask_sz": 0,
                          "quote_age_s": np.nan, "ok": False})
            continue
        b = float(bid[j]); a = float(ask[j])
        age_s = (int(t) - int(ts_idx[j])) / 1e9
        ok = (a > 0 and b > 0 and a > b
                and (a - b) < 5.0 and age_s < 300)
        out.append({"bid": b, "ask": a,
                      "bid_sz": int(bsz[j]),
                      "ask_sz": int(asz[j]),
                      "quote_age_s": float(age_s), "ok": ok})
    return pd.DataFrame(out)


def tick_validate_cohort(c_2026, label):
    """Run tick validation on a 2026 cohort. Returns enriched
    DataFrame with tick fills and slippage."""
    c_2026 = c_2026.copy().reset_index(drop=True)
    c_2026["entry_ts_C"] = c_2026["entry_ts"] + DELAY_S * 1_000_000_000
    c_2026["entry_dt"] = pd.to_datetime(
        c_2026["entry_ts_C"], unit="ns", utc=True)
    c_2026["entry_month"] = c_2026["entry_dt"].dt.month
    c_2026["exit_dt"] = pd.to_datetime(
        c_2026["exit_ts"], unit="ns", utc=True)
    c_2026["exit_month"] = c_2026["exit_dt"].dt.month

    print(f"\n--- {label} (n={len(c_2026):,}) ---")
    print(f"  Trade distribution by month:")
    print(c_2026["entry_month"].value_counts().sort_index().to_dict())

    entry_quotes = pd.DataFrame()
    exit_quotes = pd.DataFrame()
    months_needed = sorted(set(c_2026["entry_month"].unique())
                              | set(c_2026["exit_month"].unique()))
    for month in months_needed:
        if month not in MBP1_PATHS:
            print(f"  WARN: no MBP-1 file for month {month}")
            continue
        mbp = load_mbp1_month(MBP1_PATHS[month])
        # Entry lookups
        entry_mask = c_2026["entry_month"] == month
        if entry_mask.sum() > 0:
            sub_idx = c_2026[entry_mask].index
            ts_arr = c_2026.loc[sub_idx, "entry_ts_C"].values
            res = lookup_quotes_at(mbp, ts_arr)
            res.index = sub_idx
            res.columns = [f"entry_{c}" for c in res.columns]
            entry_quotes = pd.concat([entry_quotes, res])
        # Exit lookups
        exit_mask = c_2026["exit_month"] == month
        if exit_mask.sum() > 0:
            sub_idx = c_2026[exit_mask].index
            ts_arr = c_2026.loc[sub_idx, "exit_ts"].values
            res = lookup_quotes_at(mbp, ts_arr)
            res.index = sub_idx
            res.columns = [f"exit_{c}" for c in res.columns]
            exit_quotes = pd.concat([exit_quotes, res])
        del mbp

    c_2026 = c_2026.join(entry_quotes).join(exit_quotes)
    long_mask = c_2026["direction"] == 1
    c_2026["entry_fill_tick"] = np.where(
        long_mask, c_2026["entry_ask"], c_2026["entry_bid"])
    c_2026["exit_fill_tick"] = np.where(
        long_mask, c_2026["exit_bid"], c_2026["exit_ask"])
    c_2026["pts_tick"] = np.where(
        long_mask,
        c_2026["exit_fill_tick"] - c_2026["entry_fill_tick"],
        c_2026["entry_fill_tick"] - c_2026["exit_fill_tick"])
    c_2026["pnl_tick"] = c_2026["pts_tick"] * NQ_MULT - 2 * COMMISSION
    c_2026["pnl_bar"] = c_2026["d_pnl_5m"]
    c_2026["slippage_per_trade"] = (
        c_2026["pnl_bar"] - c_2026["pnl_tick"])
    return c_2026


def report(label, c_2026):
    bad_entry = ~c_2026["entry_ok"]
    bad_exit = ~c_2026["exit_ok"]
    valid = ~(bad_entry | bad_exit)
    print(f"\n=== {label} HEADLINE ===")
    print(f"  Quote quality: bad entries={bad_entry.sum()}, "
          f"bad exits={bad_exit.sum()}, "
          f"valid both sides={valid.sum()}/{len(c_2026)}")
    for sub_label, mask in [("ALL", c_2026.index),
                                ("Valid quotes", c_2026[valid].index)]:
        sub = c_2026.loc[mask]
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


def main():
    t0 = time.time()
    print("=" * 78)
    print("TICK VALIDATION — ATR-NORMALIZED C FILTERS, 2026 OOS")
    print("=" * 78)

    feats = pd.read_parquet(OUT / "checkpoint_features.parquet")
    n_pre = len(feats)
    feats = feats.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    if n_pre != len(feats):
        print(f"  deduped: {n_pre:,} -> {len(feats):,}")

    feats["f_unr_atr_T_5m"] = (
        feats["f_unr_pnl_T_5m"] / (feats["atr"] * NQ_MULT))
    alive = feats[feats["alive_5m"]].copy()

    # Build cohorts: ATR >= 0.6 and ATR >= 0.75, 2026 only
    for thr_atr, label, fname in [
        (0.60, "ATR>=0.60", "atr_ge_0.60"),
        (0.75, "ATR>=0.75", "atr_ge_0.75"),
    ]:
        cohort = alive[alive["f_unr_atr_T_5m"] >= thr_atr].copy()
        c_2026 = cohort[cohort["year"] == 2026].copy()
        c_2026 = c_2026.sort_values("entry_ts").reset_index(drop=True)
        c_2026 = c_2026.rename(columns={"fill_px": "fill_price",
                                              "exit_px": "exit_price"})
        if len(c_2026) == 0:
            print(f"  no {label} trades in 2026"); continue
        c_2026 = tick_validate_cohort(c_2026, label)
        report(label, c_2026)
        c_2026.to_parquet(OUT / f"tick_validation_{fname}_2026.parquet")
        print(f"  Saved: tick_validation_{fname}_2026.parquet")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
