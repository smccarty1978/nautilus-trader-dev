"""Stage 1 acceptance for the adapter-based generic runtime feature host.

Exercises ``ProviderHost`` end to end on a *synthetic* completed-event tape only --
no real market data, no collector wiring, no population engine. Proves:

  * all 34 deep-pullback FeatureInstances resolve to runtime adapters,
  * every required physical alias is distinct,
  * no required FeatureInstance is unbound,
  * the host produces the full 34-column candidate snapshot under sufficient
    synthetic state, with the required columns non-null,
  * parameterized instances stay distinct,
  * a canonical provider with no registered adapter fails closed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_workflow.provider_host import (
    ADAPTER_REGISTRY,
    EVENT_EPISODE_START,
    EVENT_REGIME_TRANSITION_1M,
    ProviderHost,
    RuntimeProviderBindingMissing,
    STREAM_COMPLETED_1M,
    STREAM_COMPLETED_1S,
    STREAM_COMPLETED_5M,
    STREAM_COMPLETED_5S,
)

NS = 1_000_000_000
REPO = Path(__file__).resolve().parents[2]
STUDY = REPO / "studies" / "deep_pullback_5s_reacceleration_model"
ATR = 10.0
PREVAILING = 1  # bullish prevailing regime


def _price(t: int) -> float:
    """Synthetic bullish path with a late adverse pullback and partial recovery."""
    if t <= 180:
        return 20000.0 - 40.0 * t / 180.0          # bearish warmup regime
    if t <= 1400:
        return 19960.0 + 0.52 * (t - 180)          # bullish drift -> ~20594
    if t <= 1440:
        return 20594.4 - 1.4 * (t - 1400)          # pullback -> ~20538
    return 20538.4 + 1.0 * (t - 1440)              # recovery -> ~20598


def _bar(t0: int, t1: int) -> tuple[float, float, float, float]:
    pts = [_price(t) for t in range(t0, t1 + 1)]
    return pts[0], max(pts), min(pts), pts[-1]


def _build_tape() -> list[tuple[int, str, dict]]:
    """A timestamp-sorted list of normalized (ts, event_type, payload)."""
    ev: list[tuple[int, str, dict]] = []

    # 1m regime transitions: bearish [0,180), bullish [180, ...]
    ev.append((0, EVENT_REGIME_TRANSITION_1M, dict(
        direction=-1, start_ns=0, start_price=_price(0), atr_start=ATR, prior_end_close=_price(0))))
    ev.append((180 * NS, EVENT_REGIME_TRANSITION_1M, dict(
        direction=1, start_ns=180 * NS, start_price=_price(180), atr_start=ATR,
        prior_end_close=_price(179))))

    # completed 1s bars, ts_event = t, ts_init = t + 1s
    for t in range(0, 1500):
        o, h, l, c = _bar(t, t + 1)
        ev.append(((t + 1) * NS, STREAM_COMPLETED_1S, dict(
            ts_init=(t + 1) * NS, open=o, high=h, low=l, close=c, volume=100.0 + (t % 7),
            arm_atr=ATR)))

    # completed 1m bars (drive ema history + regime-geometry current-1m state)
    for m in range(0, 25):
        t0, t1 = m * 60, m * 60 + 60
        o, h, l, c = _bar(t0, t1)
        direction = -1 if t1 <= 180 else 1
        ev.append((t1 * NS, STREAM_COMPLETED_1M, dict(
            ts_init=t1 * NS, close_ts=t1 * NS, direction=direction,
            open=o, high=h, low=l, close=c, volume=6000.0, atr=ATR)))

    # completed 5m bars: bearish at 300, bullish thereafter
    for k in range(1, 6):
        ct = k * 300
        o, h, l, c = _bar(ct - 300, ct)
        direction = -1 if ct == 300 else 1
        ev.append((ct * NS, STREAM_COMPLETED_5M, dict(
            close_ts=ct * NS, direction=direction, open=o, high=h, low=l, close=c, atr=ATR)))

    # completed 5s bars: prevailing +1, a counter -1 stretch through the pullback,
    # then flip back to +1 before the decision.
    for s in range(5, 1501, 5):
        o, h, l, c = _bar(s - 5, s)
        if 1405 <= s <= 1440:
            direction = -1
        else:
            direction = 1
        ev.append((s * NS, STREAM_COMPLETED_5S, dict(
            close_ts=s * NS, direction=direction, open=o, high=h, low=l, close=c, atr=ATR)))

    # episode start at the prevailing favorable extreme (t = 1400)
    ev.append((1400 * NS, EVENT_EPISODE_START, dict(
        start_ns=1400 * NS, direction=PREVAILING, favorable_extreme_price=_price(1400),
        arm_threshold_atr=1.0)))

    ev.sort(key=lambda row: (row[0], 0 if row[1] == EVENT_REGIME_TRANSITION_1M else 1))
    return ev


def _run_host(host: ProviderHost, decision_t: int = 1500) -> dict:
    for ts, event_type, payload in _build_tape():
        if ts > decision_t * NS:
            break
        host.dispatch(event_type, payload)
    episode_state = dict(
        armed=True,
        prevailing_direction=PREVAILING,
        prevailing_extreme_ts=1400 * NS,
        prior_deep_pullback_count=2,
        regime_expansion_atr_per_min=0.35,
    )
    return host.snapshot(
        decision_ts=decision_t * NS, price=_price(decision_t), atr=ATR,
        episode_state=episode_state,
    )


@pytest.fixture()
def compiled_study() -> dict:
    return json.loads((STUDY / "compiled_study.json").read_text(encoding="utf-8"))


def test_all_34_featureinstances_resolve_to_adapters(compiled_study):
    host = ProviderHost.from_feature_contract(compiled_study)
    verdict = host.verify_bindings()
    assert verdict["required"] == 34
    assert verdict["passed"], verdict["unbound"]
    assert verdict["bound"] == 34
    assert verdict["unbound"] == []


def test_every_required_physical_alias_is_distinct(compiled_study):
    host = ProviderHost.from_feature_contract(compiled_study)
    aliases = [s.physical_alias for s in host.instances]
    assert len(aliases) == len(set(aliases)) == 34


def test_binding_metadata_is_machine_readable_and_complete(compiled_study):
    host = ProviderHost.from_feature_contract(compiled_study)
    meta = host.binding_metadata()
    assert len(meta) == 34
    for record in meta:
        assert record["canonical_name"]
        assert record["canonical_provider"] in ADAPTER_REGISTRY
        assert record["runtime_adapter"]
        assert record["physical_alias"]
        assert record["bound"] is True
        assert set(record["required_streams"]) <= {
            "completed_1s", "completed_1m", "completed_5m", "completed_5s",
        }


def test_synthetic_34_feature_snapshot_is_complete_and_required_non_null(compiled_study):
    host = ProviderHost.from_feature_contract(compiled_study)
    row = _run_host(host)

    declared = [s.physical_alias for s in host.instances]
    assert sorted(row) == sorted(declared)
    assert len(row) == 34

    # feature_null_policies for this study are all "allow", but the synthetic tape is
    # built to satisfy every provider availability guard, so under sufficient state the
    # host must actually produce values -- an all-null 34 columns would be a silent
    # binding failure. Assert a strong non-null floor across every provider family.
    non_null = {k for k, v in row.items() if v is not None}
    # Under the fully-provisioned synthetic tape every provider guard is satisfied,
    # so all 34 columns must carry a real value.
    assert sorted(non_null) == sorted(row), (
        f"null under sufficient state: {sorted(set(row) - non_null)}"
    )
    must_be_present = {
        # structural family
        "prior_1m_regime_efficiency", "prior_5m_regime_efficiency",
        "current_5m_regime_age_min", "current_5m_regime_efficiency",
        "current_5m_regime_mfe_atr", "current_5m_regime_range_atr",
        # rolling family
        "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
        "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr",
        # arrival + context
        "arrival_velocity", "arrival_acceleration", "ema_slope",
        # episode geometry
        "pullback_max_depth_atr", "pullback_current_depth_atr",
        "pullback_recovery_from_extreme_atr", "pullback_elapsed_seconds",
        "pullback_post_arm_seconds", "seconds_since_prevailing_directional_extreme",
        "prior_deep_pullback_count",
        # counter-regime + current 5m direction/alignment
        "recovery_from_counter_regime_extreme_atr",
        "fraction_of_counter_regime_move_recovered",
        "current_5m_regime_direction", "regime_alignment",
        # direction-normalized est-delta
        "trend_normalized_est_delta_sum_5s", "trend_normalized_est_delta_sum_60s",
        "trend_normalized_est_delta_sum_300s",
    }
    missing = sorted(must_be_present - non_null)
    assert not missing, f"required-non-null columns came back null: {missing}"

    assert row["prior_deep_pullback_count"] == 2
    assert row["current_5m_regime_direction"] == 1
    assert row["regime_alignment"] == 1
    assert row["pullback_max_depth_atr"] > 0.0


def test_parameterized_instances_stay_distinct(compiled_study):
    host = ProviderHost.from_feature_contract(compiled_study)
    row = _run_host(host)
    # three trend-normalized windows must be genuinely different computations
    s5 = row["trend_normalized_est_delta_sum_5s"]
    s60 = row["trend_normalized_est_delta_sum_60s"]
    s300 = row["trend_normalized_est_delta_sum_300s"]
    assert s5 != s60 != s300
    # and the two ratios reference different numerator windows
    assert (row["trend_normalized_est_delta_sum_ratio_5s_vs_300s"]
            != row["trend_normalized_est_delta_sum_ratio_60s_vs_300s"])


def test_missing_adapter_fails_closed():
    fake = {
        "contracts": {"feature_contract": {"runtime_data_requirements": {"resolved_instances": [
            {"canonical_name": "made_up", "parameters": {}, "physical_alias": "made_up",
             "provider": "features.trackers.nonexistent.NoProvider",
             "input_requirements": {"required_streams": ["completed_1s"]}},
        ]}}},
    }
    with pytest.raises(RuntimeProviderBindingMissing):
        ProviderHost.from_feature_contract(fake)


def test_duplicate_alias_fails_closed():
    fake = {
        "contracts": {"feature_contract": {"runtime_data_requirements": {"resolved_instances": [
            {"canonical_name": "arrival_velocity", "parameters": {"lookback": 20},
             "physical_alias": "dup",
             "provider": "features.trackers.generic_arrival.GenericArrivalVelocityProvider",
             "input_requirements": {"required_streams": ["completed_1s"]}},
            {"canonical_name": "arrival_acceleration", "parameters": {"short_lookback": 20},
             "physical_alias": "dup",
             "provider": "features.trackers.generic_arrival.GenericArrivalVelocityProvider",
             "input_requirements": {"required_streams": ["completed_1s"]}},
        ]}}},
    }
    with pytest.raises(ValueError, match="DUPLICATE_PHYSICAL_ALIAS"):
        ProviderHost.from_feature_contract(fake)
