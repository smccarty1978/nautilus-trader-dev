"""Grammar and compiler tests: the predicate language stays tiny, set-expansion is exact,
gaps are typed, and the three parity compositions compile without opening a catalog."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_workflow.grammar.compiler import (_mark_epoch_bearing_stream, _validate_runtime_composition,
                                                 compile_study, load_spec)
from research_workflow.grammar.gaps import CapabilityGapReport
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


def test_gap_strict_max_gap_at_or_beyond_horizon_is_semantic_decision_required():
    # WARN-3: under the default horizon_end_rule ("strict") a max_gap that is not strictly
    # shorter than the horizon it is meant to guard can never be exceeded -- the horizon-end
    # unobserved span is bounded by the horizon itself, so a tape with zero interior
    # observations silently falls through to the expiry policy instead of censoring GAP.
    spec = _base(); spec["outcome"]["max_gap"] = "200s"  # horizon is 180s
    assert (GapKind.SEMANTIC_DECISION_REQUIRED, "outcome.max_gap") in _gap_kinds(spec)


def test_gap_strict_max_gap_shorter_than_horizon_compiles_clean():
    # Control: max_gap strictly shorter than the horizon is not flagged.
    spec = _base(); spec["outcome"]["max_gap"] = "60s"  # horizon is 180s
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.card()


def test_strict_gap_rule_surfaced_in_compiled_outcome_contract():
    out = compile_study(load_spec(ROOT / "fixtures" / "parity" / "shape_a" / "study.yaml"), repo_root=ROOT)
    assert out.ok, out.card()
    assert "strict_gap_rule" in out.plan.outcome and out.plan.outcome["strict_gap_rule"]


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


def test_completed_bar_cadence_stream_is_visible_at_its_own_epoch():
    """G7a.  ``cadence: completed_1m`` on a dataset that also declares external 1s leaves nq_1m a
    queued CONTEXT stream (released strictly before the next execution bar) but marks it visible AT
    the epoch: the epoch it raises is that bar's own close, and the 1s bar closing at the same
    instant is already applied, so nothing is ahead of T."""
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_b" / "study.yaml")
    spec["population"]["cadence"] = "completed_1m"
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.card()
    nq_1m = next(s for s in out.plan.streams if s["key"] == "nq_1m")
    assert (nq_1m["role"], nq_1m["visibility"], nq_1m["epoch_bearing"]) == ("context", "at_epoch", True)
    assert out.plan.population["cadence"] == {"kind": "completed_bar", "stream": "nq_1m", "every_ns": 60 * 1_000_000_000}
    assert any("completed-bar cadence stream" in n for n in out.plan.notes)
    # the availability table is what an auditor reads: it must carry the same fact
    rows = {r["id"]: r for r in out.plan.availability["rows"] if r.get("stream") == "nq_1m"}
    assert rows and all(r["visibility"] == "at_epoch" for r in rows.values())


@pytest.mark.parametrize("dataset,empty", [(None, "none"), ("NQ_1S_V2_GLOBEX", "zero_volume_in_trading_day")])
def test_derived_streams_are_closed_window_from_the_coarsest_epoch_visible_source(dataset, empty):
    """A1/D1: under a 1m cadence, 3m/5m/1h derive from nq_1m (visible at the epoch) and 5s from nq_1s;
    every derived stream is closed_window; empty windows are zero-volume bars only on a dataset whose
    `sessions` calendar can say what a trading day is."""
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_b" / "study.yaml")
    spec["streams"][0]["timeframes"] = list(spec["streams"][0]["timeframes"]) + ["3m", "1h"]
    if dataset:
        spec["streams"][0]["dataset"] = dataset
    spec["population"]["cadence"] = "completed_1m"
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.card()
    by = {s["key"]: s for s in out.plan.streams}
    assert {k: by[k]["derived_from"] for k in ("nq_5s", "nq_3m", "nq_5m", "nq_1h")} == {
        "nq_5s": "nq_1s", "nq_3m": "nq_1m", "nq_5m": "nq_1m", "nq_1h": "nq_1m"}
    derived = [s for s in out.plan.streams if s["source"] == "derived"]
    assert {(s["aggregation"], s["empty_window"]) for s in derived} == {("closed_window", empty)}
    assert by["nq_1m"]["ts_init_delta_ns"] == 60 * 1_000_000_000


def test_stream_roles_are_resolved_over_the_timeframes_the_study_requests():
    """The dataset declares external 1s AND 1m; a study that requests neither of them cannot derive
    anything.  Resolving ``finest`` over the DATASET's externals wrote ``derived_from: nq_1s`` into a
    plan that carried no nq_1s -- a compile that succeeds and a host that cannot be constructed."""
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_b" / "study.yaml")
    spec["streams"][0]["timeframes"] = ["5s", "5m"]
    out = compile_study(spec, repo_root=ROOT)
    assert not out.ok
    assert (GapKind.UNAVAILABLE_STREAM, "streams[0].timeframes") in {(g.kind, g.where) for g in out.gaps.gaps}


@pytest.mark.parametrize("shape,cadence", [("shape_a", None), ("shape_b", None), ("shape_c", None), ("shape_b", "completed_1m")])
def test_every_compiled_plan_is_constructible_by_the_host(shape, cadence):
    """G7b as a property: whatever the host multiplexer refuses to build, the compiler must refuse to
    emit.  A runtime assertion after a frame seal is not an acceptable outcome for a composition the
    compiler accepted."""
    from research_workflow.host.mux import StreamMux
    spec = load_spec(ROOT / "fixtures" / "parity" / shape / "study.yaml")
    if cadence:
        spec["population"]["cadence"] = cadence
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.card()
    mux = StreamMux(out.plan.streams, lambda bar: None)
    epoch_stream = out.plan.population["cadence"]["stream"]
    assert epoch_stream in mux.at_epoch_streams


class _StubCtx:
    """Only what the two composition checks touch: streams, notes and the gap report."""

    def __init__(self, streams):
        self.streams = [dict(s) for s in streams]
        self.notes = []
        self.gaps = CapabilityGapReport("stub")

    def gap(self, kind, where, message, **detail):
        self.gaps.add(kind, where, message, **detail)


def _stub_streams():
    ns = 1_000_000_000
    return [{"key": "nq_1s", "instrument": "NQ", "timeframe": "1s", "duration_ns": ns, "role": "execution",
             "source": "external", "visibility": "at_epoch"},
            {"key": "nq_5s", "instrument": "NQ", "timeframe": "5s", "duration_ns": 5 * ns, "role": "execution",
             "source": "derived", "derived_from": "nq_1s", "aggregation": "complete_bucket", "visibility": "at_epoch"},
            {"key": "nq_1m", "instrument": "NQ", "timeframe": "1m", "duration_ns": 60 * ns, "role": "context",
             "source": "external", "visibility": "strictly_before"}]


def test_non_constructible_stream_graph_is_a_typed_gap_not_a_runtime_error():
    """Adversarial: a derived stream whose source is not in the plan.  The dry construction of the
    real StreamMux is what closes the class -- the message names the host, not a stack trace."""
    streams = [s for s in _stub_streams() if s["key"] != "nq_1s"]
    ctx = _StubCtx(streams)
    _validate_runtime_composition(ctx, {"cadence": {"kind": "completed_bar", "stream": "nq_1m"}})
    assert (GapKind.UNSUPPORTED_COMPOSITION, "streams") in {(g.kind, g.where) for g in ctx.gaps.gaps}


def test_cadence_stream_declared_strictly_before_is_a_typed_gap():
    """Adversarial: the exact runtime failure G7 hit, now refused at compile.  If anything ever
    leaves a cadence stream strictly_before, the compile returns a gap instead of sealing a plan
    that raises CONTEXT_STREAM_VISIBLE_AT_EPOCH on its first epoch."""
    ctx = _StubCtx(_stub_streams())
    _validate_runtime_composition(ctx, {"cadence": {"kind": "completed_bar", "stream": "nq_1m"}})
    assert (GapKind.UNSUPPORTED_COMPOSITION, "population.cadence") in {(g.kind, g.where) for g in ctx.gaps.gaps}


def test_context_cadence_with_no_execution_stream_is_refused():
    """The one composition G7a cannot cover: the mux drains the context queue only ahead of an
    execution bar, so with no execution stream every epoch would fire at flush, at the end of the run."""
    streams = [dict(s, role="context", visibility="strictly_before") for s in _stub_streams()]
    ctx = _StubCtx(streams)
    _mark_epoch_bearing_stream(ctx, "nq_1m", "NQ")
    assert (GapKind.UNSUPPORTED_COMPOSITION, "population.cadence") in {(g.kind, g.where) for g in ctx.gaps.gaps}
    assert all(s["visibility"] == "strictly_before" for s in ctx.streams)


def test_cadence_stream_on_the_execution_stream_is_untouched():
    """Control: the overwhelmingly common composition must not change at all -- gate 4 (existing
    sealed studies reproduce bit-identically) rests on this."""
    ctx = _StubCtx(_stub_streams())
    _mark_epoch_bearing_stream(ctx, "nq_1s", "NQ")
    assert ctx.gaps.ok and ctx.notes == []
    assert ctx.streams == _stub_streams()


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
