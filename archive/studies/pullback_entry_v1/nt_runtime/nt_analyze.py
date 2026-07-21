"""Compare NT runtime trades vs offline collector trades, per year.

For each year (2024, 2026):
  - Load NT trade log (nt_trades.parquet)
  - Load offline pullback rows (oos_pullback_1atr_<year>.parquet)
  - Compute population stats for each
  - Match trades by signal_time / decision_ts to identify
    same-trade pairs and report economic divergence

Output: NT_PARITY_REPORT.md
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent.parent
os.chdir(project_root)

OUT_BASE = Path("studies/pullback_entry_v1/results")
YEARS = [2024, 2026]


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def max_drawdown(pnl_chronological):
    if len(pnl_chronological) == 0:
        return 0.0
    cum = pd.Series(pnl_chronological).cumsum().values
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
        "mean": float(s.mean()),
        "median": float(s.median()),
        "sum": float(s.sum()),
        "pf": float(wins.sum() / abs(losses.sum())) if len(losses)
                and losses.sum() != 0 else float("inf"),
        "max_dd": max_drawdown(s),
    }
    if outcome is not None:
        oc = pd.Series(outcome)
        out["pt_pct"] = float((oc == "pt").mean())
        out["sl_pct"] = float((oc == "sl").mean())
        out["regime_pct"] = float((oc == "regime").mean())
    return out


def main():
    lines = []
    lines.append("# Pullback NT Runtime Parity Validation")
    lines.append("")
    lines.append("**Rule**: HH/LL-confirmed 1m regime, wait for first "
                 "1.0 ATR pullback, decision/fill timing matches "
                 "offline. Bracket: PT 1.0 ATR / SL 0.75 ATR. Exit on "
                 "PT, SL, opposing 1m regime flip, or 30-min cap.")
    lines.append("")
    lines.append("**NT runtime mechanics**: market entry order "
                 "submitted 1 bar early so NT venue fills at OPEN of "
                 "target fill_ts bar (matches collector's "
                 "fill_price = bar.open[fill_ts] convention). PT/SL "
                 "levels computed from ACTUAL NT fill price. PT/SL "
                 "monitored intra-bar via 1s bar H/L. Regime flip "
                 "detected on 1m bar processing → market exit submits "
                 "→ NT fills at next 1s bar OPEN.")
    lines.append("")
    lines.append("**Known structural divergence**: collector exits "
                 "regime trades at OPEN of next flip's 1m bar (~60s "
                 "before flip can actually be detected). NT detects "
                 "the flip only at 1m bar CLOSE, so the trade is "
                 "exposed to ~60s of additional price action during "
                 "the flip-bar's adverse move. Expect SL hits to be "
                 "elevated vs collector.")
    lines.append("")

    summary_rows = []
    for year in YEARS:
        nt_dir = OUT_BASE / f"nt_runtime_{year}"
        nt_trades_path = nt_dir / "nt_trades.parquet"
        offline_path = OUT_BASE / f"oos_pullback_1atr_{year}.parquet"

        if not nt_trades_path.exists():
            lines.append(f"## {year} — NT trades not found at "
                         f"{nt_trades_path}")
            continue

        nt = pd.read_parquet(nt_trades_path)
        off = pd.read_parquet(offline_path)
        nt_n = len(nt)
        off_n = len(off)

        # Outcome maps
        nt_outcome = nt["exit_reason"]  # pt/sl/regime/timeout
        off_outcome = off["bracket_100_75_outcome"]

        # PnL: NT actual vs collector
        nt_actual_stats = stats(nt["net_pnl_actual"], nt_outcome,
                                  "NT actual (real fills)")
        nt_ref_stats = stats(nt["net_pnl_ref"].dropna(), nt_outcome,
                               "NT ref (collector exit price)")
        off_stats = stats(off["bracket_100_75_pnl"], off_outcome,
                            "Offline collector")

        lines.append(f"## {year}")
        lines.append("")
        lines.append(f"NT trades: {nt_n:,}, Offline trades: {off_n:,}, "
                     f"Δ count: {nt_n - off_n:+,} "
                     f"({100*(nt_n - off_n)/off_n:+.1f}%)")
        lines.append("")
        lines.append("| Population | n | PT% | SL% | Reg% | Mean $ | "
                     "Median $ | PF | Total $ | Max DD |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for s in [nt_actual_stats, nt_ref_stats, off_stats]:
            if s["n"] == 0:
                continue
            lines.append(
                f"| {s['label']} | {s['n']:,} | "
                f"{fmt_p(s.get('pt_pct'))} | "
                f"{fmt_p(s.get('sl_pct'))} | "
                f"{fmt_p(s.get('regime_pct'))} | "
                f"{fmt_d(s['mean'])} | {fmt_d(s['median'])} | "
                f"{s['pf']:.2f} | {fmt_d(s['sum'])} | "
                f"{fmt_d(s['max_dd'])} |")
        lines.append("")

        # Slippage diagnostics
        if "exit_slippage_dollars" in nt.columns:
            es = nt["exit_slippage_dollars"].dropna()
            es_by_outcome = nt.groupby("exit_reason")[
                "exit_slippage_dollars"].agg(["mean", "sum", "count"])
            lines.append("Exit slippage (NT actual vs expected):")
            lines.append("")
            lines.append("| Exit reason | n | Mean $ slip | Total $ |")
            lines.append("|---|--:|--:|--:|")
            for reason, row in es_by_outcome.iterrows():
                lines.append(
                    f"| {reason} | {int(row['count']):,} | "
                    f"{fmt_d(row['mean'])} | {fmt_d(row['sum'])} |")
            lines.append(
                f"| **All** | {len(es):,} | "
                f"{fmt_d(es.mean())} | {fmt_d(es.sum())} |")
            lines.append("")

        # Trade pairing — match by signal_time
        if "signal_time" in nt.columns and "signal_time_ts" in off.columns:
            nt_sig = nt.copy()
            nt_sig["sig_key"] = nt_sig["signal_time"]
            off_sig = off.copy()
            off_sig["sig_key"] = off_sig["signal_time_ts"]
            both = nt_sig[["sig_key", "exit_reason",
                              "net_pnl_actual"]].merge(
                off_sig[["sig_key", "bracket_100_75_outcome",
                          "bracket_100_75_pnl"]],
                on="sig_key", how="outer", indicator=True)
            n_both = int((both["_merge"] == "both").sum())
            n_nt_only = int((both["_merge"] == "left_only").sum())
            n_off_only = int((both["_merge"] == "right_only").sum())
            lines.append(
                f"Trade pairing by signal_time: {n_both:,} matched, "
                f"{n_nt_only:,} NT-only, {n_off_only:,} offline-only.")
            lines.append("")

            # Outcome agreement on matched pairs
            matched = both[both["_merge"] == "both"].copy()
            same_outcome = (matched["exit_reason"] ==
                              matched["bracket_100_75_outcome"]).sum()
            lines.append(
                f"Of {n_both:,} matched: outcome agreement "
                f"{same_outcome:,} "
                f"({100*same_outcome/n_both:.1f}%).")
            lines.append("")

            # Cross-tab of NT outcome vs Offline outcome
            ct = pd.crosstab(matched["exit_reason"],
                              matched["bracket_100_75_outcome"],
                              margins=True)
            lines.append("Outcome cross-tab (rows = NT, cols = offline):")
            lines.append("")
            lines.append("```")
            lines.append(ct.to_string())
            lines.append("```")
            lines.append("")

            # Mean PnL on matched pairs
            paired_nt_mean = matched["net_pnl_actual"].mean()
            paired_off_mean = matched["bracket_100_75_pnl"].mean()
            paired_delta = paired_nt_mean - paired_off_mean
            lines.append(
                f"On {n_both:,} matched pairs — NT mean "
                f"{fmt_d(paired_nt_mean)}, Offline mean "
                f"{fmt_d(paired_off_mean)}, Δ "
                f"**{fmt_d(paired_delta)}**.")
            lines.append("")

            # Sample mismatches
            mismatches = matched[
                matched["exit_reason"] !=
                  matched["bracket_100_75_outcome"]]
            if len(mismatches):
                ct_mis = pd.crosstab(mismatches["exit_reason"],
                                       mismatches[
                                           "bracket_100_75_outcome"])
                lines.append(f"**Mismatches** ({len(mismatches):,} of "
                             f"{n_both:,}):")
                lines.append("")
                lines.append("```")
                lines.append(ct_mis.to_string())
                lines.append("```")
                lines.append("")

        summary_rows.append({
            "year": year,
            "nt_n": nt_n, "off_n": off_n,
            "nt_mean": nt_actual_stats["mean"],
            "off_mean": off_stats["mean"],
            "delta_per_trade": (nt_actual_stats["mean"]
                                  - off_stats["mean"]),
            "nt_pf": nt_actual_stats["pf"],
            "off_pf": off_stats["pf"],
            "nt_total": nt_actual_stats["sum"],
            "off_total": off_stats["sum"],
            "nt_pt": nt_actual_stats.get("pt_pct"),
            "off_pt": off_stats.get("pt_pct"),
            "nt_sl": nt_actual_stats.get("sl_pct"),
            "off_sl": off_stats.get("sl_pct"),
            "nt_dd": nt_actual_stats["max_dd"],
        })

    # Cross-year summary
    lines.append("## Cross-year NT vs Offline summary")
    lines.append("")
    lines.append("| Year | NT n | Off n | NT mean $ | Off mean $ | "
                 "Δ/trade | NT PT% | Off PT% | NT SL% | Off SL% | "
                 "NT PF | Off PF | NT total | NT max DD |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in summary_rows:
        lines.append(
            f"| {r['year']} | {r['nt_n']:,} | {r['off_n']:,} | "
            f"{fmt_d(r['nt_mean'])} | {fmt_d(r['off_mean'])} | "
            f"**{fmt_d(r['delta_per_trade'])}** | "
            f"{fmt_p(r['nt_pt'])} | {fmt_p(r['off_pt'])} | "
            f"{fmt_p(r['nt_sl'])} | {fmt_p(r['off_sl'])} | "
            f"{r['nt_pf']:.2f} | {r['off_pf']:.2f} | "
            f"{fmt_d(r['nt_total'])} | {fmt_d(r['nt_dd'])} |")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    for r in summary_rows:
        if r["nt_total"] > 0 and r["nt_pf"] > 1.0:
            lines.append(
                f"- **{r['year']}**: NT runtime profitable. "
                f"PF {r['nt_pf']:.2f}, total {fmt_d(r['nt_total'])}, "
                f"max DD {fmt_d(r['nt_dd'])}. "
                f"Δ vs offline: {fmt_d(r['delta_per_trade'])}/trade.")
        else:
            lines.append(
                f"- **{r['year']}**: NT runtime "
                f"{'unprofitable' if r['nt_total'] <= 0 else 'marginal'}. "
                f"PF {r['nt_pf']:.2f}, total {fmt_d(r['nt_total'])}.")
    lines.append("")

    out_path = OUT_BASE / "NT_PARITY_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")
    for r in summary_rows:
        print(f"  {r['year']}: NT n={r['nt_n']:,} mean=${r['nt_mean']:.2f}"
               f" PF={r['nt_pf']:.2f} total=${r['nt_total']:,.0f} | "
               f"Off mean=${r['off_mean']:.2f} PF={r['off_pf']:.2f} "
               f"| Δ=${r['delta_per_trade']:+.2f}/trade")


if __name__ == "__main__":
    main()
