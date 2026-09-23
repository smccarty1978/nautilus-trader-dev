"""Descriptive analysis under the frozen ANALYSIS_PLAN.json (no model of any kind).

    python studies/nq_post_entry_path_mechanism_2023/analyze.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import path_mechanism as pm  # noqa: E402

A = pm.OUT
PLAN = json.loads((A / "ANALYSIS_PLAN.json").read_text(encoding="utf-8"))
for n, s in PLAN["bound_to"].items():
    if pm.sha_file(A / n) != s:
        raise SystemExit(f"PLAN_BINDING_CHANGED: {n}")
REPS, SEED = pm.BOOT_REPS, pm.BOOT_SEED
LEVELS = [0.5, 1.0, 1.5, 2.0, 3.0]


def auc_fast(pos: np.ndarray, neg: np.ndarray) -> float:
    """Probability of superiority P(X_pos > X_neg) + 1/2 P(tie) (Mann-Whitney)."""
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    allv = np.concatenate([pos, neg])
    ranks = pd.Series(allv).rank(method="average").to_numpy()
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def effect(x: np.ndarray, y: np.ndarray, sess: np.ndarray) -> dict:
    ok = ~np.isnan(x)
    x, y, sess = x[ok], y[ok], sess[ok]
    pos, neg = x[y == 1], x[y == 0]
    out = {"n_pos": int(len(pos)), "n_neg": int(len(neg))}
    if len(pos) < 20 or len(neg) < 20:
        return {**out, "auc": np.nan, "auc_lo": np.nan, "auc_hi": np.nan}
    q = lambda v, p: float(np.percentile(v, p))  # noqa: E731
    sd = np.sqrt(((len(pos) - 1) * pos.var(ddof=1) + (len(neg) - 1) * neg.var(ddof=1)) / (len(pos) + len(neg) - 2))
    out.update({"med_pos": q(pos, 50), "iqr_pos": [q(pos, 25), q(pos, 75)], "med_neg": q(neg, 50), "iqr_neg": [q(neg, 25), q(neg, 75)],
                "mean_pos": float(pos.mean()), "mean_neg": float(neg.mean()), "cohen_d": float((pos.mean() - neg.mean()) / sd) if sd > 0 else 0.0,
                "auc": auc_fast(pos, neg)})
    rng = np.random.default_rng(SEED)
    codes, uniq = pd.factorize(sess)
    groups = [np.flatnonzero(codes == i) for i in range(len(uniq))]
    draws = []
    for _ in range(REPS):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        yy, xx = y[idx], x[idx]
        if yy.min() == yy.max():
            continue
        draws.append(auc_fast(xx[yy == 1], xx[yy == 0]))
    out["auc_lo"], out["auc_hi"] = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
    return out


def meaningful(r) -> bool:
    return bool((r["auc"] >= 0.60 and r["auc_lo"] >= 0.55) or (r["auc"] <= 0.40 and r["auc_hi"] <= 0.45)) if np.isfinite(r["auc"]) else False


def main() -> None:
    tl = pd.read_parquet(A / "TRADE_EVENT_TIMELINE.parquet")
    cp = pd.read_parquet(A / "CHECKPOINT_STATE.parquet")
    ev = pd.read_parquet(A / "EVENT_ANCHORED_STATE.parquet")
    _, pop, _ = pm.load_dev()
    st = pop[["regime_start_ns", "dir_1m", "dir_5m", "dir_15m", "dir_1h"]].copy()
    st["mtf_state"] = st[["dir_1m", "dir_5m", "dir_15m", "dir_1h"]].apply(lambda r: "/".join("L" if v > 0 else "S" for v in r), axis=1)
    tl = tl.merge(st[["regime_start_ns", "mtf_state"]], on="regime_start_ns")
    tl["fav2"], tl["fav3"] = tl["reach_fav_2p0"], tl["reach_fav_3p0"]
    tl["group"] = np.where(tl["fav2"] == 0, "G1_failed", np.where(tl["win"] == 1, "G2_sustained", "G3_giveback"))
    base = tl[["regime_start_ns", "session", "fav2", "fav3", "win", "group", "mtf_state", "dir"]]

    # ------------------------------------------------------------------ MTF transition timing
    rows = []
    for tf in pm.TFS:
        m = tl[(tl[f"chain_{tf}"] == "EXACT") & (tl[f"aligned_T0_{tf}"] == 0) & tl[f"t_first_into_{tf}"].notna()].copy()
        t_tr = m[f"t_first_into_{tf}"].to_numpy()
        tt = np.column_stack([m[f"t_fav_{pm.lbl(x)}"].to_numpy() for x in LEVELS])
        before = np.nan_to_num(tt <= t_tr[:, None], nan=0).astype(bool) & ~np.isnan(tt)
        ties = (tt == t_tr[:, None]).any(axis=1)
        m["cat_idx"] = before.sum(axis=1)
        names = ["5m BEFORE +0.5A", "between +0.5A and +1A", "between +1A and +1.5A", "between +1.5A and +2A", "AFTER +2A (before +3A)", "AFTER +3A"]
        names = [n.replace("5m", tf) for n in names]
        nxt = np.array([np.nan if k >= 5 else tt[i, k] for i, k in enumerate(m["cat_idx"])])
        m["next_level_reached_later"] = ~np.isnan(nxt)
        m["tie"] = ties
        for k, name in enumerate(names):
            g = m[m["cat_idx"] == k]
            rows.append({"tf": tf, "category": name, "N": len(g), "pct": 100 * len(g) / len(m) if len(m) else np.nan,
                         "next_level_never_reached_n": int((~g["next_level_reached_later"]).sum()) if k < 5 else 0,
                         "ties_same_second": int(g["tie"].sum()),
                         "median_t_transition_s": g[f"t_first_into_{tf}"].median(),
                         **{f"median_t_fav_{pm.lbl(x)}_s": g[f"t_fav_{pm.lbl(x)}"].median() for x in LEVELS},
                         "win_pct": 100 * g["win"].mean(), "fav2_pct": 100 * g["fav2"].mean(), "fav3_pct": 100 * g["fav3"].mean(),
                         "adv0p5_pct": 100 * g["reach_adv_0p5"].mean(), "adv1_pct": 100 * g["reach_adv_1p0"].mean()})
    timing = pd.DataFrame(rows)
    pm.write_table("MTF_TIMING", timing)
    # reverse view: among +2A trades misaligned at T0, where did the 5m into-transition fall relative to +2A?
    rev = {}
    for tf in pm.TFS:
        m = tl[(tl[f"chain_{tf}"] == "EXACT") & (tl[f"aligned_T0_{tf}"] == 0) & (tl["fav2"] == 1)]
        t2, tt = m["t_fav_2p0"], m[f"t_first_into_{tf}"]
        t05 = m["t_fav_0p5"]
        rev[tf] = {"n_plus2_misaligned_at_T0": len(m), "into_before_plus0p5": float((tt < t05).mean()),
                   "into_before_plus2": float((tt <= t2).mean()), "into_after_plus2_before_terminal": float((tt > t2).mean()),
                   "never_into_before_terminal": float(tt.isna().mean())}
        a = tl[(tl[f"chain_{tf}"] == "EXACT") & (tl[f"aligned_T0_{tf}"] == 1)]
        away = a["t_first_trans_" + tf].notna()
        rev[tf]["aligned_at_T0"] = {"n": len(a), "away_transition_before_terminal_pct": 100 * float(away.mean()),
                                    "win_pct_if_away": 100 * float(a.loc[away, "win"].mean()) if away.any() else None,
                                    "win_pct_if_no_transition": 100 * float(a.loc[~away, "win"].mean())}
    # F5 prevalence among misaligned, overall
    # ------------------------------------------------------------------ checkpoint comparisons
    cpx = cp.merge(base, on="regime_start_ns")
    varz = PLAN["variables"]["path"] + PLAN["variables"]["mtf"]
    jobs = []
    for e in PLAN["checkpoints_s"]:
        at = cpx[cpx["elapsed_s"] == e]
        subsets = {"ALIVE": at[at["alive"] == 1], "PRE2": at[(at["alive"] == 1) & (at["mfe"] < 2.0)], "EARLY": at[(at["alive"] == 1) & (at["mfe"] < 1.0)]}
        for sname, s in subsets.items():
            for cname, (yser, mask) in {"C1": (s["fav2"], None), "C2": (s["win"], s["fav2"] == 1), "C3": (s["fav3"], None)}.items():
                ss = s if mask is None else s[mask]
                yy = (ss["win"] if cname == "C2" else ss["fav3"] if cname == "C3" else ss["fav2"]).to_numpy()
                for v in varz:
                    if e == 0 and v in PLAN["variables"]["path"]:
                        continue                                   # no path exists at T0
                    jobs.append(((e, sname, cname, v), ss[v].to_numpy(dtype=float), yy, ss["session"].to_numpy()))
    res = Parallel(n_jobs=8)(delayed(effect)(x, y, s) for _, x, y, s in jobs)
    cmp_rows = [{"elapsed_s": k[0], "subset": k[1], "contrast": k[2], "variable": k[3], **r} for (k, *_), r in zip(jobs, res)]
    comp = pd.DataFrame(cmp_rows)
    comp["meaningful"] = comp.apply(meaningful, axis=1)
    for c in ("iqr_pos", "iqr_neg"):
        comp[c] = comp[c].astype(str)
    pm.write_table("GROUP_COMPARISONS_CHECKPOINT", comp)

    # emergence table
    em = []
    for e in PLAN["checkpoints_s"]:
        at = cpx[(cpx["elapsed_s"] == e)]
        alive = at[at["alive"] == 1]
        run = alive[alive["fav2"] == 1]
        g1 = alive[alive["fav2"] == 0]
        row = {"elapsed_s": e, "alive_n": len(alive), "alive_pct_of_all": 100 * len(alive) / len(at),
               "alive_pct_G1": 100 * (at["alive"][at["fav2"] == 0]).mean(), "alive_pct_plus2": 100 * (at["alive"][at["fav2"] == 1]).mean(),
               "plus2_alive_n": len(run), "plus2_already_0p5_pct": 100 * (run["mfe"] >= 0.5).mean(),
               "plus2_already_1p0_pct": 100 * (run["mfe"] >= 1.0).mean(), "plus2_already_2p0_pct": 100 * (run["mfe"] >= 2.0).mean(),
               "plus2_median_mfe": run["mfe"].median(), "G1_median_mfe": g1["mfe"].median(),
               "plus2_median_mae": run["mae"].median(), "G1_median_mae": g1["mae"].median()}
        for sub, con in (("PRE2", "C1"), ("EARLY", "C1"), ("PRE2", "C2")):
            q = comp[(comp.elapsed_s == e) & (comp.subset == sub) & (comp.contrast == con)]
            if len(q):
                b = q.iloc[(q["auc"] - 0.5).abs().argmax()]
                row[f"{con}_{sub}_best_var"] = b["variable"]
                row[f"{con}_{sub}_best_auc"] = b["auc"]
                row[f"{con}_{sub}_best_ci"] = f"[{b['auc_lo']:.3f}, {b['auc_hi']:.3f}]"
                row[f"{con}_{sub}_n_meaningful"] = int(q["meaningful"].sum())
                for v in ("mfe", "aligned_5m"):
                    qq = q[q.variable == v]
                    row[f"{con}_{sub}_auc_{v}"] = float(qq["auc"].iloc[0]) if len(qq) else np.nan
        em.append(row)
    emergence = pd.DataFrame(em)
    pm.write_table("INFORMATION_EMERGENCE", emergence)

    # ------------------------------------------------------------------ event-anchored
    evx = ev.merge(base, on="regime_start_ns")
    ev_rows, ev_base = [], []
    jobs = []
    for evn, g in evx.groupby("event"):
        outs = {"reach_plus2": "fav2", "reach_plus3": "fav3", "win": "win"} if evn != "fav_2p0" else {"win_given_plus2 (C2)": "win", "reach_plus3": "fav3"}
        ev_base.append({"event": evn, "n": len(g), **{f"P({k})": 100 * g[v].mean() for k, v in outs.items()},
                        "median_t_since_t0_s": g["t_since_t0_s"].median(), "pct_5m_aligned_at_touch": 100 * g["aligned_5m"].mean(),
                        "pct_adv1_before_touch": 100 * g["adv1_before"].mean()})
        for oname, ocol in outs.items():
            if evn != "fav_2p0" and oname == "reach_plus2" and evn == "fav_2p0":
                continue
            for v in PLAN["variables"]["event_anchored"]:
                jobs.append(((evn, oname, v), g[v].to_numpy(dtype=float), g[ocol].to_numpy(), g["session"].to_numpy()))
        if evn != "fav_2p0":
            gg = g[g["fav2"] == 1]
            for v in PLAN["variables"]["event_anchored"]:
                jobs.append(((evn, "win_given_plus2 (C2)", v), gg[v].to_numpy(dtype=float), gg["win"].to_numpy(), gg["session"].to_numpy()))
    res = Parallel(n_jobs=8)(delayed(effect)(x, y, s) for _, x, y, s in jobs)
    evc = pd.DataFrame([{"event": k[0], "outcome": k[1], "variable": k[2], **r} for (k, *_), r in zip(jobs, res)])
    evc["meaningful"] = evc.apply(meaningful, axis=1)
    for c in ("iqr_pos", "iqr_neg"):
        evc[c] = evc[c].astype(str)
    pm.write_table("GROUP_COMPARISONS_EVENT", evc)
    pm.write_table("EVENT_BASE_RATES", pd.DataFrame(ev_base))

    # ------------------------------------------------------------------ giveback at T0 (MTF only; T0 surface already null)
    t0c = comp[(comp.elapsed_s == 0) & (comp.contrast == "C2")]

    # ------------------------------------------------------------------ initial-state map
    srows = []
    c60 = cpx[(cpx.elapsed_s == 60) & (cpx.alive == 1) & (cpx.mfe < 1.0)]
    for s, g in tl.groupby("mtf_state"):
        if len(g) < 150:
            srows.append({"mtf_state": s, "N": len(g), "supported": False})
            continue
        mis5 = g[(g["chain_5m"] == "EXACT") & (g["aligned_T0_5m"] == 0)]
        f5 = mis5[mis5["t_first_into_5m"].notna()]
        tt05 = f5["t_fav_0p5"]
        e60 = c60[c60["mtf_state"] == s]
        eff = effect(e60["mfe"].to_numpy(dtype=float), e60["fav2"].to_numpy(), e60["session"].to_numpy())
        run = g[g["fav2"] == 1]
        srows.append({"mtf_state": s, "N": len(g), "supported": True, "long": s[0] == "L", "fav2_pct": 100 * g["fav2"].mean(),
                      "win_pct": 100 * g["win"].mean(), "giveback_pct_of_plus2": 100 * (1 - run["win"].mean()),
                      "misaligned_5m_at_T0": len(mis5) > 0, "f5_pct_of_misaligned": 100 * len(f5) / len(mis5) if len(mis5) else None,
                      "f5_before_plus0p5_pct": 100 * float(((f5["t_first_into_5m"] < tt05) | tt05.isna()).mean()) if len(f5) else None,
                      "f5_after_plus1_pct": 100 * float((f5["t_first_into_5m"] >= f5["t_fav_1p0"]).mean()) if len(f5) else None,
                      "plus2_median_t_to_0p5_s": run["t_fav_0p5"].median(), "plus2_median_t_to_2p0_s": run["t_fav_2p0"].median(),
                      "C1_EARLY_60s_auc_mfe": eff["auc"], "C1_EARLY_60s_auc_ci": f"[{eff['auc_lo']:.3f}, {eff['auc_hi']:.3f}]" if np.isfinite(eff["auc"]) else None})
    states = pd.DataFrame(srows)
    pm.write_table("INITIAL_STATE_MAP", states)
    ls = []
    for dname, g in tl.groupby("dir"):
        run = g[g["fav2"] == 1]
        e60 = c60[c60["dir"] == dname]
        eff = effect(e60["mfe"].to_numpy(dtype=float), e60["fav2"].to_numpy(), e60["session"].to_numpy())
        ls.append({"dir": "long" if dname > 0 else "short", "N": len(g), "fav2_pct": 100 * g["fav2"].mean(), "win_pct": 100 * g["win"].mean(),
                   "giveback_pct_of_plus2": 100 * (1 - run["win"].mean()), "plus2_median_t_to_2p0_s": run["t_fav_2p0"].median(),
                   "C1_EARLY_60s_auc_mfe": eff["auc"], "ci": [eff["auc_lo"], eff["auc_hi"]]})

    # ------------------------------------------------------------------ verdict per the frozen rule
    c1 = comp[comp.contrast == "C1"]
    A_ = bool(c1[(c1.elapsed_s == 0) & (c1.subset == "ALIVE")]["meaningful"].any())
    early_hits = []
    for e in [x for x in PLAN["checkpoints_s"] if x <= 120]:
        em_row = emergence[emergence.elapsed_s == e].iloc[0]
        q = c1[(c1.elapsed_s == e) & (c1.subset == "EARLY") & c1.meaningful]
        if len(q) and em_row["plus2_already_1p0_pct"] < 25:
            early_hits.append({"elapsed_s": e, "variables": q["variable"].tolist(), "plus2_already_1p0_pct": em_row["plus2_already_1p0_pct"]})
    B_ = bool(early_hits)
    evc1 = evc[(evc.event.isin(["fav_1p0", "fav_1p5"])) & (evc.outcome == "reach_plus2")]
    any_c1 = bool(c1["meaningful"].any() or evc1["meaningful"].any())
    verdict = ("T0_INFORMATION" if A_ else "EARLY_POST_ENTRY_INFORMATION" if B_ else "LATE_CONFIRMATION_ONLY" if any_c1 else "NO_USEFUL_PATH_SEPARATION")
    c2 = comp[(comp.contrast == "C2") & (comp.subset == "PRE2") & comp.meaningful]
    evc2 = evc[(evc.outcome == "win_given_plus2 (C2)") & (evc.event.isin(["fav_0p5", "fav_1p0", "fav_1p5"])) & evc.meaningful]
    out = {"kind": "path_mechanism_results", "verdict_by_frozen_rule": verdict, "A_T0": A_, "B_early_hits": early_hits, "any_C1_meaningful": any_c1,
           "C2_giveback_distinguishable_before_plus2": bool(len(c2) or len(evc2)),
           "C2_meaningful_checkpoint": c2[["elapsed_s", "variable", "auc", "auc_lo", "auc_hi"]].to_dict("records"),
           "C2_meaningful_event": evc2[["event", "variable", "auc", "auc_lo", "auc_hi"]].to_dict("records"),
           "mtf_reverse_view": rev, "long_short": ls, "t0_C2": t0c[["variable", "auc", "auc_lo", "auc_hi"]].to_dict("records"),
           "plan_sha256": pm.sha_file(A / "ANALYSIS_PLAN.json")}
    pm.write_json("ANALYSIS_RESULTS.json", out)
    pd.set_option("display.width", 250)
    print(timing.round(1).to_string())
    print(emergence.round(3).T.to_string())
    print(pd.DataFrame(ev_base).round(1).to_string())
    print(json.dumps({k: out[k] for k in ("verdict_by_frozen_rule", "A_T0", "B_early_hits", "any_C1_meaningful", "C2_giveback_distinguishable_before_plus2", "mtf_reverse_view", "long_short")}, indent=1, default=pm._jsonable))


if __name__ == "__main__":
    main()
