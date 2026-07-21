"""Shared paths/constants for the NT event-driven pure-flip-trigger POC."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
PHASE2, RESULTS, AUDIT, WORK = STUDY / "phase2", STUDY / "results", STUDY / "audit", STUDY / "_work"

CATALOG_PATH = ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
ENTRY_POLICY_WORK = ROOT / "studies" / "short_rth_pure_flip_score_entry_policy" / "_work"

BAR_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
BAR_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
INSTRUMENT_ID = "NQ.XCME"

NS = 1_000_000_000
NQ_MULT = 20.0
COST_RT = 10.0
TICK = 0.25
STOP_ATR_MULT = 1.25

SELECTED_MONTH = "2025-03"
VARIANTS = {"T1": "trig_B_top2.5", "T2": "trig_C30_top5", "T3": "trig_B_top5"}

# Full-year load from Jan 1 for fresh RegimeEngine warmup, matching the
# offline atlas construction convention (fable5_nt_short_rth_policy_a).
LOAD_START = pd.Timestamp("2025-01-01", tz="UTC")
LOAD_END = pd.Timestamp("2025-12-31 23:59:59", tz="UTC")

for _p in (PHASE2, RESULTS, AUDIT, WORK):
    _p.mkdir(parents=True, exist_ok=True)


def schedule_path(variant_label: str) -> Path:
    return WORK / f"nt_schedule_{variant_label}.parquet"


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()
