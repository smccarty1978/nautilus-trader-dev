"""Feature definition promotion: a definition is verified by evidence about itself (features/promotion.py).

Gates from the promotion packet, each proven adversarially where it can be:

* P1  the rehearsal's feature (``structural_max_expansion_checkpoint_atr``) promotes and compiles;
* P4  a definition with no golden values, values that do not match, a forged record, or evidence
      that drifted after promotion is REFUSED -- at verify, at resolution and at compile;
* P5  a promoted feature cannot silently replace a differently-named one (bundle shadowing, alias
      collision, physical-alias collision are refused);
* determinism and the causal guard are executed, not asserted.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from features import promotion as P
from features import registry as R
from features.registry import FeatureInstance, FeatureInstanceError

REPO_ROOT = Path(__file__).resolve().parents[2]
NAME = "structural_max_expansion_checkpoint_atr"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Copies of the evidence directories the module may mutate, with the registry cache reset."""
    golden = tmp_path / "golden"; promos = tmp_path / "promotions"
    shutil.copytree(P.GOLDEN_DIR, golden); shutil.copytree(P.PROMOTIONS_DIR, promos)
    monkeypatch.setattr(P, "GOLDEN_DIR", golden)
    monkeypatch.setattr(P, "PROMOTIONS_DIR", promos)
    R.invalidate_promotion_cache()
    yield {"golden": golden, "promotions": promos}
    R.invalidate_promotion_cache()


def _fixture(sandbox) -> dict:
    return json.loads((sandbox["golden"] / f"{NAME}.json").read_text(encoding="utf-8"))


def _write_fixture(sandbox, fixture: dict) -> None:
    (sandbox["golden"] / f"{NAME}.json").write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_active():
    return R.resolve_feature_instances("canonical_verified_definition_universe",
                                       (FeatureInstance(NAME, {"context": "current"}),))[0]


# --------------------------------------------------------------------------- P1
def test_the_rehearsal_feature_verifies_against_hand_derived_values():
    evidence = P.verify(NAME)
    assert evidence["physical_aliases"] == [NAME]
    assert evidence["determinism"] == {"runs": 2, "identical": True}
    assert evidence["causal_guard"] == "SNAPSHOT_BEFORE_LATEST_RUNTIME_EVENT"
    assert evidence["consumed_streams"] == ["completed_1m", "completed_1s", "completed_5m"]
    assert set(evidence["consumed_streams"]) <= set(evidence["declared_input_contracts"])


def _rehearsal_spec(study_id: str) -> dict:
    """The rehearsal composition (artifacts/platform_v2/rehearsal), with the withdrawn instance restored."""
    return {
        "study": {"id": study_id, "tier": 2, "question": "does the checkpoint normalisation compile"},
        "streams": [{"dataset": "NQ_1S_V2_GLOBEX", "timeframes": ["1s", "1m"]}],
        "context": {"regime_1m": {"tracker": "regime.dual_ema", "timeframe": "1m"},
                    "excursion": {"tracker": "regime.excursion", "bars": "1s", "regime": "regime_1m"},
                    "regime_bar_5m": {"tracker": "regime_bar.calendar_bucket", "bucket": "5m", "bars": "1m", "regime": "regime_1m"}},
        "population": {"session": "RTH", "cadence": {"every": "5s", "anchor": "regime_1m.start_ns", "max_age": "1800s"},
                       "qualify": "excursion.frozen_atr > 0 and regime_1m.age_s >= 120s and features.structural_snapshot_ready",
                       "direction": "regime_1m.dir", "anchor_identity": "regime_1m.start_ns"},
        "triggers": "every_candidate",
        "features": {"instances": [{"feature": "regime_efficiency", "over": {"timeframe": ["1m", "5m"]}, "context": "prior"},
                                   {"feature": "rolling_giveback_atr", "window": "300s", "update_every": "1s"},
                                   {"feature": "structural_max_expansion_atr", "context": "current"},
                                   {"feature": NAME, "context": "current"}],
                     "bindings": {"completed_5m": {"tracker": "regime_bar_5m", "ready_gate": False},
                                  "snapshot": {"atr": "regime_1m.atr", "family_a_atr": "excursion.frozen_atr",
                                               "episode_state": {"prevailing_direction": "regime_1m.dir"}}}},
        "outcome": {"kind": "label", "event": "regime_1m.flipped", "horizon": "300s", "direction": "regime_1m.dir", "session_end": "censor"},
        "chronology": {"train": [2023], "dev": [2024], "prohibited": [2020, 2021, 2022, 2025, 2026], "authorized_dates": ["2023-03-01"]},
    }


def test_the_rehearsal_feature_resolves_verified_and_compiles():
    resolved = _resolve_active()
    assert resolved["status"] == "verified" and resolved["physical_alias"] == NAME
    assert NAME in R.resolve_source_universe("canonical_verified_definition_universe")
    from research_workflow.grammar.compiler import compile_study
    out = compile_study(_rehearsal_spec("p1_feature_promotion"))
    assert out.ok, out.gaps.to_dict()
    inst = {i["physical_alias"]: i for i in out.plan.features["instances"]}
    assert inst[NAME]["status"] == "verified"
    assert inst[NAME]["provider"].endswith("GenericStructuralGeometryProvider")
    proof = [b for b in out.plan.binding_proof if b["kind"] == "feature" and b["id"] == NAME]
    assert proof and proof[0]["bound"] is True
    closure = set(out.plan.closure["files"])
    assert {f"features/definitions/canonical/{NAME}.py", f"features/definitions/golden/{NAME}.json",
            f"features/definitions/promotions/{NAME}.json", "features/promotion.py"} <= closure


# --------------------------------------------------------------------------- P4
def test_no_golden_values_is_refused(sandbox):
    (sandbox["golden"] / f"{NAME}.json").unlink()
    with pytest.raises(P.FeaturePromotionRefused, match="GOLDEN_FIXTURE_MISSING"):
        P.verify(NAME)
    # the stale record no longer hashes to a fixture -> the definition is provisional again
    with pytest.raises(FeatureInstanceError, match="UNVERIFIED_CANONICAL_FEATURE"):
        _resolve_active()


def test_wrong_golden_values_are_refused(sandbox):
    fixture = _fixture(sandbox)
    fixture["snapshots"][1]["expected"][NAME] = 30.0   # the frozen-ATR sibling's value: a substituted normaliser
    _write_fixture(sandbox, fixture)
    with pytest.raises(P.FeaturePromotionRefused, match="GOLDEN_VALUE_MISMATCH"):
        P.verify(NAME)
    with pytest.raises(P.FeaturePromotionRefused):
        P.promote(NAME)
    assert not P.check_record(NAME)["passed"]          # the old record no longer binds the edited fixture
    with pytest.raises(FeatureInstanceError, match="UNVERIFIED_CANONICAL_FEATURE"):
        _resolve_active()


def test_a_forged_record_is_refused_at_compile(sandbox):
    """Hashes made to match the tree, but the evidence never ran (observed digest is invented)."""
    record = json.loads((sandbox["promotions"] / f"{NAME}.json").read_text(encoding="utf-8"))
    record["observed_sha256"] = "0" * 64
    (sandbox["promotions"] / f"{NAME}.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    R.invalidate_promotion_cache()
    # hash binding alone cannot tell: resolution admits it ...
    assert _resolve_active()["status"] == "verified"
    # ... but the compiler re-executes the evidence and refuses with a typed gap
    report = P.check_record(NAME, execute=True)
    assert report["passed"] is False and report["execution_error"] == "PROMOTION_RECORD_OBSERVED_SHA256_STALE"
    from research_workflow.grammar.compiler import compile_study
    out = compile_study(_rehearsal_spec("p4_forged_record"))
    assert not out.ok
    gaps = json.dumps(out.gaps.to_dict())
    assert "FEATURE_PROMOTION_EVIDENCE_INVALID" in gaps and "PROMOTION_RECORD_OBSERVED_SHA256_STALE" in gaps


def test_fixture_without_a_post_snapshot_event_is_refused(sandbox):
    fixture = _fixture(sandbox)
    last = fixture["snapshots"][-1]["decision_ts"]
    from research_workflow.provider_host import _event_avail_ts
    fixture["tape"] = [e for e in fixture["tape"] if (_event_avail_ts(e["type"], e["event"]) or 0) <= last]
    _write_fixture(sandbox, fixture)
    with pytest.raises(P.FeaturePromotionRefused, match="GOLDEN_FIXTURE_NO_POST_SNAPSHOT_EVENT"):
        P.verify(NAME)


def test_fixture_without_a_derivation_is_refused(sandbox):
    fixture = _fixture(sandbox); fixture["derivation"] = ""
    _write_fixture(sandbox, fixture)
    with pytest.raises(P.FeaturePromotionRefused, match="GOLDEN_FIXTURE_INVALID"):
        P.verify(NAME)


def test_provider_drift_after_promotion_demotes_the_definition(sandbox, monkeypatch):
    record = json.loads((sandbox["promotions"] / f"{NAME}.json").read_text(encoding="utf-8"))
    record["provider_sha256"] = "f" * 64   # what a provider edit after promotion looks like to the record
    (sandbox["promotions"] / f"{NAME}.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    R.invalidate_promotion_cache()
    assert "PROMOTION_RECORD_PROVIDER_SHA256_STALE" in P.record_binding_errors(NAME)
    with pytest.raises(FeatureInstanceError, match="UNVERIFIED_CANONICAL_FEATURE"):
        _resolve_active()


# --------------------------------------------------------------------------- P5
def test_a_bundle_identity_cannot_be_shadowed(sandbox):
    """Promoting a catalogue record whose name is a migrated bundle identity is refused."""
    fixture = _fixture(sandbox); fixture["feature"] = "structural_max_expansion_atr"
    fixture["instances"] = [{"parameters": {"context": "current"}}]
    (sandbox["golden"] / "structural_max_expansion_atr.json").write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.raises(P.FeaturePromotionRefused, match="FEATURE_ALREADY_IN_AUTHORITY_BUNDLE"):
        P.verify("structural_max_expansion_atr")


def test_alias_collisions_are_refused():
    from research_workflow.provider_host import InstanceSpec
    spec = InstanceSpec(canonical_name=NAME, parameters={"context": "current"},
                        physical_alias="prior_5m_regime_efficiency",   # an existing legacy alias of another identity
                        canonical_provider="x", required_streams=())
    with pytest.raises(P.FeaturePromotionRefused, match="PHYSICAL_ALIAS_COLLISION"):
        P.check_no_substitution(NAME, [spec])
    with pytest.raises(P.FeaturePromotionRefused, match="FEATURE_NAME_COLLIDES_WITH_ALIAS"):
        P.check_no_substitution("rolling_5m_giveback_atr", [])


def test_promotion_does_not_reach_candidate_or_legacy_authorities():
    assert NAME not in R.resolve_source_universe("canonical_verified_definition_universe", authority="candidate")
    with pytest.raises(FeatureInstanceError):
        R.resolve_feature_request(NAME, {"context": "current"}, authority="candidate")


# --------------------------------------------------------------------------- catalogue as data
def test_catalogue_records_are_one_file_per_definition():
    from features.definitions import canonical as CAT
    files = {Path(f).stem for f in CAT.record_files()}
    assert files == set(R.CANONICAL_FEATURE_DEFINITIONS)
    assert list(R.CANONICAL_FEATURE_DEFINITIONS) == sorted(R.CANONICAL_FEATURE_DEFINITIONS)


def test_a_misnamed_record_fails_the_catalogue_closed(tmp_path, monkeypatch):
    from features.definitions import canonical as CAT
    bad = tmp_path / "canonical"; bad.mkdir()
    (bad / "__init__.py").write_text("", encoding="utf-8")
    (bad / "alpha.py").write_text("from features.feature_types import FeatureDefinition\nDEFINITION = FeatureDefinition(name='beta')\n", encoding="utf-8")
    monkeypatch.setattr(CAT, "_HERE", bad)
    import sys
    sys.path.insert(0, str(tmp_path))
    try:
        monkeypatch.setattr(CAT, "__name__", "canonical")
        with pytest.raises(FeatureInstanceError, match="FEATURE_DEFINITION_RECORD_MISNAMED"):
            CAT._load()
    finally:
        sys.path.remove(str(tmp_path))


def test_every_promotion_record_replays(sandbox):
    report = P.check_all(execute=True)
    assert report["passed"], report
    assert NAME in [r["feature"] for r in report["records"]]
