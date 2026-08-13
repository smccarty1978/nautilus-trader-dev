from datetime import datetime, timezone
from pathlib import Path

import pytest

from features.trackers.price_levels import PriceLevelTracker
from studies.full_trade_path_builder.implementation.phase_a_adapter import (
    BullishFadeAdapter,
    load_ordered_features,
)
from studies.full_trade_path_builder.implementation.phase_a_candidate import (
    CausalBullishCandidateTracker,
)
from studies.full_trade_path_builder.implementation.phase_a_core import NS, SourceProvenance
from studies.full_trade_path_builder.implementation.phase_a_strategy import is_rth_minute_bar
from studies.full_trade_path_builder.implementation.run_phase_a_collect import (
    SEALED_BOUNDARY,
    requested_load_end,
    frozen_catalog_identity,
    validate_window,
)

ROOT = Path(__file__).resolve().parents[3]


def _ns(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * NS)


def test_price_level_rth_open_or_and_last_minute():
    tracker = PriceLevelTracker()
    pre = _ns("2025-07-01T13:30:00")
    tracker.update_1m(pre, 90, 91, 89, 90, is_rth_minute_bar(pre))
    assert tracker._rth_open is None
    # First 30 contained RTH minutes close 13:31 through 14:00 UTC.
    for i in range(1, 31):
        ti = pre + i * 60 * NS
        tracker.update_1m(ti, 100 + i, 200 + i, 50 - i, 101 + i, is_rth_minute_bar(ti))
    assert tracker._rth_open == 101
    # The next completed minute finalizes the already observed first 30.
    ti = pre + 31 * 60 * NS
    tracker.update_1m(ti, 150, 999, 1, 151, is_rth_minute_bar(ti))
    assert tracker._opening_range_final == {"high": 230, "low": 20}
    last = _ns("2025-07-01T20:00:00")
    tracker.update_1m(last, 300, 305, 295, 301, is_rth_minute_bar(last))
    assert tracker._today_bars[-1][0] == last
    assert is_rth_minute_bar(last)
    rollover = _ns("2025-07-01T22:00:00")
    tracker.update_1m(rollover, 400, 401, 399, 400, is_rth_minute_bar(rollover))
    assert tracker.prior_day_ohlc == {"open": 90, "high": 999, "low": 1, "close": 301}


def test_prefix_invariance_and_flip_tie():
    prefix_rows, full_rows = [], []
    a = CausalBullishCandidateTracker(prefix_rows.append, lambda _: None, lambda _: True)
    b = CausalBullishCandidateTracker(full_rows.append, lambda _: None, lambda _: True)
    for tracker in (a, b):
        tracker.on_regime_flip(0, 1, 100, 1)
    for sec in range(1, 126):
        args = ((sec - 1) * NS, sec * NS, 102, 100, 101)
        a.on_completed_1s(*args)
        b.on_completed_1s(*args)
    frozen = [dict(x) for x in prefix_rows]
    for sec in range(126, 181):
        b.on_completed_1s((sec - 1) * NS, sec * NS, 103, 100, 102)
    assert prefix_rows == frozen
    assert full_rows[:len(frozen)] == frozen
    # At T, checkpoint dispatch precedes a minute-confirmed flip at T.
    assert full_rows[-1]["checkpoint_decision_ns"] == 180 * NS
    b.on_regime_flip(180 * NS, -1, 102, 1)


def test_adapter_order_metadata_and_atr_routing():
    names = load_ordered_features(ROOT)
    assert len(names) == 25 and len(set(names)) == 25
    adapter = BullishFadeAdapter(names)

    class FakeEngine:
        def ordered_vector(self, observation_ts, reference_price, atr):
            return [atr] * 25, {name: False for name in names}, False

    adapter.engine = FakeEngine()
    prov = SourceProvenance(9 * NS, 10 * NS, 0, 0)
    v1, _, _ = adapter.snapshot(10 * NS, 100, 2.0, prov)
    v2, _, _ = adapter.snapshot(10 * NS, 100, 4.0, prov)
    assert v1 == [2.0] * 25 and v2 == [4.0] * 25


def test_sealed_boundary_window_math_without_2026_access():
    start = datetime(2025, 12, 1, tzinfo=timezone.utc)
    validate_window(start, SEALED_BOUNDARY)
    assert requested_load_end(SEALED_BOUNDARY) == SEALED_BOUNDARY
    with pytest.raises(RuntimeError):
        validate_window(SEALED_BOUNDARY, datetime(2026, 2, 1, tzinfo=timezone.utc))


def test_catalog_identity_never_opens_monolithic_data(monkeypatch):
    original = Path.open
    opened = []

    def guarded(self, *args, **kwargs):
        opened.append(self)
        if self.suffix == ".parquet":
            raise AssertionError(f"sealed monolithic data file opened: {self}")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    identity = frozen_catalog_identity()
    assert identity["identity_mode"].startswith("trusted_precomputed")
    assert opened and all(path.suffix != ".parquet" for path in opened)
