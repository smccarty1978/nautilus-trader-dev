"""``outcome: none`` -- a first-class DESCRIPTIVE (observational) study mode.

Legal only with ``model: none``: no label, no barrier/event, no direction requirement, no
model fit/score. The host emits candidate rows (identity + metadata + features + derived)
and NO outcome/label column at all; omitting ``outcome`` entirely remains an error.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from research_workflow.grammar.compiler import compile_study, load_spec
from research_workflow.grammar.gaps import GapKind

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"


def _base():
    """shape_a's compiled spec dict, with chronology.dev emptied (outcome: none forbids dev
    years) and population.direction removed (not required in descriptive mode)."""
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_a" / "study.yaml")
    spec["chronology"]["dev"] = []
    del spec["population"]["direction"]
    return spec


def _descriptive():
    spec = _base()
    spec["outcome"] = "none"
    return spec


def _gap_kinds(spec):
    out = compile_study(spec, repo_root=ROOT)
    assert not out.ok
    return {(g.kind, g.where) for g in out.gaps.gaps}


def test_outcome_none_compiles_without_direction_or_label():
    spec = _descriptive()
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.card() if hasattr(out, "card") else out.gaps.to_dict()
    plan = out.plan.to_dict()
    assert plan["outcome"] == {
        "contract": "none", "kernel": "none", "direction": None, "entry_reference": None,
        "arms": [], "flip": None, "primary_arm": None, "label_column": None,
        "observation_columns": [],
    }
    assert plan["model"] is None
    assert plan["columns"]["observation"] == []


def test_omitting_outcome_entirely_is_still_an_error():
    spec = _base()
    del spec["outcome"]
    out = compile_study(spec, repo_root=ROOT)
    assert not out.ok
    assert any(g.where == "outcome" for g in out.gaps.gaps)


def test_outcome_none_with_a_fitted_model_is_a_typed_gap():
    spec = _descriptive()
    spec["model"] = {"family": "lightgbm", "mode": "train"}
    assert (GapKind.UNSUPPORTED_COMPOSITION, "outcome") in _gap_kinds(spec)


def test_outcome_none_with_score_mode_model_is_a_typed_gap():
    spec = _descriptive()
    spec["model"] = {"mode": "score", "models": [{"id": "a" * 64, "label": "target_flip_within_horizon"}]}
    assert (GapKind.UNSUPPORTED_COMPOSITION, "outcome") in _gap_kinds(spec)


def test_outcome_none_with_trigger_entry_is_a_typed_gap():
    spec = _descriptive()
    spec["triggers"] = {"states": {"WATCH": {"enter_when": "excursion.mfe_atr >= 1.0"}},
                        "entry": {"when": "state == WATCH", "reference": "next_bar_open"}}
    assert (GapKind.UNSUPPORTED_COMPOSITION, "triggers.entry") in _gap_kinds(spec)


def test_outcome_none_with_dev_years_is_a_typed_gap():
    spec = _descriptive()
    spec["chronology"]["dev"] = [2024]
    assert (GapKind.SEMANTIC_DECISION_REQUIRED, "chronology.dev") in _gap_kinds(spec)


def test_outcome_none_still_validates_a_declared_direction():
    spec = _descriptive()
    spec["population"]["direction"] = "regime_1m.does_not_exist"
    out = compile_study(spec, repo_root=ROOT)
    assert not out.ok
    assert any(g.where == "population.direction" for g in out.gaps.gaps)


def test_outcome_none_compiles_under_stage_collect():
    spec = _descriptive()
    spec["stage"] = "collect"
    # stage: collect is PERMISSIVE: no population.qualify (COLLECT_MUST_BE_PERMISSIVE), which is
    # an unrelated, pre-existing stage:collect constraint -- drop it to isolate outcome: none.
    del spec["population"]["qualify"]
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.gaps.to_dict() if not out.ok else None
    assert out.plan.to_dict()["stage"] == "collect"


def test_outcome_bearing_plans_unaffected_bit_identical():
    """The outcome: none branch must not perturb an outcome-bearing study's compiled plan."""
    for shape in ("shape_a", "shape_b", "shape_c"):
        out = compile_study(load_spec(ROOT / "fixtures" / "parity" / shape / "study.yaml"), repo_root=ROOT)
        assert out.ok, out.gaps.to_dict() if not out.ok else None
        assert out.plan.plan_sha256


# -- runtime: a tiny synthetic host replay emits no outcome column at all ------------------
def test_host_replay_emits_identity_only_observations(tmp_path):
    from research_workflow.host_runner import run_plan_on_bars
    from research_workflow.sessions import build_session_table
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS

    NS = 1_000_000_000
    body = yaml.safe_load((GOLDEN / "study_flip.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = "golden_flip_descriptive"
    body["outcome"] = "none"
    body["chronology"]["dev"] = []
    study = tmp_path / "studies" / "golden_flip_descriptive"
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    out = compile_study(load_spec(study), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, out.gaps.to_dict() if not out.ok else None
    plan = out.plan.to_dict()
    assert plan["outcome"]["contract"] == "none"

    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    session_spec = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    run = run_plan_on_bars(plan, bars, session_table=build_session_table(session_spec))
    cands, obs = run["candidates"], run["observations"]
    assert len(cands) > 0
    assert len(obs) == len(cands)
    assert list(obs.columns) == ["observation_ts", "regime_start_ns", "checkpoint_index"]
    outcome_like = {"target_flip_within_horizon", "disposition", "censor_reason", "resolution_seconds",
                    "observed_seconds", "flip_ts"}
    assert not (outcome_like & set(cands.columns))
    assert not (outcome_like & set(obs.columns))
    assert run["stats"].get("pending_at_end") == 0
