"""Unit and Integration Tests for NT Generic Runner MVP (Phase 1: collect mode).
================================================================================
Validates compiled study loader, data plan, engine builder, run plan, telemetry,
output manager, CLI runner, and golden equivalence against reference collector.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml

from backtests.nt_runtime.compiled_study_loader import (
    CompiledStudyData,
    InvalidCompiledStudyError,
    StaleCompiledStudyError,
    load_compiled_study,
)
from backtests.nt_runtime.data_plan import (
    DataPlan,
    UnauthorizedExecutionDomainError,
    resolve_data_plan,
)
from backtests.nt_runtime.engine_builder import build_engine, create_futures_instrument
from backtests.nt_runtime.modes.collect import run_collect_mode
from backtests.nt_runtime.output_manager import OutputManager
from backtests.nt_runtime.run_plan import RunPlan, RunStage, resolve_run_plan
from backtests.nt_runtime.strategy_binding import (
    StrategyBinding,
    UnregisteredStrategyBindingError,
    resolve_strategy_binding,
)
from backtests.nt_runtime.telemetry import CausalTelemetry
from research.schemas.study_spec import StudySpec
from scripts.find_first_parity_divergence import compare_ledgers


@pytest.fixture
def mock_study_dir():
    """Creates a temporary valid study directory with study.yaml and compiled_study.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        study_dir = Path(tmpdir) / "test_collect_study"
        study_dir.mkdir(parents=True)

        study_dict = {
            "study": {
                "id": "test_collect_study",
                "type": "flip_prediction",
                "risk_tier": 2,
                "description": "Test collect study for generic NT runner.",
            },
            "operation": {
                "kind": "train_evaluate",
                "target_metric": "pr_auc",
            },
            "instrument": {
                "symbol": "NQ",
                "venue": "XCME",
            },
            "population": {
                "type": "regime_state",
                "prevailing_regime": "bullish",
                "session": "RTH",
                "qualification": {
                    "age_gate_seconds": 300,
                    "established": True,
                },
            },
            "target": {
                "type": "flip",
                "event": "confirmed_flip",
                "direction": "bearish",
                "horizon_seconds": 300,
            },
            "features": {
                "source_key": "F3_top25_gbt_v1",
                "feature_list_sha256": "5e8b5cfd125b7b6dd030dba26126b57d51616014095e70cb8a357ebbf06e2cea",
                "feature_list": ["rth_vol_cum", "rth_elapsed_seconds", "pct_levels_behind_trade"],
                "metadata_columns": ["observation_ts", "close", "atr"],
            },
            "chronology": {
                "train": [2021, 2022, 2023, 2024],
                "dev": [2025],
                "prohibited": [2026],
            },
            "execution": {
                "runtime": "nautilustrader",
                "strategy_class": "strategies.flip_prediction_collector.FlipPredictionCollector",
                "progress_seconds": 60,
                "bounded": True,
            },
        }

        spec = StudySpec.model_validate(study_dict)
        spec_sha256 = spec.compute_sha256()

        # Write study.yaml
        with open(study_dir / "study.yaml", "w", encoding="utf-8") as f:
            yaml.dump(study_dict, f)

        # Write compiled_study.json
        compiled_dict = {
            "study_id": "test_collect_study",
            "study_type": "flip_prediction",
            "spec_sha256": spec_sha256,
            "fit_decision": "STUDY_TYPE_MATCH",
            "contracts": {
                "execution_contract": {
                    "runtime": "nautilustrader",
                    "strategy_class": "strategies.flip_prediction_collector.FlipPredictionCollector",
                }
            },
        }
        with open(study_dir / "compiled_study.json", "w", encoding="utf-8") as f:
            json.dump(compiled_dict, f, indent=2)

        yield study_dir


# =============================================================================
# 1. Compiled Study Loader Tests
# =============================================================================

def test_load_compiled_study_success(mock_study_dir):
    data = load_compiled_study(mock_study_dir)
    assert data.study_id == "test_collect_study"
    assert data.study_type == "flip_prediction"
    assert len(data.spec_sha256) == 64
    assert data.spec.instrument.symbol == "NQ"


def test_load_compiled_study_detects_stale_yaml(mock_study_dir):
    # Mutate study.yaml without recompiling compiled_study.json
    yaml_path = mock_study_dir / "study.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f)
    d["study"]["description"] = "Modified description causing hash drift."
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(d, f)

    with pytest.raises(StaleCompiledStudyError, match="STALE_COMPILED_STUDY"):
        load_compiled_study(mock_study_dir)


def test_load_compiled_study_missing_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(InvalidCompiledStudyError, match="Missing study.yaml"):
            load_compiled_study(Path(tmpdir))


# =============================================================================
# 2. Data Plan & Chronology Guard Tests
# =============================================================================

def test_resolve_data_plan_authorized_dates(mock_study_dir):
    study_data = load_compiled_study(mock_study_dir)
    data_plan = resolve_data_plan(study_data, start_date="2023-03-03", end_date="2023-03-03")
    assert data_plan.symbol == "NQ"
    assert data_plan.venue == "XCME"
    assert data_plan.raw_timestamp_semantic == "OPEN_STAMPED"
    assert data_plan.ts_init_delta_1s_ns == 1_000_000_000
    assert data_plan.ts_init_delta_1m_ns == 60_000_000_000


def test_resolve_data_plan_rejects_prohibited_years(mock_study_dir):
    study_data = load_compiled_study(mock_study_dir)
    with pytest.raises(UnauthorizedExecutionDomainError, match="UNAUTHORIZED_EXECUTION_DOMAIN"):
        # 2026 is prohibited in chronology
        resolve_data_plan(study_data, start_date="2026-01-05", end_date="2026-01-05")


def test_resolve_data_plan_rejects_unauthorized_years(mock_study_dir):
    study_data = load_compiled_study(mock_study_dir)
    with pytest.raises(UnauthorizedExecutionDomainError, match="UNAUTHORIZED_EXECUTION_DOMAIN"):
        # 2019 is not in authorized train/dev/diagnostic years
        resolve_data_plan(study_data, start_date="2019-03-05", end_date="2019-03-05")


# =============================================================================
# 3. Strategy Binding Tests
# =============================================================================

def test_resolve_strategy_binding_success():
    binding = resolve_strategy_binding("flip_prediction_collector", mode="collect")
    assert binding.binding_id == "flip_prediction_collector"
    assert binding.class_name == "FlipPredictionCollector"
    assert "collect" in binding.supported_modes


def test_resolve_strategy_binding_unsupported_mode():
    with pytest.raises(UnregisteredStrategyBindingError, match="does not support mode 'backtest'"):
        resolve_strategy_binding("flip_prediction_collector", mode="backtest")


def test_resolve_strategy_binding_unregistered():
    with pytest.raises(UnregisteredStrategyBindingError, match="UNREGISTERED_STRATEGY"):
        resolve_strategy_binding("non_existent_strategy")


# =============================================================================
# 4. Run Plan & Stage Resolution Tests
# =============================================================================

def test_resolve_run_plan_stages(mock_study_dir):
    study_data = load_compiled_study(mock_study_dir)
    
    # Day stage
    plan_day = resolve_run_plan(study_data, stage="day", reference_date="2025-03-03")
    assert plan_day.stage == RunStage.DAY
    assert plan_day.start_date == "2025-03-03"
    assert plan_day.end_date == "2025-03-03"
    assert plan_day.auto_expand is False

    # Week stage
    plan_week = resolve_run_plan(study_data, stage="week", reference_date="2025-03-03")
    assert plan_week.stage == RunStage.WEEK
    assert plan_week.start_date == "2025-03-03"
    assert plan_week.end_date == "2025-03-07"
    assert plan_week.auto_expand is False


# =============================================================================
# 5. Output Manager & Telemetry Tests
# =============================================================================

def test_output_manager_persists_artifacts(mock_study_dir):
    with tempfile.TemporaryDirectory() as tmp_out:
        study_data = load_compiled_study(mock_study_dir)
        run_plan = resolve_run_plan(study_data, stage="day", reference_date="2023-03-03")
        data_plan = resolve_data_plan(study_data, start_date="2023-03-03", end_date="2023-03-03")

        mgr = OutputManager(study_data, data_plan, run_plan, output_base_dir=Path(tmp_out))
        assert (mgr.run_dir / "run_manifest.json").exists()

        # Create dummy dataframes
        cands_df = pd.DataFrame([
            {
                "observation_ts": 1740993000000000000,
                "close": 21000.0,
                "atr": 10.0,
                "rth_vol_cum": 100.0,
                "rth_elapsed_seconds": 60.0,
                "pct_levels_behind_trade": 0.5,
            }
        ])
        obs_df = pd.DataFrame([
            {"observation_ts": 1740993000000000000, "flip_ts": 1740993120000000000, "target_flip_within_horizon": 1}
        ])

        telemetry = CausalTelemetry()
        telemetry.start()
        telemetry.record_bar_callback("1s", ts_event=1000, ts_init=2000)
        telemetry.update_candidates(1)
        snapshot = telemetry.stop()

        status = mgr.persist_collection(cands_df, obs_df, snapshot)
        assert status["status"] == "SUCCESS"
        assert (mgr.collection_dir / "candidates.parquet").exists()
        assert (mgr.collection_dir / "observations.parquet").exists()
        assert (mgr.collection_dir / "collection_manifest.json").exists()


# =============================================================================
# 6. Collect Equivalence Validator Tests
# =============================================================================

def test_check_collect_equivalence_match():
    from scripts.check_collect_equivalence import check_collect_equivalence
    df_a = pd.DataFrame([
        {"observation_ts": 1000, "regime_start_ns": 500, "close": 21000.0, "atr": 10.500001},
        {"observation_ts": 2000, "regime_start_ns": 500, "close": 21005.0, "atr": 10.500002},
    ])
    df_b = pd.DataFrame([
        {"observation_ts": 1000, "regime_start_ns": 500, "close": 21000.0, "atr": 10.500000},
        {"observation_ts": 2000, "regime_start_ns": 500, "close": 21005.0, "atr": 10.500000},
    ])
    is_eq, report = check_collect_equivalence(df_a, df_b, float_tolerance=1e-4)
    assert is_eq is True
    assert report["verdict"] == "GENERIC_RUNNER_EQUIVALENT"


def test_check_collect_equivalence_divergence_detection():
    from scripts.check_collect_equivalence import check_collect_equivalence
    df_a = pd.DataFrame([
        {"observation_ts": 1000, "regime_start_ns": 500, "close": 21000.0, "atr": 10.5},
    ])
    df_b = pd.DataFrame([
        {"observation_ts": 1000, "regime_start_ns": 500, "close": 21000.0, "atr": 15.0},  # Big ATR divergence!
    ])
    is_eq, report = check_collect_equivalence(df_a, df_b, float_tolerance=1e-5)
    assert is_eq is False
    assert report["verdict"] == "GENERIC_RUNNER_DIVERGED"
    assert report["divergence"]["field"] == "atr"


# =============================================================================
# 7. Parity First-Divergence Canary Test
# =============================================================================

def test_first_divergence_canary_detects_candidate_mismatch():
    ref_ledger = [
        {"timestamp": 1000, "stage": "completed_bar", "payload": {"bar_type": "1s"}},
        {"timestamp": 2000, "stage": "candidate", "payload": {"close": 21000.0, "atr": 10.5}, "hash": "hash_a"},
    ]
    divergent_ledger = [
        {"timestamp": 1000, "stage": "completed_bar", "payload": {"bar_type": "1s"}},
        {"timestamp": 2000, "stage": "candidate", "payload": {"close": 21000.0, "atr": 12.0}, "hash": "hash_b"},  # Divergent ATR!
    ]

    is_identical, report = compare_ledgers(ref_ledger, divergent_ledger)
    assert is_identical is False
    assert report is not None
    assert report["timestamp"] == 2000
    assert report["first_failing_stage"] == "candidate"
    assert report["field"] == "atr"


# =============================================================================
# 8. Telemetry & Process RSS Memory Tests
# =============================================================================

def test_telemetry_process_rss_and_bar_breakdown():
    telemetry = CausalTelemetry()
    telemetry.start()
    telemetry.record_loaded_bars("1s", 50000)
    telemetry.record_loaded_bars("1m", 1200)

    telemetry.record_bar_callback("1s", ts_event=1000, ts_init=2000)
    telemetry.record_bar_callback("1s", ts_event=2000, ts_init=3000)
    telemetry.record_bar_callback("1m", ts_event=1000, ts_init=61000)
    telemetry.update_candidates(5)

    snapshot = telemetry.stop()
    assert snapshot.baseline_process_rss_mb > 0
    assert snapshot.peak_process_rss_mb >= snapshot.baseline_process_rss_mb
    assert snapshot.bars_loaded_by_tf["1s"] == 50000
    assert snapshot.callbacks_by_tf["1s"] == 2
    assert snapshot.callbacks_by_tf["1m"] == 1
    assert snapshot.candidates_count == 5


# =============================================================================
# 9. End-to-End Nonzero Candidate Collect Run Test
# =============================================================================

@pytest.mark.slow
def test_end_to_end_1day_collect_run_nonzero_candidates():
    study_path = Path("studies/Gemini_clean_maturity_flip_rolling_5m_productivity")
    if not study_path.exists():
        pytest.skip("Gemini_clean_maturity_flip_rolling_5m_productivity study not present")

    with tempfile.TemporaryDirectory() as tmp_out:
        status_data = run_collect_mode(
            study_path=study_path,
            stage="day",
            date_override="2023-03-03",
            output_dir=tmp_out,
        )

        assert status_data["status"] == "SUCCESS"
        assert status_data["candidates_count"] > 500
        assert status_data["observations_count"] > 500
        assert status_data["memory"]["peak_process_rss_mb"] > 50.0

        cand_df = pd.read_parquet(status_data["output_artifacts"]["candidates_parquet"])
        assert len(cand_df) == status_data["candidates_count"]
        assert "atr" in cand_df.columns
        assert "close" in cand_df.columns
        assert "observation_ts" in cand_df.columns

        # Verify Canonical Causal Parity against the 2025-03-03 Golden Reference Fixture
        ref_path = study_path / "reference_collection" / "reference_candidates_20250303.parquet"
        if ref_path.exists():
            from scripts.check_collect_equivalence import check_collect_equivalence
            ref_df = pd.read_parquet(ref_path)
            is_eq, report = check_collect_equivalence(ref_df, cand_df, allow_canonical_parity=True)
            assert is_eq is True
            assert report["population"]["reference_coverage"] == 1.0
            assert report["divergence_classes"]["unknown"] == 0
            assert report["verdict"] == "GENERIC_RUNNER_CANONICAL_PARITY"
