"""
Phase 7 -- matched state-timing controls (C1-C7), NO fitted-Q in any
primary/control policy except C7 (explicit benchmark-only reference).
Every stochastic control is repeated across >=50 independent seeds; single
realizations are never reported as evidence.

Reference policy: the frozen P9 session x direction deterministic policy
(build_deterministic_policies.frozen_policy_config.json). NOTE: P7
(session-only) is NOT used as the reference here -- validation legitimately
selected "disabled" for both RTH and ETH under P7, so it fires on ZERO test
episodes; P9 (which adopted a direction split because validation showed it
clearly improved over session-only) is the one policy that actually
intervenes, so it is the only sensible subject for these timing controls.

Writes:
  results/control_results.parquet
  results/control_seed_distribution.parquet
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import base as C
import build_deterministic_policies as BP
import simulate_state_stops as SS

N_SEEDS = 50


def p9_signal(df, ep_meta, frozen):
    return BP.p9_signal(df, ep_meta, frozen["P9_config"])


def ev_delta(df, sig, ep_base, ep_meta, bars, e0_mean):
    pnl = C.policy_pnl(df, sig, ep_base, ep_meta, bars)
    return float(pnl.mean()) - e0_mean


def seed_summary(vals: np.ndarray, ref_delta: float) -> dict:
    v = np.asarray(vals, dtype=np.float64)
    v = v[~np.isnan(v)]
    return {
        "mean": float(v.mean()), "median": float(np.median(v)), "std": float(v.std()),
        "p5": float(np.percentile(v, 5)), "p25": float(np.percentile(v, 25)),
        "p75": float(np.percentile(v, 75)), "p95": float(np.percentile(v, 95)),
        "frac_beating_real_policy": float((v > ref_delta).mean()),
        "n_seeds": len(v),
    }


# ── C1: random timing within same state spell ──────────────────────────────
def c1_random_in_spell(test, ep_base, ep_meta, bars, e0_mean, target_states, seed):
    rng = np.random.default_rng(seed)
    df = test.sort_values(["episode_id", "seconds_since_entry"])
    in_target = df["smoothed_state"].isin(target_states).values
    ep_codes = df.groupby("episode_id").ngroup().values
    row_idx = df.index.values
    n = len(df)

    chosen = []
    i = 0
    while i < n:
        j = i
        while j < n and ep_codes[j] == ep_codes[i]:
            j += 1
        spell_mask = in_target[i:j]
        if spell_mask.any():
            candidates = np.where(spell_mask)[0]
            # a random checkpoint WITHIN the spell, never before state entry
            # (candidates already restricted to in_target rows); pick any one
            pick = candidates[rng.integers(0, len(candidates))]
            chosen.append(row_idx[i:j][pick])
        i = j

    sig = pd.Series(False, index=test.index)
    sig.loc[chosen] = True
    sig = sig & C.elig(test)
    return ev_delta(test, sig, ep_base, ep_meta, bars, e0_mean)


# ── C2: matched cross-episode transition timing ─────────────────────────────
def c2_matched_cross_episode_timing(test, ep_base, ep_meta, bars, e0_mean, target_states,
                                    edges, seed):
    """For each real-transition episode, use a MATCHED donor's elapsed time
    since state entry to decide the firing offset, applied to the target's
    OWN spell (capped at the target's spell end -- never fires after the
    target has already left that state).

    Vectorised via precomputed per-episode row-position groups (a single
    groupby pass) instead of a per-event `df[df.episode_id==ep]` filter --
    that pattern re-scans the full ~620K-row test frame on every (event,
    seed) pair and is prohibitively slow at this population size (the same
    anti-pattern already fixed twice elsewhere this session)."""
    rng = np.random.default_rng(seed)
    df = test.sort_values(["episode_id", "seconds_since_entry"])  # KEEP original index labels
    ep_row_pos = df.groupby("episode_id", sort=False).indices  # episode_id -> positional array (time-ordered)
    obs_arr = df["observation_time"].values.astype(np.int64)
    state_arr = df["smoothed_state"].values

    events = df[df["transition_confirmed"] & df["smoothed_state"].isin(target_states)]
    if len(events) == 0:
        return np.nan
    first = events.groupby("episode_id").first().reset_index()
    first_obs = first["observation_time"].values.astype(np.int64)
    first_ep = first["episode_id"].values

    bkt = SS.add_match_buckets(df, edges)
    bkt["episode_id"] = df["episode_id"].values

    ev_bkt = SS.add_match_buckets(first, edges)  # row order == `first` row order (positional)
    ev_bkt["episode_id"] = first_ep

    key_cols = ["session", "direction", "smoothed_state", "age_bucket", "regime_age_bucket",
               "mfe_bucket", "giveback_bucket", "atr_bucket"]
    pool_groups = bkt.groupby(key_cols).groups

    chosen = []
    for i in range(len(ev_bkt)):
        row = ev_bkt.iloc[i]
        key = tuple(row[k] for k in key_cols)
        idx = pool_groups.get(key, pd.Index([]))
        idx = idx[bkt.loc[idx, "episode_id"] != first_ep[i]] if len(idx) else idx
        if len(idx) == 0:
            continue
        donor_row_pos = idx[rng.integers(0, len(idx))]
        donor_elapsed = df.loc[donor_row_pos, "seconds_in_smoothed_state"]

        ep = first_ep[i]
        pos = ep_row_pos.get(ep)
        if pos is None or len(pos) == 0:
            continue
        spell_start = int(first_obs[i])
        state = row["smoothed_state"]
        target_ts = int(spell_start + donor_elapsed * 1e9)

        ep_obs = obs_arr[pos]
        ep_state = state_arr[pos]
        spell_mask = (ep_obs >= spell_start) & (ep_state == state)
        spell_pos = pos[spell_mask]
        if len(spell_pos) == 0:
            continue
        spell_obs = obs_arr[spell_pos]
        cand_mask = spell_obs >= target_ts
        pick_pos = spell_pos[np.argmax(cand_mask)] if cand_mask.any() else spell_pos[-1]
        chosen.append(df.index[pick_pos])  # convert positional index -> original test label

    sig = pd.Series(False, index=test.index)
    sig.loc[chosen] = True
    sig = sig & C.elig(test)
    return ev_delta(test, sig, ep_base, ep_meta, bars, e0_mean)


# ── C3: state-path shuffle across matched episodes ──────────────────────────
def _episode_groups(df, ep_ids, value_col):
    tmp = pd.DataFrame({"episode_id": ep_ids, "seconds_since_entry": df["seconds_since_entry"].values,
                       "_v": np.asarray(value_col)})
    tmp = tmp.sort_values(["episode_id", "seconds_since_entry"])
    out = {}
    for ep, g in tmp.groupby("episode_id", sort=False):
        out[ep] = (g["seconds_since_entry"].values, g["_v"].values)
    return out


def build_episode_match_table(df, ep_meta, atr_edges):
    g = df.groupby("episode_id")
    ep_index = g.size().index
    atr_bucket = pd.cut(g["atr_at_flip"].first().reindex(ep_index), atr_edges, labels=False)
    return pd.DataFrame({
        "session": np.where(g["is_rth"].first() == 1, "RTH", "ETH"),
        "direction": ep_meta["direction"].reindex(ep_index).values,
        "atr_bucket": atr_bucket.values,
    }, index=ep_index)


def matched_donor_map(tbl, seed):
    rng = np.random.default_rng(seed)
    donor = {}
    for key, idx in tbl.groupby(["session", "direction", "atr_bucket"]).groups.items():
        eps = list(idx)
        if len(eps) < 2:
            continue
        shuffled = eps.copy()
        rng.shuffle(shuffled)
        shifted = shuffled[1:] + shuffled[:1]
        for a, b in zip(eps, shifted):
            donor[a] = b
    return donor


def c3_state_path_shuffle(test, ep_base, ep_meta, bars, e0_mean, frozen, atr_edges, seed):
    tbl = build_episode_match_table(test, ep_meta, atr_edges)
    donor_map = matched_donor_map(tbl, seed)
    if not donor_map:
        return np.nan
    donor_groups = _episode_groups(test, test["episode_id"].values, test["smoothed_state"].values)
    tgt_pos = {ep: idx for ep, idx in test.groupby("episode_id", sort=False).indices.items()}

    swapped_state = np.full(len(test), None, dtype=object)
    for ep, donor_ep in donor_map.items():
        pos = tgt_pos.get(ep)
        donor = donor_groups.get(donor_ep)
        if pos is None or donor is None or len(pos) == 0:
            continue
        d_ages, d_states = donor
        tgt_ages = test["seconds_since_entry"].values[pos]
        p = np.searchsorted(d_ages, tgt_ages, side="left")
        p = np.clip(p, 0, len(d_ages) - 1)
        swapped_state[pos] = d_states[p]

    df2 = test.copy()
    valid = swapped_state != None  # noqa: E711
    df2["smoothed_state"] = np.where(valid, swapped_state, test["smoothed_state"])
    sig = p9_signal(df2, ep_meta, frozen)
    return ev_delta(df2, sig, ep_base, ep_meta, bars, e0_mean)


# ── C4 / C5: matched random intervention placebos ───────────────────────────
def matched_count_placebo(test, ep_base, ep_meta, bars, e0_mean, real_sig, edges, seed,
                          restrict_to_ordinary):
    """Trigger the SAME NUMBER of interventions as the real policy, matched
    per-event on (session, direction, age bucket, mfe bucket, giveback
    bucket, atr bucket), optionally restricted to ORDINARY-state donor rows
    (C4) or drawn from the real policy's own realized state distribution
    (C5)."""
    rng = np.random.default_rng(seed)
    real_hit = test[real_sig.values if hasattr(real_sig, "values") else real_sig]
    if len(real_hit) == 0:
        return np.nan
    real_first = real_hit.sort_values("seconds_since_entry").groupby("episode_id").first().reset_index()

    elig_mask = C.elig(test).values
    pool = test[elig_mask].reset_index(drop=True)
    if restrict_to_ordinary:
        pool = pool[pool["smoothed_state"] == "ORDINARY"].reset_index(drop=True)

    pool_bkt = SS.add_match_buckets(pool, edges)
    pool_bkt["episode_id"] = pool["episode_id"].values
    pool_bkt["row_pos"] = np.arange(len(pool))
    real_bkt = SS.add_match_buckets(real_first, edges)
    real_bkt["episode_id"] = real_first["episode_id"].values

    if restrict_to_ordinary:
        key_cols = ["session", "direction", "age_bucket", "mfe_bucket", "giveback_bucket", "atr_bucket"]
    else:
        key_cols = ["session", "direction", "smoothed_state", "age_bucket", "mfe_bucket",
                   "giveback_bucket", "atr_bucket"]
    pool_groups = {k: list(v) for k, v in pool_bkt.groupby(key_cols).groups.items()}
    for k in pool_groups:
        rng.shuffle(pool_groups[k])

    chosen = []
    for i, row in real_bkt.reset_index(drop=True).iterrows():
        key = tuple(row[k] for k in key_cols)
        cands = pool_groups.get(key, [])
        ep = real_bkt["episode_id"].iloc[i]
        picked = None
        remaining = []
        for c in cands:
            if picked is None and pool_bkt["episode_id"].iloc[c] != ep:
                picked = c
            else:
                remaining.append(c)
        pool_groups[key] = remaining
        if picked is not None:
            chosen.append(pool.index[picked])

    sig = pd.Series(False, index=test.index)
    sig.loc[chosen] = True
    return ev_delta(test, sig, ep_base, ep_meta, bars, e0_mean)


# ── C6: transition delay perturbation (deterministic) ───────────────────────
def c6_delay_perturbation(test, ep_base, ep_meta, bars, e0_mean, frozen, shift_s):
    """Shifts the REFERENCE (P9) policy's per-segment delays -- P7 is
    all-disabled on this test period, so perturbing IT would trivially
    remain all-disabled and tell us nothing."""
    def shifted(cfg):
        return {"weak": None if cfg["weak"] is None else cfg["weak"] + shift_s,
                "term": None if cfg["term"] is None else cfg["term"] + shift_s}

    p9_cfg = frozen["P9_config"]
    shifted_cfg = {seg: shifted(cfg) for seg, cfg in p9_cfg.items()}
    sig = BP.p9_signal(test, ep_meta, shifted_cfg)
    return ev_delta(test, sig, ep_base, ep_meta, bars, e0_mean)


# ── C7: fitted-Q benchmark (reference only, never combined) ─────────────────
def c7_fitted_q_benchmark(train, test, ep_base, ep_meta, bars, e0_mean):
    v3_frozen = json.load(open(C.V3_RESULTS / "frozen_policy_config.json"))
    feats0 = v3_frozen["features_P1"]
    v3_full = pd.read_parquet(C.V3_PREPARED_FULL)
    v3_train = v3_full[v3_full["period"] == "train"].reset_index(drop=True)
    v3_test = v3_full[v3_full["period"] == "test"].reset_index(drop=True)
    m0 = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                       min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                       random_state=42, n_jobs=4, verbose=-1)
    m0.fit(v3_train[feats0].fillna(0).to_numpy(dtype=np.float32), v3_train["hold_advantage"].fillna(0).values)
    s_test = m0.predict(v3_test[feats0].fillna(0).to_numpy(dtype=np.float32))
    weak = C.elig(v3_test) & (pd.Series(s_test, index=v3_test.index) < v3_frozen["P1a_thr"])
    return ev_delta(v3_test, weak, ep_base, ep_meta, bars, e0_mean)


def main():
    print("=" * 70)
    print("Phase 7 -- matched state-timing controls (C1-C7, 50 seeds each)")
    print("=" * 70)

    train, val, test, tt = C.load_base()
    bars = C.load_bars()
    train_pb = SS.load_pb_history(train)

    frozen = json.load(open(C.RESULTS / "frozen_policy_config.json"))
    ep_base_test, ep_meta_test = C.prep_period(test, tt, "test")
    e0_test = float(ep_base_test["e0_pnl"].mean())

    sig_ref = p9_signal(test, ep_meta_test, frozen)
    ref_delta = ev_delta(test, sig_ref, ep_base_test, ep_meta_test, bars, e0_test)
    print(f"  reference P9 delta vs E0: ${ref_delta:+.2f}")

    edges = SS.freeze_bucket_edges(train_pb)
    atr_edges = edges["atr"]

    rows, seed_dist_rows = [{"control": "REFERENCE_P9_delta_vs_e0", "mean": ref_delta}], []

    print("  running C1 (random timing within spell, 50 seeds) ...")
    c1_vals = [c1_random_in_spell(test, ep_base_test, ep_meta_test, bars, e0_test,
                                  ["WEAKENING", "TERMINAL"], seed) for seed in range(N_SEEDS)]
    s = seed_summary(c1_vals, ref_delta)
    rows.append({"control": "C1_random_timing_in_spell", **s})
    seed_dist_rows += [{"control": "C1", "seed": i, "value": v} for i, v in enumerate(c1_vals)]
    print(f"    C1 mean=${s['mean']:+.2f} frac_beats_real={s['frac_beating_real_policy']:.2f}")

    print("  running C2 (matched cross-episode timing, 50 seeds) ...")
    c2_vals = [c2_matched_cross_episode_timing(test, ep_base_test, ep_meta_test, bars, e0_test,
                                               ["WEAKENING", "TERMINAL"], edges, seed)
              for seed in range(N_SEEDS)]
    s = seed_summary(c2_vals, ref_delta)
    rows.append({"control": "C2_matched_cross_episode_timing", **s})
    seed_dist_rows += [{"control": "C2", "seed": i, "value": v} for i, v in enumerate(c2_vals)]
    print(f"    C2 mean=${s['mean']:+.2f} frac_beats_real={s['frac_beating_real_policy']:.2f}")

    print("  running C3 (state-path shuffle, 50 seeds) ...")
    c3_vals = [c3_state_path_shuffle(test, ep_base_test, ep_meta_test, bars, e0_test, frozen, atr_edges, seed)
              for seed in range(N_SEEDS)]
    s = seed_summary(c3_vals, ref_delta)
    rows.append({"control": "C3_state_path_shuffle", **s})
    seed_dist_rows += [{"control": "C3", "seed": i, "value": v} for i, v in enumerate(c3_vals)]
    print(f"    C3 mean=${s['mean']:+.2f} frac_beats_real={s['frac_beating_real_policy']:.2f}")

    print("  running C4 (ORDINARY-state placebo, 50 seeds) ...")
    c4_vals = [matched_count_placebo(test, ep_base_test, ep_meta_test, bars, e0_test, sig_ref, edges,
                                     seed, restrict_to_ordinary=True) for seed in range(N_SEEDS)]
    s = seed_summary(c4_vals, ref_delta)
    rows.append({"control": "C4_ordinary_state_placebo", **s})
    seed_dist_rows += [{"control": "C4", "seed": i, "value": v} for i, v in enumerate(c4_vals)]
    print(f"    C4 mean=${s['mean']:+.2f} frac_beats_real={s['frac_beating_real_policy']:.2f}")

    print("  running C5 (intervention-rate-matched random control, 50 seeds) ...")
    c5_vals = [matched_count_placebo(test, ep_base_test, ep_meta_test, bars, e0_test, sig_ref, edges,
                                     seed, restrict_to_ordinary=False) for seed in range(N_SEEDS)]
    s = seed_summary(c5_vals, ref_delta)
    rows.append({"control": "C5_rate_matched_random", **s})
    seed_dist_rows += [{"control": "C5", "seed": i, "value": v} for i, v in enumerate(c5_vals)]
    print(f"    C5 mean=${s['mean']:+.2f} frac_beats_real={s['frac_beating_real_policy']:.2f}")

    print("  running C6 (delay perturbation, deterministic) ...")
    for shift in [5, 10, 15, 30]:
        d = c6_delay_perturbation(test, ep_base_test, ep_meta_test, bars, e0_test, frozen, shift)
        rows.append({"control": f"C6_delay_plus_{shift}s", "mean": d})
        print(f"    C6 +{shift}s: ${d:+.2f}")

    print("  running C7 (fitted-Q benchmark, reference only) ...")
    d_c7 = c7_fitted_q_benchmark(train, test, ep_base_test, ep_meta_test, bars, e0_test)
    rows.append({"control": "C7_fitted_q_BENCHMARK_ONLY", "mean": d_c7})
    print(f"    C7 (v3 P1a benchmark): ${d_c7:+.2f}")

    ctrl_df = pd.DataFrame(rows)
    ctrl_df.to_parquet(C.RESULTS / "control_results.parquet", index=False)
    pd.DataFrame(seed_dist_rows).to_parquet(C.RESULTS / "control_seed_distribution.parquet", index=False)
    print(ctrl_df.to_string(index=False))
    print("done.")


if __name__ == "__main__":
    main()
