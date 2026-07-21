"""Phase 4 - data-readiness + directionality gate. STOP before training if any
check fails. Writes data_readiness.csv, label_quality_by_year.csv,
feature_availability.csv (directionality_audit.csv is produced in Phase 0).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

STUDY = Path(__file__).resolve().parents[1]
WORK, RESULTS = STUDY / "_work", STUDY / "results"
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
TARGET = "bullish_regime_flip_within_300s"
TOP100 = json.load(open(RESULTS / "top100_feature_manifest.json"))["feature_names_in_order"]
# Columns that must NEVER be inside the model feature matrix (outcome/future).
FORBIDDEN_IN_MATRIX = {"confirm_flip_ns", "time_to_bullish_flip_s", "bullish_flip_within_600s",
                       TARGET, "fill_ts", "fill_px", "regime_end_ns"}


def main():
    checks, readiness, label_quality, availability = {}, [], [], []
    all_ok = True
    for y in YEARS:
        df = pd.read_parquet(WORK / f"prepared_long_{y}.parquet")
        missing = [f for f in TOP100 if f not in df.columns]
        obj = [f for f in TOP100 if f in df.columns and df[f].dtype == object]
        leak = [f for f in TOP100 if f in FORBIDDEN_IN_MATRIX]
        dir_ok = bool((df["prevailing_direction"] == -1).all() and (df["entry_direction"] == 1).all())
        pos = int(df[TARGET].sum())
        readiness.append({
            "year": y, "rows": len(df), "distinct_regimes": int(df["regime_start_ns"].nunique()),
            "top100_all_present": not missing, "n_missing_features": len(missing),
            "n_object_dtype_features": len(obj), "n_forbidden_in_matrix": len(leak),
            "direction_minus1_only": dir_ok,
            "positive_count": pos, "positive_rate": round(pos / len(df), 5),
            "mean_rows_per_regime": round(len(df) / df["regime_start_ns"].nunique(), 3),
        })
        label_quality.append({
            "year": y, "rows": len(df), "positive_count": pos,
            "positive_rate": round(pos / len(df), 5),
            "within_600s_rate": round(float(df["bullish_flip_within_600s"].mean()), 5),
            "median_time_to_flip_s": round(float(df["time_to_bullish_flip_s"].median()), 2),
            "min_time_to_flip_s": round(float(df["time_to_bullish_flip_s"].min()), 2),
            "label_dtype": str(df[TARGET].dtype), "label_values": sorted(df[TARGET].unique().tolist()),
        })
        for f in TOP100:
            availability.append({"year": y, "feature": f,
                                 "present": f in df.columns,
                                 "null_rate": round(float(df[f].isna().mean()), 6) if f in df.columns else None})
        year_ok = (not missing and not obj and not leak and dir_ok
                   and df[TARGET].isin([0, 1]).all() and 0.02 < pos / len(df) < 0.98)
        all_ok = all_ok and year_ok
        checks[y] = year_ok

    pd.DataFrame(readiness).to_csv(RESULTS / "data_readiness.csv", index=False)
    pd.DataFrame(label_quality).to_csv(RESULTS / "label_quality_by_year.csv", index=False)
    pd.DataFrame(availability).to_csv(RESULTS / "feature_availability.csv", index=False)
    verdict = "PASS" if all_ok else "FAIL"
    # Disclosed carry-forward residual (W2): timing-unverified features inherited
    # from the short-side reduction study. Non-blocking, recorded not hidden.
    flist = pd.read_csv(RESULTS / "top100_feature_list.csv")
    timing_unverified = flist[flist["timing_status"] == "TIMING_UNVERIFIED"]["feature_name"].tolist()
    (RESULTS / "phase4_gate_verdict.json").write_text(
        json.dumps({"verdict": verdict, "per_year_ok": checks,
                    "timing_unverified_features_disclosed": timing_unverified,
                    "timing_unverified_note": "Inherited disclosed residual from the "
                    "runtime_constrained_f3_feature_reduction study (regime-relative "
                    "accumulated A4 family). Non-blocking; flagged for provenance, "
                    "same treatment as the short-side model."}, indent=2), encoding="utf-8")
    print(pd.DataFrame(readiness).to_string(index=False))
    print(f"\nPHASE 4 GATE: {verdict}")
    if not all_ok:
        raise SystemExit("PHASE 4 GATE FAILED - do not train")


if __name__ == "__main__":
    main()
