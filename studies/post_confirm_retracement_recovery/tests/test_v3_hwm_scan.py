"""The V3 HWM-exit scanner must be able to FAIL.

`exit_now_hwm` priced at the high-water mark is not a reachable fill -- 61.6% of
the predecessor's headline vanished when it was marked properly. V3 is the gate
that keeps that price out of every economic path, so a V3 that cannot fail is
worse than no V3 at all.

The scan originally matched bare text and so flagged its own comment and its own
regex literal, failing on a package with zero real leaks. Requiring the quotes
fixed that -- these are polars column keys and a real use is always a string
literal -- but a narrower pattern is exactly the kind of change that can quietly
turn a live gate into a tautology. These tests pin both directions.
"""
from __future__ import annotations

import re

import pytest

# The pattern under test, kept byte-identical to validate.py's V3 block.
PATTERN = r"[\"'](exit_now_hwm\w*)[\"']"


def _leaks(src: str) -> list[str]:
    return [m.group(1) for m in re.finditer(PATTERN, src)
            if not m.group(1).endswith("CONTRAST_ONLY")]


@pytest.mark.parametrize("src", [
    'st["exit_now_hwm_atr"] = float(w.run_mfe[j])',
    "row['exit_now_hwm'] = hwm",
    'pl.col("exit_now_hwm_atr").mean()',
    '{"exit_now_hwm_atr_CONTRAST": 1.0}',      # near-miss suffix, still a leak
])
def test_a_real_hwm_exit_reference_is_caught(src):
    assert _leaks(src), f"V3 would not catch a genuine leak: {src!r}"


@pytest.mark.parametrize("src", [
    'st["exit_now_hwm_atr_CONTRAST_ONLY"] = float(w.run_mfe[j])',
    's["exit_now_hwm_atr_CONTRAST_ONLY"].mean()',
])
def test_the_contrast_only_column_is_permitted(src):
    assert not _leaks(src), f"V3 rejects the permitted contrast column: {src!r}"


@pytest.mark.parametrize("src", [
    "# a bare `exit_now_hwm` reference without the suffix is a defect",
    'for m in re.finditer(r"[\\"\']( exit_now_hwm\\w*)[\\"\']", src):',
])
def test_prose_and_scanner_machinery_are_not_flagged(src):
    """The false positive that made V3 fail on a clean package."""
    assert not _leaks(src), f"V3 self-flags on non-economic text: {src!r}"


def test_the_mark_priced_exit_is_never_flagged():
    """`exit_now_mark_atr` is the reachable fill and is the column that SHOULD
    carry the economics. V3 must not touch it."""
    assert not _leaks('s["exit_now_mark_atr"].mean()')


def test_scan_runs_against_the_real_package_and_finds_nothing():
    """End-to-end: the shipped package must be clean under the same pattern."""
    from studies.post_confirm_retracement_recovery.implementation.common import STUDY

    found = []
    for p in sorted((STUDY / "implementation").glob("*.py")):
        found += [f"{p.name}:{n}" for n in _leaks(p.read_text(encoding="utf-8"))]
    assert not found, f"unsuffixed HWM exit references: {found}"
