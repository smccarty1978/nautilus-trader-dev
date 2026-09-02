"""Dataset V2 builder: an immutable, native-only (never forward-filled) 1-second catalog with
calendar, holiday, early-close, maintenance, roll and gap reference tables.

    <catalog_root>/<SYM>_1S_V2/
        data/bar/<INSTRUMENT>-1-SECOND-LAST-EXTERNAL/<year>.parquet   native 1s rows only
        data/bar/<INSTRUMENT>-1-MINUTE-LAST-EXTERNAL/<year>.parquet   build-time aggregation of the SAME native
                                                                     seconds (closed=left, label=left; a minute
                                                                     exists iff >= 1 native second) -- see
                                                                     scripts/prove_bar_equivalence.py
        data/futures_contract/<INSTRUMENT>/...
        reference/{sessions,holidays,maintenance,rolls,gaps,out_of_calendar}.parquet
        build_manifest.json          sources (sha256, rows), rules, counts, reference-table digests
        dataset_manifest.json        research_workflow.roots logical digest over data/ (immutable identity)

5m is NOT materialized: it stays a runtime derivation from completed 1m bars (the equivalence proof
records why). V0 catalogs are never touched: the builder refuses any output path registered in
``backtests.nt_runtime.data_plan.PRODUCT_CATALOGS`` and refuses to write into an existing directory.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SECOND_NS = 1_000_000_000
MINUTE_NS = 60 * SECOND_NS
CHICAGO = "America/Chicago"
OLD_BREAK_END = date(2021, 6, 25)          # last session with the 15:15-15:30 CT halt (CME removed it 2021-06-28)
CALENDAR_NAME = "CME_Equity"
SCHEMA_VERSION = 2
RAW_COLUMNS = ["ts_event", "open", "high", "low", "close", "volume", "instrument_id", "symbol"]


class DatasetV2Error(RuntimeError):
    pass


@dataclass
class RawYear:
    year: str
    path: Path
    sha256: str
    rows: int
    first_ns: int
    last_ns: int
    instrument_ids: List[int] = field(default_factory=list)


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def raw_path(raw_dir: Path, symbol: str, year: str) -> Path:
    cands = [raw_dir / f"{symbol}_v0_1s_{year}.parquet", raw_dir / f"{symbol}_v0_1s_{year}_ytd.parquet"]
    for c in cands:
        if c.is_file():
            return c
    raise DatasetV2Error(f"RAW_YEAR_MISSING: {symbol} {year} (looked for {[c.name for c in cands]})")


def load_raw_year(path: Path, symbol: str) -> pd.DataFrame:
    """Native rows only. Refuses filled products, non-v0 symbols, unordered or duplicate seconds."""
    schema = pq.ParquetFile(path).schema_arrow
    if "is_fill" in schema.names:
        raise DatasetV2Error(f"FILLED_INPUT_REJECTED: {path} carries is_fill -- V2 is built from native raw years only")
    df = pd.read_parquet(path, columns=[c for c in RAW_COLUMNS if c != "ts_event"])
    if df.index.name != "ts_event":
        raise DatasetV2Error(f"RAW_INDEX_NOT_TS_EVENT: {path}")
    bad = sorted(set(df["symbol"].unique()) - {f"{symbol}.v.0"})
    if bad:
        raise DatasetV2Error(f"NON_V0_INPUT_REJECTED: {path} has {bad}")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    ts = df.index.asi8
    if len(ts) and (np.any(np.diff(ts) <= 0)):
        raise DatasetV2Error(f"RAW_NOT_STRICTLY_INCREASING: {path}")
    if len(ts) and np.any(ts % SECOND_NS):
        raise DatasetV2Error(f"RAW_NOT_SECOND_ALIGNED: {path}")
    return df.drop(columns=["symbol"])


# ---------------------------------------------------------------------------
# calendar tables
# ---------------------------------------------------------------------------

def session_table(first_ns: int, last_ns: int, calendar_name: str = CALENDAR_NAME) -> pd.DataFrame:
    """One row per trading session: open second, last valid close second (inclusive), early-close flag,
    and the pre-2021-06-28 halt window when the calendar declares one."""
    import pandas_market_calendars as mcal
    tz = ZoneInfo(CHICAGO)
    first_ct = pd.Timestamp(first_ns, tz="UTC").tz_convert(tz)
    last_ct = pd.Timestamp(last_ns, tz="UTC").tz_convert(tz)
    cal = mcal.get_calendar(calendar_name)
    sched = cal.schedule(start_date=(first_ct.date() - timedelta(days=2)).isoformat(), end_date=(last_ct.date() + timedelta(days=2)).isoformat(), market_times="all")
    rows = []
    for session_day, row in sched.iterrows():
        open_ns = int(row.market_open.value)
        close_ns = int(row.market_close.value)            # the declared close second is itself a valid bar second
        close_ct = row.market_close.tz_convert(tz)
        early = (close_ct.hour, close_ct.minute, close_ct.second) != (16, 0, 0)
        halt_start = halt_end = None
        if session_day.date() <= OLD_BREAK_END and "break_start" in sched.columns and pd.notna(row.break_start):
            bs, be = int(row.break_start.value), int(row.break_end.value)
            if open_ns < bs < be < close_ns:
                halt_start, halt_end = bs + SECOND_NS, be          # 15:15:00 is valid; halt is (15:15:00, 15:30:00)
        if open_ns % SECOND_NS or close_ns % SECOND_NS:
            raise DatasetV2Error("CALENDAR_TIMESTAMP_NOT_SECOND_ALIGNED")
        rows.append({"session_date": session_day.date(), "open_ns": open_ns, "close_ns": close_ns, "early_close": bool(early),
                     "halt_start_ns": halt_start, "halt_end_ns": halt_end})
    df = pd.DataFrame(rows)
    df = df[(df["close_ns"] >= first_ns) & (df["open_ns"] <= last_ns)].reset_index(drop=True)
    return df


def session_windows(sess: pd.Series) -> List[tuple[int, int]]:
    """Half-open [start, end) second windows in which native bars are expected for one session."""
    end = int(sess["close_ns"]) + SECOND_NS
    if sess["halt_start_ns"] is not None and not pd.isna(sess["halt_start_ns"]):
        return [(int(sess["open_ns"]), int(sess["halt_start_ns"])), (int(sess["halt_end_ns"]), end)]
    return [(int(sess["open_ns"]), end)]


def holiday_table(first_ns: int, last_ns: int, sessions: pd.DataFrame, calendar_name: str = CALENDAR_NAME) -> pd.DataFrame:
    import pandas_market_calendars as mcal
    cal = mcal.get_calendar(calendar_name)
    hol = pd.DatetimeIndex(cal.holidays().holidays)
    lo, hi = pd.Timestamp(first_ns, tz="UTC").date(), pd.Timestamp(last_ns, tz="UTC").date()
    hol = [h.date() for h in hol if lo <= h.date() <= hi]
    have = set(sessions["session_date"])
    return pd.DataFrame({"date": hol, "weekday": [h.weekday() for h in hol], "session_exists": [h in have for h in hol]})


def maintenance_table(sessions: pd.DataFrame) -> pd.DataFrame:
    """Closures between consecutive sessions (daily 16:00-17:00 CT, weekends, holidays) plus in-session halts."""
    rows = []
    s = sessions.sort_values("open_ns").reset_index(drop=True)
    for i in range(len(s)):
        r = s.iloc[i]
        if r["halt_start_ns"] is not None and not pd.isna(r["halt_start_ns"]):
            rows.append({"start_ns": int(r["halt_start_ns"]), "end_ns": int(r["halt_end_ns"]), "kind": "pre_2021_halt", "session_date": r["session_date"]})
        if i + 1 < len(s):
            nxt = s.iloc[i + 1]
            start, end = int(r["close_ns"]) + SECOND_NS, int(nxt["open_ns"])
            hours = (end - start) / SECOND_NS / 3600.0
            kind = "daily_close" if hours <= 1.0 + 1e-9 else ("early_close_extended" if r["early_close"] and hours < 30 else ("weekend" if hours < 80 else "holiday_or_extended"))
            rows.append({"start_ns": start, "end_ns": end, "kind": kind, "session_date": r["session_date"]})
    return pd.DataFrame(rows, columns=["start_ns", "end_ns", "kind", "session_date"])


def roll_table(ts: np.ndarray, instrument_ids: np.ndarray, sessions: pd.DataFrame) -> pd.DataFrame:
    """Contract rolls of the volume-continuous series: every change of the databento instrument_id."""
    if len(ts) == 0:
        return pd.DataFrame(columns=["ts_ns", "prev_instrument_id", "next_instrument_id", "session_date"])
    idx = np.flatnonzero(np.diff(instrument_ids) != 0) + 1
    dates = _session_date_for(ts[idx], sessions)
    return pd.DataFrame({"ts_ns": ts[idx], "prev_instrument_id": instrument_ids[idx - 1], "next_instrument_id": instrument_ids[idx], "session_date": dates})


def _session_date_for(ts: np.ndarray, sessions: pd.DataFrame) -> List[Optional[date]]:
    opens = sessions["open_ns"].to_numpy()
    closes = sessions["close_ns"].to_numpy()
    out: List[Optional[date]] = []
    for t in ts:
        i = int(np.searchsorted(opens, t, side="right")) - 1
        out.append(sessions["session_date"].iloc[i] if i >= 0 and t <= closes[i] else None)
    return out


def gap_tables(ts: np.ndarray, sessions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(gaps, out_of_calendar, per-session coverage). Gaps are run-length encoded missing native seconds
    inside expected windows; out_of_calendar lists native seconds outside every window (kept in the
    catalog -- native rows take precedence over the generic calendar, as the dense product documents)."""
    gaps, cover = [], []
    in_window = np.zeros(len(ts), dtype=bool)
    for _, sess in sessions.iterrows():
        expected = native = 0
        for start, end in session_windows(sess):
            lo, hi = np.searchsorted(ts, start, side="left"), np.searchsorted(ts, end, side="left")
            in_window[lo:hi] = True
            present = ts[lo:hi]
            n_exp = (end - start) // SECOND_NS
            expected += n_exp
            native += len(present)
            # runs of missing seconds: boundaries of the present set inside [start, end)
            edges = np.concatenate(([start - SECOND_NS], present, [end]))
            d = np.diff(edges)
            run_idx = np.flatnonzero(d > SECOND_NS)
            for k in run_idx:
                g0 = int(edges[k]) + SECOND_NS
                g1 = int(edges[k + 1])
                gaps.append({"start_ns": g0, "end_ns": g1, "seconds": (g1 - g0) // SECOND_NS, "session_date": sess["session_date"]})
        cover.append({"session_date": sess["session_date"], "expected_seconds": int(expected), "native_seconds": int(native),
                      "coverage": (native / expected) if expected else None})
    ooc = pd.DataFrame({"ts_ns": ts[~in_window]})
    return (pd.DataFrame(gaps, columns=["start_ns", "end_ns", "seconds", "session_date"]), ooc, pd.DataFrame(cover))


# ---------------------------------------------------------------------------
# aggregation (the ONE build-time derivation; proven against V0 and an independent implementation)
# ---------------------------------------------------------------------------

def aggregate_minutes(df_1s: pd.DataFrame) -> pd.DataFrame:
    """closed=left, label=left, a minute exists iff >= 1 native second (identical to the V0 materializer rule)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df_1s[list(agg)].resample("1min", label="left", closed="left").agg(agg).dropna()


def aggregate_minutes_independent(df_1s: pd.DataFrame) -> pd.DataFrame:
    """Second implementation via integer bucket keys (no pandas resample) for the equivalence proof."""
    ts = df_1s.index.asi8
    key = ts // MINUTE_NS * MINUTE_NS
    g = df_1s.groupby(key, sort=True)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(), "volume": g["volume"].sum()})
    out.index = pd.to_datetime(out.index, unit="ns", utc=True)
    out.index.name = "ts_event"
    return out


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def _instrument(symbol: str, venue: str, multiplier: str, price_increment: str, years: Sequence[str]):
    from nautilus_trader.model.instruments import FuturesContract
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    t = TestInstrumentProvider.future(symbol=symbol, underlying=symbol, venue=venue, exchange=venue)
    d = t.to_dict(t)
    y0, y1 = min(int(y[:4]) for y in years), max(int(y[:4]) for y in years)
    activation = pd.Timestamp(f"{y0}-01-01", tz="UTC")
    d["activation_ns"] = activation.value
    d["expiration_ns"] = pd.Timestamp(f"{y1 + 1}-01-01 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = activation.value
    d["multiplier"] = multiplier
    d["price_increment"] = price_increment
    d["price_precision"] = len(price_increment.split(".")[1]) if "." in price_increment else 0
    return FuturesContract.from_dict(d)


def _write_table(path: Path, df: pd.DataFrame) -> Dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="zstd")
    return {"path": path.name, "rows": int(len(df)), "sha256": _sha256(path)}


def product_facts(symbol: str) -> Dict[str, str]:
    from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS
    prod = PRODUCT_CATALOGS.get(symbol.upper())
    if not prod:
        raise DatasetV2Error(f"UNKNOWN_PRODUCT: {symbol}")
    return {"venue": prod["venue"], "instrument_id": prod["instrument_id"], "multiplier": prod["multiplier"], "price_increment": prod["price_increment"],
            "v0_catalog_rel_path": prod["catalog_rel_path"], "v0_dataset_id": prod["dataset_id"]}


def build_dataset_v2(*, symbol: str, years: Sequence[str], raw_dir: Path, catalog_root: Path, repo_root: Path,
                     dataset_id: Optional[str] = None, calendar_name: str = CALENDAR_NAME, write_spec: bool = True,
                     progress: Optional[Any] = None) -> Dict[str, Any]:
    from nautilus_trader.model.data import BarType
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.persistence.wranglers import BarDataWrangler
    from research_workflow.roots import write_dataset_manifest

    symbol = symbol.upper()
    dataset_id = dataset_id or f"{symbol}_1S_V2"
    facts = product_facts(symbol)
    out_dir = (Path(catalog_root) / dataset_id).resolve()
    for guard in (Path(repo_root) / facts["v0_catalog_rel_path"],):
        if out_dir == guard.resolve() or dataset_id == facts["v0_dataset_id"]:
            raise DatasetV2Error(f"V0_OVERWRITE_REFUSED: {out_dir}")
    if out_dir.exists():
        raise DatasetV2Error(f"OUTPUT_EXISTS_IMMUTABLE: {out_dir} (a V2 dataset is never rebuilt in place; choose a new dataset_id)")
    years = [str(y) for y in years]
    sources = [raw_path(Path(raw_dir), symbol, y) for y in years]

    log = progress or (lambda msg: None)
    out_dir.mkdir(parents=True)
    catalog = ParquetDataCatalog(str(out_dir))
    instrument = _instrument(symbol, facts["venue"], facts["multiplier"], facts["price_increment"], years)
    catalog.write_data([instrument])
    bt_1s = BarType.from_str(f"{instrument.id}-1-SECOND-LAST-EXTERNAL")
    bt_1m = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")

    raw_years: List[RawYear] = []
    all_ts: List[np.ndarray] = []
    all_ids: List[np.ndarray] = []
    stream_rows = {"1s": 0, "1m": 0}
    minute_check = {"years_compared": 0, "mismatching_minutes": 0}
    for year, path in zip(years, sources):
        log(f"load {path.name}")
        df = load_raw_year(path, symbol)
        raw_years.append(RawYear(year=year, path=path, sha256=_sha256(path), rows=int(len(df)), first_ns=int(df.index.asi8[0]), last_ns=int(df.index.asi8[-1]),
                                 instrument_ids=[int(v) for v in pd.unique(df["instrument_id"])]))
        all_ts.append(df.index.asi8.copy())
        all_ids.append(df["instrument_id"].to_numpy().copy())
        ohlcv = df[["open", "high", "low", "close", "volume"]]
        log(f"write 1s {year}")
        bars = BarDataWrangler(bar_type=bt_1s, instrument=instrument).process(ohlcv, ts_init_delta=SECOND_NS)
        catalog.write_data(bars)
        stream_rows["1s"] += len(bars)
        del bars
        m = aggregate_minutes(ohlcv)
        m2 = aggregate_minutes_independent(ohlcv)
        if not (len(m) == len(m2) and (m.index.asi8 == m2.index.asi8).all() and np.allclose(m.to_numpy(dtype=float), m2.to_numpy(dtype=float), rtol=0, atol=0)):
            raise DatasetV2Error(f"MINUTE_AGGREGATION_IMPLEMENTATIONS_DISAGREE: {year}")
        minute_check["years_compared"] += 1
        log(f"write 1m {year}")
        bars = BarDataWrangler(bar_type=bt_1m, instrument=instrument).process(m, ts_init_delta=MINUTE_NS)
        catalog.write_data(bars)
        stream_rows["1m"] += len(bars)
        del bars, df, ohlcv, m, m2

    ts = np.concatenate(all_ts)
    ids = np.concatenate(all_ids)
    if np.any(np.diff(ts) <= 0):
        raise DatasetV2Error("CROSS_YEAR_ORDER_VIOLATION")
    log("reference tables")
    sessions = session_table(int(ts[0]), int(ts[-1]), calendar_name)
    gaps, ooc, cover = gap_tables(ts, sessions)
    sessions = sessions.merge(cover, on="session_date", how="left")
    tables = {"sessions": sessions, "holidays": holiday_table(int(ts[0]), int(ts[-1]), sessions, calendar_name), "maintenance": maintenance_table(sessions),
              "rolls": roll_table(ts, ids, sessions), "gaps": gaps, "out_of_calendar": ooc}
    ref_dir = out_dir / "reference"
    ref_manifest = {name: _write_table(ref_dir / f"{name}.parquet", df) for name, df in tables.items()}
    reference_digest = hashlib.sha256(json.dumps({k: v["sha256"] for k, v in ref_manifest.items()}, sort_keys=True).encode()).hexdigest()

    builder_sha = _sha256(Path(__file__))
    manifest = {
        "schema_version": SCHEMA_VERSION, "dataset_id": dataset_id, "symbol": symbol, "instrument_id": str(instrument.id), "years": years,
        "rules": {"forward_fill": False, "native_rows_only": True, "out_of_calendar_native_rows": "kept (native precedence), listed in reference/out_of_calendar.parquet",
                  "1m": "build-time aggregation of the native 1s rows: closed=left, label=left, minute exists iff >= 1 native second; verified against an independent integer-bucket implementation per year",
                  "5m": "not materialized -- runtime derivation from completed 1m bars", "calendar": {"name": calendar_name, "timezone": CHICAGO,
                  "package_version": importlib.metadata.version("pandas_market_calendars"), "close_second_inclusive": True, "pre_2021_halt_last_session": OLD_BREAK_END.isoformat()}},
        "sources": [{"year": r.year, "path": str(r.path), "sha256": r.sha256, "rows": r.rows, "first_ns": r.first_ns, "last_ns": r.last_ns, "instrument_ids": r.instrument_ids} for r in raw_years],
        "streams": {"1s": {"bar_type": str(bt_1s), "rows": stream_rows["1s"], "ts_init_delta_ns": SECOND_NS, "source": "external"},
                    "1m": {"bar_type": str(bt_1m), "rows": stream_rows["1m"], "ts_init_delta_ns": MINUTE_NS, "source": "external", "derivation": "build_time_from_native_1s"}},
        "minute_aggregation_cross_check": minute_check,
        "coverage": {"first_ns": int(ts[0]), "last_ns": int(ts[-1]), "native_rows": int(len(ts)), "sessions": int(len(sessions)),
                     "expected_seconds": int(sessions["expected_seconds"].sum()), "native_in_window_seconds": int(sessions["native_seconds"].sum()),
                     "gap_runs": int(len(gaps)), "gap_seconds": int(gaps["seconds"].sum()) if len(gaps) else 0, "max_gap_seconds": int(gaps["seconds"].max()) if len(gaps) else 0,
                     "out_of_calendar_rows": int(len(ooc)), "rolls": int(len(tables["rolls"])), "early_close_sessions": int(sessions["early_close"].sum()),
                     "holidays_in_range": int(len(tables["holidays"]))},
        "reference_tables": ref_manifest, "reference_digest": reference_digest, "builder": {"module": "research_workflow.dataset_v2", "sha256": builder_sha},
        "built_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    (out_dir / "build_manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    ds_manifest = write_dataset_manifest(out_dir, dataset_id, str(instrument.id))
    manifest["logical_digest"] = ds_manifest["logical_digest"]
    manifest["catalog_path"] = str(out_dir)
    if write_spec:
        manifest["spec_path"] = str(write_dataset_spec(Path(repo_root), manifest, facts))
    return manifest


def write_dataset_spec(repo_root: Path, manifest: Dict[str, Any], facts: Dict[str, str]) -> Path:
    import yaml
    inst = manifest["instrument_id"]
    first = pd.Timestamp(manifest["coverage"]["first_ns"], tz="UTC")
    last = pd.Timestamp(manifest["coverage"]["last_ns"], tz="UTC")
    spec = {
        "dataset_id": manifest["dataset_id"], "instrument_id": inst, "schema_version": SCHEMA_VERSION,
        "catalog_rel_path": None,
        "logical_digest": manifest["logical_digest"], "digest_method": "sha256(sorted(relpath,size,sha256(bytes)) under <catalog>/data)",
        "reference_digest": manifest["reference_digest"],
        "provenance": {"source": "databento *.v.0 raw yearly parquet (native rows, no fill)", "build_manifest": "build_manifest.json",
                       "builder_sha256": manifest["builder"]["sha256"], "sources": [{"year": s["year"], "sha256": s["sha256"], "rows": s["rows"]} for s in manifest["sources"]]},
        "rules": {"forward_fill": False, "native_rows_only": True},
        "instrument": {"instrument_id": inst, "venue": facts["venue"], "multiplier": facts["multiplier"], "price_increment": facts["price_increment"]},
        "streams": {
            "1s": {"source": "external", "bar_type": manifest["streams"]["1s"]["bar_type"], "source_timestamp_semantics": "interval_open", "availability_rule": "interval_end", "ts_init_delta_ns": SECOND_NS},
            "1m": {"source": "external", "bar_type": manifest["streams"]["1m"]["bar_type"], "source_timestamp_semantics": "interval_open", "availability_rule": "interval_end", "ts_init_delta_ns": MINUTE_NS,
                   "derivation": "build_time_from_native_1s(closed=left,label=left,minute_exists_iff_native_second)", "equivalence_proof": "artifacts/platform_v2_do_soon/dataset_v2/equivalence_<SYMBOL>.json"},
            "5m": {"source": "derived", "external_catalog_stream": False, "derived_from": "1m", "aggregator": "runtime_complete_calendar_bucket"},
        },
        "reference_tables": sorted(manifest["reference_tables"]),
        "coverage": {"start": first.isoformat(), "end": last.isoformat(), "years": manifest["years"]},
    }
    path = repo_root / "research" / "datasets" / f"{manifest['dataset_id']}.yaml"
    header = ("# DatasetSpec authority for the immutable %s catalog (Dataset V2).\n# Built by research_workflow.dataset_v2 -- native 1s rows only, never forward-filled; 1m is a build-time\n"
              "# aggregation of the same seconds; 5m stays a runtime derivation. Reference tables live under <catalog>/reference/.\n" % manifest["dataset_id"])
    path.write_text(header + yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path
