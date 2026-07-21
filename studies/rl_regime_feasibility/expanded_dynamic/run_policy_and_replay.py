"""Phase 5+6: Dynamic policy construction and exact 1s replay.

Phase 5: Train entry + exit models, tune thresholds on val set.
Phase 6: Run exact 1s replay on test set.

Produces:
  results/policy_thresholds.json
  results/replay_trades.parquet
  results/replay_summary.parquet
  results/bootstrap_ci.parquet
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import glob as _glob
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

OUT_DIR   = Path("studies/rl_regime_feasibility/expanded_dynamic/results")
FEAT_FILE = OUT_DIR / "expanded_features.parquet"
TGT_ENTRY = OUT_DIR / "entry_targets.parquet"
TGT_EXIT  = OUT_DIR / "exit_targets.parquet"
CATALOG   = "data/catalog/NQ_v0_2020_2026"

_MULT  = 20.0
_COMM  = 5.0
_ATR_STOP = 1.5
_MAX_H_NS = 300 * 1_000_000_000
_NS    = 1_000_000_000
_SEED  = 42

# Feature sets (from run_ablations.py)
_EXISTING_COLS = [
    "seconds_since_flip", "current_progress_atr", "max_progress_atr",
    "max_adverse_atr", "pullback_from_peak_atr", "seconds_since_peak",
    "progress_efficiency", "aligned_return_5s_atr", "aligned_return_15s_atr",
    "aligned_return_30s_atr", "aligned_return_60s_atr", "realized_vol_60s_atr",
    "range_5s_atr", "volume_5s_zscore", "volume_30s_vs_5m",
    "bollinger_width_percentile_1m", "bollinger_keltner_width_ratio_1m",
    "kalman_velocity_atr_per_s", "kalman_acceleration_atr_per_s2",
    "kalman_innovation_zscore", "ema3_ema9_spread_30s_atr",
    "regime_5s_aligned", "regime_30s_aligned", "regime_5m_aligned",
    "regime_age_1m_bars", "adx14_1m", "position_in_trailing_1m_range",
    "minutes_since_rth_open",
]
_DNA_COLS = [
    "atr_norm_at_flip", "atr_ratio_vs_60",
    "pre_5_return_atr", "pre_5_range_atr", "pre_5_body_sum_atr",
    "pre_5_realized_vol_atr", "pre_5_efficiency", "pre_5_chop_score",
    "pre_5_hh_ll_count", "pre_5_failed_breakout_count",
    "pre_5_range_ratio_vs_60", "pre_5_compression_score",
    "pre_5_expansion_score", "pre_5_lr_slope_atr",
    "pre_5_volume_ratio", "pre_5_volume_trend", "pre_5_volume_zscore",
    "pre_5_signed_volume_proxy",
    "pre_15_return_atr", "pre_15_range_atr", "pre_15_body_sum_atr",
    "pre_15_realized_vol_atr", "pre_15_efficiency", "pre_15_chop_score",
    "pre_15_hh_ll_count", "pre_15_failed_breakout_count",
    "pre_15_range_ratio_vs_60", "pre_15_compression_score",
    "pre_15_expansion_score", "pre_15_lr_slope_atr",
    "pre_15_volume_ratio", "pre_15_volume_trend", "pre_15_volume_zscore",
    "pre_15_signed_volume_proxy",
    "pre_30_return_atr", "pre_30_range_atr", "pre_30_body_sum_atr",
    "pre_30_realized_vol_atr", "pre_30_efficiency", "pre_30_chop_score",
    "pre_30_hh_ll_count", "pre_30_failed_breakout_count",
    "pre_30_range_ratio_vs_60", "pre_30_compression_score",
    "pre_30_expansion_score", "pre_30_lr_slope_atr",
    "pre_30_volume_ratio", "pre_30_volume_trend", "pre_30_volume_zscore",
    "pre_30_signed_volume_proxy",
    "ema9_slope_atr", "ema21_slope_atr", "slope_acceleration",
    "distance_from_ema9_atr", "distance_from_ema21_atr",
    "minutes_to_rth_close", "is_rth",
    "distance_to_vwap_atr", "distance_to_session_high_atr",
    "distance_to_session_low_atr", "distance_to_overnight_high_atr",
    "distance_to_overnight_low_atr",
]
_DERIVED_COLS = [
    "progress_sq_atr", "adverse_vs_peak_ratio", "progress_minus_adverse",
    "pb_severity_ratio", "current_vs_max_progress", "time_since_peak_ratio",
    "position_in_episode", "seconds_remaining",
    "vol_x_velocity", "vol_x_acceleration", "range_x_vol",
    "regime_alignment_score", "adx_x_progress", "adx_x_max_progress",
    "ema_spread_x_progress", "bb_x_vol",
    "progress_x_compression", "progress_x_pre5_eff", "progress_x_lr_slope",
    "pre_eff_5v15", "pre_vol_5v15", "pre_comp_5v30", "flip_momentum_qual", "pre_vol_accel",
    "kalman_aligned", "kalman_accel_aligned", "step_index_scaled",
]
# Exit-specific features (added when in positioned state)
_EXIT_EXTRA = ["unrealized_pnl_atr", "time_in_trade_s"]

_ENTRY_FEATURES = _EXISTING_COLS + _DNA_COLS + _DERIVED_COLS
_EXIT_FEATURES  = _ENTRY_FEATURES + _EXIT_EXTRA

_LGB_PARAMS = {
    "objective": "binary", "metric": "auc",
    "n_estimators": 400, "learning_rate": 0.05,
    "num_leaves": 63, "min_child_samples": 200,
    "subsample": 0.8, "colsample_bytree": 0.8,
    "reg_alpha": 0.1, "reg_lambda": 1.0,
    "random_state": _SEED, "n_jobs": -1, "verbose": -1,
}


# ── Price decoding ─────────────────────────────────────────────────────────────

def _decode_price(chunked_col) -> np.ndarray:
    parts = []
    for chunk in chunked_col.chunks:
        buf = chunk.buffers()[1]
        parts.append(np.frombuffer(buf, dtype="<i8"))
    return np.concatenate(parts).astype(np.float64) / 1e9


# ── Phase 5: Train models ──────────────────────────────────────────────────────

def train_entry_model(feat: pd.DataFrame, tgt: pd.DataFrame) -> tuple:
    print("\nPhase 5a: Training entry model ...")
    df = feat.merge(tgt[["observation_time", "y_entry_positive_300s"]], on="observation_time", how="inner")

    train = df[df["period"] == "train"]
    val   = df[df["period"] == "val"]
    test  = df[df["period"] == "test"]

    avail = [c for c in _ENTRY_FEATURES if c in df.columns]
    print(f"  Features: {len(avail)}/{len(_ENTRY_FEATURES)} available")

    X_tr, y_tr = train[avail].fillna(0).values, train["y_entry_positive_300s"].values
    X_vl, y_vl = val[avail].fillna(0).values, val["y_entry_positive_300s"].values

    model = lgb.LGBMClassifier(**_LGB_PARAMS)
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_vl, y_vl)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
    )

    val_prob  = model.predict_proba(X_vl)[:, 1]
    val_auc   = roc_auc_score(y_vl, val_prob)
    print(f"  Val AUC: {val_auc:.4f}")

    # Attach probabilities to full dataset
    all_X = df[avail].fillna(0).values
    all_prob = model.predict_proba(all_X)[:, 1]
    df = df.copy()
    df["entry_prob"] = all_prob

    return model, avail, df, val_auc


def train_exit_model(feat: pd.DataFrame, exit_tgt: pd.DataFrame) -> tuple:
    print("\nPhase 5b: Training exit model ...")
    df = feat.merge(
        exit_tgt[["observation_time", "y_exit_positive_60s", "unrealized_pnl_atr", "time_in_trade_s"]],
        on="observation_time", how="inner"
    )

    avail = [c for c in _EXIT_FEATURES if c in df.columns]
    print(f"  Features: {len(avail)}/{len(_EXIT_FEATURES)} available (incl exit extras)")

    train = df[df["period"] == "train"]
    val   = df[df["period"] == "val"]

    X_tr, y_tr = train[avail].fillna(0).values, train["y_exit_positive_60s"].values
    X_vl, y_vl = val[avail].fillna(0).values, val["y_exit_positive_60s"].values

    model = lgb.LGBMClassifier(**_LGB_PARAMS)
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_vl, y_vl)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
    )

    val_prob = model.predict_proba(X_vl)[:, 1]
    val_auc  = roc_auc_score(y_vl, val_prob)
    print(f"  Val AUC: {val_auc:.4f}")

    return model, avail, val_auc


def tune_thresholds(entry_model, entry_feats, feat_df, tgt_df) -> dict:
    """Tune entry + exit thresholds on val set to maximize val-period EV."""
    print("\nPhase 5c: Tuning thresholds on val set ...")

    val_feat = feat_df[feat_df["period"] == "val"]
    val_tgt  = tgt_df[tgt_df["period"] == "val"]
    df = val_feat.merge(val_tgt[["observation_time", "y_entry_adv_300s"]], on="observation_time", how="inner")

    avail = [c for c in entry_feats if c in df.columns]
    probs = entry_model.predict_proba(df[avail].fillna(0).values)[:, 1]
    df = df.copy()
    df["entry_prob"] = probs

    # For each episode in val, simulate: enter at first crossing, hold 300s
    ep_df = df.sort_values(["flip_time", "step_index"])

    best_ev  = float("-inf")
    best_thr = 0.50

    for thr in np.arange(0.40, 0.70, 0.01):
        trades = []
        for ep_id, grp in ep_df.groupby("episode_id"):
            crossings = grp[grp["entry_prob"] >= thr]
            if len(crossings) == 0:
                continue
            first = crossings.iloc[0]
            pnl = float(first["y_entry_adv_300s"]) if not math.isnan(float(first["y_entry_adv_300s"])) else 0.0
            trades.append(pnl)

        n_ep = ep_df["episode_id"].nunique()
        ev = sum(trades) / n_ep if n_ep > 0 else 0.0

        if ev > best_ev:
            best_ev  = ev
            best_thr = round(float(thr), 3)

    print(f"  Best entry threshold: {best_thr:.3f}  (val EV/ep = {best_ev:+.2f})")

    # Exit threshold: freeze at 0.5 (hold if confidence > 0.5, else exit)
    # The exit model predicts P(next 60s is positive), so:
    # - exit_prob < exit_thr => exit NOW
    # - exit_prob >= exit_thr => hold
    exit_thr = 0.50

    thresholds = {
        "entry_threshold": best_thr,
        "entry_val_ev":    round(best_ev, 4),
        "exit_threshold":  exit_thr,
        "entry_n_features": len([c for c in entry_feats if c in feat_df.columns]),
    }
    with open(OUT_DIR / "policy_thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=2)

    print(f"  Saved policy_thresholds.json")
    return thresholds


# ── Phase 6: Exact 1s replay ───────────────────────────────────────────────────

def load_1s_bars(obs_min_ns: int, obs_max_ns: int) -> tuple:
    print("\nPhase 6a: Loading 1s bars ...")
    pq_files = sorted(_glob.glob(str(Path(CATALOG) / "data/bar/NQ.XCME-1-SECOND-LAST-EXTERNAL/*.parquet")))
    if not pq_files:
        raise FileNotFoundError(f"No 1s parquet files in {CATALOG}")

    ns_start = obs_min_ns - 2 * 60 * _NS
    ns_end   = obs_max_ns + _MAX_H_NS + 600 * _NS

    tbl = pq.read_table(
        pq_files,
        columns=["ts_event", "open", "high", "low"],
        filters=[("ts_event", ">=", ns_start), ("ts_event", "<=", ns_end)],
    )
    ts_arr = tbl["ts_event"].combine_chunks().to_numpy().astype(np.int64)
    op_arr = _decode_price(tbl["open"])
    hi_arr = _decode_price(tbl["high"])
    lo_arr = _decode_price(tbl["low"])
    del tbl

    print(f"  {len(ts_arr):,} bars loaded")
    return ts_arr, op_arr, hi_arr, lo_arr


def _simulate_episode(
    obs_ts_arr: np.ndarray,  # sorted obs timestamps for this episode
    obs_prob_entry: np.ndarray,  # entry model prob at each obs
    obs_prob_exit: np.ndarray,   # exit model prob at each obs (may be None/nan before entry)
    direction: int,
    flip_close: float,
    atr: float,
    ep_end_ns: int,
    ts: np.ndarray,
    op: np.ndarray,
    hi: np.ndarray,
    lo: np.ndarray,
    entry_thr: float,
    exit_thr: float,
) -> dict:
    stop_px = flip_close - direction * _ATR_STOP * atr

    # Find first crossing (first obs where entry_prob >= entry_thr)
    entry_obs_idx = None
    for k, (obs_t, prob) in enumerate(zip(obs_ts_arr, obs_prob_entry)):
        if prob >= entry_thr:
            entry_obs_idx = k
            break

    if entry_obs_idx is None:
        return {"exit_reason": "no_entry", "pnl": 0.0, "entered": False}

    entry_obs_ts = int(obs_ts_arr[entry_obs_idx])

    # Find entry bar (first 1s bar at or after obs_ts)
    eidx = int(np.searchsorted(ts, entry_obs_ts, side="left"))
    if eidx >= len(ts):
        return {"exit_reason": "censored_entry", "pnl": 0.0, "entered": False}

    entry_ts = int(ts[eidx])
    entry_px = float(op[eidx])

    # Gap-through stop at entry bar open
    if direction == 1 and entry_px <= stop_px:
        pnl = direction * (entry_px - entry_px) * _MULT - _COMM
        return {"exit_reason": "stop_at_entry", "pnl": -_COMM, "entered": True,
                "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px}
    if direction == -1 and entry_px >= stop_px:
        return {"exit_reason": "stop_at_entry", "pnl": -_COMM, "entered": True,
                "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px}

    # Determine cap
    if ep_end_ns > 0 and ep_end_ns > entry_ts and ep_end_ns < entry_ts + _MAX_H_NS:
        cap_ns = int(ep_end_ns)
    else:
        cap_ns = entry_ts + _MAX_H_NS

    # Build per-obs exit prob map for obs AFTER entry
    obs_exit_map = {}
    for k in range(entry_obs_idx + 1, len(obs_ts_arr)):
        obs_t = int(obs_ts_arr[k])
        if obs_t > cap_ns:
            break
        prob_e = float(obs_prob_exit[k]) if k < len(obs_prob_exit) else float("nan")
        if not math.isnan(prob_e):
            obs_exit_map[obs_t] = prob_e

    # Walk bars
    cap_idx = int(np.searchsorted(ts, cap_ns, side="left"))

    for bar_i in range(eidx + 1, min(cap_idx + 2, len(ts))):
        if bar_i >= len(ts):
            break
        bar_ts = int(ts[bar_i])
        bar_o  = float(op[bar_i])
        bar_h  = float(hi[bar_i])
        bar_l  = float(lo[bar_i])

        if bar_ts > cap_ns:
            # Exit at cap (use bar open)
            exit_px = bar_o
            pnl = direction * (exit_px - entry_px) * _MULT - _COMM
            return {"exit_reason": "cap", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": exit_px}

        # Gap-through stop
        if direction == 1 and bar_o <= stop_px:
            pnl = direction * (bar_o - entry_px) * _MULT - _COMM
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": bar_o}
        if direction == -1 and bar_o >= stop_px:
            pnl = direction * (bar_o - entry_px) * _MULT - _COMM
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": bar_o}

        # Intrabar stop touch -> fill at NEXT bar open
        if direction == 1 and bar_l <= stop_px:
            next_px = float(op[bar_i + 1]) if bar_i + 1 < len(ts) else stop_px
            pnl = direction * (next_px - entry_px) * _MULT - _COMM
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": next_px}
        if direction == -1 and bar_h >= stop_px:
            next_px = float(op[bar_i + 1]) if bar_i + 1 < len(ts) else stop_px
            pnl = direction * (next_px - entry_px) * _MULT - _COMM
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": next_px}

        # Dynamic exit: obs at prev bar's close_ts triggers exit at this bar's open
        prev_obs_ts = bar_ts - _NS  # approximate: obs at bar_ts-1s close
        # Check if any observation up to this bar has low exit prob
        for obs_t, exit_prob in list(obs_exit_map.items()):
            if obs_t < bar_ts and exit_prob < exit_thr:
                # Exit at this bar's open
                exit_px = bar_o
                pnl = direction * (exit_px - entry_px) * _MULT - _COMM
                del obs_exit_map[obs_t]
                return {"exit_reason": "dynamic", "pnl": pnl, "entered": True,
                        "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                        "exit_ts": bar_ts, "exit_px": exit_px,
                        "exit_obs_prob": exit_prob}
            elif obs_t >= bar_ts:
                break

    # Fell off end of window
    last_idx = min(cap_idx, len(ts) - 1)
    exit_px = float(op[last_idx]) if last_idx > eidx else entry_px
    pnl = direction * (exit_px - entry_px) * _MULT - _COMM
    return {"exit_reason": "cap", "pnl": pnl, "entered": True,
            "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
            "exit_ts": int(ts[last_idx]) if last_idx < len(ts) else cap_ns,
            "exit_px": exit_px}


def run_replay(
    entry_model, entry_feats: list,
    exit_model, exit_feats: list,
    feat_df: pd.DataFrame,
    exit_tgt_df: pd.DataFrame,
    thresholds: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    t0 = time.time()
    print("\nPhase 6b: Running exact 1s replay on test set ...")

    entry_thr = thresholds["entry_threshold"]
    exit_thr  = thresholds["exit_threshold"]

    # Test period only
    test_feat = feat_df[feat_df["period"] == "test"].copy()
    test_exit = exit_tgt_df[exit_tgt_df["period"] == "test"].copy()
    print(f"  Test episodes: {test_feat['episode_id'].nunique():,}")
    print(f"  Test observations: {len(test_feat):,}")

    # Score entry model on all test observations
    avail_entry = [c for c in entry_feats if c in test_feat.columns]
    entry_probs = entry_model.predict_proba(test_feat[avail_entry].fillna(0).values)[:, 1]
    test_feat = test_feat.copy()
    test_feat["entry_prob"] = entry_probs

    # Score exit model on positioned-state observations
    # For exit: merge exit_tgt extra features into test_feat
    avail_exit = [c for c in exit_feats if c in test_feat.columns or c in test_exit.columns]
    test_exit_feat = test_feat.merge(
        test_exit[["observation_time", "unrealized_pnl_atr", "time_in_trade_s"]].drop_duplicates(),
        on="observation_time", how="left"
    )
    avail_exit_real = [c for c in avail_exit if c in test_exit_feat.columns]
    exit_probs = exit_model.predict_proba(test_exit_feat[avail_exit_real].fillna(0).values)[:, 1]
    test_feat["exit_prob"] = exit_probs

    # Load 1s bars
    obs_min_ns = int(test_feat["observation_time"].min())
    obs_max_ns = int(test_feat["observation_time"].max())
    ts_arr, op_arr, hi_arr, lo_arr = load_1s_bars(obs_min_ns, obs_max_ns)

    # Group by episode
    print(f"  Simulating episodes ...")
    episodes = test_feat.sort_values(["flip_time", "step_index"]).groupby("episode_id")

    trade_rows = []
    ep_rows    = []
    n_total    = test_feat["episode_id"].nunique()
    t_log      = time.time()

    for i, (ep_id, grp) in enumerate(episodes):
        grp = grp.sort_values("step_index")

        direction  = int(grp["direction"].iloc[0])
        flip_close = float(grp["flip_close"].iloc[0])
        atr        = float(grp["atr_at_flip"].iloc[0])
        ep_end_ns  = int(grp["episode_end_time"].iloc[0]) if grp["episode_end_time"].iloc[0] else 0
        flip_time  = int(grp["flip_time"].iloc[0])

        obs_ts   = grp["observation_time"].values.astype(np.int64)
        ep_entry = grp["entry_prob"].values
        ep_exit  = grp["exit_prob"].values

        result = _simulate_episode(
            obs_ts, ep_entry, ep_exit,
            direction, flip_close, atr, ep_end_ns,
            ts_arr, op_arr, hi_arr, lo_arr,
            entry_thr, exit_thr,
        )

        pnl = float(result.get("pnl", 0.0))
        ep_rows.append({
            "episode_id":     ep_id,
            "flip_time":      flip_time,
            "direction":      direction,
            "atr_at_flip":    atr,
            "entered":        result.get("entered", False),
            "exit_reason":    result.get("exit_reason", "no_entry"),
            "pnl":            pnl,
        })

        if result.get("entered", False):
            row = {
                "episode_id":    ep_id,
                "flip_time":     flip_time,
                "direction":     direction,
                "atr_at_flip":   atr,
                "flip_close":    flip_close,
                "entry_ts":      result.get("entry_ts", 0),
                "entry_px":      result.get("entry_px", float("nan")),
                "stop_px":       result.get("stop_px", float("nan")),
                "exit_ts":       result.get("exit_ts", 0),
                "exit_px":       result.get("exit_px", float("nan")),
                "exit_reason":   result.get("exit_reason", ""),
                "pnl":           pnl,
                "entry_prob":    float(ep_entry[0]) if len(ep_entry) > 0 else float("nan"),
                "ep_end_ns":     ep_end_ns,
            }
            trade_rows.append(row)

        if (i + 1) % 1000 == 0 or time.time() - t_log > 15:
            elapsed = time.time() - t0
            print(f"  {i+1:,}/{n_total:,} episodes ({100*(i+1)/n_total:.1f}%) | {elapsed:.0f}s")
            t_log = time.time()

    trades_df  = pd.DataFrame(trade_rows) if trade_rows else pd.DataFrame()
    ep_summary = pd.DataFrame(ep_rows)

    n_ep     = len(ep_summary)
    n_traded = ep_summary["entered"].sum()
    total_pnl = ep_summary["pnl"].sum()
    ev_per_ep = total_pnl / n_ep if n_ep > 0 else 0.0
    ev_traded = trades_df["pnl"].mean() if len(trades_df) > 0 else 0.0
    wr        = (trades_df["pnl"] > 0).mean() * 100 if len(trades_df) > 0 else 0.0

    print(f"\n  === REPLAY RESULTS ===")
    print(f"  Test episodes:   {n_ep:,}")
    print(f"  Traded:          {n_traded:,} ({100*n_traded/n_ep:.1f}%)")
    print(f"  Total PnL:       ${total_pnl:+,.0f}")
    print(f"  EV / episode:    ${ev_per_ep:+.2f}")
    print(f"  EV / trade:      ${ev_traded:+.2f}")
    print(f"  Win rate:        {wr:.1f}%")

    if len(trades_df) > 0:
        exit_dist = trades_df["exit_reason"].value_counts().to_dict()
        print(f"  Exit types:      {exit_dist}")

    # Bootstrap CI
    ep_pnl = ep_summary["pnl"].values
    rng = np.random.default_rng(_SEED)
    boot_means = []
    for _ in range(2000):
        sample = rng.choice(ep_pnl, size=len(ep_pnl), replace=True)
        boot_means.append(sample.mean())
    ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])
    print(f"  95% CI:          ({ci_lo:+.2f}, {ci_hi:+.2f})")

    # Monthly breakdown
    if len(trades_df) > 0 and "entry_ts" in trades_df.columns:
        trades_df["entry_month"] = pd.to_datetime(trades_df["entry_ts"], unit="ns").dt.to_period("M")
        monthly = trades_df.groupby("entry_month")["pnl"].agg(["mean", "sum", "count"])
        print(f"\n  Monthly PnL:")
        for m, row in monthly.iterrows():
            print(f"    {m}: EV/trade=${row['mean']:+.2f}  total=${row['sum']:+,.0f}  n={int(row['count'])}")

    # Summary record
    summary_dict = {
        "n_episodes":    n_ep,
        "n_traded":      int(n_traded),
        "trade_rate":    round(n_traded / n_ep, 4) if n_ep > 0 else 0.0,
        "total_pnl":     round(total_pnl, 2),
        "ev_per_episode": round(ev_per_ep, 4),
        "ev_per_trade":  round(ev_traded, 4),
        "win_rate":      round(wr / 100, 4),
        "ci_lo_95":      round(ci_lo, 4),
        "ci_hi_95":      round(ci_hi, 4),
        "entry_threshold": entry_thr,
        "exit_threshold":  exit_thr,
    }
    pd.DataFrame([summary_dict]).to_parquet(OUT_DIR / "replay_summary.parquet", index=False)

    if len(trades_df) > 0:
        trades_df.to_parquet(OUT_DIR / "replay_trades.parquet", index=False)

    # Bootstrap CI as parquet
    pd.DataFrame({
        "boot_mean": boot_means,
        "ci_lo_95": ci_lo,
        "ci_hi_95": ci_hi,
        "ev_per_episode": ev_per_ep,
    }).to_parquet(OUT_DIR / "bootstrap_ci.parquet", index=False)

    print(f"\n  Replay complete in {time.time()-t0:.1f}s")
    return trades_df, ep_summary


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    print("Loading data ...")
    feat_df    = pd.read_parquet(FEAT_FILE)
    entry_tgt  = pd.read_parquet(TGT_ENTRY)
    exit_tgt   = pd.read_parquet(TGT_EXIT)
    print(f"  feat: {feat_df.shape}, entry_tgt: {entry_tgt.shape}, exit_tgt: {exit_tgt.shape}")

    entry_model, entry_feats, entry_feat_df, entry_val_auc = train_entry_model(feat_df, entry_tgt)
    exit_model, exit_feats, exit_val_auc = train_exit_model(feat_df, exit_tgt)

    thresholds = tune_thresholds(entry_model, entry_feats, feat_df, entry_tgt)
    thresholds["entry_val_auc"] = round(entry_val_auc, 4)
    thresholds["exit_val_auc"]  = round(exit_val_auc, 4)
    with open(OUT_DIR / "policy_thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=2)
    print(f"\nPolicy thresholds: {thresholds}")

    trades_df, ep_summary = run_replay(
        entry_model, entry_feats,
        exit_model, exit_feats,
        feat_df, exit_tgt,
        thresholds,
    )
    return trades_df, ep_summary


if __name__ == "__main__":
    main()
    print("\nPhase 5+6 complete.")
