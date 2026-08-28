"""Stage-1 audit regression tests -- the F-A / F-D / F-3 / F-5 / F-4 repairs.

Every test here previously documented a confirmed Stage-1 defect (as strict-xfail) and
is now a passing regression that locks the fix.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from research_workflow.provider_host import (
    ArrivalVelocityAdapter,
    CompletedRegimeGeometryAdapter,
    ContextAdapter,
    InstanceSpec,
    NonMonotonicRuntimeEvent,
    ProviderHost,
    SnapshotBeforeLatestRuntimeEvent,
    StructuralGeometryAdapter,
)
from research_workflow.tests.test_provider_host import _build_tape, _price

NS = 1_000_000_000
REPO = Path(__file__).resolve().parents[2]
STUDY = REPO / "studies" / "deep_pullback_5s_reacceleration_model"


def _compiled() -> dict:
    return json.loads((STUDY / "compiled_study.json").read_text(encoding="utf-8"))


def _dispatch_to(host: ProviderHost, upto_s: int) -> None:
    for ts, event_type, payload in _build_tape():
        if ts > upto_s * NS:
            break
        host.dispatch(event_type, payload)


# =========================================================================== #
# F-A -- Family-A ema_slope reproduces the frozen Model C parent runtime exactly
# =========================================================================== #
def _parent_compact_ema_slope(midpoints, atr):
    """research_workflow/generic_collector.py :: _get_context_features, verbatim."""
    if len(midpoints) < 6:
        return 0.0
    return (midpoints[-1] - midpoints[-6]) / (5 * atr)


def test_f_a_ema_slope_matches_frozen_parent_runtime_exactly():
    spec = [InstanceSpec("ema_slope", {"ema_role": "short", "lookback": 20}, "ema_slope",
                         "features.trackers.generic_context.GenericContextProvider", ("completed_1m",))]
    adapter = ContextAdapter(spec)
    atr = 10.0
    # Feed 1m highs/lows; check parity at every step including the 0.0 warmup band.
    hs = [20000.0 + 3.1 * i + (i % 4) for i in range(40)]
    ls = [h - 8.0 - (i % 3) for i, h in enumerate(hs)]
    for i, (h, l) in enumerate(zip(hs, ls)):
        adapter.on_event("completed_1m", {"high": h, "low": l})
        got = adapter.snapshot(decision_ts=(i + 1) * 60 * NS, price=h, atr=atr, episode_state={})["ema_slope"]
        expected = _parent_compact_ema_slope(list(adapter._midpoints), atr)
        assert got == pytest.approx(expected, abs=1e-12), f"step {i}"
    # warmup band really is 0.0 (parent behavior), not null
    a2 = ContextAdapter(spec)
    for _ in range(5):
        a2.on_event("completed_1m", {"high": 100.0, "low": 99.0})
    assert a2.snapshot(decision_ts=1000 * NS, price=100.0, atr=atr, episode_state={})["ema_slope"] == 0.0
    assert ContextAdapter.FROZEN_FAMILY_A_EMA_SLOPE_STEPS == 5


# =========================================================================== #
# F-D -- regime_alignment polarity is canonical (lives in the provider)
# =========================================================================== #
def _regime_provider():
    from features.trackers.generic_regime_geometry import GenericCompletedRegimeGeometryProvider
    return GenericCompletedRegimeGeometryProvider()


def _bar(p, *, tf_close_ts, direction):
    return dict(timeframe=None, close_ts=tf_close_ts, direction=direction,
               open_=p, high=p + 1, low=p - 1, close=p, atr=10.0)


def test_f_d_regime_alignment_polarity_is_defined_by_the_canonical_provider():
    from features.trackers.generic_regime_geometry import GenericCompletedRegimeGeometryProvider
    assert hasattr(GenericCompletedRegimeGeometryProvider, "alignment")

    def build(d1, d5):
        prov = _regime_provider()
        # two completed 1m bars (so _current["1m"] exists and is completed by ts)
        prov.on_completed_bar(timeframe="1m", close_ts=60 * NS, direction=d1, open_=100, high=101, low=99, close=100, atr=10.0)
        prov.on_completed_bar(timeframe="1m", close_ts=120 * NS, direction=d1, open_=100, high=101, low=99, close=100, atr=10.0)
        prov.on_completed_bar(timeframe="5m", close_ts=300 * NS, direction=d5, open_=100, high=101, low=99, close=100, atr=10.0)
        return prov

    assert build(1, 1).alignment(source_timeframe="1m", reference_timeframe="5m", checkpoint_ns=400 * NS)["regime_alignment"] == 1
    assert build(-1, -1).alignment(source_timeframe="1m", reference_timeframe="5m", checkpoint_ns=400 * NS)["regime_alignment"] == 1
    assert build(1, -1).alignment(source_timeframe="1m", reference_timeframe="5m", checkpoint_ns=400 * NS)["regime_alignment"] == -1
    assert build(-1, 1).alignment(source_timeframe="1m", reference_timeframe="5m", checkpoint_ns=400 * NS)["regime_alignment"] == -1


def test_f_d_regime_alignment_null_when_a_direction_is_unavailable():
    prov = _regime_provider()
    # only a 1m regime, no 5m
    prov.on_completed_bar(timeframe="1m", close_ts=60 * NS, direction=1, open_=100, high=101, low=99, close=100, atr=10.0)
    out = prov.alignment(source_timeframe="1m", reference_timeframe="5m", checkpoint_ns=100 * NS)
    assert out["available"] is False and out["regime_alignment"] is None


def test_f_d_regime_alignment_ignores_a_5m_bar_not_yet_completed_by_checkpoint():
    prov = _regime_provider()
    prov.on_completed_bar(timeframe="1m", close_ts=60 * NS, direction=1, open_=100, high=101, low=99, close=100, atr=10.0)
    prov.on_completed_bar(timeframe="5m", close_ts=300 * NS, direction=1, open_=100, high=101, low=99, close=100, atr=10.0)
    # checkpoint BEFORE the 5m close -> not causally available -> null, unchanged by it
    out = prov.alignment(source_timeframe="1m", reference_timeframe="5m", checkpoint_ns=200 * NS)
    assert out["regime_alignment"] is None


def test_f_d_adapter_forwards_the_canonical_alignment_not_its_own_transform():
    src = inspect.getsource(CompletedRegimeGeometryAdapter.snapshot)
    assert "self._provider.alignment(" in src
    assert "d5 == d1" not in src and "1 if d5" not in src  # no adapter-local polarity


# =========================================================================== #
# F-3 -- the provider change is reflected in the regenerated candidate authority
# =========================================================================== #
def test_f_3_promotion_facts_provider_hash_matches_the_current_file():
    import hashlib
    provider = REPO / "features" / "trackers" / "generic_regime_geometry.py"
    current = hashlib.sha256(provider.read_bytes()).hexdigest()
    facts = json.loads((REPO / "features" / "authority" / "candidate" / "promotion_facts.json").read_text())
    for row in facts["definitions"]:
        if row["provider"].endswith("GenericCompletedRegimeGeometryProvider"):
            assert row["provider_sha256"] == current, row["canonical_name"]


def test_f_3_regime_alignment_and_direction_resolve_verified():
    from features.registry import resolve_feature_instances, FeatureInstance
    insts = (
        FeatureInstance("regime_alignment", {"source_timeframe": "1m", "reference_timeframe": "5m",
                                             "context": "current", "bar_state": "completed"}),
        FeatureInstance("regime_direction", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    )
    resolved = resolve_feature_instances("canonical_verified_definition_universe", insts)
    assert {r["physical_alias"] for r in resolved} == {"current_5m_regime_direction", "regime_alignment"}


# =========================================================================== #
# F-5 -- ProviderHost enforces causal event ordering, fails closed on future leak
# =========================================================================== #
def _episode_state():
    return dict(armed=True, prevailing_direction=1, prevailing_extreme_ts=1400 * NS,
                prior_deep_pullback_count=2, regime_expansion_atr_per_min=0.35)


def test_f_5_future_event_after_a_historical_snapshot_request_fails_closed():
    host = ProviderHost.from_feature_contract(_compiled())
    _dispatch_to(host, 1200)
    clean = host.snapshot(decision_ts=1200 * NS, price=_price(1200), atr=10.0, episode_state=_episode_state())
    assert clean["arrival_velocity"] is not None

    host2 = ProviderHost.from_feature_contract(_compiled())
    _dispatch_to(host2, 1500)  # future events dispatched
    with pytest.raises(SnapshotBeforeLatestRuntimeEvent):
        host2.snapshot(decision_ts=1200 * NS, price=_price(1200), atr=10.0, episode_state=_episode_state())


def test_f_5_non_monotonic_stream_event_is_rejected():
    host = ProviderHost.from_feature_contract(_compiled())
    host.dispatch("completed_1s", {"ts_init": 100 * NS, "open": 1, "high": 2, "low": 0, "close": 1,
                                   "volume": 10, "arm_atr": 10.0})
    with pytest.raises(NonMonotonicRuntimeEvent):
        host.dispatch("completed_1s", {"ts_init": 100 * NS, "open": 1, "high": 2, "low": 0, "close": 1,
                                       "volume": 10, "arm_atr": 10.0})
    with pytest.raises(NonMonotonicRuntimeEvent):
        host.dispatch("completed_1s", {"ts_init": 50 * NS, "open": 1, "high": 2, "low": 0, "close": 1,
                                       "volume": 10, "arm_atr": 10.0})


def test_f_5_interleaved_streams_at_different_cadence_are_allowed():
    host = ProviderHost.from_feature_contract(_compiled())
    host.dispatch("completed_1s", {"ts_init": 5 * NS, "open": 1, "high": 2, "low": 0, "close": 1, "volume": 10, "arm_atr": 10.0})
    host.dispatch("completed_5s", {"close_ts": 5 * NS, "direction": 1, "open": 1, "high": 2, "low": 0, "close": 1, "atr": 10.0})
    host.dispatch("completed_1s", {"ts_init": 6 * NS, "open": 1, "high": 2, "low": 0, "close": 1, "volume": 10, "arm_atr": 10.0})
    host.dispatch("completed_5s", {"close_ts": 10 * NS, "direction": 1, "open": 1, "high": 2, "low": 0, "close": 1, "atr": 10.0})
    # no exception: 1s and 5s streams each stayed monotonic though they interleaved


def test_f_5_snapshot_at_exactly_the_last_event_ts_is_allowed():
    host = ProviderHost.from_feature_contract(_compiled())
    _dispatch_to(host, 1500)
    row = host.snapshot(decision_ts=1500 * NS, price=_price(1500), atr=10.0, episode_state=_episode_state())
    assert len(row) == 34


# =========================================================================== #
# F-4 -- static realizability is non-tautological
# =========================================================================== #
def test_f_4_unsupported_parameterization_is_reported_unbound():
    fake = {
        "contracts": {"feature_contract": {"runtime_data_requirements": {"resolved_instances": [
            {"canonical_name": "regime_efficiency",
             "parameters": {"timeframe": "15m", "context": "current", "bar_state": "completed"},
             "physical_alias": "current_15m_regime_efficiency",
             "provider": "features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider",
             "input_requirements": {"required_streams": ["completed_15m"]}},
        ]}}},
    }
    host = ProviderHost.from_feature_contract(fake)
    verdict = host.verify_bindings()
    assert verdict["unbound"] == ["current_15m_regime_efficiency"]
    assert verdict["passed"] is False
    meta = verdict["metadata"][0]
    assert meta["bound"] is False and meta["snapshot_output_binding"] is None


def test_f_4_deep_pullback_still_binds_all_34_with_named_snapshot_paths():
    host = ProviderHost.from_feature_contract(_compiled())
    verdict = host.verify_bindings()
    assert verdict == pytest.approx(verdict)  # smoke
    assert verdict["required"] == 34 and verdict["bound"] == 34 and verdict["unbound"] == []
    for m in verdict["metadata"]:
        assert m["snapshot_output_binding"] and m["snapshot_output_binding"].endswith(m["physical_alias"])
        assert m["bound"] is True


def test_f_4_bound_is_not_merely_alias_in_requested_list():
    src = inspect.getsource(ProviderHost.binding_metadata)
    assert "can_emit" in src
    assert "in adapter.physical_aliases" not in src
