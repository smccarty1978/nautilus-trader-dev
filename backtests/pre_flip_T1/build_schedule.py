"""Build the NT backtest schedule for pre-flip T-1 top-X% predictions.

Converts the walk-forward OOS predictions into a trade schedule the NT
strategy can replay. Each row = one fired prediction → one trade.

Schema written:
  - entry_ts_ns : int64 — the candidate close_ts; NT will fill on next
    1s bar after this timestamp (bar_execution=True)
  - exit_ts_ns  : int64 — either V_A's actual regime-flip exit_ts (if a
    V_A-confirmed flip occurred at the predicted horizon) OR
    candidate.close_ts + 60s for no-flip bar-close exit
  - direction   : int8 — +1 long, -1 short
  - atr_at_signal : float64 — for diagnostics
  - p_score     : float64 — for diagnostics
  - is_va_confirm : bool — whether V_A confirmed a flip at the horizon
  - close_1m_at_signal : float64 — for diagnostics
  - year, month : int — for reporting
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd


OUT = Path("studies/v_a_excursion_regime/results_v0")
SCHEDULE_DIR = Path("backtests/pre_flip_T1/results")
HORIZON_S = 60   # T-1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-quantile", type=float, default=0.10,
                      help="Top quantile of p_score to fire on (e.g., 0.10)")
    ap.add_argument("--year", type=int, default=2026,
                      help="OOS year to build schedule for")
    ap.add_argument("--threshold-source", choices=["global", "year"],
                      default="global",
                      help="'global' = quantile across ALL OOS predictions; "
                             "'year' = quantile within the target year only")
    ap.add_argument("--out-suffix", type=str, default="2026_top10")
    args = ap.parse_args()

    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Building NT schedule: T-1 top {args.top_quantile*100:.0f}% "
          f"on {args.year} OOS")

    # Load OOS predictions
    oos = pd.read_parquet(OUT / "pre_flip_oos_T1.parquet")
    print(f"  total OOS predictions: {len(oos):,}")
    # Threshold source: global across all OOS years OR within the target year
    if args.threshold_source == "global":
        thresh = oos["p_score"].quantile(1 - args.top_quantile)
        print(f"  GLOBAL top {args.top_quantile*100:.0f}% threshold: "
              f"p_score >= {thresh:.4f}")
    else:
        year_pool = oos[oos["year"] == args.year]
        thresh = year_pool["p_score"].quantile(1 - args.top_quantile)
        print(f"  YEAR-RELATIVE top {args.top_quantile*100:.0f}% threshold "
              f"({args.year}): p_score >= {thresh:.4f}")

    fired = oos[(oos["p_score"] >= thresh)
                  & (oos["year"] == args.year)].copy()
    fired = fired.sort_values("close_ts_ns").reset_index(drop=True)
    print(f"  fired in {args.year}: {len(fired):,}")
    if len(fired) == 0:
        print("  no fired predictions — exiting")
        return

    # Build entry_ts (the candidate close_ts, NT fires on next 1s bar)
    fired["entry_ts_ns"] = fired["close_ts_ns"]
    fired["target_flip_ts_ns"] = (
        fired["close_ts_ns"] + HORIZON_S * 1_000_000_000)

    # Load V_A confirmed flips for the year to determine V_A-confirm exits
    snap = pd.read_parquet(
        f"collectors/collector_v2/results/v_a_v0_{args.year}/snapshots_with_vol_vwap.parquet",
        columns=["kind", "decision_ts", "direction", "became_trade",
                   "session"])
    trades = pd.read_parquet(
        f"collectors/collector_v2/results/v_a_v0_{args.year}/trades.parquet",
        columns=["decision_ts", "direction", "fill_price", "exit_ts",
                   "exit_price", "atr_at_signal", "net_pnl", "session"])
    b1 = snap[(snap["kind"] == "bar1_check")
                & (snap["became_trade"])
                & (snap["session"] == "RTH")].copy()
    b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
    va = b1.merge(
        trades[trades["session"] == "RTH"][[
            "decision_ts", "direction", "exit_ts", "atr_at_signal"]],
        on=["decision_ts", "direction"], how="inner")
    va_lookup = va.set_index(["flip_bar_close_ts", "direction"])
    print(f"  V_A confirmed flips: {len(va):,}")

    # For each fired, determine exit_ts:
    # - If V_A confirmed at target_flip_ts: use V_A's exit_ts
    # - Else: exit at close_ts + 60s
    exit_ts_list = []
    is_va_confirm_list = []
    atr_list = []
    for _, fr in fired.iterrows():
        target = int(fr["target_flip_ts_ns"])
        d = int(fr["direction"])
        try:
            va_row = va_lookup.loc[(target, d)]
            exit_ts_list.append(int(va_row["exit_ts"]))
            is_va_confirm_list.append(True)
            atr_list.append(float(va_row["atr_at_signal"]))
        except KeyError:
            # No V_A confirm — exit at +1 bar close
            exit_ts_list.append(target)
            is_va_confirm_list.append(False)
            # Use candidate's 1m ATR as proxy (load from candidates)
            atr_list.append(np.nan)
    fired["exit_ts_ns"] = exit_ts_list
    fired["is_va_confirm"] = is_va_confirm_list
    fired["atr_at_signal"] = atr_list

    # Fill missing atr_at_signal from candidates
    cands = pd.read_parquet(OUT / "pre_flip_candidates.parquet")
    cand_lookup = cands.set_index(
        ["close_ts_ns", "candidate_direction"])
    for k in range(len(fired)):
        if np.isnan(fired["atr_at_signal"].iloc[k]):
            cts = int(fired["close_ts_ns"].iloc[k])
            d = int(fired["direction"].iloc[k])
            try:
                fired.at[k, "atr_at_signal"] = float(
                    cand_lookup.loc[(cts, d), "atr_1m"])
                fired.at[k, "close_1m_at_signal"] = float(
                    cand_lookup.loc[(cts, d), "close_1m"])
            except KeyError:
                pass

    if "close_1m_at_signal" not in fired.columns:
        fired["close_1m_at_signal"] = np.nan
    fired["entry_dt"] = pd.to_datetime(
        fired["entry_ts_ns"], unit="ns", utc=True)
    fired["exit_dt"] = pd.to_datetime(
        fired["exit_ts_ns"], unit="ns", utc=True)
    fired["month"] = fired["entry_dt"].dt.month

    schedule = fired[[
        "entry_ts_ns", "exit_ts_ns", "direction", "atr_at_signal",
        "p_score", "label", "is_va_confirm", "close_1m_at_signal",
        "year", "month",
    ]].copy()

    out_path = SCHEDULE_DIR / f"schedule_T1_{args.out_suffix}.parquet"
    schedule.to_parquet(out_path, index=False)
    print(f"\n  Wrote {len(schedule):,} trades to {out_path}")
    print(f"  Per-month: {schedule['month'].value_counts().sort_index().to_dict()}")
    print(f"  VA-confirm: {schedule['is_va_confirm'].sum()} / "
          f"{len(schedule)} ({schedule['is_va_confirm'].mean():.1%})")
    print(f"  Direction: {schedule['direction'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
