"""V-shape recovery add-on with POST-ADD FAILURE MANAGEMENT.

Design (per user spec May 2026):

  C1: original Goldilocks breakout entry, prior_level SL, full PT.
      Unchanged from baseline.

  C2 (v-recovery add-on with failure management):
    Trigger:
      1) Trade has dipped below breach level (long: low < L)
      2) 1m bar closes back above breach level
      3) max_MAE since entry >= 3 pts (real v-shape)
    Entry: open of 1s bar after re-cross 1m close.

    Initial tight stop (TIGHTER of):
      long:  max(recross_1m_low - 0.25, breach_level - 1.0)
      short: min(recross_1m_high + 0.25, breach_level + 1.0)

    Validation: if C2 doesn't reach +2.5 MFE within 60s, scratch
                C2 at the close of that bar.

    At +5 MFE: stop transitions to STATIC BE+1tick (no trailing).

    C2 PT: same full PT as C1.

  Within-bar priority (conservative): stop > PT.

This attacks "fake recoveries" — RtB losers that re-cross but stall
without continuing — by killing them early with a tight stop or the
validation timeout.
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
    NQ_DOLLAR_PER_PT, COMMISSION_PTS, TICK_SIZE,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")
OUT.mkdir(parents=True, exist_ok=True)

MAE_MIN = 3.0
VALIDATION_SECS = 60
PLUS5_THRESHOLD = 5.0
BREACH_BUFFER = 1.0          # breach_level ± 1 pt
BAR_BUFFER = 0.25            # recross bar low/high ± 1 tick
BE_OFFSET = 0.25             # +1 tick on BE


def sim_failmgmt(
    entry_idx, di, entry_px, breach_level, target_px, prior_sl_px,
    eod_idx,
    opens, highs, lows, closes, ts_seconds,
    mae_min=MAE_MIN, validation_secs=VALIDATION_SECS,
    plus5=PLUS5_THRESHOLD,
    breach_buffer=BREACH_BUFFER, bar_buffer=BAR_BUFFER,
    be_offset=BE_OFFSET,
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

    # C1 state
    c1_open = True
    c1_outcome = None; c1_exit_px = None; c1_exit_idx = None

    # C2 state
    c2_open = False
    c2_entry_idx = -1
    c2_entry_px = None
    c2_stop_px = None
    c2_be_active = False
    c2_running_mfe = 0.0
    c2_outcome = None
    c2_exit_px = None
    c2_exit_idx = None
    c2_pending_entry = -1
    c2_init_stop_pending = None

    # Trade-level state
    has_dipped = False
    c1_running_mae = 0.0
    recross_attempted = False

    # 1m bar tracking
    running_1m_low = float("inf")
    running_1m_high = float("-inf")

    for s in range(nbars):
        o = sli_o[s]; h = sli_h[s]; l = sli_l[s]; c = sli_c[s]
        sec = sli_sec[s]

        # --- Update C1 running MAE (for filter) ---
        if di == 1:
            cur_mae = entry_px - l
        else:
            cur_mae = h - entry_px
        if cur_mae > c1_running_mae:
            c1_running_mae = cur_mae

        # --- Detect dip below breach ---
        if not has_dipped:
            if di == 1 and l < breach_level: has_dipped = True
            elif di == -1 and h > breach_level: has_dipped = True

        # --- Update running 1m bar ---
        if l < running_1m_low: running_1m_low = l
        if h > running_1m_high: running_1m_high = h

        # --- 1m close moment (sec == 0): check re-cross ---
        if sec == 0:
            completed_1m_low = running_1m_low
            completed_1m_high = running_1m_high

            if (not recross_attempted and has_dipped and c1_open):
                crossed = ((di == 1 and c > breach_level) or
                           (di == -1 and c < breach_level))
                if crossed and c1_running_mae >= mae_min:
                    if di == 1:
                        c2_init_stop_pending = max(
                            completed_1m_low - bar_buffer,
                            breach_level - breach_buffer)
                    else:
                        c2_init_stop_pending = min(
                            completed_1m_high + bar_buffer,
                            breach_level + breach_buffer)
                    c2_pending_entry = s + 1
                    recross_attempted = True

            # Reset for next 1m bar
            running_1m_low = float("inf")
            running_1m_high = float("-inf")

        # --- Enter C2 at scheduled bar ---
        if (c2_pending_entry >= 0 and not c2_open and c2_entry_idx < 0
                and s == c2_pending_entry):
            c2_entry_idx = s
            c2_entry_px = float(o)
            c2_stop_px = float(c2_init_stop_pending)
            c2_open = True
            c2_running_mfe = 0.0

        # --- C1 exit checks (independent of C2) ---
        # Conservative: SL beats PT in same bar
        if c1_open:
            if di == 1:
                c1_sl = (l <= prior_sl_px)
                c1_tgt = (h >= target_px)
            else:
                c1_sl = (h >= prior_sl_px)
                c1_tgt = (l <= target_px)
            if c1_sl:
                c1_open = False
                c1_outcome = "loss"
                c1_exit_px = float(prior_sl_px); c1_exit_idx = s
            elif c1_tgt:
                c1_open = False
                c1_outcome = "win"
                c1_exit_px = float(target_px); c1_exit_idx = s

        # --- C2 logic (if open) ---
        if c2_open:
            # Update C2 MFE
            if di == 1:
                c2_cur_mfe = h - c2_entry_px
            else:
                c2_cur_mfe = c2_entry_px - l
            if c2_cur_mfe > c2_running_mfe:
                c2_running_mfe = c2_cur_mfe

            # Validation: if not at +2.5 MFE within window, scratch
            secs_since = s - c2_entry_idx
            if (not c2_be_active and c2_running_mfe < 2.5
                    and secs_since >= validation_secs):
                c2_open = False
                c2_outcome = "validation_exit"
                c2_exit_px = float(c)
                c2_exit_idx = s

            # Transition: if MFE >= +5, lock stop at static BE+1tick
            if (c2_open and not c2_be_active
                    and c2_running_mfe >= plus5):
                c2_be_active = True
                if di == 1:
                    c2_stop_px = c2_entry_px + be_offset
                else:
                    c2_stop_px = c2_entry_px - be_offset

            # C2 stop check (conservative — wins same bar)
            if c2_open:
                if di == 1:
                    stop_hit = (l <= c2_stop_px)
                else:
                    stop_hit = (h >= c2_stop_px)
                if stop_hit:
                    c2_open = False
                    c2_outcome = ("be_stop" if c2_be_active
                                  else "tight_stop")
                    c2_exit_px = float(c2_stop_px)
                    c2_exit_idx = s

            # C2 PT check
            if c2_open:
                if di == 1:
                    tgt = (h >= target_px)
                else:
                    tgt = (l <= target_px)
                if tgt:
                    c2_open = False
                    c2_outcome = "win"
                    c2_exit_px = float(target_px); c2_exit_idx = s

        # --- Break early if everything done ---
        if not c1_open and not c2_open and c2_entry_idx >= 0:
            break
        if not c1_open and not recross_attempted:
            break

    # EOD-flat
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
        "c2_init_stop": (float(c2_init_stop_pending)
                         if c2_init_stop_pending is not None else None),
        "c2_be_active": c2_be_active,
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

    print(f"Running v-recovery with failure management...")
    print(f"  MAE_MIN={MAE_MIN}, VALIDATION_SECS={VALIDATION_SECS}, "
          f"PLUS5={PLUS5_THRESHOLD}")
    print(f"  C2 init stop: tighter of (recross_bar_low/high "
          f"+/- {BAR_BUFFER}, breach_level +/- {BREACH_BUFFER})")
    print(f"  At +5 MFE: static BE+{BE_OFFSET} (no trailing)")

    rows = []
    for t in all_trades:
        o, h, l, c, sec = arrays[t["year"]]
        r = sim_failmgmt(
            t["entry_1s_idx"], t["direction"], t["entry_px"],
            t["breach_level"], t["target"], t["prior_sl"],
            t["eod_idx"], o, h, l, c, sec)
        if r is None: continue
        rows.append({**t, **r})
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "vshape_failmgmt.parquet")
    print(f"Saved {len(df):,} rows.")

    # ----- Per group: C2 add rate by bucket -----
    print(f"\n{'='*78}")
    print(f"C2 ADD RATE per bucket (with failure management)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        n = len(g); n_add = int(g["c2_added"].sum())
        print(f"\n[{grp}] n={n:,}  C2_added={n_add:,} "
              f"({100*n_add/n:.1f}%)")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            ad = int(sub["c2_added"].sum())
            print(f"  {bk:<22} n={len(sub):>5,} C2_added={ad:>5,} "
                  f"({100*ad/len(sub):>5.1f}%)")

    # ----- C2 outcome distribution -----
    print(f"\n{'='*78}")
    print(f"C2 OUTCOME distribution (only C2 trades)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[(df["group"] == grp) & (df["c2_added"])]
        if len(g) == 0: continue
        n = len(g)
        win = int((g["c2_outcome"] == "win").sum())
        be = int((g["c2_outcome"] == "be_stop").sum())
        tight = int((g["c2_outcome"] == "tight_stop").sum())
        val = int((g["c2_outcome"] == "validation_exit").sum())
        eod = int((g["c2_outcome"] == "eod_flat").sum())
        c2_total = float((g["c2_pnl_pts"] * NQ_DOLLAR_PER_PT).sum())
        print(f"\n[{grp}] C2 n={n:,}  "
              f"WR={100*win/n:.1f}% (PT={win}, BE={be}, "
              f"tight={tight}, valid_exit={val}, EOD={eod})")
        print(f"  C2 total ${c2_total:+,.0f}  "
              f"per-C2 ${c2_total/n:+.2f}")

    # ----- PnL: 1-ctr vs 1+1 with failure mgmt -----
    print(f"\n{'='*78}")
    print(f"PnL: 1-ctr (C1 only) vs 1+1 (C1 + failure-managed C2)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        c1_total = float(g["c1_only_pnl_dollars"].sum())
        full_total = float(g["total_pnl_dollars"].sum())
        c2_contrib = full_total - c1_total
        n = len(g)
        print(f"\n[{grp}] n={n:,}")
        print(f"  C1 only:  ${c1_total:+,.0f} (${c1_total/n:+.2f}/tr)")
        print(f"  1+1 fail-mgmt: ${full_total:+,.0f} "
              f"(${full_total/n:+.2f}/tr)")
        print(f"  C2 contribution: ${c2_contrib:+,.0f}")
        for yr in (2024, 2025):
            sg = g[g["year"] == yr]
            if len(sg) == 0: continue
            c1_y = float(sg["c1_only_pnl_dollars"].sum())
            full_y = float(sg["total_pnl_dollars"].sum())
            print(f"  {yr}: C1 ${c1_y:+,.0f}, 1+1 ${full_y:+,.0f}, "
                  f"C2 ${full_y - c1_y:+,.0f}")

    # ----- Per-bucket detail -----
    print(f"\n{'='*78}")
    print(f"PER-BUCKET — 1-ctr vs 1+1 fail-mgmt")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}]")
        print(f"  {'bucket':<22} {'n':>5} {'C2%':>5} "
              f"{'1ctr_$/tr':>10} {'1+1_$/tr':>10} {'C2_$/tr':>10}  "
              f"{'1ctr_total':>13} {'1+1_total':>13}")
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

    # ----- Comparison vs unfiltered v-recovery -----
    prior = OUT / "vshape_recross_addon.parquet"
    if prior.exists():
        pdf = pd.read_parquet(prior)
        print(f"\n{'='*78}")
        print(f"COMPARISON: failure mgmt vs unfiltered v-recovery (+$72K design)")
        print(f"{'='*78}")
        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            g = df[df["group"] == grp]
            pg = pdf[pdf["group"] == grp]
            if len(g) == 0 or len(pg) == 0: continue
            print(f"\n[{grp}]")
            print(f"  Unfiltered v-recovery (no fail mgmt): "
                  f"${pg['total_pnl_dollars'].sum():+,.0f}")
            print(f"  WITH failure management:               "
                  f"${g['total_pnl_dollars'].sum():+,.0f}")
            print(f"  Delta: "
                  f"${g['total_pnl_dollars'].sum() - pg['total_pnl_dollars'].sum():+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
