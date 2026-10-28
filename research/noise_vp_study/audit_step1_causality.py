"""
Step 1: Pre-Sampling Causal Integrity Audit
Location: research/noise_vp_study/audit_step1_causality.py

Objective:
Proves mathematically and empirically whether the performance gain from pre-sampling
(:29:57-:29:59 ET) is a genuine execution advantage or an artifact of look-ahead leakage.

Policies Evaluated:
1. Policy A (Strictly Causal Pre-Sample / V1 & V2):
   - Eligibility is evaluated ONLY using information available at t - 1s (:29:59 / :59:59).
   - If criteria are met, order is filled at t - 1s (p_59s + slip).
   - Any price reversal between t - 1s and t = 0s (:00:00) is absorbed naturally as part of trade outcome.
2. Policy B (Look-Ahead Leakage Control):
   - Eligibility is evaluated at t = 0s (:00:00 / :30:00) using p_00s.
   - BUT trades are back-dated and assigned a fill price at t - 1s (p_59s).
   - This isolates whether look-ahead knowledge of the :00:00 bar close inflates performance.

Reconciliation Metrics:
- Type I (Transient / Invalidation): Qualified at :59s, but invalidated by :00s.
  (If > 30%, the pre-sample signal is unstable).
- Type II (Look-Ahead Leakage Candidates): Did not qualify at :59s, but qualified at :00s.
- Consistent Signals: Qualified at both :59s and :00s.
- Full PnL, Win Rate, Sharpe, and Drawdown comparison between Policy A and Policy B.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

# Script paths
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
CACHE_FILE = SCRIPT_DIR / "rth_resampled_cache.parquet"

POINT_VALUE_NQ = 20.0
TICK_SIZE = 0.25
COMMISSION_NQ_RT = 4.50


def load_cached_bars() -> pd.DataFrame:
    if not CACHE_FILE.exists():
        raise FileNotFoundError(f"Cache file not found at {CACHE_FILE}")
    return pd.read_parquet(CACHE_FILE)


def evaluate_signal_at_price(
    eval_p: float,
    upper: float,
    lower: float,
    vwap: float,
    prev_poc: float,
    prev_vah: float,
    prev_val: float,
    atr_15m: float,
    use_vp_filter: bool = True,
) -> int:
    """
    Returns +1 for Long, -1 for Short, 0 for Flat.
    """
    if eval_p > upper and eval_p > vwap:
        if not use_vp_filter:
            return 1
        vp_pass = (eval_p > prev_vah) or (eval_p < prev_val and (prev_poc - eval_p >= 1.5 * atr_15m))
        if vp_pass:
            return 1
    elif eval_p < lower and eval_p < vwap:
        if not use_vp_filter:
            return -1
        vp_pass = (eval_p < prev_val) or (eval_p > prev_vah and (eval_p - prev_poc >= 1.5 * atr_15m))
        if vp_pass:
            return -1
    return 0


def audit_step1_reconciliation(df_bars: pd.DataFrame, use_vp_filter: bool = True) -> Dict[str, Any]:
    """
    Evaluates signal status across all half-hour checkpoints at :59s vs :00s,
    and runs full life-cycle backtests for Policy A (strictly causal) vs Policy B (look-ahead backdated).
    """
    slip_side = 1 * TICK_SIZE
    comm_side = (COMMISSION_NQ_RT / POINT_VALUE_NQ) / 2.0
    t_start = pd.to_datetime("09:59:00").time()
    t_end = pd.to_datetime("15:29:00").time()

    # Step 1.1: Signal State Cross-Classification
    chk_bars = df_bars[
        df_bars.index.minute.isin([29, 59]) &
        (df_bars.index.time >= t_start) &
        (df_bars.index.time <= t_end)
    ].copy()

    total_checkpoints = len(chk_bars)
    sig_59_list = []
    sig_00_list = []
    p59_list = []
    p00_list = []

    for row in chk_bars.itertuples():
        p59 = row.p_59s
        p00 = row.p_00s
        up = row.upper_band
        lo = row.lower_band
        vwap = row.vwap
        poc = row.prev_poc
        vah = row.prev_vah
        val = row.prev_val
        atr = row.atr_15m if not np.isnan(row.atr_15m) else 15.0

        s59 = evaluate_signal_at_price(p59, up, lo, vwap, poc, vah, val, atr, use_vp_filter)
        s00 = evaluate_signal_at_price(p00, up, lo, vwap, poc, vah, val, atr, use_vp_filter)

        sig_59_list.append(s59)
        sig_00_list.append(s00)
        p59_list.append(p59)
        p00_list.append(p00)

    chk_bars["sig_59"] = sig_59_list
    chk_bars["sig_00"] = sig_00_list

    # Classification counts
    both_active_match = ((chk_bars["sig_59"] != 0) & (chk_bars["sig_59"] == chk_bars["sig_00"])).sum()
    both_flat = ((chk_bars["sig_59"] == 0) & (chk_bars["sig_00"] == 0)).sum()
    type1_invalidated = ((chk_bars["sig_59"] != 0) & (chk_bars["sig_00"] != chk_bars["sig_59"])).sum()
    type2_leakage_only = ((chk_bars["sig_59"] == 0) & (chk_bars["sig_00"] != 0)).sum()

    total_signals_59 = (chk_bars["sig_59"] != 0).sum()
    total_signals_00 = (chk_bars["sig_00"] != 0).sum()

    type1_rate = (type1_invalidated / total_signals_59) * 100.0 if total_signals_59 > 0 else 0.0
    type2_rate = (type2_leakage_only / total_signals_00) * 100.0 if total_signals_00 > 0 else 0.0

    # Step 1.2: Lifecycle Backtests (Policy A vs Policy B)
    all_dates = pd.date_range(df_bars.index.min().date(), df_bars.index.max().date(), freq="B").date
    oos_start = pd.to_datetime("2025-01-01").date()
    oos_dates = [d for d in all_dates if d >= oos_start]

    def run_policy(policy_mode: str) -> List[Dict[str, Any]]:
        trades = []
        grouped = df_bars.groupby("date")
        for date_val, day in grouped:
            day_bars = list(day.itertuples(name="Bar"))
            pos = 0
            entry_p = 0.0
            entry_t = None

            for bar in day_bars:
                ts = bar.Index
                t_val = ts.time()
                if not (ts.minute in (29, 59) and t_start <= t_val <= t_end):
                    continue

                p59 = bar.p_59s
                p00 = bar.p_00s
                up = bar.upper_band
                lo = bar.lower_band
                vwap = bar.vwap
                poc = bar.prev_poc
                vah = bar.prev_vah
                val = bar.prev_val
                atr = bar.atr_15m if not np.isnan(bar.atr_15m) else 15.0

                # Exit evaluation (identical trailing stop rules)
                eval_p_exit = p59 if policy_mode == "Policy_A" else p00
                if pos == 1:
                    if eval_p_exit < max(up, vwap):
                        exit_p = p59 - slip_side
                        gross = exit_p - entry_p
                        net = gross - (slip_side + 2 * comm_side)
                        trades.append({"entry_time": entry_t, "exit_time": ts, "net_pts": net, "date": entry_t.date()})
                        pos = 0
                elif pos == -1:
                    if eval_p_exit > min(lo, vwap):
                        exit_p = p59 + slip_side
                        gross = entry_p - exit_p
                        net = gross - (slip_side + 2 * comm_side)
                        trades.append({"entry_time": entry_t, "exit_time": ts, "net_pts": net, "date": entry_t.date()})
                        pos = 0

                # Entry evaluation
                if pos == 0:
                    if policy_mode == "Policy_A":
                        # Strictly Causal: evaluated at :59s, filled at :59s
                        sig = evaluate_signal_at_price(p59, up, lo, vwap, poc, vah, val, atr, use_vp_filter)
                        if sig == 1:
                            pos = 1
                            entry_p = p59 + slip_side
                            entry_t = ts
                        elif sig == -1:
                            pos = -1
                            entry_p = p59 - slip_side
                            entry_t = ts
                    elif policy_mode == "Policy_B":
                        # Look-Ahead Leakage: evaluated at :00s, but back-dated fill at :59s
                        sig = evaluate_signal_at_price(p00, up, lo, vwap, poc, vah, val, atr, use_vp_filter)
                        if sig == 1:
                            pos = 1
                            entry_p = p59 + slip_side  # BACK-DATED FILL
                            entry_t = ts
                        elif sig == -1:
                            pos = -1
                            entry_p = p59 - slip_side  # BACK-DATED FILL
                            entry_t = ts

            # EOD Flat at 16:00
            if pos != 0:
                eod_p = day_bars[-1].close
                if pos == 1:
                    exit_p = eod_p - slip_side
                    gross = exit_p - entry_p
                else:
                    exit_p = eod_p + slip_side
                    gross = entry_p - exit_p
                net = gross - (slip_side + 2 * comm_side)
                trades.append({"entry_time": entry_t, "exit_time": day_bars[-1].Index, "net_pts": net, "date": entry_t.date()})

        return trades

    trades_pol_a = run_policy("Policy_A")
    trades_pol_b = run_policy("Policy_B")

    def calc_policy_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        dft = pd.DataFrame(trades)
        n = len(dft)
        wr = (dft["net_pts"] > 0).mean() * 100.0
        avg_pts = dft["net_pts"].mean()
        tot_pts = dft["net_pts"].sum()
        gains = dft.loc[dft["net_pts"] > 0, "net_pts"].sum()
        losses = abs(dft.loc[dft["net_pts"] <= 0, "net_pts"].sum())
        pf = gains / losses if losses > 0 else 999.0

        daily_pnl = dft.groupby("date")["net_pts"].sum()
        daily_full = daily_pnl.reindex(all_dates, fill_value=0.0)
        sr_full = (daily_full.mean() / daily_full.std()) * math.sqrt(252) if daily_full.std() > 0 else 0.0

        daily_oos = daily_full.reindex(oos_dates, fill_value=0.0)
        sr_oos = (daily_oos.mean() / daily_oos.std()) * math.sqrt(252) if daily_oos.std() > 0 else 0.0

        cum = daily_full.cumsum()
        max_dd = (cum.cummax() - cum).max()

        return {
            "trades": n,
            "win_rate": wr,
            "avg_pts": avg_pts,
            "total_pts": tot_pts,
            "profit_factor": pf,
            "sr_full": sr_full,
            "sr_oos": sr_oos,
            "max_dd_pts": max_dd,
            "max_dd_usd": max_dd * POINT_VALUE_NQ,
        }

    metrics_pol_a = calc_policy_metrics(trades_pol_a)
    metrics_pol_b = calc_policy_metrics(trades_pol_b)

    return {
        "total_checkpoints": total_checkpoints,
        "both_active_match": both_active_match,
        "both_flat": both_flat,
        "type1_invalidated": type1_invalidated,
        "type1_rate": type1_rate,
        "type2_leakage_only": type2_leakage_only,
        "type2_rate": type2_rate,
        "total_signals_59": total_signals_59,
        "total_signals_00": total_signals_00,
        "metrics_pol_a": metrics_pol_a,
        "metrics_pol_b": metrics_pol_b,
    }


def main():
    print("=" * 78)
    print("STEP 1: PRE-SAMPLING CAUSAL INTEGRITY AUDIT")
    print("=" * 78)

    df_bars = load_cached_bars()
    print(f"Loaded {len(df_bars):,} bars. Running causal reconciliation on V2 signals...")

    res = audit_step1_reconciliation(df_bars, use_vp_filter=True)

    print("\n--- Checkpoint Signal Cross-Classification (:59s vs :00s) ---")
    print(f"Total Half-Hour Checkpoints Audited: {res['total_checkpoints']:,}")
    print(f"Consistent Active Signals (:59s AND :00s match): {res['both_active_match']:,} ({res['both_active_match']/res['total_signals_59']*100:.2f}% of :59s signals)")
    print(f"Consistent Flat (No signal at either):          {res['both_flat']:,}")
    print(f"Type I Transient Signals (:59s hit, :00s flat):  {res['type1_invalidated']:,} (Failure Rate: {res['type1_rate']:.2f}%)")
    print(f"Type II Leakage Signals (:59s flat, :00s hit):   {res['type2_leakage_only']:,} ({res['type2_rate']:.2f}% of :00s signals)")

    print("\n--- Causal Policy Reconciliation (Policy A vs Policy B) ---")
    pa = res["metrics_pol_a"]
    pb = res["metrics_pol_b"]

    print(f"Policy A (Strictly Causal :59s): N={pa['trades']} | WR={pa['win_rate']:.2f}% | Avg={pa['avg_pts']:+.2f} pt | Tot={pa['total_pts']:+,.2f} pt | PF={pa['profit_factor']:.2f} | SR_full={pa['sr_full']:.2f} | SR_oos={pa['sr_oos']:.2f} | MaxDD={pa['max_dd_pts']:.2f} pt")
    print(f"Policy B (Look-Ahead Leakage):   N={pb['trades']} | WR={pb['win_rate']:.2f}% | Avg={pb['avg_pts']:+.2f} pt | Tot={pb['total_pts']:+,.2f} pt | PF={pb['profit_factor']:.2f} | SR_full={pb['sr_full']:.2f} | SR_oos={pb['sr_oos']:.2f} | MaxDD={pb['max_dd_pts']:.2f} pt")

    delta_pts = pa["total_pts"] - pb["total_pts"]
    delta_avg = pa["avg_pts"] - pb["avg_pts"]
    print(f"\nDelta (Policy A - Policy B): Total Pts: {delta_pts:+,.2f} pt | Avg Pts: {delta_avg:+.2f} pt")
    if res["type1_rate"] < 30.0:
        print(f"Audit Status: PASS (Type I failure rate {res['type1_rate']:.2f}% < 30.0% threshold).")
    else:
        print(f"Audit Status: FAIL (Type I failure rate {res['type1_rate']:.2f}% >= 30.0% threshold).")


if __name__ == "__main__":
    main()
