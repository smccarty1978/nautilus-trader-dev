"""MA entry-quality filter sweep on Group A v-recovery design.

DESIGN
------
Trade mechanics UNCHANGED from +$72K baseline:
  C1: 1 contract initial entry, prior_SL, full PT
  C2: dip + 1m re-cross + MAE >= 3 trigger, prior_SL, full PT

NEW: apply MA filter at trigger detection. If filter fails, SKIP the
entire trade (no C1 entry). Otherwise enter as normal.

MAs computed on 1m close prices (no look-ahead — value at trigger
bar's close):
  EMA13, EMA21, SMA21, EMA50

Filters tested:
  F1 (price vs MA):
    long pass if close > MA; short pass if close < MA
  F2 (MA slope):
    long pass if MA[t] > MA[t-1]; short pass if MA[t] < MA[t-1]
  F3 (distance from MA):
    pass if abs(close - MA) <= threshold pts
  F1+F2: both must pass
  F1+F2+F3: all three must pass

For each filter cell:
  trades_kept count + per-bucket kept rate
  net PnL (with v-recovery design on filtered population)
  per-year split

Goal: find a filter that removes more loser dollars than winner dollars.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m, annotate_sessions_ct,
)
from studies.level_momentum_continuation.analyze_breakout_filter import (
    detect_triggers_breakout, assign_group,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, precompute_eod_1s, map_1m_trigger_to_1s_entry,
)
from studies.level_momentum_continuation.analyze_2contract_tp5_be import (
    sim_baseline_path, assign_bucket,
    NQ_DOLLAR_PER_PT, COMMISSION_PTS,
)
from studies.level_momentum_continuation.analyze_vshape_recross_addon import (
    sim_recross,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)


def harvest_with_mas(year):
    """Like the standard harvest, but attach MA values from 1m bars
    at trigger close time."""
    print(f"\n[{year}] loading & attaching MAs to triggers...")
    bars_1s = load_v0_1s(Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
    bars_1s = annotate_sessions_1s(bars_1s)
    bars_1m = bars_1s[
        ["open", "high", "low", "close", "volume"]
    ].resample("1min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(subset=["open", "high", "low", "close"])
    bars_1m = annotate_sessions_ct(bars_1m)

    # Compute MAs on 1m close prices (causal, no lookahead)
    bars_1m["ema13"] = bars_1m["close"].ewm(span=13, adjust=False).mean()
    bars_1m["ema21"] = bars_1m["close"].ewm(span=21, adjust=False).mean()
    bars_1m["sma21"] = bars_1m["close"].rolling(21).mean()
    bars_1m["ema50"] = bars_1m["close"].ewm(span=50, adjust=False).mean()
    # Slopes (current - prior)
    bars_1m["ema13_slope"] = bars_1m["ema13"].diff()
    bars_1m["ema21_slope"] = bars_1m["ema21"].diff()
    bars_1m["sma21_slope"] = bars_1m["sma21"].diff()
    bars_1m["ema50_slope"] = bars_1m["ema50"].diff()
    # Distance (close - MA, signed)
    bars_1m["dist_ema13"] = bars_1m["close"] - bars_1m["ema13"]
    bars_1m["dist_ema21"] = bars_1m["close"] - bars_1m["ema21"]
    bars_1m["dist_sma21"] = bars_1m["close"] - bars_1m["sma21"]
    bars_1m["dist_ema50"] = bars_1m["close"] - bars_1m["ema50"]

    triggers = detect_triggers_breakout(bars_1m)

    bars_1s_reset = bars_1s.reset_index(drop=False)
    opens = bars_1s_reset["open"].values.astype(np.float64)
    highs = bars_1s_reset["high"].values.astype(np.float64)
    lows = bars_1s_reset["low"].values.astype(np.float64)
    closes = bars_1s_reset["close"].values.astype(np.float64)
    sessions = bars_1s_reset["session"].values
    ts_close_1s = pd.DatetimeIndex(bars_1s_reset["ts_close"])
    if ts_close_1s.tz is None:
        ts_close_1s = ts_close_1s.tz_localize("UTC")
    else:
        ts_close_1s = ts_close_1s.tz_convert("UTC")
    ts_seconds = ts_close_1s.second.values.astype(np.int32)
    next_eod = precompute_eod_1s(bars_1s_reset)

    last_chain_exit = -1
    trades = []
    for tr in triggers:
        ts = pd.Timestamp(tr["bar_ts_close"])
        if ts.tz is None: ts = ts.tz_localize("UTC")
        else: ts = ts.tz_convert("UTC")
        e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
        if e < 0: continue
        if e <= last_chain_exit: continue
        di = tr["direction"]
        entry_px = float(opens[e])
        # Run v-recovery sim (this is the +$72K design)
        r = sim_recross(
            e, di, entry_px, float(tr["breach_level"]),
            float(tr["target"]), float(tr["stop"]),
            int(next_eod[e]), opens, highs, lows, closes, ts_seconds)
        if r is None: continue
        last_chain_exit = r["exit_idx_global"]
        if sessions[e] != "RTH":
            continue
        # Attach MA values from 1m at trigger ts
        if ts not in bars_1m.index:
            continue
        ma_row = bars_1m.loc[ts]
        # Bucket assignment (using baseline path for max_mae)
        bp = sim_baseline_path(
            e, di, entry_px, float(tr["target"]),
            float(tr["stop"]), int(next_eod[e]),
            highs, lows, closes)
        if bp is None: continue
        bucket = assign_bucket(
            bp["outcome"], bp["mfe_t"], bp["mae_t"], bp["max_mfe"])
        # MAE >= 3 filter for the +$72K v-recovery: but apply later
        # to keep simple. Use the unfiltered v-recovery (+$72K).
        trades.append({
            "year": year, "level_pair": tr["level_pair"],
            "group": assign_group(tr["level_pair"]),
            "direction": di,
            "trigger_close": float(tr["close_at_breach"]),
            "ema13": float(ma_row["ema13"]),
            "ema21": float(ma_row["ema21"]),
            "sma21": float(ma_row["sma21"]),
            "ema50": float(ma_row["ema50"]),
            "ema13_slope": float(ma_row["ema13_slope"])
                            if pd.notna(ma_row["ema13_slope"]) else 0.0,
            "ema21_slope": float(ma_row["ema21_slope"])
                            if pd.notna(ma_row["ema21_slope"]) else 0.0,
            "sma21_slope": float(ma_row["sma21_slope"])
                            if pd.notna(ma_row["sma21_slope"]) else 0.0,
            "ema50_slope": float(ma_row["ema50_slope"])
                            if pd.notna(ma_row["ema50_slope"]) else 0.0,
            "dist_ema13": float(ma_row["dist_ema13"])
                            if pd.notna(ma_row["dist_ema13"]) else 0.0,
            "dist_ema21": float(ma_row["dist_ema21"])
                            if pd.notna(ma_row["dist_ema21"]) else 0.0,
            "dist_sma21": float(ma_row["dist_sma21"])
                            if pd.notna(ma_row["dist_sma21"]) else 0.0,
            "dist_ema50": float(ma_row["dist_ema50"])
                            if pd.notna(ma_row["dist_ema50"]) else 0.0,
            "bucket": bucket,
            "c1_outcome": r["c1_outcome"],
            "c2_added": r["c2_added"],
            "c2_outcome": r["c2_outcome"],
            "total_pnl_dollars": r["total_pnl_dollars"],
            "c1_only_pnl_dollars": r["c1_only_pnl_dollars"],
        })
    print(f"  RTH trades: {len(trades):,}")
    return trades


def apply_filter(trades_df, filter_func, label):
    """Apply filter to trades. Compute kept stats + PnL."""
    mask = trades_df.apply(filter_func, axis=1)
    kept = trades_df[mask]
    n = len(trades_df)
    n_kept = len(kept)
    if n == 0:
        return None
    total_kept = float(kept["total_pnl_dollars"].sum())
    y2024 = float(
        kept[kept["year"]==2024]["total_pnl_dollars"].sum())
    y2025 = float(
        kept[kept["year"]==2025]["total_pnl_dollars"].sum())
    out = {
        "filter": label,
        "n_total": n,
        "n_kept": n_kept,
        "kept_pct": 100 * n_kept / n,
        "total_$": total_kept,
        "y2024_$": y2024,
        "y2025_$": y2025,
    }
    # Per-bucket kept stats
    for bk in ("win_clean", "win_vshape",
               "loss_runthenbreak", "loss_quick"):
        sub_all = trades_df[trades_df["bucket"] == bk]
        sub_kept = kept[kept["bucket"] == bk]
        n_bk = len(sub_all)
        n_bk_kept = len(sub_kept)
        if n_bk == 0:
            continue
        out[f"{bk}_total"] = n_bk
        out[f"{bk}_kept"] = n_bk_kept
        out[f"{bk}_kept_pct"] = 100 * n_bk_kept / n_bk
        out[f"{bk}_kept_$"] = float(sub_kept["total_pnl_dollars"].sum())
    return out


# ---------------- Filter functions ----------------

def make_price_vs_ma_filter(ma_col):
    def f(row):
        if row["direction"] == 1:
            return row["trigger_close"] > row[ma_col]
        else:
            return row["trigger_close"] < row[ma_col]
    return f


def make_slope_filter(slope_col):
    def f(row):
        if row["direction"] == 1:
            return row["slope_col"] > 0 if "slope_col" in row else row[slope_col] > 0
        else:
            return row[slope_col] < 0
    return f


def make_dist_filter(dist_col, threshold):
    """Pass if |close - MA| <= threshold (long: close above MA, but
    not too far; short: close below MA, but not too far)."""
    def f(row):
        d = row[dist_col]
        if row["direction"] == 1:
            # For long: close > MA AND distance not too large
            return 0 < d <= threshold
        else:
            return -threshold <= d < 0
    return f


def make_combined(price_filter, slope_filter):
    def f(row):
        return price_filter(row) and slope_filter(row)
    return f


def main():
    t0 = time.time()
    all_trades = []
    for year in (2024, 2025):
        ts = harvest_with_mas(year)
        all_trades.extend(ts)
    df = pd.DataFrame(all_trades)
    print(f"\nTotal RTH trades: {len(df):,}")

    # Focus on Group A
    g = df[df["group"] == "A_25pt"].copy()
    print(f"Group A trades: {len(g):,}")

    # Baseline (no filter, +$72K)
    base_total = float(g["total_pnl_dollars"].sum())
    base_y24 = float(g[g["year"]==2024]["total_pnl_dollars"].sum())
    base_y25 = float(g[g["year"]==2025]["total_pnl_dollars"].sum())
    print(f"\nBASELINE (no MA filter): total ${base_total:+,.0f} "
          f"(2024 ${base_y24:+,.0f} / 2025 ${base_y25:+,.0f})")

    print(f"\n{'='*78}\nMA ENTRY FILTERS — Group A only\n{'='*78}")

    rows = []

    # ----- F1: price vs MA -----
    print(f"\n--- F1: price vs MA (long: close>MA, short: close<MA) ---")
    for ma in ("ema13", "ema21", "sma21", "ema50"):
        out = apply_filter(g, make_price_vs_ma_filter(ma),
                            f"F1_{ma}")
        if out is None: continue
        rows.append(out)
        print(f"  {out['filter']:<22} kept {out['n_kept']:>5,}/{out['n_total']:,} "
              f"({out['kept_pct']:>5.1f}%)  total ${out['total_$']:+,.0f}  "
              f"(2024 ${out['y2024_$']:+,.0f} / 2025 ${out['y2025_$']:+,.0f})")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            kp = out.get(f"{bk}_kept_pct")
            if kp is None: continue
            print(f"      {bk:<22} kept {kp:>4.1f}%  "
                  f"${out.get(f'{bk}_kept_$', 0):+,.0f}")

    # ----- F2: MA slope -----
    print(f"\n--- F2: MA slope > 0 (long) / < 0 (short) ---")
    for ma in ("ema13", "ema21", "sma21", "ema50"):
        out = apply_filter(g, make_slope_filter(f"{ma}_slope"),
                            f"F2_{ma}")
        if out is None: continue
        rows.append(out)
        print(f"  {out['filter']:<22} kept {out['n_kept']:>5,}/{out['n_total']:,} "
              f"({out['kept_pct']:>5.1f}%)  total ${out['total_$']:+,.0f}  "
              f"(2024 ${out['y2024_$']:+,.0f} / 2025 ${out['y2025_$']:+,.0f})")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            kp = out.get(f"{bk}_kept_pct")
            if kp is None: continue
            print(f"      {bk:<22} kept {kp:>4.1f}%  "
                  f"${out.get(f'{bk}_kept_$', 0):+,.0f}")

    # ----- F3: Distance bound -----
    print(f"\n--- F3: distance from MA (close on right side AND not too far) ---")
    for ma in ("ema13", "ema21", "sma21", "ema50"):
        for thr in (10, 15, 20, 30):
            out = apply_filter(g,
                make_dist_filter(f"dist_{ma}", thr),
                f"F3_{ma}_{thr}pt")
            if out is None: continue
            rows.append(out)
            print(f"  {out['filter']:<25} kept {out['n_kept']:>5,}/{out['n_total']:,} "
                  f"({out['kept_pct']:>5.1f}%)  total ${out['total_$']:+,.0f}  "
                  f"(2024 ${out['y2024_$']:+,.0f} / 2025 ${out['y2025_$']:+,.0f})")

    # ----- F1 + F2 combined -----
    print(f"\n--- F1+F2: price vs MA AND slope (both must pass) ---")
    for ma in ("ema13", "ema21", "sma21", "ema50"):
        out = apply_filter(g,
            make_combined(make_price_vs_ma_filter(ma),
                           make_slope_filter(f"{ma}_slope")),
            f"F1+F2_{ma}")
        if out is None: continue
        rows.append(out)
        print(f"  {out['filter']:<22} kept {out['n_kept']:>5,}/{out['n_total']:,} "
              f"({out['kept_pct']:>5.1f}%)  total ${out['total_$']:+,.0f}  "
              f"(2024 ${out['y2024_$']:+,.0f} / 2025 ${out['y2025_$']:+,.0f})")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            kp = out.get(f"{bk}_kept_pct")
            if kp is None: continue
            print(f"      {bk:<22} kept {kp:>4.1f}%  "
                  f"${out.get(f'{bk}_kept_$', 0):+,.0f}")

    pd.DataFrame(rows).to_csv(
        OUT / "ma_entry_filter.csv", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.1f}s")
    print(f"saved: {OUT / 'ma_entry_filter.csv'}")

    # ---- Top 5 cells ----
    df_r = pd.DataFrame(rows)
    df_r["pass_both"] = (
        (df_r["y2024_$"] > 0) & (df_r["y2025_$"] > 0))
    print(f"\n{'='*78}\nTOP 5 CELLS BY TOTAL PnL (positive both years)\n{'='*78}")
    pp = df_r[df_r["pass_both"]].nlargest(5, "total_$")
    for _, r in pp.iterrows():
        print(f"  {r['filter']:<25} kept {int(r['n_kept']):>5,} "
              f"({r['kept_pct']:>5.1f}%)  total ${r['total_$']:+,.0f}  "
              f"(2024 ${r['y2024_$']:+,.0f} / 2025 ${r['y2025_$']:+,.0f})  "
              f"vs base {base_total:+.0f}: Δ${r['total_$']-base_total:+,.0f}")


if __name__ == "__main__":
    main()
