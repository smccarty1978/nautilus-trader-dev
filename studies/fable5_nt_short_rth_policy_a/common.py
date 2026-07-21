"""Shared paths/constants for the NT event-driven W4 short-RTH Policy A study."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS, AUDIT, WORK = STUDY / "results", STUDY / "audit", STUDY / "_work"

CATALOG_PATH = ROOT / "data" / "catalog" / "NQ_v0_2020_2026"
REPAIR_RESULTS = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair" / "results"

BAR_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
BAR_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
INSTRUMENT_ID = "NQ.XCME"

NS_PER_S = 1_000_000_000
NQ_MULT = 20.0
COST_RT = 10.0            # $ round-trip (matches offline Policy A benchmark)
TICK = 0.25

PREFLIP_STOP_ATR = 1.25
POSTFLIP_STOP_ATR = 1.50
TIMEOUT_S = 300

# RTH = 08:30-15:00 America/Chicago. This matches the repaired prior studies'
# is_rth (minute < 15*60) and the frozen `session` column that produced the
# 807-trade benchmark. The task text also writes "15:15"; that conflicts with
# the named source, so we use 15:00 and disclose it. RTH gates entry only.
RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60

# Full-year load/trade windows (UTC). Short-RTH frozen entries span
# 2025-01-02..2025-12-30 and 2026-01-02..2026-04-29, so we load full years.
LOAD_WINDOWS = {
    2025: (pd.Timestamp("2025-01-01", tz="UTC"),
           pd.Timestamp("2025-12-31 23:59:59", tz="UTC")),
    2026: (pd.Timestamp("2026-01-01", tz="UTC"),
           pd.Timestamp("2026-06-30 23:59:59", tz="UTC")),
}

# Offline short-RTH Policy A benchmark (from prior studies) for reconciliation.
BENCHMARK = {
    2025: {"trades": 604, "net_pnl": 20304.0, "per_trade": 33.62, "max_dd": 14331.0},
    2026: {"trades": 203, "net_pnl": 6709.0, "per_trade": 33.05, "max_dd": 11144.0},
    "combined": {"trades": 807, "net_pnl": 27013.0, "per_trade": 33.47,
                 "pf": 1.174, "max_dd": 14331.0},
}

for _p in (RESULTS, AUDIT, WORK):
    _p.mkdir(parents=True, exist_ok=True)


def frozen_trade_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def score_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"


def schedule_path(year: int) -> Path:
    return WORK / f"short_rth_schedule_{year}.parquet"


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()
