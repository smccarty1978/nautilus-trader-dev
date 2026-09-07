"""Date-bounded partition execution (``chronology.windows``).

A window NARROWS an already-authorized train/dev year to explicit inclusive dates. The tests
below pin the three properties the capability exists to guarantee:

1. a window can never open a year the role declarations did not already authorize;
2. a year that declares windows streams and emits only those dates, and says so in its manifest;
3. an authorization artifact that disagrees with the plan's windows refuses the run before a
   single bar is streamed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from research_workflow.grammar.compiler import compile_study, load_spec
from research_workflow.grammar.gaps import GapKind
from research_workflow.lifecycle_v2 import (LifecycleV2Error, authorized_windows, authorized_years,
                                            partition_windows, windows_identity)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000


def _spec(tmp_path: Path, chronology: dict) -> Path:
    body = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = "windows_probe"
    body["chronology"] = chronology
    study = tmp_path / "studies" / "windows_probe"
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return study


def _compile(tmp_path: Path, chronology: dict):
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    return compile_study(load_spec(_spec(tmp_path, chronology)), repo_root=ROOT,
                         datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)


def test_a_valid_window_compiles_ordered_and_role_tagged(tmp_path):
    out = _compile(tmp_path, {"train": [2029, 2030], "dev": [], "prohibited": [],
                              "windows": ["2030-01-05..2030-01-09", "2029-12-31..2029-12-31"]})
    assert out.ok, out.card()
    windows = out.plan.chronology["windows"]
    assert [w["id"] for w in windows] == ["2029-12-31_2029-12-31", "2030-01-05_2030-01-09"]
    assert {w["role"] for w in windows} == {"train"}
    assert windows_identity(windows) == ["2029:2029-12-31..2029-12-31", "2030:2030-01-05..2030-01-09"]


@pytest.mark.parametrize("windows,kind", [
    (["2030-01-05"], GapKind.INVALID_PARAMETERIZATION),               # not a range
    (["2030-13-01..2030-13-02"], GapKind.INVALID_PARAMETERIZATION),   # not a date
    (["2030-01-09..2030-01-05"], GapKind.INVALID_PARAMETERIZATION),   # ends before it starts
    (["2030-01-05..2030-01-06", "2030-01-06..2030-01-08"], GapKind.INVALID_PARAMETERIZATION),  # overlap
    (["2029-12-30..2030-01-02"], GapKind.SEMANTIC_DECISION_REQUIRED),  # crosses a year
])
def test_malformed_windows_are_typed_gaps(tmp_path, windows, kind):
    out = _compile(tmp_path, {"train": [2029, 2030], "dev": [], "prohibited": [], "windows": windows})
    assert not out.ok
    window_gaps = [g for g in out.gaps.to_dict()["gaps"] if str(g["where"]).startswith("chronology.windows")]
    assert window_gaps, out.card()
    assert kind.value in {g["kind"] for g in window_gaps}


def test_a_window_can_never_open_an_unauthorized_year(tmp_path):
    """The whole point of the capability: windows narrow, they never authorize."""
    for chronology in (
        {"train": [2030], "dev": [], "prohibited": [2024], "windows": ["2024-03-01..2024-03-31"]},   # prohibited
        {"train": [2030], "dev": [], "prohibited": [], "diagnostic": [2024], "windows": ["2024-03-01..2024-03-31"]},  # diagnostic-only
        {"train": [2030], "dev": [], "prohibited": [], "windows": ["2027-03-01..2027-03-31"]},       # undeclared
    ):
        out = _compile(tmp_path, chronology)
        assert not out.ok, chronology
        window_gaps = [g for g in out.gaps.to_dict()["gaps"] if str(g["where"]).startswith("chronology.windows")]
        assert {g["kind"] for g in window_gaps} == {GapKind.SEMANTIC_DECISION_REQUIRED.value}, chronology


def test_authorized_windows_may_only_narrow():
    plan = {"chronology": {"windows": [{"id": "2024-03-01_2024-03-31", "year": 2024, "start": "2024-03-01", "end": "2024-03-31", "role": "train"}]}}
    assert authorized_windows(plan, None) == plan["chronology"]["windows"]
    assert authorized_windows(plan, ["2024-03-01..2024-03-31"]) == plan["chronology"]["windows"]
    assert partition_windows(plan, 2024) == plan["chronology"]["windows"]
    assert partition_windows(plan, 2023) == []
    with pytest.raises(LifecycleV2Error, match="WINDOWS_NOT_AUTHORIZED"):
        authorized_windows(plan, ["2024-04-01..2024-04-30"])
    with pytest.raises(LifecycleV2Error, match="WINDOWS_NOT_AUTHORIZED"):
        authorized_windows(plan, [])


def test_stale_authorization_windows_refuse_the_run():
    plan = {"chronology": {"train": [2024], "dev": [], "prohibited": [2025],
                           "windows": [{"id": "2024-03-01_2024-03-31", "year": 2024, "start": "2024-03-01", "end": "2024-03-31", "role": "train"}]}}
    fresh = {"train_years": [2024], "oos_years": [], "prohibited_years": [2025],
             "partition_windows": ["2024:2024-03-01..2024-03-31"]}
    assert authorized_years(plan, "train", None, authorization=fresh) == [2024]
    for stale in ({**fresh, "partition_windows": []},
                  {**fresh, "partition_windows": ["2024:2024-04-01..2024-04-30"]}):
        with pytest.raises(LifecycleV2Error, match="WINDOWS_NOT_AUTHORIZED"):
            authorized_years(plan, "train", None, authorization=stale)


@pytest.fixture(scope="module")
def synthetic_bars():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    return bars, json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))


def test_a_windowed_partition_emits_only_the_declared_dates(tmp_path, synthetic_bars):
    """The golden fixture carries two sessions, 2029-12-31 and 2030-01-01. A window on the
    first must produce a 2029 partition containing only 2029-12-31 rows, a manifest that names
    the window, and a reconcile that passes against the windows rather than the calendar year."""
    import pandas as pd
    from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    bars, expected = synthetic_bars
    study = _spec(tmp_path, {"train": [2029], "dev": [], "prohibited": [],
                             "windows": ["2029-12-31..2029-12-31"]})
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    opts = V2Options(execute=True, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True)
    lc = V2Lifecycle(study, repo_root=ROOT, options=opts)
    lc.compile(); lc.prepare()

    auth = json.loads((study / "artifacts" / "experiment_authorization.json").read_text(encoding="utf-8"))
    assert auth["partition_windows"] == ["2029:2029-12-31..2029-12-31"]

    (study / "artifacts").mkdir(exist_ok=True)
    (study / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(
        {"composite_seal_hash": "seal", "execution_manifest_composite_sha256": "mfst"}), encoding="utf-8")
    out_dir = study / "_work" / "controller" / "partitions" / "train" / "2029"
    manifest = lc.run_partition(2029, "train", out_dir)

    assert manifest["date_bounded"] is True
    assert [w["window_id"] for w in manifest["windows"]] == ["2029-12-31_2029-12-31"]
    candidates = pd.read_parquet(out_dir / "candidates.parquet")
    assert len(candidates) > 0
    days = set(pd.to_datetime(candidates["observation_ts"], unit="ns", utc=True).dt.date.astype(str))
    assert days == {"2029-12-31"}

    receipt = lc.reconcile()
    assert receipt["status"] == "PASS"
    reconcile = json.loads((study / "_work" / "controller" / "reconcile.json").read_text(encoding="utf-8"))
    assert reconcile["passed"] is True
    assert reconcile["partition_windows"] == ["2029:2029-12-31..2029-12-31"]
