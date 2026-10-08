#!/usr/bin/env python3
"""Fail-closed guard for recursive deletion.

Prompted by a data-loss incident: a cleanup of what was believed to be a throwaway
worktree followed a link out of it and destroyed real data. On Windows this is
particularly easy to miss -- a directory *junction* is a reparse point, not a symlink, and
``os.path.islink()`` returns False for one.

The rule this enforces is deliberately narrow:

    A recursive delete must abort entirely if ANY descendant resolves outside the
    intended disposable root.

Aborting entirely matters. Deleting "the safe part" of a tree you did not fully understand
is exactly the shape of the incident -- the traversal reached the link only partway
through.

A second incident (2026-10-08) showed the check is useless while nothing calls it: an agent
ran ``git worktree remove --force`` on a worktree holding catalog junctions. ``delete`` and
``worktree-remove`` below are therefore the only deletion paths the PreToolUse hook
(``scripts/hooks/data_guard.py``) lets an agent use; both refuse protected live data and any
reparse point at all.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple


class UnsafeDeletionError(RuntimeError):
    """Raised when a recursive delete would reach outside its disposable root."""


def _is_reparse_point(p: Path) -> bool:
    """True for symlinks and, on Windows, junctions/mount points.

    ``Path.is_symlink()`` alone is not sufficient: a Windows directory junction is a
    reparse point that is not a symlink, and it is the form most likely to appear in a
    repository that links out to bulk data storage.
    """
    try:
        if p.is_symlink():
            return True
        st = os.lstat(p)
        return bool(getattr(st, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        # An unstattable entry cannot be shown to be safe.
        return True


def find_escaping_paths(root: Path) -> List[Tuple[str, str]]:
    """Returns (path, resolved_target) for every descendant that escapes ``root``.

    Traversal does not follow links -- it inspects them. Following them would be the very
    mistake this guards against.
    """
    root = Path(root).resolve()
    escaping: List[Tuple[str, str]] = []

    if not root.exists():
        return escaping

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for name in list(dirnames) + list(filenames):
            child = here / name
            if not _is_reparse_point(child):
                continue
            try:
                target = child.resolve()
            except OSError:
                escaping.append((str(child), "<unresolvable>"))
                continue
            try:
                target.relative_to(root)
            except ValueError:
                escaping.append((str(child), str(target)))
        # Never descend through a reparse point.
        dirnames[:] = [d for d in dirnames if not _is_reparse_point(here / d)]

    return escaping


def assert_safe_to_delete(target: Path, disposable_root: Path) -> None:
    """Fails closed unless ``target`` can be recursively deleted safely.

    Args:
        target: the directory about to be removed.
        disposable_root: the workspace that is genuinely disposable. ``target`` must live
            inside it, and nothing under ``target`` may point outside it.
    """
    target = Path(target).resolve()
    disposable_root = Path(disposable_root).resolve()

    try:
        target.relative_to(disposable_root)
    except ValueError:
        raise UnsafeDeletionError(
            f"UNSAFE_DELETION_TARGET_OUTSIDE_ROOT: {target} is not inside the disposable "
            f"root {disposable_root}. Refusing to delete."
        )

    if target == disposable_root.anchor or str(target) in ("/", ""):
        raise UnsafeDeletionError(f"UNSAFE_DELETION_TARGET: refusing to delete {target}")

    escaping = find_escaping_paths(target)
    if escaping:
        rendered = "; ".join(f"{p} -> {t}" for p, t in escaping[:10])
        raise UnsafeDeletionError(
            f"UNSAFE_DELETION_ESCAPES_ROOT: {len(escaping)} path(s) under {target} resolve "
            f"outside {disposable_root}: {rendered}. Aborting the ENTIRE deletion -- "
            f"deleting the remainder of a tree containing an escape is how real data was "
            f"lost. Detach or relocate the link first."
        )


def find_reparse_points(root: Path) -> List[str]:
    """Every reparse point (symlink, junction, mount point) under ``root``, internal or not, without following any."""
    root = Path(root)
    found: List[str] = []
    if _is_reparse_point(root):
        return [str(root)]
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for name in list(dirnames) + list(filenames):
            if _is_reparse_point(here / name):
                found.append(str(here / name))
        dirnames[:] = [d for d in dirnames if not _is_reparse_point(here / d)]
    return found


def protected_roots(repo_root: Optional[Path] = None) -> List[Path]:
    """Live data that no cleanup may touch: <repo>/data and the configured catalog_roots."""
    repo_root = Path(repo_root or Path(__file__).resolve().parents[1])
    bases = [repo_root]
    try:  # from a secondary worktree, the live data sits under the MAIN checkout
        common = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        bases.append(Path(common).parent)
    except Exception:
        pass
    roots = [b / sub for b in bases for sub in ("data", "research/datasets")]
    try:
        from scripts.hooks.data_guard import _catalog_roots
    except Exception:  # pragma: no cover - import path differs when run as a script
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from hooks.data_guard import _catalog_roots  # type: ignore
    roots += [Path(r) for r in _catalog_roots()]
    return [Path(os.path.normcase(str(r.resolve()))) for r in roots]


def assert_not_protected(target: Path, repo_root: Optional[Path] = None) -> None:
    """Refuse a target that is, contains, or lies inside live data."""
    t = Path(os.path.normcase(str(Path(target).resolve())))
    for r in protected_roots(repo_root):
        if t == r or r in t.parents or t in r.parents:
            raise UnsafeDeletionError(f"UNSAFE_DELETION_PROTECTED_DATA: {target} overlaps protected live data {r}.")


def safe_delete(target: Path, disposable_root: Path) -> None:
    """Fail-closed recursive delete: refuses protected data, any reparse point at all, or any escape."""
    assert_not_protected(target)
    assert_safe_to_delete(target, disposable_root)
    links = find_reparse_points(target)
    if links:
        raise UnsafeDeletionError(f"UNSAFE_DELETION_CONTAINS_REPARSE_POINT: {len(links)} under {target}: "
                                  f"{'; '.join(links[:10])}. Remove each link non-recursively first (rmdir <link>).")
    shutil.rmtree(target)


def _git_worktrees(repo: Path) -> List[Path]:
    out = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True,
                         check=True).stdout
    return [Path(line[len("worktree "):]) for line in out.splitlines() if line.startswith("worktree ")]


def safe_worktree_remove(path: Path, repo: Optional[Path] = None) -> None:
    """Remove a registered secondary git worktree only after proving it holds no reparse point and no live data."""
    repo = Path(repo or Path(__file__).resolve().parents[1])
    path = Path(path)
    trees = [Path(os.path.normcase(str(w.resolve()))) for w in _git_worktrees(repo)]
    p = Path(os.path.normcase(str(path.resolve())))
    if p not in trees:
        raise UnsafeDeletionError(f"UNSAFE_WORKTREE_NOT_REGISTERED: {path} is not a worktree of {repo}.")
    if p == trees[0]:
        raise UnsafeDeletionError(f"UNSAFE_WORKTREE_IS_MAIN: refusing to remove the main worktree {path}.")
    assert_not_protected(path, repo)
    links = find_reparse_points(path)
    if links:
        raise UnsafeDeletionError(f"UNSAFE_WORKTREE_CONTAINS_REPARSE_POINT: {len(links)} under {path}: "
                                  f"{'; '.join(links[:10])}. Remove each link non-recursively (rmdir <link>) and retry.")
    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(path)], check=True)


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0].startswith("--"):  # legacy form: check only
        argv = ["check"] + argv
    ap = argparse.ArgumentParser(description="Fail-closed recursive deletion")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--target", required=True)
    c.add_argument("--disposable-root", required=True)
    d = sub.add_parser("delete")
    d.add_argument("--target", required=True)
    d.add_argument("--disposable-root", required=True)
    w = sub.add_parser("worktree-remove")
    w.add_argument("path")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "check":
            assert_not_protected(Path(args.target))
            assert_safe_to_delete(Path(args.target), Path(args.disposable_root))
            print(f"SAFE_TO_DELETE: {args.target}")
        elif args.cmd == "delete":
            safe_delete(Path(args.target), Path(args.disposable_root))
            print(f"DELETED: {args.target}")
        else:
            safe_worktree_remove(Path(args.path))
            print(f"WORKTREE_REMOVED: {args.path}")
    except UnsafeDeletionError as err:
        print(f"[REFUSED] {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
