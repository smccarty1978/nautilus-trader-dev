"""2-contract TP+5 / BE+1tick simulation with 90%-TP-filler-protection
cat_SL per group.

Cat_SL chosen so that 90% of trades that reach +5.25 MFE actually
reach it (i.e., MAE-before-+5.25 distribution p90 from prior study):
  A_25pt:    cat_SL = 14.0 pts
  B_14_15pt: cat_SL = 11.0 pts
  C_10_11pt: cat_SL =  9.5 pts

Plus the prior best per-group cat_SL (8/6/8) for direct comparison.
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

from studies.level_momentum_continuation.analyze_2contract_tp5_be import (
    sim_2contract, sim_baseline_path, assign_bucket, harvest_trades,
    NQ_DOLLAR_PER_PT,
)

OUT = Path("studies/level_momentum_continuation/results_breakout")

# Pairs: (cat_SL_90pct, cat_SL_prev_best)
GROUP_CATS = {
    "A_25pt":    [("90pct", 14.0), ("prev",  8.0)],
    "B_14_15pt": [("90pct", 11.0), ("prev",  6.0)],
    "C_10_11pt": [("90pct",  9.5), ("prev",  8.0)],
}


def run_cell(trades, year_arrays, cat_pts):
    rows = []
    for t in trades:
        h, l, c = year_arrays[t["year"]]
        r = sim_2contract(
            t["entry_1s_idx"], t["direction"], t["entry_px"],
            t["target"], t["prior_sl"], t["eod_idx"], cat_pts,
            h, l, c)
        if r is None: continue
        rows.append({"year": t["year"], "bucket": t["bucket"],
                     "direction": t["direction"], **r})
    return pd.DataFrame(rows)


def summarize(df, label):
    n = len(df)
    if n == 0: return None
    n_c1tp = int((df["c1_outcome"] == "tp").sum())
    n_c1cat = int((df["c1_outcome"] == "cat_loss").sum())
    n_c2pt = int((df["c2_outcome"] == "win").sum())
    n_c2be = int((df["c2_outcome"] == "be_stop").sum())
    n_c2cat = int((df["c2_outcome"] == "cat_loss").sum())
    n_c2eod = int((df["c2_outcome"] == "eod_flat").sum())
    out = {
        "label": label, "n": n,
        "c1_tp%": 100 * n_c1tp / n,
        "c1_cat%": 100 * n_c1cat / n,
        "c2_pt%": 100 * n_c2pt / n,
        "c2_be%": 100 * n_c2be / n,
        "c2_cat%": 100 * n_c2cat / n,
        "c2_eod%": 100 * n_c2eod / n,
        "$/tr": float(df["total_pnl_dollars"].mean()),
        "total_$": float(df["total_pnl_dollars"].sum()),
    }
    for yr in (2024, 2025):
        sub = df[df["year"] == yr]
        if len(sub):
            out[f"y{yr}_total_$"] = float(sub["total_pnl_dollars"].sum())
            out[f"y{yr}_$/tr"] = float(sub["total_pnl_dollars"].mean())
            out[f"y{yr}_n"] = len(sub)
    for bk in ("win_clean", "win_vshape",
               "loss_runthenbreak", "loss_quick"):
        sub = df[df["bucket"] == bk]
        if len(sub):
            out[f"{bk}_n"] = len(sub)
            out[f"{bk}_$/tr"] = float(sub["total_pnl_dollars"].mean())
            out[f"{bk}_total_$"] = float(sub["total_pnl_dollars"].sum())
            out[f"{bk}_c1tp%"] = float(
                100 * (sub["c1_outcome"] == "tp").mean())
            out[f"{bk}_c2pt%"] = float(
                100 * (sub["c2_outcome"] == "win").mean())
            out[f"{bk}_c2be%"] = float(
                100 * (sub["c2_outcome"] == "be_stop").mean())
            out[f"{bk}_c2cat%"] = float(
                100 * (sub["c2_outcome"] == "cat_loss").mean())
    return out


def main():
    t0 = time.time()
    all_trades = []
    year_arrays = {}
    for year in (2024, 2025):
        trades, h, l, c = harvest_trades(year)
        year_arrays[year] = (h, l, c)
        all_trades.extend(trades)
    print(f"\nTotal RTH trades: {len(all_trades):,}\n")

    summary_rows = []
    for grp, cats in GROUP_CATS.items():
        gt = [t for t in all_trades if t["group"] == grp]
        if not gt: continue
        print(f"\n{'='*78}")
        print(f"[{grp}]  n_trades={len(gt):,}")
        print(f"{'='*78}")
        for tag, cat in cats:
            df = run_cell(gt, year_arrays, cat)
            s = summarize(df, f"{grp}_{tag}_cat{cat}")
            s["group"] = grp; s["cat_sl"] = cat; s["tag"] = tag
            summary_rows.append(s)

            print(f"\n--- {tag} cat_SL={cat} pts ---")
            print(f"  n={s['n']:,}  $/tr={s['$/tr']:+.2f}  "
                  f"total ${s['total_$']:+,.0f}")
            print(f"  2024: ${s.get('y2024_total_$', 0):+,.0f} "
                  f"({s.get('y2024_$/tr', 0):+.2f}/tr, "
                  f"n={int(s.get('y2024_n', 0)):,})")
            print(f"  2025: ${s.get('y2025_total_$', 0):+,.0f} "
                  f"({s.get('y2025_$/tr', 0):+.2f}/tr, "
                  f"n={int(s.get('y2025_n', 0)):,})")
            print(f"  C1: TP={s['c1_tp%']:>4.1f}%  cat={s['c1_cat%']:>4.1f}%")
            print(f"  C2: PT={s['c2_pt%']:>4.1f}%  BE={s['c2_be%']:>4.1f}%  "
                  f"cat={s['c2_cat%']:>4.1f}%  EOD={s['c2_eod%']:>4.1f}%")
            print(f"\n  Per-bucket:")
            print(f"  {'bucket':<22} {'n':>5}  {'$/tr':>9} "
                  f"{'C1_TP%':>7} {'C2_PT%':>7} {'C2_BE%':>7} "
                  f"{'C2_cat%':>8}  {'total_$':>13}")
            for bk in ("win_clean", "win_vshape",
                       "loss_runthenbreak", "loss_quick"):
                n = s.get(f"{bk}_n", 0)
                if not n: continue
                print(f"  {bk:<22} {int(n):>5,}  "
                      f"{s[f'{bk}_$/tr']:>+8.2f}  "
                      f"{s[f'{bk}_c1tp%']:>6.1f}% "
                      f"{s[f'{bk}_c2pt%']:>6.1f}% "
                      f"{s[f'{bk}_c2be%']:>6.1f}% "
                      f"{s[f'{bk}_c2cat%']:>7.1f}%  "
                      f"{s[f'{bk}_total_$']:>+12,.0f}")

    pd.DataFrame(summary_rows).to_csv(
        OUT / "2contract_90pct_sl.csv", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.1f}s")
    print(f"saved: {OUT / '2contract_90pct_sl.csv'}")


if __name__ == "__main__":
    main()
