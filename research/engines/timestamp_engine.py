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


def resolve_catalog_for_symbol(instrument_symbol: str) -> str:
    """Resolves a product symbol to its catalog, using the runtime's own registry.

    ``PRODUCT_CATALOGS`` in ``backtests/nt_runtime/data_plan.py`` is what actually decides
    which catalog a run loads. Compiling the timestamp contract from a *different* source
    of truth is how an ES study came to carry NQ measurements: the previous signature
    accepted ``instrument_symbol`` and then ignored it, defaulting the catalog path to
    ``data/catalog/NQ_v0_2020_2026`` for every instrument.
    """
    from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS

    sym = (instrument_symbol or "").strip().upper()
    if sym not in PRODUCT_CATALOGS:
        raise CatalogTimestampSemanticError(
            f"UNSUPPORTED_INSTRUMENT: no catalog registered for {instrument_symbol!r}. "
            f"Known products: {sorted(PRODUCT_CATALOGS)}. A timestamp contract must be "
            f"measured on the instrument's own catalog, never on another product's."
        )
    return PRODUCT_CATALOGS[sym]["catalog_rel_path"]


def compile_timestamp_contract(
    instrument_symbol: str = "NQ",
    catalog_path: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compiles the authoritative timestamp and availability contract backed by empirical measurements.

    The catalog is resolved *from the instrument* unless one is passed explicitly.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    if catalog_path is None:
        catalog_path = resolve_catalog_for_symbol(instrument_symbol)

    cat_p = (repo_root / catalog_path).resolve()
    measurements = measure_catalog_bar_semantics(cat_p)

    # An instrument contract must carry its own instrument's evidence. Measuring the
    # right catalog is not enough if the measurement came back empty -- that would leave
    # the contract asserting a timestamp invariant nothing had checked.
    measured_types = [k for k in measurements.get("measurements", {})]
    sym = (instrument_symbol or "").strip().upper()
    foreign = [k for k in measured_types if not k.upper().startswith(f"{sym}.")]
    if foreign:
        raise CatalogTimestampSemanticError(
            f"FOREIGN_INSTRUMENT_EVIDENCE: timestamp contract for {sym} would record "
            f"measurements for {foreign}. Evidence must come from the study's own instrument."
        )
    if measurements.get("status") != "MEASURED" or not measured_types:
        raise CatalogTimestampSemanticError(
            f"TIMESTAMP_EVIDENCE_UNMEASURED: no bar-timestamp measurements could be taken for "
            f"{sym} at {cat_p} (status={measurements.get('status')}). A contract may not assert "
            f"an availability invariant it never measured."
        )

    contract = {
        "source": "databento_glbx_mdp3",
        "instrument_symbol": sym,
        "measured_catalog_rel_path": catalog_path,
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
