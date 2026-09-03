"""Compact audit packets generated from a compiled plan (auditors never read the repo).

Two packets, each a few KB: the causal packet carries what a lookahead reviewer needs
(streams and their visibility, every tracker with its inputs/cadence/warmup, the
population cadence and predicates, the trigger graph, the outcome contract, the
availability table, the closure identity); the contract packet carries what a
compliance reviewer needs (chronology role table, model plan, output columns, binding
proof, deliverables per stage, seal identities).  Both name the exact summary block the
auditor must return.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

SUMMARY_TEMPLATE = {
    "verdict": "CLEAR | BLOCKED", "audit_type": "causal | contract", "study": "<study_id>", "auditor": "<distinct identity>",
    "audited_execution_composite_sha256": "<copy from packet.identity.execution_composite_sha256>",
    "critical": 0, "warning": 0, "note": 0,
}
SUMMARY_INSTRUCTIONS = ("Write audit/pass_NN.md (causal) or audit/contract_pass_NN.md (contract) and end it with exactly one block: "
                        "<!-- AUDIT_SUMMARY_V2_START --> {json} <!-- AUDIT_SUMMARY_V2_END -->; then run "
                        "`research audit ingest --study <dir> --type <causal|contract> --report <file> --author <you>`.")

DELIVERABLES_BY_STAGE = {
    "compile": ["compiled_plan.json"], "prepare": ["audit/frozen_execution_manifest.json", "artifacts/experiment_authorization.json"],
    "readiness": ["audit/readiness.json"], "preflight": ["audit/preflight.json"], "tests": ["_work/controller/test_summary.json"],
    "causal_audit": ["audit/status.json"], "contract_audit": ["audit/contract_status.json"], "seal": ["artifacts/preexec_audit_seal.json"],
    "smoke": ["artifacts/smoke_acceptance.json"], "collection": ["_work/controller/partitions/train/<year>/{candidates,observations}.parquet"],
    "reconcile": ["_work/controller/reconcile.json"], "merge": ["_work/controller/merged/{candidates,observations}.parquet", "_work/controller/merged/identity.json"],
    "fit": ["artifacts/experiment_models.json"], "freeze": ["artifacts/train_experiment_freeze.json"],
    "oos": ["_work/controller/partitions/oos/<year>/{candidates,observations}.parquet"], "analyze": ["artifacts/experiment_analysis.json"],
    "close": ["artifacts/study_closure.json"],
}


def _identity(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _predicate_text(node: Any) -> Any:
    return node.get("text") if isinstance(node, dict) else node


def causal_packet(plan: Mapping[str, Any], *, study_id: str, execution_composite: str, dirty_paths: List[str], test_summary: Mapping[str, Any]) -> Dict[str, Any]:
    trackers = [{"id": t["id"], "capability": t["capability"], "inputs": t.get("inputs"), "subscriptions": [s["from"] + ":" + ",".join(s["events"]) for s in t.get("subscriptions") or []],
                 "cadence": t.get("cadence"), "warmup_bars": t.get("warmup_bars"), "params": {k: v for k, v in (t.get("params") or {}).items() if k not in ("instances", "routing", "snapshot", "spec")}}
                for t in plan["trackers"]]
    trig = plan["triggers"]
    triggers = {"kind": trig.get("kind")}
    if trig.get("kind") == "graph":
        triggers.update({"reset_when": _predicate_text(trig.get("reset_when")),
                         "states": {n: {"enter_when": _predicate_text(s["enter_when"]), "expire_when": _predicate_text(s.get("expire_when")), "from": s.get("from"), "chain": s.get("chain")} for n, s in trig["states"].items()},
                         "entry": {"when": _predicate_text((trig.get("entry") or {}).get("when")), "reference": (trig.get("entry") or {}).get("reference"), "max_per_watch": (trig.get("entry") or {}).get("max_per_watch")},
                         "precedence": trig.get("precedence"), "sub_epochs": trig.get("sub_epochs"), "sub_epoch_sources": trig.get("sub_epoch_sources")})
    o = plan["outcome"]
    outcome = {k: o.get(k) for k in ("contract", "kernel", "direction", "relation", "atr", "atr_availability", "entry_reference", "session_end_censoring",
                                    "max_gap_ns", "same_bar_rule", "horizon_end_rule", "resolution_precedence", "primary_arm", "composition", "label_column")}
    outcome["arms"] = o.get("arms")
    outcome["flip"] = o.get("flip")
    features = plan.get("features") or {}
    packet = {
        "packet_version": 2, "audit_type": "causal", "study_id": study_id, "plan_sha256": plan.get("plan_sha256"),
        "identity": {"execution_composite_sha256": execution_composite, "closure_hash_algorithm": plan["closure"].get("hash_algorithm"), "closure_file_count": plan["closure"].get("file_count")},
        "streams": [{k: s.get(k) for k in ("key", "instrument", "timeframe", "role", "source", "derived_from", "aggregation", "visibility", "same_ts")} for s in plan["streams"]],
        "same_timestamp_rule": plan.get("availability", {}).get("same_timestamp_rule"),
        "session": plan.get("session"), "trackers": trackers,
        "population": {"cadence": plan["population"].get("cadence"), "qualify": _predicate_text(plan["population"].get("qualify")), "direction": plan["population"].get("direction"), "anchor_identity": plan["population"].get("anchor_identity")},
        "triggers": triggers, "outcome": outcome,
        "features": {"host": features.get("implementation"), "aliases": features.get("aliases"), "routing": features.get("routing"), "snapshot": features.get("snapshot"), "required_events": features.get("required_events")},
        "availability_table": plan.get("availability", {}).get("rows"), "warmup": plan.get("warmup"),
        "invariants": ["completed bars only (ts_init)", "context streams visible strictly before T", "derived buckets complete-only",
                       "outcome kernel resolves from bars strictly after T", "label contract has no fill semantics", "assert_oos_open is the only OOS door"],
        "worktree_dirty_paths": dirty_paths, "tests": {k: test_summary.get(k) for k in ("status", "counts", "execution_composite_sha256")},
        "required_summary_block": SUMMARY_TEMPLATE, "instructions": SUMMARY_INSTRUCTIONS,
    }
    packet["identity"]["packet_sha256"] = _identity({k: v for k, v in packet.items() if k != "identity"})
    return packet


def contract_packet(plan: Mapping[str, Any], *, study_id: str, execution_composite: str, dirty_paths: List[str], test_summary: Mapping[str, Any],
                    seal: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    model = plan.get("model") or {}
    packet = {
        "packet_version": 2, "audit_type": "contract", "study_id": study_id, "plan_sha256": plan.get("plan_sha256"), "spec_sha256": plan.get("spec_sha256"),
        "identity": {"execution_composite_sha256": execution_composite, "registry_sha256": plan.get("registry_sha256"), "seal": dict(seal or {})},
        "study": plan.get("study"), "instruments": {k: {kk: v.get(kk) for kk in ("dataset_id", "dataset_digest", "role")} for k, v in plan["instruments"].items()},
        "chronology": plan.get("chronology"),
        "model": {"family": model.get("family"), "params": model.get("params"), "arms": model.get("arms"), "validation": model.get("validation")} if model else None,
        "year_role_table": ((model.get("validation") or {}).get("year_role_table") if model else None),
        "columns": plan.get("columns"), "outcome": {k: plan["outcome"].get(k) for k in ("contract", "kernel", "label_column", "arms", "primary_arm")},
        "binding_proof": plan.get("binding_proof"), "deliverables_by_stage": DELIVERABLES_BY_STAGE,
        "invariants": ["every declared primitive maps to exactly one runtime implementation", "TRAIN/tuning/final-validation/OOS years disjoint",
                       "no study Python for a tier-2 study", "identity columns observation_ts/regime_start_ns/checkpoint_index on every row",
                       "outcome columns are labels, never features"],
        "worktree_dirty_paths": dirty_paths, "tests": {k: test_summary.get(k) for k in ("status", "counts", "execution_composite_sha256")},
        "required_summary_block": SUMMARY_TEMPLATE, "instructions": SUMMARY_INSTRUCTIONS,
    }
    packet["identity"]["packet_sha256"] = _identity({k: v for k, v in packet.items() if k != "identity"})
    return packet


__all__ = ["causal_packet", "contract_packet", "DELIVERABLES_BY_STAGE", "SUMMARY_TEMPLATE"]
