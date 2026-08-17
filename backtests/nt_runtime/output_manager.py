"""Output Manager & Manifest Generator for NautilusTrader Execution.
===================================================================
Produces standardized run directories, manifests, and parquet artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from backtests.nt_runtime.compiled_study_loader import CompiledStudyData
from backtests.nt_runtime.data_plan import DataPlan
from backtests.nt_runtime.run_plan import RunPlan
from backtests.nt_runtime.telemetry import TelemetrySnapshot


CANDIDATE_KEY_COLUMNS = ["observation_ts", "regime_start_ns", "checkpoint_index"]


def reconcile_candidate_dispositions(
    candidates_df: pd.DataFrame,
    observations_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Proves every emitted candidate reached exactly one terminal disposition.

    The identity being checked::

        candidates == labeled_positive + labeled_negative + censored

    A candidate with no observation row is the failure this exists to catch: it is not a
    missing record, it is a member of the population that disappeared because its outcome
    never resolved. Selecting on that is selecting on the future.

    Reconciliation is on the full candidate key rather than on counts alone, so a dropped
    candidate offset by a duplicated one cannot net out to zero.
    """
    n_cand = len(candidates_df)
    n_obs = len(observations_df)
    report: Dict[str, Any] = {
        "candidates": n_cand,
        "observations": n_obs,
        "passed": True,
        "findings": [],
    }

    if n_cand == 0:
        report["passed"] = n_obs == 0
        if n_obs:
            report["findings"].append("observations emitted with no candidates")
        return report

    key_cols = [c for c in CANDIDATE_KEY_COLUMNS if c in candidates_df.columns
                and c in observations_df.columns]
    if not key_cols:
        report["passed"] = False
        report["findings"].append("no shared candidate key columns to reconcile on")
        return report

    cand_keys = set(map(tuple, candidates_df[key_cols].itertuples(index=False, name=None)))
    obs_keys = list(map(tuple, observations_df[key_cols].itertuples(index=False, name=None)))
    obs_key_set = set(obs_keys)

    undisposed = cand_keys - obs_key_set
    orphaned = obs_key_set - cand_keys
    duplicated = len(obs_keys) - len(obs_key_set)

    report["undisposed_candidates"] = len(undisposed)
    report["orphaned_observations"] = len(orphaned)
    report["duplicate_observations"] = duplicated

    if undisposed:
        report["passed"] = False
        report["findings"].append(
            f"{len(undisposed)} candidates reached no terminal disposition "
            f"(present in candidates, absent from observations)"
        )
    if orphaned:
        report["passed"] = False
        report["findings"].append(f"{len(orphaned)} observations reference no emitted candidate")
    if duplicated:
        report["passed"] = False
        report["findings"].append(f"{duplicated} candidates were disposed more than once")

    if "disposition" in observations_df.columns:
        counts = observations_df["disposition"].value_counts(dropna=False).to_dict()
        report["disposition_counts"] = {str(k): int(v) for k, v in counts.items()}
        total = sum(report["disposition_counts"].values())
        if total != n_cand:
            report["passed"] = False
            report["findings"].append(
                f"disposition total {total} != candidate count {n_cand}"
            )
    else:
        report["disposition_counts"] = None

    return report


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
            "pid": os.getpid(),
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

    def finalize_failed(self, error: BaseException, status: str = "FAILED") -> Dict[str, Any]:
        """Records a terminal status for a run that did not reach persistence (H2).

        Six of the ten ES acceptance runs were left at ``RUNNING`` with no ``status.json``
        and no outputs, because the manifest was only ever updated on the success path. An
        abandoned run and an in-flight run were indistinguishable, and neither could be
        told apart from a successful one by anything except the absence of a file.
        """
        now = datetime.now(timezone.utc).isoformat()
        status_data = {
            "run_id": self.run_id,
            "study_id": self.study_data.study_id,
            "status": status,
            "stage": self.run_plan.stage.value,
            "error_type": type(error).__name__,
            "error_message": str(error)[:2000],
            "end_time_utc": now,
        }
        with open(self.status_path, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception:
            manifest_data = {"run_id": self.run_id}
        manifest_data.update({
            "status": status,
            "error_type": type(error).__name__,
            "error_message": str(error)[:2000],
            "end_time_utc": now,
        })
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)
        return status_data

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

        # Declared feature contract <=> produced surface (C1). Column existence and an
        # ordered-name hash cannot see an all-null column; this can, and it consults the
        # registry's null policy rather than banning nulls outright.
        from scripts.check_feature_surface import validate_feature_surface

        surface_report = validate_feature_surface(candidates_df, expected_feats)

        # Candidate/observation reconciliation (E). A candidate that quietly failed to
        # reach a terminal disposition used to vanish from the observation surface
        # entirely, which is future-conditioned selection rather than a missing row.
        reconciliation = reconcile_candidate_dispositions(candidates_df, observations_df)

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
            "feature_surface_validation": surface_report.to_dict(),
            "candidate_disposition_reconciliation": reconciliation,
        }
        col_manifest_path = self.collection_dir / "collection_manifest.json"
        with open(col_manifest_path, "w", encoding="utf-8") as f:
            json.dump(collection_manifest, f, indent=2)

        # A collection whose declared features were not actually produced is not a
        # successful collection. The artifacts are still written -- they are the
        # evidence of what went wrong -- but the run is not filed as SUCCESS.
        run_status = (
            "SUCCESS" if (surface_report.passed and reconciliation["passed"])
            else "FAILED_VALIDATION"
        )

        # Update run_manifest and status.json
        status_data = {
            "run_id": self.run_id,
            "study_id": self.study_data.study_id,
            "status": run_status,
            "feature_surface_validation": surface_report.to_dict(),
            "candidate_disposition_reconciliation": reconciliation,
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
            "status": "COMPLETED" if run_status == "SUCCESS" else "FAILED_VALIDATION",
            "feature_surface_passed": surface_report.passed,
            "candidate_reconciliation_passed": reconciliation["passed"],
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
