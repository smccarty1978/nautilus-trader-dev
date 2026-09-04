"""Window parameterization of the estimated volume/delta feature family.

Three defects made this family undeclarable in Platform V2 even though every value was
already computed by the tracker:

1. ``generate_physical_alias`` dropped the window: ``vol_sum`` at 5s and at 300s both
   rendered as the bare ``vol_sum``, so declaring more than one window failed with
   ``INVALID_PARAMETERIZATION: duplicate physical aliases``. 6 of the family's 205
   committed legacy aliases rendered exactly; the rest could not be spelled at all.
2. ``OHLCVDeltaAdapter`` emitted only the two direction-normalized features, so every
   other name in the family compiled to ``MISSING_CAPABILITY: no runtime adapter renders
   'vol_sum'`` despite being a registered, verified capability.
3. The two-window comparisons were hardcoded to (30s,300s) and (60s,900s) for volume and
   (15,60)/(30,120)/(60,300) for delta, so a study could not ask for 5s-vs-300s at all.

The tests below lock the fix at each layer, and -- importantly -- lock the DEFAULT paths
byte-for-byte, since this family's historical output is the parity reference for sealed
studies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

import numpy as np
import pytest

from features.registry import (
    FeatureInstance,
    _canonical_bundle,
    generate_physical_alias,
)
from features.trackers.generic_ohlcv_delta import GenericOHLCVDeltaProvider
from features.trackers.ohlcv_delta import (
    DEFAULT_WINDOW_PAIRS,
    OHLCVDeltaTracker,
    WINDOWS_S,
)
from research_workflow.provider_host import (
    OHLCVDeltaAdapter,
    ProviderHost,
    STREAM_COMPLETED_1S,
)

NS = 1_000_000_000
ATR = 10.0
DELTA_PROVIDER = "features.trackers.generic_ohlcv_delta.GenericOHLCVDeltaProvider"


# --------------------------------------------------------------------------- #
# synthetic tape
# --------------------------------------------------------------------------- #
def _bars(n: int = 800, seed: int = 11):
    """Completed 1s bars whose volume RAMPS, so short and long windows genuinely differ
    in participation (a constant-volume tape would let a window bug pass silently)."""
    rng = np.random.default_rng(seed)
    px = 20000.0
    for i in range(1, n + 1):
        px += rng.normal(0.0, 0.6)
        o, c = px - 0.25, px
        yield dict(ts_init=i * NS, open=o, high=max(o, c) + 0.4, low=min(o, c) - 0.4,
                   close=c, volume=50.0 + 0.35 * i + (i % 5))


def _fed_provider(windows: Sequence[int], pairs=None, n: int = 800) -> GenericOHLCVDeltaProvider:
    p = GenericOHLCVDeltaProvider(windows_seconds=list(windows), window_pairs=pairs)
    for bar in _bars(n):
        p.update_completed_bar(close_ts=bar["ts_init"], open_px=bar["open"], high=bar["high"],
                               low=bar["low"], close=bar["close"], volume=bar["volume"])
    return p


# --------------------------------------------------------------------------- #
# 1. alias rendering
# --------------------------------------------------------------------------- #
def _family_aliases() -> List[tuple]:
    bundle = _canonical_bundle("active")
    families = {d["canonical_name"]: tuple(d.get("family") or ())
                for d in bundle["registry"]["definitions"]}
    return [(alias, v["canonical_feature"], v.get("parameters") or {})
            for alias, v in sorted(bundle["aliases"]["aliases"].items())
            if families.get(v["canonical_feature"]) == ("ohlcv_est_delta",)]


def test_every_committed_ohlcv_alias_renders_exactly():
    """The renderer is not inventing spellings: it reproduces all 205 committed legacy
    aliases of the family byte for byte, which is what makes extending it to new windows
    safe. Was 6/205."""
    rows = _family_aliases()
    assert len(rows) == 205, f"family alias count moved: {len(rows)}"
    bad = [(alias, generate_physical_alias(FeatureInstance(cn, params)))
           for alias, cn, params in rows
           if generate_physical_alias(FeatureInstance(cn, params)) != alias]
    assert not bad, f"{len(bad)} aliases render differently, e.g. {bad[:5]}"


@pytest.mark.parametrize("window", ["5s", "30s", "60s", "300s"])
def test_window_is_part_of_the_physical_identity(window):
    alias = generate_physical_alias(
        FeatureInstance("vol_sum", {"context": "rolling", "timeframe": window}))
    assert alias == f"vol_sum_{window}"


def test_four_windows_yield_four_distinct_aliases():
    """The exact shape that previously raised DUPLICATE_PHYSICAL_ALIAS."""
    aliases = {generate_physical_alias(
        FeatureInstance("vol_sum", {"context": "rolling", "timeframe": w}))
        for w in ("5s", "30s", "60s", "300s")}
    assert len(aliases) == 4


def test_regime_and_rth_contexts_keep_their_spelling():
    assert generate_physical_alias(
        FeatureInstance("vol_sum", {"context": "regime"})) == "regime_vol_sum"
    assert generate_physical_alias(
        FeatureInstance("abs_delta_cum", {"context": "RTH"})) == "rth_abs_delta_cum"


def test_pullback_spelling_of_range_atr_is_untouched():
    """``range_atr`` is in two families; the ohlcv rule is gated on ``context`` so the
    pullback ``{scope: trailing}`` spelling cannot be captured by it."""
    assert generate_physical_alias(
        FeatureInstance("range_atr", {"scope": "trailing", "timeframe": "30s"})) == "range_atr"
    assert generate_physical_alias(
        FeatureInstance("range_atr", {"context": "rolling", "timeframe": "30s"})) == "range_atr_30s"


# --------------------------------------------------------------------------- #
# 2. tracker: default parity + parameterized pairs
# --------------------------------------------------------------------------- #
def test_default_windows_and_pairs_are_unchanged():
    t = OHLCVDeltaTracker()
    assert t.windows_seconds == tuple(sorted(WINDOWS_S))
    assert t.window_pairs == {k: tuple(v) for k, v in DEFAULT_WINDOW_PAIRS.items()}


def test_default_pair_values_are_the_historical_formulas():
    """Every historical pair key is still emitted and still equals its original formula."""
    snap = _fed_provider(WINDOWS_S, n=1900).snapshot(atr=ATR)

    def w(sec, key):
        return snap[f"{key}_{sec}s"]

    assert snap["est_delta_sum_15s_minus_60s_scaled"] == w(15, "est_delta_sum") - w(60, "est_delta_sum")
    assert snap["est_delta_sum_30s_minus_120s_scaled"] == w(30, "est_delta_sum") - w(120, "est_delta_sum")
    assert snap["est_delta_sum_60s_minus_300s_scaled"] == w(60, "est_delta_sum") - w(300, "est_delta_sum")
    assert snap["est_delta_ratio_15s_minus_60s"] == w(15, "est_delta_ratio") - w(60, "est_delta_ratio")
    assert snap["vol_sum_30s_vs_300s_ratio"] == w(30, "vol_sum") / max(w(300, "vol_sum"), 1e-9)
    assert snap["vol_sum_60s_vs_900s_ratio"] == w(60, "vol_sum") / max(w(900, "vol_sum"), 1e-9)


def test_requested_pairs_are_computed():
    """5s-vs-300s and 60s-vs-300s did not exist before; 30s-vs-300s did."""
    snap = _fed_provider([5, 30, 60, 300],
                         pairs={"vol_sum_vs_ratio": [(5, 300), (30, 300), (60, 300)]}).snapshot(atr=ATR)
    for a in (5, 30, 60):
        key = f"vol_sum_{a}s_vs_300s_ratio"
        assert key in snap and snap[key] is not None
        assert snap[key] == snap[f"vol_sum_{a}s"] / max(snap["vol_sum_300s"], 1e-9)
    # a ramping tape means shorter windows carry a smaller share of the 300s activity
    assert snap["vol_sum_5s_vs_300s_ratio"] < snap["vol_sum_30s_vs_300s_ratio"] < snap["vol_sum_60s_vs_300s_ratio"]


def test_explicitly_requested_pair_without_its_windows_fails_closed():
    with pytest.raises(ValueError, match="needs windows"):
        OHLCVDeltaTracker(windows_seconds=[5, 300],
                          window_pairs={"vol_sum_vs_ratio": [(30, 300)]})


def test_unknown_pair_kind_fails_closed():
    with pytest.raises(ValueError, match="unknown window pair kind"):
        OHLCVDeltaTracker(window_pairs={"not_a_kind": [(30, 300)]})


# --------------------------------------------------------------------------- #
# 3. acceleration (new canonical feature)
# --------------------------------------------------------------------------- #
def test_acceleration_is_this_window_minus_the_preceding_equal_window():
    p = _fed_provider([30, 60])
    near = p.metric(name="est_delta_sum", window="30s", atr=ATR)
    far = p.metric(name="est_delta_sum", window="60s", atr=ATR)
    preceding = far - near                      # [t-60, t-30], contiguous and disjoint
    got = p.trend_normalized_est_delta_acceleration(
        short_window="30s", prevailing_direction=1, atr=ATR)
    assert got == pytest.approx(near - preceding)
    assert got == pytest.approx(2.0 * near - far)


def test_acceleration_is_direction_normalized():
    p = _fed_provider([30, 60])
    up = p.trend_normalized_est_delta_acceleration(
        short_window="30s", prevailing_direction=1, atr=ATR)
    down = p.trend_normalized_est_delta_acceleration(
        short_window="30s", prevailing_direction=-1, atr=ATR)
    assert down == -up


def test_acceleration_without_the_doubled_window_fails_closed():
    p = _fed_provider([30, 60])
    with pytest.raises(ValueError, match="needs windows"):
        p.trend_normalized_est_delta_acceleration(
            short_window="45s", prevailing_direction=1, atr=ATR)


def test_acceleration_rejects_an_absent_prevailing_direction():
    p = _fed_provider([30, 60])
    with pytest.raises(ValueError, match="prevailing_direction"):
        p.trend_normalized_est_delta_acceleration(
            short_window="30s", prevailing_direction=0, atr=ATR)


def test_acceleration_is_not_the_misnamed_minus_scaled_feature():
    """est_delta_sum_minus_scaled(30,60) is D(30)-D(60) = MINUS the preceding window's
    delta. The acceleration is D(30) - (D(60)-D(30)). They are different numbers, and
    conflating them is the mistake this feature exists to remove."""
    p = _fed_provider([30, 60], pairs={"est_delta_sum_minus_scaled": [(30, 60)]})
    snap = p.snapshot(atr=ATR)
    minus_scaled = snap["est_delta_sum_30s_minus_60s_scaled"]
    accel = p.trend_normalized_est_delta_acceleration(
        short_window="30s", prevailing_direction=1, atr=ATR)
    near = snap["est_delta_sum_30s"]
    assert minus_scaled == pytest.approx(-(snap["est_delta_sum_60s"] - near))
    assert accel == pytest.approx(near + minus_scaled)
    assert accel != pytest.approx(minus_scaled)


# --------------------------------------------------------------------------- #
# 4. adapter binding
# --------------------------------------------------------------------------- #
def _contract(instances: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {"contracts": {"feature_contract": {
        "runtime_data_requirements": {"resolved_instances": [
            {**i, "provider": DELTA_PROVIDER,
             "input_requirements": {"required_streams": [STREAM_COMPLETED_1S]}}
            for i in instances]}}}}


def _instance(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {"canonical_name": name, "parameters": params,
            "physical_alias": generate_physical_alias(FeatureInstance(name, params))}


ARM_B = (
    [_instance("vol_sum", {"context": "rolling", "timeframe": w}) for w in ("5s", "30s", "60s", "300s")]
    + [_instance("vol_sum_vs_ratio", {"context": "rolling", "timeframe": a, "timeframe_2": "300s"})
       for a in ("5s", "30s", "60s")]
)


def _host_snapshot(instances, direction: int = 1) -> Dict[str, Any]:
    host = ProviderHost.from_feature_contract(_contract(instances))
    assert not host._unbound, f"unbound: {host._unbound}"
    for bar in _bars(800):
        host.dispatch(STREAM_COMPLETED_1S, bar)
    return dict(host.snapshot(decision_ts=800 * NS, price=20000.0, atr=ATR,
                              episode_state={"prevailing_direction": direction}))


def test_volume_participation_surface_binds_and_emits():
    snap = _host_snapshot(ARM_B)
    expected = {i["physical_alias"] for i in ARM_B}
    assert expected <= set(snap)
    assert all(snap[a] is not None for a in expected), \
        f"null: {sorted(a for a in expected if snap[a] is None)}"


def test_adapter_routes_each_window_to_its_own_value():
    snap = _host_snapshot(ARM_B)
    sums = [snap[f"vol_sum_{w}"] for w in ("5s", "30s", "60s", "300s")]
    assert len(set(sums)) == 4, f"windows collapsed: {sums}"
    assert sums == sorted(sums), "a longer window must accumulate at least as much volume"


def test_direction_normalized_and_passthrough_instances_coexist():
    instances = ARM_B + [
        _instance("trend_normalized_est_delta_sum",
                  {"window": w, "update_every": "1s", "direction_reference": "prevailing_1m"})
        for w in ("5s", "30s", "60s", "300s")]
    snap = _host_snapshot(instances)
    assert snap["vol_sum_30s"] is not None
    assert snap["trend_normalized_est_delta_sum_30s"] is not None


def test_absent_direction_nulls_only_the_direction_normalized_instances():
    """An unsigned participation level is still meaningful with no prevailing regime;
    a direction-normalized one is not. Previously the adapter nulled the whole group."""
    instances = ARM_B + [
        _instance("trend_normalized_est_delta_sum",
                  {"window": "30s", "update_every": "1s", "direction_reference": "prevailing_1m"})]
    snap = _host_snapshot(instances, direction=0)
    assert snap["trend_normalized_est_delta_sum_30s"] is None
    assert snap["vol_sum_30s"] is not None


def test_regime_and_rth_contexts_stay_unbound_rather_than_wrong():
    """Their values depend on reset_regime / reset_rth lifecycle calls the adapter never
    receives, so emitting them would be a plausible number over the wrong accumulation
    window. They must fail closed."""
    from research_workflow.provider_host import InstanceSpec
    for context in ("regime", "RTH"):
        spec = InstanceSpec(canonical_name="vol_sum", parameters={"context": context},
                            physical_alias="x", canonical_provider=DELTA_PROVIDER,
                            required_streams=(STREAM_COMPLETED_1S,))
        assert not OHLCVDeltaAdapter.can_emit(spec), f"{context} must not bind"


def test_declared_windowed_names_match_the_tracker_vocabulary():
    """OHLCVDeltaAdapter._WINDOWED is a hand-written declaration (can_emit is a
    classmethod and cannot probe a provider). Assert it against what the tracker
    actually emits per window, so a tracker key added or removed cannot drift away
    from the adapter's declaration unnoticed."""
    snap = _fed_provider([300], n=400).snapshot(atr=ATR)
    emitted = {k[: -len("_300s")] for k in snap if k.endswith("_300s")}
    # vol_mean / vol_max spell the bar granularity into the key (vol_mean_1s_300s).
    emitted = {n[: -len("_1s")] if n.endswith("_1s") else n for n in emitted}
    declared = set(OHLCVDeltaAdapter._WINDOWED)
    assert emitted == declared, (
        f"tracker-only: {sorted(emitted - declared)}; declared-only: {sorted(declared - emitted)}")
