"""Unit and Integration Tests for NT Generic Runner MVP (Phase 1: collect mode).
================================================================================
Validates compiled study loader, data plan, engine builder, run plan, telemetry,
output manager, CLI runner, and golden equivalence against reference collector.
"""

import dataclasses
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml
from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

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
from backtests.nt_runtime.modes.collect import _execute_collect, run_collect_mode
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


# =============================================================================
# 10. Phase-Zero Manifest Path Wiring Tests (generic collect.py cfg_kwargs fix)
# =============================================================================
# A collector's StrategyConfig may declare `phase0_manifest_path`, a fail-closed
# phase-zero authentication gate (see studies/Codex_clean_maturity_flip_rolling_5m_
# productivity/implementation/phase0.py). _execute_collect must resolve that path
# generically from study_data.study_dir -- the same hasattr-gated convention already
# used for prevailing_regime/target_direction/etc -- rather than leaving it at the
# declaring config's "" default, which always failed closed regardless of study.


class _Phase0GatedTestConfig(StrategyConfig, frozen=True):
    """Minimal StrategyConfig declaring the phase-zero field, for exercising the
    shared collect-mode wiring without constructing the full CleanFlipCollector."""
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    phase0_manifest_path: str = ""


class _Phase0GatedTestStrategy(Strategy):
    """Calls the real, unmodified Codex phase0.authorize_execution gate on construction,
    so negative-path tests exercise the actual fail-closed refusal without paying for
    CleanFlipCollector's full feature-engine setup."""

    def __init__(self, config: _Phase0GatedTestConfig) -> None:
        super().__init__(config)
        from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.phase0 import (
            authorize_execution,
        )
        authorize_execution(Path(config.phase0_manifest_path))


def _plans_for(study_data, reference_date="2023-03-03"):
    run_plan = resolve_run_plan(study_data, stage="day", reference_date=reference_date)
    data_plan = resolve_data_plan(study_data, start_date=run_plan.start_date, end_date=run_plan.end_date)
    return run_plan, data_plan


def test_execute_collect_resolves_phase0_manifest_path_generically(mock_study_dir):
    """cfg_kwargs must receive study-directory-relative phase0_manifest_path, not the
    declaring config's "" default, and must not be hardcoded to any particular study."""
    study_data = load_compiled_study(mock_study_dir)
    run_plan, data_plan = _plans_for(study_data)

    config_cls = MagicMock(name="ConfigClsWithPhase0")
    config_cls.phase0_manifest_path = ""  # declared field marker so hasattr(...) is True
    strategy_cls = MagicMock(name="StrategyClsWithPhase0")
    strategy_cls.return_value = MagicMock(spec=[])
    strategy_binding = SimpleNamespace(config_cls=config_cls, strategy_cls=strategy_cls)

    telemetry = CausalTelemetry()
    telemetry.start()
    output_mgr = MagicMock()

    with patch("backtests.nt_runtime.modes.collect.build_engine", return_value=(MagicMock(), MagicMock())):
        _execute_collect(
            study_data, study_data.spec, data_plan, run_plan, strategy_binding,
            output_mgr, telemetry, "ERROR",
        )

    resolved_path = config_cls.call_args.kwargs["phase0_manifest_path"]
    expected_path = str(study_data.study_dir / "artifacts" / "phase0_source_manifest.json")
    assert resolved_path == expected_path
    # Study-directory-relative, not hardcoded to any particular study name: this fixture's
    # study is named "test_collect_study", nowhere near any real study on disk.
    assert resolved_path.startswith(str(study_data.study_dir))
    assert resolved_path.endswith("test_collect_study\\artifacts\\phase0_source_manifest.json") or \
        resolved_path.endswith("test_collect_study/artifacts/phase0_source_manifest.json")
    assert "Codex_clean_maturity_flip_rolling_5m_productivity" not in resolved_path


def test_execute_collect_fails_closed_when_phase0_manifest_missing(mock_study_dir):
    """No artifacts/phase0_source_manifest.json at the resolved path -> the existing
    'phase-zero authorization missing' refusal fires, reached via the correct path."""
    study_data = load_compiled_study(mock_study_dir)
    run_plan, data_plan = _plans_for(study_data)
    assert not (mock_study_dir / "artifacts" / "phase0_source_manifest.json").exists()

    strategy_binding = SimpleNamespace(
        config_cls=_Phase0GatedTestConfig, strategy_cls=_Phase0GatedTestStrategy,
    )
    telemetry = CausalTelemetry()
    telemetry.start()
    output_mgr = MagicMock()

    with patch("backtests.nt_runtime.modes.collect.build_engine", return_value=(MagicMock(), MagicMock())):
        with pytest.raises(RuntimeError, match="phase-zero authorization missing"):
            _execute_collect(
                study_data, study_data.spec, data_plan, run_plan, strategy_binding,
                output_mgr, telemetry, "ERROR",
            )


def test_execute_collect_fails_closed_when_phase0_manifest_stale(mock_study_dir):
    """A syntactically-valid but tampered manifest at the resolved path still fails via
    the existing authorize_execution 'stale or altered' refusal."""
    study_data = load_compiled_study(mock_study_dir)
    run_plan, data_plan = _plans_for(study_data)

    artifacts_dir = mock_study_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tampered_manifest = artifacts_dir / "phase0_source_manifest.json"
    tampered_manifest.write_text(json.dumps({
        "schema_version": 1, "authenticated": True, "tampered_by_test": True,
    }))

    strategy_binding = SimpleNamespace(
        config_cls=_Phase0GatedTestConfig, strategy_cls=_Phase0GatedTestStrategy,
    )
    telemetry = CausalTelemetry()
    telemetry.start()
    output_mgr = MagicMock()

    with patch("backtests.nt_runtime.modes.collect.build_engine", return_value=(MagicMock(), MagicMock())):
        with pytest.raises(RuntimeError, match="stale or altered"):
            _execute_collect(
                study_data, study_data.spec, data_plan, run_plan, strategy_binding,
                output_mgr, telemetry, "ERROR",
            )


def test_execute_collect_leaves_non_phase0_config_unaffected(mock_study_dir):
    """A config_cls that does NOT declare phase0_manifest_path (the pre-existing
    FlipPredictionCollector binding) is completely unaffected by the wiring change:
    cfg_kwargs gets no such key and construction proceeds exactly as before."""
    study_data = load_compiled_study(mock_study_dir)
    run_plan, data_plan = _plans_for(study_data)

    binding = resolve_strategy_binding("flip_prediction_collector", mode="collect")
    assert not hasattr(binding.config_cls, "phase0_manifest_path")
    fake_strategy_instance = MagicMock(spec=[])
    strategy_binding = dataclasses.replace(
        binding, strategy_cls=MagicMock(return_value=fake_strategy_instance),
    )

    telemetry = CausalTelemetry()
    telemetry.start()
    output_mgr = MagicMock()

    with patch("backtests.nt_runtime.modes.collect.build_engine", return_value=(MagicMock(), MagicMock())):
        _execute_collect(
            study_data, study_data.spec, data_plan, run_plan, strategy_binding,
            output_mgr, telemetry, "ERROR",
        )

    constructed_config = strategy_binding.strategy_cls.call_args.args[0]
    assert not hasattr(constructed_config, "phase0_manifest_path")
    assert type(constructed_config).__name__ == "FlipPredictionCollectorConfig"


def test_clean_flip_collector_constructs_via_generic_wiring():
    """Proves the wiring is correct for the real governed study: CleanFlipCollector.__init__
    completes without raising when driven through _execute_collect's real cfg_kwargs-building
    logic. build_engine/engine.run() are stubbed so this exercises config-building and
    strategy construction only -- no real market data is loaded and no NT event loop runs,
    so this stays fast and deterministic (not marked slow).
    """
    study_path = Path("studies/Codex_clean_maturity_flip_rolling_5m_productivity")
    if not study_path.exists():
        pytest.skip("Codex_clean_maturity_flip_rolling_5m_productivity study not present")

    from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation import phase0 as codex_phase0

    study_data = load_compiled_study(study_path)
    run_plan, data_plan = _plans_for(study_data, reference_date="2023-10-02")
    strategy_binding = resolve_strategy_binding(
        study_data.spec.execution.strategy_class,
        study_type=study_data.spec.study.type,
        mode="collect",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        # A freshly authenticated manifest, generated by phase0's own (unmodified)
        # authenticate() at test time -- not asserted/fabricated by the test -- so this
        # test is independent of whether the repo's committed artifact happens to have
        # drifted stale relative to the current tree (an unrelated, pre-existing concern).
        fresh_manifest_path = Path(tmpdir) / "artifacts" / "phase0_source_manifest.json"
        codex_phase0.write_manifest(fresh_manifest_path)
        study_data_for_run = dataclasses.replace(study_data, study_dir=Path(tmpdir))

        class _StopAfterConstruction(Exception):
            pass

        mock_engine = MagicMock()
        mock_engine.run.side_effect = _StopAfterConstruction("stubbed after strategy construction")
        telemetry = CausalTelemetry()
        telemetry.start()
        output_mgr = MagicMock()

        with patch(
            "backtests.nt_runtime.modes.collect.build_engine",
            return_value=(mock_engine, MagicMock()),
        ):
            with pytest.raises(_StopAfterConstruction):
                _execute_collect(
                    study_data_for_run, study_data.spec, data_plan, run_plan, strategy_binding,
                    output_mgr, telemetry, "ERROR",
                )

        # engine.run() was reached, so CleanFlipCollector.__init__ (which calls
        # authorize_execution before any other setup) completed without raising.
        mock_engine.add_strategy.assert_called_once()
        constructed_strategy = mock_engine.add_strategy.call_args.args[0]
        assert type(constructed_strategy).__name__ == "CleanFlipCollector"


# =============================================================================
# 11. Fail-Closed Output-Interface Verification
# =============================================================================
# A run where the engine genuinely loaded bars (backtests/nt_runtime/engine_builder.py
# calls telemetry.record_loaded_bars, independent of any collector's own instrumentation)
# but the strategy exposes no candidates/observations extraction interface at all is
# unverifiable, not merely unproductive: there is no way to distinguish "legitimately
# found nothing" from "processed real data and never surfaced it" (observed live:
# runs/20260818_174901_..._day loaded 213K+ bars and internally produced 409 regime
# transitions, yet silently reported 0 candidates/observations because the strategy
# predated this output-interface convention). bars_1s_count/bars_1m_count telemetry is
# deliberately NOT included in this fail-closed check: it is unimplemented even by the
# known-working strategies/flip_prediction_collector.py reference and asserted nowhere,
# so hardening it would break every existing study's collect run.

def test_execute_collect_fails_closed_when_bars_loaded_but_no_candidates_interface(mock_study_dir):
    study_data = load_compiled_study(mock_study_dir)
    run_plan, data_plan = _plans_for(study_data)

    strategy_binding = SimpleNamespace(
        config_cls=MagicMock(spec=[]),
        strategy_cls=MagicMock(return_value=MagicMock(spec=[])),  # no output interface at all
    )

    telemetry = CausalTelemetry()
    telemetry.start()
    telemetry.record_loaded_bars("1s", 100)
    output_mgr = MagicMock()

    with patch("backtests.nt_runtime.modes.collect.build_engine", return_value=(MagicMock(), MagicMock())):
        with pytest.raises(RuntimeError, match="STRATEGY_OUTPUT_INTERFACE_MISSING"):
            _execute_collect(
                study_data, study_data.spec, data_plan, run_plan, strategy_binding,
                output_mgr, telemetry, "ERROR",
            )


def test_execute_collect_fails_closed_when_bars_loaded_but_no_observations_interface(mock_study_dir):
    study_data = load_compiled_study(mock_study_dir)
    run_plan, data_plan = _plans_for(study_data)

    # Candidates interface present; observations interface absent.
    strategy_instance = MagicMock(spec=["get_candidates_dataframe"])
    strategy_instance.get_candidates_dataframe.return_value = pd.DataFrame()
    strategy_binding = SimpleNamespace(
        config_cls=MagicMock(spec=[]),
        strategy_cls=MagicMock(return_value=strategy_instance),
    )

    telemetry = CausalTelemetry()
    telemetry.start()
    telemetry.record_loaded_bars("1m", 5)
    output_mgr = MagicMock()

    with patch("backtests.nt_runtime.modes.collect.build_engine", return_value=(MagicMock(), MagicMock())):
        with pytest.raises(RuntimeError, match="STRATEGY_OUTPUT_INTERFACE_MISSING"):
            _execute_collect(
                study_data, study_data.spec, data_plan, run_plan, strategy_binding,
                output_mgr, telemetry, "ERROR",
            )


def test_execute_collect_succeeds_when_interface_present_but_legitimately_empty(mock_study_dir):
    """A strategy that DOES implement both extraction methods but finds nothing (a
    valid population can legitimately produce zero candidates) must NOT be treated
    as a defect -- this proves the check targets interface absence, not row count."""
    study_data = load_compiled_study(mock_study_dir)
    run_plan, data_plan = _plans_for(study_data)

    strategy_instance = MagicMock(spec=["get_candidates_dataframe", "get_observations_dataframe"])
    strategy_instance.get_candidates_dataframe.return_value = pd.DataFrame()
    strategy_instance.get_observations_dataframe.return_value = pd.DataFrame()
    strategy_binding = SimpleNamespace(
        config_cls=MagicMock(spec=[]),
        strategy_cls=MagicMock(return_value=strategy_instance),
    )

    telemetry = CausalTelemetry()
    telemetry.start()
    telemetry.record_loaded_bars("1s", 100)
    telemetry.record_loaded_bars("1m", 5)
    output_mgr = MagicMock()

    with patch("backtests.nt_runtime.modes.collect.build_engine", return_value=(MagicMock(), MagicMock())):
        status_data = _execute_collect(
            study_data, study_data.spec, data_plan, run_plan, strategy_binding,
            output_mgr, telemetry, "ERROR",
        )

    assert status_data is output_mgr.persist_collection.return_value
    persisted_candidates_df = output_mgr.persist_collection.call_args.args[0]
    assert len(persisted_candidates_df) == 0


def test_execute_collect_does_not_fail_closed_when_no_bars_loaded(mock_study_dir):
    """No bars loaded at all (telemetry.bars_loaded_by_tf stays empty, exactly as in
    every pre-existing test in this file where build_engine is mocked) -- nothing to
    verify, so a strategy without the interface must not be treated as a defect here.
    This is also what proves the new check cannot regress any existing test above."""
    study_data = load_compiled_study(mock_study_dir)
    run_plan, data_plan = _plans_for(study_data)

    strategy_binding = SimpleNamespace(
        config_cls=MagicMock(spec=[]),
        strategy_cls=MagicMock(return_value=MagicMock(spec=[])),
    )

    telemetry = CausalTelemetry()
    telemetry.start()
    output_mgr = MagicMock()

    with patch("backtests.nt_runtime.modes.collect.build_engine", return_value=(MagicMock(), MagicMock())):
        _execute_collect(
            study_data, study_data.spec, data_plan, run_plan, strategy_binding,
            output_mgr, telemetry, "ERROR",
        )  # must not raise

    output_mgr.persist_collection.assert_called_once()
