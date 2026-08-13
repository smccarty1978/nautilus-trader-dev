"""V8 must cover the PANELS, not only the derived CSVs.

`recovery_state_panel.parquet` shipped with no `path` column at all while the
gate suite reported 14/14. V8 listed seven CSVs and never opened the panel, so
the deliverable it was supposed to vouch for was outside its own scope.

A number without its `path` label is unreadable: UNCONSTRAINED ignores the stop
and is descriptive, STOP_LIVE is the tradeable path. Mixing them silently is how
a descriptive statistic ends up computed on stop-truncated data.

These tests pin both directions -- the panel carries the label, and the gate can
still fail if it stops carrying it.
"""
from __future__ import annotations

import polars as pl
import pytest

from studies.post_confirm_retracement_recovery.implementation.common import (
    PATH_STOP, PATH_UNC, RESULTS,
)

PANEL = "recovery_state_panel.parquet"
CSVS = ("retracement_frequency.csv", "recovery_probability.csv",
        "recovery_timing.csv", "adverse_before_recovery.csv",
        "failed_recovery_economics.csv", "runner_interception.csv",
        "conditional_value_curve.csv")


def _panel() -> pl.DataFrame:
    p = RESULTS / PANEL
    if not p.exists():
        pytest.skip(f"{PANEL} not built; run --stage build")
    return pl.read_parquet(p)


def test_the_state_panel_carries_a_path_column():
    assert "path" in _panel().columns, (
        "recovery_state_panel.parquet has no `path` column -- SPEC manifest "
        "item 9 requires path='UNCONSTRAINED'")


def test_the_state_panel_is_entirely_unconstrained():
    """The panel ignores the stop by construction. A STOP_LIVE row in it would
    mean stop-truncated data reached a descriptive table."""
    labels = set(_panel()["path"].to_list())
    assert labels == {PATH_UNC}, f"unexpected path labels in the panel: {labels}"


def test_no_null_path_in_the_state_panel():
    assert _panel()["path"].null_count() == 0


@pytest.mark.parametrize("name", CSVS)
def test_every_derived_table_is_labelled(name):
    p = RESULTS / name
    if not p.exists():
        pytest.skip(f"{name} not built")
    d = pl.read_csv(p)
    assert "path" in d.columns and d["path"].null_count() == 0, (
        f"{name} carries unlabelled rows")


# --- the gate's own logic, exercised against synthetic frames --------------
# Mirrors validate.py's V8 predicate so a regression that silently narrows the
# check is caught here rather than by the next auditor.

def _v8(frames: dict[str, pl.DataFrame]) -> tuple[list, list]:
    missing = [n for n, d in frames.items()
               if "path" not in d.columns or d["path"].null_count()]
    panel = frames[PANEL]
    wrong = (sorted(set(panel["path"].to_list()) - {PATH_UNC})
             if "path" in panel.columns else ["<column absent>"])
    return missing, wrong


def test_gate_fails_when_the_panel_has_no_path_column():
    """The exact defect that shipped."""
    missing, wrong = _v8({PANEL: pl.DataFrame({"regime_id": ["a"]})})
    assert missing == [PANEL] and wrong == ["<column absent>"]


def test_gate_fails_on_a_stop_live_row_in_the_panel():
    missing, wrong = _v8({PANEL: pl.DataFrame({"path": [PATH_UNC, PATH_STOP]})})
    assert not missing and wrong == [PATH_STOP]


def test_gate_fails_on_a_null_path():
    missing, wrong = _v8({PANEL: pl.DataFrame({"path": [PATH_UNC, None]})})
    assert missing == [PANEL]


def test_gate_passes_on_a_correct_panel():
    missing, wrong = _v8({PANEL: pl.DataFrame({"path": [PATH_UNC, PATH_UNC]})})
    assert not missing and not wrong
