"""Repair packet D / D1+D2: the compiler must consume the DatasetSpec declared
``reference_tables`` contract (not a phantom ``calendar_table`` flag), the runtime must derive
explicit RTH/ETH calendar windows from a dataset sessions reference table with fail-closed
hash verification, and no ETH session-close path may silently inherit the RTH close.

All fixtures are synthetic (a tmp catalog directory / a pandas_market_calendars-derived sessions
table); the real catalog is never opened."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_workflow import dataset_v2
from research_workflow.dataset_v2 import DatasetV2Error, session_table
from research_workflow.sessions import (
    CalendarSessionTable, LegacySessionTable, SessionCloseUndefinedError,
    SessionHaltInvalidError, SessionRowInvalidError,
    build_session_table, resolve_calendar_session_spec, session_windows,
)

ROOT = Path(__file__).resolve().parents[2]
CT = "America/Chicago"


def _ns(s: str) -> int:
    return int(pd.Timestamp(s, tz=CT).tz_convert("UTC").value)


@pytest.fixture(scope="module")
def sessions_df():
    first = pd.Timestamp("2020-12-20", tz="UTC").value
    last = pd.Timestamp("2024-11-30", tz="UTC").value
    return session_table(first, last)


# --------------------------------------------------------------------------- #
# session_windows: RTH / ETH derivation
# --------------------------------------------------------------------------- #
def test_normal_day_rth_window(sessions_df):
    rows = session_windows(sessions_df, "RTH")
    assert (_ns("2024-01-03 08:30:00"), _ns("2024-01-03 15:15:00")) in rows


def test_normal_day_eth_segments(sessions_df):
    rows = session_windows(sessions_df, "ETH")
    day = pd.Timestamp("2024-01-03").date()
    row = sessions_df[sessions_df.session_date == day].iloc[0]
    pre = (int(row["open_ns"]), _ns("2024-01-03 08:30:00"))
    post = (_ns("2024-01-03 15:15:00"), int(row["close_ns"]))
    assert pre in rows
    assert post in rows


def test_dst_spring_forward_2024_03_10(sessions_df):
    # 08:30 CT on the Monday after spring-forward resolves via the CDT offset (UTC-5), not the
    # stale CST offset (UTC-6): 08:30 CDT == 13:30Z, NOT 14:30Z.
    rows = session_windows(sessions_df, "RTH")
    monday_open, monday_close = _ns("2024-03-11 08:30:00"), _ns("2024-03-11 15:15:00")
    assert (monday_open, monday_close) in rows
    assert monday_open == pd.Timestamp("2024-03-11 13:30:00", tz="UTC").value


def test_dst_fall_back_2024_11_03(sessions_df):
    rows = session_windows(sessions_df, "RTH")
    monday_open, monday_close = _ns("2024-11-04 08:30:00"), _ns("2024-11-04 15:15:00")
    assert (monday_open, monday_close) in rows
    assert monday_open == pd.Timestamp("2024-11-04 14:30:00", tz="UTC").value


def test_holiday_has_no_window_and_not_in_session(sessions_df):
    holiday = pd.Timestamp("2024-01-01").date()
    assert holiday not in set(sessions_df.session_date)
    rows = session_windows(sessions_df, "RTH")
    table = CalendarSessionTable(rows, name="RTH")
    assert not table.in_session(_ns("2024-01-01 10:00:00"))


def test_early_close_rth_close_is_calendar_close_not_1515():
    first = pd.Timestamp("2024-06-25", tz="UTC").value
    last = pd.Timestamp("2024-07-10", tz="UTC").value
    s = session_table(first, last)
    early_row = s[(s.session_date == pd.Timestamp("2024-07-03").date())].iloc[0]
    assert bool(early_row["early_close"])
    rows = session_windows(s, "RTH")
    windows = dict(rows)
    early_open = _ns("2024-07-03 08:30:00")
    assert early_open in windows
    assert windows[early_open] == int(early_row["close_ns"])
    assert windows[early_open] != _ns("2024-07-03 15:15:00")


def test_session_boundary_close_attribution(sessions_df):
    rows = session_windows(sessions_df, "RTH")
    table = CalendarSessionTable(rows, name="RTH")
    assert table.in_session(_ns("2024-01-03 08:30:00")) is False   # closes exactly at open -> NOT in RTH
    assert table.in_session(_ns("2024-01-03 15:15:00")) is True    # closes exactly at RTH close -> IS in RTH


def test_eth_close_for_preopen_ts_is_the_open_instant(sessions_df):
    rows = session_windows(sessions_df, "ETH")
    table = CalendarSessionTable(rows, name="ETH")
    assert table.session_close(_ns("2024-01-03 07:00:00")) == _ns("2024-01-03 08:30:00")


def test_eth_close_for_postclose_ts_is_the_day_close(sessions_df):
    rows = session_windows(sessions_df, "ETH")
    table = CalendarSessionTable(rows, name="ETH")
    assert table.session_close(_ns("2024-01-03 15:45:00")) == _ns("2024-01-03 16:00:00")


def test_halt_day_eth_post_segment_starts_at_halt_end():
    first = pd.Timestamp("2021-02-25", tz="UTC").value
    last = pd.Timestamp("2021-03-04", tz="UTC").value
    s = session_table(first, last)
    rows = session_windows(s, "ETH")
    starts = {o for o, _ in rows}
    assert _ns("2021-03-01 15:30:00") in starts        # halt end, not 15:15
    assert _ns("2021-03-01 15:15:00") not in starts


# --------------------------------------------------------------------------- #
# N-2: session_windows fails closed on a malformed sessions reference-table row
# --------------------------------------------------------------------------- #
def _synthetic_row(**overrides) -> dict:
    day = pd.Timestamp("2024-01-03").date()
    row = {"session_date": day, "open_ns": _ns("2024-01-02 17:00:00"), "close_ns": _ns("2024-01-03 16:00:00"),
           "early_close": False, "halt_start_ns": None, "halt_end_ns": None}
    row.update(overrides)
    return row


def test_session_row_close_before_open_rejects():
    df = pd.DataFrame([_synthetic_row(close_ns=_ns("2024-01-02 17:00:00") - 1)])
    with pytest.raises(SessionRowInvalidError, match="SESSION_ROW_INVALID"):
        session_windows(df, "RTH")


def test_session_row_close_equal_open_rejects():
    open_ns = _ns("2024-01-02 17:00:00")
    df = pd.DataFrame([_synthetic_row(open_ns=open_ns, close_ns=open_ns)])
    with pytest.raises(SessionRowInvalidError, match="SESSION_ROW_INVALID"):
        session_windows(df, "RTH")


def test_overlapping_consecutive_session_rows_reject():
    first = _synthetic_row(session_date=pd.Timestamp("2024-01-02").date(),
                            open_ns=_ns("2024-01-01 17:00:00"), close_ns=_ns("2024-01-03 10:00:00"))
    second = _synthetic_row(session_date=pd.Timestamp("2024-01-03").date(),
                             open_ns=_ns("2024-01-02 17:00:00"), close_ns=_ns("2024-01-03 16:00:00"))
    df = pd.DataFrame([first, second])
    with pytest.raises(SessionRowInvalidError, match="SESSION_ROW_INVALID"):
        session_windows(df, "RTH")


def test_halt_end_before_halt_start_rejects():
    halt_end = _ns("2024-01-03 15:30:00")
    df = pd.DataFrame([_synthetic_row(halt_start_ns=halt_end + 1, halt_end_ns=halt_end)])
    with pytest.raises(SessionHaltInvalidError, match="SESSION_HALT_INVALID"):
        session_windows(df, "ETH")


def test_halt_end_before_rth_close_it_interrupts_rejects():
    # RTH close is 15:15:00 CT; a halt ending before that cannot be interrupting it.
    halt_start = _ns("2024-01-03 15:00:00")
    halt_end = _ns("2024-01-03 15:10:00")
    df = pd.DataFrame([_synthetic_row(halt_start_ns=halt_start, halt_end_ns=halt_end)])
    with pytest.raises(SessionHaltInvalidError, match="SESSION_HALT_INVALID"):
        session_windows(df, "ETH")


# --------------------------------------------------------------------------- #
# LegacySessionTable ETH: fail closed, no silent RTH inheritance
# --------------------------------------------------------------------------- #
def test_legacy_eth_session_close_raises():
    table = LegacySessionTable("ETH")
    with pytest.raises(SessionCloseUndefinedError):
        table.session_close(_ns("2024-01-03 07:00:00"))


def test_legacy_rth_session_close_unaffected():
    table = LegacySessionTable("RTH")
    assert table.session_close(_ns("2024-01-03 10:00:00")) == _ns("2024-01-03 15:15:00")


# --------------------------------------------------------------------------- #
# reference-table verification: fail closed on missing/corrupt/mismatched
# --------------------------------------------------------------------------- #
def _write_ref_catalog(tmp_path: Path, *, corrupt: bool = False, missing: bool = False) -> Path:
    catalog = tmp_path / "SYN_CAL"
    ref_dir = catalog / "reference"
    ref_dir.mkdir(parents=True)
    tables = {"sessions": pd.DataFrame({"open_ns": [1], "close_ns": [2]}), "holidays": pd.DataFrame({"date": ["2024-01-01"]})}
    ref_manifest = {}
    for name, df in tables.items():
        p = ref_dir / f"{name}.parquet"
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), p)
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        ref_manifest[name] = {"path": p.name, "rows": len(df), "sha256": sha}
    digest = hashlib.sha256(json.dumps({k: v["sha256"] for k, v in ref_manifest.items()}, sort_keys=True).encode()).hexdigest()
    if corrupt:
        (ref_dir / "sessions.parquet").write_bytes(b"not-a-parquet-file")
    if missing:
        (ref_dir / "holidays.parquet").unlink()
    manifest = {"reference_tables": ref_manifest, "reference_digest": digest}
    (catalog / "build_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return catalog


def test_load_reference_tables_ok(tmp_path):
    catalog = _write_ref_catalog(tmp_path)
    manifest = json.loads((catalog / "build_manifest.json").read_text())
    digest = manifest["reference_digest"]
    tables = dataset_v2.load_reference_tables(catalog, ["sessions", "holidays"], digest)
    assert set(tables) == {"sessions", "holidays"}


def test_load_reference_tables_missing_fails_closed(tmp_path):
    catalog = _write_ref_catalog(tmp_path, missing=True)
    with pytest.raises(DatasetV2Error, match="REFERENCE_TABLE_MISSING"):
        dataset_v2.load_reference_tables(catalog, ["sessions", "holidays"], None)


def test_load_reference_tables_corrupt_fails_closed(tmp_path):
    catalog = _write_ref_catalog(tmp_path, corrupt=True)
    with pytest.raises(DatasetV2Error, match="REFERENCE_TABLE_CORRUPT"):
        dataset_v2.load_reference_tables(catalog, ["sessions", "holidays"], None)


def test_load_reference_tables_digest_mismatch_fails_closed(tmp_path):
    catalog = _write_ref_catalog(tmp_path)
    with pytest.raises(DatasetV2Error, match="REFERENCE_DIGEST_MISMATCH"):
        dataset_v2.load_reference_tables(catalog, ["sessions", "holidays"], "0" * 64)


# --------------------------------------------------------------------------- #
# resolve_calendar_session_spec: end-to-end row materialization from a synthetic catalog
# --------------------------------------------------------------------------- #
def test_resolve_calendar_session_spec_materializes_rows(tmp_path, monkeypatch):
    catalog = tmp_path / "SYN_CAL2"
    ref_dir = catalog / "reference"
    ref_dir.mkdir(parents=True)
    first = pd.Timestamp("2024-01-02", tz="UTC").value
    last = pd.Timestamp("2024-01-10", tz="UTC").value
    s = session_table(first, last)
    p = ref_dir / "sessions.parquet"
    pq.write_table(pa.Table.from_pandas(s, preserve_index=False), p)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    ref_manifest = {"sessions": {"path": "sessions.parquet", "rows": len(s), "sha256": sha}}
    digest = hashlib.sha256(json.dumps({k: v["sha256"] for k, v in ref_manifest.items()}, sort_keys=True).encode()).hexdigest()
    (catalog / "build_manifest.json").write_text(json.dumps({"reference_tables": ref_manifest, "reference_digest": digest}), encoding="utf-8")

    from research_workflow import roots as roots_mod

    def fake_resolve_dataset(dataset_id, repo_root, **kw):
        return roots_mod.ResolvedDataset(dataset_id, catalog, digest, "test", None)

    monkeypatch.setattr(roots_mod, "resolve_dataset", fake_resolve_dataset)
    spec = {"kind": "calendar", "session": "RTH", "censor_session": "RTH", "dataset": "SYN_CAL2",
            "reference_tables": ["sessions"], "reference_digest": digest}
    resolved = resolve_calendar_session_spec(spec, ROOT)
    assert resolved["rows"], resolved
    table = build_session_table(resolved)
    assert isinstance(table, CalendarSessionTable)
    assert table.in_session(_ns("2024-01-03 10:00:00"))


# --------------------------------------------------------------------------- #
# compiler: reference_tables contract, not the phantom calendar_table flag
# --------------------------------------------------------------------------- #
def _dataset_with_reference_tables(tmp_path: Path, ref_tables) -> Path:
    src = ROOT / "fixtures" / "golden" / "datasets" / "SYN_A.yaml"
    import yaml
    doc = yaml.safe_load(src.read_text(encoding="utf-8"))
    if ref_tables is not None:
        doc["reference_tables"] = ref_tables
        doc["reference_digest"] = "deadbeef"
    dst_dir = tmp_path / "datasets"
    dst_dir.mkdir(parents=True, exist_ok=True)
    (dst_dir / "SYN_A.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    (dst_dir / "SYN_B.yaml").write_text((ROOT / "fixtures" / "golden" / "datasets" / "SYN_B.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return dst_dir


def test_compiler_reads_reference_tables_not_calendar_table_flag(tmp_path):
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    spec = load_spec(ROOT / "fixtures" / "golden" / "study_barrier.yaml")
    datasets_dir = _dataset_with_reference_tables(tmp_path, ["sessions", "holidays"])
    out = compile_study(spec, repo_root=ROOT, datasets_dir=datasets_dir, extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, out.card()
    assert out.plan.session["kind"] == "calendar"
    assert out.plan.session["reference_tables"] == ["sessions", "holidays"]


def test_dataset_declares_reference_tables_without_sessions_is_a_typed_gap(tmp_path):
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.grammar.gaps import GapKind
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    spec = load_spec(ROOT / "fixtures" / "golden" / "study_barrier.yaml")
    datasets_dir = _dataset_with_reference_tables(tmp_path, ["holidays", "maintenance"])
    out = compile_study(spec, repo_root=ROOT, datasets_dir=datasets_dir, extra_bindings=SYNTHETIC_BINDINGS)
    assert not out.ok
    assert any(g.kind == GapKind.SEMANTIC_DECISION_REQUIRED and g.where == "outcome.session" for g in out.gaps.gaps)


def test_compiler_refuses_eth_censoring_on_a_non_calendar_dataset(tmp_path):
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.grammar.gaps import GapKind
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    spec = load_spec(ROOT / "fixtures" / "golden" / "study_barrier.yaml")
    spec["outcome"]["session"] = "ETH"
    datasets_dir = _dataset_with_reference_tables(tmp_path, None)   # legacy dataset (no reference_tables at all)
    out = compile_study(spec, repo_root=ROOT, datasets_dir=datasets_dir, extra_bindings=SYNTHETIC_BINDINGS)
    assert not out.ok
    assert any(g.kind == GapKind.SEMANTIC_DECISION_REQUIRED and g.where == "outcome.session" for g in out.gaps.gaps)


def test_legacy_dataset_still_compiles_as_legacy_kind_no_gap(tmp_path):
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    spec = load_spec(ROOT / "fixtures" / "golden" / "study_barrier.yaml")
    datasets_dir = _dataset_with_reference_tables(tmp_path, None)
    out = compile_study(spec, repo_root=ROOT, datasets_dir=datasets_dir, extra_bindings=SYNTHETIC_BINDINGS)
    assert out.ok, out.card()
    assert out.plan.session["kind"] == "legacy"
