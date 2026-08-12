"""Runner for the P90 conditional losing-5s-flip failure exit study.

    python -m studies.p90_conditional_losing_5s_exit.implementation.lineage
    python -m studies.p90_conditional_losing_5s_exit.run_study
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
from studies.p90_5s_regime_impulse.implementation import regime_5s as R5
from studies.p90_conditional_losing_5s_exit.implementation import analysis as A
from studies.p90_conditional_losing_5s_exit.implementation import validate as V
from studies.p90_conditional_losing_5s_exit.implementation.lineage import (
    ARMED_REQUIRED, attach_alignment, load_arms,
)
from studies.p90_conditional_losing_5s_exit.implementation.policy import (
    LOSING_5S_FLIP_EXIT, flip_events_frame, run_policy, to_frame,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "studies/p90_conditional_losing_5s_exit/results"
SEED = 20260812


def _code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / "studies/p90_conditional_losing_5s_exit").rglob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    lineage = json.loads((OUT / "lineage_reconciliation.json").read_text())
    if not lineage["all_reproduced"]:
        raise RuntimeError("SPEC 9 ABORT -- Phase 0 did not reproduce")

    arms = load_arms()
    market, regimes = load_market(), load_regimes()
    r5 = R5.load()
    arms = attach_alignment(arms, r5)
    entries = arms.filter(pl.col("entered"))
    print(f"arms={arms.height:,}  entries={entries.height:,}  "
          f"5s flips={r5.n:,}  [{time.time()-t0:.0f}s]", flush=True)

    frames: dict[str, pl.DataFrame] = {}
    walks_cache = {}
    for name, stop, cond in (("BASELINE_1.00", 1.00, False),
                             ("COND_1.00", 1.00, True),
                             ("BASELINE_0.75", 0.75, False),
                             ("COND_0.75", 0.75, True)):
        print(f"simulating {name} ...", flush=True)
        w = run_policy(entries, market, regimes, r5, stop, conditional=cond)
        walks_cache[name] = w
        frames[name] = to_frame(w)

    # Phase 1 base: every adverse flip over the BASELINE 1.00 window
    flips = flip_events_frame(walks_cache["BASELINE_1.00"], arms)
    flips.write_parquet(OUT / "adverse_5s_flip_events.parquet")
    print(f"  {flips.height:,} adverse 5s flip events", flush=True)

    # ---------------------------------------------- Phase 11: matched placebo
    # k and tau both drawn from POOLED distributions, never from the trade's own
    # realised flip count or lifetime (SPEC section 7).
    counts_pool = frames["BASELINE_1.00"].filter(
        pl.col("entered"))["n_adverse_flips"].to_numpy()
    times_pool = flips["seconds_since_entry"].to_numpy()
    draws = []
    for _ in range(entries.height):
        k = int(rng.choice(counts_pool))
        draws.append(np.sort(rng.choice(times_pool, size=k, replace=True))
                     if k > 0 else np.empty(0))
    print(f"simulating PLACEBO_COND_1.00 (pooled k and tau) ...", flush=True)
    w_plac = run_policy(entries, market, regimes, r5, 1.00, conditional=True,
                        placebo_draws=draws)
    frames["PLACEBO_COND_1.00"] = to_frame(w_plac)

    # p_unreached: the share of drawn placebo check times that fell beyond the
    # trade's natural end and could never fire. SPEC section 7 makes this a
    # mandatory disclosure -- a control whose draws mostly land outside the
    # window is not actually matched, and this fraction is the only way to see
    # it. (`placebo_must_be_length_blind`.)
    pf = frames["PLACEBO_COND_1.00"].filter(pl.col("entered"))
    n_cand = int(pf["n_placebo_candidates"].sum())
    n_unreach = int(pf["n_placebo_unreached"].sum())
    placebo_meta = {
        "counts_and_times_pooled": True,
        "count_pool_median": float(np.median(counts_pool)),
        "time_pool_median_s": float(np.median(times_pool)),
        "n_placebo_candidates": n_cand,
        "n_placebo_unreached": n_unreach,
        "p_unreached": (n_unreach / n_cand) if n_cand else float("nan"),
        "seed": SEED,
    }

    # ------------------------------------------------------------- economics
    econ = {k: A.economics(v, k, rng) for k, v in frames.items()}
    pl.DataFrame(list(econ.values()), infer_schema_length=None).write_csv(
        OUT / "primary_economics.csv")

    deltas = {
        "COND_1.00": A.paired_delta(frames["BASELINE_1.00"], frames["COND_1.00"], rng),
        "COND_0.75": A.paired_delta(frames["BASELINE_0.75"], frames["COND_0.75"], rng),
    }
    # placebo - conditional: the real rule wins if this is negative and excludes 0
    placebo_delta = A.paired_delta(frames["COND_1.00"],
                                   frames["PLACEBO_COND_1.00"], rng)

    for name, path in (("BASELINE_1.00", "baseline_100.parquet"),
                       ("COND_1.00", "conditional_100.parquet"),
                       ("BASELINE_0.75", "baseline_075.parquet"),
                       ("COND_0.75", "conditional_075.parquet")):
        frames[name].join(arms.select("regime_id", "terminal_label_full"),
                          on="regime_id", how="left").write_parquet(OUT / path)
    frames["PLACEBO_COND_1.00"].write_parquet(OUT / "placebo_conditional_100.parquet")

    # ---------------------------------------------------------------- tables
    A.flip_geometry(flips).write_csv(OUT / "flip_state_geometry.csv")
    A.signal_coverage(frames["BASELINE_1.00"], flips, arms).write_csv(
        OUT / "trade_level_signal_coverage.csv")
    conf = A.confusion(frames["BASELINE_1.00"], flips, arms)
    conf.write_csv(OUT / "failure_confusion_matrix.csv")

    harvest = pl.concat([
        A.failure_harvest(frames["BASELINE_1.00"], frames["COND_1.00"], arms, "COND_1.00"),
        A.failure_harvest(frames["BASELINE_0.75"], frames["COND_0.75"], arms, "COND_0.75"),
        A.failure_harvest(frames["BASELINE_1.00"], frames["PLACEBO_COND_1.00"], arms,
                          "PLACEBO_COND_1.00"),
    ])
    harvest.write_csv(OUT / "failure_harvest.csv")

    destruction = pl.concat([
        A.good_trade_destruction(frames["BASELINE_1.00"], frames["COND_1.00"],
                                 arms, "COND_1.00", "losing_5s"),
        A.good_trade_destruction(frames["BASELINE_0.75"], frames["COND_0.75"],
                                 arms, "COND_0.75", "losing_5s"),
        A.good_trade_destruction(frames["BASELINE_1.00"], frames["BASELINE_0.75"],
                                 arms, "BASELINE_0.75", "tighter_stop"),
        A.good_trade_destruction(frames["COND_1.00"], frames["COND_0.75"],
                                 arms, "COND_0.75", "tighter_stop"),
    ])
    destruction.write_csv(OUT / "good_trade_destruction.csv")

    sav = []
    for pol, basename in (("COND_1.00", "BASELINE_1.00"), ("COND_0.75", "BASELINE_0.75")):
        h = harvest.filter(pl.col("policy") == pol).to_dicts()[0]
        dd = destruction.filter((pl.col("policy") == pol)
                                & (pl.col("source") == "losing_5s")).to_dicts()[0]
        saved = h["atr_saved_total"]
        forfeited = dd["atr_forfeited_total"]
        sav.append({
            "policy": pol,
            "failure_atr_saved": saved,
            "good_trade_atr_forfeited": forfeited,
            "net_difference": saved + forfeited,
            "net_atr_per_original_arm": deltas[pol]["delta_per_arm"],
            "delta_ci_low": deltas[pol]["delta_ci_low"],
            "delta_ci_high": deltas[pol]["delta_ci_high"],
            "delta_ci_excludes_zero": deltas[pol]["delta_ci_excludes_zero"],
            "d_max_dd": econ[pol]["max_dd_atr"] - econ[basename]["max_dd_atr"],
            "savings_sacrifice_ratio": (abs(saved / forfeited)
                                        if forfeited else float("nan")),
        })
    pl.DataFrame(sav).write_csv(OUT / "savings_vs_sacrifice.csv")

    pl.concat([A.pre_post_confirm(frames["BASELINE_1.00"], frames["COND_1.00"], "COND_1.00"),
               A.pre_post_confirm(frames["BASELINE_0.75"], frames["COND_0.75"], "COND_0.75")]
              ).write_csv(OUT / "pre_post_confirm.csv")
    pl.concat([A.flip_sequence(frames["BASELINE_1.00"], frames["COND_1.00"], arms, "COND_1.00"),
               A.flip_sequence(frames["BASELINE_0.75"], frames["COND_0.75"], arms, "COND_0.75")]
              ).write_csv(OUT / "flip_sequence.csv")
    A.stop_interaction(frames["COND_1.00"], frames["COND_0.75"], arms).write_csv(
        OUT / "stop_interaction.csv")

    pl.DataFrame([{
        "policy": "PLACEBO_COND_1.00",
        "n_fired": econ["PLACEBO_COND_1.00"]["n_conditional_exits"],
        "n_fired_conditional": econ["COND_1.00"]["n_conditional_exits"],
        "mean_net_atr": econ["PLACEBO_COND_1.00"]["exp_per_entry_net"],
        "exp_per_arm_net": econ["PLACEBO_COND_1.00"]["exp_per_arm_net"],
        "conditional_exp_per_arm_net": econ["COND_1.00"]["exp_per_arm_net"],
        "ci_low": econ["PLACEBO_COND_1.00"]["ci_low"],
        "ci_high": econ["PLACEBO_COND_1.00"]["ci_high"],
        # manifest's literal name, plus the self-describing alias -- the sign
        # convention matters here: this is placebo MINUS conditional, so the
        # real rule wins only if it is negative and its CI excludes zero
        "delta_vs_conditional": placebo_delta["delta_per_arm"],
        "delta_placebo_minus_conditional": placebo_delta["delta_per_arm"],
        "delta_ci_low": placebo_delta["delta_ci_low"],
        "delta_ci_high": placebo_delta["delta_ci_high"],
        "delta_ci_excludes_zero": placebo_delta["delta_ci_excludes_zero"],
        "conditional_beats_placebo": bool(placebo_delta["delta_ci_excludes_zero"]
                                          and placebo_delta["delta_per_arm"] < 0),
        **placebo_meta,
    }]).write_csv(OUT / "matched_placebo.csv")

    by_year = pl.concat([A.by_group(f, k, "entry_year", arms) for k, f in frames.items()])
    by_year.write_csv(OUT / "by_year.csv")
    by_side = pl.concat([A.by_group(f, k, "side", arms) for k, f in frames.items()])
    by_side.write_csv(OUT / "by_side.csv")

    # ------------------------------------------------------ gates and verdict
    gates = V.run_gates(arms=arms, lineage=lineage, frames=frames, flips=flips,
                        placebo_meta=placebo_meta)
    (OUT / "validation_report.json").write_text(json.dumps(
        {"gates": gates, "n_gates": len(gates),
         "n_failed": sum(1 for x in gates if not x["pass"])}, indent=2, default=str))

    verdict = V.determine_verdict(
        gates=gates, econ=econ, deltas=deltas, harvest=harvest,
        destruction=destruction, confusion=conf, by_year=by_year,
        by_side=by_side, placebo_delta=placebo_delta)

    cov = pl.read_csv(OUT / "trade_level_signal_coverage.csv")
    cov_f = cov.filter(pl.col("cohort") == "failure").to_dicts()[0]
    cov_c = cov.filter(pl.col("cohort") == "confirming").to_dicts()[0]
    crow = conf.filter(pl.col("group") == "ALL").to_dicts()[0]
    h1 = harvest.filter(pl.col("policy") == "COND_1.00").to_dicts()[0]
    d1 = destruction.filter((pl.col("policy") == "COND_1.00")
                            & (pl.col("source") == "losing_5s")).to_dicts()[0]
    ppc = pl.read_csv(OUT / "pre_post_confirm.csv").filter(
        pl.col("policy") == "COND_1.00")
    sv = pl.read_csv(OUT / "savings_vs_sacrifice.csv")

    answers = {
        "q1_pct_failures_with_losing_flip_before_1atr": cov_f["pct_losing_before_1atr_stop"],
        "q2_pct_confirmers_with_same_signal_before_confirm": cov_c["pct_losing_before_confirm"],
        "q3_ppv": {"ppv": crow["ppv"], "prevalence": crow["prevalence"],
                   "lift": crow["ppv"] - crow["prevalence"]},
        "q4_median_loss_at_conditional_exit": float(
            frames["COND_1.00"].filter(pl.col("outcome") == LOSING_5S_FLIP_EXIT)
            ["return_at_fire_atr"].median()),
        "q5_atr_saved_on_failures": h1["atr_saved_total"],
        "q6_atr_forfeited_on_successes": d1["atr_forfeited_total"],
        "q7_savings_sacrifice_ratio": sv.filter(
            pl.col("policy") == "COND_1.00")["savings_sacrifice_ratio"].item(),
        "q8_cond_100_improves_per_arm": deltas["COND_1.00"],
        "q9_cond_075_improves_further": deltas["COND_0.75"],
        "q10_does_075_still_add_value": {
            "cond_075_minus_cond_100_per_arm":
                econ["COND_0.75"]["exp_per_arm_net"] - econ["COND_1.00"]["exp_per_arm_net"],
            "see": "results/stop_interaction.csv"},
        "q11_maxdd": {k: econ[k]["max_dd_atr"] for k in econ},
        "q12_year_stability": "results/by_year.csv",
        "q13_side_consistency": "results/by_side.csv",
        "q14_before_vs_after_confirm": ppc.to_dicts(),
        "q15_beats_matched_placebo": {
            "delta_placebo_minus_conditional": placebo_delta["delta_per_arm"],
            "ci": [placebo_delta["delta_ci_low"], placebo_delta["delta_ci_high"]],
            "ci_excludes_zero": placebo_delta["delta_ci_excludes_zero"],
            "conditional_beats_placebo": bool(
                placebo_delta["delta_ci_excludes_zero"]
                and placebo_delta["delta_per_arm"] < 0)},
        "q16_verdict": verdict["verdict"],
    }

    summary = {"study": "p90_conditional_losing_5s_exit", **verdict,
               "report_answers": answers, "economics": econ, "deltas": deltas,
               "placebo_delta": placebo_delta,
               "baseline_lifecycle": "FULL (hold through confirmation -> opposing flip)",
               "cost_points_round_turn": COST_POINTS,
               "gates_passed": sum(1 for x in gates if x["pass"]),
               "gates_total": len(gates),
               "runtime_s": round(time.time() - t0, 1)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    inputs = {}
    for rel in ("data/canonical/regime_complete_v1/canonical_regime_paths_all.parquet",
                "data/canonical/regime_complete_v1/canonical_regimes_all.parquet",
                "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet",
                "studies/p90_5s_regime_impulse/_work/regime_5s_flips.parquet"):
        p = ROOT / rel
        inputs[rel] = {"exists": p.exists(),
                       "size_bytes": p.stat().st_size if p.exists() else None,
                       "rows": (pl.scan_parquet(p).select(pl.len()).collect().item()
                                if p.exists() else None)}
    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "p90_conditional_losing_5s_exit",
        "predecessor": "studies/p90_5s_regime_impulse",
        "inputs": inputs, "code_sha256": _code_hash(), "seed": SEED,
        "arms": ARMED_REQUIRED, "entries": entries.height,
        "adverse_flip_events": flips.height,
        "stop_grid_atr": [1.00, 0.75],
        "conditional_threshold": "current_return_atr < 0",
        "cost_points_round_turn": COST_POINTS,
        "years": [2021, 2022, 2023, 2024, 2025], "sealed_years": [2026],
        "generated_not_committed": ["results/*.parquet", "results/*.csv"],
    }, indent=2, default=str))

    print(json.dumps({k: summary[k] for k in ("verdict", "facts")}, indent=2, default=str))
    print(f"gates {summary['gates_passed']}/{summary['gates_total']}  "
          f"[{summary['runtime_s']}s]")


if __name__ == "__main__":
    main()
