"""``research.analysis.ops`` is a registration boundary -- proven, not asserted.

Two conditions define a registration boundary (``docs/RESEARCH_WORKFLOW.md`` §21.14):

1. it exposes a stable resolution API that consumers import, and
2. it discovers registered capabilities through the declared capability index, never by
   statically importing them.

Condition 2 is the load-bearing one: if the resolver statically imported the implementations,
reachability would be unchanged and nothing would have been gained.  ``test_boundary_does_not_
statically_import_any_implementation`` and ``test_no_consumer_imports_an_implementation_module``
pin it against the same AST walk the platform's own closure uses.

``test_golden_resolution`` is the proof that consumers cannot be affected: every registered
operation resolves to the same implementation, the same declared inputs and the same context
flag as the committed golden, which was generated before the split.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from research.analysis import ops as ops_api
from research.analysis.tests.golden_analysis_ops import GOLDEN_PATH, build

REPO_ROOT = Path(__file__).resolve().parents[3]
BOUNDARY = "research/analysis/ops.py"
IMPLEMENTATION_MODULES = {"research/analysis/diagnostic_ops.py", "research/analysis/derive_ops.py",
                          "research/analysis/contrast_ops.py"}
CONSUMERS = ("research_workflow/grammar/compiler.py", "research_workflow/lifecycle_v2.py")


def _static_imports(rel: str) -> set[str]:
    """Every repo-local module a file imports anywhere -- the closure walker's own rule."""
    from research_workflow.grammar.compiler import _static_imports as walk
    return walk(rel, REPO_ROOT)


# --------------------------------------------------------------------------- #
# A1 -- golden resolution
# --------------------------------------------------------------------------- #
def test_golden_resolution():
    """Every existing analysis op resolves identically to the pre-split golden."""
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    current = build()
    assert current == golden, (
        "analysis-op resolution moved; regenerate with "
        "`python -m research.analysis.tests.golden_analysis_ops` and justify every line of the diff"
    )


def test_every_registered_op_resolves_to_a_callable():
    for op in sorted(ops_api.known_ops()):
        assert callable(ops_api.op_implementation(op)), op


def test_unknown_op_is_refused_by_name():
    with pytest.raises(ops_api.AnalysisOpError, match="ANALYSIS_OP_UNKNOWN"):
        ops_api.run_op("analysis.definitely.not.registered", None)


def test_missing_declared_input_is_refused_before_the_op_runs():
    with pytest.raises(ops_api.AnalysisOpError, match="ANALYSIS_OP_INPUT_MISSING"):
        ops_api.run_op("analysis.metric.tail_lift", None, params={"score": "s", "label": "y"})


# --------------------------------------------------------------------------- #
# boundary condition 2 -- discovery is through the index, not the import graph
# --------------------------------------------------------------------------- #
def test_boundary_does_not_statically_import_any_implementation():
    reached = _static_imports(BOUNDARY)
    assert not (reached & IMPLEMENTATION_MODULES), (
        f"{BOUNDARY} statically imports {sorted(reached & IMPLEMENTATION_MODULES)}: the boundary is "
        "an assertion, not a fact -- reachability is unchanged and nothing was gained"
    )


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_no_consumer_imports_an_implementation_module(consumer):
    reached = _static_imports(consumer)
    assert not (reached & IMPLEMENTATION_MODULES), (
        f"{consumer} statically imports {sorted(reached & IMPLEMENTATION_MODULES)}; consumers resolve "
        "operations through research.analysis.ops"
    )
    assert BOUNDARY in reached, f"{consumer} should reach the boundary it resolves through"


def test_implementations_are_reachable_only_through_the_index():
    """No repo module outside the implementation's own tests statically imports it."""
    offenders = []
    for path in REPO_ROOT.rglob("*.py"):
        parts = path.relative_to(REPO_ROOT).parts
        if "__pycache__" in parts or parts[0] in ("studies", "artifacts", "scratch", "features") or "tests" in parts:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in IMPLEMENTATION_MODULES:
            continue
        if _static_imports(rel) & IMPLEMENTATION_MODULES:
            offenders.append(rel)
    assert offenders == [], f"static importers of an analysis-op implementation: {offenders}"


def test_no_hand_maintained_registration_table_remains():
    """The registry lives in the index; a table here would rot alongside it."""
    tree = ast.parse((REPO_ROOT / "research/analysis/diagnostic_ops.py").read_text(encoding="utf-8"))
    names = {t.id for node in tree.body if isinstance(node, ast.Assign)
             for t in node.targets if isinstance(t, ast.Name)}
    assert not (names & {"OPS", "OP_INPUTS", "OP_CONTEXT"}), (
        f"diagnostic_ops.py re-grew a hand-maintained op table: {sorted(names & {'OPS', 'OP_INPUTS', 'OP_CONTEXT'})}"
    )


def test_no_exclusion_list_replaces_the_boundary():
    """A3: nothing anywhere names the end-to-end proofs to exempt them from a tier."""
    banned = ("test_supervisor_blackbox", "test_redteam_packet_f")
    offenders = []
    for rel in (BOUNDARY, "research/analysis/diagnostic_ops.py", *CONSUMERS):
        body = (REPO_ROOT / rel).read_text(encoding="utf-8")
        offenders += [f"{rel}:{name}" for name in banned if name in body]
    assert offenders == [], f"hand-maintained exclusion found: {offenders}"


# --------------------------------------------------------------------------- #
# the index is the registration, and it is complete
# --------------------------------------------------------------------------- #
def test_index_and_generated_registry_agree():
    from research_workflow.capabilities import load_registry
    generated = {e["id"]: e for e in load_registry()["kinds"]["analysis_ops"]}
    assert set(generated) == set(ops_api.known_ops())
    for op, entry in generated.items():
        assert tuple(entry.get("inputs") or ()) == ops_api.op_inputs(op), op
        assert bool(entry.get("needs_context")) == (op in ops_api.context_ops()), op


def test_implementation_files_names_the_closure_seed():
    files = ops_api.implementation_files(sorted(ops_api.known_ops()))
    assert set(files) == IMPLEMENTATION_MODULES
    for rel in files:
        assert (REPO_ROOT / rel).is_file()


def test_an_empty_or_unreadable_index_fails_closed(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("trackers: []\n", encoding="utf-8")
    with pytest.raises(ops_api.AnalysisOpError, match="ANALYSIS_OP_INDEX_EMPTY"):
        ops_api.known_ops(empty)
    with pytest.raises(ops_api.AnalysisOpError, match="ANALYSIS_OP_INDEX_UNREADABLE"):
        ops_api.known_ops(tmp_path / "does_not_exist.yaml")


# --------------------------------------------------------------------------- #
# per-boundary index files -- one registration point per kind
# --------------------------------------------------------------------------- #
def test_a_kind_declared_in_two_index_files_is_refused(monkeypatch, tmp_path):
    """One registration point per kind, or a boundary reading its own file could disagree
    with the generated registry without anything noticing."""
    import research_workflow.capabilities as C
    aggregate = tmp_path / "capabilities_index.yaml"
    aggregate.write_text("analysis_ops: []\n", encoding="utf-8")
    extra = tmp_path / "index.d"
    extra.mkdir()
    (extra / "analysis_ops.yaml").write_text("analysis_ops: []\n", encoding="utf-8")
    monkeypatch.setattr(C, "INDEX_PATH", aggregate)
    monkeypatch.setattr(C, "INDEX_DIR", extra)
    with pytest.raises(RuntimeError, match="CAPABILITY_KIND_DECLARED_TWICE"):
        C.read_seed_index()


def test_each_boundary_kind_lives_in_its_own_index_file():
    """A boundary that read the shared index would charge every other kind's edit to
    everything it serves; the surface measurement is only attributable if they are separate."""
    import yaml
    import research_workflow.capabilities as C
    aggregate = yaml.safe_load(C.INDEX_PATH.read_text(encoding="utf-8")) or {}
    assert "analysis_ops" not in aggregate and "feature_definitions" not in aggregate
    for kind, boundary_path in (("analysis_ops", ops_api._INDEX_PATH),
                                ("feature_definitions", None)):
        path = C.INDEX_DIR / f"{kind}.yaml"
        assert path.is_file(), f"{kind} has a boundary but no index file of its own"
        assert set(yaml.safe_load(path.read_text(encoding="utf-8")) or {}) == {kind}
        if boundary_path is not None:
            assert Path(boundary_path) == path
