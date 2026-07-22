from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from sklearn.calibration import calibration_curve
from sklearn.inspection import permutation_importance
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             confusion_matrix, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score,
                             roc_curve)

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
RESULTS = STUDY / "results"
CFG = yaml.safe_load((STUDY / "config.yaml").read_text())
TARGET_B = "bearish_regime_flip_within_300s"
TARGET_L = "bullish_regime_flip_within_300s"
KEY = ["regime_start_ns", "observation_time"]

BULL_ART = ROOT / "studies/freeze_reduced_flip_model_artifacts/artifacts/short_bearish_flip_top25_current_reference"
BULL_CORRECT = ROOT / "studies/short_rth_pure_flip_prediction_enriched/_work/prepared_2025.parquet"
BULL_LEGACY = ROOT / "studies/short_rth_enriched_volume_level_retrain/_work/prepared_2025.parquet"
BULL_CORRECT_2024 = ROOT / "studies/short_rth_pure_flip_prediction_enriched/_work/prepared_2024.parquet"
BULL_LEGACY_2024 = ROOT / "studies/short_rth_enriched_volume_level_retrain/_work/prepared_2024.parquet"
BEAR_ART = ROOT / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top103_gbt_v2"
BEAR_WORK = ROOT / "studies/long_rth_strict_symmetric_retrain/_work/monthly/2025"
BEAR_ATTACHED = ROOT / "studies/long_rth_mirrored_surface_top100_training/_work/attached_long_2025.parquet"
RAW = ROOT / "data/raw/NQ_v0_1s_2025.parquet"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def assert_keys(df: pd.DataFrame, name: str) -> None:
    if df[KEY].isna().any().any() or df.duplicated(KEY).any():
        raise RuntimeError(f"{name}: null or duplicate checkpoint key")


def assert_same_keys(left: pd.DataFrame, right: pd.DataFrame, left_name: str, right_name: str) -> None:
    assert_keys(left, left_name); assert_keys(right, right_name)
    a = pd.MultiIndex.from_frame(left[KEY]); b = pd.MultiIndex.from_frame(right[KEY])
    if len(a) != len(b) or not a.equals(b):
        missing_right = len(a.difference(b)); missing_left = len(b.difference(a))
        raise RuntimeError(f"checkpoint coverage mismatch {left_name}/{right_name}: "
                           f"rows={len(a)}/{len(b)}, missing_right={missing_right}, missing_left={missing_left}")


def feature_order(path: Path) -> list[str]:
    csv = path / "feature_order.csv"
    if csv.exists():
        return pd.read_csv(csv)["feature_name"].tolist()
    return json.loads((path / "feature_list.json").read_text())


def score(model, df: pd.DataFrame, features: list[str]) -> np.ndarray:
    return model.predict_proba(df[features])[:, 1]


def metric_row(name: str, y: np.ndarray, p: np.ndarray) -> dict:
    prevalence = float(np.mean(y))
    threshold = float(np.quantile(p, 1.0 - prevalence))
    pred = p >= threshold
    return {
        "model": name, "rows": len(y), "prevalence": prevalence,
        "roc_auc": float(roc_auc_score(y, p)),
        "average_precision": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "threshold_prevalence_matched": threshold,
        "precision_prevalence_matched": float(precision_score(y, pred)),
        "recall_prevalence_matched": float(recall_score(y, pred)),
    }


def calibration_rows(name: str, y: np.ndarray, p: np.ndarray) -> list[dict]:
    observed, predicted = calibration_curve(y, p, n_bins=CFG["calibration_bins"], strategy="quantile")
    bins = pd.qcut(pd.Series(p), CFG["calibration_bins"], duplicates="drop")
    counts = bins.value_counts(sort=False).to_numpy()
    return [{"model": name, "bin": i + 1, "count": int(counts[i]),
             "mean_probability": float(predicted[i]), "observed_rate": float(observed[i])}
            for i in range(len(observed))]


def lift_rows(name: str, y: np.ndarray, p: np.ndarray) -> list[dict]:
    base = float(np.mean(y)); out = []
    for pct in CFG["lift_percentiles"]:
        q = float(np.quantile(p, 1 - pct / 100)); mask = p >= q
        rate = float(np.mean(y[mask]))
        out.append({"model": name, "top_pct": pct, "threshold": q,
                    "rows": int(mask.sum()), "positive_rate": rate,
                    "lift": rate / base})
    return out


def curves(name: str, y: np.ndarray, p: np.ndarray) -> None:
    fpr, tpr, _ = roc_curve(y, p); precision, recall, _ = precision_recall_curve(y, p)
    pd.DataFrame({"fpr": fpr, "tpr": tpr}).to_csv(RESULTS / f"roc_curve_{name}.csv", index=False)
    pd.DataFrame({"recall": recall, "precision": precision}).to_csv(RESULTS / f"pr_curve_{name}.csv", index=False)
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].plot(fpr, tpr); ax[0].plot([0, 1], [0, 1], "--", color="gray")
    ax[0].set(xlabel="FPR", ylabel="TPR", title=f"{name} ROC")
    ax[1].plot(recall, precision); ax[1].set(xlabel="Recall", ylabel="Precision", title=f"{name} PR")
    fig.tight_layout(); fig.savefig(RESULTS / f"curves_{name}.png", dpi=150); plt.close(fig)


def confusion_rows(event: str, y: np.ndarray, z: np.ndarray) -> list[dict]:
    cm = confusion_matrix(y.astype(int), z.astype(int), labels=[0, 1])
    return [{"comparison": event, "actual": a, "comparison_event": b, "count": int(cm[a, b])}
            for a in (0, 1) for b in (0, 1)]


def prediction_confusions(name: str, y: np.ndarray, p: np.ndarray) -> list[dict]:
    prevalence_threshold = float(np.quantile(p, 1.0 - np.mean(y)))
    out = []
    for label, threshold in (("probability_0_5", .5), ("prevalence_matched", prevalence_threshold)):
        for row in confusion_rows(f"{name}_{label}", y, p >= threshold):
            row["threshold"] = threshold; out.append(row)
    return out


def historical_replay(model, features: list[str]) -> pd.DataFrame:
    published_rates = {1.0: .080, 2.5: .072, 5.0: .061}
    frames = []
    for year, correct_path, legacy_path in ((2024, BULL_CORRECT_2024, BULL_LEGACY_2024),
                                             (2025, BULL_CORRECT, BULL_LEGACY)):
        correct = pd.read_parquet(correct_path); legacy = pd.read_parquet(legacy_path)
        local = pd.to_datetime(correct.observation_time, unit="ns", utc=True).dt.tz_convert("America/Chicago")
        rth = (local.dt.time >= pd.Timestamp("08:30:00").time()) & (local.dt.time < pd.Timestamp("15:15:00").time())
        correct = correct.loc[rth].reset_index(drop=True); legacy = legacy.loc[rth].reset_index(drop=True)
        assert_same_keys(correct, legacy, f"corrected {year}", f"legacy {year}")
        seconds = (legacy.exit_ts.to_numpy() - legacy.observation_time.to_numpy()) / 1e9
        legacy_event = legacy.hit_opposing_flip.astype(bool).to_numpy() & (seconds > 0) & (seconds <= 300)
        frames.append(pd.DataFrame({"year": year, "regime_start_ns": correct.regime_start_ns,
            "observation_time": correct.observation_time, "score": score(model, correct, features),
            "training_target": correct[TARGET_B].astype(int), "legacy_reliability_event": legacy_event,
            "seconds_to_true_flip": (correct.confirm_flip_ns-correct.observation_time)/1e9}))
    d = pd.concat(frames, ignore_index=True).sort_values("observation_time")
    rows = []
    for pct in CFG["lift_percentiles"]:
        threshold = float(np.quantile(d.score, 1-pct/100))
        first = d[d.score >= threshold].groupby("regime_start_ns", as_index=False).first()
        published = published_rates.get(float(pct), np.nan)
        rows.append({"top_pct": pct, "threshold": threshold, "signals": len(first),
                     "training_target_rate": float(first.training_target.mean()),
                     "legacy_reliability_event_rate": float(first.legacy_reliability_event.mean()),
                     "published_legacy_event_rate": published,
                     "replay_minus_published": float(first.legacy_reliability_event.mean()-published) if np.isfinite(published) else np.nan,
                     "median_seconds_to_true_flip": float(first.seconds_to_true_flip.median()),
                     "training_target_positives": int(first.training_target.sum()),
                     "legacy_event_positives": int(first.legacy_reliability_event.sum())})
    return pd.DataFrame(rows)


def load_bearish() -> tuple[pd.DataFrame, object, list[str]]:
    monthly = sorted(BEAR_WORK.glob("*.parquet"))
    if len(monthly) != 12:
        raise RuntimeError("strict Bearish 2025 monthly population incomplete")
    d = pd.concat((pd.read_parquet(p) for p in monthly), ignore_index=True)
    attached = pd.read_parquet(BEAR_ATTACHED, columns=KEY + ["confirm_flip_ns", "fill_px", "atr_at_entry"])
    assert_same_keys(d[KEY], attached[KEY], "bearish monthly", "bearish attached")
    d = d.merge(attached, on=KEY, how="left", validate="one_to_one")
    assert_keys(d, "bearish")
    if d[["confirm_flip_ns", "fill_px", "atr_at_entry"]].isna().any().any():
        raise RuntimeError("bearish attachment has missing timing/economic fields")
    return d, joblib.load(BEAR_ART / "model.joblib"), feature_order(BEAR_ART)


def manual_trace(bull: pd.DataFrame) -> None:
    rows = []
    for label in (1, 0):
        part = bull[bull[TARGET_B].astype(int) == label].sort_values(KEY).head(CFG["manual_trace_per_class"])
        for _, r in part.iterrows():
            seconds = (int(r.confirm_flip_ns) - int(r.observation_time)) / 1e9
            arithmetic = int(seconds <= 300.0)
            rows.append({"expected_class": label, "regime_start_ns": int(r.regime_start_ns),
                         "observation_time": int(r.observation_time), "confirm_flip_ns": int(r.confirm_flip_ns),
                         "seconds_to_confirmed_flip": seconds, "stored_label": int(r[TARGET_B]),
                         "arithmetic_label": arithmetic, "verified": arithmetic == int(r[TARGET_B])})
    out = pd.DataFrame(rows)
    if len(out) != 100 or not out.verified.all():
        raise RuntimeError("manual 50-positive/50-negative trace failed")
    out.to_csv(RESULTS / "manual_target_trace_100.csv", index=False)


def economic_rows(df: pd.DataFrame, direction: str) -> pd.DataFrame:
    bars = pd.read_parquet(RAW, columns=["open", "high", "low", "close"])
    if bars.index.name == "ts_event":
        ts = bars.index.astype("int64").to_numpy()
    else:
        ts = pd.to_datetime(bars.pop("ts_event"), utc=True).astype("int64").to_numpy()
    if len(ts) < 2 or np.any(np.diff(ts) <= 0):
        raise RuntimeError("raw one-second timestamps must be strictly increasing and unique")
    high, low, close = (bars[c].to_numpy() for c in ("high", "low", "close"))
    out = []
    positives = df[df["target"].astype(bool)]
    for r in positives.itertuples(index=False):
        start = int(np.searchsorted(ts, r.observation_time, side="right"))
        end = int(np.searchsorted(ts, r.confirm_flip_ns, side="left"))
        if end <= start or start >= len(ts):
            continue
        h = float(np.max(high[start:end])); l = float(np.min(low[start:end])); terminal = float(close[end - 1])
        if direction == "bullish_fade":
            rem_prev_mfe = h - r.entry_px; rem_mae = r.entry_px - l
            pnl = r.entry_px - terminal; dist_regime_high = h - r.entry_px
        else:
            rem_prev_mfe = r.entry_px - l; rem_mae = h - r.entry_px
            pnl = terminal - r.entry_px; dist_regime_high = r.entry_px - l
        out.append({"model": direction, "regime_start_ns": r.regime_start_ns,
                    "observation_time": r.observation_time, "seconds_to_flip": r.seconds_to_flip,
                    "remaining_prevailing_mfe_points": max(0.0, rem_prev_mfe),
                    "remaining_mae_points": max(0.0, rem_mae), "exit_pnl_points_mark": pnl,
                    "distance_from_terminal_extreme_points": max(0.0, dist_regime_high),
                    "remaining_prevailing_mfe_atr": max(0.0, rem_prev_mfe) / r.atr,
                    "remaining_mae_atr": max(0.0, rem_mae) / r.atr,
                    "exit_pnl_atr_mark": pnl / r.atr})
    return pd.DataFrame(out)


def explain(name: str, model, df: pd.DataFrame, features: list[str], target: str) -> None:
    sample = df.sample(min(CFG["shap_sample_rows"], len(df)), random_state=CFG["random_seed"])
    X = sample[features]
    perm = permutation_importance(model, X, sample[target].astype(int), scoring="roc_auc",
                                  n_repeats=3, random_state=CFG["random_seed"], n_jobs=-1)
    imp = pd.DataFrame({"model": name, "feature": features,
                        "permutation_auc_mean": perm.importances_mean,
                        "permutation_auc_std": perm.importances_std}).sort_values("permutation_auc_mean", ascending=False)
    imp.to_csv(RESULTS / f"feature_importance_{name}.csv", index=False)
    try:
        import shap
        sx = X.sample(min(1000, len(X)), random_state=CFG["random_seed"])
        values = shap.TreeExplainer(model).shap_values(sx)
        if isinstance(values, list): values = values[-1]
        values = np.asarray(values)
        long = pd.DataFrame(values, columns=features).assign(sample_row=sx.index.to_numpy()).melt(
            id_vars="sample_row", var_name="feature", value_name="shap_value")
        long.insert(0, "model", name)
        long.to_csv(RESULTS / f"shap_distribution_{name}.csv", index=False)
        quant = long.groupby(["model", "feature"]).shap_value.quantile([.01,.05,.25,.5,.75,.95,.99]).unstack()
        quant.columns = [f"q{int(q*100):02d}" for q in quant.columns]
        quant.reset_index().to_csv(RESULTS / f"shap_quantiles_{name}.csv", index=False)
        mapper = getattr(model, "_bin_mapper", None)
        saturation = []
        for i, c in enumerate(features):
            thresholds = np.asarray(mapper.bin_thresholds_[i]) if mapper is not None else np.array([])
            if len(thresholds):
                saturation.append(float(((sx[c] <= thresholds[0]) | (sx[c] > thresholds[-1])).mean()))
            else:
                saturation.append(1.0)
        sv = pd.DataFrame({"model": name, "feature": features,
                           "mean_abs_shap": np.abs(values).mean(axis=0),
                           "mean_shap": np.asarray(values).mean(axis=0),
                           "feature_min": sx.min().to_numpy(), "feature_max": sx.max().to_numpy(),
                           "outer_model_bin_rate": saturation})
        sv.sort_values("mean_abs_shap", ascending=False).to_csv(RESULTS / f"shap_summary_{name}.csv", index=False)
    except Exception as exc:
        (RESULTS / f"shap_unavailable_{name}.txt").write_text(f"{type(exc).__name__}: {exc}\n")


def write_reports(metrics: pd.DataFrame, lifts: pd.DataFrame, event: pd.DataFrame,
                  timing: pd.DataFrame, econ: pd.DataFrame, parity: dict, replay: pd.DataFrame) -> None:
    b = metrics.query("model == 'bullish_fade'").iloc[0]
    l = metrics.query("model == 'bearish_fade_top103'").iloc[0]
    legacy = metrics.query("model == 'bullish_scores_vs_legacy_event'").iloc[0]
    legacy_disagree = float((event.training_target != event.legacy_reliability_event).mean())
    fn = int(((event.training_target == 1) & (event.legacy_reliability_event == 0)).sum())
    tp = int(((event.training_target == 1) & (event.legacy_reliability_event == 1)).sum())
    recall = tp / (tp + fn)
    replay25 = replay.query("top_pct == 2.5").iloc[0]
    gate = CFG["classification"]
    classification_b = (abs(b.roc_auc - gate["published_bullish_auc"]) <= gate["reproduction_auc_tolerance"] and
                        legacy_disagree >= gate["minimum_event_disagreement"] and
                        recall < gate["maximum_legacy_recall_of_training_positives"] and
                        replay25.training_target_rate >= gate["minimum_original_top_2_5pct_positive_rate"] and
                        replay25.legacy_reliability_event_rate <= gate["maximum_legacy_top_2_5pct_positive_rate"])
    econ_b = econ.query("model == 'bullish_fade'")
    classification_c = (not classification_b and
                        b.roc_auc >= gate["minimum_original_target_predictive_auc"] and
                        econ_b.exit_pnl_atr_mark.median() <= gate["economically_weak_median_exit_pnl_atr"])
    classification_d = (not classification_b and not classification_c and
                        legacy_disagree < gate["minimum_event_disagreement"] and
                        l.roc_auc - b.roc_auc >= gate["market_asymmetry_minimum_auc_gap"])
    if classification_b:
        code, classification = "B", "B — Training label differs from evaluation event"
        causal = ("The model is genuinely predictive of its original checkpoint target, but the historical reliability "
                  "event is policy-conditioned and quantitatively recreates the apparent collapse.")
        action = ("Join scores to the corrected pure-flip population by `(regime_start_ns, observation_time)` and use "
                  "`confirm_flip_ns` directly. Do not retrain to repair this evaluation defect.")
    elif classification_c:
        code, classification = "C", "C — Model predicts training label correctly but target is economically weak"
        causal = "The original target is predicted, but its median fade-direction checkpoint-to-flip mark is non-positive."
        action = "Redefine the economic target contract before considering retraining; do not tune the current evaluation event."
    elif classification_d:
        code, classification = "D", "D — Bullish regimes provide weaker imminent-flip information"
        causal = "Event definitions agree closely, while the Bearish comparator has the predeclared material AUC advantage."
        action = "Treat the asymmetry as a market-information limitation and specify a new target before retraining."
    else:
        code, classification = "E", "E — Other"
        causal = "No predeclared A-D rule passes; the evidence does not support a narrower causal claim."
        action = "Do not retrain; investigate the failed classification gates and expand the study contract first."
    summary = (
        f"Bullish frozen predictions reproduce bit-exactly ({parity['bullish_max_abs_diff']:.1f} max difference). "
        f"On the original 2025 target, AUC={b.roc_auc:.5f}, AP={b.average_precision:.5f}, Brier={b.brier:.5f}. "
        f"The historical reliability event disagrees with the training target on {legacy_disagree:.1%} of checkpoints "
        f"and captures only {recall:.1%} of true <=300s flips. Scoring that legacy event gives "
        f"AUC={legacy.roc_auc:.5f}, AP={legacy.average_precision:.5f}. In the exact historical 2024–2025 "
        f"first-signal replay, top-2.5% event rate is {replay25.legacy_reliability_event_rate:.1%} (published 7.2%; "
        f"difference {replay25.replay_minus_published:+.1%}), versus {replay25.training_target_rate:.1%} on the original target."
    )
    (STUDY / "model_reproduction_report.md").write_text(
        "# Model Reproduction Report\n\n" + summary +
        "\n\nThe published Bullish AUC 0.67099 is reproduced within floating-point tolerance; "
        "the artifact-to-frozen-reference predictions are bit-exact. AP, Brier, calibration, confusion matrices, "
        "lift and curves were recomputed because the upstream freeze report did not publish all of them.\n\n" +
        metrics.to_markdown(index=False) + "\n")
    (STUDY / "training_target_contract.md").write_text(
        "# Training Target Contract\n\nBullish candidates are established bullish (`+1`) RTH regimes sampled every five seconds. "
        "The observation timestamp is `observation_time`; the event timestamp is the already-confirmed next opposing "
        "regime transition `confirm_flip_ns`. A positive is exactly `0 < confirm_flip_ns-observation_time <= 300s`; "
        "a negative is a later confirmed flip. Confirmation comes from the upstream regime tracker, not a trade exit. "
        "All 100 deterministic manual traces pass; see `results/manual_target_trace_100.csv`. The frozen lineage carries "
        "a separate disclosed one-second feature look-ahead from open-labelled OHLCV attachment.\n")
    comparison = f"""# Bullish vs Bearish Fade Comparison

{summary}

| Model | ROC-AUC | AP | Brier | Base rate |
|---|---:|---:|---:|---:|
| Bullish Fade Top25 V1 | {b.roc_auc:.5f} | {b.average_precision:.5f} | {b.brier:.5f} | {b.prevalence:.3f} |
| Bearish Fade Top103 V2 | {l.roc_auc:.5f} | {l.average_precision:.5f} | {l.brier:.5f} | {l.prevalence:.3f} |
| Bullish scores vs legacy reliability event | {legacy.roc_auc:.5f} | {legacy.average_precision:.5f} | {legacy.brier:.5f} | {legacy.prevalence:.3f} |

The first demonstrated asymmetry is evaluation construction: Bearish Fade uses the strict pure confirmed-flip event,
while the historical Bullish reliability run replaced missing `confirm_flip_ns` with a policy-conditioned
`hit_opposing_flip/exit_ts` event. Feature-importance and SHAP summaries are in `results/`.
"""
    (STUDY / "bullish_vs_bearish_fade_comparison.md").write_text(comparison)
    (STUDY / "economic_value_analysis.md").write_text(
        "# Economic Value Analysis\n\nThese are non-executable marks strictly between checkpoint and confirmed flip. "
        f"For Bullish positives, median remaining prevailing MFE is {econ_b.remaining_prevailing_mfe_atr.median():.3f} ATR, "
        f"median adverse excursion for a short is {econ_b.remaining_mae_atr.median():.3f} ATR, and median checkpoint-to-flip "
        f"short mark PnL is {econ_b.exit_pnl_atr_mark.median():.3f} ATR. No slippage, fill latency, or commissions are modeled.\n")
    root = f"""# Root Cause Report

## Classification: {classification}

{summary}

The predeclared gates select **{code}**. {causal} The original target is the next confirmed bearish regime flip within
300 seconds; the historical reliability event was reconstructed from an older trade-policy outcome and assigns no
flip whenever that simulated policy did not survive to `hit_opposing_flip`. This creates {fn:,} false negatives
against the actual training target in 2025.

The disclosed one-second Bullish feature look-ahead is a secondary model-validity defect, but it does not explain the
        large reliability collapse. {action} For production validity, the one-second
attachment defect must subsequently be removed and the existing model rebuilt under the strict causal feature contract.

## Executive answers

1. Yes: ROC-AUC reproduces at {b.roc_auc:.5f}; artifact predictions are bit-exact. AP is {b.average_precision:.5f}.
2. {'Yes, for its original target.' if b.roc_auc >= .60 else 'No; original-target discrimination is insufficient.'}
3. {'No.' if legacy_disagree > 0 else 'Yes.'}
4. The reliability event is conditioned on an older simulated trade surviving to an opposing-flip exit.
5. Not applicable; they are not identical.
6. Primary classification: {classification}. Secondary defect: one-second feature look-ahead.
7. {action}
"""
    (STUDY / "root_cause_report.md").write_text(root)


def main() -> None:
    if any("2026" in str(p) for p in [BULL_CORRECT, BULL_LEGACY, BEAR_WORK, BEAR_ATTACHED, RAW]):
        raise RuntimeError("sealed 2026 path in active inputs")
    RESULTS.mkdir(parents=True, exist_ok=True)
    bull = pd.read_parquet(BULL_CORRECT); legacy = pd.read_parquet(BULL_LEGACY)
    assert_same_keys(bull, legacy, "bullish corrected", "bullish legacy")
    bm = joblib.load(BULL_ART / "model.joblib"); bf = feature_order(BULL_ART)
    bp = score(bm, bull, bf)
    frozen = pd.read_parquet(BULL_ART / "score_reference_2025.parquet")
    assert_same_keys(bull[KEY], frozen[KEY], "bullish prepared", "bullish frozen reference")
    check = frozen.merge(pd.DataFrame({**{k: bull[k] for k in KEY}, "recomputed": bp}), on=KEY, validate="one_to_one")
    maxdiff = float(np.max(np.abs(check.score - check.recomputed)))
    if maxdiff != 0.0:
        raise RuntimeError(f"Bullish prediction parity failed: {maxdiff}")
    delta_bull = (bull.confirm_flip_ns - bull.observation_time) / 1e9
    if not (delta_bull > 0).all():
        raise RuntimeError("Bullish confirmed flip must be strictly after observation")
    arithmetic = (delta_bull <= 300.0).astype(int)
    if not np.array_equal(arithmetic.to_numpy(), bull[TARGET_B].astype(int).to_numpy()):
        raise RuntimeError("Bullish label arithmetic mismatch")
    observed_auc = float(roc_auc_score(arithmetic, bp))
    class_cfg = CFG["classification"]
    if abs(observed_auc - class_cfg["published_bullish_auc"]) > class_cfg["reproduction_auc_tolerance"]:
        raise RuntimeError("CLASSIFICATION_A_MODEL_REPRODUCTION_FAILURE: "
                           f"published_auc={class_cfg['published_bullish_auc']}, observed_auc={observed_auc}")
    manual_trace(bull)

    legacy_hit = legacy.hit_opposing_flip.astype(bool).to_numpy()
    legacy_seconds = (legacy.exit_ts.to_numpy() - legacy.observation_time.to_numpy()) / 1e9
    legacy_event = legacy_hit & (legacy_seconds > 0.0) & (legacy_seconds <= 300.0)
    legacy_confirm = np.where(legacy_hit, legacy.exit_ts, np.nan)
    joined = bull[KEY + [TARGET_B, "confirm_flip_ns"]].merge(
        pd.DataFrame({**{k: legacy[k] for k in KEY}, "legacy_hit_opposing_flip": legacy_hit,
                      "legacy_reliability_event": legacy_event,
                      "legacy_event_ts": legacy_confirm}), on=KEY, validate="one_to_one")
    if len(joined) != len(bull):
        raise RuntimeError("Bullish corrected/legacy join lost checkpoints")
    joined = joined.rename(columns={TARGET_B: "training_target"})
    joined["flip_within_300_seconds"] = joined.training_target
    joined["flip_within_600_seconds"] = ((joined.confirm_flip_ns - joined.observation_time) / 1e9 <= 600).astype(int)
    joined["actual_confirmed_bearish_flip"] = 1
    joined["seconds_to_confirmed_flip"] = (joined.confirm_flip_ns - joined.observation_time) / 1e9
    joined.to_csv(STUDY / "target_vs_reliability_comparison.csv", index=False)
    pd.DataFrame(confusion_rows("training_target_vs_300s", joined.training_target.to_numpy(), joined.flip_within_300_seconds.to_numpy()) +
                 confusion_rows("training_target_vs_legacy_reliability", joined.training_target.to_numpy(), joined.legacy_reliability_event.to_numpy())).to_csv(RESULTS / "event_confusion_matrices.csv", index=False)

    bear, lm, lf = load_bearish(); lp = score(lm, bear, lf)
    fixture = pd.read_parquet(BEAR_ART / "validation_fixture.parquet")
    expected_fixture = np.load(BEAR_ART / "validation_fixture_scores.npy")
    actual_fixture = score(lm, fixture, lf)
    bear_maxdiff = float(np.max(np.abs(expected_fixture - actual_fixture)))
    if bear_maxdiff != 0.0:
        raise RuntimeError(f"Bearish fixture prediction parity failed: {bear_maxdiff}")
    metrics = pd.DataFrame([metric_row("bullish_fade", arithmetic.to_numpy(), bp),
                            metric_row("bearish_fade_top103", bear[TARGET_L].astype(int).to_numpy(), lp),
                            metric_row("bullish_scores_vs_legacy_event", legacy_event.astype(int), bp)])
    metrics.to_csv(RESULTS / "model_metrics.csv", index=False)
    pd.DataFrame(prediction_confusions("bullish_fade", arithmetic.to_numpy(), bp) +
                 prediction_confusions("bearish_fade_top103", bear[TARGET_L].astype(int).to_numpy(), lp) +
                 prediction_confusions("bullish_scores_vs_legacy_event", legacy_event.astype(int), bp)).to_csv(
                     RESULTS / "model_prediction_confusion_matrices.csv", index=False)
    cal = pd.DataFrame(calibration_rows("bullish_fade", arithmetic.to_numpy(), bp) +
                       calibration_rows("bearish_fade_top103", bear[TARGET_L].astype(int).to_numpy(), lp) +
                       calibration_rows("bullish_scores_vs_legacy_event", legacy_event.astype(int), bp))
    cal.to_csv(RESULTS / "calibration.csv", index=False)
    lifts = pd.DataFrame(lift_rows("bullish_fade", arithmetic.to_numpy(), bp) +
                         lift_rows("bearish_fade_top103", bear[TARGET_L].astype(int).to_numpy(), lp) +
                         lift_rows("bullish_scores_vs_legacy_event", legacy_event.astype(int), bp))
    lifts.to_csv(RESULTS / "lift.csv", index=False)
    curves("bullish_fade", arithmetic.to_numpy(), bp); curves("bearish_fade_top103", bear[TARGET_L].astype(int).to_numpy(), lp)
    curves("bullish_scores_vs_legacy_event", legacy_event.astype(int), bp)
    replay = historical_replay(bm, bf)
    replay.to_csv(RESULTS / "historical_reliability_replay.csv", index=False)

    timing = pd.concat([
        pd.DataFrame({"model": "bullish_fade", "seconds_to_training_event": (bull.confirm_flip_ns-bull.observation_time)/1e9,
                      "seconds_to_confirmed_flip": (bull.confirm_flip_ns-bull.observation_time)/1e9, "positive": arithmetic}),
        pd.DataFrame({"model": "bearish_fade_top103", "seconds_to_training_event": (bear.confirm_flip_ns-bear.observation_time)/1e9,
                      "seconds_to_confirmed_flip": (bear.confirm_flip_ns-bear.observation_time)/1e9,
                      "positive": bear[TARGET_L].astype(int)})], ignore_index=True)
    dist = timing[timing.positive == 1].groupby("model")[["seconds_to_training_event", "seconds_to_confirmed_flip"]].agg(
        ["count", "median", lambda x: x.quantile(.90), lambda x: x.quantile(.95)])
    dist.columns = ["_".join([a, {"<lambda_0>": "p90", "<lambda_1>": "p95"}.get(b, b)]) for a, b in dist.columns]
    dist.reset_index().to_csv(STUDY / "event_timing_distribution.csv", index=False)

    bull_e = pd.DataFrame({"regime_start_ns": bull.regime_start_ns, "observation_time": bull.observation_time,
                           "confirm_flip_ns": bull.confirm_flip_ns, "entry_px": bull.entry_px,
                           "atr": bull.atr_at_entry, "target": arithmetic,
                           "seconds_to_flip": (bull.confirm_flip_ns-bull.observation_time)/1e9})
    bear_e = pd.DataFrame({"regime_start_ns": bear.regime_start_ns, "observation_time": bear.observation_time,
                           "confirm_flip_ns": bear.confirm_flip_ns, "entry_px": bear.fill_px,
                           "atr": bear.atr_at_entry, "target": bear[TARGET_L].astype(int),
                           "seconds_to_flip": (bear.confirm_flip_ns-bear.observation_time)/1e9})
    econ = pd.concat([economic_rows(bull_e, "bullish_fade"), economic_rows(bear_e, "bearish_fade_top103")], ignore_index=True)
    econ.to_csv(RESULTS / "economic_event_rows.csv", index=False)
    explain("bullish_fade", bm, bull.assign(**{TARGET_B: arithmetic}), bf, TARGET_B)
    explain("bearish_fade_top103", lm, bear, lf, TARGET_L)
    parity = {"bullish_max_abs_diff": maxdiff, "bearish_fixture_max_abs_diff": bear_maxdiff,
              "bullish_model_sha256": sha256(BULL_ART / "model.joblib"),
              "bearish_model_sha256": sha256(BEAR_ART / "model.joblib")}
    (RESULTS / "reproduction.json").write_text(json.dumps(parity, indent=2) + "\n")
    write_reports(metrics, lifts, joined, timing, econ, parity, replay)


if __name__ == "__main__":
    main()
