"""RTH-open eligibility epoch fields on FeatureHostBinding (A0 population contract).

* ``rth_open_elapsed_seconds``: seconds since the 09:30 open INSTANT (T=09:31 -> 60, T=11:00 -> 5400);
  None while the anchor is unavailable.
* ``rth_recovery_direction`` = -sign(close_T - anchor_T); 0 at zero displacement / no anchor.
"""
from datetime import datetime
from types import SimpleNamespace
import zoneinfo

from features.trackers.host_bindings import FeatureHostBinding
from research_workflow.provider_host import PriceLevelAdapter, InstanceSpec, STREAM_COMPLETED_1M

NS = 1_000_000_000
ET = zoneinfo.ZoneInfo("America/New_York")


def _ns(h, m):
    return int(datetime(2023, 10, 2, h, m, tzinfo=ET).timestamp() * NS)


def _binding():
    spec = InstanceSpec(canonical_name="distance_to_level",
                        parameters={"level": "rth_open", "normalization": "points"},
                        canonical_provider="features.trackers.generic_price_levels.GenericPriceLevelProvider",
                        physical_alias="d", required_streams=frozenset({STREAM_COMPLETED_1M}))
    adapter = PriceLevelAdapter([spec])
    b = FeatureHostBinding.__new__(FeatureHostBinding)
    b._host = SimpleNamespace(adapters=[adapter])
    return b, adapter


def _bar(adapter, close_h, close_m, o, c):
    ts = _ns(close_h, close_m)
    adapter.on_event(STREAM_COMPLETED_1M, {"ts_init": ts, "close_ts": ts, "open": o, "high": max(o, c) + 1,
                                           "low": min(o, c) - 1, "close": c})


def _epoch(h, m, price):
    return SimpleNamespace(T=_ns(h, m), price=price)


def test_fields_declared_as_epoch_fields():
    for f in ("rth_open", "rth_open_elapsed_seconds", "rth_recovery_direction"):
        assert f in FeatureHostBinding.EPOCH_FIELDS


def test_anchor_unavailable_fails_closed():
    b, _ = _binding()
    e = _epoch(9, 31, 15000.0)
    assert b.epoch_value("rth_open_elapsed_seconds", e) is None
    assert b.epoch_value("rth_recovery_direction", e) == 0


def test_elapsed_seconds_window_boundaries():
    b, a = _binding()
    _bar(a, 9, 31, 15000.0, 15010.0)          # opening bar (09:30-09:31), anchor = 15000.0
    assert b.epoch_value("rth_open_elapsed_seconds", _epoch(9, 31, 15010.0)) == 60.0
    assert b.epoch_value("rth_open_elapsed_seconds", _epoch(11, 0, 15010.0)) == 5400.0
    assert b.epoch_value("rth_open_elapsed_seconds", _epoch(11, 1, 15010.0)) == 5460.0   # > 5400: ineligible


def test_recovery_direction_is_negative_sign_of_displacement_not_regime():
    b, a = _binding()
    _bar(a, 9, 31, 15000.0, 15010.0)
    assert b.epoch_value("rth_recovery_direction", _epoch(9, 32, 15010.0)) == -1   # above anchor -> short
    assert b.epoch_value("rth_recovery_direction", _epoch(9, 33, 14990.0)) == 1    # below anchor -> long
    assert b.epoch_value("rth_recovery_direction", _epoch(9, 34, 15000.0)) == 0    # zero displacement -> excluded
