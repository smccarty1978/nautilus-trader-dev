"""TRAIN / prohibited-year boundary: what a TRAIN-only partition reads, processes, emits and resolves.

Chronology contract under test (UTC calendar years, the platform's single convention):

* a role year Y is the UTC interval [Y-01-01T00:00Z, Y-12-31T23:59:59.999999999Z] (``primary_ns``);
* candidates are emitted only for checkpoints inside ``primary_ns`` (warmup and tail bars update
  state and resolve outcomes, never emit rows);
* the launch window is [primary_start 00:00Z - warmup_days, run_end 23:59:59.999999999Z], and
  ``run_end`` extends past Dec 31 ONLY when the next year is itself a train/dev year;
* a catalog file whose closed filename interval overlaps a prohibited year and the window refuses
  before a byte is read.

Four failure modes are kept apart: (1) opening a file with next-year timestamps, (2) processing
next-year bars, (3) emitting next-year candidates, (4) next-year information changing a year-Y row.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from research_workflow import roots
from research_workflow.roots import DatasetScopeRefused, utc_year_interval_ns, verify_dataset_scope, write_dataset_manifest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000
END_2029 = int(pd.Timestamp("2029-12-31 23:59:59.999999999", tz="UTC").value)


# ----------------------------------------------------------------- launch-window arithmetic
def _bounds(chronology, year, horizon_s=5400):
    from research_workflow.lifecycle_v2 import V2Lifecycle
    lc = V2Lifecycle.__new__(V2Lifecycle)
    plan = {"chronology": chronology, "outcome": {"arms": [{"horizon_ns": horizon_s * NS}]}}
    return lc._partition_bounds(plan, year, "train")


@pytest.mark.parametrize("chronology, run_end", [
    ({"train": [2021, 2022, 2023], "dev": [], "prohibited": [2024]}, "2023-12-31"),     # the price-action study
    ({"train": [2021, 2022, 2023], "dev": [2024], "prohibited": []}, "2024-01-01"),     # the frozen FPR study
    ({"train": [2023], "dev": [], "prohibited": []}, "2023-12-31"),
])
def test_run_end_extends_only_into_a_declared_role_year(chronology, run_end):
    b = _bounds(chronology, 2023)
    assert (b["primary_start"], b["primary_end"], b["run_end"]) == ("2023-01-01", "2023-12-31", run_end)
    assert b["primary_ns"] == (int(pd.Timestamp("2023-01-01", tz="UTC").value),
                               int(pd.Timestamp("2023-12-31 23:59:59.999999999", tz="UTC").value))
    assert _bounds(chronology, 2022)["run_end"] == "2023-01-01"     # inner years keep their outcome tail


# ------------------------------------------------------- real NautilusTrader catalog, Globex layout
BT_1S = "ESZ9.XCME-1-SECOND-LAST-EXTERNAL"
BT_1M = "ESZ9.XCME-1-MINUTE-LAST-EXTERNAL"


def _write(catalog, instrument, bar_type, index):
    from nautilus_trader.model.data import BarType
    from nautilus_trader.persistence.wranglers import BarDataWrangler
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0}, index=index)
    catalog.write_data(BarDataWrangler(bar_type=BarType.from_str(bar_type), instrument=instrument).process(df))


def _globex_catalog(path: Path, *, next_year_opens: str):
    """2028 warmup tail, 2029 sessions through the Dec 31 close (16:00 CT = 22:00 UTC), and a 2030 file
    starting at ``next_year_opens`` -- the CME New Year reopen (Jan 1 17:00 CT = 23:00 UTC) or, for the
    UTC/Chicago divergence case, a session opening Dec 31 17:00 CT (= 23:00 UTC, still UTC-2029)."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    catalog = ParquetDataCatalog(str(path))
    inst = TestInstrumentProvider.es_future(2019, 12)
    files = {
        2028: pd.date_range("2028-12-28 14:30", "2028-12-29 21:59", freq="1min", tz="UTC"),
        2029: pd.date_range("2029-12-31 14:30", "2029-12-31 22:00", freq="1min", tz="UTC"),
        2030: pd.date_range(next_year_opens, periods=90, freq="1min", tz="UTC"),
    }
    for idx in files.values():
        _write(catalog, inst, BT_1M, idx)
        _write(catalog, inst, BT_1S, pd.date_range(idx[0], idx[-1], freq="1s", tz="UTC"))
    m = write_dataset_manifest(path, "DS", "ESZ9.XCME")
    return SimpleNamespace(path=path, digest=m["logical_digest"], manifest=m, files=files)


def _built(opened, cat):
    opened.clear()          # building the manifest hashed every file; only reads after this point count
    return cat


def _launch_window(chronology, year=2029, warmup_days=5):
    b = _bounds(chronology, year)
    s = pd.Timestamp(f"{b['primary_start']} 00:00:00", tz="UTC") - pd.Timedelta(days=warmup_days)
    return int(s.value), int(pd.Timestamp(f"{b['run_end']} 23:59:59.999999999", tz="UTC").value)


@pytest.fixture
def opened(monkeypatch):
    seen: list = []
    real_sha, real_footer = roots._sha256_file, roots._footer_ts_init
    monkeypatch.setattr(roots, "_sha256_file", lambda p: (seen.append(Path(p).as_posix()), real_sha(p))[1])
    monkeypatch.setattr(roots, "_footer_ts_init", lambda p: (seen.append(Path(p).as_posix()), real_footer(p))[1])
    return seen


TRAIN_ONLY = {"train": [2029], "dev": [], "prohibited": [2030]}


def test_train_only_window_reads_every_year_bar_and_no_next_year_byte(tmp_path, opened):
    """Failure modes (1) and (2) on a real catalog: the 2030 file is never opened, the bars the engine
    loader returns stop at the Dec 31 close, and no 2029 bar (warmup included) is dropped."""
    from utils.runner.data import CausalDataLoader
    cat = _built(opened, _globex_catalog(tmp_path / "DS", next_year_opens="2030-01-01 23:00"))
    w = _launch_window(TRAIN_ONLY)
    assert pd.Timestamp(w[0], tz="UTC") == pd.Timestamp("2028-12-27", tz="UTC")       # warmup crosses the year
    rec = verify_dataset_scope(cat.path, cat.digest, windows=[w], bar_types=[BT_1S, BT_1M],
                               forbidden=[utc_year_interval_ns(2030)])
    years_in_scope = {pd.Timestamp(f["interval_ns"][0], tz="UTC").year for f in rec["files"] if f["interval_ns"]}
    assert years_in_scope == {2028, 2029}
    files_2030 = [e["path"] for e in cat.manifest["files"]
                  if (iv := roots.bar_file_interval(e["path"])) and pd.Timestamp(iv[0], tz="UTC").year == 2030]
    assert len(files_2030) == 2 and not any(p.endswith(tuple(files_2030)) for p in opened)
    assert rec["out_of_scope_file_count"] == 2                                          # the two 2030 bar files
    start, end = pd.Timestamp(w[0], tz="UTC"), pd.Timestamp(w[1], tz="UTC")
    for bt, step in ((BT_1M, "1min"), (BT_1S, "1s")):
        bars = CausalDataLoader(cat.path).load_bars(bar_type=bt, start=start, end=end)
        ts = [b.ts_init for b in bars]
        assert max(ts) <= w[1] and max(ts) < utc_year_interval_ns(2030)[0]
        expected = sum(len(idx) if step == "1min" else len(pd.date_range(idx[0], idx[-1], freq="1s"))
                       for y, idx in cat.files.items() if y in (2028, 2029))
        assert len(bars) == expected                                                    # nothing in-year dropped


def test_the_frozen_fpr_convention_streams_the_next_years_reopen_hour(tmp_path, opened):
    """The FPR chronology (dev: [2030]) extends run_end to Jan 1, so the same launch opens the 2030 file
    and streams its 23:00-23:59 UTC bars: failure modes (1) and (2), by the declared convention."""
    from utils.runner.data import CausalDataLoader
    cat = _globex_catalog(tmp_path / "DS", next_year_opens="2030-01-01 23:00")
    w = _launch_window({"train": [2029], "dev": [2030], "prohibited": []})
    rec = verify_dataset_scope(cat.path, cat.digest, windows=[w], bar_types=[BT_1S, BT_1M])
    assert any(pd.Timestamp(f["interval_ns"][0], tz="UTC").year == 2030 for f in rec["files"] if f["interval_ns"])
    bars = CausalDataLoader(cat.path).load_bars(bar_type=BT_1M, start=pd.Timestamp(w[0], tz="UTC"), end=pd.Timestamp(w[1], tz="UTC"))
    late = [b.ts_init for b in bars if b.ts_init >= utc_year_interval_ns(2030)[0]]
    assert late and min(late) == int(cat.files[2030][0].value)
    # ...and with 2030 prohibited instead, the identical tail is refused before any byte is read.
    opened.clear()
    with pytest.raises(DatasetScopeRefused, match="DATASET_SCOPE_UNAUTHORIZED_FILE"):
        verify_dataset_scope(cat.path, cat.digest, windows=[w], bar_types=[BT_1S, BT_1M], forbidden=[utc_year_interval_ns(2030)])
    assert opened == []


def test_a_next_year_session_opening_inside_utc_year_y_is_refused_not_silently_read(tmp_path, opened):
    """UTC/Chicago divergence: a session opening Dec 31 17:00 CT (23:00 UTC) belongs to the next
    trading date but to UTC year 2029. Filed with the next year, its file interval starts inside the
    TRAIN window AND overlaps the prohibited year -> refused before any byte is read."""
    cat = _built(opened, _globex_catalog(tmp_path / "DS", next_year_opens="2029-12-31 23:00"))
    with pytest.raises(DatasetScopeRefused, match="DATASET_SCOPE_UNAUTHORIZED_FILE"):
        verify_dataset_scope(cat.path, cat.digest, windows=[_launch_window(TRAIN_ONLY)], bar_types=[BT_1S, BT_1M],
                             forbidden=[utc_year_interval_ns(2030)])
    assert opened == []


def test_endpoints_are_closed_at_the_last_permitted_nanosecond(tmp_path):
    cat = _globex_catalog(tmp_path / "DS", next_year_opens="2030-01-01 23:00")
    first_2030 = int(cat.files[2030][0].value)
    for end, refuses in ((first_2030 - 1, False), (first_2030, True)):
        call = lambda: verify_dataset_scope(cat.path, cat.digest, windows=[(_launch_window(TRAIN_ONLY)[0], end)],
                                            bar_types=[BT_1S, BT_1M], forbidden=[utc_year_interval_ns(2030)])
        if refuses:
            with pytest.raises(DatasetScopeRefused, match="DATASET_SCOPE_UNAUTHORIZED_FILE"):
                call()
        else:
            call()


# ------------------------------------------------------ the host itself, golden fixture (2029 | 2030)
def _golden():
    import subprocess
    import sys
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    return bars, json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden():
    return _golden()


def _run_2029(tmp_path, golden, chronology, name):
    """One governed TRAIN-2029 partition through the real lifecycle + host. The bar source returns
    exactly what the catalog loader returns for the launch window (ts_init in [warmup_start, end])
    and records every window and every bar it handed the host."""
    from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    bars, expected = golden
    body = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = name
    body["chronology"] = chronology
    study = tmp_path / "studies" / name
    study.mkdir(parents=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    seen = {"windows": [], "max_ts": None}

    def source(start, end):
        lo = int((pd.Timestamp(f"{start} 00:00:00", tz="UTC") - pd.Timedelta(days=5)).value)
        hi = int(pd.Timestamp(f"{end} 23:59:59.999999999", tz="UTC").value)
        out = [b for b in bars if lo <= b.ts_init <= hi]
        seen["windows"].append((start, end))
        seen["max_ts"] = max(b.ts_init for b in out)
        return out

    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    lc = V2Lifecycle(study, repo_root=ROOT, options=V2Options(execute=True, datasets_dir=GOLDEN / "datasets",
                                                              extra_bindings=SYNTHETIC_BINDINGS, bar_source=source,
                                                              session_table_spec=session, in_process_partitions=True))
    lc.compile(); lc.prepare()
    (study / "artifacts").mkdir(exist_ok=True)
    (study / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(
        {"composite_seal_hash": "seal", "execution_manifest_composite_sha256": "mfst"}), encoding="utf-8")
    out = study / "_work" / "controller" / "partitions" / "train" / "2029"
    manifest = lc.run_partition(2029, "train", out)
    return (pd.read_parquet(out / "candidates.parquet"), pd.read_parquet(out / "observations.parquet"), manifest, seen)


def test_train_only_partition_processes_emits_and_resolves_nothing_from_the_prohibited_year(tmp_path, golden):
    """Failure modes (2), (3), (4) through the real host: the TRAIN-only partition is handed no 2030
    bar, emits no 2030 row, and its every 2029 row is identical to the run that DID stream 2030
    (dev tail) -- so 2030 information changed nothing -- with no outcome cut short (no DATA_END)."""
    c_cut, o_cut, m_cut, seen_cut = _run_2029(tmp_path, golden, {"train": [2029], "dev": [], "prohibited": [2030]}, "cut")
    c_tail, o_tail, m_tail, seen_tail = _run_2029(tmp_path, golden, {"train": [2029], "dev": [2030], "prohibited": []}, "tail")
    assert seen_cut["windows"] == [("2029-01-01", "2029-12-31")] and seen_cut["max_ts"] <= END_2029
    assert seen_tail["windows"] == [("2029-01-01", "2030-01-01")] and seen_tail["max_ts"] > END_2029   # the tail DID stream 2030
    assert len(c_cut) > 0
    for frame in (c_cut, o_cut, c_tail, o_tail):
        assert pd.to_datetime(frame["observation_ts"], unit="ns", utc=True).dt.year.eq(2029).all()     # (3)
    pd.testing.assert_frame_equal(c_cut, c_tail)                                                      # (4)
    pd.testing.assert_frame_equal(o_cut, o_tail)
    reasons = pd.concat([o_cut[c] for c in o_cut.columns if c.endswith("censor_reason")])
    assert not reasons.eq("DATA_END").any()
    assert m_cut["run_end"] == "2029-12-31" and m_tail["run_end"] == "2030-01-01"


def test_an_outcome_unresolvable_inside_the_window_is_censored_data_end_never_dropped(golden):
    """Outcome resolution at the final permitted timestamp: a stream that ends mid-horizon keeps the
    candidate and censors it DATA_END (visible to the parity gate's censoring comparison)."""
    bars, expected = golden
    full = _host_run(bars, expected)
    T = int(full["observations"]["observation_ts"].max())
    cut = _host_run([b for b in bars if b.ts_init <= T + NS], expected)
    assert set(cut["candidates"]["observation_ts"]) == set(full["candidates"]["observation_ts"])  # nothing dropped
    last = cut["observations"].set_index("observation_ts").loc[T]
    assert "DATA_END" in {last[c] for c in cut["observations"].columns if c.endswith("censor_reason")}


@pytest.mark.xfail(strict=True, reason="PENDING_AT_END_VACUOUS: HostCore.stats() is read after finalize() has drained "
                                       "kernel.pending, so stats['pending_at_end'] is always 0 and the smoke check "
                                       "'pending_resolved_at_run_end' / WINDOW_OUTCOME_UNRESOLVED can never fire")
def test_pending_at_end_reports_outcomes_left_open_by_the_window(golden):
    bars, expected = golden
    full = _host_run(bars, expected)
    T = int(full["observations"]["observation_ts"].max())
    cut = _host_run([b for b in bars if b.ts_init <= T + NS], expected)
    assert cut["stats"]["pending_at_end"] > 0


def _host_run(bars, expected):
    import tempfile
    from research_workflow.grammar.compiler import compile_study
    from research_workflow.host_runner import run_plan_on_bars
    from research_workflow.sessions import build_session_table
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    body = yaml.safe_load((GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8"))
    out = compile_study(body, repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, out.gaps.to_dict()
    tmp = Path(tempfile.mkdtemp()) / "compiled_plan.json"
    out.plan.write(tmp)
    plan = json.loads(tmp.read_text(encoding="utf-8"))
    table = build_session_table({"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]})
    return run_plan_on_bars(plan, bars, session_table=table)
