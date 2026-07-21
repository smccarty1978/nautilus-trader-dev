"""V-recovery add-on with QUALIFIED trigger filter.

POLICY
------
Same base as analyze_vshape_recross_addon.py:
  C1 enters at 1s after 1m trigger close. prior-level SL + original PT.

Trigger qualification for C2 (all must be true at re-cross moment):
  1) Trade dipped below breach level (existing)
  2) 1m bar closes back above breach (existing)
  3) NEW: max_MAE since entry >= MAE_MIN (3 pts)
       — must be a real v-shape candidate, not noise
  4) NEW: max_MFE / max_MAE >= MFE_MAE_RATIO (0.6)
       — real recovery, not weak bounce; trade had meaningful
         early move relative to dip
  5) NEW: HOLD CONFIRMATION — for HOLD_BARS (5) 1s bars after the
       1m close, every 1s close must be > breach (long, invert short)
       — momentum confirmation, not just one bar's close

If all 5 conditions met, add C2 at the bar AFTER the hold window
(i.e., re-cross at T, hold check spans T+1..T+5, C2 enters at T+6).

C2 uses prior_level SL and original PT (same as C1).
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

from studies.level_momentum_continuation.analyze_vshape_recross_addon import (
    harvest,
)
from studies.level_momentum_continuation.analyze_2contract_tp5_be import (
    NQ_DOLLAR_PER_PT, COMMISSION_PTS,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

# Qualified-add-on parameters
MAE_MIN = 3.0           # max_MAE at re-cross must be >= this
MFE_MAE_RATIO = 0.6     # max_MFE / max_MAE at re-cross must be >= this
HOLD_BARS = 5           # 1s bars to confirm after re-cross


def sim_recross_qualified(
    entry_idx, di, entry_px, breach_level, target_px, prior_sl_px,
    eod_idx,
    opens, highs, lows, closes, ts_seconds,
    mae_min=MAE_MIN, mfe_mae_ratio=MFE_MAE_RATIO,
    hold_bars=HOLD_BARS,
):
    """Walk 1s bars. C2 added only if qualification AND hold pass."""
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
    running_mfe = 0.0
    running_mae = 0.0

    # Re-cross + hold state machine
    # state: 'idle' -> 'recross_at_T' (after re-cross detected)
    # During hold: count consecutive 1s closes above L
    # At T + hold_bars: if all closes passed, add C2 at T + hold_bars + 1
    recross_state = "idle"   # idle | holding
    recross_at = -1
    hold_pass = True         # tracks whether hold confirmation still valid
    qualifies = False        # at re-cross moment, did MAE/MFE pass

    for s in range(nbars):
        o = sli_o[s]; h = sli_h[s]; l = sli_l[s]; c = sli_c[s]
        sec = sli_sec[s]

        # Update running MFE / MAE
        if di == 1:
            cur_mfe = h - entry_px; cur_mae = entry_px - l
        else:
            cur_mfe = entry_px - l; cur_mae = h - entry_px
        if cur_mfe > running_mfe: running_mfe = cur_mfe
        if cur_mae > running_mae: running_mae = cur_mae

        # Detect dip below breach
        if not has_dipped:
            if di == 1 and l < breach_level: has_dipped = True
            elif di == -1 and h > breach_level: has_dipped = True

        # Re-cross detection: at 1m close moment, has_dipped, C1 open,
        # state idle (so we only attempt one re-cross per trade)
        if (recross_state == "idle" and has_dipped and c1_open
                and sec == 0):
            crossed = ((di == 1 and c > breach_level) or
                       (di == -1 and c < breach_level))
            if crossed:
                # Apply qualification at re-cross moment
                ratio_ok = (running_mae > 0 and
                            running_mfe / running_mae >= mfe_mae_ratio)
                mae_ok = running_mae >= mae_min
                qualifies = mae_ok and ratio_ok
                recross_state = "holding"
                recross_at = s
                hold_pass = qualifies   # only proceed if pre-qual passes

        # During hold window: each 1s close must be above L (long)
        if recross_state == "holding":
            elapsed = s - recross_at  # 0 = re-cross bar itself
            if 1 <= elapsed <= hold_bars:
                # Check 1s close stays above breach
                if di == 1 and c <= breach_level:
                    hold_pass = False
                elif di == -1 and c >= breach_level:
                    hold_pass = False
            # At elapsed == hold_bars + 1, decide whether to add C2
            if elapsed == hold_bars + 1:
                if hold_pass and qualifies and c1_open and not c2_open:
                    c2_entry_idx = s
                    c2_entry_px = float(o)
                    c2_open = True
                # End of state machine — only one C2 per trade
                recross_state = "done"

        # C1 exit checks
        if c1_open:
            if di == 1:
                sl_hit = (l <= prior_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= prior_sl_px)
                tgt_hit = (l <= target_px)
            if sl_hit:
                c1_outcome = "loss"
                c1_exit_px = float(prior_sl_px); c1_exit_idx = s
                c1_open = False
            elif tgt_hit:
                c1_outcome = "win"
                c1_exit_px = float(target_px); c1_exit_idx = s
                c1_open = False

        # C2 exit checks
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

        if not c1_open and not c2_open and c2_entry_idx >= 0:
            break
        if not c1_open and recross_state == "done" and c2_entry_idx < 0:
            break
        if not c1_open and recross_state == "idle":
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
        "c1_outcome": c1_outcome,
        "c1_pnl_pts": float(c1_pnl),
        "c2_added": c2_entry_idx >= 0,
        "c2_outcome": c2_outcome,
        "c2_pnl_pts": float(c2_pnl),
        "c2_entry_px": (float(c2_entry_px) if c2_entry_px else None),
        "recross_local": recross_at,
        "qualifies_pre_hold": qualifies,
        "hold_pass": hold_pass,
        "total_pnl_pts": float(c1_pnl + c2_pnl),
        "total_pnl_dollars": float(
            (c1_pnl + c2_pnl) * NQ_DOLLAR_PER_PT),
        "c1_only_pnl_dollars": float(c1_pnl * NQ_DOLLAR_PER_PT),
        "exit_idx_global": entry_idx + last_local,
    }


def main():
    t0 = time.time()
    all_trades = []
    arrays = {}
    for year in (2024, 2025):
        trs, o, h, l, c, sec = harvest(year)
        arrays[year] = (o, h, l, c, sec)
        all_trades.extend(trs)
    print(f"\nTotal RTH trades: {len(all_trades):,}\n")

    # Sweep over (mae_min, mfe_mae_ratio, hold_bars) — 3 cells:
    #   - baseline = unfiltered (MAE_MIN=0, ratio=0, hold=0)
    #   - mid = MAE>=3, ratio>=0.4, hold=3
    #   - strict = MAE>=3, ratio>=0.6, hold=5
    configs = [
        ("unfiltered", 0.0, 0.0, 0),
        ("mid:MAE3_R0.4_H3", 3.0, 0.4, 3),
        ("strict:MAE3_R0.6_H5", 3.0, 0.6, 5),
        ("loose:MAE3_R0.0_H0", 3.0, 0.0, 0),
        ("ratio_only:R0.6_H0", 0.0, 0.6, 0),
        ("hold_only:H5", 0.0, 0.0, 5),
    ]

    summary = []
    for label, mae_min, ratio, hold in configs:
        print(f"\n{'='*78}")
        print(f"CONFIG: {label}  (MAE>={mae_min}, MFE/MAE>={ratio}, "
              f"hold={hold} bars)")
        print(f"{'='*78}")
        rows = []
        for t in all_trades:
            o, h, l, c, sec = arrays[t["year"]]
            r = sim_recross_qualified(
                t["entry_1s_idx"], t["direction"], t["entry_px"],
                t["breach_level"], t["target"], t["prior_sl"],
                t["eod_idx"], o, h, l, c, sec,
                mae_min=mae_min, mfe_mae_ratio=ratio,
                hold_bars=hold)
            if r is None: continue
            rows.append({**t, **r, "config": label})
        df = pd.DataFrame(rows)

        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            g = df[df["group"] == grp]
            if len(g) == 0: continue
            n = len(g); n_add = int(g["c2_added"].sum())
            c1_total = float(g["c1_only_pnl_dollars"].sum())
            full_total = float(g["total_pnl_dollars"].sum())
            print(f"\n  [{grp}] n={n:,}  C2_added={n_add:,} "
                  f"({100*n_add/n:.1f}%)")
            print(f"    1-ctr only: ${c1_total:+,.0f}  "
                  f"(${c1_total/n:+.2f}/tr)")
            print(f"    1+1: ${full_total:+,.0f}  "
                  f"(${full_total/n:+.2f}/tr)")
            print(f"    C2 contribution: ${full_total - c1_total:+,.0f}")
            for yr in (2024, 2025):
                sg = g[g["year"] == yr]
                if len(sg) == 0: continue
                print(f"    {yr}: 1+1 ${sg['total_pnl_dollars'].sum():+,.0f}")
            # Per bucket: how often does C2 fire and how much does it earn
            print(f"    {'bucket':<22} {'n':>5} {'C2%':>6} "
                  f"{'C2 $/tr':>10} {'C2 total':>12}")
            for bk in ("win_clean", "win_vshape",
                       "loss_runthenbreak", "loss_quick"):
                sub = g[g["bucket"] == bk]
                if len(sub) == 0: continue
                c2_total = float((sub["c2_pnl_pts"] * NQ_DOLLAR_PER_PT).sum())
                c2_pct = 100 * sub["c2_added"].mean()
                c2_pt = float((sub["c2_pnl_pts"] * NQ_DOLLAR_PER_PT).mean())
                print(f"    {bk:<22} {len(sub):>5,} {c2_pct:>5.1f}%  "
                      f"{c2_pt:>+8.2f}  {c2_total:>+12,.0f}")
            summary.append({
                "config": label, "group": grp,
                "n": n, "c2_added": n_add,
                "c2_pct": 100*n_add/n,
                "c1_only_total": c1_total,
                "full_total": full_total,
                "c2_contribution": full_total - c1_total,
            })

    pd.DataFrame(summary).to_csv(
        OUT / "vshape_recross_qualified.csv", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.1f}s")
    print(f"saved: {OUT / 'vshape_recross_qualified.csv'}")


if __name__ == "__main__":
    main()
