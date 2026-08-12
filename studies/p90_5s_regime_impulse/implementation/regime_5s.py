"""Build the 5-second regime timeline from the canonical store's own 1s rows.

**This artifact did not exist before this study.** The canonical store's "5s
checkpoints" are model-scoring dispatch slots, not a regime, and no 5s regime
column exists anywhere in it. SPEC section 3 freezes the definition: the *same*
sticky rule the 1m regime uses (`RegimeStateEngine`), applied to 5s buckets built
by `TimeframeAggregator`'s bucketing.

Two things here are load-bearing:

* **Bucketing is on `path_event_ns` (bar OPEN), availability is `close_ts`.**
  `aggregator.py:122` uses `bucket_id = ts_event // bucket_size` and
  `close_ts = (bucket_id + 1) * bucket_size`. The bucket closing at `C` therefore
  contains exactly the 1s bars covering `(C-5s, C]`. Bucketing on the
  availability clock instead would fold the bar closing at `C+4s` into the bucket
  labelled `C` -- a four-second look-ahead. The two clocks are kept separate
  throughout (SPEC section 5).
* **The engine is run continuously across RTH and ETH.** Restarting it at each
  RTH open would hand every session a cold, warmup-contaminated regime. Entries
  and exits are gated to RTH downstream; the *state* is continuous.

The recursion is vectorised rather than looped. `ewm_mean(adjust=False)` is
exactly `y[0] = x[0]; y[i] = a*x[i] + (1-a)*y[i-1]`, which is the engine's EMA
update verbatim, and the sticky carry-forward is a forward-fill of the ternary
signal. `tests/test_regime_5s_parity.py` proves the vectorised result equals a
literal `TimeframeAggregator` + `RegimeStateEngine` replay bar for bar.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
WORK = ROOT / "studies/p90_5s_regime_impulse/_work"

NS = 1_000_000_000
BUCKET_NS = 5 * NS

# collectors/collector_v2/regime_engine.py: ALPHA3, ALPHA9
ALPHA3 = 2.0 / (3 + 1)
ALPHA9 = 2.0 / (9 + 1)

FLIPS_PATH = WORK / "regime_5s_flips.parquet"
BUCKETS_META = WORK / "regime_5s_build.json"


def build_buckets() -> pl.DataFrame:
    """5s OHLC buckets over the FULL path feed (RTH + ETH), sorted by close_ts.

    A bucket exists only if at least one 1s bar fell in its slot -- identical to
    the aggregator, which never emits an empty bucket.
    """
    lf = (
        pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet")
        .select("path_event_ns", "high", "low", "close")
        .with_columns(bucket_id=(pl.col("path_event_ns") // BUCKET_NS))
        .sort("path_event_ns")
        .group_by("bucket_id", maintain_order=True)
        .agg(
            high=pl.col("high").max(),
            low=pl.col("low").min(),
            close=pl.col("close").last(),
            n_1s=pl.len(),
        )
    )
    df = lf.collect(engine="streaming").sort("bucket_id")
    return df.with_columns(
        open_ts=(pl.col("bucket_id") * BUCKET_NS),
        close_ts=((pl.col("bucket_id") + 1) * BUCKET_NS),
    )


def apply_regime(buckets: pl.DataFrame) -> pl.DataFrame:
    """Sticky EMA3/EMA9 high-low regime, exactly `RegimeStateEngine`'s rule.

    +1 if close > EMA3_high and close > EMA9_high
    -1 if close < EMA3_low  and close < EMA9_low
    else carry the previous regime forward (0 only before the first signal).
    """
    df = buckets.with_columns(
        ema3_h=pl.col("high").ewm_mean(alpha=ALPHA3, adjust=False),
        ema9_h=pl.col("high").ewm_mean(alpha=ALPHA9, adjust=False),
        ema3_l=pl.col("low").ewm_mean(alpha=ALPHA3, adjust=False),
        ema9_l=pl.col("low").ewm_mean(alpha=ALPHA9, adjust=False),
    )
    raw = (
        pl.when((pl.col("close") > pl.col("ema3_h")) & (pl.col("close") > pl.col("ema9_h")))
        .then(pl.lit(1, dtype=pl.Int8))
        .when((pl.col("close") < pl.col("ema3_l")) & (pl.col("close") < pl.col("ema9_l")))
        .then(pl.lit(-1, dtype=pl.Int8))
        .otherwise(None)
    )
    # forward_fill IS the engine's sticky carry; leading nulls (before the first
    # qualifying bar) become regime 0 = uninitialised, which downstream treats as
    # an explicit NON-ENTRY category rather than imputing a direction.
    df = df.with_columns(raw_signal=raw).with_columns(
        regime=pl.col("raw_signal").forward_fill().fill_null(0).cast(pl.Int8)
    )
    return df.with_columns(
        prev_regime=pl.col("regime").shift(1).fill_null(0).cast(pl.Int8)
    )


def flip_timeline(state: pl.DataFrame) -> pl.DataFrame:
    """One row per 5s regime CHANGE: (close_ts, regime).

    The full per-bucket state is 12M rows and is never needed -- every question
    this study asks ("state at t", "age at t", "first non-aligned bucket after t",
    "next aligned bucket after t") is a searchsorted over the change points.
    The first row is the initial transition out of 0.
    """
    flips = state.filter(pl.col("regime") != pl.col("prev_regime")).select(
        "close_ts", "regime", "bucket_id"
    )
    return flips.sort("close_ts")


class Regime5s:
    """Queryable 5s regime timeline. All lookups are availability-clock based.

    `state_at(t)` answers with the last bucket whose `close_ts <= t`, which is
    exactly the `CompletedBarRegistry` invariant (`state.close_ts <=
    decision_ts`). Nothing here can read an in-progress bucket.
    """

    def __init__(self, flips: pl.DataFrame):
        self.close_ts = flips["close_ts"].to_numpy()
        self.regime = flips["regime"].to_numpy().astype(np.int8)

    @property
    def n(self) -> int:
        return int(self.close_ts.size)

    def _idx_at(self, t_ns: int | np.ndarray) -> np.ndarray:
        """Index of the last flip with close_ts <= t; -1 if none yet."""
        return np.searchsorted(self.close_ts, t_ns, side="right") - 1

    def state_at(self, t_ns: int | np.ndarray) -> np.ndarray:
        """Regime available AT t. 0 = uninitialised (no completed bucket yet)."""
        i = self._idx_at(t_ns)
        out = np.where(i >= 0, self.regime[np.maximum(i, 0)], np.int8(0))
        return out.astype(np.int8)

    def flip_ts_at(self, t_ns: int | np.ndarray) -> np.ndarray:
        """close_ts of the bucket that STARTED the regime live at t; -1 if none."""
        i = self._idx_at(t_ns)
        return np.where(i >= 0, self.close_ts[np.maximum(i, 0)], -1)

    def next_change_after(self, t_ns: int | np.ndarray) -> np.ndarray:
        """close_ts of the first regime CHANGE strictly after t; -1 if none."""
        j = np.searchsorted(self.close_ts, t_ns, side="right")
        return np.where(j < self.close_ts.size, self.close_ts[np.minimum(j, self.n - 1)], -1)

    def first_non_aligned_after(self, t_ns: int, direction: int) -> int:
        """close_ts of the first bucket after t whose regime != direction.

        Because the engine is sticky binary, the regime only changes at flips, so
        the first non-aligned *bucket* is the first flip away from `direction`.
        Returns -1 if the regime never leaves `direction` in the feed.
        """
        j = int(np.searchsorted(self.close_ts, t_ns, side="right"))
        while j < self.close_ts.size:
            if self.regime[j] != direction:
                return int(self.close_ts[j])
            j += 1
        return -1

    def first_aligned_after(self, t_ns: int, direction: int) -> int:
        """close_ts of the first bucket after t whose regime == direction."""
        j = int(np.searchsorted(self.close_ts, t_ns, side="right"))
        while j < self.close_ts.size:
            if self.regime[j] == direction:
                return int(self.close_ts[j])
            j += 1
        return -1


def load() -> Regime5s:
    if not FLIPS_PATH.exists():
        raise FileNotFoundError(
            f"{FLIPS_PATH} missing -- run `python -m "
            f"studies.p90_5s_regime_impulse.implementation.regime_5s` first"
        )
    return Regime5s(pl.read_parquet(FLIPS_PATH))


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    print("aggregating 1s path rows into 5s buckets ...", flush=True)
    all_buckets = build_buckets()
    n_slots, src_absorbed = all_buckets.height, int(all_buckets["n_1s"].sum())

    # The real aggregator never closes the final in-progress bucket -- a bucket
    # is closed only by the arrival of a bar in the NEXT bucket (aggregator.py:83).
    # Discard it here too, so the built timeline is exactly what a live replay
    # would have produced. Found by lookahead-auditor pass 1, which noted the
    # build kept it while asserting otherwise. Provably inert for every trade
    # (the row is the feed's last, outside RTH), but an assertion that is merely
    # true-in-practice is the kind that stops being true later.
    final_bucket_n_1s = int(all_buckets["n_1s"][-1])
    buckets = all_buckets.head(n_slots - 1)
    n_buckets, n_1s = buckets.height, int(buckets["n_1s"].sum())
    print(f"  {n_buckets:,} closed buckets from {n_1s:,} 1s rows "
          f"(1 partial bucket discarded, {final_bucket_n_1s} rows)", flush=True)

    print("applying the sticky EMA3/EMA9 regime ...", flush=True)
    state = apply_regime(buckets)
    flips = flip_timeline(state)
    flips.write_parquet(FLIPS_PATH)
    print(f"  {flips.height:,} regime changes -> {FLIPS_PATH.name}", flush=True)

    # Reconciliation, not assumption (SPEC section 7). The bucket grid must
    # account for every 1s row, and the bucket count must equal the number of
    # distinct 5s slots the feed actually touches.
    expected_slots = int(
        pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet")
        .select((pl.col("path_event_ns") // BUCKET_NS).n_unique())
        .collect()
        .item()
    )
    src_rows = int(
        pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet")
        .select(pl.len()).collect().item()
    )
    meta = {
        "buckets_built": n_buckets,
        "buckets_expected_closed": expected_slots - 1,
        "distinct_5s_slots_touched": expected_slots,
        # every slot the feed touches is either a closed bucket or THE final
        # partial one -- exactly one bucket may be outstanding, never more
        "buckets_reconcile": n_buckets + 1 == expected_slots,
        "source_1s_rows": src_rows,
        "absorbed_1s_rows": n_1s,
        "final_partial_bucket_1s_rows": final_bucket_n_1s,
        "rows_reconcile": n_1s + final_bucket_n_1s == src_rows,
        "regime_changes": flips.height,
        "alpha3": ALPHA3,
        "alpha9": ALPHA9,
        "bucket_ns": BUCKET_NS,
        "bucketing_clock": "path_event_ns (bar OPEN)",
        "availability_clock": "close_ts = (bucket_id + 1) * 5e9",
        "sessions_included": "RTH+ETH (continuous engine); entries/exits gated to RTH downstream",
        # computed from the build, not asserted
        "final_partial_bucket_discarded": bool(n_buckets == n_slots - 1),
        "regime_value_counts_over_closed_buckets": {
            str(k): int(v) for k, v in
            zip(*[state["regime"].value_counts().sort("regime")[c].to_list()
                  for c in ("regime", "count")])
        },
        "flips_sha256": hashlib.sha256(FLIPS_PATH.read_bytes()).hexdigest(),
    }
    BUCKETS_META.write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: v for k, v in meta.items() if k != "flips_sha256"}, indent=2))
    if not meta["buckets_reconcile"] or not meta["rows_reconcile"]:
        raise RuntimeError("5s bucket grid failed to reconcile -- SPEC section 8 ABORT")


if __name__ == "__main__":
    main()
