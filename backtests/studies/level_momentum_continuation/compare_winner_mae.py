"""Side-by-side comparison: winner MAE distribution
   ALL winners vs FIRST-BAR-CONFIRMED winners.

Tests whether the first-bar confirm filter selects 'cleaner'
winners — i.e. winners with tighter MAE distribution.

Key column: p95 MAE (the threshold that preserves 95% of winners).

Source datasets:
  - winner_mae_by_pair_session.csv         (ALL winners — earlier)
  - confirmed_winner_mae_pair_session.csv  (first-bar-confirmed
                                            winners — latest)
"""
from __future__ import annotations

import os, sys
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

OUT = Path(
    "studies/level_momentum_continuation/results_nq_2025")
ALL_FILE = OUT / "winner_mae_by_pair_session.csv"
CONF_FILE = OUT / "confirmed_winner_mae_pair_session.csv"


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:+.1f}%"


def main():
    print(f"Loading {ALL_FILE}...")
    all_w = pd.read_csv(ALL_FILE)
    print(f"  {len(all_w)} cells")
    print(f"Loading {CONF_FILE}...")
    conf_w = pd.read_csv(CONF_FILE)
    print(f"  {len(conf_w)} cells")

    # Standardize column names. ALL file uses
    # mae_p50/p75/p90/p95/p99 + n_winners.
    # CONFIRMED file uses mae_p50/p75/p90/p95/p99 + n_trades.
    all_cols = ["level_pair", "entry_session", "n_winners",
                  "mae_p50", "mae_p75", "mae_p90",
                  "mae_p95", "mae_p99", "mae_max", "mae_mean"]
    all_w = all_w.rename(
        columns={"n_winners": "n_all_winners",
                  "mae_p50": "all_p50",
                  "mae_p75": "all_p75",
                  "mae_p90": "all_p90",
                  "mae_p95": "all_p95",
                  "mae_p99": "all_p99",
                  "mae_max": "all_max",
                  "mae_mean": "all_mean"})
    conf_w = conf_w.rename(
        columns={"n_trades": "n_conf_winners",
                  "mae_p50": "conf_p50",
                  "mae_p75": "conf_p75",
                  "mae_p90": "conf_p90",
                  "mae_p95": "conf_p95",
                  "mae_p99": "conf_p99",
                  "mae_max": "conf_max",
                  "mae_mean": "conf_mean"})

    keep_all = ["level_pair", "entry_session", "n_all_winners",
                  "all_p50", "all_p75", "all_p90",
                  "all_p95", "all_p99", "all_max", "all_mean"]
    keep_conf = ["level_pair", "entry_session",
                   "n_conf_winners", "conf_p50", "conf_p75",
                   "conf_p90", "conf_p95", "conf_p99",
                   "conf_max", "conf_mean"]

    merged = all_w[keep_all].merge(
        conf_w[keep_conf], on=["level_pair", "entry_session"],
        how="inner")

    # Reduction in p95 MAE = (all_p95 - conf_p95) / all_p95
    merged["p95_reduction_pts"] = (
        merged["all_p95"] - merged["conf_p95"])
    merged["p95_reduction_pct"] = (
        merged["p95_reduction_pts"] / merged["all_p95"])
    merged["p99_reduction_pts"] = (
        merged["all_p99"] - merged["conf_p99"])
    merged["p99_reduction_pct"] = (
        merged["p99_reduction_pts"] / merged["all_p99"])
    merged["mean_reduction_pts"] = (
        merged["all_mean"] - merged["conf_mean"])

    # Sort by p95 reduction descending (where filter helps most)
    merged = merged.sort_values(
        "p95_reduction_pct", ascending=False)

    # Compute overall (weighted by n_conf_winners)
    total_all_n = int(merged["n_all_winners"].sum())
    total_conf_n = int(merged["n_conf_winners"].sum())

    print(f"\nALL winners total: {total_all_n:,}")
    print(f"Confirmed winners total: {total_conf_n:,} "
          f"({100*total_conf_n/total_all_n:.1f}% of all)")

    # Save merged
    merged.to_csv(OUT / "compare_winner_mae.csv", index=False)

    # Build markdown report
    L = []
    L.append("# Winner MAE Comparison: ALL vs First-Bar-Confirmed\n")
    L.append("Source data:\n")
    L.append(f"- ALL winners: `{ALL_FILE.name}` "
              f"({total_all_n:,} winners)\n")
    L.append(f"- Confirmed winners: `{CONF_FILE.name}` "
              f"({total_conf_n:,} winners, "
              f"{100*total_conf_n/total_all_n:.1f}% of all)\n\n")
    L.append("## Hypothesis test\n")
    L.append(
        "If the first-bar confirm filter selects cleaner winners, "
        "the confirmed winners' MAE distribution should be "
        "TIGHTER (lower p95) than the full population of winners. "
        "If MAE distributions are basically identical, the filter "
        "doesn't reduce drawdown — it only changes who is in the "
        "winning set, not how badly they drew down before "
        "winning.\n")

    L.append("## Headline (overall, weighted)\n")
    # Pool aggregates: weighted means by n
    aw_p50 = (merged["all_p50"] * merged["n_all_winners"]).sum() / total_all_n
    aw_p75 = (merged["all_p75"] * merged["n_all_winners"]).sum() / total_all_n
    aw_p90 = (merged["all_p90"] * merged["n_all_winners"]).sum() / total_all_n
    aw_p95 = (merged["all_p95"] * merged["n_all_winners"]).sum() / total_all_n
    aw_p99 = (merged["all_p99"] * merged["n_all_winners"]).sum() / total_all_n
    cw_p50 = (merged["conf_p50"] * merged["n_conf_winners"]).sum() / total_conf_n
    cw_p75 = (merged["conf_p75"] * merged["n_conf_winners"]).sum() / total_conf_n
    cw_p90 = (merged["conf_p90"] * merged["n_conf_winners"]).sum() / total_conf_n
    cw_p95 = (merged["conf_p95"] * merged["n_conf_winners"]).sum() / total_conf_n
    cw_p99 = (merged["conf_p99"] * merged["n_conf_winners"]).sum() / total_conf_n
    L.append("(Weighted across cells by their winner count)\n")
    L.append("| Metric | ALL winners | Confirmed winners | "
             "Δ (Conf − All) | Δ % |")
    L.append("|---|--:|--:|--:|--:|")
    L.append(f"| p50 MAE | {aw_p50:.2f} | {cw_p50:.2f} | "
              f"{cw_p50-aw_p50:+.2f} | {fmt_p((cw_p50-aw_p50)/aw_p50)} |")
    L.append(f"| p75 MAE | {aw_p75:.2f} | {cw_p75:.2f} | "
              f"{cw_p75-aw_p75:+.2f} | {fmt_p((cw_p75-aw_p75)/aw_p75)} |")
    L.append(f"| p90 MAE | {aw_p90:.2f} | {cw_p90:.2f} | "
              f"{cw_p90-aw_p90:+.2f} | {fmt_p((cw_p90-aw_p90)/aw_p90)} |")
    L.append(f"| **p95 MAE** | **{aw_p95:.2f}** | **{cw_p95:.2f}** "
              f"| **{cw_p95-aw_p95:+.2f}** | "
              f"**{fmt_p((cw_p95-aw_p95)/aw_p95)}** |")
    L.append(f"| p99 MAE | {aw_p99:.2f} | {cw_p99:.2f} | "
              f"{cw_p99-aw_p99:+.2f} | {fmt_p((cw_p99-aw_p99)/aw_p99)} |")
    L.append("")

    L.append("## p95 MAE comparison by pair × session "
              "(sorted by Δ% — biggest reduction first)\n")
    L.append("| Pair | Session | n (all) | n (conf) | "
             "ALL p95 | CONF p95 | Δ pts | Δ % |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for _, r in merged.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n_all_winners']):,} | "
            f"{int(r['n_conf_winners']):,} | "
            f"{r['all_p95']:.2f} | "
            f"{r['conf_p95']:.2f} | "
            f"{r['p95_reduction_pts']:+.2f} | "
            f"{fmt_p(r['p95_reduction_pct'])} |")
    L.append("")

    L.append("## Full distribution comparison by pair × session\n")
    L.append("| Pair | Session | n (all/conf) | Mean | p50 | p75 "
             "| p90 | p95 | p99 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in merged.sort_values(
            ["level_pair", "entry_session"]).iterrows():
        nstr = f"{int(r['n_all_winners']):,}/{int(r['n_conf_winners']):,}"
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{nstr} | "
            f"{r['all_mean']:.2f}/{r['conf_mean']:.2f} | "
            f"{r['all_p50']:.2f}/{r['conf_p50']:.2f} | "
            f"{r['all_p75']:.2f}/{r['conf_p75']:.2f} | "
            f"{r['all_p90']:.2f}/{r['conf_p90']:.2f} | "
            f"{r['all_p95']:.2f}/{r['conf_p95']:.2f} | "
            f"{r['all_p99']:.2f}/{r['conf_p99']:.2f} |")
    L.append("")

    L.append("## Interpretation\n")
    p95_drops_pts = merged["p95_reduction_pts"]
    p95_drops_pct = merged["p95_reduction_pct"]
    n_better = int((p95_drops_pts > 0).sum())
    n_worse = int((p95_drops_pts < 0).sum())
    n_equal = int((p95_drops_pts == 0).sum())
    L.append(f"- {n_better} cells: confirmed winners have TIGHTER "
              "p95 MAE (filter helps)\n")
    L.append(f"- {n_worse} cells: confirmed winners have WIDER "
              "p95 MAE (filter hurts)\n")
    L.append(f"- {n_equal} cells: no change\n")
    L.append(f"- Median reduction in p95 MAE across cells: "
              f"{p95_drops_pts.median():+.2f} pts "
              f"({fmt_p(p95_drops_pct.median())})\n")
    L.append(f"- Mean reduction across cells: "
              f"{p95_drops_pts.mean():+.2f} pts "
              f"({fmt_p(p95_drops_pct.mean())})\n")

    p = OUT / "report_compare_winner_mae.md"
    p.write_text("\n".join(L), encoding="utf-8")
    print(f"\nReport: {p}")


if __name__ == "__main__":
    sys.exit(main())
