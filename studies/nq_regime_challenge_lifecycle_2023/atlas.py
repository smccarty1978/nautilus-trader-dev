"""Descriptive challenge / lifecycle atlas (no ML, no policy).

Reads artifacts/CHALLENGE_EVENTS.parquet and CHALLENGE_CHECKPOINTS.parquet (challenge.py). Every contrast uses quintile
edges from development block A applied to both blocks, and reports raw and LOCATION-RESIDUAL effects:

  baseline(dist_flip decile)   block-A mean of the outcome in the same decile of distance-to-flip-threshold (the race
                               geometry: new extreme is k*A above, the flip threshold is dist_flip_A below)
  residual = outcome - baseline

Material (pre-declared): |top-minus-bottom residual| >= 5 pp on P(new extreme) or >= 0.15 A on hold value, same sign
in blocks A and B, and B at least half of A in magnitude.

    python studies/nq_regime_challenge_lifecycle_2023/atlas.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "artifacts"
RNG = np.random.default_rng(20260925)
OUTC = ["res_new_ext", "hold_A", "rem_mfe_A", "new_1p0A", "deepen_0p5"]
NON_FEATURES = {"regime_start_ns", "k", "tc_ns", "dir", "block", "session", "is_last", "n_challenges_regime", "t_to_flip_s",
                "final_gross_A", "res_new_ext", "t_res_s", "max_depth_A", "deepen_0p5", "deepen_1p0", "rec50", "rec75", "new_prog_A",
                "rem_mfe_A", "hold_A", "new_0p25A", "new_0p5A", "new_1p0A", "new_2p0A", "depth_pts_raw"}
FAMILY = {
    "A_maturity": ["t_onset_s", "n", "n_prior", "mfe_A", "mfe_pts", "mae_A", "loc_close_A", "loc_touch_A", "since_ext_s", "deepest_prior_A",
                   "since_prev_onset_s", "frac_time_below_0p25", "prog_last_A", "prev_rec_time_s", "prev_max_depth_A"],
    "B_impulse": ["imp_A", "imp_pts", "imp_dur_s", "imp_eff", "imp_speed_A_min", "imp_vol_rate", "imp_vol_accel", "imp_bars", "imp_body_mean_pts",
                  "imp_body_med_pts", "imp_dir_frac", "imp_big_frac", "imp_max_consec_dir", "imp_overlap", "imp_wick_frac", "imp_range_mean_pts"],
    "C_challenge": ["depth_pts", "retrace_frac", "ch_dur_s", "ch_vel_A_min", "ch_eff", "ch_vol_rate", "ch_vol_ratio", "ret15_A", "ret30_A", "ret60_A",
                    "ret120_A", "rv120_pts", "ch_adv_bars", "consec_adv_bars", "max_adv_bar_A", "ch_bars", "ch_body_mean_pts", "ch_overlap",
                    "ch_wick_frac", "ch_range_mean_pts"],
    "D_ema_band": ["dist_flip_A", "dist_flip_touch_A", "pen_ema3", "pen_ema9", "closes_thru_ema3_last3", "band_w_A", "band_w_chg5", "band_pos",
                   "slope3_A", "slope9_A", "slope9_chg_A", "ema_sep_A"],
    "E_level_memory": ["n_turns_0p25", "n_turns_0p5", "n_turns_1p0", "ext_vs_prev_same_regime_A", "stalled_at_prior_regime_ext", "touch_vs_prev_deep_A",
                       "n_prior_deeps_near_touch_0p25", "n_prior_deeps_near_touch_0p5", "n_marginal_ext"],
    "F_htf": [f"{tf}_{p}" for tf in ("5m", "15m", "1h") for p in ("aligned", "aligned_at_start", "flips_since_start", "age_min")] + ["5m_dist_flip_A"],
    "G_session": ["min_since_open", "min_to_close", "opening_drive", "rv30_pts", "vol30_per_min", "atr_pts"],
}
RAW_POINT = ["mfe_pts", "imp_pts", "imp_body_mean_pts", "imp_body_med_pts", "imp_range_mean_pts", "depth_pts", "rv120_pts", "ch_body_mean_pts",
             "ch_range_mean_pts", "rv30_pts", "atr_pts"]


def qbin(x: pd.Series, a_mask: np.ndarray, q: int = 5):
    """Quintiles from block A; low-cardinality features bin by level (top level capped where >= 5% of block A remains)."""
    xa = x[a_mask].dropna()
    if xa.nunique() < 2:
        return pd.Series(np.nan, index=x.index)
    u = np.sort(xa.unique())
    if len(u) <= 12:
        cap = max([v for v in u if (xa >= v).mean() >= 0.05])
        levels = u[u <= cap]
        b = pd.Series(np.searchsorted(levels, np.clip(x, levels[0], cap), side="right") - 1, index=x.index).astype(float)
    else:
        edges = np.unique(np.quantile(xa, np.linspace(0, 1, q + 1)[1:-1]))
        raw = np.digitize(x, edges)
        present = np.unique(raw[a_mask & x.notna().to_numpy()])
        b = pd.Series(np.searchsorted(present, np.clip(raw, present[0], present[-1])), index=x.index).astype(float)
    b[x.isna()] = np.nan
    return b if b.nunique() >= 2 else pd.Series(np.nan, index=x.index)


def add_baseline(df: pd.DataFrame, loc_col: str, outcomes, group_cols=()):
    """Block-A mean of each outcome per location decile (and optional group); residual = outcome - baseline."""
    a = (df.block == "A").to_numpy()
    df["_loc_bin"] = qbin(df[loc_col], a, 10)
    keys = list(group_cols) + ["_loc_bin"]
    base = df[a].groupby(keys)[outcomes].mean()
    joined = df[keys].merge(base, left_on=keys, right_index=True, how="left")
    for o in outcomes:
        df[f"{o}_base"] = joined[o].to_numpy()
        df[f"{o}_res"] = df[o] - df[f"{o}_base"]
    return df


def boot_diff(df, col, hi, lo, reps=200):
    u, inv = np.unique(df.session.to_numpy(), return_inverse=True)
    v = df[col].to_numpy()
    ok = ~np.isnan(v)
    parts = [np.bincount(inv, weights=np.where(msk & ok, v, 0), minlength=len(u)) for msk in (hi, lo)] + \
            [np.bincount(inv, weights=(msk & ok).astype(float), minlength=len(u)) for msk in (hi, lo)]
    w = RNG.multinomial(len(u), np.full(len(u), 1 / len(u)), size=reps)
    d = (w @ parts[0]) / (w @ parts[2]) - (w @ parts[1]) / (w @ parts[3])
    return float(np.nanpercentile(d, 2.5)), float(np.nanpercentile(d, 97.5))


def feature_atlas(df: pd.DataFrame, feats, outcomes, tag: str, ci: bool = True):
    a = (df.block == "A").to_numpy()
    cells, spreads = [], []
    for f in feats:
        if f not in df or df[f].notna().mean() < 0.2:
            continue
        b = qbin(df[f], a)
        if b.isna().all():
            continue
        nb = int(b.max()) + 1
        for blk in ("A", "B", "ALL"):
            m = (df.block == blk).to_numpy() if blk != "ALL" else np.ones(len(df), bool)
            for q in range(nb):
                sel = m & (b == q).to_numpy()
                cells.append({"scope": tag, "feature": f, "block": blk, "bin": q, "n": int(sel.sum()), "feature_mean": float(df.loc[sel, f].mean()),
                              **{o: float(df.loc[sel, o].mean()) for o in outcomes}})
            hi, lo = m & (b == nb - 1).to_numpy(), m & (b == 0).to_numpy()
            row = {"scope": tag, "feature": f, "block": blk, "n_top": int(hi.sum()), "n_bottom": int(lo.sum()), "coverage": float(df.loc[m, f].notna().mean())}
            for o in outcomes:
                row[f"{o}_spread"] = float(df.loc[hi, o].mean() - df.loc[lo, o].mean())
            if blk == "ALL" and ci:
                for o in [o for o in outcomes if o.endswith("_res")][:2] or outcomes[:2]:     # CI on the location residuals
                    row[f"{o}_ci_lo"], row[f"{o}_ci_hi"] = boot_diff(df, o, hi, lo)
            spreads.append(row)
    return pd.DataFrame(cells), pd.DataFrame(spreads)


def verdict_table(sp: pd.DataFrame, p_col: str, h_col: str, p_thr=0.05, h_thr=0.15):
    w = sp[sp.block != "ALL"].pivot_table(index=["scope", "feature"], columns="block", values=[p_col, h_col])
    out = []
    for (scope, f), r in w.iterrows():
        for col, thr in ((p_col, p_thr), (h_col, h_thr)):
            a_, b_ = r[(col, "A")], r[(col, "B")]
            material = abs(a_) >= thr and np.sign(a_) == np.sign(b_) and abs(b_) >= 0.5 * abs(a_)
            out.append({"scope": scope, "feature": f, "outcome": col, "A": a_, "B": b_, "same_sign": bool(np.sign(a_) == np.sign(b_)), "material": bool(material)})
    return pd.DataFrame(out)


def main() -> None:
    t0 = time.time()
    T = {}
    ev = pd.read_parquet(OUT / "CHALLENGE_EVENTS.parquet")
    cp = pd.read_parquet(OUT / "CHALLENGE_CHECKPOINTS.parquet")
    ev["null_gr"] = np.clip(ev.dist_flip_A, 0.01, None) / (ev.k + np.clip(ev.dist_flip_A, 0.01, None))
    ev = ev.groupby("k", group_keys=False).apply(lambda g: add_baseline(g.copy(), "dist_flip_A", OUTC))
    res_cols = [f"{o}_res" for o in OUTC]
    life = {}

    # ---------------- Phase 1-2: lifecycle topology
    per = {}
    for k, g in ev.groupby("k"):
        c = g.groupby("regime_start_ns").n.max()
        per[str(k)] = {"episodes": len(g), "per_regime_mean": float(c.mean()), "per_regime_median": float(c.median()),
                       "per_regime_p90": float(c.quantile(0.9)), "p_new_ext": float(g.res_new_ext.mean()), "p_null_gambler": float(g.null_gr.mean()),
                       "p_deepen_0p5": float(g.deepen_0p5.mean()), "median_t_res_s": float(g.t_res_s.median()), "hold_A": float(g.hold_A.mean()),
                       "rem_mfe_A": float(g.rem_mfe_A.mean()), "share_regimes_ending_in_transition_episode": float((g[g.is_last == 1].res_new_ext == 0).mean())}
    life["per_threshold"] = per
    e5 = ev[ev.k == 0.5].copy()
    # descriptive response categories (not exclusive labels)
    e5["cat"] = np.select(
        [(e5.res_new_ext == 1) & (e5.t_res_s <= 120) & (e5.max_depth_A < 0.75),
         (e5.res_new_ext == 1) & (e5.deepen_0p5 == 0),
         (e5.res_new_ext == 1) & (e5.deepen_0p5 == 1),
         (e5.res_new_ext == 0) & (e5.rec50 == 1),
         (e5.res_new_ext == 0) & (e5.rec50 == 0)],
        ["A_FAST_REJECTION", "B_SLOW_REJECTION", "E_DEEPEN_THEN_RECOVER", "C_PARTIAL_RECOVERY_THEN_FLIP", "F_DIRECT_TRANSITION"], "OTHER")
    cats = e5.groupby("cat").agg(n=("n", "size"), share=("n", lambda s: len(s) / len(e5)), med_t_res_s=("t_res_s", "median"),
                                 med_max_depth_A=("max_depth_A", "median"), hold_A=("hold_A", "mean"), rem_mfe_A=("rem_mfe_A", "mean"),
                                 new_1p0A=("new_1p0A", "mean"))
    life["categories_k0p5"] = cats.round(4).reset_index().to_dict("records")
    e10 = ev[ev.k == 1.0]
    c10 = np.select([(e10.res_new_ext == 1) & (e10.t_res_s <= 120) & (e10.max_depth_A < 1.25), (e10.res_new_ext == 1) & (e10.deepen_0p5 == 0),
                     (e10.res_new_ext == 1), (e10.rec50 == 1)],
                    ["A_FAST_REJECTION", "B_SLOW_REJECTION", "E_DEEPEN_THEN_RECOVER", "C_PARTIAL_RECOVERY_THEN_FLIP"], "F_DIRECT_TRANSITION")
    cats10 = e10.groupby(c10).agg(n=("n", "size"), med_t_res_s=("t_res_s", "median"), hold_A=("hold_A", "mean"), rem_mfe_A=("rem_mfe_A", "mean"))
    cats10["share"] = cats10.n / cats10.n.sum()
    cats10.to_csv(OUT / "CATEGORIES_K1p0.csv")
    tres = np.log10(e5.t_res_s.dropna().clip(lower=1))
    hist, edges = np.histogram(tres, bins=24)
    life["log10_t_res_hist"] = {"counts": hist.tolist(), "edges": np.round(edges, 3).tolist()}
    # episode-to-episode topology: category of episode n -> category of n+1 (same regime)
    e5 = e5.sort_values(["regime_start_ns", "n"])
    e5["next_cat"] = e5.groupby("regime_start_ns").cat.shift(-1).fillna("END")
    topo = pd.crosstab(e5.cat, e5.next_cat, normalize="index").round(3)
    topo.to_csv(OUT / "TOPOLOGY_K0p5.csv")
    by_n = e5.groupby(e5.n.clip(upper=8)).agg(N=("n", "size"), p_new_ext=("res_new_ext", "mean"), p_res=("res_new_ext_res", "mean"),
                                              hold_A=("hold_A", "mean"), rem_mfe_A=("rem_mfe_A", "mean"), deepen=("deepen_0p5", "mean"),
                                              mfe_A=("mfe_A", "mean"), dist_flip=("dist_flip_A", "mean"))
    by_n.to_csv(OUT / "BY_CHALLENGE_NUMBER_K0p5.csv")
    by_dist = ev.groupby(["k", "_loc_bin"]).agg(N=("n", "size"), dist=("dist_flip_A", "mean"), p=("res_new_ext", "mean"), null=("null_gr", "mean"),
                                                hold=("hold_A", "mean"), rem=("rem_mfe_A", "mean")).reset_index()
    by_dist.to_csv(OUT / "LOCATION_BASELINE.csv", index=False)
    T["lifecycle"] = time.time() - t0

    # ---------------- Phase 7: onset atlas, primary k = 0.5, raw + residual outcomes
    t1 = time.time()
    feats = [f for fam in FAMILY.values() for f in fam]
    cells, spreads = feature_atlas(e5, feats, OUTC + res_cols, "onset_k0p5")
    # maturity strata (Phase 8): first challenge vs later; MFE bands
    strata = {"first_challenge": e5.n == 1, "later_challenge": e5.n >= 2, "mfe_lt1A": e5.mfe_A < 1, "mfe_1to3A": (e5.mfe_A >= 1) & (e5.mfe_A < 3),
              "mfe_ge3A": e5.mfe_A >= 3, "opening_30m": e5.min_since_open < 30, "after_30m": e5.min_since_open >= 30}
    st_cells, st_spreads = [], []
    for name, msk in strata.items():
        c_, s_ = feature_atlas(e5[msk.to_numpy()].copy(), feats, ["res_new_ext_res", "hold_A_res", "rem_mfe_A_res"], f"onset_k0p5|{name}", ci=False)
        st_cells.append(c_)
        st_spreads.append(s_)
    # other thresholds, residual outcomes only
    c_, s_ = feature_atlas(ev[ev.k == 0.25].copy(), feats, ["res_new_ext_res", "hold_A_res"], "onset_k0.25", ci=False)
    st_cells.append(c_)
    st_spreads.append(s_)
    for k in (1.0, 1.5, 2.0):                                    # multi-candle, human-visible challenges: full outcomes + CIs
        c_, s_ = feature_atlas(ev[ev.k == k].copy(), feats, OUTC + res_cols, f"onset_k{k}")
        st_cells.append(c_)
        st_spreads.append(s_)
    all_cells = pd.concat([cells] + st_cells, ignore_index=True)
    all_spreads = pd.concat([spreads] + st_spreads, ignore_index=True)
    T["onset_atlas"] = time.time() - t1

    # ---------------- Phase 4: response checkpoints (OPEN episodes only), residual vs location at the checkpoint
    t2 = time.time()
    op = cp[cp.status == "OPEN"].copy()
    op["session"] = op.regime_start_ns.map(e5.drop_duplicates("regime_start_ns").set_index("regime_start_ns").session)
    op["loc2"] = op.dist_flip_A / (op.dist_flip_A.clip(lower=0.01) + op.depth_now_A.clip(lower=0.01))   # race position in [.., 1]
    op["vol_resp"] = op.vol_rate_since / op.imp_vol_rate
    resp_feats = ["rec_frac", "max_depth_so_far_A", "depth_now_A", "dist_flip_A", "above_ema3", "recaptured_ema3", "n_touch_crosses",
                  "vol_resp", "new_lows_0p1", "mfe_A", "age_s", "atr_pts", "cp_adv_bars", "cp_adv_bar_frac", "cp_consec_adv",
                  "cp_closes_below_ema3", "cp_ema3_recaptured", "cp_max_adv_body_A", "cp_overlap", "cp_band_w_chg", "cp_slope9_A", "cp_ema_sep_A"]
    cp_out = ["cp_new_ext", "cp_hold_A", "cp_rem_mfe_A"]
    cp_cells, cp_spreads, cp_info = [], [], []
    for (kk, lab), g in op.groupby(["k", "cp"]):
        lab = f"k{kk}|{lab}"
        g = add_baseline(g.copy(), "loc2", cp_out)
        c_, s_ = feature_atlas(g, resp_feats, [f"{o}_res" for o in cp_out] + cp_out, f"cp|{lab}", ci=False)
        cp_cells.append(c_)
        cp_spreads.append(s_)
        cp_info.append({"cp": lab, "n_open": len(g), "p_new_ext": float(g.cp_new_ext.mean()), "hold_A": float(g.cp_hold_A.mean()),
                        "rem_mfe_A": float(g.cp_rem_mfe_A.mean()), "median_t_to_flip_s": float(g.cp_t_to_flip_s.median()),
                        "loc_only_p_range": float(g.groupby("_loc_bin").cp_new_ext.mean().max() - g.groupby("_loc_bin").cp_new_ext.mean().min())})
    cp_cells, cp_spreads = pd.concat(cp_cells, ignore_index=True), pd.concat(cp_spreads, ignore_index=True)
    status = cp.groupby(["k", "cp", "status"]).size().unstack(fill_value=0)
    status.to_csv(OUT / "CHECKPOINT_STATUS.csv")
    T["response_atlas"] = time.time() - t2

    # ---------------- Phase 5: repeated-challenge sequences (n >= 3, k = 0.5)
    t3 = time.time()
    s = e5.sort_values(["regime_start_ns", "n"]).copy()
    g = s.groupby("regime_start_ns")
    s["prog_prev2"] = g.prog_last_A.shift(1)                     # progress of the previous recovery leg
    s["depth_prev2"] = g.max_depth_A.shift(2)
    s["imp_eff_prev"] = g.imp_eff.shift(1)
    s["progress_declining"] = (s.prog_last_A < s.prog_prev2).astype(float).where(s.prog_prev2.notna())
    s["depth_increasing"] = (s.prev_max_depth_A > s.depth_prev2).astype(float).where(s.depth_prev2.notna())
    s["impulse_weakening"] = (s.imp_eff < s.imp_eff_prev).astype(float).where(s.imp_eff_prev.notna())
    s["rec_slowing"] = (s.prev_rec_time_s > g.prev_rec_time_s.shift(1)).astype(float).where(g.prev_rec_time_s.shift(1).notna())
    s["deterioration_count"] = s[["progress_declining", "depth_increasing", "impulse_weakening", "rec_slowing"]].sum(axis=1, min_count=4)
    s["pattern"] = np.select([s.deterioration_count >= 3, s.deterioration_count <= 1], ["DETERIORATING", "STRENGTHENING"], "MIXED")
    s.loc[s.deterioration_count.isna(), "pattern"] = "SHORT_HISTORY"
    seq_rows = []
    for blk in ("A", "B", "ALL"):
        m = s if blk == "ALL" else s[s.block == blk]
        for pat, gg in m.groupby("pattern"):
            seq_rows.append({"block": blk, "pattern": pat, "n": len(gg), "p_new_ext": gg.res_new_ext.mean(), "p_res": gg.res_new_ext_res.mean(),
                             "hold_A": gg.hold_A.mean(), "hold_res": gg.hold_A_res.mean(), "rem_mfe_A": gg.rem_mfe_A.mean(), "rem_res": gg.rem_mfe_A_res.mean(),
                             "new_1p0A": gg.new_1p0A.mean(), "mfe_A": gg.mfe_A.mean(), "dist_flip_A": gg.dist_flip_A.mean()})
    seq = pd.DataFrame(seq_rows)
    seq_feats = ["prog_last_A", "prog_prev2", "prev_max_depth_A", "touch_vs_prev_deep_A", "prev_rec_time_s", "n_marginal_ext",
                 "n_prior_deeps_near_touch_0p5", "progress_declining", "depth_increasing", "impulse_weakening", "rec_slowing", "deterioration_count"]
    sq_cells, sq_spreads = feature_atlas(s[s.n >= 3].copy(), seq_feats, OUTC + res_cols, "sequence_n>=3")
    # hindsight contrast: last (transition) episode vs earlier ones in the same regimes (NOT prospective)
    last_vs = s[s.n_challenges_regime >= 3].groupby("is_last")[["prog_last_A", "prev_max_depth_A", "imp_eff", "ch_vel_A_min", "dist_flip_A",
                                                                "touch_vs_prev_deep_A", "ch_vol_ratio", "imp_A"]].median()
    last_vs.to_csv(OUT / "HINDSIGHT_LAST_VS_EARLIER.csv")
    T["sequence"] = time.time() - t3

    # ---------------- verdict inputs
    vt_on = verdict_table(all_spreads[all_spreads.scope.str.startswith("onset") | all_spreads.scope.str.startswith("sequence")],
                          "res_new_ext_res_spread", "hold_A_res_spread")
    vt_seq = verdict_table(sq_spreads, "res_new_ext_res_spread", "hold_A_res_spread")
    vt_cp = verdict_table(cp_spreads, "cp_new_ext_res_spread", "cp_hold_A_res_spread")
    vt = pd.concat([vt_on, vt_seq, vt_cp], ignore_index=True)
    # ---------------- raw points vs ATR within the location baseline (Q18)
    raw = spreads[(spreads.block != "ALL") & spreads.feature.isin(RAW_POINT)][["feature", "block", "res_new_ext_res_spread", "hold_A_res_spread", "rem_mfe_A_res_spread"]]

    atlas = pd.concat([all_cells.assign(kind="onset"), cp_cells.assign(kind="response"), sq_cells.assign(kind="sequence")], ignore_index=True)
    atlas.to_parquet(OUT / "REGIME_LIFECYCLE_ATLAS.parquet", index=False)
    pd.concat([all_spreads, cp_spreads, sq_spreads], ignore_index=True).to_csv(OUT / "ATLAS_SPREADS.csv", index=False)
    vt.to_csv(OUT / "MATERIALITY.csv", index=False)
    seq.to_csv(OUT / "SEQUENCE_PATTERNS.csv", index=False)
    raw.to_csv(OUT / "RAW_POINT_EFFECTS.csv", index=False)
    pd.DataFrame(cp_info).to_csv(OUT / "CHECKPOINT_INFO.csv", index=False)
    cats.to_csv(OUT / "CATEGORIES_K0p5.csv")
    e5[["regime_start_ns", "n", "cat", "next_cat"]].to_parquet(OUT / "EPISODE_CATEGORIES_K0p5.parquet", index=False)
    life["runtime_s"] = {k: round(v, 1) for k, v in T.items()} | {"total": round(time.time() - t0, 1)}
    (OUT / "LIFECYCLE_SUMMARY.json").write_text(json.dumps(life, indent=2, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"runtime_s": life["runtime_s"], "material_rows": int(vt.material.sum()), "tested_rows": len(vt)}, indent=1))


if __name__ == "__main__":
    main()
