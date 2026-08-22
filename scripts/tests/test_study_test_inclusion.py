"""Regression tests for Phase 1 Packet C (mandatory study-test inclusion).

Covers:
  - Priority 1: studies/<study>/tests/test_*.py enters the mandatory selected surface
  - Priority 2: select_required_tests.py --json no longer crashes
  - the existing fail-safe broad fallback is preserved, not narrowed
  - research_preflight.py wires --study through to the selector
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.select_required_tests import (
    discover_all_framework_tests,
    discover_study_tests,
    get_test_selection_report,
    select_tests_for_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CLEAN_FLIP_STUDY = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"


def _mk(path: Path, body: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Priority 1 -- study-test discovery
# ---------------------------------------------------------------------------

def test_discover_study_tests_finds_nested_study_tests(tmp_path: Path):
    _mk(tmp_path / "tests" / "test_foo.py", "def test_x(): pass\n")
    _mk(tmp_path / "tests" / "test_bar.py", "def test_y(): pass\n")
    _mk(tmp_path / "tests" / "not_a_test.py", "x = 1\n")

    found = discover_study_tests(tmp_path, repo_root=tmp_path.parent)
    assert len(found) == 2
    assert all(f.endswith("test_foo.py") or f.endswith("test_bar.py") for f in found)


def test_discover_study_tests_returns_empty_when_no_tests_dir(tmp_path: Path):
    assert discover_study_tests(tmp_path, repo_root=tmp_path.parent) == []


def test_discover_study_tests_returns_empty_for_no_study():
    assert discover_study_tests(None) == []


def test_discover_study_tests_falls_back_to_absolute_path_outside_repo(tmp_path: Path):
    """A study copied outside the repo tree (e.g. a tmp_path test fixture) must still
    resolve to a usable, existing path -- not a ValueError or a bogus relative path."""
    _mk(tmp_path / "tests" / "test_out_of_repo.py", "def test_x(): pass\n")
    found = discover_study_tests(tmp_path, repo_root=REPO_ROOT)
    assert len(found) == 1
    assert Path(found[0]).is_absolute()
    assert Path(found[0]).is_file()


def test_select_tests_for_files_always_includes_study_tests(tmp_path: Path):
    """A study's own tests must appear in the selected surface regardless of which
    unrelated framework file changed."""
    _mk(tmp_path / "tests" / "test_study_local.py", "def test_x(): pass\n")
    selected = select_tests_for_files(
        ["utils/resampling.py"], repo_root=REPO_ROOT, study_dir=tmp_path,
    )
    assert "scripts/tests/test_resampling.py" in selected
    assert any(s.endswith("test_study_local.py") for s in selected)


def test_study_tests_survive_the_fallback_branch(tmp_path: Path):
    """The existing fail-safe broad fallback (unresolved change -> run everything) must
    not silently drop the study's own tests."""
    _mk(tmp_path / "tests" / "test_study_local.py", "def test_x(): pass\n")
    selected = select_tests_for_files(
        ["strategies/unknown_strategy.py"], repo_root=REPO_ROOT, study_dir=tmp_path,
    )
    # Fallback still fires for framework tests (unchanged behaviour).
    assert "scripts/tests/test_causal_lint.py" in selected
    assert "scripts/tests/test_causal_canaries.py" in selected
    # And the study's own test is present too, not lost inside the fallback.
    assert any(s.endswith("test_study_local.py") for s in selected)


def test_no_study_given_selection_is_unchanged_from_pre_packet_c_behaviour():
    """Backward compatibility: omitting study_dir must not alter existing selection."""
    with_none = select_tests_for_files(["utils/resampling.py"], repo_root=REPO_ROOT, study_dir=None)
    without_arg = select_tests_for_files(["utils/resampling.py"], repo_root=REPO_ROOT)
    assert with_none == without_arg


@pytest.mark.skipif(not (CLEAN_FLIP_STUDY / "tests").exists(), reason="CleanFlip study tests dir absent")
def test_clean_flip_study_local_tests_are_no_longer_a_zero_surface():
    """RFC: 'the study-test surface is currently effectively zero inside the mandatory
    selector and must be corrected.' Proves it now discovers a non-empty, real surface."""
    found = discover_study_tests(CLEAN_FLIP_STUDY, repo_root=REPO_ROOT)
    assert len(found) > 0
    for rel in found:
        assert (REPO_ROOT / rel).is_file() if not Path(rel).is_absolute() else Path(rel).is_file()


@pytest.mark.skipif(not (CLEAN_FLIP_STUDY / "tests").exists(), reason="CleanFlip study tests dir absent")
def test_clean_flip_study_tests_are_selected_when_preflighting_that_study():
    selected = select_tests_for_files(["some/unrelated/file.py"], repo_root=REPO_ROOT, study_dir=CLEAN_FLIP_STUDY)
    study_test_names = {p.name for p in (CLEAN_FLIP_STUDY / "tests").glob("test_*.py")}
    selected_names = {Path(s).name for s in selected}
    assert study_test_names <= selected_names


# ---------------------------------------------------------------------------
# Preserve the six mandatory gates / discoverable surface
# ---------------------------------------------------------------------------

def test_discover_all_framework_tests_unchanged_in_shape():
    tests = discover_all_framework_tests(REPO_ROOT)
    assert len(tests) >= 20
    assert all(t.startswith("scripts/tests/test_") for t in tests)


def test_report_includes_study_tests_discovered_count(tmp_path: Path):
    _mk(tmp_path / "tests" / "test_a.py", "def test_x(): pass\n")
    _mk(tmp_path / "tests" / "test_b.py", "def test_y(): pass\n")
    report = get_test_selection_report(["utils/resampling.py"], repo_root=REPO_ROOT, study_dir=tmp_path)
    assert report["study_tests_discovered"] == 2
    assert report["test_files_discovered"] >= 20 + 2


# ---------------------------------------------------------------------------
# Priority 2 -- selector JSON hygiene
# ---------------------------------------------------------------------------

def test_json_flag_no_longer_crashes_via_subprocess():
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "select_required_tests.py"), "--files", "utils/resampling.py", "--json"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert "selected_tests" in data
    assert "scripts/tests/test_resampling.py" in data["selected_tests"]


def test_json_flag_with_study_reports_study_tests():
    res = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "select_required_tests.py"),
            "--files", "utils/resampling.py",
            "--study", str(CLEAN_FLIP_STUDY),
            "--json",
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["study_tests_discovered"] > 0
    assert any("Codex_clean_maturity_flip_rolling_5m_productivity" in t for t in data["selected_tests"])


# ---------------------------------------------------------------------------
# research_preflight.py wiring
# ---------------------------------------------------------------------------

def test_research_preflight_passes_study_flag_to_selector():
    src = (REPO_ROOT / "scripts" / "research_preflight.py").read_text(encoding="utf-8")
    assert '"--study"' in src or "'--study'" in src
    assert "select_required_tests.py" in src


def test_cli_no_study_flag_matches_prior_default_behaviour():
    """Omitting --study must reproduce exactly the pre-Packet-C selection (framework
    tests only, from git diff / --files mapping)."""
    res_files_only = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "select_required_tests.py"), "--files", "utils/resampling.py"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert res_files_only.returncode == 0
    lines = [l.strip() for l in res_files_only.stdout.splitlines() if l.strip()]
    assert lines == ["scripts/tests/test_resampling.py"]
