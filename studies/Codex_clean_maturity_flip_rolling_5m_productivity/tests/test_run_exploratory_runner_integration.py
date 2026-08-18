"""End-to-end regression tests for run_exploratory_models.run().

Contract Pass 16 left two findings unverified because prior tests only
exercised the runner's internal helpers (_assert_structural_coverage,
authorize_stage) in isolation: (1) the structural_coverage.json marker's
on-disk persistence after a full A/B/C fit+score pass, and (2) the
runner's own refusal paths when a persisted partition manifest disagrees
with the authenticated phase-zero lineage or when phase-zero itself is
stale. These tests build a minimal deterministic synthetic fixture and
drive run() itself, not its internals, to close that gap.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation import phase0
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector import (
    BASELINE_CANDIDATES, ROLLING_FEATURES, STRUCTURAL_FEATURES,
)
from studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.run_exploratory_models import run

NS = 1_000_000_000
PRIMARY_BUCKETS = (("300-600s", 450.0), ("600-900s", 750.0), ("900-1800s", 1200.0))
ROWS_PER_TRAIN_CELL = 12
ROWS_PER_OOS_CELL = 10


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rth_base_ns(year: int) -> int:
    # 16:00 UTC == 10:00 America/Chicago (CST) in February -> well inside
    # the frozen [08:30, 15:00) RTH window and clear of any DST boundary.
    dt = datetime(year, 2, 2, 16, 0, 0, tzinfo=timezone.utc)
    return int(dt.timestamp()) * NS


def _synthetic_frame(year: int, rows_per_cell: int, rng: np.random.Generator, counter: itertools.count) -> pl.DataFrame:
    base_ns = _rth_base_ns(year)
    records: list[dict] = []
    for direction in (1, -1):
        for bucket, age in PRIMARY_BUCKETS:
            for _ in range(rows_per_cell):
                offset = next(counter)
                row = {
                    "checkpoint_decision_ns": base_ns + offset * 5 * NS,
                    "regime_start_ns": base_ns + offset * 5 * NS - int(age * NS),
                    "prevailing_direction": direction,
                    "regime_age_seconds": age,
                    "running_mfe_atr": 1.5,
                    "new_progress_windows": 3,
                    "retained_mfe_ratio": 0.7,
                    "flip_within_300s": int(rng.integers(0, 2)),
                    "structural_available": True,
                }
                for name in (*BASELINE_CANDIDATES, *STRUCTURAL_FEATURES, *ROLLING_FEATURES):
                    row[name] = float(rng.uniform(0.0, 1.0))
                records.append(row)
    return pl.DataFrame(records)


def _write_partition(directory: Path, year: int, frame: pl.DataFrame, phase0_sha: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    features_path = directory / "features.parquet"
    frame.write_parquet(features_path)
    manifest = {
        "start": datetime(year, 1, 1, tzinfo=timezone.utc).isoformat(),
        "end": datetime(year + 1, 1, 1, tzinfo=timezone.utc).isoformat(),
        "phase0_sha256": phase0_sha,
        "features_sha256": _sha(features_path),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))


def _build_fixture(tmp_path: Path) -> tuple[list[Path], list[Path], str, Path]:
    phase0_path = tmp_path / "2021" / "phase0_source_manifest.json"
    phase0.write_manifest(phase0_path)
    phase0_sha = _sha(phase0_path)

    rng = np.random.default_rng(1234)
    counter = itertools.count()
    train_dirs = []
    for year in (2021, 2022, 2023):
        directory = tmp_path / str(year)
        frame = _synthetic_frame(year, ROWS_PER_TRAIN_CELL, rng, counter)
        _write_partition(directory, year, frame, phase0_sha)
        train_dirs.append(directory)

    oos_counter = itertools.count()
    oos_dir = tmp_path / "2024"
    oos_frame = _synthetic_frame(2024, ROWS_PER_OOS_CELL, rng, oos_counter)
    _write_partition(oos_dir, 2024, oos_frame, phase0_sha)

    return train_dirs, [oos_dir], phase0_sha, phase0_path


def test_run_persists_structural_coverage_marker_on_disk(tmp_path):
    train_dirs, oos_dirs, _, _ = _build_fixture(tmp_path)
    output_dir = tmp_path / "output"

    summary = run(train_dirs, oos_dirs, output_dir)

    marker_path = output_dir / "structural_coverage.json"
    assert marker_path.is_file(), "run() must persist structural_coverage.json, not just return it in memory"
    persisted = json.loads(marker_path.read_text())
    assert persisted["mode"] == "EXPLORATORY — CONTRACT GATE BLOCKED"
    assert persisted["minimum_required_coverage"] == pytest.approx(0.90)
    cells = persisted["cells"]
    # 2 directions x 3 buckets x {TRAIN, OOS} = 12 coverage cells; every
    # cell is 100% available by fixture construction.
    assert len(cells) == 12
    assert all(cell["coverage"] == pytest.approx(1.0) for cell in cells)
    assert {cell["split"] for cell in cells} == {"TRAIN_2021_2023", "OOS_2024"}
    assert summary["directional_cells"] > 0


def test_run_refuses_when_oos_partition_lineage_diverges_from_train_phase0(tmp_path):
    train_dirs, oos_dirs, _, _ = _build_fixture(tmp_path)
    oos_manifest_path = oos_dirs[0] / "manifest.json"
    manifest = json.loads(oos_manifest_path.read_text())
    manifest["phase0_sha256"] = "0" * 64
    oos_manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(RuntimeError, match="different phase-zero lineage"):
        run(train_dirs, oos_dirs, tmp_path / "output")


def test_run_refuses_when_phase0_manifest_is_stale_or_altered(tmp_path):
    train_dirs, oos_dirs, _, phase0_path = _build_fixture(tmp_path)
    # Corrupt the authenticated phase-zero manifest itself; authorize_stage
    # inside run() must refuse before any collection/freeze/fit touches data.
    phase0_path.write_text("{}")

    with pytest.raises(RuntimeError, match="stale or altered"):
        run(train_dirs, oos_dirs, tmp_path / "output")
