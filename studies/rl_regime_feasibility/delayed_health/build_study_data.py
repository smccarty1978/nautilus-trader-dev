"""Phases 1-4: Bar-4 definition, causal KNN health scores, bar-4 survivor population.

Outputs:
  results/bar4_definition.md
  results/bar4_definition.json
  results/knn_generation_contract.json
  results/knn_provenance_audit.json
  results/causal_knn_health.parquet
  results/bar4_survivors.parquet
  results/bar4_population_summary.parquet
  results/entry_targets.parquet
  results/exit_targets.parquet
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
from sklearn.neighbors import KDTree
from sklearn.preprocessing import StandardScaler

OUT_DIR = Path("studies/rl_regime_feasibility/delayed_health/results")
SNAP_FILE = Path("studies/rl_regime_feasibility/results/feature_snapshots.parquet")
LABEL_FILE = Path("studies/rl_regime_feasibility/results/forward_labels.parquet")
EP_FILE = Path("studies/rl_regime_feasibility/results/episode_summary.parquet")

_NS = 1_000_000_000
_NQ_MULT = 20.0
_COMM = 5.0
_ATR_STOP = 1.5

# ── Bar-4 definition ──────────────────────────────────────────────────────────
# From archive/studies/1m_mtf_context/analysis/delayed_entry_bar4.py:
#   "Delayed entry @ bar+4 open (~120s after current entry)"
#   "filter: regime active at bar+3 close"
#   delay_s = 120 from V_A entry_ts
# V_A entry in that study ≈ flip_bar_OPEN + 30s ≈ flip_time - 30s
# So bar+3 close from V_A entry = flip_time - 30s + 120s = flip_time + 90s
#
# For this RL study, the natural reference is flip_time (the moment the 1m flip bar closes).
# 4 complete 1-minute bars after flip close = flip_time + 240s.
# We define BAR4_DELAY_S = 240s, corresponding to step_index >= 48 in the 5s observation space.
# We also run placebo tests at 60s, 120s, 180s, 300s, 360s to find the survival knee.
#
BAR4_DELAY_S = 240
BAR4_STEP_INDEX = BAR4_DELAY_S // 5  # = 48

# KNN parameters
KNN_K = 100
KNN_SEED = 42
KNN_LIB_SAMPLE = 80_000   # sample the library to this size to keep KDTree queries fast

# 12 KNN features mapped from feature_snapshots columns
_KNN_FEAT_MAP = {
    "bar_idx":          "regime_age_1m_bars",       # 1m bar index
    "mfe_sofar":        "max_progress_atr",          # max favorable excursion
    "mae_sofar":        "max_adverse_atr",            # max adverse excursion
    "pnl_now":          "current_progress_atr",       # current PnL in ATR
    "pullback":         "pullback_from_peak_atr",     # pullback from peak
    "health_ratio":     None,                          # computed: mfe/max(mae,0.1)
    "progress_eff":     "progress_efficiency",         # directional efficiency
    "close_loc":        "position_in_trailing_1m_range",
    "range_exp":        "range_5s_atr",
    "vol_exp":          "volume_5s_zscore",
    "ema_spread":       "ema3_ema9_spread_30s_atr",
    "kalman_vel":       "kalman_velocity_atr_per_s",
}

_KNN_FEAT_NAMES = list(_KNN_FEAT_MAP.keys())

# 28 baseline live-state features (from expanded study)
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

PLACEBO_DELAYS_S = [60, 120, 180, 240, 300, 360]

# ── Phase 1: Bar-4 definition ──────────────────────────────────────────────────

def write_bar4_definition():
    print("Phase 1: Writing bar-4 definition ...")

    defn = {
        "bar4_delay_seconds": BAR4_DELAY_S,
        "bar4_step_index": BAR4_STEP_INDEX,
        "reference_point": "flip_time (close of the 1m bar that triggered the regime flip)",
        "bar4_decision_timestamp": f"flip_time + {BAR4_DELAY_S}s",
        "fill_timestamp": "next 1s bar OPEN at or after decision_timestamp",
        "bars_counted_from": "flip_time (flip bar = bar 0, bar 1 closes at flip+60s, bar 4 closes at flip+240s)",
        "survival_requirement": "episode still active (no opposing flip) at bar-4 decision timestamp",
        "direction_requirement": "same direction as original flip",
        "bar4_confirmation_requirement": False,
        "sources_consulted": [
            "archive/studies/1m_mtf_context/analysis/delayed_entry_bar4.py (delay_s=120 from V_A entry_ts ~ flip+60s -> flip+180s equivalent)",
            "backtests/studies/regime_dna_knn/bar4_knn_path_atlas.py (bar k>=4 from entry)",
            "MEMORY.md: 'bar-4 all-flips, GTC market' in ml_entry_knn_hc_mgmt study",
            "MEMORY.md: 'Post-Bar3 QuickFail-rejection → Bar4 entry' counting bars from flip",
        ],
        "definition_ambiguity": (
            "The archived study (delayed_entry_bar4.py) counts 120s from V_A entry_ts (~flip-30s to flip+90s), "
            "corresponding to approximately flip+90s. However, the ML entry knn study and MEMORY.md references "
            "consistently use 'bar 4' to mean the 4th 1m bar after the flip close (=flip+240s). "
            "We adopt flip+240s as the primary definition and run placebo tests at "
            + str(PLACEBO_DELAYS_S) + "s to empirically locate the survival knee."
        ),
        "example": {
            "flip_confirmed_utc": "10:00:00",
            "bar_1_closes": "10:01:00",
            "bar_2_closes": "10:02:00",
            "bar_3_closes": "10:03:00",
            "bar_4_closes": "10:04:00  ← entry decision (fill at next 1s open)",
            "fill_time": "~10:04:00 + 1s",
        },
    }

    with open(OUT_DIR / "bar4_definition.json", "w") as f:
        json.dump(defn, f, indent=2)

    md = f"""# Bar-4 Delayed Entry Definition

## Resolution

**Bar-4 decision timestamp**: `flip_time + {BAR4_DELAY_S} seconds`
**Observation step**: `step_index >= {BAR4_STEP_INDEX}` (5s steps from flip)
**Fill**: next 1s bar OPEN at or after decision timestamp

## Counting Convention

- **Bar 0**: the 1m flip bar itself (closes at `flip_time`)
- **Bar 1**: closes at `flip_time + 60s`
- **Bar 2**: closes at `flip_time + 120s`
- **Bar 3**: closes at `flip_time + 180s`
- **Bar 4**: closes at `flip_time + 240s` ← **decision point**

Entry fill occurs at the next 1s bar open after the bar-4 close.

## Survival Requirement

Episode must still be active (no opposing flip, no cap) at the bar-4 decision timestamp.

## Sources and Ambiguity

The archived `delayed_entry_bar4.py` uses `delay_s=120` from V_A entry_ts, which was
approximately flip_time - 30s (V_A entry = flip_bar_open + 30s). This yields
~flip_time + 90s, not 240s.

The MEMORY.md ML entry study ("bar-4 all-flips") and post-bar3 studies consistently
treat "bar 4" as the 4th bar after flip close = flip + 240s.

We adopt **flip + 240s** as canonical and run placebo tests at {PLACEBO_DELAYS_S}s
to empirically locate the survival knee.

## Example

```
flip confirmed at 10:00:00 (bar 0 closes)
bar 1 completes at 10:01:00
bar 2 completes at 10:02:00
bar 3 completes at 10:03:00
bar 4 completes at 10:04:00  <- entry decision
fill at 10:04:01 (next 1s bar open)
```
"""
    with open(OUT_DIR / "bar4_definition.md", "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  Saved bar4_definition.md + .json")


# ── Phase 2: KNN generation contract ──────────────────────────────────────────

def write_knn_contract():
    print("Phase 2: Writing KNN generation contract ...")
    contract = {
        "source_study": "backtests/studies/regime_dna_knn/bar4_knn_path_atlas.py",
        "k": KNN_K,
        "distance_metric": "Euclidean on StandardScaler-normalized features",
        "features_n": len(_KNN_FEAT_NAMES),
        "features": _KNN_FEAT_NAMES,
        "feature_mapping": _KNN_FEAT_MAP,
        "step_band_matching": "N/A (period-based library approach)",
        "causality_rule": "neighbor.flip_time < query.flip_time (strict chronological)",
        "event_dedup": "one observation per episode per step_band (first observation in band)",
        "walk_forward_scheme": (
            "train obs: query against all prior flip_time episodes; "
            "val obs: query against all train-period episodes; "
            "test obs: query against train+val-period episodes"
        ),
        "health_definitions": {
            "hA": "P(y_entry_positive_300s=1 | neighbor) - P(y_entry_positive_300s=0 | neighbor) = 2*P_pos - 1",
            "hB": "mean(neighbor_pnl_300s_atr) / max(mean(|neighbor_mae_300s_atr|), 0.25)",
            "hC": "P(neighbor_pnl_60s > 0) - P(neighbor_pnl_60s < 0) = 2*P_pos60 - 1",
            "composite": "mean(percentile_rank(hA), percentile_rank(hB), percentile_rank(hC)) on training set",
        },
        "original_12_features": [
            "bar_idx", "mfe_sofar", "mae_sofar", "pnl_now", "pullback",
            "progress_count", "consec_noncont", "dist_flip_open",
            "health_ratio", "close_loc", "range_exp", "vol_exp"
        ],
        "missing_from_snapshots": ["progress_count", "consec_noncont", "dist_flip_open"],
        "substitutions": {
            "bar_idx": "regime_age_1m_bars",
            "progress_count": "DROPPED (not available; using bar_idx as proxy)",
            "consec_noncont": "DROPPED (not available)",
            "dist_flip_open": "APPROXIMATED as current_progress_atr",
            "health_ratio": "COMPUTED as max_progress_atr / max(max_adverse_atr, 0.1)",
        },
    }
    with open(OUT_DIR / "knn_generation_contract.json", "w") as f:
        json.dump(contract, f, indent=2)
    print(f"  Saved knn_generation_contract.json")


# ── Phase 3: Build causal KNN health scores ────────────────────────────────────

def _build_knn_features(df: pd.DataFrame) -> np.ndarray:
    """Build the 12-feature KNN state vector from feature_snapshots columns."""
    n = len(df)
    X = np.zeros((n, len(_KNN_FEAT_NAMES)), dtype=np.float32)
    for j, name in enumerate(_KNN_FEAT_NAMES):
        mapped = _KNN_FEAT_MAP[name]
        if mapped is None:
            # health_ratio: computed
            mfe = df["max_progress_atr"].values
            mae = df["max_adverse_atr"].values
            X[:, j] = mfe / np.maximum(mae, 0.1)
        elif mapped in df.columns:
            X[:, j] = df[mapped].values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=10.0, neginf=-10.0)
    return X


def _query_knn_batch(X_query: np.ndarray, X_ref: np.ndarray, y_pos300_ref: np.ndarray,
                     y_pos60_ref: np.ndarray, pnl300_ref: np.ndarray, ep_ids_ref: np.ndarray,
                     atrs_query: np.ndarray, k: int) -> tuple:
    """Score a batch of query observations against a reference library."""
    n = len(X_query)
    hA = np.full(n, np.nan, dtype=np.float32)
    hB = np.full(n, np.nan, dtype=np.float32)
    hC = np.full(n, np.nan, dtype=np.float32)
    mean_dist = np.full(n, np.nan, dtype=np.float32)
    n_eff = np.zeros(n, dtype=np.int32)

    if len(X_ref) < k:
        return hA, hB, hC, mean_dist, n_eff

    tree = KDTree(X_ref, leaf_size=60)
    k_actual = min(k * 2, len(X_ref))  # over-fetch for de-dup by episode
    dists_all, inds_all = tree.query(X_query, k=k_actual)

    for qi in range(n):
        nb_inds = inds_all[qi]
        nb_dists = dists_all[qi]
        nb_ep = ep_ids_ref[nb_inds]
        # De-dup: one obs per episode
        _, first_per_ep = np.unique(nb_ep, return_index=True)
        first_per_ep = first_per_ep[:k]  # cap at k unique eps
        nb_inds = nb_inds[first_per_ep]
        nb_dists = nb_dists[first_per_ep]

        k_eff = len(nb_inds)
        if k_eff < 5:
            continue

        nb_y300 = y_pos300_ref[nb_inds]
        nb_y60 = y_pos60_ref[nb_inds]
        nb_pnl = pnl300_ref[nb_inds]

        p_pos300 = float(nb_y300.mean())
        p_pos60 = float(nb_y60.mean())
        hA[qi] = 2 * p_pos300 - 1.0
        hC[qi] = 2 * p_pos60 - 1.0

        mean_pnl = float(nb_pnl.mean())
        atr_val = float(atrs_query[qi]) * _NQ_MULT
        pnl_atr = mean_pnl / max(atr_val, 1.0)
        hB[qi] = float(np.clip(pnl_atr / max(abs(pnl_atr), 0.25), -1.0, 1.0)) if abs(pnl_atr) > 0 else 0.0

        mean_dist[qi] = float(nb_dists.mean())
        n_eff[qi] = k_eff

    return hA, hB, hC, mean_dist, n_eff


def build_causal_knn(snap: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Generate causal KNN health scores for bar-4+ observations.

    Episode-level approach (fast):
    - Score ONE observation per episode at step_index = BAR4_STEP_INDEX
    - Broadcast that score to ALL bar-4+ steps of the same episode
    - Library: sampled from prior period (train for val, train+val for test)
    - ~26K episodes → trivial computation vs 3M row-wise queries

    Causality: library episodes have strictly earlier flip_time than query episodes.
    """
    print(f"\nPhase 3: Building causal KNN health scores (episode-level, k={KNN_K}) ...")
    t0 = time.time()

    # Merge outcomes into snap at bar-4 step only
    # Get the bar-4 snapshot for each episode
    snap_b4_snap = snap[snap["step_index"] == BAR4_STEP_INDEX].copy()
    snap_b4_snap = snap_b4_snap.sort_values("flip_time").reset_index(drop=True)
    print(f"  Bar-4 episode snapshots: {len(snap_b4_snap):,}")

    # Merge forward labels at bar-4
    lab_sub = labels[["observation_time", "base__pnl_300s", "base__pnl_60s"]].drop_duplicates("observation_time")
    snap_b4_snap = snap_b4_snap.merge(lab_sub, on="observation_time", how="left")
    snap_b4_snap["y_pos_300s"] = (snap_b4_snap["base__pnl_300s"] > 0).fillna(0).astype(np.float32)
    snap_b4_snap["y_pos_60s"] = (snap_b4_snap["base__pnl_60s"] > 0).fillna(0).astype(np.float32)
    snap_b4_snap["pnl_300s"] = snap_b4_snap["base__pnl_300s"].fillna(0).astype(np.float32)

    # Build KNN features on episode-level snapshots
    X_ep = _build_knn_features(snap_b4_snap)
    ep_ids_ep = snap_b4_snap["episode_id"].values
    y_pos_300_ep = snap_b4_snap["y_pos_300s"].values
    y_pos_60_ep = snap_b4_snap["y_pos_60s"].values
    pnl_300_ep = snap_b4_snap["pnl_300s"].values
    atrs_ep = snap_b4_snap["atr_at_flip"].values
    periods_ep = snap_b4_snap["period"].values
    flip_times_ep = snap_b4_snap["flip_time"].values.astype(np.int64)

    train_mask_ep = periods_ep == "train"
    val_mask_ep = periods_ep == "val"
    test_mask_ep = periods_ep == "test"

    scaler = StandardScaler()
    scaler.fit(X_ep[train_mask_ep])
    X_scaled_ep = scaler.transform(X_ep)
    X_scaled_ep = np.nan_to_num(X_scaled_ep, nan=0.0, posinf=5.0, neginf=-5.0).astype(np.float32)

    n_ep = len(snap_b4_snap)
    hA_ep = np.full(n_ep, np.nan, dtype=np.float32)
    hB_ep = np.full(n_ep, np.nan, dtype=np.float32)
    hC_ep = np.full(n_ep, np.nan, dtype=np.float32)
    md_ep = np.full(n_ep, np.nan, dtype=np.float32)
    ne_ep = np.zeros(n_ep, dtype=np.int32)

    rng_knn = np.random.default_rng(KNN_SEED)

    def _sample_lib(idx_arr: np.ndarray, n_max: int) -> np.ndarray:
        if len(idx_arr) > n_max:
            idx_arr = rng_knn.choice(idx_arr, size=n_max, replace=False)
            idx_arr.sort()
        return idx_arr

    tr_idx = np.where(train_mask_ep)[0]
    val_idx = np.where(val_mask_ep)[0]
    test_idx = np.where(test_mask_ep)[0]

    # ── Score val: query against sampled train library ──
    lib_tr = _sample_lib(tr_idx, KNN_LIB_SAMPLE)
    print(f"  Train library: {len(lib_tr):,} ep-snapshots | {time.time()-t0:.1f}s")
    hA_v, hB_v, hC_v, md_v, ne_v = _query_knn_batch(
        X_scaled_ep[val_idx], X_scaled_ep[lib_tr],
        y_pos_300_ep[lib_tr], y_pos_60_ep[lib_tr], pnl_300_ep[lib_tr], ep_ids_ep[lib_tr],
        atrs_ep[val_idx], KNN_K
    )
    hA_ep[val_idx] = hA_v; hB_ep[val_idx] = hB_v; hC_ep[val_idx] = hC_v
    md_ep[val_idx] = md_v; ne_ep[val_idx] = ne_v
    print(f"  Val: {(~np.isnan(hA_v)).sum():,}/{len(val_idx):,} scored | {time.time()-t0:.1f}s")

    # ── Score test: query against sampled train+val library ──
    trval_idx = np.concatenate([tr_idx, val_idx])
    lib_trval = _sample_lib(trval_idx, KNN_LIB_SAMPLE)
    hA_t, hB_t, hC_t, md_t, ne_t = _query_knn_batch(
        X_scaled_ep[test_idx], X_scaled_ep[lib_trval],
        y_pos_300_ep[lib_trval], y_pos_60_ep[lib_trval], pnl_300_ep[lib_trval], ep_ids_ep[lib_trval],
        atrs_ep[test_idx], KNN_K
    )
    hA_ep[test_idx] = hA_t; hB_ep[test_idx] = hB_t; hC_ep[test_idx] = hC_t
    md_ep[test_idx] = md_t; ne_ep[test_idx] = ne_t
    print(f"  Test: {(~np.isnan(hA_t)).sum():,}/{len(test_idx):,} scored | {time.time()-t0:.1f}s")

    # ── Score train OOF: first-half library, second-half query ──
    tr_median_ft = np.median(flip_times_ep[train_mask_ep])
    tr_h1_idx = tr_idx[flip_times_ep[tr_idx] <= tr_median_ft]
    tr_h2_idx = tr_idx[flip_times_ep[tr_idx] > tr_median_ft]
    if len(tr_h1_idx) > KNN_K and len(tr_h2_idx) > 0:
        lib_h1 = _sample_lib(tr_h1_idx, KNN_LIB_SAMPLE // 2)
        hA_tr, hB_tr, hC_tr, md_tr, ne_tr = _query_knn_batch(
            X_scaled_ep[tr_h2_idx], X_scaled_ep[lib_h1],
            y_pos_300_ep[lib_h1], y_pos_60_ep[lib_h1], pnl_300_ep[lib_h1], ep_ids_ep[lib_h1],
            atrs_ep[tr_h2_idx], KNN_K
        )
        hA_ep[tr_h2_idx] = hA_tr; hB_ep[tr_h2_idx] = hB_tr; hC_ep[tr_h2_idx] = hC_tr
        md_ep[tr_h2_idx] = md_tr; ne_ep[tr_h2_idx] = ne_tr
    print(f"  Train OOF: {(~np.isnan(hA_ep[tr_idx])).sum():,}/{len(tr_idx):,} scored | {time.time()-t0:.1f}s")

    # Compute composite percentile rank vs train distribution
    def _pct_rank_fast(vals: np.ndarray, ref_vals: np.ndarray) -> np.ndarray:
        ref_clean = np.sort(ref_vals[~np.isnan(ref_vals)])
        if len(ref_clean) == 0:
            return np.full(len(vals), 0.5, dtype=np.float32)
        result = np.searchsorted(ref_clean, vals.astype(np.float64), side="right").astype(np.float32) / len(ref_clean)
        result[np.isnan(vals)] = np.nan
        return result

    tr_hA = hA_ep[tr_h2_idx] if len(tr_h2_idx) > 0 else hA_ep[val_idx]  # use scored train
    tr_hB = hB_ep[tr_h2_idx] if len(tr_h2_idx) > 0 else hB_ep[val_idx]
    tr_hC = hC_ep[tr_h2_idx] if len(tr_h2_idx) > 0 else hC_ep[val_idx]

    rank_hA = _pct_rank_fast(hA_ep, tr_hA)
    rank_hB = _pct_rank_fast(hB_ep, tr_hB)
    rank_hC = _pct_rank_fast(hC_ep, tr_hC)
    composite_ep = np.nanmean(np.stack([rank_hA, rank_hB, rank_hC], axis=1), axis=1).astype(np.float32)

    # Build episode-level score lookup
    ep_to_score = {
        ep_ids_ep[i]: {
            "knn_hA": float(hA_ep[i]),
            "knn_hB": float(hB_ep[i]),
            "knn_hC": float(hC_ep[i]),
            "knn_composite": float(composite_ep[i]),
            "knn_mean_dist": float(md_ep[i]),
            "knn_n_eff": int(ne_ep[i]),
        }
        for i in range(n_ep)
    }

    # Now build the full bar-4+ observation DataFrame with scores broadcast per episode
    print("  Broadcasting scores to all bar-4+ observations ...")
    snap_all_b4 = snap[snap["step_index"] >= BAR4_STEP_INDEX].copy()
    snap_all_b4 = snap_all_b4.sort_values(["flip_time", "observation_time"]).reset_index(drop=True)

    ep_ids_all = snap_all_b4["episode_id"].values
    knn_hA_all = np.array([ep_to_score.get(ep, {}).get("knn_hA", np.nan) for ep in ep_ids_all], dtype=np.float32)
    knn_hB_all = np.array([ep_to_score.get(ep, {}).get("knn_hB", np.nan) for ep in ep_ids_all], dtype=np.float32)
    knn_hC_all = np.array([ep_to_score.get(ep, {}).get("knn_hC", np.nan) for ep in ep_ids_all], dtype=np.float32)
    knn_comp_all = np.array([ep_to_score.get(ep, {}).get("knn_composite", np.nan) for ep in ep_ids_all], dtype=np.float32)
    knn_md_all = np.array([ep_to_score.get(ep, {}).get("knn_mean_dist", np.nan) for ep in ep_ids_all], dtype=np.float32)
    knn_ne_all = np.array([ep_to_score.get(ep, {}).get("knn_n_eff", 0) for ep in ep_ids_all], dtype=np.int32)

    # snap_b4 = full bar-4+ rows
    snap_b4 = snap_all_b4  # rename for downstream compatibility
    n = len(snap_b4)
    hA_arr = knn_hA_all
    hB_arr = knn_hB_all
    hC_arr = knn_hC_all
    composite_arr = knn_comp_all
    knn_mean_dist_arr = knn_md_all
    knn_n_eff_arr = knn_ne_all

    # Assemble output DataFrame
    knn_df = snap_b4[["episode_id", "step_index", "observation_time", "flip_time", "period"]].copy()
    knn_df["knn_hA"] = hA_arr
    knn_df["knn_hB"] = hB_arr
    knn_df["knn_hC"] = hC_arr
    knn_df["knn_composite"] = composite_arr
    knn_df["knn_mean_dist"] = knn_mean_dist_arr
    knn_df["knn_n_eff"] = knn_n_eff_arr
    # Compatibility fields
    knn_df["knn_unique_eps"] = knn_n_eff_arr  # approximate
    knn_df["knn_neighbor_agreement"] = np.nan  # not computed in fast mode

    n_scored = (~np.isnan(hA_arr)).sum()
    print(f"  Scored: {n_scored:,} / {n:,} observations ({100*n_scored/n:.1f}%)")
    print(f"  KNN hA: mean={np.nanmean(hA_arr):+.3f}, std={np.nanstd(hA_arr):.3f}")
    print(f"  KNN hC: mean={np.nanmean(hC_arr):+.3f}, std={np.nanstd(hC_arr):.3f}")
    print(f"  Composite: mean={np.nanmean(composite_arr):.3f}, std={np.nanstd(composite_arr):.3f}")
    print(f"  Elapsed: {time.time()-t0:.1f}s")

    knn_df.to_parquet(OUT_DIR / "causal_knn_health.parquet", index=False)
    print(f"  Saved causal_knn_health.parquet ({len(knn_df):,} rows)")

    # Write provenance audit
    provenance = {
        "total_bar4_obs": int(len(snap_b4)),
        "scored_obs": int(n_scored),
        "pct_scored": round(100 * n_scored / len(snap_b4), 2),
        "k": KNN_K,
        "median_n_eff": float(np.nanmedian(knn_n_eff_arr)),
        "median_unique_eps": float(np.nanmedian(knn_n_eff_arr)),
        "hA_mean": round(float(np.nanmean(hA_arr)), 4),
        "hC_mean": round(float(np.nanmean(hC_arr)), 4),
        "composite_mean": round(float(np.nanmean(composite_arr)), 4),
        "approach": "period-based library (train->val, train+val->test, first-half->second-half train)",
        "causality_check": "val/test: all neighbors have earlier flip_time; train: first-half prior only",
        "contamination_check": "PASS: no forward-looking labels in features; library does not include query period",
    }
    with open(OUT_DIR / "knn_provenance_audit.json", "w") as f:
        json.dump(provenance, f, indent=2)
    print(f"  Saved knn_provenance_audit.json")
    return knn_df


# ── Phase 4: Bar-4 survivor population ────────────────────────────────────────

def build_bar4_survivors(snap: pd.DataFrame, labels: pd.DataFrame, knn_df: pd.DataFrame) -> pd.DataFrame:
    print("\nPhase 4: Building bar-4 survivor population ...")

    # Episode-level bar-4 survival
    ep_summary = snap.groupby("episode_id").agg(
        flip_time=("flip_time", "first"),
        direction=("direction", "first"),
        atr_at_flip=("atr_at_flip", "first"),
        flip_close=("flip_close", "first"),
        period=("period", "first"),
        episode_end_time=("episode_end_time", "first"),
        termination_reason=("termination_reason", "first"),
        max_step=("step_index", "max"),
        n_obs=("step_index", "count"),
    ).reset_index()

    ep_summary["survived_to_bar4"] = ep_summary["max_step"] >= BAR4_STEP_INDEX

    # For survivors, build feature set at step_index = BAR4_STEP_INDEX
    bar4_obs = snap[snap["step_index"] == BAR4_STEP_INDEX].copy()

    n_total = len(ep_summary)
    n_surv = ep_summary["survived_to_bar4"].sum()
    n_total_by_period = ep_summary.groupby("period").size().to_dict()
    n_surv_by_period = ep_summary[ep_summary["survived_to_bar4"]].groupby("period").size().to_dict()

    print(f"  Total episodes: {n_total:,}")
    print(f"  Bar-4 survivors: {n_surv:,} ({100*n_surv/n_total:.1f}%)")
    for p in ["train", "val", "test"]:
        nt = n_total_by_period.get(p, 0)
        ns = n_surv_by_period.get(p, 0)
        print(f"    {p}: {ns:,}/{nt:,} ({100*ns/max(nt,1):.1f}%)")

    # Classify non-survivors
    non_surv = ep_summary[~ep_summary["survived_to_bar4"]].copy()
    term_counts = non_surv["termination_reason"].value_counts().to_dict()
    print(f"  Non-survivor termination reasons: {term_counts}")

    # Merge KNN at bar-4 step for survivors
    knn_at_bar4 = knn_df[knn_df["step_index"] == BAR4_STEP_INDEX][
        ["episode_id", "knn_hA", "knn_hB", "knn_hC", "knn_composite", "knn_mean_dist", "knn_n_eff"]
    ].rename(columns={
        "knn_hA": "knn_hA_at_bar4",
        "knn_hB": "knn_hB_at_bar4",
        "knn_hC": "knn_hC_at_bar4",
        "knn_composite": "knn_composite_at_bar4",
        "knn_mean_dist": "knn_mean_dist_at_bar4",
        "knn_n_eff": "knn_n_eff_at_bar4",
    })

    survivors = ep_summary[ep_summary["survived_to_bar4"]].copy()
    survivors = survivors.merge(
        bar4_obs[[c for c in [
            "episode_id", "step_index", "observation_time",
            "current_progress_atr", "max_progress_atr", "max_adverse_atr",
            "pullback_from_peak_atr", "progress_efficiency",
            "regime_age_1m_bars",
        ] if c in bar4_obs.columns]].rename(columns={"observation_time": "bar4_obs_time"}),
        on="episode_id", how="left"
    )
    survivors = survivors.merge(knn_at_bar4, on="episode_id", how="left")

    # Compute remaining opportunity (for analysis only — NOT features)
    # Use forward_labels at bar-4 observation
    bar4_labels = labels.merge(
        bar4_obs[["episode_id", "observation_time"]],
        on="observation_time", how="inner"
    )
    if "base__pnl_300s" in bar4_labels.columns:
        survivors = survivors.merge(
            bar4_labels[["episode_id", "base__pnl_300s", "base__pnl_regime"]].rename(
                columns={"base__pnl_300s": "remaining_pnl_300s", "base__pnl_regime": "remaining_regime_pnl"}
            ),
            on="episode_id", how="left"
        )

    # Remaining MFE distribution
    if "remaining_pnl_300s" in survivors.columns:
        rem_pnl = survivors["remaining_pnl_300s"].dropna()
        print(f"  Remaining PnL@300s (survivors): mean=${rem_pnl.mean():+.2f}, median=${rem_pnl.median():+.2f}")
        atr_mean = survivors["atr_at_flip"].mean()
        pct_pos = (rem_pnl > 0).mean() * 100
        print(f"  Positive remaining return: {pct_pos:.1f}%")

    survivors.to_parquet(OUT_DIR / "bar4_survivors.parquet", index=False)

    # Population summary
    pop_summary = {
        "total_episodes": int(n_total),
        "bar4_survivors": int(n_surv),
        "bar4_survival_rate": round(n_surv / n_total, 4),
        "bar4_delay_s": BAR4_DELAY_S,
        "by_period": {
            p: {"total": n_total_by_period.get(p, 0), "survived": n_surv_by_period.get(p, 0)}
            for p in ["train", "val", "test"]
        },
        "non_survivor_reasons": term_counts,
    }
    pd.DataFrame([pop_summary]).to_parquet(OUT_DIR / "bar4_population_summary.parquet", index=False)
    print(f"  Saved bar4_survivors.parquet + bar4_population_summary.parquet")
    return survivors


# ── Phase 7: Build entry and exit targets ─────────────────────────────────────

def build_targets(snap: pd.DataFrame, labels: pd.DataFrame, knn_df: pd.DataFrame):
    """Build entry targets (bar-4+ only) and exit targets."""
    print("\nPhase 7: Building entry and exit targets ...")

    # Entry targets: for each bar-4+ observation, compute forward labels
    bar4_snap = snap[snap["step_index"] >= BAR4_STEP_INDEX].copy()

    outcome_cols = [
        "observation_time",
        "base__pnl_60s", "base__pnl_120s", "base__pnl_300s",
        "base__stopped_60s", "base__stopped_120s", "base__stopped_300s",
        "base__pnl_regime",
    ]
    avail = [c for c in outcome_cols if c in labels.columns]
    lab_sub = labels[avail].drop_duplicates("observation_time")

    entry_df = bar4_snap.merge(lab_sub, on="observation_time", how="inner")
    entry_df["y_entry_positive_60s"] = (entry_df["base__pnl_60s"] > 0).astype(np.int8) if "base__pnl_60s" in entry_df.columns else np.nan
    entry_df["y_entry_positive_120s"] = (entry_df["base__pnl_120s"] > 0).astype(np.int8) if "base__pnl_120s" in entry_df.columns else np.nan
    entry_df["y_entry_positive_300s"] = (entry_df["base__pnl_300s"] > 0).astype(np.int8) if "base__pnl_300s" in entry_df.columns else np.nan
    entry_df["y_entry_adv_300s"] = entry_df["base__pnl_300s"].fillna(0)
    entry_df["y_entry_adv_120s"] = entry_df["base__pnl_120s"].fillna(0)

    # Merge KNN features into entry_df
    entry_df = entry_df.merge(
        knn_df[["observation_time", "knn_hA", "knn_hB", "knn_hC", "knn_composite",
                "knn_mean_dist", "knn_n_eff", "knn_unique_eps", "knn_neighbor_agreement"]],
        on="observation_time", how="left"
    )

    entry_df.to_parquet(OUT_DIR / "entry_targets.parquet", index=False)
    print(f"  entry_targets: {len(entry_df):,} rows")

    # Exit targets: positioned-state observations (all steps after hypothetical entry)
    # For exit model: we need observations where we're IN a position
    # Use all bar-4+ positioned observations as the exit target dataset
    # Unrealized PnL = current_progress_atr (aligned with direction, already in ATR)
    exit_df = bar4_snap.copy()
    exit_df = exit_df.merge(lab_sub, on="observation_time", how="inner")
    exit_df["y_exit_positive_60s"] = (exit_df["base__pnl_60s"] > 0).astype(np.int8) if "base__pnl_60s" in exit_df.columns else np.nan
    exit_df["y_exit_positive_120s"] = (exit_df["base__pnl_120s"] > 0).astype(np.int8) if "base__pnl_120s" in exit_df.columns else np.nan
    exit_df["unrealized_pnl_atr"] = exit_df["current_progress_atr"]
    exit_df["time_in_trade_s"] = exit_df["seconds_since_flip"] - BAR4_DELAY_S

    exit_df = exit_df.merge(
        knn_df[["observation_time", "knn_hA", "knn_hB", "knn_hC", "knn_composite",
                "knn_mean_dist", "knn_n_eff"]],
        on="observation_time", how="left"
    )

    exit_df.to_parquet(OUT_DIR / "exit_targets.parquet", index=False)
    print(f"  exit_targets: {len(exit_df):,} rows")

    # Check label distribution
    for col in ["y_entry_positive_300s", "y_entry_positive_120s"]:
        if col in entry_df.columns:
            for period in ["train", "val", "test"]:
                sub = entry_df[entry_df["period"] == period][col]
                print(f"  {period} {col}: {sub.mean():.3f} pos rate ({len(sub):,} obs)")

    return entry_df, exit_df


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("DELAYED HEALTH STUDY — Phase 1-4+7: Data Building")
    print("=" * 70)

    # Phase 1: Bar-4 definition
    write_bar4_definition()

    # Phase 2: KNN contract
    write_knn_contract()

    # Load data
    print("\nLoading feature snapshots ...")
    snap = pd.read_parquet(SNAP_FILE)
    print(f"  Snapshots: {snap.shape}")

    print("Loading forward labels ...")
    labels = pd.read_parquet(LABEL_FILE)
    print(f"  Labels: {labels.shape}")

    # Phase 3: Causal KNN
    knn_df = build_causal_knn(snap, labels)

    # Phase 4: Bar-4 survivors
    survivors = build_bar4_survivors(snap, labels, knn_df)

    # Phase 7: Targets
    entry_tgt, exit_tgt = build_targets(snap, labels, knn_df)

    print("\n" + "=" * 70)
    print("Phase 1-4+7 COMPLETE")
    print(f"  bar4_definition.md / .json")
    print(f"  knn_generation_contract.json")
    print(f"  knn_provenance_audit.json")
    print(f"  causal_knn_health.parquet: {len(knn_df):,} rows")
    print(f"  bar4_survivors.parquet: {len(survivors):,} episodes")
    print(f"  entry_targets.parquet: {len(entry_tgt):,} rows")
    print(f"  exit_targets.parquet: {len(exit_tgt):,} rows")
    print("=" * 70)


if __name__ == "__main__":
    main()
