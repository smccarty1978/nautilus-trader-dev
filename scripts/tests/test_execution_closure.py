"""Adversarial regression tests for the sealed execution closure (Finding A1).

The failed ES acceptance test sealed a manifest that reported ``coverage_pct: 100.0``
while omitting ``features/__init__.py``, ``features/engine.py``, ``features/library.py``,
``features/collector.py`` and ``features/trackers/median_center.py`` -- every one of which
executes as a consequence of ``from features.trackers.wick import WickTracker``, because
Python imports the parent package first and that package's ``__init__`` imports the rest.

These tests are written against a synthetic repository wherever possible, so they assert
the *mechanism* rather than the current shape of this repo's import graph.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.resolve_execution_manifest import (
    ancestor_package_inits,
    compute_ast_closure,
    resolve_declared_dataset_id,
    resolve_execution_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ES_STUDY = REPO_ROOT / "studies" / "es_wick_imbalance_exploratory"
CLEAN_FLIP_STUDY = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"
NQ_DATASET_YAML = REPO_ROOT / "research" / "datasets" / "NQ_v0_2020_2026.yaml"


# ---------------------------------------------------------------------------
# Synthetic-repo mechanism tests
# ---------------------------------------------------------------------------

def _mk(path: Path, body: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """A package whose __init__ pulls in a module nothing else imports.

    ``entry.py`` imports only ``pkg.sub.leaf``. Executing that import also executes
    ``pkg/__init__.py``, which imports ``pkg/side_effect.py``. A closure that follows
    only explicit imports from the entrypoint misses both.
    """
    root = tmp_path / "repo"
    _mk(root / "pkg" / "__init__.py", "from pkg.side_effect import SideEffect\n")
    _mk(root / "pkg" / "side_effect.py", "class SideEffect:\n    pass\n")
    _mk(root / "pkg" / "sub" / "__init__.py", "MARKER = 1\n")
    _mk(root / "pkg" / "sub" / "leaf.py", "def leaf():\n    return 1\n")
    _mk(root / "entry.py", "from pkg.sub.leaf import leaf\n")
    return root


def _closure_rel(seeds, root):
    visited, unresolved = compute_ast_closure(seeds, root)
    return {p.relative_to(root).as_posix() for p in visited}, unresolved


def test_package_init_execution_is_included(fake_repo: Path):
    """A1.1 -- importing pkg.sub.leaf executes pkg/__init__.py and pkg/sub/__init__.py."""
    rel, unresolved = _closure_rel([fake_repo / "entry.py"], fake_repo)
    assert unresolved == []
    assert "pkg/__init__.py" in rel
    assert "pkg/sub/__init__.py" in rel


def test_imports_triggered_from_init_are_included(fake_repo: Path):
    """A1.2 -- pkg/__init__.py's own imports are followed transitively."""
    rel, _ = _closure_rel([fake_repo / "entry.py"], fake_repo)
    assert "pkg/side_effect.py" in rel, (
        "side_effect.py executes via pkg/__init__.py but was not in the closure"
    )


def test_namespace_package_without_init_contributes_nothing(fake_repo: Path):
    """A PEP 420 directory has no __init__ to execute, so none may be invented."""
    _mk(fake_repo / "ns" / "mod.py", "X = 1\n")
    _mk(fake_repo / "entry2.py", "from ns.mod import X\n")
    rel, _ = _closure_rel([fake_repo / "entry2.py"], fake_repo)
    assert "ns/mod.py" in rel
    assert not any(r.startswith("ns/") and r.endswith("__init__.py") for r in rel)


def test_ancestor_inits_ignores_paths_outside_repo(tmp_path: Path):
    """A third-party module is not a repo-local dependency and contributes no inits."""
    outside = tmp_path / "elsewhere" / "mod.py"
    _mk(outside)
    assert ancestor_package_inits(outside, tmp_path / "repo") == []


def test_seed_inside_a_package_pulls_its_own_init(fake_repo: Path):
    """A seed file is itself imported; its package chain executes too."""
    rel, _ = _closure_rel([fake_repo / "pkg" / "sub" / "leaf.py"], fake_repo)
    assert "pkg/__init__.py" in rel
    assert "pkg/sub/__init__.py" in rel


def test_closure_does_not_over_broaden(fake_repo: Path):
    """A1 must not be 'fixed' by sweeping in unrelated repository files."""
    _mk(fake_repo / "unrelated.py", "Y = 2\n")
    _mk(fake_repo / "pkg" / "never_imported.py", "Z = 3\n")
    rel, _ = _closure_rel([fake_repo / "entry.py"], fake_repo)
    assert "unrelated.py" not in rel
    assert "pkg/never_imported.py" not in rel


def test_unresolved_repo_local_import_is_reported(tmp_path: Path):
    """An import into a known repo-local root package that resolves to nothing is unresolved."""
    root = tmp_path / "repo"
    _mk(root / "entry.py", "from features.does_not_exist import Thing\n")
    _visited, unresolved = compute_ast_closure([root / "entry.py"], root)
    assert unresolved, "an unresolvable repo-local import must be reported, not silently dropped"


# ---------------------------------------------------------------------------
# Real-repository tests -- the specific A1 regression
# ---------------------------------------------------------------------------

pytestmark_real = pytest.mark.skipif(
    not (ES_STUDY / "study.yaml").exists(), reason="ES acceptance study not present"
)


@pytest.mark.skipif(not (ES_STUDY / "study.yaml").exists(), reason="ES study absent")
def test_features_engine_and_package_init_are_in_the_real_closure():
    """A1.3 -- the exact files the Red Team found missing must now be sealed."""
    _sha, _fh, md = resolve_execution_manifest(ES_STUDY, REPO_ROOT)
    combined = set(md["combined_files"])
    for required in (
        "repo:features/__init__.py",
        "repo:features/engine.py",
        "repo:features/library.py",
        "repo:features/collector.py",
        "repo:features/trackers/wick.py",
        "repo:features/trackers/median_center.py",
    ):
        assert required in combined, f"{required} executes at collect time but is not sealed"


@pytest.mark.skipif(not (ES_STUDY / "study.yaml").exists(), reason="ES study absent")
def test_changing_an_execution_affecting_file_changes_the_composite(tmp_path: Path):
    """A1.4 -- editing any included file must move the composite.

    ``features/engine.py`` is the specific file that used to be invisible: before the
    fix, mutating it left the composite -- and therefore the seal -- unchanged.
    """
    target = REPO_ROOT / "features" / "engine.py"
    original = target.read_bytes()
    before, _, _ = resolve_execution_manifest(ES_STUDY, REPO_ROOT)
    try:
        target.write_bytes(original + b"\n# execution-affecting edit\n")
        after, _, _ = resolve_execution_manifest(ES_STUDY, REPO_ROOT)
    finally:
        target.write_bytes(original)
    assert before != after, "a change to features/engine.py did not move the composite"

    restored, _, _ = resolve_execution_manifest(ES_STUDY, REPO_ROOT)
    assert restored == before, "composite is not a pure function of file content"


@pytest.mark.skipif(not (ES_STUDY / "study.yaml").exists(), reason="ES study absent")
def test_causal_lint_consumes_the_expanded_closure():
    """A1.5 -- the lint scope is the manifest closure, so it grows with it."""
    import subprocess
    import sys

    out = tmp_json = REPO_ROOT / "scripts" / "tests" / "_lint_scope_probe.json"
    try:
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "causal_lint.py"),
             "--study", str(ES_STUDY), "--json", str(out)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        data = json.loads(out.read_text(encoding="utf-8"))
    finally:
        tmp_json.unlink(missing_ok=True)

    _sha, _fh, md = resolve_execution_manifest(ES_STUDY, REPO_ROOT)
    py_in_closure = [k for k in md["combined_files"] if k.endswith(".py")]
    # The lint excludes a small self-exclusion set; it must nonetheless scan a scope
    # that scales with the closure rather than a fixed, smaller list.
    assert data["files_scanned"] >= len(py_in_closure) - 5
    assert data["files_expected"] >= len(py_in_closure) - 5


@pytest.mark.skipif(not (ES_STUDY / "study.yaml").exists(), reason="ES study absent")
def test_coverage_cannot_report_100_when_a_dependency_is_unresolved(tmp_path: Path):
    """A1.6 -- coverage is denominated by demand, so a gap is visible.

    ``resolved / resolved`` is 100% by construction and can never fall. The check
    injects an unresolvable repo-local import into a file that is genuinely inside the
    closure and asserts both that strict mode refuses and that the observational mode
    reports honest sub-100% coverage.
    """
    from scripts.resolve_execution_manifest import UnresolvedDependencyError

    target = REPO_ROOT / "features" / "engine.py"
    original = target.read_bytes()
    try:
        target.write_bytes(b"from features.no_such_module import Missing\n" + original)

        with pytest.raises(UnresolvedDependencyError):
            resolve_execution_manifest(ES_STUDY, REPO_ROOT)

        _sha, _fh, md = resolve_execution_manifest(ES_STUDY, REPO_ROOT, strict=False)
        assert md["unresolved_dependencies"], "unresolved import was not recorded"
        assert md["coverage_pct"] < 100.0, (
            f"coverage still reads {md['coverage_pct']} with an unresolved dependency"
        )
    finally:
        target.write_bytes(original)


# ---------------------------------------------------------------------------
# Packet A1 -- DatasetSpec closure scoping (RFC section 6.8)
# ---------------------------------------------------------------------------

from scripts.resolve_execution_manifest import resolve_study_files  # noqa: E402


def _mk_synthetic_study(study_dir: Path, dataset_id: str | None) -> None:
    """Minimal mandatory study-contract skeleton for resolve_study_files()."""
    _mk(study_dir / "research_decision.yaml", "id: synthetic\n")
    _mk(study_dir / "SPEC.md", "# synthetic spec\n")
    dataset_line = f"    dataset_id: {dataset_id}\n" if dataset_id else ""
    _mk(
        study_dir / "study.yaml",
        f"execution:\n  data_requirements:\n{dataset_line}",
    )
    _mk(study_dir / "compiled_study.json", "{}\n")
    _mk(study_dir / "artifacts" / "phase0_source_manifest.json", "{}\n")


def test_declared_dataset_id_with_no_authority_yaml_raises(tmp_path: Path):
    """A study that declares a dataset_id with no matching YAML must fail closed."""
    study_dir = tmp_path / "synthetic_study"
    repo_root = tmp_path / "synthetic_repo"
    _mk_synthetic_study(study_dir, dataset_id="MISSING_DATASET")
    with pytest.raises(FileNotFoundError):
        resolve_study_files(study_dir, repo_root)


def test_declared_dataset_id_with_authority_yaml_is_included(tmp_path: Path):
    """The referenced DatasetSpec enters the study-scoped closure under a stable key."""
    study_dir = tmp_path / "synthetic_study"
    repo_root = tmp_path / "synthetic_repo"
    _mk_synthetic_study(study_dir, dataset_id="SYNTH_DATASET")
    _mk(repo_root / "research" / "datasets" / "SYNTH_DATASET.yaml", "dataset_id: SYNTH_DATASET\n")

    files = resolve_study_files(study_dir, repo_root)
    assert "study:dataset:SYNTH_DATASET" in files
    assert files["study:dataset:SYNTH_DATASET"] == (
        repo_root / "research" / "datasets" / "SYNTH_DATASET.yaml"
    ).resolve()


def test_no_declared_dataset_id_adds_nothing(tmp_path: Path):
    """A study that declares no dataset_id is not forced onto DatasetSpec by this packet."""
    study_dir = tmp_path / "synthetic_study"
    repo_root = tmp_path / "synthetic_repo"
    _mk_synthetic_study(study_dir, dataset_id=None)
    files = resolve_study_files(study_dir, repo_root)
    assert not any(k.startswith("study:dataset:") for k in files)


def test_unrelated_dataset_spec_does_not_change_declaring_study_closure(tmp_path: Path):
    """RFC 6.8: editing an unrelated instrument's DatasetSpec must not move this closure."""
    study_dir = tmp_path / "synthetic_study"
    repo_root = tmp_path / "synthetic_repo"
    _mk_synthetic_study(study_dir, dataset_id="SYNTH_DATASET")
    _mk(repo_root / "research" / "datasets" / "SYNTH_DATASET.yaml", "dataset_id: SYNTH_DATASET\n")
    unrelated = _mk(repo_root / "research" / "datasets" / "UNRELATED_DATASET.yaml", "dataset_id: UNRELATED_DATASET\n")

    before = resolve_study_files(study_dir, repo_root)
    unrelated.write_text("dataset_id: UNRELATED_DATASET\nedited: true\n", encoding="utf-8")
    after = resolve_study_files(study_dir, repo_root)

    assert set(before.keys()) == set(after.keys())
    assert not any(k.startswith("study:dataset:UNRELATED") for k in before)


# ---------------------------------------------------------------------------
# Packet A1 -- real-repository regression (Codex_clean_maturity_flip_rolling_5m_productivity)
# ---------------------------------------------------------------------------

_clean_flip_present = (CLEAN_FLIP_STUDY / "study.yaml").exists() and NQ_DATASET_YAML.exists()


@pytest.mark.skipif(not _clean_flip_present, reason="CleanFlip study or NQ DatasetSpec absent")
def test_declared_dataset_id_resolves_for_clean_flip_study():
    assert resolve_declared_dataset_id(CLEAN_FLIP_STUDY) == "NQ_v0_2020_2026"


@pytest.mark.skipif(not _clean_flip_present, reason="CleanFlip study or NQ DatasetSpec absent")
def test_referenced_dataset_spec_is_in_the_real_closure():
    _sha, _fh, md = resolve_execution_manifest(CLEAN_FLIP_STUDY, REPO_ROOT)
    assert "study:dataset:NQ_v0_2020_2026" in md["combined_files"]
    assert "study:dataset:NQ_v0_2020_2026" in md["study_contract_files"]


@pytest.mark.skipif(not _clean_flip_present, reason="CleanFlip study or NQ DatasetSpec absent")
def test_post_freeze_edit_to_referenced_dataset_spec_moves_the_composite():
    """RFC 6.8 acceptance test: editing the referenced DatasetSpec must stale the seal."""
    original = NQ_DATASET_YAML.read_bytes()
    try:
        before, _, _ = resolve_execution_manifest(CLEAN_FLIP_STUDY, REPO_ROOT)
        NQ_DATASET_YAML.write_bytes(original + b"\n# execution-affecting edit\n")
        after, _, _ = resolve_execution_manifest(CLEAN_FLIP_STUDY, REPO_ROOT)
    finally:
        NQ_DATASET_YAML.write_bytes(original)
    assert before != after, "editing the referenced DatasetSpec did not move the composite"

    restored, _, _ = resolve_execution_manifest(CLEAN_FLIP_STUDY, REPO_ROOT)
    assert restored == before, "composite is not a pure function of file content"


@pytest.mark.skipif(not (ES_STUDY / "study.yaml").exists(), reason="ES study absent")
def test_unrelated_study_without_dataset_id_is_unaffected_by_nq_dataset_spec(tmp_path: Path):
    """ES declares no dataset_id; editing the NQ DatasetSpec must not move ES's composite."""
    if not NQ_DATASET_YAML.exists():
        pytest.skip("NQ DatasetSpec absent")
    assert resolve_declared_dataset_id(ES_STUDY) is None

    original = NQ_DATASET_YAML.read_bytes()
    try:
        before, _, _ = resolve_execution_manifest(ES_STUDY, REPO_ROOT)
        NQ_DATASET_YAML.write_bytes(original + b"\n# unrelated-study probe edit\n")
        after, _, _ = resolve_execution_manifest(ES_STUDY, REPO_ROOT)
    finally:
        NQ_DATASET_YAML.write_bytes(original)
    assert before == after, "editing an unrelated study's DatasetSpec moved ES's composite"
