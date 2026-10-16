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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DIGEST_METHOD = "sha256(sorted(relpath,size,sha256(bytes)) under <catalog>/data)"
DATASET_MANIFEST_NAME = "dataset_manifest.json"
SCOPED_DIGEST_METHOD = "sha256(manifest-ordered (relpath,size,sha256(bytes)) of the data/ files a [start,end] bar query can open)"
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


class DatasetScopeRefused(RuntimeError):
    """The scoped byte check refused before reading any data byte (inconsistent manifest, or a
    forbidden-period file inside the run window)."""


class DatasetFilesDrifted(RuntimeError):
    """The catalog files on disk no longer match the manifest that was written for them."""


@dataclass(frozen=True)
class RootConfig:
    path: Optional[Path]
    catalog_roots: tuple[Path, ...]
    model_root: Optional[Path]
    leases_dir: Path
    worktree_root: Optional[Path]
    lease_ttl_seconds: int = 259200   # 72h: how long a writer lease stays `live` past its holder's last renewal

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
            "lease_ttl_seconds": self.lease_ttl_seconds,
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
    ttl = int(raw["lease_ttl_seconds"]) if raw.get("lease_ttl_seconds") else 259200
    return RootConfig(Path(p).resolve(), roots, model_root, leases, worktree_root, ttl)


# ---------------------------------------------------------------------------
# Dataset digests and on-disk manifests
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _entries_digest(entries: Iterable[Dict[str, Any]]) -> str:
    payload = json.dumps([[e["path"], e["size"], e["sha256"]] for e in entries], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_catalog_digest(catalog_dir: Path) -> Dict[str, Any]:
    """Content digest of an immutable NautilusTrader catalog directory."""
    catalog_dir = Path(catalog_dir).resolve()
    data_dir = catalog_dir / "data"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"CATALOG_DATA_DIR_MISSING: {data_dir}")
    entries: List[Dict[str, Any]] = []
    for p in sorted(x for x in data_dir.rglob("*") if x.is_file()):
        entries.append({"path": p.relative_to(catalog_dir).as_posix(), "size": p.stat().st_size, "sha256": _sha256_file(p)})
    return {"logical_digest": _entries_digest(entries), "digest_method": DIGEST_METHOD,
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


def verify_dataset_files(catalog_dir: Path, manifest: Dict[str, Any]) -> None:
    """Cheap live check: every manifest file exists with its recorded size and no extra files
    appeared under ``data/``. Catches truncation, additions and replacements of different size."""
    catalog_dir = Path(catalog_dir).resolve()
    recorded = {e["path"]: int(e["size"]) for e in manifest.get("files") or []}
    for rel, size in recorded.items():
        f = catalog_dir / rel
        if not f.is_file():
            raise DatasetFilesDrifted(f"DATASET_FILES_DRIFTED: {rel} missing from {catalog_dir}")
        if f.stat().st_size != size:
            raise DatasetFilesDrifted(f"DATASET_FILES_DRIFTED: {rel} size {f.stat().st_size} != manifest {size}")
    data_dir = catalog_dir / "data"
    if data_dir.is_dir():
        actual = {p.relative_to(catalog_dir).as_posix() for p in data_dir.rglob("*") if p.is_file()}
        extra = sorted(actual - set(recorded))
        if extra:
            raise DatasetFilesDrifted(f"DATASET_FILES_DRIFTED: files not in manifest: {extra[:5]}")


def verify_dataset_bytes(catalog_dir: Path, expected_digest: str) -> Dict[str, Any]:
    """Authoritative live check: recompute the content digest from the bytes on disk."""
    digest = compute_catalog_digest(catalog_dir)
    if digest["logical_digest"] != expected_digest:
        raise DatasetDigestMismatch(f"DATASET_DIGEST_MISMATCH: live bytes digest {digest['logical_digest']} != expected {expected_digest}")
    return digest


def utc_year_interval_ns(year: int) -> Tuple[int, int]:
    """[Jan 1 00:00, Dec 31 23:59:59.999999999] UTC of ``year``: the chronology's year boundary."""
    a = int(datetime(int(year), 1, 1, tzinfo=timezone.utc).timestamp()) * 1_000_000_000
    b = int(datetime(int(year) + 1, 1, 1, tzinfo=timezone.utc).timestamp()) * 1_000_000_000 - 1
    return a, b


def bar_file_interval(relpath: str) -> Optional[Tuple[int, int]]:
    """The ``[first_ts, last_ts]`` NautilusTrader encodes in a catalog data file name, parsed by
    NautilusTrader's own rule (the rule its queries select files by). None when the name carries no
    interval -- NautilusTrader then opens the file for EVERY query, so callers must treat it as in scope."""
    from nautilus_trader.persistence.catalog.parquet import _parse_filename_timestamps
    try:
        return _parse_filename_timestamps(relpath)
    except (ValueError, TypeError, IndexError):
        return None


def _intersects(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]   # closed intervals, as NautilusTrader's _query_intersects_filename


def _bar_dir(relpath: str) -> Optional[str]:
    parts = relpath.split("/")
    return parts[2] if len(parts) >= 4 and parts[0] == "data" and parts[1] == "bar" else None


def verify_dataset_scope(catalog_dir: Path, expected_digest: str, *, windows: Sequence[Tuple[int, int]], bar_types: Sequence[str] = (),
                         forbidden: Sequence[Tuple[int, int]] = ()) -> Dict[str, Any]:
    """Prove the bytes that runs over the closed ``windows`` (ns) can open, and only those.

    1. Identity without reading data: the on-disk manifest's own ``(path, size, sha256)`` inventory must
       re-hash to the committed ``logical_digest`` (so the manifest IS the dataset identity), and the live
       ``data/`` tree must match that inventory by name and size (missing / extra / resized files refuse).
    2. Scope: a file is out of scope ONLY when it is a bar file whose filename interval is provably disjoint
       from every window. Everything else -- unparseable names, non-bar data, overlapping files -- is in scope.
    3. Authorization: an in-scope bar file overlapping a ``forbidden`` interval, or of unknown interval while
       any period is forbidden, refuses BEFORE any data byte is read.
    4. Only in-scope files are opened: bytes re-hashed against the manifest, parquet footer ``ts_init``
       statistics checked against the filename interval.
    """
    catalog_dir = Path(catalog_dir).resolve()
    manifest = read_dataset_manifest(catalog_dir)
    if not manifest:
        raise DatasetScopeRefused(f"DATASET_SCOPE_MANIFEST_MISSING: {catalog_dir / DATASET_MANIFEST_NAME}")
    entries = list(manifest.get("files") or [])
    paths = [str(e.get("path")) for e in entries]
    malformed = [e.get("path") for e in entries if not (str(e.get("path", "")).startswith("data/") and isinstance(e.get("size"), int)
                                                         and isinstance(e.get("sha256"), str) and len(e["sha256"]) == 64)]
    if malformed or len(set(paths)) != len(paths):
        raise DatasetScopeRefused(f"DATASET_SCOPE_MANIFEST_INCONSISTENT: malformed or duplicate entries {(malformed or paths)[:3]}")
    if manifest.get("logical_digest") != expected_digest or _entries_digest(entries) != expected_digest:
        raise DatasetScopeRefused(f"DATASET_SCOPE_MANIFEST_INCONSISTENT: inventory re-hashes to {_entries_digest(entries)[:12]}, "
                                  f"manifest declares {str(manifest.get('logical_digest'))[:12]}, committed {expected_digest[:12]}")
    verify_dataset_files(catalog_dir, manifest)
    wins = [(int(a), int(b)) for a, b in windows]
    if not wins or any(a > b for a, b in wins):
        raise DatasetScopeRefused(f"DATASET_SCOPE_WINDOW_INVALID: {wins}")
    intervals = {p: (bar_file_interval(p) if _bar_dir(p) else None) for p in paths}
    by_dir: Dict[str, List[Tuple[int, int, str]]] = {}
    for p, iv in intervals.items():
        if iv is not None:
            if iv[0] > iv[1]:
                raise DatasetScopeRefused(f"DATASET_SCOPE_MANIFEST_INCONSISTENT: {p} interval start > end")
            by_dir.setdefault(_bar_dir(p), []).append((iv[0], iv[1], p))
    for d, ivs in by_dir.items():
        ivs.sort()
        for (_a0, a1, pa), (b0, _b1, pb) in zip(ivs, ivs[1:]):
            if b0 <= a1:
                raise DatasetScopeRefused(f"DATASET_SCOPE_MANIFEST_INCONSISTENT: overlapping file intervals in {d}: {pa}, {pb}")
    scoped, skipped = [], 0
    for e in entries:
        iv = intervals[e["path"]]
        if iv is not None and not any(_intersects(iv, w) for w in wins):
            skipped += 1
            continue
        if _bar_dir(e["path"]) is not None:
            if iv is None and forbidden:
                raise DatasetScopeRefused(f"DATASET_SCOPE_UNAUTHORIZED_FILE: {e['path']} carries no interval and would be opened by every query")
            hit = next((f for f in forbidden if iv is not None and _intersects(iv, f)), None)
            if hit is not None:
                raise DatasetScopeRefused(f"DATASET_SCOPE_UNAUTHORIZED_FILE: {e['path']} [{iv[0]}, {iv[1]}] overlaps a forbidden period "
                                          f"[{hit[0]}, {hit[1]}] and lies inside a run window {[list(w) for w in wins]}")
        scoped.append((e, iv))
    for bt in bar_types:
        if by_dir.get(bt) and not any(_bar_dir(e["path"]) == bt for e, _ in scoped):
            raise DatasetScopeRefused(f"DATASET_SCOPE_NO_COVERAGE: no {bt} file intersects the run windows {[list(w) for w in wins]}")
    files: List[Dict[str, Any]] = []
    for e, iv in scoped:   # the only files opened
        f = catalog_dir / e["path"]
        if f.stat().st_size != e["size"] or _sha256_file(f) != e["sha256"]:
            raise DatasetDigestMismatch(f"DATASET_DIGEST_MISMATCH: {e['path']} bytes differ from the manifest (scoped verification)")
        footer = _footer_ts_init(f) if iv is not None else None
        if footer is not None and not (iv[0] <= footer[0] and footer[1] <= iv[1]):
            raise DatasetScopeRefused(f"DATASET_SCOPE_MANIFEST_INCONSISTENT: {e['path']} ts_init [{footer[0]}, {footer[1]}] outside its filename interval")
        files.append({"path": e["path"], "size": e["size"], "sha256": e["sha256"], "interval_ns": list(iv) if iv else None,
                      "footer_ts_init_ns": list(footer) if footer else None})
    covered: Dict[str, List[List[int]]] = {}
    for f in files:
        if f["interval_ns"]:
            covered.setdefault(_bar_dir(f["path"]), []).append(f["interval_ns"])
    return {"status": "VERIFIED_SCOPED", "method": SCOPED_DIGEST_METHOD, "logical_digest": expected_digest,
            "windows_ns": [list(w) for w in wins], "bar_types": list(bar_types), "forbidden_ns": [list(f) for f in forbidden],
            "scoped_digest": _entries_digest(files), "files": files, "covered_intervals_ns": covered,
            "file_count": len(files), "total_bytes": sum(f["size"] for f in files), "out_of_scope_file_count": skipped,
            "inventory_file_count": len(entries)}


def _footer_ts_init(path: Path) -> Optional[Tuple[int, int]]:
    """min/max ``ts_init`` from the parquet footer statistics; None when the file is not parquet or has no stats."""
    try:
        import pyarrow.parquet as pq
        md = pq.ParquetFile(path).metadata
    except Exception:
        return None
    try:
        idx = md.schema.names.index("ts_init")
    except ValueError:
        return None
    lo = hi = None
    for i in range(md.num_row_groups):
        st = md.row_group(i).column(idx).statistics
        if st is None or not st.has_min_max:
            return None
        lo = st.min if lo is None else min(lo, st.min)
        hi = st.max if hi is None else max(hi, st.max)
    return None if lo is None else (int(lo), int(hi))


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
            if verify_digest:
                verify_dataset_files(path, on_disk)
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
    if verify_digest:
        verify_dataset_files(path, read_dataset_manifest(path) or {})
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
    "DatasetRootUnresolved", "DuplicateDatasetConflict", "DatasetDigestMismatch", "DatasetFilesDrifted", "ResolvedDataset",
    "load_config", "config_path", "compute_catalog_digest", "write_dataset_manifest", "read_dataset_manifest",
    "resolve_dataset", "committed_dataset_spec_path", "resolve_model_root", "verify_dataset_files", "verify_dataset_bytes",
    "SCOPED_DIGEST_METHOD", "DatasetScopeRefused", "verify_dataset_scope", "bar_file_interval", "utc_year_interval_ns",
]
