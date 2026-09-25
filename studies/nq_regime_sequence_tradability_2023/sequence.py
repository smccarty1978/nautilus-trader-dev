"""Regime-sequence tradability atlas (descriptive; no ML, no policy simulation).

Input: _work/REGIMES.parquet + _work/GRID_1M.parquet from extract.py (parity-checked, development sessions only).

Unit: flip i = start of regime i (the flip-to-flip trade). Features use ONLY regimes j < i of the same contiguous
chain segment (every such regime is complete at S_i because T_{i-1} == S_i) plus the 1m close grid at or before S_i
and the audited T0 HTF snapshot (T0 = S_i + 15 s = entry instant). Outcomes use regimes i .. i+k-1 of the same
segment. Definitions: REGIME_SEQUENCE_FEATURE_DEFINITIONS.md.

    python studies/nq_regime_sequence_tradability_2023/sequence.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, OUT = HERE / "_work", HERE / "artifacts"
NS = 1_000_000_000
COST_PTS = 2.9 * 0.25          # ntr nq_default_v1: 1 tick slippage/side + $2.25 commission/side = 2.9 ticks round trip
RNG = np.random.default_rng(20260925)
N_BOOT = 300

# oriented so that HIGH = "rotation-like" is NOT assumed; orientation used only by the composite (below)
PRIMARY = ["eff_3", "eff_5", "eff_clock_30m", "flips_30m", "dur_mean_3", "terr_ratio_5", "chan_width_5",
           "prog_same_last", "prog_opp_last", "frac_new_ext_4", "flip_disp_6", "n_near_0p5_6",
           "headroom_same", "fails_at_level", "rng_ratio_3v3", "rng_mean_3", "htf5_prog", "htf15_prior_disp"]
# composite: sign = +1 means a HIGH value is rotation-like
ROT_COMPONENTS = {"eff_5": -1, "terr_ratio_5": -1, "flips_30m": +1, "frac_new_ext_4": -1, "n_near_0p5_6": +1}
OUTCOMES = ["nx_gross", "nx_net", "nx_disp", "nx_mfe", "nx_mae", "nx_dur_min", "nx_reach_0p5", "nx_reach_1p0", "nx_reach_2p0",
            "nx_fav_first", "nx_new_ext", "fw2_gross", "fw3_gross", "fw4_gross", "fw3_net", "fw3_eff", "fw3_net_disp",
            "fw3_flips_per_30m", "fw3_terr", "fw3_escape", "fw3_rotational"]


def features_and_outcomes(r: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    r = r.sort_values("regime_start_ns").reset_index(drop=True)
    r["seg"] = ((r.session != r.session.shift()) | (r.regime_start_ns != r.terminal_ts.shift())).cumsum()
    d = r.dir.to_numpy(float)
    P0, P1, atr = r.start_px.to_numpy(), r.end_px.to_numpy(), r.atr.to_numpy()
    hi, lo = r.reg_hi.to_numpy(), r.reg_lo.to_numpy()
    fav = np.where(d > 0, hi, lo)
    S, T = r.regime_start_ns.to_numpy(np.int64), r.terminal_ts.to_numpy(np.int64)
    dur = (T - S) / NS
    rng = hi - lo
    gross = r.terminal_gross_atr.to_numpy()
    net = gross - COST_PTS / atr
    seg = r.seg.to_numpy()
    n = len(r)
    F = {k: np.full(n, np.nan) for k in PRIMARY + ["prev_disp", "dist_same_flip", "n_near_0p25_6", "n_near_1p0_6",
                                                   "flips_10m", "flips_20m", "htf5_prior_disp", "htf15_prog", "hist_regimes"]}
    O = {k: np.full(n, np.nan) for k in OUTCOMES + ["fw2_eff", "fw4_eff", "fw2_net", "fw4_net"]}
    g_by = {s: (g.ts.to_numpy(np.int64), g.close.to_numpy()) for s, g in grid.groupby("session")}
    seg_first = pd.Series(np.arange(n)).groupby(seg).transform("min").to_numpy()
    seg_last = pd.Series(np.arange(n)).groupby(seg).transform("max").to_numpy()
    sess = r.session.to_numpy()
    for i in range(n):
        a, A = seg_first[i], atr[i]
        h = i - a                                           # completed regimes available in this segment
        F["hist_regimes"][i] = h
        # --- flip density (clock): prior flips in (S_i - w, S_i), valid only when the segment covers the window
        for w, key in ((10, "flips_10m"), (20, "flips_20m"), (30, "flips_30m")):
            if S[a] <= S[i] - w * 60 * NS:
                F[key][i] = int(np.sum(S[a:i] > S[i] - w * 60 * NS))
        if h >= 3:
            F["dur_mean_3"][i] = dur[i - 3:i].mean() / 60
            F["eff_3"][i] = abs(P0[i] - P0[i - 3]) / np.abs(P1[i - 3:i] - P0[i - 3:i]).sum()
            F["rng_mean_3"][i] = rng[i - 3:i].mean() / A
        if h >= 5:
            F["eff_5"][i] = abs(P0[i] - P0[i - 5]) / np.abs(P1[i - 5:i] - P0[i - 5:i]).sum()
            F["terr_ratio_5"][i] = (hi[i - 5:i].max() - lo[i - 5:i].min()) / rng[i - 5:i].sum()
            F["chan_width_5"][i] = (hi[i - 5:i].max() - lo[i - 5:i].min()) / A
        if h >= 1:
            F["prev_disp"][i] = d[i - 1] * (P1[i - 1] - P0[i - 1]) / A
        if h >= 2:
            F["dist_same_flip"][i] = d[i] * (P0[i] - P0[i - 2]) / A
        if h >= 4:
            F["prog_same_last"][i] = d[i] * (fav[i - 2] - fav[i - 4]) / A
            F["prog_opp_last"][i] = d[i] * (fav[i - 1] - fav[i - 3]) / A
        if h >= 6:
            js = np.arange(i - 4, i)
            F["frac_new_ext_4"][i] = np.mean(d[js] * (fav[js] - fav[js - 2]) / A > 0.25)
            F["flip_disp_6"][i] = np.std(P0[i - 6:i + 1]) / A
            dist = np.abs(P0[i - 6:i] - P0[i]) / A
            F["n_near_0p25_6"][i], F["n_near_0p5_6"][i], F["n_near_1p0_6"][i] = (dist <= 0.25).sum(), (dist <= 0.5).sum(), (dist <= 1.0).sum()
            F["rng_ratio_3v3"][i] = rng[i - 3:i].mean() / rng[i - 6:i - 3].mean()
            # level memory: last same-direction stall level (fav extreme of regime i-2) and how often it was tried before
            lvl = fav[i - 2]
            F["headroom_same"][i] = d[i] * (lvl - P0[i]) / A
            F["fails_at_level"][i] = int(np.sum(np.abs(fav[[i - 4, i - 6]] - lvl) <= 0.5 * A))
        # --- clock path efficiency over 30 min of 1m closes ending at S_i (grid starts 70 min before the first flip)
        gt, gc = g_by[sess[i]]
        e = int(np.searchsorted(gt, S[i], side="right"))
        b = int(np.searchsorted(gt, S[i] - 30 * 60 * NS, side="left"))
        if b >= 0 and e - b >= 25:
            path = np.abs(np.diff(gc[b:e])).sum()
            F["eff_clock_30m"][i] = abs(gc[e - 1] - gc[b]) / path if path > 0 else np.nan
        # --- outcomes
        O["nx_disp"][i] = d[i] * (P1[i] - P0[i]) / A
        if h >= 2:
            O["nx_new_ext"][i] = float(d[i] * (fav[i] - fav[i - 2]) > 0)
        for k in (2, 3, 4):
            if i + k - 1 <= seg_last[i]:
                js = np.arange(i, i + k)
                O[f"fw{k}_gross"][i] = gross[js].sum()
                O[f"fw{k}_net"][i] = net[js].sum()
                path = np.abs(P1[js] - P0[js]).sum()
                nd = abs(P1[i + k - 1] - P0[i])
                O[f"fw{k}_eff"][i] = nd / path if path > 0 else np.nan
                if k == 3:
                    O["fw3_net_disp"][i] = nd / A
                    O["fw3_flips_per_30m"][i] = 3 / ((T[i + 2] - S[i]) / NS / 1800)
                    O["fw3_terr"][i] = (hi[js].max() - lo[js].min()) / rng[js].sum()
                    O["fw3_escape"][i] = max(hi[js].max() - P0[i], P0[i] - lo[js].min()) / A
                    O["fw3_rotational"][i] = float(nd / A < 1.0)
    out = r.copy()
    for k, v in {**F, **O}.items():
        out[k] = v
    out["nx_gross"], out["nx_net"] = gross, net
    out["nx_mfe"], out["nx_mae"], out["nx_dur_min"] = r.trade_mfe_atr, r.trade_mae_atr, dur / 60
    for x in ("0p5", "1p0", "2p0"):
        out[f"nx_reach_{x}"] = r[f"reach_fav_{x}"].astype(float)
    tf, ta = r.t_fav_1p0.fillna(np.inf), r.t_adv_1p0.fillna(np.inf)
    out["nx_fav_first"] = ((tf < ta) & np.isfinite(tf)).astype(float)
    # HTF progress from the audited T0 snapshot (T0 = entry instant): progress of the current 5m / 15m regime and the
    # displacement of the last completed 5m regime, all in that timeframe's ATR
    out["htf5_prog"] = r.dir_5m * (r.start_px - r.start_price_5m) / r.atr_5m
    out["htf15_prog"] = r.dir_15m * (r.start_px - r.start_price_15m) / r.atr_15m
    out["htf5_prior_disp"] = r.prior_terminal_displacement_atr_5m
    out["htf15_prior_disp"] = r.prior_terminal_displacement_atr_15m
    al = r[["aligned_T0_5m", "aligned_T0_15m", "aligned_T0_1h"]]
    out["mtf_group"] = np.select([al.isna().any(axis=1), (al == 1).all(axis=1),
                                  (al.aligned_T0_5m == 1) & (al.aligned_T0_15m == 1) & (al.aligned_T0_1h == 0),
                                  (al == 0).all(axis=1)], ["NA", "ALL_ALIGNED", "AAO", "ALL_OPPOSED"], "MIXED")
    return out


def qbins(x: pd.Series, a_mask: pd.Series, q: int = 5):
    """Quintile edges from development block A only, applied to both blocks (ties -> fewer bins)."""
    edges = np.unique(np.nanquantile(x[a_mask].dropna(), np.linspace(0, 1, q + 1)[1:-1]))
    raw = np.digitize(x, edges)
    present = np.unique(raw[a_mask.to_numpy() & x.notna().to_numpy()])      # discrete features leave some bins empty
    b = pd.Series(np.searchsorted(present, np.clip(raw, present[0], present[-1])), index=x.index).astype(float)
    b[x.isna()] = np.nan
    return b, edges[present[1:] - 1]


def boot_diff(df: pd.DataFrame, col: str, hi_mask, lo_mask) -> tuple[float, float]:
    """Session-block bootstrap CI (2.5/97.5) for mean(col | hi) - mean(col | lo)."""
    sess = df.session.to_numpy()
    u, inv = np.unique(sess, return_inverse=True)
    v = df[col].to_numpy()
    ok = ~np.isnan(v)
    sh = np.bincount(inv, weights=np.where(hi_mask & ok, v, 0), minlength=len(u))
    nh = np.bincount(inv, weights=(hi_mask & ok).astype(float), minlength=len(u))
    sl = np.bincount(inv, weights=np.where(lo_mask & ok, v, 0), minlength=len(u))
    nl = np.bincount(inv, weights=(lo_mask & ok).astype(float), minlength=len(u))
    w = RNG.multinomial(len(u), np.full(len(u), 1 / len(u)), size=N_BOOT)
    diffs = (w @ sh) / (w @ nh) - (w @ sl) / (w @ nl)
    return float(np.nanpercentile(diffs, 2.5)), float(np.nanpercentile(diffs, 97.5))


def trimmed_mean(v: pd.Series, top: float = 0.01) -> float:
    v = v.dropna()
    return float(v[v <= v.quantile(1 - top)].mean()) if len(v) else np.nan


def summarize(g: pd.DataFrame) -> dict:
    s = {"n": len(g)}
    for c in OUTCOMES:
        s[c] = float(g[c].mean())
    s["nx_gross_ex_top1pct"] = trimmed_mean(g.nx_gross)
    s["fw3_n"] = int(g.fw3_gross.notna().sum())
    return s


def main() -> None:
    t0 = time.time()
    r = pd.read_parquet(WORK / "REGIMES.parquet")
    grid = pd.read_parquet(WORK / "GRID_1M.parquet")
    df = features_and_outcomes(r, grid)
    t_feat = time.time() - t0
    A = df.block == "A"

    # ---------------- Phase 4: per-feature quintile atlas, edges from block A
    t1 = time.time()
    atlas, spread = [], []
    for f in PRIMARY:
        b, edges = qbins(df[f], A)
        df[f"q_{f}"] = b
        nb = len(edges) + 1
        for blk in ("A", "B", "ALL"):
            m = df.block.eq(blk) if blk != "ALL" else pd.Series(True, index=df.index)
            for q in range(nb):
                g = df[m & (b == q)]
                atlas.append({"feature": f, "block": blk, "bin": q, "n_bins": nb, "lo_edge": edges[q - 1] if q > 0 else -np.inf,
                              "hi_edge": edges[q] if q < nb - 1 else np.inf, "feature_mean": float(g[f].mean()), **summarize(g)})
            lo_m, hi_m = (m & (b == 0)).to_numpy(), (m & (b == nb - 1)).to_numpy()
            row = {"feature": f, "block": blk, "coverage": float(df.loc[m, f].notna().mean())}
            for c in ("nx_gross", "nx_net", "nx_mfe", "nx_reach_2p0", "fw3_gross", "fw3_eff", "fw3_flips_per_30m", "fw3_escape", "fw3_rotational"):
                row[f"{c}_top_minus_bottom"] = float(df.loc[hi_m, c].mean() - df.loc[lo_m, c].mean())
            if blk == "ALL":
                for c in ("nx_gross", "fw3_gross"):
                    row[f"{c}_ci_lo"], row[f"{c}_ci_hi"] = boot_diff(df, c, hi_m, lo_m)
            spread.append(row)
    atlas, spread = pd.DataFrame(atlas), pd.DataFrame(spread)
    t_atlas = time.time() - t1

    # ---------------- Phase 5: coarse composite rotation score (percentile ranks vs block A; equal weights)
    t2 = time.time()
    comp = []
    for f, sgn in ROT_COMPONENTS.items():
        ref = np.sort(df.loc[A, f].dropna().to_numpy())
        pr = np.searchsorted(ref, df[f].to_numpy(), side="right") / len(ref)
        pr = np.where(df[f].isna(), np.nan, pr)
        comp.append(pr if sgn > 0 else 1 - pr)
    df["rot_score"] = np.mean(np.vstack(comp), axis=0)          # NaN if any component is missing
    cut_lo, cut_hi = np.nanquantile(df.loc[A, "rot_score"], [0.2, 0.8])
    df["state"] = np.select([df.rot_score.isna(), df.rot_score >= cut_hi, df.rot_score <= cut_lo], ["NO_HISTORY", "ROTATION", "EXPANSION"], "MIXED")
    states = []
    for blk in ("A", "B", "ALL"):
        m = df.block.eq(blk) if blk != "ALL" else pd.Series(True, index=df.index)
        for st in ("EXPANSION", "MIXED", "ROTATION", "NO_HISTORY"):
            states.append({"block": blk, "state": st, **summarize(df[m & (df.state == st)])})
    states = pd.DataFrame(states)
    # gate arithmetic (descriptive: what the ROTATION bucket contains; not a policy simulation)
    gate = []
    for blk in ("A", "B", "ALL"):
        m = df.block.eq(blk) if blk != "ALL" else pd.Series(True, index=df.index)
        ex, ke = df[m & (df.state == "ROTATION")], df[m & (df.state != "ROTATION")]
        gate.append({"block": blk, "n_all": int(m.sum()), "n_excluded": len(ex), "frac_excluded": len(ex) / int(m.sum()),
                     "excluded_gross": float(ex.nx_gross.mean()), "excluded_net": float(ex.nx_net.mean()),
                     "retained_gross": float(ke.nx_gross.mean()), "retained_net": float(ke.nx_net.mean()),
                     "all_gross": float(df[m].nx_gross.mean()), "all_net": float(df[m].nx_net.mean()),
                     "retained_gross_ex_top1pct": trimmed_mean(ke.nx_gross), "all_gross_ex_top1pct": trimmed_mean(df[m].nx_gross),
                     "excluded_sum_gross_A": float(ex.nx_gross.sum()), "retained_sum_gross_A": float(ke.nx_gross.sum())})
    gate = pd.DataFrame(gate)
    # ROTATION minus rest, session-bootstrap CI, raw and with each side's top 1% of nx_gross removed
    df["nx_gross_trim"] = df.nx_gross.where(df.nx_gross <= df.nx_gross.quantile(0.99))
    for c in ("nx_gross", "nx_gross_trim", "nx_net", "nx_reach_2p0", "fw3_gross", "fw3_eff"):
        for blk in ("A", "B", "ALL"):
            m = (df.block.eq(blk) if blk != "ALL" else pd.Series(True, index=df.index)).to_numpy()
            rot, rest = m & (df.state == "ROTATION").to_numpy(), m & (df.state != "ROTATION").to_numpy()
            lo_ci, hi_ci = boot_diff(df, c, rot, rest)
            gate.loc[gate.block == blk, f"rot_minus_rest_{c}"] = float(df.loc[rot, c].mean() - df.loc[rest, c].mean())
            gate.loc[gate.block == blk, f"rot_minus_rest_{c}_ci"] = f"[{lo_ci:.3f}, {hi_ci:.3f}]"
    # persistence: state at flip i vs flip i+1 / i+3 within the same segment
    pers = []
    for k in (1, 3):
        nxt = df.groupby("seg").state.shift(-k)
        ok = nxt.notna() & (df.state != "NO_HISTORY") & (nxt != "NO_HISTORY")
        for blk in ("A", "B"):
            m = ok & df.block.eq(blk)
            ct = pd.crosstab(df.loc[m, "state"], nxt[m], normalize="index")
            base = nxt[m].value_counts(normalize=True)
            for st in ct.index:
                for st2 in ct.columns:
                    pers.append({"lag": k, "block": blk, "state": st, "next_state": st2, "p": float(ct.loc[st, st2]), "base_rate": float(base[st2])})
    pers = pd.DataFrame(pers)
    t_comp = time.time() - t2

    # ---------------- Phase 6: robustness by direction and MTF group (states only; stop when n small)
    rob = []
    for blk in ("A", "B"):
        for by in ("dir", "mtf_group"):
            for key, g in df[df.block.eq(blk) & (df.state != "NO_HISTORY")].groupby([by, "state"]):
                rob.append({"block": blk, "by": by, "group": str(key[0]), "state": key[1], "n": len(g), "nx_gross": float(g.nx_gross.mean()),
                            "nx_reach_2p0": float(g.nx_reach_2p0.mean()), "fw3_gross": float(g.fw3_gross.mean()),
                            "fw3_eff": float(g.fw3_eff.mean()), "small_n": len(g) < 100})
    rob = pd.DataFrame(rob)
    t_rob = time.time() - t2 - t_comp

    # ---------------- controls + persistence (Spearman; within-segment lags; development sessions pooled)
    def sp(x, y):
        z = pd.concat([x, y], axis=1).dropna()
        return round(float(z.corr("spearman").iloc[0, 1]), 3)
    gs = df.groupby("seg")
    rng_atr = (df.reg_hi - df.reg_lo) / df.atr
    rng_pts = df.reg_hi - df.reg_lo
    controls = {
        "feature_positive_controls": {"flips_30m~dur_mean_3": sp(df.flips_30m, df.dur_mean_3), "eff_5~terr_ratio_5": sp(df.eff_5, df.terr_ratio_5),
                                      "eff_3~eff_clock_30m": sp(df.eff_3, df.eff_clock_30m)},
        "hindsight_contemporaneous": {"fw3_eff~fw3_gross": sp(df.fw3_eff, df.fw3_gross), "fw3_escape~fw3_gross": sp(df.fw3_escape, df.fw3_gross),
                                      "nx_disp~nx_gross": sp(df.nx_disp, df.nx_gross)},
        "regime_autocorrelation": {f"lag{k}": {"duration": sp(df.nx_dur_min, gs.nx_dur_min.shift(k)), "abs_disp_atr": sp(df.nx_disp.abs(), gs.nx_disp.shift(k).abs()),
                                               "gross": sp(df.nx_gross, gs.nx_gross.shift(k)), "range_atr": sp(rng_atr, rng_atr.groupby(df.seg).shift(k)),
                                               "range_points": sp(rng_pts, rng_pts.groupby(df.seg).shift(k)), "atr": sp(df.atr, gs.atr.shift(k))} for k in (1, 2, 3)},
        "forward_state_persistence_non_overlapping": {"fw3_eff(i)~fw3_eff(i+3)": sp(df.fw3_eff, gs.fw3_eff.shift(-3)),
                                                      "fw3_gross(i)~fw3_gross(i+3)": sp(df.fw3_gross, gs.fw3_gross.shift(-3)),
                                                      "fw3_flips_per_30m(i)~(i+3)": sp(df.fw3_flips_per_30m, gs.fw3_flips_per_30m.shift(-3)),
                                                      "fw3_rotational(i)~(i+3)": sp(df.fw3_rotational, gs.fw3_rotational.shift(-3))},
        "feature_vs_outcome_spearman": {f: {o: sp(df[f], df[o]) for o in ("nx_gross", "nx_dur_min", "fw3_gross", "fw3_eff", "fw3_flips_per_30m", "fw3_escape")}
                                        for f in PRIMARY},
    }
    sgn = spread[spread.block != "ALL"].pivot(index="feature", columns="block")
    controls["sign_agreement_A_vs_B"] = {c: int((np.sign(sgn[(f"{c}_top_minus_bottom", "A")]) == np.sign(sgn[(f"{c}_top_minus_bottom", "B")])).sum())
                                         for c in ("nx_gross", "fw3_gross", "fw3_eff")}
    controls["n_features"] = len(PRIMARY)
    (OUT / "CONTROLS_AND_PERSISTENCE.json").write_text(json.dumps(controls, indent=2) + "\n", encoding="utf-8")

    OUT.mkdir(exist_ok=True)
    keep =["regime_start_ns", "session", "block", "seg", "dir", "t0_ns", "terminal_ts", "start_px", "end_px", "start_price_1m", "reg_hi", "reg_lo",
            "atr", "entry_price", "terminal_exit_price", "hist_regimes", "mtf_group", "rot_score", "state"]
    feat_cols = PRIMARY + ["prev_disp", "dist_same_flip", "n_near_0p25_6", "n_near_1p0_6", "flips_10m", "flips_20m", "htf5_prior_disp", "htf15_prog"]
    df[keep + feat_cols + OUTCOMES + ["fw2_eff", "fw4_eff", "fw2_net", "fw4_net"]].to_parquet(OUT / "REGIME_SEQUENCE_FORWARD_OUTCOMES.parquet", index=False)
    atlas.to_parquet(OUT / "REGIME_SEQUENCE_ATLAS.parquet", index=False)
    spread.to_csv(OUT / "FEATURE_SPREADS.csv", index=False)
    states.to_csv(OUT / "STATE_TABLE.csv", index=False)
    gate.to_csv(OUT / "GATE_ARITHMETIC.csv", index=False)
    pers.to_csv(OUT / "STATE_PERSISTENCE.csv", index=False)
    rob.to_csv(OUT / "ROBUSTNESS_DIR_MTF.csv", index=False)
    chain = {"n_regimes": len(df), "segments": int(df.seg.nunique()), "sessions": int(df.session.nunique()),
             "contiguous_links": int((df.groupby("seg").size() - 1).sum()), "holes_inside_session": int(df.seg.nunique() - df.session.nunique()),
             "state_cuts_block_A": [float(cut_lo), float(cut_hi)], "cost_points_round_trip": COST_PTS,
             "runtime_s": {"features_outcomes": round(t_feat, 1), "atlas_bootstrap": round(t_atlas, 1), "composite": round(t_comp, 1),
                           "robustness": round(t_rob, 1), "total": round(time.time() - t0, 1)}}
    (OUT / "SEQUENCE_RUN.json").write_text(json.dumps(chain, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(chain, indent=1))


if __name__ == "__main__":
    main()
