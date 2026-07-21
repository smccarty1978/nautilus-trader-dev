"""For each filtered V_A trade (total_excursion_slow=mid), compute
rolling excursion features at fixed checkpoints during the trade.

Checkpoints:
  - entry  (== decision_ts; features already computed pre-entry)
  - +2 min after entry
  - +3 min after entry
  - +5 min after entry
  - +10 min after entry
  - halfway to regime-flip exit (entry_ts + (exit_ts-entry_ts)/2)

For each checkpoint t in [entry, exit], compute features using ONLY
1s bars with ts_event < t (causality enforced):

Per window (5m fast / 15m medium / 30m slow):
  anchor_open = OPEN of first 1s bar at-or-after (t - window)
  high_max, low_min over window strictly before t
  close_now = close of last 1s bar with ts_event < t

Direction-aware:
  long:  mfe = high_max - anchor_open ; mae = anchor_open - low_min
  short: mfe = anchor_open - low_min  ; mae = high_max - anchor_open

  ratio = mfe / max(mae, 0.25)
  total_excursion = mfe + mae
  efficiency = abs(close_now - anchor_open) / max(total_excursion, 0.25)
  net_move = close_now - anchor_open  (sign per direction)

Plus current trade-state features:
  current_mfe_atr = (max favorable price excursion since entry) / atr_at_signal
  current_mae_atr = (max adverse price excursion since entry) / atr_at_signal
  unrealized_pnl_dollars

Each trade row includes the eventual outcome category for downstream
diagnostics:
  runner       : final MFE_atr >= 3.0  (eventual winner)
  winner       : net_pnl > 0 AND final MFE_atr < 3.0  (rare for V_A)
  loser_doa    : net_pnl <= 0 AND final MFE_atr < 0.25
  loser_subatr : net_pnl <= 0 AND 0.25 <= final MFE_atr < 1.0
  loser_giveback: net_pnl <= 0 AND final MFE_atr >= 1.0
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

NQ_MULT = 20.0

WINDOWS = {
    # Coarse (1m-resolution intent — 5/15/30 min)
    "fast":    5 * 60,
    "medium": 15 * 60,
    "slow":   30 * 60,
    # Fine (30s-resolution intent — 5×30s / 15×30s / 30×30s
    # = 2.5 / 7.5 / 15 min)
    "xfast":   5 * 30,    # 150 s
    "xmedium": 15 * 30,   # 450 s
    "xslow":   30 * 30,   # 900 s
}
CHECKPOINTS = [
    ("entry", 0),       # at decision_ts
    ("+2m", 120),
    ("+3m", 180),
    ("+5m", 300),
    ("+10m", 600),
]
# halfway computed per trade

OUT = Path("studies/v_a_excursion_regime/results_v0")
OUT.mkdir(parents=True, exist_ok=True)


def compute_tertile_cuts(dfs):
    is_combined = pd.concat(
        [dfs[yr] for yr in (2024, 2025) if yr in dfs], ignore_index=True)
    return is_combined["total_excursion_slow"].quantile([1/3, 2/3]).values


def tertile_label(v, lo, hi):
    if pd.isna(v): return np.nan
    if v < lo: return "low"
    if v < hi: return "mid"
    return "high"


def categorize_outcome(row):
    final_mfe_atr = row["running_mfe"] / max(row["atr_at_signal"], 0.01)
    if row["net_pnl"] > 0 and final_mfe_atr >= 3.0:
        return "runner"
    if row["net_pnl"] > 0:
        return "winner"
    if final_mfe_atr < 0.25:
        return "loser_doa"
    if final_mfe_atr < 1.0:
        return "loser_subatr"
    return "loser_giveback"


def load_year_bars(year: int):
    """Load v.0 1s bars covering [start_of_year-2d, end_of_year]."""
    parts = []
    if year == 2024:
        files = ["data/raw/NQ_v0_1s_2023.parquet",
                  "data/raw/NQ_v0_1s_2024.parquet"]
    elif year == 2025:
        files = ["data/raw/NQ_v0_1s_2024.parquet",
                  "data/raw/NQ_v0_1s_2025.parquet"]
    else:  # 2026
        files = ["data/raw/NQ_v0_1s_2025.parquet",
                  "data/raw/NQ_v0_1s_2026_ytd.parquet"]
    for f in files:
        if Path(f).exists():
            df = pd.read_parquet(f, columns=["open","high","low","close"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            parts.append(df)
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    return bars


def compute_window_features(direction, anchor_open, high_max, low_min,
                              close_now):
    if direction == 1:
        mfe = high_max - anchor_open
        mae = anchor_open - low_min
    else:
        mfe = anchor_open - low_min
        mae = high_max - anchor_open
    ratio = mfe / max(mae, 0.25)
    total_exc = mfe + mae
    eff = abs(close_now - anchor_open) / max(total_exc, 0.25)
    net = (close_now - anchor_open) if direction == 1 else (anchor_open - close_now)
    return mfe, mae, ratio, total_exc, eff, net


def features_at_checkpoint(checkpoint_ts_ns, direction, atr,
                              ts_index_ns, opens, highs, lows, closes,
                              entry_ts_ns, fill_price):
    """Compute 5/15/30 window features and trade-state features at
    checkpoint_ts_ns. Returns dict.
    """
    out = {}

    # Per-window pre-checkpoint excursion features
    for win_name, win_secs in WINDOWS.items():
        win_start_ns = checkpoint_ts_ns - win_secs * 1_000_000_000
        i_lo = np.searchsorted(ts_index_ns, win_start_ns, side="left")
        i_hi = np.searchsorted(ts_index_ns, checkpoint_ts_ns, side="left")
        if i_hi - i_lo < 60:
            for k in ("mfe", "mae", "ratio", "total_excursion",
                       "efficiency", "net_move"):
                out[f"{k}_{win_name}"] = np.nan
            continue
        anchor_open = float(opens[i_lo])
        hi = float(highs[i_lo:i_hi].max())
        lo = float(lows[i_lo:i_hi].min())
        close_now = float(closes[i_hi - 1])
        mfe, mae, ratio, te, eff, net = compute_window_features(
            direction, anchor_open, hi, lo, close_now)
        out[f"mfe_{win_name}"] = mfe
        out[f"mae_{win_name}"] = mae
        out[f"ratio_{win_name}"] = ratio
        out[f"total_excursion_{win_name}"] = te
        out[f"efficiency_{win_name}"] = eff
        out[f"net_move_{win_name}"] = net

    # Trade-state features (only valid if checkpoint > entry)
    if checkpoint_ts_ns >= entry_ts_ns:
        j_lo = np.searchsorted(ts_index_ns, entry_ts_ns, side="left")
        j_hi = np.searchsorted(ts_index_ns, checkpoint_ts_ns, side="left")
        if j_hi > j_lo:
            seg_h = highs[j_lo:j_hi]
            seg_l = lows[j_lo:j_hi]
            seg_c = closes[j_hi - 1]
            if direction == 1:
                cur_mfe = float(seg_h.max() - fill_price)
                cur_mae = float(fill_price - seg_l.min())
                unrealized_pts = float(seg_c - fill_price)
            else:
                cur_mfe = float(fill_price - seg_l.min())
                cur_mae = float(seg_h.max() - fill_price)
                unrealized_pts = float(fill_price - seg_c)
            out["current_mfe_atr"] = cur_mfe / max(atr, 0.01)
            out["current_mae_atr"] = cur_mae / max(atr, 0.01)
            out["unrealized_pnl"] = unrealized_pts * NQ_MULT
            out["close_now"] = float(seg_c)
        else:
            out["current_mfe_atr"] = 0.0
            out["current_mae_atr"] = 0.0
            out["unrealized_pnl"] = 0.0
            out["close_now"] = np.nan
    else:
        out["current_mfe_atr"] = np.nan
        out["current_mae_atr"] = np.nan
        out["unrealized_pnl"] = np.nan
        out["close_now"] = np.nan
    return out


def process_year(year, lo_cut, hi_cut):
    print(f"\n=== {year} ===")
    p = OUT / f"v_a_v0_{year}_with_excursion.parquet"
    df = pd.read_parquet(p)
    df["bkt"] = df["total_excursion_slow"].apply(
        lambda v: tertile_label(v, lo_cut, hi_cut))
    filtered = df[df["bkt"] == "mid"].copy()
    filtered["outcome"] = filtered.apply(categorize_outcome, axis=1)
    print(f"  filtered trades: {len(filtered):,}")
    print(f"  outcome distribution:")
    for cat, n in filtered["outcome"].value_counts().items():
        print(f"    {cat}: {n:,} ({100*n/len(filtered):.1f}%)")

    bars = load_year_bars(year)
    ts_index_ns = bars.index.astype("int64").to_numpy()
    opens = bars["open"].values.astype(np.float64)
    highs = bars["high"].values.astype(np.float64)
    lows = bars["low"].values.astype(np.float64)
    closes = bars["close"].values.astype(np.float64)

    rows = []
    t0 = time.time()
    for i, tr in filtered.iterrows():
        entry_ns = int(tr["entry_ts"])
        exit_ns = int(tr["exit_ts"])
        decision_ns = int(tr["decision_ts"])
        direction = int(tr["direction"])
        atr = float(tr["atr_at_signal"])
        fill_px = float(tr["fill_price"])

        # Build checkpoint list including 'halfway'
        halfway_ns = (entry_ns + exit_ns) // 2
        cps = [(name, entry_ns + dsec * 1_000_000_000)
                for name, dsec in CHECKPOINTS]
        cps.append(("halfway", halfway_ns))
        # Also include the actual exit ts -1s for reference
        cps.append(("at_exit", exit_ns - 1_000_000_000))

        for cp_name, cp_ts in cps:
            # Skip if checkpoint is past exit
            if cp_ts > exit_ns:
                continue
            # All checkpoints must be < exit_ts strictly
            cp_ts = min(cp_ts, exit_ns - 1)

            f = features_at_checkpoint(
                cp_ts, direction, atr, ts_index_ns,
                opens, highs, lows, closes, entry_ns, fill_px)

            row = {
                "year": year,
                "trade_idx": i,
                "checkpoint": cp_name,
                "checkpoint_ts": cp_ts,
                "entry_ts": entry_ns,
                "exit_ts": exit_ns,
                "decision_ts": decision_ns,
                "direction": direction,
                "atr_at_signal": atr,
                "fill_price": fill_px,
                "outcome": tr["outcome"],
                "net_pnl": tr["net_pnl"],
                "gross_pnl": tr["gross_pnl"],
                "hold_s": tr["hold_s"],
                "final_mfe_atr": tr["running_mfe"] / max(atr, 0.01),
                "final_mae_atr": tr["running_mae"] / max(atr, 0.01),
                **f,
            }
            rows.append(row)

        if i and i % 500 == 0:
            print(f"    {i}/{len(filtered)}  elapsed {time.time()-t0:.0f}s")

    out_df = pd.DataFrame(rows)
    print(f"  done in {time.time()-t0:.0f}s   total checkpoint rows: {len(out_df):,}")
    out_path = OUT / f"v_a_v0_{year}_checkpoints.parquet"
    out_df.to_parquet(out_path)
    print(f"  wrote {out_path}")
    return out_df


def main():
    t0 = time.time()
    print("=" * 78)
    print("V_A filtered trade checkpoint feature computation")
    print("=" * 78)

    dfs = {}
    for yr in (2024, 2025, 2026):
        p = OUT / f"v_a_v0_{yr}_with_excursion.parquet"
        dfs[yr] = pd.read_parquet(p)
    lo_cut, hi_cut = compute_tertile_cuts(dfs)
    print(f"\nTertile cuts on total_excursion_slow (2024+2025): "
          f"low/mid={lo_cut:.2f}, mid/high={hi_cut:.2f}")

    for yr in (2024, 2025, 2026):
        process_year(yr, lo_cut, hi_cut)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
