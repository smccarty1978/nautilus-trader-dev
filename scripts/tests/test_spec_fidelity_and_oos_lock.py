"""Unit Tests for SPEC Fidelity Gate, Forbidden Lineage Guard, and OOS Phase Lock.
=============================================================================
"""

import json
import pytest
from pathlib import Path
import yaml

from research.schemas.study_spec import StudySpec
from research.study_types.flip_prediction import FlipPredictionCompiler
from scripts.check_spec_fidelity import check_spec_fidelity
from scripts.generate_oos_unlock import generate_oos_unlock, verify_oos_unlock_token
from backtests.nt_runtime.compiled_study_loader import load_compiled_study
from backtests.nt_runtime.data_plan import resolve_data_plan, UnauthorizedExecutionDomainError


def test_forbidden_feature_lineage_rejected(tmp_path):
    spec_data = {
        "study": {
            "id": "test_forbidden_f3_study",
            "type": "flip_prediction",
            "risk_tier": 2,
            "description": "Test forbidden lineage rejection",
        },
        "operation": {"kind": "train_evaluate"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state", "prevailing_regime": "both", "session": "RTH"},
        "target": {"type": "flip", "direction": "both", "horizon_seconds": 300},
        "features": {
            "source_key": "F3_top25_gbt_v1",
            "forbidden_lineage": ["F3_selected", "F3_top25_gbt_v1"],
            "feature_list": ["atr"],
        },
        "model": {"family": "HistGradientBoostingClassifier"},
        "chronology": {"train": [2021, 2022, 2023], "dev": [2024], "prohibited": [2025, 2026]},
        "stratification": {"buckets": [[300, 600], [600, 900], [900, 1800]]},
        "lineage": {"clean_lineage_start": "2026-08-15T00:45:00Z", "invalidated_prior_runs": [{"id": 1}]},
        "execution": {"runtime": "nautilustrader"},
    }
    spec = StudySpec.model_validate(spec_data)
    compiler = FlipPredictionCompiler()
    with pytest.raises(ValueError, match="FORBIDDEN_FEATURE_LINEAGE"):
        compiler.compile(spec)


def test_spec_fidelity_100_percent_on_gemini_study():
    study_dir = Path("studies/Gemini_clean_maturity_flip_rolling_5m_productivity")
    if not study_dir.exists():
        pytest.skip("Study directory not found")
    report = check_spec_fidelity(study_dir)
    assert report["verdict"] == "PASS"
    assert report["spec_clause_coverage_pct"] == 100.0
    assert report["unmapped_required_clauses_count"] == 0


def test_oos_lock_blocks_2024_access_without_token():
    study_dir = Path("studies/Gemini_clean_maturity_flip_rolling_5m_productivity")
    if not study_dir.exists():
        pytest.skip("Study directory not found")

    compiled_data = load_compiled_study(study_dir)

    # Attempting to resolve data plan for 2024 without oos_unlock.json must fail closed
    with pytest.raises(UnauthorizedExecutionDomainError, match="OOS_LOCKED_UNTIL_FREEZE"):
        resolve_data_plan(compiled_data, start_date="2024-03-04", end_date="2024-03-04")
