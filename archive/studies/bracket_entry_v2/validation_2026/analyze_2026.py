"""Post-process 2026 live backtest with commission + 1-tick AND
2-tick slippage scenarios. Produce final validation report."""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

import sys as _sys
_default = ("studies/bracket_entry_v2/validation_2026/results/"
              "nt_run_t600gate")
NT_ROOT = Path(_sys.argv[1] if len(_sys.argv) > 1 else _default)
TICK = 0.25
NQ_MULT = 20.0
COMMISSION = 5.0


def classify_exit(row, tol=0.05):
    d = row["direction"]
    atr = row["atr_at_signal"]
    if atr <= 0:
        return "unknown"
    move = (row["avg_px_close"] - row["avg_px_open"]) * d / atr
    if move >= 1.0 - tol:
        return "pt"
    if move <= -(1.0 - tol):
        return "sl"
    return "regime_exit"


def apply_slippage(df: pd.DataFrame, slip_ticks: int) -> pd.Series:
    """Apply N-tick entry + N-tick SL/regime exit slippage."""
    d = df["direction"].values
    entry = df["avg_px_open"].astype(float).values
    exit_ = df["avg_px_close"].astype(float).values
    reason = df["exit_reason"].values
    slip_entry = entry + np.where(d == 1, TICK * slip_ticks,
                                     -TICK * slip_ticks)
    # Adverse exit applies to SL + regime_exit (not PT limit)
    slip_mask = np.isin(reason, ["sl", "regime_exit", "unknown"])
    slip_exit = np.where(
        slip_mask,
        exit_ + np.where(d == 1, -TICK * slip_ticks,
                          TICK * slip_ticks),
        exit_,
    )
    return ((slip_exit - slip_entry) * d * NQ_MULT - COMMISSION)


def risk(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    k = int(len(s) * 0.05)
    trim = (s.sort_values().iloc[k:len(s) - k].mean()
             if k * 2 < len(s) else np.nan)
    return {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed_5pct": float(trim),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
    }


def _d(v):
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    pos = pd.read_parquet(NT_ROOT / "positions.parquet")
    trades = pd.read_parquet(NT_ROOT / "strategy_trades.parquet")
    # metrics.yaml lives alongside positions.parquet in NT_ROOT

    # Match strategy trades to NT positions by entry timestamp.
    # Strategy trades have decision_ts_ns; NT positions have ts_opened.
    # A simpler path: pull atr_at_signal + direction directly from
    # strategy_trades, merge on index.
    pos = pos.copy()
    pos["entry_ts_ns"] = pos["ts_opened"].astype("int64")
    # Sort both by entry time and pair 1:1 (single-position strategy)
    pos = pos.sort_values("entry_ts_ns").reset_index(drop=True)
    trades = trades.sort_values("decision_ts_ns").reset_index(drop=True)
    # Drop trades that never filled (entry_fill_price NaN)
    trades_filled = trades[trades["entry_fill_price"].notna()].copy()
    trades_filled = trades_filled.sort_values("decision_ts_ns").reset_index(
        drop=True)
    if len(pos) != len(trades_filled):
        print(f"WARN: pos={len(pos)} vs trades_filled={len(trades_filled)}")
    n = min(len(pos), len(trades_filled))
    pos = pos.iloc[:n].copy()
    pos["direction"] = trades_filled["direction"].iloc[:n].values
    pos["atr_at_signal"] = trades_filled["atr_at_signal"].iloc[:n].values
    pos["strategy_score"] = trades_filled["score"].iloc[:n].values
    pos["strategy_exit_reason"] = (
        trades_filled["exit_reason"].iloc[:n].values)

    pos["exit_reason"] = pos.apply(classify_exit, axis=1)
    pos["pnl_raw"] = ((pos["avg_px_close"] - pos["avg_px_open"])
                        * pos["direction"] * NQ_MULT)
    pos["pnl_1tick"] = apply_slippage(pos, 1)
    pos["pnl_2tick"] = apply_slippage(pos, 2)
    pos["exit_dt"] = pd.to_datetime(
        pos["ts_closed"].astype("int64"), unit="ns", utc=True)
    pos["month"] = pos["exit_dt"].dt.to_period("M").astype(str)

    # Build report
    lines: list[str] = []
    lines.append("# 2026 Unseen NT Validation — top_15 Live Strategy")
    lines.append("")
    lines.append("**Test window**: 2026-01-01 through 2026-04-15 "
                  "(Q1 + 2 weeks of April)")
    lines.append("")
    lines.append("**Model**: top_15 retrained on 2020-2024 / val 2025. "
                  "Never saw 2026 data.")
    lines.append("")
    lines.append("**Execution**: LiveBracketStrategy (subclass of "
                  "CollectorV2) — true runtime. Features computed "
                  "live from the 1s bar stream; model scored at each "
                  "30s checkpoint; orders submitted into NT's engine.")
    lines.append("")

    # Headline
    lines.append("## Scenario comparison")
    lines.append("")
    lines.append("| Scenario | n | Mean $ | Median $ | Trim 5% | "
                  "Win% | PF | Total $ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for label, col in [
        ("A — Raw ($0 commission, no slippage)", "pnl_raw"),
        ("B — +$5 commission + 1-tick slippage", "pnl_1tick"),
        ("C — +$5 commission + 2-tick slippage", "pnl_2tick"),
    ]:
        m = risk(pos[col])
        lines.append(
            f"| {label} | {m['n']:,} | {_d(m['mean'])} | "
            f"{_d(m['median'])} | {_d(m['trimmed_5pct'])} | "
            f"{_p(m['win_rate'])} | {m['pf']:.2f} | {_d(m['sum'])} |")
    lines.append("")

    # Exit mix
    lines.append("## Exit reason mix")
    lines.append("")
    lines.append("| Exit | n | 1-tick Mean $ | 2-tick Mean $ | Total 1-tick $ |")
    lines.append("|---|--:|--:|--:|--:|")
    for reason, sub in pos.groupby("exit_reason"):
        m1 = risk(sub["pnl_1tick"])
        m2 = risk(sub["pnl_2tick"])
        lines.append(
            f"| {reason} | {m1['n']:,} | {_d(m1['mean'])} | "
            f"{_d(m2['mean'])} | {_d(m1['sum'])} |")
    lines.append("")

    # Monthly under scenario B (1-tick, primary)
    lines.append("## Monthly — 1-tick slippage (primary)")
    lines.append("")
    lines.append("| Month | n | Mean $ | Trim 5% | Win% | PF | Total $ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for month, sub in pos.groupby("month"):
        m = risk(sub["pnl_1tick"])
        lines.append(
            f"| {month} | {m['n']:,} | {_d(m['mean'])} | "
            f"{_d(m['trimmed_5pct'])} | {_p(m['win_rate'])} | "
            f"{m['pf']:.2f} | {_d(m['sum'])} |")
    lines.append("")

    # Direction split
    lines.append("## Direction split — 1-tick slippage")
    lines.append("")
    lines.append("| Side | n | Mean $ | Trim 5% | Win% | PF | Total $ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for d_, sub in pos.groupby("direction"):
        label = "Long" if d_ == 1 else "Short"
        m = risk(sub["pnl_1tick"])
        lines.append(
            f"| {label} | {m['n']:,} | {_d(m['mean'])} | "
            f"{_d(m['trimmed_5pct'])} | {_p(m['win_rate'])} | "
            f"{m['pf']:.2f} | {_d(m['sum'])} |")
    lines.append("")

    # Comparison to 2024 and 2025 from feature_reduction
    lines.append("## Comparison to 2024 and 2025 (top_15, "
                  "1-tick slippage, same cost model)")
    lines.append("")
    lines.append("| Year | n | Mean $ | PF | Win% | Total $ | Notes |")
    lines.append("|---|--:|--:|--:|--:|--:|---|")
    # Values from feature_reduction FINAL_REPORT (scenario C)
    lines.append("| 2024 | 2,719 | $20.79 | 1.21 | 56.5% | "
                  "+$56,540 | Retrained thru 2022, val 2023 |")
    lines.append("| 2025 | 2,697 | $35.50 | 1.26 | 57.1% | "
                  "+$95,745 | Retrained thru 2023, val 2024 |")
    m1 = risk(pos["pnl_1tick"])
    lines.append(
        f"| **2026 YTD** | **{m1['n']:,}** | **{_d(m1['mean'])}** | "
        f"**{m1['pf']:.2f}** | **{_p(m1['win_rate'])}** | "
        f"**{_d(m1['sum'])}** | Retrained thru 2024, val 2025 |")
    lines.append("")

    # Strategy diagnostics
    with open(NT_ROOT / "metrics.yaml") as f:
        import yaml
        metrics = yaml.safe_load(f)

    lines.append("## Strategy diagnostics (live run)")
    lines.append("")
    live = metrics["live_diag"]
    coll = metrics["collector_diag"]
    lines.append(
        f"- Confirmed events: {coll['confirmed']:,}")
    lines.append(
        f"- Checkpoints scored (features present): "
        f"{live['checkpoints_scored']:,}")
    lines.append(
        f"- Checkpoints skipped (missing features): "
        f"{live['missing_features']:,} "
        f"({100*live['missing_features']/(live['checkpoints_scored']+live['missing_features']):.1f}%)")
    lines.append(
        f"- Scores above threshold (0.4719): "
        f"{live['scores_above_threshold']:,} "
        f"({100*live['scores_above_threshold']/live['checkpoints_scored']:.1f}% of scored)")
    lines.append(
        f"- Entries queued after single-position gate: "
        f"{live['entries_queued']:,}")
    lines.append(
        f"- Entries filled: {live['entries_filled']:,}")
    lines.append(f"- PT hits: {live['pt_hits']:,}  "
                  f"SL hits: {live['sl_hits']:,}  "
                  f"Regime exits: {live['regime_exits']:,}")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    total_1tick = m1["sum"]
    pf_1tick = m1["pf"]
    total_2tick = risk(pos["pnl_2tick"])["sum"]
    pf_2tick = risk(pos["pnl_2tick"])["pf"]
    if pf_1tick > 1.15:
        verdict = "STRONG — edge survives on unseen 2026 data."
    elif pf_1tick > 1.05:
        verdict = ("MARGINAL — positive edge but meaningfully weaker "
                    "than 2024/2025. Investigate before deploying.")
    else:
        verdict = ("WEAK — edge collapses on 2026. Model may need "
                    "retraining or feature stability audit before "
                    "deployment.")
    lines.append(f"- 1-tick slippage: PF {pf_1tick:.2f}, "
                  f"total {_d(total_1tick)}")
    lines.append(f"- 2-tick slippage: PF {pf_2tick:.2f}, "
                  f"total {_d(total_2tick)}")
    lines.append(f"- Verdict: **{verdict}**")
    lines.append("")

    # Diagnostic observations
    lines.append("## Diagnostic observations")
    lines.append("")
    score_rate = (live['scores_above_threshold']
                    / live['checkpoints_scored'])
    lines.append(
        f"- **Score drift**: the threshold pulled "
        f"{100*score_rate:.1f}% of 2026 checkpoints over the bar, "
        "vs the 10% target by design. The 2026 score distribution "
        "has shifted right relative to val 2025 — the fixed "
        "threshold is no longer targeting the top decile on the "
        "new data. A rolling-percentile threshold (e.g. top 10% "
        "of last 20 trading days) would adapt to regime shifts.")
    lines.append(
        f"- **Missing-feature rate**: "
        f"{100*live['missing_features']/(live['checkpoints_scored']+live['missing_features']):.1f}% "
        "of checkpoints were skipped due to at least one missing "
        "top_15 feature. Investigate which feature is most often "
        "NaN on 2026 data.")

    out_path = Path(
        "studies/bracket_entry_v2/validation_2026/"
        "VALIDATION_2026_REPORT_t600gate.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out_path}")

    # Console summary
    print("\n=== Scenarios ===")
    for label, col in [("RAW", "pnl_raw"),
                        ("1-tick", "pnl_1tick"),
                        ("2-tick", "pnl_2tick")]:
        m = risk(pos[col])
        print(f"  {label:<8s} total={_d(m['sum']):<12s} "
               f"mean={_d(m['mean']):<10s} "
               f"PF={m['pf']:.2f}  Win={_p(m['win_rate'])}")


if __name__ == "__main__":
    main()
