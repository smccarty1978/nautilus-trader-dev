"""Generic analysis operations: the six things the v2 analyze stage could not express.

Each test pins the property that makes the operation trustworthy rather than merely
plausible -- the denominator, the exclusivity, the determinism, the censoring rule.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.analysis.diagnostic_ops import (AnalysisOpError, anchor_first_threshold_crossing, anchored_path,
                                              arm_delta_integrity_gate, bucket_decomposition, cell_matched_controls,
                                              cumulative_incidence, population_parity_gate, precedence_labels,
                                              resolve_by, run_op, tail_lift)

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


# --------------------------------------------------------------------------- A7 (stop gate)
def _reference(tmp_path):
    """A frozen reference in its OWN vocabulary: LONG/SHORT, and its own key/timestamp names."""
    import hashlib
    ref = pd.DataFrame([{"direction": "LONG", "regime_id": 1, "ref_ts": 100},
                        {"direction": "SHORT", "regime_id": 2, "ref_ts": 200},
                        {"direction": "SHORT", "regime_id": 3, "ref_ts": 300}])
    path = tmp_path / "ref.parquet"
    ref.to_parquet(path, index=False)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _population(**over):
    rows = pd.DataFrame([{"regime_start_ns": 1, "regime_direction": 1, "observation_ts": 100},
                         {"regime_start_ns": 2, "regime_direction": -1, "observation_ts": 200},
                         {"regime_start_ns": 3, "regime_direction": -1, "observation_ts": 300}])
    return rows.assign(**over) if over else rows


def _gate(tmp_path, rows, **over):
    path, sha = _reference(tmp_path)
    params = {"reference_path": path.name, "reference_sha256": sha,
              "key": ["regime_start_ns"], "reference_key": ["regime_id"],
              "expected_total": 3, "expected_by": {"regime_direction": {1: 1, -1: 2}},
              "timestamp_column": "observation_ts", "reference_timestamp_column": "ref_ts",
              "value_map": {"direction": {"LONG": 1, "SHORT": -1}},
              "context": {"studies_root": str(tmp_path)}}
    params.update(over)
    return population_parity_gate(rows, **params)


def test_a_matching_population_passes_the_gate_and_reports_its_evidence(tmp_path):
    out = _gate(tmp_path, _population())
    assert out["payload"]["status"] == "PASS" and out["payload"]["failures"] == []
    assert out["payload"]["population_rows"] == 3 and out["payload"]["reference_rows"] == 3
    assert len(out["frame"]) == 3            # the gate passes the population through untouched


def test_the_gate_raises_on_a_missing_row_a_extra_row_and_a_moved_timestamp(tmp_path):
    with pytest.raises(AnalysisOpError, match="reference key\\(s\\) absent"):
        _gate(tmp_path, _population().iloc[:2])
    extra = pd.concat([_population(),
                       pd.DataFrame([{"regime_start_ns": 9, "regime_direction": -1, "observation_ts": 900}])],
                      ignore_index=True)
    with pytest.raises(AnalysisOpError, match="unexpected key"):
        _gate(tmp_path, extra, expected_total=4, expected_by={"regime_direction": {1: 1, -1: 3}})
    moved = _population()
    moved.loc[1, "observation_ts"] = 999
    with pytest.raises(AnalysisOpError, match="different instant"):
        _gate(tmp_path, moved)


def test_the_gate_raises_when_the_declared_counts_do_not_hold(tmp_path):
    with pytest.raises(AnalysisOpError, match="expected 4"):
        _gate(tmp_path, _population(), expected_total=4)
    flipped = _population()
    flipped.loc[0, "regime_direction"] = -1
    with pytest.raises(AnalysisOpError, match="counts"):
        _gate(tmp_path, flipped)


def test_the_reference_itself_cannot_drift(tmp_path):
    """A frozen comparison whose own bytes are unpinned is not frozen."""
    with pytest.raises(AnalysisOpError, match="REFERENCE_SHA_MISMATCH"):
        _gate(tmp_path, _population(), reference_sha256="0" * 64)
    with pytest.raises(AnalysisOpError, match="REFERENCE_MISSING"):
        _gate(tmp_path, _population(), reference_path="nope.parquet")


def test_an_unmapped_reference_value_is_refused_rather_than_dropped(tmp_path):
    with pytest.raises(AnalysisOpError, match="VALUE_MAP_UNMATCHED"):
        _gate(tmp_path, _population(), value_map={"direction": {"LONG": 1}})


def test_run_op_supplies_the_gate_its_resolution_context(tmp_path):
    path, sha = _reference(tmp_path)
    out = run_op("analysis.gate.population_parity", _population(),
                 params={"reference_path": path.name, "reference_sha256": sha,
                         "key": ["regime_start_ns"], "reference_key": ["regime_id"],
                         "expected_total": 3},
                 context={"studies_root": str(tmp_path)})
    assert out["payload"]["status"] == "PASS"


# --------------------------------------------------- A7b: predeclared parity exceptions
# A parity gate with no escape hatch is unusable across a dataset migration: the reference
# and the population can differ for a reason that is KNOWN and is not drift (a source catalog
# with no bars for a session date, a calendar that genuinely differs). The escape hatch has to
# be narrow enough that it cannot become a way to make an inconvenient disagreement disappear.
NS = 10 ** 9
_D1 = int(pd.Timestamp("2024-01-02", tz="UTC").value)
_D2 = int(pd.Timestamp("2024-12-31", tz="UTC").value)


def _dated_reference(tmp_path):
    import hashlib
    ref = pd.DataFrame([{"regime_id": 1, "ref_ts": _D1}, {"regime_id": 2, "ref_ts": _D1 + NS}])
    path = tmp_path / "dated_ref.parquet"
    ref.to_parquet(path, index=False)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _dated_gate(tmp_path, rows, **over):
    path, sha = _dated_reference(tmp_path)
    params = {"reference_path": path.name, "reference_sha256": sha,
              "key": ["regime_start_ns"], "reference_key": ["regime_id"],
              "timestamp_column": "observation_ts", "reference_timestamp_column": "ref_ts",
              "context": {"studies_root": str(tmp_path)}}
    params.update(over)
    return population_parity_gate(rows, **params)


def _dated_population(extra_on_excepted_day=0, drop_compared=0):
    rows = [{"regime_start_ns": 1, "observation_ts": _D1},
            {"regime_start_ns": 2, "observation_ts": _D1 + NS}]
    rows = rows[: len(rows) - drop_compared] if drop_compared else rows
    rows += [{"regime_start_ns": 100 + i, "observation_ts": _D2 + i * NS}
             for i in range(extra_on_excepted_day)]
    return pd.DataFrame(rows)


_EXCEPT = [{"date": "2024-12-31", "reason": "parent source catalog carries no 1s bars for this session"}]


def test_an_undeclared_extra_session_day_blocks(tmp_path):
    with pytest.raises(AnalysisOpError, match="ANALYSIS_POPULATION_PARITY_FAILED"):
        _dated_gate(tmp_path, _dated_population(extra_on_excepted_day=2))


def test_a_declared_session_date_exception_is_allowed_and_reported(tmp_path):
    out = _dated_gate(tmp_path, _dated_population(extra_on_excepted_day=2),
                      excluded_session_dates=_EXCEPT)
    p = out["payload"]
    assert p["status"] == "PASS"
    assert p["excluded_session_dates"] == [
        {"date": "2024-12-31", "reason": _EXCEPT[0]["reason"],
         "removed_from_population": 2, "removed_from_reference": 0}]
    assert p["compared_after_exclusions"] == {"population": 2, "reference": 2}


def test_an_exception_cannot_mask_a_difference_on_a_COMPARED_day(tmp_path):
    """The property that makes the hatch narrow: excluding 2024-12-31 must not excuse a row
    missing on 2024-01-02. Exclusions remove whole session dates, never individual keys."""
    with pytest.raises(AnalysisOpError, match="ANALYSIS_POPULATION_PARITY_FAILED"):
        _dated_gate(tmp_path, _dated_population(extra_on_excepted_day=2, drop_compared=1),
                    excluded_session_dates=_EXCEPT)


def test_a_stale_exception_that_removes_nothing_fails_closed(tmp_path):
    """A declaration that no longer describes reality is a defect, not a harmless leftover."""
    with pytest.raises(AnalysisOpError, match="ANALYSIS_PARITY_EXCLUSION_DEAD"):
        _dated_gate(tmp_path, _dated_population(), excluded_session_dates=_EXCEPT)


def test_an_exception_without_a_reason_is_refused(tmp_path):
    with pytest.raises(AnalysisOpError, match="ANALYSIS_PARITY_EXCLUSION_UNREASONED"):
        _dated_gate(tmp_path, _dated_population(extra_on_excepted_day=1),
                    excluded_session_dates=[{"date": "2024-12-31"}])


def test_exceptions_require_timestamp_columns_to_derive_a_session_date(tmp_path):
    with pytest.raises(AnalysisOpError, match="ANALYSIS_PARITY_EXCLUSION_NEEDS_TIMESTAMPS"):
        _dated_gate(tmp_path, _dated_population(extra_on_excepted_day=1),
                    timestamp_column=None, reference_timestamp_column=None,
                    excluded_session_dates=_EXCEPT)


# --------------------------------------------------------------- arm-delta integrity gate
# The gate exists to make one specific negative result trustworthy: "the added family carries
# no information". A degenerate added block produces the SAME reading, so each test below pins
# one way the block can be dead while the arm still looks like a legitimate comparison.

class _WeightedProba:
    """Deterministic, picklable stand-in for a fitted estimator.

    A fixed linear score over declared columns with declared weights, so a test decides exactly
    whether an added column changes the model's predictions -- a real fit would only make that
    approximately true.
    """

    def __init__(self, weights):
        self.weights = dict(weights)

    def predict_proba(self, X):
        import numpy as np
        z = np.zeros(len(X), dtype=float)
        for column, w in self.weights.items():
            z = z + float(w) * pd.to_numeric(X[column], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        p = 1.0 / (1.0 + np.exp(-z))
        return np.column_stack([1.0 - p, p])


_TS = pd.Timestamp("2024-06-03T14:30:00Z").value


def _arm_frame(**over) -> pd.DataFrame:
    """4 LONG + 4 SHORT binary rows in 2024, plus one censored (label 2) row per direction."""
    rows = []
    for i, direction in enumerate([1] * 5 + [-1] * 5):
        k = i % 5
        rows.append({"observation_ts": _TS + i * NS, "direction": direction,
                     "y": 2 if k == 4 else k % 2, "f1": 0.1 * (i + 1), "f2": 1.0 - 0.05 * i,
                     "f3": 0.5 + 0.25 * k})
    return pd.DataFrame(rows).assign(**over) if over else pd.DataFrame(rows)


def _store(tmp_path, model_id: str, weights, inputs):
    from research_workflow.model_store import ModelLineage, store_model
    lineage = ModelLineage(study_id="s1", cell_id=None, direction=None, target_arm=None, fold_id="final",
                           config_id="C00", seed=42, ordered_inputs=list(inputs), feature_contract_sha256=None,
                           preprocessing_contract_sha256="identity", target_contract_sha256=None,
                           target_frame_identity=None, training_population_identity=None, family="sklearn")
    store_model(model_id=model_id, estimator=_WeightedProba(weights), lineage=lineage, tier="registry",
                selection_status="selected", metrics={}, golden_train_frame=None,
                model_root=tmp_path / "models")


def _fitted_study(tmp_path, arms, *, cells=(("LONG", 1), ("SHORT", -1)), final_fit_rows=4, write_manifest=True):
    """A study directory whose fit stage has already run: compiled plan + fitted arms + model store.

    ``arms`` is ``[(arm_id, is_baseline, features, weights)]``, fit once per cell.
    """
    import json
    study = tmp_path / "studies" / "s1"
    (study / "artifacts").mkdir(parents=True, exist_ok=True)
    (study / "compiled_plan.json").write_text(json.dumps({
        "model": {"cells": [{"id": cid, "subset": {"direction": value}} for cid, value in cells]},
        "outcome": {"label_column": "y"}}), encoding="utf-8")
    models = []
    for cell_id, _ in cells:
        for arm, baseline, features, weights in arms:
            model_id = f"m_{arm}_{cell_id}"
            _store(tmp_path, model_id, weights, features)
            models.append({"arm": arm, "cell": cell_id, "baseline_arm": baseline, "model_id": model_id,
                           "features": list(features), "n_features": len(features),
                           "final_fit_rows": final_fit_rows, "direction": cell_id.lower()})
    if write_manifest:
        (study / "artifacts" / "experiment_models.json").write_text(json.dumps({
            "schema_version": 3, "label_column": "y", "tuning_years": [2024], "models": models}), encoding="utf-8")
    return study


_LIVE = [("A", True, ["f1", "f2"], {"f1": 1.0, "f2": -1.0}),
         ("B", False, ["f1", "f2", "f3"], {"f1": 1.0, "f2": -1.0, "f3": 0.75})]


def _integrity(tmp_path, rows, arms=None, *, study=None, **over):
    study = study or _fitted_study(tmp_path, arms if arms is not None else _LIVE)
    params = {"baseline_arm": "A", "scope": "per_cell", "min_non_null_rate": 0.95,
              "require_positive_variance": True, "require_distinct_fit_identity": True,
              "require_distinct_predictions": True,
              "context": {"studies_root": str(tmp_path / "studies"), "study_dir": str(study),
                          "model_root": str(tmp_path / "models")}}
    params.update(over)
    return arm_delta_integrity_gate(rows, **params)


def test_a_live_added_block_passes_the_gate_and_reports_its_evidence(tmp_path):
    out = _integrity(tmp_path, _arm_frame())
    payload = out["payload"]
    assert payload["status"] == "PASS" and payload["failures"] == []
    assert len(out["frame"]) == 10                       # a gate passes its population through untouched
    assert payload["population"]["binary_rows_in_tuning_years"] == 8    # the label-2 rows are not fitted rows
    assert [c["cell"] for c in payload["cells"]] == ["LONG", "SHORT"]
    assert all(c["rebuilt_fitted_rows"] == 4 and c["population_reconciled"] for c in payload["cells"])
    arms = {(a["arm"], a["cell"]): a for a in payload["arms"]}
    assert set(arms) == {("B", "LONG"), ("B", "SHORT")}   # the baseline arm is never checked against itself
    assert arms[("B", "LONG")]["added_block"] == ["f3"] and arms[("B", "LONG")]["removed_from_baseline"] == []
    assert arms[("B", "LONG")]["fit_identity_distinct"] and arms[("B", "LONG")]["predictions"]["distinct"]
    assert arms[("B", "LONG")]["columns"][0]["non_null_rate"] == 1.0


def test_a_mostly_null_added_block_is_refused(tmp_path):
    rows = _arm_frame()
    rows.loc[rows.index[:3], "f3"] = None                # 1 of the 4 fitted LONG rows still carries a value
    with pytest.raises(AnalysisOpError, match="added column 'f3' is populated on"):
        _integrity(tmp_path, rows)


def test_a_constant_added_block_is_refused(tmp_path):
    """An all-null column is what check_feature_surface refuses; a CONSTANT one it accepts."""
    with pytest.raises(AnalysisOpError, match="added column 'f3' is CONSTANT"):
        _integrity(tmp_path, _arm_frame(f3=0.5))


def test_a_block_that_is_dead_in_one_cell_only_is_refused_for_that_cell(tmp_path):
    """LONG and SHORT are fit separately, so a per-cell gate is the only one that can see this."""
    rows = _arm_frame()
    rows.loc[rows["direction"] == -1, "f3"] = 0.5
    with pytest.raises(AnalysisOpError, match="arm 'B' cell 'SHORT': added column 'f3' is CONSTANT"):
        _integrity(tmp_path, rows)


def test_an_added_block_the_fitted_model_ignored_is_refused(tmp_path):
    """The block is present and varying; the model simply never used it. Only predictions show this."""
    arms = [("A", True, ["f1", "f2"], {"f1": 1.0, "f2": -1.0}),
            ("B", False, ["f1", "f2", "f3"], {"f1": 1.0, "f2": -1.0, "f3": 0.0})]
    with pytest.raises(AnalysisOpError, match="predictions on the fitted population do not diverge"):
        _integrity(tmp_path, _arm_frame(), arms)


def test_predictions_that_barely_diverge_are_refused_when_a_minimum_is_declared(tmp_path):
    arms = [("A", True, ["f1", "f2"], {"f1": 1.0, "f2": -1.0}),
            ("B", False, ["f1", "f2", "f3"], {"f1": 1.0, "f2": -1.0, "f3": 1e-9})]
    assert _integrity(tmp_path, _arm_frame(), arms)["payload"]["status"] == "PASS"
    with pytest.raises(AnalysisOpError, match="do not diverge"):
        _integrity(tmp_path, _arm_frame(), arms, min_prediction_divergence=1e-3)


def test_an_empty_added_block_is_refused(tmp_path):
    """An arm whose columns are the baseline's is the baseline; there is no delta to vouch for."""
    arms = [("A", True, ["f1", "f2"], {"f1": 1.0, "f2": -1.0}),
            ("B", False, ["f1", "f2"], {"f1": 2.0, "f2": -1.0})]
    with pytest.raises(AnalysisOpError, match="the added block is EMPTY"):
        _integrity(tmp_path, _arm_frame(), arms)


def test_a_missing_baseline_arm_is_refused(tmp_path):
    with pytest.raises(AnalysisOpError, match="no model for the declared baseline arm 'A_MISSING'"):
        _integrity(tmp_path, _arm_frame(), baseline_arm="A_MISSING")


def test_the_gate_refuses_a_population_it_cannot_reproduce(tmp_path):
    """A gate that derives its own scope cannot detect scope loss: reconcile against the fit stage."""
    study = _fitted_study(tmp_path, _LIVE, final_fit_rows=99)
    with pytest.raises(AnalysisOpError, match="cannot vouch for a population it cannot reproduce"):
        _integrity(tmp_path, _arm_frame(), study=study)


def test_the_gate_refuses_an_empty_fitted_population(tmp_path):
    rows = _arm_frame()
    rows["y"] = 2                                        # every row censored: nothing was fitted
    with pytest.raises(AnalysisOpError, match="rebuilds an EMPTY fitted population"):
        _integrity(tmp_path, rows)


def test_the_gate_fails_closed_when_the_fit_stage_left_no_manifest(tmp_path):
    study = _fitted_study(tmp_path, _LIVE, write_manifest=False)
    with pytest.raises(AnalysisOpError, match="ANALYSIS_ARM_INTEGRITY_MODELS_MISSING"):
        _integrity(tmp_path, _arm_frame(), study=study)


def test_the_gate_fails_closed_when_it_cannot_resolve_its_own_study(tmp_path):
    _fitted_study(tmp_path, _LIVE)
    with pytest.raises(AnalysisOpError, match="ANALYSIS_ARM_INTEGRITY_STUDY_UNRESOLVED"):
        arm_delta_integrity_gate(_arm_frame(), baseline_arm="A", context={"studies_root": str(tmp_path / "studies")})


def test_a_declared_manifest_path_resolves_against_studies_root(tmp_path):
    """The escape hatch for an execution context that carries no study_dir."""
    study = _fitted_study(tmp_path, _LIVE)
    out = _integrity(tmp_path, _arm_frame(), study=study, models_manifest="s1/artifacts/experiment_models.json",
                     context={"studies_root": str(tmp_path / "studies"), "model_root": str(tmp_path / "models")})
    assert out["payload"]["status"] == "PASS"


def test_an_unknown_scope_is_refused(tmp_path):
    with pytest.raises(AnalysisOpError, match="ANALYSIS_ARM_INTEGRITY_SCOPE_UNKNOWN"):
        _integrity(tmp_path, _arm_frame(), scope="per_arm")


def test_a_disabled_property_is_measured_and_reported_but_not_enforced(tmp_path):
    """Every property is reported whether or not it is enforced -- a study states what it verified."""
    out = _integrity(tmp_path, _arm_frame(f3=0.5), require_positive_variance=False)
    column = out["payload"]["arms"][0]["columns"][0]
    assert out["payload"]["status"] == "PASS"
    assert column["populated"] and not column["has_variance"] and column["n_unique"] == 1
    assert out["payload"]["thresholds"]["require_positive_variance"] is False


def test_run_op_dispatches_the_gate_with_its_execution_context(tmp_path):
    study = _fitted_study(tmp_path, _LIVE)
    out = run_op("analysis.gate.arm_delta_integrity", _arm_frame(),
                 params={"baseline_arm": "A"},
                 context={"studies_root": str(tmp_path / "studies"), "study_dir": str(study),
                          "model_root": str(tmp_path / "models")})
    assert out["payload"]["status"] == "PASS" and out["payload"]["baseline_arm"] == "A"


# --------------------------------------------------------------------------- tail_lift
def _scored(n: int, seed: int, *, direction: int = 1, hit_above: float = 0.7) -> pd.DataFrame:
    import random
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        sc = rng.random()
        rows.append({"direction": direction, "score": sc, "hit": 1 if (sc > hit_above and rng.random() < 0.8) or rng.random() < 0.1 else 0})
    return pd.DataFrame(rows)


def test_tail_lift_thresholds_come_from_the_reference_not_the_evaluated_rows():
    ref = pd.DataFrame({"score": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], "hit": 0})
    rows = pd.DataFrame({"score": [0.05, 0.06, 0.07, 0.08, 0.95, 0.96], "hit": [0, 0, 0, 1, 1, 1]})
    out = tail_lift(rows, reference=ref, score="score", label="hit", quantiles=[0.9])
    cell = out["payload"]["cells"][0]
    assert cell["threshold"] == 1.0                      # 90th percentile of the REFERENCE with interpolation=higher
    assert cell["n_tail"] == 0 and cell["lift"] is None  # none of the rows reach it; an in-sample threshold would have
    in_sample = tail_lift(rows, reference=rows, score="score", label="hit", quantiles=[0.9])["payload"]["cells"][0]
    assert in_sample["threshold"] == 0.96 and in_sample["n_tail"] == 1


def test_tail_lift_arithmetic_and_interpolation_pin():
    ref = pd.DataFrame({"score": [i / 100 for i in range(100)]})
    rows = pd.DataFrame({"score": [0.10, 0.50, 0.91, 0.92, 0.95, 0.99], "hit": [0, 0, 1, 0, 1, 1]})
    out = tail_lift(rows, reference=ref, score="score", label="hit", quantiles=[0.9, 0.95])
    c90, c95 = out["payload"]["cells"]
    assert c90["threshold"] == 0.90 and c90["n_tail"] == 4 and c90["tail_rate"] == 0.75 and c90["base_rate"] == 0.5 and c90["lift"] == 1.5
    assert c95["threshold"] == 0.95 and c95["n_tail"] == 2 and c95["tail_rate"] == 1.0 and c95["lift"] == 2.0
    assert c90["tail_share"] <= 0.1 + 1e-9 or c90["n_rows"] < 10   # 'higher' never over-fills the tail on the reference itself
    ref_self = tail_lift(ref.assign(hit=0), reference=ref, score="score", label="hit", quantiles=[0.9])["payload"]["cells"][0]
    assert ref_self["tail_share"] <= 0.10 + 1e-9
    assert list(out["frame"].columns) == ["group", "quantile", "threshold", "n_reference", "n_rows", "n_tail", "tail_share", "base_rate", "tail_rate", "lift"]


def test_tail_lift_excludes_and_counts_null_scores_and_censored_labels():
    ref = pd.DataFrame({"score": [0.1, 0.5, None, 0.9]})
    rows = pd.DataFrame({"score": [0.95, None, 0.96, 0.2], "hit": [1, 1, None, 0]})
    out = tail_lift(rows, reference=ref, score="score", label="hit", quantiles=[0.5])
    assert out["payload"]["excluded"] == {"rows_null_score": 1, "rows_non_binary_label": 1, "reference_null_score": 1}
    assert out["payload"]["cells"][0]["n_rows"] == 2 and out["payload"]["cells"][0]["n_reference"] == 3


def test_tail_lift_groups_use_their_own_reference_and_refuse_a_missing_group():
    ref = pd.concat([pd.DataFrame({"direction": 1, "score": [0.1, 0.2, 0.3, 0.4]}), pd.DataFrame({"direction": -1, "score": [0.6, 0.7, 0.8, 0.9]})])
    rows = pd.DataFrame({"direction": [1, 1, -1, -1], "score": [0.35, 0.05, 0.85, 0.65], "hit": [1, 0, 1, 0]})
    out = tail_lift(rows, reference=ref, score="score", label="hit", quantiles=[0.5], group_by="direction")
    by_group = {c["group"]: c for c in out["payload"]["cells"]}
    assert by_group[1]["threshold"] == 0.3 and by_group[-1]["threshold"] == 0.8
    assert by_group[1]["n_tail"] == 1 and by_group[-1]["n_tail"] == 1
    with pytest.raises(AnalysisOpError, match="ANALYSIS_TAIL_LIFT_REFERENCE_EMPTY"):
        tail_lift(rows.assign(direction=[1, 1, 2, 2]), reference=ref, score="score", label="hit", quantiles=[0.5], group_by="direction")


def test_tail_lift_is_registered_requires_its_reference_input_and_is_order_independent():
    with pytest.raises(AnalysisOpError, match="ANALYSIS_OP_INPUT_MISSING"):
        run_op("analysis.metric.tail_lift", _scored(50, 1), params={"score": "score", "label": "hit"})
    ref, rows = _scored(400, 7), _scored(300, 11)
    a = run_op("analysis.metric.tail_lift", rows, inputs={"reference": ref}, params={"score": "score", "label": "hit"})["payload"]
    b = run_op("analysis.metric.tail_lift", rows.sample(frac=1.0, random_state=3), inputs={"reference": ref.sample(frac=1.0, random_state=5)},
               params={"score": "score", "label": "hit"})["payload"]
    assert a == b and [c["quantile"] for c in a["cells"]] == [0.9, 0.95, 0.975]
    with pytest.raises(AnalysisOpError, match="ANALYSIS_TAIL_LIFT_QUANTILES_INVALID"):
        tail_lift(rows, reference=ref, score="score", label="hit", quantiles=[1.0])
