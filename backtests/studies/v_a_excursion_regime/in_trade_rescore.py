"""In-trade model rescoring for no-flip trades.

Hypothesis:
  At each subsequent 1m bar close after entry (+60s, +120s, +180s,
  ...), check if the T-1 model STILL produces a high score for the
  same direction at that bar. If yes, the model still expects an
  imminent flip — hold. If no (or no candidate exists), exit.

Compares to baseline +60s exit on no-flip cohort.

Decision rule (per in-trade bar):
  hold if a candidate exists at that 1m close for same direction
    AND its OOS p_T1 score >= threshold_in_trade
  else exit at that bar's close (using next 1s bar OPEN)

Max hold: 600s (10 minutes).

Sweeps in-trade threshold to find the deployable parameter.
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
    build_schedule, PRE_FLIP_OOS, COLLECTOR_DIR,
    NQ_MULT, COMMISSION_RT, replay_no_flip_baseline_1s,
)
from bracket_grid_2024_2025 import (
    load_year_bars_and_flips, apply_roll_filter_year,
)


OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/in_trade_rescore")
MAX_HOLD_S = 600
RESCORE_INTERVAL_S = 60   # check at every 1m bar
TOP20_QUANTILE = 0.20


def replay_in_trade_rescore(
    bar_ts, bar_open, bar_close,
    score_lookup,   # dict (close_ts_ns, direction) -> p_T1
    entry_ts_ns, direction, in_trade_threshold,
):
    """Replay a no-flip trade with in-trade rescoring exit.

    Returns dict with entry, exit, reason.
    """
    d = direction
    eidx = int(np.searchsorted(bar_ts, entry_ts_ns, side="right"))
    if eidx >= len(bar_ts):
        return None
    entry_fill = float(bar_open[eidx])

    # Check at +60s, +120s, +180s, ..., +600s
    held_since = entry_ts_ns
    for elapsed_s in range(RESCORE_INTERVAL_S, MAX_HOLD_S + 1,
                                  RESCORE_INTERVAL_S):
        check_ts = entry_ts_ns + elapsed_s * 1_000_000_000
        # Look up score at this 1m bar close
        score = score_lookup.get((int(check_ts), d), None)
        if score is None or score < in_trade_threshold:
            # Exit at this bar's close → use next 1s bar OPEN
            exit_idx = int(np.searchsorted(bar_ts, check_ts,
                                                  side="right"))
            if exit_idx >= len(bar_ts):
                exit_idx = len(bar_ts) - 1
            exit_fill = float(bar_open[exit_idx])
            reason = ("NO_CAND"
                          if score is None else "BELOW_THRESH")
            return {
                "entry_ts_ns": entry_ts_ns,
                "entry_fill_price": entry_fill,
                "exit_ts_ns": int(bar_ts[exit_idx]),
                "exit_fill_price": exit_fill,
                "direction": d,
                "elapsed_s": elapsed_s,
                "exit_reason": reason,
                "exit_score": (score
                                  if score is not None else np.nan),
            }
    # Max hold reached
    exit_ts = entry_ts_ns + MAX_HOLD_S * 1_000_000_000
    exit_idx = int(np.searchsorted(bar_ts, exit_ts, side="right"))
    if exit_idx >= len(bar_ts):
        exit_idx = len(bar_ts) - 1
    return {
        "entry_ts_ns": entry_ts_ns,
        "entry_fill_price": entry_fill,
        "exit_ts_ns": int(bar_ts[exit_idx]),
        "exit_fill_price": float(bar_open[exit_idx]),
        "direction": d,
        "elapsed_s": MAX_HOLD_S,
        "exit_reason": "MAX_HOLD",
        "exit_score": np.nan,
    }


def replay_baseline_1s(bar_ts, bar_open, entry_ts_ns, direction):
    """Baseline: exit at +60s bar OPEN."""
    eidx = int(np.searchsorted(bar_ts, entry_ts_ns, side="right"))
    if eidx >= len(bar_ts):
        return None
    entry_fill = float(bar_open[eidx])
    exit_ts = entry_ts_ns + 60 * 1_000_000_000
    exit_idx = int(np.searchsorted(bar_ts, exit_ts, side="right"))
    if exit_idx >= len(bar_ts):
        exit_idx = len(bar_ts) - 1
    return {
        "entry_ts_ns": entry_ts_ns,
        "entry_fill_price": entry_fill,
        "exit_ts_ns": int(bar_ts[exit_idx]),
        "exit_fill_price": float(bar_open[exit_idx]),
        "direction": direction,
        "elapsed_s": 60,
        "exit_reason": "BASELINE_60S",
    }


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    oos = pd.read_parquet(PRE_FLIP_OOS)
    top20_thresh = oos["p_score"].quantile(1 - TOP20_QUANTILE)
    print(f"Top-20% entry threshold: p_T1 >= {top20_thresh:.4f}")
    print(f"Total OOS predictions: {len(oos):,}")

    # Build score lookup: (close_ts_ns, direction) -> p_T1
    print(f"Building score lookup...")
    score_lookup = {}
    for _, row in oos.iterrows():
        score_lookup[(int(row["close_ts_ns"]),
                          int(row["direction"]))] = float(
            row["p_score"])
    print(f"  Score lookup size: {len(score_lookup):,}")

    # In-trade thresholds to test
    IN_TRADE_THRESHOLDS = [
        0.0,           # any candidate = hold (very loose)
        0.0770,        # top 50% (loose)
        0.0886,        # top 30%
        0.0923,        # top 20% (same as entry)
        0.0991,        # top 10% (tighter than entry)
        0.1011,        # top 5%
    ]
    THRESH_LABELS = ["any", "top50", "top30", "top20",
                          "top10", "top5"]

    # Run per year
    print(f"\nReplaying per year (top 20% entry, no-flip cohort)...")
    all_results = {}
    for year in [2024, 2025, 2026]:
        print(f"\n  Year {year}:")
        sched = build_schedule(
            oos, year, top20_thresh,
            f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
            f"{COLLECTOR_DIR}/v_a_v0_{year}/"
            f"snapshots_with_vol_vwap.parquet")
        n_pre = len(sched)
        sched, n_drop = apply_roll_filter_year(sched, year)
        nf_sched = sched[~sched["is_va_confirm"]].copy(
            ).reset_index(drop=True)
        print(f"    schedule {n_pre:,} → {len(sched):,} after "
              f"roll-day (-{n_drop})")
        print(f"    no-flip cohort: {len(nf_sched):,}")

        bar_ts, bar_open, _, _, bar_close, _, _ = \
            load_year_bars_and_flips(year)

        # Baseline (+60s exit)
        bl_rows = []
        for _, tr in nf_sched.iterrows():
            r = replay_baseline_1s(bar_ts, bar_open,
                                          int(tr["entry_ts_ns"]),
                                          int(tr["direction"]))
            if r is not None:
                r["year"] = year
                r["pnl_pts"] = (r["exit_fill_price"]
                                    - r["entry_fill_price"]) * r["direction"]
                r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION_RT
                bl_rows.append(r)
        bl_df = pd.DataFrame(bl_rows)
        print(f"    baseline (+60s): "
              f"${bl_df['net_pnl'].sum():+,.0f}  "
              f"${bl_df['net_pnl'].mean():+.2f}/tr  "
              f"WR={(bl_df['net_pnl']>0).mean():.1%}")

        # In-trade rescore per threshold
        in_trade_results = {}
        for thr, label in zip(IN_TRADE_THRESHOLDS, THRESH_LABELS):
            rows = []
            for _, tr in nf_sched.iterrows():
                r = replay_in_trade_rescore(
                    bar_ts, bar_open, bar_close, score_lookup,
                    int(tr["entry_ts_ns"]), int(tr["direction"]),
                    thr)
                if r is not None:
                    r["year"] = year
                    r["pnl_pts"] = (r["exit_fill_price"]
                                        - r["entry_fill_price"]) * r["direction"]
                    r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION_RT
                    rows.append(r)
            df = pd.DataFrame(rows)
            in_trade_results[label] = df
            print(f"    in-trade thr={label} (>= {thr:.4f}): "
                  f"${df['net_pnl'].sum():+,.0f}  "
                  f"${df['net_pnl'].mean():+.2f}/tr  "
                  f"WR={(df['net_pnl']>0).mean():.1%}  "
                  f"hold mean={df['elapsed_s'].mean():.0f}s  "
                  f"max_hold={(df['exit_reason']=='MAX_HOLD').sum()}")

        all_results[year] = {
            "baseline": bl_df,
            "in_trade": in_trade_results,
        }
        del bar_ts, bar_open, bar_close
        gc.collect()

    # ===== Combined summary =====
    print(f"\n{'='*100}")
    print(f"NO-FLIP COHORT — In-trade rescore vs +60s baseline (top 20% entry)")
    print(f"{'='*100}")
    print(f"  Policy: at each 1m bar in-trade, exit if no candidate "
          f"OR p_T1 < threshold. Max hold {MAX_HOLD_S}s.")
    print()
    print(f"  {'Policy':<12} {'2024 n':>7} {'2024 $/tr':>10} "
          f"{'2025 n':>7} {'2025 $/tr':>10} "
          f"{'2026 n':>7} {'2026 $/tr':>10} "
          f"{'3yr tot':>10} {'min':>8}")
    # Baseline first
    bl_24 = all_results[2024]["baseline"]
    bl_25 = all_results[2025]["baseline"]
    bl_26 = all_results[2026]["baseline"]
    bl_total = bl_24["net_pnl"].sum() + bl_25["net_pnl"].sum() + bl_26["net_pnl"].sum()
    bl_min = min(bl_24["net_pnl"].mean(), bl_25["net_pnl"].mean(),
                      bl_26["net_pnl"].mean())
    print(f"  {'BL +60s':<12} "
          f"{len(bl_24):>7} ${bl_24['net_pnl'].mean():>+8.2f} "
          f"{len(bl_25):>7} ${bl_25['net_pnl'].mean():>+8.2f} "
          f"{len(bl_26):>7} ${bl_26['net_pnl'].mean():>+8.2f} "
          f"${bl_total:>+8,.0f} ${bl_min:>+6.2f}")
    for label in THRESH_LABELS:
        d24 = all_results[2024]["in_trade"][label]
        d25 = all_results[2025]["in_trade"][label]
        d26 = all_results[2026]["in_trade"][label]
        total = d24["net_pnl"].sum() + d25["net_pnl"].sum() + d26["net_pnl"].sum()
        min_pt = min(d24["net_pnl"].mean(), d25["net_pnl"].mean(),
                          d26["net_pnl"].mean())
        print(f"  {label:<12} "
              f"{len(d24):>7} ${d24['net_pnl'].mean():>+8.2f} "
              f"{len(d25):>7} ${d25['net_pnl'].mean():>+8.2f} "
              f"{len(d26):>7} ${d26['net_pnl'].mean():>+8.2f} "
              f"${total:>+8,.0f} ${min_pt:>+6.2f}")

    # Combined with VA-confirm baseline (which doesn't change)
    print(f"\n{'='*100}")
    print(f"FULL COMBINED PnL (VA-confirm hold-to-flip + in-trade NF)")
    print(f"{'='*100}")
    # Need VA-confirm baseline per year — load from existing or recompute
    from bracket_2025_2026 import replay_va_baseline_1s
    print(f"  Computing VA-confirm baseline...")
    va_totals = {}
    for year in [2024, 2025, 2026]:
        sched = build_schedule(
            oos, year, top20_thresh,
            f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
            f"{COLLECTOR_DIR}/v_a_v0_{year}/"
            f"snapshots_with_vol_vwap.parquet")
        sched, _ = apply_roll_filter_year(sched, year)
        va_sched = sched[sched["is_va_confirm"]]
        bar_ts, bar_open, _, _, _, _, _ = load_year_bars_and_flips(
            year)
        va_rows = []
        for _, tr in va_sched.iterrows():
            r = replay_va_baseline_1s(
                bar_ts, bar_open,
                int(tr["entry_ts_ns"]),
                int(tr["exit_ts_ns"]), int(tr["direction"]))
            if r is not None:
                r["pnl_pts"] = (r["exit_fill_price"]
                                    - r["entry_fill_price"]) * r["direction"]
                r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION_RT
                va_rows.append(r)
        va_totals[year] = (len(va_rows),
                                sum(r["net_pnl"] for r in va_rows))
        del bar_ts, bar_open
        gc.collect()
    print(f"  VA-confirm totals (unchanged across policies):")
    for year, (n, tot) in va_totals.items():
        print(f"    {year}: n={n}  ${tot:+,.0f}  "
              f"${tot/n if n else 0:+.2f}/tr")

    # Combined per policy
    print(f"\n  Policy           2024     2025     2026   3yr-total  min-yr/tr")
    for label_name, get_nf in [
        ("BL +60s", lambda y: all_results[y]["baseline"]),
        *[(f"in-trade {l}",
              lambda y, l=l: all_results[y]["in_trade"][l])
              for l in THRESH_LABELS]]:
        combined_per_year = {}
        for year in [2024, 2025, 2026]:
            nf = get_nf(year)
            n = va_totals[year][0] + len(nf)
            tot = va_totals[year][1] + nf["net_pnl"].sum()
            combined_per_year[year] = (n, tot, tot/n if n else 0)
        total = sum(t for n, t, _ in combined_per_year.values())
        min_per_tr = min(p for _, _, p in combined_per_year.values())
        print(f"  {label_name:<16} "
              f"${combined_per_year[2024][1]:>+7,.0f}  "
              f"${combined_per_year[2025][1]:>+7,.0f}  "
              f"${combined_per_year[2026][1]:>+7,.0f}  "
              f"${total:>+9,.0f}  "
              f"${min_per_tr:>+6.2f}")

    # Save full results
    for year in [2024, 2025, 2026]:
        all_results[year]["baseline"].to_parquet(
            OUT_DIR / f"baseline_{year}.parquet", index=False)
        for label in THRESH_LABELS:
            all_results[year]["in_trade"][label].to_parquet(
                OUT_DIR / f"in_trade_{label}_{year}.parquet",
                index=False)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
