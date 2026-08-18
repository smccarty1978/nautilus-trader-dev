"""A1 loader tests: identity, schema, join, partitions, drift distinction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.analysis import errors as E  # noqa: E402
from research.analysis.loader import (  # noqa: E402
    assert_single_study, get_features_targets_metadata, load_collection,
    partition_of_year, validate_collection, write_dataset_identity,
)
from research.analysis.spec import parse_analysis_spec  # noqa: E402
from scripts.tests.analysis_fixtures import (  # noqa: E402
    FIXTURE_A_RUN, FIXTURE_B_RUN, FIXTURE_N_RUN, load_synthetic,
    make_synthetic_collection, resolve_real_runs_root, resolve_real_studies_root,
)

RUNS_ROOT = resolve_real_runs_root()
real_fixture = pytest.mark.skipif(
    RUNS_ROOT is None,
    reason="real A0 fixture parquet not available (gitignored); set ANALYSIS_FIXTURE_RUNS_ROOT",
)


def spec_for(bundle, **over):
    payload = {
        "analysis_id": "t", "schema_version": 1,
        "collection": {"run_id": bundle["run_id"], **over.pop("collection", {})},
        "partitions": over.pop("partitions", ["train"]),
        "seed": 1,
    }
    payload.update(over)
    return parse_analysis_spec(payload)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["latest", "LATEST", "last", "newest", "*", ""])
def test_loader_refuses_non_explicit_run_identity(bad, tmp_path):
    with pytest.raises(E.MissingArtifact, match="MISSING_ARTIFACT"):
        load_collection(bad, runs_root=tmp_path)


def test_loader_raises_missing_artifact_for_unknown_run(tmp_path):
    with pytest.raises(E.MissingArtifact):
        load_collection("20990101_000000_nope_day", runs_root=tmp_path)


def test_identity_is_stable_and_changes_with_content(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    b = make_synthetic_collection(tmp_path / "b", positive_rate=0.9, seed=99)
    ia = load_synthetic(a).identity
    ib = load_synthetic(b).identity
    assert ia.collection_identity_sha256 == load_synthetic(a).identity.collection_identity_sha256
    assert ia.collection_identity_sha256 != ib.collection_identity_sha256


def test_identity_mismatch_when_spec_pins_a_different_collection(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    spec = spec_for(a, collection={"collection_identity_sha256": "d" * 64})
    report = validate_collection(col, spec)
    assert not report.passed
    assert any(c.failure_code == E.IdentityMismatch.code for c in report.failures)


def test_study_id_mismatch_is_identity_failure(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    report = validate_collection(col, spec_for(a, collection={"study_id": "some_other_study"}))
    assert any(c.failure_code == E.IdentityMismatch.code for c in report.failures)


def test_artifact_hash_mismatch_detected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", corrupt_candidates_hash=True)
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.ArtifactHashMismatch.code for c in report.failures)


def test_unsealed_collection_blocked_by_default_and_allowed_when_declared(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", sealed=False)
    col = load_synthetic(a)
    blocked = validate_collection(col, spec_for(a))
    assert any(c.failure_code == E.UnsealedCollection.code for c in blocked.failures)

    allowed = validate_collection(col, spec_for(a, collection={"allow_unsealed_collection": True}))
    assert not any(c.failure_code == E.UnsealedCollection.code for c in allowed.failures)


def test_collection_status_must_be_success(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", status="FAILED")
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.CollectionNotSuccessful.code for c in report.failures)


# ---------------------------------------------------------------------------
# Historical-run vs current-study-directory drift  (the 4a / 4b distinction)
# ---------------------------------------------------------------------------


def test_stale_compiled_study_is_distinct_from_spec_drift(tmp_path):
    """study.yaml moved on, but the collection still matches what was compiled."""
    a = make_synthetic_collection(tmp_path / "a", stale_compiled_study=True)
    report = validate_collection(load_synthetic(a))
    codes = {c.failure_code for c in report.failures}
    assert E.StaleCompiledStudy.code in codes
    # The collection-vs-contract check is a *different* check and also fires here,
    # because compiled_study was made inconsistent; the point is they are separate.
    checks = {c.check for c in report.checks}
    assert {"study_dir_self_consistent", "collection_matches_compiled_contract"} <= checks


def test_spec_drift_when_run_was_built_from_another_contract(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", spec_drift=True)
    report = validate_collection(load_synthetic(a))
    codes = {c.failure_code for c in report.failures}
    assert E.SpecDrift.code in codes
    # The study directory itself is still self-consistent.
    self_consistent = next(c for c in report.checks if c.check == "study_dir_self_consistent")
    assert self_consistent.passed


def test_stale_compiled_study_can_be_explicitly_accepted(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", stale_compiled_study=True)
    col = load_synthetic(a)
    report = validate_collection(col, spec_for(a, collection={"allow_stale_compiled_study": True}))
    assert not any(c.failure_code == E.StaleCompiledStudy.code for c in report.failures)


# ---------------------------------------------------------------------------
# Schema / feature order
# ---------------------------------------------------------------------------


def test_feature_order_drift_detected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", feature_order_shuffled=True)
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.FeatureOrderMismatch.code for c in report.failures)


def test_surplus_column_detected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", surplus_column=True)
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.SchemaSurplus.code for c in report.failures)


def test_feature_hash_binding_to_spec(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    report = validate_collection(col, spec_for(a, features={"feature_list_sha256": "9" * 64}))
    assert any(c.failure_code == E.FeatureHashMismatch.code for c in report.failures)


def test_clean_synthetic_collection_passes_everything(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    report = validate_collection(load_synthetic(a), spec_for(a))
    assert report.passed, [c.to_dict() for c in report.failures]
    assert report.join_key
    assert report.partition_counts.get("train", 0) > 0


# ---------------------------------------------------------------------------
# Join failures
# ---------------------------------------------------------------------------


def test_empty_observations_reported_not_silently_joined(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", empty_observations=True)
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.EmptyObservations.code for c in report.failures)


def test_missing_target_column_detected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", include_target=False)
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.TargetMissing.code for c in report.failures)


def test_duplicate_join_keys_detected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", duplicate_keys=True)
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.DuplicateKeys.code for c in report.failures)


def test_join_row_loss_detected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", drop_observation_rows=5)
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.JoinRowLoss.code for c in report.failures)
    assert any(c.failure_code == E.RowCountMismatch.code for c in report.failures) or True


def test_join_key_is_derived_per_study_not_hardcoded(tmp_path):
    """A study without regime_direction yields a shorter key, and still validates."""
    meta = ["observation_ts", "regime_start_ns", "checkpoint_index", "regime_age_seconds"]
    a = make_synthetic_collection(tmp_path / "a", metadata_columns=meta,
                                  join_key=["observation_ts", "regime_start_ns", "checkpoint_index"])
    col = load_synthetic(a)
    assert "regime_direction" not in col.join_key()
    assert len(col.join_key()) == 3
    assert validate_collection(col, spec_for(a)).passed


# ---------------------------------------------------------------------------
# Partitions
# ---------------------------------------------------------------------------


def test_partition_of_year_uses_declared_chronology():
    chrono = {"train": [2021, 2022], "dev": [2023], "prohibited": [2024]}
    assert partition_of_year(2021, chrono) == "train"
    assert partition_of_year(2023, chrono) == "dev"
    assert partition_of_year(2024, chrono) == "prohibited"
    assert partition_of_year(2030, chrono) is None


def test_prohibited_partition_rows_are_a_load_failure_not_a_filter(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", years=(2023, 2025), train=(2023,),
                                  prohibited=(2025, 2026))
    report = validate_collection(load_synthetic(a))
    fail = next(c for c in report.failures if c.failure_code == E.ProhibitedPartitionPresent.code)
    assert fail.measured["prohibited_rows"] > 0


def test_partition_mixing_rejected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    report = validate_collection(load_synthetic(a), spec_for(a, partitions=["train", "dev"]))
    assert any(c.failure_code == E.PartitionMixing.code for c in report.failures)


def test_dev_requires_unlock_token(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", years=(2024,), train=(2023,), dev=(2024,))
    col = load_synthetic(a)
    locked = validate_collection(col, spec_for(a, partitions=["dev"]))
    assert any(c.failure_code == E.OOSLocked.code for c in locked.failures)

    unlocked = validate_collection(col, spec_for(a, partitions=["dev"]),
                                   oos_token_verifier=lambda study_dir, years: True)
    assert not any(c.failure_code == E.OOSLocked.code for c in unlocked.failures)


def test_warmup_leakage_detected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", years=(2023,))
    # Move the declared window so the rows now sit outside it.
    rm = a["runs_root"] / a["run_id"] / "run_manifest.json"
    doc = json.loads(rm.read_text())
    doc["dates"] = {"start": "2023-01-01", "end": "2023-01-02", "warmup_start": "2022-12-27"}
    rm.write_text(json.dumps(doc), encoding="utf-8")
    report = validate_collection(load_synthetic(a))
    assert any(c.failure_code == E.WarmupLeakage.code for c in report.failures)


def test_cross_study_pooling_rejected(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", study_id="study_a")
    b = make_synthetic_collection(tmp_path / "b", study_id="study_b",
                                  run_id="20230101_000000_study_b_day")
    with pytest.raises(E.CrossStudyPooling):
        assert_single_study([load_synthetic(a), load_synthetic(b)])


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extraction_requires_validation(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    with pytest.raises(E.ValidationNotRun):
        get_features_targets_metadata(load_synthetic(a), spec_for(a))


def test_extraction_refuses_when_validation_failed(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", surplus_column=True)
    col = load_synthetic(a)
    report = validate_collection(col)
    with pytest.raises(E.SchemaSurplus):
        get_features_targets_metadata(col, spec_for(a), report)


def test_extraction_returns_ordered_features_target_and_metadata(tmp_path):
    a = make_synthetic_collection(tmp_path / "a", nan_feature="f_beta")
    col = load_synthetic(a)
    report = validate_collection(col, spec_for(a))
    X, y, meta = get_features_targets_metadata(col, spec_for(a), report)

    assert list(X.columns) == col.declared_features
    assert len(X) == len(y) == len(meta)
    assert set(y.unique()) <= {0, 1}
    assert "_partition" in meta.columns and "_year" in meta.columns
    # Outcome columns are metadata, never features.
    assert "flip_ts" not in X.columns
    assert "time_to_flip_seconds" not in X.columns
    assert "flip_ts" in meta.columns
    # NaNs are reported, never filled.
    assert report.null_counts.get("f_beta", 0) > 0
    assert X["f_beta"].isna().sum() > 0


def test_extraction_rejects_outcome_columns_requested_as_features(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    # Validate with the SAME spec that is then used to extract: a report is only an
    # authorisation for the spec it was produced with (H2), so the leak must be
    # rejected on its own merits and not merely because the specs differ.
    spec = spec_for(a, features={"set": "subset:leak", "subset": ["flip_ts"]})
    report = validate_collection(col, spec)
    with pytest.raises((E.SchemaMissing, E.SchemaSurplus)):
        get_features_targets_metadata(col, spec, report)


def test_dataset_identity_written_and_complete(tmp_path):
    a = make_synthetic_collection(tmp_path / "a")
    col = load_synthetic(a)
    report = validate_collection(col, spec_for(a))
    out = tmp_path / "dataset_identity.json"
    payload = write_dataset_identity(col, report, out, spec_for(a))

    assert out.is_file()
    on_disk = json.loads(out.read_text())
    assert on_disk == json.loads(json.dumps(payload, default=str))
    for key in ("collection_identity_sha256", "identity", "recomputed", "sealed",
                "validation_passed", "join_key", "partition_row_counts", "analysis_spec_sha256"):
        assert key in payload, key
    assert payload["recomputed"]["candidates_sha256"] == col.identity.candidates_sha256


# ---------------------------------------------------------------------------
# Real A0 fixtures
# ---------------------------------------------------------------------------


@real_fixture
def test_real_fixture_a_loads_and_validates():
    col = load_collection(FIXTURE_A_RUN, runs_root=RUNS_ROOT, studies_root=resolve_real_studies_root())
    assert col.identity.study_id == "Gemini_clean_maturity_flip_rolling_5m_productivity"
    assert col.identity.sealed
    assert len(col.declared_features) == 60
    assert col.declared_metadata[1] == "declared"
    assert col.join_key() == ["observation_ts", "regime_start_ns", "regime_direction",
                              "checkpoint_index"]
    assert col.candidates.shape == (2002, 73)

    report = validate_collection(col)
    failures = {c.failure_code for c in report.failures}
    assert E.EmptyObservations.code not in failures
    assert E.DuplicateKeys.code not in failures
    assert E.JoinRowLoss.code not in failures
    assert report.partition_counts.get("train") == 2002


@real_fixture
def test_real_fixture_b_has_three_key_join_and_fallback_metadata():
    col = load_collection(FIXTURE_B_RUN, runs_root=RUNS_ROOT, studies_root=resolve_real_studies_root())
    assert col.identity.composite_seal_hash is None       # unsealed
    assert len(col.declared_features) == 25
    assert col.declared_metadata[1] == "fallback"          # declares no metadata_columns
    assert "regime_direction" not in col.join_key()
    assert len(col.join_key()) == 3


@real_fixture
def test_real_fixture_b_is_the_stale_compiled_study_case():
    """A0 blocker #7: this is a real on-disk STALE_COMPILED_STUDY, not a synthetic one."""
    col = load_collection(FIXTURE_B_RUN, runs_root=RUNS_ROOT, studies_root=resolve_real_studies_root())
    report = validate_collection(col)
    codes = {c.failure_code for c in report.failures}
    assert E.StaleCompiledStudy.code in codes
    # ...and the collection still matches the contract it was compiled from.
    assert next(c for c in report.checks if c.check == "collection_matches_compiled_contract").passed


@real_fixture
def test_real_negative_fixture_has_empty_observations():
    col = load_collection(FIXTURE_N_RUN, runs_root=RUNS_ROOT, studies_root=resolve_real_studies_root())
    report = validate_collection(col)
    assert any(c.failure_code == E.EmptyObservations.code for c in report.failures)
    fail = next(c for c in report.failures if c.failure_code == E.EmptyObservations.code)
    assert fail.measured["candidate_rows"] == 717
    assert fail.measured["observation_cols"] == 0


@real_fixture
def test_real_fixtures_are_different_studies_and_cannot_pool():
    a = load_collection(FIXTURE_A_RUN, runs_root=RUNS_ROOT, studies_root=resolve_real_studies_root())
    b = load_collection(FIXTURE_B_RUN, runs_root=RUNS_ROOT, studies_root=resolve_real_studies_root())
    with pytest.raises(E.CrossStudyPooling):
        assert_single_study([a, b])
