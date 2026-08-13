"""Runner for the post-confirmation 5m context x forward opportunity study.

    python -m studies.post_confirm_5m_forward_opportunity.implementation.lineage  # Phase 0
    python -m studies.post_confirm_5m_forward_opportunity.run_study
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

from studies.p90_5m_regime_context.implementation import regime_5m as R5M
from studies.post_confirm_5m_forward_opportunity.implementation import analysis as A
from studies.post_confirm_5m_forward_opportunity.implementation import join as J
from studies.post_confirm_5m_forward_opportunity.implementation import lineage as L
from studies.post_confirm_5m_forward_opportunity.implementation import validate as V

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "studies/post_confirm_5m_forward_opportunity/results"
STUDY_DIR = ROOT / "studies/post_confirm_5m_forward_opportunity"
SEED = 20260811


def _code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(STUDY_DIR.rglob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()


def _run_tests() -> bool:
    print("running causality + capture-curve unit tests (SPEC section 8 stop conditions 3, 5) ...",
         flush=True)
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         "studies/post_confirm_5m_forward_opportunity/tests/test_join_causality.py", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(r.stdout[-2000:])
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
    return r.returncode == 0


def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    tests_ok = _run_tests()
    if not tests_ok:
        raise RuntimeError("SPEC 8 ABORT -- causality/capture-curve unit tests failed")

    # Phase 0
    arms = L.load_arms()
    classification = L.load_classification()
    panel_ids = L.load_panel_trade_ids()
    pop = L.build_population(arms, classification, panel_ids)
    lineage = L.reconcile(arms, classification, panel_ids, pop)
    (OUT / "lineage_reconciliation.json").write_text(json.dumps(lineage, indent=2, default=str))
    if not lineage["all_reproduced"]:
        raise RuntimeError(f"SPEC 8 ABORT -- Phase 0 failed: {lineage['failed']}")

    tm_rows = []
    GROUP_TRANSITION_LABEL = {"WITH_WITH": "WITH_5M", "AGAINST_WITH": "WITH_5M",
                              "WITH_AGAINST": "AGAINST_5M", "AGAINST_AGAINST": "AGAINST_5M"}
    GROUP_STABLE_LABEL = {"WITH_WITH": "WITH_5M", "AGAINST_AGAINST": "AGAINST_5M"}
    for t, n in lineage["checks"]["transition_matrix"]["observed"].items():
        tm_rows.append({"transition": t, "n": n,
                        "group_transition_label": GROUP_TRANSITION_LABEL[t],
                        "group_stable_label": GROUP_STABLE_LABEL.get(t)})
    pl.DataFrame(tm_rows).write_csv(OUT / "transition_matrix.csv")
    print(f"Phase 0 OK  [{time.time()-t0:.0f}s]", flush=True)

    # Phase 1
    r5m = R5M.load()
    confirmation_state = J.build_confirmation_state(arms, classification, r5m, panel_ids)
    confirmation_state.write_parquet(OUT / "confirmation_state.parquet")
    print(f"Phase 1 OK -- {confirmation_state.height} confirmed trades  [{time.time()-t0:.0f}s]",
         flush=True)

    # Phases 2-11, 13
    panel = A.load_panel()
    joined = A.build_joined(panel, confirmation_state)

    p2 = A.phase2_landmark_attrition(joined)
    p2.write_csv(OUT / "landmark_attrition.csv")

    p3 = A.phase3_mark_to_market(joined)
    p3.write_csv(OUT / "mark_to_market.csv")

    p4 = A.phase4_incremental_mfe(joined)
    p4.write_csv(OUT / "incremental_mfe.csv")

    p5 = A.phase5_remaining_mfe(joined)
    p5.write_csv(OUT / "remaining_mfe.csv")

    curve, threshold_tbl = A.phase6_capture_curve(joined, confirmation_state)
    curve.write_csv(OUT / "opportunity_capture.csv")
    threshold_tbl.write_csv(OUT / "opportunity_capture_time_to_threshold.csv")
    print(f"Phase 6 OK (gate V-RECONCILE passed)  [{time.time()-t0:.0f}s]", flush=True)

    p7 = A.phase7_new_extreme_probability(joined)
    p7.write_csv(OUT / "new_extreme_probability.csv")

    p8 = A.phase8_adverse_path(joined)
    p8.write_csv(OUT / "adverse_path.csv")

    p9 = A.phase9_giveback_timing(joined)
    p9.write_csv(OUT / "giveback_timing.csv")

    rng = np.random.default_rng(SEED)
    p10 = A.phase10_continuation_value(joined, rng)
    p10.write_csv(OUT / "continuation_value.csv")

    p11 = A.phase11_mfe_quality_buckets({"joined": joined})
    p11.write_csv(OUT / "mfe_quality_buckets.csv")

    strata = A.phase12_strata(confirmation_state)
    p12 = A.phase12_matched_confirmation_control(joined, confirmation_state, strata, rng)
    p12.write_csv(OUT / "matched_confirmation_control.csv")

    p13 = A.phase13_year_side_stability(joined)
    p13.write_csv(OUT / "year_side_stability.csv")

    primary = A.primary_table(joined, confirmation_state)
    primary.write_csv(OUT / "primary_table.csv")

    opp_summary = A.opportunity_capture_summary(threshold_tbl, joined)
    opp_summary.write_csv(OUT / "opportunity_capture_summary.csv")
    print(f"Phases 2-13 + primary tables written  [{time.time()-t0:.0f}s]", flush=True)

    # ------------------------------------------------------ gates and verdict
    all_output_frames = {
        "landmark_attrition": p2, "mark_to_market": p3, "incremental_mfe": p4,
        "remaining_mfe": p5, "opportunity_capture": curve,
        "opportunity_capture_time_to_threshold": threshold_tbl,
        "new_extreme_probability": p7, "adverse_path": p8, "giveback_timing": p9,
        "continuation_value": p10, "mfe_quality_buckets": p11,
        "matched_confirmation_control": p12, "year_side_stability": p13,
        "primary_table": primary, "opportunity_capture_summary": opp_summary,
    }
    gates = V.run_gates(
        lineage=lineage, confirmation_state=confirmation_state, landmark_attrition=p2,
        adverse_path=p8, phase12_strata_cols=A.STRATA_COLS, all_output_frames=all_output_frames,
        race_pairs=A.RACE_PAIRS,
    )
    (OUT / "validation_report.json").write_text(json.dumps(
        {"gates": gates, "n_gates": len(gates),
         "n_failed": sum(1 for x in gates if not x["pass"])}, indent=2, default=str))

    verdict = V.determine_verdict(
        gates=gates, primary_table=primary, phase12=p12, phase6_threshold=threshold_tbl,
        phase9_giveback=p9, phase13=p13, phase11=p11,
    )

    summary = {
        "study": "post_confirm_5m_forward_opportunity", **verdict,
        "primary_table": primary.to_dicts(),
        "opportunity_capture_summary": opp_summary.to_dicts(),
        "phase12_matched_control": p12.to_dicts(),
        "gates_passed": sum(1 for x in gates if x["pass"]), "gates_total": len(gates),
        "runtime_s": round(time.time() - t0, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    inputs = {}
    for rel in ("studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet",
               "studies/p90_5m_regime_context/results/p90_classification.parquet",
               "studies/p90_5m_regime_context/_work/regime_5m_flips.parquet",
               "studies/post_confirm_forward_opportunity/results/observation_panel.parquet"):
        p = ROOT / rel
        inputs[rel] = {"exists": p.exists(),
                       "size_bytes": p.stat().st_size if p.exists() else None,
                       "rows": (pl.scan_parquet(p).select(pl.len()).collect().item()
                                if p.exists() else None)}
    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "post_confirm_5m_forward_opportunity",
        "predecessors": ["studies/p90_5m_regime_context", "studies/post_confirm_forward_opportunity"],
        "inputs": inputs, "code_sha256": _code_hash(), "seed": SEED,
        "landmarks_s": list(A.LANDMARKS), "capture_thresholds": list(A.CAPTURE_THRESHOLDS),
        "confirm_mfe_edges": list(A.CONFIRM_MFE_EDGES), "confirm_mae_edges": list(A.CONFIRM_MAE_EDGES),
        "confirm_return_edges": list(A.CONFIRM_RETURN_EDGES), "confirm_speed_edges": list(A.CONFIRM_SPEED_EDGES),
        "years": [2021, 2022, 2023, 2024, 2025], "sealed_years": [2026],
        "generated_not_committed": ["results/*.parquet", "results/*.csv"],
    }, indent=2, default=str))

    print(json.dumps({"verdict": verdict["verdict"], "facts": verdict.get("facts", {})}, indent=2))
    print(f"gates {summary['gates_passed']}/{summary['gates_total']}  [{summary['runtime_s']}s]")


if __name__ == "__main__":
    main()
