"""Runner for the P90 regime-age x realized-progress quick diagnostic.

    python -m studies.p90_regime_age_progress_diagnostic.run_study

Order is load-bearing: Phase 0 verifies the ORIGINAL eligibility contract against the
accepted artifact BEFORE any population is built, so a contract mismatch stops the
study rather than being discovered after the tables exist.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import polars as pl

from studies.p90_regime_age_progress_diagnostic.implementation import analysis as A
from studies.p90_regime_age_progress_diagnostic.implementation import contract as C
from studies.p90_regime_age_progress_diagnostic.implementation import outcomes as O
from studies.p90_regime_age_progress_diagnostic.implementation import population as P
from studies.p90_regime_age_progress_diagnostic.implementation import validate as V

ROOT = Path(__file__).resolve().parents[2]
STUDY_DIR = ROOT / "studies/p90_regime_age_progress_diagnostic"
OUT = STUDY_DIR / "results"

EVENT_COLUMNS = [
    "regime_id", "population", "checkpoint_decision_ns", "entry_year", "side",
    "direction", "prevailing_regime", "regime_age_s", "running_mfe_atr",
    "current_progress_atr", "retained_mfe_ratio", "new_progress_windows",
    "atr_at_checkpoint", "probability", "age_bucket", "mfe_bucket",
    "velocity_atr_per_min", "velocity_quartile", "age_ge_1800s",
    "qualifies_under_600s_gate", "b_ns",
    "seconds_to_prevailing_flip", "flip_le_120s", "flip_le_180s", "flip_le_300s",
    "flip_censored", "secs_to_session_close", "flip_window_crosses_session_close",
    "flip_le_300s_session_gated",
    "terminal_label", "walk_valid", "ambiguous", "confirmed", "seconds_to_confirm",
    "mae_to_confirm_atr", "return_at_confirm_atr",
    "eventual_max_mfe_atr", "mfe_ge_1_0", "mfe_ge_2_0", "mfe_ge_3_0",
]


def _code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(STUDY_DIR.rglob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()


def _write_json(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    print(f"  wrote results/{name}", flush=True)


def _write_csv(name: str, df: pl.DataFrame) -> None:
    df.write_csv(OUT / name)
    print(f"  wrote results/{name}  ({df.height} rows)", flush=True)


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- Phase 0: the original contract, verified -------------------------
    print("PHASE 0  verifying the original model eligibility contract ...", flush=True)
    contract = C.build_contract()
    _write_json("phase0_contract.json", contract)
    failed = [r["item"] for r in contract["contract_rows"] if not r["match"]]
    if failed:
        raise SystemExit(f"ABORT: contract rows failed verification: {failed}")
    print(f"  {len(contract['contract_rows'])} contract rows verified; "
          f"{len(contract['discrepancies'])} discrepancies RECORDED", flush=True)

    # ---- Populations ------------------------------------------------------
    print("PHASE 1  building arm populations A and B ...", flush=True)
    pops = P.build_populations()
    scored, a, b = pops["scored"], pops["A"], pops["B"]
    print(f"  A={a.height}  B={b.height}  unique events={pops['unique_events'].height}",
          flush=True)

    _write_csv("p90_eligibility_base_rates.csv", P.eligibility_base_rates(scored))
    _write_csv("first_eligible_age_by_regime.csv", P.first_eligible_age_by_regime(scored))

    # ---- Outcomes, simulated once per distinct event ----------------------
    print("PHASE 2  simulating outcomes ...", flush=True)
    market, regimes = O.load_engines()
    ends = O.load_regime_ends()
    armed_ids = set(pops["unique_events"]["regime_id"].to_list())
    tiling = O.check_tiling(ends, armed_ids, regimes)
    print(f"  V-TILE: checked={tiling['n_checked']} mismatches={tiling['n_mismatches']} "
          f"censored={tiling['n_null_end_censored']}", flush=True)
    if not tiling["pass"]:
        raise SystemExit("ABORT: V-TILE failed -- regime end is not the next regime start")

    sim = O.simulate(pops["unique_events"], market, regimes, ends)
    print(f"  simulated {sim.height} distinct events", flush=True)

    # ---- Join outcomes onto both populations ------------------------------
    events = pl.concat([
        a.select(sorted(set(a.columns) & set(b.columns))),
        b.select(sorted(set(a.columns) & set(b.columns))),
    ]).join(sim, on=["regime_id", "checkpoint_decision_ns"], how="left")
    events = events.select([c for c in EVENT_COLUMNS if c in events.columns])
    events.write_parquet(OUT / "p90_events.parquet")
    print(f"  wrote results/p90_events.parquet ({events.height} rows)", flush=True)

    # ---- Tables -----------------------------------------------------------
    print("PHASE 3  aggregating ...", flush=True)
    cells = A.cell_table(events)
    _write_csv("primary_matrix.csv", A.primary_matrix(cells))
    _write_csv("outcome1_target.csv", A.outcome1_table(cells))
    _write_csv("outcome2_confirmation.csv", A.outcome2_table(cells))
    _write_csv("outcome3_opportunity.csv", A.outcome3_table(cells))

    velocity = A.velocity_table(events, pops["velocity_edges"])
    _write_csv("velocity_table.csv", velocity)

    comparison_tbl = A.population_comparison(events, pops["comparison"])
    _write_csv("population_comparison.csv", comparison_tbl)

    age_tbl = V.age_contrast(events)
    _write_csv("age_contrast.csv", age_tbl)

    _write_csv("year_side_stability.csv",
               A.year_side_stability(events, (V.YOUNG_BUCKET, V.OLD_BUCKET)))

    _write_json("population_lineage.json", {
        "expected_vs_observed": pops["comparison"],
        "tiling": tiling,
        "n_unique_simulated_events": sim.height,
        "note": ("B is NOT a clean subset: 354 regimes appear in both populations at "
                 "DIFFERENT arm timestamps (population A fires earlier). Only-in-B is 0."),
    })

    # ---- Gates and verdict ------------------------------------------------
    print("PHASE 4  gates and verdict ...", flush=True)
    gates = V.run_gates(scored=scored, comparison=pops["comparison"],
                        events=events, tiling=tiling, contract=contract)
    gates.append(V.check_grid_complete(cells))
    gates.extend(V.check_denominators(events, cells))
    n_fail = sum(1 for g in gates if not g["pass"])
    _write_json("validation_report.json", {"n_gates": len(gates), "n_failed": n_fail,
                                           "gates": gates})
    for g in gates:
        if not g["pass"]:
            print(f"  GATE FAILED: {g['gate']} expected={g['expected']} "
                  f"observed={g['observed']}", flush=True)

    verdict = V.classify(age_tbl, velocity, comparison_tbl)
    _write_json("summary.json", {
        "study": "p90_regime_age_progress_diagnostic",
        "years": "2021-2025 (2026 SEALED)",
        "n_gates": len(gates), "n_gates_failed": n_fail,
        "verdict": verdict,
        "population_fact": {
            "headline": ("The >600s gate is barely a restriction. The MODEL is what "
                         "excludes young regimes: the P90 qualify rate among ELIGIBLE "
                         "checkpoints rises ~180x with regime age."),
            "n_a_arms_excluded_by_600s_gate":
                pops["comparison"]["n_a_arms_excluded_by_600s_gate"],
            "n_a_arms_strictly_below_600s":
                pops["comparison"]["n_a_arms_strictly_below_600s"],
            "n_a": pops["comparison"]["n_a"], "n_b": pops["comparison"]["n_b"],
        },
        "discrepancies_recorded": [d["id"] for d in contract["discrepancies"]],
    })

    _write_json("partition_manifest.json", {
        "code_hash": _code_hash(),
        "inputs": {
            "scores": "data/canonical/regime_complete_v1/canonical_regime_scores_all.parquet",
            "regimes": "data/canonical/regime_complete_v1/canonical_regimes_all.parquet",
            "paths": "data/canonical/regime_complete_v1/canonical_regime_paths_all.parquet",
        },
        "in_domain_scored_observations": scored.height,
        "frozen_thresholds_top_10": {"bullish": 0.43167249785595935,
                                     "bearish": 0.44559149246408103},
        "threshold_overlap_waiver": "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json",
        "frozen_age_edges": [list(e) for e in P.AGE_EDGES],
        "frozen_mfe_edges": [list(e) for e in P.MFE_EDGES],
        "frozen_velocity_quartile_edges": list(pops["velocity_edges"]),
        "stop_atr": 1.0,
        "thin_cell_n": P.THIN_CELL_N,
        "elapsed_s": round(time.time() - t0, 1),
    })

    print(f"\nDONE in {time.time() - t0:.1f}s   gates failed: {n_fail}   "
          f"verdict: {verdict['primary_verdict']}", flush=True)
    if n_fail:
        raise SystemExit(f"ABORT: {n_fail} gate(s) failed")


if __name__ == "__main__":
    main()
