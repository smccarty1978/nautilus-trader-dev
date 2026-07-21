"""V-shape recovery add-on: 2nd contract on 1m re-cross of breach level.

POLICY
------
1. Original C1 enters at 1s bar following 1m trigger close. Uses
   prior-level SL and original PT (next-level - 2.5).
2. Walk 1s bars from entry forward. Track:
     - running adverse: did low ever dip below breach_level (long)?
     - 1m close events (every 60s, when 1s ts second == 0)
3. When BOTH (a) trade has dipped below breach_level, AND (b) a 1m
   bar closes back above breach_level (long, invert short), AND (c)
   C1 still open: ADD C2 at the next 1s bar (1s after the 1m close).
   Cap: only one add-on per trade.
4. C2 uses the SAME SL (prior_level) and PT as C1. Independent exit.
5. EOD-flat at 16:00 CT.

This is a "recovery confirmation entry" — wait until v-shape proves
itself by re-claiming the breach level on a closed bar.

Compare:
- 1-contract baseline (C1 only)
- 1+1 contract with re-cross add-on

Per group, per bucket, per year.
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

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)


def sim_path_with_recross(
    entry_idx, di, entry_px, breach_level, target_px, prior_sl_px,
    eod_idx,
    highs, lows, closes,
    ts_seconds,   # array: ts second-of-minute for each 1s bar
):
    """Walk 1s bars. Compute outcomes for C1 and C2 (if added).

    C2 trigger: low_since_entry crossed below breach_level (long),
    AND a subsequent 1s bar with second == 0 (= 1m close moment) has
    close above breach_level. C2 added at next 1s bar.

    Both contracts: prior_sl_px (SL) and target_px (PT). EOD = exit
    at close of last 1s bar before EOD.
    """
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None

    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    sli_sec = ts_seconds[entry_idx : last + 1]
    nbars = len(sli_h)

    # C1 state
    c1_open = True
    c1_outcome = None; c1_exit_px = None; c1_exit_idx = None
    # C2 state
    c2_open = False           # Not yet entered
    c2_entry_idx = -1         # slice idx where C2 enters
    c2_entry_px = None
    c2_outcome = None; c2_exit_px = None; c2_exit_idx = None
    # Re-cross tracking
    has_dipped = False
    recross_armed = False     # has 1m closed back across L?
    recross_at = -1

    for s in range(nbars):
        h = sli_h[s]; l = sli_l[s]; c = sli_c[s]; sec = sli_sec[s]

        # Track dip below breach (long: low < L; short: high > L)
        if not has_dipped:
            if di == 1 and l < breach_level:
                has_dipped = True
            elif di == -1 and h > breach_level:
                has_dipped = True

        # Check re-cross at 1m close moments (second == 0)
        if (not recross_armed and has_dipped and c1_open
                and sec == 0):
            if di == 1 and c > breach_level:
                recross_armed = True
                recross_at = s
            elif di == -1 and c < breach_level:
                recross_armed = True
                recross_at = s

        # If re-cross armed, enter C2 at next 1s bar
        if (recross_armed and not c2_open and c2_entry_idx < 0
                and s == recross_at + 1):
            # C2 entry at this bar's open
            opens_here = (highs[entry_idx + s] if False
                          else None)
            # We need the OPEN of this 1s bar; use entry_px-relative
            # but properly: open of this 1s bar = global opens[entry_idx + s]
            # We don't have opens passed in — compute from prior context
            # Solution: use sli_c[s-1] as approximation? No — use
            # actual open. We'll need opens passed. Modify below.
            pass

        # 4) Exit checks for C1
        if c1_open:
            if di == 1:
                sl_hit = (l <= prior_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= prior_sl_px)
                tgt_hit = (l <= target_px)
            if sl_hit and tgt_hit:
                c1_outcome = "loss"
                c1_exit_px = float(prior_sl_px); c1_exit_idx = s
                c1_open = False
            elif sl_hit:
                c1_outcome = "loss"
                c1_exit_px = float(prior_sl_px); c1_exit_idx = s
                c1_open = False
            elif tgt_hit:
                c1_outcome = "win"
                c1_exit_px = float(target_px); c1_exit_idx = s
                c1_open = False

        # 5) Exit checks for C2
        if c2_open:
            if di == 1:
                sl_hit = (l <= prior_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= prior_sl_px)
                tgt_hit = (l <= target_px)
            if sl_hit and tgt_hit:
                c2_outcome = "loss"
                c2_exit_px = float(prior_sl_px); c2_exit_idx = s
                c2_open = False
            elif sl_hit:
                c2_outcome = "loss"
                c2_exit_px = float(prior_sl_px); c2_exit_idx = s
                c2_open = False
            elif tgt_hit:
                c2_outcome = "win"
                c2_exit_px = float(target_px); c2_exit_idx = s
                c2_open = False

        if not c1_open and (c2_entry_idx < 0 or not c2_open):
            # C1 closed; check if C2 will fire
            if c1_open is False and c2_entry_idx < 0:
                # C2 cannot fire after C1 closes (per spec)
                if not recross_armed:
                    break

        if not c1_open and c2_entry_idx >= 0 and not c2_open:
            break

    # If still open at EOD
    if c1_open:
        c1_outcome = "eod_flat"
        c1_exit_px = float(sli_c[-1]); c1_exit_idx = nbars - 1
    if c2_open:
        c2_outcome = "eod_flat"
        c2_exit_px = float(sli_c[-1]); c2_exit_idx = nbars - 1

    c1_pnl = (c1_exit_px - entry_px) * di - COMMISSION_PTS
    if c2_entry_idx >= 0 and c2_entry_px is not None:
        c2_pnl = (c2_exit_px - c2_entry_px) * di - COMMISSION_PTS
    else:
        c2_pnl = 0.0

    return {
        "c1_outcome": c1_outcome, "c1_pnl_pts": float(c1_pnl),
        "c1_exit_idx_global": entry_idx + c1_exit_idx,
        "c2_added": c2_entry_idx >= 0,
        "c2_outcome": c2_outcome, "c2_pnl_pts": float(c2_pnl),
        "recross_at_global": (entry_idx + recross_at
                               if recross_at >= 0 else -1),
        "total_pnl_pts": float(c1_pnl + c2_pnl),
        "total_pnl_dollars": float(
            (c1_pnl + c2_pnl) * NQ_DOLLAR_PER_PT),
        "exit_idx_global": entry_idx + max(
            c1_exit_idx, c2_exit_idx if c2_exit_idx is not None else -1),
    }


# Replace the placeholder above with a proper impl using `opens` array.
def sim_recross(
    entry_idx, di, entry_px, breach_level, target_px, prior_sl_px,
    eod_idx,
    opens, highs, lows, closes, ts_seconds,
):
    n = len(highs)
    last = min(eod_idx, n - 1)
    if entry_idx >= n or last < entry_idx:
        return None
    sli_o = opens[entry_idx : last + 1]
    sli_h = highs[entry_idx : last + 1]
    sli_l = lows[entry_idx : last + 1]
    sli_c = closes[entry_idx : last + 1]
    sli_sec = ts_seconds[entry_idx : last + 1]
    nbars = len(sli_h)

    c1_open = True
    c1_outcome = None; c1_exit_px = None; c1_exit_idx = None
    c2_open = False
    c2_entry_idx = -1; c2_entry_px = None
    c2_outcome = None; c2_exit_px = None; c2_exit_idx = None
    has_dipped = False
    recross_armed = False; recross_at = -1
    c1_tp_at = -1   # not used here but kept for parity

    for s in range(nbars):
        o = sli_o[s]; h = sli_h[s]; l = sli_l[s]; c = sli_c[s]
        sec = sli_sec[s]

        # Detect dip below breach
        if not has_dipped:
            if di == 1 and l < breach_level:
                has_dipped = True
            elif di == -1 and h > breach_level:
                has_dipped = True

        # 1m close re-cross detection (only if not yet armed,
        # has dipped, and C1 still open)
        if (not recross_armed and has_dipped and c1_open
                and sec == 0):
            if di == 1 and c > breach_level:
                recross_armed = True; recross_at = s
            elif di == -1 and c < breach_level:
                recross_armed = True; recross_at = s

        # Add C2 at the bar AFTER recross_at
        if (recross_armed and c2_entry_idx < 0
                and s == recross_at + 1):
            c2_entry_idx = s
            c2_entry_px = float(o)
            c2_open = True

        # C1 exit checks
        if c1_open:
            if di == 1:
                sl_hit = (l <= prior_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= prior_sl_px)
                tgt_hit = (l <= target_px)
            # Conservative: SL beats PT in same bar
            if sl_hit:
                c1_outcome = "loss"
                c1_exit_px = float(prior_sl_px); c1_exit_idx = s
                c1_open = False
            elif tgt_hit:
                c1_outcome = "win"
                c1_exit_px = float(target_px); c1_exit_idx = s
                c1_open = False

        # C2 exit checks (only if C2 has entered)
        if c2_open:
            if di == 1:
                sl_hit = (l <= prior_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= prior_sl_px)
                tgt_hit = (l <= target_px)
            if sl_hit:
                c2_outcome = "loss"
                c2_exit_px = float(prior_sl_px); c2_exit_idx = s
                c2_open = False
            elif tgt_hit:
                c2_outcome = "win"
                c2_exit_px = float(target_px); c2_exit_idx = s
                c2_open = False

        # Break if everything closed
        if not c1_open and not c2_open and c2_entry_idx >= 0:
            break
        if not c1_open and not recross_armed:
            # C1 done, no recross detected before C1 exit -> can't add C2
            break

    if c1_open:
        c1_outcome = "eod_flat"
        c1_exit_px = float(sli_c[-1]); c1_exit_idx = nbars - 1
    if c2_open:
        c2_outcome = "eod_flat"
        c2_exit_px = float(sli_c[-1]); c2_exit_idx = nbars - 1

    c1_pnl = (c1_exit_px - entry_px) * di - COMMISSION_PTS
    if c2_entry_idx >= 0 and c2_entry_px is not None:
        c2_pnl = (c2_exit_px - c2_entry_px) * di - COMMISSION_PTS
    else:
        c2_pnl = 0.0

    last_local = c1_exit_idx
    if c2_exit_idx is not None:
        last_local = max(last_local, c2_exit_idx)

    return {
        "c1_outcome": c1_outcome, "c1_pnl_pts": float(c1_pnl),
        "c2_added": c2_entry_idx >= 0,
        "c2_outcome": c2_outcome,
        "c2_pnl_pts": float(c2_pnl),
        "c2_entry_px": (float(c2_entry_px)
                         if c2_entry_px is not None else None),
        "recross_local": recross_at,
        "total_pnl_pts": float(c1_pnl + c2_pnl),
        "total_pnl_dollars": float(
            (c1_pnl + c2_pnl) * NQ_DOLLAR_PER_PT),
        "c1_only_pnl_dollars": float(c1_pnl * NQ_DOLLAR_PER_PT),
        "exit_idx_global": entry_idx + last_local,
    }


def harvest(year):
    print(f"\n[{year}] loading & harvesting...")
    bars_1s = load_v0_1s(Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
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
        trades.append({
            "year": year, "entry_1s_idx": e, "entry_px": entry_px,
            "direction": di, "target": float(tr["target"]),
            "prior_sl": float(tr["stop"]),
            "breach_level": float(tr["breach_level"]),
            "eod_idx": int(next_eod[e]),
            "level_pair": tr["level_pair"],
            "group": assign_group(tr["level_pair"]),
            "bucket": bucket,
        })
    print(f"  RTH trades on baseline chain: {len(trades):,}")
    return trades, opens, highs, lows, closes, ts_seconds


def main():
    t0 = time.time()
    all_trades = []
    arrays = {}
    for year in (2024, 2025):
        trs, o, h, l, c, sec = harvest(year)
        arrays[year] = (o, h, l, c, sec)
        all_trades.extend(trs)
    print(f"\nTotal RTH trades: {len(all_trades):,}\n")

    # Run sim
    print("Running re-cross add-on sim...")
    rows = []
    for t in all_trades:
        o, h, l, c, sec = arrays[t["year"]]
        r = sim_recross(
            t["entry_1s_idx"], t["direction"], t["entry_px"],
            t["breach_level"], t["target"], t["prior_sl"],
            t["eod_idx"], o, h, l, c, sec)
        if r is None: continue
        rows.append({**t, **r})
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "vshape_recross_addon.parquet")
    print(f"Saved {len(df):,} rows.")

    # ----- Per group: re-cross add-on rate by bucket -----
    print(f"\n{'='*78}")
    print(f"RE-CROSS ADD-ON RATE per bucket (= % of trades that get C2)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        n = len(g); n_add = int(g["c2_added"].sum())
        print(f"\n[{grp}] n={n:,}, C2 added={n_add:,} "
              f"({100*n_add/n:.1f}%)")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            ad = int(sub["c2_added"].sum())
            print(f"  {bk:<22} n={len(sub):>5,} C2_added={ad:>5,} "
                  f"({100*ad/len(sub):>5.1f}%)")

    # ----- PnL: 1-ctr baseline vs 1+1 add-on -----
    print(f"\n{'='*78}")
    print(f"PnL COMPARISON: 1-ctr baseline (C1 only) vs 1+1 add-on")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        c1_only_total = float(g["c1_only_pnl_dollars"].sum())
        full_total = float(g["total_pnl_dollars"].sum())
        c2_contribution = full_total - c1_only_total
        print(f"\n[{grp}] n={len(g):,}")
        print(f"  1-ctr baseline (C1 only):  total ${c1_only_total:+,.0f}  "
              f"(${g['c1_only_pnl_dollars'].mean():+.2f}/tr)")
        print(f"  1+1 with re-cross add-on:  total ${full_total:+,.0f}  "
              f"(${g['total_pnl_dollars'].mean():+.2f}/tr)")
        print(f"  C2 contribution: ${c2_contribution:+,.0f}")

        # Per year
        for yr in (2024, 2025):
            sg = g[g["year"] == yr]
            if len(sg) == 0: continue
            c1_y = float(sg["c1_only_pnl_dollars"].sum())
            full_y = float(sg["total_pnl_dollars"].sum())
            print(f"  {yr}: 1-ctr ${c1_y:+,.0f}, "
                  f"1+1 ${full_y:+,.0f}, "
                  f"C2 contrib ${full_y-c1_y:+,.0f}")

    # ----- Per-bucket PnL impact -----
    print(f"\n{'='*78}")
    print(f"PER-BUCKET — 1-ctr vs 1+1 add-on")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}]")
        print(f"  {'bucket':<22} {'n':>5} {'C2%':>5} "
              f"{'1ctr_$/tr':>10} {'1+1_$/tr':>10} "
              f"{'C2_$/tr':>10}  {'1ctr_total':>13} {'1+1_total':>13}")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            c1_pt = sub["c1_only_pnl_dollars"].mean()
            full_pt = sub["total_pnl_dollars"].mean()
            c2_only = sub["c2_pnl_pts"] * NQ_DOLLAR_PER_PT
            c2_pt = float(c2_only.mean())
            c2_pct = 100 * sub["c2_added"].mean()
            print(f"  {bk:<22} {len(sub):>5,} {c2_pct:>4.1f}% "
                  f"{c1_pt:>+9.2f}  {full_pt:>+9.2f}  "
                  f"{c2_pt:>+9.2f}  "
                  f"{sub['c1_only_pnl_dollars'].sum():>+12,.0f}  "
                  f"{sub['total_pnl_dollars'].sum():>+12,.0f}")

    # ----- C2 outcome breakdown -----
    print(f"\n{'='*78}")
    print(f"C2 OUTCOMES (only C2 trades)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[(df["group"] == grp) & (df["c2_added"])]
        if len(g) == 0: continue
        n = len(g)
        win = int((g["c2_outcome"] == "win").sum())
        loss = int((g["c2_outcome"] == "loss").sum())
        eod = int((g["c2_outcome"] == "eod_flat").sum())
        c2_total = float((g["c2_pnl_pts"] * NQ_DOLLAR_PER_PT).sum())
        print(f"\n[{grp}] C2 n={n:,}  "
              f"WR={100*win/n:.1f}% (win={win:,}, loss={loss:,}, "
              f"eod={eod:,})")
        print(f"  C2 total ${c2_total:+,.0f}  "
              f"per-C2 ${c2_total/n:+.2f}")
        # Per year
        for yr in (2024, 2025):
            sg = g[g["year"] == yr]
            if len(sg) == 0: continue
            sw = int((sg["c2_outcome"] == "win").sum())
            print(f"  {yr}: n={len(sg):,} WR={100*sw/len(sg):.1f}% "
                  f"C2 total ${(sg['c2_pnl_pts']*NQ_DOLLAR_PER_PT).sum():+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
