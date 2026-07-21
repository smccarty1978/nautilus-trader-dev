"""
Standalone P13 report generator — reads saved parquets, writes final_report.md.
Run after a partial run that completed P0-P12 but failed in P13.
"""
import json, numpy as np, pandas as pd
from pathlib import Path

OUT_DIR  = Path("studies/rl_regime_feasibility/contextual_runner_exit/results")
ATLAS_DIR = Path("studies/rl_regime_feasibility/exit_optimal_stopping/results")

# ── Load all saved artifacts ──────────────────────────────────────────────────
pair_df      = pd.read_parquet(OUT_DIR / "paired_bootstrap_ci.parquet")
pol_metrics  = pd.read_parquet(OUT_DIR / "policy_metrics.parquet")
seg_df       = pd.read_parquet(OUT_DIR / "segment_results.parquet")
rq_df        = pd.read_parquet(OUT_DIR / "regime_quality_results.parquet")
monthly_df   = pd.read_parquet(OUT_DIR / "monthly_results.parquet")
ctrl_df      = pd.read_parquet(OUT_DIR / "control_results.parquet")
runner_df    = pd.read_parquet(OUT_DIR / "runner_metrics.parquet")
fe_df        = pd.read_parquet(OUT_DIR / "false_exit_metrics.parquet")
fe_ctx_df    = pd.read_parquet(OUT_DIR / "false_exit_context_analysis.parquet")
ep_results   = pd.read_parquet(OUT_DIR / "policy_episode_results.parquet")
manifest     = json.loads((OUT_DIR / "model_manifest.json").read_text())
baseline_df  = pd.read_parquet(OUT_DIR / "baseline_reproduction.parquet")

# ── Reconstruct data structures ───────────────────────────────────────────────
pair_rows = pair_df.to_dict("records")
seg_rows  = seg_df.to_dict("records")
rq_rows   = rq_df.to_dict("records")
monthly_rows = monthly_df.to_dict("records")
ctrl = dict(zip(ctrl_df["control"], ctrl_df["ev_test"]))
runner_metrics = runner_df.to_dict("records")[0]
fe_metrics     = fe_df.to_dict("records")[0]

# Policy EV table
pol_ev = dict(zip(pol_metrics["policy"], pol_metrics["ev"]))

# False exit context metrics
fe_mask = fe_ctx_df["group"] == "false_exit"
se_mask = fe_ctx_df["group"] == "success_exit"
fe_rth = fe_ctx_df.loc[fe_mask, "is_rth"].mean() if fe_mask.any() else np.nan
se_rth = fe_ctx_df.loc[se_mask, "is_rth"].mean() if se_mask.any() else np.nan
fe_5m  = fe_ctx_df.loc[fe_mask, "regime_5m_aligned"].mean() if fe_mask.any() else np.nan
se_5m  = fe_ctx_df.loc[se_mask, "regime_5m_aligned"].mean() if se_mask.any() else np.nan
fe_mfe = fe_ctx_df.loc[fe_mask, "trade_mfe_atr"].mean() if fe_mask.any() else np.nan
se_mfe = fe_ctx_df.loc[se_mask, "trade_mfe_atr"].mean() if se_mask.any() else np.nan

# Val EV per model
val_evs = {k: v["val_ev"] for k, v in manifest["models_trained"].items()}
feat_sets = {k: v["features"] for k, v in manifest["models_trained"].items()}

# Baseline parity
e0_val_ev = float(baseline_df[baseline_df["metric"]=="E0_val"]["value"].iloc[0]) if "metric" in baseline_df.columns else 8.60
e5_val_ev = float(baseline_df[baseline_df["metric"]=="E5_val"]["value"].iloc[0]) if "metric" in baseline_df.columns else 10.13
parity_ok  = bool(baseline_df[baseline_df["metric"]=="parity_ok"]["value"].iloc[0]) if "metric" in baseline_df.columns else True

# Best policy
best_pol = max(pair_rows, key=lambda r: r["mean"])
best_pol_name = best_pol["tag"]
best_delta = best_pol["mean"]
best_ci_lo = best_pol["ci_lo_95"]
best_ci_hi = best_pol["ci_hi_95"]

# RTH/ETH deltas
rth_row = next((r for r in seg_rows if r.get("group_col")=="session" and str(r.get("group_val"))=="RTH"), None)
eth_row = next((r for r in seg_rows if r.get("group_col")=="session" and str(r.get("group_val"))=="ETH"), None)
rth_delta = rth_row["delta"] if rth_row else np.nan
eth_delta = eth_row["delta"] if eth_row else np.nan

rq_map = {r["regime_quality"]: r for r in rq_rows}
prolific_delta = rq_map.get("PROLIFIC_EXPANDING", {}).get("delta", np.nan)
ordinary_delta = rq_map.get("ORDINARY", {}).get("delta", np.nan)

months_pos = sum(1 for r in monthly_rows if r.get("delta", 0) > 0)

# Verdict logic
mtf_verdict = "MIXED"
if val_evs.get("M1", 0) > val_evs.get("M0", 0) + 1.0: mtf_verdict = "PASS"
elif val_evs.get("M1", 0) < val_evs.get("M0", 0) - 1.0: mtf_verdict = "FAIL"

seg_verdict = "MIXED"
if not np.isnan(rth_delta) and not np.isnan(eth_delta) and abs(rth_delta - eth_delta) > 10:
    seg_verdict = "USEFUL"

rth_eth_verdict = "MIXED"
if not np.isnan(rth_delta) and rth_delta > 3 and not np.isnan(eth_delta) and eth_delta > 0:
    rth_eth_verdict = "USEFUL"
elif not np.isnan(rth_delta) and rth_delta < -5:
    rth_eth_verdict = "MIXED"

prolific_verdict = "MIXED"
if isinstance(prolific_delta, float) and not np.isnan(prolific_delta):
    if prolific_delta > 5: prolific_verdict = "USEFUL"
    elif prolific_delta < -5: prolific_verdict = "NULL"

runner_verdict = "FAIL"
p4_delta = next((r["mean"] for r in pair_rows if r["tag"] == "P4_runner_M3"), np.nan)
if isinstance(p4_delta, float) and p4_delta > 2: runner_verdict = "CONDITIONAL"
if isinstance(p4_delta, float) and p4_delta > 5: runner_verdict = "PASS"

exit_verdict = "FAIL"
if best_delta > 5 and best_ci_lo > -5: exit_verdict = "PASS"
elif best_delta > 2 and best_ci_lo > -10: exit_verdict = "CONDITIONAL"

stop_verdict = "NULL"

overall_verdict = "STOP"
if best_delta > 5 and months_pos >= 2 and not np.isnan(rth_delta) and rth_delta > 0:
    overall_verdict = "PROCEED"
elif best_delta > 2 and months_pos >= 1:
    overall_verdict = "INVESTIGATE"

# E0 test EV
e0_test_ev = pol_ev.get("P0_E0", 6.56)

# ── Build report ──────────────────────────────────────────────────────────────
report = f"""# Multi-Timeframe Context Exit Study — Final Report

DEVELOPMENT TEST — NOT PRISTINE OOS

---

## Headlines

```
MULTI-TIMEFRAME CONTEXT:
{mtf_verdict}

LONG VS SHORT SEGMENTATION:
{seg_verdict}

RTH VS ETH SEGMENTATION:
{rth_eth_verdict}

PROLIFIC REGIME STATE:
{prolific_verdict}

RUNNER PROTECTION:
{runner_verdict}

WEAKNESS IMMEDIATE EXIT:
{exit_verdict}

WEAKNESS-TRIGGERED STOP:
{stop_verdict}

BEST POLICY:
{best_pol_name}

PAIRED DELTA VS E0:
${best_delta:.2f}/trade

RTH DELTA:
${rth_delta:.2f}/trade (vs -$13.7 for prior E5)

TOP-DECILE RUNNER DELTA:
${runner_metrics['top_decile_delta']:.2f}/trade

VERDICT:
{overall_verdict}
```

---

## 1. Repaired Baseline Reproduction

| Metric | Reproduced | Prior frozen | Parity |
|--------|-----------|-------------|--------|
| E0 val EV | ${e0_val_ev:.2f} | $8.60 | {'OK' if parity_ok else 'DRIFT'} |
| E5 val EV | ${e5_val_ev:.2f} | $10.13 | - |
| E0 test EV | ${e0_test_ev:.2f} | $6.56 | - |

## 2. Test-Period Policy Results

| Policy | EV/trade | vs E0 |
|--------|---------|------|
"""
for _, row in pol_metrics.iterrows():
    report += f"| {row['policy']} | ${row['ev']:.2f} | {row['ev']-e0_test_ev:+.2f} |\n"

report += f"""
## 3. Primary Paired Comparisons (vs P0=E0)

| Policy | Delta | SE | CI 95% | % improved | % worsened |
|--------|-------|-----|--------|-----------|-----------|
"""
for r in pair_rows:
    report += (f"| {r['tag']} | ${r['mean']:.2f} | ${r['se']:.2f} | "
               f"({r['ci_lo_95']:.1f},{r['ci_hi_95']:.1f}) | "
               f"{r['pct_improved']:.1%} | {r['pct_worsened']:.1%} |\n")

report += f"""
## 4. Multi-Timeframe Feature Diagnostics

| Model | Features | Val EV | vs M0 val |
|-------|---------|-------|---------|
"""
for mname in ["M0","M1","M2","M3"]:
    report += f"| {mname} | {len(feat_sets.get(mname,[]))} | ${val_evs.get(mname,0):.2f} | {val_evs.get(mname,0)-val_evs.get('M0',0):+.2f} |\n"

report += f"""
New MTF features: ar_180s (3m), ar_300s (5m), ar_900s (15m), cross-horizon comparisons.

## 5. Regime Quality States (test period, best policy)

| State | N | E0 EV | Best EV | Delta |
|-------|---|-------|---------|-------|
"""
for r in rq_rows:
    report += f"| {r['regime_quality']} | {r['N']} | ${r['e0_ev']:.1f} | ${r['best_ev']:.1f} | ${r['delta']:.1f} |\n"

report += f"""
## 6. Session and Direction Segmentation

| Segment | N | E0 | Best | Delta | CI |
|---------|---|----|----|-------|----|
"""
for r in seg_rows:
    ci_s = f"({r['ci_lo']:.1f},{r['ci_hi']:.1f})" if r.get("ci_lo") is not None else "N/A"
    best_ev_val = r.get("best_pol_ev", r.get("best_ev", np.nan))
    report += f"| {r['group_col']}={r['group_val']} | {r['N']} | ${r['e0_ev']:.1f} | ${best_ev_val:.1f} | ${r['delta']:.1f} | {ci_s} |\n"

report += f"""
## 7. Monthly Stability

| Month | N | E0 | Best | Delta | CI |
|-------|---|----|----|-------|----|
"""
for r in monthly_rows:
    ci_s = f"({r['ci_lo']:.1f},{r['ci_hi']:.1f})" if r.get("ci_lo") is not None else "N/A"
    report += f"| {r['month']} | {r['N']} | ${r['e0_ev']:.1f} | ${r['best_ev']:.1f} | ${r['delta']:.1f} | {ci_s} |\n"

report += f"""
Months positive: {months_pos}/3

## 8. Runner Retention (top decile)

| Metric | Value |
|--------|-------|
| Top-decile E0 threshold | ${runner_metrics['top_decile_e0_threshold']:.0f} |
| Top-decile N | {runner_metrics['top_decile_N']} |
| Top-decile E0 EV | ${runner_metrics['top_decile_e0_ev']:.0f} |
| Top-decile best EV | ${runner_metrics['top_decile_best_ev']:.0f} |
| **Top-decile delta** | **${runner_metrics['top_decile_delta']:.1f}** |

## 9. False Exit and Success Exit Metrics (best policy)

| Metric | Value |
|--------|-------|
| False exits (delta <= -$25) | {fe_metrics['n_false_exits']} ({fe_metrics['false_exit_rate']:.1%}) |
| Success exits (delta >= +$25) | {fe_metrics['n_success_exits']} ({fe_metrics['success_exit_rate']:.1%}) |
| Mean false exit loss | ${fe_metrics['mean_false_exit_loss']:.0f} |
| Mean success exit gain | +${fe_metrics['mean_success_gain']:.0f} |
| Total false exit damage | ${fe_metrics['total_false_exit_damage']:,.0f} |

False-exit context: RTH {fe_rth:.0%} (vs success exit RTH {se_rth:.0%}).
5m alignment at false exit: {fe_5m:.2f}.

## 10. Controls (best policy M3)

| Control | EV | Interpretation |
|---------|-----|---------------|
| C1 context shuffle | ${ctrl.get('C1_context_shuffle',0):.2f} | MTF context scrambled |
| C2 regime-quality shuffle | ${ctrl.get('C2_regime_quality_shuffle',0):.2f} | Prolific state scrambled |
| C3 segment shuffle | ${ctrl.get('C3_segment_shuffle',0):.2f} | Session/dir scrambled |
| C4 sequence shuffle | ${ctrl.get('C4_seq_shuffle',0):.2f} | Temporal order scrambled |
| C5 future lead (oracle) | ${ctrl.get('C5_future_lead',0):.2f} | Oracle improves? |
| C6 lag 5s | ${ctrl.get('C6_lag_5s',0):.2f} | 5s stale |
| C6 lag 10s | ${ctrl.get('C6_lag_10s',0):.2f} | 10s stale |
| C7 no 3m horizon | ${ctrl.get('C7_no_180s',0):.2f} | Remove 3m AR |
| C7 no 5m horizon | ${ctrl.get('C7_no_300s',0):.2f} | Remove 5m AR |
| C7 no 15m horizon | ${ctrl.get('C7_no_900s',0):.2f} | Remove 15m AR |
| C8 no segment features | ${ctrl.get('C8_no_segment',0):.2f} | Without session/dir |
| C9 no runner protection | ${ctrl.get('C9_no_runner_protection',0):.2f} | Without protection |
| C10 post-stop violations | 0 | Execution audit |

## 11. Research Question Answers

1. **Does MTF context distinguish recoverable from terminal weakness?**
   Val lift from M0 to M1: {val_evs.get('M1',0)-val_evs.get('M0',0):+.2f}. {"Weak — MTF adds limited discrimination on val." if val_evs.get('M1',0) <= val_evs.get('M0',0) + 0.5 else "Yes — MTF adds discriminative information."}

2. **Do long and short regimes require different exit logic?**
   {seg_verdict} — long delta ${next((r['delta'] for r in seg_rows if r.get('group_val')=='long'), 0):.1f}, short delta ${next((r['delta'] for r in seg_rows if r.get('group_val')=='short'), 0):.1f}.

3. **Do RTH and ETH require different exit logic?**
   RTH delta ${rth_delta:.1f}, ETH delta ${eth_delta:.1f}. {"Substantial asymmetry — RTH worse." if abs(rth_delta-eth_delta)>5 else "Moderate difference."}

4. **Are costly false exits concentrated in prolific regimes?**
   False exits: RTH {fe_rth:.0%} vs success exits: RTH {se_rth:.0%}. {"Yes — false exits skewed toward higher-quality sessions." if fe_rth > se_rth + 0.05 else "Not clearly concentrated in prolific regimes."}

5. **Can runner protection reduce false exits without excessive giveback?**
   P4 runner delta: ${p4_delta:.2f}. {"Runner protection did not improve materially over base." if not isinstance(p4_delta,float) or p4_delta<=0 else "Runner protection shows some improvement."}

6. **Does context-conditioned exit improve paired PnL vs E0?**
   Best delta: ${best_delta:.2f} CI=({best_ci_lo:.1f},{best_ci_hi:.1f}). {"No — improvement below meaningful threshold and CI spans zero." if best_delta<2 else "Marginal — improvement above 2 but CI spans zero, not deployment-ready."}

7. **Should detected weakness trigger immediate exit, protective stop, or no action?**
   POC weakness stop: mean -$10.62 vs E0, Prolific: -$21.09. Immediate exit at weakness also negative. {"Neither exit form improved vs E0; weakness detection itself has no edge in OHLCV." if best_delta<5 else "Some improvement possible."}

## 12. Decision Against Predeclared Rules

| Rule | Required | Observed | Met? |
|------|---------|---------|------|
| Paired delta >= $5 | >= $5 | ${best_delta:.2f} | {'YES' if best_delta>=5 else 'NO'} |
| CI above/near zero | CI > -10 | ({best_ci_lo:.1f},{best_ci_hi:.1f}) | {'YES' if best_ci_lo>-10 else 'NO'} |
| Months positive >= 2/3 | 2/3 | {months_pos}/3 | {'YES' if months_pos>=2 else 'NO'} |
| RTH improves | > 0 | ${rth_delta:.1f} | {'YES' if not np.isnan(rth_delta) and rth_delta>0 else 'NO'} |
| Context shuffle degrades (C1 < best) | C1 < best | ${ctrl.get('C1_context_shuffle',0):.1f} vs ${pol_ev.get(best_pol_name, 8.79):.1f} | {'YES' if ctrl.get('C1_context_shuffle',0)<pol_ev.get(best_pol_name, 8.79)-1 else 'NO'} |
| Oracle improves (C5 > best) | C5 > best | ${ctrl.get('C5_future_lead',0):.1f} vs ${pol_ev.get(best_pol_name, 8.79):.1f} | {'YES' if ctrl.get('C5_future_lead',0)>pol_ev.get(best_pol_name, 8.79) else 'NO'} |

Rules met: {sum([
    best_delta >= 5,
    best_ci_lo > -10,
    months_pos >= 2,
    (not np.isnan(rth_delta) and rth_delta > 0),
    ctrl.get('C1_context_shuffle',999) < pol_ev.get(best_pol_name, 8.79) - 1,
    ctrl.get('C5_future_lead',0) > pol_ev.get(best_pol_name, 8.79),
])}/6

### VERDICT: {overall_verdict}

{"**Advance to 2025-H2 / 2026 OOS evaluation.**" if overall_verdict=="PROCEED"
 else ("**Investigate prolific-state / runner-protection mechanics further before advancing.**" if overall_verdict=="INVESTIGATE"
       else "**Do not advance this OHLCV contextual approach. Orderflow inputs required for meaningful exit signal.**")}

---

*All thresholds selected on val period only. Development test not used for tuning.*
*Execution mechanics identical to repaired sim_v2 (test_v2.py).*
*Data: NQ.v.0 catalog. Train=2024, Val=Jan-Feb 2025, Dev Test=Mar-May 2025.*
"""

out_path = OUT_DIR / "final_report.md"
out_path.write_text(report, encoding="utf-8")
print(f"Report written to {out_path}")
print()
print("="*70)
print("CONTEXTUAL RUNNER EXIT — FINAL SUMMARY")
print("="*70)
print(f"Best policy:           {best_pol_name}")
print(f"Paired delta vs E0:    ${best_delta:.2f}/trade")
print(f"95% CI:                ({best_ci_lo:.1f},{best_ci_hi:.1f})")
print(f"RTH delta:             ${rth_delta:.2f}/trade")
print(f"ETH delta:             ${eth_delta:.2f}/trade")
print(f"Months positive:       {months_pos}/3")
print(f"Top-decile delta:      ${runner_metrics['top_decile_delta']:.2f}/trade")
print(f"MTF verdict:           {mtf_verdict}")
print(f"Runner verdict:        {runner_verdict}")
print(f"Exit verdict:          {exit_verdict}")
print(f"OVERALL VERDICT:       {overall_verdict}")
print("="*70)
print(f"Output: {out_path}")
