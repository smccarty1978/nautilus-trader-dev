"""MAE distribution for trades that:
  1) Had first-bar confirm (first_bar_winner == 1, i.e. first bar
     closed favorably for trade direction), AND
  2) Eventually won the full trade (outcome == "win", i.e. target
     hit before stop within 120 bars).

Reports the FULL-trade MAE percentiles for this subset by:
  - Overall
  - Session (RTH/ETH)
  - Pair
  - Pair × Session

The p99 MAE tells you the worst adverse excursion that 99% of the
"first-bar-confirmed AND eventual winner" trades stayed within. A
stop wider than that preserves 99% of these wins; a tighter stop
sacrifices some.
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


SOURCE = Path(
    "studies/level_momentum_continuation/results_nq_2025/"
    "trades_with_first_bar.csv")
OUT = Path(
    "studies/level_momentum_continuation/results_nq_2025")


def percentiles(series: pd.Series) -> dict:
    if len(series) == 0:
        return {f"p{q}": float("nan")
                for q in (50, 75, 90, 95, 99)}
    return {
        "p50": float(np.percentile(series, 50)),
        "p75": float(np.percentile(series, 75)),
        "p90": float(np.percentile(series, 90)),
        "p95": float(np.percentile(series, 95)),
        "p99": float(np.percentile(series, 99)),
        "max": float(series.max()),
        "mean": float(series.mean()),
    }


def aggregate(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    iter_obj = (df.groupby(group_cols, observed=True)
                  if group_cols else [(("ALL",), df)])
    for keys, g in iter_obj:
        if not isinstance(keys, tuple): keys = (keys,)
        n = len(g)
        pcts = percentiles(g["mae_pts"])
        row = dict(zip(group_cols if group_cols else ["scope"],
                            keys))
        row.update({
            "n_trades": n,
            "mean_pnl_pts": float(g["pnl_pts"].mean()),
            "median_pnl_pts": float(g["pnl_pts"].median()),
            "mae_p50": pcts["p50"],
            "mae_p75": pcts["p75"],
            "mae_p90": pcts["p90"],
            "mae_p95": pcts["p95"],
            "mae_p99": pcts["p99"],
            "mae_max": pcts["max"],
            "mae_mean": pcts["mean"],
        })
        rows.append(row)
    return pd.DataFrame(rows)


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:.{dp}f}"


def write_report(subset, agg_overall, agg_session, agg_pair,
                       agg_pair_session):
    L = []
    L.append("# MAE for First-Bar-Confirmed Winners "
              "— Level Momentum Study\n")
    L.append(f"Source: `{SOURCE}` | filtered subset n={len(subset):,}\n")
    L.append("## Subset definition\n")
    L.append(
        "- `first_bar_winner == 1` (first bar closed favorably for "
        "trade direction)\n"
        "- `outcome == \"win\"` (target hit before stop within 120 "
        "bars)\n\n"
        "MAE = max adverse excursion across the FULL trade "
        "lifetime (entry to target hit), in absolute points.\n\n"
        "**p99 MAE** = the worst drawdown that 99% of these "
        "trades stayed within. A stop wider than this would "
        "preserve >=99% of these wins; tighter would clip some.\n")

    L.append("## Overall (all pairs/sessions combined)\n")
    r = agg_overall.iloc[0]
    L.append(f"- n = {int(r['n_trades']):,}")
    L.append(f"- Mean PnL: {r['mean_pnl_pts']:+.2f} pts | "
              f"Median: {r['median_pnl_pts']:+.2f}")
    L.append(f"- MAE percentiles: p50={r['mae_p50']:.2f}, "
              f"p75={r['mae_p75']:.2f}, p90={r['mae_p90']:.2f}, "
              f"p95={r['mae_p95']:.2f}, "
              f"**p99={r['mae_p99']:.2f}**, "
              f"max={r['mae_max']:.2f}")
    L.append(f"- Mean MAE: {r['mae_mean']:.2f} pts\n")

    L.append("## By session\n")
    L.append("| Session | n | Mean PnL | MAE p50 | p75 | p90 | "
             "p95 | **p99** | max |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in agg_session.iterrows():
        L.append(
            f"| {r['entry_session']} | {int(r['n_trades']):,} | "
            f"{r['mean_pnl_pts']:+.2f} | "
            f"{r['mae_p50']:.2f} | "
            f"{r['mae_p75']:.2f} | "
            f"{r['mae_p90']:.2f} | "
            f"{r['mae_p95']:.2f} | "
            f"**{r['mae_p99']:.2f}** | "
            f"{r['mae_max']:.2f} |")
    L.append("")

    L.append("## By pair\n")
    L.append("| Pair | n | Mean PnL | MAE p50 | p75 | p90 | "
             "p95 | **p99** | max |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in agg_pair.sort_values(
            "mae_p99", ascending=True).iterrows():
        L.append(
            f"| {r['level_pair']} | {int(r['n_trades']):,} | "
            f"{r['mean_pnl_pts']:+.2f} | "
            f"{r['mae_p50']:.2f} | "
            f"{r['mae_p75']:.2f} | "
            f"{r['mae_p90']:.2f} | "
            f"{r['mae_p95']:.2f} | "
            f"**{r['mae_p99']:.2f}** | "
            f"{r['mae_max']:.2f} |")
    L.append("")

    L.append("## By pair × session\n")
    L.append("| Pair | Session | n | Mean PnL | MAE p50 | p75 | "
             "p90 | p95 | **p99** | max |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in agg_pair_session.sort_values(
            ["level_pair", "entry_session"]).iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n_trades']):,} | "
            f"{r['mean_pnl_pts']:+.2f} | "
            f"{r['mae_p50']:.2f} | "
            f"{r['mae_p75']:.2f} | "
            f"{r['mae_p90']:.2f} | "
            f"{r['mae_p95']:.2f} | "
            f"**{r['mae_p99']:.2f}** | "
            f"{r['mae_max']:.2f} |")
    L.append("")

    p = OUT / "report_confirmed_winner_mae.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    print(f"Loading {SOURCE}...")
    trades = pd.read_csv(SOURCE)
    print(f"  total trades: {len(trades):,}")

    fb_pass = trades["first_bar_winner"] == 1
    won = trades["outcome"] == "win"
    subset = trades[fb_pass & won].copy()
    print(f"  first-bar-confirmed: {fb_pass.sum():,}")
    print(f"  ... AND eventual winner: {len(subset):,} "
          f"({100*len(subset)/fb_pass.sum():.1f}% of confirmed)")

    agg_overall = aggregate(subset, [])
    agg_session = aggregate(subset, ["entry_session"])
    agg_pair = aggregate(subset, ["level_pair"])
    agg_ps = aggregate(subset, ["level_pair", "entry_session"])

    agg_overall.to_csv(
        OUT / "confirmed_winner_mae_overall.csv", index=False)
    agg_session.to_csv(
        OUT / "confirmed_winner_mae_session.csv", index=False)
    agg_pair.to_csv(
        OUT / "confirmed_winner_mae_pair.csv", index=False)
    agg_ps.to_csv(
        OUT / "confirmed_winner_mae_pair_session.csv", index=False)

    print("\nWriting report...")
    rp = write_report(subset, agg_overall, agg_session,
                            agg_pair, agg_ps)
    print(f"Report: {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
