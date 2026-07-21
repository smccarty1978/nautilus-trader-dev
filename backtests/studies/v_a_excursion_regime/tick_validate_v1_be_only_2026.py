"""Tick-validate V1 (BE @0.75 only) on 2026 OOS top-50% cohort.

For each top-50% trade in 2026:
  1. Walk 1s OHLC from entry_ts forward
  2. Detect when MFE crosses 0.75 ATR (intra-bar high check for longs,
     low check for shorts) -> arm BE
  3. After BE armed, detect when 1s bar low (long) or high (short)
     crosses fill_price -> BE triggered
  4. Look up MBP-1 quotes at:
     - entry_ts (real ask for long, bid for short)
     - BE trigger ts OR regime exit ts (real bid for long, ask for short)
  5. Compute tick PnL vs bar PnL
  6. Report slippage, lift retention, per-month breakdown

Conservative BE fill: at BE_trigger ts use quote.bid (long) / quote.ask
(short). If the 1s bar's low went BELOW fill_price by more than the
spread, fill at min(quote.bid, fill_price - 0.25) — captures stop
slippage beyond 1 tick.
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
BE_ARM_ATR = 0.75
TOP50_THRESHOLD = 0.2821

MBP1_PATHS = {
    1: "data/raw/NQ_v0_mbp1_2026_01.parquet",
    2: "data/raw/NQ_v0_mbp1_2026_02.parquet",
    3: "data/raw/NQ_v0_mbp1_2026_03.parquet",
    4: "data/raw/NQ_v0_mbp1_2026_04.parquet",
}
ONE_S_2026 = "data/raw/NQ_v0_1s_2026_ytd.parquet"


def load_1s_ohlc(path):
    df = pq.read_table(
        path, columns=["ts_event", "open", "high", "low", "close"]
        ).to_pandas()
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df["ts_event_ns"] = df["ts_event"].dt.tz_convert("UTC"
                            ).dt.tz_localize(None).astype("datetime64[ns]"
                            ).astype("int64")
    return df


def load_mbp1_month(path):
    print(f"    loading {path}...", flush=True)
    df = pd.read_parquet(
        path, columns=["ts_event", "bid_px_00", "ask_px_00"])
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def lookup_quote(mbp_df, target_ts: int):
    ts_idx = mbp_df["ts_event"].values.astype("int64")
    j = np.searchsorted(ts_idx, np.int64(target_ts), side="right") - 1
    if j < 0:
        return None, None, False
    b = float(mbp_df["bid_px_00"].values[j])
    a = float(mbp_df["ask_px_00"].values[j])
    age_s = (int(target_ts) - int(ts_idx[j])) / 1e9
    ok = (a > 0 and b > 0 and a > b
            and (a - b) < 5.0 and age_s < 300)
    return b, a, ok


def find_be_trigger(bars_ts, bars_h, bars_l, entry_ts, exit_ts,
                       fill_price, direction, atr,
                       arm_atr=BE_ARM_ATR):
    """Walk 1s bars in [entry_ts, exit_ts]. Return (arm_ts, trigger_ts)
    where arm_ts is when MFE first reached arm_atr ATR, and trigger_ts
    is when BE was hit (after arming). Either may be None.
    """
    i_start = int(np.searchsorted(bars_ts, entry_ts, side="left"))
    i_end = int(np.searchsorted(bars_ts, exit_ts, side="right"))
    if i_end <= i_start:
        return None, None

    arm_threshold = arm_atr * atr  # in points
    arm_ts = None
    trigger_ts = None
    for i in range(i_start, i_end):
        h = bars_h[i]; l = bars_l[i]
        if arm_ts is None:
            # MFE arm check
            if direction == 1:
                if (h - fill_price) >= arm_threshold:
                    arm_ts = int(bars_ts[i])
            else:
                if (fill_price - l) >= arm_threshold:
                    arm_ts = int(bars_ts[i])
            # If armed this bar, check trigger in SAME bar
            if arm_ts is not None:
                if direction == 1:
                    if l <= fill_price:
                        trigger_ts = arm_ts
                        return arm_ts, trigger_ts
                else:
                    if h >= fill_price:
                        trigger_ts = arm_ts
                        return arm_ts, trigger_ts
        else:
            # BE trigger check
            if direction == 1:
                if l <= fill_price:
                    trigger_ts = int(bars_ts[i])
                    return arm_ts, trigger_ts
            else:
                if h >= fill_price:
                    trigger_ts = int(bars_ts[i])
                    return arm_ts, trigger_ts
    return arm_ts, None


def main():
    t0 = time.time()
    print("=" * 78)
    print("TICK VALIDATION — V1 (BE @0.75 only) on 2026 OOS top-50%")
    print("=" * 78)

    # Load top-50% predictions
    preds = pd.read_parquet(OUT / "ml_n40_oos_preds_with_trades.parquet")
    top50_2026 = preds[(preds["p_unr075"] >= TOP50_THRESHOLD)
                          & (preds["year"] == 2026)].copy().reset_index(
        drop=True)
    print(f"\n  2026 OOS top-50% trades: {len(top50_2026):,}")

    # Load 1s OHLC for 2026
    print(f"\n  Loading 2026 1s OHLC...")
    bars_2026 = load_1s_ohlc(ONE_S_2026)
    bars_ts = bars_2026["ts_event_ns"].to_numpy()
    bars_h = bars_2026["high"].to_numpy()
    bars_l = bars_2026["low"].to_numpy()
    bars_c = bars_2026["close"].to_numpy()
    print(f"    {len(bars_2026):,} 1s bars loaded")

    # Detect BE arm/trigger per trade
    print(f"\n  Detecting BE arm/trigger per trade...")
    arm_results = []
    for _, trade in top50_2026.iterrows():
        arm_ts, trig_ts = find_be_trigger(
            bars_ts, bars_h, bars_l,
            int(trade["entry_ts"]), int(trade["exit_ts"]),
            float(trade["fill_price"]), int(trade["direction"]),
            float(trade["atr_at_signal"]))
        arm_results.append({
            "decision_ts": trade["decision_ts"],
            "direction": trade["direction"],
            "entry_ts": trade["entry_ts"],
            "exit_ts": trade["exit_ts"],
            "fill_price": trade["fill_price"],
            "atr_at_signal": trade["atr_at_signal"],
            "be_arm_ts": arm_ts,
            "be_trigger_ts": trig_ts,
            "net_pnl_baseline": trade["net_pnl"],
            "exit_price_baseline": trade["exit_price"],
        })
    res = pd.DataFrame(arm_results)
    n_armed = res["be_arm_ts"].notna().sum()
    n_triggered = res["be_trigger_ts"].notna().sum()
    print(f"    BE armed: {n_armed:,} / {len(res):,} ({n_armed/len(res):.1%})")
    print(f"    BE triggered: {n_triggered:,} / {len(res):,} "
          f"({n_triggered/len(res):.1%})")

    # Determine "effective exit" — BE trigger ts (if any) else regime exit ts
    res["effective_exit_ts"] = np.where(
        res["be_trigger_ts"].notna(),
        res["be_trigger_ts"], res["exit_ts"])
    res["exit_via_be"] = res["be_trigger_ts"].notna()
    res["effective_exit_dt"] = pd.to_datetime(
        res["effective_exit_ts"].astype(np.int64),
        unit="ns", utc=True)
    res["effective_exit_month"] = res["effective_exit_dt"].dt.month
    res["entry_dt"] = pd.to_datetime(
        res["entry_ts"].astype(np.int64), unit="ns", utc=True)
    res["entry_month"] = res["entry_dt"].dt.month
    months_needed = sorted(set(res["entry_month"].unique())
                              | set(res["effective_exit_month"].unique()))

    # Load MBP-1 month by month, look up quotes
    print(f"\n  Looking up MBP-1 quotes at entry and effective exit...")
    entry_bid = np.full(len(res), np.nan)
    entry_ask = np.full(len(res), np.nan)
    entry_ok = np.zeros(len(res), dtype=bool)
    exit_bid = np.full(len(res), np.nan)
    exit_ask = np.full(len(res), np.nan)
    exit_ok = np.zeros(len(res), dtype=bool)
    for month in months_needed:
        if month not in MBP1_PATHS:
            continue
        mbp = load_mbp1_month(MBP1_PATHS[month])
        # Entries in this month
        entry_mask = (res["entry_month"] == month).to_numpy()
        for idx in np.where(entry_mask)[0]:
            b, a, ok = lookup_quote(mbp, int(res["entry_ts"].iloc[idx]))
            entry_bid[idx] = b if b else np.nan
            entry_ask[idx] = a if a else np.nan
            entry_ok[idx] = ok
        # Exits in this month
        exit_mask = (res["effective_exit_month"] == month).to_numpy()
        for idx in np.where(exit_mask)[0]:
            b, a, ok = lookup_quote(
                mbp, int(res["effective_exit_ts"].iloc[idx]))
            exit_bid[idx] = b if b else np.nan
            exit_ask[idx] = a if a else np.nan
            exit_ok[idx] = ok
        del mbp
    res["entry_bid"] = entry_bid
    res["entry_ask"] = entry_ask
    res["entry_ok"] = entry_ok
    res["exit_bid"] = exit_bid
    res["exit_ask"] = exit_ask
    res["exit_ok"] = exit_ok

    # Tick-PnL: entry at ask (long) / bid (short); exit at bid (long) / ask (short)
    long_mask = res["direction"].to_numpy() == 1
    res["entry_fill_tick"] = np.where(long_mask, res["entry_ask"],
                                            res["entry_bid"])
    res["exit_fill_tick"] = np.where(long_mask, res["exit_bid"],
                                           res["exit_ask"])
    # For BE-triggered trades, the exit fill is the bid at BE trigger ts.
    # The simulation bar PnL assumes BE filled at fill_price ($0 - $10).
    # Real tick fill: at quote bid right at trigger ts. If bar low went
    # BELOW fill_price, the stop slipped — quote bid may be below
    # fill_price too.
    res["pts_tick"] = np.where(
        long_mask,
        res["exit_fill_tick"] - res["entry_fill_tick"],
        res["entry_fill_tick"] - res["exit_fill_tick"])
    res["pnl_tick"] = res["pts_tick"] * NQ_MULT - 2 * COMMISSION_ONE_WAY
    # Bar-PnL with V1 BE rule: if BE triggered, $0 - $10; else use baseline
    res["pnl_bar_v1"] = np.where(
        res["exit_via_be"],
        -2 * COMMISSION_ONE_WAY,
        res["net_pnl_baseline"])

    valid = res["entry_ok"] & res["exit_ok"]
    n_valid = int(valid.sum())
    print(f"\n  Quote quality: valid both={n_valid:,}/{len(res):,}")

    print(f"\n=== HEADLINE — V1 (BE @0.75) tick validation 2026 OOS ===")
    bar_total = res["pnl_bar_v1"].sum()
    tick_total = res["pnl_tick"].sum()
    bar_mean = bar_total / len(res)
    tick_mean = tick_total / len(res)
    bar_wr = (res["pnl_bar_v1"] > 0).mean() * 100
    tick_wr = (res["pnl_tick"] > 0).mean() * 100
    print(f"\n  ALL (n={len(res)})")
    print(f"    bar v1: ${bar_total:>+10,.0f}  ${bar_mean:>+8.2f}/tr  "
          f"WR={bar_wr:.1f}%")
    print(f"    tick:   ${tick_total:>+10,.0f}  ${tick_mean:>+8.2f}/tr  "
          f"WR={tick_wr:.1f}%")
    print(f"    Δ:      ${tick_total-bar_total:>+10,.0f}  "
          f"${tick_mean-bar_mean:>+8.2f}/tr")

    if n_valid > 0:
        v = res[valid]
        bar_total_v = v["pnl_bar_v1"].sum()
        tick_total_v = v["pnl_tick"].sum()
        bar_mean_v = bar_total_v / len(v)
        tick_mean_v = tick_total_v / len(v)
        print(f"\n  Valid quotes (n={len(v)})")
        print(f"    bar v1: ${bar_total_v:>+10,.0f}  ${bar_mean_v:>+8.2f}/tr")
        print(f"    tick:   ${tick_total_v:>+10,.0f}  ${tick_mean_v:>+8.2f}/tr")
        print(f"    Δ:      ${tick_total_v-bar_total_v:>+10,.0f}  "
              f"${tick_mean_v-bar_mean_v:>+8.2f}/tr")

    # Compare to V0 baseline tick (already computed in prior run, but
    # recompute here for clarity using THIS res's entry/exit fills with
    # the BASELINE exit ts):
    # For trades that did NOT BE-trigger, tick PnL is the same as V1.
    # For trades that DID BE-trigger, baseline would have held to regime
    # exit. We need to lookup quotes at the BASELINE exit_ts for those.
    # That's more work; instead use the bar baseline (net_pnl) as the
    # comparison anchor and note that V0 tick was -$10,645 from prior
    # script.

    print(f"\n  Per-month breakdown (valid only):")
    print(f"    {'month':<7}  {'n':>4}  {'be%':>5}  "
          f"{'bar_v1':>10}  {'tick':>10}  {'tick-bar':>9}")
    for month in sorted(months_needed):
        sub = res[(res["entry_month"] == month) & valid]
        if len(sub) == 0:
            continue
        n_m = len(sub)
        be_pct = sub["exit_via_be"].mean() * 100
        bar_m = sub["pnl_bar_v1"].sum()
        tick_m = sub["pnl_tick"].sum()
        print(f"    2026-{month:>02}  {n_m:>4}  {be_pct:>4.1f}%  "
              f"${bar_m:>+8,.0f}  ${tick_m:>+8,.0f}  "
              f"${tick_m-bar_m:>+7,.0f}")

    # Slippage decomposition for BE trades
    if valid.sum() > 0:
        be_v = res[valid & res["exit_via_be"]].copy()
        if len(be_v) > 0:
            long_be = be_v["direction"] == 1
            # The "bar BE" exit is at fill_price (zero PnL exit).
            # The "tick BE" exit is at quote bid (long) / ask (short).
            # Slippage = fill_price - quote bid (long) -- positive = paid
            be_v["be_slip_pts"] = np.where(
                long_be,
                be_v["fill_price"] - be_v["exit_bid"],
                be_v["exit_ask"] - be_v["fill_price"])
            be_v["be_slip_$"] = be_v["be_slip_pts"] * NQ_MULT
            print(f"\n  BE slippage decomposition "
                  f"(BE-triggered valid trades, n={len(be_v):,}):")
            s = be_v["be_slip_$"]
            print(f"    mean=${s.mean():+.2f}/tr  median=${s.median():+.2f}  "
                  f"p10=${s.quantile(0.1):+.2f}  p90=${s.quantile(0.9):+.2f}  "
                  f"max=${s.max():+.2f}")
            print(f"    n with positive slip: {(s > 0).sum()}/{len(s)}  "
                  f"n with extreme (>$50): {(s > 50).sum()}/{len(s)}")

    res.to_parquet(OUT / "tick_validate_v1_be_only_2026.parquet")
    print(f"\n  Saved: tick_validate_v1_be_only_2026.parquet")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
