"""Scoped dataset byte verification (chore readiness_scoped_dataset_bytes).

A real NautilusTrader catalog (synthetic years 2029-2031, written by ``ParquetDataCatalog.write_data`` so
file names, intervals and footers are genuine) proves that readiness / launch verification hashes exactly
the files a ``[warmup_start, run_end]`` bar query opens, never a file outside that window, and that the
logical dataset identity is unchanged.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from research_workflow import roots
from research_workflow.roots import (DatasetDigestMismatch, DatasetFilesDrifted, DatasetScopeRefused, bar_file_interval,
                                     compute_catalog_digest, utc_year_interval_ns, verify_dataset_bytes, verify_dataset_scope,
                                     write_dataset_manifest)

YEARS = (2029, 2030, 2031)
BT_1S = "ESZ9.XCME-1-SECOND-LAST-EXTERNAL"
BT_1M = "ESZ9.XCME-1-MINUTE-LAST-EXTERNAL"


def _write_year(catalog, instrument, bar_type: str, year: int, step: str) -> None:
    from nautilus_trader.model.data import BarType
    from nautilus_trader.persistence.wranglers import BarDataWrangler
    idx = pd.date_range(f"{year}-01-01 23:00", periods=5, freq=step, tz="UTC")   # Globex reopens New Year's evening
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0}, index=idx)
    bars = BarDataWrangler(bar_type=BarType.from_str(bar_type), instrument=instrument).process(df)
    catalog.write_data(bars)


@pytest.fixture
def cat(tmp_path: Path):
    """One file per year per bar type, exactly the Dataset V2 builder's layout; manifest + digest written."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    path = tmp_path / "DS"
    catalog = ParquetDataCatalog(str(path))
    instrument = TestInstrumentProvider.es_future(2019, 12)
    for y in YEARS:
        _write_year(catalog, instrument, BT_1S, y, "1s")
        _write_year(catalog, instrument, BT_1M, y, "1min")
    m = write_dataset_manifest(path, "DS", "ESZ9.XCME")
    return SimpleNamespace(path=path, digest=m["logical_digest"], manifest=m, catalog=catalog)


def _files_of(cat, year: int):
    a, b = utc_year_interval_ns(year)
    return [e["path"] for e in cat.manifest["files"] if (iv := bar_file_interval(e["path"])) and a <= iv[0] <= b]


def _ns(ts: str) -> int:
    return int(pd.Timestamp(ts, tz="UTC").value)


def _window(start: str, end: str, warmup_days: int = 0):
    """The window a launch hands the engine (resolve_dataset_plan's start/end/warmup arithmetic)."""
    s = pd.Timestamp(f"{start} 00:00:00", tz="UTC") - pd.Timedelta(days=warmup_days)
    return int(s.value), int(pd.Timestamp(f"{end} 23:59:59.999999999", tz="UTC").value)


@pytest.fixture
def opened(monkeypatch):
    """Every path whose bytes or footer the verifier reads."""
    seen: list[str] = []
    real_sha, real_footer = roots._sha256_file, roots._footer_ts_init
    monkeypatch.setattr(roots, "_sha256_file", lambda p: (seen.append(Path(p).as_posix()), real_sha(p))[1])
    monkeypatch.setattr(roots, "_footer_ts_init", lambda p: (seen.append(Path(p).as_posix()), real_footer(p))[1])
    return seen


def test_layout_is_one_interval_named_file_per_year_per_bar_type(cat):
    bar_files = [e["path"] for e in cat.manifest["files"] if e["path"].startswith("data/bar/")]
    assert len(bar_files) == 6 and all(bar_file_interval(p) for p in bar_files)
    assert all(len(_files_of(cat, y)) == 2 for y in YEARS)


def test_authorized_files_are_verified_and_future_year_files_are_never_opened(cat, opened):
    rec = verify_dataset_scope(cat.path, cat.digest, windows=[_window("2030-01-01", "2030-12-31")], bar_types=[BT_1S, BT_1M])
    assert rec["status"] == "VERIFIED_SCOPED" and rec["logical_digest"] == cat.digest
    assert sorted(f["path"] for f in rec["files"] if f["interval_ns"]) == sorted(_files_of(cat, 2030))
    assert not any(p.endswith(tuple(_files_of(cat, 2031))) or p.endswith(tuple(_files_of(cat, 2029))) for p in opened), opened
    assert rec["out_of_scope_file_count"] == 4 and rec["scoped_digest"] and rec["covered_intervals_ns"].keys() == {BT_1S, BT_1M}


def test_warmup_crossing_the_year_boundary_includes_the_prior_year_file(cat):
    rec = verify_dataset_scope(cat.path, cat.digest, windows=[_window("2030-01-01", "2030-12-31", warmup_days=5)], bar_types=[BT_1S, BT_1M])
    # the 2029 files end on 2029-01-01 23:04, so a 5-day warmup into late December 2029 does NOT reach them ...
    assert sorted(f["path"] for f in rec["files"] if f["interval_ns"]) == sorted(_files_of(cat, 2030))
    # ... while a warmup that reaches back over the 2029 bars does
    rec = verify_dataset_scope(cat.path, cat.digest, windows=[_window("2030-01-01", "2030-12-31", warmup_days=370)], bar_types=[BT_1S, BT_1M])
    assert sorted(f["path"] for f in rec["files"] if f["interval_ns"]) == sorted(_files_of(cat, 2029) + _files_of(cat, 2030))


def test_interval_boundaries_are_closed_like_nautilus_trader(cat):
    p = _files_of(cat, 2031)[0]
    a, b = bar_file_interval(p)
    hit = lambda w: p in {f["path"] for f in verify_dataset_scope(cat.path, cat.digest, windows=[w])["files"]}
    assert hit((a, a)) and hit((b, b)) and hit((a - 10, a)) and hit((b, b + 10))
    assert not hit((a - 10, a - 1)) and not hit((b + 1, b + 10))


def test_scope_selection_equals_nautilus_trader_query_selection(cat):
    from nautilus_trader.persistence.catalog.parquet import _query_intersects_filename
    rng = random.Random(7)
    lo, hi = _ns("2028-12-01"), _ns("2032-02-01")
    bar = [e["path"] for e in cat.manifest["files"] if e["path"].startswith("data/bar/")]
    for _ in range(300):
        a, b = sorted(rng.randint(lo, hi) for _ in range(2))
        ours = {f["path"] for f in verify_dataset_scope(cat.path, cat.digest, windows=[(a, b)])["files"] if f["path"] in bar}
        nt = {q for q in bar if _query_intersects_filename(q, pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC"))}
        assert ours == nt


def test_the_engine_loader_reads_only_bars_from_the_scoped_files(cat):
    from utils.runner.data import CausalDataLoader
    start, end = (pd.Timestamp(v, tz="UTC") for v in ("2030-01-01", "2030-12-31 23:59:59.999999999"))
    rec = verify_dataset_scope(cat.path, cat.digest, windows=[(int(start.value), int(end.value))], bar_types=[BT_1S, BT_1M])
    covered = rec["covered_intervals_ns"]
    for bt in (BT_1S, BT_1M):
        bars = CausalDataLoader(cat.path).load_bars(bar_type=bt, start=start, end=end)
        assert bars and all(any(a <= b.ts_init <= z for a, z in covered[bt]) for b in bars)


def test_forbidden_year_file_inside_the_window_refuses_before_any_byte_is_read(cat, opened):
    with pytest.raises(DatasetScopeRefused, match="DATASET_SCOPE_UNAUTHORIZED_FILE"):
        verify_dataset_scope(cat.path, cat.digest, windows=[_window("2030-01-01", "2031-01-05")], bar_types=[BT_1S, BT_1M],
                             forbidden=[utc_year_interval_ns(2031)])
    assert opened == []
    # the same forbidden year outside the window is irrelevant
    rec = verify_dataset_scope(cat.path, cat.digest, windows=[_window("2030-01-01", "2030-12-31")], forbidden=[utc_year_interval_ns(2031)])
    assert rec["status"] == "VERIFIED_SCOPED"


def test_tampering_an_authorized_file_is_detected(cat):
    f = cat.path / _files_of(cat, 2030)[0]
    raw = bytearray(f.read_bytes()); raw[len(raw) // 2] ^= 0xFF; f.write_bytes(bytes(raw))   # same size
    with pytest.raises(DatasetDigestMismatch, match="scoped verification"):
        verify_dataset_scope(cat.path, cat.digest, windows=[_window("2030-01-01", "2030-12-31")])


def test_tampering_an_out_of_scope_file_is_left_to_the_run_that_reads_it(cat):
    f = cat.path / _files_of(cat, 2031)[0]
    raw = bytearray(f.read_bytes()); raw[len(raw) // 2] ^= 0xFF; f.write_bytes(bytes(raw))
    assert verify_dataset_scope(cat.path, cat.digest, windows=[_window("2030-01-01", "2030-12-31")])["status"] == "VERIFIED_SCOPED"
    with pytest.raises(DatasetDigestMismatch):
        verify_dataset_scope(cat.path, cat.digest, windows=[_window("2031-01-01", "2031-12-31")])
    with pytest.raises(DatasetDigestMismatch):       # the explicit whole-dataset audit still sees it
        verify_dataset_bytes(cat.path, cat.digest)


@pytest.mark.parametrize("year", [2030, 2031])
def test_missing_extra_or_resized_files_refuse_wherever_they_are(cat, year):
    w = [_window("2030-01-01", "2030-12-31")]
    f = cat.path / _files_of(cat, year)[0]
    keep = f.read_bytes()
    f.unlink()
    with pytest.raises(DatasetFilesDrifted, match="missing"):
        verify_dataset_scope(cat.path, cat.digest, windows=w)
    f.write_bytes(keep + b"x")
    with pytest.raises(DatasetFilesDrifted, match="size"):
        verify_dataset_scope(cat.path, cat.digest, windows=w)
    f.write_bytes(keep)
    (f.parent / "2030-06-01T00-00-00-000000000Z_2030-06-02T00-00-00-000000000Z.parquet").write_bytes(b"x")
    with pytest.raises(DatasetFilesDrifted, match="not in manifest"):
        verify_dataset_scope(cat.path, cat.digest, windows=w)


def _rewrite_manifest(cat, mutate) -> None:
    p = cat.path / "dataset_manifest.json"
    m = json.loads(p.read_text(encoding="utf-8")); mutate(m); p.write_text(json.dumps(m), encoding="utf-8")


@pytest.mark.parametrize("mutation", ["entry_sha", "declared_digest", "duplicate", "bad_path"])
def test_manifest_inconsistencies_are_refused(cat, mutation, opened):
    def mutate(m):
        if mutation == "entry_sha":
            m["files"][0]["sha256"] = "0" * 64
        elif mutation == "declared_digest":
            m["logical_digest"] = "f" * 64
        elif mutation == "duplicate":
            m["files"].append(dict(m["files"][0]))
        else:
            m["files"][0]["path"] = "../outside.parquet"
    _rewrite_manifest(cat, mutate)
    with pytest.raises(DatasetScopeRefused, match="DATASET_SCOPE_MANIFEST_INCONSISTENT"):
        verify_dataset_scope(cat.path, cat.digest, windows=[_window("2030-01-01", "2030-12-31")])
    assert opened == []


def test_a_file_whose_bars_lie_outside_its_filename_interval_is_refused(cat):
    f = cat.path / _files_of(cat, 2030)[0]
    a, b = bar_file_interval(f.name)
    from nautilus_trader.persistence.catalog.parquet import _timestamps_to_filename
    f.rename(f.parent / _timestamps_to_filename(a + 10**12, b + 10**12))   # claims a later interval than its bars
    m = write_dataset_manifest(cat.path, "DS", "ESZ9.XCME")
    with pytest.raises(DatasetScopeRefused, match="outside its filename interval"):
        verify_dataset_scope(cat.path, m["logical_digest"], windows=[_window("2030-01-01", "2030-12-31")])


def test_an_uninterval_bar_file_is_always_in_scope_and_refused_when_any_period_is_forbidden(cat):
    (cat.path / "data" / "bar" / BT_1S / "part-0.parquet").write_bytes(b"legacy")
    m = write_dataset_manifest(cat.path, "DS", "ESZ9.XCME")
    rec = verify_dataset_scope(cat.path, m["logical_digest"], windows=[_window("2030-01-01", "2030-12-31")])
    assert any(f["path"].endswith("part-0.parquet") for f in rec["files"])
    with pytest.raises(DatasetScopeRefused, match="carries no interval"):
        verify_dataset_scope(cat.path, m["logical_digest"], windows=[_window("2030-01-01", "2030-12-31")], forbidden=[utc_year_interval_ns(2031)])


def test_a_window_with_no_file_of_a_requested_bar_type_refuses(cat):
    with pytest.raises(DatasetScopeRefused, match="DATASET_SCOPE_NO_COVERAGE"):
        verify_dataset_scope(cat.path, cat.digest, windows=[_window("2032-01-01", "2032-12-31")], bar_types=[BT_1S])


def test_logical_identity_and_manifest_contract_are_unchanged(cat):
    assert compute_catalog_digest(cat.path)["logical_digest"] == cat.digest == cat.manifest["logical_digest"]
    assert roots._entries_digest(cat.manifest["files"]) == cat.digest
    assert verify_dataset_bytes(cat.path, cat.digest)["file_count"] == len(cat.manifest["files"])


def test_launch_verification_scopes_to_the_data_plan_window_and_refuses_prohibited_years(cat, opened):
    from backtests.nt_runtime.data_plan import WrongPhysicalDatasetError, verify_launch_dataset_bytes
    def dp(start, end, warmup=5):
        s = pd.Timestamp(f"{start} 00:00:00", tz="UTC")
        return SimpleNamespace(dataset_id="DS", dataset_logical_digest=cat.digest, catalog_path=cat.path, bar_type_1s=BT_1S, bar_type_1m=BT_1M,
                               warmup_start_dt=s - pd.Timedelta(days=warmup), end_dt=pd.Timestamp(f"{end} 23:59:59.999999999", tz="UTC"))
    out = verify_launch_dataset_bytes(dp("2030-01-01", "2030-12-31"), forbidden_years=[2031])
    assert out["status"] == "VERIFIED" and out["logical_digest"] == cat.digest and out["file_count"] == 2
    assert not any("2031-" in Path(p).name[:5] for p in opened)
    with pytest.raises(WrongPhysicalDatasetError, match="DATASET_SCOPE_UNAUTHORIZED_FILE"):
        verify_launch_dataset_bytes(dp("2030-01-01", "2031-01-03"), forbidden_years=[2031])


def _lifecycle_on(cat, chronology, monkeypatch, *, smoke_date=None):
    """A V2Lifecycle whose plan resolves to the synthetic catalog (launch_data_plan patched to the same
    window arithmetic as resolve_dataset_plan)."""
    from research_workflow import host_runner
    from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
    def fake_plan(plan, start_date, end_date, *, warmup_days, repo_root):
        s = pd.Timestamp(f"{start_date} 00:00:00", tz="UTC")
        return SimpleNamespace(dataset_id="DS", dataset_logical_digest=cat.digest, catalog_path=cat.path, bar_type_1s=BT_1S, bar_type_1m=BT_1M,
                               warmup_start_dt=s - pd.Timedelta(days=warmup_days), end_dt=pd.Timestamp(f"{end_date} 23:59:59.999999999", tz="UTC"))
    monkeypatch.setattr(host_runner, "launch_data_plan", fake_plan)
    lc = V2Lifecycle(cat.path.parent / "study", options=V2Options(smoke_date=smoke_date))
    plan = {"chronology": chronology, "outcome": {"arms": [{"horizon_ns": 3600 * 10**9}]}, "instruments": {}}
    return lc, plan


def test_readiness_scope_covers_train_partitions_and_smoke_but_not_held_out_years(cat, monkeypatch, opened):
    lc, plan = _lifecycle_on(cat, {"train": [2029, 2030], "dev": [], "prohibited": [2031]}, monkeypatch, smoke_date="2030-01-02")
    scope = lc._readiness_byte_scope(plan)
    assert sorted(f["path"] for f in scope["files"] if f["interval_ns"]) == sorted(_files_of(cat, 2029) + _files_of(cat, 2030))
    assert scope["forbidden_years"] == [2031] and not any(p.endswith(tuple(_files_of(cat, 2031))) for p in opened)


def test_readiness_refuses_when_a_train_partition_tail_would_open_the_held_out_year(cat, monkeypatch, opened):
    """_partition_bounds extends the last TRAIN year's run_end into the next year when that year is dev:
    that launch would stream the held-out year's first day. Readiness refuses instead of hashing it."""
    lc, plan = _lifecycle_on(cat, {"train": [2029, 2030], "dev": [2031], "prohibited": []}, monkeypatch)
    assert ("2030-01-01", "2031-01-01") in lc._readiness_launch_windows(plan)
    with pytest.raises(DatasetScopeRefused, match="DATASET_SCOPE_UNAUTHORIZED_FILE"):
        lc._readiness_byte_scope(plan)
    assert opened == [] and not any(p.endswith(tuple(_files_of(cat, 2031))) for p in opened)
