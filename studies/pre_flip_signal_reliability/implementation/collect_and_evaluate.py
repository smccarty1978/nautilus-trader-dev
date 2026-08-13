import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


def load_model_and_score(model_dir: Path, df_prep: pd.DataFrame) -> np.ndarray:
    """Loads feature order and joblib model, then computes scores."""
    feat_order_path = model_dir / "feature_order.csv"
    model_path = model_dir / "model.joblib"
    
    df_feats = pd.read_csv(feat_order_path)
    feat_names = df_feats["feature_name"].tolist()
    
    X = df_prep[feat_names].copy()
    model = joblib.load(model_path)
    
    if hasattr(model, "predict_proba"):
        scores = model.predict_proba(X)[:, 1]
    else:
        scores = model.decision_function(X)
    return scores


def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Filters dataframe to canonical Chicago RTH (08:30:00 to < 15:15:00)."""
    ts_dt = pd.to_datetime(df["observation_time"], unit="ns", utc=True).dt.tz_convert("America/Chicago")
    time_val = ts_dt.dt.time
    t_start = pd.to_datetime("08:30:00").time()
    t_end = pd.to_datetime("15:15:00").time()
    mask = (time_val >= t_start) & (time_val < t_end)
    return df[mask].copy()


def load_1s_bars(year: int) -> pd.DataFrame:
    """Loads 1s raw parquet bars for NQ futures."""
    path = Path(f"data/raw/NQ_v0_1s_{year}.parquet")
    if not path.exists():
        raise FileNotFoundError(f"Raw 1s bar file not found: {path}")
    df = pd.read_parquet(path)
    if "ts_event" not in df.columns and df.index.name == "ts_event":
        df = df.reset_index()
    if "ts_event" in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df["ts_event"]):
            df["ts_event"] = df["ts_event"].astype("int64")
    return df


def evaluate_direction(
    df_candidates: pd.DataFrame,
    direction_name: str,
    bars_dict: dict,
    percentiles: list
) -> pd.DataFrame:
    """Evaluates pre-flip signal reliability using ultra-fast fully-vectorized NumPy operations."""
    print(f"Evaluating {direction_name} model across {len(df_candidates)} RTH candidates...")
    
    df_cand = df_candidates.sort_values("observation_time").reset_index(drop=True)
    scores = df_cand["score"].values

    threshold_map = {pct: np.percentile(scores, 100.0 - pct) for pct in percentiles}

    bars_arrays = {}
    for yr, df_b in bars_dict.items():
        bars_arrays[yr] = {
            "ts": df_b["ts_event"].values,
            "open": df_b["open"].values,
            "high": df_b["high"].values,
            "low": df_b["low"].values,
            "close": df_b["close"].values
        }

    essential_cols = [c for c in ["regime_start_ns", "observation_time", "year", "entry_px", "fill_px", "atr_at_entry", "confirm_flip_ns", "score"] if c in df_cand.columns]

    all_signals = []
    for pct, thresh_val in threshold_map.items():
        df_sub = df_cand.loc[df_cand["score"] >= thresh_val, essential_cols]
        if len(df_sub) == 0:
            continue
        df_sigs = df_sub.groupby("regime_start_ns", as_index=False).first()
        df_sigs["threshold_pct"] = pct
        df_sigs["threshold_val"] = thresh_val
        all_signals.append(df_sigs)

    if not all_signals:
        return pd.DataFrame()

    df_all_sigs = pd.concat(all_signals, ignore_index=True)
    
    population_rows = []

    for year_val, df_yr_sigs in df_all_sigs.groupby("year"):
        yr_bars = bars_arrays.get(year_val)
        if yr_bars is None:
            continue

        ts_arr = yr_bars["ts"]
        high_arr = yr_bars["high"]
        low_arr = yr_bars["low"]
        close_arr = yr_bars["close"]
        open_arr = yr_bars["open"]

        sig_ts_arr = df_yr_sigs["observation_time"].values.astype(np.int64)
        reg_start_arr = df_yr_sigs["regime_start_ns"].values.astype(np.int64)
        
        has_confirm_col = "confirm_flip_ns" in df_yr_sigs.columns
        confirm_flip_arr = df_yr_sigs["confirm_flip_ns"].values.astype(np.float64) if has_confirm_col else np.full(len(df_yr_sigs), np.nan)
        
        sig_px_arr = (df_yr_sigs["entry_px"] if "entry_px" in df_yr_sigs.columns else df_yr_sigs["fill_px"]).values.astype(np.float64)
        atr_arr = df_yr_sigs["atr_at_entry"].values.astype(np.float64)
        score_arr = df_yr_sigs["score"].values.astype(np.float64)
        pct_arr = df_yr_sigs["threshold_pct"].values
        thresh_val_arr = df_yr_sigs["threshold_val"].values

        # FULLY VECTORIZED BINARY SEARCHES
        idx_sig_arr = np.searchsorted(ts_arr, sig_ts_arr)
        idx_reg_start_arr = np.searchsorted(ts_arr, reg_start_arr)
        
        has_flip_mask = ~np.isnan(confirm_flip_arr) & (confirm_flip_arr > sig_ts_arr)
        
        end_search_ts_arr = np.where(has_flip_mask, confirm_flip_arr, ts_arr[-1]).astype(np.int64)
        idx_reg_end_arr = np.searchsorted(ts_arr, end_search_ts_arr)

        # Pre-search flip target horizons
        idx_flip_arr = idx_reg_end_arr
        idx_30s_arr = np.searchsorted(ts_arr, confirm_flip_arr + 30_000_000_000)
        idx_60s_arr = np.searchsorted(ts_arr, confirm_flip_arr + 60_000_000_000)
        idx_120s_arr = np.searchsorted(ts_arr, confirm_flip_arr + 120_000_000_000)
        idx_300s_arr = np.searchsorted(ts_arr, confirm_flip_arr + 300_000_000_000)

        N = len(df_yr_sigs)
        for i in range(N):
            sig_ts = sig_ts_arr[i]
            reg_start_ts = reg_start_arr[i]
            has_flip = has_flip_mask[i]
            confirm_flip_ts = int(confirm_flip_arr[i]) if has_flip else None
            sig_px = sig_px_arr[i]
            atr_val = atr_arr[i]
            score_val = score_arr[i]
            pct = pct_arr[i]
            thresh_val = thresh_val_arr[i]

            time_to_flip_s = (confirm_flip_ts - sig_ts) / 1e9 if has_flip else np.nan
            elapsed_regime_s = (sig_ts - reg_start_ts) / 1e9

            rem_mfe_pts, rem_mae_pts = 0.0, 0.0
            total_regime_mfe_pts = 0.0
            captured_regime_mfe_pts = 0.0
            path_mae_pts, path_mfe_pts = 0.0, 0.0
            flip_px = sig_px

            idx_reg_s = idx_reg_start_arr[i]
            idx_reg_e = idx_reg_end_arr[i]
            # Offset start index by +1 to prevent 1s intra-bar look-ahead leak of signal second
            idx_s = idx_sig_arr[i] + 1

            if idx_reg_s < len(ts_arr) and idx_reg_e <= len(ts_arr) and idx_reg_s < idx_reg_e:
                reg_highs = high_arr[idx_reg_s:idx_reg_e]
                reg_lows = low_arr[idx_reg_s:idx_reg_e]
                reg_open = open_arr[idx_reg_s]

                if idx_s < len(ts_arr) and idx_s < idx_reg_e:
                    rem_highs = high_arr[idx_s:idx_reg_e]
                    rem_lows = low_arr[idx_s:idx_reg_e]
                    flip_px = close_arr[min(idx_reg_e - 1, len(close_arr) - 1)]
                else:
                    rem_highs = np.array([sig_px])
                    rem_lows = np.array([sig_px])
                    flip_px = sig_px

                if direction_name == "short":
                    # Prevailing regime is Bullish (+1)
                    # Remaining prevailing MFE = max high after signal minus signal price
                    rem_mfe_pts = max(0.0, np.max(rem_highs) - sig_px)
                    rem_mae_pts = max(0.0, sig_px - np.min(rem_lows))
                    
                    total_regime_mfe_pts = max(0.0, np.max(reg_highs) - reg_open)
                    captured_regime_mfe_pts = max(0.0, sig_px - reg_open)
                    
                    # Trade direction path metrics for Short (-1)
                    path_mfe_pts = max(0.0, sig_px - np.min(rem_lows))
                    path_mae_pts = max(0.0, np.max(rem_highs) - sig_px)
                else:
                    # Prevailing regime is Bearish (-1)
                    # Remaining prevailing MFE = signal price minus min low after signal
                    rem_mfe_pts = max(0.0, sig_px - np.min(rem_lows))
                    rem_mae_pts = max(0.0, np.max(rem_highs) - sig_px)
                    
                    total_regime_mfe_pts = max(0.0, reg_open - np.min(reg_lows))
                    captured_regime_mfe_pts = max(0.0, reg_open - sig_px)
                    
                    # Trade direction path metrics for Long (+1)
                    path_mfe_pts = max(0.0, np.max(rem_highs) - sig_px)
                    path_mae_pts = max(0.0, sig_px - np.min(rem_lows))

            # Fast pre-searched horizon slices
            post_flip_mfe_30s, post_flip_mfe_60s, post_flip_mfe_120s, post_flip_mfe_300s = np.nan, np.nan, np.nan, np.nan
            if has_flip:
                i_flip = idx_flip_arr[i]
                i_30s = idx_30s_arr[i]
                i_60s = idx_60s_arr[i]
                i_120s = idx_120s_arr[i]
                i_300s = idx_300s_arr[i]

                if i_flip < i_30s <= len(ts_arr):
                    post_flip_mfe_30s = max(0.0, (flip_px - np.min(low_arr[i_flip:i_30s])) if direction_name == "short" else (np.max(high_arr[i_flip:i_30s]) - flip_px))
                if i_flip < i_60s <= len(ts_arr):
                    post_flip_mfe_60s = max(0.0, (flip_px - np.min(low_arr[i_flip:i_60s])) if direction_name == "short" else (np.max(high_arr[i_flip:i_60s]) - flip_px))
                if i_flip < i_120s <= len(ts_arr):
                    post_flip_mfe_120s = max(0.0, (flip_px - np.min(low_arr[i_flip:i_120s])) if direction_name == "short" else (np.max(high_arr[i_flip:i_120s]) - flip_px))
                if i_flip < i_300s <= len(ts_arr):
                    post_flip_mfe_300s = max(0.0, (flip_px - np.min(low_arr[i_flip:i_300s])) if direction_name == "short" else (np.max(high_arr[i_flip:i_300s]) - flip_px))

            pnl = (sig_px - flip_px) if direction_name == "short" else (flip_px - sig_px)
            if has_flip and time_to_flip_s <= 300.0:
                bucket = "Bucket A" if pnl > 0 else "Bucket B"
            else:
                bucket = "Bucket C"

            rem_mfe_atr = rem_mfe_pts / atr_val if atr_val > 0 else 0.0
            rem_mae_atr = rem_mae_pts / atr_val if atr_val > 0 else 0.0
            path_mae_atr = path_mae_pts / atr_val if atr_val > 0 else 0.0
            path_mfe_atr = path_mfe_pts / atr_val if atr_val > 0 else 0.0
            rem_mfe_pct = (rem_mfe_pts / total_regime_mfe_pts * 100.0) if total_regime_mfe_pts > 0 else 0.0
            captured_mfe_pct = (captured_regime_mfe_pts / total_regime_mfe_pts * 100.0) if total_regime_mfe_pts > 0 else 0.0

            population_rows.append({
                "direction": direction_name,
                "threshold_pct": pct,
                "threshold_val": thresh_val,
                "regime_start_ns": reg_start_ts,
                "signal_ts": sig_ts,
                "confirm_flip_ns": confirm_flip_ts if confirm_flip_ts else np.nan,
                "year": year_val,
                "bucket": bucket,
                "time_to_flip_s": time_to_flip_s,
                "elapsed_regime_s": elapsed_regime_s,
                "rem_mfe_pts": rem_mfe_pts,
                "rem_mfe_atr": rem_mfe_atr,
                "rem_mae_pts": rem_mae_pts,
                "rem_mae_atr": rem_mae_atr,
                "rem_mfe_pct": rem_mfe_pct,
                "captured_mfe_pct": captured_mfe_pct,
                "path_mae_pts": path_mae_pts,
                "path_mae_atr": path_mae_atr,
                "path_mfe_pts": path_mfe_pts,
                "path_mfe_atr": path_mfe_atr,
                "post_flip_mfe_30s_atr": (post_flip_mfe_30s / atr_val) if pd.notnull(post_flip_mfe_30s) and atr_val > 0 else np.nan,
                "post_flip_mfe_60s_atr": (post_flip_mfe_60s / atr_val) if pd.notnull(post_flip_mfe_60s) and atr_val > 0 else np.nan,
                "post_flip_mfe_120s_atr": (post_flip_mfe_120s / atr_val) if pd.notnull(post_flip_mfe_120s) and atr_val > 0 else np.nan,
                "post_flip_mfe_300s_atr": (post_flip_mfe_300s / atr_val) if pd.notnull(post_flip_mfe_300s) and atr_val > 0 else np.nan,
                "score": score_val
            })

    return pd.DataFrame(population_rows)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", choices=["short", "long", "all"], default="all")
    args = parser.parse_args()

    print(f"=== Pre-Flip Signal Reliability Study (Mode: {args.direction.upper()}) ===")
    
    out_dir = Path("studies/pre_flip_signal_reliability/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Load 1s price bars
    print("Loading 1s raw price bars for 2024 and 2025...")
    bars_dict = {
        2024: load_1s_bars(2024),
        2025: load_1s_bars(2025)
    }

    percentiles = [50.0, 40.0, 30.0, 25.0, 20.0, 15.0, 10.0, 7.5, 5.0, 2.5, 1.0]

    df_pop_short = pd.DataFrame()
    df_pop_long = pd.DataFrame()

    if args.direction in ["short", "all"]:
        print("Loading and scoring Short-RTH model candidates...")
        df_short_2024 = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2024.parquet")
        df_short_2025 = pd.read_parquet("studies/short_rth_enriched_volume_level_retrain/_work/prepared_2025.parquet")
        df_short = pd.concat([df_short_2024, df_short_2025], ignore_index=True)
        df_short = filter_rth(df_short)
        if "confirm_flip_ns" not in df_short.columns and "hit_opposing_flip" in df_short.columns and "exit_ts" in df_short.columns:
            df_short["confirm_flip_ns"] = np.where(df_short["hit_opposing_flip"], df_short["exit_ts"], np.nan)
        
        model_dir_short = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/short_bearish_flip_top25_current_reference")
        df_short["score"] = load_model_and_score(model_dir_short, df_short)
        df_pop_short = evaluate_direction(df_short, "short", bars_dict, percentiles)

    if args.direction in ["long", "all"]:
        print("Loading and scoring Long-RTH model candidates...")
        df_long_2024 = pd.read_parquet("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2024.parquet")
        df_long_2025 = pd.read_parquet("studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_2025.parquet")
        df_long = pd.concat([df_long_2024, df_long_2025], ignore_index=True)
        df_long = filter_rth(df_long)
        
        model_dir_long = Path("studies/freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_top25")
        df_long["score"] = load_model_and_score(model_dir_long, df_long)
        df_pop_long = evaluate_direction(df_long, "long", bars_dict, percentiles)

    df_pop_all = pd.concat([df_pop_short, df_pop_long], ignore_index=True)
    
    num_cols = [
        "threshold_pct", "threshold_val", "regime_start_ns", "signal_ts", "confirm_flip_ns",
        "time_to_flip_s", "elapsed_regime_s", "rem_mfe_pts", "rem_mfe_atr", "rem_mae_pts",
        "rem_mae_atr", "rem_mfe_pct", "captured_mfe_pct", "path_mae_pts", "path_mae_atr", "path_mfe_pts",
        "path_mfe_atr", "post_flip_mfe_30s_atr", "post_flip_mfe_60s_atr", "post_flip_mfe_120s_atr",
        "post_flip_mfe_300s_atr", "score"
    ]
    for c in num_cols:
        if c in df_pop_all.columns:
            df_pop_all[c] = pd.to_numeric(df_pop_all[c], errors="coerce")

    # Save signal_population.csv
    df_pop_all.to_csv(out_dir / "signal_population.csv", index=False)
    print(f"Saved signal_population.csv ({len(df_pop_all)} total signal observations)")


if __name__ == "__main__":
    main()
