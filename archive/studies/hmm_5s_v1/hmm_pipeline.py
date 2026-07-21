"""HMM 5s state layer pipeline (raw flips, no HH/LL gate).

Steps:
  1. Aggregate 1s catalog bars to 5s for 2023-2025
  2. Compute compact 5s feature set (returns, range, body%, close-loc,
     vol z-score, EMA10 slope)
  3. Fit 4-state Gaussian HMM on 2023-2024 5s features
  4. Re-derive raw 1m regime flips on 2025 by running the regime
     indicator over 1m bars
  5. For each raw flip on 2025 RTH:
       - Inferred HMM state at flip moment from preceding 5min lookback
       - Flag whether bar+1 made HH/LL (would-have-been-confirmed)
       - Walk 1s bars from flip+30s through min(regime_exit, +30min)
         to determine PT/SL/regime/unresolved outcome
  6. State-conditioned trade economics + outcome mix + comparison
     of confirmed vs unconfirmed raw flips by state
"""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from hmmlearn import hmm

OUT = Path("studies/hmm_5s_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


# ----- 1. 5s bar aggregation -----

def aggregate_1s_to_5s(bars_1s_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1s bars to 5s. Index = ts_event (open time of 5s bar)."""
    df = bars_1s_df.copy()
    df["ts_dt"] = pd.to_datetime(df["ts_event"], unit="ns", utc=True)
    df = df.set_index("ts_dt")
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    out = df[["open", "high", "low", "close", "volume"]].resample(
        "5s", label="left", closed="left").agg(agg).dropna()
    out["ts_event_ns"] = out.index.view("int64")
    return out.reset_index(drop=True)


def load_year_5s(year: int) -> pd.DataFrame:
    """Load 1s bars for a year + warmup, aggregate to 5s."""
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=2)
    end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"  Loading 1s bars {start.date()} -> {end.date()}...",
           flush=True)
    bars = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=start, end=end)
    print(f"    {len(bars):,} 1s bars", flush=True)
    df = pd.DataFrame({
        "ts_event": [b.ts_event for b in bars],
        "open": [float(b.open) for b in bars],
        "high": [float(b.high) for b in bars],
        "low": [float(b.low) for b in bars],
        "close": [float(b.close) for b in bars],
        "volume": [float(b.volume) if hasattr(b, "volume") else 0.0
                    for b in bars],
    })
    print("    aggregating to 5s...", flush=True)
    df_5s = aggregate_1s_to_5s(df)
    print(f"    {len(df_5s):,} 5s bars", flush=True)
    return df_5s


# ----- 2. 5s feature set -----

def compute_5s_features(df: pd.DataFrame,
                          vol_z_window: int = 60,
                          ema_window: int = 10,
                          rv_window: int = 12) -> pd.DataFrame:
    """Compute compact 5s feature set.

    7 features (within the 5-10 budget):
      - ret: log return
      - range: high-low (in pts)
      - body_pct: |close-open|/range
      - close_loc: (close-low)/range
      - vol_z: volume z-score over rolling 60-bar (5min) window
      - ema_slope: 10-bar EMA of returns (sign + magnitude proxy)
      - rv: realized vol (std of last 12 returns = 1min)
    """
    out = df.copy()
    rng = (out["high"] - out["low"]).clip(lower=1e-9)
    out["ret"] = np.log(out["close"] / out["close"].shift(1))
    out["range"] = (out["high"] - out["low"]).values
    out["body_pct"] = (np.abs(out["close"] - out["open"]) / rng).values
    out["close_loc"] = ((out["close"] - out["low"]) / rng).values
    vol_mean = out["volume"].rolling(vol_z_window).mean()
    vol_std = out["volume"].rolling(vol_z_window).std().clip(lower=1e-9)
    out["vol_z"] = (out["volume"] - vol_mean) / vol_std
    out["ema_slope"] = out["ret"].ewm(
        span=ema_window, adjust=False).mean()
    out["rv"] = out["ret"].rolling(rv_window).std()
    return out


FEATURE_COLS = ["ret", "range", "body_pct", "close_loc",
                "vol_z", "ema_slope", "rv"]


# ----- 3. Fit HMM -----

def fit_hmm(features: pd.DataFrame, n_states: int = 4,
              random_state: int = 42) -> hmm.GaussianHMM:
    """Fit a Gaussian HMM on the feature matrix. Drop NaN rows."""
    X = features[FEATURE_COLS].dropna().values
    print(f"  Fitting {n_states}-state Gaussian HMM on "
           f"{len(X):,} 5s observations...", flush=True)
    # Standardize features (HMM is sensitive to scale)
    means = X.mean(axis=0)
    stds = X.std(axis=0)
    stds[stds < 1e-9] = 1.0
    X_norm = (X - means) / stds

    t0 = time.time()
    model = hmm.GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        n_iter=100,
        random_state=random_state,
        verbose=False,
    )
    model.fit(X_norm)
    print(f"    Trained in {time.time() - t0:.1f}s, "
           f"converged={model.monitor_.converged}", flush=True)
    return model, means, stds


# ----- 4. Re-derive raw 1m flips on 2025 -----

class SimpleRegimeTracker:
    """Lightweight 1m regime tracker matching v2 collector logic.

    Regime: based on EMA3 of high vs low. Long if close > EMA3_H AND
    close > EMA9_H, short if close < EMA3_L AND close < EMA9_L. Sticky
    (no flip until both conditions for opposite regime).

    This is a simplified version; for the HMM study we just need flip
    detection at the right bars.
    """

    def __init__(self):
        self.regime = 0
        self.bars_in_regime = 0
        self.ema3_h = self.ema9_h = self.ema3_l = self.ema9_l = None
        self.alpha3 = 2.0 / (3 + 1)
        self.alpha9 = 2.0 / (9 + 1)

    def update(self, bar_h: float, bar_l: float, bar_c: float) -> bool:
        """Returns True if regime flipped on this bar."""
        if self.ema3_h is None:
            self.ema3_h = bar_h
            self.ema9_h = bar_h
            self.ema3_l = bar_l
            self.ema9_l = bar_l
        else:
            self.ema3_h = self.alpha3 * bar_h + (1 - self.alpha3) * self.ema3_h
            self.ema9_h = self.alpha9 * bar_h + (1 - self.alpha9) * self.ema9_h
            self.ema3_l = self.alpha3 * bar_l + (1 - self.alpha3) * self.ema3_l
            self.ema9_l = self.alpha9 * bar_l + (1 - self.alpha9) * self.ema9_l

        new_regime = self.regime  # sticky default
        if bar_c > self.ema3_h and bar_c > self.ema9_h:
            new_regime = 1
        elif bar_c < self.ema3_l and bar_c < self.ema9_l:
            new_regime = -1

        flipped = (new_regime != 0
                    and self.regime != 0
                    and new_regime != self.regime)
        if new_regime != self.regime:
            self.bars_in_regime = 1
        else:
            self.bars_in_regime += 1
        self.regime = new_regime if new_regime != 0 else self.regime
        return flipped


def enumerate_raw_flips(year: int) -> pd.DataFrame:
    """Walk 1m bars for the year, return raw flips with metadata."""
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    # Include warmup: pull all of prev year for indicator init
    start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=30)
    end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"  Loading 1m bars {start.date()} -> {end.date()}...",
           flush=True)
    bars = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=start, end=end)
    print(f"    {len(bars):,} 1m bars", flush=True)

    tracker = SimpleRegimeTracker()
    flips = []
    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    last_h = last_l = last_c = None

    for i, b in enumerate(bars):
        h = float(b.high)
        l = float(b.low)
        c = float(b.close)
        flipped = tracker.update(h, l, c)
        if flipped and b.ts_event >= year_start_ns:
            flips.append({
                "flip_bar_ts_event": b.ts_event,
                "flip_bar_ts_init": b.ts_init,
                "flip_bar_h": h,
                "flip_bar_l": l,
                "flip_bar_c": c,
                "flip_bar_idx": i,
                "new_regime": tracker.regime,
            })
        last_h, last_l, last_c = h, l, c

    df_flips = pd.DataFrame(flips)
    print(f"    {len(df_flips):,} raw flips on {year}", flush=True)

    # For each flip, look at bar+1 to determine HH/LL confirmation
    # bar+1 = the next 1m bar after the flip
    bar_h_arr = np.array([float(b.high) for b in bars])
    bar_l_arr = np.array([float(b.low) for b in bars])
    confirmed = []
    for _, row in df_flips.iterrows():
        idx = int(row["flip_bar_idx"])
        if idx + 1 >= len(bars):
            confirmed.append(False)
            continue
        b1_h = bar_h_arr[idx + 1]
        b1_l = bar_l_arr[idx + 1]
        if row["new_regime"] == 1:
            # Long flip: bar+1 must make new HH (b1_h > flip_h)
            confirmed.append(bool(b1_h > row["flip_bar_h"]))
        else:
            # Short flip: bar+1 must make new LL
            confirmed.append(bool(b1_l < row["flip_bar_l"]))
    df_flips["hhll_confirmed"] = confirmed
    return df_flips


# ----- 5. Forward outcome walks -----

def walk_outcome(bars_ts: np.ndarray, bars_h: np.ndarray,
                   bars_l: np.ndarray, bars_o: np.ndarray,
                   fill_ts_ns: int, fill_price: float, atr: float,
                   direction: int, max_horizon_s: int = 1800) -> dict:
    """Walk 1s bars from fill_ts forward to determine PT/SL/regime/unres
    outcome with 1.0 ATR PT and 1.0 ATR SL bracket."""
    pt_level = fill_price + direction * 1.0 * atr
    sl_level = fill_price - direction * 1.0 * atr

    end_ts = fill_ts_ns + max_horizon_s * 1_000_000_000
    lo = np.searchsorted(bars_ts, fill_ts_ns, side="left")
    hi = np.searchsorted(bars_ts, end_ts, side="left")
    if hi <= lo:
        return {"outcome": "unresolved", "resolution_time_s": np.nan,
                 "exit_price": fill_price}

    seg_h = bars_h[lo:hi]
    seg_l = bars_l[lo:hi]
    seg_ts = bars_ts[lo:hi]

    if direction == 1:
        # PT touched: any bar high >= pt_level
        # SL touched: any bar low <= sl_level
        pt_hits = seg_h >= pt_level
        sl_hits = seg_l <= sl_level
    else:
        pt_hits = seg_l <= pt_level
        sl_hits = seg_h >= sl_level

    pt_first_idx = pt_hits.argmax() if pt_hits.any() else len(seg_h) + 1
    sl_first_idx = sl_hits.argmax() if sl_hits.any() else len(seg_h) + 1

    if pt_first_idx == len(seg_h) + 1 and sl_first_idx == len(seg_h) + 1:
        return {"outcome": "unresolved",
                 "resolution_time_s": (seg_ts[-1] - fill_ts_ns) / 1e9,
                 "exit_price": float(bars_o[lo + len(seg_h) - 1])}
    if pt_first_idx < sl_first_idx:
        return {"outcome": "pt",
                 "resolution_time_s":
                     (seg_ts[pt_first_idx] - fill_ts_ns) / 1e9,
                 "exit_price": pt_level}
    elif sl_first_idx < pt_first_idx:
        return {"outcome": "sl",
                 "resolution_time_s":
                     (seg_ts[sl_first_idx] - fill_ts_ns) / 1e9,
                 "exit_price": sl_level}
    else:
        # Same bar — apply "more decisive" tie-break (favor PT here for
        # consistency with v2 collector default)
        return {"outcome": "pt",
                 "resolution_time_s":
                     (seg_ts[pt_first_idx] - fill_ts_ns) / 1e9,
                 "exit_price": pt_level}


# ----- 6. ATR(14) on 1m bars (Wilder's RMA) -----

def compute_atr14_at_flip(bars_1m: list, idx: int) -> float:
    """Compute ATR(14) on 1m bars up to and including bar at idx."""
    if idx < 14:
        return float("nan")
    # Get last 100 bars or so for warmup
    start = max(0, idx - 200)
    h = np.array([float(bars_1m[i].high) for i in range(start, idx + 1)])
    l = np.array([float(bars_1m[i].low) for i in range(start, idx + 1)])
    c = np.array([float(bars_1m[i].close) for i in range(start, idx + 1)])
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c),
                              np.abs(l - prev_c)])
    if len(tr) < 14:
        return float("nan")
    atr = tr[:14].mean()
    for i in range(14, len(tr)):
        atr = (atr * 13 + tr[i]) / 14
    return float(atr)


# ----- Main -----

def main():
    print("=" * 72)
    print("HMM 5s STATE LAYER — RAW FLIPS")
    print("=" * 72)

    # --- Load 5s bars for 2023, 2024, 2025 ---
    print("\n[1] Loading 5s bars (aggregate from 1s catalog)...")
    df_5s_train = []
    for year in [2023, 2024]:
        d = load_year_5s(year)
        d["year"] = year
        df_5s_train.append(d)
    df_5s_train = pd.concat(df_5s_train, ignore_index=True)
    df_5s_train = df_5s_train.sort_values("ts_event_ns").reset_index(drop=True)

    df_5s_2025 = load_year_5s(2025)
    df_5s_2025 = df_5s_2025.sort_values("ts_event_ns").reset_index(drop=True)

    # --- Compute 5s features ---
    print("\n[2] Computing 5s features...")
    feats_train = compute_5s_features(df_5s_train)
    feats_2025 = compute_5s_features(df_5s_2025)
    print(f"    Train ({len(feats_train):,} 5s bars), 2025 "
           f"({len(feats_2025):,} 5s bars)")

    # --- Fit HMM (try 3,4,5 states; pick 4 by default) ---
    print("\n[3] Fitting Gaussian HMM (4 states)...")
    model, means, stds = fit_hmm(feats_train, n_states=4)
    # Save model + normalization
    import pickle
    with open(OUT / "hmm_model.pkl", "wb") as f:
        pickle.dump({"model": model, "means": means, "stds": stds,
                      "feature_cols": FEATURE_COLS}, f)
    print(f"    Saved: {OUT / 'hmm_model.pkl'}")

    # Inspect state means in feature space
    state_means_norm = model.means_
    state_means_orig = state_means_norm * stds + means
    state_summary = pd.DataFrame(
        state_means_orig, columns=FEATURE_COLS)
    state_summary["state"] = range(model.n_components)
    state_summary.to_parquet(OUT / "state_feature_means.parquet",
                                index=False)
    print(f"\n    State feature means (original units):")
    print(state_summary.to_string(
        index=False, float_format=lambda x: f"{x:.4f}"))

    # --- Score 2025 5s bars to get state sequence ---
    print("\n[4] Inferring state sequence on 2025 5s bars...")
    X25 = feats_2025[FEATURE_COLS].fillna(0.0).values  # fill nan with 0 for safety
    valid_mask = feats_2025[FEATURE_COLS].notna().all(axis=1).values
    X25_norm = (X25 - means) / stds
    states25 = model.predict(X25_norm)
    feats_2025["state"] = states25
    feats_2025.loc[~valid_mask, "state"] = -1
    # State distribution
    print(f"    2025 state distribution:")
    state_dist = feats_2025[feats_2025["state"] >= 0]["state"].value_counts().sort_index()
    for s, n in state_dist.items():
        print(f"      State {s}: {n:,} 5s bars "
               f"({100*n/(states25 >= 0).sum():.1f}%)")

    # --- Enumerate raw flips on 2025 ---
    print("\n[5] Enumerating raw 1m flips on 2025...")
    raw_flips = enumerate_raw_flips(2025)
    raw_flips.to_parquet(OUT / "raw_flips_2025.parquet", index=False)
    n_conf = int(raw_flips["hhll_confirmed"].sum())
    n_unconf = int((~raw_flips["hhll_confirmed"]).sum())
    print(f"    Raw flips: {len(raw_flips):,} "
           f"(confirmed {n_conf:,}, unconfirmed {n_unconf:,})")

    # --- For each raw flip on RTH 2025: state @ flip + walk outcome ---
    print("\n[6] Computing state at flip + forward outcomes...")
    # Need 1s bars for forward walks + 1m bars for ATR
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    print("  Loading 2025 1s bars (for forward walks + fill prices)...",
           flush=True)
    bars_1s_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-01", tz="UTC"),
        end=pd.Timestamp("2025-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_1s_nt])
    bars_h = np.array([float(b.high) for b in bars_1s_nt])
    bars_l = np.array([float(b.low) for b in bars_1s_nt])
    bars_o = np.array([float(b.open) for b in bars_1s_nt])
    print(f"    {len(bars_1s_nt):,} 1s bars loaded")

    # 1m bars (already loaded for flip enumeration but we need them again
    # for ATR computation per-flip)
    print("  Loading 2025 1m bars (for ATR)...", flush=True)
    bars_1m_nt = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp("2025-01-01", tz="UTC")
              - pd.Timedelta(days=30),
        end=pd.Timestamp("2025-12-31 23:59:59", tz="UTC"))
    bars_1m_ts = np.array([b.ts_event for b in bars_1m_nt])

    # 5s bars / states (with ts_event_ns and state)
    feats_2025_arr = feats_2025[["ts_event_ns", "state"]].values
    bars_5s_ts = feats_2025_arr[:, 0].astype("int64")
    bars_5s_state = feats_2025_arr[:, 1].astype("int64")

    # Filter raw flips to RTH (08:30-15:00 CT = 13:30-20:00 UTC for CST,
    # 14:30-21:00 UTC for CDT). Use simple UTC test for now.
    import pytz
    CT = pytz.timezone("America/Chicago")
    flip_dts = pd.to_datetime(raw_flips["flip_bar_ts_event"],
                                 unit="ns", utc=True).dt.tz_convert(CT)
    flip_minutes = flip_dts.dt.hour * 60 + flip_dts.dt.minute
    rth_mask = (flip_minutes >= 510) & (flip_minutes < 900)
    raw_flips_rth = raw_flips[rth_mask].copy()
    print(f"    RTH-only raw flips on 2025: {len(raw_flips_rth):,}")

    # Build a quick lookup of flip_idx_in_full_1m_bars
    # We have flip_bar_idx (0-indexed within the FULL 1m bars set used
    # in enumerate_raw_flips, which started 30d before year). But that
    # bar set is different from the 2025-only 1m bars we just loaded.
    # So we need to re-find each flip in the new 1m array by ts_event.
    bars_1m_ts_set = bars_1m_ts
    records = []
    t0 = time.time()
    skipped_warmup = 0
    for _, row in raw_flips_rth.iterrows():
        flip_ts = int(row["flip_bar_ts_event"])
        flip_init = int(row["flip_bar_ts_init"])
        d = int(row["new_regime"])
        # Find this 1m bar in the year-bars array
        idx_in_1m = np.searchsorted(bars_1m_ts, flip_ts)
        if (idx_in_1m >= len(bars_1m_ts)
                or bars_1m_ts[idx_in_1m] != flip_ts):
            continue

        atr = compute_atr14_at_flip(bars_1m_nt, idx_in_1m)
        if not np.isfinite(atr) or atr <= 0:
            skipped_warmup += 1
            continue

        # Decision time = flip_init (bar close), fill = flip_init + 30s
        fill_ts = flip_init + 30 * 1_000_000_000
        # First 1s bar with ts_event >= fill_ts
        idx_1s = np.searchsorted(bars_ts, fill_ts, side="left")
        if idx_1s >= len(bars_ts):
            continue
        # Slippage cap: skip if first 1s bar > fill_ts + 60s
        if bars_ts[idx_1s] - fill_ts > 60 * 1_000_000_000:
            continue
        actual_fill_ts = int(bars_ts[idx_1s])
        fill_price = float(bars_o[idx_1s])

        # CAUSAL: state at flip moment must come from 5s bar that
        # has CLOSED by flip_init. 5s bar at index i closes at
        # bars_5s_ts[i] + 5s (ts_event + bucket size).
        state_idx = int(np.searchsorted(
            bars_5s_ts + 5 * int(1e9), flip_init,
            side="right")) - 1
        if state_idx < 0:
            continue
        state_at_flip = int(bars_5s_state[state_idx])
        if state_at_flip < 0:
            continue

        # Dwell time: how many consecutive prior 5s bars in same state
        dwell = 0
        i = state_idx
        while i >= 0 and bars_5s_state[i] == state_at_flip:
            dwell += 1
            i -= 1
        dwell_s = dwell * 5

        # State 30s before flip (for transition info)
        prior_idx = np.searchsorted(
            bars_5s_ts, flip_init - 30 * 1_000_000_000,
            side="right") - 1
        prior_state = (int(bars_5s_state[prior_idx])
                        if prior_idx >= 0 else -1)
        recent_transition = (
            state_at_flip != prior_state and prior_state >= 0)

        # Walk outcome
        outcome = walk_outcome(
            bars_ts, bars_h, bars_l, bars_o,
            actual_fill_ts, fill_price, atr, d,
            max_horizon_s=1800)

        records.append({
            "flip_bar_ts_event": flip_ts,
            "flip_bar_ts_init": flip_init,
            "direction": d,
            "atr": atr,
            "fill_ts_ns": actual_fill_ts,
            "fill_price": fill_price,
            "fill_slip_s": (actual_fill_ts - fill_ts) / 1e9,
            "state": state_at_flip,
            "prior_state_30s": prior_state,
            "dwell_s": dwell_s,
            "recent_transition": recent_transition,
            "hhll_confirmed": bool(row["hhll_confirmed"]),
            "outcome": outcome["outcome"],
            "resolution_s": outcome["resolution_time_s"],
            "exit_price": outcome["exit_price"],
        })
    elapsed = time.time() - t0
    print(f"    Walked {len(records):,} raw-flip trades "
           f"({elapsed:.0f}s, skipped {skipped_warmup} for warmup)")

    rec = pd.DataFrame(records)
    # Compute per-trade PnL with cost model
    rec["pnl_raw"] = (rec["exit_price"] - rec["fill_price"]).abs()
    # Apply direction and signs based on outcome
    is_win = rec["outcome"] == "pt"
    is_sl = rec["outcome"] == "sl"
    rec["pnl_dollars"] = 0.0
    rec.loc[is_win, "pnl_dollars"] = (
        1.0 * rec.loc[is_win, "atr"] * NQ_MULT
        - COMMISSION - TICK_COST)
    rec.loc[is_sl, "pnl_dollars"] = (
        -1.0 * rec.loc[is_sl, "atr"] * NQ_MULT
        - COMMISSION - 2 * TICK_COST)
    is_unres = rec["outcome"] == "unresolved"
    # For unresolved at flip, use exit_price - fill_price * direction * 20
    if is_unres.any():
        rec.loc[is_unres, "pnl_dollars"] = (
            (rec.loc[is_unres, "exit_price"]
             - rec.loc[is_unres, "fill_price"])
            * rec.loc[is_unres, "direction"] * NQ_MULT
            - COMMISSION - TICK_COST)

    rec.to_parquet(OUT / "rawflip_state_outcomes_2025.parquet",
                     index=False)
    print(f"    Saved: {OUT / 'rawflip_state_outcomes_2025.parquet'}")
    print(f"\n    OUTCOME MIX (raw flips, 2025 RTH):")
    print(rec["outcome"].value_counts())


if __name__ == "__main__":
    main()
