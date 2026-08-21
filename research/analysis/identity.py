"""Immutable collection identity (A0 §2).

An analysis binds to exactly one collection run. There is no `latest`. Identity is
recomputed from artifacts on disk rather than trusted from a manifest, so a manifest
that disagrees with its own parquet is detectable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from research.analysis.errors import InvalidRunId, MissingArtifact

SCHEMA_VERSION = "1.0.0"

# Documented fallback when a study declares no `features.metadata_columns`.
# Mirrors the default list in backtests/nt_runtime/output_manager.py. It is
# duplicated here deliberately: the analysis harness must not import the sealed
# collector runtime, and A0 blocker #5 records that this list should eventually be
# promoted to one shared constant.
DEFAULT_METADATA_COLUMNS: tuple = (
    "observation_ts", "regime_start_ns", "regime_direction", "checkpoint_index",
    "regime_age_seconds", "close", "atr", "running_mfe_atr", "running_mae_atr",
    "current_pnl_atr", "new_progress_windows", "retained_mfe_ratio",
    "triggering_1s_ts_init",
)

# Columns produced by the collector that describe the OUTCOME. They resolve only
# after the target horizon elapses and are therefore never features.
OUTCOME_COLUMNS: tuple = ("flip_ts", "time_to_flip_seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(payload: Any) -> str:
    """Stable hash of a JSON-serialisable payload (sorted keys, no whitespace drift)."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def sha256_json_file(path: Path) -> str:
    """Identity of a *structured text* artifact: hash of its parsed canonical form.

    Manifests are git-tracked text. Under `core.autocrlf` a Windows checkout and a
    Linux checkout hold byte-different but semantically identical files, so a raw
    byte hash makes collection identity platform-dependent and raises a false
    IDENTITY_MISMATCH off-platform. Parsing first removes line endings, key order and
    indentation from the identity while keeping every value in it.

    Generated binary data (`*.parquet`) keeps `sha256_file` — no normalisation, ever.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise MissingArtifact(f"{path} is not readable canonical JSON: {err}", path=str(path)) from err
    return canonical_sha256(payload)


@dataclass(frozen=True)
class CollectionIdentity:
    """The tuple every downstream artifact must carry (A0 §2)."""

    run_id: str
    study_id: str
    spec_sha256: Optional[str]
    composite_seal_hash: Optional[str]
    candidates_sha256: str
    observations_sha256: str
    collection_manifest_sha256: str
    feature_list_sha256: Optional[str]
    stage: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    warmup_start: Optional[str]
    timestamp_contract: Dict[str, Any] = field(default_factory=dict)

    @property
    def sealed(self) -> bool:
        return bool(self.composite_seal_hash)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def collection_identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def dataset_identity(
        self,
        *,
        recomputed_candidates_sha256: Optional[str] = None,
        recomputed_observations_sha256: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """The payload written to `dataset_identity.json`."""
        payload: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "collection_identity_sha256": self.collection_identity_sha256,
            "identity": self.to_dict(),
            "recomputed": {
                "candidates_sha256": recomputed_candidates_sha256,
                "observations_sha256": recomputed_observations_sha256,
            },
            "sealed": self.sealed,
        }
        if extra:
            payload.update(extra)
        return payload


def _read_json(path: Path, what: str) -> Dict[str, Any]:
    if not path.is_file():
        raise MissingArtifact(f"{what} not found at {path}", path=str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        raise MissingArtifact(f"{what} at {path} is not valid JSON: {err}", path=str(path)) from err


# A run_id is a directory NAME, never a path. Any of these characters turns it into
# a path expression, which is how `../secret_runs/<run>` escaped `runs_root` while
# `identity.run_id` kept only the basename and erased the traversal.
FORBIDDEN_RUN_ID_TOKENS: tuple = ("/", "\\", "..", ".", ":", "\x00")


def assert_plain_run_id(run_id: str) -> str:
    """Rejects anything that is not a single, literal directory name."""
    rid = "" if run_id is None else str(run_id)
    if not rid or rid.strip() != rid or not rid.strip():
        raise InvalidRunId(
            f"run_id={run_id!r} is not a plain run directory name", run_id=run_id
        )
    hit = [tok for tok in FORBIDDEN_RUN_ID_TOKENS if tok in rid]
    if hit:
        raise InvalidRunId(
            f"run_id={run_id!r} contains path syntax {hit}; a run_id is a directory name "
            f"inside runs_root, never a path",
            run_id=run_id, forbidden=hit,
        )
    return rid


@dataclass(frozen=True)
class CollectionPaths:
    run_dir: Path
    run_manifest: Path
    status: Path
    collection_manifest: Path
    candidates: Path
    observations: Path
    runs_root: Optional[Path] = None

    @property
    def resolved_run_dir(self) -> Path:
        return Path(self.run_dir).resolve()

    @classmethod
    def for_run(cls, run_id: str, runs_root: Path) -> "CollectionPaths":
        """Resolves `runs_root/<run_id>` and refuses anything outside `runs_root`.

        Containment is asserted on the RESOLVED paths, so a symlink or a `..` hidden
        in `runs_root` itself cannot smuggle the run directory somewhere else.
        """
        rid = assert_plain_run_id(run_id)
        root = Path(runs_root)
        run_dir = root / rid
        resolved_root = root.resolve()
        resolved_run = run_dir.resolve()
        if resolved_run.parent != resolved_root:
            raise InvalidRunId(
                f"run_id={run_id!r} resolves to {resolved_run} which is not a direct child of "
                f"runs_root {resolved_root}",
                run_id=run_id, resolved_run_dir=str(resolved_run),
                runs_root=str(resolved_root),
            )
        coll = run_dir / "collection"
        return cls(
            runs_root=root,
            run_dir=run_dir,
            run_manifest=run_dir / "run_manifest.json",
            status=run_dir / "status.json",
            collection_manifest=coll / "collection_manifest.json",
            candidates=coll / "candidates.parquet",
            observations=coll / "observations.parquet",
        )

    def require_all(self) -> None:
        for label, p in (
            ("run directory", self.run_dir),
            ("run_manifest.json", self.run_manifest),
            ("collection_manifest.json", self.collection_manifest),
            ("candidates.parquet", self.candidates),
            ("observations.parquet", self.observations),
        ):
            if not p.exists():
                raise MissingArtifact(f"{label} missing for run", path=str(p))


def build_identity(
    paths: CollectionPaths,
    run_manifest: Dict[str, Any],
    collection_manifest: Dict[str, Any],
    feature_list_sha256: Optional[str],
) -> CollectionIdentity:
    dates = run_manifest.get("dates") or {}
    return CollectionIdentity(
        run_id=paths.run_dir.name,
        study_id=collection_manifest.get("study_id") or run_manifest.get("study_id") or "",
        spec_sha256=run_manifest.get("spec_sha256"),
        composite_seal_hash=run_manifest.get("composite_seal_hash"),
        candidates_sha256=collection_manifest.get("candidates_sha256", ""),
        observations_sha256=collection_manifest.get("observations_sha256", ""),
        # Canonical-JSON, not raw bytes: the manifest is git-tracked text (M1).
        collection_manifest_sha256=sha256_json_file(paths.collection_manifest),
        feature_list_sha256=feature_list_sha256,
        stage=run_manifest.get("stage"),
        start_date=dates.get("start"),
        end_date=dates.get("end"),
        warmup_start=dates.get("warmup_start"),
        timestamp_contract=run_manifest.get("timestamp_contract") or {},
    )
