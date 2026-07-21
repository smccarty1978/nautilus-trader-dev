"""V-shape recovery add-on with tighter cat_SL per group.

Difference from analyze_vshape_recross_addon.py:
  Both C1 and C2 use cat_SL_per_group (NOT prior-level SL).
  Each contract's SL is at its OWN entry +/- cat_sl_pts.

Cat_SL grid (from prior MAE-protection analysis, 90% of TP-fillers):
  A_25pt:    cat_SL = 14.0 pts
  B_14_15pt: cat_SL = 11.0 pts
  C_10_11pt: cat_SL =  9.5 pts

Same v-recovery trigger: trade dipped below breach level, then 1m bar
closes back above, add C2 at next 1s bar.

Both contracts run with cat_SL and original PT (next-level - 2.5).
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

# Per-group cat_SL (90% protection of TP-fillers)
CAT_SL_PER_GROUP = {
    "A_25pt":    14.0,
    "B_14_15pt": 11.0,
    "C_10_11pt":  9.5,
}


def sim_recross_with_catsl(
    entry_idx, di, entry_px, breach_level, target_px, cat_sl_pts,
    eod_idx,
    opens, highs, lows, closes, ts_seconds,
):
    """Like sim_recross but using cat_sl_pts per contract (NOT
    prior-level SL). Each contract's SL = its_entry +/- cat_sl_pts."""
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

    # C1 SL price
    if di == 1:
        c1_sl_px = entry_px - cat_sl_pts
    else:
        c1_sl_px = entry_px + cat_sl_pts

    c1_open = True
    c1_outcome = None; c1_exit_px = None; c1_exit_idx = None
    c2_open = False
    c2_entry_idx = -1; c2_entry_px = None; c2_sl_px = None
    c2_outcome = None; c2_exit_px = None; c2_exit_idx = None
    has_dipped = False
    recross_armed = False; recross_at = -1

    for s in range(nbars):
        o = sli_o[s]; h = sli_h[s]; l = sli_l[s]; c = sli_c[s]
        sec = sli_sec[s]

        # Detect dip below breach
        if not has_dipped:
            if di == 1 and l < breach_level:
                has_dipped = True
            elif di == -1 and h > breach_level:
                has_dipped = True

        # 1m close re-cross
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
            if di == 1:
                c2_sl_px = c2_entry_px - cat_sl_pts
            else:
                c2_sl_px = c2_entry_px + cat_sl_pts
            c2_open = True

        # C1 exit checks
        if c1_open:
            if di == 1:
                sl_hit = (l <= c1_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= c1_sl_px)
                tgt_hit = (l <= target_px)
            if sl_hit:
                c1_outcome = "loss"
                c1_exit_px = float(c1_sl_px); c1_exit_idx = s
                c1_open = False
            elif tgt_hit:
                c1_outcome = "win"
                c1_exit_px = float(target_px); c1_exit_idx = s
                c1_open = False

        # C2 exit checks
        if c2_open:
            if di == 1:
                sl_hit = (l <= c2_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= c2_sl_px)
                tgt_hit = (l <= target_px)
            if sl_hit:
                c2_outcome = "loss"
                c2_exit_px = float(c2_sl_px); c2_exit_idx = s
                c2_open = False
            elif tgt_hit:
                c2_outcome = "win"
                c2_exit_px = float(target_px); c2_exit_idx = s
                c2_open = False

        # Break logic
        if not c1_open and not c2_open and c2_entry_idx >= 0:
            break
        if not c1_open and not recross_armed:
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


def main():
    t0 = time.time()
    all_trades = []
    arrays = {}
    for year in (2024, 2025):
        trs, o, h, l, c, sec = harvest(year)
        arrays[year] = (o, h, l, c, sec)
        all_trades.extend(trs)
    print(f"\nTotal RTH trades: {len(all_trades):,}\n")

    print("Running re-cross add-on with tight cat_SL...")
    rows = []
    for t in all_trades:
        o, h, l, c, sec = arrays[t["year"]]
        cat = CAT_SL_PER_GROUP.get(t["group"])
        if cat is None: continue
        r = sim_recross_with_catsl(
            t["entry_1s_idx"], t["direction"], t["entry_px"],
            t["breach_level"], t["target"], cat,
            t["eod_idx"], o, h, l, c, sec)
        if r is None: continue
        rows.append({**t, **r, "cat_sl_pts": cat})
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "vshape_recross_catsl.parquet")
    print(f"Saved {len(df):,} rows.")

    # ----- Per group: re-cross add-on rate by bucket -----
    print(f"\n{'='*78}")
    print(f"RE-CROSS ADD-ON RATE per bucket (with cat_SL)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        cat = CAT_SL_PER_GROUP[grp]
        n = len(g); n_add = int(g["c2_added"].sum())
        print(f"\n[{grp}] cat_SL={cat} pts  n={n:,}, "
              f"C2 added={n_add:,} ({100*n_add/n:.1f}%)")
        for bk in ("win_clean", "win_vshape",
                   "loss_runthenbreak", "loss_quick"):
            sub = g[g["bucket"] == bk]
            if len(sub) == 0: continue
            ad = int(sub["c2_added"].sum())
            print(f"  {bk:<22} n={len(sub):>5,} C2_added={ad:>5,} "
                  f"({100*ad/len(sub):>5.1f}%)")

    # ----- PnL: 1-ctr vs 1+1 -----
    print(f"\n{'='*78}")
    print(f"PnL: 1-ctr (C1 only, cat_SL) vs 1+1 with re-cross add-on")
    print(f"vs comparison row from prior run with prior_level SL")
    print(f"{'='*78}")

    # Load prior data for comparison
    prior_path = OUT / "vshape_recross_addon.parquet"
    prior_df = (pd.read_parquet(prior_path)
                if prior_path.exists() else None)

    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        c1_total = float(g["c1_only_pnl_dollars"].sum())
        full_total = float(g["total_pnl_dollars"].sum())
        c2_contrib = full_total - c1_total
        n = len(g)
        print(f"\n[{grp}] cat_SL={CAT_SL_PER_GROUP[grp]} pts  n={n:,}")
        print(f"  CAT_SL version:")
        print(f"    1-ctr (C1 only): ${c1_total:+,.0f}  "
              f"(${c1_total/n:+.2f}/tr)")
        print(f"    1+1 with re-cross: ${full_total:+,.0f}  "
              f"(${full_total/n:+.2f}/tr)")
        print(f"    C2 contribution: ${c2_contrib:+,.0f}")
        if prior_df is not None:
            pg = prior_df[prior_df["group"] == grp]
            if len(pg):
                p_c1 = float(pg["c1_only_pnl_dollars"].sum())
                p_full = float(pg["total_pnl_dollars"].sum())
                print(f"  PRIOR (prior_level SL) version:")
                print(f"    1-ctr (C1 only): ${p_c1:+,.0f}  "
                      f"(${p_c1/len(pg):+.2f}/tr)")
                print(f"    1+1 with re-cross: ${p_full:+,.0f}  "
                      f"(${p_full/len(pg):+.2f}/tr)")
                print(f"  DELTA (cat_SL vs prior_SL):")
                print(f"    1-ctr: ${c1_total - p_c1:+,.0f}")
                print(f"    1+1: ${full_total - p_full:+,.0f}")

        # Per year
        for yr in (2024, 2025):
            sg = g[g["year"] == yr]
            if len(sg) == 0: continue
            c1_y = float(sg["c1_only_pnl_dollars"].sum())
            full_y = float(sg["total_pnl_dollars"].sum())
            print(f"  {yr}: 1-ctr ${c1_y:+,.0f}, 1+1 ${full_y:+,.0f}, "
                  f"C2 ${full_y-c1_y:+,.0f}")

    # ----- Per-bucket detail -----
    print(f"\n{'='*78}")
    print(f"PER-BUCKET — 1-ctr vs 1+1 add-on (cat_SL)")
    print(f"{'='*78}")
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df[df["group"] == grp]
        if len(g) == 0: continue
        print(f"\n[{grp}] cat_SL={CAT_SL_PER_GROUP[grp]} pts")
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

    # ----- C2 outcome detail -----
    print(f"\n{'='*78}")
    print(f"C2 OUTCOMES (only C2 trades, with cat_SL)")
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
              f"eod={eod:,})  per-C2 ${c2_total/n:+.2f}")
        for yr in (2024, 2025):
            sg = g[g["year"] == yr]
            if len(sg) == 0: continue
            sw = int((sg["c2_outcome"] == "win").sum())
            print(f"  {yr}: n={len(sg):,} WR={100*sw/len(sg):.1f}% "
                  f"C2 ${(sg['c2_pnl_pts']*NQ_DOLLAR_PER_PT).sum():+,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
