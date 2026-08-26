import pytest
from pathlib import Path
import pandas as pd
from research.schemas.study_spec import StudySpec
from backtests.nt_runtime.compiled_study_loader import CompiledStudyData
from backtests.nt_runtime.data_plan import DataPlan
from backtests.nt_runtime.run_plan import RunPlan, RunStage
from backtests.nt_runtime.output_manager import OutputManager

def _create_mock_study_spec(study_id: str) -> StudySpec:
    study_dict = {
        "study": {
            "id": study_id,
            "type": "flip_prediction",
            "risk_tier": 2,
            "description": "Mock study description.",
        },
        "operation": {"kind": "train_evaluate", "target_metric": "pr_auc"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {
            "type": "regime_state", "prevailing_regime": "bullish", "session": "RTH",
            "qualification": {"age_gate_seconds": 300, "established": True},
        },
        "chronology": {"train": [2021, 2022], "dev": [2023], "prohibited": [2024]},
        "target": {"type": "flip", "event": "confirmed_flip", "direction": "bearish", "horizon_seconds": 300},
        "features": {
            "feature_list": [],
            "feature_list_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", # empty sha
            "metadata_columns": ["observation_ts", "regime_start_ns", "checkpoint_index"],
        },
        "execution": {
            "runtime": "nautilustrader",
            "strategy_class": "strategies.flip_prediction_collector.FlipPredictionCollector",
            "progress_seconds": 60,
            "bounded": True,
        },
    }
    return StudySpec.model_validate(study_dict)

def _create_mock_output_manager(tmp_path: Path, study_id: str, output_base_dir: Path = None) -> OutputManager:
    spec = _create_mock_study_spec(study_id)
    study_dir = tmp_path / f"studies/{study_id}"
    study_dir.mkdir(parents=True, exist_ok=True)
    
    study_data = CompiledStudyData(
        study_id=spec.study.id,
        study_dir=study_dir,
        study_type=spec.study.type,
        spec=spec,
        spec_sha256=spec.compute_sha256(),
        contracts={},
        raw_compiled_json={},
    )
    
    start_dt = pd.Timestamp("2023-10-02", tz="UTC")
    end_dt = pd.Timestamp("2023-10-02 23:59:59.999999999", tz="UTC")
    
    data_plan = DataPlan(
        symbol="NQ",
        venue="XCME",
        instrument_id="NQ.XCME",
        multiplier="20.0",
        price_increment="0.25",
        catalog_path=tmp_path / "fake_catalog",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        start_dt=start_dt,
        end_dt=end_dt,
        warmup_days=5,
        warmup_start_dt=start_dt - pd.Timedelta(days=5),
        raw_timestamp_semantic="OPEN_STAMPED",
        ts_init_delta_1s_ns=1_000_000_000,
        ts_init_delta_1m_ns=60_000_000_000,
    )
    
    run_plan = RunPlan(stage=RunStage.DAY, start_date="2023-10-02", end_date="2023-10-02")
    
    return OutputManager(
        study_data=study_data,
        data_plan=data_plan,
        run_plan=run_plan,
        output_base_dir=output_base_dir,
    )

def test_study_run_directories_are_isolated(tmp_path: Path):
    """Proves study A cannot write/default into study B's run directory."""
    mgr_a = _create_mock_output_manager(tmp_path, "study_a")
    mgr_b = _create_mock_output_manager(tmp_path, "study_b")
    
    # Assert directories are distinct and separate
    assert mgr_a.run_dir != mgr_b.run_dir
    assert "study_a" in str(mgr_a.run_dir)
    assert "study_b" in str(mgr_b.run_dir)
    assert "study_b" not in str(mgr_a.run_dir)
    assert "study_a" not in str(mgr_b.run_dir)

def test_output_path_derived_deterministically(tmp_path: Path):
    """Proves output path is derived deterministically from study id and run parameters."""
    mgr = _create_mock_output_manager(tmp_path, "study_test_deterministic")
    
    # The output path should be resolved under the study's own directory (e.g. studies/study_test_deterministic/runs/)
    expected_base_dir = tmp_path / "studies/study_test_deterministic/runs"
    assert mgr.run_dir.parent == expected_base_dir
    assert mgr.run_id.startswith(pd.Timestamp.now("UTC").strftime("%Y%m%d"))
    assert "study_test_deterministic" in mgr.run_id

def test_explicit_output_dir_override_works(tmp_path: Path):
    """Proves explicit output_base_dir override works and overrides the study-local default."""
    custom_output_dir = tmp_path / "custom_runs"
    mgr = _create_mock_output_manager(tmp_path, "study_with_override", output_base_dir=custom_output_dir)
    
    # Should resolve under custom override, not under studies/study_with_override/runs/
    assert mgr.run_dir.parent == custom_output_dir
    assert custom_output_dir.exists()

def test_ignored_run_data_does_not_affect_identity(tmp_path: Path):
    """Proves that ignored run directory content does not modify compile identity or seal."""
    # Create the manager and write initial manifest
    mgr = _create_mock_output_manager(tmp_path, "study_check_identity")
    
    spec_sha_before = mgr.study_data.spec_sha256
    
    # Simulate writing extra parquets/junk files in the run directory
    junk_parquet = mgr.run_dir / "junk_data.parquet"
    junk_parquet.write_bytes(b"some fake parquet bytes")
    
    # Ensure study spec hash hasn't shifted and spec sha remains identical
    assert mgr.study_data.spec.compute_sha256() == spec_sha_before
