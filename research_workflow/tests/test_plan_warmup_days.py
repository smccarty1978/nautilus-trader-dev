"""The governed replay honours the compiled plan's declared warmup, and records the bar range it read.

Before chore/plan_warmup_days, V2Options.warmup_days was a fixed 5 that ignored the plan's
chronology.warmup.days_before_partition: a window starting on 2022-01-03 streamed 2021-12-29.. bars
although 2021 was prohibited, and a declared `days_before_partition: 0` still read 5 earlier days.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000


def _lifecycle(tmp_path, **opts):
    from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
    study = tmp_path / "studies" / "s"
    study.mkdir(parents=True)
    return V2Lifecycle(study, options=V2Options(**opts))


def _capture_catalog_warmup(monkeypatch):
    import research_workflow.host_runner as hr
    seen = {}

    def fake(plan, *, start_date, end_date, warmup_days, **kw):
        seen.update(start=start_date, end=end_date, warmup_days=warmup_days)
        return {"stats": {}}
    monkeypatch.setattr(hr, "run_plan_on_catalog", fake)
    return seen


@pytest.mark.parametrize("declared,expected", [(0, 0), (3, 3), (5, 5)])
def test_replay_uses_declared_days_before_partition(tmp_path, monkeypatch, declared, expected):
    seen = _capture_catalog_warmup(monkeypatch)
    lc = _lifecycle(tmp_path)
    plan = {"chronology": {"warmup": {"days_before_partition": declared}}}
    lc._run_window(plan, "2022-01-10", "2022-01-21", (0, 1), progress=None)
    assert seen["warmup_days"] == expected


def test_replay_default_is_five_when_plan_declares_nothing(tmp_path, monkeypatch):
    seen = _capture_catalog_warmup(monkeypatch)
    _lifecycle(tmp_path)._run_window({"chronology": {}}, "2022-03-01", "2022-03-02", (0, 1), progress=None)
    assert seen["warmup_days"] == 5


def test_explicit_operator_override_wins(tmp_path, monkeypatch):
    seen = _capture_catalog_warmup(monkeypatch)
    lc = _lifecycle(tmp_path, warmup_days=2)
    lc._run_window({"chronology": {"warmup": {"days_before_partition": 0}}}, "2022-01-10", "2022-01-10", (0, 1), progress=None)
    assert seen["warmup_days"] == 2


def test_negative_declared_warmup_fails_closed(tmp_path):
    from research_workflow.lifecycle_v2 import LifecycleV2Error
    with pytest.raises(LifecycleV2Error, match="INVALID_WARMUP_DAYS"):
        _lifecycle(tmp_path)._warmup_days({"chronology": {"warmup": {"days_before_partition": -1}}})


def test_replay_binding_keys_on_the_declared_warmup(tmp_path, monkeypatch):
    """The partition-reuse key must carry the lead-in actually replayed, not the old fixed 5."""
    import research_workflow.replay_closure as rc
    seen = {}

    def fake_binding(plan, *, dataset, partition, authorization_sha256, warmup_days, repo_root=None):
        seen["warmup_days"] = warmup_days
        return {}
    monkeypatch.setattr(rc, "replay_closure_binding", fake_binding)
    lc = _lifecycle(tmp_path)
    plan = {"chronology": {"warmup": {"days_before_partition": 0}}, "instruments": {"NQ": {"role": "execution"}}}
    lc._replay_binding(plan, {"id": "train-2022"})
    assert seen["warmup_days"] == 0


def test_compiled_plan_carries_days_before_partition_where_the_replay_reads_it():
    """End-to-end on the compiler: the field the controller reads is where compile_study writes it."""
    from research_workflow.grammar.compiler import compile_study
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    import yaml
    spec = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    spec.setdefault("chronology", {})["warmup"] = {"days_before_partition": 0}
    out = compile_study(spec, repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, out.gaps.to_dict()
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "compiled_plan.json"
    out.plan.write(tmp)
    plan = json.loads(tmp.read_text(encoding="utf-8"))
    from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
    lc = V2Lifecycle(tmp.parent, options=V2Options())
    assert lc._warmup_days(plan) == 0


def test_host_stats_record_observed_bar_range():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.grammar.compiler import compile_study
    from research_workflow.host.interfaces import BarView
    from research_workflow.host_runner import run_plan_on_bars
    from research_workflow.sessions import build_session_table
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    import tempfile
    import yaml
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    out = compile_study(yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8")), repo_root=ROOT,
                        datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok
    tmp = Path(tempfile.mkdtemp()) / "compiled_plan.json"
    out.plan.write(tmp)
    plan = json.loads(tmp.read_text(encoding="utf-8"))
    table = build_session_table({"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]})
    run = run_plan_on_bars(plan, bars, session_table=table)
    rng = run["stats"]["bar_range"]
    by_stream = {}
    for b in bars:
        by_stream.setdefault(b.stream, []).append(b)
    assert set(rng) == {s for s in by_stream if run["stats"]["bars_by_stream"].get(s)}
    for s, r in rng.items():
        seq = by_stream[s]
        assert r["first_ts_init"] == min(b.ts_init for b in seq)
        assert r["last_ts_init"] == max(b.ts_init for b in seq)
        assert r["first_ts_event"] == min(b.ts_event for b in seq)
        assert r["last_ts_event"] == max(b.ts_event for b in seq)
