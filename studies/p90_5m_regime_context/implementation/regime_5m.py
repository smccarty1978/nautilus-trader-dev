"""Build the 5-minute regime timeline from the canonical store's own 1s rows.

Direct adaptation of `studies/p90_5s_regime_impulse/implementation/regime_5s.py`
(SPEC section 2) -- only `BUCKET_NS` changes. Two things remain load-bearing,
copied verbatim from that study:

* **Bucketing is on `path_event_ns` (bar OPEN), availability is `close_ts`.**
  `aggregator.py:122` uses `bucket_id = ts_event // bucket_size` and
  `close_ts = (bucket_id + 1) * bucket_size`. The bucket closing at `C`
  therefore contains exactly the 1s bars covering `(C-300s, C]`. Bucketing on
  the availability clock instead would fold a bar closing after `C` into the
  bucket labelled `C` -- a look-ahead. The two clocks are kept separate
  throughout (SPEC section 5).
* **The engine is run continuously across RTH and ETH.** Restarting it at each
  RTH open would hand every session a cold, warmup-contaminated regime.
  Entries and classification are gated to RTH downstream; the *state* is
  continuous.

Two additions beyond the 5s template (SPEC section 2): a full per-bucket
state table (5m has ~300-500k closed buckets over 5 years, cheap to keep in
full, unlike 5s's 12M rows) to answer "regime age in completed bars", and
`age_seconds_at`/`age_bars_at` query methods on `Regime5m`.

`tests/test_regime_5m_parity.py` proves the vectorised result equals a literal
`TimeframeAggregator` + `RegimeStateEngine` replay bar for bar (SPEC 2.1).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
WORK = ROOT / "studies/p90_5m_regime_context/_work"

NS = 1_000_000_000
BUCKET_NS = 5 * 60 * NS

# collectors/collector_v2/regime_engine.py: RegimeStateEngine.ALPHA3/ALPHA9
ALPHA3 = 2.0 / (3 + 1)
ALPHA9 = 2.0 / (9 + 1)

BUCKETS_PATH = WORK / "regime_5m_buckets.parquet"
FLIPS_PATH = WORK / "regime_5m_flips.parquet"
BUILD_META = WORK / "regime_5m_build.json"

#: runtime cross-check (SPEC section 2) -- non-blocking, informational only.
V2_SNAPSHOT_DIR = ROOT / "backtests/studies/1m_regime_collector_v2/results"
V2_SNAPSHOT_YEARS = (2021, 2022, 2023, 2024, 2025)
V2_AGREEMENT_WARN_BELOW = 0.95


def build_buckets() -> pl.DataFrame:
    """5m OHLC buckets over the FULL path feed (RTH + ETH), sorted by close_ts.

    A bucket exists only if at least one 1s bar fell in its slot -- identical
    to the aggregator, which never emits an empty bucket.
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
    # qualifying bar) become regime 0 = uninitialised, which downstream treats
    # as an explicit UNINIT category rather than imputing a direction.
    df = df.with_columns(raw_signal=raw).with_columns(
        regime=pl.col("raw_signal").forward_fill().fill_null(0).cast(pl.Int8)
    )
    return df.with_columns(
        bar_index=pl.arange(0, pl.len()).cast(pl.Int64),
        prev_regime=pl.col("regime").shift(1).fill_null(0).cast(pl.Int8),
    )


def flip_timeline(state: pl.DataFrame) -> pl.DataFrame:
    """One row per 5m regime CHANGE: (close_ts, regime, bar_index).

    Every question this study asks ("state at t", "age at t") is a
    searchsorted over these change points; the full per-bucket state
    (`regime_5m_buckets.parquet`) is kept separately only to answer "age in
    completed bars", which needs the full bar index, not just flip points.
    The first row is the initial transition out of 0.
    """
    flips = state.filter(pl.col("regime") != pl.col("prev_regime")).select(
        "close_ts", "regime", "bar_index"
    )
    return flips.sort("close_ts")


class Regime5m:
    """Queryable 5m regime timeline. All lookups are availability-clock based.

    `state_at(t)` answers with the last bucket whose `close_ts <= t`, which is
    exactly the `CompletedBarRegistry` invariant (`state.close_ts <=
    decision_ts`). Nothing here can read an in-progress bucket.
    """

    def __init__(self, flips: pl.DataFrame, all_close_ts: np.ndarray):
        self.close_ts = flips["close_ts"].to_numpy()
        self.regime = flips["regime"].to_numpy().astype(np.int8)
        self.flip_bar_index = flips["bar_index"].to_numpy()
        # full per-bucket close_ts grid, for "age in completed bars"
        self._all_close_ts = all_close_ts

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

    def lookahead_next_change_after(self, t_ns: int | np.ndarray) -> np.ndarray:
        """close_ts of the first regime CHANGE strictly after t; -1 if none.

        `lookahead_`-prefixed by convention (not just its caller's output
        columns): the ONE legitimate forward-looking lookup in this study
        (SPEC 5). May only be called from
        `classify.py::phase6_future_flip_labels`, whose output is walled off
        into a separate, `label_only_`-prefixed frame. `validate.py` asserts
        via a source scan that this method has exactly that one call site.
        """
        j = np.searchsorted(self.close_ts, t_ns, side="right")
        return np.where(j < self.close_ts.size, self.close_ts[np.minimum(j, self.n - 1)], -1)

    def lookahead_next_change_into_direction_after(self, t_ns: int, direction: int) -> int:
        """close_ts of the first regime CHANGE strictly after t landing on
        `direction`; -1 if the regime never flips into `direction` in the feed.

        `lookahead_`-prefixed for the same reason as `lookahead_next_change_after`.
        """
        j = int(np.searchsorted(self.close_ts, t_ns, side="right"))
        while j < self.close_ts.size:
            if self.regime[j] == direction:
                return int(self.close_ts[j])
            j += 1
        return -1

    def age_seconds_at(self, t_ns: int | np.ndarray) -> np.ndarray:
        """Seconds the live 5m regime has been in force at t (== seconds since
        the last flip, the same quantity under this engine's semantics)."""
        flip = self.flip_ts_at(t_ns)
        out = np.where(flip >= 0, (np.asarray(t_ns) - flip) / NS, np.nan)
        return out

    def age_bars_at(self, t_ns: int | np.ndarray) -> np.ndarray:
        """Completed 5m bars since (and including) the flip bar, at t.

        Reproduces `RegimeStateEngine.bars_in_regime`, which counts 1 on the
        flip bar itself: bar-index of the last closed bucket <= t, minus
        bar-index of the flip bucket, plus 1.
        """
        i = self._idx_at(t_ns)
        cur_bar_idx = np.searchsorted(self._all_close_ts, t_ns, side="right") - 1
        flip_bar_idx = np.where(i >= 0, self.flip_bar_index[np.maximum(i, 0)], -1)
        out = np.where((i >= 0) & (cur_bar_idx >= 0), cur_bar_idx - flip_bar_idx + 1, -1)
        return out


def load() -> Regime5m:
    if not FLIPS_PATH.exists() or not BUCKETS_PATH.exists():
        raise FileNotFoundError(
            f"{FLIPS_PATH} / {BUCKETS_PATH} missing -- run `python -m "
            f"studies.p90_5m_regime_context.implementation.regime_5m` first"
        )
    flips = pl.read_parquet(FLIPS_PATH)
    all_close_ts = pl.read_parquet(BUCKETS_PATH, columns=["close_ts"])["close_ts"].to_numpy()
    return Regime5m(flips, all_close_ts)


def _runtime_cross_check() -> dict:
    """SPEC section 2: non-blocking reconciliation against the independent
    5m regime already snapshotted by `1m_regime_collector_v2`. A mismatch is
    a finding to report, not proof this engine is wrong -- that collector is
    a separate implementation, not provably the same code path as
    `RegimeStateEngine`. The parity test (section 2.1) is the authoritative
    causal-correctness check, not this cross-check.
    """
    r5m = load()
    n_checked, n_agree = 0, 0
    per_year: dict[str, dict] = {}
    for year in V2_SNAPSHOT_YEARS:
        p = V2_SNAPSHOT_DIR / f"v2_feature_snapshots_{year}.parquet"
        if not p.exists():
            per_year[str(year)] = {"available": False}
            continue
        # checkpoint_s == 0 is the row AT signal_time itself; any later
        # checkpoint (30, 60, ... s after signal) reflects a LATER 5m state
        # and would corrupt the comparison (lookahead-auditor pass 1, F1/A1).
        snap = pl.read_parquet(
            p, columns=["signal_time", "checkpoint_s", "regime_5m_direction"]
        ).filter(pl.col("checkpoint_s") == 0).drop_nulls(["signal_time", "regime_5m_direction"])
        if snap.height == 0:
            per_year[str(year)] = {"available": True, "n": 0}
            continue
        t = snap["signal_time"].to_numpy()
        ours = r5m.state_at(t)
        theirs = snap["regime_5m_direction"].to_numpy()
        # theirs is +1/-1 (no neutral in the runtime collector once armed);
        # only compare where our engine is warmed up (state != 0)
        mask = ours != 0
        agree = int((ours[mask] == theirs[mask]).sum())
        n = int(mask.sum())
        n_checked += n
        n_agree += agree
        per_year[str(year)] = {
            "available": True, "n_compared": n,
            "agreement_rate": (agree / n) if n else float("nan"),
        }
    overall = (n_agree / n_checked) if n_checked else float("nan")
    return {
        "n_compared_total": n_checked,
        "agreement_rate_overall": overall,
        "warn_below": V2_AGREEMENT_WARN_BELOW,
        "warning": bool(n_checked and overall < V2_AGREEMENT_WARN_BELOW),
        "per_year": per_year,
        "note": ("non-blocking / informational -- separate implementation, "
                 "not the authoritative causal-correctness check (see 2.1 parity test)"),
    }


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    print("aggregating 1s path rows into 5m buckets ...", flush=True)
    all_buckets = build_buckets()
    n_slots, src_absorbed = all_buckets.height, int(all_buckets["n_1s"].sum())

    # The real aggregator never closes the final in-progress bucket -- a
    # bucket is closed only by the arrival of a bar in the NEXT bucket
    # (aggregator.py:83). Discard it here too, so the built timeline is
    # exactly what a live replay would have produced.
    final_bucket_n_1s = int(all_buckets["n_1s"][-1])
    buckets = all_buckets.head(n_slots - 1)
    n_buckets, n_1s = buckets.height, int(buckets["n_1s"].sum())
    print(f"  {n_buckets:,} closed buckets from {n_1s:,} 1s rows "
          f"(1 partial bucket discarded, {final_bucket_n_1s} rows)", flush=True)

    print("applying the sticky EMA3/EMA9 regime ...", flush=True)
    state = apply_regime(buckets)
    state.select("close_ts", "open_ts", "high", "low", "close", "regime",
                 "bar_index").write_parquet(BUCKETS_PATH)
    flips = flip_timeline(state)
    flips.write_parquet(FLIPS_PATH)
    print(f"  {flips.height:,} regime changes -> {FLIPS_PATH.name}", flush=True)

    # Reconciliation, not assumption. The bucket grid must account for every
    # 1s row, and the bucket count must equal the number of distinct 5m slots
    # the feed actually touches.
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
    print("cross-checking against the independent runtime 5m snapshot collector ...",
          flush=True)
    cross_check = _runtime_cross_check()

    meta = {
        "buckets_built": n_buckets,
        "buckets_expected_closed": expected_slots - 1,
        "distinct_5m_slots_touched": expected_slots,
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
        "availability_clock": "close_ts = (bucket_id + 1) * 300e9",
        "sessions_included": "RTH+ETH (continuous engine); entries/classification gated to RTH downstream",
        "final_partial_bucket_discarded": bool(n_buckets == n_slots - 1),
        "regime_value_counts_over_closed_buckets": {
            str(k): int(v) for k, v in
            zip(*[state["regime"].value_counts().sort("regime")[c].to_list()
                  for c in ("regime", "count")])
        },
        "runtime_cross_check": cross_check,
        "flips_sha256": hashlib.sha256(FLIPS_PATH.read_bytes()).hexdigest(),
        "buckets_sha256": hashlib.sha256(BUCKETS_PATH.read_bytes()).hexdigest(),
    }
    BUILD_META.write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: v for k, v in meta.items()
                      if k not in ("flips_sha256", "buckets_sha256")}, indent=2))
    if not meta["buckets_reconcile"] or not meta["rows_reconcile"]:
        raise RuntimeError("5m bucket grid failed to reconcile -- SPEC section 9 ABORT")
    if cross_check["warning"]:
        print(f"WARNING: runtime cross-check agreement "
              f"{cross_check['agreement_rate_overall']:.4f} < "
              f"{V2_AGREEMENT_WARN_BELOW} (non-blocking, see SPEC section 2)")


if __name__ == "__main__":
    main()
