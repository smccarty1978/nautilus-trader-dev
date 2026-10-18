"""Tests for PriceLevelAdapter in research_workflow/provider_host.py."""
import pytest
from datetime import datetime
import zoneinfo

from features.trackers.generic_price_levels import GenericPriceLevelProvider
from research_workflow.provider_host import (
    PriceLevelAdapter,
    InstanceSpec,
    STREAM_COMPLETED_1M,
)


def test_price_level_adapter_can_emit():
    spec = InstanceSpec(
        canonical_name="distance_to_level",
        parameters={"level": "rth_open", "normalization": "points"},
        canonical_provider="features.trackers.generic_price_levels.GenericPriceLevelProvider",
        physical_alias="dist_rth_open",
        required_streams=frozenset({STREAM_COMPLETED_1M}),
    )
    assert PriceLevelAdapter.can_emit(spec) is True


def test_price_level_adapter_snapshot():
    spec = InstanceSpec(
        canonical_name="distance_to_level",
        parameters={"level": "rth_open", "normalization": "points"},
        canonical_provider="features.trackers.generic_price_levels.GenericPriceLevelProvider",
        physical_alias="dist_rth_open",
        required_streams=frozenset({STREAM_COMPLETED_1M}),
    )
    adapter = PriceLevelAdapter([spec])
    assert adapter.required_streams() == frozenset({STREAM_COMPLETED_1M})

    # 2023-10-02 09:30:00 ET is 13:30:00 UTC
    tz = zoneinfo.ZoneInfo("America/New_York")
    dt_open = datetime(2023, 10, 2, 9, 30, tzinfo=tz)
    ts_event = int(dt_open.timestamp() * 1_000_000_000)
    ts_init = ts_event + 60_000_000_000  # 09:31:00 ET

    payload = {
        "ts_event": ts_event,
        "ts_init": ts_init,
        "open": 15000.0,
        "high": 15020.0,
        "low": 14995.0,
        "close": 15010.0,
    }

    adapter.on_event(STREAM_COMPLETED_1M, payload)

    # Snapshot at 09:31:00 ET (ts_init)
    snap = adapter.snapshot(
        decision_ts=ts_init,
        price=15010.0,
        atr=10.0,
        episode_state={"prevailing_direction": 1},
    )

    assert "dist_rth_open" in snap
    assert snap["dist_rth_open"] == 10.0  # 15010.0 - 15000.0
