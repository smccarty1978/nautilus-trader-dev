"""Timestamp and Bar-Availability Contract Engine.
================================================
Measures and validates empirical Databento -> NautilusTrader timestamp contracts
from actual catalog parquet data files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


class CatalogTimestampSemanticError(RuntimeError):
    """Raised when measured catalog timestamp semantics violate causal contracts."""
    pass


EXPECTED_TIMEFRAME_DELTAS_NS = {
    "1-SECOND": 1_000_000_000,
    "1-MINUTE": 60_000_000_000,
    "3-MINUTE": 180_000_000_000,
    "5-MINUTE": 300_000_000_000,
}


def measure_catalog_bar_semantics(
    catalog_path: Path,
    sample_rows: int = 1000,
) -> Dict[str, Any]:
    """Empirically samples catalog parquet files and verifies ts_init - ts_event == bar_duration_ns."""
    bar_dir = catalog_path / "data" / "bar" if (catalog_path / "data" / "bar").exists() else catalog_path
    if not bar_dir.exists():
        # Fallback to searching data/catalog
        cand_dirs = list(Path("data/catalog").glob(f"*{catalog_path.name}*/data/bar"))
        if cand_dirs:
            bar_dir = cand_dirs[0]

    measurements: Dict[str, Any] = {}

    if not bar_dir.exists():
        return {
            "status": "UNMEASURED_CATALOG_NOT_FOUND",
            "catalog_path": str(catalog_path),
            "measurements": {},
        }

    for type_dir in sorted(bar_dir.iterdir()):
        if not type_dir.is_dir():
            continue
        parquet_files = list(type_dir.glob("*.parquet"))
        if not parquet_files:
            continue

        sample_file = parquet_files[0]
        try:
            df = pd.read_parquet(sample_file, columns=["ts_event", "ts_init"])
            if len(df) > sample_rows:
                df = df.head(sample_rows)
            deltas = (df["ts_init"] - df["ts_event"]).unique().tolist()

            # Determine expected delta from directory name
            expected_delta = None
            for tf_key, exp_d in EXPECTED_TIMEFRAME_DELTAS_NS.items():
                if tf_key in type_dir.name.upper():
                    expected_delta = exp_d
                    break

            is_valid = (expected_delta is not None) and (deltas == [expected_delta])
            measurements[type_dir.name] = {
                "sample_count": len(df),
                "expected_delta_ns": expected_delta,
                "observed_deltas_ns": deltas,
                "pass": is_valid,
            }
            if not is_valid and expected_delta is not None:
                raise CatalogTimestampSemanticError(
                    f"CATALOG_TIMESTAMP_VIOLATION: {type_dir.name} observed deltas {deltas} != expected {expected_delta}"
                )
        except Exception as exc:
            if isinstance(exc, CatalogTimestampSemanticError):
                raise
            measurements[type_dir.name] = {"error": str(exc), "pass": False}

    return {
        "status": "MEASURED",
        "catalog_path": str(catalog_path),
        "measurements": measurements,
    }


def compile_timestamp_contract(
    instrument_symbol: str = "NQ",
    catalog_path: str = "data/catalog/NQ_v0_2020_2026",
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compiles the authoritative timestamp and availability contract backed by empirical measurements."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    cat_p = (repo_root / catalog_path).resolve()
    measurements = measure_catalog_bar_semantics(cat_p)

    contract = {
        "source": "databento_glbx_mdp3",
        "raw_timestamp_semantic": "OPEN_STAMPED",
        "raw_index_field": "ts_event",
        "timezone": "UTC",
        "offline_research_aggregation": {
            "pandas_rule": "resample(rule, label='right', closed='left')",
            "semantic": "CLOSE_STAMPED",
        },
        "nautilus_catalog": {
            "ts_event_semantic": "OPEN_STAMPED",
            "ts_init_semantic": "CLOSE_STAMPED",
            "causal_dispatch_field": "ts_init",
            "availability_invariant": "if nt_ts_event_semantic == 'OPEN_STAMPED': ts_init - ts_event == bar_duration_ns",
            "timeframe_deltas_ns": EXPECTED_TIMEFRAME_DELTAS_NS,
            "empirical_measurement": measurements,
        },
        "causal_rule": "FULL_BAR_OHLCV_AVAILABLE_ONLY_AT_INTERVAL_CLOSE",
    }
    return contract
