import json
import shutil
from pathlib import Path
import yaml

from research_workflow.workflow_engine import WorkflowActions, WorkflowEngine
from research_workflow.study_spec_compiler import FieldResolution, compile_approved_request

def _request(study: Path):
    return {"study_spec": {"study": {"id": study.name, "type": "flip_prediction", "description": "x"},
        "instrument": {"symbol": "NQ", "venue": "XCME"}, "population": {"type": "regime_state", "session": "RTH"},
        "target": {"type": "flip", "event": "regime_flip", "direction": "bullish", "horizon_seconds": 60},
        "chronology": {"train": [2021], "dev": [2022], "prohibited": [2025, 2026]},
        "features": {"source": "canonical_verified_definition_universe", "instances": []}, "model": {}, "execution": {"runtime": "nautilustrader"}}}

def _actions():
    def put(name, payload):
        def f(s):
            p=s/name; p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(payload)); return payload
        return f
    def prepare(s):
        (s/"compiled_study.json").write_text(json.dumps({"spec": {}})); return {}
        
    def prepared(s):
        (s/"compiled_study.json").write_text(json.dumps({"spec": {}})); (s/"audit").mkdir(exist_ok=True)
        try:
            from scripts.resolve_execution_manifest import resolve_execution_manifest
            composite=resolve_execution_manifest(s)[0]
        except Exception: composite="fixture"
        (s/"audit/frozen_execution_manifest.json").write_text(json.dumps({"frozen_execution_composite_sha256":composite})); return {}
    def audit(name):
        def f(s):
            p=s/name; p.parent.mkdir(exist_ok=True); payload={"verdict":"CLEAR", "audited_execution_composite_sha256":json.loads((s/"audit/frozen_execution_manifest.json").read_text())["frozen_execution_composite_sha256"]}; p.write_text(json.dumps(payload)); return payload
        return f
    return WorkflowActions(reconcile=lambda s: {}, prepare=prepared,
        readiness=put("audit/readiness.json", {"overall_status":"PASS"}),
        preflight=put("audit/preflight.json", {"verdict":"CLEAR"}),
        causal=audit("audit/status.json"), contract=audit("audit/contract_status.json"),
        seal=put("artifacts/preexec_audit_seal.json", {"seal_status":"LOCKED"}))

def test_complete_request_materializes_and_reaches_authorization_gate(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    result=WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"
    assert (study/"study.yaml").is_file() and (study/"SPEC.md").is_file()
    assert (study/"workflow_state.json").is_file()

def test_default_actions_construct_without_name_error():
    actions = WorkflowActions()
    assert callable(actions.preflight) and callable(actions.prepare)

def test_failed_readiness_fails_closed(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    a=_actions(); a.readiness=lambda s: {"overall_status":"BLOCKED"}
    assert WorkflowEngine(study, actions=a).advance()["terminal_state"] == "SAFETY_OR_AUTHORIZATION_BLOCK"

def test_semantic_gap_is_not_construction_blocker(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text("research_question: unclear\n")
    result=WorkflowEngine(study, actions=_actions()).advance()
    assert result["terminal_state"] == "SEMANTIC_DECISION_REQUIRED"

def test_authority_conflict_is_explicit_terminal(tmp_path):
    study=tmp_path/"s"; study.mkdir(); request=_request(study); request["study_spec"]["study"]["id"]="other"
    (study/"research_decision.yaml").write_text(yaml.safe_dump(request))
    assert WorkflowEngine(study, actions=_actions()).advance()["terminal_state"] == "AUTHORITY_CONFLICT"

def test_compiler_exposes_exact_resolution_enum(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    result=compile_approved_request(study)
    assert result["ok"]
    assert FieldResolution.RESOLVED_EXPLICITLY.value in result["resolutions"].values()

def test_rerun_is_idempotent_at_terminal_gate(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    engine=WorkflowEngine(study, actions=_actions()); assert engine.advance()["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"
    assert WorkflowEngine(study, actions=_actions()).advance()["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"

def test_missing_implementation_writes_machine_handoff(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    (study/"artifacts").mkdir(); (study/"artifacts/capability_reconciliation.json").write_text(json.dumps({"state":"NEEDS_WORK"}))
    a=_actions(); a.reconcile=lambda s: {"state":"IMPLEMENTATION_REQUIRED", "error":"missing_x", "detail":"contract", "required_tests":["x"]}
    assert WorkflowEngine(study, actions=a).advance()["terminal_state"] == "IMPLEMENTATION_REQUIRED"
    assert (study/"artifacts/implementation_contract.json").is_file()

def test_train_and_oos_boundaries_are_not_crossed(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    assert WorkflowEngine(study, actions=_actions()).advance()["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"
    (study/"artifacts/train_experiment_freeze.json").write_text("{}")
    assert WorkflowEngine(study, actions=_actions()).advance()["terminal_state"] == "OOS_AUTHORIZATION_REQUIRED"

def test_intake_with_concepts_but_no_authored_surface_is_semantic_decision(tmp_path):
    """Capability authority is never the feature-selection authority (scaffolding rule F):
    families/concepts without an explicit feature_surface halt at SEMANTIC_DECISION_REQUIRED."""
    root=Path(__file__).resolve().parents[2]; source=root/"studies/deep_pullback_5s_reacceleration_model"
    req = yaml.safe_load((source/"research_decision.yaml").read_text())
    req.get("feature_policy", {}).pop("feature_surface", None)
    req.pop("feature_surface", None)
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(req))
    result=compile_approved_request(study, write=False)
    assert result["ok"] is False and result["terminal"] == "SEMANTIC_DECISION_REQUIRED"
    assert result["unresolved"]["reason"] == "FEATURE_SURFACE_NOT_AUTHORED"

def test_deep_pullback_materializes_from_its_authored_feature_surface(tmp_path):
    root=Path(__file__).resolve().parents[2]; source=root/"studies/deep_pullback_5s_reacceleration_model"; study=tmp_path/source.name; study.mkdir()
    (study/"research_decision.yaml").write_text((source/"research_decision.yaml").read_text())
    result=compile_approved_request(study, write=True)
    assert result["ok"]
    assert all((study/p).exists() for p in ("study.yaml","SPEC.md","TASK_PACKET.json","compiled_study.json","config/feature_contract.json"))
    compiled=json.loads((study/"compiled_study.json").read_text())
    assert compiled["spec"]["features"]["derived_inputs"][0]["parent_train_freeze_artifact_sha256"] == "c5bd68ca503a2395b7ca695354fae5a5968b44c95aef74290bb59d952e4f49a9"
    outcome=compiled["contracts"]["target_contract"]["required_forward_outcomes"][0]
    assert outcome["session_end_censoring"] is True and outcome["max_gap_seconds"] == 1
    assert outcome["atr_frozen_at"] == "decision_ts" and "wilder_atr_14" in outcome["atr_source"]
    # A2: composite target horizon surfaced onto target_contract, censoring consistent.
    tc=compiled["contracts"]["target_contract"]
    assert tc["horizon_seconds"] == 300 and tc["censoring_policy"]["max_horizon_seconds"] == 300
    # Full authored surface: 34 distinct canonical FeatureInstance columns + 1 derived input.
    fc=compiled["contracts"]["feature_contract"]
    assert fc["feature_count"] == 34 and len(set(fc["feature_list"])) == 34
    assert fc["feature_list"][:3] == ["arrival_velocity", "arrival_acceleration", "ema_slope"]
    assert "current_5m_regime_mfe_atr" in fc["feature_list"] and "pullback_current_depth_atr" in fc["feature_list"]
    assert "trend_normalized_est_delta_sum_5s" in fc["feature_list"] and "trend_normalized_est_delta_sum_300s" in fc["feature_list"]

def test_ordered_barrier_atr_provenance_rejects_non_decision_freeze():
    from research.schemas.study_spec import RequiredForwardOutcomeSpec
    import pytest
    with pytest.raises(ValueError, match="ORDERED_BARRIER_ATR_MUST_FREEZE_AT_DECISION"):
        RequiredForwardOutcomeSpec(id="x", horizon_seconds=10, atr_source="latest_causally_completed_1m_wilder_atr_14_available_at_T", atr_frozen_at="entry_ts", ordered_barriers=[{"id":"b","favorable_atr":1,"adverse_atr":1,"horizon_seconds":10}])

# The following are distinct regression assertions for the generic acceptance matrix.
def test_verified_capability_does_not_call_reconciliation(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    (study/"artifacts").mkdir(); (study/"artifacts/capability_reconciliation.json").write_text(json.dumps({"state":"READY_TO_SCAFFOLD"}))
    a=_actions(); calls=[]; a.reconcile=lambda s: calls.append(s) or {"state":"READY"}
    WorkflowEngine(study, actions=a).advance(); assert calls == []

def test_novel_reusable_capability_reconciles_then_continues(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    (study/"artifacts").mkdir(); (study/"artifacts/capability_reconciliation.json").write_text(json.dumps({"state":"PROMOTION_REQUIRED"}))
    a=_actions(); calls=[]; a.reconcile=lambda s: calls.append("reconcile") or {"state":"READY_TO_SCAFFOLD", "promoted":["new_feature"]}
    assert WorkflowEngine(study, actions=a).advance()["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"; assert calls == ["reconcile"]

def test_implementation_handoff_has_full_contract_shape(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study))); (study/"artifacts").mkdir()
    (study/"artifacts/capability_reconciliation.json").write_text(json.dumps({"state":"MISSING"}))
    a=_actions(); a.reconcile=lambda s: {"state":"IMPLEMENTATION_REQUIRED"}
    WorkflowEngine(study, actions=a).advance(); handoff=json.loads((study/"artifacts/implementation_contract.json").read_text())
    assert {"capability_identity","semantic_contract","provider_or_collector_class_expected","parameters","availability_reset_null_semantics","required_tests","affected_generic_interface","expected_resume_point"} <= set(handoff)

def test_authority_change_restarts_from_prepare(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    assert WorkflowEngine(study, actions=_actions()).advance()["terminal_state"] == "READY_FOR_TRAIN_AUTHORIZATION"
    state=json.loads((study/"workflow_state.json").read_text()); state["fingerprints"]["active_feature_authority"]="old"; (study/"workflow_state.json").write_text(json.dumps(state))
    a=_actions(); calls=[]; original=a.prepare; a.prepare=lambda s: calls.append("prepare") or original(s)
    WorkflowEngine(study, actions=a).advance(); assert calls == ["prepare"]

def test_study_spec_change_restarts_downstream_closure(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study)))
    WorkflowEngine(study, actions=_actions()).advance(); (study/"study.yaml").write_text((study/"study.yaml").read_text()+"\n# changed\n")
    a=_actions(); calls=[]; original=a.prepare; a.prepare=lambda s: calls.append("prepare") or original(s)
    WorkflowEngine(study, actions=a).advance(); assert calls == ["prepare"]

def test_completed_rerun_calls_no_leaf(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study))); WorkflowEngine(study, actions=_actions()).advance()
    a=_actions(); calls=[]
    for n in ("prepare","readiness","preflight","causal","contract","seal"):
        setattr(a,n,lambda s, n=n: calls.append(n) or {"status":"CLEAR"})
    WorkflowEngine(study, actions=a).advance(); assert calls == []

def test_existing_compiled_study_is_compatible(tmp_path):
    study=tmp_path/"s"; study.mkdir(); (study/"research_decision.yaml").write_text(yaml.safe_dump(_request(study))); WorkflowEngine(study, actions=_actions()).advance()
    a=_actions(); calls=[]; a.prepare=lambda s: calls.append("prepare")
    WorkflowEngine(study, actions=a).advance(); assert calls == []
