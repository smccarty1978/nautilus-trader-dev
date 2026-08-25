"""Memory-bounded, deterministic collection partition primitives.

Partitions are an execution concern, not a study-specific collector.  A partition
keeps a primary interval for output and explicit causal context intervals for
warmup and target disposition.  The helpers deliberately do not alter session
filtering: ETH history remains available to the generic collector.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from research_workflow.experiment import load_authorization, runtime_authorization


class PartitionError(RuntimeError):
    """Raised when partition provenance, boundaries, or output schemas disagree."""


@dataclass(frozen=True)
class PartitionSpec:
    partition_id: str
    period: str
    primary_start: str
    primary_end: str
    warmup_start: str
    warmup_end: str
    lookahead_start: str
    lookahead_end: str
    authorization_sha256: str
    source_identity: str
    feature_instance_sha256: str
    contract_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def provenance_sha256(self) -> str:
        body = self.to_dict()
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _date_range(start: str, end: str) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, end, freq="D")]


def build_year_partitions(
    study_path: str | Path,
    period: str = "train",
    *,
    years: Sequence[int] | None = None,
    warmup_days: int = 5,
    lookahead_seconds: int | None = None,
    source_identity: str = "catalog-authority",
) -> list[PartitionSpec]:
    """Build year partitions from the study chronology without touching data."""
    path = Path(study_path).resolve()
    auth = load_authorization(path)
    selected = tuple(years or (auth.train_years if period == "train" else auth.oos_years))
    if not selected:
        raise PartitionError(f"no authorized years for period={period!r}")
    if period not in {"train", "oos", "dev"}:
        raise PartitionError(f"unknown period: {period!r}")
    if period in {"oos", "dev"}:
        # This is an explicit planning guard; collection additionally checks the
        # TRAIN freeze via runtime_authorization/assert_oos_open.
        from research_workflow.experiment import assert_oos_open
        assert_oos_open(path)
    study = __import__("yaml").safe_load((path / "study.yaml").read_text(encoding="utf-8")) or {}
    target = ((study.get("target") or {}).get("horizon_seconds") or 300)
    horizon = int(lookahead_seconds if lookahead_seconds is not None else target)
    features = (study.get("features") or {}).get("instances") or []
    contract_hash = _canonical_hash({"population": study.get("population"), "target": study.get("target"), "chronology": study.get("chronology")})
    feature_hash = _canonical_hash(features)
    out: list[PartitionSpec] = []
    for year in sorted(set(int(y) for y in selected)):
        primary_start = date(year, 1, 1)
        primary_end = date(year, 12, 31)
        warmup_start = primary_start - timedelta(days=warmup_days)
        lookahead_end = datetime.combine(primary_end, datetime.max.time(), tzinfo=timezone.utc) + timedelta(seconds=horizon)
        out.append(PartitionSpec(
            partition_id=f"{period}-{year}", period=period,
            primary_start=primary_start.isoformat(), primary_end=primary_end.isoformat(),
            warmup_start=warmup_start.isoformat(), warmup_end=primary_end.isoformat(),
            lookahead_start=primary_end.isoformat(), lookahead_end=lookahead_end.date().isoformat(),
            authorization_sha256=auth.authorization_sha256, source_identity=source_identity,
            feature_instance_sha256=feature_hash, contract_sha256=contract_hash,
        ))
    return out


def collect_partition(
    study_path: str | Path,
    partition: PartitionSpec,
    *,
    output_dir: str | Path | None = None,
    execute: bool = False,
    log_level: str = "ERROR",
) -> dict[str, Any]:
    """Plan or execute one bounded primary partition through the NT collector."""
    path = Path(study_path).resolve()
    auth = load_authorization(path)
    if partition.authorization_sha256 != auth.authorization_sha256:
        raise PartitionError("partition authorization is stale")
    payload = runtime_authorization(path, partition.period)
    # Replay causal lookahead when it remains inside the authorized partition.
    # At a chronology boundary the lower-level authorization must remain fail-closed;
    # the target contract's session/data-end censoring handles the unresolved tail.
    authorized_years = set(auth.train_years if partition.period == "train" else auth.oos_years)
    primary_end = pd.Timestamp(partition.primary_end, tz="UTC")
    requested_end = pd.Timestamp(partition.lookahead_end, tz="UTC")
    exec_end = requested_end if requested_end.year in authorized_years else primary_end
    exec_end_date = exec_end.strftime("%Y-%m-%d")
    payload["dates"] = _date_range(partition.primary_start, exec_end_date)
    payload["runtime_authorization_sha256"] = _canonical_hash({k: payload[k] for k in payload if k != "runtime_authorization_sha256"})
    result: dict[str, Any] = {"status": "PLANNED", "partition": partition.to_dict(), "provenance_sha256": partition.provenance_sha256}
    if not execute:
        return result
    from backtests.nt_runtime.modes.collect import run_collect_mode
    run = run_collect_mode(
        study_path=path, stage="full", output_dir=output_dir, log_level=log_level,
        experiment_authorization=payload,
        date_range=(partition.primary_start, exec_end_date),
        primary_interval=(
            pd.Timestamp(partition.primary_start, tz="UTC").value,
            (pd.Timestamp(partition.primary_end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value,
        ),
    )
    result.update({"status": "COLLECTED", "run": run})
    return result


def reconcile_partitions(partitions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate partition provenance and primary interval disjointness."""
    records = [dict(p) for p in partitions]
    seen: set[str] = set()
    findings: list[str] = []
    for rec in records:
        spec = rec.get("partition", rec)
        pid = str(spec.get("partition_id"))
        if pid in seen:
            findings.append(f"duplicate partition_id: {pid}")
        seen.add(pid)
    ordered = sorted((r.get("partition", r) for r in records), key=lambda s: s.get("primary_start", ""))
    for left, right in zip(ordered, ordered[1:]):
        if left.get("primary_end", "") >= right.get("primary_start", ""):
            findings.append(f"overlapping primary intervals: {left.get('partition_id')} / {right.get('partition_id')}")
    hashes = {(s.get("authorization_sha256"), s.get("feature_instance_sha256"), s.get("contract_sha256")) for s in ordered}
    if len(hashes) > 1:
        findings.append("incompatible partition authority hashes")
    return {"passed": not findings, "partition_count": len(records), "findings": findings, "partition_ids": [s.get("partition_id") for s in ordered]}


def merge_partition_outputs(
    frames: Sequence[pd.DataFrame],
    partitions: Sequence[PartitionSpec],
    *,
    key_columns: Sequence[str] = ("observation_ts", "regime_start_ns", "checkpoint_index"),
) -> pd.DataFrame:
    """Merge primary outputs deterministically, rejecting overlap/schema drift."""
    if len(frames) != len(partitions):
        raise PartitionError("one output frame is required for each partition")
    if not frames:
        return pd.DataFrame()
    columns = list(frames[0].columns)
    if any(list(frame.columns) != columns for frame in frames[1:]):
        raise PartitionError("partition output schema mismatch")
    # A column that is all-null in one partition can be float64 while the same
    # populated column is int64 in another.  Resolve that deterministic, lossless
    # promotion once at the merge boundary; arbitrary object coercion is rejected.
    aligned: list[pd.DataFrame] = []
    for frame in frames:
        copy = frame.copy()
        for col in columns:
            kinds = [f[col].dtype.kind for f in frames]
            if len(set(kinds)) > 1:
                if set(kinds) <= {"b", "i", "u", "f"}:
                    copy[col] = copy[col].astype("float64")
                else:
                    raise PartitionError(f"partition output dtype mismatch: {col}")
        aligned.append(copy)
    merged = pd.concat(aligned, ignore_index=True)
    keys = [c for c in key_columns if c in merged.columns]
    if keys and merged.duplicated(keys).any():
        raise PartitionError("overlapping primary candidate keys")
    if keys:
        merged = merged.sort_values(keys, kind="mergesort").reset_index(drop=True)
    return merged


def retain_primary_rows(
    frame: pd.DataFrame,
    partition: PartitionSpec,
    *,
    timestamp_column: str = "observation_ts",
) -> pd.DataFrame:
    """Keep only rows whose observation timestamp is inside the primary interval.

    Warmup/lookahead rows are valid inputs to the collector but are never primary
    outputs.  Filtering is post-replay and therefore cannot change causal state.
    """
    if frame.empty or timestamp_column not in frame.columns:
        return frame.copy()
    ts = pd.to_datetime(frame[timestamp_column], unit="ns", utc=True)
    start = pd.Timestamp(partition.primary_start, tz="UTC")
    end = pd.Timestamp(partition.primary_end, tz="UTC") + pd.Timedelta(days=1)
    return frame.loc[(ts >= start) & (ts < end)].copy()
