from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import scripts.build_dense_1s as dense_module
from scripts.build_dense_1s import DenseBuildError, NativeStream, add_native_exception_windows, aggregation_smoke, build_dense, densify_window, expected_windows, validate_native_boundaries, validate_output, write_calendar_conflicts


def ns(value: str) -> int:
    return int(np.datetime64(value, "ns").astype("int64"))


RAW_SCHEMA = pa.schema(
    [
        ("rtype", pa.uint8()), ("publisher_id", pa.uint16()), ("instrument_id", pa.uint32()),
        ("open", pa.float64()), ("high", pa.float64()), ("low", pa.float64()), ("close", pa.float64()),
        ("volume", pa.uint64()), ("symbol", pa.string()), ("ts_event", pa.timestamp("ns", tz="UTC")),
    ]
)


def native_table(times: list[str], closes: list[float]) -> pa.Table:
    size = len(times)
    values = {
        "rtype": pa.array([32] * size, type=pa.uint8()), "publisher_id": pa.array([1] * size, type=pa.uint16()),
        "instrument_id": pa.array([2] * size, type=pa.uint32()), "open": pa.array(closes), "high": pa.array(closes),
        "low": pa.array(closes), "close": pa.array(closes), "volume": pa.array([3] * size, type=pa.uint64()),
        "symbol": pa.array(["NQ"] * size), "ts_event": pa.array([ns(value) for value in times], type=pa.timestamp("ns", tz="UTC")),
    }
    return pa.Table.from_pydict(values, schema=RAW_SCHEMA)


def dense(times: list[str], closes: list[float], start: str, end: str):
    return densify_window(native_table(times, closes), ns(start), ns(end), {}, RAW_SCHEMA)[0]


def test_missing_one_second_carries_prior_close_and_marks_fill():
    out = dense(["2023-06-15T15:00:00", "2023-06-15T15:00:02"], [10.0, 12.0], "2023-06-15T15:00:00", "2023-06-15T15:00:03")
    assert out["is_fill"].to_pylist() == [False, True, False]
    assert out["open"].to_pylist() == [10.0, 10.0, 12.0]
    assert out["high"].to_pylist() == [10.0, 10.0, 12.0]
    assert out["low"].to_pylist() == [10.0, 10.0, 12.0]
    assert out["close"].to_pylist() == [10.0, 10.0, 12.0]
    assert out["volume"].to_pylist() == [3, 0, 3]


def test_multiple_missing_seconds_remain_at_last_known_close():
    out = dense(["2023-06-15T15:00:00", "2023-06-15T15:00:04"], [10.0, 14.0], "2023-06-15T15:00:00", "2023-06-15T15:00:05")
    assert out["close"].to_pylist() == [10.0, 10.0, 10.0, 10.0, 14.0]
    assert out["volume"].to_pylist() == [3, 0, 0, 0, 3]


def test_fill_ohlc_is_flat_at_previous_close_not_previous_native_open():
    raw = native_table(["2023-06-15T15:00:00", "2023-06-15T15:00:02"], [10.0, 12.0])
    raw = raw.set_column(raw.schema.get_field_index("open"), "open", pa.array([9.0, 11.0]))
    raw = raw.set_column(raw.schema.get_field_index("high"), "high", pa.array([11.0, 13.0]))
    raw = raw.set_column(raw.schema.get_field_index("low"), "low", pa.array([8.0, 10.0]))
    out, _ = densify_window(raw, ns("2023-06-15T15:00:00"), ns("2023-06-15T15:00:03"), {}, RAW_SCHEMA)
    assert out["open"].to_pylist()[1:2] == [10.0]
    assert out["high"].to_pylist()[1:2] == [10.0]
    assert out["low"].to_pylist()[1:2] == [10.0]
    assert out["close"].to_pylist()[1:2] == [10.0]


def test_native_row_is_preserved_exactly():
    raw = native_table(["2023-06-15T15:00:00"], [10.25])
    raw = raw.set_column(raw.schema.get_field_index("high"), "high", pa.array([11.5]))
    out, _ = densify_window(raw, ns("2023-06-15T15:00:00"), ns("2023-06-15T15:00:01"), {}, RAW_SCHEMA)
    assert out.drop(["is_fill"]).equals(raw, check_metadata=False)


def test_reopen_fill_uses_preclosure_close_not_next_native_price():
    before = native_table(["2023-06-15T20:59:59"], [100.0])
    _, state = densify_window(before, ns("2023-06-15T20:59:59"), ns("2023-06-15T21:00:00"), {}, RAW_SCHEMA)
    after = native_table(["2023-06-15T22:00:01"], [110.0])
    out, _ = densify_window(after, ns("2023-06-15T22:00:00"), ns("2023-06-15T22:00:02"), state, RAW_SCHEMA)
    assert out["close"].to_pylist() == [100.0, 110.0]
    assert out["is_fill"].to_pylist() == [True, False]


def test_old_break_is_closed_and_new_regime_is_open():
    old = list(expected_windows(ns("2021-06-25T20:14:59"), ns("2021-06-25T20:30:01")))
    new = list(expected_windows(ns("2021-06-28T20:14:59"), ns("2021-06-28T20:30:01")))
    assert sum((end - start) // 1_000_000_000 for start, end in old) == 4
    assert sum((end - start) // 1_000_000_000 for start, end in new) == 903


def test_scheduled_maintenance_has_no_expected_rows():
    windows = list(expected_windows(ns("2023-06-15T21:00:00"), ns("2023-06-15T21:59:58")))
    assert windows == [(ns("2023-06-15T21:00:00"), ns("2023-06-15T21:00:01"))]


@pytest.mark.parametrize("times, code", [
    (["2023-06-15T15:00:00", "2023-06-15T15:00:00"], "DUPLICATE_INPUT_TIMESTAMP"),
    (["2023-06-15T15:00:01", "2023-06-15T15:00:00"], "OUT_OF_ORDER_INPUT"),
])
def test_duplicate_and_out_of_order_input_fail_closed(tmp_path: Path, times: list[str], code: str):
    path = tmp_path / "NQ_v0_1s_2023.parquet"
    pq.write_table(native_table(times, [10.0, 11.0]), path)
    stream = NativeStream([path], RAW_SCHEMA)
    with pytest.raises(DenseBuildError, match=code):
        stream.read_window(ns("2023-06-15T15:00:00"), ns("2023-06-15T15:00:03"))


def test_partial_end_is_clipped_to_last_native_second():
    windows = list(expected_windows(ns("2023-06-15T15:00:00"), ns("2023-06-15T15:00:02")))
    assert windows == [(ns("2023-06-15T15:00:00"), ns("2023-06-15T15:00:03"))]


def test_calendar_covers_weekend_sunday_reopen_holiday_and_dst_cases():
    assert list(expected_windows(ns("2023-06-17T15:00:00"), ns("2023-06-17T15:00:01"))) == []  # Saturday
    assert list(expected_windows(ns("2023-06-18T22:00:00"), ns("2023-06-18T22:00:01"))) == [(ns("2023-06-18T22:00:00"), ns("2023-06-18T22:00:02"))]
    assert list(expected_windows(ns("2023-12-25T15:00:00"), ns("2023-12-25T15:00:01"))) == []  # Christmas closure
    assert list(expected_windows(ns("2024-01-01T15:00:00"), ns("2024-01-01T15:00:01"))) == []  # New Year closure
    assert sum((end - start) // 1_000_000_000 for start, end in expected_windows(ns("2023-11-23T17:59:59"), ns("2023-11-23T18:00:01"))) == 2  # Thanksgiving early close boundary
    assert list(expected_windows(ns("2023-03-12T22:00:00"), ns("2023-03-12T22:00:01"))) == [(ns("2023-03-12T22:00:00"), ns("2023-03-12T22:00:02"))]  # DST Sunday reopen


def test_delayed_special_open_is_preserved_from_calendar(monkeypatch: pytest.MonkeyPatch):
    class DelayedOpenCalendar:
        def schedule(self, **_kwargs):
            return pd.DataFrame(
                {"market_open": [pd.Timestamp("2023-01-03T00:00:00Z")], "break_start": [pd.Timestamp("2023-01-03T21:15:00Z")], "break_end": [pd.Timestamp("2023-01-03T21:30:00Z")], "market_close": [pd.Timestamp("2023-01-03T22:00:00Z")]},
                index=[pd.Timestamp("2023-01-03")],
            )
    monkeypatch.setattr(dense_module.mcal, "get_calendar", lambda _: DelayedOpenCalendar())
    assert list(expected_windows(ns("2023-01-02T23:59:59"), ns("2023-01-03T00:00:01"))) == [(ns("2023-01-03T00:00:00"), ns("2023-01-03T00:00:02"))]


def write_raw_source(tmp_path: Path, table: pa.Table) -> Path:
    path = tmp_path / "NQ_v0_1s_2023.parquet"
    pq.write_table(table, path)
    return path


def test_native_boundary_precheck_reports_endpoints_and_conflicts(tmp_path: Path):
    source = write_raw_source(tmp_path, native_table(["2023-06-15T21:00:00", "2023-06-15T22:00:00"], [10.0, 12.0]))
    report = validate_native_boundaries([source])
    assert report["native_16_00_00_rows"] == 1 and report["native_17_00_00_rows"] == 1
    assert report["native_interior_16_00_17_00_rows"] == 0 and report["boundary_validation"] == "PASS"
    interior = write_raw_source(tmp_path, native_table(["2023-06-15T21:00:00", "2023-06-15T21:15:01"], [10.0, 11.0]))
    assert validate_native_boundaries([interior])["boundary_validation"] == "PASS"
    material = write_raw_source(tmp_path, native_table(["2023-06-15T21:15:01", "2023-06-15T21:15:02"], [10.0, 11.0]))
    material_report = validate_native_boundaries([material])
    assert material_report["boundary_validation"] == "PASS"
    assert material_report["calendar_conflict_status"] == "WARNING"
    assert material_report["native_calendar_conflict_rows"] == 2
    pre_boundary = write_raw_source(tmp_path, native_table(["2021-06-25T20:15:00"], [10.0]))
    assert validate_native_boundaries([pre_boundary])["pre_2021_native_15_15_boundary_rows"] == 1
    assert validate_native_boundaries([pre_boundary])["boundary_validation"] == "PASS"
    pre_interior = write_raw_source(tmp_path, native_table(["2021-06-25T20:15:01"], [10.0]))
    assert validate_native_boundaries([pre_interior])["boundary_validation"] == "PASS"


def test_native_rows_inside_generic_early_close_are_preserved_and_reported(tmp_path: Path):
    # CME_Equity closes Thanksgiving 2016 at 12:00 CT.  Rows after that
    # boundary are neither NQ endpoint exceptions nor valid open seconds.
    source = write_raw_source(
        tmp_path,
        native_table(["2016-11-25T18:00:01", "2016-11-25T18:00:02"], [10.0, 11.0]),
    )
    report = validate_native_boundaries([source])
    assert report["native_inside_generic_calendar_closure_rows"] == 2
    assert report["boundary_validation"] == "PASS"


def test_isolated_native_row_inside_generic_closure_is_preserved(tmp_path: Path):
    source = write_raw_source(
        tmp_path,
        native_table(["2016-11-25T18:00:01"], [10.0]),
    )
    report = validate_native_boundaries([source])
    assert report["native_inside_generic_calendar_closure_rows"] == 1
    assert report["native_closure_exception_rows"] == 1
    assert report["boundary_validation"] == "PASS"


def test_native_row_in_weekend_closure_is_preserved_and_reported(tmp_path: Path):
    source = write_raw_source(tmp_path, native_table(["2023-06-17T15:00:00"], [10.0]))
    report = validate_native_boundaries([source])
    assert report["native_inside_unallowed_calendar_closure_rows"] == 1
    assert report["boundary_validation"] == "PASS"
    assert report["calendar_conflict_status"] == "WARNING"
    maintenance_clock = write_raw_source(tmp_path, native_table(["2023-06-17T21:15:00"], [10.0]))
    report = validate_native_boundaries([maintenance_clock])
    assert report["native_inside_unallowed_calendar_closure_rows"] == 1
    assert report["boundary_validation"] == "PASS"


def test_nonmaterial_exception_limit_and_native_only_window(tmp_path: Path):
    base = ns("2023-06-15T21:00:00")
    isolated = [base + (index * 2 + 1) * 1_000_000_000 for index in range(100)]
    times = [pd.Timestamp(value, unit="ns", tz="UTC").strftime("%Y-%m-%dT%H:%M:%S") for value in isolated]
    allowed = write_raw_source(tmp_path, native_table(times, [10.0] * 100))
    allowed_report = validate_native_boundaries([allowed])
    assert allowed_report["boundary_validation"] == "PASS" and allowed_report["native_calendar_conflict_rows"] == 100
    blocked = write_raw_source(tmp_path, native_table(times + ["2023-06-15T21:03:21"], [10.0] * 101))
    blocked_report = validate_native_boundaries([blocked])
    assert blocked_report["boundary_validation"] == "PASS" and blocked_report["native_calendar_conflict_rows"] == 101
    # Every conflict is emitted as a native-only singleton row.
    windows = add_native_exception_windows([(base, base + 1_000_000_000)], [base + 2_000_000_000])
    assert windows == [(base, base + 1_000_000_000), (base + 2_000_000_000, base + 3_000_000_000)]
    out, _ = densify_window(native_table(["2023-06-15T21:00:02"], [10.0]), base + 2_000_000_000, base + 3_000_000_000, {}, RAW_SCHEMA)
    assert out["is_fill"].to_pylist() == [False] and out["volume"].to_pylist() == [3]


def test_calendar_conflict_csv_preserves_native_ohlcv(tmp_path: Path):
    source = write_raw_source(tmp_path, native_table(["2016-11-25T18:00:01"], [10.0]))
    schema = pq.ParquetFile(source).schema_arrow
    report = validate_native_boundaries([source])
    artifact = tmp_path / "calendar_conflicts.csv"
    assert write_calendar_conflicts([source], schema, report["native_calendar_conflict_ns"], artifact) == 1
    text = artifact.read_text(encoding="utf-8")
    assert "CALENDAR_CONFLICT_NATIVE_PRESENT" in text and "10.0" in text


def test_validator_reports_native_parity_fill_validity_and_ytd_overrun(tmp_path: Path):
    raw = native_table(["2023-06-15T15:00:00", "2023-06-15T15:00:02"], [10.0, 12.0])
    source = write_raw_source(tmp_path, raw)
    output = tmp_path / "candidate.parquet"
    dense_out, _ = densify_window(raw, ns("2023-06-15T15:00:00"), ns("2023-06-15T15:00:03"), {}, RAW_SCHEMA)
    pq.write_table(dense_out, output)
    report = validate_output([source], output, [(ns("2023-06-15T15:00:00"), ns("2023-06-15T15:00:03"))], ns("2023-06-15T15:00:02"))
    assert report["native_mismatches"] == report["fill_violations"] == report["ytd_overrun_rows"] == 0
    assert report["missing_expected_open_seconds"] == report["rows_during_scheduled_closures"] == 0


def test_coverage_counts_missing_and_closed_seconds_independently(tmp_path: Path):
    base = ns("2023-06-15T15:00:00")
    windows = [(base, base + 3_000_000_000)]
    missing = tmp_path / "missing.parquet"
    pq.write_table(pa.table({"ts_event": pa.array([base, base + 2_000_000_000], type=pa.timestamp("ns", tz="UTC"))}), missing)
    report = dense_module._validate_expected_coverage(missing, windows)
    assert report["missing_expected_open_seconds"] == 1 and report["rows_during_scheduled_closures"] == 0
    extra = tmp_path / "extra.parquet"
    pq.write_table(pa.table({"ts_event": pa.array([base, base + 1_000_000_000, base + 2_000_000_000, base + 3_000_000_000], type=pa.timestamp("ns", tz="UTC"))}), extra)
    report = dense_module._validate_expected_coverage(extra, windows)
    assert report["missing_expected_open_seconds"] == 0 and report["rows_during_scheduled_closures"] == 1


def test_native_stream_is_continuous_across_source_year_boundary(tmp_path: Path):
    first = tmp_path / "NQ_v0_1s_2022.parquet"
    second = tmp_path / "NQ_v0_1s_2023.parquet"
    pq.write_table(native_table(["2022-12-31T23:59:59"], [10.0]), first)
    pq.write_table(native_table(["2023-01-01T00:00:00"], [11.0]), second)
    stream = NativeStream([first, second], RAW_SCHEMA)
    rows = stream.read_window(ns("2022-12-31T23:59:59"), ns("2023-01-01T00:00:01"))
    assert rows["ts_event"].to_pylist() == [pd.Timestamp("2022-12-31T23:59:59Z"), pd.Timestamp("2023-01-01T00:00:00Z")]


def test_normal_aggregation_smoke_uses_dense_clock(tmp_path: Path):
    seconds = [f"2023-06-15T15:{minute:02d}:{second:02d}" for minute in range(60) for second in range(60)]
    raw = native_table(seconds, [float(index) for index in range(3600)])
    output = tmp_path / "dense.parquet"
    dense_out, _ = densify_window(raw, ns(seconds[0]), ns("2023-06-15T16:00:00"), {}, RAW_SCHEMA)
    pq.write_table(dense_out, output)
    assert aggregation_smoke(output, samples=("2023-06-15",)) == {"5s": "PASS", "30s": "PASS", "1m": "PASS"}


def test_failed_validation_does_not_publish_canonical_file(tmp_path: Path):
    write_raw_source(tmp_path, native_table(["2023-06-15T15:00:00", "2023-06-15T15:00:01"], [10.0, 11.0]))
    output = tmp_path / "published.parquet"
    manifest = tmp_path / "manifest.json"
    with pytest.raises(DenseBuildError, match="VALIDATION_FAILED"):
        build_dense("NQ", tmp_path, output, manifest)
    assert not output.exists()
    assert (tmp_path / "manifest.failed.json").exists()


def test_partitioned_fallback_is_published_only_after_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_raw_source(tmp_path, native_table(["2023-06-15T15:00:00", "2023-06-15T15:00:01"], [10.0, 11.0]))
    output = tmp_path / "published.parquet"
    manifest = tmp_path / "manifest.json"
    original = dense_module._write_candidate
    calls = {"single": 0}

    def writer_failure_then_fallback(*args, **kwargs):
        if not kwargs["partitioned"]:
            calls["single"] += 1
            raise OSError("simulated single-file writer failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(dense_module, "_write_candidate", writer_failure_then_fallback)
    monkeypatch.setattr(dense_module, "aggregation_smoke", lambda _: {"5s": "PASS", "30s": "PASS", "1m": "PASS"})
    result = build_dense("NQ", tmp_path, output, manifest)
    fallback = tmp_path / "NQ_dense_1s"
    assert calls["single"] == 1
    assert result["format"] == "PARTITIONED_FALLBACK"
    assert result["fallback_reason"] == "OSError: simulated single-file writer failure"
    assert "early closes" in result["project_nq_endpoint_override"]
    assert result["output_sha256"] and fallback.is_dir() and manifest.exists() and not output.exists()


def test_manifest_write_failure_does_not_publish_canonical_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_raw_source(tmp_path, native_table(["2023-06-15T15:00:00", "2023-06-15T15:00:01"], [10.0, 11.0]))
    output = tmp_path / "published.parquet"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(dense_module, "aggregation_smoke", lambda _: {"5s": "PASS", "30s": "PASS", "1m": "PASS"})
    original = Path.write_text

    def fail_manifest(path: Path, *args, **kwargs):
        if path == manifest:
            raise OSError("simulated manifest failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_manifest)
    with pytest.raises(OSError, match="manifest failure"):
        build_dense("NQ", tmp_path, output, manifest)
    assert not output.exists()
