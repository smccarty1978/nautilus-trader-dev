"""autonomous_explore: tier: explore runs compile -> close without packets or approvals, under machine-enforced science.

Covers: D1 plan-bound audit freshness (the reproduced stale-audit defect), study-local observers with read-only
tracker + session inputs, declared study-local tests, the research ledger (immutable attempts, cross-study exposure,
computed claim level), RESULT_CARD + CLOSED_ISOLATED, and the refusals (leaky observer, reserved data, OOS, model).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000

OBSERVER = '''from features.trackers.base import BaseBinding


class CloseLocationStreak(BaseBinding):
    """Consecutive completed bars closing in the top (+) / bottom (-) quarter of their range; resets each session."""
    CAPABILITY = "study_local.close_location_streak"
    AVAILABILITY = "bar_close"
    MAX_STATE_ITEMS = 16
    INPUTS = {"bars": "stream", "regime": "tracker"}
    SESSION = True
    PARAMS = {"band": 0.25}
    FIELDS = ("streak", "range_atr", "session_bar", "last_close_ts")

    def __init__(self, params, inputs):
        super().__init__(params, inputs)
        self._regime = inputs["regime"]
        self._session = inputs["session"]
        self._open = None
        self.streak = 0
        self.range_atr = 0.0
        self.session_bar = 0
        self.last_close_ts = None

    def on_bar(self, input_key, bar):
        win = self._session.session_window(bar.ts_init)
        key = win[0] if win else None
        if key != self._open:
            self._open, self.streak, self.session_bar = key, 0, 0
        self.session_bar += 1
        rng = bar.high - bar.low
        loc = (bar.close - bar.low) / rng if rng > 0 else 0.5
        band = float(self.params["band"])
        s = 1 if loc >= 1.0 - band else (-1 if loc <= band else 0)
        self.streak = 0 if s == 0 else (self.streak + s if self.streak * s > 0 else s)
        atr = self._regime.atr
        self.range_atr = round(rng / atr, 6) if atr else 0.0
        self.last_close_ts = int(bar.ts_init)
'''

# deliberately invalid: remembers the bar it saw on the PREVIOUS run through a class-level cache keyed by ts, so a
# replay of the same timestamps with different future prices changes earlier outputs (future perturbation fails)
LEAKY = OBSERVER.replace("    def on_bar(self, input_key, bar):\n", '''    _SEEN = {}

    def on_bar(self, input_key, bar):
        prev = CloseLocationStreak._SEEN.get(bar.ts_init - 60_000_000_000)
        CloseLocationStreak._SEEN[bar.ts_init] = bar.close
        if prev is not None and prev > bar.close + 100:
            self.streak += 0
''').replace("        self.last_close_ts = int(bar.ts_init)\n", "        self.last_close_ts = int(bar.ts_init) + len(CloseLocationStreak._SEEN) % 2\n")

STUDY_TEST = '''from pathlib import Path

from research_workflow.study_observers import load_observer, synthetic_tape, synthetic_sessions, observer_inputs


class _Atr:
    FIELDS = ("atr",)
    atr = 2.0


def test_hand_calculated_streak():
    here = Path(__file__).resolve().parents[1]
    cls = load_observer(here / "observers" / "close_location_streak.py", here.name, "close_location_streak")
    tape = synthetic_tape(n_sessions=2, seconds=40)
    obs = cls({"band": 0.25}, observer_inputs(cls, {"bars": "obs", "regime": _Atr()}, synthetic_sessions(tape)))
    streak, opened = 0, None
    for b in tape:
        rng = b.high - b.low
        loc = (b.close - b.low) / rng if rng > 0 else 0.5
        s = 1 if loc >= 0.75 else (-1 if loc <= 0.25 else 0)
        day = b.ts_init // 86_400_000_000_000
        if day != opened:
            opened, streak = day, 0
        streak = 0 if s == 0 else (streak + s if streak * s > 0 else s)
        obs.on_bar("bars", b)
        assert obs.streak == streak and obs.range_atr == round(rng / 2.0, 6)
'''

ANALYSIS = {
    "source": "train",
    "steps": [
        {"id": "rows", "op": "analysis.derive.columns",
         "params": {"columns": [{"name": "streak_hi", "expr": "abs(cls_streak) >= 2"}]}},
        {"id": "uncertainty", "op": "analysis.uncertainty.clustered_mean", "rows": "rows",
         "params": {"value_columns": ["target_flip_within_horizon"], "cluster_ts_column": "observation_ts", "censored_column": "censored",
                    "differences": [{"name": "streak_vs_rest", "a": {"streak_hi": True}, "b": {"streak_hi": False}}]}},
    ],
    "artifacts": [{"name": "explore_uncertainty.json", "source": "uncertainty", "kind": "json"}],
}

RESULT = {"hypothesis": "a >=2-bar close-location streak raises the 60 s regime-flip rate", "expected_sign": "positive",
          "primary": {"artifact": "explore_uncertainty.json", "difference": "streak_vs_rest", "column": "target_flip_within_horizon"},
          "min_effect": 0.02, "min_clusters": 2, "control": "same population, |streak| < 2"}


@pytest.fixture(scope="module")
def synthetic_bars():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    return bars, json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    monkeypatch.setenv("NT_RESEARCH_LEDGER", str(d))
    return d


@pytest.fixture
def explore_study(tmp_path):
    """A study under this checkout's studies/ (observer + tests are hashed into the closure / plan like a real study)."""
    import os
    sid = f"zz_explore_probe_{os.getpid()}"
    d = ROOT / "studies" / sid
    d.mkdir(parents=True)
    try:
        yield sid, d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _spec(sid: str, **over):
    body = yaml.safe_load((GOLDEN / "study_flip.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = sid
    body["tier"] = "explore"
    body["family"] = "close_location_probe"
    body["context"]["cls"] = {"tracker": "study_local:close_location_streak", "bars": "1m", "regime": "regime", "band": 0.25}
    body["features"]["columns"]["cls_streak"] = "cls.streak"
    body["chronology"] = {"train": [2030], "dev": [], "prohibited": [], "authorized_dates": ["2030-01-01"]}
    body["analysis"] = ANALYSIS
    body["result"] = RESULT
    body["study_tests"] = ["tests/test_close_location_streak.py"]
    body.update(over)
    return body


def _write(study: Path, body, observer: str = OBSERVER) -> None:
    (study / "observers").mkdir(exist_ok=True)
    (study / "observers" / "close_location_streak.py").write_text(observer, encoding="utf-8")
    (study / "tests").mkdir(exist_ok=True)
    (study / "tests" / "test_close_location_streak.py").write_text(STUDY_TEST, encoding="utf-8")
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")


def _controller(study, bars, expected, monkeypatch, tmp_path):
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow.lifecycle_v2 import V2Options
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    opts = V2Options(execute=False, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True, model_root=tmp_path / "model_store")
    monkeypatch.setattr(V2StudyController, "_worktree",
                        lambda self: {"path": str(ROOT), "branch": "test", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []})
    return lambda: V2StudyController(study, options=opts, repo_root=ROOT)


# --------------------------------------------------------------------------- the primary success path
def test_explore_study_runs_compile_to_closed_isolated_with_a_delivered_result(tmp_path, synthetic_bars, monkeypatch, ledger, explore_study):
    bars, expected = synthetic_bars
    sid, study = explore_study
    _write(study, _spec(sid))
    ctl = _controller(study, bars, expected, monkeypatch, tmp_path)

    card = ctl().run(through="close")                          # ONE call: no packet, no --execute-authorized, no approval
    assert card["STATUS"] != "BLOCKED", (card.get("stage"), card.get("reason"), card.get("actions_executed"))
    assert card["state"] == "STUDY_CLOSED" and card["terminal"] == "CLOSED_ISOLATED", card
    assert card["result"]["verdict"] in ("SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE")
    assert card["result"]["claim_level"] == "EXPLORATORY"

    plan = json.loads((study / "compiled_plan.json").read_text(encoding="utf-8"))
    assert f"studies/{sid}/observers/close_location_streak.py" in plan["closure"]["files"]
    assert plan["explore"]["result"]["expected_sign"] == "positive"            # the rule was frozen in the plan
    proof = next(p for p in plan["binding_proof"] if p.get("id") == "cls")
    assert proof["observer_check"]["passed"] and proof["observer_check"]["upstream"] == ["regime"]

    # deterministic audits replaced packets, and are bound to THIS plan
    for name in ("status.json", "contract_status.json"):
        st = json.loads((study / "audit" / name).read_text(encoding="utf-8"))
        assert st["verdict"] == "CLEAR" and st["audited_plan_sha256"] == plan["plan_sha256"]
        assert st["auditor"].startswith("research_workflow.explore_deterministic_")
    tests = json.loads((study / "_work/controller/test_summary.json").read_text(encoding="utf-8"))
    assert any(f.endswith("test_close_location_streak.py") for f in tests["files"]) and tests["status"] == "PASS"

    closure = json.loads((study / "artifacts/study_closure.json").read_text(encoding="utf-8"))
    assert closure["isolation"] == "CLOSED_ISOLATED" and closure["outcome"] == card["result"]["verdict"]
    card_md = (study / "RESULT_CARD.md").read_text(encoding="utf-8")
    for needle in ("Hypothesis", "Population", "Dataset / interval", "Primary outcome", "Control", "session-clustered CI",
                   "Scientific validity", "Limitations", "Recommendation"):
        assert needle in card_md, needle
    res = json.loads((study / "artifacts/result.json").read_text(encoding="utf-8"))
    assert (study / "artifacts/attempts" / res["attempt_id"] / "result.json").is_file()

    from research_workflow import research_ledger as RL
    kinds = [e["kind"] for e in RL.events()]
    assert kinds.count("exposure") == 1 and kinds.count("result") == 1
    exposure = RL.events("exposure")[0]
    assert exposure["intervals"] == [{"dataset": "SYN_A", "start": "2030-01-01", "end": "2030-01-01"}]
    assert (study / "artifacts/ledger" / f"{exposure['event_id']}.json").is_file()            # git-committable mirror

    # closed is terminal: running again changes nothing and never re-collects
    again = ctl().run(through="close")
    assert again["state"] == "STUDY_CLOSED"
    assert [e["kind"] for e in RL.events()] == kinds


# --------------------------------------------------------------------------- refusals before any outcome analysis
def test_a_leaky_observer_is_refused_at_compile_and_the_controller_does_not_advance(tmp_path, synthetic_bars, monkeypatch, ledger, explore_study):
    bars, expected = synthetic_bars
    sid, study = explore_study
    _write(study, _spec(sid), observer=LEAKY)
    card = _controller(study, bars, expected, monkeypatch, tmp_path)().run(through="close")
    assert card["state"] == "NEEDS_COMPILE" and card.get("capability_gaps"), card
    assert any("causality harness" in str(g) or "OBSERVER_" in str(g) for g in card["capability_gaps"])
    assert not (study / "artifacts" / "result.json").exists()
    from research_workflow import research_ledger as RL
    assert RL.events() == []                                   # no data was touched: nothing to record


@pytest.mark.parametrize("over, code", [
    ({"chronology": {"train": [2030], "dev": [2031], "prohibited": []}}, "EXPLORE_NO_OOS"),
    ({"result": None}, "EXPLORE_SPEC_INCOMPLETE"),
])
def test_explore_grammar_refuses_oos_and_unregistered_decisions(explore_study, over, code):
    from research_workflow.grammar.spec import StudySpecV2
    sid, _ = explore_study
    with pytest.raises(Exception, match=code):
        StudySpecV2.model_validate(_spec(sid, **over))


def test_reserved_confirmation_data_is_refused_before_any_bar(tmp_path, synthetic_bars, monkeypatch, ledger, explore_study):
    bars, expected = synthetic_bars
    sid, study = explore_study
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"catalog_roots": [str(tmp_path)],
                                   "reserved_windows": [{"dataset": "SYN_A", "start": "2030-01-01", "end": "2030-12-31"}]}), encoding="utf-8")
    monkeypatch.setenv("NT_RESEARCH_CONFIG", str(cfg))
    _write(study, _spec(sid))
    card = _controller(study, bars, expected, monkeypatch, tmp_path)().run(through="close")
    assert card["STATUS"] == "BLOCKED" and card["stage"] == "contract_audit", card
    assert not (study / "artifacts" / "smoke_acceptance.json").exists()


# --------------------------------------------------------------------------- D1: plan-bound audit freshness
def _reseal_fixture(tmp_path, plan_a, plan_b):
    from research_workflow.lifecycle_v2 import V2Lifecycle
    s = tmp_path / "s"
    lc = V2Lifecycle.__new__(V2Lifecycle)
    lc.study, lc.audit, lc.artifacts, lc.work = s, s / "audit", s / "artifacts", s / "_work/controller"
    comp = plan_a["closure"]["composite_sha256"]
    for p, d in ((lc.audit / "frozen_execution_manifest.json", {"plan_sha256": plan_b["plan_sha256"], "frozen_execution_composite_sha256": comp}),
                 (s / "compiled_plan.json", plan_b)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(plan_b if p.name == "compiled_plan.json" else d, default=str), encoding="utf-8")
    for n in ("status.json", "contract_status.json"):
        (lc.audit / n).write_text(json.dumps({"verdict": "CLEAR", "audited_execution_composite_sha256": comp,
                                              "audited_plan_sha256": plan_a["plan_sha256"], "auditor": n}), encoding="utf-8")
    return lc


@pytest.mark.parametrize("mutate", [
    lambda s: s["outcome"].__setitem__("session_end", "ignore" if s["outcome"].get("session_end") != "ignore" else "censor"),
    lambda s: s["population"].__setitem__("qualify", "regime.age_s >= 20s and regime.frozen_atr > 0"),
    lambda s: s["chronology"].__setitem__("authorized_dates", ["2030-01-02"]),
], ids=["outcome_session_end", "population", "chronology"])
def test_a_semantic_change_cannot_reseal_on_an_earlier_clear_audit(tmp_path, mutate):
    """The reproduced defect: composite unchanged, plan changed, prior CLEAR used to seal. Now refused."""
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.lifecycle_v2 import LifecycleV2Error
    spec = load_spec(GOLDEN / "study_flip.yaml")
    spec["chronology"] = {"train": [2030], "dev": [], "prohibited": [], "authorized_dates": ["2030-01-01"]}
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    kw = dict(repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=dict(SYNTHETIC_BINDINGS))
    a = compile_study(spec, **kw)
    mutate(spec)
    b = compile_study(spec, **kw)
    assert a.ok and b.ok, (a.card(), b.card())
    pa, pb = a.plan.to_dict(), b.plan.to_dict()
    assert pa["closure"]["composite_sha256"] == pb["closure"]["composite_sha256"] and pa["plan_sha256"] != pb["plan_sha256"]
    with pytest.raises(LifecycleV2Error, match="AUDIT_NOT_CLEAR_OR_STALE"):
        _reseal_fixture(tmp_path, pa, pb).seal()
    # the unchanged plan reuses its valid approval
    lc = _reseal_fixture(tmp_path / "same", pa, pa)
    assert lc.seal()["status"] == "PASS"


def test_a_code_change_stales_the_audit_and_a_reseal_keeps_exposure_history(tmp_path, ledger):
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow import research_ledger as RL
    c = V2StudyController.__new__(V2StudyController)
    c.study = tmp_path / "s"
    (c.study / "audit").mkdir(parents=True)
    st = c.study / "audit" / "status.json"
    st.write_text(json.dumps({"verdict": "CLEAR", "audited_execution_composite_sha256": "a" * 64, "audited_plan_sha256": "p"}), encoding="utf-8")
    fp = {"execution_composite": "a" * 64, "current_execution_composite": "a" * 64, "plan_sha256": "p"}
    assert c._audit_current(st, fp)
    assert not c._audit_current(st, {**fp, "current_execution_composite": "b" * 64})       # code / dependency change
    assert not c._audit_current(st, {**fp, "plan_sha256": "q"})                             # scientific change
    # exposure is outside the study's sealable artifacts and write-once: a reseal / rerun cannot erase it
    plan = {"plan_sha256": "p", "study": {"id": "s"}, "instruments": {"X": {"dataset_id": "SYN_A", "dataset_digest": "d"}},
            "chronology": {"train": [2030]}, "outcome": {"label_column": "y"}, "explore": {"tier": "explore", "family": "f"}}
    first = RL.record_exposure(c.study, plan, {"SYN_A": "d"})
    again = RL.record_exposure(c.study, plan, {"SYN_A": "d"})
    assert first["new"] and not again["new"] and len(RL.events("exposure")) == 1
    with pytest.raises(RL.LedgerError, match="LEDGER_EVENT_IMMUTABLE"):
        RL._write_once(RL.ledger_dir() / "events" / f"{first['event_id']}.json", {"tampered": True})


def test_a_new_study_id_does_not_make_seen_data_unseen_and_claims_are_computed(ledger):
    from research_workflow import research_ledger as RL
    base = {"instruments": {"X": {"dataset_id": "NQ", "dataset_digest": "d"}}, "outcome": {"label_column": "y"},
            "population": {"qualify": "q"}, "closure": {"files": {}}}
    a = {**base, "plan_sha256": "pa", "study": {"id": "a"}, "chronology": {"train": [2024]}, "explore": {"tier": "explore", "family": "f"}}
    RL.record_exposure(Path("."), a, {"NQ": "d"}) if False else RL.append({"kind": "exposure", "attempt_id": "A", "study_id": "a", "family": "f",
                                                                          "intervals": RL.plan_intervals(a), "definition_sha256": RL.definition_sha256(a)})
    b = {**a, "plan_sha256": "pb", "study": {"id": "b_new_id"}, "population": {"qualify": "q2"}}
    assert RL.prior_exposure(RL.plan_intervals(b))            # another study id: 2024 is still recorded as seen
    assert RL.claim_level(b, attempt="B")[0] == "EXPLORATORY"
    RL.append({"kind": "result", "attempt_id": "A", "definition_sha256": RL.definition_sha256(a), "intervals": RL.plan_intervals(a), "verdict": "INCONCLUSIVE"})
    same_def_new_year = {**a, "plan_sha256": "pc", "study": {"id": "c"}, "chronology": {"train": [2025]}}
    assert RL.claim_level(same_def_new_year, attempt="C")[0] == "CHRONOLOGICAL_ROBUSTNESS"
    assert RL.claim_level({**a, "plan_sha256": "pd", "study": {"id": "d"}}, attempt="D")[0] == "HISTORICAL_REPLICATION"
    governed = {**a, "explore": None, "chronology": {"train": [2026]}}
    assert RL.claim_level(governed, attempt="G")[0] != "CONFIRMATORY"          # nothing reserved -> never confirmatory
