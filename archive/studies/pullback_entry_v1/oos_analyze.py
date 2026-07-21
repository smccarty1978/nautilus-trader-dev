"""OOS analyzer for the 1.0 ATR pullback / PT 1.0 / SL 0.75 combo.

Three populations per year:
  1. Confirmed-entry baseline (all HH/LL-confirmed RTH regimes,
     signal-time entry)
  2. Matched survivor baseline (subset of (1) where regime survived to
     1.0 ATR pullback)
  3. Pullback-entry strategy (decision-time entry at first 1.0 ATR
     pullback)
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/pullback_entry_v1/results")
YEARS = [2024, 2025, 2026]
PNL_COL = "bracket_100_75_pnl"
OC_COL = "bracket_100_75_outcome"
RES_COL = "bracket_100_75_resolution_s"


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def max_drawdown(pnl_series_chronological: pd.Series) -> float:
    if len(pnl_series_chronological) == 0:
        return 0.0
    cum = pnl_series_chronological.cumsum().values
    running_peak = np.maximum.accumulate(cum)
    drawdown = cum - running_peak
    return float(drawdown.min())


def stats_row(df: pd.DataFrame, label: str) -> dict:
    if len(df) == 0:
        return {"label": label, "n": 0}
    s = df[PNL_COL].dropna()
    oc = df[OC_COL]
    wins = s[s > 0]
    losses = s[s < 0]
    # Chronological order for max DD
    if "fill_ts" in df.columns:
        df_sorted = df.sort_values("fill_ts")
        mdd = max_drawdown(df_sorted[PNL_COL].dropna())
    else:
        mdd = float("nan")
    out = {
        "label": label,
        "n": len(s),
        "pt_pct": float((oc == "pt").mean()),
        "sl_pct": float((oc == "sl").mean()),
        "regime_pct": float((oc == "regime").mean()),
        "timeout_pct": float((oc == "timeout").mean()),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "sum": float(s.sum()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0 else float("inf")),
        "max_dd": mdd,
        "mean_atr": (float(df["atr_at_signal"].mean())
                       if "atr_at_signal" in df.columns
                       else float("nan")),
        "median_regime_dur_min": (
            float(df["regime_duration_s"].median()) / 60
            if "regime_duration_s" in df.columns
            else float("nan")),
        "mean_regime_dur_min": (
            float(df["regime_duration_s"].mean()) / 60
            if "regime_duration_s" in df.columns
            else float("nan")),
    }
    if "time_since_signal_s" in df.columns:
        t = df["time_since_signal_s"].dropna()
        out["median_t_pullback"] = float(t.median())
        out["mean_t_pullback"] = float(t.mean())
    else:
        out["median_t_pullback"] = float("nan")
        out["mean_t_pullback"] = float("nan")
    return out


def main():
    lines = []
    lines.append("# Pullback Combo OOS Validation — 2024 + 2026")
    lines.append("")
    lines.append("**Rule under test**: HH/LL-confirmed 1m regime, "
                 "wait for first 1.0 ATR pullback, enter at next "
                 "30s-checkpoint+30s fill. Bracket: PT 1.0 ATR / "
                 "SL 0.75 ATR. Exit at bracket hit OR opposing 1m "
                 "regime flip OR 30-min cap.")
    lines.append("")
    lines.append("**Cost**: $5 commission + 1-tick adverse entry. "
                 "PT/regime/timeout: 1-tick exit slip; SL: 2-tick "
                 "exit slip.")
    lines.append("")
    lines.append("**Source of edge claim**: 2025 in-sample matched-"
                 "baseline showed +$13.69/trade lift for this exact "
                 "combo. This test asks: does the lift hold OOS?")
    lines.append("")

    summary_rows = []
    for year in YEARS:
        ce = pd.read_parquet(
            OUT / f"oos_confirmed_entries_{year}.parquet")
        pb = pd.read_parquet(
            OUT / f"oos_pullback_1atr_{year}.parquet")

        # Matched baseline: confirmed-entry rows from regimes that
        # appear in pullback set
        survivor_ids = set(pb["regime_id"].unique())
        ms = ce[ce["regime_id"].isin(survivor_ids)].copy()

        ce_s = stats_row(ce, "1. Confirmed-entry baseline")
        ms_s = stats_row(ms, "2. Matched survivor baseline")
        pb_s = stats_row(pb, "3. Pullback-entry strategy")

        delta_vs_baseline = pb_s["mean"] - ce_s["mean"]
        delta_vs_matched = pb_s["mean"] - ms_s["mean"]

        is_oos = year != 2025
        tag = "OOS" if is_oos else "in-sample reference"
        lines.append(f"## {year} ({tag})")
        lines.append("")
        lines.append(
            f"Confirmed regimes (n total): {len(ce):,}. "
            f"Reaching 1.0 ATR pullback: {len(pb):,} "
            f"({100*len(pb)/len(ce):.1f}%).")
        lines.append("")
        lines.append("| Population | n | PT% | SL% | Reg% | TO% | "
                     "Mean $ | Median $ | PF | Total $ | Max DD | "
                     "Mean ATR | Med Reg Dur |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for s in [ce_s, ms_s, pb_s]:
            lines.append(
                f"| {s['label']} | {s['n']:,} | "
                f"{fmt_p(s['pt_pct'])} | {fmt_p(s['sl_pct'])} | "
                f"{fmt_p(s['regime_pct'])} | "
                f"{fmt_p(s['timeout_pct'])} | "
                f"{fmt_d(s['mean'])} | {fmt_d(s['median'])} | "
                f"{s['pf']:.2f} | {fmt_d(s['sum'])} | "
                f"{fmt_d(s['max_dd'])} | "
                f"{s['mean_atr']:.2f} | "
                f"{s['median_regime_dur_min']:.1f}min |")
        lines.append("")
        lines.append(
            f"- **Δ pullback vs confirmed baseline**: "
            f"**{fmt_d(delta_vs_baseline)}/trade** "
            f"({len(pb):,} trades, total "
            f"{fmt_d(pb_s['sum'] - ce_s['mean']*len(pb))})")
        lines.append(
            f"- **Δ pullback vs matched survivor baseline**: "
            f"**{fmt_d(delta_vs_matched)}/trade** (the apples-to-"
            f"apples test)")
        if not pd.isna(pb_s["median_t_pullback"]):
            lines.append(
                f"- Median time to pullback decision: "
                f"{pb_s['median_t_pullback']:.0f}s "
                f"(mean {pb_s['mean_t_pullback']:.0f}s)")
        lines.append("")

        summary_rows.append({
            "year": year, "tag": tag,
            "n_confirmed": len(ce),
            "n_pullback": len(pb),
            "ce_mean": ce_s["mean"], "ms_mean": ms_s["mean"],
            "pb_mean": pb_s["mean"],
            "delta_baseline": delta_vs_baseline,
            "delta_matched": delta_vs_matched,
            "pb_pf": pb_s["pf"], "ms_pf": ms_s["pf"],
            "ce_pf": ce_s["pf"],
            "pb_total": pb_s["sum"],
            "pb_max_dd": pb_s["max_dd"],
        })

    # ----- Cross-year summary -----
    lines.append("## Cross-year summary")
    lines.append("")
    lines.append("| Year | Tag | n trades | Conf base $ | "
                 "Match base $ | Pullback $ | Δ vs Conf | "
                 "**Δ vs Matched** | Pullback PF | Match PF | "
                 "Total $ | Max DD |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in summary_rows:
        lines.append(
            f"| {r['year']} | {r['tag']} | {r['n_pullback']:,} | "
            f"{fmt_d(r['ce_mean'])} | {fmt_d(r['ms_mean'])} | "
            f"{fmt_d(r['pb_mean'])} | "
            f"{fmt_d(r['delta_baseline'])} | "
            f"**{fmt_d(r['delta_matched'])}** | "
            f"{r['pb_pf']:.2f} | {r['ms_pf']:.2f} | "
            f"{fmt_d(r['pb_total'])} | "
            f"{fmt_d(r['pb_max_dd'])} |")
    lines.append("")

    # Verdict
    matched_deltas = [r["delta_matched"] for r in summary_rows
                        if r["tag"] == "OOS"]
    in_sample_2025 = [r for r in summary_rows
                        if r["year"] == 2025][0]
    n_pos_oos = sum(1 for d in matched_deltas if d > 0)
    n_total_oos = len(matched_deltas)
    lines.append("## Verdict")
    lines.append("")
    lines.append(
        f"**2025 in-sample matched-baseline lift**: "
        f"{fmt_d(in_sample_2025['delta_matched'])}/trade.")
    lines.append("")
    lines.append(
        f"**OOS matched-baseline lift**: "
        f"{n_pos_oos}/{n_total_oos} OOS years positive.")
    for r in summary_rows:
        if r["tag"] == "OOS":
            lines.append(
                f"- {r['year']}: {fmt_d(r['delta_matched'])}/trade "
                f"(n={r['n_pullback']:,}, pullback total "
                f"{fmt_d(r['pb_total'])})")
    lines.append("")

    # Robustness assessment
    if all(r["delta_matched"] > 0 for r in summary_rows):
        verdict = ("**HOLDS**: positive Δ in all three years. "
                    "The pullback edge is reproducible OOS.")
    elif n_pos_oos == n_total_oos:
        verdict = ("**LIKELY HOLDS**: positive Δ in all OOS years, "
                    "though magnitude varies.")
    elif n_pos_oos > 0:
        verdict = (f"**MIXED**: {n_pos_oos}/{n_total_oos} OOS years "
                    "positive. The 2025 in-sample number may "
                    "be inflated.")
    else:
        verdict = (f"**FAILS OOS**: {n_pos_oos}/{n_total_oos} OOS "
                    "years positive. The 2025 +$13.69 lift was "
                    "noise.")
    lines.append(verdict)

    out_path = OUT / "OOS_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")
    print("\n=== Quick scan ===")
    for r in summary_rows:
        print(f"  {r['year']} ({r['tag']}): n={r['n_pullback']:,}, "
               f"pb=${r['pb_mean']:.2f}, ms=${r['ms_mean']:.2f}, "
               f"Δ_matched=${r['delta_matched']:+.2f}, "
               f"PF={r['pb_pf']:.2f}, total={r['pb_total']:,.0f}")


if __name__ == "__main__":
    main()
