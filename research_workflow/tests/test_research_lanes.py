"""Research lanes (WORKFLOW.md §Q): routing, study-local observer isolation and causality, merge-tier classification.

Primary success test: a new exploratory study with a novel causal feature, written as a study-local observer, compiles,
runs through the NT observation host (HostCore), produces observations that equal an independent reference, routes
to FAST_OBSERVATION with no broad regression or capability promotion gate, and writes a compact lane manifest.
The converse tests show that a shared platform change or a trading backtest cannot reach the cheap lane.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from research_workflow import research_lanes as L
from research_workflow import study_observers as SO
from research_workflow.host.interfaces import BarView

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000
CT = ZoneInfo("America/Chicago")

OBSERVER = '''from collections import deque

from features.trackers.base import BaseBinding


class SignedVolumeStreak(BaseBinding):
    """Novel causal feature: consecutive same-direction 1 s closes and the signed volume of the last window_s seconds."""
    CAPABILITY = "study_local.signed_volume_streak"
    AVAILABILITY = "bar_close"
    MAX_STATE_ITEMS = 128
    INPUTS = {"bars": "stream"}
    PARAMS = {"window_s": 30}
    FIELDS = ("streak", "signed_vol_window", "last_close_ts")

    def __init__(self, params, inputs):
        super().__init__(params, inputs)
        self._win = deque()
        self._sum = 0.0
        self.streak = 0
        self.signed_vol_window = 0.0
        self.last_close_ts = None

    def on_bar(self, input_key, bar):
        sign = 1 if bar.close > bar.open else (-1 if bar.close < bar.open else 0)
        if sign == 0:
            self.streak = 0
        elif self.streak * sign > 0:
            self.streak += sign
        else:
            self.streak = sign
        sv = sign * float(bar.volume)
        self._win.append((bar.ts_init, sv))
        self._sum += sv
        horizon = bar.ts_init - int(self.params["window_s"]) * 1_000_000_000
        while self._win and self._win[0][0] <= horizon:
            self._sum -= self._win.popleft()[1]
        self.signed_vol_window = round(self._sum, 6)
        self.last_close_ts = int(bar.ts_init)
'''


def _write_observer(study_dir: Path, source: str = OBSERVER, name: str = "signed_volume_streak") -> Path:
    p = study_dir / "observers" / f"{name}.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source, encoding="utf-8")
    return p


def _load(tmp_path: Path, source: str, name: str = "signed_volume_streak", study: str = "lane_probe"):
    d = tmp_path / "studies" / study
    return SO.load_observer(_write_observer(d, source, name), study, name)


# =========================================================================== observer isolation
@pytest.mark.parametrize("snippet, needle", [
    ("import pandas as pd\n", "pandas"),
    ("from studies.other.observers import x\n", "studies.other.observers"),
    ("from . import helper\n", "relative imports"),
    ("import sys\n", "import sys"),
    ("import importlib\n", "import importlib"),
    ("X = open('data.parquet')\n", "open()"),
    ("def f(df):\n    return df.shift(-1)\n", ".shift"),
])
def test_observer_isolation_rules_refuse_retrospective_or_cross_study_code(tmp_path, snippet, needle):
    with pytest.raises(SO.ObserverError) as e:
        _load(tmp_path, snippet + OBSERVER)
    assert e.value.code == "OBSERVER_ISOLATION_VIOLATION" and needle in str(e.value)


def test_observer_must_live_in_its_own_study_and_declare_availability_and_bound(tmp_path):
    p = _write_observer(tmp_path / "studies" / "a")
    with pytest.raises(SO.ObserverError, match="OBSERVER_OUTSIDE_STUDY"):
        SO.load_observer(p, "b", "signed_volume_streak")                  # another study's observer
    with pytest.raises(SO.ObserverError, match="OBSERVER_NAME_INVALID"):
        SO.observer_file(tmp_path, "../a/observers/x")
    with pytest.raises(SO.ObserverError, match="OBSERVER_AVAILABILITY_UNDECLARED"):
        _load(tmp_path, OBSERVER.replace('    AVAILABILITY = "bar_close"\n', ""), study="c")
    with pytest.raises(SO.ObserverError, match="OBSERVER_STATE_UNBOUNDED"):
        _load(tmp_path, OBSERVER.replace("    MAX_STATE_ITEMS = 128\n", ""), study="d")
    with pytest.raises(SO.ObserverError, match="OBSERVER_INPUTS_INVALID"):
        _load(tmp_path, OBSERVER.replace('INPUTS = {"bars": "stream"}', 'INPUTS = {"bars": "stream", "regime": "tracker"}'), study="e")


def test_host_refuses_a_study_local_implementation_for_another_study(tmp_path):
    p = _write_observer(tmp_path / "studies" / "owner")
    cls = SO.load_observer(p, "owner", "signed_volume_streak")
    ref = SO.implementation_ref("owner", p, ROOT, cls)
    assert SO.resolve_implementation(ref, plan_study_id="owner", repo_root=ROOT).__name__ == "SignedVolumeStreak"
    with pytest.raises(SO.ObserverError, match="OBSERVER_CROSS_STUDY_IMPORT"):
        SO.resolve_implementation(ref, plan_study_id="thief", repo_root=ROOT)
    from research_workflow.host import strategy
    with pytest.raises(SO.ObserverError, match="OBSERVER_CROSS_STUDY_IMPORT"):
        strategy._load(ref, {"study": {"id": "thief"}})


# =========================================================================== generated causality harness
def test_harness_passes_a_causal_bounded_observer(tmp_path):
    rep = SO.causality_check(_load(tmp_path, OBSERVER), {"window_s": 30})
    assert rep["passed"], rep
    assert all(rep["checks"][k] for k in ("deterministic", "prefix_invariance", "future_perturbation", "scalar_fields"))


LEAKY = OBSERVER.replace("    def on_bar(self, input_key, bar):\n", '''    SEEN = {}

    def on_bar(self, input_key, bar):
        prior = SignedVolumeStreak.SEEN.get(bar.ts_init)        # a value remembered from ANOTHER (later) pass
        SignedVolumeStreak.SEEN[bar.ts_init] = bar.close
        if prior is not None:
            self.streak = 0 if prior > bar.close else 1
            return
''')
UNBOUNDED = OBSERVER.replace("        while self._win and self._win[0][0] <= horizon:\n            self._sum -= self._win.popleft()[1]\n", "")


@pytest.mark.parametrize("source, failure", [
    (LEAKY, "OBSERVER_DETERMINISTIC_FAILED"),
    (UNBOUNDED, "OBSERVER_STATE_BOUND_EXCEEDED"),
    (OBSERVER.replace("self.last_close_ts = int(bar.ts_init)", "self.last_close_ts = 0"), None),
    (OBSERVER.replace("        self.last_close_ts = int(bar.ts_init)\n", "        self.last_close_ts = [bar.ts_init]\n"), "OBSERVER_SCALAR_FIELDS_FAILED"),
])
def test_harness_refuses_leaky_unbounded_or_non_scalar_observers(tmp_path, source, failure):
    rep = SO.causality_check(_load(tmp_path, source), {"window_s": 30})
    if failure is None:
        assert rep["passed"]                                    # a constant field alone is fine while other fields vary
    else:
        assert not rep["passed"] and rep["failure"].startswith(failure), rep


# =========================================================================== primary success test (end to end)
def _ct(d, h, m):
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=CT).timestamp()) * NS


def _tape():
    rng = random.Random(7)
    bars = []
    for i in range(3):
        d = datetime(2030, 1, 7) + timedelta(days=i)
        t, px = _ct(d, 8, 30), 100.0
        while t < _ct(d, 8, 30) + 1200 * NS:
            o = px
            px += rng.choice([-0.25, 0.0, 0.25])
            bars.append(BarView("1s", t, t + NS, o, max(o, px), min(o, px), px, float(rng.choice([0, 1, 3, 8]))))
            t += rng.choice([1, 1, 2, 5]) * NS
    return bars


def _session_table(bars):
    from research_workflow.sessions import TRADING_DAY, build_session_table
    days = sorted({datetime.fromtimestamp(b.ts_init / NS, tz=CT).date() for b in bars})
    rth = [(_ct(d, 8, 30), _ct(d, 15, 15)) for d in days]
    td = [(_ct(d - timedelta(days=1), 17, 0), _ct(d, 16, 0)) for d in days]
    return build_session_table({"kind": "calendar", "session": "RTH", "rows": rth, "rows_by_session": {"RTH": rth, TRADING_DAY: td}})


@pytest.fixture
def in_repo_study():
    """A throw-away study under this checkout's studies/ so the observer is hashed into the closure like a real one."""
    sid = f"zz_lane_probe_{os.getpid()}"
    d = ROOT / "studies" / sid
    d.mkdir(parents=True)
    try:
        yield sid, d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_primary_new_exploratory_study_with_a_novel_local_feature_runs_fast_and_causally(tmp_path, in_repo_study):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.host.strategy import HostCore
    from research_workflow.host_runner import sort_bars_causal
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS

    sid, study = in_repo_study
    bars = _tape()
    _write_observer(study)
    spec = {
        "study": {"id": sid, "tier": 2, "question": "does a signed-volume streak precede direction? (lane probe)"},
        "streams": [{"dataset": "SYN_A", "timeframes": ["1s"]}],
        "context": {"obs": {"tracker": "study_local:signed_volume_streak", "bars": "1s", "window_s": 30}},
        "population": {"session": "RTH"},
        "triggers": "every_candidate",
        "features": {"host": "synthetic", "metadata": {"streak": "obs.streak", "svw": "obs.signed_vol_window", "seen": "obs.last_close_ts"}},
        "outcome": "none",
        "chronology": {"train": [2030], "dev": [], "prohibited": []},
        "model": "none",
    }
    (study / "study.yaml").write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    ds = tmp_path / "datasets"
    ds.mkdir()
    for p in (GOLDEN / "datasets").glob("*.yaml"):
        shutil.copy2(p, ds / p.name)
    a = yaml.safe_load((ds / "SYN_A.yaml").read_text(encoding="utf-8"))
    iso = lambda ns: datetime.fromtimestamp(ns / NS, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    a["coverage"] = {"start": iso(bars[0].ts_event), "end": iso(bars[-1].ts_init)}
    (ds / "SYN_A.yaml").write_text(yaml.safe_dump(a, sort_keys=False), encoding="utf-8")

    out = compile_study(load_spec(study), repo_root=ROOT, datasets_dir=ds, extra_bindings=dict(SYNTHETIC_BINDINGS))
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    tracker = plan["trackers"][0]
    rel = f"studies/{sid}/observers/signed_volume_streak.py"
    assert tracker["implementation"].startswith(f"study_local:{sid}:{rel}:")
    assert rel in plan["closure"]["files"]                       # hashed: editing the observer stales the plan/seal
    proof = next(p for p in plan["binding_proof"] if p["id"] == "obs") if isinstance(plan.get("binding_proof"), list) else None
    assert proof is None or proof["observer_check"]["passed"]

    # NT observation host: candidates at every epoch, fields read after the row closing at T
    key = plan["streams"][0]["key"]
    core = HostCore(plan, session_table=_session_table(bars))
    rk = [BarView(key, b.ts_event, b.ts_init, b.open, b.high, b.low, b.close, b.volume) for b in bars]
    for b in sort_bars_causal(rk, {s["key"]: int(s["duration_ns"]) for s in plan["streams"]}):
        core.ingest(b)
    candidates, _ = core.finalize()
    rows = candidates.to_dict("records")
    assert len(rows) > 1000

    # independent reference (brute force, no shared code): state after the row closing at T
    after, streak = {}, 0
    for i, b in enumerate(bars):
        s = (b.close > b.open) - (b.close < b.open)
        streak = 0 if s == 0 else (streak + s if streak * s > 0 else s)
        w = sum(((x.close > x.open) - (x.close < x.open)) * x.volume for x in bars[: i + 1] if x.ts_init > b.ts_init - 30 * NS)
        after[b.ts_init] = (streak, round(float(w), 6), b.ts_init)
    for r in rows:
        T = int(r["observation_ts"])
        assert int(r["seen"]) <= T                               # availability: never a bar closing after the epoch
        assert (int(r["streak"]), round(float(r["svw"]), 6), int(r["seen"])) == after[int(r["seen"])]
    assert {int(r["seen"]) for r in rows} <= set(after)        # population consistency: every row maps to a source close

    # lane: FAST_OBSERVATION, no broad regression / promotion / contract audit
    facts = L.facts_from_study(study)
    assert facts["study_local_observers"] == ["obs"]
    lane = L.route(facts)["lane"]
    gates = L.required_gates(lane, facts)
    assert lane == L.FAST_OBSERVATION and "observer_causality_harness" in gates
    assert not set(gates) & {"broad_test_delta", "capability_promotion", "contract_audit", "full_history_parity"}

    # a research result + an evidence-based decision, recorded in one compact manifest
    up = [r for r in rows if int(r["streak"]) >= 3]
    obs = tmp_path / "observations.json"
    obs.write_text(json.dumps({"n": len(rows), "n_streak_ge3": len(up)}), encoding="utf-8")
    m = L.lane_manifest(study_id=sid, lane=lane, dataset_id="SYN_A", dataset_digest="synthetic", capability_versions={},
                        study_contract_sha256="n/a", plan_sha256=plan["plan_sha256"], schema_version="1", period=["2030-01-07", "2030-01-09"],
                        outputs=[obs], validation={"observer_causality_harness": "PASS", "independent_reference": "PASS",
                                                   "broad_test_delta": "NOT_REQUIRED"}, verdict="STOP")
    L.write_lane_manifest(tmp_path / "lane_manifest.json", m)
    assert json.loads((tmp_path / "lane_manifest.json").read_text(encoding="utf-8"))["verdict"] == "STOP"


def test_a_failing_observer_is_a_study_side_gap_not_a_platform_gap(tmp_path, in_repo_study):
    from research_workflow.grammar.compiler import compile_study
    sid, study = in_repo_study
    _write_observer(study, UNBOUNDED)
    spec = {"study": {"id": sid, "tier": 2, "question": "q"}, "streams": [{"dataset": "SYN_A", "timeframes": ["1s"]}],
            "context": {"obs": {"tracker": "study_local:signed_volume_streak", "bars": "1s"}},
            "population": {"session": "RTH"}, "triggers": "every_candidate", "features": {"host": "synthetic", "metadata": {"s": "obs.streak"}},
            "outcome": "none", "chronology": {"train": [2030], "dev": [], "prohibited": []}, "model": "none"}
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    out = compile_study(spec, repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=dict(SYNTHETIC_BINDINGS))
    kinds = {g.kind.value for g in out.gaps.gaps}
    assert not out.ok and "INVALID_PARAMETERIZATION" in kinds and "MISSING_CAPABILITY" not in kinds
    assert any("OBSERVER_STATE_BOUND_EXCEEDED" in g.message for g in out.gaps.gaps)


# =========================================================================== routing (design §7, 1-12)
def test_routing_matrix():
    fast = L.route({})
    assert fast["lane"] == L.FAST_OBSERVATION                                                      # 1 descriptive
    assert L.route({"study_local_observers": []})["lane"] == L.FAST_OBSERVATION                     # 2 existing capabilities
    assert L.route({"missing_capability": False})["lane"] == L.FAST_OBSERVATION                     # 3 first-passage: registered kernel
    assert L.route({"missing_capability": True})["lane"] == L.FAST_OBSERVATION                      # novel feature -> local observer
    assert L.route({"prior_verdict": "VALIDATE"})["lane"] == L.RESEARCH_VALIDATION                  # 4
    assert L.route({"oos_confirmation": True})["lane"] == L.RESEARCH_VALIDATION
    assert L.route({"trading_backtest": True})["lane"] == L.EXECUTION_VALIDATION                    # 5
    assert L.route({"missing_capability": True, "local_route_possible": False})["lane"] == L.PLATFORM_CHANGE   # 6
    assert L.route({"missing_capability": True, "reuse_consumers": 2})["lane"] == L.PLATFORM_CHANGE
    assert L.route({"shared_code_changed": True})["lane"] == L.PLATFORM_CHANGE
    assert L.route({"sealed": True, "trading_backtest": True})["lane"] == L.HISTORICAL               # 11
    assert L.required_gates(L.HISTORICAL) == []


def test_declared_lane_can_raise_never_lower():
    assert L.route({"declared_lane": L.RESEARCH_VALIDATION})["lane"] == L.RESEARCH_VALIDATION
    r = L.route({"trading_backtest": True, "declared_lane": L.FAST_OBSERVATION})
    assert r["lane"] == L.EXECUTION_VALIDATION and any("ignored" in w for w in r["why"])
    with pytest.raises(ValueError, match="RESEARCH_LANE_UNKNOWN"):
        L.route({"declared_lane": "YOLO"})


def test_expensive_gates_only_where_the_lane_justifies_them():                                     # 10
    seen = {lane: set(L.required_gates(lane, {"study_local_observers": ["x"]})) for lane in L.LANES}
    assert not seen[L.FAST_OBSERVATION] & L.EXPENSIVE_GATES
    assert "contract_audit" in seen[L.RESEARCH_VALIDATION] and "capability_promotion" not in seen[L.RESEARCH_VALIDATION]
    assert {"nt_runtime_candidate_generation", "order_fill_exit_realism"} <= seen[L.EXECUTION_VALIDATION]
    assert "broad_test_delta" in seen[L.PLATFORM_CHANGE]                                           # CORE diff by default
    assert "broad_test_delta" not in L.required_gates(L.PLATFORM_CHANGE, {"merge_tier": "ADDITIVE_CAPABILITY"})
    assert "broad_test_delta" in L.required_gates(L.FAST_OBSERVATION, {"shared_code_changed": True})


def test_validated_capability_is_reused_without_repeat_promotion():                                # 7
    caps = [{"id": "tracker.volume_clock.developing", "promotion_evidence_sha256": "ffc1e6d0"}]
    gates = L.required_gates(L.FAST_OBSERVATION, {"consumed_capabilities": caps})
    assert not set(gates) & {"capability_promotion", "full_history_parity", "parity_evidence"}
    with pytest.raises(ValueError, match="CAPABILITY_UNVERIFIED"):
        L.required_gates(L.FAST_OBSERVATION, {"consumed_capabilities": [{"id": "tracker.x"}]})


def test_execution_validation_refuses_a_frozen_precomputed_schedule():                             # 9
    full = {k: 0 for k in L.RECONCILIATION_KEYS}
    bad = L.validate_execution_claim({"candidate_source": "precomputed_schedule", "features_computed_at_runtime": False,
                                      "fill_model": "close", "reconciliation": {}})
    assert not bad["accepted"] and len(bad["problems"]) == 4
    ok = L.validate_execution_claim({"candidate_source": "nt_runtime", "features_computed_at_runtime": True,
                                     "fill_model": "top_of_book", "reconciliation": full})
    assert ok["accepted"], ok


def test_frozen_population_resumes_without_recollection():                                         # 12 (Phase F shape)
    gates = L.required_gates(L.FAST_OBSERVATION, {"population_frozen": True})
    assert "single_full_collection" not in gates and "bounded_smoke_full_pipeline" not in gates
    assert "frozen_definitions_before_outcomes" in gates and "causal_audit" in gates


def test_lane_manifest_rejects_unknown_verdicts_and_statuses(tmp_path):
    kw = dict(study_id="s", lane=L.FAST_OBSERVATION, dataset_id="d", dataset_digest="x", capability_versions={}, study_contract_sha256="c",
              plan_sha256=None, schema_version="1", period=[], outputs=[])
    with pytest.raises(ValueError, match="VERDICT_UNKNOWN"):
        L.lane_manifest(validation={}, verdict="MAYBE", **kw)
    with pytest.raises(ValueError, match="VALIDATION_STATUS_UNKNOWN"):
        L.lane_manifest(validation={"x": "OK?"}, verdict="STOP", **kw)


# =========================================================================== merge-tier classification (P4)
def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def mini_repo(tmp_path, monkeypatch):
    import research_workflow.merge_tier as T
    r = tmp_path / "repo"
    files = {
        "features/trackers/host_bindings.py": "TRACKER_BINDINGS = {'a': 1}\n__all__ = ['TRACKER_BINDINGS']\n",
        "features/trackers/old.py": "X = 1\n",
        "research_workflow/grammar/compiler.py": "def f():\n    return 1\n",
        "research_workflow/capabilities_index.yaml": "trackers:\n- id: tracker.old\n  module: features.trackers.old\n",
        "features/tests/test_old.py": "def test_x():\n    pass\n",
        "conftest.py": "",
    }
    for rel, txt in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(txt, encoding="utf-8")
    _git(r.parent, "init", "-q", str(r))
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    monkeypatch.setattr(T, "ROOT", r)
    base = _git(r, "rev-parse", "HEAD")
    n = [0]

    def change(edits, deletes=()):
        n[0] += 1
        _git(r, "checkout", "-q", "-B", f"case{n[0]}", base)
        for rel, txt in edits.items():
            (r / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / rel).write_text(txt, encoding="utf-8")
        for rel in deletes:
            (r / rel).unlink()
        _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
        return T.classify_diff(base, "HEAD")[0]
    return change


def test_merge_tier_additive_only_for_strictly_additive_diffs(mini_repo):
    idx = "trackers:\n- id: tracker.old\n  module: features.trackers.old\n- id: tracker.new\n  module: features.trackers.new\n"
    assert mini_repo({"features/trackers/new.py": "Y = 2\n", "features/tests/test_new.py": "def test_y():\n    pass\n",
                      "research_workflow/capabilities_index.yaml": idx, "artifacts/x/README.md": "evidence\n"}) == "ADDITIVE_CAPABILITY"
    assert mini_repo({"features/trackers/host_bindings.py": "TRACKER_BINDINGS = {'a': 1, 'b': 2}\n__all__ = ['TRACKER_BINDINGS']\n"}) == "ADDITIVE_CAPABILITY"


@pytest.mark.parametrize("edits, deletes, expected", [
    ({"research_workflow/grammar/compiler.py": "def f():\n    return 2\n"}, (), "CORE_SURFACE"),          # shared interface
    ({"features/trackers/old.py": "X = 2\n"}, (), "MODIFIED_CAPABILITY"),                                 # semantic edit
    ({"research_workflow/capabilities_index.yaml": "trackers:\n- id: tracker.old\n  module: features.trackers.other\n"}, (), "MODIFIED_CAPABILITY"),
    ({"features/trackers/host_bindings.py": "TRACKER_BINDINGS = {'a': 9}\n__all__ = ['TRACKER_BINDINGS']\n"}, (), "CORE_SURFACE"),
    ({"conftest.py": "import os\n"}, (), "CORE_SURFACE"),                                                  # test config
    ({"studies/s/study.yaml": "x: 1\n"}, (), "CORE_SURFACE"),                                              # pinned evidence
    ({"somewhere/new_thing.py": "Z = 1\n"}, (), "CORE_SURFACE"),                                           # unmapped -> uncertain
    ({}, ("features/tests/test_old.py",), "CORE_SURFACE"),                                                 # any deletion
])
def test_merge_tier_escalates_shared_semantic_or_uncertain_changes(mini_repo, edits, deletes, expected):
    assert mini_repo(edits, deletes) == expected


def test_broad_classes_keep_the_requested_broad_scopes(mini_repo, monkeypatch):
    import research_workflow.merge_tier as T
    mini_repo({"research_workflow/grammar/compiler.py": "def f():\n    return 3\n"})
    base = _git(T.ROOT, "rev-list", "--max-parents=0", "HEAD")
    g = T.gate_plan(base, "HEAD", ["research_workflow/tests", "scripts/tests"])
    assert g["mode"] == "broad" and g["scopes"] == ["research_workflow/tests", "scripts/tests"]


# =========================================================================== zero-study-Python stays enforced (R10 / ZERO_STUDY_PYTHON)
def test_zero_study_python_exempts_only_plan_bound_observers(tmp_path):
    from types import SimpleNamespace
    from research_workflow.lifecycle_v2 import PLAN_NAME, V2Lifecycle
    sid = "lane_r10"
    d = tmp_path / sid
    p = _write_observer(d)
    cls = SO.load_observer(p, sid, "signed_volume_streak")
    ref = SO.implementation_ref(sid, p, ROOT, cls)
    check = lambda: V2Lifecycle._zero_study_python(SimpleNamespace(study=d))[0]
    assert check() == ["observers/signed_volume_streak.py"]                   # no plan binds it yet: refused
    (d / PLAN_NAME).write_text(json.dumps({"study": {"id": sid}, "trackers": [{"id": "obs", "implementation": ref}]}), encoding="utf-8")
    assert check() == []                                                      # bound by this study's plan: sanctioned
    (d / "helpers.py").write_text("x = 1\n", encoding="utf-8")
    _write_observer(d, name="unbound_extra")
    assert check() == ["helpers.py", "observers/unbound_extra.py"]           # everything else still fails
    (d / PLAN_NAME).write_text(json.dumps({"study": {"id": "someone_else"}, "trackers": [{"id": "obs", "implementation": ref}]}), encoding="utf-8")
    assert "observers/signed_volume_streak.py" in check()                     # another study's plan cannot sanction it


def test_test_delta_tier_base_runs_as_a_script_and_reports_the_tier():
    """Regression: `scripts/test_delta.py --tier-base` crashed (ModuleNotFoundError) when run as a script."""
    r = subprocess.run([os.sys.executable, "scripts/test_delta.py", "research_workflow/tests/test_research_lanes.py::test_routing_matrix",
                        "--tier-base", "HEAD", "--json"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    assert "ModuleNotFoundError" not in r.stderr, r.stderr[-800:]
    card = json.loads(r.stdout)
    assert card["merge_tier"]["class"] == "EMPTY_DIFF" and card["merge_tier"]["mode"] == "requested" and card["ran"] == 1
