"""Phase C -- FROZEN 2023 -> 2024 replication readout.

Every claim, statistic, threshold and frozen constant below was fixed from the 2023 atlas BEFORE any
2024 outcome was read. `--year 2023` is the self-test (2023 must satisfy its own claims);
`--year 2024` is refused unless this file, the atlas script and the replication contract are all
committed and unmodified, so the readout that opens 2024 is provably the frozen one.

    python studies/nq_va_multitf_trade_state_geometry/analysis/replication_readout.py --year 2023
    python studies/nq_va_multitf_trade_state_geometry/analysis/replication_readout.py --year 2024
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
spec = importlib.util.spec_from_file_location("atlas", HERE / "phase_c_atlas_2023.py")
atlas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(atlas)

CONTRACT = STUDY / "artifacts" / "phase_c_2024_replication_contract.yaml"
FROZEN = {"RAPID_EDGE_s": 34.0, "LONG_QUIET_duration_p75_s": 1065.0, "MIN_TRADES": 5000}
HTF_FAMILIES = ["5m_maturity", "15m_maturity", "1h_maturity", "5m_current_geometry", "15m_current_geometry",
                "1h_current_geometry", "5m_geometry_features", "cross_tf_alignment", "prior_5m_geometry"]
PRIMARY = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C12"]
CORE = ["C3", "C5", "C7"]


def require_committed():
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=STUDY, capture_output=True, text=True).stdout.strip()
    files = [CONTRACT, HERE / "phase_c_atlas_2023.py", Path(__file__).resolve()]
    for f in files:
        rel = f.resolve().relative_to(Path(root).resolve()).as_posix()
        if subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=root, capture_output=True).returncode:
            sys.exit(f"REPLICATION_REFUSED: {rel} is not committed")
        if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=root).returncode:
            sys.exit(f"REPLICATION_REFUSED: {rel} differs from HEAD")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()


def verdict(ok: bool, partial: bool = False) -> str:
    return "PASS" if ok else ("PARTIAL" if partial else "FAIL")


def run(year: int) -> dict:
    head = require_committed() if year != 2023 else None
    m, ident = atlas.load_frame(year)
    t, excluded, _ = atlas.build_trades(m)
    t["arch"], t["adv_first"] = atlas.classify(t, FROZEN["RAPID_EDGE_s"])
    t["long_quiet"] = (t.dur >= FROZEN["LONG_QUIET_duration_p75_s"]) & (t.mfe_rung < 1) & (t.mae_rung < 1)
    fam = atlas.feature_families(t)
    N = len(t)
    C = {}
    if N < FROZEN["MIN_TRADES"]:
        return {"year": year, "verdict": "INSUFFICIENT_SAMPLE", "n": N}

    mu, se = t.pnl.mean(), atlas.clustered_se(t.pnl, t.day)
    C["C1"] = {"claim": "untreated flip-to-flip gross is ~break-even", "mean_A": mu, "se": se,
               "verdict": verdict(abs(mu) <= 0.15, abs(mu) <= 0.30)}

    def cont(side, a, b):
        ha, hb = np.isfinite(t[f"{side}_{atlas.tag(a)}"]), np.isfinite(t[f"{side}_{atlas.tag(b)}"])
        return float(hb[ha].mean() ** (1 / (b - a)))
    fav = [cont("tf", a, b) for a, b in [(1, 1.5), (1.5, 2), (2, 3), (3, 4), (4, 5)]]
    adv = [cont("ta", a, b) for a, b in [(1, 1.5), (1.5, 2)]]
    f_ok, a_ok = all(0.55 <= v <= 0.78 for v in fav), all(v <= 0.40 for v in adv)
    C["C2"] = {"claim": "favorable ladder continues at a roughly constant per-A rate (long right tail); adverse ladder collapses past -1A (flip exit truncates the left tail)",
               "fav_per_A": fav, "adv_per_A": adv, "verdict": verdict(f_ok and a_ok, f_ok or a_ok)}

    em = atlas.exit_mechanism(t)
    C["C3"] = {"claim": "for trades that never reach +2A the terminal sits at the lifecycle adverse extreme", **em,
               "verdict": verdict(em["spearman_pnl_vs_neg_mae_rung"] >= 0.80 and abs(em["mean_pnl_plus_mae_rung_A"]) <= 0.25,
                                  em["spearman_pnl_vs_neg_mae_rung"] >= 0.70)}

    ts = atlas.top_share(t.pnl, 0.05)
    C["C4"] = {"claim": "expectancy is right-tail dependent", **ts,
               "verdict": verdict(ts["mean_rest_A"] <= -0.25 and ts["sum_top_A"] > 0, ts["mean_rest_A"] < 0)}

    htf = [f for k in HTF_FAMILIES for f in fam[k]]
    rho = max(abs(spearmanr(t[f], t.pnl, nan_policy="omit")[0]) for f in htf)
    y_rf = t.arch == "FAILURE_RAPID"
    y_rn = t.mfe_rung >= 3
    a_rf = max(abs(atlas.auc(t[f], y_rf) - .5) for f in htf)
    a_rn = max(abs(atlas.auc(t[f], y_rn) - .5) for f in htf)
    C["C5"] = {"claim": "T0 higher-timeframe state/geometry carries almost no information about the 1m lifecycle",
               "max_abs_spearman_pnl": rho, "max_abs_auc_dev_rapid_failure": a_rf, "max_abs_auc_dev_runner3": a_rn,
               "n_features": len(htf),
               "verdict": verdict(rho <= 0.06 and a_rf <= 0.05 and a_rn <= 0.05, rho <= 0.10 and max(a_rf, a_rn) <= 0.08)}

    e_sev = atlas.auc(t.entry_ext_A, np.isfinite(t.ta_2p00))
    e_run = atlas.auc(t.entry_ext_A, y_rn)
    e_rho = spearmanr(t.entry_ext_A, t.pnl)[0]
    C["C6"] = {"claim": "entry extension from the flip-bar open scales BOTH tails (scale, not sign)",
               "auc_severe_mae2": e_sev, "auc_runner3": e_run, "spearman_pnl": e_rho,
               "verdict": verdict(e_sev >= 0.58 and e_run >= 0.52 and abs(e_rho) <= 0.08, e_sev >= 0.55)}

    p = atlas.build_panel(m, t)
    grid = []
    for s in [30, 60, 120, 285]:
        g = p[p.s == s]
        for _, gg in g.groupby([g.mfe_by_s.clip(upper=2.0), g.mae_by_s.clip(upper=1.0)]):
            if len(gg) >= atlas.MIN_N:
                grid.append({"s": s, "n": len(gg), "mean_rem_pnl_A": gg.rem_pnl_A.mean(),
                             "se": atlas.clustered_se(gg.rem_pnl_A, gg.T0_day)})
    mg = atlas.martingale(p, grid)
    rem_ok = all(abs(mg[str(s)]["mean_rem_pnl_A"]) <= 0.15 for s in [30, 60, 120, 285])
    C["C7"] = {"claim": "remaining gross from any observed early-path state is ~0 (post-entry state predicts spread, not drift)",
               **mg, "verdict": verdict(rem_ok and (mg["share_cells_abs_z_gt_2"] or 0) <= 0.10,
                                        rem_ok and (mg["share_cells_abs_z_gt_2"] or 0) <= 0.20)}

    def path_auc(s):
        g = p[(p.s == s) & ~(p.T0_ta_1p00 <= s)]
        return atlas.auc(g.mae_by_s, pd.Series(np.isfinite(g.T0_ta_1p00).values, index=g.index))
    y1 = pd.Series(np.isfinite(t.ta_1p00).values, index=t.index)
    t0_best = max(abs(atlas.auc(t[f], y1) - .5) for f in atlas.t0_feature_list(t) if t[f].notna().sum() > 1000)
    a15, a120 = path_auc(15), path_auc(120)
    C["C8"] = {"claim": "the -1A loser becomes identifiable only after entry and increasingly with time",
               "t0_best_abs_auc_dev": t0_best, "path_auc_s15": a15, "path_auc_s120": a120,
               "verdict": verdict(a120 >= 0.65 and a120 > a15 and t0_best <= 0.07, a120 > a15)}

    sh = t.arch.value_counts(normalize=True)
    g = lambda k: float(sh.get(k, 0.0))
    fail = g("FAILURE_RAPID") + g("FAILURE_SLOW")
    conds = [g("STAGNANT_QUIET") < 0.01, g("DEVELOPED_HELD") < 0.05, 0.25 <= g("DEVELOPED_GIVEBACK") <= 0.40,
             0.07 <= g("RUNNER_5PLUS") <= 0.15, 0.20 <= fail <= 0.30]
    C["C9"] = {"claim": "archetype prevalence: no quiet stagnation, giveback is the modal 1-3A outcome, ~1 in 9 reaches +5A",
               "shares": sh.to_dict(), "failure_share": fail, "conditions": conds,
               "verdict": verdict(all(conds), sum(conds) >= 4)}

    feats = [f for f in atlas.t0_feature_list(t) if t[f].notna().sum() > 1000]
    sep = {a: max(abs(atlas.auc(t[f], t.arch == a) - .5) for f in feats)
           for a in ["FAILURE_RAPID", "RUNNER_3_5", "RUNNER_5PLUS", "DEVELOPED_GIVEBACK"]}
    C["C10"] = {"claim": "path archetypes are NOT separable at T0", "max_abs_auc_dev": sep,
                "verdict": verdict(max(sep.values()) <= 0.08, max(sep.values()) <= 0.12)}

    mean_all = t.pnl.mean()
    c1 = t[(t.rel_1h == "O") & (t.rel_15m == "A") & (t.rel_5m == "A")]
    c2 = t[t.n_aligned == 3]
    d1, d2 = c1.pnl.mean() - mean_all, c2.pnl.mean() - mean_all
    C["C11"] = {"claim": "SECONDARY/WEAK: 1h-opposed-with-5m+15m-aligned is below the population mean; all-aligned is above",
                "n_1h_opp_ltf_aligned": len(c1), "delta_1": d1, "se_1": atlas.clustered_se(c1.pnl, c1.day),
                "n_all_aligned": len(c2), "delta_2": d2, "se_2": atlas.clustered_se(c2.pnl, c2.day),
                "verdict": verdict(d1 < 0 and d2 > 0, (d1 < 0) or (d2 > 0)), "primary": False}

    r = t[t.mfe_rung >= 3]
    dl = abs(r["1h_loc_in_range"].median() - t["1h_loc_in_range"].median())
    da = abs((r.n_aligned == 3).mean() - (t.n_aligned == 3).mean())
    C["C12"] = {"claim": "runners are born in the same T0 HTF geometry as everything else", "abs_delta_median_1h_loc": dl,
                "abs_delta_all_aligned_share": da, "verdict": verdict(dl <= 0.03 and da <= 0.03, dl <= 0.06 and da <= 0.06)}

    v = [C[k]["verdict"] for k in PRIMARY]
    if all(x == "PASS" for x in v):
        overall = "REPLICATED"
    elif sum(x == "PASS" for x in v) >= int(np.ceil(0.75 * len(v))) and all(C[k]["verdict"] != "FAIL" for k in CORE):
        overall = "PARTIAL_REPLICATION"
    else:
        overall = "REPLICATION_FAILED"
    return {"year": year, "frame": ident, "contract_commit": head, "n_trades": N, "excluded": len(excluded),
            "frozen_constants": FROZEN, "claims": C, "primary_verdicts": dict(zip(PRIMARY, v)), "overall": overall}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2023, 2024])
    a = ap.parse_args()
    res = run(a.year)
    name = "phase_c_2023_replication_selftest.json" if a.year == 2023 else "phase_c_2024_replication_readout.json"
    atlas.jdump(name, res)
    print(json.dumps({"year": a.year, "overall": res.get("overall", res.get("verdict")),
                      "primary": res.get("primary_verdicts"), "secondary_C11": res.get("claims", {}).get("C11", {}).get("verdict")}))


if __name__ == "__main__":
    main()
