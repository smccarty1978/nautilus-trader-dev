"""Re-simulate breakout-filter trades (RTH only) with timing tracking
to split:

  Winners:
    - Clean: very low MAE before any meaningful favorable excursion
    - V-shape: meaningful adverse move BEFORE recovering to win

  Losers:
    - Quick: never built any positive MFE — direct stop
    - Run-then-break: had meaningful MFE, then reversed to SL

For each bucket per gap-group, report population share, dollar
contribution, and MFE/MAE statistics. Goal: see whether bucket
proportions support a tighter-SL or BE-arming design.

ARM_THRESHOLD = 2.5 pts: matches the prior BE arming convention.
CLEAN_MAE_CAP = 2.0 pts: adverse moves below 2 pts are noise/spread.
"""
from __future__ import annotations

import os, sys
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
    detect_triggers_breakout, LEVEL_PAIR_TO_GROUP, assign_group,
    NQ_DOLLAR_PER_PT, COMMISSION_PTS, MAX_BARS,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

ARM_THRESHOLD = 2.5      # MFE pts to consider "armed"
CLEAN_MAE_CAP = 2.0      # max adverse before arming, to be "clean"


def simulate_trade_with_timing(
    trig: dict,
    opens: np.ndarray, highs: np.ndarray, lows: np.ndarray,
    closes: np.ndarray, ts_closes: np.ndarray, sessions: np.ndarray,
    n: int,
) -> dict | None:
    entry_idx = trig["bar_idx"] + 1
    if entry_idx >= n:
        return None
    d = trig["direction"]
    target = trig["target"]
    stop = trig["stop"]
    entry_price = float(opens[entry_idx])
    last_bar = min(entry_idx + MAX_BARS - 1, n - 1)

    mae = 0.0
    mfe = 0.0
    mae_at = 0
    mfe_at = 0
    arm_bar = -1               # first bar (rel to entry) where MFE >= ARM
    mae_before_arm = 0.0       # max adverse before arming (or full life)

    outcome = "timed_out"
    exit_price = float(closes[last_bar])
    exit_idx = last_bar

    for k, i in enumerate(range(entry_idx, last_bar + 1)):
        h = float(highs[i]); l = float(lows[i])
        if d == 1:
            adverse = entry_price - l
            favorable = h - entry_price
        else:
            adverse = h - entry_price
            favorable = entry_price - l
        if adverse > mae:
            mae = adverse; mae_at = k
        if favorable > mfe:
            mfe = favorable; mfe_at = k
        # Track adverse before arming
        if arm_bar < 0:
            if adverse > mae_before_arm:
                mae_before_arm = adverse
            if favorable >= ARM_THRESHOLD:
                arm_bar = k
        # Stop-then-target
        if d == 1:
            stop_hit = l <= stop
            tgt_hit = h >= target
        else:
            stop_hit = h >= stop
            tgt_hit = l <= target
        if stop_hit:
            outcome = "loss"
            exit_price = float(stop); exit_idx = i
            break
        if tgt_hit:
            outcome = "win"
            exit_price = float(target); exit_idx = i
            break

    pnl_pts = (exit_price - entry_price) * d
    bars_held = exit_idx - entry_idx + 1
    return {
        "trigger_ts_close": pd.Timestamp(trig["bar_ts_close"]),
        "entry_session": sessions[entry_idx],
        "level_pair": trig["level_pair"],
        "direction": d,
        "outcome": outcome,
        "pnl_pts": float(pnl_pts),
        "pnl_net_pts": float(pnl_pts - COMMISSION_PTS),
        "pnl_dollars": float(
            (pnl_pts - COMMISSION_PTS) * NQ_DOLLAR_PER_PT),
        "mae_pts": float(mae),
        "mfe_pts": float(mfe),
        "mae_at_bar": int(mae_at),
        "mfe_at_bar": int(mfe_at),
        "arm_bar": int(arm_bar),               # -1 if never armed
        "mae_before_arm": float(mae_before_arm),
        "bars_held": int(bars_held),
        "exit_idx": exit_idx,
    }


def run_chain(triggers: list[dict], bars_1m: pd.DataFrame
              ) -> pd.DataFrame:
    bars = bars_1m.reset_index(drop=False)
    opens = bars["open"].values
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    ts_closes = bars["ts_close"].values
    sessions = bars["session"].values
    n = len(bars)

    out = []
    last_exit_idx = -1
    for trig in triggers:
        if trig["bar_idx"] <= last_exit_idx:
            continue
        r = simulate_trade_with_timing(
            trig, opens, highs, lows, closes, ts_closes, sessions, n)
        if r is None: continue
        out.append(r)
        last_exit_idx = r["exit_idx"]
    return pd.DataFrame(out)


# ---------------- Bucket assignment ----------------

def assign_bucket(row) -> str:
    if row["outcome"] == "win":
        # Clean if mae_before_arm < CLEAN_MAE_CAP
        # (and trade actually armed before resolving)
        if row["arm_bar"] >= 0 and row["mae_before_arm"] < CLEAN_MAE_CAP:
            return "win_clean"
        else:
            return "win_vshape"
    elif row["outcome"] == "loss":
        if row["mfe_pts"] < ARM_THRESHOLD:
            return "loss_quick"
        else:
            return "loss_runthenbreak"
    else:
        return "timed_out"


def main():
    all_rows = []
    for year in (2024, 2025):
        print(f"\n[{year}] loading & simulating...")
        bars_1s = load_v0_1s(
            Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
        bars_1m = resample_1s_to_1m(bars_1s)
        bars_1m = annotate_sessions_ct(bars_1m)
        triggers = detect_triggers_breakout(bars_1m)
        trades = run_chain(triggers, bars_1m)
        trades["year"] = year
        all_rows.append(trades)
        print(f"  trades: {len(trades):,}")

    df = pd.concat(all_rows, ignore_index=True)
    df["group"] = df["level_pair"].map(assign_group)
    df["bucket"] = df.apply(assign_bucket, axis=1)

    # RTH only
    rth = df[df["entry_session"] == "RTH"].copy()
    rth.to_parquet(OUT / "trades_rth_with_timing.parquet")
    print(f"\nRTH trades: {len(rth):,} "
          f"(saved to trades_rth_with_timing.parquet)")

    print(f"\n{'='*78}\n"
          f"BUCKET DISTRIBUTION — RTH (2024+2025)\n"
          f"  win_clean      = win, MAE-before-arm < "
          f"{CLEAN_MAE_CAP} pts (true breakout)\n"
          f"  win_vshape     = win, MAE-before-arm >= "
          f"{CLEAN_MAE_CAP} pts (dipped then recovered)\n"
          f"  loss_quick     = loss, MFE < "
          f"{ARM_THRESHOLD} pts (never got going)\n"
          f"  loss_runthenbreak = loss, MFE >= "
          f"{ARM_THRESHOLD} pts (had move, gave it back)\n"
          f"  timed_out      = neither hit by bar 120\n"
          f"{'='*78}")

    # Per-group breakdown
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = rth[rth["group"] == grp]
        if len(g) == 0:
            continue
        print(f"\n[{grp}] n={len(g):,}  "
              f"total ${g['pnl_dollars'].sum():>+10,.0f}  "
              f"per-trade ${g['pnl_dollars'].mean():>+6.2f}")
        print(f"  {'bucket':<22} {'n':>7} {'pct':>6} "
              f"{'mean_pnl_$':>11} {'total_pnl_$':>13} "
              f"{'mfe_p50':>8} {'mae_p50':>8} {'arm_p50':>8} "
              f"{'mae_befarm_p50':>14}")
        for bk in ("win_clean", "win_vshape",
                   "loss_quick", "loss_runthenbreak", "timed_out"):
            b = g[g["bucket"] == bk]
            if len(b) == 0:
                continue
            mfe50 = float(np.percentile(b["mfe_pts"], 50))
            mae50 = float(np.percentile(b["mae_pts"], 50))
            arm50 = (float(np.percentile(
                b.loc[b["arm_bar"] >= 0, "arm_bar"], 50))
                     if (b["arm_bar"] >= 0).any() else float("nan"))
            mba50 = float(np.percentile(b["mae_before_arm"], 50))
            print(f"  {bk:<22} "
                  f"{len(b):>7,} "
                  f"{100*len(b)/len(g):>5.1f}% "
                  f"{b['pnl_dollars'].mean():>+10.2f} "
                  f"{b['pnl_dollars'].sum():>+13,.0f} "
                  f"{mfe50:>8.2f} "
                  f"{mae50:>8.2f} "
                  f"{arm50:>8.1f} "
                  f"{mba50:>14.2f}")

    # ALL RTH summary across groups
    print(f"\n[RTH ALL groups combined] n={len(rth):,}  "
          f"total ${rth['pnl_dollars'].sum():>+10,.0f}  "
          f"per-trade ${rth['pnl_dollars'].mean():>+6.2f}")
    print(f"  {'bucket':<22} {'n':>7} {'pct':>6} "
          f"{'mean_pnl_$':>11} {'total_pnl_$':>13}")
    for bk in ("win_clean", "win_vshape",
               "loss_quick", "loss_runthenbreak", "timed_out"):
        b = rth[rth["bucket"] == bk]
        if len(b) == 0: continue
        print(f"  {bk:<22} "
              f"{len(b):>7,} "
              f"{100*len(b)/len(rth):>5.1f}% "
              f"{b['pnl_dollars'].mean():>+10.2f} "
              f"{b['pnl_dollars'].sum():>+13,.0f}")

    # ----------- Bucket-shape MFE/MAE percentiles -----------
    print(f"\n{'='*78}\n"
          f"DETAILED MFE / MAE percentiles per bucket × group (RTH)\n"
          f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = rth[rth["group"] == grp]
        print(f"\n[{grp}] n={len(g):,}")
        for bk in ("win_clean", "win_vshape",
                   "loss_quick", "loss_runthenbreak"):
            b = g[g["bucket"] == bk]
            if len(b) == 0: continue
            mfe = b["mfe_pts"].values
            mae = b["mae_pts"].values
            print(f"  {bk:<20} n={len(b):>5,} | "
                  f"MFE p25/50/75/90: "
                  f"{np.percentile(mfe,25):>5.2f}/"
                  f"{np.percentile(mfe,50):>5.2f}/"
                  f"{np.percentile(mfe,75):>5.2f}/"
                  f"{np.percentile(mfe,90):>5.2f} | "
                  f"MAE p25/50/75/90: "
                  f"{np.percentile(mae,25):>5.2f}/"
                  f"{np.percentile(mae,50):>5.2f}/"
                  f"{np.percentile(mae,75):>5.2f}/"
                  f"{np.percentile(mae,90):>5.2f}")

    # ----------- Hypothesis sizing -----------
    print(f"\n{'='*78}\n"
          f"HYPOTHESIS SIZING — could a tighter-SL or "
          f"BE-arming design recover edge?\n"
          f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = rth[rth["group"] == grp]
        wins = g[g["outcome"] == "win"]
        losses = g[g["outcome"] == "loss"]
        wclean = (wins["mae_before_arm"] < CLEAN_MAE_CAP).sum()
        wvshape = len(wins) - wclean
        lquick = (losses["mfe_pts"] < ARM_THRESHOLD).sum()
        lrtb = len(losses) - lquick
        print(f"\n[{grp}]")
        print(f"  Wins: {len(wins):>5,} = "
              f"{wclean:>5,} clean ({100*wclean/max(1,len(wins)):.1f}%) + "
              f"{wvshape:>5,} v-shape ({100*wvshape/max(1,len(wins)):.1f}%)")
        print(f"  Losses: {len(losses):>5,} = "
              f"{lquick:>5,} quick ({100*lquick/max(1,len(losses)):.1f}%) + "
              f"{lrtb:>5,} run-then-break "
              f"({100*lrtb/max(1,len(losses)):.1f}%)")
        # If we could perfectly turn run-then-break losses into BE
        # (zero pnl minus commission), how much would we gain?
        rtb_loss_pnl = (losses[losses["mfe_pts"] >= ARM_THRESHOLD]
                              ["pnl_dollars"].sum())
        rtb_count = (losses["mfe_pts"] >= ARM_THRESHOLD).sum()
        be_pnl_per_rtb = -COMMISSION_PTS * NQ_DOLLAR_PER_PT  # = -$5
        be_pnl_total = rtb_count * be_pnl_per_rtb
        print(f"  If we BE-stopped all run-then-break losses:")
        print(f"    current run-then-break PnL: ${rtb_loss_pnl:>+11,.0f}")
        print(f"    BE  (-$5/trade after comm): ${be_pnl_total:>+11,.0f}")
        print(f"    rescue: ${be_pnl_total - rtb_loss_pnl:>+11,.0f}")
        cur_total = g["pnl_dollars"].sum()
        new_total = cur_total + (be_pnl_total - rtb_loss_pnl)
        print(f"    group total: ${cur_total:>+11,.0f} -> "
              f"${new_total:>+11,.0f}")


if __name__ == "__main__":
    main()
