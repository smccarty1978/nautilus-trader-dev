"""Reconcile stage: bounded memory, byte-identical findings and ``reconcile.json``.

chore/reconcile_bounded_memory. Before it, ``V2Lifecycle.reconcile`` ``pd.read_parquet``'d every
whole candidates/observations partition (202 columns incl. 9 nested profile structs for the G2
pilot: 3.23 GiB peak for 13,501 rows, linear in rows x profile width) although its checks need only
column names, row counts and the KEY columns. These tests pin, against the pre-chore implementation
kept verbatim below as an ORACLE (main 4f53d9ae): identical ``reconcile.json`` (all fields but the
generated timestamp) and identical raised error for every finding kind; column names identical to a
full pandas read (stored pandas index columns, named indexes, range indexes); and a peak memory that
does not grow with the nested payload width and grows with the row count only by the KEY columns.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_workflow.lifecycle_v2 import (KEY, LifecycleV2Error, V2Lifecycle, V2Options, _now, _read,  # noqa: F401
                                            _reconcile_parquet_shape, _write, load_plan, partition_windows,
                                            windows_identity)

REPO = Path(__file__).resolve().parents[2]
DAY = 86_400 * 10**9
T2022 = int(pd.Timestamp("2022-01-10", tz="UTC").value)
T2023 = int(pd.Timestamp("2023-03-01", tz="UTC").value)
WINDOW = {"id": "2022-01-10_2022-01-21", "year": 2022, "start": "2022-01-10", "end": "2022-01-21"}


# ---------------------------------------------------------------------------------------------------
# ORACLE: V2Lifecycle.reconcile exactly as on main 4f53d9ae (copied verbatim; test-only).
# ---------------------------------------------------------------------------------------------------
def _old_reconcile(self, study: Path | None = None) -> Dict[str, Any]:
    self._require_execute("reconcile")
    import pandas as pd
    plan = load_plan(self.study)
    base = self.work / "partitions" / "train"
    years = self._authorized_years(plan, "train", self.opts.years)
    findings: List[str] = []
    schemas, digests, rows = [], set(), 0
    seen_keys = 0
    for y in years:
        d = base / str(y)
        m = _read(d / "manifest.json")
        if m.get("status") != "PASS":
            findings.append(f"partition {y} not PASS"); continue
        c = pd.read_parquet(d / "candidates.parquet"); o = pd.read_parquet(d / "observations.parquet")
        schemas.append((tuple(c.columns), tuple(o.columns)))
        if (m.get("dataset") or {}).get("logical_digest"):
            digests.add(m["dataset"]["logical_digest"])
        if len(c) != len(o):
            findings.append(f"partition {y}: candidates {len(c)} != observations {len(o)}")
        if len(c) and c.duplicated(list(KEY)).any():
            findings.append(f"partition {y}: duplicate candidate keys")
        if len(c) and not pd.to_datetime(c["observation_ts"], unit="ns", utc=True).dt.year.eq(int(y)).all():
            findings.append(f"partition {y}: rows outside the primary year")
        # A date-bounded year is only reconciled against its DECLARED windows: proving rows sit
        # inside the calendar year would not detect a partition that streamed unauthorized dates.
        declared = partition_windows(plan, int(y))
        if declared and len(c):
            ts = pd.to_datetime(c["observation_ts"], unit="ns", utc=True)
            inside = False
            for w in declared:
                lo = pd.Timestamp(w["start"], tz="UTC")
                hi = pd.Timestamp(w["end"], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
                inside = ((ts >= lo) & (ts <= hi)) if inside is False else (inside | ((ts >= lo) & (ts <= hi)))
            outside = int((~inside).sum())
            if outside:
                findings.append(f"partition {y}: {outside} row(s) outside the declared windows "
                                f"{[w['id'] for w in declared]}")
            if [str(x) for x in (m.get("windows") or [])] == []:
                findings.append(f"partition {y}: manifest records no windows for a date-bounded year")
        rows += len(c); seen_keys += len(c)
    if len(set(schemas)) > 1:
        findings.append("partition output schema mismatch")
    if len(digests) > 1:
        findings.append(f"partitions read different dataset digests: {sorted(digests)}")
    reuse = self._reattest_partition_reuse(plan, base, years, findings)
    path = _write(self.work / "reconcile.json", {"passed": not findings, "findings": findings, "years": list(years), "rows": rows,
                                                "authority": "plan.chronology.train",
                                                "partition_windows": windows_identity((plan.get("chronology") or {}).get("windows") or []),
                                                "dataset_digests": sorted(digests),
                                                "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                                                "partition_reuse": reuse,
                                                "generated_at_utc": _now()})
    if findings:
        raise LifecycleV2Error("RECONCILE_FAILED: " + "; ".join(findings))
    return {"status": "PASS", "outputs": [str(path)]}


# -- fixtures -----------------------------------------------------------------------------------------
def _profile(n: int, width: int) -> pa.StructArray:
    w = pa.array([list(range(width + (i % 3))) if i % 7 else None for i in range(n)], pa.list_(pa.int64()))
    return pa.StructArray.from_arrays([pa.array(np.arange(n, dtype=np.int64)), w], ["snapshot_ts", "weights_fp"])


def _candidates(ts: np.ndarray, *, width: int = 8, extra: bool = False) -> pa.Table:
    n = len(ts)
    cols = {"observation_ts": pa.array(ts, pa.int64()), "regime_start_ns": pa.array(ts - 5 * 10**9, pa.int64()),
            "checkpoint_index": pa.array(np.arange(n) % 4, pa.int64()), "score": pa.array(np.linspace(0, 1, n)),
            "r0_h120_profile": _profile(n, width), "r1_h360_profile": _profile(n, width)}
    if extra:
        cols["extra"] = pa.array(np.zeros(n))
    return pa.table(cols)


def _observations(cand: pa.Table) -> pa.Table:
    return cand.select(list(KEY))


def _write_part(study: Path, year: int, cand: pa.Table, obs: pa.Table | None = None, *, status: str = "PASS",
                digest: str | None = "d0", windows: List[str] | None = None, rg: int = 7) -> Path:
    d = study / "_work" / "controller" / "partitions" / "train" / str(year)
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(cand, d / "candidates.parquet", row_group_size=rg)
    pq.write_table(_observations(cand) if obs is None else obs, d / "observations.parquet", row_group_size=max(1, rg * 2))
    m: Dict[str, Any] = {"status": status, "plan_sha256": "plan0"}
    if digest is not None:
        m["dataset"] = {"logical_digest": digest}
    if windows is not None:
        m["windows"] = windows
    (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return d


def _study(tmp_path: Path, *, windowed: bool = True) -> Path:
    study = tmp_path / "study"
    (study / "audit").mkdir(parents=True)
    plan = {"plan_sha256": "plan0", "chronology": {"train": [2022, 2023], "dev": [], "prohibited": [],
                                                    "windows": [WINDOW] if windowed else []}}
    (study / "compiled_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (study / "audit" / "frozen_execution_manifest.json").write_text(
        json.dumps({"frozen_execution_composite_sha256": "c0"}), encoding="utf-8")
    return study


def _ts(start: int, n: int, step: int = 60 * 10**9) -> np.ndarray:
    return start + np.arange(n, dtype=np.int64) * step


def _run(fn, lc: V2Lifecycle) -> tuple[Dict[str, Any], str | None]:
    out = lc.work / "reconcile.json"
    if out.exists():
        out.unlink()
    err = None
    try:
        fn(lc)
    except Exception as exc:  # the oracle and the new code must raise the same thing
        err = f"{type(exc).__name__}: {exc}"
    rec = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    rec.pop("generated_at_utc", None)
    return rec, err


def _assert_parity(study: Path) -> Dict[str, Any]:
    lc = V2Lifecycle(study, options=V2Options(execute=True))
    old, old_err = _run(_old_reconcile, lc)
    new, new_err = _run(lambda x: x.reconcile(), lc)
    assert new == old
    assert new_err == old_err
    raw = (lc.work / "reconcile.json").read_text(encoding="utf-8") if (lc.work / "reconcile.json").exists() else ""
    return {"rec": new, "err": new_err, "raw": raw}


# -- R1: parity per failure mode ---------------------------------------------------------------------
def _pass_study(tmp_path: Path) -> Path:
    study = _study(tmp_path)
    _write_part(study, 2022, _candidates(_ts(T2022, 50)), windows=[WINDOW["id"]])
    _write_part(study, 2023, _candidates(_ts(T2023, 31)), rg=5)
    return study


def test_parity_passing_case(tmp_path):
    r = _assert_parity(_pass_study(tmp_path))
    assert r["err"] is None and r["rec"]["passed"] is True and r["rec"]["rows"] == 81 and r["rec"]["findings"] == []


@pytest.mark.parametrize("case", ["row_count", "duplicate_keys", "outside_year", "outside_windows", "manifest_no_windows",
                                  "schema_mismatch", "digests", "not_pass", "several"])
def test_parity_failure_modes(tmp_path, case):
    study = _study(tmp_path)
    c22 = _candidates(_ts(T2022, 40))
    c23 = _candidates(_ts(T2023, 30))
    kw22: Dict[str, Any] = {"windows": [WINDOW["id"]]}
    kw23: Dict[str, Any] = {}
    if case in ("row_count", "several"):
        kw23["obs"] = _observations(c23).slice(0, 29)
    if case in ("duplicate_keys", "several"):
        c22 = pa.concat_tables([c22, c22.slice(3, 2)])
    if case == "outside_year":
        c23 = _candidates(np.concatenate([_ts(T2023, 28), np.array([T2022, T2022 + 1], dtype=np.int64)]))
    if case in ("outside_windows", "several"):
        c22 = pa.concat_tables([c22, _candidates(_ts(T2022 + 30 * DAY, 3))])
    if case == "manifest_no_windows":
        kw22["windows"] = []
    if case in ("schema_mismatch", "several"):
        c23 = _candidates(c23.column("observation_ts").to_numpy(), extra=True)
    if case in ("digests", "several"):
        kw23["digest"] = "d1"
    if case == "not_pass":
        kw23["status"] = "FAILED"
    _write_part(study, 2022, c22, **kw22)
    _write_part(study, 2023, c23, **kw23)
    r = _assert_parity(study)
    assert r["rec"]["passed"] is False and r["rec"]["findings"], r
    assert r["err"] and r["err"].startswith("LifecycleV2Error: RECONCILE_FAILED: "), r


def test_parity_whole_year_and_empty_partition(tmp_path):
    study = _study(tmp_path, windowed=False)
    _write_part(study, 2022, _candidates(_ts(T2022, 0)))
    _write_part(study, 2023, _candidates(_ts(T2023, 12)), digest=None)
    r = _assert_parity(study)
    assert r["err"] is None and r["rec"]["rows"] == 12


def test_parity_empty_partition_under_declared_window(tmp_path):
    study = _study(tmp_path)
    _write_part(study, 2022, _candidates(_ts(T2022, 0)), windows=[])
    _write_part(study, 2023, _candidates(_ts(T2023, 3)))
    assert _assert_parity(study)["err"] is None


def test_parity_missing_key_column_raises_the_same_error(tmp_path):
    study = _study(tmp_path)
    c = _candidates(_ts(T2022, 9)).drop_columns(["checkpoint_index"])
    _write_part(study, 2022, c, obs=c.select(["observation_ts", "regime_start_ns"]), windows=[WINDOW["id"]])
    _write_part(study, 2023, _candidates(_ts(T2023, 4)))
    r = _assert_parity(study)
    assert r["err"] and r["err"].startswith("KeyError"), r
    # empty partition without KEY columns: neither implementation touches KEY
    study2 = _study(tmp_path / "b")
    c0 = _candidates(_ts(T2022, 0)).drop_columns(["checkpoint_index"])
    _write_part(study2, 2022, c0, obs=c0.select(["observation_ts"]), windows=[])
    _write_part(study2, 2023, _candidates(_ts(T2023, 4)))
    assert _assert_parity(study2)["rec"]["findings"] == ["partition output schema mismatch"]


@pytest.mark.parametrize("index", ["default_range", "stored_unnamed", "stored_named", "no_index"])
def test_parity_pandas_written_partitions(tmp_path, index):
    """pandas-written partitions: the stored index (``__index_level_0__`` / a named index / range
    metadata) is not a pandas column; the footer-only names must reproduce that exactly."""
    study = _study(tmp_path)
    for y, start, n in ((2022, T2022, 25), (2023, T2023, 18)):
        df = pd.DataFrame({"observation_ts": _ts(start, n), "regime_start_ns": _ts(start, n) - 7,
                           "checkpoint_index": np.arange(n) % 3, "score": np.linspace(0, 1, n), "label": ["a"] * n})
        kw: Dict[str, Any] = {}
        if index == "stored_unnamed":
            df.index = np.arange(n) * 10 + 5
            kw["index"] = True
        elif index == "stored_named":
            df.index = pd.Index(np.arange(n) * 3, name="row_id")
            kw["index"] = True
        elif index == "no_index":
            kw["index"] = False
        d = study / "_work" / "controller" / "partitions" / "train" / str(y)
        d.mkdir(parents=True)
        df.to_parquet(d / "candidates.parquet", row_group_size=7, **kw)
        df[list(KEY)].to_parquet(d / "observations.parquet", **kw)
        (d / "manifest.json").write_text(json.dumps({"status": "PASS", "plan_sha256": "plan0", "windows": [WINDOW["id"]] if y == 2022 else [],
                                                     "dataset": {"logical_digest": "d0"}}), encoding="utf-8")
        for name in ("candidates.parquet", "observations.parquet"):
            names, rows = _reconcile_parquet_shape(d / name)
            full = pd.read_parquet(d / name)
            assert names == tuple(full.columns) and rows == len(full)
    r = _assert_parity(study)
    assert r["err"] is None, r


def test_shape_matches_pandas_on_nested_multi_row_group(tmp_path):
    p = tmp_path / "x.parquet"
    pq.write_table(_candidates(_ts(T2022, 101), width=40), p, row_group_size=9)
    assert pq.ParquetFile(p).metadata.num_row_groups == 12
    full = pd.read_parquet(p)
    assert _reconcile_parquet_shape(p) == (tuple(full.columns), len(full))


def test_row_group_layout_invariance(tmp_path):
    outs = []
    for rg in (1, 7, 1000):
        study = _study(tmp_path / str(rg))
        _write_part(study, 2022, _candidates(_ts(T2022, 50)), windows=[WINDOW["id"]], rg=rg)
        _write_part(study, 2023, pa.concat_tables([_candidates(_ts(T2023, 31))] * 1), rg=rg)
        outs.append(_assert_parity(study)["raw"].split('"generated_at_utc"')[0])
    assert outs[0] == outs[1] == outs[2]


# -- memory scaling ---------------------------------------------------------------------------------
_MEM_SCRIPT = textwrap.dedent("""
    import json, sys, tracemalloc
    import pyarrow as pa
    from pathlib import Path
    from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options
    lc = V2Lifecycle(Path(sys.argv[1]), options=V2Options(execute=True))
    pool = pa.default_memory_pool()
    base = pool.bytes_allocated()
    tracemalloc.start()
    lc.reconcile()
    _, py_peak = tracemalloc.get_traced_memory()
    print(json.dumps({"arrow_peak": pool.max_memory() - base, "py_peak": py_peak}))
""")


def _measure(tmp_path: Path, n: int, width: int) -> Dict[str, int]:
    study = _study(tmp_path / f"{n}_{width}", windowed=False)
    d = study / "_work" / "controller" / "partitions" / "train" / "2022"
    d.mkdir(parents=True)
    ts_all = _ts(T2022, n)
    for name in ("candidates.parquet", "observations.parquet"):
        schema = _candidates(ts_all[:1], width=width).schema if name == "candidates.parquet" else _observations(_candidates(ts_all[:1])).schema
        with pq.ParquetWriter(d / name, schema) as w:
            for s in range(0, n, 500):
                c = _candidates(ts_all[s:s + 500], width=width)
                w.write_table(c if name == "candidates.parquet" else _observations(c))
    (d / "manifest.json").write_text(json.dumps({"status": "PASS", "plan_sha256": "plan0"}), encoding="utf-8")
    plan = json.loads((study / "compiled_plan.json").read_text(encoding="utf-8"))
    plan["chronology"]["train"] = [2022]
    (study / "compiled_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", _MEM_SCRIPT, str(study)], cwd=str(REPO), capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_reconcile_peak_flat_in_payload_width_and_key_bounded_in_rows(tmp_path):
    base = _measure(tmp_path, 4_000, 16)
    wide = _measure(tmp_path, 4_000, 1_024)      # ~8 KB/row x 2 profiles of list<int64>: ~64 MB of payload
    many = _measure(tmp_path, 16_000, 16)
    # Width: 64x the nested payload must not move the peak (a whole read would hold ~64 MB).
    for k in ("arrow_peak", "py_peak"):
        assert wide[k] < 1.25 * base[k] + (1 << 20), (k, base, wide)
    assert wide["arrow_peak"] < 8 << 20, wide
    # Rows: growth is bounded by the KEY columns (3 x int64 = 24 B/row; allow 16x that for pandas
    # temporaries: to_datetime, duplicated hashing, window masks), not by the row payload.
    for k in ("arrow_peak", "py_peak"):
        assert many[k] - base[k] < 12_000 * 24 * 16 + (1 << 20), (k, base, many)
