"""Analyze v3 live NT runs — build final dual-OOS report.

For each (year, candidate):
  - Load positions + strategy_trades
  - Classify exits (PT/SL/regime_exit)
  - Compute cost-adjusted PnL (1-tick slippage)
  - Compute outcome mix
  - Build per-row record

Report:
  - Iteration table per year (AUC, NT economics, outcome mix)
  - Outcome mix comparison: population vs top-decile selections
  - Smallest-viable selection
  - Cross-year stability
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

V3_ROOT = Path("studies/bracket_entry_v3_fullpop/results")
NT_ROOT = V3_ROOT / "nt_runs"
SWEEP_SUMMARY = V3_ROOT / "sweep_summary.parquet"

ITERATIONS = ["full", "top_50", "top_35", "top_25", "top_20",
              "top_15", "top_10"]
YEARS = [2024, 2026]


def classify_exit(row, tol=0.05) -> str:
    d = row["direction"]
    atr = row["atr_at_signal"]
    if atr <= 0:
        return "unknown"
    m = (row["avg_px_close"] - row["avg_px_open"]) * d / atr
    if m >= 1.0 - tol:
        return "pt"
    if m <= -(1.0 - tol):
        return "sl"
    return "regime_exit"


def cost_adjusted_pnl(pos: pd.DataFrame) -> pd.Series:
    """Scenario C: $5 commission + 1-tick adverse entry + 1-tick
    adverse exit on SL/regime_exit."""
    d = pos["direction"].values
    entry = pos["avg_px_open"].astype(float).values
    exit_ = pos["avg_px_close"].astype(float).values
    reason = pos["exit_reason"].values
    entry_slip = np.where(d == 1, 0.25, -0.25)
    slip_mask = np.isin(reason, ["sl", "regime_exit", "unknown"])
    exit_slip = np.where(slip_mask,
                           np.where(d == 1, -0.25, 0.25), 0.0)
    pnl = (((exit_ + exit_slip) - (entry + entry_slip))
             * d * 20.0 - 5.0)
    return pd.Series(pnl, index=pos.index)


def load_run(year: int, iteration: str) -> pd.DataFrame | None:
    run_dir = NT_ROOT / f"{year}_{iteration}"
    pos_path = run_dir / "positions.parquet"
    tr_path = run_dir / "strategy_trades.parquet"
    if not pos_path.exists() or not tr_path.exists():
        return None
    pos = pd.read_parquet(pos_path)
    tr = pd.read_parquet(tr_path)
    tr = tr[tr["entry_fill_price"].notna()].copy()
    tr = tr.sort_values("decision_ts_ns").reset_index(drop=True)
    pos = pos.copy()
    pos["entry_ts_ns"] = pos["ts_opened"].astype("int64")
    pos = pos.sort_values("entry_ts_ns").reset_index(drop=True)
    n = min(len(pos), len(tr))
    pos = pos.iloc[:n].copy()
    pos["direction"] = tr["direction"].iloc[:n].values
    pos["atr_at_signal"] = tr["atr_at_signal"].iloc[:n].values
    pos["score"] = tr["score"].iloc[:n].values
    pos["checkpoint_s"] = tr["checkpoint_s"].iloc[:n].values
    pos["exit_reason"] = pos.apply(classify_exit, axis=1)
    pos["pnl_1tick"] = cost_adjusted_pnl(pos)
    pos["pnl_raw"] = ((pos["avg_px_close"] - pos["avg_px_open"])
                        * pos["direction"] * 20.0)
    return pos


def risk(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan,
                 "trimmed": np.nan, "pf": np.nan,
                 "win_rate": np.nan, "sum": 0.0}
    wins = s[s > 0]
    losses = s[s < 0]
    k = int(len(s) * 0.05)
    trim = (s.sort_values().iloc[k:len(s) - k].mean()
             if k * 2 < len(s) else np.nan)
    return {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed": float(trim),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
    }


def outcome_mix(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {k: np.nan for k in ("pt_pct", "sl_pct",
                                      "regime_pct", "unknown_pct")}
    n = len(df)
    return {
        "pt_pct": int((df["exit_reason"] == "pt").sum()) / n,
        "sl_pct": int((df["exit_reason"] == "sl").sum()) / n,
        "regime_pct": int((df["exit_reason"] == "regime_exit").sum()) / n,
        "unknown_pct": int((df["exit_reason"] == "unknown").sum()) / n,
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
    sweep = pd.read_parquet(SWEEP_SUMMARY)
    # Build per-run rows
    records = []
    for year in YEARS:
        for iteration in ITERATIONS:
            df = load_run(year, iteration)
            cls_row = sweep[(sweep["oos_year"] == year)
                             & (sweep["iter"] == iteration)]
            auc = float(cls_row["auc"].iloc[0]) if len(cls_row) else np.nan
            pr_auc = float(cls_row["pr_auc"].iloc[0]) if len(cls_row) else np.nan
            base = float(cls_row["base_rate"].iloc[0]) if len(cls_row) else np.nan
            top10_hit = float(cls_row["top10_hit_rate"].iloc[0]) if len(cls_row) else np.nan
            if df is None:
                rec = {"year": year, "iter": iteration,
                        "n": 0, "status": "missing"}
            else:
                r = risk(df["pnl_1tick"])
                mix = outcome_mix(df)
                long_n = int((df["direction"] == 1).sum())
                short_n = int((df["direction"] == -1).sum())
                rec = {
                    "year": year, "iter": iteration,
                    "auc": auc, "pr_auc": pr_auc,
                    "base_rate": base, "top10_hit": top10_hit,
                    **r, **mix,
                    "long_pct": long_n / r["n"] if r["n"] else np.nan,
                    "short_pct": short_n / r["n"] if r["n"] else np.nan,
                }
            records.append(rec)

    df_summary = pd.DataFrame(records)
    df_summary.to_parquet(V3_ROOT / "final_summary.parquet",
                             index=False)

    # Build report
    lines = []
    lines.append("# Bracket-Entry v3 — Full-Population Rescue Report")
    lines.append("")
    lines.append("Label: `is_pt_first = 1 iff pt100_before_sl100 == 1` "
                  "(negative class includes SL, regime-exit, unresolved).")
    lines.append("Evaluation: LIVE full-population NT strategy. "
                  "No schedule-driven results.")
    lines.append("")

    for year in YEARS:
        lines.append(f"## {year} OOS")
        lines.append("")
        lines.append("| Iter | Features | AUC | Top-10 hit | "
                      "n | Mean $ | Trim 5% | PF | Win% | L/S% | "
                      "PT% | SL% | Regime% | Total $ |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|--:|--:|--:|")
        for iteration in ITERATIONS:
            r = df_summary[
                (df_summary["year"] == year)
                & (df_summary["iter"] == iteration)]
            if len(r) == 0:
                continue
            r = r.iloc[0]
            n_feat_lookup = {
                "full": 177, "top_50": 50, "top_35": 35,
                "top_25": 25, "top_20": 20, "top_15": 15,
                "top_10": 10,
            }
            if r.get("status") == "missing":
                lines.append(f"| {iteration} | "
                              f"{n_feat_lookup[iteration]} | — | — | "
                              "MISSING RUN |")
                continue
            lines.append(
                f"| {iteration} | {n_feat_lookup[iteration]} | "
                f"{r['auc']:.4f} | {_p(r['top10_hit'])} | "
                f"{int(r['n']):,} | {_d(r['mean'])} | "
                f"{_d(r['trimmed'])} | {r['pf']:.2f} | "
                f"{_p(r['win_rate'])} | "
                f"{100*r['long_pct']:.0f}/{100*r['short_pct']:.0f} | "
                f"{_p(r['pt_pct'])} | {_p(r['sl_pct'])} | "
                f"{_p(r['regime_pct'])} | "
                f"{_d(r['sum'])} |")
        lines.append("")

    # Cross-year summary (picking best iteration per year + overlap)
    lines.append("## Cross-year smallest-viable analysis")
    lines.append("")
    lines.append("A candidate is viable if PF > 1.10 on BOTH years.")
    lines.append("")
    lines.append("| Iter | 2024 PF | 2024 Mean | 2026 PF | 2026 Mean "
                  "| Both > 1.10 |")
    lines.append("|---|--:|--:|--:|--:|---|")
    for iteration in ITERATIONS:
        r24 = df_summary[(df_summary["year"] == 2024)
                          & (df_summary["iter"] == iteration)]
        r26 = df_summary[(df_summary["year"] == 2026)
                          & (df_summary["iter"] == iteration)]
        if len(r24) == 0 or len(r26) == 0:
            continue
        r24 = r24.iloc[0]
        r26 = r26.iloc[0]
        pf_ok = (r24.get("pf", 0) > 1.10
                  and r26.get("pf", 0) > 1.10)
        lines.append(
            f"| {iteration} | {r24.get('pf', float('nan')):.2f} | "
            f"{_d(r24.get('mean'))} | "
            f"{r26.get('pf', float('nan')):.2f} | "
            f"{_d(r26.get('mean'))} | "
            f"{'✅' if pf_ok else '❌'} |")
    lines.append("")

    # Verdict
    any_passing = False
    for iteration in ITERATIONS:
        r24 = df_summary[(df_summary["year"] == 2024)
                          & (df_summary["iter"] == iteration)]
        r26 = df_summary[(df_summary["year"] == 2026)
                          & (df_summary["iter"] == iteration)]
        if (len(r24) and len(r26)
            and r24.iloc[0].get("pf", 0) > 1.10
            and r26.iloc[0].get("pf", 0) > 1.10):
            any_passing = True
            break

    lines.append("## Verdict")
    lines.append("")
    if any_passing:
        lines.append("**At least one candidate survives both OOS "
                      "years under live full-population evaluation. "
                      "The rescue has traction — inspect individual "
                      "candidates for best preservation + stability.**")
    else:
        lines.append("**NO candidate passes PF > 1.10 on both 2024 "
                      "AND 2026. The rescue label + feature set does "
                      "not produce a durable deployment edge.**")
        lines.append("")
        lines.append("Retire this branch. The bracket-aligned "
                      "entry-quality model family appears not viable "
                      "under honest full-population evaluation, even "
                      "with the corrected label.")
    lines.append("")

    out = V3_ROOT / "FINAL_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out}")

    # Console summary
    print()
    print(df_summary[["year", "iter", "n", "mean", "pf",
                        "win_rate", "pt_pct", "regime_pct",
                        "sum"]].to_string(
        index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
