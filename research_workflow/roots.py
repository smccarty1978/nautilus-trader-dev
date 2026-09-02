"""Machine-local immutable roots: catalogs and the model store.

Scientific identity never depends on a machine path. A study binds a ``dataset_id``;
the committed DatasetSpec (``research/datasets/<id>.yaml``) carries the dataset's
``logical_digest``; this module resolves that identity to a physical directory through
the operator's machine-local configuration and proves the on-disk copy carries the same
digest. Receipts record ``dataset_id`` + digest, never the resolved path.

Configuration (first found wins):
    $NT_RESEARCH_CONFIG            explicit path to a config YAML
    ~/.nt_research/config.yaml     default location

    catalog_roots:
      - D:/market-data/catalog      # each root holds <dataset_id>/dataset_manifest.json
    model_root: ~/.nt_research/models
    leases_dir: ~/.nt_research/leases   # optional, defaults under the config dir
    worktree_root: C:/Users/me/Projects  # optional, defaults to the repo's parent

Rules
-----
* When ``catalog_roots`` is configured, dataset resolution goes ONLY through the roots.
  There is no repo-relative fallback (``DATASET_ROOT_UNRESOLVED`` is a hard failure).
* Two roots holding the same ``dataset_id`` with different digests -> hard failure
  (``DUPLICATE_DATASET_CONFLICT``). Identical digests in several roots are acceptable;
  the first configured root wins deterministically.
* When no config exists (transitional/legacy mode) the committed ``catalog_rel_path``
  is resolved relative to the repository root, exactly as before.

The digest is the *content digest* of the immutable catalog files:
``sha256`` over the sorted list of ``(relative_path, size, sha256(file bytes))`` for
every file under ``<catalog>/data``. Identical copies on different machines produce the
same digest; a row-level logical digest is a later dataset-version concern.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DIGEST_METHOD = "sha256(sorted(relpath,size,sha256(bytes)) under <catalog>/data)"
DATASET_MANIFEST_NAME = "dataset_manifest.json"
CONFIG_ENV = "NT_RESEARCH_CONFIG"
DEFAULT_CONFIG_DIR = Path.home() / ".nt_research"


class RootConfigError(RuntimeError):
    """The machine-local root configuration is malformed."""


class DatasetRootUnresolved(RuntimeError):
    """``catalog_roots`` is configured but no root carries the dataset with the declared digest."""


class DuplicateDatasetConflict(RuntimeError):
    """Two configured roots carry the same dataset_id with different digests."""


class DatasetDigestMismatch(RuntimeError):
    """The on-disk dataset manifest digest does not match the committed DatasetSpec digest."""


@dataclass(frozen=True)
class RootConfig:
    path: Optional[Path]
    catalog_roots: tuple[Path, ...]
    model_root: Optional[Path]
    leases_dir: Path
    worktree_root: Optional[Path]

    @property
    def active(self) -> bool:
        return bool(self.catalog_roots)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "config_path": str(self.path) if self.path else None,
            "catalog_roots": [str(p) for p in self.catalog_roots],
            "model_root": str(self.model_root) if self.model_root else None,
            "leases_dir": str(self.leases_dir),
            "worktree_root": str(self.worktree_root) if self.worktree_root else None,
        }


def _expand(value: Any) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(str(value)))).resolve()


def config_path() -> Optional[Path]:
    env = os.environ.get(CONFIG_ENV)
    if env:
        p = Path(env)
        return p if p.is_file() else None
    p = DEFAULT_CONFIG_DIR / "config.yaml"
    return p if p.is_file() else None


def load_config(path: Optional[Path] = None) -> RootConfig:
    """Load the machine-local root configuration; absent config -> inactive (legacy mode)."""
    p = path if path is not None else config_path()
    # Test/process-local override of the model store root (never of catalog roots): lets a
    # test suite keep the operator's catalogs while isolating every fit it persists.
    model_override = os.environ.get("NT_RESEARCH_MODEL_ROOT")
    if p is None:
        return RootConfig(None, (), _expand(model_override) if model_override else None, DEFAULT_CONFIG_DIR / "leases", None)
    import yaml
    raw = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise RootConfigError(f"ROOT_CONFIG_MALFORMED: {p} must be a mapping")
    roots_raw = raw.get("catalog_roots") or []
    if not isinstance(roots_raw, list) or any(not isinstance(r, str) for r in roots_raw):
        raise RootConfigError("ROOT_CONFIG_MALFORMED: catalog_roots must be a list of strings")
    roots = tuple(_expand(r) for r in roots_raw)
    model_root = _expand(model_override) if model_override else (_expand(raw["model_root"]) if raw.get("model_root") else None)
    leases = _expand(raw["leases_dir"]) if raw.get("leases_dir") else Path(p).resolve().parent / "leases"
    worktree_root = _expand(raw["worktree_root"]) if raw.get("worktree_root") else None
    return RootConfig(Path(p).resolve(), roots, model_root, leases, worktree_root)


# ---------------------------------------------------------------------------
# Dataset digests and on-disk manifests
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_catalog_digest(catalog_dir: Path) -> Dict[str, Any]:
    """Content digest of an immutable NautilusTrader catalog directory."""
    catalog_dir = Path(catalog_dir).resolve()
    data_dir = catalog_dir / "data"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"CATALOG_DATA_DIR_MISSING: {data_dir}")
    entries: List[Dict[str, Any]] = []
    for p in sorted(x for x in data_dir.rglob("*") if x.is_file()):
        entries.append({"path": p.relative_to(catalog_dir).as_posix(), "size": p.stat().st_size, "sha256": _sha256_file(p)})
    payload = json.dumps([[e["path"], e["size"], e["sha256"]] for e in entries], separators=(",", ":"))
    return {"logical_digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "digest_method": DIGEST_METHOD,
            "file_count": len(entries), "total_bytes": sum(e["size"] for e in entries), "files": entries}


def write_dataset_manifest(catalog_dir: Path, dataset_id: str, instrument_id: Optional[str] = None) -> Dict[str, Any]:
    """Write ``<catalog>/dataset_manifest.json`` (the on-disk identity a root is matched by)."""
    digest = compute_catalog_digest(catalog_dir)
    manifest = {"schema_version": 1, "dataset_id": dataset_id, "instrument_id": instrument_id,
                "logical_digest": digest["logical_digest"], "digest_method": digest["digest_method"],
                "file_count": digest["file_count"], "total_bytes": digest["total_bytes"], "files": digest["files"],
                "generated_at_utc": datetime.now(timezone.utc).isoformat()}
    (Path(catalog_dir) / DATASET_MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_dataset_manifest(catalog_dir: Path) -> Optional[Dict[str, Any]]:
    p = Path(catalog_dir) / DATASET_MANIFEST_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Dataset resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedDataset:
    dataset_id: str
    catalog_path: Path
    logical_digest: Optional[str]
    resolution: str   # "configured_root" | "legacy_repo_relative"
    root: Optional[Path]

    def identity(self) -> Dict[str, Any]:
        """What a receipt records: identity and digest, never the machine path."""
        return {"dataset_id": self.dataset_id, "logical_digest": self.logical_digest, "resolution": self.resolution}


def committed_dataset_spec_path(dataset_id: str, repo_root: Path) -> Path:
    return (Path(repo_root) / "research" / "datasets" / f"{dataset_id}.yaml").resolve()


def resolve_dataset(dataset_id: str, repo_root: Path, *, config: Optional[RootConfig] = None,
                    catalog_rel_path: Optional[str] = None, verify_digest: bool = True) -> ResolvedDataset:
    """Resolve ``dataset_id`` to a physical catalog directory.

    ``catalog_rel_path`` is the legacy repo-relative location (from PRODUCT_CATALOGS or the
    DatasetSpec); it is used ONLY when no ``catalog_roots`` are configured.
    """
    repo_root = Path(repo_root).resolve()
    cfg = config if config is not None else load_config()
    spec_path = committed_dataset_spec_path(dataset_id, repo_root)
    declared_digest: Optional[str] = None
    declared_rel: Optional[str] = catalog_rel_path
    if spec_path.is_file():
        import yaml
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
        declared_digest = spec.get("logical_digest") or None
        declared_rel = declared_rel or spec.get("catalog_rel_path")

    if not cfg.active:
        if not declared_rel:
            raise DatasetRootUnresolved(f"DATASET_ROOT_UNRESOLVED: no catalog_roots configured and no catalog_rel_path known for {dataset_id!r}")
        path = (repo_root / declared_rel).resolve()
        digest = None
        on_disk = read_dataset_manifest(path) if path.is_dir() else None
        if on_disk:
            digest = on_disk.get("logical_digest")
            if verify_digest and declared_digest and digest != declared_digest:
                raise DatasetDigestMismatch(f"DATASET_DIGEST_MISMATCH: {dataset_id} on-disk {digest} != committed {declared_digest}")
        return ResolvedDataset(dataset_id, path, digest or declared_digest, "legacy_repo_relative", None)

    # Configured roots: the only resolution path. No repo-relative fallback.
    if not declared_digest:
        raise DatasetRootUnresolved(
            f"DATASET_ROOT_UNRESOLVED: catalog_roots are configured but {spec_path} declares no logical_digest; "
            f"run 'research data manifest {dataset_id}' and commit the digest")
    matches: List[tuple[Path, Path, str]] = []
    conflicts: List[tuple[Path, str]] = []
    for root in cfg.catalog_roots:
        candidate = root / dataset_id
        on_disk = read_dataset_manifest(candidate) if candidate.is_dir() else None
        if not on_disk:
            continue
        if on_disk.get("dataset_id") != dataset_id:
            conflicts.append((candidate, f"dataset_id={on_disk.get('dataset_id')!r}"))
            continue
        d = str(on_disk.get("logical_digest") or "")
        if d == declared_digest:
            matches.append((root, candidate, d))
        else:
            conflicts.append((candidate, d))
    if conflicts and not matches:
        raise DuplicateDatasetConflict(
            f"DUPLICATE_DATASET_CONFLICT: {dataset_id} found only with digests != committed {declared_digest[:12]}...: "
            + ", ".join(f"{p} ({d[:12] if len(d) >= 12 else d})" for p, d in conflicts))
    if conflicts and matches:
        raise DuplicateDatasetConflict(
            f"DUPLICATE_DATASET_CONFLICT: {dataset_id} present with conflicting digests across roots: "
            + ", ".join(f"{p} ({d[:12] if len(d) >= 12 else d})" for p, d in conflicts)
            + "; matching copies: " + ", ".join(str(c) for _, c, _ in matches))
    if not matches:
        raise DatasetRootUnresolved(
            f"DATASET_ROOT_UNRESOLVED: no configured catalog root carries {dataset_id} with digest {declared_digest[:12]}...; "
            f"roots={[str(r) for r in cfg.catalog_roots]}")
    root, path, digest = matches[0]
    return ResolvedDataset(dataset_id, path, digest, "configured_root", root)


# ---------------------------------------------------------------------------
# Model root
# ---------------------------------------------------------------------------

def resolve_model_root(config: Optional[RootConfig] = None, *, create: bool = False) -> Optional[Path]:
    cfg = config if config is not None else load_config()
    if cfg.model_root is None:
        return None
    if create:
        cfg.model_root.mkdir(parents=True, exist_ok=True)
    return cfg.model_root


__all__ = [
    "CONFIG_ENV", "DIGEST_METHOD", "DATASET_MANIFEST_NAME", "RootConfig", "RootConfigError",
    "DatasetRootUnresolved", "DuplicateDatasetConflict", "DatasetDigestMismatch", "ResolvedDataset",
    "load_config", "config_path", "compute_catalog_digest", "write_dataset_manifest", "read_dataset_manifest",
    "resolve_dataset", "committed_dataset_spec_path", "resolve_model_root",
]
