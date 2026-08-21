import pytest

from features.registry import FEATURE_REGISTRY
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation import phase0
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.execution import authorize_stage


def test_phase0_authenticates_actual_config_and_clean_registry_inventory():
    manifest = phase0.authenticate()
    assert manifest["authenticated"]
    assert manifest["config"]["oos_year"] == 2024
    assert manifest["config"]["train_years"] == [2021, 2022, 2023]
    assert manifest["candidate_count"] >= 25
    assert manifest["study_yaml_sha256"]
    assert manifest["collection_input_allowlist"]["years"] == [2021, 2022, 2023, 2024]
    assert all(FEATURE_REGISTRY[name].status == "verified" for name in manifest["candidate_features"])


def test_phase0_rejects_noncentral_implementation(monkeypatch):
    candidate = phase0.verified_numeric_candidates()[0]
    definition = FEATURE_REGISTRY[candidate]
    monkeypatch.setattr(definition, "implementation", "studies.fake.module")
    with pytest.raises(RuntimeError, match="not importable|escapes central features tree"):
        phase0._implementation_path(candidate)


def test_phase0_execution_authorization_refuses_missing_stale_and_altered_manifest(tmp_path):
    manifest_path = tmp_path / "phase0.json"
    with pytest.raises(RuntimeError, match="missing"):
        phase0.authorize_execution(manifest_path)
    phase0.write_manifest(manifest_path)
    assert phase0.authorize_execution(manifest_path)["authenticated"]
    manifest_path.write_text("{}")
    with pytest.raises(RuntimeError, match="stale or altered"):
        phase0.authorize_execution(manifest_path)


def test_stage_authorization_refuses_forbidden_year_for_collection_freeze_and_fit(tmp_path):
    manifest_path = tmp_path / "phase0.json"
    phase0.write_manifest(manifest_path)
    for stage in ("collection", "feature_freeze", "fit"):
        assert authorize_stage(manifest_path, stage, [2021, 2024])["authenticated"]
        with pytest.raises(RuntimeError, match="forbidden"):
            authorize_stage(manifest_path, stage, [2025])
