"""Analyzer — momentum-confirm offline vs NT comparison."""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/momentum_confirm_v1/results")
YEARS = [2024, 2025, 2026]
MODES = ["1m_momentum", "30s_momentum"]
NQ_MULT = 20.0


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


def stats(df, pnl_col, dur_col=None, dir_col=None):
    if len(df) == 0:
        return {"n": 0}
    pnl = df[pnl_col].dropna()
    n = len(pnl)
    if n == 0:
        return {"n": 0}
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))
    out = {
        "n": n,
        "wr": float((pnl > 0).mean()),
        "mean": float(pnl.mean()),
        "median": float(pnl.median()),
        "sum": float(pnl.sum()),
        "pf": float(pf),
        "max_dd": max_drawdown(pnl),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses)
                      else float("nan"),
    }
    if dur_col and dur_col in df.columns:
        out["avg_dur_s"] = float(df[dur_col].mean())
        out["med_dur_s"] = float(df[dur_col].median())
    if dir_col and dir_col in df.columns:
        out["long_pct"] = float((df[dir_col] == 1).mean())
        out["short_pct"] = float((df[dir_col] == -1).mean())
    return out


def main():
    lines = []
    lines.append("# Momentum-Confirm Regime-Exit NT Validation")
    lines.append("")
    lines.append("**Strategy**: enter on 1m regime flip after "
                 "confirmation (HH/LL + bar closes in regime "
                 "direction). Hold to opposing 1m regime flip.")
    lines.append("")
    lines.append("**Two versions**:")
    lines.append("- V_A (1m_momentum): bar+1 makes HH/LL + bar+1 "
                 "closes in regime direction. Fill at flip+90s.")
    lines.append("- V_B (30s_momentum): first 30s after flip makes "
                 "HH/LL + 30s window closes in regime direction. "
                 "Fill at flip+60s.")
    lines.append("")
    lines.append("**Causal exit**: at next opposing 1m flip's CLOSE. "
                 "NT submits market exit on flip detection, fills at "
                 "next 1s bar.")
    lines.append("")
    lines.append("**Cost**: $5 commission + 1-tick adverse exit slip.")
    lines.append("")

    summary = []
    for year in YEARS:
        for mode in MODES:
            label = "V_A" if mode == "1m_momentum" else "V_B"
            offline_path = (OUT / (
                f"offline_v_a_{year}.parquet"
                if mode == "1m_momentum"
                else f"offline_v_b_{year}.parquet"))
            nt_path = (OUT / f"nt_{mode}_{year}"
                         / "nt_trades.parquet")

            offline_exists = offline_path.exists()
            nt_exists = nt_path.exists()

            offline = pd.read_parquet(
                offline_path) if offline_exists else pd.DataFrame()
            nt = pd.read_parquet(
                nt_path) if nt_exists else pd.DataFrame()

            off_s = stats(offline, "net_pnl",
                            dur_col="regime_dur_s",
                            dir_col="direction")
            if len(nt):
                nt = nt.copy()
                nt["hold_s"] = (nt["exit_ts"] - nt["entry_ts"]) / 1e9
            nt_s = stats(nt, "net_pnl",
                           dur_col="hold_s",
                           dir_col="direction")

            lines.append(f"## {year} — {label} ({mode})")
            lines.append("")
            n_off = off_s.get("n", 0)
            n_nt = nt_s.get("n", 0)
            count_delta = n_nt - n_off
            mean_delta = (nt_s.get("mean", float("nan"))
                            - off_s.get("mean", float("nan")))
            lines.append(
                f"Offline n={n_off:,}, NT n={n_nt:,}, "
                f"Δ count {count_delta:+,} "
                f"({100*count_delta/n_off:+.1f}%). "
                f"Mean $ Δ: **{fmt_d(mean_delta)}/trade**.")
            lines.append("")
            lines.append("| Source | n | WR% | Mean $ | Median $ | "
                         "Avg Win | Avg Loss | PF | Total $ | "
                         "Max DD | Long% | Short% | "
                         "Avg Dur | Med Dur |")
            lines.append(
                "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
            for src, s in [("Offline", off_s), ("NT", nt_s)]:
                if s["n"] == 0:
                    lines.append(f"| {src} | 0 | — | — | — | — | "
                                  "— | — | — | — | — | — | — | — |")
                    continue
                lines.append(
                    f"| {src} | {s['n']:,} | {fmt_p(s['wr'])} | "
                    f"{fmt_d(s['mean'])} | {fmt_d(s['median'])} | "
                    f"{fmt_d(s.get('avg_win'))} | "
                    f"{fmt_d(s.get('avg_loss'))} | "
                    f"{s['pf']:.2f} | {fmt_d(s['sum'])} | "
                    f"{fmt_d(s['max_dd'])} | "
                    f"{fmt_p(s.get('long_pct'))} | "
                    f"{fmt_p(s.get('short_pct'))} | "
                    f"{(s.get('avg_dur_s', 0) or 0)/60:.1f}min | "
                    f"{(s.get('med_dur_s', 0) or 0)/60:.1f}min |")
            lines.append("")

            summary.append({
                "year": year, "mode": mode, "label": label,
                "off_n": n_off, "nt_n": n_nt,
                "off_mean": off_s.get("mean", float("nan")),
                "nt_mean": nt_s.get("mean", float("nan")),
                "off_wr": off_s.get("wr", float("nan")),
                "nt_wr": nt_s.get("wr", float("nan")),
                "off_pf": off_s.get("pf", float("nan")),
                "nt_pf": nt_s.get("pf", float("nan")),
                "nt_total": nt_s.get("sum", float("nan")),
                "nt_max_dd": nt_s.get("max_dd", float("nan")),
                "delta_per_trade": (nt_s.get("mean", float("nan"))
                                       - off_s.get("mean",
                                                     float("nan"))),
            })

    # Cross-year comparison
    lines.append("## Cross-year summary — NT only")
    lines.append("")
    lines.append("| Year | Mode | NT n | NT WR | NT Mean $ | "
                 "NT PF | NT Total $ | NT Max DD | "
                 "Off→NT Δ/trade |")
    lines.append(
        "|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for r in summary:
        lines.append(
            f"| {r['year']} | {r['label']} | {r['nt_n']:,} | "
            f"{fmt_p(r['nt_wr'])} | {fmt_d(r['nt_mean'])} | "
            f"{r['nt_pf']:.2f} | {fmt_d(r['nt_total'])} | "
            f"{fmt_d(r['nt_max_dd'])} | "
            f"{fmt_d(r['delta_per_trade'])} |")
    lines.append("")

    # Aggregate per mode across years (NT only)
    lines.append("## Aggregate per mode (3-year NT totals)")
    lines.append("")
    lines.append("| Mode | NT n | NT mean $ | NT total $ | NT PF |")
    lines.append("|---|--:|--:|--:|--:|")
    for mode in MODES:
        rs = [r for r in summary if r["mode"] == mode]
        if not rs:
            continue
        # Reload all NT trades for proper aggregation
        all_pnls = []
        for r in rs:
            year = r["year"]
            p = OUT / f"nt_{mode}_{year}/nt_trades.parquet"
            if p.exists():
                df = pd.read_parquet(p)
                all_pnls.append(df["net_pnl"])
        if not all_pnls:
            continue
        all_pnl = pd.concat(all_pnls, ignore_index=True)
        wins = all_pnl[all_pnl > 0]
        losses = all_pnl[all_pnl < 0]
        pf = (wins.sum() / abs(losses.sum())
                if len(losses) and losses.sum() != 0
                else float("inf"))
        lines.append(
            f"| {mode} | {len(all_pnl):,} | "
            f"{fmt_d(all_pnl.mean())} | "
            f"{fmt_d(all_pnl.sum())} | {pf:.2f} |")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    n_pos_nt = sum(1 for r in summary
                      if not pd.isna(r["nt_mean"])
                      and r["nt_mean"] > 0)
    drag_avg = np.nanmean([r["delta_per_trade"] for r in summary])
    lines.append(
        f"**NT runs positive across {n_pos_nt}/{len(summary)} "
        f"year×mode cells.**")
    lines.append("")
    lines.append(
        f"**Average offline→NT drag**: {fmt_d(drag_avg)}/trade. "
        f"Small drag = collector is faithful proxy. Large drag = "
        f"residual systematic difference.")
    lines.append("")

    out_path = OUT / "MOMENTUM_CONFIRM_NT_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")
    print("\nQuick scan:")
    for r in summary:
        print(f"  {r['year']} {r['label']}: "
               f"off n={r['off_n']:,} mean=${r['off_mean']:.2f} | "
               f"NT n={r['nt_n']:,} mean=${r['nt_mean']:.2f} "
               f"PF={r['nt_pf']:.2f} total=${r['nt_total']:,.0f} "
               f"DD=${r['nt_max_dd']:,.0f} | "
               f"Δ=${r['delta_per_trade']:+.2f}/trade")


if __name__ == "__main__":
    main()
