"""V_A baseline reproduction analyzer.

Reads collectors/collector_v2/results/v_a_<year>/ outputs and
produces a per-year report comparing to the known prior NT-validated
V_A baseline (studies/momentum_confirm_v1/results/nt_*).
"""

from __future__ import annotations
import json
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("collectors/collector_v2/results")
PRIOR = Path("studies/momentum_confirm_v1/results")
YEARS = [2024, 2025, 2026]

# Known baselines from prior NT-validated V_A run
PRIOR_BASELINE = {
    2024: {"n": 3343, "wr": 0.352, "mean": 5.64, "pf": 1.03,
              "total": 18840, "max_dd": -44410},
    2025: {"n": 3313, "wr": 0.341, "mean": 17.97, "pf": 1.07,
              "total": 59535, "max_dd": -53020},
    2026: {"n": 1001, "wr": 0.352, "mean": -19.68, "pf": 0.93,
              "total": -19700, "max_dd": -29850},
}


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
    return {"n": n, "wr": float((s > 0).mean()),
              "mean": float(s.mean()), "median": float(s.median()),
              "sum": float(s.sum()), "pf": float(pf),
              "max_dd": max_dd(s),
              "avg_win": float(wins.mean()) if len(wins) else float("nan"),
              "avg_loss": float(losses.mean()) if len(losses)
                          else float("nan")}


def provenance_check(df):
    """Returns dict of TF → violation count."""
    out = {}
    for tf in ["30s", "1m", "3m", "5m"]:
        col = f"last_{tf}_close_ts"
        if col in df.columns:
            out[tf] = int((df[col] > df["decision_ts"]).sum())
    return out


def load_year(year):
    d = OUT / f"v_a_{year}"
    snaps = (pd.read_parquet(d / "snapshots.parquet")
                if (d / "snapshots.parquet").exists()
                else pd.DataFrame())
    trades = (pd.read_parquet(d / "trades.parquet")
                 if (d / "trades.parquet").exists()
                 else pd.DataFrame())
    diag = (json.load(open(d / "diag.json"))
              if (d / "diag.json").exists() else {})
    return snaps, trades, diag


def load_prior_nt(year):
    """Load prior NT-validated V_A trades for parity comparison."""
    p = PRIOR / f"nt_1m_momentum_{year}/nt_trades.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def main():
    lines = []
    lines.append("# V_A Baseline Reproduction via Collector V2")
    lines.append("")
    lines.append("V_A reference (1m HH/LL + momentum confirm, hold "
                 "to opposing 1m regime flip) re-run through the new "
                 "Collector V2 architecture for 2024 / 2025 / 2026.")
    lines.append("")
    lines.append("**Baseline reference**: prior NT-validated V_A run "
                 "in `studies/momentum_confirm_v1/results/nt_1m_"
                 "momentum_<year>/`. Identical strategy logic; only "
                 "the implementation differs (legacy vs new "
                 "registry/aggregator/audit infrastructure).")
    lines.append("")

    summary = []
    for year in YEARS:
        snaps, trades, diag = load_year(year)
        prior = load_prior_nt(year)
        v2 = stats(trades["net_pnl"]) if len(trades) else {"n": 0}
        prior_s = (stats(prior["net_pnl"])
                      if len(prior) else {"n": 0})
        prov = provenance_check(snaps) if len(snaps) else {}

        lines.append(f"## {year}")
        lines.append("")
        lines.append(f"Snapshots: {len(snaps):,}")
        lines.append(f"Trades:    {len(trades):,}")
        lines.append("")
        lines.append("Provenance audit (must be all 0):")
        lines.append("")
        lines.append("| TF | Violations |")
        lines.append("|---|--:|")
        for tf in ["30s", "1m", "3m", "5m"]:
            v = prov.get(tf, "N/A")
            mark = " ✓" if v == 0 else " **VIOLATION**"
            lines.append(f"| {tf} | {v}{mark} |")
        lines.append("")

        lines.append("Trade performance — Collector V2 vs prior "
                      "NT V_A baseline:")
        lines.append("")
        lines.append("| Source | n | WR | Mean $ | Med $ | "
                     "Avg Win | Avg Loss | PF | Total $ | Max DD |")
        lines.append(
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for label, s in [("Collector V2 (this run)", v2),
                            ("Prior NT V_A (baseline)", prior_s)]:
            if s.get("n", 0) == 0:
                lines.append(f"| {label} | 0 | — | — | — | — | "
                              "— | — | — | — |")
                continue
            lines.append(
                f"| {label} | {s['n']:,} | "
                f"{fmt_p(s.get('wr'))} | "
                f"{fmt_d(s.get('mean'))} | "
                f"{fmt_d(s.get('median'))} | "
                f"{fmt_d(s.get('avg_win'))} | "
                f"{fmt_d(s.get('avg_loss'))} | "
                f"{s.get('pf', 0):.2f} | "
                f"{fmt_d(s.get('sum'))} | "
                f"{fmt_d(s.get('max_dd'))} |")
        lines.append("")
        if v2.get("n") and prior_s.get("n"):
            n_d = v2["n"] - prior_s["n"]
            mean_d = v2["mean"] - prior_s["mean"]
            total_d = v2["sum"] - prior_s["sum"]
            n_d_pct = 100 * n_d / prior_s["n"]
            lines.append(
                f"- Δ trade count: {n_d:+,} "
                f"({n_d_pct:+.1f}%)")
            lines.append(
                f"- Δ mean $ / trade: **{fmt_d(mean_d)}**")
            lines.append(
                f"- Δ total $: {fmt_d(total_d)}")
        lines.append("")

        # Per-snapshot kind breakdown
        if len(snaps):
            lines.append("Snapshot mix:")
            lines.append("")
            kind_counts = snaps["kind"].value_counts().sort_index()
            for k, v in kind_counts.items():
                lines.append(f"- `{k}`: {v:,}")
            lines.append("")

        # Diag
        if diag:
            lines.append("Diagnostics:")
            lines.append("")
            for k, v in diag.items():
                lines.append(f"- {k}: {v:,}")
            lines.append("")

        summary.append({
            "year": year,
            "v2_n": v2.get("n", 0),
            "v2_mean": v2.get("mean"),
            "v2_pf": v2.get("pf"),
            "v2_total": v2.get("sum"),
            "v2_max_dd": v2.get("max_dd"),
            "prior_n": prior_s.get("n", 0),
            "prior_mean": prior_s.get("mean"),
            "prior_total": prior_s.get("sum"),
            "n_snaps": len(snaps),
            "prov_ok": all(v == 0 for v in prov.values())
                          if prov else False,
        })

    # Cross-year summary
    lines.append("## Cross-year summary")
    lines.append("")
    lines.append("| Year | n_snaps | n_trades_v2 | n_trades_prior | "
                 "Δn | Mean $ V2 | Mean $ Prior | Δ Mean | "
                 "Total V2 | Total Prior | Provenance OK |")
    lines.append(
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|")
    for r in summary:
        n_d = (r["v2_n"] - r["prior_n"]
                 if r["prior_n"] else r["v2_n"])
        mean_d = ((r["v2_mean"] - r["prior_mean"])
                    if r["v2_mean"] is not None
                    and r["prior_mean"] is not None
                    else None)
        lines.append(
            f"| {r['year']} | {r['n_snaps']:,} | "
            f"{r['v2_n']:,} | {r['prior_n']:,} | "
            f"{n_d:+,} | "
            f"{fmt_d(r['v2_mean'])} | "
            f"{fmt_d(r['prior_mean'])} | "
            f"{fmt_d(mean_d)} | "
            f"{fmt_d(r['v2_total'])} | "
            f"{fmt_d(r['prior_total'])} | "
            f"{'✓' if r['prov_ok'] else '**FAIL**'} |")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    all_prov = all(r["prov_ok"] for r in summary)
    parity_close = all(
        abs(r["v2_n"] - r["prior_n"]) / max(1, r["prior_n"]) < 0.05
        for r in summary if r["prior_n"])
    lines.append(f"Provenance: "
                 f"{'✓ all years 0 violations' if all_prov else '**violations found**'}")
    lines.append(f"Trade-count parity vs prior NT baseline (within "
                 f"5%): "
                 f"{'✓' if parity_close else '**diverged**'}")
    lines.append("")

    out_path = OUT.parent / "reports" / "V_A_BASELINE_REPRODUCTION.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")
    print("\nQuick scan:")
    for r in summary:
        print(f"  {r['year']}: V2 n={r['v2_n']:,} mean=${r['v2_mean']:.2f}"
               f" PF={r['v2_pf']:.2f} total=${r['v2_total']:,.0f} | "
               f"Prior n={r['prior_n']:,} mean=${r['prior_mean']:.2f} "
               f"total=${r['prior_total']:,.0f} | "
               f"prov_ok={r['prov_ok']}")


if __name__ == "__main__":
    main()
