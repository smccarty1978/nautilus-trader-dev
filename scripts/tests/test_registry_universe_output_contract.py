"""Regression tests for Phase 1 Packet D2 (registry-universe non-empty output contract).

Covers:
  - features.registry.resolve_source_universe: the shared "existing registry authority"
    resolver for features.source, matching the pre-existing phase0.py authentication
  - OutputManager.persist_collection: a study collecting from a registry-defined
    universe (features.source set, features.feature_list still null) can now persist a
    real, non-empty candidate surface without UNEXPECTED_OUTPUT_COLUMN
  - the representative collector's metadata authority is single-sourced
  - D1 strictness (zero-row schema, full candidate key) is preserved
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtests.nt_runtime.compiled_study_loader import CompiledStudyData
from backtests.nt_runtime.data_plan import DataPlan
from backtests.nt_runtime.output_manager import CANDIDATE_KEY_COLUMNS, OutputManager
from backtests.nt_runtime.run_plan import RunPlan, RunStage
from backtests.nt_runtime.telemetry import CausalTelemetry
from features.registry import FEATURE_REGISTRY, resolve_source_universe
from research.schemas.study_spec import StudySpec

REPO_ROOT = Path(__file__).resolve().parents[2]
CLEAN_FLIP_STUDY = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"

REGISTRY_UNIVERSE = resolve_source_universe("verified_registry_numeric_universe")
VALID_FEATURE_A = REGISTRY_UNIVERSE[0]
VALID_FEATURE_B = REGISTRY_UNIVERSE[1]
NON_UNIVERSE_REGISTERED_FEATURE = next(
    n for n in FEATURE_REGISTRY if n not in set(REGISTRY_UNIVERSE)
)

CLEAN_FLIP_METADATA = [
    "observation_ts", "regime_start_ns", "checkpoint_index",
    "regime_age_seconds", "running_mfe_atr", "new_progress_windows", "retained_mfe_ratio",
]


# ---------------------------------------------------------------------------
# Shared harness -- mirrors scripts/tests/test_output_manager_zero_row.py's, extended
# with a `source` parameter.
# ---------------------------------------------------------------------------

def _spec(metadata_columns, source=None, feature_list=None, feature_list_sha256=None):
    study_dict = {
        "study": {
            "id": "d2_registry_universe_test", "type": "flip_prediction", "risk_tier": 2,
            "description": "D2 registry-universe output-contract harness study.",
        },
        "operation": {"kind": "train_evaluate", "target_metric": "pr_auc"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {
            "type": "regime_state", "prevailing_regime": "bullish", "session": "RTH",
            "qualification": {"age_gate_seconds": 300, "established": True},
        },
        "target": {"type": "flip", "event": "confirmed_flip", "direction": "bearish", "horizon_seconds": 300},
        "features": {
            "source": source,
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


def _output_manager(tmp_path: Path, metadata_columns, source=None, feature_list=None, feature_list_sha256=None) -> OutputManager:
    spec = _spec(metadata_columns, source, feature_list, feature_list_sha256)
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


def _empty_df(columns):
    return pd.DataFrame(columns=columns)


# ---------------------------------------------------------------------------
# 1. features.source resolves the representative registry universe
# ---------------------------------------------------------------------------

def test_resolve_source_universe_matches_phase0_authentication():
    from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.phase0 import (
        verified_numeric_candidates,
    )
    assert resolve_source_universe("verified_registry_numeric_universe") == verified_numeric_candidates()
    assert len(REGISTRY_UNIVERSE) >= 25


def test_resolve_source_universe_none_is_a_noop():
    assert resolve_source_universe(None) == []
    assert resolve_source_universe("") == []


def test_resolve_source_universe_unknown_fails_closed():
    with pytest.raises(ValueError, match="UNKNOWN_FEATURE_SOURCE"):
        resolve_source_universe("some_typo_source")


# ---------------------------------------------------------------------------
# 2. valid registry-universe candidate DataFrame persists
# ---------------------------------------------------------------------------

def test_valid_registry_feature_candidate_persists(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6, VALID_FEATURE_A: 0.1, VALID_FEATURE_B: 0.2,
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0, "disposition": "LABELED_POSITIVE"}])

    status = mgr.persist_collection(cands_df, obs_df, _telemetry())
    assert status["status"] == "SUCCESS"
    assert status["feature_surface_validation"]["passed"] is True


def test_all_declared_registry_features_can_be_represented(tmp_path: Path):
    """A wide, legitimate registry-universe collection (many features at once) persists."""
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    row = {
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6,
    }
    sample = REGISTRY_UNIVERSE[:50]
    row.update({name: 0.5 for name in sample})
    cands_df = pd.DataFrame([row])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])

    status = mgr.persist_collection(cands_df, obs_df, _telemetry())
    assert status["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 3. undeclared/non-registry feature still fails
# ---------------------------------------------------------------------------

def test_non_registry_column_still_fails_unexpected_output_column(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6, "totally_made_up_column_xyz": 1.0,
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])

    with pytest.raises(ValueError, match="UNEXPECTED_OUTPUT_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


def test_registered_but_out_of_universe_feature_still_fails(tmp_path: Path):
    """A real registered feature that is NOT in the declared collection universe (e.g.
    unverified or non-numeric) must still be rejected -- registration alone is not
    membership in the declared source."""
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6, NON_UNIVERSE_REGISTERED_FEATURE: 1.0,
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])

    with pytest.raises(ValueError, match="UNEXPECTED_OUTPUT_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


def test_no_declared_source_does_not_widen_allowed_columns(tmp_path: Path):
    """A study without a declared source gets no collection-universe widening --
    backward compatible with pre-D2 behaviour."""
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source=None)
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6, VALID_FEATURE_A: 0.1,
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])

    with pytest.raises(ValueError, match="UNEXPECTED_OUTPUT_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


# ---------------------------------------------------------------------------
# 4. metadata_columns comes from canonical contract; required metadata passes
# ---------------------------------------------------------------------------

def test_required_metadata_passes_with_declared_contract(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6,
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])
    status = mgr.persist_collection(cands_df, obs_df, _telemetry())
    assert status["status"] == "SUCCESS"


def test_undeclared_metadata_column_still_rejected(tmp_path: Path):
    """A column that is neither declared metadata nor a collection-universe feature nor
    a frozen feature must still fail -- D2 widens the feature surface, not metadata."""
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6, "some_undeclared_bookkeeping_field": "x",
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])
    with pytest.raises(ValueError, match="UNEXPECTED_OUTPUT_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


@pytest.mark.skipif(not (CLEAN_FLIP_STUDY / "compiled_study.json").exists(), reason="CleanFlip study absent")
def test_clean_flip_study_declares_metadata_columns_in_contract():
    with open(CLEAN_FLIP_STUDY / "compiled_study.json", "r", encoding="utf-8") as f:
        import json
        compiled = json.load(f)
    declared = compiled["spec"]["features"]["metadata_columns"]
    assert declared == CLEAN_FLIP_METADATA
    for key_col in CANDIDATE_KEY_COLUMNS:
        assert key_col in declared


# ---------------------------------------------------------------------------
# 5. duplicate collector declared_metadata authority is removed
# ---------------------------------------------------------------------------

def test_collector_no_longer_hardcodes_its_own_metadata_list():
    src = (CLEAN_FLIP_STUDY / "implementation" / "collector.py").read_text(encoding="utf-8")
    # The old inline literal that used to live inside get_candidates_dataframe.
    assert '"regime_direction", "checkpoint_index"' not in src
    assert "self._metadata_columns" in src
    assert "metadata_columns: tuple[str, ...]" in src  # single declared authority, on the config


def test_collect_mode_wires_metadata_columns_generically():
    src = (REPO_ROOT / "backtests" / "nt_runtime" / "modes" / "collect.py").read_text(encoding="utf-8")
    assert '"metadata_columns"' in src
    assert "spec.features.metadata_columns" in src


# ---------------------------------------------------------------------------
# 6. empty collector DataFrame uses canonical metadata/key schema
# ---------------------------------------------------------------------------

def test_real_collector_empty_candidates_dataframe_uses_config_schema():
    from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import (
        CleanFlipCollector, CleanFlipCollectorConfig,
    )
    collector = CleanFlipCollector.__new__(CleanFlipCollector)
    collector._metadata_columns = CleanFlipCollectorConfig().metadata_columns
    collector.candidates_log = []
    df = collector.get_candidates_dataframe()
    assert df.empty
    assert list(df.columns) == list(CleanFlipCollectorConfig().metadata_columns)
    for key_col in CANDIDATE_KEY_COLUMNS:
        assert key_col in df.columns


# ---------------------------------------------------------------------------
# 8. full candidate key remains required (D1 not regressed)
# ---------------------------------------------------------------------------

def test_candidate_key_still_required_alongside_registry_features(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    cands_df = pd.DataFrame([{
        "observation_ts": 1,  # regime_start_ns, checkpoint_index missing
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6, VALID_FEATURE_A: 0.1,
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])
    with pytest.raises(ValueError, match="MISSING_OUTPUT_METADATA|MISSING_CANDIDATE_KEY_COLUMN"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


def test_zero_row_registry_universe_study_still_structurally_strict(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    cands_df = _empty_df(["observation_ts", "regime_start_ns"])  # missing checkpoint_index + rest
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)
    with pytest.raises(ValueError, match="MISSING_OUTPUT_METADATA"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


def test_zero_row_registry_universe_study_passes_with_correct_schema(tmp_path: Path):
    mgr = _output_manager(tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe")
    cands_df = _empty_df(CLEAN_FLIP_METADATA)
    obs_df = _empty_df(CANDIDATE_KEY_COLUMNS)
    status = mgr.persist_collection(cands_df, obs_df, _telemetry())
    assert status["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 9. later frozen feature_list remains unset/unmodified as designed
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (CLEAN_FLIP_STUDY / "compiled_study.json").exists(), reason="CleanFlip study absent")
def test_clean_flip_frozen_feature_list_still_unset():
    import json
    with open(CLEAN_FLIP_STUDY / "compiled_study.json", "r", encoding="utf-8") as f:
        compiled = json.load(f)
    assert compiled["spec"]["features"]["feature_list"] is None
    assert compiled["spec"]["features"]["feature_list_sha256"] is None
    assert compiled["spec"]["features"]["source"] == "verified_registry_numeric_universe"


def test_frozen_feature_list_strict_order_check_unaffected_by_collection_universe(tmp_path: Path):
    """D2.9: a declared frozen feature_list still requires exact ordered identity --
    collection_universe never substitutes for it."""
    mgr = _output_manager(
        tmp_path, metadata_columns=CLEAN_FLIP_METADATA, source="verified_registry_numeric_universe",
        feature_list=[VALID_FEATURE_A, VALID_FEATURE_B], feature_list_sha256="0" * 64,
    )
    cands_df = pd.DataFrame([{
        "observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0,
        "regime_age_seconds": 150.0, "running_mfe_atr": 1.2, "new_progress_windows": 3,
        "retained_mfe_ratio": 0.6, VALID_FEATURE_A: 0.1,  # VALID_FEATURE_B missing
    }])
    obs_df = pd.DataFrame([{"observation_ts": 1, "regime_start_ns": 0, "checkpoint_index": 0}])
    with pytest.raises(ValueError, match="mismatch frozen StudySpec contract"):
        mgr.persist_collection(cands_df, obs_df, _telemetry())


# ---------------------------------------------------------------------------
# 10. compiled_study reflects the contract values
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (CLEAN_FLIP_STUDY / "compiled_study.json").exists(), reason="CleanFlip study absent")
def test_compiled_study_spec_hash_matches_recompiled_study_yaml():
    from backtests.nt_runtime.compiled_study_loader import load_compiled_study
    # Raises StaleCompiledStudyError if study.yaml and compiled_study.json disagree.
    data = load_compiled_study(CLEAN_FLIP_STUDY)
    assert data.spec.features.metadata_columns == CLEAN_FLIP_METADATA
    assert data.spec.features.source == "verified_registry_numeric_universe"
