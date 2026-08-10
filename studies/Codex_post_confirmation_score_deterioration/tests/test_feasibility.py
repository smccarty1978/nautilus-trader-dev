import polars as pl

from studies.Codex_post_confirmation_score_deterioration.implementation.feasibility import (
    MIN_OBS,
    _group_coverage,
)


def test_coverage_requires_three_actual_dispatches() -> None:
    frame = pl.DataFrame({
        "terminal_label_full": ["FAIL", "FAIL", "WIN"],
        "n_obs": [0, MIN_OBS, MIN_OBS + 1],
        "first_delay_s": [None, 10.0, 5.0],
    })
    rows = _group_coverage(frame, ["terminal_label_full"])
    fail = next(row for row in rows if row["terminal_label_full"] == "FAIL")
    assert fail["trades"] == 2
    assert fail["trades_with_ge3_obs"] == 1
    assert fail["pct_with_ge3_obs"] == 50.0
