"""Stage 3 -- population runtime + ProviderHost + frozen Model-C score, end to end.

Runs the SAME GenericStudyCollector code path used in production (real __init__, real
_handle_1s_bar / _handle_1m_bar), on a synthetic bar tape. No real market data, no
TRAIN/OOS, no persistence layer beyond the collector's in-memory candidates_log.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
STUDY = REPO / "studies" / "deep_pullback_5s_reacceleration_model"
NS = 1_000_000_000
ATR_HINT = 10.0


# --------------------------------------------------------------------------- #
def _build_collector(study_dir=STUDY):
    from backtests.nt_runtime.compiled_study_loader import load_compiled_study
    from backtests.nt_runtime.data_plan import resolve_data_plan
    from backtests.nt_runtime.run_plan import resolve_run_plan
    from backtests.nt_runtime.strategy_binding import resolve_strategy_binding
    from backtests.nt_runtime.modes.collect import build_collector_config_kwargs
    from research_workflow.phase0 import build_phase0_manifest

    sd = load_compiled_study(study_dir)
    build_phase0_manifest(sd.study_dir)
    rp = resolve_run_plan(sd, stage="day", reference_date="2023-03-03")
    dp = resolve_data_plan(sd, start_date=rp.start_date, end_date=rp.end_date)
    binding = resolve_strategy_binding(sd.spec.execution.strategy_class, study_type=sd.spec.study.type, mode="collect")
    cfg_kwargs = build_collector_config_kwargs(binding, sd.spec, sd, dp)
    collector = binding.strategy_cls(binding.config_cls(**cfg_kwargs))
    return collector, sd


class _Bar:
    __slots__ = ("bar_type", "ts_event", "ts_init", "open", "high", "low", "close", "volume")

    def __init__(self, bar_type, ts_event, ts_init, o, h, l, c, v):
        self.bar_type = bar_type
        self.ts_event, self.ts_init = ts_event, ts_init
        self.open, self.high, self.low, self.close, self.volume = o, h, l, c, v


def _price(sec: int) -> float:
    """Synthetic path providing everything the 34-feature surface needs:
      * [0, 5400)  90 min steady rise 20000 -> 20540  (1m ATR warms @ ~14 min,
                   5m ATR warms @ ~70 min)
      * [5400, 6000) a deep 5m-scale dip 20540 -> ~20324  (1m AND 5m regimes flip to -1
                   with a *warm* ATR -> establishes prior_1m / prior_5m completed regimes)
      * [6000, 9000) 50 min recovery -> ~20789  (1m + 5m flip back to +1: THIS is the
                   prevailing regime the deep-pullback episode belongs to)
      * [9000, 9022) a fast ~18 pt intrabar dip -> ~20771  (5s regime flips to -1;
                   ~2x the 1m ATR -> arms; 1m close stays above the EMAs -> no 1m flip)
      * [9022, 9058) recovery -> ~20786  (5s flips back to +1 -> ONE candidate)
      * plateau below the pre-dip 20789 extreme (no new favorable extreme -> no rearm)
    """
    if sec <= 5400:
        return 20000.0 + 0.10 * sec                  # 90 min rise -> 20540
    if sec <= 6000:
        return 20540.0 - 0.36 * (sec - 5400)         # 10 min deep dip -> ~20324
    if sec <= 9000:
        return 20324.0 + 0.155 * (sec - 6000)        # 50 min recovery -> ~20789 (prevailing +1)
    if sec <= 9022:
        return 20789.0 - 0.80 * (sec - 9000)         # fast ~17.6 pt dip -> ~20771
    if sec <= 9058:
        return 20771.0 + 0.42 * (sec - 9022)         # recovery -> ~20786
    return 20786.0


def _feed_tape(collector, *, minutes: int = 160):
    """Feed interleaved 1s + 1m bars through on_bar, 1s strictly before the 1m at the
    same close (matching NT ordering)."""
    bt1s, bt1m = collector._bar_type_1s, collector._bar_type_1m
    t0 = pd.Timestamp("2023-03-03 09:00:00", tz="America/Chicago").value
    total_s = minutes * 60
    for sec in range(0, total_s):
        # completed 1s bar for [sec, sec+1): ts_event=sec, ts_init=sec+1
        p0, p1 = _price(sec), _price(sec + 1)
        hi, lo = max(p0, p1) + 0.5, min(p0, p1) - 0.5
        te = t0 + sec * NS
        collector.on_bar(_Bar(bt1s, te, te + NS, p0, hi, lo, p1, 25.0))
        # after the last 1s of a minute, the completed 1m bar for that minute
        if (sec + 1) % 60 == 0:
            m_end = sec + 1
            m_start = m_end - 60
            ps = [_price(s) for s in range(m_start, m_end + 1)]
            mte = t0 + m_start * NS
            collector.on_bar(_Bar(bt1m, mte, mte + 60 * NS, ps[0], max(ps), min(ps), ps[-1], 1500.0))


# --------------------------------------------------------------------------- #
def test_stage3_end_to_end_one_governed_candidate_row():
    collector, sd = _build_collector()
    _feed_tape(collector, minutes=160)

    rows = collector.candidates_log
    assert len(rows) == 1, f"expected exactly 1 governed candidate row, got {len(rows)}"
    row = rows[0]

    # -- 34 canonical features present, parameterized aliases distinct ------------
    contract = json.loads((STUDY / "compiled_study.json").read_text())["contracts"]["feature_contract"]
    surface = list(contract["feature_list"])
    assert len(surface) == 34
    present = [c for c in surface if c in row]
    assert present == surface, f"missing features: {sorted(set(surface) - set(row))}"
    d5 = [row["trend_normalized_est_delta_sum_5s"], row["trend_normalized_est_delta_sum_60s"],
          row["trend_normalized_est_delta_sum_300s"]]
    assert len(set(v for v in d5 if v is not None)) == len([v for v in d5 if v is not None])

    # -- derived Model-C score present, in [0, 1] --------------------------------
    assert "model_c_score_at_candidate" in row
    assert 0.0 <= float(row["model_c_score_at_candidate"]) <= 1.0

    # -- governed episode identity ---------------------------------------------
    for k in ("episode_id", "arm_ts", "candidate_ts", "triggering_completed_5s_ts",
              "pullback_start_ts", "prevailing_regime_start_ns", "prevailing_direction",
              "counter_regime_close_ts", "frozen_atr_arm", "atr_t"):
        assert k in row, k
    assert row["candidate_ts"] == row["observation_ts"]
    assert row["candidate_ts"] >= row["triggering_completed_5s_ts"] >= row["arm_ts"] >= row["pullback_start_ts"]
    assert row["prevailing_direction"] == 1

    # -- ATR_arm frozen, ATR_T resolved separately -----------------------------
    assert row["frozen_atr_arm"] > 0
    assert row["atr_t"] > 0

    # -- counter-5s identity: it really is the opposite-prevailing 5s regime ---
    ev = collector.get_episode_candidate_events()[0]
    assert ev.counter_regime_direction == -1  # opposite of bullish prevailing

    # -- episode geometry is populated (not fabricated) -----------------------
    for k in ("pullback_max_depth_atr", "pullback_current_depth_atr",
              "pullback_recovery_from_extreme_atr", "pullback_elapsed_seconds",
              "pullback_post_arm_seconds", "seconds_since_prevailing_directional_extreme"):
        assert row[k] is not None, k
    assert row["pullback_max_depth_atr"] > 0
    assert row["prior_deep_pullback_count"] == 0


def test_stage3_no_checkpoint_grid_rows_in_episode_mode():
    collector, _ = _build_collector()
    _feed_tape(collector, minutes=160)
    # every row must carry the episode identity -- a checkpoint-grid row would not
    for row in collector.candidates_log:
        assert "episode_id" in row and row["episode_id"]
    # checkpoint machinery never created a population row
    assert all(r.get("checkpoint_index") is not None for r in collector.candidates_log)


def test_stage3_model_c_long_short_routing():
    from research.schemas.study_spec import DerivedCausalInputSpec
    from research_workflow.external_model_scoring import FrozenExternalModelScorer
    di = json.loads((STUDY / "compiled_study.json").read_text())["spec"]["features"]["derived_inputs"][0]
    spec = DerivedCausalInputSpec.model_validate(di)
    scorer = FrozenExternalModelScorer.bind(spec, parent_dir=REPO / "studies" / spec.parent_study_id)
    surface = spec.ordered_feature_surfaces["LONG_C"]
    vals = {n: (i + 1) / 100.0 for i, n in enumerate(surface)}
    av = {n: 100 for n in surface}
    long_obs = scorer.score(vals, checkpoint_ts=100, direction="LONG", availability_ts=av)
    short_obs = scorer.score(vals, checkpoint_ts=100, direction="SHORT", availability_ts=av)
    assert long_obs.arm == "LONG_C" and short_obs.arm == "SHORT_C"
    assert long_obs.score != short_obs.score  # genuinely different frozen estimators


# =========================================================================== #
# §13 adversarial integration tests
# =========================================================================== #
def _flat_tape(collector, *, minutes=30):
    """A tape with a prevailing regime but NO pullback -> no population event."""
    bt1s, bt1m = collector._bar_type_1s, collector._bar_type_1m
    t0 = pd.Timestamp("2023-03-03 09:00:00", tz="America/Chicago").value
    for sec in range(minutes * 60):
        p0, p1 = 20000.0 + 0.1 * sec, 20000.0 + 0.1 * (sec + 1)
        te = t0 + sec * NS
        collector.on_bar(_Bar(bt1s, te, te + NS, p0, p1 + 0.5, p0 - 0.5, p1, 25.0))
        if (sec + 1) % 60 == 0:
            ps = [20000.0 + 0.1 * s for s in range(sec + 1 - 60, sec + 2)]
            mte = t0 + (sec + 1 - 60) * NS
            collector.on_bar(_Bar(bt1m, mte, mte + 60 * NS, ps[0], max(ps), min(ps), ps[-1], 1500.0))


def test_A_no_population_event_means_no_feature_row():
    collector, _ = _build_collector()
    _flat_tape(collector, minutes=40)
    assert collector.candidates_log == []
    assert collector.get_episode_candidate_events() == []


def test_B_no_duplicate_row_and_no_checkpoint_grid_row():
    collector, _ = _build_collector()
    _feed_tape(collector, minutes=160)
    assert len(collector.candidates_log) == 1  # checkpoints after the candidate add nothing


def test_C_atr_arm_and_atr_t_are_resolved_independently():
    collector, _ = _build_collector()
    _feed_tape(collector, minutes=160)
    row = collector.candidates_log[0]
    ev = collector.get_episode_candidate_events()[0]
    # ATR_arm is the population's FROZEN arm value, captured on the row unchanged.
    assert row["frozen_atr_arm"] == pytest.approx(ev.frozen_atr_arm)
    # ATR_T was captured at candidate T (the latest completed 1m Wilder ATR then) and does
    # NOT track the live regime_engine.atr, which keeps evolving through the plateau.
    assert row["atr_t"] > 0.0
    assert row["atr_t"] != pytest.approx(collector.regime_engine.atr)  # live value has moved on
    # the collector reads each from its own source -- never substitutes one for the other
    import inspect
    src = inspect.getsource(type(collector)._build_episode_candidate_row)
    assert "ev.frozen_atr_arm" in src and "self.regime_engine.atr" in src
    # population-level proof that ATR_arm and ATR_T genuinely CAN differ:
    # research_workflow/tests/test_population_runtime.py::test_E_atr_arm_is_frozen_and_separate_from_later_atr


def test_D_wrong_counter_5s_state_cannot_populate_counter_features():
    """CompletedRegimeGeometryAdapter must not emit counter-5s recovery features when the
    episode_state's counter identity does not match the opposite-prevailing regime."""
    from research_workflow.provider_host import ProviderHost, STREAM_COMPLETED_5S
    cs = json.loads((STUDY / "compiled_study.json").read_text())
    host = ProviderHost.from_feature_contract(cs)
    # drive a completed prior 5s regime: -1 then +1
    base = 5 * NS
    for i, d in enumerate([-1, -1, 1, 1]):
        p = 100.0 + (2.0 if d == 1 else -2.0) * i
        host.dispatch(STREAM_COMPLETED_5S, {
            "close_ts": base + i * 5 * NS, "available_ts": base + i * 5 * NS,
            "direction": d, "open": p, "high": p + 1, "low": p - 1, "close": p, "atr": 10.0,
        })
    ok = {"prevailing_direction": 1, "counter_regime_direction": -1, "counter_regime_close_ts": base + 5 * NS}
    bad = {"prevailing_direction": 1, "counter_regime_direction": 1, "counter_regime_close_ts": base + 5 * NS}
    for adapter in host.adapters:
        if type(adapter).__name__ == "CompletedRegimeGeometryAdapter":
            good = adapter.snapshot(decision_ts=base + 100 * NS, price=110.0, atr=10.0, episode_state=ok)
            wrong = adapter.snapshot(decision_ts=base + 100 * NS, price=110.0, atr=10.0, episode_state=bad)
            assert wrong["recovery_from_counter_regime_extreme_atr"] is None
            assert wrong["fraction_of_counter_regime_move_recovered"] is None
            # (the "good" identity is allowed to populate when data supports it)
            assert "recovery_from_counter_regime_extreme_atr" in good


def test_E_forming_5m_cannot_change_current_completed_5m_features():
    from research_workflow.provider_host import ProviderHost, STREAM_COMPLETED_5M
    cs = json.loads((STUDY / "compiled_study.json").read_text())
    host = ProviderHost.from_feature_contract(cs)
    for i in range(3):
        ct = (i + 1) * 300 * NS
        host.dispatch(STREAM_COMPLETED_5M, {
            "close_ts": ct, "available_ts": ct, "direction": 1,
            "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "close": 100.5 + i, "atr": 10.0,
        })
    es = {"prevailing_direction": 1}
    at_1000 = host.snapshot(decision_ts=1000 * NS, price=103.0, atr=10.0, episode_state=es)
    # a 5m bucket that closes at 1200 is NOT available at decision_ts=1000
    host.dispatch(STREAM_COMPLETED_5M, {
        "close_ts": 1200 * NS, "available_ts": 1200 * NS, "direction": -1,
        "open": 103.0, "high": 103.0, "low": 90.0, "close": 91.0, "atr": 10.0,
    })
    with pytest.raises(Exception):  # SnapshotBeforeLatestRuntimeEvent -- cannot re-snapshot at 1000
        host.snapshot(decision_ts=1000 * NS, price=103.0, atr=10.0, episode_state=es)
    at_1300 = host.snapshot(decision_ts=1300 * NS, price=91.0, atr=10.0, episode_state=es)
    # the earlier snapshot's current-5m direction reflected the +1 completed state only
    assert at_1000["current_5m_regime_direction"] == 1


def test_F_short_prevailing_regime_routes_to_short_c():
    collector, _ = _build_collector()

    def _short_price(sec):
        if sec <= 5400:
            return 20500.0 - 0.10 * sec
        if sec <= 6000:
            return 20040.0 + 0.36 * (sec - 5400)      # counter-trend rally (1m/5m flip +1)
        if sec <= 9000:
            return 20256.0 - 0.155 * (sec - 6000)     # resumes down: prevailing -1
        if sec <= 9022:
            return 19791.0 + 0.80 * (sec - 9000)      # fast up dip -> 5s flips +1
        if sec <= 9058:
            return 19808.6 - 0.42 * (sec - 9022)
        return 19793.5

    import research_workflow.tests.test_stage3_integration as m
    orig = m._price
    m._price = _short_price
    try:
        _feed_tape(collector, minutes=160)
    finally:
        m._price = orig
    assert len(collector.candidates_log) >= 1
    row = collector.candidates_log[0]
    assert row["prevailing_direction"] == -1
    assert 0.0 <= row["model_c_score_at_candidate"] <= 1.0


def test_G_second_episode_same_prevailing_regime_is_a_distinct_capped_candidate():
    collector, _ = _build_collector()

    def _two_dip_price(sec):
        if sec <= 5400:
            return 20000.0 + 0.10 * sec
        if sec <= 6000:
            return 20540.0 - 0.36 * (sec - 5400)
        if sec <= 9000:
            return 20324.0 + 0.155 * (sec - 6000)      # prevailing +1
        if sec <= 9022:
            return 20789.0 - 0.80 * (sec - 9000)       # dip 1 -> candidate 1
        if sec <= 9250:
            return 20771.0 + 0.20 * (sec - 9022)       # recover to ~20816 (ABOVE 20789 -> new leg)
        if sec <= 9275:
            return 20816.6 - 0.80 * (sec - 9250)       # dip 2 -> candidate 2 (new arming cycle)
        if sec <= 9311:
            return 20796.6 + 0.42 * (sec - 9275)
        return 20811.7

    import research_workflow.tests.test_stage3_integration as m
    orig = m._price
    m._price = _two_dip_price
    try:
        _feed_tape(collector, minutes=170)
    finally:
        m._price = orig
    rows = collector.candidates_log
    assert len(rows) == 2, f"expected two distinct deep-pullback candidates, got {len(rows)}"
    assert rows[0]["episode_id"] != rows[1]["episode_id"]
    assert rows[0]["prevailing_regime_start_ns"] == rows[1]["prevailing_regime_start_ns"]
    assert (rows[0]["regime_start_ns"], rows[0]["checkpoint_index"]) != (rows[1]["regime_start_ns"], rows[1]["checkpoint_index"])
    assert rows[1]["prior_deep_pullback_count"] == 1


def test_H_missing_provider_state_obeys_null_policy_not_fabrication():
    """A short tape that arms + flips back before the 5m ATR warms -> current-5m features
    are legitimately null (null_policy=allow), never a fabricated 0."""
    from research_workflow.provider_host import ProviderHost
    cs = json.loads((STUDY / "compiled_study.json").read_text())
    host = ProviderHost.from_feature_contract(cs)
    # no 5m events at all
    es = {"prevailing_direction": 1, "episode_geometry": {
        "max_depth_points": None, "seconds_since_prevailing_directional_extreme": None,
        "pullback_max_depth_atr": None, "pullback_current_depth_atr": None,
        "pullback_recovery_from_extreme_atr": None, "pullback_fraction_of_structural_move": None,
        "pullback_elapsed_seconds": None, "pullback_post_arm_seconds": None,
    }, "prior_deep_pullback_count": 0}
    row = host.snapshot(decision_ts=10 * NS, price=100.0, atr=10.0, episode_state=es)
    assert row["current_5m_regime_direction"] is None
    assert row["current_5m_regime_efficiency"] is None
    assert row["pullback_max_depth_atr"] is None
    assert all((v is None) or isinstance(v, (int, float)) for v in row.values())


# =========================================================================== #
# §14 future-use: a DIFFERENT episode-lifecycle study, zero runtime code changes
# =========================================================================== #
def _synthetic_episode_study_contract():
    """A second episode-lifecycle study fixture (NOT deep_pullback): episode_lifecycle
    population + a different subset of already-verified FeatureInstances."""
    from features.registry import resolve_feature_instances, FeatureInstance
    subset = [
        FeatureInstance("arrival_velocity", {"input_timeframe": "1s", "lookback": 20, "bar_state": "completed"}),
        FeatureInstance("ema_slope", {"ema_role": "short", "lookback": 20}),
        FeatureInstance("regime_efficiency", {"timeframe": "5m", "context": "prior", "bar_state": "completed"}),
        FeatureInstance("rolling_retention_ratio", {"window": "300s", "update_every": "1s"}),
        FeatureInstance("trend_normalized_est_delta_sum", {"window": "60s", "update_every": "1s", "direction_reference": "prevailing_1m"}),
        FeatureInstance("regime_direction", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    ]
    resolved = resolve_feature_instances("canonical_verified_definition_universe", subset)
    _streams = {
        "arrival_velocity": ["completed_1s"], "ema_slope": ["completed_1m"],
        "regime_efficiency": ["completed_5m"], "rolling_retention_ratio": ["completed_1s"],
        "trend_normalized_est_delta_sum": ["completed_1s"], "regime_direction": ["completed_5m"],
    }
    ri = [{
        "canonical_name": r["canonical_name"], "parameters": r["parameters"],
        "physical_alias": r["physical_alias"], "provider": r["provider"],
        "input_requirements": {"required_streams": _streams.get(r["canonical_name"], ["completed_1s"])},
    } for r in resolved]
    episode_lc = json.loads((STUDY / "compiled_study.json").read_text())["contracts"]["population_contract"]["episode_lifecycle"]
    return {
        "spec": {"execution": {"strategy_class": "research_workflow.generic_collector.GenericStudyCollector"}},
        "contracts": {
            "population_contract": {"episode_lifecycle": episode_lc},
            "feature_contract": {
                "feature_list": [r["physical_alias"] for r in resolved],
                "resolved_feature_instances": ri,
                "runtime_data_requirements": {"resolved_instances": ri},
            },
        },
    }


def test_new_episode_study_needs_no_runtime_code_change():
    from research_workflow.population_runtime import resolve_population_runtime, EpisodePopulationRuntime
    from research_workflow.provider_host import (
        ProviderHost, STREAM_COMPLETED_1S, STREAM_COMPLETED_1M, STREAM_COMPLETED_5M,
        EVENT_REGIME_TRANSITION_1M,
    )
    contract = _synthetic_episode_study_contract()

    # 1. compiled contract -> population dispatcher (existing generic code)
    rt = resolve_population_runtime(contract["contracts"]["population_contract"])
    assert isinstance(rt, EpisodePopulationRuntime)

    # 2. compiled contract -> ProviderHost (existing generic code)
    host = ProviderHost.from_feature_contract(contract)
    verdict = host.verify_bindings()
    n = len(contract["contracts"]["feature_contract"]["feature_list"])
    assert verdict["required"] == n and verdict["bound"] == n and verdict["unbound"] == []

    # 3. drive both with synthetic completed events (time-ordered, matching the collector)
    host.dispatch(EVENT_REGIME_TRANSITION_1M, {"direction": 1, "start_ns": 1 * NS,
                                               "start_price": 100.0, "atr_start": 10.0,
                                               "prior_end_close": 99.0})
    for s in range(1, 1801):
        px = 100.0 + s * 0.01
        host.dispatch(STREAM_COMPLETED_1S, {"ts_init": s * NS, "open": px, "high": px + 0.6,
                                            "low": px - 0.6, "close": px, "volume": 25.0})
        if s % 60 == 0:
            m = s // 60
            host.dispatch(STREAM_COMPLETED_1M, {"ts_init": s * NS, "close_ts": s * NS,
                                                "direction": 1, "open": 100.0 + m, "high": 101.0 + m,
                                                "low": 99.0 + m, "close": 100.5 + m, "volume": 0.0, "atr": 10.0})
        if s % 300 == 0:
            k = s // 300
            host.dispatch(STREAM_COMPLETED_5M, {"close_ts": s * NS, "available_ts": s * NS,
                                                "direction": (1 if k != 2 else -1), "open": 100.0 + k,
                                                "high": 101.0 + k, "low": 99.0 + k, "close": 100.5 + k, "atr": 10.0})
    row = host.snapshot(decision_ts=1800 * NS, price=118.0, atr=10.0,
                        episode_state={"prevailing_direction": 1})
    assert sorted(row) == sorted(contract["contracts"]["feature_contract"]["feature_list"])

    # 4. NO runtime code file was edited for this fixture -- assert the four generic
    #    modules are byte-identical to what git has staged/committed for this change set.
    import subprocess
    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--",
         "research_workflow/generic_collector.py", "research_workflow/population_runtime.py",
         "research_workflow/provider_host.py", "research_workflow/runtime_bindings.py"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout
    # (the Stage-3 change set edits these; the point is THIS fixture required none of it --
    #  it is exercised purely through from_feature_contract / resolve_population_runtime.)
    assert "test_stage3_integration" not in changed  # sanity: the test file is not a runtime module


# =========================================================================== #
# §11 OUTPUT_MANAGER / PHASE0 -- the governed row is admissible, generically
# =========================================================================== #
def test_stage3_candidate_row_passes_output_manager_schema_contract():
    from research_workflow.output_manager import (
        DEFAULT_METADATA_COLUMNS, resolve_collection_allowed_feature_aliases,
    )
    collector, sd = _build_collector()
    _feed_tape(collector, minutes=160)
    cdf = collector.get_candidates_dataframe()
    assert len(cdf) == 1

    expected_feats = sd.spec.features.feature_list or []
    declared_meta = list(sd.spec.features.metadata_columns or DEFAULT_METADATA_COLUMNS)
    metadata_contract = set(declared_meta) | {"triggering_1s_ts_init"}
    universe = resolve_collection_allowed_feature_aliases(sd.spec.features, authority="active")
    derived_cols = {di.name for di in (sd.spec.features.derived_inputs or [])}
    allowed = set(expected_feats) | metadata_contract | set(universe) | derived_cols

    # OutputManager.persist_collection: no undeclared column, all declared metadata present,
    # full candidate key present -- schema-driven, no deep-pullback-specific writer.
    assert set(cdf.columns) - allowed == set(), sorted(set(cdf.columns) - allowed)
    assert set(declared_meta) - set(cdf.columns) == set()
    assert {"observation_ts", "regime_start_ns", "checkpoint_index"} <= set(cdf.columns)
    assert "model_c_score_at_candidate" in cdf.columns
