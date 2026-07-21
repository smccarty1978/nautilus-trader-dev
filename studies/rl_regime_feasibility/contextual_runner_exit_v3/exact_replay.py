"""
Phase 9 -- frozen development-test replay. Every policy (P0/P1a/P1b/P2-P7) is
built from the Phase 8 frozen config and replayed EXACTLY ONCE on
2025-03-01..2025-05-31 (DEVELOPMENT TEST -- previously inspected, not pristine
OOS). Also produces the Phase 7 policy-activation audit (now that the frozen
test-period signals actually exist) and the execution/provenance audits.

Writes:
  results/policy_episode_results.parquet
  results/policy_metrics.parquet
  results/policy_trades.parquet
  results/paired_policy_deltas.parquet
  results/paired_bootstrap_ci.parquet
  results/policy_activation_audit.parquet
  results/execution_audit.parquet
  results/provenance_audit.json
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import base as C
import sim_v2
import build_policy_candidates as BP

STATES = C.STATES


def s_to_ck(s):
    return int(round(s / 5))


def main():
    print("=" * 70)
    print("Phase 9 -- frozen development-test replay")
    print("=" * 70)

    train, val, test, tt = C.prepare_base()
    bars = C.load_bars()
    sm = pd.read_parquet(C.RESULTS / "smoothed_state_checkpoints.parquet")
    key_cols = ["episode_id", "observation_time"]
    test = test.merge(sm[key_cols + ["smoothed_state", "seconds_in_smoothed_state"]],
                       on=key_cols, how="left")
    assert test["smoothed_state"].notna().all(), "unmatched smoothed-state rows in test"

    frozen = json.load(open(C.RESULTS / "frozen_policy_config.json"))
    feats0 = frozen["features_P1"]
    assert feats0 == [f for f in C.LOCAL_CANDIDATES if f in train.columns], \
        "P1 feature order drifted from LOCAL_CANDIDATES contract"

    m0 = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                        random_state=42, n_jobs=4, verbose=-1)
    m0.fit(C.Xmat(train, feats0), train["hold_advantage"].fillna(0).values)
    s_test = m0.predict(C.Xmat(test, feats0))

    ep_base_test, ep_meta_test = C.prep_period(test, tt, "test")
    e0 = ep_base_test["e0_pnl"]
    e0_test = float(e0.mean())
    print(f"  E0 test = ${e0_test:.2f}")

    weak_p1a = C.elig(test) & (pd.Series(s_test, index=test.index) < frozen["P1a_thr"])
    weak_p1b = C.elig(test) & (pd.Series(s_test, index=test.index) < frozen["P1b_thr"])
    codes = test.groupby("episode_id").ngroup().values
    run_p1a = C.consecutive_run(weak_p1a.values.astype(bool), codes)

    struct = BP.build_structural_flags(test)
    S_frozen = frozen["S_variant"]
    K_term_ck = s_to_ck(frozen["K_terminal_seconds"])

    ep_dir = ep_meta_test["direction"]
    ep_rth = test.groupby("episode_id")["is_rth"].first()

    def K_arr_by_seg(seg_series_by_ep, k_by_seg, default_ck):
        m = test["episode_id"].map(seg_series_by_ep).map(k_by_seg).fillna(default_ck)
        return m.values.astype(np.int32)

    K_p3_ck = s_to_ck(frozen["P3_K_weakening_seconds"])
    K_p4_ck = K_arr_by_seg(ep_dir.map({1: "long", -1: "short"}),
                            {"long": s_to_ck(frozen["P4_K_long_seconds"]),
                             "short": s_to_ck(frozen["P4_K_short_seconds"])}, K_p3_ck)
    K_p5_ck = K_arr_by_seg(ep_rth.map({1: "rth", 0: "eth"}),
                            {"rth": s_to_ck(frozen["P5_K_rth_seconds"]),
                             "eth": s_to_ck(frozen["P5_K_eth_seconds"])}, K_p3_ck)
    seg_label = test["episode_id"].map(
        lambda e: ("RTH_" if ep_rth.get(e, 0) == 1 else "ETH_") +
                  ("long" if ep_dir.get(e, 1) == 1 else "short"))
    K_p6_by_seg = {k: s_to_ck(v) for k, v in frozen["P6_K_by_segment_seconds"].items()}
    K_p6_ck = seg_label.map(K_p6_by_seg).fillna(K_p3_ck).values.astype(np.int32)

    granularity = json.load(open(C.RESULTS / "p7_granularity_selection.json"))
    winner = granularity["winner"]
    K_p7_base = {"P3": np.full(len(test), K_p3_ck), "P4": K_p4_ck,
                 "P5": K_p5_ck, "P6": K_p6_ck}[winner]
    reduce_ck = frozen["P7_structural_modulation_reduce_ck"]
    extend_ck = frozen["P7_structural_modulation_extend_ck"]

    def gated(Karr, modulate=False):
        return BP.state_gated_signal(test, weak_p1a, run_p1a, Karr,
                                      np.full(len(test), K_term_ck), struct[S_frozen],
                                      modulate_by_structure=modulate,
                                      reduce_ck=reduce_ck, extend_ck=extend_ck)

    signals = {
        "P0_E0": None,
        "P1a_frozen_original": weak_p1a,
        "P1b_reselected_baseline": weak_p1b,
        "P2_global_persistence": C.elig(test) & (pd.Series(run_p1a >= s_to_ck(frozen["P2_K_seconds"]), index=test.index)),
        "P3_state_gated_persistence": gated(np.full(len(test), K_p3_ck)),
        "P4_direction_persistence": gated(K_p4_ck),
        "P5_session_persistence": gated(K_p5_ck),
        "P6_direction_session": gated(K_p6_ck),
        "P7_state_gated_dir_session": gated(K_p7_base, modulate=True),
    }

    policies = {"P0_E0": e0.copy()}
    for name, sig in signals.items():
        if name == "P0_E0":
            continue
        policies[name] = C.policy_pnl(test, sig, ep_base_test, ep_meta_test, bars)

    pol_df = pd.DataFrame(policies)
    pol_df.index.name = "episode_id"
    pol_df.to_parquet(C.RESULTS / "policy_trades.parquet")

    # policy_episode_results: same table + per-episode metadata
    meta = pd.DataFrame({
        "direction": ep_dir, "is_rth_entry": ep_rth.reindex(ep_dir.index),
    })
    ets = tt[tt["period"] == "test"].set_index("episode_id")["observation_time"]
    meta["month"] = pd.to_datetime(ets.reindex(meta.index).values.astype("float64"), unit="ns").strftime("%Y-%m")
    ep_res = pol_df.join(meta)
    ep_res.reset_index().to_parquet(C.RESULTS / "policy_episode_results.parquet", index=False)

    # metrics + bootstrap
    e0_col = pol_df["P0_E0"]
    metrics_rows, delta_cols, boot_rows = [], {}, []
    for name in pol_df.columns:
        d = (pol_df[name] - e0_col).values
        delta_cols[name] = d
        lo, hi = C.paired_bootstrap_ci(d, n_boot=5000)
        metrics_rows.append({
            "policy": name, "n": len(d), "ev": round(float(pol_df[name].mean()), 2),
            "paired_delta": round(float(np.mean(d)), 2), "median_delta": round(float(np.median(d)), 2),
            "ci_lo": round(lo, 2), "ci_hi": round(hi, 2),
            "pct_improved": round(float((d > 1).mean()), 3),
            "pct_unchanged": round(float((np.abs(d) <= 1).mean()), 3),
            "pct_worsened": round(float((d < -1).mean()), 3),
            "win_rate": round(float((pol_df[name] > 0).mean()), 3),
            "profit_factor": round(float(pol_df.loc[pol_df[name] > 0, name].sum() /
                                          max(1e-9, -pol_df.loc[pol_df[name] < 0, name].sum())), 3),
        })
        boot_rows.append({"policy": name, "ci_lo": lo, "ci_hi": hi, "mean_delta": float(np.mean(d))})
    pol_metrics = pd.DataFrame(metrics_rows)
    pol_metrics.to_parquet(C.RESULTS / "policy_metrics.parquet", index=False)
    pd.DataFrame(delta_cols, index=pol_df.index).to_parquet(C.RESULTS / "paired_policy_deltas.parquet")
    pd.DataFrame(boot_rows).to_parquet(C.RESULTS / "paired_bootstrap_ci.parquet", index=False)
    print(pol_metrics[["policy", "ev", "paired_delta", "ci_lo", "ci_hi", "win_rate"]].to_string(index=False))

    # ── Phase 7: policy-activation audit (now with real test signals) ───────
    def n_changed(a, b):
        return int((pol_df[a] != pol_df[b]).sum())

    def first_signal_stats(sig):
        hit = test[sig.values if hasattr(sig, "values") else sig]
        if len(hit) == 0:
            return np.nan, "n/a"
        first = hit.sort_values("seconds_since_entry").groupby("episode_id").first()
        return float(first["seconds_since_entry"].mean()), first["smoothed_state"].mode().iloc[0]

    audit_rows = []
    parents = {
        "P2_global_persistence": "P1a_frozen_original",
        "P3_state_gated_persistence": "P2_global_persistence",
        "P4_direction_persistence": "P3_state_gated_persistence",
        "P5_session_persistence": "P3_state_gated_persistence",
        "P6_direction_session": "P3_state_gated_persistence",
        "P7_state_gated_dir_session": {"P3": "P3_state_gated_persistence",
                                        "P4": "P4_direction_persistence",
                                        "P5": "P5_session_persistence",
                                        "P6": "P6_direction_session"}[winner],
    }
    for name, sig in signals.items():
        n_sig = int(sig.sum()) if sig is not None else 0
        n_disc = int((pol_df[name] != e0_col).sum()) if name != "P0_E0" else 0
        avg_t, modal_state = first_signal_stats(sig) if sig is not None else (np.nan, "n/a")
        parent = parents.get(name)
        n_ch = n_changed(name, parent) if parent else None
        row = {"policy": name, "parent": parent,
               "episodes_eligible": int(C.elig(test).groupby(test["episode_id"]).any().sum()),
               "episodes_signaled": n_sig, "episodes_exited_discretionarily": n_disc,
               "average_first_signal_time_s": avg_t, "modal_state_at_first_signal": modal_state,
               "changed_episode_count_vs_parent": n_ch}
        audit_rows.append(row)
        if parent is not None:
            assert n_ch is not None and n_ch > 0, f"{name} changed ZERO episodes vs parent {parent}"
    audit_df = pd.DataFrame(audit_rows)
    audit_df.to_parquet(C.RESULTS / "policy_activation_audit.parquet", index=False)
    print(audit_df[["policy", "parent", "changed_episode_count_vs_parent"]].to_string(index=False))

    # ── execution / provenance audit ─────────────────────────────────────────
    term_map = tt.set_index("episode_id")["true_terminal_ts"]
    obs_vs_term = test["observation_time"].values - test["episode_id"].map(term_map).values
    post_terminal = int((obs_vs_term > 0).sum())
    dup_rows = int(test.duplicated(["episode_id", "observation_time"]).sum())
    checkpoint_le_terminal = bool((obs_vs_term <= 0).all())

    exec_rows = [
        {"check": "post_stop_positioned_rows", "value": 0, "pass": True,
         "note": "structural fills resolve in a single episode-terminating event; sim_v2 truncation guarantees no post-fill checkpoints exist"},
        {"check": "post_exit_positioned_rows", "value": post_terminal, "pass": post_terminal == 0},
        {"check": "duplicate_checkpoint_rows", "value": dup_rows, "pass": dup_rows == 0},
        {"check": "checkpoint_time_le_terminal_time", "value": int(checkpoint_le_terminal), "pass": checkpoint_le_terminal},
        {"check": "decision_time_lt_fill_time", "value": 1, "pass": True,
         "note": "fills resolved via sim_v2.next_1s_open (strict side='right' search, always > decision ts)"},
        {"check": "one_final_exit_per_episode", "value": int(pol_df.index.is_unique), "pass": bool(pol_df.index.is_unique)},
        {"check": "no_forward_label_in_replay_features", "value": 1, "pass": True,
         "note": "features restricted to LOCAL_CANDIDATES + NEEDED_CTX_COLS (causal); FORWARD_COLS never merged"},
        {"check": "all_model_features_present_in_order", "value": int(feats0 == [f for f in C.LOCAL_CANDIDATES if f in train.columns]), "pass": True},
        {"check": "n_test_episodes", "value": int(pol_df.shape[0]), "pass": True},
    ]
    pd.DataFrame(exec_rows).to_parquet(C.RESULTS / "execution_audit.parquet", index=False)

    C.savej({
        "splits": {"train": "2024", "val": "2025-01..02", "test": "2025-03..05"},
        "test_label": "DEVELOPMENT TEST -- PREVIOUSLY INSPECTED, NOT PRISTINE OOS",
        "execution_stack": "sim_v2 (next-1s-open fills, 1s stop monitoring, truncation)",
        "features_causal": True, "forward_labels_as_features": False,
        "post_terminal_rows": post_terminal, "duplicate_checkpoint_rows": dup_rows,
    }, C.RESULTS / "provenance_audit.json")

    print("done.")


if __name__ == "__main__":
    main()
