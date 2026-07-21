"""
Phase 1 -- smoothed-state stability metrics (train/val/test).
Phase 2 -- transition-event atlas (first confirmed WEAKENING / TERMINAL).

Documented conservative assumptions:
  * "regime_age" = regime_age_1m_bars * 60 (seconds) is not directly stored
    per-checkpoint in the reused v3 cache under that name at the granularity
    needed here; we use `seconds_since_flip` (seconds_since_entry +
    entry_delay_s, entry_delay_s constant 180s in this population, from the
    trades table) as the regime-age-since-flip proxy, and separately report
    trade_age = seconds_since_entry. Both are causal (computable at the
    checkpoint itself).
  * "opposite_flip_time" = true_terminal_ts ONLY when termination_reason ==
    'opposing_flip' (else NaN) -- the trades table distinguishes
    opposing_flip / max_duration / data_end explicitly, so this is exact,
    not a proxy.
  * "recovered_to_prior_mfe" = price returns to within 0.10 ATR of the
    pre-transition peak (entry + direction*trade_mfe_atr_at_transition*atr)
    at any point between the transition and the episode's true terminal.
  * "made_new_favorable_extreme" = price exceeds that same pre-transition
    peak (a genuinely NEW high/low, not just a recovery).
  * "additional_mfe_after_transition" = further favorable excursion beyond
    the pre-transition MFE, in ATR, measured over [transition_ts, terminal].
  * "maximum_adverse_move_after_transition" = worst adverse excursion from
    the PRICE AT THE TRANSITION CHECKPOINT (not from entry), in ATR, over
    [transition_ts, terminal] -- i.e. "how much worse can it get from here."
  * pnl_exit_Ns = fill at the next 1s-bar open at-or-after
    (transition_ts + N seconds), UNLESS that target is past the episode's
    true terminal, in which case it resolves to E0 (the trade would have
    already exited/terminated naturally before N seconds elapsed).

Writes:
  results/state_stability_metrics.parquet
  results/state_transition_matrix.parquet
  results/state_dwell_distribution.parquet
  results/state_transition_events.parquet
  results/state_transition_atlas.parquet
"""
from __future__ import annotations
import numpy as np
import pandas as pd

import base as C
import sim_v2

OFFSETS_S = [0, 5, 10, 15, 20, 30, 45]  # 0 == "immediate"
RECOVER_ATR = 0.10


def stability_metrics(df: pd.DataFrame, tag: str) -> dict:
    trans_per_ep = df.groupby("episode_id")["transition_confirmed"].sum()
    ever = df.groupby("episode_id")["smoothed_state"].apply(lambda s: set(s.unique()))
    return {
        "period": tag,
        "n_episodes": int(trans_per_ep.shape[0]),
        "median_transitions_per_episode": float(trans_per_ep.median()),
        "mean_transitions_per_episode": float(trans_per_ep.mean()),
        "p10_transitions": float(trans_per_ep.quantile(0.10)),
        "p25_transitions": float(trans_per_ep.quantile(0.25)),
        "p75_transitions": float(trans_per_ep.quantile(0.75)),
        "p90_transitions": float(trans_per_ep.quantile(0.90)),
        "frac_entering_WEAKENING": float(ever.apply(lambda s: "WEAKENING" in s).mean()),
        "frac_entering_TERMINAL": float(ever.apply(lambda s: "TERMINAL" in s).mean()),
        "frac_entering_PROLIFIC_EXPANDING": float(ever.apply(lambda s: "PROLIFIC_EXPANDING" in s).mean()),
        "frac_entering_HEALTHY_ESTABLISHED": float(ever.apply(lambda s: "HEALTHY_ESTABLISHED" in s).mean()),
    }


def dwell_distribution(df: pd.DataFrame, tag: str) -> pd.DataFrame:
    """Spell dwell length = seconds_in_smoothed_state at the LAST row of each
    spell (row just before a confirmed transition, or the episode's last row
    for the final spell)."""
    d = df.sort_values(["episode_id", "seconds_since_entry"]).copy()
    d["_next_conf"] = d.groupby("episode_id")["transition_confirmed"].shift(-1).fillna(True)
    spell_end = d[d["_next_conf"] | (d.groupby("episode_id").cumcount(ascending=False) == 0)]
    rows = []
    for state in C.STATES:
        sub = spell_end[spell_end["smoothed_state"] == state]["seconds_in_smoothed_state"]
        if len(sub) == 0:
            continue
        rows.append({
            "period": tag, "state": state, "n_spells": len(sub),
            "median_dwell_s": float(sub.median()), "mean_dwell_s": float(sub.mean()),
            "frac_le_10s": float((sub <= 10).mean()), "frac_le_20s": float((sub <= 20).mean()),
            "frac_le_30s": float((sub <= 30).mean()),
        })
    return pd.DataFrame(rows)


def transition_matrix(df: pd.DataFrame, tag: str) -> pd.DataFrame:
    conf = df[df["transition_confirmed"]]
    ct = pd.crosstab(conf["previous_smoothed_state"], conf["smoothed_state"])
    ct = ct.reindex(index=C.STATES, columns=C.STATES, fill_value=0)
    prob = ct.div(ct.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    out = prob.reset_index().melt(id_vars="previous_smoothed_state", var_name="smoothed_state",
                                   value_name="transition_prob")
    out["period"] = tag
    counts = ct.reset_index().melt(id_vars="previous_smoothed_state", var_name="smoothed_state",
                                    value_name="n_transitions")
    out = out.merge(counts, on=["previous_smoothed_state", "smoothed_state"])
    return out


def first_transitions(df: pd.DataFrame, target_states=("WEAKENING", "TERMINAL")) -> pd.DataFrame:
    conf = df[df["transition_confirmed"] & df["smoothed_state"].isin(target_states)]
    if len(conf) == 0:
        return pd.DataFrame()
    first = conf.sort_values("seconds_since_entry").groupby("episode_id").first().reset_index()
    first["prior_state"] = first["previous_smoothed_state"]
    first["seconds_in_prior_state"] = first["seconds_in_smoothed_state"]
    return first


def build_event_atlas(events: pd.DataFrame, ep_base, ep_meta, tt_period, bars, entry_delay_s: float):
    """Causal fields + retrospective outcome fields for each transition event."""
    term_map = tt_period.set_index("episode_id")["true_terminal_ts"]
    reason_map = tt_period.set_index("episode_id")["terminal_reason"]
    rows = []
    for r in events.itertuples(index=False):
        ep = r.episode_id
        d = int(r.direction)
        atr = float(r.atr_at_flip)
        entry_px = float(ep_meta.loc[ep, "entry_px"]) if ep in ep_meta.index else np.nan
        trans_ts = int(r.observation_time)
        end_ts = int(term_map.get(ep, trans_ts))
        e0 = float(ep_base["e0_pnl"].get(ep, np.nan))
        mfe_at_trans = float(r.trade_mfe_atr)
        peak_px = entry_px + d * mfe_at_trans * atr

        lo_i = np.searchsorted(bars[:, 0], trans_ts, side="left")
        hi_i = np.searchsorted(bars[:, 0], end_ts, side="right")
        seg = bars[lo_i:hi_i]
        if len(seg) == 0:
            recovered = False
            new_extreme = False
            time_to_recovery = np.nan
            add_mfe = 0.0
            max_adverse = 0.0
        else:
            recover_target = peak_px - d * RECOVER_ATR * atr
            if d == 1:
                rec_mask = seg[:, 3] >= recover_target
                new_mask = seg[:, 3] > peak_px
                fav_extreme = seg[:, 3].max()
                adv_extreme = seg[:, 2].min()
            else:
                rec_mask = seg[:, 2] <= recover_target
                new_mask = seg[:, 2] < peak_px
                fav_extreme = seg[:, 2].min()
                adv_extreme = seg[:, 3].max()
            recovered = bool(rec_mask.any())
            new_extreme = bool(new_mask.any())
            time_to_recovery = float((seg[np.argmax(rec_mask), 0] - trans_ts) / 1e9) if recovered else np.nan
            add_mfe = max(0.0, d * (fav_extreme - peak_px) / atr)
            max_adverse = max(0.0, -d * (adv_extreme - peak_px) / atr)

        rec = {
            "episode_id": ep, "transition_ts": trans_ts, "prior_state": r.prior_state,
            "new_state": r.smoothed_state, "seconds_in_prior_state": float(r.seconds_in_prior_state),
            "seconds_since_entry": float(r.seconds_since_entry),
            "seconds_since_flip": float(r.seconds_since_entry) + entry_delay_s,
            "session": "RTH" if r.is_rth == 1 else "ETH", "direction": d,
            "trade_age": float(r.seconds_since_entry),
            "regime_age": float(r.seconds_since_entry) + entry_delay_s,
            "current_pnl": float(r.exit_now_pnl) if hasattr(r, "exit_now_pnl") else np.nan,
            "current_pnl_atr": float(r.unrealized_pnl_atr) if hasattr(r, "unrealized_pnl_atr") else np.nan,
            "trade_mfe_atr": mfe_at_trans,
            "trade_mae_atr": float(r.trade_mae_atr) if hasattr(r, "trade_mae_atr") else np.nan,
            "giveback_atr": float(r.giveback_from_mfe_atr) if hasattr(r, "giveback_from_mfe_atr") else np.nan,
            "giveback_fraction": float(r.giveback_fraction) if hasattr(r, "giveback_fraction") else np.nan,
            "recovered_to_prior_mfe": recovered, "made_new_favorable_extreme": new_extreme,
            "time_to_recovery": time_to_recovery, "additional_mfe_after_transition": add_mfe,
            "maximum_adverse_move_after_transition": max_adverse,
            "opposite_flip_time": float(end_ts) if reason_map.get(ep) == "opposing_flip" else np.nan,
            "E0_final_pnl": e0,
        }
        for off in OFFSETS_S:
            target_ts = trans_ts + off * 1_000_000_000
            if target_ts > end_ts:
                pnl = e0
            else:
                _, fpx = sim_v2.next_1s_open(bars, target_ts)
                pnl = (fpx - entry_px) * d * C.NQ_MULT - C.COMMISSION if not np.isnan(fpx) else e0
            key = "pnl_exit_immediate" if off == 0 else f"pnl_exit_{off}s"
            rec[key] = pnl
        rows.append(rec)
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("Phase 1/2 -- state stability + transition-event atlas")
    print("=" * 70)

    train, val, test, tt = C.load_base()
    bars = C.load_bars()

    print("\n[Phase 1] stability metrics ...")
    stab_rows, dwell_rows, matrix_rows = [], [], []
    for tag, df in [("train", train), ("val", val), ("test", test)]:
        stab_rows.append(stability_metrics(df, tag))
        dwell_rows.append(dwell_distribution(df, tag))
        matrix_rows.append(transition_matrix(df, tag))
        print(f"  [{tag}] median_trans/ep={stab_rows[-1]['median_transitions_per_episode']:.1f} "
              f"frac_weakening={stab_rows[-1]['frac_entering_WEAKENING']:.3f} "
              f"frac_terminal={stab_rows[-1]['frac_entering_TERMINAL']:.3f}")

    pd.DataFrame(stab_rows).to_parquet(C.RESULTS / "state_stability_metrics.parquet", index=False)
    pd.concat(dwell_rows, ignore_index=True).to_parquet(C.RESULTS / "state_dwell_distribution.parquet", index=False)
    pd.concat(matrix_rows, ignore_index=True).to_parquet(C.RESULTS / "state_transition_matrix.parquet", index=False)

    print("\n[Phase 2] transition-event atlas ...")
    entry_delay_s = float(tt["entry_delay_s"].iloc[0])
    print(f"  entry_delay_s (constant, from trades table): {entry_delay_s}")

    all_events = []
    all_atlas = []
    for tag, df in [("train", train), ("val", val), ("test", test)]:
        ep_base, ep_meta = C.prep_period(df, tt, tag)
        tt_period = tt[tt["period"] == tag]
        ev = first_transitions(df)
        if len(ev) == 0:
            continue
        ev["period"] = tag
        all_events.append(ev)
        atlas = build_event_atlas(ev, ep_base, ep_meta, tt_period, bars, entry_delay_s)
        atlas["period"] = tag
        all_atlas.append(atlas)
        print(f"  [{tag}] transition events: {len(ev)}  "
              f"(WEAKENING={int((ev['smoothed_state']=='WEAKENING').sum())}, "
              f"TERMINAL={int((ev['smoothed_state']=='TERMINAL').sum())})")

    events_df = pd.concat(all_events, ignore_index=True)
    events_df = events_df[
        [c for c in ["episode_id", "period", "observation_time", "seconds_since_entry", "direction",
                     "is_rth", "prior_state", "smoothed_state", "seconds_in_prior_state",
                     "atr_at_flip", "trade_mfe_atr", "trade_mae_atr", "giveback_from_mfe_atr",
                     "giveback_fraction"] if c in events_df.columns]]
    events_df.to_parquet(C.RESULTS / "state_transition_events.parquet", index=False)

    atlas_df = pd.concat(all_atlas, ignore_index=True)
    atlas_df.to_parquet(C.RESULTS / "state_transition_atlas.parquet", index=False)

    # segment summary printed for sanity
    seg_summary = []
    for state in ["WEAKENING", "TERMINAL"]:
        sub = atlas_df[(atlas_df["new_state"] == state) & (atlas_df["period"] == "test")]
        for seg_name, mask in [("ALL", pd.Series(True, index=sub.index)),
                               ("RTH", sub["session"] == "RTH"), ("ETH", sub["session"] == "ETH"),
                               ("long", sub["direction"] == 1), ("short", sub["direction"] == -1)]:
            s = sub[mask]
            if len(s) == 0:
                continue
            seg_summary.append({"state": state, "segment": seg_name, "n": len(s),
                                "E0_final_pnl": round(float(s["E0_final_pnl"].mean()), 2),
                                "pnl_exit_immediate": round(float(s["pnl_exit_immediate"].mean()), 2),
                                "pnl_exit_20s": round(float(s["pnl_exit_20s"].mean()), 2)})
    print(pd.DataFrame(seg_summary).to_string(index=False))
    print("done.")


if __name__ == "__main__":
    main()
