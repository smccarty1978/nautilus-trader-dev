"""Grammar and compiler tests: the predicate language stays tiny, set-expansion is exact,
gaps are typed, and the three parity compositions compile without opening a catalog."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_workflow.grammar import compile_study, load_spec
from research_workflow.grammar.expansion import expand_instances
from research_workflow.grammar.gaps import GapKind
from research_workflow.grammar.predicates import PredicateSyntaxError, parse_predicate, referenced_roots, render

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"


def test_predicates_parse_and_render_canonically():
    cases = {
        "a.x >= 120s and b.y >= 1.0": "a.x >= 120s and b.y >= 1.0",
        "state == WATCH and r5.turned(from=-r1.dir, to=r1.dir) and age(WATCH) > 0": "state == WATCH and r5.turned(from=-r1.dir, to=r1.dir) and age(WATCH) > 0",
        "not (a.x in [1, 2]) or b.flipped": "not (a.x in [1, 2]) or b.flipped",
        "x.depth_atr >= 2.5": "x.depth_atr >= 2.5",
    }
    for text, canon in cases.items():
        ast = parse_predicate(text)
        assert render(ast) == canon
        assert render(parse_predicate(render(ast))) == canon


def test_predicate_language_rejects_arithmetic_and_unknown_syntax():
    for bad in ("a.x + 1 > 0", "a.x * b.y > 1", "foo(", "a.x >", "lambda: 1", "a.x ** 2"):
        with pytest.raises(PredicateSyntaxError):
            parse_predicate(bad)


def test_referenced_roots():
    assert referenced_roots(parse_predicate("a.x > 1 and b.turned(to=c.dir) or state == WATCH")) == {"a", "b", "c", "state"}


def test_set_expansion_is_cartesian_and_ordered():
    rows = expand_instances([{"feature": "f", "over": {"timeframe": ["1m", "5m"], "context": ["prior", "current"]}, "bar_state": "completed"}])
    assert [r["parameters"] for r in rows] == [
        {"bar_state": "completed", "timeframe": "1m", "context": "prior"}, {"bar_state": "completed", "timeframe": "1m", "context": "current"},
        {"bar_state": "completed", "timeframe": "5m", "context": "prior"}, {"bar_state": "completed", "timeframe": "5m", "context": "current"}]
    with pytest.raises(ValueError):
        expand_instances([{"feature": "f", "over": {"timeframe": ["1m"]}, "alias": "x"}])


@pytest.mark.parametrize("shape", ["shape_a", "shape_b", "shape_c"])
def test_parity_compositions_compile_statically(shape):
    out = compile_study(load_spec(ROOT / "fixtures" / "parity" / shape / "study.yaml"), repo_root=ROOT)
    assert out.ok, out.card()
    card = out.plan.card()
    assert card["catalog_opened"] is False
    assert all(b["bound"] for b in out.plan.binding_proof)
    assert out.plan.plan_sha256 and out.plan.closure["composite_sha256"]


def _gap_kinds(spec):
    out = compile_study(spec, repo_root=ROOT)
    assert not out.ok
    return {(g.kind, g.where) for g in out.gaps.gaps}


def _base():
    return load_spec(ROOT / "fixtures" / "parity" / "shape_a" / "study.yaml")


def test_gap_missing_capability():
    spec = _base(); spec["context"]["nope"] = {"tracker": "regime.does_not_exist", "timeframe": "1m"}
    assert (GapKind.MISSING_CAPABILITY, "context.nope") in _gap_kinds(spec)


def test_gap_invalid_parameterization():
    spec = _base(); spec["context"]["regime_1m"]["bogus_param"] = 3
    assert (GapKind.INVALID_PARAMETERIZATION, "context.regime_1m") in _gap_kinds(spec)


def test_gap_unavailable_stream():
    spec = _base(); spec["streams"][0]["dataset"] = "NO_SUCH_DATASET"
    assert (GapKind.UNAVAILABLE_STREAM, "streams[0]") in _gap_kinds(spec)


def test_gap_unsupported_composition_event_in_qualify():
    spec = _base(); spec["population"]["qualify"] = "regime_1m.flipped"
    assert (GapKind.UNSUPPORTED_COMPOSITION, "population.qualify") in _gap_kinds(spec)


def test_gap_semantic_decision_chronology_double_use():
    spec = _base(); spec["model"] = {"family": "lightgbm", "validation": {"protocol": "model_selection.random", "tuning_years": [2021, 2022, 2023], "final_train_validation_years": [2023]}}
    assert any(k == GapKind.SEMANTIC_DECISION_REQUIRED for k, _ in _gap_kinds(spec))


def test_gap_ambiguous_temporal_semantics_atr_availability():
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_c" / "study.yaml")
    spec["outcome"].pop("atr_availability")
    assert (GapKind.AMBIGUOUS_TEMPORAL_SEMANTICS, "outcome.atr_availability") in _gap_kinds(spec)


def test_label_contract_refuses_decision_close_entry():
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_c" / "study.yaml")
    spec["outcome"]["entry_reference"] = "decision_close"
    assert (GapKind.INVALID_PARAMETERIZATION, "outcome.entry_reference") in _gap_kinds(spec)


def test_same_timestamp_opt_in_requires_a_decision():
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    spec = load_spec(GOLDEN / "study_barrier.yaml")
    spec["streams"][1]["same_ts"] = "available"
    out = compile_study(spec, repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert not out.ok and any(g.kind == GapKind.SEMANTIC_DECISION_REQUIRED for g in out.gaps.gaps)


def test_score_mode_reuses_frozen_models_and_validates_labels():
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_c" / "study.yaml")
    mid = "0" * 64
    spec["model"] = {"mode": "score", "models": [{"id": mid, "label": "target_tp1_sl1_0_label", "subset": {"regime_direction": -1}, "name": "LONG_SL1_0"}]}
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.card()
    assert out.plan.model["mode"] == "score" and out.plan.model["models"][0]["name"] == "LONG_SL1_0" and out.plan.model["family"] is None
    spec["model"]["models"][0]["label"] = "not_a_label"
    assert (GapKind.INVALID_PARAMETERIZATION, "model.models[0].label") in _gap_kinds(spec)
    spec["model"] = {"mode": "score"}
    out = compile_study(spec, repo_root=ROOT)
    assert not out.ok and any(g.kind == GapKind.INVALID_PARAMETERIZATION for g in out.gaps.gaps)


def test_coarser_external_timeframes_are_context_streams():
    """Only the finest external timeframe of the execution instrument carries epochs; the 1m bar closing at
    an epoch T must be a context stream (visible strictly before the epoch) enforced by the host, not by feed order."""
    out = compile_study(load_spec(ROOT / "fixtures" / "parity" / "shape_b" / "study.yaml"), repo_root=ROOT)
    assert out.ok, out.card()
    roles = {s["key"]: (s["role"], s["visibility"], s["source"]) for s in out.plan.streams}
    assert roles["nq_1s"] == ("execution", "at_epoch", "external")
    assert roles["nq_1m"] == ("context", "strictly_before", "external")
    assert roles["nq_5s"][0] == "execution" and roles["nq_5s"][2] == "derived"


def test_search_space_requires_walk_forward_protocol_and_two_tuning_years():
    spec = _base()
    spec["model"] = {"family": "lightgbm", "search_space": {"n_estimators": [50, 100]},
                     "validation": {"protocol": "model_selection.random", "tuning_years": [2021], "final_train_validation_years": []}}
    assert (GapKind.SEMANTIC_DECISION_REQUIRED, "model.validation.tuning_years") in _gap_kinds(spec)
    spec["model"]["validation"]["tuning_years"] = [2021, 2022]
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.card()
    assert out.plan.model["search_space"] == {"n_estimators": {"choices": [50, 100]}}
    spec["model"]["search_space"] = {"max_depth": {"low": 2, "high": 6, "int": True, "bogus": 1}}
    assert (GapKind.INVALID_PARAMETERIZATION, "model.search_space.max_depth") in _gap_kinds(spec)


def test_old_runtime_policy_blocks_new_v1_studies_but_not_historical_ones(tmp_path):
    from research_workflow.policy import OldRuntimePolicyError, assert_old_runtime_allowed
    new_v1 = tmp_path / "new_v1"; new_v1.mkdir()
    (new_v1 / "study.yaml").write_text("study:\n  id: new_v1\n  type: flip_prediction\nexecution:\n  strategy_class: research_workflow.generic_collector.GenericStudyCollector\n", encoding="utf-8")
    with pytest.raises(OldRuntimePolicyError, match="OLD_RUNTIME_LEGACY_ONLY"):
        assert_old_runtime_allowed(new_v1)
    hist = ROOT / "studies" / "regime_transition_target_before_stop_v1"
    if (hist / "study.yaml").is_file():
        assert assert_old_runtime_allowed(hist)["platform"] == "v1_historical"
    assert assert_old_runtime_allowed(ROOT / "studies" / "v2_shape_a_flip_180s")["platform"] == "v2"
