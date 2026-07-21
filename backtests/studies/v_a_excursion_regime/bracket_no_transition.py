"""Bracket WITHOUT regime-flip transition.

Policy:
- VA-confirm trades: hold to regime flip (current behavior, unchanged)
- No-flip trades: PT / SL / Timeout bracket, NO regime transition

Compares 3 policies side-by-side:
  BL  = Baseline (current +60s exit on no-flip)
  BR+ = Bracket WITH regime transition (prior run, has issues)
  BR- = Bracket WITHOUT regime transition (this run)

Plus monthly breakdown per year.
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

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from bracket_2025_2026 import (
    build_schedule, apply_roll_day_filter, load_year_data,
    replay_va_baseline_1s, replay_no_flip_baseline_1s, round_tick,
    PRE_FLIP_OOS, COLLECTOR_DIR, OUT_DIR as BR_OUT_DIR,
    PT_ATR, SL_ATR, TIMEOUT_S, BRACKET_START_S, TOP_QUANTILE,
    NQ_MULT, COMMISSION_RT, ROLL_DATES, ROLL_EXCL_DAYS,
)


OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/bracket_no_xfer")


def replay_no_flip_no_xfer(
    bar_ts, bar_open, bar_high, bar_low, bar_close,
    entry_ts_ns, direction, atr_at_signal,
):
    """No-flip bracket without regime-flip transition.

    PT (limit): exact PT level
    SL (stop):  fill at NEXT 1s bar OPEN after touch
    TO:         bar.close at timeout_ts (no regime exit)
    """
    d = direction
    entry_idx = int(np.searchsorted(bar_ts, entry_ts_ns, side="right"))
    if entry_idx >= len(bar_ts):
        return None
    entry_fill = float(bar_open[entry_idx])

    if d == 1:
        pt_level = round_tick(entry_fill + PT_ATR * atr_at_signal,
                                  "down")
        sl_level = round_tick(entry_fill - SL_ATR * atr_at_signal,
                                  "up")
    else:
        pt_level = round_tick(entry_fill - PT_ATR * atr_at_signal,
                                  "up")
        sl_level = round_tick(entry_fill + SL_ATR * atr_at_signal,
                                  "down")

    bracket_start_ts = entry_ts_ns + BRACKET_START_S * 1_000_000_000
    timeout_ts = entry_ts_ns + TIMEOUT_S * 1_000_000_000
    bs_idx = int(np.searchsorted(bar_ts, bracket_start_ts,
                                       side="right"))
    to_idx = int(np.searchsorted(bar_ts, timeout_ts, side="right"))
    to_idx = min(to_idx, len(bar_ts) - 1)
    if bs_idx >= to_idx:
        return None

    h = bar_high[bs_idx:to_idx + 1]
    l = bar_low[bs_idx:to_idx + 1]
    if d == 1:
        pt_touch = h >= pt_level
        sl_touch = l <= sl_level
    else:
        pt_touch = l <= pt_level
        sl_touch = h >= sl_level
    pt_first = int(np.argmax(pt_touch)) if pt_touch.any() else -1
    sl_first = int(np.argmax(sl_touch)) if sl_touch.any() else -1

    events = []
    if pt_first >= 0:
        events.append((bs_idx + pt_first, "PT", pt_level))
    if sl_first >= 0:
        sl_bar_idx = bs_idx + sl_first
        next_idx = sl_bar_idx + 1
        if next_idx >= len(bar_ts):
            next_idx = sl_bar_idx
        events.append((sl_bar_idx, "SL", float(bar_open[next_idx])))

    if not events:
        return {
            "entry_ts_ns": entry_ts_ns,
            "entry_fill_price": entry_fill,
            "exit_ts_ns": int(bar_ts[to_idx]),
            "exit_fill_price": float(bar_close[to_idx]),
            "direction": d, "atr_at_signal": atr_at_signal,
            "pt_level": pt_level, "sl_level": sl_level,
            "exit_reason": "TO",
        }

    events.sort(key=lambda e: e[0])
    first_idx, reason, fill_price = events[0]
    if reason == "PT" and sl_first == pt_first:
        # same-bar tie: pessimistic SL
        reason = "SL"
        sl_bar_idx = bs_idx + sl_first
        next_idx = sl_bar_idx + 1
        if next_idx >= len(bar_ts):
            next_idx = sl_bar_idx
        fill_price = float(bar_open[next_idx])
        first_idx = sl_bar_idx

    return {
        "entry_ts_ns": entry_ts_ns,
        "entry_fill_price": entry_fill,
        "exit_ts_ns": int(bar_ts[first_idx]),
        "exit_fill_price": fill_price,
        "direction": d, "atr_at_signal": atr_at_signal,
        "pt_level": pt_level, "sl_level": sl_level,
        "exit_reason": reason,
    }


def run_year(year, oos_df, threshold):
    print(f"\n{'='*78}")
    print(f"YEAR {year} — bracket WITHOUT regime transition")
    print(f"{'='*78}")
    t0 = time.time()
    sched = build_schedule(
        oos_df, year, threshold,
        f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
        f"{COLLECTOR_DIR}/v_a_v0_{year}/"
        f"snapshots_with_vol_vwap.parquet")
    n_pre = len(sched)
    sched, n_drop = apply_roll_day_filter(sched, "entry_ts_ns", year)
    print(f"  Schedule: {n_pre:,} → {len(sched):,} after roll-day "
          f"exclusion (-{n_drop})")
    print(f"  Loading data...")
    bar_ts, bar_open, bar_high, bar_low, bar_close, _, _ = \
        load_year_data(year)

    results = []
    for _, tr in sched.iterrows():
        d = int(tr["direction"])
        if bool(tr["is_va_confirm"]):
            r = replay_va_baseline_1s(
                bar_ts, bar_open,
                int(tr["entry_ts_ns"]),
                int(tr["exit_ts_ns"]), d)
            if r is not None:
                r["is_va_confirm"] = True
                r["exit_reason"] = "VA_BASELINE"
                r["atr_at_signal"] = float(tr["atr_at_signal"])
                results.append(r)
        else:
            r = replay_no_flip_no_xfer(
                bar_ts, bar_open, bar_high, bar_low, bar_close,
                int(tr["entry_ts_ns"]), d,
                float(tr["atr_at_signal"]))
            if r is not None:
                r["is_va_confirm"] = False
                results.append(r)
    df = pd.DataFrame(results)
    df["pnl_pts"] = (
        (df["exit_fill_price"] - df["entry_fill_price"])
        * df["direction"])
    df["gross_pnl"] = df["pnl_pts"] * NQ_MULT
    df["net_pnl"] = df["gross_pnl"] - COMMISSION_RT
    df["year"] = year
    df["entry_dt"] = pd.to_datetime(df["entry_ts_ns"], unit="ns",
                                          utc=True)
    df["month"] = df["entry_dt"].dt.month

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_DIR / f"replay_no_xfer_1s_{year}.parquet",
                       index=False)
    print(f"  Done ({time.time()-t0:.0f}s)  n={len(df):,}")
    print(f"  Total: ${df['net_pnl'].sum():+,.0f}  "
          f"${df['net_pnl'].mean():+.2f}/tr  "
          f"WR={(df['net_pnl']>0).mean():.1%}")
    va = df[df["is_va_confirm"]]
    nf = df[~df["is_va_confirm"]]
    print(f"  VA-confirm: n={len(va)}  "
          f"${va['net_pnl'].sum():+,.0f}  "
          f"${va['net_pnl'].mean():+.2f}/tr")
    print(f"  No-flip:    n={len(nf)}  "
          f"${nf['net_pnl'].sum():+,.0f}  "
          f"${nf['net_pnl'].mean():+.2f}/tr")
    print(f"  No-flip exit reasons:")
    for reason in ["PT", "SL", "TO"]:
        sub = nf[nf["exit_reason"] == reason]
        if len(sub) > 0:
            print(f"    {reason:<5}: n={len(sub):>4}  "
                  f"({len(sub)/len(nf):>5.1%})  "
                  f"${sub['net_pnl'].sum():+9,.0f}  "
                  f"${sub['net_pnl'].mean():+.2f}/tr  "
                  f"WR={(sub['net_pnl']>0).mean():.1%}")
    del bar_ts, bar_open, bar_high, bar_low, bar_close
    gc.collect()
    return df


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Policy: PT={PT_ATR} / SL={SL_ATR} / TO={TIMEOUT_S}s  "
          f"NO regime transition (timeout instead)")
    oos = pd.read_parquet(PRE_FLIP_OOS)
    threshold = oos["p_score"].quantile(1 - TOP_QUANTILE)
    print(f"Threshold: p >= {threshold:.4f}")

    df_25 = run_year(2025, oos, threshold)
    df_26 = run_year(2026, oos, threshold)

    # Load comparison data
    bl_25 = pd.read_parquet(BR_OUT_DIR / "baseline_1s_2025.parquet")
    bl_26 = pd.read_parquet(BR_OUT_DIR / "baseline_1s_2026.parquet")
    bp_25 = pd.read_parquet(BR_OUT_DIR / "replay_1s_2025.parquet")
    bp_26 = pd.read_parquet(BR_OUT_DIR / "replay_1s_2026.parquet")

    # Side-by-side
    print(f"\n{'='*100}")
    print(f"THREE-POLICY COMPARISON (1s bar mode)")
    print(f"{'='*100}")
    print(f"  BL  = Baseline (+60s exit on no-flip, hold-to-flip on VA)")
    print(f"  BR+ = Bracket WITH regime transition")
    print(f"  BR- = Bracket WITHOUT regime transition (PT/SL/TO only)")
    print()
    print(f"  {'Year':<6} {'BL $':>10} {'BL $/tr':>9} "
          f"{'BR+ $':>10} {'BR+ $/tr':>10} "
          f"{'BR- $':>10} {'BR- $/tr':>10}")
    for year, bl, bp, br in [(2025, bl_25, bp_25, df_25),
                                      (2026, bl_26, bp_26, df_26)]:
        print(f"  {year:<6} "
              f"${bl['net_pnl'].sum():>+8,.0f} "
              f"${bl['net_pnl'].mean():>+7.2f} "
              f"${bp['net_pnl'].sum():>+8,.0f} "
              f"${bp['net_pnl'].mean():>+8.2f} "
              f"${br['net_pnl'].sum():>+8,.0f} "
              f"${br['net_pnl'].mean():>+8.2f}")

    # Monthly breakdown for each policy per year
    for year, bl, bp, br in [(2025, bl_25, bp_25, df_25),
                                      (2026, bl_26, bp_26, df_26)]:
        for df in [bl, bp, br]:
            if "month" not in df.columns:
                df["entry_dt"] = pd.to_datetime(
                    df["entry_ts_ns"], unit="ns", utc=True)
                df["month"] = df["entry_dt"].dt.month
        print(f"\n{'='*100}")
        print(f"YEAR {year} — MONTHLY BREAKDOWN")
        print(f"{'='*100}")
        print(f"  {'Mo':<4} {'n':>5} "
              f"{'BL $':>10} {'BL $/tr':>9} "
              f"{'BR+ $':>10} {'BR+ $/tr':>10} "
              f"{'BR- $':>10} {'BR- $/tr':>10}  "
              f"{'BR- vs BL':>10}")
        for mo in sorted(br["month"].unique()):
            bl_m = bl[bl["month"] == mo]
            bp_m = bp[bp["month"] == mo]
            br_m = br[br["month"] == mo]
            delta = br_m['net_pnl'].sum() - bl_m['net_pnl'].sum()
            print(f"  {mo:<4} {len(br_m):>5,} "
                  f"${bl_m['net_pnl'].sum():>+8,.0f} "
                  f"${bl_m['net_pnl'].mean():>+7.2f} "
                  f"${bp_m['net_pnl'].sum():>+8,.0f} "
                  f"${bp_m['net_pnl'].mean():>+8.2f} "
                  f"${br_m['net_pnl'].sum():>+8,.0f} "
                  f"${br_m['net_pnl'].mean():>+8.2f}  "
                  f"${delta:>+9,.0f}")
        n_pos = sum(1 for mo in sorted(br["month"].unique())
                       if br[br["month"] == mo]["net_pnl"].sum() > 0)
        n_tot = len(br["month"].unique())
        print(f"  Positive months (BR-): {n_pos}/{n_tot}")

    # Year-stack stability
    print(f"\n{'='*100}")
    print(f"COMBINED 2025+2026 — STABILITY ACROSS YEARS")
    print(f"{'='*100}")
    bl_all = pd.concat([bl_25, bl_26])
    bp_all = pd.concat([bp_25, bp_26])
    br_all = pd.concat([df_25, df_26])
    print(f"  Baseline (BL):      "
          f"${bl_all['net_pnl'].sum():>+9,.0f}  "
          f"${bl_all['net_pnl'].mean():>+6.2f}/tr  "
          f"WR={(bl_all['net_pnl']>0).mean():.1%}")
    print(f"  Bracket w/ xfer:    "
          f"${bp_all['net_pnl'].sum():>+9,.0f}  "
          f"${bp_all['net_pnl'].mean():>+6.2f}/tr  "
          f"WR={(bp_all['net_pnl']>0).mean():.1%}")
    print(f"  Bracket no xfer:    "
          f"${br_all['net_pnl'].sum():>+9,.0f}  "
          f"${br_all['net_pnl'].mean():>+6.2f}/tr  "
          f"WR={(br_all['net_pnl']>0).mean():.1%}")
    print(f"  BR- lift vs BL:     "
          f"${br_all['net_pnl'].sum()-bl_all['net_pnl'].sum():>+9,.0f}  "
          f"(${(br_all['net_pnl'].mean()-bl_all['net_pnl'].mean()):>+6.2f}/tr)")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
