"""Diff-Aware Test Selection Tool.
=================================

Determines the minimal set of mandatory deterministic fast tests based on
changed files in git diff, plus (Phase 1 Packet C) a study's own mandatory
local tests whenever a study is being preflighted.

Usage:
  python scripts/select_required_tests.py
  python scripts/select_required_tests.py --files file1.py file2.py
  python scripts/select_required_tests.py --study studies/<name>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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

# Bounded study-preflight surface.  A compiled study must not inherit the
# repository-wide CI suite merely because unrelated files are dirty.
STUDY_CORE_TESTS = {
    "scripts/tests/test_artifact_schema.py",
    "scripts/tests/test_causal_lint.py",
    "scripts/tests/test_execution_closure.py",
    "scripts/tests/test_freeze_boundary.py",
    "scripts/tests/test_output_manager_zero_row.py",
    "scripts/tests/test_readiness.py",
    "scripts/tests/test_phase0_source_lineage.py",
    "scripts/tests/test_population_funnel.py",
    "scripts/tests/test_target_censoring.py",
}

STUDY_PROVIDER_TESTS = {
    "scripts/tests/test_feature_promotion.py",
    "scripts/tests/test_feature_surface_validation.py",
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


def discover_study_tests(study_dir: Optional[Path], repo_root: Optional[Path] = None) -> List[str]:
    """Discovers a study's own mandatory tests: studies/<study>/tests/test_*.py.

    Phase 1 Packet C: the study-test surface was effectively zero inside the mandatory
    selector -- `discover_all_framework_tests` only ever looked at `scripts/tests/`, so a
    study's own local tests never entered the CAUSAL_INVARIANTS gate regardless of what
    changed. Returns repo-relative POSIX paths when `study_dir` is under `repo_root` (the
    normal governed case, matching the style of `discover_all_framework_tests`); falls
    back to an absolute path string when the study lives outside the repo tree (e.g. a
    `tmp_path`-copied study in a test fixture), so pytest can still locate the file either
    way. Returns ``[]`` when no study is given or the study has no `tests/` directory --
    this does not force every study to adopt a `tests/` directory.
    """
    if study_dir is None:
        return []
    study_dir = Path(study_dir)
    if repo_root is None:
        repo_root = REPO_ROOT
    tests_dir = study_dir / "tests"
    if not tests_dir.exists():
        return []
    result: List[str] = []
    for p in sorted(tests_dir.glob("test_*.py")):
        resolved = p.resolve()
        try:
            result.append(resolved.relative_to(repo_root.resolve()).as_posix())
        except ValueError:
            result.append(str(resolved))
    return result


def select_tests_for_files(
    files: List[str],
    repo_root: Optional[Path] = None,
    study_dir: Optional[Path] = None,
) -> List[str]:
    if repo_root is None:
        repo_root = REPO_ROOT

    study_tests = discover_study_tests(study_dir, repo_root)

    # A compiled study has an explicit execution closure.  Keep preflight bounded
    # to its contract/provider surface; the old unresolved-diff fallback selected
    # every repository test (1,125 tests for CleanFlip).
    if study_dir is not None and (Path(study_dir) / "compiled_study.json").exists():
        return sorted((STUDY_CORE_TESTS | STUDY_PROVIDER_TESTS) | set(study_tests))

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

    # If unresolved changes, empty selection, or explicitly requested full suite, run all
    # discovered framework tests (the existing fail-safe broad fallback, preserved as-is).
    framework_selected = all_tests if (unresolved or not selected) else sorted(selected)

    # Packet C: a study's own tests are always part of the mandatory selected surface when
    # preflighting that study -- not conditioned on the diff/mapping outcome above, and not
    # lost inside the fallback branch either.
    return sorted(set(framework_selected) | set(study_tests))


def get_test_selection_report(
    files: List[str],
    repo_root: Optional[Path] = None,
    study_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    if repo_root is None:
        repo_root = REPO_ROOT

    all_tests = discover_all_framework_tests(repo_root)
    study_tests = discover_study_tests(study_dir, repo_root)
    all_discoverable = sorted(set(all_tests) | set(study_tests))
    selected_tests = select_tests_for_files(files, repo_root=repo_root, study_dir=study_dir)
    coverage_pct = round(len(selected_tests) / len(all_discoverable) * 100.0, 2) if all_discoverable else 100.0

    governed = bool(study_dir and (Path(study_dir) / "compiled_study.json").exists())
    group_files = {
        "study_local": sorted(set(study_tests) & set(selected_tests)),
        "core_governance": sorted(set(STUDY_CORE_TESTS) & set(selected_tests)) if governed else [],
        "provider_relevant": sorted(set(STUDY_PROVIDER_TESTS) & set(selected_tests)) if governed else [],
    }
    return {
        "test_files_discovered": len(all_discoverable),
        "test_files_selected": len(selected_tests),
        "coverage_pct": coverage_pct,
        "selected_tests": selected_tests,
        "all_tests": all_discoverable,
        "study_tests_discovered": len(study_tests),
        "selection_groups": {key: len(value) for key, value in group_files.items()},
        "selection_group_files": group_files,
        "global_ci_excluded": max(0, len(all_discoverable) - len(selected_tests)) if governed else 0,
    }


def profile_selected_tests(files: List[str], *, timeout_seconds: float = 30.0) -> List[Dict[str, Any]]:
    """Collect per-file test counts and collection latency without executing tests."""
    profile = []
    for path in files:
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", path, "--collect-only", "-q"],
                cwd=str(REPO_ROOT), capture_output=True, text=True,
                timeout=timeout_seconds,
            )
            lines = [line for line in proc.stdout.splitlines() if line.strip()]
            count = 0
            for line in reversed(lines):
                if "test" in line.lower() and "selected" not in line.lower():
                    import re
                    match = re.search(r"(\d+)\s+test", line)
                    if match:
                        count = int(match.group(1))
                        break
            profile.append({"path": path, "test_count": count,
                            "elapsed_seconds": round(time.perf_counter() - started, 3),
                            "status": "COLLECTED" if proc.returncode == 0 else "COLLECTION_FAILED"})
        except subprocess.TimeoutExpired:
            profile.append({"path": path, "test_count": None,
                            "elapsed_seconds": round(time.perf_counter() - started, 3),
                            "status": "COLLECTION_TIMEOUT"})
    return profile


def main() -> int:
    ap = argparse.ArgumentParser(description="Select mandatory fast tests based on git diff")
    ap.add_argument("--files", nargs="*", help="Explicit list of changed files")
    ap.add_argument("--all", action="store_true", help="Select all discovered test files")
    ap.add_argument("--json", action="store_true", help="Print structured JSON output")
    ap.add_argument(
        "--study", type=str, default=None,
        help="Study directory whose tests/test_*.py are always included in the mandatory selection",
    )
    args = ap.parse_args()

    study_dir = Path(args.study).resolve() if args.study else None
    files = args.files if args.files is not None else get_git_changed_files()
    if args.json:
        report = get_test_selection_report([] if args.all else files, study_dir=study_dir)
        print(json.dumps(report, indent=2))
    else:
        if args.all:
            tests = sorted(set(discover_all_framework_tests()) | set(discover_study_tests(study_dir)))
        else:
            tests = select_tests_for_files(files, study_dir=study_dir)
        for t in tests:
            print(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
