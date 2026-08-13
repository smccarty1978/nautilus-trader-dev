"""Partition-resume idempotence.

The full build is 60 subprocesses over several hours, so resume correctness is
load-bearing: a partition that is silently accepted when it is stale, truncated,
or from a different code version would corrupt the store in a way no downstream
check attributes back to the build.

These tests drive the supervisor's acceptance predicate directly rather than
running NautilusTrader.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from studies.regime_complete_canonical_store.implementation.run_collect import OUTPUTS
from studies.regime_complete_canonical_store.implementation.run_months import (
    month_windows,
    validated,
)

START = datetime(2025, 3, 1, tzinfo=timezone.utc)
END = datetime(2025, 4, 1, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _partition(tmp_path: Path, status: str = "complete") -> Path:
    directory = tmp_path / "year=2025" / "month=03"
    directory.mkdir(parents=True)
    sha = {}
    for key, name in OUTPUTS.items():
        target = directory / name
        target.write_bytes(f"payload::{key}".encode())
        sha[key] = _sha256(target)
    (directory / "manifest.json").write_text(
        json.dumps({
            "status": status,
            "start": START.isoformat(),
            "end": END.isoformat(),
            "rows": {k: 1 for k in OUTPUTS},
            "sha256": sha,
            "runtime_seconds": 1.0,
            "warmup_flips_skipped": 0,
        })
    )
    return directory


def test_a_complete_partition_is_accepted_without_recollection(tmp_path: Path):
    directory = _partition(tmp_path)
    manifest = validated(directory, START, END)
    assert manifest is not None
    assert manifest["status"] == "complete"


def test_validation_is_idempotent(tmp_path: Path):
    directory = _partition(tmp_path)
    first = validated(directory, START, END)
    second = validated(directory, START, END)
    assert first == second


def test_a_missing_partition_is_rebuilt(tmp_path: Path):
    assert validated(tmp_path / "year=2025" / "month=03", START, END) is None


def test_an_incomplete_partition_is_rebuilt(tmp_path: Path):
    directory = _partition(tmp_path, status="in_progress")
    assert validated(directory, START, END) is None


def test_a_corrupted_payload_is_rejected_not_silently_accepted(tmp_path: Path):
    directory = _partition(tmp_path)
    (directory / OUTPUTS["paths"]).write_bytes(b"truncated")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        validated(directory, START, END)


def test_a_partition_built_for_a_different_window_is_rejected(tmp_path: Path):
    directory = _partition(tmp_path)
    with pytest.raises(RuntimeError, match="window mismatch"):
        validated(directory, START, datetime(2025, 5, 1, tzinfo=timezone.utc))


def test_every_output_is_hash_checked(tmp_path: Path):
    """A resume check that only verified some outputs would accept a partition
    whose other datasets were truncated."""
    for key, name in OUTPUTS.items():
        directory = _partition(tmp_path / key)
        (directory / name).write_bytes(b"corrupted")
        with pytest.raises(RuntimeError, match="hash mismatch"):
            validated(directory, START, END)


# ------------------------------------------------------------------ windows


def test_month_windows_cover_2021_2025_contiguously():
    windows = month_windows((2021, 2022, 2023, 2024, 2025))
    assert len(windows) == 60
    for (_, end), (next_start, _) in zip(windows, windows[1:]):
        assert end == next_start, "windows must abut with no gap or overlap"
    assert windows[0][0] == datetime(2021, 1, 1, tzinfo=timezone.utc)
    assert windows[-1][1] == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_no_window_reaches_into_2026():
    """2026 is reserved for runtime OOS validation."""
    windows = month_windows((2021, 2022, 2023, 2024, 2025))
    sealed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert all(start < sealed for start, _ in windows)
    assert all(end <= sealed for _, end in windows)


def test_shards_partition_the_month_list_exactly():
    windows = month_windows((2021, 2022, 2023, 2024, 2025))
    for shard_count in (1, 2, 3, 4):
        assigned = [
            {i for i in range(len(windows)) if i % shard_count == shard}
            for shard in range(shard_count)
        ]
        union: set[int] = set()
        for shard_set in assigned:
            assert not (union & shard_set), "shards must not overlap"
            union |= shard_set
        assert union == set(range(len(windows))), "shards must cover every month"
