"""2024 OOS: classification generalization, frozen score-tail, timing, TRAIN->OOS
degradation. LONG and SHORT reported separately.

Frozen 180s models: native LightGBM boosters from the aggregate TRAIN freeze
(train_experiment_freeze.json). No refit, no retune, no threshold change.
Frozen 300s parent: LGBMClassifier estimators from the parent's frozen bundle
(previously-observed benchmark; parent is never re-touched).

LONG  <=> regime_direction == -1     SHORT <=> regime_direction == +1
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, joblib
import lightgbm as lgb

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(ROOT))
from research.analysis.metrics import classification_bundle

S180 = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
SPAR = ROOT / "studies" / "clean_maturity_flip_model_rolling_productivity"
JOIN = ["observation_ts", "regime_start_ns", "checkpoint_index"]
ARM_C = ["arrival_velocity", "arrival_acceleration", "ema_slope",
         "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
         "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
         "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
         "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr"]
DIR_SIGN = {"LONG": -1, "SHORT": 1}
MATURITY = [(0, 300), (300, 600), (600, 900), (900, 1800), (1800, 10**9)]

AGG = json.loads((S180 / "artifacts" / "train_experiment_freeze.json").read_text())
PAR_FZ = json.loads((SPAR / "artifacts" / "train_experiment_freeze_repaired.json").read_text())
TPS = json.loads((S180 / "artifacts" / "two_phase_selection_dispatch_summary.json").read_text())


def mbucket(age):
    for lo, hi in MATURITY:
        if lo <= age < hi:
            return f"{lo}-{hi}" if hi < 10**8 else f"{lo}+"
    return "na"


def _bundle(y, s):
    b = classification_bundle(pd.Series(np.asarray(y)), np.asarray(s, dtype=float))
    return {k: (b[k]["value"] if b[k]["status"] == "ok" else None)
            for k in ("roc_auc", "pr_auc", "brier", "positive_rate", "sample_count")}


def _calibration(y, s, bins=10):
    y = np.asarray(y, float); s = np.asarray(s, float)
    edges = np.quantile(s, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    rows, ece = [], 0.0
    for i in range(bins):
        m = (s >= edges[i]) & (s < edges[i + 1])
        if not m.any():
            continue
        p, o, n = float(s[m].mean()), float(y[m].mean()), int(m.sum())
        rows.append({"bin": i, "n": n, "mean_pred": p, "obs_rate": o})
        ece += (n / len(s)) * abs(p - o)
    return {"reliability_bins": rows, "expected_calibration_error": float(ece)}


def _metrics_block(y, s):
    d = _bundle(y, s)
    br = d["positive_rate"]
    d["pr_auc_over_base_rate"] = (d["pr_auc"] / br) if (d["pr_auc"] is not None and br) else None
    d["calibration"] = _calibration(y, s)
    return d


def load_180s_oos():
    c = pd.read_parquet(S180 / "artifacts" / "oos_candidates_merged.parquet")
    o = pd.read_parquet(S180 / "artifacts" / "oos_observations_merged.parquet")
    df = c.merge(o[JOIN + ["regime_direction", "target_flip_within_horizon", "disposition", "time_to_flip_seconds"]],
                 on=JOIN, how="inner", validate="one_to_one")
    df = df[df.disposition.isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])].copy()
    df["y"] = df.target_flip_within_horizon.astype(int)
    df["_yr"] = pd.to_datetime(df.observation_ts, unit="ns", utc=True).dt.year
    df = df[df._yr == 2024].copy()
    df["mb"] = df.regime_age_seconds.map(mbucket)
    return df


def load_parent_oos():
    c = pd.read_parquet(SPAR / "artifacts" / "oos2024_raw_candidates_reproduced.parquet")
    o = pd.read_parquet(SPAR / "artifacts" / "oos2024_raw_observations_reproduced.parquet")
    df = c.merge(o[JOIN + ["regime_direction", "target_flip_within_horizon", "disposition", "time_to_flip_seconds"]],
                 on=JOIN, how="inner", validate="one_to_one")
    df = df[df.disposition.isin(["LABELED_POSITIVE", "LABELED_NEGATIVE"])].copy()
    df["y"] = df.target_flip_within_horizon.astype(int)
    df["_yr"] = pd.to_datetime(df.observation_ts, unit="ns", utc=True).dt.year
    df = df[df._yr == 2024].copy()
    df["mb"] = df.regime_age_seconds.map(mbucket) if "regime_age_seconds" in df.columns else "na"
    return df


def score_180s(df, direction):
    mid = {r["model_role"]: r["model_id"] for r in AGG["model_artifacts"]}[f"{direction}_C"]
    bst = lgb.Booster(model_file=str(S180 / "artifacts" / "models" / f"{mid}.booster.txt"))
    thr = {k: AGG["thresholds"][f"{direction}_C"][k]["threshold"] for k in ("p90", "p95", "p97_5")}
    return bst.predict(df[ARM_C].to_numpy(float)), thr, mid


def score_parent(df, direction):
    rec = joblib.load(SPAR / "artifacts" / "train_fitted_models.joblib")[f"{direction}_C"]
    feats = rec["provenance"]["ordered_features"]
    s = rec["estimator"].predict_proba(df[feats])[:, 1]
    thr = {k: PAR_FZ["thresholds"][f"{direction}_C"][k] for k in ("p90", "p95", "p97_5")}
    return s, thr, rec["fit_identity_sha256"]


def score_tail(df, s, thr):
    d = df.assign(score=s)
    base = float(d.y.mean())
    out = {"base_rate": base}
    for k, v in thr.items():
        hi = d[d.score >= v]
        flipped = hi[hi.y == 1]
        out[k] = {
            "threshold": float(v),
            "retained_n": int(len(hi)),
            "retained_frac": float(len(hi) / len(d)) if len(d) else None,
            "actual_flip_prob": float(hi.y.mean()) if len(hi) else None,
            "precision_lift_over_base": float(hi.y.mean() / base) if (len(hi) and base) else None,
            "median_seconds_to_flip": float(flipped.time_to_flip_seconds.median()) if len(flipped) else None,
        }
    return out


def first_crossing_timing(df, s, thr):
    d = df.assign(score=s).sort_values(JOIN)
    out = {}
    for k, v in thr.items():
        hi = d[d.score >= v]
        fc = hi.groupby("regime_start_ns", as_index=False).first()
        flipped = fc[fc.time_to_flip_seconds.notna()]
        out[k] = {
            "n_first_crossings": int(len(fc)),
            "n_flipped": int(len(flipped)),
            "flip_rate": float(fc.time_to_flip_seconds.notna().mean()) if len(fc) else None,
            "median_seconds_to_flip": float(flipped.time_to_flip_seconds.median()) if len(flipped) else None,
        }
    return out


def direction_report(d180, dpar, direction):
    sign = DIR_SIGN[direction]
    a = d180[d180.regime_direction == sign].reset_index(drop=True)
    p = dpar[dpar.regime_direction == sign].reset_index(drop=True)
    s180, thr180, mid = score_180s(a, direction)
    spar, thrpar, pid = score_parent(p, direction)

    train_gate = TPS[direction]["final_validation_metrics"]  # 2023 reject-only
    oos_180 = _metrics_block(a.y, s180)

    return {
        "model_id_180s": mid, "model_fit_identity_300s": pid,
        "n_180s": int(len(a)), "n_300s": int(len(p)),
        "classification_180s": oos_180,
        "classification_300s_parent_benchmark": _metrics_block(p.y, spar),
        "by_maturity_180s": {b: _metrics_block(g.y, s180[a.mb.values == b])
                             for b, g in a.groupby("mb") if len(g) > 200},
        "frozen_score_tail_180s": score_tail(a, s180, thr180),
        "frozen_score_tail_300s_parent_benchmark": score_tail(p, spar, thrpar),
        "first_crossing_timing_180s": first_crossing_timing(a, s180, thr180),
        "first_crossing_timing_300s_parent_benchmark": first_crossing_timing(p, spar, thrpar),
        "train_2023_reject_only_gate": {"pr_auc": train_gate["pr_auc"], "brier": train_gate["brier"]},
        "train_to_oos_degradation": {
            "pr_auc_train2023": train_gate["pr_auc"], "pr_auc_oos2024": oos_180["pr_auc"],
            "pr_auc_delta": (oos_180["pr_auc"] - train_gate["pr_auc"]) if oos_180["pr_auc"] is not None else None,
            "pr_auc_retention_frac": (oos_180["pr_auc"] / train_gate["pr_auc"]) if oos_180["pr_auc"] is not None else None,
            "brier_train2023": train_gate["brier"], "brier_oos2024": oos_180["brier"],
        },
    }


def main():
    d180 = load_180s_oos()
    dpar = load_parent_oos()
    result = {
        "generated_for": "2024 OOS",
        "note": "frozen 180s native boosters vs previously-observed frozen 300s parent benchmark; no refit/retune/threshold change",
        "oos_180s_labeled_rows": int(len(d180)),
        "oos_180s_base_rate_overall": float(d180.y.mean()),
        "oos_300s_parent_labeled_rows_2024": int(len(dpar)),
        "aggregate_freeze_sha256": AGG["freeze_sha256"],
    }
    for direction in ("LONG", "SHORT"):
        result[direction] = direction_report(d180, dpar, direction)
    (S180 / "artifacts" / "oos_2024_classification_timing.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({d: {
        "180s_roc_auc": result[d]["classification_180s"]["roc_auc"],
        "180s_pr_auc": result[d]["classification_180s"]["pr_auc"],
        "180s_pr_auc_lift": result[d]["classification_180s"]["pr_auc_over_base_rate"],
        "180s_brier": result[d]["classification_180s"]["brier"],
        "180s_base": result[d]["classification_180s"]["positive_rate"],
        "300s_roc_auc": result[d]["classification_300s_parent_benchmark"]["roc_auc"],
        "300s_pr_auc_lift": result[d]["classification_300s_parent_benchmark"]["pr_auc_over_base_rate"],
        "train2023_pr_auc": result[d]["train_2023_reject_only_gate"]["pr_auc"],
    } for d in ("LONG", "SHORT")}, indent=2))


if __name__ == "__main__":
    main()
