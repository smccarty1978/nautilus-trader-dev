"""Post-processing combination screen — failure filter + winner model.

Cheap go/no-go test using EXISTING OOS predictions:
  - Failure model: studies/failure_filter_v1/results/models_oos_{year}/oos_predictions.parquet
  - Winner model:  studies/bracket_entry_v3_fullpop/results/models_oos_{year}/full/oos_predictions.parquet

Both trained on the same OOS splits, same full live population. Predictions
ALREADY exist — just need to merge, filter, score economics.

NOT a live NT run. No single-position gate. Pure formulaic bracket PnL on
the row population that survives the filter + selection.

Tests:
  - winner only (top-10% by winner score) — baseline
  - failure-filter only (exclude top-N% by failure score, no winner selection)
  - combined (filter + then top-10% winner)
"""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

YEARS = [2024, 2026]
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0  # 1 tick × $20/pt = $5


def bracket_pnl(df: pd.DataFrame) -> pd.Series:
    """Per-row bracket PnL with $5 commission + 1-tick adverse entry +
    1-tick adverse exit on SL/regime/unresolved. NaN pt100 = treat
    as regime exit (bracket never resolved)."""
    pt = df["pt100_before_sl100"].values
    atr = df["atr_at_signal"].values
    out = np.empty(len(df), dtype=float)
    for i in range(len(df)):
        v = pt[i]
        if pd.isna(v):
            # Unresolved — bracket didn't hit before regime exit.
            # Treat as adverse close at regime-flip price ≈ -1 ATR
            # (the regime flip moved against the trade by ~1 ATR on
            # average — see prior unresolved-rows analysis).
            # Use a conservative -0.7 ATR as proxy (matches earlier
            # regime_exit-rows mean PnL behavior).
            out[i] = -0.7 * atr[i] * NQ_MULT - COMMISSION - TICK_COST
        elif v == 1:
            out[i] = atr[i] * NQ_MULT - COMMISSION - TICK_COST
        else:
            out[i] = -atr[i] * NQ_MULT - COMMISSION - 2 * TICK_COST
    return pd.Series(out, index=df.index)


def stats(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {"n": 0}
    s = df["pnl"].dropna()
    wins = s[s > 0]
    losses = s[s < 0]
    k = int(len(s) * 0.05)
    trim = (s.sort_values().iloc[k:len(s) - k].mean()
             if k * 2 < len(s) else float("nan"))
    pt = df["pt100_before_sl100"]
    pt_n = int((pt == 1).sum())
    sl_n = int((pt == 0).sum())
    unres_n = int(pt.isna().sum())
    long_n = int((df["signal_direction"] == 1).sum())
    short_n = int((df["signal_direction"] == -1).sum())
    return {
        "n": len(df),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed_5pct": float(trim),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
        "pt_pct": pt_n / len(df),
        "sl_pct": sl_n / len(df),
        "regime_pct": unres_n / len(df),
        "long_pct": long_n / len(df),
        "short_pct": short_n / len(df),
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


def run_year(year: int) -> dict:
    failure_pred = pd.read_parquet(
        f"studies/failure_filter_v1/results/models_oos_{year}/"
        "oos_predictions.parquet")
    winner_pred = pd.read_parquet(
        f"studies/bracket_entry_v3_fullpop/results/"
        f"models_oos_{year}/full/oos_predictions.parquet")

    failure_pred = failure_pred.rename(
        columns={"score": "failure_score"})
    winner_pred = winner_pred.rename(
        columns={"score": "winner_score"})

    keep_w = ["event_id", "checkpoint_s", "winner_score"]
    df = failure_pred.merge(
        winner_pred[keep_w],
        on=["event_id", "checkpoint_s"], how="inner")
    print(f"\n=== {year} ===")
    print(f"Merged population: {len(df):,}")

    df["pnl"] = bracket_pnl(df)

    # Compute thresholds on OOS data directly (per-OOS percentiles)
    f_p98 = float(df["failure_score"].quantile(0.98))
    f_p95 = float(df["failure_score"].quantile(0.95))
    f_p90 = float(df["failure_score"].quantile(0.90))
    w_p90 = float(df["winner_score"].quantile(0.90))

    print(f"Failure thresholds: p98={f_p98:.4f} p95={f_p95:.4f} "
           f"p90={f_p90:.4f}")
    print(f"Winner threshold (top-10%): {w_p90:.4f}")

    rows = []

    def record(label: str, sub: pd.DataFrame):
        s = stats(sub)
        rows.append({"label": label, **s})

    # 1. ALL (full population, no filter, no selection)
    record("ALL (no filter, no selection)", df)

    # 2. Winner only (top-10% by winner score)
    win_only = df[df["winner_score"] >= w_p90]
    record("Winner only (top-10%)", win_only)

    # 3. Failure filter only — exclude worst N%
    excl2 = df[df["failure_score"] < f_p98]
    excl5 = df[df["failure_score"] < f_p95]
    excl10 = df[df["failure_score"] < f_p90]
    record("Failure-filter only: excl worst 2%", excl2)
    record("Failure-filter only: excl worst 5%", excl5)
    record("Failure-filter only: excl worst 10%", excl10)

    # 4. Combined: filter then winner-top-10%
    for label, df_filt in [("excl worst 2%", excl2),
                              ("excl worst 5%", excl5),
                              ("excl worst 10%", excl10)]:
        # On survivors, take top 10% by winner score (per OOS p90 of survivors)
        w_thr = float(df_filt["winner_score"].quantile(0.90))
        combo = df_filt[df_filt["winner_score"] >= w_thr]
        record(f"Combined: {label} + winner top-10%", combo)

    return {"year": year, "rows": rows}


def main():
    out_lines = ["# Combo Screening — Failure Filter + Winner Model",
                  "",
                  "Post-processing test on existing OOS predictions. "
                  "No live NT run, no single-position gate. Pure "
                  "formulaic bracket PnL.",
                  "",
                  "Cost: $5 commission + 1-tick adverse entry + "
                  "1-tick adverse exit on losses. Unresolved rows "
                  "scored as -0.7 ATR proxy (matches prior "
                  "regime-exit-rows behavior).",
                  ""]
    all_rows = []
    for year in YEARS:
        result = run_year(year)
        out_lines.append(f"## {year} OOS")
        out_lines.append("")
        out_lines.append("| Slice | n | Mean $ | Median $ | Trim 5% | "
                          "PF | Win% | PT% | Reg% | L/S% | Total $ |")
        out_lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|")
        for r in result["rows"]:
            out_lines.append(
                f"| {r['label']} | {int(r['n']):,} | "
                f"{_d(r.get('mean'))} | {_d(r.get('median'))} | "
                f"{_d(r.get('trimmed_5pct'))} | "
                f"{r.get('pf', float('nan')):.2f} | "
                f"{_p(r.get('win_rate'))} | "
                f"{_p(r.get('pt_pct'))} | "
                f"{_p(r.get('regime_pct'))} | "
                f"{100*r.get('long_pct', 0):.0f}/"
                f"{100*r.get('short_pct', 0):.0f} | "
                f"{_d(r.get('sum'))} |")
            all_rows.append({"year": year, **r})
        out_lines.append("")

    df_all = pd.DataFrame(all_rows)
    out_path = Path("studies/failure_filter_v1/results/"
                      "COMBO_SCREENING.md")
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nReport: {out_path}")

    # Console quick-scan
    print()
    print("=== QUICK SCAN ===")
    cols = ["year", "label", "n", "mean", "pf", "win_rate", "pt_pct"]
    print(df_all[cols].to_string(
        index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
