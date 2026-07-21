"""Tick-validate T-1 pre-flip top-10% on 2026 OOS.

For each fired 2026 candidate (p_score in global top 10% of all OOS):
  - Entry: next 1s bar OPEN after candidate.close_ts (bar1-close + 1s)
    in candidate_direction. Tick fill at MBP-1 ask (long) / bid (short).
  - Exit:
    (a) If V_A confirms flip in candidate_direction at target_flip_ts =
        candidate.close_ts + 60s: use V_A's regime-flip exit_ts.
    (b) Else: exit at candidate.close_ts + 60s (the bar-close exit
        that performed best in bar-mode trade sim).
  - Tick fill: MBP-1 bid (long) / ask (short) at exit_ts.

Reports bar-mode vs tick PnL, per-month breakdown, slippage decomposition.
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


OUT = Path("studies/v_a_excursion_regime/results_v0")
NQ_MULT = 20.0
COMMISSION_ONE_WAY = 5.0
TOP_QUANTILE = 0.10        # global top 10% of OOS p_scores
HORIZON_S = 60             # T-1 = 60 seconds
MBP1_PATHS = {
    1: "data/raw/NQ_v0_mbp1_2026_01.parquet",
    2: "data/raw/NQ_v0_mbp1_2026_02.parquet",
    3: "data/raw/NQ_v0_mbp1_2026_03.parquet",
    4: "data/raw/NQ_v0_mbp1_2026_04.parquet",
}
ONE_S_2026 = "data/raw/NQ_v0_1s_2026_ytd.parquet"


def load_1s_oc(path):
    df = pq.read_table(
        path, columns=["ts_event", "open", "close"]).to_pandas()
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df["ts_event_ns"] = df["ts_event"].dt.tz_convert("UTC"
                            ).dt.tz_localize(None).astype("datetime64[ns]"
                            ).astype("int64")
    return df


def load_mbp1(path):
    print(f"    loading {path}...", flush=True)
    df = pd.read_parquet(
        path, columns=["ts_event", "bid_px_00", "ask_px_00"])
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def lookup_quote(mbp_df, target_ts):
    ts_idx = mbp_df["ts_event"].values.astype("int64")
    j = np.searchsorted(ts_idx, np.int64(target_ts), side="right") - 1
    if j < 0:
        return np.nan, np.nan, False
    b = float(mbp_df["bid_px_00"].values[j])
    a = float(mbp_df["ask_px_00"].values[j])
    age_s = (int(target_ts) - int(ts_idx[j])) / 1e9
    ok = (a > 0 and b > 0 and a > b and (a - b) < 5.0 and age_s < 300)
    return b, a, ok


def main():
    t0 = time.time()
    print("=" * 78)
    print("TICK VALIDATION — T-1 pre-flip top 10% on 2026 OOS")
    print("=" * 78)

    # Load T-1 OOS predictions
    oos = pd.read_parquet(OUT / "pre_flip_oos_T1.parquet")
    print(f"\n  Total OOS predictions: {len(oos):,}")
    thresh = oos["p_score"].quantile(1 - TOP_QUANTILE)
    print(f"  Global top {TOP_QUANTILE*100:.0f}% threshold: p >= {thresh:.4f}")
    fired = oos[oos["p_score"] >= thresh].copy()
    fired_2026 = fired[fired["year"] == 2026].copy().reset_index(drop=True)
    print(f"  Top {TOP_QUANTILE*100:.0f}% total: {len(fired):,}")
    print(f"  Top {TOP_QUANTILE*100:.0f}% in 2026: {len(fired_2026):,}")
    print(f"  Pos rate in 2026 fired: {fired_2026['label'].mean():.3%}")

    # Load 1s OHLC for 2026 (for bar-mode reference)
    print(f"\n  Loading 2026 1s OHLC...")
    bars_2026 = load_1s_oc(ONE_S_2026)
    bars_ts = bars_2026["ts_event_ns"].to_numpy()
    bars_o = bars_2026["open"].to_numpy()
    bars_c = bars_2026["close"].to_numpy()
    print(f"    {len(bars_2026):,} 1s bars loaded")

    # Load V_A flip outcomes for the V_A-confirm case
    print(f"\n  Loading 2026 V_A trades for confirmed-flip exits...")
    snap_2026 = pd.read_parquet(
        "collectors/collector_v2/results/v_a_v0_2026/snapshots_with_vol_vwap.parquet",
        columns=["kind", "decision_ts", "direction", "became_trade",
                   "session"])
    trades_2026 = pd.read_parquet(
        "collectors/collector_v2/results/v_a_v0_2026/trades.parquet",
        columns=["decision_ts", "direction", "fill_price", "exit_ts",
                   "exit_price", "atr_at_signal", "net_pnl", "session"])
    b1 = snap_2026[(snap_2026["kind"] == "bar1_check")
                      & (snap_2026["became_trade"])
                      & (snap_2026["session"] == "RTH")].copy()
    b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
    va_2026 = b1.merge(
        trades_2026[trades_2026["session"] == "RTH"][[
            "decision_ts", "direction", "fill_price", "exit_ts",
            "exit_price", "net_pnl"]],
        on=["decision_ts", "direction"], how="inner")
    va_lookup = va_2026.set_index(["flip_bar_close_ts", "direction"])
    print(f"    V_A confirmed flips in 2026: {len(va_2026):,}")

    # For each fired 2026 candidate, build trade row
    print(f"\n  Building entry/exit timestamps for fired predictions...")
    fired_2026["entry_ts_ns"] = fired_2026["close_ts_ns"]
    fired_2026["target_flip_ts_ns"] = (
        fired_2026["close_ts_ns"] + HORIZON_S * 1_000_000_000)
    # Determine exit_ts and outcome: V_A confirm vs no-flip bar-close
    exit_ts_list = []
    outcome_list = []
    va_exit_price = []
    for _, fr in fired_2026.iterrows():
        target_ts = int(fr["target_flip_ts_ns"])
        d = int(fr["direction"])
        try:
            va_row = va_lookup.loc[(target_ts, d)]
            exit_ts_list.append(int(va_row["exit_ts"]))
            outcome_list.append("va_confirm")
            va_exit_price.append(float(va_row["exit_price"]))
        except KeyError:
            # No V_A confirm — exit at +1 bar close (= target_flip_ts)
            exit_ts_list.append(target_ts)
            outcome_list.append("no_flip")
            va_exit_price.append(np.nan)
    fired_2026["exit_ts_ns"] = exit_ts_list
    fired_2026["outcome"] = outcome_list
    fired_2026["va_exit_price"] = va_exit_price

    n_va = (fired_2026["outcome"] == "va_confirm").sum()
    print(f"    VA-confirm: {n_va} ({n_va/len(fired_2026):.1%})")
    print(f"    No-flip:    {len(fired_2026)-n_va} "
          f"({(len(fired_2026)-n_va)/len(fired_2026):.1%})")

    # Entry/exit prices from 1s OHLC (bar mode)
    print(f"\n  Computing bar-mode fills (1s OPEN at entry/exit ts)...")
    bar_entry_px = np.full(len(fired_2026), np.nan)
    bar_exit_px = np.full(len(fired_2026), np.nan)
    for k, fr in fired_2026.iterrows():
        i_e = int(np.searchsorted(
            bars_ts, int(fr["entry_ts_ns"]), side="left"))
        if i_e < len(bars_ts):
            bar_entry_px[k] = float(bars_o[i_e])
        i_x = int(np.searchsorted(
            bars_ts, int(fr["exit_ts_ns"]), side="left"))
        if i_x < len(bars_ts):
            bar_exit_px[k] = float(bars_o[i_x])
    fired_2026["bar_entry_px"] = bar_entry_px
    fired_2026["bar_exit_px"] = bar_exit_px
    fired_2026["bar_pnl"] = (
        (fired_2026["bar_exit_px"] - fired_2026["bar_entry_px"])
        * fired_2026["direction"] * NQ_MULT
        - 2 * COMMISSION_ONE_WAY)

    # MBP-1 quote lookups for tick fills
    print(f"\n  Looking up MBP-1 quotes for tick fills...")
    fired_2026["entry_dt"] = pd.to_datetime(
        fired_2026["entry_ts_ns"], unit="ns", utc=True)
    fired_2026["exit_dt"] = pd.to_datetime(
        fired_2026["exit_ts_ns"], unit="ns", utc=True)
    fired_2026["entry_month"] = fired_2026["entry_dt"].dt.month
    fired_2026["exit_month"] = fired_2026["exit_dt"].dt.month
    months_needed = sorted(
        set(fired_2026["entry_month"].unique())
        | set(fired_2026["exit_month"].unique()))
    entry_bid = np.full(len(fired_2026), np.nan)
    entry_ask = np.full(len(fired_2026), np.nan)
    entry_ok = np.zeros(len(fired_2026), dtype=bool)
    exit_bid = np.full(len(fired_2026), np.nan)
    exit_ask = np.full(len(fired_2026), np.nan)
    exit_ok = np.zeros(len(fired_2026), dtype=bool)
    for month in months_needed:
        if month not in MBP1_PATHS:
            continue
        mbp = load_mbp1(MBP1_PATHS[month])
        emask = (fired_2026["entry_month"] == month).to_numpy()
        for idx in np.where(emask)[0]:
            b, a, ok = lookup_quote(
                mbp, int(fired_2026["entry_ts_ns"].iloc[idx]))
            entry_bid[idx] = b; entry_ask[idx] = a; entry_ok[idx] = ok
        xmask = (fired_2026["exit_month"] == month).to_numpy()
        for idx in np.where(xmask)[0]:
            b, a, ok = lookup_quote(
                mbp, int(fired_2026["exit_ts_ns"].iloc[idx]))
            exit_bid[idx] = b; exit_ask[idx] = a; exit_ok[idx] = ok
        del mbp
    fired_2026["entry_bid"] = entry_bid
    fired_2026["entry_ask"] = entry_ask
    fired_2026["entry_ok"] = entry_ok
    fired_2026["exit_bid"] = exit_bid
    fired_2026["exit_ask"] = exit_ask
    fired_2026["exit_ok"] = exit_ok

    long_mask = fired_2026["direction"].to_numpy() == 1
    fired_2026["tick_entry_px"] = np.where(
        long_mask, fired_2026["entry_ask"], fired_2026["entry_bid"])
    fired_2026["tick_exit_px"] = np.where(
        long_mask, fired_2026["exit_bid"], fired_2026["exit_ask"])
    fired_2026["tick_pnl"] = (
        (fired_2026["tick_exit_px"] - fired_2026["tick_entry_px"])
        * fired_2026["direction"] * NQ_MULT
        - 2 * COMMISSION_ONE_WAY)
    fired_2026["slippage_per_trade"] = (
        fired_2026["bar_pnl"] - fired_2026["tick_pnl"])
    valid = fired_2026["entry_ok"] & fired_2026["exit_ok"]

    # Headline
    print(f"\n=== HEADLINE — T-1 top 10% on 2026 OOS ===")
    print(f"  Quote quality: valid both={valid.sum()}/{len(fired_2026)}")
    for label_, mask in [("ALL", fired_2026.index),
                              ("Valid quotes", fired_2026[valid].index)]:
        sub = fired_2026.loc[mask]
        n = len(sub)
        if n == 0:
            continue
        bar_t = sub["bar_pnl"].sum()
        tick_t = sub["tick_pnl"].sum()
        bar_m = bar_t / n
        tick_m = tick_t / n
        slip = sub["slippage_per_trade"].sum()
        bar_wr = (sub["bar_pnl"] > 0).mean() * 100
        tick_wr = (sub["tick_pnl"] > 0).mean() * 100
        print(f"\n  {label_} (n={n:,})")
        print(f"    bar:  ${bar_t:>+10,.0f}  ${bar_m:>+8.2f}/tr  "
              f"WR={bar_wr:.1f}%")
        print(f"    tick: ${tick_t:>+10,.0f}  ${tick_m:>+8.2f}/tr  "
              f"WR={tick_wr:.1f}%")
        print(f"    Δ:    ${tick_t-bar_t:>+10,.0f}  "
              f"${(tick_m-bar_m):>+8.2f}/tr  "
              f"slip ${slip/n:+.2f}/tr")
        if bar_m != 0:
            print(f"    edge retention: {tick_m/bar_m:.0%}")

    # Per-month
    print(f"\n  Per-month (valid quotes only):")
    print(f"    {'month':<8}  {'n':>4}  {'bar_$':>10}  {'tick_$':>10}  "
          f"{'slip':>9}  {'va%':>5}")
    for month in sorted(months_needed):
        sub = fired_2026[(fired_2026["entry_month"] == month) & valid]
        if len(sub) == 0:
            continue
        va_pct = (sub["outcome"] == "va_confirm").mean() * 100
        print(f"    2026-{month:>02}  {len(sub):>4}  "
              f"${sub['bar_pnl'].sum():>+8,.0f}  "
              f"${sub['tick_pnl'].sum():>+8,.0f}  "
              f"${sub['slippage_per_trade'].sum():>+7,.0f}  "
              f"{va_pct:>4.1f}%")

    # Breakdown by outcome (VA-confirm vs no-flip)
    print(f"\n  Per-outcome breakdown (valid quotes):")
    v = fired_2026[valid]
    for outcome in ["va_confirm", "no_flip"]:
        sub = v[v["outcome"] == outcome]
        n = len(sub)
        if n == 0:
            continue
        bar_t = sub["bar_pnl"].sum()
        tick_t = sub["tick_pnl"].sum()
        bar_wr = (sub["bar_pnl"] > 0).mean() * 100
        tick_wr = (sub["tick_pnl"] > 0).mean() * 100
        print(f"    {outcome:<12}  n={n:>4}  "
              f"bar=${bar_t:>+8,.0f} ({bar_t/n:+.2f}/tr WR={bar_wr:.1f}%)  "
              f"tick=${tick_t:>+8,.0f} ({tick_t/n:+.2f}/tr WR={tick_wr:.1f}%)")

    # Slippage breakdown
    if valid.sum() > 0:
        v = fired_2026[valid].copy()
        long_v = v["direction"] == 1
        v["entry_slip_$"] = np.where(
            long_v,
            (v["tick_entry_px"] - v["bar_entry_px"]) * NQ_MULT,
            (v["bar_entry_px"] - v["tick_entry_px"]) * NQ_MULT)
        v["exit_slip_$"] = np.where(
            long_v,
            (v["bar_exit_px"] - v["tick_exit_px"]) * NQ_MULT,
            (v["tick_exit_px"] - v["bar_exit_px"]) * NQ_MULT)
        print(f"\n  Slippage decomposition (n={len(v):,}):")
        for col, lbl in [("entry_slip_$", "Entry slip (pay above bar OPEN)"),
                          ("exit_slip_$", "Exit slip (sell below bar exit)")]:
            s = v[col]
            print(f"    {lbl:<35}  mean=${s.mean():>+7.2f}/tr  "
                  f"med=${s.median():>+6.2f}  p90=${s.quantile(0.9):>+6.2f}  "
                  f"max=${s.max():>+6.2f}")
        total_slip = v["slippage_per_trade"].mean()
        print(f"    {'TOTAL':<35}  mean=${total_slip:>+7.2f}/tr")

    fired_2026.to_parquet(OUT / "tick_validate_pre_flip_T1_top10_2026.parquet")
    print(f"\n  Saved: tick_validate_pre_flip_T1_top10_2026.parquet")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
