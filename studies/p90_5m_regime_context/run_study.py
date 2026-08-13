"""Runner for the P90 entry path x 5-minute regime context study.

    python -m studies.p90_5m_regime_context.implementation.regime_5m   # build (once)
    python -m studies.p90_5m_regime_context.implementation.lineage     # Phase 0
    python -m studies.p90_5m_regime_context.run_study
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import polars as pl

from studies.p90_5m_regime_context.implementation import analysis as A
from studies.p90_5m_regime_context.implementation import classify as C
from studies.p90_5m_regime_context.implementation import lineage as L
from studies.p90_5m_regime_context.implementation import regime_5m as R5M
from studies.p90_5m_regime_context.implementation import validate as V

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "studies/p90_5m_regime_context/results"
STUDY_DIR = ROOT / "studies/p90_5m_regime_context"


def _code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(STUDY_DIR.rglob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()


def _run_parity_tests() -> bool:
    print("running the 5m regime parity test suite (SPEC 9.4 gate) ...", flush=True)
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         "studies/p90_5m_regime_context/tests/test_regime_5m_parity.py", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(r.stdout[-2000:])
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
    return r.returncode == 0


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    # Stop condition 4: parity gate before any classification runs.
    parity_ok = _run_parity_tests()
    if not parity_ok:
        raise RuntimeError("SPEC 9.4 ABORT -- 5m regime parity test failed")

    # Phase 0
    arms = L.load_arms()
    lineage = L.reconcile(arms)
    (OUT / "lineage_reconciliation.json").write_text(json.dumps(lineage, indent=2))
    if not lineage["all_reproduced"]:
        raise RuntimeError(f"SPEC 9 ABORT -- Phase 0 failed: {lineage['failed']}")
    print(f"Phase 0 OK -- {arms.height:,} arms reconciled  [{time.time()-t0:.0f}s]", flush=True)

    if not R5M.BUILD_META.exists():
        raise RuntimeError(
            "5m regime not built -- run `python -m "
            "studies.p90_5m_regime_context.implementation.regime_5m` first")
    build_meta = json.loads(R5M.BUILD_META.read_text())
    if not (build_meta["buckets_reconcile"] and build_meta["rows_reconcile"]):
        raise RuntimeError("SPEC 9 ABORT -- 5m bucket/row reconciliation failed")
    r5m = R5M.load()
    print(f"5m regime loaded -- {r5m.n:,} flips  [{time.time()-t0:.0f}s]", flush=True)

    # Classification
    classification = C.classify_core(arms, r5m)
    classification.write_parquet(OUT / "p90_classification.parquet")
    phase6_labels = C.phase6_future_flip_labels(arms, r5m)
    strata = C.phase11_strata(arms)
    base = A.build_base(arms, classification)
    print(f"classification done -- {classification.height:,} arms  [{time.time()-t0:.0f}s]", flush=True)

    # Phases 1-11 + primary tables
    p1 = A.phase1_context(base)
    p1.write_csv(OUT / "p90_5m_context.csv")

    p2 = A.phase2_pre_confirm(base)
    p2.write_csv(OUT / "pre_confirm_outcome.csv")

    p3 = A.phase3_confirmation_speed(base)
    p3.write_csv(OUT / "confirmation_speed.csv")

    p4 = A.phase4_mfe_quality(base)
    p4.write_csv(OUT / "mfe_quality.csv")

    transition_matrix = A.phase5_transition_matrix(base)
    transition_matrix.write_csv(OUT / "transition_matrix.csv")
    against_with_deep_dive = A.phase5_against_with_deep_dive(transition_matrix)
    against_with_deep_dive.write_csv(OUT / "against_with_deep_dive.csv")

    phase6_timing = A.phase6_timing(phase6_labels, arms)
    phase6_timing.write_csv(OUT / "phase6_timing.csv")
    phase6_bucket_summary = A.phase6_bucket_summary(phase6_timing)

    p7 = A.phase7_regime_age(base)
    p7.write_csv(OUT / "regime_age_outcomes.csv")

    p8 = A.phase8_5s_failure(arms, classification, r5m)
    p8.write_csv(OUT / "five_m_x_5s_failure.csv")

    p9 = A.phase9_stop_context(base)
    p9.write_csv(OUT / "stop_075_context.csv")

    e10 = A.phase10_full_economics(base)
    e10.write_csv(OUT / "full_economics.csv")
    by_year = A.phase10_by_year(base)
    by_year.write_csv(OUT / "full_economics_by_year.csv")
    by_side = A.phase10_by_side(base)
    by_side.write_csv(OUT / "full_economics_by_side.csv")

    p11 = A.phase11_matched_control(base, strata)
    p11.write_csv(OUT / "matched_stratified_control.csv")

    primary = A.primary_table(base)
    primary.write_csv(OUT / "primary_table.csv")
    print(f"Phases 1-11 written  [{time.time()-t0:.0f}s]", flush=True)

    # ------------------------------------------------------ gates and verdict
    non_phase6_frames = {
        "p90_classification": classification, "p90_5m_context": p1,
        "pre_confirm_outcome": p2, "confirmation_speed": p3, "mfe_quality": p4,
        "transition_matrix": transition_matrix, "against_with_deep_dive": against_with_deep_dive,
        "regime_age_outcomes": p7, "five_m_x_5s_failure": p8, "stop_075_context": p9,
        "full_economics": e10, "full_economics_by_year": by_year,
        "full_economics_by_side": by_side, "matched_stratified_control": p11,
        "primary_table": primary,
    }
    gates = V.run_gates(
        arms=arms, lineage=lineage, build_meta=build_meta, classification=classification,
        transition_matrix=transition_matrix, phase6_labels=phase6_labels,
        non_phase6_frames=non_phase6_frames, parity_tests_passed=parity_ok,
    )
    (OUT / "validation_report.json").write_text(json.dumps(
        {"gates": gates, "n_gates": len(gates),
         "n_failed": sum(1 for x in gates if not x["pass"])}, indent=2, default=str))

    verdict = V.determine_verdict(
        gates=gates, primary_table=primary, pre_confirm=p2,
        transition_matrix=transition_matrix, against_with_deep_dive=against_with_deep_dive,
        five_m_x_5s_failure=p8, phase11=p11.to_dicts()[0],
    )

    summary = {
        "study": "p90_5m_regime_context", **verdict,
        "primary_table": primary.to_dicts(),
        "phase6_bucket_summary": phase6_bucket_summary.to_dicts(),
        "gates_passed": sum(1 for x in gates if x["pass"]), "gates_total": len(gates),
        "runtime_s": round(time.time() - t0, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    inputs = {}
    for rel in ("data/canonical/regime_complete_v1/canonical_regime_paths_all.parquet",
               "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet",
               "studies/p90_5m_regime_context/_work/regime_5m_flips.parquet",
               "studies/p90_5m_regime_context/_work/regime_5m_buckets.parquet",
               "studies/p90_conditional_losing_5s_exit/results/adverse_5s_flip_events.parquet",
               "studies/p90_conditional_losing_5s_exit/results/baseline_100.parquet",
               "studies/p90_conditional_losing_5s_exit/results/baseline_075.parquet"):
        p = ROOT / rel
        inputs[rel] = {"exists": p.exists(),
                       "size_bytes": p.stat().st_size if p.exists() else None,
                       "rows": (pl.scan_parquet(p).select(pl.len()).collect().item()
                                if p.exists() else None)}
    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "p90_5m_regime_context",
        "predecessors": ["studies/p90_5s_regime_impulse", "studies/p90_conditional_losing_5s_exit"],
        "inputs": inputs, "code_sha256": _code_hash(), "seed": 20260812,
        "arms": L.ARMED_REQUIRED, "confirming": L.N_CONFIRMING_REF,
        "age_bucket_edges_min": list(C.AGE_BUCKET_EDGES_MIN),
        "time_of_day_edges_min": list(C.TOD_EDGES_MIN),
        "arm_score_quartile_edges": C.arm_score_quartiles(arms),
        "years": [2021, 2022, 2023, 2024, 2025], "sealed_years": [2026],
        "generated_not_committed": ["results/*.parquet", "results/*.csv", "_work/*"],
    }, indent=2, default=str))

    print(json.dumps({"verdict": verdict["verdict"], "secondary_signals": verdict["secondary_signals"]},
                     indent=2))
    print(f"gates {summary['gates_passed']}/{summary['gates_total']}  [{summary['runtime_s']}s]")


if __name__ == "__main__":
    main()
