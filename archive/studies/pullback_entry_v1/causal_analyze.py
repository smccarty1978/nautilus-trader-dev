"""Causal-vs-buggy-vs-NT comparison for pullback OOS study.

For each year (2024, 2025, 2026):
  - Buggy offline: oos_pullback_1atr_<year>.parquet
  - Causal offline: causal_pullback_1atr_<year>.parquet
  - NT runtime: nt_runtime_<year>/nt_trades.parquet (where available)
  - Matched survivor baseline (causal version)

Compute population stats per source, plus matched-pair comparisons
to attribute the buggy-vs-causal gap.
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


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def max_drawdown(s):
    if len(s) == 0:
        return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats(pnl, outcome=None, label="?"):
    s = pd.Series(pnl).dropna()
    if len(s) == 0:
        return {"label": label, "n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    out = {
        "label": label, "n": len(s),
        "mean": float(s.mean()), "median": float(s.median()),
        "sum": float(s.sum()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
        "max_dd": max_drawdown(s),
    }
    if outcome is not None:
        oc = pd.Series(outcome)
        out["pt_pct"] = float((oc == "pt").mean())
        out["sl_pct"] = float((oc == "sl").mean())
        out["regime_pct"] = float((oc == "regime").mean())
        out["timeout_pct"] = float((oc == "timeout").mean())
    return out


def main():
    lines = []
    lines.append("# Causal Collector vs Buggy vs NT — Pullback OOS")
    lines.append("")
    lines.append("**Bug fixed**: collector now uses "
                 "`next_flip.flip_bar_ts_init` (= 1m bar CLOSE) for "
                 "regime exit timing and the 1m bar's close price "
                 "for regime exit price. No more dropping trades "
                 "based on `fill_ts >= regime_end_ts` (future "
                 "knowledge). Decisions only filtered if regime "
                 "already known to be flipped at decision time.")
    lines.append("")
    lines.append("**Comparison**: BUGGY = original "
                 "`oos_pullback_1atr_<year>.parquet`. CAUSAL = new "
                 "`causal_pullback_1atr_<year>.parquet`. NT = real "
                 "runtime trades from `nt_runtime_<year>/"
                 "nt_trades.parquet`.")
    lines.append("")

    summary_rows = []
    for year in YEARS:
        buggy_path = OUT / f"oos_pullback_1atr_{year}.parquet"
        causal_path = OUT / f"causal_pullback_1atr_{year}.parquet"
        causal_ce_path = OUT / f"causal_confirmed_entries_{year}.parquet"
        nt_path = OUT / f"nt_runtime_{year}" / "nt_trades.parquet"

        buggy = pd.read_parquet(buggy_path)
        causal = pd.read_parquet(causal_path)
        causal_ce = pd.read_parquet(causal_ce_path)
        nt = pd.read_parquet(nt_path) if nt_path.exists() else None

        # Matched survivor baseline (causal): confirmed-entry rows
        # whose regime_id appears in the pullback set
        survivor_ids = set(causal["regime_id"].unique())
        ms_causal = causal_ce[causal_ce["regime_id"].isin(
            survivor_ids)].copy()

        buggy_s = stats(buggy[PNL_COL], buggy[OC_COL], "BUGGY pullback")
        causal_s = stats(causal[PNL_COL], causal[OC_COL],
                          "CAUSAL pullback")
        ms_s = stats(ms_causal[PNL_COL], ms_causal[OC_COL],
                       "CAUSAL matched baseline")
        ce_s = stats(causal_ce[PNL_COL], causal_ce[OC_COL],
                       "CAUSAL confirmed-entry baseline (all)")
        if nt is not None:
            nt_s = stats(nt["net_pnl_actual"], nt["exit_reason"],
                          "NT runtime (actual fills)")
        else:
            nt_s = None

        delta_pb_vs_msbase = causal_s["mean"] - ms_s["mean"]
        delta_buggy_vs_causal = buggy_s["mean"] - causal_s["mean"]
        delta_nt_vs_causal = (nt_s["mean"] - causal_s["mean"]
                                if nt_s else float("nan"))

        is_oos = year != 2025
        tag = "OOS" if is_oos else "in-sample reference"
        lines.append(f"## {year} ({tag})")
        lines.append("")
        lines.append(
            f"Confirmed regimes: {len(causal_ce):,}. Pullback "
            f"survivors: {len(causal):,} "
            f"({100*len(causal)/len(causal_ce):.1f}%). "
            f"Buggy version had {len(buggy):,} pullback rows.")
        lines.append("")
        lines.append("| Population | n | PT% | SL% | Reg% | Mean $ | "
                     "Median $ | PF | Total $ | Max DD |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        rows = [ce_s, ms_s, buggy_s, causal_s]
        if nt_s is not None:
            rows.append(nt_s)
        for s in rows:
            lines.append(
                f"| {s['label']} | {s['n']:,} | "
                f"{fmt_p(s.get('pt_pct'))} | "
                f"{fmt_p(s.get('sl_pct'))} | "
                f"{fmt_p(s.get('regime_pct'))} | "
                f"{fmt_d(s['mean'])} | {fmt_d(s['median'])} | "
                f"{s['pf']:.2f} | {fmt_d(s['sum'])} | "
                f"{fmt_d(s['max_dd'])} |")
        lines.append("")

        lines.append(
            f"- **Δ CAUSAL pullback vs CAUSAL matched baseline**: "
            f"**{fmt_d(delta_pb_vs_msbase)}/trade** "
            f"(this is the methodology-corrected pullback edge)")
        lines.append(
            f"- Δ BUGGY pullback vs CAUSAL pullback (bug impact): "
            f"**{fmt_d(delta_buggy_vs_causal)}/trade** "
            f"(amount of inflation the bug introduced)")
        if nt_s is not None:
            lines.append(
                f"- Δ NT actual vs CAUSAL pullback (real-world drag): "
                f"**{fmt_d(delta_nt_vs_causal)}/trade**")
        lines.append("")

        # Matched-pair comparison: causal vs NT on same trades
        if nt_s is not None and "signal_time" in nt.columns:
            nt_keys = nt[["signal_time", "exit_reason",
                            "net_pnl_actual"]].copy()
            nt_keys["sig_key"] = nt_keys["signal_time"]
            causal_keys = causal[["signal_time_ts", OC_COL,
                                     PNL_COL]].copy()
            causal_keys["sig_key"] = causal_keys["signal_time_ts"]
            both = nt_keys.merge(causal_keys, on="sig_key",
                                    how="outer", indicator=True)
            n_both = int((both["_merge"] == "both").sum())
            n_nt_only = int((both["_merge"] == "left_only").sum())
            n_causal_only = int((both["_merge"] == "right_only").sum())
            matched = both[both["_merge"] == "both"].copy()
            outcome_match = (matched["exit_reason"]
                              == matched[OC_COL]).sum()
            lines.append(
                f"Trade pairing NT vs CAUSAL: {n_both:,} matched, "
                f"{n_nt_only:,} NT-only, {n_causal_only:,} "
                f"causal-only.")
            lines.append(
                f"Outcome agreement on matched: {outcome_match:,} "
                f"({100*outcome_match/n_both:.1f}%).")
            lines.append("")
            ct = pd.crosstab(matched["exit_reason"], matched[OC_COL],
                              margins=True)
            lines.append("Outcome cross-tab (rows = NT, cols = "
                          "CAUSAL):")
            lines.append("")
            lines.append("```")
            lines.append(ct.to_string())
            lines.append("```")
            lines.append("")
            paired_nt = matched["net_pnl_actual"].mean()
            paired_causal = matched[PNL_COL].mean()
            lines.append(
                f"On {n_both:,} matched: NT mean "
                f"{fmt_d(paired_nt)}, CAUSAL mean "
                f"{fmt_d(paired_causal)}, Δ "
                f"**{fmt_d(paired_nt - paired_causal)}**.")
            lines.append("")

        summary_rows.append({
            "year": year, "tag": tag,
            "n_buggy": buggy_s["n"], "n_causal": causal_s["n"],
            "n_nt": nt_s["n"] if nt_s else 0,
            "buggy_mean": buggy_s["mean"],
            "causal_mean": causal_s["mean"],
            "ms_mean": ms_s["mean"],
            "nt_mean": nt_s["mean"] if nt_s else float("nan"),
            "delta_pb_vs_ms": delta_pb_vs_msbase,
            "delta_buggy_vs_causal": delta_buggy_vs_causal,
            "delta_nt_vs_causal": delta_nt_vs_causal,
            "causal_pf": causal_s["pf"],
            "ms_pf": ms_s["pf"],
            "nt_pf": nt_s["pf"] if nt_s else float("nan"),
            "causal_total": causal_s["sum"],
            "nt_total": nt_s["sum"] if nt_s else float("nan"),
            "causal_pt": causal_s.get("pt_pct"),
            "nt_pt": nt_s.get("pt_pct") if nt_s else float("nan"),
            "causal_sl": causal_s.get("sl_pct"),
            "nt_sl": nt_s.get("sl_pct") if nt_s else float("nan"),
            "causal_reg": causal_s.get("regime_pct"),
            "nt_reg": nt_s.get("regime_pct") if nt_s else float("nan"),
        })

    # Cross-year summary
    lines.append("## Cross-year summary")
    lines.append("")
    lines.append("| Year | Tag | n CAUSAL | n NT | CAUSAL mean | "
                 "CAUSAL matched mean | NT mean | "
                 "**Δ CAUSAL vs matched** | Δ BUGGY vs CAUSAL | "
                 "Δ NT vs CAUSAL | CAUSAL PF | NT PF |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in summary_rows:
        lines.append(
            f"| {r['year']} | {r['tag']} | {r['n_causal']:,} | "
            f"{r['n_nt']:,} | "
            f"{fmt_d(r['causal_mean'])} | "
            f"{fmt_d(r['ms_mean'])} | "
            f"{fmt_d(r['nt_mean'])} | "
            f"**{fmt_d(r['delta_pb_vs_ms'])}** | "
            f"{fmt_d(r['delta_buggy_vs_causal'])} | "
            f"{fmt_d(r['delta_nt_vs_causal'])} | "
            f"{r['causal_pf']:.2f} | "
            f"{r['nt_pf']:.2f} |")
    lines.append("")

    # Outcome mix comparison
    lines.append("## Outcome mix: CAUSAL vs NT")
    lines.append("")
    lines.append("| Year | CAUSAL PT% | NT PT% | CAUSAL SL% | "
                 "NT SL% | CAUSAL Reg% | NT Reg% |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for r in summary_rows:
        lines.append(
            f"| {r['year']} | {fmt_p(r['causal_pt'])} | "
            f"{fmt_p(r['nt_pt'])} | "
            f"{fmt_p(r['causal_sl'])} | {fmt_p(r['nt_sl'])} | "
            f"{fmt_p(r['causal_reg'])} | {fmt_p(r['nt_reg'])} |")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    deltas_matched = [r["delta_pb_vs_ms"] for r in summary_rows]
    deltas_nt_vs_causal = [r["delta_nt_vs_causal"]
                              for r in summary_rows
                              if not pd.isna(r["delta_nt_vs_causal"])]
    n_pos = sum(1 for d in deltas_matched if d > 0)
    n_total = len(deltas_matched)

    lines.append(f"**CAUSAL pullback Δ vs matched baseline**:")
    for r in summary_rows:
        lines.append(
            f"- {r['year']} ({r['tag']}): "
            f"{fmt_d(r['delta_pb_vs_ms'])}/trade "
            f"(was {fmt_d(r['delta_pb_vs_ms'] + r['delta_buggy_vs_causal'])} "
            f"in BUGGY)")
    lines.append("")
    if n_pos == n_total:
        lines.append("**Pullback edge SURVIVES the bug fix** — still "
                     "positive Δ in all years.")
    elif n_pos == 0:
        lines.append("**Pullback edge DESTROYED by the bug fix** — "
                     "negative Δ in all years. The buggy collector "
                     "manufactured the entire edge via non-causal "
                     "regime-exit pricing.")
    else:
        lines.append(f"**Pullback edge MIXED** — "
                     f"{n_pos}/{n_total} years positive after fix.")
    lines.append("")
    if deltas_nt_vs_causal:
        avg_drag = np.mean(deltas_nt_vs_causal)
        lines.append(
            f"**NT vs CAUSAL drag**: average "
            f"{fmt_d(avg_drag)}/trade. Small drag = causal collector "
            f"is a faithful proxy for NT runtime. Large drag = "
            f"residual systematic difference (e.g., entry slip, "
            f"different bracket race resolution).")
    lines.append("")

    out_path = OUT / "CAUSAL_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")
    for r in summary_rows:
        print(f"  {r['year']}: causal n={r['n_causal']:,} "
               f"mean=${r['causal_mean']:.2f} PF={r['causal_pf']:.2f} "
               f"| matched=${r['ms_mean']:.2f} | "
               f"Δ_match=${r['delta_pb_vs_ms']:+.2f} | "
               f"NT mean=${r['nt_mean']:.2f}")


if __name__ == "__main__":
    main()
