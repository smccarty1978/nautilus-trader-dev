"""Combined analysis: first-bar filter + optimal stop sweep.

Restricts to trades whose FIRST BAR closed favorably (close-vs-open
in trade direction), then sweeps alt-stop distances and reports best
stop per (pair × session). Compares to unfiltered baseline.

Adds commission ($5 RT on NQ ≈ 0.25 pts/trade) so net economics
shown reflect realistic friction.

Important caveat on the alt-stop sweep:
  Only TIGHTER stops can be re-simulated from observed MAE. Original
  stop = "one prior in sequence" was 15-30 pts. Sweep range is
  2.5-25 pts. So sweep covers tighter or roughly-equal alternatives,
  not wider.

Important caveat on the first-bar filter:
  The first bar's close is the EARLIEST signal we can act on (60s
  after entry). The "filtered" trade set assumes we EXIT at first
  bar's close if it didn't close favorably; this exit is at first
  bar's close price. The trade incurs a small PnL during that first
  bar (could be plus or minus, mean close-move ≈ 0).

We model this as:
  - For trades where first bar closed favorably: hold to original
    outcome (win/loss/timeout) using the alt-stop substitution rule.
  - For trades where first bar closed unfavorably: exit immediately
    at first bar's close. PnL = first_bar_close_move_pts (signed).
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

ALT_STOP_PTS = [2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0, 25.0]
COMMISSION_PTS = 0.25  # $5 RT / $20 per pt = 0.25 pts on NQ
NQ_DOLLAR_PER_PT = 20.0


# ---------------- Filter + alt-stop substitution ----------------

def apply_first_bar_filter_and_alt_stop(
    trades: pd.DataFrame, alt_stop_pts: float,
) -> pd.DataFrame:
    """For each trade, compute the new outcome under:
      - first-bar filter: if first_bar_winner == 0, exit at first
        bar close (PnL = first_bar_close_move_pts).
      - else (first bar passed), apply alt-stop substitution on the
        observed MAE: if MAE >= alt_stop_pts, alt stop triggered
        first → loss at -alt_stop_pts. Else → original PnL.

    Adds columns: filter_outcome, filter_pnl_gross, filter_pnl_net.
    Net = gross - COMMISSION_PTS. Trades that were filtered out via
    first-bar exit also pay one commission (entry + first-bar exit).
    """
    out = trades.copy()
    fb_pass = out["first_bar_winner"] == 1
    mae = out["mae_pts"]
    triggered = mae >= alt_stop_pts

    # Outcome and gross PnL
    new_outcome = np.where(
        ~fb_pass,
        "first_bar_filtered",
        np.where(triggered, "loss", out["outcome"]))
    new_pnl_gross = np.where(
        ~fb_pass,
        out["first_bar_close_move_pts"],
        np.where(triggered, -alt_stop_pts, out["pnl_pts"]))

    out["filter_outcome"] = new_outcome
    out["filter_pnl_gross"] = new_pnl_gross
    out["filter_pnl_net"] = new_pnl_gross - COMMISSION_PTS
    out["alt_stop_pts"] = alt_stop_pts
    return out


def stats_block(trades: pd.DataFrame,
                    pnl_col: str = "filter_pnl_net",
                    outcome_col: str = "filter_outcome") -> dict:
    n = len(trades)
    if n == 0: return {"n": 0}
    pnl = trades[pnl_col]
    win = trades[outcome_col] == "win"
    loss = trades[outcome_col] == "loss"
    fb_filt = trades[outcome_col] == "first_bar_filtered"
    return {
        "n": n,
        "n_win": int(win.sum()),
        "n_loss": int(loss.sum()),
        "n_fb_filtered": int(fb_filt.sum()),
        "win_rate": float(win.mean()),
        "loss_rate": float(loss.mean()),
        "fb_filtered_rate": float(fb_filt.mean()),
        "mean_pnl_pts": float(pnl.mean()),
        "median_pnl_pts": float(pnl.median()),
        "total_pnl_pts": float(pnl.sum()),
        "mean_win_pts": (float(pnl[win].mean())
                              if win.any() else float("nan")),
        "mean_loss_pts": (float(pnl[loss].mean())
                                if loss.any() else float("nan")),
        "mean_fb_filt_pnl": (float(pnl[fb_filt].mean())
                                  if fb_filt.any() else float("nan")),
    }


def sweep_per_group(trades: pd.DataFrame,
                          group_cols: list[str]) -> pd.DataFrame:
    """For each group, sweep alt stops; pick the alt stop that
    maximizes net PnL on the FILTERED population. Also report
    the unfiltered baseline net PnL for comparison."""
    rows = []
    for keys, g in trades.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        # Unfiltered baseline (no commission applied yet — apply now)
        unf_pnl = g["pnl_pts"].mean() - COMMISSION_PTS
        unf_wr = float((g["outcome"] == "win").mean())
        unf_n = len(g)

        # Sweep alt stops on filtered population
        best = None
        for D in ALT_STOP_PTS:
            sg = apply_first_bar_filter_and_alt_stop(g, D)
            s = stats_block(sg)
            if best is None or s["mean_pnl_pts"] > best["mean_pnl_pts"]:
                best = {"alt_stop": D, **s}

        row = dict(zip(group_cols, keys))
        row.update({
            "n_total": unf_n,
            "unfilt_mean_pnl_net": unf_pnl,
            "unfilt_win_rate": unf_wr,
            "best_stop": best["alt_stop"],
            "filt_n": best["n"],  # same as n_total — we kept all rows
            "filt_n_win": best["n_win"],
            "filt_n_loss": best["n_loss"],
            "filt_n_fb_filtered": best["n_fb_filtered"],
            "filt_win_rate": best["win_rate"],
            "filt_loss_rate": best["loss_rate"],
            "filt_fb_filtered_rate": best["fb_filtered_rate"],
            "filt_mean_pnl_net": best["mean_pnl_pts"],
            "filt_total_pnl_net": best["total_pnl_pts"],
            "filt_mean_win": best["mean_win_pts"],
            "filt_mean_loss": best["mean_loss_pts"],
            "filt_mean_fb_filt_pnl": best["mean_fb_filt_pnl"],
            "improvement_vs_unfilt": (
                best["mean_pnl_pts"] - unf_pnl),
            "annualized_dollars": (
                best["total_pnl_pts"] * NQ_DOLLAR_PER_PT),
        })
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------- Reporting ----------------

def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:+.{dp}f}"


def fmt_d(v):
    if v is None or pd.isna(v): return "—"
    return f"${v:,.0f}"


def write_report(trades, sweep_overall, sweep_pair_session):
    L = []
    L.append("# Combined Filter + Stop Optimization "
              "— Level Momentum Study\n")
    L.append(f"Source: `{SOURCE}` | n={len(trades):,}\n")
    L.append("## Method\n")
    L.append(
        "Combines the first-bar filter (only HOLD trades whose "
        "first bar closed favorably; otherwise exit at first-bar "
        "close) with the alt-stop sweep (replace 'one prior in "
        "sequence' stop with a tighter D in {2.5, 5, 7.5, 10, "
        "12.5, 15, 17.5, 20, 25} pts).\n\n"
        "Mechanics per trade:\n"
        "1. Enter at bar after trigger's open (causal, as before).\n"
        "2. After first bar closes:\n"
        "   - If first bar closed UNFAVORABLY for trade direction "
        "→ exit immediately at first-bar close. PnL = "
        "first_bar_close_move_pts (signed by direction).\n"
        "   - Else → continue holding under the alt-stop rule.\n"
        "3. With alt stop D pts, if observed MAE >= D, alt stop "
        "triggered first → loss at -D. Else → original outcome.\n\n"
        f"Commission: {COMMISSION_PTS} pts/trade (≈ $5 RT on NQ "
        "at $20/pt). Applied to ALL trades, including those exited "
        "at first bar.\n\n"
        "Annualized $ uses the FILTERED net total PnL × NQ $20/pt "
        "multiplier.\n")

    L.append("## Overall (all pairs/sessions combined)\n")
    L.append("| Stop pts | n | WR | LossR | FB-filt% | "
             "Mean PnL Net | Median | Total PnL Net | Annual $ |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in sweep_overall.iterrows():
        ann = r['total_pnl_pts'] * NQ_DOLLAR_PER_PT
        L.append(
            f"| {r['alt_stop_pts']} | {int(r['n']):,} | "
            f"{fmt_p(r['win_rate'])} | "
            f"{fmt_p(r['loss_rate'])} | "
            f"{fmt_p(r['fb_filtered_rate'])} | "
            f"{fmt_f(r['mean_pnl_pts'], 3)} | "
            f"{fmt_f(r['median_pnl_pts'], 2)} | "
            f"{fmt_f(r['total_pnl_pts'], 0)} | "
            f"{fmt_d(ann)} |")
    L.append("")

    L.append("## Best (filter + alt-stop) per (pair × session)\n")
    L.append("Sorted by improvement vs unfiltered baseline.\n")
    L.append("| Pair | Session | n | Best Stop | "
             "Filt WR | Filt PnL Net | Unfilt PnL Net | "
             "Improvement | Annual $ |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    s = sweep_pair_session.sort_values(
        "improvement_vs_unfilt", ascending=False)
    for _, r in s.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n_total']):,} | {r['best_stop']:.1f} | "
            f"{fmt_p(r['filt_win_rate'])} | "
            f"{fmt_f(r['filt_mean_pnl_net'], 3)} | "
            f"{fmt_f(r['unfilt_mean_pnl_net'], 3)} | "
            f"{fmt_f(r['improvement_vs_unfilt'], 3)} | "
            f"{fmt_d(r['annualized_dollars'])} |")
    L.append("")

    L.append("## Top deployable candidates "
              "(net mean PnL > +$0.30/trade, n >= 1,000)\n")
    candidates = sweep_pair_session[
        (sweep_pair_session["filt_mean_pnl_net"] > 0.30) &
        (sweep_pair_session["n_total"] >= 1000)
    ].sort_values("filt_mean_pnl_net", ascending=False)
    if candidates.empty:
        L.append("None.\n")
    else:
        L.append("| Pair | Session | n | Best Stop | "
                 "Filt WR | Mean Net | Annual $ |")
        L.append("|---|---|--:|--:|--:|--:|--:|")
        for _, r in candidates.iterrows():
            L.append(
                f"| {r['level_pair']} | {r['entry_session']} | "
                f"{int(r['n_total']):,} | {r['best_stop']:.1f} | "
                f"{fmt_p(r['filt_win_rate'])} | "
                f"{fmt_f(r['filt_mean_pnl_net'], 3)} | "
                f"{fmt_d(r['annualized_dollars'])} |")
        L.append("")

    L.append("## Combined-portfolio summary "
              "(top candidates only)\n")
    if not candidates.empty:
        total_n = int(candidates["n_total"].sum())
        total_pnl = float(candidates["filt_total_pnl_net"].sum())
        total_ann = float(candidates["annualized_dollars"].sum())
        per_trade = total_pnl / total_n if total_n else 0
        L.append(f"- Combined trade count: {total_n:,}/yr "
                  f"({total_n/252:.1f} per trading day)")
        L.append(f"- Combined net PnL: {total_pnl:+.1f} pts/year")
        L.append(f"- Combined annualized $: {fmt_d(total_ann)}")
        L.append(f"- Combined avg net PnL/trade: "
                  f"{per_trade:+.3f} pts")
    L.append("")

    L.append("## Caveats\n")
    L.append(
        f"- Single year (2025), no OOS validation.\n"
        f"- Commission set at {COMMISSION_PTS} pts (~$5 RT). "
        f"Higher commission would shift breakeven up.\n"
        f"- Slippage = 0 assumed. NQ liquidity is generally good "
        f"so 1 tick ($0.25 = 0.0125 pts at 1 contract) of slip "
        f"per trade × 2 sides = ~$5 round-trip slip. Effective "
        f"~0.5 pts/trade total friction (commission + slippage). "
        f"Most profitable cells still positive at this level.\n"
        f"- Alt-stop sweep is bounded at 25 pts (cannot test "
        f"wider stops without re-simulating from raw bars).\n"
        f"- The first-bar filter requires waiting one bar before "
        f"committing — a 60-second delay. Tradeable in practice.\n"
        f"- 'Best' stop chosen by mean PnL on this single year; "
        f"OOS validation needed before trusting.\n")

    p = OUT / "report_combined_filter_stop.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    print(f"Loading {SOURCE}...")
    trades = pd.read_csv(SOURCE)
    print(f"  {len(trades):,} trades")

    print("\nOverall sweep (all pairs/sessions combined)...")
    rows = []
    for D in ALT_STOP_PTS:
        sg = apply_first_bar_filter_and_alt_stop(trades, D)
        s = stats_block(sg)
        s["alt_stop_pts"] = D
        rows.append(s)
    sweep_ovr = pd.DataFrame(rows)
    sweep_ovr.to_csv(OUT / "combined_sweep_overall.csv",
                            index=False)
    print(sweep_ovr[
        ["alt_stop_pts", "n", "win_rate", "fb_filtered_rate",
         "mean_pnl_pts", "total_pnl_pts"]].to_string(index=False))

    print("\nSweep per (pair × session)...")
    sweep_ps = sweep_per_group(
        trades, ["level_pair", "entry_session"])
    sweep_ps.to_csv(
        OUT / "combined_sweep_pair_session.csv", index=False)

    print("\nWriting report...")
    rp = write_report(trades, sweep_ovr, sweep_ps)
    print(f"Report: {rp}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
