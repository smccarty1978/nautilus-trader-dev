"""SMA(20) trend-alignment filter analysis on Level Momentum trades.

Hypothesis: trades aligned with the SMA(20) trend (long when close >
SMA20, short when close < SMA20) at the trigger bar should have:
  - Higher win rate
  - Tighter winner MAE
  - Better mean PnL per trade

Compares aligned vs unaligned subsets per (pair, session). Also runs
the alt-stop sweep separately on each subset so we can see whether
optimal stop changes when restricted to aligned trades.

SMA(20) timing: computed on 1m closes, causal — SMA at bar i uses
closes [i-19 .. i] inclusive. The SMA value at the TRIGGER bar
(close-time) is what we compare to that bar's close.
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

SMA_LEN = 20
ALT_STOP_PTS = [2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0, 25.0]


# ---------------- Compute SMA + tag trades ----------------

def compute_sma_and_tag(trades: pd.DataFrame,
                                bars_1m: pd.DataFrame) -> pd.DataFrame:
    """Add aligned column to trades.
    Aligned = (long & close > SMA20) OR (short & close < SMA20)."""
    bars = bars_1m.copy()
    bars[f"sma{SMA_LEN}"] = (bars["close"]
        .rolling(SMA_LEN, min_periods=SMA_LEN).mean())
    # Build a ts_close -> sma lookup
    sma_lookup = bars[f"sma{SMA_LEN}"]

    out = trades.copy()
    out["trigger_ts_close"] = pd.to_datetime(
        out["trigger_ts_close"], utc=True)
    out[f"sma{SMA_LEN}"] = (out["trigger_ts_close"]
        .map(lambda ts: sma_lookup.get(ts, np.nan)))
    # Aligned check: long needs close > SMA, short needs close < SMA
    aligned = np.where(
        out["direction"] == 1,
        out["close_at_breach"] > out[f"sma{SMA_LEN}"],
        out["close_at_breach"] < out[f"sma{SMA_LEN}"],
    )
    out["sma_aligned"] = aligned
    # Drop trades where SMA isn't computable (warmup)
    out = out.dropna(subset=[f"sma{SMA_LEN}"])
    return out


# ---------------- Stats helpers ----------------

def stats_block(trades: pd.DataFrame, pnl_col="pnl_pts",
                    outcome_col="outcome",
                    mae_col="mae_pts") -> dict:
    n = len(trades)
    if n == 0: return {"n": 0}
    win = trades[outcome_col] == "win"
    loss = trades[outcome_col] == "loss"
    mae_wins = trades.loc[win, mae_col]
    return {
        "n": n,
        "win_rate": float(win.mean()),
        "loss_rate": float(loss.mean()),
        "mean_pnl_pts": float(trades[pnl_col].mean()),
        "median_pnl_pts": float(trades[pnl_col].median()),
        "total_pnl_pts": float(trades[pnl_col].sum()),
        "mean_win_pts": (float(trades.loc[win, pnl_col].mean())
                              if win.any() else float("nan")),
        "mean_loss_pts": (float(trades.loc[loss, pnl_col].mean())
                                if loss.any() else float("nan")),
        "winner_mae_p50": (float(np.percentile(mae_wins, 50))
                                if len(mae_wins) else float("nan")),
        "winner_mae_p75": (float(np.percentile(mae_wins, 75))
                                if len(mae_wins) else float("nan")),
        "winner_mae_p90": (float(np.percentile(mae_wins, 90))
                                if len(mae_wins) else float("nan")),
        "winner_mae_p95": (float(np.percentile(mae_wins, 95))
                                if len(mae_wins) else float("nan")),
        "winner_mae_mean": (float(mae_wins.mean())
                                  if len(mae_wins) else float("nan")),
    }


def aligned_vs_unaligned(trades: pd.DataFrame,
                                  group_cols: list[str]) -> pd.DataFrame:
    rows = []
    for keys, g in trades.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        # Aligned subset
        for label, mask in [
                ("aligned", g["sma_aligned"]),
                ("unaligned", ~g["sma_aligned"]),
                ("all", pd.Series([True] * len(g),
                                          index=g.index))]:
            sub = g[mask]
            row = dict(zip(group_cols, keys))
            row["bucket"] = label
            row.update(stats_block(sub))
            rows.append(row)
    df = pd.DataFrame(rows)
    return df


def resim_with_alt_stop(trades: pd.DataFrame,
                                alt_stop_pts: float) -> pd.DataFrame:
    out = trades.copy()
    triggered = out["mae_pts"] >= alt_stop_pts
    out["new_outcome"] = np.where(
        triggered, "loss", out["outcome"])
    out["new_pnl_pts"] = np.where(
        triggered, -alt_stop_pts, out["pnl_pts"])
    return out


def alt_stop_sweep_aligned(trades: pd.DataFrame,
                                    group_cols: list[str]) -> pd.DataFrame:
    """For each (group, alignment), sweep alt stops, find best."""
    rows = []
    for keys, g in trades.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        for label, mask in [
                ("aligned", g["sma_aligned"]),
                ("unaligned", ~g["sma_aligned"]),
                ("all", pd.Series([True] * len(g),
                                          index=g.index))]:
            sub = g[mask]
            if len(sub) == 0: continue
            best = None
            for D in ALT_STOP_PTS:
                sg = resim_with_alt_stop(sub, D)
                s = stats_block(sg, pnl_col="new_pnl_pts",
                                     outcome_col="new_outcome")
                if best is None or (
                        s["mean_pnl_pts"] > best["mean_pnl_pts"]):
                    best = {"alt_stop": D, **s}
            base = stats_block(sub)
            row = dict(zip(group_cols, keys))
            row["bucket"] = label
            row["n"] = base["n"]
            row["orig_pnl"] = base["mean_pnl_pts"]
            row["orig_wr"] = base["win_rate"]
            row["best_stop"] = best["alt_stop"]
            row["best_pnl"] = best["mean_pnl_pts"]
            row["best_wr"] = best["win_rate"]
            row["improvement"] = best["mean_pnl_pts"] - base["mean_pnl_pts"]
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------- Reporting ----------------

def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:+.{dp}f}"


def write_report(trades, n_drop_warmup, av_un_pair_session,
                       sweep_pair_session_aligned,
                       sweep_pair_session_unaligned,
                       best_aligned_only):
    L = []
    L.append(f"# SMA(20) Trend-Alignment Filter "
              "— Level Momentum Study\n")
    L.append(f"Source trades: `{SOURCE}` | n={len(trades):,} "
              f"(after dropping {n_drop_warmup:,} for SMA warmup)\n")

    L.append("## Method\n")
    L.append(
        f"- Compute SMA({SMA_LEN}) on 1m closes (causal: SMA at "
        f"bar i uses closes [i-{SMA_LEN-1} .. i] inclusive).\n"
        "- For each trigger bar, check the close vs the SMA value "
        "at that same bar.\n"
        "- **Aligned** = (long AND close > SMA) OR (short AND "
        "close < SMA).\n"
        "- **Unaligned** = the opposite.\n"
        "- Hypothesis: aligned trades should have higher WR, "
        "tighter winner MAE, better mean PnL.\n"
        "- Trades within first 19 bars of data dropped (SMA "
        "warmup).\n")

    # Overall aligned vs unaligned (manual — no groupby with empty keys)
    if True:
        L.append("## Overall: aligned vs unaligned (all pairs/sessions combined)\n")
        L.append("| Bucket | n | WR | LossR | Mean PnL | "
                 "Median | Total | Mean Win | Mean Loss | "
                 "Win MAE p50 | p90 | p95 |")
        L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        # Manually compute for overall
        for label, mask in [
                ("aligned", trades["sma_aligned"]),
                ("unaligned", ~trades["sma_aligned"]),
                ("all", pd.Series([True] * len(trades),
                                          index=trades.index))]:
            sub = trades[mask]
            s = stats_block(sub)
            L.append(
                f"| {label} | {s['n']:,} | "
                f"{fmt_p(s['win_rate'])} | "
                f"{fmt_p(s['loss_rate'])} | "
                f"{fmt_f(s['mean_pnl_pts'], 3)} | "
                f"{fmt_f(s['median_pnl_pts'], 2)} | "
                f"{fmt_f(s['total_pnl_pts'], 0)} | "
                f"{fmt_f(s['mean_win_pts'], 2)} | "
                f"{fmt_f(s['mean_loss_pts'], 2)} | "
                f"{fmt_f(s['winner_mae_p50'], 2)} | "
                f"{fmt_f(s['winner_mae_p90'], 2)} | "
                f"{fmt_f(s['winner_mae_p95'], 2)} |")
        L.append("")

    L.append("## Aligned vs Unaligned by (pair × session)\n")
    L.append("| Pair | Session | Bucket | n | WR | Mean PnL | "
             "Mean Win | Mean Loss | Win MAE p50 | p90 | p95 |")
    L.append("|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in av_un_pair_session.sort_values(
            ["level_pair", "entry_session", "bucket"]).iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{r['bucket']} | {int(r['n']):,} | "
            f"{fmt_p(r['win_rate'])} | "
            f"{fmt_f(r['mean_pnl_pts'], 3)} | "
            f"{fmt_f(r['mean_win_pts'], 2)} | "
            f"{fmt_f(r['mean_loss_pts'], 2)} | "
            f"{fmt_f(r['winner_mae_p50'], 2)} | "
            f"{fmt_f(r['winner_mae_p90'], 2)} | "
            f"{fmt_f(r['winner_mae_p95'], 2)} |")
    L.append("")

    L.append("## Best alt-stop per (pair × session × alignment)\n")
    L.append("Top of table sorted by improvement vs original (within "
              "the aligned bucket).\n")
    L.append("| Pair | Session | Bucket | n | Orig PnL | Orig WR | "
             "Best stop | Best PnL | Best WR | Improvement |")
    L.append("|---|---|---|--:|--:|--:|--:|--:|--:|--:|")
    # Sort: aligned rows first by improvement desc
    al_rows = sweep_pair_session_aligned[
        sweep_pair_session_aligned["bucket"] == "aligned"
    ].sort_values("improvement", ascending=False)
    un_rows = sweep_pair_session_aligned[
        sweep_pair_session_aligned["bucket"] == "unaligned"
    ]
    all_rows = sweep_pair_session_aligned[
        sweep_pair_session_aligned["bucket"] == "all"
    ]
    for _, r in al_rows.iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{r['bucket']} | {int(r['n']):,} | "
            f"{fmt_f(r['orig_pnl'], 3)} | "
            f"{fmt_p(r['orig_wr'])} | "
            f"{r['best_stop']:.1f} | "
            f"{fmt_f(r['best_pnl'], 3)} | "
            f"{fmt_p(r['best_wr'])} | "
            f"{fmt_f(r['improvement'], 3)} |")
    L.append("")

    L.append("## Top aligned-only candidates (positive best PnL, "
              "n >= 500)\n")
    L.append("| Pair | Session | n | Orig PnL | Best stop | "
             "Best PnL | Best WR | Annualized $* |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|")
    candidates = al_rows[
        (al_rows["best_pnl"] > 0) & (al_rows["n"] >= 500)
    ].sort_values("best_pnl", ascending=False)
    for _, r in candidates.iterrows():
        ann_dollars = r["best_pnl"] * r["n"] * 20  # NQ $20/pt
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | "
            f"{fmt_f(r['orig_pnl'], 3)} | "
            f"{r['best_stop']:.1f} | "
            f"{fmt_f(r['best_pnl'], 3)} | "
            f"{fmt_p(r['best_wr'])} | "
            f"${ann_dollars:,.0f} |")
    L.append("")
    L.append("*Annualized $ uses NQ contract multiplier $20/pt × n trades. "
              "ETH-only or RTH-only depending on row. No commissions.\n")

    p = OUT / "report_sma_filter.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    print(f"Loading trades from {SOURCE}...")
    trades = pd.read_csv(SOURCE)
    print(f"  {len(trades):,} trades")

    print(f"Reloading bars + computing SMA({SMA_LEN})...")
    bars_1s = load_v0_1s(V0_PARQUET)
    bars_1m = resample_1s_to_1m(bars_1s)
    bars_1m = annotate_sessions_ct(bars_1m)
    print(f"  {len(bars_1m):,} 1m bars")

    print("Tagging trades with SMA alignment...")
    trades_tagged = compute_sma_and_tag(trades, bars_1m)
    n_drop = len(trades) - len(trades_tagged)
    print(f"  {len(trades_tagged):,} trades after SMA warmup "
          f"(dropped {n_drop:,})")
    aligned_n = int(trades_tagged["sma_aligned"].sum())
    unalign_n = len(trades_tagged) - aligned_n
    print(f"  Aligned: {aligned_n:,} ({100*aligned_n/len(trades_tagged):.1f}%)")
    print(f"  Unaligned: {unalign_n:,} ({100*unalign_n/len(trades_tagged):.1f}%)")

    # Save tagged trades
    trades_tagged.to_csv(OUT / "trades_with_sma20.csv",
                                 index=False)

    print("\nComputing aligned vs unaligned by (pair × session)...")
    av_ps = aligned_vs_unaligned(
        trades_tagged, ["level_pair", "entry_session"])
    av_ps.to_csv(OUT / "sma_filter_pair_session.csv",
                       index=False)

    print("Sweeping alt stops per (pair × session × bucket)...")
    sweep_ps_al = alt_stop_sweep_aligned(
        trades_tagged, ["level_pair", "entry_session"])
    sweep_ps_al.to_csv(
        OUT / "sma_filter_alt_stop_sweep.csv", index=False)

    # Aligned-only best (subset of above)
    best_al = sweep_ps_al[
        sweep_ps_al["bucket"] == "aligned"].sort_values(
            "best_pnl", ascending=False)
    best_al.to_csv(OUT / "sma_filter_best_stops_aligned.csv",
                          index=False)

    print("\nWriting report...")
    rp = write_report(
        trades_tagged, n_drop, av_ps, sweep_ps_al,
        sweep_ps_al, best_al)
    print(f"Report: {rp}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
