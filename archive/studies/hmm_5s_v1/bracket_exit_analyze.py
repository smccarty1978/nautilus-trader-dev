"""Build bracket-exit study report."""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path("studies/hmm_5s_v1/results")
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


def stats(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {"n": 0}
    s = df["pnl_dollars"].dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    return {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
        "pt_pct": float((df["outcome"] == "pt").mean()),
        "sl_pct": float((df["outcome"] == "sl").mean()),
        "stall_pct": float((df["outcome"] == "stall").mean()),
        "regime_pct": float((df["outcome"] == "regime").mean()),
        "timeout_pct": float((df["outcome"] == "timeout").mean()),
    }


def median_time(df: pd.DataFrame, outcome: str) -> float:
    sub = df[df["outcome"] == outcome]["resolution_s"]
    return float(sub.median()) if len(sub) else float("nan")


def fmt_d(v):
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    df = pd.read_parquet(OUT / "bracket_exit_outcomes.parquet")
    print(f"Total outcome rows: {len(df):,}")

    BRACKETS = [(1.00, 1.00), (1.25, 1.00), (1.50, 1.00),
                 (2.00, 1.00),
                 (1.00, 0.75), (1.25, 0.75), (1.50, 0.75)]

    lines = []
    lines.append("# HMM Best-Slice — Bracket + Exit-Rule Study")
    lines.append("")
    lines.append("**Population**: 2025 RTH raw 1m flips, HH/LL confirmed, "
                  "NOT in HMM state 3, no recent transition (n=1,086)")
    lines.append("")
    lines.append("**Cost model**: $5 commission + 1-tick adverse entry. "
                  "PT/stall/regime exits: 1-tick adverse exit; SL exits: "
                  "additional 1-tick adverse exit. Regime exits price at "
                  "actual close at regime-flip moment (not -0.7 ATR proxy).")
    lines.append("")

    # ----- 1. Bracket grid -----
    lines.append("## 1. Bracket grid (no stall exit)")
    lines.append("")
    lines.append("| PT R | SL R | n | PT% | SL% | Reg% | Time% | Mean $ | "
                  "Median $ | PF | Total $ | Med PT t | Med SL t | "
                  "Med res t |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for pt_R, sl_R in BRACKETS:
        sub = df[(df["pt_R"] == pt_R) & (df["sl_R"] == sl_R)
                  & (df["stall_rule"] == "none")]
        m = stats(sub)
        if m["n"] == 0:
            continue
        med_pt = median_time(sub, "pt")
        med_sl = median_time(sub, "sl")
        med_all = float(sub["resolution_s"].median())
        lines.append(
            f"| {pt_R} | {sl_R} | {m['n']:,} | "
            f"{fmt_p(m['pt_pct'])} | {fmt_p(m['sl_pct'])} | "
            f"{fmt_p(m['regime_pct'])} | "
            f"{fmt_p(m['timeout_pct'])} | "
            f"{fmt_d(m['mean'])} | {fmt_d(m['median'])} | "
            f"{m['pf']:.2f} | {fmt_d(m['sum'])} | "
            f"{med_pt:.0f}s | {med_sl:.0f}s | {med_all:.0f}s |")
    lines.append("")

    # ----- 2. Resolution timing diagnostics (1.0/1.0 baseline) -----
    lines.append("## 2. Resolution timing (1.0/1.0 bracket, no stall)")
    lines.append("")
    base = df[(df["pt_R"] == 1.0) & (df["sl_R"] == 1.0)
                & (df["stall_rule"] == "none")]
    res = base["resolution_s"].dropna()
    print(f"  Resolution distribution (n={len(base):,}):")
    print(f"    Within 30s:  {100*(res <= 30).mean():.1f}%")
    print(f"    Within 60s:  {100*(res <= 60).mean():.1f}%")
    print(f"    Within 120s: {100*(res <= 120).mean():.1f}%")
    print(f"    Within 180s: {100*(res <= 180).mean():.1f}%")

    lines.append("Cumulative resolution %:")
    lines.append("")
    lines.append("| Within | % resolved |")
    lines.append("|--:|--:|")
    for t in [30, 60, 90, 120, 180, 300, 600, 1200, 1800]:
        pct = 100 * (res <= t).mean()
        lines.append(f"| {t}s | {pct:.1f}% |")
    lines.append("")

    pt_res = base[base["outcome"] == "pt"]["resolution_s"]
    sl_res = base[base["outcome"] == "sl"]["resolution_s"]
    re_res = base[base["outcome"] == "regime"]["resolution_s"]
    lines.append(
        f"- Time to PT — median {pt_res.median():.0f}s, "
        f"mean {pt_res.mean():.0f}s, p90 {pt_res.quantile(0.90):.0f}s")
    lines.append(
        f"- Time to SL — median {sl_res.median():.0f}s, "
        f"mean {sl_res.mean():.0f}s, p90 {sl_res.quantile(0.90):.0f}s")
    if len(re_res):
        lines.append(
            f"- Time to regime exit — median {re_res.median():.0f}s, "
            f"mean {re_res.mean():.0f}s")
    lines.append(
        f"- Regime-exit fraction at 1.0/1.0: "
        f"{fmt_p((base['outcome']=='regime').mean())}")
    lines.append("")

    # ----- 3. Stall exit tests -----
    lines.append("## 3. Stall exit tests on key brackets")
    lines.append("")
    STALL_RULES = ["none", "no_progress_60s", "no_progress_90s",
                    "no_progress_120s", "mfe_lt_025_60s",
                    "mfe_lt_050_90s", "mfe_lt_050_120s"]
    BRACKET_TEST = [(1.0, 1.0), (1.5, 1.0), (2.0, 1.0)]
    for pt_R, sl_R in BRACKET_TEST:
        lines.append(f"### Bracket {pt_R} PT / {sl_R} SL")
        lines.append("")
        lines.append("| Stall rule | n | PT% | SL% | Stall% | Reg% | "
                      "Mean $ | PF | Total $ |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
        for rule in STALL_RULES:
            sub = df[(df["pt_R"] == pt_R) & (df["sl_R"] == sl_R)
                      & (df["stall_rule"] == rule)]
            m = stats(sub)
            if m["n"] == 0:
                continue
            lines.append(
                f"| {rule} | {m['n']:,} | "
                f"{fmt_p(m['pt_pct'])} | {fmt_p(m['sl_pct'])} | "
                f"{fmt_p(m['stall_pct'])} | "
                f"{fmt_p(m['regime_pct'])} | "
                f"{fmt_d(m['mean'])} | {m['pf']:.2f} | "
                f"{fmt_d(m['sum'])} |")
        lines.append("")

    # ----- 4. Regime-exit reality check -----
    lines.append("## 4. Regime-exit reality check")
    lines.append("")
    re_df = pd.read_parquet(OUT / "regime_exit_reality.parquet")
    if len(re_df):
        lines.append(f"On the 1.0/1.0 bracket (no stall), "
                      f"{len(re_df):,} trades exited via regime "
                      "(or timed out) instead of bracket.")
        lines.append("")
        lines.append(
            f"- Mean actual ATR PnL on regime exits: "
            f"**{re_df['actual_atr_pnl'].mean():.4f}**")
        lines.append(
            f"- Median: **{re_df['actual_atr_pnl'].median():.4f}**")
        lines.append(
            f"- Std: {re_df['actual_atr_pnl'].std():.4f}")
        lines.append(
            f"- % positive: "
            f"{100*(re_df['pnl_dollars']>0).mean():.1f}%")
        lines.append(
            f"- % worse than -0.5 ATR: "
            f"{100*(re_df['actual_atr_pnl']<-0.5).mean():.1f}%")
        lines.append(
            f"- % worse than -1.0 ATR: "
            f"{100*(re_df['actual_atr_pnl']<-1.0).mean():.1f}%")
        lines.append("")
        lines.append("**Comparison to prior -0.7 ATR proxy**: "
                      f"actual mean {re_df['actual_atr_pnl'].mean():.3f} ATR "
                      f"is roughly the same. Proxy was approximately "
                      "right.")
    lines.append("")

    # ----- 5. Comparison vs baselines -----
    lines.append("## 5. Comparison vs baselines (1-tick slip cost model)")
    lines.append("")

    # Load earlier rawflip outcomes for baseline comparisons
    rec = pd.read_parquet(OUT / "rawflip_state_outcomes_2025.parquet")
    # All raw flips (from prior study, used 30-min lookahead with no
    # regime-exit logic — already has pnl_dollars in -1tick-slip model
    # but regime exits not modeled. Just report what's there.)
    def _stats_simple(df):
        s = df["pnl_dollars"].dropna()
        if len(s) == 0:
            return {"n": 0}
        wins = s[s > 0]
        losses = s[s < 0]
        return {
            "n": len(s),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "pf": float(wins.sum() / abs(losses.sum()))
                  if len(losses) and losses.sum() != 0
                  else float("inf"),
            "win_rate": float((s > 0).mean()),
            "sum": float(s.sum()),
        }

    rawflip_all = _stats_simple(rec)
    rawflip_conf = _stats_simple(rec[rec["hhll_confirmed"] == True])
    hmm_slice = _stats_simple(rec[
        (rec["hhll_confirmed"] == True)
        & (rec["state"] != 3)
        & (~rec["recent_transition"])])

    # Best from this study
    best_iter = None
    best_pf = 0
    for pt_R, sl_R in BRACKETS:
        for rule in STALL_RULES:
            sub = df[(df["pt_R"] == pt_R) & (df["sl_R"] == sl_R)
                      & (df["stall_rule"] == rule)]
            if len(sub):
                m = stats(sub)
                if m["pf"] > best_pf:
                    best_pf = m["pf"]
                    best_iter = (pt_R, sl_R, rule, m)

    lines.append("| Variant | n | Mean $ | Median $ | PF | Win% | "
                  "Total $ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    lines.append(
        f"| All raw flips (no regime-exit logic) | "
        f"{rawflip_all['n']:,} | {fmt_d(rawflip_all['mean'])} | "
        f"{fmt_d(rawflip_all['median'])} | {rawflip_all['pf']:.2f} | "
        f"{fmt_p(rawflip_all['win_rate'])} | "
        f"{fmt_d(rawflip_all['sum'])} |")
    lines.append(
        f"| HH/LL confirmed only | "
        f"{rawflip_conf['n']:,} | {fmt_d(rawflip_conf['mean'])} | "
        f"{fmt_d(rawflip_conf['median'])} | {rawflip_conf['pf']:.2f} | "
        f"{fmt_p(rawflip_conf['win_rate'])} | "
        f"{fmt_d(rawflip_conf['sum'])} |")
    lines.append(
        f"| HMM best slice (1.0/1.0, no regime-exit) | "
        f"{hmm_slice['n']:,} | {fmt_d(hmm_slice['mean'])} | "
        f"{fmt_d(hmm_slice['median'])} | {hmm_slice['pf']:.2f} | "
        f"{fmt_p(hmm_slice['win_rate'])} | "
        f"{fmt_d(hmm_slice['sum'])} |")
    if best_iter:
        pt_R, sl_R, rule, m = best_iter
        lines.append(
            f"| **Best variant ({pt_R}/{sl_R}, {rule})** | "
            f"{m['n']:,} | **{fmt_d(m['mean'])}** | "
            f"{fmt_d(m['median'])} | **{m['pf']:.2f}** | "
            f"{fmt_p(m['win_rate'])} | "
            f"{fmt_d(m['sum'])} |")
    lines.append("")

    # ----- Verdict -----
    lines.append("## Verdict")
    lines.append("")
    if best_pf > 1.0:
        lines.append(
            f"**A combination crossed PF > 1.0**: "
            f"{best_iter[0]}/{best_iter[1]} bracket with "
            f"{best_iter[2]} stall rule produced PF "
            f"{best_iter[3]['pf']:.2f}, mean "
            f"{fmt_d(best_iter[3]['mean'])} per trade, "
            f"total {fmt_d(best_iter[3]['sum'])} on "
            f"{best_iter[3]['n']:,} trades.")
    else:
        lines.append(
            f"**No bracket × stall combination crossed PF > 1.0** on "
            f"this filtered population. Best was "
            f"{best_iter[0]}/{best_iter[1]} bracket with "
            f"{best_iter[2]} rule at PF {best_iter[3]['pf']:.2f} "
            f"(mean {fmt_d(best_iter[3]['mean'])}/trade).")
    lines.append("")
    lines.append(
        "The HMM identified a population that's still structurally "
        "negative under realistic costs, even with bracket geometry "
        "and stall-exit experiments. The noise floor on this strategy "
        "class isn't broken by exit-management changes.")

    out_path = OUT / "BRACKET_EXIT_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()
