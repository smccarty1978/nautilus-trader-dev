"""Diagnostic: re-run C_lock50_30s_5 tape replay with CALENDAR-
aligned 30s buckets (matching tick-NT runtime semantics) instead of
the elapsed-time bucketing used in the prior IS+OOS studies.

If calendar-bucket result ≈ tick-NT result, the bucket alignment
explains the gap.

Just NQ 2024+2025+2026 RTH for parity with the prior IS report.
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
OUT = Path("studies/v_a_exit_recon/results")
NQ_MULT = 20.0
COST_RT = 10.0
YEARS = [2024, 2025, 2026]


def stats(pnl):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0: return {"n": 0}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
          if len(losses) and losses.sum() != 0
          else float("inf"))
    return {
        "n": n, "wr": float((s > 0).mean()),
        "mean": float(s.mean()), "sum": float(s.sum()),
        "pf": float(pf),
    }


def precompute_calendar_30s(tape: pd.DataFrame) -> pd.DataFrame:
    """Same as hhll_progression.precompute_progression but for
    30s only and using CALENDAR-ALIGNED bucketing
    (`ts_init // 30_000_000_000` in nanoseconds → wall-clock 30s
    buckets aligned to UTC :00 / :30 boundaries)."""
    tape = tape.sort_values(
        ["trade_id", "ts_init"]).reset_index(drop=True)

    # Calendar 30s bucket id
    tape["bucket_cal_30s"] = (
        tape["ts_init"] // (30 * 1_000_000_000)).astype(int)
    d = tape["direction"].values
    h = tape["h"].values; l = tape["l"].values
    tape["_fav_price"] = np.where(d == 1, h, l)
    signed = tape["_fav_price"] * d
    tape["_signed_fav"] = signed
    grp = tape.groupby(["trade_id", "bucket_cal_30s"], sort=False)
    bucket_max_signed = grp["_signed_fav"].transform("max")
    tape["bucket_extreme_signed"] = bucket_max_signed
    bucket_df = (
        tape.groupby(["trade_id", "bucket_cal_30s"], sort=False)
        .agg(bucket_extreme_signed=(
            "bucket_extreme_signed", "max"),
             bucket_close_ts=("ts_init", "max"),
             direction=("direction", "first"))
        .reset_index())
    bucket_df = bucket_df.sort_values(
        ["trade_id", "bucket_cal_30s"]).reset_index(drop=True)
    bucket_df["bucket_cummax"] = (
        bucket_df.groupby("trade_id", sort=False)
        ["bucket_extreme_signed"].cummax())
    bucket_df["prev_cummax"] = (
        bucket_df.groupby("trade_id", sort=False)
        ["bucket_cummax"].shift(1))
    bucket_df["is_new"] = (
        bucket_df["bucket_extreme_signed"]
        > bucket_df["prev_cummax"].fillna(-np.inf)).astype(int)

    def bars_since(g):
        out = np.empty(len(g), dtype=np.int32)
        cnt = -1
        for i, b in enumerate(g):
            if b: cnt = 0
            else: cnt = cnt + 1 if cnt >= 0 else 0
            out[i] = cnt
        return out

    bs = (bucket_df["is_new"]
          .groupby(bucket_df["trade_id"], sort=False)
          .transform(bars_since))
    bucket_df["bars_since_new_cal_30s"] = bs.values
    bucket_df["next_bucket"] = bucket_df["bucket_cal_30s"] + 1
    lookup = bucket_df[
        ["trade_id", "next_bucket",
          "bars_since_new_cal_30s"]].rename(
              columns={"next_bucket": "bucket_cal_30s"})
    tape = tape.merge(
        lookup, on=["trade_id", "bucket_cal_30s"], how="left")
    tape["bars_since_new_cal_30s"] = (
        tape["bars_since_new_cal_30s"].fillna(-1).astype(int))
    return tape.drop(
        columns=["_fav_price", "_signed_fav",
                 "bucket_extreme_signed"], errors="ignore")


def replay_c_lock50(trades, tape, stall_bars=5,
                       lock_pct=0.50, min_mfe_atr=1.0):
    out = []
    tape_groups = tape.groupby("trade_id", sort=False)
    for _, t in trades.iterrows():
        ev = int(t["trade_id"])
        if ev not in tape_groups.groups:
            out.append({**t, "new_net_pnl": float(t["net_pnl"]),
                          "fired": False}); continue
        g = tape_groups.get_group(ev)
        atr = float(t["atr_at_signal"])
        min_mfe_pts = min_mfe_atr * atr
        ep = float(t["fill_price"])
        d = int(t["direction"])
        arm_cond = ((g["mfe_pts"] >= min_mfe_pts)
                    & (g["bars_since_new_cal_30s"] >= stall_bars))
        if not arm_cond.any():
            out.append({**t, "new_net_pnl": float(t["net_pnl"]),
                          "fired": False}); continue
        arm_idx = g.index[arm_cond.values][0]
        mfe_at_arm = float(g.loc[arm_idx, "mfe_pts"])
        protect_offset = lock_pct * mfe_at_arm
        if d == 1:
            protect_px = ep + protect_offset
            post = g.loc[arm_idx:]
            hit = post["l"] <= protect_px
        else:
            protect_px = ep - protect_offset
            post = g.loc[arm_idx:]
            hit = post["h"] >= protect_px
        if not hit.any():
            out.append({**t, "new_net_pnl": float(t["net_pnl"]),
                          "fired": False}); continue
        hit_row = post[hit].iloc[0]
        gross = (protect_px - ep) * d * NQ_MULT
        net = gross - COST_RT
        out.append({**t, "new_net_pnl": float(net),
                       "fired": True})
    return pd.DataFrame(out)


def main():
    print("Loading tape for 2024+2025+2026...")
    all_trades = []; all_tape = []
    for yr in YEARS:
        d = PORT / f"NQ_{yr}"
        if not (d / "trade_tape.parquet").exists():
            print(f"  NQ {yr}: no tape — skip"); continue
        trades = pd.read_parquet(d / "trades.parquet")
        tape = pd.read_parquet(d / "trade_tape.parquet")
        rth = trades[trades["session"] == "RTH"].copy()
        rth_ids = set(rth["decision_event_id"])
        tape_rth = tape[
            tape["decision_event_id"].isin(rth_ids)].copy()
        OFFSET = yr * 1_000_000
        rth["trade_id"] = rth["decision_event_id"] + OFFSET
        tape_rth["trade_id"] = (
            tape_rth["decision_event_id"] + OFFSET)
        rth["year"] = yr
        all_trades.append(rth)
        all_tape.append(tape_rth)
        print(f"  NQ {yr}: {len(rth):,} trades / "
              f"{len(tape_rth):,} tape rows")
    trades = pd.concat(all_trades, ignore_index=True)
    tape = pd.concat(all_tape, ignore_index=True)
    print(f"\nTotal: {len(trades):,} trades, {len(tape):,} tape rows")

    print("\nPre-computing CALENDAR-aligned 30s progression...")
    tape = precompute_calendar_30s(tape)

    print("Replaying C_lock50_30s_5 with calendar-aligned "
          "bucketing...")
    out = replay_c_lock50(trades, tape, stall_bars=5,
                                lock_pct=0.50, min_mfe_atr=1.0)
    print(f"  fired on {out['fired'].sum():,}/{len(out):,} trades "
          f"({out['fired'].mean()*100:.1f}%)")

    # Per-year compare to baseline
    print("\n=== Per-year comparison (CALENDAR buckets) ===")
    print("Year | Baseline mean | HH/LL cal mean | Δ | "
          "Years+ → ?")
    for yr in YEARS:
        sub = out[out["year"] == yr]
        s_b = stats(sub["net_pnl"])
        s_h = stats(sub["new_net_pnl"])
        if s_b["n"] == 0: continue
        d_mean = s_h["mean"] - s_b["mean"]
        sign = "↑" if d_mean > 0 else "↓"
        print(f"  {yr} | ${s_b['mean']:7.2f} | "
              f"${s_h['mean']:7.2f} | {d_mean:+7.2f} {sign}")
    s_all_b = stats(out["net_pnl"])
    s_all_h = stats(out["new_net_pnl"])
    print(f"  ALL  | ${s_all_b['mean']:7.2f} | "
          f"${s_all_h['mean']:7.2f} | "
          f"{s_all_h['mean']-s_all_b['mean']:+7.2f}")
    print()
    print(f"Baseline aggregate: {s_all_b['n']:,} trades, "
          f"${s_all_b['sum']:,.0f}, PF {s_all_b['pf']:.2f}")
    print(f"HH/LL cal aggregate: ${s_all_h['sum']:,.0f}, "
          f"PF {s_all_h['pf']:.2f}, WR {s_all_h['wr']*100:.1f}%")

    # Compare to original IS-report tape replay (entry-aligned)
    print("\n=== vs original IS-report (entry-aligned bucketing) ===")
    print("  Original IS C_lock50_30s_5 ALL: $54.33/trade, $416K, "
          "WR 56-59%")
    print(f"  Calendar-aligned re-do ALL:  "
          f"${s_all_h['mean']:.2f}/trade, "
          f"${s_all_h['sum']:,.0f}, "
          f"WR {s_all_h['wr']*100:.1f}%")

    out.to_parquet(
        OUT / "trades_C_lock50_30s_5_calendar_buckets.parquet",
        index=False)


if __name__ == "__main__":
    main()
