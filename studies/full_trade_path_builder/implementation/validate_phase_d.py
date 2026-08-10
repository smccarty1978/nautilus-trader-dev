"""Deterministic Phase D summary/path and raw-catalog parity validation."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from .run_phase_a_collect import BAR_1S, CATALOG, atomic_json, sha256_file

NS = 1_000_000_000


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)


def sample_rows(paths: pd.DataFrame) -> pd.DataFrame:
    picks = [paths.iloc[0], paths.iloc[-1]]
    for direction in (-1, 1):
        subset = paths[paths.trade_direction == direction]
        if not subset.empty:
            picks.append(subset.iloc[0])
    for field in ("is_confirm_flip_boundary", "is_fallback_exit_boundary"):
        subset = paths[paths[field]]
        if not subset.empty:
            picks.append(subset.iloc[0])
    counts = paths.groupby("timestamp_close_ns").trade_id.nunique()
    overlap = counts[counts > 1]
    if not overlap.empty:
        picks.append(paths[paths.timestamp_close_ns == overlap.index[0]].iloc[0])
    return pd.DataFrame(picks).drop_duplicates(
        subset=["trade_id", "timestamp_close_ns"]
    )


def validate(root: Path, result: Path) -> dict:
    catalog = ParquetDataCatalog(str(CATALOG))
    failures = []
    raw_failures = []
    sample_records = []
    trades_checked = 0
    rows_checked = 0
    ambiguous = 0
    monthly = []
    source_bindings = []
    global_manifest = root / "global_path_manifest.json"
    if not global_manifest.exists():
        raise RuntimeError("Phase D global source manifest is missing")
    global_payload = json.loads(global_manifest.read_text())
    if global_payload.get("status") != "complete" or global_payload.get("month_count") != 60:
        raise RuntimeError("Phase D global source manifest is not complete")
    month_dirs = sorted(root.glob("entry_year=*/entry_month=*"))
    if len(month_dirs) != 60:
        raise RuntimeError(f"expected 60 Phase D source partitions, found {len(month_dirs)}")
    for month_dir in month_dirs:
        path_file = month_dir / "trade_paths.parquet"
        summary_file = month_dir / "trade_population.parquet"
        manifest_file = month_dir / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        if manifest.get("status") != "complete":
            raise RuntimeError(f"incomplete Phase D source partition: {month_dir}")
        if manifest.get("phase_d_identity") != global_payload.get("phase_d_identity"):
            raise RuntimeError(f"Phase D source identity mismatch: {month_dir}")
        if manifest.get("global_flip_ledger_sha256") != global_payload.get(
            "global_flip_ledger_sha256"
        ):
            raise RuntimeError(f"Phase D source flip-ledger mismatch: {month_dir}")
        path_hash = sha256_file(path_file)
        summary_hash = sha256_file(summary_file)
        if path_hash != manifest.get("path_sha256"):
            raise RuntimeError(f"Phase D source path hash mismatch: {path_file}")
        if summary_hash != manifest.get("summary_sha256"):
            raise RuntimeError(f"Phase D source summary hash mismatch: {summary_file}")
        paths = pq.read_table(path_file).to_pandas()
        summaries = pq.read_table(summary_file).to_pandas()
        rows_checked += len(paths)
        trades_checked += len(summaries)
        ambiguous += int((paths.intrabar_ordering == "ordering_ambiguous_same_bar").sum())
        by_trade = {key: frame.sort_values("path_sequence") for key, frame in paths.groupby("trade_id")}
        for summary in summaries.to_dict("records"):
            trade_id = summary["trade_id"]
            frame = by_trade.get(trade_id)
            if frame is None or frame.empty:
                failures.append({"trade_id": trade_id, "field": "missing_path"})
                continue
            checks = {
                "path_row_count": (len(frame), summary["path_row_count"]),
                "path_first_timestamp_ns": (
                    int(frame.iloc[0].timestamp_open_ns),
                    summary["path_first_timestamp_ns"],
                ),
                "path_final_timestamp_ns": (
                    int(frame.iloc[-1].timestamp_close_ns),
                    summary["path_final_timestamp_ns"],
                ),
                "full_trade_mfe_atr": (
                    float(frame.running_mfe_atr.max()),
                    summary["full_trade_mfe_atr"],
                ),
                "full_trade_mae_atr": (
                    float(-frame.running_mae_atr.min()),
                    summary["full_trade_mae_atr"],
                ),
                "full_trade_mfe_ns": (
                    (
                        int(summary["checkpoint_decision_ns"])
                        if float(frame.running_mfe_atr.max()) == 0.0
                        else int(
                            frame.loc[
                                frame.running_mfe_atr.idxmax(), "timestamp_close_ns"
                            ]
                        )
                    ),
                    summary["full_trade_mfe_ns"],
                ),
                "full_trade_mae_ns": (
                    (
                        int(summary["checkpoint_decision_ns"])
                        if float(frame.running_mae_atr.min()) == 0.0
                        else int(
                            frame.loc[
                                frame.running_mae_atr.idxmin(), "timestamp_close_ns"
                            ]
                        )
                    ),
                    summary["full_trade_mae_ns"],
                ),
            }
            if summary["path_is_complete"]:
                checks["fallback_exit_mark_return_atr"] = (
                    float(frame.iloc[-1].close_pnl_atr),
                    summary["fallback_exit_mark_return_atr"],
                )
            for field, (actual, expected) in checks.items():
                equal = actual == expected if isinstance(actual, int) else close(actual, expected)
                if not equal:
                    failures.append(
                        {
                            "trade_id": trade_id,
                            "field": field,
                            "actual": actual,
                            "expected": expected,
                        }
                    )
        samples = sample_rows(paths)
        start_ns = int(samples.timestamp_open_ns.min())
        end_ns = int(samples.timestamp_close_ns.max())
        bars = catalog.bars(
            bar_types=[BAR_1S],
            start=datetime.fromtimestamp(start_ns / NS, tz=timezone.utc),
            end=datetime.fromtimestamp(end_ns / NS, tz=timezone.utc),
        )
        source = {
            int(bar.ts_init): (
                bar.open.as_double(),
                bar.high.as_double(),
                bar.low.as_double(),
                bar.close.as_double(),
            )
            for bar in bars
        }
        for row in samples.itertuples(index=False):
            expected = source.get(int(row.timestamp_close_ns))
            actual = (float(row.open), float(row.high), float(row.low), float(row.close))
            passed = expected == actual
            record = {
                "partition": str(month_dir),
                "trade_id": row.trade_id,
                "timestamp_close_ns": int(row.timestamp_close_ns),
                "trade_direction": int(row.trade_direction),
                "source_ohlc": expected,
                "path_ohlc": actual,
                "passed": passed,
            }
            sample_records.append(record)
            if not passed:
                raw_failures.append(record)
        monthly.append(
            {
                "partition": str(month_dir),
                "trade_count": len(summaries),
                "path_row_count": len(paths),
                "raw_bar_samples": len(samples),
            }
        )
        source_bindings.append(
            {
                "partition": str(month_dir),
                "manifest_sha256": sha256_file(manifest_file),
                "path_sha256": path_hash,
                "summary_sha256": summary_hash,
            }
        )
    payload = {
        "status": "PASS" if not failures and not raw_failures else "FAIL",
        "trade_count": trades_checked,
        "path_row_count": rows_checked,
        "summary_path_failure_count": len(failures),
        "raw_bar_sample_count": len(sample_records),
        "raw_bar_failure_count": len(raw_failures),
        "ambiguous_same_bar_row_count": ambiguous,
        "source_global_manifest_sha256": sha256_file(global_manifest),
        "source_bindings": source_bindings,
        "sample_method": (
            "Deterministic first/last, first long/short, first confirmation/"
            "fallback boundary, and first overlapping timestamp per entry month."
        ),
        "monthly": monthly,
        "samples": sample_records,
        "summary_path_failures": failures[:100],
        "raw_bar_failures": raw_failures[:100],
    }
    atomic_json(payload, result)
    if payload["status"] != "PASS":
        raise RuntimeError(
            f"Phase D validation failed: summary={len(failures)} raw={len(raw_failures)}"
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-d-root", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    print(json.dumps(validate(Path(args.phase_d_root), Path(args.result)), indent=2))


if __name__ == "__main__":
    main()
