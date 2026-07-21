"""1s-precise BE @0.75 simulation across full V_A and ML cohorts.

Replaces the path_checkpoint-based simulator (which inflated BE PnL by
~5-10x) with proper 1s OHLC trigger detection.

Detection logic per trade:
  - Walk 1s bars in [entry_ts, exit_ts]
  - BE arms when bar.high - fill_price >= 0.75 * atr (long), or
    fill_price - bar.low >= 0.75 * atr (short)
  - After BE armed, BE triggers when bar.low <= fill_price (long) or
    bar.high >= fill_price (short)
  - Within the SAME bar where BE arms, check trigger condition too
    (intra-second V-shape catches itself)
  - Triggered trade exits at fill_price (PnL = $0) minus 2x commission
  - Non-triggered trade holds to regime flip (uses existing net_pnl)

Reports the corrected BE lift for:
  - All V_A confirmed RTH trades
  - Top-50% ML cohort
  - Bottom-50% ML cohort
Per-year and combined.
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
ONE_S_PATHS = {
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}


def load_1s_ohlc(path):
    df = pq.read_table(
        path, columns=["ts_event", "high", "low"]).to_pandas()
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    df["ts_event_ns"] = df["ts_event"].dt.tz_convert("UTC"
                            ).dt.tz_localize(None).astype("datetime64[ns]"
                            ).astype("int64")
    return df


def find_be_trigger_1s(bars_ts, bars_h, bars_l, entry_ts, exit_ts,
                          fill_price, direction, atr,
                          arm_atr=BE_ARM_ATR):
    """Walk 1s bars and return (arm_ts, trigger_ts) using 1s precision."""
    i_start = int(np.searchsorted(bars_ts, entry_ts, side="left"))
    i_end = int(np.searchsorted(bars_ts, exit_ts, side="right"))
    if i_end <= i_start:
        return None, None
    arm_threshold = arm_atr * atr
    arm_ts = None
    for i in range(i_start, i_end):
        h = bars_h[i]; l = bars_l[i]
        if arm_ts is None:
            if direction == 1:
                if (h - fill_price) >= arm_threshold:
                    arm_ts = int(bars_ts[i])
            else:
                if (fill_price - l) >= arm_threshold:
                    arm_ts = int(bars_ts[i])
            # Same-bar trigger check
            if arm_ts is not None:
                if direction == 1:
                    if l <= fill_price:
                        return arm_ts, arm_ts
                else:
                    if h >= fill_price:
                        return arm_ts, arm_ts
        else:
            if direction == 1:
                if l <= fill_price:
                    return arm_ts, int(bars_ts[i])
            else:
                if h >= fill_price:
                    return arm_ts, int(bars_ts[i])
    return arm_ts, None


def simulate_cohort(cohort: pd.DataFrame,
                       bars_by_year: dict[int, dict]) -> pd.DataFrame:
    """Apply 1s-precise BE @0.75 to each trade. Returns df with
    pnl_v1 and exit_via_be."""
    results = []
    for _, trade in cohort.iterrows():
        yr = int(trade["year"])
        bars_data = bars_by_year[yr]
        bars_ts = bars_data["ts"]
        bars_h = bars_data["h"]
        bars_l = bars_data["l"]
        arm_ts, trig_ts = find_be_trigger_1s(
            bars_ts, bars_h, bars_l,
            int(trade["entry_ts"]), int(trade["exit_ts"]),
            float(trade["fill_price"]), int(trade["direction"]),
            float(trade["atr_at_signal"]))
        if trig_ts is not None:
            pnl_v1 = -2 * COMMISSION_ONE_WAY
        else:
            pnl_v1 = float(trade["net_pnl"])
        results.append({
            "decision_ts": trade["decision_ts"],
            "direction": trade["direction"],
            "year": yr,
            "p_unr075": trade.get("p_unr075", np.nan),
            "pnl_baseline": float(trade["net_pnl"]),
            "pnl_v1": pnl_v1,
            "be_armed": arm_ts is not None,
            "be_triggered": trig_ts is not None,
        })
    return pd.DataFrame(results)


def report(name, res):
    n = len(res)
    base_t = res["pnl_baseline"].sum()
    v1_t = res["pnl_v1"].sum()
    delta = v1_t - base_t
    print(f"\n  {name} (n={n:,})")
    print(f"    Baseline:   total=${base_t:>+10,.0f}  mean=${base_t/n:>+7.2f}/tr")
    print(f"    + BE @0.75: total=${v1_t:>+10,.0f}  mean=${v1_t/n:>+7.2f}/tr")
    print(f"    Δ (lift):   total=${delta:>+10,.0f}  mean=${delta/n:>+7.2f}/tr")
    arm_pct = res["be_armed"].mean() * 100
    trig_pct = res["be_triggered"].mean() * 100
    print(f"    BE arm rate: {arm_pct:.1f}%   trigger rate: {trig_pct:.1f}%")
    print(f"    {'year':>4}  {'n':>5}  {'base':>10}  {'v1':>10}  "
          f"{'Δ':>10}  {'trig%':>6}")
    for yr in sorted(res["year"].unique()):
        ysub = res[res["year"] == yr]
        yb = ysub["pnl_baseline"].sum()
        yv = ysub["pnl_v1"].sum()
        yt = ysub["be_triggered"].mean() * 100
        print(f"    {yr:>4}  {len(ysub):>5,}  ${yb:>+8,.0f}  "
              f"${yv:>+8,.0f}  ${yv-yb:>+8,.0f}  {yt:>5.1f}%")


def main():
    t0 = time.time()
    print("=" * 78)
    print("BE @0.75 — 1s-PRECISE SIMULATION  (corrected)")
    print("=" * 78)

    preds = pd.read_parquet(OUT / "ml_n40_oos_preds_with_trades.parquet")
    print(f"\nTotal OOS trades: {len(preds):,}")
    print(f"  Top 50%: {(preds['p_unr075'] >= TOP50_THRESHOLD).sum():,}")
    print(f"  Bot 50%: {(preds['p_unr075'] < TOP50_THRESHOLD).sum():,}")

    # Load 1s bars per year
    bars_by_year = {}
    for yr in [2024, 2025, 2026]:
        print(f"\n  Loading 1s OHLC for {yr}...", flush=True)
        df = load_1s_ohlc(ONE_S_PATHS[yr])
        bars_by_year[yr] = {
            "ts": df["ts_event_ns"].to_numpy(),
            "h": df["high"].to_numpy(),
            "l": df["low"].to_numpy(),
        }
        print(f"    {len(df):,} bars ({time.time()-t0:.0f}s)")

    # Run simulation on FULL V_A
    print(f"\n  Simulating BE @0.75 on ALL V_A trades (1s precision)...")
    t1 = time.time()
    full_res = simulate_cohort(preds, bars_by_year)
    print(f"    ({time.time()-t1:.0f}s)")

    print(f"\n{'='*78}")
    print(f"RESULTS — 1s-precise BE @0.75")
    print(f"{'='*78}")
    report("FULL V_A", full_res)

    top = full_res[full_res["p_unr075"] >= TOP50_THRESHOLD]
    bot = full_res[full_res["p_unr075"] < TOP50_THRESHOLD]
    report("TOP 50% ML cohort", top)
    report("BOT 50% ML cohort", bot)

    # Comparison to path_checkpoint sim numbers
    print(f"\n{'='*78}")
    print(f"COMPARISON: path_checkpoint sim vs 1s-precise sim")
    print(f"{'='*78}")
    print(f"\n  Top 50% combined (3,400 trades):")
    print(f"    Path_checkpoint sim BE lift: +$103,815  (claimed)")
    print(f"    1s-precise sim BE lift:      "
          f"${top['pnl_v1'].sum() - top['pnl_baseline'].sum():+,.0f}")
    print(f"\n  Bot 50% combined (3,428 trades):")
    print(f"    Path_checkpoint sim BE lift: +$105,010  (claimed)")
    print(f"    1s-precise sim BE lift:      "
          f"${bot['pnl_v1'].sum() - bot['pnl_baseline'].sum():+,.0f}")
    print(f"\n  Combined ALL V_A (6,828 trades):")
    print(f"    Path_checkpoint sim BE lift: +$208,825  (claimed)")
    print(f"    1s-precise sim BE lift:      "
          f"${full_res['pnl_v1'].sum() - full_res['pnl_baseline'].sum():+,.0f}")

    # Per-trade lift comparison
    print(f"\n  Per-trade lift comparison (does ML filter matter?):")
    top_lift = (top["pnl_v1"].sum() - top["pnl_baseline"].sum()) / len(top)
    bot_lift = (bot["pnl_v1"].sum() - bot["pnl_baseline"].sum()) / len(bot)
    print(f"    Top 50% per-trade lift: ${top_lift:+.2f}/tr")
    print(f"    Bot 50% per-trade lift: ${bot_lift:+.2f}/tr")
    print(f"    Top - Bot diff:         ${top_lift - bot_lift:+.2f}/tr")

    # 2026-specific check
    print(f"\n  2026 OOS specifically:")
    for label, sub in [("ALL V_A", full_res), ("Top 50%", top),
                          ("Bot 50%", bot)]:
        yr_sub = sub[sub["year"] == 2026]
        b = yr_sub["pnl_baseline"].sum()
        v = yr_sub["pnl_v1"].sum()
        print(f"    {label:<10}  n={len(yr_sub):>4}  "
              f"base=${b:>+8,.0f}  v1=${v:>+8,.0f}  Δ=${v-b:>+7,.0f}")

    full_res.to_parquet(OUT / "be_1s_precise_results.parquet")
    print(f"\nSaved: {OUT / 'be_1s_precise_results.parquet'}")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
