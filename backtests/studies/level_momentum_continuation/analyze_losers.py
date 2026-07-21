"""Loser anatomy — MFE / MAE / MFE-MAE ratio distributions.

For trades that LOST (hit the original stop) and trades that
TIMED OUT, re-walk each trade's bars and compute:
  - MFE_pts: max favorable excursion during trade life
  - MAE_pts: max adverse excursion during trade life (already known
    for losers ≈ stop distance)
  - mfe_to_mae_ratio: MFE / MAE (was the trade ever in our favor?)
  - mfe_above_X_threshold flags: did MFE reach X pts at any point?

Goal: characterize losing trades. Did they "almost work" (high MFE
before reversing)? Or were they wrong from the start (low MFE)?

The answer informs whether a trailing stop / scale-out / move-to-BE
could have saved some losses.
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
    "trades_with_first_bar.csv")
OUT = Path(
    "studies/level_momentum_continuation/results_nq_2025")

MFE_THRESHOLDS_PTS = [2.5, 5.0, 7.5, 10.0, 15.0, 20.0]


def compute_loser_mfe_mae(trades: pd.DataFrame,
                                  bars_1m: pd.DataFrame) -> pd.DataFrame:
    """For each trade, re-walk bars from entry to exit and compute
    full MFE + MAE. Adds columns to a copy of trades."""
    bars = bars_1m.reset_index(drop=False)
    opens = bars["open"].values
    highs = bars["high"].values
    lows = bars["low"].values
    n_bars = len(bars)

    out = trades.copy()
    eidx = out["entry_idx"].astype(int).values
    xidx = out["exit_idx"].astype(int).values
    d = out["direction"].astype(int).values
    ep = out["entry_price"].astype(float).values

    n = len(out)
    mfe = np.zeros(n)
    mae = np.zeros(n)
    bars_to_max_mfe = np.zeros(n, dtype=int)
    bars_to_max_mae = np.zeros(n, dtype=int)
    mfe_pre_max_mae = np.zeros(n)
    mae_pre_max_mfe = np.zeros(n)

    for i in range(n):
        ei = eidx[i]
        xi = min(xidx[i], n_bars - 1)
        if xi < ei:
            continue
        max_mfe_i = 0.0
        max_mae_i = 0.0
        bar_max_mfe = 0
        bar_max_mae = 0
        # Track MFE-before-MAE-peak and MAE-before-MFE-peak
        mfe_seen_so_far = 0.0
        mae_seen_so_far = 0.0
        for k, j in enumerate(range(ei, xi + 1)):
            h = highs[j]; l = lows[j]
            if d[i] == 1:
                fav = h - ep[i]
                adv = ep[i] - l
            else:
                fav = ep[i] - l
                adv = h - ep[i]
            if fav > max_mfe_i:
                max_mfe_i = fav
                bar_max_mfe = k
                mae_pre_max_mfe[i] = mae_seen_so_far
            if adv > max_mae_i:
                max_mae_i = adv
                bar_max_mae = k
                mfe_pre_max_mae[i] = mfe_seen_so_far
            mfe_seen_so_far = max(mfe_seen_so_far, fav)
            mae_seen_so_far = max(mae_seen_so_far, adv)
        mfe[i] = max_mfe_i
        mae[i] = max_mae_i
        bars_to_max_mfe[i] = bar_max_mfe
        bars_to_max_mae[i] = bar_max_mae

    out["full_mfe_pts"] = mfe
    out["full_mae_pts"] = mae  # this should match existing mae_pts
    out["bars_to_max_mfe"] = bars_to_max_mfe
    out["bars_to_max_mae"] = bars_to_max_mae
    out["mfe_pre_max_mae_pts"] = mfe_pre_max_mae
    out["mae_pre_max_mfe_pts"] = mae_pre_max_mfe
    out["mfe_to_mae_ratio"] = np.where(
        mae > 0, mfe / mae, np.nan)
    return out


def stats_block(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0: return {"n": 0}
    mfe = df["full_mfe_pts"]
    mae = df["full_mae_pts"]
    ratio = df["mfe_to_mae_ratio"].dropna()
    out = {
        "n": n,
        "mfe_p50": float(np.percentile(mfe, 50)),
        "mfe_p75": float(np.percentile(mfe, 75)),
        "mfe_p90": float(np.percentile(mfe, 90)),
        "mfe_p95": float(np.percentile(mfe, 95)),
        "mfe_max": float(mfe.max()),
        "mfe_mean": float(mfe.mean()),
        "mae_p50": float(np.percentile(mae, 50)),
        "mae_p90": float(np.percentile(mae, 90)),
        "mae_p95": float(np.percentile(mae, 95)),
        "mae_mean": float(mae.mean()),
        "mfe_mae_ratio_p50": float(ratio.median()) if len(ratio) else float("nan"),
        "mfe_mae_ratio_mean": float(ratio.mean()) if len(ratio) else float("nan"),
    }
    # MFE thresholds: % of trades with MFE >= X
    for X in MFE_THRESHOLDS_PTS:
        out[f"pct_mfe_ge_{X}pt"] = float((mfe >= X).mean())
    return out


def aggregate(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    iter_obj = (df.groupby(group_cols, observed=True)
                  if group_cols else [(("ALL",), df)])
    for keys, g in iter_obj:
        if not isinstance(keys, tuple): keys = (keys,)
        s = stats_block(g)
        row = dict(zip(group_cols if group_cols else ["scope"],
                            keys))
        row.update(s)
        rows.append(row)
    return pd.DataFrame(rows)


def fmt_p(v):
    if v is None or pd.isna(v): return "—"
    return f"{100*v:.1f}%"


def fmt_f(v, dp=2):
    if v is None or pd.isna(v): return "—"
    return f"{v:.{dp}f}"


def write_report(losers, timeouts, agg_loser_overall,
                       agg_to_overall, agg_loser_pair_session,
                       agg_to_pair_session):
    L = []
    L.append("# Loser & Timeout Anatomy "
              "— Level Momentum Study\n")
    L.append(f"Source: `{SOURCE}` | "
              f"Losers n={len(losers):,}, "
              f"Timeouts n={len(timeouts):,}\n")
    L.append("## Method\n")
    L.append(
        "For each LOSER (outcome='loss', stopped at original "
        "'one prior in sequence' stop) and each TIMEOUT "
        "(outcome='timed_out'), re-walk all bars from entry to "
        "exit and compute:\n"
        "- **MFE** (max favorable excursion): the best the trade "
        "ever was, in trade direction.\n"
        "- **MAE** (max adverse excursion): the worst it ever was. "
        "For losers this should ≈ original stop distance.\n"
        "- **mfe/mae ratio**: did the trade ever look like a "
        "winner before reversing?\n"
        "- **% with MFE ≥ X**: how often did losers reach X pts "
        "favorable at any point during the trade?\n")

    # Overall losers
    r = agg_loser_overall.iloc[0]
    L.append("## Losers — overall\n")
    L.append(f"- n = {int(r['n']):,}")
    L.append(f"- MFE: mean={r['mfe_mean']:.2f}, "
              f"p50={r['mfe_p50']:.2f}, p75={r['mfe_p75']:.2f}, "
              f"p90={r['mfe_p90']:.2f}, p95={r['mfe_p95']:.2f}, "
              f"max={r['mfe_max']:.2f}")
    L.append(f"- MAE: mean={r['mae_mean']:.2f}, "
              f"p50={r['mae_p50']:.2f}, p90={r['mae_p90']:.2f}, "
              f"p95={r['mae_p95']:.2f}")
    L.append(f"- MFE/MAE ratio: median="
              f"{r['mfe_mae_ratio_p50']:.3f}, "
              f"mean={r['mfe_mae_ratio_mean']:.3f}")
    L.append(f"- % of losers with MFE >= threshold:")
    for X in MFE_THRESHOLDS_PTS:
        L.append(f"  - >= {X} pt: "
                  f"{fmt_p(r[f'pct_mfe_ge_{X}pt'])}")
    L.append("")

    # Overall timeouts
    if len(timeouts):
        rt = agg_to_overall.iloc[0]
        L.append("## Timeouts — overall\n")
        L.append(f"- n = {int(rt['n']):,}")
        L.append(f"- MFE: mean={rt['mfe_mean']:.2f}, "
                  f"p50={rt['mfe_p50']:.2f}, p90={rt['mfe_p90']:.2f}, "
                  f"p95={rt['mfe_p95']:.2f}, max={rt['mfe_max']:.2f}")
        L.append(f"- MAE: mean={rt['mae_mean']:.2f}, "
                  f"p50={rt['mae_p50']:.2f}, p90={rt['mae_p90']:.2f}, "
                  f"p95={rt['mae_p95']:.2f}")
        L.append(f"- MFE/MAE ratio: median="
                  f"{rt['mfe_mae_ratio_p50']:.3f}, "
                  f"mean={rt['mfe_mae_ratio_mean']:.3f}")
        L.append(f"- % of timeouts with MFE >= threshold:")
        for X in MFE_THRESHOLDS_PTS:
            L.append(f"  - >= {X} pt: "
                      f"{fmt_p(rt[f'pct_mfe_ge_{X}pt'])}")
        L.append("")

    # Losers by pair × session
    L.append("## Losers — by pair × session\n")
    L.append("| Pair | Session | n | MFE p50 | p75 | p90 | "
             "p95 | MFE mean | MAE mean | "
             "MFE/MAE | %MFE≥5 | %MFE≥10 | %MFE≥15 |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in agg_loser_pair_session.sort_values(
            ["level_pair", "entry_session"]).iterrows():
        L.append(
            f"| {r['level_pair']} | {r['entry_session']} | "
            f"{int(r['n']):,} | "
            f"{r['mfe_p50']:.2f} | {r['mfe_p75']:.2f} | "
            f"{r['mfe_p90']:.2f} | {r['mfe_p95']:.2f} | "
            f"{r['mfe_mean']:.2f} | {r['mae_mean']:.2f} | "
            f"{r['mfe_mae_ratio_mean']:.3f} | "
            f"{fmt_p(r['pct_mfe_ge_5.0pt'])} | "
            f"{fmt_p(r['pct_mfe_ge_10.0pt'])} | "
            f"{fmt_p(r['pct_mfe_ge_15.0pt'])} |")
    L.append("")

    # Timeouts by pair × session (if any)
    if len(agg_to_pair_session):
        L.append("## Timeouts — by pair × session "
                  "(non-empty cells)\n")
        L.append("| Pair | Session | n | MFE p50 | p75 | p90 | "
                 "MFE mean | MAE mean | MFE/MAE | %MFE≥5 | "
                 "%MFE≥10 | %MFE≥15 |")
        L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for _, r in agg_to_pair_session.sort_values(
                ["level_pair", "entry_session"]).iterrows():
            if r["n"] < 50: continue  # skip tiny cells
            L.append(
                f"| {r['level_pair']} | {r['entry_session']} | "
                f"{int(r['n']):,} | "
                f"{r['mfe_p50']:.2f} | {r['mfe_p75']:.2f} | "
                f"{r['mfe_p90']:.2f} | "
                f"{r['mfe_mean']:.2f} | {r['mae_mean']:.2f} | "
                f"{r['mfe_mae_ratio_mean']:.3f} | "
                f"{fmt_p(r['pct_mfe_ge_5.0pt'])} | "
                f"{fmt_p(r['pct_mfe_ge_10.0pt'])} | "
                f"{fmt_p(r['pct_mfe_ge_15.0pt'])} |")
        L.append("")

    L.append("## Interpretation guide\n")
    L.append(
        "- **High MFE losers** = trades that DID move in our favor "
        "before reversing. A move-to-BE or trailing stop could "
        "have saved many. Pairs with high `%MFE≥5pt` for losers "
        "are candidates for breakeven-stop rules.\n"
        "- **Low MFE losers** = trades that immediately went "
        "against us. The entry signal was wrong. No exit rule "
        "saves these.\n"
        "- **MFE/MAE ratio < 0.5** = losers were never close to "
        "their target. Tightening stop helps; can't 'save' these "
        "with a partial exit.\n"
        "- **MFE/MAE ratio > 0.7** = losers got fairly close to "
        "winning. A trailing stop or move-to-BE after MFE = X is "
        "worth testing.\n")

    p = OUT / "report_loser_anatomy.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    print(f"Loading {SOURCE}...")
    trades = pd.read_csv(SOURCE)
    print(f"  {len(trades):,} trades")
    losers = trades[trades["outcome"] == "loss"].copy()
    timeouts = trades[trades["outcome"] == "timed_out"].copy()
    print(f"  losers: {len(losers):,}")
    print(f"  timeouts: {len(timeouts):,}")

    print("Reloading bars...")
    bars_1s = load_v0_1s(V0_PARQUET)
    bars_1m = resample_1s_to_1m(bars_1s)
    bars_1m = annotate_sessions_ct(bars_1m)

    print("Computing MFE/MAE for losers...")
    losers = compute_loser_mfe_mae(losers, bars_1m)
    print("Computing MFE/MAE for timeouts...")
    timeouts = compute_loser_mfe_mae(timeouts, bars_1m)

    losers.to_csv(OUT / "losers_with_full_mfe_mae.csv",
                       index=False)
    timeouts.to_csv(OUT / "timeouts_with_full_mfe_mae.csv",
                          index=False)

    print("Aggregating...")
    agg_loser_ovr = aggregate(losers, [])
    agg_to_ovr = aggregate(timeouts, [])
    agg_loser_ps = aggregate(
        losers, ["level_pair", "entry_session"])
    agg_to_ps = aggregate(
        timeouts, ["level_pair", "entry_session"])

    agg_loser_ovr.to_csv(
        OUT / "loser_anatomy_overall.csv", index=False)
    agg_to_ovr.to_csv(
        OUT / "timeout_anatomy_overall.csv", index=False)
    agg_loser_ps.to_csv(
        OUT / "loser_anatomy_pair_session.csv", index=False)
    agg_to_ps.to_csv(
        OUT / "timeout_anatomy_pair_session.csv", index=False)

    print("Writing report...")
    rp = write_report(
        losers, timeouts, agg_loser_ovr, agg_to_ovr,
        agg_loser_ps, agg_to_ps)
    print(f"Report: {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
