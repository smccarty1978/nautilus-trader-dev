"""
Phase 2/3/8 -- build the narrow policy set (P0, P1a, P1b, P2-P7) and the
structural-confirmation variants (S0-S4), select every free choice on
VALIDATION ONLY, and freeze the winning configuration.

Weakness score: reuses the P1 fitted-Q model (M0, LOCAL_CANDIDATES features)
scored against hold_advantage, thresholded at the frozen v2 value (same
"weak_now" trigger P1 already uses) -- per spec: "Use the existing fitted-Q
... scores plus smoothed state."

Segment attribution (direction, RTH/ETH) is fixed at EPISODE ENTRY (first
checkpoint), matching v2's existing convention -- this makes P4/P5/P6's
per-segment threshold selection an EXACT partition of validation episodes
(no row-level segment-switching ambiguity mid-episode), not an approximation.

K_terminal and the structural-confirmation variant (S) are selected once via
P3 and then SHARED by P4-P7 (coordinate-wise selection, not a full joint grid
over every axis at once) -- documented conservative assumption to keep the
grid compact per the spec's repeated "compact set" instruction.

Writes (Phase 8 freeze deliverables):
  results/validation_policy_grid.parquet
  results/frozen_policy_config.json
  results/policy_thresholds.json
  results/model_hashes.json
"""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import base as C
import sim_v2

V2_THR_P1A = 125.23300123309254

# ── candidate grids (seconds -> checkpoints @ 5s spacing) ───────────────────
K_GLOBAL_S = [10, 20, 30, 45]
K_WEAK_S = [15, 20, 30, 45]
K_TERM_S = [5, 10, 15]
K_LONG_S = [20, 30, 45]
K_SHORT_S = [5, 10, 20, 30]
K_RTH_S = [20, 30, 45]
K_ETH_S = [5, 10, 20, 30]
K_SEG_S = [10, 20, 30]           # P6 compact per-segment candidate set

MIN_SEG_EPISODES = 50            # fallback threshold for P6 segment sizing


def s_to_ck(s):
    return int(round(s / 5))


def train_m0(train_df, feats=None):
    feats = feats or [f for f in C.LOCAL_CANDIDATES if f in train_df.columns]
    X = C.Xmat(train_df, feats)
    y = train_df["hold_advantage"].fillna(0).values
    m = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                       min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                       random_state=42, n_jobs=4, verbose=-1)
    m.fit(X, y)
    return m, feats


def ev(df, sig, ep_base, ep_meta, bars):
    return float(C.policy_pnl(df, sig, ep_base, ep_meta, bars).mean())


def build_structural_flags(df: pd.DataFrame) -> pd.DataFrame:
    """S0-S4, causal, from already-loaded MTF context columns."""
    out = pd.DataFrame(index=df.index)
    b3 = (df.get("structure_break_against_3m", pd.Series(0, index=df.index)).fillna(0) > 0.5)
    b5 = (df.get("structure_break_against_5m", pd.Series(0, index=df.index)).fillna(0) > 0.5)
    out["S0"] = False
    out["S1"] = b3
    out["S2"] = b5
    out["S3"] = b3 | b5
    codes = df.groupby("episode_id").ngroup().values
    lw_run = C.consecutive_run(df["local_weak"].values.astype(bool), codes)
    fail_recover = df["giveback_fraction"].fillna(0) > 0.10
    out["S4"] = (lw_run >= 4) & fail_recover.values
    return out


def state_gated_signal(df, weak_now, run, K_weak_arr, K_term_arr, S_flag,
                        modulate_by_structure=False, reduce_ck=1, extend_ck=1):
    """Generic P3-style state-gated exit signal.
    PROLIFIC/ORDINARY: never fire. HEALTHY: fire iff S_flag. WEAKENING: fire
    when run(weak_now) >= K_weak_arr (optionally +-modulated by S_flag, for
    P7). TERMINAL: fire when run(weak_now) >= K_term_arr (typically small)."""
    elig_ = C.elig(df)
    st = df["smoothed_state"].values
    if modulate_by_structure:
        k_eff = np.where(S_flag.values, np.maximum(K_weak_arr - reduce_ck, 1),
                          K_weak_arr + extend_ck)
    else:
        k_eff = K_weak_arr
    weakening_fire = elig_.values & (st == "WEAKENING") & (run >= k_eff)
    terminal_fire = elig_.values & (st == "TERMINAL") & (run >= K_term_arr)
    healthy_fire = elig_.values & (st == "HEALTHY_ESTABLISHED") & S_flag.values
    sig = weakening_fire | terminal_fire | healthy_fire
    return pd.Series(sig, index=df.index)


def episode_K_map(ep_index, seg_of_ep, k_by_seg, default_ck):
    m = ep_index.map(lambda e: k_by_seg.get(seg_of_ep.get(e), default_ck))
    return m.values.astype(np.int32)


def main():
    print("=" * 70)
    print("Phase 2/3/8 -- build policy candidates + structural confirmation")
    print("=" * 70)

    train, val, test, tt = C.prepare_base()
    bars = C.load_bars()

    sm = pd.read_parquet(C.RESULTS / "smoothed_state_checkpoints.parquet")
    key_cols = ["episode_id", "observation_time"]
    for df_name, df in [("train", train), ("val", val), ("test", test)]:
        merged = df.merge(sm[key_cols + ["smoothed_state"]], on=key_cols, how="left")
        assert len(merged) == len(df), f"{df_name}: smoothed-state merge changed row count"
        if df_name == "train":
            train = merged
        elif df_name == "val":
            val = merged
        else:
            test = merged

    # NOTE: this script selects every free choice on VALIDATION ONLY. Test-period
    # data/scores/signals are deliberately never computed here -- exact_replay.py
    # is the sole place test is scored, using only the frozen config this script
    # writes. (A prior draft computed unused test-period intermediates here;
    # removed per lookahead-auditor WARNING to eliminate any risk of a future
    # edit accidentally wiring test into a selection loop.)
    ep_base_val, ep_meta_val = C.prep_period(val, tt, "val")
    e0_val = float(ep_base_val["e0_pnl"].mean())
    print(f"  E0 val=${e0_val:.2f}")

    # ── weakness score (fitted-Q, same recipe as P1) ────────────────────────
    m0, feats0 = train_m0(train)
    s_val = m0.predict(C.Xmat(val, feats0))
    weak_now_val = C.elig(val) & (pd.Series(s_val, index=val.index) < V2_THR_P1A)

    # P1b: independent reselection
    best_ev, best_thr = -1e9, None
    for q in np.arange(10, 91, 5):
        thr = np.percentile(s_val, q)
        sig = C.elig(val) & (pd.Series(s_val, index=val.index) < thr)
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        if e > best_ev:
            best_ev, best_thr = e, thr
    thr_p1b = float(best_thr)

    grid_rows = []

    def log(policy, param, thr, val_ev):
        grid_rows.append({"policy": policy, "param": str(param), "thr": float(thr),
                           "val_ev": round(val_ev, 3)})

    log("P1a", "frozen", V2_THR_P1A, ev(val, weak_now_val, ep_base_val, ep_meta_val, bars))
    log("P1b", "reselected", thr_p1b, best_ev)

    # ── P2: global persistence ──────────────────────────────────────────────
    codes_val = val.groupby("episode_id").ngroup().values
    run_val = C.consecutive_run(weak_now_val.values.astype(bool), codes_val)

    best_ev, best_K = -1e9, K_GLOBAL_S[0]
    for Ks in K_GLOBAL_S:
        ck = s_to_ck(Ks)
        sig = C.elig(val) & (pd.Series(run_val >= ck, index=val.index))
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        log("P2", f"{Ks}s", ck, e)
        if e > best_ev:
            best_ev, best_K = e, Ks
    K_p2 = best_K
    print(f"  P2 global persistence: K={K_p2}s (val ev ${best_ev:.2f})")

    # ── Structural confirmation variant (S) -- selected via P3 baseline ─────
    struct_val = build_structural_flags(val)
    K_weak_base_ck = s_to_ck(30)   # baseline while selecting S / K_terminal
    K_term_base_ck = s_to_ck(10)

    best_ev, best_S = -1e9, "S0"
    for sname in ["S0", "S1", "S2", "S3", "S4"]:
        Karr = np.full(len(val), K_weak_base_ck)
        Tarr = np.full(len(val), K_term_base_ck)
        sig = state_gated_signal(val, weak_now_val, run_val, Karr, Tarr, struct_val[sname])
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        log("S_variant", sname, 0, e)
        if e > best_ev:
            best_ev, best_S = e, sname
    S_frozen = best_S
    print(f"  structural-confirmation variant: {S_frozen} (val ev ${best_ev:.2f})")

    # ── K_terminal (coordinate-wise, K_weakening held at baseline) ──────────
    best_ev, best_Kt = -1e9, K_TERM_S[0]
    for Ks in K_TERM_S:
        ck = s_to_ck(Ks)
        Karr = np.full(len(val), K_weak_base_ck)
        Tarr = np.full(len(val), ck)
        sig = state_gated_signal(val, weak_now_val, run_val, Karr, Tarr, struct_val[S_frozen])
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        log("P3_Kterm", f"{Ks}s", ck, e)
        if e > best_ev:
            best_ev, best_Kt = e, Ks
    K_term_ck = s_to_ck(best_Kt)
    print(f"  K_terminal: {best_Kt}s")

    # ── P3: K_weakening (coordinate-wise, K_terminal now frozen) ────────────
    best_ev, best_Kw = -1e9, K_WEAK_S[0]
    for Ks in K_WEAK_S:
        ck = s_to_ck(Ks)
        Karr = np.full(len(val), ck)
        Tarr = np.full(len(val), K_term_ck)
        sig = state_gated_signal(val, weak_now_val, run_val, Karr, Tarr, struct_val[S_frozen])
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        log("P3", f"{Ks}s", ck, e)
        if e > best_ev:
            best_ev, best_Kw = e, Ks
    K_p3_ck = s_to_ck(best_Kw)
    print(f"  P3 state-gated persistence: K_weakening={best_Kw}s, K_terminal={best_Kt}s, S={S_frozen}  (val ev ${best_ev:.2f})")
    ev_p3_val = best_ev

    # ── segment attribution (fixed at episode entry) ────────────────────────
    ep_dir_val = ep_meta_val["direction"]
    ep_rth_val = val.groupby("episode_id")["is_rth"].first()

    def make_K_arr(df, ep_seg, k_by_seg, default_ck):
        ep_ids = df["episode_id"]
        k_map = ep_seg.map(lambda s: k_by_seg.get(s, default_ck))
        return ep_ids.map(k_map).fillna(default_ck).values.astype(np.int32)

    # ── P4: long/short persistence ───────────────────────────────────────────
    def select_seg_K(seg_mask, candidates, label):
        eps = seg_mask[seg_mask].index
        best_ev, best_K = -1e9, candidates[0]
        idx_mask = val["episode_id"].isin(eps).values
        for Ks in candidates:
            ck = s_to_ck(Ks)
            Karr = np.where(idx_mask, ck, 10 ** 6)  # effectively never fires outside segment
            Tarr = np.full(len(val), K_term_ck)
            sig_full = state_gated_signal(val, weak_now_val, run_val, Karr, Tarr, struct_val[S_frozen])
            sig_seg = sig_full & pd.Series(idx_mask, index=val.index)
            sub_eps = eps
            e0_sub = float(ep_base_val["e0_pnl"].loc[ep_base_val["e0_pnl"].index.isin(sub_eps)].mean())
            pnl = C.policy_pnl(val, sig_seg, ep_base_val, ep_meta_val, bars)
            e = float(pnl.loc[pnl.index.isin(sub_eps)].mean())
            log(f"seg_{label}", f"{Ks}s", ck, e)
            if e > best_ev:
                best_ev, best_K = e, Ks
        return best_K, best_ev

    K_long, ev_long = select_seg_K(ep_dir_val == 1, K_LONG_S, "long")
    K_short, ev_short = select_seg_K(ep_dir_val == -1, K_SHORT_S, "short")
    print(f"  P4 direction persistence: long={K_long}s (val ${ev_long:.2f}), short={K_short}s (val ${ev_short:.2f})")

    # ── P5: RTH/ETH persistence ──────────────────────────────────────────────
    K_rth, ev_rth = select_seg_K(ep_rth_val == 1, K_RTH_S, "rth")
    K_eth, ev_eth = select_seg_K(ep_rth_val != 1, K_ETH_S, "eth")
    print(f"  P5 session persistence: RTH={K_rth}s (val ${ev_rth:.2f}), ETH={K_eth}s (val ${ev_eth:.2f})")

    # ── P6: direction x session (compact candidate set, fallback if undersized) ──
    seg_defs = {
        "RTH_long": (ep_rth_val == 1) & (ep_dir_val == 1),
        "RTH_short": (ep_rth_val == 1) & (ep_dir_val == -1),
        "ETH_long": (ep_rth_val != 1) & (ep_dir_val == 1),
        "ETH_short": (ep_rth_val != 1) & (ep_dir_val == -1),
    }
    K_p6 = {}
    for seg_name, mask in seg_defs.items():
        n_eps = int(mask.sum())
        if n_eps < MIN_SEG_EPISODES:
            fallback = K_long if "long" in seg_name else K_short
            K_p6[seg_name] = fallback
            print(f"  P6 {seg_name}: n={n_eps} < {MIN_SEG_EPISODES}, falling back to direction-only K={fallback}s")
            continue
        Kb, evb = select_seg_K(mask, K_SEG_S, f"p6_{seg_name}")
        K_p6[seg_name] = Kb
        print(f"  P6 {seg_name}: n={n_eps}, K={Kb}s (val ${evb:.2f})")

    # ── P7: best granularity (P3 vs P4 vs P5 vs P6) + structural modulation ──
    ev_p4_full = ev(val, state_gated_signal(
        val, weak_now_val, run_val,
        make_K_arr(val, ep_dir_val.map({1: "long", -1: "short"}),
                   {"long": s_to_ck(K_long), "short": s_to_ck(K_short)}, K_p3_ck),
        np.full(len(val), K_term_ck), struct_val[S_frozen]), ep_base_val, ep_meta_val, bars)
    ev_p5_full = ev(val, state_gated_signal(
        val, weak_now_val, run_val,
        make_K_arr(val, ep_rth_val.map({1: "rth", 0: "eth"}),
                   {"rth": s_to_ck(K_rth), "eth": s_to_ck(K_eth)}, K_p3_ck),
        np.full(len(val), K_term_ck), struct_val[S_frozen]), ep_base_val, ep_meta_val, bars)
    seg_label_val = pd.Series(np.where(ep_rth_val.reindex(val["episode_id"]).values == 1,
                                        np.where(ep_dir_val.reindex(val["episode_id"]).values == 1, "RTH_long", "RTH_short"),
                                        np.where(ep_dir_val.reindex(val["episode_id"]).values == 1, "ETH_long", "ETH_short")),
                               index=val.index)
    K_p6_arr_val = seg_label_val.map(lambda s: s_to_ck(K_p6[s])).values.astype(np.int32)
    ev_p6_full = ev(val, state_gated_signal(
        val, weak_now_val, run_val, K_p6_arr_val, np.full(len(val), K_term_ck), struct_val[S_frozen]),
        ep_base_val, ep_meta_val, bars)

    granularity_evs = {"P3": ev_p3_val, "P4": ev_p4_full, "P5": ev_p5_full, "P6": ev_p6_full}
    winner = max(granularity_evs, key=lambda k: granularity_evs[k])
    print(f"  P7 base granularity winner: {winner}  ({granularity_evs})")
    for k, v in granularity_evs.items():
        log("P7_granularity_candidate", k, 0, v)

    C.savej({"granularity_val_ev": granularity_evs, "winner": winner},
            C.RESULTS / "p7_granularity_selection.json")

    # ── freeze everything ────────────────────────────────────────────────────
    grid_df = pd.DataFrame(grid_rows)
    grid_df.to_parquet(C.RESULTS / "validation_policy_grid.parquet", index=False)

    frozen = {
        "weak_now_model": "M0 fitted-Q (LOCAL_CANDIDATES, LGBMRegressor, seed=42)",
        "P1a_thr": V2_THR_P1A,
        "P1b_thr": thr_p1b,
        "P2_K_seconds": K_p2,
        "S_variant": S_frozen,
        "K_terminal_seconds": best_Kt,
        "P3_K_weakening_seconds": best_Kw,
        "P4_K_long_seconds": K_long,
        "P4_K_short_seconds": K_short,
        "P5_K_rth_seconds": K_rth,
        "P5_K_eth_seconds": K_eth,
        "P6_K_by_segment_seconds": K_p6,
        "P6_min_segment_episodes": MIN_SEG_EPISODES,
        "P7_granularity_winner": winner,
        "P7_structural_modulation_reduce_ck": 1,
        "P7_structural_modulation_extend_ck": 1,
        "features_P1": feats0,
    }
    C.savej(frozen, C.RESULTS / "frozen_policy_config.json")
    C.savej({"P1a_thr": V2_THR_P1A, "P1b_thr": thr_p1b, "P2_K_s": K_p2,
             "K_terminal_s": best_Kt, "P3_K_weak_s": best_Kw,
             "P4_K_long_s": K_long, "P4_K_short_s": K_short,
             "P5_K_rth_s": K_rth, "P5_K_eth_s": K_eth,
             "P6_K_by_segment_s": K_p6, "S_variant": S_frozen},
            C.RESULTS / "policy_thresholds.json")

    feat_hash = hashlib.sha256(",".join(feats0).encode()).hexdigest()[:16]
    pred_hash = hashlib.sha256(np.round(s_val, 4).tobytes()).hexdigest()[:16]
    C.savej({"M0_feature_list_hash": feat_hash, "M0_val_prediction_hash": pred_hash,
             "n_features": len(feats0), "lgbm_params": {
                 "n_estimators": 300, "learning_rate": 0.05, "max_depth": 4,
                 "min_child_samples": 100, "num_leaves": 15, "reg_lambda": 10.0,
                 "random_state": 42}},
            C.RESULTS / "model_hashes.json")

    print("done.")


if __name__ == "__main__":
    main()
