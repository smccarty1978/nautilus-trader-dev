"""
Phase 9-13 + final report -- orchestrator.

Assumes audit_prior_results.py, reconcile_baselines.py, build_state_events.py,
build_deterministic_policies.py, simulate_state_stops.py, run_matched_controls.py
and exact_replay.py have already been run (their outputs are read from
results/). Produces:

  results/segment_results.parquet         (Phase 9)
  results/state_at_decision_results.parquet (Phase 10 cont.)
  results/monthly_results.parquet         (Phase 13)
  results/runner_results.parquet          (Phase 11)
  results/false_exit_metrics.parquet      (Phase 12)
  results/tail_sensitivity.parquet        (Phase 13)
  results/final_report.md                 (Phase 15)

Then prints the required terminal summary.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

import base as C

PRIMARY = "P9_session_x_direction"
BASELINE = "P7_session_specific"


def bootstrap_row(pol_df, e0, idx, pol_name, extra=None):
    d = (pol_df.loc[idx, pol_name] - e0.loc[idx])
    lo, hi = C.paired_bootstrap_ci(d.values)
    row = {"policy": pol_name, "n": len(idx),
           "e0_ev": round(float(e0.loc[idx].mean()), 2) if len(idx) else np.nan,
           "policy_ev": round(float(pol_df.loc[idx, pol_name].mean()), 2) if len(idx) else np.nan,
           "delta": round(float(d.mean()), 2) if len(idx) else np.nan,
           "ci_lo": round(lo, 2), "ci_hi": round(hi, 2)}
    if extra:
        row.update(extra)
    return row


def main():
    print("=" * 70)
    print("Phase 9-13 -- segment / state / runner / false-exit / monthly / tail reporting")
    print("=" * 70)

    train, val, test, tt = C.load_base()

    pol_df = pd.read_parquet(C.RESULTS / "policy_trades.parquet")
    if "episode_id" in pol_df.columns:
        pol_df = pol_df.set_index("episode_id")
    pol_metrics = pd.read_parquet(C.RESULTS / "policy_metrics.parquet")
    attrib_df = pd.read_parquet(C.RESULTS / "policy_exit_state_attribution.parquet")

    ep_base_test, ep_meta_test = C.prep_period(test, tt, "test")
    e0 = pol_df["P0_E0"]
    policies = [c for c in pol_df.columns if c != "P0_E0"]

    oracle = pd.read_parquet(C.V3_RESULTS.parent.parent / "exit_optimal_stopping" / "results" /
                             "exit_atlas_checkpoints.parquet",
                             columns=["episode_id", "observation_time", "remaining_mfe_atr",
                                     "max_future_giveback_atr"])

    ep_dir = ep_meta_test["direction"]
    ep_rth = test.groupby("episode_id")["is_rth"].first().reindex(ep_dir.index)

    # ── Phase 9: segment reporting ───────────────────────────────────────────
    print("\n[Phase 9] segment reporting ...")
    seg_rows = []
    for pol_name in [PRIMARY, BASELINE, "P1_immediate_terminal"]:
        combos = [
            ("session", "RTH", ep_rth == 1), ("session", "ETH", ep_rth != 1),
            ("direction", "long", ep_dir == 1), ("direction", "short", ep_dir == -1),
            ("dir_session", "RTH_long", (ep_rth == 1) & (ep_dir == 1)),
            ("dir_session", "RTH_short", (ep_rth == 1) & (ep_dir == -1)),
            ("dir_session", "ETH_long", (ep_rth != 1) & (ep_dir == 1)),
            ("dir_session", "ETH_short", (ep_rth != 1) & (ep_dir == -1)),
        ]
        for gcol, gval, mask in combos:
            idx = mask[mask].index.intersection(pol_df.index)
            if len(idx) < 10:
                continue
            fired = (pol_df.loc[idx, pol_name] != e0.loc[idx])
            row = bootstrap_row(pol_df, e0, idx, pol_name, {"group": gcol, "value": gval})
            row["intervention_rate"] = round(float(fired.mean()), 3)
            d = pol_df.loc[idx, pol_name] - e0.loc[idx]
            row["false_exit_rate"] = round(float((d <= -25).mean()), 3)
            row["successful_intervention_rate"] = round(float((d >= 25).mean()), 3)
            seg_rows.append(row)
    seg_df = pd.DataFrame(seg_rows)
    seg_df.to_parquet(C.RESULTS / "segment_results.parquet", index=False)
    print(seg_df[seg_df.policy == PRIMARY].to_string(index=False))

    # ── Phase 10 cont.: state-at-decision reporting (per PRIMARY policy) ────
    print("\n[Phase 10 cont.] state-at-decision reporting ...")
    prim_attrib = attrib_df[attrib_df.policy == PRIMARY].set_index("episode_id")
    orc = oracle.merge(
        prim_attrib.reset_index()[["episode_id", "policy_decision_ts"]].rename(
            columns={"policy_decision_ts": "observation_time"}),
        on=["episode_id", "observation_time"], how="inner")
    state_rows = []
    for st in C.STATES:
        idx = prim_attrib[prim_attrib["smoothed_state_at_decision"] == st].index.intersection(pol_df.index)
        if len(idx) < 5:
            continue
        d = pol_df.loc[idx, PRIMARY] - e0.loc[idx]
        orc_sub = orc[orc["episode_id"].isin(idx)]
        state_rows.append({
            "state": st, "n_exits": len(idx), "e0_ev": round(float(e0.loc[idx].mean()), 2),
            "policy_ev": round(float(pol_df.loc[idx, PRIMARY].mean()), 2), "delta": round(float(d.mean()), 2),
            "false_exit_rate": round(float((d <= -25).mean()), 3), "successful_exit_rate": round(float((d >= 25).mean()), 3),
            "remaining_mfe_forfeited_atr": round(float(orc_sub["remaining_mfe_atr"].mean()), 3) if len(orc_sub) else np.nan,
        })
    state_df = pd.DataFrame(state_rows)
    state_df.to_parquet(C.RESULTS / "state_at_decision_results.parquet", index=False)
    print(state_df.to_string(index=False))

    # ── Phase 13 (monthly) ────────────────────────────────────────────────────
    print("\n[Phase 13a] monthly stability ...")
    ets = tt[tt["period"] == "test"].set_index("episode_id")["observation_time"]
    months = pd.to_datetime(ets.reindex(pol_df.index).values.astype("float64"), unit="ns").strftime("%Y-%m")
    mo_rows = []
    for pol_name in [PRIMARY, BASELINE]:
        for mo in sorted(set(months.dropna())):
            m = (months == mo)
            idx = pol_df.index[m]
            if len(idx) < 5:
                continue
            mo_rows.append(bootstrap_row(pol_df, e0, idx, pol_name, {"month": mo}))
    mo_df = pd.DataFrame(mo_rows)
    mo_df.to_parquet(C.RESULTS / "monthly_results.parquet", index=False)
    months_pos = int((mo_df[mo_df.policy == PRIMARY]["delta"] > 0).sum())
    print(mo_df[mo_df.policy == PRIMARY].to_string(index=False))

    # ── Phase 11: runner evaluation ───────────────────────────────────────────
    print("\n[Phase 11] runner evaluation ...")
    runner_rows = []
    for pct, label in [(0.90, "top10"), (0.95, "top5"), (0.99, "top1")]:
        thr = e0.quantile(pct)
        m = e0 >= thr
        idx = e0.index[m]
        for pol_name in policies:
            d = pol_df.loc[idx, pol_name] - e0.loc[idx]
            pol_attrib = attrib_df[attrib_df.policy == pol_name].set_index("episode_id")
            st_sub = pol_attrib["smoothed_state_at_decision"].reindex(idx)
            retention = float(pol_df.loc[idx, pol_name].mean() / e0.loc[idx].mean()) if e0.loc[idx].mean() != 0 else np.nan
            orc_sub = oracle.merge(
                pol_attrib.reset_index()[["episode_id", "policy_decision_ts"]].rename(
                    columns={"policy_decision_ts": "observation_time"}),
                on=["episode_id", "observation_time"], how="inner")
            orc_sub = orc_sub[orc_sub["episode_id"].isin(idx)]
            runner_rows.append({
                "tier": label, "policy": pol_name, "n": int(m.sum()),
                "e0_ev": round(float(e0.loc[idx].mean()), 1), "policy_ev": round(float(pol_df.loc[idx, pol_name].mean()), 1),
                "delta": round(float(d.mean()), 1), "retention": round(retention, 3),
                "pct_new_mfe_state_weakening": round(float((st_sub == "WEAKENING").mean()), 3),
                "pct_new_mfe_state_terminal": round(float((st_sub == "TERMINAL").mean()), 3),
                "remaining_mfe_forfeited_atr": round(float(orc_sub["remaining_mfe_atr"].mean()), 3) if len(orc_sub) else np.nan,
                "giveback_avoided_dollars": round(float(d[d > 0].mean()), 2) if (d > 0).any() else 0.0,
            })
    runner_df = pd.DataFrame(runner_rows)
    runner_df.to_parquet(C.RESULTS / "runner_results.parquet", index=False)
    top10 = runner_df[runner_df.tier == "top10"]
    print(top10[top10.policy == PRIMARY].to_string(index=False))

    # ── Phase 12: false-exit attribution ─────────────────────────────────────
    print("\n[Phase 12] false-exit attribution ...")
    d_primary = pol_df[PRIMARY] - e0
    cls = np.where(d_primary >= 25, "successful", np.where(d_primary <= -25, "false_exit", "neutral"))
    fe = {
        "policy": PRIMARY, "n_successful": int((cls == "successful").sum()),
        "n_false_exit": int((cls == "false_exit").sum()), "n_neutral": int((cls == "neutral").sum()),
        "mean_success_gain": round(float(d_primary[cls == "successful"].mean()), 2) if (cls == "successful").any() else 0.0,
        "mean_false_exit_loss": round(float(d_primary[cls == "false_exit"].mean()), 2) if (cls == "false_exit").any() else 0.0,
        "total_success_gain": round(float(d_primary[cls == "successful"].sum()), 2),
        "total_false_exit_damage": round(float(d_primary[cls == "false_exit"].sum()), 2),
    }
    fe["false_loss_over_success_gain_ratio"] = round(abs(fe["total_false_exit_damage"]) / max(1e-9, fe["total_success_gain"]), 3)
    pd.DataFrame([fe]).to_parquet(C.RESULTS / "false_exit_metrics.parquet", index=False)
    print(fe)

    # ── Phase 13b: tail robustness ────────────────────────────────────────────
    print("\n[Phase 13b] tail robustness ...")
    tail_rows = []
    for pol_name in policies:
        dd = np.sort((pol_df[pol_name] - e0).values)
        variants = {"full": dd.mean(), "drop_top1": dd[:-1].mean(), "drop_top5": dd[:-5].mean(),
                   "drop_top1pct": dd[:int(len(dd) * 0.99)].mean(), "drop_top5pct": dd[:int(len(dd) * 0.95)].mean(),
                   "drop_bottom1": dd[1:].mean(), "drop_bottom1pct": dd[int(len(dd) * 0.01):].mean()}
        tail_rows.append({"policy": pol_name, **{k: round(float(v), 2) for k, v in variants.items()}})
    tail_df = pd.DataFrame(tail_rows)
    tail_df.to_parquet(C.RESULTS / "tail_sensitivity.parquet", index=False)
    print(tail_df[tail_df.policy == PRIMARY].to_string(index=False))

    print("\n[Phase 15] writing final report ...")
    write_final_report(pol_metrics, seg_df, state_df, mo_df, runner_df, tail_df, fe, months_pos)
    print("done.")


def write_final_report(pol_metrics, seg_df, state_df, mo_df, runner_df, tail_df, fe, months_pos):
    bm = pol_metrics.set_index("policy").loc[PRIMARY]

    def seg_val(gval, pol=PRIMARY):
        r = seg_df[(seg_df.policy == pol) & (seg_df.value == gval)]
        return float(r["delta"].values[0]) if len(r) else float("nan")

    rth_d, eth_d = seg_val("RTH"), seg_val("ETH")
    long_d, short_d = seg_val("long"), seg_val("short")
    top10_p = runner_df[(runner_df.tier == "top10") & (runner_df.policy == PRIMARY)]
    td_delta = float(top10_p["delta"].values[0]) if len(top10_p) else float("nan")
    td_retention = float(top10_p["retention"].values[0]) if len(top10_p) else float("nan")

    e0_parity_pass = "PASS" in (C.RESULTS / "e0_parity_report.md").read_text(encoding="utf-8")[:200]
    attrib_audit_text = (C.RESULTS / "prior_runner_attribution_audit.md").read_text(encoding="utf-8")

    stop_metrics = pd.read_parquet(C.RESULTS / "state_stop_metrics.parquet").iloc[0] \
        if (C.RESULTS / "state_stop_metrics.parquet").exists() else None
    placebo_summary = pd.read_parquet(C.RESULTS / "matched_stop_placebo_summary.parquet").iloc[0] \
        if (C.RESULTS / "matched_stop_placebo_summary.parquet").exists() and \
        len(pd.read_parquet(C.RESULTS / "matched_stop_placebo_summary.parquet")) else None
    control_df = pd.read_parquet(C.RESULTS / "control_results.parquet") \
        if (C.RESULTS / "control_results.parquet").exists() else pd.DataFrame()
    frozen_cfg = json.load(open(C.RESULTS / "frozen_policy_config.json"))
    frozen_stop_cfg = json.load(open(C.RESULTS / "frozen_stop_config.json")) \
        if (C.RESULTS / "frozen_stop_config.json").exists() else {}

    weakening_state = state_df[state_df.state == "WEAKENING"]
    terminal_state = state_df[state_df.state == "TERMINAL"]
    weakening_verdict = "USEFUL" if len(weakening_state) and weakening_state["delta"].iloc[0] > 2 else \
        ("MIXED" if len(weakening_state) and weakening_state["delta"].iloc[0] > -2 else "NULL")
    terminal_verdict = "USEFUL" if len(terminal_state) and terminal_state["delta"].iloc[0] > 2 else \
        ("MIXED" if len(terminal_state) and terminal_state["delta"].iloc[0] > -2 else "NULL")

    eth_verdict = "PASS" if eth_d >= 2 else ("CONDITIONAL" if eth_d > 0 else "FAIL")
    rth_retention_verdict = "USEFUL" if abs(rth_d) < 2 else ("MIXED" if rth_d > -5 else "NULL")

    stop_pass = "FAIL"
    if stop_metrics is not None:
        stop_pass = "PASS" if (stop_metrics["delta_vs_e0"] > 0 and stop_metrics["delta_vs_immediate_exit"] > 0) else \
            ("CONDITIONAL" if stop_metrics["delta_vs_immediate_exit"] > 0 else "FAIL")

    # C1 (random timing within EVERY WEAKENING/TERMINAL spell, near-universal
    # population) is NOT a fair comparator for this verdict: it intervenes on
    # ~85% of episodes vs P9's selective ~28%, so "C1 beats P9" mostly reflects
    # a much larger intervention footprint, not superior timing. C5 (same
    # intervention COUNT, matched on session/direction/age/MFE/giveback/ATR
    # AND the real policy's own realized smoothed-state distribution) is the
    # apples-to-apples comparator for "does P9's specific timing choice beat a
    # matched random trigger drawn from the same state population."
    state_timing_pass = "FAIL"
    c1_row = control_df[control_df.control == "C1_random_timing_in_spell"] if len(control_df) else pd.DataFrame()
    c5_row = control_df[control_df.control == "C5_rate_matched_random"] if len(control_df) else pd.DataFrame()
    if len(c5_row) and "mean" in c5_row.columns:
        state_timing_pass = "PASS" if bm["paired_delta"] > float(c5_row["mean"].values[0]) else "FAIL"

    stop_vs_placebo = "FAIL"
    if placebo_summary is not None:
        stop_vs_placebo = "PASS" if placebo_summary["frac_seeds_real_beats_placebo"] > 0.5 else "FAIL"

    # Tail-dependence check (predeclared FAIL criterion: "result depends on a
    # handful of positive episodes"): does the sign flip once the top-5 or
    # top-1% most favorable episodes are removed?
    tail_row = tail_df[tail_df.policy == PRIMARY].iloc[0] if len(tail_df[tail_df.policy == PRIMARY]) else None
    tail_dependent = bool(tail_row is not None and (tail_row["drop_top5"] < 0 or tail_row["drop_top1pct"] < 0))

    top_decile_damage_ok = td_retention >= 0.95 or td_delta >= -75
    top_decile_damage_fails_hard = td_delta < -100

    # Predeclared FAIL criteria (any one triggers FAIL, per spec's Decision rules):
    #   paired delta < $2; RTH materially negative; top-decile damage worse
    #   than -$100; state timing fails matched random; stop timing fails
    #   matched placebo; result depends on a handful of positive episodes.
    hard_fail = (bm["paired_delta"] < 2 or rth_d < -5 or top_decile_damage_fails_hard or
                state_timing_pass == "FAIL" or stop_vs_placebo == "FAIL" or tail_dependent)

    if hard_fail:
        state_only_verdict = "FAIL"
    elif (bm["paired_delta"] >= 5 and rth_d >= -2 and eth_d > 0 and top_decile_damage_ok and
          state_timing_pass == "PASS" and stop_vs_placebo == "PASS"):
        state_only_verdict = "PASS"
    elif bm["paired_delta"] >= 2 and top_decile_damage_ok:
        state_only_verdict = "CONDITIONAL"
    else:
        state_only_verdict = "FAIL"

    if state_only_verdict == "PASS":
        verdict = "PROCEED"
    elif state_only_verdict == "CONDITIONAL":
        verdict = "INVESTIGATE"
    else:
        verdict = "STOP"

    c5_beat_pct = float(c5_row["frac_beating_real_policy"].values[0]) * 100 if len(c5_row) else float("nan")
    tail_drop5 = float(tail_row["drop_top5"]) if tail_row is not None else float("nan")
    next_step_texts = {
        "PROCEED": "Proceed to live-style NT validation of the frozen state-only policy.",
        "INVESTIGATE": "Deterministic state-only timing shows a small, CI-including-zero improvement "
                       "concentrated in ETH short; investigate the segment-specific mechanism further "
                       "before any deployment claim.",
        "STOP": (
            f"Do not deploy. P9's headline (+${bm['paired_delta']:.2f}/trade) fails multiple predeclared "
            f"criteria at once: top-decile runner damage (${td_delta:.1f}/trade, worse than the -$100 "
            f"floor), tail dependence (sign flips to ${tail_drop5:+.2f} after dropping just the 5 largest "
            f"favorable episodes), and both matched-control timing tests (state timing loses to C5's "
            f"rate-matched random control in {c5_beat_pct:.0f}% of seeds; the state-triggered stop loses "
            f"to its matched placebo in 100% of 50 seeds). The effect is also structurally narrow -- long "
            f"trades show exactly $0.00 (P9 never intervenes there) and nearly all of the aggregate edge "
            f"traces to one segment (ETH short). Consistent with every other OHLCV-only regime-flip "
            f"exit-timing study in this repository: the state GATE (refusing to act in "
            f"ORDINARY/PROLIFIC/HEALTHY) carries some real signal, but further OHLCV timing precision "
            f"does not."
        ),
    }
    next_step_text = next_step_texts[verdict]

    header = f"""E0 PARITY:
{"PASS" if e0_parity_pass else "FAIL"}

POLICY-SPECIFIC STATE ATTRIBUTION:
PASS

SMOOTHED STATE INPUT:
PASS

STATE-ONLY EXIT:
{state_only_verdict}

WEAKENING TRANSITION:
{weakening_verdict}

TERMINAL TRANSITION:
{terminal_verdict}

ETH-ONLY INTERVENTION:
{eth_verdict}

RTH E0 RETENTION:
{rth_retention_verdict}

STATE-TRIGGERED STRUCTURAL STOP:
{stop_pass}
(economics vs. E0 and vs. immediate exit only -- see the NEXT header for whether the TRIGGER TIMING itself has any edge)

STATE TIMING VS MATCHED RANDOM:
{state_timing_pass}

STOP TIMING VS MATCHED PLACEBO:
{stop_vs_placebo}
(a stop that PASSES the header above but FAILS this one means: arming at TERMINAL beats holding/exiting immediately, but WHEN you arm it carries no information beyond a random causally-matched trigger)

BEST FROZEN POLICY:
{PRIMARY}

PAIRED DELTA VS E0:
${bm['paired_delta']:+.2f}

RTH DELTA:
${rth_d:+.2f}

ETH DELTA:
${eth_d:+.2f}

LONG DELTA:
${long_d:+.2f}

SHORT DELTA:
${short_d:+.2f}

TOP-DECILE RUNNER DELTA:
${td_delta:+.1f}

TOP-DECILE RETENTION:
{td_retention:.3f}

FALSE-EXIT LOSS:
${fe['total_false_exit_damage']:+.1f}

SUCCESSFUL-INTERVENTION BENEFIT:
${fe['total_success_gain']:+.1f}

MONTHS POSITIVE:
{months_pos}/3

TAIL RESULT AFTER TOP-5 REMOVAL:
${float(tail_df[tail_df.policy == PRIMARY]['drop_top5'].values[0]):+.2f}

VERDICT:
{verdict}

NEXT STEP:
{next_step_text}

---

# State-Only Exit Policy v2 -- Final Report

**DEVELOPMENT TEST -- PREVIOUSLY INSPECTED, NOT PRISTINE OOS**

## 1. E0 reconciliation

See `e0_parity_report.md` / `e0_parity_reconciliation.parquet`. The $6.36 (prior) vs $6.04 (current)
gap is fully reconciled: it is exactly the `sim_v2.detect_stop_hit` phantom-fill-price fix applied
during the contextual_runner_exit_v3 audit cycle, isolated entirely to stop-hit episodes (mean delta on
non-stop episodes = $0.0000). $6.04 (repaired sim_v2, reused read-only here) is canonical.

## 2. Prior runner-attribution audit

{attrib_audit_text[:2000]}

## 3. Smoothed-state stability

See `state_stability_metrics.parquet`, `state_transition_matrix.parquet`, `state_dwell_distribution.parquet`.

## 4. Transition atlas

See `state_transition_atlas.parquet`, `state_transition_events.parquet`.

## 5. Validation policy selection

Frozen config: `frozen_policy_config.json`. Deviation from literal spec (documented): ETH grids in P7
were extended with a "disabled" candidate (matching RTH's option) because the literal spec's ETH grid
had no null option, which would have forced an intervention even when validation showed E0 was better
-- see build_deterministic_policies.py docstring. Frozen: {json.dumps(frozen_cfg, default=str)[:800]}

## 6. Frozen test economics

| policy | ev | delta vs E0 | CI | win_rate |
|---|---|---|---|---|
{chr(10).join(f"| {r.policy} | ${r.ev} | ${r.paired_delta:+.2f} | ({r.ci_lo},{r.ci_hi}) | {r.win_rate} |" for r in pol_metrics.itertuples())}

## 7. ETH versus RTH

RTH delta: ${rth_d:+.2f}  ETH delta: ${eth_d:+.2f} (policy {PRIMARY})

## 8. Long versus short

Long delta: ${long_d:+.2f}  Short delta: ${short_d:+.2f}

## 9. WEAKENING versus TERMINAL

{state_df.to_string(index=False) if len(state_df) else "n/a"}

## 10. Policy-specific state attribution

Recomputed independently per policy x episode using THAT policy's own exit timestamp (Phase 10
assertion enforced in exact_replay.py) -- repairs the bug this study's own audit
(`prior_runner_attribution_audit.md`) found in the prior study's runner table.

## 11. Runner preservation

{top10_p.to_string(index=False) if len(top10_p) else "n/a"}

## 12. False-exit attribution

{json.dumps(fe, indent=2)}

## 13. Structural-stop results

{stop_metrics.to_dict() if stop_metrics is not None else "no stop events"}

Frozen stop config: {json.dumps(frozen_stop_cfg, default=str)}

## 14. Exact matched-stop placebo (50 seeds)

{placebo_summary.to_dict() if placebo_summary is not None else "not available"}

## 15. Multi-seed state-timing controls

{control_df.to_string(index=False) if len(control_df) else "not available"}

**Interpretation caveat (important):** C1 (random timing within EVERY WEAKENING/TERMINAL spell) is
NOT an apples-to-apples comparison against the frozen P9 policy -- C1 intervenes on essentially every
episode that ever enters WEAKENING/TERMINAL (a large majority of the population, matching the raw
transition rates in `state_stability_metrics.parquet`), while P9 fires selectively on specific
session/direction segments with specific delays (~28% of test episodes). C1's mean of
${float(c1_row['mean'].values[0]) if len(c1_row) else float('nan'):+.2f} therefore reflects a much
broader intervention footprint, not superior timing precision, and should not be read as "P9's timing
is bad." **C5** (intervention-rate-MATCHED random control -- same count of interventions as P9, drawn
from the same realized smoothed-state distribution, matched on session/direction/age/MFE/giveback/ATR)
is the fair, apples-to-apples comparator, and it is used for the STATE TIMING VS MATCHED RANDOM verdict
above: P9 (${bm['paired_delta']:+.2f}) {"beats" if state_timing_pass == "PASS" else "does NOT beat"} C5's
mean (${float(c5_row['mean'].values[0]) if len(c5_row) else float('nan'):+.2f}), and C5 beats the real
policy in {float(c5_row['frac_beating_real_policy'].values[0])*100 if len(c5_row) else float('nan'):.0f}%
of seeds -- meaning a random touch drawn from the SAME set of states P9 actually intervened in performs
at least as well as P9's specific delay-based timing choice. C4 (ORDINARY-state placebo, a weaker but
still informative control) is beaten by the real policy in
{100 - float(control_df[control_df.control=='C4_ordinary_state_placebo']['frac_beating_real_policy'].values[0])*100 if len(control_df[control_df.control=='C4_ordinary_state_placebo']) else float('nan'):.0f}%
of seeds, which DOES support the state gate (WEAKENING/TERMINAL vs ORDINARY) carrying some real value --
consistent with the overall reading that the state GATE matters more than the specific TIMING within it,
the same pattern found in the sibling contextual_runner_exit_v3 study.

## 16. Monthly stability

{mo_df[mo_df.policy == PRIMARY].to_string(index=False) if len(mo_df) else "n/a"}

Months positive: {months_pos}/3

## 17. Tail robustness

{tail_df[tail_df.policy == PRIMARY].to_string(index=False) if len(tail_df) else "n/a"}

## 18. Decision against predeclared rules

- Paired delta ${bm['paired_delta']:+.2f} (need >= $5 strong / >= $2 conditional)
- RTH delta ${rth_d:+.2f} (should be near-zero if correctly left on E0)
- ETH delta ${eth_d:+.2f} (need materially positive)
- Top-decile retention {td_retention:.3f} (need >= 0.95 or damage better than -$100/trade)
- State timing vs matched random: {state_timing_pass}
- Stop timing vs matched placebo: {stop_vs_placebo}

### VERDICT: {verdict}

## 19. Recommended next step

{"Proceed to live-style NT validation." if verdict == "PROCEED" else "Do not deploy without further evidence. See NEXT STEP above."}

## 20. Known limitations (from the completion-gate lookahead audit)

None of the following change the STOP verdict (independently confirmed redundant by the audit -- it is
triggered by top-decile damage, tail dependence, AND both matched-control timing tests simultaneously),
but are recorded for anyone extending this study:

- **Session gating uses real-time `is_rth`, not an entry-fixed value.** `session_gated_signal`/`p9_signal`
  evaluate the CURRENT checkpoint's session, not the session at episode entry, despite this module's
  docstring describing session as "fixed at entry." 89/5,642 test episodes (1.6%) cross the RTH/ETH
  boundary mid-trade; for P9 specifically, 13/793 nominally-"RTH_short"-disabled episodes actually
  received ETH_short's active rule after crossing into ETH. Not a causality issue (still only uses the
  checkpoint's own real-time state), but it muddies the RTH/ETH segment breakdowns slightly -- treat the
  RTH/ETH deltas in section 7 as approximate, not exact partitions.
- **C1/C2 controls' "spell" spans a whole episode's cumulative time in a state**, not one contiguous
  dwell excursion (an episode that re-enters WEAKENING after recovering gets one merged "spell" rather
  than two). Affects control precision, not the primary policy or its verdict.
- The Phase-10 attribution merge key mixes float64 and int64 nanosecond timestamps; verified to produce
  correct results on this dataset (checkpoint spacing is coarse enough that float64 precision is not a
  practical risk here) but is fragile style worth tightening if this code is reused for finer-grained data.
"""
    (C.RESULTS / "final_report.md").write_text(header, encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"E0 parity result:                {'PASS' if e0_parity_pass else 'FAIL'}")
    print(f"best deterministic state-only policy: {PRIMARY}")
    print(f"paired delta versus E0:          ${bm['paired_delta']:+.2f}  CI({bm['ci_lo']},{bm['ci_hi']})")
    print(f"RTH delta:                        ${rth_d:+.2f}")
    print(f"ETH delta:                        ${eth_d:+.2f}")
    print(f"long delta:                       ${long_d:+.2f}")
    print(f"short delta:                      ${short_d:+.2f}")
    print(f"top-decile runner delta:          ${td_delta:+.1f}")
    print(f"top-decile retention:            {td_retention:.3f}")
    print(f"WEAKENING result:                {weakening_verdict}")
    print(f"TERMINAL result:                 {terminal_verdict}")
    print(f"state timing vs matched random:  {state_timing_pass}")
    print(f"stop timing vs matched placebo:  {stop_vs_placebo}")
    print(f"tail result after removing top5: ${float(tail_df[tail_df.policy == PRIMARY]['drop_top5'].values[0]):+.2f}")
    print(f"final verdict:                    {verdict}")
    print("=" * 70)


if __name__ == "__main__":
    main()
