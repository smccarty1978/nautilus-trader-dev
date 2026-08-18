"""Generic raw-parquet -> NautilusTrader catalog materializer.
=================================================================
Builds a ``ParquetDataCatalog`` for any product registered in
:mod:`backtests.nt_runtime.data_plan`'s ``PRODUCT_CATALOGS`` from clean
``data/raw/{SYMBOL}_v0_1s_{year}.parquet`` sources. Replaces per-product
copies of the ES/NQ multi-year builder with one declarative builder driven
by the same product registry the runtime already resolves catalogs from.

``plan_materialization`` is side-effect free: it never reads raw parquet
rows or writes anything, only checks paths, so it is safe to call from
data-plan resolution or CLI dry-runs. ``build_catalog`` performs the actual
write and is only invoked after a plan reports ``MATERIALIZATION_REQUIRED``.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS

SUPPORTED_STREAMS = ("1s", "1m", "5m")

_STREAM_SUFFIX = {
    "1s": "1-SECOND-LAST-EXTERNAL",
    "1m": "1-MINUTE-LAST-EXTERNAL",
    "5m": "5-MINUTE-LAST-EXTERNAL",
}
_STREAM_RESAMPLE_RULE = {"1m": "1min", "5m": "5min"}
_STREAM_TS_INIT_DELTA_KEY = {
    "1s": "ts_init_delta_1s_ns",
    "1m": "ts_init_delta_1m_ns",
    "5m": None,  # ES/NQ builder hardcodes 5m at 300_000_000_000ns; no PRODUCT_CATALOGS key exists yet.
}
_5M_TS_INIT_DELTA_NS = 300_000_000_000


class MaterializationPlanError(ValueError):
    """Raised when a plan is requested for an unsupported product or stream."""


@dataclass(frozen=True)
class RawSourceStatus:
    year: str
    path: Path
    exists: bool


@dataclass(frozen=True)
class MaterializationPlan:
    status: str  # READY | MATERIALIZATION_REQUIRED | RAW_DATA_MISSING | UNSUPPORTED_PRODUCT
    product: str
    streams: List[str]
    years: List[str]
    catalog_path: Path
    raw_sources: List[RawSourceStatus] = field(default_factory=list)
    missing_streams: List[str] = field(default_factory=list)
    detail: str = ""


def _raw_path(repo_root: Path, symbol: str, year: str) -> Path:
    return repo_root / "data" / "raw" / f"{symbol}_v0_1s_{year}.parquet"


def _catalog_bar_dir(catalog_path: Path, instrument_id: str, stream: str) -> Path:
    suffix = _STREAM_SUFFIX[stream]
    return catalog_path / "data" / "bar" / f"{instrument_id}-{suffix}"


def plan_materialization(
    product: str,
    years: List[str],
    streams: List[str],
    repo_root: Optional[Path] = None,
) -> MaterializationPlan:
    """Side-effect-free assessment of what a materialization run would need.

    Never opens a raw parquet's rows and never writes to the catalog -- only
    checks path existence -- so callers (data-plan resolution, CLI dry-runs)
    can call this freely without triggering a build.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    unknown_streams = [s for s in streams if s not in SUPPORTED_STREAMS]
    if unknown_streams:
        raise MaterializationPlanError(
            f"UNSUPPORTED_STREAM: {unknown_streams}. Supported: {list(SUPPORTED_STREAMS)}"
        )

    sym = product.upper()
    if sym not in PRODUCT_CATALOGS:
        return MaterializationPlan(
            status="UNSUPPORTED_PRODUCT",
            product=sym,
            streams=list(streams),
            years=list(years),
            catalog_path=Path(),
            detail=f"'{sym}' is not registered in PRODUCT_CATALOGS. Known: {sorted(PRODUCT_CATALOGS)}",
        )

    prod = PRODUCT_CATALOGS[sym]
    catalog_path = (repo_root / prod["catalog_rel_path"]).resolve()

    raw_sources = [
        RawSourceStatus(year=yr, path=_raw_path(repo_root, sym, yr), exists=_raw_path(repo_root, sym, yr).exists())
        for yr in years
    ]
    missing_raw = [rs for rs in raw_sources if not rs.exists]
    if missing_raw:
        return MaterializationPlan(
            status="RAW_DATA_MISSING",
            product=sym,
            streams=list(streams),
            years=list(years),
            catalog_path=catalog_path,
            raw_sources=raw_sources,
            detail=f"Missing raw source(s): {[str(rs.path) for rs in missing_raw]}",
        )

    instrument_id = prod["instrument_id"]
    missing_streams = [
        s for s in streams
        if not _catalog_bar_dir(catalog_path, instrument_id, s).exists()
    ]
    if missing_streams:
        return MaterializationPlan(
            status="MATERIALIZATION_REQUIRED",
            product=sym,
            streams=list(streams),
            years=list(years),
            catalog_path=catalog_path,
            raw_sources=raw_sources,
            missing_streams=missing_streams,
            detail=f"Catalog missing stream(s): {missing_streams}",
        )

    return MaterializationPlan(
        status="READY",
        product=sym,
        streams=list(streams),
        years=list(years),
        catalog_path=catalog_path,
        raw_sources=raw_sources,
        detail="All requested streams already materialized.",
    )


def _sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_raw_1s(path: Path, symbol: str) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=["open", "high", "low", "close", "volume", "symbol", "instrument_id"])
    expected_symbol = f"{symbol}.v.0"
    bad_symbols = sorted(set(df["symbol"].unique()) - {expected_symbol})
    if bad_symbols:
        raise ValueError(
            f"NON_V0_INPUT_REJECTED: {path} contains symbol(s) {bad_symbols}, expected only "
            f"'{expected_symbol}'. Only *.v.0 (volume-continuous) raw data is authorized."
        )
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def _aggregate(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df[list(agg)].resample(rule, label="left", closed="left").agg(agg).dropna()


def build_catalog(
    product: str,
    years: List[str],
    streams: List[str],
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Materializes the requested streams into the product's registered catalog path.

    Writes the instrument once (idempotent overwrite) and each requested bar
    stream, then writes a ``materialization_manifest.json`` recording raw
    source provenance (path, sha256, row count) and per-stream output row
    counts for deterministic auditability.
    """
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.instruments import FuturesContract
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.persistence.wranglers import BarDataWrangler
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    plan = plan_materialization(product, years, streams, repo_root=repo_root)
    if plan.status == "UNSUPPORTED_PRODUCT":
        raise MaterializationPlanError(plan.detail)
    if plan.status == "RAW_DATA_MISSING":
        raise FileNotFoundError(plan.detail)

    sym = plan.product
    prod = PRODUCT_CATALOGS[sym]
    catalog_path = plan.catalog_path
    catalog_path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(catalog_path))

    t = TestInstrumentProvider.future(symbol=sym, underlying=sym, venue=prod["venue"], exchange=prod["venue"])
    d = t.to_dict(t)
    activation = pd.Timestamp(f"{min(int(y[:4]) for y in years)}-01-01", tz="UTC")
    d["activation_ns"] = activation.value
    d["expiration_ns"] = pd.Timestamp(f"{max(int(y[:4]) for y in years) + 1}-01-01 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = activation.value
    d["multiplier"] = prod["multiplier"]
    d["price_increment"] = prod["price_increment"]
    price_increment_str = str(prod["price_increment"])
    d["price_precision"] = len(price_increment_str.split(".")[1]) if "." in price_increment_str else 0
    instrument = FuturesContract.from_dict(d)
    catalog.write_data([instrument])

    raw_manifest: List[Dict[str, Any]] = []
    parts = []
    for rs in plan.raw_sources:
        df = _load_raw_1s(rs.path, sym)
        raw_manifest.append({
            "year": rs.year,
            "path": str(rs.path),
            "sha256": _sha256(rs.path),
            "row_count": len(df),
            "distinct_instrument_ids": int(df["instrument_id"].nunique()),
        })
        parts.append(df[["open", "high", "low", "close", "volume"]])

    df_full = pd.concat(parts).sort_index()
    df_full = df_full[~df_full.index.duplicated(keep="first")]

    stream_manifest: Dict[str, Any] = {}
    for stream in streams:
        bt = BarType.from_str(f"{instrument.id}-{_STREAM_SUFFIX[stream]}")
        wrangler = BarDataWrangler(bar_type=bt, instrument=instrument)
        if stream == "1s":
            ts_init_delta = prod[_STREAM_TS_INIT_DELTA_KEY["1s"]]
            bars = wrangler.process(df_full, ts_init_delta=ts_init_delta)
        else:
            ts_init_delta = (
                prod[_STREAM_TS_INIT_DELTA_KEY[stream]]
                if _STREAM_TS_INIT_DELTA_KEY[stream] is not None
                else _5M_TS_INIT_DELTA_NS
            )
            df_agg = _aggregate(df_full, _STREAM_RESAMPLE_RULE[stream])
            bars = wrangler.process(df_agg, ts_init_delta=ts_init_delta)
        catalog.write_data(bars)
        stream_manifest[stream] = {"row_count": len(bars), "ts_init_delta_ns": ts_init_delta}
        del bars

    manifest = {
        "product": sym,
        "venue": prod["venue"],
        "instrument_id": str(instrument.id),
        "multiplier": prod["multiplier"],
        "price_increment": prod["price_increment"],
        "years": list(years),
        "streams": stream_manifest,
        "raw_sources": raw_manifest,
        "built_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (catalog_path / "materialization_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
