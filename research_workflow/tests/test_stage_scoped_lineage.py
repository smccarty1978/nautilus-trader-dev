"""Regression contract for independent collection and modeling identities."""
import json
import pandas as pd
import pytest
from research_workflow.experiment import TrainFreezeRequired, assert_oos_open, authorize_experiment

def _study(tmp_path):
    s=tmp_path/"s"; s.mkdir(); (s/"study.yaml").write_text("study:\n  id: s\nchronology:\n  train: [2021]\n  dev: [2022]\n  prohibited: [2025, 2026]\n")
    (s/"artifacts").mkdir(); (s/"audit").mkdir(); authorize_experiment(s)
    return s

def _freeze(s, collection="collection", modeling="modeling"):
    auth=json.loads((s/"artifacts/experiment_authorization.json").read_text())
    (s/"artifacts/train_experiment_freeze.json").write_text(json.dumps({"partition":"train","authorization_sha256":auth["authorization_sha256"],"stage_scoped_lineage":{"COLLECTION_PRODUCER_CLOSURE":collection,"TARGET_RUNTIME_CLOSURE":"target","MODELING_EXECUTION_CLOSURE":modeling}}))

def test_train_freeze_binds_collection_target_and_modeling_lineage(tmp_path):
    s=_study(tmp_path); _freeze(s)
    assert set(json.loads((s/"artifacts/train_experiment_freeze.json").read_text())["stage_scoped_lineage"]) == {"COLLECTION_PRODUCER_CLOSURE","TARGET_RUNTIME_CLOSURE","MODELING_EXECUTION_CLOSURE"}

def test_collection_identity_change_stales_downstream_and_modeling_only_does_not_stale_collection(tmp_path, monkeypatch):
    s=_study(tmp_path); _freeze(s)
    import scripts.resolve_execution_manifest as rem
    import research_workflow.modeling_closure as mc
    import research_workflow.target_runtime as tr
    monkeypatch.setattr(tr,"resolve_target_runtime_closure",lambda *a, **k: {"target_runtime_closure_sha256":"target"})
    # Modeling-only change: collection identity unchanged, modeling composite drifts.
    monkeypatch.setattr(rem,"resolve_execution_manifest",lambda *a, **k: ("collection",{},{}))
    monkeypatch.setattr(mc,"resolve_modeling_closure",lambda *a, **k: {"modeling_execution_composite_sha256":"changed"})
    with pytest.raises(TrainFreezeRequired,match="MODELING_CLOSURE_STALE"): assert_oos_open(s)
    # Collection-producing code changed: staleness is caught before modeling.
    monkeypatch.setattr(rem,"resolve_execution_manifest",lambda *a, **k: ("changed_collection",{},{}))
    monkeypatch.setattr(mc,"resolve_modeling_closure",lambda *a, **k: {"modeling_execution_composite_sha256":"modeling"})
    with pytest.raises(TrainFreezeRequired,match="COLLECTION_CLOSURE_STALE"): assert_oos_open(s)
