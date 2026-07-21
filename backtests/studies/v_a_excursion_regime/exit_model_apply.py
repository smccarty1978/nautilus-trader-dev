"""Apply the trained exit model to non-VA trades and compare exit policies.

Policies to test (all on top 10% deployment schedule, single-pos applied
post-hoc in NT runs; this offline analysis runs ALL trades):

  P0 BL          baseline +60s exit (current)
  P1 RES         current rescore (hold while T-1 candidate >= top50)
  P2 EXIT-only   hold while p_exit_model >= threshold
  P3 HYBRID      hold while (T-1 cand >= top50) AND (p_exit_model >= thr)
  P4 +60s-only   exit model at +60s decision only; after that use P1 rule

Threshold sweep on p_exit_model. VA-confirm trades keep their existing
exit (regime flip) in all policies.

Output: per-year, per-policy $/tr + total in 1s mode. If any policy
shows robust positive lift, schedules can be built and NT-validated.
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
    NQ_MULT, replay_no_flip_baseline_1s, replay_va_baseline_1s,
)
from bracket_grid_2024_2025 import (
    load_year_bars_and_flips, apply_roll_filter_year,
)


OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/exit_model")
EXIT_OOS = OUT_DIR / "exit_model_oos.parquet"
TOP10_QUANTILE = 0.10
T1_RESCORE_THR = 0.0770   # top50 — proven rescore threshold
COMMISSION = 5.0          # $5 RT user's actual cost
MAX_HOLD_S = 600
DECISION_INTERVAL_S = 60


def replay_with_dynamic_exit(
    bar_ts, bar_open,
    entry_ts_ns, direction,
    decision_fn,
):
    """Replay a non-VA trade with a dynamic exit decision function.

    decision_fn(elapsed_s) -> bool: True = hold, False = exit.

    Returns dict with entry/exit prices and reason.
    """
    d = direction
    eidx = int(np.searchsorted(bar_ts, entry_ts_ns, side="right"))
    if eidx >= len(bar_ts):
        return None
    entry_fill = float(bar_open[eidx])

    for elapsed_s in range(DECISION_INTERVAL_S,
                                   MAX_HOLD_S + 1,
                                   DECISION_INTERVAL_S):
        check_ts = entry_ts_ns + elapsed_s * 1_000_000_000
        hold = decision_fn(elapsed_s)
        if not hold:
            exit_idx = int(np.searchsorted(bar_ts, check_ts,
                                                  side="right"))
            if exit_idx >= len(bar_ts):
                exit_idx = len(bar_ts) - 1
            return {
                "entry_ts_ns": entry_ts_ns,
                "entry_fill_price": entry_fill,
                "exit_ts_ns": int(bar_ts[exit_idx]),
                "exit_fill_price": float(bar_open[exit_idx]),
                "direction": d,
                "elapsed_s": elapsed_s,
                "exit_reason": "MODEL_EXIT",
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
    }


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load exit model OOS predictions
    exit_oos = pd.read_parquet(EXIT_OOS)
    print(f"Loaded {len(exit_oos):,} exit model OOS predictions")
    # Lookup: (entry_ts_ns, elapsed_s, direction) -> p_exit_model
    exit_lookup = {}
    for _, r in exit_oos.iterrows():
        exit_lookup[(int(r["entry_ts_ns"]), int(r["elapsed_s"]),
                        int(r["direction"]))] = float(r["p_exit_model"])
    print(f"  exit lookup size: {len(exit_lookup):,}")

    # Load T-1 OOS predictions for rescore + entry filtering
    t1_oos = pd.read_parquet(PRE_FLIP_OOS)
    t1_thresh = t1_oos["p_score"].quantile(1 - TOP10_QUANTILE)
    print(f"T-1 top 10% threshold: p_T1 >= {t1_thresh:.4f}")
    # T-1 score lookup at any (ts, direction)
    t1_lookup = {}
    for _, r in t1_oos.iterrows():
        t1_lookup[(int(r["close_ts_ns"]),
                      int(r["direction"]))] = float(r["p_score"])

    # Thresholds to sweep on p_exit_model
    THRESHOLDS = [0.40, 0.45, 0.48, 0.50, 0.52, 0.55, 0.60]

    # Per-year setup + replay
    all_results = {}
    for year in [2024, 2025, 2026]:
        print(f"\n=== Year {year} ===")
        t1y = time.time()
        sched = build_schedule(
            t1_oos, year, t1_thresh,
            f"{COLLECTOR_DIR}/v_a_v0_{year}/trades.parquet",
            f"{COLLECTOR_DIR}/v_a_v0_{year}/"
            f"snapshots_with_vol_vwap.parquet")
        sched["entry_ts_ns"] = sched["entry_ts_ns"].astype("int64")
        n_pre = len(sched)
        sched, n_drop = apply_roll_filter_year(sched, year)
        print(f"  schedule: {n_pre:,} → {len(sched):,} after roll-day")

        bar_ts, bar_open, _, _, _, _, _ = load_year_bars_and_flips(
            year)

        va_sched = sched[sched["is_va_confirm"]].copy()
        nf_sched = sched[~sched["is_va_confirm"]].copy()
        print(f"  VA-confirm: {len(va_sched):,}  no-flip: {len(nf_sched):,}")

        # VA-confirm baseline (unchanged across policies)
        va_rows = []
        for _, tr in va_sched.iterrows():
            r = replay_va_baseline_1s(
                bar_ts, bar_open,
                int(tr["entry_ts_ns"]),
                int(tr["exit_ts_ns"]),
                int(tr["direction"]))
            if r is not None:
                r["pnl_pts"] = (r["exit_fill_price"]
                                    - r["entry_fill_price"]) * r["direction"]
                r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION
                va_rows.append(r)
        va_total = sum(r["net_pnl"] for r in va_rows)
        print(f"    VA-confirm: ${va_total:+,.0f} "
              f"(${va_total/max(len(va_rows),1):+.2f}/tr)")

        # P0: baseline +60s
        p0_rows = []
        for _, tr in nf_sched.iterrows():
            r = replay_no_flip_baseline_1s(
                bar_ts, bar_open,
                int(tr["entry_ts_ns"]),
                int(tr["direction"]))
            if r is not None:
                r["pnl_pts"] = (r["exit_fill_price"]
                                    - r["entry_fill_price"]) * r["direction"]
                r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION
                p0_rows.append(r)
        p0_total = sum(r["net_pnl"] for r in p0_rows)
        print(f"    P0 BL +60s : ${p0_total:+,.0f}  "
              f"NF n={len(p0_rows)} ${p0_total/max(len(p0_rows),1):+.2f}/tr")

        # P1: current rescore (T-1 candidate >= top50)
        def p1_decision(entry_ts, d):
            def fn(elapsed_s):
                check_ts = entry_ts + elapsed_s * 1_000_000_000
                score = t1_lookup.get((check_ts, d), None)
                return score is not None and score >= T1_RESCORE_THR
            return fn

        p1_rows = []
        for _, tr in nf_sched.iterrows():
            ets = int(tr["entry_ts_ns"])
            d = int(tr["direction"])
            r = replay_with_dynamic_exit(
                bar_ts, bar_open, ets, d,
                p1_decision(ets, d))
            if r is not None:
                r["pnl_pts"] = (r["exit_fill_price"]
                                    - r["entry_fill_price"]) * d
                r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION
                p1_rows.append(r)
        p1_total = sum(r["net_pnl"] for r in p1_rows)
        print(f"    P1 RES top50: ${p1_total:+,.0f}  "
              f"NF n={len(p1_rows)} ${p1_total/max(len(p1_rows),1):+.2f}/tr")

        # P2 / P3 / P4 across thresholds
        for thr in THRESHOLDS:
            def p2_decision(entry_ts, d, thr=thr):
                def fn(elapsed_s):
                    p = exit_lookup.get((entry_ts, elapsed_s, d),
                                              None)
                    return p is not None and p >= thr
                return fn

            def p3_decision(entry_ts, d, thr=thr):
                def fn(elapsed_s):
                    check_ts = entry_ts + elapsed_s * 1_000_000_000
                    t1s = t1_lookup.get((check_ts, d), None)
                    t1_active = (t1s is not None
                                    and t1s >= T1_RESCORE_THR)
                    p = exit_lookup.get((entry_ts, elapsed_s, d),
                                              None)
                    em_hold = p is not None and p >= thr
                    return t1_active and em_hold
                return fn

            def p4_decision(entry_ts, d, thr=thr):
                def fn(elapsed_s):
                    if elapsed_s == 60:
                        p = exit_lookup.get((entry_ts, elapsed_s, d),
                                                  None)
                        return p is not None and p >= thr
                    else:
                        check_ts = entry_ts + elapsed_s * 1_000_000_000
                        t1s = t1_lookup.get((check_ts, d), None)
                        return (t1s is not None
                                  and t1s >= T1_RESCORE_THR)
                return fn

            for p_label, p_fn in [("P2 EX  ", p2_decision),
                                          ("P3 HYB ", p3_decision),
                                          ("P4 +60s", p4_decision)]:
                rows = []
                for _, tr in nf_sched.iterrows():
                    ets = int(tr["entry_ts_ns"])
                    d = int(tr["direction"])
                    r = replay_with_dynamic_exit(
                        bar_ts, bar_open, ets, d, p_fn(ets, d))
                    if r is not None:
                        r["pnl_pts"] = (r["exit_fill_price"]
                                            - r["entry_fill_price"]) * d
                        r["net_pnl"] = r["pnl_pts"] * NQ_MULT - COMMISSION
                        rows.append(r)
                total = sum(r["net_pnl"] for r in rows)
                tag = f"thr={thr:.2f}"
                all_results.setdefault(
                    (p_label.strip(), thr), {})[year] = {
                    "nf_n": len(rows),
                    "nf_total": total,
                    "nf_per_tr": total / max(len(rows), 1),
                    "va_total": va_total,
                    "va_n": len(va_rows),
                    "combined_total": va_total + total,
                    "combined_n": len(va_rows) + len(rows),
                }
        all_results.setdefault(("P0_BL", None), {})[year] = {
            "nf_n": len(p0_rows),
            "nf_total": p0_total,
            "nf_per_tr": p0_total / max(len(p0_rows), 1),
            "va_total": va_total,
            "va_n": len(va_rows),
            "combined_total": va_total + p0_total,
            "combined_n": len(va_rows) + len(p0_rows),
        }
        all_results.setdefault(("P1_RES_TOP50", None), {})[year] = {
            "nf_n": len(p1_rows),
            "nf_total": p1_total,
            "nf_per_tr": p1_total / max(len(p1_rows), 1),
            "va_total": va_total,
            "va_n": len(va_rows),
            "combined_total": va_total + p1_total,
            "combined_n": len(va_rows) + len(p1_rows),
        }
        del bar_ts, bar_open
        gc.collect()
        print(f"  year done ({time.time()-t1y:.0f}s)")

    # Summary table
    print(f"\n{'='*100}")
    print(f"COMBINED 3-YEAR SUMMARY (commission $5 RT, 1s mode, no single-pos)")
    print(f"{'='*100}")
    print(f"  {'Policy':<22} {'Thr':<6} "
          f"{'2024 $/tr':>10} {'2025 $/tr':>10} {'2026 $/tr':>10} "
          f"{'3yr tot':>10} {'min $/tr':>10}")

    rows = []
    for (policy, thr), per_year in all_results.items():
        c24 = per_year.get(2024, {}).get("combined_per_tr",
                                                None)
        c25 = per_year.get(2025, {}).get("combined_per_tr",
                                                None)
        c26 = per_year.get(2026, {}).get("combined_per_tr",
                                                None)
        # combined_per_tr needs to be computed
        for yr in [2024, 2025, 2026]:
            d = per_year[yr]
            d["combined_per_tr"] = (d["combined_total"]
                                            / max(d["combined_n"], 1))
        c24 = per_year[2024]["combined_per_tr"]
        c25 = per_year[2025]["combined_per_tr"]
        c26 = per_year[2026]["combined_per_tr"]
        tot = sum(per_year[yr]["combined_total"]
                      for yr in [2024, 2025, 2026])
        min_ptr = min(c24, c25, c26)
        rows.append({
            "policy": policy,
            "thr": thr,
            "y24_per_tr": c24,
            "y25_per_tr": c25,
            "y26_per_tr": c26,
            "tot": tot,
            "min_per_tr": min_ptr,
            "per_year": per_year,
        })

    # Sort by min_per_tr descending (robustness criterion)
    rows.sort(key=lambda r: -r["min_per_tr"])
    for r in rows:
        thr_str = f"{r['thr']:.2f}" if r["thr"] is not None else "-"
        print(f"  {r['policy']:<22} {thr_str:<6} "
              f"${r['y24_per_tr']:>+8.2f} "
              f"${r['y25_per_tr']:>+8.2f} "
              f"${r['y26_per_tr']:>+8.2f} "
              f"${r['tot']:>+8,.0f} "
              f"${r['min_per_tr']:>+8.2f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
