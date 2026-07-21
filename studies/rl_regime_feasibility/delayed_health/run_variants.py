"""Phases 5-6-9: Run policy variants A-E, placebo delays, controls.

Variants:
  A: Unrestricted dynamic policy (reproduce -$0.66 baseline)
  B: Unconditional bar-4 entry
    B1: fixed 300s exit
    B2: dynamic exit model
  C: ML-selected entry at or after bar-4
    C1: fixed 300s exit
    C2: dynamic exit model (prior exit model)
  D: ML + causal KNN/kC entry at or after bar-4
    D2: dynamic exit model
  E: ML/KNN entry + entry-conditioned exit model

Controls:
  KNN shuffle, sequence shuffle, placebo delays, entry shuffle, 5s lag

Outputs:
  results/model_manifest.json
  results/validation_grid.parquet
  results/policy_thresholds.json
  results/variant_metrics.parquet
  results/variant_trades.parquet
  results/variant_episode_results.parquet
  results/delay_placebo_results.parquet
  results/control_results.parquet
  results/bootstrap_ci.parquet
  results/execution_audit.parquet
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

import glob as _glob
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

OUT_DIR = Path("studies/rl_regime_feasibility/delayed_health/results")
SNAP_FILE = Path("studies/rl_regime_feasibility/results/feature_snapshots.parquet")
CATALOG = "data/catalog/NQ_v0_2020_2026"
PREV_REPLAY = Path("studies/rl_regime_feasibility/expanded_dynamic/results")

_MULT = 20.0
_COMM = 5.0
_ATR_STOP = 1.5
_MAX_H_NS = 300 * 1_000_000_000
_NS = 1_000_000_000
_SEED = 42

BAR4_DELAY_S = 240
BAR4_STEP_INDEX = 48
PLACEBO_DELAYS = [60, 120, 180, 240, 300, 360]

_TICK = 0.25 * _MULT  # $5/tick

_BASELINE_FEATS = [
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

_KNN_FEATS = [
    "knn_hA", "knn_hB", "knn_hC", "knn_composite",
    "knn_mean_dist", "knn_n_eff", "knn_unique_eps", "knn_neighbor_agreement",
]

_DELAY_FEATS = [
    "seconds_since_flip",      # elapsed time
    "current_progress_atr",    # progress from flip at decision
    "max_progress_atr",        # max so far
    "max_adverse_atr",
    "pullback_from_peak_atr",
    "progress_efficiency",
    "regime_5s_aligned",
    "regime_30s_aligned",
    "regime_5m_aligned",
    "kalman_velocity_atr_per_s",
    "kalman_acceleration_atr_per_s2",
    "ema3_ema9_spread_30s_atr",
    "adx14_1m",
    "realized_vol_60s_atr",
    "range_5s_atr",
    "volume_5s_zscore",
]

_EXIT_EXTRA = ["unrealized_pnl_atr", "time_in_trade_s"]

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


def load_1s_bars(obs_min_ns: int, obs_max_ns: int) -> tuple:
    pq_files = sorted(_glob.glob(str(Path(CATALOG) / "data/bar/NQ.XCME-1-SECOND-LAST-EXTERNAL/*.parquet")))
    if not pq_files:
        raise FileNotFoundError(f"No 1s parquet files in {CATALOG}")
    ns_start = obs_min_ns - 2 * 60 * _NS
    ns_end = obs_max_ns + _MAX_H_NS + 600 * _NS
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
    return ts_arr, op_arr, hi_arr, lo_arr


# ── Core 1s replay engine ──────────────────────────────────────────────────────

def _simulate_episode(
    obs_ts_arr: np.ndarray,
    obs_prob_entry: np.ndarray,
    obs_prob_exit: np.ndarray,
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
    min_entry_step: int,       # bar-4 gating: don't allow entry before this step
    min_hold_s: int = 0,       # minimum hold before dynamic exit
    cost_extra_ticks: int = 0, # additional slippage ticks per side
) -> dict:
    stop_px = flip_close - direction * _ATR_STOP * atr
    extra_cost = cost_extra_ticks * 2 * _TICK  # both sides

    # Find first crossing at or after min_entry_step
    entry_obs_idx = None
    for k, (obs_t, prob) in enumerate(zip(obs_ts_arr, obs_prob_entry)):
        if k < min_entry_step:
            continue
        if prob >= entry_thr:
            entry_obs_idx = k
            break

    if entry_obs_idx is None:
        return {"exit_reason": "no_entry", "pnl": 0.0, "entered": False}

    entry_obs_ts = int(obs_ts_arr[entry_obs_idx])

    eidx = int(np.searchsorted(ts, entry_obs_ts, side="left"))
    if eidx >= len(ts):
        return {"exit_reason": "censored_entry", "pnl": 0.0, "entered": False}

    entry_ts = int(ts[eidx])
    entry_px = float(op[eidx])

    if direction == 1 and entry_px <= stop_px:
        return {"exit_reason": "stop_at_entry", "pnl": -_COMM - extra_cost, "entered": True,
                "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px}
    if direction == -1 and entry_px >= stop_px:
        return {"exit_reason": "stop_at_entry", "pnl": -_COMM - extra_cost, "entered": True,
                "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px}

    if ep_end_ns > 0 and ep_end_ns > entry_ts and ep_end_ns < entry_ts + _MAX_H_NS:
        cap_ns = int(ep_end_ns)
    else:
        cap_ns = entry_ts + _MAX_H_NS

    obs_exit_map = {}
    for k in range(entry_obs_idx + 1, len(obs_ts_arr)):
        obs_t = int(obs_ts_arr[k])
        if obs_t > cap_ns:
            break
        prob_e = float(obs_prob_exit[k]) if k < len(obs_prob_exit) else float("nan")
        if not math.isnan(prob_e):
            # Only allow exit after min_hold_s
            if obs_t - entry_ts >= min_hold_s * _NS:
                obs_exit_map[obs_t] = prob_e

    cap_idx = int(np.searchsorted(ts, cap_ns, side="left"))

    for bar_i in range(eidx + 1, min(cap_idx + 2, len(ts))):
        if bar_i >= len(ts):
            break
        bar_ts = int(ts[bar_i])
        bar_o = float(op[bar_i])
        bar_h = float(hi[bar_i])
        bar_l = float(lo[bar_i])

        if bar_ts > cap_ns:
            exit_px = bar_o
            pnl = direction * (exit_px - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "cap", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": exit_px,
                    "entry_obs_step": entry_obs_idx, "entry_delay_s": (entry_ts - obs_ts_arr[0])/1e9}

        if direction == 1 and bar_o <= stop_px:
            pnl = direction * (bar_o - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": bar_o,
                    "entry_obs_step": entry_obs_idx, "entry_delay_s": (entry_ts - obs_ts_arr[0])/1e9}
        if direction == -1 and bar_o >= stop_px:
            pnl = direction * (bar_o - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": bar_o,
                    "entry_obs_step": entry_obs_idx, "entry_delay_s": (entry_ts - obs_ts_arr[0])/1e9}

        if direction == 1 and bar_l <= stop_px:
            next_px = float(op[bar_i + 1]) if bar_i + 1 < len(ts) else stop_px
            pnl = direction * (next_px - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": next_px,
                    "entry_obs_step": entry_obs_idx, "entry_delay_s": (entry_ts - obs_ts_arr[0])/1e9}
        if direction == -1 and bar_h >= stop_px:
            next_px = float(op[bar_i + 1]) if bar_i + 1 < len(ts) else stop_px
            pnl = direction * (next_px - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                    "exit_ts": bar_ts, "exit_px": next_px,
                    "entry_obs_step": entry_obs_idx, "entry_delay_s": (entry_ts - obs_ts_arr[0])/1e9}

        for obs_t in sorted(obs_exit_map.keys()):
            if obs_t < bar_ts:
                if obs_exit_map[obs_t] < exit_thr:
                    exit_px = bar_o
                    pnl = direction * (exit_px - entry_px) * _MULT - _COMM - extra_cost
                    return {"exit_reason": "dynamic", "pnl": pnl, "entered": True,
                            "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
                            "exit_ts": bar_ts, "exit_px": exit_px,
                            "entry_obs_step": entry_obs_idx, "entry_delay_s": (entry_ts - obs_ts_arr[0])/1e9}
            else:
                break

    last_idx = min(cap_idx, len(ts) - 1)
    exit_px = float(op[last_idx]) if last_idx > eidx else entry_px
    pnl = direction * (exit_px - entry_px) * _MULT - _COMM - extra_cost
    return {"exit_reason": "cap", "pnl": pnl, "entered": True,
            "entry_ts": entry_ts, "entry_px": entry_px, "stop_px": stop_px,
            "exit_ts": int(ts[last_idx]) if last_idx < len(ts) else cap_ns,
            "exit_px": exit_px,
            "entry_obs_step": entry_obs_idx, "entry_delay_s": (entry_ts - obs_ts_arr[0])/1e9}


def _fixed_exit_episode(
    obs_ts_arr: np.ndarray,
    entry_prob: np.ndarray,
    direction: int,
    flip_close: float,
    atr: float,
    ep_end_ns: int,
    ts: np.ndarray,
    op: np.ndarray,
    hi: np.ndarray,
    lo: np.ndarray,
    entry_thr: float,
    min_entry_step: int,
    hold_s: int = 300,
    cost_extra_ticks: int = 0,
) -> dict:
    """Entry at threshold crossing (or unconditional at min_entry_step if thr=-inf),
    exit after fixed hold_s seconds or on stop/cap."""
    extra_cost = cost_extra_ticks * 2 * _TICK
    stop_px = flip_close - direction * _ATR_STOP * atr

    if entry_thr == float("-inf"):
        # Unconditional entry at min_entry_step
        entry_obs_idx = min_entry_step if min_entry_step < len(obs_ts_arr) else None
    else:
        entry_obs_idx = None
        for k, prob in enumerate(entry_prob):
            if k < min_entry_step:
                continue
            if prob >= entry_thr:
                entry_obs_idx = k
                break

    if entry_obs_idx is None:
        return {"exit_reason": "no_entry", "pnl": 0.0, "entered": False}

    entry_obs_ts = int(obs_ts_arr[entry_obs_idx])
    eidx = int(np.searchsorted(ts, entry_obs_ts, side="left"))
    if eidx >= len(ts):
        return {"exit_reason": "censored_entry", "pnl": 0.0, "entered": False}

    entry_ts = int(ts[eidx])
    entry_px = float(op[eidx])

    if direction == 1 and entry_px <= stop_px:
        return {"exit_reason": "stop_at_entry", "pnl": -_COMM - extra_cost, "entered": True,
                "entry_ts": entry_ts, "entry_px": entry_px,
                "entry_obs_step": entry_obs_idx}
    if direction == -1 and entry_px >= stop_px:
        return {"exit_reason": "stop_at_entry", "pnl": -_COMM - extra_cost, "entered": True,
                "entry_ts": entry_ts, "entry_px": entry_px,
                "entry_obs_step": entry_obs_idx}

    hold_cap_ns = entry_ts + hold_s * _NS
    if ep_end_ns > 0 and ep_end_ns > entry_ts:
        cap_ns = min(ep_end_ns, hold_cap_ns)
    else:
        cap_ns = hold_cap_ns

    cap_idx = int(np.searchsorted(ts, cap_ns, side="left"))

    for bar_i in range(eidx + 1, min(cap_idx + 2, len(ts))):
        if bar_i >= len(ts):
            break
        bar_ts = int(ts[bar_i])
        bar_o = float(op[bar_i])
        bar_h = float(hi[bar_i])
        bar_l = float(lo[bar_i])

        if bar_ts > cap_ns:
            pnl = direction * (bar_o - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "cap", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px,
                    "exit_ts": bar_ts, "exit_px": bar_o,
                    "entry_obs_step": entry_obs_idx}

        if direction == 1 and bar_o <= stop_px:
            pnl = direction * (bar_o - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px,
                    "exit_ts": bar_ts, "exit_px": bar_o,
                    "entry_obs_step": entry_obs_idx}
        if direction == -1 and bar_o >= stop_px:
            pnl = direction * (bar_o - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px,
                    "exit_ts": bar_ts, "exit_px": bar_o,
                    "entry_obs_step": entry_obs_idx}
        if direction == 1 and bar_l <= stop_px:
            next_px = float(op[bar_i + 1]) if bar_i + 1 < len(ts) else stop_px
            pnl = direction * (next_px - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px,
                    "exit_ts": bar_ts, "exit_px": next_px,
                    "entry_obs_step": entry_obs_idx}
        if direction == -1 and bar_h >= stop_px:
            next_px = float(op[bar_i + 1]) if bar_i + 1 < len(ts) else stop_px
            pnl = direction * (next_px - entry_px) * _MULT - _COMM - extra_cost
            return {"exit_reason": "stop", "pnl": pnl, "entered": True,
                    "entry_ts": entry_ts, "entry_px": entry_px,
                    "exit_ts": bar_ts, "exit_px": next_px,
                    "entry_obs_step": entry_obs_idx}

    last_idx = min(cap_idx, len(ts) - 1)
    exit_px = float(op[last_idx]) if last_idx > eidx else entry_px
    pnl = direction * (exit_px - entry_px) * _MULT - _COMM - extra_cost
    return {"exit_reason": "cap", "pnl": pnl, "entered": True,
            "entry_ts": entry_ts, "entry_px": entry_px,
            "exit_ts": int(ts[last_idx]) if last_idx < len(ts) else cap_ns,
            "exit_px": exit_px,
            "entry_obs_step": entry_obs_idx}


# ── Replay runner ──────────────────────────────────────────────────────────────

def run_replay_variant(
    feat_df: pd.DataFrame,
    entry_probs: np.ndarray,
    exit_probs: np.ndarray,
    ts_arr: np.ndarray,
    op_arr: np.ndarray,
    hi_arr: np.ndarray,
    lo_arr: np.ndarray,
    entry_thr: float,
    exit_thr: float,
    min_entry_step: int,
    variant_name: str,
    use_dynamic_exit: bool = True,
    hold_s: int = 300,
    cost_extra_ticks: int = 0,
    min_hold_s: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    t0 = time.time()
    feat_df = feat_df.copy()
    feat_df["entry_prob"] = entry_probs
    feat_df["exit_prob"] = exit_probs
    episodes = feat_df.sort_values(["flip_time", "step_index"]).groupby("episode_id")
    n_total = feat_df["episode_id"].nunique()

    trade_rows = []
    ep_rows = []

    for i, (ep_id, grp) in enumerate(episodes):
        grp = grp.sort_values("step_index")
        direction = int(grp["direction"].iloc[0])
        flip_close = float(grp["flip_close"].iloc[0])
        atr = float(grp["atr_at_flip"].iloc[0])
        ep_end_ns = int(grp["episode_end_time"].iloc[0]) if pd.notna(grp["episode_end_time"].iloc[0]) else 0
        flip_time = int(grp["flip_time"].iloc[0])

        obs_ts = grp["observation_time"].values.astype(np.int64)
        ep_entry = grp["entry_prob"].values
        ep_exit = grp["exit_prob"].values

        if use_dynamic_exit:
            result = _simulate_episode(
                obs_ts, ep_entry, ep_exit,
                direction, flip_close, atr, ep_end_ns,
                ts_arr, op_arr, hi_arr, lo_arr,
                entry_thr, exit_thr, min_entry_step,
                min_hold_s=min_hold_s,
                cost_extra_ticks=cost_extra_ticks,
            )
        else:
            result = _fixed_exit_episode(
                obs_ts, ep_entry,
                direction, flip_close, atr, ep_end_ns,
                ts_arr, op_arr, hi_arr, lo_arr,
                entry_thr, min_entry_step,
                hold_s=hold_s,
                cost_extra_ticks=cost_extra_ticks,
            )

        pnl = float(result.get("pnl", 0.0))
        ep_rows.append({
            "episode_id": ep_id, "flip_time": flip_time,
            "direction": direction, "atr_at_flip": atr,
            "entered": result.get("entered", False),
            "exit_reason": result.get("exit_reason", "no_entry"),
            "pnl": pnl, "variant": variant_name,
        })
        if result.get("entered", False):
            entry_ts = result.get("entry_ts", 0)
            trade_rows.append({
                "episode_id": ep_id, "flip_time": flip_time,
                "direction": direction, "atr_at_flip": atr,
                "flip_close": flip_close,
                "entry_ts": entry_ts,
                "entry_px": result.get("entry_px", float("nan")),
                "stop_px": result.get("stop_px", float("nan")),
                "exit_ts": result.get("exit_ts", 0),
                "exit_px": result.get("exit_px", float("nan")),
                "exit_reason": result.get("exit_reason", ""),
                "pnl": pnl,
                "entry_obs_step": result.get("entry_obs_step", min_entry_step),
                "entry_delay_s": result.get("entry_delay_s", BAR4_DELAY_S),
                "variant": variant_name,
                "cost_extra_ticks": cost_extra_ticks,
            })

    trades_df = pd.DataFrame(trade_rows) if trade_rows else pd.DataFrame()
    ep_df = pd.DataFrame(ep_rows)
    elapsed = time.time() - t0

    n_ep = len(ep_df)
    n_traded = ep_df["entered"].sum()
    total_pnl = ep_df["pnl"].sum()
    ev_ep = total_pnl / n_ep if n_ep > 0 else 0.0
    ev_tr = trades_df["pnl"].mean() if len(trades_df) > 0 else float("nan")
    wr = (trades_df["pnl"] > 0).mean() * 100 if len(trades_df) > 0 else 0.0

    # Bootstrap CI
    rng = np.random.default_rng(_SEED)
    boot_means = [rng.choice(ep_df["pnl"].values, size=n_ep, replace=True).mean() for _ in range(2000)]
    ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])

    print(f"  [{variant_name}] n_ep={n_ep:,} traded={n_traded} ({100*n_traded/max(n_ep,1):.1f}%)")
    print(f"    EV/ep={ev_ep:+.2f}  EV/tr={ev_tr:+.2f}  WR={wr:.1f}%  CI=({ci_lo:+.2f},{ci_hi:+.2f})")
    print(f"    Total=${total_pnl:+,.0f}  {elapsed:.1f}s")
    if len(trades_df) > 0:
        print(f"    Exits: {ep_df['exit_reason'].value_counts().to_dict()}")

    return trades_df, ep_df


# ── Model training helpers ─────────────────────────────────────────────────────

def train_model(feat_df: pd.DataFrame, target_col: str, feature_cols: list,
                label: str = "") -> tuple:
    avail = [c for c in feature_cols if c in feat_df.columns]
    train = feat_df[feat_df["period"] == "train"]
    val = feat_df[feat_df["period"] == "val"]

    X_tr = train[avail].fillna(0).values
    y_tr = train[target_col].values
    X_vl = val[avail].fillna(0).values
    y_vl = val[target_col].values

    m = lgb.LGBMClassifier(**_LGB_PARAMS)
    m.fit(X_tr, y_tr, eval_set=[(X_vl, y_vl)],
          callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)])
    val_prob = m.predict_proba(X_vl)[:, 1]
    val_auc = roc_auc_score(y_vl, val_prob)
    print(f"  {label} val_AUC={val_auc:.4f} ({len(avail)} features, {len(train):,} train)")
    return m, avail, val_auc


def score_model(model, feat_df: pd.DataFrame, feature_cols: list) -> np.ndarray:
    avail = [c for c in feature_cols if c in feat_df.columns]
    return model.predict_proba(feat_df[avail].fillna(0).values)[:, 1]


def tune_entry_threshold(entry_model, feature_cols: list, feat_df: pd.DataFrame,
                         target_col: str = "y_entry_adv_300s",
                         min_entry_step: int = 0) -> tuple[float, float]:
    """Tune entry threshold on val set by maximizing EV/episode."""
    val = feat_df[(feat_df["period"] == "val") & (feat_df["step_index"] >= min_entry_step)]
    avail = [c for c in feature_cols if c in val.columns]
    probs = entry_model.predict_proba(val[avail].fillna(0).values)[:, 1]
    val = val.copy()
    val["entry_prob"] = probs

    ep_groups = val.sort_values(["flip_time", "step_index"]).groupby("episode_id")
    n_val_ep = feat_df[(feat_df["period"] == "val")]["episode_id"].nunique()

    best_ev, best_thr = float("-inf"), 0.50
    for thr in np.arange(0.40, 0.70, 0.01):
        pnls = []
        for _, grp in ep_groups:
            cross = grp[grp["entry_prob"] >= thr]
            if len(cross) == 0:
                continue
            pnl = float(cross.iloc[0].get(target_col, 0))
            if not math.isnan(pnl):
                pnls.append(pnl)
        ev = sum(pnls) / n_val_ep if n_val_ep > 0 else 0.0
        if ev > best_ev:
            best_ev, best_thr = ev, round(float(thr), 3)

    print(f"  Val threshold={best_thr:.3f}, val EV/ep={best_ev:+.2f}")
    return best_thr, best_ev


def compute_variant_metrics(ep_df: pd.DataFrame, trades_df: pd.DataFrame,
                            variant: str, cost_ticks: int = 0) -> dict:
    n_ep = len(ep_df)
    n_traded = int(ep_df["entered"].sum())
    total_pnl = float(ep_df["pnl"].sum())
    ev_ep = total_pnl / n_ep if n_ep > 0 else 0.0
    has_trades = len(trades_df) > 0 and "pnl" in trades_df.columns
    ev_tr = float(trades_df["pnl"].mean()) if has_trades else float("nan")
    wr = float((trades_df["pnl"] > 0).mean()) if has_trades else float("nan")
    winners = trades_df[trades_df["pnl"] > 0]["pnl"] if has_trades else pd.Series([], dtype=float)
    losers = trades_df[trades_df["pnl"] <= 0]["pnl"] if has_trades else pd.Series([], dtype=float)
    pf = abs(winners.sum()) / max(abs(losers.sum()), 1.0) if len(losers) > 0 else float("inf")

    rng = np.random.default_rng(_SEED)
    ep_pnls = ep_df["pnl"].values
    boot_means = [rng.choice(ep_pnls, size=n_ep, replace=True).mean() for _ in range(2000)]
    ci_lo, ci_hi = float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))

    m = {
        "variant": variant,
        "cost_ticks": cost_ticks,
        "n_episodes": n_ep,
        "n_traded": n_traded,
        "trade_rate": round(n_traded / max(n_ep, 1), 4),
        "total_pnl": round(total_pnl, 2),
        "ev_per_episode": round(ev_ep, 4),
        "ev_per_trade": round(ev_tr, 4),
        "win_rate": round(wr, 4),
        "profit_factor": round(pf, 4),
        "ci_lo_95": round(ci_lo, 4),
        "ci_hi_95": round(ci_hi, 4),
        "avg_winner": round(float(winners.mean()), 2) if len(winners) > 0 else float("nan"),
        "avg_loser": round(float(losers.mean()), 2) if len(losers) > 0 else float("nan"),
    }
    # Monthly breakdown
    if len(trades_df) > 0 and "entry_ts" in trades_df.columns:
        trades_df = trades_df.copy()
        trades_df["month"] = pd.to_datetime(trades_df["entry_ts"], unit="ns").dt.to_period("M").astype(str)
        monthly = trades_df.groupby("month")["pnl"].agg(["mean", "sum", "count"])
        for idx, row in monthly.iterrows():
            m[f"month_{idx}_ev"] = round(float(row["mean"]), 2)
    return m


# ── Main study runner ──────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("DELAYED HEALTH STUDY — Phase 5-6-9: Variants + Controls")
    print("=" * 70)

    # Load data
    print("\nLoading data ...")
    entry_tgt = pd.read_parquet(OUT_DIR / "entry_targets.parquet")
    exit_tgt = pd.read_parquet(OUT_DIR / "exit_targets.parquet")
    knn_df = pd.read_parquet(OUT_DIR / "causal_knn_health.parquet")
    snap = pd.read_parquet(SNAP_FILE)

    print(f"  entry_targets: {entry_tgt.shape}")
    print(f"  exit_targets: {exit_tgt.shape}")

    # Merge KNN into entry targets
    knn_merge = knn_df[["observation_time"] + _KNN_FEATS].drop_duplicates("observation_time")
    entry_tgt = entry_tgt.merge(knn_merge, on="observation_time", how="left")

    # Build full feature dataset (merge snap + KNN)
    full_df = snap.merge(knn_merge, on="observation_time", how="left")

    # Determine test episodes and test subset
    test_feat = full_df[full_df["period"] == "test"].copy()
    n_test_ep = test_feat["episode_id"].nunique()
    print(f"  Test episodes: {n_test_ep:,}")

    # ── Load 1s bars ──
    obs_min_ns = int(test_feat["observation_time"].min())
    obs_max_ns = int(test_feat["observation_time"].max())
    print("\nLoading 1s bars ...")
    ts_arr, op_arr, hi_arr, lo_arr = load_1s_bars(obs_min_ns, obs_max_ns)
    print(f"  {len(ts_arr):,} bars loaded")

    all_variant_metrics = []
    all_trades = []
    all_ep_results = []
    model_manifest = {}
    val_grid_rows = []
    thresholds = {}

    # ── Variant A: Reproduce unrestricted dynamic policy ──
    print("\n" + "─" * 60)
    print("VARIANT A: Unrestricted dynamic policy (reproduce -$0.66)")
    print("─" * 60)

    # Use prior thresholds from expanded study if available
    prev_thr_file = PREV_REPLAY / "policy_thresholds.json"
    if prev_thr_file.exists():
        with open(prev_thr_file) as f:
            prev_thr = json.load(f)
        print(f"  Loaded prior thresholds: {prev_thr}")
    else:
        prev_thr = {"entry_threshold": 0.48, "exit_threshold": 0.50}

    # Train entry model (baseline 28 features, unrestricted)
    print("\n  Training entry model (28 baseline, unrestricted) ...")
    entry_model_A, entry_feats_A, val_auc_A = train_model(
        full_df.merge(entry_tgt[["observation_time", "y_entry_positive_300s"]].drop_duplicates(), on="observation_time", how="inner"),
        "y_entry_positive_300s", _BASELINE_FEATS, "Entry-A"
    )
    model_manifest["entry_A"] = {"features": entry_feats_A, "val_auc": val_auc_A}

    # Train exit model
    print("  Training exit model (baseline, unrestricted) ...")
    # exit_tgt already contains baseline features (built from bar4_snap which is snap)
    exit_model_A, exit_feats_A, exit_val_auc_A = train_model(
        exit_tgt,
        "y_exit_positive_60s",
        _BASELINE_FEATS + _EXIT_EXTRA,
        "Exit-A"
    )
    model_manifest["exit_A"] = {"features": exit_feats_A, "val_auc": exit_val_auc_A}

    # Tune entry threshold
    entry_tgt_full = full_df.merge(entry_tgt[["observation_time", "y_entry_adv_300s"]].drop_duplicates(), on="observation_time", how="inner")
    entry_thr_A, val_ev_A = tune_entry_threshold(entry_model_A, entry_feats_A, entry_tgt_full, min_entry_step=0)
    thresholds["A"] = {"entry_thr": entry_thr_A, "exit_thr": 0.50, "val_ev": val_ev_A}
    val_grid_rows.append({"variant": "A", "entry_thr": entry_thr_A, "val_ev": val_ev_A, "val_auc": val_auc_A})

    # Score test observations
    entry_probs_A = score_model(entry_model_A, test_feat, entry_feats_A)
    # Build exit-scoring features on test_feat directly (avoid merge)
    test_feat_with_exit = test_feat.copy()
    test_feat_with_exit["unrealized_pnl_atr"] = test_feat_with_exit["current_progress_atr"]
    test_feat_with_exit["time_in_trade_s"] = test_feat_with_exit["seconds_since_flip"] - BAR4_DELAY_S
    exit_probs_A = score_model(exit_model_A, test_feat_with_exit, exit_feats_A)

    trades_A, ep_A = run_replay_variant(
        test_feat, entry_probs_A, exit_probs_A,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=entry_thr_A, exit_thr=0.50,
        min_entry_step=0, variant_name="A_unrestricted",
        use_dynamic_exit=True,
    )
    metrics_A = compute_variant_metrics(ep_A, trades_A, "A_unrestricted")
    all_variant_metrics.append(metrics_A)
    all_trades.append(trades_A)
    all_ep_results.append(ep_A)

    # ── Variant B: Unconditional bar-4 entry ──
    print("\n" + "─" * 60)
    print("VARIANT B: Unconditional bar-4 entry")
    print("─" * 60)

    # B1: Fixed 300s exit
    print("\n  B1: Fixed 300s exit")
    dummy_probs = np.ones(len(test_feat))
    null_probs = np.full(len(test_feat), 0.0)

    trades_B1, ep_B1 = run_replay_variant(
        test_feat, dummy_probs, null_probs,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=0.0, exit_thr=0.0,
        min_entry_step=BAR4_STEP_INDEX, variant_name="B1_uncond_fixed",
        use_dynamic_exit=False, hold_s=300,
    )
    metrics_B1 = compute_variant_metrics(ep_B1, trades_B1, "B1_uncond_fixed")
    all_variant_metrics.append(metrics_B1)
    all_trades.append(trades_B1)
    all_ep_results.append(ep_B1)

    # B2: Dynamic exit model
    print("\n  B2: Dynamic exit model (A's exit model)")
    exit_probs_B = exit_probs_A

    trades_B2, ep_B2 = run_replay_variant(
        test_feat, dummy_probs, exit_probs_B,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=0.0, exit_thr=0.50,
        min_entry_step=BAR4_STEP_INDEX, variant_name="B2_uncond_dynamic",
        use_dynamic_exit=True,
    )
    metrics_B2 = compute_variant_metrics(ep_B2, trades_B2, "B2_uncond_dynamic")
    all_variant_metrics.append(metrics_B2)
    all_trades.append(trades_B2)
    all_ep_results.append(ep_B2)

    # ── Variant C: ML-selected entry after bar-4 ──
    print("\n" + "─" * 60)
    print("VARIANT C: ML entry at/after bar-4 (existing model)")
    print("─" * 60)

    # Tune threshold on bar-4+ only
    print("  Tuning entry threshold (bar-4+ observations) ...")
    entry_thr_C, val_ev_C = tune_entry_threshold(
        entry_model_A, entry_feats_A, entry_tgt_full, min_entry_step=BAR4_STEP_INDEX
    )
    thresholds["C"] = {"entry_thr": entry_thr_C, "exit_thr": 0.50, "val_ev": val_ev_C}
    val_grid_rows.append({"variant": "C", "entry_thr": entry_thr_C, "val_ev": val_ev_C, "val_auc": val_auc_A})

    # C1: Fixed exit
    trades_C1, ep_C1 = run_replay_variant(
        test_feat, entry_probs_A, null_probs,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=entry_thr_C, exit_thr=0.0,
        min_entry_step=BAR4_STEP_INDEX, variant_name="C1_ml_fixed",
        use_dynamic_exit=False, hold_s=300,
    )
    metrics_C1 = compute_variant_metrics(ep_C1, trades_C1, "C1_ml_fixed")
    all_variant_metrics.append(metrics_C1)
    all_trades.append(trades_C1)
    all_ep_results.append(ep_C1)

    # C2: Dynamic exit
    trades_C2, ep_C2 = run_replay_variant(
        test_feat, entry_probs_A, exit_probs_A,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=entry_thr_C, exit_thr=0.50,
        min_entry_step=BAR4_STEP_INDEX, variant_name="C2_ml_dynamic",
        use_dynamic_exit=True,
    )
    metrics_C2 = compute_variant_metrics(ep_C2, trades_C2, "C2_ml_dynamic")
    all_variant_metrics.append(metrics_C2)
    all_trades.append(trades_C2)
    all_ep_results.append(ep_C2)

    # ── Variant D: ML + KNN after bar-4 ──
    print("\n" + "─" * 60)
    print("VARIANT D: ML + causal KNN/kC after bar-4")
    print("─" * 60)

    # Train new entry model with KNN features
    # entry_tgt already has all snap columns (period, episode_id, etc.) + knn features + labels
    d_feats = _BASELINE_FEATS + _KNN_FEATS + _DELAY_FEATS
    # Only bar-4+ observations for training D model (entry_tgt is already bar-4+)
    entry_tgt_D_b4 = entry_tgt  # entry_tgt is already filtered to step_index >= BAR4_STEP_INDEX

    print(f"  Training entry model D ({len([c for c in d_feats if c in entry_tgt_D_b4.columns])} features, bar-4+ only) ...")
    entry_model_D, entry_feats_D, val_auc_D = train_model(
        entry_tgt_D_b4, "y_entry_positive_300s", d_feats, "Entry-D"
    )
    model_manifest["entry_D"] = {"features": entry_feats_D, "val_auc": val_auc_D}

    # Score full test (bar-4+ only — zeros elsewhere)
    test_b4 = test_feat[test_feat["step_index"] >= BAR4_STEP_INDEX].copy()
    entry_probs_D_b4 = score_model(entry_model_D, test_b4, entry_feats_D)
    # Build full-length prob array aligned to test_feat index
    entry_probs_D = np.zeros(len(test_feat))
    b4_mask = test_feat["step_index"].values >= BAR4_STEP_INDEX
    entry_probs_D[b4_mask] = entry_probs_D_b4

    # Tune D threshold — entry_tgt has y_entry_adv_300s
    entry_thr_D, val_ev_D = tune_entry_threshold(
        entry_model_D, entry_feats_D, entry_tgt_D_b4, min_entry_step=BAR4_STEP_INDEX
    )
    thresholds["D"] = {"entry_thr": entry_thr_D, "exit_thr": 0.50, "val_ev": val_ev_D, "val_auc": val_auc_D}
    val_grid_rows.append({"variant": "D", "entry_thr": entry_thr_D, "val_ev": val_ev_D, "val_auc": val_auc_D})

    trades_D, ep_D = run_replay_variant(
        test_feat, entry_probs_D, exit_probs_A,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=entry_thr_D, exit_thr=0.50,
        min_entry_step=BAR4_STEP_INDEX, variant_name="D_ml_knn_dynamic",
        use_dynamic_exit=True,
    )
    metrics_D = compute_variant_metrics(ep_D, trades_D, "D_ml_knn_dynamic")
    all_variant_metrics.append(metrics_D)
    all_trades.append(trades_D)
    all_ep_results.append(ep_D)

    # ── Variant E: Entry-conditioned exit model ──
    print("\n" + "─" * 60)
    print("VARIANT E: ML/KNN entry + entry-conditioned exit model")
    print("─" * 60)

    # Build OOF policy-selected entries from TRAINING data
    # Generate D-model entry selections across training period
    print("  Generating OOF D-model entries on training data ...")
    train_feat_b4 = full_df[(full_df["period"] == "train") & (full_df["step_index"] >= BAR4_STEP_INDEX)].copy()
    train_probs_D = score_model(entry_model_D, train_feat_b4, entry_feats_D)
    train_feat_b4["entry_prob_D"] = train_probs_D

    # Find first threshold crossing per episode
    selected_train_eps = {}
    for ep_id, grp in train_feat_b4.sort_values(["flip_time", "step_index"]).groupby("episode_id"):
        cross = grp[grp["entry_prob_D"] >= entry_thr_D]
        if len(cross) > 0:
            sel = cross.iloc[0]
            selected_train_eps[ep_id] = {
                "obs_time": sel["observation_time"],
                "step": sel["step_index"],
            }
    print(f"  Selected {len(selected_train_eps):,} OOF entries from training data")

    # Build exit target dataset anchored to OOF entries
    # For each selected entry, take all subsequent observations as positioned states
    if len(selected_train_eps) > 0:
        sel_ep_ids = list(selected_train_eps.keys())
        sel_obs_times = {ep: selected_train_eps[ep]["obs_time"] for ep in sel_ep_ids}

        exit_tgt_E = exit_tgt[exit_tgt["period"] == "train"].copy()
        exit_tgt_E = exit_tgt_E[exit_tgt_E["episode_id"].isin(sel_ep_ids)].copy()
        # Filter to steps after entry
        exit_tgt_E["entry_obs_time"] = exit_tgt_E["episode_id"].map(sel_obs_times)
        exit_tgt_E = exit_tgt_E[exit_tgt_E["observation_time"] >= exit_tgt_E["entry_obs_time"]]
        exit_tgt_E["time_in_trade_s"] = (exit_tgt_E["observation_time"] - exit_tgt_E["entry_obs_time"]) / 1e9
        exit_tgt_E["unrealized_pnl_atr"] = exit_tgt_E["current_progress_atr"] if "current_progress_atr" in exit_tgt_E.columns else 0.0

        # Train entry-conditioned exit model
        # exit_tgt_E already has baseline features (from snap), just add unrealized_pnl_atr
        e_feats = _BASELINE_FEATS + _KNN_FEATS + _EXIT_EXTRA + ["time_in_trade_s"]
        print(f"  Training exit model E on {len(exit_tgt_E):,} positioned obs ...")
        if len(exit_tgt_E) > 1000 and "y_exit_positive_60s" in exit_tgt_E.columns:
            # Use val period OOF entries as well for val_auc
            val_feat_b4 = full_df[(full_df["period"] == "val") & (full_df["step_index"] >= BAR4_STEP_INDEX)].copy()
            val_probs_D = score_model(entry_model_D, val_feat_b4, entry_feats_D)
            val_feat_b4["entry_prob_D"] = val_probs_D
            selected_val_eps = {}
            for ep_id, grp in val_feat_b4.sort_values(["flip_time", "step_index"]).groupby("episode_id"):
                cross = grp[grp["entry_prob_D"] >= entry_thr_D]
                if len(cross) > 0:
                    selected_val_eps[ep_id] = cross.iloc[0]["observation_time"]

            exit_tgt_E_val = exit_tgt[exit_tgt["period"] == "val"].copy()
            exit_tgt_E_val = exit_tgt_E_val[exit_tgt_E_val["episode_id"].isin(selected_val_eps.keys())].copy()
            if len(exit_tgt_E_val) > 100:
                exit_tgt_E_val["entry_obs_time"] = exit_tgt_E_val["episode_id"].map(selected_val_eps)
                exit_tgt_E_val = exit_tgt_E_val[exit_tgt_E_val["observation_time"] >= exit_tgt_E_val["entry_obs_time"]]
                exit_tgt_E_val["time_in_trade_s"] = (exit_tgt_E_val["observation_time"] - exit_tgt_E_val["entry_obs_time"]) / 1e9
                exit_tgt_E_val["unrealized_pnl_atr"] = exit_tgt_E_val.get("current_progress_atr", 0.0)
                exit_combined = pd.concat([exit_tgt_E, exit_tgt_E_val], ignore_index=True)
            else:
                exit_combined = exit_tgt_E
        else:
            exit_combined = exit_tgt_E

        if "y_exit_positive_60s" in exit_combined.columns and exit_combined["period"].nunique() >= 2:
            exit_model_E, exit_feats_E, exit_val_auc_E = train_model(
                exit_combined, "y_exit_positive_60s",
                e_feats, "Exit-E"
            )
            model_manifest["exit_E"] = {"features": exit_feats_E, "val_auc": exit_val_auc_E}
        else:
            print("  Insufficient data for exit model E, using exit model A")
            exit_model_E, exit_feats_E, exit_val_auc_E = exit_model_A, exit_feats_A, exit_val_auc_A

        # Score exit model E on test — compute extra features from test_feat directly
        test_with_exit_E = test_feat.copy()
        test_with_exit_E["unrealized_pnl_atr"] = test_with_exit_E["current_progress_atr"]
        test_with_exit_E["time_in_trade_s"] = test_with_exit_E["seconds_since_flip"] - BAR4_DELAY_S
        exit_probs_E = score_model(exit_model_E, test_with_exit_E, exit_feats_E)
    else:
        exit_probs_E = exit_probs_A
        print("  No OOF entries found, using exit model A for E")

    # Tune E exit threshold on val
    val_feat_b4_scored = full_df[full_df["period"] == "val"].copy()
    val_ep_probs_D = np.zeros(len(val_feat_b4_scored))
    val_b4_mask = val_feat_b4_scored["step_index"].values >= BAR4_STEP_INDEX
    if val_b4_mask.sum() > 0:
        val_ep_probs_D[val_b4_mask] = score_model(entry_model_D, val_feat_b4_scored[val_b4_mask], entry_feats_D)
    val_feat_b4_scored["entry_prob"] = val_ep_probs_D

    val_with_exit = val_feat_b4_scored.copy()
    val_with_exit["unrealized_pnl_atr"] = val_with_exit["current_progress_atr"]
    val_with_exit["time_in_trade_s"] = val_with_exit["seconds_since_flip"] - BAR4_DELAY_S
    val_exit_probs = score_model(exit_model_E, val_with_exit, exit_feats_E)
    val_feat_b4_scored["exit_prob"] = val_exit_probs

    # Load val 1s bars
    val_obs_min = int(val_feat_b4_scored["observation_time"].min())
    val_obs_max = int(val_feat_b4_scored["observation_time"].max())
    val_ts, val_op, val_hi, val_lo = load_1s_bars(val_obs_min, val_obs_max)

    best_exit_thr_E = 0.50
    best_val_ev_E = float("-inf")
    for exit_thr_cand in [0.40, 0.45, 0.50, 0.55, 0.60]:
        _, ep_val_tmp = run_replay_variant(
            val_feat_b4_scored, val_ep_probs_D, val_exit_probs,
            val_ts, val_op, val_hi, val_lo,
            entry_thr=entry_thr_D, exit_thr=exit_thr_cand,
            min_entry_step=BAR4_STEP_INDEX, variant_name=f"E_val_{exit_thr_cand}",
            use_dynamic_exit=True,
        )
        val_ev = ep_val_tmp["pnl"].sum() / max(len(ep_val_tmp), 1)
        print(f"  exit_thr={exit_thr_cand:.2f}: val EV/ep={val_ev:+.2f}")
        if val_ev > best_val_ev_E:
            best_val_ev_E = val_ev
            best_exit_thr_E = exit_thr_cand

    print(f"  Best exit threshold E: {best_exit_thr_E} (val EV={best_val_ev_E:+.2f})")
    thresholds["E"] = {"entry_thr": entry_thr_D, "exit_thr": best_exit_thr_E,
                       "val_ev": best_val_ev_E, "val_auc": val_auc_D}
    val_grid_rows.append({"variant": "E", "entry_thr": entry_thr_D, "val_ev": best_val_ev_E, "val_auc": val_auc_D})

    # Run test replay for E
    trades_E, ep_E = run_replay_variant(
        test_feat, entry_probs_D, exit_probs_E,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=entry_thr_D, exit_thr=best_exit_thr_E,
        min_entry_step=BAR4_STEP_INDEX, variant_name="E_ml_knn_cond_exit",
        use_dynamic_exit=True,
    )
    metrics_E = compute_variant_metrics(ep_E, trades_E, "E_ml_knn_cond_exit")
    all_variant_metrics.append(metrics_E)
    all_trades.append(trades_E)
    all_ep_results.append(ep_E)

    # ── Cost stress: re-run E under +1T and +2T ──
    print("\n" + "─" * 30)
    print("Cost stress: E under +1 tick and +2 ticks RT slippage")
    for cost_t in [1, 2]:
        trades_Ec, ep_Ec = run_replay_variant(
            test_feat, entry_probs_D, exit_probs_E,
            ts_arr, op_arr, hi_arr, lo_arr,
            entry_thr=entry_thr_D, exit_thr=best_exit_thr_E,
            min_entry_step=BAR4_STEP_INDEX, variant_name=f"E_plus{cost_t}tick",
            use_dynamic_exit=True, cost_extra_ticks=cost_t,
        )
        m = compute_variant_metrics(ep_Ec, trades_Ec, f"E_plus{cost_t}tick", cost_ticks=cost_t)
        all_variant_metrics.append(m)
        all_trades.append(trades_Ec)
        all_ep_results.append(ep_Ec)

    # ── Placebo delay tests ──
    print("\n" + "─" * 60)
    print("PLACEBO DELAY TESTS (unconditional entry at each delay)")
    print("─" * 60)
    placebo_rows = []
    for delay_s in PLACEBO_DELAYS:
        step_idx = delay_s // 5
        trades_p, ep_p = run_replay_variant(
            test_feat, dummy_probs, null_probs,
            ts_arr, op_arr, hi_arr, lo_arr,
            entry_thr=0.0, exit_thr=0.0,
            min_entry_step=step_idx, variant_name=f"placebo_{delay_s}s",
            use_dynamic_exit=False, hold_s=300,
        )
        m = compute_variant_metrics(ep_p, trades_p, f"placebo_{delay_s}s")
        m["delay_s"] = delay_s
        placebo_rows.append(m)
    pd.DataFrame(placebo_rows).to_parquet(OUT_DIR / "delay_placebo_results.parquet", index=False)
    print("  Saved delay_placebo_results.parquet")

    # ── Controls ──
    print("\n" + "─" * 60)
    print("CONTROLS")
    print("─" * 60)
    rng = np.random.default_rng(_SEED + 1)
    ctrl_rows = []

    # Control 1: KNN shuffle across episodes
    print("\n  Control 1: KNN feature shuffle across episodes ...")
    ep_ids_arr = test_feat["episode_id"].values
    unique_eps = np.unique(ep_ids_arr)
    ep_shuffle = rng.permutation(unique_eps)
    ep_map = dict(zip(unique_eps, ep_shuffle))
    test_feat_c1 = test_feat.copy()
    for col in _KNN_FEATS:
        if col in test_feat_c1.columns:
            shuffled_ep = test_feat_c1["episode_id"].map(ep_map)
            knn_lookup = test_feat_c1.set_index("episode_id")[col].to_dict()
            test_feat_c1[col] = test_feat_c1["episode_id"].map(lambda ep: knn_lookup.get(ep_map.get(ep, ep), np.nan))
    entry_probs_c1 = np.zeros(len(test_feat_c1))
    b4_mask_c1 = test_feat_c1["step_index"].values >= BAR4_STEP_INDEX
    entry_probs_c1[b4_mask_c1] = score_model(entry_model_D, test_feat_c1[b4_mask_c1], entry_feats_D)
    _, ep_c1 = run_replay_variant(
        test_feat_c1, entry_probs_c1, exit_probs_E,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=entry_thr_D, exit_thr=best_exit_thr_E,
        min_entry_step=BAR4_STEP_INDEX, variant_name="ctrl1_knn_shuffle",
    )
    m_c1 = compute_variant_metrics(ep_c1, pd.DataFrame(), "ctrl1_knn_shuffle")
    m_c1["delta_ev"] = m_c1["ev_per_episode"] - metrics_E["ev_per_episode"]
    ctrl_rows.append(m_c1)

    # Control 2: 5s lag on entry scores
    print("\n  Control 2: 5s lag on entry scores ...")
    entry_probs_lag = np.zeros(len(test_feat))
    # Shift entry probs by one step per episode
    for ep_id, grp in test_feat.sort_values(["flip_time", "step_index"]).groupby("episode_id"):
        idx = grp.index.values
        probs_ep = entry_probs_D[np.arange(len(test_feat))[test_feat.index.isin(idx)]]
        if len(probs_ep) > 1:
            lagged = np.roll(probs_ep, 1)
            lagged[0] = 0.0
            ep_idx = test_feat.index.isin(idx)
            entry_probs_lag[ep_idx] = lagged

    _, ep_lag = run_replay_variant(
        test_feat, entry_probs_lag, exit_probs_E,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=entry_thr_D, exit_thr=best_exit_thr_E,
        min_entry_step=BAR4_STEP_INDEX, variant_name="ctrl2_lag",
    )
    m_lag = compute_variant_metrics(ep_lag, pd.DataFrame(), "ctrl2_5s_lag")
    m_lag["delta_ev"] = m_lag["ev_per_episode"] - metrics_E["ev_per_episode"]
    ctrl_rows.append(m_lag)

    # Control 3: Entry score shuffle across episodes (same trade rate)
    print("\n  Control 3: Entry score shuffle across episodes ...")
    ep_probs_by_ep = {}
    for ep_id, grp in test_feat.sort_values(["flip_time", "step_index"]).groupby("episode_id"):
        idx_mask = test_feat["episode_id"] == ep_id
        ep_probs_by_ep[ep_id] = entry_probs_D[idx_mask.values]

    shuffled_ep_ids = rng.permutation(list(ep_probs_by_ep.keys()))
    ep_probs_shuffled = dict(zip(list(ep_probs_by_ep.keys()), [ep_probs_by_ep[k] for k in shuffled_ep_ids]))

    entry_probs_c3 = np.zeros(len(test_feat))
    for ep_id, grp in test_feat.sort_values(["flip_time", "step_index"]).groupby("episode_id"):
        idx_mask = (test_feat["episode_id"] == ep_id).values
        n_target = int(idx_mask.sum())
        probs_src = ep_probs_shuffled.get(ep_id, np.zeros(n_target))
        if len(probs_src) >= n_target:
            entry_probs_c3[idx_mask] = probs_src[:n_target]
        else:
            padded = np.zeros(n_target)
            padded[:len(probs_src)] = probs_src
            entry_probs_c3[idx_mask] = padded

    _, ep_c3 = run_replay_variant(
        test_feat, entry_probs_c3, exit_probs_E,
        ts_arr, op_arr, hi_arr, lo_arr,
        entry_thr=entry_thr_D, exit_thr=best_exit_thr_E,
        min_entry_step=BAR4_STEP_INDEX, variant_name="ctrl3_entry_shuffle",
    )
    m_c3 = compute_variant_metrics(ep_c3, pd.DataFrame(), "ctrl3_entry_shuffle")
    m_c3["delta_ev"] = m_c3["ev_per_episode"] - metrics_E["ev_per_episode"]
    ctrl_rows.append(m_c3)

    pd.DataFrame(ctrl_rows).to_parquet(OUT_DIR / "control_results.parquet", index=False)
    print("  Saved control_results.parquet")

    # ── Save all results ──
    print("\n" + "─" * 60)
    print("Saving all results ...")

    variant_metrics_df = pd.DataFrame(all_variant_metrics)
    variant_metrics_df.to_parquet(OUT_DIR / "variant_metrics.parquet", index=False)

    if all_trades:
        all_trades_df = pd.concat([t for t in all_trades if len(t) > 0], ignore_index=True)
        all_trades_df.to_parquet(OUT_DIR / "variant_trades.parquet", index=False)

    if all_ep_results:
        all_ep_df = pd.concat(all_ep_results, ignore_index=True)
        all_ep_df.to_parquet(OUT_DIR / "variant_episode_results.parquet", index=False)

    # Bootstrap CI for each variant
    boot_rows = []
    for ep_df_v in all_ep_results:
        variant = ep_df_v["variant"].iloc[0] if "variant" in ep_df_v.columns else "unknown"
        ep_pnls = ep_df_v["pnl"].values
        boot_means = [rng.choice(ep_pnls, size=len(ep_pnls), replace=True).mean() for _ in range(1000)]
        boot_rows.append({
            "variant": variant,
            "ev_per_episode": float(ep_pnls.mean()),
            "ci_lo_95": float(np.percentile(boot_means, 2.5)),
            "ci_hi_95": float(np.percentile(boot_means, 97.5)),
        })
    pd.DataFrame(boot_rows).to_parquet(OUT_DIR / "bootstrap_ci.parquet", index=False)

    # Validation grid
    pd.DataFrame(val_grid_rows).to_parquet(OUT_DIR / "validation_grid.parquet", index=False)

    # Policy thresholds
    with open(OUT_DIR / "policy_thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=2)

    # Model manifest
    with open(OUT_DIR / "model_manifest.json", "w") as f:
        json.dump(model_manifest, f, indent=2)

    # Execution audit
    ep_A_test = ep_A[ep_A["episode_id"].isin(test_feat["episode_id"].unique())]
    audit = {
        "stop_convention": "gap-through fills at bar open; intrabar touch fills at next bar open",
        "entry_convention": "market fill at next 1s bar open after decision timestamp",
        "cost_base": f"${_COMM} RT commission",
        "atr_stop": f"{_ATR_STOP} ATR from flip_close",
        "max_hold_s": 300,
        "episode_cap_s": 1800,
    }
    pd.DataFrame([audit]).to_parquet(OUT_DIR / "execution_audit.parquet", index=False)
    pd.DataFrame([{}]).to_parquet(OUT_DIR / "provenance_audit.json.parquet", index=False)
    with open(OUT_DIR / "provenance_audit.json", "w") as f:
        json.dump(audit, f, indent=2)

    # Attribution table
    print("\n" + "=" * 80)
    print("ATTRIBUTION TABLE")
    print("=" * 80)
    print(f"{'Variant':<30} {'Delay':>7} {'ML':>5} {'KNN':>5} {'CondExit':>9} {'EV/ep':>9} {'95% CI'}")
    print("-" * 80)
    attr_rows = [
        ("A_unrestricted",       "No",  "Yes", "No",  "No",  metrics_A),
        ("B1_uncond_fixed",      "Bar4","No",  "No",  "No",  metrics_B1),
        ("B2_uncond_dynamic",    "Bar4","No",  "No",  "No",  metrics_B2),
        ("C1_ml_fixed",          "Bar4","Yes", "No",  "No",  metrics_C1),
        ("C2_ml_dynamic",        "Bar4","Yes", "No",  "No",  metrics_C2),
        ("D_ml_knn_dynamic",     "Bar4","Yes", "Yes", "No",  metrics_D),
        ("E_ml_knn_cond_exit",   "Bar4","Yes", "Yes", "Yes", metrics_E),
    ]
    for name, delay, ml, knn, cond_exit, m in attr_rows:
        ev = m["ev_per_episode"]
        ci_lo = m["ci_lo_95"]
        ci_hi = m["ci_hi_95"]
        print(f"{name:<30} {delay:>7} {ml:>5} {knn:>5} {cond_exit:>9} {ev:>+9.2f}  ({ci_lo:+.2f},{ci_hi:+.2f})")

    print("\nDeltas:")
    ev_A = metrics_A["ev_per_episode"]
    ev_B1 = metrics_B1["ev_per_episode"]
    ev_B2 = metrics_B2["ev_per_episode"]
    ev_C2 = metrics_C2["ev_per_episode"]
    ev_D = metrics_D["ev_per_episode"]
    ev_E = metrics_E["ev_per_episode"]
    print(f"  delay effect (B1 vs A):           {ev_B1 - ev_A:+.2f}/ep")
    print(f"  ML-after-delay (C2 vs B2):         {ev_C2 - ev_B2:+.2f}/ep")
    print(f"  KNN/kC (D vs C2):                  {ev_D - ev_C2:+.2f}/ep")
    print(f"  entry-cond exit (E vs D):           {ev_E - ev_D:+.2f}/ep")
    print(f"  full improvement (E vs A):          {ev_E - ev_A:+.2f}/ep")
    print("=" * 80)

    return {
        "A": metrics_A, "B1": metrics_B1, "B2": metrics_B2,
        "C1": metrics_C1, "C2": metrics_C2, "D": metrics_D, "E": metrics_E
    }


if __name__ == "__main__":
    metrics = main()
    print("\nPhase 5-6-9 complete.")
