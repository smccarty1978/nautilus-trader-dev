"""Output Manager & Manifest Generator for NautilusTrader Execution.
===================================================================
Produces standardized run directories, manifests, and parquet artifacts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from backtests.nt_runtime.compiled_study_loader import CompiledStudyData
from backtests.nt_runtime.data_plan import DataPlan
from backtests.nt_runtime.run_plan import RunPlan
from backtests.nt_runtime.telemetry import TelemetrySnapshot


def compute_file_sha256(filepath: Path) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class OutputManager:
    """Manages deterministic run output paths and standardized run manifests."""

    def __init__(
        self,
        study_data: CompiledStudyData,
        data_plan: DataPlan,
        run_plan: RunPlan,
        output_base_dir: Optional[Path] = None,
        composite_seal_hash: Optional[str] = None,
        execution_manifest_sha256: Optional[str] = None,
    ) -> None:
        self.study_data = study_data
        self.data_plan = data_plan
        self.run_plan = run_plan
        self.composite_seal_hash = composite_seal_hash
        self.execution_manifest_sha256 = execution_manifest_sha256

        if output_base_dir is None:
            repo_root = Path(__file__).resolve().parents[2]
            output_base_dir = repo_root / "runs"

        self.run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{study_data.study_id}_{run_plan.stage.value}"
        self.run_dir = output_base_dir / self.run_id
        self.collection_dir = self.run_dir / "collection"
        self.audit_dir = self.run_dir / "audit"

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.collection_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        self.manifest_path = self.run_dir / "run_manifest.json"
        self.status_path = self.run_dir / "status.json"

        # Initialize initial manifest
        self._write_initial_manifest()

    def _write_initial_manifest(self) -> None:
        manifest_data = {
            "run_id": self.run_id,
            "study_id": self.study_data.study_id,
            "study_type": self.study_data.study_type,
            "spec_sha256": self.study_data.spec_sha256,
            "composite_seal_hash": self.composite_seal_hash,
            "execution_manifest_sha256": self.execution_manifest_sha256,
            "stage": self.run_plan.stage.value,
            "dates": {
                "start": self.run_plan.start_date,
                "end": self.run_plan.end_date,
                "warmup_start": self.data_plan.warmup_start_dt.isoformat(),
            },
            "instrument": {
                "symbol": self.data_plan.symbol,
                "venue": self.data_plan.venue,
                "instrument_id": self.data_plan.instrument_id,
            },
            "timestamp_contract": {
                "raw_timestamp_semantic": self.data_plan.raw_timestamp_semantic,
                "ts_init_delta_1s_ns": self.data_plan.ts_init_delta_1s_ns,
                "ts_init_delta_1m_ns": self.data_plan.ts_init_delta_1m_ns,
            },
            "start_time_utc": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING",
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

    def persist_collection(
        self,
        candidates_df: pd.DataFrame,
        observations_df: pd.DataFrame,
        telemetry: TelemetrySnapshot,
    ) -> Dict[str, Any]:
        """Saves collection parquets, updates status and manifest."""
        # Filter out warmup candidates strictly before start_dt or after end_dt
        start_ns = int(self.data_plan.start_dt.value)
        end_ns = int(self.data_plan.end_dt.value)

        if not candidates_df.empty and "observation_ts" in candidates_df.columns:
            candidates_df = candidates_df[
                (candidates_df["observation_ts"] >= start_ns) & (candidates_df["observation_ts"] <= end_ns)
            ].copy()

        if not observations_df.empty and "observation_ts" in observations_df.columns:
            observations_df = observations_df[
                (observations_df["observation_ts"] >= start_ns) & (observations_df["observation_ts"] <= end_ns)
            ].copy()

        # Strict contract-driven schema validation (features + metadata)
        expected_feats = self.study_data.spec.features.feature_list or []
        expected_sha = self.study_data.spec.features.feature_list_sha256
        declared_metadata = self.study_data.spec.features.metadata_columns or [
            "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index",
            "regime_age_seconds", "close", "atr", "running_mfe_atr", "running_mae_atr",
            "current_pnl_atr", "new_progress_windows", "retained_mfe_ratio", "triggering_1s_ts_init",
        ]
        allowed_columns = set(expected_feats) | set(declared_metadata)

        # Check for duplicate column names
        if len(candidates_df.columns) != len(set(candidates_df.columns)):
            raise ValueError("DUPLICATE_OUTPUT_COLUMNS: Candidates dataframe has duplicate column names!")

        # Check for unexpected surplus columns
        extra_cols = set(candidates_df.columns) - allowed_columns
        if extra_cols:
            raise ValueError(f"UNEXPECTED_OUTPUT_COLUMN: candidates dataframe contains undeclared columns: {sorted(list(extra_cols))}")

        # Check required metadata columns
        missing_meta = set(declared_metadata) - set(candidates_df.columns)
        if missing_meta and not candidates_df.empty:
            raise ValueError(f"MISSING_OUTPUT_METADATA: candidates dataframe missing declared metadata columns: {sorted(list(missing_meta))}")

        # Strict feature parity validation against StudySpec
        if expected_feats:
            # Extract features matching the contract's expected feature names
            emitted_feats = [c for c in candidates_df.columns if c in set(expected_feats)]
            emitted_sha = hashlib.sha256(json.dumps(emitted_feats).encode("utf-8")).hexdigest()

            if emitted_feats != expected_feats or (expected_sha and emitted_sha != expected_sha):
                raise ValueError(
                    f"Emitted candidate features mismatch frozen StudySpec contract!\n"
                    f"Expected ({len(expected_feats)} cols, sha={expected_sha}): {expected_feats[:5]}...\n"
                    f"Emitted ({len(emitted_feats)} cols, sha={emitted_sha}): {emitted_feats[:5]}..."
                )

        cand_path = self.collection_dir / "candidates.parquet"
        obs_path = self.collection_dir / "observations.parquet"

        candidates_df.to_parquet(cand_path, index=False)
        observations_df.to_parquet(obs_path, index=False)

        cand_hash = compute_file_sha256(cand_path)
        obs_hash = compute_file_sha256(obs_path)

        collection_manifest = {
            "run_id": self.run_id,
            "study_id": self.study_data.study_id,
            "candidates_count": len(candidates_df),
            "observations_count": len(observations_df),
            "candidates_sha256": cand_hash,
            "observations_sha256": obs_hash,
            "columns": {
                "candidates": list(candidates_df.columns),
                "observations": list(observations_df.columns),
            },
        }
        col_manifest_path = self.collection_dir / "collection_manifest.json"
        with open(col_manifest_path, "w", encoding="utf-8") as f:
            json.dump(collection_manifest, f, indent=2)

        # Update run_manifest and status.json
        status_data = {
            "run_id": self.run_id,
            "study_id": self.study_data.study_id,
            "status": "SUCCESS",
            "stage": self.run_plan.stage.value,
            "wall_time_seconds": round(telemetry.elapsed_seconds, 3),
            "total_bars_processed": telemetry.total_bars_processed,
            "candidates_count": len(candidates_df),
            "observations_count": len(observations_df),
            "throughput_bars_per_sec": round(telemetry.throughput_bars_per_sec, 1),
            "memory": {
                "baseline_process_rss_mb": telemetry.baseline_process_rss_mb,
                "peak_process_rss_mb": telemetry.peak_process_rss_mb,
                "rss_delta_mb": telemetry.rss_delta_mb,
                "python_tracemalloc_peak_mb": telemetry.python_tracemalloc_peak_mb,
            },
            "bars_breakdown": {
                "loaded": telemetry.bars_loaded_by_tf,
                "callbacks": telemetry.callbacks_by_tf,
                "ts_event_ranges": telemetry.ts_event_ranges_by_tf,
                "ts_init_ranges": telemetry.ts_init_ranges_by_tf,
            },
            "output_artifacts": {
                "candidates_parquet": str(cand_path),
                "observations_parquet": str(obs_path),
                "collection_manifest": str(col_manifest_path),
            },
            "end_time_utc": datetime.now(timezone.utc).isoformat(),
        }

        with open(self.status_path, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)

        # Re-read and update manifest
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        manifest_data.update({
            "status": "COMPLETED",
            "telemetry": {
                "wall_time_seconds": telemetry.elapsed_seconds,
                "total_bars_processed": telemetry.total_bars_processed,
                "throughput_bars_per_sec": telemetry.throughput_bars_per_sec,
                "baseline_process_rss_mb": telemetry.baseline_process_rss_mb,
                "peak_process_rss_mb": telemetry.peak_process_rss_mb,
                "rss_delta_mb": telemetry.rss_delta_mb,
                "python_tracemalloc_peak_mb": telemetry.python_tracemalloc_peak_mb,
                "bars_loaded": telemetry.bars_loaded_by_tf,
                "callbacks": telemetry.callbacks_by_tf,
            },
            "outputs": {
                "candidates_count": len(candidates_df),
                "candidates_sha256": cand_hash,
                "observations_count": len(observations_df),
                "observations_sha256": obs_hash,
            },
            "end_time_utc": datetime.now(timezone.utc).isoformat(),
        })

        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        return status_data
