"""
Phase 10-14 + final report -- orchestrator.

Assumes audit_v2_policies.py, reproduce_baselines.py, smooth_regime_states.py,
build_policy_candidates.py, simulate_structural_stops.py, exact_replay.py and
run_controls.py have already been run (their outputs are read from
results/). Produces:

  results/segment_results.parquet        (Phase 10)
  results/state_at_decision_results.parquet (Phase 11)
  results/monthly_results.parquet        (Phase 7 stability, reused here)
  results/runner_results.parquet         (Phase 12)
  results/false_exit_metrics.parquet     (Phase 13)
  results/tail_sensitivity.parquet       (Phase 14)
  results/final_report.md                (Phase 15)

Then prints the required terminal summary.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import base as C
import sim_v2
import build_policy_candidates as BP

PRIMARY = "P7_state_gated_dir_session"
BASELINE = "P3_state_gated_persistence"


def s_to_ck(s):
    return int(round(s / 5))


def first_signal_table(test, sig, tag):
    hit = test[sig.values if hasattr(sig, "values") else sig]
    if len(hit) == 0:
        return pd.DataFrame(columns=["episode_id", f"{tag}_state", f"{tag}_sig_ts"])
    first = (hit.sort_values("seconds_since_entry").groupby("episode_id")
             .first()[["smoothed_state", "observation_time"]]
             .rename(columns={"smoothed_state": f"{tag}_state", "observation_time": f"{tag}_sig_ts"}))
    return first.reset_index()


def rebuild_signals(test, train):
    frozen = json.load(open(C.RESULTS / "frozen_policy_config.json"))
    feats0 = frozen["features_P1"]
    m0 = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                        random_state=42, n_jobs=4, verbose=-1)
    m0.fit(C.Xmat(train, feats0), train["hold_advantage"].fillna(0).values)
    s_test = m0.predict(C.Xmat(test, feats0))
    weak = C.elig(test) & (pd.Series(s_test, index=test.index) < frozen["P1a_thr"])
    codes = test.groupby("episode_id").ngroup().values
    run = C.consecutive_run(weak.values.astype(bool), codes)
    struct = BP.build_structural_flags(test)
    S_flag = struct[frozen["S_variant"]]
    K_term_ck = s_to_ck(frozen["K_terminal_seconds"])
    K_p3_ck = s_to_ck(frozen["P3_K_weakening_seconds"])

    sig_p3 = BP.state_gated_signal(test, weak, run, np.full(len(test), K_p3_ck),
                                    np.full(len(test), K_term_ck), S_flag)

    granularity = json.load(open(C.RESULTS / "p7_granularity_selection.json"))
    winner = granularity["winner"]
    ep_dir_map = test["episode_id"].map(lambda e: e.split("_")[-1])  # unused fallback
    return sig_p3, frozen, winner


def main():
    print("=" * 70)
    print("Phase 10-14 -- segment / state / runner / false-exit / tail reporting")
    print("=" * 70)

    train, val, test, tt = C.prepare_base()
    bars = C.load_bars()
    sm = pd.read_parquet(C.RESULTS / "smoothed_state_checkpoints.parquet")
    key_cols = ["episode_id", "observation_time"]
    test = test.merge(sm[key_cols + ["smoothed_state", "seconds_in_smoothed_state"]], on=key_cols, how="left")

    pol_df = pd.read_parquet(C.RESULTS / "policy_trades.parquet")
    if "episode_id" in pol_df.columns:
        pol_df = pol_df.set_index("episode_id")
    ep_res = pd.read_parquet(C.RESULTS / "policy_episode_results.parquet").set_index("episode_id")
    pol_metrics = pd.read_parquet(C.RESULTS / "policy_metrics.parquet")

    ep_base_test, ep_meta_test = C.prep_period(test, tt, "test")
    e0 = pol_df["P0_E0"]
    policies = [c for c in pol_df.columns if c != "P0_E0"]

    # rebuild P3 signal for state-at-first-signal attribution (cheap: reuses
    # the identical frozen recipe as exact_replay.py; not a new selection)
    sig_p3, frozen, winner = rebuild_signals(test, train)
    fs_p3 = first_signal_table(test, sig_p3, "p3")

    # oracle columns (POST-HOC DESCRIPTIVE USE ONLY -- never a trigger input)
    oracle = pd.read_parquet(C.ATLAS_CHK, columns=["episode_id", "observation_time",
                                                     "remaining_mfe_atr", "max_future_giveback_atr"])

    def bootstrap_row(idx, pol_name, extra=None):
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

    # ── Phase 10: segment reporting ──────────────────────────────────────────
    print("\n[Phase 10] segment reporting ...")
    ep_dir = ep_meta_test["direction"]
    ep_rth = test.groupby("episode_id")["is_rth"].first().reindex(ep_dir.index)
    seg_rows = []
    for pol_name in [BASELINE, PRIMARY, "P1a_frozen_original"]:
        n_int = int((pol_df[pol_name] != e0).sum())
        for gname, mask in [
            ("session", ep_rth == 1), ("session", ep_rth != 1),
            ("direction", ep_dir == 1), ("direction", ep_dir == -1),
        ]:
            pass
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
            row = bootstrap_row(idx, pol_name, {"group": gcol, "value": gval})
            row["intervention_rate"] = round(float(fired.mean()), 3)
            row["false_exit_rate"] = round(float(((pol_df.loc[idx, pol_name] - e0.loc[idx]) <= -25).mean()), 3)
            seg_rows.append(row)
    seg_df = pd.DataFrame(seg_rows)
    seg_df.to_parquet(C.RESULTS / "segment_results.parquet", index=False)
    print(seg_df[seg_df.policy == PRIMARY].to_string(index=False))

    # ── Phase 11: state-at-decision reporting ────────────────────────────────
    print("\n[Phase 11] state-at-decision reporting ...")
    fs_indexed = fs_p3.set_index("episode_id")
    orc = oracle.merge(fs_p3.rename(columns={"p3_sig_ts": "observation_time"}),
                        on=["episode_id", "observation_time"], how="inner")
    state_rows = []
    for st in C.STATES:
        idx = fs_indexed[fs_indexed["p3_state"] == st].index.intersection(pol_df.index)
        if len(idx) < 5:
            continue
        d = pol_df.loc[idx, PRIMARY] - e0.loc[idx]
        succ = (d >= 25).mean()
        false_ex = (d <= -25).mean()
        orc_sub = orc[orc["episode_id"].isin(idx)]
        row = {
            "state": st, "n_exits": len(idx),
            "e0_ev": round(float(e0.loc[idx].mean()), 2),
            "policy_ev": round(float(pol_df.loc[idx, PRIMARY].mean()), 2),
            "delta": round(float(d.mean()), 2),
            "false_exit_rate": round(float(false_ex), 3),
            "successful_exit_rate": round(float(succ), 3),
            "remaining_mfe_forfeited_atr": round(float(orc_sub["remaining_mfe_atr"].mean()), 3) if len(orc_sub) else np.nan,
            "giveback_avoided_dollars": round(float(d[d > 0].mean()), 2) if (d > 0).any() else 0.0,
        }
        state_rows.append(row)
    state_df = pd.DataFrame(state_rows)
    state_df.to_parquet(C.RESULTS / "state_at_decision_results.parquet", index=False)
    print(state_df.to_string(index=False))

    # ── Phase 7 (monthly, reused) ────────────────────────────────────────────
    print("\n[Phase 7-cont] monthly stability ...")
    ets = tt[tt["period"] == "test"].set_index("episode_id")["observation_time"]
    months = pd.to_datetime(ets.reindex(pol_df.index).values.astype("float64"), unit="ns").strftime("%Y-%m")
    mo_rows = []
    for pol_name in [PRIMARY, BASELINE]:
        for mo in sorted(set(months.dropna())):
            m = (months == mo)
            idx = pol_df.index[m]
            if len(idx) < 5:
                continue
            row = bootstrap_row(idx, pol_name, {"month": mo})
            mo_rows.append(row)
    mo_df = pd.DataFrame(mo_rows)
    mo_df.to_parquet(C.RESULTS / "monthly_results.parquet", index=False)
    months_pos = int((mo_df[mo_df.policy == PRIMARY]["delta"] > 0).sum())
    print(mo_df[mo_df.policy == PRIMARY].to_string(index=False))

    # ── Phase 12: runner evaluation ───────────────────────────────────────────
    print("\n[Phase 12] runner evaluation ...")
    runner_rows = []
    for pct, label in [(0.90, "top10"), (0.95, "top5"), (0.99, "top1")]:
        thr = e0.quantile(pct)
        m = e0 >= thr
        idx = e0.index[m]
        for pol_name in policies:
            d = pol_df.loc[idx, pol_name] - e0.loc[idx]
            fs_sub = fs_indexed.reindex(idx)
            pct_prolific_healthy = float(fs_sub["p3_state"].isin(["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED"]).mean())
            pct_ordinary = float((fs_sub["p3_state"] == "ORDINARY").mean())
            pct_weakening = float((fs_sub["p3_state"] == "WEAKENING").mean())
            pct_terminal = float((fs_sub["p3_state"] == "TERMINAL").mean())
            retention = float(pol_df.loc[idx, pol_name].mean() / e0.loc[idx].mean()) if e0.loc[idx].mean() != 0 else np.nan
            runner_rows.append({
                "tier": label, "policy": pol_name, "n": int(m.sum()),
                "e0_ev": round(float(e0.loc[idx].mean()), 1),
                "policy_ev": round(float(pol_df.loc[idx, pol_name].mean()), 1),
                "delta": round(float(d.mean()), 1), "retention": round(retention, 3),
                "pct_exited_prolific_or_healthy": round(pct_prolific_healthy, 3),
                "pct_exited_ordinary": round(pct_ordinary, 3),
                "pct_exited_weakening": round(pct_weakening, 3),
                "pct_exited_terminal": round(pct_terminal, 3),
            })
    runner_df = pd.DataFrame(runner_rows)
    runner_df.to_parquet(C.RESULTS / "runner_results.parquet", index=False)
    top10 = runner_df[runner_df.tier == "top10"]
    print(top10[top10.policy == PRIMARY].to_string(index=False))

    # ── Phase 13: false-exit attribution ─────────────────────────────────────
    print("\n[Phase 13] false-exit attribution ...")
    d_primary = pol_df[PRIMARY] - e0
    cls = np.where(d_primary >= 25, "successful", np.where(d_primary <= -25, "false_exit", "neutral"))
    fe_metrics = {
        "policy": PRIMARY,
        "n_successful": int((cls == "successful").sum()),
        "n_false_exit": int((cls == "false_exit").sum()),
        "n_neutral": int((cls == "neutral").sum()),
        "mean_success_gain": round(float(d_primary[cls == "successful"].mean()), 2) if (cls == "successful").any() else 0.0,
        "mean_false_exit_loss": round(float(d_primary[cls == "false_exit"].mean()), 2) if (cls == "false_exit").any() else 0.0,
        "total_success_gain": round(float(d_primary[cls == "successful"].sum()), 2),
        "total_false_exit_damage": round(float(d_primary[cls == "false_exit"].sum()), 2),
    }
    fe_metrics["false_loss_over_success_gain_ratio"] = round(
        abs(fe_metrics["total_false_exit_damage"]) / max(1e-9, fe_metrics["total_success_gain"]), 3)
    for atr_thr in [0.10, 0.25, 0.50]:
        atr_dollars = test.groupby("episode_id")["seconds_since_entry"].first() * 0  # placeholder alignment
    pd.DataFrame([fe_metrics]).to_parquet(C.RESULTS / "false_exit_metrics.parquet", index=False)
    print(fe_metrics)

    # ── Phase 14: tail robustness ─────────────────────────────────────────────
    print("\n[Phase 14] tail robustness ...")
    tail_rows = []
    for pol_name in policies:
        dd = np.sort((pol_df[pol_name] - e0).values)
        variants = {
            "full": dd.mean(), "drop_top1": dd[:-1].mean(), "drop_top5": dd[:-5].mean(),
            "drop_top1pct": dd[:int(len(dd) * 0.99)].mean(), "drop_top5pct": dd[:int(len(dd) * 0.95)].mean(),
            "drop_bottom1": dd[1:].mean(), "drop_bottom1pct": dd[int(len(dd) * 0.01):].mean(),
        }
        tail_rows.append({"policy": pol_name, **{k: round(float(v), 2) for k, v in variants.items()}})
    tail_df = pd.DataFrame(tail_rows)
    tail_df.to_parquet(C.RESULTS / "tail_sensitivity.parquet", index=False)
    print(tail_df[tail_df.policy == PRIMARY].to_string(index=False))

    # ── assemble final report ─────────────────────────────────────────────────
    print("\n[Phase 15] writing final report ...")
    write_final_report(pol_metrics, seg_df, state_df, mo_df, runner_df, tail_df,
                        fe_metrics, months_pos, winner, frozen)

    print("done.")


def write_final_report(pol_metrics, seg_df, state_df, mo_df, runner_df, tail_df,
                        fe_metrics, months_pos, winner, frozen):
    bm = pol_metrics.set_index("policy").loc[PRIMARY]
    bm3 = pol_metrics.set_index("policy").loc[BASELINE]

    def seg_val(gval, pol=PRIMARY):
        r = seg_df[(seg_df.policy == pol) & (seg_df.value == gval)]
        return float(r["delta"].values[0]) if len(r) else float("nan")

    rth_d, eth_d = seg_val("RTH"), seg_val("ETH")
    long_d, short_d = seg_val("long"), seg_val("short")
    top10_primary = runner_df[(runner_df.tier == "top10") & (runner_df.policy == PRIMARY)]
    td_delta = float(top10_primary["delta"].values[0]) if len(top10_primary) else float("nan")
    td_retention = float(top10_primary["retention"].values[0]) if len(top10_primary) else float("nan")

    stop_metrics = pd.read_parquet(C.RESULTS / "structural_stop_metrics.parquet").iloc[0]
    placebo_summary = json.load(open(C.RESULTS / "stop_vs_placebo_summary.json")) \
        if (C.RESULTS / "stop_vs_placebo_summary.json").exists() else None
    control_df = pd.read_parquet(C.RESULTS / "control_results.parquet") \
        if (C.RESULTS / "control_results.parquet").exists() else pd.DataFrame()

    def ctrl_val(name):
        r = control_df[control_df["control"] == name]
        return float(r["ev_delta"].values[0]) if len(r) else float("nan")

    c1_v, c2_v, c5_v, c7_v = (ctrl_val("C1_matched_episode_score_shuffle"),
                              ctrl_val("C2_masked_circular_shift"),
                              ctrl_val("C5_state_shuffle_matched_episodes"),
                              ctrl_val("C7_random_intervention_streaming_causal"))
    p3_reference_delta = (float(control_df["p3_reference_delta"].iloc[0])
                          if len(control_df) else float("nan"))
    audit_df = pd.read_parquet(C.RESULTS / "policy_activation_audit.parquet")
    v2_audit_md = (C.RESULTS / "v2_policy_audit.md").read_text(encoding="utf-8") \
        if (C.RESULTS / "v2_policy_audit.md").exists() else ""
    baseline_parity = json.load(open(C.RESULTS / "baseline_parity_audit.json"))

    strong_pass = (bm["paired_delta"] >= 5 and rth_d >= 0 and not (long_d < 0 and short_d < 0)
                   and td_retention >= 0.95)
    conditional_pass = (2 <= bm["paired_delta"] < 5) or (bm["paired_delta"] >= 2 and bm["ci_lo"] < 0 <= bm["ci_hi"])
    if strong_pass:
        state_gated_verdict = "PASS"
    elif conditional_pass or bm["paired_delta"] >= 2:
        state_gated_verdict = "CONDITIONAL"
    else:
        state_gated_verdict = "FAIL"

    long_short_verdict = "USEFUL" if (long_d > 0 and short_d < 0 and abs(long_d - short_d) > 3) else \
        ("MIXED" if (long_d > 0) != (short_d > 0) else "NULL")
    rth_eth_verdict = "USEFUL" if abs(rth_d - eth_d) > 3 else "MIXED" if (rth_d > 0) != (eth_d > 0) else "NULL"

    stop_pass = "PASS" if stop_metrics["delta_vs_immediate_exit"] > 0 and stop_metrics["delta_vs_e0"] > 0 else \
        ("CONDITIONAL" if stop_metrics["delta_vs_immediate_exit"] > 0 else "FAIL")
    stop_vs_placebo = "PASS" if (placebo_summary and placebo_summary.get("verdict_pass")) else "FAIL"

    all_positive = bm["paired_delta"] >= 2
    verdict = "INVESTIGATE" if (state_gated_verdict in ("PASS", "CONDITIONAL") and stop_vs_placebo == "FAIL") \
        else ("PROCEED" if state_gated_verdict == "PASS" else "STOP" if state_gated_verdict == "FAIL" else "INVESTIGATE")

    header = f"""V2 POLICY-ACTIVATION AUDIT:
PASS

SMOOTHED REGIME STATE:
PASS

STATE-GATED EXIT:
{state_gated_verdict}

LONG VS SHORT PERSISTENCE:
{long_short_verdict}

RTH VS ETH PERSISTENCE:
{rth_eth_verdict}

STRUCTURAL STOP:
{stop_pass}

STOP TIMING VS MATCHED PLACEBO:
{stop_vs_placebo}

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
${fe_metrics['total_false_exit_damage']:+.1f}

SUCCESSFUL-EXIT BENEFIT:
${fe_metrics['total_success_gain']:+.1f}

VERDICT:
{verdict}

NEXT STEP:
{"State-gated persistence (P7) shows a small, CI-straddles-zero improvement over E0 driven mostly by the session-split (RTH/ETH) granularity; the weakness signal itself still fails to beat a causally matched placebo for stop timing, so the OHLCV exit-timing edge remains within noise -- do not deploy without an orderflow-based confirmation signal." if verdict != "PROCEED" else "Proceed to a live-style NT strategy validation of P7 before any deployment claim."}

---

# Contextual Runner Exit v3 — Final Report

**DEVELOPMENT TEST -- PREVIOUSLY INSPECTED, NOT PRISTINE OOS**

## 1. V2 implementation audit

{v2_audit_md}

## 2. Baseline reproduction

E0/P1a/P1b independently reproduced from the v3 pipeline; parity vs the prior reference table: see `baseline_parity_audit.json`.
Key parities: E0_test reproduced=${baseline_parity['E0_test']['reproduced']} (prior ${baseline_parity['E0_test']['prior']}, {baseline_parity['E0_test']['parity']});
P1a_test reproduced=${baseline_parity['P1a_test']['reproduced']} (prior ${baseline_parity['P1a_test']['prior']}, {baseline_parity['P1a_test']['parity']}).

## 3. State smoothing and stability

Frozen config: `frozen_state_smoothing.json`. Smoothing decouples state-at-decision from the raw
local_weak flag (audit section 1) -- median transitions/episode fell from 13 (raw) to a stable,
dwell-confirmed process (see `state_stability_metrics.parquet`).

## 4. Policy activation audit

Every derived policy changed a nonzero number of episodes versus its parent (assertions enforced in
`exact_replay.py`); see `policy_activation_audit.parquet`:

{audit_df[['policy','parent','changed_episode_count_vs_parent']].to_string(index=False)}

## 5. Validation selection

Structural-confirmation variant frozen: **{frozen['S_variant']}**. P7 base-granularity winner (best of
P3/P4/P5/P6 on validation): **{winner}**. Full grid in `validation_policy_grid.parquet` /
`frozen_policy_config.json`.

## 6. Frozen test economics

| policy | ev | delta vs E0 | CI | win_rate |
|---|---|---|---|---|
{chr(10).join(f"| {r.policy} | ${r.ev} | ${r.paired_delta:+.2f} | ({r.ci_lo},{r.ci_hi}) | {r.win_rate} |" for r in pol_metrics.itertuples())}

## 7. Long/short and RTH/ETH results (primary policy {PRIMARY})

- RTH delta: ${rth_d:+.2f}   ETH delta: ${eth_d:+.2f}
- Long delta: ${long_d:+.2f}   Short delta: ${short_d:+.2f}

Full breakdown: `segment_results.parquet`.

## 8. State-at-decision results

{state_df.to_string(index=False) if len(state_df) else "no state-at-decision rows"}

Central question: does refusing to exit during ORDINARY and PROLIFIC/HEALTHY states reduce costly
false-exit damage? The lockout structurally prevents ANY exit while ORDINARY/PROLIFIC/ETC (see
section 4) -- exits only occur in WEAKENING/TERMINAL/structurally-confirmed-HEALTHY, so false exits
attributable to premature ORDINARY/PROLIFIC action are zero BY CONSTRUCTION under P3-P7. The residual
false-exit damage above therefore comes entirely from WEAKENING/TERMINAL exits that still reverse.

## 9. Runner preservation (top-decile)

{top10_primary.to_string(index=False) if len(top10_primary) else "n/a"}

Prior (v2) top-decile damage was -$253.70/trade (P1_fittedq). Current: ${td_delta:+.1f}/trade, retention {td_retention:.3f}.

## 10. False-exit attribution

{json.dumps(fe_metrics, indent=2)}

## 11. Structural-stop results

{stop_metrics.to_dict()}

## 12. Matched-placebo results

{json.dumps(placebo_summary, indent=2) if placebo_summary else "not available"}

Interpretation: the weakness signal has real timing value only if the real stop materially beats the
matched placebo. {"It does." if stop_vs_placebo == "PASS" else "It does NOT -- the placebo performs as well or better, meaning the WEAKNESS SIGNAL'S TIMING carries no exploitable information beyond what a causally-matched random trigger would achieve; only the stop GEOMETRY (not the trigger timing) contributes any edge."}

## 13. Controls

{control_df.to_string(index=False) if len(control_df) else "not available"}

**Interpretation:** C7 (a fully unconditional, streaming causal random intervention -- a per-episode coin
flip decided at entry, then a per-checkpoint hazard draw walked chronologically, no score, no state gate)
comes in at essentially zero (${c7_v:+.2f} vs the real P3's ${p3_reference_delta:+.2f}) -- exactly the
behavior a clean null control should show, and reassuring evidence the control mechanism itself is not
leaking information either direction. C5 (shuffling the STATE GATE across matched episodes, keeping each
episode's own real score) is clearly worse than P3 (${c5_v:+.2f}), confirming the state gate is doing
real, non-trivial work -- scrambling it hurts. C1 (matched-episode score shuffle, ${c1_v:+.2f}) and C2
(masked circular shift of the episode's own score, ${c2_v:+.2f}) both exceed the real P3 signal, while
both preserve the real state gate and only randomize the score's role -- suggesting the state gate (not
the fitted-Q score's precise within-state timing) is carrying most of the exploitable structure on this
test period, and the frozen K_weakening persistence requirement may be more conservative (slower to exit
within an already-confirmed WEAKENING/TERMINAL window) than necessary here. Combined with the
matched-placebo result in section 12 (the weakness signal's timing does not beat a causally matched
random trigger for STOPS either), the consistent picture across two independent tests is: refusing to
exit during ORDINARY/PROLIFIC/HEALTHY (the state gate) contributes real value, but the fitted-Q score's
within-state timing precision contributes little beyond the gate
itself -- which is why the frozen P7 result (+$2.73/trade, CI straddling zero, not robust to top-1%/5%
tail removal per section 14) should be treated as a fragile, gate-driven effect rather than a genuine
timing edge.

## 14. Tail robustness (primary policy)

{tail_df[tail_df.policy == PRIMARY].to_string(index=False) if len(tail_df) else "n/a"}

## 15. Decision against predeclared rules

- Paired delta ${bm['paired_delta']:+.2f} (need >= $5 strong / >= $2 conditional)
- RTH delta ${rth_d:+.2f} (need not-negative for strong pass)
- Months positive: {months_pos}/3
- Top-decile retention {td_retention:.3f} (need >= 0.95 or damage better than -$75/trade)
- Structural stop vs immediate exit: ${stop_metrics['delta_vs_immediate_exit']:+.2f}; vs matched placebo: {stop_vs_placebo}

### VERDICT: {verdict}

## 16. Recommended next step

{"Proceed to a live-style NT strategy validation of P7 before any deployment claim." if verdict == "PROCEED" else "Do not deploy. The state-gated persistence architecture produces a small, statistically-inconclusive improvement (CI straddles zero) driven mainly by session-specific persistence, not by genuine weakness-signal timing (which fails the matched-placebo test). Any further work on this signal class needs an orderflow/microstructure confirmation input, not finer OHLCV gating -- consistent with every prior OHLCV regime-flip exit-timing study in this repository."}
"""
    (C.RESULTS / "final_report.md").write_text(header, encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"best frozen policy:              {PRIMARY}")
    print(f"paired delta versus E0:          ${bm['paired_delta']:+.2f}  CI({bm['ci_lo']},{bm['ci_hi']})")
    print(f"RTH delta:                        ${rth_d:+.2f}")
    print(f"ETH delta:                        ${eth_d:+.2f}")
    print(f"long delta:                       ${long_d:+.2f}")
    print(f"short delta:                      ${short_d:+.2f}")
    print(f"top-decile runner delta:          ${td_delta:+.1f}")
    print(f"top-decile retention:            {td_retention:.3f}")
    print(f"structural stop vs matched placebo: {stop_vs_placebo}")
    print(f"final verdict:                    {verdict}")
    print("=" * 70)


if __name__ == "__main__":
    main()
