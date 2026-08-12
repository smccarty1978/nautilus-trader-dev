"""The vectorised 5s regime must equal a literal aggregator + engine replay.

SPEC section 3 freezes the 5s regime as `RegimeStateEngine` over
`TimeframeAggregator`'s 5s buckets. `regime_5s.py` computes that with
`ewm_mean(adjust=False)` and a forward-fill instead of a per-bar Python loop, for
speed over 61.5M rows. That substitution is only legitimate if it is bit-equal to
the thing it replaces, which is what these tests establish -- on a real slice of
the canonical store, not a synthetic fixture.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from collectors.collector_v2.aggregator import TimeframeAggregator
from collectors.collector_v2.regime_engine import RegimeStateEngine
from collectors.collector_v2.registry import CompletedBarRegistry
from studies.p90_5s_regime_impulse.implementation.regime_5s import (
    BUCKET_NS, apply_regime, flip_timeline, Regime5s,
)

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
SLICE_ROWS = 400_000


@pytest.fixture(scope="module")
def raw() -> pl.DataFrame:
    """A contiguous real slice of the path feed, in path_event_ns order."""
    df = (
        pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet")
        .select("path_event_ns", "open", "high", "low", "close", "volume")
        .sort("path_event_ns")
        .head(SLICE_ROWS)
        .collect()
    )
    assert df.height == SLICE_ROWS
    return df


@pytest.fixture(scope="module")
def replayed(raw: pl.DataFrame) -> pl.DataFrame:
    """Ground truth: drive the real aggregator + real engine, bar by bar."""
    registry = CompletedBarRegistry(supported_timeframes=("5s",))
    engine = RegimeStateEngine("5s", registry)
    out: list[dict] = []

    def on_closed(tf: str, bucket) -> None:
        engine.on_bar_closed(bucket)
        st = registry.get("5s")
        out.append({
            "close_ts": st.close_ts, "high": st.high, "low": st.low,
            "close": st.close, "regime": st.regime,
        })

    agg = TimeframeAggregator(on_bucket_closed=on_closed, timeframes=("5s",))
    for r in raw.iter_rows(named=True):
        agg.on_1s_bar(int(r["path_event_ns"]), r["open"], r["high"],
                      r["low"], r["close"], r["volume"] or 0.0)
    return pl.DataFrame(out)


@pytest.fixture(scope="module")
def vectorised(raw: pl.DataFrame) -> pl.DataFrame:
    buckets = (
        raw.with_columns(bucket_id=(pl.col("path_event_ns") // BUCKET_NS))
        .group_by("bucket_id", maintain_order=True)
        .agg(high=pl.col("high").max(), low=pl.col("low").min(),
             close=pl.col("close").last(), n_1s=pl.len())
        .sort("bucket_id")
        .with_columns(
            open_ts=(pl.col("bucket_id") * BUCKET_NS),
            close_ts=((pl.col("bucket_id") + 1) * BUCKET_NS),
        )
    )
    # The aggregator never closes the final in-progress bucket (aggregator.py:83),
    # so the vectorised frame carries exactly one extra row the replay cannot emit.
    return apply_regime(buckets).head(buckets.height - 1)


def test_bucket_boundaries_match(replayed, vectorised):
    assert replayed.height == vectorised.height
    assert replayed["close_ts"].to_list() == vectorised["close_ts"].to_list()


def test_bucket_ohlc_matches(replayed, vectorised):
    for col in ("high", "low", "close"):
        np.testing.assert_array_equal(
            replayed[col].to_numpy(), vectorised[col].to_numpy(),
            err_msg=f"{col} differs between replay and vectorised build")


def test_regime_matches_exactly(replayed, vectorised):
    """The whole point: identical sticky regime on every completed bucket."""
    np.testing.assert_array_equal(
        replayed["regime"].to_numpy().astype(np.int8),
        vectorised["regime"].to_numpy().astype(np.int8))


def test_regime_is_sticky_binary_after_warmup(vectorised):
    """SPEC 3.1: no NEUTRAL state exists, so 'not aligned' == 'opposite'."""
    reg = vectorised["regime"].to_numpy()
    nz = np.flatnonzero(reg != 0)
    assert nz.size > 0
    assert set(np.unique(reg[nz[0]:]).tolist()) <= {-1, 1}, \
        "a 0 appears after the first signal -- the carry-forward is broken"


def test_bucket_contains_only_past_bars(raw, vectorised):
    """A bucket closing at C may contain only bars covering (C-5s, C].

    Bucketing on the availability clock instead of the open clock would fold the
    bar closing at C+4s into the bucket labelled C. This is the four-second
    look-ahead the SPEC's clock separation exists to prevent.
    """
    ev = raw["path_event_ns"].to_numpy()
    bid = ev // BUCKET_NS
    for close_ts in vectorised["close_ts"].to_numpy()[:2000]:
        # close_ts == (bucket_id + 1) * BUCKET_NS, so the members are one id back
        member_ev = ev[bid == (close_ts // BUCKET_NS) - 1]
        assert member_ev.size > 0
        # path_init = path_event + 1s must land in (C-5s, C]
        assert (member_ev + 1_000_000_000 <= close_ts).all()
        assert (member_ev + 1_000_000_000 > close_ts - BUCKET_NS).all()


def test_lookup_never_reads_an_incomplete_bucket(vectorised):
    """`state_at(t)` must return the last bucket with close_ts <= t."""
    flips = flip_timeline(vectorised)
    r5 = Regime5s(flips)
    for close_ts, regime in zip(flips["close_ts"].to_list()[:200],
                                flips["regime"].to_list()[:200]):
        # available exactly AT its close ...
        assert int(r5.state_at(close_ts)) == regime
        # ... and invisible one nanosecond earlier. Every row of the change-point
        # list carries a regime differing from its predecessor, so a lookup that
        # leaked the in-progress bucket would show the new value early.
        assert int(r5.state_at(close_ts - 1)) != regime


def test_first_non_aligned_after_is_a_real_later_bucket(vectorised):
    r5 = Regime5s(flip_timeline(vectorised))
    for t, d in [(int(r5.close_ts[k]), int(r5.regime[k])) for k in range(0, 50)]:
        nxt = r5.first_non_aligned_after(t, d)
        if nxt == -1:
            continue
        assert nxt > t, "the exit bucket must close strictly after the decision"
        assert int(r5.state_at(nxt)) != d
