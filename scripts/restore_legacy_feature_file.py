"""Explicit operator tool to restore one archived legacy source file exactly."""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "features" / "archive" / "legacy_registry_2026_08_22"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("relative_path")
    args = parser.parse_args()
    source = (ARCHIVE / args.relative_path).resolve()
    target = (ROOT / args.relative_path).resolve()
    if not source.is_file() or ROOT not in target.parents:
        raise SystemExit("INVALID_RESTORE_TARGET")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
        raise SystemExit("RESTORE_HASH_MISMATCH")
    print(f"RESTORED {args.relative_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
