"""
Delayed Entry Repair -- run_policies.py  (Phases 4-7)

Design split:
  Phase 4-5  Delay sweep on val (unconditional) -> select best_delay.
             Matched cohort decomposes survival-filter vs timing benefit.
  Phase 6-7  KNN model ALWAYS at bar-4 (240s), where KNN data exists.
             Manifest assertion requires knn_hA, knn_hB, knn_hC, knn_mean_dist, knn_n_eff.
             KNN shuffle control at 240s gives a MEANINGFUL comparison.
             Long / short reported separately.
  Phase 7c   Combined test window for both unconditional and bar-4 ML variants.

Key fixes vs delayed_health:
  1. No double-merge -- KNN columns already clean in study_features.parquet.
  2. KNN model trained ONLY at 240s where KNN has real values at inference.
  3. KNN shuffle control at 240s: shuffles real KNN values, not zeros.
  4. Manifest assertion enforced on bar-4 model specifically.
  5. Uses seconds_since_flip for delay targeting, not step_index.
  6. Two test windows (2024-Q4, 2025-H1) reported separately + combined.
"""

from pathlib import Path
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import roc_auc_score

# -- Paths ----------------------------------------------------------------------
STUDY_DIR = Path("studies/rl_regime_feasibility")
OUT_DIR   = STUDY_DIR / "delayed_entry_repair/results"

# -- Delays --------------------------------------------------------------------
CANDIDATE_DELAYS = [60, 120, 180, 240]
BAR4_DELAY_S     = 240           # KNN is only computed at seconds_since_flip >= 240s

# -- Feature lists -------------------------------------------------------------
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
    "knn_hA", "knn_hB", "knn_hC",
    "knn_mean_dist", "knn_n_eff",
    "knn_unique_eps", "knn_neighbor_agreement",
]

# Required fields for manifest assertion
_REQUIRED_KNN_MANIFEST = ["knn_hA", "knn_hB", "knn_hC", "knn_mean_dist", "knn_n_eff"]

# Bar-4 model features: deduplicated (fixes the double-merge suffix bug pattern)
_BAR4_FEATS = list(dict.fromkeys(_BASELINE_FEATS + _KNN_FEATS))
assert len(_BAR4_FEATS) == len(set(_BAR4_FEATS)), "Duplicate features in bar-4 model!"

# -- LGBM config ---------------------------------------------------------------
LGBM_PARAMS = dict(
    n_estimators=400, learning_rate=0.05, num_leaves=63,
    min_child_samples=200, subsample=0.8, random_state=42,
    n_jobs=2, verbosity=-1,
)
BOOTSTRAP_N    = 2000
BOOTSTRAP_SEED = 42


# -- Helpers --------------------------------------------------------------------

def _bootstrap_ci(values: np.ndarray, n: int = BOOTSTRAP_N,
                  seed: int = BOOTSTRAP_SEED, level: float = 0.95) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = [rng.choice(values, len(values), replace=True).mean() for _ in range(n)]
    lo = (1 - level) / 2 * 100
    return float(np.percentile(means, lo)), float(np.percentile(means, 100 - lo))


def _ev_metrics(pnl_arr: np.ndarray) -> dict:
    n_total = len(pnl_arr)
    traded  = pnl_arr[pnl_arr != 0]
    n_tr    = len(traded)
    if n_tr == 0:
        return {"ev_ep": float("nan"), "ev_tr": float("nan"), "wr": float("nan"),
                "ci_lo": float("nan"), "ci_hi": float("nan"),
                "n_traded": 0, "n_total": n_total}
    ev_ep = float(pnl_arr.mean())
    ev_tr = float(traded.mean())
    wr    = float((traded > 0).mean())
    lo, hi = _bootstrap_ci(pnl_arr)
    return {"ev_ep": ev_ep, "ev_tr": ev_tr, "wr": wr,
            "ci_lo": lo, "ci_hi": hi, "n_traded": n_tr, "n_total": n_total}


def _pnl_col(policy: str, cost: str) -> str:
    return {
        ("fixed_300s",      "base"):    "base__pnl_300s",
        ("fixed_300s",      "plus_1t"): "base_plus_1t__pnl_300s",
        ("fixed_300s",      "plus_2t"): "base_plus_2t__pnl_300s",
        ("opposing_regime", "base"):    "base__pnl_regime",
        ("opposing_regime", "plus_1t"): "base_plus_1t__pnl_regime",
        ("opposing_regime", "plus_2t"): "base_plus_2t__pnl_regime",
    }[(policy, cost)]


def train_lgbm(df: pd.DataFrame, target: str, feats: list, label: str = "") -> tuple:
    avail = [c for c in feats if c in df.columns]
    assert avail, f"No features available for {label}"
    tr = df[df["period"] == "train"]
    va = df[df["period"] == "val"]
    m  = LGBMClassifier(**LGBM_PARAMS)
    m.fit(tr[avail].fillna(0), tr[target])
    auc = float(roc_auc_score(va[target], m.predict_proba(va[avail].fillna(0))[:, 1]))
    print(f"  {label}: val_AUC={auc:.4f}  n_feats={len(avail)}  n_train={len(tr):,}")
    return m, avail, auc


# -- Delay utilities ------------------------------------------------------------

def first_at_or_after(df: pd.DataFrame, delay_s: float) -> pd.DataFrame:
    """First observation per episode where seconds_since_flip >= delay_s."""
    return (
        df[df["seconds_since_flip"] >= delay_s]
        .sort_values(["episode_id", "seconds_since_flip"])
        .groupby("episode_id", sort=False).first()
        .reset_index()
    )


def first_immediate(df: pd.DataFrame) -> pd.DataFrame:
    """First observation per episode (immediate entry)."""
    return (
        df.sort_values(["episode_id", "seconds_since_flip"])
        .groupby("episode_id", sort=False).first()
        .reset_index()
    )


def _filter(df: pd.DataFrame, period_prefix: str | None,
            direction: int | None) -> pd.DataFrame:
    if period_prefix is not None:
        df = df[df["period"].str.startswith(period_prefix)]
    if direction is not None:
        df = df[df["direction"] == direction]
    return df


# -- Policy evaluation ----------------------------------------------------------

def eval_uncond(df: pd.DataFrame, delay_s: float, policy: str,
                cost: str = "base", period_prefix=None, direction=None) -> dict:
    """Unconditional delayed entry using precomputed labels."""
    src     = _filter(df, period_prefix, direction)
    all_eps = src["episode_id"].unique()
    col     = _pnl_col(policy, cost)
    delayed = first_at_or_after(src, delay_s)[["episode_id", col]].rename(columns={col: "pnl"})
    cohort  = pd.DataFrame({"episode_id": all_eps}).merge(delayed, on="episode_id", how="left")
    cohort["pnl"] = cohort["pnl"].fillna(0.0)
    m = _ev_metrics(cohort["pnl"].values)
    m.update(delay_s=delay_s, policy=policy, cost_tier=cost)
    return m


def eval_ml_gated(df: pd.DataFrame, delay_s: float, model, feats: list,
                  threshold: float, policy: str, cost: str = "base",
                  period_prefix=None, direction=None) -> dict:
    """ML-gated delayed entry using precomputed labels."""
    src     = _filter(df, period_prefix, direction)
    all_eps = src["episode_id"].unique()
    col     = _pnl_col(policy, cost)
    rows    = first_at_or_after(src, delay_s).copy()
    avail   = [c for c in feats if c in rows.columns]
    rows["prob"] = model.predict_proba(rows[avail].fillna(0).values)[:, 1]
    entered = rows[rows["prob"] >= threshold][["episode_id", col]].rename(columns={col: "pnl"})
    cohort  = pd.DataFrame({"episode_id": all_eps}).merge(entered, on="episode_id", how="left")
    cohort["pnl"] = cohort["pnl"].fillna(0.0)
    m = _ev_metrics(cohort["pnl"].values)
    m.update(delay_s=delay_s, policy=policy, cost_tier=cost, threshold=threshold)
    return m


def eval_knn_shuffle(df: pd.DataFrame, delay_s: float, model, feats: list,
                     threshold: float, policy: str,
                     period_prefix=None, direction=None, seed: int = 42) -> dict:
    """Permute KNN columns across episodes before scoring. Measures KNN information value."""
    rng   = np.random.default_rng(seed)
    src   = _filter(df, period_prefix, direction)
    all_eps = src["episode_id"].unique()
    col   = _pnl_col(policy, "base")
    rows  = first_at_or_after(src, delay_s).copy()

    # Shuffle KNN features across episodes
    knn_in = [c for c in _KNN_FEATS if c in rows.columns]
    knn_coverage = rows[knn_in[0]].notna().mean() if knn_in else 0.0
    n = len(rows)
    perm = rng.permutation(n)
    rows[knn_in] = rows[knn_in].values[perm]

    avail  = [c for c in feats if c in rows.columns]
    rows["prob"] = model.predict_proba(rows[avail].fillna(0).values)[:, 1]
    entered = rows[rows["prob"] >= threshold][["episode_id", col]].rename(columns={col: "pnl"})
    cohort  = pd.DataFrame({"episode_id": all_eps}).merge(entered, on="episode_id", how="left")
    cohort["pnl"] = cohort["pnl"].fillna(0.0)
    m = _ev_metrics(cohort["pnl"].values)
    m.update(delay_s=delay_s, policy=policy, cost_tier="base",
             knn_coverage_at_delay=float(knn_coverage))
    return m


# -- Matched cohort decomposition -----------------------------------------------

def matched_cohort_decompose(df: pd.DataFrame, delay_s: float, policy: str,
                              period_prefix: str) -> dict:
    """Decompose delay EV into survival-filter benefit + timing benefit."""
    col = _pnl_col(policy, "base")
    src = df[df["period"].str.startswith(period_prefix)].copy()
    all_eps = src["episode_id"].unique()
    imm = first_immediate(src)[["episode_id", col]].rename(columns={col: "imm_pnl"})
    dly = first_at_or_after(src, delay_s)[["episode_id", col]].rename(columns={col: "del_pnl"})
    c   = (pd.DataFrame({"episode_id": all_eps})
           .merge(imm, on="episode_id", how="left")
           .merge(dly, on="episode_id", how="left"))
    survived = c["del_pnl"].notna()
    c.loc[~survived, "del_pnl"] = 0.0
    n_total, n_surv = len(c), int(survived.sum())
    ev_imm = float(c["imm_pnl"].mean())
    ev_del = float(c["del_pnl"].mean())
    sf_ben = -float(c.loc[~survived, "imm_pnl"].mean()) if (~survived).any() else 0.0
    t_ben  = (float(c.loc[survived, "del_pnl"].mean()) -
               float(c.loc[survived, "imm_pnl"].mean())) if survived.any() else 0.0
    return {"delay_s": delay_s, "policy": policy, "period": period_prefix,
            "n_total": n_total, "n_survived": n_surv, "n_filtered": n_total - n_surv,
            "survival_rate": n_surv / n_total,
            "ev_immediate": ev_imm, "ev_delayed": ev_del,
            "total_improvement": ev_del - ev_imm,
            "survival_filter_benefit": sf_ben, "timing_benefit": t_ben}


# -- Threshold tuning -----------------------------------------------------------

def tune_threshold(df: pd.DataFrame, delay_s: float, model, feats: list,
                   policy: str = "fixed_300s") -> tuple[float, float]:
    val_df = df[df["period"] == "val"]
    best_thr, best_ev = 0.50, float("-inf")
    for thr in np.arange(0.40, 0.65, 0.05):
        m = eval_ml_gated(val_df, delay_s, model, feats, thr, policy)
        if m["ev_ep"] > best_ev:
            best_ev, best_thr = m["ev_ep"], float(thr)
    return best_thr, best_ev


# -- Main -----------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("Delayed Entry Repair -- Phase 4-7: Policy Evaluation")
    print("=" * 70)

    df = pd.read_parquet(OUT_DIR / "study_features.parquet")
    print(f"\nLoaded study_features: {df.shape}")

    # Guard: no suffix conflicts
    bad = [c for c in df.columns if c.endswith("_x") or c.endswith("_y")]
    if bad:
        raise ValueError(f"Suffix-conflict columns: {bad[:10]}")
    print("Suffix conflict check: PASS")

    # Verify KNN coverage in bar-4 observations
    bar4_rows = df[df["seconds_since_flip"] >= BAR4_DELAY_S]
    bar4_knn_cov = bar4_rows["knn_hA"].notna().mean()
    print(f"KNN coverage at bar-4+ observations: {bar4_knn_cov:.1%}")

    df["y_entry_positive_300s"] = (df["base__pnl_300s"] > 0).astype(np.int8)

    manifest = {}

    # ===========================================================================
    # Phase 4: Delay sweep on val (unconditional)
    # ===========================================================================
    print("\n" + "-" * 60)
    print("Phase 4: Delay sweep on val (unconditional)")
    print("-" * 60)
    sweep_rows = []
    for d in CANDIDATE_DELAYS:
        mf = eval_uncond(df, d, "fixed_300s", period_prefix="val")
        mr = eval_uncond(df, d, "opposing_regime", period_prefix="val")
        sweep_rows.append({"delay_s": d,
                           "ev_ep_fixed":  round(mf["ev_ep"], 2),
                           "n_traded_fixed": mf["n_traded"],
                           "ev_ep_regime": round(mr["ev_ep"], 2),
                           "n_traded_regime": mr["n_traded"]})
        print(f"  delay={d:3d}s  fixed={mf['ev_ep']:+.2f} ({mf['n_traded']}/{mf['n_total']})"
              f"  regime={mr['ev_ep']:+.2f}")
    sweep = pd.DataFrame(sweep_rows)
    sweep.to_parquet(OUT_DIR / "delay_sweep_val.parquet", index=False)

    best_delay = int(sweep.loc[sweep["ev_ep_fixed"].idxmax(), "delay_s"])
    print(f"\n  * Selected delay: {best_delay}s (val fixed_300s EV/ep)")

    # ===========================================================================
    # Phase 5: Unconditional results at best_delay on test periods
    # ===========================================================================
    print("\n" + "-" * 60)
    print(f"Phase 5: Unconditional entry at {best_delay}s -- test periods")
    print("-" * 60)
    uncond_rows = []
    for policy in ["fixed_300s", "opposing_regime"]:
        for cost in ["base", "plus_1t", "plus_2t"]:
            for prd in ["test_2024q4", "test_2025h1"]:
                for dir_val, dir_name in [(None, "combined"), (1, "long"), (-1, "short")]:
                    m = eval_uncond(df, best_delay, policy, cost, prd, dir_val)
                    m["period"] = prd; m["direction"] = dir_name
                    uncond_rows.append(m)
                    if cost == "base" and dir_name == "combined":
                        print(f"  [{prd}] {policy}: EV/ep={m['ev_ep']:+.2f}"
                              f"  WR={m['wr']:.1%}  CI=({m['ci_lo']:+.2f},{m['ci_hi']:+.2f})"
                              f"  n={m['n_traded']}/{m['n_total']}")
    pd.DataFrame(uncond_rows).to_parquet(OUT_DIR / "uncond_policy_results.parquet", index=False)

    # -- Phase 5b: Matched cohort decomposition -----------------------------
    print("\nMatched cohort decomposition:")
    cohort_rows = []
    for prd in ["test_2024q4", "test_2025h1"]:
        for policy in ["fixed_300s", "opposing_regime"]:
            c = matched_cohort_decompose(df, best_delay, policy, prd)
            cohort_rows.append(c)
            print(f"  [{prd}] {policy}: "
                  f"imm={c['ev_immediate']:+.2f}  del={c['ev_delayed']:+.2f}  "
                  f"filter={c['survival_filter_benefit']:+.2f}  "
                  f"timing={c['timing_benefit']:+.2f}  "
                  f"survive={c['survival_rate']:.1%}")
    pd.DataFrame(cohort_rows).to_parquet(OUT_DIR / "matched_cohort.parquet", index=False)

    # ===========================================================================
    # Phase 6: KNN model at bar-4 (240s) -- KNN has real values here
    # This is the ONLY meaningful KNN test: at 240s, all inference rows have KNN.
    # ===========================================================================
    print("\n" + "-" * 60)
    print(f"Phase 6: Bar-4 ({BAR4_DELAY_S}s) KNN entry model")
    print("-" * 60)

    # Train on bar-4+ observations only (KNN always available)
    tv_bar4 = df[
        df["period"].isin(["train", "val"]) &
        (df["seconds_since_flip"] >= BAR4_DELAY_S)
    ].copy()
    bar4_model, bar4_feats, bar4_auc = train_lgbm(
        tv_bar4, "y_entry_positive_300s", _BAR4_FEATS, "Bar4-KNN"
    )

    # -- Manifest assertion (required) --------------------------------------
    print("\n  Manifest assertion:")
    failed = [c for c in _REQUIRED_KNN_MANIFEST if c not in bar4_feats]
    if failed:
        raise AssertionError(
            f"MANIFEST ASSERTION FAILED -- required KNN fields absent from bar-4 model: {failed}\n"
            f"  bar4_feats = {bar4_feats}"
        )
    for c in _REQUIRED_KNN_MANIFEST:
        print(f"    ok {c}")

    # Check KNN coverage at inference (bar-4 delay step in val)
    val_bar4_rows = first_at_or_after(df[df["period"] == "val"], BAR4_DELAY_S)
    infer_knn_cov = val_bar4_rows["knn_hA"].notna().mean()
    print(f"  KNN coverage at inference (val, 240s): {infer_knn_cov:.1%}")
    assert infer_knn_cov > 0.5, \
        f"KNN coverage {infer_knn_cov:.1%} too low at 240s -- check KNN data"

    manifest["bar4_model"] = {
        "delay_s":               BAR4_DELAY_S,
        "features":              bar4_feats,
        "val_auc":               bar4_auc,
        "knn_fields_asserted":   _REQUIRED_KNN_MANIFEST,
        "knn_coverage_at_infer": float(infer_knn_cov),
    }

    # -- Tune bar-4 threshold on val -----------------------------------------
    print("\n  Tuning bar-4 threshold on val ...")
    bar4_thr, bar4_val_ev = tune_threshold(df, BAR4_DELAY_S, bar4_model, bar4_feats)
    print(f"  Best bar-4 threshold: {bar4_thr:.2f}  val EV/ep: {bar4_val_ev:+.2f}")
    manifest["bar4_threshold"] = bar4_thr
    manifest["bar4_val_ev"]    = bar4_val_ev

    # ===========================================================================
    # Phase 7: Bar-4 ML results on test periods
    # ===========================================================================
    print("\n" + "-" * 60)
    print(f"Phase 7: Bar-4 ML results ({BAR4_DELAY_S}s) -- test periods")
    print("-" * 60)
    ml_rows = []
    for policy in ["fixed_300s", "opposing_regime"]:
        for cost in ["base", "plus_1t", "plus_2t"]:
            for prd in ["test_2024q4", "test_2025h1"]:
                for dir_val, dir_name in [(None, "combined"), (1, "long"), (-1, "short")]:
                    m = eval_ml_gated(df, BAR4_DELAY_S, bar4_model, bar4_feats,
                                      bar4_thr, policy, cost, prd, dir_val)
                    m["period"] = prd; m["direction"] = dir_name
                    ml_rows.append(m)
                    if cost == "base" and dir_name == "combined":
                        print(f"  [{prd}] ML+{policy}: EV/ep={m['ev_ep']:+.2f}"
                              f"  WR={m['wr']:.1%}  CI=({m['ci_lo']:+.2f},{m['ci_hi']:+.2f})"
                              f"  n={m['n_traded']}/{m['n_total']}")
    ml_df = pd.DataFrame(ml_rows)
    ml_df.to_parquet(OUT_DIR / "ml_policy_results.parquet", index=False)

    # ===========================================================================
    # Phase 7b: KNN shuffle control at bar-4 (REQUIRED, MEANINGFUL)
    # At 240s, KNN has real values -> shuffling tests real information value
    # ===========================================================================
    print("\n" + "-" * 60)
    print("Phase 7b: KNN shuffle control at bar-4 (required)")
    print("-" * 60)
    ctrl_rows = []
    for policy in ["fixed_300s", "opposing_regime"]:
        for prd in ["test_2024q4", "test_2025h1"]:
            c = eval_knn_shuffle(df, BAR4_DELAY_S, bar4_model, bar4_feats,
                                 bar4_thr, policy, period_prefix=prd)
            c["period"] = prd; c["policy"] = policy
            ctrl_rows.append(c)
            print(f"  [{prd}] KNN-shuffle {policy}: EV/ep={c['ev_ep']:+.2f}"
                  f"  WR={c['wr']:.1%}  CI=({c['ci_lo']:+.2f},{c['ci_hi']:+.2f})"
                  f"  n={c['n_traded']}/{c['n_total']}"
                  f"  knn_cov={c['knn_coverage_at_delay']:.1%}")
    ctrl_df = pd.DataFrame(ctrl_rows)

    print("\n  KNN lift vs shuffle control:")
    verdicts = {}
    for policy in ["fixed_300s", "opposing_regime"]:
        for prd in ["test_2024q4", "test_2025h1"]:
            real_ev = ml_df[
                (ml_df["policy"] == policy) & (ml_df["period"] == prd) &
                (ml_df["direction"] == "combined") & (ml_df["cost_tier"] == "base")
            ]["ev_ep"].iloc[0]
            ctrl_ev = ctrl_df[
                (ctrl_df["policy"] == policy) & (ctrl_df["period"] == prd)
            ]["ev_ep"].iloc[0]
            delta = real_ev - ctrl_ev
            verdict = "NULL" if abs(delta) < 0.5 else ("LIFT" if delta > 0 else "HURT")
            print(f"  [{prd}] {policy}: real={real_ev:+.2f}  shuffle={ctrl_ev:+.2f}"
                  f"  ?={delta:+.2f}  [{verdict}]")
            ctrl_df.loc[
                (ctrl_df["policy"] == policy) & (ctrl_df["period"] == prd),
                ["delta_vs_real", "knn_verdict"]
            ] = [delta, verdict]
            verdicts[(policy, prd)] = verdict
    ctrl_df.to_parquet(OUT_DIR / "knn_control_results.parquet", index=False)

    # ===========================================================================
    # Phase 7c: Combined test summary -- all variants, base cost, combined direction
    # ===========================================================================
    print("\n" + "-" * 60)
    print("Phase 7c: Combined test summary")
    print("-" * 60)
    test_df = df[df["period"].str.startswith("test")].copy()
    combined_rows = []
    for var, fn, d, thr in [
        ("uncond_fixed",   eval_uncond,    best_delay,   None),
        ("uncond_regime",  eval_uncond,    best_delay,   None),
        ("bar4_uncond_f",  eval_uncond,    BAR4_DELAY_S, None),
        ("bar4_ml_fixed",  eval_ml_gated,  BAR4_DELAY_S, bar4_thr),
        ("bar4_ml_regime", eval_ml_gated,  BAR4_DELAY_S, bar4_thr),
    ]:
        policy = "fixed_300s" if "fixed" in var or var == "uncond_fixed" else "opposing_regime"
        if var == "uncond_regime":
            policy = "opposing_regime"
        if var == "bar4_uncond_f":
            policy = "fixed_300s"
        for dir_val, dir_name in [(None, "combined"), (1, "long"), (-1, "short")]:
            if fn is eval_uncond:
                m = fn(test_df, d, policy, "base", direction=dir_val)
            else:
                m = fn(test_df, d, bar4_model, bar4_feats, thr, policy, "base",
                       direction=dir_val)
            m["variant"] = var; m["direction"] = dir_name; m["period"] = "test_combined"
            combined_rows.append(m)
            if dir_name == "combined":
                print(f"  {var:20s}: EV/ep={m['ev_ep']:+.2f}  WR={m['wr']:.1%}"
                      f"  CI=({m['ci_lo']:+.2f},{m['ci_hi']:+.2f})"
                      f"  n={m['n_traded']}/{m['n_total']}")
    combined_df = pd.DataFrame(combined_rows)
    combined_df.to_parquet(OUT_DIR / "combined_test_results.parquet", index=False)

    # Save manifest
    with open(OUT_DIR / "model_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # -- Final summary -------------------------------------------------------
    print("\n" + "=" * 70)
    print("SUMMARY")
    print(f"  Best unconditional delay (val): {best_delay}s")
    print(f"  Bar-4 KNN model val AUC:        {bar4_auc:.4f}")
    print(f"  Bar-4 threshold:                {bar4_thr:.2f}")
    knn_global = "LIFT" if any(v == "LIFT" for v in verdicts.values()) else \
                 "NULL" if all(v == "NULL" for v in verdicts.values()) else "MIXED"
    print(f"  KNN verdict (shuffle control):  {knn_global}")
    print("\nPhase 4-7 complete.")


if __name__ == "__main__":
    main()
