"""Dataset V2 builder on a synthetic raw year: native rows only, no fill, correct reference tables,
immutable output, V0 paths refused, and the catalog readable back through NautilusTrader."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_workflow import dataset_v2 as dv2

NS = 1_000_000_000
ROOT = Path(__file__).resolve().parents[2]


def _synthetic_raw(path: Path, symbol: str = "NQ") -> dict:
    """Four CME sessions around MLK day 2021: 01-14, 01-15, 01-18 (holiday session with a 12:00 CT early close), 01-19."""
    rng = np.random.default_rng(7)
    rows = []
    sessions = dv2.session_table(int(pd.Timestamp("2021-01-13 23:00", tz="UTC").value), int(pd.Timestamp("2021-01-19 22:00", tz="UTC").value))
    gap_plan = {}
    for i, (_, s) in enumerate(sessions.iterrows()):
        # January 2021 still carries the 15:15-15:30 CT halt: only in-window seconds are native
        secs = np.concatenate([np.arange(a, b, NS) for a, b in dv2.session_windows(s)])
        keep = rng.random(len(secs)) > 0.4                          # thin tape: ~40% missing seconds
        keep[:120] = True                                            # first two minutes dense
        keep[1000:1100] = False                                      # one deterministic 100 s gap
        gap_plan[str(s["session_date"])] = (int(secs[1000]), int(secs[1100]))
        for t in secs[keep]:
            rows.append((t, 4000 + i, 100.0 + rng.random(), 101.0, 99.0, 100.5, int(rng.integers(1, 50))))
    # one native row inside the daily close (16:30 CT on the first session): kept, listed as out_of_calendar
    ooc_ts = int(sessions.iloc[0]["close_ns"]) + 1800 * NS
    rows.append((ooc_ts, 4000, 100.0, 100.0, 100.0, 100.0, 1))
    rows.sort()
    df = pd.DataFrame(rows, columns=["ts_event", "instrument_id", "open", "high", "low", "close", "volume"])
    df["ts_event"] = pd.to_datetime(df["ts_event"], unit="ns", utc=True)
    df["symbol"] = f"{symbol}.v.0"
    df["rtype"] = np.uint8(32)
    df["publisher_id"] = np.uint16(1)
    df["instrument_id"] = df["instrument_id"].astype("uint32")
    df["volume"] = df["volume"].astype("uint64")
    df = df.set_index("ts_event")
    df.to_parquet(path)
    return {"sessions": sessions, "gap_plan": gap_plan, "rows": len(df), "ooc_ts": ooc_ts}


def test_builder_produces_native_only_catalog_with_reference_tables(tmp_path: Path):
    raw = tmp_path / "raw"; raw.mkdir()
    facts = _synthetic_raw(raw / "NQ_v0_1s_2021.parquet")
    m = dv2.build_dataset_v2(symbol="NQ", years=["2021"], raw_dir=raw, catalog_root=tmp_path / "catalog", repo_root=tmp_path, write_spec=False)
    cat = Path(m["catalog_path"])
    assert cat.name == "NQ_1S_V2" and (cat / "dataset_manifest.json").is_file() and (cat / "build_manifest.json").is_file()
    assert m["streams"]["1s"]["rows"] == facts["rows"]                       # native rows in, native rows out: nothing filled
    assert m["rules"]["forward_fill"] is False
    cov = m["coverage"]
    assert cov["sessions"] == 4 and cov["rolls"] == 3 and cov["out_of_calendar_rows"] == 1 and cov["holidays_in_range"] == 0 and cov["early_close_sessions"] == 1   # MLK day is an early-close session, not a closure
    gaps = pd.read_parquet(cat / "reference" / "gaps.parquet")
    for day, (g0, g1) in facts["gap_plan"].items():
        hit = gaps[(gaps["start_ns"] <= g0) & (gaps["end_ns"] >= g1)]
        assert len(hit) == 1, (day, g0, g1)
    sessions = pd.read_parquet(cat / "reference" / "sessions.parquet")
    assert list(sessions["session_date"].astype(str)) == ["2021-01-14", "2021-01-15", "2021-01-18", "2021-01-19"]
    assert list(sessions["early_close"]) == [False, False, True, False]
    assert (sessions["native_seconds"] <= sessions["expected_seconds"]).all() and (sessions["coverage"] < 1.0).all()
    hol = pd.read_parquet(cat / "reference" / "holidays.parquet")
    assert len(hol) == 0
    xmas = dv2.holiday_table(int(pd.Timestamp("2021-12-20", tz="UTC").value), int(pd.Timestamp("2021-12-28", tz="UTC").value), sessions)
    assert "2021-12-24" in set(xmas["date"].astype(str)) and not bool(xmas.set_index(xmas["date"].astype(str)).loc["2021-12-24", "session_exists"])
    maint = pd.read_parquet(cat / "reference" / "maintenance.parquet")
    assert set(maint["kind"]) >= {"daily_close", "early_close_extended", "weekend"} and (maint["end_ns"] > maint["start_ns"]).all()
    rolls = pd.read_parquet(cat / "reference" / "rolls.parquet")
    assert list(rolls["prev_instrument_id"]) == [4000, 4001, 4002] and list(rolls["next_instrument_id"]) == [4001, 4002, 4003]
    ooc = pd.read_parquet(cat / "reference" / "out_of_calendar.parquet")
    assert list(ooc["ts_ns"]) == [facts["ooc_ts"]]
    # the catalog reads back through NautilusTrader with the declared ts_init contract
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    bars = ParquetDataCatalog(str(cat)).bars(bar_types=[m["streams"]["1s"]["bar_type"]])
    assert len(bars) == facts["rows"] and all(b.ts_init - b.ts_event == NS for b in bars[:500])
    mins = ParquetDataCatalog(str(cat)).bars(bar_types=[m["streams"]["1m"]["bar_type"]])
    assert len(mins) == m["streams"]["1m"]["rows"] and all(b.ts_init - b.ts_event == 60 * NS for b in mins[:200])
    # immutable: a second build into the same id is refused, and the digest is deterministic
    with pytest.raises(dv2.DatasetV2Error, match="OUTPUT_EXISTS_IMMUTABLE"):
        dv2.build_dataset_v2(symbol="NQ", years=["2021"], raw_dir=raw, catalog_root=tmp_path / "catalog", repo_root=tmp_path, write_spec=False)
    m2 = dv2.build_dataset_v2(symbol="NQ", years=["2021"], raw_dir=raw, catalog_root=tmp_path / "catalog2", repo_root=tmp_path, write_spec=False)
    assert m2["logical_digest"] == m["logical_digest"] and m2["reference_digest"] == m["reference_digest"]


def test_builder_refuses_v0_paths_and_filled_inputs(tmp_path: Path):
    raw = tmp_path / "raw"; raw.mkdir()
    _synthetic_raw(raw / "NQ_v0_1s_2021.parquet")
    with pytest.raises(dv2.DatasetV2Error, match="V0_OVERWRITE_REFUSED"):
        dv2.build_dataset_v2(symbol="NQ", years=["2021"], raw_dir=raw, catalog_root=tmp_path / "data" / "catalog", repo_root=tmp_path, dataset_id="NQ_v0_2020_2026", write_spec=False)
    df = pd.read_parquet(raw / "NQ_v0_1s_2021.parquet")
    df["is_fill"] = False
    df.to_parquet(raw / "NQ_v0_1s_2022.parquet")
    with pytest.raises(dv2.DatasetV2Error, match="FILLED_INPUT_REJECTED"):
        dv2.load_raw_year(raw / "NQ_v0_1s_2022.parquet", "NQ")


def test_dataset_spec_binds_in_the_static_compiler(tmp_path: Path):
    raw = tmp_path / "raw"; raw.mkdir()
    _synthetic_raw(raw / "NQ_v0_1s_2021.parquet")
    (tmp_path / "research" / "datasets").mkdir(parents=True)
    m = dv2.build_dataset_v2(symbol="NQ", years=["2021"], raw_dir=raw, catalog_root=tmp_path / "catalog", repo_root=tmp_path, write_spec=True)
    spec_path = Path(m["spec_path"])
    assert spec_path.name == "NQ_1S_V2.yaml"
    from research_workflow.grammar import compile_study, load_spec
    study = load_spec(ROOT / "fixtures" / "parity" / "shape_a" / "study.yaml")
    study["streams"][0]["dataset"] = "NQ_1S_V2"
    out = compile_study(study, repo_root=ROOT, datasets_dir=spec_path.parent)
    assert out.ok, out.card()
    inst = out.plan.instruments["NQ"]
    assert inst["dataset_id"] == "NQ_1S_V2" and inst["dataset_digest"] == m["logical_digest"]
    streams = {s["key"]: s for s in out.plan.streams}
    assert streams["nq_1s"]["source"] == "external" and streams["nq_1m"]["source"] == "external"
    assert streams["nq_1m"]["bar_type"] == m["streams"]["1m"]["bar_type"]


# --- W-3 (adversarial pass 02): the reference_digest aggregate must bind over ALL manifest
# tables (matching the build-time formula), not silently disarm when a study declares only a
# subset of the catalog's reference tables.

def test_reference_digest_binds_even_when_declaring_a_strict_subset(tmp_path: Path):
    raw = tmp_path / "raw"; raw.mkdir()
    _synthetic_raw(raw / "NQ_v0_1s_2021.parquet")
    m = dv2.build_dataset_v2(symbol="NQ", years=["2021"], raw_dir=raw, catalog_root=tmp_path / "catalog", repo_root=tmp_path, write_spec=False)
    cat = Path(m["catalog_path"])
    manifest_path = cat / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["reference_tables"]) > {"sessions"}, "fixture must build more than one reference table"

    # (a) a strict-subset declaration with the correct aggregate digest still passes.
    tables = dv2.load_reference_tables(cat, ["sessions"], reference_digest=m["reference_digest"])
    assert "sessions" in tables

    # (b) an undeclared table's manifest-recorded sha256 is tampered -- the study only ever
    # reads "sessions", but the digest must still catch the corruption of a table it never
    # loads, because the DatasetSpec digest is defined over the WHOLE catalog build.
    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    other = next(n for n in tampered["reference_tables"] if n != "sessions")
    tampered["reference_tables"][other]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(dv2.DatasetV2Error, match="REFERENCE_DIGEST_MISMATCH"):
        dv2.load_reference_tables(cat, ["sessions"], reference_digest=m["reference_digest"])


def test_declared_table_not_in_manifest_rejected(tmp_path: Path):
    raw = tmp_path / "raw"; raw.mkdir()
    _synthetic_raw(raw / "NQ_v0_1s_2021.parquet")
    m = dv2.build_dataset_v2(symbol="NQ", years=["2021"], raw_dir=raw, catalog_root=tmp_path / "catalog", repo_root=tmp_path, write_spec=False)
    cat = Path(m["catalog_path"])
    with pytest.raises(dv2.DatasetV2Error, match="REFERENCE_TABLE_MISSING"):
        dv2.load_reference_tables(cat, ["sessions", "totally_made_up_table"], reference_digest=m["reference_digest"])


def test_missing_build_manifest_fails_closed(tmp_path: Path):
    cat = tmp_path / "empty_catalog"; cat.mkdir()
    with pytest.raises(dv2.DatasetV2Error, match="REFERENCE_TABLE_MISSING"):
        dv2.load_reference_tables(cat, ["sessions"], reference_digest="deadbeef" * 8)


def test_unparsable_build_manifest_fails_closed(tmp_path: Path):
    cat = tmp_path / "bad_catalog"; cat.mkdir()
    (cat / "build_manifest.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(dv2.DatasetV2Error, match="REFERENCE_TABLE_MISSING"):
        dv2.load_reference_tables(cat, ["sessions"], reference_digest="deadbeef" * 8)
