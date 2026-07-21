"""
Phase 5 -- state-triggered structural stops (S0-S5), NO fitted-Q anywhere.
Phase 6 -- EXACT one-to-one matched stop placebo, >=50 seeds.

Stop geometry (validation-selected, fixed 0.25 ATR buffer per spec):
  A: current pullback low/high (60s bar-scan) +/- 0.25 ATR
  B: last recovered pullback low/high (Family-G `pb_max_depth`, reused
     READ-ONLY from contextual_runner_exit_v3's existing, already-audited
     MTF context cache -- not a new feature) +/- 0.25 ATR
  C: the TIGHTER (more conservative) of A and B
  D: fixed giveback-from-MFE (0.25 or 0.50 ATR, validation-selected)

Arming architectures:
  S0: E0 (no intervention)
  S1: arm stop at first confirmed WEAKENING
  S2: arm stop after persistent WEAKENING (frozen P4 WEAKENING delay)
  S3: arm stop at TERMINAL (instead of an immediate market exit)
  S4: WEAKENING arms a stop; TERMINAL is a market exit (not a stop)
  S5: ETH-only version of the winning S1-S4 architecture; RTH stays on E0

Phase 6 matched placebo -- for every REAL stop-arm event, find EXACTLY ONE
placebo checkpoint from a DIFFERENT episode in the same (session, direction,
smoothed_state, trade-age bucket, regime-age bucket, MFE bucket, giveback
bucket, ATR bucket) cell, via random permutation WITHOUT REPLACEMENT within
each cell (no donor reused within a seed unless the cell is exhausted, in
which case the excess real events are reported as unmatched, not silently
dropped or duplicated). Repeated across >=50 seeds.

Writes:
  results/state_stop_trades.parquet
  results/state_stop_episode_results.parquet
  results/state_stop_metrics.parquet
  results/matched_stop_placebo.parquet
  results/matched_stop_placebo_summary.parquet
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

import base as C
import sim_v2
import build_deterministic_policies as BP

BUFFER_ATR = 0.25
D_GIVEBACK_CANDIDATES = [0.25, 0.50]
STRUCT_LOOKBACK_S = 60
N_PLACEBO_SEEDS = 50


def structural_low_high(bars, sig_ts, direction, lookback_s=STRUCT_LOOKBACK_S):
    lo_i = np.searchsorted(bars[:, 0], sig_ts - lookback_s * 1_000_000_000, side="left")
    hi_i = np.searchsorted(bars[:, 0], sig_ts, side="right")
    if hi_i <= lo_i:
        return np.nan
    if direction == 1:
        return float(bars[lo_i:hi_i, 2].min())
    return float(bars[lo_i:hi_i, 3].max())


def load_pb_history(period_df):
    """READ-ONLY reuse of contextual_runner_exit_v2's already-computed,
    already-audited Family-G pullback-history column (pb_max_depth) -- not a
    new feature. (v3 reused this same cache for its own structural stops.)"""
    pb = pd.read_parquet(C.V2_CONTEXT_CACHE, columns=["episode_id", "observation_time", "pb_max_depth"])
    merged = period_df.merge(pb, on=["episode_id", "observation_time"], how="left")
    assert len(merged) == len(period_df), "pb-history merge changed row count"
    return merged


def weakening_events(df, delay_s):
    sig = BP.signal_state_delay(df, ["WEAKENING"], delay_s, "dwell")
    hit = df[sig.values]
    if len(hit) == 0:
        return pd.DataFrame()
    return hit.sort_values("seconds_since_entry").groupby("episode_id").first().reset_index()


def terminal_events(df):
    sig = BP.signal_state_delay(df, ["TERMINAL"], 0, "dwell")
    hit = df[sig.values]
    if len(hit) == 0:
        return pd.DataFrame()
    return hit.sort_values("seconds_since_entry").groupby("episode_id").first().reset_index()


def build_stop_levels(ev_row, bars, ep_meta):
    ep = ev_row.episode_id
    d = int(ev_row.direction)
    atr = float(ev_row.atr_at_flip)
    entry_px = float(ep_meta.loc[ep, "entry_px"])
    sig_ts = int(ev_row.observation_time)
    buf = BUFFER_ATR * atr

    struct_lvl = structural_low_high(bars, sig_ts, d)
    lvl_a = (struct_lvl - buf) if d == 1 else (struct_lvl + buf)

    pb_ref = getattr(ev_row, "pb_max_depth", np.nan)
    prior_pb_px = (entry_px - d * float(pb_ref) * atr) if pd.notna(pb_ref) and pb_ref > 0 else struct_lvl
    lvl_b = (prior_pb_px - buf) if d == 1 else (prior_pb_px + buf)

    if d == 1:
        lvl_c = max(lvl_a, lvl_b) if pd.notna(lvl_a) and pd.notna(lvl_b) else (lvl_a if pd.notna(lvl_a) else lvl_b)
    else:
        lvl_c = min(lvl_a, lvl_b) if pd.notna(lvl_a) and pd.notna(lvl_b) else (lvl_a if pd.notna(lvl_a) else lvl_b)

    mfe = float(ev_row.trade_mfe_atr)
    levels_d = {gb: entry_px + d * (mfe - gb) * atr for gb in D_GIVEBACK_CANDIDATES}

    return {"A": lvl_a, "B": lvl_b, "C": lvl_c, **{f"D{gb}": levels_d[gb] for gb in D_GIVEBACK_CANDIDATES}}


def simulate_one_stop_set(events, ep_base, ep_meta, tt_period, bars, rule, buffer_atr=BUFFER_ATR,
                          d_giveback=0.5):
    term_map = tt_period.set_index("episode_id")["true_terminal_ts"]
    recs = []
    for r in events.itertuples(index=False):
        ep = r.episode_id
        d = int(r.direction)
        entry = float(ep_meta.loc[ep, "entry_px"])
        atr = float(r.atr_at_flip)
        sig_ts = int(r.observation_time)
        end_ts = int(term_map.get(ep, sig_ts))
        e0 = float(ep_base["e0_pnl"].get(ep, np.nan))

        levels = build_stop_levels(r, bars, ep_meta)
        if rule.startswith("D"):
            lvl = entry + d * (float(r.trade_mfe_atr) - d_giveback) * atr
        else:
            lvl = levels[rule]

        rec = {"episode_id": ep, "signal_ts": sig_ts, "state_at_signal": r.smoothed_state,
               "direction": d, "stop_rule": rule, "stop_activation_ts": sig_ts,
               "initial_stop_price": float(lvl) if pd.notna(lvl) else np.nan,
               "all_stop_updates": json.dumps([float(lvl)]) if pd.notna(lvl) else "[]",
               "e0_pnl": e0}

        if lvl is None or (isinstance(lvl, float) and np.isnan(lvl)):
            rec.update({"stop_trigger_ts": None, "stop_fill_ts": None, "stop_fill_price": None,
                       "recovery_ts": None, "new_mfe_ts": None, "recovery_before_stop": False,
                       "new_mfe_before_stop": False, "net_pnl": e0})
            recs.append(rec)
            continue

        _, cur_px = sim_v2.next_1s_open(bars, sig_ts)
        invalid = (d == 1 and cur_px <= lvl) or (d == -1 and cur_px >= lvl)
        if invalid:
            pnl = (cur_px - entry) * d * C.NQ_MULT - C.COMMISSION
            rec.update({"stop_trigger_ts": sig_ts, "stop_fill_ts": sig_ts,
                       "stop_fill_price": float(cur_px), "recovery_ts": None, "new_mfe_ts": None,
                       "recovery_before_stop": False, "new_mfe_before_stop": False, "net_pnl": pnl})
            recs.append(rec)
            continue

        stop_ts, stop_fill = sim_v2.detect_stop_hit(bars, sig_ts, end_ts, lvl, d)
        fav_target = entry + d * (float(r.trade_mfe_atr) + 0.10) * atr
        lo_i = np.searchsorted(bars[:, 0], sig_ts, side="left")
        hi_i = np.searchsorted(bars[:, 0], end_ts, side="right")
        seg = bars[lo_i:hi_i]
        if d == 1:
            rec_mask = seg[:, 3] >= fav_target
        else:
            rec_mask = seg[:, 2] <= fav_target
        rec_ts = int(seg[np.argmax(rec_mask), 0]) if (len(seg) and rec_mask.any()) else None

        stopped = stop_ts is not None
        recovered_first = rec_ts is not None and (not stopped or rec_ts < stop_ts)
        if stopped and not recovered_first:
            pnl = (stop_fill - entry) * d * C.NQ_MULT - C.COMMISSION
            rec.update({"stop_trigger_ts": stop_ts, "stop_fill_ts": stop_ts,
                       "stop_fill_price": float(stop_fill)})
        else:
            pnl = e0
            rec.update({"stop_trigger_ts": stop_ts if stopped else None,
                       "stop_fill_ts": None, "stop_fill_price": None})
        rec.update({"recovery_ts": rec_ts, "new_mfe_ts": rec_ts,
                   "recovery_before_stop": bool(recovered_first),
                   "new_mfe_before_stop": bool(rec_ts is not None), "net_pnl": pnl})
        recs.append(rec)
    return pd.DataFrame(recs)


def s1s4_pnl(df, ep_base, ep_meta, tt_period, bars, arch, K_weak_delay, rule, d_giveback, only_mask=None):
    """arch in {'S1','S2','S3','S4'}. Returns per-episode net PnL Series
    (E0 default; overwritten by whichever branch fires)."""
    result = ep_base["e0_pnl"].copy()
    df_use = df if only_mask is None else df[only_mask]

    if arch in ("S1", "S2"):
        delay = 0 if arch == "S1" else K_weak_delay
        ev = weakening_events(df_use, delay)
        if len(ev):
            sr = simulate_one_stop_set(ev, ep_base, ep_meta, tt_period, bars, rule, d_giveback=d_giveback)
            result.loc[sr["episode_id"].values] = sr["net_pnl"].values
        return result, (ev if len(ev) else pd.DataFrame())

    if arch == "S3":
        ev = terminal_events(df_use)
        if len(ev):
            sr = simulate_one_stop_set(ev, ep_base, ep_meta, tt_period, bars, rule, d_giveback=d_giveback)
            result.loc[sr["episode_id"].values] = sr["net_pnl"].values
        return result, (ev if len(ev) else pd.DataFrame())

    if arch == "S4":
        # WEAKENING arms a stop; TERMINAL is an immediate market exit.
        # TERMINAL is NOT absorbing in this state machine (it can recover to
        # WEAKENING/ORDINARY and a later WEAKENING-delay can re-confirm), so
        # "which event resolves the episode" must compare ACTUAL TIMESTAMPS,
        # not just episode-ID set membership (an episode-ID-only check would
        # let a later WEAKENING arm silently override an earlier, already-
        # correct TERMINAL market exit).
        ev_w = weakening_events(df_use, K_weak_delay)
        ev_t = terminal_events(df_use)
        w_ts = ev_w.set_index("episode_id")["observation_time"] if len(ev_w) else pd.Series(dtype=float)
        t_ts = ev_t.set_index("episode_id")["observation_time"] if len(ev_t) else pd.Series(dtype=float)
        all_eps = w_ts.index.union(t_ts.index)
        w_first = (w_ts.reindex(all_eps).fillna(np.inf) <= t_ts.reindex(all_eps).fillna(np.inf))

        ev_w_wins = ev_w[ev_w["episode_id"].isin(w_first[w_first].index)] if len(ev_w) else pd.DataFrame()
        ev_t_wins = ev_t[ev_t["episode_id"].isin(w_first[~w_first].index)] if len(ev_t) else pd.DataFrame()

        if len(ev_w_wins):
            sr_w = simulate_one_stop_set(ev_w_wins, ep_base, ep_meta, tt_period, bars, rule, d_giveback=d_giveback)
            result.loc[sr_w["episode_id"].values] = sr_w["net_pnl"].values
        if len(ev_t_wins):
            # TERMINAL branch is a MARKET EXIT here, not a stop.
            pnl_t = C.policy_pnl(df_use, BP.signal_state_delay(df_use, ["TERMINAL"], 0, "dwell"),
                                 ep_base, ep_meta, bars)
            result.loc[ev_t_wins["episode_id"].values] = pnl_t.loc[ev_t_wins["episode_id"].values].values
        all_ev = [e for e in (ev_w_wins, ev_t_wins) if len(e)]
        return result, (pd.concat(all_ev, ignore_index=True) if all_ev else pd.DataFrame())

    raise ValueError(arch)


# ── Phase 6: exact one-to-one matched placebo ───────────────────────────────
def add_match_buckets(df, edges):
    b = pd.DataFrame(index=df.index)
    b["session"] = np.where(df["is_rth"] == 1, "RTH", "ETH")
    b["direction"] = df["direction"].astype(int)
    b["smoothed_state"] = df["smoothed_state"]
    b["age_bucket"] = pd.cut(df["seconds_since_entry"], edges["age"], labels=False)
    b["regime_age_bucket"] = pd.cut(df["seconds_in_smoothed_state"], edges["regime_age"], labels=False)
    b["mfe_bucket"] = pd.cut(df["trade_mfe_atr"], edges["mfe"], labels=False)
    b["giveback_bucket"] = pd.cut(df["giveback_fraction"].fillna(0), edges["giveback"], labels=False)
    b["atr_bucket"] = pd.cut(df["atr_at_flip"], edges["atr"], labels=False)
    return b


def freeze_bucket_edges(train_df):
    q = lambda s, n: np.unique(np.nanquantile(s.values, np.linspace(0, 1, n + 1)))
    return {
        "age": np.array([0, 30, 60, 120, 240, 480, 1e9]),
        "regime_age": np.array([0, 10, 30, 60, 120, 1e9]),
        "mfe": q(train_df["trade_mfe_atr"].clip(lower=0), 4),
        "giveback": np.array([-1e-9, 0.1, 0.25, 0.5, 1.0, 1e9]),
        "atr": q(train_df["atr_at_flip"].fillna(0), 4),
    }


def exact_match_one_seed(real_bkt, pool_bkt, key_cols, seed):
    """Exact 1:1 matching WITHOUT replacement within this seed -- at the
    EPISODE level: once a donor EPISODE has supplied a checkpoint to one real
    event in this seed, none of its OTHER rows may be drawn again this seed
    (even from a different bucket), so every placebo observation in a given
    seed comes from a distinct episode and the 50-seed distribution reflects
    genuine resampling variability rather than one episode's path repeating.
    Returns (matched_real_idx, matched_donor_row_pos, unmatched_real_idx)."""
    rng = np.random.default_rng(seed)
    pool_groups = {}
    for key, g in pool_bkt.groupby(key_cols):
        order = g["row_pos"].values.copy()
        rng.shuffle(order)
        pool_groups[key] = list(order)

    used_donor_episodes = set()
    matched_real, matched_donor, unmatched_real = [], [], []
    real_shuffled_idx = real_bkt.index.values.copy()
    rng.shuffle(real_shuffled_idx)
    for i in real_shuffled_idx:
        row = real_bkt.loc[i]
        key = tuple(row[k] for k in key_cols)
        pool = pool_groups.get(key, [])
        chosen = None
        # skip donors from the SAME episode as this real event, AND donor
        # episodes already used elsewhere in this seed
        skipped = []
        while pool:
            cand = pool.pop()
            cand_ep = pool_bkt["episode_id"].iloc[cand]
            if cand_ep == row["episode_id"] or cand_ep in used_donor_episodes:
                skipped.append(cand)
                continue
            chosen = cand
            break
        pool_groups[key] = pool  # already popped from
        # do NOT permanently discard skipped donors -- they were only invalid
        # for THIS specific real event (self-episode) or already used
        # elsewhere; restore them so later reals in the same key can still
        # try them (a "used" donor may become relevant again only if freed,
        # which never happens within a seed, so this mainly serves the
        # same-episode-as-target skip case).
        if skipped:
            pool_groups[key] = skipped + pool_groups[key]
        if chosen is not None:
            used_donor_episodes.add(pool_bkt["episode_id"].iloc[chosen])
        if chosen is None:
            unmatched_real.append(i)
        else:
            matched_real.append(i)
            matched_donor.append(chosen)
    return matched_real, matched_donor, unmatched_real


def run_matched_placebo(real_events, sm_period, edges, ep_meta, ep_base, tt_period, bars,
                        rule, d_giveback, n_seeds=N_PLACEBO_SEEDS):
    pool_bkt = add_match_buckets(sm_period, edges)
    pool_bkt["episode_id"] = sm_period["episode_id"].values
    pool_bkt["row_pos"] = np.arange(len(sm_period))
    elig_mask = C.elig(sm_period).values
    pool_bkt = pool_bkt[elig_mask].reset_index(drop=True)
    pool_bkt["row_pos"] = np.arange(len(pool_bkt))  # positions into the FILTERED sm_period_elig
    sm_period_elig = sm_period[elig_mask].reset_index(drop=True)

    # real_events is already a subset of sm_period's own rows (one row per
    # episode, the confirmed arm/trigger checkpoint) -- it already carries
    # every column add_match_buckets needs, no merge required.
    real_events = real_events.reset_index(drop=True)
    real_bkt = add_match_buckets(real_events, edges)
    real_bkt["episode_id"] = real_events["episode_id"].values

    key_cols = ["session", "direction", "smoothed_state", "age_bucket", "regime_age_bucket",
                "mfe_bucket", "giveback_bucket", "atr_bucket"]

    seed_rows = []
    all_placebo_rows = []
    for seed in range(n_seeds):
        matched_real, matched_donor, unmatched_real = exact_match_one_seed(real_bkt, pool_bkt, key_cols, seed)
        if not matched_real:
            continue
        donor_rows = sm_period_elig.iloc[[pool_bkt["row_pos"].iloc[d] for d in matched_donor]].reset_index(drop=True)
        donor_rows = donor_rows.merge(ep_meta[["entry_px", "direction"]], left_on="episode_id",
                                      right_index=True, how="left", suffixes=("", "_m"))
        # build placebo events using the DONOR's own context
        placebo_rows = []
        for r in donor_rows.itertuples(index=False):
            placebo_rows.append({"episode_id": r.episode_id, "direction": int(r.direction),
                                 "observation_time": int(r.observation_time),
                                 "atr_at_flip": float(r.atr_at_flip), "trade_mfe_atr": float(r.trade_mfe_atr),
                                 "pb_max_depth": getattr(r, "pb_max_depth", np.nan),
                                 "smoothed_state": r.smoothed_state})
        placebo_events = pd.DataFrame(placebo_rows)
        placebo_stop = simulate_one_stop_set(placebo_events, ep_base, ep_meta, tt_period, bars, rule,
                                             d_giveback=d_giveback)
        real_sub = real_events.iloc[matched_real].reset_index(drop=True)
        real_stop = simulate_one_stop_set(real_sub, ep_base, ep_meta, tt_period, bars, rule, d_giveback=d_giveback)

        real_delta = float((real_stop["net_pnl"] - real_stop["e0_pnl"]).mean())
        placebo_delta = float((placebo_stop["net_pnl"] - placebo_stop["e0_pnl"]).mean())
        seed_rows.append({"seed": seed, "n_matched": len(matched_real), "n_unmatched": len(unmatched_real),
                          "real_delta": real_delta, "placebo_delta": placebo_delta,
                          "real_minus_placebo": real_delta - placebo_delta})
        if seed == 0:
            placebo_stop["seed"] = seed
            all_placebo_rows.append(placebo_stop)

    return pd.DataFrame(seed_rows), (pd.concat(all_placebo_rows, ignore_index=True) if all_placebo_rows else pd.DataFrame())


def main():
    print("=" * 70)
    print("Phase 5/6 -- state-triggered stops + exact matched placebo")
    print("=" * 70)

    train, val, test, tt = C.load_base()
    bars = C.load_bars()
    train = load_pb_history(train)
    val = load_pb_history(val)
    test = load_pb_history(test)

    frozen = json.load(open(C.RESULTS / "frozen_policy_config.json"))
    K_weak_delay = frozen["P4_Kweak_seconds"]

    ep_base_val, ep_meta_val = C.prep_period(val, tt, "val")
    tt_val = tt[tt["period"] == "val"]
    e0_val = float(ep_base_val["e0_pnl"].mean())

    # ── select stop rule + D giveback on validation, architecture S2 as probe ──
    best = (-1e9, None, None)
    for rule in ["A", "B", "C"]:
        pnl, _ = s1s4_pnl(val, ep_base_val, ep_meta_val, tt_val, bars, "S2", K_weak_delay, rule, 0.5)
        d = float(pnl.mean()) - e0_val
        print(f"  [val] S2 rule={rule}: delta vs E0 = ${d:+.2f}")
        if d > best[0]:
            best = (d, rule, None)
    for gb in D_GIVEBACK_CANDIDATES:
        pnl, _ = s1s4_pnl(val, ep_base_val, ep_meta_val, tt_val, bars, "S2", K_weak_delay, "D", gb)
        d = float(pnl.mean()) - e0_val
        print(f"  [val] S2 rule=D giveback={gb}: delta vs E0 = ${d:+.2f}")
        if d > best[0]:
            best = (d, "D", gb)
    _, rule_frozen, gb_frozen = best
    gb_frozen = gb_frozen if gb_frozen is not None else 0.5
    print(f"  FROZEN stop geometry: rule={rule_frozen} giveback={gb_frozen} (val delta ${best[0]:+.2f})")

    # ── select architecture S1-S4 on validation ────────────────────────────
    best_arch = (-1e9, "S1")
    for arch in ["S1", "S2", "S3", "S4"]:
        pnl, _ = s1s4_pnl(val, ep_base_val, ep_meta_val, tt_val, bars, arch, K_weak_delay, rule_frozen, gb_frozen)
        d = float(pnl.mean()) - e0_val
        print(f"  [val] architecture {arch}: delta vs E0 = ${d:+.2f}")
        if d > best_arch[0]:
            best_arch = (d, arch)
    arch_frozen = best_arch[1]
    print(f"  FROZEN architecture: {arch_frozen} (val delta ${best_arch[0]:+.2f})")

    # ── S5 (ETH-only winning architecture) vs whole-population winner ──────
    eth_mask_val = val["is_rth"] != 1
    pnl_s5, _ = s1s4_pnl(val, ep_base_val, ep_meta_val, tt_val, bars, arch_frozen, K_weak_delay,
                         rule_frozen, gb_frozen, only_mask=eth_mask_val)
    d_s5 = float(pnl_s5.mean()) - e0_val
    print(f"  [val] S5 (ETH-only {arch_frozen}): delta vs E0 = ${d_s5:+.2f}")

    C.savej({"stop_rule": rule_frozen, "d_giveback_atr": gb_frozen, "architecture": arch_frozen,
            "K_weakening_delay_seconds": K_weak_delay, "buffer_atr": BUFFER_ATR}, C.RESULTS / "frozen_stop_config.json")

    # ── run frozen stop architecture on TEST ────────────────────────────────
    ep_base_test, ep_meta_test = C.prep_period(test, tt, "test")
    tt_test = tt[tt["period"] == "test"]
    pnl_test, ev_test = s1s4_pnl(test, ep_base_test, ep_meta_test, tt_test, bars, arch_frozen,
                                 K_weak_delay, rule_frozen, gb_frozen)
    e0_test = float(ep_base_test["e0_pnl"].mean())

    if len(ev_test):
        stop_trades = simulate_one_stop_set(ev_test.drop_duplicates("episode_id"), ep_base_test, ep_meta_test,
                                            tt_test, bars, rule_frozen, d_giveback=gb_frozen)
    else:
        stop_trades = pd.DataFrame()
    stop_trades.to_parquet(C.RESULTS / "state_stop_trades.parquet", index=False)

    immediate_pnl = C.policy_pnl(test, BP.signal_state_delay(test, ["WEAKENING", "TERMINAL"], 0, "combined"),
                                 ep_base_test, ep_meta_test, bars)
    stop_ep_res = pd.DataFrame({"episode_id": pnl_test.index, "net_pnl": pnl_test.values,
                                "e0_pnl": ep_base_test["e0_pnl"].values,
                                "immediate_exit_pnl": immediate_pnl.values})
    stop_ep_res.to_parquet(C.RESULTS / "state_stop_episode_results.parquet", index=False)

    d_e0 = float(pnl_test.mean()) - e0_test
    d_imm = float((pnl_test - immediate_pnl).mean())
    metrics = {"architecture": arch_frozen, "stop_rule": rule_frozen, "d_giveback_atr": gb_frozen,
              "n_events": len(ev_test.drop_duplicates("episode_id")) if len(ev_test) else 0,
              "mean_pnl": round(float(pnl_test.mean()), 2), "delta_vs_e0": round(d_e0, 2),
              "delta_vs_immediate_exit": round(d_imm, 2)}
    pd.DataFrame([metrics]).to_parquet(C.RESULTS / "state_stop_metrics.parquet", index=False)
    print(f"  TEST: {arch_frozen} n_events={metrics['n_events']} delta_vs_E0=${d_e0:+.2f} delta_vs_imm=${d_imm:+.2f}")

    # ── Phase 6: exact matched placebo (test), >=50 seeds ───────────────────
    print("\n[Phase 6] exact one-to-one matched placebo (50 seeds) ...")
    edges = freeze_bucket_edges(train)
    real_events_for_placebo = ev_test.drop_duplicates("episode_id").reset_index(drop=True) if len(ev_test) else pd.DataFrame()
    if len(real_events_for_placebo):
        seed_df, placebo_sample = run_matched_placebo(real_events_for_placebo, test, edges, ep_meta_test,
                                                       ep_base_test, tt_test, bars, rule_frozen, gb_frozen)
        seed_df.to_parquet(C.RESULTS / "matched_stop_placebo.parquet", index=False)
        frac_real_beats = float((seed_df["real_minus_placebo"] > 0).mean())
        summary = {
            "n_seeds": len(seed_df),
            "mean_real_delta": round(float(seed_df["real_delta"].mean()), 3),
            "mean_placebo_delta": round(float(seed_df["placebo_delta"].mean()), 3),
            "mean_real_minus_placebo": round(float(seed_df["real_minus_placebo"].mean()), 3),
            "median_real_minus_placebo": round(float(seed_df["real_minus_placebo"].median()), 3),
            "std_real_minus_placebo": round(float(seed_df["real_minus_placebo"].std()), 3),
            "p5": round(float(seed_df["real_minus_placebo"].quantile(0.05)), 3),
            "p25": round(float(seed_df["real_minus_placebo"].quantile(0.25)), 3),
            "p75": round(float(seed_df["real_minus_placebo"].quantile(0.75)), 3),
            "p95": round(float(seed_df["real_minus_placebo"].quantile(0.95)), 3),
            "frac_seeds_real_beats_placebo": frac_real_beats,
            "mean_n_matched": round(float(seed_df["n_matched"].mean()), 1),
            "mean_n_unmatched": round(float(seed_df["n_unmatched"].mean()), 1),
        }
        pd.DataFrame([summary]).to_parquet(C.RESULTS / "matched_stop_placebo_summary.parquet", index=False)
        print(pd.DataFrame([summary]).to_string(index=False))
    else:
        print("  no stop events on test -- skipping matched placebo")
        pd.DataFrame().to_parquet(C.RESULTS / "matched_stop_placebo.parquet", index=False)
        pd.DataFrame().to_parquet(C.RESULTS / "matched_stop_placebo_summary.parquet", index=False)

    print("done.")


if __name__ == "__main__":
    main()
