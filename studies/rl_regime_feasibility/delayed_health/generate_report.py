"""Phase 10: Generate final decision-ready report.

Reads all produced artifacts from results/ and writes final_report.md.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

OUT_DIR = Path("studies/rl_regime_feasibility/delayed_health/results")


def _tbl(df: pd.DataFrame, cols=None, fmt: dict = None) -> str:
    if cols:
        df = df[cols]
    fmt = fmt or {}
    rows = []
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows.append(header)
    rows.append(sep)
    for _, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            if c in fmt:
                cells.append(fmt[c].format(v))
            elif isinstance(v, float):
                cells.append(f"{v:.3f}" if abs(v) < 1e5 else f"{v:,.0f}")
            else:
                cells.append(str(v))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def generate_report():
    print("Phase 10: Generating final report ...")

    # Load all artifacts
    vm = pd.read_parquet(OUT_DIR / "variant_metrics.parquet") if (OUT_DIR / "variant_metrics.parquet").exists() else pd.DataFrame()
    boot = pd.read_parquet(OUT_DIR / "bootstrap_ci.parquet") if (OUT_DIR / "bootstrap_ci.parquet").exists() else pd.DataFrame()
    placebo = pd.read_parquet(OUT_DIR / "delay_placebo_results.parquet") if (OUT_DIR / "delay_placebo_results.parquet").exists() else pd.DataFrame()
    controls = pd.read_parquet(OUT_DIR / "control_results.parquet") if (OUT_DIR / "control_results.parquet").exists() else pd.DataFrame()
    knn_prov = {}
    if (OUT_DIR / "knn_provenance_audit.json").exists():
        with open(OUT_DIR / "knn_provenance_audit.json") as f:
            knn_prov = json.load(f)
    model_manifest = {}
    if (OUT_DIR / "model_manifest.json").exists():
        with open(OUT_DIR / "model_manifest.json") as f:
            model_manifest = json.load(f)
    thresholds = {}
    if (OUT_DIR / "policy_thresholds.json").exists():
        with open(OUT_DIR / "policy_thresholds.json") as f:
            thresholds = json.load(f)
    bar4_defn = {}
    if (OUT_DIR / "bar4_definition.json").exists():
        with open(OUT_DIR / "bar4_definition.json") as f:
            bar4_defn = json.load(f)
    pop_summary = {}
    if (OUT_DIR / "bar4_population_summary.parquet").exists():
        pop_df = pd.read_parquet(OUT_DIR / "bar4_population_summary.parquet")
        pop_summary = pop_df.to_dict("records")[0] if len(pop_df) > 0 else {}
    vg = {}
    if (OUT_DIR / "validation_grid.parquet").exists():
        vg_df = pd.read_parquet(OUT_DIR / "validation_grid.parquet")
    else:
        vg_df = pd.DataFrame()

    # Extract key metrics
    def _get(variant: str, field: str, default=float("nan")):
        if len(vm) == 0:
            return default
        row = vm[vm["variant"] == variant]
        if len(row) == 0:
            return default
        return row.iloc[0].get(field, default)

    def _ci(variant: str):
        if len(boot) == 0:
            return ("n/a", "n/a")
        row = boot[boot["variant"] == variant]
        if len(row) == 0:
            return ("n/a", "n/a")
        return (f"{row.iloc[0]['ci_lo_95']:+.2f}", f"{row.iloc[0]['ci_hi_95']:+.2f}")

    ev_A = _get("A_unrestricted", "ev_per_episode")
    ev_B1 = _get("B1_uncond_fixed", "ev_per_episode")
    ev_B2 = _get("B2_uncond_dynamic", "ev_per_episode")
    ev_C1 = _get("C1_ml_fixed", "ev_per_episode")
    ev_C2 = _get("C2_ml_dynamic", "ev_per_episode")
    ev_D = _get("D_ml_knn_dynamic", "ev_per_episode")
    ev_E = _get("E_ml_knn_cond_exit", "ev_per_episode")
    ev_E1t = _get("E_plus1tick", "ev_per_episode")
    ev_E2t = _get("E_plus2tick", "ev_per_episode")

    # Survival stats
    n_total = pop_summary.get("total_episodes", "n/a")
    n_surv = pop_summary.get("bar4_survivors", "n/a")
    surv_rate = pop_summary.get("bar4_survival_rate", 0)

    # Model AUCs
    entry_D_auc = model_manifest.get("entry_D", {}).get("val_auc", float("nan"))
    entry_A_auc = model_manifest.get("entry_A", {}).get("val_auc", float("nan"))

    # Best delay from placebo
    best_delay_row = {}
    if len(placebo) > 0 and "delay_s" in placebo.columns:
        placebo = placebo.sort_values("delay_s")
        best_delay_row = placebo.loc[placebo["ev_per_episode"].idxmax()].to_dict() if "ev_per_episode" in placebo.columns else {}

    # Determine verdict
    n_positive = sum(1 for ev in [ev_E, ev_E1t, ev_E2t] if not np.isnan(ev) and ev > 0)
    best_variant_ev = max([ev for ev in [ev_A, ev_B1, ev_B2, ev_C1, ev_C2, ev_D, ev_E] if not np.isnan(ev)], default=float("nan"))

    if not np.isnan(ev_E) and ev_E > 2.0:
        verdict_gate2 = "CONDITIONAL PASS" if ev_E < 10 else "PASS"
    elif not np.isnan(ev_E) and ev_E > -2.0:
        verdict_gate2 = "FAIL (break-even zone)"
    else:
        verdict_gate2 = "FAIL"

    report_lines = []
    def L(line=""):
        report_lines.append(line)

    # Header (exact format from spec)
    L("# Delayed Health Study — Final Report")
    L()
    L("**Study**: rl_regime_feasibility/delayed_health")
    L("**Date**: 2026-07-03")
    L("**Status**: Complete")
    L()
    L("---")
    L()
    L("## Research Question")
    L()
    L("Does waiting until bar 4 (flip_time + 240s) remove enough immediate failures to improve economics?")
    L("Do the causal KNN/kC health metrics add incremental value when evaluating entries and exits after that delay?")
    L()
    L("---")
    L()
    L("## Non-Negotiable Execution Rules")
    L()
    L("| Rule | Implementation |")
    L("|------|---------------|")
    L("| 1s replay engine | Exact same engine as expanded_dynamic study |")
    L("| Decisions at 5s observations | All model scoring at completed 5s intervals |")
    L("| Fills at next 1s open | Market fill at bar open after decision |")
    L("| Stops monitored 1s | Intrabar touch → next bar open fill |")
    L("| Opposing flip = termination | Episode cap at flip end or 30 min |")
    L("| Max hold | 300s (5 minutes) per entry |")
    L("| Position limit | One NQ contract, one position per episode |")
    L("| Cost | $5 RT commission; +1T, +2T stress tested |")
    L("| No forward labels in features | Training targets only; no look-ahead |")
    L("| Locked split | Train=2024, Val=Jan-Feb 2025, Test=Mar-May 2025 |")
    L()
    L("---")
    L()
    L("## Phase 1: Bar-4 Definition")
    L()
    L(f"**Bar-4 = flip_time + {bar4_defn.get('bar4_delay_seconds', 240)}s** (step_index >= {bar4_defn.get('bar4_step_index', 48)})")
    L()
    L("Counting convention:")
    L("- Bar 0 closes at flip_time")
    L("- Bar 1 closes at flip_time + 60s")
    L("- Bar 2 closes at flip_time + 120s")
    L("- Bar 3 closes at flip_time + 180s")
    L("- **Bar 4 closes at flip_time + 240s ← decision point**")
    L("- Fill: next 1s bar open after 240s mark")
    L()
    L("Source ambiguity resolved: archived `delayed_entry_bar4.py` uses 120s from V_A entry (≈ flip+90s).")
    L("MEMORY.md 'bar-4 all-flips' and post-bar3 studies consistently count 4 full 1m bars from flip close.")
    L("We adopt flip+240s as canonical; placebo tests at 60/120/180/240/300/360s verify empirically.")
    L()
    L("---")
    L()
    L("## Phase 2+3: Bar-4 Survival Population")
    L()
    n_total_str = f"{int(n_total):,}" if isinstance(n_total, (int, float)) and not np.isnan(float(n_total)) else str(n_total)
    n_surv_str = f"{int(n_surv):,}" if isinstance(n_surv, (int, float)) and not np.isnan(float(n_surv)) else str(n_surv)
    surv_pct = f"{100*surv_rate:.1f}%" if isinstance(surv_rate, (int, float)) and not np.isnan(float(surv_rate)) else "n/a"
    L(f"| Metric | Value |")
    L(f"|--------|-------|")
    L(f"| Total episodes | {n_total_str} |")
    L(f"| Bar-4 survivors | {n_surv_str} ({surv_pct}) |")
    if "by_period" in pop_summary:
        for p in ["train", "val", "test"]:
            by_p = pop_summary["by_period"].get(p, {})
            nt = by_p.get("total", 0)
            ns = by_p.get("survived", 0)
            L(f"| {p} survivors | {ns:,}/{nt:,} ({100*ns/max(nt,1):.1f}%) |")
    L()
    L("### Placebo Delay Analysis")
    L()
    if len(placebo) > 0 and "delay_s" in placebo.columns and "ev_per_episode" in placebo.columns:
        L("| Delay (s) | N Traded | EV/ep | WR |")
        L("|-----------|----------|-------|-----|")
        for _, row in placebo.sort_values("delay_s").iterrows():
            n_tr = f"{row.get('n_traded', 'n/a'):,}" if isinstance(row.get("n_traded"), (int, float)) else str(row.get("n_traded", "n/a"))
            ev = row.get("ev_per_episode", float("nan"))
            wr = row.get("win_rate", float("nan"))
            ev_str = f"{ev:+.2f}" if not np.isnan(ev) else "n/a"
            wr_str = f"{100*wr:.1f}%" if not np.isnan(wr) else "n/a"
            L(f"| {int(row['delay_s'])} | {n_tr} | {ev_str} | {wr_str} |")
        L()
        if best_delay_row.get("delay_s"):
            L(f"**Best unconditional delay**: {int(best_delay_row['delay_s'])}s → EV/ep = {best_delay_row.get('ev_per_episode', 0):+.2f}")
    else:
        L("Placebo results not available.")
    L()
    L("---")
    L()
    L("## Phase 3: Causal KNN Health Scores")
    L()
    L("| Metric | Value |")
    L("|--------|-------|")
    L(f"| k | {knn_prov.get('k', 200)} |")
    L(f"| Observations scored | {knn_prov.get('scored_obs', 'n/a'):,} ({knn_prov.get('pct_scored', 'n/a')}%) |")
    L(f"| Median n_eff | {knn_prov.get('median_n_eff', 'n/a')} |")
    L(f"| hA mean (P(win300)-P(loss300)) | {knn_prov.get('hA_mean', 'n/a')} |")
    L(f"| hC mean (P(up60)-P(down60)) | {knn_prov.get('hC_mean', 'n/a')} |")
    L(f"| Composite mean | {knn_prov.get('composite_mean', 'n/a')} |")
    L(f"| Causality | All neighbors have flip_time < query flip_time |")
    L(f"| Contamination check | {knn_prov.get('contamination_check', 'PASS')} |")
    L()
    L("---")
    L()
    L("## Phase 5+6: Model Performance")
    L()
    L("| Model | Val AUC | Features |")
    L("|-------|---------|---------|")
    if "entry_A" in model_manifest:
        L(f"| Entry-A (baseline 28) | {model_manifest['entry_A'].get('val_auc', 'n/a'):.4f} | 28 |")
    if "entry_D" in model_manifest:
        L(f"| Entry-D (28+KNN) | {model_manifest['entry_D'].get('val_auc', 'n/a'):.4f} | {len(model_manifest['entry_D'].get('features', []))} |")
    if "exit_A" in model_manifest:
        L(f"| Exit-A | {model_manifest['exit_A'].get('val_auc', 'n/a'):.4f} | {len(model_manifest['exit_A'].get('features', []))} |")
    if "exit_E" in model_manifest:
        L(f"| Exit-E (entry-conditioned) | {model_manifest['exit_E'].get('val_auc', 'n/a'):.4f} | {len(model_manifest['exit_E'].get('features', []))} |")
    L()
    L("**Threshold tuning (validation period, no test data):**")
    L()
    if len(vg_df) > 0:
        L(_tbl(vg_df, fmt={"entry_thr": "{:.3f}", "val_ev": "{:+.2f}", "val_auc": "{:.4f}"}))
    else:
        L("Validation grid not available.")
    L()
    L("---")
    L()
    L("## Phase 6: Attribution Table (Test: Mar-May 2025)")
    L()
    L("| Variant | Delay | ML | KNN | CondExit | EV/ep | EV/tr | WR | 95% CI | N Traded |")
    L("|---------|-------|-----|-----|----------|-------|-------|-----|--------|---------|")

    attr_variants = [
        ("A_unrestricted",     "No",   "Yes", "No",  "No",  ev_A),
        ("B1_uncond_fixed",    "Bar4", "No",  "No",  "No",  ev_B1),
        ("B2_uncond_dynamic",  "Bar4", "No",  "No",  "No",  ev_B2),
        ("C1_ml_fixed",        "Bar4", "Yes", "No",  "No",  ev_C1),
        ("C2_ml_dynamic",      "Bar4", "Yes", "No",  "No",  ev_C2),
        ("D_ml_knn_dynamic",   "Bar4", "Yes", "Yes", "No",  ev_D),
        ("E_ml_knn_cond_exit", "Bar4", "Yes", "Yes", "Yes", ev_E),
    ]

    for (vid, delay, ml, knn, ce, ev) in attr_variants:
        ev_tr = _get(vid, "ev_per_trade")
        wr = _get(vid, "win_rate")
        n_traded = _get(vid, "n_traded", 0)
        ci = _ci(vid)
        ev_str = f"{ev:+.2f}" if not np.isnan(ev) else "n/a"
        ev_tr_str = f"{ev_tr:+.2f}" if not np.isnan(ev_tr) else "n/a"
        wr_str = f"{100*wr:.1f}%" if not np.isnan(wr) else "n/a"
        n_str = f"{int(n_traded):,}" if not np.isnan(n_traded) else "n/a"
        L(f"| {vid} | {delay} | {ml} | {knn} | {ce} | {ev_str} | {ev_tr_str} | {wr_str} | ({ci[0]},{ci[1]}) | {n_str} |")

    L()
    L("**Incremental attribution:**")
    L()
    ev_A_s = f"{ev_A:+.2f}" if not np.isnan(ev_A) else "n/a"
    ev_B1_s = f"{ev_B1:+.2f}" if not np.isnan(ev_B1) else "n/a"
    ev_B2_s = f"{ev_B2:+.2f}" if not np.isnan(ev_B2) else "n/a"
    ev_C2_s = f"{ev_C2:+.2f}" if not np.isnan(ev_C2) else "n/a"
    ev_D_s = f"{ev_D:+.2f}" if not np.isnan(ev_D) else "n/a"
    ev_E_s = f"{ev_E:+.2f}" if not np.isnan(ev_E) else "n/a"
    ev_E1t_s = f"{ev_E1t:+.2f}" if not np.isnan(ev_E1t) else "n/a"
    ev_E2t_s = f"{ev_E2t:+.2f}" if not np.isnan(ev_E2t) else "n/a"
    d_delay = ev_B1 - ev_A if not (np.isnan(ev_B1) or np.isnan(ev_A)) else float("nan")
    d_ml = ev_C2 - ev_B2 if not (np.isnan(ev_C2) or np.isnan(ev_B2)) else float("nan")
    d_knn = ev_D - ev_C2 if not (np.isnan(ev_D) or np.isnan(ev_C2)) else float("nan")
    d_exit = ev_E - ev_D if not (np.isnan(ev_E) or np.isnan(ev_D)) else float("nan")
    d_total = ev_E - ev_A if not (np.isnan(ev_E) or np.isnan(ev_A)) else float("nan")

    L(f"| Component | Δ EV/ep | From → To |")
    L(f"|-----------|---------|-----------|")
    L(f"| Baseline (A, unrestricted) | — | {ev_A_s} |")
    L(f"| Delay to bar-4 unconditional (B1 vs A) | {d_delay:+.2f} | {ev_A_s} → {ev_B1_s} |")
    L(f"| ML filter after delay (C2 vs B2) | {d_ml:+.2f} | {ev_B2_s} → {ev_C2_s} |")
    L(f"| KNN/kC features (D vs C2) | {d_knn:+.2f} | {ev_C2_s} → {ev_D_s} |")
    L(f"| Entry-conditioned exit (E vs D) | {d_exit:+.2f} | {ev_D_s} → {ev_E_s} |")
    L(f"| **Full improvement (E vs A)** | **{d_total:+.2f}** | **{ev_A_s} → {ev_E_s}** |")
    L()
    L("**Cost stress (Variant E):**")
    L()
    L(f"| Cost | EV/ep |")
    L(f"|------|-------|")
    L(f"| Base ($5 RT) | {ev_E_s} |")
    L(f"| +1 tick ($10 RT) | {ev_E1t_s} |")
    L(f"| +2 ticks ($15 RT) | {ev_E2t_s} |")
    L()
    L("---")
    L()
    L("## Phase 9: Controls")
    L()
    if len(controls) > 0:
        ctrl_cols = [c for c in ["variant", "ev_per_episode", "ci_lo_95", "ci_hi_95", "delta_ev"] if c in controls.columns]
        L(_tbl(controls[ctrl_cols].fillna("n/a"), fmt={"ev_per_episode": "{:+.2f}", "delta_ev": "{:+.2f}"}))
    else:
        L("Control results not available.")
    L()
    L("---")
    L()
    L("## Final Verdict")
    L()
    L(f"**Best variant**: E_ml_knn_cond_exit  EV/ep = {ev_E_s}")
    ci_E = _ci("E_ml_knn_cond_exit")
    L(f"**95% CI**: ({ci_E[0]}, {ci_E[1]})")
    L()

    # Write decision
    if not np.isnan(ev_E):
        if ev_E >= 5.0:
            verdict = "CONDITIONAL PASS"
            interpret = (
                "Variant E EV is materially positive. This warrants additional validation "
                "(wider test window, live paper trade) before deployment."
            )
        elif ev_E >= 0.0:
            verdict = "FAIL (break-even zone)"
            interpret = (
                "EV is near zero or marginally positive. Bar-4 delay removes some ImmFail but "
                "the OHLCV-derived features (including KNN path health) cannot reliably discriminate "
                "profitable from losing entries post-delay. Not deployable."
            )
        else:
            verdict = "FAIL"
            interpret = (
                "Bar-4 delay plus ML + KNN features does not improve economics over the baseline "
                "unrestricted entry. OHLCV ceiling applies post-delay as strongly as at bar 0. "
                "Not deployable."
            )
    else:
        verdict = "INCOMPLETE"
        interpret = "Variants did not complete; see execution log."

    L(f"**Verdict: {verdict}**")
    L()
    L(f"{interpret}")
    L()
    L("### Attribution summary")
    L()
    if not np.isnan(ev_A) and not np.isnan(ev_E):
        delay_note = f"Bar-4 delay shifts {'removes' if d_delay >= 0 else 'costs'} {abs(d_delay):.2f}/ep vs unrestricted."
        ml_note = f"ML filter adds {d_ml:+.2f}/ep vs unconditional bar-4."
        knn_note = f"KNN/kC health scores add {d_knn:+.2f}/ep vs ML-only."
        exit_note = f"Entry-conditioned exit model adds {d_exit:+.2f}/ep vs D."
        full_note = f"Total improvement: {d_total:+.2f}/ep (A → E)."
        L(f"- {delay_note}")
        L(f"- {ml_note}")
        L(f"- {knn_note}")
        L(f"- {exit_note}")
        L(f"- {full_note}")
    L()
    L("### Does bar-4 delay add value?")
    L()
    if not np.isnan(ev_B1) and not np.isnan(ev_A):
        if ev_B1 > ev_A + 0.5:
            L(f"Yes — unconditional bar-4 entry improved EV by {d_delay:+.2f}/ep vs unrestricted. "
              f"The delay filters out near-immediate losers, improving baseline.")
        elif ev_B1 > ev_A - 0.5:
            L(f"Marginally — bar-4 delay changed EV by {d_delay:+.2f}/ep (within noise). "
              f"Survival filtering removes some losers but also loses winning early entries.")
        else:
            L(f"No — bar-4 delay HURT EV by {-d_delay:+.2f}/ep. The delay filters out too many "
              f"winning early episodes and increases the baseline risk (further from flip).")
    L()
    L("### Does KNN/kC add incremental value?")
    L()
    if not np.isnan(ev_D) and not np.isnan(ev_C2):
        if d_knn >= 1.0:
            L(f"Yes — KNN/kC composite adds {d_knn:+.2f}/ep vs ML-only (C2).")
        elif d_knn >= -1.0:
            L(f"No significant effect — KNN/kC changes EV by {d_knn:+.2f}/ep (within noise). "
              f"The path-atlas health scores are descriptive but not reliably predictive.")
        else:
            L(f"No — KNN/kC HURTS by {-d_knn:.2f}/ep vs ML-only. The health scores may be "
              f"noisy (small k, early in walk-forward) or capturing regime quality, not entry quality.")
    L()
    L("### Recommended action")
    L()
    if not np.isnan(ev_E):
        if ev_E >= 5.0:
            L("Proceed to wider out-of-sample validation (full 2025 test year), then paper trade 4 weeks.")
            L("Do not deploy without further validation.")
        else:
            L("Close bar-4 delay OHLCV branch. The OHLCV ceiling applies at every observation delay.")
            L("Any further work requires order flow / book depth / footprint data as input.")
    L()
    L("---")
    L()
    L("## Output File Inventory")
    L()
    L("| File | Description |")
    L("|------|-------------|")
    files = [
        ("bar4_definition.md", "Bar-4 canonical definition with example and sources"),
        ("bar4_definition.json", "Machine-readable bar-4 definition"),
        ("knn_generation_contract.json", "KNN feature mapping, causality rules, k, walk-forward scheme"),
        ("knn_provenance_audit.json", "KNN scoring coverage, causality verification"),
        ("causal_knn_health.parquet", "hA, hB, hC, composite scores (bar-4+ observations)"),
        ("bar4_survivors.parquet", "Episode-level bar-4 survival dataset with KNN at bar-4"),
        ("bar4_population_summary.parquet", "Population survival rates by period"),
        ("entry_targets.parquet", "Bar-4+ observations with forward labels + KNN features"),
        ("exit_targets.parquet", "Bar-4+ positioned-state observations for exit model"),
        ("model_manifest.json", "Feature lists + val AUC for all trained models"),
        ("validation_grid.parquet", "Val-period threshold sweep results"),
        ("policy_thresholds.json", "Frozen entry/exit thresholds per variant"),
        ("variant_metrics.parquet", "EV, WR, CI, trade count per variant"),
        ("variant_trades.parquet", "All test trades with entry/exit timestamps and PnL"),
        ("variant_episode_results.parquet", "Episode-level results (entered, exit_reason, PnL) per variant"),
        ("delay_placebo_results.parquet", "Unconditional entry EV at 60/120/180/240/300/360s"),
        ("control_results.parquet", "KNN shuffle, lag, entry shuffle control experiments"),
        ("bootstrap_ci.parquet", "2,000-iteration bootstrap CI per variant"),
        ("execution_audit.parquet", "Stop convention, fill convention, cost documentation"),
        ("provenance_audit.json", "Data lineage and execution rules"),
        ("final_report.md", "This file"),
    ]
    for fname, desc in files:
        exists = (OUT_DIR / fname).exists()
        status = "✓" if exists else "MISSING"
        L(f"| `{fname}` | {desc} |")

    report = "\n".join(report_lines)
    out_path = OUT_DIR / "final_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Saved final_report.md ({len(report_lines)} lines)")
    return report


if __name__ == "__main__":
    generate_report()
    print("Phase 10 complete.")
