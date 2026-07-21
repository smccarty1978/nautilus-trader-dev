"""Compute rolling MFE/MAE excursion features for V_A trades.

Layered analysis on the existing collector_v2 V_A corpus:
  - Trades from collectors/collector_v2/results/v_a_{year}/trades.parquet
  - Decision timestamps from snapshots.parquet (joined via decision_event_id)
  - 1s OHLCV from data/raw/NQ_v0_1s_{year}.parquet (NQ.v.0 — volume
    continuous, per memory rule)

For each trade, anchor at decision_ts (signal time, NOT entry_ts) and
look BACK over windows {fast=5min, medium=15min, slow=30min}.

Within each window:
  - Window covers [decision_ts - window, decision_ts) — STRICTLY before
  - anchor_open = OPEN of first 1s bar at or after (decision_ts - window)
  - last_feature_bar_ts = ts_event of LAST 1s bar with ts_event < decision_ts
  - high_max = max over window
  - low_min  = min over window
  - close_now = close of LAST 1s bar STRICTLY BEFORE decision_ts

For LONG trades (direction=+1):
  bull_mfe = high_max - anchor_open ; bull_mae = anchor_open - low_min
For SHORT trades (direction=-1):
  bear_mfe = anchor_open - low_min  ; bear_mae = high_max - anchor_open

Per window:
  ratio           = mfe / max(mae, 0.25)
  total_excursion = mfe + mae
  efficiency      = abs(close_now - anchor_open) / max(total_excursion, 0.25)
  net_move        = close_now - anchor_open

In-trade MFE/MAE (path reconstruction) over [entry_ts, exit_ts):
  trade_mfe / trade_mae from 1s bar high/low.

CAUSALITY (asserted per trade):
  last_feature_bar_ts < decision_ts <= entry_ts
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

WINDOWS = {
    "fast": 5 * 60,
    "medium": 15 * 60,
    "slow": 30 * 60,
}

OUT = Path("studies/v_a_excursion_regime/results_v0")
OUT.mkdir(parents=True, exist_ok=True)


def load_year_trades(year: int):
    """Load trades from v_a_v0_{year}/ — re-collected on the NQ.v.0
    multi-year catalog. The newer trades.parquet already has
    `decision_ts` as a direct column, so no snapshot merge needed.
    """
    base = Path(f"collectors/collector_v2/results/v_a_v0_{year}")
    trades = pd.read_parquet(base / "trades.parquet")
    if "decision_ts" not in trades.columns:
        # Fallback for older schema
        snaps = pd.read_parquet(base / "snapshots.parquet")
        snaps = snaps[snaps["became_trade"] == True][["event_id",
                                                          "decision_ts"]]
        trades = trades.merge(
            snaps, left_on="decision_event_id", right_on="event_id",
            how="left",
        )
    if trades["decision_ts"].isna().any():
        n = trades["decision_ts"].isna().sum()
        print(f"  WARN: {n} trades missing decision_ts")
    return trades


def load_v0_1s_for_year(year: int):
    """Load NQ.v.0 1s OHLCV for the year. For 2024 trades, the corpus
    spans late 2023 -> end 2024, so also load 2023 to cover lookback at
    the start of 2024."""
    parts = []
    if year == 2024:
        for f in ("data/raw/NQ_v0_1s_2023.parquet",
                  "data/raw/NQ_v0_1s_2024.parquet"):
            if Path(f).exists():
                df = pd.read_parquet(f, columns=["open", "high", "low", "close"])
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                parts.append(df)
    elif year == 2025:
        for f in ("data/raw/NQ_v0_1s_2024.parquet",
                  "data/raw/NQ_v0_1s_2025.parquet"):
            if Path(f).exists():
                df = pd.read_parquet(f, columns=["open", "high", "low", "close"])
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                parts.append(df)
    elif year == 2026:
        for f in ("data/raw/NQ_v0_1s_2025.parquet",
                  "data/raw/NQ_v0_1s_2026_ytd.parquet"):
            if Path(f).exists():
                df = pd.read_parquet(f, columns=["open", "high", "low", "close"])
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                parts.append(df)
    if not parts:
        raise FileNotFoundError(f"No NQ.v.0 1s data for {year}")
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    print(f"  loaded {len(bars):,} 1s bars covering "
          f"{bars.index.min()} -> {bars.index.max()}")
    return bars


def compute_features_for_trade(trade_row, ts_index_ns, opens, highs, lows,
                                  closes):
    """All windows and trade-MFE/MAE for one trade.

    Returns dict including causality safeguard logs.
    """
    decision_ts = int(trade_row["decision_ts"])
    entry_ts = int(trade_row["entry_ts"])
    exit_ts = int(trade_row["exit_ts"])
    direction = int(trade_row["direction"])
    # Note: don't repeat decision_ts/entry_ts/exit_ts here — they
    # already exist in the trades row. Keep window-specific safeguard
    # logs distinct (window_start_ts_*, last_feature_bar_ts_*).
    out = {}

    # --- Pre-decision excursion windows ---
    for win_name, win_secs in WINDOWS.items():
        win_start_ns = decision_ts - win_secs * 1_000_000_000
        # Bars with ts_event in [win_start, decision_ts)
        i_lo = np.searchsorted(ts_index_ns, win_start_ns, side="left")
        i_hi = np.searchsorted(ts_index_ns, decision_ts, side="left")
        if i_hi - i_lo < 60:
            for k in ("mfe", "mae", "ratio", "total_excursion",
                      "efficiency", "net_move", "n_bars"):
                out[f"{k}_{win_name}"] = np.nan
            out[f"window_start_ts_{win_name}"] = win_start_ns
            out[f"last_feature_bar_ts_{win_name}"] = np.nan
            continue
        anchor_open = float(opens[i_lo])
        high_max = float(highs[i_lo:i_hi].max())
        low_min = float(lows[i_lo:i_hi].min())
        close_now = float(closes[i_hi - 1])
        last_feature_bar_ts = int(ts_index_ns[i_hi - 1])

        # Causality assertion
        assert last_feature_bar_ts < decision_ts, (
            f"CAUSALITY VIOLATION: last_feature_bar_ts {last_feature_bar_ts} "
            f">= decision_ts {decision_ts} for {win_name}")
        assert decision_ts <= entry_ts, (
            f"CAUSALITY VIOLATION: decision_ts {decision_ts} > "
            f"entry_ts {entry_ts}")

        if direction == 1:
            mfe = high_max - anchor_open
            mae = anchor_open - low_min
        else:
            mfe = anchor_open - low_min
            mae = high_max - anchor_open
        ratio = mfe / max(mae, 0.25)
        total_exc = mfe + mae
        eff = abs(close_now - anchor_open) / max(total_exc, 0.25)
        net = close_now - anchor_open
        out[f"mfe_{win_name}"] = mfe
        out[f"mae_{win_name}"] = mae
        out[f"ratio_{win_name}"] = ratio
        out[f"total_excursion_{win_name}"] = total_exc
        out[f"efficiency_{win_name}"] = eff
        out[f"net_move_{win_name}"] = net
        out[f"n_bars_{win_name}"] = i_hi - i_lo
        out[f"window_start_ts_{win_name}"] = win_start_ns
        out[f"last_feature_bar_ts_{win_name}"] = last_feature_bar_ts

    # --- In-trade MFE/MAE via 1s path reconstruction [entry_ts, exit_ts) ---
    fill_px = float(trade_row["fill_price"])
    j_lo = np.searchsorted(ts_index_ns, entry_ts, side="left")
    j_hi = np.searchsorted(ts_index_ns, exit_ts, side="left")
    if j_hi > j_lo:
        seg_h = highs[j_lo:j_hi]
        seg_l = lows[j_lo:j_hi]
        if direction == 1:
            trade_mfe = float(seg_h.max() - fill_px)
            trade_mae = float(fill_px - seg_l.min())
        else:
            trade_mfe = float(fill_px - seg_l.min())
            trade_mae = float(seg_h.max() - fill_px)
        out["trade_mfe"] = trade_mfe
        out["trade_mae"] = trade_mae
        out["trade_mfe_to_mae"] = trade_mfe / max(trade_mae, 0.25)
        out["trade_path_n_bars"] = j_hi - j_lo
    else:
        out["trade_mfe"] = np.nan
        out["trade_mae"] = np.nan
        out["trade_mfe_to_mae"] = np.nan
        out["trade_path_n_bars"] = 0

    return out


def process_year(year: int):
    print(f"\n=== Processing year {year} ===")
    trades = load_year_trades(year)
    print(f"  trades: {len(trades):,}")
    if "decision_ts" not in trades.columns:
        print(f"  ERROR: no decision_ts column")
        return None

    bars = load_v0_1s_for_year(year)
    ts_index_ns = bars.index.astype("int64").to_numpy()
    opens = bars["open"].values.astype(np.float64)
    highs = bars["high"].values.astype(np.float64)
    lows = bars["low"].values.astype(np.float64)
    closes = bars["close"].values.astype(np.float64)

    feats = []
    n_violations = 0
    t0 = time.time()
    for i, row in trades.iterrows():
        if pd.isna(row.get("decision_ts")):
            feats.append({})
            continue
        try:
            f = compute_features_for_trade(
                row, ts_index_ns, opens, highs, lows, closes)
            feats.append(f)
        except AssertionError as e:
            n_violations += 1
            if n_violations <= 5:
                print(f"  ASSERTION FAIL trade {i}: {e}")
            feats.append({})
        if i and i % 500 == 0:
            print(f"    {i}/{len(trades)}  elapsed {time.time()-t0:.0f}s")
    feats_df = pd.DataFrame(feats)
    out_df = pd.concat([trades.reset_index(drop=True), feats_df], axis=1)
    print(f"  done in {time.time()-t0:.0f}s   causality violations: "
          f"{n_violations}")

    # Strip duplicate ts columns from feats (we want trade columns to win)
    if "decision_ts" in feats_df.columns and \
            "decision_ts_x" in out_df.columns:
        out_df = out_df.drop(columns=[c for c in out_df.columns
                                          if c.endswith("_y")])

    out_path = OUT / f"v_a_v0_{year}_with_excursion.parquet"
    out_df.to_parquet(out_path)
    print(f"  wrote {out_path}  ({len(out_df):,} rows, "
          f"{len(out_df.columns)} cols)")
    return out_df


def main():
    t0 = time.time()
    print("=" * 78)
    print("V_A Excursion Regime — feature computation (NQ.v.0 source)")
    print("=" * 78)
    summary = {}
    for yr in (2024, 2025, 2026):
        try:
            df = process_year(yr)
            summary[yr] = df
        except Exception as e:
            print(f"  ERROR year {yr}: {e}")
            import traceback; traceback.print_exc()

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")
    for yr, df in summary.items():
        if df is not None:
            n_complete = df["ratio_fast"].notna().sum() if \
                "ratio_fast" in df.columns else 0
            print(f"  {yr}: {len(df):,} trades, "
                  f"{n_complete:,} with all features "
                  f"({100*n_complete/len(df):.1f}%)")


if __name__ == "__main__":
    main()
