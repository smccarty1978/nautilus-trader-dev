"""OOS pullback collector — CAUSAL regime-exit version.

Causal regime-exit logic (patched 2026-04-26):

1. regime_end_ts uses next_flip.flip_bar_ts_init (= 1m bar CLOSE,
   the moment the flip is detectable), NOT flip_bar_ts_event
   (= bar OPEN, ~60s before detection is possible).

2. regime_exit_price uses the 1m bar's close at regime_end_ts,
   NOT the 1s bar CLOSE at flip-bar OPEN time (~59s too early).

3. Trade-inclusion filters do NOT use future regime knowledge.
   Trade committed if regime intact at DECISION time
   (next_flip.ts_init > decision_ts). NEVER drop based on
   fill_ts vs regime_end_ts — live system can't retract.

Pre-2026-04-26 versions of this collector had non-causal logic
that inflated PnL by $40-72/trade. Outputs:
  - oos_confirmed_entries_<year>.parquet
  - oos_pullback_1atr_<year>.parquet
"""

from __future__ import annotations
import os, sys, time, argparse
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "studies/hmm_5s_v1"))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from hmm_pipeline import SimpleRegimeTracker  # noqa

OUT = Path("studies/pullback_entry_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
PULLBACK_THRESHOLD = 1.00
BRACKETS = [
    (1.00, 1.00), (1.25, 1.00), (1.50, 1.00), (2.00, 1.00),
    (1.00, 0.75), (1.50, 0.75),
]
MAX_HORIZON_S = 1800


def compute_atr_series(h, l, c, period=14):
    n = len(c)
    tr = np.empty(n, dtype=float)
    tr[0] = h[0] - l[0]
    prev_c = c[:-1]
    tr[1:] = np.maximum.reduce([
        h[1:] - l[1:], np.abs(h[1:] - prev_c), np.abs(l[1:] - prev_c)])
    atr = np.full(n, np.nan, dtype=float)
    if n < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def enumerate_flips_year(bars_1m_h, bars_1m_l, bars_1m_c, bars_1m_ts,
                            bars_1m_init, year_start_ns):
    """Enumerate raw 1m flips with both ts_event (OPEN) and ts_init
    (CLOSE) of the flip bar."""
    tracker = SimpleRegimeTracker()
    flips = []
    for i in range(len(bars_1m_c)):
        flipped = tracker.update(
            bars_1m_h[i], bars_1m_l[i], bars_1m_c[i])
        if flipped and bars_1m_ts[i] >= year_start_ns:
            flips.append({
                "flip_bar_idx": i,
                "flip_bar_ts_event": int(bars_1m_ts[i]),
                "flip_bar_ts_init": int(bars_1m_init[i]),
                "flip_bar_h": float(bars_1m_h[i]),
                "flip_bar_l": float(bars_1m_l[i]),
                "flip_bar_c": float(bars_1m_c[i]),  # 1m bar close
                "new_regime": int(tracker.regime),
            })
    df = pd.DataFrame(flips)
    if not len(df):
        return df
    confirmed = []
    for _, row in df.iterrows():
        idx = int(row["flip_bar_idx"])
        if idx + 1 >= len(bars_1m_c):
            confirmed.append(False)
            continue
        if row["new_regime"] == 1:
            confirmed.append(bool(bars_1m_h[idx + 1] > row["flip_bar_h"]))
        else:
            confirmed.append(bool(bars_1m_l[idx + 1] < row["flip_bar_l"]))
    df["hhll_confirmed"] = confirmed
    return df


def compute_outcomes_causal(seg_h, seg_l, seg_o, seg_c, seg_ts,
                              fill_price, atr, direction,
                              regime_end_ts, regime_end_price, fill_ts):
    """Causal compute_outcomes.

    regime_end_ts: ts_init of next opposing flip (= 1m bar CLOSE,
                   the moment of flip detection).
    regime_end_price: price at regime_end_ts = OPEN of 1s bar at
                     ts_event == regime_end_ts (= 1m bar CLOSE price).
                     Pre-computed to ensure we exit at the actual
                     causal price, not at a 1s bar close ~1s later.

    On each bracket: PT/SL race with intra-1s-bar resolution. If
    neither hits before regime_end_ts, exit at regime_end_price at
    regime_end_ts. If we run off the segment without resolution,
    exit at the last 1s close (timeout).
    """
    n = len(seg_h)
    if n == 0:
        return None
    if direction == 1:
        mfe_atr_seq = (seg_h - fill_price) / atr
        mae_atr_seq = (fill_price - seg_l) / atr
    else:
        mfe_atr_seq = (fill_price - seg_l) / atr
        mae_atr_seq = (seg_h - fill_price) / atr
    peak_mfe = np.maximum.accumulate(mfe_atr_seq)
    peak_mae = np.maximum.accumulate(mae_atr_seq)
    elapsed_s = (seg_ts - fill_ts) / 1e9

    # Causal regime exit: happens at the FIRST 1s bar with ts_event
    # >= regime_end_ts. The exit price is regime_end_price (1m close
    # at the moment of detection), passed in by the caller.
    re_idx = np.searchsorted(seg_ts, regime_end_ts, side="left")
    regime_in_window = re_idx < n

    out = {}
    for pt_R, sl_R in BRACKETS:
        pt_idx = (np.argmax(peak_mfe >= pt_R)
                    if (peak_mfe >= pt_R).any() else n + 1)
        sl_idx = (np.argmax(peak_mae >= sl_R)
                    if (peak_mae >= sl_R).any() else n + 1)

        events = []
        if pt_idx < n:
            events.append(("pt", pt_idx,
                            pt_R * atr * NQ_MULT - COMMISSION - TICK_COST,
                            fill_price + direction * pt_R * atr))
        if sl_idx < n:
            events.append(("sl", sl_idx,
                            -sl_R * atr * NQ_MULT - COMMISSION - 2 * TICK_COST,
                            fill_price - direction * sl_R * atr))
        if regime_in_window:
            re_pnl = ((regime_end_price - fill_price) * direction
                        * NQ_MULT - COMMISSION - TICK_COST)
            events.append(("regime", re_idx, re_pnl, regime_end_price))

        if not events:
            timeout_close = float(seg_c[-1])
            outcome = "timeout"
            pnl = ((timeout_close - fill_price) * direction * NQ_MULT
                     - COMMISSION - TICK_COST)
            res_s = float(elapsed_s[-1])
            exit_price = timeout_close
        else:
            events.sort(key=lambda x: x[1])
            outcome, idx, pnl, exit_price = events[0]
            res_s = float(elapsed_s[idx])

        tag = f"{int(pt_R*100)}_{int(sl_R*100)}"
        out[f"bracket_{tag}_outcome"] = outcome
        out[f"bracket_{tag}_pnl"] = pnl
        out[f"bracket_{tag}_resolution_s"] = res_s
        out[f"bracket_{tag}_exit_price"] = exit_price
    return out


def main(year: int):
    print("=" * 72)
    print(f"PULLBACK OOS COLLECTOR (CAUSAL) — YEAR {year}")
    print("=" * 72)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    print(f"\nLoading 1m bars ({year} + 30d warmup)...")
    bars_1m_nt = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC")
              - pd.Timedelta(days=30),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_1m_ts = np.array([b.ts_event for b in bars_1m_nt])
    bars_1m_init = np.array([b.ts_init for b in bars_1m_nt])
    bars_1m_h = np.array([float(b.high) for b in bars_1m_nt])
    bars_1m_l = np.array([float(b.low) for b in bars_1m_nt])
    bars_1m_c = np.array([float(b.close) for b in bars_1m_nt])
    print(f"  {len(bars_1m_nt):,} 1m bars")

    print("Computing ATR(14) series...")
    atr_series = compute_atr_series(bars_1m_h, bars_1m_l, bars_1m_c, 14)

    print(f"Enumerating raw 1m flips on {year}...")
    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    raw_flips = enumerate_flips_year(
        bars_1m_h, bars_1m_l, bars_1m_c, bars_1m_ts, bars_1m_init,
        year_start_ns)
    print(f"  Raw flips: {len(raw_flips):,}, "
           f"HH/LL confirmed: {int(raw_flips['hhll_confirmed'].sum()):,}")

    raw_flips = raw_flips.sort_values(
        "flip_bar_ts_event").reset_index(drop=True)
    # CAUSAL: next-flip exit timestamp uses ts_init (CLOSE), not
    # ts_event (OPEN). Also pre-compute next-flip CLOSE price.
    raw_flips["next_flip_ts_init"] = raw_flips[
        "flip_bar_ts_init"].shift(-1).fillna(
        raw_flips["flip_bar_ts_init"].max() + 30 * 24 * 3600 * int(1e9)
    ).astype("int64")
    raw_flips["next_flip_close_price"] = raw_flips[
        "flip_bar_c"].shift(-1).fillna(0.0)

    # RTH HH/LL confirmed
    import pytz
    CT = pytz.timezone("America/Chicago")
    flip_dts = pd.to_datetime(raw_flips["flip_bar_ts_event"],
                                 unit="ns", utc=True).dt.tz_convert(CT)
    flip_minutes = flip_dts.dt.hour * 60 + flip_dts.dt.minute
    rth_mask = (flip_minutes >= 510) & (flip_minutes < 900)
    pop = raw_flips[rth_mask & raw_flips["hhll_confirmed"]].copy()
    print(f"  RTH HH/LL confirmed: {len(pop):,}")

    print(f"\nLoading {year} 1s bars...")
    bars_1s_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC"),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_1s_nt])
    bars_h = np.array([float(b.high) for b in bars_1s_nt])
    bars_l = np.array([float(b.low) for b in bars_1s_nt])
    bars_o = np.array([float(b.open) for b in bars_1s_nt])
    bars_c = np.array([float(b.close) for b in bars_1s_nt])
    print(f"  {len(bars_1s_nt):,} 1s bars")

    confirmed_entries = []
    pullback_candidates = []
    skipped_no_atr = skipped_no_b1 = 0
    skipped_regime_already_dead_at_signal = 0
    skipped_regime_dead_at_decision = 0
    skipped_no_baseline_fill = 0
    t0 = time.time()

    for regime_id, row in pop.iterrows():
        flip_ts_event = int(row["flip_bar_ts_event"])
        d = int(row["new_regime"])
        next_flip_ts_init = int(row["next_flip_ts_init"])
        next_flip_close_price = float(row["next_flip_close_price"])
        flip_idx = int(row["flip_bar_idx"])

        if flip_idx + 1 >= len(bars_1m_c):
            skipped_no_b1 += 1
            continue
        b1_idx = flip_idx + 1
        atr = atr_series[b1_idx]
        if not np.isfinite(atr) or atr <= 0:
            skipped_no_atr += 1
            continue

        # signal_time = bar+1 close = bars_1m_init[b1_idx]
        signal_time = int(bars_1m_init[b1_idx])

        # CAUSAL filter: regime must be intact at signal_time. The
        # earliest possible next flip is bar+2 (since bar+1 confirmed
        # us). If next_flip_ts_init <= signal_time, the regime is
        # already known to have flipped — skip.
        # next_flip_ts_init <= signal_time means: next opposing flip
        # bar's CLOSE is at or before signal_time = bar+1 CLOSE.
        # That can only happen if next opposing flip bar IS bar+1
        # itself, which is impossible (HH/LL confirmation requires
        # bar+1 to make new HH/LL = same direction as flip).
        if next_flip_ts_init <= signal_time:
            skipped_regime_already_dead_at_signal += 1
            continue

        signal_price = float(bars_1m_c[b1_idx])

        # ----- Confirmed-entry baseline: signal-time entry -----
        # Decision at signal_time. CAUSAL filter: regime intact at
        # decision (next_flip_ts_init > decision_ts = signal_time).
        # We already checked above. No further filter on fill_ts
        # vs regime_end (live system can't predict).
        baseline_fill_target = signal_time + 30 * int(1e9)
        bf_idx = np.searchsorted(bars_ts, baseline_fill_target,
                                    side="left")
        if (bf_idx >= len(bars_ts)
                or bars_ts[bf_idx] - baseline_fill_target
                    > 60 * int(1e9)):
            # No 1s bar at fill time within slip cap — execution
            # impossible (no data, e.g., session boundary). Skip.
            skipped_no_baseline_fill += 1
            continue
        baseline_fill_ts = int(bars_ts[bf_idx])
        baseline_fill_price = float(bars_o[bf_idx])

        # Walk window: from fill to min(regime_end, fill + max_horizon)
        baseline_walk_end = min(
            next_flip_ts_init,
            baseline_fill_ts + MAX_HORIZON_S * int(1e9))
        bw_hi = np.searchsorted(bars_ts, baseline_walk_end,
                                  side="left")
        # Include the bar AT regime_end_ts so re_idx finds it
        # (we want exit AT the bar where ts_event == regime_end_ts)
        if (bw_hi < len(bars_ts)
                and bars_ts[bw_hi] == next_flip_ts_init):
            bw_hi += 1  # include the regime-exit bar
        bw_hi = min(bw_hi, len(bars_ts))
        baseline_outcomes = compute_outcomes_causal(
            bars_h[bf_idx:bw_hi], bars_l[bf_idx:bw_hi],
            bars_o[bf_idx:bw_hi], bars_c[bf_idx:bw_hi],
            bars_ts[bf_idx:bw_hi],
            baseline_fill_price, atr, d,
            next_flip_ts_init, next_flip_close_price,
            baseline_fill_ts)
        if baseline_outcomes is None:
            skipped_no_baseline_fill += 1
            continue
        regime_dur_s = (next_flip_ts_init - signal_time) / 1e9
        confirmed_row = {
            "regime_id": int(regime_id),
            "flip_bar_ts_event": flip_ts_event,
            "signal_time_ts": signal_time,
            "signal_price": signal_price,
            "direction": d,
            "atr_at_signal": atr,
            "regime_end_ts": next_flip_ts_init,
            "regime_end_price": next_flip_close_price,
            "regime_duration_s": regime_dur_s,
            "fill_ts": baseline_fill_ts,
            "fill_price": baseline_fill_price,
        }
        confirmed_row.update(baseline_outcomes)
        confirmed_entries.append(confirmed_row)

        # ----- Pullback detection -----
        # Walk 1s bars in regime window for pullback detection
        walk_end_ts = min(next_flip_ts_init,
                            signal_time + MAX_HORIZON_S * int(1e9))
        lo = np.searchsorted(bars_ts, signal_time, side="left")
        hi = np.searchsorted(bars_ts, walk_end_ts, side="left")
        if hi <= lo:
            continue
        seg_h = bars_h[lo:hi]
        seg_l = bars_l[lo:hi]
        seg_o = bars_o[lo:hi]
        seg_c = bars_c[lo:hi]
        seg_ts = bars_ts[lo:hi]

        if d == 1:
            running_peak = np.maximum.accumulate(seg_h)
            pullback_depth = (running_peak - seg_l) / atr
            max_progress_so_far = (running_peak - signal_price) / atr
        else:
            running_peak = np.minimum.accumulate(seg_l)
            pullback_depth = (seg_h - running_peak) / atr
            max_progress_so_far = (signal_price - running_peak) / atr

        cross_mask = pullback_depth >= PULLBACK_THRESHOLD
        if not cross_mask.any():
            continue
        cross_idx = int(np.argmax(cross_mask))
        cross_ts = int(seg_ts[cross_idx])
        elapsed_at_cross = (cross_ts - signal_time) // int(1e9)
        decision_offset_s = ((elapsed_at_cross + 29) // 30) * 30
        if decision_offset_s == 0:
            decision_offset_s = 30
        decision_ts = signal_time + decision_offset_s * int(1e9)
        fill_ts_target = decision_ts + 30 * int(1e9)

        # CAUSAL filter: regime intact at DECISION time only.
        # next_flip_ts_init > decision_ts (regime not yet detected
        # as flipped at the moment we make the decision).
        # NO filter on fill_ts vs regime_end (live system commits
        # at decision and cannot retract before fill).
        if next_flip_ts_init <= decision_ts:
            skipped_regime_dead_at_decision += 1
            continue

        # Get fill bar (first 1s bar at or after fill_ts_target)
        fill_idx_global = np.searchsorted(
            bars_ts, fill_ts_target, side="left")
        if fill_idx_global >= len(bars_ts):
            continue
        actual_fill_ts = int(bars_ts[fill_idx_global])
        if actual_fill_ts - fill_ts_target > 60 * int(1e9):
            # Data gap — order can't fill within slip cap. Skip.
            continue
        fill_price = float(bars_o[fill_idx_global])
        time_since_signal_s = (decision_ts - signal_time) / 1e9

        walk_end = min(
            next_flip_ts_init,
            actual_fill_ts + MAX_HORIZON_S * int(1e9))
        walk_hi = np.searchsorted(bars_ts, walk_end, side="left")
        if (walk_hi < len(bars_ts)
                and bars_ts[walk_hi] == next_flip_ts_init):
            walk_hi += 1
        walk_hi = min(walk_hi, len(bars_ts))
        walk_lo = fill_idx_global
        outcomes = compute_outcomes_causal(
            bars_h[walk_lo:walk_hi], bars_l[walk_lo:walk_hi],
            bars_o[walk_lo:walk_hi], bars_c[walk_lo:walk_hi],
            bars_ts[walk_lo:walk_hi],
            fill_price, atr, d,
            next_flip_ts_init, next_flip_close_price,
            actual_fill_ts)
        if outcomes is None:
            continue
        pb_row = {
            "regime_id": int(regime_id),
            "flip_bar_ts_event": flip_ts_event,
            "signal_time_ts": signal_time,
            "direction": d,
            "atr_at_signal": atr,
            "regime_end_ts": next_flip_ts_init,
            "regime_end_price": next_flip_close_price,
            "regime_duration_s": regime_dur_s,
            "threshold_cross_ts": cross_ts,
            "decision_ts": int(decision_ts),
            "fill_ts": actual_fill_ts,
            "fill_price": fill_price,
            "time_since_signal_s": time_since_signal_s,
            "max_progress_before_pullback_atr": float(
                max_progress_so_far[cross_idx]),
        }
        pb_row.update(outcomes)
        pullback_candidates.append(pb_row)

    elapsed = time.time() - t0
    print(f"  Walked {len(pop):,} regimes in {elapsed:.0f}s")
    print(f"  Skipped: no_atr={skipped_no_atr}, no_b1={skipped_no_b1}, "
           f"regime_already_dead_at_signal="
           f"{skipped_regime_already_dead_at_signal}, "
           f"regime_dead_at_decision={skipped_regime_dead_at_decision}, "
           f"no_baseline_fill={skipped_no_baseline_fill}")
    print(f"  Confirmed-entry baseline rows: {len(confirmed_entries):,}")
    print(f"  Pullback-entry rows (1.0 ATR): "
           f"{len(pullback_candidates):,}")

    df_ce = pd.DataFrame(confirmed_entries)
    df_pb = pd.DataFrame(pullback_candidates)
    df_ce.to_parquet(
        OUT / f"oos_confirmed_entries_{year}.parquet", index=False)
    df_pb.to_parquet(
        OUT / f"oos_pullback_1atr_{year}.parquet", index=False)
    print(f"\nSaved:")
    print(f"  {OUT / f'oos_confirmed_entries_{year}.parquet'}")
    print(f"  {OUT / f'oos_pullback_1atr_{year}.parquet'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    main(args.year)
