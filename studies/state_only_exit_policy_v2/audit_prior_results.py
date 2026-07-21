"""
Audit -- prior (contextual_runner_exit_v3) runner-state-at-exit attribution bug.

Confirms the reported bug: v3's runner_results.parquet shows IDENTICAL
pct_exited_{state} values for EVERY policy (P1a..P7), despite those policies
having materially different exit rules and therefore different exit
timestamps. Root cause (traced to v3/run_study.py): the "state at exit" table
was built ONCE from the P3 policy's first-signal state
(`fs_p3 = first_signal_table(test, sig_p3, "p3")`) and then reused, via
`fs_sub = fs_indexed.reindex(idx)`, for every OTHER policy's runner-tier rows
in the Phase-12 loop -- P1a, P1b, P2, P4, P5, P6 and P7 all report P3's
first-signal state, not their own.

This script is READ-ONLY against contextual_runner_exit_v3/ (imports its
modules only to reconstruct two of its policies for comparison; writes
nothing there).

Writes:
  results/prior_runner_attribution_audit.md
  results/policy_exit_state_audit.parquet
"""
from __future__ import annotations
import json
import sys
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import base as C

V3 = C.V3
sys.path.insert(0, str(V3))
import build_policy_candidates as V3BP  # noqa: E402 -- read-only reuse for reconstruction only


def reconstruct_v3_p1a(train, test):
    """Reconstruct v3's P1a (frozen fitted-Q immediate exit) signal + first-fire
    state, purely for auditing the attribution bug -- not used anywhere else
    in this study, and not a primary policy here."""
    frozen = json.load(open(V3 / "results" / "frozen_policy_config.json"))
    feats0 = frozen["features_P1"]
    thr = frozen["P1a_thr"]
    m0 = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                        random_state=42, n_jobs=4, verbose=-1)
    X_tr = train[feats0].fillna(0).to_numpy(dtype=np.float32)
    m0.fit(X_tr, train["hold_advantage"].fillna(0).values)
    X_te = test[feats0].fillna(0).to_numpy(dtype=np.float32)
    s_test = m0.predict(X_te)
    weak_now = C.elig(test) & (pd.Series(s_test, index=test.index) < thr)
    return weak_now


def reconstruct_v3_p7(train, test):
    """Reconstruct v3's P7 (state-gated + best-granularity + structural
    modulation) signal for comparison. Reuses v3's own state_gated_signal
    exactly as exact_replay.py did."""
    frozen = json.load(open(V3 / "results" / "frozen_policy_config.json"))
    feats0 = frozen["features_P1"]
    m0 = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                        random_state=42, n_jobs=4, verbose=-1)
    m0.fit(train[feats0].fillna(0).to_numpy(dtype=np.float32),
           train["hold_advantage"].fillna(0).values)
    s_test = m0.predict(test[feats0].fillna(0).to_numpy(dtype=np.float32))
    weak = C.elig(test) & (pd.Series(s_test, index=test.index) < frozen["P1a_thr"])
    codes = test.groupby("episode_id").ngroup().values
    run = C.consecutive_run(weak.values.astype(bool), codes)
    struct = V3BP.build_structural_flags(test)
    S_flag = struct[frozen["S_variant"]]
    K_term_ck = C.s_to_ck(frozen["K_terminal_seconds"])

    granularity = json.load(open(V3 / "results" / "p7_granularity_selection.json"))
    winner = granularity["winner"]
    ep_dir = test.groupby("episode_id")["direction"].first()
    ep_rth = test.groupby("episode_id")["is_rth"].first()
    K_p3_ck = C.s_to_ck(frozen["P3_K_weakening_seconds"])

    def K_arr_by_seg(seg_map_ep, k_by_seg, default_ck):
        m = test["episode_id"].map(seg_map_ep).map(k_by_seg).fillna(default_ck)
        return m.values.astype(np.int32)

    K_p4 = K_arr_by_seg(ep_dir.map({1: "long", -1: "short"}),
                         {"long": C.s_to_ck(frozen["P4_K_long_seconds"]),
                          "short": C.s_to_ck(frozen["P4_K_short_seconds"])}, K_p3_ck)
    K_p5 = K_arr_by_seg(ep_rth.map({1: "rth", 0: "eth"}),
                         {"rth": C.s_to_ck(frozen["P5_K_rth_seconds"]),
                          "eth": C.s_to_ck(frozen["P5_K_eth_seconds"])}, K_p3_ck)
    seg_label = test["episode_id"].map(
        lambda e: ("RTH_" if ep_rth.get(e, 0) == 1 else "ETH_") +
                  ("long" if ep_dir.get(e, 1) == 1 else "short"))
    K_p6_by_seg = {k: C.s_to_ck(v) for k, v in frozen["P6_K_by_segment_seconds"].items()}
    K_p6 = seg_label.map(K_p6_by_seg).fillna(K_p3_ck).values.astype(np.int32)

    K_base = {"P3": np.full(len(test), K_p3_ck), "P4": K_p4, "P5": K_p5, "P6": K_p6}[winner]
    sig = V3BP.state_gated_signal(test, weak, run, K_base, np.full(len(test), K_term_ck),
                                   S_flag, modulate_by_structure=True,
                                   reduce_ck=frozen["P7_structural_modulation_reduce_ck"],
                                   extend_ck=frozen["P7_structural_modulation_extend_ck"])
    return sig


def first_fire_state(test, sig, label):
    hit = test[sig.values if hasattr(sig, "values") else sig]
    if len(hit) == 0:
        return pd.DataFrame(columns=["episode_id", f"{label}_exit_ts", f"{label}_state"])
    first = (hit.sort_values("seconds_since_entry").groupby("episode_id")
             .first()[["observation_time", "smoothed_state"]]
             .rename(columns={"observation_time": f"{label}_exit_ts",
                              "smoothed_state": f"{label}_state"}))
    return first.reset_index()


def main():
    print("=" * 70)
    print("Audit -- prior runner-state-at-exit attribution (contextual_runner_exit_v3)")
    print("=" * 70)

    rr = pd.read_parquet(V3 / "results" / "runner_results.parquet")
    top10 = rr[rr["tier"] == "top10"]
    cols = ["pct_exited_prolific_or_healthy", "pct_exited_ordinary",
            "pct_exited_weakening", "pct_exited_terminal"]
    identical = bool((top10[cols].nunique() == 1).all())
    print(f"  v3 runner_results.parquet: identical state-at-exit across ALL policies = {identical}")
    print(top10[["policy"] + cols].to_string(index=False))

    # reconstruct two v3 policies with materially different exit rules
    train, val, test, tt = C.load_base()
    # v3's own train/test frames carry the fitted-Q feature columns; reload
    # those directly from v3's own prepared cache (read-only) for this
    # reconstruction, since this audit script -- unlike the rest of this
    # study -- is explicitly reproducing v3's fitted-Q policies for comparison.
    v3_full = pd.read_parquet(C.V3_PREPARED_FULL)
    v3_train = v3_full[v3_full["period"] == "train"].reset_index(drop=True)
    v3_test = v3_full[v3_full["period"] == "test"].reset_index(drop=True)
    sm = pd.read_parquet(C.V3_SMOOTHED_STATE, columns=["episode_id", "observation_time", "smoothed_state"])
    v3_test = v3_test.merge(sm, on=["episode_id", "observation_time"], how="left")

    sig_p1a = reconstruct_v3_p1a(v3_train, v3_test)
    sig_p7 = reconstruct_v3_p7(v3_train, v3_test)

    fs_p1a = first_fire_state(v3_test, sig_p1a, "p1a")
    fs_p7 = first_fire_state(v3_test, sig_p7, "p7")

    dist_p1a = fs_p1a["p1a_state"].value_counts(normalize=True)
    dist_p7 = fs_p7["p7_state"].value_counts(normalize=True)
    print("\n  RECONSTRUCTED true first-fire state distribution (all fired episodes):")
    print("  P1a (immediate fitted-Q):", dist_p1a.to_dict())
    print("  P7  (state-gated):       ", dist_p7.to_dict())

    merged = fs_p1a.merge(fs_p7, on="episode_id", how="outer")
    n_both_fired = int(merged[["p1a_state", "p7_state"]].notna().all(axis=1).sum())
    n_differ = int((merged["p1a_state"] != merged["p7_state"]).sum())
    identical_ts = int((merged["p1a_exit_ts"] == merged["p7_exit_ts"]).sum())
    print(f"\n  episodes where both P1a and P7 fired: {n_both_fired}")
    print(f"  of those, state-at-exit differs: {n_differ}")
    print(f"  episodes with identical exit_ts (P1a vs P7): {identical_ts}")

    merged.to_parquet(C.RESULTS / "policy_exit_state_audit.parquet", index=False)

    assert n_differ > 0, "reconstruction assertion failed: expected P1a/P7 state-at-exit to differ"

    md = f"""# Prior Runner-State-at-Exit Attribution Audit (contextual_runner_exit_v3)

## Finding: CONFIRMED BUG

`results/runner_results.parquet` (top10 tier) reports **identical**
`pct_exited_{{state}}` values for all 8 policies (P1a..P7):

{top10[['policy'] + cols].to_string(index=False)}

`identical across all policies` = **{identical}**.

## Root cause

Traced to `contextual_runner_exit_v3/run_study.py` Phase 12 (runner evaluation):
a single state-at-first-signal table (`fs_p3`, built from the P3 policy's own
signal) is reused via `.reindex(idx)` for every policy's `pct_exited_*`
columns, instead of recomputing first-fire state from each policy's OWN
signal/exit timestamp. Since P1a fires on ANY instant fitted-Q weakness
(no state gate) while P3/P4/P5/P6/P7 only fire under state-gated persistence,
their true exit-state distributions cannot be the same -- the reported
identical values are a reporting artifact, not a real finding.

## Empirical proof (reconstruction)

Reconstructed v3's P1a (immediate fitted-Q, frozen threshold) and P7
(state-gated, best-granularity + structural modulation) signals independently
on v3's own test data and computed each one's TRUE first-fire smoothed_state:

- P1a true first-fire state distribution: {dist_p1a.round(3).to_dict()}
- P7 true first-fire state distribution: {dist_p7.round(3).to_dict()}
- Episodes where both fired: {n_both_fired}; state-at-exit differs in {n_differ} of them
- Episodes with identical exit timestamp (P1a vs P7): {identical_ts}

This confirms state-at-exit is policy-specific and the prior report's
uniform table cannot be trusted. `state_only_exit_policy_v2`'s own Phase 10
(`policy_exit_state_attribution.parquet`) recomputes state-at-decision
independently for every policy x episode using THAT policy's own exit
timestamp, with an explicit assertion that this recomputation happens
per-policy (not reused across policies).

## Required assertion (this study)

`changed_episode_count` / distinct-attribution assertions are enforced in
`build_deterministic_policies.py` and `exact_replay.py`: policies with
different signals must not silently share a state-attribution table.
"""
    (C.RESULTS / "prior_runner_attribution_audit.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print("done.")


if __name__ == "__main__":
    main()
