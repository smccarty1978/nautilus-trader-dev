"""Fallback PT/SL/timeout bracket for no-flip cohort, with optional
regime-flip transition to confirmed-mode hold.

State machine (for no-flip trades only):
  [entry, +60s]   : hold, no exit
  [+60s, timeout] : bracket active (PT, SL, regime-flip transition)
  at timeout      : exit at bar close
  if regime flips in our direction at any minute close within bracket:
      transition to confirmed-mode (hold to next opposite regime flip)

VA-confirm trades keep their baseline exit (already actual NT MBP-1 PnL).

Grid:
  PT      = [0.75, 1.0, 1.25, 1.5]   ATR multiplier
  SL      = [0.5,  0.75, 1.0, 1.25]  ATR multiplier
  Timeout = [180, 300, 600]          seconds from entry
  + with/without regime-flip transition
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


TRADES_PATH = ("backtests/pre_flip_T1/results/"
                  "nt_mbp1_2026_top10_N20/trades_all_months.parquet")
RAW_1S = "data/raw/NQ_v0_1s_2026_ytd.parquet"
SNAPSHOTS = ("collectors/collector_v2/results/v_a_v0_2026/"
               "snapshots_with_vol_vwap.parquet")
NQ_MULT = 20.0
COMMISSION_RT = 10.0
ARTIFACT_THRESHOLD_PTS = 5.0

PT_GRID = [0.75, 1.0, 1.25, 1.5]
SL_GRID = [0.5, 0.75, 1.0, 1.25]
TIMEOUT_GRID = [180, 300, 600]
BRACKET_START_S = 60


def simulate_one(
    high_arr, low_arr, close_arr, ts_arr,
    flips_in_dir_ts, flips_opp_dir_ts,
    entry_ts, entry_px, atr, d,
    pt_atr, sl_atr, timeout_s,
    use_regime_transition,
):
    """Simulate one trade under one bracket policy.

    Returns: (exit_pnl_pts, exit_reason)
    """
    pt_level = entry_px + d * pt_atr * atr
    sl_level = entry_px - d * sl_atr * atr
    bracket_start_ts = entry_ts + BRACKET_START_S * 1_000_000_000
    bracket_end_ts = entry_ts + timeout_s * 1_000_000_000

    # Bars where bar OPEN in [bracket_start_ts, bracket_end_ts]
    # bar at index i covers [ts[i], ts[i]+1s)
    idx_lo = np.searchsorted(ts_arr, bracket_start_ts, side="left")
    idx_hi = np.searchsorted(ts_arr, bracket_end_ts, side="right")
    if idx_lo >= len(ts_arr):
        return 0.0, "no_data"
    idx_hi = min(idx_hi, len(ts_arr))
    if idx_hi <= idx_lo:
        return 0.0, "no_data"

    h = high_arr[idx_lo:idx_hi]
    l = low_arr[idx_lo:idx_hi]
    c = close_arr[idx_lo:idx_hi]
    t = ts_arr[idx_lo:idx_hi]

    # Bar-by-bar PT/SL detection
    if d == 1:
        pt_touch = h >= pt_level
        sl_touch = l <= sl_level
    else:
        pt_touch = l <= pt_level
        sl_touch = h >= sl_level

    pt_first = np.argmax(pt_touch) if pt_touch.any() else -1
    sl_first = np.argmax(sl_touch) if sl_touch.any() else -1

    # Regime flip transition (only if enabled)
    transition_idx = -1
    if use_regime_transition:
        # Find regime flips in our direction at minute boundaries
        # within [bracket_start_ts, bracket_end_ts]
        rel = flips_in_dir_ts[
            (flips_in_dir_ts >= bracket_start_ts)
            & (flips_in_dir_ts <= bracket_end_ts)]
        if len(rel) > 0:
            first_flip_ts = int(rel[0])
            transition_idx = int(np.searchsorted(t, first_flip_ts,
                                                       side="left"))
            if transition_idx >= len(t):
                transition_idx = -1

    # Determine which event fires first (smallest non-neg index)
    events = []
    if pt_first >= 0:
        events.append((pt_first, "PT", pt_level))
    if sl_first >= 0:
        events.append((sl_first, "SL", sl_level))
    if transition_idx >= 0:
        events.append((transition_idx, "REGIME", None))

    if not events:
        # Timeout
        exit_px = c[-1]
        return (exit_px - entry_px) * d, "TO"

    events.sort(key=lambda e: e[0])
    first_idx, reason, level = events[0]

    # Same-bar PT+SL tie: pessimistic (assume SL fires first)
    if reason == "PT" and sl_first == first_idx:
        reason = "SL"
        level = sl_level

    if reason == "PT":
        return (pt_level - entry_px) * d, "PT"
    elif reason == "SL":
        return (sl_level - entry_px) * d, "SL"
    elif reason == "REGIME":
        # Transition to confirmed-mode: hold to next opposite flip
        # after the transition_idx
        trans_ts = int(t[first_idx])
        opp_after = flips_opp_dir_ts[
            flips_opp_dir_ts > trans_ts]
        if len(opp_after) == 0:
            # No opposite flip — exit at last available bar
            exit_px = close_arr[-1]
        else:
            exit_ts = int(opp_after[0])
            exit_idx = np.searchsorted(ts_arr, exit_ts, side="left")
            exit_idx = min(exit_idx, len(ts_arr) - 1)
            exit_px = close_arr[exit_idx]
        return (exit_px - entry_px) * d, "REGIME"


def main():
    t0 = time.time()
    print("Loading inputs...")

    trades = pd.read_parquet(TRADES_PATH)
    trades = trades[trades["exit_filled"]].copy().reset_index(drop=True)
    trades["entry_ts_ns"] = trades["entry_ts_ns"].astype("int64")
    trades["exit_ts_ns"] = trades["exit_ts_ns"].astype("int64")

    # Load 1s bars
    bars = pd.read_parquet(RAW_1S,
                              columns=["open", "high", "low", "close"])
    bars.index = pd.to_datetime(bars.index, utc=True)
    bars = bars.sort_index()
    ts_arr = bars.index.view("int64")
    high_arr = bars["high"].to_numpy().astype("float64")
    low_arr = bars["low"].to_numpy().astype("float64")
    close_arr = bars["close"].to_numpy().astype("float64")

    # Load regime flips
    snap = pd.read_parquet(SNAPSHOTS,
                              columns=["kind", "decision_ts",
                                        "direction", "session"])
    flips = snap[(snap["kind"] == "regime_flip")
                    & (snap["session"] == "RTH")].copy()
    flips["decision_ts"] = flips["decision_ts"].astype("int64")
    flips["flip_close_ts"] = flips["decision_ts"] - 1_000_000_000
    flips = flips.sort_values("decision_ts").reset_index(drop=True)
    flips_up_ts = flips[flips["direction"] == 1
                          ]["flip_close_ts"].to_numpy()
    flips_dn_ts = flips[flips["direction"] == -1
                          ]["flip_close_ts"].to_numpy()
    print(f"  {len(trades):,} trades  "
          f"{len(flips):,} regime flips  "
          f"{len(bars):,} 1s bars  ({time.time()-t0:.0f}s)")

    # Filter data-artifact trades
    trades["exit_idx"] = np.searchsorted(ts_arr,
                                                trades["exit_ts_ns"].values,
                                                side="left")
    trades["exit_idx"] = trades["exit_idx"].clip(0, len(ts_arr) - 1)
    trades["bar_close_at_exit"] = close_arr[trades["exit_idx"].values]
    trades["artifact_diff"] = (
        trades["bar_close_at_exit"] - trades["exit_fill_price"]).abs()
    artifact_mask = trades["artifact_diff"] > ARTIFACT_THRESHOLD_PTS
    n_drop = int(artifact_mask.sum())
    trades = trades[~artifact_mask].copy().reset_index(drop=True)
    print(f"  Dropped {n_drop} artifact trades, working with "
          f"{len(trades):,}")

    no_flip = trades[~trades["is_va_confirm"]].copy().reset_index(drop=True)
    va = trades[trades["is_va_confirm"]].copy().reset_index(drop=True)
    print(f"  No-flip cohort: {len(no_flip):,}  "
          f"VA-confirm: {len(va):,}")
    print(f"  VA baseline: ${va['net_pnl'].sum():+,.0f}  "
          f"(${va['net_pnl'].mean():+.2f}/tr)")
    print(f"  No-flip baseline (current 60s): "
          f"${no_flip['net_pnl'].sum():+,.0f}  "
          f"(${no_flip['net_pnl'].mean():+.2f}/tr)")
    print()

    va_total = va["net_pnl"].sum()

    rows = []
    for use_regime in [False, True]:
        for pt_atr in PT_GRID:
            for sl_atr in SL_GRID:
                for to_s in TIMEOUT_GRID:
                    pnls_pts = []
                    reasons = []
                    for _, tr in no_flip.iterrows():
                        pnl_pts, reason = simulate_one(
                            high_arr, low_arr, close_arr, ts_arr,
                            flips_up_ts if tr["direction"] == 1
                                else flips_dn_ts,
                            flips_dn_ts if tr["direction"] == 1
                                else flips_up_ts,
                            int(tr["entry_ts_ns"]),
                            float(tr["entry_fill_price"]),
                            float(tr["atr_at_signal"]),
                            int(tr["direction"]),
                            pt_atr, sl_atr, to_s, use_regime)
                        pnls_pts.append(pnl_pts)
                        reasons.append(reason)
                    pnls_pts = np.array(pnls_pts)
                    gross = pnls_pts * NQ_MULT
                    net = gross - COMMISSION_RT
                    reasons_s = pd.Series(reasons)
                    nf_total = net.sum()
                    total = va_total + nf_total
                    n = len(net)
                    wr = (net > 0).mean()
                    pt_rate = (reasons_s == "PT").mean()
                    sl_rate = (reasons_s == "SL").mean()
                    to_rate = (reasons_s == "TO").mean()
                    rg_rate = (reasons_s == "REGIME").mean()
                    rows.append({
                        "regime_xfer": use_regime,
                        "pt_atr": pt_atr,
                        "sl_atr": sl_atr,
                        "timeout_s": to_s,
                        "nf_total": nf_total,
                        "nf_per_tr": net.mean(),
                        "nf_wr": wr,
                        "combined_total": total,
                        "combined_per_tr": total / (len(no_flip)
                                                    + len(va)),
                        "pt_rate": pt_rate,
                        "sl_rate": sl_rate,
                        "to_rate": to_rate,
                        "rg_rate": rg_rate,
                    })

    grid = pd.DataFrame(rows)
    grid.to_parquet(
        "studies/v_a_excursion_regime/results_v0/"
        "fallback_bracket_grid.parquet", index=False)

    # Print top results
    print("=" * 90)
    print("TOP 20 (combined VA + no-flip cohort, by combined total)")
    print("=" * 90)
    top = grid.sort_values("combined_total", ascending=False).head(20)
    print(f"{'xfer':<5} {'PT':<5} {'SL':<6} {'TO':<5} "
          f"{'NF$':>9} {'NF/tr':>7} {'NF WR':>6} "
          f"{'Comb$':>9} {'Comb/tr':>8}  "
          f"PT%/SL%/TO%/RG%")
    for _, r in top.iterrows():
        xfer = "Y" if r["regime_xfer"] else "N"
        print(f"{xfer:<5} {r['pt_atr']:<5} {r['sl_atr']:<6} "
              f"{int(r['timeout_s']):<5} "
              f"${r['nf_total']:>+7,.0f} "
              f"${r['nf_per_tr']:>+5.2f} "
              f"{r['nf_wr']:>5.1%} "
              f"${r['combined_total']:>+7,.0f} "
              f"${r['combined_per_tr']:>+6.2f}  "
              f"{r['pt_rate']:>3.0%}/{r['sl_rate']:>3.0%}/"
              f"{r['to_rate']:>3.0%}/{r['rg_rate']:>3.0%}")

    print(f"\nBaselines:")
    print(f"  Combined actual: ${trades['net_pnl'].sum():+,.0f}  "
          f"(${trades['net_pnl'].mean():+.2f}/tr)")
    print(f"  VA only: ${va_total:+,.0f}  "
          f"(${va_total/len(va):+.2f}/tr)")
    print(f"  No-flip actual: "
          f"${no_flip['net_pnl'].sum():+,.0f}  "
          f"(${no_flip['net_pnl'].mean():+.2f}/tr)")

    # User's first default
    default = grid[(grid["pt_atr"] == 1.0) & (grid["sl_atr"] == 0.75)
                       & (grid["timeout_s"] == 300)]
    print(f"\nUser's first default (PT=1.0, SL=0.75, TO=300s):")
    for _, r in default.iterrows():
        xfer = "with" if r["regime_xfer"] else "without"
        print(f"  {xfer} regime transition: "
              f"NF=${r['nf_total']:+,.0f} (${r['nf_per_tr']:+.2f}/tr)  "
              f"Combined=${r['combined_total']:+,.0f} "
              f"(${r['combined_per_tr']:+.2f}/tr)  "
              f"PT%={r['pt_rate']:.0%}/SL%={r['sl_rate']:.0%}/"
              f"TO%={r['to_rate']:.0%}/RG%={r['rg_rate']:.0%}")

    # Show effect of regime transition
    print(f"\nEffect of regime-flip transition (paired):")
    print(f"  {'PT':<5} {'SL':<6} {'TO':<5} "
          f"{'no-xfer NF$':>11} {'with-xfer NF$':>13} {'Δ':>8}")
    pivoted = grid.pivot_table(
        index=["pt_atr", "sl_atr", "timeout_s"],
        columns="regime_xfer", values="nf_total").reset_index()
    pivoted["delta"] = pivoted[True] - pivoted[False]
    pivoted = pivoted.sort_values("delta", ascending=False).head(10)
    for _, r in pivoted.iterrows():
        print(f"  {r['pt_atr']:<5} {r['sl_atr']:<6} "
              f"{int(r['timeout_s']):<5} "
              f"${r[False]:>+9,.0f} ${r[True]:>+11,.0f} "
              f"${r['delta']:>+6,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
