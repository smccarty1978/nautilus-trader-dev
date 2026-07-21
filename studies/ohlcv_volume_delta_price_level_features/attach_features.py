"""Attach Part A/B features to the existing labeled short-RTH surface, by
live-replaying raw 1s/1m bars through the same OHLCVDeltaTracker/
PriceLevelTracker classes registered in features/registry.py -- not a
separate vectorized reimplementation (benchmarked: ~270s/year, comparable to
this repo's existing atlas-build cost, see SPEC.md scout item 5 resolution).

Regime boundaries are taken from the already-audited `canonical_regime_timeline`
(the same function used throughout short_rth_entry_surface_backfill /
short_rth_w4_retrain_entry_strength) -- not re-derived. RTH uses the same
`is_rth()` (fill-time-remediated convention). ATR is `atr_at_entry`
(== atr_at_checkpoint) already present on the existing labeled surface --
never recomputed.

This script only ADDS columns to the existing labeled_featured_{year}.parquet
rows (keyed on regime_start_ns/observation_time) -- it never changes rows,
labels, or eligibility. Usable both for the 5-day runtime-validation smoke
(pass --start/--end) and the full 6-year attachment.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RETRAIN = ROOT / "studies" / "short_rth_w4_retrain_entry_strength"
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"
VALIDATION = HERE / "validation"
for d in (WORK, RESULTS, AUDIT, VALIDATION):
    d.mkdir(parents=True, exist_ok=True)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for p in (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, is_rth, validate_raw_bars,
)

from features.trackers.ohlcv_delta import OHLCVDeltaTracker  # noqa: E402
from features.trackers.price_levels import PriceLevelTracker  # noqa: E402

NS = 1_000_000_000
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)


def minute_bucket_key(bar_ts: int) -> int:
    """Bucket a close-labeled 1s bar (covering `(bar_ts-1s, bar_ts]`) into
    the 1-minute bucket it actually COMPLETES. A bar whose ts is an exact
    multiple of 60s is the true last second of the minute ending at that
    ts -- `bar_ts // 60s` would wrongly group it with the FOLLOWING 59
    seconds instead (this was CRIT-1: every synthesized 1-minute bar's
    content was silently wrong). `(bar_ts - 1) // 60s` is correct: for
    `bar_ts` in `{60k+1, ..., 60k+60}`, this returns `k`."""
    return (bar_ts - 1) // (60 * NS)


def surface_path(year: int) -> Path:
    return RETRAIN / "_work" / f"labeled_featured_{year}.parquet"


def run_year(year: int, start: str | None = None, end: str | None = None) -> dict:
    t0 = time.time()
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)

    surface = pd.read_parquet(surface_path(year))
    surface = surface.sort_values(["regime_start_ns", "observation_time"]).reset_index(drop=True)

    # Regime timeline must be built from the FULL raw year (regime detection
    # needs full-year context to reproduce the same boundaries as the
    # existing atlas) -- only the REPLAY loop below is truncated to the
    # validation window, with generous warmup padding so tracker state
    # (regime-relative, RTH-cumulative, prior-day/overnight) is not cold-started
    # mid-regime/mid-day.
    timeline = canonical_regime_timeline(year, raw)
    regime_starts = timeline["regime_start_ns"].to_numpy(np.int64)
    order = np.argsort(regime_starts)
    regime_starts = regime_starts[order]

    if start or end:
        obs_dt = pd.to_datetime(surface["observation_time"], unit="ns", utc=True)
        mask = pd.Series(True, index=surface.index)
        if start:
            mask &= obs_dt >= pd.Timestamp(start, tz="UTC")
        if end:
            mask &= obs_dt < pd.Timestamp(end, tz="UTC")
        surface = surface[mask].reset_index(drop=True)
        if start:
            padded_start = pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=5)
            start_ns = pd.Timestamp(start, tz="UTC").value
            # A fixed 5-day pad is not sufficient if the regime actually
            # active at --start began earlier than that (regime durations
            # are highly variable in this project's own data) -- replaying
            # from a truncated regime start would silently corrupt
            # regime-relative (A4) features while regime_elapsed_seconds
            # itself (computed from the true regime_start_ns) stayed
            # correct, an inconsistent combination that would not be
            # flagged anywhere. Extend the pad back to the true active
            # regime's start whenever that is earlier.
            prior_regime_starts = regime_starts[regime_starts <= start_ns]
            if len(prior_regime_starts):
                true_active_start = pd.Timestamp(int(prior_regime_starts.max()), unit="ns", tz="UTC")
                replay_start = min(padded_start, true_active_start)
            else:
                replay_start = padded_start
        else:
            replay_start = raw.index.min()
        replay_end = pd.Timestamp(end, tz="UTC") if end else raw.index.max()
        raw = raw.loc[replay_start:replay_end]

    # Baselines computed AFTER any --start/--end windowing, so the
    # row-count/label-preservation checks are meaningful in both the 5-day
    # smoke mode and the full-year mode (unfiltered, this is simply the
    # untouched existing surface).
    original_row_count = len(surface)
    original_label_cols = [c for c in surface.columns if c in (
        "net_pnl", "exit_reason", "hit_pre_alignment_stop", "label_available")]
    original_labels_hash = pd.util.hash_pandas_object(
        surface[original_label_cols]
    ).sum() if original_label_cols else None

    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)
    closes = raw["close"].to_numpy(float)
    vols = raw["volume"].to_numpy(float)

    # The atlas's `observation_time` is a theoretical fixed-5s-interval
    # timestamp (arange from regime start) -- it does not always land on an
    # actual traded second (occasional genuine 1s data gaps in the raw feed,
    # a pre-existing characteristic, not introduced here). Snap each
    # checkpoint to the last ACTUAL bar at or before its observation_time --
    # fully compliant with the observation contract (latest_source_ts_used
    # <= observation_ts) and avoids silently dropping otherwise-valid rows.
    obs_times = surface["observation_time"].to_numpy(np.int64)
    snap_idx = np.searchsorted(ts, obs_times, side="right") - 1
    n_ungapped = int((ts[np.clip(snap_idx, 0, len(ts) - 1)] == obs_times).sum())
    gap_snapped = int(len(obs_times) - n_ungapped - int((snap_idx < 0).sum()))

    obs_lookup: dict[int, list[tuple[int, int, float]]] = {}
    unmatched_before_data = 0
    for row, idx in zip(surface.itertuples(index=False), snap_idx):
        if idx < 0:
            unmatched_before_data += 1
            continue
        snap_ts = int(ts[idx])
        obs_lookup.setdefault(snap_ts, []).append(
            (int(row.regime_start_ns), int(row.observation_time), float(row.atr_at_entry)))

    ohlcv_tracker = OHLCVDeltaTracker()
    price_tracker = PriceLevelTracker()

    # Regime/RTH transitions are confirmed once per completed MINUTE (every
    # regime_start_ns is itself some minute's close timestamp, by
    # construction of the underlying 1m regime engine) -- FeatureEngine
    # cannot know a transition any sooner than that either. Resolving
    # regime/RTH context per-1-SECOND-bar (as this loop originally did)
    # attributed 59 of a transitioning minute's 60 seconds to the OLD
    # regime and only the exact boundary second to the new one -- disagreeing
    # with FeatureEngine's buffer-and-replay fix (CRIT-2), which correctly
    # attributes the whole confirming minute to the new regime. Fixed here
    # to match: buffer each forming minute's bars and resolve/replay them
    # only at that minute's completion, using the SAME granularity and the
    # SAME anchor-price convention (the confirming minute's own open) as
    # FeatureEngine now does.
    reg_idx = -1
    if len(regime_starts) and int(regime_starts[0]) <= int(ts[0]):
        reg_idx = int(np.searchsorted(regime_starts, ts[0], side="right")) - 1
        close_i = int(np.searchsorted(ts, regime_starts[reg_idx], side="left"))
        if close_i < len(ts) and int(ts[close_i]) == int(regime_starts[reg_idx]):
            # regime_starts[reg_idx] is the confirming minute's CLOSE (per
            # minute_bucket_key's convention, it's the minute's LAST bar,
            # not its first) -- scan backward to that minute's own first
            # bar so the anchor matches the main loop's `minute_o`
            # convention (the confirming minute's own open), not the
            # minute's last second's open.
            confirming_bucket = minute_bucket_key(int(regime_starts[reg_idx]))
            start_i = close_i
            while start_i > 0 and minute_bucket_key(int(ts[start_i - 1])) == confirming_bucket:
                start_i -= 1
            ohlcv_tracker.reset_regime(int(regime_starts[reg_idx]), float(opens[start_i]))
        # else: the regime active at the start of this replay window began
        # before any bar in our loaded (possibly padded) window -- this
        # should not happen given the CRIT-4 padding fix above, which
        # extends replay_start back to the true active regime's start. If
        # it ever does, regime_available correctly stays False until the
        # next in-window transition rather than silently using a wrong anchor.

    was_rth = False
    current_minute = None
    minute_o = minute_h = minute_l = prev_close = None
    minute_buffer: list[tuple[int, float, float, float, float]] = []
    last_finalized_1m_close_ts = None

    records = []
    n = len(ts)
    for i in range(n):
        bar_ts = int(ts[i])

        # Rolling-window (A1-A3) update: unconditional, no regime/RTH
        # dependency, so this happens immediately regardless of minute state.
        b_est = ohlcv_tracker.update(bar_ts, opens[i], highs[i], lows[i], closes[i], vols[i])

        minute_key = minute_bucket_key(bar_ts)
        if current_minute is None:
            current_minute = minute_key
            minute_o, minute_h, minute_l = opens[i], highs[i], lows[i]
            minute_buffer = [(bar_ts, highs[i], lows[i], vols[i], b_est["bar_est_delta"])]
        elif minute_key != current_minute:
            # Finalize the just-completed minute (built from minute_buffer,
            # which does NOT include bar i -- that belongs to the next minute).
            m_close_ts = int((current_minute + 1) * 60 * NS)

            while reg_idx + 1 < len(regime_starts) and m_close_ts >= regime_starts[reg_idx + 1]:
                reg_idx += 1
                ohlcv_tracker.reset_regime(int(regime_starts[reg_idx]), float(minute_o))

            now_rth = is_rth(m_close_ts)
            if now_rth and not was_rth:
                ohlcv_tracker.reset_rth(m_close_ts)
            elif not now_rth and was_rth:
                ohlcv_tracker.end_rth()
            was_rth = now_rth

            for buf_ts, buf_high, buf_low, buf_vol, buf_delta in minute_buffer:
                ohlcv_tracker.accumulate_regime_rth(buf_ts, buf_high, buf_low, buf_vol, buf_delta)

            price_tracker.update_1m(m_close_ts, minute_o, minute_h, minute_l, prev_close, now_rth)
            last_finalized_1m_close_ts = m_close_ts

            current_minute = minute_key
            minute_o, minute_h, minute_l = opens[i], highs[i], lows[i]
            minute_buffer = [(bar_ts, highs[i], lows[i], vols[i], b_est["bar_est_delta"])]
        else:
            minute_h = max(minute_h, highs[i])
            minute_l = min(minute_l, lows[i])
            minute_buffer.append((bar_ts, highs[i], lows[i], vols[i], b_est["bar_est_delta"]))
        prev_close = closes[i]

        hits = obs_lookup.get(bar_ts)
        if hits:
            for regime_start_ns, obs_time, atr in hits:
                # Computed per-row (not hoisted out of this loop) so each
                # row's own ATR is used -- rows that gap-snap to the same
                # underlying bar must not share one row's ATR-normalized values.
                f_ohlcv = ohlcv_tracker.calculate(atr=atr)
                f_price = price_tracker.calculate(bar_ts, closes[i], atr, direction=-1)
                rec = {"regime_start_ns": regime_start_ns, "observation_time": obs_time,
                       "latest_source_ts_used": bar_ts, "observation_ts": obs_time,
                       "latest_1s_bar_close_ts_used": bar_ts,
                       "latest_1m_bar_close_ts_used": last_finalized_1m_close_ts}
                rec.update(f_ohlcv)
                rec.update(f_price)
                records.append(rec)

    # Flush the trailing still-forming minute (WARN-5): the main loop only
    # commits a minute's buffered bars to regime/RTH cumulative state once
    # the FOLLOWING minute's first bar arrives, so the very last minute of
    # this replay window is otherwise left buffered and never committed.
    # No already-recorded checkpoint is retroactively affected (any
    # checkpoint within this trailing minute was already computed above,
    # using state as of the last minute that WAS finalized -- a bounded,
    # causally-valid lag, not a look-ahead issue); this flush only ensures
    # the tracker's own final state is complete if inspected afterward.
    if minute_buffer:
        for buf_ts, buf_high, buf_low, buf_vol, buf_delta in minute_buffer:
            ohlcv_tracker.accumulate_regime_rth(buf_ts, buf_high, buf_low, buf_vol, buf_delta)

    feat_df = pd.DataFrame(records)
    runtime_s = time.time() - t0

    merged = surface.merge(feat_df, on=["regime_start_ns", "observation_time"],
                          how="left", validate="one_to_one")
    dq_violations = int((merged["latest_source_ts_used"] > merged["observation_time"]).sum())

    new_row_count = len(merged)
    # merge(how="left") preserves the left frame's row order, and `surface`
    # was already sorted by keys above, so no re-sort is needed here.
    new_labels_hash = pd.util.hash_pandas_object(
        merged[original_label_cols]
    ).sum() if original_label_cols else None

    return {
        "year": year, "runtime_s": round(runtime_s, 1),
        "raw_bars_processed": n, "surface_rows": len(surface),
        "feature_rows_produced": len(feat_df),
        "gap_snapped_checkpoints": gap_snapped,
        "unmatched_before_data_start": unmatched_before_data,
        "original_row_count": original_row_count, "new_row_count": new_row_count,
        "row_count_unchanged": original_row_count == new_row_count,
        "labels_unchanged": (original_labels_hash == new_labels_hash),
        "duplicate_rows": int(merged.duplicated(["regime_start_ns", "observation_time"]).sum()),
        "provenance_violations": dq_violations,
        "merged_df": merged,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=list(YEARS))
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--out-prefix", type=str, default="attached")
    args = ap.parse_args()

    all_reports = {}
    for year in args.years:
        report = run_year(year, args.start, args.end)
        merged = report.pop("merged_df")
        all_reports[year] = report
        out_path = WORK / f"{args.out_prefix}_{year}.parquet"
        merged.to_parquet(out_path, index=False, compression="zstd")
        print(f"[{year}] {report['runtime_s']}s, {report['feature_rows_produced']:,} rows, "
              f"row_count_unchanged={report['row_count_unchanged']}, "
              f"labels_unchanged={report['labels_unchanged']}, "
              f"provenance_violations={report['provenance_violations']}")

    (RESULTS / f"{args.out_prefix}_manifest.json").write_text(
        json.dumps(all_reports, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
