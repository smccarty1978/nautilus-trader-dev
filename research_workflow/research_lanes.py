"""Research lanes: proportional validation (WORKFLOW.md §Q).

Pure functions. ``route`` picks the cheapest lane the study's own facts allow. A declared ``research_lane`` in
``research_decision.yaml`` can only RAISE the lane, never lower it below what the facts require. ``required_gates``
is the validation budget for that lane. ``validate_execution_claim`` refuses an execution-validation claim that is
not an independent NT runtime reconstruction.

This module selects and reports. The controller's own stage gates (causal audit, seal, OOS latch, ...) are unchanged
and still enforced by the controller.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

FAST_OBSERVATION = "FAST_OBSERVATION"
RESEARCH_VALIDATION = "RESEARCH_VALIDATION"
EXECUTION_VALIDATION = "EXECUTION_VALIDATION"
PLATFORM_CHANGE = "PLATFORM_CHANGE"
HISTORICAL = "HISTORICAL"
LANES = (FAST_OBSERVATION, RESEARCH_VALIDATION, EXECUTION_VALIDATION, PLATFORM_CHANGE)
_RANK = {FAST_OBSERVATION: 0, RESEARCH_VALIDATION: 1, EXECUTION_VALIDATION: 2, PLATFORM_CHANGE: 2}

# Validation budget per lane (WORKFLOW.md §Q.3). Every lane keeps causality; cost grows with the claim.
_GATES: Dict[str, List[str]] = {
    FAST_OBSERVATION: ["compile_proof", "synthetic_causal_tests", "observer_causality_harness", "causal_audit",
                       "frozen_definitions_before_outcomes", "bounded_smoke_full_pipeline", "single_full_collection",
                       "lane_manifest"],
    RESEARCH_VALIDATION: ["compile_proof", "synthetic_causal_tests", "observer_causality_harness", "causal_audit",
                          "frozen_definitions_before_outcomes", "bounded_smoke_full_pipeline", "single_full_collection",
                          "lane_manifest", "contract_audit", "seal", "independent_reference_parity",
                          "population_timestamp_reconciliation", "chronological_validation", "oos_latch",
                          "targeted_integration_tests"],
    EXECUTION_VALIDATION: ["compile_proof", "synthetic_causal_tests", "causal_audit", "lane_manifest", "contract_audit",
                           "seal", "nt_runtime_candidate_generation", "nt_runtime_features_and_scores",
                           "order_fill_exit_realism", "session_end_behaviour", "research_vs_execution_reconciliation"],
    PLATFORM_CHANGE: ["capability_contract", "targeted_capability_tests", "synthetic_causal_tests", "parity_evidence",
                      "registry_check", "merge_tier_gate", "capability_promotion"],
    HISTORICAL: [],
}
EXPENSIVE_GATES = {"broad_test_delta", "contract_audit", "capability_promotion", "full_history_parity",
                   "nt_runtime_candidate_generation", "order_fill_exit_realism"}
RECONCILIATION_KEYS = ("missing_candidates", "extra_candidates", "duplicate_candidates", "retimed_candidates",
                       "feature_score_differences", "trigger_differences", "orders", "fills", "exits", "costs")


def route(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """facts (all optional):
    closed / sealed (bool)                 -> HISTORICAL: keeps its own evidence and contracts, nothing is re-selected
    shared_code_changed (bool)             -> PLATFORM_CHANGE
    missing_capability (bool), local_route_possible (bool, default True), reuse_consumers (int)
                                            -> PLATFORM_CHANGE only when no study-local route exists or >= 2 studies need it
    trading_backtest / order_simulation (bool) -> EXECUTION_VALIDATION
    oos_confirmation (bool: a model fit or confirmation on a held-out year), prior_verdict == "VALIDATE"
                                            -> RESEARCH_VALIDATION
    declared_lane (str)                    -> may raise the lane, never lower it
    """
    why: List[str] = []
    if facts.get("closed") or facts.get("sealed"):
        return {"lane": HISTORICAL, "why": ["sealed/closed study: historical authority is immutable; no gate re-selected"]}
    lane = FAST_OBSERVATION
    why.append("default: exploratory observation")
    if facts.get("oos_confirmation") or str(facts.get("prior_verdict") or "").upper() == "VALIDATE":
        lane = RESEARCH_VALIDATION
        why.append("confirmation of a prior result / held-out evaluation")
    if facts.get("trading_backtest") or facts.get("order_simulation"):
        lane = EXECUTION_VALIDATION
        why.append("trading policy with orders and fills")
    platform = bool(facts.get("shared_code_changed"))
    if facts.get("missing_capability"):
        if not facts.get("local_route_possible", True):
            platform = True
            why.append("missing capability with no study-local observer route")
        elif int(facts.get("reuse_consumers") or 1) >= 2:
            platform = True
            why.append("capability needed by >= 2 studies: promote it")
        else:
            why.append("missing capability served by a study-local observer: no platform work")
    if platform:
        why.append("shared platform code changes")
    declared = facts.get("declared_lane")
    if declared:
        if declared not in LANES:
            raise ValueError(f"RESEARCH_LANE_UNKNOWN: {declared!r}; one of {LANES}")
        if _RANK[declared] > _RANK[lane] or declared == PLATFORM_CHANGE:
            lane = declared
            why.append(f"declared {declared}")
        elif declared != lane:
            why.append(f"declared {declared} ignored: the study's facts require {lane}")
    out = {"lane": PLATFORM_CHANGE if platform and lane != EXECUTION_VALIDATION else lane, "why": why}
    if platform and lane == EXECUTION_VALIDATION:
        out["also"] = [PLATFORM_CHANGE]          # the platform part goes through its chore first; execution gates still apply
    return out


def required_gates(lane: str, facts: Optional[Mapping[str, Any]] = None) -> List[str]:
    facts = dict(facts or {})
    if lane not in _GATES:
        raise ValueError(f"RESEARCH_LANE_UNKNOWN: {lane!r}")
    gates = list(_GATES[lane])
    if lane == PLATFORM_CHANGE:
        gates.append("broad_test_delta" if facts.get("merge_tier") != "ADDITIVE_CAPABILITY" else "derived_surface_test_delta")
        if facts.get("full_history_required"):
            gates.append("full_history_parity")
    elif facts.get("shared_code_changed"):
        gates.append("broad_test_delta")
    if not facts.get("study_local_observers"):
        gates = [g for g in gates if g != "observer_causality_harness"]
    if facts.get("population_frozen"):
        gates = [g for g in gates if g not in ("single_full_collection", "bounded_smoke_full_pipeline")]
    for cap in facts.get("consumed_capabilities") or []:
        if not cap.get("promotion_evidence_sha256"):
            raise ValueError(f"CAPABILITY_UNVERIFIED: {cap.get('id')!r} has no promotion evidence; it cannot be consumed")
    return gates


def validate_execution_claim(evidence: Mapping[str, Any]) -> Dict[str, Any]:
    """An EXECUTION_VALIDATION claim needs the NT engine to generate the candidates itself, plus a full reconciliation.
    A frozen precomputed schedule replayed through NT is refused (schedule-driven evaluation inflates PnL)."""
    problems: List[str] = []
    if str(evidence.get("candidate_source")) != "nt_runtime":
        problems.append(f"candidate_source must be 'nt_runtime' (got {evidence.get('candidate_source')!r}); "
                        "a precomputed trade schedule is not execution validation")
    if not evidence.get("features_computed_at_runtime"):
        problems.append("features must be computed by the runtime, not joined from research tables")
    if str(evidence.get("fill_model")) not in ("top_of_book", "nt_matching_engine"):
        problems.append("fills must come from top of book / the NT matching engine")
    rec = evidence.get("reconciliation") or {}
    missing = [k for k in RECONCILIATION_KEYS if k not in rec]
    if missing:
        problems.append(f"reconciliation lacks {missing}")
    return {"accepted": not problems, "problems": problems}


def facts_from_study(study_dir: Path) -> Dict[str, Any]:
    """Facts readable from the study's own files (no compile, no data)."""
    import yaml

    study_dir = Path(study_dir)
    spec = yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8")) or {}
    dec_p = study_dir / "research_decision.yaml"
    dec = (yaml.safe_load(dec_p.read_text(encoding="utf-8")) or {}) if dec_p.is_file() else {}
    art = study_dir / "artifacts"
    chron = spec.get("chronology") or {}
    model = spec.get("model")
    has_model = model not in (None, "none") and not (isinstance(model, Mapping) and model.get("kind") in (None, "none"))
    observers = sorted(n for n, c in (spec.get("context") or {}).items() if str((c or {}).get("tracker", "")).startswith("study_local:"))
    return {
        "closed": (art / "study_closure.json").is_file(),
        "sealed": (art / "seal.json").is_file() or (study_dir / "audit" / "seal.json").is_file(),
        "oos_confirmation": bool(has_model and chron.get("dev")),
        "trading_backtest": bool(spec.get("strategy_class") or (spec.get("execution") or {}).get("orders")),
        "study_local_observers": observers,
        "declared_lane": dec.get("research_lane"),
        "prior_verdict": dec.get("prior_verdict"),
    }


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lane_manifest(*, study_id: str, lane: str, dataset_id: str, dataset_digest: str, capability_versions: Mapping[str, str],
                  study_contract_sha256: str, plan_sha256: Optional[str], schema_version: str, period: Iterable[str],
                  outputs: Iterable[Path], validation: Mapping[str, str], verdict: str,
                  timestamp_convention: str = "int64 UTC ns; ts_event = bar open, ts_init = bar close = availability",
                  timezone: str = "UTC (sessions: America/Chicago)") -> Dict[str, Any]:
    """The one compact provenance record of a routine run (§Q.4). Large unchanged inputs are referenced by digest."""
    if verdict not in ("STOP", "REFINE", "VALIDATE", "PROMOTE"):
        raise ValueError(f"VERDICT_UNKNOWN: {verdict!r}")
    bad = [g for g, v in validation.items() if v not in ("PASS", "FAIL", "NOT_REQUIRED")]
    if bad:
        raise ValueError(f"VALIDATION_STATUS_UNKNOWN: {bad}")
    return {"schema": "lane_manifest/1", "study_id": study_id, "lane": lane, "dataset_id": dataset_id,
            "dataset_digest": dataset_digest, "capability_versions": dict(capability_versions),
            "study_contract_sha256": study_contract_sha256, "plan_sha256": plan_sha256, "schema_version": schema_version,
            "timestamp_convention": timestamp_convention, "timezone": timezone, "period": list(period),
            "outputs": [{"path": Path(p).as_posix(), "sha256": _sha(Path(p))} for p in outputs],
            "validation": dict(validation), "verdict": verdict}


def write_lane_manifest(path: Path, manifest: Mapping[str, Any]) -> Path:
    Path(path).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return Path(path)


__all__ = ["LANES", "FAST_OBSERVATION", "RESEARCH_VALIDATION", "EXECUTION_VALIDATION", "PLATFORM_CHANGE", "HISTORICAL",
           "EXPENSIVE_GATES", "route", "required_gates", "validate_execution_claim", "facts_from_study", "lane_manifest",
           "write_lane_manifest"]
