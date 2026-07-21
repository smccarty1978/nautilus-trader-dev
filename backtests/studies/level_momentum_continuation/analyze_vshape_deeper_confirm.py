"""V-recovery add-on with DEEPER CONFIRMATION (post-re-cross wait + threshold).

DESIGN
------
C1 (unchanged):
  - 1 contract initial entry
  - prior_level SL
  - full PT (next-level - 2.5)

C2 (NEW: post-re-cross deeper confirmation):
  Step 1: Detect candidate
    - Trade dipped below breach
    - 1m bar closes back above breach
    - max_MAE since entry >= 3 pts
  Step 2: WAIT T seconds after re-cross 1m close
  Step 3: At T_rc + T, check 1s close >= breach + threshold
    - If yes, add C2 at T_rc + T + 1 (next 1s bar open)
    - Else skip
  Step 4: C2 runs with prior_level SL and full PT

Sweep:
  T (wait seconds) = [30, 45, 60]
  threshold (above breach, pts) = [2, 3, 4, 5]

Compare to +$72K baseline (no wait, no threshold).
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

MAE_MIN = 3.0
WAIT_GRID = [30, 45, 60]
THRESHOLD_GRID = [2.0, 3.0, 4.0, 5.0]


def sim_deeper(
    entry_idx, di, entry_px, breach_level, target_px, prior_sl_px,
    eod_idx,
    opens, highs, lows, closes, ts_seconds,
    wait_secs, threshold,
    mae_min=MAE_MIN,
):
    """C1 with prior_SL + full PT.
    C2 added at T_rc + wait + 1 if price meets threshold above breach.
    """
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
    c2_entry_idx = -1; c2_entry_px = None
    c2_outcome = None; c2_exit_px = None; c2_exit_idx = None

    # Trade state
    has_dipped = False
    c1_running_mae = 0.0
    recross_attempted = False
    recross_at = -1
    confirmation_bar = -1   # bar at which to apply threshold check
    c2_pending_entry = -1

    for s in range(nbars):
        o = sli_o[s]; h = sli_h[s]; l = sli_l[s]; c = sli_c[s]
        sec = sli_sec[s]

        # Update running MAE
        if di == 1:
            cur_mae = entry_px - l
        else:
            cur_mae = h - entry_px
        if cur_mae > c1_running_mae:
            c1_running_mae = cur_mae

        # Detect dip below breach
        if not has_dipped:
            if di == 1 and l < breach_level: has_dipped = True
            elif di == -1 and h > breach_level: has_dipped = True

        # 1m close: re-cross detection (only first one)
        if (not recross_attempted and has_dipped and c1_open
                and sec == 0):
            crossed = ((di == 1 and c > breach_level) or
                       (di == -1 and c < breach_level))
            if crossed and c1_running_mae >= mae_min:
                recross_at = s
                confirmation_bar = s + wait_secs
                recross_attempted = True

        # At confirmation bar: apply threshold check
        if (confirmation_bar >= 0 and s == confirmation_bar
                and c1_open and not c2_open and c2_entry_idx < 0):
            if di == 1:
                passes = (c >= breach_level + threshold)
            else:
                passes = (c <= breach_level - threshold)
            if passes:
                c2_pending_entry = s + 1
            confirmation_bar = -1   # done

        # Enter C2 at scheduled bar
        if (c2_pending_entry >= 0 and not c2_open and c2_entry_idx < 0
                and s == c2_pending_entry):
            c2_entry_idx = s
            c2_entry_px = float(o)
            c2_open = True

        # C1 exit checks (conservative SL beats PT)
        if c1_open:
            if di == 1:
                sl_hit = (l <= prior_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= prior_sl_px)
                tgt_hit = (l <= target_px)
            if sl_hit:
                c1_open = False
                c1_outcome = "loss"
                c1_exit_px = float(prior_sl_px); c1_exit_idx = s
            elif tgt_hit:
                c1_open = False
                c1_outcome = "win"
                c1_exit_px = float(target_px); c1_exit_idx = s

        # C2 exit checks
        if c2_open:
            if di == 1:
                sl_hit = (l <= prior_sl_px)
                tgt_hit = (h >= target_px)
            else:
                sl_hit = (h >= prior_sl_px)
                tgt_hit = (l <= target_px)
            if sl_hit:
                c2_open = False
                c2_outcome = "loss"
                c2_exit_px = float(prior_sl_px); c2_exit_idx = s
            elif tgt_hit:
                c2_open = False
                c2_outcome = "win"
                c2_exit_px = float(target_px); c2_exit_idx = s

        if not c1_open and not c2_open and c2_entry_idx >= 0:
            break
        if (not c1_open and not recross_attempted):
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
        "c1_outcome": c1_outcome, "c1_pnl_pts": float(c1_pnl),
        "c2_added": c2_entry_idx >= 0,
        "c2_outcome": c2_outcome,
        "c2_pnl_pts": float(c2_pnl),
        "c2_entry_px": (float(c2_entry_px)
                        if c2_entry_px else None),
        "recross_at_local": recross_at,
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

    summary_rows = []
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        gt = [t for t in all_trades if t["group"] == grp]
        if not gt: continue
        print(f"\n{'='*78}\n[{grp}] n={len(gt):,}")
        print(f"{'='*78}")

        for wait_s in WAIT_GRID:
            for threshold in THRESHOLD_GRID:
                rows = []
                for t in gt:
                    o, h, l, c, sec = arrays[t["year"]]
                    r = sim_deeper(
                        t["entry_1s_idx"], t["direction"],
                        t["entry_px"], t["breach_level"],
                        t["target"], t["prior_sl"], t["eod_idx"],
                        o, h, l, c, sec,
                        wait_secs=wait_s, threshold=threshold)
                    if r is None: continue
                    rows.append({**t, **r})
                df = pd.DataFrame(rows)
                if len(df) == 0: continue
                n = len(df)
                n_add = int(df["c2_added"].sum())
                c1_total = float(df["c1_only_pnl_dollars"].sum())
                full_total = float(df["total_pnl_dollars"].sum())
                c2_contrib = full_total - c1_total
                y2024 = float(
                    df[df["year"]==2024]["total_pnl_dollars"].sum())
                y2025 = float(
                    df[df["year"]==2025]["total_pnl_dollars"].sum())

                # Per-bucket
                row = {
                    "group": grp, "wait_s": wait_s,
                    "threshold": threshold, "n": n,
                    "c2_added": n_add, "c2_pct": 100*n_add/n,
                    "c1_total": c1_total, "full_total": full_total,
                    "c2_contrib": c2_contrib,
                    "y2024_total": y2024, "y2025_total": y2025,
                }
                # Per bucket
                for bk in ("win_clean", "win_vshape",
                           "loss_runthenbreak", "loss_quick"):
                    sub = df[df["bucket"] == bk]
                    if len(sub) == 0: continue
                    n_bk = len(sub)
                    n_bk_c2 = int(sub["c2_added"].sum())
                    c2_bk_total = float(
                        (sub["c2_pnl_pts"] * NQ_DOLLAR_PER_PT).sum())
                    row[f"{bk}_n"] = n_bk
                    row[f"{bk}_c2_n"] = n_bk_c2
                    row[f"{bk}_c2_pct"] = 100 * n_bk_c2 / n_bk
                    row[f"{bk}_c2_total"] = c2_bk_total
                summary_rows.append(row)

                tag = f"wait={wait_s:>2}s thr=L+{threshold:.0f}"
                print(f"  {tag:<25}  C2_add={n_add:>4,} ({100*n_add/n:>4.1f}%)  "
                      f"total ${full_total:+,.0f}  "
                      f"C2 contrib ${c2_contrib:+,.0f}  "
                      f"(2024 ${y2024:+,.0f} / 2025 ${y2025:+,.0f})")

    pd.DataFrame(summary_rows).to_csv(
        OUT / "vshape_deeper_confirm.csv", index=False)

    # ---- Best cell per group ----
    print(f"\n{'='*78}")
    print(f"BEST CELL PER GROUP (positive in BOTH years)")
    print(f"{'='*78}")
    df_s = pd.DataFrame(summary_rows)
    for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
        g = df_s[df_s["group"] == grp]
        if g.empty: continue
        passers = g[(g["y2024_total"] > 0) & (g["y2025_total"] > 0)]
        print(f"\n[{grp}]")
        if len(passers) == 0:
            best = g.nlargest(1, "full_total").iloc[0]
            print(f"  No cells positive both years.")
            print(f"  Best by total: wait={int(best['wait_s'])}s "
                  f"thr=L+{best['threshold']:.0f}  "
                  f"total ${best['full_total']:+,.0f}  "
                  f"(2024 ${best['y2024_total']:+,.0f} / "
                  f"2025 ${best['y2025_total']:+,.0f})")
        else:
            best = passers.nlargest(1, "full_total").iloc[0]
            print(f"  {len(passers)}/{len(g)} cells positive both years")
            print(f"  Best: wait={int(best['wait_s'])}s "
                  f"thr=L+{best['threshold']:.0f}  "
                  f"total ${best['full_total']:+,.0f}  "
                  f"(2024 ${best['y2024_total']:+,.0f} / "
                  f"2025 ${best['y2025_total']:+,.0f})")
            for bk in ("win_vshape", "loss_runthenbreak"):
                pct = best.get(f"{bk}_c2_pct", 0)
                ttl = best.get(f"{bk}_c2_total", 0)
                print(f"    {bk}: C2_pct={pct:.1f}%  "
                      f"C2_total ${ttl:+,.0f}")

    # ---- Comparison to +$72K baseline ----
    prior = OUT / "vshape_recross_addon.parquet"
    if prior.exists():
        pdf = pd.read_parquet(prior)
        print(f"\n{'='*78}")
        print(f"vs UNFILTERED v-recovery baseline (+$72K design)")
        print(f"{'='*78}")
        for grp in ("A_25pt", "B_14_15pt", "C_10_11pt"):
            pg = pdf[pdf["group"] == grp]
            base_total = float(pg["total_pnl_dollars"].sum())
            print(f"\n[{grp}] baseline ${base_total:+,.0f}")
            g = df_s[df_s["group"] == grp]
            best = g.nlargest(1, "full_total").iloc[0]
            print(f"  best deeper-confirm: wait={int(best['wait_s'])}s "
                  f"thr=L+{best['threshold']:.0f}  "
                  f"total ${best['full_total']:+,.0f}  "
                  f"(Δ ${best['full_total']-base_total:+,.0f})")

    print(f"\n[done] runtime: {time.time()-t0:.1f}s")
    print(f"saved: {OUT / 'vshape_deeper_confirm.csv'}")


if __name__ == "__main__":
    main()
