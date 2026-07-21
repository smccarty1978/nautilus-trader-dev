"""Shared paths, constants and helpers for the Fable 5 pre-flip D10 study."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
AUDIT = STUDY / "audit"
WORK = STUDY / "_work"

UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context"
UPSTREAM_RESULTS = UPSTREAM / "results"
ATLAS_PATH = UPSTREAM_RESULTS / "weakness_checkpoint_atlas.parquet"
MANIFEST_PATH = UPSTREAM_RESULTS / "weakness_model_manifest.json"

RAW_1S = {
    2025: ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet",
    2026: ROOT / "data" / "raw" / "NQ_v0_1s_2026_ytd.parquet",
}
CATALOG_PATH = ROOT / "data" / "catalog" / "NQ_v0_2020_2026"

NS_PER_S = 1_000_000_000
NQ_MULT = 20.0
TICK = 0.25
COMM_RT = 5.0          # $ round-trip commission (project standard)
SLIP_RT = 5.0          # 1 NQ tick round-trip slippage allowance
COST_RT = COMM_RT + SLIP_RT

STOP_GRID = (0.50, 1.00, 1.50)
CHECKPOINT_STEP_S = 5          # 2025/2026 atlas cadence
MAX_CHECKPOINT_AGE_S = 1800    # atlas scoring cap

# Economics windows (UTC, inclusive start / exclusive end)
ECON_WINDOWS = {
    2025: (pd.Timestamp("2025-03-01", tz="UTC"), pd.Timestamp("2025-12-31", tz="UTC")),
    2026: (pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-04-30", tz="UTC")),
}

EXIT_REASONS = (
    "stop_before_flip",
    "stop_after_flip",
    "d10_exit",
    "opposite_regime_flip_exit",
    "data_end_censored",
)

for _p in (RESULTS, AUDIT, WORK):
    _p.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def read_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def w4_feature_list() -> list[str]:
    m = read_manifest()
    assert m["best_spec"] == "W4", f"upstream best spec changed: {m['best_spec']}"
    return list(m["features"])


def load_frozen_threshold() -> dict:
    return json.loads((WORK / "frozen_threshold.json").read_text(encoding="utf-8"))


def is_rth(ts_ns: np.ndarray | int) -> np.ndarray | bool:
    """RTH = 08:30-15:00 America/Chicago (display/segmentation only)."""
    ts = pd.to_datetime(ts_ns, unit="ns", utc=True)
    if isinstance(ts, pd.Timestamp):
        ct = ts.tz_convert("America/Chicago")
        mins = ct.hour * 60 + ct.minute
        return 8 * 60 + 30 <= mins < 15 * 60
    ct = pd.DatetimeIndex(ts).tz_convert("America/Chicago")
    mins = np.asarray(ct.hour) * 60 + np.asarray(ct.minute)
    return (mins >= 8 * 60 + 30) & (mins < 15 * 60)


def net_pnl_usd(pnl_pts: np.ndarray | float) -> np.ndarray | float:
    """Gross points -> net USD for 1 contract with project-standard costs."""
    return np.asarray(pnl_pts, dtype=float) * NQ_MULT - COST_RT
