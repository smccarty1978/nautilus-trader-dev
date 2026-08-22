"""Regression tests for Phase 1 Packet B (Runtime READINESS).

Covers the 19 required scenarios from ML_Trend_Analysis_Workflow_V2_Phase1_FINAL.md §8/
Packet B: dataset identity parity (pass/fail), warmup coverage failure, 1s/1m timestamp
delta mismatches, the derived-5m path without an external stream, instrument precision
mismatch, callback-order inversion/pass, real collector instantiation, the reused
STRATEGY_OUTPUT_INTERFACE_MISSING check, the synthetic schema fixture (pass/fail),
double execution-identity resolution (pass/mutation-fail), the alternate-catalog-opener
scan (pass/injected-fail), artifact persistence, and overall-failure aggregation.

Tests against the real NQ catalog / real CleanFlip study are skipped when either is
absent, matching the skipif convention already used by scripts/tests/test_data_plan_
resolver.py and scripts/tests/test_alternate_catalog_opener_guard.py.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import yaml

from backtests.nt_runtime.compiled_study_loader import load_compiled_study
from backtests.nt_runtime.data_plan import DataPlan, resolve_data_plan
from backtests.nt_runtime.run_plan import RunPlan, RunStage, resolve_run_plan
from backtests.nt_runtime.output_manager import OutputManager, verify_strategy_output_interface
from backtests.nt_runtime.readiness import (
    AlternateCatalogOpenerFound,
    CallbackCausalOrderViolation,
    IdentityInstabilityError,
    InstrumentPrecisionMismatch,
    OutputSchemaContractFailed,
    RealCollectorInstantiationFailed,
    TimestampContractViolation,
    assert_callback_order_or_raise,
    build_synthetic_schema_fixture,
    check_r1_dataset_identity,
    instantiate_real_collector,
    persist_readiness_artifact,
    run_readiness,
    verify_dataset_identity_chain,
    verify_derived_5m_path,
    verify_identity_double_resolution,
    verify_instrument_precision,
    verify_no_alternate_catalog_openers,
    verify_stream_timestamp_delta,
)
from backtests.nt_runtime.data_plan import WrongPhysicalDatasetError, CatalogCoverageError

REPO_ROOT = Path(__file__).resolve().parents[2]
CLEAN_FLIP_STUDY = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"
REAL_NQ_CATALOG = REPO_ROOT / "data" / "catalog" / "NQ_v0_2020_2026"

_study_and_catalog_present = (
    (CLEAN_FLIP_STUDY / "compiled_study.json").exists() and REAL_NQ_CATALOG.exists()
)
requires_real_study = pytest.mark.skipif(
    not _study_and_catalog_present, reason="CleanFlip study or real NQ catalog absent"
)


class _Bar:
    """Minimal (ts_event, ts_init) test double for R2 -- verify_stream_timestamp_delta
    only reads these two attributes, so real NT Bar objects are not required."""

    def __init__(self, ts_event: int, ts_init: int):
        self.ts_event = ts_event
        self.ts_init = ts_init


class _MinuteBar:
    """Minimal completed-1m test double for R2's derived-5m path (CompletedMinuteFive
    MinuteAggregator.on_completed_1m only reads these six attributes)."""

    def __init__(self, open_ts: int, o: float, h: float, l: float, c: float, v: float):
        self.ts_event = open_ts
        self.open, self.high, self.low, self.close, self.volume = o, h, l, c, v


# =============================================================================
# 1/2 -- R1 dataset identity parity (pass / wrong physical catalog fails)
# =============================================================================

@requires_real_study
def test_r1_exact_declared_resolved_opened_dataset_parity_passes():
    study_data = load_compiled_study(CLEAN_FLIP_STUDY)
    run_plan = resolve_run_plan(study_data, stage="day", reference_date="2023-10-02")
    data_plan, identity = check_r1_dataset_identity(study_data, run_plan, REPO_ROOT)
    assert identity["passed"] is True
    assert identity["declared_dataset_id"] == identity["dataset_spec_dataset_id"] == "NQ_v0_2020_2026"
    assert data_plan.catalog_path == REAL_NQ_CATALOG.resolve()


def test_r1_wrong_physical_catalog_fails(tmp_path: Path):
    """DatasetSpec.dataset_id itself disagrees with the study's declared dataset_id --
    resolve_catalog_plan/resolve_data_plan's own path-based A2.2 check cannot see this
    (the paths still match); verify_dataset_identity_chain's own DatasetSpec.dataset_id
    comparison is what catches it."""
    repo_root = tmp_path / "repo"
    catalog_dir = repo_root / "data" / "catalog" / "SOME_CATALOG"
    catalog_dir.mkdir(parents=True)
    datasets_dir = repo_root / "research" / "datasets"
    datasets_dir.mkdir(parents=True)
    (datasets_dir / "DS_A.yaml").write_text(
        yaml.safe_dump({
            "dataset_id": "DS_B_MISMATCHED",  # declared is DS_A, authority claims DS_B
            "instrument_id": "NQ.XCME",
            "catalog_rel_path": "data/catalog/SOME_CATALOG",
            "provenance": {"source": "databento"},
            "streams": {
                "1s": {"source": "external", "bar_type": "NQ.XCME-1-SECOND-LAST-EXTERNAL",
                       "source_timestamp_semantics": "interval_open", "availability_rule": "interval_end",
                       "ts_init_delta_ns": 1_000_000_000},
                "1m": {"source": "external", "bar_type": "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
                       "source_timestamp_semantics": "interval_open", "availability_rule": "interval_end",
                       "ts_init_delta_ns": 60_000_000_000},
                "5m": {"source": "derived", "external_catalog_stream": False,
                       "derived_from": "1m", "aggregator": "CompletedMinuteFiveMinuteAggregator"},
            },
            "coverage": {"start": "2020-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
        }),
        encoding="utf-8",
    )

    study_data = SimpleNamespace(spec=SimpleNamespace(execution=SimpleNamespace(
        data_requirements={"dataset_id": "DS_A"}
    )))
    data_plan = DataPlan(
        symbol="NQ", venue="XCME", instrument_id="NQ.XCME", multiplier="20.0", price_increment="0.25",
        catalog_path=catalog_dir.resolve(), bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        start_dt=pd.Timestamp("2023-10-02", tz="UTC"), end_dt=pd.Timestamp("2023-10-02 23:59:59", tz="UTC"),
        warmup_days=5, warmup_start_dt=pd.Timestamp("2023-09-27", tz="UTC"),
        raw_timestamp_semantic="OPEN_STAMPED", ts_init_delta_1s_ns=1_000_000_000, ts_init_delta_1m_ns=60_000_000_000,
    )

    with pytest.raises(WrongPhysicalDatasetError, match="WRONG_PHYSICAL_DATASET"):
        verify_dataset_identity_chain(study_data, data_plan, repo_root)


# =============================================================================
# 3 -- R1 warmup coverage missing fails
# =============================================================================

@requires_real_study
def test_r1_warmup_coverage_missing_fails():
    study_data = load_compiled_study(CLEAN_FLIP_STUDY)
    run_plan = resolve_run_plan(study_data, stage="day", reference_date="2023-10-05")
    with pytest.raises(CatalogCoverageError, match="CATALOG_COVERAGE_GAP"):
        check_r1_dataset_identity(study_data, run_plan, REPO_ROOT, warmup_days=1500)


# =============================================================================
# 4/5 -- R2 1s / 1m timestamp delta mismatches fail
# =============================================================================

def test_r2_1s_timestamp_delta_mismatch_fails():
    bars = [_Bar(ts_event=0, ts_init=1_000_000_000), _Bar(ts_event=1_000_000_000, ts_init=1_500_000_000)]
    with pytest.raises(TimestampContractViolation, match="TS_INIT_DELTA_MISMATCH"):
        verify_stream_timestamp_delta(bars, expected_delta_ns=1_000_000_000, label="1s")


def test_r2_1m_timestamp_delta_mismatch_fails():
    bars = [_Bar(ts_event=0, ts_init=60_000_000_000), _Bar(ts_event=60_000_000_000, ts_init=61_000_000_000)]
    with pytest.raises(TimestampContractViolation, match="TS_INIT_DELTA_MISMATCH"):
        verify_stream_timestamp_delta(bars, expected_delta_ns=60_000_000_000, label="1m")


def test_r2_timestamp_contract_passes_on_correct_deltas():
    bars = [_Bar(ts_event=i * 1_000_000_000, ts_init=(i + 1) * 1_000_000_000) for i in range(5)]
    result = verify_stream_timestamp_delta(bars, expected_delta_ns=1_000_000_000, label="1s")
    assert result["passed"] is True
    assert result["sampled"] == 5


# =============================================================================
# 6 -- derived 5m path is validated without an external 5m stream
# =============================================================================

def test_r2_derived_5m_path_validated_from_completed_1m_only():
    ns = 1_000_000_000
    bars_1m = [_MinuteBar(minute * 60 * ns, 100.0, 101.0, 99.0, 100.0, 10.0) for minute in range(5)]
    result = verify_derived_5m_path(bars_1m)
    assert result["passed"] is True
    assert result["completed_5m_count"] == 1
    # Structural proof this never opens/looks for an external 5m stream: the function
    # accepts exactly the completed-1m sample and nothing else.
    import inspect
    from backtests.nt_runtime import readiness as readiness_mod
    src = inspect.getsource(readiness_mod.verify_derived_5m_path)
    assert "bar_type_5m" not in src and "5-MINUTE" not in src


def test_r2_derived_5m_path_fails_on_incomplete_parents():
    ns = 1_000_000_000
    bars_1m = [_MinuteBar(minute * 60 * ns, 100.0, 101.0, 99.0, 100.0, 10.0) for minute in (0, 1, 3, 4)]
    with pytest.raises(Exception):
        verify_derived_5m_path(bars_1m)


# =============================================================================
# 7 -- instrument precision mismatch fails
# =============================================================================

def test_r3_instrument_precision_mismatch_fails():
    data_plan = SimpleNamespace(instrument_id="NQ.XCME", price_increment="0.25")
    instrument = SimpleNamespace(id="NQ.XCME", price_increment="1.00", price_precision=0)
    sample_bar = SimpleNamespace(close=SimpleNamespace(precision=2))
    with pytest.raises(InstrumentPrecisionMismatch, match="INSTRUMENT_PRECISION_MISMATCH"):
        verify_instrument_precision(data_plan, instrument, sample_bar)


def test_r3_instrument_precision_passes_on_match():
    data_plan = SimpleNamespace(instrument_id="NQ.XCME", price_increment="0.25")
    instrument = SimpleNamespace(id="NQ.XCME", price_increment="0.25", price_precision=2)
    sample_bar = SimpleNamespace(close=SimpleNamespace(precision=2))
    result = verify_instrument_precision(data_plan, instrument, sample_bar)
    assert result["passed"] is True


# =============================================================================
# 8/9 -- callback inversion fails / valid order passes
# =============================================================================

def test_r4_callback_inversion_fails():
    event_stream = [(1_000, "1m"), (1_000, "1s")]  # 1s AFTER coincident 1m -> inversion
    with pytest.raises(CallbackCausalOrderViolation, match="CALLBACK_CAUSAL_ORDER_VIOLATION"):
        assert_callback_order_or_raise(event_stream)


def test_r4_valid_callback_order_passes():
    event_stream = [(1_000, "1s"), (1_000, "1m"), (2_000, "1s")]
    result = assert_callback_order_or_raise(event_stream)
    assert result["passed"] is True
    assert result["events"] == 3


# =============================================================================
# 10 -- real collector instantiates with phase0 authorization
# =============================================================================

@requires_real_study
def test_r5_real_collector_instantiates_with_fresh_phase0_authorization(tmp_path: Path):
    """Mirrors scripts/tests/test_nt_runner_collect.py's
    test_clean_flip_collector_constructs_via_generic_wiring: generates a FRESH manifest
    at test time (not the possibly-stale committed one), so this test is independent of
    whether the repo's committed phase0 artifact has drifted relative to the current tree
    -- an unrelated, pre-existing concern this packet does not own."""
    from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation import phase0 as codex_phase0

    study_data = load_compiled_study(CLEAN_FLIP_STUDY)
    run_plan = resolve_run_plan(study_data, stage="day", reference_date="2023-10-02")
    data_plan = resolve_data_plan(study_data, run_plan.start_date, run_plan.end_date, repo_root=REPO_ROOT)

    fresh_manifest_path = tmp_path / "artifacts" / "phase0_source_manifest.json"
    codex_phase0.write_manifest(fresh_manifest_path)
    study_data_for_run = dataclasses.replace(study_data, study_dir=tmp_path)

    collector = instantiate_real_collector(study_data_for_run, data_plan)
    assert type(collector).__name__ == "CleanFlipCollector"


def test_r5_real_collector_instantiation_failure_is_wrapped():
    study_data = SimpleNamespace(
        spec=SimpleNamespace(
            execution=SimpleNamespace(strategy_class="strategies.flip_prediction_collector.FlipPredictionCollector"),
            study=SimpleNamespace(type="flip_prediction"),
            population=SimpleNamespace(prevailing_regime=None), target=SimpleNamespace(direction=None, horizon_seconds=None),
            features=SimpleNamespace(feature_list=None, metadata_columns=None),
        ),
        study_dir=Path("/nonexistent"),
        contracts={},
    )
    data_plan = SimpleNamespace(instrument_id="NQ.XCME", bar_type_1s="X-1-SECOND", bar_type_1m="X-1-MINUTE")
    with patch("backtests.nt_runtime.readiness.resolve_strategy_binding", side_effect=RuntimeError("boom")):
        with pytest.raises(RealCollectorInstantiationFailed, match="REAL_COLLECTOR_INSTANTIATION_FAILED"):
            instantiate_real_collector(study_data, data_plan)


# =============================================================================
# 11 -- missing output interface fails using the existing (reused) check
# =============================================================================

def test_r6_missing_output_interface_fails_via_existing_check():
    """R6 reuses backtests.nt_runtime.output_manager.verify_strategy_output_interface
    verbatim -- this proves the shared check itself, which is exactly what R6 invokes."""
    strategy = MagicMock(spec=[])  # no candidates/observations interface at all
    with pytest.raises(RuntimeError, match="STRATEGY_OUTPUT_INTERFACE_MISSING"):
        verify_strategy_output_interface(strategy, bars_loaded_total=1)


def test_r6_present_output_interface_passes():
    strategy = MagicMock(spec=["get_candidates_dataframe", "get_observations_dataframe"])
    strategy.get_candidates_dataframe.return_value = pd.DataFrame()
    strategy.get_observations_dataframe.return_value = pd.DataFrame()
    cand_df, obs_df = verify_strategy_output_interface(strategy, bars_loaded_total=1)
    assert cand_df.empty and obs_df.empty


# =============================================================================
# 12/13 -- synthetic schema fixture passes / malformed schema fails
# =============================================================================

@requires_real_study
def test_r7_synthetic_valid_output_schema_passes():
    study_data = load_compiled_study(CLEAN_FLIP_STUDY)
    run_plan = resolve_run_plan(study_data, stage="day", reference_date="2023-10-02")
    data_plan = resolve_data_plan(study_data, run_plan.start_date, run_plan.end_date, repo_root=REPO_ROOT)
    result = build_synthetic_schema_fixture(study_data, data_plan, run_plan)
    assert result["passed"] is True
    assert result["feature_checked"]


@requires_real_study
def test_r7_malformed_schema_fails_via_real_output_manager(tmp_path: Path):
    """Proves the malformed-schema failure path through the exact same OutputManager
    call R7 uses -- not a second, reimplemented validator."""
    from backtests.nt_runtime.telemetry import CausalTelemetry

    study_data = load_compiled_study(CLEAN_FLIP_STUDY)
    run_plan = resolve_run_plan(study_data, stage="day", reference_date="2023-10-02")
    data_plan = resolve_data_plan(study_data, run_plan.start_date, run_plan.end_date, repo_root=REPO_ROOT)

    # Missing declared metadata columns entirely -> MISSING_OUTPUT_METADATA.
    bad_candidates = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
    }])
    bad_observations = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0, "disposition": "LABELED_POSITIVE",
    }])

    telemetry = CausalTelemetry()
    telemetry.start()
    snapshot = telemetry.stop()

    mgr = OutputManager(study_data, data_plan, run_plan, output_base_dir=tmp_path)
    with pytest.raises(ValueError, match="MISSING_OUTPUT_METADATA"):
        mgr.persist_collection(bad_candidates, bad_observations, snapshot)


# =============================================================================
# 14/15 -- double identity resolution passes / mutation between resolutions fails
# =============================================================================

@requires_real_study
def test_r8_double_identity_resolution_passes():
    result = verify_identity_double_resolution(CLEAN_FLIP_STUDY, REPO_ROOT)
    assert result["passed"] is True
    assert result["coverage_pct"] == 100.0
    assert result["unresolved_dependencies"] == []


def test_r8_identity_mutation_between_resolutions_fails():
    manifest_a = ("hash_A", {"repo:a.py": "x"}, {"unresolved_dependencies": [], "coverage_pct": 100.0})
    manifest_b = ("hash_B", {"repo:a.py": "y"}, {"unresolved_dependencies": [], "coverage_pct": 100.0})
    with patch(
        "scripts.resolve_execution_manifest.resolve_execution_manifest",
        side_effect=[manifest_a, manifest_b],
    ):
        with pytest.raises(IdentityInstabilityError, match="READINESS_IDENTITY_INSTABILITY"):
            verify_identity_double_resolution(Path("/does/not/matter"), REPO_ROOT)


# =============================================================================
# 16/17 -- alternate opener scan passes on the quarantined study / injected fails
# =============================================================================

@requires_real_study
def test_r9_alternate_catalog_opener_scan_passes_on_quarantined_study():
    result = verify_no_alternate_catalog_openers(CLEAN_FLIP_STUDY)
    assert result["passed"] is True
    assert result["violations"] == 0


def test_r9_injected_alternate_catalog_opener_fails(tmp_path: Path):
    (tmp_path / "implementation").mkdir()
    (tmp_path / "implementation" / "sneaky.py").write_text(
        "from nautilus_trader.persistence.catalog import ParquetDataCatalog\n"
        "c = ParquetDataCatalog('data/catalog/NQ_v0_2020_2026')\n",
        encoding="utf-8",
    )
    with pytest.raises(AlternateCatalogOpenerFound, match="ALTERNATE_CATALOG_OPENER_VIOLATION"):
        verify_no_alternate_catalog_openers(tmp_path)


# =============================================================================
# 18 -- readiness artifact is persisted
# =============================================================================

def test_readiness_artifact_is_persisted(tmp_path: Path):
    result = {"schema_version": 1, "study": "x", "overall_status": "BLOCKED"}
    artifact_path = persist_readiness_artifact(tmp_path, result)
    assert artifact_path == tmp_path / "audit" / "readiness.json"
    assert artifact_path.exists()
    with open(artifact_path, "r", encoding="utf-8") as f:
        persisted = json.load(f)
    assert persisted["overall_status"] == "BLOCKED"


# =============================================================================
# 19 -- any failed check marks overall READINESS failed
# =============================================================================

def test_run_readiness_marks_overall_failed_when_any_check_fails(tmp_path: Path):
    """R1 injected to fail; R2-R7 must cascade as R1_PREREQUISITE_FAILED without being
    attempted, and R8/R9 (independent of DataPlan) must still run on their own."""
    study_dir = tmp_path / "fake_study"
    study_dir.mkdir()
    study_dict = {
        "study": {"id": "fake_study", "type": "flip_prediction", "risk_tier": 2, "description": "x"},
        "operation": {"kind": "train_evaluate", "target_metric": "roc_auc"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state", "prevailing_regime": "bullish", "session": "RTH",
                        "qualification": {"age_gate_seconds": 120, "established": True}},
        "target": {"type": "flip", "event": "confirmed_flip", "direction": "bearish", "horizon_seconds": 300},
        "features": {"metadata_columns": ["observation_ts", "regime_start_ns", "checkpoint_index"]},
        "chronology": {"train": [2021], "dev": [2022], "prohibited": [2026]},
        "execution": {"runtime": "nautilustrader", "strategy_class": "strategies.flip_prediction_collector.FlipPredictionCollector",
                      "progress_seconds": 60, "bounded": True},
    }
    from research.schemas.study_spec import StudySpec
    spec = StudySpec.model_validate(study_dict)
    (study_dir / "study.yaml").write_text(yaml.safe_dump(study_dict), encoding="utf-8")
    (study_dir / "compiled_study.json").write_text(json.dumps({
        "study_id": "fake_study", "study_type": "flip_prediction", "spec_sha256": spec.compute_sha256(),
        "contracts": {"execution_contract": {"runtime": "nautilustrader"}},
    }), encoding="utf-8")

    with patch(
        "backtests.nt_runtime.readiness.check_r1_dataset_identity",
        side_effect=RuntimeError("INJECTED_R1_FAILURE"),
    ):
        result = run_readiness(study_dir, repo_root=REPO_ROOT)

    assert result["overall_status"] == "BLOCKED"
    assert result["r1_dataset_identity"]["passed"] is False
    assert result["r2_1s_timestamp"]["code"] == "R1_PREREQUISITE_FAILED"
    assert result["r7_synthetic_schema"]["code"] == "R1_PREREQUISITE_FAILED"
    # R9 is independent of DataPlan and must still have actually run.
    assert result["r9_alternate_opener"]["passed"] is True
    assert (study_dir / "audit" / "readiness.json").exists()
