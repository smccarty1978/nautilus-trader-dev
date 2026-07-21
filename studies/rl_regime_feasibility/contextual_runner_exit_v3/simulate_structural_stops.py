"""
Phase 4/5 -- real structural-stop policies (Stop A/B/C/D) monitored on 1s
bars, plus a CAUSALLY MATCHED cross-episode placebo (replaces v2's invalid
random-checkpoint placebo -- see audit_v2_policies.py finding #3).

Stop A: current pullback structure (recent structural low/high - buffer).
Stop B: prior recovered pullback structure (last completed+recovered
         pullback extreme from Family G history; falls back to Stop A's
         level if no completed pullback exists yet).
Stop C: MFE/ATR stop -- give back a validation-selected fraction of MFE.
Stop D: state-gated arming -- PROLIFIC/HEALTHY arm a structural stop,
         ORDINARY no action, WEAKENING exit after persistence (frozen P3
         K_weakening), TERMINAL immediate exit.

Matched placebo: for every real arm event, draw a DIFFERENT episode's
checkpoint from the same (session, direction, smoothed_state, age-bucket,
regime-age-bucket, MFE-bucket, giveback-bucket, vol-bucket) cell. Bucket
edges for continuous variables are frozen on TRAIN. No future information:
matching uses only variables observable AT that checkpoint.

Writes:
  results/structural_stop_trades.parquet
  results/structural_stop_episode_results.parquet
  results/structural_stop_metrics.parquet
  results/matched_stop_placebo.parquet
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

import base as C
import sim_v2
import build_policy_candidates as BP

BUFFER_ATR_CANDIDATES = [0.05, 0.10, 0.25]
MFE_GIVEBACK_FRAC_CANDIDATES = [0.35, 0.50, 0.65]
STRUCT_LOOKBACK_S = 60


def structural_low_high(bars, sig_ts, direction, lookback_s=STRUCT_LOOKBACK_S):
    lo_i = np.searchsorted(bars[:, 0], sig_ts - lookback_s * 1_000_000_000, side="left")
    hi_i = np.searchsorted(bars[:, 0], sig_ts, side="right")
    if hi_i <= lo_i:
        return np.nan
    if direction == 1:
        return float(bars[lo_i:hi_i, 2].min())
    return float(bars[lo_i:hi_i, 3].max())


def load_pb_history(period_df):
    """Merge Family-G pullback-history columns (not in NEEDED_CTX_COLS) onto
    the already-prepared frame, keyed on (episode_id, observation_time)."""
    pb = pd.read_parquet(C.V2_CONTEXT_CACHE, columns=[
        "episode_id", "observation_time", "pb_last_depth", "pb_median_depth",
        "pb_max_depth", "pb_last_made_new_extreme"])
    merged = period_df.merge(pb, on=["episode_id", "observation_time"], how="left")
    assert len(merged) == len(period_df), "pb-history merge changed row count"
    return merged


def first_weakness_events(df, p3_sig):
    """First row where the frozen P3 signal fires (the 'qualifying persistent
    weakness signal' stops arm after)."""
    hit = df[p3_sig.values]
    if len(hit) == 0:
        return pd.DataFrame(columns=["episode_id"])
    first = hit.sort_values("seconds_since_entry").groupby("episode_id").first()
    return first.reset_index()


def build_events(df, p3_sig, ep_meta, bars):
    ev = first_weakness_events(df, p3_sig)
    if len(ev) == 0:
        return pd.DataFrame()
    ev = ev.merge(ep_meta[["entry_px", "direction"]], on=None, left_on="episode_id",
                  right_index=True, how="left", suffixes=("", "_m"))
    rows = []
    for r in ev.itertuples(index=False):
        sig_ts = int(r.observation_time)
        d = int(r.direction)
        struct_lvl = structural_low_high(bars, sig_ts, d)
        pb_ref = getattr(r, "pb_max_depth", np.nan)
        atr = getattr(r, "atr_at_flip")
        entry = float(r.entry_px)
        # prior recovered pullback extreme, expressed as an absolute price:
        # entry adverse excursion of pb_max_depth ATR against the trade,
        # falls back to the current structural low/high if no completed
        # (recovered) pullback has occurred yet.
        prior_pb_px = (entry - d * float(pb_ref) * atr) if pd.notna(pb_ref) and pb_ref > 0 else struct_lvl
        rows.append({
            "episode_id": r.episode_id, "direction": d, "sig_ts": sig_ts,
            "state_at_signal": r.smoothed_state, "entry_px": entry, "atr": float(atr),
            "trade_mfe_atr": float(r.trade_mfe_atr),
            "struct_low": struct_lvl if d == 1 else np.nan,
            "struct_high": struct_lvl if d == -1 else np.nan,
            "prior_pb_low": prior_pb_px if d == 1 else np.nan,
            "prior_pb_high": prior_pb_px if d == -1 else np.nan,
        })
    return pd.DataFrame(rows)


def simulate_one_stop(events, ep_base, tt_period, bars, rule, buffer_atr=0.10, mfe_frac=0.5):
    term_map = tt_period.set_index("episode_id")["true_terminal_ts"]
    recs = []
    for r in events.itertuples(index=False):
        ep = r.episode_id
        d = int(r.direction)
        entry = float(r.entry_px)
        atr = float(r.atr)
        sig_ts = int(r.sig_ts)
        end_ts = int(term_map.get(ep, sig_ts))
        e0 = float(ep_base["e0_pnl"].get(ep, np.nan))
        buf = buffer_atr * atr

        if rule == "A":
            lvl = (r.struct_low - buf) if d == 1 else (r.struct_high + buf)
        elif rule == "B":
            lvl = (r.prior_pb_low - buf) if d == 1 else (r.prior_pb_high + buf)
        elif rule == "C":
            lvl = entry + d * ((1 - mfe_frac) * r.trade_mfe_atr) * atr
        else:
            raise ValueError(rule)

        rec = {"episode_id": ep, "signal_time": sig_ts, "signal_state": r.state_at_signal,
               "direction": d, "stop_rule": rule, "initial_stop_price": float(lvl) if pd.notna(lvl) else np.nan,
               "every_stop_update": json.dumps([float(lvl)]) if pd.notna(lvl) else "[]",
               "e0_pnl": e0}

        if lvl is None or (isinstance(lvl, float) and np.isnan(lvl)):
            rec.update({"stop_activation_time": sig_ts, "stop_trigger_time": None,
                        "stop_fill_time": None, "stop_fill_price": None,
                        "recovery_time": None, "new_mfe_time": None,
                        "whether_recovery_preceded_stop": False,
                        "whether_new_mfe_preceded_stop": False, "net_pnl": e0})
            recs.append(rec)
            continue

        _, cur_px = sim_v2.next_1s_open(bars, sig_ts)
        invalid_at_entry = (d == 1 and cur_px <= lvl) or (d == -1 and cur_px >= lvl)
        rec["stop_activation_time"] = sig_ts
        if invalid_at_entry:
            fpx = cur_px
            pnl = (fpx - entry) * d * C.NQ_MULT - C.COMMISSION
            rec.update({"stop_trigger_time": sig_ts, "stop_fill_time": sig_ts,
                        "stop_fill_price": float(fpx), "recovery_time": None,
                        "new_mfe_time": None, "whether_recovery_preceded_stop": False,
                        "whether_new_mfe_preceded_stop": False, "net_pnl": pnl})
            recs.append(rec)
            continue

        stop_ts, stop_fill = sim_v2.detect_stop_hit(bars, sig_ts, end_ts, lvl, d)
        fav_target = entry + d * (r.trade_mfe_atr + 0.10) * atr
        lo_i = np.searchsorted(bars[:, 0], sig_ts, side="left")
        hi_i = np.searchsorted(bars[:, 0], end_ts, side="right")
        seg = bars[lo_i:hi_i]
        if d == 1:
            rec_mask = seg[:, 3] >= fav_target
        else:
            rec_mask = seg[:, 2] <= fav_target
        rec_ts = int(seg[np.argmax(rec_mask), 0]) if rec_mask.any() else None

        stopped = stop_ts is not None
        recovered_first = rec_ts is not None and (not stopped or rec_ts < stop_ts)
        if stopped and not recovered_first:
            pnl = (stop_fill - entry) * d * C.NQ_MULT - C.COMMISSION
            rec.update({"stop_trigger_time": stop_ts, "stop_fill_time": stop_ts,
                        "stop_fill_price": float(stop_fill)})
        else:
            pnl = e0
            rec.update({"stop_trigger_time": stop_ts if stopped else None,
                        "stop_fill_time": None, "stop_fill_price": None})
        rec.update({"recovery_time": rec_ts, "new_mfe_time": rec_ts,
                    "whether_recovery_preceded_stop": bool(recovered_first),
                    "whether_new_mfe_preceded_stop": bool(rec_ts is not None),
                    "net_pnl": pnl})
        recs.append(rec)
    return pd.DataFrame(recs)


# ── causal matched placebo ──────────────────────────────────────────────────
def add_match_buckets(df, edges):
    b = pd.DataFrame(index=df.index)
    b["session"] = np.where(df["is_rth"] == 1, "RTH", "ETH")
    b["direction"] = df["direction"].astype(int)
    b["smoothed_state"] = df["smoothed_state"]
    b["age_bucket"] = pd.cut(df["seconds_since_entry"], edges["age"], labels=False)
    b["regime_age_bucket"] = pd.cut(df["seconds_in_smoothed_state"], edges["regime_age"], labels=False)
    b["mfe_bucket"] = pd.cut(df["trade_mfe_atr"], edges["mfe"], labels=False)
    b["giveback_bucket"] = pd.cut(df["giveback_fraction"].fillna(0), edges["giveback"], labels=False)
    b["vol_bucket"] = pd.cut(df["realized_vol_60s_atr"].fillna(0), edges["vol"], labels=False)
    return b


def freeze_bucket_edges(train_df):
    q = lambda s, n: np.unique(np.nanquantile(s.values, np.linspace(0, 1, n + 1)))
    return {
        "age": np.array([0, 30, 60, 120, 240, 480, 1e9]),
        "regime_age": np.array([0, 10, 30, 60, 120, 1e9]),
        "mfe": q(train_df["trade_mfe_atr"].clip(lower=0), 4),
        "giveback": np.array([-1e-9, 0.1, 0.25, 0.5, 1.0, 1e9]),
        "vol": q(train_df["realized_vol_60s_atr"].fillna(0), 4),
    }


def matched_placebo(events, period_df, sm_period, edges, ep_meta, ep_base, tt_period, bars,
                     rule, buffer_atr, mfe_frac, seed=42):
    """For each real event, sample a DIFFERENT episode's checkpoint from the
    same bucket cell (causal state only), arm the SAME stop rule there."""
    rng = np.random.default_rng(seed)
    pool_bkt = add_match_buckets(sm_period, edges)
    pool_bkt["episode_id"] = sm_period["episode_id"].values
    pool_bkt["observation_time"] = sm_period["observation_time"].values
    pool_bkt["row_pos"] = np.arange(len(sm_period))

    real_bkt = add_match_buckets(events.merge(
        sm_period[["episode_id", "observation_time", "is_rth", "seconds_since_entry",
                   "seconds_in_smoothed_state", "giveback_fraction",
                   "realized_vol_60s_atr", "smoothed_state"]],
        left_on=["episode_id", "sig_ts"], right_on=["episode_id", "observation_time"],
        how="left"), edges)
    real_bkt["episode_id"] = events["episode_id"].values

    key_cols = ["session", "direction", "smoothed_state", "age_bucket",
                "regime_age_bucket", "mfe_bucket", "giveback_bucket", "vol_bucket"]
    pool_groups = pool_bkt.groupby(key_cols)["row_pos"].apply(list).to_dict()

    donor_rows = []
    for i, row in real_bkt.reset_index(drop=True).iterrows():
        key = tuple(row[k] for k in key_cols)
        candidates = pool_groups.get(key, [])
        candidates = [c for c in candidates if pool_bkt["episode_id"].iloc[c] != real_bkt["episode_id"].iloc[i]]
        if not candidates:
            continue
        pick = candidates[rng.integers(0, len(candidates))]
        donor_rows.append(pool_bkt.iloc[pick])

    if not donor_rows:
        return pd.DataFrame()
    donors = pd.DataFrame(donor_rows).reset_index(drop=True)
    donor_full = sm_period.iloc[donors["row_pos"].values].reset_index(drop=True)

    ep2 = ep_meta[["entry_px", "direction"]]
    donor_full = donor_full.merge(ep2, left_on="episode_id", right_index=True, how="left",
                                   suffixes=("", "_m"))
    assert "pb_max_depth" in donor_full.columns, \
        "donor_full missing pb_max_depth -- caller must load_pb_history(sm_period) first"

    rows = []
    for r in donor_full.itertuples(index=False):
        sig_ts = int(r.observation_time)
        d = int(r.direction)
        entry = float(r.entry_px)
        atr = float(r.atr_at_flip)
        struct_lvl = structural_low_high(bars, sig_ts, d)
        pb_ref = getattr(r, "pb_max_depth", np.nan)
        # mirror build_events' prior_pb_px EXACTLY (donor's own pb_max_depth,
        # not the current structural low/high) so the placebo runs the SAME
        # stop geometry as the real events, isolating timing from geometry.
        prior_pb_px = (entry - d * float(pb_ref) * atr) if pd.notna(pb_ref) and pb_ref > 0 else struct_lvl
        rows.append({
            "episode_id": r.episode_id, "direction": d, "sig_ts": sig_ts,
            "state_at_signal": r.smoothed_state, "entry_px": entry,
            "atr": atr, "trade_mfe_atr": float(r.trade_mfe_atr),
            "struct_low": struct_lvl if d == 1 else np.nan,
            "struct_high": struct_lvl if d == -1 else np.nan,
            "prior_pb_low": prior_pb_px if d == 1 else np.nan,
            "prior_pb_high": prior_pb_px if d == -1 else np.nan,
        })
    placebo_events = pd.DataFrame(rows)
    placebo_stop = simulate_one_stop(placebo_events, ep_base, tt_period, bars, rule,
                                      buffer_atr=buffer_atr, mfe_frac=mfe_frac)
    return placebo_stop


def main():
    print("=" * 70)
    print("Phase 4/5 -- structural stops + causal matched placebo")
    print("=" * 70)

    train, val, test, tt = C.prepare_base()
    bars = C.load_bars()
    sm = pd.read_parquet(C.RESULTS / "smoothed_state_checkpoints.parquet")

    frozen = json.load(open(C.RESULTS / "frozen_policy_config.json"))
    S_frozen = frozen["S_variant"]
    K_term_ck = BP.s_to_ck(frozen["K_terminal_seconds"])
    K_weak_ck = BP.s_to_ck(frozen["P3_K_weakening_seconds"])
    thr_p1a = frozen["P1a_thr"]
    feats0 = frozen["features_P1"]

    from lightgbm import LGBMRegressor
    m0 = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                        min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                        random_state=42, n_jobs=4, verbose=-1)
    m0.fit(C.Xmat(train, feats0), train["hold_advantage"].fillna(0).values)

    key_cols = ["episode_id", "observation_time"]
    val = val.merge(sm[key_cols + ["smoothed_state", "seconds_in_smoothed_state"]], on=key_cols, how="left")
    test = test.merge(sm[key_cols + ["smoothed_state", "seconds_in_smoothed_state"]], on=key_cols, how="left")
    val = load_pb_history(val)
    test = load_pb_history(test)

    ep_base_val, ep_meta_val = C.prep_period(val, tt, "val")
    ep_base_test, ep_meta_test = C.prep_period(test, tt, "test")

    def p3_signal(df):
        s = m0.predict(C.Xmat(df, feats0))
        weak_now = C.elig(df) & (pd.Series(s, index=df.index) < thr_p1a)
        codes = df.groupby("episode_id").ngroup().values
        run = C.consecutive_run(weak_now.values.astype(bool), codes)
        struct = BP.build_structural_flags(df)
        Karr = np.full(len(df), K_weak_ck)
        Tarr = np.full(len(df), K_term_ck)
        return BP.state_gated_signal(df, weak_now, run, Karr, Tarr, struct[S_frozen])

    sig_val = p3_signal(val)
    sig_test = p3_signal(test)

    events_val = build_events(val, sig_val, ep_meta_val, bars)
    events_test = build_events(test, sig_test, ep_meta_test, bars)
    print(f"  weakness-arm events: val={len(events_val)}  test={len(events_test)}")

    # ── select stop rule + buffer/mfe_frac on validation ────────────────────
    tt_val = tt[tt["period"] == "val"]
    best = (-1e9, None, None, None)
    for rule in ["A", "B", "C"]:
        if rule == "C":
            for mf in MFE_GIVEBACK_FRAC_CANDIDATES:
                sr = simulate_one_stop(events_val, ep_base_val, tt_val, bars, rule, mfe_frac=mf)
                d = float((sr["net_pnl"] - sr["e0_pnl"]).mean())
                print(f"  [val] rule={rule} mfe_frac={mf}: delta vs E0 = ${d:+.2f} (n={len(sr)})")
                if d > best[0]:
                    best = (d, rule, None, mf)
        else:
            for buf in BUFFER_ATR_CANDIDATES:
                sr = simulate_one_stop(events_val, ep_base_val, tt_val, bars, rule, buffer_atr=buf)
                d = float((sr["net_pnl"] - sr["e0_pnl"]).mean())
                print(f"  [val] rule={rule} buffer={buf}: delta vs E0 = ${d:+.2f} (n={len(sr)})")
                if d > best[0]:
                    best = (d, rule, buf, None)

    _, rule_frozen, buf_frozen, mfe_frozen = best
    buf_frozen = buf_frozen if buf_frozen is not None else 0.10
    mfe_frozen = mfe_frozen if mfe_frozen is not None else 0.50
    print(f"  FROZEN stop geometry: rule={rule_frozen} buffer={buf_frozen} mfe_frac={mfe_frozen} (val delta ${best[0]:+.2f})")

    # ── run frozen stop on TEST ──────────────────────────────────────────────
    tt_test = tt[tt["period"] == "test"]
    stop_test = simulate_one_stop(events_test, ep_base_test, tt_test, bars, rule_frozen,
                                   buffer_atr=buf_frozen, mfe_frac=mfe_frozen)
    stop_test["persistence_duration"] = frozen["P3_K_weakening_seconds"]
    stop_test.to_parquet(C.RESULTS / "structural_stop_trades.parquet", index=False)

    imm_pnl_test = C.policy_pnl(test, sig_test, ep_base_test, ep_meta_test, bars)
    ep_ids_stop = stop_test["episode_id"].values
    stop_ep_res = stop_test[["episode_id", "net_pnl", "e0_pnl"]].copy()
    stop_ep_res["immediate_exit_pnl"] = imm_pnl_test.reindex(ep_ids_stop).values
    stop_ep_res.to_parquet(C.RESULTS / "structural_stop_episode_results.parquet", index=False)

    n_changed_vs_immediate = int((stop_test["net_pnl"] != stop_ep_res["immediate_exit_pnl"]).sum())
    assert n_changed_vs_immediate > 0, "structural stop changed ZERO episodes vs immediate exit"

    d_e0 = float((stop_test["net_pnl"] - stop_test["e0_pnl"]).mean())
    d_imm = float((stop_test["net_pnl"] - stop_ep_res["immediate_exit_pnl"]).mean())
    metrics = {
        "stop_rule": rule_frozen, "buffer_atr": buf_frozen, "mfe_giveback_frac": mfe_frozen,
        "n_events": len(stop_test), "mean_pnl": round(float(stop_test["net_pnl"].mean()), 2),
        "delta_vs_e0": round(d_e0, 2), "delta_vs_immediate_exit": round(d_imm, 2),
        "n_changed_vs_immediate_exit": n_changed_vs_immediate,
        "pct_recovered_first": round(float(stop_test["whether_recovery_preceded_stop"].mean()), 3),
        "pct_new_mfe_first": round(float(stop_test["whether_new_mfe_preceded_stop"].mean()), 3),
    }
    pd.DataFrame([metrics]).to_parquet(C.RESULTS / "structural_stop_metrics.parquet", index=False)
    print(f"  TEST structural stop: n={metrics['n_events']} delta_vs_E0=${d_e0:+.2f} "
          f"delta_vs_immediate=${d_imm:+.2f} changed_vs_immediate={n_changed_vs_immediate}")

    # ── matched placebo (test) ───────────────────────────────────────────────
    edges = freeze_bucket_edges(train.merge(sm[key_cols + ["smoothed_state", "seconds_in_smoothed_state"]],
                                             on=key_cols, how="left"))
    placebo_test = matched_placebo(events_test, test, test, edges, ep_meta_test, ep_base_test,
                                    tt_test, bars, rule_frozen, buf_frozen, mfe_frozen)
    if len(placebo_test):
        d_placebo = float((placebo_test["net_pnl"] - placebo_test["e0_pnl"]).mean())
        placebo_test.to_parquet(C.RESULTS / "matched_stop_placebo.parquet", index=False)
        real_minus_placebo = d_e0 - d_placebo
        lo, hi = C.paired_bootstrap_ci((stop_test["net_pnl"] - stop_test["e0_pnl"]).values -
                                        np.pad((placebo_test["net_pnl"] - placebo_test["e0_pnl"]).values,
                                               (0, max(0, len(stop_test) - len(placebo_test))), constant_values=np.nan)[:len(stop_test)])
        print(f"  matched placebo: n={len(placebo_test)} delta_vs_own_E0=${d_placebo:+.2f}  "
              f"real_minus_placebo=${real_minus_placebo:+.2f}")
        C.savej({
            "real_stop_delta_vs_e0": round(d_e0, 2),
            "matched_placebo_delta_vs_e0": round(d_placebo, 2),
            "real_minus_placebo": round(real_minus_placebo, 2),
            "bootstrap_ci_lo": round(lo, 2) if not np.isnan(lo) else None,
            "bootstrap_ci_hi": round(hi, 2) if not np.isnan(hi) else None,
            "n_real_events": len(stop_test), "n_placebo_events": len(placebo_test),
            "verdict_pass": bool(d_e0 > d_placebo),
        }, C.RESULTS / "stop_vs_placebo_summary.json")
    else:
        print("  WARNING: no matched placebo donors found (bucket cells empty)")

    print("done.")


if __name__ == "__main__":
    main()
