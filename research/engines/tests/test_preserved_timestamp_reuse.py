"""Fail-closed tests for sealed timestamp evidence reuse in modeling-only recompiles."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research.engines.timestamp_engine import (
    PreservedTimestampEvidenceReuseError,
    preserved_timestamp_contract_for_modeling_recompile,
)
from research.schemas.study_spec import StudySpec
from research_workflow.study_factory import materialize_compiled_study
from research_workflow.compiler import compile_study


def _spec(*, dataset="NQ_v0_2020_2026", symbol="NQ"):
    return StudySpec.model_validate({
        "study": {"id": "sealed_phase_d", "type": "bespoke", "description": "sealed fixture"},
        "operation": {"kind": "train_evaluate"}, "instrument": {"symbol": symbol, "venue": "XCME"},
        "population": {"type": "regime_state", "session": "RTH"}, "target": {"type": "flip"}, "features": {},
        "model": {"mode": "training", "family": "lightgbm", "arms": ["BASELINE"]},
        "chronology": {"train": [2021, 2022, 2023], "dev": [2024], "prohibited": [2025, 2026]},
        "execution": {"runtime": "nautilustrader", "data_requirements": {"dataset_id": dataset}},
        "bespoke": {"reason": "sealed timestamp reuse fixture", "unsupported_contract_element": "fixture"},
    })


def _write_sealed(study: Path, old: StudySpec, *, corrupt=None):
    (study / "audit").mkdir(parents=True)
    (study / "artifacts").mkdir()
    (study / "config").mkdir()
    compiled = {"spec": old.model_dump(mode="json"), "spec_sha256": old.compute_sha256()}
    raw = json.dumps(compiled).encode()
    (study / "compiled_study.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    composite = "a" * 64
    frozen = {"compiled_study_sha256": digest, "frozen_execution_composite_sha256": composite}
    seal = {"composite_seal_hash": composite, "file_hashes": {"study:compiled_study.json": digest}}
    timestamp = {"instrument_symbol": "NQ", "measured_catalog_rel_path": "data/catalog/NQ_v0_2020_2026",
                 "raw_timestamp_semantic": "OPEN_STAMPED", "raw_index_field": "ts_event",
                 "causal_rule": "FULL_BAR_OHLCV_AVAILABLE_ONLY_AT_INTERVAL_CLOSE", "nautilus_catalog": {
                     "ts_event_semantic": "OPEN_STAMPED", "ts_init_semantic": "CLOSE_STAMPED",
                     "causal_dispatch_field": "ts_init", "empirical_measurement": {"status": "MEASURED", "measurements": {
                         "NQ.XCME-1-SECOND-LAST-EXTERNAL": {"pass": True}}}}}
    if corrupt == "seal": seal["composite_seal_hash"] = "b" * 64
    if corrupt == "hash": frozen["compiled_study_sha256"] = "c" * 64
    if corrupt == "measurement": timestamp["nautilus_catalog"]["empirical_measurement"]["measurements"]["NQ.XCME-1-SECOND-LAST-EXTERNAL"]["pass"] = False
    (study / "audit" / "frozen_execution_manifest.json").write_text(json.dumps(frozen))
    (study / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(seal))
    (study / "config" / "timestamp_contract.json").write_text(json.dumps(timestamp))


def _modeling_only(old: StudySpec) -> StudySpec:
    raw = old.model_dump(mode="json")
    raw["model"] = {"mode": "training", "family": "lightgbm", "arms": ["LONG_SL0_5"]}
    raw["execution"]["modeling_driver_relpaths"] = ["implementation/phase_d.py"]
    raw["bespoke"]["custom_scope"] = ["implementation/phase_d.py"]
    return StudySpec.model_validate(raw)


def _phase_d_transition(old: StudySpec) -> StudySpec:
    raw = _modeling_only(old).model_dump(mode="json")
    raw["operation"]["kind"] = "phase_d_modeling"
    return StudySpec.model_validate(raw)


def test_sealed_modeling_only_reuse_marks_evidence_preserved(tmp_path):
    old = _spec(); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old)
    reused = preserved_timestamp_contract_for_modeling_recompile(study, _modeling_only(old))
    assert reused["evidence_provenance"]["mode"] == "PRESERVED_SEALED_MODELING_ONLY_REUSE"
    assert reused["evidence_provenance"]["newly_measured"] is False


def test_sealed_phase_d_operation_transition_is_the_only_permitted_operation_change(tmp_path):
    old = _spec(); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old)
    assert preserved_timestamp_contract_for_modeling_recompile(study, _phase_d_transition(old))["evidence_provenance"]


def test_reuse_rejects_arbitrary_operation_kind(tmp_path):
    old = _spec(); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old)
    raw = _phase_d_transition(old).model_dump(mode="json"); raw["operation"]["kind"] = "execution_economics"
    with pytest.raises(PreservedTimestampEvidenceReuseError, match="OPERATION_CHANGED"):
        preserved_timestamp_contract_for_modeling_recompile(study, StudySpec.model_validate(raw))


def test_reuse_rejects_reverse_phase_d_transition(tmp_path):
    old = _phase_d_transition(_spec()); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old)
    raw = _modeling_only(old).model_dump(mode="json"); raw["operation"]["kind"] = "train_evaluate"
    with pytest.raises(PreservedTimestampEvidenceReuseError, match="OPERATION_CHANGED"):
        preserved_timestamp_contract_for_modeling_recompile(study, StudySpec.model_validate(raw))


def test_reuse_rejects_phase_d_transition_with_target_metric_change(tmp_path):
    old = _spec(); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old)
    raw = _phase_d_transition(old).model_dump(mode="json"); raw["operation"]["target_metric"] = "roc_auc"
    with pytest.raises(PreservedTimestampEvidenceReuseError, match="OPERATION_CHANGED"):
        preserved_timestamp_contract_for_modeling_recompile(study, StudySpec.model_validate(raw))


@pytest.mark.parametrize("corrupt, code", [("seal", "SEAL_COMPOSITE"), ("hash", "FROZEN_COMPILED"), ("measurement", "MEASUREMENT_INVALID")])
def test_reuse_rejects_invalid_preserved_evidence(tmp_path, corrupt, code):
    old = _spec(); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old, corrupt=corrupt)
    with pytest.raises(PreservedTimestampEvidenceReuseError, match=code):
        preserved_timestamp_contract_for_modeling_recompile(study, _modeling_only(old))


@pytest.mark.parametrize("kind", ("dataset", "instrument", "nonmodel"))
def test_reuse_rejects_collection_or_runtime_change(tmp_path, kind):
    old = _spec(); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old)
    raw = _modeling_only(old).model_dump(mode="json")
    if kind == "dataset": raw["execution"]["data_requirements"] = {"dataset_id": "OTHER"}
    elif kind == "instrument": raw["instrument"]["symbol"] = "ES"
    else: raw["population"]["session"] = "ETH"
    with pytest.raises(PreservedTimestampEvidenceReuseError):
        preserved_timestamp_contract_for_modeling_recompile(study, StudySpec.model_validate(raw))


def test_reuse_rejects_new_study(tmp_path):
    with pytest.raises(PreservedTimestampEvidenceReuseError, match="EVIDENCE_MISSING"):
        preserved_timestamp_contract_for_modeling_recompile(tmp_path / "new", _modeling_only(_spec()))


def test_factory_uses_authenticated_reuse_only_after_live_measurement_refuses(tmp_path):
    old = _spec(); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old)
    result = materialize_compiled_study(_modeling_only(old), study)
    assert result["spec_sha256"]
    timestamp = json.loads((study / "config" / "timestamp_contract.json").read_text())
    assert timestamp["evidence_provenance"]["newly_measured"] is False


def test_lifecycle_compiler_path_uses_the_same_authenticated_reuse(tmp_path):
    old = _spec(); study = tmp_path / "sealed_phase_d"; _write_sealed(study, old)
    new = _modeling_only(old)
    import yaml
    (study / "study.yaml").write_text(yaml.safe_dump(new.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    assert compile_study(study) == 0
    compiled = json.loads((study / "compiled_study.json").read_text())
    assert compiled["contracts"]["timestamp_contract"]["evidence_provenance"]["mode"] == "PRESERVED_SEALED_MODELING_ONLY_REUSE"
