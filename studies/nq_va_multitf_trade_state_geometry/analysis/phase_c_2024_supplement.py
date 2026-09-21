"""Phase C -- 2024 SUPPLEMENTARY DESCRIPTIVE READOUT (not verdict-bearing).

Written AFTER the frozen readout (replication_readout.py --year 2024, contract commit 3716a016) had
produced its verdict. It changes no claim, threshold or constant. It re-applies the FROZEN atlas
section functions of analysis/phase_c_atlas_2023.py to the 2024 partition (same hash-verified
load_frame) so that already-defined quantities -- runner optionality, exit-at-MAE, MTF direction
table, post-entry identifiability, archetype prevalence -- can be read beside their 2023 values.

Rules kept:
  * archetypes use the FROZEN RAPID_EDGE 34 s (s7_archetypes would recompute it from 2024, so its
    loop is reproduced here with the frozen constant; classify() itself is the frozen function);
  * sections whose buckets are within-year quantile edges that 2023 froze (s3/s4 quintile tables,
    s6 terciles, s8 current-pnl quintiles, s11 quintile spreads) are NOT re-bucketed; only their
    edge-free statistics (Spearman) are read;
  * the atlas writes phase_c_2023_* files, so its output directory is redirected to a scratch
    folder -- no 2023 artifact is touched.

Output: artifacts/phase_c_2024_replication_results.json (frozen readout verbatim + this supplement +
2023 comparators).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ART = STUDY / "artifacts"
spec = importlib.util.spec_from_file_location("atlas", HERE / "phase_c_atlas_2023.py")
atlas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(atlas)

RAPID_EDGE_s = 34.0
LONG_QUIET_s = 1065.0
READOUT = ART / "phase_c_2024_replication_readout.json"


def load(name):
    return json.loads((ART / name).read_text(encoding="utf-8"))


def cum_ge(dist: dict, levels=(0.25, 0.5, 0.75, 1.0)) -> dict:
    """P(MAE rung before the favourable rung >= y) from a rung distribution."""
    d = {float(k): v for k, v in dist.items()}
    return {f"-{y:.2f}A": float(sum(v for k, v in d.items() if k >= y)) for y in levels}


def runner_optionality(pops: list) -> dict:
    out = {}
    for p in pops:
        out[p["population"]] = {"n": p["n"], "reached_before_the_rung": cum_ge(p["mae_rung_before_rung_dist"]),
                                "adverse_0p50_before_fav_0p50": p["p_adverse_0p50_first"]}
    return out


def archetypes(t: pd.DataFrame) -> dict:
    t = t.copy()
    t["arch"], t["adv_first"] = atlas.classify(t, RAPID_EDGE_s)
    t["long_quiet"] = (t.dur >= LONG_QUIET_s) & (t.mfe_rung < 1) & (t.mae_rung < 1)
    N = len(t)
    rows = []
    for a in atlas.ARCH_ORDER:
        g = t[t.arch == a]
        r = {"archetype": a, **atlas.summ(g, N)}
        if len(g) >= 30:
            r.update({"sum_pnl_A": g.pnl.sum(), "adverse_first_share": g.adv_first.mean(),
                      "long_quiet_share": g.long_quiet.mean(), "long_share": (g.side == "LONG").mean(),
                      "mtf_all_aligned_share": (g.n_aligned == 3).mean(),
                      "share_first_move_adverse_0p25": (g.ta_0p25 < g.tf_0p25).mean(),
                      "median_s_to_first_0p25_adv": g.ta_0p25.replace(np.inf, np.nan).median()})
        rows.append(r)
    g0 = t[(t.mfe_rung < 0.5) & np.isfinite(t.ta_0p50)]
    ta = t.ta_0p50[np.isfinite(t.ta_0p50)]
    # 2023 histogram edges, so the two shapes are directly comparable
    e23 = load("phase_c_2023_path_archetypes.json")["shape_diagnostics"]
    h_ta = np.histogram(np.log10(ta.clip(lower=1)), bins=e23["log10_time_to_-0.50A_hist"]["edges"])
    h_d = np.histogram(np.log10(t.dur), bins=e23["log10_duration_hist"]["edges"])
    return {"frozen_RAPID_EDGE_s": RAPID_EDGE_s,
            "observed_2024_median_s_to_-0.50A_in_failure_group_NOT_USED": float(g0.ta_0p50.median()),
            "long_quiet_flag_share": float(t.long_quiet.mean()), "rows": rows,
            "shape_on_2023_edges": {"log10_time_to_-0.50A_counts": h_ta[0].tolist(),
                                    "log10_duration_counts": h_d[0].tolist()}}


def main():
    if not READOUT.exists():
        sys.exit("run replication_readout.py --year 2024 first; this supplement never precedes the verdict")
    readout = json.loads(READOUT.read_text(encoding="utf-8"))
    atlas.OUT = Path(tempfile.mkdtemp(prefix="phase_c_2024_supp_"))
    m, ident = atlas.load_frame(2024)
    t, excluded, lad = atlas.build_trades(m)
    t["arch"], t["adv_first"] = atlas.classify(t, RAPID_EDGE_s)   # frozen edge; s8/s11 read t.arch
    t["long_quiet"] = (t.dur >= LONG_QUIET_s) & (t.mfe_rung < 1) & (t.mae_rung < 1)
    pop = atlas.s1_population(t, excluded, ident, lad)
    mil = atlas.s1_milestones(t)
    mtf = atlas.s2_mtf(t)
    s3, s4 = atlas.s3_s4(t)
    s8, panel = atlas.s8_transitions(m, t)
    s9 = atlas.s9_runners(t)
    s10 = atlas.s10_failures(t, panel)
    s11 = atlas.s11_information(t)
    arch = archetypes(t)

    sp = [r["rho"] for h in atlas.TFS for sec in (s3, s4) for r in sec["per_tf"][h] if r.get("bucket") == "SPEARMAN_vs_pnl"]
    c7_cells = [dict(r, z=r["mean_rem_pnl_A"] / r["se"]) for r in s8["grid"]
                if r.get("se") and r["n"] >= atlas.MIN_N and r["s"] in (30, 60, 120, 285)
                and abs(r["mean_rem_pnl_A"] / r["se"]) > 2]

    r23 = load("phase_c_2023_runner_forensics.json")
    sup = {
        "note": "SUPPLEMENTARY / DESCRIPTIVE. Frozen atlas functions applied to 2024; not part of the frozen verdict.",
        "population": {k: pop[k] for k in ["trades_t0_total", "trades_resolved_terminal", "excluded_unresolved_terminal",
                                           "A_points_quantiles", "long_short", "pnl_A", "pnl_A_by_side", "outcome_bands",
                                           "duration_s", "duration_after_1515_ct_share", "entry_extension_A_quantiles",
                                           "tail_share_of_gross", "gross_ex_top_q"]},
        "milestones": {"incidence": [{"milestone": r["milestone"], "p": r["p_hit_in_lifecycle"],
                                      "median_s": r["time_s_quantiles_given_hit"].get(0.5)} for r in mil["milestones"]],
                       "ladder_continuation": mil["ladder_continuation"], "races": mil["races"],
                       "excursion_before": mil["excursion_before"], "exit_mechanism_non_runners": mil["exit_mechanism_non_runners"],
                       "joint_mfe_mae_rung_mean_pnl": mil["joint_mfe_mae_rung_mean_pnl"]},
        "runner_optionality": {"2024": runner_optionality(s9["populations"]),
                               "2023": runner_optionality(r23["populations"])},
        "runners": {k: s9[k] for k in ["populations", "baseline", "tail_share_of_gross", "contribution_by_lifecycle_mfe_rung"]},
        "mtf_direction": mtf,
        "htf_per_series_spearman_range": {"n_series": len(sp), "min": float(np.nanmin(sp)), "max": float(np.nanmax(sp))},
        "post_entry": {"alive_by_s": s8["alive_by_s"], "martingale": s8["martingale_check"], "scenarios": s8["scenarios"],
                       "c7_cells_abs_z_gt_2": c7_cells, "identifiability": s10["identifiability"],
                       "failure_populations": s10["populations"]},
        "information_map_family_summary": s11["family_summary"],
        "archetypes": arch,
        "not_recomputed": ["s3/s4 quintile tables and the 1h named contrast (2023 within-year quantile edges)",
                           "s6 hierarchical terciles", "s8 current-pnl quintiles", "s11 quintile spreads",
                           "s5 prior-regime quintiles"],
    }
    out = {"study": "nq_va_multitf_trade_state_geometry", "replication_year": 2024, "contract_commit": readout["contract_commit"],
           "frozen_readout_verbatim": readout, "supplement": sup}
    atlas.OUT = ART
    atlas.jdump("phase_c_2024_replication_results.json", out)
    print(json.dumps({"STATUS": "OK", "overall": readout["overall"], "n_trades": len(t), "c7_cells_z_gt_2": len(c7_cells)}))


if __name__ == "__main__":
    main()
