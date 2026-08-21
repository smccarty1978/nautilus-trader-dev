"""Run/failure artifact lifecycle and bounded date authorization (H1, H2, date scope).

H1 -- ``audit/failure_packet.json`` read ``BLOCKED`` beside an ``audit/preflight.json``
that read ``CLEAR``. Neither carried a generation id, timestamp or binding hash, so a
consumer could not tell which described the current state.

H2 -- six of ten ES run directories were left at ``RUNNING`` with no ``status.json`` and
no outputs, because the manifest was only ever updated on the success path.

Date scope -- the acceptance request intended 2024-09-03/04/05 while ``train: [2024]``
authorized every day of 2024. Year-level chronology cannot express a three-day scope, so
the contract could not distinguish the intended scope from the permitted one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

from backtests.nt_runtime.data_plan import (  # noqa: E402
    UnauthorizedExecutionDomainError,
    enforce_authorized_dates,
    resolve_authorized_dates,
)
from scripts.reconcile_runs import classify_run, reconcile_runs  # noqa: E402


# ---------------------------------------------------------------------------
# H1 -- current vs historical preflight state
# ---------------------------------------------------------------------------

def _run_preflight(study: Path, extra=()):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "research_preflight.py"),
         "--study", str(study), "--skip-tests", *extra],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


def test_preflight_artifacts_carry_a_generation_identity(tmp_path):
    """H1.1 -- every preflight artifact says which run produced it and when."""
    audit = tmp_path / "audit"
    audit.mkdir(parents=True)
    res = _run_preflight(tmp_path)
    assert (audit / "preflight.json").exists(), res.stdout + res.stderr
    data = json.loads((audit / "preflight.json").read_text(encoding="utf-8"))
    assert data["preflight_run_id"]
    assert data["generated_at_utc"]


def test_clear_preflight_supersedes_but_does_not_delete_a_failure_packet(tmp_path):
    """H1.2 -- the exact historical ambiguity, resolved without destroying evidence."""
    audit = tmp_path / "audit"
    audit.mkdir(parents=True)
    stale = {
        "status": "BLOCKED",
        "failed_gate": "CAUSAL_LINT",
        "failure_ids": ["OLD_FINDING"],
        "failure_details": [],
    }
    (audit / "failure_packet.json").write_text(json.dumps(stale), encoding="utf-8")

    res = _run_preflight(tmp_path)
    pre = json.loads((audit / "preflight.json").read_text(encoding="utf-8"))
    packet = json.loads((audit / "failure_packet.json").read_text(encoding="utf-8"))

    assert (audit / "failure_packet.json").exists(), "forensic evidence must not be deleted"
    if pre["status"] == "CLEAR":
        assert packet["superseded"] is True
        assert packet["superseded_by_preflight_run_id"] == pre["preflight_run_id"]
        assert packet["failure_ids"] == ["OLD_FINDING"], "history must survive verbatim"
    else:
        # A genuinely blocked preflight writes a *current* packet.
        assert packet["superseded"] is False
        assert packet["preflight_run_id"] == pre["preflight_run_id"]


def test_blocked_preflight_packet_is_bound_to_its_own_run(tmp_path):
    """A current packet is identified by the run that produced it, not by mere presence."""
    audit = tmp_path / "audit"
    audit.mkdir(parents=True)
    (tmp_path / "study.yaml").write_text("not: valid: yaml: {", encoding="utf-8")
    _run_preflight(tmp_path)
    pre = json.loads((audit / "preflight.json").read_text(encoding="utf-8"))
    if pre["status"] == "BLOCKED":
        packet = json.loads((audit / "failure_packet.json").read_text(encoding="utf-8"))
        assert packet["preflight_run_id"] == pre["preflight_run_id"]
        assert packet["superseded"] is False


# ---------------------------------------------------------------------------
# H2 -- interrupted runs reach a terminal state
# ---------------------------------------------------------------------------

def _mk_run(root: Path, name: str, manifest: dict, status: dict | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if status is not None:
        (d / "status.json").write_text(json.dumps(status), encoding="utf-8")
    return d


def test_running_manifest_with_a_dead_pid_is_abandoned(tmp_path):
    """H2.1 -- the historical six runs. A dead process cannot write its own epitaph."""
    d = _mk_run(tmp_path, "r1", {"study_id": "s", "status": "RUNNING", "pid": 999999})
    rec = classify_run(d)
    assert rec["state"] == "ABANDONED"
    assert "not alive" in rec["reason"]


def test_running_manifest_with_a_live_pid_is_still_running(tmp_path):
    """An in-flight run must not be misfiled as abandoned."""
    d = _mk_run(tmp_path, "r2", {"study_id": "s", "status": "RUNNING", "pid": os.getpid()})
    assert classify_run(d)["state"] == "RUNNING"


def test_running_manifest_with_no_pid_is_abandoned(tmp_path):
    """'Unknown' is not evidence of liveness; the historical manifests recorded no pid."""
    d = _mk_run(tmp_path, "r3", {"study_id": "s", "status": "RUNNING"})
    rec = classify_run(d)
    assert rec["state"] == "ABANDONED"
    assert "no pid" in rec["reason"]


def test_successful_run_keeps_its_own_terminal_status(tmp_path):
    d = _mk_run(tmp_path, "r4",
                {"study_id": "s", "status": "COMPLETED"},
                {"status": "SUCCESS"})
    assert classify_run(d)["state"] == "SUCCESS"


def test_failed_validation_is_a_distinct_terminal_state(tmp_path):
    d = _mk_run(tmp_path, "r5",
                {"study_id": "s", "status": "FAILED_VALIDATION"},
                {"status": "FAILED_VALIDATION"})
    assert classify_run(d)["state"] == "FAILED_VALIDATION"


def test_corrupt_manifest_is_reported_not_ignored(tmp_path):
    d = tmp_path / "r6"
    d.mkdir()
    (d / "run_manifest.json").write_text("{broken", encoding="utf-8")
    assert classify_run(d)["state"] == "CORRUPT"


def test_reconciliation_writes_a_sidecar_and_preserves_the_manifest(tmp_path):
    """H2.2 -- historical run artifacts are never rewritten or deleted."""
    d = _mk_run(tmp_path, "r7", {"study_id": "s", "status": "RUNNING", "pid": 999999})
    original = (d / "run_manifest.json").read_bytes()

    report = reconcile_runs(tmp_path, write=True)
    assert report["counts"]["ABANDONED"] == 1
    assert (d / "run_manifest.json").read_bytes() == original, "manifest was mutated"

    sidecar = json.loads((d / "lifecycle.json").read_text(encoding="utf-8"))
    assert sidecar["terminal_state"] == "ABANDONED"
    assert sidecar["reconciled_by"] == "scripts/reconcile_runs.py"


def test_live_run_gets_no_sidecar(tmp_path):
    d = _mk_run(tmp_path, "r8", {"study_id": "s", "status": "RUNNING", "pid": os.getpid()})
    reconcile_runs(tmp_path, write=True)
    assert not (d / "lifecycle.json").exists()


def test_collect_mode_finalizes_a_failed_run():
    """The runtime records a terminal status on the failure path, not only on success."""
    import inspect
    from backtests.nt_runtime.modes import collect

    src = inspect.getsource(collect.run_collect_mode)
    assert "finalize_failed" in src
    assert "ABORTED" in src and "FAILED" in src


# ---------------------------------------------------------------------------
# Exact bounded date authorization
# ---------------------------------------------------------------------------

def _study(dates=None):
    """A compiled-study stand-in carrying only what the date gate reads."""
    return SimpleNamespace(
        spec=SimpleNamespace(
            execution=SimpleNamespace(
                data_requirements={"authorized_dates": dates} if dates else None
            )
        )
    )


ACCEPTANCE_DATES = ["2024-09-03", "2024-09-04", "2024-09-05"]


def test_no_declared_dates_leaves_year_gates_as_the_only_authority():
    """Backwards compatible: a study that declares nothing is unaffected."""
    assert resolve_authorized_dates(_study()) is None
    assert enforce_authorized_dates(_study(), "2024-01-01", "2024-12-31") is None


def test_authorized_date_is_admitted():
    assert enforce_authorized_dates(_study(ACCEPTANCE_DATES), "2024-09-03", "2024-09-03") == \
        ACCEPTANCE_DATES


def test_unauthorized_date_inside_an_authorized_year_is_refused():
    """The whole point: `train: [2024]` is not authorization for 2024-09-06."""
    with pytest.raises(UnauthorizedExecutionDomainError, match="UNAUTHORIZED_EXECUTION_DATE"):
        enforce_authorized_dates(_study(ACCEPTANCE_DATES), "2024-09-06", "2024-09-06")


def test_window_spanning_an_unauthorized_gap_is_refused():
    """A range is checked day by day, so a permitted range cannot smuggle a gap."""
    dates = ["2024-09-03", "2024-09-05"]        # 09-04 deliberately absent
    with pytest.raises(UnauthorizedExecutionDomainError, match="2024-09-04"):
        enforce_authorized_dates(_study(dates), "2024-09-03", "2024-09-05")


def test_full_authorized_window_is_admitted():
    assert enforce_authorized_dates(_study(ACCEPTANCE_DATES), "2024-09-03", "2024-09-05")


def test_malformed_authorized_dates_fail_closed():
    with pytest.raises(UnauthorizedExecutionDomainError, match="MALFORMED_AUTHORIZED_DATES"):
        resolve_authorized_dates(_study("2024-09-03"))
    with pytest.raises(UnauthorizedExecutionDomainError, match="MALFORMED_AUTHORIZED_DATES"):
        resolve_authorized_dates(_study(["not-a-date"]))


def test_full_stage_of_a_date_bounded_study_does_not_expand_to_the_year():
    """H/date -- `--stage full` must not exceed the authorization."""
    from backtests.nt_runtime.run_plan import RunStage, resolve_run_plan

    compiled = SimpleNamespace(
        spec=SimpleNamespace(
            chronology=SimpleNamespace(train=[2024], dev=[], diagnostic=[], prohibited=[2025, 2026]),
            execution=SimpleNamespace(data_requirements={"authorized_dates": ACCEPTANCE_DATES}),
        )
    )
    plan = resolve_run_plan(compiled, stage=RunStage.FULL)
    assert plan.start_date == "2024-09-03"
    assert plan.end_date == "2024-09-05"


def test_day_stage_defaults_to_the_first_authorized_date():
    from backtests.nt_runtime.run_plan import RunStage, resolve_run_plan

    compiled = SimpleNamespace(
        spec=SimpleNamespace(
            chronology=SimpleNamespace(train=[2024], dev=[], diagnostic=[], prohibited=[]),
            execution=SimpleNamespace(data_requirements={"authorized_dates": ACCEPTANCE_DATES}),
        )
    )
    plan = resolve_run_plan(compiled, stage=RunStage.DAY)
    assert plan.start_date == plan.end_date == "2024-09-03"


def test_unbounded_study_keeps_its_previous_default():
    """A study without exact dates behaves exactly as before."""
    from backtests.nt_runtime.run_plan import RunStage, resolve_run_plan

    compiled = SimpleNamespace(
        spec=SimpleNamespace(
            chronology=SimpleNamespace(train=[2024], dev=[], diagnostic=[], prohibited=[]),
            execution=SimpleNamespace(data_requirements=None),
        )
    )
    plan = resolve_run_plan(compiled, stage=RunStage.DAY)
    assert plan.start_date == "2024-03-03"
