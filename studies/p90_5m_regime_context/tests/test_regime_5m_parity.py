"""The vectorised 5m regime must equal a literal aggregator + engine replay.

SPEC section 2 freezes the 5m regime as `RegimeStateEngine` over
`TimeframeAggregator`'s 5m buckets. `regime_5m.py` computes that with
`ewm_mean(adjust=False)` and a forward-fill instead of a per-bar Python loop.
That substitution is only legitimate if it is bit-equal to the thing it
replaces, which is what these tests establish -- on a real slice of the
canonical store, not a synthetic fixture. Direct adaptation of
`studies/p90_5s_regime_impulse/tests/test_regime_5s_parity.py`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from collectors.collector_v2.aggregator import TimeframeAggregator
from collectors.collector_v2.regime_engine import RegimeStateEngine
from collectors.collector_v2.registry import CompletedBarRegistry
from studies.p90_5m_regime_context.implementation.regime_5m import (
    BUCKET_NS, apply_regime, flip_timeline, Regime5m,
)

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
SLICE_ROWS = 200_000


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
    registry = CompletedBarRegistry(supported_timeframes=("5m",))
    engine = RegimeStateEngine("5m", registry)
    out: list[dict] = []

    def on_closed(tf: str, bucket) -> None:
        engine.on_bar_closed(bucket)
        st = registry.get("5m")
        out.append({
            "close_ts": st.close_ts, "high": st.high, "low": st.low,
            "close": st.close, "regime": st.regime,
        })

    agg = TimeframeAggregator(on_bucket_closed=on_closed, timeframes=("5m",))
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
    assert replayed.height > 0, "slice too small to close any 5m bucket"
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
    """SPEC 2: no NEUTRAL state exists, so 'not aligned' == 'opposite'."""
    reg = vectorised["regime"].to_numpy()
    nz = np.flatnonzero(reg != 0)
    assert nz.size > 0
    assert set(np.unique(reg[nz[0]:]).tolist()) <= {-1, 1}, \
        "a 0 appears after the first signal -- the carry-forward is broken"


def test_bucket_contains_only_past_bars(raw, vectorised):
    """A bucket closing at C may contain only bars covering (C-300s, C].

    Bucketing on the availability clock instead of the open clock would fold
    a bar closing after C into the bucket labelled C. This is the look-ahead
    the SPEC's clock separation exists to prevent.
    """
    ev = raw["path_event_ns"].to_numpy()
    bid = ev // BUCKET_NS
    for close_ts in vectorised["close_ts"].to_numpy()[:2000]:
        # close_ts == (bucket_id + 1) * BUCKET_NS, so the members are one id back
        member_ev = ev[bid == (close_ts // BUCKET_NS) - 1]
        assert member_ev.size > 0
        # path_init = path_event + 1s must land in (C-300s, C]
        assert (member_ev + 1_000_000_000 <= close_ts).all()
        assert (member_ev + 1_000_000_000 > close_ts - BUCKET_NS).all()


def test_lookup_never_reads_an_incomplete_bucket(vectorised):
    """`state_at(t)` must return the last bucket with close_ts <= t."""
    flips = flip_timeline(vectorised)
    r5m = Regime5m(flips, vectorised["close_ts"].to_numpy())
    for close_ts, regime in zip(flips["close_ts"].to_list()[:200],
                                flips["regime"].to_list()[:200]):
        # available exactly AT its close ...
        assert int(r5m.state_at(close_ts)) == regime
        # ... and invisible one nanosecond earlier. Every row of the
        # change-point list carries a regime differing from its predecessor,
        # so a lookup that leaked the in-progress bucket would show the new
        # value early.
        assert int(r5m.state_at(close_ts - 1)) != regime


def test_first_change_into_direction_after_is_a_real_later_bucket(vectorised):
    flips = flip_timeline(vectorised)
    r5m = Regime5m(flips, vectorised["close_ts"].to_numpy())
    for t, d in [(int(r5m.close_ts[k]), int(r5m.regime[k]))
                 for k in range(0, min(50, r5m.n))]:
        # look for the next flip AWAY from d, then the next flip back INTO d
        away = r5m.lookahead_next_change_after(t)
        if away == -1:
            continue
        nxt = r5m.lookahead_next_change_into_direction_after(int(away), d)
        if nxt == -1:
            continue
        assert nxt > t, "the target bucket must close strictly after the decision"
        assert int(r5m.state_at(nxt)) == d


def test_age_bars_matches_bars_in_regime(replayed, vectorised):
    """age_bars_at(close_ts of bucket i) must equal RegimeStateEngine's
    bars_in_regime as of bucket i, reconstructed from the replay's own
    regime column (consecutive same-regime run length ending at i)."""
    flips = flip_timeline(vectorised)
    r5m = Regime5m(flips, vectorised["close_ts"].to_numpy())
    reg = replayed["regime"].to_numpy()
    close_ts = replayed["close_ts"].to_numpy()

    # Reconstruct expected bars_in_regime by run-length from the replay.
    # RegimeStateEngine leaves bars_in_regime at 0 while regime==0 (the
    # leading uninitialised prefix, which can never recur once a first
    # signal fires -- see regime_engine.py's `if new_regime == 0: pass`) --
    # so this is -1 there (matching Regime5m.age_bars_at's sentinel), not a
    # naive row-position count.
    expected = np.empty(reg.size, dtype=np.int64)
    run = 0
    prev = None
    for i, r in enumerate(reg):
        if r == 0:
            expected[i] = -1
            run, prev = 0, 0
            continue
        run = run + 1 if r == prev else 1
        expected[i] = run
        prev = r

    sample = np.linspace(0, reg.size - 1, num=min(200, reg.size), dtype=int)
    for i in sample:
        got = int(r5m.age_bars_at(int(close_ts[i])))
        assert got == int(expected[i]), (
            f"bucket {i}: age_bars_at={got} expected bars_in_regime={expected[i]}")
