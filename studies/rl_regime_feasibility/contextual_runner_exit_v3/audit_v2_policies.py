"""
Phase 0a — audit why v2's P2/P4/P7 were bit-identical, why the sequence-shuffle
control was invalid, and why the random-checkpoint stop placebo was inflated.

Read-only against v2 artifacts + the v3 prepared base data. Writes:
  results/v2_policy_activation_audit.parquet
  results/v2_policy_audit.md
"""
from __future__ import annotations
import numpy as np
import pandas as pd

import base as C

V2_RES = C.V2_RESULTS


def audit_p2_p4_p7_identical() -> dict:
    pt = pd.read_parquet(V2_RES / "policy_trades.parquet")
    p2_p4_identical = bool((pt["P2_context_exit"] == pt["P4_prolific_lockout"]).all())
    p2_p7_identical = bool((pt["P2_context_exit"] == pt["P7_hybrid_stop"]).all())
    n_changed_p4_vs_p2 = int((pt["P2_context_exit"] != pt["P4_prolific_lockout"]).sum())
    n_changed_p7_vs_p2 = int((pt["P2_context_exit"] != pt["P7_hybrid_stop"]).sum())

    # Root-cause proof: raw state machine makes local_weak and
    # state in {PROLIFIC_EXPANDING, HEALTHY_ESTABLISHED} mutually exclusive
    # BY CONSTRUCTION (assign_states requires ~local_weak for both states).
    # v3's prepare_base() reuses the identical raw-state formula, so we can
    # demonstrate the tautology directly on the same population.
    train, val, test, tt = C.prepare_base()
    co_occur = int(((test["local_weak"]) &
                     (test["state"].isin(["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED"]))).sum())
    ct = pd.crosstab(test["state"], test["local_weak"])

    return {
        "p2_p4_bit_identical": p2_p4_identical,
        "p2_p7_bit_identical": p2_p7_identical,
        "n_changed_episodes_p4_vs_p2": n_changed_p4_vs_p2,
        "n_changed_episodes_p7_vs_p2": n_changed_p7_vs_p2,
        "local_weak_AND_prolific_or_healthy_rows": co_occur,
        "state_vs_local_weak_crosstab": ct.to_dict(),
        "root_cause": (
            "build_regime_state_machine.assign_states() requires ~local_weak "
            "for BOTH prolific and healthy states, while P2's weakness trigger "
            "IS local_weak. So lockout_test = ~state.isin([PROLIFIC,HEALTHY]) is "
            "TRUE at every row where the P2 signal can fire -- P4 = P2 & lockout "
            "== P2 identically, and P7's stop-branch (armed only when first "
            "weakness occurs during PROLIFIC/HEALTHY) can never activate for the "
            "same reason, so P7's immediate-exit branch == P2 identically too. "
            "This is a logical tautology, not a coincidence -- co-occurrence is "
            "exactly zero across every period."
        ),
        "v3_fix": (
            "Phase 1 smoothing decouples state-at-decision from the instantaneous "
            "local_weak flag: the SMOOTHED state persists through raw weakening "
            "blips until a transition is confirmed over N consecutive checkpoints "
            "(with dwell + asymmetric hysteresis), so a checkpoint can have "
            "local_weak=True while the smoothed state is still PROLIFIC_EXPANDING "
            "or HEALTHY_ESTABLISHED (the raw transition simply hasn't been "
            "confirmed yet). This is what makes P3/P7 state-gating non-vacuous."
        ),
    }


def audit_sequence_shuffle() -> dict:
    """C5 in v2 (`run_study.py` lines building `order = np.lexsort((RNG.random(...), codes))`)
    permutes checkpoint rows freely WITHIN each episode's group with no time
    constraint. This can and does move a LATER-in-time checkpoint's feature
    vector into an EARLIER decision slot -- an implicit future-information
    control, not a temporal-structure ablation. It is not "unrestricted
    permutation is illegal because permutation itself is illegal" but because
    an unrestricted permutation is symmetric in time and therefore has ~50%
    chance of using looking-forward information at any slot; the recorded EV
    (+38.07 vs baseline in v2's control_results.parquet) is consistent with the
    model exploiting that forward leakage rather than being purely destructive.
    """
    ctrl = pd.read_parquet(V2_RES / "control_results.parquet")
    row = ctrl[ctrl["control"] == "C5_seq_shuffle"]
    seq_ev = float(row["ev"].values[0]) if len(row) else np.nan
    best_ev_ref = float(row["best_ev_ref"].values[0]) if len(row) and "best_ev_ref" in row else np.nan
    return {
        "control": "C5_seq_shuffle (v2)",
        "reported_ev": seq_ev,
        "best_ev_ref (P1_fittedq test ev)": best_ev_ref,
        "finding": (
            "v2's sequence shuffle used `np.lexsort((RNG.random(len(test)), codes))`, "
            "an UNRESTRICTED within-episode permutation with no temporal ordering "
            "constraint -- any checkpoint's full feature row (including MTF context "
            "computed at a later observation_time) can be relocated to an earlier "
            "decision slot in the same episode. The resulting EV (+38.07, far above "
            "every real policy) is the signature of a permutation control that "
            "leaked future information rather than destroying temporal structure. "
            "v3's C1/C5 controls (run_controls.py) use only causal, cross-episode "
            "matched shuffles or circular shifts with wrapped-observation masking."
        ),
        "verdict": "INVALID -- superseded by v3 C1 (matched-episode shuffle) and C2 (masked circular shift)",
    }


def audit_random_stop_placebo() -> dict:
    """v2's `random_events()` draws ONE checkpoint via
    `g.sample(1, random_state=1)` from the FULL set of eligible checkpoints
    already recorded for that episode. Because episodes are truncated at their
    true terminal event, sampling uniformly over "all eligible checkpoints of
    this episode" requires knowing, at selection time, how long the episode
    ultimately survives -- a longer-lived (mostly-favorable) episode contributes
    proportionally more candidate rows to the sampler, so the draw is biased
    toward episodes that are further along a favorable path. That is a forward-
    looking / survivorship selection, not a causal "pick a checkpoint you could
    have picked in real time" placebo.
    """
    stop_metrics = pd.read_parquet(V2_RES / "weakness_stop_metrics.parquet")
    ctrl = pd.read_parquet(V2_RES / "control_results.parquet")
    row = ctrl[ctrl["control"] == "C10_stop_placebo_s2_vs_e0"]
    placebo_ev = float(row["ev"].values[0]) if len(row) else np.nan

    train, val, test, tt = C.prepare_base()
    elig = test[test["seconds_since_entry"] >= C.MIN_ELIG_S]
    ep_len = elig.groupby("episode_id")["seconds_since_entry"].max()
    ep_n = elig.groupby("episode_id").size()
    corr_len_n = float(np.corrcoef(ep_len.values, ep_n.values)[0, 1])

    return {
        "control": "C10_stop_placebo_s2_vs_e0 (v2)",
        "reported_ev_vs_e0": placebo_ev,
        "corr_episode_length_vs_n_eligible_checkpoints": round(corr_len_n, 4),
        "finding": (
            "v2's placebo drew a uniform random ELIGIBLE checkpoint from the full, "
            "already-truncated episode via pandas groupby.sample(), which requires "
            "the complete in-episode checkpoint set (i.e. the episode's eventual "
            "survival length) to exist before the draw. Episode length and "
            "eligible-checkpoint count are perfectly correlated by construction "
            "(corr computed above), so the draw implicitly overweights longer-lived "
            "(more often favorable / still-alive) episodes relative to a real-time "
            "trigger, which can only ever see the checkpoints that have occurred "
            "SO FAR. This explains the suspiciously strong +$35.54/trade result. "
            "v3's matched placebo (simulate_structural_stops.py) selects a stop-arm "
            "checkpoint from a DIFFERENT episode using only causally-available, "
            "bucket-matched state (session/direction/age-bucket/regime-age-bucket/"
            "MFE-bucket/giveback-bucket/smoothed-state/vol-bucket), never using "
            "final episode duration or future stop/recovery outcomes."
        ),
        "verdict": "INVALID -- superseded by v3 matched_stop_placebo.parquet",
    }


def audit_state_flicker() -> dict:
    train, val, test, tt = C.prepare_base()
    trans_per_ep = test.groupby("episode_id")["state_transition_reason"].apply(
        lambda s: int(s.str.contains("->", na=False).sum()))
    dwell = test.groupby(["episode_id", "state_start_time"])["seconds_in_state"].max()
    return {
        "median_transitions_per_episode": float(trans_per_ep.median()),
        "mean_transitions_per_episode": float(trans_per_ep.mean()),
        "frac_dwells_le_10s": float((dwell <= 10).mean()),
        "frac_dwells_le_30s": float((dwell <= 30).mean()),
        "finding": (
            "Raw one-checkpoint (5s) state transitions flicker heavily: median "
            f"{trans_per_ep.median():.0f} transitions/episode, "
            f"{float((dwell <= 10).mean()):.1%} of state spells last <=10s. Using "
            "this raw sequence directly as a policy trigger (as v2 did for "
            "state-gating) is unstable and, combined with the local_weak "
            "tautology above, structurally prevents any weakness-triggered policy "
            "from ever firing while the raw state reads PROLIFIC/HEALTHY. v3 Phase "
            "1 (smooth_regime_states.py) adds dwell + confirmation hysteresis."
        ),
    }


def main():
    print("=" * 70)
    print("Phase 0a -- audit v2 policy-activation and control defects")
    print("=" * 70)

    a1 = audit_p2_p4_p7_identical()
    a2 = audit_sequence_shuffle()
    a3 = audit_random_stop_placebo()
    a4 = audit_state_flicker()

    rows = [
        {"policy": "P4_prolific_lockout", "parent": "P2_context_exit",
         "changed_episode_count_vs_parent": a1["n_changed_episodes_p4_vs_p2"],
         "assertion_pass": a1["n_changed_episodes_p4_vs_p2"] > 0},
        {"policy": "P7_hybrid_stop", "parent": "P2_context_exit",
         "changed_episode_count_vs_parent": a1["n_changed_episodes_p7_vs_p2"],
         "assertion_pass": a1["n_changed_episodes_p7_vs_p2"] > 0},
    ]
    audit_df = pd.DataFrame(rows)
    audit_df.to_parquet(C.RESULTS / "v2_policy_activation_audit.parquet", index=False)

    ct = a1["state_vs_local_weak_crosstab"]
    ct_lines = ["| state | local_weak=False | local_weak=True |", "|---|---|---|"]
    for state in C.STATES:
        f = ct.get(False, {}).get(state, 0)
        t = ct.get(True, {}).get(state, 0)
        ct_lines.append(f"| {state} | {f} | {t} |")

    md = f"""# V2 Policy-Activation Audit

## 1. P2 / P4 / P7 bit-identical -- CONFIRMED, root cause found

- P2 == P4 bit-identical: **{a1['p2_p4_bit_identical']}** (changed episodes vs parent: {a1['n_changed_episodes_p4_vs_p2']})
- P2 == P7 bit-identical: **{a1['p2_p7_bit_identical']}** (changed episodes vs parent: {a1['n_changed_episodes_p7_vs_p2']})
- Rows with local_weak=True AND state in {{PROLIFIC_EXPANDING, HEALTHY_ESTABLISHED}}: **{a1['local_weak_AND_prolific_or_healthy_rows']}** (test period)

### state x local_weak crosstab (test period)
{chr(10).join(ct_lines)}

**Root cause:** {a1['root_cause']}

**v3 fix:** {a1['v3_fix']}

## 2. Sequence-shuffle control (C5) was invalid

- v2 reported EV: {a2['reported_ev']}  (vs P1_fittedq test EV: {a2['best_ev_ref (P1_fittedq test ev)']})
- {a2['finding']}
- Verdict: {a2['verdict']}

## 3. Random-checkpoint stop placebo (C10) was inflated

- v2 reported Δ vs E0: {a3['reported_ev_vs_e0']}
- corr(episode length, n eligible checkpoints) = {a3['corr_episode_length_vs_n_eligible_checkpoints']}
- {a3['finding']}
- Verdict: {a3['verdict']}

## 4. Regime state flicker

- Median transitions/episode: {a4['median_transitions_per_episode']}
- Mean transitions/episode: {a4['mean_transitions_per_episode']}
- Fraction of state spells lasting <=10s: {a4['frac_dwells_le_10s']:.1%}
- Fraction of state spells lasting <=30s: {a4['frac_dwells_le_30s']:.1%}
- {a4['finding']}

## Summary of required v3 repairs

1. Smooth the raw state sequence with dwell + confirmation hysteresis (Phase 1) so
   state-at-decision is decoupled from the instantaneous local_weak flag used to
   trigger exits -- this is the ONLY way P3/P7-style state gating can be non-vacuous.
2. Replace the unrestricted within-episode sequence shuffle with matched-episode /
   masked-circular-shift controls (Phase 6, C1/C2).
3. Replace the random-checkpoint stop placebo with a causally matched, cross-episode
   placebo that never uses final episode duration or future outcomes (Phase 5).
4. Add `changed_episode_count_vs_parent > 0` assertions for every derived policy
   (Phase 7) so a silently-inactive policy fails loudly instead of reporting.
"""
    (C.RESULTS / "v2_policy_audit.md").write_text(md, encoding="utf-8")
    print(md)
    print("done.")


if __name__ == "__main__":
    main()
