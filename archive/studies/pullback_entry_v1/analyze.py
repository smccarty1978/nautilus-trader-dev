"""Pullback Entry Study v1 — analyzer / report builder."""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/pullback_entry_v1/results")
NQ_MULT = 20.0

BRACKETS = [(1.00, 1.00), (1.25, 1.00), (1.50, 1.00), (2.00, 1.00),
             (1.00, 0.75), (1.50, 0.75)]
THRESHOLDS = [0.25, 0.50, 0.75, 1.00]


def stats(df: pd.DataFrame, pnl_col: str, outcome_col: str = None) -> dict:
    if len(df) == 0:
        return {"n": 0}
    s = df[pnl_col].dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    out = {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
    }
    if outcome_col and outcome_col in df.columns:
        oc = df[outcome_col]
        out["pt_pct"] = float((oc == "pt").mean())
        out["sl_pct"] = float((oc == "sl").mean())
        out["regime_pct"] = float((oc == "regime").mean())
        out["timeout_pct"] = float((oc == "timeout").mean())
    return out


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    pb = pd.read_parquet(OUT / "pullback_candidates_2025.parquet")
    bl = pd.read_parquet(OUT / "matched_baseline_2025.parquet")
    print(f"Pullback candidates: {len(pb):,}")
    print(f"Matched baseline:     {len(bl):,}")

    lines = []
    lines.append("# Confirmed Regime Pullback Entry Study v1")
    lines.append("")
    lines.append("**Population**: 2025 RTH HH/LL-confirmed 1m regime "
                 "flips (n=5,595 regimes; 5,301 produced ≥1 pullback "
                 "candidate after intact-regime filter).")
    lines.append("")
    lines.append("**Setup**: signal_time = bar+1 close. Walk 1s bars "
                 "from signal_time to next opposing 1m flip (or 30-min "
                 "cap). On first crossing of pullback_depth_atr "
                 "thresholds [0.25, 0.50, 0.75, 1.00], snap decision "
                 "to next 30s checkpoint anchored at signal_time. "
                 "Fill at decision + 30s. Filter rows where regime "
                 "ended before decision OR before fill.")
    lines.append("")
    lines.append("**Cost model**: $5 commission + 1-tick adverse "
                 "entry. PT/regime/timeout exits: 1-tick adverse "
                 "exit; SL: additional 1-tick adverse exit.")
    lines.append("")
    lines.append("**Critical caveat**: matched-baseline rows use the "
                 "SAME regime IDs that survived to produce each "
                 "pullback. Comparing pullback vs matched baseline "
                 "removes the survivorship inflation that comes from "
                 "filtering to long-lived regimes. Pullback vs "
                 "*unfiltered* baseline is misleading.")
    lines.append("")

    # ============================================================
    # 1. Baseline confirmed-entry economics
    # ============================================================
    lines.append("## 1. Baseline confirmed-entry economics")
    lines.append("")
    lines.append("Reference numbers showing the survivorship effect.")
    lines.append("")

    rec = pd.read_parquet(
        "studies/hmm_5s_v1/results/rawflip_state_outcomes_2025.parquet")
    conf = rec[rec["hhll_confirmed"]]
    raw_n = len(conf)
    raw_pnl = conf["pnl_dollars"]
    lines.append("| Variant | n | Mean $ | Median $ | PT% | PF |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    raw_wins = raw_pnl[raw_pnl > 0].sum()
    raw_losses = abs(raw_pnl[raw_pnl < 0].sum())
    raw_pf = raw_wins / raw_losses if raw_losses else float("inf")
    lines.append(
        f"| Unfiltered (all confirmed RTH flips) | "
        f"{raw_n:,} | {fmt_d(raw_pnl.mean())} | "
        f"{fmt_d(raw_pnl.median())} | "
        f"{fmt_p((conf['outcome']=='pt').mean())} | {raw_pf:.2f} |")
    for thr in THRESHOLDS:
        sub = bl[bl["matched_threshold_atr"] == thr]
        m = stats(sub, "bracket_100_100_pnl",
                    "bracket_100_100_outcome")
        lines.append(
            f"| Matched (regime survived to {thr:.2f} ATR pullback) | "
            f"{m['n']:,} | {fmt_d(m['mean'])} | "
            f"{fmt_d(m['median'])} | "
            f"{fmt_p(m.get('pt_pct'))} | {m['pf']:.2f} |")
    lines.append("")
    lines.append("Survivorship lift = ~$60/trade. Filtering to "
                 "regimes that survive long enough to retrace inside "
                 "themselves selects the long-lived (profitable) tail "
                 "of the population.")
    lines.append("")

    # ============================================================
    # 2. Pullback economics by threshold
    # ============================================================
    lines.append("## 2. Pullback economics by threshold (1.0/1.0 bracket)")
    lines.append("")
    lines.append("| Threshold | n | PT% | SL% | Reg% | Mean $ | "
                 "Median $ | PF | Total $ |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for thr in THRESHOLDS:
        sub = pb[pb["pullback_threshold_atr"] == thr]
        m = stats(sub, "bracket_100_100_pnl",
                    "bracket_100_100_outcome")
        lines.append(
            f"| {thr:.2f} | {m['n']:,} | "
            f"{fmt_p(m.get('pt_pct'))} | "
            f"{fmt_p(m.get('sl_pct'))} | "
            f"{fmt_p(m.get('regime_pct'))} | "
            f"{fmt_d(m['mean'])} | {fmt_d(m['median'])} | "
            f"{m['pf']:.2f} | {fmt_d(m['sum'])} |")
    lines.append("")

    # ============================================================
    # 3. Matched-baseline comparison by threshold
    # ============================================================
    lines.append("## 3. Matched-baseline comparison (1.0/1.0 bracket)")
    lines.append("")
    lines.append("This is the headline test. Same regime IDs, "
                 "different entry timing.")
    lines.append("")
    lines.append("| Threshold | n | Pullback $ | Baseline $ | "
                 "Δ Mean $ | Pullback PT% | Baseline PT% | Δ PT% |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|")
    for thr in THRESHOLDS:
        pb_sub = pb[pb["pullback_threshold_atr"] == thr]
        bl_sub = bl[bl["matched_threshold_atr"] == thr]
        pb_m = stats(pb_sub, "bracket_100_100_pnl",
                       "bracket_100_100_outcome")
        bl_m = stats(bl_sub, "bracket_100_100_pnl",
                       "bracket_100_100_outcome")
        delta_pnl = pb_m["mean"] - bl_m["mean"]
        delta_pt = pb_m.get("pt_pct", 0) - bl_m.get("pt_pct", 0)
        lines.append(
            f"| {thr:.2f} | {pb_m['n']:,} | "
            f"{fmt_d(pb_m['mean'])} | {fmt_d(bl_m['mean'])} | "
            f"**{fmt_d(delta_pnl)}** | "
            f"{fmt_p(pb_m.get('pt_pct'))} | "
            f"{fmt_p(bl_m.get('pt_pct'))} | "
            f"**{100*delta_pt:+.1f}pp** |")
    lines.append("")

    # ============================================================
    # 4. Bracket grid by threshold (6 brackets × 4 thresholds)
    # ============================================================
    lines.append("## 4. Bracket grid by threshold (pullback entries)")
    lines.append("")
    for pt_R, sl_R in BRACKETS:
        tag = f"{int(pt_R*100)}_{int(sl_R*100)}"
        pnl_col = f"bracket_{tag}_pnl"
        oc_col = f"bracket_{tag}_outcome"
        lines.append(f"### Bracket PT={pt_R} / SL={sl_R}")
        lines.append("")
        lines.append("| Threshold | n | PT% | SL% | Reg% | Mean $ | "
                     "Median $ | PF | Total $ |")
        lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for thr in THRESHOLDS:
            sub = pb[pb["pullback_threshold_atr"] == thr]
            m = stats(sub, pnl_col, oc_col)
            lines.append(
                f"| {thr:.2f} | {m['n']:,} | "
                f"{fmt_p(m.get('pt_pct'))} | "
                f"{fmt_p(m.get('sl_pct'))} | "
                f"{fmt_p(m.get('regime_pct'))} | "
                f"{fmt_d(m['mean'])} | {fmt_d(m['median'])} | "
                f"{m['pf']:.2f} | {fmt_d(m['sum'])} |")
        lines.append("")

    # ============================================================
    # 5. Regime-exit PnL by threshold
    # ============================================================
    lines.append("## 5. Regime-exit-only PnL by threshold")
    lines.append("")
    lines.append("Hold every pullback entry to the next 1m opposing "
                 "flip (or 30-min cap). No PT/SL.")
    lines.append("")
    lines.append("| Threshold | n | Mean ATR | Med ATR | "
                 "Mean $ | Med $ | % >0 | % < -0.5 ATR | "
                 "% < -1.0 ATR | Mean MFE | Mean MAE |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for thr in THRESHOLDS:
        sub = pb[pb["pullback_threshold_atr"] == thr]
        atr_pnl = sub["regime_exit_atr"].dropna()
        dol_pnl = sub["regime_exit_pnl"].dropna()
        mfe = sub["mfe_to_regime_exit_atr"].dropna()
        mae = sub["mae_to_regime_exit_atr"].dropna()
        lines.append(
            f"| {thr:.2f} | {len(sub):,} | "
            f"{atr_pnl.mean():.3f} | {atr_pnl.median():.3f} | "
            f"{fmt_d(dol_pnl.mean())} | {fmt_d(dol_pnl.median())} | "
            f"{fmt_p((dol_pnl > 0).mean())} | "
            f"{fmt_p((atr_pnl < -0.5).mean())} | "
            f"{fmt_p((atr_pnl < -1.0).mean())} | "
            f"{mfe.mean():.3f} | {mae.mean():.3f} |")
    lines.append("")

    # ============================================================
    # 6. Timing diagnostics by threshold (1.0/1.0)
    # ============================================================
    lines.append("## 6. Timing diagnostics (1.0/1.0 bracket)")
    lines.append("")
    lines.append("| Threshold | Med PT t | Mean PT t | Med SL t | "
                 "Mean SL t | Med Res t | <60s | <120s | <180s | <300s |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for thr in THRESHOLDS:
        sub = pb[pb["pullback_threshold_atr"] == thr]
        pt_t = sub["bracket_100_100_pt_t"].dropna()
        sl_t = sub["bracket_100_100_sl_t"].dropna()
        res = sub["bracket_100_100_resolution_s"].dropna()
        lines.append(
            f"| {thr:.2f} | "
            f"{pt_t.median():.0f}s | {pt_t.mean():.0f}s | "
            f"{sl_t.median():.0f}s | {sl_t.mean():.0f}s | "
            f"{res.median():.0f}s | "
            f"{fmt_p((res<=60).mean())} | "
            f"{fmt_p((res<=120).mean())} | "
            f"{fmt_p((res<=180).mean())} | "
            f"{fmt_p((res<=300).mean())} |")
    lines.append("")

    # Path-quality flag rates
    lines.append("Path-quality flag rates by threshold:")
    lines.append("")
    lines.append("| Threshold | n | clean_path_300s | fast_fail_60s | "
                 "stall_then_reverse_180s |")
    lines.append("|--:|--:|--:|--:|--:|")
    for thr in THRESHOLDS:
        sub = pb[pb["pullback_threshold_atr"] == thr]
        lines.append(
            f"| {thr:.2f} | {len(sub):,} | "
            f"{fmt_p(sub['clean_path_300s'].mean())} | "
            f"{fmt_p(sub['fast_fail_60s'].mean())} | "
            f"{fmt_p(sub['stall_then_reverse_180s'].mean())} |")
    lines.append("")

    # ============================================================
    # 7. Pullback-quality buckets
    # ============================================================
    lines.append("## 7. Pullback-quality buckets (1.0/1.0 bracket, "
                 "all thresholds combined)")
    lines.append("")
    lines.append("Buckets defined by:")
    lines.append("- depth: shallow = ≤median pullback_depth_atr, "
                 "deep = >median")
    lines.append("- speed: slow = ≤median pullback_speed_atr_per_min, "
                 "fast = >median")
    lines.append("")
    median_depth = pb["pullback_depth_atr"].median()
    median_speed = pb["pullback_speed_atr_per_min"].median()
    print(f"  Median depth: {median_depth:.3f} ATR")
    print(f"  Median speed: {median_speed:.3f} ATR/min")
    lines.append(f"Median pullback_depth_atr: {median_depth:.3f}")
    lines.append(f"Median pullback_speed_atr_per_min: "
                 f"{median_speed:.3f}")
    lines.append("")
    pb["depth_bucket"] = np.where(
        pb["pullback_depth_atr"] <= median_depth, "shallow", "deep")
    pb["speed_bucket"] = np.where(
        pb["pullback_speed_atr_per_min"] <= median_speed,
        "slow", "fast")
    pb["quality_bucket"] = (pb["depth_bucket"] + "/"
                              + pb["speed_bucket"])
    # Violent reversal: very fast AND deep
    p90_speed = pb["pullback_speed_atr_per_min"].quantile(0.90)
    p75_depth = pb["pullback_depth_atr"].quantile(0.75)
    pb.loc[
        (pb["pullback_speed_atr_per_min"] >= p90_speed)
        & (pb["pullback_depth_atr"] >= p75_depth),
        "quality_bucket"] = "violent_reversal"

    lines.append("| Bucket | n | PT% | Mean $ | Median $ | PF |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for bucket in ["shallow/slow", "shallow/fast", "deep/slow",
                    "deep/fast", "violent_reversal"]:
        sub = pb[pb["quality_bucket"] == bucket]
        m = stats(sub, "bracket_100_100_pnl",
                    "bracket_100_100_outcome")
        if m["n"] == 0:
            continue
        lines.append(
            f"| {bucket} | {m['n']:,} | "
            f"{fmt_p(m.get('pt_pct'))} | "
            f"{fmt_d(m['mean'])} | {fmt_d(m['median'])} | "
            f"{m['pf']:.2f} |")
    lines.append("")

    # ============================================================
    # 8. HMM stratification
    # ============================================================
    lines.append("## 8. HMM stratification (secondary)")
    lines.append("")
    lines.append("### 8a. Pullback economics by threshold × HMM "
                 "state at pullback decision")
    lines.append("")
    lines.append("| Threshold | State 0 | State 1 | State 2 | "
                 "State 3 | Total |")
    lines.append("|--:|---|---|---|---|---|")
    for thr in THRESHOLDS:
        sub = pb[pb["pullback_threshold_atr"] == thr]
        cells = [f"| {thr:.2f}"]
        for st in [0, 1, 2, 3]:
            ss = sub[sub["state_at_decision"] == st]
            if len(ss):
                m = stats(ss, "bracket_100_100_pnl")
                cells.append(f"n={m['n']} {fmt_d(m['mean'])}")
            else:
                cells.append("—")
        m_all = stats(sub, "bracket_100_100_pnl")
        cells.append(f"n={m_all['n']} {fmt_d(m_all['mean'])}")
        lines.append(" | ".join(cells) + " |")
    lines.append("")

    lines.append("### 8b. Pullback economics by threshold × HMM "
                 "state at raw flip")
    lines.append("")
    lines.append("| Threshold | State 0 | State 1 | State 2 | "
                 "State 3 | Total |")
    lines.append("|--:|---|---|---|---|---|")
    for thr in THRESHOLDS:
        sub = pb[pb["pullback_threshold_atr"] == thr]
        cells = [f"| {thr:.2f}"]
        for st in [0, 1, 2, 3]:
            ss = sub[sub["state_at_raw_flip"] == st]
            if len(ss):
                m = stats(ss, "bracket_100_100_pnl")
                cells.append(f"n={m['n']} {fmt_d(m['mean'])}")
            else:
                cells.append("—")
        m_all = stats(sub, "bracket_100_100_pnl")
        cells.append(f"n={m_all['n']} {fmt_d(m_all['mean'])}")
        lines.append(" | ".join(cells) + " |")
    lines.append("")

    lines.append("### 8c. HMM state changed vs unchanged "
                 "(signal -> decision)")
    lines.append("")
    lines.append("| Group | n | PT% | Mean $ | Median $ | PF |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for label, mask in [
        ("State unchanged", ~pb["hmm_state_changed_since_signal"]),
        ("State changed", pb["hmm_state_changed_since_signal"]),
    ]:
        sub = pb[mask]
        m = stats(sub, "bracket_100_100_pnl",
                    "bracket_100_100_outcome")
        lines.append(
            f"| {label} | {m['n']:,} | "
            f"{fmt_p(m.get('pt_pct'))} | "
            f"{fmt_d(m['mean'])} | {fmt_d(m['median'])} | "
            f"{m['pf']:.2f} |")
    lines.append("")

    lines.append("### 8d. State 3 flag at pullback (vol-burst flag)")
    lines.append("")
    lines.append("| Group | n | PT% | Mean $ | Median $ | PF |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for label, mask in [
        ("Not state 3", ~pb["hmm_state_3_flag_at_pullback"]),
        ("State 3", pb["hmm_state_3_flag_at_pullback"]),
    ]:
        sub = pb[mask]
        m = stats(sub, "bracket_100_100_pnl",
                    "bracket_100_100_outcome")
        lines.append(
            f"| {label} | {m['n']:,} | "
            f"{fmt_p(m.get('pt_pct'))} | "
            f"{fmt_d(m['mean'])} | {fmt_d(m['median'])} | "
            f"{m['pf']:.2f} |")
    lines.append("")

    # ============================================================
    # Verdict
    # ============================================================
    # Compute the headline delta
    deltas = []
    for thr in THRESHOLDS:
        pb_m = pb[pb["pullback_threshold_atr"] == thr][
            "bracket_100_100_pnl"].mean()
        bl_m = bl[bl["matched_threshold_atr"] == thr][
            "bracket_100_100_pnl"].mean()
        deltas.append((thr, pb_m - bl_m))
    best_thr, best_delta = max(deltas, key=lambda x: x[1])

    lines.append("## Verdict")
    lines.append("")
    lines.append(
        f"**Pullback entry adds at most {fmt_d(best_delta)} per "
        f"trade** vs same-regime signal-time baseline (best at "
        f"{best_thr:.2f} ATR threshold).")
    lines.append("")
    lines.append(
        "The headline +$50-65/trade is almost entirely survivorship "
        "(filtering to regimes long enough to produce a pullback). "
        "When matched against signal-time entry on the same regimes, "
        f"the pullback edge is ${deltas[0][1]:.2f} to "
        f"${deltas[-1][1]:.2f} per trade across thresholds.")
    lines.append("")
    lines.append(
        "PT rate **drops** with deeper pullbacks (from ~58% baseline "
        "to ~51% pullback at 1.0 ATR), suggesting that deeper "
        "pullbacks signal weaker continuation. The economic edge "
        "comes from a slightly better fill price, not from improved "
        "trade quality.")
    lines.append("")
    lines.append(
        "**The matched-baseline correction is the key methodological "
        "result.** Without it, this study would have looked like a "
        "huge win.")

    out_path = OUT / "PULLBACK_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()
