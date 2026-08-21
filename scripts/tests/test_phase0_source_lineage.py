"""Regression tests for phase-0 source manifest lineage (Finding A2).

The failed ES acceptance test produced a manifest recording
``git_commit_hash: 5972556…`` while enumerating ``latest_1m_wick_imbalance`` in its
verified candidate universe. At ``5972556`` the file ``features/trackers/wick.py`` did
not exist and the registry contained no such entry: the manifest's *content* came from
the working tree while its *provenance* named a commit that could not have produced it.

These tests drive a real throwaway git repository so the clean/dirty/new-file cases are
genuine git states rather than mocked ones.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(project_root: Path):
    """Loads build_phase0_manifest bound to an arbitrary project root."""
    spec = importlib.util.spec_from_file_location(
        f"bp0_{abs(hash(str(project_root)))}", REPO_ROOT / "scripts" / "build_phase0_manifest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.project_root = project_root
    return mod


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return res.stdout


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    (repo / "features").mkdir(parents=True)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "features" / "registry.py").write_text("REGISTRY = {'a': 1}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def test_clean_tree_yields_committed_provenance(git_repo: Path):
    """A2.1 -- when nothing diverges, the commit id IS sufficient provenance."""
    mod = _load_module(git_repo)
    b = mod.build_source_state_binding([git_repo / "features" / "registry.py"])
    assert b["provenance_strength"] == "COMMITTED"
    assert b["git_commit_is_sufficient_provenance"] is True
    assert b["working_tree_dirty"] is False
    assert b["dependencies_diverging_from_commit"] == []


def test_unrelated_untracked_file_does_not_downgrade_provenance(git_repo: Path):
    """Strength is decided by the dependencies, not by global tree cleanliness.

    A repository nearly always holds some untracked file (a run directory, a scratch
    note). If that forced WORKING_TREE forever the field would carry no information --
    the failure mode of a check that fires on everything.
    """
    mod = _load_module(git_repo)
    (git_repo / "untracked_scratch.txt").write_bytes(b"noise\n")
    b = mod.build_source_state_binding([git_repo / "features" / "registry.py"])
    assert b["working_tree_dirty"] is True, "global dirtiness is still reported"
    assert b["provenance_strength"] == "COMMITTED"
    assert b["dependencies_diverging_from_commit"] == []


def test_dirty_tree_downgrades_provenance(git_repo: Path):
    """A2.2 -- a modified dependency must not be signed off by the old commit."""
    mod = _load_module(git_repo)
    (git_repo / "features" / "registry.py").write_text("REGISTRY = {'a': 2}\n", encoding="utf-8")
    b = mod.build_source_state_binding([git_repo / "features" / "registry.py"])
    assert b["provenance_strength"] == "WORKING_TREE"
    assert b["git_commit_is_sufficient_provenance"] is False
    assert "features/registry.py" in b["dependencies_diverging_from_commit"]
    assert b["source_files"]["features/registry.py"]["state"] == "MODIFIED"


def test_newly_created_uncommitted_feature_is_flagged(git_repo: Path):
    """A2.3 -- the exact ES failure: a feature file that does not exist at HEAD.

    This is the case the old implementation got wrong. ``git rev-parse HEAD`` returns a
    perfectly valid commit id for a file that commit never contained.
    """
    mod = _load_module(git_repo)
    newf = git_repo / "features" / "wick.py"
    newf.write_text("class WickTracker:\n    pass\n", encoding="utf-8")
    b = mod.build_source_state_binding(
        [git_repo / "features" / "registry.py", newf]
    )
    assert b["provenance_strength"] == "WORKING_TREE"
    assert b["source_files"]["features/wick.py"]["state"] == "UNTRACKED_OR_NEW"
    assert "features/wick.py" in b["dependencies_diverging_from_commit"]


def test_source_state_sha_changes_with_content(git_repo: Path):
    """The binding is a function of bytes, so it moves when the source moves."""
    mod = _load_module(git_repo)
    dep = [git_repo / "features" / "registry.py"]
    before = mod.build_source_state_binding(dep)["source_state_sha256"]
    (git_repo / "features" / "registry.py").write_text("REGISTRY = {'a': 3}\n", encoding="utf-8")
    after = mod.build_source_state_binding(dep)["source_state_sha256"]
    assert before != after


def test_manifest_claiming_an_incompatible_commit_is_rejected(git_repo: Path):
    """A2.4 -- an overclaimed commit is refused even though the bytes are current.

    Reconstructs the historical artifact directly: content taken from the working tree,
    provenance asserting a commit that never held it.
    """
    mod = _load_module(git_repo)
    newf = git_repo / "features" / "wick.py"
    newf.write_text("class WickTracker:\n    pass\n", encoding="utf-8")

    forged = {
        "source_state_binding": {
            "provenance_strength": "COMMITTED",
            "git_commit_hash": _git(git_repo, "rev-parse", "HEAD").strip(),
            "git_commit_is_sufficient_provenance": True,   # the lie
            "working_tree_dirty": False,
            "source_files": {
                "features/wick.py": {
                    "sha256": hashlib.sha256(newf.read_bytes()).hexdigest(),
                    "state": "COMMITTED",
                }
            },
        }
    }
    with pytest.raises(mod.SourceProvenanceError, match="does not exist at that commit"):
        mod.verify_source_state_binding(forged)


def test_drifted_dependency_is_rejected(git_repo: Path):
    """A2.5 -- a manifest describing source that has since changed is not current."""
    mod = _load_module(git_repo)
    dep = git_repo / "features" / "registry.py"
    manifest = {"source_state_binding": mod.build_source_state_binding([dep])}
    mod.verify_source_state_binding(manifest)          # currently consistent
    dep.write_text("REGISTRY = {'a': 99}\n", encoding="utf-8")
    with pytest.raises(mod.SourceProvenanceError, match="drifted"):
        mod.verify_source_state_binding(manifest)


def test_manifest_without_a_binding_is_rejected(git_repo: Path):
    """A bare commit id is not provenance, and must not be accepted as one."""
    mod = _load_module(git_repo)
    with pytest.raises(mod.SourceProvenanceError, match="SOURCE_BINDING_ABSENT"):
        mod.verify_source_state_binding({"git_commit_hash": "deadbeef"})


def test_real_manifest_generation_records_a_binding(tmp_path: Path):
    """The generator must actually emit the binding for a real study."""
    import shutil

    src = REPO_ROOT / "studies" / "es_wick_imbalance_exploratory"
    if not (src / "study.yaml").exists():
        pytest.skip("ES study absent")
    probe = tmp_path / "es_probe"
    shutil.copytree(src, probe)

    mod = _load_module(REPO_ROOT)
    manifest = mod.build_phase0_manifest(probe)
    binding = manifest["source_state_binding"]
    assert binding["source_state_sha256"]
    assert binding["provenance_strength"] in ("COMMITTED", "WORKING_TREE")

    # The registry itself and the study's own authored contracts are always bound.
    assert "features/registry.py" in binding["source_files"]
    assert any(k.endswith("study.yaml") for k in binding["source_files"])
    assert any(k.endswith("SPEC.md") for k in binding["source_files"])

    # Every implementation module backing an enumerated verified feature is bound. The
    # wick tracker is deliberately NOT expected here: the feature is 'provisional', so it
    # is not part of the verified candidate universe this manifest enumerates.
    from features.registry import FEATURE_REGISTRY

    enumerated = manifest["candidate_feature_universe"]["candidates"]
    assert "latest_1m_wick_imbalance" not in enumerated, (
        "a provisional feature must not appear in the verified candidate universe"
    )
    sample = next(iter(enumerated))
    impl = FEATURE_REGISTRY[sample].implementation
    if impl:
        rel = "/".join(impl.rsplit(".", 1)[0].split(".")) + ".py"
        assert rel in binding["source_files"], (
            f"implementation {rel} backs an enumerated feature but is not bound"
        )
