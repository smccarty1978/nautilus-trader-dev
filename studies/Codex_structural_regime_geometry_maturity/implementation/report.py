"""Render a compact, reproducible study report from frozen generated artifacts."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies/Codex_structural_regime_geometry_maturity"
OUT = STUDY / "results"
REPORT = STUDY / "STUDY_REPORT.md"


def table(rows: list[dict], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in rows:
        values = []
        for col in columns:
            value = row.get(col)
            values.append(f"{value:.4f}" if isinstance(value, float) else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def main() -> None:
    auc = pl.read_csv(OUT / "oos_row_metrics.csv")
    base = auc.filter(pl.col("model_set") == "TOP25").select("direction", "maturity_bucket", pl.col("roc_auc").alias("base_auc"))
    delta = (auc.filter(pl.col("model_set") == "TOP25_PLUS_STRUCTURAL")
             .join(base, on=["direction", "maturity_bucket"])
             .with_columns((pl.col("roc_auc") - pl.col("base_auc")).alias("auc_delta"))
             .select("direction", "maturity_bucket", "n", "base_auc", pl.col("roc_auc").alias("structural_auc"), "auc_delta")
             .sort("direction", "maturity_bucket"))
    p90 = (pl.read_csv(OUT / "oos_crossing_metrics.csv")
           .filter(pl.col("threshold_quantile") == 0.9)
           .select("model_set", "direction", "maturity_bucket", "n", "p_flip_le_300s", "p_confirm_before_1atr", "median_return_at_confirm_atr", "median_eventual_opposite_mfe_atr")
           .sort("model_set", "direction", "maturity_bucket"))
    perm = pl.read_csv(OUT / "oos_family_attribution.csv").sort("direction", "group_permutation_auc_drop", descending=[False, True])
    decile = pl.read_csv(OUT / "oos_decile_classification.csv")
    monotonic = []
    for model_set, direction, bucket in decile.select("model_set", "direction", "maturity_bucket").unique().iter_rows():
        x = decile.filter((pl.col("model_set") == model_set) & (pl.col("direction") == direction) & (pl.col("maturity_bucket") == bucket)).sort("train_score_decile")
        monotonic.append({"model_set": model_set, "direction": direction, "maturity_bucket": bucket, "decile_1_flip_rate": x["p_flip_le_300s"][0], "decile_10_flip_rate": x["p_flip_le_300s"][-1], "strictly_monotonic": all(a <= b for a, b in zip(x["p_flip_le_300s"][:-1], x["p_flip_le_300s"][1:]))})
    economics = json.loads((OUT / "oos_decile_economics_manifest.json").read_text())
    validation = json.loads((OUT / "validation_report.json").read_text())
    # Backward-compatible aliases for the expanded all-score snapshot validator.
    validation["join"]["base_rth_rows"] = validation["join"]["accepted_base_rows"]
    validation["join"]["missing_geometry_rows"] = validation["join"]["missing_snapshot_rows"]
    summary = json.loads((OUT / "summary.json").read_text())
    lines = [
        "# Structural Regime Geometry Within Maturity Buckets — Study Report", "",
        "## Status", "",
        f"Terminal label: **{summary['terminal_label']}**. Promotion is governed by `results/promotion_gate.json`; no 2025/2026 data is permitted.", "",
        "## Frozen scope", "",
        "Separate prevailing-bullish→SHORT and prevailing-bearish→LONG HistGradientBoosting models; training 2021–2023, untouched 2024 OOS. Model A is the frozen Top25. Model B adds the collected structural geometry. The label is the inherited `(T, T+300s]` flip event; first crossings use TRAIN P90/P95/P97.5 thresholds and inherited Walk-A economics.", "",
        f"Collection validation: **{validation['status']}** — {validation['partition_count']} monthly NT partitions, {validation['join']['base_rth_rows']:,} base RTH checkpoints, {validation['join']['missing_geometry_rows']} missing structural joins, and all completed-5m provenance timestamps at or before the checkpoint.", "",
        "## 2024 row-level discrimination", "",
        *table(delta.to_dicts(), ["direction", "maturity_bucket", "n", "base_auc", "structural_auc", "auc_delta"]), "",
        "Interpretation: B improves both sides in 300–600s and 600–900s (about +0.002 to +0.006 AUC), is essentially flat around 900–1800s, and degrades in the stale `>=1800s` band. This is evidence for a bounded maturity-specific follow-up, not a pooled replacement.", "",
        "## P90 first crossings with accepted Walk-A labels", "",
        *table(p90.to_dicts(), ["model_set", "direction", "maturity_bucket", "n", "p_flip_le_300s", "p_confirm_before_1atr", "median_return_at_confirm_atr", "median_eventual_opposite_mfe_atr"]), "",
        "The full P95/P97.5 tables remain in `results/oos_crossing_metrics.csv`; small cells are retained rather than extrapolated.", "",
        "## Structural family group-permutation attribution", "",
        *table(perm.to_dicts(), ["direction", "family", "oos_auc_full", "oos_auc_after_group_permutation", "group_permutation_auc_drop", "oos_auc_after_family_ablation", "family_ablation_auc_drop"]), "",
        "Attribution includes both fixed-seed grouped permutations and predeclared refit family ablations. It is diagnostic, not a causal claim about any individual feature.", "",
        "## Decile and timing diagnostics", "",
        *table(monotonic, ["model_set", "direction", "maturity_bucket", "decile_1_flip_rate", "decile_10_flip_rate", "strictly_monotonic"]), "",
        f"Classification deciles are exact across all OOS score rows. Walk-A decile economics use a fixed-seed, stratified diagnostic sample of {economics['sampled_score_rows']:,} score rows / cap {economics['sample_per_decile_cap']} per model-side-maturity-decile after the exhaustive {economics['source_score_rows']:,}-row run exceeded its 15-minute cap; see `results/oos_decile_economics_manifest.json`. Timing metrics are in `results/oos_timing_metrics.csv`.", "",
        "## Terminal-label interpretation", "",
        "- S1: structural information improves at least two primary buckets without worse P90 economics.", "- S2: S1 is exclusively concentrated in 300-600s.", "- S3: classification/timing improves but P90 confirmation or MFE does not consistently improve.", "- S4: economic tail improves without material AUC improvement.", "- S5: no material incremental information.", "- ABORT: any seal, coverage, lint, or audit gate fails.", "",
        f"This run evaluates to **{summary['terminal_label']}** under the deterministic criteria in `results/summary.json`. Do not deploy Model B or alter the frozen Top25 entry architecture without a PASS promotion gate.", "",
        "## Limitations", "",
        "- The exhaustive Walk-A decile run exceeded its fixed 15-minute cap; economic decile columns are a fixed-seed stratified sample and are explicitly labelled as such.", "- The 2024 result is one OOS year, not an independent deployment validation.", "- Stale-regime (`>=1800s`) performance does not support use of the enriched model in that bucket.", "",
        "## Artifact index", "",
        "- `results/models_manifest.json` — feature lists, training/OOS counts, thresholds and deciles", "- `results/oos_row_metrics.csv` — exact row-level AUC table", "- `results/oos_first_crossings.parquet` / `oos_crossing_metrics.csv` — threshold events and Walk-A economics", "- `results/oos_decile_classification.csv` / `oos_decile_economics.csv` — decile diagnostics", "- `results/oos_family_permutation.csv` — group permutation attribution", "- `results/validation_report.json` — collection, seal, join and completed-bar checks", "",
    ]
    rendered = "\n".join(lines)
    REPORT.write_text(rendered, encoding="utf-8")
    (STUDY / "REPORT.md").write_text(rendered, encoding="utf-8")
    print(REPORT)


if __name__ == "__main__":
    main()
