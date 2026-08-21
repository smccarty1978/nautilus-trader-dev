"""Regression tests for the Red Team harness findings.

Source: `exports/FINAL_REDTEAM_BACKTEST_HARNESS_2026-08-16.md` — M3, W1, W4, N1.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtests.nt_runtime.modes.backtest import (  # noqa: E402
    BacktestContractError, MissingArtifactError, _assert_required_artifacts,
    _count_evaluator_trades,
)


# ===========================================================================
# M3 — no failed run may leave a SUCCESS manifest
# ===========================================================================


def _run_dir(tmp_path: Path, *, complete: bool) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "logs").mkdir(parents=True)
    names = ["run_manifest.json", "resolved_config.json", "execution_metrics.json", "summary.json"]
    if not complete:
        names.remove("summary.json")
    for name in names:
        (run_dir / name).write_text("{}", encoding="utf-8")
    return run_dir


def test_m3_required_artifact_check_still_raises(tmp_path):
    with pytest.raises(MissingArtifactError, match="REQUIRED_ARTIFACTS_MISSING"):
        _assert_required_artifacts(_run_dir(tmp_path, complete=False), "virtual", {})


def test_m3_assertion_precedes_success_persistence_in_source():
    """THE EXPLOIT: the check ran after the SUCCESS manifest was already written.

    Asserted structurally: in `run_backtest_mode`, the guarded
    `_assert_required_artifacts(...)` call must appear BEFORE the final
    `status": "SUCCESS"` manifest update.
    """
    src = (REPO_ROOT / "backtests" / "nt_runtime" / "modes" / "backtest.py").read_text(
        encoding="utf-8"
    )
    body = src.split("def run_backtest_mode", 1)[1]
    assert_pos = body.index("_assert_required_artifacts(")
    success_pos = body.index('"status": "SUCCESS",')
    assert assert_pos < success_pos, (
        "artifact validation must run before the SUCCESS manifest is persisted"
    )


def test_m3_failure_path_persists_failed_incomplete_artifacts():
    """The failure branch must rewrite the manifest before re-raising."""
    src = (REPO_ROOT / "backtests" / "nt_runtime" / "modes" / "backtest.py").read_text(
        encoding="utf-8"
    )
    assert '"status": "FAILED_INCOMPLETE_ARTIFACTS"' in src
    failure_block = src.split("except MissingArtifactError", 1)[1].split("raise", 1)[0]
    assert "run_manifest.json" in failure_block, "manifest is not rewritten on failure"
    assert "FAILED_INCOMPLETE_ARTIFACTS" in failure_block


def test_m3_simulated_run_without_trades_artifact_is_incomplete(tmp_path):
    with pytest.raises(MissingArtifactError, match="trades.parquet"):
        _assert_required_artifacts(_run_dir(tmp_path, complete=True), "simulated_orders", {})


# ===========================================================================
# W1 — a virtual strategy must not pass as simulated_orders
# ===========================================================================


class _FakeTrade:
    pass


class _FakeEvaluator:
    def __init__(self, closed, active):
        self.name = "R2.5"
        self.trade_history = [_FakeTrade() for _ in range(closed)]
        self.active_trades = [_FakeTrade() for _ in range(active)]


class _VirtualStrategy:
    def __init__(self, closed=19, active=1):
        self.evaluators = [_FakeEvaluator(closed, active)]


def test_w1_counts_evaluator_trades():
    assert _count_evaluator_trades(_VirtualStrategy(19, 1)) == 20
    assert _count_evaluator_trades(object()) == 0


def test_w1_simulated_contract_rejects_virtual_strategy_with_zero_positions():
    """THE EXPLOIT: ScoreFanning under simulated_orders reported SUCCESS with an
    empty trades.parquet, silently discarding 20 real evaluator trades."""
    src = (REPO_ROOT / "backtests" / "nt_runtime" / "modes" / "backtest.py").read_text(
        encoding="utf-8"
    )
    assert "SIMULATED_CONTRACT_VIOLATED" in src
    # The guard must fire on: evaluator trades present AND zero broker positions.
    guard = src.split("SIMULATED_CONTRACT_VIOLATED", 1)[0]
    assert "evaluator_trades > 0" in guard
    assert 'positions_report_rows"] == 0' in guard


def test_w1_guard_precedes_output_writing():
    """The contract must be enforced before any artifact is written."""
    src = (REPO_ROOT / "backtests" / "nt_runtime" / "modes" / "backtest.py").read_text(
        encoding="utf-8"
    )
    branch = src.split("outputs = extract_simulated_outputs", 1)[1]
    assert branch.index("SIMULATED_CONTRACT_VIOLATED") < branch.index('artifacts["trades"]')


# ===========================================================================
# W4 — strategy_trades is required, not conditional
# ===========================================================================


def test_w4_strategy_trades_is_written_unconditionally():
    src = (REPO_ROOT / "backtests" / "nt_runtime" / "modes" / "backtest.py").read_text(
        encoding="utf-8"
    )
    branch = src.split("outputs = extract_simulated_outputs", 1)[1].split("summary = summarize_simulated", 1)[0]
    assert 'if not outputs["strategy_trades"].empty:' not in branch, (
        "strategy_trades is still written only when non-empty"
    )
    assert 'artifacts["strategy_trades"]' in branch


def test_w4_golden_assertion_is_unconditional():
    src = (REPO_ROOT / "scripts" / "tests" / "test_nt_runner_backtest.py").read_text(
        encoding="utf-8"
    )
    block = src.split("def test_w4_harness_matches_frozen_baseline", 1)[1]
    assert 'if "strategy_trades.parquet" in ref and' not in block, (
        "the strategy_trades equivalence assertion is still guarded by an `if`"
    )
    assert 'assert "strategy_trades" in result["artifacts"]' in block


# ===========================================================================
# N1 — the documented example command must actually work
# ===========================================================================


def test_n1_documented_example_has_no_invalid_param():
    doc = (REPO_ROOT / "docs" / "BACKTEST_EXECUTION.md").read_text(encoding="utf-8")
    assert "policies_preset" not in doc, "the invalid --param example is still documented"


def test_n1_documented_example_dry_runs_successfully():
    """Execute the documented command with --dry-run; it must resolve, not error."""
    cmd = [
        sys.executable, "backtests/run_backtest.py",
        "--strategy", "score_fanning_strategy", "--symbol", "NQ",
        "--start-date", "2023-03-03", "--end-date", "2023-03-03",
        "--warmup-days", "5", "--order-handling", "virtual", "--dry-run",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"documented example failed:\n{proc.stdout}\n{proc.stderr}"
    plan = json.loads(proc.stdout)
    assert plan["status"] == "RESOLVED"
    assert plan["plan"]["execution_mode"]["order_handling"] == "virtual"


def test_n1_undeclared_param_is_still_rejected_with_the_field_list():
    proc = subprocess.run(
        [sys.executable, "backtests/run_backtest.py",
         "--strategy", "score_fanning_strategy", "--symbol", "NQ",
         "--start-date", "2023-03-03", "--end-date", "2023-03-03",
         "--param", "policies_preset=r5_r25", "--dry-run"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "UNKNOWN_PARAMETER" in proc.stderr
    assert "policies" in proc.stderr        # the real field is listed
