"""Parity of the single authoritative regime tracker against the accepted references.

1. In-memory exact parity against the legacy engines on synthetic bars (regime sequence
   identical, ATR/EMA identical to 1e-12).
2. Real-data parity against the frozen regime-complete canonical store for 2021-01
   (flip timestamps + directions), skipped when the catalog or store is absent.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from features.trackers.regime_dual_ema import DualEmaRegimeTracker

REPO = Path(__file__).resolve().parents[2]
MAIN_REPO = Path(r"C:/Users/Scott McCarty/Projects/Nautilus Trader")
STORE = MAIN_REPO / "studies/regime_complete_canonical_store/_work/monthly/year=2021/month=01/canonical_regimes.parquet"


def _bars(n: int = 5000, seed: int = 7):
    rng = np.random.default_rng(seed)
    close = 15000 + np.cumsum(rng.normal(scale=3.0, size=n))
    high = close + np.abs(rng.normal(scale=2.0, size=n))
    low = close - np.abs(rng.normal(scale=2.0, size=n))
    return high, low, close


class _LegacyGenericRegimeEngine:
    """Verbatim copy of the pre-consolidation research_workflow.generic_collector.RegimeEngine."""
    ALPHA3 = 0.5; ALPHA9 = 0.2; ATR_P = 14
    def __init__(self):
        self.ema3_h = self.ema9_h = self.ema3_l = self.ema9_l = None; self.prev_c = None; self.atr_warmup = []; self.atr = None; self.regime = 0
    def update(self, h, l, c):
        if self.ema3_h is None:
            self.ema3_h = self.ema9_h = h; self.ema3_l = self.ema9_l = l
        else:
            self.ema3_h = self.ALPHA3 * h + (1 - self.ALPHA3) * self.ema3_h; self.ema9_h = self.ALPHA9 * h + (1 - self.ALPHA9) * self.ema9_h
            self.ema3_l = self.ALPHA3 * l + (1 - self.ALPHA3) * self.ema3_l; self.ema9_l = self.ALPHA9 * l + (1 - self.ALPHA9) * self.ema9_l
        tr = h - l if self.prev_c is None else max(h - l, abs(h - self.prev_c), abs(l - self.prev_c)); self.prev_c = c
        if self.atr is None:
            self.atr_warmup.append(tr)
            if len(self.atr_warmup) == self.ATR_P: self.atr = sum(self.atr_warmup) / self.ATR_P; self.atr_warmup = []
        else:
            self.atr = (self.atr * (self.ATR_P - 1) + tr) / self.ATR_P
        new_regime = self.regime
        if c > (self.ema3_h or 0) and c > (self.ema9_h or 0): new_regime = 1
        elif c < (self.ema3_l or 0) and c < (self.ema9_l or 0): new_regime = -1
        if new_regime != 0 and new_regime != self.regime: self.regime = new_regime
        return self.regime


def test_exact_parity_with_legacy_generic_collector_engine():
    h, l, c = _bars()
    ref, new = _LegacyGenericRegimeEngine(), DualEmaRegimeTracker(timeframe="1m")
    flips = 0
    for i in range(len(c)):
        r_ref = ref.update(float(h[i]), float(l[i]), float(c[i])); r_new = new.update(float(h[i]), float(l[i]), float(c[i]))
        assert r_ref == r_new, i
        assert (ref.atr is None) == (new.atr is None) and (ref.atr is None or abs(ref.atr - new.atr) <= 1e-12), i
        assert abs(ref.ema3_h - new.ema3_h) <= 1e-9 and abs(ref.ema9_l - new.ema9_l) <= 1e-9
        flips += int(i and r_new != prev) if i else 0
        prev = r_new
    assert flips > 50  # the fixture actually exercises flips


def test_exact_parity_with_collector_v2_regime_state_engine():
    from collectors.collector_v2.aggregator import _OpenBucket
    from collectors.collector_v2.registry import CompletedBarRegistry
    from collectors.collector_v2.regime_engine import RegimeStateEngine
    h, l, c = _bars(seed=11)
    registry = CompletedBarRegistry(["1m"]) if _accepts_list() else CompletedBarRegistry()
    ref = RegimeStateEngine("1m", registry); new = DualEmaRegimeTracker(timeframe="1m")
    for i in range(len(c)):
        bucket = _OpenBucket(bucket_id=i, open_ts=i * 60_000_000_000, close_ts=(i + 1) * 60_000_000_000, open=float(c[i]), high=float(h[i]), low=float(l[i]), close=float(c[i]), volume=1.0, expected_count=60, observed_event_ts=set())
        ref.on_bar_closed(bucket); upd = new.observe(float(h[i]), float(l[i]), float(c[i]))
        state = registry.latest("1m") if hasattr(registry, "latest") else registry.get("1m")
        assert state.regime == upd.regime, i
        assert (math.isnan(state.atr) and upd.atr is None) or abs(state.atr - upd.atr) <= 1e-12, i
        assert state.bars_in_regime == upd.bars_in_regime, i


def _accepts_list() -> bool:
    import inspect
    from collectors.collector_v2.registry import CompletedBarRegistry
    params = inspect.signature(CompletedBarRegistry.__init__).parameters
    return len(params) > 1


def test_identity_and_parameters_are_explicit():
    t = DualEmaRegimeTracker(timeframe="5m", instrument="ES", short_period=3, long_period=9, atr_period=14)
    ident = t.identity()
    assert ident["timeframe"] == "5m" and ident["instrument"] == "ES" and ident["capability"] == "tracker.regime.dual_ema"
    assert DualEmaRegimeTracker(timeframe="1m").identity() != ident


@pytest.mark.skipif(not STORE.is_file() or not (MAIN_REPO / "data/catalog/NQ_v0_2020_2026/data").is_dir(), reason="frozen regime store or NQ catalog absent")
def test_real_data_parity_with_frozen_regime_store_2021_01():
    import pandas as pd
    import pyarrow.parquet as pq
    from utils.runner.data import CausalDataLoader
    loader = CausalDataLoader(MAIN_REPO / "data/catalog/NQ_v0_2020_2026")
    bars = loader.load_bars("NQ.XCME-1-MINUTE-LAST-EXTERNAL", pd.Timestamp("2020-12-01", tz="UTC"), pd.Timestamp("2021-02-01", tz="UTC"))
    assert len(bars) > 20000
    t = DualEmaRegimeTracker(timeframe="1m", instrument="NQ")
    flips = []
    for b in bars:
        upd = t.observe(float(b.high), float(b.low), float(b.close))
        if upd.flipped or (upd.previous_regime == 0 and upd.regime != 0):
            flips.append((int(b.ts_init), upd.regime))
    ref = pq.read_table(STORE, columns=["regime_start_decision_ns", "regime_direction"]).to_pandas()
    lo, hi = pd.Timestamp("2021-01-05", tz="UTC").value, pd.Timestamp("2021-01-30", tz="UTC").value
    ref = ref[(ref["regime_start_decision_ns"] >= lo) & (ref["regime_start_decision_ns"] <= hi)]
    ours = {(ts, d) for ts, d in flips if lo <= ts <= hi}
    theirs = {(int(r.regime_start_decision_ns), int(r.regime_direction)) for r in ref.itertuples()}
    assert len(theirs) > 500
    missing, extra = theirs - ours, ours - theirs
    assert not missing and not extra, {"missing_from_tracker": sorted(missing)[:5], "extra_in_tracker": sorted(extra)[:5], "n_ref": len(theirs), "n_ours": len(ours)}
