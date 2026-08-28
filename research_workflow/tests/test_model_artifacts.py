import json
import shutil
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from research_workflow.model_artifacts import persist_models, resolve_model, ModelArtifactError
from research.analysis.modeling import FittedModel, FitProvenance

def test_persisted_model_survives_closure_and_golden_scores(tmp_path):
    study=tmp_path/"studies"/"a"; study.mkdir(parents=True)
    est=LogisticRegression().fit([[0,0],[1,1]],[0,1])
    prov=FitProvenance("A","logistic_regression",["x","y"],2,2,0,{}, {},None,None,{},"x")
    m=FittedModel(est,prov); manifest={"arms":{"A":{**prov.to_dict(),"fit_identity_sha256":prov.fit_identity_sha256}}}
    record=persist_models(study,{"A":m},manifest)["records"][0]
    (study/"artifacts").mkdir(exist_ok=True); (study/"artifacts"/"study_closure.json").write_text(json.dumps({"status":"CLOSED"}))
    loaded=resolve_model(record["model_id"],registry_root=study.parent/"model_registry")
    assert loaded["artifact_status"] == "PRESERVED_AND_LOADABLE"

def test_registry_is_relocatable_after_studies_tree_move(tmp_path):
    original=tmp_path/"original"/"studies"; study=original/"s"; study.mkdir(parents=True)
    est=LogisticRegression().fit([[0,0],[1,1]],[0,1]); prov=FitProvenance("A","logistic_regression",["x","y"],2,2,0,{}, {},None,None,{},"x")
    rec=persist_models(study,{"A":FittedModel(est,prov)},{"arms":{"A":{**prov.to_dict(),"fit_identity_sha256":prov.fit_identity_sha256}}})["records"][0]
    moved_parent=tmp_path/"moved"; moved_parent.mkdir(); shutil.move(str(original), str(moved_parent/"studies"))
    loaded=resolve_model(rec["model_id"], registry_root=moved_parent/"studies"/"model_registry")
    assert loaded["model_id"] == rec["model_id"]

def test_multi_arm_requires_long_short_routing(tmp_path):
    study=tmp_path/"studies"/"s"; study.mkdir(parents=True); est=LogisticRegression().fit([[0,0],[1,1]],[0,1])
    def mk(arm):
        p=FitProvenance(arm,"logistic_regression",["x","y"],2,2,0,{}, {},None,None,{},"x")
        return FittedModel(est,p), {**p.to_dict(),"fit_identity_sha256":p.fit_identity_sha256}
    long,lr=mk("LONG_A"); short,sr=mk("SHORT_A")
    with pytest.raises(ModelArtifactError,match="ROUTING_REQUIRED"):
        persist_models(study,{"LONG_A":long,"SHORT_A":short},{"arms":{"LONG_A":lr,"SHORT_A":sr}})
    recs=persist_models(study,{"LONG_A":long,"SHORT_A":short},{"arms":{"LONG_A":lr,"SHORT_A":sr}},direction_routing={"LONG":"LONG_A","SHORT":"SHORT_A"})["records"]
    assert recs[0]["direction_routing"]["LONG"] == "LONG_A"

def test_non_identity_preprocessing_registry_record_fails_closed(tmp_path):
    study=tmp_path/"studies"/"s"; study.mkdir(parents=True); est=LogisticRegression().fit([[0,0],[1,1]],[0,1])
    p=FitProvenance("A","logistic_regression",["x","y"],2,2,0,{}, {},None,None,{},"x")
    rec=persist_models(study,{"A":FittedModel(est,p)},{"arms":{"A":{**p.to_dict(),"fit_identity_sha256":p.fit_identity_sha256}}})["records"][0]
    registry=study.parent/"model_registry"/f"{rec['model_id']}.json"; body=json.loads(registry.read_text()); body["preprocessing_identity"]={"kind":"standard_scaler"}; registry.write_text(json.dumps(body))
    with pytest.raises(ModelArtifactError,match="MODEL_PREPROCESSING_UNAVAILABLE"):
        resolve_model(rec["model_id"],registry_root=study.parent/"model_registry")
