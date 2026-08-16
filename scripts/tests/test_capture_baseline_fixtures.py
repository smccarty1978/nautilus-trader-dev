"""Tests for scripts/capture_baseline_fixtures.py.

All tests operate on temporary directories with mocked subprocess runners; none
of them execute a real backtest or touch the working tree.
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
    STATUS_ABSENT_UNVERIFIED,
    STATUS_ABSENT_VERIFIED,
    STATUS_PRODUCED,
    STATUS_STALE_UNMANAGED,
    VALID_STATUSES,
    FixtureSpec,
    TargetSpec,
    build_dry_run_plan,
    capture_fixture,
    check_worktree_gates,
    classify_target,
    compare_normalized,
    get_fixture,
    normalized_parquet_identity,
    resolve_repo_local_closure,
    resolve_repo_local_closure_detailed,
    scan_stale_unmanaged,
    selected_closure_paths,
    snapshot_resolved_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fake_repo(tmp_path: Path) -> Path:
    """Builds a minimal repo whose 'entrypoint' imports a repo-local helper."""
    repo = tmp_path / "repo"
    (repo / "backtests").mkdir(parents=True)
    (repo / "helpers").mkdir(parents=True)
    (repo / "helpers" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "helpers" / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "backtests" / "fake_runner.py").write_text(
        "import json\nimport os\nfrom helpers.util import VALUE\nprint('ran', VALUE)\n",
        encoding="utf-8",
    )
    (repo / "out").mkdir(parents=True)
    return repo


def fake_fixture(targets, **kw) -> FixtureSpec:
    return FixtureSpec(
        fixture_id="fx_test",
        description="test fixture",
        entrypoint="backtests/fake_runner.py",
        argv=("--flag", "1"),
        targets=tuple(targets),
        **kw,
    )


def writer_runner(writes, returncode=0, stdout="ok", mutate=None):
    """Returns a runner that creates the given {relpath: content} files."""

    def _runner(cmd, cwd):
        for rel, content in writes.items():
            p = Path(cwd) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        if mutate:
            for rel, content in mutate.items():
                (Path(cwd) / rel).write_text(content, encoding="utf-8")
        return {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": "",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "finished_utc": "2026-01-01T00:00:01+00:00",
        }

    return _runner


def fake_git(mapping):
    def _git(args, repo_root):
        return mapping.get(tuple(args), "")

    return _git


# ---------------------------------------------------------------------------
# Worktree / untracked-python gates
# ---------------------------------------------------------------------------


def test_gate_blocks_untracked_py_inside_fixture_closure(tmp_path):
    git = fake_git(
        {
            ("diff", "--name-only"): "",
            ("diff", "--cached", "--name-only"): "",
            ("ls-files", "--others", "--exclude-standard"): "helpers/util.py\nnotes.md\n",
        }
    )
    res = check_worktree_gates(
        tmp_path, protected_paths=frozenset({"helpers/util.py"}), git_runner=git
    )
    assert res.passed is False
    assert "helpers/util.py" in res.disallowed_untracked_py
    assert "UNTRACKED_PY_IN_FIXTURE_CLOSURE" in res.blocking_reason


def test_gate_does_not_block_untracked_py_outside_every_closure(tmp_path):
    """New harness code elsewhere in the tree cannot affect the legacy entrypoint."""
    git = fake_git(
        {
            ("diff", "--name-only"): "",
            ("diff", "--cached", "--name-only"): "",
            ("ls-files", "--others", "--exclude-standard"): (
                "backtests/run_backtest.py\nbacktests/nt_runtime/modes/backtest.py\n"
            ),
        }
    )
    res = check_worktree_gates(
        tmp_path, protected_paths=frozenset({"backtests/run_w4_backtest.py"}), git_runner=git
    )
    assert res.passed is True
    assert res.disallowed_untracked_py == []
    assert "backtests/run_backtest.py" in res.untracked_py_outside_closure


def test_gate_allows_allowlisted_untracked_py(tmp_path):
    git = fake_git(
        {
            ("diff", "--name-only"): "",
            ("diff", "--cached", "--name-only"): "",
            ("ls-files", "--others", "--exclude-standard"): (
                "scripts/capture_baseline_fixtures.py\n"
                "scripts/tests/test_capture_baseline_fixtures.py\n"
                "REPORT.md\n"
            ),
        }
    )
    res = check_worktree_gates(
        tmp_path,
        protected_paths=frozenset({"scripts/capture_baseline_fixtures.py"}),
        git_runner=git,
    )
    assert res.passed is True
    assert res.disallowed_untracked_py == []


def test_module_shadowing_a_closure_import_is_caught(tmp_path):
    """A rogue file shadowing an imported module resolves INTO the closure."""
    repo = make_fake_repo(tmp_path)
    # 'helpers/util.py' is imported by the fake entrypoint, so it is in the closure.
    protected = selected_closure_paths([fake_fixture([])], repo)
    assert "helpers/util.py" in protected

    git = fake_git(
        {
            ("diff", "--name-only"): "",
            ("diff", "--cached", "--name-only"): "",
            ("ls-files", "--others", "--exclude-standard"): "helpers/util.py\n",
        }
    )
    res = check_worktree_gates(repo, protected_paths=protected, git_runner=git)
    assert res.passed is False


def test_gate_records_dirty_worktree_without_blocking(tmp_path):
    """Gates 1/2 are advisory and must be reported, not silently dropped."""
    git = fake_git(
        {
            ("diff", "--name-only"): "CLAUDE.md\ndocs/X.md\n",
            ("diff", "--cached", "--name-only"): "staged.py\n",
            ("ls-files", "--others", "--exclude-standard"): "",
        }
    )
    res = check_worktree_gates(tmp_path, git_runner=git)
    assert res.passed is True
    assert res.worktree_clean is False
    assert res.modified_tracked == ["CLAUDE.md", "docs/X.md"]
    assert res.staged == ["staged.py"]


def test_non_py_untracked_files_never_block(tmp_path):
    git = fake_git(
        {
            ("diff", "--name-only"): "",
            ("diff", "--cached", "--name-only"): "",
            ("ls-files", "--others", "--exclude-standard"): (
                "a.md\nb.json\nforensics/x.py.retired\n"
            ),
        }
    )
    res = check_worktree_gates(tmp_path, git_runner=git)
    assert res.passed is True
    assert res.untracked_py == []


# ---------------------------------------------------------------------------
# Resolved config + fill evidence
# ---------------------------------------------------------------------------


def test_w4_resolved_config_snapshot_materialises_all_inherited_fields():
    snap = snapshot_resolved_config(get_fixture("fixture_2_w4_b1"), REPO_ROOT)
    assert snap["status"] == "observed_from_config_class"
    fields = snap["resolved_fields"]
    # entry_qty is policy-derived in the runner (2 for B4, else 1)
    assert fields["entry_qty"] == 1
    assert fields["year"] == 2023
    assert fields["policy"] == "B1"
    # inherited BaselineFlipParityConfig defaults must be materialised, not omitted
    for inherited in ("sl_atr", "tp_atr", "ma_period", "ma_type", "trade_side", "be_level_atr"):
        assert inherited in fields


def test_score_fanning_resolved_config_records_the_import_failure_honestly():
    snap = snapshot_resolved_config(get_fixture("fixture_1_score_fanning"), REPO_ROOT)
    # The legacy config class cannot be imported in this environment; the snapshot
    # must say so rather than silently emitting a partial/derived config.
    assert snap["status"] in ("observed_from_config_class", "unavailable_config_class_unimportable")
    if snap["status"] == "unavailable_config_class_unimportable":
        assert "error" in snap
        assert snap["entrypoint_kwargs"]["checkpoint_dir"] == "backtests/results/checkpoints"


def test_fill_evidence_is_explicit_for_both_fixtures():
    from scripts.capture_baseline_fixtures import build_fill_evidence

    virtual = build_fill_evidence(get_fixture("fixture_1_score_fanning"))
    assert virtual["fill_artifact_present"] is False
    assert "no NT orders" in virtual["statement"] or "submits no" in virtual["statement"]

    simulated = build_fill_evidence(get_fixture("fixture_2_w4_b1"))
    assert simulated["fill_artifact_present"] is False
    assert "not persisted" in simulated["statement"]


# ---------------------------------------------------------------------------
# Status classification matrix
# ---------------------------------------------------------------------------


def test_status_vocabulary_is_exactly_the_four_defined_statuses():
    assert VALID_STATUSES == {
        STATUS_PRODUCED,
        STATUS_ABSENT_VERIFIED,
        STATUS_ABSENT_UNVERIFIED,
        STATUS_STALE_UNMANAGED,
    }


def test_no_year_derived_status_exists_in_module():
    """The retired `expected_absent_for_2023` label must not reappear."""
    src = (REPO_ROOT / "scripts" / "capture_baseline_fixtures.py").read_text(encoding="utf-8")
    assert "expected_absent_for_2023" not in src
    assert "expected_absent_for_" not in src


@pytest.mark.parametrize(
    "preexisting,quarantined,post_exists,pre,post,pre_mt,post_mt,expected",
    [
        # absent before -> produced
        (False, False, True, None, "h1", None, 100.0, STATUS_PRODUCED),
        # absent before, still absent -> provable absence
        (False, False, False, None, None, None, None, STATUS_ABSENT_VERIFIED),
        # quarantined, nothing written -> provable absence
        (True, True, False, "h0", None, 50.0, None, STATUS_ABSENT_VERIFIED),
        # quarantined, written -> produced
        (True, True, True, "h0", "h1", 50.0, 100.0, STATUS_PRODUCED),
        # pre-existing, run deleted it -> cannot verify
        (True, False, False, "h0", None, 50.0, None, STATUS_ABSENT_UNVERIFIED),
        # pre-existing, content changed -> produced
        (True, False, True, "h0", "h1", 50.0, 100.0, STATUS_PRODUCED),
        # pre-existing, identical content but rewritten (mtime advanced) -> produced
        (True, False, True, "h0", "h0", 50.0, 100.0, STATUS_PRODUCED),
        # pre-existing, untouched -> neither produced nor provably absent
        (True, False, True, "h0", "h0", 50.0, 50.0, STATUS_ABSENT_UNVERIFIED),
    ],
)
def test_classify_target_matrix(
    preexisting, quarantined, post_exists, pre, post, pre_mt, post_mt, expected
):
    status, _note = classify_target(preexisting, quarantined, post_exists, pre, post, pre_mt, post_mt)
    assert status == expected
    assert status in VALID_STATUSES


def test_identical_content_rewritten_is_attributed_via_mtime():
    status, note = classify_target(True, False, True, "same", "same", 50.0, 100.0)
    assert status == STATUS_PRODUCED
    assert note is not None and "modification timestamp" in note


def test_untouched_preexisting_file_is_not_attributed_to_the_run():
    status, note = classify_target(True, False, True, "same", "same", 50.0, 50.0)
    assert status == STATUS_ABSENT_UNVERIFIED
    assert note is not None and "not modified by the run" in note


# ---------------------------------------------------------------------------
# Preservation / restoration lifecycle
# ---------------------------------------------------------------------------


def test_absent_target_is_copied_to_evidence_then_removed(tmp_path):
    repo = make_fake_repo(tmp_path)
    fx = fake_fixture([TargetSpec("out/new.txt", "produced", hash_output=False)])
    runner = writer_runner({"out/new.txt": "fresh"})

    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=runner, collect_catalog_bounds=False)

    t = section["targets"][0]
    assert t["status"] == STATUS_PRODUCED
    assert t["preexisting_before_run"] is False
    # Working tree restored: the newly created file is gone.
    assert not (repo / "out" / "new.txt").exists()
    assert t["restored_to_original_state"] is True
    # Evidence retained.
    assert (tmp_path / "cap" / t["evidence_copy"]).read_text() == "fresh"


def test_preexisting_target_overwritten_is_restored_exactly(tmp_path):
    repo = make_fake_repo(tmp_path)
    original = repo / "out" / "existing.txt"
    original.write_text("ORIGINAL", encoding="utf-8")

    fx = fake_fixture([TargetSpec("out/existing.txt", "produced", hash_output=False)])
    runner = writer_runner({"out/existing.txt": "OVERWRITTEN"})

    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=runner, collect_catalog_bounds=False)

    t = section["targets"][0]
    assert t["status"] == STATUS_PRODUCED
    assert t["preexisting_before_run"] is True
    assert t["restored_to_original_state"] is True
    assert original.read_text() == "ORIGINAL"           # exact original state
    # The run's output was captured before restoration.
    assert (tmp_path / "cap" / t["evidence_copy"]).read_text() == "OVERWRITTEN"
    # And the original was preserved.
    assert (tmp_path / "cap" / t["preserved_to"]).read_text() == "ORIGINAL"


def test_preexisting_conditional_target_is_quarantined_and_restored(tmp_path):
    """Quarantine proves a fresh absence, then the original must come back."""
    repo = make_fake_repo(tmp_path)
    stale = repo / "out" / "cond.txt"
    stale.write_text("STALE", encoding="utf-8")

    fx = fake_fixture([TargetSpec("out/cond.txt", "conditional", hash_output=False)])
    runner = writer_runner({})  # run produces nothing

    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=runner, collect_catalog_bounds=False)

    t = section["targets"][0]
    assert t["quarantined_to_prove_absence"] is True
    assert t["status"] == STATUS_ABSENT_VERIFIED
    assert stale.read_text() == "STALE"
    assert t["restored_to_original_state"] is True


def test_untouched_preexisting_target_is_not_attributed(tmp_path):
    """A 'produced' target the run never wrote must not be claimed as output."""
    repo = make_fake_repo(tmp_path)
    (repo / "out" / "p.txt").write_text("X", encoding="utf-8")

    fx = fake_fixture([TargetSpec("out/p.txt", "produced", hash_output=False)])
    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=writer_runner({}), collect_catalog_bounds=False)

    t = section["targets"][0]
    assert t["status"] == STATUS_ABSENT_UNVERIFIED
    assert "not modified by the run" in t["attribution_note"]
    assert (repo / "out" / "p.txt").read_text() == "X"


def test_stale_unmanaged_files_are_recorded_and_left_in_place(tmp_path):
    repo = make_fake_repo(tmp_path)
    (repo / "out" / "w4_parity_2025_B1.parquet").write_text("old", encoding="utf-8")

    fx = fake_fixture(
        [TargetSpec("out/w4_parity_2023_B1.parquet", "conditional", hash_output=False)],
        stale_watch_globs=("out/w4_parity_*.parquet",),
    )
    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=writer_runner({}), collect_catalog_bounds=False)

    stale = section["preexisting_stale_unmanaged"]
    assert len(stale) == 1
    assert stale[0]["path"] == "out/w4_parity_2025_B1.parquet"
    assert stale[0]["status"] == STATUS_STALE_UNMANAGED
    assert (repo / "out" / "w4_parity_2025_B1.parquet").exists()  # untouched


# ---------------------------------------------------------------------------
# Real fixture declarations: R5 and W4 parity semantics
# ---------------------------------------------------------------------------


def test_r5_target_is_conditional_with_code_grounded_absence_cause():
    fx = get_fixture("fixture_1_score_fanning")
    r5 = next(t for t in fx.targets if t.path.endswith("results_R5.parquet"))
    assert r5.expectation == "conditional"
    assert r5.quarantine_required is True          # absence must be provable
    assert "0.55" in r5.absence_cause and "0.62" in r5.absence_cause


def test_r25_target_is_expected_produced():
    fx = get_fixture("fixture_1_score_fanning")
    r25 = next(t for t in fx.targets if t.path.endswith("results_R2.5.parquet"))
    assert r25.expectation == "produced"


def test_w4_parity_is_conditional_on_parity_logs_not_on_year():
    fx = get_fixture("fixture_2_w4_b1")
    parity = next(t for t in fx.targets if "w4_parity" in t.path)
    assert parity.expectation == "conditional"
    assert parity.quarantine_required is True
    cause = parity.absence_cause
    assert "parity_logs" in cause
    assert "NOT of --year" in cause or "not of --year" in cause.lower()


def test_w4_stale_glob_catches_other_year_parity_files():
    fx = get_fixture("fixture_2_w4_b1")
    assert any("w4_parity_*" in g for g in fx.stale_watch_globs)


def test_w4_primary_outputs_declared():
    fx = get_fixture("fixture_2_w4_b1")
    paths = {t.path for t in fx.targets}
    assert any(p.endswith("NQ_2023_B1/trades.parquet") for p in paths)
    assert any(p.endswith("NQ_2023_B1/strategy_trades.parquet") for p in paths)


# ---------------------------------------------------------------------------
# Normalized comparison rules
# ---------------------------------------------------------------------------


def test_normalized_identity_ignores_volatile_columns_and_row_order(tmp_path):
    a = tmp_path / "a.parquet"
    b = tmp_path / "b.parquet"
    pd.DataFrame(
        {"trade_id": [1, 2], "pnl": [10.0, -5.0], "trader_id": ["W4-BACKTESTER", "W4-BACKTESTER"]}
    ).to_parquet(a, index=False)
    pd.DataFrame(
        {"trade_id": [2, 1], "pnl": [-5.0, 10.0], "trader_id": ["OTHER-ID", "OTHER-ID"]}
    ).to_parquet(b, index=False)

    ia, ib = normalized_parquet_identity(a), normalized_parquet_identity(b)
    assert ia["normalized_sha256"] == ib["normalized_sha256"]
    assert ia["columns_excluded_volatile"] == ["trader_id"]
    assert compare_normalized(ia, ib)["equivalent"] is True


def test_normalized_identity_detects_value_change(tmp_path):
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    pd.DataFrame({"px": [100.25, 100.50]}).to_parquet(a, index=False)
    pd.DataFrame({"px": [100.25, 100.75]}).to_parquet(b, index=False)
    cmp = compare_normalized(normalized_parquet_identity(a), normalized_parquet_identity(b))
    assert cmp["equivalent"] is False
    assert "normalized content hash differs" in cmp["differences"]


def test_normalized_identity_detects_row_count_change(tmp_path):
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    pd.DataFrame({"px": [1.0, 2.0]}).to_parquet(a, index=False)
    pd.DataFrame({"px": [1.0]}).to_parquet(b, index=False)
    cmp = compare_normalized(normalized_parquet_identity(a), normalized_parquet_identity(b))
    assert cmp["equivalent"] is False
    assert any("row_count" in d for d in cmp["differences"])


def test_compare_normalized_reports_float_tolerance_is_not_row_level():
    """Tick-quantised prices must compare exactly; the tolerance is aggregate-only."""
    ref = {"row_count": 1, "columns_hashed": ["px"], "normalized_sha256": "a"}
    cand = {"row_count": 1, "columns_hashed": ["px"], "normalized_sha256": "b"}
    cmp = compare_normalized(ref, cand)
    assert cmp["equivalent"] is False
    assert cmp["float_rtol"] == 1e-9


# ---------------------------------------------------------------------------
# Source identity / invalidation
# ---------------------------------------------------------------------------


def test_source_change_during_run_invalidates_capture(tmp_path):
    repo = make_fake_repo(tmp_path)
    fx = fake_fixture([TargetSpec("out/x.txt", "produced", hash_output=False)])
    # The runner mutates a repo-local file inside the entrypoint's closure.
    runner = writer_runner({"out/x.txt": "v"}, mutate={"helpers/util.py": "VALUE = 999\n"})

    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=runner, collect_catalog_bounds=False)

    assert section["status"] == "INVALIDATED_SOURCE_CHANGED_DURING_RUN"
    assert section["source_closure"]["stable_across_run"] is False
    assert "helpers/util.py" in section["source_closure"]["drifted_files"]


def test_stable_source_yields_success(tmp_path):
    repo = make_fake_repo(tmp_path)
    fx = fake_fixture([TargetSpec("out/x.txt", "produced", hash_output=False)])
    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=writer_runner({"out/x.txt": "v"}),
                              collect_catalog_bounds=False)
    assert section["status"] == "SUCCESS"
    assert section["source_closure"]["stable_across_run"] is True


def test_nonzero_returncode_marks_failed_unmodified(tmp_path):
    repo = make_fake_repo(tmp_path)
    fx = fake_fixture([TargetSpec("out/x.txt", "produced", hash_output=False)])
    section = capture_fixture(fx, tmp_path / "cap", repo_root=repo,
                              runner=writer_runner({}, returncode=1),
                              collect_catalog_bounds=False)
    assert section["status"] == "FAILED_UNMODIFIED"


def test_closure_follows_repo_local_imports_only(tmp_path):
    repo = make_fake_repo(tmp_path)
    closure = resolve_repo_local_closure(repo / "backtests" / "fake_runner.py", repo)
    assert "backtests/fake_runner.py" in closure
    assert "helpers/util.py" in closure
    # stdlib imports (json, os) are not repo-local and must not appear
    assert not any(c in ("json.py", "os.py") for c in closure)


# ---------------------------------------------------------------------------
# Closure completeness
# ---------------------------------------------------------------------------


def build_closure_repo(tmp_path: Path) -> Path:
    """A repo exercising every discovery mechanism the resolver must handle."""
    repo = tmp_path / "repo"
    (repo / "pkg" / "sub").mkdir(parents=True)
    (repo / "plain").mkdir(parents=True)
    (repo / "dyn").mkdir(parents=True)

    # Package with __init__.py at BOTH levels -> both execute on import
    (repo / "pkg" / "__init__.py").write_text("PKG = 1\n", encoding="utf-8")
    (repo / "pkg" / "sub" / "__init__.py").write_text("SUB = 1\n", encoding="utf-8")
    (repo / "pkg" / "sub" / "leaf.py").write_text(
        "from plain.deep import DEEP\n", encoding="utf-8"
    )

    # Namespace-style directory (no __init__.py) with a nested chain
    (repo / "plain" / "deep.py").write_text("from plain.deeper import X\nDEEP = 1\n", encoding="utf-8")
    (repo / "plain" / "deeper.py").write_text("X = 1\n", encoding="utf-8")

    # Dynamically resolved module, referenced only as a string literal
    (repo / "dyn" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "dyn" / "registered_strategy.py").write_text("class S: pass\n", encoding="utf-8")

    (repo / "entry.py").write_text(
        "import os\n"
        "import pkg.sub.leaf\n"
        "from plain import deep\n"
        "REGISTRY = {'thing': {'module_path': 'dyn.registered_strategy',\n"
        "                      'class_name': 'S'}}\n"
        "STUDY_CLASS = 'dyn.registered_strategy.S'\n",
        encoding="utf-8",
    )
    return repo


def test_closure_includes_ancestor_package_inits(tmp_path):
    """Importing pkg.sub.leaf executes pkg/__init__.py and pkg/sub/__init__.py."""
    repo = build_closure_repo(tmp_path)
    detail = resolve_repo_local_closure_detailed(repo / "entry.py", repo)

    assert detail["pkg/__init__.py"] == "package_init"
    assert detail["pkg/sub/__init__.py"] == "package_init"
    assert detail["pkg/sub/leaf.py"] == "static_import"


def test_closure_follows_nested_transitive_imports(tmp_path):
    """entry -> pkg.sub.leaf -> plain.deep -> plain.deeper must all be captured."""
    repo = build_closure_repo(tmp_path)
    detail = resolve_repo_local_closure_detailed(repo / "entry.py", repo)

    assert "plain/deep.py" in detail
    assert "plain/deeper.py" in detail, "transitive third-level import was dropped"


def test_closure_handles_from_package_import_module(tmp_path):
    """`from plain import deep` names a submodule, not an attribute."""
    repo = build_closure_repo(tmp_path)
    detail = resolve_repo_local_closure_detailed(repo / "entry.py", repo)
    assert "plain/deep.py" in detail


def test_closure_captures_dynamically_resolved_strategy_modules(tmp_path):
    """Registry `module_path` strings are never seen by an import-only walk."""
    repo = build_closure_repo(tmp_path)
    detail = resolve_repo_local_closure_detailed(repo / "entry.py", repo)

    assert "dyn/registered_strategy.py" in detail, (
        "dynamically resolved strategy module missing from closure"
    )
    assert detail["dyn/registered_strategy.py"] == "dynamic_string_literal"
    # its package __init__ executes too
    assert detail["dyn/__init__.py"] == "package_init"


def test_closure_ignores_dotted_strings_that_are_not_repo_modules(tmp_path):
    """A dotted string that resolves to nothing must not inflate the closure."""
    repo = build_closure_repo(tmp_path)
    (repo / "entry.py").write_text(
        "MSG = 'nautilus_trader.model.data'\nOTHER = 'some.thing.absent'\n", encoding="utf-8"
    )
    detail = resolve_repo_local_closure_detailed(repo / "entry.py", repo)
    assert list(detail) == ["entry.py"]


def test_real_fixture_closures_are_complete_and_provenanced():
    """Regression: fixture 1's closure previously omitted utils/__init__.py."""
    f1 = resolve_repo_local_closure_detailed(
        REPO_ROOT / "backtests/run_staged_backtest.py", REPO_ROOT
    )
    assert "utils/__init__.py" in f1
    assert f1["utils/__init__.py"] == "package_init"
    assert "strategies/score_fanning_strategy.py" in f1
    for mod in ("checkpoint", "data", "fanning", "progress", "registry"):
        assert f"utils/runner/{mod}.py" in f1

    f2 = resolve_repo_local_closure_detailed(
        REPO_ROOT / "backtests/run_w4_backtest.py", REPO_ROOT
    )
    assert "backtests/run_w4_backtest.py" in f2
    assert "strategies/w4_exit_strategy.py" in f2
    assert "backtests/baseline_flip_parity/strategy.py" in f2
    # Completeness is a claim about executed files: assert no repo-local package
    # __init__.py on any of those import paths was missed.
    for pkg in ("backtests", "strategies", "backtests/baseline_flip_parity"):
        init = REPO_ROOT / pkg / "__init__.py"
        assert init.is_file() == (f"{pkg}/__init__.py" in f2), (
            f"{pkg}/__init__.py existence and closure membership disagree"
        )


def test_every_closure_entry_has_a_discovery_reason():
    for entry in ("backtests/run_staged_backtest.py", "backtests/run_w4_backtest.py"):
        detail = resolve_repo_local_closure_detailed(REPO_ROOT / entry, REPO_ROOT)
        assert detail
        assert all(
            v in ("entrypoint", "static_import", "package_init", "dynamic_string_literal")
            for v in detail.values()
        )


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_plan_executes_nothing_and_reports_provability(tmp_path):
    repo = make_fake_repo(tmp_path)
    (repo / "out" / "cond.txt").write_text("stale", encoding="utf-8")
    fx = fake_fixture(
        [
            TargetSpec("out/cond.txt", "conditional", hash_output=False),
            TargetSpec("out/fresh.txt", "produced", hash_output=False),
        ]
    )
    plan = build_dry_run_plan(fx, repo_root=repo)

    actions = {a["target_path"]: a for a in plan["planned_target_actions"]}
    assert actions["out/cond.txt"]["action"] == "quarantine -> run -> restore"
    assert actions["out/cond.txt"]["provable_absence"] is True
    assert actions["out/fresh.txt"]["provable_absence"] is True
    # Nothing was executed or modified.
    assert (repo / "out" / "cond.txt").read_text() == "stale"
    assert not (repo / "out" / "fresh.txt").exists()


def test_real_fixture_dry_run_plans_resolve():
    for fid in ("fixture_1_score_fanning", "fixture_2_w4_b1"):
        plan = build_dry_run_plan(get_fixture(fid))
        assert plan["entrypoint_exists"] is True
        assert plan["source_closure_file_count"] > 0
        assert len(plan["planned_target_actions"]) == len(get_fixture(fid).targets)
