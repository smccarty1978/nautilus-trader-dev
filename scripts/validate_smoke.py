"""Canonical Deterministic Smoke Validator.
=========================================
Performs automated, empirical validation of persisted 1-day smoke run artifacts:
  - Reads candidates.parquet and observations.parquet directly
  - Calculates duplicate candidate keys (must be 0)
  - Calculates future-source violations (must be 0)
  - Verifies exact checkpoint timestamp equality (triggering_1s_ts_init == observation_ts)
  - Verifies exact ordered feature list and SHA-256 against frozen StudySpec
  - Verifies study identity, execution manifest hash, and cryptographic seal hash
  - Generates artifacts/smoke_acceptance.json ONLY after 100% of computed checks pass.

No hand-authored acceptance claims are permitted.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtests.nt_runtime.output_manager import reconcile_candidate_dispositions
from scripts.preexec_audit_seal import verify_preexec_audit_seal, _hash_file
from scripts.resolve_execution_manifest import resolve_execution_manifest

VALIDATOR_VERSION = 2


class SmokeValidationError(RuntimeError):
    """Raised when deterministic smoke validation fails."""
    pass


def validate_smoke_run(
    study_dir: Path,
    run_dir: Optional[Path] = None,
    expected_smoke_date: str = "2023-03-03",
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Empirically validates smoke run artifacts and issues smoke_acceptance.json."""
    if repo_root is None:
        repo_root = REPO_ROOT

    study_dir = study_dir.resolve()
    repo_root = repo_root.resolve()

    # 1. Locate latest day run if run_dir not explicitly passed
    if run_dir is None:
        runs_dir = repo_root / "runs"
        day_runs = sorted(runs_dir.glob(f"*_{study_dir.name}_day"))
        if not day_runs:
            raise SmokeValidationError(f"No completed day runs found in {runs_dir} for study {study_dir.name}")
        run_dir = day_runs[-1]
    else:
        run_dir = run_dir.resolve()

    if not run_dir.exists():
        raise SmokeValidationError(f"Specified run directory does not exist: {run_dir}")

    # 2. Check run completion and status.json
    status_file = run_dir / "status.json"
    if not status_file.exists():
        raise SmokeValidationError(f"Missing run status artifact: {status_file}")

    with open(status_file, "r", encoding="utf-8") as f:
        run_status = json.load(f)

    if run_status.get("status") != "SUCCESS":
        raise SmokeValidationError(f"Smoke run did not complete successfully (status={run_status.get('status')})")

    # 3. Verify cryptographic pre-execution audit seal
    seal_data = verify_preexec_audit_seal(study_dir, repo_root=repo_root)
    seal_hash = seal_data["composite_seal_hash"]

    # 4. Resolve current execution manifest
    manifest_hash, file_hashes, _ = resolve_execution_manifest(study_dir, repo_root=repo_root)
    if seal_hash != manifest_hash:
        raise SmokeValidationError(
            f"SEAL_MANIFEST_MISMATCH: Current execution manifest ({manifest_hash[:16]}) != seal ({seal_hash[:16]})"
        )

    # 4b. Verify run-to-seal binding via run_manifest.json (R4-2)
    run_manifest_file = run_dir / "run_manifest.json"
    if not run_manifest_file.exists():
        raise SmokeValidationError(f"Missing run manifest artifact: {run_manifest_file}")
    with open(run_manifest_file, "r", encoding="utf-8") as f:
        run_manifest = json.load(f)

    run_seal = run_manifest.get("composite_seal_hash")
    if not run_seal or run_seal != seal_hash:
        raise SmokeValidationError(
            f"RUN_SEAL_MISMATCH: run_manifest composite_seal_hash ({run_seal}) != current verified seal ({seal_hash})"
        )

    run_manifest_sha = run_manifest.get("execution_manifest_sha256")
    if not run_manifest_sha or run_manifest_sha != manifest_hash:
        raise SmokeValidationError(
            f"RUN_MANIFEST_MISMATCH: run_manifest execution_manifest_sha256 ({run_manifest_sha}) != current execution manifest ({manifest_hash})"
        )

    # 5. Read candidates parquet
    cand_file = run_dir / "collection" / "candidates.parquet"
    if not cand_file.exists():
        cand_file = run_dir / "candidates.parquet"
    if not cand_file.exists():
        raise SmokeValidationError(f"Missing candidates parquet in run directory: {run_dir}")

    cand_df = pd.read_parquet(cand_file)
    total_candidates = len(cand_df)
    if total_candidates == 0:
        raise SmokeValidationError("Smoke run emitted 0 candidates.")

    # 6. Verify target date filtering & timezones
    # Read smoke_date from study contract if not provided as argument
    study_yaml_p = study_dir / "study.yaml"
    import yaml
    with open(study_yaml_p, "r", encoding="utf-8") as f:
        study_cfg = yaml.safe_load(f)

    actual_smoke_date = expected_smoke_date or study_cfg.get("chronology", {}).get("smoke_date", "2023-03-03")

    # W4: the smoke date is an operator-supplied CLI value with a hard-coded default. It
    # must be checked against the study's own authorization, or a validator can bless a
    # run on a date the study was never permitted to load.
    authorized_dates = (
        (study_cfg.get("execution", {}) or {}).get("data_requirements", {}) or {}
    ).get("authorized_dates")
    if authorized_dates:
        if actual_smoke_date not in set(authorized_dates):
            raise SmokeValidationError(
                f"UNAUTHORIZED_SMOKE_DATE: {actual_smoke_date} is not among this study's "
                f"authorized dates {sorted(authorized_dates)}. The CLI date is not an "
                f"authority; the compiled study is."
            )

    # W1: the deliverables contract is the authority for what a collect run must produce.
    # The validator previously checked only the two parquets it happened to know about,
    # which is the same "checker derives its own scope" defect the contract was created to
    # remove -- a missing collection_manifest.json passed silently.
    # W-A: read it from the SEALED artifact, not the loose sidecar.
    #
    # `config/deliverables_contract.json` was the authority here while sitting outside
    # the sealed study identity, so reducing `deliverables_by_mode.collect` to
    # `["candidates.parquet"]` after sealing restored the original W1 defect -- a missing
    # collection_manifest.json passing silently -- with the seal still reporting valid.
    # A mutable sidecar overriding sealed state is the same shape as every other defect
    # in this family.
    #
    # `compiled_study.json` already carries the compiler's own output at
    # `contracts.deliverables_contract`, and it IS sealed. That is the authority. The
    # sidecar is kept as the human/test-readable rendering and is verified to MATCH; it
    # is never consulted for a decision, so there are not two authorities.
    compiled_p = study_dir / "compiled_study.json"
    if not compiled_p.is_file():
        raise SmokeValidationError(
            f"COMPILED_STUDY_MISSING: {compiled_p}. The sealed compiled study is the "
            f"authority for what a run must deliver; without it this validator would "
            f"have to invent its own deliverable list."
        )
    compiled = json.loads(compiled_p.read_text(encoding="utf-8"))
    deliverables_contract = (compiled.get("contracts") or {}).get("deliverables_contract")
    if not isinstance(deliverables_contract, dict):
        raise SmokeValidationError(
            "DELIVERABLES_CONTRACT_MISSING: compiled_study.json declares no "
            "contracts.deliverables_contract. Recompile the study; a validator may not "
            "derive its own scope."
        )

    deliverables_p = study_dir / "config" / "deliverables_contract.json"
    if deliverables_p.is_file():
        sidecar = json.loads(deliverables_p.read_text(encoding="utf-8"))
        if sidecar != deliverables_contract:
            raise SmokeValidationError(
                f"DELIVERABLES_CONTRACT_DRIFT: {deliverables_p} does not match "
                f"contracts.deliverables_contract in compiled_study.json. The compiled "
                f"study is authoritative; the sidecar has been edited or the study was "
                f"not recompiled after a contract change."
            )

    collect_deliverables = (deliverables_contract.get("deliverables_by_mode") or {}).get("collect")
    if not collect_deliverables:
        raise SmokeValidationError(
            "DELIVERABLES_CONTRACT_EMPTY: the contract declares no collect-mode deliverables"
        )

    artifact_meta = deliverables_contract.get("artifact_metadata") or {}
    missing_deliverables = []
    for artifact in collect_deliverables:
        rel_to = (artifact_meta.get(artifact) or {}).get("relative_to", "run_dir")
        base = run_dir / "collection" if rel_to.endswith("collection") else run_dir
        if not (base / artifact).is_file():
            missing_deliverables.append(f"{rel_to}/{artifact}")
    if missing_deliverables:
        raise SmokeValidationError(
            f"MISSING_DECLARED_DELIVERABLE: the deliverables contract requires "
            f"{missing_deliverables}, which the run did not produce"
        )

    # observation_ts is nanoseconds UTC
    dt_utc = pd.to_datetime(cand_df["observation_ts"], unit="ns", utc=True)
    dt_ct = dt_utc.dt.tz_convert("America/Chicago")
    day_strings = dt_ct.dt.strftime("%Y-%m-%d")

    # W4 (second half): nothing in the emitted surface may fall outside the study's
    # authorization either. Placed here because it needs the decoded candidate days.
    if authorized_dates:
        unauthorized_days = [
            d for d in sorted(set(day_strings.unique())) if d not in set(authorized_dates)
        ]
        if unauthorized_days:
            raise SmokeValidationError(
                f"UNAUTHORIZED_CANDIDATE_DATES: candidates were emitted on {unauthorized_days}, "
                f"outside the study's authorized dates {sorted(authorized_dates)}"
            )

    target_day_mask = day_strings == actual_smoke_date
    target_day_df = cand_df[target_day_mask]
    target_day_candidates = len(target_day_df)

    if target_day_candidates == 0:
        raise SmokeValidationError(f"0 candidates emitted for expected smoke date {actual_smoke_date}")

    # Check for unauthorized OOS dates (e.g. dev/prohibited years)
    prohibited_years = set(study_cfg.get("chronology", {}).get("prohibited", [2025, 2026]))
    dev_years = set(study_cfg.get("chronology", {}).get("dev", [2024]))
    years_in_run = set(dt_utc.dt.year.unique())
    unauthorized_years = years_in_run & (prohibited_years | dev_years)
    if unauthorized_years:
        raise SmokeValidationError(f"Unauthorized OOS/prohibited years found in smoke candidates: {unauthorized_years}")

    # 7. Verify duplicate candidate keys (must be 0)
    key_cols = [c for c in ["observation_ts", "regime_start_ns", "checkpoint_index"] if c in cand_df.columns]
    duplicates_count = int(target_day_df.duplicated(subset=key_cols).sum()) if key_cols else 0
    if duplicates_count > 0:
        raise SmokeValidationError(f"Found {duplicates_count} duplicate candidate rows in smoke run!")

    # 8. Check future-source violations and timestamp causality based on observation policy (R4-1)
    if "triggering_1s_ts_init" not in cand_df.columns:
        raise SmokeValidationError("MISSING_CAUSALITY_METADATA: candidate records missing 'triggering_1s_ts_init' column")

    candidate_rows_total = len(cand_df)
    causality_rows_examined = int(cand_df["triggering_1s_ts_init"].notna().sum())
    causality_coverage_pct = round(causality_rows_examined / candidate_rows_total * 100.0, 2) if candidate_rows_total > 0 else 0.0

    if causality_rows_examined != candidate_rows_total or causality_coverage_pct != 100.0:
        raise SmokeValidationError(
            f"INCOMPLETE_CAUSALITY_EXAMINATION: examined {causality_rows_examined}/{candidate_rows_total} rows ({causality_coverage_pct}%)"
        )

    obs_policy = study_cfg.get("execution", {}).get("observation_policy", {})
    required_relation = obs_policy.get("required_source_relation", "equal")

    future_source_violations_count = 0
    exact_timestamp_equality_verified = False

    if required_relation == "equal":
        violations = cand_df["triggering_1s_ts_init"] != cand_df["observation_ts"]
        future_source_violations_count = int(violations.sum())
        exact_timestamp_equality_verified = bool(future_source_violations_count == 0)
        if future_source_violations_count > 0:
            raise SmokeValidationError(
                f"CAUSAL_VIOLATION: Found {future_source_violations_count} candidates where triggering_1s_ts_init != observation_ts!"
            )
    elif required_relation == "<=":
        violations = cand_df["triggering_1s_ts_init"] > cand_df["observation_ts"]
        future_source_violations_count = int(violations.sum())
        exact_timestamp_equality_verified = bool((cand_df["triggering_1s_ts_init"] == cand_df["observation_ts"]).all())
        if future_source_violations_count > 0:
            raise SmokeValidationError(
                f"CAUSAL_VIOLATION: Found {future_source_violations_count} candidates where triggering_1s_ts_init > observation_ts!"
            )
    else:
        future_source_violations_count = 0
        exact_timestamp_equality_verified = False

    # 9. Verify Feature Columns and Ordered SHA-256
    expected_feature_list = study_cfg.get("features", {}).get("feature_list", [])
    expected_feature_count = len(expected_feature_list)
    expected_feature_sha256 = hashlib.sha256(json.dumps(expected_feature_list).encode("utf-8")).hexdigest()

    if expected_feature_list:
        emitted_feature_cols = [c for c in cand_df.columns if c in set(expected_feature_list)]
    else:
        meta_cols = {
            "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index",
            "regime_age_seconds", "close", "atr", "running_mfe_atr", "running_mae_atr",
            "current_pnl_atr", "new_progress_windows", "retained_mfe_ratio", "triggering_1s_ts_init"
        }
        emitted_feature_cols = [c for c in cand_df.columns if c not in meta_cols]

    emitted_feature_sha256 = hashlib.sha256(json.dumps(emitted_feature_cols).encode("utf-8")).hexdigest()

    if expected_feature_count > 0 and len(emitted_feature_cols) != expected_feature_count:
        raise SmokeValidationError(
            f"FEATURE_COUNT_MISMATCH: Emitted {len(emitted_feature_cols)} features, expected {expected_feature_count}"
        )

    if expected_feature_count > 0 and emitted_feature_sha256 != expected_feature_sha256:
        raise SmokeValidationError(
            f"FEATURE_HASH_MISMATCH: Emitted feature hash ({emitted_feature_sha256}) != expected ({expected_feature_sha256})"
        )

    # 9b. Declared feature contract <=> produced VALUES (C1).
    # Steps 9 and 9a above compare names, counts and an ordered hash; all three pass on a
    # column that is null in every row, which is exactly how the historical 100%-NULL
    # wick collection was accepted. This re-derives the surface check independently of
    # the value recorded by the collector -- a deliberate second gate, not a duplicate.
    from scripts.check_feature_surface import validate_feature_surface

    declared_metadata = (study_cfg.get("features", {}) or {}).get("metadata_columns")
    surface_report = validate_feature_surface(
        cand_df, expected_feature_list, metadata_columns=declared_metadata
    )
    if not surface_report.passed:
        detail = "; ".join(f"[{f['code']}] {f['message']}" for f in surface_report.findings)
        raise SmokeValidationError(f"FEATURE_SURFACE_INVALID: {detail}")

    # The run itself must not have been filed as valid on a failing surface.
    if run_status.get("feature_surface_validation", {}).get("passed") is False:
        raise SmokeValidationError(
            "RUN_FEATURE_SURFACE_FAILED: the run recorded a failing feature surface validation"
        )

    # 9c. Candidate/observation reconciliation (E), re-derived from the artifacts.
    obs_file = run_dir / "collection" / "observations.parquet"
    if not obs_file.exists():
        raise SmokeValidationError(
            f"MISSING_OBSERVATIONS_PARQUET: {obs_file}. A collect run's observation surface "
            f"is a required deliverable; without it no candidate can be shown to have "
            f"reached a terminal disposition."
        )
    obs_df = pd.read_parquet(obs_file)
    reconciliation = reconcile_candidate_dispositions(cand_df, obs_df)
    if not reconciliation["passed"]:
        raise SmokeValidationError(
            "CANDIDATE_RECONCILIATION_FAILED: " + "; ".join(reconciliation["findings"])
        )

    # 10. Verify Direction / Population Coverage if configured
    if "regime_direction" in target_day_df.columns and study_cfg.get("population", {}).get("prevailing_regime") == "both":
        directions_present = list(target_day_df["regime_direction"].unique())
        if len(directions_present) < 2:
            raise SmokeValidationError(f"Expected both regime directions, found only: {directions_present}")

    # 11. Generate Deterministic smoke_acceptance.json
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    validator_file_sha = _hash_file(Path(__file__).resolve())
    cand_file_sha = _hash_file(cand_file)

    acceptance_payload = {
        "study_name": study_dir.name,
        "validator_version": VALIDATOR_VERSION,
        "validator_file_sha256": validator_file_sha,
        "run_dir": str(run_dir),
        "candidates_parquet_sha256": cand_file_sha,
        "sealed_composite_sha256": seal_hash,
        "execution_manifest_composite_sha256": manifest_hash,
        "smoke_date": expected_smoke_date,
        "candidate_rows_total": candidate_rows_total,
        "candidates_count_total": total_candidates,
        "candidates_count_target_day": target_day_candidates,
        "duplicate_candidates_count": duplicates_count,
        "causality_rows_examined": causality_rows_examined,
        "causality_coverage_pct": causality_coverage_pct,
        "future_source_violations_count": future_source_violations_count,
        "exact_timestamp_equality_verified": exact_timestamp_equality_verified,
        "feature_count": len(emitted_feature_cols),
        "feature_list_sha256": emitted_feature_sha256,
        "feature_surface_validation": surface_report.to_dict(),
        "candidate_disposition_reconciliation": reconciliation,
        "observations_count": int(len(obs_df)),
        "deterministic_validation_verified": True,
        "status": "ACCEPTED",
        "validated_at": now_iso,
    }

    acceptance_file = study_dir / "artifacts" / "smoke_acceptance.json"
    acceptance_file.parent.mkdir(parents=True, exist_ok=True)
    with open(acceptance_file, "w", encoding="utf-8") as f:
        json.dump(acceptance_payload, f, indent=2)

    return acceptance_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Smoke Validator for NautilusTrader Research")
    parser.add_argument("--study", "-s", type=str, required=True, help="Path to study directory")
    parser.add_argument("--run-dir", "-r", type=str, help="Specific run directory (default: latest day run)")
    parser.add_argument("--date", "-d", type=str, default="2023-03-03", help="Expected smoke date (default: 2023-03-03)")
    parser.add_argument("--json", action="store_true", help="Print json output")
    args = parser.parse_args()

    study_dir = Path(args.study).resolve()
    run_dir = Path(args.run_dir).resolve() if args.run_dir else None

    try:
        acc = validate_smoke_run(study_dir, run_dir, expected_smoke_date=args.date)
        if args.json:
            print(json.dumps(acc, indent=2))
        else:
            print("=" * 60)
            print(f"SMOKE VALIDATION PASSED: {study_dir.name}")
            print(f"Status:                      {acc['status']}")
            print(f"Smoke Target Date:           {acc['smoke_date']}")
            print(f"Candidates (Target Day):     {acc['candidates_count_target_day']}")
            print(f"Future Source Violations:    {acc['future_source_violations_count']}")
            print(f"Exact Timestamp Equality:    {acc['exact_timestamp_equality_verified']}")
            print(f"Emitted Feature Count:       {acc['feature_count']} (SHA: {acc['feature_list_sha256'][:16]}...)")
            print(f"Sealed Composite Hash:       {acc['sealed_composite_sha256'][:16]}...")
            print(f"Emitted Acceptance File:     {study_dir / 'artifacts' / 'smoke_acceptance.json'}")
            print("=" * 60)
        return 0
    except Exception as exc:
        print(f"SMOKE_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
