"""Compare NT 5m-aligned V_A vs offline anatomy + baseline NT V_A."""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/momentum_confirm_5m_v1/results")
ANATOMY_OUT = Path("studies/momentum_2026_anatomy_v1/results")
BASELINE_OUT = Path("studies/momentum_confirm_v1/results")
YEARS = [2024, 2025, 2026]


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def max_dd(s):
    if len(s) == 0:
        return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats(pnl):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))
    return {
        "n": n, "wr": float((s > 0).mean()),
        "mean": float(s.mean()), "median": float(s.median()),
        "sum": float(s.sum()), "pf": float(pf),
        "max_dd": max_dd(s),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses)
                      else float("nan")}


def main():
    lines = []
    lines.append("# 5m-Aligned V_A — NT Validation")
    lines.append("")
    lines.append("**Strategy**: V_A momentum-confirm + 5m regime "
                 "alignment gate. 5m regime aggregated from 1m bars "
                 "internally (catalog has no 5m bars).")
    lines.append("")
    lines.append("**Hypothesis** (from anatomy v1): adding 5m "
                 "alignment lifts mean to ~$66/trade, reduces max "
                 "DD 4-6×, makes 2026 positive.")
    lines.append("")

    summary = []
    for year in YEARS:
        nt_path = OUT / f"nt_{year}" / "nt_trades.parquet"
        anatomy_path = (ANATOMY_OUT
                          / f"features_1m_momentum_{year}.parquet")
        baseline_path = (BASELINE_OUT
                            / f"nt_1m_momentum_{year}"
                            / "nt_trades.parquet")

        nt = (pd.read_parquet(nt_path) if nt_path.exists()
                else pd.DataFrame())
        anatomy = (pd.read_parquet(anatomy_path)
                     if anatomy_path.exists() else pd.DataFrame())
        baseline_nt = (pd.read_parquet(baseline_path)
                          if baseline_path.exists()
                          else pd.DataFrame())

        # Offline 5m-aligned filter applied to anatomy data
        offline_5m = (anatomy[anatomy["regime_5m_aligned"] == 1]
                        if len(anatomy) else pd.DataFrame())

        nt_s = stats(nt["net_pnl"]) if len(nt) else {"n": 0}
        off_s = (stats(offline_5m["final_net_pnl"])
                   if len(offline_5m) else {"n": 0})
        base_s = (stats(baseline_nt["net_pnl"])
                    if len(baseline_nt) else {"n": 0})

        lines.append(f"## {year}")
        lines.append("")
        lines.append(
            f"NT (5m-aligned): n={nt_s['n']:,}, "
            f"Offline (5m-aligned): n={off_s['n']:,}, "
            f"NT baseline (no 5m gate): n={base_s['n']:,}")
        lines.append("")
        lines.append("| Source | n | WR | Mean $ | Med $ | Avg Win | "
                     "Avg Loss | PF | Total $ | Max DD |")
        lines.append(
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for label, s in [
            ("NT 5m-aligned (this study)", nt_s),
            ("Offline 5m-aligned (anatomy)", off_s),
            ("NT baseline V_A (no 5m gate)", base_s),
        ]:
            if s["n"] == 0:
                lines.append(f"| {label} | 0 | — | — | — | — | "
                              "— | — | — | — |")
                continue
            lines.append(
                f"| {label} | {s['n']:,} | {fmt_p(s['wr'])} | "
                f"{fmt_d(s['mean'])} | {fmt_d(s['median'])} | "
                f"{fmt_d(s['avg_win'])} | "
                f"{fmt_d(s['avg_loss'])} | {s['pf']:.2f} | "
                f"{fmt_d(s['sum'])} | {fmt_d(s['max_dd'])} |")
        lines.append("")
        if nt_s["n"] and off_s["n"]:
            delta_n = nt_s["n"] - off_s["n"]
            delta_mean = nt_s["mean"] - off_s["mean"]
            lines.append(
                f"- **NT vs Offline parity**: count Δ "
                f"{delta_n:+,} ({100*delta_n/off_s['n']:+.1f}%), "
                f"mean $ Δ **{fmt_d(delta_mean)}/trade**")
        if nt_s["n"] and base_s["n"]:
            lines.append(
                f"- **NT 5m-gate vs NT baseline**: trade count "
                f"reduction {fmt_p(1 - nt_s['n']/base_s['n'])}, "
                f"mean $ improvement "
                f"{fmt_d(nt_s['mean'] - base_s['mean'])}")
        lines.append("")

        summary.append({
            "year": year,
            "nt_n": nt_s.get("n", 0),
            "nt_mean": nt_s.get("mean"),
            "nt_pf": nt_s.get("pf"),
            "nt_total": nt_s.get("sum"),
            "nt_dd": nt_s.get("max_dd"),
            "nt_wr": nt_s.get("wr"),
            "off_n": off_s.get("n", 0),
            "off_mean": off_s.get("mean"),
            "off_total": off_s.get("sum"),
            "base_n": base_s.get("n", 0),
            "base_mean": base_s.get("mean"),
            "base_total": base_s.get("sum"),
            "base_dd": base_s.get("max_dd"),
        })

    # Cross-year summary
    lines.append("## Cross-year summary")
    lines.append("")
    lines.append("| Year | NT n | NT WR | NT Mean | NT PF | "
                 "NT Total | NT Max DD | Off Mean | Δ NT-Off | "
                 "Base Mean | Base DD | Improv vs Base |")
    lines.append(
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in summary:
        delta_off = ((r["nt_mean"] - r["off_mean"])
                       if r["nt_mean"] is not None
                       and r["off_mean"] is not None
                       else None)
        improv_base = ((r["nt_mean"] - r["base_mean"])
                          if r["nt_mean"] is not None
                          and r["base_mean"] is not None
                          else None)
        lines.append(
            f"| {r['year']} | {r['nt_n']:,} | "
            f"{fmt_p(r['nt_wr'])} | "
            f"{fmt_d(r['nt_mean'])} | "
            f"{r['nt_pf']:.2f} | "
            f"{fmt_d(r['nt_total'])} | "
            f"{fmt_d(r['nt_dd'])} | "
            f"{fmt_d(r['off_mean'])} | "
            f"{fmt_d(delta_off)} | "
            f"{fmt_d(r['base_mean'])} | "
            f"{fmt_d(r['base_dd'])} | "
            f"{fmt_d(improv_base)} |")
    lines.append("")

    # 3-year aggregate
    lines.append("## 3-year aggregate (NT 5m-aligned)")
    lines.append("")
    all_pnls = []
    for year in YEARS:
        p = OUT / f"nt_{year}" / "nt_trades.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            all_pnls.append(df["net_pnl"])
    if all_pnls:
        all_pnl = pd.concat(all_pnls, ignore_index=True)
        s = stats(all_pnl)
        lines.append(
            f"- Total trades: {s['n']:,}")
        lines.append(f"- Mean $/trade: {fmt_d(s['mean'])}")
        lines.append(f"- WR: {fmt_p(s['wr'])}")
        lines.append(f"- PF: {s['pf']:.2f}")
        lines.append(f"- Total: **{fmt_d(s['sum'])}**")
        lines.append(f"- Avg Win: {fmt_d(s['avg_win'])}")
        lines.append(f"- Avg Loss: {fmt_d(s['avg_loss'])}")

    # Verdict
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    n_pos = sum(1 for r in summary
                   if r["nt_mean"] is not None and r["nt_mean"] > 0)
    lines.append(f"NT 5m-aligned positive in {n_pos}/{len(summary)} "
                 f"years.")
    lines.append("")

    out_path = OUT / "NT_5M_VALIDATION_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")
    for r in summary:
        print(f"  {r['year']}: NT n={r['nt_n']:,} "
               f"mean=${r['nt_mean']:.2f} PF={r['nt_pf']:.2f} "
               f"total=${r['nt_total']:,.0f} DD=${r['nt_dd']:,.0f} "
               f"| off mean=${r['off_mean']:.2f} | "
               f"base mean=${r['base_mean']:.2f}")


if __name__ == "__main__":
    main()
