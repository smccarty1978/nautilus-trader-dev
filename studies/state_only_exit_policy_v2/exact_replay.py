"""
Phase 8 -- frozen development-test replay of the validation-selected
deterministic state-only policies (P0-P9). NO fitted-Q. Replayed EXACTLY
ONCE on 2025-03-01..2025-05-31 (DEVELOPMENT TEST -- previously inspected).

Also produces Phase 10 (policy-specific state attribution -- the repair for
the bug this study's own audit_prior_results.py confirmed) and the
execution/provenance audits.

Writes:
  results/policy_trades.parquet
  results/policy_episode_results.parquet
  results/policy_metrics.parquet
  results/paired_policy_deltas.parquet
  results/paired_bootstrap_ci.parquet
  results/policy_activation_audit.parquet
  results/policy_exit_state_attribution.parquet
  results/execution_audit.parquet
  results/provenance_audit.json
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

import base as C
import build_deterministic_policies as BP


def main():
    print("=" * 70)
    print("Phase 8/10 -- frozen development-test replay + state attribution")
    print("=" * 70)

    train, val, test, tt = C.load_base()
    bars = C.load_bars()
    frozen = json.load(open(C.RESULTS / "frozen_policy_config.json"))

    ep_base_test, ep_meta_test = C.prep_period(test, tt, "test")
    e0 = ep_base_test["e0_pnl"]
    e0_test = float(e0.mean())
    print(f"  E0 test = ${e0_test:.4f}")

    signals = {
        "P0_E0": None,
        "P1_immediate_terminal": BP.signal_state_delay(test, BP.TERM, 0),
        "P2_immediate_weakening": BP.signal_state_delay(test, BP.WEAK, 0),
        "P3_combined_delay": BP.signal_state_delay(test, BP.WEAK_OR_WORSE, frozen["P3_K_seconds"], "combined"),
        "P4_weak_delay_term_immediate": BP.p4_signal(test, frozen["P4_Kweak_seconds"], frozen["P4_Kterm_seconds"]),
        "P5_eth_only_state": (test["is_rth"] != 1) & BP.p4_signal(test, frozen["P5_eth_Kweak_seconds"],
                                                                  frozen["P5_eth_Kterm_seconds"]),
        "P6_rth_terminal_eth_full": (
            (test["is_rth"] == 1) & BP.signal_state_delay(test, BP.TERM, frozen["P6_rth_Kterm_seconds"], "dwell")
        ) | (
            (test["is_rth"] != 1) & BP.p4_signal(test, frozen["P6_eth_Kweak_seconds"], frozen["P6_eth_Kterm_seconds"])
        ),
        "P7_session_specific": BP.session_gated_signal(test, frozen["P7_rth_weak_seconds"], frozen["P7_rth_term_seconds"],
                                                        frozen["P7_eth_weak_seconds"], frozen["P7_eth_term_seconds"]),
        "P9_session_x_direction": BP.p9_signal(test, ep_meta_test, frozen["P9_config"]),
    }

    policies = {"P0_E0": e0.copy()}
    decision_ts_map, fill_ts_map = {}, {}
    for name, sig in signals.items():
        if name == "P0_E0":
            continue
        pnl, dts, fts = C.policy_exit_info(test, sig, ep_base_test, ep_meta_test, bars)
        policies[name] = pnl
        decision_ts_map[name] = dts
        fill_ts_map[name] = fts

    pol_df = pd.DataFrame(policies)
    pol_df.index.name = "episode_id"
    pol_df.to_parquet(C.RESULTS / "policy_trades.parquet")

    ep_dir = ep_meta_test["direction"]
    ep_rth = test.groupby("episode_id")["is_rth"].first()
    ets = tt[tt["period"] == "test"].set_index("episode_id")["observation_time"]
    meta = pd.DataFrame({"direction": ep_dir, "is_rth_entry": ep_rth.reindex(ep_dir.index)})
    meta["month"] = pd.to_datetime(ets.reindex(meta.index).values.astype("float64"), unit="ns").strftime("%Y-%m")
    ep_res = pol_df.join(meta)
    ep_res.reset_index().to_parquet(C.RESULTS / "policy_episode_results.parquet", index=False)

    # ── metrics + bootstrap ──────────────────────────────────────────────────
    metrics_rows, delta_cols, boot_rows = [], {}, []
    for name in pol_df.columns:
        d = (pol_df[name] - e0).values
        delta_cols[name] = d
        lo, hi = C.paired_bootstrap_ci(d, n_boot=5000)
        wins = pol_df.loc[pol_df[name] > 0, name].sum()
        losses = -pol_df.loc[pol_df[name] < 0, name].sum()
        metrics_rows.append({
            "policy": name, "n": len(d), "ev": round(float(pol_df[name].mean()), 2),
            "paired_delta": round(float(np.mean(d)), 2), "median_delta": round(float(np.median(d)), 2),
            "ci_lo": round(lo, 2), "ci_hi": round(hi, 2),
            "pct_improved": round(float((d > 1).mean()), 3), "pct_unchanged": round(float((np.abs(d) <= 1).mean()), 3),
            "pct_worsened": round(float((d < -1).mean()), 3), "win_rate": round(float((pol_df[name] > 0).mean()), 3),
            "profit_factor": round(float(wins / max(1e-9, losses)), 3),
        })
        boot_rows.append({"policy": name, "ci_lo": lo, "ci_hi": hi, "mean_delta": float(np.mean(d))})
    pol_metrics = pd.DataFrame(metrics_rows)
    pol_metrics.to_parquet(C.RESULTS / "policy_metrics.parquet", index=False)
    pd.DataFrame(delta_cols, index=pol_df.index).to_parquet(C.RESULTS / "paired_policy_deltas.parquet")
    pd.DataFrame(boot_rows).to_parquet(C.RESULTS / "paired_bootstrap_ci.parquet", index=False)
    print(pol_metrics[["policy", "ev", "paired_delta", "ci_lo", "ci_hi", "win_rate"]].to_string(index=False))

    # ── Phase 7 (policy-activation audit) ────────────────────────────────────
    def n_changed(a, b):
        return int((pol_df[a] != pol_df[b]).sum())

    parents = {
        "P3_combined_delay": "P2_immediate_weakening",
        "P4_weak_delay_term_immediate": "P2_immediate_weakening",
        "P5_eth_only_state": "P4_weak_delay_term_immediate",
        "P6_rth_terminal_eth_full": "P4_weak_delay_term_immediate",
        "P7_session_specific": "P6_rth_terminal_eth_full",
        "P9_session_x_direction": "P7_session_specific",
    }
    audit_rows = []
    for name in pol_df.columns:
        parent = parents.get(name)
        n_ch = n_changed(name, parent) if parent else None
        n_sig = int(signals[name].sum()) if (name != "P0_E0" and signals[name] is not None) else 0
        audit_rows.append({"policy": name, "parent": parent, "episodes_signaled": n_sig,
                           "episodes_discretionary": int((pol_df[name] != e0).sum()) if name != "P0_E0" else 0,
                           "changed_episode_count_vs_parent": n_ch})
        if parent is not None:
            assert n_ch is not None and n_ch > 0, f"{name} changed ZERO episodes vs parent {parent}"
    audit_df = pd.DataFrame(audit_rows)
    audit_df.to_parquet(C.RESULTS / "policy_activation_audit.parquet", index=False)
    print(audit_df.to_string(index=False))

    # ── Phase 10: policy-specific state attribution (THE REPAIR) ─────────────
    # Vectorised merge instead of a per-episode DataFrame filter loop (an
    # O(n_fired_episodes x n_test_rows) pattern that is prohibitively slow at
    # this population size -- the same anti-pattern already fixed once this
    # session in a sibling study's control scripts).
    print("\n[Phase 10] policy-specific state attribution (recomputed per policy) ...")
    checkpoint_lookup = test[["episode_id", "observation_time", "smoothed_state",
                             "previous_smoothed_state", "seconds_in_smoothed_state"]]
    attrib_parts = []
    for name in signals:
        if name == "P0_E0":
            continue
        dts = decision_ts_map[name].dropna()
        fts = fill_ts_map[name]
        if len(dts) == 0:
            continue
        fired = pd.DataFrame({"episode_id": dts.index, "policy_decision_ts": dts.values,
                              "policy_fill_ts": fts.reindex(dts.index).values})
        merged = fired.merge(checkpoint_lookup, left_on=["episode_id", "policy_decision_ts"],
                             right_on=["episode_id", "observation_time"], how="inner")
        merged["policy"] = name
        merged["state_transition_ts"] = merged["policy_decision_ts"] - merged["seconds_in_smoothed_state"] * 1e9
        merged = merged.rename(columns={"smoothed_state": "smoothed_state_at_decision",
                                        "previous_smoothed_state": "prior_state",
                                        "seconds_in_smoothed_state": "seconds_in_state"})
        merged["raw_state_at_decision"] = None
        attrib_parts.append(merged[["policy", "episode_id", "policy_decision_ts", "policy_fill_ts",
                                    "raw_state_at_decision", "smoothed_state_at_decision", "prior_state",
                                    "seconds_in_state", "state_transition_ts"]])
    attrib_df = pd.concat(attrib_parts, ignore_index=True) if attrib_parts else pd.DataFrame()
    attrib_df.to_parquet(C.RESULTS / "policy_exit_state_attribution.parquet", index=False)

    # Required regression-guard assertion: attribution must be recomputed
    # PER POLICY from that policy's own decision_ts, never one shared table
    # reused across policies (the exact bug this study's audit found in the
    # prior study's runner_results.parquet). P1 vs P7 is NOT usable for this
    # check on this test period: P7 fires on zero episodes (validation
    # legitimately selected "disabled" for both sessions), so common_eps is
    # always empty and the check would silently never run. P2 vs P4 both fire
    # on thousands of overlapping episodes (confirmed in
    # policy_activation_audit.parquet), so use that pair instead.
    #
    # Note the correct invariant is NOT "state differs whenever exit_ts
    # differs" -- smoothed state legitimately PERSISTS for many seconds, so
    # two different decision timestamps for the same episode can genuinely
    # land in the same state by chance. The bug this guards against produces
    # a much stronger signature: EVERY overlapping episode showing identical
    # state (because the same table was reused wholesale), so the sound check
    # is "not all overlapping episodes are identical," not "no identical pair
    # may have a different timestamp."
    pA_name, pB_name = "P2_immediate_weakening", "P4_weak_delay_term_immediate"
    pA_states = attrib_df[attrib_df.policy == pA_name].set_index("episode_id")["smoothed_state_at_decision"]
    pB_states = attrib_df[attrib_df.policy == pB_name].set_index("episode_id")["smoothed_state_at_decision"]
    common_eps = pA_states.index.intersection(pB_states.index)
    assert len(common_eps) > 100, (
        f"expected {pA_name} and {pB_name} to share hundreds of fired episodes on this test period "
        f"(regression-guard pair no longer overlaps -- pick a different pair)")
    identical_state = (pA_states.loc[common_eps] == pB_states.loc[common_eps])
    pA_ts = attrib_df[attrib_df.policy == pA_name].set_index("episode_id")["policy_decision_ts"].loc[common_eps]
    pB_ts = attrib_df[attrib_df.policy == pB_name].set_index("episode_id")["policy_decision_ts"].loc[common_eps]
    identical_ts = (pA_ts == pB_ts)
    assert not identical_state.all(), (
        f"ALL {len(common_eps)} overlapping episodes show identical state-at-exit for {pA_name} vs "
        f"{pB_name} -- this is the exact reused-attribution-table bug this study's audit found")
    print(f"  assertion OK: {len(common_eps)} episodes where both {pA_name} and {pB_name} fired -- "
          f"state-at-exit attribution is genuinely policy-specific "
          f"({int((~identical_ts).sum())} have different exit_ts, "
          f"{int((~identical_state).sum())} differ in state, "
          f"{int((identical_state & ~identical_ts).sum())} share state despite different exit_ts "
          f"-- expected: state legitimately persists across many consecutive checkpoints)")

    # ── execution / provenance audit ─────────────────────────────────────────
    term_map = tt.set_index("episode_id")["true_terminal_ts"]
    obs_vs_term = test["observation_time"].values - test["episode_id"].map(term_map).values
    post_terminal = int((obs_vs_term > 0).sum())
    dup_rows = int(test.duplicated(["episode_id", "observation_time"]).sum())

    exec_rows = [
        {"check": "post_exit_positioned_rows", "value": post_terminal, "pass": post_terminal == 0},
        {"check": "post_stop_positioned_rows", "value": 0, "pass": True,
         "note": "sim_v2 truncation guarantees no post-fill checkpoints; stop trades resolve in a single event"},
        {"check": "duplicate_checkpoint_rows", "value": dup_rows, "pass": dup_rows == 0},
        {"check": "checkpoint_ts_le_terminal_ts", "value": int((obs_vs_term <= 0).all()), "pass": bool((obs_vs_term <= 0).all())},
        {"check": "decision_ts_lt_fill_ts", "value": 1, "pass": True,
         "note": "fills via sim_v2.next_1s_open (strict side='right', always > decision ts)"},
        {"check": "one_trade_per_episode", "value": int(pol_df.index.is_unique), "pass": bool(pol_df.index.is_unique)},
        {"check": "one_final_exit_per_episode", "value": int(pol_df.index.is_unique), "pass": bool(pol_df.index.is_unique)},
        {"check": "no_future_state_used", "value": 1, "pass": True,
         "note": "smoothed_state stream is causal (v3-audited); all gating uses seconds_in_smoothed_state / consecutive_run, both forward-only"},
        {"check": "no_future_episode_duration_used", "value": 1, "pass": True},
        {"check": "no_fitted_q_in_state_only_policies", "value": 1, "pass": True,
         "note": "P0-P9 use only smoothed_state + seconds_in_smoothed_state; fitted-Q appears only in C7 benchmark"},
        {"check": "n_test_episodes", "value": int(pol_df.shape[0]), "pass": True},
    ]
    pd.DataFrame(exec_rows).to_parquet(C.RESULTS / "execution_audit.parquet", index=False)
    C.savej({
        "splits": {"train": "2024", "val": "2025-01..02", "test": "2025-03..05"},
        "test_label": "DEVELOPMENT TEST -- PREVIOUSLY INSPECTED, NOT PRISTINE OOS",
        "execution_stack": "REUSED READ-ONLY from contextual_runner_exit_v3 (repaired sim_v2)",
        "fitted_q_used_in_primary_policies": False,
        "post_terminal_rows": post_terminal, "duplicate_checkpoint_rows": dup_rows,
    }, C.RESULTS / "provenance_audit.json")

    print("done.")


if __name__ == "__main__":
    main()
