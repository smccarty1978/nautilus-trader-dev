from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
AUDIT = STUDY / "audit"
WORK = STUDY / "_work"
UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context" / "results"
ATLAS = UPSTREAM / "weakness_checkpoint_atlas.parquet"
FLIP_ATLAS = UPSTREAM / "flip_context_atlas.parquet"
MANIFEST = UPSTREAM / "weakness_model_manifest.json"

for path in (RESULTS, AUDIT, WORK):
    path.mkdir(parents=True, exist_ok=True)


def sha256(path: Path, block: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def read_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def year_catalog(year: int) -> Path:
    fixed = ROOT / "data" / "catalog" / f"NQ_v0_{year}_fixed"
    combined = ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
    return fixed if fixed.exists() else combined
