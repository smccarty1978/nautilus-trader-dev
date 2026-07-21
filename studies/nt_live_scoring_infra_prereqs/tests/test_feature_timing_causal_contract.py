"""Phase 3 hand-verification: targeted causal checks confirming
`results/feature_timing_causal_spec.md`'s claims empirically, not just by
citation. Uses the actual trackers (`OHLCVDeltaTracker`, `PriceLevelTracker`)
that already back 546/695 F3 features (Phase 1 finding).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from features.trackers.ohlcv_delta import OHLCVDeltaTracker  # noqa: E402

NS = 1_000_000_000


def _feed_bars(tracker: OHLCVDeltaTracker, bars):
    for ts, o, h, l, c, v in bars:
        b = tracker.update(ts, o, h, l, c, v)
        tracker.accumulate_regime_rth(ts, h, l, v, b["bar_est_delta"])


def _make_bars(n: int, start_ts: int = 0, seed: int = 0):
    import random
    rng = random.Random(seed)
    bars = []
    px = 100.0
    for i in range(n):
        o = px
        h = o + rng.uniform(0, 1)
        l = o - rng.uniform(0, 1)
        c = rng.uniform(l, h)
        v = rng.uniform(1, 100)
        bars.append((start_ts + i * NS, o, h, l, c, v))
        px = c
    return bars


def test_prefix_invariance_calculate_at_T_unaffected_by_bars_after_T():
    """Feature value at checkpoint T is unchanged if all bars after T are
    removed -- the exact `latest_source_ts_used <= observation_ts` rule
    (feature_timing_causal_spec.md core rule)."""
    all_bars = _make_bars(50)
    prefix_bars = all_bars[:30]

    tracker_full = OHLCVDeltaTracker()
    tracker_full.reset_regime(all_bars[0][0], all_bars[0][1])
    tracker_full.reset_rth(all_bars[0][0])
    for i, bar in enumerate(all_bars):
        _feed_bars(tracker_full, [bar])
        if i == 29:  # snapshot at the 30th bar (index 29), before feeding the rest
            snapshot_at_T = tracker_full.calculate(atr=1.0)

    tracker_prefix_only = OHLCVDeltaTracker()
    tracker_prefix_only.reset_regime(prefix_bars[0][0], prefix_bars[0][1])
    tracker_prefix_only.reset_rth(prefix_bars[0][0])
    _feed_bars(tracker_prefix_only, prefix_bars)
    snapshot_prefix_only = tracker_prefix_only.calculate(atr=1.0)

    assert snapshot_at_T == snapshot_prefix_only, (
        "feature snapshot at checkpoint T must be identical whether or not "
        "bars after T ever existed -- a mismatch here is a look-ahead bug")


def test_snapshot_immutability_returned_dict_not_mutated_by_later_updates():
    """A previously emitted feature vector cannot change after future
    updates (feature_timing_causal_spec.md's snapshot-immutability
    requirement, carried over from the live-scoring brief's Phase 4)."""
    bars = _make_bars(20)
    tracker = OHLCVDeltaTracker()
    tracker.reset_regime(bars[0][0], bars[0][1])
    tracker.reset_rth(bars[0][0])
    _feed_bars(tracker, bars[:10])
    snapshot = tracker.calculate(atr=1.0)
    snapshot_copy = dict(snapshot)

    _feed_bars(tracker, bars[10:])
    tracker.calculate(atr=1.0)  # new snapshot, discarded

    assert snapshot == snapshot_copy, (
        "the dict object returned by an earlier calculate() call must not "
        "be mutated in place by subsequent update()/calculate() calls")


def test_warmup_window_unavailable_before_full_history():
    """No feature silently emits an invalid default before readiness --
    window_available_Ns must be False (not a zero-filled value) until the
    window is fully covered by completed bars (ohlcv_delta.py:210-222)."""
    bars = _make_bars(3)
    tracker = OHLCVDeltaTracker()
    tracker.reset_regime(bars[0][0], bars[0][1])
    tracker.reset_rth(bars[0][0])
    _feed_bars(tracker, bars)
    snap = tracker.calculate(atr=1.0)

    assert snap["window_available_5s"] is False, (
        "with only 3 completed bars, the 5s window cannot be fully covered "
        "and must report unavailable, not a value computed on partial data")
    assert snap["vol_sum_5s"] is None


def test_regime_reset_uses_only_information_at_or_before_boundary():
    """reset_regime() must not require or accept any information about the
    regime's eventual end/duration -- confirmed by its signature accepting
    only (ts_event, anchor_price), both knowable at the reset instant."""
    import inspect
    sig = inspect.signature(OHLCVDeltaTracker.reset_regime)
    params = list(sig.parameters.keys())
    assert params == ["self", "ts_event", "anchor_price"], (
        f"reset_regime signature changed to {params} -- re-verify it still "
        f"takes no forward-looking argument (e.g. regime duration/end_ts)")
