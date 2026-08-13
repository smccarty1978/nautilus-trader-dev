"""Baseline reconciliation: engine BASE policy vs frozen expected counts and the
builder's stored per-stop result parquets."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

STUDY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = STUDY_DIR.parents[1]
BUILDER = REPO_ROOT / "studies" / "full_trade_path_builder"

EXPECTED = {
    0.75: {
        "STOPPED BEFORE CONFIRMATION": 2528, "STOPPED AFTER CONFIRMATION": 1511,
        "REGIME-FLIP EXIT FOR PROFIT": 1215, "REGIME-FLIP EXIT FOR LOSS": 504,
        "REGIME-FLIP EXIT FLAT": 15, "CENSORED / UNRESOLVED": 54,
        "AMBIGUOUS EVENT ORDER": 9,
    },
    1.00: {
        "STOPPED BEFORE CONFIRMATION": 2149, "STOPPED AFTER CONFIRMATION": 1209,
        "REGIME-FLIP EXIT FOR PROFIT": 1464, "REGIME-FLIP EXIT FOR LOSS": 905,
        "REGIME-FLIP EXIT FLAT": 17, "CENSORED / UNRESOLVED": 78,
        "AMBIGUOUS EVENT ORDER": 14,
    },
    1.25: {
        "STOPPED BEFORE CONFIRMATION": 1855, "STOPPED AFTER CONFIRMATION": 861,
        "REGIME-FLIP EXIT FOR PROFIT": 1631, "REGIME-FLIP EXIT FOR LOSS": 1357,
        "REGIME-FLIP EXIT FLAT": 20, "CENSORED / UNRESOLVED": 98,
        "AMBIGUOUS EVENT ORDER": 14,
    },
}
STORED = {
    0.75: "top2_5_stop_0_75_regime_exit_results.parquet",
    1.00: "top2_5_stop_1_00_regime_exit_results.parquet",
    1.25: "top2_5_stop_1_25_regime_exit_results.parquet",
}

df = pl.read_parquet(
    STUDY_DIR / "results" / "post_confirmation_mfe_model_exit_trade_policy_results.parquet"
).filter(pl.col("policy_id") == "BASE")

report = {"per_stop": {}, "all_exact": True}
for stop, exp in EXPECTED.items():
    sub = df.filter(pl.col("initial_stop_atr") == stop)
    got = dict(sub.group_by("outcome_class").len().iter_rows())
    counts_match = got == exp
    stored = pl.read_parquet(BUILDER / "results" / STORED[stop]).select(
        "trade_id", "outcome_class", "realized_return_atr")
    joined = sub.select("trade_id", "outcome_class", "realized_return_atr").join(
        stored, on="trade_id", how="inner", suffix="_stored")
    cls_mismatch = joined.filter(
        pl.col("outcome_class") != pl.col("outcome_class_stored"))
    ret_mismatch = joined.filter(
        (pl.col("realized_return_atr") - pl.col("realized_return_atr_stored"))
        .abs() > 1e-9
    ).filter(
        pl.col("realized_return_atr").is_not_null()
        | pl.col("realized_return_atr_stored").is_not_null()
    )
    ok = counts_match and cls_mismatch.height == 0 and ret_mismatch.height == 0
    report["all_exact"] &= ok
    report["per_stop"][str(stop)] = {
        "population": sub.height,
        "expected": exp,
        "engine": got,
        "counts_exact": counts_match,
        "joined_rows": joined.height,
        "classification_mismatches_vs_stored": cls_mismatch.height,
        "realized_return_mismatches_vs_stored": ret_mismatch.height,
        "exact": ok,
        "mismatch_examples": cls_mismatch.head(5).to_dicts(),
    }

out = STUDY_DIR / "results" / "baseline_reconciliation.json"
out.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
