"""
Phase 3/4 -- pure deterministic state-only policies (P0-P9). NO fitted-Q
anywhere. All timing gates use the FROZEN smoothed_state stream's own dwell
counter (`seconds_in_smoothed_state`, per-state clock) or a combined
WEAKENING-or-worse run-length (for P3, which spec explicitly separates from
P4's per-state delays). All free choices are selected on VALIDATION ONLY.

Session/direction attribution is fixed at episode entry (first checkpoint's
is_rth / direction) -- an exact partition, no outcome leakage, matching the
convention already used (and audited clean) in contextual_runner_exit_v3.

Writes:
  results/validation_policy_grid.parquet
  results/frozen_policy_config.json
  results/policy_thresholds.json
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

import base as C

WEAK = ["WEAKENING"]
TERM = ["TERMINAL"]
WEAK_OR_WORSE = ["WEAKENING", "TERMINAL"]

P3_K_S = [5, 10, 15, 20, 30, 45]
P4_KW_S = [10, 15, 20, 30, 45]
P4_KT_S = [0, 5, 10]
P7_RTH_WEAK = [None, 20, 30, 45]     # None == disabled
P7_RTH_TERM = [None, 0, 5]           # None == disabled, 0 == immediate
# Spec lists ETH WEAKENING/TERMINAL grids with no "disabled" option (implicitly
# assuming ETH always benefits from intervention). Per "Do not assume this --
# select on validation," a `None` (disabled) candidate is ADDED to both ETH
# grids as a documented deviation: if validation shows ETH is better left on
# E0 too, the selection must be free to discover that, not be forced into a
# worse-than-E0 intervention because the candidate set excluded "do nothing."
P7_ETH_WEAK = [None, 5, 10, 15, 20, 30]
P7_ETH_TERM = [None, 0, 5, 10]
MIN_SEG_EPISODES = 50


def signal_state_delay(df, target_states, delay_s, mode="dwell"):
    """mode='dwell': per-state clock (seconds_in_smoothed_state), used when a
    policy's delay is specific to ONE state (P4/P5/P6/P7 architecture).
    mode='combined': consecutive-run across the WHOLE target_states family
    (used only by P3, which spec defines as "WEAKENING or worse persists
    continuously" -- a combined clock that survives a WEAKENING->TERMINAL
    transition without resetting, unlike the per-state dwell clock)."""
    if delay_s is None:
        return pd.Series(False, index=df.index)
    elig_ = C.elig(df)
    in_target = df["smoothed_state"].isin(target_states)
    if mode == "dwell":
        cond = in_target & (df["seconds_in_smoothed_state"] >= delay_s)
    else:
        codes = df.groupby("episode_id").ngroup().values
        run_ck = C.consecutive_run(in_target.values.astype(bool), codes)
        cond = in_target & (run_ck * C.CHECKPOINT_S >= delay_s)
    return elig_ & cond


def p4_signal(df, Kw, Kt):
    return signal_state_delay(df, WEAK, Kw, "dwell") | signal_state_delay(df, TERM, Kt, "dwell")


def session_gated_signal(df, rth_weak, rth_term, eth_weak, eth_term):
    is_rth = df["is_rth"] == 1
    rth_sig = (signal_state_delay(df, WEAK, rth_weak, "dwell") |
               signal_state_delay(df, TERM, rth_term, "dwell"))
    eth_sig = (signal_state_delay(df, WEAK, eth_weak, "dwell") |
               signal_state_delay(df, TERM, eth_term, "dwell"))
    return (is_rth & rth_sig) | (~is_rth & eth_sig)


def p9_signal(df, ep_meta, p9_config):
    """Shared P9 (session x direction, with fallback) signal builder --
    used by build_deterministic_policies.py (selection), exact_replay.py
    (frozen test replay) AND run_matched_controls.py / simulate_state_stops.py
    (as the reference/arming policy) so all three always agree on what P9
    actually is. P7 is NOT a safe "reference intervening policy" for controls
    -- validation legitimately selected "disabled" for both sessions, so P7
    fires on zero episodes; P9 is the one policy that actually intervenes."""
    is_rth = df["is_rth"] == 1
    ep_dir = ep_meta["direction"]
    long_mask = df["episode_id"].map(ep_dir) == 1

    def seg_sig(cfg):
        return (signal_state_delay(df, WEAK, cfg["weak"], "dwell") |
                signal_state_delay(df, TERM, cfg["term"], "dwell"))

    sig = pd.Series(False, index=df.index)
    sig |= is_rth & long_mask & seg_sig(p9_config["RTH_long"])
    sig |= is_rth & ~long_mask & seg_sig(p9_config["RTH_short"])
    sig |= ~is_rth & long_mask & seg_sig(p9_config["ETH_long"])
    sig |= ~is_rth & ~long_mask & seg_sig(p9_config["ETH_short"])
    return sig


def ev(df, sig, ep_base, ep_meta, bars):
    return float(C.policy_pnl(df, sig, ep_base, ep_meta, bars).mean())


def main():
    print("=" * 70)
    print("Phase 3/4 -- deterministic state-only policies (validation selection)")
    print("=" * 70)

    train, val, test, tt = C.load_base()
    bars = C.load_bars()
    ep_base_val, ep_meta_val = C.prep_period(val, tt, "val")
    e0_val = float(ep_base_val["e0_pnl"].mean())
    print(f"  E0 val = ${e0_val:.4f}")

    grid_rows = []

    def log(policy, param, val_ev):
        grid_rows.append({"policy": policy, "param": str(param), "val_ev": round(val_ev, 4)})

    # P1 / P2 -- no free parameters
    ev_p1 = ev(val, signal_state_delay(val, TERM, 0), ep_base_val, ep_meta_val, bars)
    ev_p2 = ev(val, signal_state_delay(val, WEAK, 0), ep_base_val, ep_meta_val, bars)
    log("P1_immediate_terminal", "n/a", ev_p1)
    log("P2_immediate_weakening", "n/a", ev_p2)
    print(f"  P1 immediate TERMINAL: val ev ${ev_p1:.2f}  (delta ${ev_p1-e0_val:+.2f})")
    print(f"  P2 immediate WEAKENING: val ev ${ev_p2:.2f}  (delta ${ev_p2-e0_val:+.2f})")

    # P3 -- combined WEAKENING-or-worse persistence
    best_ev, best_K = -1e9, P3_K_S[0]
    for K in P3_K_S:
        sig = signal_state_delay(val, WEAK_OR_WORSE, K, "combined")
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        log("P3", f"{K}s", e)
        if e > best_ev:
            best_ev, best_K = e, K
    K_p3 = best_K
    print(f"  P3 combined delay: K={K_p3}s (val ev ${best_ev:.2f})")

    # P4 -- coordinate-wise: freeze Kw at a mid default while selecting Kt, then vice versa
    Kw_default = 20
    best_ev, best_Kt = -1e9, P4_KT_S[0]
    for Kt in P4_KT_S:
        sig = p4_signal(val, Kw_default, Kt)
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        log("P4_Kterm", f"{Kt}s", e)
        if e > best_ev:
            best_ev, best_Kt = e, Kt
    Kt_p4 = best_Kt
    best_ev, best_Kw = -1e9, P4_KW_S[0]
    for Kw in P4_KW_S:
        sig = p4_signal(val, Kw, Kt_p4)
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        log("P4_Kweak", f"{Kw}s", e)
        if e > best_ev:
            best_ev, best_Kw = e, Kw
    Kw_p4 = best_Kw
    ev_p4 = ev(val, p4_signal(val, Kw_p4, Kt_p4), ep_base_val, ep_meta_val, bars)
    print(f"  P4: Kweak={Kw_p4}s Kterm={Kt_p4}s (val ev ${ev_p4:.2f})")

    # P5 -- ETH-only P4-style; RTH stays on E0
    def p5_signal(df, Kw, Kt):
        eth_sig = p4_signal(df, Kw, Kt)
        return (df["is_rth"] != 1) & eth_sig

    val_eth = val[val["is_rth"] != 1]
    best_ev, best_Kw5, best_Kt5 = -1e9, P4_KW_S[0], P4_KT_S[0]
    for Kt in P4_KT_S:
        for Kw in P4_KW_S:
            sig = p5_signal(val, Kw, Kt)
            e = ev(val, sig, ep_base_val, ep_meta_val, bars)
            log("P5", f"Kw{Kw}_Kt{Kt}", e)
            if e > best_ev:
                best_ev, best_Kw5, best_Kt5 = e, Kw, Kt
    print(f"  P5 (ETH-only): Kweak={best_Kw5}s Kterm={best_Kt5}s (val ev ${best_ev:.2f})")

    # P6 -- RTH terminal-only (ignore weakening), ETH full P4-style
    def p6_signal(df, eth_Kw, eth_Kt, rth_Kt):
        is_rth = df["is_rth"] == 1
        rth_sig = signal_state_delay(df, TERM, rth_Kt, "dwell")
        eth_sig = p4_signal(df, eth_Kw, eth_Kt)
        return (is_rth & rth_sig) | (~is_rth & eth_sig)

    best_ev, best_p6 = -1e9, (Kw_p4, Kt_p4, 0)
    for rth_Kt in [0, 5, 10]:
        sig = p6_signal(val, best_Kw5, best_Kt5, rth_Kt)
        e = ev(val, sig, ep_base_val, ep_meta_val, bars)
        log("P6_rthKterm", f"{rth_Kt}s", e)
        if e > best_ev:
            best_ev, best_p6 = e, (best_Kw5, best_Kt5, rth_Kt)
    print(f"  P6: ETH(Kweak={best_p6[0]}s,Kterm={best_p6[1]}s) RTH(Kterm={best_p6[2]}s) (val ev ${best_ev:.2f})")

    # P7 -- fully independent session-specific timing (RTH and ETH truly separable:
    # exclusive is_rth partition, so selecting each session's params to maximize
    # EV *within that session's own episodes* is an exact decomposition of the
    # overall EV, not an approximation).
    ep_dir_val = C.make_ep_meta(val)["direction"]
    ep_rth_val = val.groupby("episode_id")["is_rth"].first()
    ep_base_dict = ep_base_val["e0_pnl"]

    def select_session_grid(session_mask, weak_grid, term_grid, label):
        eps = session_mask[session_mask].index
        idx_mask = val["episode_id"].isin(eps).values
        best_ev, best_w, best_t = -1e9, weak_grid[0], term_grid[0]
        for t in term_grid:
            for w in weak_grid:
                sig_full = ((signal_state_delay(val, WEAK, w, "dwell") if w is not None else pd.Series(False, index=val.index)) |
                            (signal_state_delay(val, TERM, t, "dwell") if t is not None else pd.Series(False, index=val.index)))
                sig_seg = sig_full & pd.Series(idx_mask, index=val.index)
                pnl = C.policy_pnl(val, sig_seg, ep_base_val, ep_meta_val, bars)
                e = float(pnl.loc[pnl.index.isin(eps)].mean())
                log(f"P7_{label}", f"w{w}_t{t}", e)
                if e > best_ev:
                    best_ev, best_w, best_t = e, w, t
        return best_w, best_t, best_ev

    rth_w, rth_t, rth_ev = select_session_grid(ep_rth_val == 1, P7_RTH_WEAK, P7_RTH_TERM, "RTH")
    eth_w, eth_t, eth_ev = select_session_grid(ep_rth_val != 1, P7_ETH_WEAK, P7_ETH_TERM, "ETH")
    print(f"  P7: RTH(weak={rth_w},term={rth_t}) val ev ${rth_ev:.2f} | "
          f"ETH(weak={eth_w},term={eth_t}) val ev ${eth_ev:.2f}")

    # P8 -- direction diagnostic on top of P7's session logic (report only;
    # adopt direction-split timing ONLY if it clearly beats session-only)
    def select_dir_grid(seg_mask, weak_grid, term_grid, label):
        eps = seg_mask[seg_mask].index
        if len(eps) < MIN_SEG_EPISODES:
            return None
        idx_mask = val["episode_id"].isin(eps).values
        best_ev, best_w, best_t = -1e9, weak_grid[0], term_grid[0]
        for t in term_grid:
            for w in weak_grid:
                sig_full = ((signal_state_delay(val, WEAK, w, "dwell") if w is not None else pd.Series(False, index=val.index)) |
                            (signal_state_delay(val, TERM, t, "dwell") if t is not None else pd.Series(False, index=val.index)))
                sig_seg = sig_full & pd.Series(idx_mask, index=val.index)
                pnl = C.policy_pnl(val, sig_seg, ep_base_val, ep_meta_val, bars)
                e = float(pnl.loc[pnl.index.isin(eps)].mean())
                log(f"P8_{label}", f"w{w}_t{t}", e)
                if e > best_ev:
                    best_ev, best_w, best_t = e, w, t
        return {"weak": best_w, "term": best_t, "val_ev": best_ev}

    p8_rth_long = select_dir_grid((ep_rth_val == 1) & (ep_dir_val == 1), P7_RTH_WEAK, P7_RTH_TERM, "RTH_long")
    p8_rth_short = select_dir_grid((ep_rth_val == 1) & (ep_dir_val == -1), P7_RTH_WEAK, P7_RTH_TERM, "RTH_short")
    p8_eth_long = select_dir_grid((ep_rth_val != 1) & (ep_dir_val == 1), P7_ETH_WEAK, P7_ETH_TERM, "ETH_long")
    p8_eth_short = select_dir_grid((ep_rth_val != 1) & (ep_dir_val == -1), P7_ETH_WEAK, P7_ETH_TERM, "ETH_short")
    print(f"  P8 diagnostic: RTH_long={p8_rth_long} RTH_short={p8_rth_short} "
          f"ETH_long={p8_eth_long} ETH_short={p8_eth_short}")

    # decide whether direction-split clearly improves over session-only P7:
    # combined val EV of direction-split vs session-only, weighted by segment size
    def combined_seg_ev(seg_results, seg_masks):
        tot_pnl, tot_n = 0.0, 0
        for res, mask in zip(seg_results, seg_masks):
            if res is None:
                continue
            eps = mask[mask].index
            n = len(eps)
            tot_pnl += res["val_ev"] * n
            tot_n += n
        return tot_pnl / tot_n if tot_n else np.nan

    p8_combined_ev = combined_seg_ev(
        [p8_rth_long, p8_rth_short, p8_eth_long, p8_eth_short],
        [(ep_rth_val == 1) & (ep_dir_val == 1), (ep_rth_val == 1) & (ep_dir_val == -1),
         (ep_rth_val != 1) & (ep_dir_val == 1), (ep_rth_val != 1) & (ep_dir_val == -1)])
    p7_combined_ev = (rth_ev * (ep_rth_val == 1).sum() + eth_ev * (ep_rth_val != 1).sum()) / len(ep_rth_val)
    adopt_direction_split = bool(p8_combined_ev - p7_combined_ev > 1.5)
    print(f"  P8 combined val ev=${p8_combined_ev:.2f} vs P7 session-only=${p7_combined_ev:.2f} "
          f"-> adopt_direction_split={adopt_direction_split} (threshold $1.50)")

    # P9 -- session x direction with fallback session->global
    p9_config = {}
    for label, res, fallback in [
        ("RTH_long", p8_rth_long, {"weak": rth_w, "term": rth_t}),
        ("RTH_short", p8_rth_short, {"weak": rth_w, "term": rth_t}),
        ("ETH_long", p8_eth_long, {"weak": eth_w, "term": eth_t}),
        ("ETH_short", p8_eth_short, {"weak": eth_w, "term": eth_t}),
    ]:
        if res is not None and adopt_direction_split:
            p9_config[label] = {"weak": res["weak"], "term": res["term"], "source": "direction_specific"}
        else:
            p9_config[label] = {**fallback, "source": "session_fallback"}
    print(f"  P9 config: {p9_config}")

    grid_df = pd.DataFrame(grid_rows)
    grid_df.to_parquet(C.RESULTS / "validation_policy_grid.parquet", index=False)

    frozen = {
        "P3_K_seconds": K_p3,
        "P4_Kweak_seconds": Kw_p4, "P4_Kterm_seconds": Kt_p4,
        "P5_eth_Kweak_seconds": best_Kw5, "P5_eth_Kterm_seconds": best_Kt5,
        "P6_eth_Kweak_seconds": best_p6[0], "P6_eth_Kterm_seconds": best_p6[1],
        "P6_rth_Kterm_seconds": best_p6[2],
        "P7_rth_weak_seconds": rth_w, "P7_rth_term_seconds": rth_t,
        "P7_eth_weak_seconds": eth_w, "P7_eth_term_seconds": eth_t,
        "P8_adopt_direction_split": adopt_direction_split,
        "P8_diagnostics": {"RTH_long": p8_rth_long, "RTH_short": p8_rth_short,
                          "ETH_long": p8_eth_long, "ETH_short": p8_eth_short},
        "P9_config": p9_config,
        "P9_min_segment_episodes": MIN_SEG_EPISODES,
    }
    C.savej(frozen, C.RESULTS / "frozen_policy_config.json")
    C.savej(frozen, C.RESULTS / "policy_thresholds.json")
    print("done.")


if __name__ == "__main__":
    main()
