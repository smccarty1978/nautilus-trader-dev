"""Descriptive analysis under the frozen artifacts/DESIGN.json (no model of any kind).

    python studies/nq_post_entry_mechanical_null_2023/analyze.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mechanical_null as mn  # noqa: E402

A = mn.OUT
DESIGN = json.loads((A / "DESIGN.json").read_text(encoding="utf-8"))
REPS, SEED = 1000, 20260927
PRIMARY = DESIGN["variables"]["primary"]
SECONDARY = [v for v in DESIGN["variables"]["secondary"] if v not in ("dir", "tod_min")] + ["tod_min"]
ANCH = DESIGN["anchors"]["primary"]
SEG_EDGES = [0, 120, 300, 10_000]          # minutes after 08:30 CT
MEANINGFUL, ADJ = 0.05, 2


def cluster_boot(sess: np.ndarray, cols: dict, stat, reps=REPS, seed=SEED):
    """Session-cluster bootstrap. cols: name -> per-row arrays; stat(agg) -> float, agg = per-session sums."""
    codes, uniq = pd.factorize(sess)
    S = len(uniq)
    agg = {k: np.bincount(codes, weights=v, minlength=S) for k, v in cols.items()}
    point = stat(agg)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, S, size=(reps, S))
    draws = []
    for p in pick:
        sub = {k: v[p] for k, v in agg.items()}
        val = stat(sub)
        if np.isfinite(val):
            draws.append(val)
    lo, hi = (np.percentile(draws, [2.5, 97.5]) if draws else (np.nan, np.nan))
    return float(point), float(lo), float(hi)


def mean_stat(agg):
    return agg["y"].sum() / agg["n"].sum() if agg["n"].sum() else np.nan


def level_residual(df, y, null):
    ok = df[y].notna() & df[null].notna()
    d = df[ok]
    r = (d[y] - d[null]).to_numpy(float)
    return cluster_boot(d["session"].to_numpy(), {"y": r, "n": np.ones(len(d))}, mean_stat), int(len(d))


def tercile_delta(df, var, resid_col, cuts, strata=None):
    """delta = mean(resid | var > q2) - mean(resid | var <= q1); strata -> N-weighted mean of within-stratum deltas."""
    d = df[df[var].notna() & df[resid_col].notna()]
    if len(d) == 0 or cuts is None:
        return (np.nan, np.nan, np.nan), 0
    q1, q2 = cuts
    lo_m, hi_m = (d[var] <= q1).to_numpy(), (d[var] > q2).to_numpy()
    r = d[resid_col].to_numpy(float)
    st = np.zeros(len(d), int) if strata is None else d[strata].to_numpy()
    cols = {}
    for s in np.unique(st):
        m = st == s
        cols[f"yh{s}"], cols[f"nh{s}"] = r * (hi_m & m), (hi_m & m).astype(float)
        cols[f"yl{s}"], cols[f"nl{s}"] = r * (lo_m & m), (lo_m & m).astype(float)
    keys = np.unique(st)

    def stat(agg):
        num, den = 0.0, 0.0
        for s in keys:
            nh, nl = agg[f"nh{s}"].sum(), agg[f"nl{s}"].sum()
            if nh == 0 or nl == 0:
                continue
            w = nh + nl
            num += w * (agg[f"yh{s}"].sum() / nh - agg[f"yl{s}"].sum() / nl)
            den += w
        return num / den if den else np.nan
    return cluster_boot(d["session"].to_numpy(), cols, stat), int(lo_m.sum() + hi_m.sum())


def mde(p, n):
    if n <= 0 or not np.isfinite(p):
        return np.nan
    return float(2.80 * np.sqrt(max(p * (1 - p), 1e-9) * (6.0 / n)) * np.sqrt(1.3))


def main():
    ev = pd.read_parquet(A / "EVENT_LEVEL.parquet")
    f, pop, split = mn.pm.load_dev()
    st = pop[["regime_start_ns", "dir_1m", "dir_5m", "dir_15m", "dir_1h"]].copy()
    st["mtf_state"] = st[["dir_1m", "dir_5m", "dir_15m", "dir_1h"]].apply(lambda r: "/".join("L" if v > 0 else "S" for v in r), axis=1)
    ev = ev.merge(st[["regime_start_ns", "mtf_state"]], on="regime_start_ns", how="left")
    ev["seg"] = pd.cut(ev["tod_min"], SEG_EDGES, right=False, labels=False)
    # outcomes and residual columns
    ev["yA"] = ev["fixed_outcome"].where(ev["fixed_outcome"].isin([0.0, 1.0]) & (ev["fixed_eligible"] == 1))
    ev["N1"] = (ev["anchor"] + 1) / 3
    ev["N1c"] = (ev["cur"] + 1) / 3
    ev["rA_N2"] = ev["yA"] - ev["null_p_fixed"]
    ev["yB"] = ev["term_reach2"].where(ev["anchor"] < 2.0)
    ev["rB_N3"] = ev["yB"] - ev["null_p_term_reach2"]
    ev["yG"] = (1 - ev["win"]).where(ev["term_reach2"] == 1).where(ev["anchor"].isin(DESIGN_GB := [1.0, 1.5, 2.0]))
    ev["nullG"] = np.where(ev["anchor"] == 2.0, 1 - ev["null_p_term_win"], ev["null_p_giveback_given_reach2"])
    ev["rG_N3"] = ev["yG"] - ev["nullG"]
    blocks = {"discovery": ev["block"] == "discovery", "replication": ev["block"] == "replication", "pooled": ev["block"].notna()}

    # ------------------------------------------------------------------ power (before any effect is read)
    pw = []
    for x in ANCH + [2.0]:
        for bname, bm in blocks.items():
            e = ev[bm & (ev["anchor"] == x)]
            for oname, y in (("A", "yA"), ("B", "yB"), ("G", "yG")):
                yy = e[y].dropna()
                if len(yy):
                    pw.append({"anchor": x, "block": bname, "outcome": oname, "N": len(yy), "rate": float(yy.mean()),
                               "MDE_tercile_delta": mde(float(yy.mean()), len(yy))})
    power = pd.DataFrame(pw)
    mn_write(power, "POWER")

    # ------------------------------------------------------------------ Phase 1 / 5 level residuals
    lv = []
    for x in ANCH + [2.0]:
        for bname, bm in blocks.items():
            e = ev[bm & (ev["anchor"] == x)]
            row = {"anchor": x, "block": bname}
            if x < 2.0:
                a = e[e["yA"].notna()]
                row.update({"A_N": len(a), "A_actual": a["yA"].mean(), "A_N1": a["N1"].mean(), "A_N1c": a["N1c"].mean(),
                            "A_N2": a["null_p_fixed"].mean(), "A_censored_or_ambiguous": int(((e["fixed_eligible"] == 1) & e["yA"].isna()).sum()),
                            "A_excluded_adv1_before": int((e["fixed_eligible"] == 0).sum())})
                for nm in ("N1", "N1c", "null_p_fixed"):
                    (p, lo, hi), _ = level_residual(a, "yA", nm)
                    row[f"A_resid_{nm}"], row[f"A_resid_{nm}_lo"], row[f"A_resid_{nm}_hi"] = p, lo, hi
                b = e[e["yB"].notna()]
                row.update({"B_N": len(b), "B_actual": b["yB"].mean(), "B_N3": b["null_p_term_reach2"].mean()})
                (p, lo, hi), _ = level_residual(b, "yB", "null_p_term_reach2")
                row["B_resid_N3"], row["B_resid_N3_lo"], row["B_resid_N3_hi"] = p, lo, hi
            g = e[e["yG"].notna()]
            if len(g):
                row.update({"G_N": len(g), "G_actual": g["yG"].mean(), "G_N3": g["nullG"].mean()})
                (p, lo, hi), _ = level_residual(g, "yG", "nullG")
                row["G_resid_N3"], row["G_resid_N3_lo"], row["G_resid_N3_hi"] = p, lo, hi
            lv.append(row)
    levels = pd.DataFrame(lv)
    mn_write(levels, "LEVEL_RESIDUALS")

    # ------------------------------------------------------------------ Phase 3/5/6 path effects
    outcomes = {"A_res_N2": ("yA", "rA_N2", ANCH), "A_raw": ("yA", "yA", ANCH), "B_res_N3": ("yB", "rB_N3", ANCH),
                "B_raw": ("yB", "yB", ANCH), "G_res_N3": ("yG", "rG_N3", [1.0, 1.5, 2.0]), "G_raw": ("yG", "yG", [1.0, 1.5, 2.0])}
    rows = []
    for oname, (ycol, rcol, anchors) in outcomes.items():
        for x in anchors:
            ex = ev[(ev["anchor"] == x) & ev[ycol].notna() & ev[rcol].notna()]
            disc = ex[ex["block"] == "discovery"]
            for var in PRIMARY + SECONDARY:
                if disc[var].nunique() < 3:
                    cuts = None
                else:
                    cuts = tuple(np.quantile(disc[var].dropna(), [1 / 3, 2 / 3]))
                    if cuts[0] == cuts[1]:
                        cuts = None
                for bname in ("discovery", "replication", "pooled"):
                    e = ex if bname == "pooled" else ex[ex["block"] == bname]
                    variants = [("plain", None)]
                    if var == "time_to_anchor_s":
                        variants = [("tod_stratified", "seg"), ("plain", None), ("tod_stratified_excl_last_hour", "seg")]
                    for vname, strata in variants:
                        ee = e[e["time_to_close_s"] >= 3600] if vname.endswith("excl_last_hour") else e
                        (p, lo, hi), n = tercile_delta(ee, var, rcol, cuts, strata)
                        rows.append({"outcome": oname, "anchor": x, "variable": var, "variant": vname, "block": bname, "n_used": n,
                                     "delta": p, "lo": lo, "hi": hi, "primary": var in PRIMARY,
                                     "meaningful": bool(np.isfinite(p) and abs(p) >= MEANINGFUL and (lo > 0 or hi < 0))})
    eff = pd.DataFrame(rows)
    mn_write(eff, "PATH_EFFECTS")

    # trigger conditioning for speed (B and G): raw delta within trig_rel_entry terciles
    tc = []
    for oname, ycol, anchors in (("B_raw", "yB", ANCH), ("G_raw", "yG", [1.0, 1.5, 2.0])):
        for x in anchors:
            ex = ev[(ev["anchor"] == x) & ev[ycol].notna()].copy()
            disc = ex[ex["block"] == "discovery"]
            tcut = np.quantile(disc["trig_rel_entry"], [1 / 3, 2 / 3])
            ex["trig_t"] = np.digitize(ex["trig_rel_entry"], tcut)
            scut = tuple(np.quantile(disc["time_to_anchor_s"], [1 / 3, 2 / 3]))
            for bname in ("discovery", "replication", "pooled"):
                e = ex if bname == "pooled" else ex[ex["block"] == bname]
                (p, lo, hi), n = tercile_delta(e, "time_to_anchor_s", ycol, scut, "trig_t")
                tc.append({"outcome": oname, "anchor": x, "block": bname, "speed_delta_within_trigger_terciles": p, "lo": lo, "hi": hi, "n": n,
                           "trig_rel_entry_median_fast": float(e.loc[e["time_to_anchor_s"] <= scut[0], "trig_rel_entry"].median()),
                           "trig_rel_entry_median_slow": float(e.loc[e["time_to_anchor_s"] > scut[1], "trig_rel_entry"].median()),
                           "rate_by_trig_tercile": [float(e.loc[e["trig_t"] == k, ycol].mean()) for k in range(3)]})
    trig = pd.DataFrame(tc)
    trig["rate_by_trig_tercile"] = trig["rate_by_trig_tercile"].astype(str)
    mn_write(trig, "TRIGGER_CONDITIONING")

    # three-class tables at +1A / +1.5A
    tcr = []
    for x in (1.0, 1.5):
        e = ev[ev["anchor"] == x].copy()
        e["cls"] = np.where(e["term_reach2"] == 0, "fail_before_plus2", np.where(e["win"] == 1, "plus2_then_win", "plus2_then_giveback"))
        disc = e[e["block"] == "discovery"]
        scut = np.quantile(disc["time_to_anchor_s"], [1 / 3, 2 / 3])
        e["speed_t"] = pd.Series(np.digitize(e["time_to_anchor_s"], scut)).map({0: "fast", 1: "mid", 2: "slow"}).to_numpy()
        for (blk, sp), g in e.groupby(["block", "speed_t"]):
            tcr.append({"anchor": x, "block": blk, "speed_tercile": sp, "N": len(g), **{c: float((g["cls"] == c).mean()) for c in ("fail_before_plus2", "plus2_then_giveback", "plus2_then_win")},
                        "giveback_share_of_plus2": float((g["cls"] == "plus2_then_giveback").sum() / max((g["term_reach2"] == 1).sum(), 1)),
                        "median_trig_rel_entry": float(g["trig_rel_entry"].median())})
        for cls, g in e.groupby("cls"):
            tcr.append({"anchor": x, "block": "pooled", "class": cls, "N": len(g), **{f"median_{v}": float(g[v].median()) for v in PRIMARY + ["trig_rel_entry", "dist_to_trig"]}})
    mn_write(pd.DataFrame(tcr), "GIVEBACK_THREE_CLASS")

    # ------------------------------------------------------------------ pass evaluation (frozen rule)
    def passes(sub_disc, sub_rep, pw_out):
        """sub_*: rows for one (outcome, variable, variant) keyed by anchor, ordered."""
        anchors = sorted(sub_disc["anchor"])
        mean_ok = dict(zip(sub_disc["anchor"], sub_disc["meaningful"]))
        runs, best = [], []
        cur = []
        for a in anchors:
            if mean_ok[a]:
                cur.append(a)
            else:
                if len(cur) >= ADJ:
                    runs.append(cur)
                cur = []
        if len(cur) >= ADJ:
            runs.append(cur)
        for run in runs:
            dd = sub_disc.set_index("anchor").loc[run, "delta"]
            rr = sub_rep.set_index("anchor").loc[run, "delta"]
            same = bool((np.sign(dd) == np.sign(rr)).all())
            mag = bool(rr.abs().mean() >= 0.5 * dd.abs().mean())
            mdes = pw_out.set_index("anchor").loc[run, "MDE_tercile_delta"]
            powered = bool((mdes <= 0.10).all())
            best.append({"anchors": run, "disc_delta": dd.tolist(), "rep_delta": rr.tolist(), "same_sign": same, "magnitude_ok": mag,
                         "rep_powered": powered, "PASS": same and mag and powered})
        return best
    evaluations = []
    omap = {"A_res_N2": "A", "B_res_N3": "B", "G_res_N3": "G", "A_raw": "A", "B_raw": "B", "G_raw": "G"}
    for (oname, var, vname), g in eff[eff["block"] != "pooled"].groupby(["outcome", "variable", "variant"]):
        if vname == "tod_stratified_excl_last_hour":
            continue
        if var == "time_to_anchor_s" and vname == "plain":
            continue                                          # speed is tested tod-stratified (frozen)
        pw_out = power[(power["block"] == "replication") & (power["outcome"] == omap[oname])]
        res = passes(g[g["block"] == "discovery"], g[g["block"] == "replication"], pw_out)
        evaluations.append({"outcome": oname, "variable": var, "variant": vname, "primary": var in PRIMARY, "runs": res,
                            "PASS": any(r["PASS"] for r in res)})
    evals = pd.DataFrame(evaluations)
    # level residual pass
    def level_pass(col, anchors):
        d = levels[(levels["block"] == "discovery") & levels["anchor"].isin(anchors)].set_index("anchor")
        r = levels[(levels["block"] == "replication") & levels["anchor"].isin(anchors)].set_index("anchor")
        mean_ok = [(a, bool(abs(d.loc[a, col]) >= MEANINGFUL and (d.loc[a, f"{col}_lo"] > 0 or d.loc[a, f"{col}_hi"] < 0))) for a in anchors]
        runs, cur = [], []
        for a, ok in mean_ok:
            if ok:
                cur.append(a)
            else:
                if len(cur) >= ADJ:
                    runs.append(cur)
                cur = []
        if len(cur) >= ADJ:
            runs.append(cur)
        out = []
        for run in runs:
            same = bool((np.sign(d.loc[run, col]) == np.sign(r.loc[run, col])).all())
            mag = bool(r.loc[run, col].abs().mean() >= 0.5 * d.loc[run, col].abs().mean())
            out.append({"anchors": run, "disc": d.loc[run, col].tolist(), "rep": r.loc[run, col].tolist(), "PASS": same and mag})
        return {"runs": out, "PASS": any(o["PASS"] for o in out)}
    lvl = {"A_vs_N1c": level_pass("A_resid_N1c", ANCH), "A_vs_N1": level_pass("A_resid_N1", ANCH),
           "A_vs_N2": level_pass("A_resid_null_p_fixed", ANCH), "B_vs_N3": level_pass("B_resid_N3", ANCH),
           "G_vs_N3": level_pass("G_resid_N3", [1.0, 1.5, 2.0])}
    prim = evals[evals["primary"] & evals["outcome"].isin(["A_res_N2", "B_res_N3", "G_res_N3"])]
    path_pass = prim[prim["PASS"]]
    underpowered = bool((power[(power["block"] == "replication") & (power["outcome"] == "A") & power["anchor"].isin(ANCH)]["MDE_tercile_delta"] > 0.10).all())
    if len(path_pass):
        verdict = "PATH_INFORMATION_PRESENT"
    elif lvl["A_vs_N1c"]["PASS"] or lvl["B_vs_N3"]["PASS"] or lvl["G_vs_N3"]["PASS"] or underpowered:
        verdict = "INCONCLUSIVE_MECHANICAL_BASELINE"
    else:
        verdict = "LOCATION_ONLY"
    raw_speed = evals[(evals["variable"] == "time_to_anchor_s") & evals["outcome"].isin(["B_raw", "G_raw", "A_raw"])][["outcome", "PASS"]].to_dict("records")

    # ------------------------------------------------------------------ robustness (passing primaries; else largest pooled |delta| per residual outcome)
    targets = [(r.outcome, r.variable, r.variant) for r in path_pass.itertuples()]
    if not targets:
        pe = eff[(eff["block"] == "pooled") & eff["primary"] & eff["outcome"].isin(["A_res_N2", "B_res_N3", "G_res_N3"]) & (eff["variant"] != "tod_stratified_excl_last_hour")]
        pe = pe[~((pe["variable"] == "time_to_anchor_s") & (pe["variant"] == "plain"))]
        for o, g in pe.groupby("outcome"):
            b = g.iloc[g["delta"].abs().argmax()]
            targets.append((o, b["variable"], b["variant"]))
    rb = []
    for oname, var, vname in targets:
        ycol, rcol, anchors = outcomes[oname]
        pe_rows = eff[(eff.outcome == oname) & (eff.variable == var) & (eff.variant == vname) & (eff.block == "pooled")]
        x = float(pe_rows.iloc[pe_rows["delta"].abs().argmax()]["anchor"])
        ex = ev[(ev["anchor"] == x) & ev[ycol].notna() & ev[rcol].notna()]
        disc = ex[ex["block"] == "discovery"]
        cuts = tuple(np.quantile(disc[var], [1 / 3, 2 / 3]))
        strata = "seg" if vname.startswith("tod") else None
        for gname, gcol in (("dir", "dir"), ("mtf_state", "mtf_state"), ("seg", "seg")):
            for gv, g in ex.groupby(gcol):
                if len(g) < 150:
                    continue
                (p, lo, hi), n = tercile_delta(g, var, rcol, cuts, strata if gname != "seg" else None)
                rb.append({"outcome": oname, "variable": var, "variant": vname, "anchor": x, "group": gname, "value": str(gv), "N": len(g), "delta": p, "lo": lo, "hi": hi})
    mn_write(pd.DataFrame(rb), "ROBUSTNESS")

    res = {"kind": "mechanical_null_results", "verdict_by_frozen_rule": verdict, "level_residual_pass": lvl,
           "primary_path_pass": path_pass[["outcome", "variable", "variant", "runs"]].to_dict("records"),
           "all_evaluations": evals.to_dict("records"), "raw_speed_pass": raw_speed,
           "replication_underpowered_everywhere": underpowered, "design_sha256": mn.sha_file(A / "DESIGN.json")}
    (A / "ANALYSIS_RESULTS.json").write_text(json.dumps(res, indent=2, sort_keys=True, default=mn.pm._jsonable) + "\n", encoding="utf-8")
    pd.set_option("display.width", 250)
    print(power[power.outcome != "B"].pivot_table(index=["outcome", "anchor"], columns="block", values="MDE_tercile_delta").round(3))
    print(levels.round(3).to_string())
    print(json.dumps({"verdict": verdict, "levels": lvl, "path_pass": res["primary_path_pass"], "raw_speed": raw_speed}, indent=1, default=mn.pm._jsonable))


def mn_write(df, name):
    df.to_csv(A / f"{name}.csv", index=False)
    df.to_parquet(A / f"{name}.parquet", index=False)


if __name__ == "__main__":
    main()
