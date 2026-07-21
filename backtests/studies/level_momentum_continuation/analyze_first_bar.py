"""First-bar MFE/MAE and open->close outcome analysis.

For each trade, the "first bar" is the entry bar (the bar AFTER the
trigger bar; we entered at this bar's open).

Computes:
  - first_bar_MFE_pts: max favorable excursion within the entry bar
  - first_bar_MAE_pts: max adverse excursion within the entry bar
  - first_bar_winner: did the entry bar's CLOSE move favorably vs
    its OPEN? (i.e., 1-bar holding period outcome)

Aggregated by (pair × session) and compared against the full-trade
outcome to see if first-bar behavior predicts the trade's eventual
win/loss.

Also compares first-bar win% to the full 120-bar win rate by group.
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

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m, annotate_sessions_ct,
)

V0_PARQUET = Path("data/raw/NQ_v0_1s_2025.parquet")
SOURCE = Path(
    "studies/level_momentum_continuation/results_nq_2025/"
    "trades_unfiltered.csv")
OUT = Path(
    "studies/level_momentum_continuation/results_nq_2025")


def compute_first_bar_metrics(trades: pd.DataFrame,
                                       bars_1m: pd.DataFrame) -> pd.DataFrame:
    """Pull entry-bar OHLC and compute first-bar metrics.

    Trades' entry_idx is a positional index into the bars frame
    that the original simulation iterated. Verify alignment by
    spot-checking entry_price == bars.open[entry_idx].
    """
    bars = bars_1m.reset_index(drop=False)
    opens = bars["open"].values
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    n = len(bars)

    out = trades.copy()
    eidx = out["entry_idx"].astype(int).values
    valid = (eidx >= 0) & (eidx < n)
    if not valid.all():
        out = out[valid].copy()
        eidx = out["entry_idx"].astype(int).values

    bar_open = opens[eidx]
    bar_high = highs[eidx]
    bar_low = lows[eidx]
    bar_close = closes[eidx]

    # Spot-check: do recorded entry_prices match bars.open[entry_idx]?
    diff = np.abs(out["entry_price"].values - bar_open)
    bad = (diff > 0.001).sum()
    print(f"  alignment check: {bad}/{len(out)} trades have "
          "entry_price != bars.open[entry_idx]")

    out["first_bar_open"] = bar_open
    out["first_bar_high"] = bar_high
    out["first_bar_low"] = bar_low
    out["first_bar_close"] = bar_close

    d = out["direction"].values
    # MFE = price moved favorably in trade direction within the bar
    # For long: MFE = high - open; MAE = open - low
    # For short: MFE = open - low; MAE = high - open
    out["first_bar_mfe_pts"] = np.where(
        d == 1, bar_high - bar_open, bar_open - bar_low)
    out["first_bar_mae_pts"] = np.where(
        d == 1, bar_open - bar_low, bar_high - bar_open)
    out["first_bar_close_move_pts"] = np.where(
        d == 1, bar_close - bar_open, bar_open - bar_close)
    out["first_bar_winner"] = (
        out["first_bar_close_move_pts"] > 0).astype(int)
    return out


def aggregate(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    iter_obj = (df.groupby(group_cols, observed=True)
                  if group_cols else [(("ALL",), df)])
    for keys, g in iter_obj:
        if not isinstance(keys, tuple): keys = (keys,)
        n = len(g)
        wins_full = (g["outcome"] == "win").sum()
        wins_first = (g["first_bar_winner"] == 1).sum()
        # First-bar predictive power
        first_w_full_w = ((g["first_bar_winner"] == 1) &
                            (g["outcome"] == "win")).sum()
        first_l_full_w = ((g["first_bar_winner"] == 0) &
                            (g["outcome"] == "win")).sum()
        first_w_full_l = ((g["first_bar_winner"] == 1) &
                            (g["outcome"] == "loss")).sum()
        first_l_full_l = ((g["first_bar_winner"] == 0) &
                            (g["outcome"] == "loss")).sum()
        cond_win_if_first_win = (
            first_w_full_w / max(first_w_full_w + first_w_full_l, 1))
        cond_win_if_first_loss = (
            first_l_full_w / max(first_l_full_w + first_l_full_l, 1))
        row = dict(zip(group_cols if group_cols else ["scope"],
                            keys))
        row.update({
            "n": n,
            "first_bar_win%": wins_first / n,
            "full_trade_win%": wins_full / n,
            "first_bar_mean_mfe": float(g["first_bar_mfe_pts"].mean()),
            "first_bar_mean_mae": float(g["first_bar_mae_pts"].mean()),
            "first_bar_mfe_p50": float(np.percentile(
                g["first_bar_mfe_pts"], 50)),
            "first_bar_mfe_p90": float(np.percentile(
                g["first_bar_mfe_pts"], 90)),
            "first_bar_mae_p50": float(np.percentile(
                g["first_bar_mae_pts"], 50)),
            "first_bar_mae_p90": float(np.percentile(
                g["first_bar_mae_pts"], 90)),
            "mean_close_move_pts": float(
                g["first_bar_close_move_pts"].mean()),
            # Conditional: trade win rate given first-bar outcome
            "P(trade_win | first_bar_win)": cond_win_if_first_win,
            "P(trade_win | first_bar_loss)": cond_win_if_first_loss,
            "lift_first_bar_filter": (
                cond_win_if_first_win - cond_win_if_first_loss),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:+.{dp}f}"


def write_report(trades, agg_overall, agg_pair,
                       agg_session, agg_pair_session):
    L = []
    L.append("# First-Bar MFE/MAE Analysis "
              "— Level Momentum Study\n")
    L.append(f"Source trades: `{SOURCE}` | n={len(trades):,}\n")

    L.append("## Method\n")
    L.append(
        "- 'First bar' = the bar AFTER the trigger bar (entry "
        "happens at this bar's open).\n"
        "- **first_bar_MFE** = within this bar, how far did price "
        "move favorably for the trade direction (high-open for "
        "long, open-low for short)?\n"
        "- **first_bar_MAE** = within this bar, how far adverse "
        "(open-low for long, high-open for short)?\n"
        "- **first_bar_winner** = did the bar's CLOSE move "
        "favorably vs OPEN? Equivalent to a 1-bar holding-period "
        "outcome.\n"
        "- **P(trade_win | first_bar_win)** = of trades whose first "
        "bar closed favorably, what fraction eventually hit the "
        "level target?\n"
        "- **P(trade_win | first_bar_loss)** = of trades whose first "
        "bar closed unfavorably, what fraction still hit target.\n"
        "- **lift** = the difference. Positive lift means first-bar "
        "outcome predicts the trade outcome (could be a useful "
        "early filter).\n")

    L.append("## Overall (all trades)\n")
    r = agg_overall.iloc[0]
    L.append(f"- n = {r['n']:,}")
    L.append(f"- **First-bar winner% (close > open in dir): "
              f"{fmt_p(r['first_bar_win%'])}**")
    L.append(f"- Full-trade winner% (target hit before stop): "
              f"{fmt_p(r['full_trade_win%'])}")
    L.append(f"- First-bar mean MFE: "
              f"{r['first_bar_mean_mfe']:.2f} pts (median "
              f"{r['first_bar_mfe_p50']:.2f}, p90 "
              f"{r['first_bar_mfe_p90']:.2f})")
    L.append(f"- First-bar mean MAE: "
              f"{r['first_bar_mean_mae']:.2f} pts (median "
              f"{r['first_bar_mae_p50']:.2f}, p90 "
              f"{r['first_bar_mae_p90']:.2f})")
    L.append(f"- Mean close-move (signed by direction): "
              f"{r['mean_close_move_pts']:+.3f} pts")
    L.append(f"- **P(trade_win | first_bar_win) = "
              f"{fmt_p(r['P(trade_win | first_bar_win)'])}**")
    L.append(f"- **P(trade_win | first_bar_loss) = "
              f"{fmt_p(r['P(trade_win | first_bar_loss)'])}**")
    L.append(f"- **First-bar filter lift: "
              f"{fmt_p(r['lift_first_bar_filter'])}**\n")

    L.append("## By session\n")
    L.append("| Session | n | 1st-bar Win% | Full Win% | "
             "1st MFE | 1st MAE | Mean Close-Move | "
             "P(W\\|1st W) | P(W\\|1st L) | Lift |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in agg_session.iterrows():
        L.append(
            f"| {r['entry_session']} | {int(r['n']):,} | "
            f"{fmt_p(r['first_bar_win%'])} | "
            f"{fmt_p(r['full_trade_win%'])} | "
            f"{r['first_bar_mean_mfe']:.2f} | "
            f"{r['first_bar_mean_mae']:.2f} | "
            f"{fmt_f(r['mean_close_move_pts'], 3)} | "
            f"{fmt_p(r['P(trade_win | first_bar_win)'])} | "
            f"{fmt_p(r['P(trade_win | first_bar_loss)'])} | "
            f"{fmt_p(r['lift_first_bar_filter'])} |")
    L.append("")

    L.append("## By pair (overall)\n")
    L.append("| Pair | n | 1st-bar Win% | Full Win% | 1st MFE | "
             "1st MAE | Mean Move | P(W\\|1st W) | "
             "P(W\\|1st L) | Lift |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in agg_pair.sort_values(
            "lift_first_bar_filter", ascending=False).iterrows():
        L.append(
            f"| {r['level_pair']} | {int(r['n']):,} | "
            f"{fmt_p(r['first_bar_win%'])} | "
            f"{fmt_p(r['full_trade_win%'])} | "
            f"{r['first_bar_mean_mfe']:.2f} | "
            f"{r['first_bar_mean_mae']:.2f} | "
            f"{fmt_f(r['mean_close_move_pts'], 3)} | "
            f"{fmt_p(r['P(trade_win | first_bar_win)'])} | "
            f"{fmt_p(r['P(trade_win | first_bar_loss)'])} | "
            f"{fmt_p(r['lift_first_bar_filter'])} |")
    L.append("")

    L.append("## By pair × session\n")
    L.append("| Pair | Session | n | 1st-bar Win% | Full Win% | "
             "1st MFE | 1st MAE | P(W\\|1st W) | P(W\\|1st L) | "
             "Lift |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in agg_pair_session.sort_values(
            ["level_pair", "entry_session"]).iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | "
            f"{fmt_p(r['first_bar_win%'])} | "
            f"{fmt_p(r['full_trade_win%'])} | "
            f"{r['first_bar_mean_mfe']:.2f} | "
            f"{r['first_bar_mean_mae']:.2f} | "
            f"{fmt_p(r['P(trade_win | first_bar_win)'])} | "
            f"{fmt_p(r['P(trade_win | first_bar_loss)'])} | "
            f"{fmt_p(r['lift_first_bar_filter'])} |")
    L.append("")

    p = OUT / "report_first_bar.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    print(f"Loading trades from {SOURCE}...")
    trades = pd.read_csv(SOURCE)
    print(f"  {len(trades):,} trades")

    print("Reloading bars...")
    bars_1s = load_v0_1s(V0_PARQUET)
    bars_1m = resample_1s_to_1m(bars_1s)
    bars_1m = annotate_sessions_ct(bars_1m)
    print(f"  {len(bars_1m):,} 1m bars")

    print("Computing first-bar metrics...")
    trades_fb = compute_first_bar_metrics(trades, bars_1m)

    trades_fb.to_csv(OUT / "trades_with_first_bar.csv",
                            index=False)

    print("Aggregating...")
    agg_overall = aggregate(trades_fb, [])
    agg_pair = aggregate(trades_fb, ["level_pair"])
    agg_session = aggregate(trades_fb, ["entry_session"])
    agg_ps = aggregate(trades_fb,
                            ["level_pair", "entry_session"])

    agg_overall.to_csv(OUT / "first_bar_overall.csv", index=False)
    agg_pair.to_csv(OUT / "first_bar_pair.csv", index=False)
    agg_session.to_csv(OUT / "first_bar_session.csv", index=False)
    agg_ps.to_csv(OUT / "first_bar_pair_session.csv",
                          index=False)

    print("Writing report...")
    rp = write_report(trades_fb, agg_overall, agg_pair,
                            agg_session, agg_ps)
    print(f"Report: {rp}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
