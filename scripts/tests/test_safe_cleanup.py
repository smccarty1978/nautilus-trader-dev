"""Fail-closed recursive-deletion guard (data-loss incident).

A cleanup of a supposedly throwaway worktree followed a link out of it and destroyed real
data. Symlink creation needs privileges on Windows, so those cases skip rather than give a
false pass -- the plain containment and refusal logic is always exercised.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.safe_cleanup import (
    UnsafeDeletionError,
    assert_safe_to_delete,
    find_escaping_paths,
)


@pytest.fixture()
def workspace(tmp_path: Path):
    root = tmp_path / "disposable"
    (root / "work" / "nested").mkdir(parents=True)
    (root / "work" / "a.txt").write_bytes(b"scratch\n")
    (root / "work" / "nested" / "b.txt").write_bytes(b"scratch\n")

    outside = tmp_path / "REAL_DATA"
    outside.mkdir()
    (outside / "precious.parquet").write_bytes(b"irreplaceable\n")
    return root, outside


def _try_symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
        return True
    except (OSError, NotImplementedError):
        return False


def test_ordinary_tree_is_safe(workspace):
    root, _outside = workspace
    assert find_escaping_paths(root / "work") == []
    assert_safe_to_delete(root / "work", root)


def test_target_outside_the_disposable_root_is_refused(workspace):
    """The most direct mistake: deleting something that was never disposable."""
    root, outside = workspace
    with pytest.raises(UnsafeDeletionError, match="UNSAFE_DELETION_TARGET_OUTSIDE_ROOT"):
        assert_safe_to_delete(outside, root)


def test_escaping_link_aborts_the_entire_deletion(workspace):
    """The incident: a descendant link resolves outside the disposable root."""
    root, outside = workspace
    link = root / "work" / "nested" / "data_link"
    if not _try_symlink(link, outside):
        pytest.skip("symlink creation not permitted in this environment")

    escaping = find_escaping_paths(root / "work")
    assert escaping, "the escaping link was not detected"
    assert str(outside) in escaping[0][1]

    with pytest.raises(UnsafeDeletionError, match="UNSAFE_DELETION_ESCAPES_ROOT"):
        assert_safe_to_delete(root / "work", root)


def test_internal_link_is_not_an_escape(workspace):
    """A link that stays inside the disposable root is not a reason to refuse."""
    root, _outside = workspace
    link = root / "work" / "inner_link"
    if not _try_symlink(link, root / "work" / "nested"):
        pytest.skip("symlink creation not permitted in this environment")
    assert find_escaping_paths(root / "work") == []
    assert_safe_to_delete(root / "work", root)


def test_traversal_does_not_follow_links_out(workspace):
    """Inspecting a link must not mean walking through it."""
    root, outside = workspace
    (outside / "deep").mkdir()
    (outside / "deep" / "more.txt").write_bytes(b"x\n")
    link = root / "work" / "escape"
    if not _try_symlink(link, outside):
        pytest.skip("symlink creation not permitted in this environment")

    escaping = find_escaping_paths(root / "work")
    # Reported once, as the link itself -- not walked into and reported per file.
    assert [p for p, _t in escaping] == [str(link)]


def test_missing_target_is_not_an_error(workspace):
    root, _outside = workspace
    assert find_escaping_paths(root / "does_not_exist") == []


def test_real_data_survives_a_refused_cleanup(workspace):
    """The point of failing closed: nothing is deleted when the check refuses."""
    import shutil

    root, outside = workspace
    link = root / "work" / "data_link"
    if not _try_symlink(link, outside):
        pytest.skip("symlink creation not permitted in this environment")

    try:
        assert_safe_to_delete(root / "work", root)
        shutil.rmtree(root / "work")          # not reached
    except UnsafeDeletionError:
        pass

    assert (outside / "precious.parquet").exists(), "real data was destroyed"
    assert (root / "work" / "a.txt").exists(), "a refused cleanup deleted part of the tree"


# ---------------------------------------------------------------------------
# Windows directory junctions -- the incident's actual form.
#
# A junction is a reparse point that is NOT a symlink: `Path.is_symlink()` returns False
# for one. It also needs no elevation, so unlike the symlink cases above these run for
# real here. A guard that only checked `is_symlink()` would pass every test above and
# still walk straight out of the workspace.
# ---------------------------------------------------------------------------

def _try_junction(link: Path, target: Path) -> bool:
    import subprocess

    if os.name != "nt":
        return False
    res = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    return res.returncode == 0 and link.exists()


def test_junction_is_recognised_as_a_reparse_point(workspace):
    from scripts.safe_cleanup import _is_reparse_point

    root, outside = workspace
    link = root / "work" / "junction_link"
    if not _try_junction(link, outside):
        pytest.skip("junction creation unavailable")

    assert link.is_symlink() is False, "a junction is not a symlink -- that is the trap"
    assert _is_reparse_point(link) is True, "junction not detected as a reparse point"


def test_escaping_junction_aborts_the_entire_deletion(workspace):
    """The incident, reproduced exactly: a junction out of a disposable workspace."""
    root, outside = workspace
    link = root / "work" / "nested" / "catalog_junction"
    if not _try_junction(link, outside):
        pytest.skip("junction creation unavailable")

    escaping = find_escaping_paths(root / "work")
    assert escaping, "escaping junction was not detected"
    assert str(outside) in escaping[0][1]

    with pytest.raises(UnsafeDeletionError, match="UNSAFE_DELETION_ESCAPES_ROOT"):
        assert_safe_to_delete(root / "work", root)


def test_real_data_survives_a_refused_junction_cleanup(workspace):
    import shutil

    root, outside = workspace
    link = root / "work" / "catalog_junction"
    if not _try_junction(link, outside):
        pytest.skip("junction creation unavailable")

    try:
        assert_safe_to_delete(root / "work", root)
        shutil.rmtree(root / "work")          # must not be reached
    except UnsafeDeletionError:
        pass

    assert (outside / "precious.parquet").exists(), "real data was destroyed"
    assert (root / "work" / "a.txt").exists(), "a refused cleanup deleted part of the tree"


def test_internal_junction_is_not_an_escape(workspace):
    root, _outside = workspace
    link = root / "work" / "inner_junction"
    if not _try_junction(link, root / "work" / "nested"):
        pytest.skip("junction creation unavailable")
    assert find_escaping_paths(root / "work") == []
    assert_safe_to_delete(root / "work", root)


# ---------------------------------------------------------------------------
# Sanctioned deletion paths (incident 2026-10-08: `git worktree remove --force` through catalog junctions).
# ---------------------------------------------------------------------------

def _git_repo_with_worktree(tmp_path: Path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)  # noqa: E731
    run("init", "-q")
    (repo / "f.txt").write_text("x")
    run("add", "f.txt")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    wt = tmp_path / "repo-wt"
    assert run("worktree", "add", "--detach", str(wt)).returncode == 0
    return repo, wt


def test_worktree_remove_refuses_a_worktree_holding_a_junction_and_deletes_nothing(workspace, tmp_path):
    from scripts.safe_cleanup import safe_worktree_remove

    _root, outside = workspace
    repo, wt = _git_repo_with_worktree(tmp_path)
    (wt / "data" / "catalog").mkdir(parents=True)
    link = wt / "data" / "catalog" / "NQ"
    if not _try_junction(link, outside):
        pytest.skip("junction creation unavailable")
    with pytest.raises(UnsafeDeletionError, match="UNSAFE_WORKTREE_CONTAINS_REPARSE_POINT"):
        safe_worktree_remove(wt, repo)
    assert (outside / "precious.parquet").exists()
    assert (wt / "f.txt").exists(), "a refused removal touched the worktree"
    os.rmdir(link)


def test_worktree_remove_removes_a_clean_worktree(tmp_path):
    from scripts.safe_cleanup import safe_worktree_remove

    repo, wt = _git_repo_with_worktree(tmp_path)
    (wt / "untracked_scratch").mkdir()
    safe_worktree_remove(wt, repo)
    assert not wt.exists()


def test_worktree_remove_refuses_main_and_unregistered(tmp_path):
    from scripts.safe_cleanup import safe_worktree_remove

    repo, _wt = _git_repo_with_worktree(tmp_path)
    with pytest.raises(UnsafeDeletionError, match="UNSAFE_WORKTREE_IS_MAIN"):
        safe_worktree_remove(repo, repo)
    with pytest.raises(UnsafeDeletionError, match="UNSAFE_WORKTREE_NOT_REGISTERED"):
        safe_worktree_remove(tmp_path / "nowhere", repo)
    assert (repo / "f.txt").exists()


def test_safe_delete_refuses_any_reparse_point_even_internal(workspace):
    from scripts.safe_cleanup import safe_delete

    root, _outside = workspace
    link = root / "work" / "inner_junction"
    if not _try_junction(link, root / "work" / "nested"):
        pytest.skip("junction creation unavailable")
    with pytest.raises(UnsafeDeletionError, match="UNSAFE_DELETION_CONTAINS_REPARSE_POINT"):
        safe_delete(root / "work", root)
    assert (root / "work" / "a.txt").exists()


def test_safe_delete_deletes_an_ordinary_tree(workspace):
    from scripts.safe_cleanup import safe_delete

    root, _ = workspace
    safe_delete(root / "work", root)
    assert not (root / "work").exists()


def test_safe_delete_handles_read_only_files_like_git_objects(workspace):
    import stat as _stat
    from scripts.safe_cleanup import safe_delete

    root, _ = workspace
    ro = root / "work" / "nested" / "obj"
    ro.write_bytes(b"x")
    os.chmod(ro, _stat.S_IREAD)
    safe_delete(root / "work", root)
    assert not (root / "work").exists()


def test_live_data_is_protected_from_every_deletion_path():
    from scripts.safe_cleanup import assert_not_protected, protected_roots

    roots = protected_roots()
    assert any(r.name == "data" for r in roots)
    with pytest.raises(UnsafeDeletionError, match="UNSAFE_DELETION_PROTECTED_DATA"):
        assert_not_protected(roots[0] / "catalog" / "NQ_1S_V2_GLOBEX")
    with pytest.raises(UnsafeDeletionError, match="UNSAFE_DELETION_PROTECTED_DATA"):
        assert_not_protected(roots[0].parent)  # a tree that CONTAINS live data


def test_agents_documents_the_rule():
    repo_root = Path(__file__).resolve().parents[2]
    agents = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "DESTRUCTIVE FILESYSTEM SAFETY" in agents
    assert "reparse point" in agents.lower()
    assert "fail closed" in agents.lower()
