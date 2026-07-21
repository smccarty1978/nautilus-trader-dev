"""Confirmed Regime Pullback Entry Study v1 — collector (CAUSAL).

Causal regime-exit logic (patched 2026-04-26):
  - regime_end_ts = next_flip.flip_bar_ts_init (= 1m bar CLOSE,
    moment of detection), NOT flip_bar_ts_event (= bar OPEN).
  - regime_exit_price = next_flip 1m bar close, NOT 1s bar close
    at flip-bar OPEN time.
  - Trade-inclusion filters do NOT use future regime knowledge.
    Trade committed if regime intact at DECISION time only.

For each HH/LL-confirmed RTH 1m regime flip on 2025:
  - signal_time = bar+1 close (= flip_bar_ts_init + 60s)
  - atr_at_signal = 1m ATR(14) after bar+1 close
  - regime_end_ts = ts_init of next opposing 1m flip
  - regime_end_price = 1m close of next opposing flip bar

Walk 1s bars from signal_time forward, tracking running favorable
extreme. On first crossing of each pullback threshold (0.25, 0.50,
0.75, 1.00 ATR retrace from peak), snap decision to next 30s
checkpoint anchored at signal_time. Fill at decision + 30s. Skip
ONLY if regime is already known flipped at decision time.

Compute features at decision_time (no lookahead), outcomes from fill
forward (6 brackets + actual regime-exit + path quality).

Pre-2026-04-26 versions of this collector had non-causal logic
that inflated PnL by $40-72/trade. Outputs:
  - pullback_candidates_2025.parquet
  - matched_baseline_2025.parquet
"""

from __future__ import annotations
import os, sys, time, pickle
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "studies/hmm_5s_v1"))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from hmm_pipeline import (  # noqa
    SimpleRegimeTracker, compute_5s_features, FEATURE_COLS,
    aggregate_1s_to_5s,
)

OUT = Path("studies/pullback_entry_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
PULLBACK_THRESHOLDS_ATR = [0.25, 0.50, 0.75, 1.00]
BRACKETS = [
    (1.00, 1.00), (1.25, 1.00), (1.50, 1.00), (2.00, 1.00),
    (1.00, 0.75), (1.50, 0.75),
]
MAX_HORIZON_S = 1800  # 30 min cap
PATH_WINDOWS_S = [120, 300, 600]


# ---------------------------------------------------------------
# 1. Pre-compute ATR(14) series for every 2025 1m bar (Wilder)
# ---------------------------------------------------------------

def compute_atr_series(bars_1m_h, bars_1m_l, bars_1m_c, period=14):
    n = len(bars_1m_c)
    tr = np.empty(n, dtype=float)
    tr[0] = bars_1m_h[0] - bars_1m_l[0]
    prev_c = bars_1m_c[:-1]
    tr[1:] = np.maximum.reduce([
        bars_1m_h[1:] - bars_1m_l[1:],
        np.abs(bars_1m_h[1:] - prev_c),
        np.abs(bars_1m_l[1:] - prev_c),
    ])
    atr = np.full(n, np.nan, dtype=float)
    if n < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ---------------------------------------------------------------
# 2. Compute outcomes from fill (6 brackets + regime + path)
# ---------------------------------------------------------------

def compute_outcomes(seg_h, seg_l, seg_c, seg_ts, fill_price, atr,
                       direction, regime_end_ts, regime_end_price,
                       fill_ts):
    """Return dict of outcome features for one entry. CAUSAL.

    regime_end_ts: ts_init of next opposing flip (= 1m bar CLOSE).
    regime_end_price: 1m close at regime_end_ts (price at moment
                     of detection — passed in by caller).
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

    # Causal regime exit: first 1s bar with ts_event >= regime_end_ts
    # (= 1m bar CLOSE = moment of detection). Exit price = 1m close
    # passed in as regime_end_price.
    re_idx_search = np.searchsorted(seg_ts, regime_end_ts, side="left")
    regime_in_window = re_idx_search < n

    out = {}
    for pt_R, sl_R in BRACKETS:
        pt_idx = (np.argmax(peak_mfe >= pt_R)
                    if (peak_mfe >= pt_R).any() else n + 1)
        sl_idx = (np.argmax(peak_mae >= sl_R)
                    if (peak_mae >= sl_R).any() else n + 1)

        events = []
        if pt_idx < n:
            events.append(("pt", pt_idx,
                            pt_R * atr * NQ_MULT - COMMISSION - TICK_COST))
        if sl_idx < n:
            events.append(("sl", sl_idx,
                            -sl_R * atr * NQ_MULT - COMMISSION - 2 * TICK_COST))
        if regime_in_window:
            re_pnl = ((regime_end_price - fill_price) * direction
                        * NQ_MULT - COMMISSION - TICK_COST)
            events.append(("regime", re_idx_search, re_pnl))

        if not events:
            timeout_close = float(seg_c[-1])
            outcome = "timeout"
            pnl = ((timeout_close - fill_price) * direction * NQ_MULT
                     - COMMISSION - TICK_COST)
            res_s = float(elapsed_s[-1])
        else:
            events.sort(key=lambda x: x[1])
            outcome, idx, pnl = events[0]
            res_s = float(elapsed_s[idx])

        tag = f"{int(pt_R*100)}_{int(sl_R*100)}"
        out[f"bracket_{tag}_outcome"] = outcome
        out[f"bracket_{tag}_pnl"] = pnl
        out[f"bracket_{tag}_resolution_s"] = res_s
        out[f"bracket_{tag}_pt_t"] = (float(elapsed_s[pt_idx])
                                          if pt_idx < n else float("nan"))
        out[f"bracket_{tag}_sl_t"] = (float(elapsed_s[sl_idx])
                                          if sl_idx < n else float("nan"))

    # Regime-exit-only outcome (hold to regime exit). CAUSAL: exit
    # at regime_end_price, not at 1s bar CLOSE.
    if regime_in_window:
        re_idx = min(re_idx_search, n - 1)
        regime_exit_pnl = ((regime_end_price - fill_price) * direction
                            * NQ_MULT - COMMISSION - TICK_COST)
        regime_exit_atr = ((regime_end_price - fill_price) * direction) / atr
        regime_exit_t = float(elapsed_s[re_idx])
        re_mfe = float(peak_mfe[re_idx])
        re_mae = float(peak_mae[re_idx])
        out["regime_exit_in_window"] = True
        out["regime_exit_t"] = regime_exit_t
    else:
        timeout_close = float(seg_c[-1])
        regime_exit_pnl = ((timeout_close - fill_price) * direction
                            * NQ_MULT - COMMISSION - TICK_COST)
        regime_exit_atr = ((timeout_close - fill_price) * direction) / atr
        re_mfe = float(peak_mfe[-1])
        re_mae = float(peak_mae[-1])
        out["regime_exit_in_window"] = False
        out["regime_exit_t"] = float(elapsed_s[-1])

    out["regime_exit_pnl"] = regime_exit_pnl
    out["regime_exit_atr"] = regime_exit_atr
    out["mfe_to_regime_exit_atr"] = re_mfe
    out["mae_to_regime_exit_atr"] = re_mae

    # Path-quality features — MFE/MAE in fixed time windows
    for w in PATH_WINDOWS_S:
        mask = elapsed_s <= w
        if mask.any():
            mfe_w = float(peak_mfe[mask][-1])
            mae_w = float(peak_mae[mask][-1])
        else:
            mfe_w = float("nan")
            mae_w = float("nan")
        out[f"mfe_{w}s_atr"] = mfe_w
        out[f"mae_{w}s_atr"] = mae_w

    # Path-quality flags
    mfe_300 = out["mfe_300s_atr"]
    mae_300 = out["mae_300s_atr"]
    mfe_60 = (float(peak_mfe[elapsed_s <= 60][-1])
                  if (elapsed_s <= 60).any() else float("nan"))
    mae_60 = (float(peak_mae[elapsed_s <= 60][-1])
                  if (elapsed_s <= 60).any() else float("nan"))
    out["clean_path_300s"] = bool(
        not np.isnan(mfe_300) and mfe_300 >= 0.5
        and not np.isnan(mae_300) and mae_300 < 0.5)
    out["fast_fail_60s"] = bool(
        not np.isnan(mae_60) and mae_60 >= 0.5)

    # stall_then_reverse_180s: max MFE within 120s < 0.25 then went
    # adverse by 180s (mae_180 > 0.5)
    mfe_120 = (float(peak_mfe[elapsed_s <= 120][-1])
                  if (elapsed_s <= 120).any() else float("nan"))
    mae_180 = (float(peak_mae[elapsed_s <= 180][-1])
                  if (elapsed_s <= 180).any() else float("nan"))
    out["stall_then_reverse_180s"] = bool(
        not np.isnan(mfe_120) and mfe_120 < 0.25
        and not np.isnan(mae_180) and mae_180 >= 0.5)

    return out


# ---------------------------------------------------------------
# 3. Main collector
# ---------------------------------------------------------------

def main():
    print("=" * 72)
    print("PULLBACK ENTRY STUDY v1 — COLLECTOR")
    print("=" * 72)

    # ----- Load 1m bars with warmup, build ATR series + ts index -----
    print("\nLoading 1m bars (2025 + 30d warmup)...")
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1m_nt = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-01", tz="UTC")
              - pd.Timedelta(days=30),
        end=pd.Timestamp("2025-12-31 23:59:59", tz="UTC"))
    bars_1m_ts = np.array([b.ts_event for b in bars_1m_nt])  # OPEN time
    bars_1m_init = np.array([b.ts_init for b in bars_1m_nt])  # CLOSE time
    bars_1m_h = np.array([float(b.high) for b in bars_1m_nt])
    bars_1m_l = np.array([float(b.low) for b in bars_1m_nt])
    bars_1m_c = np.array([float(b.close) for b in bars_1m_nt])
    print(f"  {len(bars_1m_nt):,} 1m bars")

    print("Computing ATR(14) series (Wilder)...")
    atr_series = compute_atr_series(bars_1m_h, bars_1m_l, bars_1m_c, 14)

    # ----- Enumerate 2025 raw 1m flips inline with ts_init access -----
    # Re-derive HH/LL labels and store flip_bar_ts_init for causal
    # regime-exit timing.
    print("Enumerating raw 1m flips inline...")
    tracker = SimpleRegimeTracker()
    flips = []
    year_start_ns = pd.Timestamp("2025-01-01", tz="UTC").value
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
                "flip_bar_c": float(bars_1m_c[i]),
                "new_regime": int(tracker.regime),
            })
    raw_flips = pd.DataFrame(flips)
    confirmed = []
    for _, row in raw_flips.iterrows():
        idx = int(row["flip_bar_idx"])
        if idx + 1 >= len(bars_1m_c):
            confirmed.append(False)
            continue
        if row["new_regime"] == 1:
            confirmed.append(bool(bars_1m_h[idx + 1] > row["flip_bar_h"]))
        else:
            confirmed.append(bool(bars_1m_l[idx + 1] < row["flip_bar_l"]))
    raw_flips["hhll_confirmed"] = confirmed
    print(f"  Raw flips: {len(raw_flips):,}, "
           f"HH/LL confirmed: {int(raw_flips['hhll_confirmed'].sum()):,}")

    # CAUSAL: next-flip exit timestamp uses ts_init (CLOSE), and
    # next-flip CLOSE price for the exit price.
    raw_flips = raw_flips.sort_values(
        "flip_bar_ts_event").reset_index(drop=True)
    raw_flips["next_flip_ts_init"] = raw_flips[
        "flip_bar_ts_init"].shift(-1).fillna(
        raw_flips["flip_bar_ts_init"].max() + 30 * 24 * 3600 * int(1e9)
    ).astype("int64")
    raw_flips["next_flip_close_price"] = raw_flips[
        "flip_bar_c"].shift(-1).fillna(0.0)

    # ----- Filter to RTH HH/LL confirmed -----
    import pytz
    CT = pytz.timezone("America/Chicago")
    flip_dts = pd.to_datetime(raw_flips["flip_bar_ts_event"],
                                 unit="ns", utc=True).dt.tz_convert(CT)
    flip_minutes = flip_dts.dt.hour * 60 + flip_dts.dt.minute
    rth_mask = (flip_minutes >= 510) & (flip_minutes < 900)
    pop = raw_flips[rth_mask & raw_flips["hhll_confirmed"]].copy()
    print(f"  RTH HH/LL confirmed: {len(pop):,}")

    # ----- Load 1s bars for forward walks + fill prices -----
    print("\nLoading 2025 1s bars...")
    bars_1s_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-01", tz="UTC"),
        end=pd.Timestamp("2025-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_1s_nt])
    bars_h = np.array([float(b.high) for b in bars_1s_nt])
    bars_l = np.array([float(b.low) for b in bars_1s_nt])
    bars_o = np.array([float(b.open) for b in bars_1s_nt])
    bars_c = np.array([float(b.close) for b in bars_1s_nt])
    print(f"  {len(bars_1s_nt):,} 1s bars")

    # ----- HMM state series for 2025 -----
    print("\nLoading HMM model + computing 2025 5s state series...")
    with open("studies/hmm_5s_v1/results/hmm_model.pkl", "rb") as f:
        hmm_data = pickle.load(f)
    model = hmm_data["model"]
    means = hmm_data["means"]
    stds = hmm_data["stds"]
    feat_cols = hmm_data["feature_cols"]

    # Aggregate 1s -> 5s, compute features, predict states
    df_1s = pd.DataFrame({
        "ts_event": bars_ts, "open": bars_o, "high": bars_h,
        "low": bars_l, "close": bars_c,
        "volume": [float(b.volume) if hasattr(b, "volume") else 0.0
                    for b in bars_1s_nt],
    })
    df_5s = aggregate_1s_to_5s(df_1s)
    feats_5s = compute_5s_features(df_5s)
    X = feats_5s[feat_cols].fillna(0.0).values
    valid = feats_5s[feat_cols].notna().all(axis=1).values
    X_norm = (X - means) / stds
    states_5s = model.predict(X_norm)
    states_5s_ts = feats_5s["ts_event_ns"].values.astype("int64")
    # Mark invalid as -1
    states_5s = np.where(valid, states_5s, -1).astype("int64")
    print(f"  {len(states_5s):,} 5s state values")

    # CAUSAL HMM lookup: states_5s[i] uses full 5s bar i; bar
    # closes at ts_event + 5s.
    states_5s_close_ts = states_5s_ts + 5 * int(1e9)

    def hmm_state_at(ts_ns: int) -> int:
        idx = int(np.searchsorted(
            states_5s_close_ts, ts_ns, side="right")) - 1
        if idx < 0:
            return -1
        return int(states_5s[idx])

    # ----- Walk pop and emit candidate rows + matched baselines -----
    print(f"\nWalking {len(pop):,} regimes...")
    pullback_rows = []
    baseline_rows = []
    skipped_no_atr = skipped_no_b1 = skipped_short_regime = 0
    t0 = time.time()

    for regime_id, row in pop.iterrows():
        flip_ts_event = int(row["flip_bar_ts_event"])
        flip_ts_init = int(row["flip_bar_ts_init"])
        d = int(row["new_regime"])
        # CAUSAL: next opposing flip's CLOSE time (= moment of detection)
        # and CLOSE price (= price at moment of detection).
        regime_end_ts = int(row["next_flip_ts_init"])
        regime_end_price = float(row["next_flip_close_price"])

        # bar+1: 1m bar starting at flip_ts_init (open=flip_ts_init)
        b1_idx = np.searchsorted(bars_1m_ts, flip_ts_init, side="left")
        if (b1_idx >= len(bars_1m_ts)
                or bars_1m_ts[b1_idx] != flip_ts_init):
            skipped_no_b1 += 1
            continue
        atr = atr_series[b1_idx]
        if not np.isfinite(atr) or atr <= 0:
            skipped_no_atr += 1
            continue

        # signal_time = bar+1 close = flip_ts_init + 60s
        signal_time = flip_ts_init + 60 * int(1e9)

        # CAUSAL filter: if the regime is already known to have flipped
        # by signal_time, skip. (Edge case — bar+1 confirmation
        # generally precludes this.)
        if regime_end_ts <= signal_time:
            skipped_short_regime += 1
            continue

        # Walk 1s bars from signal_time to min(regime_end_ts,
        # signal_time + MAX_HORIZON_S). For pullback detection we
        # only care about extremes within the regime.
        walk_end_ts = min(regime_end_ts,
                            signal_time + MAX_HORIZON_S * int(1e9))
        lo = np.searchsorted(bars_ts, signal_time, side="left")
        hi = np.searchsorted(bars_ts, walk_end_ts, side="left")
        if hi <= lo:
            skipped_short_regime += 1
            continue
        seg_h = bars_h[lo:hi]
        seg_l = bars_l[lo:hi]
        seg_o = bars_o[lo:hi]
        seg_c = bars_c[lo:hi]
        seg_ts = bars_ts[lo:hi]

        # Signal price = bar+1 close = first 1s bar at signal_time's
        # open price (or use bar+1's close from 1m). Use 1m close.
        signal_price = float(bars_1m_c[b1_idx])

        # Running favorable extreme (for long: cumulative max of high;
        # for short: cumulative min of low)
        if d == 1:
            running_peak = np.maximum.accumulate(seg_h)
            pullback_depth = running_peak - seg_h  # but vs current price
            # pullback_depth_atr at each bar = (peak - current_low) / atr
            # Use seg_l for "current price" since pullback hits via low
            pullback_depth = (running_peak - seg_l) / atr
            max_progress_so_far = (running_peak - signal_price) / atr
            current_progress = (seg_c - signal_price) / atr
            adverse_extreme_seq = np.minimum.accumulate(seg_l)
            adverse_vs_signal = adverse_extreme_seq < signal_price
        else:
            running_peak = np.minimum.accumulate(seg_l)
            pullback_depth = (seg_h - running_peak) / atr
            max_progress_so_far = (signal_price - running_peak) / atr
            current_progress = (signal_price - seg_c) / atr
            adverse_extreme_seq = np.maximum.accumulate(seg_h)
            adverse_vs_signal = adverse_extreme_seq > signal_price

        elapsed_s = (seg_ts - signal_time) / 1e9

        # State at signal time
        state_at_signal = hmm_state_at(signal_time)

        # ---------- Build matched baseline row (signal-time entry) -----
        # Only emit baseline rows for thresholds the regime DOES reach.
        # We add to baseline_rows after threshold loop.

        thresholds_reached = []  # list of (threshold, decision_ts, fill_ts, decision_idx_in_seg, fill_idx_in_seg)
        for thresh in PULLBACK_THRESHOLDS_ATR:
            cross_mask = pullback_depth >= thresh
            if not cross_mask.any():
                continue
            cross_idx = int(np.argmax(cross_mask))
            cross_ts = int(seg_ts[cross_idx])
            # Snap to next 30s checkpoint anchored at signal_time
            elapsed_at_cross = (cross_ts - signal_time) // int(1e9)
            decision_offset_s = ((elapsed_at_cross + 29) // 30) * 30
            if decision_offset_s == 0:
                decision_offset_s = 30  # min wait
            decision_ts = signal_time + decision_offset_s * int(1e9)
            fill_ts_target = decision_ts + 30 * int(1e9)
            # CAUSAL filter: only check regime intact at DECISION time.
            # Live system commits at decision and CANNOT retract before
            # fill — never filter on fill_ts vs regime_end.
            if regime_end_ts <= decision_ts:
                continue
            # Get actual fill: first 1s bar at or after fill_ts_target
            fill_idx_global = np.searchsorted(
                bars_ts, fill_ts_target, side="left")
            if fill_idx_global >= len(bars_ts):
                continue
            actual_fill_ts = int(bars_ts[fill_idx_global])
            # Slip cap 60s — data gap, can't fill
            if actual_fill_ts - fill_ts_target > 60 * int(1e9):
                continue
            fill_price = float(bars_o[fill_idx_global])
            # decision idx in seg (for feature snap)
            decision_idx_in_seg = np.searchsorted(
                seg_ts, decision_ts, side="right") - 1
            if decision_idx_in_seg < 0:
                continue

            # ----- Snap features at decision_ts (no lookahead) -----
            feat = {
                "regime_id": int(regime_id),
                "flip_bar_ts_event": flip_ts_event,
                "flip_bar_ts_init": flip_ts_init,
                "signal_time_ts": int(signal_time),
                "signal_price": signal_price,
                "direction": d,
                "atr_at_signal": atr,
                "regime_end_ts": regime_end_ts,
                "pullback_threshold_atr": thresh,
                "threshold_cross_ts": cross_ts,
                "decision_ts": int(decision_ts),
                "fill_ts": actual_fill_ts,
                "fill_price": fill_price,
                "fill_slip_s": (actual_fill_ts - fill_ts_target) / 1e9,
                "time_since_signal_s": (decision_ts - signal_time) / 1e9,
                "pullback_depth_atr": float(pullback_depth[
                    decision_idx_in_seg]),
                "max_progress_before_pullback_atr": float(
                    max_progress_so_far[decision_idx_in_seg]),
                "current_progress_atr": float(current_progress[
                    decision_idx_in_seg]),
                "adverse_extreme_vs_signal": bool(adverse_vs_signal[
                    decision_idx_in_seg]),
                "state_at_signal": state_at_signal,
                "state_at_decision": hmm_state_at(int(decision_ts)),
                "state_30s_before_decision": hmm_state_at(
                    int(decision_ts) - 30 * int(1e9)),
            }
            # pullback_speed: depth / time-since-peak
            # Find time of running peak prior to cross_idx
            if d == 1:
                peak_idx = int(np.argmax(seg_h[:cross_idx + 1]))
            else:
                peak_idx = int(np.argmin(seg_l[:cross_idx + 1]))
            time_since_peak_s = max(
                1.0, (seg_ts[cross_idx] - seg_ts[peak_idx]) / 1e9)
            feat["pullback_speed_atr_per_min"] = (
                feat["pullback_depth_atr"] / (time_since_peak_s / 60.0))
            feat["state_at_raw_flip"] = hmm_state_at(flip_ts_event)
            feat["hmm_state_changed_since_signal"] = (
                feat["state_at_decision"] != feat["state_at_signal"]
                and feat["state_at_decision"] >= 0
                and feat["state_at_signal"] >= 0)
            feat["hmm_recent_transition_flag"] = (
                feat["state_at_decision"] !=
                  feat["state_30s_before_decision"]
                and feat["state_at_decision"] >= 0
                and feat["state_30s_before_decision"] >= 0)
            feat["hmm_state_3_flag_at_pullback"] = (
                feat["state_at_decision"] == 3)

            # ----- Outcomes from fill forward (CAUSAL) -----
            walk_lo = fill_idx_global
            walk_end = min(
                regime_end_ts,
                actual_fill_ts + MAX_HORIZON_S * int(1e9))
            walk_hi = np.searchsorted(bars_ts, walk_end, side="left")
            # Include the bar AT regime_end_ts so re_idx can find it
            if (walk_hi < len(bars_ts)
                    and bars_ts[walk_hi] == regime_end_ts):
                walk_hi += 1
            walk_hi = min(walk_hi, len(bars_ts))
            outcomes = compute_outcomes(
                bars_h[walk_lo:walk_hi], bars_l[walk_lo:walk_hi],
                bars_c[walk_lo:walk_hi], bars_ts[walk_lo:walk_hi],
                fill_price, atr, d, regime_end_ts, regime_end_price,
                actual_fill_ts)
            if outcomes is None:
                continue
            feat.update(outcomes)
            pullback_rows.append(feat)
            thresholds_reached.append(thresh)

        # ---------- Matched baseline (signal-time entry, CAUSAL) -----
        # Emit one baseline row per regime per threshold reached.
        # CAUSAL: regime check at decision time only (= signal_time).
        if not thresholds_reached:
            continue
        # signal_time was already validated as < regime_end_ts above
        baseline_fill_target = signal_time + 30 * int(1e9)
        baseline_fill_idx = np.searchsorted(
            bars_ts, baseline_fill_target, side="left")
        if baseline_fill_idx >= len(bars_ts):
            continue
        baseline_actual_fill_ts = int(bars_ts[baseline_fill_idx])
        if baseline_actual_fill_ts - baseline_fill_target > 60 * int(1e9):
            continue
        baseline_fill_price = float(bars_o[baseline_fill_idx])
        # Walk to min(regime_end, fill + max_horizon). Include the
        # bar AT regime_end_ts.
        baseline_walk_end = min(
            regime_end_ts,
            baseline_actual_fill_ts + MAX_HORIZON_S * int(1e9))
        baseline_walk_hi = np.searchsorted(
            bars_ts, baseline_walk_end, side="left")
        if (baseline_walk_hi < len(bars_ts)
                and bars_ts[baseline_walk_hi] == regime_end_ts):
            baseline_walk_hi += 1
        baseline_walk_hi = min(baseline_walk_hi, len(bars_ts))
        baseline_outcomes = compute_outcomes(
            bars_h[baseline_fill_idx:baseline_walk_hi],
            bars_l[baseline_fill_idx:baseline_walk_hi],
            bars_c[baseline_fill_idx:baseline_walk_hi],
            bars_ts[baseline_fill_idx:baseline_walk_hi],
            baseline_fill_price, atr, d, regime_end_ts,
            regime_end_price, baseline_actual_fill_ts)
        if baseline_outcomes is None:
            continue
        for thresh in thresholds_reached:
            base_feat = {
                "regime_id": int(regime_id),
                "flip_bar_ts_event": flip_ts_event,
                "signal_time_ts": int(signal_time),
                "signal_price": signal_price,
                "direction": d,
                "atr_at_signal": atr,
                "regime_end_ts": regime_end_ts,
                "matched_threshold_atr": thresh,
                "fill_ts": baseline_actual_fill_ts,
                "fill_price": baseline_fill_price,
                "state_at_signal": state_at_signal,
                "state_at_raw_flip": hmm_state_at(flip_ts_event),
            }
            base_feat.update(baseline_outcomes)
            baseline_rows.append(base_feat)

    elapsed = time.time() - t0
    print(f"  Walked {len(pop):,} regimes in {elapsed:.0f}s")
    print(f"  Skipped: no_atr={skipped_no_atr}, no_b1={skipped_no_b1}, "
           f"short_regime={skipped_short_regime}")
    print(f"  Pullback candidate rows: {len(pullback_rows):,}")
    print(f"  Matched baseline rows: {len(baseline_rows):,}")

    df_pb = pd.DataFrame(pullback_rows)
    df_bl = pd.DataFrame(baseline_rows)
    df_pb.to_parquet(OUT / "pullback_candidates_2025.parquet",
                       index=False)
    df_bl.to_parquet(OUT / "matched_baseline_2025.parquet",
                       index=False)
    print(f"\nSaved:")
    print(f"  {OUT / 'pullback_candidates_2025.parquet'}")
    print(f"  {OUT / 'matched_baseline_2025.parquet'}")

    # Quick sanity print
    if len(df_pb):
        print(f"\nThreshold counts (pullback candidates):")
        print(df_pb["pullback_threshold_atr"].value_counts().sort_index())
        print(f"\n1.0/1.0 bracket aggregate:")
        sub = df_pb["bracket_100_100_pnl"]
        print(f"  n={len(sub):,}, mean=${sub.mean():.2f}, "
               f"median=${sub.median():.2f}")


if __name__ == "__main__":
    main()
