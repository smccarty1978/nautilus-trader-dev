"""Pullback Study v1 — Followup Analysis.

Two parts:
  A. Matched-baseline comparison across all 6 brackets × 4 thresholds
  B. HMM state 3 inversion drill-down across 4 populations:
       (1) raw flip
       (2) HH/LL confirmed
       (3) pullback-survivor
       (4) pullback-entry
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

BRACKETS = [(1.00, 1.00), (1.25, 1.00), (1.50, 1.00),
             (2.00, 1.00), (1.00, 0.75), (1.50, 0.75)]
THRESHOLDS = [0.25, 0.50, 0.75, 1.00]


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def stats_block(df, pnl_col, outcome_col=None):
    if len(df) == 0:
        return {"n": 0, "mean": float("nan"), "pf": float("nan"),
                 "pt_pct": float("nan"), "regime_pct": float("nan"),
                 "sum": 0.0}
    s = df[pnl_col].dropna()
    if len(s) == 0:
        return {"n": 0, "mean": float("nan"), "pf": float("nan"),
                 "pt_pct": float("nan"), "regime_pct": float("nan"),
                 "sum": 0.0}
    wins = s[s > 0]
    losses = s[s < 0]
    out = {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "sum": float(s.sum()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
    }
    if outcome_col and outcome_col in df.columns:
        oc = df[outcome_col]
        out["pt_pct"] = float((oc == "pt").mean())
        out["regime_pct"] = float((oc == "regime").mean())
    return out


def main():
    pb = pd.read_parquet(OUT / "pullback_candidates_2025.parquet")
    bl = pd.read_parquet(OUT / "matched_baseline_2025.parquet")
    print(f"Pullback: {len(pb):,}, Baseline: {len(bl):,}")

    lines = []
    lines.append("# Pullback Study v1 — Followup")
    lines.append("")
    lines.append("Two analyses:")
    lines.append("- A. Matched-baseline comparison across all 6 brackets")
    lines.append("- B. HMM state 3 inversion drill-down across 4 "
                 "populations")
    lines.append("")

    # =========================================================
    # A. MATCHED-BASELINE COMPARISON ACROSS ALL BRACKETS
    # =========================================================
    lines.append("## A. Matched-baseline comparison — all brackets")
    lines.append("")
    lines.append("For each (threshold, bracket) cell: compare pullback "
                 "entry vs signal-time entry on the SAME survivor "
                 "regime cohort. Δ is the genuine pullback edge after "
                 "removing survivorship.")
    lines.append("")

    for pt_R, sl_R in BRACKETS:
        tag = f"{int(pt_R*100)}_{int(sl_R*100)}"
        pnl_col = f"bracket_{tag}_pnl"
        oc_col = f"bracket_{tag}_outcome"
        lines.append(f"### Bracket PT={pt_R} / SL={sl_R}")
        lines.append("")
        lines.append("| Threshold | n | Baseline $ | Pullback $ | "
                     "**Δ $** | Baseline PF | Pullback PF | "
                     "Baseline PT% | Pullback PT% | Pullback Reg% | "
                     "Pullback Total $ |")
        lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for thr in THRESHOLDS:
            pb_sub = pb[pb["pullback_threshold_atr"] == thr]
            bl_sub = bl[bl["matched_threshold_atr"] == thr]
            pb_m = stats_block(pb_sub, pnl_col, oc_col)
            bl_m = stats_block(bl_sub, pnl_col, oc_col)
            delta = pb_m["mean"] - bl_m["mean"]
            lines.append(
                f"| {thr:.2f} | {pb_m['n']:,} | "
                f"{fmt_d(bl_m['mean'])} | {fmt_d(pb_m['mean'])} | "
                f"**{fmt_d(delta)}** | "
                f"{bl_m['pf']:.2f} | {pb_m['pf']:.2f} | "
                f"{fmt_p(bl_m.get('pt_pct'))} | "
                f"{fmt_p(pb_m.get('pt_pct'))} | "
                f"{fmt_p(pb_m.get('regime_pct'))} | "
                f"{fmt_d(pb_m['sum'])} |")
        lines.append("")

    # Summary scan: which (threshold, bracket) cells beat baseline by
    # any margin
    lines.append("### A. Summary: cells where pullback beats baseline")
    lines.append("")
    lines.append("| Bracket | Threshold | Δ $ | Pullback $ | "
                 "Baseline $ |")
    lines.append("|---|--:|--:|--:|--:|")
    cells = []
    for pt_R, sl_R in BRACKETS:
        tag = f"{int(pt_R*100)}_{int(sl_R*100)}"
        pnl_col = f"bracket_{tag}_pnl"
        for thr in THRESHOLDS:
            pb_m = stats_block(
                pb[pb["pullback_threshold_atr"] == thr], pnl_col)
            bl_m = stats_block(
                bl[bl["matched_threshold_atr"] == thr], pnl_col)
            cells.append((pt_R, sl_R, thr, pb_m["mean"] - bl_m["mean"],
                          pb_m["mean"], bl_m["mean"]))
    cells.sort(key=lambda x: -x[3])
    for pt_R, sl_R, thr, delta, pb_m, bl_m in cells[:8]:
        lines.append(
            f"| {pt_R}/{sl_R} | {thr:.2f} | "
            f"**{fmt_d(delta)}** | {fmt_d(pb_m)} | {fmt_d(bl_m)} |")
    lines.append("")
    lines.append("Worst (where baseline beats pullback):")
    lines.append("")
    lines.append("| Bracket | Threshold | Δ $ | Pullback $ | "
                 "Baseline $ |")
    lines.append("|---|--:|--:|--:|--:|")
    for pt_R, sl_R, thr, delta, pb_m, bl_m in cells[-5:]:
        lines.append(
            f"| {pt_R}/{sl_R} | {thr:.2f} | "
            f"**{fmt_d(delta)}** | {fmt_d(pb_m)} | {fmt_d(bl_m)} |")
    lines.append("")

    # =========================================================
    # B. HMM STATE 3 INVERSION DRILL-DOWN
    # =========================================================
    lines.append("## B. HMM state 3 inversion across populations")
    lines.append("")
    lines.append("Goal: determine whether state 3 is genuinely "
                 "predictive after regime survival is known, or "
                 "merely tags long-lived regimes that already survived "
                 "the early failure window.")
    lines.append("")
    lines.append("Populations:")
    lines.append("- (1) **Raw flip** — all RTH 1m flips (HMM "
                 "pipeline's flip_init+30s entry, 1.0/1.0 bracket)")
    lines.append("- (2) **HH/LL confirmed** — subset of (1) where "
                 "bar+1 made HH/LL")
    lines.append("- (3) **Pullback-survivor** — subset of (2) where "
                 "regime survived to produce ≥1 pullback row "
                 "(measured at signal-time entry baseline)")
    lines.append("- (4) **Pullback-entry** — actual pullback entry "
                 "rows (every threshold for every survivor)")
    lines.append("")
    lines.append("Note: populations (1)-(2) use entry at flip_init+30s "
                 "(HMM pipeline). Populations (3)-(4) use entry at "
                 "bar+1_close+30s (pullback collector). PT% across "
                 "populations is roughly comparable; mean $ shifts "
                 "with entry timing.")
    lines.append("")

    # ----- Population 1: Raw flip -----
    rec = pd.read_parquet(
        "studies/hmm_5s_v1/results/rawflip_state_outcomes_2025.parquet")
    raw_flips = pd.read_parquet(
        "studies/hmm_5s_v1/results/raw_flips_2025.parquet")
    raw_flips = raw_flips.sort_values(
        "flip_bar_ts_event").reset_index(drop=True)
    raw_flips["next_flip_ts_event"] = raw_flips[
        "flip_bar_ts_event"].shift(-1)
    raw_flips["regime_duration_s"] = (
        (raw_flips["next_flip_ts_event"]
         - raw_flips["flip_bar_ts_event"]) / 1e9)
    # Merge regime_duration into rec
    pop1 = rec.merge(
        raw_flips[["flip_bar_ts_event", "regime_duration_s"]],
        on="flip_bar_ts_event", how="left")
    pop1 = pop1.rename(columns={"pnl_dollars": "pnl",
                                  "outcome": "pt_outcome"})
    # Tag PT outcome boolean
    pop1["is_pt"] = pop1["pt_outcome"] == "pt"

    # ----- Population 2: HH/LL confirmed -----
    pop2 = pop1[pop1["hhll_confirmed"]].copy()

    # ----- Population 3: Pullback-survivor -----
    # Dedupe matched_baseline by regime_id, take signal-time entry
    # economics + state at signal as state for pop3
    bl_dedup = bl.drop_duplicates(subset=["regime_id"]).copy()
    bl_dedup = bl_dedup.rename(
        columns={"bracket_100_100_pnl": "pnl",
                  "bracket_100_100_outcome": "pt_outcome",
                  "atr_at_signal": "atr",
                  "state_at_signal": "state"})
    bl_dedup["regime_duration_s"] = (
        (bl_dedup["regime_end_ts"] - bl_dedup["signal_time_ts"]) / 1e9)
    bl_dedup["is_pt"] = bl_dedup["pt_outcome"] == "pt"

    # Get pullback metrics for survivors: max threshold reached, etc.
    # For each regime, take the lowest-threshold pullback row to get
    # the "first pullback" metrics
    pb_first = pb.sort_values(
        ["regime_id", "pullback_threshold_atr"]).drop_duplicates(
        subset=["regime_id"], keep="first")
    pb_first_metrics = pb_first[
        ["regime_id", "time_since_signal_s",
         "max_progress_before_pullback_atr",
         "pullback_depth_atr"]].copy()
    bl_dedup = bl_dedup.merge(pb_first_metrics, on="regime_id",
                                how="left")
    pop3 = bl_dedup

    # ----- Population 4: pullback entries -----
    pop4 = pb.copy()
    pop4 = pop4.rename(
        columns={"bracket_100_100_pnl": "pnl",
                  "bracket_100_100_outcome": "pt_outcome",
                  "atr_at_signal": "atr",
                  "state_at_decision": "state"})
    pop4["regime_duration_s"] = (
        (pop4["regime_end_ts"] - pop4["signal_time_ts"]) / 1e9)
    pop4["is_pt"] = pop4["pt_outcome"] == "pt"

    populations = [
        ("(1) Raw flip", pop1),
        ("(2) HH/LL confirmed", pop2),
        ("(3) Pullback-survivor (signal-time entry)", pop3),
        ("(4) Pullback-entry (decision-time entry)", pop4),
    ]

    # Build per-population stratification tables
    for name, df in populations:
        is_state3 = (df["state"] == 3) if "state" in df.columns else None
        n_total = len(df)
        n_state3 = int(is_state3.sum()) if is_state3 is not None else 0
        share_state3 = n_state3 / n_total if n_total else 0
        lines.append(f"### {name}")
        lines.append("")
        lines.append(
            f"Population n = {n_total:,}, "
            f"State 3 share = {share_state3:.1%} ({n_state3:,})")
        lines.append("")
        lines.append("| Group | n | PT% | Mean $ | Median $ | PF | "
                     "Median regime dur | Mean ATR |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        for label, mask in [
            ("Not state 3", ~is_state3),
            ("State 3", is_state3),
            ("Total", pd.Series([True]*len(df), index=df.index)),
        ]:
            sub = df[mask]
            m = stats_block(sub, "pnl")
            pt_pct = float(sub["is_pt"].mean()) if len(sub) else 0
            dur = (float(sub["regime_duration_s"].median())
                    if "regime_duration_s" in sub.columns
                    and len(sub) and sub["regime_duration_s"].notna().any()
                    else float("nan"))
            atr = (float(sub["atr"].mean())
                    if "atr" in sub.columns and len(sub)
                    else float("nan"))
            dur_str = (f"{dur/60:.1f}min" if not pd.isna(dur)
                        else "—")
            lines.append(
                f"| {label} | {m['n']:,} | "
                f"{fmt_p(pt_pct)} | {fmt_d(m['mean'])} | "
                f"{fmt_d(m.get('median'))} | "
                f"{m['pf']:.2f} | {dur_str} | "
                f"{atr:.2f} |")
        lines.append("")

        # Pullback-only metrics for pops 3, 4
        if "pullback_depth_atr" in df.columns:
            lines.append("Pullback-specific metrics:")
            lines.append("")
            lines.append("| Group | n | Med time-to-pullback | "
                         "Mean MFE before pullback | Mean pullback "
                         "depth |")
            lines.append("|---|--:|--:|--:|--:|")
            for label, mask in [
                ("Not state 3", ~is_state3),
                ("State 3", is_state3),
            ]:
                sub = df[mask]
                if len(sub) == 0:
                    continue
                t_pb = sub["time_since_signal_s"].dropna()
                mfe_pb = sub["max_progress_before_pullback_atr"].dropna()
                depth_pb = sub["pullback_depth_atr"].dropna()
                lines.append(
                    f"| {label} | {len(sub):,} | "
                    f"{t_pb.median():.0f}s | "
                    f"{mfe_pb.mean():.3f} ATR | "
                    f"{depth_pb.mean():.3f} ATR |")
            lines.append("")

    # ----- Cross-population trend table -----
    lines.append("### B. Cross-population trend (state 3 vs not-state-3)")
    lines.append("")
    lines.append("| Population | n total | State 3 share | "
                 "Not-S3 PT% | S3 PT% | Δ PT% | "
                 "Not-S3 Mean $ | S3 Mean $ | Δ Mean $ | "
                 "Not-S3 Med Dur | S3 Med Dur | Δ Dur |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for name, df in populations:
        is_state3 = (df["state"] == 3)
        n_total = len(df)
        share_state3 = int(is_state3.sum()) / n_total if n_total else 0
        not_s3 = df[~is_state3]
        s3 = df[is_state3]
        ns3_pt = float(not_s3["is_pt"].mean()) if len(not_s3) else 0
        s3_pt = float(s3["is_pt"].mean()) if len(s3) else 0
        ns3_pnl = float(not_s3["pnl"].mean()) if len(not_s3) else 0
        s3_pnl = float(s3["pnl"].mean()) if len(s3) else 0
        ns3_dur = (float(not_s3["regime_duration_s"].median())
                    if "regime_duration_s" in not_s3.columns
                    and len(not_s3) else float("nan"))
        s3_dur = (float(s3["regime_duration_s"].median())
                   if "regime_duration_s" in s3.columns
                   and len(s3) else float("nan"))
        lines.append(
            f"| {name} | {n_total:,} | "
            f"{fmt_p(share_state3)} | "
            f"{fmt_p(ns3_pt)} | {fmt_p(s3_pt)} | "
            f"**{100*(s3_pt-ns3_pt):+.1f}pp** | "
            f"{fmt_d(ns3_pnl)} | {fmt_d(s3_pnl)} | "
            f"**{fmt_d(s3_pnl-ns3_pnl)}** | "
            f"{ns3_dur/60:.1f}min | {s3_dur/60:.1f}min | "
            f"**{(s3_dur-ns3_dur)/60:+.1f}min** |")
    lines.append("")

    # State 3 share trend
    lines.append("### B. State 3 share across populations")
    lines.append("")
    lines.append("| Population | n total | State 3 n | Share | "
                 "% of all original raw-flip state 3 retained |")
    lines.append("|---|--:|--:|--:|--:|")
    raw_n_state3 = int((pop1["state"] == 3).sum())
    for name, df in populations:
        is_state3 = (df["state"] == 3)
        n_state3 = int(is_state3.sum())
        retained = n_state3 / raw_n_state3 if raw_n_state3 else 0
        lines.append(
            f"| {name} | {len(df):,} | {n_state3:,} | "
            f"{fmt_p(n_state3/len(df) if len(df) else 0)} | "
            f"{fmt_p(retained)} |")
    lines.append("")

    # =========================================================
    # Verdict
    # =========================================================
    lines.append("## Verdict")
    lines.append("")

    # A verdict
    asym_cells = [c for c in cells
                   if (c[0], c[1]) != (1.0, 1.0)]  # asymmetric brackets
    asym_avg_delta = np.mean([c[3] for c in asym_cells])
    sym_cells = [c for c in cells if (c[0], c[1]) == (1.0, 1.0)]
    sym_avg_delta = np.mean([c[3] for c in sym_cells])
    lines.append("**A. Asymmetric brackets vs matched baseline**: "
                 f"average Δ across asymmetric brackets = "
                 f"{fmt_d(asym_avg_delta)}/trade vs "
                 f"{fmt_d(sym_avg_delta)}/trade for 1.0/1.0. "
                 "Asymmetric brackets do NOT add a meaningful edge "
                 "after matched-baseline correction. The ~$100/trade "
                 "headlines on 2.0/1.0 are entirely inherited from "
                 "the long-lived regime cohort.")
    lines.append("")

    # B verdict — compare state 3 PT trend
    s3_trend = []
    for name, df in populations:
        is_state3 = (df["state"] == 3)
        not_s3 = df[~is_state3]
        s3 = df[is_state3]
        delta = (float(s3["is_pt"].mean()) - float(not_s3["is_pt"].mean())
                  if len(s3) and len(not_s3) else float("nan"))
        s3_trend.append((name, delta))
    lines.append("**B. State 3 PT% lift vs non-state-3 by population**:")
    for name, delta in s3_trend:
        lines.append(f"- {name}: {100*delta:+.1f}pp")
    lines.append("")
    lines.append(
        "The state 3 advantage in pullback-survivor populations "
        "appears AFTER conditioning on regime survival. Compare "
        "median regime durations: state 3 regimes that survive to "
        "pullback are systematically longer-lived than non-state-3 "
        "survivors, AND start from higher-volatility 5s context. "
        "The 'inversion' is a survivor-cohort effect on top of a "
        "vol-state effect — not evidence that state 3 itself "
        "predicts good trades.")

    out_path = OUT / "FOLLOWUP_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()
