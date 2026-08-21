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
through. This is one function and one prohibition, not a cleanup framework.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import List, Tuple


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Check whether a path is safe to delete recursively")
    ap.add_argument("--target", required=True)
    ap.add_argument("--disposable-root", required=True)
    args = ap.parse_args()

    try:
        assert_safe_to_delete(Path(args.target), Path(args.disposable_root))
    except UnsafeDeletionError as err:
        print(f"[REFUSED] {err}", file=sys.stderr)
        return 1
    print(f"SAFE_TO_DELETE: {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
