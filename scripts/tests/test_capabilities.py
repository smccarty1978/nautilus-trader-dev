"""Generated capability registry (research_workflow.capabilities)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_workflow import capabilities as cap

REPO = Path(__file__).resolve().parents[2]
REQUIRED_FIELDS = {"id", "kind", "version", "parameters", "dependencies", "update_cadence", "cost_class", "status", "implementation", "required_tests"}


@pytest.fixture(scope="module")
def registry():
    return cap.build_registry(REPO)


def test_every_kind_is_present_and_entries_carry_the_contract(registry):
    assert set(registry["kinds"]) == set(cap.KINDS)
    for kind, rows in registry["kinds"].items():
        for e in rows:
            assert REQUIRED_FIELDS <= set(e), (kind, e["id"], REQUIRED_FIELDS - set(e))
            assert e["cost_class"] in {"per_1s", "per_source_event", "per_candidate", "on_demand", "offline_only"}


def test_features_are_introspected_from_the_active_bundle(registry):
    feats = registry["kinds"]["features"]
    assert len(feats) >= 100
    e = cap.describe(registry, "feature.regime_efficiency")
    assert e and e["parameters"] == ["bar_state", "context", "timeframe"] and e["update_cadence"] == "per_source_bar"
    assert e["implementation"].startswith("features.trackers.") and e["implementation_exists"] is True


def test_datasets_and_streams_come_from_dataset_specs(registry):
    ids = {e["id"] for e in registry["kinds"]["datasets"]}
    assert {"dataset.NQ_v0_2020_2026", "dataset.ES_v0_2020_2026", "dataset.YM_v0_2024"} <= ids
    s = cap.describe(registry, "stream.NQ_v0_2020_2026.5m")
    assert s and "stream.NQ_v0_2020_2026.1m" in s["dependencies"]


def test_no_benchmark_fields_in_the_registry(registry):
    for e in cap.entries(registry):
        assert not any(k.startswith("benchmark") or k.startswith("last_verified") for k in e)


def test_seeded_entries_are_verified_or_marked_broken(registry):
    seeded = [e for k in ("trackers", "trigger_primitives", "outcomes", "entry_references", "model_drivers", "validation_protocols") for e in registry["kinds"][k]]
    assert seeded
    for e in seeded:
        # `candidate` is the capability-flow status for scaffolded/promotable primitives and for
        # non-executable entry references; it never claims a verified implementation.
        assert e["status"] in {"verified", "broken", "candidate"}
        if e["status"] == "verified":
            assert e["implementation_verified"] and not e["missing_tests"]


def test_ids_unique_and_dependencies_resolve(registry):
    ids = [e["id"] for e in cap.entries(registry)]
    assert len(ids) == len(set(ids))
    unresolved = {e["id"]: e["unresolved_dependencies"] for e in cap.entries(registry) if e["unresolved_dependencies"]}
    assert unresolved == {}, unresolved


def test_search_and_describe(registry):
    hits = cap.search(registry, "ordered_barrier")
    assert any(h["id"] == "outcome.ordered_barrier" for h in hits)
    assert cap.describe(registry, "nope.missing") is None


def test_generate_and_check_roundtrip(tmp_path: Path):
    path = tmp_path / "registry.json"
    reg = cap.generate(path=path)
    assert json.loads(path.read_text())["content_sha256"] == reg["content_sha256"]
    assert cap.generate(check=True, path=path)["content_sha256"] == reg["content_sha256"]
    stale = json.loads(path.read_text()); stale["content_sha256"] = "0" * 64; path.write_text(json.dumps(stale))
    with pytest.raises(RuntimeError, match="CAPABILITY_REGISTRY_STALE"):
        cap.generate(check=True, path=path)


def test_committed_registry_is_current():
    cap.generate(check=True)


def test_cli_list_describe_search(capsys):
    assert cap.cli(SimpleNamespace(cmd="list", kind="outcomes", status=None)) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1]); assert out["STATUS"] == "OK" and out["count"] >= 3
    assert cap.cli(SimpleNamespace(cmd="describe", capability_id="feature.regime_efficiency")) == 0
    assert cap.cli(SimpleNamespace(cmd="search", text="regime")) == 0
    assert cap.cli(SimpleNamespace(cmd="list", kind="bogus", status=None)) == 2
