"""The runtime-contract binding gate: a declared population_contract.episode_lifecycle
must resolve to an executable runtime component, or preflight fails closed with
RUNTIME_CONTRACT_BINDING_MISSING. (Per-feature value coverage is proven empirically by
the smoke validator's RUNTIME_FEATURE_BINDING_MISSING / EPISODE_POPULATION_NOT_GATED.)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_workflow.runtime_bindings import (
    collector_runtime_capabilities,
    verify_runtime_contract,
)


def test_generic_collector_does_not_support_episode_lifecycle():
    caps = collector_runtime_capabilities("research_workflow.generic_collector.GenericStudyCollector")
    assert caps["supports_episode_lifecycle"] is False


def test_episode_lifecycle_without_collector_support_is_missing_binding(tmp_path):
    study = tmp_path / "s"
    study.mkdir()
    (study / "compiled_study.json").write_text(json.dumps({
        "spec": {"execution": {}},
        "contracts": {
            "population_contract": {"episode_lifecycle": {"max_candidates_per_episode": 1}},
            "feature_contract": {"resolved_feature_instances": []},
        },
    }))
    result = verify_runtime_contract(study)
    assert result["passed"] is False
    assert {m["primitive"] for m in result["missing"]} == {"population_contract.episode_lifecycle"}
    assert result["missing"][0]["required_binding"] == (
        "research_workflow.episode_population.EpisodePopulationEngine"
    )


def test_non_episode_population_passes(tmp_path):
    study = tmp_path / "s"
    study.mkdir()
    (study / "compiled_study.json").write_text(json.dumps({
        "spec": {"execution": {}},
        "contracts": {"population_contract": {}, "feature_contract": {"resolved_feature_instances": []}},
    }))
    assert verify_runtime_contract(study)["passed"] is True


def test_real_deep_pullback_study_is_blocked_on_episode_binding():
    study = Path(__file__).resolve().parents[2] / "studies" / "deep_pullback_5s_reacceleration_model"
    if not (study / "compiled_study.json").is_file():
        pytest.skip("deep_pullback study is not scaffolded in this tree")
    result = verify_runtime_contract(study)
    assert result["passed"] is False
    assert result["checked"]["episode_lifecycle_declared"] is True
    assert "population_contract.episode_lifecycle" in {m["primitive"] for m in result["missing"]}


def test_existing_non_episode_studies_are_not_regressed():
    import glob
    root = Path(__file__).resolve().parents[2]
    checked = 0
    for cs in glob.glob(str(root / "studies" / "*" / "compiled_study.json")):
        data = json.loads(Path(cs).read_text())
        pc = (data.get("contracts") or {}).get("population_contract") or {}
        if pc.get("episode_lifecycle"):
            continue
        r = verify_runtime_contract(Path(cs).parent)
        assert r["passed"], f"{Path(cs).parent.name}: {r['missing']}"
        checked += 1
    if checked == 0:
        pytest.skip("no non-episode compiled study in tree")


def test_preflight_required_checks_include_runtime_binding():
    from research_workflow.preflight import REQUIRED_STUDY_CHECKS
    assert "RUNTIME_CONTRACT_BINDING" in REQUIRED_STUDY_CHECKS


def test_episode_study_is_provider_host_mode_and_all_features_bind():
    study = Path(__file__).resolve().parents[2] / "studies" / "deep_pullback_5s_reacceleration_model"
    if not (study / "compiled_study.json").is_file():
        pytest.skip("deep_pullback study is not scaffolded in this tree")
    result = verify_runtime_contract(study)
    assert result["checked"]["runtime_feature_mode"] == "provider_host"
    phb = result["checked"]["provider_host_bindings"]
    assert phb == {"required": 34, "bound": 34}
    # every remaining miss is the episode primitive, never a feature instance
    assert all(m["primitive"] == "population_contract.episode_lifecycle" for m in result["missing"])


def test_non_episode_studies_never_run_the_provider_host_check():
    import glob
    root = Path(__file__).resolve().parents[2]
    for cs in glob.glob(str(root / "studies" / "*" / "compiled_study.json")):
        data = json.loads(Path(cs).read_text())
        pc = (data.get("contracts") or {}).get("population_contract") or {}
        if pc.get("episode_lifecycle"):
            continue
        checked = verify_runtime_contract(Path(cs).parent)["checked"]
        assert checked["runtime_feature_mode"] == "legacy_runtime"
        assert checked["provider_host_bindings"] is None
