"""Exact global-integrity validation for finalized Phase B artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from .run_phase_a_collect import SEALED_BOUNDARY, atomic_json, sha256_file
from .phase_b_grid import canonical_partition_bounds, expected_rth_grid_ns

NS = 1_000_000_000
STEP = 5 * NS
RANK_COLUMNS = (
    "bullish_percentile", "bullish_decile", "bullish_is_top_10",
    "bullish_is_top_5", "bullish_is_top_2_5",
    "bearish_percentile", "bearish_decile", "bearish_is_top_10",
    "bearish_is_top_5", "bearish_is_top_2_5",
)


def expected_rth_grid(start: datetime, end: datetime) -> np.ndarray:
    start_ns, end_ns = int(start.timestamp() * NS), int(end.timestamp() * NS)
    return np.asarray(expected_rth_grid_ns(start_ns, end_ns), dtype=np.int64)


def _nullable_bool_consistent(
    seconds: np.ndarray, flag: list[bool | None], censored: np.ndarray, horizon: int
) -> bool:
    for value, actual, is_censored in zip(seconds, flag, censored, strict=True):
        if is_censored:
            if actual is not None:
                return False
        else:
            expected = bool(math.isfinite(value) and value <= horizon)
            if actual is None or bool(actual) != expected:
                return False
    return True


def validate(root: Path, result_path: Path) -> dict:
    manifest_paths = sorted(root.glob("year=*/month=*/manifest.json"))
    if len(manifest_paths) != 60:
        raise RuntimeError(f"expected 60 manifests, found {len(manifest_paths)}")
    actual_partitions = {
        (
            int(path.parent.parent.name.removeprefix("year=")),
            int(path.parent.name.removeprefix("month=")),
        )
        for path in manifest_paths
    }
    expected_partitions = {
        (year, month) for year in range(2021, 2026) for month in range(1, 13)
    }
    if actual_partitions != expected_partitions:
        raise RuntimeError(
            f"non-canonical partition set; "
            f"missing={sorted(expected_partitions-actual_partitions)} "
            f"extra={sorted(actual_partitions-expected_partitions)}"
        )
    global_manifest = json.loads(
        (root / "global_label_manifest.json").read_text(encoding="utf-8")
    )
    correction = json.loads(
        (root / "missing_scope_correction_manifest.json").read_text(encoding="utf-8")
    )
    reconciliation = json.loads(
        (root / "missing_grid_reconciliation_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if global_manifest.get("status") != "complete":
        raise RuntimeError("global label manifest is not complete")
    if correction.get("status") != "complete":
        raise RuntimeError("missing-scope correction is not complete")
    if reconciliation.get("status") != "complete":
        raise RuntimeError("missing-grid reconciliation is not complete")

    failures: list[str] = []
    total_rows = total_missing = total_neutral = total_censored = 0
    reconciliation_rows_before = reconciliation_rows_after = 0
    reconciliation_rewritten = 0
    runtime_identity = config_hash = catalog_identity = correction_hash = None
    flip_by_key: dict[tuple[int, int], dict] = {}
    partition_results = []

    for manifest_path in manifest_paths:
        partition = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        start = datetime.fromisoformat(manifest["start"])
        end = datetime.fromisoformat(manifest["end"])
        score_path = partition / "canonical_model_scores.parquet"
        missing_path = partition / "missing_dispatch.parquet"
        flip_path = partition / "confirmed_flips.parquet"
        prefix = str(partition.relative_to(root))

        def fail(message: str) -> None:
            failures.append(f"{prefix}: {message}")

        year = int(partition.parent.name.removeprefix("year="))
        month = int(partition.name.removeprefix("month="))
        expected_start, expected_end = canonical_partition_bounds(year, month)
        if start != expected_start or end != expected_end:
            fail("non-canonical partition interval")
        if manifest.get("status") != "complete":
            fail("status is not complete")
        if manifest.get("warmup_days") != 4:
            fail("warmup_days is not 4")
        if manifest.get("labels_finalized_globally") is not True:
            fail("labels were not globally finalized")
        for path, field in (
            (score_path, "canonical_model_scores_sha256"),
            (missing_path, "missing_dispatch_sha256"),
            (flip_path, "confirmed_flips_sha256"),
        ):
            if sha256_file(path) != manifest.get(field):
                fail(f"hash mismatch for {path.name}")

        for name, value in (
            ("runtime_identity", manifest.get("runtime_identity")),
            ("config_sha256", manifest.get("config_sha256")),
            ("catalog_identity", manifest.get("catalog_identity")),
            (
                "missing_scope_correction_code_sha256",
                manifest.get("missing_scope_correction_code_sha256"),
            ),
        ):
            baseline_name = {
                "runtime_identity": "runtime_identity",
                "config_sha256": "config_hash",
                "catalog_identity": "catalog_identity",
                "missing_scope_correction_code_sha256": "correction_hash",
            }[name]
            current = locals()[baseline_name]
            if current is None:
                if baseline_name == "runtime_identity":
                    runtime_identity = value
                elif baseline_name == "config_hash":
                    config_hash = value
                elif baseline_name == "catalog_identity":
                    catalog_identity = value
                else:
                    correction_hash = value
            elif value != current:
                fail(f"mixed {name}")
        if manifest.get("missing_scope") != "[partition_start,partition_end)":
            fail("missing diagnostics are not declared partition-scoped")
        if manifest.get("missing_grid_reconciliation_status") != "complete":
            fail("missing-grid reconciliation is not complete")
        if (
            manifest.get("missing_grid_reconciliation_code_sha256")
            != reconciliation.get("reconciliation_code_sha256")
        ):
            fail("missing-grid reconciliation code is not globally bound")
        required_reconciliation_fields = (
            "missing_grid_pre_reconciliation_sha256",
            "missing_grid_pre_reconciliation_rows",
            "missing_grid_reconciled_sha256",
            "missing_grid_reconciled_rows",
        )
        if any(manifest.get(field) is None for field in required_reconciliation_fields):
            fail("missing-grid reconciliation journal is incomplete")
        else:
            if (
                manifest["missing_grid_reconciled_sha256"]
                != manifest["missing_dispatch_sha256"]
            ):
                fail("reconciled target hash differs from active missing hash")
            if manifest["missing_grid_reconciled_rows"] != manifest["n_missing"]:
                fail("reconciled target row count differs from active count")
            before = manifest["missing_grid_pre_reconciliation_rows"]
            after = manifest["missing_grid_reconciled_rows"]
            reconciliation_rows_before += before
            reconciliation_rows_after += after
            reconciliation_rewritten += int(
                manifest["missing_grid_pre_reconciliation_sha256"]
                != manifest["missing_grid_reconciled_sha256"]
            )

        table = pq.read_table(score_path)
        keys = table["checkpoint_decision_ns"].to_numpy()
        missing = pq.read_table(
            missing_path, columns=["checkpoint_decision_ns"]
        )["checkpoint_decision_ns"].to_numpy()
        expected = expected_rth_grid(start, end)
        start_ns, end_ns = int(start.timestamp() * NS), int(end.timestamp() * NS)
        if len(keys) != manifest.get("n_rows"):
            fail("score row count differs from manifest")
        if len(missing) != manifest.get("n_missing"):
            fail("missing row count differs from manifest")
        if len(keys) and (
            np.any(keys[1:] <= keys[:-1])
            or np.any(keys % STEP != 0)
            or keys[0] < start_ns
            or keys[-1] >= end_ns
        ):
            fail("score keys are non-monotonic, off-grid, or out of interval")
        if len(missing) and (
            len(np.unique(missing)) != len(missing)
            or np.any(missing % STEP != 0)
            or missing.min() < start_ns
            or missing.max() >= end_ns
        ):
            fail("missing keys are duplicate, off-grid, or out of interval")
        observed = np.union1d(keys, missing)
        if len(np.intersect1d(keys, missing)) or not np.array_equal(observed, expected):
            fail("score plus missing keys do not exactly reconcile to RTH grid")
        if not np.array_equal(table["timestamp_ns"].to_numpy(), keys):
            fail("timestamp_ns differs from checkpoint_decision_ns")
        if table["session"].to_pylist() != ["RTH"] * len(table):
            fail("non-RTH session value")
        for column in RANK_COLUMNS:
            if table[column].null_count != len(table):
                fail(f"{column} is not globally null")
        if any(
            value != "NO_PRE_STUDY_FROZEN_RANK_REFERENCE"
            for value in table["bullish_rank_unavailable_reason"].to_pylist()
        ):
            fail("unexpected Bullish rank unavailable reason")
        if any(
            value != "NO_PRE_STUDY_FROZEN_RANK_REFERENCE"
            for value in table["bearish_rank_unavailable_reason"].to_pylist()
        ):
            fail("unexpected Bearish rank unavailable reason")

        regime = table["prevailing_regime"].to_numpy()
        censored300 = table["label_300_is_right_censored"].to_numpy()
        censored600 = table["label_600_is_right_censored"].to_numpy()
        if not np.array_equal(censored600, table["label_is_right_censored"].to_numpy()):
            fail("shared censor flag differs from 600-second censor flag")
        bull_seconds = table["seconds_to_next_bullish_confirm_flip"].to_numpy(
            zero_copy_only=False
        )
        bear_seconds = table["seconds_to_next_bearish_confirm_flip"].to_numpy(
            zero_copy_only=False
        )
        for seconds, prefix_name in (
            (bull_seconds, "bullish"),
            (bear_seconds, "bearish"),
        ):
            if not _nullable_bool_consistent(
                seconds,
                table[f"{prefix_name}_confirm_within_300s"].to_pylist(),
                censored300,
                300,
            ):
                fail(f"{prefix_name} 300-second label inconsistency")
            if not _nullable_bool_consistent(
                seconds,
                table[f"{prefix_name}_confirm_within_600s"].to_pylist(),
                censored600,
                600,
            ):
                fail(f"{prefix_name} 600-second label inconsistency")

        total_rows += len(keys)
        total_missing += len(missing)
        total_neutral += int(np.count_nonzero(regime == 0))
        total_censored += int(np.count_nonzero(censored600))
        for row in pq.read_table(flip_path).to_pylist():
            flip_by_key[(row["confirm_flip_ns"], row["new_direction"])] = row
        partition_results.append(
            {
                "partition": prefix,
                "rows": len(keys),
                "missing": len(missing),
                "expected_grid": len(expected),
                "failures": sum(item.startswith(prefix + ":") for item in failures),
            }
        )

    flips = sorted(flip_by_key.values(), key=lambda row: row["confirm_flip_ns"])
    flip_hash = hashlib.sha256(
        json.dumps(flips, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if total_rows != global_manifest.get("row_count"):
        failures.append("global row count mismatch")
    if len(flips) != global_manifest.get("unique_flip_count"):
        failures.append("global flip count mismatch")
    if flip_hash != global_manifest.get("global_flip_ledger_sha256"):
        failures.append("global flip-ledger hash mismatch")
    if global_manifest.get("observation_end_ns") != int(
        SEALED_BOUNDARY.timestamp() * NS
    ):
        failures.append("global observation end differs from sealed boundary")
    if reconciliation.get("partition_count") != len(manifest_paths):
        failures.append("global reconciliation partition count mismatch")
    if reconciliation.get("rows_before") != reconciliation_rows_before:
        failures.append("global reconciliation source-row aggregate mismatch")
    if reconciliation.get("rows_after") != reconciliation_rows_after:
        failures.append("global reconciliation target-row aggregate mismatch")
    if (
        reconciliation.get("rows_added")
        != reconciliation_rows_after - reconciliation_rows_before
    ):
        failures.append("global reconciliation added-row aggregate mismatch")
    if reconciliation.get("partitions_rewritten") != reconciliation_rewritten:
        failures.append("global reconciliation rewritten-count mismatch")

    result = {
        "status": "PASS" if not failures else "FAIL",
        "partition_count": len(manifest_paths),
        "row_count": total_rows,
        "missing_dispatch_count": total_missing,
        "unique_flip_count": len(flips),
        "neutral_or_unconfirmed_rows": total_neutral,
        "right_censored_600_rows": total_censored,
        "global_flip_ledger_sha256": flip_hash,
        "failures": failures,
        "partitions": partition_results,
    }
    atomic_json(result, result_path)
    if failures:
        raise RuntimeError(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition-root", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    print(json.dumps(validate(Path(args.partition_root), Path(args.result)), indent=2))


if __name__ == "__main__":
    main()
