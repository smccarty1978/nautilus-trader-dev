"""Phase 1+2: Audit existing KNN/kC artifacts and build expanded feature set.

Produces:
  results/existing_feature_inventory.parquet
  results/knn_kc_audit.md
  results/knn_kc_audit.json
  results/expanded_features.parquet
"""
from __future__ import annotations

import json
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

OUT_DIR   = Path("studies/rl_regime_feasibility/expanded_dynamic/results")
SNAP_FILE = Path("studies/rl_regime_feasibility/results/feature_snapshots.parquet")
DNA_FILE  = Path("backtests/studies/regime_dna_knn/results/regime_dna.parquet")

OUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Phase 1: KNN/kC Audit ────────────────────────────────────────────────────

AUDIT_RECORDS = [
    {
        "artifact": "regime_dna.parquet",
        "location": "backtests/studies/regime_dna_knn/results/regime_dna.parquet",
        "shape": "146831 x 68",
        "key_columns": "regime_start_ts, pre_5/15/30_* (48 pre-flip features), ema9/21_slope, distance_to_vwap",
        "classification": "CAUSAL_SAFE",
        "rationale": (
            "All pre_5/15/30 features are computed exclusively from 1m bars "
            "COMPLETED before the flip bar. regime_start_ts is the CLOSE of the "
            "flip bar. EMA slopes and distances are at flip-bar close. VWAP and "
            "session high/low use only bars through flip-bar close. "
            "100% overlap with RL episode flip_time universe."
        ),
        "use_decision": "INCLUDE — join on flip_time=regime_start_ts as pre-flip context features",
    },
    {
        "artifact": "early_health_capsule.parquet",
        "location": "backtests/studies/regime_dna_knn/results/early_health_capsule.parquet",
        "shape": "146831 x 21",
        "key_columns": "regime_start_ts, pre5_efficiency, pre5_compression, n_post, post_o/h/l/c/v",
        "classification": "CAUSAL_UNCERTAIN",
        "rationale": (
            "pre5_* features are CAUSAL_SAFE (same logic as regime_dna pre_5_*). "
            "But n_post and post_o/h/l/c/v record the FIRST bar AFTER the flip — "
            "forward-looking relative to the flip. No causal guarantee on post_* columns."
        ),
        "use_decision": "EXCLUDE — pre5 columns are redundant with regime_dna; post_* are forward-looking",
    },
    {
        "artifact": "dna_knn_scores.parquet",
        "location": "backtests/studies/regime_dna_knn/results/dna_knn_scores.parquet",
        "shape": "1314501 x 42",
        "key_columns": "regime_id, bar_ts, score_pt050_sl025..score_failure_risk, score_expected_net",
        "classification": "NONCAUSAL",
        "rationale": (
            "KNN scores are trained on regime_dna DNA features via leave-one-out "
            "KNN lookup. The training set includes all years, meaning OOS regime IDs "
            "have neighbors from future years in the index. Additionally per MEMORY.md: "
            "'Bar-4 KNN path-atlas: calibrated for RISK/TIMING, blind on "
            "OPPORTUNITY/DIRECTION. rem-MFE skill +5% & P(+1 before -1) FLAT ~45% "
            "(blind). Closes V_A/flip+hC/Model-B line.' Dead signal class."
        ),
        "use_decision": "EXCLUDE — non-causal train/test contamination + dead signal per audit",
    },
    {
        "artifact": "obs_depth0p25/0p5/0p75.parquet (hC values)",
        "location": "studies/pullback_dna/results/obs_depth*.parquet",
        "shape": "23K-31K x 38 (per file)",
        "key_columns": "regime_start_ts, entry_ts, hC, hC_velocity, state",
        "classification": "NONCAUSAL",
        "rationale": (
            "These files record only regimes where hC >= 0.50 at pullback entry "
            "(bar 8+). Using them as RL features creates selection bias: ~57% of "
            "RL episodes have no pullback obs record. The hC value is computed at "
            "pullback entry_ts, not at the 5s observation time. The underlying "
            "components (EMA alignment, ATR, regime state) are already captured in "
            "existing features (ema3_ema9_spread, regime_5s/30s/5m aligned, adx14)."
        ),
        "use_decision": "EXCLUDE — selection bias + already covered by existing features",
    },
    {
        "artifact": "hc_sizing_extremes/trades.parquet",
        "location": "studies/hc_sizing_extremes/trades.parquet",
        "shape": "60 x 42",
        "key_columns": "decision_ts, hC, sizing_factor",
        "classification": "NONCAUSAL",
        "rationale": (
            "Only 60 trades covering 2025; too small a subset to use as features. "
            "hC at decision time is from the same pullback_dna computation logic. "
            "Not joinable to RL episode universe in a representative way."
        ),
        "use_decision": "EXCLUDE — too few samples, not representative",
    },
    {
        "artifact": "transition_atlas.parquet / opportunity_curve.parquet",
        "location": "studies/pullback_dna/results/reports/*.parquet",
        "shape": "253 x 14 / 9 x 5",
        "key_columns": "t_s (seconds), survival/probability summary statistics",
        "classification": "NONCAUSAL",
        "rationale": (
            "Population-level summary statistics (e.g., P(reach 0.5 ATR | alive at t=30s)). "
            "These are derived from the FULL outcome distribution and would inject "
            "look-ahead if used as per-observation features. They are not per-episode."
        ),
        "use_decision": "EXCLUDE — population summary statistics; forward-looking if used as features",
    },
]


def write_audit() -> None:
    print("Phase 1: Writing KNN/kC audit ...")

    # JSON
    with open(OUT_DIR / "knn_kc_audit.json", "w") as f:
        json.dump(AUDIT_RECORDS, f, indent=2)

    # Markdown
    lines = [
        "# KNN/kC Artifact Audit",
        "",
        "**Study**: rl_regime_feasibility/expanded_dynamic",
        "**Date**: 2026-07-03",
        "",
        "## Summary",
        "",
        "| Artifact | Classification | Use Decision |",
        "|----------|---------------|-------------|",
    ]
    for r in AUDIT_RECORDS:
        lines.append(f"| `{r['artifact']}` | {r['classification']} | {r['use_decision'].split(' — ')[0]} |")

    lines += [
        "",
        "## Detailed Findings",
        "",
    ]
    for r in AUDIT_RECORDS:
        lines += [
            f"### `{r['artifact']}`",
            f"**Location**: `{r['location']}`",
            f"**Shape**: {r['shape']}",
            f"**Key columns**: {r['key_columns']}",
            f"**Classification**: **{r['classification']}**",
            f"**Rationale**: {r['rationale']}",
            f"**Decision**: {r['use_decision']}",
            "",
        ]

    lines += [
        "## Approved Features for Expanded Study",
        "",
        "Only one external artifact is approved for joining:",
        "- **`regime_dna.parquet`** (CAUSAL_SAFE): 47 pre-flip features joined on `flip_time = regime_start_ts`",
        "- **Existing 28 features** from `feature_snapshots.parquet`",
        "- **~25 derived interaction/ratio features** computed from the above",
        "",
        "Total planned features: ~100",
    ]

    with open(OUT_DIR / "knn_kc_audit.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  Written: knn_kc_audit.md, knn_kc_audit.json")


# ── Phase 2: Build expanded features ─────────────────────────────────────────

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


def _safe_div(a: pd.Series, b: pd.Series, fill: float = 0.0) -> pd.Series:
    return np.where(b.abs() > 1e-9, a / b, fill)


def build_expanded_features() -> pd.DataFrame:
    t0 = time.time()
    print("\nPhase 2: Building expanded features ...")

    print("  Loading feature snapshots ...")
    snaps = pd.read_parquet(SNAP_FILE)
    print(f"  {len(snaps):,} rows, {snaps.shape[1]} cols")

    print("  Loading regime_dna ...")
    dna = pd.read_parquet(DNA_FILE, columns=["regime_start_ts"] + _DNA_COLS)
    print(f"  {len(dna):,} rows, {dna.shape[1]} cols")

    # Join on flip_time = regime_start_ts
    print("  Joining pre-flip context ...")
    merged = snaps.merge(
        dna.rename(columns={"regime_start_ts": "flip_time"}),
        on="flip_time",
        how="left",
    )
    n_miss = merged["atr_norm_at_flip"].isna().sum()
    print(f"  Join complete: {len(merged):,} rows, {n_miss} missing ({100*n_miss/len(merged):.1f}%)")

    # Derived features
    print("  Computing derived features ...")
    d = merged

    _EPS = 1e-9

    # Path geometry
    d["progress_sq_atr"]          = d["current_progress_atr"] ** 2 * np.sign(d["current_progress_atr"])
    d["adverse_vs_peak_ratio"]    = _safe_div(d["max_adverse_atr"], d["max_progress_atr"].clip(lower=_EPS))
    d["progress_minus_adverse"]   = d["current_progress_atr"] - d["max_adverse_atr"]
    d["pb_severity_ratio"]        = _safe_div(d["pullback_from_peak_atr"], d["max_progress_atr"].clip(lower=_EPS))
    d["current_vs_max_progress"]  = _safe_div(d["current_progress_atr"], d["max_progress_atr"].clip(lower=_EPS))
    d["time_since_peak_ratio"]    = _safe_div(d["seconds_since_peak"], d["seconds_since_flip"].clip(lower=1.0))
    d["position_in_episode"]      = d["seconds_since_flip"] / 1800.0  # fraction of max 30min
    d["seconds_remaining"]        = (1800.0 - d["seconds_since_flip"]).clip(lower=0)

    # Volatility/momentum interactions
    d["vol_x_velocity"]           = d["realized_vol_60s_atr"] * d["kalman_velocity_atr_per_s"].fillna(0)
    d["vol_x_acceleration"]       = d["realized_vol_60s_atr"] * d["kalman_acceleration_atr_per_s2"].fillna(0).abs()
    d["range_x_vol"]              = d["range_5s_atr"] * d["realized_vol_60s_atr"]

    # Regime alignment composite
    d["regime_alignment_score"]   = (d["regime_5s_aligned"] + d["regime_30s_aligned"] + d["regime_5m_aligned"])

    # ADX interactions
    d["adx_x_progress"]           = d["adx14_1m"].fillna(0) * d["current_progress_atr"]
    d["adx_x_max_progress"]       = d["adx14_1m"].fillna(0) * d["max_progress_atr"]

    # EMA spread interactions
    d["ema_spread_x_progress"]    = d["ema3_ema9_spread_30s_atr"].fillna(0) * d["current_progress_atr"]

    # Bollinger/vol interaction
    d["bb_x_vol"]                 = d["bollinger_width_percentile_1m"].fillna(0) * d["realized_vol_60s_atr"]

    # Pre-flip vs current interaction
    d["progress_x_compression"]   = d["current_progress_atr"] * d["pre_5_compression_score"].fillna(0)
    d["progress_x_pre5_eff"]      = d["current_progress_atr"] * d["pre_5_efficiency"].fillna(0)
    d["progress_x_lr_slope"]      = d["current_progress_atr"] * d["pre_5_lr_slope_atr"].fillna(0)

    # Pre-flip multi-window ratios
    d["pre_eff_5v15"]             = _safe_div(d["pre_5_efficiency"].fillna(0), d["pre_15_efficiency"].clip(lower=_EPS))
    d["pre_vol_5v15"]             = _safe_div(d["pre_5_volume_ratio"].fillna(0), d["pre_15_volume_ratio"].clip(lower=_EPS))
    d["pre_comp_5v30"]            = _safe_div(d["pre_5_compression_score"].fillna(0), d["pre_30_compression_score"].clip(lower=_EPS))
    d["flip_momentum_qual"]       = d["pre_5_lr_slope_atr"].fillna(0) * d["pre_5_compression_score"].fillna(0)
    d["pre_vol_accel"]            = d["pre_5_volume_zscore"].fillna(0) - d["pre_15_volume_zscore"].fillna(0)

    # Kalman-based regime signal
    d["kalman_aligned"]           = (d["kalman_velocity_atr_per_s"].fillna(0) > 0).astype(float) * 2 - 1
    d["kalman_accel_aligned"]     = (d["kalman_acceleration_atr_per_s2"].fillna(0) > 0).astype(float) * 2 - 1

    # Episode structure
    d["step_index_scaled"]        = d["step_index"] / 360.0  # max ~360 steps in 30min episode at 5s

    print(f"  Done. {d.shape[1]} total columns in {time.time()-t0:.1f}s")
    return d


def write_inventory(df: pd.DataFrame) -> None:
    existing = [
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
    rows = []
    meta_cols = {"episode_id", "step_index", "observation_time", "flip_time", "flip_close",
                 "atr_at_flip", "direction", "termination_reason", "episode_end_time", "period"}
    for col in df.columns:
        if col in meta_cols:
            continue
        source = "existing_collector"
        if col in existing:
            source = "existing_collector"
        elif col in _DNA_COLS:
            source = "regime_dna_preflip"
        else:
            source = "derived"
        rows.append({"feature": col, "source": source})

    inv = pd.DataFrame(rows)
    inv.to_parquet(OUT_DIR / "existing_feature_inventory.parquet", index=False)
    print(f"\nInventory: {len(inv)} features ({inv['source'].value_counts().to_dict()})")


def get_feature_cols(df: pd.DataFrame) -> list[str]:
    meta_cols = {"episode_id", "step_index", "observation_time", "flip_time", "flip_close",
                 "atr_at_flip", "direction", "termination_reason", "episode_end_time", "period"}
    return [c for c in df.columns if c not in meta_cols]


if __name__ == "__main__":
    write_audit()
    df = build_expanded_features()
    write_inventory(df)

    # Save expanded features
    feat_cols = get_feature_cols(df)
    print(f"\nSaving expanded_features.parquet with {len(feat_cols)} features ...")
    df.to_parquet(OUT_DIR / "expanded_features.parquet", index=False)
    print(f"  Saved: {len(df):,} rows x {df.shape[1]} cols")
    print(f"\n  Feature groups:")
    existing_n = sum(1 for c in feat_cols if c in [
        "seconds_since_flip","current_progress_atr","max_progress_atr","max_adverse_atr",
        "pullback_from_peak_atr","seconds_since_peak","progress_efficiency",
        "aligned_return_5s_atr","aligned_return_15s_atr","aligned_return_30s_atr",
        "aligned_return_60s_atr","realized_vol_60s_atr","range_5s_atr",
        "volume_5s_zscore","volume_30s_vs_5m","bollinger_width_percentile_1m",
        "bollinger_keltner_width_ratio_1m","kalman_velocity_atr_per_s",
        "kalman_acceleration_atr_per_s2","kalman_innovation_zscore",
        "ema3_ema9_spread_30s_atr","regime_5s_aligned","regime_30s_aligned",
        "regime_5m_aligned","regime_age_1m_bars","adx14_1m",
        "position_in_trailing_1m_range","minutes_since_rth_open",
    ])
    dna_n = sum(1 for c in feat_cols if c in _DNA_COLS)
    derived_n = len(feat_cols) - existing_n - dna_n
    print(f"    Existing collector: {existing_n}")
    print(f"    Pre-flip DNA:       {dna_n}")
    print(f"    Derived:            {derived_n}")
    print(f"    Total:              {len(feat_cols)}")
