"""RT-06 -- an unknown population qualification key cannot compile/seal silently.

``PopulationSpec.qualification`` was ``Dict[str, Any]``: the collector consumed a fixed
subset and any other authored key was silently ignored. It is now a typed, closed
``PopulationQualificationSpec`` (``extra="forbid"``) whose per-field ``exclude_if`` keeps
``model_dump`` byte-identical to the old dict, so no existing study's ``spec_sha256``
moves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research.schemas.study_spec import (
    PopulationQualificationSpec,
    PopulationSpec,
    StudySpec,
)

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# unknown key rejection
# --------------------------------------------------------------------------- #
def test_unknown_qualification_key_is_rejected():
    with pytest.raises(Exception) as ei:
        PopulationSpec.model_validate(
            {"qualification": {"age_gate_seconds": 120, "totally_made_up_key": 3}}
        )
    assert "totally_made_up_key" in str(ei.value)


def test_known_established_filter_keys_accepted():
    q = PopulationQualificationSpec.model_validate(
        {"established": True, "age_gate_seconds": 120, "cadence_seconds": 5,
         "running_mfe_atr_gte": 1.0, "new_progress_windows_gte": 2, "retained_mfe_ratio_gte": 0.5}
    )
    assert q.age_gate_seconds == 120


def test_identity_allowlist_and_analysis_slice_keys_accepted():
    q = PopulationQualificationSpec.model_validate(
        {"required_checkpoint_identities_path": "artifacts/pop.parquet",
         "required_checkpoint_identities_sha256": "a" * 64,
         "population_version": "V1", "selection": "one_first_crossing_per_regime",
         "stage1_score_threshold_source": "x", "stage1_score_threshold_derivation": "TRAIN_ONLY",
         "primary_maturity_buckets": ["300-600s"], "diagnostic_maturity_buckets": ["<300s"],
         "maturity_role": "population_slice_only_never_a_model_input"}
    )
    assert q.required_checkpoint_identities_path.endswith("pop.parquet")


def test_identity_allowlist_not_combinable_with_established_filter():
    with pytest.raises(Exception, match="MUTUALLY_EXCLUSIVE"):
        PopulationQualificationSpec.model_validate(
            {"required_checkpoint_identities_path": "x", "required_checkpoint_identities_sha256": "a" * 64,
             "age_gate_seconds": 120}
        )


# --------------------------------------------------------------------------- #
# hash neutrality
# --------------------------------------------------------------------------- #
def test_typed_qualification_is_hash_neutral_vs_plain_dict():
    plain = {"age_gate_seconds": 120, "established": True, "cadence_seconds": 5}
    typed = PopulationQualificationSpec.model_validate(plain).model_dump(exclude_none=False)
    assert json.dumps(typed, sort_keys=True) == json.dumps(plain, sort_keys=True)


@pytest.mark.parametrize("study_id", [
    "clean_maturity_flip_model_180s_horizon",
    "workflow_canary_ordered_barrier_v1",
    "deep_pullback_5s_reacceleration_model",
    "clean_maturity_flip_model_rolling_productivity",
    "reconstructed_long_rth_strict_retrain",
])
def test_existing_study_spec_hash_unchanged(study_id):
    study = REPO / "studies" / study_id
    if not (study / "study.yaml").is_file():
        pytest.skip(study_id)
    spec = StudySpec.model_validate(yaml.safe_load((study / "study.yaml").read_text()))
    compiled = json.loads((study / "compiled_study.json").read_text())
    assert spec.compute_sha256() == compiled["spec_sha256"]


def test_clean_tradable_reversal_all_keys_recognized():
    """The study with the most qualification keys still validates -- every key it authors
    is a declared field, not silently ignored."""
    study = REPO / "studies" / "clean_tradable_reversal"
    if not (study / "study.yaml").is_file():
        pytest.skip("clean_tradable_reversal")
    StudySpec.model_validate(yaml.safe_load((study / "study.yaml").read_text()))
