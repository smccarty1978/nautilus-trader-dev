import pandas as pd
import pytest

from research.analysis.first_p90_warning_horizon import (
    FirstP90AnalysisError, _anchors, _controls, _incidence, _negative, _score_summary, _subtypes,
)

NS = 1_000_000_000
THRESHOLDS = {"LONG": {"p90": .3, "p95": .4, "p97_5": .5}, "SHORT": {"p90": .3, "p95": .4, "p97_5": .5}}


def rows(*, terminal=180, reason="ACCEPTED_OPPOSING_FLIP", market="OBSERVED", score_status="OBSERVED", missing=()):
    base = 1704067200 * NS
    return pd.DataFrame([{"regime_start_ns": 1, "direction": "LONG", "anchor_ts": base, "scheduled_ts": base + offset * NS,
        "offset_s": offset, "score": None if offset in missing else (.2 if offset == 15 else .35), "score_valid": offset not in missing,
        "terminal_reason": reason, "terminal_ts": base + terminal * NS, "market_path_status": market,
        "score_path_status": score_status, "session_open_ts": base - 300 * NS, "regime_age_seconds": 300} for offset in (15, 30, 60, 90, 120)])


def test_inclusive_180_and_late_negative_denominators():
    anchor = _anchors(rows(), THRESHOLDS)
    assert _incidence(anchor)["populations"]["pooled"][2]["cumulative_count"] == 1
    late = _anchors(rows(terminal=240), THRESHOLDS)
    assert _negative(late)["negative_denominator"] == 1
    assert _negative(late)["rows"][0]["n"] == 1


def test_session_before_180_is_censor_not_negative_and_missing_score_censors_subtype():
    early = _anchors(rows(terminal=120, reason="RTH_CLOSE"), THRESHOLDS)
    assert _incidence(early)["populations"]["pooled"][2]["n"] == 0
    diagnostic = rows(terminal=600, reason="HORIZON_600S", missing=(30,))
    anchor = _anchors(diagnostic, THRESHOLDS)
    _, summary = _score_summary(anchor, diagnostic, THRESHOLDS)
    assert _subtypes(anchor, summary).iloc[0].warning_subtype == "SESSION_CENSORED"


def test_year_and_terminal_mismatch_fail_closed():
    bad = rows(); bad.loc[0, "anchor_ts"] = 1735689600 * NS
    with pytest.raises(FirstP90AnalysisError, match="YEAR"):
        from research.analysis.first_p90_warning_horizon import _validate
        _validate(bad)
    d = rows(); d.loc[1, "terminal_ts"] += NS
    with pytest.raises(FirstP90AnalysisError, match="TERMINAL"):
        from research.analysis.first_p90_warning_horizon import _validate
        _validate(d)


def test_controls_select_strictly_before_fire_and_never_fire():
    a = _anchors(rows(terminal=600, reason="HORIZON_600S"), THRESHOLDS)
    base = int(a.iloc[0].anchor_ts) + 600 * NS
    a = a.assign(anchor_ts=base, session_open_ts=base-300*NS)
    observations = pd.DataFrame([
        {"regime_start_ns": 1, "observation_ts": base-5*NS, "regime_age_seconds": 300, "session_open_ts": base-300*NS, "parent_long_score": .2, "parent_short_score": .2},
        {"regime_start_ns": 1, "observation_ts": base, "regime_age_seconds": 300, "session_open_ts": base-300*NS, "parent_long_score": .1, "parent_short_score": .1},
        {"regime_start_ns": 2, "observation_ts": base-5*NS, "regime_age_seconds": 300, "session_open_ts": base-300*NS, "parent_long_score": .2, "parent_short_score": .2},
    ])
    selected = _controls(a, observations, {"LONG":"parent_long_score", "SHORT":"parent_short_score"})["selected_controls"]
    assert any(x["kind"] == "firing" and x["score"] == .2 for x in selected)
    assert any(x["kind"] == "never_fire" for x in selected)
