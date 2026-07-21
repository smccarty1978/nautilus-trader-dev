"""Full-year scalar-versus-batched W4 equivalence check."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE.parent / "regime_sequence_chop_context"
sys.path[:0] = [str(HERE), str(UPSTREAM)]

from CODEX_5_X_common import AUDIT, sha256_file, write_json, year_atlas_path  # noqa: E402
from train_weakness_model import CENTER_FEATS, LOCAL_FEATS, SEQUENCE_FEATS  # noqa: E402

SCALAR = HERE / "_work" / "CODEX_5_X_repaired_years" / "CODEX_5_X_scalar_reference_2021.parquet"
BATCHED = year_atlas_path(2021)
FEATURE_SOURCE = UPSTREAM / "train_weakness_model.py"
RTOL = 1e-12
ATOL = 1e-12


def main() -> None:
    keys = ["regime_start_ns", "observation_time", "direction"]
    if (len(CENTER_FEATS) != 49 or len(SEQUENCE_FEATS) != 100 or len(LOCAL_FEATS) != 5
            or len(set(CENTER_FEATS)) != 49
            or len(set(SEQUENCE_FEATS)) != 100
            or len(set(LOCAL_FEATS)) != 5
            or len(set(CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS)) != 154):
        raise RuntimeError("unexpected or duplicate scalar/batched feature inventory")
    model_features = CENTER_FEATS + SEQUENCE_FEATS + LOCAL_FEATS
    compare = keys + model_features
    left = pq.ParquetFile(SCALAR)
    right = pq.ParquetFile(BATCHED)
    if left.metadata.num_rows != right.metadata.num_rows:
        raise RuntimeError("scalar/batched row counts differ")
    max_abs = {col: 0.0 for col in model_features}
    mismatch = {col: 0 for col in model_features}
    key_mismatches = 0
    left_table = pq.read_table(SCALAR, columns=compare).combine_chunks()
    right_table = pq.read_table(BATCHED, columns=compare).combine_chunks()
    left_batches = left_table.to_batches(max_chunksize=50_000)
    right_batches = right_table.to_batches(max_chunksize=50_000)
    batches = 0
    for lb, rb in zip(left_batches, right_batches, strict=True):
        if lb.num_rows != rb.num_rows:
            raise RuntimeError("scalar/batched rechunk lengths differ")
        l = lb.to_pandas()
        r = rb.to_pandas()
        batches += 1
        key_mismatches += int((l[keys].to_numpy() != r[keys].to_numpy()).sum())
        for col in model_features:
            a = l[col].to_numpy(dtype=float)
            b = r[col].to_numpy(dtype=float)
            both_nan = np.isnan(a) & np.isnan(b)
            valid = ~(both_nan)
            equal_nan_pattern = np.isnan(a) == np.isnan(b)
            close = np.isclose(a, b, rtol=RTOL, atol=ATOL, equal_nan=True)
            mismatch[col] += int((~close).sum())
            if valid.any() and equal_nan_pattern.all():
                max_abs[col] = max(max_abs[col], float(np.nanmax(np.abs(a - b))))

    atr_alias_mismatches = 0
    invalid_atr = 0
    for batch in right.iter_batches(
        batch_size=100_000,
        columns=["atr", "atr_at_entry", "atr_at_checkpoint"],
    ):
        d = batch.to_pandas()
        atr_alias_mismatches += int((
            d["atr"].to_numpy(dtype=float)
            != d["atr_at_checkpoint"].to_numpy(dtype=float)
        ).sum())
        values = d[["atr_at_entry", "atr_at_checkpoint"]].to_numpy(dtype=float)
        invalid_atr += int((~np.isfinite(values) | (values <= 0)).sum())

    total_value_mismatches = int(sum(mismatch.values()))
    result = {
        "status": "PASS" if (
            key_mismatches == total_value_mismatches
            == atr_alias_mismatches == invalid_atr == 0
        ) else "FAIL",
        "rows": left.metadata.num_rows,
        "batches": batches,
        "key_mismatches": key_mismatches,
        "value_mismatches": total_value_mismatches,
        "mismatches_by_column": mismatch,
        "max_abs_difference_by_column": max_abs,
        "atr_alias_mismatches": atr_alias_mismatches,
        "invalid_atr_cells": invalid_atr,
        "rtol": RTOL,
        "atol": ATOL,
        "ordered_key_columns": keys,
        "ordered_local_features": LOCAL_FEATS,
        "ordered_center_features": CENTER_FEATS,
        "ordered_sequence_features": SEQUENCE_FEATS,
        "local_feature_count": len(LOCAL_FEATS),
        "center_feature_count": len(CENTER_FEATS),
        "sequence_feature_count": len(SEQUENCE_FEATS),
        "scalar_sha256": sha256_file(SCALAR),
        "batched_sha256": sha256_file(BATCHED),
        "comparator_sha256": sha256_file(Path(__file__).resolve()),
        "feature_definition_sha256": sha256_file(FEATURE_SOURCE),
    }
    write_json(AUDIT / "CODEX_5_X_batched_scalar_equivalence_2021.json", result)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in {"mismatches_by_column", "max_abs_difference_by_column"}},
                     indent=2))
    if result["status"] != "PASS":
        raise RuntimeError("full-year scalar/batched equivalence failed")


if __name__ == "__main__":
    main()
