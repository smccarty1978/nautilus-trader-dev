"""Post-attachment reporting for Part D: consumes attach_features.py's
`_work/full_{year}.parquet` outputs and `results/full_manifest.json`, and
produces the required feature-join/availability/NaN-rate reports plus a
top-level manifest. Read-only w.r.t. the attached data -- no new features
computed here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK, RESULTS = HERE / "_work", HERE / "results"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from features.registry import resolve_feature_request, resolve_runtime_feature_aliases  # noqa: E402

NEW_FAMILIES = ("ohlcv_est_delta", "price_level_context")
_RESOLVED_FEATURES = {n: resolve_feature_request(n) for n in resolve_runtime_feature_aliases()}
NEW_FEATURE_COLS = [n for n, d in _RESOLVED_FEATURES.items() if set(d["family"] if isinstance(d["family"], list) else (d["family"],)) & set(NEW_FAMILIES)]

YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
KNOWN_CROSSING_CONTROLS = {2025: 650, 2026: 222}


def main() -> None:
    attach_manifest = json.loads((RESULTS / "full_manifest.json").read_text(encoding="utf-8"))

    join_rows, avail_rows, nan_rows = [], [], []
    for year in YEARS:
        path = WORK / f"full_{year}.parquet"
        df = pd.read_parquet(path)
        report = attach_manifest[str(year)]

        present_cols = [c for c in NEW_FEATURE_COLS if c in df.columns]
        missing_cols = [c for c in NEW_FEATURE_COLS if c not in df.columns]
        join_rate = float(df[present_cols].notna().any(axis=1).mean()) if present_cols else 0.0

        join_rows.append({
            "year": year, "surface_rows": report["surface_rows"],
            "feature_rows_produced": report["feature_rows_produced"],
            "row_count_unchanged": report["row_count_unchanged"],
            "labels_unchanged": report["labels_unchanged"],
            "duplicate_rows": report["duplicate_rows"],
            "provenance_violations": report["provenance_violations"],
            "gap_snapped_checkpoints": report["gap_snapped_checkpoints"],
            "unmatched_before_data_start": report["unmatched_before_data_start"],
            "new_feature_columns_present": len(present_cols),
            "new_feature_columns_missing": len(missing_cols),
            "join_rate_any_new_feature_present": join_rate,
        })

        for col in present_cols:
            s = df[col]
            if s.dtype == object or str(s.dtype) == "bool":
                # bool/str/enum columns: availability rate, not a NaN rate.
                avail = float(s.notna().mean())
            else:
                avail = float(s.notna().mean())
            avail_rows.append({"year": year, "feature": col, "availability_rate": avail})
            if pd.api.types.is_numeric_dtype(s):
                nan_rows.append({"year": year, "feature": col,
                                 "nan_rate": float(s.isna().mean()),
                                 "n": len(s), "n_nan": int(s.isna().sum())})

    join_df = pd.DataFrame(join_rows)
    avail_df = pd.DataFrame(avail_rows)
    nan_df = pd.DataFrame(nan_rows)

    join_df.to_csv(RESULTS / "feature_join_summary.csv", index=False)
    avail_df.to_csv(RESULTS / "feature_availability_by_year.csv", index=False)
    nan_df.to_csv(RESULTS / "feature_nan_rates.csv", index=False)

    all_row_counts_unchanged = bool(join_df["row_count_unchanged"].all())
    all_labels_unchanged = bool(join_df["labels_unchanged"].all())
    all_no_duplicates = bool((join_df["duplicate_rows"] == 0).all())
    all_no_provenance_violations = bool((join_df["provenance_violations"] == 0).all())
    all_features_present = bool((join_df["new_feature_columns_missing"] == 0).all())

    manifest = {
        "years": list(YEARS),
        "total_new_features_expected": len(NEW_FEATURE_COLS),
        "families": {fam: sum(1 for n in NEW_FEATURE_COLS if fam in (_RESOLVED_FEATURES[n]["family"] if isinstance(_RESOLVED_FEATURES[n]["family"], list) else (_RESOLVED_FEATURES[n]["family"],)))
                    for fam in NEW_FAMILIES},
        "all_row_counts_unchanged": all_row_counts_unchanged,
        "all_labels_unchanged": all_labels_unchanged,
        "all_no_duplicate_rows": all_no_duplicates,
        "all_no_provenance_violations": all_no_provenance_violations,
        "all_expected_feature_columns_present": all_features_present,
        "per_year": join_rows,
    }
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print(join_df.to_string(index=False))
    print()
    print(f"All row counts unchanged: {all_row_counts_unchanged}")
    print(f"All labels unchanged: {all_labels_unchanged}")
    print(f"All no duplicate rows: {all_no_duplicates}")
    print(f"All no provenance violations: {all_no_provenance_violations}")
    print(f"All expected feature columns present: {all_features_present}")


if __name__ == "__main__":
    main()
