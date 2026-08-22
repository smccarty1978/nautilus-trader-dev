"""Regression tests for Phase 1 Packet D1 (zero-row output hardening).

Covers:
  - persist_collection: metadata/candidate-key/observation-key validation must not
    become vacuous merely because a DataFrame has zero rows
  - reconcile_candidate_dispositions: the zero-candidate branch must not be reachable
    with a malformed schema, and the full candidate key may not shrink via intersection
  - D1.4: validate_smoke.py's real-population guard is not duplicated here
  - D1.5: current non-empty UNEXPECTED_OUTPUT_COLUMN behavior is unchanged pending D2
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtests.nt_runtime.compiled_study_loader import CompiledStudyData
from backtests.nt_runtime.data_plan import DataPlan
from backtests.nt_runtime.output_manager import (
    CANDIDATE_KEY_COLUMNS,
    OutputManager,
    reconcile_candidate_dispositions,
)
from backtests.nt_runtime.run_plan import RunPlan, RunStage
from backtests.nt_runtime.telemetry import CausalTelemetry
from research.schemas.study_spec import StudySpec

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Shared harness -- a minimal, real OutputManager, no real catalog required.
# ---------------------------------------------------------------------------

def _spec(metadata_columns, feature_list=None, feature_list_sha256=None):
    study_dict = {
        "study": {
            "id": "d1_zero_row_test",
            "type": "flip_prediction",
            "risk_tier": 2,
            "description": "D1 zero-row hardening harness study.",
        },
        "operation": {"kind": "train_evaluate", "target_metric": "pr_auc"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {
            "type": "regime_state", "prevailing_regime": "bullish", "session": "RTH",
            "qualification": {"age_gate_seconds": 300, "established": True},
        },
        "target": {"type": "flip", "event": "confirmed_flip", "direction": "bearish", "horizon_seconds": 300},
        "features": {
            "feature_list": feature_list,
            "feature_list_sha256": feature_list_sha256,
            "metadata_columns": metadata_columns,
        },
        "chronology": {"train": [2021, 2022, 2023, 2024], "dev": [2025], "prohibited": [2026]},
        "execution": {
            "runtime": "nautilustrader",
            "strategy_class": "strategies.flip_prediction_collector.FlipPredictionCollector",
            "progress_seconds": 60, "bounded": True,
        },
    }
    return StudySpec.model_validate(study_dict)


def _output_manager(tmp_path: Path, metadata_columns, feature_list=None, feature_list_sha256=None) -> OutputManager:
    spec = _spec(metadata_columns, feature_list, feature_list_sha256)
    study_data = CompiledStudyData(
        study_id=spec.study.id, study_dir=tmp_path, study_type=spec.study.type,
        spec=spec, spec_sha256=spec.compute_sha256(), contracts={}, raw_compiled_json={},
    )
    start_dt = pd.Timestamp("2023-10-02", tz="UTC")
    end_dt = pd.Timestamp("2023-10-02 23:59:59.999999999", tz="UTC")
    data_plan = DataPlan(
        symbol="NQ", venue="XCME", instrument_id="NQ.XCME", multiplier="20.0", price_increment="0.25",
        catalog_path=tmp_path / "fake_catalog", bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL", start_dt=start_dt, end_dt=end_dt,
        warmup_days=5, warmup_start_dt=start_dt - pd.Timedelta(days=5),
        raw_timestamp_semantic="OPEN_STAMPED", ts_init_delta_1s_ns=1_000_000_000, ts_init_delta_1m_ns=60_000_000_000,
    )
    run_plan = RunPlan(stage=RunStage.DAY, start_date="2023-10-02", end_date="2023-10-02")
    return OutputManager(study_data, data_plan, run_plan, output_base_dir=tmp_path / "runs")


def _telemetry():
    t = CausalTelemetry()
    t.start()
    return t.stop()


FULL_KEY_METADATA = ["observation_ts", "regime_start_ns", "checkpoint_index", "close", "atr"]


def _empty_df(columns):
    return pd.DataFrame(columns=columns)


# ---------------------------------------------------------------------------
# 1. empty candidates with required columns => structurally valid
# ---------------------------------------------------------------------------

def test_empty_candidates_with_required_columns_is_structurally_valid(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    cands_df = _empty_df(FULL_KEY_METADATA)
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)

    status = mgr.persist_collection(cands_df, obs_df, _telemetry())
    assert status["status"] == "SUCCESS"
    assert status["candidates_count"] == 0
    assert status["observations_count"] == 0


# ---------------------------------------------------------------------------
# 2. empty candidates with missing metadata column => fail
# ---------------------------------------------------------------------------

def test_empty_candidates_missing_metadata_column_fails(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    cands_df = _empty_df(["observation_ts", "regime_start_ns", "checkpoint_index"])  # missing close/atr
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)

    with pytest.raises(ValueError, match="MISSING_OUTPUT_METADATA"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


# ---------------------------------------------------------------------------
# 3. empty candidates with missing candidate key field => fail
# ---------------------------------------------------------------------------

def test_empty_candidates_missing_candidate_key_field_fails(tmp_path: Path):
    """The declared metadata list itself omits the key -- the independent key check must
    still catch it (D1.2: not derived from declared_metadata contents)."""
    metadata = ["observation_ts", "close", "atr"]  # omits regime_start_ns/checkpoint_index
    mgr = _output_manager(tmp_path, metadata_columns=metadata)
    cands_df = _empty_df(metadata)
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)

    with pytest.raises(ValueError, match="MISSING_CANDIDATE_KEY_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


# ---------------------------------------------------------------------------
# 4. empty observations with missing observation key => fail
# ---------------------------------------------------------------------------

def test_empty_observations_missing_observation_key_fails(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    cands_df = _empty_df(FULL_KEY_METADATA)
    obs_df = _empty_df(["observation_ts"])  # missing regime_start_ns/checkpoint_index

    with pytest.raises(ValueError, match="MISSING_OBSERVATION_KEY_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


def test_reconcile_empty_observations_missing_key_directly():
    cand_df = _empty_df(CANDIDATE_KEY_COLUMNS)
    obs_df = _empty_df(["observation_ts"])
    report = reconcile_candidate_dispositions(cand_df, obs_df)
    assert report["passed"] is False
    assert any("observations dataframe missing" in f for f in report["findings"])


# ---------------------------------------------------------------------------
# 5. zero candidates + zero observations with correct schemas => reconciliation PASS
# ---------------------------------------------------------------------------

def test_zero_candidates_zero_observations_correct_schema_reconciles(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    cands_df = _empty_df(FULL_KEY_METADATA)
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)

    status = mgr.persist_collection(cands_df, obs_df, _telemetry())
    assert status["candidate_disposition_reconciliation"]["passed"] is True
    assert status["status"] == "SUCCESS"


def test_reconcile_zero_and_zero_with_correct_schema_passes_directly():
    cand_df = _empty_df(CANDIDATE_KEY_COLUMNS)
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)
    report = reconcile_candidate_dispositions(cand_df, obs_df)
    assert report["passed"] is True
    assert report["candidates"] == 0
    assert report["observations"] == 0


# ---------------------------------------------------------------------------
# 6. zero candidates + malformed empty observations => FAIL
# ---------------------------------------------------------------------------

def test_zero_candidates_malformed_empty_observations_fails_at_persist(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    cands_df = _empty_df(FULL_KEY_METADATA)
    obs_df = pd.DataFrame()  # no columns at all -- the exact "columnless empty" case

    with pytest.raises(ValueError, match="MISSING_OBSERVATION_KEY_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


def test_reconcile_zero_candidates_malformed_observations_fails_directly():
    """Proves the identity 'zero candidates == zero observations' cannot be reached by a
    malformed (columnless) observations_df -- reconciliation is not vacuous at n_cand==0."""
    cand_df = _empty_df(CANDIDATE_KEY_COLUMNS)
    obs_df = pd.DataFrame()
    report = reconcile_candidate_dispositions(cand_df, obs_df)
    assert report["passed"] is False
    assert report["observations"] == 0  # the count identity alone would have looked fine


# ---------------------------------------------------------------------------
# 7. non-empty candidate key may not shrink via intersection
# ---------------------------------------------------------------------------

def test_nonempty_candidate_key_does_not_shrink_via_intersection():
    """Historical hole: key_cols was derived from columns present on BOTH sides. A
    candidates_df missing regime_start_ns/checkpoint_index used to silently reconcile on
    observation_ts alone instead of failing closed."""
    cand_df = pd.DataFrame([
        {"observation_ts": 1, "some_feature": 0.5},
        {"observation_ts": 2, "some_feature": 0.6},
    ])
    obs_df = pd.DataFrame([
        {"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0, "disposition": "LABELED_POSITIVE"},
        {"observation_ts": 2, "regime_start_ns": 0, "checkpoint_index": 1, "disposition": "LABELED_NEGATIVE"},
    ])
    report = reconcile_candidate_dispositions(cand_df, obs_df)
    assert report["passed"] is False
    assert any("candidates dataframe missing" in f for f in report["findings"])


def test_nonempty_reconciliation_still_passes_with_full_key_present():
    """Sanity: the fix does not break the legitimate full-key reconciliation path."""
    cand_df = pd.DataFrame([
        {"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0},
        {"observation_ts": 2, "regime_start_ns": 0, "checkpoint_index": 1},
    ])
    obs_df = pd.DataFrame([
        {"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0, "disposition": "LABELED_POSITIVE"},
        {"observation_ts": 2, "regime_start_ns": 0, "checkpoint_index": 1, "disposition": "LABELED_NEGATIVE"},
    ])
    report = reconcile_candidate_dispositions(cand_df, obs_df)
    assert report["passed"] is True
    assert report["undisposed_candidates"] == 0
    assert report["orphaned_observations"] == 0
    assert report["duplicate_observations"] == 0


# ---------------------------------------------------------------------------
# 8. duplicate columns still fail at zero rows
# ---------------------------------------------------------------------------

def test_zero_row_duplicate_candidate_columns_fail(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    cands_df = _empty_df(FULL_KEY_METADATA)
    cands_df.columns = ["observation_ts", "regime_start_ns", "checkpoint_index", "close", "close"]  # dup
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)

    with pytest.raises(ValueError, match="DUPLICATE_OUTPUT_COLUMNS"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


def test_zero_row_duplicate_observation_columns_fail(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    cands_df = _empty_df(FULL_KEY_METADATA)
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)
    obs_df.columns = ["observation_ts", "regime_start_ns", "regime_start_ns"]  # dup

    with pytest.raises(ValueError, match="DUPLICATE_OUTPUT_COLUMNS"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


# ---------------------------------------------------------------------------
# 9. real-smoke non-zero requirement remains in validate_smoke.py, not duplicated
# ---------------------------------------------------------------------------

def test_real_smoke_zero_candidate_guard_lives_only_in_validate_smoke():
    src = (REPO_ROOT / "scripts" / "validate_smoke.py").read_text(encoding="utf-8")
    assert "0 candidates emitted for expected smoke date" in src

    om_src = (REPO_ROOT / "backtests" / "nt_runtime" / "output_manager.py").read_text(encoding="utf-8")
    assert "0 candidates emitted for expected smoke date" not in om_src


def test_output_manager_never_requires_nonzero_candidates(tmp_path: Path):
    """D1.4: OutputManager must accept a genuinely empty, well-formed collection as
    SUCCESS -- the productive-smoke requirement belongs solely to validate_smoke.py."""
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    status = mgr.persist_collection(_empty_df(FULL_KEY_METADATA), _empty_df(CANDIDATE_KEY_COLUMNS), _telemetry())
    assert status["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 10. existing non-empty UNEXPECTED_OUTPUT_COLUMN behavior remains unchanged pending D2
# ---------------------------------------------------------------------------

def test_nonempty_unexpected_output_column_still_rejected(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=FULL_KEY_METADATA)
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "close": 1.0, "atr": 1.0, "some_undeclared_registry_feature": 0.5,
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])

    with pytest.raises(ValueError, match="UNEXPECTED_OUTPUT_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


def test_nonempty_declared_features_still_required_in_full_and_order(tmp_path: Path):
    """Unrelated to D1: this is D2's territory (features.source / feature_list). D1 must
    not have altered this pre-existing behavior."""
    mgr = _output_manager(
        tmp_path, metadata_columns=FULL_KEY_METADATA,
        feature_list=["feat_a", "feat_b"],
        feature_list_sha256="0" * 64,
    )
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "close": 1.0, "atr": 1.0, "feat_a": 0.1,  # feat_b missing
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])

    with pytest.raises(ValueError, match="mismatch frozen StudySpec contract"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())
