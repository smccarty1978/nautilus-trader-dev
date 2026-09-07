"""Static producer declarations shared by the compiler and lifecycle writer."""
# Single source of truth for the deliverable each stage writes -- research_workflow.audit_packets_v2
# builds DELIVERABLES_BY_STAGE from this constant so the audit packet cannot silently name a
# different filename than the one the lifecycle actually writes (red-team packet F1). Values are
# paths relative to the study directory; a "<year>" placeholder marks a per-partition path.
DELIVERABLES = {
    "compile": ["compiled_plan.json"],
    "prepare": ["audit/frozen_execution_manifest.json", "artifacts/experiment_authorization.json"],
    "readiness": ["audit/readiness.json"],
    "preflight": ["audit/preflight.json"],
    "tests": ["_work/controller/test_summary.json"],
    "causal_audit": ["audit/status.json"],
    "contract_audit": ["audit/contract_status.json"],
    "seal": ["artifacts/preexec_audit_seal.json"],
    "smoke": ["artifacts/smoke_acceptance.json"],
    "collection": ["_work/controller/partitions/train/<year>/{candidates,observations}.parquet"],
    "reconcile": ["_work/controller/reconcile.json"],
    "merge": ["_work/controller/merged/{candidates,observations}.parquet", "_work/controller/merged/identity.json"],
    "fit": ["artifacts/experiment_models.json"],
    "freeze": ["artifacts/train_experiment_freeze.json"],
    "oos": ["_work/controller/partitions/oos/<year>/{candidates,observations}.parquet"],
    "analyze": ["artifacts/experiment_analysis_v2.json"],
    "close": ["artifacts/study_closure.json"],
}
# fit additionally writes artifacts/tuning_trials.json (+ tuning_optuna.db for the optuna sampler)
# when the plan declares a model.search_space; not a fixed filename, so callers that need it
# should check plan["model"].get("search_space") and add it themselves (see audit_packets_v2).
FIT_TUNING_DELIVERABLES = ["artifacts/tuning_trials.json"]
