"""Phase C Comprehensive Full TRAIN Feasibility Evaluation.
==========================================================
Replays all 3 target arms across 2021-2023 (1,387,411 candidates) using the exact
causal completed 1m ATR and forward 1s bars.
"""

from __future__ import annotations

import gc
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd

from utils.runner.data import CausalDataLoader
from utils.session_boundaries import session_close_ns

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = REPO_ROOT / "studies" / "regime_transition_target_before_stop_v1"
WORK_DIR = STUDY_DIR / "_work" / "train_merged_collection"
CATALOG_PATH = REPO_ROOT / "data" / "catalog" / "NQ_v0_2020_2026"

NS = 1_000_000_000

CANONICAL_FEATURES = [
    "arrival_acceleration",
    "arrival_velocity",
    "ema_slope",
    "prior_1m_regime_efficiency",
    "prior_1m_regime_mfe_atr",
    "prior_1m_regime_range_atr",
    "prior_5m_regime_efficiency",
    "prior_5m_regime_mfe_atr",
    "prior_5m_regime_range_atr",
    "rolling_300s_current_progress_atr",
    "rolling_300s_giveback_atr",
    "rolling_300s_max_progress_atr",
    "rolling_300s_retention_ratio",
]

TARGET_ARMS = [
    {"arm_id": "TP_1.0_SL_0.5", "fav": 1.0, "adv": 0.5},
    {"arm_id": "TP_1.0_SL_1.0", "fav": 1.0, "adv": 1.0},
    {"arm_id": "TP_1.0_SL_1.5", "fav": 1.0, "adv": 1.5},
]


class RegimeEngine:
    ATR_P = 14
    def __init__(self):
        self.prev_c = None
        self.atr_warmup = []
        self.atr = None

    def update(self, h: float, l: float, c: float) -> float:
        tr = h - l if self.prev_c is None else max(h - l, abs(h - self.prev_c), abs(l - self.prev_c))
        self.prev_c = c
        if self.atr is None:
            self.atr_warmup.append(tr)
            if len(self.atr_warmup) == self.ATR_P:
                self.atr = sum(self.atr_warmup) / self.ATR_P
                self.atr_warmup = []
        else:
            self.atr = (self.atr * (self.ATR_P - 1) + tr) / self.ATR_P
        return self.atr or 0.0


def evaluate_chunk(
    cand_indices: np.ndarray,
    obs_ts: np.ndarray,
    directions: np.ndarray,
    atrs: np.ndarray,
    events_ts: np.ndarray,
    events_open: np.ndarray,
    events_high: np.ndarray,
    events_low: np.ndarray,
    events_gap: np.ndarray,
    horizon_ns: int = 300 * NS,
):
    """Vectorized / accelerated barrier evaluation for a chunk of candidates."""
    n_cands = len(cand_indices)
    
    # Preallocate output arrays for 3 arms
    # 0 = TP1.0/SL0.5, 1 = TP1.0/SL1.0, 2 = TP1.0/SL1.5
    # Dispositions: 1 = POSITIVE, 0 = NEGATIVE, -1 = TIMEOUT, -2 = SESSION_END, -3 = GAP, -4 = AMBIGUOUS, -5 = DATA_END
    disp_arr = np.zeros((3, n_cands), dtype=np.int8)
    time_arr = np.zeros((3, n_cands), dtype=np.float32)

    for idx in range(n_cands):
        T = obs_ts[idx]
        direction = directions[idx]
        atr = atrs[idx]
        session_close = session_close_ns(T, "RTH")

        # Find first 1s bar strictly after T
        start_idx = np.searchsorted(events_ts, T, side="right")
        end_idx = np.searchsorted(events_ts, T + 350 * NS, side="right")

        if start_idx >= len(events_ts) or start_idx >= end_idx:
            # No forward bars
            disp_arr[:, idx] = -5
            time_arr[:, idx] = 300.0
            continue

        entry_price = events_open[start_idx]

        # Calculate TP and SL prices for each arm
        # Arm 0: fav 1.0, adv 0.5
        # Arm 1: fav 1.0, adv 1.0
        # Arm 2: fav 1.0, adv 1.5
        if direction == 1:
            tp_0 = entry_price + 1.0 * atr
            sl_0 = entry_price - 0.5 * atr
            tp_1 = entry_price + 1.0 * atr
            sl_1 = entry_price - 1.0 * atr
            tp_2 = entry_price + 1.0 * atr
            sl_2 = entry_price - 1.5 * atr
        else:
            tp_0 = entry_price - 1.0 * atr
            sl_0 = entry_price + 0.5 * atr
            tp_1 = entry_price - 1.0 * atr
            sl_1 = entry_price + 1.0 * atr
            tp_2 = entry_price - 1.0 * atr
            sl_2 = entry_price + 1.5 * atr

        resolved_0 = False
        resolved_1 = False
        resolved_2 = False

        for b_i in range(start_idx, end_idx):
            bar_ts = events_ts[b_i]
            
            # Check session end
            if bar_ts > session_close:
                res_sec = (bar_ts - T) / NS
                if not resolved_0:
                    disp_arr[0, idx] = -2
                    time_arr[0, idx] = res_sec
                    resolved_0 = True
                if not resolved_1:
                    disp_arr[1, idx] = -2
                    time_arr[1, idx] = res_sec
                    resolved_1 = True
                if not resolved_2:
                    disp_arr[2, idx] = -2
                    time_arr[2, idx] = res_sec
                    resolved_2 = True
                break

            # Check gap
            if events_gap[b_i]:
                res_sec = (bar_ts - T) / NS
                if not resolved_0:
                    disp_arr[0, idx] = -3
                    time_arr[0, idx] = res_sec
                    resolved_0 = True
                if not resolved_1:
                    disp_arr[1, idx] = -3
                    time_arr[1, idx] = res_sec
                    resolved_1 = True
                if not resolved_2:
                    disp_arr[2, idx] = -3
                    time_arr[2, idx] = res_sec
                    resolved_2 = True
                break

            b_h = events_high[b_i]
            b_l = events_low[b_i]
            res_sec = (bar_ts - T) / NS

            # Check Arm 0 (SL 0.5)
            if not resolved_0:
                if direction == 1:
                    hit_tp = b_h >= tp_0
                    hit_sl = b_l <= sl_0
                else:
                    hit_tp = b_l <= tp_0
                    hit_sl = b_h >= sl_0

                if hit_tp and hit_sl:
                    disp_arr[0, idx] = -4  # Ambiguous
                    time_arr[0, idx] = res_sec
                    resolved_0 = True
                elif hit_tp:
                    disp_arr[0, idx] = 1   # Positive
                    time_arr[0, idx] = res_sec
                    resolved_0 = True
                elif hit_sl:
                    disp_arr[0, idx] = 0   # Negative
                    time_arr[0, idx] = res_sec
                    resolved_0 = True

            # Check Arm 1 (SL 1.0)
            if not resolved_1:
                if direction == 1:
                    hit_tp = b_h >= tp_1
                    hit_sl = b_l <= sl_1
                else:
                    hit_tp = b_l <= tp_1
                    hit_sl = b_h >= sl_1

                if hit_tp and hit_sl:
                    disp_arr[1, idx] = -4
                    time_arr[1, idx] = res_sec
                    resolved_1 = True
                elif hit_tp:
                    disp_arr[1, idx] = 1
                    time_arr[1, idx] = res_sec
                    resolved_1 = True
                elif hit_sl:
                    disp_arr[1, idx] = 0
                    time_arr[1, idx] = res_sec
                    resolved_1 = True

            # Check Arm 2 (SL 1.5)
            if not resolved_2:
                if direction == 1:
                    hit_tp = b_h >= tp_2
                    hit_sl = b_l <= sl_2
                else:
                    hit_tp = b_l <= tp_2
                    hit_sl = b_h >= sl_2

                if hit_tp and hit_sl:
                    disp_arr[2, idx] = -4
                    time_arr[2, idx] = res_sec
                    resolved_2 = True
                elif hit_tp:
                    disp_arr[2, idx] = 1
                    time_arr[2, idx] = res_sec
                    resolved_2 = True
                elif hit_sl:
                    disp_arr[2, idx] = 0
                    time_arr[2, idx] = res_sec
                    resolved_2 = True

            if resolved_0 and resolved_1 and resolved_2:
                break

            # Horizon expiry check
            if bar_ts >= T + horizon_ns:
                if not resolved_0:
                    disp_arr[0, idx] = 0  # Unresolved at horizon -> negative (timeout)
                    time_arr[0, idx] = 300.0
                    resolved_0 = True
                if not resolved_1:
                    disp_arr[1, idx] = 0
                    time_arr[1, idx] = 300.0
                    resolved_1 = True
                if not resolved_2:
                    disp_arr[2, idx] = 0
                    time_arr[2, idx] = 300.0
                    resolved_2 = True
                break

        # If still unresolved at end of events
        if not resolved_0:
            disp_arr[0, idx] = 0
            time_arr[0, idx] = 300.0
        if not resolved_1:
            disp_arr[1, idx] = 0
            time_arr[1, idx] = 300.0
        if not resolved_2:
            disp_arr[2, idx] = 0
            time_arr[2, idx] = 300.0

    return disp_arr, time_arr


def main():
    print("============================================================")
    print("STARTING FULL PHASE C REPLAY & FEASIBILITY ANALYSIS")
    print("============================================================")
    start_time = time.time()

    c_df = pd.read_parquet(WORK_DIR / "candidates.parquet")
    o_df = pd.read_parquet(WORK_DIR / "observations.parquet")
    n_cands = len(c_df)
    print(f"Loaded {n_cands:,} candidates in {time.time() - start_time:.2f}s")

    c_df["ts_dt"] = pd.to_datetime(c_df["observation_ts"], unit="ns", utc=True)
    c_df["year"] = c_df["ts_dt"].dt.year
    c_df["month_str"] = c_df["ts_dt"].dt.strftime("%Y-%m")
    c_df["date_str"] = c_df["ts_dt"].dt.strftime("%Y-%m-%d")

    # Prevailing regime direction: +1 = Bullish prevailing (SHORT candidate), -1 = Bearish prevailing (LONG candidate)
    regime_directions = o_df["regime_direction"].to_numpy(dtype=np.int8)
    trade_directions = (-regime_directions).astype(np.int8)
    obs_ts_all = c_df["observation_ts"].to_numpy(dtype=np.int64)

    # 1. Compute causal completed 1m Wilder ATR-14 for all timestamps
    print("\n---> Loading 1m bars to build causal ATR timeline...")
    loader = CausalDataLoader(CATALOG_PATH)
    m1_bars = loader.load_bars(
        "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        pd.Timestamp("2020-12-27 00:00:00", tz="UTC"),
        pd.Timestamp("2023-12-31 23:59:59", tz="UTC"),
    )
    print(f"Loaded {len(m1_bars):,} 1m bars.")

    engine = RegimeEngine()
    m1_ts_inits = np.zeros(len(m1_bars), dtype=np.int64)
    m1_atrs = np.zeros(len(m1_bars), dtype=np.float64)

    for i, b in enumerate(m1_bars):
        m1_ts_inits[i] = int(b.ts_init)
        m1_atrs[i] = engine.update(float(b.high), float(b.low), float(b.close))

    # For each candidate, find the latest causally completed 1m ATR (bar with ts_init <= T)
    atr_indices = np.searchsorted(m1_ts_inits, obs_ts_all, side="right") - 1
    atr_indices = np.clip(atr_indices, 0, len(m1_atrs) - 1)
    cand_atrs = m1_atrs[atr_indices]
    print(f"Mapped ATRs for {n_cands:,} candidates. Median ATR: {np.median(cand_atrs):.2f}, Mean: {np.mean(cand_atrs):.2f}")

    # 2. Replay all 3 arms month by month
    months = sorted(c_df["month_str"].unique())
    print(f"\n---> Replaying 3 target arms across {len(months)} months...")

    all_disp = np.zeros((3, n_cands), dtype=np.int8)
    all_time = np.zeros((3, n_cands), dtype=np.float32)

    for m_idx, m_str in enumerate(months):
        m_mask = (c_df["month_str"] == m_str).to_numpy()
        m_indices = np.where(m_mask)[0]
        if len(m_indices) == 0:
            continue

        m_start = pd.Timestamp(f"{m_str}-01 00:00:00", tz="UTC")
        # Load through end of month + 1 day
        m_end = (m_start + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1))
        
        m_bars_1s = loader.load_bars(
            "NQ.XCME-1-SECOND-LAST-EXTERNAL",
            m_start,
            m_end,
        )

        n_1s = len(m_bars_1s)
        events_ts = np.array([int(b.ts_init) for b in m_bars_1s], dtype=np.int64)
        events_open = np.array([float(b.open) for b in m_bars_1s], dtype=np.float64)
        events_high = np.array([float(b.high) for b in m_bars_1s], dtype=np.float64)
        events_low = np.array([float(b.low) for b in m_bars_1s], dtype=np.float64)
        events_gap = np.zeros(n_1s, dtype=bool)

        disp_chunk, time_chunk = evaluate_chunk(
            cand_indices=m_indices,
            obs_ts=obs_ts_all[m_indices],
            directions=regime_directions[m_indices],
            atrs=cand_atrs[m_indices],
            events_ts=events_ts,
            events_open=events_open,
            events_high=events_high,
            events_low=events_low,
            events_gap=events_gap,
        )

        all_disp[:, m_indices] = disp_chunk
        all_time[:, m_indices] = time_chunk
        print(f"     [{m_idx+1}/{len(months)}] {m_str}: processed {len(m_indices):,} candidates ({n_1s:,} 1s bars)")

    print(f"\nCompleted replaying all {n_cands:,} candidates in {time.time() - start_time:.2f}s")

    # 3. Target Parity Verification (Arm 1 TP1.0/SL1.0 vs observations.parquet)
    # in observations.parquet: 1 = POSITIVE, 0 = NEGATIVE, CENSORED
    obs_disps = o_df["disposition"].to_numpy()
    obs_labels = o_df["target_flip_within_horizon"].to_numpy()

    arm1_disp = all_disp[1]
    # Check mismatches
    arm1_is_pos = (arm1_disp == 1)
    obs_is_pos = (obs_disps == "LABELED_POSITIVE")
    pos_mismatches = int(np.sum(arm1_is_pos != obs_is_pos))

    arm1_is_neg = (arm1_disp == 0)
    obs_is_neg = (obs_disps == "LABELED_NEGATIVE")
    neg_mismatches = int(np.sum(arm1_is_neg != obs_is_neg))

    arm1_is_cens = (arm1_disp < 0)
    obs_is_cens = (obs_disps == "CENSORED")
    cens_mismatches = int(np.sum(arm1_is_cens != obs_is_cens))

    print(f"\n============================================================")
    print("TARGET REPLAY PARITY (Arm 1 TP1.0/SL1.0 vs Collector Observations)")
    print(f"============================================================")
    print(f"Positive Mismatches: {pos_mismatches}")
    print(f"Negative Mismatches: {neg_mismatches}")
    print(f"Censoring Mismatches: {cens_mismatches}")
    print(f"Parity: {'PASS' if (pos_mismatches == 0 and neg_mismatches == 0 and cens_mismatches == 0) else 'FAIL'}")

    # 4. Produce Complete Feasibility Metrics
    c_df["arm0_disp"] = all_disp[0]
    c_df["arm0_time"] = all_time[0]
    c_df["arm1_disp"] = all_disp[1]
    c_df["arm1_time"] = all_time[1]
    c_df["arm2_disp"] = all_disp[2]
    c_df["arm2_time"] = all_time[2]
    c_df["regime_direction"] = regime_directions
    c_df["trade_direction"] = trade_directions
    c_df["regime_key"] = o_df["regime_direction"].astype(str) + "_" + c_df["regime_start_ns"].astype(str)

    # Cross-arm structural check (widening stop: SL 0.5 -> SL 1.0 -> SL 1.5)
    # Impossible transitions: Positive at smaller stop -> Negative at larger stop (without censoring)
    imp_01 = np.sum((all_disp[0] == 1) & (all_disp[1] == 0))
    imp_12 = np.sum((all_disp[1] == 1) & (all_disp[2] == 0))
    imp_02 = np.sum((all_disp[0] == 1) & (all_disp[2] == 0))
    total_impossible = imp_01 + imp_12 + imp_02

    print(f"\n============================================================")
    print("CROSS-ARM WIDENING-STOP INVARIANTS")
    print(f"============================================================")
    print(f"Impossible Transitions (SL0.5 Pos -> SL1.0 Neg): {imp_01}")
    print(f"Impossible Transitions (SL1.0 Pos -> SL1.5 Neg): {imp_12}")
    print(f"Impossible Transitions (SL0.5 Pos -> SL1.5 Neg): {imp_02}")
    print(f"Total Impossible Transitions: {total_impossible}")

    # Transition Table
    trans_table = {}
    for i0, d0 in [(1, "POS"), (0, "NEG"), (-2, "SESS"), (-3, "GAP"), (-4, "AMB")]:
        for i1, d1 in [(1, "POS"), (0, "NEG"), (-2, "SESS"), (-3, "GAP"), (-4, "AMB")]:
            for i2, d2 in [(1, "POS"), (0, "NEG"), (-2, "SESS"), (-3, "GAP"), (-4, "AMB")]:
                cnt = int(np.sum((all_disp[0] == i0) & (all_disp[1] == i1) & (all_disp[2] == i2)))
                if cnt > 0:
                    trans_table[f"{d0} -> {d1} -> {d2}"] = cnt

    print("\nTransition Table (SL 0.5 -> SL 1.0 -> SL 1.5):")
    for k, v in sorted(trans_table.items(), key=lambda x: -x[1]):
        print(f"  {k:25s}: {v:8,} ({v/n_cands*100:5.2f}%)")

    # 5. Summaries by Arm, Year, Direction
    feasibility_data = {}
    arms_meta = [
        ("TP1_SL0_5", 0, "arm0_disp", "arm0_time"),
        ("TP1_SL1_0", 1, "arm1_disp", "arm1_time"),
        ("TP1_SL1_5", 2, "arm2_disp", "arm2_time"),
    ]

    for arm_name, arm_idx, disp_col, time_col in arms_meta:
        feasibility_data[arm_name] = {}
        
        # Pooled
        d_vals = c_df[disp_col]
        t_vals = c_df[time_col]
        n_pos = int((d_vals == 1).sum())
        n_neg = int((d_vals == 0).sum())
        n_res = n_pos + n_neg
        n_sess = int((d_vals == -2).sum())
        n_gap = int((d_vals == -3).sum())
        n_amb = int((d_vals == -4).sum())
        n_timeout = int(((d_vals == 0) & (t_vals >= 300.0)).sum())

        res_times = t_vals[d_vals.isin([0, 1])]

        feasibility_data[arm_name]["pooled"] = {
            "total": int(len(c_df)),
            "resolved": n_res,
            "positive": n_pos,
            "negative": n_neg,
            "positive_rate": float(n_pos / n_res * 100) if n_res else 0.0,
            "resolved_rate": float(n_res / len(c_df) * 100),
            "timeout": n_timeout,
            "session_end": n_sess,
            "gap": n_gap,
            "ambiguous": n_amb,
            "median_seconds": float(res_times.median()) if len(res_times) else None,
            "p25_seconds": float(res_times.quantile(0.25)) if len(res_times) else None,
            "p75_seconds": float(res_times.quantile(0.75)) if len(res_times) else None,
            "p90_seconds": float(res_times.quantile(0.90)) if len(res_times) else None,
            "frac_30s": float((res_times <= 30).sum() / len(res_times) * 100) if len(res_times) else 0.0,
            "frac_60s": float((res_times <= 60).sum() / len(res_times) * 100) if len(res_times) else 0.0,
            "frac_120s": float((res_times <= 120).sum() / len(res_times) * 100) if len(res_times) else 0.0,
            "frac_180s": float((res_times <= 180).sum() / len(res_times) * 100) if len(res_times) else 0.0,
            "frac_300s": float((res_times <= 300).sum() / len(res_times) * 100) if len(res_times) else 0.0,
        }

        # By Year
        feasibility_data[arm_name]["yearly"] = {}
        for y in [2021, 2022, 2023]:
            y_df = c_df[c_df["year"] == y]
            yd_vals = y_df[disp_col]
            yt_vals = y_df[time_col]
            y_pos = int((yd_vals == 1).sum())
            y_neg = int((yd_vals == 0).sum())
            y_res = y_pos + y_neg
            y_sess = int((yd_vals == -2).sum())
            y_gap = int((yd_vals == -3).sum())
            y_amb = int((yd_vals == -4).sum())
            y_timeout = int(((yd_vals == 0) & (yt_vals >= 300.0)).sum())
            y_res_times = yt_vals[yd_vals.isin([0, 1])]

            feasibility_data[arm_name]["yearly"][y] = {
                "total": int(len(y_df)),
                "resolved": y_res,
                "positive": y_pos,
                "negative": y_neg,
                "positive_rate": float(y_pos / y_res * 100) if y_res else 0.0,
                "resolved_rate": float(y_res / len(y_df) * 100),
                "timeout": y_timeout,
                "session_end": y_sess,
                "gap": y_gap,
                "ambiguous": y_amb,
                "median_seconds": float(y_res_times.median()) if len(y_res_times) else None,
                "p90_seconds": float(y_res_times.quantile(0.90)) if len(y_res_times) else None,
            }

        # By Direction
        feasibility_data[arm_name]["direction"] = {}
        for d_code, d_name in [(1, "LONG"), (-1, "SHORT")]:
            d_df = c_df[c_df["trade_direction"] == d_code]
            dd_vals = d_df[disp_col]
            dt_vals = d_df[time_col]
            d_pos = int((dd_vals == 1).sum())
            d_neg = int((dd_vals == 0).sum())
            d_res = d_pos + d_neg
            d_sess = int((dd_vals == -2).sum())
            d_gap = int((dd_vals == -3).sum())
            d_amb = int((dd_vals == -4).sum())
            d_res_times = dt_vals[dd_vals.isin([0, 1])]

            feasibility_data[arm_name]["direction"][d_name] = {
                "total": int(len(d_df)),
                "resolved": d_res,
                "positive": d_pos,
                "negative": d_neg,
                "positive_rate": float(d_pos / d_res * 100) if d_res else 0.0,
                "median_seconds": float(d_res_times.median()) if len(d_res_times) else None,
                "p90_seconds": float(d_res_times.quantile(0.90)) if len(d_res_times) else None,
            }

    # 6. Candidate Density and Regime Dependency
    c_df["regime_key"] = c_df["regime_direction"].astype(str) + "_" + c_df["regime_start_ns"].astype(str)
    unique_regimes_total = c_df["regime_key"].nunique()
    unique_regimes_long = c_df[c_df["trade_direction"] == 1]["regime_key"].nunique()
    unique_regimes_short = c_df[c_df["trade_direction"] == -1]["regime_key"].nunique()

    cands_per_regime = c_df.groupby("regime_key").size()
    cands_per_day = c_df.groupby("date_str").size()

    # Regime-level win rate (contains >=1 positive candidate)
    reg_pos_0 = c_df.groupby("regime_key")["arm0_disp"].apply(lambda s: (s == 1).sum() > 0)
    reg_pos_1 = c_df.groupby("regime_key")["arm1_disp"].apply(lambda s: (s == 1).sum() > 0)
    reg_pos_2 = c_df.groupby("regime_key")["arm2_disp"].apply(lambda s: (s == 1).sum() > 0)

    # First vs last candidate in regime
    c_df_sorted = c_df.sort_values(["regime_key", "checkpoint_index"])
    first_cands = c_df_sorted.groupby("regime_key").first()
    last_cands = c_df_sorted.groupby("regime_key").last()

    first_pos_rate_1 = float((first_cands["arm1_disp"] == 1).sum() / (first_cands["arm1_disp"].isin([0, 1])).sum() * 100)
    last_pos_rate_1 = float((last_cands["arm1_disp"] == 1).sum() / (last_cands["arm1_disp"].isin([0, 1])).sum() * 100)

    # 7. Feature Health
    feat_stats = []
    for feat in CANONICAL_FEATURES:
        vals = c_df[feat]
        n_total = len(vals)
        n_null = vals.isna().sum()
        n_inf = np.isinf(vals).sum()
        valid = vals.dropna()
        valid = valid[~np.isinf(valid)]
        feat_stats.append({
            "feature": feat,
            "null_pct": float(n_null / n_total * 100),
            "finite_pct": float((n_total - n_null - n_inf) / n_total * 100),
            "median": float(valid.median()) if len(valid) else None,
            "p01": float(valid.quantile(0.01)) if len(valid) else None,
            "p99": float(valid.quantile(0.99)) if len(valid) else None,
            "min": float(valid.min()) if len(valid) else None,
            "max": float(valid.max()) if len(valid) else None,
        })

    # Output dictionary
    results = {
        "integrity": {
            "duplicate_candidates": int(c_df.duplicated(subset=["observation_ts", "regime_start_ns", "checkpoint_index"]).sum()),
            "ordering_errors": int((c_df["observation_ts"].diff() < 0).sum()),
            "parity_mismatches": int(pos_mismatches + neg_mismatches + cens_mismatches),
            "impossible_transitions": int(total_impossible),
        },
        "density": {
            "total_candidates": int(n_cands),
            "long_candidates": int((c_df["trade_direction"] == 1).sum()),
            "short_candidates": int((c_df["trade_direction"] == -1).sum()),
            "unique_regimes_total": int(unique_regimes_total),
            "unique_regimes_long": int(unique_regimes_long),
            "unique_regimes_short": int(unique_regimes_short),
            "candidates_per_regime_median": float(cands_per_regime.median()),
            "candidates_per_regime_p90": float(cands_per_regime.quantile(0.90)),
            "candidates_per_day_median": float(cands_per_day.median()),
        },
        "regime_diagnostics": {
            "regimes_with_pos_arm0_pct": float(reg_pos_0.mean() * 100),
            "regimes_with_pos_arm1_pct": float(reg_pos_1.mean() * 100),
            "regimes_with_pos_arm2_pct": float(reg_pos_2.mean() * 100),
            "first_candidate_pos_rate_arm1": first_pos_rate_1,
            "last_candidate_pos_rate_arm1": last_pos_rate_1,
        },
        "transition_table": trans_table,
        "feasibility": feasibility_data,
        "feature_health": feat_stats,
    }

    out_file = WORK_DIR / "phase_c_full_results.json"
    out_file.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"\nSuccessfully wrote complete results to {out_file}")


if __name__ == "__main__":
    main()
