"""Phase 3 (part A) - Attach the 56 ohlcv+price features to the mirrored
LONG surface by live-replaying raw 1s/1m bars through the SAME
OHLCVDeltaTracker / PriceLevelTracker classes used for the short side.

Fork of
`studies/ohlcv_volume_delta_price_level_features/attach_features.py:run_year`.
THREE behavioral changes vs the upstream short-side attach; everything else
(minute bucketing, regime/RTH reset ordering, buffer-and-replay minute
finalization) is identical:

    upstream short side                           long mirror
    -------------------                           -----------
 1. surface = labeled_featured_{year} (dir==+1)   surface = surface_long_{year} (dir==-1)
 2. price_tracker.calculate(..., direction=-1)    price_tracker.calculate(..., direction=+1)
 3. snap = searchsorted(ts, obs, "right")-1       snap = searchsorted(ts, obs, "left")-1
    (INCLUSIVE of bar_ts==obs)                    (STRICTLY BEFORE obs)

Change 3 fixes a 1-second look-ahead present in the upstream attach and
INHERITED by the deployed short-side model: raw 1s bars are open-labelled
(ts_event=t covers [t, t+1s); see CODEX_5_X_run_established_fade.py:3-4), so a
bar with ts_event==observation_time is still FORMING at the observation instant.
The atlas's own checkpoint builder uses the strict convention
(build_weakness_atlas.py:96 `searchsorted(..., side='left')-1`; W4 merge asserts
`feature_bar_ts_event < observation_time`). This fork matches the atlas so all
100 features share one causal convention: latest source bar strictly before
observation_time. The provenance check below is tightened to strict `>=`.
`direction` only affects PriceLevelTracker._direction_normalized (ahead/behind);
of the top-100 that is exactly one feature (`pct_levels_behind_trade`). The
OHLCV tracker call takes no direction argument on either side (absolute).
`minute_bucket_key` is imported from the original module (not re-typed) so the
CRIT-1 minute-bucketing fix cannot silently drift.
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
STUDY = HERE.parent
ROOT = STUDY.parents[1]
WORK, RESULTS = STUDY / "_work", STUDY / "results"
for d in (WORK, RESULTS):
    d.mkdir(parents=True, exist_ok=True)

FEAT_DIR = ROOT / "studies" / "ohlcv_volume_delta_price_level_features"
for p in (ROOT, FEAT_DIR,
          ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, is_rth, validate_raw_bars,
)
from features.trackers.ohlcv_delta import OHLCVDeltaTracker  # noqa: E402
from features.trackers.price_levels import PriceLevelTracker  # noqa: E402
import attach_features as AF  # noqa: E402  (reuse minute_bucket_key verbatim)

NS = 1_000_000_000
LONG_DIRECTION = +1  # <-- change 2: long entry (short side used -1)


def surface_path(year: int) -> Path:
    return WORK / f"surface_long_{year}.parquet"  # <-- change 1: mirrored surface


def run_year(year: int) -> dict:
    t0 = time.time()
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)

    surface = pd.read_parquet(surface_path(year))
    surface = surface.sort_values(["regime_start_ns", "observation_time"]).reset_index(drop=True)
    original_row_count = len(surface)

    timeline = canonical_regime_timeline(year, raw)
    regime_starts = np.sort(timeline["regime_start_ns"].to_numpy(np.int64))

    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)
    closes = raw["close"].to_numpy(float)
    vols = raw["volume"].to_numpy(float)

    obs_times = surface["observation_time"].to_numpy(np.int64)
    # Change 3: strictly-before snap (last COMPLETED open-labelled bar). The last
    # completed bar at obs is ts_event == obs-1s; a gap exists when the snapped
    # bar is earlier than that.
    snap_idx = np.searchsorted(ts, obs_times, side="left") - 1
    valid = snap_idx >= 0
    snapped_ts = ts[np.clip(snap_idx, 0, len(ts) - 1)]
    n_contiguous = int(((snapped_ts == obs_times - NS) & valid).sum())
    gap_snapped = int(valid.sum() - n_contiguous)

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

    reg_idx = -1
    if len(regime_starts) and int(regime_starts[0]) <= int(ts[0]):
        reg_idx = int(np.searchsorted(regime_starts, ts[0], side="right")) - 1
        close_i = int(np.searchsorted(ts, regime_starts[reg_idx], side="left"))
        if close_i < len(ts) and int(ts[close_i]) == int(regime_starts[reg_idx]):
            confirming_bucket = AF.minute_bucket_key(int(regime_starts[reg_idx]))
            start_i = close_i
            while start_i > 0 and AF.minute_bucket_key(int(ts[start_i - 1])) == confirming_bucket:
                start_i -= 1
            ohlcv_tracker.reset_regime(int(regime_starts[reg_idx]), float(opens[start_i]))

    was_rth = False
    current_minute = None
    minute_o = minute_h = minute_l = prev_close = None
    minute_buffer: list[tuple[int, float, float, float, float]] = []
    last_finalized_1m_close_ts = None

    records = []
    n = len(ts)
    for i in range(n):
        bar_ts = int(ts[i])
        b_est = ohlcv_tracker.update(bar_ts, opens[i], highs[i], lows[i], closes[i], vols[i])

        minute_key = AF.minute_bucket_key(bar_ts)
        if current_minute is None:
            current_minute = minute_key
            minute_o, minute_h, minute_l = opens[i], highs[i], lows[i]
            minute_buffer = [(bar_ts, highs[i], lows[i], vols[i], b_est["bar_est_delta"])]
        elif minute_key != current_minute:
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
                f_ohlcv = ohlcv_tracker.calculate(atr=atr)
                f_price = price_tracker.calculate(bar_ts, closes[i], atr, direction=LONG_DIRECTION)
                rec = {"regime_start_ns": regime_start_ns, "observation_time": obs_time,
                       "latest_source_ts_used": bar_ts,
                       "latest_1m_bar_close_ts_used": last_finalized_1m_close_ts}
                rec.update(f_ohlcv)
                rec.update(f_price)
                records.append(rec)

    if minute_buffer:
        for buf_ts, buf_high, buf_low, buf_vol, buf_delta in minute_buffer:
            ohlcv_tracker.accumulate_regime_rth(buf_ts, buf_high, buf_low, buf_vol, buf_delta)

    feat_df = pd.DataFrame(records)
    merged = surface.merge(feat_df, on=["regime_start_ns", "observation_time"],
                           how="left", validate="one_to_one")
    # Strict causal invariant (matches atlas W4 merge): the latest source bar
    # used must be STRICTLY before observation_time (>= is a look-ahead).
    dq_violations = int((merged["latest_source_ts_used"] >= merged["observation_time"]).sum())

    out_path = WORK / f"attached_long_{year}.parquet"
    merged.to_parquet(out_path, index=False, compression="zstd")

    return {
        "year": year, "runtime_s": round(time.time() - t0, 1),
        "raw_bars_processed": n, "surface_rows": original_row_count,
        "feature_rows_produced": len(feat_df),
        "row_count_unchanged": original_row_count == len(merged),
        "gap_snapped_checkpoints": gap_snapped,
        "unmatched_before_data_start": unmatched_before_data,
        "duplicate_rows": int(merged.duplicated(["regime_start_ns", "observation_time"]).sum()),
        "provenance_violations": dq_violations,
        "output_path": str(out_path), "output_sha256": sha256_file(out_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+",
                    default=[2021, 2022, 2023, 2024, 2025, 2026])
    args = ap.parse_args()
    reports = {}
    for y in args.years:
        reports[y] = run_year(y)
        r = reports[y]
        print(f"[{y}] {r['runtime_s']}s rows={r['surface_rows']:,} "
              f"row_count_unchanged={r['row_count_unchanged']} "
              f"provenance_violations={r['provenance_violations']}")
    (RESULTS / "phase3_attach_manifest.json").write_text(
        json.dumps({"generator_sha256": sha256_file(Path(__file__).resolve()),
                    "direction": LONG_DIRECTION, "years": reports}, indent=2, default=str),
        encoding="utf-8")


if __name__ == "__main__":
    main()
