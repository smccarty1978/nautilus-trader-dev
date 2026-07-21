"""Quick check: apply the Phase 3 Huber model's score-ranking to a
PT/SL = 1 ATR / 1 ATR bracket instead of hold-to-flip.

Per-row bracket PnL (dollars):
  pt100 == 1  →  +1.0 ATR × atr_at_signal × NQ_MULT − COMMISSION
  pt100 == 0  →  −1.0 ATR × atr_at_signal × NQ_MULT − COMMISSION
  pt100 NaN   →  bracket did not resolve before event termination.
                 Fallback: use regime_exit_pnl_dollars (trader exits
                 at regime flip — which is what live bracket traders
                 do when they also cancel-on-regime-flip). Commission
                 is already baked into regime_exit_pnl_dollars.

No retraining — just score-based bucketing on the existing predictions.
"""

from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NQ_MULT = 20.0
COMMISSION = 5.0


def compute_bracket_pnl(df: pd.DataFrame) -> pd.Series:
    """Return a Series of per-row bracket PnL in dollars."""
    pt = df["pt100_before_sl100"].values
    atr = df["atr_at_signal"].values
    regime_pnl = df["regime_exit_pnl_dollars"].values
    out = np.empty(len(df), dtype=float)
    for i in range(len(df)):
        v = pt[i]
        if pd.isna(v):
            out[i] = regime_pnl[i]  # already includes commission
        elif v == 1:
            out[i] = atr[i] * NQ_MULT - COMMISSION
        else:
            out[i] = -atr[i] * NQ_MULT - COMMISSION
    return pd.Series(out, index=df.index, name="bracket_pnl")


def risk(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    sorted_s = s.sort_values()
    trim_k = int(len(s) * 0.05)
    trimmed = (sorted_s.iloc[trim_k:len(s) - trim_k].mean()
                if trim_k * 2 < len(s) else float("nan"))
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed_5pct": float(trimmed),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "avg_winner": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loser": float(losses.mean()) if len(losses) else float("nan"),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0 else float("inf")),
    }


def _d(v) -> str:
    if v is None or pd.isna(v) or (isinstance(v, float) and np.isinf(v)):
        return "—" if pd.isna(v) else "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def format_row(label: str, r: dict) -> str:
    return (f"| {label} | {r['n']:,} | "
             f"{_d(r['mean'])} | {_d(r['median'])} | "
             f"{_d(r['trimmed_5pct'])} | {_p(r['win_rate'])} | "
             f"{_d(r['avg_winner'])} | {_d(r['avg_loser'])} | "
             f"{r['pf']:.2f} | {_d(r['sum'])} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions",
                     default="studies/good_entry_v2/results/"
                              "phase3_oos_predictions_huber.parquet")
    ap.add_argument("--out",
                     default="studies/good_entry_v2/results/"
                              "BRACKET_REPORT.md")
    args = ap.parse_args()

    print(f"Loading: {args.predictions}")
    df = pd.read_parquet(args.predictions)
    print(f"  {len(df):,} rows, "
           f"{df['event_id'].nunique():,} events")

    # Attach bracket PnL
    df = df.copy()
    df["bracket_pnl"] = compute_bracket_pnl(df)

    # Resolution summary
    pt_hits = int((df["pt100_before_sl100"] == 1).sum())
    sl_hits = int((df["pt100_before_sl100"] == 0).sum())
    unresolved = int(df["pt100_before_sl100"].isna().sum())
    print(f"  PT hits: {pt_hits:,}  SL hits: {sl_hits:,}  "
           f"Unresolved (fallback to regime-exit): {unresolved:,}")

    lines: list[str] = []
    lines.append("# Good Entry v2 — Bracket Check (PT/SL = 1 ATR / 1 ATR)")
    lines.append("")
    lines.append(f"Source: `{args.predictions}`")
    lines.append(f"- Rows: {len(df):,}")
    lines.append(f"- Events: {df['event_id'].nunique():,}")
    lines.append(f"- PT hits: {pt_hits:,}  /  SL hits: {sl_hits:,}  "
                  f"/  Unresolved: {unresolved:,} "
                  f"({100*unresolved/len(df):.1f}%)")
    lines.append("- Unresolved rows fall back to `regime_exit_pnl_dollars`")
    lines.append(f"- Commission: -${COMMISSION}/trade (already in both"
                  " bracket and regime-exit paths)")
    lines.append("")

    header = ("| Cut | n | Mean $ | Median $ | Trim 5% | Win% | "
                "Avg win $ | Avg loss $ | PF | Total $ |")
    divider = "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"

    # ===== Decile table =====
    lines.append("## Decile-by-decile (by model score, RTH OOS)")
    lines.append("")
    lines.append(header)
    lines.append(divider)
    df_sorted = df.sort_values("score").reset_index(drop=True)
    df_sorted["bucket"] = pd.qcut(
        df_sorted["score"].rank(method="first"),
        q=10, labels=False)
    for b in range(10):
        sub = df_sorted[df_sorted["bucket"] == b]
        r = risk(sub["bracket_pnl"])
        lines.append(format_row(f"D{b}", r))
    lines.append("")

    # ===== Top-k buckets =====
    lines.append("## Top-k economics (by score, RTH OOS)")
    lines.append("")
    lines.append(header)
    lines.append(divider)
    lines.append(format_row("ALL", risk(df["bracket_pnl"])))
    for frac in [0.30, 0.20, 0.10, 0.05]:
        n = int(round(frac * len(df)))
        top = df.sort_values("score", ascending=False).head(n)
        lines.append(format_row(f"top {int(frac*100)}%",
                                  risk(top["bracket_pnl"])))
    lines.append("")

    # ===== Long vs Short =====
    lines.append("## RTH-Long vs RTH-Short (top-10%)")
    lines.append("")
    lines.append(header)
    lines.append(divider)
    for label, mask in [
        ("RTH-Long ALL",
         df["signal_direction"] == 1),
        ("RTH-Long top-10%",
         None),  # placeholder
        ("RTH-Short ALL",
         df["signal_direction"] == -1),
        ("RTH-Short top-10%",
         None),
    ]:
        if mask is not None:
            sub = df[mask]
            lines.append(format_row(label, risk(sub["bracket_pnl"])))
        else:
            if "Long" in label:
                sub = df[df["signal_direction"] == 1]
            else:
                sub = df[df["signal_direction"] == -1]
            top = sub.sort_values("score", ascending=False).head(
                int(round(0.10 * len(sub))))
            lines.append(format_row(label, risk(top["bracket_pnl"])))
    lines.append("")

    # ===== T buckets =====
    lines.append("## Top-10% by T bucket (within first 600s)")
    lines.append("")
    lines.append(header)
    lines.append(divider)
    for lo, hi, lbl in [
        (0, 90, "0-90s"), (90, 180, "90-180s"),
        (180, 300, "180-300s"), (300, 450, "300-450s"),
        (450, 601, "450-600s"),
    ]:
        sub = df[(df["checkpoint_s"] >= lo)
                  & (df["checkpoint_s"] < hi)]
        if len(sub) == 0:
            continue
        top = sub.sort_values("score", ascending=False).head(
            int(round(0.10 * len(sub))))
        lines.append(format_row(f"{lbl} top-10%",
                                  risk(top["bracket_pnl"])))
    lines.append("")

    # ===== RTH-Short × T =====
    lines.append("## RTH-Short × T bucket (top-10%)")
    lines.append("")
    lines.append(header)
    lines.append(divider)
    rs = df[df["signal_direction"] == -1]
    for lo, hi, lbl in [
        (0, 90, "0-90s"), (90, 180, "90-180s"),
        (180, 300, "180-300s"), (300, 450, "300-450s"),
        (450, 601, "450-600s"),
    ]:
        sub = rs[(rs["checkpoint_s"] >= lo)
                  & (rs["checkpoint_s"] < hi)]
        if len(sub) == 0:
            continue
        top = sub.sort_values("score", ascending=False).head(
            int(round(0.10 * len(sub))))
        lines.append(format_row(f"RTH-Short {lbl} top-10%",
                                  risk(top["bracket_pnl"])))
    lines.append("")

    # ===== Quarters =====
    lines.append("## Top-10% by 2025 quarter (stability)")
    lines.append("")
    lines.append(header)
    lines.append(divider)
    q_df = df.copy()
    q_df["fill_dt_utc"] = pd.to_datetime(
        q_df["fill_time_actual"], unit="ns", utc=True)
    q_df["quarter"] = q_df["fill_dt_utc"].dt.quarter
    for q in [1, 2, 3, 4]:
        sub = q_df[q_df["quarter"] == q]
        if len(sub) == 0:
            continue
        top = sub.sort_values("score", ascending=False).head(
            int(round(0.10 * len(sub))))
        lines.append(format_row(f"Q{q} top-10%",
                                  risk(top["bracket_pnl"])))
    lines.append("")

    # ===== RTH-Short 180-300s deep dive =====
    lines.append("## RTH-Short × 180-300s deep dive (top-k)")
    lines.append("")
    lines.append(header)
    lines.append(divider)
    target = df[(df["signal_direction"] == -1)
                 & (df["checkpoint_s"] >= 180)
                 & (df["checkpoint_s"] < 300)]
    lines.append(format_row("RTH-Short 180-300s ALL",
                              risk(target["bracket_pnl"])))
    for frac in [0.30, 0.20, 0.10, 0.05]:
        n = int(round(frac * len(target)))
        top = target.sort_values("score", ascending=False).head(n)
        lines.append(format_row(
            f"RTH-Short 180-300s top {int(frac*100)}%",
            risk(top["bracket_pnl"])))
    lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Report: {args.out}")


if __name__ == "__main__":
    main()
