"""Regression tests for the Red Team baseline-capture findings.

Source: `exports/FINAL_REDTEAM_BACKTEST_HARNESS_2026-08-16.md` — M1, M2, W2, W3.
Each reproduces the demonstrated exploit and asserts it is now refused.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.capture_baseline_fixtures import (  # noqa: E402
    PROVENANCE_PACKAGES, STATUS_ABSENT_UNVERIFIED, STATUS_ABSENT_VERIFIED, STATUS_PRODUCED,
    FixtureSpec, TargetSpec, _hash_catalog_partitions, _partition_intersects_window,
    capture_fixture, check_worktree_gates, classify_target, dependency_versions,
    produced_reference_identities,
)
from scripts.tests.test_capture_baseline_fixtures import (  # noqa: E402
    fake_fixture, fake_git, make_fake_repo, writer_runner,
)


# ===========================================================================
# M1 — a stale file must never become the golden reference
# ===========================================================================


def test_m1_fabricated_capture_does_not_report_success(tmp_path):
    """THE EXPLOIT: runner writes nothing, a stale file sits at a `produced` target.

    Previously reported SUCCESS / baseline_valid: true and published the stale
    file's identity as the golden reference.
    """
    repo = make_fake_repo(tmp_path)
    stale = repo / "out" / "results.parquet"
    pd.DataFrame({"x": [1, 2, 3]}).to_parquet(stale, index=False)

    fx = fake_fixture([TargetSpec("out/results.parquet", "produced")])
    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=writer_runner({}), collect_catalog_bounds=False)

    assert section["status"] == "FAILED_REQUIRED_TARGET_NOT_PRODUCED"
    assert section["baseline_valid"] is False
    assert section["required_targets_not_produced"] == ["out/results.parquet"]
    # And the stale file is restored untouched.
    assert stale.is_file()


def test_m1_stale_identity_is_not_offered_as_a_reference(tmp_path):
    """Even if a section is inspected directly, a non-produced target is filtered."""
    section = {
        "targets": [
            {"target_path": "out/stale.parquet", "status": STATUS_ABSENT_UNVERIFIED,
             "normalized_identity": {"normalized_sha256": "deadbeef", "row_count": 20}},
            {"target_path": "out/real.parquet", "status": STATUS_PRODUCED,
             "normalized_identity": {"normalized_sha256": "cafe", "row_count": 5}},
        ]
    }
    refs = produced_reference_identities(section)
    assert set(refs) == {"real.parquet"}
    assert "stale.parquet" not in refs


def test_m1_produced_target_that_is_produced_still_passes(tmp_path):
    repo = make_fake_repo(tmp_path)
    fx = fake_fixture([TargetSpec("out/new.txt", "produced", hash_output=False)])
    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=writer_runner({"out/new.txt": "fresh"}),
                              collect_catalog_bounds=False)
    assert section["status"] == "SUCCESS"
    assert section["baseline_valid"] is True
    assert section["targets"][0]["status"] == STATUS_PRODUCED
    assert section["required_targets_not_produced"] == []


# ===========================================================================
# M2 — attribution may not rest on modification time
# ===========================================================================


def test_m2_mtime_advance_alone_is_not_production():
    status, note = classify_target(True, False, True, "same", "same", 50.0, 999.0)
    assert status == STATUS_ABSENT_UNVERIFIED
    assert "not accepted as evidence" in note


def test_m2_produced_targets_are_quarantined():
    """Quarantine is what replaces mtime as the attribution mechanism."""
    assert TargetSpec("p", "produced").quarantine_required is True
    assert TargetSpec("c", "conditional").quarantine_required is True


def test_m2_preexisting_produced_target_is_attributed_by_clean_start(tmp_path):
    """A pre-existing file is moved aside, so its reappearance IS the proof."""
    repo = make_fake_repo(tmp_path)
    target = repo / "out" / "p.txt"
    target.write_text("ORIGINAL", encoding="utf-8")

    fx = fake_fixture([TargetSpec("out/p.txt", "produced", hash_output=False)])
    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=writer_runner({"out/p.txt": "ORIGINAL"}),
                              collect_catalog_bounds=False)

    t = section["targets"][0]
    assert t["quarantined_to_prove_absence"] is True
    assert t["status"] == STATUS_PRODUCED          # byte-identical, but provably written
    assert t["restored_to_original_state"] is True
    assert target.read_text() == "ORIGINAL"


def test_m2_real_fixture_specs_quarantine_their_primary_targets():
    from scripts.capture_baseline_fixtures import get_fixture

    for fid, primary in (("fixture_1_score_fanning", "results_R2.5.parquet"),
                         ("fixture_2_w4_b1", "trades.parquet")):
        spec = next(t for t in get_fixture(fid).targets if t.path.endswith(primary))
        assert spec.expectation == "produced"
        assert spec.quarantine_required is True, f"{primary} still rests on mtime"


# ===========================================================================
# W2 — a modified closure member blocks authoritative capture
# ===========================================================================


def test_w2_modified_tracked_closure_member_blocks_capture(tmp_path):
    """THE EXPLOIT: strategies/score_fanning_strategy.py was modified at capture time."""
    git = fake_git({
        ("diff", "--name-only"): "strategies/score_fanning_strategy.py\n",
        ("diff", "--cached", "--name-only"): "",
        ("ls-files", "--others", "--exclude-standard"): "",
    })
    res = check_worktree_gates(
        tmp_path,
        protected_paths=frozenset({"strategies/score_fanning_strategy.py"}),
        git_runner=git,
    )
    assert res.passed is False
    assert "MODIFIED_TRACKED_FILE_IN_FIXTURE_CLOSURE" in res.blocking_reason
    assert res.dirty_tracked_in_closure == ["strategies/score_fanning_strategy.py"]


def test_w2_staged_closure_member_also_blocks(tmp_path):
    git = fake_git({
        ("diff", "--name-only"): "",
        ("diff", "--cached", "--name-only"): "utils/runner/data.py\n",
        ("ls-files", "--others", "--exclude-standard"): "",
    })
    res = check_worktree_gates(tmp_path, protected_paths=frozenset({"utils/runner/data.py"}),
                               git_runner=git)
    assert res.passed is False
    assert "utils/runner/data.py" in res.dirty_tracked_in_closure


def test_w2_modified_file_outside_the_closure_stays_advisory(tmp_path):
    git = fake_git({
        ("diff", "--name-only"): "README.md\ndocs/X.md\n",
        ("diff", "--cached", "--name-only"): "",
        ("ls-files", "--others", "--exclude-standard"): "",
    })
    res = check_worktree_gates(tmp_path, protected_paths=frozenset({"utils/runner/data.py"}),
                               git_runner=git)
    assert res.passed is True
    assert res.worktree_clean is False        # still recorded
    assert res.dirty_tracked_in_closure == []


# ===========================================================================
# W3 — environment and catalog content provenance
# ===========================================================================


def test_w3_dependency_versions_recorded():
    versions = dependency_versions()
    for pkg in PROVENANCE_PACKAGES:
        assert pkg in versions, f"{pkg} version is not recorded"
    assert versions["nautilus_trader"], "nautilus_trader version missing"
    assert versions["python"]


def test_w3_catalog_partitions_are_content_hashed(tmp_path):
    catalog = tmp_path / "cat"
    (catalog / "data" / "bar").mkdir(parents=True)
    a = catalog / "data" / "bar" / "1600000000000000000-1700000000000000000-0.parquet"
    pd.DataFrame({"x": [1, 2]}).to_parquet(a, index=False)

    start = pd.Timestamp("2023-01-01", tz="UTC")
    end = pd.Timestamp("2023-12-31", tz="UTC")
    out = _hash_catalog_partitions(catalog, start, end)

    assert out["status"] == "ok"
    assert out["file_count"] == 1
    assert len(out["files"][0]["sha256"]) == 64
    assert len(out["composite_sha256"]) == 64


def test_w3_changed_bar_value_changes_the_composite(tmp_path):
    """A value change inside the window must be visible, not just row counts."""
    catalog = tmp_path / "cat"
    (catalog / "data").mkdir(parents=True)
    p = catalog / "data" / "part.parquet"
    start = pd.Timestamp("2023-01-01", tz="UTC")
    end = pd.Timestamp("2023-12-31", tz="UTC")

    pd.DataFrame({"close": [100.0, 101.0]}).to_parquet(p, index=False)
    before = _hash_catalog_partitions(catalog, start, end)["composite_sha256"]

    pd.DataFrame({"close": [100.0, 999.0]}).to_parquet(p, index=False)   # same row count
    after = _hash_catalog_partitions(catalog, start, end)["composite_sha256"]

    assert before != after


def test_w3_partition_window_selection():
    inside = Path("1672531200000000000-1704067200000000000-0.parquet")
    before = Path("1000000000000000000-1100000000000000000-0.parquet")
    unparseable = Path("part-abc.parquet")
    lo = int(pd.Timestamp("2023-06-01", tz="UTC").value)
    hi = int(pd.Timestamp("2023-06-02", tz="UTC").value)

    assert _partition_intersects_window(inside, lo, hi) is True
    assert _partition_intersects_window(before, lo, hi) is False
    # Over-inclusion is the safe direction for provenance.
    assert _partition_intersects_window(unparseable, lo, hi) is True


def test_w3_missing_catalog_is_reported_not_silently_empty(tmp_path):
    out = _hash_catalog_partitions(tmp_path / "nope", pd.Timestamp("2023-01-01", tz="UTC"),
                                   pd.Timestamp("2023-01-02", tz="UTC"))
    assert out["status"] == "catalog_not_found"
