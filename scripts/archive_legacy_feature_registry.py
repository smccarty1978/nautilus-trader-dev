"""Create and verify the non-runtime Feature System V1 rollback archive.

The archive is deliberately produced before the active registry is changed.  It
contains source authority and lifecycle evidence only; production imports never
read from it.  Re-running is idempotent only when the existing archive hashes
match the source snapshot, preventing a later implementation state from being
silently mixed into the legacy record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = REPO_ROOT / "features" / "archive" / "legacy_registry_2026_08_22"
SOURCE_PATHS = (
    "features/registry.py",
    "features/FEATURE_REGISTRY_CONTRACT.md",
    "features/feature_lifecycle_baseline.json",
    "features/feature_definition_promotions.json",
    "features/coverage.py",
    "features/calendar_aggregation.py",
    "scripts/check_feature_promotion.py",
    "scratch/feature_system_v2_registry_mapping.json",
)
SOURCE_GLOBS = ("features/trackers/*.py",)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files() -> Iterable[Path]:
    for relative in SOURCE_PATHS:
        path = REPO_ROOT / relative
        if path.exists():
            yield path
    for pattern in SOURCE_GLOBS:
        yield from sorted(REPO_ROOT.glob(pattern))


def git_value(*args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=False, capture_output=True, text=True
    )
    return completed.stdout.strip() or None


def build(destination: Path) -> dict:
    sources = tuple(source_files())
    if not sources:
        raise RuntimeError("No legacy registry authority files found")
    entries = []
    for source in sources:
        relative = source.relative_to(REPO_ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and sha256(target) != sha256(source):
            raise RuntimeError(
                f"IMMUTABLE_ARCHIVE_CONFLICT: {target} differs from current legacy source"
            )
        if not target.exists():
            shutil.copy2(source, target)
        entries.append({"path": relative.as_posix(), "sha256": sha256(target), "bytes": target.stat().st_size})

    manifest = {
        "archive_format": 1,
        "archive_date": "2026-08-22",
        "reason": "Feature System V2 full canonical-registry migration rollback/reference snapshot",
        "source_commit": git_value("rev-parse", "HEAD"),
        "source_dirty_paths": (git_value("status", "--short") or "").splitlines(),
        "runtime_dependency": False,
        "migration_artifact": "scratch/feature_system_v2_full_migration_inventory.json",
        "files": entries,
    }
    hashes = {entry["path"]: entry["sha256"] for entry in entries}
    readme = """# Legacy Feature Registry Archive (2026-08-22)\n\nThis is a non-runtime, immutable rollback/reference snapshot created immediately\nbefore the Feature System V2 full canonical-registry cutover.  It preserves the\nlegacy registry, lifecycle evidence, promotion evidence, provider source, and\nrelevant schema/validation source.\n\nTo reference the previous authority, inspect the copied files in this directory.\nTo restore deliberately, copy only the required source files back to the repo and\nrestart governed acceptance; this archive is never imported by runtime code.\n\nThe complete migration inventory is written to\n`scratch/feature_system_v2_full_migration_inventory.json`.  `manifest.json` and\n`sha256s.json` enumerate and integrity-pin every archived source file.\n"""
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (destination / "sha256s.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (destination / "README.md").write_text(readme, encoding="utf-8")
    return manifest


def verify(destination: Path) -> dict:
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = json.loads((destination / "sha256s.json").read_text(encoding="utf-8"))
    actual = {entry["path"]: sha256(destination / entry["path"]) for entry in manifest["files"]}
    if actual != expected:
        raise RuntimeError("ARCHIVE_HASH_VERIFICATION_FAILED")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest = verify(args.destination) if args.verify_only else build(args.destination)
    verify(args.destination)
    print(json.dumps({"status": "PASS", "archive": str(args.destination), "files": len(manifest["files"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
