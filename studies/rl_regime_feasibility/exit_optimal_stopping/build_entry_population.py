"""
Phase 0: Build entry populations P1, P2, P3.

P1 = immediate entry at flip (step_index == 0)
P2 = fixed 180-second delayed entry (first obs with seconds_since_flip >= 180)
P3 = 180s delayed + LightGBM-gated entry (trained out-of-fold on 2024)

Period splits (this study):
  train:  2024-01-01 – 2024-12-31   (all of 2024)
  val:    2025-01-01 – 2025-02-28
  test:   2025-03-01 – 2025-05-31
"""

from pathlib import Path
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.model_selection import StratifiedKFold

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path("studies/rl_regime_feasibility")
REPAIR_DIR = BASE_DIR / "delayed_entry_repair/results"
OUT_DIR    = BASE_DIR / "exit_optimal_stopping/results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NQ_MULT    = 20.0   # $/pt
COMMISSION = 5.0    # $5 RT
DELAY_P2   = 180    # seconds

# ── Period cuts (UTC ns) ──────────────────────────────────────────────────────
def _ns(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value)

CUTS = {
    "train": (_ns("2024-01-01"), _ns("2025-01-01")),
    "val":   (_ns("2025-01-01"), _ns("2025-03-01")),
    "test":  (_ns("2025-03-01"), _ns("2025-06-01")),
}

def assign_period(flip_time_ns: pd.Series) -> pd.Series:
    p = pd.Series("unknown", index=flip_time_ns.index)
    for name, (lo, hi) in CUTS.items():
        p[(flip_time_ns >= lo) & (flip_time_ns < hi)] = name
    return p

# ── Baseline feature set for P3 entry model ──────────────────────────────────
P3_ENTRY_FEATS = [
    "current_progress_atr", "max_progress_atr", "max_adverse_atr",
    "pullback_from_peak_atr", "seconds_since_peak", "progress_efficiency",
    "aligned_return_5s_atr", "aligned_return_15s_atr", "aligned_return_30s_atr",
    "aligned_return_60s_atr", "realized_vol_60s_atr", "range_5s_atr",
    "volume_5s_zscore", "volume_30s_vs_5m",
    "bollinger_width_percentile_1m", "bollinger_keltner_width_ratio_1m",
    "kalman_velocity_atr_per_s", "kalman_acceleration_atr_per_s2",
    "kalman_innovation_zscore", "ema3_ema9_spread_30s_atr",
    "regime_5s_aligned", "regime_30s_aligned", "regime_5m_aligned",
    "regime_age_1m_bars", "adx14_1m", "position_in_trailing_1m_range",
    "minutes_since_rth_open",
]


def build_populations(sf: pd.DataFrame) -> dict:
    """Return dict of entry DataFrames for P1, P2, P3."""
    populations = {}

    # ── P1: immediate entry at step_index == 0 ───────────────────────────────
    p1 = (sf[sf["step_index"] == 0]
          .copy()
          .drop_duplicates("episode_id"))
    p1 = _add_entry_fields(p1, delay_s=0.0)
    populations["P1"] = p1
    print(f"  P1 (immediate): {len(p1):,} entries, {p1['period'].value_counts().sort_index().to_dict()}")

    # ── P2: fixed 180s delayed entry ─────────────────────────────────────────
    eligible = sf[sf["seconds_since_flip"] >= DELAY_P2].copy()
    p2 = (eligible
          .sort_values(["episode_id", "seconds_since_flip"])
          .groupby("episode_id", sort=False)
          .first()
          .reset_index())
    p2 = _add_entry_fields(p2, delay_s=DELAY_P2)
    populations["P2"] = p2
    print(f"  P2 (180s fixed): {len(p2):,} entries, {p2['period'].value_counts().sort_index().to_dict()}")

    # ── P3: 180s + ML gating ──────────────────────────────────────────────────
    p3 = _build_p3(p2)
    populations["P3"] = p3
    print(f"  P3 (180s + ML):  {len(p3[p3['ml_enter']==1]):,} entries taken (out of {len(p3):,} eligible)")

    return populations


def _add_entry_fields(df: pd.DataFrame, delay_s: float) -> pd.DataFrame:
    df = df.copy()
    df["entry_delay_s"]        = delay_s
    df["entry_progress_atr"]   = df["current_progress_atr"]
    # entry_px and stop_px already present from forward_labels in study_features
    return df


def _build_p3(p2: pd.DataFrame) -> pd.DataFrame:
    """Train LightGBM entry filter on 2024 out-of-fold, freeze on val/test."""
    p3 = p2.copy()
    p3["ml_enter"] = 0

    # Binary target: base__pnl_300s > 0
    p3["target"] = (p3["base__pnl_300s"] > 0).astype(int)

    feats = [f for f in P3_ENTRY_FEATS if f in p3.columns]
    X = p3[feats].fillna(0).values
    y = p3["target"].values

    train_mask = p3["period"] == "train"
    val_test_mask = p3["period"].isin(["val", "test"])

    # Out-of-fold on train, then train full model on all train → apply to val/test
    oof_proba = np.zeros(len(p3))
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    train_idx = np.where(train_mask.values)[0]
    X_tr = X[train_idx]; y_tr = y[train_idx]

    for fold_tr, fold_val in skf.split(X_tr, y_tr):
        mdl = LGBMClassifier(n_estimators=200, learning_rate=0.05,
                             max_depth=4, min_child_samples=50,
                             num_leaves=15, reg_lambda=5.0,
                             random_state=42, n_jobs=4, verbose=-1)
        mdl.fit(X_tr[fold_tr], y_tr[fold_tr])
        oof_proba[train_idx[fold_val]] = mdl.predict_proba(X_tr[fold_val])[:, 1]

    # Full train model for val/test inference
    full_mdl = LGBMClassifier(n_estimators=200, learning_rate=0.05,
                              max_depth=4, min_child_samples=50,
                              num_leaves=15, reg_lambda=5.0,
                              random_state=42, n_jobs=4, verbose=-1)
    full_mdl.fit(X[train_mask], y[train_mask])
    oof_proba[val_test_mask.values] = full_mdl.predict_proba(X[val_test_mask])[:, 1]
    p3["ml_score"] = oof_proba

    # Tune threshold on val: maximize EV per eligible episode
    val_mask = p3["period"] == "val"
    if val_mask.sum() > 0:
        best_thr, best_ev = 0.5, -np.inf
        for thr in np.arange(0.45, 0.70, 0.025):
            taken = p3.loc[val_mask & (p3["ml_score"] >= thr)]
            if len(taken) < 20:
                continue
            total_ev = taken["base__pnl_300s"].mean() * (len(taken) / val_mask.sum())
            if total_ev > best_ev:
                best_ev, best_thr = total_ev, thr
        p3["ml_threshold"] = best_thr
        p3["ml_enter"] = (p3["ml_score"] >= best_thr).astype(int)
        print(f"    P3 threshold={best_thr:.3f}, val EV/eligible={best_ev:.2f}")
    else:
        p3["ml_threshold"] = 0.5
        p3["ml_enter"] = (p3["ml_score"] >= 0.5).astype(int)

    # OOF AUC
    from sklearn.metrics import roc_auc_score
    try:
        tr_auc = roc_auc_score(y[train_mask], oof_proba[train_mask.values])
        vt_auc = roc_auc_score(y[val_test_mask], oof_proba[val_test_mask.values])
        print(f"    P3 OOF AUC: train={tr_auc:.4f}, val+test={vt_auc:.4f}")
    except Exception:
        pass

    return p3


def compute_matched_survivor(pop_p1: pd.DataFrame, pop_p2: pd.DataFrame) -> pd.DataFrame:
    """
    Decompose P2 improvement over P1 into:
      - selection_benefit: loss avoided by skipping episodes that end before delay
      - timing_benefit: delta EV among episodes that survive to delay
    """
    rows = []
    for period in ["val", "test"]:
        p1 = pop_p1[pop_p1["period"] == period]
        p2 = pop_p2[pop_p2["period"] == period]

        n_total = len(p1)
        survived = set(p2["episode_id"])
        p1_surv = p1[p1["episode_id"].isin(survived)]
        p1_died = p1[~p1["episode_id"].isin(survived)]
        p2_surv = p2[p2["episode_id"].isin(p1["episode_id"])]

        for policy, pnl_col in [("fixed_300s", "base__pnl_300s"),
                                 ("regime_exit", "base__pnl_regime")]:
            if pnl_col not in p1.columns:
                continue
            ev_imm    = p1[pnl_col].mean()
            ev_del    = p2[pnl_col].mean() * (len(p2) / n_total)  # eligible basis
            ev_surv_imm = p1_surv[pnl_col].mean() if len(p1_surv) else np.nan
            ev_surv_del = p2_surv[pnl_col].mean() if len(p2_surv) else np.nan
            ev_died_imm = p1_died[pnl_col].mean() if len(p1_died) else 0.0

            frac_survived = len(p2) / n_total
            selection_benefit = -ev_died_imm * (1 - frac_survived) * n_total / n_total
            timing_benefit    = (ev_surv_del - ev_surv_imm) if not (np.isnan(ev_surv_del) or np.isnan(ev_surv_imm)) else np.nan

            rows.append({
                "period": period, "policy": policy,
                "n_total": n_total, "n_survived": len(p2), "frac_survived": frac_survived,
                "ev_immediate": ev_imm, "ev_delayed": ev_del,
                "ev_survived_immediate": ev_surv_imm, "ev_survived_delayed": ev_surv_del,
                "selection_benefit": selection_benefit, "timing_benefit": timing_benefit,
                "total_improvement": ev_del - ev_imm,
            })
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("Phase 0: Build Entry Populations")
    print("=" * 70)

    print("\nLoading study_features.parquet ...")
    sf = pd.read_parquet(REPAIR_DIR / "study_features.parquet")
    print(f"  Loaded: {sf.shape}")

    # Re-assign periods per this study's splits
    sf["period"] = assign_period(sf["flip_time"])
    print(f"  Period distribution: {sf.groupby('period')['episode_id'].nunique().to_dict()}")

    print("\nBuilding populations ...")
    pops = build_populations(sf)

    # Save each population
    all_entries = []
    metrics_rows = []
    for pop_name, pop_df in pops.items():
        if pop_name == "P3":
            # Only save the actually-entered subset
            taken = pop_df[pop_df["ml_enter"] == 1].copy()
        else:
            taken = pop_df.copy()

        out_cols = [
            "episode_id", "flip_time", "flip_close", "atr_at_flip", "direction",
            "episode_end_time", "termination_reason", "period",
            "entry_delay_s", "entry_progress_atr", "entry_px", "stop_px",
            "seconds_since_flip", "step_index", "observation_time",
            "base__pnl_300s", "base__pnl_regime",
            "base_plus_1t__pnl_300s", "base_plus_1t__pnl_regime",
            "base_plus_2t__pnl_300s", "base_plus_2t__pnl_regime",
        ]
        if pop_name == "P3":
            out_cols += ["ml_score", "ml_threshold", "ml_enter"]
        out_cols = [c for c in out_cols if c in taken.columns]

        taken_out = taken[out_cols].copy()
        taken_out["population"] = pop_name
        all_entries.append(taken_out)

        for period in ["train", "val", "test"]:
            sub = taken[taken["period"] == period]
            if len(sub) == 0:
                continue
            metrics_rows.append({
                "population": pop_name, "period": period,
                "n_episodes_eligible": (pop_df["period"] == period).sum(),
                "n_traded": len(sub),
                "ev_per_eligible": sub["base__pnl_300s"].mean() * len(sub) / (pop_df["period"] == period).sum(),
                "ev_per_trade": sub["base__pnl_300s"].mean(),
                "wr_300s": (sub["base__pnl_300s"] > 0).mean(),
                "ev_regime": sub["base__pnl_regime"].mean() if "base__pnl_regime" in sub.columns else np.nan,
            })

    trades_df = pd.concat(all_entries, ignore_index=True)
    trades_df.to_parquet(OUT_DIR / "entry_population_trades.parquet", index=False)
    print(f"\nSaved entry_population_trades.parquet: {trades_df.shape}")

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df.to_parquet(OUT_DIR / "entry_population_metrics.parquet", index=False)
    print("Saved entry_population_metrics.parquet")
    print(metrics_df.to_string())

    # Matched survivor analysis P1 vs P2
    print("\nMatched survivor decomposition P1 vs P2 ...")
    msdf = compute_matched_survivor(pops["P1"], pops["P2"])
    msdf.to_parquet(OUT_DIR / "matched_survivor_comparison.parquet", index=False)
    print(msdf.to_string())

    # Manifest
    manifest = {
        "populations": {
            name: {
                "n_train": int((pops[name]["period"] == "train").sum()),
                "n_val":   int((pops[name]["period"] == "val").sum()),
                "n_test":  int((pops[name]["period"] == "test").sum()),
                "delay_s": DELAY_P2 if name in ("P2", "P3") else 0,
            }
            for name in pops
        },
        "period_cuts": {k: [str(pd.Timestamp(v[0], unit='ns', tz='UTC')),
                             str(pd.Timestamp(v[1], unit='ns', tz='UTC'))]
                         for k, v in CUTS.items()},
        "commission": COMMISSION, "nq_mult": NQ_MULT,
        "stop_atr_mult": 1.5,
    }
    with open(OUT_DIR / "entry_population_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print("\nSaved entry_population_manifest.json")
    print("Phase 0 complete.")


if __name__ == "__main__":
    main()
