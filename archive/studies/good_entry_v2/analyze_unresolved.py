"""Investigate 'unresolved' bracket rows and compare fallback rules.

An unresolved bracket row = trade filled, but neither PT nor SL touched
during the tracker's observable window [fill_time, regime_exit_time or
fill_time+1800s, whichever earlier].

Three fallback rules for unresolved rows:
  A. Regime-exit fallback (current) — exit at `regime_exit_price`
     when the 1m regime flips. Uses `regime_exit_pnl_dollars` directly.
  B. Commission-only — assume trader closes flat at some unspecified
     time. PnL = -$5 (commission only). Pessimistic.
  C. "Bracket never resolves" treated as 0 PnL before commission
     (PnL = -$5). Equivalent to B but named differently for clarity.

Rule A bakes in an assumption: the trader actively monitors regime
flips and closes at the regime_exit_price. Rule B assumes the trader
closes at the entry price (roughly equivalent to a time-stop at entry
which doesn't make sense — this is a worst-case floor).

The honest comparison is A vs "ignore unresolved entirely" (exclude
them and see what the resolved-bracket economics look like).
"""

from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

NQ_MULT = 20.0
COMMISSION = 5.0


def bracket_pnl_regime_fallback(df: pd.DataFrame) -> pd.Series:
    """Current rule: use regime_exit_pnl_dollars for unresolved."""
    pt = df["pt100_before_sl100"].values
    atr = df["atr_at_signal"].values
    regime_pnl = df["regime_exit_pnl_dollars"].values
    out = np.empty(len(df), dtype=float)
    for i in range(len(df)):
        v = pt[i]
        if pd.isna(v):
            out[i] = regime_pnl[i]
        elif v == 1:
            out[i] = atr[i] * NQ_MULT - COMMISSION
        else:
            out[i] = -atr[i] * NQ_MULT - COMMISSION
    return pd.Series(out, index=df.index)


def bracket_pnl_commission_only(df: pd.DataFrame) -> pd.Series:
    """Pessimistic: unresolved treated as flat (commission only)."""
    pt = df["pt100_before_sl100"].values
    atr = df["atr_at_signal"].values
    out = np.empty(len(df), dtype=float)
    for i in range(len(df)):
        v = pt[i]
        if pd.isna(v):
            out[i] = -COMMISSION
        elif v == 1:
            out[i] = atr[i] * NQ_MULT - COMMISSION
        else:
            out[i] = -atr[i] * NQ_MULT - COMMISSION
    return pd.Series(out, index=df.index)


def risk(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    sorted_s = s.sort_values()
    k = int(len(s) * 0.05)
    trimmed = (sorted_s.iloc[k:len(s) - k].mean()
                if k * 2 < len(s) else float("nan"))
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed_5pct": float(trimmed),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0 else float("inf")),
    }


def _d(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions",
                     default="studies/good_entry_v2/results/"
                              "phase3_oos_predictions_huber.parquet")
    ap.add_argument("--out",
                     default="studies/good_entry_v2/results/"
                              "UNRESOLVED_REPORT.md")
    args = ap.parse_args()

    df = pd.read_parquet(args.predictions)
    df = df.copy()

    # Classify each row
    pt = df["pt100_before_sl100"]
    df["bracket_status"] = np.where(
        pt.isna(), "unresolved",
        np.where(pt == 1, "pt_hit", "sl_hit"))

    # Event duration bucket
    # regime_exit_time isn't in prediction file; reconstruct from
    # cohort if needed. For now use a proxy: we can compute
    # regime_exit_time_s from the labels parquet — but we don't have
    # it here. Skip for phase 1, use checkpoint_s as rough proxy.

    # --- Compute both rules ---
    df["pnl_A_regime"] = bracket_pnl_regime_fallback(df)
    df["pnl_B_commission"] = bracket_pnl_commission_only(df)

    lines: list[str] = []
    lines.append("# Unresolved Bracket Investigation")
    lines.append("")

    # Status mix
    status_mix = df["bracket_status"].value_counts()
    lines.append("## Bracket resolution mix (all RTH OOS 2025)")
    lines.append("")
    lines.append("| Status | n | % |")
    lines.append("|---|--:|--:|")
    for s, n in status_mix.items():
        lines.append(f"| {s} | {n:,} | {100 * n / len(df):.1f}% |")
    lines.append("")

    # What does regime_exit_pnl look like on unresolved rows?
    unres = df[df["bracket_status"] == "unresolved"]
    res = df[df["bracket_status"] != "unresolved"]
    lines.append("## regime_exit PnL profile of unresolved rows")
    lines.append("")
    r_unres = risk(unres["regime_exit_pnl_dollars"])
    r_res = risk(res["regime_exit_pnl_dollars"])
    lines.append("| Subset | n | Mean $ | Median $ | Trim 5% | "
                  "Win% | PF |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    lines.append(
        f"| Unresolved bracket | {r_unres['n']:,} | "
        f"{_d(r_unres['mean'])} | {_d(r_unres['median'])} | "
        f"{_d(r_unres['trimmed_5pct'])} | "
        f"{_p(r_unres['win_rate'])} | {r_unres['pf']:.2f} |")
    lines.append(
        f"| Resolved (PT or SL) | {r_res['n']:,} | "
        f"{_d(r_res['mean'])} | {_d(r_res['median'])} | "
        f"{_d(r_res['trimmed_5pct'])} | "
        f"{_p(r_res['win_rate'])} | {r_res['pf']:.2f} |")
    lines.append("")
    lines.append(
        "**Interpretation**: unresolved rows by definition never saw "
        "price move ±1 ATR from entry before the event terminated. "
        "Their regime-exit PnL reflects the small end-of-event drift "
        "(much smaller in absolute terms than a resolved ±1 ATR outcome).")
    lines.append("")

    # --- Compare bracket results under both rules ---
    for label, subset in [
        ("ALL RTH", df),
        ("top 10% (all RTH, by score)",
         df.sort_values("score", ascending=False).head(
             int(0.10 * len(df)))),
        ("RTH-Short top-10%",
         df[df["signal_direction"] == -1]
           .sort_values("score", ascending=False).head(
             int(0.10 * (df["signal_direction"] == -1).sum()))),
        ("RTH-Short 180-300s top-10%",
         df[(df["signal_direction"] == -1)
             & (df["checkpoint_s"] >= 180)
             & (df["checkpoint_s"] < 300)]
           .sort_values("score", ascending=False).head(
             int(0.10 * ((df["signal_direction"] == -1)
                          & (df["checkpoint_s"] >= 180)
                          & (df["checkpoint_s"] < 300)).sum()))),
    ]:
        lines.append(f"## {label}: A vs B fallback comparison")
        lines.append("")
        n_unres = (subset["bracket_status"] == "unresolved").sum()
        lines.append(
            f"- n={len(subset):,}, unresolved={n_unres:,} "
            f"({100*n_unres/len(subset):.1f}% of this cut)")
        lines.append("")
        lines.append("| Rule | n | Mean $ | Median $ | Trim 5% | "
                      "Win% | PF | Total $ |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        for rule_name, col in [
            ("A: regime-exit fallback (current)", "pnl_A_regime"),
            ("B: commission-only (pessimistic)", "pnl_B_commission"),
        ]:
            rr = risk(subset[col])
            lines.append(
                f"| {rule_name} | {rr['n']:,} | "
                f"{_d(rr['mean'])} | {_d(rr['median'])} | "
                f"{_d(rr['trimmed_5pct'])} | "
                f"{_p(rr['win_rate'])} | {rr['pf']:.2f} | "
                f"{_d(rr['sum'])} |")
        # Also: resolved-only (drop unresolved entirely)
        resolved_only = subset[subset["bracket_status"] != "unresolved"]
        rr = risk(resolved_only["pnl_A_regime"])  # A == B for resolved
        lines.append(
            f"| C: resolved-only (drop unresolved) | "
            f"{rr['n']:,} | "
            f"{_d(rr['mean'])} | {_d(rr['median'])} | "
            f"{_d(rr['trimmed_5pct'])} | "
            f"{_p(rr['win_rate'])} | {rr['pf']:.2f} | "
            f"{_d(rr['sum'])} |")
        lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
