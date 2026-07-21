"""
Phase 6 -- valid temporal/causal controls (C1-C7). Replaces v2's invalid
unrestricted within-episode sequence shuffle and random-checkpoint stop
placebo (see audit_v2_policies.py) with controls that never move
later-in-time information to an earlier decision slot.

All controls are evaluated against the frozen P3 state-gated persistence
policy on the development-test period, reusing the exact same execution
stack (sim_v2 fills, next-1s-open, 1s stop-free discretionary exit).

Writes:
  results/control_results.parquet
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import base as C
import sim_v2
import build_policy_candidates as BP
import simulate_structural_stops as SS

RNG = np.random.default_rng(42)


def s_to_ck(s):
    return int(round(s / 5))


def load_frozen():
    frozen = json.load(open(C.RESULTS / "frozen_policy_config.json"))
    return frozen


def build_p3_signal(df, score, thr, K_weak_ck, K_term_ck, S_flag):
    weak = C.elig(df) & (pd.Series(score, index=df.index) < thr)
    codes = df.groupby("episode_id").ngroup().values
    run = C.consecutive_run(weak.values.astype(bool), codes)
    Karr = np.full(len(df), K_weak_ck)
    Tarr = np.full(len(df), K_term_ck)
    return BP.state_gated_signal(df, weak, run, Karr, Tarr, S_flag), weak, run


def ev_delta(df, sig, ep_base, ep_meta, bars, e0_mean):
    pnl = C.policy_pnl(df, sig, ep_base, ep_meta, bars)
    return float(pnl.mean()) - e0_mean


def build_episode_match_table(df, ep_meta, atr_edges):
    """One row per episode: matching keys for C1/C5 (matched-episode swap).

    Deliberately does NOT bucket on final/eventual episode duration -- that is
    only knowable once the episode has terminated and is correlated with
    outcome (a chronically-weak trade that stops out quickly has a very
    different final length than a long-lived runner). Matching keys here are
    session/direction (fixed at entry) plus an ATR-at-flip volatility bucket
    (also fixed at entry, frozen edges from train). Path alignment
    (searchsorted on seconds_since_entry, clipped to the donor's nearest
    available age) already handles donors of different lengths gracefully --
    no duration match is needed for that mechanism to work causally.

    NOTE: two earlier "entry-delay" proxies were tried and both turned out
    degenerate in this population: `seconds_since_entry.min()` is identically
    0 for every episode (the checkpoint stream always starts at age 0), and
    the trades table's own `entry_delay_s` is a CONSTANT 180s for every trade
    (this atlas samples runners at a fixed 180s-post-flip entry by design --
    see common.py's docstring). Neither varies, so neither can discriminate
    donors. Replaced with ATR-at-flip (a genuinely-varying, entry-time,
    causal volatility-regime proxy) on re-audit."""
    g = df.groupby("episode_id")
    ep_index = g.size().index
    atr_at_entry = g["atr_at_flip"].first().reindex(ep_index)
    atr_bucket = pd.cut(atr_at_entry, atr_edges, labels=False)
    tbl = pd.DataFrame({
        "session": np.where(g["is_rth"].first() == 1, "RTH", "ETH"),
        "direction": ep_meta["direction"].reindex(ep_index).values,
        "atr_bucket": atr_bucket.values,
    }, index=ep_index)
    return tbl


def matched_donor_map(tbl, seed=42):
    """For each episode, pick a DIFFERENT episode matched on (session,
    direction, atr_bucket). Fixed seed. Returns dict ep->donor_ep."""
    rng = np.random.default_rng(seed)
    donor = {}
    groups = tbl.groupby(["session", "direction", "atr_bucket"]).groups
    for key, idx in groups.items():
        eps = list(idx)
        if len(eps) < 2:
            continue
        shuffled = eps.copy()
        rng.shuffle(shuffled)
        # derangement-ish: shift by 1; if any fixed point remains, swap with neighbor
        shifted = shuffled[1:] + shuffled[:1]
        for a, b in zip(eps, shifted):
            donor[a] = b
    return donor


def _episode_groups(df, ep_ids, value_col):
    """One groupby pass -> dict episode_id -> (sorted ages, aligned values).
    O(1) lookup per episode afterward, instead of re-filtering the full
    DataFrame (620K+ rows) once per episode (which is what made the earlier
    per-episode `df[df['episode_id']==donor_ep]` loop take 10+ minutes)."""
    tmp = pd.DataFrame({"episode_id": ep_ids, "seconds_since_entry": df["seconds_since_entry"].values,
                         "_v": np.asarray(value_col)})
    tmp = tmp.sort_values(["episode_id", "seconds_since_entry"])
    out = {}
    for ep, g in tmp.groupby("episode_id", sort=False):
        out[ep] = (g["seconds_since_entry"].values, g["_v"].values)
    return out


def c1_matched_score_shuffle(test, score, ep_base, ep_meta, bars, thr, K_weak_ck, K_term_ck, S_flag,
                              e0_mean, atr_edges):
    """Swap each episode's SCORE PATH with a matched donor's, aligned by
    seconds_since_entry (nearest available), then rebuild the P3 signal using
    the target episode's OWN state/direction/session -- only the numeric
    score content is exchanged."""
    tbl = build_episode_match_table(test, ep_meta, atr_edges)
    donor_map = matched_donor_map(tbl)
    if not donor_map:
        return np.nan

    df = test.copy()
    donor_groups = _episode_groups(df, df["episode_id"].values, score)
    tgt_groups_pos = {ep: idx for ep, idx in df.groupby("episode_id", sort=False).indices.items()}

    swapped_score = np.full(len(df), np.nan)
    for ep, donor_ep in donor_map.items():
        tgt_pos = tgt_groups_pos.get(ep)
        donor = donor_groups.get(donor_ep)
        if tgt_pos is None or donor is None or len(tgt_pos) == 0:
            continue
        d_ages, d_scores = donor
        tgt_ages = df["seconds_since_entry"].values[tgt_pos]
        pos = np.searchsorted(d_ages, tgt_ages, side="left")
        pos = np.clip(pos, 0, len(d_ages) - 1)
        swapped_score[tgt_pos] = d_scores[pos]

    valid = ~np.isnan(swapped_score)
    fallback_thr = thr + 1  # never fires where no donor found
    score_use = np.where(valid, swapped_score, fallback_thr)
    sig, _, _ = build_p3_signal(df, score_use, thr, K_weak_ck, K_term_ck, S_flag)
    return ev_delta(df, sig, ep_base, ep_meta, bars, e0_mean)


def c2_masked_circular_shift(test, score, ep_base, ep_meta, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean, seed=7):
    """Circularly shift each episode's OWN score path; mask wrapped rows
    (never eligible to fire) so no future observation can appear earlier."""
    rng = np.random.default_rng(seed)
    df = test.copy()
    df["_score"] = score
    df = df.sort_values(["episode_id", "seconds_since_entry"])
    out_score = np.empty(len(df))
    mask_wrapped = np.zeros(len(df), dtype=bool)
    pos = 0
    for ep, g in df.groupby("episode_id", sort=False):
        n = len(g)
        shift = int(rng.integers(1, max(2, n)))
        vals = g["_score"].values
        shifted = np.roll(vals, shift)
        wrap_mask = np.zeros(n, dtype=bool)
        wrap_mask[:shift] = True  # these rows pulled a value from the FUTURE end via wraparound
        out_score[pos:pos + n] = shifted
        mask_wrapped[pos:pos + n] = wrap_mask
        pos += n
    # Neutralise wrapped (future-derived) rows to "never weak" BEFORE
    # computing weak/run -- masking sig alone is not enough, since the
    # consecutive-run persistence counter would otherwise be primed by a
    # future value at the wrapped row and carry that streak into the very
    # next (unmasked) row. This is the same technique already used for
    # unmatched rows in c1_matched_score_shuffle's fallback_thr.
    out_score_masked = np.where(mask_wrapped, thr + 1, out_score)
    sig, weak, run = build_p3_signal(df, out_score_masked, thr, K_weak_ck, K_term_ck, S_flag)
    return ev_delta(df, sig, ep_base, ep_meta, bars, e0_mean)


def c3_lag(test, score, ep_base, ep_meta, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean, lag_ck):
    s = pd.Series(score, index=test.index).groupby(test["episode_id"]).shift(lag_ck).fillna(thr + 1).values
    sig, _, _ = build_p3_signal(test, s, thr, K_weak_ck, K_term_ck, S_flag)
    return ev_delta(test, sig, ep_base, ep_meta, bars, e0_mean)


def c4_future_lead(test, score, ep_base, ep_meta, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean, lead_ck):
    s = pd.Series(score, index=test.index).groupby(test["episode_id"]).shift(-lead_ck).fillna(thr + 1).values
    sig, _, _ = build_p3_signal(test, s, thr, K_weak_ck, K_term_ck, S_flag)
    return ev_delta(test, sig, ep_base, ep_meta, bars, e0_mean)


def c5_state_shuffle(test, score, ep_base, ep_meta, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean,
                      atr_edges):
    """Shuffle smoothed_state PATHS between matched episodes (same matching
    as C1), keeping each episode's own score/weakness path."""
    tbl = build_episode_match_table(test, ep_meta, atr_edges)
    donor_map = matched_donor_map(tbl, seed=99)
    if not donor_map:
        return np.nan
    df = test.copy()
    donor_groups = _episode_groups(df, df["episode_id"].values, df["smoothed_state"].values)
    tgt_groups_pos = {ep: idx for ep, idx in df.groupby("episode_id", sort=False).indices.items()}

    swapped_state = np.full(len(df), None, dtype=object)
    for ep, donor_ep in donor_map.items():
        tgt_pos = tgt_groups_pos.get(ep)
        donor = donor_groups.get(donor_ep)
        if tgt_pos is None or donor is None or len(tgt_pos) == 0:
            continue
        d_ages, d_states = donor
        tgt_ages = df["seconds_since_entry"].values[tgt_pos]
        pos = np.searchsorted(d_ages, tgt_ages, side="left")
        pos = np.clip(pos, 0, len(d_ages) - 1)
        swapped_state[tgt_pos] = d_states[pos]
    valid = swapped_state != None  # noqa: E711
    df2 = df.copy()
    df2["smoothed_state"] = np.where(valid, swapped_state, df["smoothed_state"])
    weak = C.elig(df2) & (pd.Series(score, index=df2.index) < thr)
    codes = df2.groupby("episode_id").ngroup().values
    run = C.consecutive_run(weak.values.astype(bool), codes)
    sig = BP.state_gated_signal(df2, weak, run, np.full(len(df2), K_weak_ck),
                                 np.full(len(df2), K_term_ck), S_flag)
    return ev_delta(df2, sig, ep_base, ep_meta, bars, e0_mean)


def c6_label_shuffle(test, score, ep_base, ep_meta, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean,
                      K_by_dir, seed=13):
    """Shuffle direction labels only WITHIN each session stratum (RTH/ETH),
    then apply P4's direction-specific K using the SHUFFLED label. If P4's
    long/short split carried real segment signal, this should degrade
    performance toward P3's pooled result."""
    rng = np.random.default_rng(seed)
    ep_dir = ep_meta["direction"]
    ep_rth = test.groupby("episode_id")["is_rth"].first()
    shuffled_dir = ep_dir.copy()
    for sess_val in [1, 0]:
        idx = ep_rth[ep_rth == sess_val].index.intersection(ep_dir.index)
        vals = ep_dir.loc[idx].values.copy()
        rng.shuffle(vals)
        shuffled_dir.loc[idx] = vals
    seg_map = shuffled_dir.map({1: "long", -1: "short"})
    K_arr = test["episode_id"].map(seg_map).map(K_by_dir).fillna(K_weak_ck).values.astype(np.int32)
    weak = C.elig(test) & (pd.Series(score, index=test.index) < thr)
    codes = test.groupby("episode_id").ngroup().values
    run = C.consecutive_run(weak.values.astype(bool), codes)
    sig = BP.state_gated_signal(test, weak, run, K_arr, np.full(len(test), K_term_ck), S_flag)
    return ev_delta(test, sig, ep_base, ep_meta, bars, e0_mean)


def c7_random_intervention(test, ep_base, ep_meta, bars, tt_test, edges, e0_mean, seed=21,
                           p_episode=0.05, hazard=0.15):
    """Trigger an IMMEDIATE EXIT at a genuinely CAUSAL, STREAMING random
    checkpoint -- no weakness signal, no state gate.

    Two independent random draws, neither of which requires knowing an
    episode's eventual length:
      1. `candidate`: a per-episode coin flip keyed only by episode identity
         (available at episode start, before any checkpoint is observed) --
         decides whether this episode is EVER eligible for intervention.
      2. `hazard`: walking a candidate episode's eligible checkpoints IN
         CHRONOLOGICAL ORDER, each one independently fires with probability
         `hazard`; the first success wins. At the moment checkpoint k is
         evaluated, this only ever uses information from checkpoints
         0..k of the SAME episode -- a streaming Bernoulli trigger, exactly
         what a live strategy could implement with a per-bar coin flip.

    This replaces an earlier version that fixed the per-EPISODE selection
    bias (v2's C10 bug) but still chose the WITHIN-episode checkpoint via a
    retrospective `.sample()` over the episode's full eventual eligible set
    -- the same causality violation one level down, caught on re-audit."""
    sm_period = test
    elig_mask = C.elig(sm_period).values
    elig_df = sm_period.loc[elig_mask].sort_values(["episode_id", "seconds_since_entry"])

    ep_ids = elig_df["episode_id"].values
    row_idx = elig_df.index.values
    n = len(elig_df)

    rng = np.random.default_rng(seed)
    uniq_eps = pd.unique(ep_ids)
    candidate_draw = rng.random(len(uniq_eps))
    candidate_set = set(uniq_eps[candidate_draw < p_episode])

    hazard_draws = rng.random(n)
    fired = np.zeros(n, dtype=bool)
    fired_eps = set()
    for i in range(n):
        ep = ep_ids[i]
        if ep in fired_eps or ep not in candidate_set:
            continue
        if hazard_draws[i] < hazard:
            fired[i] = True
            fired_eps.add(ep)

    sig = pd.Series(False, index=sm_period.index)
    sig.loc[row_idx[fired]] = True
    return ev_delta(sm_period, sig, ep_base, ep_meta, bars, e0_mean)


def main():
    print("=" * 70)
    print("Phase 6 -- causal controls (C1-C7)")
    print("=" * 70)

    train, val, test, tt = C.prepare_base()
    bars = C.load_bars()
    sm = pd.read_parquet(C.RESULTS / "smoothed_state_checkpoints.parquet")
    key_cols = ["episode_id", "observation_time"]
    test = test.merge(sm[key_cols + ["smoothed_state", "seconds_in_smoothed_state"]], on=key_cols, how="left")

    frozen = load_frozen()
    feats0 = frozen["features_P1"]
    m0 = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                        random_state=42, n_jobs=4, verbose=-1)
    m0.fit(C.Xmat(train, feats0), train["hold_advantage"].fillna(0).values)
    score = m0.predict(C.Xmat(test, feats0))
    thr = frozen["P1a_thr"]
    K_weak_ck = s_to_ck(frozen["P3_K_weakening_seconds"])
    K_term_ck = s_to_ck(frozen["K_terminal_seconds"])
    struct = BP.build_structural_flags(test)
    S_flag = struct[frozen["S_variant"]]

    ep_base_test, ep_meta_test = C.prep_period(test, tt, "test")
    e0_mean = float(ep_base_test["e0_pnl"].mean())

    # ATR-at-flip bucket edges (frozen on train) -- the C1/C5 matching key
    train_atr_per_ep = train.groupby("episode_id")["atr_at_flip"].first()
    atr_edges = np.unique(np.nanquantile(train_atr_per_ep.values, np.linspace(0, 1, 5)))

    sig_p3, _, _ = build_p3_signal(test, score, thr, K_weak_ck, K_term_ck, S_flag)
    p3_ev = float(C.policy_pnl(test, sig_p3, ep_base_test, ep_meta_test, bars).mean())
    p3_delta = p3_ev - e0_mean
    print(f"  reference P3 delta vs E0: ${p3_delta:+.2f}")

    rows = [{"control": "REFERENCE_P3_delta_vs_e0", "ev_delta": round(p3_delta, 3)}]

    d = c1_matched_score_shuffle(test, score, ep_base_test, ep_meta_test, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean, atr_edges)
    rows.append({"control": "C1_matched_episode_score_shuffle", "ev_delta": round(d, 3)})
    print(f"  C1 matched-episode score shuffle: ${d:+.2f}")

    d = c2_masked_circular_shift(test, score, ep_base_test, ep_meta_test, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean)
    rows.append({"control": "C2_masked_circular_shift", "ev_delta": round(d, 3)})
    print(f"  C2 masked circular shift: ${d:+.2f}")

    for secs in [5, 10, 15, 30]:
        d = c3_lag(test, score, ep_base_test, ep_meta_test, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean, s_to_ck(secs))
        rows.append({"control": f"C3_lag_{secs}s", "ev_delta": round(d, 3)})
        print(f"  C3 lag {secs}s: ${d:+.2f}")

    for secs in [5, 10]:
        d = c4_future_lead(test, score, ep_base_test, ep_meta_test, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean, s_to_ck(secs))
        rows.append({"control": f"C4_future_lead_{secs}s_ORACLE_quarantined", "ev_delta": round(d, 3)})
        print(f"  C4 future-lead oracle {secs}s (quarantined, non-tradable): ${d:+.2f}")

    d = c5_state_shuffle(test, score, ep_base_test, ep_meta_test, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean, atr_edges)
    rows.append({"control": "C5_state_shuffle_matched_episodes", "ev_delta": round(d, 3)})
    print(f"  C5 state shuffle (matched episodes): ${d:+.2f}")

    K_by_dir = {"long": s_to_ck(frozen["P4_K_long_seconds"]), "short": s_to_ck(frozen["P4_K_short_seconds"])}
    d = c6_label_shuffle(test, score, ep_base_test, ep_meta_test, bars, thr, K_weak_ck, K_term_ck, S_flag, e0_mean, K_by_dir)
    rows.append({"control": "C6_direction_label_shuffle_within_session", "ev_delta": round(d, 3)})
    print(f"  C6 direction-label shuffle within session: ${d:+.2f}")

    edges = SS.freeze_bucket_edges(train.merge(sm[key_cols + ["smoothed_state", "seconds_in_smoothed_state"]],
                                                on=key_cols, how="left"))
    tt_test = tt[tt["period"] == "test"]
    d = c7_random_intervention(test, ep_base_test, ep_meta_test, bars, tt_test, edges, e0_mean)
    rows.append({"control": "C7_random_intervention_streaming_causal", "ev_delta": round(d, 3)})
    print(f"  C7 random intervention (matched checkpoint, no weakness signal): ${d:+.2f}")

    ctrl_df = pd.DataFrame(rows)
    ctrl_df["p3_reference_delta"] = round(p3_delta, 3)
    ctrl_df.to_parquet(C.RESULTS / "control_results.parquet", index=False)
    print(ctrl_df.to_string(index=False))
    print("done.")


if __name__ == "__main__":
    main()
