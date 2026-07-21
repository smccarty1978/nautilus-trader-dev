"""Analyze stop-loss placement for the Level Momentum study.

Two analyses:

A) MAE distribution for WINNERS by group.
   For trades that hit target, what was the worst adverse excursion
   before target was reached? Tells us how tight a stop could be
   without killing the win.

B) Alt-stop sweep.
   For each candidate stop distance D in {2.5, 5, 7.5, 10, 12.5,
   15, 17.5, 20, 25} pts, re-simulate the existing trade population:
     - If observed MAE >= D, the alt stop triggers first.
       Original outcome (win/loss/timeout) is overridden -> loss at D.
     - If MAE < D, the alt stop never triggers; original outcome
       and original PnL stand.
   Reports new WR, mean PnL, mean loss, total PnL by pair x session.

Why this works only for TIGHTER stops:
  Original stop = "one prior in sequence" (typically 15-30 pts from
  entry). If alt_D <= original distance, the alt stop is always
  reached before the original stop. We can derive new outcomes from
  observed MAE without re-simulating bars. This breaks if alt_D >
  original distance (we'd need to know what happened past the original
  stop, which the recorded trades don't tell us).

Usage:
    python studies/level_momentum_continuation/analyze_stops.py
"""
from __future__ import annotations

import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)


SOURCE = Path(
    "studies/level_momentum_continuation/results_nq_2025/"
    "trades_unfiltered.csv")
OUT = Path(
    "studies/level_momentum_continuation/results_nq_2025")

ALT_STOP_PTS = [2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0, 25.0]
COMMISSION_PTS = 0.0  # no costs assumed in this analysis (set later)


# ---------------- A: MAE distribution for winners ----------------

def mae_distribution_winners(trades: pd.DataFrame,
                                     group_cols: list[str]) -> pd.DataFrame:
    wins = trades[trades["outcome"] == "win"].copy()
    out = []
    for keys, g in wins.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        n = len(g)
        mae = g["mae_pts"].values
        row = dict(zip(group_cols, keys))
        row.update({
            "n_winners": n,
            "mae_p50": float(np.percentile(mae, 50)),
            "mae_p75": float(np.percentile(mae, 75)),
            "mae_p90": float(np.percentile(mae, 90)),
            "mae_p95": float(np.percentile(mae, 95)),
            "mae_p99": float(np.percentile(mae, 99)),
            "mae_max": float(mae.max()),
            "mae_mean": float(mae.mean()),
        })
        # % of winners that exceeded each candidate stop
        for D in ALT_STOP_PTS:
            row[f"%winners_killed_by_{D}pt"] = (
                float((mae >= D).mean()))
        out.append(row)
    return pd.DataFrame(out).sort_values(
        group_cols + ["n_winners"], ascending=[True] * len(group_cols)
        + [False])


# ---------------- B: alt-stop sweep ----------------

def resim_with_alt_stop(trades: pd.DataFrame,
                                alt_stop_pts: float) -> pd.DataFrame:
    """Apply tighter alt-stop. Returns new outcome+pnl per trade."""
    out = trades.copy()
    out["alt_stop_pts"] = alt_stop_pts
    triggered = out["mae_pts"] >= alt_stop_pts
    out["new_outcome"] = np.where(
        triggered, "loss", out["outcome"])
    out["new_pnl_pts"] = np.where(
        triggered, -alt_stop_pts, out["pnl_pts"])
    return out


def stats_block(trades: pd.DataFrame, pnl_col: str,
                    outcome_col: str) -> dict:
    n = len(trades)
    if n == 0: return {"n": 0}
    pnl = trades[pnl_col]
    win_mask = trades[outcome_col] == "win"
    loss_mask = trades[outcome_col] == "loss"
    return {
        "n": n,
        "win_rate": float(win_mask.mean()),
        "loss_rate": float(loss_mask.mean()),
        "mean_pnl_pts": float(pnl.mean()),
        "median_pnl_pts": float(pnl.median()),
        "total_pnl_pts": float(pnl.sum()),
        "mean_win_pts": (float(pnl[win_mask].mean())
                              if win_mask.any() else float("nan")),
        "mean_loss_pts": (float(pnl[loss_mask].mean())
                                if loss_mask.any() else float("nan")),
    }


def sweep_by_group(trades: pd.DataFrame,
                          group_cols: list[str]) -> pd.DataFrame:
    """For each group, compute baseline stats + each alt stop's stats."""
    rows = []
    for keys, g in trades.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        # Baseline (original)
        base = stats_block(g, "pnl_pts", "outcome")
        row = dict(zip(group_cols, keys))
        row["alt_stop_pts"] = "ORIG"
        row.update(base)
        rows.append(row)
        # Each alt stop
        for D in ALT_STOP_PTS:
            sg = resim_with_alt_stop(g, D)
            s = stats_block(sg, "new_pnl_pts", "new_outcome")
            row = dict(zip(group_cols, keys))
            row["alt_stop_pts"] = D
            row.update(s)
            rows.append(row)
    df = pd.DataFrame(rows)
    return df


def best_stop_per_group(sweep: pd.DataFrame,
                                group_cols: list[str]) -> pd.DataFrame:
    """For each group, the alt_stop that maximizes mean_pnl_pts
    (excluding ORIG)."""
    sw = sweep[sweep["alt_stop_pts"] != "ORIG"].copy()
    out = []
    for keys, g in sw.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        # Pick row with highest mean_pnl_pts
        best = g.loc[g["mean_pnl_pts"].idxmax()]
        # Original stat for comparison
        orig = sweep[(sweep["alt_stop_pts"] == "ORIG")]
        for k, v in zip(group_cols, keys):
            orig = orig[orig[k] == v]
        if len(orig):
            orig_pnl = float(orig["mean_pnl_pts"].iloc[0])
            orig_wr = float(orig["win_rate"].iloc[0])
        else:
            orig_pnl = float("nan"); orig_wr = float("nan")
        row = dict(zip(group_cols, keys))
        row.update({
            "n": int(best["n"]),
            "best_stop_pts": float(best["alt_stop_pts"]),
            "best_mean_pnl": float(best["mean_pnl_pts"]),
            "best_win_rate": float(best["win_rate"]),
            "orig_mean_pnl": orig_pnl,
            "orig_win_rate": orig_wr,
            "improvement_pnl": float(best["mean_pnl_pts"]) - orig_pnl,
        })
        out.append(row)
    return pd.DataFrame(out).sort_values(
        "improvement_pnl", ascending=False)


# ---------------- Reporting helpers ----------------

def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:+.{dp}f}"


def write_report(trades, mae_pair, mae_pair_session,
                       sweep_overall, sweep_pair_session,
                       best_pair_session):
    L = []
    L.append("# Stop-Loss Analysis — Level Momentum Continuation\n")
    L.append(f"Source: `{SOURCE}` ({len(trades):,} trades)\n")
    L.append("## Method\n")
    L.append(
        "**Part A** — MAE distribution among WINNERS. For each "
        "(pair, session), what was the worst drawdown winners "
        "endured before reaching target? % killed by each stop "
        "candidate is `count(MAE >= stop) / n_winners`.\n\n"
        "**Part B** — Alt-stop sweep on the existing trade "
        "population. For each candidate distance D, re-simulate: "
        "if observed MAE >= D, alt stop triggers first -> loss at "
        "-D pts (regardless of original outcome). Otherwise, "
        "original outcome and PnL stand. This is rigorous only "
        "for tightening (D <= original stop distance), which holds "
        "here since original stops are 15-30 pts and alt range is "
        "2.5-25 pts.\n")

    L.append("## Part A: MAE distribution for winners\n")
    L.append("### By pair\n")
    cols_pct = ["%winners_killed_by_2.5pt",
                  "%winners_killed_by_5.0pt",
                  "%winners_killed_by_10.0pt",
                  "%winners_killed_by_15.0pt",
                  "%winners_killed_by_20.0pt"]
    L.append("| Pair | n_win | MAE p50 | p75 | p90 | p95 | max | "
             "%kill@2.5 | %kill@5 | %kill@10 | %kill@15 | %kill@20 |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in mae_pair.iterrows():
        L.append(
            f"| {r['level_pair']} | {int(r['n_winners']):,} | "
            f"{r['mae_p50']:.2f} | {r['mae_p75']:.2f} | "
            f"{r['mae_p90']:.2f} | {r['mae_p95']:.2f} | "
            f"{r['mae_max']:.2f} | "
            + " | ".join(fmt_p(r[c]) for c in cols_pct) + " |")
    L.append("")

    L.append("### By pair × session\n")
    L.append("| Pair | Session | n_win | MAE p50 | p75 | p90 | p95 | "
             "%kill@5 | %kill@10 | %kill@15 |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in mae_pair_session.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n_winners']):,} | {r['mae_p50']:.2f} | "
            f"{r['mae_p75']:.2f} | {r['mae_p90']:.2f} | "
            f"{r['mae_p95']:.2f} | "
            f"{fmt_p(r['%winners_killed_by_5.0pt'])} | "
            f"{fmt_p(r['%winners_killed_by_10.0pt'])} | "
            f"{fmt_p(r['%winners_killed_by_15.0pt'])} |")
    L.append("")

    L.append("## Part B: Alt-stop sweep — overall (all trades)\n")
    L.append("| Stop pts | n | WR | LossR | Mean PnL | Median PnL | "
             "Total PnL | Mean Win | Mean Loss |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in sweep_overall.iterrows():
        L.append(
            f"| {r['alt_stop_pts']} | {int(r['n']):,} | "
            f"{fmt_p(r['win_rate'])} | "
            f"{fmt_p(r['loss_rate'])} | "
            f"{fmt_f(r['mean_pnl_pts'], 3)} | "
            f"{fmt_f(r['median_pnl_pts'], 2)} | "
            f"{fmt_f(r['total_pnl_pts'], 0)} | "
            f"{fmt_f(r['mean_win_pts'], 2)} | "
            f"{fmt_f(r['mean_loss_pts'], 2)} |")
    L.append("")

    L.append("## Part B: Best alt-stop per (pair × session)\n")
    L.append("Sorted by improvement vs original.\n")
    L.append("| Pair | Session | n | Best stop | Best PnL | "
             "Best WR | Orig PnL | Orig WR | Improvement |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in best_pair_session.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | {r['best_stop_pts']:.1f} pt | "
            f"{fmt_f(r['best_mean_pnl'], 3)} | "
            f"{fmt_p(r['best_win_rate'])} | "
            f"{fmt_f(r['orig_mean_pnl'], 3)} | "
            f"{fmt_p(r['orig_win_rate'])} | "
            f"{fmt_f(r['improvement_pnl'], 3)} |")
    L.append("")

    L.append("## Note on what this can / cannot tell you\n")
    L.append(
        "- Tighter stops are accurately re-simulated from observed "
        "MAE.\n"
        "- We cannot evaluate WIDER stops than the original (e.g. "
        "stops >25 pts) because the recorded trades stopped at "
        "the original stop and we don't know what would have "
        "happened past it.\n"
        "- Alt stops sweep does NOT include commission. At ~$5 "
        "round-trip on NQ (=0.25 pts), break-even shifts by ~0.25 "
        "pts/trade — not material at the magnitudes shown but "
        "would matter if the best-stop mean PnL is small.\n"
        "- The 'best' stop is chosen by mean PnL on this single "
        "year. No OOS validation.\n")

    p = OUT / "report_stops.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    print(f"Loading {SOURCE}...")
    trades = pd.read_csv(SOURCE)
    print(f"  {len(trades):,} trades")
    n_win = int((trades["outcome"] == "win").sum())
    print(f"  winners: {n_win:,}")

    print("\n[Part A] MAE distribution for winners by pair...")
    mae_pair = mae_distribution_winners(trades, ["level_pair"])
    mae_pair.to_csv(OUT / "winner_mae_by_pair.csv", index=False)
    print("  by pair × session...")
    mae_ps = mae_distribution_winners(
        trades, ["level_pair", "entry_session"])
    mae_ps.to_csv(OUT / "winner_mae_by_pair_session.csv",
                       index=False)

    print("\n[Part B] Alt-stop sweep — overall...")
    sweep_ovr = pd.DataFrame()
    rows = []
    base = stats_block(trades, "pnl_pts", "outcome")
    base_row = {"alt_stop_pts": "ORIG", **base}
    rows.append(base_row)
    for D in ALT_STOP_PTS:
        sg = resim_with_alt_stop(trades, D)
        rows.append({"alt_stop_pts": D,
                          **stats_block(sg, "new_pnl_pts",
                                              "new_outcome")})
    sweep_ovr = pd.DataFrame(rows)
    sweep_ovr.to_csv(OUT / "alt_stop_sweep_overall.csv",
                            index=False)

    print("  by pair × session...")
    sweep_ps = sweep_by_group(
        trades, ["level_pair", "entry_session"])
    sweep_ps.to_csv(OUT / "alt_stop_sweep_pair_session.csv",
                           index=False)

    print("  best stop per (pair × session)...")
    best_ps = best_stop_per_group(
        sweep_ps, ["level_pair", "entry_session"])
    best_ps.to_csv(OUT / "best_alt_stop_pair_session.csv",
                          index=False)

    print("\nWriting report...")
    rp = write_report(trades, mae_pair, mae_ps,
                            sweep_ovr, sweep_ps, best_ps)
    print(f"Report: {rp}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
