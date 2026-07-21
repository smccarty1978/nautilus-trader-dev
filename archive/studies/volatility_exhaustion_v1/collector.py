"""Volatility Exhaustion / Failure Study v1 — collector.

Identify HMM state 3 (vol burst) impulses inside a 1m regime. When
the impulse is in the regime direction (continuation attempt) and
state 3 exits, apply 4 failure triggers. If a trigger fires, trade
the REVERSAL (opposite of impulse direction).

Causal timing: decision at trigger close, fill 30s later. No future
survival filtering. No regime-exit edge claims.

Triggers (all checked starting from state-3-exit time):
  1. close_loc      — within 60s post-exit, first 5s bar whose close
                      is in lower 50% of impulse range (bullish) or
                      upper 50% (bearish).
  2. no_new_30s     — at impulse_end + 30s, fires if no new high
                      (bullish) or new low (bearish) reached during
                      that window.
  3. no_new_60s     — same at +60s.
  4. wick_rejection — first 5s bar after exit with upper wick > 2x
                      body (bullish) or lower wick > 2x body (bearish).

Outputs: trades_<year>.parquet with one row per (impulse, trigger).
"""

from __future__ import annotations
import os, sys, time, argparse, pickle
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

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

OUT = Path("studies/volatility_exhaustion_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
CT = pytz.timezone("America/Chicago")
WINDOWS_S = [60, 120, 180, 300]
RACES = [
    (0.50, 0.50),
    (0.75, 0.50),
    (1.00, 0.50),
    (1.00, 0.75),
    (1.50, 0.75),
]
TRIGGER_SEARCH_S = 60  # bound trigger search to 60s post-exit


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


def enumerate_flips(bars_h, bars_l, bars_c, bars_ts, bars_init,
                       year_start_ns):
    """Returns flips DataFrame and a regime time series (per-1m-bar
    array of regime in effect at that bar's CLOSE)."""
    tracker = SimpleRegimeTracker()
    flips = []
    regime_at_bar_close = np.zeros(len(bars_c), dtype=int)
    for i in range(len(bars_c)):
        flipped = tracker.update(bars_h[i], bars_l[i], bars_c[i])
        regime_at_bar_close[i] = tracker.regime
        if flipped and bars_ts[i] >= year_start_ns:
            flips.append({
                "flip_bar_idx": i,
                "flip_bar_ts_event": int(bars_ts[i]),
                "flip_bar_ts_init": int(bars_init[i]),
                "flip_bar_c": float(bars_c[i]),
                "new_regime": int(tracker.regime),
            })
    return pd.DataFrame(flips), regime_at_bar_close


def shannon_entropy(p):
    p = p[p > 1e-12]
    return float(-(p * np.log(p)).sum())


def main(year: int):
    print("=" * 72)
    print(f"VOLATILITY EXHAUSTION STUDY v1 — YEAR {year}")
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
    atr_series = compute_atr_series(bars_1m_h, bars_1m_l, bars_1m_c)

    print("Enumerating raw 1m flips + regime time series...")
    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    raw_flips, regime_at_1m_close = enumerate_flips(
        bars_1m_h, bars_1m_l, bars_1m_c, bars_1m_ts, bars_1m_init,
        year_start_ns)
    print(f"  Raw flips: {len(raw_flips):,}")

    # Build per-1m-bar regime + flip-id (which regime episode are we in)
    # regime_id increments at each flip
    flip_id_at_bar = np.zeros(len(bars_1m_c), dtype=int)
    flip_idx_set = set(raw_flips["flip_bar_idx"].tolist()) if len(
        raw_flips) else set()
    cur_id = 0
    for i in range(len(bars_1m_c)):
        if i in flip_idx_set:
            cur_id += 1
        flip_id_at_bar[i] = cur_id

    # Map flip_id → flip start info (for extension/age computation)
    flip_lookup = {}  # id → (flip_bar_idx, flip_bar_close)
    for _, r in raw_flips.iterrows():
        idx = int(r["flip_bar_idx"])
        # The flip-id starts AT this idx (since cur_id += 1 when i == idx)
        # find the assigned flip_id
        fid = flip_id_at_bar[idx]
        flip_lookup[fid] = (idx, float(r["flip_bar_c"]))

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

    print("\nComputing per-1s session day + RTH extremes...")
    # Use date in CT to identify session days. Reset session extremes
    # at each new RTH session day (8:30 CT).
    ts_ct = pd.to_datetime(bars_ts, unit="ns", utc=True).tz_convert(CT)
    minutes_arr = (ts_ct.hour * 60 + ts_ct.minute)
    if hasattr(minutes_arr, "values"):
        minutes_arr = minutes_arr.values
    in_rth = (minutes_arr >= 510) & (minutes_arr < 900)
    # Identify session boundaries (transitions from non-RTH to RTH)
    rth_arr = in_rth.astype(np.int8)
    rth_starts = np.zeros(len(rth_arr), dtype=bool)
    rth_starts[0] = bool(rth_arr[0])
    rth_starts[1:] = (rth_arr[1:] == 1) & (rth_arr[:-1] == 0)
    session_id = np.cumsum(rth_starts) - (1 if rth_starts[0] else 0)
    session_id = np.where(in_rth, session_id, -1)

    # Compute per-bar running max/min within each RTH session
    session_high_arr = np.full(len(bars_ts), np.nan)
    session_low_arr = np.full(len(bars_ts), np.nan)
    cur_session = -2
    cur_h = -np.inf
    cur_l = np.inf
    for i in range(len(bars_ts)):
        sid = session_id[i]
        if sid == -1:
            session_high_arr[i] = np.nan
            session_low_arr[i] = np.nan
            continue
        if sid != cur_session:
            cur_session = sid
            cur_h = bars_h[i]
            cur_l = bars_l[i]
        else:
            if bars_h[i] > cur_h:
                cur_h = bars_h[i]
            if bars_l[i] < cur_l:
                cur_l = bars_l[i]
        session_high_arr[i] = cur_h
        session_low_arr[i] = cur_l

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
    state_probs_5s = model.predict_proba(X_norm)
    states_5s = np.where(valid, states_5s, -1).astype("int64")

    bar_5s_ts = feats_5s["ts_event_ns"].values.astype("int64")
    bar_5s_o = feats_5s["open"].values
    bar_5s_h = feats_5s["high"].values
    bar_5s_l = feats_5s["low"].values
    bar_5s_c = feats_5s["close"].values
    bar_5s_vol_z = feats_5s["vol_z"].values
    print(f"  {len(states_5s):,} 5s state values")

    # ----- Identify state 3 segments -----
    # consecutive 5s bars where state == 3
    print("\nIdentifying state 3 segments...")
    seg_starts = []
    seg_ends = []
    in_seg = False
    seg_start = -1
    for i in range(len(states_5s)):
        if states_5s[i] == 3:
            if not in_seg:
                seg_start = i
                in_seg = True
        else:
            if in_seg:
                seg_starts.append(seg_start)
                seg_ends.append(i - 1)
                in_seg = False
    if in_seg:
        seg_starts.append(seg_start)
        seg_ends.append(len(states_5s) - 1)
    print(f"  {len(seg_starts):,} state 3 segments")

    # ----- Process each segment -----
    print("\nProcessing impulses + triggers...")
    rows = []
    skipped_warmup = 0
    skipped_not_rth = 0
    skipped_no_continuation = 0
    skipped_no_atr = 0
    skipped_no_trigger = 0
    skipped_no_fill = 0
    diag_continuation = 0
    diag_triggers_fired = {"close_loc": 0, "no_new_30s": 0,
                              "no_new_60s": 0, "wick_rejection": 0}
    t0 = time.time()
    impulse_id = 0

    for ss, se in zip(seg_starts, seg_ends):
        impulse_start_ts = int(bar_5s_ts[ss])
        # State 3 exit time = ts_event of FIRST bar AFTER segment
        # = bar_5s_ts[se] + 5s
        impulse_end_ts = int(bar_5s_ts[se] + 5_000_000_000)

        # Filter to impulse start in RTH
        ts_start_ct = pd.Timestamp(impulse_start_ts,
                                       tz="UTC").tz_convert(CT)
        m_start = ts_start_ct.hour * 60 + ts_start_ct.minute
        if not (510 <= m_start < 900):
            skipped_not_rth += 1
            continue

        # Impulse properties from 5s bars
        seg_h = bar_5s_h[ss:se + 1]
        seg_l = bar_5s_l[ss:se + 1]
        seg_o_arr = bar_5s_o[ss:se + 1]
        seg_c_arr = bar_5s_c[ss:se + 1]
        seg_vol_z = bar_5s_vol_z[ss:se + 1]

        impulse_open = float(seg_o_arr[0])
        impulse_close = float(seg_c_arr[-1])
        impulse_high = float(seg_h.max())
        impulse_low = float(seg_l.min())
        impulse_range = impulse_high - impulse_low
        if impulse_range < 1e-9:
            continue

        impulse_dir = 1 if impulse_close > impulse_open else (
            -1 if impulse_close < impulse_open else 0)
        if impulse_dir == 0:
            continue
        impulse_body = abs(impulse_close - impulse_open)
        impulse_body_pct = impulse_body / impulse_range
        impulse_close_loc = (impulse_close - impulse_low) / impulse_range
        impulse_volume_z_mean = float(np.nanmean(seg_vol_z))
        impulse_duration_s = (se - ss + 1) * 5

        # Lookup 1m regime at impulse start
        bar_1m_idx = np.searchsorted(
            bars_1m_init, impulse_start_ts, side="right") - 1
        if bar_1m_idx < 0 or bar_1m_idx >= len(bars_1m_c):
            skipped_warmup += 1
            continue
        regime_at_impulse = int(regime_at_1m_close[bar_1m_idx])
        atr = float(atr_series[bar_1m_idx])
        if not np.isfinite(atr) or atr <= 0:
            skipped_no_atr += 1
            continue

        # Continuation filter: impulse direction must match regime
        if regime_at_impulse == 0 or regime_at_impulse != impulse_dir:
            skipped_no_continuation += 1
            continue
        diag_continuation += 1

        # Regime extension + age (using flip_id_at_bar)
        cur_flip_id = flip_id_at_bar[bar_1m_idx]
        if cur_flip_id in flip_lookup:
            regime_start_idx, regime_start_close = flip_lookup[
                cur_flip_id]
            regime_age_bars = bar_1m_idx - regime_start_idx
            extension_atr = (
                (impulse_close - regime_start_close) * regime_at_impulse
                / atr)
        else:
            regime_age_bars = -1
            extension_atr = float("nan")

        # Session extremes at impulse start
        s_idx = np.searchsorted(bars_ts, impulse_start_ts, side="left")
        if s_idx >= len(bars_ts):
            continue
        s_high = float(session_high_arr[s_idx])
        s_low = float(session_low_arr[s_idx])
        if np.isnan(s_high):
            dist_session_high_atr = float("nan")
            dist_session_low_atr = float("nan")
        else:
            dist_session_high_atr = (s_high - impulse_close) / atr
            dist_session_low_atr = (impulse_close - s_low) / atr

        # Common impulse-feature dict (same across triggers for this impulse)
        impulse_features = {
            "year": year,
            "impulse_id": impulse_id,
            "impulse_start_ts": impulse_start_ts,
            "impulse_end_ts": impulse_end_ts,
            "impulse_duration_s": impulse_duration_s,
            "impulse_direction": impulse_dir,
            "regime_direction": regime_at_impulse,
            "regime_id": int(cur_flip_id),
            "regime_age_bars": int(regime_age_bars),
            "extension_from_regime_atr": extension_atr,
            "atr_at_impulse": atr,
            "impulse_open": impulse_open,
            "impulse_high": impulse_high,
            "impulse_low": impulse_low,
            "impulse_close": impulse_close,
            "impulse_range_atr": impulse_range / atr,
            "impulse_body_pct": impulse_body_pct,
            "impulse_close_loc": impulse_close_loc,
            "impulse_volume_z_mean": impulse_volume_z_mean,
            "dist_from_session_high_atr": dist_session_high_atr,
            "dist_from_session_low_atr": dist_session_low_atr,
        }
        impulse_id += 1

        # ----- Apply triggers -----
        # Compute the post-exit window for searching triggers
        post_lo_5s = se + 1
        post_hi_5s = np.searchsorted(
            bar_5s_ts, impulse_end_ts + TRIGGER_SEARCH_S * int(1e9),
            side="left")
        if post_hi_5s <= post_lo_5s:
            skipped_no_trigger += 1
            continue
        post_5s_h = bar_5s_h[post_lo_5s:post_hi_5s]
        post_5s_l = bar_5s_l[post_lo_5s:post_hi_5s]
        post_5s_o = bar_5s_o[post_lo_5s:post_hi_5s]
        post_5s_c = bar_5s_c[post_lo_5s:post_hi_5s]
        post_5s_ts = bar_5s_ts[post_lo_5s:post_hi_5s]

        triggers_to_fire = []  # list of (trigger_type, trigger_ts)

        # Trigger 1: close_loc failure
        # bullish: first post-exit 5s bar where close < midpoint of impulse range
        # bearish: first post-exit 5s bar where close > midpoint
        midpoint = (impulse_high + impulse_low) / 2
        if impulse_dir == 1:
            mask = post_5s_c < midpoint
        else:
            mask = post_5s_c > midpoint
        if mask.any():
            idx = int(np.argmax(mask))
            # Trigger at the CLOSE of that 5s bar = ts_event + 5s
            trig_ts = int(post_5s_ts[idx] + 5_000_000_000)
            triggers_to_fire.append(("close_loc", trig_ts))

        # Trigger 2 & 3: no_new_30s / no_new_60s
        for window_s, tag in [(30, "no_new_30s"), (60, "no_new_60s")]:
            cutoff_ts = impulse_end_ts + window_s * int(1e9)
            window_hi = np.searchsorted(
                post_5s_ts, cutoff_ts, side="left")
            if window_hi <= 0:
                continue
            window_h_arr = post_5s_h[:window_hi]
            window_l_arr = post_5s_l[:window_hi]
            if impulse_dir == 1:
                made_new = bool((window_h_arr > impulse_high).any())
            else:
                made_new = bool((window_l_arr < impulse_low).any())
            if not made_new:
                triggers_to_fire.append((tag, cutoff_ts))

        # Trigger 4: wick_rejection
        # First post-exit 5s bar with rejection wick > 2 * body
        if len(post_5s_h):
            for j in range(min(3, len(post_5s_h))):  # check first 3 bars
                bo = post_5s_o[j]
                bc = post_5s_c[j]
                bh = post_5s_h[j]
                bl = post_5s_l[j]
                body = abs(bc - bo)
                if body < 1e-9:
                    continue
                if impulse_dir == 1:
                    upper_wick = bh - max(bo, bc)
                    if upper_wick > 2 * body:
                        trig_ts = int(post_5s_ts[j] + 5_000_000_000)
                        triggers_to_fire.append(
                            ("wick_rejection", trig_ts))
                        break
                else:
                    lower_wick = min(bo, bc) - bl
                    if lower_wick > 2 * body:
                        trig_ts = int(post_5s_ts[j] + 5_000_000_000)
                        triggers_to_fire.append(
                            ("wick_rejection", trig_ts))
                        break

        if not triggers_to_fire:
            skipped_no_trigger += 1
            continue

        # ----- For each trigger that fired, build a trade row -----
        for trig_type, trig_ts in triggers_to_fire:
            diag_triggers_fired[trig_type] += 1

            decision_ts = trig_ts
            fill_ts_target = decision_ts + 30 * int(1e9)
            fill_idx = np.searchsorted(
                bars_ts, fill_ts_target, side="left")
            if fill_idx >= len(bars_ts):
                skipped_no_fill += 1
                continue
            actual_fill_ts = int(bars_ts[fill_idx])
            if actual_fill_ts - fill_ts_target > 60 * int(1e9):
                skipped_no_fill += 1
                continue
            fill_price = float(bars_o[fill_idx])

            # Trade direction = REVERSAL = -impulse_direction
            entry_dir = -impulse_dir

            # Forward outcomes from fill (max window)
            walk_lo = fill_idx
            walk_end = actual_fill_ts + max(WINDOWS_S) * int(1e9)
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

            if entry_dir == 1:
                mfe_seq = (seg_h_fwd - fill_price) / atr
                mae_seq = (fill_price - seg_l_fwd) / atr
            else:
                mfe_seq = (fill_price - seg_l_fwd) / atr
                mae_seq = (seg_h_fwd - fill_price) / atr
            peak_mfe = np.maximum.accumulate(mfe_seq)
            peak_mae = np.maximum.accumulate(mae_seq)

            row = dict(impulse_features)
            row.update({
                "trigger_type": trig_type,
                "trigger_ts": trig_ts,
                "decision_ts": decision_ts,
                "fill_ts": actual_fill_ts,
                "fill_price": fill_price,
                "fill_slip_s": (actual_fill_ts - fill_ts_target) / 1e9,
                "entry_direction": entry_dir,
            })

            # MFE/MAE per window
            for w in WINDOWS_S:
                mask = elapsed_s <= w
                if mask.any():
                    mfe_w = float(peak_mfe[mask][-1])
                    mae_w = float(peak_mae[mask][-1])
                    last_idx = int(np.where(mask)[0][-1])
                    close_w = float(seg_c_fwd[last_idx])
                else:
                    mfe_w = float("nan")
                    mae_w = float("nan")
                    close_w = float("nan")
                row[f"mfe_{w}s_atr"] = mfe_w
                row[f"mae_{w}s_atr"] = mae_w
                row[f"close_at_{w}s_price"] = close_w

            # Race outcomes (PT-before-SL)
            for pt_R, sl_R in RACES:
                pt_first = (np.argmax(peak_mfe >= pt_R)
                              if (peak_mfe >= pt_R).any() else n_fwd + 1)
                sl_first = (np.argmax(peak_mae >= sl_R)
                              if (peak_mae >= sl_R).any() else n_fwd + 1)
                pt_t = (float(elapsed_s[pt_first])
                          if pt_first < n_fwd else float("inf"))
                sl_t = (float(elapsed_s[sl_first])
                          if sl_first < n_fwd else float("inf"))
                tag = f"race_{int(pt_R*100)}_{int(sl_R*100)}"
                for w in WINDOWS_S:
                    pt_in = pt_t <= w
                    sl_in = sl_t <= w
                    if pt_in and sl_in:
                        outcome = "pt" if pt_t < sl_t else "sl"
                        res_t = pt_t if outcome == "pt" else sl_t
                    elif pt_in:
                        outcome, res_t = "pt", pt_t
                    elif sl_in:
                        outcome, res_t = "sl", sl_t
                    else:
                        outcome, res_t = "unresolved", float("nan")
                    row[f"{tag}_{w}s_outcome"] = outcome
                    row[f"{tag}_{w}s_resolution_s"] = res_t

            rows.append(row)

    elapsed = time.time() - t0
    print(f"  Processed {len(seg_starts):,} state 3 segments in "
           f"{elapsed:.0f}s")
    print(f"  Continuation impulses (in regime direction): "
           f"{diag_continuation:,}")
    print(f"  Triggers fired: {diag_triggers_fired}")
    print(f"  Skipped: not_rth={skipped_not_rth}, "
           f"warmup={skipped_warmup}, "
           f"no_atr={skipped_no_atr}, "
           f"no_continuation={skipped_no_continuation}, "
           f"no_trigger={skipped_no_trigger}, "
           f"no_fill={skipped_no_fill}")
    print(f"  Trade rows: {len(rows):,}")

    df = pd.DataFrame(rows)
    out_path = OUT / f"trades_{year}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")
    if len(df):
        print(f"\nTrigger counts:")
        print(df["trigger_type"].value_counts())
        print(f"\nDirection split (entry):")
        print(df["entry_direction"].value_counts())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    main(args.year)
