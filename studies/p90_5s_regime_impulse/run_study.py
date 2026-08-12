"""Runner for the P90-primed 5-second regime impulse study.

    python -m studies.p90_5s_regime_impulse.run_study

Assumes Phase 0 (`implementation.lineage`) and the 5s regime build
(`implementation.regime_5s`) have already run; both are cheap to re-run and are
re-checked here rather than trusted.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, load_market, load_regimes,
)
from studies.p90_5s_regime_impulse.implementation import analysis as A
from studies.p90_5s_regime_impulse.implementation import regime_5s as R5
from studies.p90_5s_regime_impulse.implementation import validate as V
from studies.p90_5s_regime_impulse.implementation.lineage import (
    ARMED_REQUIRED, load_arms,
)
from studies.p90_5s_regime_impulse.implementation.policy import (
    ALIGNED, run_policy, walks_to_frame,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "studies/p90_5s_regime_impulse/results"
WORK = ROOT / "studies/p90_5s_regime_impulse/_work"
SEED = 20260812
N_ENTRY_PLACEBO_DRAWS = 1000


def _code_hash() -> str:
    h = hashlib.sha256()
    impl = ROOT / "studies/p90_5s_regime_impulse"
    for p in sorted(impl.rglob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    lineage = json.loads((OUT / "lineage_reconciliation.json").read_text())
    if not lineage["all_targets_reproduced"]:
        raise RuntimeError("SPEC 8.1 ABORT -- Phase 0 lineage did not reproduce")
    r5_meta = json.loads((WORK / "regime_5s_build.json").read_text())

    arms = load_arms()
    market, regimes = load_market(), load_regimes()
    r5 = R5.load()
    print(f"arms={arms.height:,}  1s RTH bars={market.n:,}  "
          f"5s flips={r5.n:,}  [{time.time()-t0:.0f}s]", flush=True)

    # ---------------------------------------------------------- S1 and S075
    print("simulating S1 (1.00 ATR) ...", flush=True)
    w_s1 = walks_to_frame(run_policy(arms, market, regimes, r5, 1.00))
    print("simulating S075 (0.75 ATR) ...", flush=True)
    w_s075 = walks_to_frame(run_policy(arms, market, regimes, r5, 0.75))

    # ------------------------------------------------- PLACEBO_EXIT (length-blind)
    # The hold is drawn from the POOLED realised S1 hold distribution, not from
    # each trade's own realised lifetime -- a per-trade uniform draw over the
    # realised span is itself look-ahead (`placebo_must_be_length_blind`).
    entered_s1 = w_s1.filter(pl.col("entered") & pl.col("gross_atr").is_finite())
    hold_pool = entered_s1["hold_s"].to_numpy()
    n_aligned = int((w_s1["alignment"] == ALIGNED).sum())
    forced = rng.choice(hold_pool, size=n_aligned, replace=True)
    print(f"simulating PLACEBO_EXIT (pooled hold draw, n={n_aligned:,}) ...", flush=True)
    w_plac = walks_to_frame(
        run_policy(arms, market, regimes, r5, 1.00, forced_holds=forced))

    # ------------------------------------------------------------- economics
    e_s1 = A.economics(w_s1, "S1")
    e_s075 = A.economics(w_s075, "S075")
    e_plac = A.economics(w_plac, "PLACEBO_EXIT")
    e_a = lineage["benchmark_a"]["next_open_fill"]

    # S1 - PLACEBO_EXIT, paired on the arm, bootstrapped over arms
    def per_arm(w: pl.DataFrame) -> np.ndarray:
        v = np.zeros(w.height)
        m = (w["entered"] & w["gross_atr"].is_finite()).to_numpy()
        v[m] = w.filter(pl.col("entered") & pl.col("gross_atr").is_finite())["net_atr"].to_numpy()
        return v

    d = per_arm(w_s1) - per_arm(w_plac)
    bi = rng.integers(0, d.size, size=(A.BOOT, d.size))
    d_ci = np.percentile(d[bi].mean(axis=1), [2.5, 97.5])

    # ------------------------------------------- PLACEBO_ENTRY (count-matched)
    # Does ALIGNMENT select a better population, judged by the accepted lifecycle?
    bench = pl.read_parquet(OUT / "benchmark_a_next_open.parquet")
    bench_net = dict(zip(bench["regime_id"].to_list(), bench["net_atr"].to_list()))
    all_ids = arms["regime_id"].to_list()
    aligned_ids = set(w_s1.filter(pl.col("alignment") == ALIGNED)["regime_id"].to_list())
    conf_map = dict(zip(arms["regime_id"].to_list(),
                        arms["walk_a_confirm_reached_censored"].to_list()))

    def bench_stats(ids) -> tuple[float, float]:
        vals = [bench_net.get(i) for i in ids]
        vals = [v for v in vals if v is not None and np.isfinite(v)]
        confs = [bool(conf_map.get(i)) for i in ids]
        return (float(np.sum(vals) / ARMED_REQUIRED),
                float(np.mean(confs)) if confs else float("nan"))

    obs_exp, obs_conf = bench_stats(aligned_ids)
    draws_exp, draws_conf, entry_draw_ids = [], [], []
    idx_all = np.arange(len(all_ids))
    for _ in range(N_ENTRY_PLACEBO_DRAWS):
        pick = rng.choice(idx_all, size=len(aligned_ids), replace=False)
        ids = [all_ids[i] for i in pick]
        entry_draw_ids.append(ids)
        ex, cf = bench_stats(ids)
        draws_exp.append(ex)
        draws_conf.append(cf)
    band_exp = np.percentile(draws_exp, [2.5, 50, 97.5])
    band_conf = np.percentile(draws_conf, [2.5, 50, 97.5])
    aligned_beats_band = bool(obs_exp > band_exp[2])

    placebo_ci = {
        "s1_minus_placebo_exit_per_arm": float(d.mean()),
        "s1_minus_placebo_ci_low": float(d_ci[0]),
        "s1_minus_placebo_ci_high": float(d_ci[1]),
        "s1_minus_placebo_ci_excludes_zero": bool(d_ci[0] > 0 or d_ci[1] < 0),
        "entry_placebo_draws": N_ENTRY_PLACEBO_DRAWS,
        "aligned_subset_bench_exp_per_arm": obs_exp,
        "entry_placebo_band_exp": list(map(float, band_exp)),
        "aligned_subset_bench_confirm_rate": obs_conf,
        "entry_placebo_band_confirm": list(map(float, band_conf)),
        "aligned_beats_entry_placebo_band": aligned_beats_band,
        "placebo_exit_hold_pool_median_s": float(np.median(hold_pool)),
        "placebo_exit_p_unresolved": float(
            (w_plac.filter(pl.col("entered"))["outcome"] == "SESSION_CLOSE").mean()),
    }
    # PLACEBO_ENTRY is scored under BENCHMARK A, not under 5s management, so its
    # row must be computed from benchmark-A trades -- never copied from
    # PLACEBO_EXIT. Every statistic below is the median across the 1,000
    # count-matched draws; the 5s-management columns are left null because this
    # control has no 5s exit, and a copied value there would be a false reading.
    bench_by_id = {r["regime_id"]: r for r in bench.iter_rows(named=True)}

    def draw_stats(ids) -> dict:
        v = np.array([bench_by_id[i]["net_atr"] for i in ids
                      if i in bench_by_id and np.isfinite(bench_by_id[i]["net_atr"])])
        g = np.array([bench_by_id[i]["gross_atr"] for i in ids
                      if i in bench_by_id and np.isfinite(bench_by_id[i]["gross_atr"])])
        w, l = v[v > 0], v[v < 0]
        return {
            "win_rate": float((v > 0).mean()) if v.size else float("nan"),
            "mean_atr": float(v.mean()) if v.size else float("nan"),
            "median_atr": float(np.median(v)) if v.size else float("nan"),
            "mean_winner": float(w.mean()) if w.size else float("nan"),
            "median_winner": float(np.median(w)) if w.size else float("nan"),
            "mean_loser": float(l.mean()) if l.size else float("nan"),
            "median_loser": float(np.median(l)) if l.size else float("nan"),
            "profit_factor": (float(w.sum() / -l.sum())
                              if l.size and l.sum() != 0 else float("nan")),
            "gross_atr_total": float(g.sum()), "net_atr_total": float(v.sum()),
            "exp_per_entry_gross": float(g.mean()) if g.size else float("nan"),
            "exp_per_entry_net": float(v.mean()) if v.size else float("nan"),
            "exp_per_arm_gross": float(g.sum() / ARMED_REQUIRED),
            "max_dd_atr": A.max_drawdown(
                v, np.arange(v.size)) if v.size else float("nan"),
        }

    per_draw = [draw_stats(d_ids) for d_ids in entry_draw_ids]
    e_plac_entry = {
        "policy": "PLACEBO_ENTRY",
        "n_arms": ARMED_REQUIRED, "n_entries": len(aligned_ids),
        "entry_coverage": len(aligned_ids) / ARMED_REQUIRED,
        "n_stop": None, "n_5s_exit": None, "n_session": None,
        "median_hold_s": None, "pct_ambiguous": None,
        **{k: float(np.median([d[k] for d in per_draw])) for k in per_draw[0]},
        "exp_per_arm_net": float(band_exp[1]),
        "exp_per_arm_net_ci_low": float(band_exp[0]),
        "exp_per_arm_net_ci_high": float(band_exp[2]),
        "atr_per_100_arms": float(band_exp[1] * 100),
    }

    # ----------------------------------------------------------------- tables
    align = A.alignment_table(w_s1)
    geom_s1 = A.geometry_table(w_s1, r5, arms)
    geom_s075 = A.geometry_table(w_s075, r5, arms)

    row_a = {**{k: float("nan") for k in e_s1}, "policy": "A_LIFECYCLE",
             "n_arms": ARMED_REQUIRED, "n_entries": e_a["n_resolved"],
             "entry_coverage": e_a["n_resolved"] / ARMED_REQUIRED,
             "win_rate": e_a["win_rate"], "mean_atr": e_a["mean_net_atr"],
             "median_atr": e_a["median_net_atr"],
             "exp_per_entry_net": e_a["mean_net_atr"],
             "exp_per_entry_gross": e_a["mean_gross_atr"],
             "exp_per_arm_net": e_a["net_atr_per_arm"],
             "exp_per_arm_gross": e_a["mean_gross_atr"] * e_a["n_resolved"] / ARMED_REQUIRED,
             "atr_per_100_arms": e_a["net_atr_per_arm"] * 100}
    comparison = pl.DataFrame([row_a, e_s1, e_s075, e_plac, e_plac_entry],
                              infer_schema_length=None)
    comparison.write_csv(OUT / "policy_comparison.csv")
    # Manifest item 9 names these columns literally; the completion gate checks
    # the list as written, so emit those names rather than the internal ones.
    comparison.select(
        "policy",
        pl.col("n_arms").alias("n_original_arms"),
        "n_entries", "entry_coverage", "exp_per_arm_gross", "exp_per_arm_net",
        pl.col("net_atr_total").alias("total_net_atr"),
        "atr_per_100_arms",
        pl.col("exp_per_arm_net_ci_low").alias("ci_low"),
        pl.col("exp_per_arm_net_ci_high").alias("ci_high"),
    ).write_csv(OUT / "per_original_arm.csv")

    align.write_csv(OUT / "p90_5s_alignment.csv")
    geom_s1.write_csv(OUT / "five_second_geometry.csv")

    # `walk_a_terminal_label` is the ACCEPTED lifecycle's outcome for the same
    # arm, carried alongside each trade so a reader can compare the two without
    # re-joining. It is a diagnostic column and is attached after simulation --
    # nothing in the policy has ever seen it (gate V9).
    label = arms.select("regime_id", "walk_a_terminal_label")
    for frame, path in ((w_s1, "trades_s1.parquet"),
                        (w_s075, "trades_s075.parquet"),
                        (w_plac, "trades_placebo_exit.parquet")):
        frame.join(label, on="regime_id", how="left").write_parquet(OUT / path)

    pl.concat([A.exit_vs_confirmation(w_s1, "S1"),
               A.exit_vs_confirmation(w_s075, "S075"),
               A.exit_vs_confirmation(w_plac, "PLACEBO_EXIT")]
              ).write_csv(OUT / "exit_vs_confirmation.csv")
    pl.concat([A.confirmation_capture(w_s1, "S1", rng),
               A.confirmation_capture(w_s075, "S075", rng),
               A.confirmation_capture(w_plac, "PLACEBO_EXIT", rng)],
              how="diagonal").write_csv(OUT / "confirmation_capture.csv")
    failure = pl.concat([A.failure_cost(w_s1, arms, "S1"),
                         A.failure_cost(w_s075, arms, "S075"),
                         A.failure_cost(w_plac, arms, "PLACEBO_EXIT")])
    failure.write_csv(OUT / "failure_cost.csv")
    pres = A.preservation(w_s1, w_s075, arms)
    pres.write_csv(OUT / "successful_trade_preservation.csv")
    A.stop_comparison(w_s1, w_s075, arms, e_s1, e_s075).write_csv(
        OUT / "stop_comparison.csv")
    nonentry = A.nonentry_future_alignment(w_s1, arms, r5, market, regimes)
    nonentry.write_csv(OUT / "nonentry_future_alignment.csv")
    pl.concat([A.age_diagnostic(geom_s1, "S1"),
               A.age_diagnostic(geom_s075, "S075")]).write_csv(
        OUT / "five_second_age_diagnostic.csv")

    by_year = pl.concat([A.by_group(w_s1, "S1", "entry_year"),
                         A.by_group(w_s075, "S075", "entry_year"),
                         A.by_group(w_plac, "PLACEBO_EXIT", "entry_year")])
    by_year.write_csv(OUT / "by_year.csv")
    by_side = pl.concat([A.by_group(w_s1, "S1", "side"),
                         A.by_group(w_s075, "S075", "side"),
                         A.by_group(w_plac, "PLACEBO_EXIT", "side")])
    by_side.write_csv(OUT / "by_side.csv")

    # ------------------------------------------------------- gates & verdict
    gates = V.run_gates(arms=arms, walks_s1=w_s1, walks_s075=w_s075,
                        walks_placebo=w_plac, lineage=lineage, r5_meta=r5_meta,
                        align=align)
    (OUT / "validation_report.json").write_text(json.dumps(
        {"gates": gates, "n_gates": len(gates),
         "n_failed": sum(1 for x in gates if not x["pass"])}, indent=2))

    verdict = V.determine_verdict(
        gates=gates, e_a=e_a, e_s1=e_s1, e_s075=e_s075, e_plac=e_plac,
        placebo_ci=placebo_ci, preservation=pres, failure=failure,
        by_year=by_year, by_side=by_side, nonentry=nonentry)

    align_all = align.filter(pl.col("group") == "ALL").to_dicts()[0]
    pres_s1 = pres.filter(pl.col("policy") == "S1").to_dicts()[0]
    fail_s1 = failure.filter(pl.col("policy") == "S1").to_dicts()[0]
    fail_pl = failure.filter(pl.col("policy") == "PLACEBO_EXIT").to_dicts()[0]
    stopcmp = pl.read_csv(OUT / "stop_comparison.csv").to_dicts()[0]
    cap_s1 = pl.read_csv(OUT / "confirmation_capture.csv").filter(
        pl.col("policy") == "S1").to_dicts()[0]
    xvc = pl.read_csv(OUT / "exit_vs_confirmation.csv").filter(
        pl.col("policy") == "S1")

    def xcls(name: str) -> dict:
        return xvc.filter(pl.col("class") == name).to_dicts()[0]

    # Manifest item 20: the 15 report answers, keyed q1-q15, machine-readable.
    answers = {
        "q1_pct_arms_5s_aligned": align_all["pct_aligned"],
        "q2_confirming_mae": {
            "censored_note": "bounded below 1.00 ATR BY CONSTRUCTION",
            "see": "results/confirming_trade_mae.csv",
        },
        "q3_confirmers_killed_by_075_surviving_100": {
            "n": pres_s1["n_killed_by_075_surviving_100"],
            "pct": pres_s1["pct_killed_by_075_surviving_100"],
        },
        "q4_expectancy": {
            "per_entered_trade": {"S1": e_s1["exp_per_entry_net"],
                                  "S075": e_s075["exp_per_entry_net"]},
            "per_original_arm": {"S1": e_s1["exp_per_arm_net"],
                                 "S075": e_s075["exp_per_arm_net"],
                                 "A_LIFECYCLE": e_a["net_atr_per_arm"]},
        },
        "q5_capture": {"vs_confirm_return": cap_s1["capture_vs_confirm_return"],
                       "vs_confirm_mfe": cap_s1["capture_vs_confirm_mfe"]},
        "q6_5s_exit_before_confirmation": {
            "pct_5s_exit_first": xcls("5S_EXIT_BEFORE_1M_CONFIRM")["pct"],
            "pct_confirm_first": xcls("1M_CONFIRM_BEFORE_5S_EXIT")["pct"],
        },
        "q7_holding_through_confirmation": {
            "median_incremental_atr": cap_s1["median_incremental_atr"],
            "ci": [cap_s1["incremental_ci_low"], cap_s1["incremental_ci_high"]],
            "ci_excludes_zero": cap_s1["incremental_ci_excludes_zero"],
        },
        "q8_failed_p90_signals": {
            "accepted_net_atr_per_failure_arm": fail_s1["accepted_net_atr_per_failure_arm"],
            "s1_net_atr_per_failure_arm": fail_s1["net_atr_per_failure_arm"],
            "placebo_net_atr_per_failure_arm": fail_pl["net_atr_per_failure_arm"],
        },
        "q9_failures_become_smaller_losses": {
            "s1_mean_loss": fail_s1["mean_loss"],
            "pct_out_before_100_adverse": fail_s1["pct_exited_before_100_adverse"],
        },
        "q10_075_vs_100": {
            "d_exp_per_arm": stopcmp["d_exp_per_arm"],
            "d_max_dd": stopcmp["d_max_dd"],
            "n_confirm_trades_destroyed": stopcmp["n_confirm_trades_destroyed"],
            "pct_s1_trades_reaching_stop": e_s1["n_stop"] / max(e_s1["n_entries"], 1),
        },
        "q11_year_stability": {
            str(r["entry_year"]): r["exp_per_arm_net"]
            for r in by_year.filter(pl.col("policy") == "S1").iter_rows(named=True)},
        "q12_side_consistency": {
            r["side"]: r["exp_per_arm_net"]
            for r in by_side.filter(pl.col("policy") == "S1").iter_rows(named=True)},
        "q13_nonentry_future_alignment": {
            r["bucket"]: r["pct"] for r in nonentry.iter_rows(named=True)},
        "q14_verdict": verdict["verdict"],
        "q15_next_study": (
            "ABANDON THE BRANCH. Fresh-5s-flip entry is ruled out by the Phase 11 "
            "age diagnostic (fresh entries perform the same as stale ones); "
            "5s-as-early-failure-exit is ruled out by PLACEBO_EXIT (the failure "
            "saving does not separate from a length-blind random hold)."),
    }

    summary = {
        "study": "p90_5s_regime_impulse",
        **verdict,
        "report_answers": answers,
        "placebo": placebo_ci,
        "benchmark_a_next_open": e_a,
        "S1": e_s1, "S075": e_s075, "PLACEBO_EXIT": e_plac,
        "alignment_all": align.filter(pl.col("group") == "ALL").to_dicts()[0],
        "cost_points_round_turn": COST_POINTS,
        "gates_passed": sum(1 for x in gates if x["pass"]),
        "gates_total": len(gates),
        "runtime_s": round(time.time() - t0, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    store = ROOT / "data/canonical/regime_complete_v1"
    inputs = {}
    for rel in ("data/canonical/regime_complete_v1/canonical_regime_paths_all.parquet",
                "data/canonical/regime_complete_v1/canonical_regimes_all.parquet",
                "data/canonical/regime_complete_v1/canonical_regime_scores_all.parquet",
                "data/canonical/regime_complete_v1/canonical_model_threshold_contracts.parquet",
                "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet",
                "studies/p90_5s_regime_impulse/_work/regime_5s_flips.parquet"):
        p = ROOT / rel
        inputs[rel] = {
            "exists": p.exists(),
            "size_bytes": p.stat().st_size if p.exists() else None,
            "rows": (pl.scan_parquet(p).select(pl.len()).collect().item()
                     if p.exists() else None),
        }

    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "p90_5s_regime_impulse",
        "inputs": inputs,
        "code_sha256": _code_hash(),
        "seed": SEED,
        "arms": ARMED_REQUIRED,
        "market_rth_1s_bars": market.n,
        "regime_5s_build": r5_meta,
        "stop_grid_atr": [1.00, 0.75],
        "cost_points_round_turn": COST_POINTS,
        "years": [2021, 2022, 2023, 2024, 2025],
        "sealed_years": [2026],
        "entry_fill_convention": "open of first 1s bar with path_init_ns > arm_ns",
        "exit_fill_convention": "open of first 1s bar after the 5s bucket close_ts",
        "generated_not_committed": ["_work/regime_5s_flips.parquet"],
        "supporting_artifacts_beyond_the_manifest": [
            "results/benchmark_a_reference.parquet",
            "results/benchmark_a_next_open.parquet",
            "results/trades_placebo_exit.parquet",
        ],
    }, indent=2, default=str))

    print(json.dumps({k: summary[k] for k in ("verdict", "facts")}, indent=2))
    print(f"gates {summary['gates_passed']}/{summary['gates_total']}  "
          f"[{summary['runtime_s']}s]")


if __name__ == "__main__":
    main()
