"""Fast Resolution Expansion Study v1 — collector.

For each HH/LL-confirmed RTH 1m regime flip:
  - 4 entry candidates: at signal, +30s, +60s, +90s checkpoints
  - decision at checkpoint close, fill 30s later
  - causal regime intact check at DECISION time only
  - NO future-survival filtering

Outputs: per-(regime, candidate) row with:
  - signal-strength features (flip + bar+1 shape)
  - early-movement features (at decision time)
  - HMM features (state, probabilities, entropy, dwell)
  - forward MFE/MAE at 30/60/120/180/300s
  - 5 race labels (PT-before-SL) × 5 windows
  - close prices at each window for unresolved-policy 1

NO regime-exit PnL anywhere. Unresolved trades are unresolved.
"""

from __future__ import annotations
import os, sys, time, argparse, pickle
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

OUT = Path("studies/fast_resolution_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
ENTRY_CANDIDATES_S = [0, 30, 60, 90]
WINDOWS_S = [30, 60, 120, 180, 300]
RACES = [
    (0.50, 0.50),
    (0.75, 0.50),
    (1.00, 0.50),
    (1.00, 0.75),
    (1.25, 0.75),
]


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


def enumerate_flips(bars_1m_h, bars_1m_l, bars_1m_c, bars_1m_o,
                       bars_1m_ts, bars_1m_init, year_start_ns):
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
                "flip_bar_o": float(bars_1m_o[i]),
                "flip_bar_h": float(bars_1m_h[i]),
                "flip_bar_l": float(bars_1m_l[i]),
                "flip_bar_c": float(bars_1m_c[i]),
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


def shannon_entropy(probs: np.ndarray) -> float:
    p = probs[probs > 1e-12]
    return float(-(p * np.log(p)).sum())


def main(year: int):
    print("=" * 72)
    print(f"FAST RESOLUTION EXPANSION STUDY v1 — YEAR {year}")
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
    bars_1m_o = np.array([float(b.open) for b in bars_1m_nt])
    bars_1m_h = np.array([float(b.high) for b in bars_1m_nt])
    bars_1m_l = np.array([float(b.low) for b in bars_1m_nt])
    bars_1m_c = np.array([float(b.close) for b in bars_1m_nt])
    print(f"  {len(bars_1m_nt):,} 1m bars")

    print("Computing ATR(14) series...")
    atr_series = compute_atr_series(bars_1m_h, bars_1m_l, bars_1m_c)

    print(f"Enumerating raw 1m flips on {year}...")
    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    raw_flips = enumerate_flips(
        bars_1m_h, bars_1m_l, bars_1m_c, bars_1m_o,
        bars_1m_ts, bars_1m_init, year_start_ns)
    print(f"  Raw flips: {len(raw_flips):,}, "
           f"HH/LL conf: {int(raw_flips['hhll_confirmed'].sum()):,}")

    raw_flips = raw_flips.sort_values(
        "flip_bar_ts_event").reset_index(drop=True)
    raw_flips["next_flip_ts_init"] = raw_flips[
        "flip_bar_ts_init"].shift(-1).fillna(
        raw_flips["flip_bar_ts_init"].max() + 30 * 24 * 3600 * int(1e9)
    ).astype("int64")

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

    # ----- HMM state series + posterior probabilities -----
    print("\nLoading HMM model + scoring 5s features...")
    with open("studies/hmm_5s_v1/results/hmm_model.pkl", "rb") as f:
        hmm_data = pickle.load(f)
    model = hmm_data["model"]
    means = hmm_data["means"]
    stds = hmm_data["stds"]
    feat_cols = hmm_data["feature_cols"]

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
    state_probs_5s = model.predict_proba(X_norm)  # (N, n_states)
    states_5s_ts = feats_5s["ts_event_ns"].values.astype("int64")
    states_5s = np.where(valid, states_5s, -1).astype("int64")
    state_probs_5s = np.where(
        valid[:, None], state_probs_5s, np.nan)
    n_states = state_probs_5s.shape[1]
    print(f"  {len(states_5s):,} 5s state values, {n_states} states")

    # CAUSAL HMM lookup: states_5s[i] computed from full 5s bar i;
    # bar closes at ts_event + 5s. Lookup by close time.
    states_5s_close_ts = states_5s_ts + 5 * int(1e9)

    def hmm_lookup(ts_ns: int):
        idx = int(np.searchsorted(
            states_5s_close_ts, ts_ns, side="right")) - 1
        if idx < 0:
            return -1, np.full(n_states, np.nan), np.nan, 0
        st = int(states_5s[idx])
        probs = state_probs_5s[idx]
        ent = (shannon_entropy(probs)
                if not np.isnan(probs).any() else float("nan"))
        # Dwell time in current state
        dwell = 0
        i = idx
        while i >= 0 and states_5s[i] == st and st >= 0:
            dwell += 1
            i -= 1
        return st, probs, ent, dwell * 5  # dwell in seconds

    # ----- Walk pop -----
    print(f"\nWalking {len(pop):,} regimes × "
           f"{len(ENTRY_CANDIDATES_S)} candidates...")
    rows = []
    skipped_no_atr = 0
    skipped_regime_dead_at_decision = 0
    skipped_no_fill = 0
    t0 = time.time()
    max_window_s = max(WINDOWS_S)

    for regime_id, row in pop.iterrows():
        flip_ts_event = int(row["flip_bar_ts_event"])
        flip_ts_init = int(row["flip_bar_ts_init"])
        d = int(row["new_regime"])
        regime_end_ts = int(row["next_flip_ts_init"])

        if row["flip_bar_idx"] + 1 >= len(bars_1m_c):
            continue
        b1_idx = int(row["flip_bar_idx"]) + 1
        atr = atr_series[b1_idx]
        if not np.isfinite(atr) or atr <= 0:
            skipped_no_atr += 1
            continue

        signal_time = flip_ts_init + 60 * int(1e9)
        signal_price = float(bars_1m_c[b1_idx])
        if regime_end_ts <= signal_time:
            continue

        # ----- Signal-strength features (constant per regime) -----
        flip_o = float(bars_1m_o[b1_idx - 1])
        flip_h = float(bars_1m_h[b1_idx - 1])
        flip_l = float(bars_1m_l[b1_idx - 1])
        flip_c = float(bars_1m_c[b1_idx - 1])
        flip_rng = max(1e-9, flip_h - flip_l)
        flip_body_pct = abs(flip_c - flip_o) / flip_rng
        flip_close_loc = (flip_c - flip_l) / flip_rng

        b1_o = float(bars_1m_o[b1_idx])
        b1_h = float(bars_1m_h[b1_idx])
        b1_l = float(bars_1m_l[b1_idx])
        b1_c = float(bars_1m_c[b1_idx])
        b1_rng = max(1e-9, b1_h - b1_l)
        bar1_body_pct = abs(b1_c - b1_o) / b1_rng
        bar1_close_loc = (b1_c - b1_l) / b1_rng

        two_bar_high = max(flip_h, b1_h)
        two_bar_low = min(flip_l, b1_l)
        two_bar_range_atr = (two_bar_high - two_bar_low) / atr
        two_bar_body_atr = abs(b1_c - flip_o) / atr

        # HMM at raw flip and signal
        hmm_st_flip, _, _, _ = hmm_lookup(flip_ts_event)
        hmm_st_signal, _, _, _ = hmm_lookup(signal_time)

        # ----- For each entry candidate -----
        for ec_s in ENTRY_CANDIDATES_S:
            decision_ts = signal_time + ec_s * int(1e9)
            fill_ts_target = decision_ts + 30 * int(1e9)

            # CAUSAL filter: only check regime at decision
            if regime_end_ts <= decision_ts:
                skipped_regime_dead_at_decision += 1
                continue

            # Fill bar
            fill_idx_global = np.searchsorted(
                bars_ts, fill_ts_target, side="left")
            if fill_idx_global >= len(bars_ts):
                skipped_no_fill += 1
                continue
            actual_fill_ts = int(bars_ts[fill_idx_global])
            if actual_fill_ts - fill_ts_target > 60 * int(1e9):
                skipped_no_fill += 1
                continue
            fill_price = float(bars_o[fill_idx_global])

            # ----- Early movement features at decision time -----
            # Bars from signal_time to decision_ts
            sig_lo = np.searchsorted(bars_ts, signal_time, side="left")
            dec_idx = np.searchsorted(
                bars_ts, decision_ts, side="right") - 1
            if dec_idx < sig_lo:
                # No bars between signal and decision (e.g., ec_s=0)
                progress_since_signal_atr = 0.0
                pullback_from_peak_atr = 0.0
                running_peak_at_decision = signal_price
            else:
                seg_h_pre = bars_h[sig_lo:dec_idx + 1]
                seg_l_pre = bars_l[sig_lo:dec_idx + 1]
                if d == 1:
                    running_peak_at_decision = float(seg_h_pre.max())
                    current_at_decision = float(bars_c[dec_idx])
                    progress_since_signal_atr = (
                        (current_at_decision - signal_price) / atr)
                    pullback_from_peak_atr = (
                        (running_peak_at_decision - current_at_decision)
                        / atr)
                else:
                    running_peak_at_decision = float(seg_l_pre.min())
                    current_at_decision = float(bars_c[dec_idx])
                    progress_since_signal_atr = (
                        (signal_price - current_at_decision) / atr)
                    pullback_from_peak_atr = (
                        (current_at_decision - running_peak_at_decision)
                        / atr)

            # New progress in last 30s
            t_30s_ago = decision_ts - 30 * int(1e9)
            t30_idx = np.searchsorted(
                bars_ts, t_30s_ago, side="right") - 1
            if t30_idx < 0 or t30_idx >= len(bars_ts):
                new_progress_last_30s_atr = 0.0
            else:
                price_30s_ago = float(bars_c[t30_idx])
                cur = float(bars_c[dec_idx]) if dec_idx >= 0 else signal_price
                new_progress_last_30s_atr = (
                    (cur - price_30s_ago) * d / atr)

            stall_flag = bool(
                ec_s > 0 and abs(new_progress_last_30s_atr) < 0.05)

            # HMM at decision
            hmm_st_dec, hmm_probs_dec, hmm_ent_dec, hmm_dwell_dec_s = (
                hmm_lookup(decision_ts))
            hmm_st_30s_before, _, _, _ = hmm_lookup(
                int(decision_ts - 30 * int(1e9)))
            hmm_state_changed_since_signal = bool(
                hmm_st_dec != hmm_st_signal
                and hmm_st_dec >= 0 and hmm_st_signal >= 0)
            hmm_recent_transition = bool(
                hmm_st_dec != hmm_st_30s_before
                and hmm_st_dec >= 0 and hmm_st_30s_before >= 0)

            # ----- Forward outcomes from fill -----
            walk_lo = fill_idx_global
            walk_end = actual_fill_ts + max_window_s * int(1e9)
            walk_hi = np.searchsorted(bars_ts, walk_end, side="left")
            walk_hi = min(walk_hi + 1, len(bars_ts))
            seg_h_fwd = bars_h[walk_lo:walk_hi]
            seg_l_fwd = bars_l[walk_lo:walk_hi]
            seg_c_fwd = bars_c[walk_lo:walk_hi]
            seg_ts_fwd = bars_ts[walk_lo:walk_hi]
            n_fwd = len(seg_h_fwd)
            if n_fwd == 0:
                skipped_no_fill += 1
                continue
            elapsed_s = (seg_ts_fwd - actual_fill_ts) / 1e9

            if d == 1:
                mfe_seq = (seg_h_fwd - fill_price) / atr
                mae_seq = (fill_price - seg_l_fwd) / atr
            else:
                mfe_seq = (fill_price - seg_l_fwd) / atr
                mae_seq = (seg_h_fwd - fill_price) / atr
            peak_mfe = np.maximum.accumulate(mfe_seq)
            peak_mae = np.maximum.accumulate(mae_seq)

            feat = {
                "regime_id": int(regime_id),
                "year": year,
                "flip_bar_ts_event": flip_ts_event,
                "signal_time_ts": int(signal_time),
                "signal_price": signal_price,
                "direction": d,
                "atr_at_signal": float(atr),
                "regime_end_ts": regime_end_ts,
                "entry_candidate_s": ec_s,
                "decision_ts": int(decision_ts),
                "fill_ts": actual_fill_ts,
                "fill_price": fill_price,
                "fill_slip_s": (actual_fill_ts - fill_ts_target) / 1e9,
                # Signal strength
                "flip_bar_body_pct": flip_body_pct,
                "flip_bar_close_loc": flip_close_loc,
                "bar1_body_pct": bar1_body_pct,
                "bar1_close_loc": bar1_close_loc,
                "two_bar_range_atr": two_bar_range_atr,
                "two_bar_body_atr": two_bar_body_atr,
                # Early movement
                "progress_since_signal_atr": progress_since_signal_atr,
                "pullback_from_peak_atr": pullback_from_peak_atr,
                "new_progress_last_30s_atr":
                    new_progress_last_30s_atr,
                "stall_flag": stall_flag,
                # HMM
                "hmm_state_at_raw_flip": hmm_st_flip,
                "hmm_state_at_confirmed_signal": hmm_st_signal,
                "hmm_state_at_decision": hmm_st_dec,
                "hmm_state_changed_since_signal":
                    hmm_state_changed_since_signal,
                "hmm_recent_transition_flag": hmm_recent_transition,
                "hmm_state_prob_0":
                    float(hmm_probs_dec[0]) if n_states > 0
                    else float("nan"),
                "hmm_state_prob_1":
                    float(hmm_probs_dec[1]) if n_states > 1
                    else float("nan"),
                "hmm_state_prob_2":
                    float(hmm_probs_dec[2]) if n_states > 2
                    else float("nan"),
                "hmm_state_prob_3":
                    float(hmm_probs_dec[3]) if n_states > 3
                    else float("nan"),
                "hmm_state_entropy": float(hmm_ent_dec),
                "hmm_dwell_time_current_state_s":
                    int(hmm_dwell_dec_s),
                "hmm_state_3_flag": bool(hmm_st_dec == 3),
            }

            # Forward MFE/MAE per window
            for w in WINDOWS_S:
                mask = elapsed_s <= w
                if mask.any():
                    mfe_w = float(peak_mfe[mask][-1])
                    mae_w = float(peak_mae[mask][-1])
                    close_w_idx = int(np.argmax(elapsed_s > w)) - 1
                    if close_w_idx < 0:
                        close_w_idx = int(np.argmax(mask)) + int(
                            mask.sum()) - 1
                    close_w = float(seg_c_fwd[close_w_idx])
                else:
                    mfe_w = float("nan")
                    mae_w = float("nan")
                    close_w = float("nan")
                feat[f"mfe_{w}s_atr"] = mfe_w
                feat[f"mae_{w}s_atr"] = mae_w
                feat[f"close_at_{w}s_price"] = close_w

            # Race labels per (race, window)
            for pt_R, sl_R in RACES:
                pt_first_idx = (np.argmax(peak_mfe >= pt_R)
                                  if (peak_mfe >= pt_R).any()
                                  else n_fwd + 1)
                sl_first_idx = (np.argmax(peak_mae >= sl_R)
                                  if (peak_mae >= sl_R).any()
                                  else n_fwd + 1)
                pt_t = (float(elapsed_s[pt_first_idx])
                          if pt_first_idx < n_fwd else float("inf"))
                sl_t = (float(elapsed_s[sl_first_idx])
                          if sl_first_idx < n_fwd else float("inf"))
                race_tag = (
                    f"race_{int(pt_R*100)}_{int(sl_R*100)}")
                for w in WINDOWS_S:
                    pt_in = pt_t <= w
                    sl_in = sl_t <= w
                    if pt_in and sl_in:
                        outcome = "pt" if pt_t < sl_t else "sl"
                        res_t = pt_t if outcome == "pt" else sl_t
                    elif pt_in:
                        outcome = "pt"
                        res_t = pt_t
                    elif sl_in:
                        outcome = "sl"
                        res_t = sl_t
                    else:
                        outcome = "unresolved"
                        res_t = float("nan")
                    feat[f"{race_tag}_{w}s_outcome"] = outcome
                    feat[f"{race_tag}_{w}s_resolution_s"] = res_t

            rows.append(feat)

    elapsed = time.time() - t0
    print(f"  Walked {len(pop):,} regimes in {elapsed:.0f}s")
    print(f"  Skipped: no_atr={skipped_no_atr}, "
           f"regime_dead_at_decision={skipped_regime_dead_at_decision}, "
           f"no_fill={skipped_no_fill}")
    print(f"  Trade rows: {len(rows):,}")

    df = pd.DataFrame(rows)
    out_path = OUT / f"trades_{year}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")
    if len(df):
        print(f"\nEntry-candidate counts:")
        print(df["entry_candidate_s"].value_counts().sort_index())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    main(args.year)
