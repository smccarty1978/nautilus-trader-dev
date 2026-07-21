"""Build training dataset for the NEW exit model.

Question the new model answers (target B):
  At in-trade decision time T (entry+60s, +120s, ..., +540s):
  Will holding for another 120 seconds beat exiting now?

Label:
  1 if (open_at_T+120s - open_at_T) * direction > 0
  0 otherwise

Trade-state features at decision time T (NOT entry-time features):
  unrealized_pts          (open_at_T - entry_price) * d
  unrealized_atr          ditto / atr
  mfe_pts                 max favorable excursion since entry
  mae_pts                 max adverse excursion since entry
  mfe_atr, mae_atr        ditto / atr
  mfe_mae_ratio
  current_p_T1            OOS p_T1 at this candidate moment (or NaN)
  has_candidate           1 if candidate exists at this 1m close
  p_T1_change             current_p_T1 - entry_p_T1 (NaN if missing)
  micro_close_loc_30s_dir as of this in-trade bar
  micro_alignment_count   regime_5s + regime_15s + regime_30s == d
  regime_1m_now_d         is 1m regime in our direction NOW?
  regime_flipped_to_d     regime_1m flipped to d at any point since entry
  bars_since_entry        elapsed_s / 60
  direction               +1 / -1

Scope: top 50% T-1 fires (p_T1 >= 0.0770), non-VA-confirmed only.
Walk-forward training same as T-1: scored monthly starting 2024-04.
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from bracket_2025_2026 import COLLECTOR_DIR, PRE_FLIP_OOS
from bracket_grid_2024_2025 import apply_roll_filter_year


PRE_FLIP_CANDIDATES = ("studies/v_a_excursion_regime/results_v0/"
                          "pre_flip_candidates_augmented.parquet")
OUT_DIR = Path("studies/v_a_excursion_regime/results_v0/exit_model")
ONE_S_BAR_PATHS = {
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}
TOP50_THRESHOLD = 0.0991   # CHANGED: now top-10% gate (was 0.0770).
                                   # Aligns training distribution with
                                   # deployment population. Smaller
                                   # dataset (~90K rows) but more relevant.
DECISION_OFFSETS_S = [60, 120, 180, 240, 300, 360, 420, 480, 540]
LABEL_HORIZON_S = 120


def load_year_bars(year):
    bars = pd.read_parquet(ONE_S_BAR_PATHS[year],
                              columns=["open", "high", "low", "close"])
    bars.index = pd.to_datetime(bars.index, utc=True)
    bars = bars.sort_index()
    ts_arr = bars.index.view("int64")
    o = bars["open"].to_numpy().astype("float64")
    h = bars["high"].to_numpy().astype("float64")
    l = bars["low"].to_numpy().astype("float64")
    c = bars["close"].to_numpy().astype("float64")
    return ts_arr, o, h, l, c


def load_va_lookup(year):
    """Build set of (flip_bar_close_ts, direction) that VA-confirmed."""
    snap = pd.read_parquet(
        f"{COLLECTOR_DIR}/v_a_v0_{year}/snapshots_with_vol_vwap.parquet",
        columns=["kind", "decision_ts", "direction",
                   "became_trade", "session"])
    b1 = snap[(snap["kind"] == "bar1_check")
                  & (snap["became_trade"])
                  & (snap["session"] == "RTH")].copy()
    b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
    return set(zip(b1["flip_bar_close_ts"].astype("int64"),
                       b1["direction"].astype("int64")))


def load_regime_lookup(year):
    """Sparse regime state from collector snapshots.

    Snapshots fire at specific events (regime_flip, bar1_check,
    path_checkpoint) — NOT at every 1m bar close. Most 1m closes have
    NO snapshot. To get state at any in-trade 1m close, we use
    merge_asof(direction='backward') to find the last snapshot at or
    before that moment (CRITICAL-1 fix from audit).

    Returns DataFrame sorted by bar_close_ts (timestamp ns) with regime
    columns. Caller uses merge_asof against this.
    """
    snap = pd.read_parquet(
        f"{COLLECTOR_DIR}/v_a_v0_{year}/snapshots_with_vol_vwap.parquet",
        columns=["kind", "decision_ts", "session",
                   "regime_30s", "regime_1m", "regime_3m", "regime_5m",
                   "atr_1m",
                   "dist_close_to_ema3_h_1m_atr",
                   "dist_close_to_ema9_h_1m_atr",
                   "dist_close_to_ema3_l_1m_atr",
                   "dist_close_to_ema9_l_1m_atr",
                   "vol_delta_1m", "vol_imbalance_1m",
                   "bars_in_regime_1m"])
    # WARNING-A audit fix: use decision_ts directly. snapshot
    # decision_ts is the moment the regime state was determined
    # (bar's ts_init = ts_event + 1s). regime_age_s then correctly
    # measures (check_ts - snapshot_decision_ts) / 1e9.
    snap["bar_close_ts"] = snap["decision_ts"].astype("int64")
    snap = snap[snap["session"] == "RTH"].copy()
    snap = snap.sort_values("bar_close_ts").drop_duplicates(
        subset=["bar_close_ts"])
    return snap.reset_index(drop=True)


def lookup_regime_asof(regime_df, check_ts, direction):
    """Find latest regime snapshot at or before check_ts.

    Returns (regime_dict, found_bool). Empty dict if no prior snapshot.
    """
    ts_arr = regime_df["bar_close_ts"].to_numpy()
    idx = np.searchsorted(ts_arr, check_ts, side="right") - 1
    if idx < 0:
        return None, False
    row = regime_df.iloc[idx]
    return row, True


def build_for_year(year, oos, regime_lookup, va_set,
                       score_lookup):
    print(f"\n=== {year} ===")
    t0 = time.time()
    # Filter to top-N% candidates in this year, non-VA
    # (TOP50_THRESHOLD constant is now the deployment top-10% threshold)
    year_mask = (oos["year"] == year) & (oos["p_score"] >= TOP50_THRESHOLD)
    year_cands = oos[year_mask].copy()
    print(f"  top-gate candidates (p>={TOP50_THRESHOLD:.4f}): "
          f"{len(year_cands):,}")
    # Drop VA-confirmed. CRITICAL: candidate's close_ts_ns is the
    # PRE-flip (T-1) bar close. The flip happens at the NEXT 1m bar
    # (T), so we match (close_ts_ns + 60s, direction) against
    # flip_bar_close_ts in va_set. Matches build_schedule() in
    # bracket_2025_2026.py.
    year_cands["is_va"] = year_cands.apply(
        lambda r: (int(r["close_ts_ns"]) + 60_000_000_000,
                       int(r["direction"]))
            in va_set, axis=1)
    nva = year_cands[~year_cands["is_va"]].copy().reset_index(
        drop=True)
    print(f"  non-VA candidates: {len(nva):,}  "
          f"VA-rate dropped: {year_cands['is_va'].mean():.1%}")

    # Roll-day exclusion (audit Note): drop candidates within ±3d of
    # quarterly rolls. bracket_grid_2024_2025.apply_roll_filter_year
    # operates on a df with 'entry_ts_ns' column — alias close_ts_ns.
    nva["entry_ts_ns"] = nva["close_ts_ns"].astype("int64")
    n_pre = len(nva)
    nva, n_drop = apply_roll_filter_year(nva, year)
    print(f"  after roll-day filter: {len(nva):,} "
          f"(dropped {n_drop} within ±3d of quarterly rolls)")

    # Get atr_at_signal for each candidate from augmented candidates
    cands_aug = pd.read_parquet(
        PRE_FLIP_CANDIDATES,
        columns=["close_ts_ns", "candidate_direction", "atr_1m",
                   "close_1m"])
    cands_aug = cands_aug.rename(
        columns={"candidate_direction": "direction",
                   "atr_1m": "atr_at_signal",
                   "close_1m": "entry_close_1m"})
    nva = nva.merge(cands_aug, on=["close_ts_ns", "direction"],
                       how="left")
    nva = nva.dropna(subset=["atr_at_signal"])
    print(f"  after atr-merge: {len(nva):,}")

    # Load year bars
    ts_arr, bar_o, bar_h, bar_l, bar_c = load_year_bars(year)
    print(f"  bars loaded ({time.time()-t0:.0f}s)")

    rows = []
    for i, c in nva.iterrows():
        entry_ts = int(c["close_ts_ns"])
        d = int(c["direction"])
        atr = float(c["atr_at_signal"])
        entry_p_T1 = float(c["p_score"])

        entry_idx = int(np.searchsorted(ts_arr, entry_ts,
                                              side="right"))
        if entry_idx >= len(ts_arr):
            continue
        # WARNING-1 audit fix: assert fill bar is strictly AFTER
        # entry_ts so we never use a bar whose data spans BEFORE entry.
        # ts_arr[entry_idx] is the bar OPEN time of the fill bar.
        if int(ts_arr[entry_idx]) <= entry_ts:
            # Should not happen with side='right' but guard anyway
            continue
        entry_price = float(bar_o[entry_idx])

        # Track running MFE/MAE and regime flip
        running_max = entry_price
        running_min = entry_price
        regime_flipped_to_d = False
        prev_idx = entry_idx

        for elapsed_s in DECISION_OFFSETS_S:
            check_ts = entry_ts + elapsed_s * 1_000_000_000
            curr_idx = int(np.searchsorted(ts_arr, check_ts,
                                                  side="right"))
            if curr_idx >= len(ts_arr):
                break
            # Update running max/min over [entry_idx, curr_idx)
            if curr_idx > prev_idx:
                running_max = max(running_max,
                                       float(bar_h[prev_idx:curr_idx].max()))
                running_min = min(running_min,
                                       float(bar_l[prev_idx:curr_idx].min()))
            prev_idx = curr_idx

            current_price = float(bar_o[curr_idx])
            unrealized_pts = (current_price - entry_price) * d
            if d == 1:
                mfe_pts = max(running_max - entry_price, 0.0)
                mae_pts = max(entry_price - running_min, 0.0)
            else:
                mfe_pts = max(entry_price - running_min, 0.0)
                mae_pts = max(running_max - entry_price, 0.0)

            # Look up regime state at this in-trade bar's close
            # Use merge_asof-style search (CRITICAL-1 fix): find latest
            # snapshot at or before check_ts. Snapshots are sparse so
            # this may return state from minutes ago — we track staleness.
            regime_row, regime_found = lookup_regime_asof(
                regime_lookup, check_ts, d)
            regime_age_s = np.nan
            if regime_found:
                regime_age_s = (check_ts
                                  - int(regime_row["bar_close_ts"])) / 1e9
            if regime_found:
                regime_1m_now = int(regime_row["regime_1m"])
                regime_30s = int(regime_row["regime_30s"])
                regime_3m = int(regime_row["regime_3m"])
                regime_5m = int(regime_row["regime_5m"])
                bars_in_regime_1m = int(regime_row["bars_in_regime_1m"])
                if regime_1m_now == d:
                    regime_flipped_to_d = True
                # micro_alignment_count (sub-1m + 1m): {0,1,2}
                micro_count = ((regime_30s == d)
                                  + (regime_1m_now == d))
                # broader_alignment_count (slow TFs): {0,1,2}
                broader_count = ((regime_3m == d)
                                    + (regime_5m == d))
                # WARNING-B audit fix: NaN fallback for missing columns
                # (symmetric with no-snapshot rows, avoids "neutral
                # volume" misinterpretation)
                vol_delta_1m = float(
                    regime_row.get("vol_delta_1m", np.nan))
                vol_imbalance_1m = float(
                    regime_row.get("vol_imbalance_1m", np.nan))
                if d == 1:
                    dist_to_thr = float(
                        max(regime_row["dist_close_to_ema3_h_1m_atr"],
                              regime_row["dist_close_to_ema9_h_1m_atr"]))
                else:
                    dist_to_thr = float(
                        min(regime_row["dist_close_to_ema3_l_1m_atr"],
                              regime_row["dist_close_to_ema9_l_1m_atr"]))
            else:
                # No prior snapshot exists for this candidate window.
                # Set features to NaN (LightGBM handles missing) rather
                # than zeros — zero means "no alignment" which is a
                # specific value, not missing. Audit CRITICAL-1.
                regime_1m_now = -99  # sentinel
                regime_30s = regime_3m = regime_5m = -99
                micro_count = np.nan
                broader_count = np.nan
                bars_in_regime_1m = np.nan
                vol_delta_1m = np.nan
                vol_imbalance_1m = np.nan
                dist_to_thr = np.nan

            # T-1 NEW-CANDIDATE score at this in-trade bar.
            # CRITICAL-2 audit fix: clarified naming. This is NOT the
            # entry trade's T-1 score continuing in time. It's "if a
            # NEW T-1 candidate fires at this exact 1m close, what was
            # its score?" — i.e., does the model re-fire on this bar.
            # Almost always NaN (rare event); when present, encodes
            # consecutive momentum signal in same direction.
            new_cand_p_T1 = score_lookup.get((check_ts, d), np.nan)
            new_cand_fired = int(not np.isnan(new_cand_p_T1))
            new_cand_score_vs_entry = (
                new_cand_p_T1 - entry_p_T1
                if not np.isnan(new_cand_p_T1) else np.nan)

            # LABEL: 120s forward direction
            label_ts = check_ts + LABEL_HORIZON_S * 1_000_000_000
            label_idx = int(np.searchsorted(ts_arr, label_ts,
                                                  side="right"))
            if label_idx >= len(ts_arr):
                break
            future_price = float(bar_o[label_idx])
            label = int((future_price - current_price) * d > 0)

            rows.append({
                "entry_ts_ns": entry_ts,
                "elapsed_s": elapsed_s,
                "direction": d,
                "year": year,
                "atr_at_signal": atr,
                "entry_p_T1": entry_p_T1,
                "unrealized_pts": unrealized_pts,
                "unrealized_atr": unrealized_pts / atr,
                "mfe_pts": mfe_pts,
                "mae_pts": mae_pts,
                "mfe_atr": mfe_pts / atr,
                "mae_atr": mae_pts / atr,
                "mfe_mae_ratio": mfe_pts / max(mae_pts, 0.01),
                "new_cand_p_T1": new_cand_p_T1,
                "new_cand_fired": new_cand_fired,
                "new_cand_score_vs_entry": new_cand_score_vs_entry,
                "regime_age_s": regime_age_s,
                "micro_alignment_count": micro_count,
                "broader_alignment_count": broader_count,
                "regime_1m_now_d": int(regime_1m_now == d),
                "regime_flipped_to_d": int(regime_flipped_to_d),
                "bars_in_regime_1m": bars_in_regime_1m,
                "dist_to_flip_threshold_atr": dist_to_thr,
                "vol_delta_1m": vol_delta_1m,
                "vol_imbalance_1m": vol_imbalance_1m,
                "bars_since_entry": elapsed_s // 60,
                "label_B": label,
                "current_price": current_price,
                "entry_price": entry_price,
                "future_price": future_price,
            })

    df = pd.DataFrame(rows)
    print(f"  generated {len(df):,} rows  ({time.time()-t0:.0f}s)")
    print(f"  label-1 rate: {df['label_B'].mean():.1%}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_DIR / f"exit_model_data_{year}.parquet",
                      index=False)
    del ts_arr, bar_o, bar_h, bar_l, bar_c
    gc.collect()
    return df


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    oos = pd.read_parquet(PRE_FLIP_OOS)
    print(f"Total OOS predictions: {len(oos):,}")

    # Score lookup for current_p_T1 and rescore-style features
    print("Building score lookup...")
    score_lookup = {}
    for _, row in oos.iterrows():
        score_lookup[(int(row["close_ts_ns"]),
                          int(row["direction"]))] = float(row["p_score"])
    print(f"  {len(score_lookup):,} entries")

    # Per year: VA lookup + regime lookup + build features
    all_year_dfs = []
    for year in [2024, 2025, 2026]:
        print(f"\n--- Year {year} ---")
        print("  loading VA lookup...")
        va_set = load_va_lookup(year)
        print(f"    {len(va_set):,} VA-confirm (ts,d) tuples")
        print("  loading regime lookup...")
        regime_lookup = load_regime_lookup(year)
        print(f"    {len(regime_lookup):,} bar-close states")
        ydf = build_for_year(year, oos, regime_lookup, va_set,
                                  score_lookup)
        all_year_dfs.append(ydf)

    all_df = pd.concat(all_year_dfs, ignore_index=True)
    all_df.to_parquet(OUT_DIR / "exit_model_data_all.parquet",
                          index=False)
    print(f"\n{'='*78}")
    print(f"Combined dataset: {len(all_df):,} rows")
    print(f"  by year:")
    for yr in [2024, 2025, 2026]:
        yd = all_df[all_df["year"] == yr]
        print(f"    {yr}: {len(yd):,} rows  "
              f"label-1 rate {yd['label_B'].mean():.1%}")
    print(f"  by elapsed_s:")
    for es in DECISION_OFFSETS_S:
        ed = all_df[all_df["elapsed_s"] == es]
        print(f"    +{es:>3}s: {len(ed):,} rows  "
              f"label-1 rate {ed['label_B'].mean():.1%}")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
