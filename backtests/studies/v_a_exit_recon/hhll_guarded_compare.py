"""Compare HH/LL tick-NT vs guarded variants vs baselines.

Loads four runs:
  - hhll_FebSep_audit (or hhll_FebSep): unguarded HH/LL
  - baseline_FebSep: unguarded baseline (regime-only)
  - hhll_guarded_FebSep: guarded HH/LL (no-entry-after 14:45,
    force-flat 14:58)
  - baseline_guarded_FebSep: guarded baseline

Compares on Feb-Sep 2025 RTH. Reports per-run economics and
slippage diagnostics.
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

CT = pytz.timezone("America/Chicago")
TICK_NT = Path("collectors/collector_v2/results/tick_nt")
OUT = Path("studies/v_a_exit_recon/results")


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.1f}%"


def fmt_pf(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"{v:.2f}"


def max_dd(s):
    if len(s) == 0: return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats(pnl, hold_s=None):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0: return {"n": 0}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
          if len(losses) and losses.sum() != 0
          else float("inf"))
    out = {"n": n, "wr": float((s > 0).mean()),
              "mean": float(s.mean()), "sum": float(s.sum()),
              "pf": float(pf), "max_dd": max_dd(s),
              "avg_win": (float(wins.mean()) if len(wins)
                            else 0.0),
              "avg_loss": (float(losses.mean()) if len(losses)
                              else 0.0)}
    if hold_s is not None and len(hold_s):
        out["med_hold_s"] = float(pd.Series(hold_s).median())
    return out


def find_run_dir(prefix: str) -> Path | None:
    candidates = sorted(TICK_NT.glob(f"{prefix}*"))
    if not candidates: return None
    return candidates[-1]


def load_run(prefix: str):
    d = find_run_dir(prefix)
    if d is None: return None, None
    tp = d / "trades.parquet"
    if not tp.exists(): return None, None
    trades = pd.read_parquet(tp)
    diag_p = d / "diag.json"
    diag = json.load(open(diag_p)) if diag_p.exists() else {}
    return trades, diag


def main():
    feb_start = pd.Timestamp("2025-02-01", tz="UTC").value
    sep_end = pd.Timestamp("2025-10-01", tz="UTC").value

    runs = {
        "hhll_unguarded": "hhll_FebSep_audit",
        "baseline_unguarded": "baseline_FebSep",
        "hhll_guarded": "hhll_guarded_FebSep",
        "baseline_guarded": "baseline_guarded_FebSep",
    }
    loaded = {}
    for label, prefix in runs.items():
        trades, diag = load_run(prefix)
        if trades is None:
            print(f"  Missing {prefix} — skip {label}")
            continue
        rth = trades[
            (trades["session"] == "RTH")
            & (trades["entry_ts"] >= feb_start)
            & (trades["entry_ts"] < sep_end)].copy()
        loaded[label] = {"trades": rth, "diag": diag}
        print(f"  {label}: {len(rth):,} RTH Feb-Sep trades, "
              f"diag entries_filled={diag.get('entries_filled', '?')}")

    if not loaded:
        print("Nothing to compare"); return

    # ---- Build report ----
    lines = []
    lines.append("# HH/LL Tick-NT — Guarded vs Unguarded Comparison")
    lines.append("")
    lines.append("Compares the original tick-NT HH/LL run against a "
                 "version with live-tradable guardrails:")
    lines.append("")
    lines.append("- **No new entries after 14:45 CT** "
                  "(no_entry_after_min_ct=885)")
    lines.append("- **Force flat at 14:58 CT** "
                  "(force_flat_at_min_ct=898)")
    lines.append("")
    lines.append("Both HH/LL and baseline (regime-only) variants "
                  "are run with and without guardrails for clean "
                  "attribution.")
    lines.append("")
    lines.append("Window: NQ RTH Feb-Sep 2025, $5 commission, "
                  "tick-driven execution")
    lines.append("")

    # Diag table
    lines.append("## Diagnostic counters")
    lines.append("")
    lines.append("| Counter | "
                  + " | ".join(loaded.keys())
                  + " |")
    lines.append("|" + "|".join(["---"] * (len(loaded) + 1)) + "|")
    keys = ["entries_filled", "entries_rejected",
              "rejected_after_no_entry_cutoff",
              "regime_exits", "hhll_armed", "hhll_exits",
              "force_flat_exits"]
    for k in keys:
        cells = [k]
        for label, info in loaded.items():
            cells.append(f"{info['diag'].get(k, 0):,}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # Headline economics
    lines.append("## Headline economics — NQ RTH Feb-Sep 2025")
    lines.append("")
    lines.append("| Run | n | WR | Mean $ | PF | Total $ | "
                  "Max DD | Med Hold s | Avg Win | Avg Loss |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for label, info in loaded.items():
        rth = info["trades"]
        s = stats(rth["net_pnl"], rth["hold_s"])
        lines.append(
            f"| **{label}** | {s['n']:,} | "
            f"{fmt_p(s['wr'])} | "
            f"{fmt_d(s['mean'])} | "
            f"{fmt_pf(s['pf'])} | "
            f"{fmt_d(s['sum'])} | "
            f"{fmt_d(s['max_dd'])} | "
            f"{s.get('med_hold_s', 0):.0f} | "
            f"{fmt_d(s['avg_win'])} | "
            f"{fmt_d(s['avg_loss'])} |")
    lines.append("")

    # Δ comparison
    if "hhll_guarded" in loaded and "hhll_unguarded" in loaded:
        s_unguarded = stats(loaded["hhll_unguarded"]["trades"]["net_pnl"])
        s_guarded = stats(loaded["hhll_guarded"]["trades"]["net_pnl"])
        lines.append("## Δ HH/LL guarded − HH/LL unguarded")
        lines.append("")
        lines.append(f"- Trade count: {s_guarded['n']:,} vs "
                      f"{s_unguarded['n']:,} "
                      f"({s_guarded['n']-s_unguarded['n']:+,} from cutoffs)")
        lines.append(f"- Mean $/trade: {fmt_d(s_guarded['mean'])} vs "
                      f"{fmt_d(s_unguarded['mean'])} "
                      f"({fmt_d(s_guarded['mean']-s_unguarded['mean'])})")
        lines.append(f"- Total $: {fmt_d(s_guarded['sum'])} vs "
                      f"{fmt_d(s_unguarded['sum'])} "
                      f"({fmt_d(s_guarded['sum']-s_unguarded['sum'])})")
        lines.append(f"- WR: {fmt_p(s_guarded['wr'])} vs "
                      f"{fmt_p(s_unguarded['wr'])}")
        lines.append("")

    if "hhll_guarded" in loaded and "baseline_guarded" in loaded:
        s_h = stats(loaded["hhll_guarded"]["trades"]["net_pnl"])
        s_b = stats(loaded["baseline_guarded"]["trades"]["net_pnl"])
        lines.append("## HH/LL overlay impact under guardrails")
        lines.append("")
        lines.append(f"- HH/LL guarded: {fmt_d(s_h['mean'])}/trade, "
                      f"{fmt_d(s_h['sum'])} total")
        lines.append(f"- Baseline guarded: {fmt_d(s_b['mean'])}/trade, "
                      f"{fmt_d(s_b['sum'])} total")
        lines.append(f"- **Δ (HH/LL − baseline) under guardrails**: "
                      f"{fmt_d(s_h['mean']-s_b['mean'])}/trade, "
                      f"{fmt_d(s_h['sum']-s_b['sum'])} total")
        lines.append("")

    # Exit-reason mix
    if "hhll_guarded" in loaded:
        rth = loaded["hhll_guarded"]["trades"]
        if "exit_reason" in rth.columns:
            lines.append("## Exit reason mix — HH/LL guarded")
            lines.append("")
            mix = rth["exit_reason"].value_counts()
            for reason, cnt in mix.items():
                pct = cnt / len(rth)
                sub = rth[rth["exit_reason"] == reason]
                ss = stats(sub["net_pnl"])
                lines.append(
                    f"- **{reason}**: {cnt:,} trades "
                    f"({fmt_p(pct)}), mean {fmt_d(ss['mean'])}, "
                    f"WR {fmt_p(ss['wr'])}")
            lines.append("")

    # Forensic top-5 contribution
    lines.append("## Forensic — top-5 worst-slip contribution "
                  "(from prior audit)")
    lines.append("")
    forensic_p = OUT / "hhll_forensic_audit_full.parquet"
    if forensic_p.exists():
        forensic = pd.read_parquet(forensic_p)
        worst5 = forensic.nlargest(
            5, "slip_a_vs_c_realistic_ticks")
        lines.append("Note: positive slip = A FAVORABLE vs first-"
                      "cross. So top-5 'worst' here is actually "
                      "FAVORABLE to A. Adverse-tail (large negative "
                      "slip) is what would hurt A.")
        lines.append("")
        lines.append("Top-5 most FAVORABLE slips for A:")
        for _, r in worst5.iterrows():
            lines.append(
                f"- {r['cross_ct_time']} CT, "
                f"slip {r['slip_a_vs_c_realistic_ticks']:+.0f} "
                f"ticks ({fmt_d(r['slip_a_vs_c_realistic_dollars'])}), "
                f"min→RTH-close {int(r['min_to_rth_close'])}")
        adverse5 = forensic.nsmallest(
            5, "slip_a_vs_c_realistic_ticks")
        lines.append("")
        lines.append("Top-5 most ADVERSE slips for A:")
        for _, r in adverse5.iterrows():
            lines.append(
                f"- {r['cross_ct_time']} CT, "
                f"slip {r['slip_a_vs_c_realistic_ticks']:+.0f} "
                f"ticks ({fmt_d(r['slip_a_vs_c_realistic_dollars'])}), "
                f"min→RTH-close {int(r['min_to_rth_close'])}")
        lines.append("")
        lines.append(f"- Total top-5 favorable: "
                      f"{fmt_d(worst5['slip_a_vs_c_realistic_dollars'].sum())}")
        lines.append(f"- Total top-5 adverse: "
                      f"{fmt_d(adverse5['slip_a_vs_c_realistic_dollars'].sum())}")
    lines.append("")

    out_p = OUT / "HHLL_GUARDED_COMPARE.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
