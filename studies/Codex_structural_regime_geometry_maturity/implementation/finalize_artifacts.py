"""Materialize manifest deliverables and derive every reachable terminal label."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

from studies.Codex_structural_regime_geometry_maturity.implementation.contracts import MATERIAL_AUC_DELTA, PRIMARY_BUCKETS, classify_terminal, sha256
from studies.Codex_structural_regime_geometry_maturity.implementation.paths import COLLECTION_ROOT
from studies.Codex_structural_regime_geometry_maturity.run_study import STRUCTURAL, TOP25

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies/Codex_structural_regime_geometry_maturity"
OUT, COLLECTION, STORE = STUDY / "results", COLLECTION_ROOT, ROOT / "data/canonical/regime_complete_v1"


def status_clean(path: Path) -> bool:
    if not path.is_file():
        return False
    payload = json.loads(path.read_text())
    return int(payload.get("critical", payload.get("blocking", 99))) == 0 and payload.get("verdict") in {"PASS", "CLEAR"}


def lint_clean(path: Path) -> bool:
    if not path.is_file():
        return False
    payload = json.loads(path.read_text())
    return int(payload.get("critical", 99)) == 0 and int(payload.get("warning", 99)) == 0


def phase0_clean(path: Path) -> bool:
    return path.is_file() and json.loads(path.read_text()).get("status") == "PASS"


def terminal_summary(out: Path = OUT, study: Path = STUDY) -> dict:
    """Classify only from the materialized result workflow and gate evidence."""
    auc = pl.read_csv(out / "oos_row_metrics.csv").filter(pl.col("direction").is_in(["SHORT", "LONG"]))
    base = auc.filter(pl.col("model_set") == "TOP25").select("direction", "maturity_bucket", pl.col("roc_auc").alias("base_auc"))
    comparison = (auc.filter(pl.col("model_set") == "TOP25_PLUS_STRUCTURAL").join(base, on=["direction", "maturity_bucket"]).with_columns((pl.col("roc_auc") - pl.col("base_auc")).alias("auc_delta")))
    discrimination = comparison.filter((pl.col("maturity_bucket").is_in(PRIMARY_BUCKETS)) & (pl.col("auc_delta") >= MATERIAL_AUC_DELTA)).select("direction", "maturity_bucket", "auc_delta")
    timing = pl.read_csv(out / "oos_timing_metrics.csv")
    timing_a = timing.filter(pl.col("model_set") == "TOP25").select("direction", "maturity_bucket", pl.col("spearman_score_pct_vs_neg_secs_to_flip").alias("a_rho"), pl.col("median_top_score_secs_to_flip").alias("a_top_seconds"))
    timing_b = timing.filter(pl.col("model_set") == "TOP25_PLUS_STRUCTURAL").select("direction", "maturity_bucket", pl.col("spearman_score_pct_vs_neg_secs_to_flip").alias("b_rho"), pl.col("median_top_score_secs_to_flip").alias("b_top_seconds"))
    timing_improvement = (timing_b.join(timing_a, on=["direction", "maturity_bucket"]).filter(pl.col("maturity_bucket").is_in(PRIMARY_BUCKETS) & ((pl.col("b_rho") > pl.col("a_rho")) | (pl.col("b_top_seconds") < pl.col("a_top_seconds")))).select("direction", "maturity_bucket"))
    evidence = pl.concat([discrimination.select("direction", "maturity_bucket"), timing_improvement]).unique()
    p90 = pl.read_csv(out / "oos_crossing_metrics.csv").filter(pl.col("threshold_quantile") == 0.9)
    a = p90.filter(pl.col("model_set") == "TOP25").select("direction", "maturity_bucket", pl.col("p_confirm_before_1atr").alias("a_confirm"), pl.col("median_eventual_opposite_mfe_atr").alias("a_mfe"))
    b = p90.filter(pl.col("model_set") == "TOP25_PLUS_STRUCTURAL").select("direction", "maturity_bucket", pl.col("p_confirm_before_1atr").alias("b_confirm"), pl.col("median_eventual_opposite_mfe_atr").alias("b_mfe"))
    economic = b.join(a, on=["direction", "maturity_bucket"]).with_columns(
        ((pl.col("b_confirm") >= pl.col("a_confirm")) & (pl.col("b_mfe") >= pl.col("a_mfe"))).alias("nonworse")
    )
    checked = economic.join(evidence, on=["direction", "maturity_bucket"], how="inner")
    economics_nonworse = checked.height > 0 and all((row["b_confirm"] >= row["a_confirm"] and row["b_mfe"] >= row["a_mfe"]) for row in checked.to_dicts())
    economic_tail_only = evidence.height == 0 and any((row["b_confirm"] > row["a_confirm"] and row["b_mfe"] > row["a_mfe"]) for row in economic.to_dicts())
    validation = json.loads((out / "validation_report.json").read_text())
    audit_ok = status_clean(study / "audit/status.json") and status_clean(study / "audit/contract_status.json")
    phase0_ok, lint_ok = phase0_clean(out / "phase0_contract.json"), lint_clean(study / "audit/lint.json")
    younger_only = evidence.height >= 2 and all(row["maturity_bucket"] == "300-600s" for row in evidence.to_dicts())
    terminal = classify_terminal(abort=validation["status"] != "PASS" or not audit_ok or not phase0_ok or not lint_ok, classification_cells=evidence.height, younger_only=younger_only, economics_nonworse=economics_nonworse, economic_tail_only=economic_tail_only)
    return {"terminal_label": terminal, "criteria": {"material_auc_delta": MATERIAL_AUC_DELTA, "primary_evidence_direction_bucket_cells": evidence.height, "discrimination_positive_cells": discrimination.to_dicts(), "timing_positive_cells": timing_improvement.to_dicts(), "economics_nonworse_at_p90": economics_nonworse, "economic_tail_only": economic_tail_only, "younger_only": younger_only, "validation_pass": validation["status"] == "PASS", "phase0_contract_pass": phase0_ok, "lint_pass": lint_ok, "causal_audit_pass": status_clean(study / "audit/status.json"), "contract_audit_pass": status_clean(study / "audit/contract_status.json")}, "primary_comparisons": comparison.select("direction", "maturity_bucket", "n", "base_auc", "roc_auc", "auc_delta").to_dicts(), "sealed_2026": True, "acceptance": "PROMOTION_GATE_PENDING"}


def main() -> None:
    geometry = pl.scan_parquet(str(COLLECTION / "*/structural_rows.parquet"))
    score_features = [f"bullish__{name}" for name in TOP25] + [f"bearish__{name}" for name in TOP25]
    score = (pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet").filter((pl.col("entry_year") >= 2021) & (pl.col("entry_year") <= 2024) & (pl.col("session") == "RTH")).select("checkpoint_decision_ns", "regime_id", "entry_year", "seconds_from_regime_start", "checkpoint_reference_price", "atr_at_checkpoint", "bullish_in_domain", "bearish_in_domain", *score_features))
    checkpoint_path = OUT / "structural_checkpoints.parquet"
    # Preserve unavailable rows and their explicit reasons in the manifest
    # artifact; analysis chooses eligible rows separately and never imputes them.
    decision_key = ["checkpoint_decision_ns", "regime_id"]
    snapshots = geometry.join(score.select(*decision_key).unique(), on="checkpoint_decision_ns", how="inner", validate="m:1")
    score.join(snapshots, on=decision_key, how="inner").sink_parquet(checkpoint_path, compression="zstd", statistics=True)
    manifests = [json.loads(path.read_text()) for path in sorted(COLLECTION.glob("*/manifest.json"))]
    reason_rows = geometry.select(pl.col("structural_unavailable_reason").drop_nulls().value_counts()).collect().to_dicts()
    reasons = {item["structural_unavailable_reason"]["structural_unavailable_reason"]: item["structural_unavailable_reason"]["count"] for item in reason_rows}
    total = geometry.select(pl.len()).collect().item()
    available = geometry.select(pl.col("structural_available").sum()).collect().item()
    collection = {"partitions": len(manifests), "partition_rows": sum(item["rows"] for item in manifests), "partition_sha256": {item["start"][:7]: item["sha256"] for item in manifests}, "attrition": {"all_nt_snapshots": total, "available_snapshots": available, "unavailable_snapshots": total - available, "unavailable_reasons": reasons, "missing_prior_1m_anchor": reasons.get("NO_COMPLETED_PRIOR_1M_REGIME", 0)}, "checkpoint_artifact_sha256": sha256(checkpoint_path), "code_sha256": {name: sha256(path) for name, path in {"tracker": ROOT / "features/trackers/structural_regime_geometry.py", "collector": STUDY / "implementation/collector.py", "runner": STUDY / "implementation/run_collect.py"}.items()}, "no_2026_assertion": True, "source": "NautilusTrader event-loop collector"}
    (OUT / "collection_manifest.json").write_text(json.dumps(collection, indent=2))
    model_path = OUT / "models_manifest.json"
    models = json.loads(model_path.read_text())
    models["source_hashes"] = {"top25_candidate_sets": sha256(ROOT / "studies/runtime_constrained_f3_feature_reduction/results/candidate_feature_sets.json"), "study_runner": sha256(STUDY / "run_study.py"), "structural_feature_order": hashlib.sha256("\n".join(STRUCTURAL).encode()).hexdigest()}
    model_path.write_text(json.dumps(models, indent=2))
    classification, economics = pl.read_csv(OUT / "oos_decile_classification.csv"), pl.read_csv(OUT / "oos_decile_economics.csv").rename({name: f"sample_{name}" for name in ["n", "p_flip_le_300s"]})
    classification.join(economics, on=["model_set", "direction", "maturity_bucket", "train_score_decile"], how="left").write_csv(OUT / "oos_deciles.csv")
    summary = terminal_summary()
    summary["attrition"] = collection["attrition"]
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({"checkpoint_artifact": str(checkpoint_path), "partitions": len(manifests), "terminal_label": summary["terminal_label"]}, indent=2))


if __name__ == "__main__":
    main()
