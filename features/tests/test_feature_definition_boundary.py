"""``features.registry`` is a registration boundary -- proven, not asserted.

Two conditions define a registration boundary (``docs/RESEARCH_WORKFLOW.md`` §21.14):

1. it exposes a stable resolution API that consumers import, and
2. it discovers registered capabilities through the declared capability index, never by
   statically importing them.

Condition 2 is the load-bearing one.  If the resolver statically imported the definitions,
reachability would be unchanged and the split would have bought nothing:
``test_resolver_does_not_statically_import_any_definition_module`` pins it against the same AST
walk the platform's own execution closure uses, and
``test_no_consumer_reaches_a_definition_module`` pins it for the five modules the surface
measurement is about.

``test_golden_resolution`` is the proof that consumers cannot be affected: every registered
name -- 693 physical catalogue entries, 41 canonical definitions, 36 legacy instance aliases,
every declared parameter value of every definition, every universe/alias surface and every
fail-closed error -- resolves to exactly what the committed golden recorded before the split.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import features.registry as R
from features.tests.golden_feature_resolution import GOLDEN_PATH, build, manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOUNDARY = "features/registry.py"
# The canonical catalogue is a package of one record module per definition (feature promotion,
# 2026-09): every record is a definition module for the reachability conditions below.
DEFINITION_MODULES = {"features/definitions/physical_catalogue.py", "features/definitions/canonical/__init__.py",
                      "features/definitions/legacy_instances.py"} | {
    p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "features" / "definitions" / "canonical").glob("*.py")
    if p.name != "__init__.py"}
# The consumers whose reachability is the whole point (modularity report, B2 escalation table).
CONSUMERS = ("research_workflow/provider_host.py", "research_workflow/forward_outcomes/guard.py",
             "research_workflow/output_manager.py", "backtests/nt_runtime/modes/collect.py",
             "research_workflow/generic_collector.py", "research_workflow/grammar/compiler.py",
             "research_workflow/phase0.py")


def _static_imports(rel: str) -> set[str]:
    from research_workflow.grammar.compiler import _static_imports as walk
    return walk(rel, REPO_ROOT)


def _closure(seeds) -> set[str]:
    from research_workflow.grammar.compiler import transitive_closure_files
    return transitive_closure_files(set(seeds), REPO_ROOT)


# --------------------------------------------------------------------------- #
# F1 -- golden resolution
# --------------------------------------------------------------------------- #
def test_golden_resolution():
    """Every existing feature binding resolves identically to the pre-split golden."""
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    current = manifest(build())
    if current == golden:
        return
    detail = []
    for key in sorted(set(golden["verbatim"]) | set(current["verbatim"])):
        if golden["verbatim"].get(key) != current["verbatim"].get(key):
            detail.append(f"verbatim section {key!r} moved")
    for section in sorted(set(golden["digests"]) | set(current["digests"])):
        a, b = golden["digests"].get(section, {}), current["digests"].get(section, {})
        moved = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        if moved:
            detail.append(f"{section}: {len(moved)} moved, first={moved[:5]}")
    pytest.fail("feature resolution moved:\n  " + "\n  ".join(detail) + "\nRegenerate with "
                "`python -m features.tests.golden_feature_resolution --full <path>` and justify every line.")


# --------------------------------------------------------------------------- #
# boundary condition 2 -- discovery is through the index, not the import graph
# --------------------------------------------------------------------------- #
def test_resolver_does_not_statically_import_any_definition_module():
    reached = _static_imports(BOUNDARY)
    assert not (reached & DEFINITION_MODULES), (
        f"{BOUNDARY} statically imports {sorted(reached & DEFINITION_MODULES)}: the boundary is an "
        "assertion, not a fact -- reachability is unchanged and nothing was gained"
    )


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_no_consumer_reaches_a_definition_module(consumer):
    """A consumer depends on the resolver's interface, never on which definitions are registered."""
    reached = _closure([consumer])
    assert not (reached & DEFINITION_MODULES), (
        f"{consumer} reaches {sorted(reached & DEFINITION_MODULES)}; adding a feature definition "
        "would put it back on that consumer's blast radius"
    )
    assert BOUNDARY in reached, f"{consumer} should still reach the resolver it resolves through"


def test_definition_modules_are_reachable_only_through_the_index():
    """No repo module outside the definitions package statically imports a definition catalogue."""
    offenders = []
    for path in REPO_ROOT.rglob("*.py"):
        parts = path.relative_to(REPO_ROOT).parts
        if "__pycache__" in parts or parts[0] in ("studies", "artifacts", "scratch") or "tests" in parts:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in DEFINITION_MODULES or rel.startswith("features/definitions/"):
            continue
        if _static_imports(rel) & DEFINITION_MODULES:
            offenders.append(rel)
    assert offenders == [], f"static importers of a feature-definition catalogue: {offenders}"


# --------------------------------------------------------------------------- #
# the index is the registration, and the closure still covers what it covered
# --------------------------------------------------------------------------- #
def test_declared_modules_match_the_definition_files():
    declared = R.declared_definition_modules()
    assert declared == ("features.definitions.physical_catalogue", "features.definitions.canonical",
                        "features.definitions.legacy_instances")
    files = set(R.definition_files())
    # every definition module, plus the promotion evidence that decides which records resolve
    # as verified (golden fixtures + promotion records): both are part of what a study binds
    assert DEFINITION_MODULES <= files
    from features.promotion import evidence_files
    assert set(evidence_files()) <= files
    assert files - DEFINITION_MODULES - set(evidence_files()) == set()


def test_generated_registry_carries_the_definition_modules():
    from research_workflow.capabilities import load_registry
    entries = {e["id"]: e for e in load_registry()["kinds"]["feature_definitions"]}
    assert {e["implementation"] for e in entries.values()} == set(R.declared_definition_modules())
    assert all(e["status"] == "verified" for e in entries.values()), entries


def test_compiler_closure_still_covers_every_definition_module():
    """Seeded explicitly, because the import walk cannot see a dynamically resolved module.

    Editing a feature definition must stale a study's freeze exactly as it did when the
    definitions lived inside ``features/registry.py``.
    """
    covered = _closure({BOUNDARY, *R.definition_files()})
    assert DEFINITION_MODULES <= covered
    assert "features/definitions/providers.py" in covered, "shared provider identities dropped out"
    assert "features/feature_types.py" in covered


def test_an_empty_or_unreadable_index_fails_closed(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("trackers: []\n", encoding="utf-8")
    with pytest.raises(R.FeatureInstanceError, match="FEATURE_DEFINITION_INDEX_EMPTY"):
        R.declared_definition_modules(empty)
    with pytest.raises(R.FeatureInstanceError, match="FEATURE_DEFINITION_INDEX_UNREADABLE"):
        R.declared_definition_modules(tmp_path / "does_not_exist.yaml")


def test_definition_catalogues_are_still_reachable_by_their_historical_names():
    """Consumers and historical tests read these off the module; module ``__getattr__`` serves them."""
    from features.definitions import canonical as CAT
    assert len(R.FEATURE_REGISTRY) == 693
    # one record file per canonical definition (41 migrated + every evidence-promoted addition)
    assert len(R.CANONICAL_FEATURE_DEFINITIONS) == len(CAT.record_files()) >= 41
    assert len(R.LEGACY_FEATURE_INSTANCE_OVERRIDES) == 36
    assert R.FEATURE_REGISTRY is R.FEATURE_REGISTRY          # one merged catalogue, not a rebuild per access
    with pytest.raises(AttributeError):
        R.NOT_A_CATALOGUE


def test_a_definition_module_declaring_nothing_is_refused(monkeypatch, tmp_path):
    """Fail-closed: a module registered as a catalogue that contributes none is a broken tree."""
    index = tmp_path / "index.yaml"
    index.write_text("feature_definitions:\n  - id: feature_definitions.empty\n"
                     "    implementation: features.definitions.providers\n", encoding="utf-8")
    monkeypatch.setattr(R, "_INDEX_PATH", index)
    monkeypatch.setattr(R, "_CATALOGUES", None)
    with pytest.raises(R.FeatureInstanceError, match="FEATURE_DEFINITION_MODULE_EMPTY"):
        R._catalogues()
    monkeypatch.setattr(R, "_CATALOGUES", None)


def test_an_unimportable_definition_module_is_refused(monkeypatch, tmp_path):
    index = tmp_path / "index.yaml"
    index.write_text("feature_definitions:\n  - id: feature_definitions.gone\n"
                     "    implementation: features.definitions.definitely_not_there\n", encoding="utf-8")
    monkeypatch.setattr(R, "_INDEX_PATH", index)
    monkeypatch.setattr(R, "_CATALOGUES", None)
    with pytest.raises(R.FeatureInstanceError, match="FEATURE_DEFINITION_MODULE_UNRESOLVED"):
        R._catalogues()
    monkeypatch.setattr(R, "_CATALOGUES", None)
