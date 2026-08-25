"""Provenance binding and persistence for forward-outcome artifacts.

An outcome table is only interpretable next to the exact entry set, spec and code that
produced it, so the manifest binds all four and the reconciliation recomputes them from
disk rather than trusting what the manifest says about itself.

The manifest also carries the artifact's declared role. Forward outcomes are
``OUTCOME_LABEL_POST_EVENT`` data: non-causal relative to entry time and never a model
input. Stating that in the artifact means a downstream consumer can refuse the table
without having to recognise the column names.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from research.analysis.identity import canonical_sha256, sha256_file
from research_workflow.forward_outcomes.contracts import (
    ForwardOutcomeError,
    ForwardOutcomeSpec,
    ProposedEntry,
)
from research_workflow.forward_outcomes.guard import (
    OUTCOME_DATA_CLASS,
    assert_outcome_columns_not_registrable,
    outcome_table_metadata,
)
from research_workflow.forward_outcomes.selection import entries_to_frame

SCHEMA_VERSION = 1
PACKAGE_DIR = Path(__file__).resolve().parent

ENTRIES_FILE = "proposed_entries.parquet"
OUTCOMES_FILE = "forward_outcomes.parquet"
MANIFEST_FILE = "forward_outcome_manifest.json"


class OutcomeProvenanceError(ForwardOutcomeError):
    """Raised when an outcome artifact does not reconcile with its own manifest."""


def code_identity() -> dict[str, str]:
    """Line-ending-normalised hashes of this package's own sources."""
    from scripts.resolve_execution_manifest import canonical_file_sha256

    return {
        path.name: canonical_file_sha256(path)
        for path in sorted(PACKAGE_DIR.glob("*.py"))
    }


def outcomes_to_frame(records: Sequence[Mapping[str, Any]], spec: ForwardOutcomeSpec) -> pd.DataFrame:
    """Materialise outcome records in the exact schema the spec generates."""
    columns = list(spec.outcome_columns())
    if not records:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    frame = pd.DataFrame.from_records(list(records))
    unexpected = [c for c in frame.columns if c not in columns]
    if unexpected:
        raise OutcomeProvenanceError(
            f"outcome records carry columns the spec does not generate: {unexpected[:10]}"
        )
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise OutcomeProvenanceError(
            f"outcome records are missing generated columns: {missing[:10]}"
        )
    return frame[columns].sort_values(["entry_ts", "entry_id"], kind="mergesort").reset_index(drop=True)


def write_outcome_artifacts(
    output_dir: str | Path,
    *,
    entries: Sequence[ProposedEntry],
    records: Sequence[Mapping[str, Any]],
    spec: ForwardOutcomeSpec,
    study_id: str,
    source_period: str,
    authorization_sha256: str,
    source_freeze_sha256: str,
    source_identity: Mapping[str, Any],
    selector_identity: Optional[Mapping[str, Any]] = None,
    partitions: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Persist entries, outcomes and a manifest that binds them to their authority."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # The registry door is checked at write time, not only in tests: an artifact whose
    # columns could be requested as features must never reach disk.
    registry_check = assert_outcome_columns_not_registrable(spec)

    entry_frame = entries_to_frame(entries)
    outcome_frame = outcomes_to_frame(records, spec)

    entry_ids = set(entry_frame["entry_id"]) if not entry_frame.empty else set()
    outcome_ids = set(outcome_frame["entry_id"]) if not outcome_frame.empty else set()
    if entry_ids != outcome_ids:
        missing = sorted(entry_ids - outcome_ids)
        extra = sorted(outcome_ids - entry_ids)
        raise OutcomeProvenanceError(
            f"entry/outcome sets disagree: {len(missing)} entries without an outcome "
            f"{missing[:5]}, {len(extra)} outcomes without an entry {extra[:5]}. Every "
            f"proposed entry must resolve to exactly one outcome row, including the "
            f"censored ones."
        )

    entry_path = out / ENTRIES_FILE
    outcome_path = out / OUTCOMES_FILE
    entry_frame.to_parquet(entry_path, index=False)
    outcome_frame.to_parquet(outcome_path, index=False)

    status_counts = (
        Counter(outcome_frame["outcome_status"].fillna("UNKNOWN")) if not outcome_frame.empty else Counter()
    )
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "study_id": study_id,
        "source_period": source_period,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_class": OUTCOME_DATA_CLASS,
        "outcome_table_metadata": dict(outcome_table_metadata(spec)),
        "spec": spec.to_dict(),
        "spec_sha256": spec.spec_sha256,
        "authorization_sha256": authorization_sha256,
        "source_freeze_sha256": source_freeze_sha256,
        "source_identity": dict(source_identity),
        "selector_identity": dict(selector_identity or {}),
        "partitions": [dict(p) for p in (partitions or [])],
        "code_identity": code_identity(),
        "registry_guard": registry_check,
        "entry_count": int(len(entry_frame)),
        "outcome_count": int(len(outcome_frame)),
        "entry_set_sha256": canonical_sha256(sorted(e.entry_sha256 for e in entries)),
        "outcome_status_counts": {str(k): int(v) for k, v in sorted(status_counts.items())},
        "outcome_columns": list(spec.outcome_columns()),
        "artifacts": {
            ENTRIES_FILE: sha256_file(entry_path),
            OUTCOMES_FILE: sha256_file(outcome_path),
        },
    }
    body["manifest_sha256"] = canonical_sha256(
        {k: v for k, v in body.items() if k != "generated_at_utc"}
    )
    (out / MANIFEST_FILE).write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
    return body


def reconcile_outcome_artifacts(output_dir: str | Path) -> dict[str, Any]:
    """Recompute every bound identity from disk and report disagreements.

    Deliberately recomputed rather than read back: a manifest that agrees only with
    itself proves nothing about the parquet sitting next to it.
    """
    out = Path(output_dir).resolve()
    manifest_path = out / MANIFEST_FILE
    if not manifest_path.is_file():
        raise OutcomeProvenanceError(f"no forward-outcome manifest at {manifest_path}")
    body = json.loads(manifest_path.read_text(encoding="utf-8"))

    findings: list[str] = []
    expected = canonical_sha256({k: v for k, v in body.items() if k not in ("generated_at_utc", "manifest_sha256")})
    if body.get("manifest_sha256") != expected:
        findings.append("manifest_sha256 does not match its own body")

    for name, recorded in (body.get("artifacts") or {}).items():
        path = out / name
        if not path.is_file():
            findings.append(f"missing artifact: {name}")
            continue
        if sha256_file(path) != recorded:
            findings.append(f"artifact hash drift: {name}")

    entries = pd.read_parquet(out / ENTRIES_FILE) if (out / ENTRIES_FILE).is_file() else pd.DataFrame()
    outcomes = pd.read_parquet(out / OUTCOMES_FILE) if (out / OUTCOMES_FILE).is_file() else pd.DataFrame()

    if len(entries) != body.get("entry_count"):
        findings.append(f"entry_count mismatch: {len(entries)} on disk vs {body.get('entry_count')}")
    if len(outcomes) != body.get("outcome_count"):
        findings.append(f"outcome_count mismatch: {len(outcomes)} on disk vs {body.get('outcome_count')}")
    if not entries.empty and entries["entry_id"].duplicated().any():
        findings.append("duplicate entry_id in proposed_entries")
    if not outcomes.empty and outcomes["entry_id"].duplicated().any():
        findings.append("duplicate entry_id in forward_outcomes")
    if not entries.empty and not outcomes.empty:
        if set(entries["entry_id"]) != set(outcomes["entry_id"]):
            findings.append("entry_id sets differ between proposed_entries and forward_outcomes")
    if not entries.empty:
        recomputed = canonical_sha256(sorted(entries["entry_sha256"].tolist()))
        if recomputed != body.get("entry_set_sha256"):
            findings.append("entry_set_sha256 does not match the persisted entry rows")
    if list(outcomes.columns) != list(body.get("outcome_columns") or []):
        findings.append("forward_outcomes columns do not match the spec-generated schema")
    if body.get("data_class") != OUTCOME_DATA_CLASS:
        findings.append(f"artifact is not declared as {OUTCOME_DATA_CLASS}")

    current_code = code_identity()
    if body.get("code_identity") and body["code_identity"] != current_code:
        drifted = sorted(
            k for k in set(current_code) | set(body["code_identity"])
            if current_code.get(k) != body["code_identity"].get(k)
        )
        findings.append(f"observation code changed since the artifact was written: {drifted}")

    return {
        "passed": not findings,
        "findings": findings,
        "entry_count": int(len(entries)),
        "outcome_count": int(len(outcomes)),
        "manifest_sha256": body.get("manifest_sha256"),
        "spec_sha256": body.get("spec_sha256"),
    }
