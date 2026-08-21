"""Fit the frozen directional A/B feasibility comparison on NT-collected snapshots."""
from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import polars as pl
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from studies.Codex_structural_regime_geometry_maturity.implementation.paths import COLLECTION_ROOT

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "studies/Codex_structural_regime_geometry_maturity"
OUT = STUDY / "results"
MODEL_ARTIFACTS = OUT / "model_artifacts"
STORE = ROOT / "data/canonical/regime_complete_v1"
SEALED_2025_NS = 1_735_689_600_000_000_000
BULL_ART = STUDY / "artifacts/frozen_train_only_baselines/BULLISH_STRICT_top25_train_2023_v1"
LONG_ART = STUDY / "artifacts/frozen_train_only_baselines/LONG_STRICT_top25_train_2023_v1"
TOP25_BY_DIRECTION: dict[str, list[str]] = {"SHORT": [], "LONG": []}
TOP25: list[str] = []


def require_frozen_baselines() -> None:
    global TOP25
    TOP25_BY_DIRECTION["SHORT"] = json.loads((BULL_ART / "feature_list.json").read_text())
    TOP25_BY_DIRECTION["LONG"] = json.loads((LONG_ART / "feature_list.json").read_text())
    TOP25 = list(dict.fromkeys(TOP25_BY_DIRECTION["SHORT"] + TOP25_BY_DIRECTION["LONG"]))
STRUCTURAL = [
    "structural_max_expansion_atr", "structural_current_expansion_atr", "structural_giveback_atr", "structural_retention_ratio", "structural_expansion_atr_per_min", "regime_expansion_atr_per_min",
    "prior_1m_regime_duration_min", "prior_1m_regime_range_atr", "prior_1m_regime_net_directional_move_atr", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr_per_min", "prior_1m_regime_net_move_atr_per_min", "prior_1m_regime_efficiency",
    "current_5m_regime_age_min", "current_5m_regime_range_atr", "current_5m_directional_displacement_atr", "current_5m_regime_range_atr_per_min", "prior_5m_regime_duration_min", "prior_5m_regime_range_atr", "prior_5m_regime_net_directional_move_atr", "prior_5m_regime_range_atr_per_min", "distance_to_completed_5m_high_atr", "distance_to_completed_5m_low_atr", "current_1m_move_outside_completed_5m_range",
]
FAMILIES = {
    "expansion": STRUCTURAL[:2],
    "retention_giveback": STRUCTURAL[2:4],
    "speed": STRUCTURAL[4:6],
    "prior_1m_geometry": STRUCTURAL[6:13],
    "geometry_5m": STRUCTURAL[13:],
}
BUCKETS = [(300, 600, "300-600s"), (600, 900, "600-900s"), (900, 1800, "900-1800s"), (1800, float("inf"), ">=1800s")]


def load() -> pl.DataFrame:
    geo = pl.scan_parquet(str(COLLECTION_ROOT / "*/structural_rows.parquet")).filter(pl.col("structural_available"))
    score_columns = [f"bullish__{x}" for x in TOP25] + [f"bearish__{x}" for x in TOP25]
    score = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter((pl.col("entry_year") >= 2021) & (pl.col("entry_year") <= 2024) & (pl.col("session") == "RTH"))
        .select("checkpoint_decision_ns", "entry_year", "regime_id", "seconds_from_regime_start", "checkpoint_reference_price", "atr_at_checkpoint", "running_mfe_atr", "new_progress_windows", "retained_mfe_ratio", "bullish_in_domain", "bearish_in_domain", *score_columns)
    )
    ends = (pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
            .select("regime_id", "regime_end_decision_ns")
            .with_columns(pl.when(pl.col("regime_end_decision_ns") < SEALED_2025_NS).then(pl.col("regime_end_decision_ns")).otherwise(None).alias("regime_end_decision_ns")))
    # Snapshots are produced independently of the canonical score surface.  Bind
    # them to that surface once, then require the frozen decision/regime key for
    # every downstream fit/label row.
    decision_key = ["checkpoint_decision_ns", "regime_id"]
    snapshots = geo.join(score.select(*decision_key).unique(), on="checkpoint_decision_ns", how="inner", validate="m:1")
    return (
        score.join(snapshots, on=decision_key, how="inner")
        .join(ends, on="regime_id", how="left")
        .with_columns(
            label=((pl.col("regime_end_decision_ns") - pl.col("checkpoint_decision_ns")) > 0) & ((pl.col("regime_end_decision_ns") - pl.col("checkpoint_decision_ns")) <= 300_000_000_000),
            seconds_to_eventual_flip=(pl.col("regime_end_decision_ns") - pl.col("checkpoint_decision_ns")) / 1_000_000_000,
            maturity_bucket=pl.when(pl.col("seconds_from_regime_start") < 600).then(pl.lit("300-600s")).when(pl.col("seconds_from_regime_start") < 900).then(pl.lit("600-900s")).when(pl.col("seconds_from_regime_start") < 1800).then(pl.lit("900-1800s")).otherwise(pl.lit(">=1800s")),
        )
        .filter(pl.col("regime_end_decision_ns").is_not_null())
        .collect()
    )


def side(df: pl.DataFrame, name: str, direction: int) -> pl.DataFrame:
    prefix, gate = ("bullish", "bullish_in_domain") if direction == 1 else ("bearish", "bearish_in_domain")
    features = TOP25_BY_DIRECTION[name]
    return df.filter(pl.col(gate) & (pl.col("seconds_from_regime_start") >= 300)).rename({f"{prefix}__{f}": f for f in features}).with_columns(direction=pl.lit(name))


def metrics(frame: pl.DataFrame, score_col: str, model_set: str, direction: str) -> list[dict]:
    rows = []
    for _, _, bucket in BUCKETS:
        x = frame.filter(pl.col("maturity_bucket") == bucket)
        if x.height and x["label"].n_unique() == 2:
            rows.append({"model_set": model_set, "direction": direction, "maturity_bucket": bucket, "n": x.height, "positives": int(x["label"].sum()), "roc_auc": roc_auc_score(x["label"].to_numpy(), x[score_col].to_numpy())})
    return rows


def _family_attribution(model, train: pl.DataFrame, oos: pl.DataFrame, features: list[str], direction: str) -> list[dict]:
    x, y = oos.select(features).to_numpy(), oos["label"].to_numpy()
    baseline = roc_auc_score(y, model.predict_proba(x)[:, 1])
    pos = {name: i for i, name in enumerate(features)}
    rows = []
    for number, (family, names) in enumerate(FAMILIES.items()):
        rng, altered = np.random.default_rng(10_000 + number), x.copy()
        for name in names:
            altered[:, pos[name]] = rng.permutation(altered[:, pos[name]])
        auc = roc_auc_score(y, model.predict_proba(altered)[:, 1])
        reduced_features = [feature for feature in features if feature not in names]
        reduced = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)
        reduced.fit(train.select(reduced_features).to_numpy(), train["label"].to_numpy())
        ablated_auc = roc_auc_score(y, reduced.predict_proba(oos.select(reduced_features).to_numpy())[:, 1])
        rows.append({"direction": direction, "family": family, "oos_auc_full": baseline, "oos_auc_after_group_permutation": auc, "group_permutation_auc_drop": baseline - auc, "oos_auc_after_family_ablation": ablated_auc, "family_ablation_auc_drop": baseline - ablated_auc, "seed": 10_000 + number})
    return rows


def fit_one(df: pl.DataFrame, direction: str) -> tuple[list[dict], pl.DataFrame, dict, list[dict]]:
    base_features = TOP25_BY_DIRECTION[direction]
    enriched = base_features + STRUCTURAL
    df = df.drop_nulls(list(dict.fromkeys(enriched)))
    train, oos = df.filter(pl.col("entry_year") <= 2023), df.filter(pl.col("entry_year") == 2024)
    result, scored, manifest, importance = [], [], {}, []
    for model_set, features in (("TOP25", base_features), ("TOP25_PLUS_STRUCTURAL", enriched)):
        model = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)
        model.fit(train.select(features).to_numpy(), train["label"].to_numpy())
        MODEL_ARTIFACTS.mkdir(parents=True, exist_ok=True)
        artifact_path = MODEL_ARTIFACTS / f"{direction}_{model_set}.joblib"
        joblib.dump(model, artifact_path)
        train_score = model.predict_proba(train.select(features).to_numpy())[:, 1]
        oos_score = model.predict_proba(oos.select(features).to_numpy())[:, 1]
        col = f"score_{model_set}"
        part = oos.with_columns(pl.Series(col, oos_score))
        thresholds = {str(q): float(np.quantile(train_score, q, method="linear")) for q in (0.9, 0.95, 0.975)}
        deciles = [float(np.quantile(train_score, q, method="linear")) for q in np.arange(0.1, 1.0, 0.1)]
        result += metrics(part, col, model_set, direction)
        scored.append(part.select("checkpoint_decision_ns", "regime_id", "entry_year", "maturity_bucket", "label", "seconds_to_eventual_flip", "checkpoint_reference_price", "atr_at_checkpoint", *enriched, pl.lit(direction).alias("direction"), pl.lit(model_set).alias("model_set"), pl.col(col).alias("score")).with_columns(pl.Series("train_score_decile", np.searchsorted(np.asarray(deciles), oos_score, side="right") + 1)))
        manifest[f"{direction}_{model_set}"] = {"features": features, "baseline_source": source_contract(direction), "train_rows": train.height, "oos_rows": oos.height, "thresholds": thresholds, "deciles": deciles, "random_seed": 42, "artifact": str(artifact_path.relative_to(OUT)), "artifact_sha256": __import__("hashlib").sha256(artifact_path.read_bytes()).hexdigest()}
        if model_set == "TOP25_PLUS_STRUCTURAL":
            importance += _family_attribution(model, train, oos, features, direction)
    return result, pl.concat(scored), manifest, importance


def first_crossings(scores: pl.DataFrame, manifest: dict) -> pl.DataFrame:
    rows = []
    for key, detail in manifest.items():
        direction = key.split("_TOP25", 1)[0]
        model_set = "TOP25" if key.endswith("TOP25") else "TOP25_PLUS_STRUCTURAL"
        subset = scores.filter((pl.col("direction") == direction) & (pl.col("model_set") == model_set)).sort(["regime_id", "checkpoint_decision_ns"])
        for quantile, threshold in detail["thresholds"].items():
            crossed = subset.with_columns(previous=pl.col("score").shift(1).over("regime_id")).filter((pl.col("score") >= threshold) & (pl.col("previous") < threshold)).group_by("regime_id").first()
            rows.append(crossed.with_columns(threshold_quantile=pl.lit(float(quantile)), threshold=pl.lit(threshold)))
    return pl.concat(rows)


def decile_metrics(scores: pl.DataFrame) -> pl.DataFrame:
    return scores.group_by("model_set", "direction", "maturity_bucket", "train_score_decile").agg(n=pl.len(), p_flip_le_300s=pl.col("label").mean(), median_seconds_to_eventual_flip=pl.col("seconds_to_eventual_flip").filter(pl.col("seconds_to_eventual_flip") > 0).median()).sort("model_set", "direction", "maturity_bucket", "train_score_decile")


def timing_metrics(scores: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for model_set, direction, bucket in scores.select("model_set", "direction", "maturity_bucket").unique().iter_rows():
        x = scores.filter((pl.col("model_set") == model_set) & (pl.col("direction") == direction) & (pl.col("maturity_bucket") == bucket))
        ranked = x.with_columns((pl.col("score").rank("average").over("regime_id") / pl.len().over("regime_id")).alias("within_regime_score_percentile"))
        positives = ranked.filter(pl.col("seconds_to_eventual_flip") > 0)
        rho = spearmanr(positives["within_regime_score_percentile"].to_numpy(), -positives["seconds_to_eventual_flip"].to_numpy()).statistic if positives.height >= 3 else float("nan")
        top = ranked.sort(["regime_id", "score", "checkpoint_decision_ns"], descending=[False, True, False]).group_by("regime_id").first().filter(pl.col("seconds_to_eventual_flip") > 0)
        final = ranked.sort(["regime_id", "checkpoint_decision_ns"], descending=[False, True]).group_by("regime_id").first()
        rows.append({"model_set": model_set, "direction": direction, "maturity_bucket": bucket, "n_checkpoints": ranked.height, "n_positive_checkpoints": positives.height, "n_regimes": ranked["regime_id"].n_unique(), "spearman_score_pct_vs_neg_secs_to_flip": rho, "median_top_score_secs_to_flip": top["seconds_to_eventual_flip"].median(), "mean_final_preflip_score_pct": final["within_regime_score_percentile"].mean()})
    return pl.DataFrame(rows).sort("model_set", "direction", "maturity_bucket")


def phase0_contract(raw: pl.DataFrame) -> dict:
    """Reconcile only the frozen 2021-2024 study surface; never inspect 2025/2026."""
    sources = {"prevailing_bullish_short": source_contract("SHORT"), "prevailing_bearish_long": source_contract("LONG")}
    eligibility = (pl.col("seconds_from_regime_start") > 120) & (pl.col("running_mfe_atr") >= 1) & (pl.col("new_progress_windows") >= 2) & (pl.col("retained_mfe_ratio") >= 0.5) & ((pl.col("checkpoint_decision_ns") % 5_000_000_000) == 0)
    observed = raw.filter(pl.col("bullish_in_domain") | pl.col("bearish_in_domain")).select(pl.len().alias("joined_2021_2024_rth_rows"), eligibility.sum().alias("strict_eligible_rows"), (~eligibility).sum().alias("strict_eligibility_failures"), pl.col("bullish_in_domain").sum().alias("bullish_in_domain_rows"), pl.col("bearish_in_domain").sum().alias("bearish_in_domain_rows"), pl.col("entry_year").min().alias("minimum_checkpoint_year"), pl.col("entry_year").max().alias("maximum_checkpoint_year")).to_dicts()[0]
    source_ok = all(item["verified"] for item in sources.values())
    eligibility_ok = observed["strict_eligibility_failures"] == 0
    return {"status": "PASS" if source_ok and eligibility_ok else "FAIL", "study_years": [2021, 2022, 2023, 2024], "sealed_after_ns": SEALED_2025_NS, "target": "prevailing_1m_regime_flip_in_(T,T+300s]", "train_years": [2021, 2022, 2023], "oos_year": 2024, "accepted_eligibility": {"session": "RTH", "strict_age_seconds": ">120", "running_mfe_atr": ">=1", "new_progress_windows": ">=2", "retained_mfe_ratio": ">=0.5", "atr_anchor": "confirmed_1m_regime_start", "cadence_seconds": 5, "in_domain": "direction-specific accepted canonical gate", "right_censoring": "excluded"}, "top25_sources": sources, "observed_reconciliation": observed}


def source_contract(direction: str) -> dict:
    import hashlib
    if direction == "SHORT":
        source, name, feature_path = BULL_ART, "BULLISH_STRICT_top25_train_2023_v1", BULL_ART / "feature_list.json"
    else:
        source, name, feature_path = LONG_ART, "LONG_STRICT_top25_train_2023_v1", LONG_ART / "feature_list.json"
    actual = hashlib.sha256(json.dumps(TOP25_BY_DIRECTION[direction]).encode()).hexdigest()
    manifest = json.loads((source / "manifest.json").read_text())
    expected = manifest["ordered_feature_list_hash"]
    required = {"model_id": name, "direction": direction, "selection_years": [2021, 2022, 2023], "oos_boundary": "2024-01-01T00:00:00+00:00", "future_years_read": [], "target": "prevailing_1m_regime_flip_in_(T,T+300s]", "session": "RTH", "atr_anchor": "confirmed_1m_regime_start", "right_censoring": "excluded"}
    facts_match = all(manifest.get(key) == value for key, value in required.items()) and manifest.get("strict_eligibility", {}).get("cadence_ns") == 5_000_000_000
    return {"name": name, "feature_path": str(feature_path.relative_to(ROOT)), "feature_sha256": hashlib.sha256(feature_path.read_bytes()).hexdigest(), "features_sha256": actual, "expected_features_sha256": expected, "feature_count": len(TOP25_BY_DIRECTION[direction]), "manifest_sha256": hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest(), "verified": actual == expected and len(TOP25_BY_DIRECTION[direction]) == 25 and facts_match}


def main() -> None:
    require_frozen_baselines()
    OUT.mkdir(exist_ok=True)
    started, raw = time.time(), load()
    results, all_scores, manifest, permutations = [], [], {}, []
    for name, sign in (("SHORT", 1), ("LONG", -1)):
        result, scores, details, family_rows = fit_one(side(raw, name, sign), name)
        results += result
        all_scores.append(scores)
        manifest.update(details)
        permutations += family_rows
    scores = pl.concat(all_scores)
    for model_set in ("TOP25", "TOP25_PLUS_STRUCTURAL"):
        for _, _, bucket in BUCKETS:
            pooled = scores.filter((pl.col("model_set") == model_set) & (pl.col("maturity_bucket") == bucket))
            if pooled.height and pooled["label"].n_unique() == 2:
                results.append({"model_set": model_set, "direction": "POOLED_DIRECTION_LABELLED", "maturity_bucket": bucket, "n": pooled.height, "positives": int(pooled["label"].sum()), "roc_auc": roc_auc_score(pooled["label"].to_numpy(), pooled["score"].to_numpy())})
    first = first_crossings(scores, manifest)
    pl.DataFrame(results).write_csv(OUT / "oos_row_metrics.csv")
    scores.write_parquet(OUT / "oos_scores.parquet")
    first.write_parquet(OUT / "oos_first_crossings.parquet")
    decile_metrics(scores).write_csv(OUT / "oos_decile_classification.csv")
    timing_metrics(scores).write_csv(OUT / "oos_timing_metrics.csv")
    attribution = pl.DataFrame(permutations).sort("direction", "group_permutation_auc_drop", descending=[False, True])
    attribution.write_csv(OUT / "oos_family_permutation.csv")
    attribution.write_csv(OUT / "oos_family_attribution.csv")
    (OUT / "models_manifest.json").write_text(json.dumps(manifest, indent=2))
    (OUT / "phase0_contract.json").write_text(json.dumps(phase0_contract(raw), indent=2, default=str))
    (OUT / "collection_manifest.json").write_text(json.dumps({"partitions": 48, "joined_rth_rows": raw.height, "elapsed_seconds": time.time() - started, "sealed_2026": True, "source": "NT event-loop collector"}, indent=2))
    print(json.dumps({"joined_rows": raw.height, "metrics": len(results), "crossings": first.height, "elapsed_seconds": time.time() - started}, indent=2))


if __name__ == "__main__":
    main()
