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


def test_generic_collector_now_dispatches_the_population_runtime():
    caps = collector_runtime_capabilities("research_workflow.generic_collector.GenericStudyCollector")
    # Stage 2: the flag AND a real dispatch path are both required.
    assert caps["declares_episode_lifecycle"] is True
    assert caps["dispatches_population_runtime"] is True
    assert caps["supports_episode_lifecycle"] is True


class _StubCollectorNoDispatch:
    """A collector that declares the flag but never drives the population runtime."""
    SUPPORTS_EPISODE_LIFECYCLE = True


def test_declaration_alone_does_not_satisfy_the_episode_gate(tmp_path, monkeypatch):
    import research_workflow.runtime_bindings as rb
    monkeypatch.setattr(rb, "_load_collector_class", lambda _sc: _StubCollectorNoDispatch)
    study = tmp_path / "s"
    study.mkdir()
    (study / "compiled_study.json").write_text(json.dumps({
        "spec": {"execution": {"strategy_class": "x.Stub"}},
        "contracts": {
            "population_contract": {"episode_lifecycle": {
                "arm_condition": {"kind": "directional_adverse_excursion", "threshold_atr": 1.0,
                                  "price_source": "completed_1s_intrabar"},
                "required_event": {"kind": "direction_relation", "source": "completed_5s_regime",
                                   "bar_state": "completed",
                                   "availability_timestamp": "completed_source_bar_ts_init",
                                   "relation": "opposite_prevailing", "active_at_arm_counts": True},
                "emit_condition": {"kind": "direction_transition", "source": "completed_5s_regime",
                                   "bar_state": "completed",
                                   "availability_timestamp": "completed_source_bar_ts_init",
                                   "from_relation": "opposite_prevailing",
                                   "to_relation": "aligned_prevailing", "strictly_after_arm": True},
                "rearm_on": ["new_favorable_extreme"], "terminate_on": ["prevailing_regime_flip"],
                "max_candidates_per_episode": 1,
            }},
            "feature_contract": {"resolved_feature_instances": []},
        },
    }))
    result = verify_runtime_contract(study)
    assert result["passed"] is False
    prims = {m["primitive"] for m in result["missing"]}
    assert "population_contract.episode_lifecycle" in prims
    episode_miss = next(m for m in result["missing"] if m["primitive"] == "population_contract.episode_lifecycle")
    assert "does not dispatch" in episode_miss["reason"]


def test_non_episode_population_passes(tmp_path):
    study = tmp_path / "s"
    study.mkdir()
    (study / "compiled_study.json").write_text(json.dumps({
        "spec": {"execution": {}},
        "contracts": {"population_contract": {}, "feature_contract": {"resolved_feature_instances": []}},
    }))
    assert verify_runtime_contract(study)["passed"] is True


def test_real_deep_pullback_study_episode_binding_is_satisfied():
    study = Path(__file__).resolve().parents[2] / "studies" / "deep_pullback_5s_reacceleration_model"
    if not (study / "compiled_study.json").is_file():
        pytest.skip("deep_pullback study is not scaffolded in this tree")
    result = verify_runtime_contract(study)
    assert result["checked"]["episode_lifecycle_declared"] is True
    # Stage 2: the episode primitive is now bound; no episode_lifecycle miss remains.
    assert "population_contract.episode_lifecycle" not in {m["primitive"] for m in result["missing"]}
    assert result["checked"]["provider_host_bindings"] == {"required": 34, "bound": 34}


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


def test_target_runtime_binding_is_proven_and_unknown_target_blocks(tmp_path):
    study = tmp_path / "s"; study.mkdir()
    payload = {"spec": {"execution": {}}, "contracts": {"population_contract": {},
        "feature_contract": {"resolved_feature_instances": []}, "target_contract": {"primitive": "ordered_barrier"}}}
    (study / "compiled_study.json").write_text(json.dumps(payload))
    ok = verify_runtime_contract(study)
    assert ok["passed"] and ok["checked"]["target_runtime"]["runtime"] == "OrderedBarrierTargetRuntime"
    payload["contracts"]["target_contract"]["primitive"] = "not_a_target"
    (study / "compiled_study.json").write_text(json.dumps(payload))
    failed = verify_runtime_contract(study)
    assert failed["passed"] is False
    assert "TARGET_RUNTIME_MISMATCH" in failed["missing"][0]["reason"]


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
