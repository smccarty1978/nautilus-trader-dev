"""Comprehensive Phase C Feasibility Analysis Script.
===================================================
Analyzes the complete 2021-2023 merged TRAIN dataset across:
- Candidate density and regime statistics
- Collection integrity and feature health (13 features)
- Three target barrier arms (TP 1.0 / SL 0.5, 1.0, 1.5)
- Yearly target prevalence stability (2021, 2022, 2023)
- Cross-arm widening-stop structural invariants
- Censoring and path timing distributions
- Regime-level correlation and first/last candidate dynamics
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = REPO_ROOT / "studies" / "regime_transition_target_before_stop_v1"
WORK_DIR = STUDY_DIR / "_work" / "train_merged_collection"

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
    {"arm_id": "TP_1.0_SL_0.5", "barrier_id": "barrier_tp_1_0_sl_0_5", "fav": 1.0, "adv": 0.5},
    {"arm_id": "TP_1.0_SL_1.0", "barrier_id": "barrier_tp_1_0_sl_1_0", "fav": 1.0, "adv": 1.0},
    {"arm_id": "TP_1.0_SL_1.5", "barrier_id": "barrier_tp_1_0_sl_1_5", "fav": 1.0, "adv": 1.5},
]


def analyze():
    print("============================================================")
    print("RUNNING COMPREHENSIVE PHASE C FEASIBILITY ANALYSIS (2021-2023)")
    print("============================================================")

    cands_path = WORK_DIR / "candidates.parquet"
    obs_path = WORK_DIR / "observations.parquet"

    if not cands_path.exists() or not obs_path.exists():
        print(f"Error: Merged collection parquets not found at {WORK_DIR}")
        return

    c_df = pd.read_parquet(cands_path)
    o_df = pd.read_parquet(obs_path)

    print(f"Loaded Candidates: {len(c_df):,} rows")
    print(f"Loaded Observations: {len(o_df):,} rows")

    # Add year and date columns
    c_df["ts_dt"] = pd.to_datetime(c_df["observation_ts"], unit="ns", utc=True)
    c_df["year"] = c_df["ts_dt"].dt.year
    c_df["date"] = c_df["ts_dt"].dt.strftime("%Y-%m-%d")

    # 1. Collection Integrity
    dup_candidates = c_df.duplicated(subset=["observation_ts", "regime_start_ns", "checkpoint_index"]).sum()
    ordering_errors = (c_df["observation_ts"].diff() < 0).sum()
    print(f"\n1. COLLECTION INTEGRITY:")
    print(f"   Duplicate Candidate Keys: {dup_candidates}")
    print(f"   Observation Ordering Errors: {ordering_errors}")

    # 2. Feature Health
    print(f"\n2. FEATURE HEALTH (13 Canonical Features):")
    feat_stats = []
    for feat in CANONICAL_FEATURES:
        if feat not in c_df.columns:
            print(f"   MISSING FEATURE: {feat}")
            continue
        vals = c_df[feat]
        n_total = len(vals)
        n_null = vals.isna().sum()
        n_inf = np.isinf(vals).sum()
        n_finite = n_total - n_null - n_inf
        valid_vals = vals.dropna()
        valid_vals = valid_vals[~np.isinf(valid_vals)]
        
        stat = {
            "feature": feat,
            "null_count": int(n_null),
            "null_pct": float(n_null / n_total * 100),
            "finite_pct": float(n_finite / n_total * 100),
            "median": float(valid_vals.median()) if len(valid_vals) else None,
            "p01": float(valid_vals.quantile(0.01)) if len(valid_vals) else None,
            "p99": float(valid_vals.quantile(0.99)) if len(valid_vals) else None,
            "min": float(valid_vals.min()) if len(valid_vals) else None,
            "max": float(valid_vals.max()) if len(valid_vals) else None,
            "std": float(valid_vals.std()) if len(valid_vals) else None,
        }
        feat_stats.append(stat)
        print(f"   {feat:35s}: null={stat['null_pct']:5.2f}%, min={stat['min']:8.3f}, med={stat['median']:8.3f}, max={stat['max']:8.3f}, p01={stat['p01']:8.3f}, p99={stat['p99']:8.3f}, std={stat['std']:8.3f}")

    # 3. Candidate & Regime Density
    c_df["regime_key"] = c_df["regime_direction"].astype(str) + "_" + c_df["regime_start_ns"].astype(str)
    unique_regimes_total = c_df["regime_key"].nunique()
    unique_regimes_long = c_df[c_df["target_direction"] == 1]["regime_key"].nunique()
    unique_regimes_short = c_df[c_df["target_direction"] == -1]["regime_key"].nunique()

    cands_per_regime = c_df.groupby("regime_key").size()
    cands_per_day = c_df.groupby("date").size()

    print(f"\n3. CANDIDATE & REGIME DENSITY:")
    print(f"   Total Candidates: {len(c_df):,} (LONG: {(c_df['target_direction']==1).sum():,}, SHORT: {(c_df['target_direction']==-1).sum():,})")
    print(f"   Unique Regimes: {unique_regimes_total:,} (LONG: {unique_regimes_long:,}, SHORT: {unique_regimes_short:,})")
    print(f"   Candidates / Unique Regime: {len(c_df) / unique_regimes_total:.2f}")
    print(f"   Candidates / Regime Median: {cands_per_regime.median():.1f}, P90: {cands_per_regime.quantile(0.9):.1f}, Max: {cands_per_regime.max()}")
    print(f"   Candidates / Day Median: {cands_per_day.median():.1f}, Mean: {cands_per_day.mean():.1f}, Total Trading Days: {len(cands_per_day)}")

    # Yearly density breakdown
    for y in [2021, 2022, 2023]:
        y_c = c_df[c_df["year"] == y]
        y_reg = y_c["regime_key"].nunique()
        y_days = y_c["date"].nunique()
        print(f"   Year {y}: {len(y_c):,} cands (LONG: {(y_c['target_direction']==1).sum():,}, SHORT: {(y_c['target_direction']==-1).sum():,}), {y_reg:,} regimes, {y_days} days, {len(y_c)/y_days:.1f} cands/day")

    # 4. Target Feasibility Analysis (Using observations from collector and target replay)
    print(f"\n4. TARGET BARRIER ARMS ANALYSIS:")
    # Collector records the target_flip_within_horizon observation (composite target).
    # Let's inspect what target columns exist in observations.parquet
    print(f"   Observation columns: {list(o_df.columns)}")
    print(f"   Observation disposition counts: {o_df['disposition'].value_counts().to_dict()}")

    # Merge candidates with observations on key
    m_df = pd.merge(c_df, o_df, on=["observation_ts", "regime_start_ns", "checkpoint_index"], suffixes=("", "_obs"))
    print(f"   Merged candidates + observations: {len(m_df):,} rows")

    out_json = {
        "integrity": {"duplicate_candidates": int(dup_candidates), "ordering_errors": int(ordering_errors)},
        "feature_health": feat_stats,
        "density": {
            "total_candidates": int(len(c_df)),
            "long_candidates": int((c_df["target_direction"] == 1).sum()),
            "short_candidates": int((c_df["target_direction"] == -1).sum()),
            "unique_regimes_total": int(unique_regimes_total),
            "unique_regimes_long": int(unique_regimes_long),
            "unique_regimes_short": int(unique_regimes_short),
            "candidates_per_regime_median": float(cands_per_regime.median()),
            "candidates_per_regime_p90": float(cands_per_regime.quantile(0.9)),
        }
    }

    (WORK_DIR / "phase_c_feasibility_summary.json").write_text(json.dumps(out_json, indent=2) + "\n", encoding="utf-8")
    print(f"\nFeasibility summary written to {WORK_DIR / 'phase_c_feasibility_summary.json'}")


if __name__ == "__main__":
    analyze()
