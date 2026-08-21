"""Diff-Aware Test Selection Tool.
=================================

Determines the minimal set of mandatory deterministic fast tests based on
changed files in git diff.

Usage:
  python scripts/select_required_tests.py
  python scripts/select_required_tests.py --files file1.py file2.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent

TEST_MAPPINGS = {
    "scripts/causal_lint.py": ["scripts/tests/test_causal_lint.py"],
    "utils/resampling.py": ["scripts/tests/test_resampling.py"],
    "scripts/check_model_binding.py": ["scripts/tests/test_model_binding.py"],
    "scripts/check_artifact_schema.py": ["scripts/tests/test_artifact_schema.py"],
    "utils/causal_canaries.py": ["scripts/tests/test_causal_canaries.py"],
    "scripts/find_first_parity_divergence.py": ["scripts/tests/test_parity_divergence.py"],
}

DIR_MAPPINGS = {
    "features/": ["scripts/tests/test_causal_canaries.py"],
    "models/": ["scripts/tests/test_model_binding.py"],
    "utils/runner/": ["scripts/tests/test_model_binding.py", "scripts/tests/test_resampling.py"],
}


def get_git_changed_files() -> List[str]:
    try:
        res = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [l.strip() for l in res.stdout.splitlines() if l.strip()]
    except Exception:
        return []


def discover_all_framework_tests(repo_root: Optional[Path] = None) -> List[str]:
    """Deterministically discovers all framework test files in scripts/tests."""
    if repo_root is None:
        repo_root = REPO_ROOT
    test_dir = repo_root / "scripts" / "tests"
    if not test_dir.exists():
        return []
    return sorted([p.relative_to(repo_root).as_posix() for p in test_dir.glob("test_*.py")])


def select_tests_for_files(files: List[str], repo_root: Optional[Path] = None) -> List[str]:
    if repo_root is None:
        repo_root = REPO_ROOT

    all_tests = discover_all_framework_tests(repo_root)
    selected: Set[str] = set()
    unresolved = False

    for f in files:
        f_norm = f.replace("\\", "/")
        matched = False
        for pattern, tests in TEST_MAPPINGS.items():
            if pattern in f_norm:
                selected.update(tests)
                matched = True

        for dir_prefix, tests in DIR_MAPPINGS.items():
            if f_norm.startswith(dir_prefix):
                selected.update(tests)
                matched = True

        if not matched and f_norm.endswith(".py"):
            unresolved = True

    # If unresolved changes, empty selection, or explicitly requested full suite, run all discovered tests
    if unresolved or not selected:
        return all_tests

    return sorted(list(selected))


def get_test_selection_report(files: List[str], repo_root: Optional[Path] = None) -> Dict[str, Any]:
    if repo_root is None:
        repo_root = REPO_ROOT

    all_tests = discover_all_framework_tests(repo_root)
    selected_tests = select_tests_for_files(files, repo_root=repo_root)
    coverage_pct = round(len(selected_tests) / len(all_tests) * 100.0, 2) if all_tests else 100.0

    return {
        "test_files_discovered": len(all_tests),
        "test_files_selected": len(selected_tests),
        "coverage_pct": coverage_pct,
        "selected_tests": selected_tests,
        "all_tests": all_tests,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Select mandatory fast tests based on git diff")
    ap.add_argument("--files", nargs="*", help="Explicit list of changed files")
    ap.add_argument("--all", action="store_true", help="Select all discovered test files")
    ap.add_argument("--json", action="store_true", help="Print structured JSON output")
    args = ap.parse_args()

    files = args.files if args.files is not None else get_git_changed_files()
    if args.json:
        report = get_test_selection_report([] if args.all else files)
        print(json.dumps(report, indent=2))
    else:
        tests = discover_all_framework_tests() if args.all else select_tests_for_files(files)
        for t in tests:
            print(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
