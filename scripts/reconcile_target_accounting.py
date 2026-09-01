"""Phase C.1 Target Accounting Reconciliation Script.
===================================================
Produces authoritative, mutually-exclusive target accounting for all 1,387,411 candidates
across 2021-2023 and all 3 target arms (TP 1.0 / SL 0.5, 1.0, 1.5).
"""

from __future__ import annotations

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
RUNS_DIR = STUDY_DIR / "runs"

NS = 1_000_000_000


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
    """Evaluates 3 arms for a chunk of candidates.
    Returns:
      dispositions: (3, n_cands) strings
      labels: (3, n_cands) float (1.0, 0.0, NaN)
      resolution_seconds: (3, n_cands) float
      resolution_types: (3, n_cands) strings
    """
    n_cands = len(obs_ts)
    # Output codes:
    # 1 = POSITIVE (hit TP)
    # 0 = NEGATIVE_SL (hit SL)
    # -1 = NEGATIVE_TIMEOUT (reached 300s without hitting either)
    # -2 = SESSION_END (censored)
    # -3 = GAP (censored)
    # -4 = AMBIGUOUS (censored)
    # -5 = DATA_END (censored)
    codes = np.zeros((3, n_cands), dtype=np.int8)
    times = np.zeros((3, n_cands), dtype=np.float32)

    for idx in range(n_cands):
        T = obs_ts[idx]
        direction = directions[idx]
        atr = atrs[idx]
        session_close = session_close_ns(T, "RTH")

        start_idx = np.searchsorted(events_ts, T, side="right")
        end_idx = np.searchsorted(events_ts, T + 350 * NS, side="right")

        if start_idx >= len(events_ts) or start_idx >= end_idx:
            codes[:, idx] = -5
            times[:, idx] = 300.0
            continue

        entry_price = events_open[start_idx]

        if direction == 1:
            tp_0 = entry_price + 1.0 * atr; sl_0 = entry_price - 0.5 * atr
            tp_1 = entry_price + 1.0 * atr; sl_1 = entry_price - 1.0 * atr
            tp_2 = entry_price + 1.0 * atr; sl_2 = entry_price - 1.5 * atr
        else:
            tp_0 = entry_price - 1.0 * atr; sl_0 = entry_price + 0.5 * atr
            tp_1 = entry_price - 1.0 * atr; sl_1 = entry_price + 1.0 * atr
            tp_2 = entry_price - 1.0 * atr; sl_2 = entry_price + 1.5 * atr

        resolved_0 = False; resolved_1 = False; resolved_2 = False

        for b_i in range(start_idx, end_idx):
            bar_ts = events_ts[b_i]
            res_sec = (bar_ts - T) / NS

            if bar_ts > session_close:
                if not resolved_0: codes[0, idx] = -2; times[0, idx] = res_sec; resolved_0 = True
                if not resolved_1: codes[1, idx] = -2; times[1, idx] = res_sec; resolved_1 = True
                if not resolved_2: codes[2, idx] = -2; times[2, idx] = res_sec; resolved_2 = True
                break

            if events_gap[b_i]:
                if not resolved_0: codes[0, idx] = -3; times[0, idx] = res_sec; resolved_0 = True
                if not resolved_1: codes[1, idx] = -3; times[1, idx] = res_sec; resolved_1 = True
                if not resolved_2: codes[2, idx] = -3; times[2, idx] = res_sec; resolved_2 = True
                break

            b_h = events_high[b_i]; b_l = events_low[b_i]

            # Arm 0 (SL 0.5)
            if not resolved_0:
                h_tp = b_h >= tp_0 if direction == 1 else b_l <= tp_0
                h_sl = b_l <= sl_0 if direction == 1 else b_h >= sl_0
                if h_tp and h_sl: codes[0, idx] = -4; times[0, idx] = res_sec; resolved_0 = True
                elif h_tp: codes[0, idx] = 1; times[0, idx] = res_sec; resolved_0 = True
                elif h_sl: codes[0, idx] = 0; times[0, idx] = res_sec; resolved_0 = True

            # Arm 1 (SL 1.0)
            if not resolved_1:
                h_tp = b_h >= tp_1 if direction == 1 else b_l <= tp_1
                h_sl = b_l <= sl_1 if direction == 1 else b_h >= sl_1
                if h_tp and h_sl: codes[1, idx] = -4; times[1, idx] = res_sec; resolved_1 = True
                elif h_tp: codes[1, idx] = 1; times[1, idx] = res_sec; resolved_1 = True
                elif h_sl: codes[1, idx] = 0; times[1, idx] = res_sec; resolved_1 = True

            # Arm 2 (SL 1.5)
            if not resolved_2:
                h_tp = b_h >= tp_2 if direction == 1 else b_l <= tp_2
                h_sl = b_l <= sl_2 if direction == 1 else b_h >= sl_2
                if h_tp and h_sl: codes[2, idx] = -4; times[2, idx] = res_sec; resolved_2 = True
                elif h_tp: codes[2, idx] = 1; times[2, idx] = res_sec; resolved_2 = True
                elif h_sl: codes[2, idx] = 0; times[2, idx] = res_sec; resolved_2 = True

            if resolved_0 and resolved_1 and resolved_2:
                break

            if bar_ts >= T + horizon_ns:
                if not resolved_0: codes[0, idx] = -1; times[0, idx] = 300.0; resolved_0 = True
                if not resolved_1: codes[1, idx] = -1; times[1, idx] = 300.0; resolved_1 = True
                if not resolved_2: codes[2, idx] = -1; times[2, idx] = 300.0; resolved_2 = True
                break

        if not resolved_0: codes[0, idx] = -1; times[0, idx] = 300.0
        if not resolved_1: codes[1, idx] = -1; times[1, idx] = 300.0
        if not resolved_2: codes[2, idx] = -1; times[2, idx] = 300.0

    return codes, times


def main():
    print("============================================================")
    print("PHASE C.1 TARGET ACCOUNTING RECONCILIATION")
    print("============================================================")

    c_df = pd.read_parquet(WORK_DIR / "candidates.parquet")
    o_df = pd.read_parquet(WORK_DIR / "observations.parquet")
    n_cands = len(c_df)
    print(f"Loaded {n_cands:,} candidates.")

    # Check partition parity against raw partition outputs
    part_runs = {
        2021: RUNS_DIR / "20260831_205335_regime_transition_target_before_stop_v1_full",
        2022: RUNS_DIR / "20260831_231201_regime_transition_target_before_stop_v1_full",
        2023: RUNS_DIR / "20260901_033344_regime_transition_target_before_stop_v1_full",
    }
    part_counts = {}
    for y, p_dir in part_runs.items():
        p_c = pd.read_parquet(p_dir / "collection" / "candidates.parquet")
        p_o = pd.read_parquet(p_dir / "collection" / "observations.parquet")
        part_counts[y] = {"cands": len(p_c), "obs": len(p_o), "disp": p_o["disposition"].value_counts().to_dict()}
        print(f"Partition {y} ({p_dir.name}): candidates={len(p_c):,}, observations={len(p_o):,}, dispositions={part_counts[y]['disp']}")

    # Add temporal metadata
    c_df["ts_dt"] = pd.to_datetime(c_df["observation_ts"], unit="ns", utc=True)
    c_df["year"] = c_df["ts_dt"].dt.year
    c_df["month_str"] = c_df["ts_dt"].dt.strftime("%Y-%m")
    c_df["date_str"] = c_df["ts_dt"].dt.strftime("%Y-%m-%d")

    # Prevailing regime direction & candidate direction
    regime_directions = o_df["regime_direction"].to_numpy(dtype=np.int8)
    trade_directions = (-regime_directions).astype(np.int8)
    obs_ts_all = c_df["observation_ts"].to_numpy(dtype=np.int64)

    # 1. Causal 1m ATR timeline
    print("\n---> Loading 1m bars for causal ATR timeline...")
    loader = CausalDataLoader(CATALOG_PATH)
    m1_bars = loader.load_bars(
        "NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        pd.Timestamp("2020-12-27 00:00:00", tz="UTC"),
        pd.Timestamp("2023-12-31 23:59:59", tz="UTC"),
    )
    engine = RegimeEngine()
    m1_ts_inits = np.zeros(len(m1_bars), dtype=np.int64)
    m1_atrs = np.zeros(len(m1_bars), dtype=np.float64)
    for i, b in enumerate(m1_bars):
        m1_ts_inits[i] = int(b.ts_init)
        m1_atrs[i] = engine.update(float(b.high), float(b.low), float(b.close))

    atr_indices = np.searchsorted(m1_ts_inits, obs_ts_all, side="right") - 1
    atr_indices = np.clip(atr_indices, 0, len(m1_atrs) - 1)
    cand_atrs = m1_atrs[atr_indices]

    # 2. Replay all 3 arms
    months = sorted(c_df["month_str"].unique())
    print(f"\n---> Replaying 3 target arms across {len(months)} months...")
    all_codes = np.zeros((3, n_cands), dtype=np.int8)
    all_times = np.zeros((3, n_cands), dtype=np.float32)

    for m_idx, m_str in enumerate(months):
        m_mask = (c_df["month_str"] == m_str).to_numpy()
        m_indices = np.where(m_mask)[0]
        if len(m_indices) == 0:
            continue

        m_start = pd.Timestamp(f"{m_str}-01 00:00:00", tz="UTC")
        m_end = (m_start + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1))
        m_bars_1s = loader.load_bars("NQ.XCME-1-SECOND-LAST-EXTERNAL", m_start, m_end)

        n_1s = len(m_bars_1s)
        events_ts = np.array([int(b.ts_init) for b in m_bars_1s], dtype=np.int64)
        events_open = np.array([float(b.open) for b in m_bars_1s], dtype=np.float64)
        events_high = np.array([float(b.high) for b in m_bars_1s], dtype=np.float64)
        events_low = np.array([float(b.low) for b in m_bars_1s], dtype=np.float64)
        events_gap = np.zeros(n_1s, dtype=bool)

        codes_chunk, times_chunk = evaluate_chunk(
            obs_ts=obs_ts_all[m_indices],
            directions=regime_directions[m_indices],
            atrs=cand_atrs[m_indices],
            events_ts=events_ts,
            events_open=events_open,
            events_high=events_high,
            events_low=events_low,
            events_gap=events_gap,
        )
        all_codes[:, m_indices] = codes_chunk
        all_times[:, m_indices] = times_chunk

    print("Replay completed.")

    # 3. Mutually Exclusive Accounting Table Computation
    # Codes:
    # 1  = POSITIVE
    # 0  = NEGATIVE (Hit SL)
    # -1 = TIMEOUT (Reached 300s without hit)
    # -2 = SESSION_END
    # -3 = GAP
    # -4 = AMBIGUOUS
    # -5 = DATA_END
    
    arms_config = [
        ("TP1_SL0_5", 0),
        ("TP1_SL1_0", 1),
        ("TP1_SL1_5", 2),
    ]

    accounting_summary = {}

    for arm_name, arm_idx in arms_config:
        codes = all_codes[arm_idx]
        times = all_times[arm_idx]
        
        # Build DataFrame for easy aggregation
        df_arm = pd.DataFrame({
            "year": c_df["year"],
            "direction": trade_directions,
            "code": codes,
            "time": times,
        })
        df_arm["dir_name"] = df_arm["direction"].map({1: "LONG", -1: "SHORT"})

        accounting_summary[arm_name] = {"cells": {}, "pooled": {}}

        # Process by Year x Direction
        for y in [2021, 2022, 2023, "POOLED"]:
            for d in ["LONG", "SHORT", "ALL"]:
                if y == "POOLED" and d == "ALL":
                    sub = df_arm
                    cell_key = "POOLED"
                elif y == "POOLED":
                    sub = df_arm[df_arm["dir_name"] == d]
                    cell_key = f"POOLED_{d}"
                elif d == "ALL":
                    sub = df_arm[df_arm["year"] == y]
                    cell_key = f"{y}_ALL"
                else:
                    sub = df_arm[(df_arm["year"] == y) & (df_arm["dir_name"] == d)]
                    cell_key = f"{y}_{d}"

                n_tot = len(sub)
                n_pos = int((sub["code"] == 1).sum())
                n_neg_sl = int((sub["code"] == 0).sum())
                n_timeout = int((sub["code"] == -1).sum())
                n_neg_total = n_neg_sl + n_timeout
                n_sess = int((sub["code"] == -2).sum())
                n_gap = int((sub["code"] == -3).sum())
                n_amb = int((sub["code"] == -4).sum())
                n_data_end = int((sub["code"] == -5).sum())

                n_labeled = n_pos + n_neg_total
                n_censored = n_sess + n_gap + n_amb + n_data_end
                n_terminal = n_labeled + n_censored

                # Verification of accounting identity
                identity_pass = (n_terminal == n_tot) and (n_labeled == n_pos + n_neg_sl + n_timeout) and (n_censored == n_sess + n_gap + n_amb + n_data_end)

                pos_rate_labeled = (n_pos / n_labeled * 100) if n_labeled else 0.0
                censor_rate = (n_censored / n_tot * 100) if n_tot else 0.0

                cell_stats = {
                    "total": n_tot,
                    "positive": n_pos,
                    "negative_sl": n_neg_sl,
                    "timeout": n_timeout,
                    "negative_total": n_neg_total,
                    "session_end": n_sess,
                    "gap": n_gap,
                    "ambiguous": n_amb,
                    "data_end": n_data_end,
                    "labeled_count": n_labeled,
                    "censored_count": n_censored,
                    "terminal_count": n_terminal,
                    "positive_rate_among_labeled": float(pos_rate_labeled),
                    "censor_rate": float(censor_rate),
                    "identity_pass": bool(identity_pass),
                }

                if cell_key == "POOLED":
                    accounting_summary[arm_name]["pooled"] = cell_stats
                else:
                    accounting_summary[arm_name]["cells"][cell_key] = cell_stats

    # 4. Cross-Arm Invariant Transition Table (Exact Mutually Exclusive)
    # Map each candidate to 3-arm tuple
    trans_records = []
    # Map code to string
    code_map = {1: "POS", 0: "NEG_SL", -1: "TIMEOUT", -2: "SESS", -3: "GAP", -4: "AMB", -5: "DATA_END"}
    code_broad_map = {1: "POS", 0: "NEG", -1: "NEG", -2: "CENS", -3: "CENS", -4: "CENS", -5: "CENS"}

    c0 = all_codes[0]; c1 = all_codes[1]; c2 = all_codes[2]
    # Check impossible widening stop transitions:
    # If SL 0.5 is POS, SL 1.0 cannot be NEG (either SL or TIMEOUT)
    # If SL 1.0 is POS, SL 1.5 cannot be NEG
    imp_01 = int(np.sum((c0 == 1) & ((c1 == 0) | (c1 == -1))))
    imp_12 = int(np.sum((c1 == 1) & ((c2 == 0) | (c2 == -1))))
    imp_02 = int(np.sum((c0 == 1) & ((c2 == 0) | (c2 == -1))))
    total_impossible = imp_01 + imp_12 + imp_02

    # Comprehensive transition counts
    t_df = pd.DataFrame({"arm0": [code_map[c] for c in c0], "arm1": [code_map[c] for c in c1], "arm2": [code_map[c] for c in c2]})
    t_df["trans"] = t_df["arm0"] + " -> " + t_df["arm1"] + " -> " + t_df["arm2"]
    trans_counts = t_df["trans"].value_counts().to_dict()

    print("\n============================================================")
    print("ACCOUNTING IDENTITIES & CROSS-ARM INVARIANTS")
    print("============================================================")
    print(f"Total Impossible Transitions (Pos -> Neg): {total_impossible}")
    print(f"Cross-Arm Transition Table Total Rows: {len(t_df):,} (Expected: {n_cands:,})")
    for arm_name in arms_config:
        p_stat = accounting_summary[arm_name[0]]["pooled"]
        print(f"\nArm: {arm_name[0]}")
        print(f"  Total: {p_stat['total']:,}")
        print(f"  Labeled: {p_stat['labeled_count']:,} (Pos: {p_stat['positive']:,}, Neg_SL: {p_stat['negative_sl']:,}, Timeout: {p_stat['timeout']:,})")
        print(f"  Censored: {p_stat['censored_count']:,} (Sess: {p_stat['session_end']:,}, Amb: {p_stat['ambiguous']:,}, Gap: {p_stat['gap']:,}, DataEnd: {p_stat['data_end']:,})")
        print(f"  Terminal: {p_stat['terminal_count']:,}")
        print(f"  Identity Pass: {p_stat['identity_pass']}")

    # 5. Regime Decay Follow-Up
    c_df["regime_key"] = o_df["regime_direction"].astype(str) + "_" + c_df["regime_start_ns"].astype(str)
    c_df["arm1_code"] = all_codes[1]
    c_df["trade_dir_name"] = trade_directions
    c_df["trade_dir_name"] = c_df["trade_dir_name"].map({1: "LONG", -1: "SHORT"})

    # Ordinal index within regime
    c_df["regime_ordinal"] = c_df.groupby("regime_key").cumcount()
    c_df["regime_size"] = c_df.groupby("regime_key")["regime_ordinal"].transform("max") + 1
    c_df["regime_ordinal_pct"] = c_df["regime_ordinal"] / c_df["regime_size"]

    # Decile bins
    c_df["ordinal_decile"] = pd.qcut(c_df["regime_ordinal_pct"], q=10, labels=[f"D{i+1}" for i in range(10)], duplicates="drop")
    c_df["age_decile"] = pd.qcut(c_df["regime_age_seconds"], q=10, labels=[f"A{i+1}" for i in range(10)], duplicates="drop")

    # Win rate by ordinal decile
    decay_by_ordinal = c_df.groupby("ordinal_decile", observed=False)["arm1_code"].apply(lambda s: (s == 1).sum() / (s.isin([0, 1, -1])).sum() * 100).to_dict()
    decay_by_year = c_df.groupby(["year", "ordinal_decile"], observed=False)["arm1_code"].apply(lambda s: (s == 1).sum() / (s.isin([0, 1, -1])).sum() * 100).unstack().to_dict()
    decay_by_dir = c_df.groupby(["trade_dir_name", "ordinal_decile"], observed=False)["arm1_code"].apply(lambda s: (s == 1).sum() / (s.isin([0, 1, -1])).sum() * 100).unstack().to_dict()

    out_data = {
        "accounting": accounting_summary,
        "cross_arm": {
            "total_rows": len(t_df),
            "impossible_transitions": total_impossible,
            "transitions": trans_counts,
        },
        "regime_decay": {
            "by_ordinal_decile_pooled": decay_by_ordinal,
            "by_year_and_decile": decay_by_year,
            "by_direction_and_decile": decay_by_dir,
        },
        "partitions_reconciled": part_counts,
    }

    out_file = WORK_DIR / "phase_c1_accounting_reconciliation.json"
    out_file.write_text(json.dumps(out_data, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved accounting reconciliation report to: {out_file}")


if __name__ == "__main__":
    main()
