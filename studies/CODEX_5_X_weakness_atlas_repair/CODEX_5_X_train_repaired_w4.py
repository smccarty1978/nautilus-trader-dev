"""Chronological repaired-W4 structure comparison, freeze, and 2026 test."""
from __future__ import annotations

import argparse
import gc
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, roc_auc_score,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(UPSTREAM))

from CODEX_5_X_common import (  # noqa: E402
    AUDIT, BUNDLE_PATH, CALIBRATION_END_NS, CALIBRATION_START_NS,
    FIRST_2026_OPEN_PATH, MANIFEST_PATH, NAN_GATE, NS,
    REQUIRED_DEPENDENCY_RELATIVE, RESULTS, ROOT,
    SEED, SELECTION_END_NS,
    SELECTION_START_NS, TRAIN_YEARS, require_frozen_pre_2026_contract,
    sha256_file, write_json, year_atlas_path,
)
from train_weakness_model import CENTER_FEATS, LOCAL_FEATS, SEQUENCE_FEATS  # noqa: E402

BASE_FEATURES = CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS
INTERACTION_LOCAL = LOCAL_FEATS
def columns_needed() -> list[str]:
    return list(dict.fromkeys(BASE_FEATURES + [
        NAN_GATE, "observation_time", "regime_start_ns", "regime_end_ns",
        "regime_age", "direction", "atr", "atr_at_entry",
        "atr_at_checkpoint", "opp_flip_in_120s",
        "terminal_deterioration",
    ]))


def load_years(years: list[int]) -> pd.DataFrame:
    parts = []
    for year in years:
        path = year_atlas_path(year)
        assert path.exists(), path
        d = pd.read_parquet(path, columns=columns_needed())
        d["year"] = year
        parts.append(d)
    out = pd.concat(parts, ignore_index=True)
    if out["direction"].isna().any() or set(out["direction"].unique()) != {-1, 1}:
        raise RuntimeError("model atlas direction domain must be exactly {-1,+1}")
    if not (out["observation_time"] < out["regime_end_ns"]).all():
        raise RuntimeError("model atlas contains an endpoint/post-flip row")
    out = out[out[NAN_GATE].notna()].copy()
    out["target"] = (
        (out["opp_flip_in_120s"] == 1)
        | (out["terminal_deterioration"] == 1)
    ).astype(np.int8)
    return out


def base_matrix(d: pd.DataFrame,
                features: list[str] | None = None) -> np.ndarray:
    return d[features or BASE_FEATURES].to_numpy(dtype=np.float32)


def interaction_matrix(d: pd.DataFrame, base: np.ndarray | None = None,
                       base_features: list[str] | None = None,
                       interaction_local: list[str] | None = None) -> np.ndarray:
    if base is None:
        base = base_matrix(d, base_features)
    direction = d["direction"].to_numpy(dtype=np.float32)[:, None]
    local = d[interaction_local or INTERACTION_LOCAL].to_numpy(dtype=np.float32)
    return np.concatenate([base, direction, local * direction], axis=1)


def new_model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=100, max_depth=5, learning_rate=0.05, random_state=SEED,
    )


def raw_scores(models: dict, structure: str, d: pd.DataFrame,
               x_base: np.ndarray | None = None,
               base_features: list[str] | None = None,
               interaction_local: list[str] | None = None) -> np.ndarray:
    if x_base is None:
        x_base = base_matrix(d, base_features)
    if structure == "pooled":
        return models["pooled"].predict_proba(x_base)[:, 1]
    if structure == "pooled_interactions":
        return models["pooled_interactions"].predict_proba(
            interaction_matrix(d, x_base, base_features,
                               interaction_local))[:, 1]
    if structure == "directional_pair":
        direction = d["direction"].to_numpy()
        if set(np.unique(direction)) != {-1, 1}:
            raise RuntimeError("directional scoring requires {-1,+1}")
        out = np.empty(len(d), dtype=float)
        long = direction == 1
        short = direction == -1
        if not np.all(long | short):
            raise RuntimeError("unrouted direction during scoring")
        out[long] = models["long_only"].predict_proba(x_base[long])[:, 1]
        out[short] = models["short_only"].predict_proba(x_base[short])[:, 1]
        return out
    raise ValueError(structure)


def metric_row(model: str, segment: str, y: np.ndarray,
               prob: np.ndarray) -> dict:
    return {
        "model": model, "segment": segment, "count": len(y),
        "base_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, prob)),
        "pr_auc": float(average_precision_score(y, prob)),
        "brier": float(brier_score_loss(y, prob)),
    }


def structure_metrics(models: dict, d: pd.DataFrame,
                      window: str) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    x = base_matrix(d)
    y = d["target"].to_numpy(dtype=np.int8)
    direction = d["direction"].to_numpy()
    scores = {
        name: raw_scores(models, name, d, x)
        for name in ("pooled", "pooled_interactions", "directional_pair")
    }
    rows = []
    for name, prob in scores.items():
        rows.append({**metric_row(name, "all", y, prob), "window": window})
        for dr, label in ((1, "prevailing_long"), (-1, "prevailing_short")):
            m = direction == dr
            rows.append({**metric_row(name, label, y[m], prob[m]),
                         "window": window})
    for dr, name, label in (
        (1, "long_only", "prevailing_long"),
        (-1, "short_only", "prevailing_short"),
    ):
        m = direction == dr
        p = models[name].predict_proba(x[m])[:, 1]
        rows.append({**metric_row(name, label, y[m], p), "window": window})
    del x
    gc.collect()
    return pd.DataFrame(rows), scores


def select_structure(metrics: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    candidates = []
    for name in ("pooled", "pooled_interactions", "directional_pair"):
        x = metrics[metrics["model"] == name].set_index("segment")
        auc_l = float(x.loc["prevailing_long", "roc_auc"])
        auc_s = float(x.loc["prevailing_short", "roc_auc"])
        candidates.append({
            "model": name, "macro_direction_auc": (auc_l + auc_s) / 2,
            "direction_auc_gap": abs(auc_l - auc_s),
            "auc_long": auc_l, "auc_short": auc_s,
            "complexity_rank": {"pooled": 0, "pooled_interactions": 1,
                                "directional_pair": 2}[name],
        })
    c = pd.DataFrame(candidates)
    best = c["macro_direction_auc"].max()
    eligible = c[c["macro_direction_auc"] >= best - 0.005].copy()
    eligible = eligible.sort_values(
        ["direction_auc_gap", "complexity_rank"], kind="stable"
    )
    return str(eligible.iloc[0]["model"]), c


def calibrate_and_threshold(raw: np.ndarray, d: pd.DataFrame) -> tuple[dict, np.ndarray, dict]:
    y = d["target"].to_numpy(dtype=np.int8)
    direction = d["direction"].to_numpy()
    calibrated = np.empty(len(d), dtype=float)
    calibrators: dict[int, IsotonicRegression] = {}
    thresholds: dict[int, float] = {}
    for dr in (1, -1):
        m = direction == dr
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        calibrated[m] = iso.fit_transform(raw[m], y[m])
        calibrators[dr] = iso
        thresholds[dr] = float(np.percentile(calibrated[m], 90.0))
    return calibrators, calibrated, thresholds


def apply_calibration(raw: np.ndarray, direction: np.ndarray,
                      calibrators: dict) -> np.ndarray:
    if set(np.unique(direction)) != {-1, 1}:
        raise RuntimeError("calibration requires direction domain {-1,+1}")
    out = np.empty(len(raw), dtype=float)
    for dr in (1, -1):
        m = direction == dr
        out[m] = calibrators[dr].predict(raw[m])
    return out


def purged_2025_windows(val: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Create outcome-disjoint H1/H2 frames and purge boundary regimes."""
    bounds = val.groupby("regime_start_ns", sort=False).agg(
        regime_start_ns=("regime_start_ns", "first"),
        regime_end_ns=("regime_end_ns", "first"),
    )
    crossing = bounds[(bounds["regime_start_ns"] < SELECTION_END_NS)
                      & (bounds["regime_end_ns"] > SELECTION_END_NS)].index
    selection_keys = bounds[
        (bounds["regime_start_ns"] >= SELECTION_START_NS)
        & (bounds["regime_end_ns"] <= SELECTION_END_NS)
    ].index
    calibration_keys = bounds[
        (bounds["regime_start_ns"] >= CALIBRATION_START_NS)
        & (bounds["regime_end_ns"] <= CALIBRATION_END_NS)
    ].index
    selection = val[val["regime_start_ns"].isin(selection_keys)].copy()
    calibration = val[val["regime_start_ns"].isin(calibration_keys)].copy()
    overlap = set(selection["regime_start_ns"]) & set(calibration["regime_start_ns"])
    if overlap:
        raise RuntimeError("selection/calibration regime keys overlap")
    purge = {
        "boundary_ns": SELECTION_END_NS,
        "purged_regime_count": len(crossing),
        "purged_regime_start_ns": [int(x) for x in crossing],
        "selection_regime_count": int(selection["regime_start_ns"].nunique()),
        "calibration_regime_count": int(calibration["regime_start_ns"].nunique()),
    }
    return selection, calibration, purge


def score_distribution_and_crossings(d: pd.DataFrame, scores: np.ndarray,
                                     thresholds: dict, window: str) -> pd.DataFrame:
    x = d[["observation_time", "regime_start_ns", "direction"]].copy()
    x["score"] = scores
    rows = []
    for dr, g in x.groupby("direction"):
        threshold = float(thresholds[int(dr)])
        g = g.sort_values(["regime_start_ns", "observation_time"], kind="stable")
        prev = g.groupby("regime_start_ns", sort=False)["score"].shift(1)
        crosses = prev.notna() & (prev < threshold) & (g["score"] >= threshold)
        regimes = int(g["regime_start_ns"].nunique())
        crossed_regimes = int(g.loc[crosses, "regime_start_ns"].nunique())
        q = g["score"].quantile([0.01, 0.10, 0.50, 0.90, 0.99])
        rows.append({
            "window": window, "direction": int(dr), "threshold": threshold,
            "checkpoint_count": len(g), "finite_score_rate": float(np.isfinite(g["score"]).mean()),
            "score_mean": g["score"].mean(), "score_std": g["score"].std(),
            "score_p01": q.loc[0.01], "score_p10": q.loc[0.10],
            "score_p50": q.loc[0.50], "score_p90": q.loc[0.90],
            "score_p99": q.loc[0.99],
            "checkpoint_at_or_above_rate": float((g["score"] >= threshold).mean()),
            "strict_cross_count": int(crosses.sum()),
            "regime_count": regimes, "crossed_regime_count": crossed_regimes,
            "strict_cross_regime_rate": crossed_regimes / regimes if regimes else np.nan,
        })
    return pd.DataFrame(rows)


def score_frame(d: pd.DataFrame, calibrated: np.ndarray,
                thresholds: dict) -> pd.DataFrame:
    direction = d["direction"].to_numpy(dtype=np.int8)
    return pd.DataFrame({
        "observation_time": d["observation_time"].to_numpy(dtype=np.int64),
        "regime_start_ns": d["regime_start_ns"].to_numpy(dtype=np.int64),
        "direction": direction,
        "regime_age": d["regime_age"].to_numpy(dtype=float),
        "atr": d["atr"].to_numpy(dtype=float),
        "atr_at_entry": d["atr_at_entry"].to_numpy(dtype=float),
        "atr_at_checkpoint": d["atr_at_checkpoint"].to_numpy(dtype=float),
        "w4_score": calibrated,
        "direction_threshold": np.where(direction == 1, thresholds[1], thresholds[-1]),
        "score_valid": np.isfinite(calibrated),
    }).sort_values(["regime_start_ns", "observation_time"], kind="stable")


def ensure_freeze_allowed() -> None:
    if FIRST_2026_OPEN_PATH.exists():
        raise RuntimeError("cannot refreeze after the first recorded 2026 opening")
    if year_atlas_path(2026).exists():
        raise RuntimeError(
            "2026 repaired atlas already exists; freeze cannot access or replace it"
        )


def train_and_freeze() -> None:
    ensure_freeze_allowed()
    train = load_years(list(TRAIN_YEARS))
    if int(train["year"].max()) > 2024:
        raise RuntimeError("training frame contains post-2024 rows")
    val = load_years([2025])
    if int(val["observation_time"].max()) >= CALIBRATION_END_NS:
        raise RuntimeError("2025 frame crosses into 2026")
    selection, calibration, purge = purged_2025_windows(val)
    if selection.empty or calibration.empty:
        raise RuntimeError("purged 2025 selection/calibration frame is empty")

    xtr = base_matrix(train)
    ytr = train["target"].to_numpy(dtype=np.int8)
    dtr = train["direction"].to_numpy(dtype=np.int8)
    models = {name: new_model() for name in (
        "pooled", "long_only", "short_only", "pooled_interactions"
    )}
    models["pooled"].fit(xtr, ytr)
    for dr, name in ((1, "long_only"), (-1, "short_only")):
        m = dtr == dr
        models[name].fit(xtr[m], ytr[m])
    xtr_int = interaction_matrix(train, xtr)
    models["pooled_interactions"].fit(xtr_int, ytr)
    del xtr_int, xtr, ytr, dtr, train
    gc.collect()

    selection_metrics, _ = structure_metrics(models, selection, "2025_H1_selection")
    selected, comparison = select_structure(selection_metrics)
    raw_cal = raw_scores(models, selected, calibration)
    calibrators, calibrated, thresholds = calibrate_and_threshold(raw_cal, calibration)
    calibration_metrics = []
    ycal = calibration["target"].to_numpy(dtype=np.int8)
    dcal = calibration["direction"].to_numpy()
    for dr, label in ((1, "prevailing_long"), (-1, "prevailing_short")):
        m = dcal == dr
        calibration_metrics.append({
            **metric_row(selected, label, ycal[m], calibrated[m]),
            "window": "2025_H2_calibration", "calibrated": True,
        })
    distribution = score_distribution_and_crossings(
        calibration, calibrated, thresholds, "2025_H2_calibration"
    )

    # Apply the already-frozen structure/calibrators to all of 2025 only for
    # development reporting and the later 2025 policy simulation. H1 remains
    # the structure-selection window and H2 remains the calibration window.
    raw_val = raw_scores(models, selected, val)
    val_direction = val["direction"].to_numpy(dtype=np.int8)
    calibrated_val = apply_calibration(raw_val, val_direction, calibrators)
    full_year_distribution = score_distribution_and_crossings(
        val, calibrated_val, thresholds, "2025_full_development"
    )

    sm = selection_metrics[selection_metrics["model"] == selected].set_index("segment")
    cross_rates = distribution.set_index("direction")["strict_cross_regime_rate"]
    balance_ratio = float(
        cross_rates.max() / cross_rates.min()
        if cross_rates.min() > 0 else np.inf
    )
    gate = {
        "selected_structure": selected,
        "selection_auc_long": float(sm.loc["prevailing_long", "roc_auc"]),
        "selection_auc_short": float(sm.loc["prevailing_short", "roc_auc"]),
        "finite_score_rate_long": float(distribution.set_index("direction").loc[1, "finite_score_rate"]),
        "finite_score_rate_short": float(distribution.set_index("direction").loc[-1, "finite_score_rate"]),
        "cross_rate_long": float(cross_rates.loc[1]),
        "cross_rate_short": float(cross_rates.loc[-1]),
        "cross_rate_balance_ratio": balance_ratio,
    }
    gate["pass"] = bool(
        gate["selection_auc_long"] > 0.50
        and gate["selection_auc_short"] > 0.50
        and gate["finite_score_rate_long"] >= 0.99
        and gate["finite_score_rate_short"] >= 0.99
        and gate["cross_rate_long"] > 0
        and gate["cross_rate_short"] > 0
        and gate["cross_rate_balance_ratio"] <= 2.0
    )

    with BUNDLE_PATH.open("wb") as f:
        pickle.dump({
            "models": models, "selected_structure": selected,
            "base_features": BASE_FEATURES,
            "interaction_local": INTERACTION_LOCAL,
            "calibrators": calibrators, "thresholds": thresholds,
            "seed": SEED,
        }, f)

    pd.concat([selection_metrics, pd.DataFrame(calibration_metrics)],
              ignore_index=True).to_parquet(
        RESULTS / "CODEX_5_X_model_structure_comparison_2025.parquet", index=False)
    comparison.to_parquet(
        RESULTS / "CODEX_5_X_model_selection_candidates.parquet", index=False)
    pd.concat([distribution, full_year_distribution], ignore_index=True).to_parquet(
        RESULTS / "CODEX_5_X_w4_score_distribution_crossings_2025.parquet", index=False)
    score_frame(calibration, calibrated, thresholds).to_parquet(
        RESULTS / "CODEX_5_X_repaired_w4_scores_2025_H2.parquet", index=False)
    score_frame(val, calibrated_val, thresholds).to_parquet(
        RESULTS / "CODEX_5_X_repaired_w4_scores_2025.parquet", index=False)

    manifest = {
        "status": (
            "FROZEN_PRE_2026_GATE_PASSED"
            if gate["pass"] else "FAILED_PRE_2026_GATE"
        ),
        "train_years": list(TRAIN_YEARS),
        "selection_window": "2025-01-01..2025-06-30",
        "calibration_window": "2025-07-01..2025-12-31",
        "selected_structure": selected,
        "selection_rule": "macro directional ROC-AUC; within 0.005 prefer smaller directional gap then simpler pooled",
        "calibration": "direction-specific isotonic on 2025-H2",
        "threshold_definition": "direction-specific P90 calibrated score on 2025-H2",
        "thresholds": {str(k): v for k, v in thresholds.items()},
        "boundary_purge": purge,
        "base_feature_count": len(BASE_FEATURES),
        "interaction_features": ["direction"] + [f"direction_x_{f}" for f in INTERACTION_LOCAL],
        "atr_contract": {
            "local_excursion_denominator": "atr_at_entry",
            "checkpoint_context_atr": "atr_at_checkpoint",
            "legacy_atr_alias": "atr_at_checkpoint",
        },
        "gate": gate,
        "bundle_sha256": sha256_file(BUNDLE_PATH),
        "repaired_atlas_sha256": {
            str(year): sha256_file(year_atlas_path(year))
            for year in (*TRAIN_YEARS, 2025)
        },
        "dependency_sha256": {
            rel: sha256_file(ROOT / rel)
            for rel in REQUIRED_DEPENDENCY_RELATIVE
        },
        "no_2026_access": True,
    }
    write_json(MANIFEST_PATH, manifest)
    report = f"""# CODEX 5.X — Repaired W4 Freeze Report

Selected structure: `{selected}`

Pre-2026 W4 gate: `{'PASS' if gate['pass'] else 'FAIL'}`

## Structure comparison (2025-H1)

{selection_metrics.round(6).to_markdown(index=False)}

## Candidate selection summary

{comparison.round(6).to_markdown(index=False)}

## H1/H2 regime-boundary purge

`{json.dumps(purge, sort_keys=True)}`

## Calibrated score distributions and crossings (2025-H2)

{distribution.round(6).to_markdown(index=False)}

## Frozen-model score distributions and crossings (full 2025 development year)

{full_year_distribution.round(6).to_markdown(index=False)}

Thresholds: prevailing long `{thresholds[1]:.12f}`, prevailing short
`{thresholds[-1]:.12f}`.

No 2026 atlas, label, score, or metric was accessed during this freeze.
"""
    (RESULTS / "CODEX_5_X_repaired_w4_freeze_report.md").write_text(
        report, encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def evaluate_2026() -> None:
    manifest = require_frozen_pre_2026_contract("evaluate repaired W4 on 2026")
    with BUNDLE_PATH.open("rb") as f:
        bundle = pickle.load(f)
    if (bundle["base_features"] != BASE_FEATURES
            or bundle["interaction_local"] != INTERACTION_LOCAL):
        raise RuntimeError("current feature definitions differ from frozen bundle")
    d = load_years([2026])
    x = base_matrix(d, bundle["base_features"])
    raw = raw_scores(
        bundle["models"], bundle["selected_structure"], d, x,
        bundle["base_features"], bundle["interaction_local"],
    )
    direction = d["direction"].to_numpy(dtype=np.int8)
    calibrated = apply_calibration(raw, direction, bundle["calibrators"])
    thresholds = bundle["thresholds"]
    distribution = score_distribution_and_crossings(
        d, calibrated, thresholds, "2026_final_test"
    )
    y = d["target"].to_numpy(dtype=np.int8)
    rows = []
    for dr, label in ((1, "prevailing_long"), (-1, "prevailing_short")):
        m = direction == dr
        rows.append({**metric_row(bundle["selected_structure"], label,
                                  y[m], calibrated[m]),
                     "window": "2026_final_test", "calibrated": True})
    pd.DataFrame(rows).to_parquet(
        RESULTS / "CODEX_5_X_model_metrics_2026.parquet", index=False)
    distribution.to_parquet(
        RESULTS / "CODEX_5_X_w4_score_distribution_crossings_2026.parquet", index=False)
    score_frame(d, calibrated, thresholds).to_parquet(
        RESULTS / "CODEX_5_X_repaired_w4_scores_2026.parquet", index=False)
    report = f"""# CODEX 5.X — Repaired W4 2026 Final Test

The frozen structure, calibrators, and thresholds were loaded without change.
No 2026 value altered the manifest.

## Directional model metrics

{pd.DataFrame(rows).round(6).to_markdown(index=False)}

## Score distributions and strict crossings

{distribution.round(6).to_markdown(index=False)}
"""
    (RESULTS / "CODEX_5_X_repaired_w4_2026_report.md").write_text(
        report, encoding="utf-8")
    print(report)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--evaluate-2026", action="store_true")
    args = ap.parse_args()
    if args.freeze == args.evaluate_2026:
        raise SystemExit("choose exactly one of --freeze or --evaluate-2026")
    if args.freeze:
        train_and_freeze()
    else:
        evaluate_2026()


if __name__ == "__main__":
    main()
