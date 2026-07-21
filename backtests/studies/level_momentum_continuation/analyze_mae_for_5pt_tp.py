"""For each RTH breakout-filter trade, compute:
- Did MFE ever reach +5.25 pts (= 5pt TP + 1 tick buffer for fill)?
- If yes, MAX MAE accumulated BEFORE first reaching +5.25
- Bucket assignment

Per group (A_25pt, B_14_15pt, C_10_11pt) report:
- % of trades reaching +5.25 MFE (overall + per bucket)
- MAE-before-first-+5.25 distribution (p25-p99) for those reaching
- Implied SL distance to protect 90% / 95% of "TP-fillers"

This answers: "What SL allows the trades that COULD hit our +5 TP
to actually reach it without being stopped first?"
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
    sim_baseline_path, assign_bucket, ARM_THRESHOLD, CLEAN_MAE_CAP,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

TP_PLUS_TICK = 5.25  # 5pt TP + 1 tick (so MFE 5.25 ensures TP fills)


def walk_path_for_5pt(entry_idx, di, entry_px, prior_sl_px,
                      target_px, eod_idx,
                      highs, lows, closes):
    """Walk 1s path. Track until MFE reaches 5.25 OR natural exit
    (PT/prior-level SL/EOD). Reaching 5.25 only counts if it happens
    BEFORE the natural exit (otherwise it's post-stop phantom).

    Returns:
      reached_525: bool, did running MFE cross 5.25 BEFORE natural exit
      mae_before_525: max MAE during [entry, t_525) (None if not reached)
      max_mfe_natural: max MFE over [entry, natural_exit]
      max_mae_natural: max MAE over [entry, natural_exit]
    """
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None

    running_mfe = 0.0
    running_mae = 0.0
    mae_before_525 = 0.0
    reached_525 = False
    t_525 = -1
    natural_exit = -1
    nbars = last - entry_idx + 1

    for s in range(nbars):
        i = entry_idx + s
        h = highs[i]; l = lows[i]
        if di == 1:
            cur_mfe = h - entry_px
            cur_mae = entry_px - l
            sl_hit = (l <= prior_sl_px)
            tgt_hit = (h >= target_px)
        else:
            cur_mfe = entry_px - l
            cur_mae = h - entry_px
            sl_hit = (h >= prior_sl_px)
            tgt_hit = (l <= target_px)

        if cur_mfe > running_mfe:
            running_mfe = cur_mfe
        if cur_mae > running_mae:
            running_mae = cur_mae

        # Track MAE before reaching 5.25 (still updating)
        if not reached_525:
            if cur_mae > mae_before_525:
                mae_before_525 = cur_mae
            if running_mfe >= TP_PLUS_TICK:
                reached_525 = True
                t_525 = s

        # Natural exit fires
        if sl_hit or tgt_hit:
            natural_exit = s
            break

    if natural_exit < 0:
        natural_exit = nbars - 1  # EOD

    return {
        "reached_525": reached_525,
        "t_525": t_525,
        "mae_before_525": (float(mae_before_525)
                            if reached_525 else None),
        "max_mfe_natural": float(running_mfe),
        "max_mae_natural": float(running_mae),
        "natural_exit_s": natural_exit,
    }


def main():
    t0 = time.time()
    rows = []

    for year in (2024, 2025):
        print(f"\n[{year}] loading & walking paths...")
        bars_1s = load_v0_1s(
            Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
        bars_1s = annotate_sessions_1s(bars_1s)
        bars_1m = bars_1s[
            ["open", "high", "low", "close", "volume"]
        ].resample("1min", label="right", closed="right").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"
        }).dropna(subset=["open", "high", "low", "close"])
        bars_1m = annotate_sessions_ct(bars_1m)
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
        next_eod = precompute_eod_1s(bars_1s_reset)

        last_chain_exit = -1
        for tr in triggers:
            ts = pd.Timestamp(tr["bar_ts_close"])
            if ts.tz is None: ts = ts.tz_localize("UTC")
            else: ts = ts.tz_convert("UTC")
            e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
            if e < 0: continue
            if e <= last_chain_exit: continue
            di = tr["direction"]
            entry_px = float(opens[e])
            # Use baseline outcome for bucket assignment
            bp = sim_baseline_path(
                e, di, entry_px, float(tr["target"]),
                float(tr["stop"]), int(next_eod[e]),
                highs, lows, closes)
            if bp is None: continue
            last_chain_exit = bp["exit_idx_global"]
            if sessions[e] != "RTH":
                continue
            bucket = assign_bucket(
                bp["outcome"], bp["mfe_t"], bp["mae_t"], bp["max_mfe"])
            wp = walk_path_for_5pt(
                e, di, entry_px, float(tr["stop"]),
                float(tr["target"]),
                int(next_eod[e]), highs, lows, closes)
            if wp is None: continue
            rows.append({
                "year": year, "level_pair": tr["level_pair"],
                "group": assign_group(tr["level_pair"]),
                "direction": di, "bucket": bucket,
                "baseline_outcome": bp["outcome"],
                **wp,
            })
        print(f"  RTH trades: {sum(1 for r in rows if r['year']==year):,}")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "mae_for_5pt_tp.parquet")
    print(f"\nTotal RTH trades: {len(df):,}  (saved)")
    print(f"  runtime: {time.time()-t0:.1f}s")

    # ---- Per group: % reaching 5.25 + MAE distribution ----
    print(f"\n{'='*78}")
    print(f"% reaching MFE >= +5.25 pts (would fill +5 TP) per group")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        n = len(g)
        n_reach = int(g["reached_525"].sum())
        print(f"\n[{grp}] n_total={n:,}  n_reach_5.25={n_reach:,} "
              f"({100*n_reach/n:.1f}%)")
        # Per bucket
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            sub_reach = sub[sub["reached_525"]]
            print(f"    {bk:<22} n={len(sub):>5,} "
                  f"reach_5.25={len(sub_reach):>5,} "
                  f"({100*len(sub_reach)/len(sub):>5.1f}%)")

    # ---- MAE-before-5.25 distribution (among those reaching) ----
    print(f"\n{'='*78}")
    print(f"MAE accumulated BEFORE first MFE>=+5.25 (among trades "
          f"reaching +5.25)")
    print(f"This is the SL distance that would let X% of TP-fillers "
          f"actually reach the TP.")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[(df["group"] == grp) & (df["reached_525"])]
        if len(g) == 0: continue
        mae = g["mae_before_525"].values
        print(f"\n[{grp}] n_TP_fillers={len(g):,}")
        print(f"  MAE-before-5.25 percentiles:")
        for q in (25, 50, 75, 80, 85, 90, 95, 99):
            v = np.percentile(mae, q)
            print(f"    p{q:>2}: {v:>6.2f} pts  "
                  f"(SL >= {v:.2f} protects ~{q}% of TP-fillers)")
        print(f"  mean: {mae.mean():>6.2f}, max: {mae.max():>6.2f}")

        # Per-bucket breakdown
        print(f"\n  Per-bucket (among trades reaching 5.25):")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            mae_b = sub["mae_before_525"].values
            print(f"    {bk:<22} n={len(sub):>5,} "
                  f"MAE p50/p75/p90/p95/p99 = "
                  f"{np.percentile(mae_b,50):>5.2f}/"
                  f"{np.percentile(mae_b,75):>5.2f}/"
                  f"{np.percentile(mae_b,90):>5.2f}/"
                  f"{np.percentile(mae_b,95):>5.2f}/"
                  f"{np.percentile(mae_b,99):>5.2f}")

    # ---- Decision summary table ----
    print(f"\n{'='*78}")
    print(f"DESIGN SUMMARY — SL distance vs % of TP-fillers protected")
    print(f"(restricted to trades that reach +5.25 BEFORE natural exit)")
    print(f"{'='*78}")
    print(f"\n  group        n_reach    p75      p90      p95")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[(df["group"] == grp) & (df["reached_525"])]
        if len(g) == 0: continue
        mae = g["mae_before_525"].values
        print(f"  {grp:<12} {len(g):>6,}    "
              f"{np.percentile(mae,75):>5.2f}    "
              f"{np.percentile(mae,90):>5.2f}    "
              f"{np.percentile(mae,95):>5.2f}")

    # ---- Combined "winning" buckets only (the ones we want to keep) ----
    print(f"\n{'='*78}")
    print(f"WIN BUCKETS ONLY (clean+vshape) — trades we want to KEEP")
    print(f"{'='*78}")
    win_buckets = ("win_clean", "win_vshape")
    print(f"\n  group         n_win     p75      p90      p95      p99")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[(df["group"] == grp) &
                (df["reached_525"]) &
                (df["bucket"].isin(win_buckets))]
        if len(g) == 0: continue
        mae = g["mae_before_525"].values
        print(f"  {grp:<12} {len(g):>6,}    "
              f"{np.percentile(mae,75):>5.2f}    "
              f"{np.percentile(mae,90):>5.2f}    "
              f"{np.percentile(mae,95):>5.2f}    "
              f"{np.percentile(mae,99):>5.2f}")


if __name__ == "__main__":
    main()
