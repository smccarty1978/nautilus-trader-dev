"""Bounded acceptance: a closed source model is reusable by immutable id."""
import json
import pandas as pd
import pytest
import yaml
from research.analysis.spec import AnalysisSpec, ModelArm
from research_workflow.modeling import fit_models, freeze_train_artifacts
from research_workflow.model_artifacts import score_preserved_model, validate_golden_prediction
from research_workflow.target_runtime import validate_target_parity
from research_workflow.workflow_engine import WorkflowEngine
from research.schemas.study_spec import DerivedCausalInputSpec
from research_workflow.external_model_scoring import FrozenExternalModelScorer
from research.schemas.study_spec import StudySpec
from research_workflow.compiler import compile_study
from research_workflow.runtime_bindings import verify_runtime_contract

def test_synthetic_closed_model_reuse_without_runtime_code_change(tmp_path):
    root=tmp_path/"studies"; source=root/"source"; child=root/"child"; source.mkdir(parents=True); child.mkdir()
    authored={"study":{"id":"source","type":"bespoke","description":"synthetic"},"operation":{"kind":"train_evaluate"},"bespoke":{"reason":"Synthetic target-runtime acceptance fixture","unsupported_contract_element":"ordered barrier fixture","canonical_type_considered":"flip_prediction","reusable_extension_considered":"target runtime"},"instrument":{"symbol":"NQ"},"population":{"prevailing_regime":"bearish"},"target":{"type":"classification","direction":"bullish","conditions":[{"id":"primary","kind":"ordered_barrier","forward_outcome_id":"path","barrier_id":"b"}],"required_forward_outcomes":[{"id":"path","entry_reference":"next_bar_open","horizon_seconds":10,"max_tracking_seconds":10,"max_gap_seconds":1,"atr_source":"latest_causally_completed_1m_wilder_atr_14_available_at_T","atr_frozen_at":"decision_ts","ordered_barriers":[{"id":"b","favorable_atr":1.,"adverse_atr":1.,"horizon_seconds":10}]}]},"chronology":{"train":[2021],"dev":[2022],"prohibited":[2025,2026]},"features":{},"model":{},"execution":{"runtime":"nautilustrader"}}
    spec_authored=StudySpec.model_validate(authored)
    source.joinpath("study.yaml").write_text(yaml.safe_dump(spec_authored.model_dump(mode="json")))
    assert compile_study(source) == 0
    compiled=json.loads(source.joinpath("compiled_study.json").read_text())
    assert compiled["contracts"]["target_contract"]["primitive"] == "ordered_barrier"
    bindings=verify_runtime_contract(source)
    assert bindings["checked"]["target_runtime"]["target_runtime_closure_sha256"]
    assert bindings["checked"]["modeling_execution_closure_sha256"]
    source.joinpath("audit").mkdir(); source.joinpath("audit/frozen_execution_manifest.json").write_text(json.dumps({"frozen_execution_composite_sha256":"collection"}))
    X=pd.DataFrame({"x":[0.,0.,1.,1.,.2,.8],"z":[0.,1.,0.,1.,.4,.6]}); y=pd.Series([0,0,1,1,0,1]); meta=pd.DataFrame({"_partition":["train"]*len(X)})
    spec=AnalysisSpec(analysis_id="synthetic", run_id="bounded", study_id="source", model_arms=(ModelArm("A",["x","z"]),), seed=7)
    fitted=fit_models(source,X,y,meta=meta,spec=spec,estimator="lightgbm",hyperparameters={"n_estimators":4,"min_child_samples":1})
    rec=fitted["model_artifacts"]["records"][0]; assert validate_golden_prediction(rec)
    freeze_train_artifacts(source,feature_sets={"A":["x","z"]},models_manifest=fitted["manifest"],preprocessing_hash="prep",score_arrays={"A":[.1,.2]},meta=meta, model_artifact_records=fitted["model_artifacts"]["records"])
    parity=validate_target_parity({"primitive":"ordered_barrier"}, [{"candidate":{"observation_ts":0,"horizon_end_ts":1,"entry_price":100.,"atr":1.,"direction":1,"favorable_atr":1.,"adverse_atr":1.},"events":[{"ts":1,"high":101.,"low":100.}],"actual":{"disposition":"POSITIVE","label":1}}])
    assert parity["passed"]
    source.joinpath("artifacts").mkdir(exist_ok=True)
    decision_p = source.joinpath("artifacts/research_decision_stage17.json")
    decision_body = {"study_id": "source", "terminal_decision": "ship_it"}
    from research.analysis.identity import canonical_sha256
    decision_body["decision_identity_sha256"] = canonical_sha256(decision_body)
    decision_p.write_text(json.dumps(decision_body))
    import hashlib
    dec_sha = hashlib.sha256(decision_p.read_bytes()).hexdigest()
    closure_body = {
        "schema_version": 1, "study_id": "source", "status": "CLOSED",
        "outcome": "DIAGNOSTIC_POSITIVE", "terminal_decision": "ship_it",
        "model_ids": [rec["model_id"]],
        "bound_evidence": {
            "stage17_research_decision": {
                "path": "artifacts/research_decision_stage17.json",
                "sha256": dec_sha,
            }
        }
    }
    closure_body["closure_identity_sha256"] = canonical_sha256(closure_body)
    closure_p = source.joinpath("artifacts/study_closure.json")
    closure_p.write_text(json.dumps(closure_body))
    from research_workflow.model_artifacts import assign_scientific_status
    assign_scientific_status(
        model_id=rec["model_id"],
        registry_root=root / "model_registry",
        scientific_status="VALID_PRIMARY",
        closure_evidence_path=closure_p,
        decision_evidence_path=decision_p,
    )
    assert WorkflowEngine(source).advance()["terminal_state"] == "STUDY_CLOSED"
    child.joinpath("study.yaml").write_text("study:\n  id: child\nfeatures:\n  derived_inputs:\n    - name: parent_score\n      kind: frozen_external_model_score\n      model_id: %s\n" % rec["model_id"])
    declaration=yaml.safe_load(child.joinpath("study.yaml").read_text())["features"]["derived_inputs"][0]
    parsed=DerivedCausalInputSpec.model_validate(declaration)
    scorer=FrozenExternalModelScorer.bind(parsed, parent_dir=source)
    snapshot={k:float(X.iloc[0][k]) for k in rec["ordered_model_inputs"]}
    observed=scorer.score(snapshot, checkpoint_ts=10, direction="LONG", availability_ts={k:10 for k in snapshot}).score
    expected=score_preserved_model(rec["model_id"], X.iloc[:1], registry_root=root/"model_registry")[0]
    NEW_STUDY_REUSES_CLOSED_MODEL_WITHOUT_RUNTIME_CODE_CHANGE = observed == expected
    assert NEW_STUDY_REUSES_CLOSED_MODEL_WITHOUT_RUNTIME_CODE_CHANGE is True
