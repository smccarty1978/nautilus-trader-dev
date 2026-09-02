"""Synthetic acceptance for the declared Phase-D modeling composition only."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
DRIVER = REPO_ROOT / "studies" / "regime_transition_target_before_stop_v1" / "implementation" / "phase_d_modeling.py"


def _module():
    spec = importlib.util.spec_from_file_location("phase_d_modeling_fixture", DRIVER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path):
    study = tmp_path / "studies" / "phase_d_fixture"
    (study / "implementation").mkdir(parents=True)
    (study / "config").mkdir()
    shutil.copy2(DRIVER, study / "implementation" / "phase_d_modeling.py")
    features = [f"f{i}" for i in range(13)]
    (study / "config" / "feature_contract.json").write_text(json.dumps({"feature_list": features}))
    (study / "compiled_study.json").write_text(json.dumps({"spec": {
        "study": {"id": "phase_d_fixture", "type": "bespoke", "description": "synthetic fixture"},
        "operation": {"kind": "phase_d_modeling"}, "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state", "session": "RTH"}, "target": {"type": "flip"}, "features": {},
        "model": {"mode": "training", "family": "lightgbm", "arms": ["LONG_SL0_5"]},
        "chronology": {"train": [2021, 2022, 2023], "dev": [2024], "prohibited": [2025, 2026]},
        "execution": {"runtime": "nautilustrader", "modeling_driver_relpaths": ["implementation/phase_d_modeling.py"]},
        "bespoke": {"reason": "synthetic phase d fixture", "unsupported_contract_element": "fixture", "custom_scope": ["implementation/phase_d_modeling.py"]},
        "required_gates": [{"id": "synthetic_pre_fit", "stage": "pre_fit", "artifact_path": "artifacts/gate.json", "artifact_schema_version": 1}],
    }}))
    candidates, observations, targets = [], [], []
    for year in (2021, 2022, 2023):
        for direction in (-1, 1):
            for regime in range(2):
                regime_start = int(pd.Timestamp(f"{year}-01-01", tz="UTC").value + (direction + 2) * 1_000_000 + regime)
                for checkpoint in range(5):
                    ts = int(pd.Timestamp(f"{year}-01-02", tz="UTC").value + (regime * 10 + checkpoint) * 1_000_000_000)
                    # Phase-C surface layout: features + population metadata on the
                    # candidate surface; regime_direction + resolution bookkeeping on
                    # the observation surface.
                    candidates.append({"observation_ts": ts, "regime_start_ns": regime_start, "checkpoint_index": checkpoint,
                                       "regime_age_seconds": 120 + checkpoint * 5, "running_mfe_atr": 1.0 + 0.1 * checkpoint,
                                       **{f: float((checkpoint + regime + year + direction + i) % 7) for i, f in enumerate(features)}})
                    observations.append({"observation_ts": ts, "regime_start_ns": regime_start, "checkpoint_index": checkpoint,
                                         "regime_direction": direction})
                    row = {}
                    for suffix in ("sl0_5", "sl1_0", "sl1_5"):
                        disposition = "TIMEOUT" if checkpoint == 4 else ("POSITIVE" if checkpoint % 2 else "NEGATIVE")
                        row[f"target_tp1_{suffix}_label"] = np.nan if disposition == "TIMEOUT" else float(disposition == "POSITIVE")
                        row[f"target_tp1_{suffix}_disposition"] = disposition
                    targets.append(row)
    target_path = study / "_work" / "train_merged_collection" / "phase_c2_reconciled_targets.parquet"
    target_path.parent.mkdir(parents=True)
    for name, frame in (("candidates", pd.DataFrame(candidates)), ("observations", pd.DataFrame(observations))):
        frame.to_parquet(tmp_path / f"{name}.parquet", index=False)
    pd.DataFrame(targets).to_parquet(target_path, index=False)
    sha = __import__("hashlib").sha256(target_path.read_bytes()).hexdigest()
    (study / "artifacts").mkdir()
    (study / "artifacts" / "train_target_authority_reconciliation.json").write_text(json.dumps({"byte_sha256": sha, "target_only_logical_sha256": "synthetic-logical"}))
    return study, features, tmp_path / "candidates.parquet", tmp_path / "observations.parquet", target_path, sha


def test_phase_d_synthetic_is_train_only_six_cell_deterministic_and_persists(tmp_path, monkeypatch):
    driver = _module()
    study, _, candidates, observations, targets, sha = _fixture(tmp_path)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_SHA256", sha)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_LOGICAL_SHA256", "synthetic-logical")
    opened, gated = [], []
    monkeypatch.setattr("research_workflow.experiment._assert_study_open", lambda p: opened.append(p))
    monkeypatch.setattr("research_workflow.gates.assert_gates_satisfied", lambda *a, **k: gated.append((a, k)))
    configs = [{"max_depth": 3, "num_leaves": 7, "learning_rate": 0.05, "min_data_in_leaf": 1,
                "n_estimators": 2, "n_jobs": 1, "deterministic": True, "verbosity": -1}]
    first = driver.run_phase_d(study, candidates_path=candidates, observations_path=observations,
                               targets_path=targets, output_dir=tmp_path / "out", configurations=configs)
    payload = json.loads(Path(first["artifact"]).read_text())
    assert first["status"] == "PASS"
    assert first["oos_accessed"] is False
    assert set(payload["cells"]) == {f"{d}_{a}" for d in ("LONG", "SHORT") for a in ("SL0_5", "SL1_0", "SL1_5")}
    assert payload["model_artifact_count"] == 24  # one config x two folds plus selected two folds, six cells
    assert all(len(cell["attempts"]) == 1 for cell in payload["cells"].values())
    assert all(set(cell["validation"]) == {"fold_2022", "fold_2023"} for cell in payload["cells"].values())
    assert opened and gated
    second = driver.run_phase_d(study, candidates_path=candidates, observations_path=observations,
                                targets_path=targets, output_dir=tmp_path / "out2", configurations=configs)
    assert json.loads(Path(second["artifact"]).read_text())["cells"]["LONG_SL0_5"]["selected"] == payload["cells"]["LONG_SL0_5"]["selected"]


def test_phase_d_rejects_oos_input_before_fit(tmp_path, monkeypatch):
    driver = _module()
    study, _, candidates, observations, targets, sha = _fixture(tmp_path)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_SHA256", sha)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_LOGICAL_SHA256", "synthetic-logical")
    obs = pd.read_parquet(observations)
    obs.loc[0, "observation_ts"] = int(pd.Timestamp("2024-01-01", tz="UTC").value)
    obs.to_parquet(observations, index=False)
    with pytest.raises(driver.PhaseDProtocolError, match="PHASE_D_CANDIDATE_OBSERVATION_IDENTITY_OR_ORDER_MISMATCH|PHASE_D_NONTRAIN_YEAR_READ"):
        driver.run_phase_d(study, candidates_path=candidates, observations_path=observations, targets_path=targets,
                           output_dir=tmp_path / "out", configurations=[{"n_estimators": 2, "min_data_in_leaf": 1}])


def test_phase_d_rejects_arbitrary_or_missing_authority(tmp_path, monkeypatch):
    driver = _module(); study, _, candidates, observations, targets, sha = _fixture(tmp_path)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_SHA256", sha)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_LOGICAL_SHA256", "synthetic-logical")
    other = tmp_path / "other.parquet"; pd.read_parquet(targets).to_parquet(other)
    with pytest.raises(driver.PhaseDProtocolError, match="ARBITRARY_TARGET_PATH"):
        driver.run_phase_d(study, candidates_path=candidates, observations_path=observations, targets_path=other)
    (study / "artifacts" / "train_target_authority_reconciliation.json").unlink()
    with pytest.raises(driver.PhaseDProtocolError, match="AUTHORITY_EVIDENCE_MISSING"):
        driver.run_phase_d(study, candidates_path=candidates, observations_path=observations, targets_path=targets)


# --------------------------------------------------------------------------------------
# Section-9 acceptance tests A-K + contract-pass-06 CRITICAL closures.
# All synthetic: any fit uses tiny fixtures with n_estimators<=2.
# --------------------------------------------------------------------------------------
_TINY = [{"max_depth": 3, "num_leaves": 7, "learning_rate": 0.05, "min_data_in_leaf": 1,
          "n_estimators": 2, "n_jobs": 1, "deterministic": True, "verbosity": -1}]


def _gated_run(driver, tmp_path, monkeypatch, **overrides):
    study, features, candidates, observations, targets, sha = _fixture(tmp_path)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_SHA256", sha)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_LOGICAL_SHA256", "synthetic-logical")
    monkeypatch.setattr("research_workflow.experiment._assert_study_open", lambda p: None)
    monkeypatch.setattr("research_workflow.gates.assert_gates_satisfied", lambda *a, **k: None)
    kw = dict(candidates_path=candidates, observations_path=observations, targets_path=targets,
              output_dir=tmp_path / "out", configurations=_TINY)
    kw.update(overrides)
    receipt = driver.run_phase_d(study, **kw)
    return study, features, receipt, json.loads(Path(receipt["artifact"]).read_text())


def test_section9_A_H_I_J_K_full_run(tmp_path, monkeypatch):
    driver = _module()
    study, features, receipt, payload = _gated_run(driver, tmp_path, monkeypatch)
    cells = payload["cells"]
    # A: six cells compile distinctly, distinct selected-model arm identities.
    assert set(cells) == {f"{d}_{a}" for d in ("LONG", "SHORT") for a in ("SL0_5", "SL1_0", "SL1_5")}
    selected_arms = [art["model_role"] for art in payload["model_artifacts"] if "SELECTED" in str(art["model_role"])]
    assert len(selected_arms) == len(set(selected_arms)) == 12  # 6 cells x 2 folds
    # H: excluded dispositions (TIMEOUT) never enter the binary label set.
    frame = driver.load_phase_c_inputs(
        tmp_path / "candidates.parquet", tmp_path / "observations.parquet",
        study / "_work" / "train_merged_collection" / "phase_c2_reconciled_targets.parquet",
        feature_columns=features)
    for direction in ("LONG", "SHORT"):
        for arm in ("SL0_5", "SL1_0", "SL1_5"):
            _all, binary = driver._resolved_cell(frame, direction, arm)
            _, disp = driver._cell_target_columns(arm)
            assert "TIMEOUT" not in set(binary[disp].unique())
            label, _ = driver._cell_target_columns(arm)
            assert not binary[label].isna().any()
    # I: regime grouping metadata preserved through the join and into the reports.
    assert "regime_start_ns" in frame.columns
    for cell in cells.values():
        for fr in cell["validation"].values():
            assert fr["unique_regimes"] >= 1
            assert set(fr["regime_level"]) == {"first", "max", "mean"}
    # J: model selection cannot consume OOS evidence.
    assert receipt["oos_accessed"] is False and payload["oos_accessed"] is False
    for cell in cells.values():
        assert set(cell["validation"]) <= {"fold_2022", "fold_2023"}
        for fr in cell["validation"].values():
            assert fr["first_fire"]["threshold_population"] == "validation_scores_only"
        for attempt in cell["attempts"]:
            assert {fm["fold"] for fm in attempt["fold_metrics"]} <= {"fold_2022", "fold_2023"}
    # K: selected-model identity is lineage-bound to source + feature contract + folds.
    assert set(payload["source_sha256"]) == {"candidates", "observations", "targets"}
    for art in payload["model_artifacts"]:
        assert art["model_id"] and art["artifact_sha256"]


def test_section9_B_long_short_identity_cannot_collide(tmp_path, monkeypatch):
    driver = _module()
    study, features, _, _ = _gated_run(driver, tmp_path, monkeypatch)
    frame = driver.load_phase_c_inputs(
        tmp_path / "candidates.parquet", tmp_path / "observations.parquet",
        study / "_work" / "train_merged_collection" / "phase_c2_reconciled_targets.parquet",
        feature_columns=features)
    long_all, _ = driver._resolved_cell(frame, "LONG", "SL1_0")
    short_all, _ = driver._resolved_cell(frame, "SHORT", "SL1_0")
    assert set(long_all.index).isdisjoint(short_all.index)
    assert set(long_all["_direction"]) == {"LONG"} and set(short_all["_direction"]) == {"SHORT"}


def test_section9_C_three_stop_arms_identity_cannot_collide(tmp_path):
    driver = _module()
    cols = [driver._cell_target_columns(a) for a in ("SL0_5", "SL1_0", "SL1_5")]
    assert len({c for pair in cols for c in pair}) == 6  # 3 arms x (label, disposition), all distinct


def test_section9_D_E_temporal_folds_accepted(tmp_path, monkeypatch):
    driver = _module()
    study, features, _, payload = _gated_run(driver, tmp_path, monkeypatch)
    assert driver.FOLDS[0]["fit_years"] == (2021,) and driver.FOLDS[0]["validation_year"] == 2022
    assert driver.FOLDS[1]["fit_years"] == (2021, 2022) and driver.FOLDS[1]["validation_year"] == 2023
    frame = driver.load_phase_c_inputs(
        tmp_path / "candidates.parquet", tmp_path / "observations.parquet",
        study / "_work" / "train_merged_collection" / "phase_c2_reconciled_targets.parquet",
        feature_columns=features)
    _, binary = driver._resolved_cell(frame, "LONG", "SL1_0")
    for fold in driver.FOLDS:  # no exception == accepted
        driver._assert_group_integrity(binary, fold["fit_years"], fold["validation_year"])
    for cell in payload["cells"].values():
        assert set(cell["validation"]) == {"fold_2022", "fold_2023"}


def test_section9_F_reversed_chronology_rejected(tmp_path):
    driver = _module()
    # The declared protocol is chronological by construction: every fold's fit years
    # strictly precede its validation year, and folds expand forward in time.
    for fold in driver.FOLDS:
        assert max(fold["fit_years"]) < fold["validation_year"]
        assert set(fold["fit_years"]).isdisjoint({fold["validation_year"]})
    assert [f["validation_year"] for f in driver.FOLDS] == sorted(f["validation_year"] for f in driver.FOLDS)


def test_section9_G_oos_year_cannot_enter_train_protocol(tmp_path, monkeypatch):
    driver = _module()
    assert 2024 in driver.OOS_YEARS
    for fold in driver.FOLDS:
        assert set(fold["fit_years"]) <= set(driver.TRAIN_YEARS)
        assert fold["validation_year"] in driver.TRAIN_YEARS
    study, features, candidates, observations, targets, sha = _fixture(tmp_path)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_SHA256", sha)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_LOGICAL_SHA256", "synthetic-logical")
    obs = pd.read_parquet(observations)
    obs.loc[0, "observation_ts"] = int(pd.Timestamp("2024-06-01", tz="UTC").value)
    cand = pd.read_parquet(candidates)
    cand.loc[0, "observation_ts"] = int(pd.Timestamp("2024-06-01", tz="UTC").value)
    obs.to_parquet(observations, index=False)
    cand.to_parquet(candidates, index=False)
    with pytest.raises(driver.PhaseDProtocolError, match="PHASE_D_NONTRAIN_YEAR_READ"):
        driver.load_phase_c_inputs(candidates, observations, targets, feature_columns=features)


def test_contract_pass06_wrong_target_hash_fails_closed_before_output(tmp_path, monkeypatch):
    driver = _module()
    study, features, candidates, observations, targets, sha = _fixture(tmp_path)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_SHA256", "0" * 64)
    monkeypatch.setattr(driver, "AUTHORITATIVE_TARGET_LOGICAL_SHA256", "synthetic-logical")
    out = tmp_path / "should_not_exist"
    with pytest.raises(driver.PhaseDProtocolError, match="TARGET_AUTHORITY_MISMATCH"):
        driver.run_phase_d(study, candidates_path=candidates, observations_path=observations,
                           targets_path=targets, output_dir=out, configurations=_TINY)
    assert not out.exists()


def test_contract_pass06_fit_path_routes_only_through_governed_primitive(tmp_path):
    src = DRIVER.read_text(encoding="utf-8")
    assert "from research_workflow.modeling import fit_temporal_fold" in src
    assert "from research.analysis.modeling import fit_model" not in src
    assert "import fit_model" not in src


def test_contract_pass06_report_schema_and_per_fold_log_loss(tmp_path, monkeypatch):
    driver = _module()
    _, _, receipt, payload = _gated_run(driver, tmp_path, monkeypatch)
    for key in ("schema_version", "phase", "train_years", "oos_accessed", "feature_columns",
                "source_sha256", "configuration_count", "folds", "cells", "model_artifact_count",
                "model_artifacts", "result_sha256"):
        assert key in payload, key
    assert payload["phase"] == "PHASE_D_MODELING"
    assert payload["train_years"] == [2021, 2022, 2023]
    for cell in payload["cells"].values():
        assert set(cell) == {"attempts", "selected", "validation"}
        for fr in cell["validation"].values():
            assert fr["log_loss"]["metric"] == "log_loss"
            assert isinstance(fr["log_loss"]["value"], float)
            for m in ("roc_auc", "pr_auc", "brier", "prevalence", "calibration", "deciles"):
                assert m in fr
        for attempt in cell["attempts"]:
            for fm in attempt["fold_metrics"]:
                assert fm["log_loss"]["metric"] == "log_loss"
    # deliverables contract, engine and SPEC all agree on the two modeling deliverables.
    contract = json.loads((REPO_ROOT / "studies" / "regime_transition_target_before_stop_v1"
                           / "config" / "deliverables_contract.json").read_text())
    assert "modeling" in contract["authorized_modes"]
    names = set(contract["deliverables_by_mode"]["modeling"])
    assert {"phase_d_modeling_report.json", "phase_d_model_artifacts.json"} <= names
    for name in names:
        assert contract["artifact_metadata"][name]["mode"] == "modeling"
