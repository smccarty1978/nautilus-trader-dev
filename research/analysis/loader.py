"""Validated collection loader (A0 §3, §4, §5 — phase A1).

Three public entry points, deliberately separated so that a validation failure is
*reportable* rather than fatal at load time:

    load_collection(run_id)                 -> Collection      (reads, no validation)
    validate_collection(collection, spec)   -> ValidationReport (every check, fail-closed)
    get_features_targets_metadata(...)      -> (X, y, meta)     (requires a passing report)

Design rules carried from the backtest harness work: no implicit "latest"; identity
re-verified from disk rather than trusted from a manifest; the join key derived per
study; and no imputation, ranking, or filtering inside the loader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from research.analysis.errors import (
    ArtifactHashMismatch, CollectionNotSuccessful, CrossStudyPooling, DuplicateColumns,
    DuplicateKeys, EmptyObservations, FeatureHashMismatch, FeatureOrderMismatch,
    IdentityMismatch, JoinKeyMissing, JoinRowLoss, MissingArtifact, OOSLocked,
    PartitionMixing, ProhibitedPartitionPresent, RowCountMismatch, SchemaMissing,
    SchemaSurplus, SpecDrift, StaleCompiledStudy, TargetMissing, UnsealedCollection,
    ValidationNotRun, WarmupLeakage,
)
from research.analysis.identity import (
    DEFAULT_METADATA_COLUMNS, OUTCOME_COLUMNS, CollectionIdentity, CollectionPaths,
    build_identity, canonical_sha256, sha256_file,
)
from research.analysis.spec import AnalysisSpec

LOADER_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


@dataclass
class Collection:
    """Everything read from one collection run. No validation has been applied."""

    identity: CollectionIdentity
    paths: CollectionPaths
    run_manifest: Dict[str, Any]
    collection_manifest: Dict[str, Any]
    status: Dict[str, Any]
    study_yaml: Dict[str, Any]
    compiled_study: Dict[str, Any]
    candidates: pd.DataFrame
    observations: pd.DataFrame
    study_dir: Path

    # -- contract accessors ------------------------------------------------
    @property
    def declared_features(self) -> List[str]:
        return list(((self.study_yaml.get("features") or {}).get("feature_list")) or [])

    @property
    def declared_metadata(self) -> Tuple[List[str], str]:
        """Returns (metadata columns, source) where source is 'declared' or 'fallback'."""
        declared = (self.study_yaml.get("features") or {}).get("metadata_columns")
        if declared:
            return list(declared), "declared"
        return list(DEFAULT_METADATA_COLUMNS), "fallback"

    @property
    def chronology(self) -> Dict[str, Any]:
        return self.study_yaml.get("chronology") or {}

    @property
    def target_contract(self) -> Dict[str, Any]:
        return self.study_yaml.get("target") or {}

    def declared_join_key(self, spec: Optional[AnalysisSpec] = None) -> Tuple[List[str], str]:
        """Resolves the join key OF RECORD and says where it came from.

        The key is never read off the live `observations` frame. A key defined as
        "declared metadata ∩ observation columns" is unfalsifiable by construction:
        every derived column is trivially present in observations, so a *missing* key
        column silently shortens the key instead of failing JOIN_KEY_MISSING, and a
        4-column key degrades to 3 while validation reports zero failures.

        Resolution order, strongest declaration first:

          1. `collection.expected_join_key` pinned in the analysis spec;
          2. `features.join_key` declared in the study contract;
          3. the observation columns the collection manifest RECORDS having emitted,
             intersected with declared metadata (the producer's own declaration,
             fixed at collection time and covered by `collection_manifest_sha256`);
          4. declared metadata ∩ candidate columns — last resort, and still not read
             from the frame whose scope loss we are trying to detect.

        Fixture A resolves to 4 keys, Fixture B to 3, without hardcoding either.
        """
        meta, _ = self.declared_metadata
        declared_meta = [c for c in meta if c not in OUTCOME_COLUMNS]

        if spec is not None and getattr(spec, "expected_join_key", ()):
            return list(spec.expected_join_key), "analysis_spec.collection.expected_join_key"

        contract_key = (self.study_yaml.get("features") or {}).get("join_key")
        if contract_key:
            return [str(c) for c in contract_key], "study.yaml features.join_key"

        recorded = (self.collection_manifest.get("columns") or {}).get("observations")
        if recorded:
            rec = set(recorded)
            return ([c for c in declared_meta if c in rec],
                    "collection_manifest.columns.observations")

        cand_cols = set(self.candidates.columns)
        return ([c for c in declared_meta if c in cand_cols],
                "declared_metadata n candidates.columns")

    def join_key(self, spec: Optional[AnalysisSpec] = None) -> List[str]:
        """The declared join key of record (see `declared_join_key`)."""
        return self.declared_join_key(spec)[0]


def _read_json(path: Path, what: str) -> Dict[str, Any]:
    if not path.is_file():
        raise MissingArtifact(f"{what} not found", path=str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        raise MissingArtifact(f"{what} is not valid JSON: {err}", path=str(path)) from err


def load_collection(
    run_id: str,
    *,
    runs_root: Path = Path("runs"),
    studies_root: Path = Path("studies"),
) -> Collection:
    """Resolves an EXACT run id and reads its artifacts. Performs no validation.

    Raises only MISSING_ARTIFACT. Everything else is `validate_collection`'s job, so
    that a broken collection produces a report rather than an import-time crash.
    """
    if not run_id or run_id.strip().lower() in {"latest", "last", "newest", "*"}:
        raise MissingArtifact(
            f"run_id={run_id!r} is not an explicit run identity; there is no 'latest'",
            run_id=run_id,
        )

    paths = CollectionPaths.for_run(run_id, Path(runs_root))
    paths.require_all()

    run_manifest = _read_json(paths.run_manifest, "run_manifest.json")
    collection_manifest = _read_json(paths.collection_manifest, "collection_manifest.json")
    status = _read_json(paths.status, "status.json") if paths.status.is_file() else {}

    study_id = collection_manifest.get("study_id") or run_manifest.get("study_id") or ""
    study_dir = Path(studies_root) / study_id
    study_yaml: Dict[str, Any] = {}
    compiled_study: Dict[str, Any] = {}
    if study_dir.is_dir():
        import yaml

        sy = study_dir / "study.yaml"
        cs = study_dir / "compiled_study.json"
        if sy.is_file():
            study_yaml = yaml.safe_load(sy.read_text(encoding="utf-8")) or {}
        if cs.is_file():
            compiled_study = json.loads(cs.read_text(encoding="utf-8"))

    feature_sha = (study_yaml.get("features") or {}).get("feature_list_sha256")

    candidates = pd.read_parquet(paths.candidates)
    try:
        observations = pd.read_parquet(paths.observations)
    except Exception:  # noqa: BLE001 - a (0,0) parquet is a real on-disk case
        observations = pd.DataFrame()

    identity = build_identity(paths, run_manifest, collection_manifest, feature_sha)

    return Collection(
        identity=identity,
        paths=paths,
        run_manifest=run_manifest,
        collection_manifest=collection_manifest,
        status=status,
        study_yaml=study_yaml,
        compiled_study=compiled_study,
        candidates=candidates,
        observations=observations,
        study_dir=study_dir,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    check: str
    passed: bool
    measured: Any = None
    failure_code: Optional[str] = None
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "passed": self.passed,
            "measured": self.measured,
            "failure_code": self.failure_code,
            "detail": self.detail,
        }


@dataclass
class ValidationReport:
    run_id: str
    checks: List[CheckResult] = field(default_factory=list)
    partition_counts: Dict[str, int] = field(default_factory=dict)
    metadata_source: str = ""
    join_key: List[str] = field(default_factory=list)
    null_counts: Dict[str, int] = field(default_factory=dict)
    # --- what this report is a report ABOUT (H2) --------------------------
    # A report produced without a spec never ran seal_policy, oos_unlocked,
    # no_partition_mixing or collection_identity_matches_spec. Carrying that fact on
    # the artifact is what lets extraction refuse to treat it as authorisation.
    spec_supplied: bool = False
    analysis_spec_sha256: Optional[str] = None
    join_key_source: str = ""

    # Checks that only exist when a spec is supplied. Recorded so the skipped set is
    # visible on the report rather than inferable only by absence.
    SPEC_BOUND_CHECKS = (
        "seal_policy", "oos_unlocked", "no_partition_mixing",
        "collection_identity_matches_spec", "study_id_matches_spec",
        "feature_hash_matches_spec", "target_horizon_matches_spec",
    )

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed]

    @property
    def skipped_checks(self) -> List[str]:
        if self.spec_supplied:
            return []
        return list(self.SPEC_BOUND_CHECKS)

    def authorizes(self, spec: AnalysisSpec) -> bool:
        """True only if this report was produced by validating THIS spec."""
        return bool(
            self.spec_supplied
            and self.analysis_spec_sha256
            and spec is not None
            and self.analysis_spec_sha256 == spec.analysis_spec_sha256
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "loader_version": LOADER_VERSION,
            "passed": self.passed,
            "spec_supplied": self.spec_supplied,
            "analysis_spec_sha256": self.analysis_spec_sha256,
            "skipped_checks": self.skipped_checks,
            "checks": [c.to_dict() for c in self.checks],
            "partition_row_counts": self.partition_counts,
            "metadata_source": self.metadata_source,
            "join_key": self.join_key,
            "join_key_source": self.join_key_source,
            "feature_null_counts": self.null_counts,
        }

    def raise_if_failed(self) -> None:
        if self.passed:
            return
        first = self.failures[0]
        from research.analysis import errors as _errors

        for name in dir(_errors):
            cls = getattr(_errors, name)
            if isinstance(cls, type) and getattr(cls, "code", None) == first.failure_code:
                raise cls(first.detail, check=first.check, measured=first.measured)
        raise _errors.AnalysisError(first.detail)


def partition_of_year(year: int, chronology: Dict[str, Any]) -> Optional[str]:
    for name in ("train", "dev", "diagnostic"):
        if year in set(chronology.get(name) or []):
            return name
    if year in set(chronology.get("prohibited") or []):
        return "prohibited"
    return None


def _years_from_ts(series: pd.Series) -> pd.Series:
    """Partition is derived from observation_ts (UTC), never from a filename."""
    return pd.to_datetime(series, unit="ns", utc=True).dt.year


def validate_collection(
    collection: Collection,
    spec: Optional[AnalysisSpec] = None,
    *,
    oos_token_verifier=None,
) -> ValidationReport:
    """Runs every A0 §3 check plus the §5 partition rules, in order, fail-closed.

    Records the MEASURED value of each check, not just a verdict — a check that only
    ever prints PASS is not evidence.
    """
    r = ValidationReport(
        run_id=collection.identity.run_id,
        spec_supplied=spec is not None,
        analysis_spec_sha256=spec.analysis_spec_sha256 if spec is not None else None,
    )
    add = r.checks.append
    c = collection

    # 1 artifacts present (already enforced by load_collection)
    add(CheckResult("artifacts_present", True, measured=str(c.paths.run_dir)))

    # 2 collection succeeded
    st = c.status.get("status")
    add(CheckResult("collection_status_success", st == "SUCCESS", measured=st,
                    failure_code=None if st == "SUCCESS" else CollectionNotSuccessful.code,
                    detail="" if st == "SUCCESS" else f"status.json reports {st!r}"))

    # 3 parquet hashes match the manifest
    for label, path, recorded in (
        ("candidates", c.paths.candidates, c.identity.candidates_sha256),
        ("observations", c.paths.observations, c.identity.observations_sha256),
    ):
        actual = sha256_file(path)
        ok = actual == recorded
        add(CheckResult(f"{label}_hash_matches_manifest", ok,
                        measured={"recorded": recorded, "recomputed": actual},
                        failure_code=None if ok else ArtifactHashMismatch.code,
                        detail="" if ok else f"{label}.parquet hash differs from collection_manifest"))

    # 4a study dir self-consistent now
    cs_hash = c.compiled_study.get("spec_sha256")
    cur_hash = _current_spec_hash(c)
    ok4a = bool(cs_hash) and bool(cur_hash) and cs_hash == cur_hash
    allow_stale = bool(spec and spec.allow_stale_compiled_study)
    add(CheckResult("study_dir_self_consistent", ok4a or allow_stale,
                    measured={"study_yaml": cur_hash, "compiled_study": cs_hash,
                              "allowed_stale": allow_stale},
                    failure_code=None if (ok4a or allow_stale) else StaleCompiledStudy.code,
                    detail="" if (ok4a or allow_stale) else
                    "study.yaml no longer matches compiled_study.json; the study directory has "
                    "moved on since compilation (the collection itself may still be valid)"))

    # 4b collection produced from the compiled contract
    ok4b = bool(cs_hash) and cs_hash == c.identity.spec_sha256
    add(CheckResult("collection_matches_compiled_contract", ok4b,
                    measured={"compiled_study": cs_hash, "run_manifest": c.identity.spec_sha256},
                    failure_code=None if ok4b else SpecDrift.code,
                    detail="" if ok4b else
                    "the run was produced from a different study contract than the one compiled"))

    # 5/6/7 feature contract
    declared = c.declared_features
    cand_cols = list(c.candidates.columns)
    declared_sha = c.identity.feature_list_sha256

    # L2: with no declared feature list there is no contract to check. Both checks
    # below would otherwise pass vacuously ([] == [] and None in {None, None}) and
    # report a verified feature contract where none exists.
    contract_present = bool(declared) and bool(declared_sha)
    if not contract_present:
        detail = (
            "no feature contract is available: "
            f"declared feature_list has {len(declared)} entries and "
            f"feature_list_sha256 is {declared_sha!r}. The study directory is absent or "
            f"declares no features, so feature order and feature hash cannot be verified."
        )
        add(CheckResult("feature_contract_declared", False,
                        measured={"declared_n": len(declared), "feature_list_sha256": declared_sha},
                        failure_code=SchemaMissing.code, detail=detail))

    present_in_order = [col for col in cand_cols if col in set(declared)]
    ok_order = contract_present and present_in_order == declared
    add(CheckResult("feature_order_preserved", ok_order,
                    measured={"declared_n": len(declared), "emitted_n": len(present_in_order)},
                    failure_code=None if ok_order else (
                        FeatureOrderMismatch.code if contract_present else SchemaMissing.code),
                    detail="" if ok_order else (
                        "emitted feature order differs from the declared feature_list order"
                        if contract_present else
                        "feature order is unverifiable: no declared feature list")))

    recomputed = canonical_sha256(declared) if declared else None
    # Match the collector's own hashing convention (json.dumps default separators).
    import hashlib as _h
    recomputed_collector = _h.sha256(json.dumps(declared).encode("utf-8")).hexdigest() if declared else None
    ok_hash = contract_present and declared_sha in {recomputed, recomputed_collector}
    add(CheckResult("feature_list_hash_matches", ok_hash,
                    measured={"declared": declared_sha, "recomputed": recomputed_collector},
                    failure_code=None if ok_hash else (
                        FeatureHashMismatch.code if contract_present else SchemaMissing.code),
                    detail="" if ok_hash else (
                        "ordered feature list hash does not match the declared value"
                        if contract_present else
                        "feature list hash is unverifiable: no declared feature list")))

    meta_cols, meta_source = c.declared_metadata
    r.metadata_source = meta_source
    allowed = set(declared) | set(meta_cols)
    surplus = sorted(set(cand_cols) - allowed)
    missing = sorted(set(declared) - set(cand_cols))
    add(CheckResult("no_surplus_columns", not surplus, measured=surplus,
                    failure_code=None if not surplus else SchemaSurplus.code,
                    detail="" if not surplus else f"undeclared candidate columns: {surplus}"))
    add(CheckResult("no_missing_features", not missing, measured=missing,
                    failure_code=None if not missing else SchemaMissing.code,
                    detail="" if not missing else f"declared features absent from candidates: {missing}"))

    # 8 duplicate column names
    dup_cols = [x for x in {*cand_cols} if cand_cols.count(x) > 1]
    add(CheckResult("no_duplicate_columns", not dup_cols, measured=dup_cols,
                    failure_code=None if not dup_cols else DuplicateColumns.code,
                    detail="" if not dup_cols else f"duplicate candidate columns: {dup_cols}"))

    # 10 observations non-empty  (checked before target/key so (0,0) reports clearly)
    obs_empty = c.observations.empty or len(c.observations.columns) == 0
    cand_nonempty = not c.candidates.empty
    ok_obs = not (cand_nonempty and obs_empty)
    add(CheckResult("observations_non_empty", ok_obs,
                    measured={"candidate_rows": len(c.candidates),
                              "observation_rows": len(c.observations),
                              "observation_cols": len(c.observations.columns)},
                    failure_code=None if ok_obs else EmptyObservations.code,
                    detail="" if ok_obs else
                    "candidates are non-empty but observations.parquet is empty; the target is "
                    "unavailable and an inner join would silently yield zero rows"))

    target_col = spec.target_column if spec else "target_flip_within_horizon"
    # Resolved from the contract, NOT from the observation frame, so a key column that
    # went missing from observations shortens nothing and is reportable (H3).
    join_key, join_key_source = c.declared_join_key(spec)
    r.join_key = list(join_key)
    r.join_key_source = join_key_source

    if ok_obs:
        # 9 target + join key present
        has_target = target_col in c.observations.columns
        add(CheckResult("target_present", has_target, measured=target_col,
                        failure_code=None if has_target else TargetMissing.code,
                        detail="" if has_target else
                        f"observations.parquet has no column {target_col!r}"))
        missing_cand = [k for k in join_key if k not in c.candidates.columns]
        missing_obs = [k for k in join_key if k not in c.observations.columns]
        ok_keys = bool(join_key) and not missing_cand and not missing_obs
        add(CheckResult("join_key_resolved", ok_keys,
                        measured={"join_key": join_key, "source": join_key_source,
                                  "missing_from_candidates": missing_cand,
                                  "missing_from_observations": missing_obs},
                        failure_code=None if ok_keys else JoinKeyMissing.code,
                        detail="" if ok_keys else (
                            f"declared join key ({join_key_source}) is not fully present: "
                            f"missing from candidates={missing_cand}, "
                            f"missing from observations={missing_obs}. A shortened key would "
                            f"join across the dropped dimension instead of failing."
                        )))

        if ok_keys:
            # 11 duplicate keys
            dup_c = int(c.candidates.duplicated(subset=join_key).sum())
            dup_o = int(c.observations.duplicated(subset=join_key).sum())
            ok_dup = dup_c == 0 and dup_o == 0
            add(CheckResult("join_key_unique", ok_dup,
                            measured={"candidates": dup_c, "observations": dup_o},
                            failure_code=None if ok_dup else DuplicateKeys.code,
                            detail="" if ok_dup else "join key is not unique in both frames"))

            # 12 join is 1:1 and loses nothing
            if ok_dup:
                merged = c.candidates.merge(c.observations, on=join_key, how="inner")
                lost = len(c.candidates) - len(merged)
                add(CheckResult("join_no_row_loss", lost == 0,
                                measured={"candidates": len(c.candidates), "joined": len(merged),
                                          "lost": lost},
                                failure_code=None if lost == 0 else JoinRowLoss.code,
                                detail="" if lost == 0 else f"inner join dropped {lost} candidate rows"))

    # 13 row counts match the manifest
    exp_c = c.collection_manifest.get("candidates_count")
    exp_o = c.collection_manifest.get("observations_count")
    ok_rows = (exp_c is None or exp_c == len(c.candidates)) and (
        exp_o is None or exp_o == len(c.observations)
    )
    add(CheckResult("row_counts_match_manifest", ok_rows,
                    measured={"manifest": [exp_c, exp_o],
                              "actual": [len(c.candidates), len(c.observations)]},
                    failure_code=None if ok_rows else RowCountMismatch.code,
                    detail="" if ok_rows else "frame row counts disagree with collection_manifest"))

    # 14 + partitions
    _validate_partitions(c, spec, r, add, oos_token_verifier)

    # seal policy
    if spec is not None:
        sealed_ok = c.identity.sealed or spec.allow_unsealed_collection
        add(CheckResult("seal_policy", sealed_ok,
                        measured={"sealed": c.identity.sealed,
                                  "allow_unsealed": spec.allow_unsealed_collection},
                        failure_code=None if sealed_ok else UnsealedCollection.code,
                        detail="" if sealed_ok else
                        "collection has no composite_seal_hash and allow_unsealed_collection is false"))

        # identity binding
        if spec.collection_identity_sha256:
            got = c.identity.collection_identity_sha256
            ok_id = got == spec.collection_identity_sha256
            add(CheckResult("collection_identity_matches_spec", ok_id,
                            measured={"expected": spec.collection_identity_sha256, "actual": got},
                            failure_code=None if ok_id else IdentityMismatch.code,
                            detail="" if ok_id else "resolved collection identity differs from the spec"))
        if spec.study_id and spec.study_id != c.identity.study_id:
            add(CheckResult("study_id_matches_spec", False,
                            measured={"expected": spec.study_id, "actual": c.identity.study_id},
                            failure_code=IdentityMismatch.code,
                            detail="run belongs to a different study than the spec declares"))
        if spec.feature_list_sha256 and spec.feature_list_sha256 != declared_sha:
            add(CheckResult("feature_hash_matches_spec", False,
                            measured={"expected": spec.feature_list_sha256, "actual": declared_sha},
                            failure_code=FeatureHashMismatch.code,
                            detail="spec pins a different ordered feature set"))
        if spec.target_horizon_seconds is not None:
            declared_h = c.target_contract.get("horizon_seconds")
            if declared_h != spec.target_horizon_seconds:
                add(CheckResult("target_horizon_matches_spec", False,
                                measured={"expected": spec.target_horizon_seconds, "actual": declared_h},
                                failure_code=IdentityMismatch.code,
                                detail="target horizon differs; targets are not comparable"))

    # null reporting (never imputation)
    feat_present = [f for f in declared if f in c.candidates.columns]
    if feat_present:
        nulls = c.candidates[feat_present].isna().sum()
        r.null_counts = {k: int(v) for k, v in nulls.items() if v > 0}

    return r


def _current_spec_hash(c: Collection) -> Optional[str]:
    """Computes the study.yaml hash the same way the study factory does."""
    if not c.study_yaml:
        return None
    try:
        from research.schemas.study_spec import StudySpec

        return StudySpec.model_validate(c.study_yaml).compute_sha256()
    except Exception:  # noqa: BLE001 - unparsable spec is reported by the check, not here
        return None


def _validate_partitions(c: Collection, spec, r: ValidationReport, add, oos_token_verifier) -> None:
    chrono = c.chronology
    if "observation_ts" not in c.candidates.columns or c.candidates.empty:
        add(CheckResult("partition_derivable", False, measured="observation_ts absent",
                        failure_code=SchemaMissing.code,
                        detail="observation_ts is required to derive partitions"))
        return

    years = _years_from_ts(c.candidates["observation_ts"])
    counts: Dict[str, int] = {}
    for year, n in years.value_counts().items():
        part = partition_of_year(int(year), chrono) or "unassigned"
        counts[part] = counts.get(part, 0) + int(n)
    r.partition_counts = counts

    prohibited_n = counts.get("prohibited", 0)
    add(CheckResult("no_prohibited_partition_rows", prohibited_n == 0,
                    measured={"prohibited_rows": prohibited_n, "by_partition": counts},
                    failure_code=None if prohibited_n == 0 else ProhibitedPartitionPresent.code,
                    detail="" if prohibited_n == 0 else
                    f"{prohibited_n} rows fall in prohibited years; this is a load failure, not a filter"))

    # 14 warmup leakage: no row before the declared run window
    start = c.identity.start_date
    end = c.identity.end_date
    if start and end:
        lo = pd.Timestamp(f"{start} 00:00:00", tz="UTC")
        hi = pd.Timestamp(f"{end} 23:59:59.999999999", tz="UTC")
        ts = pd.to_datetime(c.candidates["observation_ts"], unit="ns", utc=True)
        outside = int(((ts < lo) | (ts > hi)).sum())
        add(CheckResult("no_warmup_leakage", outside == 0,
                        measured={"rows_outside_window": outside, "window": [start, end]},
                        failure_code=None if outside == 0 else WarmupLeakage.code,
                        detail="" if outside == 0 else
                        f"{outside} rows fall outside the declared run window"))

    if spec is None:
        return

    requested = set(spec.partitions)
    if len(requested) > 1 and {"train", "dev"} <= requested:
        add(CheckResult("no_partition_mixing", False, measured=sorted(requested),
                        failure_code=PartitionMixing.code,
                        detail="TRAIN and DEV may not appear in one fitted arm; run them separately"))

    if "dev" in requested:
        unlocked = False
        detail = "DEV/OOS access requires a verified unlock token"
        if oos_token_verifier is not None:
            try:
                unlocked = bool(oos_token_verifier(c.study_dir, sorted(set(chrono.get("dev") or []))))
            except Exception as err:  # noqa: BLE001
                detail = f"OOS unlock verification failed: {err}"
        add(CheckResult("oos_unlocked", unlocked, measured={"requested": sorted(requested)},
                        failure_code=None if unlocked else OOSLocked.code,
                        detail="" if unlocked else detail))


# ---------------------------------------------------------------------------
# Feature / target / metadata extraction
# ---------------------------------------------------------------------------


def get_features_targets_metadata(
    collection: Collection,
    spec: AnalysisSpec,
    report: Optional[ValidationReport] = None,
) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Returns (features in declared order, target, metadata incl. partition + outcomes).

    Requires a passing ValidationReport. Outcome columns (`flip_ts`,
    `time_to_flip_seconds`) are returned in metadata and never in features: they
    resolve only after the target horizon and would be leakage.
    """
    if report is None:
        raise ValidationNotRun(
            "get_features_targets_metadata requires a ValidationReport; call "
            "validate_collection(...) first"
        )
    # Failure first: a report that failed must surface ITS failure, not the binding
    # complaint, so `validate_collection(c)` -> SCHEMA_SURPLUS keeps reporting
    # SCHEMA_SURPLUS.
    report.raise_if_failed()

    # H2: a passing report only authorises the spec it was produced with. Without
    # this, `validate_collection(c)` (no spec) returns passed=True having never run
    # seal_policy, oos_unlocked, no_partition_mixing or the identity bindings, and
    # extraction under a DEV spec then hands back DEV rows with OOS_LOCKED silent.
    if not report.authorizes(spec):
        raise ValidationNotRun(
            "this ValidationReport does not authorise this analysis spec: "
            f"report.analysis_spec_sha256={report.analysis_spec_sha256!r} "
            f"(spec_supplied={report.spec_supplied}) vs "
            f"spec.analysis_spec_sha256={spec.analysis_spec_sha256!r}. "
            f"Checks that never ran on this report: {report.skipped_checks or 'none'}. "
            "Re-run validate_collection(collection, spec) with the spec you intend to use.",
            report_analysis_spec_sha256=report.analysis_spec_sha256,
            spec_analysis_spec_sha256=spec.analysis_spec_sha256,
            spec_supplied=report.spec_supplied,
            skipped_checks=report.skipped_checks,
        )

    c = collection
    # Use the key the report actually validated, so extraction and validation cannot
    # disagree about what a row is.
    join_key = list(report.join_key) or c.join_key(spec)
    merged = c.candidates.merge(c.observations, on=join_key, how="inner", validate="one_to_one")

    declared = c.declared_features
    if spec.feature_set != "declared":
        unknown = [f for f in spec.feature_subset if f not in declared]
        if unknown:
            raise SchemaMissing(
                f"analysis spec requests features not in the collection: {unknown}",
                unknown=unknown,
            )
        feature_cols = list(spec.feature_subset)
    else:
        feature_cols = list(declared)

    leaking = [f for f in feature_cols if f in OUTCOME_COLUMNS]
    if leaking:
        raise SchemaSurplus(
            f"outcome columns requested as features: {leaking}. These resolve only after the "
            f"target horizon and are never features.",
            leaking=leaking,
        )

    X = merged[feature_cols].copy()
    y = merged[spec.target_column].copy()

    meta_cols, _ = c.declared_metadata
    meta_present = [m for m in meta_cols if m in merged.columns]
    outcome_present = [o for o in OUTCOME_COLUMNS if o in merged.columns]
    meta = merged[meta_present + outcome_present].copy()

    years = _years_from_ts(merged["observation_ts"])
    meta["_year"] = years
    meta["_partition"] = [partition_of_year(int(y_), c.chronology) or "unassigned" for y_ in years]

    requested = set(spec.partitions)
    keep = meta["_partition"].isin(requested)
    if not keep.all():
        X, y, meta = X[keep].copy(), y[keep].copy(), meta[keep].copy()

    return X.reset_index(drop=True), y.reset_index(drop=True), meta.reset_index(drop=True)


def write_dataset_identity(
    collection: Collection,
    report: ValidationReport,
    out_path: Path,
    spec: Optional[AnalysisSpec] = None,
) -> Dict[str, Any]:
    """Writes `dataset_identity.json` — the identity every downstream artifact carries."""
    payload = collection.identity.dataset_identity(
        recomputed_candidates_sha256=sha256_file(collection.paths.candidates),
        recomputed_observations_sha256=sha256_file(collection.paths.observations),
        extra={
            "loader_version": LOADER_VERSION,
            "validation_passed": report.passed,
            # A spec-less validation did not run the seal / OOS / mixing / identity
            # checks; `validation_passed` alone would overstate what was verified.
            "validation_spec_supplied": report.spec_supplied,
            "validation_skipped_checks": report.skipped_checks,
            "join_key": report.join_key,
            "join_key_source": report.join_key_source,
            "metadata_source": report.metadata_source,
            "partition_row_counts": report.partition_counts,
            "feature_null_counts": report.null_counts,
            "analysis_spec_sha256": spec.analysis_spec_sha256 if spec else None,
            "analysis_id": spec.analysis_id if spec else None,
            # Recorded but deliberately NOT part of collection_identity_sha256: it is
            # machine-specific, and identity must stay stable across checkouts (M1).
            # It is here so an artifact says which directory it was actually read from
            # rather than only the basename (H1).
            "resolved_run_dir": collection.paths.resolved_run_dir.as_posix(),
        },
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": harness artifacts must be byte-identical on every platform (L8/M1).
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8",
                        newline="\n")
    return payload


def assert_single_study(collections: Sequence[Collection]) -> None:
    """Cross-study pooling is prohibited by default (A0 §5)."""
    studies = sorted({c.identity.study_id for c in collections})
    if len(studies) > 1:
        raise CrossStudyPooling(
            f"refusing to pool collections from different studies: {studies}. Their chronologies "
            f"may disagree, so pooling can put one study's locked DEV year into another's TRAIN.",
            studies=studies,
        )
