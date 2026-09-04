"""Generic analysis operations: the six things the v2 analyze stage could not express.

Each test pins the property that makes the operation trustworthy rather than merely
plausible -- the denominator, the exclusivity, the determinism, the censoring rule.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.analysis.diagnostic_ops import (AnalysisOpError, anchor_first_threshold_crossing, anchored_path,
                                              bucket_decomposition, cell_matched_controls, cumulative_incidence,
                                              precedence_labels, resolve_by, run_op)

NS = 1_000_000_000
BY = {"column": "direction", "cases": {1: {"value": "long_score", "threshold": 0.30, "levels": {"p95": 0.40}},
                                       -1: {"value": "short_score", "threshold": 0.20, "levels": {"p95": 0.35}}}}


def _rows(**over) -> pd.DataFrame:
    base = pd.DataFrame([
        # regime 1 (LONG): below, below, CROSS, above, dips below, above
        {"g": 1, "direction": 1, "t": 10, "long_score": 0.10, "short_score": 0.9, "eligible": True},
        {"g": 1, "direction": 1, "t": 20, "long_score": 0.29, "short_score": 0.9, "eligible": True},
        {"g": 1, "direction": 1, "t": 30, "long_score": 0.31, "short_score": 0.9, "eligible": True},
        {"g": 1, "direction": 1, "t": 40, "long_score": 0.45, "short_score": 0.9, "eligible": True},
        {"g": 1, "direction": 1, "t": 50, "long_score": 0.12, "short_score": 0.9, "eligible": True},
        {"g": 1, "direction": 1, "t": 60, "long_score": 0.33, "short_score": 0.9, "eligible": True},
        # regime 2 (SHORT): never reaches its own threshold
        {"g": 2, "direction": -1, "t": 10, "long_score": 0.9, "short_score": 0.05, "eligible": True},
        {"g": 2, "direction": -1, "t": 20, "long_score": 0.9, "short_score": 0.19, "eligible": True},
    ])
    return base.assign(**over) if over else base


# --------------------------------------------------------------------------- by
def test_by_selector_refuses_a_row_whose_arm_was_never_declared():
    rows = _rows()
    rows.loc[0, "direction"] = 0
    with pytest.raises(AnalysisOpError, match="ANALYSIS_BY_UNMATCHED_ROWS"):
        resolve_by(rows, BY)


def test_by_selector_keys_int_float_and_str_arms_identically():
    rows = _rows()
    for cases in ({1: {"value": "long_score", "threshold": 0.3}, -1: {"value": "short_score", "threshold": 0.2}},
                  {"1": {"value": "long_score", "threshold": 0.3}, "-1": {"value": "short_score", "threshold": 0.2}},
                  {1.0: {"value": "long_score", "threshold": 0.3}, -1.0: {"value": "short_score", "threshold": 0.2}}):
        out = resolve_by(rows, {"column": "direction", "cases": cases})
        assert list(out["_threshold"]) == [0.3] * 6 + [0.2] * 2


# --------------------------------------------------------------------------- A1
def test_anchor_is_the_first_inclusive_crossing_and_one_per_group():
    out = anchor_first_threshold_crossing(_rows(), by=BY, group_by=["g"], order_by="t")
    assert list(out["frame"]["g"]) == [1]
    assert out["frame"]["t"].iloc[0] == 30           # first >= 0.30, not the later 0.45 or the recross
    assert out["payload"]["anchors"] == 1
    assert out["payload"]["groups_total"] == 2       # regime 2 never reaches ITS OWN threshold


def test_anchor_uses_the_per_arm_threshold_not_a_pooled_one():
    """0.29 clears the SHORT threshold but not the LONG one; a pooled threshold would misfire."""
    rows = _rows()
    rows.loc[rows.index[6], "short_score"] = 0.25     # regime 2, t=10: above SHORT's 0.20
    out = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t")
    assert set(out["frame"]["g"]) == {1, 2}
    assert out["payload"]["anchors_by_case"] == {"-1": 1, "1": 1}


def test_eligibility_restricts_which_row_may_anchor_without_dropping_rows():
    """A superset population reproduces a frozen parent's anchor exactly by declaring the
    parent's eligibility as a column: the ineligible rows stay in the frame for the path."""
    rows = _rows()
    rows.loc[rows.index[2], "eligible"] = False       # the real first crossing is not parent-eligible
    out = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t", eligible_column="eligible")
    assert out["frame"]["t"].iloc[0] == 40
    assert out["payload"]["eligible_column"] == "eligible"


# --------------------------------------------------------------------------- A2
def _incidence_rows():
    #                       resolved  duration  observed
    return pd.DataFrame([
        {"k": "fast",      "resolved": True,  "dur": 90.0,  "obs": 90.0,  "arm": "LONG"},
        {"k": "late",      "resolved": True,  "dur": 240.0, "obs": 240.0, "arm": "LONG"},
        {"k": "slow",      "resolved": True,  "dur": 500.0, "obs": 500.0, "arm": "SHORT"},
        {"k": "no_flip",   "resolved": False, "dur": float("nan"), "obs": 900.0, "arm": "SHORT"},
        {"k": "cut_short", "resolved": False, "dur": float("nan"), "obs": 100.0, "arm": "LONG"},
    ])


def test_a_fast_resolver_stays_in_every_longer_horizon_denominator():
    """The censoring trap: a unit that resolved at 90s is observed for only 90s. Requiring
    'observed for at least h' alone would drop it from the 180s denominator and inflate the
    rate at every longer horizon."""
    out = cumulative_incidence(_incidence_rows(), horizons=[60, 180, 300, 600], resolved_column="resolved",
                               duration_column="dur", observed_seconds_column="obs")
    rows = {r["horizon_seconds"]: r for r in out["payload"]["populations"]["pooled"]}
    assert rows[180]["eligible_n"] == 4              # everything except the 100s-observed unit
    assert rows[180]["cumulative_count"] == 1        # the 90s flip
    assert rows[300]["eligible_n"] == 4 and rows[300]["cumulative_count"] == 2
    assert rows[600]["eligible_n"] == 4 and rows[600]["cumulative_count"] == 3
    assert rows[180]["ineligible_right_censored_n"] == 1


def test_increments_sum_to_the_cumulative_count():
    out = cumulative_incidence(_incidence_rows(), horizons=[60, 180, 300, 600], resolved_column="resolved",
                               duration_column="dur", observed_seconds_column="obs")
    rows = [r for r in out["payload"]["populations"]["pooled"] if r["horizon_seconds"] != "observed_end"]
    assert sum(r["increment_count"] for r in rows) == rows[-1]["cumulative_count"]


def test_strata_are_reported_alongside_pooled():
    out = cumulative_incidence(_incidence_rows(), horizons=[300], resolved_column="resolved", duration_column="dur",
                               observed_seconds_column="obs", strata=["arm"])
    assert set(out["payload"]["populations"]) == {"pooled", "arm=LONG", "arm=SHORT"}


def test_non_increasing_horizons_are_refused():
    with pytest.raises(AnalysisOpError, match="ANALYSIS_HORIZONS_INVALID"):
        cumulative_incidence(_incidence_rows(), horizons=[300, 180], resolved_column="resolved",
                             duration_column="dur", observed_seconds_column="obs")


# --------------------------------------------------------------------------- A3
def test_buckets_are_mutually_exclusive_and_exhaustive_with_two_denominators():
    buckets = [{"id": "181_240", "gt": 180, "lte": 240}, {"id": "241_600", "gt": 240, "lte": 600},
               {"id": "persistent_gt_600", "unresolved": True, "min_observed_seconds": 600},
               {"id": "censored", "unresolved": True}]
    out = bucket_decomposition(_incidence_rows(), buckets=buckets, resolved_column="resolved", duration_column="dur",
                               observed_seconds_column="obs", negative_after_seconds=180)
    rows = {r["bucket"]: r for r in out["payload"]["populations"]["pooled"]}
    assert sum(r["n"] for r in rows.values()) == 5           # exhaustive
    assert rows["181_240"]["n"] == 1 and rows["241_600"]["n"] == 1
    assert rows["persistent_gt_600"]["n"] == 1 and rows["censored"]["n"] == 1
    assert rows["UNCLASSIFIED"]["n"] == 1                     # the 90s flip is not a 180s negative bucket
    assert out["payload"]["negative_denominator"] == 4        # everything except the 90s flip
    assert rows["181_240"]["percent_of_negative"] == pytest.approx(0.25)
    assert rows["181_240"]["percent_of_all"] == pytest.approx(0.2)


def test_declaration_order_wins_so_an_earlier_bucket_cannot_be_reclaimed():
    buckets = [{"id": "wide", "gt": 0, "lte": 600}, {"id": "narrow", "gt": 180, "lte": 240}]
    out = bucket_decomposition(_incidence_rows(), buckets=buckets, resolved_column="resolved", duration_column="dur",
                               observed_seconds_column="obs", negative_after_seconds=180)
    rows = {r["bucket"]: r["n"] for r in out["payload"]["populations"]["pooled"]}
    assert rows["wide"] == 3 and rows["narrow"] == 0


# --------------------------------------------------------------------------- A4
def test_controls_are_the_latest_below_threshold_row_strictly_before_the_anchor():
    rows = _rows()
    anchors = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t")["frame"]
    out = cell_matched_controls(rows, anchors=anchors, by=BY, group_by=["g"], strata=["direction"], order_by="t", min_n=1)
    controls = out["frame"]
    assert len(controls) == 2
    long_control = controls[controls.g == 1].iloc[0]
    assert long_control["t"] == 20 and long_control["control_kind"] == "pre_anchor"   # NOT t=50, which is after
    short_control = controls[controls.g == 2].iloc[0]
    assert short_control["t"] == 20 and short_control["control_kind"] == "never_anchored"


def test_a_cell_is_reportable_only_when_both_sides_reach_min_n():
    rows = _rows()
    anchors = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t")["frame"]
    out = cell_matched_controls(rows, anchors=anchors, by=BY, group_by=["g"], strata=["direction"], order_by="t", min_n=30)
    assert {c["status"] for c in out["payload"]["cells"]} == {"INSUFFICIENT"}
    assert out["payload"]["reportable_cells"] == 0
    generous = cell_matched_controls(rows, anchors=anchors, by=BY, group_by=["g"], strata=["direction"], order_by="t", min_n=1)
    ok = [c for c in generous["payload"]["cells"] if c["status"] == "OK"]
    assert [c["cell"] for c in ok] == ["1"]      # LONG has 1 anchor and 1 control; SHORT has 0 anchors


# --------------------------------------------------------------------------- A5
def test_path_reports_offsets_collapse_recross_and_level_reach():
    rows = _rows()
    anchors = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t")["frame"]
    anchors = anchors.assign(terminal=1_000)
    out = anchored_path(rows, anchors=anchors, by=BY, group_by=["g"], order_by="t", offsets=[10, 20, 30],
                        max_offset_seconds=600, terminal_column="terminal", levels=["p95"], time_unit="s")
    row = out["frame"].iloc[0]
    assert row["value_at_10s"] == pytest.approx(0.45)   # t=40
    assert row["value_at_20s"] == pytest.approx(0.12)   # t=50, below threshold
    assert row["value_at_30s"] == pytest.approx(0.33)   # t=60, back above
    assert not row["path_censored"] and row["fell_below"] and row["recrossed"]
    assert row["max_value"] == pytest.approx(0.45)
    assert row["reached_p95"] and row["time_to_p95_seconds"] == 10


def test_a_missing_required_offset_censors_the_path_and_is_never_imputed():
    rows = _rows()
    rows = rows[rows.t != 50]                          # the +20s observation disappears
    anchors = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t")["frame"].assign(terminal=1_000)
    out = anchored_path(rows, anchors=anchors, by=BY, group_by=["g"], order_by="t", offsets=[10, 20, 30],
                        max_offset_seconds=600, terminal_column="terminal", time_unit="s")
    row = out["frame"].iloc[0]
    assert row["path_censored"] and row["missing_offsets"] == [20.0]
    assert row["value_at_20s"] is None


def test_an_offset_past_the_terminal_is_not_required_and_does_not_censor():
    rows = _rows()
    anchors = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t")["frame"].assign(terminal=45)
    out = anchored_path(rows, anchors=anchors, by=BY, group_by=["g"], order_by="t", offsets=[10, 20, 30],
                        max_offset_seconds=600, terminal_column="terminal", time_unit="s")
    row = out["frame"].iloc[0]
    assert row["terminal_offset_seconds"] == 15 and row["required_offsets"] == [10.0]
    assert not row["path_censored"]


# --------------------------------------------------------------------------- A6
RULES = [
    {"label": "CENSORED", "when": [["path_censored", "eq", True]]},
    {"label": "FAST", "when": [["resolved", "eq", True], ["dur", "lte", 180]]},
    {"label": "LATE", "when": [["resolved", "eq", True], ["dur", "lte", 300]]},
    {"label": "SLOW", "when": [["resolved", "eq", True], ["dur", "lte", 600]]},
    {"label": "COLLAPSE", "when": [["resolved", "eq", False], ["fell_below", "eq", True]]},
    {"label": "PERSISTENT_HIGH", "when": []},
]


def test_declaration_order_is_the_precedence_and_a_dominating_rule_cannot_be_reclaimed():
    frame = pd.DataFrame([
        {"path_censored": False, "resolved": True, "dur": 90.0, "fell_below": False},
        {"path_censored": False, "resolved": True, "dur": 240.0, "fell_below": False},
        {"path_censored": False, "resolved": True, "dur": 500.0, "fell_below": True},
        {"path_censored": False, "resolved": False, "dur": float("nan"), "fell_below": True},
        {"path_censored": False, "resolved": False, "dur": float("nan"), "fell_below": False},
        {"path_censored": True, "resolved": True, "dur": 90.0, "fell_below": False},
    ])
    out = precedence_labels(frame, rules=RULES, output_column="subtype")
    assert list(out["frame"]["subtype"]) == ["FAST", "LATE", "SLOW", "COLLAPSE", "PERSISTENT_HIGH", "CENSORED"]
    assert out["payload"]["unclassified"] == 0
    # the censored row WOULD have matched FAST; precedence, not arithmetic, decided it
    matches = {m["label"]: m for m in out["payload"]["rule_matches"]}
    assert matches["FAST"]["matched"] == 1 and matches["FAST"]["would_have_matched"] == 2


def test_unknown_op_and_missing_input_fail_closed():
    with pytest.raises(AnalysisOpError, match="ANALYSIS_OP_UNKNOWN"):
        run_op("analysis.nope", _rows())
    with pytest.raises(AnalysisOpError, match="ANALYSIS_OP_INPUT_MISSING"):
        run_op("analysis.control.cell_matched", _rows(), params={"by": BY, "group_by": ["g"], "strata": [], "order_by": "t"})
    with pytest.raises(AnalysisOpError, match="ANALYSIS_RULE_INVALID"):
        precedence_labels(pd.DataFrame([{"a": 1}]), rules=[{"label": "x", "when": [["a", "wat", 1]]}])
    with pytest.raises(AnalysisOpError, match="ANALYSIS_COLUMN_MISSING"):
        precedence_labels(pd.DataFrame([{"a": 1}]), rules=[{"label": "x", "when": [["nope", "eq", 1]]}])


# --------------------------------------------------------------------------- eligibility
def test_multi_condition_eligibility_restricts_selection_without_dropping_rows():
    """The parent's qualification is three numeric gates plus an age cap, not one boolean.
    Declaring them here reproduces the parent's selection identity from a superset frame."""
    rows = _rows().assign(mfe=[1.5, 1.5, 0.4, 1.5, 1.5, 1.5, 1.5, 1.5], age=[10, 20, 30, 40, 50, 60, 10, 20])
    gates = [["mfe", "gte", 1.0], ["age", "lte", 45]]
    out = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t", eligible_when=gates)
    assert out["frame"]["t"].iloc[0] == 40           # t=30 fails the mfe gate; t=60 fails the age cap
    assert out["payload"]["rows_total"] == 8 and out["payload"]["rows_eligible"] == 5
    assert out["payload"]["eligibility_restricted"] is True

    anchors = out["frame"]
    controls = cell_matched_controls(rows, anchors=anchors, by=BY, group_by=["g"], strata=["direction"],
                                     order_by="t", min_n=1, eligible_when=gates)["frame"]
    assert list(controls[controls.g == 1]["t"]) == [20]   # t=30 is ineligible, t=50 is after the anchor


def test_terminal_reduction_gives_one_observation_horizon_to_every_downstream_statistic():
    rows = _rows().assign(stop_a=[100] * 8, stop_b=[80, 80, 80, 80, 80, 80, 80, 80])
    out = anchor_first_threshold_crossing(rows, by=BY, group_by=["g"], order_by="t",
                                          terminal={"columns": ["stop_a", "stop_b"], "reduce": "min", "unit": "s"})
    assert out["frame"]["terminal_ts"].iloc[0] == 80
    assert out["frame"]["observed_seconds"].iloc[0] == 50      # anchor at t=30
    with pytest.raises(AnalysisOpError, match="ANALYSIS_TERMINAL_BEFORE_ANCHOR"):
        anchor_first_threshold_crossing(rows.assign(stop_b=5), by=BY, group_by=["g"], order_by="t",
                                        terminal={"columns": ["stop_b"], "reduce": "min", "unit": "s"})


def test_eligibility_conditions_fail_closed_on_a_bad_op_or_column():
    for gates, match in (([["mfe", "wat", 1.0]], "ANALYSIS_ELIGIBILITY_INVALID"),
                         ([["nope", "gte", 1.0]], "ANALYSIS_COLUMN_MISSING"),
                         ([["mfe", "gte"]], "ANALYSIS_ELIGIBILITY_INVALID")):
        with pytest.raises(AnalysisOpError, match=match):
            anchor_first_threshold_crossing(_rows().assign(mfe=1.0), by=BY, group_by=["g"], order_by="t",
                                            eligible_when=gates)
