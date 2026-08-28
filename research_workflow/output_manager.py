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
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtests.nt_runtime.compiled_study_loader import CompiledStudyData
from backtests.nt_runtime.data_plan import DataPlan
from backtests.nt_runtime.run_plan import RunPlan
from backtests.nt_runtime.telemetry import TelemetrySnapshot


CANDIDATE_KEY_COLUMNS = ["observation_ts", "regime_start_ns", "checkpoint_index"]

# Canonical output metadata contract used when a study declares no explicit
# ``features.metadata_columns``. Mirrored (deliberately, to avoid importing the sealed
# runtime) by research/analysis/identity.DEFAULT_METADATA_COLUMNS; READINESS R7 must
# validate its synthetic fixture against THIS list, not an empty fallback of its own.
DEFAULT_METADATA_COLUMNS: Tuple[str, ...] = (
    "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index",
    "regime_age_seconds", "close", "atr", "running_mfe_atr", "running_mae_atr",
    "current_pnl_atr", "new_progress_windows", "retained_mfe_ratio", "triggering_1s_ts_init",
)

# Single canonical output-interface contract (STRATEGY_OUTPUT_INTERFACE_MISSING). Named
# here -- not in backtests/nt_runtime/modes/collect.py -- so a second consumer (READINESS
# R6) can verify the same contract against a strategy instance without either reimplementing
# the attribute list or importing the collect-mode orchestrator.
CANDIDATES_INTERFACE_ATTRS = (
    "get_candidates_dataframe", "get_candidates_df", "candidates_df", "candidates_dataframe",
)
OBSERVATIONS_INTERFACE_ATTRS = (
    "get_observations_dataframe", "get_observations_df", "observations_df", "observations_dataframe",
)


def resolve_collection_allowed_feature_aliases(features_spec: Any, *, authority: str = "active") -> List[str]:
    """Shared collection contract surface for persistence and productive READINESS."""
    from features.registry import FeatureInstance, resolve_feature_instances, resolve_source_universe
    source = getattr(features_spec, "source", None)
    feature_list = getattr(features_spec, "feature_list", None) or []
    instances = []
    for item in (getattr(features_spec, "instances", None) or []):
        instances.append(FeatureInstance(
            str(item["feature"]), dict(item.get("parameters", {})), item.get("physical_alias")
        ))
    resolved = resolve_feature_instances(source, tuple(instances), legacy_mode=False) if instances else []
    # Explicit FeatureInstances define a study's bounded output contract.  Do not
    # silently expand it to the global canonical definition universe merely because
    # ``selection.source`` is present; that would reintroduce the instance-vs-library
    # ambiguity this resolver is meant to eliminate.
    if instances:
        return sorted(set(feature_list) | {item["physical_alias"] for item in resolved})
    return sorted(set(feature_list) | set(resolve_source_universe(source, authority=authority)))


def extract_strategy_dataframe(strat: Any, attr_names: Tuple[str, ...]) -> Tuple[pd.DataFrame, bool]:
    """Extracts a collected surface from a strategy generically.

    Returns whether any matching attribute/method was found at all, distinct from "found
    but empty" -- a strategy with no output interface is unverifiable, not merely
    unproductive.
    """
    for name in attr_names:
        val = getattr(strat, name, None)
        if val is not None:
            if callable(val):
                res = val()
                if isinstance(res, pd.DataFrame):
                    return res, True
            elif isinstance(val, pd.DataFrame):
                return val, True
    return pd.DataFrame(), False


def verify_strategy_output_interface(
    strategy: Any, bars_loaded_total: int
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Fails closed rather than silently reporting zero activity: if bars genuinely
    loaded but the strategy exposes no output interface at all, we cannot tell a
    legitimately empty result apart from real processing that was never surfaced.

    Returns (candidates_df, observations_df) extracted from the strategy. Raises
    RuntimeError("STRATEGY_OUTPUT_INTERFACE_MISSING: ...") when bars loaded but an
    interface is absent.
    """
    candidates_df, candidates_interface_found = extract_strategy_dataframe(
        strategy, CANDIDATES_INTERFACE_ATTRS
    )
    observations_df, observations_interface_found = extract_strategy_dataframe(
        strategy, OBSERVATIONS_INTERFACE_ATTRS
    )

    if bars_loaded_total > 0 and not candidates_interface_found:
        raise RuntimeError(
            f"STRATEGY_OUTPUT_INTERFACE_MISSING: {bars_loaded_total} bars were loaded into the "
            f"engine but {type(strategy).__name__} implements none of "
            f"{'/'.join(CANDIDATES_INTERFACE_ATTRS)}. Cannot verify whether the loaded bars "
            f"were processed; refusing to report a candidates count."
        )
    if bars_loaded_total > 0 and not observations_interface_found:
        raise RuntimeError(
            f"STRATEGY_OUTPUT_INTERFACE_MISSING: {bars_loaded_total} bars were loaded into the "
            f"engine but {type(strategy).__name__} implements none of "
            f"{'/'.join(OBSERVATIONS_INTERFACE_ATTRS)}. Cannot verify whether the loaded bars "
            f"were processed; refusing to report an observations count."
        )
    return candidates_df, observations_df


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

    # D1: the full candidate key is required on both sides, at any row count -- including
    # zero rows. A key derived from whichever columns happen to survive on both sides can
    # silently narrow (even to an empty key set) instead of failing closed. This check runs
    # before the n_cand == 0 branch below, so a malformed empty observations_df (missing
    # the matching key contract) cannot reach the "0 candidates == 0 observations" identity
    # by accident -- that identity is only valid once both schemas are proven sound.
    missing_cand_key = [c for c in CANDIDATE_KEY_COLUMNS if c not in candidates_df.columns]
    missing_obs_key = [c for c in CANDIDATE_KEY_COLUMNS if c not in observations_df.columns]
    if missing_cand_key or missing_obs_key:
        report["passed"] = False
        if missing_cand_key:
            report["findings"].append(
                f"candidates dataframe missing required candidate key column(s): {missing_cand_key}"
            )
        if missing_obs_key:
            report["findings"].append(
                f"observations dataframe missing required matching key column(s): {missing_obs_key}"
            )
        return report

    if n_cand == 0:
        report["passed"] = n_obs == 0
        if n_obs:
            report["findings"].append("observations emitted with no candidates")
        return report

    key_cols = CANDIDATE_KEY_COLUMNS
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


def reconcile_population_funnel(
    total_population_checkpoints: Optional[int],
    declared_contract_exclusions_in_run: Optional[int],
    implementation_only_exclusions: Optional[int],
    candidates_emitted_raw: Optional[int],
    candidates_raw_count: int,
    candidates_persisted_count: int,
) -> Optional[Dict[str, Any]]:
    """Proves the collector's observed population funnel (D8) reconciles exactly.

    Required identity::

        total_population_checkpoints
        == declared_contract_exclusions + implementation_only_exclusions + candidates_emitted

    D8 defines total_population_checkpoints over every 5s-aligned checkpoint for which a
    completed 1s bar was actually dispatched -- this includes the engine's pre-start
    warmup window (see engine_builder.ExecutionMode.warmup_dispatched), which this
    function's caller separately trims candidates_df/observations_df against
    [start_dt, end_dt] for. A candidate emitted during warmup is still a real population
    member: it did not fail a declared eligibility gate, it was excluded from the
    persisted surface by the study's own declared collection-window contract. It is
    therefore folded into declared_contract_exclusions (not silently dropped, and not
    counted as a candidate the persisted output never contains) so the identity above
    holds against the actual persisted row count (candidates_persisted_count), per
    Packet E's exact-parity requirement.

    Returns None when the strategy does not expose population-funnel telemetry
    (total_population_checkpoints is None) -- there is nothing to reconcile, and this is
    not a defect for the majority of strategies that predate this instrumentation.

    Raises ValueError (hard fail, never a warning) if the observed counts are internally
    inconsistent or the identity does not balance exactly.
    """
    if total_population_checkpoints is None:
        return None

    declared_contract_exclusions_in_run = declared_contract_exclusions_in_run or 0
    implementation_only_exclusions = implementation_only_exclusions or 0
    candidates_emitted_raw = candidates_emitted_raw or 0

    if candidates_raw_count != candidates_emitted_raw:
        raise ValueError(
            f"POPULATION_FUNNEL_INCONSISTENT: strategy reported {candidates_emitted_raw} "
            f"raw candidates emitted but the extracted candidates dataframe had "
            f"{candidates_raw_count} rows before the collection-window filter."
        )

    candidates_outside_window = candidates_raw_count - candidates_persisted_count
    if candidates_outside_window < 0:
        raise ValueError(
            "POPULATION_FUNNEL_INCONSISTENT: the collection-window filter produced more "
            "candidate rows than it started with."
        )

    declared_contract_exclusions = declared_contract_exclusions_in_run + candidates_outside_window
    reconciled_total = (
        declared_contract_exclusions + implementation_only_exclusions + candidates_persisted_count
    )
    passed = reconciled_total == total_population_checkpoints

    report: Dict[str, Any] = {
        "total_population_checkpoints": total_population_checkpoints,
        "declared_contract_exclusions": declared_contract_exclusions,
        "declared_contract_exclusions_in_run": declared_contract_exclusions_in_run,
        "candidates_outside_collection_window": candidates_outside_window,
        "implementation_only_exclusions": implementation_only_exclusions,
        "candidates_emitted": candidates_persisted_count,
        "reconciliation_passed": passed,
    }
    if not passed:
        raise ValueError(
            f"POPULATION_FUNNEL_RECONCILIATION_FAILED: total_population_checkpoints="
            f"{total_population_checkpoints} != declared_contract_exclusions("
            f"{declared_contract_exclusions}) + implementation_only_exclusions("
            f"{implementation_only_exclusions}) + candidates_emitted("
            f"{candidates_persisted_count}) = {reconciled_total}"
        )
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
        feature_authority: str = "active",
    ) -> None:
        self.study_data = study_data
        self.data_plan = data_plan
        self.run_plan = run_plan
        self.composite_seal_hash = composite_seal_hash
        self.execution_manifest_sha256 = execution_manifest_sha256
        self.feature_authority = feature_authority

        if output_base_dir is None:
            output_base_dir = study_data.study_dir / "runs"

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
            "feature_authority": self.feature_authority,
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
        # Packet E: captured before the warmup-window filter below reassigns
        # candidates_df, so reconcile_population_funnel can see how many raw candidates
        # existed prior to that filter.
        candidates_raw_count = len(candidates_df)

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
        declared_metadata = self.study_data.spec.features.metadata_columns or list(DEFAULT_METADATA_COLUMNS)
        # Causality provenance is an optional runtime metadata column for legacy
        # fixtures, but is allowed and persisted whenever the collector emits it.
        metadata_contract = set(declared_metadata) | {"triggering_1s_ts_init"}

        # D2: collection candidate universe != frozen model feature list. A study may
        # declare features.source (e.g. "verified_registry_numeric_universe") to collect
        # from a registry-defined candidate set BEFORE its later TRAIN-stage feature_list
        # is frozen. Resolving that source is what makes those columns allowed at
        # collection time; expected_feats (the frozen list) stays exactly as declared --
        # empty here is not a defect, it is "not yet selected".
        collection_universe = resolve_collection_allowed_feature_aliases(
            self.study_data.spec.features, authority=self.feature_authority,
        )

        # Declared derived causal inputs (e.g. a frozen external model score) are bound to
        # their own column and are neither a market FeatureInstance nor metadata.
        derived_cols = {
            di.name for di in (self.study_data.spec.features.derived_inputs or [])
            if getattr(di, "name", None)
        }
        allowed_columns = set(expected_feats) | metadata_contract | set(collection_universe) | derived_cols

        # Check for duplicate column names. D1: this already ran unconditionally regardless
        # of row count -- a duplicate column name is a schema defect, not a data defect --
        # so zero rows was never a reason to skip it.
        if len(candidates_df.columns) != len(set(candidates_df.columns)):
            raise ValueError("DUPLICATE_OUTPUT_COLUMNS: Candidates dataframe has duplicate column names!")
        if len(observations_df.columns) != len(set(observations_df.columns)):
            raise ValueError("DUPLICATE_OUTPUT_COLUMNS: Observations dataframe has duplicate column names!")

        # Check for unexpected surplus columns
        extra_cols = set(candidates_df.columns) - allowed_columns
        if extra_cols:
            raise ValueError(f"UNEXPECTED_OUTPUT_COLUMN: candidates dataframe contains undeclared columns: {sorted(list(extra_cols))}")

        # D1: required metadata columns must be present at ANY row count, including zero.
        # `len(candidates_df) == 0` used to skip this check entirely, so an empty DataFrame
        # with the wrong (or no) columns still filed as a valid governed output -- the
        # schema check was vacuous exactly when it mattered most: a genuinely empty
        # collection run.
        missing_meta = set(declared_metadata) - set(candidates_df.columns)
        if missing_meta:
            raise ValueError(f"MISSING_OUTPUT_METADATA: candidates dataframe missing declared metadata columns: {sorted(list(missing_meta))}")

        # D1: the full candidate key (research_decision-authoritative, D1.2) must be present
        # on candidates regardless of `declared_metadata` contents -- a study whose declared
        # metadata list omits a key column must not silently lose key enforcement.
        missing_cand_key = [c for c in CANDIDATE_KEY_COLUMNS if c not in candidates_df.columns]
        if missing_cand_key:
            raise ValueError(
                f"MISSING_CANDIDATE_KEY_COLUMN: candidates dataframe missing required candidate "
                f"key column(s): {missing_cand_key}"
            )

        # D1.2: "The observation side must carry the required matching key contract as
        # defined by the existing system" -- the existing system's matching key contract is
        # CANDIDATE_KEY_COLUMNS, the same triple reconcile_candidate_dispositions joins on.
        missing_obs_key = [c for c in CANDIDATE_KEY_COLUMNS if c not in observations_df.columns]
        if missing_obs_key:
            raise ValueError(
                f"MISSING_OBSERVATION_KEY_COLUMN: observations dataframe missing required "
                f"matching key column(s): {missing_obs_key}"
            )

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

        surface_report = validate_feature_surface(
            candidates_df, expected_feats, metadata_columns=declared_metadata,
            collection_universe=collection_universe,
        )

        # Candidate/observation reconciliation (E). A candidate that quietly failed to
        # reach a terminal disposition used to vanish from the observation surface
        # entirely, which is future-conditioned selection rather than a missing row.
        reconciliation = reconcile_candidate_dispositions(candidates_df, observations_df)

        # Population funnel (Packet E, D8). None when the strategy exposes no funnel
        # telemetry; otherwise hard-fails closed (raises) rather than persisting a
        # warning-only mismatch.
        population_funnel = reconcile_population_funnel(
            total_population_checkpoints=telemetry.population_total_checkpoints,
            declared_contract_exclusions_in_run=telemetry.population_declared_contract_exclusions_in_run,
            implementation_only_exclusions=telemetry.population_implementation_only_exclusions,
            candidates_emitted_raw=telemetry.population_candidates_emitted_raw,
            candidates_raw_count=candidates_raw_count,
            candidates_persisted_count=len(candidates_df),
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
            "feature_surface_validation": surface_report.to_dict(),
            "candidate_disposition_reconciliation": reconciliation,
            "population_funnel": population_funnel,
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
            "population_funnel": population_funnel,
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
            "population_funnel_reconciliation_passed": (
                population_funnel["reconciliation_passed"] if population_funnel else None
            ),
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
