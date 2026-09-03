"""Red-team packet F3: --execute-authorized is a real execution gate, not ceremonial.

Every V2 stage after "seal" (smoke, collection, reconcile, merge, fit, freeze, oos,
analyze, close) is refused with blocker_code EXECUTION_NOT_AUTHORIZED unless
V2Options.execute is True -- checked by the controller before the run lock is even
acquired, and independently inside each lifecycle leaf so a direct programmatic caller
cannot bypass the controller either.
"""
from __future__ import annotations

import json

import pytest

from research_workflow.governed_controller_v2 import V2StudyController
from research_workflow.lifecycle_v2 import LifecycleV2Error, V2Lifecycle, V2Options
from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
from research_workflow.tests.test_lifecycle_v2 import GOLDEN, ROOT, _study_dir, _write_audit, synthetic_bars  # noqa: F401

NS = 1_000_000_000


def _through_seal(tmp_path, synthetic_bars, monkeypatch, *, execute: bool):
    bars, expected = synthetic_bars
    study = _study_dir(tmp_path)
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    opts = V2Options(execute=execute, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True,
                     closure={"outcome": "SYNTHETIC_FLOW_COMPLETE", "terminal_decision": "PLATFORM_V2_FLOW_PROVEN"})
    monkeypatch.setattr(V2StudyController, "_worktree", lambda self: {"path": str(ROOT), "branch": "test", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []})
    ctl = lambda: V2StudyController(study, options=opts, repo_root=ROOT)
    ctl().run(through="tests")
    ctl().run(through="seal")
    from research_workflow.lifecycle_v2 import ingest_audit_report
    ingest_audit_report(study, "causal", _write_audit(study, "causal", "auditor_a"))
    ctl().run(through="seal")
    ingest_audit_report(study, "contract", _write_audit(study, "contract", "auditor_b"))
    return study, ctl, opts


def test_through_seal_without_the_flag_proceeds(tmp_path, synthetic_bars, monkeypatch):
    study, ctl, _ = _through_seal(tmp_path, synthetic_bars, monkeypatch, execute=False)
    card = ctl().run(through="seal")
    assert card["STATUS"] == "OK" and card["state"] == "READY_TO_SMOKE", card


def test_through_collection_without_the_flag_is_blocked(tmp_path, synthetic_bars, monkeypatch):
    study, ctl, _ = _through_seal(tmp_path, synthetic_bars, monkeypatch, execute=False)
    card = ctl().run(through="collection")
    assert card["STATUS"] == "BLOCKED" and card["blocker_code"] == "EXECUTION_NOT_AUTHORIZED", card
    # never touched the lock or ran anything post-seal
    assert not (study / "_work" / "controller" / "run.lock").is_file()
    assert card["actions_executed"] == []


def test_through_smoke_with_the_flag_runs(tmp_path, synthetic_bars, monkeypatch):
    study, ctl, _ = _through_seal(tmp_path, synthetic_bars, monkeypatch, execute=True)
    card = ctl().run(through="smoke")
    assert card["STATUS"] == "OK" and card["state"] == "READY_TO_COLLECT", card


def test_direct_lifecycle_collection_without_execute_raises(tmp_path, synthetic_bars, monkeypatch):
    study, ctl, opts = _through_seal(tmp_path, synthetic_bars, monkeypatch, execute=True)
    ctl().run(through="seal")
    # A direct programmatic caller (bypassing the controller) is refused too, even though
    # the study has already sealed and opts.execute was True at controller time -- construct
    # a fresh V2Lifecycle with execute=False to simulate the bypass.
    bars, expected = synthetic_bars
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    bypass_opts = V2Options(execute=False, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                            bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True)
    lc = V2Lifecycle(study, repo_root=ROOT, options=bypass_opts)
    with pytest.raises(LifecycleV2Error, match="EXECUTION_NOT_AUTHORIZED"):
        lc.collection()
