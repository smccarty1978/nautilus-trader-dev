"""
Phase 1 -- smooth the raw checkpoint regime-state sequence with dwell +
confirmation hysteresis, asymmetric by transition type.

Fixes (audit_v2_policies.py):
  * raw state flicker (median 13 transitions/episode, 57% of spells <=10s)
  * the local_weak/PROLIFIC-HEALTHY tautology -- smoothing is the ONLY
    mechanism that lets a checkpoint be locally weak while the regime is still
    read as PROLIFIC/HEALTHY (the raw transition just hasn't been confirmed).

Rules (compact grid, validation-selected):
  * min_dwell_s: smoothed state must have held >= this long before a new
    transition can be confirmed.
  * confirm_default: consecutive differing raw checkpoints required to
    confirm an ordinary transition.
  * confirm_strict (> default): required for PROLIFIC/HEALTHY -> WEAKENING
    and ORDINARY -> TERMINAL (harder to declare things are getting worse from
    a strong or neutral state).
  * confirm_fast (< default): required for WEAKENING -> TERMINAL (deterioration
    from an already-weak state is confirmed quickly).
  * confirm_recovery (>= strict): required for ANY transition OUT of TERMINAL
    (recovery needs the strongest evidence).

Writes:
  results/smoothed_state_checkpoints.parquet
  results/state_smoothing_grid.parquet
  results/frozen_state_smoothing.json
  results/state_stability_metrics.parquet
"""
from __future__ import annotations
import numpy as np
import pandas as pd

import base as C
import sim_v2

STRICT_PAIRS = {
    ("PROLIFIC_EXPANDING", "WEAKENING"), ("HEALTHY_ESTABLISHED", "WEAKENING"),
    ("ORDINARY", "TERMINAL"),
}
FAST_PAIRS = {("WEAKENING", "TERMINAL")}

# compact validation-only grid (spec offers 10/15/20/30s dwell x 2/3/4 confirm)
GRID = [
    {"min_dwell_s": 15, "confirm_default": 2, "confirm_strict": 3, "confirm_fast": 2, "confirm_recovery": 4},
    {"min_dwell_s": 15, "confirm_default": 3, "confirm_strict": 4, "confirm_fast": 2, "confirm_recovery": 4},
    {"min_dwell_s": 30, "confirm_default": 2, "confirm_strict": 3, "confirm_fast": 2, "confirm_recovery": 4},
    {"min_dwell_s": 30, "confirm_default": 3, "confirm_strict": 4, "confirm_fast": 3, "confirm_recovery": 4},
]


def smooth_episode_block(raw, t, min_dwell_s, confirm_default, confirm_strict,
                          confirm_fast, confirm_recovery):
    """Smooth ONE episode's chronological raw-state array. Returns 5 arrays."""
    n = len(raw)
    smoothed = [None] * n
    seconds_in_state = np.zeros(n)
    transition_confirmed = np.zeros(n, dtype=bool)
    transition_candidate = np.zeros(n, dtype=bool)
    reason = [None] * n

    cur_state = raw[0]
    cur_start_t = t[0]
    cand_state = None
    cand_start_t = 0
    cand_count = 0

    smoothed[0] = cur_state
    reason[0] = "init:" + cur_state

    for k in range(1, n):
        r = raw[k]
        dwell = (t[k] - cur_start_t) / 1e9
        if r == cur_state:
            cand_state = None
            cand_count = 0
            smoothed[k] = cur_state
            reason[k] = "hold"
        else:
            if cand_state != r:
                cand_state = r
                cand_count = 1
                cand_start_t = t[k]
            else:
                cand_count += 1
            if cur_state == "TERMINAL":
                need = confirm_recovery
            elif (cur_state, r) in STRICT_PAIRS:
                need = confirm_strict
            elif (cur_state, r) in FAST_PAIRS:
                need = confirm_fast
            else:
                need = confirm_default

            if dwell >= min_dwell_s and cand_count >= need:
                reason[k] = f"confirmed:{cur_state}->{r}"
                cur_state = r
                cur_start_t = cand_start_t
                cand_state = None
                cand_count = 0
                transition_confirmed[k] = True
                smoothed[k] = cur_state
            else:
                transition_candidate[k] = True
                reason[k] = f"candidate:{cur_state}->{r}({cand_count}/{need})"
                smoothed[k] = cur_state
        seconds_in_state[k] = (t[k] - cur_start_t) / 1e9

    return smoothed, seconds_in_state, transition_confirmed, transition_candidate, reason


def smooth_states(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Vectorised-per-episode smoothing. df must be sorted by
    [episode_id, seconds_since_entry]. Returns df with added columns."""
    df = df.sort_values(["episode_id", "seconds_since_entry"]).reset_index(drop=True)
    ep = df["episode_id"].values
    raw = df["state"].values
    t = df["observation_time"].values.astype(np.int64)
    n = len(df)

    smoothed_all = np.empty(n, dtype=object)
    sec_all = np.zeros(n)
    confirm_all = np.zeros(n, dtype=bool)
    cand_all = np.zeros(n, dtype=bool)
    reason_all = np.empty(n, dtype=object)

    i = 0
    while i < n:
        j = i
        while j < n and ep[j] == ep[i]:
            j += 1
        sm, sec, conf, cand, rsn = smooth_episode_block(
            raw[i:j], t[i:j], **params)
        smoothed_all[i:j] = sm
        sec_all[i:j] = sec
        confirm_all[i:j] = conf
        cand_all[i:j] = cand
        reason_all[i:j] = rsn
        i = j

    out = df.copy()
    out["previous_smoothed_state"] = pd.Series(smoothed_all, index=out.index).groupby(out["episode_id"]).shift(1)
    out["smoothed_state"] = smoothed_all
    out["seconds_in_smoothed_state"] = sec_all
    out["transition_confirmed"] = confirm_all
    out["transition_candidate"] = cand_all
    out["transition_reason"] = reason_all
    return out


def stability_metrics(df: pd.DataFrame, tag: str) -> dict:
    trans_per_ep = df.groupby("episode_id")["transition_confirmed"].sum()
    dwell = df.loc[df["transition_confirmed"] | (df["previous_smoothed_state"].isna()),
                    ["episode_id"]].copy()
    # dwell spell lengths: seconds_in_smoothed_state just BEFORE each confirmed transition
    spell_len = df.groupby("episode_id").apply(
        lambda g: g["seconds_in_smoothed_state"].values[-1] if len(g) else np.nan,
        include_groups=False)
    ever = df.groupby("episode_id")["smoothed_state"].apply(lambda s: set(s.unique()))
    return {
        "grid_tag": tag,
        "median_transitions_per_episode": float(trans_per_ep.median()),
        "mean_transitions_per_episode": float(trans_per_ep.mean()),
        "frac_ever_prolific": float(ever.apply(lambda s: "PROLIFIC_EXPANDING" in s).mean()),
        "frac_ever_weakening": float(ever.apply(lambda s: "WEAKENING" in s).mean()),
        "frac_ever_terminal": float(ever.apply(lambda s: "TERMINAL" in s).mean()),
    }


def policy_pnl(df, sig, ep_base, ep_meta, bars):
    result = ep_base["e0_pnl"].copy()
    trig = df[sig.values if hasattr(sig, "values") else sig]
    if len(trig):
        trig = trig.sort_values("seconds_since_entry")
        fired = (trig.groupby("episode_id")["observation_time"].first()
                 .reset_index().rename(columns={"observation_time": "sig_ts"}))
        fired = fired.merge(ep_meta[["entry_px", "direction"]],
                             left_on="episode_id", right_index=True, how="left")
        obs = fired["sig_ts"].values.astype(np.float64)
        fi = np.searchsorted(bars[:, 0], obs, side="right")
        valid = fi < len(bars)
        fic = fi.clip(0, len(bars) - 1)
        fpx = np.where(valid, bars[fic, 1], np.nan)
        pnl = (fpx - fired["entry_px"].values) * fired["direction"].values * C.NQ_MULT - C.COMMISSION
        fired["pnl"] = pnl
        bad = ~valid
        if bad.any():
            fired.loc[bad, "pnl"] = fired.loc[bad, "episode_id"].map(ep_base["e0_pnl"]).values
        result.loc[fired["episode_id"].values] = fired["pnl"].values
    return result


def proxy_policy_ev(df, ep_base, ep_meta, bars):
    """Simplified P3-style proxy used ONLY to rank smoothing configs:
    exit immediately in TERMINAL; exit in WEAKENING after 4 consecutive
    (20s) local_weak checkpoints; no action in PROLIFIC/HEALTHY/ORDINARY."""
    elig = df["seconds_since_entry"] >= C.MIN_ELIG_S
    term_sig = elig & (df["smoothed_state"] == "TERMINAL")

    lw = df["local_weak"].values
    codes = df.groupby("episode_id").ngroup().values
    run = np.zeros(len(df), dtype=int)
    for k in range(len(df)):
        run[k] = (run[k - 1] + 1) if (k > 0 and codes[k] == codes[k - 1] and lw[k]) else (1 if lw[k] else 0)
    weak_persist = pd.Series(run >= 4, index=df.index)
    weak_sig = elig & (df["smoothed_state"] == "WEAKENING") & weak_persist

    sig = term_sig | weak_sig
    pnl = policy_pnl(df, sig, ep_base, ep_meta, bars)
    return float(pnl.mean())


def main():
    print("=" * 70)
    print("Phase 1 -- smooth regime states")
    print("=" * 70)

    train, val, test, tt = C.prepare_base()
    bars = C.load_bars()
    ep_base_val = sim_v2.build_ep_base(val, tt[tt["period"] == "val"])
    ep_meta_val = C.make_ep_meta(val)
    e0_val = float(ep_base_val["e0_pnl"].mean())

    print(f"  grid: {len(GRID)} configs (validation only)")
    grid_rows = []
    stab_rows = []
    best = (-1e9, None, None)
    for gi, params in enumerate(GRID):
        tag = f"dwell{params['min_dwell_s']}_c{params['confirm_default']}"
        val_sm = smooth_states(val, params)
        ev = proxy_policy_ev(val_sm, ep_base_val, ep_meta_val, bars)
        delta = ev - e0_val
        stab = stability_metrics(val_sm, tag)
        stab_rows.append(stab)
        grid_rows.append({"config": tag, **params, "val_ev": round(ev, 3),
                           "val_delta": round(delta, 3), **stab})
        print(f"  [{tag}] val EV=${ev:.2f} delta=${delta:+.2f} "
              f"median_trans/ep={stab['median_transitions_per_episode']:.1f}")
        if delta > best[0]:
            best = (delta, params, tag)

    grid_df = pd.DataFrame(grid_rows)
    grid_df.to_parquet(C.RESULTS / "state_smoothing_grid.parquet", index=False)
    pd.DataFrame(stab_rows).to_parquet(C.RESULTS / "state_stability_metrics.parquet", index=False)

    frozen_params, frozen_tag = best[1], best[2]
    print(f"\n  FROZEN smoothing config: {frozen_tag} (val delta ${best[0]:+.2f}) params={frozen_params}")
    C.savej({"frozen_config_tag": frozen_tag, "params": frozen_params,
             "selection_rule": "max proxy-policy paired EV delta vs E0 on validation "
                                "(compact grid); stability reported, not used as the "
                                "selection criterion itself.",
             "val_ev_delta": round(best[0], 3)},
            C.RESULTS / "frozen_state_smoothing.json")

    print("  applying frozen smoothing to train/val/test ...")
    smoothed_parts = []
    for tag, df in [("train", train), ("val", val), ("test", test)]:
        sm = smooth_states(df, frozen_params)
        smoothed_parts.append(sm)
    full_sm = pd.concat(smoothed_parts, ignore_index=True)

    keep = ["episode_id", "observation_time", "seconds_since_entry", "period",
            "direction", "is_rth", "local_weak", "hold_advantage",
            "state", "previous_smoothed_state", "smoothed_state",
            "seconds_in_smoothed_state", "transition_confirmed",
            "transition_candidate", "transition_reason"]
    full_sm[keep].to_parquet(C.RESULTS / "smoothed_state_checkpoints.parquet", index=False)

    # diagnostics printed
    dist = full_sm.groupby(["period", "smoothed_state"]).size().reset_index(name="n")
    print(dist.to_string(index=False))
    print("done.")


if __name__ == "__main__":
    main()
