"""Train and score sealed pre-2026 quarterly expanding-window models.

This module consumes only facts emitted by the accepted NautilusTrader global
collector. It never reconstructs a feature, regime, or signal from raw bars.
Candidate creation and lifecycle simulation are intentionally delegated to the
NT collector stage; this module only fits models and evaluates predictions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import numpy as np
import polars as pl
import yaml
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from .contracts import Quarter, evaluation_mask, quarters, resolved_train_mask, threshold

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies/quarterly_walk_forward_flip_models"
STORE = ROOT / "data/canonical/regime_complete_v1"
SCORES = STORE / "canonical_regime_scores_all.parquet"
REGIMES = STORE / "canonical_regimes_all.parquet"
SEALED_END = Quarter(2026, 1).start


@dataclass(frozen=True)
class ModelContract:
    name: str
    prefix: str
    artifact: Path
    target_direction: int
    trade_direction: int


CONTRACTS = (
    ModelContract(
        "BULLISH_STRICT_top25_gbt_v2", "bullish",
        ROOT / "studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2",
        -1, -1,
    ),
    ModelContract(
        "LONG_STRICT_top25_gbt_v2", "bearish",
        ROOT / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2",
        1, 1,
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_features(contract: ModelContract) -> list[str]:
    paths = (contract.artifact / "ordered_features.json", contract.artifact / "feature_list.json")
    for path in paths:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            values = raw.get("features", raw) if isinstance(raw, dict) else raw
            features = list(values)
            if len(features) == len(set(features)) == 25:
                return features
    manifest = json.loads((contract.artifact / "model_manifest.json").read_text(encoding="utf-8"))
    features = list(manifest["features"])
    if len(features) != 25:
        raise RuntimeError(f"{contract.name}: exact 25-feature list missing")
    return features


def next_flip_labels(times: np.ndarray, direction: int) -> np.ndarray:
    """Build the frozen target from accepted *confirmed* regime decisions.

    The accepted canonical regime-store contract defines
    ``regime_start_decision_ns`` as the timestamp at which the confirmed
    transition became causally available. The scan is explicitly sealed before
    collection: no 2026 row can enter memory while pre-2026 labels are built.
    """
    regimes = (
        pl.scan_parquet(REGIMES)
        .filter(pl.col("regime_start_decision_ns") < SEALED_END)
        .select("regime_sequence_number", "regime_start_decision_ns", "regime_direction")
        .sort("regime_start_decision_ns")
        .collect(engine="streaming")
    )
    starts = regimes["regime_start_decision_ns"].to_numpy().astype(np.int64)
    directions = regimes["regime_direction"].to_numpy().astype(np.int8)
    sequence = regimes["regime_sequence_number"].to_numpy().astype(np.int64)
    if not starts.size or np.any(np.diff(starts) <= 0):
        raise RuntimeError("canonical confirmed-regime starts are not strictly monotonic")
    if np.any(np.diff(sequence) != 1):
        raise RuntimeError("canonical confirmed-regime sequence has a missing or duplicate regime")
    if np.any(np.diff(directions) == 0):
        raise RuntimeError("canonical regime direction does not alternate at confirmed starts")
    target = starts[directions == direction]
    at = np.searchsorted(target, times, side="right")
    future = np.full(times.shape, -1, dtype=np.int64)
    valid = at < target.size
    future[valid] = target[at[valid]]
    return ((future > times) & (future - times <= 300 * 1_000_000_000)).astype(np.int8)


def load_population(contract: ModelContract, features: list[str]) -> dict[str, np.ndarray]:
    p = contract.prefix
    columns = [
        "checkpoint_decision_ns", "regime_start_ns", "regime_age_seconds",
        "reference_price", "atr_at_checkpoint", "study_year", "confirmed_regime_direction",
        "is_regime_confirmed", f"{p}_probability",
    ] + [f"{p}__{feature}" for feature in features]
    frame = (
        pl.scan_parquet(SCORES)
        .filter(
            (pl.col("study_year") <= 2025)
            & pl.col(f"{p}_in_domain")
            & pl.col(f"{p}_feature_complete")
        )
        .select(columns)
        .sort("checkpoint_decision_ns")
        .collect(engine="streaming")
    )
    if frame.height == 0:
        raise RuntimeError(f"{contract.name}: empty pre-2026 population")
    times = frame["checkpoint_decision_ns"].to_numpy().astype(np.int64)
    if np.any(times >= SEALED_END):
        raise RuntimeError("sealed-year observation reached pre-2026 trainer")
    x = frame.select([f"{p}__{feature}" for feature in features]).to_numpy().astype(np.float64)
    if not np.isfinite(x).all():
        raise RuntimeError(f"{contract.name}: non-finite supposedly complete feature row")
    source_direction = frame["confirmed_regime_direction"].to_numpy().astype(np.int8)
    confirmed = frame["is_regime_confirmed"].to_numpy()
    if not np.all(confirmed) or not np.all(source_direction == -contract.target_direction):
        raise RuntimeError(f"{contract.name}: source in-domain population violates confirmed opposite-regime target contract")
    return {
        "times": times,
        "regime": frame["regime_start_ns"].to_numpy().astype(np.int64),
        "age": frame["regime_age_seconds"].to_numpy().astype(np.float64),
        "price": frame["reference_price"].to_numpy().astype(np.float64),
        "atr": frame["atr_at_checkpoint"].to_numpy().astype(np.float64),
        "year": frame["study_year"].to_numpy().astype(np.int16),
        "frozen_score": frame[f"{p}_probability"].to_numpy().astype(np.float64),
        "x": x,
        "y": next_flip_labels(times, contract.target_direction),
    }


def metrics(y: np.ndarray, score: np.ndarray) -> dict[str, float | None]:
    if len(np.unique(y)) != 2:
        return {name: None for name in ("roc_auc", "pr_auc", "brier", "log_loss", "calibration_slope", "calibration_intercept")}
    clipped = np.clip(score, 1e-12, 1 - 1e-12)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    calibration = LogisticRegression(C=1e6, solver="lbfgs").fit(logits, y)
    return {
        "roc_auc": float(roc_auc_score(y, score)),
        "pr_auc": float(average_precision_score(y, score)),
        "brier": float(brier_score_loss(y, score)),
        "log_loss": float(log_loss(y, score, labels=[0, 1])),
        "calibration_slope": float(calibration.coef_[0, 0]),
        "calibration_intercept": float(calibration.intercept_[0]),
    }


def output_thresholds(score: np.ndarray) -> dict[str, float]:
    return {"top_10": threshold(score, 0.90), "top_5": threshold(score, 0.95), "top_2_5": threshold(score, 0.975), "top_1": threshold(score, 0.99)}


def train_pre_2026() -> dict:
    cfg = yaml.safe_load((STUDY / "config/study.yaml").read_text(encoding="utf-8"))
    params = dict(cfg["model"])
    params.pop("class")
    out_models, out_results = STUDY / "models/pre_2026", STUDY / "results"
    out_models.mkdir(parents=True, exist_ok=True)
    out_results.mkdir(parents=True, exist_ok=True)
    records, threshold_rows, manifest_rows = [], [], []
    for contract in CONTRACTS:
        features = load_features(contract)
        pop = load_population(contract, features)
        visible_end = min(int(pop["times"].max()), SEALED_END - 1)
        for quarter in quarters(2021, 2025):
            train = resolved_train_mask(pop["times"], quarter.start)
            evaluate = evaluation_mask(pop["times"], quarter, visible_end)
            if train.sum() == 0 or evaluate.sum() == 0 or len(np.unique(pop["y"][train])) != 2:
                continue
            model = HistGradientBoostingClassifier(**params).fit(pop["x"][train], pop["y"][train])
            target_dir = out_models / contract.name / quarter.label
            target_dir.mkdir(parents=True, exist_ok=True)
            model_path = target_dir / "model.joblib"
            joblib.dump(model, model_path)
            train_score = model.predict_proba(pop["x"][train])[:, 1]
            wf_score = model.predict_proba(pop["x"][evaluate])[:, 1]
            frozen_score = pop["frozen_score"][evaluate]
            if not np.isfinite(frozen_score).all():
                raise RuntimeError(f"{contract.name} {quarter.label}: frozen comparison score absent")
            th = output_thresholds(train_score)
            model_hash = sha256(model_path)
            artifact = {
                "model_id": contract.name, "evaluation_quarter": quarter.label,
                "model_sha256": model_hash, "feature_list": features,
                "feature_hash": hashlib.sha256(json.dumps(features).encode()).hexdigest(),
                "train_end_exclusive_ns": quarter.start, "train_rows": int(train.sum()),
                "train_positive_rate": float(pop["y"][train].mean()), "seed": params["random_state"],
                "thresholds": th, "threshold_reference": "same_model_resolved_pre_quarter_training_scores",
            }
            (target_dir / "manifest.json").write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
            wm, fm = metrics(pop["y"][evaluate], wf_score), metrics(pop["y"][evaluate], frozen_score)
            row = {
                "model_id": contract.name, "direction": "bullish" if contract.prefix == "bullish" else "bearish",
                "quarter": quarter.label, "n_scored": int(evaluate.sum()),
                "positive_rate": float(pop["y"][evaluate].mean()), "probability_mean": float(wf_score.mean()),
                "probability_std": float(wf_score.std()), "model_sha256": model_hash,
            }
            for name, value in wm.items():
                row[f"wf_{name}"] = value
                row[f"frozen_{name}"] = fm[name]
                row[f"delta_{name}"] = None if value is None or fm[name] is None else value - fm[name]
            for label, value in th.items():
                selected = wf_score >= value
                event_rate = float(pop["y"][evaluate][selected].mean()) if selected.any() else None
                row[f"wf_{label}_threshold"] = value
                row[f"wf_{label}_event_rate"] = event_rate
                row[f"wf_{label}_lift"] = None if event_rate is None else event_rate - row["positive_rate"]
                threshold_rows.append({"model_id": contract.name, "quarter": quarter.label, "view": "WALK_FORWARD_CAUSAL_THRESHOLD", "level": label, "threshold": value, "available": True})
            records.append(row)
            manifest_rows.append(artifact)
    if not records:
        raise RuntimeError("no valid pre-2026 evaluation quarter for both-class expanding training")
    pl.DataFrame(records).write_parquet(out_results / "quarterly_model_metrics.parquet")
    pl.DataFrame(threshold_rows).write_parquet(out_results / "quarterly_thresholds.parquet")
    (out_results / "quarterly_training_manifest.json").write_text(json.dumps(manifest_rows, indent=2) + "\n", encoding="utf-8")
    return {"models": len(manifest_rows), "metrics": len(records), "sealed_year_accessed": False}


if __name__ == "__main__":
    print(json.dumps(train_pre_2026(), indent=2))
