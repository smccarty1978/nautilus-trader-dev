"""Engine-null residual capture study (extension of nq_post_entry_mechanical_null_2023). No model, no policy.

    python studies/nq_post_entry_mechanical_null_2023/residual_capture/residual_capture.py build|power|analyze

build    re-runs the (in-place extended) mechanical_null.build_session with econ=True: identical original draws
         (parity-checked bit-for-bit against ../artifacts/EVENT_LEVEL.parquet), econ outcomes real + engine-null,
         T0 and +3A anchors on a separate stream, trigger timeline with pre-bar bound AND realized threshold.
power    MDEs from the session-cluster SE of REAL outcomes only (no residual mean is read).
analyze  residual curves under the frozen CONTRACT.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import mechanical_null as mn  # noqa: E402

OUT = HERE / "artifacts"
CONTRACT = json.loads((HERE / "CONTRACT.json").read_text(encoding="utf-8"))
PRIMARY = CONTRACT["anchors"]["primary"]
LAGS = ["trig_rel_entry", "dist_to_trig", "mfe_to_trig", "catchup1"]
LAG_NAMES = {"trig_rel_entry": "trig_pos", "dist_to_trig": "price_to_trig", "mfe_to_trig": "mfe_to_trig", "catchup1": "catchup1"}
CONT = ["final_pnl", "add_mfe", "giveback", "frac_surrendered"]
BIN = ["exit_below_entry", "giveback_ge_1A"]
REPS, SEED = 1000, 20260928
SEG_EDGES = [0, 120, 300, 10_000]
THR_CONT, THR_BIN = 0.10, 0.05


def write(df, name):
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"{name}.csv", index=False)
    df.to_parquet(OUT / f"{name}.parquet", index=False)


def write_json(obj, name):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=2, sort_keys=True, default=mn.pm._jsonable) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- build
def stage_build(workers=10):
    from joblib import Parallel, delayed
    f, pop, split = mn.pm.load_dev()
    tl = pd.read_parquet(mn.PATHSTUDY / "artifacts" / "TRADE_EVENT_TIMELINE.parquet")
    eng = mn.replay_engine()
    arms = pop[["regime_start_ns", "session_close_ts", "terminal_exit_price"] +
               [c for a in mn.ARM.values() for c in (f"{a}_disposition", f"{a}_resolution_seconds")]]
    tj = tl.merge(arms, on="regime_start_ns", how="left")
    jobs = []
    for i, (sess, part) in enumerate(tj.groupby("session")):          # identical enumeration/seeds to the original build
        lo_ts = int(part["t0_ns"].min()) - (mn.POOL_S + 120) * mn.NS
        hi_ts = int(part["session_close_ts"].max())
        es = eng[(eng["ts"] >= lo_ts - 3600 * mn.NS) & (eng["ts"] <= hi_ts)].reset_index(drop=True)
        jobs.append((sess, part, es, mn.SIM_SEED + i))
    res = Parallel(n_jobs=workers, verbose=2)(delayed(mn.build_session)(*a, econ=True) for a in jobs)
    ev = pd.DataFrame([e for evs, _, _, _ in res for e in evs])
    timeline = pd.DataFrame([row for _, _, tlr, _ in res for row in tlr])
    epar = {}
    for _, _, _, p in res:
        for k, (n, mm) in p.items():
            epar.setdefault(k, [0, 0])
            epar[k][0] += n
            epar[k][1] += mm
    blocks = {s: "discovery" for s in split["blocks"]["development_train"]["session_list"]}
    blocks.update({s: "replication" for s in split["blocks"]["development_validation"]["session_list"]})
    ev["block"] = ev["session"].map(blocks)
    # parity 1: original null columns reproduced bit-for-bit
    old = pd.read_parquet(mn.OUT / "EVENT_LEVEL.parquet")
    cols = ["null_p_fixed", "null_fixed_resolved", "null_p_term_reach2", "null_p_giveback_given_reach2", "null_p_term_win",
            "null_sim_unflipped", "trig_rel_entry", "cur", "mfe_through", "fixed_outcome"]
    j = old.merge(ev, on=["regime_start_ns", "anchor"], how="left", suffixes=("_old", "_new"))
    null_par = {c: int((~((j[f"{c}_old"] == j[f"{c}_new"]) | (j[f"{c}_old"].isna() & j[f"{c}_new"].isna()))).sum()) for c in cols}
    null_par["rows_compared"] = len(j)
    null_par["rows_missing_in_new"] = int(j["cur_new"].isna().sum())
    econ_par = {k: {"compared": n, "mismatch": mm} for k, (n, mm) in epar.items()}
    tl_flip = timeline.groupby("regime_start_ns")["engine_flip"].agg(["sum", "last"])
    econ_par["exactly_one_flip_per_trade_at_terminal"] = {"trades": len(tl_flip), "mismatch": int(((tl_flip["sum"] != 1) | (~tl_flip["last"])).sum())}
    audit = {"kind": "residual_capture_build_audit", "events": len(ev), "events_by_anchor": ev["anchor"].value_counts().sort_index().to_dict(),
             "original_null_reproduced_bit_for_bit": null_par, "econ_parity": econ_par,
             "sim_flipped_share_mean": float((ev["null_econ_n_flipped"] / mn.K_SIM).mean()),
             "timeline_rows": len(timeline), "final_20pct_loaded": False}
    audit["PASS"] = (all(v == 0 for k, v in null_par.items() if k not in ("rows_compared",)) and
                     all(v["mismatch"] == 0 for v in econ_par.values()))
    write(ev, "EVENT_ECON")
    write(timeline, "TRIGGER_TIMELINE")
    write_json(audit, "ECON_BUILD_AUDIT.json")
    print(json.dumps(audit, indent=1, default=mn.pm._jsonable))
    if not audit["PASS"]:
        raise SystemExit("INVALID: econ build parity failed")


# ----------------------------------------------------------------------------- helpers
def load_events():
    ev = pd.read_parquet(OUT / "EVENT_ECON.parquet")
    for c in CONT + BIN:
        ev[f"null_{c}"] = ev[f"null_econ_{'p_' if c in BIN else ''}{c}"]
        ev[f"res_{c}"] = ev[f"real_{c}"] - ev[f"null_{c}"]
    ev["seg"] = pd.cut(ev["tod_min"], SEG_EDGES, right=False, labels=False)
    return ev


def boot(sess, cols, stat, reps=REPS, seed=SEED):
    codes, uniq = pd.factorize(sess)
    S = len(uniq)
    agg = {k: np.bincount(codes, weights=np.nan_to_num(v), minlength=S) for k, v in cols.items()}
    point = stat(agg)
    rng = np.random.default_rng(seed)
    draws = [stat({k: v[p] for k, v in agg.items()}) for p in rng.integers(0, S, size=(reps, S))]
    draws = [x for x in draws if np.isfinite(x)]
    lo, hi = np.percentile(draws, [2.5, 97.5]) if draws else (np.nan, np.nan)
    return float(point), float(lo), float(hi), float(np.std(draws)) if draws else np.nan


def mean_ci(d, col):
    d = d[d[col].notna()]
    if len(d) < 30:
        return (np.nan,) * 4, len(d)
    v = d[col].to_numpy(float)
    return boot(d["session"].to_numpy(), {"y": v, "n": np.ones(len(d))}, lambda a: a["y"].sum() / a["n"].sum()), len(d)


# ----------------------------------------------------------------------------- power
def stage_power():
    ev = load_events()
    rows = []
    for x in PRIMARY + [0.0]:
        for b in ("discovery", "replication"):
            e = ev[(ev["anchor"] == x) & (ev["block"] == b)]
            for c in CONT + BIN:
                (_, _, _, se), n = mean_ci(e, f"real_{c}")            # SE of the REAL outcome mean only
                rows.append({"anchor": x, "block": b, "outcome": c, "N": n, "se_mean": se,
                             "MDE_overall_residual": 2.8 * se if np.isfinite(se) else np.nan,
                             "MDE_tercile_residual": 2.8 * se * np.sqrt(3) if np.isfinite(se) else np.nan})
    pw = pd.DataFrame(rows)
    write(pw, "POWER")
    print(pw.pivot_table(index=["outcome", "anchor"], columns="block", values="MDE_tercile_residual").round(3).to_string())


# ----------------------------------------------------------------------------- analyze
def stage_analyze():
    ev = load_events()
    pw = pd.read_parquet(OUT / "POWER.parquet")
    blocks = {"discovery": ev["block"] == "discovery", "replication": ev["block"] == "replication", "pooled": ev["block"].notna()}

    # overall real / null / residual per anchor
    ov = []
    for x in [0.0] + PRIMARY:
        for bname, bm in blocks.items():
            e = ev[bm & (ev["anchor"] == x)]
            row = {"anchor": x, "block": bname, "N": len(e)}
            for c in CONT + BIN + ["boundary_component", "fill_gap", "term_s"]:
                row[f"real_{c}"] = e[f"real_{c}"].mean()
                nc = f"null_econ_{'p_' if c in BIN else ''}{c}"
                row[f"null_{c}"] = e[nc].mean()
                if c in CONT + BIN:
                    (p, lo, hi, _), _ = mean_ci(e, f"res_{c}")
                    row[f"res_{c}"], row[f"res_{c}_lo"], row[f"res_{c}_hi"] = p, lo, hi
            ov.append(row)
    overall = pd.DataFrame(ov)
    write(overall, "OVERALL_REAL_NULL_RESIDUAL")

    # residual curves by lag tercile (discovery cutpoints per anchor)
    rc = []
    for x in PRIMARY:
        ex = ev[ev["anchor"] == x]
        disc = ex[ex["block"] == "discovery"]
        for lag in LAGS:
            if disc[lag].notna().sum() < 90:
                continue
            q1, q2 = np.quantile(disc[lag].dropna(), [1 / 3, 2 / 3])
            ex_t = np.where(ex[lag] <= q1, 0, np.where(ex[lag] > q2, 2, 1))
            for bname in blocks:
                e = ex[blocks[bname].loc[ex.index]]
                tt = ex_t[blocks[bname].loc[ex.index].to_numpy()]
                for k in range(3):
                    g = e[tt == k]
                    row = {"anchor": x, "lag": LAG_NAMES[lag], "tercile": ["low", "mid", "high"][k], "block": bname, "N": len(g),
                           "lag_median": float(g[lag].median()) if len(g) else np.nan}
                    for c in CONT + BIN:
                        row[f"real_{c}"] = g[f"real_{c}"].mean()
                        row[f"null_{c}"] = g[f"null_{c}"].mean()
                        (p, lo, hi, _), _ = mean_ci(g, f"res_{c}")
                        row[f"res_{c}"], row[f"res_{c}_lo"], row[f"res_{c}_hi"] = p, lo, hi
                    rc.append(row)
    curves = pd.DataFrame(rc)
    write(curves, "RESIDUAL_CURVES")

    # Spearman(lag, residual) and Spearman(lag, raw) per anchor (pooled + blocks)
    sp = []
    for x in PRIMARY:
        for bname, bm in blocks.items():
            e = ev[bm & (ev["anchor"] == x)]
            for lag in LAGS:
                for c in ("final_pnl", "giveback", "add_mfe"):
                    ok = e[lag].notna() & e[f"res_{c}"].notna()
                    sp.append({"anchor": x, "block": bname, "lag": LAG_NAMES[lag], "outcome": c,
                               "rho_raw": float(e.loc[ok, lag].rank().corr(e.loc[ok, f"real_{c}"].rank())),
                               "rho_null": float(e.loc[ok, lag].rank().corr(e.loc[ok, f"null_{c}"].rank())),
                               "rho_residual": float(e.loc[ok, lag].rank().corr(e.loc[ok, f"res_{c}"].rank()))})
    write(pd.DataFrame(sp), "LAG_RANK_CORRELATIONS")

    # state evaluation (frozen)
    def meaningful(p, lo, hi, thr):
        return bool(np.isfinite(p) and abs(p) >= thr and (lo > 0 or hi < 0))

    def rep_label(dp, row_rep, c, x):
        rp, rlo, rhi = row_rep[f"res_{c}"], row_rep[f"res_{c}_lo"], row_rep[f"res_{c}_hi"]
        mde = pw[(pw.anchor == x) & (pw.block == "replication") & (pw.outcome == c)]["MDE_tercile_residual"].iloc[0]
        if not np.isfinite(rp) or np.sign(rp) != np.sign(dp):
            return "CONTRADICTED"
        if rlo > 0 or rhi < 0:
            return "REPRODUCED"
        return "NOT_SHOWN_AT_AVAILABLE_POWER" if mde > abs(dp) else "CONTRADICTED"

    states = []
    for lag in LAG_NAMES.values():
        for terc in ("low", "mid", "high"):
            for sname, need in (("excess_giveback", {"giveback": +1, "final_pnl": -1}), ("excess_continuation", {"add_mfe": +1, "final_pnl": +1})):
                hits = []
                for x in PRIMARY:
                    d = curves[(curves.anchor == x) & (curves.lag == lag) & (curves.tercile == terc) & (curves.block == "discovery")]
                    r = curves[(curves.anchor == x) & (curves.lag == lag) & (curves.tercile == terc) & (curves.block == "replication")]
                    if not len(d) or not len(r):
                        hits.append((x, False, None))
                        continue
                    d, r = d.iloc[0], r.iloc[0]
                    ok = all(meaningful(d[f"res_{c}"], d[f"res_{c}_lo"], d[f"res_{c}_hi"], THR_CONT) and np.sign(d[f"res_{c}"]) == s for c, s in need.items())
                    labels = {c: rep_label(d[f"res_{c}"], r, c, x) for c in need} if ok else None
                    hits.append((x, ok and all(v != "CONTRADICTED" for v in labels.values()), labels))
                run, best = [], []
                for x, ok, lab in hits:
                    if ok:
                        run.append((x, lab))
                    else:
                        if len(run) >= 2:
                            best.append(run)
                        run = []
                if len(run) >= 2:
                    best.append(run)
                disc_only = [x for x, ok, lab in hits if lab is not None]
                states.append({"state": sname, "lag": lag, "tercile": terc, "qualifying_runs": [[{"anchor": a, "replication": l} for a, l in rr] for rr in best],
                               "discovery_meaningful_anchors": disc_only, "PASS": bool(best)})
    st = pd.DataFrame(states)
    gb_pass, ct_pass = st[(st.state == "excess_giveback") & st.PASS], st[(st.state == "excess_continuation") & st.PASS]
    # overall uniform final_pnl residual
    uni = []
    for x in PRIMARY:
        d = overall[(overall.anchor == x) & (overall.block == "discovery")].iloc[0]
        r = overall[(overall.anchor == x) & (overall.block == "replication")].iloc[0]
        if meaningful(d["res_final_pnl"], d["res_final_pnl_lo"], d["res_final_pnl_hi"], THR_CONT):
            uni.append({"anchor": x, "disc": d["res_final_pnl"], "replication": rep_label(d["res_final_pnl"], r, "final_pnl", x)})
    uniform = [u for u in uni if u["replication"] != "CONTRADICTED"]
    disc_mde = pw[(pw.block == "discovery") & (pw.outcome == "final_pnl") & pw.anchor.isin(PRIMARY)]["MDE_tercile_residual"]
    if len(gb_pass) and len(ct_pass):
        verdict = "MIXED_RESIDUAL"
    elif len(gb_pass):
        verdict = "EXCESS_GIVEBACK_RESIDUAL"
    elif len(ct_pass):
        verdict = "EXCESS_CONTINUATION_RESIDUAL"
    elif (disc_mde > THR_CONT).all():
        verdict = "INCONCLUSIVE"
    else:
        verdict = "TRIGGER_LAG_IS_TRADEOFF - MECHANICALLY_NEUTRAL"

    # speed in residual space (tod-stratified tercile contrast slow - fast)
    spd = []
    for x in PRIMARY:
        ex = ev[ev["anchor"] == x]
        disc = ex[ex["block"] == "discovery"]
        q1, q2 = np.quantile(disc["time_to_anchor_s"], [1 / 3, 2 / 3])
        for bname, bm in blocks.items():
            for excl in (False, True):
                e = ex[bm.loc[ex.index]]
                if excl:
                    e = e[e["time_to_close_s"] >= 3600]
                for c in ("final_pnl", "giveback", "add_mfe"):
                    for kind in ("real", "null", "res"):
                        col = f"{kind}_{c}"
                        num, den, cols = 0.0, 0.0, {}
                        segs = [s for s in e["seg"].dropna().unique()]
                        hi_m, lo_m = (e["time_to_anchor_s"] > q2).to_numpy(), (e["time_to_anchor_s"] <= q1).to_numpy()
                        v = e[col].to_numpy(float)
                        for s in segs:
                            m = (e["seg"] == s).to_numpy()
                            cols[f"yh{s}"], cols[f"nh{s}"] = np.where(hi_m & m, v, 0), (hi_m & m).astype(float)
                            cols[f"yl{s}"], cols[f"nl{s}"] = np.where(lo_m & m, v, 0), (lo_m & m).astype(float)

                        def stat(a, segs=segs):
                            nu, de = 0.0, 0.0
                            for s in segs:
                                nh, nl = a[f"nh{s}"].sum(), a[f"nl{s}"].sum()
                                if nh and nl:
                                    w = nh + nl
                                    nu += w * (a[f"yh{s}"].sum() / nh - a[f"yl{s}"].sum() / nl)
                                    de += w
                            return nu / de if de else np.nan
                        p, lo, hi, _ = boot(e["session"].to_numpy(), cols, stat)
                        spd.append({"anchor": x, "block": bname, "excl_last_hour": excl, "outcome": c, "kind": kind,
                                    "slow_minus_fast": p, "lo": lo, "hi": hi})
    write(pd.DataFrame(spd), "SPEED_RESIDUAL")

    # speed -> lag link (descriptive): median trigger position by speed tercile
    link = []
    for x in PRIMARY:
        ex = ev[ev["anchor"] == x]
        disc = ex[ex["block"] == "discovery"]
        q1, q2 = np.quantile(disc["time_to_anchor_s"], [1 / 3, 2 / 3])
        for lab, m in (("fast", ex["time_to_anchor_s"] <= q1), ("mid", (ex["time_to_anchor_s"] > q1) & (ex["time_to_anchor_s"] <= q2)), ("slow", ex["time_to_anchor_s"] > q2)):
            g = ex[m]
            link.append({"anchor": x, "speed": lab, "N": len(g), **{f"median_{l}": float(g[l].median()) for l in LAGS},
                         **{f"mean_real_{c}": g[f"real_{c}"].mean() for c in ("final_pnl", "giveback", "add_mfe")},
                         **{f"mean_null_{c}": g[f"null_{c}"].mean() for c in ("final_pnl", "giveback", "add_mfe")}})
    write(pd.DataFrame(link), "SPEED_LAG_LINK")

    # protection map: trigger position bins at each anchor
    bins = [-np.inf, -1.0, -0.5, 0.0, 0.5, 1.0, np.inf]
    labels = ["< -1A", "-1A..-0.5A", "-0.5A..0", "0..+0.5A", "+0.5A..+1A", ">= +1A"]
    pm_rows = []
    for x in PRIMARY:
        e = ev[ev["anchor"] == x].copy()
        e["pbin"] = pd.cut(e["trig_rel_entry"], bins, labels=labels, right=False)
        for lab, g in e.groupby("pbin", observed=False):
            pm_rows.append({"anchor": x, "trigger_bin": lab, "N": len(g), "share": len(g) / len(e) if len(e) else np.nan,
                            "real_exit_below_entry": g["real_exit_below_entry"].mean(), "null_exit_below_entry": g["null_exit_below_entry"].mean(),
                            "real_final_pnl": g["real_final_pnl"].mean(), "null_final_pnl": g["null_final_pnl"].mean(),
                            "real_add_mfe": g["real_add_mfe"].mean(), "null_add_mfe": g["null_add_mfe"].mean(),
                            "real_giveback": g["real_giveback"].mean(), "null_giveback": g["null_giveback"].mean()})
        pm_rows.append({"anchor": x, "trigger_bin": "ALL", "N": len(e), "median_trig_rel_entry": float(e["trig_rel_entry"].median()),
                        "protected_share_of_mfe_median": float((e["trig_rel_entry"].clip(lower=0) / e["mfe_through"]).median()),
                        "p_trigger_below_entry": float((e["trig_rel_entry"] < 0).mean())})
    write(pd.DataFrame(pm_rows), "PROTECTION_MAP")

    # 2D map: trigger lag tercile x additional-MFE outcome (real vs null)
    two = []
    for x in PRIMARY:
        ex = ev[ev["anchor"] == x]
        disc = ex[ex["block"] == "discovery"]
        q1, q2 = np.quantile(disc["mfe_to_trig"], [1 / 3, 2 / 3])
        t_ = np.where(ex["mfe_to_trig"] <= q1, "low", np.where(ex["mfe_to_trig"] > q2, "high", "mid"))
        for lag_t in ("low", "mid", "high"):
            g = ex[t_ == lag_t]
            for lo_, hi_, lab in ((-np.inf, 0.5, "add_mfe < 0.5A"), (0.5, 1.5, "0.5-1.5A"), (1.5, np.inf, ">= 1.5A")):
                m = (g["real_add_mfe"] >= lo_) & (g["real_add_mfe"] < hi_)
                two.append({"anchor": x, "mfe_to_trig_tercile": lag_t, "add_mfe_band": lab, "real_share": float(m.mean()),
                            "real_mean_giveback_in_band": float(g.loc[m, "real_giveback"].mean()) if m.any() else np.nan,
                            "real_mean_final_pnl_in_band": float(g.loc[m, "real_final_pnl"].mean()) if m.any() else np.nan})
    write(pd.DataFrame(two), "LAG_BY_ADD_MFE_MAP")

    # capture (T0 events)
    cap = []
    t0 = ev[ev["anchor"] == 0.0].copy()
    t0["q"] = pd.qcut(t0["real_final_mfe"], 5, labels=False)
    for bname, bm in blocks.items():
        e = t0[bm.loc[t0.index]]
        for lab, g in (("all", e), ("top_final_mfe_quintile (outcome-defined)", e[e["q"] == 4])):
            row = {"block": bname, "group": lab, "N": len(g)}
            for kind in ("real", "null"):
                row[f"{kind}_final_mfe"] = g[f"{kind}_final_mfe"].mean()
                row[f"{kind}_final_pnl"] = g[f"{kind}_final_pnl"].mean()
                row[f"{kind}_giveback"] = g[f"{kind}_giveback"].mean()
                row[f"{kind}_capture_ratio_of_means"] = g[f"{kind}_final_pnl"].mean() / g[f"{kind}_final_mfe"].mean()
                row[f"{kind}_frac_surrendered"] = g[f"{kind}_frac_surrendered"].mean()
            for c in ("final_pnl", "giveback", "frac_surrendered"):
                (p, lo, hi, _), _ = mean_ci(g, f"res_{c}")
                row[f"res_{c}"], row[f"res_{c}_lo"], row[f"res_{c}_hi"] = p, lo, hi
            cap.append(row)
    write(pd.DataFrame(cap), "CAPTURE")

    # robustness for claimed states only
    rb = []
    for s in pd.concat([gb_pass, ct_pass]).itertuples():
        lag = [k for k, v in LAG_NAMES.items() if v == s.lag][0]
        for run in s.qualifying_runs:
            for item in run:
                x = item["anchor"]
                ex = ev[ev["anchor"] == x]
                disc = ex[ex["block"] == "discovery"]
                q1, q2 = np.quantile(disc[lag].dropna(), [1 / 3, 2 / 3])
                sel = ex[(ex[lag] <= q1) if s.tercile == "low" else (ex[lag] > q2) if s.tercile == "high" else ((ex[lag] > q1) & (ex[lag] <= q2))]
                for gname, gcol in (("dir", "dir"), ("seg", "seg")):
                    for gv, g in sel.groupby(gcol):
                        (p, lo, hi, _), n = mean_ci(g, "res_final_pnl")
                        rb.append({"state": s.state, "lag": s.lag, "tercile": s.tercile, "anchor": x, "group": gname, "value": str(gv), "N": n,
                                   "res_final_pnl": p, "lo": lo, "hi": hi})
    write(pd.DataFrame(rb), "ROBUSTNESS")

    res = {"kind": "residual_capture_results", "verdict": verdict, "uniform_final_pnl_residual": uniform,
           "excess_giveback_states": gb_pass.to_dict("records"), "excess_continuation_states": ct_pass.to_dict("records"),
           "all_states": st.to_dict("records"), "discovery_final_pnl_tercile_MDE": disc_mde.tolist(),
           "contract_sha256": mn.sha_file(HERE / "CONTRACT.json")}
    write_json(res, "RESIDUAL_RESULTS.json")
    pd.set_option("display.width", 250)
    keep = ["anchor", "block", "N"] + [f"{k}_{c}" for c in ("final_pnl", "giveback", "add_mfe", "frac_surrendered", "exit_below_entry") for k in ("real", "null", "res")] + ["res_final_pnl_lo", "res_final_pnl_hi", "real_fill_gap", "null_fill_gap"]
    print(overall[keep].round(3).to_string())
    print(json.dumps({"verdict": verdict, "uniform": uniform, "gb": len(gb_pass), "ct": len(ct_pass)}, indent=1, default=mn.pm._jsonable))


if __name__ == "__main__":
    stage = sys.argv[1]
    {"build": stage_build, "power": stage_power, "analyze": stage_analyze}[stage]()
