from __future__ import annotations

import os

from scripts.run_bounded_study import progress_signature


def test_same_size_rewrite_changes_progress_signature(tmp_path):
    progress = tmp_path / "progress.json"
    progress.write_text('{"step": 1}', encoding="utf-8")
    before = progress_signature(progress)

    progress.write_text('{"step": 2}', encoding="utf-8")
    stat_info = progress.stat()
    os.utime(
        progress,
        ns=(stat_info.st_atime_ns, before[0] + 1_000_000),
    )

    after = progress_signature(progress)
    assert after[1] == before[1]
    assert after != before


def test_truncation_changes_progress_signature(tmp_path):
    progress = tmp_path / "progress.json"
    progress.write_text('{"long_step": 100}', encoding="utf-8")
    before = progress_signature(progress)

    progress.write_text("{}", encoding="utf-8")

    assert progress_signature(progress) != before
